#!/usr/bin/env python3
"""Developer Guide — Comprehensive Simulation Demo.

This script is the **central reference** for the pydsvdcapi developer
guide.  It exercises the full API surface through five virtual devices
and an interactive menu, with detailed inline commentary explaining
every concept.

The five virtual devices
========================

1. **Yellow — Simple pushbutton + on/off brightness output**
   Demonstrates:  ``ButtonInput`` (single), ``Output(ON_OFF)``,
   auto-created ``BRIGHTNESS`` channel, basic ``derive_model_features()``.

2. **Yellow — 2-way rocker + dimmer (brightness + colour temperature)**
   Demonstrates:  ``create_button_group()`` (two-way), ``Output(DIMMER_COLOR_TEMP)``,
   auto-created ``BRIGHTNESS`` + ``COLOR_TEMPERATURE`` channels.

3. **Grey — Garage-door contact + blinds output**
   Demonstrates:  ``BinaryInput(GARAGE_DOOR_OPEN)``, ``Output(POSITIONAL)`` with
   manual ``add_channel()`` (shade position + blade angle),
   ``ColorClass.GREY``.

4. **Yellow — Illumination + active-power sensors + RGBW output**
   Demonstrates:  two ``SensorInput`` instances (``ILLUMINATION``,
   ``ACTIVE_POWER``), ``Output(FULL_COLOR_DIMMER)`` with six
   auto-created colour channels, uplink converter.

5. **White — Custom device property + event + custom action**
   Demonstrates:  ``DeviceProperty``, ``DeviceEvent``, ``CustomAction``,
   ``DeviceActionDescription``, ``ActionParameter``,
   ``OutputFunction.CUSTOM`` + ``OutputMode.DISABLED``
   (the SingleDevice / ActionOutputBehaviour pattern).

Interactive menu
================

::

    [1] Simulate shutdown & restore  —  persist, tear down, rebuild
    [2] Create converter             —  attach W→kW converter on device 4
    [3] Template workflow            —  save device 1, instantiate copy
    [4] Fire event (device 5)        —  push event to dSS
    [5] End simulation & cleanup     —  vanish, goodbye, delete files
    [6] Toggle logging               —  show library debug output

Run from the project root::

    python examples/developer_guide_demo.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import sys
from pathlib import Path
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Make the package importable when running from the repository root.
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ---------------------------------------------------------------------------
# pydsvdcapi imports
# ---------------------------------------------------------------------------
# The top-level ``pydsvdcapi`` package re-exports everything a normal
# integration needs.  Only the few items not in __init__ (ActionParameter,
# DsUidNamespace, genericVDC_pb2) are imported directly.

# Mock device simulators (separate file for clarity).
from mock_devices import (  # noqa: E402
    MockDevice1,
    MockDevice2,
    MockDevice3,
    MockDevice4,
    MockDevice5,
)

from pydsvdcapi import (  # noqa: E402
    # -- Property type constants --
    PROPERTY_TYPE_NUMERIC,
    BinaryInput,
    # -- Enums --
    BinaryInputType,
    BinaryInputUsage,
    ButtonFunction,
    ButtonInput,
    ButtonMode,
    ButtonType,
    ColorClass,
    ColorGroup,
    CustomAction,
    Device,
    DeviceActionDescription,
    DeviceEvent,
    DeviceProperty,
    Output,
    OutputChannelType,
    OutputFunction,
    OutputMode,
    SensorInput,
    SensorType,
    SensorUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
    create_button_group,
)
from pydsvdcapi import genericVDC_pb2 as pb  # noqa: E402
from pydsvdcapi.actions import ActionParameter  # noqa: E402
from pydsvdcapi.dsuid import DsUid, DsUidNamespace  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
#
# All temporary state (YAML persistence, templates) lives under /tmp
# so the demo can be re-run cleanly without leftover files.

_TMP = Path("/tmp/pydsvdcapi_devguide")
STATE_FILE = _TMP / "state.yaml"
TEMPLATE_DIR = _TMP / "templates"

MODEL_NAME = "pydsvdcapi DevGuide Gateway"
HOST_NAME = "pydsvdcapi DevGuide Host"
VENDOR = "pydsvdcapi"

VDC_IMPL_ID = "x-pydsvdcapi-devguide"
VDC_NAME = "DevGuide vDC"
VDC_MODEL = "pydsvdcapi Developer Guide Controller v1"

CONNECT_TIMEOUT = 120  # seconds to wait for a vdSM to connect


# ═══════════════════════════════════════════════════════════════════════════
# ANSI COLOURS & CONSOLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
GREY = "\033[90m"
BLUE = "\033[94m"


class ColourFormatter(logging.Formatter):
    LEVEL_COLOURS = {
        logging.DEBUG: GREY,
        logging.INFO: "",
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, "")
        ts = self.formatTime(record, "%H:%M:%S")
        return f"{GREY}{ts}{RESET} {colour}{record.getMessage()}{RESET}"


# Logging is **off** by default — menu option [6] toggles it.
_log_handler: Optional[logging.Handler] = None
_logging_enabled = False


def _setup_logging_handler() -> None:
    """Create (but do not attach) the coloured console handler."""
    global _log_handler
    _log_handler = logging.StreamHandler(sys.stdout)
    _log_handler.setFormatter(ColourFormatter())


def toggle_logging() -> bool:
    """Toggle library debug logging on/off.  Returns new state."""
    global _logging_enabled
    root = logging.getLogger()
    if _logging_enabled:
        if _log_handler in root.handlers:
            root.removeHandler(_log_handler)
        root.setLevel(logging.WARNING)
        _logging_enabled = False
    else:
        root.addHandler(_log_handler)
        root.setLevel(logging.DEBUG)
        # Silence very noisy loggers even in debug mode.
        for name in (
            "zeroconf",
            "pydsvdcapi.output_channel",
            "pydsvdcapi.session",
            "pydsvdcapi.output",
            "pydsvdcapi.binary_input",
            "pydsvdcapi.sensor_input",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)
        _logging_enabled = True
    return _logging_enabled


def banner(text: str) -> None:
    w = 64
    print()
    print(f"{BOLD}{CYAN}{'=' * w}{RESET}")
    print(f"{BOLD}{CYAN}  {text.center(w - 4)}  {RESET}")
    print(f"{BOLD}{CYAN}{'=' * w}{RESET}")
    print()


def section(text: str) -> None:
    print(f"\n{BOLD}{BLUE}--- {text} ---{RESET}\n")


def info(text: str) -> None:
    print(f"{GREEN}[demo]{RESET} {text}")


def warn(text: str) -> None:
    print(f"{YELLOW}[warn]{RESET} {text}")


async def _read_line(prompt: str) -> str:
    """Read a line of stdin without blocking the event loop."""
    loop = asyncio.get_running_loop()

    def _do() -> str:
        print(prompt, end="", flush=True)
        line = sys.stdin.readline()
        return line.strip() if line else ""

    return await loop.run_in_executor(None, _do)


async def wait_for_session(
    host: VdcHost,
    timeout: float = CONNECT_TIMEOUT,
) -> None:
    """Block until the vdSM completes the Hello handshake."""
    info(f"Waiting up to {int(timeout)}s for vdSM on port {host.port}…")
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        s = host.session
        if s is not None and s.is_active:
            info(f"Session established — vdSM {s.vdsm_dsuid}  (API v{s.api_version})")
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(
        f"No vdSM connected within {timeout}s.  Is a dSS reachable on the network?"
    )


# ═══════════════════════════════════════════════════════════════════════════
# PROTOBUF MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════
# The ``on_message`` callback handles protobuf messages that are **not**
# consumed by the library's internal session layer (e.g. unknown types).
# For this demo we simply acknowledge anything the vdSM sends that
# expects a response.


async def on_message(
    session,
    msg: pb.Message,
) -> Optional[pb.Message]:
    if msg.message_id > 0:
        resp = pb.Message()
        resp.type = pb.GENERIC_RESPONSE
        resp.message_id = msg.message_id
        resp.generic_response.code = pb.ERR_OK
        return resp
    return None


# ═══════════════════════════════════════════════════════════════════════════
# DEVICE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
#
# Each ``build_device_N()`` function:
#   1. Creates a Device (with a deterministic dSUID for repeatability).
#   2. Creates one Vdsd inside it with the correct primary_group.
#   3. Adds inputs, outputs, actions, events, and/or properties.
#   4. Calls ``vdsd.derive_model_features()`` to auto-set model flags.
#   5. Returns the unannounced Device.


def _make_on_channel_applied(label: str):
    """Factory for ``output.on_channel_applied`` callbacks.

    The ``on_channel_applied`` callback is invoked whenever the dSS
    pushes new output values (e.g. from a scene call).  A real driver
    would forward these to hardware; here we just print them.
    """

    async def on_channel_applied(output: Output, updates: dict) -> None:
        parts = []
        for ch_type, val in updates.items():
            name = ch_type.name if hasattr(ch_type, "name") else str(ch_type)
            parts.append(f"{name}={val:.1f}")
        info(f"{MAGENTA}[{label}] channel applied{RESET}  {', '.join(parts)}")

    return on_channel_applied


# ---------------------------------------------------------------------------
# Device 1 — Yellow: single pushbutton + on/off brightness
# ---------------------------------------------------------------------------


def build_device_1(vdc: Vdc) -> Device:
    """Simple on/off light with one pushbutton.

    **Key concepts demonstrated:**
    - ``Device`` / ``Vdsd`` lifecycle (create, add components, announce)
    - ``ButtonInput`` with ``SINGLE_PUSHBUTTON`` type
    - ``Output(ON_OFF)`` auto-creates a BRIGHTNESS channel
    - ``derive_model_features()`` auto-sets model-feature flags

    **Derived model features:**
    ``dontcare``, ``light``, ``transt``, ``outvalue8``, ``outmode``,
    ``switch``, ``outmodeswitch``, ``pushbutton``, ``pushbadvanced``,
    ``pushbarea``
    """
    # ---- 1. Create the Device with a deterministic dSUID ────────────
    # Using ``DsUid.from_name_in_space`` derives a repeatable dSUID from
    # a human-readable string so the dSS recognises the device across
    # restarts.
    dsuid = DsUid.from_name_in_space("devguide-device-1", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    # ---- 2. Create the vdSD (virtual digitalSTROM device) ───────────
    # ``primary_group`` sets the device's colour class.
    # ColorClass.YELLOW (1) = Light devices.
    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Simple Light",
        model="DevGuide Light v1",
        primary_group=ColorClass.YELLOW,
    )
    device.add_vdsd(vdsd)

    # ---- 3. Add a single pushbutton ─────────────────────────────────
    # ButtonInput models a physical button.  The built-in ClickDetector
    # state machine resolves press/release timing into click events
    # (single, double, hold, etc.) and pushes them to the dSS.
    btn = ButtonInput(
        vdsd=vdsd,
        ds_index=0,
        button_id=0,
        button_type=ButtonType.SINGLE_PUSHBUTTON,
        name="Light Button",
        group=1,  # group 1 = Yellow / Light
        function=ButtonFunction.DEVICE,
        mode=ButtonMode.STANDARD,
    )
    vdsd.add_button_input(btn)

    # ---- 4. Add the output ──────────────────────────────────────────
    # OutputFunction.ON_OFF auto-creates one BRIGHTNESS channel.
    # The dSS treats ``brightness > onThreshold`` as ON.
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.ON_OFF,
        name="output",
        default_group=1,
        active_group=1,
        groups={1},
        mode=OutputMode.BINARY,
        push_changes=True,
    )
    vdsd.set_output(output)
    output.on_channel_applied = _make_on_channel_applied("1")

    # ---- 5. Auto-derive model features ──────────────────────────────
    # ``derive_model_features()`` inspects the vdSD's components and
    # sets the appropriate model-feature flags (e.g. "dontcare",
    # "blink", "outvalue8", etc.) so the dSS UI works correctly.
    vdsd.derive_model_features()

    return device


# ---------------------------------------------------------------------------
# Device 2 — Yellow: 2-way rocker + dimmer (brightness + colour temperature)
# ---------------------------------------------------------------------------


def build_device_2(vdc: Vdc) -> Device:
    """CT-dimmable light with a two-way rocker button.

    **Key concepts demonstrated:**
    - ``create_button_group()`` helper for multi-element buttons
    - ``Output(DIMMER_COLOR_TEMP)`` auto-creates BRIGHTNESS +
      COLOR_TEMPERATURE channels (mired)

    **Derived model features:**
    ``dontcare``, ``light``, ``dimmable``, ``transt``, ``outvalue8``,
    ``outmode``, ``pushbutton``, ``pushbadvanced``, ``pushbarea``,
    ``pushbcombined``, ``twowayconfig``
    """
    dsuid = DsUid.from_name_in_space("devguide-device-2", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="CT Dimmer",
        model="DevGuide CT Light v1",
        primary_group=ColorClass.YELLOW,
    )
    device.add_vdsd(vdsd)

    # ---- Two-way rocker button ──────────────────────────────────────
    # ``create_button_group()`` creates one ButtonInput per element
    # (DOWN at ds_index=0, UP at ds_index=1 for TWO_WAY_PUSHBUTTON).
    # The returned list must be added to the vdSD manually.
    buttons = create_button_group(
        vdsd=vdsd,
        button_id=0,
        button_type=ButtonType.TWO_WAY_PUSHBUTTON,
        start_index=0,
        name_prefix="Rocker",
        group=1,
        function=ButtonFunction.DEVICE,
        mode=ButtonMode.STANDARD,
    )
    for btn in buttons:
        vdsd.add_button_input(btn)

    # ---- CT dimmer output ───────────────────────────────────────────
    # DIMMER_COLOR_TEMP auto-creates:
    #   • BRIGHTNESS    (ds_index 0, 0–100 %)
    #   • COLOR_TEMPERATURE (ds_index 1, 100–1000 mired)
    # active_group=1 triggers the "light" model feature.
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.DIMMER_COLOR_TEMP,
        name="output",
        default_group=1,
        active_group=1,
        groups={1},
        push_changes=True,
    )
    vdsd.set_output(output)
    output.on_channel_applied = _make_on_channel_applied("2")

    vdsd.derive_model_features()
    return device


# ---------------------------------------------------------------------------
# Device 3 — Grey: garage-door contact + blinds output
# ---------------------------------------------------------------------------


def build_device_3(vdc: Vdc) -> Device:
    """Garage-door contact + motorised blinds (shade position + blade angle).

    **Key concepts demonstrated:**
    - ``BinaryInput`` with ``BinaryInputType.GARAGE_DOOR_OPEN``
    - ``ColorClass.GREY`` (shade / blind devices)
    - ``Output(POSITIONAL)`` — channels are added manually via
      ``output.add_channel()`` (not auto-created)

    **Derived model features:**
    ``dontcare``, ``shade``, ``transt``, ``shadeprops``,
    ``shadeposition``, ``locationconfig``, ``windprotectionconfig``

    Note: ``BinaryInputType.GARAGE_DOOR_OPEN`` (16) is not in the
    ``presence`` set {1,3,5,6} nor the ``window`` set {13,14,15},
    so neither of those features is derived.
    """
    dsuid = DsUid.from_name_in_space("devguide-device-3", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Smart Blinds",
        model="DevGuide Blinds v1",
        primary_group=ColorClass.GREY,
    )
    device.add_vdsd(vdsd)

    # ---- Garage-door contact binary input ───────────────────────────
    # BinaryInputType.GARAGE_DOOR_OPEN (16) — open/closed door contact.
    bi = BinaryInput(
        vdsd=vdsd,
        ds_index=0,
        sensor_function=BinaryInputType.GARAGE_DOOR_OPEN,
        input_usage=BinaryInputUsage.ROOM_CLIMATE,
        name="Garage Door",
    )
    vdsd.add_binary_input(bi)

    # ---- Blinds output (positional) ─────────────────────────────────
    # OutputFunction.POSITIONAL does NOT auto-create channels.
    # For blinds we need two: shade position and blade opening angle.
    # default_group=2 / active_group=2 = Grey (Shade).
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.POSITIONAL,
        name="output",
        default_group=2,
        active_group=2,
        groups={2},
        push_changes=True,
    )
    vdsd.set_output(output)

    # Add channels manually — ``add_channel()`` auto-assigns ds_index
    # if omitted, but we're explicit here for clarity.
    output.add_channel(
        OutputChannelType.SHADE_POSITION_OUTSIDE,
        ds_index=0,
        name="Shade Position",
    )
    output.add_channel(
        OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
        ds_index=1,
        name="Blade Angle",
    )

    output.on_channel_applied = _make_on_channel_applied("3")

    vdsd.derive_model_features()
    return device


# ---------------------------------------------------------------------------
# Device 4 — Yellow: illumination + active-power sensors + RGBW output
# ---------------------------------------------------------------------------


def build_device_4(vdc: Vdc) -> Device:
    """Dual-sensor + full-colour RGBW output.

    **Key concepts demonstrated:**
    - Multiple ``SensorInput`` instances on one vdSD
    - ``SensorInput`` required keyword-only params (``sensor_type``,
      ``min_value``, ``max_value``, ``resolution``)
    - ``Output(FULL_COLOR_DIMMER)`` auto-creates: brightness, hue,
      saturation, colortemp, cieX, cieY
    - Uplink converter (menu option [2]) converts W → kW

    **Derived model features:**
    ``dontcare``, ``sensor``, ``energy``, ``consumption``, ``light``,
    ``dimmable``, ``transt``, ``outvalue8``, ``outmode``,
    ``outputchannels``

    Note: ``ILLUMINATION`` (sensorType 3) contributes only ``sensor``
    (no dedicated sensor feature). ``ACTIVE_POWER`` (sensorType 14)
    adds both ``energy`` and ``consumption``.
    """
    dsuid = DsUid.from_name_in_space("devguide-device-4", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="RGBW Light + Sensors",
        model="DevGuide RGBW v1",
        primary_group=ColorClass.YELLOW,
    )
    device.add_vdsd(vdsd)

    # ---- Illumination sensor ────────────────────────────────────────
    # SensorInput now requires ``sensor_type``, ``min_value``,
    # ``max_value``, and ``resolution`` — no defaults.
    si_lux = SensorInput(
        vdsd=vdsd,
        ds_index=0,
        sensor_type=SensorType.ILLUMINATION,
        sensor_usage=SensorUsage.ROOM,
        name="Illumination",
        min_value=0.0,
        max_value=100_000.0,
        resolution=1.0,
        update_interval=60.0,
    )
    vdsd.add_sensor_input(si_lux)

    # ---- Active power sensor ────────────────────────────────────────
    # This sensor reports raw power in Watts.  Menu option [2] will
    # demonstrate attaching an uplink converter to show kW instead.
    si_power = SensorInput(
        vdsd=vdsd,
        ds_index=1,
        sensor_type=SensorType.ACTIVE_POWER,
        sensor_usage=SensorUsage.DEVICE_LEVEL,
        name="Active Power",
        min_value=0.0,
        max_value=3680.0,
        resolution=0.1,
        update_interval=30.0,
    )
    vdsd.add_sensor_input(si_power)

    # ---- Full-colour RGBW output ────────────────────────────────────
    # FULL_COLOR_DIMMER auto-creates six channels:
    #   brightness, hue, saturation, colortemp, cieX, cieY
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.FULL_COLOR_DIMMER,
        name="output",
        default_group=1,
        active_group=1,
        groups={1},
        push_changes=True,
    )
    vdsd.set_output(output)
    output.on_channel_applied = _make_on_channel_applied("4")

    vdsd.derive_model_features()
    return device


# ---------------------------------------------------------------------------
# Device 5 — White: custom property + event + custom action (SingleDevice)
# ---------------------------------------------------------------------------


def build_device_5(vdc: Vdc) -> Device:
    """Custom integration device (SingleDevice / white).

    **Key concepts demonstrated:**
    - ``ColorClass.WHITE`` (9) — triggers the "Einzelgerät" (single
      device) query path in the dSS
    - ``Output(CUSTOM)`` + ``OutputMode.DISABLED`` —
      the ActionOutputBehaviour pattern: no regular output channels,
      the device is controlled via actions only
    - ``DeviceActionDescription`` + ``ActionParameter`` — declares an
      action the dSS can invoke
    - ``CustomAction`` — a named preset for an action description
    - ``DeviceEvent`` — an event the device can fire to the dSS

    **Derived model features:**\n    *(none)*\n\n    Note: SingleDevice outputs suppress all output/channel model\n    features (including ``dontcare``).  ``OutputFunction.CUSTOM``\n    (0x7F) tells the dSS this device has no standard output function.
    ``ColorClass.WHITE`` (9) does not match any primary-group rule, so
    no joker/heating/location features are derived.
    - ``DeviceProperty`` — a custom read/write property
    - ``on_invoke_action`` callback
    """
    dsuid = DsUid.from_name_in_space("devguide-device-5", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Custom Controller",
        model="DevGuide Custom v1",
        primary_group=ColorClass.WHITE,
        # oemModelGuid with a known GTIN enables hasActions=true on the dSS.
        # dSS looks up the GTIN in its vdc-db (hasActionInterface()) to decide
        # whether the device has an action interface.  Since
        # dynamicDefinitions=True, all actual descriptions still come from the
        # VDC and override any database content.
        #
        # 2345678901234 = "FrameworkTestDeviceWithoutRegressionImpact" —
        # a dedicated stub entry in the dSS vdc-db (device_template_id=0,
        # no states/events/properties in the DB) that exists solely to allow
        # hasActionInterface() to return true without polluting the device
        # model with DB-sourced states, actions, or translations.
        oem_model_guid="gs1:(01)2345678901234",
    )
    device.add_vdsd(vdsd)

    # ---- Action output (no channels) ────────────────────────────────
    # SingleDevices use OutputFunction.CUSTOM + DISABLED.  This tells
    # the dSS "I have no regular output channels — control me via
    # actions".  derive_model_features() suppresses all output/channel
    # model features when SingleDevice configurations are present.
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.CUSTOM,
        name="output",
        mode=OutputMode.DISABLED,
        default_group=int(ColorGroup.BLACK),
        active_group=int(ColorGroup.BLACK),
        groups={int(ColorGroup.BLACK)},
    )
    vdsd.set_output(output)

    # ---- Action description: "activate" ─────────────────────────────
    # Declares an invokable action with typed parameters.
    # The dSS shows this in the device's action panel.
    param = ActionParameter(
        name="intensity",
        type="numeric",
        min_value=0.0,
        max_value=100.0,
        resolution=1.0,
        siunit="%",
        default=50.0,
    )
    desc = DeviceActionDescription(
        vdsd=vdsd,
        ds_index=0,
        name="activate",
        params=[param],
        description="Activate the custom controller at a given intensity",
    )
    vdsd.add_device_action_description(desc)

    # ---- Custom action (named preset for the action description) ────
    cust = CustomAction(
        vdsd=vdsd,
        ds_index=0,
        name="custom.activate-full",
        action="activate",
        title="Activate Full",
        params={"intensity": 100.0},
    )
    vdsd.add_custom_action(cust)

    # ---- Device event ───────────────────────────────────────────────
    # Events are one-way notifications pushed from the device to the
    # dSS.  The dSS can use them to trigger server-side automations.
    evt = DeviceEvent(
        vdsd=vdsd,
        ds_index=0,
        name="customAlert",
        description="Fired by the custom controller when triggered",
    )
    vdsd.add_device_event(evt)

    # ---- Device property ────────────────────────────────────────────
    # Custom properties are visible in the dSS device configurator.
    prop = DeviceProperty(
        vdsd=vdsd,
        ds_index=0,
        name="eventCounter",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=999_999.0,
        resolution=1.0,
        default=0.0,
        description="Number of times the custom event has been fired",
    )
    vdsd.add_device_property(prop)

    # ---- Wire the invoke-action callback ────────────────────────────
    # ``on_invoke_action`` is called when the dSS triggers an action.
    async def _on_invoke(action_id: str, params: dict) -> None:
        intensity = params.get("intensity", 0.0)
        info(
            f"{MAGENTA}[5] Action invoked{RESET}  "
            f"id='{action_id}'  intensity={intensity:.0f}%"
        )

    vdsd.on_invoke_action = _on_invoke

    # ---- Model feature: highlevel ───────────────────────────────────
    # "highlevel" shows the SingleDevice action UI in the dSS.
    vdsd.add_model_feature("highlevel")

    # derive_model_features() is called but the manually added
    # "highlevel" flag is preserved.
    vdsd.derive_model_features()
    return device


# ═══════════════════════════════════════════════════════════════════════════
# DEVICE REGISTRY & LIFECYCLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def build_all_devices(vdc: Vdc) -> Dict[str, Device]:
    """Build all five devices and return them keyed by label."""
    return {
        "1": build_device_1(vdc),
        "2": build_device_2(vdc),
        "3": build_device_3(vdc),
        "4": build_device_4(vdc),
        "5": build_device_5(vdc),
    }


async def announce_devices(
    host: VdcHost,
    devices: Dict[str, Device],
) -> None:
    """Announce all devices concurrently.

    When the vDC has multiple pre-registered devices the vdSM
    discovers all of them at once and will not confirm any single
    announce until all are in flight — sequential announcing would
    deadlock.  Therefore we use ``asyncio.gather``.
    """
    session = host.session

    async def _announce_one(label: str, device: Device) -> None:
        count = await device.announce(session)
        total = len(device.vdsds)
        info(
            f"{GREEN}[{label}]{RESET} announced  "
            f"({count}/{total} vdSDs, dSUID={device.dsuid})"
        )

    await asyncio.gather(*[_announce_one(lbl, dev) for lbl, dev in devices.items()])


async def vanish_devices(
    host: VdcHost,
    devices: Dict[str, Device],
) -> None:
    """Vanish all devices."""
    session = host.session
    for label, device in devices.items():
        await device.vanish(session)
        info(f"{YELLOW}[{label}]{RESET} vanished")


def build_mocks(devices: Dict[str, Device]) -> Dict[str, object]:
    """Wrap each device in its mock simulator."""
    return {
        "1": MockDevice1(devices["1"]),
        "2": MockDevice2(devices["2"]),
        "3": MockDevice3(devices["3"]),
        "4": MockDevice4(devices["4"]),
        "5": MockDevice5(devices["5"]),
    }


async def start_mocks(mocks: Dict[str, object]) -> None:
    for m in mocks.values():
        m.start()


async def stop_mocks(mocks: Dict[str, object]) -> None:
    for m in mocks.values():
        await m.stop()


# ═══════════════════════════════════════════════════════════════════════════
# MENU ACTIONS
# ═══════════════════════════════════════════════════════════════════════════


# --- [1] Shutdown & restore -------------------------------------------


async def action_shutdown_restore(
    host: VdcHost,
    vdc: Vdc,
    devices: Dict[str, Device],
    mocks: Dict[str, object],
    port: int,
) -> tuple:
    """Simulate a VDC breakdown: stop, rebuild from YAML, re-announce.

    This demonstrates the persistence / restore cycle:
    1. Stop the host (flushes auto-save).
    2. Replace the primary YAML with the backup to simulate data loss.
    3. Rebuild the VdcHost from the backup YAML.
    4. Re-register devices and wait for auto-announce.

    Returns ``(new_host, new_vdc, new_devices, new_mocks)``.
    """
    banner("Menu [1] — Simulate shutdown & restore")

    section("Stopping mock simulators…")
    await stop_mocks(mocks)

    section("Stopping VdcHost (simulating breakdown)…")
    await host.stop()
    info("Host stopped.")

    # Swap in the backup YAML to simulate partial data loss.
    backup = STATE_FILE.with_suffix(".bak.yaml")
    if backup.exists():
        backup.replace(STATE_FILE)
        info(f"Replaced state with backup: {STATE_FILE}")
    else:
        warn("No backup found — using existing state file as-is.")

    await asyncio.sleep(2)
    section("Rebuilding VdcHost from persisted YAML…")

    new_host = VdcHost(
        port=port,
        state_path=STATE_FILE,
    )

    if not new_host.vdcs:
        warn("No vDC in restored state — rebuilding from scratch.")
        new_vdc = Vdc(
            host=new_host,
            implementation_id=VDC_IMPL_ID,
            name=VDC_NAME,
            model=VDC_MODEL,
            template_path=TEMPLATE_DIR,
            capabilities=VdcCapabilities(
                metering=False,
                identification=True,
                dynamic_definitions=True,
            ),
        )
        new_host.add_vdc(new_vdc)
    else:
        new_vdc = list(new_host.vdcs.values())[0]
        new_vdc._template_path = TEMPLATE_DIR  # type: ignore[attr-defined]

    info(f"Restored vDC: {new_vdc.name}  (dSUID={new_vdc.dsuid})")

    section("Re-building and registering devices…")
    new_devices = build_all_devices(new_vdc)
    for device in new_devices.values():
        new_vdc.add_device(device)

    await new_host.start(on_message=on_message)
    info("New host started.")

    await wait_for_session(new_host)

    # Wait for auto-announce to complete.
    for _ in range(40):
        if new_vdc.is_announced and all(d.is_announced for d in new_devices.values()):
            break
        await asyncio.sleep(0.5)

    if not new_vdc.is_announced:
        warn("vDC re-announcement failed.")
    else:
        info("vDC and all devices re-announced successfully!")

    section("Restarting mock simulators…")
    new_mocks = build_mocks(new_devices)
    await start_mocks(new_mocks)

    info("Shutdown & restore complete!")
    return new_host, new_vdc, new_devices, new_mocks


# --- [2] Create converter --------------------------------------------


async def action_create_converter(
    devices: Dict[str, Device],
) -> None:
    """Attach a W→kW uplink converter to device 4's active-power sensor.

    Demonstrates ``SensorInput.set_uplink_converter()`` — the converter
    snippet is a Python expression that transforms the raw value before
    it reaches the dSS.

    Once applied, subsequent sensor pushes will show kW instead of W.
    """
    banner("Menu [2] — Create uplink converter")

    vdsd_4 = next(iter(devices["4"].vdsds.values()))
    si_power: SensorInput = vdsd_4.sensor_inputs[1]

    converter_code = "value = value / 1000"
    info(f"Converter snippet:  {converter_code!r}")
    info(f"Sensor:             {si_power.name} (ds_index={si_power.ds_index})")
    info("Effect:             raw W → kW (divide by 1000)")

    answer = await _read_line(
        f"\n{BOLD}Apply this converter? [y/N]: {RESET}",
    )
    if answer.lower() in ("y", "yes"):
        si_power.set_uplink_converter(converter_code)
        info("Converter applied!  Subsequent pushes will report kW.")
    else:
        info("Converter not applied.")


# --- [3] Template workflow --------------------------------------------


async def action_template_workflow(
    host: VdcHost,
    vdc: Vdc,
    devices: Dict[str, Device],
) -> Optional[Device]:
    """Save device 1 as a template, then instantiate a new device from it.

    Demonstrates the full template lifecycle:
    1. ``vdc.save_template()`` — serialise device structure to YAML.
    2. ``vdc.load_template()`` — load back the template.
    3. ``tmpl.configure()`` — fill in required per-instance fields.
    4. ``tmpl.instantiate()`` — create a new Device from the template.
    5. Wire required callbacks, announce.

    Returns the new device (or ``None`` on failure).
    """
    banner("Menu [3] — Save as template & create new device")

    if vdc._template_path is None:  # type: ignore[attr-defined]
        warn("Template path not set — cannot save template.")
        return None

    # ---- Save device 1 as template ──────────────────────────────────
    section("Saving Device 1 as template…")
    device_1 = devices["1"]
    try:
        tpl_path = vdc.save_template(
            device_1,
            template_type="generic",
            integration="x-devguide",
            name="simple-light",
            description="Simple on/off light (developer guide)",
        )
        info(f"Template saved to: {tpl_path}")
    except Exception as exc:
        warn(f"save_template failed: {exc}")
        return None

    # ---- Load the template back ─────────────────────────────────────
    section("Loading template…")
    try:
        tmpl = vdc.load_template("generic", "x-devguide", "simple-light")
    except Exception as exc:
        warn(f"load_template failed: {exc}")
        return None

    info(f"Template: '{tmpl.name}'  type={tmpl.template_type}")
    info(f"  required_fields   : {list(tmpl.required_fields.keys())}")
    info(f"  required_callbacks: {list(tmpl.required_callbacks.keys())}")

    # ---- Ask for the new device name ────────────────────────────────
    name = await _read_line(
        f"\n{BOLD}Name for the new device [Light Copy]: {RESET}",
    )
    if not name:
        name = "Light Copy"

    # ---- Configure and instantiate ──────────────────────────────────
    section("Instantiating from template…")
    dsuid_new = DsUid.from_name_in_space(
        f"devguide-template-{name}",
        DsUidNamespace.VDC,
    )
    tmpl.configure({"vdsds[0].name": name})

    try:
        new_device = tmpl.instantiate(vdc=vdc, dsuid=dsuid_new)
    except Exception as exc:
        warn(f"instantiate failed: {exc}")
        return None

    # ---- Wire required callbacks ────────────────────────────────────
    new_vdsd = next(iter(new_device.vdsds.values()))
    new_output = new_vdsd.output
    if new_output is not None:
        new_output.on_channel_applied = _make_on_channel_applied("T")

    # ---- Announce ───────────────────────────────────────────────────
    session = host.session
    count = await new_device.announce(session)
    info(
        f"{GREEN}[T]{RESET} '{new_vdsd.name}' announced  "
        f"({count} vdSDs, dSUID={new_device.dsuid})"
    )
    return new_device


# --- [4] Fire event (device 5) ---------------------------------------


async def action_fire_event(
    mocks: Dict[str, object],
) -> None:
    """Trigger device 5's custom event and push it to the dSS.

    Demonstrates ``DeviceEvent.raise_event()`` — the library sends a
    ``VDC_SEND_PUSH_NOTIFICATION`` carrying the event to the vdSM.
    """
    banner("Menu [4] — Fire event (device 5)")
    mock_5: MockDevice5 = mocks["5"]  # type: ignore[assignment]
    await mock_5.trigger_event()
    info("Event 'customAlert' sent to dSS!")


# --- [5] End simulation & cleanup ------------------------------------


async def action_end(
    host: VdcHost,
    devices: Dict[str, Device],
    mocks: Dict[str, object],
    template_device: Optional[Device],
) -> None:
    """Vanish all devices, stop host, remove all temporary files."""
    banner("Menu [5] — End simulation & cleanup")

    section("Stopping mock simulators…")
    await stop_mocks(mocks)

    section("Vanishing devices…")
    await vanish_devices(host, devices)

    if template_device is not None:
        session = host.session
        await template_device.vanish(session)
        info("[T] template device vanished")

    section("Stopping VdcHost…")
    await host.stop()
    info("Host stopped.")

    section("Cleaning up temporary files…")
    if _TMP.exists():
        shutil.rmtree(_TMP)
        info(f"Removed {_TMP}")
    else:
        info("Nothing to clean up.")

    info("Simulation ended.  Goodbye!")


# --- [6] Toggle logging ----------------------------------------------


def action_toggle_logging() -> None:
    enabled = toggle_logging()
    if enabled:
        info("Logging ENABLED — library debug output now visible.")
        info("Select [6] again to disable.")
    else:
        info("Logging DISABLED.")


# ═══════════════════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════


async def show_menu() -> str:
    loop = asyncio.get_running_loop()

    def _draw() -> str:
        print()
        print(f"{BOLD}{CYAN}╔════════════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}{CYAN}║       Developer Guide Demo — Main Menu        ║{RESET}")
        print(f"{BOLD}{CYAN}╠════════════════════════════════════════════════╣{RESET}")
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[1]{RESET} Simulate shutdown & restore               {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[2]{RESET} Create converter (W→kW on device 4)       {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[3]{RESET} Save as template & create new device      {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[4]{RESET} Fire event (device 5)                     {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[5]{RESET} End simulation & cleanup                  {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[6]{RESET} Toggle logging                            {CYAN}║{RESET}"
        )
        print(f"{BOLD}{CYAN}╚════════════════════════════════════════════════╝{RESET}")
        print(f"{BOLD}Choice:{RESET} ", end="", flush=True)
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            line = ""
        if not line:
            if sys.stdin.isatty():
                # PTY with no data yet — caller should retry
                return ""
            return "5"  # non-TTY EOF → clean exit
        return line.strip()

    return await loop.run_in_executor(None, _draw)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


async def main() -> None:
    _setup_logging_handler()

    # Ensure temp directories exist.
    _TMP.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Ctrl+C → graceful shutdown ──────────────────────────────────
    loop = asyncio.get_running_loop()
    _stop_event = asyncio.Event()

    def _sigint_handler() -> None:
        print(f"\n{BOLD}{YELLOW}Ctrl+C — requesting clean shutdown…{RESET}")
        _stop_event.set()

    loop.add_signal_handler(signal.SIGINT, _sigint_handler)

    # ── Port selection ──────────────────────────────────────────────
    _parser = argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--port", type=int, default=None)
    _args, _ = _parser.parse_known_args()

    if _args.port is not None:
        port = _args.port
    else:

        def _ask_port() -> int:
            while True:
                try:
                    raw = input(
                        f"\n{BOLD}Enter TCP port for the VdcHost "
                        f"[default 8444]: {RESET}"
                    ).strip()
                    if not raw:
                        return 8444
                    p = int(raw)
                    if 1 <= p <= 65535:
                        return p
                    print("  Port must be between 1 and 65535.")
                except (ValueError, KeyboardInterrupt, EOFError):
                    return 8444

        port = await loop.run_in_executor(None, _ask_port)

    # ══════════════════════════════════════════════════════════════════
    # PHASE 1:  Build the VdcHost → Vdc → Devices hierarchy
    # ══════════════════════════════════════════════════════════════════
    #
    # The object graph looks like:
    #
    #   VdcHost  (TCP server, DNS-SD, persistence)
    #     └─ Vdc  (logical vDC container)
    #         └─ Device  (1 per hardware unit, owns the base dSUID)
    #             └─ Vdsd  (1 per sub-device, individually announced)
    #                 ├─ ButtonInput(s)
    #                 ├─ BinaryInput(s)
    #                 ├─ SensorInput(s)
    #                 ├─ Output → OutputChannel(s)
    #                 ├─ DeviceEvent(s)
    #                 ├─ DeviceProperty(s)
    #                 ├─ DeviceActionDescription(s)
    #                 └─ CustomAction(s)

    banner("Starting Developer Guide Demo")

    host = VdcHost(
        port=port,
        model=MODEL_NAME,
        name=HOST_NAME,
        vendor_name=VENDOR,
        state_path=STATE_FILE,
    )
    vdc = Vdc(
        host=host,
        implementation_id=VDC_IMPL_ID,
        name=VDC_NAME,
        model=VDC_MODEL,
        template_path=TEMPLATE_DIR,
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    info(f"VdcHost  dSUID={host.dsuid}  port={host.port}")
    info(f"VDC      dSUID={vdc.dsuid}")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 2:  Build + register devices BEFORE starting the host
    # ══════════════════════════════════════════════════════════════════
    #
    # The dSM may query known devices immediately on Hello (from a
    # prior session).  Pre-registering ensures getProperty returns
    # valid data instead of ERR_NOT_FOUND.

    section("Building and registering devices…")
    devices = build_all_devices(vdc)
    for device in devices.values():
        vdc.add_device(device)
    info(f"Registered {len(devices)} devices with the vDC")

    # Print a summary of each device.
    for label, device in devices.items():
        vdsd = next(iter(device.vdsds.values()))
        info(
            f"  [{label}] {vdsd.name}  "
            f"(group={vdsd.primary_group.name if vdsd.primary_group else '?'}, "
            f"dSUID={vdsd.dsuid})"
        )

    # ══════════════════════════════════════════════════════════════════
    # PHASE 3:  Start TCP server + DNS-SD → auto-announce
    # ══════════════════════════════════════════════════════════════════
    #
    # ``host.start()`` opens the TCP listener and broadcasts the
    # DNS-SD / zeroconf service record.  When the vdSM connects and
    # completes the Hello handshake, the library auto-announces the
    # vDC and all pre-registered devices.

    await host.start(on_message=on_message)
    info("TCP server started — service announced via DNS-SD")

    try:
        await wait_for_session(host)
    except TimeoutError as exc:
        print(f"{RED}{exc}{RESET}")
        await host.stop()
        return

    # Wait for auto-announce to complete (vDC + all devices).
    section("Waiting for auto-announce to complete…")
    for _ in range(40):
        if vdc.is_announced and all(d.is_announced for d in devices.values()):
            break
        await asyncio.sleep(0.5)

    if not vdc.is_announced:
        warn("vDC announcement failed — aborting.")
        await host.stop()
        return

    unannounced = [l for l, d in devices.items() if not d.is_announced]
    if unannounced:
        warn(f"Devices {unannounced} not announced — aborting.")
        await host.stop()
        return

    info("vDC and all 5 devices announced successfully!")

    # ══════════════════════════════════════════════════════════════════
    # PHASE 4:  Start mock simulators + interactive menu
    # ══════════════════════════════════════════════════════════════════

    section("Starting mock device simulators…")
    mocks = build_mocks(devices)
    await start_mocks(mocks)
    info("All mock simulators running.")

    # Track devices created via the template workflow.
    template_device: Optional[Device] = None

    # When stdin is not a real terminal (e.g. background process / no tty),
    # skip the interactive menu and run headlessly until SIGINT / SIGTERM.
    if not sys.stdin.isatty():
        info("stdin is not a terminal — running headless.  Send SIGINT to stop.")
        await _stop_event.wait()
        await action_end(host, devices, mocks, template_device)
        return

    while True:
        if _stop_event.is_set():
            await action_end(host, devices, mocks, template_device)
            break

        menu_task = asyncio.ensure_future(show_menu())
        stop_waiter = asyncio.ensure_future(_stop_event.wait())
        done, pending = await asyncio.wait(
            [menu_task, stop_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()

        if _stop_event.is_set():
            await action_end(host, devices, mocks, template_device)
            break

        choice = menu_task.result() if not menu_task.cancelled() else ""

        if not choice:
            continue  # EOF on PTY or cancelled — redraw menu

        if choice == "1":
            host, vdc, devices, mocks = await action_shutdown_restore(
                host,
                vdc,
                devices,
                mocks,
                port,
            )
            template_device = None  # lost after rebuild

        elif choice == "2":
            await action_create_converter(devices)

        elif choice == "3":
            template_device = await action_template_workflow(
                host,
                vdc,
                devices,
            )

        elif choice == "4":
            await action_fire_event(mocks)

        elif choice == "5":
            await action_end(host, devices, mocks, template_device)
            break

        elif choice == "6":
            action_toggle_logging()

        else:
            warn(f"Unknown choice: '{choice}' — enter 1–6.")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())  # use --port 8444 to skip the port prompt
