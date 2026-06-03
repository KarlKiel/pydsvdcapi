#!/usr/bin/env python3
"""Example VDC — 4 yellow (LIGHTS) virtual devices.

Demonstrates the four main light configurations:
  L1  Simple Light       — ON_OFF,             outconfigswitch + impulseconfig
  L2  Dimmable Light     — DIMMER,             transt + dimtimeconfig
  L3  Dim+CT Light       — DIMMER_COLOR_TEMP,  outputchannels + transt + dimtimeconfig
  L4  Full-Color RGBW    — FULL_COLOR_DIMMER,  outputchannels + identification

Console commands (press Enter after typing):
  r       restart: vanish all → wait 20 s → reconnect (tests persistence)
  q       quit cleanly: vanish, stop, delete persistence files
  x       exit without cleanup (keeps persistence for next run)

Channel values change automatically every 30–90 s (mocked).

Usage:
    python examples/example_lights.py [--port PORT] [--debug]
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
    OutputMode,
    OutputUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8341
STATE_FILE = Path("/tmp/pydsvdcapi_example_lights.yaml")

VENDOR_NAME = "pydsvdcapi Examples"
VENDOR_GUID = "gs1:(01)0000000000001"

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
GREY_C = "\033[90m"
RED_C = "\033[91m"
GREEN_C = "\033[92m"
YELLOW_C = "\033[93m"


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
    return DsUid.from_name_in_space(f"example-lights-{tag}", DsUidNamespace.VDC)


def _vdsd(device: Device, name: str, model: str) -> Vdsd:
    return Vdsd(
        device=device,
        primary_group=ColorGroup.YELLOW,
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
    mode: OutputMode | None = None,
    variable_ramp: bool = False,
) -> Output:
    out = Output(
        vdsd=vdsd,
        function=func,
        output_usage=OutputUsage.ROOM,
        name="output",
        default_group=int(ColorClass.LIGHTS),
        active_group=int(ColorClass.LIGHTS),
        groups={int(ColorClass.LIGHTS)},
        mode=mode,
        push_changes=True,
        variable_ramp=variable_ramp,
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


# ===========================================================================
# Device builders — one function per device
# ===========================================================================


def build_l1_simple_light(vdc: Vdc, idx: int) -> DevInfo:
    name = "Simple Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l1"))
    v = _vdsd(device, name, "ExampleLights-L1")
    device.add_vdsd(v)

    out = _output(v, OutputFunction.ON_OFF)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("outconfigswitch")  # "switch on above X%" threshold
    v.add_model_feature("impulseconfig")  # Impulse tab for binary-output pulse
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l2_dimmable_light(vdc: Vdc, idx: int) -> DevInfo:
    name = "Dimmable Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l2"))
    v = _vdsd(device, name, "ExampleLights-L2")
    device.add_vdsd(v)

    out = _output(v, OutputFunction.DIMMER, mode=OutputMode.GRADUAL, variable_ramp=True)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l3_dim_ct_light(vdc: Vdc, idx: int) -> DevInfo:
    name = "Dim+CT Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l3"))
    v = _vdsd(device, name, "ExampleLights-L3")
    device.add_vdsd(v)

    out = _output(
        v, OutputFunction.DIMMER_COLOR_TEMP, mode=OutputMode.GRADUAL, variable_ramp=True
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.add_model_feature("outputchannels")  # required so dSS shows CT slider
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l4_full_color_rgbw(vdc: Vdc, idx: int) -> DevInfo:
    name = "Full-Color RGBW"
    device = Device(vdc=vdc, dsuid=_dsuid("l4"))
    v = _vdsd(device, name, "ExampleLights-L4")
    device.add_vdsd(v)

    out = _output(
        v, OutputFunction.FULL_COLOR_DIMMER, mode=OutputMode.GRADUAL, variable_ramp=True
    )
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.add_model_feature("outputchannels")  # required for independent channel controls
    v.add_model_feature("identification")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


# ===========================================================================
# Build all 4 devices
# ===========================================================================


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_l1_simple_light,
        build_l2_dimmable_light,
        build_l3_dim_ct_light,
        build_l4_full_color_rgbw,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic changes (~every 30–90 s)
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Randomly update one channel on one device every 30–90 s."""
    while True:
        await asyncio.sleep(random.uniform(30, 90))

        session = host.session
        if session is None or not session.is_active:
            continue

        candidates = [d for d in devices if d.output is not None]
        if not candidates:
            continue

        dev = random.choice(candidates)
        channels = list(dev.output.channels.values())
        if not channels:
            continue

        ch = random.choice(channels)
        rng = ch.max_value - ch.min_value
        new_val = round(ch.min_value + random.uniform(0, rng), 1)
        try:
            await ch.update_value(new_val)
            _notify(f"[MOCK] [{dev.name}] {ch.name} → {new_val}")
        except Exception as exc:
            logging.getLogger("example_lights").debug("Mock error: %s", exc)


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
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"  pyDSvDCAPI Example Lights VDC  |  {status}")
    print(f"  {GREY_C}{len(devices)} devices announced{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")
    print(f"  {BOLD}r{RESET}  Restart (vanish → wait 20 s → reconnect)")
    print(f"  {BOLD}q{RESET}  Quit clean (vanish + delete persistence files)")
    print(f"  {BOLD}x{RESET}  Exit (keep persistence for restart test)")
    print(f"{BOLD}{'=' * 60}{RESET}")
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
            print(f"\n{BOLD}{YELLOW_C}--- DSS NOTIFICATION ---{RESET}")
            print(f"  {msg}")
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    extra = await asyncio.wait_for(_notif_q.get(), timeout=remaining)
                    print(f"  {extra}")
                except asyncio.TimeoutError:
                    break
            print(f"{BOLD}{YELLOW_C}--- Returning to menu ---{RESET}")
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
            print(f"\n{YELLOW_C}Clean quit — vanishing and removing persistence…{RESET}")
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
    """Run the example lights VDC. Returns True if restart is requested."""
    setup_logging(debug=debug)

    host = VdcHost(
        port=port,
        model="pyDSvDCAPI Example Lights",
        name="example-lights-host",
        vendor_name=VENDOR_NAME,
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-example-lights",
        name="Example Lights VDC",
        model="pydsvdcapi-example-lights",
        capabilities=VdcCapabilities(metering=False, identification=True),
    )
    host.add_vdc(vdc)

    devices = build_all_devices(vdc)
    print(f"\n{BOLD}Example Lights VDC — {len(devices)} devices built{RESET}")
    print(f"Listening on port {port}. Waiting for dSS/vdSM…")

    loop = asyncio.get_running_loop()
    _start_stdin_thread(loop)

    await host.start()

    connected = await wait_for_session(host, timeout=180.0)
    if not connected:
        print(f"{RED_C}No connection within 3 minutes — exiting.{RESET}")
        await host.stop()
        return False

    session = host.session
    print(f"{GREEN_C}Session established — announcing {len(devices)} devices…{RESET}")

    for di in devices:
        await di.device.announce(session)

    print(f"{GREEN_C}All devices announced.{RESET}")

    await push_initial_output_values(devices)
    print(f"{GREEN_C}Initial output values pushed.{RESET}")

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
