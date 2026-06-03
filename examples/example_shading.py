#!/usr/bin/env python3
"""Example VDC — 4 grey (BLINDS/AWNINGS) shading virtual devices.

Demonstrates four main shading configurations:
  S1  Curtain            — SHADE_POSITION_INDOOR,                         shadeposition
  S2  Awning             — SHADE_POSITION_OUTSIDE,   AWNINGS(65) group,   shadeposition + locationconfig + windprotectionconfigawning
  S3  Indoor Blinds      — SHADE_POSITION_INDOOR + SHADE_OPENING_ANGLE_INDOOR,   shadeposition + shadebladeang
  S4  Outdoor Shutter    — SHADE_POSITION_OUTSIDE + SHADE_OPENING_ANGLE_OUTSIDE, shadeposition + shadebladeang + locationconfig + windprotectionconfigblind

Console commands (press Enter after typing):
  r       restart: vanish all → wait 20 s → reconnect (tests persistence)
  q       quit cleanly: vanish, stop, delete persistence files
  x       exit without cleanup (keeps persistence for next run)

Channel values change automatically every 30–90 s (mocked).
Outdoor devices (S2, S4) have a 20 % chance to simulate wind-protection retract.

Usage:
    python examples/example_shading.py [--port PORT] [--debug]
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
    OutputUsage,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8342
STATE_FILE = Path("/tmp/pydsvdcapi_example_shading.yaml")

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
    outdoor: bool = False


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
    return DsUid.from_name_in_space(f"example-shading-v2-{tag}", DsUidNamespace.VDC)


def _vdsd(device: Device, name: str, model: str) -> Vdsd:
    return Vdsd(
        device=device,
        primary_group=ColorGroup.GREY,
        subdevice_index=0,
        name=name,
        model=model,
        model_version="1.0.0",
        vendor_name=VENDOR_NAME,
        vendor_guid=VENDOR_GUID,
        zone_id=0,
    )


def _shade_output(vdsd: Vdsd, active_group: int, groups: set[int]) -> Output:
    out = Output(
        vdsd=vdsd,
        function=OutputFunction.POSITIONAL,
        output_usage=OutputUsage.ROOM,
        name="output",
        default_group=int(ColorClass.BLINDS),
        active_group=active_group,
        groups=groups,
        push_changes=True,
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


def build_s1_curtain(vdc: Vdc, idx: int) -> DevInfo:
    name = "Curtain"
    device = Device(vdc=vdc, dsuid=_dsuid("s1"))
    v = _vdsd(device, name, "ExampleShading-S1")
    device.add_vdsd(v)

    out = _shade_output(v, int(ColorClass.BLINDS), {int(ColorClass.BLINDS)})
    out.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_s2_awning(vdc: Vdc, idx: int) -> DevInfo:
    name = "Awning"
    device = Device(vdc=vdc, dsuid=_dsuid("s2"))
    v = _vdsd(device, name, "ExampleShading-S2")
    device.add_vdsd(v)

    # AWNINGS(65) is a global app group (>=64) — cannot appear in groups set.
    # groups must contain BLINDS(2) so device participates in shade scenes.
    out = _shade_output(v, int(ColorClass.AWNINGS), {int(ColorClass.BLINDS)})
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("locationconfig")
    v.add_model_feature("windprotectionconfigawning")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out, outdoor=True)


def build_s3_indoor_blinds(vdc: Vdc, idx: int) -> DevInfo:
    name = "Indoor Blinds"
    device = Device(vdc=vdc, dsuid=_dsuid("s3"))
    v = _vdsd(device, name, "ExampleShading-S3")
    device.add_vdsd(v)

    out = _shade_output(v, int(ColorClass.BLINDS), {int(ColorClass.BLINDS)})
    out.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
    out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_INDOOR)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("shadebladeang")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_s4_outdoor_shutter(vdc: Vdc, idx: int) -> DevInfo:
    name = "Outdoor Shutter"
    device = Device(vdc=vdc, dsuid=_dsuid("s4"))
    v = _vdsd(device, name, "ExampleShading-S4")
    device.add_vdsd(v)

    out = _shade_output(v, int(ColorClass.BLINDS), {int(ColorClass.BLINDS)})
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("shadebladeang")
    v.add_model_feature("locationconfig")
    v.add_model_feature("windprotectionconfigblind")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out, outdoor=True)


# ===========================================================================
# Build all 4 devices
# ===========================================================================


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_s1_curtain,
        build_s2_awning,
        build_s3_indoor_blinds,
        build_s4_outdoor_shutter,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic changes (~every 30–90 s)
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Randomly update one channel on one device every 30–90 s.

    Outdoor devices have a 20 % chance to simulate wind-protection retract.
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
        channels = list(dev.output.channels.values())
        if not channels:
            continue

        try:
            # 20 % chance outdoor devices simulate wind-protection retract
            if dev.outdoor and random.random() < 0.2:
                pos_ch = channels[0]  # primary position channel
                await pos_ch.update_value(pos_ch.min_value)
                _notify(
                    f"[MOCK] [{dev.name}] wind protection — retracted to {pos_ch.min_value}"
                )
            else:
                ch = random.choice(channels)
                rng = ch.max_value - ch.min_value
                new_val = round(ch.min_value + random.uniform(0, rng), 1)
                await ch.update_value(new_val)
                _notify(f"[MOCK] [{dev.name}] {ch.name} → {new_val}")
        except Exception as exc:
            logging.getLogger("example_shading").debug("Mock error: %s", exc)


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
    print(f"  pydsvdcapi Example — Shading  |  {status}")
    print(f"  {GREY_C}{len(devices)} devices  (S1=curtain  S2=awning  S3=indoor-blind  S4=shutter){RESET}")
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
    """Run the example shading VDC. Returns True if restart is requested."""
    setup_logging(debug=debug)

    host = VdcHost(
        port=port,
        model="pydsvdcapi Example Shading",
        name="example-shading-host",
        vendor_name=VENDOR_NAME,
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-example-shading",
        name="Example Shading VDC",
        model="pydsvdcapi-example-shading",
        capabilities=VdcCapabilities(metering=False, identification=True),
    )
    host.add_vdc(vdc)

    devices = build_all_devices(vdc)
    print(f"\n{BOLD}Example Shading VDC — {len(devices)} devices built{RESET}")
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
