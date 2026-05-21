"""Output channel component for vdSD devices.

An :class:`OutputChannel` represents one controllable dimension of a
device's single :class:`~pydsvdcapi.output.Output` — for example
*brightness*, *hue*, *shade position* or *heating power*.

Each output can own **one or more** channels.  The set of channels
depends on the output's :pyattr:`~pydsvdcapi.output.Output.function`:

======================  ===================================================
Output function          Required channels
======================  ===================================================
ON_OFF (0)               brightness
DIMMER (1)               brightness
POSITIONAL (2)           device-dependent (shades, valves, …) — add manually
DIMMER_COLOR_TEMP (3)    brightness, colortemp
FULL_COLOR_DIMMER (4)    brightness, hue, saturation, colortemp, cieX, cieY
BIPOLAR (5)              device-dependent — add manually
INTERNALLY_CTRL (6)      device-dependent — add manually
======================  ===================================================

For functions 0/1/3/4 the :class:`~pydsvdcapi.output.Output` auto-
creates the required channels.  For 2/5/6 the integrator must add them
via :meth:`Output.add_channel`.

Bidirectional value flow
~~~~~~~~~~~~~~~~~~~~~~~~

Channel values can change from **two** directions:

1. **vdSM → device** (``setOutputChannelValue`` notification, §7.3.9):
   The vdSM sets a value that the vDC must apply to the hardware.
   This is always forwarded to the device immediately via the
   ``on_channel_applied`` callback on the :class:`Output`.

2. **device → vdSM** (local change → ``pushProperty``, §7.1.3):
   When the device-side code calls :meth:`OutputChannel.update_value`,
   the new value is stored and — if ``pushChanges`` is set on the
   owning output — a ``VDC_SEND_PUSH_NOTIFICATION`` is sent to the vdSM.

``apply_now`` buffering (§7.3.9)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When the vdSM sends multiple ``setOutputChannelValue`` notifications
for the same device, only the last one (with ``apply_now=True`` or
omitted) triggers the hardware callback.  Previous values are buffered
on the channel until that point.

Age tracking
~~~~~~~~~~~~

Like sensors, each channel tracks the *age* of its value — i.e. how
many seconds ago the value was last applied / confirmed by the device.
``age`` is ``None`` when a new value has been set by the vdSM but not
yet confirmed by the hardware.

Property exposure
~~~~~~~~~~~~~~~~~

Three property sub-trees at the vdSD level (§4.1.3), each represented
as a **single** ``PropertyElement`` whose children are keyed by the
channel's **name** (e.g. ``"brightness"``, ``"colortemp"``):

* **channelDescriptions** — read-only metadata (name, channelType,
  dsIndex, min, max, resolution).
* **channelSettings** — currently empty (no per-channel settings
  defined in the spec).
* **channelStates** — ``value`` and ``age``.  Must **not** be written
  via ``setProperty``; use ``setOutputChannelValue`` instead.

.. important::

   dSS identifies channels by their **name**, not by their numeric
   ``dsIndex``.  All three property sub-trees must therefore use the
   channel name as the element key.  The ``setOutputChannelValue``
   notification from dSS also carries the name in the ``channelId``
   field (API v3 onwards).

Persistence
~~~~~~~~~~~

Channel *descriptions* are persisted (which channels exist, their
types and ds-indices).  Channel *values* (state) are volatile and NOT
persisted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi.conversion import apply_converter, compile_converter
from pydsvdcapi.enums import OutputChannelType

if TYPE_CHECKING:
    from pydsvdcapi.output import Output

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel type metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelSpec:
    """Metadata for a standard output channel type.

    Attributes
    ----------
    name:
        Protocol-level channel name (e.g. ``"brightness"``).
    min_value:
        Minimum value in the channel's unit.
    max_value:
        Maximum value in the channel's unit.
    resolution:
        Default resolution (smallest distinguishable step).
    """

    name: str
    min_value: float
    max_value: float
    resolution: float


#: Metadata table for all standard channel types (vDC API §4.9.4).
#: IDs follow the ``OutputChannelType`` enum.
CHANNEL_SPECS: dict[OutputChannelType, ChannelSpec] = {
    # -- Light channels ------------------------------------------------
    OutputChannelType.BRIGHTNESS: ChannelSpec(
        name="brightness", min_value=0, max_value=100, resolution=100 / 255
    ),
    OutputChannelType.HUE: ChannelSpec(
        name="hue", min_value=0, max_value=360, resolution=360 / 255
    ),
    OutputChannelType.SATURATION: ChannelSpec(
        name="saturation", min_value=0, max_value=100, resolution=100 / 255
    ),
    OutputChannelType.COLOR_TEMPERATURE: ChannelSpec(
        name="colortemp", min_value=100, max_value=1000, resolution=900 / 255
    ),
    OutputChannelType.CIE_X: ChannelSpec(
        name="x", min_value=0, max_value=10000, resolution=10000 / 255
    ),
    OutputChannelType.CIE_Y: ChannelSpec(
        name="y", min_value=0, max_value=10000, resolution=10000 / 255
    ),
    # -- Shade channels ------------------------------------------------
    OutputChannelType.SHADE_POSITION_OUTSIDE: ChannelSpec(
        name="shadePositionOutside",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.SHADE_POSITION_INDOOR: ChannelSpec(
        name="shadePositionIndoor",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE: ChannelSpec(
        name="shadeOpeningAngleOutside",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.SHADE_OPENING_ANGLE_INDOOR: ChannelSpec(
        name="shadeOpeningAngleIndoor",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.TRANSPARENCY: ChannelSpec(
        name="transparency",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    # -- Climate channels ----------------------------------------------
    OutputChannelType.HEATING_POWER: ChannelSpec(
        name="heatingPower",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.COOLING_CAPACITY: ChannelSpec(
        name="coolingCapacity",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.AIR_FLOW_INTENSITY: ChannelSpec(
        name="airFlowIntensity",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.AIR_FLOW_DIRECTION: ChannelSpec(
        name="airFlowDirection",
        min_value=0,
        max_value=2,
        resolution=1,
    ),
    OutputChannelType.AIR_FLAP_POSITION: ChannelSpec(
        name="airFlapPosition",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.AIR_LOUVER_POSITION: ChannelSpec(
        name="airLouverPosition",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.AIR_LOUVER_AUTO: ChannelSpec(
        name="airLouverAuto",
        min_value=0,
        max_value=1,
        resolution=1,
    ),
    OutputChannelType.AIR_FLOW_AUTO: ChannelSpec(
        name="airFlowAuto",
        min_value=0,
        max_value=1,
        resolution=1,
    ),
    # -- Audio channels ------------------------------------------------
    OutputChannelType.AUDIO_VOLUME: ChannelSpec(
        name="audioVolume",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    # -- Misc channels -------------------------------------------------
    OutputChannelType.WATER_TEMPERATURE: ChannelSpec(
        name="waterTemperature",
        min_value=0,
        max_value=150,
        resolution=150 / 255,
    ),
    OutputChannelType.WATER_FLOW_RATE: ChannelSpec(
        name="waterFlowRate",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    OutputChannelType.POWER_STATE: ChannelSpec(
        name="powerState",
        min_value=0,
        max_value=3,
        resolution=1,
    ),
    OutputChannelType.POWER_LEVEL: ChannelSpec(
        name="powerLevel",
        min_value=0,
        max_value=100,
        resolution=100 / 255,
    ),
    # -- Video channels ------------------------------------------------
    OutputChannelType.VIDEO_STATION: ChannelSpec(
        name="videoStation",
        min_value=0,
        max_value=65535,
        resolution=1,
    ),
    OutputChannelType.VIDEO_INPUT_SOURCE: ChannelSpec(
        name="videoInputSource",
        min_value=0,
        max_value=255,
        resolution=1,
    ),
}


def get_channel_spec(
    channel_type: OutputChannelType | int,
) -> ChannelSpec | None:
    """Look up the :class:`ChannelSpec` for a standard channel type.

    Returns ``None`` for unknown / device-specific channel types
    (ID ≥ 192).
    """
    if isinstance(channel_type, int) and not isinstance(
        channel_type, OutputChannelType
    ):
        try:
            channel_type = OutputChannelType(channel_type)
        except ValueError:
            return None
    return CHANNEL_SPECS.get(channel_type)


# ---------------------------------------------------------------------------
# OutputChannel
# ---------------------------------------------------------------------------


class OutputChannel:
    """One controllable dimension of a device output.

    Parameters
    ----------
    output:
        The owning :class:`~pydsvdcapi.output.Output`.
    channel_type:
        Standard channel type (``OutputChannelType`` or int).
    ds_index:
        Zero-based ``dsIndex`` within the device.  Index 0 is the
        default / primary channel.
    name:
        Human-readable label.  Defaults to the spec name for the
        channel type, or ``"channel_<dsIndex>"`` for custom types.
    min_value:
        Override the standard minimum value.
    max_value:
        Override the standard maximum value.
    resolution:
        Override the standard resolution.
    """

    def __init__(
        self,
        *,
        output: Output,
        channel_type: OutputChannelType | int,
        ds_index: int = 0,
        name: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
    ) -> None:
        self._output: Output = output

        # Store as enum if possible, otherwise keep raw int.
        try:
            self._channel_type: OutputChannelType | int = OutputChannelType(
                int(channel_type)
            )
        except ValueError:
            self._channel_type = int(channel_type)

        self._ds_index: int = ds_index

        # Resolve spec defaults.
        spec = CHANNEL_SPECS.get(
            OutputChannelType(int(channel_type))
            if isinstance(self._channel_type, OutputChannelType)
            else None  # type: ignore[arg-type]
        )
        if name is not None:
            self._name = name
        elif spec is not None:
            self._name = spec.name
        else:
            self._name = f"channel_{ds_index}"

        # Ensure float so protobuf serialises as v_double (not v_uint64).
        self._min_value: float = float(
            min_value if min_value is not None else (spec.min_value if spec else 0.0)
        )
        self._max_value: float = float(
            max_value if max_value is not None else (spec.max_value if spec else 100.0)
        )
        self._resolution: float = float(
            resolution if resolution is not None else (spec.resolution if spec else 1.0)
        )

        # ---- volatile state (NOT persisted) --------------------------
        self._value: float | None = None
        #: Monotonic timestamp of last confirmed hardware apply.
        self._last_update: float | None = None

        # Set when the first real value has been received from the device.
        self._initial_value_ready: asyncio.Event = asyncio.Event()

        # ---- value converters (optional, persisted) ------------------
        self._uplink_converter_code: str | None = None
        self._uplink_converter_fn: Callable[[Any], Any] | None = None
        self._downlink_converter_code: str | None = None
        self._downlink_converter_fn: Callable[[Any], Any] | None = None

    # ==================================================================
    # Converter management
    # ==================================================================

    def set_uplink_converter(self, code: str | None) -> None:
        """Set or clear the uplink value converter.

        Applied when the device confirms a channel value via
        :meth:`update_value` (device → dS direction).

        The snippet manipulates ``value`` (the raw device-side float).
        The library appends ``return value`` automatically.

        Pass ``None`` to remove a previously set converter.

        Raises
        ------
        SyntaxError
            If the snippet cannot be compiled.

        Example
        -------
        ::

            ch.set_uplink_converter("value = value * 100.0 / 255.0")
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

    def set_downlink_converter(self, code: str | None) -> None:
        """Set or clear the downlink value converter.

        Applied when the vdSM sets a channel value via
        :meth:`set_value_from_vdsm` (dS → device direction).

        The snippet manipulates ``value`` (the dS-side float, e.g.
        0–100 % brightness).  The library appends ``return value``
        automatically.

        Pass ``None`` to remove a previously set converter.

        Raises
        ------
        SyntaxError
            If the snippet cannot be compiled.

        Example
        -------
        ::

            ch.set_downlink_converter(
                "value = int(round(value * 255.0 / 100.0))"
            )
        """
        if code is None:
            self._downlink_converter_code = None
            self._downlink_converter_fn = None
        else:
            self._downlink_converter_fn = compile_converter(code)
            self._downlink_converter_code = code

    @property
    def downlink_converter_code(self) -> str | None:
        """The stored downlink converter snippet, or ``None``."""
        return self._downlink_converter_code

    # ==================================================================
    # Read-only description accessors
    # ==================================================================================================================================

    @property
    def output(self) -> Output:
        """The owning :class:`Output`."""
        return self._output

    @property
    def channel_type(self) -> OutputChannelType | int:
        """Channel type ID (enum or raw int for device-specific)."""
        return self._channel_type

    @property
    def ds_index(self) -> int:
        """Zero-based ``dsIndex``."""
        return self._ds_index

    @property
    def name(self) -> str:
        """Human-readable label."""
        return self._name

    @property
    def min_value(self) -> float:
        """Minimum value."""
        return self._min_value

    @property
    def max_value(self) -> float:
        """Maximum value."""
        return self._max_value

    @property
    def resolution(self) -> float:
        """Resolution (smallest distinguishable step)."""
        return self._resolution

    @resolution.setter
    def resolution(self, value: float) -> None:
        """Override the reported resolution."""
        self._resolution = float(value)

    # ==================================================================
    # Volatile state accessors
    # ==================================================================

    @property
    def value(self) -> float | None:
        """Current channel value (``None`` = unknown)."""
        return self._value

    @property
    def age(self) -> float | None:
        """Seconds since the value was last confirmed by hardware.

        ``None`` means the value was never confirmed (e.g. a new value
        was set by the vdSM but not yet applied to hardware).
        """
        if self._last_update is None:
            return None
        return time.monotonic() - self._last_update

    # ==================================================================
    # Value mutation — device side (local change)
    # ==================================================================

    async def update_value(
        self,
        value: float,
    ) -> None:
        """Set the channel value from the **device** side.

        Stores the value and marks the hardware-confirmation timestamp.
        If the owning output has ``pushChanges`` enabled and an active
        session, pushes the new value to the vdSM via
        ``VDC_SEND_PUSH_NOTIFICATION``.

        Parameters
        ----------
        value:
            New channel value in the channel's native unit/range.
        """
        value = apply_converter(
            self._uplink_converter_fn,
            value,
            component_id=f"OutputChannel[{self._ds_index}] '{self._name}'",
            direction="uplink",
        )
        self._value = self._clamp(value)
        self._initial_value_ready.set()
        self._last_update = time.monotonic()
        logger.debug(
            "OutputChannel[%d] '%s' device-side update → %s",
            self._ds_index,
            self._name,
            self._value,
        )
        # Push to vdSM if output.pushChanges is set.
        if self._output.push_changes:
            await self._output._push_channel_state(self)

    # ==================================================================
    # Value mutation — vdSM side (setOutputChannelValue)
    # ==================================================================

    def set_value_from_vdsm(self, value: float) -> None:
        """Buffer a value received from the vdSM.

        Called by the ``VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE``
        handler.  The value is stored, but the hardware-confirmation
        timestamp is cleared (``age`` becomes ``None``) until the
        device confirms.

        The device callback is **not** invoked here — it is triggered
        by :meth:`Output.apply_pending_channels` when ``apply_now``
        is ``True``.
        """
        value = apply_converter(
            self._downlink_converter_fn,
            value,
            component_id=f"OutputChannel[{self._ds_index}] '{self._name}'",
            direction="downlink",
        )
        self._value = self._clamp(value)
        self._initial_value_ready.set()
        # Age = NULL until the device confirms the value.
        self._last_update = None
        logger.debug(
            "OutputChannel[%d] '%s' vdSM-side set → %s (pending)",
            self._ds_index,
            self._name,
            self._value,
        )

    def confirm_applied(self) -> None:
        """Mark the current value as applied to the hardware.

        Called after the device callback has successfully applied the
        value.  This sets the hardware-confirmation timestamp so
        ``age`` starts counting from now.
        """
        self._last_update = time.monotonic()
        logger.debug(
            "OutputChannel[%d] '%s' confirmed applied (value=%s)",
            self._ds_index,
            self._name,
            self._value,
        )

    # ==================================================================
    # Property dicts (for getProperty responses)
    # ==================================================================

    def get_description_properties(self) -> dict[str, Any]:
        """Return this channel's ``channelDescriptions`` value dict.

        The returned dict is used as the *value* of the element keyed by
        :attr:`name` inside the ``channelDescriptions`` property sub-tree
        (§4.9.1).  Keys match the vDC API property names.
        """
        return {
            "name": self._name,
            "channelType": int(self._channel_type),
            "dsIndex": self._ds_index,
            "min": self._min_value,
            "max": self._max_value,
            "resolution": self._resolution,
        }

    def get_settings_properties(self) -> dict[str, Any]:
        """Return this channel's ``channelSettings`` value dict.

        The returned dict is used as the *value* of the element keyed by
        :attr:`name` inside the ``channelSettings`` property sub-tree
        (§4.9.2).  Currently no per-channel settings are defined.
        """
        return {}

    def get_state_properties(self) -> dict[str, Any]:
        """Return this channel's ``channelStates`` value dict.

        The returned dict is used as the *value* of the element keyed by
        :attr:`name` inside the ``channelStates`` property sub-tree
        (§4.9.3).  Keys match the vDC API property names.
        """
        return {
            "value": self._value,  # may be None (NULL)
            "age": self.age,  # may be None (NULL)
        }

    # ==================================================================
    # Persistence
    # ==================================================================

    def get_property_tree(self) -> dict[str, Any]:
        """Return a serialisable dict for YAML persistence.

        Only description metadata is persisted.  Channel value/age
        are volatile.
        """
        node: dict[str, Any] = {
            "channelType": int(self._channel_type),
            "dsIndex": self._ds_index,
            "name": self._name,
            "min": self._min_value,
            "max": self._max_value,
            "resolution": self._resolution,
        }
        if self._uplink_converter_code is not None:
            node["uplinkConverter"] = self._uplink_converter_code
        if self._downlink_converter_code is not None:
            node["downlinkConverter"] = self._downlink_converter_code
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted property tree dict.

        Only description fields; value/age remain at defaults.
        """
        if "channelType" in state:
            raw = int(state["channelType"])
            try:
                self._channel_type = OutputChannelType(raw)
            except ValueError:
                self._channel_type = raw
            # Re-resolve name from spec if not explicitly stored.
            spec = CHANNEL_SPECS.get(
                self._channel_type
                if isinstance(self._channel_type, OutputChannelType)
                else None  # type: ignore[arg-type]
            )
            if spec and "name" not in state:
                self._name = spec.name
        if "dsIndex" in state:
            self._ds_index = int(state["dsIndex"])
        if "name" in state:
            self._name = state["name"]
        if "min" in state:
            self._min_value = float(state["min"])
        if "max" in state:
            self._max_value = float(state["max"])
        if "resolution" in state:
            self._resolution = float(state["resolution"])
        # Converters
        if "uplinkConverter" in state:
            self.set_uplink_converter(state["uplinkConverter"])
        else:
            self._uplink_converter_code = None
            self._uplink_converter_fn = None
        if "downlinkConverter" in state:
            self.set_downlink_converter(state["downlinkConverter"])
        else:
            self._downlink_converter_code = None
            self._downlink_converter_fn = None

    # ==================================================================
    # Helpers
    # ==================================================================

    def _clamp(self, value: float) -> float:
        """Clamp *value* to [min_value, max_value]."""
        return max(self._min_value, min(self._max_value, value))

    def __repr__(self) -> str:
        type_name = (
            self._channel_type.name
            if isinstance(self._channel_type, OutputChannelType)
            else str(self._channel_type)
        )
        return (
            f"OutputChannel(type={type_name}, "
            f"dsIndex={self._ds_index}, "
            f"value={self._value!r})"
        )
