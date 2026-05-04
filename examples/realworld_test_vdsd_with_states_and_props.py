#!/usr/bin/env python3
"""Realworld integration demo — device states, properties & events.

This script exercises the device-level metadata components introduced
in §4.6 (states & properties) and §4.7 (events) by creating two
virtual devices that define:

  * **Device states** — discrete status indicators with fixed option
    sets (e.g. operating state, connectivity).
  * **Device properties** — generic typed values (numeric, string,
    enumeration) exposed to the dSS (e.g. battery level, firmware
    version, operating mode).
  * **Device events** — stateless push-only occurrences (e.g. doorbell
    ring, tamper alarm).

The script verifies that description metadata is correctly exposed
via ``getProperty``, that property values survive persistence, and
that state/event pushing works over a live connection.

Three-phase model
-----------------

**Phase 1 — Fresh start & feature configuration**
    * Create a ``VdcHost``, ``Vdc``, ``Device`` with **two** ``Vdsd``
      sub-devices:
      - vdSD 0: Sensor Node (Cyan/Joker) — environmental monitor with
        states, properties, events, and a dimmer output.
      - vdSD 1: Smart Plug (Yellow) — power plug with states,
        properties, events, and a switch output.
    * Verify that ``get_properties()`` exposes the correct
      ``deviceStateDescriptions``, ``deviceStates``,
      ``devicePropertyDescriptions``, ``deviceProperties``, and
      ``deviceEventDescriptions`` for each vdSD.
    * Set initial state values and property values.
    * Announce everything and wait for dSS connection.

**Phase 2 — Restart from persistence**
    * Create a new ``VdcHost`` from the persisted YAML.
    * Verify that states, properties, and events are correctly
      restored — including:
      - State descriptions (options, names) preserved.
      - Property descriptions (type, min/max, unit) preserved.
      - Property values persisted (battery=87.0, firmware version, …).
      - State values are NOT persisted (volatile).
      - Event descriptions persisted.
    * Re-announce and push state updates over the live connection.

**Phase 3 — Vanish, shutdown & cleanup**
    * Vanish the device.
    * Stop the host and delete all persistence artefacts.

Prerequisites
~~~~~~~~~~~~~

* A running digitalSTROM server (dSS) / vdSM reachable on the local
  network segment.
* Adjust ``PORT`` if the default is already in use.

Usage::

    python examples/realworld_test_vdsd_with_states_and_props.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

from pydsvdcapi import (
    ColorGroup,
    Device,
    DeviceEvent,
    DsUid,
    DsUidNamespace,
    Output,
    OutputFunction,
    OutputUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)
from pydsvdcapi.device_property import (
    PROPERTY_TYPE_ENUMERATION,
    PROPERTY_TYPE_NUMERIC,
    PROPERTY_TYPE_STRING,
    DeviceProperty,
)
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.property_handling import NO_VALUE

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_FILE = Path("/tmp/pydsvdcapi_state_prop_demo_state.yaml")

PORT = 8444
MODEL_NAME = "pydsvdcapi State+Prop Demo"
HOST_NAME = "state-prop-demo-host"
VENDOR = "pydsvdcapi"
VDC_IMPLEMENTATION_ID = "x-pydsvdcapi-demo-state-prop"
VDC_NAME = "State/Prop Demo vDC"
VDC_MODEL = "pydsvdcapi-state-prop-vdc"

# Device 1: Sensor Node (Cyan/Joker) — environmental monitor
VDSD_SENSOR_NAME = "Demo Sensor Node"
VDSD_SENSOR_MODEL = "pydsvdcapi-sensor-node"
VDSD_SENSOR_GROUP = ColorGroup.CYAN

# Device 2: Smart Plug (Yellow) — power plug
VDSD_PLUG_NAME = "Demo Smart Plug"
VDSD_PLUG_MODEL = "pydsvdcapi-smart-plug"
VDSD_PLUG_GROUP = ColorGroup.YELLOW

#: How long to wait for the vdSM/dSS to connect (seconds).
CONNECT_TIMEOUT = 120

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
GREY = "\033[90m"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


class ColourFormatter(logging.Formatter):
    """Minimal colour formatter for console output."""

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
        msg = record.getMessage()
        return f"{GREY}{ts}{RESET} {colour}{msg}{RESET}"


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColourFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


async def on_message(msg) -> None:
    """Log unhandled incoming protobuf messages from the vdSM."""
    logger = logging.getLogger("on_message")
    logger.info(
        "%sRX%s  type=%s  msg_id=%s",
        CYAN,
        RESET,
        msg.type,
        msg.message_id,
    )


async def on_channel_applied(output: Output, updates: dict) -> None:
    """Called when channel values are applied."""
    logger = logging.getLogger("hw_apply")
    parts = []
    for ch_type, value in updates.items():
        name = ch_type.name if hasattr(ch_type, "name") else str(ch_type)
        parts.append(f"{name}={value:.1f}")
    logger.info(
        "%sAPPLY%s  [%s] %s",
        GREEN,
        RESET,
        output.name,
        ", ".join(parts),
    )


async def on_control_value(
    vdsd: Vdsd,
    name: str,
    value: float,
    group: int | None,
    zone_id: int | None,
) -> None:
    """Called when the dSS pushes a control value."""
    logger = logging.getLogger("control_value")
    logger.info(
        "%sCONTROL%s  [%s] %s = %.2f",
        CYAN,
        RESET,
        vdsd.name,
        name,
        value,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def wait_for_session(host: VdcHost, timeout: float) -> None:
    """Block until the VdcHost has an active session or timeout."""
    deadline = time.monotonic() + timeout
    while host.session is None or not host.session.is_active:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"No vdSM/dSS connected within {timeout:.0f}s — aborting."
            )
        await asyncio.sleep(0.5)
    logging.getLogger("wait").info("Session established with vdSM!")


async def wait_for_user(prompt: str = "Press Enter to continue...") -> None:
    loop = asyncio.get_running_loop()
    print(f"\n{YELLOW}{prompt}{RESET}")
    await loop.run_in_executor(None, sys.stdin.readline)


def banner(text: str) -> None:
    width = max(len(text) + 4, 60)
    sep = "=" * width
    print(f"\n{BOLD}{GREEN}{sep}{RESET}")
    print(f"{BOLD}{GREEN}  {text}{RESET}")
    print(f"{BOLD}{GREEN}{sep}{RESET}\n")


def section(text: str) -> None:
    print(f"\n{BOLD}{CYAN}--- {text} ---{RESET}\n")


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------


def verify_state_descriptions(
    logger,
    vdsd_name: str,
    props: dict,
    expected: list[dict],
) -> None:
    """Verify deviceStateDescriptions in get_properties() output."""
    desc = props.get("deviceStateDescriptions")
    assert desc is not None, f"{vdsd_name}: missing deviceStateDescriptions"
    assert len(desc) == len(expected), (
        f"{vdsd_name}: expected {len(expected)} state descriptions, got {len(desc)}"
    )
    for exp in expected:
        key = exp["name"]
        assert key in desc, f"{vdsd_name}: state[{key}] missing"
        assert "name" not in desc[key], (
            f"{vdsd_name}: state[{key}] should not have 'name' inside"
        )
        if "values" in exp:
            assert desc[key]["value"]["values"] == exp["values"], (
                f"{vdsd_name}: state[{key}] values mismatch: "
                f"expected {exp['values']}, got {desc[key]['value']['values']}"
            )
        if "description" in exp:
            assert desc[key]["description"] == exp["description"]
    logger.info(
        "  %sPASS%s — %s: %d deviceStateDescriptions correct.",
        GREEN,
        RESET,
        vdsd_name,
        len(expected),
    )


def verify_property_descriptions(
    logger,
    vdsd_name: str,
    props: dict,
    expected: list[dict],
) -> None:
    """Verify devicePropertyDescriptions in get_properties() output."""
    desc = props.get("devicePropertyDescriptions")
    assert desc is not None, f"{vdsd_name}: missing devicePropertyDescriptions"
    assert len(desc) == len(expected), (
        f"{vdsd_name}: expected {len(expected)} property descriptions, got {len(desc)}"
    )
    for exp in expected:
        pkey = exp["name"]
        assert pkey in desc, f"{vdsd_name}: prop[{pkey}] missing"
        assert "name" not in desc[pkey], (
            f"{vdsd_name}: prop[{pkey}] should not have 'name' inside"
        )
        assert desc[pkey]["type"] == exp["type"]
        for field in ("min", "max", "resolution", "siunit", "default"):
            if field in exp:
                assert desc[pkey][field] == exp[field], (
                    f"{vdsd_name}: prop[{pkey}].{field} mismatch: "
                    f"expected {exp[field]}, got {desc[pkey].get(field)}"
                )
    logger.info(
        "  %sPASS%s — %s: %d devicePropertyDescriptions correct.",
        GREEN,
        RESET,
        vdsd_name,
        len(expected),
    )


def verify_event_descriptions(
    logger,
    vdsd_name: str,
    props: dict,
    expected: list[dict],
) -> None:
    """Verify deviceEventDescriptions in get_properties() output."""
    desc = props.get("deviceEventDescriptions")
    assert desc is not None, f"{vdsd_name}: missing deviceEventDescriptions"
    assert len(desc) == len(expected), (
        f"{vdsd_name}: expected {len(expected)} event descriptions, got {len(desc)}"
    )
    for exp in expected:
        ekey = exp["name"]
        assert ekey in desc, f"{vdsd_name}: event[{ekey}] missing"
        assert "name" not in desc[ekey], (
            f"{vdsd_name}: event[{ekey}] should not have 'name' inside"
        )
        if "description" in exp:
            assert desc[ekey]["description"] == exp["description"]
    logger.info(
        "  %sPASS%s — %s: %d deviceEventDescriptions correct.",
        GREEN,
        RESET,
        vdsd_name,
        len(expected),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    setup_logging()
    logger = logging.getLogger("demo")

    # ==================================================================
    # PHASE 1 — Fresh start & feature configuration
    # ==================================================================
    banner("PHASE 1: Fresh start — states, properties & events")

    # Remove leftover state file from previous runs.
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        logger.info("Removed leftover state file %s", STATE_FILE)
    bak = STATE_FILE.with_suffix(STATE_FILE.suffix + ".bak")
    if bak.exists():
        bak.unlink()

    # ---- Create VdcHost + Vdc ----------------------------------------
    host = VdcHost(
        port=PORT,
        model=MODEL_NAME,
        name=HOST_NAME,
        vendor_name=VENDOR,
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id=VDC_IMPLEMENTATION_ID,
        name=VDC_NAME,
        model=VDC_MODEL,
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    # ---- Device with two vdSDs (sub-devices) -------------------------
    device_dsuid = DsUid.from_name_in_space(
        "demo-state-prop-device-1", DsUidNamespace.VDC
    )
    device = Device(vdc=vdc, dsuid=device_dsuid)

    # ==================================================================
    # vdSD 0: Sensor Node — Cyan group, DIMMER output
    # ==================================================================
    vdsd_sensor = Vdsd(
        device=device,
        subdevice_index=0,
        primary_group=VDSD_SENSOR_GROUP,
        name=VDSD_SENSOR_NAME,
        model=VDSD_SENSOR_MODEL,
        model_features={"identification"},
    )
    output_sensor = Output(
        vdsd=vdsd_sensor,
        function=OutputFunction.DIMMER,
        output_usage=OutputUsage.ROOM,
        name="Sensor Status LED",
        default_group=int(VDSD_SENSOR_GROUP),
        active_group=int(VDSD_SENSOR_GROUP),
        variable_ramp=False,
        max_power=2.0,
        push_changes=True,
        groups={int(VDSD_SENSOR_GROUP)},
    )
    output_sensor.on_channel_applied = on_channel_applied
    vdsd_sensor.set_output(output_sensor)
    vdsd_sensor.on_control_value = on_control_value

    # --- Device States (§4.6.1 / §4.6.2) ---
    sensor_state_operating = DeviceState(
        vdsd=vdsd_sensor,
        ds_index=0,
        name="operatingState",
        options={0: "Off", 1: "Initializing", 2: "Running", 3: "Error"},
        description="Current operating state of the sensor node",
    )
    sensor_state_connectivity = DeviceState(
        vdsd=vdsd_sensor,
        ds_index=1,
        name="connectivity",
        options={0: "Offline", 1: "Online", 2: "Degraded"},
        description="Network connectivity status",
    )
    vdsd_sensor.add_device_state(sensor_state_operating)
    vdsd_sensor.add_device_state(sensor_state_connectivity)

    # --- Device Properties (§4.6.3 / §4.6.4) ---
    sensor_prop_battery = DeviceProperty(
        vdsd=vdsd_sensor,
        ds_index=0,
        name="batteryLevel",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=100.0,
        resolution=1.0,
        siunit="%",
        default=100.0,
        description="Battery charge level",
    )
    sensor_prop_firmware = DeviceProperty(
        vdsd=vdsd_sensor,
        ds_index=1,
        name="firmwareVersion",
        type=PROPERTY_TYPE_STRING,
        default="0.0.0",
        description="Current firmware version",
    )
    sensor_prop_interval = DeviceProperty(
        vdsd=vdsd_sensor,
        ds_index=2,
        name="reportingInterval",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=1.0,
        max_value=3600.0,
        resolution=1.0,
        siunit="s",
        default=60.0,
        description="Sensor reporting interval in seconds",
    )
    vdsd_sensor.add_device_property(sensor_prop_battery)
    vdsd_sensor.add_device_property(sensor_prop_firmware)
    vdsd_sensor.add_device_property(sensor_prop_interval)

    # --- Device Events (§4.7) ---
    sensor_evt_tamper = DeviceEvent(
        vdsd=vdsd_sensor,
        ds_index=0,
        name="tamperAlarm",
        description="Enclosure tamper switch triggered",
    )
    sensor_evt_lowbat = DeviceEvent(
        vdsd=vdsd_sensor,
        ds_index=1,
        name="lowBattery",
        description="Battery level critically low",
    )
    vdsd_sensor.add_device_event(sensor_evt_tamper)
    vdsd_sensor.add_device_event(sensor_evt_lowbat)

    device.add_vdsd(vdsd_sensor)

    # ==================================================================
    # vdSD 1: Smart Plug — Yellow group, SWITCH output
    # ==================================================================
    vdsd_plug = Vdsd(
        device=device,
        subdevice_index=1,
        primary_group=VDSD_PLUG_GROUP,
        name=VDSD_PLUG_NAME,
        model=VDSD_PLUG_MODEL,
        model_features={"identification", "blink"},
    )
    output_plug = Output(
        vdsd=vdsd_plug,
        function=OutputFunction.ON_OFF,
        output_usage=OutputUsage.ROOM,
        name="Plug Relay Output",
        default_group=int(VDSD_PLUG_GROUP),
        active_group=int(VDSD_PLUG_GROUP),
        variable_ramp=False,
        max_power=2300.0,
        push_changes=True,
        groups={int(VDSD_PLUG_GROUP)},
    )
    output_plug.on_channel_applied = on_channel_applied
    vdsd_plug.set_output(output_plug)
    vdsd_plug.on_control_value = on_control_value

    # --- Device States ---
    plug_state_relay = DeviceState(
        vdsd=vdsd_plug,
        ds_index=0,
        name="relayState",
        options={0: "Open", 1: "Closed"},
        description="Physical relay contact state",
    )
    plug_state_overheat = DeviceState(
        vdsd=vdsd_plug,
        ds_index=1,
        name="overheatingProtection",
        options={0: "Normal", 1: "Warning", 2: "ThermalShutdown"},
        description="Thermal protection status",
    )
    vdsd_plug.add_device_state(plug_state_relay)
    vdsd_plug.add_device_state(plug_state_overheat)

    # --- Device Properties ---
    plug_prop_power = DeviceProperty(
        vdsd=vdsd_plug,
        ds_index=0,
        name="currentPower",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=3680.0,
        resolution=0.1,
        siunit="W",
        default=0.0,
        description="Current power consumption",
    )
    plug_prop_energy = DeviceProperty(
        vdsd=vdsd_plug,
        ds_index=1,
        name="totalEnergy",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=999999.0,
        resolution=0.01,
        siunit="kWh",
        default=0.0,
        description="Total accumulated energy",
    )
    plug_prop_mode = DeviceProperty(
        vdsd=vdsd_plug,
        ds_index=2,
        name="operatingMode",
        type=PROPERTY_TYPE_ENUMERATION,
        options={0: "Normal", 1: "Timer", 2: "AlwaysOn"},
        default="0",
        description="Plug operating mode",
    )
    vdsd_plug.add_device_property(plug_prop_power)
    vdsd_plug.add_device_property(plug_prop_energy)
    vdsd_plug.add_device_property(plug_prop_mode)

    # --- Device Events ---
    plug_evt_overcurrent = DeviceEvent(
        vdsd=vdsd_plug,
        ds_index=0,
        name="overcurrentTrip",
        description="Overcurrent protection tripped",
    )
    plug_evt_button = DeviceEvent(
        vdsd=vdsd_plug,
        ds_index=1,
        name="localButtonPress",
        description="Physical button on plug pressed",
    )
    vdsd_plug.add_device_event(plug_evt_overcurrent)
    vdsd_plug.add_device_event(plug_evt_button)

    device.add_vdsd(vdsd_plug)
    vdc.add_device(device)

    # ---- Log device topology -----------------------------------------
    section("Device topology")
    logger.info("VdcHost: %s  dSUID: %s", host.name, host.dsuid)
    logger.info("vDC:     %s  dSUID: %s", vdc.name, vdc.dsuid)
    logger.info("Device:  dSUID: %s  (%d sub-devices)", device.dsuid, len(device.vdsds))
    for idx in sorted(device.vdsds):
        v = device.vdsds[idx]
        logger.info(
            "  vdSD[%d] '%s'  group=%s  dSUID=%s",
            idx,
            v.name,
            v.primary_group.name,
            v.dsuid,
        )
        logger.info("    States:     %d", len(v.device_states))
        logger.info("    Properties: %d", len(v.device_properties))
        logger.info("    Events:     %d", len(v.device_events))
        if v.output:
            logger.info(
                "    Output:     %s (%s)", v.output.name, v.output.function.name
            )

    # ==================================================================
    # PHASE 1a — Verify get_properties() exposure
    # ==================================================================
    section("Verifying get_properties() exposure")

    # --- Sensor Node ---
    sensor_props = vdsd_sensor.get_properties()

    # State descriptions
    verify_state_descriptions(
        logger,
        "Sensor",
        sensor_props,
        [
            {
                "index": 0,
                "name": "operatingState",
                "values": {
                    "Off": NO_VALUE,
                    "Initializing": NO_VALUE,
                    "Running": NO_VALUE,
                    "Error": NO_VALUE,
                },
                "description": "Current operating state of the sensor node",
            },
            {
                "index": 1,
                "name": "connectivity",
                "values": {
                    "Offline": NO_VALUE,
                    "Online": NO_VALUE,
                    "Degraded": NO_VALUE,
                },
                "description": "Network connectivity status",
            },
        ],
    )

    # Device states (no values set yet)
    dev_states = sensor_props.get("deviceStates")
    assert dev_states is not None
    assert dev_states["operatingState"]["value"] is None, "No value should be set yet"
    logger.info(
        "  %sPASS%s — Sensor: deviceStates present, no values yet.", GREEN, RESET
    )

    # Property descriptions
    verify_property_descriptions(
        logger,
        "Sensor",
        sensor_props,
        [
            {
                "index": 0,
                "name": "batteryLevel",
                "type": "numeric",
                "min": 0.0,
                "max": 100.0,
                "resolution": 1.0,
                "siunit": "%",
                "default": 100.0,
            },
            {
                "index": 1,
                "name": "firmwareVersion",
                "type": "string",
                "default": "0.0.0",
            },
            {
                "index": 2,
                "name": "reportingInterval",
                "type": "numeric",
                "min": 1.0,
                "max": 3600.0,
                "resolution": 1.0,
                "siunit": "s",
                "default": 60.0,
            },
        ],
    )

    # Device properties (no values set yet)
    dev_props = sensor_props.get("deviceProperties")
    assert dev_props is not None
    assert dev_props["batteryLevel"] is None, "No value should be set yet"
    logger.info(
        "  %sPASS%s — Sensor: deviceProperties present, no values yet.", GREEN, RESET
    )

    # Event descriptions
    verify_event_descriptions(
        logger,
        "Sensor",
        sensor_props,
        [
            {
                "index": 0,
                "name": "tamperAlarm",
                "description": "Enclosure tamper switch triggered",
            },
            {
                "index": 1,
                "name": "lowBattery",
                "description": "Battery level critically low",
            },
        ],
    )

    # --- Smart Plug ---
    plug_props = vdsd_plug.get_properties()

    verify_state_descriptions(
        logger,
        "Plug",
        plug_props,
        [
            {
                "index": 0,
                "name": "relayState",
                "values": {"Open": NO_VALUE, "Closed": NO_VALUE},
                "description": "Physical relay contact state",
            },
            {
                "index": 1,
                "name": "overheatingProtection",
                "values": {
                    "Normal": NO_VALUE,
                    "Warning": NO_VALUE,
                    "ThermalShutdown": NO_VALUE,
                },
                "description": "Thermal protection status",
            },
        ],
    )

    verify_property_descriptions(
        logger,
        "Plug",
        plug_props,
        [
            {
                "index": 0,
                "name": "currentPower",
                "type": "numeric",
                "min": 0.0,
                "max": 3680.0,
                "resolution": 0.1,
                "siunit": "W",
            },
            {
                "index": 1,
                "name": "totalEnergy",
                "type": "numeric",
                "min": 0.0,
                "max": 999999.0,
                "resolution": 0.01,
                "siunit": "kWh",
            },
            {"index": 2, "name": "operatingMode", "type": "enumeration"},
        ],
    )
    # Verify enumeration values are exposed (p44-vdc label→None format)
    plug_mode_desc = plug_props["devicePropertyDescriptions"]["operatingMode"]
    assert plug_mode_desc["values"] == {
        "Normal": NO_VALUE,
        "Timer": NO_VALUE,
        "AlwaysOn": NO_VALUE,
    }
    logger.info(
        "  %sPASS%s — Plug: operatingMode enumeration values correct.", GREEN, RESET
    )

    verify_event_descriptions(
        logger,
        "Plug",
        plug_props,
        [
            {
                "index": 0,
                "name": "overcurrentTrip",
                "description": "Overcurrent protection tripped",
            },
            {
                "index": 1,
                "name": "localButtonPress",
                "description": "Physical button on plug pressed",
            },
        ],
    )

    # ==================================================================
    # PHASE 1b — Set initial values
    # ==================================================================
    section("Setting initial state and property values")

    # Sensor states — integer option keys (match dSS internal format)
    sensor_state_operating.value = 2  # Running
    sensor_state_connectivity.value = 1  # Online
    logger.info("  Sensor operatingState = 2 (Running)")
    logger.info("  Sensor connectivity   = 1 (Online)")

    # Sensor properties (set directly, push will happen when announced)
    sensor_prop_battery.value = 87.0
    sensor_prop_firmware.value = "2.3.1"
    sensor_prop_interval.value = 120.0
    logger.info("  Sensor batteryLevel       = 87.0%%")
    logger.info("  Sensor firmwareVersion    = '2.3.1'")
    logger.info("  Sensor reportingInterval  = 120.0s")

    # Plug states — integer option keys (match dSS internal format)
    plug_state_relay.value = 1  # Closed
    plug_state_overheat.value = 0  # Normal
    logger.info("  Plug relayState             = 1 (Closed)")
    logger.info("  Plug overheatingProtection  = 0 (Normal)")

    # Plug properties
    plug_prop_power.value = 150.5
    plug_prop_energy.value = 42.73
    plug_prop_mode.value = "Timer"  # enum text label
    logger.info("  Plug currentPower     = 150.5W")
    logger.info("  Plug totalEnergy      = 42.73kWh")
    logger.info("  Plug operatingMode    = 'Timer'")

    # Verify values appear in get_properties
    sensor_props = vdsd_sensor.get_properties()
    assert sensor_props["deviceStates"]["operatingState"]["value"] == "Running"
    assert sensor_props["deviceStates"]["connectivity"]["value"] == "Online"
    assert sensor_props["deviceProperties"]["batteryLevel"] == 87.0
    assert sensor_props["deviceProperties"]["firmwareVersion"] == "2.3.1"
    assert sensor_props["deviceProperties"]["reportingInterval"] == 120.0
    logger.info("  %sPASS%s — Sensor values appear in get_properties().", GREEN, RESET)

    plug_props = vdsd_plug.get_properties()
    assert plug_props["deviceStates"]["relayState"]["value"] == "Closed"
    assert plug_props["deviceProperties"]["currentPower"] == 150.5
    assert plug_props["deviceProperties"]["operatingMode"] == "Timer"
    logger.info("  %sPASS%s — Plug values appear in get_properties().", GREEN, RESET)

    # Remember values for Phase 2 comparison.
    saved_sensor_battery = 87.0
    saved_sensor_firmware = "2.3.1"
    saved_sensor_interval = 120.0
    saved_plug_power = 150.5
    saved_plug_energy = 42.73
    saved_plug_mode = "Timer"

    # ==================================================================
    # PHASE 1c — Announce & connect
    # ==================================================================
    section("Announcing to vdSM")

    await host.start(on_message=on_message)
    logger.info("TCP server started — waiting for vdSM to connect...")

    try:
        await wait_for_session(host, CONNECT_TIMEOUT)
    except TimeoutError as exc:
        logger.error(str(exc))
        await host.stop()
        return

    # The VdcHost auto-announces all vDCs and devices on every hello
    # (including the initial connection).  Wait a moment for the
    # auto-announce task to complete, then verify everything is live.
    logger.info("Waiting for auto-announce to complete...")
    for _ in range(40):  # up to 20s
        if vdc.is_announced and device.is_announced:
            break
        await asyncio.sleep(0.5)

    if not vdc.is_announced:
        logger.error("vDC announcement failed — aborting.")
        await host.stop()
        return
    logger.info("vDC announced.")

    if not device.is_announced:
        logger.error("Device announcement failed — aborting.")
        await host.stop()
        return
    logger.info("All %d vdSD(s) announced.", len(device.vdsds))

    session = host.session
    assert session is not None and session.is_active

    # Remember identities for phase 2.
    original_host_dsuid = str(host.dsuid)
    original_vdc_dsuid = str(vdc.dsuid)
    original_device_dsuid = str(device.dsuid)
    original_sensor_dsuid = str(vdsd_sensor.dsuid)
    original_plug_dsuid = str(vdsd_plug.dsuid)

    # ---- Verify auto-save ----
    logger.info("Waiting 2s for auto-save...")
    await asyncio.sleep(2)
    assert STATE_FILE.exists(), f"Auto-save did NOT create {STATE_FILE}!"
    logger.info("Auto-save verified — %s exists.", STATE_FILE)

    await wait_for_user(
        ">>> Phase 1 complete: devices announced with states/props/events.\n"
        ">>> The dSS should now query properties (check logs).\n"
        ">>> Press Enter to shut down and proceed to Phase 2..."
    )

    # ---- Shut down phase 1 ---
    banner("PHASE 1: Shutting down")
    await host.stop()
    logger.info("VdcHost stopped.  State persisted to %s", STATE_FILE)
    logger.info("Pausing 5s before restart...")
    await asyncio.sleep(5)

    # ==================================================================
    # PHASE 2 — Restart from persistence
    # ==================================================================
    banner("PHASE 2: Restart from persistence — verify restoration")

    host2 = VdcHost(
        port=PORT,
        state_path=STATE_FILE,
    )

    logger.info("VdcHost restored from %s:", STATE_FILE)
    logger.info("  dSUID: %s", host2.dsuid)
    assert str(host2.dsuid) == original_host_dsuid
    logger.info("  %sPASS%s — host dSUID preserved.", GREEN, RESET)

    # ---- Verify vDC --------------------------------------------------
    assert len(host2.vdcs) == 1
    r_vdc = list(host2.vdcs.values())[0]
    assert str(r_vdc.dsuid) == original_vdc_dsuid
    logger.info("vDC restored: %s  dSUID: %s", r_vdc.name, r_vdc.dsuid)

    # ---- Verify device -----------------------------------------------
    assert len(r_vdc.devices) == 1
    r_device = list(r_vdc.devices.values())[0]
    assert str(r_device.dsuid) == original_device_dsuid
    assert len(r_device.vdsds) == 2
    logger.info(
        "Device restored: dSUID=%s  vdSDs=%d", r_device.dsuid, len(r_device.vdsds)
    )

    # ---- Verify vdSDs ------------------------------------------------
    r_sensor = r_device.get_vdsd(0)
    r_plug = r_device.get_vdsd(1)
    assert r_sensor is not None, "Sensor vdSD not restored"
    assert r_plug is not None, "Plug vdSD not restored"
    assert str(r_sensor.dsuid) == original_sensor_dsuid
    assert str(r_plug.dsuid) == original_plug_dsuid
    assert r_sensor.primary_group == VDSD_SENSOR_GROUP
    assert r_plug.primary_group == VDSD_PLUG_GROUP
    r_sensor.on_control_value = on_control_value
    r_plug.on_control_value = on_control_value
    logger.info(
        "  vdSD[0] '%s' group=%s  %sPASS%s",
        r_sensor.name,
        r_sensor.primary_group.name,
        GREEN,
        RESET,
    )
    logger.info(
        "  vdSD[1] '%s' group=%s  %sPASS%s",
        r_plug.name,
        r_plug.primary_group.name,
        GREEN,
        RESET,
    )

    # ==================================================================
    # PHASE 2a — Verify device state descriptions restored
    # ==================================================================
    section("Verifying device STATE descriptions after restart")

    assert len(r_sensor.device_states) == 2, (
        f"Expected 2 sensor states, got {len(r_sensor.device_states)}"
    )
    rs_operating = r_sensor.get_device_state(0)
    rs_connectivity = r_sensor.get_device_state(1)
    assert rs_operating is not None
    assert rs_connectivity is not None
    assert rs_operating.name == "operatingState"
    assert rs_operating.options == {
        0: "Off",
        1: "Initializing",
        2: "Running",
        3: "Error",
    }
    assert rs_operating.description == "Current operating state of the sensor node"
    assert rs_connectivity.name == "connectivity"
    assert rs_connectivity.options == {0: "Offline", 1: "Online", 2: "Degraded"}
    logger.info(
        "  %sPASS%s — Sensor: 2 state descriptions restored correctly.", GREEN, RESET
    )

    # State values are volatile — should be None after restart.
    assert rs_operating.value is None, (
        f"State value should be None after restart, got {rs_operating.value!r}"
    )
    assert rs_connectivity.value is None
    logger.info(
        "  %sPASS%s — Sensor: state values are None (volatile, as expected).",
        GREEN,
        RESET,
    )

    assert len(r_plug.device_states) == 2
    rp_relay = r_plug.get_device_state(0)
    rp_overheat = r_plug.get_device_state(1)
    assert rp_relay.name == "relayState"
    assert rp_relay.options == {0: "Open", 1: "Closed"}
    assert rp_overheat.name == "overheatingProtection"
    assert rp_overheat.options == {0: "Normal", 1: "Warning", 2: "ThermalShutdown"}
    logger.info(
        "  %sPASS%s — Plug: 2 state descriptions restored correctly.", GREEN, RESET
    )
    assert rp_relay.value is None
    logger.info("  %sPASS%s — Plug: state values are None (volatile).", GREEN, RESET)

    # ==================================================================
    # PHASE 2b — Verify device property descriptions & values restored
    # ==================================================================
    section("Verifying device PROPERTY descriptions & values after restart")

    assert len(r_sensor.device_properties) == 3
    rsp_battery = r_sensor.get_device_property(0)
    rsp_firmware = r_sensor.get_device_property(1)
    rsp_interval = r_sensor.get_device_property(2)
    assert rsp_battery is not None
    assert rsp_firmware is not None
    assert rsp_interval is not None

    # Description fields
    assert rsp_battery.name == "batteryLevel"
    assert rsp_battery.type == "numeric"
    assert rsp_battery.min_value == 0.0
    assert rsp_battery.max_value == 100.0
    assert rsp_battery.resolution == 1.0
    assert rsp_battery.siunit == "%"
    assert rsp_battery.default == 100.0
    assert rsp_battery.description == "Battery charge level"
    logger.info("  %sPASS%s — Sensor batteryLevel description restored.", GREEN, RESET)

    assert rsp_firmware.name == "firmwareVersion"
    assert rsp_firmware.type == "string"
    assert rsp_firmware.default == "0.0.0"
    logger.info(
        "  %sPASS%s — Sensor firmwareVersion description restored.", GREEN, RESET
    )

    assert rsp_interval.name == "reportingInterval"
    assert rsp_interval.siunit == "s"
    logger.info(
        "  %sPASS%s — Sensor reportingInterval description restored.", GREEN, RESET
    )

    # Values — device properties ARE persisted (unlike states).
    assert rsp_battery.value == saved_sensor_battery, (
        f"Expected battery={saved_sensor_battery}, got {rsp_battery.value}"
    )
    assert rsp_firmware.value == saved_sensor_firmware, (
        f"Expected firmware='{saved_sensor_firmware}', got {rsp_firmware.value!r}"
    )
    assert rsp_interval.value == saved_sensor_interval, (
        f"Expected interval={saved_sensor_interval}, got {rsp_interval.value}"
    )
    logger.info(
        "  %sPASS%s — Sensor property VALUES restored: "
        "battery=%.1f, firmware='%s', interval=%.1f",
        GREEN,
        RESET,
        rsp_battery.value,
        rsp_firmware.value,
        rsp_interval.value,
    )

    # Plug properties
    assert len(r_plug.device_properties) == 3
    rpp_power = r_plug.get_device_property(0)
    rpp_energy = r_plug.get_device_property(1)
    rpp_mode = r_plug.get_device_property(2)

    assert rpp_power.name == "currentPower"
    assert rpp_power.value == saved_plug_power
    assert rpp_energy.value == saved_plug_energy
    assert rpp_mode.name == "operatingMode"
    assert rpp_mode.type == "enumeration"
    assert rpp_mode.options == {0: "Normal", 1: "Timer", 2: "AlwaysOn"}
    assert rpp_mode.value == saved_plug_mode
    logger.info(
        "  %sPASS%s — Plug property VALUES restored: "
        "power=%.1f, energy=%.2f, mode='%s'",
        GREEN,
        RESET,
        rpp_power.value,
        rpp_energy.value,
        rpp_mode.value,
    )

    # ==================================================================
    # PHASE 2c — Verify device event descriptions restored
    # ==================================================================
    section("Verifying device EVENT descriptions after restart")

    assert len(r_sensor.device_events) == 2
    assert r_sensor.get_device_event(0).name == "tamperAlarm"
    assert (
        r_sensor.get_device_event(0).description == "Enclosure tamper switch triggered"
    )
    assert r_sensor.get_device_event(1).name == "lowBattery"
    logger.info("  %sPASS%s — Sensor: 2 event descriptions restored.", GREEN, RESET)

    assert len(r_plug.device_events) == 2
    assert r_plug.get_device_event(0).name == "overcurrentTrip"
    assert r_plug.get_device_event(1).name == "localButtonPress"
    logger.info("  %sPASS%s — Plug: 2 event descriptions restored.", GREEN, RESET)

    # ==================================================================
    # PHASE 2d — Verify get_properties() on restored vdSDs
    # ==================================================================
    section("Verifying get_properties() on restored vdSDs")

    r_sensor_props = r_sensor.get_properties()
    assert "deviceStateDescriptions" in r_sensor_props
    assert "deviceStates" in r_sensor_props
    assert "devicePropertyDescriptions" in r_sensor_props
    assert "deviceProperties" in r_sensor_props
    assert "deviceEventDescriptions" in r_sensor_props
    logger.info(
        "  %sPASS%s — Sensor: all 5 device-level property groups present.", GREEN, RESET
    )

    r_plug_props = r_plug.get_properties()
    assert "deviceStateDescriptions" in r_plug_props
    assert "devicePropertyDescriptions" in r_plug_props
    assert "deviceEventDescriptions" in r_plug_props
    # Verify persisted values come through
    assert r_plug_props["deviceProperties"]["currentPower"] == saved_plug_power
    assert r_plug_props["deviceProperties"]["operatingMode"] == saved_plug_mode
    logger.info(
        "  %sPASS%s — Plug: property values exposed correctly in get_properties().",
        GREEN,
        RESET,
    )

    # ==================================================================
    # PHASE 2e — Re-announce & push state updates
    # ==================================================================
    section("Re-announcing to vdSM")

    # Re-register callbacks (not persisted).
    r_out_sensor = r_sensor.output
    r_out_plug = r_plug.output
    if r_out_sensor:
        r_out_sensor.on_channel_applied = on_channel_applied
    if r_out_plug:
        r_out_plug.on_channel_applied = on_channel_applied

    await host2.start(on_message=on_message)
    logger.info("TCP server restarted — waiting for vdSM...")

    try:
        await wait_for_session(host2, CONNECT_TIMEOUT)
    except TimeoutError as exc:
        logger.error(str(exc))
        await host2.stop()
        return

    announced_vdcs = await host2.announce_vdcs()
    logger.info("vDC re-announced (%d/%d).", announced_vdcs, len(host2.vdcs))

    session2 = host2.session
    assert session2 is not None and session2.is_active
    announced = await r_vdc.announce_devices(session2)
    logger.info("Device re-announced (%d vdSD(s)).", announced)

    # ---- Push state updates over the live connection -----------------
    section("Pushing state updates to vdSM")

    logger.info("Pushing sensor operatingState = 2 (Running)...")
    await rs_operating.update_value(2, session2)  # Running
    logger.info("  %sPASS%s — operatingState pushed.", GREEN, RESET)

    logger.info("Pushing sensor connectivity = 1 (Online)...")
    await rs_connectivity.update_value(1, session2)  # Online
    logger.info("  %sPASS%s — connectivity pushed.", GREEN, RESET)

    logger.info("Pushing plug relayState = 1 (Closed)...")
    await rp_relay.update_value(1, session2)  # Closed
    logger.info("  %sPASS%s — relayState pushed.", GREEN, RESET)

    # ---- Push property updates over the live connection --------------
    section("Pushing property updates to vdSM")

    logger.info("Pushing sensor batteryLevel = 85.0...")
    await rsp_battery.update_value(85.0, session2)
    assert rsp_battery.value == 85.0
    logger.info("  %sPASS%s — batteryLevel pushed.", GREEN, RESET)

    logger.info("Pushing plug currentPower = 200.3W...")
    await rpp_power.update_value(200.3, session2)
    assert rpp_power.value == 200.3
    logger.info("  %sPASS%s — currentPower pushed.", GREEN, RESET)

    # ---- Push device events over the live connection -----------------
    section("Pushing device events to vdSM")

    sensor_evt_tamper_r = r_sensor.get_device_event(0)
    sensor_evt_lowbat_r = r_sensor.get_device_event(1)
    plug_evt_overcurrent_r = r_plug.get_device_event(0)

    logger.info("Raising sensor tamperAlarm event...")
    await sensor_evt_tamper_r.raise_event(session2)
    logger.info("  %sPASS%s — tamperAlarm raised.", GREEN, RESET)

    logger.info("Raising sensor lowBattery event...")
    await sensor_evt_lowbat_r.raise_event(session2)
    logger.info("  %sPASS%s — lowBattery raised.", GREEN, RESET)

    logger.info("Raising plug overcurrentTrip event...")
    await plug_evt_overcurrent_r.raise_event(session2)
    logger.info("  %sPASS%s — overcurrentTrip raised.", GREEN, RESET)

    await wait_for_user(
        ">>> Phase 2 complete: persistence verified, states/props/events pushed.\n"
        ">>> The dSS should have received the push notifications.\n"
        ">>> Press Enter to vanish and clean up..."
    )

    # ==================================================================
    # PHASE 3 — Vanish, shutdown & cleanup
    # ==================================================================
    banner("PHASE 3: Vanish, shutdown & cleanup")

    session2 = host2.session
    if session2 is not None and session2.is_active:
        logger.info("Vanishing device from vdSM...")
        await r_device.vanish(session2)
        assert not r_device.is_announced
        logger.info("Device vanished.")
        # Allow the vdSM to process the vanish notifications before
        # we tear down the connection.
        await asyncio.sleep(2)
    else:
        logger.warning("Session not active — cannot vanish cleanly.")

    # host.stop() now unregisters the DNS-SD/Avahi service *before*
    # closing the TCP session, so the vdSM sees the service disappear
    # and stops attempting reconnections.
    await host2.stop()
    logger.info("VdcHost stopped.")
    # Give the network a moment for the Avahi goodbye to propagate.
    await asyncio.sleep(2)

    # Delete persistence files.
    if host2._store is not None:
        host2._store.delete()
        logger.info("Persistence files deleted.")

    assert not STATE_FILE.exists(), f"{STATE_FILE} still exists!"
    bak_file = STATE_FILE.with_suffix(STATE_FILE.suffix + ".bak")
    assert not bak_file.exists(), f"{bak_file} still exists!"
    logger.info("Cleanup verified — no leftover files.")

    banner("STATE/PROPERTY/EVENT DEMO COMPLETE")
    logger.info("All phases completed successfully.")
    logger.info("")
    logger.info("Summary:")
    logger.info("  Phase 1: Created 2 vdSDs (Sensor Node/Cyan + Smart Plug/Yellow)")
    logger.info("           Sensor: 2 states, 3 properties, 2 events")
    logger.info("           Plug:   2 states, 3 properties, 2 events")
    logger.info("           Verified get_properties() exposure")
    logger.info("           Set initial state + property values")
    logger.info("           Announced to dSS, auto-save verified")
    logger.info("  Phase 2: Restored from YAML persistence")
    logger.info("           State descriptions preserved, values volatile (None)")
    logger.info("           Property descriptions + values preserved")
    logger.info("           Event descriptions preserved")
    logger.info("           Re-announced, pushed state + property + event updates")
    logger.info("  Phase 3: Vanished device, cleaned up")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by user.{RESET}")
