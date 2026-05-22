#!/usr/bin/env python3
"""Full showcase VDC — 27 virtual devices across all dS device classes.

Demonstrates all major device configurations:
  1  Joker (black) — single pushbutton
  2  Joker (black) — 4-way pushbutton
  3  Joker (black) — binary input (motion sensor)
  4  Joker (black) — two sensors (CO + CO2)
  5  Light (yellow) — simple switched
  6  Light (yellow) — dimmable
  7  Light (yellow) — dim + color temperature
  8  Light (yellow) — full RGBW
  9  Blinds (grey) — position + blade angle
 10  Awnings (grey) — positional
 11  Heating valve (blue) — PWM
 12  Audio (cyan)
 13  Video (magenta)
 14  Alarm horn (red)
 15  Door lock (green) — relay
 16  Smart plug (black) — relay
 17  Extended power plug (black) — power level channel
 18  Ventilation unit (blue)
 19  Motorised window (blue)
 20  FCU / fan-coil (blue)
 21  Room heating controller (blue) — receives heatingLevel control value
 22  Apartment ventilation (blue group 64) — 0-100 % fan speed
 23  Switched light (yellow) + button directly controlling output
 24  Switched light (yellow) + freely configurable button (black)
 25  White device — GTIN, black relay output, property, event, action
 26  Yellow device — GTIN, simple light output, property, event, action
 27  Oven (white) — GTIN, comprehensive states/events/actions/properties

Console commands (press Enter after typing):
  e       raise an event (submenu lists all event-capable devices)
  r       restart: vanish all → wait 20 s → reconnect (tests persistence)
  q       quit cleanly: vanish, stop, delete persistence files
  x       exit without cleanup (keeps persistence for next run)

Sensors / states change automatically ~every 5 minutes (mocked).

Usage:
    python examples/full_showcase.py [--port PORT] [--gtin GTIN] [--debug]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydsvdcapi import (
    BinaryInput,
    BinaryInputType,
    BinaryInputUsage,
    ButtonElementID,
    ButtonFunction,
    ButtonInput,
    ButtonMode,
    ButtonType,
    ColorClass,
    ColorGroup,
    Device,
    DeviceEvent,
    DsUid,
    DsUidNamespace,
    Output,
    OutputChannelType,
    OutputFunction,
    OutputMode,
    OutputUsage,
    SensorInput,
    SensorType,
    SensorUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)
from pydsvdcapi.actions import ActionParameter, DeviceActionDescription, StandardAction
from pydsvdcapi.device_property import (
    PROPERTY_TYPE_NUMERIC,
    PROPERTY_TYPE_STRING,
    DeviceProperty,
)
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.enums import (
    HeatingSystemCapability,
    HeatingSystemType,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8444
STATE_FILE = Path("/tmp/pydsvdcapi_full_showcase.yaml")

# Replace with a GTIN registered in your dSS VdcDb for hasActions=True.
# Devices 25/26 use GTIN_AB; device 27 uses GTIN_OVEN.
GTIN_AB = "gs1:(01)2345678901289"
GTIN_OVEN = (
    "gs1:(01)2345678901289"  # same placeholder — use a real oven GTIN if available
)

VENDOR_NAME = "pyDSvDCAPI Showcase"
VENDOR_GUID = "gs1:(01)0000000000001"

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
GREY = "\033[90m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
CLEAR = "\033[2J\033[H"


def _col(c: str, t: str) -> str:
    return f"{c}{t}{RESET}"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _ColourFmt(logging.Formatter):
    _MAP = {
        logging.DEBUG: GREY,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, r: logging.LogRecord) -> str:
        c = self._MAP.get(r.levelno, "")
        ts = self.formatTime(r, "%H:%M:%S")
        return f"{GREY}{ts}{RESET} {c}{r.getMessage()}{RESET}"


def setup_logging(debug: bool = False) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_ColourFmt())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    root.setLevel(logging.DEBUG if debug else logging.WARNING)


# ---------------------------------------------------------------------------
# Device info container
# ---------------------------------------------------------------------------


@dataclass
class DevInfo:
    idx: int  # 1-based device number shown in UI
    name: str
    device: Device
    vdsd: Vdsd
    events: list[DeviceEvent] = field(default_factory=list)
    sensors: list[SensorInput] = field(default_factory=list)
    binary_inputs: list[BinaryInput] = field(default_factory=list)
    states: list[DeviceState] = field(default_factory=list)
    output: Output | None = None


# ---------------------------------------------------------------------------
# Notification queue (DSS→VDC messages shown in console)
# ---------------------------------------------------------------------------

_notif_q: asyncio.Queue = asyncio.Queue()


def _notify(msg: str) -> None:
    """Put a DSS-received notification into the display queue (thread-safe)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(_notif_q.put_nowait, msg)
        else:
            _notif_q.put_nowait(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Device builder helpers
# ---------------------------------------------------------------------------


def _dsuid(tag: str) -> DsUid:
    return DsUid.from_name_in_space(f"showcase-{tag}", DsUidNamespace.VDC)


def _vdsd(
    device: Device,
    group: ColorGroup,
    name: str,
    model: str,
    gtin: str | None = None,
    hw_idx: int = 0,
) -> Vdsd:
    # hardware_guid must be unique per device instance — used by dSS to track device identity
    # across restarts and for name distribution.  hardware_model_guid identifies the model class.
    # Both are required for GTIN/oem_model_guid to work and for the device name to propagate.
    return Vdsd(
        device=device,
        primary_group=group,
        subdevice_index=0,
        name=name,
        model=model,
        model_version="1.0.0",
        vendor_name=VENDOR_NAME,
        vendor_guid=VENDOR_GUID,
        oem_model_guid=gtin,
        hardware_guid=f"mac-address:00:00:00:00:00:{hw_idx:02x}",
        hardware_model_guid="ean:(01)0000000000001",
        zone_id=0,
    )


def _output(
    vdsd: Vdsd,
    func: OutputFunction,
    group: int,
    mode: OutputMode | None = None,
    usage: OutputUsage = OutputUsage.ROOM,
    out_groups: set | None = None,
    **kwargs,
) -> Output:
    """Create and attach an Output to *vdsd*.

    *mode* defaults to None so Output auto-derives the correct value from
    *func* (ON_OFF→BINARY, CUSTOM/INTERNALLY_CONTROLLED→DISABLED, else GRADUAL).
    *out_groups* overrides the group set when the output group differs from
    the device's primary group.
    """
    groups = out_groups if out_groups is not None else {group}
    out = Output(
        vdsd=vdsd,
        function=func,
        output_usage=usage,
        name="output",
        default_group=group,
        active_group=group,
        groups=groups,
        mode=mode,
        push_changes=True,
        **kwargs,
    )
    vdsd.set_output(out)
    return out


def _channel_callback(dev_name: str):
    async def cb(out: Output, updates: dict[OutputChannelType, float]) -> None:
        parts = ", ".join(
            f"{OutputChannelType(t).name if t in OutputChannelType._value2member_map_ else t}={v:.1f}"
            for t, v in updates.items()
        )
        _notify(f"[{dev_name}] output → {parts}")

    return cb


def _control_value_callback(dev_name: str):
    async def cb(vdsd: Vdsd, name: str, value: float, group, zone_id) -> None:
        _notify(
            f"[{dev_name}] control value: {name}={value:.2f} (group={group}, zone={zone_id})"
        )

    return cb


def _action_callback(dev_name: str, states: dict[str, DeviceState] | None = None):
    async def cb(vdsd: Vdsd, action_id: str, params: dict) -> None:
        p = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "–"
        _notify(f"[{dev_name}] ACTION '{action_id}'  params: {p}")
        if states and action_id in states:
            await states[action_id].update_value(
                params.get("mode", params.get("value", 0))
            )

    return cb


def _add_standard_dynamic(vdsd: Vdsd, dev_name: str):
    """Add one state, property, event and action to any device (for GTIN devices)."""
    state = DeviceState(
        vdsd=vdsd,
        ds_index=0,
        name="status",
        options={0: "idle", 1: "active", 2: "error"},
        description="Device status",
    )
    vdsd.add_device_state(state)

    prop = DeviceProperty(
        vdsd=vdsd,
        ds_index=0,
        name="uptimeSecs",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0,
        max_value=2**31 - 1,
        resolution=1,
        siunit="s",
        default=0,
        description="Uptime in seconds",
    )
    vdsd.add_device_property(prop)

    event = DeviceEvent(
        vdsd=vdsd, ds_index=0, name="alert", description="Device alert event"
    )
    vdsd.add_device_event(event)

    param = ActionParameter(name="mode", type="string", default="idle")
    action = DeviceActionDescription(
        vdsd=vdsd,
        ds_index=0,
        name="setStatus",
        params=[param],
        description="Set device status",
    )
    vdsd.add_device_action_description(action)

    std1 = StandardAction(
        vdsd=vdsd,
        ds_index=0,
        name="std.setStatus.idle",
        action="setStatus",
        params={"mode": "idle"},
    )
    std2 = StandardAction(
        vdsd=vdsd,
        ds_index=1,
        name="std.setStatus.active",
        action="setStatus",
        params={"mode": "active"},
    )
    vdsd.add_standard_action(std1)
    vdsd.add_standard_action(std2)

    vdsd.on_invoke_action = _action_callback(dev_name)
    return state, prop, event, action


# ===========================================================================
# Device builders — one function per device
# ===========================================================================


def build_d01_joker_single_button(vdc: Vdc, idx: int) -> DevInfo:
    name = "Joker Single Button"
    device = Device(vdc=vdc, dsuid=_dsuid("d01"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D01", hw_idx=idx)
    device.add_vdsd(v)

    btn = ButtonInput(
        vdsd=v,
        ds_index=0,
        name="Button",
        button_id=0,
        button_type=ButtonType.SINGLE_PUSHBUTTON,
        button_element_id=ButtonElementID.CENTER,
        group=int(ColorClass.NONE),
        function=ButtonFunction.ROOM,
        mode=ButtonMode.STANDARD,
    )
    v.add_button_input(btn)

    v.add_model_feature("pushbutton")
    v.add_model_feature(
        "pushbdevice"
    )  # "Device Push Button" option in color group dropdown
    v.add_model_feature("pushbarea")  # "Area Push Button" option
    v.add_model_feature("jokerconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v)


def build_d02_joker_4way(vdc: Vdc, idx: int) -> DevInfo:
    name = "Joker 4-Way Button"
    device = Device(vdc=vdc, dsuid=_dsuid("d02"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D02", hw_idx=idx)
    device.add_vdsd(v)

    # 4 independent SINGLE_PUSHBUTTON inputs, each with its own button_id.
    # Each is independently assignable in the dSS configurator.
    # FOUR_WAY_NAVIGATION with a shared button_id would represent a joystick unit;
    # for a panel with 4 separate physical buttons use distinct button_ids instead.
    for i, bname in enumerate(["Button 1", "Button 2", "Button 3", "Button 4"]):
        btn = ButtonInput(
            vdsd=v,
            ds_index=i,
            name=bname,
            button_id=i,
            button_type=ButtonType.SINGLE_PUSHBUTTON,
            button_element_id=ButtonElementID.CENTER,
            group=int(ColorClass.NONE),
            function=ButtonFunction.ROOM,
            mode=ButtonMode.STANDARD,
        )
        v.add_button_input(btn)

    v.add_model_feature("pushbutton")
    v.add_model_feature("pushbdevice")
    v.add_model_feature("pushbarea")
    v.add_model_feature("pushbadvanced")
    v.add_model_feature(
        "pushbcombined"
    )  # "Combined" mode option for multi-button groups
    v.add_model_feature("jokerconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v)


def build_d03_joker_binary_motion(vdc: Vdc, idx: int) -> DevInfo:
    name = "Joker Motion Sensor"
    device = Device(vdc=vdc, dsuid=_dsuid("d03"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D03", hw_idx=idx)
    device.add_vdsd(v)

    bi = BinaryInput(
        vdsd=v,
        ds_index=0,
        name="Motion",
        sensor_function=BinaryInputType.MOTION,
        input_usage=BinaryInputUsage.ROOM_CLIMATE,
    )
    v.add_binary_input(bi)

    v.add_model_feature("jokerconfig")
    # derive_model_features() adds "akmsensor" automatically for any binary input.
    # "akminput" and "akmdelay" are NOT supported for TCP/IP VDC devices —
    # they configure behaviour via DS485 bus only and are never forwarded to
    # the VDC. Attempting to add them raises ValueError.
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, binary_inputs=[bi])


def build_d04_joker_co_sensors(vdc: Vdc, idx: int) -> DevInfo:
    name = "Joker CO/CO2 Sensors"
    device = Device(vdc=vdc, dsuid=_dsuid("d04"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D04", hw_idx=idx)
    device.add_vdsd(v)

    si_co = SensorInput(
        vdsd=v,
        ds_index=0,
        name="CO concentration",
        sensor_type=SensorType.CO_CONCENTRATION,
        sensor_usage=SensorUsage.ROOM,
        min_value=0,
        max_value=1000,
        resolution=1,
    )
    si_co2 = SensorInput(
        vdsd=v,
        ds_index=1,
        name="CO2 concentration",
        sensor_type=SensorType.CO2_CONCENTRATION,
        sensor_usage=SensorUsage.ROOM,
        min_value=400,
        max_value=5000,
        resolution=1,
    )
    v.add_sensor_input(si_co)
    v.add_sensor_input(si_co2)

    v.add_model_feature("jokerconfig")
    # D04 has only SensorInputs (not BinaryInputs), so "akmsensor" does not
    # apply here. "akminput" and "akmdelay" are not supported for TCP/IP VDC
    # devices regardless.
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, sensors=[si_co, si_co2])


def build_d05_light_switched(vdc: Vdc, idx: int) -> DevInfo:
    name = "Light Switched"
    device = Device(vdc=vdc, dsuid=_dsuid("d05"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D05", hw_idx=idx)
    device.add_vdsd(v)

    # ON_OFF (switched): mode=DEFAULT lets dSS pick; push_changes=True so dSS
    # gets the initial value after announce (avoids the "red error" on first open).
    out = _output(v, OutputFunction.ON_OFF, int(ColorClass.LIGHTS))
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature(
        "outvalue8"
    )  # 8-bit output editing slider in "Edit Device Values"
    v.add_model_feature(
        "outconfigswitch"
    )  # on-threshold slider ("switch on above X%") in Advanced Settings
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d06_light_dimmed(vdc: Vdc, idx: int) -> DevInfo:
    name = "Light Dimmed"
    device = Device(vdc=vdc, dsuid=_dsuid("d06"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D06", hw_idx=idx)
    device.add_vdsd(v)

    # DIMMER: mode=GRADUAL (2) required — DEFAULT(127) causes the "Edit Device Values"
    # UI to not open and the mobile slider to stop responding for color-capable devices.
    # Empirically verified: GRADUAL is the correct mode for all dimmer outputs.
    out = _output(
        v,
        OutputFunction.DIMMER,
        int(ColorClass.LIGHTS),
        mode=OutputMode.GRADUAL,
        variable_ramp=True,
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    # NOTE: dimmodeconfig is NOT added here — it only makes sense for physical hardware
    # dimmer types (RMS vs phase-control) and causes confusing UI / errors for VDC devices.
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d07_light_dimmed_cct(vdc: Vdc, idx: int) -> DevInfo:
    name = "Light Dim+CCT"
    device = Device(vdc=vdc, dsuid=_dsuid("d07"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D07", hw_idx=idx)
    device.add_vdsd(v)

    # DIMMER_COLOR_TEMP: mode=GRADUAL required (same reason as D06).
    # Auto-creates brightness (dsIndex=0, name="brightness") + colortemp (dsIndex=1, name="colortemp").
    out = _output(
        v,
        OutputFunction.DIMMER_COLOR_TEMP,
        int(ColorClass.LIGHTS),
        mode=OutputMode.GRADUAL,
        variable_ramp=True,
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature(
        "outputchannels"
    )  # needed so dSS shows the CT channel alongside brightness
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d08_light_rgbw(vdc: Vdc, idx: int) -> DevInfo:
    name = "Light RGBW"
    device = Device(vdc=vdc, dsuid=_dsuid("d08"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D08", hw_idx=idx)
    device.add_vdsd(v)

    # FULL_COLOR_DIMMER: mode=GRADUAL required (empirically verified working config).
    # Auto-creates 6 channels keyed by name in the property tree:
    # "brightness"(dsIndex=0), "colortemp"(dsIndex=1), "hue"(dsIndex=2),
    # "saturation"(dsIndex=3), "cieX"(dsIndex=4), "cieY"(dsIndex=5).
    # colortemp at dsIndex=1 is required for the configurator CT slider.
    # modelFeatures match the empirically verified working set.
    out = _output(
        v,
        OutputFunction.FULL_COLOR_DIMMER,
        int(ColorClass.LIGHTS),
        mode=OutputMode.GRADUAL,
        variable_ramp=True,
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature(
        "outputchannels"
    )  # required: tells dSS there are multiple independent channels
    v.add_model_feature("blink")
    v.add_model_feature("identification")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d09_blinds_positional(vdc: Vdc, idx: int) -> DevInfo:
    name = "Blinds w/ Blade Angle"
    device = Device(vdc=vdc, dsuid=_dsuid("d09"))
    v = _vdsd(device, ColorGroup.GREY, name, "Showcase-D09", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.BLINDS))
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("shadebladeang")
    v.add_model_feature("ledauto")
    v.add_model_feature("identification")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d10_awnings(vdc: Vdc, idx: int) -> DevInfo:
    name = "Awnings"
    device = Device(vdc=vdc, dsuid=_dsuid("d10"))
    # primaryGroup=GREY(2): outdoor shade / awning device.
    # activeGroup=BLINDS(2): standard shades Application Group (1–63 range, valid in groups).
    v = _vdsd(device, ColorGroup.GREY, name, "Showcase-D10", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.BLINDS))
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("locationconfig")  # orientation dropdown
    v.add_model_feature(
        "windprotectionconfigawning"
    )  # awning-specific wind protection config
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d11_heating_valve_pwm(vdc: Vdc, idx: int) -> DevInfo:
    name = "Heating Valve PWM"
    device = Device(vdc=vdc, dsuid=_dsuid("d11"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D11", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.HEATING),
        heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        heating_system_type=HeatingSystemType.FLOOR_HEATING,
    )
    out.add_channel(OutputChannelType.HEATING_POWER)
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature(
        "outvalue8"
    )  # enables "Edit Device Values" slider for valve position
    v.add_model_feature(
        "heatinggroup"
    )  # "Application" dropdown: manual heating / automatic
    # NOTE: heatingprops is NOT included — it opens "Device Properties Climate" which
    # tries to write hardware-only valve timer registers via ds485 (setValveTimerMode,
    # class_:3 index:69). VDC devices cannot respond to these bus-level calls → errors.
    # Use heatingprops only if you can handle those config registers yourself.
    v.add_model_feature("pwmvalue")  # shows PWM status/info in "Edit Device Values"
    v.add_model_feature("valvetype")  # "Attached terminal device" type dropdown
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d12_audio(vdc: Vdc, idx: int) -> DevInfo:
    name = "Audio Device"
    device = Device(vdc=vdc, dsuid=_dsuid("d12"))
    v = _vdsd(device, ColorGroup.CYAN, name, "Showcase-D12", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.AUDIO))
    out.add_channel(OutputChannelType.AUDIO_VOLUME)
    out.add_channel(OutputChannelType.POWER_STATE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("ledauto")
    v.add_model_feature("blink")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d13_video(vdc: Vdc, idx: int) -> DevInfo:
    name = "Video Device"
    device = Device(vdc=vdc, dsuid=_dsuid("d13"))
    v = _vdsd(device, ColorGroup.MAGENTA, name, "Showcase-D13", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.VIDEO))
    # POWER_STATE: 0=off, 1=standby, 2=on, 3=active (resolution=1 → integer steps)
    out.add_channel(OutputChannelType.POWER_STATE)
    # VIDEO_INPUT_SOURCE: 0-5 selects the physical input (HDMI1, HDMI2, AV, …)
    out.add_channel(OutputChannelType.VIDEO_INPUT_SOURCE, min_value=0, max_value=5)
    # VIDEO_STATION: selects TV channel/station number, 0-999
    out.add_channel(OutputChannelType.VIDEO_STATION, min_value=0, max_value=999)
    # AUDIO_VOLUME: 0-100 % relative volume for the video device's built-in speaker
    out.add_channel(OutputChannelType.AUDIO_VOLUME)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d14_alarm_horn(vdc: Vdc, idx: int) -> DevInfo:
    name = "Alarm Horn"
    device = Device(vdc=vdc, dsuid=_dsuid("d14"))
    v = _vdsd(device, ColorGroup.RED, name, "Showcase-D14", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v, OutputFunction.ON_OFF, int(ColorClass.SECURITY), mode=OutputMode.BINARY
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("blink")
    v.add_model_feature("identification")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d15_door_lock(vdc: Vdc, idx: int) -> DevInfo:
    name = "Door Lock"
    device = Device(vdc=vdc, dsuid=_dsuid("d15"))
    v = _vdsd(device, ColorGroup.GREEN, name, "Showcase-D15", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v, OutputFunction.ON_OFF, int(ColorClass.ACCESS), mode=OutputMode.BINARY
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d16_smart_plug_black(vdc: Vdc, idx: int) -> DevInfo:
    name = "Smart Plug (Black)"
    device = Device(vdc=vdc, dsuid=_dsuid("d16"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D16", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v, OutputFunction.ON_OFF, int(ColorClass.JOKER), mode=OutputMode.BINARY
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("jokerconfig")
    v.add_model_feature("optypeconfig")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d17_power_plug_extended(vdc: Vdc, idx: int) -> DevInfo:
    name = "Power Plug Extended"
    device = Device(vdc=vdc, dsuid=_dsuid("d17"))
    v = _vdsd(device, ColorGroup.BLACK, name, "Showcase-D17", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.JOKER))
    out.add_channel(OutputChannelType.POWER_LEVEL)
    out.add_channel(OutputChannelType.POWER_STATE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("jokerconfig")
    v.add_model_feature("optypeconfig")
    v.add_model_feature("consumption")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d18_ventilation(vdc: Vdc, idx: int) -> DevInfo:
    name = "Ventilation Unit"
    device = Device(vdc=vdc, dsuid=_dsuid("d18"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D18", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.VENTILATION))
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY)
    out.add_channel(OutputChannelType.AIR_FLOW_DIRECTION)
    out.add_channel(OutputChannelType.AIR_LOUVER_POSITION)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("ventconfig")
    v.add_model_feature("ledauto")
    v.add_model_feature("identification")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d19_motorised_window(vdc: Vdc, idx: int) -> DevInfo:
    name = "Motorised Window"
    device = Device(vdc=vdc, dsuid=_dsuid("d19"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D19", hw_idx=idx)
    device.add_vdsd(v)

    # Windows use shade position channel; activeGroup=WINDOW(11) distinguishes from outdoor blinds
    out = _output(v, OutputFunction.POSITIONAL, int(ColorClass.WINDOW))
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d20_fcu(vdc: Vdc, idx: int) -> DevInfo:
    name = "FCU Fan-Coil"
    device = Device(vdc=vdc, dsuid=_dsuid("d20"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D20", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.RECIRCULATION),
        active_cooling_mode=True,
        heating_system_capability=HeatingSystemCapability.HEATING_AND_COOLING,
        heating_system_type=HeatingSystemType.CONVECTOR_ACTIVE,
    )
    out.add_channel(OutputChannelType.HEATING_POWER)
    out.add_channel(OutputChannelType.COOLING_CAPACITY)
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY)
    out.add_channel(OutputChannelType.AIR_LOUVER_POSITION)
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("heatinggroup")
    v.add_model_feature("heatingprops")
    v.add_model_feature("fcu")
    v.add_model_feature("ventconfig")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d21_room_heating_settemp(vdc: Vdc, idx: int) -> DevInfo:
    """Room heating controller — dSS sends heatingLevel (0-100 %) as
    a control value; device translates this to a temperature setpoint request."""
    name = "Room Heating (setTemp)"
    device = Device(vdc=vdc, dsuid=_dsuid("d21"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D21", hw_idx=idx)
    device.add_vdsd(v)

    # INTERNALLY_CONTROLLED: output channels managed by dSS temperature control;
    # the device receives heatingLevel (0-100%) via on_control_value.
    out = _output(
        v,
        OutputFunction.INTERNALLY_CONTROLLED,
        int(ColorClass.HEATING),
        heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        heating_system_type=HeatingSystemType.FLOOR_HEATING,
    )
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("heatinggroup")
    v.add_model_feature("heatingprops")
    v.add_model_feature("temperatureoffset")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d22_apartment_ventilation(vdc: Vdc, idx: int) -> DevInfo:
    name = "Apartment Ventilation"
    device = Device(vdc=vdc, dsuid=_dsuid("d22"))
    v = _vdsd(device, ColorGroup.BLUE, name, "Showcase-D22", hw_idx=idx)
    device.add_vdsd(v)

    # activeGroup=APARTMENT_VENTILATION(64) is a global app group — cannot appear in groups.
    # groups contains VENTILATION(10) for room-level scene participation.
    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.APARTMENT_VENTILATION),
        out_groups={int(ColorClass.VENTILATION)},
    )
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY, min_value=0, max_value=100)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("ventconfig")
    v.add_model_feature("apartmentapplication")
    v.add_model_feature("ledauto")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d23_light_with_bound_button(vdc: Vdc, idx: int) -> DevInfo:
    """Switched light whose button directly controls this device's output
    (ButtonFunction.DEVICE binds the button to its own output group)."""
    name = "Light + Bound Button"
    device = Device(vdc=vdc, dsuid=_dsuid("d23"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D23", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.ON_OFF, int(ColorClass.LIGHTS))
    out.on_channel_applied = _channel_callback(name)

    btn = ButtonInput(
        vdsd=v,
        ds_index=0,
        name="On/Off",
        button_id=0,
        button_type=ButtonType.ON_OFF_SWITCH,
        button_element_id=ButtonElementID.DOWN,
        group=int(ColorClass.LIGHTS),
        function=ButtonFunction.DEVICE,
        mode=ButtonMode.STANDARD,
    )
    btn2 = ButtonInput(
        vdsd=v,
        ds_index=1,
        name="On",
        button_id=0,
        button_type=ButtonType.ON_OFF_SWITCH,
        button_element_id=ButtonElementID.UP,
        group=int(ColorClass.LIGHTS),
        function=ButtonFunction.DEVICE,
        mode=ButtonMode.STANDARD,
    )
    v.add_button_input(btn)
    v.add_button_input(btn2)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("ledauto")
    v.add_model_feature("pushbutton")
    v.add_model_feature("pushbdevice")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d24_light_with_free_button(vdc: Vdc, idx: int) -> DevInfo:
    """Switched light with an independently configurable button
    (ButtonFunction.APP / BLACK group — freely assignable in dSS UI)."""
    name = "Light + Free Button"
    device = Device(vdc=vdc, dsuid=_dsuid("d24"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D24", hw_idx=idx)
    device.add_vdsd(v)

    out = _output(v, OutputFunction.ON_OFF, int(ColorClass.LIGHTS))
    out.on_channel_applied = _channel_callback(name)

    btn = ButtonInput(
        vdsd=v,
        ds_index=0,
        name="Free Button",
        button_id=0,
        button_type=ButtonType.SINGLE_PUSHBUTTON,
        button_element_id=ButtonElementID.CENTER,
        # group=BLACK, function=APP → freely configurable in dSS
        group=int(ColorClass.NONE),
        function=ButtonFunction.APP,
        mode=ButtonMode.STANDARD,
    )
    v.add_button_input(btn)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("ledauto")
    v.add_model_feature("pushbutton")
    v.add_model_feature("pushbadvanced")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_d25_white_gtin_relay(vdc: Vdc, idx: int) -> DevInfo:
    name = "White GTIN Relay"
    device = Device(vdc=vdc, dsuid=_dsuid("d25"))
    v = _vdsd(device, ColorGroup.WHITE, name, "Showcase-D25", gtin=GTIN_AB, hw_idx=idx)
    device.add_vdsd(v)

    # White device (single device) with a black relay output
    out = _output(
        v, OutputFunction.ON_OFF, int(ColorClass.NONE), mode=OutputMode.BINARY
    )
    out.on_channel_applied = _channel_callback(name)

    state, prop, event, action = _add_standard_dynamic(v, name)

    v.add_model_feature("highlevel")
    v.add_model_feature("jokerconfig")
    v.derive_model_features()
    return DevInfo(
        idx=idx,
        name=name,
        device=device,
        vdsd=v,
        output=out,
        events=[event],
        states=[state],
    )


def build_d26_yellow_gtin_light(vdc: Vdc, idx: int) -> DevInfo:
    name = "Yellow GTIN Light"
    device = Device(vdc=vdc, dsuid=_dsuid("d26"))
    v = _vdsd(device, ColorGroup.YELLOW, name, "Showcase-D26", gtin=GTIN_AB, hw_idx=idx)
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.DIMMER,
        int(ColorClass.LIGHTS),
        mode=OutputMode.GRADUAL,
        variable_ramp=True,
    )
    out.on_channel_applied = _channel_callback(name)

    state, prop, event, action = _add_standard_dynamic(v, name)

    v.add_model_feature("dontcare")
    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("ledauto")
    v.add_model_feature("highlevel")
    v.derive_model_features()
    return DevInfo(
        idx=idx,
        name=name,
        device=device,
        vdsd=v,
        output=out,
        events=[event],
        states=[state],
    )


def build_d27_oven(vdc: Vdc, idx: int) -> DevInfo:
    """Oven (white) with comprehensive states, properties, events, and actions.

    NOTE: GTIN_OVEN must exist in the dSS VdcDb device table for the
    Activities tab (hasActions) to appear. With dynamicDefinitions=True
    the descriptions shown in the UI come from the VDC, not the VdcDb.
    Replace GTIN_OVEN at the top of this file with a real oven GTIN.
    """
    name = "Smart Oven"
    device = Device(vdc=vdc, dsuid=_dsuid("d27"))
    v = _vdsd(
        device, ColorGroup.WHITE, name, "Showcase-D27-Oven", gtin=GTIN_OVEN, hw_idx=idx
    )
    device.add_vdsd(v)

    # Oven has no standard dS output — use CUSTOM/DISABLED
    out = Output(
        vdsd=v,
        function=OutputFunction.CUSTOM,
        mode=OutputMode.DISABLED,
        name="oven-output",
        default_group=int(ColorClass.NONE),
        active_group=int(ColorClass.NONE),
        groups={int(ColorClass.NONE)},
        output_usage=OutputUsage.USER,
    )
    v.set_output(out)

    # ---- States ----
    state_mode = DeviceState(
        vdsd=v,
        ds_index=0,
        name="ovenMode",
        options={0: "off", 1: "heating", 2: "ready", 3: "error"},
        description="Current oven operating mode",
    )
    state_door = DeviceState(
        vdsd=v,
        ds_index=1,
        name="doorState",
        options={0: "closed", 1: "open"},
        description="Oven door state",
    )
    state_heat = DeviceState(
        vdsd=v,
        ds_index=2,
        name="heatingElement",
        options={0: "off", 1: "on"},
        description="Heating element active",
    )
    v.add_device_state(state_mode)
    v.add_device_state(state_door)
    v.add_device_state(state_heat)

    # ---- Properties ----
    prop_temp = DeviceProperty(
        vdsd=v,
        ds_index=0,
        name="currentTemperature",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0,
        max_value=300,
        resolution=1,
        siunit="°C",
        default=20,
        description="Current oven cavity temperature in °C",
    )
    prop_set = DeviceProperty(
        vdsd=v,
        ds_index=1,
        name="setTemperature",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0,
        max_value=300,
        resolution=5,
        siunit="°C",
        default=0,
        description="Target temperature in °C",
    )
    prop_prog = DeviceProperty(
        vdsd=v,
        ds_index=2,
        name="currentProgram",
        type=PROPERTY_TYPE_STRING,
        default="off",
        description="Active cooking program name",
    )
    prop_timer = DeviceProperty(
        vdsd=v,
        ds_index=3,
        name="timerRemaining",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0,
        max_value=7200,
        resolution=1,
        siunit="s",
        default=0,
        description="Remaining timer in seconds",
    )
    v.add_device_property(prop_temp)
    v.add_device_property(prop_set)
    v.add_device_property(prop_prog)
    v.add_device_property(prop_timer)

    # ---- Events ----
    ev_timer = DeviceEvent(
        vdsd=v, ds_index=0, name="timerExpired", description="Cooking timer has expired"
    )
    ev_ready = DeviceEvent(
        vdsd=v,
        ds_index=1,
        name="preheatReady",
        description="Oven reached target temperature (preheat done)",
    )
    ev_door = DeviceEvent(
        vdsd=v,
        ds_index=2,
        name="doorChanged",
        description="Oven door was opened or closed",
    )
    ev_error = DeviceEvent(
        vdsd=v, ds_index=3, name="error", description="Oven encountered an error"
    )
    v.add_device_event(ev_timer)
    v.add_device_event(ev_ready)
    v.add_device_event(ev_door)
    v.add_device_event(ev_error)

    # ---- Actions ----
    prog_param = ActionParameter(name="program", type="string", default="off")
    temp_param = ActionParameter(name="temperature", type="number", default=180)
    timer_param = ActionParameter(name="timerSeconds", type="number", default=1800)

    act_start = DeviceActionDescription(
        vdsd=v,
        ds_index=0,
        name="startCooking",
        params=[prog_param, temp_param, timer_param],
        description="Start cooking with given program and temperature",
    )
    act_stop = DeviceActionDescription(
        vdsd=v,
        ds_index=1,
        name="stopCooking",
        params=[],
        description="Stop cooking and turn off heating",
    )
    act_timer = DeviceActionDescription(
        vdsd=v,
        ds_index=2,
        name="setTimer",
        params=[timer_param],
        description="Set cooking timer",
    )
    v.add_device_action_description(act_start)
    v.add_device_action_description(act_stop)
    v.add_device_action_description(act_timer)

    std_off = StandardAction(
        vdsd=v, ds_index=0, name="std.off", action="stopCooking", params={}
    )
    std_180 = StandardAction(
        vdsd=v,
        ds_index=1,
        name="std.bake180",
        action="startCooking",
        params={"program": "bake", "temperature": 180, "timerSeconds": 0},
    )
    std_200 = StandardAction(
        vdsd=v,
        ds_index=2,
        name="std.bake200",
        action="startCooking",
        params={"program": "bake", "temperature": 200, "timerSeconds": 0},
    )
    std_grill = StandardAction(
        vdsd=v,
        ds_index=3,
        name="std.grill",
        action="startCooking",
        params={"program": "grill", "temperature": 220, "timerSeconds": 0},
    )
    v.add_standard_action(std_off)
    v.add_standard_action(std_180)
    v.add_standard_action(std_200)
    v.add_standard_action(std_grill)

    # Action callback
    async def oven_action(vdsd_ref: Vdsd, action_id: str, params: dict) -> None:
        p = ", ".join(f"{k}={val}" for k, val in params.items()) if params else "–"
        _notify(f"[{name}] ACTION '{action_id}'  {p}")
        if action_id == "startCooking":
            prog = params.get("program", "bake")
            temp = params.get("temperature", 180)
            prop_prog.value = prog
            prop_set.value = float(temp)
            await state_mode.update_value("heating")
        elif action_id == "stopCooking":
            prop_prog.value = "off"
            prop_set.value = 0.0
            await state_mode.update_value("off")
        elif action_id == "setTimer":
            prop_timer.value = float(params.get("timerSeconds", 0))

    v.on_invoke_action = oven_action

    v.add_model_feature("highlevel")
    v.add_model_feature("jokerconfig")
    v.derive_model_features()

    return DevInfo(
        idx=idx,
        name=name,
        device=device,
        vdsd=v,
        events=[ev_timer, ev_ready, ev_door, ev_error],
        states=[state_mode, state_door, state_heat],
    )


# ===========================================================================
# Build all 27 devices
# ===========================================================================


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_d01_joker_single_button,
        build_d02_joker_4way,
        build_d03_joker_binary_motion,
        build_d04_joker_co_sensors,
        build_d05_light_switched,
        build_d06_light_dimmed,
        build_d07_light_dimmed_cct,
        build_d08_light_rgbw,
        build_d09_blinds_positional,
        build_d10_awnings,
        build_d11_heating_valve_pwm,
        build_d12_audio,
        build_d13_video,
        build_d14_alarm_horn,
        build_d15_door_lock,
        build_d16_smart_plug_black,
        build_d17_power_plug_extended,
        build_d18_ventilation,
        build_d19_motorised_window,
        build_d20_fcu,
        build_d21_room_heating_settemp,
        build_d22_apartment_ventilation,
        build_d23_light_with_bound_button,
        build_d24_light_with_free_button,
        build_d25_white_gtin_relay,
        build_d26_yellow_gtin_light,
        build_d27_oven,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic changes (~every 5 minutes)
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Randomly update sensors / binary inputs / states about every 5 min."""
    while True:
        delay = random.uniform(280, 320)
        await asyncio.sleep(delay)

        session = host.session
        if session is None or not session.is_active:
            continue

        # Pick a random device that has something to update
        candidates = [d for d in devices if d.sensors or d.binary_inputs or d.states]
        if not candidates:
            continue
        dev = random.choice(candidates)

        try:
            if dev.sensors:
                si = random.choice(dev.sensors)
                rng = si.max_value - si.min_value
                val = si.min_value + random.uniform(0, rng)
                await si.update_value(round(val, 1), session)
                _notify(f"[MOCK] [{dev.name}] sensor '{si.name}' → {val:.1f}")

            elif dev.binary_inputs:
                bi = random.choice(dev.binary_inputs)
                new_val = random.choice([True, False])
                await bi.update_value(new_val, session)
                _notify(
                    f"[MOCK] [{dev.name}] binary input → {'active' if new_val else 'inactive'}"
                )

            elif dev.states:
                st = random.choice(dev.states)
                opts = list(st.options.keys())
                val = random.choice(opts)
                await st.update_value(val)
                _notify(
                    f"[MOCK] [{dev.name}] state '{st.name}' → {st.options.get(val, val)}"
                )

        except Exception as exc:
            logging.getLogger("showcase").debug("Mock change error: %s", exc)


# ===========================================================================
# Initial value push — avoids "red error" on first open in configurator
# ===========================================================================


async def push_initial_output_values(devices: list[DevInfo]) -> None:
    """Push a safe initial value (min_value or 0) for every output channel.

    Without this, the dSS configurator marks the output value as an error
    (shown in red) until the user sets a value from the dSS side at least once.
    push_changes=True on all outputs ensures the push notification reaches dSS.
    """
    for di in devices:
        if di.output is None:
            continue
        for ch in di.output._channels.values():
            with contextlib.suppress(Exception):
                await ch.update_value(ch.min_value)


# ===========================================================================
# Console
# ===========================================================================

_stdin_q: asyncio.Queue = asyncio.Queue()


def _start_stdin_thread(loop: asyncio.AbstractEventLoop) -> None:
    def _reader():
        for line in sys.stdin:
            asyncio.run_coroutine_threadsafe(_stdin_q.put(line.strip()), loop)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def _print_menu(devices: list[DevInfo], connected: bool) -> None:
    status = _col(GREEN, "CONNECTED") if connected else _col(RED, "WAITING…")
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"  pyDSvDCAPI Full Showcase VDC  |  {status}")
    print(f"  {GREY}27 devices announced{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")
    print(f"  {BOLD}e{RESET}  Raise event (submenu)")
    print(f"  {BOLD}r{RESET}  Restart (vanish → wait 20 s → reconnect)")
    print(f"  {BOLD}q{RESET}  Quit clean (vanish + delete persistence files)")
    print(f"  {BOLD}x{RESET}  Exit (keep persistence for restart test)")
    print(f"{BOLD}{'=' * 60}{RESET}")
    print("Option: ", end="", flush=True)


def _print_event_menu(devices: list[DevInfo]) -> None:
    event_devs = [(d, ev) for d in devices for ev in d.events]
    if not event_devs:
        print("No devices have events configured.")
        return
    print(f"\n{BOLD}Available events:{RESET}")
    for i, (d, ev) in enumerate(event_devs):
        print(f"  {BOLD}{i + 1:2d}{RESET}  [{d.name}] → {ev.name}")
    print(f"  {BOLD} 0{RESET}  All events at once")
    print(f"  {BOLD} b{RESET}  Back to main menu")
    print("Event number: ", end="", flush=True)
    return event_devs


async def _raise_event_interactive(devices: list[DevInfo]) -> None:
    event_devs = [(d, ev) for d in devices for ev in d.events]
    _print_event_menu(devices)
    try:
        raw = await asyncio.wait_for(_stdin_q.get(), timeout=30.0)
    except asyncio.TimeoutError:
        return
    if raw.lower() == "b":
        return
    if raw == "0":
        for d, ev in event_devs:
            await ev.raise_event()
            print(f"  → [{d.name}] raised '{ev.name}'")
        return
    try:
        n = int(raw) - 1
        if 0 <= n < len(event_devs):
            d, ev = event_devs[n]
            await ev.raise_event()
            print(f"  → [{d.name}] raised '{ev.name}'")
    except (ValueError, IndexError):
        print("Invalid selection.")


async def console_loop(
    host: VdcHost,
    devices: list[DevInfo],
    restart_event: asyncio.Event,
    quit_event: asyncio.Event,
    clean_event: asyncio.Event,
) -> None:
    connected = host.session is not None and host.session.is_active

    while True:
        # Check session state
        connected = host.session is not None and host.session.is_active
        _print_menu(devices, connected)

        # Wait for user input OR a DSS notification
        stdin_wait = asyncio.ensure_future(_stdin_q.get())
        notif_wait = asyncio.ensure_future(_notif_q.get())

        done, pending = await asyncio.wait(
            {stdin_wait, notif_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

        if notif_wait in done:
            # DSS sent us something — show it for 10s (collecting more)
            msg = notif_wait.result()
            print(f"\n{BOLD}{YELLOW}--- DSS NOTIFICATION ---{RESET}")
            print(f"  {msg}")
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    extra = await asyncio.wait_for(_notif_q.get(), timeout=remaining)
                    print(f"  {extra}")
                except asyncio.TimeoutError:
                    break
            print(f"{BOLD}{YELLOW}--- Returning to menu ---{RESET}")
            # Put back any stdin that arrived during notification window
            # (we'll get it on next loop iteration from the queue)
            continue

        # User typed something
        if stdin_wait in done:
            cmd = stdin_wait.result().lower().strip()
        else:
            continue

        if cmd == "e":
            await _raise_event_interactive(devices)

        elif cmd == "r":
            print(f"\n{YELLOW}Restart requested — vanishing devices…{RESET}")
            restart_event.set()
            return

        elif cmd == "q":
            print(f"\n{YELLOW}Clean quit — vanishing and removing persistence…{RESET}")
            clean_event.set()
            quit_event.set()
            return

        elif cmd == "x":
            print(f"\n{YELLOW}Exiting (keeping persistence)…{RESET}")
            quit_event.set()
            return

        else:
            print(f"Unknown command '{cmd}'. Use e / r / q / x.")


# ===========================================================================
# Session wait helper
# ===========================================================================


async def wait_for_session(host: VdcHost, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if host.session is not None and host.session.is_active:
            return True
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.5)


# ===========================================================================
# Main
# ===========================================================================


async def main(port: int, debug: bool) -> bool:
    """Run the showcase VDC. Returns True if restart is requested."""
    setup_logging(debug=debug)

    host = VdcHost(
        port=port,
        model="pyDSvDCAPI Full Showcase",
        name="full-showcase-host",
        vendor_name=VENDOR_NAME,
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-full-showcase",
        name="Full Showcase VDC",
        model="pydsvdcapi-showcase",
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    devices = build_all_devices(vdc)
    print(f"\n{BOLD}Full Showcase VDC — {len(devices)} devices built{RESET}")
    print(f"Listening on port {port}. Waiting for dSS/vdSM…")

    loop = asyncio.get_running_loop()
    _start_stdin_thread(loop)

    await host.start()

    connected = await wait_for_session(host, timeout=180.0)
    if not connected:
        print(f"{RED}No connection within 3 minutes — exiting.{RESET}")
        await host.stop()
        return False

    session = host.session
    print(f"{GREEN}Session established — announcing {len(devices)} devices…{RESET}")

    for di in devices:
        await di.device.announce(session)

    print(f"{GREEN}All devices announced.{RESET}")

    # Push initial output values for all output devices.
    # Without this, dSS configurator shows outputs in error state (red) until
    # the user manually sets a value from dSS — which is poor UX.
    await push_initial_output_values(devices)
    print(f"{GREEN}Initial output values pushed.{RESET}")

    # Push initial states for GTIN devices so the hardware tab shows live values
    # immediately after announcement (matches dynamic_features_working.py behaviour).
    d25 = devices[24]  # index 24 = device 25
    d26 = devices[25]  # index 25 = device 26
    oven = devices[26]  # index 26 = device 27
    for di in (d25, d26):
        for st in di.states:
            await st.update_value(
                list(st.options.keys())[0]
            )  # first option = idle/inactive
    for st in oven.states:
        if st.name == "ovenMode":
            await st.update_value("off")
        elif st.name == "doorState":
            await st.update_value("closed")
        elif st.name == "heatingElement":
            await st.update_value("off")

    # Start mock changes background task
    mock_task = asyncio.create_task(mock_changes_loop(devices, host))

    restart_event = asyncio.Event()
    quit_event = asyncio.Event()
    clean_event = asyncio.Event()

    console_task = asyncio.create_task(
        console_loop(host, devices, restart_event, quit_event, clean_event)
    )

    await quit_event.wait()
    mock_task.cancel()
    console_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await mock_task

    # Vanish all devices
    if session.is_active:
        print("Vanishing devices…")
        for di in devices:
            with contextlib.suppress(Exception):
                await di.device.vanish(session)

    await host.stop()

    if clean_event.is_set():
        for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
            if p.exists():
                p.unlink()
                print(f"Deleted {p}")

    if restart_event.is_set():
        print(f"{YELLOW}Waiting 20 s before restart…{RESET}")
        await asyncio.sleep(20)
        return True  # signal caller to restart

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--gtin-ab",
        default=GTIN_AB,
        dest="gtin_ab",
        help="GTIN for devices 25 and 26 (gs1:(01)... format)",
    )
    parser.add_argument(
        "--gtin-oven",
        default=GTIN_OVEN,
        dest="gtin_oven",
        help="GTIN for device 27 oven (gs1:(01)... format)",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    # Allow overriding GTINs from CLI
    GTIN_AB = args.gtin_ab
    GTIN_OVEN = args.gtin_oven

    while True:
        try:
            should_restart = asyncio.run(main(port=args.port, debug=args.debug))
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{RESET}")
            break
        if not should_restart:
            break
