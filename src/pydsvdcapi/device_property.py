"""Device property component for vdSD devices (§4.6.3, §4.6.4).

A :class:`DeviceProperty` models one generic device property on a
virtual device.  Unlike states, properties are not limited to a
fixed set of options — they may be of type *numeric*, *enumeration*,
or *string* and carry richer description metadata (type, min/max,
resolution, SI unit, …).

Each property owns two property groups visible to the vdSM:

* **devicePropertyDescriptions** — read-only invariable description
  (``name``, ``type``, ``min``, ``max``, ``resolution``, ``siunit``,
  ``options``, ``default``).  These are persisted.

* **deviceProperties** — read-write current values (``name``,
  ``value``).  Property values **are persisted**, unlike device states.

Value updates
~~~~~~~~~~~~~

The physical device reports changes via
:meth:`DeviceProperty.update_value`.  When the owning vdSD is
announced and a session is active, the library sends a
``VDC_SEND_PUSH_NOTIFICATION`` notification to the vdSM carrying the
``deviceProperties`` payload.

Persistence
~~~~~~~~~~~

Both description properties and current values are persisted (via the
owning Vdsd's property tree).

Usage::

    from pydsvdcapi.device_property import DeviceProperty

    prop = DeviceProperty(
        vdsd=my_vdsd,
        ds_index=0,
        name="batteryLevel",
        type="numeric",
        min_value=0.0,
        max_value=100.0,
        resolution=1.0,
        siunit="%",
        default=100.0,
    )
    my_vdsd.add_device_property(prop)

    # Later, when the hardware reports a value:
    await prop.update_value(85.0)
"""

from __future__ import annotations

import asyncio
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.conversion import apply_converter, compile_converter
from pydsvdcapi.property_handling import NO_VALUE, dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — valid property type strings
# ---------------------------------------------------------------------------

#: Numeric property type.
PROPERTY_TYPE_NUMERIC: str = "numeric"
#: Enumeration property type.
PROPERTY_TYPE_ENUMERATION: str = "enumeration"
#: String property type.
PROPERTY_TYPE_STRING: str = "string"

#: Set of all valid property type strings.
VALID_PROPERTY_TYPES = frozenset(
    {
        PROPERTY_TYPE_NUMERIC,
        PROPERTY_TYPE_ENUMERATION,
        PROPERTY_TYPE_STRING,
    }
)


class DeviceProperty:
    """One generic device property on a vdSD (§4.6.3 / §4.6.4).

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index of this property within the device (position
        in ``devicePropertyDescriptions`` / ``deviceProperties``).
    name:
        Property name (e.g. ``"batteryLevel"``).
    type:
        Data type identifier: ``"numeric"``, ``"enumeration"``, or
        ``"string"``.
    min_value:
        Optional minimum value (numeric only).
    max_value:
        Optional maximum value (numeric only).
    resolution:
        Optional resolution / LSB size (numeric only).
    siunit:
        Optional SI unit string, e.g. ``"°C"`` (numeric only).
    options:
        Optional option key → value mapping (enumeration only).
    default:
        Optional default value (all types).
    description:
        Optional human-readable description.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_type",
        "_min_value",
        "_max_value",
        "_resolution",
        "_siunit",
        "_options",
        "_default",
        "_description",
        "_value",
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
        type: str = PROPERTY_TYPE_STRING,
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
        siunit: str | None = None,
        options: dict[int | str, str] | None = None,
        default: float | str | None = None,
        description: str | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._type = type
        self._min_value = min_value
        self._max_value = max_value
        self._resolution = resolution
        self._siunit = siunit
        self._options: dict[int | str, str] | None = dict(options) if options else None
        self._default = default
        self._description = description
        # Current property value (persisted).
        self._value: float | str | None = None

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
        """Property name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def type(self) -> str:
        """Data type identifier (``"numeric"``, ``"enumeration"``, or
        ``"string"``)."""
        return self._type

    @type.setter
    def type(self, value: str) -> None:
        self._type = value

    @property
    def min_value(self) -> float | None:
        """Minimum value (numeric only)."""
        return self._min_value

    @min_value.setter
    def min_value(self, value: float | None) -> None:
        self._min_value = value

    @property
    def max_value(self) -> float | None:
        """Maximum value (numeric only)."""
        return self._max_value

    @max_value.setter
    def max_value(self, value: float | None) -> None:
        self._max_value = value

    @property
    def resolution(self) -> float | None:
        """Resolution / LSB size (numeric only)."""
        return self._resolution

    @resolution.setter
    def resolution(self, value: float | None) -> None:
        self._resolution = value

    @property
    def siunit(self) -> str | None:
        """SI unit string (numeric only)."""
        return self._siunit

    @siunit.setter
    def siunit(self, value: str | None) -> None:
        self._siunit = value

    @property
    def options(self) -> dict[int | str, str] | None:
        """Option key → value mapping (enumeration only, copy)."""
        return dict(self._options) if self._options is not None else None

    @options.setter
    def options(self, value: dict[int | str, str] | None) -> None:
        self._options = dict(value) if value is not None else None

    @property
    def default(self) -> float | str | None:
        """Default value."""
        return self._default

    @default.setter
    def default(self, value: float | str | None) -> None:
        self._default = value

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

        Applied in :meth:`update_value` before the value is
        type-converted and stored.  The snippet manipulates ``value``
        (the raw incoming value).  The library appends ``return value``
        automatically.

        Pass ``None`` to remove a previously set converter.

        Raises
        ------
        SyntaxError
            If the snippet cannot be compiled.

        Example
        -------
        ::

            prop.set_uplink_converter("value = round(float(value), 2)")
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

    # ---- volatile value accessor -------------------------------------

    @property
    def value(self) -> float | str | None:
        """Current property value (persisted)."""
        return self._value

    @value.setter
    def value(self, v: float | str | None) -> None:
        self._value = v
        if v is not None:
            self._initial_value_ready.set()

    # ---- property dicts ----------------------------------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return **devicePropertyDescriptions** properties (§4.6.3).

        Format::

            {"name": "battery", "type": "numeric",
             "min": 0.0, "max": 100.0, ...}

        The element name (dict key in the parent dict) IS the property
        identifier used by the dSS — it reads ``vdcProperty.getName()``.

        For enumeration properties, ``values`` is a label-keyed dict
        where each entry has no scalar value (``NO_VALUE``).  The dSS
        reads element names via ``vdcProperty["values"]`` /
        ``vdcValue.getName()``.
        """
        props: dict[str, Any] = {
            "name": self._name,
            "type": self._type,
        }
        # Numeric-specific optional fields.
        if self._type == PROPERTY_TYPE_NUMERIC:
            if self._min_value is not None:
                props["min"] = self._min_value
            if self._max_value is not None:
                props["max"] = self._max_value
            if self._resolution is not None:
                props["resolution"] = self._resolution
            if self._siunit is not None:
                props["siunit"] = self._siunit
        # Enumeration-specific: label-keyed elements with no scalar value.
        # dSS reads: vdcProperty["values"] → getName() per element.
        if self._type == PROPERTY_TYPE_ENUMERATION and self._options:
            props["values"] = {v: NO_VALUE for v in self._options.values()}
        # All-type optional fields.
        if self._default is not None:
            props["default"] = self._default
        if self._description is not None:
            props["description"] = self._description
        return props

    def get_value_properties(self) -> Any:
        """Return the **deviceProperties** value for this property.

        Format::

            scalar  (e.g. 85.0, "Auto", None)

        dSS reads ``vdcProperty.getValue()`` — the element's **own** scalar
        value (``PropertyElement.value``), NOT a nested sub-element.  So the
        value must be carried directly on the element, not inside a
        ``{"value": ...}`` child.

        Returns the raw Python scalar (``float``, ``str``, ``bool``, or
        ``None``).
        """
        return self._value

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence.

        Both description and current value are persisted.
        """
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "type": self._type,
        }
        if self._min_value is not None:
            node["minValue"] = self._min_value
        if self._max_value is not None:
            node["maxValue"] = self._max_value
        if self._resolution is not None:
            node["resolution"] = self._resolution
        if self._siunit is not None:
            node["siunit"] = self._siunit
        if self._options is not None:
            node["options"] = {str(k): v for k, v in self._options.items()}
        if self._default is not None:
            node["default"] = self._default
        if self._description is not None:
            node["description"] = self._description
        # Current value is also persisted.
        if self._value is not None:
            node["value"] = self._value
        if self._uplink_converter_code is not None:
            node["uplinkConverter"] = self._uplink_converter_code
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict."""
        if "name" in state:
            self._name = state["name"]
        if "type" in state:
            self._type = state["type"]
        if "minValue" in state:
            self._min_value = float(state["minValue"])
        if "maxValue" in state:
            self._max_value = float(state["maxValue"])
        if "resolution" in state:
            self._resolution = float(state["resolution"])
        if "siunit" in state:
            self._siunit = state["siunit"]
        if "options" in state:
            raw = state["options"]
            if isinstance(raw, dict):
                self._options = {_parse_option_key(k): v for k, v in raw.items()}
        if "default" in state:
            self._default = state["default"]
        if "description" in state:
            self._description = state.get("description")
        # Restore persisted value.
        if "value" in state:
            self._value = state["value"]
            self._initial_value_ready.set()
        # Converter
        if "uplinkConverter" in state:
            self.set_uplink_converter(state["uplinkConverter"])
        else:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None

    # ---- push to vdSM ------------------------------------------------

    async def update_value(
        self,
        value: float | int | str,
        session: VdcSession | None = None,
    ) -> None:
        """Update the property value and push the change to the vdSM.

        Parameters
        ----------
        value:
            The new property value.
        session:
            The session to send through.  When ``None``, the owning
            vdSD's current session is used.

        If no active session is available the value is still recorded
        locally, but the push is skipped with a warning.

        For numeric properties the value is stored as ``float``; for
        string and enumeration properties it is stored as ``str``.

        For enumeration properties an integer key is automatically
        resolved to the corresponding text label via the *options*
        dictionary, matching p44-vdc behaviour.
        """
        # Per §4.6.4 all property values are strings on the wire.
        # We keep numeric values as float internally for convenience
        # (min/max checks, arithmetic) but serialise as str.
        value = apply_converter(
            self._uplink_converter_fn,
            value,
            component_id=f"DeviceProperty[{self._ds_index}] '{self._name}'",
            direction="uplink",
        )
        if self._type == PROPERTY_TYPE_NUMERIC:
            self._value = float(value)
        elif self._type == PROPERTY_TYPE_ENUMERATION:
            self._value = self._resolve_enum_label(value)
        else:
            self._value = str(value)
        self._initial_value_ready.set()

        # Trigger auto-save since property values are persisted.
        self._vdsd._schedule_auto_save_if_enabled()

        session = session or self._vdsd._session
        if session is None or not session.is_active:
            logger.warning(
                "DeviceProperty[%d] '%s': cannot push — no active session for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
            return

        if not self._vdsd.is_announced:
            logger.debug(
                "DeviceProperty[%d] '%s': vdSD not announced — skipping push",
                self._ds_index,
                self._name,
            )
            return

        # Push direct scalar value (p44-vdc compatible).
        push_tree: dict[str, Any] = {
            "deviceProperties": {
                self._name: self._value,
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
                "DeviceProperty[%d] '%s': pushed value '%s' for vdSD %s",
                self._ds_index,
                self._name,
                self._value,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "DeviceProperty[%d] '%s': failed to push: %s",
                self._ds_index,
                self._name,
                exc,
            )

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DeviceProperty(ds_index={self._ds_index!r}, "
            f"name={self._name!r}, type={self._type!r}, "
            f"value={self._value!r})"
        )

    # ---- enum resolution ---------------------------------------------

    def _resolve_enum_label(self, value: float | int | str) -> str:
        """Resolve *value* to a string label for enumeration properties.

        p44-vdc always sends the text label for enumeration values.
        This method resolves:

        * ``int`` → label via options dictionary (key → label).
        * ``str`` that is an integer literal → lookup as int key.
        * ``str`` that matches an existing label → used directly.
        * fallback → ``str(value)``.
        """
        if self._options:
            # Integer key → label lookup.
            if isinstance(value, int) and not isinstance(value, bool):
                label = self._options.get(value)
                if label is not None:
                    return label
            elif isinstance(value, str):
                # Try as integer key first.
                try:
                    int_key = int(value)
                    label = self._options.get(int_key)
                    if label is not None:
                        return label
                except ValueError:
                    pass
                # Check if value is already a known label.
                if value in self._options.values():
                    return value
        return str(value)


def _parse_option_key(key: Any) -> int | str:
    """Convert a persisted option key back to int when possible."""
    if isinstance(key, int):
        return key
    try:
        return int(key)
    except (ValueError, TypeError):
        return str(key)
