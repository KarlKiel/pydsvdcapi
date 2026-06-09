#!/usr/bin/env python3
"""Example VDC — 8 blue (CLIMATE) virtual devices.

Demonstrates eight main climate configurations:
  C1  Room Heating Valve       — HEATING (3),              POSITIONAL, heatingPower channel
  C2  Room Cooling Device      — COOLING (9),              POSITIONAL, coolingCapacity channel
  C3  Room Ventilation         — VENTILATION (10),         POSITIONAL, airFlow+direction+louver
  C4  Window Opener            — WINDOW (11),              POSITIONAL, shadePositionOutside
  C5  Recirculation / FCU      — RECIRCULATION (12),       POSITIONAL, heat+cool+flow+louver
  C6  Apartment Ventilation    — APARTMENT_VENTILATION (64), POSITIONAL, airFlowIntensity 0–100
  C7  Apartment Recirculation  — APARTMENT_RECIRCULATION (69), POSITIONAL, airFlowIntensity 0–100
  C8  Temperature Controller   — TEMPERATURE_CONTROL (48), INTERNALLY_CONTROLLED (no channels)

Console commands (press Enter after typing):
  r       restart: vanish all → wait 20 s → reconnect (tests persistence)
  q       quit cleanly: vanish, stop, delete persistence files
  x       exit without cleanup (keeps persistence for next run)

Channel values change automatically every 30–90 s (mocked).
C8 has no channels and is skipped by the mock loop.

Usage:
    python examples/example_climate.py [--port PORT] [--debug]
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
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydsvdcapi import (
    ColorClass,
    ColorGroup,
    Device,
    DsUid,
    DsUidNamespace,
    Output,
    OutputChannelType,
    OutputFunction,
    OutputUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)
from pydsvdcapi.enums import HeatingSystemCapability, HeatingSystemType

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8343
STATE_FILE = Path("/tmp/pydsvdcapi_example_climate.yaml")

VENDOR_NAME = "pydsvdcapi Examples"
VENDOR_GUID = "gs1:(01)0000000000001"

_RUN_ID = uuid.uuid4().hex[:8]

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
GREY_C = "\033[90m"
RED_C = "\033[91m"
GREEN_C = "\033[92m"
YELLOW_C = "\033[93m"
BLUE_C = "\033[94m"


def _col(c: str, t: str) -> str:
    return f"{c}{t}{RESET}"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _ColourFmt(logging.Formatter):
    _MAP = {
        logging.DEBUG: GREY_C,
        logging.WARNING: YELLOW_C,
        logging.ERROR: RED_C,
        logging.CRITICAL: RED_C + BOLD,
    }

    def format(self, r: logging.LogRecord) -> str:
        c = self._MAP.get(r.levelno, "")
        ts = self.formatTime(r, "%H:%M:%S")
        return f"{GREY_C}{ts}{RESET} {c}{r.getMessage()}{RESET}"


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
    idx: int  # 1-based device number
    name: str
    device: Device
    vdsd: Vdsd
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
    return DsUid.from_name_in_space(
        f"example-climate-{_RUN_ID}-{tag}", DsUidNamespace.VDC
    )


def _vdsd(device: Device, name: str, model: str) -> Vdsd:
    return Vdsd(
        device=device,
        primary_group=ColorGroup.BLUE,
        subdevice_index=0,
        name=name,
        model=model,
        model_version="1.0.0",
        vendor_name=VENDOR_NAME,
        vendor_guid=VENDOR_GUID,
        zone_id=0,
    )


def _output(
    vdsd: Vdsd,
    func: OutputFunction,
    active_group: int,
    groups: set[int],
    **kwargs,
) -> Output:
    out = Output(
        vdsd=vdsd,
        function=func,
        output_usage=OutputUsage.ROOM,
        name="output",
        default_group=active_group,
        active_group=active_group,
        groups=groups,
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
    async def cb(vdsd, name, value, group, zone_id):
        _notify(
            f"[{dev_name}] control value: {name}={value:.2f} (group={group}, zone={zone_id})"
        )

    return cb


# ===========================================================================
# Device builders — one function per device
# ===========================================================================


def build_c1_heating_valve(vdc: Vdc, idx: int) -> DevInfo:
    name = "Room Heating Valve"
    device = Device(vdc=vdc, dsuid=_dsuid("c1"))
    v = _vdsd(device, name, "ExampleClimate-C1")
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.HEATING),
        {int(ColorClass.HEATING)},
        heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        heating_system_type=HeatingSystemType.FLOOR_HEATING,
    )
    out.add_channel(OutputChannelType.HEATING_POWER)
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("heatinggroup")
    v.add_model_feature("pwmvalue")
    v.add_model_feature("valvetype")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c2_cooling_device(vdc: Vdc, idx: int) -> DevInfo:
    name = "Room Cooling Device"
    device = Device(vdc=vdc, dsuid=_dsuid("c2"))
    v = _vdsd(device, name, "ExampleClimate-C2")
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.COOLING),
        {int(ColorClass.COOLING)},
        heating_system_capability=HeatingSystemCapability.COOLING_ONLY,
        heating_system_type=HeatingSystemType.CONVECTOR_PASSIVE,
    )
    out.add_channel(OutputChannelType.COOLING_CAPACITY)
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("heatinggroup")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c3_room_ventilation(vdc: Vdc, idx: int) -> DevInfo:
    name = "Room Ventilation"
    device = Device(vdc=vdc, dsuid=_dsuid("c3"))
    v = _vdsd(device, name, "ExampleClimate-C3")
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.VENTILATION),
        {int(ColorClass.VENTILATION)},
    )
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY)
    out.add_channel(OutputChannelType.AIR_FLOW_DIRECTION)
    out.add_channel(OutputChannelType.AIR_LOUVER_POSITION)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("ventconfig")
    v.add_model_feature("identification")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c4_window_opener(vdc: Vdc, idx: int) -> DevInfo:
    name = "Window Opener"
    device = Device(vdc=vdc, dsuid=_dsuid("c4"))
    v = _vdsd(device, name, "ExampleClimate-C4")
    device.add_vdsd(v)

    # Windows use SHADE_POSITION_OUTSIDE channel; WINDOW group distinguishes them
    # from outdoor blinds in dSS scene handling.
    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.WINDOW),
        {int(ColorClass.WINDOW)},
    )
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c5_fcu(vdc: Vdc, idx: int) -> DevInfo:
    name = "Recirculation / FCU"
    device = Device(vdc=vdc, dsuid=_dsuid("c5"))
    v = _vdsd(device, name, "ExampleClimate-C5")
    device.add_vdsd(v)

    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.RECIRCULATION),
        {int(ColorClass.RECIRCULATION)},
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
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c6_apartment_ventilation(vdc: Vdc, idx: int) -> DevInfo:
    name = "Apartment Ventilation"
    device = Device(vdc=vdc, dsuid=_dsuid("c6"))
    v = _vdsd(device, name, "ExampleClimate-C6")
    device.add_vdsd(v)

    # APARTMENT_VENTILATION(64) is a global app group (>=64) — cannot appear in groups.
    # groups contains VENTILATION(10) for room-level scene participation.
    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.APARTMENT_VENTILATION),
        {int(ColorClass.VENTILATION)},
    )
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY, min_value=0, max_value=100)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("ventconfig")
    v.add_model_feature("apartmentapplication")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c7_apartment_recirculation(vdc: Vdc, idx: int) -> DevInfo:
    name = "Apartment Recirculation"
    device = Device(vdc=vdc, dsuid=_dsuid("c7"))
    v = _vdsd(device, name, "ExampleClimate-C7")
    device.add_vdsd(v)

    # APARTMENT_RECIRCULATION(69) is a global app group — cannot appear in groups.
    # groups contains RECIRCULATION(12) for zone-level scene participation.
    out = _output(
        v,
        OutputFunction.POSITIONAL,
        int(ColorClass.APARTMENT_RECIRCULATION),
        {int(ColorClass.RECIRCULATION)},
    )
    out.add_channel(OutputChannelType.AIR_FLOW_INTENSITY, min_value=0, max_value=100)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("ventconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_c8_temperature_controller(vdc: Vdc, idx: int) -> DevInfo:
    name = "Temperature Controller"
    device = Device(vdc=vdc, dsuid=_dsuid("c8"))
    v = _vdsd(device, name, "ExampleClimate-C8")
    device.add_vdsd(v)

    # INTERNALLY_CONTROLLED: output managed by dSS temperature control algorithm.
    # dSS sends heatingLevel (0-100%) via on_control_value callback.
    # TEMPERATURE_CONTROL(48) is < 64 so it CAN appear in groups set.
    out = _output(
        v,
        OutputFunction.INTERNALLY_CONTROLLED,
        int(ColorClass.TEMPERATURE_CONTROL),
        {int(ColorClass.TEMPERATURE_CONTROL)},
        heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        heating_system_type=HeatingSystemType.FLOOR_HEATING,
    )
    out.on_channel_applied = _channel_callback(name)
    v.on_control_value = _control_value_callback(name)

    v.add_model_feature("heatinggroup")
    v.add_model_feature("heatingprops")
    v.add_model_feature("temperatureoffset")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


# ===========================================================================
# Build all 8 devices
# ===========================================================================


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_c1_heating_valve,
        build_c2_cooling_device,
        build_c3_room_ventilation,
        build_c4_window_opener,
        build_c5_fcu,
        build_c6_apartment_ventilation,
        build_c7_apartment_recirculation,
        build_c8_temperature_controller,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic changes (~every 30–90 s)
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Randomly update one channel on one device every 30–90 s.

    C8 (INTERNALLY_CONTROLLED) has no channels and will be skipped naturally.
    """
    while True:
        await asyncio.sleep(random.uniform(30, 90))

        session = host.session
        if session is None or not session.is_active:
            continue

        candidates = [d for d in devices if d.output is not None]
        if not candidates:
            continue

        dev = random.choice(candidates)
        channels = list(dev.output.channels.values())  # public .channels property
        if not channels:
            continue

        ch = random.choice(channels)
        rng = ch.max_value - ch.min_value
        new_val = round(ch.min_value + random.uniform(0, rng), 1)
        try:
            await ch.update_value(new_val)
            _notify(f"[MOCK] [{dev.name}] {ch.name} → {new_val}")
        except Exception as exc:
            logging.getLogger("example_climate").debug("Mock error: %s", exc)


# ===========================================================================
# Initial value push — avoids "red error" on first open in configurator
# ===========================================================================


async def push_initial_output_values(devices: list[DevInfo]) -> None:
    """Push a safe initial value (min_value) for every output channel."""
    for di in devices:
        if di.output is None:
            continue
        for ch in di.output.channels.values():
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
    status = _col(GREEN_C, "CONNECTED") if connected else _col(RED_C, "WAITING…")
    print(f"\n{BOLD}{'=' * 64}{RESET}")
    print(f"  pydsvdcapi Example — Climate  |  {status}")
    print(f"  {GREY_C}C1=heating  C2=cooling  C3=ventilation  C4=window{RESET}")
    print(f"  {GREY_C}C5=FCU  C6=apt-vent  C7=apt-recirc  C8=temp-ctrl{RESET}")
    print(f"{BOLD}{'=' * 64}{RESET}")
    print(f"  {BOLD}r{RESET}  Restart (vanish → wait 20 s → reconnect)")
    print(f"  {BOLD}q{RESET}  Quit clean (vanish + delete persistence files)")
    print(f"  {BOLD}x{RESET}  Exit (keep persistence for restart test)")
    print(f"{BOLD}{'=' * 64}{RESET}")
    print("Option: ", end="", flush=True)


async def console_loop(
    host: VdcHost,
    devices: list[DevInfo],
    restart_event: asyncio.Event,
    quit_event: asyncio.Event,
    clean_event: asyncio.Event,
) -> None:
    while True:
        connected = host.session is not None and host.session.is_active
        _print_menu(devices, connected)

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
            msg = notif_wait.result()
            print(f"\n{BOLD}{BLUE_C}--- DSS NOTIFICATION ---{RESET}")
            print(f"  {msg}")
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    extra = await asyncio.wait_for(_notif_q.get(), timeout=remaining)
                    print(f"  {extra}")
                except asyncio.TimeoutError:
                    break
            print(f"{BOLD}{BLUE_C}--- Returning to menu ---{RESET}")
            continue

        if stdin_wait in done:
            cmd = stdin_wait.result().lower().strip()
        else:
            continue

        if cmd == "r":
            print(f"\n{YELLOW_C}Restart requested — vanishing devices…{RESET}")
            restart_event.set()
            quit_event.set()
            return

        elif cmd == "q":
            print(
                f"\n{YELLOW_C}Clean quit — vanishing and removing persistence…{RESET}"
            )
            clean_event.set()
            quit_event.set()
            return

        elif cmd == "x":
            print(f"\n{YELLOW_C}Exiting (keeping persistence)…{RESET}")
            quit_event.set()
            return

        else:
            print(f"Unknown command '{cmd}'. Use r / q / x.")


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
    """Run the example climate VDC. Returns True if restart is requested."""
    setup_logging(debug=debug)

    host = VdcHost(
        port=port,
        model="pydsvdcapi Example Climate",
        name="example-climate-host",
        vendor_name=VENDOR_NAME,
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-example-climate",
        name="Example Climate VDC",
        model="pydsvdcapi-example-climate",
        capabilities=VdcCapabilities(metering=False, identification=True),
    )
    host.add_vdc(vdc)

    devices = build_all_devices(vdc)
    print(f"\n{BOLD}Example Climate VDC — {len(devices)} devices built{RESET}")
    print(f"Listening on port {port}. Waiting for dSS/vdSM…  [run-id: {_RUN_ID}]")

    loop = asyncio.get_running_loop()
    _start_stdin_thread(loop)

    await host.start()

    connected = await wait_for_session(host, timeout=180.0)
    if not connected:
        print(f"{RED_C}No connection within 3 minutes — exiting.{RESET}")
        await host.stop()
        return False

    session = host.session
    print(f"{GREEN_C}Session established — setting initial output values…{RESET}")

    await push_initial_output_values(devices)

    print(f"{GREEN_C}Announcing {len(devices)} devices…{RESET}")
    for di in devices:
        await di.device.announce(session)

    print(f"{GREEN_C}All devices announced.{RESET}")

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
    with contextlib.suppress(asyncio.CancelledError):
        await console_task

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
        print(f"{YELLOW_C}Waiting 20 s before restart…{RESET}")
        await asyncio.sleep(20)
        return True

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    while True:
        try:
            should_restart = asyncio.run(main(port=args.port, debug=args.debug))
        except KeyboardInterrupt:
            print(f"\n{YELLOW_C}Interrupted.{RESET}")
            break
        if not should_restart:
            break
