# Light, Shading & Climate Example Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create three self-contained example scripts (`example_lights.py`, `example_shading.py`, `example_climate.py`) that each demonstrate a realistic family of pydsvdcapi VDC devices with mocked hardware behavior, a console menu for clean teardown, and restart support.

**Architecture:** Each script follows the `full_showcase.py` skeleton exactly — module docstring, ANSI helpers, `DevInfo` dataclass, notification queue, device-builder functions, a mock-changes background task, a console loop with `r/q/x` commands, and a `main()` that runs the host with an outer restart loop. Device builders are verbatim copies of the patterns already proven in full_showcase.py for the same device types.

**Tech Stack:** Python 3.11+, asyncio, pydsvdcapi; `argparse` for CLI; `threading` for stdin; `ruff` for lint.

---

## Shared Skeleton (reference — do NOT create a separate file)

Every script reuses this identical structure:

```
module docstring
imports
ANSI constants + _col()
DEFAULT_PORT / STATE_FILE / VENDOR_NAME / VENDOR_GUID
_ColourFmt / setup_logging()
DevInfo dataclass
_notif_q + _notify()
_dsuid() / _vdsd() / _output() helpers
_channel_callback()   # prints received output commands
mock_changes_loop()   # randomly updates channels every 30–90 s
push_initial_output_values()
_stdin_q + _start_stdin_thread()
_print_menu() / console_loop()   # r=restart q=clean-quit x=exit
wait_for_session()
main()
__main__ with while-True restart loop
```

The `mock_changes_loop` for output-only examples proactively calls
`ch.update_value(new_val)` on a random channel of a random device every
30–90 s, simulating the hardware reporting its current state back.

---

## Task 1: `examples/example_lights.py`

Four yellow (LIGHTS) devices:

| # | Name | Function | Channels | Key model features |
|---|------|----------|----------|--------------------|
| L1 | Simple Light | ON_OFF | brightness (auto) | `outconfigswitch`, `impulseconfig`, `outvalue8` |
| L2 | Dimmable Light | DIMMER | brightness (auto) | `transt`, `dimtimeconfig`, `outvalue8` |
| L3 | Dim+CT Light | DIMMER_COLOR_TEMP | brightness + colortemp (auto) | `outputchannels`, `transt`, `dimtimeconfig`, `outvalue8` |
| L4 | Full-Color RGBW | FULL_COLOR_DIMMER | 6 channels (auto) | `outputchannels`, `transt`, `dimtimeconfig`, `outvalue8` |

**Files:**
- Create: `examples/example_lights.py`

- [ ] **Step 1: Write `examples/example_lights.py`**

```python
#!/usr/bin/env python3
"""pydsvdcapi example — yellow light devices.

Four virtual lights demonstrating the progression from simple on/off
to full RGBW colour control.

Devices
-------
  L1  Simple Light       — ON/OFF brightness, switch-on threshold
  L2  Dimmable Light     — single BRIGHTNESS channel, gradual dimming
  L3  Dim+CT Light       — BRIGHTNESS + COLOR_TEMPERATURE (tunable white)
  L4  Full-Color RGBW    — 6 channels: brightness, colortemp, hue,
                            saturation, cieX, cieY

Console commands (press Enter after typing)
-------------------------------------------
  r   restart: vanish all → wait 20 s → reconnect
  q   quit cleanly: vanish + delete persistence files
  x   exit without cleanup (keep persistence for next run)

Mock behavior
-------------
  Every 30–90 s a random channel on a random device is updated to a
  random value in its valid range, simulating hardware state feedback.

Usage
-----
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
from dataclasses import dataclass, field
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
    idx: int
    name: str
    device: Device
    vdsd: Vdsd
    output: Output | None = None


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------

_notif_q: asyncio.Queue = asyncio.Queue()


def _notify(msg: str) -> None:
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
# Device builders
# ===========================================================================


def build_l1_simple_light(vdc: Vdc, idx: int) -> DevInfo:
    """ON/OFF light with switch-on threshold (single brightness channel)."""
    name = "Simple Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l1"))
    v = _vdsd(device, name, "ExampleLights-L1")
    device.add_vdsd(v)

    # ON_OFF: single brightness channel auto-created; mode auto-derives to BINARY.
    # outconfigswitch → "switch on above X%" threshold slider in Advanced Settings.
    # impulseconfig   → "Impulse" tab for binary-output pulse behaviour.
    out = _output(v, OutputFunction.ON_OFF)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("outconfigswitch")
    v.add_model_feature("impulseconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l2_dimmable_light(vdc: Vdc, idx: int) -> DevInfo:
    """Dimmable light — single brightness channel with gradual dimming."""
    name = "Dimmable Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l2"))
    v = _vdsd(device, name, "ExampleLights-L2")
    device.add_vdsd(v)

    # DIMMER + GRADUAL: brightness channel 0–100 %; smooth ramp support.
    # variable_ramp=True tells dSS this device supports software transition time.
    out = _output(v, OutputFunction.DIMMER, mode=OutputMode.GRADUAL, variable_ramp=True)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l3_dim_ct_light(vdc: Vdc, idx: int) -> DevInfo:
    """Tunable-white light — brightness + colour temperature channels."""
    name = "Dim+CT Light"
    device = Device(vdc=vdc, dsuid=_dsuid("l3"))
    v = _vdsd(device, name, "ExampleLights-L3")
    device.add_vdsd(v)

    # DIMMER_COLOR_TEMP: auto-creates brightness (dsIndex=0) + colortemp (dsIndex=1).
    # outputchannels is required so dSS shows the CT slider alongside brightness.
    out = _output(v, OutputFunction.DIMMER_COLOR_TEMP, mode=OutputMode.GRADUAL, variable_ramp=True)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.add_model_feature("outputchannels")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_l4_full_color_rgbw(vdc: Vdc, idx: int) -> DevInfo:
    """Full-colour RGBW light — 6 channels: brightness, colortemp, hue, saturation, cieX, cieY."""
    name = "Full-Color RGBW"
    device = Device(vdc=vdc, dsuid=_dsuid("l4"))
    v = _vdsd(device, name, "ExampleLights-L4")
    device.add_vdsd(v)

    # FULL_COLOR_DIMMER: auto-creates all 6 light channels.
    # outputchannels is required for dSS to show independent channel controls.
    out = _output(v, OutputFunction.FULL_COLOR_DIMMER, mode=OutputMode.GRADUAL, variable_ramp=True)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("outvalue8")
    v.add_model_feature("transt")
    v.add_model_feature("dimtimeconfig")
    v.add_model_feature("outputchannels")
    v.add_model_feature("identification")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out)


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_l1_simple_light,
        build_l2_dimmable_light,
        build_l3_dim_ct_light,
        build_l4_full_color_rgbw,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic channel updates
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Every 30–90 s push a random channel value on a random device."""
    while True:
        await asyncio.sleep(random.uniform(30, 90))

        session = host.session
        if session is None or not session.is_active:
            continue

        candidates = [d for d in devices if d.output is not None]
        if not candidates:
            continue
        dev = random.choice(candidates)
        channels = list(dev.output._channels.values())
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
# Initial value push
# ===========================================================================


async def push_initial_output_values(devices: list[DevInfo]) -> None:
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
    status = _col(GREEN_C, "CONNECTED") if connected else _col(RED_C, "WAITING…")
    print(f"\n{BOLD}{'=' * 55}{RESET}")
    print(f"  pydsvdcapi Example — Lights  |  {status}")
    print(f"  {GREY_C}{len(devices)} devices  (L1=on/off  L2=dimmer  L3=dim+CT  L4=RGBW){RESET}")
    print(f"{BOLD}{'=' * 55}{RESET}")
    print(f"  {BOLD}r{RESET}  Restart (vanish → wait 20 s → reconnect)")
    print(f"  {BOLD}q{RESET}  Quit clean (vanish + delete persistence files)")
    print(f"  {BOLD}x{RESET}  Exit (keep persistence for restart test)")
    print(f"{BOLD}{'=' * 55}{RESET}")
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
            {stdin_wait, notif_wait}, return_when=asyncio.FIRST_COMPLETED
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

        if stdin_wait not in done:
            continue
        cmd = stdin_wait.result().lower().strip()

        if cmd == "r":
            print(f"\n{YELLOW_C}Restart requested — vanishing devices…{RESET}")
            restart_event.set()
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
    """Run the lights example VDC. Returns True if restart is requested."""
    setup_logging(debug=debug)

    host = VdcHost(
        port=port,
        model="pydsvdcapi Example Lights",
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
    print(f"\n{BOLD}pydsvdcapi Example — Lights — {len(devices)} devices built{RESET}")
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
```

- [ ] **Step 2: Syntax and lint check**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m py_compile examples/example_lights.py && echo "OK"
python -m ruff check examples/example_lights.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add examples/example_lights.py
git commit -m "feat: add example_lights.py — 4 yellow light devices (on/off, dimmer, dim+CT, RGBW)"
```

---

## Task 2: `examples/example_shading.py`

Four grey (BLINDS/AWNINGS) devices:

| # | Name | Channel(s) | Active group | Key model features |
|---|------|------------|-------------|--------------------|
| S1 | Curtain | SHADE_POSITION_INDOOR | BLINDS | `shadeposition` |
| S2 | Awning | SHADE_POSITION_OUTSIDE | AWNINGS (groups=BLINDS) | `shadeposition`, `locationconfig`, `windprotectionconfigawning` |
| S3 | Indoor Blinds | SHADE_POSITION_INDOOR + SHADE_OPENING_ANGLE_INDOOR | BLINDS | `shadeposition`, `shadebladeang` |
| S4 | Outdoor Shutter | SHADE_POSITION_OUTSIDE + SHADE_OPENING_ANGLE_OUTSIDE | BLINDS | `shadeposition`, `shadebladeang`, `locationconfig`, `windprotectionconfigblind` |

**Key notes:**
- Awning uses `active_group=AWNINGS(65)` (global app group, NOT in groups set) + `groups={BLINDS(2)}`
- All others use `active_group=BLINDS(2)` with `groups={BLINDS(2)}`
- Shade resolution is 16-bit (0–65535) for outside channels; `add_channel()` sets the correct default
- Mock simulates wind-protection auto-close on S2 (awning) and S4 (outdoor shutter): every ~60 s there is a 20 % chance the position is pushed to 0 (fully retracted)

**Files:**
- Create: `examples/example_shading.py`

- [ ] **Step 1: Write `examples/example_shading.py`**

```python
#!/usr/bin/env python3
"""pydsvdcapi example — grey shading devices.

Four virtual shade/blind devices covering indoor and outdoor configurations.

Devices
-------
  S1  Curtain           — indoor, single SHADE_POSITION_INDOOR channel
  S2  Awning            — outdoor, single SHADE_POSITION_OUTSIDE, wind protection
  S3  Indoor Blinds     — indoor, SHADE_POSITION_INDOOR + SHADE_OPENING_ANGLE_INDOOR
  S4  Outdoor Shutter   — outdoor, SHADE_POSITION_OUTSIDE + SHADE_OPENING_ANGLE_OUTSIDE,
                          wind protection

Console commands
----------------
  r   restart: vanish all → wait 20 s → reconnect
  q   quit cleanly: vanish + delete persistence files
  x   exit without cleanup

Mock behavior
-------------
  Every 30–90 s a random shade position is updated to simulate motor
  movement feedback.  Outdoor devices (S2, S4) also occasionally
  simulate a wind-protection event that retracts the cover to 0 %.

Usage
-----
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
    idx: int
    name: str
    device: Device
    vdsd: Vdsd
    output: Output | None = None
    outdoor: bool = False  # True → mock may trigger wind-protection retract


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------

_notif_q: asyncio.Queue = asyncio.Queue()


def _notify(msg: str) -> None:
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
    return DsUid.from_name_in_space(f"example-shading-{tag}", DsUidNamespace.VDC)


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


def _shade_output(
    vdsd: Vdsd,
    active_group: int,
    groups: set[int],
) -> Output:
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
# Device builders
# ===========================================================================


def build_s1_curtain(vdc: Vdc, idx: int) -> DevInfo:
    """Indoor curtain — single indoor position channel."""
    name = "Curtain"
    device = Device(vdc=vdc, dsuid=_dsuid("s1"))
    v = _vdsd(device, name, "ExampleShading-S1")
    device.add_vdsd(v)

    out = _shade_output(v, int(ColorClass.BLINDS), {int(ColorClass.BLINDS)})
    # SHADE_POSITION_INDOOR: indoor use, 16-bit resolution (0–65535 maps to 0–100 %)
    out.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out, outdoor=False)


def build_s2_awning(vdc: Vdc, idx: int) -> DevInfo:
    """Outdoor awning — single outdoor position channel with wind protection."""
    name = "Awning"
    device = Device(vdc=vdc, dsuid=_dsuid("s2"))
    v = _vdsd(device, name, "ExampleShading-S2")
    device.add_vdsd(v)

    # AWNINGS(65) is a global app group (≥64) — cannot appear in groups set.
    # groups must contain BLINDS(2) so the device participates in shade scenes.
    out = _shade_output(
        v,
        int(ColorClass.AWNINGS),
        {int(ColorClass.BLINDS)},
    )
    out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
    out.on_channel_applied = _channel_callback(name)

    v.add_model_feature("shadeposition")
    v.add_model_feature("locationconfig")
    v.add_model_feature("windprotectionconfigawning")
    v.derive_model_features()
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out, outdoor=True)


def build_s3_indoor_blinds(vdc: Vdc, idx: int) -> DevInfo:
    """Indoor venetian blinds — position + tilt angle channels."""
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
    return DevInfo(idx=idx, name=name, device=device, vdsd=v, output=out, outdoor=False)


def build_s4_outdoor_shutter(vdc: Vdc, idx: int) -> DevInfo:
    """Outdoor roller shutter with slat — position + tilt, wind protection."""
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


def build_all_devices(vdc: Vdc) -> list[DevInfo]:
    builders = [
        build_s1_curtain,
        build_s2_awning,
        build_s3_indoor_blinds,
        build_s4_outdoor_shutter,
    ]
    return [fn(vdc, i + 1) for i, fn in enumerate(builders)]


# ===========================================================================
# Mock periodic channel updates
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Every 30–90 s update shade positions; outdoor devices may also trigger
    a simulated wind-protection retract (position → 0)."""
    while True:
        await asyncio.sleep(random.uniform(30, 90))

        session = host.session
        if session is None or not session.is_active:
            continue

        candidates = [d for d in devices if d.output is not None]
        if not candidates:
            continue
        dev = random.choice(candidates)
        channels = list(dev.output._channels.values())
        if not channels:
            continue

        try:
            # 20 % chance outdoor devices simulate a wind-protection retract
            if dev.outdoor and random.random() < 0.2:
                pos_ch = channels[0]  # primary position channel
                await pos_ch.update_value(pos_ch.min_value)
                _notify(f"[MOCK] [{dev.name}] wind protection — retracted to {pos_ch.min_value}")
            else:
                ch = random.choice(channels)
                rng = ch.max_value - ch.min_value
                new_val = round(ch.min_value + random.uniform(0, rng), 1)
                await ch.update_value(new_val)
                _notify(f"[MOCK] [{dev.name}] {ch.name} → {new_val}")
        except Exception as exc:
            logging.getLogger("example_shading").debug("Mock error: %s", exc)


# ===========================================================================
# Initial value push
# ===========================================================================


async def push_initial_output_values(devices: list[DevInfo]) -> None:
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
    status = _col(GREEN_C, "CONNECTED") if connected else _col(RED_C, "WAITING…")
    print(f"\n{BOLD}{'=' * 58}{RESET}")
    print(f"  pydsvdcapi Example — Shading  |  {status}")
    print(f"  {GREY_C}{len(devices)} devices  (S1=curtain  S2=awning  S3=indoor-blind  S4=shutter){RESET}")
    print(f"{BOLD}{'=' * 58}{RESET}")
    print(f"  {BOLD}r{RESET}  Restart (vanish → wait 20 s → reconnect)")
    print(f"  {BOLD}q{RESET}  Quit clean (vanish + delete persistence files)")
    print(f"  {BOLD}x{RESET}  Exit (keep persistence for restart test)")
    print(f"{BOLD}{'=' * 58}{RESET}")
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
            {stdin_wait, notif_wait}, return_when=asyncio.FIRST_COMPLETED
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

        if stdin_wait not in done:
            continue
        cmd = stdin_wait.result().lower().strip()

        if cmd == "r":
            print(f"\n{YELLOW_C}Restart requested — vanishing devices…{RESET}")
            restart_event.set()
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
    print(f"\n{BOLD}pydsvdcapi Example — Shading — {len(devices)} devices built{RESET}")
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
```

- [ ] **Step 2: Syntax and lint check**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m py_compile examples/example_shading.py && echo "OK"
python -m ruff check examples/example_shading.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add examples/example_shading.py
git commit -m "feat: add example_shading.py — 4 grey shade devices (curtain, awning, indoor blinds, shutter)"
```

---

## Task 3: `examples/example_climate.py`

Eight blue (BLUE) climate devices:

| # | Name | Active group | Function | Channel(s) | Key model features |
|---|------|-------------|----------|------------|--------------------|
| C1 | Room Heating Valve | HEATING (3) | POSITIONAL | HEATING_POWER | `heatinggroup`, `pwmvalue`, `valvetype` |
| C2 | Room Cooling Device | COOLING (9) | POSITIONAL | COOLING_CAPACITY | `heatinggroup` |
| C3 | Room Ventilation | VENTILATION (10) | POSITIONAL | AIR_FLOW_INTENSITY, AIR_FLOW_DIRECTION, AIR_LOUVER_POSITION | `ventconfig` |
| C4 | Window Opener | WINDOW (11) | POSITIONAL | SHADE_POSITION_OUTSIDE | `shadeposition` |
| C5 | Recirculation / FCU | RECIRCULATION (12) | POSITIONAL | HEATING_POWER, COOLING_CAPACITY, AIR_FLOW_INTENSITY, AIR_LOUVER_POSITION | `heatinggroup`, `heatingprops`, `fcu`, `ventconfig` |
| C6 | Apartment Ventilation | APARTMENT_VENTILATION (64) | POSITIONAL | AIR_FLOW_INTENSITY | `ventconfig`, `apartmentapplication` |
| C7 | Apartment Recirculation | APARTMENT_RECIRCULATION (69) | POSITIONAL | AIR_FLOW_INTENSITY | `ventconfig` |
| C8 | Temperature Controller | TEMPERATURE_CONTROL (48) | INTERNALLY_CONTROLLED | (none — dSS-managed) | `heatinggroup`, `heatingprops`, `temperatureoffset` |

**Key notes on groups:**
- C6: `active_group=APARTMENT_VENTILATION(64)`, `groups={VENTILATION(10)}` — global group cannot go in groups set
- C7: `active_group=APARTMENT_RECIRCULATION(69)`, `groups={RECIRCULATION(12)}`
- C8: `active_group=TEMPERATURE_CONTROL(48)`, `groups={TEMPERATURE_CONTROL(48)}` — 48 < 64, valid in groups
- C1 uses `HeatingSystemCapability.HEATING_ONLY` + `HeatingSystemType.FLOOR_HEATING` (switchable to other types)
- C2 uses `HeatingSystemCapability.COOLING_ONLY`
- C5 uses `HeatingSystemCapability.HEATING_AND_COOLING` + `HeatingSystemType.CONVECTOR_ACTIVE`
- C8 uses `OutputFunction.INTERNALLY_CONTROLLED` — dSS temperature control sends `heatingLevel` (0–100 %) via `on_control_value`

Mock behavior:
- C1, C2, C5: periodically simulate output channel value changes (valve position, capacity)
- C3, C6, C7: periodically simulate fan-speed fluctuations
- C4: periodically simulate window position change (0 = closed, 100 = fully open)
- C8: receives `heatingLevel` via callback; mock prints received values

**Files:**
- Create: `examples/example_climate.py`

- [ ] **Step 1: Write `examples/example_climate.py`**

```python
#!/usr/bin/env python3
"""pydsvdcapi example — blue climate devices.

Eight virtual climate devices covering the full range of dS blue-group
sub-types: heating, cooling, ventilation, window, FCU, apartment
ventilation, apartment recirculation, and temperature control.

Devices
-------
  C1  Room Heating Valve        — HEATING_POWER channel (valve 0–100 %)
  C2  Room Cooling Device       — COOLING_CAPACITY channel
  C3  Room Ventilation          — AIR_FLOW_INTENSITY + direction + louver
  C4  Window Opener/Closer      — SHADE_POSITION_OUTSIDE (0=closed 100=open)
  C5  Recirculation / FCU       — heating + cooling + airflow + louver
  C6  Apartment Ventilation     — AIR_FLOW_INTENSITY (apartment-wide fan)
  C7  Apartment Recirculation   — AIR_FLOW_INTENSITY (apartment-wide recirc)
  C8  Temperature Controller    — INTERNALLY_CONTROLLED; receives heatingLevel
                                  (0–100 %) via dSS temperature control

Console commands
----------------
  r   restart: vanish all → wait 20 s → reconnect
  q   quit cleanly: vanish + delete persistence files
  x   exit without cleanup

Mock behavior
-------------
  Every 30–90 s a random channel value is updated on a random device,
  simulating hardware state feedback to dSS.

Usage
-----
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
    idx: int
    name: str
    device: Device
    vdsd: Vdsd
    output: Output | None = None


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------

_notif_q: asyncio.Queue = asyncio.Queue()


def _notify(msg: str) -> None:
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
    return DsUid.from_name_in_space(f"example-climate-{tag}", DsUidNamespace.VDC)


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
    async def cb(vdsd: Vdsd, name: str, value: float, group, zone_id) -> None:
        _notify(
            f"[{dev_name}] control value: {name}={value:.2f} (group={group}, zone={zone_id})"
        )
    return cb


# ===========================================================================
# Device builders
# ===========================================================================


def build_c1_heating_valve(vdc: Vdc, idx: int) -> DevInfo:
    """Room heating valve — HEATING_POWER channel (0–100 %, floor heating)."""
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
    """Room cooling device — COOLING_CAPACITY channel (0–100 %)."""
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
    """Room ventilation unit — fan speed, direction and louver channels."""
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
    """Electrical window opener/closer — position channel (0=closed, 100=fully open)."""
    name = "Window Opener"
    device = Device(vdc=vdc, dsuid=_dsuid("c4"))
    v = _vdsd(device, name, "ExampleClimate-C4")
    device.add_vdsd(v)

    # Windows use SHADE_POSITION_OUTSIDE channel; WINDOW group distinguishes
    # them from outdoor blinds in dSS scene handling.
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
    """Recirculation fan-coil unit — heating + cooling + airflow + louver."""
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
    """Apartment-wide ventilation — fan speed only, global app group 64."""
    name = "Apartment Ventilation"
    device = Device(vdc=vdc, dsuid=_dsuid("c6"))
    v = _vdsd(device, name, "ExampleClimate-C6")
    device.add_vdsd(v)

    # APARTMENT_VENTILATION(64) is a global app group — cannot appear in groups.
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
    """Apartment-wide recirculation — fan speed only, global app group 69."""
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
    """Single-room temperature controller.

    Uses INTERNALLY_CONTROLLED output — dSS temperature control sends the
    computed heatingLevel (0–100 %) as a control value via on_control_value.
    The device translates this to a physical actuator command (e.g. setpoint
    to a thermostat over Modbus or KNX).

    TEMPERATURE_CONTROL(48) is a valid groups member (< 64).
    """
    name = "Temperature Controller"
    device = Device(vdc=vdc, dsuid=_dsuid("c8"))
    v = _vdsd(device, name, "ExampleClimate-C8")
    device.add_vdsd(v)

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
# Mock periodic channel updates
# ===========================================================================


async def mock_changes_loop(devices: list[DevInfo], host: VdcHost) -> None:
    """Every 30–90 s push a random channel value on a random device."""
    while True:
        await asyncio.sleep(random.uniform(30, 90))

        session = host.session
        if session is None or not session.is_active:
            continue

        candidates = [d for d in devices if d.output is not None]
        if not candidates:
            continue
        dev = random.choice(candidates)
        channels = list(dev.output._channels.values())
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
# Initial value push
# ===========================================================================


async def push_initial_output_values(devices: list[DevInfo]) -> None:
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
    status = _col(GREEN_C, "CONNECTED") if connected else _col(RED_C, "WAITING…")
    print(f"\n{BOLD}{'=' * 64}{RESET}")
    print(f"  pydsvdcapi Example — Climate  |  {status}")
    print(
        f"  {GREY_C}C1=heating  C2=cooling  C3=ventilation  C4=window{RESET}"
    )
    print(
        f"  {GREY_C}C5=FCU  C6=apt-vent  C7=apt-recirc  C8=temp-ctrl{RESET}"
    )
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
            {stdin_wait, notif_wait}, return_when=asyncio.FIRST_COMPLETED
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

        if stdin_wait not in done:
            continue
        cmd = stdin_wait.result().lower().strip()

        if cmd == "r":
            print(f"\n{YELLOW_C}Restart requested — vanishing devices…{RESET}")
            restart_event.set()
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
    print(f"\n{BOLD}pydsvdcapi Example — Climate — {len(devices)} devices built{RESET}")
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
```

- [ ] **Step 2: Syntax and lint check**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m py_compile examples/example_climate.py && echo "OK"
python -m ruff check examples/example_climate.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add examples/example_climate.py
git commit -m "feat: add example_climate.py — 8 blue climate devices (heating, cooling, vent, window, FCU, apt-vent, apt-recirc, temp-ctrl)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Simple Light (ON/OFF + threshold) → L1 with `outconfigswitch` + `impulseconfig`
- ✅ Dimmable Light (gradual) → L2 `DIMMER` + `GRADUAL`
- ✅ Dim+CT Light → L3 `DIMMER_COLOR_TEMP` + `outputchannels`
- ✅ Full-color RGBW → L4 `FULL_COLOR_DIMMER`
- ✅ Curtain (indoor position) → S1 `SHADE_POSITION_INDOOR`
- ✅ Awning (outdoor position) → S2 `AWNINGS` group + `windprotectionconfigawning`
- ✅ Indoor Blinds (position + tilt) → S3 indoor channels + `shadebladeang`
- ✅ Outdoor Shutter (position + tilt) → S4 outdoor channels + `windprotectionconfigblind`
- ✅ Room Heating Valve → C1
- ✅ Room Cooling Device → C2
- ✅ Room Ventilation → C3
- ✅ Window Opener → C4
- ✅ FCU / Fan-Coil → C5
- ✅ Apartment Ventilation → C6
- ✅ Apartment Recirculation → C7
- ✅ Temperature Controller → C8
- ✅ Clean quit (vanish + delete persistence) → all scripts
- ✅ Restart support → all scripts

**Placeholder scan:** None found — all steps contain complete code.

**Type consistency:**
- `DevInfo` fields: `idx: int`, `name: str`, `device: Device`, `vdsd: Vdsd`, `output: Output | None` — consistent across all three files (shading adds `outdoor: bool`)
- `_channel_callback` signature matches `Output.on_channel_applied` protocol
- `_control_value_callback` signature matches `Vdsd.on_control_value` protocol
- All `_output()` helpers pass `**kwargs` through to `Output()` constructor
