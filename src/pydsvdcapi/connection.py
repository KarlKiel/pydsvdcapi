# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Low-level TCP connection with length-prefixed protobuf framing.

The vDC API transport is a TCP stream where every message is preceded by
a **2-byte big-endian length header** (max 16 384 bytes) followed by a
serialized ``Message`` protobuf.

This module provides :class:`VdcConnection` which wraps an
:mod:`asyncio` ``StreamReader`` / ``StreamWriter`` pair and exposes
``send`` / ``receive`` coroutines that operate on typed protobuf
``Message`` objects.

Usage::

    conn = VdcConnection(reader, writer)
    msg = await conn.receive()   # returns Message or None on EOF
    await conn.send(response)
    await conn.close()
"""

from __future__ import annotations

import asyncio
import logging
import struct

from google.protobuf.message import DecodeError

from pydsvdcapi import vdc_messages_pb2 as pb

logger = logging.getLogger(__name__)

#: Maximum payload length the protocol allows (2-byte header → 16 384).
MAX_MESSAGE_LENGTH: int = 16_384

#: ``struct`` format for the 2-byte big-endian length header.
_HEADER_FMT = "!H"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class VdcConnection:
    """Framing layer for a single vDC API TCP connection.

    Parameters
    ----------
    reader:
        The :class:`asyncio.StreamReader` (read side of the socket).
    writer:
        The :class:`asyncio.StreamWriter` (write side of the socket).
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False

    # ---- properties --------------------------------------------------

    @property
    def is_closed(self) -> bool:
        """``True`` when the connection has been closed."""
        return self._closed

    @property
    def peername(self) -> str:
        """Remote address as a human-readable string."""
        try:
            info = self._writer.get_extra_info("peername")
            if info:
                return f"{info[0]}:{info[1]}"
        except Exception:  # noqa: BLE001
            pass
        return "<unknown>"

    # ---- send --------------------------------------------------------

    async def send(self, msg: pb.Message) -> None:
        """Serialize *msg* and write it to the socket.

        Raises
        ------
        ConnectionError
            If the socket has been closed.
        ValueError
            If the serialized message exceeds :data:`MAX_MESSAGE_LENGTH`.
        """
        if self._closed:
            raise ConnectionError("Connection is closed")

        payload = msg.SerializeToString()
        length = len(payload)
        if length > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Message too large: {length} bytes (max {MAX_MESSAGE_LENGTH})"
            )

        header = struct.pack(_HEADER_FMT, length)
        self._writer.write(header + payload)
        await self._writer.drain()

        logger.debug(
            "Sent %s (%d bytes, msg_id=%d) → %s",
            pb.Type.Name(msg.type),
            length,
            msg.message_id,
            self.peername,
        )

    # ---- receive -----------------------------------------------------

    async def receive(self) -> pb.Message | None:
        """Read and deserialize the next message from the socket.

        Returns
        -------
        Message or None
            The parsed protobuf ``Message``, or ``None`` when the
            remote end has closed the connection (EOF).

        Raises
        ------
        ConnectionError
            If the connection was already closed locally.
        ValueError
            If the received length header exceeds
            :data:`MAX_MESSAGE_LENGTH` or the payload cannot be parsed.
        asyncio.IncompleteReadError
            If the peer closes the connection mid-message (propagates from
            ``StreamReader.readexactly``).
        """
        if self._closed:
            raise ConnectionError("Connection is closed")

        # --- read the 2-byte length header ----------------------------
        header_data = await self._reader.readexactly(_HEADER_SIZE)
        (length,) = struct.unpack(_HEADER_FMT, header_data)
        if length > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Received message length {length} exceeds maximum "
                f"({MAX_MESSAGE_LENGTH})"
            )
        if length == 0:
            raise ValueError("Received zero-length message")

        # --- read the protobuf payload --------------------------------
        payload = await self._reader.readexactly(length)

        msg = pb.Message()
        try:
            msg.ParseFromString(payload)
        except DecodeError as exc:
            raise ValueError(f"Failed to parse protobuf message: {exc}") from exc

        logger.debug(
            "Received %s (%d bytes, msg_id=%d) ← %s",
            pb.Type.Name(msg.type),
            length,
            msg.message_id,
            self.peername,
        )
        return msg

    # ---- close -------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying TCP socket.

        Safe to call multiple times.  Also signals EOF on the reader so
        that any pending :meth:`receive` call is unblocked — this
        mirrors real socket behaviour where ``transport.close()`` causes
        the protocol's ``connection_lost()`` to signal the reader.
        """
        if self._closed:
            return
        self._closed = True
        # Unblock any pending receive by feeding EOF to our own reader.
        try:
            if not self._reader.at_eof():
                self._reader.feed_eof()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        logger.debug("Connection to %s closed", self.peername)

    # ---- dunder ------------------------------------------------------

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"VdcConnection({self.peername}, {state})"
