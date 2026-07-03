# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Output component for vdSD devices.

A :class:`Output` models the single output of a virtual device.  Each
vdSD may have **at most one** output (enforced by the owning
:class:`~pydsvdcapi.vdsd.Vdsd`).  If a physical device has multiple
independent outputs, the vDC must represent it as multiple virtual
devices with separate dSUIDs (see vDC API §4.1.3).

The output owns three property groups visible to the vdSM:

* **outputDescription** — read-only hardware characteristics
  (function, outputUsage, variableRamp, maxPower, …).
* **outputSettings** — writable configuration stored persistently
  (mode, groups, pushChanges, dimming parameters, …).
* **outputState** — volatile runtime state (localPriority, transitionTime, error)
  that is **not** persisted.

Channels
~~~~~~~~

Output channels (brightness, hue, saturation, etc.) are owned by the
output.  Depending on the output's ``function``, standard channels
are auto-created on construction:

* **ON_OFF / DIMMER** → brightness
* **DIMMER_COLOR_TEMP** → brightness + colortemp
* **FULL_COLOR_DIMMER** → brightness + hue + saturation + colortemp
  + cieX + cieY
* **POSITIONAL / BIPOLAR / INTERNALLY_CONTROLLED / CUSTOM** → no
  auto-created channels; the integrator must add them via
  :meth:`add_channel`.

The ``channelDescriptions``, ``channelSettings``, and
``channelStates`` property sub-trees each carry **all channels inside
a single** ``PropertyElement``, with each channel identified by its
**name** as the element key (e.g. ``"brightness"``, ``"colortemp"``,
``"shadePositionOutside"``).  The name matches the ``channelId`` field
that dSS sends in ``setOutputChannelValue`` notifications.

See :mod:`pydsvdcapi.output_channel` for details on channel semantics,
bidirectional value flow, ``apply_now`` buffering, and push behaviour.

State model
~~~~~~~~~~~

The output's operational values (brightness level, valve position,
colour values, etc.) live in the *channels*.  The output state itself
carries ``localPriority``, ``transitionTime``, and ``error``.

When a channel value is changed locally (from the device side) and
``pushChanges`` is enabled, the output pushes the channel state to
the vdSM via ``VDC_SEND_PUSH_NOTIFICATION``.

Persistence
~~~~~~~~~~~

Only description and settings properties are persisted (via the owning
Vdsd's property tree → Device → Vdc → VdcHost YAML).  The runtime
state (``localPriority``, ``transitionTime``, ``error``)
is transient.

Usage::

    from pydsvdcapi.output import Output
    from pydsvdcapi.enums import OutputFunction, OutputMode, OutputUsage

    output = Output(
        vdsd=my_vdsd,
        function=OutputFunction.DIMMER,
        output_usage=OutputUsage.ROOM,
        name="Dimmable Light",
    )
    my_vdsd.set_output(output)
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import (
    TYPE_CHECKING,
    Any,
)

import pydsvdcapi.vdc_messages_pb2 as pb
from pydsvdcapi.enums import (
    HeatingSystemCapability,
    HeatingSystemType,
    OutputChannelType,
    OutputError,
    OutputFunction,
    OutputMode,
    OutputUsage,
    SceneEffect,
    SceneNumber,
)
from pydsvdcapi.output_channel import OutputChannel
from pydsvdcapi.property_handling import dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

#: Type alias for the channel-applied callback.
#: ``async def callback(output, channel_updates) -> None``
#: where *channel_updates* is a dict ``{OutputChannelType | int: value}``.
ChannelAppliedCallback = Callable[
    ["Output", dict[OutputChannelType | int, float]],
    Coroutine[Any, Any, None],
]

#: Type alias for the dim-channel callback (§7.3.5).
#: ``async def callback(output, channel, mode, area) -> None``
#: where *channel* is the :class:`OutputChannel` being dimmed,
#: *mode* is ``1`` (dim up), ``-1`` (dim down), or ``0`` (stop),
#: and *area* is the area restriction (0 = none, 1..4).
DimChannelCallback = Callable[
    ["Output", "OutputChannel", int, int],
    Coroutine[Any, Any, None],
]

#: Type alias for the output-settings-changed callback.
#: ``async def callback(output: Output, changed: dict[str, Any]) -> None``
#: *changed* is the dict of keys that arrived in the ``setProperty`` request.
OutputSettingsChangedCallback = Callable[
    ["Output", dict[str, Any]],
    Coroutine[Any, Any, None],
]


# ---------------------------------------------------------------------------
# Output function → auto-created channel types
# ---------------------------------------------------------------------------

#: Standard channel types auto-created for each output function.
FUNCTION_CHANNELS: dict[OutputFunction, list[OutputChannelType]] = {
    OutputFunction.ON_OFF: [
        OutputChannelType.BRIGHTNESS,
    ],
    OutputFunction.DIMMER: [
        OutputChannelType.BRIGHTNESS,
    ],
    OutputFunction.DIMMER_COLOR_TEMP: [
        OutputChannelType.BRIGHTNESS,
        OutputChannelType.COLOR_TEMPERATURE,
    ],
    OutputFunction.FULL_COLOR_DIMMER: [
        # Order verified against working dSS config: brightness(0), colortemp(1),
        # hue(2), saturation(3), cieX(4), cieY(5).  colortemp must be dsIndex 1
        # so the dSS configurator renders the CT slider correctly.
        OutputChannelType.BRIGHTNESS,
        OutputChannelType.COLOR_TEMPERATURE,
        OutputChannelType.HUE,
        OutputChannelType.SATURATION,
        OutputChannelType.CIE_X,
        OutputChannelType.CIE_Y,
    ],
    # POSITIONAL, BIPOLAR, INTERNALLY_CONTROLLED, CUSTOM — no
    # auto-created channels.  The integrator must add them via
    # add_channel().
}

logger = logging.getLogger(__name__)

# Default motor timing values for shade outputs (per vDC API specification).
_SHADOW_DEFAULT_OPEN_TIME: float = 50.0
_SHADOW_DEFAULT_CLOSE_TIME: float = 50.0
_SHADOW_DEFAULT_ANGLE_OPEN_TIME: float = 1.0
_SHADOW_DEFAULT_ANGLE_CLOSE_TIME: float = 1.0
_SHADOW_DEFAULT_STOP_DELAY_TIME: float = 0.0

#: All setting keys that :meth:`Output.apply_settings` handles explicitly.
#: Any key arriving via ``setProperty`` that is **not** in this set is stored
#: in :attr:`Output._extra_settings` and round-tripped through persistence.
_KNOWN_SETTING_KEYS: frozenset[str] = frozenset(
    {
        "mode",
        "activeGroup",
        "pushChanges",
        "groups",
        "onThreshold",
        "minBrightness",
        "dimTimeUp",
        "dimTimeDown",
        "dimTimeUpAlt1",
        "dimTimeDownAlt1",
        "dimTimeUpAlt2",
        "dimTimeDownAlt2",
        "heatingSystemCapability",
        "heatingSystemType",
        "openTime",
        "closeTime",
        "angleOpenTime",
        "angleCloseTime",
        "stopDelayTime",
    }
)

#: All keys that appear in the persisted property tree dict.
#: Used by :meth:`Output._apply_state` to identify which keys are
#: firmware-specific extras that should be stored in :attr:`Output._extra_settings`.
_KNOWN_TREE_KEYS: frozenset[str] = _KNOWN_SETTING_KEYS | frozenset(
    {
        # Description keys
        "function",
        "outputUsage",
        "name",
        "defaultGroup",
        "variableRamp",
        "maxPower",
        "activeCoolingMode",
        # Structural keys
        "channels",
        "scenes",
    }
)


# ---------------------------------------------------------------------------
# Scene default helpers
# ---------------------------------------------------------------------------

#: Scene numbers that represent an "off" action (primary channel → min).
_OFF_SCENES: frozenset = frozenset(
    {
        SceneNumber.PRESET_0,
        SceneNumber.AREA_1_OFF,
        SceneNumber.AREA_2_OFF,
        SceneNumber.AREA_3_OFF,
        SceneNumber.AREA_4_OFF,
        SceneNumber.PRESET_10,
        SceneNumber.PRESET_20,
        SceneNumber.PRESET_30,
        SceneNumber.PRESET_40,
        SceneNumber.AUTO_OFF,
        SceneNumber.DEVICE_OFF,
        SceneNumber.DEEP_OFF,
        SceneNumber.AUTO_STANDBY,
        SceneNumber.STANDBY,
        SceneNumber.ABSENT,
    }
)

#: Scene numbers that represent an "on" action (primary channel → max).
_ON_SCENES: frozenset = frozenset(
    {
        SceneNumber.PRESET_1,
        SceneNumber.AREA_1_ON,
        SceneNumber.AREA_2_ON,
        SceneNumber.AREA_3_ON,
        SceneNumber.AREA_4_ON,
        SceneNumber.PRESET_11,
        SceneNumber.PRESET_21,
        SceneNumber.PRESET_31,
        SceneNumber.PRESET_41,
        SceneNumber.MAXIMUM,
        SceneNumber.DEVICE_ON,
        SceneNumber.PRESENT,
        SceneNumber.WAKEUP,
    }
)

#: Scenes that are "action" commands and do **not** have stored values
#: (stepping, stop, dimming, panic, alarm, …).  These are excluded
#: from the default scene table.
_NON_VALUE_SCENES: frozenset = frozenset(
    {
        SceneNumber.AREA_STEPPING_CONTINUE,
        SceneNumber.DECREMENT,
        SceneNumber.INCREMENT,
        SceneNumber.STOP,
        SceneNumber.AREA_1_DEC,
        SceneNumber.AREA_1_INC,
        SceneNumber.AREA_1_STOP,
        SceneNumber.AREA_2_DEC,
        SceneNumber.AREA_2_INC,
        SceneNumber.AREA_2_STOP,
        SceneNumber.AREA_3_DEC,
        SceneNumber.AREA_3_INC,
        SceneNumber.AREA_3_STOP,
        SceneNumber.AREA_4_DEC,
        SceneNumber.AREA_4_INC,
        SceneNumber.AREA_4_STOP,
        SceneNumber.IMPULSE,
        SceneNumber.MINIMUM,
    }
)

#: Medium preset scenes — scene number → fraction of (max − min) to add to min.
#: Preset X2 = 75 %, Preset X3 = 50 %, Preset X4 = 25 % (ds-basics Table 3).
#: Five groups × three presets = 15 entries (scenes 17–31).
_MEDIUM_PRESET_FRACTIONS: dict[int, float] = {
    17: 0.75,  # Preset 2
    18: 0.50,  # Preset 3
    19: 0.25,  # Preset 4
    20: 0.75,  # Preset 12
    21: 0.50,  # Preset 13
    22: 0.25,  # Preset 14
    23: 0.75,  # Preset 22
    24: 0.50,  # Preset 23
    25: 0.25,  # Preset 24
    26: 0.75,  # Preset 32
    27: 0.50,  # Preset 33
    28: 0.25,  # Preset 34
    29: 0.75,  # Preset 42
    30: 0.50,  # Preset 43
    31: 0.25,  # Preset 44
}

#: Scenes that override local priority (ds-basics §5.3).
_IGNORE_LOCAL_PRIORITY_SCENES: frozenset = frozenset(
    {
        SceneNumber.PANIC,
        SceneNumber.FIRE,
        SceneNumber.ALARM_1,
        SceneNumber.ALARM_2,
        SceneNumber.ALARM_3,
        SceneNumber.ALARM_4,
        SceneNumber.ABSENT,  # spec §5.3 explicitly: "Absent shall have an effect … regardless"
    }
)

#: Stepping scenes that move the primary channel DOWN.
_STEP_DOWN_SCENES: frozenset = frozenset(
    {
        SceneNumber.DECREMENT,
        SceneNumber.AREA_1_DEC,
        SceneNumber.AREA_2_DEC,
        SceneNumber.AREA_3_DEC,
        SceneNumber.AREA_4_DEC,
    }
)

#: Stepping scenes that move the primary channel UP.
_STEP_UP_SCENES: frozenset = frozenset(
    {
        SceneNumber.INCREMENT,
        SceneNumber.AREA_1_INC,
        SceneNumber.AREA_2_INC,
        SceneNumber.AREA_3_INC,
        SceneNumber.AREA_4_INC,
    }
)

#: All stepping scene numbers (up, down, and continue).
_ALL_STEP_SCENES: frozenset = (
    _STEP_DOWN_SCENES
    | _STEP_UP_SCENES
    | frozenset({SceneNumber.AREA_STEPPING_CONTINUE})
)

#: Stepping scene number → area restriction (0 for zone-wide commands).
_STEP_SCENE_AREA: dict[int, int] = {
    int(SceneNumber.AREA_1_DEC): 1,
    int(SceneNumber.AREA_1_INC): 1,
    int(SceneNumber.AREA_2_DEC): 2,
    int(SceneNumber.AREA_2_INC): 2,
    int(SceneNumber.AREA_3_DEC): 3,
    int(SceneNumber.AREA_3_INC): 3,
    int(SceneNumber.AREA_4_DEC): 4,
    int(SceneNumber.AREA_4_INC): 4,
}


def _build_default_scene_entry(
    scene_nr: int,
    channels: dict[int, OutputChannel],
) -> dict[str, Any]:
    """Build the default scene entry for *scene_nr*.

    Returns a dict with the structure:
        {
            "dontCare": bool,
            "ignoreLocalPriority": bool,
            "effect": int,
            "channels": {
                <dsIndex>: {
                    "value": float | None,
                    "dontCare": bool,
                    "automatic": bool,
                },
                …
            },
        }
    """
    is_off = scene_nr in _OFF_SCENES
    is_on = scene_nr in _ON_SCENES
    medium_fraction = _MEDIUM_PRESET_FRACTIONS.get(scene_nr)
    has_default = is_off or is_on or medium_fraction is not None

    # Determine scene-global defaults.
    scene_dont_care = not has_default
    ignore_local_priority = scene_nr in _IGNORE_LOCAL_PRIORITY_SCENES
    effect = int(SceneEffect.SMOOTH) if has_default else int(SceneEffect.NONE)

    ch_entries: dict[int, dict[str, Any]] = {}
    for idx, ch in channels.items():
        if is_off:
            val: float | None = ch.min_value
        elif is_on:
            val = ch.max_value
        elif medium_fraction is not None:
            val = ch.min_value + medium_fraction * (ch.max_value - ch.min_value)
        else:
            val = ch.min_value
        ch_entries[idx] = {
            "value": val,
            "dontCare": not has_default,
            "automatic": False,
        }

    return {
        "dontCare": scene_dont_care,
        "ignoreLocalPriority": ignore_local_priority,
        "effect": effect,
        "channels": ch_entries,
    }


# ---------------------------------------------------------------------------
# Channel backward-compat dict
# ---------------------------------------------------------------------------


class _ChannelCompatDict(dict):
    """Channel property dict with transparent numeric-key resolution.

    The dSS configurator UI sends ``getProperty`` queries using the old API
    v1/v2 channel key format: the ``channelType`` integer as a string (e.g.
    ``"1"`` for brightness, ``"7"`` for shadePositionOutside) or ``"0"`` as
    the spec-defined alias for the standard channel of the device's color
    class (ds-basics §7 table 7).

    This ``dict`` subclass wraps the canonical channel property dict so that
    :func:`~pydsvdcapi.property_handling.match_query` can serve both old and
    new format queries without modification.

    Wildcard queries iterate ``dict.items()`` which only yields **canonical**
    (named) keys — no numeric duplicates appear in wildcard responses.

    Parameters
    ----------
    data:
        The canonical channel property dict (e.g. ``{"brightness": {...}}``)
        built by :meth:`~Output.get_channel_descriptions`.
    output:
        The owning :class:`Output` instance, used to resolve numeric keys via
        :meth:`~Output.channel_by_key`.
    """

    def __init__(self, data: dict, output: Output) -> None:
        super().__init__(data)
        self._output = output

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            return self._output.channel_by_key(key) is not None
        return False

    def __getitem__(self, key: str) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        ch = self._output.channel_by_key(key)
        if ch is not None and super().__contains__(ch.name):
            return super().__getitem__(ch.name)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class Output:
    """The single output of a vdSD.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd`.
    function:
        Functional type of the output (on/off, dimmer, positional, …).
    output_usage:
        Usage context (room, outdoors, user).
    name:
        Human-readable name for the output (e.g. matching a hardware
        connector label).
    default_group:
        dS Application Group ID for this output.  Use :class:`~pydsvdcapi.enums.ColorClass`
        values.  For most devices this equals the numeric value of the device's
        ``primaryGroup`` (e.g. YELLOW light: ``ColorClass.LIGHTS`` = 1;
        BLUE heating valve: ``ColorClass.HEATING`` = 3).  Climate sub-types
        use the more specific Application Group ID (e.g. ``ColorClass.VENTILATION``
        = 10 for a ventilation unit, even though ``primaryGroup`` is BLUE = 3).
        Informational only — the dSS firmware does not use this field at runtime.
    variable_ramp:
        Whether variable-speed transitions are supported.
    max_power:
        Maximum output power in Watts (``None`` = undefined).
    active_cooling_mode:
        ``True`` if the device can actively cool (FCU / air-con).
        ``None`` if not applicable.

    Settings (writable, persisted):

    mode:
        Output mode passed in ``outputSettings/mode``.  The vdSM uses this
        to set the dSM ``OutputMode`` register, which controls how the Smart
        Home API reports the output (e.g. ``gradual``, ``switched``).  When
        omitted (``None``) the correct value is auto-derived from
        ``function``: ``ON_OFF`` → ``BINARY``; ``INTERNALLY_CONTROLLED`` /
        ``CUSTOM`` → ``DISABLED``; all other functions → ``GRADUAL``.
    active_group:
        dS Application Group ID this output is active in.  Use
        :class:`~pydsvdcapi.enums.ColorClass` values.  For most devices equals
        ``default_group``.  Drives scene routing and device behaviour in the dSS
        firmware (cast to ``ApplicationType``).  For joker devices the user can
        change this via the dSS UI.  If the value is < 64 it must also appear
        in ``groups``; values ≥ 64 (global app groups) are exempt.
    groups:
        Set of dS Application Group IDs (1–63) this output belongs to.  Use
        :class:`~pydsvdcapi.enums.ColorClass` values with value ≤ 63.  For
        most devices this is a single-element set containing ``active_group``
        (when ``active_group`` < 64).  Global app group IDs (≥ 64) must NOT
        appear here — they are declared via ``active_group`` only.
    push_changes:
        Whether locally-generated output changes are pushed.
    on_threshold:
        Minimum brightness (0-100 %) to switch on non-dimmable lamps.
    min_brightness:
        Minimum brightness (0-100 %) the hardware supports.
    dim_time_up:
        Dim-up time in dS 8-bit format.
    dim_time_down:
        Dim-down time in dS 8-bit format.
    dim_time_up_alt1:
        Alternate 1 dim-up time.
    dim_time_down_alt1:
        Alternate 1 dim-down time.
    dim_time_up_alt2:
        Alternate 2 dim-up time.
    dim_time_down_alt2:
        Alternate 2 dim-down time.
    heating_system_capability:
        How ``heatingLevel`` is applied (heating-only / cooling-only /
        heating-and-cooling).  ``None`` if not a climate device.
    heating_system_type:
        Kind of valve / actuator attached.  ``None`` if not a climate
        device.
    open_time:
        Motor open travel time in seconds.
        ``None`` if not a shadow device.
    close_time:
        Motor close travel time in seconds.  ``None`` if not configured.
    angle_open_time:
        Blade angle open time in seconds.  ``None`` if not configured.
    angle_close_time:
        Blade angle close time in seconds.  ``None`` if not configured.
    stop_delay_time:
        Stop delay time in seconds.  ``None`` if not configured.
    """

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        function: OutputFunction | int = OutputFunction.ON_OFF,
        output_usage: OutputUsage | int = OutputUsage.UNDEFINED,
        name: str | None = None,
        default_group: int | None = None,
        variable_ramp: bool = False,
        max_power: float = -1.0,
        active_cooling_mode: bool | None = None,
        # Settings (writable, persisted)
        mode: OutputMode | int | None = None,
        active_group: int | None = None,
        groups: set[int] | None = None,
        push_changes: bool = False,
        on_threshold: float | None = None,
        min_brightness: float | None = None,
        dim_time_up: int | None = None,
        dim_time_down: int | None = None,
        dim_time_up_alt1: int | None = None,
        dim_time_down_alt1: int | None = None,
        dim_time_up_alt2: int | None = None,
        dim_time_down_alt2: int | None = None,
        heating_system_capability: HeatingSystemCapability | int | None = None,
        heating_system_type: HeatingSystemType | int | None = None,
        # Shadow motor timing settings
        open_time: float | None = None,
        close_time: float | None = None,
        angle_open_time: float | None = None,
        angle_close_time: float | None = None,
        stop_delay_time: float | None = None,
    ) -> None:
        # ---- parent reference ----------------------------------------
        self._vdsd: Vdsd = vdsd

        # ---- description properties (read-only, persisted) -----------
        self._function: OutputFunction = OutputFunction(int(function))
        self._output_usage: OutputUsage = OutputUsage(int(output_usage))
        self._name: str | None = name if name else None
        self._default_group: int | None = default_group
        self._variable_ramp: bool = variable_ramp
        self._max_power: float = max_power
        self._active_cooling_mode: bool | None = active_cooling_mode

        # ---- settings properties (read/write, persisted) -------------
        if mode is None:
            fn = int(self._function)
            if fn in (
                int(OutputFunction.INTERNALLY_CONTROLLED),
                int(OutputFunction.CUSTOM),
            ):
                self._mode = OutputMode.DISABLED
            elif fn == int(OutputFunction.ON_OFF):
                self._mode = OutputMode.BINARY
            else:
                self._mode = OutputMode.GRADUAL
        else:
            self._mode = OutputMode(int(mode))
        self._active_group: int | None = active_group
        self._groups: set[int] = set(groups) if groups is not None else set()
        self._push_changes: bool = push_changes
        self._on_threshold: float | None = on_threshold
        self._min_brightness: float | None = min_brightness
        self._dim_time_up: int | None = dim_time_up
        self._dim_time_down: int | None = dim_time_down
        self._dim_time_up_alt1: int | None = dim_time_up_alt1
        self._dim_time_down_alt1: int | None = dim_time_down_alt1
        self._dim_time_up_alt2: int | None = dim_time_up_alt2
        self._dim_time_down_alt2: int | None = dim_time_down_alt2
        self._heating_system_capability: HeatingSystemCapability | None = (
            HeatingSystemCapability(int(heating_system_capability))
            if heating_system_capability is not None
            else None
        )
        self._heating_system_type: HeatingSystemType | None = (
            HeatingSystemType(int(heating_system_type))
            if heating_system_type is not None
            else None
        )

        # Shadow motor timing
        self._open_time: float | None = open_time
        self._close_time: float | None = close_time
        self._angle_open_time: float | None = angle_open_time
        self._angle_close_time: float | None = angle_close_time
        self._stop_delay_time: float | None = stop_delay_time

        # Extra settings: unknown keys received via setProperty are stored
        # here so they can be round-tripped through persistence and returned
        # by get_settings_properties().
        self._extra_settings: dict[str, Any] = {}

        # ---- state properties (volatile, NOT persisted) --------------
        self._local_priority: bool = False
        self._error: OutputError = OutputError.OK
        self._transition_time: float = 0.0

        # ---- session reference (set on announcement) -----------------
        self._session: VdcSession | None = None

        # ---- channels ------------------------------------------------
        #: Channels keyed by dsIndex.
        self._channels: dict[int, OutputChannel] = {}
        #: Pending vdSM-side channel value changes (apply_now buffer).
        #: Maps dsIndex → buffered value.
        self._pending_channel_updates: dict[int, float] = {}
        #: Callback invoked when apply_now triggers hardware apply.
        self._on_channel_applied: ChannelAppliedCallback | None = None
        #: Callback invoked for dimChannel notifications (§7.3.5).
        self._on_dim_channel: DimChannelCallback | None = None
        #: Callback invoked when vdSM writes outputSettings.
        self._on_settings_changed: OutputSettingsChangedCallback | None = None
        #: Last stepping direction for AREA_STEPPING_CONTINUE: -1 down, +1 up, 0 unknown.
        self._last_step_direction: int = 0
        #: Area of last directional step (for AREA_STEPPING_CONTINUE).
        self._last_step_area: int = 0

        # Auto-create channels from function.
        self._auto_create_channels()

        # ---- scene table ---------------------------------------------
        #: Scene table: maps scene number (int) → scene entry dict.
        self._scenes: dict[int, dict[str, Any]] = {}
        #: Per-group last called scene number (for undo matching).
        #: Maps group (int) → last called scene number.
        self._last_called_scenes: dict[int, int] = {}
        #: Per-group undo snapshots of channel values before call_scene.
        #: Maps group (int) → {dsIndex: value}.
        self._undo_snapshots: dict[int, dict[int, float]] = {}
        # Populate default scenes.
        self._init_default_scenes()

    # ==================================================================
    # Read-only description accessors
    # ==================================================================

    @property
    def vdsd(self) -> Vdsd:
        """Owning vdSD."""
        return self._vdsd

    @property
    def function(self) -> OutputFunction:
        """Functional type of the output."""
        return self._function

    @property
    def output_usage(self) -> OutputUsage:
        """Usage context of the output."""
        return self._output_usage

    @property
    def name(self) -> str | None:
        """Human-readable name (optional; omitted from outputDescription when None)."""
        return self._name

    @name.setter
    def name(self, value: str | None) -> None:
        self._name = value if value else None
        self._schedule_auto_save()

    @property
    def default_group(self) -> int | None:
        """Application profile ID for this output (optional; omitted from outputDescription when None)."""
        return self._default_group

    @default_group.setter
    def default_group(self, value: int | None) -> None:
        self._default_group = int(value) if value is not None else None
        self._schedule_auto_save()

    @property
    def variable_ramp(self) -> bool:
        """Whether variable-speed transitions are supported."""
        return self._variable_ramp

    @property
    def max_power(self) -> float:
        """Maximum output power in Watts (``None`` = undefined)."""
        return self._max_power

    @property
    def active_cooling_mode(self) -> bool | None:
        """Whether the device can actively cool."""
        return self._active_cooling_mode

    # ==================================================================
    # Writable settings accessors
    # ==================================================================

    @property
    def mode(self) -> OutputMode:
        """Output operating mode."""
        return self._mode

    @mode.setter
    def mode(self, value: OutputMode | int) -> None:
        self._mode = OutputMode(int(value))
        self._schedule_auto_save()

    @property
    def active_group(self) -> int | None:
        """Application profile ID this output is active in (optional; omitted from outputSettings when None)."""
        return self._active_group

    @active_group.setter
    def active_group(self, value: int | None) -> None:
        self._active_group = int(value) if value is not None else None
        self._schedule_auto_save()

    @property
    def groups(self) -> set[int]:
        """Application profile IDs this output belongs to (use ColorClass enum values)."""
        return set(self._groups)

    @groups.setter
    def groups(self, value: set[int]) -> None:
        self._groups = set(value)
        self._schedule_auto_save()

    def add_group(self, group_id: int) -> None:
        """Add an ColorClass to the output's group membership set."""
        self._groups.add(group_id)
        self._schedule_auto_save()

    def remove_group(self, group_id: int) -> None:
        """Remove membership from a group."""
        self._groups.discard(group_id)
        self._schedule_auto_save()

    @property
    def push_changes(self) -> bool:
        """Whether locally-generated output changes are pushed."""
        return self._push_changes

    @push_changes.setter
    def push_changes(self, value: bool) -> None:
        self._push_changes = bool(value)
        self._schedule_auto_save()

    @property
    def on_threshold(self) -> float | None:
        """Minimum brightness to switch on non-dimmable lamps."""
        return self._on_threshold

    @on_threshold.setter
    def on_threshold(self, value: float | None) -> None:
        self._on_threshold = value
        self._schedule_auto_save()

    @property
    def min_brightness(self) -> float | None:
        """Minimum brightness the hardware supports."""
        return self._min_brightness

    @min_brightness.setter
    def min_brightness(self, value: float | None) -> None:
        self._min_brightness = value
        self._schedule_auto_save()

    @property
    def dim_time_up(self) -> int | None:
        """Dim-up time in dS 8-bit format."""
        return self._dim_time_up

    @dim_time_up.setter
    def dim_time_up(self, value: int | None) -> None:
        self._dim_time_up = value
        self._schedule_auto_save()

    @property
    def dim_time_down(self) -> int | None:
        """Dim-down time in dS 8-bit format."""
        return self._dim_time_down

    @dim_time_down.setter
    def dim_time_down(self, value: int | None) -> None:
        self._dim_time_down = value
        self._schedule_auto_save()

    @property
    def dim_time_up_alt1(self) -> int | None:
        """Alternate 1 dim-up time."""
        return self._dim_time_up_alt1

    @dim_time_up_alt1.setter
    def dim_time_up_alt1(self, value: int | None) -> None:
        self._dim_time_up_alt1 = value
        self._schedule_auto_save()

    @property
    def dim_time_down_alt1(self) -> int | None:
        """Alternate 1 dim-down time."""
        return self._dim_time_down_alt1

    @dim_time_down_alt1.setter
    def dim_time_down_alt1(self, value: int | None) -> None:
        self._dim_time_down_alt1 = value
        self._schedule_auto_save()

    @property
    def dim_time_up_alt2(self) -> int | None:
        """Alternate 2 dim-up time."""
        return self._dim_time_up_alt2

    @dim_time_up_alt2.setter
    def dim_time_up_alt2(self, value: int | None) -> None:
        self._dim_time_up_alt2 = value
        self._schedule_auto_save()

    @property
    def dim_time_down_alt2(self) -> int | None:
        """Alternate 2 dim-down time."""
        return self._dim_time_down_alt2

    @dim_time_down_alt2.setter
    def dim_time_down_alt2(self, value: int | None) -> None:
        self._dim_time_down_alt2 = value
        self._schedule_auto_save()

    @property
    def heating_system_capability(
        self,
    ) -> HeatingSystemCapability | None:
        """How ``heatingLevel`` control value is applied."""
        return self._heating_system_capability

    @heating_system_capability.setter
    def heating_system_capability(
        self,
        value: HeatingSystemCapability | int | None,
    ) -> None:
        self._heating_system_capability = (
            HeatingSystemCapability(int(value)) if value is not None else None
        )
        self._schedule_auto_save()

    @property
    def heating_system_type(self) -> HeatingSystemType | None:
        """Kind of valve / actuator attached."""
        return self._heating_system_type

    @heating_system_type.setter
    def heating_system_type(
        self,
        value: HeatingSystemType | int | None,
    ) -> None:
        self._heating_system_type = (
            HeatingSystemType(int(value)) if value is not None else None
        )
        self._schedule_auto_save()

    @property
    def open_time(self) -> float | None:
        """Motor open travel time in seconds (``None`` = not configured)."""
        return self._open_time

    @open_time.setter
    def open_time(self, value: float | None) -> None:
        self._open_time = value
        self._schedule_auto_save()

    @property
    def close_time(self) -> float | None:
        """Motor close travel time in seconds (``None`` = not configured)."""
        return self._close_time

    @close_time.setter
    def close_time(self, value: float | None) -> None:
        self._close_time = value
        self._schedule_auto_save()

    @property
    def angle_open_time(self) -> float | None:
        """Blade angle open time in seconds (``None`` = not configured)."""
        return self._angle_open_time

    @angle_open_time.setter
    def angle_open_time(self, value: float | None) -> None:
        self._angle_open_time = value
        self._schedule_auto_save()

    @property
    def angle_close_time(self) -> float | None:
        """Blade angle close time in seconds (``None`` = not configured)."""
        return self._angle_close_time

    @angle_close_time.setter
    def angle_close_time(self, value: float | None) -> None:
        self._angle_close_time = value
        self._schedule_auto_save()

    @property
    def stop_delay_time(self) -> float | None:
        """Stop delay time in seconds (``None`` = not configured)."""
        return self._stop_delay_time

    @stop_delay_time.setter
    def stop_delay_time(self, value: float | None) -> None:
        self._stop_delay_time = value
        self._schedule_auto_save()

    # ==================================================================
    # State accessors (volatile)
    # ==================================================================

    @property
    def local_priority(self) -> bool:
        """Local priority flag (volatile, not persisted)."""
        return self._local_priority

    @local_priority.setter
    def local_priority(self, value: bool) -> None:
        self._local_priority = bool(value)

    @property
    def error(self) -> OutputError:
        """Output error status (volatile, not persisted)."""
        return self._error

    @error.setter
    def error(self, value: OutputError | int) -> None:
        self._error = OutputError(int(value))

    @property
    def transition_time(self) -> float:
        """Transition time in seconds (volatile, not persisted)."""
        return self._transition_time

    @transition_time.setter
    def transition_time(self, value: float) -> None:
        self._transition_time = float(value)

    # ==================================================================
    # Channel management
    # ==================================================================

    @property
    def channels(self) -> dict[int, OutputChannel]:
        """All channels, keyed by ``dsIndex`` (read-only view)."""
        return dict(self._channels)

    @property
    def on_channel_applied(self) -> ChannelAppliedCallback | None:
        """Callback invoked when channel values should be applied."""
        return self._on_channel_applied

    @on_channel_applied.setter
    def on_channel_applied(self, callback: ChannelAppliedCallback | None) -> None:
        self._on_channel_applied = callback

    @property
    def on_dim_channel(self) -> DimChannelCallback | None:
        """Callback invoked for dimChannel notifications (§7.3.5)."""
        return self._on_dim_channel

    @on_dim_channel.setter
    def on_dim_channel(self, callback: DimChannelCallback | None) -> None:
        self._on_dim_channel = callback

    @property
    def on_settings_changed(self) -> OutputSettingsChangedCallback | None:
        """Callback invoked when the vdSM writes ``outputSettings``."""
        return self._on_settings_changed

    @on_settings_changed.setter
    def on_settings_changed(
        self, callback: OutputSettingsChangedCallback | None
    ) -> None:
        self._on_settings_changed = callback

    def add_channel(
        self,
        channel_type: OutputChannelType | int,
        *,
        ds_index: int | None = None,
        name: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
        siunit: str | None = None,
        symbol: str | None = None,
        enum_values: dict[int, str] | None = None,
    ) -> OutputChannel:
        """Add a channel to this output.

        Parameters
        ----------
        channel_type:
            Standard or device-specific channel type ID.
        ds_index:
            Zero-based index.  Auto-assigned (next free) if omitted.
        name, min_value, max_value, resolution:
            Override defaults from :data:`CHANNEL_SPECS`.
        siunit, symbol, enum_values:
            Unit metadata and discrete value mapping for custom channel
            types.  Ignored for predefined types (spec values are used).

        Returns
        -------
        OutputChannel
            The newly created channel.

        Raises
        ------
        ValueError
            If *ds_index* is already in use.
        """
        if ds_index is None:
            ds_index = self._next_free_ds_index()
        if ds_index in self._channels:
            raise ValueError(
                f"ds_index {ds_index} already in use by channel "
                f"{self._channels[ds_index]!r}"
            )
        channel = OutputChannel(
            output=self,
            channel_type=channel_type,
            ds_index=ds_index,
            name=name,
            min_value=min_value,
            max_value=max_value,
            resolution=resolution,
            siunit=siunit,
            symbol=symbol,
            enum_values=enum_values,
        )
        self._channels[ds_index] = channel
        self._ensure_scene_channel_entries()
        logger.debug(
            "Added channel %s (dsIndex=%d) to output '%s'",
            channel.name,
            ds_index,
            self._name,
        )
        self._schedule_auto_save()
        return channel

    def remove_channel(self, ds_index: int) -> OutputChannel | None:
        """Remove a channel by dsIndex.

        Returns the removed :class:`OutputChannel` or ``None``.
        """
        ch = self._channels.pop(ds_index, None)
        if ch is not None:
            self._pending_channel_updates.pop(ds_index, None)
            # Remove channel from all scene entries.
            for entry in self._scenes.values():
                entry.get("channels", {}).pop(ds_index, None)
            self._schedule_auto_save()
        return ch

    def get_channel(self, ds_index: int) -> OutputChannel | None:
        """Look up a channel by ``dsIndex``."""
        return self._channels.get(ds_index)

    def get_channel_by_type(
        self, channel_type: OutputChannelType | int
    ) -> OutputChannel | None:
        """Look up the first channel with the given type."""
        ct = OutputChannelType(int(channel_type))
        for ch in self._channels.values():
            if ch.channel_type == ct:
                return ch
        return None

    def _next_free_ds_index(self) -> int:
        """Return the smallest unused dsIndex."""
        idx = 0
        while idx in self._channels:
            idx += 1
        return idx

    def _auto_create_channels(self) -> None:
        """Create standard channels based on the output function."""
        channel_types = FUNCTION_CHANNELS.get(self._function, [])
        for i, ct in enumerate(channel_types):
            if i not in self._channels:
                # Create channel directly (don't go through
                # add_channel to avoid auto-save during construction).
                self._channels[i] = OutputChannel(
                    output=self,
                    channel_type=ct,
                    ds_index=i,
                )

    # ==================================================================
    # Scene table management
    # ==================================================================

    def _init_default_scenes(self) -> None:
        """Populate the scene table with defaults for all 128 scene commands.

        Per ds-basics Rule 4, every digitalSTROM device must implement
        default behaviour for all 128 scene commands.  Action-only scenes
        (stepping, stop, impulse) have no stored values and are excluded.
        """
        for nr in range(128):
            if nr in _NON_VALUE_SCENES:
                continue
            self._scenes[nr] = _build_default_scene_entry(nr, self._channels)

    def _ensure_scene_channel_entries(self) -> None:
        """Ensure every scene contains entries for all current channels.

        Called after ``add_channel`` so that new channels get default
        scene values in every existing scene.
        """
        for nr, entry in self._scenes.items():
            ch_entries = entry.get("channels", {})
            is_off = nr in _OFF_SCENES
            is_on = nr in _ON_SCENES
            medium_fraction = _MEDIUM_PRESET_FRACTIONS.get(nr)
            has_default = is_off or is_on or medium_fraction is not None
            for idx, ch in self._channels.items():
                if idx not in ch_entries:
                    if is_off:
                        val: float | None = ch.min_value
                    elif is_on:
                        val = ch.max_value
                    elif medium_fraction is not None:
                        val = ch.min_value + medium_fraction * (
                            ch.max_value - ch.min_value
                        )
                    else:
                        val = ch.min_value
                    ch_entries[idx] = {
                        "value": val,
                        "dontCare": not has_default,
                        "automatic": False,
                    }
            entry["channels"] = ch_entries

    def get_scene(self, scene_nr: int) -> dict[str, Any] | None:
        """Return the scene entry for *scene_nr*, or ``None``."""
        return self._scenes.get(scene_nr)

    @property
    def scene_numbers(self) -> list:
        """Return all stored scene numbers (for wildcard expansion)."""
        return list(self._scenes.keys())

    def get_scene_properties(self) -> dict[str, Any]:
        """Return scenes in the API property format.

        The vDC API §4.10 defines the scene property as a dict keyed
        by scene number (as string), each containing ``dontCare``,
        ``ignoreLocalPriority``, ``effect``, and a ``channels`` dict
        keyed by channel type ID (as string) with per-channel
        ``value``, ``dontCare``, and ``automatic``.
        """
        result: dict[str, Any] = {}
        for nr, entry in self._scenes.items():
            ch_api: dict[str, Any] = {}
            for idx, ch_val in entry.get("channels", {}).items():
                ch = self._channels.get(idx)
                if ch is not None:
                    ch_api[str(int(ch.channel_type))] = {
                        "value": ch_val.get("value"),
                        "dontCare": ch_val.get("dontCare", False),
                        "automatic": ch_val.get("automatic", False),
                    }
            result[str(nr)] = {
                "dontCare": entry.get("dontCare", True),
                "ignoreLocalPriority": entry.get("ignoreLocalPriority", False),
                "effect": entry.get("effect", int(SceneEffect.NONE)),
                "channels": ch_api,
            }
        return result

    def apply_scenes(self, scene_data: dict[str, Any]) -> None:
        """Apply scene settings from the vdSM (``setProperty`` for scenes).

        *scene_data* is a dict keyed by scene number (string),
        each containing the API-level scene structure with ``channels``
        keyed by channel type ID (string).
        """
        for nr_str, api_entry in scene_data.items():
            nr = int(nr_str)
            entry = self._scenes.get(nr)
            if entry is None:
                entry = _build_default_scene_entry(nr, self._channels)
                self._scenes[nr] = entry

            if "dontCare" in api_entry:
                entry["dontCare"] = bool(api_entry["dontCare"])
            if "ignoreLocalPriority" in api_entry:
                entry["ignoreLocalPriority"] = bool(api_entry["ignoreLocalPriority"])
            if "effect" in api_entry:
                entry["effect"] = int(api_entry["effect"])
            if "channels" in api_entry and isinstance(api_entry["channels"], dict):
                ch_entries = entry.setdefault("channels", {})
                for ct_str, ch_val in api_entry["channels"].items():
                    ct = int(ct_str)
                    # Find the dsIndex for this channel type.
                    target_idx: int | None = None
                    for idx, ch in self._channels.items():
                        if int(ch.channel_type) == ct:
                            target_idx = idx
                            break
                    if target_idx is None:
                        continue
                    ch_entry = ch_entries.get(
                        target_idx,
                        {
                            "value": None,
                            "dontCare": True,
                            "automatic": False,
                        },
                    )
                    if isinstance(ch_val, dict):
                        if "value" in ch_val:
                            ch_entry["value"] = (
                                float(ch_val["value"])
                                if ch_val["value"] is not None
                                else None
                            )
                        if "dontCare" in ch_val:
                            ch_entry["dontCare"] = bool(ch_val["dontCare"])
                        if "automatic" in ch_val:
                            ch_entry["automatic"] = bool(ch_val["automatic"])
                    ch_entries[target_idx] = ch_entry
        self._schedule_auto_save()

    def call_scene(
        self,
        scene_nr: int,
        *,
        force: bool = False,
        group: int = 0,
    ) -> None:
        """Apply the stored scene values to the output channels.

        Parameters
        ----------
        scene_nr:
            The dS scene number to call.
        force:
            If ``True``, local priority is overridden.
        group:
            dS group number from the notification (0 = unspecified).
            Used for per-group undo tracking.

        Behaviour:

        * If the scene's global ``dontCare`` flag is set, do nothing.
        * If **local priority** is active and neither ``force`` nor the
          scene's ``ignoreLocalPriority`` flag is set, do nothing.
        * For each channel, if the channel-level ``dontCare`` is not
          set, the stored value is applied.
        * The undo snapshot is taken **before** values are changed,
          keyed by *group* so that different groups can undo
          independently.
        """
        entry = self._scenes.get(scene_nr)
        if entry is None:
            logger.debug("call_scene %d: no entry — ignoring", scene_nr)
            return

        # Scene-global dontCare → ignore entirely.
        if entry.get("dontCare", False):
            logger.debug("call_scene %d: global dontCare — ignoring", scene_nr)
            return

        # Local priority check.
        if (
            self._local_priority
            and not force
            and not entry.get("ignoreLocalPriority", False)
        ):
            logger.debug(
                "call_scene %d: blocked by local priority",
                scene_nr,
            )
            return

        # Take undo snapshot keyed by group.
        self._undo_snapshots[group] = {
            idx: ch.value for idx, ch in self._channels.items() if ch.value is not None
        }
        self._last_called_scenes[group] = scene_nr

        # Apply channel values.
        ch_entries = entry.get("channels", {})
        for idx, ch_val in ch_entries.items():
            if ch_val.get("dontCare", False):
                continue
            ch = self._channels.get(idx)
            if ch is None:
                continue
            value = ch_val.get("value")
            if value is not None:
                self.buffer_channel_value(ch, value)

        logger.debug(
            "call_scene %d: applied to output '%s'",
            scene_nr,
            self._name,
        )

    def save_scene(self, scene_nr: int) -> None:
        """Save the current channel values into the scene entry.

        This captures the current output state so that when the scene
        is later called, these values will be restored.
        """
        entry = self._scenes.get(scene_nr)
        if entry is None:
            entry = _build_default_scene_entry(scene_nr, self._channels)
            self._scenes[scene_nr] = entry

        ch_entries = entry.setdefault("channels", {})
        for idx, ch in self._channels.items():
            ch_entry = ch_entries.get(
                idx,
                {
                    "value": None,
                    "dontCare": False,
                    "automatic": False,
                },
            )
            ch_entry["value"] = ch.value
            ch_entry["dontCare"] = False
            ch_entries[idx] = ch_entry

        # Mark scene as active (not dontCare) since the user saved it.
        entry["dontCare"] = False

        self._schedule_auto_save()
        logger.debug(
            "save_scene %d: saved current values for output '%s'",
            scene_nr,
            self._name,
        )

    def undo_scene(self, scene_nr: int, *, group: int = 0) -> None:
        """Undo the last scene call if it matches *scene_nr*.

        Restores channel values to the snapshot taken before the
        matching ``call_scene``.  If the last called scene for the
        given *group* does not match, or no snapshot exists, nothing
        happens.

        Parameters
        ----------
        scene_nr:
            The scene number to undo — must match the last called
            scene for *group*.
        group:
            dS group number (0 = unspecified).  Undo is tracked
            per-group so that independent group scene calls can be
            reverted independently.
        """
        if self._last_called_scenes.get(group) != scene_nr:
            logger.debug(
                "undo_scene %d (group %d): last called was %s — ignoring",
                scene_nr,
                group,
                self._last_called_scenes.get(group),
            )
            return
        snapshot = self._undo_snapshots.get(group)
        if snapshot is None:
            return

        for idx, value in snapshot.items():
            ch = self._channels.get(idx)
            if ch is not None:
                ch.set_value_from_vdsm(value)
                ch.confirm_applied()

        logger.debug(
            "undo_scene %d (group %d): restored previous values for output '%s'",
            scene_nr,
            group,
            self._name,
        )
        del self._undo_snapshots[group]
        del self._last_called_scenes[group]

    # ==================================================================
    # dimChannel (§7.3.5)
    # ==================================================================

    async def dim_channel(
        self,
        channel: OutputChannel,
        mode: int,
        area: int = 0,
    ) -> None:
        """Handle a dimChannel notification for this output.

        Parameters
        ----------
        channel:
            The channel to dim.
        mode:
            ``1`` = start dimming up, ``-1`` = start dimming down,
            ``0`` = stop dimming.
        area:
            Area restriction (0 = none, 1..4).
        """
        if self._on_dim_channel is not None:
            try:
                await self._on_dim_channel(self, channel, mode, area)
            except Exception:
                logger.exception(
                    "on_dim_channel callback raised for output '%s'",
                    self._name,
                )

    async def call_step_scene(self, scene_nr: int) -> None:
        """Handle a stepping scene command with Rule 6 compliance.

        ds-basics Rule 6: stepping commands must be ignored when the
        primary channel is at its minimum value.  When the channel is
        above minimum the command is forwarded to the
        :attr:`on_dim_channel` callback so the integrator can drive the
        hardware.

        Parameters
        ----------
        scene_nr:
            One of the stepping scene numbers: ``DECREMENT`` (11),
            ``INCREMENT`` (12), ``AREA_x_DEC`` / ``AREA_x_INC`` (42-49),
            or ``AREA_STEPPING_CONTINUE`` (10).
        """
        if not self._channels:
            return

        # Resolve step direction.
        if scene_nr in _STEP_DOWN_SCENES:
            mode = -1
        elif scene_nr in _STEP_UP_SCENES:
            mode = 1
        elif scene_nr == int(SceneNumber.AREA_STEPPING_CONTINUE):
            mode = self._last_step_direction
            if mode == 0:
                logger.debug(
                    "step scene %d (AREA_STEPPING_CONTINUE): no prior "
                    "direction — ignored",
                    scene_nr,
                )
                return
        else:
            return

        # Primary channel: dsIndex 0, fallback to first available.
        primary_ch = self._channels.get(0)
        if primary_ch is None:
            primary_ch = next(iter(self._channels.values()), None)
        if primary_ch is None:
            return

        # Rule 6: ignore stepping when primary channel is at minimum.
        if primary_ch.value is not None and primary_ch.value <= primary_ch.min_value:
            logger.debug(
                "step scene %d: Rule 6 — primary channel at minimum "
                "(%.3f ≤ %.3f), ignored",
                scene_nr,
                primary_ch.value,
                primary_ch.min_value,
            )
            return

        # Track direction/area for subsequent AREA_STEPPING_CONTINUE.
        if scene_nr != int(SceneNumber.AREA_STEPPING_CONTINUE):
            self._last_step_direction = mode
            self._last_step_area = _STEP_SCENE_AREA.get(scene_nr, 0)

        area = (
            self._last_step_area
            if scene_nr == int(SceneNumber.AREA_STEPPING_CONTINUE)
            else _STEP_SCENE_AREA.get(scene_nr, 0)
        )
        await self.dim_channel(primary_ch, mode, area)

    async def dispatch_scene(
        self,
        scene_nr: int,
        *,
        force: bool = False,
        group: int = 0,
    ) -> None:
        """Dispatch any scene command to the appropriate handler.

        Stepping scenes (DECREMENT, INCREMENT, AREA_x_DEC/INC,
        AREA_STEPPING_CONTINUE) are routed to :meth:`call_step_scene`.
        All other scenes are handled by :meth:`call_scene` followed by
        :meth:`apply_pending_channels`.

        Parameters
        ----------
        scene_nr:
            The dS scene number.
        force:
            Passed to :meth:`call_scene` for stored-value scenes.
        group:
            dS group number; passed to :meth:`call_scene`.
        """
        if scene_nr in _ALL_STEP_SCENES:
            await self.call_step_scene(scene_nr)
        else:
            self.call_scene(scene_nr, force=force, group=group)
            await self.apply_pending_channels()

    # ==================================================================
    # apply_now buffering (§7.3.9)
    # ==================================================================

    def buffer_channel_value(
        self,
        channel: OutputChannel,
        value: float,
    ) -> None:
        """Buffer a channel value change from the vdSM.

        Called by the setOutputChannelValue handler.  The value is
        stored on the channel and in the pending-updates buffer.
        Hardware callback is NOT invoked yet.
        """
        channel.set_value_from_vdsm(value)
        self._pending_channel_updates[channel.ds_index] = value

    async def apply_pending_channels(self) -> None:
        """Apply all buffered channel value changes to hardware.

        Invoked when ``apply_now=True`` (or omitted) on the final
        ``setOutputChannelValue`` of a batch.  Calls the
        ``on_channel_applied`` callback with a dict of
        ``{OutputChannelType: value}`` and then confirms all pending
        channels.
        """
        if not self._pending_channel_updates:
            return

        # Build the callback argument: {OutputChannelType: value}.
        updates: dict[OutputChannelType | int, float] = {}
        for ds_index, value in self._pending_channel_updates.items():
            ch = self._channels.get(ds_index)
            if ch is not None:
                updates[ch.channel_type] = value

        # Invoke the device callback.
        if self._on_channel_applied is not None:
            try:
                await self._on_channel_applied(self, updates)
            except Exception:
                logger.exception(
                    "on_channel_applied callback raised for output '%s'",
                    self._name,
                )

        # Confirm all pending channels.
        for ds_index in list(self._pending_channel_updates):
            ch = self._channels.get(ds_index)
            if ch is not None:
                ch.confirm_applied()

        self._pending_channel_updates.clear()

    # ==================================================================
    # Push channel state to vdSM (device → dSS direction)
    # ==================================================================

    async def _push_channel_state(self, channel: OutputChannel) -> None:
        """Push a single channel's state to the vdSM.

        Called by :meth:`OutputChannel.update_value` when ``pushChanges``
        is set on this output.  Sends a ``VDC_SEND_PUSH_NOTIFICATION``
        with a ``channelStates`` payload keyed by :meth:`_channel_key`,
        consistent with the keying used in ``getProperty`` responses.
        """
        session = self._session
        if session is None:
            logger.debug(
                "No active session — skipping push for channel '%s' on output '%s'",
                channel.name,
                self._name,
            )
            return

        state_dict = channel.get_state_properties()
        push_tree: dict[str, Any] = {
            "channelStates": {
                self._channel_key(channel): state_dict,
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
                "Pushed channelStates[%s] for vdSD %s: %s",
                channel.name,
                self._vdsd.dsuid,
                state_dict,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "Failed to push channelStates[%s] for vdSD %s: %s",
                channel.name,
                self._vdsd.dsuid,
                exc,
            )

    async def push_settings(self) -> None:
        """Push the current ``outputSettings`` to the vdSM.

        Sends a ``VDC_SEND_PUSH_NOTIFICATION`` with the full
        ``outputSettings`` property subtree.  A no-op if the session is
        not active or the vdSD has not been announced.
        """
        session = self._session
        if session is None:
            logger.debug(
                "No active session — skipping push_settings for output '%s'",
                self._name,
            )
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "vdSD not announced — skipping push_settings for output '%s'",
                self._name,
            )
            return

        settings_dict = self.get_settings_properties()
        push_tree: dict[str, Any] = {"outputSettings": settings_dict}

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "Pushed outputSettings for vdSD %s: %s",
                self._vdsd.dsuid,
                settings_dict,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "Failed to push outputSettings for vdSD %s: %s",
                self._vdsd.dsuid,
                exc,
            )

    # ==================================================================
    # Channel property dicts (for getProperty responses)
    # ==================================================================

    def _channel_key(self, ch: OutputChannel) -> str:
        """Return the channel name as the canonical property-dict key (API v3+).

        All output functions use the channel name (e.g. ``"brightness"``,
        ``"shadePositionOutside"``) as the outer element key, matching the
        vDC API v3+ ``getApiId()`` format.  Numeric backward-compat
        resolution for incoming queries is handled by :class:`_ChannelCompatDict`
        and :meth:`channel_by_key`.
        """
        return ch.name

    def channel_by_key(self, key: str) -> OutputChannel | None:
        """Return the channel matching *key*, with numeric backward-compat.

        Resolution order:

        1. Canonical channel name (e.g. ``"brightness"``, ``"shadePositionOutside"``).
        2. Numeric key ``"0"`` — spec-defined alias for the standard channel of
           the device's color class (ds-basics §7 table 7).  Resolved via
           :data:`~pydsvdcapi.output_channel.COLOR_CLASS_STANDARD_CHANNEL` using
           ``self._default_group`` (the output's ``ColorClass`` / application
           group ID).  Falls back to the first registered channel if the color
           class is not in the table.
        3. Channel type integer as string — old API v1/v2 wire format
           (e.g. ``"1"`` → brightness, ``"7"`` → shadePositionOutside).

        Used by ``setOutputChannelValue``, ``dimChannel``, and
        ``setProperty channelStates`` handlers in ``vdc_host.py``.
        """
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        # 1. Canonical name — fast path, covers all API v3+ callers.
        for ch in self._channels.values():
            if ch.name == key:
                return ch
        try:
            numeric = int(key)
        except ValueError:
            return None
        # 2. "0" = standard channel for color class (ds-basics §7 table 7).
        if numeric == 0 and self._default_group is not None:
            std_ct = COLOR_CLASS_STANDARD_CHANNEL.get(self._default_group)
            if std_ct is not None:
                found = self.get_channel_by_type(std_ct)
                if found is not None:
                    return found
            # fallback: first registered channel
            return self._channels.get(min(self._channels)) if self._channels else None
        # 3. Channel type number (API v1/v2 primary format).
        for ch in self._channels.values():
            if int(ch.channel_type) == numeric:
                return ch
        return None

    def get_channel_descriptions(self) -> dict[str, Any]:
        """Return the ``channelDescriptions`` sub-tree.

        Keys are channel name strings (e.g. ``"brightness"``,
        ``"shadePositionOutside"``), matching the vDC API v3+ channel ID
        format. Backward-compat numeric key resolution for incoming queries is
        provided by :class:`_ChannelCompatDict`.

        Wildcard queries iterate ``dict.items()`` and only see canonical keys;
        no numeric duplicates appear in responses.
        """
        return _ChannelCompatDict(
            {
                self._channel_key(ch): ch.get_description_properties()
                for ch in self._channels.values()
            },
            self,
        )

    def get_channel_settings(self) -> dict[str, Any]:
        """Return the ``channelSettings`` sub-tree.

        Keys are channel name strings (e.g. ``"brightness"``,
        ``"shadePositionOutside"``), matching the vDC API v3+ channel ID
        format. Backward-compat numeric key resolution for incoming queries is
        provided by :class:`_ChannelCompatDict`.

        Wildcard queries iterate ``dict.items()`` and only see canonical keys;
        no numeric duplicates appear in responses.
        """
        return _ChannelCompatDict(
            {
                self._channel_key(ch): ch.get_settings_properties()
                for ch in self._channels.values()
            },
            self,
        )

    def get_channel_states(self) -> dict[str, Any]:
        """Return the ``channelStates`` sub-tree.

        Keys are channel name strings (e.g. ``"brightness"``,
        ``"shadePositionOutside"``), matching the vDC API v3+ channel ID
        format. Backward-compat numeric key resolution for incoming queries is
        provided by :class:`_ChannelCompatDict`.

        Wildcard queries iterate ``dict.items()`` and only see canonical keys;
        no numeric duplicates appear in responses.
        """
        return _ChannelCompatDict(
            {
                self._channel_key(ch): ch.get_state_properties()
                for ch in self._channels.values()
            },
            self,
        )

    # ==================================================================
    # Property dicts (for getProperty responses)
    # ==================================================================

    def get_description_properties(self) -> dict[str, Any]:
        """Return the ``outputDescription`` property dict.

        Keys match the vDC API property names (§4.8.1).

        ``name``, ``defaultGroup``, and ``activeCoolingMode`` are **optional**:
        they are only included when explicitly set by the caller.
        ``maxPower`` is always present (``-1.0`` when undefined).
        """
        desc: dict[str, Any] = {
            "function": int(self._function),
            "outputUsage": int(self._output_usage),
            "variableRamp": self._variable_ramp,
            "maxPower": self._max_power,
        }
        if self._name is not None:
            desc["name"] = self._name
        if self._default_group is not None:
            desc["defaultGroup"] = self._default_group
        if self._active_cooling_mode is not None:
            desc["activeCoolingMode"] = self._active_cooling_mode
        return desc

    def get_settings_properties(self) -> dict[str, Any]:
        """Return the ``outputSettings`` property dict.

        Keys match the vDC API property names (§4.8.2).

        ``activeGroup`` is **optional** — included only when explicitly set.

        ``groups`` follows vDC API: group 0 (the standard/implicit
        group) is always emitted as ``true``. Member groups (1–63) are emitted
        as ``true`` if in :attr:`groups`, ``false`` (or omitted) if not.

        ``onThreshold`` is included if and only if ``function`` is ON_OFF (0);
        when function is ON_OFF and no value was supplied the spec default of
        50.0 % is used.

        Light, climate, and shadow timing settings are only included when the
        device's ``primaryGroup`` matches the relevant application class AND
        the value has been explicitly set.
        """
        settings: dict[str, Any] = {
            "mode": int(self._mode),
            "pushChanges": self._push_changes,
        }

        # activeGroup — optional, only include when explicitly set.
        if self._active_group is not None:
            settings["activeGroup"] = self._active_group

        all_groups = self._groups | {0}
        settings["groups"] = {str(gid): True for gid in sorted(all_groups)}

        pg = (
            int(self._vdsd.primary_group) if self._vdsd.primary_group is not None else 0
        )

        # onThreshold: only for ON_OFF function (mandatory for function 0).
        if int(self._function) == int(OutputFunction.ON_OFF):
            settings["onThreshold"] = (
                self._on_threshold if self._on_threshold is not None else 50.0
            )

        # Light-specific settings (primaryGroup 1 = yellow/lights).
        if pg == 1:
            if self._min_brightness is not None:
                settings["minBrightness"] = self._min_brightness
            if self._dim_time_up is not None:
                settings["dimTimeUp"] = self._dim_time_up
            if self._dim_time_down is not None:
                settings["dimTimeDown"] = self._dim_time_down
            if self._dim_time_up_alt1 is not None:
                settings["dimTimeUpAlt1"] = self._dim_time_up_alt1
            if self._dim_time_down_alt1 is not None:
                settings["dimTimeDownAlt1"] = self._dim_time_down_alt1
            if self._dim_time_up_alt2 is not None:
                settings["dimTimeUpAlt2"] = self._dim_time_up_alt2
            if self._dim_time_down_alt2 is not None:
                settings["dimTimeDownAlt2"] = self._dim_time_down_alt2

        # Climate-control settings (primaryGroup 3 = blue/heating).
        if pg == 3:
            if self._heating_system_capability is not None:
                settings["heatingSystemCapability"] = int(
                    self._heating_system_capability
                )
            if self._heating_system_type is not None:
                settings["heatingSystemType"] = int(self._heating_system_type)

        # Shadow motor timing settings: only for grey positional outputs.
        # Always emitted when both conditions hold; falls back to vDC API defaults.
        if pg == 2 and int(self._function) == int(OutputFunction.POSITIONAL):
            settings["openTime"] = (
                self._open_time
                if self._open_time is not None
                else _SHADOW_DEFAULT_OPEN_TIME
            )
            settings["closeTime"] = (
                self._close_time
                if self._close_time is not None
                else _SHADOW_DEFAULT_CLOSE_TIME
            )
            settings["angleOpenTime"] = (
                self._angle_open_time
                if self._angle_open_time is not None
                else _SHADOW_DEFAULT_ANGLE_OPEN_TIME
            )
            settings["angleCloseTime"] = (
                self._angle_close_time
                if self._angle_close_time is not None
                else _SHADOW_DEFAULT_ANGLE_CLOSE_TIME
            )
            settings["stopDelayTime"] = (
                self._stop_delay_time
                if self._stop_delay_time is not None
                else _SHADOW_DEFAULT_STOP_DELAY_TIME
            )

        # Include any extra (firmware-specific) settings that arrived via
        # setProperty but are not in the standard known-key set.
        settings.update(self._extra_settings)

        return settings

    def get_state_properties(self) -> dict[str, Any]:
        """Return the ``outputState`` property dict.

        Keys match the vDC API property names (§4.8.3).

        ``localPriority`` and ``transitionTime`` (float, seconds) are always
        present, matching vDC API base output behaviour.

        ``error`` is included for all device types (always included,
        useful for diagnostics).
        """
        return {
            "localPriority": self._local_priority,
            "transitionTime": self._transition_time,
            "error": int(self._error),
        }

    # ==================================================================
    # Settings mutation (from vdc_host setProperty)
    # ==================================================================

    def apply_settings(self, settings: dict[str, Any]) -> None:
        """Apply a dict of writable settings.

        Called by :meth:`VdcHost._apply_vdsd_set_property` when the
        vdSM sends a ``VDSM_SEND_SET_PROPERTY`` for
        ``outputSettings``.  Unknown keys are stored in
        :attr:`_extra_settings` and returned by
        :meth:`get_settings_properties`.

        Recognised shadow motor timing keys: ``openTime``, ``closeTime``,
        ``angleOpenTime``, ``angleCloseTime``, ``stopDelayTime``.
        Pass ``None`` to clear a previously set value.
        """
        if "mode" in settings:
            self._mode = OutputMode(int(settings["mode"]))
        if "activeGroup" in settings:
            self._active_group = int(settings["activeGroup"])
        if "pushChanges" in settings:
            self._push_changes = bool(settings["pushChanges"])
        if "groups" in settings:
            grp_data = settings["groups"]
            if isinstance(grp_data, dict):
                for gid_str, val in grp_data.items():
                    gid = int(gid_str)
                    if gid == 0:
                        continue  # group 0 is implicit in the wire format; never store it
                    if val:
                        self._groups.add(gid)
                    else:
                        self._groups.discard(gid)
        if "onThreshold" in settings:
            val = settings["onThreshold"]
            self._on_threshold = float(val) if val is not None else None
        if "minBrightness" in settings:
            val = settings["minBrightness"]
            self._min_brightness = float(val) if val is not None else None
        if "dimTimeUp" in settings:
            val = settings["dimTimeUp"]
            self._dim_time_up = int(val) if val is not None else None
        if "dimTimeDown" in settings:
            val = settings["dimTimeDown"]
            self._dim_time_down = int(val) if val is not None else None
        if "dimTimeUpAlt1" in settings:
            val = settings["dimTimeUpAlt1"]
            self._dim_time_up_alt1 = int(val) if val is not None else None
        if "dimTimeDownAlt1" in settings:
            val = settings["dimTimeDownAlt1"]
            self._dim_time_down_alt1 = int(val) if val is not None else None
        if "dimTimeUpAlt2" in settings:
            val = settings["dimTimeUpAlt2"]
            self._dim_time_up_alt2 = int(val) if val is not None else None
        if "dimTimeDownAlt2" in settings:
            val = settings["dimTimeDownAlt2"]
            self._dim_time_down_alt2 = int(val) if val is not None else None
        if "heatingSystemCapability" in settings:
            val = settings["heatingSystemCapability"]
            self._heating_system_capability = (
                HeatingSystemCapability(int(val)) if val is not None else None
            )
        if "heatingSystemType" in settings:
            val = settings["heatingSystemType"]
            self._heating_system_type = (
                HeatingSystemType(int(val)) if val is not None else None
            )
        if "openTime" in settings:
            val = settings["openTime"]
            self._open_time = float(val) if val is not None else None
        if "closeTime" in settings:
            val = settings["closeTime"]
            self._close_time = float(val) if val is not None else None
        if "angleOpenTime" in settings:
            val = settings["angleOpenTime"]
            self._angle_open_time = float(val) if val is not None else None
        if "angleCloseTime" in settings:
            val = settings["angleCloseTime"]
            self._angle_close_time = float(val) if val is not None else None
        if "stopDelayTime" in settings:
            val = settings["stopDelayTime"]
            self._stop_delay_time = float(val) if val is not None else None

        # Collect any keys not handled above into _extra_settings so they
        # can be round-tripped through persistence and returned by
        # get_settings_properties().
        for key, val in settings.items():
            if key not in _KNOWN_SETTING_KEYS:
                self._extra_settings[key] = val

        self._schedule_auto_save()

    def apply_state(self, state: dict[str, Any]) -> None:
        """Apply a dict of writable state properties.

        Called by :meth:`VdcHost._apply_vdsd_set_property` when the
        vdSM sends a ``VDSM_SEND_SET_PROPERTY`` for ``outputState``.

        Recognised keys: ``localPriority``, ``transitionTime``.
        Unknown keys are silently ignored.
        """
        if "localPriority" in state:
            self._local_priority = bool(state["localPriority"])
        if "transitionTime" in state:
            val = state["transitionTime"]
            self._transition_time = float(val) if val is not None else 0.0

    # ==================================================================
    # Persistence (property tree)
    # ==================================================================

    def get_property_tree(self) -> dict[str, Any]:
        """Return a serialisable dict for YAML persistence.

        Includes description + settings + channel descriptions.
        State is volatile and excluded.
        """
        tree: dict[str, Any] = {
            # Description.
            "function": int(self._function),
            "outputUsage": int(self._output_usage),
            "name": self._name,
            "defaultGroup": self._default_group,
            "variableRamp": self._variable_ramp,
            # Settings.
            "mode": int(self._mode),
            "activeGroup": self._active_group,
            "pushChanges": self._push_changes,
        }

        # Optional description properties.
        tree["maxPower"] = self._max_power
        if self._active_cooling_mode is not None:
            tree["activeCoolingMode"] = self._active_cooling_mode

        # Groups — persist as list of IDs.
        if self._groups:
            tree["groups"] = sorted(self._groups)

        # Optional light settings.
        if self._on_threshold is not None:
            tree["onThreshold"] = self._on_threshold
        if self._min_brightness is not None:
            tree["minBrightness"] = self._min_brightness
        if self._dim_time_up is not None:
            tree["dimTimeUp"] = self._dim_time_up
        if self._dim_time_down is not None:
            tree["dimTimeDown"] = self._dim_time_down
        if self._dim_time_up_alt1 is not None:
            tree["dimTimeUpAlt1"] = self._dim_time_up_alt1
        if self._dim_time_down_alt1 is not None:
            tree["dimTimeDownAlt1"] = self._dim_time_down_alt1
        if self._dim_time_up_alt2 is not None:
            tree["dimTimeUpAlt2"] = self._dim_time_up_alt2
        if self._dim_time_down_alt2 is not None:
            tree["dimTimeDownAlt2"] = self._dim_time_down_alt2

        # Optional climate settings.
        if self._heating_system_capability is not None:
            tree["heatingSystemCapability"] = int(self._heating_system_capability)
        if self._heating_system_type is not None:
            tree["heatingSystemType"] = int(self._heating_system_type)

        # Optional shadow motor timing settings.
        if self._open_time is not None:
            tree["openTime"] = self._open_time
        if self._close_time is not None:
            tree["closeTime"] = self._close_time
        if self._angle_open_time is not None:
            tree["angleOpenTime"] = self._angle_open_time
        if self._angle_close_time is not None:
            tree["angleCloseTime"] = self._angle_close_time
        if self._stop_delay_time is not None:
            tree["stopDelayTime"] = self._stop_delay_time

        # Extra (firmware-specific) settings — persisted alongside known keys.
        if self._extra_settings:
            tree.update(self._extra_settings)

        # Channels (description metadata only, not values).
        if self._channels:
            tree["channels"] = [
                ch.get_property_tree() for ch in self._channels.values()
            ]

        # Scenes — persist as dict keyed by scene number (as string).
        # Only persist scenes that differ from the pure default
        # (i.e. all scenes, since they may be modified at runtime).
        if self._scenes:
            scenes_tree: dict[str, Any] = {}
            for nr, entry in self._scenes.items():
                s: dict[str, Any] = {
                    "dontCare": entry.get("dontCare", True),
                    "ignoreLocalPriority": entry.get("ignoreLocalPriority", False),
                    "effect": entry.get("effect", 0),
                }
                ch_data: dict[str, Any] = {}
                for idx, ch_val in entry.get("channels", {}).items():
                    ch_data[str(idx)] = {
                        "value": ch_val.get("value"),
                        "dontCare": ch_val.get("dontCare", False),
                        "automatic": ch_val.get("automatic", False),
                    }
                s["channels"] = ch_data
                scenes_tree[str(nr)] = s
            tree["scenes"] = scenes_tree

        return tree

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted property tree dict.

        Restores description + settings + channel descriptions.
        State is NOT restored (it is volatile).
        """
        # Description properties.
        if "function" in state:
            self._function = OutputFunction(int(state["function"]))
        if "outputUsage" in state:
            self._output_usage = OutputUsage(int(state["outputUsage"]))
        if "name" in state:
            self._name = state["name"]
        if "defaultGroup" in state:
            self._default_group = int(state["defaultGroup"])
        if "variableRamp" in state:
            self._variable_ramp = bool(state["variableRamp"])
        if "maxPower" in state:
            self._max_power = float(state["maxPower"])
        if "activeCoolingMode" in state:
            self._active_cooling_mode = bool(state["activeCoolingMode"])

        # Settings properties.
        if "mode" in state:
            self._mode = OutputMode(int(state["mode"]))
        if "activeGroup" in state:
            self._active_group = int(state["activeGroup"])
        if "pushChanges" in state:
            self._push_changes = bool(state["pushChanges"])
        if "groups" in state:
            grp = state["groups"]
            if isinstance(grp, list):
                self._groups = set(grp)
            elif isinstance(grp, dict):
                # Handle dict format.
                self._groups = {int(k) for k, v in grp.items() if v}
        if "onThreshold" in state:
            self._on_threshold = float(state["onThreshold"])
        if "minBrightness" in state:
            self._min_brightness = float(state["minBrightness"])
        if "dimTimeUp" in state:
            self._dim_time_up = int(state["dimTimeUp"])
        if "dimTimeDown" in state:
            self._dim_time_down = int(state["dimTimeDown"])
        if "dimTimeUpAlt1" in state:
            self._dim_time_up_alt1 = int(state["dimTimeUpAlt1"])
        if "dimTimeDownAlt1" in state:
            self._dim_time_down_alt1 = int(state["dimTimeDownAlt1"])
        if "dimTimeUpAlt2" in state:
            self._dim_time_up_alt2 = int(state["dimTimeUpAlt2"])
        if "dimTimeDownAlt2" in state:
            self._dim_time_down_alt2 = int(state["dimTimeDownAlt2"])
        if "heatingSystemCapability" in state:
            self._heating_system_capability = HeatingSystemCapability(
                int(state["heatingSystemCapability"])
            )
        if "heatingSystemType" in state:
            self._heating_system_type = HeatingSystemType(
                int(state["heatingSystemType"])
            )
        if "openTime" in state:
            self._open_time = float(state["openTime"])
        if "closeTime" in state:
            self._close_time = float(state["closeTime"])
        if "angleOpenTime" in state:
            self._angle_open_time = float(state["angleOpenTime"])
        if "angleCloseTime" in state:
            self._angle_close_time = float(state["angleCloseTime"])
        if "stopDelayTime" in state:
            self._stop_delay_time = float(state["stopDelayTime"])

        # Restore extra (firmware-specific) settings: any key in the
        # persisted tree that is not a known description, settings, or
        # structural key is treated as an extra setting.
        for key, val in state.items():
            if key not in _KNOWN_TREE_KEYS:
                self._extra_settings[key] = val

        # Restore channels.
        if "channels" in state:
            self._channels.clear()
            for ch_state in state["channels"]:
                idx = ch_state.get("dsIndex", 0)
                ch_type = ch_state.get("channelType", 0)
                ch = OutputChannel(
                    output=self,
                    channel_type=ch_type,
                    ds_index=idx,
                )
                ch._apply_state(ch_state)
                self._channels[idx] = ch
        else:
            # If no channels stored, re-auto-create from function.
            self._channels.clear()
            self._auto_create_channels()

        # Restore scenes: always start from all-128 defaults so that scenes
        # not present in an older YAML (written before the range(128) expansion)
        # still get correct default values after upgrade.  Then overlay any
        # persisted scene entries on top.
        self._scenes.clear()
        self._init_default_scenes()
        if "scenes" in state:
            for nr_str, s in state["scenes"].items():
                nr = int(nr_str)
                ch_entries: dict[int, dict[str, Any]] = {}
                for idx_str, ch_val in s.get("channels", {}).items():
                    idx = int(idx_str)
                    ch_entries[idx] = {
                        "value": (
                            float(ch_val["value"])
                            if ch_val.get("value") is not None
                            else None
                        ),
                        "dontCare": bool(ch_val.get("dontCare", False)),
                        "automatic": bool(ch_val.get("automatic", False)),
                    }
                self._scenes[nr] = {
                    "dontCare": bool(s.get("dontCare", True)),
                    "ignoreLocalPriority": bool(s.get("ignoreLocalPriority", False)),
                    "effect": int(s.get("effect", int(SceneEffect.NONE))),
                    "channels": ch_entries,
                }

    # ==================================================================
    # Session management
    # ==================================================================

    def start_session(self, session: VdcSession) -> None:
        """Store the active session reference.

        Called when the owning vdSD is announced.
        """
        self._session = session

    def stop_session(self) -> None:
        """Clear the session reference.

        Called when the owning vdSD is vanished or the session
        disconnects.
        """
        self._session = None

    # ==================================================================
    # Auto-save helper
    # ==================================================================

    def _schedule_auto_save(self) -> None:
        """Trigger auto-save via the owning vdSD → Device chain."""
        device = getattr(self._vdsd, "_device", None)
        if device is not None:
            device._schedule_auto_save()

    # ==================================================================
    # Dunder
    # ==================================================================

    def __repr__(self) -> str:
        return (
            f"Output(function={self._function.name}, "
            f"mode={self._mode.name}, "
            f"name={self._name!r})"
        )
