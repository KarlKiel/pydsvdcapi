# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Device state component for vdSD devices (§4.6.1, §4.6.2).

A :class:`DeviceState` models one discrete device state on a virtual
device.  States differ from properties in that they carry a limited
number of possible values (``options``), whereas properties are
more generic.

Each state owns two property groups visible to the vdSM:

* **deviceStateDescriptions** — read-only invariable descriptive
  properties (``name``, ``options``, ``description``).
  These are persisted so the vdSM can query them after a restart.

* **deviceStates** — volatile runtime state (``name``, ``value``).
  State values are **not** persisted — they are transient.

State updates
~~~~~~~~~~~~~

The physical device reports changes via :meth:`DeviceState.update_value`.
When the owning vdSD is announced and a session is active, the library
automatically sends a ``VDC_SEND_PUSH_NOTIFICATION`` notification to the
vdSM carrying the ``deviceStates`` payload.

Persistence
~~~~~~~~~~~

Only description properties (``name``, ``options``, ``description``)
are persisted (via the owning Vdsd's property tree).  The runtime
state value is transient by definition.

Usage::

    from pydsvdcapi.device_state import DeviceState

    st = DeviceState(
        vdsd=my_vdsd,
        ds_index=0,
        name="operatingState",
        options={0: "Off", 1: "Initializing", 2: "Running", 3: "Shutdown"},
        description="Current operating state of the device",
    )
    my_vdsd.add_device_state(st)

    # Later, when the hardware reports a state change:
    await st.update_value(2)  # Running
    # Text labels are also accepted and auto-resolved:
    await st.update_value("Running")  # → resolved to key 2
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.conversion import apply_converter, compile_converter
from pydsvdcapi.property_handling import NO_VALUE, dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


class DeviceState:
    """One discrete device state on a vdSD (§4.6.1 / §4.6.2).

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index of this state within the device
        (position in ``deviceStateDescriptions`` / ``deviceStates``).
    name:
        State name (e.g. ``"operatingState"``).
    options:
        Dictionary of option-id → label pairs, e.g.
        ``{0: "Off", 1: "Running"}``.  Keys are integers or strings;
        values are human-readable labels.
    description:
        Optional human-readable description of the state.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_options",
        "_description",
        "_value",
        "_last_update",
        "_last_change",
        "_uplink_converter_code",
        "_uplink_converter_fn",
        "_initial_value_ready",
    )

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        options: dict[int | str, str] | None = None,
        description: str | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._options: dict[int | str, str] = dict(options) if options else {}
        self._description = description
        # Volatile runtime state (NOT persisted).
        # Stored as the integer option key (matching Sonos/dSS
        # internal representation where stateValue is integer).
        self._value: int | None = None
        # Timestamps for age/changed reporting (monotonic seconds).
        self._last_update: float | None = None
        self._last_change: float | None = None

        # ---- value converter (optional, persisted) -------------------
        self._uplink_converter_code: str | None = None
        self._uplink_converter_fn: Callable[[Any], Any] | None = None

        # Set when the first real (non-None) value has been received.
        self._initial_value_ready: asyncio.Event = asyncio.Event()

    # ---- read-only accessors -----------------------------------------

    @property
    def vdsd(self) -> Vdsd:
        """The owning vdSD."""
        return self._vdsd

    @property
    def ds_index(self) -> int:
        """Numeric index within the device."""
        return self._ds_index

    # ---- configurable properties -------------------------------------

    @property
    def name(self) -> str:
        """State name (e.g. ``"operatingState"``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def options(self) -> dict[int | str, str]:
        """Option-id → label dictionary (copy)."""
        return dict(self._options)

    @options.setter
    def options(self, value: dict[int | str, str]) -> None:
        self._options = dict(value)

    @property
    def description(self) -> str | None:
        """Optional human-readable description."""
        return self._description

    @description.setter
    def description(self, value: str | None) -> None:
        self._description = value

    # ---- converter management ---------------------------------------

    def set_uplink_converter(self, code: str | None) -> None:
        """Set or clear the uplink value converter.

        Applied in :meth:`update_value` before the value is resolved
        against the options dictionary.  The snippet manipulates
        ``value`` (the raw incoming int or str).  The library appends
        ``return value`` automatically.

        Pass ``None`` to remove a previously set converter.

        Raises
        ------
        SyntaxError
            If the snippet cannot be compiled.

        Example
        -------
        ::

            st.set_uplink_converter(\"\"\"
            mapping = {"STOPPED": 0, "PLAYING": 2}
            value = mapping.get(str(value), 0)
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

    # ---- volatile state accessors ------------------------------------

    @property
    def value(self) -> int | None:
        """Current state value as integer option key (volatile, not persisted)."""
        return self._value

    @value.setter
    def value(self, v: int | str | None) -> None:
        """Set state value.

        Accepts:
        - ``int`` — used directly as the option key.
        - ``str`` — first tries ``int(v)``; if that fails, performs a
          reverse lookup in *options* to find the matching key for the
          text label.  Raises ``ValueError`` if the label is unknown.
        - ``None`` — clears the value.
        """
        old = self._value
        self._value = self._resolve_value(v)
        if self._value is not None:
            now = time.monotonic()
            self._last_update = now
            if old != self._value:
                self._last_change = now
            self._initial_value_ready.set()

    # ---- value resolution --------------------------------------------

    def _resolve_value(
        self,
        v: int | str | None,
    ) -> int | None:
        """Resolve *v* to an integer option key.

        * ``None`` → ``None``
        * ``int`` → returned as-is
        * ``str`` that is an integer literal → ``int(v)``
        * ``str`` that matches an option label → corresponding key
        * otherwise → ``ValueError``
        """
        if v is None:
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, str):
            # Try numeric parse first.
            try:
                return int(v)
            except ValueError:
                pass
            # Reverse lookup: label → key.
            for key, label in self._options.items():
                if label == v:
                    return int(key) if not isinstance(key, int) else key
            raise ValueError(
                f"DeviceState '{self._name}': unknown option label "
                f"{v!r}; valid labels: "
                f"{list(self._options.values())}"
            )
        raise TypeError(
            f"DeviceState '{self._name}': expected int, str, or None, "
            f"got {type(v).__name__}"
        )

    # ---- property dicts ----------------------------------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return **deviceStateDescriptions** properties (§4.6.1).

        Format::

            {"name": "operatingState",
             "value": {"values": {"Off": NO_VALUE, "Running": NO_VALUE}},
             "description": "..."}  # optional

        The dSS reads enum option labels from element *names* under
        ``value/values`` via ``VdcElementReader`` (calling
        ``vdcValue.getName()`` for each child element).  Each element
        carries no scalar value (``NO_VALUE``); the element name IS
        the option label.
        """
        props: dict[str, Any] = {
            "name": self._name,
        }
        # Enum options as name-keyed elements with no scalar value.
        # dSS reads: vdcState["value"]["values"] → getName() per element.
        props["value"] = {"values": {v: NO_VALUE for v in self._options.values()}}
        if self._description is not None:
            props["description"] = self._description
        return props

    def _value_as_label(self) -> str | None:
        """Return the current value as a string label.

        The vDC API specification requires the text label (e.g. ``"Running"``) for
        enumeration state values, not the integer key.  This method
        performs the key → label lookup.

        Returns ``None`` when no value is set.
        """
        if self._value is None:
            return None
        label = self._options.get(self._value)
        if label is not None:
            return label
        # Fallback: convert integer to string if label not found.
        return str(self._value)

    def get_state_properties(self) -> dict[str, Any]:
        """Return **deviceStates** properties (current value, §4.6.2).

        Format::

            {"name": "operatingState", "value": "Running"}

        ``name`` is the state name (matching the description).
        ``value`` is the text label (e.g. ``"Running"``) matching
        the enumeration options in the description, serialised as
        ``v_string`` on the wire.
        """
        return {
            "name": self._name,
            "value": self._value_as_label(),
        }

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence.

        Only description properties are persisted — the runtime state
        value is volatile.
        """
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
        }
        if self._options:
            # Store as list of {"id": ..., "label": ...} for YAML safety.
            node["options"] = {str(k): v for k, v in self._options.items()}
        if self._description is not None:
            node["description"] = self._description
        if self._uplink_converter_code is not None:
            node["uplinkConverter"] = self._uplink_converter_code
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict (descriptions only)."""
        if "name" in state:
            self._name = state["name"]
        if "options" in state:
            raw = state["options"]
            if isinstance(raw, dict):
                self._options = {_parse_option_key(k): v for k, v in raw.items()}
            elif isinstance(raw, list):
                # Legacy format: list of {"id": ..., "label": ...}
                self._options = {
                    _parse_option_key(item["id"]): item["label"]
                    for item in raw
                    if "id" in item and "label" in item
                }
        if "description" in state:
            self._description = state.get("description")
        # Converter
        if "uplinkConverter" in state:
            self.set_uplink_converter(state["uplinkConverter"])
        else:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None

    # ---- push to vdSM ------------------------------------------------

    async def update_value(
        self,
        value: int | str,
        session: VdcSession | None = None,
    ) -> None:
        """Update the state value and push the change to the vdSM.

        Parameters
        ----------
        value:
            The new state value.  Accepts an integer option key or a
            text label (which is resolved via the options dictionary).
        session:
            The session to send through.  When ``None``, the owning
            vdSD's current session is used.

        If no active session is available the value is still recorded
        locally, but the push is skipped with a warning.
        """
        old = self._value
        self._value = self._resolve_value(
            apply_converter(
                self._uplink_converter_fn,
                value,
                component_id=f"DeviceState[{self._ds_index}] '{self._name}'",
                direction="uplink",
            )
        )
        if self._value is not None:
            now = time.monotonic()
            self._last_update = now
            if old != self._value:
                self._last_change = now
            self._initial_value_ready.set()

        session = session or self._vdsd._session
        if session is None or not session.is_active:
            logger.warning(
                "DeviceState[%d] '%s': cannot push — no active session for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
            return

        if not self._vdsd.is_announced:
            logger.debug(
                "DeviceState[%d] '%s': vdSD not announced — skipping push",
                self._ds_index,
                self._name,
            )
            return

        state_dict = self.get_state_properties()
        push_tree: dict[str, Any] = {
            "deviceStates": {
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
                "DeviceState[%d] '%s': pushed value '%s' for vdSD %s",
                self._ds_index,
                self._name,
                self._value,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "DeviceState[%d] '%s': failed to push: %s",
                self._ds_index,
                self._name,
                exc,
            )

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DeviceState(ds_index={self._ds_index!r}, "
            f"name={self._name!r}, value={self._value!r})"
        )


def _parse_option_key(key: Any) -> int | str:
    """Convert a persisted option key back to int when possible."""
    if isinstance(key, int):
        return key
    try:
        return int(key)
    except (ValueError, TypeError):
        return str(key)
