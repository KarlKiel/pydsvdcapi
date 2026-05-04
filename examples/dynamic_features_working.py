#!/usr/bin/env python3
"""Dynamic features integration test — states, events, and actions.

This script creates a VdSD that exposes states, events, and actions via the
``dynamicDefinitions=True`` path and verifies what actually functions in the
dSS add-on UIs (Scene Responder, UDA, hardware tab).

=============================================================================
FIRMWARE BEHAVIOR — READ BEFORE TESTING
=============================================================================

Based on reverse-engineering dss-mainline-master firmware source:

``hasActions`` flag (controls "Activities" tab visibility):
    Set during device discovery from ``VdcDb::hasActionInterface(gtin)``:
    ``SELECT name FROM device WHERE gtin=?``.  No VDC override.  Requires
    the GTIN to exist in the VdcDb ``device`` table on the dSS.

    → Set ``WORKING_GTIN`` below to a GTIN that is in your dSS VdcDb.
      The GTIN ``23456789…`` (often called the "test GTIN") is known to be
      registered and yields ``hasActions=True``.

State/event/action DESCRIPTIONS (what the configurator UI shows):
    With ``dynamicDefinitions=True`` the dSS queries the VDC live for
    ``deviceStateDescriptions``, ``deviceEventDescriptions``, and
    ``deviceActionDescriptions``.  The GTIN's VdcDb entries are IGNORED for
    descriptions; the VDC's own definitions are shown.

    → Names and options chosen here will appear in the UI.

State CONDITION evaluation (state-value-based automation rules):
    Populated at discovery from ``db->getStatesLegacy(gtin)`` into the
    ``/usr/states/<id>`` object tree.  When a push notification arrives,
    ``Device::setStateValue(name, value)`` looks up ``m_states[name]``; if
    the name is not in that map (unknown GTIN / name mismatch), the call is
    a silent no-op.

    → State-based condition evaluation FAILS for unknown GTINs or when the
      VdSD's state names differ from the VdcDb state names.

``DeviceStateEvent`` automation trigger (event-triggered rules):
    When a state push arrives, ``createDeviceStateEvent(dev, stateId, value)``
    is raised UNCONDITIONALLY before the ``setStateValue`` call.  Automation
    rules that subscribe to ``DeviceStateEvent`` (a push-based trigger, not
    a state-condition check) WILL fire with the correct ``stateId`` and
    ``value`` properties.

    → Use event-triggered rules in Scene Responder / UDA rather than
      state-condition rules for reliable automation.

Device events (``DeviceEventEvent``):
    Pushed via ``VDC_SEND_PUSH_NOTIFICATION.deviceevents``; handled by
    ``createDeviceEventEvent`` regardless of GTIN.

    → Events work reliably.

Actions (``invokeDeviceAction``):
    Sent from dSS as ``VDSM_REQUEST_GENERIC_REQUEST`` with
    ``methodname="invokeDeviceAction"``.  With ``dynamicDefinitions=True``
    the action descriptions come from the VDC.  The VDC must handle the
    generic request and dispatch to the correct action handler.

    → Actions work when the VDC handles the generic request.

Custom actions:
    ``customActions`` and ``dynamicActionDescriptions`` are ALWAYS read
    from the VDC regardless of ``dynamicDefinitions`` flag.

=============================================================================
CONFIGURATION
=============================================================================

Set ``WORKING_GTIN`` to a GTIN that IS in your dSS's VdcDb ``device`` table.
The GTIN determines whether ``hasActions=True`` → Activities tab visible.

Known working GTINs (depends on the firmware version installed on your dSS):
  - The "magic" test GTIN used in the digitalSTROM ecosystem (often starts
    with 2345678…) — replace the Xs below with your actual digits.
  - GTIN ``1234567890123`` is another commonly registered test GTIN.

If the Activities tab does NOT appear after connecting, the GTIN is not in
your dSS VdcDb.

=============================================================================
WHAT TO VERIFY IN THE dSS UI
=============================================================================

After running and connecting to dSS:

1. Hardware tab → states/properties:
   - Shows current state values (operatingMode, connectivity).
   - Pushes update the display in real time.

2. Add-on app "Scene Responder" / Activities tab:
   - Tab visible only if GTIN is registered (hasActions=True).
   - Event trigger: select device → choose "testAlarm" event.
   - State trigger: select device → choose "operatingMode" state change.
     (Shows options: standby / running / error)
   - Action: choose "setMode" action with parameter "mode".

3. Event-triggered automation:
   - Create a rule: WHEN "testAlarm" event on this device THEN …
   - Press 'e' in the loop → event fires → rule should execute.

4. State-change automation (DeviceStateEvent trigger):
   - Create a rule: WHEN state "operatingMode" changes on this device THEN …
   - Press Enter in the loop → state cycles → DeviceStateEvent fires → rule
     should execute IF the add-on uses the push event as trigger.
   - NOTE: state-VALUE-based conditions (e.g. "when operatingMode == running")
     may NOT evaluate correctly unless the GTIN has matching state defs in
     VdcDb.  Use the event trigger instead.

5. Action invocation:
   - In the add-on, select the "setMode" action → enter a mode name.
   - The VDC prints "ACTION: setMode  mode=<value>" when dSS calls it.

=============================================================================
USAGE
=============================================================================

    python examples/dynamic_features_working.py [--port PORT] [--gtin GTIN]

Press Enter  → cycle operatingMode + connectivity states
Press 'e'    → raise testAlarm event
Press 'q'    → quit
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
from pydsvdcapi.actions import ActionParameter, DeviceActionDescription, StandardAction
from pydsvdcapi.device_property import PROPERTY_TYPE_NUMERIC, DeviceProperty
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.enums import ColorClass

# ---------------------------------------------------------------------------
# Configuration — EDIT THIS GTIN
# ---------------------------------------------------------------------------

# Replace with a GTIN that exists in your dSS VdcDb device table.
# The GTIN controls hasActions=True (Activities tab visibility).
# Keep the gs1:(01) prefix; the firmware strips it internally.
DEFAULT_GTIN = "gs1:(01)2345678901289"  # ← replace with your working GTIN

DEFAULT_PORT = 8444
STATE_FILE = Path("/tmp/pydsvdcapi_dynamic_features_test.yaml")

# ---------------------------------------------------------------------------
# ANSI colour helpers
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


def setup_logging(debug: bool = False) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(ColourFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(h)
    root.setLevel(logging.DEBUG if debug else logging.INFO)


def info(msg: str) -> None:
    logging.getLogger("test").info(msg)


# ---------------------------------------------------------------------------
# Wait helper
# ---------------------------------------------------------------------------


async def wait_for_session(host: VdcHost, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while host.session is None or not host.session.is_active:
        if time.monotonic() > deadline:
            raise TimeoutError(f"No vdSM/dSS connected within {timeout:.0f}s")
        await asyncio.sleep(0.5)
    info(f"{GREEN}Session established{RESET}")


# ---------------------------------------------------------------------------
# Device construction
# ---------------------------------------------------------------------------


def build_device(
    vdc: Vdc,
    gtin: str,
) -> tuple[
    Device,
    Vdsd,
    DeviceState,
    DeviceState,
    DeviceEvent,
    DeviceProperty,
    DeviceActionDescription,
]:
    """Build a single VdSD with states, events, action, property."""

    dsuid = DsUid.from_name_in_space("dynamic-features-test-device", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Dynamic Features Test Device",
        model="pyVDC-DynFeat-Tester v1",
        model_version="1.0.0",
        vendor_name="pyDSvDCAPI",
        vendor_guid="gs1:(01)0000000000000",
        hardware_guid="mac-address:DE:AD:BE:EF:CA:FE",
        hardware_model_guid="ean:(01)0000000000002",
        primary_group=ColorClass.BLACK,  # Joker = BLACK
        oem_model_guid=gtin,
        zone_id=0,
    )
    device.add_vdsd(vdsd)

    # ---- Output (action-only, no physical dimmer/switch) ---------------
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.CUSTOM,
        mode=OutputMode.DISABLED,
        default_group=int(ColorGroup.BLACK),
        active_group=int(ColorGroup.BLACK),
        groups={int(ColorGroup.BLACK)},
    )
    vdsd.set_output(output)

    # ---- State 1: operatingMode -----------------------------------------
    # Options use string labels that will appear in the dSS condition picker.
    state_mode = DeviceState(
        vdsd=vdsd,
        ds_index=0,
        name="operatingMode",
        options={0: "standby", 1: "running", 2: "error"},
        description="Current operating mode of the device",
    )
    vdsd.add_device_state(state_mode)

    # ---- State 2: connectivity ------------------------------------------
    state_conn = DeviceState(
        vdsd=vdsd,
        ds_index=1,
        name="connectivity",
        options={0: "offline", 1: "online", 2: "degraded"},
        description="Network connectivity status",
    )
    vdsd.add_device_state(state_conn)

    # ---- Event: testAlarm -----------------------------------------------
    event = DeviceEvent(
        vdsd=vdsd,
        ds_index=0,
        name="testAlarm",
        description="Test alarm event — fires on demand",
    )
    vdsd.add_device_event(event)

    # ---- Property: uptimeSecs -------------------------------------------
    prop = DeviceProperty(
        vdsd=vdsd,
        ds_index=0,
        name="uptimeSecs",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=2_147_483_647.0,
        resolution=1.0,
        siunit="s",
        default=0.0,
        description="Device uptime in seconds",
    )
    vdsd.add_device_property(prop)

    # ---- Action template: setMode ---------------------------------------
    # The action ID used in invokeDeviceAction; names are free-form.
    # Using "string" type so any label can be passed without enum-mismatch risk.
    mode_param = ActionParameter(
        name="mode",
        type="string",
        default="standby",
    )
    action_desc = DeviceActionDescription(
        vdsd=vdsd,
        ds_index=0,
        name="setMode",
        params=[mode_param],
        description="Set the operating mode of the device",
    )
    vdsd.add_device_action_description(action_desc)

    # Standard action referencing the template (std.* prefix required for
    # standardActions list; always queried from VDC when dynamicDefinitions=True)
    std_standby = StandardAction(
        vdsd=vdsd,
        ds_index=0,
        name="std.setMode.standby",
        action="setMode",
        title="Set mode: standby",
        params={"mode": "standby"},
    )
    std_running = StandardAction(
        vdsd=vdsd,
        ds_index=1,
        name="std.setMode.running",
        action="setMode",
        title="Set mode: running",
        params={"mode": "running"},
    )
    vdsd.add_standard_action(std_standby)
    vdsd.add_standard_action(std_running)

    # ---- Model features ------------------------------------------------
    # highlevel: enables "Activities" display in dSS
    # jokerconfig: standard joker device configuration UI
    vdsd.add_model_feature("highlevel")
    vdsd.add_model_feature("jokerconfig")
    vdsd.derive_model_features()

    # ---- Action invocation callback ------------------------------------
    async def on_invoke(vdsd_ref: Vdsd, action_id: str, params: dict) -> None:
        mode = params.get("mode", "<none>")
        info(f"{MAGENTA}ACTION RECEIVED{RESET}  id='{action_id}'  mode='{mode}'")
        # Reflect the action's mode into the operatingMode state.
        new_val = {"standby": 0, "running": 1}.get(mode, 2)
        await state_mode.update_value(new_val)
        info(
            f"{GREEN}STATE UPDATED{RESET}  operatingMode → '{state_mode._options[new_val]}' "
            f"(pushed to dSS)"
        )

    vdsd.on_invoke_action = on_invoke

    return device, vdsd, state_mode, state_conn, event, prop, action_desc


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

_MODE_SEQ = ["standby", "running", "error"]
_CONN_SEQ = ["offline", "online", "degraded"]
_mode_idx = 0
_conn_idx = 0
_uptime_start = time.monotonic()


async def interactive_loop(
    vdsd: Vdsd,
    state_mode: DeviceState,
    state_conn: DeviceState,
    event: DeviceEvent,
    prop: DeviceProperty,
) -> None:
    global _mode_idx, _conn_idx

    loop = asyncio.get_running_loop()

    print(f"\n{BOLD}{CYAN}Interactive loop ready.{RESET}")
    print(
        f"  {BOLD}Enter{RESET}  → cycle operatingMode + connectivity + update uptime property"
    )
    print(f"  {BOLD}e{RESET}      → raise testAlarm event")
    print(f"  {BOLD}q{RESET}      → quit\n")

    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = raw.strip().lower()

        if cmd == "q":
            info("Quitting…")
            break

        elif cmd == "e":
            await event.raise_event()
            info(
                f"{YELLOW}EVENT raised{RESET}  'testAlarm'  "
                f"→ DeviceEventEvent fires in dSS"
            )

        else:
            # Cycle operatingMode
            _mode_idx = (_mode_idx + 1) % len(_MODE_SEQ)
            new_mode = _MODE_SEQ[_mode_idx]
            await state_mode.update_value(new_mode)
            info(
                f"{GREEN}STATE pushed{RESET}  operatingMode = '{new_mode}'  "
                f"→ DeviceStateEvent(stateId='operatingMode', value='{new_mode}') "
                f"fires in dSS"
            )

            # Cycle connectivity
            _conn_idx = (_conn_idx + 1) % len(_CONN_SEQ)
            new_conn = _CONN_SEQ[_conn_idx]
            await state_conn.update_value(new_conn)
            info(f"{GREEN}STATE pushed{RESET}  connectivity   = '{new_conn}'")

            # Update uptime property
            uptime = round(time.monotonic() - _uptime_start, 0)
            prop.value = uptime
            info(f"{CYAN}PROPERTY updated{RESET}  uptimeSecs = {uptime:.0f}s")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP port to listen on (default: 8444)",
    )
    parser.add_argument(
        "--gtin",
        default=DEFAULT_GTIN,
        help=f"GTIN for the VdSD (default: {DEFAULT_GTIN})",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug-level logging"
    )
    args = parser.parse_args()

    setup_logging(debug=args.debug)

    # Clean up leftover persistence from previous runs.
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
            info(f"Removed leftover {p}")

    # ---- Build VdcHost + VDC ------------------------------------------
    host = VdcHost(
        port=args.port,
        model="pyVDC Dynamic Features Tester",
        name="dynamic-features-test-host",
        vendor_name="pyDSvDCAPI",
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-dynfeat-test",
        name="Dynamic Features Test VDC",
        model="pydsvdcapi-dynfeat-tester",
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            # dynamicDefinitions=True → dSS queries state/event/action/property
            # descriptions live from this VDC instead of from its VdcDb.
            # Required for our custom names to appear in the configurator UI.
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    # ---- Build device --------------------------------------------------
    device, vdsd, state_mode, state_conn, event, prop, action_desc = build_device(
        vdc, args.gtin
    )

    # ---- Print startup summary -----------------------------------------
    info("")
    info(f"{BOLD}Dynamic Features Test Device{RESET}")
    info(f"  GTIN            : {BOLD}{args.gtin}{RESET}")
    info(f"  dynamicDefs     : {BOLD}True{RESET}  (descriptions from VDC, not VdcDb)")
    info(f"  Port            : {args.port}")
    info("")
    info(f"{BOLD}Device announces:{RESET}")
    info("  States  : operatingMode (standby/running/error)")
    info("            connectivity (offline/online/degraded)")
    info("  Event   : testAlarm")
    info("  Action  : setMode(mode=standby|running)")
    info("  Property: uptimeSecs")
    info("")
    info(f"{BOLD}Expected dSS behavior:{RESET}")
    info(
        f"  hasActions      : {'True (Activities tab visible)' if args.gtin else 'depends on GTIN'}"
    )
    info("  Descriptions    : from VDC (dynamicDefinitions=True)")
    info("  State triggers  : DeviceStateEvent fires on push → event rules work")
    info("  State conditions: only work if GTIN has matching state names in VdcDb")
    info("  Events          : DeviceEventEvent fires → event rules work")
    info(
        "  Actions         : invokeDeviceAction dispatched to on_invoke_action callback"
    )
    info("")

    # ---- Start host ----------------------------------------------------
    await host.start()
    info(f"Listening on port {args.port} — waiting for vdSM/dSS…")

    try:
        await wait_for_session(host, timeout=120.0)
    except TimeoutError as exc:
        logging.error(str(exc))
        await host.stop()
        return

    # ---- Announce device -----------------------------------------------
    await device.announce(host.session)
    info(f"{GREEN}Device announced{RESET}  dSUID={device.dsuid}")
    info(f"  VdSD dSUID : {vdsd.dsuid}")
    info("")

    # ---- Push initial state values -------------------------------------
    await state_mode.update_value("standby")
    info(f"{GREEN}Initial STATE{RESET}  operatingMode = 'standby'")
    await state_conn.update_value("online")
    info(f"{GREEN}Initial STATE{RESET}  connectivity  = 'online'")
    prop.value = 0.0
    info(f"{CYAN}Initial PROPERTY{RESET}  uptimeSecs = 0")
    info("")

    # ---- Interactive loop ----------------------------------------------
    await interactive_loop(vdsd, state_mode, state_conn, event, prop)

    # ---- Cleanup -------------------------------------------------------
    if host.session and host.session.is_active:
        await device.vanish(host.session)
    await host.stop()
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
    info("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}")
