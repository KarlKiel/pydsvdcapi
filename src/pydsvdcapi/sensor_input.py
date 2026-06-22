"""Sensor input component for vdSD devices.

A :class:`SensorInput` models one analogue (continuous-value) sensor on
a virtual device.  It owns three property groups visible to the vdSM:

* **sensorDescriptions** — read-only hardware characteristics
  (name, type, usage, min/max/resolution, update interval, …).
* **sensorSettings** — writable configuration stored persistently
  (group, minPushInterval, changesOnlyInterval).
* **sensorStates** — volatile runtime state (value, age, contextId,
  contextMsg, error) that is **not** persisted.

State updates
~~~~~~~~~~~~~

The physical device feeds new readings into the sensor via
:meth:`SensorInput.update_value`.  When the vdSD is announced and a
session is active, the library automatically pushes a
``VDC_SEND_PUSH_NOTIFICATION`` notification to the vdSM carrying the
``sensorStates`` property change (§7.1.3).

Push throttling
~~~~~~~~~~~~~~~

Two settings control push frequency:

* **minPushInterval** — minimum seconds between consecutive pushes.
  Rapid value changes within this window are coalesced into one
  deferred push.  Default is ``2.0`` seconds for sensors.
* **changesOnlyInterval** — minimum seconds between pushes of the
  *same* value.  Hardware re-reports of an unchanged reading are
  suppressed within this window.

Alive signalling
~~~~~~~~~~~~~~~~

When :attr:`SensorInput.alive_sign_interval` is non-zero the library
automatically re-pushes the current state at that interval as a
heartbeat.  If no push (neither from a value change nor from the alive
timer) reaches the vdSM within ``aliveSignInterval`` seconds, the
sensor should be considered out of order.  Timers are started
automatically when the owning vdSD is announced and stopped on vanish
or session disconnect.

Persistence
~~~~~~~~~~~

Only description and settings properties are persisted (via the owning
Vdsd's property tree → Device → Vdc → VdcHost YAML).  The runtime
state is transient by definition.

Usage::

    from pydsvdcapi.sensor_input import SensorInput
    from pydsvdcapi.enums import SensorType, SensorUsage

    si = SensorInput(
        vdsd=my_vdsd,
        ds_index=0,
        sensor_type=SensorType.TEMPERATURE,
        sensor_usage=SensorUsage.ROOM,
        name="Room Temperature",
        min_value=-20.0,
        max_value=60.0,
        resolution=0.1,
    )
    my_vdsd.add_sensor_input(si)

    # Later, when the hardware reports a reading:
    await si.update_value(21.5, session)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.conversion import apply_converter, compile_converter
from pydsvdcapi.enums import (
    InputError,
    SensorType,
    SensorUsage,
    validate_sensor_type_usage,
)
from pydsvdcapi.property_handling import dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: Type alias for the sensor-input-settings-changed callback.
#: ``async def callback(sensor_input: SensorInput, changed: dict[str, Any]) -> None``
SensorInputSettingsChangedCallback = Callable[
    ["SensorInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]

# ---------------------------------------------------------------------------
# SensorInput
# ---------------------------------------------------------------------------


class SensorInput:
    """One analogue (continuous-value) sensor on a vdSD.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd`.
    ds_index:
        Zero-based index among **all** sensor inputs of this device.
        Must be unique within the device.
    sensor_type:
        The physical quantity the sensor measures (see
        :class:`~pydsvdcapi.enums.SensorType`).  **Required** — always
        provide an explicit type; ``SensorType.NONE`` is not a valid
        choice for a deployed sensor.
    sensor_usage:
        Usage context beyond the device colour group.
    group:
        dS group number (writable setting, persisted).
    name:
        Human-readable name or label for this sensor.
    min_value:
        Minimum value the sensor can report.  **Required** — the API
        does not define a useful default; always specify this.
    max_value:
        Maximum value the sensor can report.  **Required** — same
        rationale as *min_value*.
    resolution:
        LSB size / resolution of the actual hardware sensor.
        **Required** — a value of ``0.0`` carries no useful information.
    update_interval:
        How fast the physical value is tracked, in seconds.
        ``0.0`` means "on change only" (instantaneous).
    alive_sign_interval:
        Maximum seconds between pushes before the sensor is considered
        out of order.  When non-zero the library re-pushes state
        automatically.  ``0.0`` disables alive signalling (default).
    min_push_interval:
        Minimum seconds between consecutive push notifications.
        Rapid value changes within this window are coalesced.
        Default is ``2.0`` seconds for sensors.
    changes_only_interval:
        Minimum seconds between pushes of unchanged values.  ``0.0``
        means every hardware update triggers a push (default).
    """

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        sensor_type: SensorType,
        min_value: float,
        max_value: float,
        resolution: float,
        ds_index: int = 0,
        sensor_usage: SensorUsage = SensorUsage.UNDEFINED,
        group: int = 0,
        name: str = "",
        update_interval: float = 0.0,
        alive_sign_interval: float = 0.0,
        min_push_interval: float = 2.0,
        changes_only_interval: float = 0.0,
    ) -> None:
        validate_sensor_type_usage(sensor_type, sensor_usage)
        self._init(
            vdsd=vdsd,
            ds_index=ds_index,
            sensor_type=sensor_type,
            sensor_usage=sensor_usage,
            group=group,
            name=name,
            min_value=min_value,
            max_value=max_value,
            resolution=resolution,
            update_interval=update_interval,
            alive_sign_interval=alive_sign_interval,
            min_push_interval=min_push_interval,
            changes_only_interval=changes_only_interval,
        )

    def _init(
        self,
        *,
        vdsd: Vdsd,
        ds_index: int,
        sensor_type: SensorType,
        sensor_usage: SensorUsage,
        group: int,
        name: str,
        min_value: float,
        max_value: float,
        resolution: float,
        update_interval: float,
        alive_sign_interval: float,
        min_push_interval: float,
        changes_only_interval: float,
    ) -> None:
        # ---- parent reference ----------------------------------------
        self._vdsd: Vdsd = vdsd

        # ---- description properties (read-only) ----------------------
        self._ds_index: int = ds_index
        self._sensor_type: SensorType = sensor_type
        self._sensor_usage: SensorUsage = sensor_usage
        self._name: str = name
        self._min_value: float = min_value
        self._max_value: float = max_value
        self._resolution: float = resolution
        self._update_interval: float = update_interval
        self._alive_sign_interval: float = alive_sign_interval

        # ---- settings properties (read/write, persisted) -------------
        self._group: int = group
        self._min_push_interval: float = min_push_interval
        self._changes_only_interval: float = changes_only_interval

        # ---- state properties (volatile, NOT persisted) --------------
        self._value: float | None = None
        self._age: float | None = None
        self._context_id: int | None = None
        self._context_msg: str | None = None
        self._error: InputError = InputError.OK
        #: Monotonic timestamp of the last value update (for age calc).
        self._last_update: float | None = None

        # Set when the first real (non-None) value has been received.
        self._initial_value_ready: asyncio.Event = asyncio.Event()

        # ---- push throttling / alive timer state ---------------------
        self._session: VdcSession | None = None
        self._on_settings_changed: SensorInputSettingsChangedCallback | None = None
        self._last_push_time: float | None = None
        self._last_pushed_state: tuple | None = None
        self._alive_timer_handle: asyncio.TimerHandle | None = None
        self._deferred_push_handle: asyncio.TimerHandle | None = None

        # ---- value converter (optional, persisted) -------------------
        self._uplink_converter_code: str | None = None
        self._uplink_converter_fn: Callable[[Any], Any] | None = None

    @classmethod
    def _restore(cls, *, vdsd: Vdsd, ds_index: int) -> SensorInput:
        """Create a bare instance for persistence restoration.

        Intended for **internal use only** by the persistence layer.
        The caller **must** immediately call ``_apply_state()`` to fill
        in the description fields (sensor_type, min, max, resolution, …)
        before the object is used in any other way.
        """
        inst: SensorInput = cls.__new__(cls)
        inst._init(
            vdsd=vdsd,
            ds_index=ds_index,
            sensor_type=SensorType.NONE,
            sensor_usage=SensorUsage.UNDEFINED,
            group=0,
            name="",
            min_value=0.0,
            max_value=0.0,
            resolution=0.0,
            update_interval=0.0,
            alive_sign_interval=0.0,
            min_push_interval=2.0,
            changes_only_interval=0.0,
        )
        return inst

    # ---- converter management ---------------------------------------

    def set_uplink_converter(self, code: str | None) -> None:
        """Set or clear the uplink value converter.

        The converter snippet is a block of Python code that
        manipulates the pre-bound variable ``value`` (the raw incoming
        sensor reading).  The library appends ``return value``
        automatically — no return statement is needed.

        Pass ``None`` to remove a previously set converter.

        Parameters
        ----------
        code:
            Python snippet string, or ``None`` to clear.

        Raises
        ------
        SyntaxError
            If the snippet cannot be compiled.

        Examples
        --------
        Simple scaling::

            si.set_uplink_converter("value = (value - 32.0) * 5.0 / 9.0")

        Multi-line::

            si.set_uplink_converter(\"\"\"
            if value is None:
                value = 0.0
            else:
                value = round(float(value) / 10.0, 1)
            \"\"\")
        """
        if code is None:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None
        else:
            self._uplink_converter_fn = compile_converter(code)
            self._uplink_converter_code = code

    @property
    def uplink_converter_code(self) -> str | None:
        """The stored uplink converter snippet, or ``None``."""
        return self._uplink_converter_code

    # ---- read-only accessors -----------------------------------------

    @property
    def ds_index(self) -> int:
        """Zero-based index (``dsIndex``)."""
        return self._ds_index

    @property
    def sensor_type(self) -> SensorType:
        """Physical quantity the sensor measures."""
        return self._sensor_type

    @property
    def sensor_usage(self) -> SensorUsage:
        """Usage context of the sensor."""
        return self._sensor_usage

    @property
    def name(self) -> str:
        """Human-readable label for this sensor."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def min_value(self) -> float:
        """Minimum value the sensor can report."""
        return self._min_value

    @property
    def max_value(self) -> float:
        """Maximum value the sensor can report."""
        return self._max_value

    @property
    def resolution(self) -> float:
        """Resolution (LSB size) of the hardware sensor."""
        return self._resolution

    @property
    def update_interval(self) -> float:
        """Physical tracking interval in seconds."""
        return self._update_interval

    @property
    def alive_sign_interval(self) -> float:
        """Maximum expected interval between pushes in seconds.

        If no push happens within this interval, the vdSM may
        consider the sensor out of order.  ``0.0`` means no alive
        signalling.
        """
        return self._alive_sign_interval

    @property
    def vdsd(self) -> Vdsd:
        """The owning :class:`Vdsd`."""
        return self._vdsd

    # ---- settings accessors (writable, persisted) --------------------

    @property
    def group(self) -> int:
        """dS group number (writable, persisted)."""
        return self._group

    @group.setter
    def group(self, value: int) -> None:
        self._group = int(value)
        self._schedule_auto_save()

    @property
    def min_push_interval(self) -> float:
        """Minimum seconds between consecutive pushes (writable, persisted).

        Default ``2.0`` for sensors.
        """
        return self._min_push_interval

    @min_push_interval.setter
    def min_push_interval(self, value: float) -> None:
        self._min_push_interval = float(value)
        self._schedule_auto_save()

    @property
    def changes_only_interval(self) -> float:
        """Minimum seconds between pushes of unchanged values (writable, persisted).

        Default ``0.0`` means every hardware update triggers a push
        regardless of whether the value changed.
        """
        return self._changes_only_interval

    @changes_only_interval.setter
    def changes_only_interval(self, value: float) -> None:
        self._changes_only_interval = float(value)
        self._schedule_auto_save()

    # ---- state accessors (volatile) ----------------------------------

    @property
    def value(self) -> float | None:
        """Current sensor value (``None`` = unknown)."""
        return self._value

    @property
    def age(self) -> float | None:
        """Seconds since the last value update (``None`` = unknown)."""
        if self._last_update is None:
            return None
        return time.monotonic() - self._last_update

    @property
    def context_id(self) -> int | None:
        """Numerical context ID (``None`` = unavailable)."""
        return self._context_id

    @property
    def context_msg(self) -> str | None:
        """Text context message (``None`` = unavailable)."""
        return self._context_msg

    @property
    def error(self) -> InputError:
        """Current error status."""
        return self._error

    @error.setter
    def error(self, value: InputError | int) -> None:
        self._error = InputError(int(value))

    # ---- state update (called by the physical device) ----------------

    async def update_value(
        self,
        value: float | None,
        session: VdcSession | None = None,
        *,
        context_id: int | None = None,
        context_msg: str | None = None,
    ) -> None:
        """Set the sensor value and push a state notification.

        Parameters
        ----------
        value:
            Sensor reading in the unit defined by :attr:`sensor_type`.
            ``None`` = unknown.
        session:
            Active session to send the push notification on.  If
            ``None`` or the vdSD is not announced, the value is stored
            locally but no push is sent.
        context_id:
            Optional numerical context ID to include in the push.
        context_msg:
            Optional text context message to include in the push.
        """
        value = apply_converter(
            self._uplink_converter_fn,
            value,
            component_id=f"SensorInput[{self._ds_index}] '{self._name}'",
            direction="uplink",
        )
        self._value = value
        if value is not None:
            self._initial_value_ready.set()
        self._last_update = time.monotonic()
        if context_id is not None:
            self._context_id = context_id
        if context_msg is not None:
            self._context_msg = context_msg
        logger.debug(
            "SensorInput[%d] '%s' value → %s",
            self._ds_index,
            self._name,
            value,
        )
        await self._push_state(session or self._session)

    async def update_error(
        self,
        error: InputError | int,
        session: VdcSession | None = None,
    ) -> None:
        """Set the error status and push a state notification.

        Parameters
        ----------
        error:
            Updated error code.
        session:
            Active session to send the push notification on.
        """
        self._error = InputError(int(error))
        logger.debug(
            "SensorInput[%d] '%s' error → %s",
            self._ds_index,
            self._name,
            self._error.name,
        )
        await self._push_state(session or self._session)

    # ---- property dicts (for getProperty responses) ------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return the ``sensorDescriptions[N]`` property dict.

        These are read-only hardware characteristics.
        """
        return {
            "name": self._name,
            "dsIndex": self._ds_index,
            "sensorType": int(self._sensor_type),
            "sensorUsage": int(self._sensor_usage),
            "min": self._min_value,
            "max": self._max_value,
            "resolution": self._resolution,
            "updateInterval": self._update_interval,
            "aliveSignInterval": self._alive_sign_interval,
        }

    def get_settings_properties(self) -> dict[str, Any]:
        """Return the ``sensorSettings[N]`` property dict.

        These are read/write, persisted.
        """
        return {
            "group": self._group,
            "minPushInterval": self._min_push_interval,
            "changesOnlyInterval": self._changes_only_interval,
        }

    def get_state_properties(self) -> dict[str, Any]:
        """Return the ``sensorStates[N]`` property dict.

        These are read-only volatile state.
        """
        state: dict[str, Any] = {}
        state["value"] = self._value  # may be None (NULL)
        state["age"] = self.age  # may be None (NULL)

        if self._context_id is not None:
            state["contextId"] = self._context_id
        if self._context_msg is not None:
            state["contextMsg"] = self._context_msg

        state["error"] = int(self._error)
        return state

    # ---- settings mutation (called from vdc_host setProperty) --------

    def apply_settings(self, incoming: dict[str, Any]) -> None:
        """Apply writable settings from a ``setProperty`` request.

        Parameters
        ----------
        incoming:
            Dict of setting name → value (e.g.
            ``{"group": 2, "minPushInterval": 5.0}``).
        """
        changed = False
        if "group" in incoming:
            self._group = int(incoming["group"])
            changed = True
        if "minPushInterval" in incoming:
            self._min_push_interval = float(incoming["minPushInterval"])
            changed = True
        if "changesOnlyInterval" in incoming:
            self._changes_only_interval = float(incoming["changesOnlyInterval"])
            changed = True
        if changed:
            logger.debug(
                "SensorInput[%d] settings updated: group=%d, "
                "minPushInterval=%.1f, changesOnlyInterval=%.1f",
                self._ds_index,
                self._group,
                self._min_push_interval,
                self._changes_only_interval,
            )
            self._schedule_auto_save()

    @property
    def on_settings_changed(self) -> SensorInputSettingsChangedCallback | None:
        """Callback invoked when the vdSM writes ``sensorSettings``."""
        return self._on_settings_changed

    @on_settings_changed.setter
    def on_settings_changed(self, callback: SensorInputSettingsChangedCallback | None) -> None:
        self._on_settings_changed = callback

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the persisted representation of this sensor input.

        Only description and settings properties are included (state
        is volatile and not persisted).
        """
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "sensorType": int(self._sensor_type),
            "sensorUsage": int(self._sensor_usage),
            "min": self._min_value,
            "max": self._max_value,
            "resolution": self._resolution,
            "updateInterval": self._update_interval,
            "aliveSignInterval": self._alive_sign_interval,
            # Settings (writable)
            "group": self._group,
            "minPushInterval": self._min_push_interval,
            "changesOnlyInterval": self._changes_only_interval,
        }
        if self._uplink_converter_code is not None:
            node["uplinkConverter"] = self._uplink_converter_code
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted property tree dict.

        Restores both description and settings properties.  State
        properties are left at their defaults (unknown / OK).
        """
        if "dsIndex" in state:
            self._ds_index = int(state["dsIndex"])
        if "name" in state:
            self._name = state["name"]
        if "sensorType" in state:
            self._sensor_type = SensorType(int(state["sensorType"]))
        if "sensorUsage" in state:
            self._sensor_usage = SensorUsage(int(state["sensorUsage"]))
        if "min" in state:
            self._min_value = float(state["min"])
        if "max" in state:
            self._max_value = float(state["max"])
        if "resolution" in state:
            self._resolution = float(state["resolution"])
        if "updateInterval" in state:
            self._update_interval = float(state["updateInterval"])
        if "aliveSignInterval" in state:
            self._alive_sign_interval = float(state["aliveSignInterval"])
        # Settings
        if "group" in state:
            self._group = int(state["group"])
        if "minPushInterval" in state:
            self._min_push_interval = float(state["minPushInterval"])
        if "changesOnlyInterval" in state:
            self._changes_only_interval = float(state["changesOnlyInterval"])
        # Converter
        if "uplinkConverter" in state:
            self.set_uplink_converter(state["uplinkConverter"])
        else:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None

    # ---- push notification -------------------------------------------

    def _current_state_key(self) -> tuple:
        """Return a hashable key representing the current value state.

        Used by ``changesOnlyInterval`` to detect unchanged values.
        """
        return (self._value,)

    async def _push_state(
        self,
        session: VdcSession | None,
        *,
        force: bool = False,
    ) -> None:
        """Push current state, respecting throttling.

        Parameters
        ----------
        session:
            Session to push on.  ``None`` → no push.
        force:
            If ``True``, bypass ``minPushInterval`` and
            ``changesOnlyInterval`` throttling (used by the alive
            timer).
        """
        if session is None:
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "SensorInput[%d]: vdSD not announced — skipping push",
                self._ds_index,
            )
            return

        now = time.monotonic()
        current_key = self._current_state_key()

        if not force and self._last_push_time is not None:
            elapsed = now - self._last_push_time

            # changesOnlyInterval: suppress same-value pushes.
            if (
                self._changes_only_interval > 0
                and current_key == self._last_pushed_state
                and elapsed < self._changes_only_interval
            ):
                logger.debug(
                    "SensorInput[%d]: same value within "
                    "changesOnlyInterval (%.1fs) — skipping push",
                    self._ds_index,
                    self._changes_only_interval,
                )
                return

            # minPushInterval: rate-limit pushes.
            if self._min_push_interval > 0 and elapsed < self._min_push_interval:
                delay = self._min_push_interval - elapsed
                logger.debug(
                    "SensorInput[%d]: within minPushInterval — deferring push by %.2fs",
                    self._ds_index,
                    delay,
                )
                self._schedule_deferred_push(session, delay)
                return

        await self._do_push(session)

    async def _do_push(self, session: VdcSession) -> None:
        """Send the ``VDC_SEND_PUSH_NOTIFICATION`` notification.

        This is the low-level push that always sends, updating
        internal tracking state (last push time, last value key,
        alive timer reschedule).
        """
        state_dict = self.get_state_properties()

        push_tree: dict[str, Any] = {
            "sensorStates": {
                str(self._ds_index): state_dict,
            }
        }

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            self._last_push_time = time.monotonic()
            self._last_pushed_state = self._current_state_key()
            logger.debug(
                "SensorInput[%d] '%s': pushed state %s for vdSD %s",
                self._ds_index,
                self._name,
                state_dict,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "SensorInput[%d] '%s': failed to push state: %s",
                self._ds_index,
                self._name,
                exc,
            )

        # (Re-)schedule the alive timer after every push attempt.
        self._reschedule_alive_timer()

    async def push_settings(self, session: VdcSession | None = None) -> None:
        """Push the current ``sensorSettings`` to the vdSM.

        Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
        ``sensorSettings`` subtree for this sensor input.  A no-op if no
        session is active or the vdSD is not announced.
        """
        session = session or self._session
        if session is None:
            logger.debug(
                "SensorInput[%d]: no active session — skipping push_settings",
                self._ds_index,
            )
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "SensorInput[%d]: vdSD not announced — skipping push_settings",
                self._ds_index,
            )
            return

        settings_dict = self.get_settings_properties()
        push_tree: dict[str, Any] = {
            "sensorSettings": {str(self._ds_index): settings_dict}
        }

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "SensorInput[%d] '%s': pushed settings for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "SensorInput[%d] '%s': failed to push settings: %s",
                self._ds_index,
                self._name,
                exc,
            )

    # ---- deferred push (minPushInterval rate limiting) ---------------

    def _schedule_deferred_push(self, session: VdcSession, delay: float) -> None:
        """Schedule a push to fire after *delay* seconds.

        Replaces any previously scheduled deferred push.
        """
        self._cancel_deferred_push()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._deferred_push_handle = loop.call_later(
            delay,
            self._on_deferred_push_fired,
            session,
        )

    def _cancel_deferred_push(self) -> None:
        """Cancel any pending deferred push."""
        if self._deferred_push_handle is not None:
            self._deferred_push_handle.cancel()
            self._deferred_push_handle = None

    def _on_deferred_push_fired(self, session: VdcSession) -> None:
        """Callback for :meth:`_schedule_deferred_push`."""
        self._deferred_push_handle = None
        if self._vdsd.is_announced:
            asyncio.create_task(self._do_push(session))

    # ---- alive timer (periodic heartbeat push) -----------------------

    def start_alive_timer(self, session: VdcSession) -> None:
        """Begin periodic alive re-pushes.

        Called when the vdSD is announced.  Stores *session* so the
        alive timer can push state autonomously.

        If :attr:`alive_sign_interval` is ``0`` the timer is not
        started (but the session is still stored so that
        ``update_value()`` can push without an explicit session).
        """
        self._session = session
        self._reschedule_alive_timer()

    def stop_alive_timer(self) -> None:
        """Stop periodic alive re-pushes and cancel pending pushes.

        Called when the vdSD vanishes or the session disconnects.
        """
        self._cancel_alive_timer()
        self._cancel_deferred_push()
        self._session = None

    def _reschedule_alive_timer(self) -> None:
        """(Re-)schedule the alive timer.

        After each push the timer is reset so it fires only when
        no other push occurs within :attr:`alive_sign_interval`
        seconds.
        """
        self._cancel_alive_timer()
        interval = self._alive_sign_interval
        if interval <= 0 or self._session is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._alive_timer_handle = loop.call_later(
            interval,
            self._on_alive_timer_fired,
        )

    def _cancel_alive_timer(self) -> None:
        """Cancel the alive timer if running."""
        if self._alive_timer_handle is not None:
            self._alive_timer_handle.cancel()
            self._alive_timer_handle = None

    def _on_alive_timer_fired(self) -> None:
        """Callback: alive interval elapsed without a push."""
        self._alive_timer_handle = None
        session = self._session
        if session is not None and self._vdsd.is_announced:
            logger.debug(
                "SensorInput[%d] '%s': alive timer fired — re-pushing state",
                self._ds_index,
                self._name,
            )
            asyncio.create_task(self._push_state(session, force=True))

    # ---- auto-save ---------------------------------------------------

    def _schedule_auto_save(self) -> None:
        """Trigger a debounced auto-save up through the Vdsd → Device
        → Vdc → VdcHost chain."""
        device = getattr(self._vdsd, "_device", None)
        if device is not None:
            device._schedule_auto_save()

    # ---- dunder ------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SensorInput(ds_index={self._ds_index}, "
            f"name={self._name!r}, "
            f"type={self._sensor_type.name})"
        )
