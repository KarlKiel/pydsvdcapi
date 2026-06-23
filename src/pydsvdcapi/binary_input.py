"""Binary input component for vdSD devices.

A :class:`BinaryInput` models one binary (digital) sensor input on a
virtual device.  It owns three property groups visible to the vdSM:

* **binaryInputDescriptions** — read-only hardware characteristics
  (name, type, update interval, …).
* **binaryInputSettings** — writable configuration stored persistently
  (group, sensorFunction).
* **binaryInputStates** — volatile runtime state (value / extendedValue,
  age, error) that is **not** persisted.

State updates
~~~~~~~~~~~~~

The physical device feeds new values into the binary input via
:meth:`BinaryInput.update_value` (for ``bool`` state) or
:meth:`BinaryInput.update_extended_value` (for ``int`` state, e.g.
window handle positions).  When the vdSD is announced and a session
is active, the library automatically pushes a
``VDC_SEND_PUSH_NOTIFICATION`` notification to the vdSM carrying the
``binaryInputStates`` property change (§7.1.3).

Persistence
~~~~~~~~~~~

Only description and settings properties are persisted (via the owning
Vdsd's property tree → Device → Vdc → VdcHost YAML).  The runtime
state is transient by definition.

Usage::

    from pydsvdcapi.binary_input import BinaryInput
    from pydsvdcapi.enums import BinaryInputType, BinaryInputUsage

    bi = BinaryInput(
        vdsd=my_vdsd,
        ds_index=0,
        sensor_function=BinaryInputType.PRESENCE,
        input_usage=BinaryInputUsage.ROOM_CLIMATE,
        name="PIR Sensor",
    )
    my_vdsd.add_binary_input(bi)

    # Later, when the hardware reports a change:
    await bi.update_value(True, session)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.conversion import apply_converter, compile_converter
from pydsvdcapi.enums import BinaryInputType, BinaryInputUsage, InputError
from pydsvdcapi.property_handling import dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Input type identifiers for the ``inputType`` description property.
INPUT_TYPE_POLL_ONLY: int = 0
INPUT_TYPE_DETECTS_CHANGES: int = 1

#: Type alias for the binary-input-settings-changed callback.
#: ``async def callback(binary_input: BinaryInput, changed: dict[str, Any]) -> None``
BinaryInputSettingsChangedCallback = Callable[
    ["BinaryInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]


# ---------------------------------------------------------------------------
# BinaryInput
# ---------------------------------------------------------------------------


class BinaryInput:
    """One binary (digital) input on a vdSD.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd`.
    ds_index:
        Zero-based index among **all** binary inputs of this device.
        Must be unique within the device.
    sensor_function:
        The hardwired / configured sensor function (see
        :class:`~pydsvdcapi.enums.BinaryInputType`).
    input_type:
        ``0`` = poll-only, ``1`` = detects changes (default).
    input_usage:
        Usage context beyond the device colour group.
    group:
        dS group number (writable setting, persisted).
    name:
        Human-readable name or label for this input.
    update_interval:
        How fast the physical value is tracked, in seconds.
        ``0.0`` means "on change only" (instantaneous).
    hardwired_function:
        If the physical function is fixed in hardware, set this to the
        matching :class:`BinaryInputType` value.  Defaults to
        ``GENERIC`` (freely configurable).
    """

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        ds_index: int = 0,
        sensor_function: BinaryInputType = BinaryInputType.GENERIC,
        input_type: int = INPUT_TYPE_DETECTS_CHANGES,
        input_usage: BinaryInputUsage = BinaryInputUsage.UNDEFINED,
        group: int = 0,
        name: str = "",
        update_interval: float = 0.0,
        hardwired_function: BinaryInputType = BinaryInputType.GENERIC,
    ) -> None:
        # ---- parent reference ----------------------------------------
        self._vdsd: Vdsd = vdsd

        # ---- description properties (read-only, not persisted) -------
        self._ds_index: int = ds_index
        self._input_type: int = input_type
        self._input_usage: BinaryInputUsage = input_usage
        self._hardwired_function: BinaryInputType = hardwired_function
        self._name: str = name
        self._update_interval: float = update_interval

        # ---- settings properties (read/write, persisted) -------------
        self._group: int = group
        self._sensor_function: BinaryInputType = sensor_function

        # ---- state properties (volatile, NOT persisted) --------------
        self._value: bool | None = None
        self._extended_value: int | None = None
        self._age: float | None = None
        self._error: InputError = InputError.OK
        #: Monotonic timestamp of the last value update (for age calc).
        self._last_update: float | None = None

        # ---- session (stored by start_alive_timer for push fallback) -
        self._session: VdcSession | None = None
        self._on_settings_changed: BinaryInputSettingsChangedCallback | None = None

        # ---- value converter (optional, persisted) -------------------
        self._uplink_converter_code: str | None = None
        self._uplink_converter_fn: Callable[[Any], Any] | None = None

    # ---- read-only accessors -----------------------------------------

    @property
    def ds_index(self) -> int:
        """Zero-based index (``dsIndex``)."""
        return self._ds_index

    @property
    def input_type(self) -> int:
        """``0`` = poll-only, ``1`` = detects changes."""
        return self._input_type

    @property
    def input_usage(self) -> BinaryInputUsage:
        """Usage context of the input."""
        return self._input_usage

    @property
    def hardwired_function(self) -> BinaryInputType:
        """Hardwired function if not freely configurable."""
        return self._hardwired_function

    @property
    def name(self) -> str:
        """Human-readable label for this input."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def update_interval(self) -> float:
        """Physical tracking interval in seconds."""
        return self._update_interval

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
    def sensor_function(self) -> BinaryInputType:
        """Configured sensor function (writable, persisted)."""
        return self._sensor_function

    @sensor_function.setter
    def sensor_function(self, value: BinaryInputType | int) -> None:
        self._sensor_function = BinaryInputType(int(value))
        self._schedule_auto_save()

    # ---- converter management ---------------------------------------

    def set_uplink_converter(self, code: str | None) -> None:
        """Set or clear the uplink value converter.

        The converter snippet is a block of Python code that
        manipulates the pre-bound variable ``value`` (the raw incoming
        binary input value).  The library appends ``return value``
        automatically — no return statement is needed.  The same
        converter is applied to both boolean updates
        (:meth:`update_value`) and integer extended-value updates
        (:meth:`update_extended_value`).

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
        Invert a boolean input::

            bi.set_uplink_converter("value = not value")

        Map integer extended value::

            bi.set_uplink_converter(\"\"\"
            if isinstance(value, int):
                value = value > 0
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

    # ---- state accessors (volatile) ----------------------------------

    @property
    def value(self) -> bool | None:
        """Current boolean value (``None`` = unknown)."""
        return self._value

    @property
    def extended_value(self) -> int | None:
        """Current extended (integer) value (``None`` = unknown).

        When set, this takes precedence over :attr:`value`.
        """
        return self._extended_value

    @property
    def age(self) -> float | None:
        """Seconds since the last value update (``None`` = unknown)."""
        if self._last_update is None:
            return None
        return time.monotonic() - self._last_update

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
        value: bool | None,
        session: VdcSession | None = None,
    ) -> None:
        """Set the boolean value and push a state notification.

        Parameters
        ----------
        value:
            ``True`` = active, ``False`` = inactive, ``None`` = unknown.
        session:
            Active session to send the push notification on.  If
            ``None`` or the vdSD is not announced, the value is stored
            locally but no push is sent.
        """
        value = apply_converter(
            self._uplink_converter_fn,
            value,
            component_id=f"BinaryInput[{self._ds_index}] '{self._name}'",
            direction="uplink",
        )
        self._value = value
        self._extended_value = None  # bool takes precedence
        self._last_update = time.monotonic()
        logger.debug(
            "BinaryInput[%d] '%s' value → %s",
            self._ds_index,
            self._name,
            value,
        )
        await self._push_state(session or self._session)

    async def update_extended_value(
        self,
        value: int | None,
        session: VdcSession | None = None,
    ) -> None:
        """Set the extended (integer) value and push a state notification.

        Parameters
        ----------
        value:
            Integer state (e.g. window handle position: 0=closed,
            1=open, 2=tilted).  ``None`` = unknown.
        session:
            Active session to send the push notification on.
        """
        value = apply_converter(
            self._uplink_converter_fn,
            value,
            component_id=f"BinaryInput[{self._ds_index}] '{self._name}'",
            direction="uplink",
        )
        self._extended_value = value
        self._value = None  # extended takes precedence
        self._last_update = time.monotonic()
        logger.debug(
            "BinaryInput[%d] '%s' extendedValue → %s",
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
            "BinaryInput[%d] '%s' error → %s",
            self._ds_index,
            self._name,
            self._error.name,
        )
        await self._push_state(session or self._session)

    # ---- property dicts (for getProperty responses) ------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return the ``binaryInputDescriptions[N]`` property dict.

        These are read-only hardware characteristics.
        """
        return {
            "name": self._name,
            "dsIndex": self._ds_index,
            "inputType": self._input_type,
            "inputUsage": int(self._input_usage),
            "sensorFunction": int(self._hardwired_function),
            "updateInterval": self._update_interval,
        }

    def get_settings_properties(self) -> dict[str, Any]:
        """Return the ``binaryInputSettings[N]`` property dict.

        These are read/write, persisted.
        """
        return {
            "group": self._group,
            "sensorFunction": int(self._sensor_function),
        }

    def get_state_properties(self) -> dict[str, Any]:
        """Return the ``binaryInputStates[N]`` property dict.

        These are read-only volatile state.
        """
        state: dict[str, Any] = {}

        # Prefer extendedValue over value when set.
        if self._extended_value is not None:
            state["extendedValue"] = self._extended_value
        else:
            state["value"] = self._value  # may be None (NULL)

        state["age"] = self.age  # may be None (NULL)
        state["error"] = int(self._error)
        return state

    # ---- settings mutation (called from vdc_host setProperty) --------

    def apply_settings(self, incoming: dict[str, Any]) -> None:
        """Apply writable settings from a ``setProperty`` request.

        Parameters
        ----------
        incoming:
            Dict of setting name → value (e.g.
            ``{"group": 2, "sensorFunction": 5}``).
        """
        changed = False
        if "group" in incoming:
            self._group = int(incoming["group"])
            changed = True
        if "sensorFunction" in incoming:
            self._sensor_function = BinaryInputType(int(incoming["sensorFunction"]))
            changed = True
        if changed:
            logger.debug(
                "BinaryInput[%d] settings updated: group=%d, sensorFunction=%s",
                self._ds_index,
                self._group,
                self._sensor_function.name,
            )
            self._schedule_auto_save()

    @property
    def on_settings_changed(self) -> BinaryInputSettingsChangedCallback | None:
        """Callback invoked when the vdSM writes ``binaryInputSettings``."""
        return self._on_settings_changed

    @on_settings_changed.setter
    def on_settings_changed(
        self, callback: BinaryInputSettingsChangedCallback | None
    ) -> None:
        self._on_settings_changed = callback

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the persisted representation of this binary input.

        Only description and settings properties are included (state
        is volatile and not persisted).
        """
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "inputType": self._input_type,
            "inputUsage": int(self._input_usage),
            "hardwiredFunction": int(self._hardwired_function),
            "updateInterval": self._update_interval,
            # Settings (writable)
            "group": self._group,
            "sensorFunction": int(self._sensor_function),
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
        if "inputType" in state:
            self._input_type = int(state["inputType"])
        if "inputUsage" in state:
            self._input_usage = BinaryInputUsage(int(state["inputUsage"]))
        if "hardwiredFunction" in state:
            self._hardwired_function = BinaryInputType(int(state["hardwiredFunction"]))
        if "updateInterval" in state:
            self._update_interval = float(state["updateInterval"])
        # Settings
        if "group" in state:
            self._group = int(state["group"])
        if "sensorFunction" in state:
            self._sensor_function = BinaryInputType(int(state["sensorFunction"]))
        # Converter
        if "uplinkConverter" in state:
            self.set_uplink_converter(state["uplinkConverter"])
        else:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None

    # ---- push notification -------------------------------------------

    async def _push_state(
        self,
        session: VdcSession | None,
        *,
        force: bool = False,
    ) -> None:
        """Push current state to the vdSM.

        Parameters
        ----------
        session:
            Session to push on.  ``None`` → no push.
        force:
            If ``True``, bypass throttling (unused for BinaryInput,
            accepted for compatibility with SensorInput and vdsd.py).
        """
        if session is None:
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "BinaryInput[%d]: vdSD not announced — skipping push",
                self._ds_index,
            )
            return

        state_dict = self.get_state_properties()

        push_tree: dict[str, Any] = {
            "binaryInputStates": {
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
            logger.debug(
                "BinaryInput[%d] '%s': pushed state %s for vdSD %s",
                self._ds_index,
                self._name,
                state_dict,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "BinaryInput[%d] '%s': failed to push state: %s",
                self._ds_index,
                self._name,
                exc,
            )

    async def push_settings(self, session: VdcSession | None = None) -> None:
        """Push the current ``binaryInputSettings`` to the vdSM.

        Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
        ``binaryInputSettings`` subtree for this input.  A no-op if no
        session is active or the vdSD is not announced.
        """
        session = session or self._session
        if session is None:
            logger.debug(
                "BinaryInput[%d]: no active session — skipping push_settings",
                self._ds_index,
            )
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "BinaryInput[%d]: vdSD not announced — skipping push_settings",
                self._ds_index,
            )
            return

        settings_dict = self.get_settings_properties()
        push_tree: dict[str, Any] = {
            "binaryInputSettings": {str(self._ds_index): settings_dict}
        }

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "BinaryInput[%d] '%s': pushed settings for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "BinaryInput[%d] '%s': failed to push settings: %s",
                self._ds_index,
                self._name,
                exc,
            )

    # ---- session management ------------------------------------------

    def start_alive_timer(self, session: VdcSession) -> None:
        """Store the session for push fallback.

        Called when the vdSD is announced.  Stores *session* so that
        :meth:`update_value` can push without an explicit session
        argument.

        .. note::

            The method name is kept for interface compatibility with
            :class:`~pydsvdcapi.sensor_input.SensorInput` and
            :class:`~pydsvdcapi.button_input.ButtonInput`.
        """
        self._session = session

    def stop_alive_timer(self) -> None:
        """Clear the stored session.

        Called when the vdSD vanishes or the session disconnects.
        """
        self._session = None

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
            f"BinaryInput(ds_index={self._ds_index}, "
            f"name={self._name!r}, "
            f"function={self._sensor_function.name})"
        )
