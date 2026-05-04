"""vDC session — protocol state machine for a vdSM ↔ vDC host session.

A :class:`VdcSession` wraps a :class:`~pydsvdcapi.connection.VdcConnection`
and implements the session lifecycle defined by the vDC API:

1. **Initialisation** — The vdSM sends a ``hello`` request; the vDC host
   validates the API version and responds with its own dSUID (or an
   error).
2. **Operation** — The session handles ``ping`` / ``pong`` keep-alive
   and dispatches other incoming messages (property access, scene
   notifications, etc.) to registered callbacks.
3. **Termination** — The session ends on ``bye``, a new ``hello``,
   connection loss, or an explicit :meth:`close`.

Message ID handling
~~~~~~~~~~~~~~~~~~~

The vDC API uses an incrementing message-ID scheme:

* **Requests** carry a ``message_id > 0``.  The response echoes the
  same ID so the sender can correlate request and response.
* **Notifications** use ``message_id = 0`` — no response is expected.
* Both sides track the *last known* message ID (the maximum of all IDs
  received or sent).  The next outgoing request uses
  ``last_known + 1``.

Use :meth:`VdcSession.send_request` for outgoing method calls that
expect a ``GENERIC_RESPONSE`` (e.g. ``announcedevice``,
``announcevdc``, ``vanish``).  Use :meth:`VdcSession.send_notification`
for fire-and-forget messages (e.g. ``pushProperty``, ``pong``).

Usage (typically managed by :class:`~pydsvdcapi.vdc_host.VdcHost`)::

    session = VdcSession(
        connection=conn,
        host_dsuid=str(host.dsuid),
        on_message=my_handler,
    )
    await session.run()  # blocks until session ends
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Awaitable, Callable

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import VdcConnection

logger = logging.getLogger(__name__)

#: The API version implemented by this library.
SUPPORTED_API_VERSION: int = 2


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class SessionState(enum.Enum):
    """State of a :class:`VdcSession`."""

    AWAITING_HELLO = enum.auto()
    """Waiting for the vdSM to send a ``hello`` request."""

    ACTIVE = enum.auto()
    """Session is established and operational."""

    CLOSED = enum.auto()
    """Session has been terminated."""


# ---------------------------------------------------------------------------
# Callback type
# ---------------------------------------------------------------------------

#: Signature for the message callback.
#:
#: Called for every incoming message *after* the hello handshake that is
#: not handled internally (i.e. not ping or bye).  The callback receives
#: the session and the raw ``Message`` protobuf and may return an
#: optional ``Message`` response.
MessageCallback = Callable[
    ["VdcSession", pb.Message],
    Awaitable[pb.Message | None],
]

#: Signature for the hello-completed callback.
#:
#: Called when the hello handshake completes and the session transitions
#: to ``ACTIVE``.  The callback receives the session and may perform
#: async work (e.g. re-announcing vDCs and devices).  It is scheduled
#: via :func:`asyncio.create_task` so it does not block the session
#: message loop.
HelloCallback = Callable[
    ["VdcSession"],
    Awaitable[None],
]


# ---------------------------------------------------------------------------
# VdcSession
# ---------------------------------------------------------------------------


class VdcSession:
    """Manages the protocol state for one vdSM ↔ vDC host session.

    Parameters
    ----------
    connection:
        The low-level :class:`VdcConnection` to use.
    host_dsuid:
        The dSUID of this vDC host (34-hex-character string).
    on_message:
        Async callback invoked for every operational message that is not
        handled internally.  May be ``None`` in which case unhandled
        messages are silently ignored.
    """

    def __init__(
        self,
        connection: VdcConnection,
        host_dsuid: str,
        on_message: MessageCallback | None = None,
        on_hello: HelloCallback | None = None,
    ) -> None:
        self._conn = connection
        self._host_dsuid = host_dsuid
        self._on_message = on_message
        self._on_hello = on_hello

        self._state = SessionState.AWAITING_HELLO
        self._vdsm_dsuid: str | None = None
        self._api_version: int | None = None

        # The *last known* message ID is the maximum of all IDs we have
        # received or sent.  The next outgoing request will use
        # ``_last_known_id + 1``.
        self._last_known_id: int = 0

        # Pending outgoing requests awaiting a correlated response.
        # Maps message_id → Future that will be resolved when the
        # response arrives.
        self._pending_requests: dict[int, asyncio.Future[pb.Message]] = {}

        # Ping/pong counter.
        self._ping_count: int = 0

    # ---- public properties -------------------------------------------

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    @property
    def vdsm_dsuid(self) -> str | None:
        """The dSUID of the connected vdSM (``None`` before hello)."""
        return self._vdsm_dsuid

    @property
    def api_version(self) -> int | None:
        """API version negotiated during hello (``None`` before hello)."""
        return self._api_version

    @property
    def connection(self) -> VdcConnection:
        """The underlying :class:`VdcConnection`."""
        return self._conn

    @property
    def is_active(self) -> bool:
        """``True`` while the session is in the ``ACTIVE`` state."""
        return self._state is SessionState.ACTIVE

    @property
    def last_known_message_id(self) -> int:
        """The highest message ID seen (received or sent) so far."""
        return self._last_known_id

    @property
    def ping_count(self) -> int:
        """Number of ping/pong exchanges completed in this session."""
        return self._ping_count

    # ---- message-ID helpers ------------------------------------------

    def _next_message_id(self) -> int:
        """Allocate and return the next outgoing message ID."""
        self._last_known_id += 1
        return self._last_known_id

    def _track_message_id(self, msg_id: int) -> None:
        """Update *_last_known_id* if *msg_id* is higher."""
        if msg_id > self._last_known_id:
            self._last_known_id = msg_id

    # ---- main loop ---------------------------------------------------

    async def run(self) -> None:
        """Run the session until it ends.

        This coroutine reads messages in a loop, dispatches them to the
        appropriate handler, and returns when the session terminates
        (bye, connection loss, or :meth:`close`).
        """
        logger.info("Session started for connection from %s", self._conn.peername)
        try:
            while self._state is not SessionState.CLOSED:
                try:
                    msg = await self._conn.receive()
                except asyncio.IncompleteReadError:
                    logger.info(
                        "Connection from %s closed (incomplete read)",
                        self._conn.peername,
                    )
                    break
                except (ConnectionError, ValueError) as exc:
                    logger.warning(
                        "Connection error from %s: %s",
                        self._conn.peername,
                        exc,
                    )
                    break

                if msg is None:
                    logger.info(
                        "Connection from %s closed (EOF)",
                        self._conn.peername,
                    )
                    break

                await self._dispatch(msg)

        finally:
            self._state = SessionState.CLOSED
            # Cancel all pending outgoing requests.
            for future in self._pending_requests.values():
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()
            await self._conn.close()
            logger.info(
                "Session ended for %s (vdSM %s)",
                self._conn.peername,
                self._vdsm_dsuid or "<unknown>",
            )

    # ---- close -------------------------------------------------------

    async def close(self) -> None:
        """Terminate the session and close the connection."""
        self._state = SessionState.CLOSED
        # Cancel all pending outgoing requests.
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        await self._conn.close()

    # ---- message dispatch --------------------------------------------

    async def _dispatch(self, msg: pb.Message) -> None:
        """Route an incoming message to the appropriate handler."""
        msg_type = msg.type

        # Track the incoming message ID for the incrementing counter.
        self._track_message_id(msg.message_id)

        # --- GENERIC_RESPONSE: correlate to a pending outgoing request
        if msg_type == pb.GENERIC_RESPONSE and msg.message_id > 0:
            future = self._pending_requests.pop(msg.message_id, None)
            if future is not None and not future.done():
                future.set_result(msg)
                return
            # No pending request found — fall through to callback.

        # --- hello (allowed in any state except CLOSED) ---------------
        if msg_type == pb.VDSM_REQUEST_HELLO:
            await self._handle_hello(msg)
            return

        # --- before hello, reject everything else ---------------------
        if self._state is SessionState.AWAITING_HELLO:
            logger.warning(
                "Received %s before hello — ignoring",
                pb.Type.Name(msg_type),
            )
            await self._send_error(
                msg,
                pb.ERR_SERVICE_NOT_AVAILABLE,
                "Session not initialised — send hello first",
            )
            return

        # --- ping → pong ---------------------------------------------
        if msg_type == pb.VDSM_SEND_PING:
            await self._handle_ping(msg)
            return

        # --- bye → acknowledge and end --------------------------------
        if msg_type == pb.VDSM_SEND_BYE:
            await self._handle_bye(msg)
            return

        # --- everything else → user callback --------------------------
        if self._on_message is not None:
            try:
                response = await self._on_message(self, msg)
                if response is not None:
                    await self._conn.send(response)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Error in message callback for %s",
                    pb.Type.Name(msg_type),
                )
                await self._send_error(
                    msg,
                    pb.ERR_MESSAGE_UNKNOWN,
                    "Internal error processing message",
                )
        else:
            logger.debug("No handler for %s — ignoring", pb.Type.Name(msg_type))

    # ---- hello -------------------------------------------------------

    async def _handle_hello(self, msg: pb.Message) -> None:
        """Process a ``VDSM_REQUEST_HELLO``."""
        hello = msg.vdsm_request_hello
        vdsm_dsuid = hello.dSUID
        api_version = hello.api_version

        logger.info(
            "Hello from vdSM %s (API v%d) via %s",
            vdsm_dsuid,
            api_version,
            self._conn.peername,
        )

        # Check API version compatibility.
        if api_version < SUPPORTED_API_VERSION:
            logger.warning(
                "Incompatible API version %d (need >= %d)",
                api_version,
                SUPPORTED_API_VERSION,
            )
            await self._send_error(
                msg,
                pb.ERR_INCOMPATIBLE_API,
                f"Incompatible API version {api_version} "
                f"(need >= {SUPPORTED_API_VERSION})",
            )
            self._state = SessionState.CLOSED
            return

        # If we were already active, this is an implicit re-hello from
        # the same vdSM (the spec says a new Hello implicitly
        # terminates the old session — we just reset).
        if self._state is SessionState.ACTIVE:
            logger.info("Re-hello — resetting session")

        self._vdsm_dsuid = vdsm_dsuid
        self._api_version = api_version
        self._state = SessionState.ACTIVE

        # Build the hello response.
        response = pb.Message()
        response.type = pb.VDC_RESPONSE_HELLO
        response.message_id = msg.message_id
        response.vdc_response_hello.dSUID = self._host_dsuid
        await self._conn.send(response)

        logger.info("Session established with vdSM %s", vdsm_dsuid)

        # Notify the host that the session is ready.  The callback is
        # scheduled as a separate task so that it does not block the
        # session message loop (the callback typically re-announces
        # vDCs and devices, which requires sending requests and waiting
        # for responses dispatched by this same loop).
        if self._on_hello is not None:
            asyncio.create_task(
                self._invoke_on_hello(),
                name=f"on_hello-{vdsm_dsuid}",
            )

    async def _invoke_on_hello(self) -> None:
        """Wrapper that invokes *_on_hello* with error handling."""
        assert self._on_hello is not None  # guarded by caller
        try:
            await self._on_hello(self)
        except Exception:  # noqa: BLE001
            logger.exception("Error in on_hello callback")

    # ---- ping / pong -------------------------------------------------

    async def _handle_ping(self, msg: pb.Message) -> None:
        """Respond to a ``VDSM_SEND_PING`` with a ``VDC_SEND_PONG``."""
        target_dsuid = msg.vdsm_send_ping.dSUID
        self._ping_count += 1

        logger.info(
            "Ping #%d for %s — sending pong",
            self._ping_count,
            target_dsuid,
        )

        pong = pb.Message()
        pong.type = pb.VDC_SEND_PONG
        pong.message_id = 0  # pong is a notification, no msg_id
        pong.vdc_send_pong.dSUID = target_dsuid or self._host_dsuid
        await self._conn.send(pong)

    # ---- bye ---------------------------------------------------------

    async def _handle_bye(self, msg: pb.Message) -> None:
        """Handle a ``VDSM_SEND_BYE`` — acknowledge and close."""
        logger.info("Bye from vdSM %s", self._vdsm_dsuid)

        # Send a GenericResponse acknowledging the bye.
        response = pb.Message()
        response.type = pb.GENERIC_RESPONSE
        response.message_id = msg.message_id
        response.generic_response.code = pb.ERR_OK
        await self._conn.send(response)

        self._state = SessionState.CLOSED

    # ---- helpers -----------------------------------------------------

    async def _send_error(
        self,
        request: pb.Message,
        code: int,
        description: str,
    ) -> None:
        """Send a ``GENERIC_RESPONSE`` error for *request*."""
        response = pb.Message()
        response.type = pb.GENERIC_RESPONSE
        response.message_id = request.message_id
        response.generic_response.code = code  # type: ignore[assignment]  # protobuf accepts int for enum fields at runtime
        response.generic_response.description = description

        try:
            await self._conn.send(response)
        except (ConnectionError, OSError):
            logger.debug("Could not send error response — connection lost")

    async def send_request(
        self,
        msg: pb.Message,
        *,
        timeout: float | None = 30.0,
    ) -> pb.Message:
        """Send a request and wait for the correlated response.

        Automatically assigns the next ``message_id`` according to the
        incrementing-ID scheme (``last_known + 1``).  Returns the
        correlated response message (typically a ``GENERIC_RESPONSE``).

        Use this for outgoing method calls like ``announcedevice``,
        ``announcevdc``, or ``vanish``.

        Parameters
        ----------
        msg:
            The protobuf ``Message`` to send.  ``message_id`` will be
            overwritten.
        timeout:
            Maximum seconds to wait for the response.  ``None`` means
            wait indefinitely.

        Returns
        -------
        Message
            The correlated response from the vdSM.

        Raises
        ------
        ConnectionError
            If the session is not active.
        asyncio.TimeoutError
            If the response does not arrive within *timeout*.
        """
        if self._state is not SessionState.ACTIVE:
            raise ConnectionError(f"Cannot send — session is {self._state.name}")

        msg_id = self._next_message_id()
        msg.message_id = msg_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future[pb.Message] = loop.create_future()
        self._pending_requests[msg_id] = future

        try:
            await self._conn.send(msg)
            if timeout is not None:
                return await asyncio.wait_for(future, timeout)
            return await future
        except Exception:
            self._pending_requests.pop(msg_id, None)
            raise

    async def send_notification(self, msg: pb.Message) -> None:
        """Send a notification (no response expected, ``message_id = 0``).

        Use this for fire-and-forget messages such as ``pushProperty``,
        ``pong``, etc.

        Raises
        ------
        ConnectionError
            If the session is not active.
        """
        if self._state is not SessionState.ACTIVE:
            raise ConnectionError(f"Cannot send — session is {self._state.name}")
        msg.message_id = 0
        await self._conn.send(msg)

    async def send_message(self, msg: pb.Message) -> None:
        """Send an arbitrary message over this session's connection.

        This is the low-level send that does **not** assign or modify
        ``message_id``.  Prefer :meth:`send_request` (for method calls
        expecting a response) or :meth:`send_notification` (for
        fire-and-forget messages).

        Raises
        ------
        ConnectionError
            If the session is not active.
        """
        if self._state is not SessionState.ACTIVE:
            raise ConnectionError(f"Cannot send — session is {self._state.name}")
        # Track the ID so the counter stays consistent.
        if msg.message_id > 0:
            self._track_message_id(msg.message_id)
        await self._conn.send(msg)

    # ---- dunder ------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"VdcSession(state={self._state.name}, "
            f"vdsm={self._vdsm_dsuid!r}, peer={self._conn.peername})"
        )
