#!/usr/bin/env python3
"""GTIN + dynamicDefinitions validation test.

Tests what the dSS actually shows in the automation configurator and
config UI when:

  - ``oem_model_guid`` = ``gs1:(01)1234567890123``  (RegressionTestDevice)
  - ``dynamic_definitions=True`` on the VDC

Goal: verify which of the four feature types (state, action, event,
property) are visible in the dSS UI surfaces and under what conditions.

Device definition
-----------------
- 1 state   : ``pyVDC_State``    — options: idle / running / error
- 1 action  : ``pyVDC_Action``   — parameter: ``level`` (0–100 %)
- 1 event   : ``pyVDC_Event``    — stateless push notification
- 1 property: ``pyVDC_Property`` — numeric, 0–1000, unit "ppm"

The loop prints the current state value every 10 s and lets you trigger
a push update or fire the event by pressing Enter.

Usage::

    python examples/test_gtin_1234_dynamic.py [--port PORT]
"""

from __future__ import annotations

import argparse
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
    OutputMode,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)
from pydsvdcapi.actions import ActionParameter, CustomAction, DeviceActionDescription
from pydsvdcapi.device_property import PROPERTY_TYPE_NUMERIC, DeviceProperty
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.enums import ColorClass, OutputUsage

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8444
STATE_FILE = Path("/tmp/pydsvdcapi_gtin1234_test.yaml")

# The GTIN under test: unknown GTIN — not present in the vdc-db, so no
# pre-allocated /usr/states/ slots exist for this device.
GTIN = "gs1:(01)9999999999993"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
GREY = "\033[90m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RED = "\033[91m"


class ColourFormatter(logging.Formatter):
    LEVEL_COLOURS = {
        logging.DEBUG: GREY,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, "")
        ts = self.formatTime(record, "%H:%M:%S")
        return f"{GREY}{ts}{RESET} {colour}{record.getMessage()}{RESET}"


def setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(ColourFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    root.setLevel(logging.INFO)


def info(msg: str) -> None:
    logging.getLogger("test").info(msg)


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------


async def wait_for_session(host: VdcHost, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while host.session is None or not host.session.is_active:
        if time.monotonic() > deadline:
            raise TimeoutError(f"No vdSM/dSS connected within {timeout:.0f}s")
        await asyncio.sleep(0.5)
    info(f"{GREEN}Session established with vdSM{RESET}")


# ---------------------------------------------------------------------------
# Build device
# ---------------------------------------------------------------------------


def build_device(
    vdc: Vdc,
) -> tuple[
    Device,
    Vdsd,
    DeviceState,
    DeviceState,
    DeviceEvent,
    DeviceProperty,
    DeviceActionDescription,
]:
    """Create the test device with two states, action, event, property."""

    dsuid = DsUid.from_name_in_space("gtin-1234-test-device", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="pyVDC Test Device",
        model="pyVDC-GTIN-Tester v1",
        model_version="1.0.0",
        vendor_name="pyDSvDCAPI",
        vendor_guid="gs1:(01)0000000000000",
        hardware_guid="mac-address:00:11:22:33:44:55",
        hardware_model_guid="ean:(01)0000000000001",
        primary_group=ColorClass.WHITE,
        # ---- GTIN under test ----
        oem_model_guid=GTIN,
        zone_id=0,
    )
    device.add_vdsd(vdsd)

    # ---- Output (CUSTOM / DISABLED — action-only device) ---------------
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.CUSTOM,
        mode=OutputMode.DISABLED,
        default_group=int(ColorGroup.MAGENTA),
        active_group=int(ColorGroup.MAGENTA),
        groups={int(ColorGroup.MAGENTA)},
    )
    vdsd.set_output(output)

    # ---- State: pyVDC_State -------------------------------------------
    state = DeviceState(
        vdsd=vdsd,
        ds_index=0,
        name="pyVDC_State",
        options={0: "idle", 1: "running", 2: "error"},
        description="Test state for GTIN validation",
    )
    vdsd.add_device_state(state)

    # ---- State: pyVDC_Mode --------------------------------------------
    state2 = DeviceState(
        vdsd=vdsd,
        ds_index=1,
        name="pyVDC_Mode",
        options={0: "off", 1: "auto", 2: "manual"},
        description="Second test state for GTIN validation",
    )
    vdsd.add_device_state(state2)

    # ---- Action: pyVDC_Action ----------------------------------------
    param = ActionParameter(
        name="level",
        type="numeric",
        min_value=0.0,
        max_value=100.0,
        resolution=1.0,
        siunit="%",
        default=50.0,
    )
    action_desc = DeviceActionDescription(
        vdsd=vdsd,
        ds_index=0,
        name="pyVDC_Action",
        params=[param],
        description="Test action for GTIN validation",
    )
    vdsd.add_device_action_description(action_desc)

    # Named preset for the action
    custom = CustomAction(
        vdsd=vdsd,
        ds_index=0,
        name="custom.pyVDC_Action-full",
        action="pyVDC_Action",
        title="pyVDC Action Full",
        params={"level": 100.0},
    )
    vdsd.add_custom_action(custom)

    # ---- Event: pyVDC_Event ------------------------------------------
    event = DeviceEvent(
        vdsd=vdsd,
        ds_index=0,
        name="pyVDC_Event",
        description="Test event for GTIN validation",
    )
    vdsd.add_device_event(event)

    # ---- Property: pyVDC_Property ------------------------------------
    prop = DeviceProperty(
        vdsd=vdsd,
        ds_index=0,
        name="pyVDC_Property",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=1000.0,
        resolution=0.1,
        siunit="ppm",
        default=0.0,
        description="Test property for GTIN validation",
    )
    vdsd.add_device_property(prop)

    # ---- Action callback --------------------------------------------
    async def on_invoke(action_id: str, params: dict) -> None:
        level = params.get("level", 0.0)
        info(f"{MAGENTA}ACTION invoked{RESET}  id='{action_id}'  level={level}%")

    vdsd.on_invoke_action = on_invoke

    # ---- Model features ---------------------------------------------
    vdsd.add_model_feature("highlevel")
    vdsd.add_model_feature("customactivityconfig")
    vdsd.derive_model_features()

    return device, vdsd, state, state2, event, prop, action_desc


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

_STATE_VALUES = ["idle", "running", "error"]
_state_index = 0
_MODE_VALUES = ["off", "auto", "manual"]
_mode_index = 0
_prop_value = 0.0


async def interactive_loop(
    host: VdcHost,
    vdsd: Vdsd,
    state: DeviceState,
    state2: DeviceState,
    event: DeviceEvent,
    prop: DeviceProperty,
) -> None:
    global _state_index, _mode_index, _prop_value

    loop = asyncio.get_running_loop()

    print(f"\n{BOLD}{CYAN}Interactive loop started.{RESET}")
    print("  Enter  → cycle pyVDC_State + pyVDC_Mode + update property")
    print("  e      → fire pyVDC_Event")
    print("  q      → quit\n")

    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = raw.strip().lower()

        if cmd == "q":
            info("Quitting…")
            break
        elif cmd == "e":
            await event.raise_event()
            info(f"{YELLOW}EVENT pushed{RESET}  pyVDC_Event fired")
        else:
            # cycle state 1
            _state_index = (_state_index + 1) % len(_STATE_VALUES)
            new_state = _STATE_VALUES[_state_index]
            await state.update_value(new_state)
            info(f"{GREEN}STATE pushed{RESET}  pyVDC_State = '{new_state}'")

            # cycle state 2
            _mode_index = (_mode_index + 1) % len(_MODE_VALUES)
            new_mode = _MODE_VALUES[_mode_index]
            await state2.update_value(new_mode)
            info(f"{GREEN}STATE pushed{RESET}  pyVDC_Mode  = '{new_mode}'")

            # update property
            _prop_value = round((_prop_value + 42.5) % 1000.0, 1)
            prop.value = _prop_value
            info(f"{CYAN}PROPERTY updated{RESET}  pyVDC_Property = {_prop_value} ppm")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    setup_logging()

    # Clean up leftover persistence
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
            info(f"Removed leftover {p}")

    # ---- Build host + VDC ------------------------------------------
    host = VdcHost(
        port=args.port,
        model="pyVDC GTIN-1234 Tester",
        name="gtin-1234-test-host",
        vendor_name="pyDSvDCAPI",
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-gtin1234-test",
        name="GTIN-1234 Test vDC",
        model="pydsvdcapi-gtin1234-tester",
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,  # ← key setting under test
        ),
    )
    host.add_vdc(vdc)

    # ---- Build device -----------------------------------------------
    device, vdsd, state, state2, event, prop, action_desc = build_device(vdc)

    info(f"GTIN under test : {BOLD}{GTIN}{RESET}")
    info(f"dynamic_definitions : {BOLD}True{RESET}")
    info("")
    info("Device features defined by this VDC:")
    info(f"  State   : pyVDC_State   (options: idle / running / error)")
    info(f"  State   : pyVDC_Mode    (options: off / auto / manual)")
    info(f"  Action  : pyVDC_Action  (param: level 0–100 %)")
    info(f"  Event   : pyVDC_Event")
    info(f"  Property: pyVDC_Property (0–1000 ppm)")
    info("")
    info("DB-defined features for GTIN 1234567890123:")
    info(f"  State   : dummyState    (options: d / mm / u / y)")
    info(f"  Property: dummyProperty (string)")
    info(f"  Actions : dummyAction1, dummyAction2, …")
    info(f"  Events  : dummyEventOther, dummyEventUI2, Nochnevent")
    info("")
    info("Observed behaviour (dynamicDefinitions=True + GTIN with DB state row):")
    info(
        "  Condition/trigger picker: shows pyVDC_State / pyVDC_Mode (dynamicDefs overrides DB)"
    )
    info(
        "  Hardware tab status    : shows pushed state values correctly (m_data->states path)"
    )
    info(
        "  Automation evaluation  : FAILS — /usr/states/ only has dummyState, not pyVDC_*"
    )
    info(
        "  DeviceStateEvent fires : yes (mechanism 3 works), but value check in rule fails"
    )
    info("  Property UI            : shows pyVDC_Property (dynamicDefs)")
    info("")

    # ---- Start and wait for session ----------------------------------
    await host.start()
    info(f"Listening on port {args.port} — waiting for vdSM/dSS connection…")
    await wait_for_session(host, timeout=120.0)

    # ---- Announce device --------------------------------------------
    await device.announce(host.session)
    info(f"{GREEN}Device announced{RESET}  dSUID={device.dsuid}")
    info(f"  vdSD dSUID : {vdsd.dsuid}")
    info("")
    info("Now check the dSS UI:")
    info("  1. Hardware tab  → 'highlevel' model feature → action UI visible?")
    info("  2. Automation: Scene Responder / UDA → device in trigger list?")
    info("     → which names: pyVDC_Action/Event or dummyAction/Event?")
    info("  3. Automation: condition picker → is pyVDC_State or dummyState shown?")
    info("  4. Config UI (getInfo) → is pyVDC_Property shown?")
    info("")

    # ---- Initial state/property push --------------------------------
    await state.update_value("idle")
    info(f"{GREEN}Initial STATE push{RESET}  pyVDC_State = 'idle'")
    await state2.update_value("off")
    info(f"{GREEN}Initial STATE push{RESET}  pyVDC_Mode  = 'off'")
    prop.value = 0.0
    info(f"{CYAN}Initial PROPERTY set{RESET}  pyVDC_Property = 0.0 ppm")

    # ---- Interactive loop -------------------------------------------
    await interactive_loop(host, vdsd, state, state2, event, prop)

    # ---- Cleanup ----------------------------------------------------
    await device.vanish(host.session)
    await host.stop()
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
    info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
