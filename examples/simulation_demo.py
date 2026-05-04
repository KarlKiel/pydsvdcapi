#!/usr/bin/env python3
"""Comprehensive vDC simulation demo.

This script demonstrates the full feature set of pydsvdcapi through an
interactive simulation with three virtual devices.

Overview
--------
After prompting for a TCP port the script:

1. Creates a :class:`VdcHost` and a :class:`Vdc` with a custom template
   directory, then starts zeroconf/DNS-SD announcement.
2. Waits for a dSS / vdSM to connect and announces the vDC.
3. Announces three virtual devices:

   **Device A — Motion-sensor + SingleDevice action** (``ColorClass.WHITE`` / primaryGroup 9)
     * :class:`BinaryInput` ds_index=0 — presence/motion sensor
     * :class:`Output` ``OutputFunction.INTERNALLY_CONTROLLED`` + ``OutputMode.DISABLED``
       (mirrors p44vdc ``ActionOutputBehaviour`` — no regular output channels)
     * :class:`DeviceActionDescription` + :class:`CustomAction` —
       ``toggle`` action that toggles the simulated light
     * Model feature ``highlevel`` (``outvalue8`` suppressed by action output type)
     * Periodic mock: randomly toggles motion; brightness tracked internally

   **Device B — Single button + CT Light + Temperature sensor** (``ColorGroup.BLACK`` / group 8)
     * One :class:`ButtonInput` element — SINGLE_PUSHBUTTON
     * :class:`SensorInput` ds_index=0 — room temperature (–10 … 50 °C)
     * :class:`Output` ``OutputFunction.DIMMER_COLOR_TEMP`` — auto-creates
       ``BRIGHTNESS`` (ds_index=0) + ``COLOR_TEMPERATURE`` (ds_index=1,
       in **mired** 100–1000); ``active_group=1``
     * :class:`DeviceProperty` — ``operatingHours`` numeric property
     * Periodic mock: simulates button presses + operating-hour and temperature updates

   **Device C — Window-sensor + Relay** (``ColorGroup.BLACK``)
     * :class:`BinaryInput` ds_index=0 — window-open contact
       (``BinaryInputType.WINDOW_OPEN``)
     * :class:`Output` ``OutputFunction.ON_OFF`` — auto-creates
       ``BRIGHTNESS`` channel (relay on when brightness > onThreshold)
     * :class:`DeviceEvent` — ``windowAlert`` event fired when the
       window state changes
     * Periodic mock: cycles window values + raises events

Interactive menu (press a key when prompted):

  ``[1]`` **Simulate VDC breakdown & auto-restore**
          Stops the host, deletes persisted state, rebuilds from the
          auto-saved YAML backup, and re-announces everything.

  ``[2]`` **Save Device A as template + create Device D**
          Saves Device A to the template directory, loads it back, and
          instantiates a fourth device ("Motion Sensor Backup") with its
          own fresh dSUID.

  ``[3]`` **End simulation**
          Vanishes all devices, sends goodbye, stops the host, and
          cleans up all temporary files and templates.

Run from the project root::

    python examples/simulation_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import random
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the package importable when running from the repository root.
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import contextlib  # noqa: E402

from pydsvdcapi import (  # noqa: E402
    PROPERTY_TYPE_NUMERIC,
    BinaryInput,
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
)
from pydsvdcapi import genericVDC_pb2 as pb  # noqa: E402
from pydsvdcapi.actions import ActionParameter  # noqa: E402
from pydsvdcapi.dsuid import DsUid, DsUidNamespace  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TMP = Path("/tmp/pydsvdcapi_simdemo")
STATE_FILE = _TMP / "state.yaml"
TEMPLATE_DIR = _TMP / "templates"

# ---------------------------------------------------------------------------
# vDC / host identity
# ---------------------------------------------------------------------------

MODEL_NAME = "pydsvdcapi Simulation Demo Gateway"
HOST_NAME = "pydsvdcapi Simulation Demo Host"
VENDOR = "pydsvdcapi"

VDC_IMPLEMENTATION_ID = "x-pydsvdcapi-sim-demo"
VDC_NAME = "Simulation Demo vDC"
VDC_MODEL = "pydsvdcapi Simulation Demo Controller v1"

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
BLUE = "\033[94m"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


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


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColourFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    # Silence noisy per-tick internal loggers; keep WARNING+ visible.
    for _noisy in (
        "zeroconf",
        "pydsvdcapi.output_channel",
        "pydsvdcapi.session",
        "pydsvdcapi.output",
        "pydsvdcapi.binary_input",
        "pydsvdcapi.sensor_input",
    ):
        logging.getLogger(_noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------


def banner(text: str) -> None:
    width = 64
    print()
    print(f"{BOLD}{CYAN}{'=' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {text.center(width - 4)}  {RESET}")
    print(f"{BOLD}{CYAN}{'=' * width}{RESET}")
    print()


def section(text: str) -> None:
    print(f"\n{BOLD}{BLUE}--- {text} ---{RESET}\n")


def info(text: str) -> None:
    print(f"{GREEN}[demo]{RESET} {text}")


def warn(text: str) -> None:
    print(f"{YELLOW}[warn]{RESET} {text}")


async def wait_for_session(host: VdcHost, timeout: float = CONNECT_TIMEOUT) -> None:
    """Block until the vdSM completes the Hello handshake."""
    info(f"Waiting up to {int(timeout)}s for vdSM to connect on port {host.port}…")
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


async def wait_for_user(prompt: str) -> None:
    """Wait for Enter without blocking the event loop."""
    loop = asyncio.get_running_loop()
    print()
    print(f"{BOLD}{YELLOW}{prompt}{RESET}")

    def _read():
        line = sys.stdin.readline()
        return line  # empty string on EOF — caller doesn't use return value

    await loop.run_in_executor(None, _read)


async def show_menu() -> str:
    """Display the interactive menu and return the chosen key."""
    loop = asyncio.get_running_loop()

    def _read() -> str:
        print()
        print(f"{BOLD}{CYAN}╔══════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}{CYAN}║         Simulation Demo — Main Menu      ║{RESET}")
        print(f"{BOLD}{CYAN}╠══════════════════════════════════════════╣{RESET}")
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[1]{RESET} Simulate VDC breakdown + auto-restore   {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[2]{RESET} Save Device A as template → Device D     {CYAN}║{RESET}"
        )
        print(
            f"{BOLD}{CYAN}║{RESET}  {YELLOW}[3]{RESET} End simulation (vanish, cleanup)         {CYAN}║{RESET}"
        )
        print(f"{BOLD}{CYAN}╚══════════════════════════════════════════╝{RESET}")
        print(f"{BOLD}Choice:{RESET} ", end="", flush=True)
        line = sys.stdin.readline()
        if not line:  # EOF — stdin closed (e.g. piped input exhausted)
            return "3"
        return line.strip()

    return await loop.run_in_executor(None, _read)


# ---------------------------------------------------------------------------
# Protobuf callback
# ---------------------------------------------------------------------------


async def on_message(session, msg: pb.Message) -> pb.Message | None:
    """Handle messages not already consumed by the session layer."""
    type_name = pb.Type.Name(msg.type)
    logging.getLogger("pb").debug(
        "%sRX%s  type=%-35s  msg_id=%d  from=%s",
        CYAN,
        RESET,
        type_name,
        msg.message_id,
        session.vdsm_dsuid,
    )
    if msg.message_id > 0:
        resp = pb.Message()
        resp.type = pb.GENERIC_RESPONSE
        resp.message_id = msg.message_id
        resp.generic_response.code = pb.ERR_OK
        return resp
    return None


# ===========================================================================
# Device-A — Motion Sensor + Dimmer + Action
# ===========================================================================


def build_device_a(vdc: Vdc) -> Device:
    """Build Device A: motion binary-input + dimmer + toggle action."""
    dsuid = DsUid.from_name_in_space("sim-demo-device-a", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)
    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Motion Dimmer",
        model="pydsvdcapi Sim-A v1",
        primary_group=ColorClass.WHITE,  # 9 — Single Device (Einzelgerät)
    )
    device.add_vdsd(vdsd)

    # --- binary input: presence / motion sensor -----------------------
    bi = BinaryInput(
        vdsd=vdsd,
        ds_index=0,
        sensor_function=BinaryInputType.PRESENCE,
        input_usage=BinaryInputUsage.ROOM_CLIMATE,
        name="Motion Sensor",
    )
    vdsd.add_binary_input(bi)

    # --- output: action output (equivalent to p44vdc ActionOutputBehaviour) ---
    # SingleDevices must use INTERNALLY_CONTROLLED (=6) + DISABLED (=0).
    # ActionOutputBehaviour in p44vdc sets exactly these values and suppresses
    # outvalue8 / outmodegeneric / blink — no regular output channels are created.
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.INTERNALLY_CONTROLLED,
        name="output",
        mode=OutputMode.DISABLED,
        default_group=int(ColorGroup.BLACK),
        active_group=int(ColorGroup.BLACK),
        groups={int(ColorGroup.BLACK)},
    )
    vdsd.set_output(output)

    # --- action description: "toggle" ---------------------------------
    param = ActionParameter(
        name="brightness",
        type="numeric",
        min_value=0.0,
        max_value=100.0,
        resolution=1.0,
        siunit="%",
        default=100.0,
    )
    desc = DeviceActionDescription(
        vdsd=vdsd,
        ds_index=0,
        name="toggle",
        params=[param],
        description="Toggle the simulated light on/off",
    )
    vdsd.add_device_action_description(desc)

    # --- custom action built on the description ----------------------
    cust = CustomAction(
        vdsd=vdsd,
        ds_index=0,
        name="custom.toggle-full",
        action="toggle",
        title="Toggle Full Brightness",
        params={"brightness": 100.0},
    )
    vdsd.add_custom_action(cust)

    # highlevel: SingleDevice action UI in dSS
    # Note: outvalue8 / outmodegeneric / blink are suppressed for action outputs
    vdsd.add_model_feature("highlevel")

    return device


class MockDeviceA:
    """Background simulator for Device A (motion + dimmer)."""

    def __init__(self, device: Device) -> None:
        self._vdsd: Vdsd = list(device.vdsds.values())[0]
        self._bi: BinaryInput = self._vdsd.binary_inputs[0]
        self._output: Output = self._vdsd.output
        self._task: asyncio.Task | None = None
        self._log = logging.getLogger("mock-A")
        self._motion = False
        self._brightness = 0.0

        # Wire the invoke-action callback
        self._vdsd.on_invoke_action = self._on_invoke_action

    async def _on_invoke_action(self, action_id: str, params: dict) -> None:
        brightness = params.get("brightness", 100.0)
        self._brightness = brightness if self._brightness == 0.0 else 0.0
        self._log.info(
            "%s[Action A]%s invoke '%s'  brightness → %.0f%%",
            MAGENTA,
            RESET,
            action_id,
            self._brightness,
        )
        # Action output has no regular output channel; state is tracked internally.

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())
        info("Mock Device A started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        info("Mock Device A stopped")

    async def _run(self) -> None:
        try:
            cycle = 0
            while True:
                # Toggle motion every ~5 s, with some randomness
                if cycle % 10 == 0:
                    self._motion = not self._motion
                    await self._bi.update_value(self._motion)
                    self._log.info(
                        "%s[A] Motion%s → %s",
                        CYAN,
                        RESET,
                        "DETECTED" if self._motion else "cleared",
                    )

                cycle += 1
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Device-B — Rocker Switch + CT Dimmer + DeviceProperty
# ===========================================================================


def build_device_b(vdc: Vdc) -> Device:
    """Build Device B: rocker-button + brightness+CT dimmer + property."""
    dsuid = DsUid.from_name_in_space("sim-demo-device-b", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)
    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Rocker CT Light",
        model="pydsvdcapi Sim-B v1",
        primary_group=ColorClass.BLACK,  # experiment: group 8 — does it affect properties visibility?
    )
    device.add_vdsd(vdsd)

    # --- button: single pushbutton (rocker replaced with one btn + sensor)
    btn = ButtonInput(
        vdsd=vdsd,
        ds_index=0,
        button_id=0,
        button_type=ButtonType.SINGLE_PUSHBUTTON,
        name="Rocker",
        group=1,
        function=ButtonFunction.DEVICE,
        mode=ButtonMode.STANDARD,
    )
    vdsd.add_button_input(btn)

    # --- sensor input: room temperature --------------------------------
    si = SensorInput(
        vdsd=vdsd,
        ds_index=0,
        sensor_type=SensorType.TEMPERATURE,
        sensor_usage=SensorUsage.ROOM,
        name="Room Temperature",
        min_value=-10.0,
        max_value=50.0,
        resolution=0.1,
        update_interval=60.0,
    )
    vdsd.add_sensor_input(si)

    # --- output: two-channel CT dimmer (brightness + colour temperature) -
    # OutputFunction.DIMMER_COLOR_TEMP auto-creates BRIGHTNESS (ds_index=0)
    # and COLOR_TEMPERATURE (ds_index=1).  COLOR_TEMPERATURE is in mired
    # (100–1000 mired, i.e. ~1000K–10000K; standard warm-white range is
    # roughly 154–370 mired / 2700K–6500K).
    # active_group=1 (Yellow / Light) enables modelFeatures "light".
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
    output.on_channel_applied = _make_on_channel_applied("B")

    # --- device property: operating hours -----------------------------
    prop = DeviceProperty(
        vdsd=vdsd,
        ds_index=0,
        name="operatingHours",
        type=PROPERTY_TYPE_NUMERIC,
        min_value=0.0,
        max_value=500_000.0,
        resolution=0.1,
        siunit="h",
        default=0.0,
    )
    vdsd.add_device_property(prop)

    # outvalue8: test whether dSS reflects delivered modelFeatures
    vdsd.add_model_feature("outvalue8")

    return device


def _make_on_channel_applied(label: str):
    async def on_channel_applied(output: Output, updates: dict) -> None:
        parts = []
        for ch_type, val in updates.items():
            name = ch_type.name if hasattr(ch_type, "name") else str(ch_type)
            parts.append(f"{name}={val:.1f}")
        info(f"{MAGENTA}[{label}] on_channel_applied{RESET}  {', '.join(parts)}")

    return on_channel_applied


class MockDeviceB:
    """Background simulator for Device B (single button + CT dimmer + temp sensor)."""

    def __init__(self, device: Device) -> None:
        self._vdsd: Vdsd = list(device.vdsds.values())[0]
        self._output: Output = self._vdsd.output
        self._prop: DeviceProperty = self._vdsd.device_properties[0]
        self._sensor: SensorInput = self._vdsd.sensor_inputs[0]
        self._task: asyncio.Task | None = None
        self._log = logging.getLogger("mock-B")
        self._brightness = 50.0
        # CT is in mired (100–1000).  333 mired ≈ 3000 K (warm white).
        self._ct = 333.0
        self._op_hours = 0.0
        # Simulated room temperature (°C)
        self._temperature = 21.0

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())
        # Push initial sensor value immediately so the dSS can show it
        # right after announcement (value is not None from first cycle).
        asyncio.ensure_future(self._sensor.update_value(round(self._temperature, 1)))
        info("Mock Device B started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        info("Mock Device B stopped")

    async def _run(self) -> None:
        try:
            cycle = 0
            while True:
                # Vary brightness + CT
                self._brightness = max(
                    0.0, min(100.0, self._brightness + random.uniform(-3.0, 3.0))
                )
                # Vary CT within 154–1000 mired (≈6500K–1000K)
                self._ct = max(
                    154.0, min(1000.0, self._ct + random.uniform(-10.0, 10.0))
                )
                ch_br = self._output.get_channel_by_type(OutputChannelType.BRIGHTNESS)
                ch_ct = self._output.get_channel_by_type(
                    OutputChannelType.COLOR_TEMPERATURE
                )
                if ch_br is not None:
                    await ch_br.update_value(self._brightness)
                if ch_ct is not None:
                    await ch_ct.update_value(self._ct)

                # Accumulate operating hours every tick (0.5 s tick → 1/7200 h)
                self._op_hours += 1.0 / 7200.0
                # Vary temperature slightly each tick
                self._temperature = max(
                    15.0, min(30.0, self._temperature + random.uniform(-0.05, 0.05))
                )

                # Push sensor update every ~5 s (10 cycles × 0.5 s).
                if cycle % 10 == 0:
                    await self._sensor.update_value(round(self._temperature, 1))
                    self._log.info(
                        "%s[B] temperature%s → %.1f °C",
                        MAGENTA,
                        RESET,
                        self._temperature,
                    )

                # Log + push property every ~30 s (60 cycles)
                if cycle % 60 == 0:
                    await self._prop.update_value(round(self._op_hours, 4))
                    self._log.info(
                        "%s[B] operatingHours%s → %.4f h",
                        MAGENTA,
                        RESET,
                        self._op_hours,
                    )

                cycle += 1
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Device-C — Window Sensor + Relay + DeviceEvent
# ===========================================================================


def build_device_c(vdc: Vdc) -> Device:
    """Build Device C: window contact binary-input + relay output + event."""
    dsuid = DsUid.from_name_in_space("sim-demo-device-c", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)
    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="Window Relay",
        model="pydsvdcapi Sim-C v1",
        primary_group=ColorClass.BLACK,
    )
    device.add_vdsd(vdsd)

    # --- binary input: window-open contact ---------------------------
    bi = BinaryInput(
        vdsd=vdsd,
        ds_index=0,
        sensor_function=BinaryInputType.WINDOW_OPEN,
        input_usage=BinaryInputUsage.OUTDOOR_CLIMATE,
        name="Window Contact",
    )
    vdsd.add_binary_input(bi)

    # --- output: on/off relay -----------------------------------------
    # OutputFunction.ON_OFF auto-creates the BRIGHTNESS channel (ds_index=0).
    # The relay is ON when brightness > onThreshold (default 50 %).
    # default_group/active_group/groups must match the vdSD primary_group
    # (group 8 = Black/Joker); without them dSM shows no group on the device.
    # mode=BINARY suits a relay: the dSM treats it as on/off, not gradual.
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.ON_OFF,
        name="output",
        default_group=8,
        active_group=8,
        groups={8},
        mode=OutputMode.BINARY,
        push_changes=True,
    )
    vdsd.set_output(output)
    output.on_channel_applied = _make_on_channel_applied("C")

    # --- device event: window state change alert ----------------------
    evt = DeviceEvent(
        vdsd=vdsd,
        ds_index=0,
        name="windowAlert",
        description="Fired when the window transitions between open and closed",
    )
    vdsd.add_device_event(evt)

    # outvalue8: test whether dSS reflects delivered modelFeatures
    vdsd.add_model_feature("outvalue8")

    return device


class MockDeviceC:
    """Background simulator for Device C (window contact + relay + event)."""

    def __init__(self, device: Device) -> None:
        self._vdsd: Vdsd = list(device.vdsds.values())[0]
        self._bi: BinaryInput = self._vdsd.binary_inputs[0]
        self._output: Output = self._vdsd.output
        self._event: DeviceEvent = self._vdsd.device_events[0]
        self._task: asyncio.Task | None = None
        self._log = logging.getLogger("mock-C")
        self._window_open = False
        self._relay_on = False

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())
        info("Mock Device C started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        info("Mock Device C stopped")

    async def _run(self) -> None:
        try:
            cycle = 0
            while True:
                # Toggle window state every ~8 s
                if cycle % 16 == 0:
                    prev = self._window_open
                    # 30% chance of flipping state
                    if random.random() < 0.30:
                        self._window_open = not self._window_open
                    if self._window_open != prev:
                        await self._bi.update_value(self._window_open)
                        self._log.info(
                            "%s[C] Window%s → %s",
                            CYAN,
                            RESET,
                            "OPEN" if self._window_open else "closed",
                        )
                        # Raise event on every transition
                        await self._event.raise_event()
                        self._log.info(
                            "%s[C] Event%s 'windowAlert' raised!",
                            MAGENTA,
                            RESET,
                        )

                # Relay mirrors window state (open → relay off / ventilation etc.)
                # ON_OFF output uses BRIGHTNESS channel: 100%=on, 0%=off.
                new_relay = not self._window_open
                if new_relay != self._relay_on:
                    self._relay_on = new_relay
                    ch = self._output.get_channel_by_type(OutputChannelType.BRIGHTNESS)
                    if ch is not None:
                        await ch.update_value(100.0 if self._relay_on else 0.0)
                    self._log.info(
                        "%s[C] Relay%s → %s",
                        CYAN,
                        RESET,
                        "ON" if self._relay_on else "OFF",
                    )

                cycle += 1
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Factory helpers
# ===========================================================================


def build_all_devices(vdc: Vdc) -> dict:
    """Build and return the active devices (currently Device A only)."""
    return {
        "A": build_device_a(vdc),
    }


async def announce_devices(
    host: VdcHost,
    vdc: Vdc,
    devices: dict,
) -> None:
    """Announce all devices in *devices* to the vdSM."""
    # Register all devices with the vDC first so that any getProperty
    # queries from the dSM (for devices it remembers from a prior session)
    # are answered correctly before we start the announcement loop.
    for device in devices.values():
        vdc.add_device(device)

    session = host.session

    # Announce all devices concurrently.  When the vDC has multiple
    # pre-registered devices the dSM discovers all of them at once and
    # will not confirm any single announce until all are in flight —
    # sequential announcing would deadlock.
    async def _announce_one(label: str, device: Device) -> None:
        for vdsd in device.vdsds.values():
            ok = await vdsd.announce(session)
            info(
                f"{GREEN}[{label}]{RESET} "
                f"'{vdsd.name}' announced  "
                f"(dSUID={vdsd.dsuid}  ok={ok})"
            )

    await asyncio.gather(
        *[_announce_one(label, device) for label, device in devices.items()]
    )


async def vanish_devices(host: VdcHost, devices: dict) -> None:
    """Send vanish for all devices in *devices*."""
    session = host.session
    for label, device in devices.items():
        for vdsd in device.vdsds.values():
            await vdsd.vanish(session)
            info(f"{YELLOW}[{label}]{RESET} '{vdsd.name}' vanished")


def build_mocks(devices: dict) -> dict:
    return {
        "A": MockDeviceA(devices["A"]),
    }


async def start_mocks(mocks: dict) -> None:
    for m in mocks.values():
        m.start()


async def stop_mocks(mocks: dict) -> None:
    for m in mocks.values():
        await m.stop()


# ===========================================================================
# Menu action implementations
# ===========================================================================


async def action_breakdown_restore(
    host: VdcHost,
    vdc: Vdc,
    devices: dict,
    mocks: dict,
    port: int,
) -> tuple[VdcHost, Vdc, dict, dict]:
    """Stop everything, wipe state, rebuild from YAML, re-announce.

    Returns the new (host, vdc, devices, mocks) tuple.
    """
    banner("Menu [1] — Simulate VDC breakdown + auto-restore")

    section("Stopping mock simulators…")
    await stop_mocks(mocks)

    section("Stopping VdcHost (simulating breakdown)…")
    await host.stop()
    info("Host stopped.")

    # Delete persisted state so we force a cold-restore from the
    # backup YAML that auto-save wrote while we were running.
    backup = STATE_FILE.with_suffix(".bak.yaml")
    if backup.exists():
        # Replace state with backup
        backup.replace(STATE_FILE)
        info(f"Replaced state file with backup: {STATE_FILE}")
    else:
        warn("No .bak.yaml found — using existing state file as-is.")

    await asyncio.sleep(2)
    section("Rebuilding VdcHost from persisted YAML…")

    new_host = VdcHost(
        port=port,
        state_path=STATE_FILE,
    )
    # The restored vdc is present in new_host.vdcs; grab the first one.
    if not new_host.vdcs:
        warn("No vDC found in restored state — rebuilding from scratch.")
        new_vdc = Vdc(
            host=new_host,
            implementation_id=VDC_IMPLEMENTATION_ID,
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
        # Re-attach template_path (not persisted)
        new_vdc._template_path = TEMPLATE_DIR  # type: ignore[attr-defined]

    info(f"Restored vDC: {new_vdc.name}  (dSUID={new_vdc.dsuid})")

    # Pre-register devices before starting so early dSM queries succeed.
    section("Re-building and registering devices…")
    new_devices = build_all_devices(new_vdc)
    for device in new_devices.values():
        new_vdc.add_device(device)

    await new_host.start(on_message=on_message)
    info("New host started.")

    await wait_for_session(new_host)

    # Wait for auto-announce (vDC + devices) to complete.
    for _ in range(40):  # up to 20 s
        if new_vdc.is_announced and all(d.is_announced for d in new_devices.values()):
            break
        await asyncio.sleep(0.5)

    if not new_vdc.is_announced:
        warn("vDC re-announcement failed.")
    else:
        info("vDC and all devices re-announced")

    section("Restarting mock simulators…")
    new_mocks = build_mocks(new_devices)
    await start_mocks(new_mocks)

    info("Breakdown + restore complete!")
    return new_host, new_vdc, new_devices, new_mocks


async def action_save_template_create_d(
    host: VdcHost,
    vdc: Vdc,
    devices: dict,
) -> Device | None:
    """Save Device A as template, load and instantiate Device D."""
    banner("Menu [2] — Save Device A as template → Device D")

    if vdc._template_path is None:  # type: ignore[attr-defined]
        warn("Template path not set on vDC — cannot save template.")
        return None

    section("Saving Device A as template…")
    device_a = devices["A"]
    try:
        tpl_path = vdc.save_template(
            device_a,
            template_type="generic",
            integration="x-pydsvdcapi-sim",
            name="motion-dimmer",
            description="Motion sensor + dimmable light (simulation demo)",
        )
        info(f"Template saved to: {tpl_path}")
    except Exception as exc:
        warn(f"save_template failed: {exc}")
        return None

    section("Loading template and instantiating Device D…")
    try:
        tmpl = vdc.load_template("generic", "x-pydsvdcapi-sim", "motion-dimmer")
    except Exception as exc:
        warn(f"load_template failed: {exc}")
        return None

    info(f"Template loaded: '{tmpl.name}'  type={tmpl.template_type}")
    info(f"  required_fields : {list(tmpl.required_fields.keys())}")

    dsuid_d = DsUid.from_name_in_space("sim-demo-device-d", DsUidNamespace.VDC)
    tmpl.configure({"vdsds[0].name": "Motion Dimmer (Backup)"})

    try:
        device_d = tmpl.instantiate(vdc=vdc, dsuid=dsuid_d)
    except Exception as exc:
        warn(f"instantiate failed: {exc}")
        return None

    # Wire the invoke-action callback (required_callbacks must be set)
    vdsd_d = list(device_d.vdsds.values())[0]
    vdsd_d.on_invoke_action = _device_d_invoke_action

    session = host.session
    vdc.add_device(device_d)
    ok = await vdsd_d.announce(session)
    info(
        f"{GREEN}[D]{RESET} '{vdsd_d.name}' announced  (dSUID={vdsd_d.dsuid}  ok={ok})"
    )
    return device_d


async def _device_d_invoke_action(action_id: str, params: dict) -> None:
    info(f"{MAGENTA}[D] on_invoke_action{RESET}  id='{action_id}'  params={params}")


async def action_end(
    host: VdcHost,
    devices: dict,
    mocks: dict,
    device_d: Device | None,
) -> None:
    """Vanish all devices, stop host, clean up all temporary files."""
    banner("Menu [3] — End simulation")

    section("Stopping mock simulators…")
    await stop_mocks(mocks)

    section("Vanishing devices…")
    await vanish_devices(host, devices)
    if device_d is not None:
        vdsd_d = list(device_d.vdsds.values())[0]
        session = host.session
        await vdsd_d.vanish(session)
        info("[D] vanished")

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


# ===========================================================================
# Main coroutine
# ===========================================================================

# ===========================================================================
# Main coroutine
# ===========================================================================


async def main() -> None:
    import signal

    setup_logging()
    _TMP.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Ctrl+C → graceful shutdown ──────────────────────────────────────
    loop = asyncio.get_running_loop()
    _stop_event = asyncio.Event()

    def _sigint_handler() -> None:
        print(f"\n{BOLD}{YELLOW}Ctrl+C — requesting clean shutdown…{RESET}")
        _stop_event.set()

    loop.add_signal_handler(signal.SIGINT, _sigint_handler)

    # ── Port selection ──────────────────────────────────────────────────

    def _ask_port() -> int:
        while True:
            try:
                raw = input(
                    f"\n{BOLD}Enter TCP port for the VdcHost [default 8444]: {RESET}"
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

    # ── Build VdcHost + VDC ─────────────────────────────────────────────
    banner("Starting Simulation Demo")

    host = VdcHost(
        port=port,
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

    # ── Build and register devices BEFORE starting the host ────────────
    # The dSM may query known devices immediately on Hello (from a prior
    # session).  Pre-registering ensures getProperty returns valid data
    # instead of ERR_NOT_FOUND, which would cause the dSM to drop the
    # connection before auto-announce can complete.
    section("Building and registering Device A…")
    devices = build_all_devices(vdc)
    for device in devices.values():
        vdc.add_device(device)

    # ── Start TCP server + DNS-SD (auto-announces vDC + all devices) ────
    await host.start(on_message=on_message)
    info("TCP server started — service announced via DNS-SD")

    try:
        await wait_for_session(host)
    except TimeoutError as exc:
        logging.getLogger("main").error(str(exc))
        await host.stop()
        return

    # ── Wait for auto-announce to complete ─────────────────────────────
    section("Waiting for auto-announce to complete…")
    for _ in range(40):  # up to 20 s
        if vdc.is_announced and all(d.is_announced for d in devices.values()):
            break
        await asyncio.sleep(0.5)

    if not vdc.is_announced:
        warn("vDC announcement failed — aborting.")
        await host.stop()
        return
    unannouncedlabels = [lbl for lbl, d in devices.items() if not d.is_announced]
    if unannouncedlabels:
        warn(f"Devices {unannouncedlabels} were not announced — aborting.")
        await host.stop()
        return
    info("vDC and all devices announced successfully")

    # ── Pause before mocks start ────────────────────────────────────────
    await wait_for_user(
        "Devices are announced.  Check the dSS configurator now.\n"
        "Press Enter to start mock simulators…"
    )

    # ── Start mock simulators ───────────────────────────────────────────
    section("Starting mock device simulators…")
    mocks = build_mocks(devices)
    await start_mocks(mocks)

    # ── Interactive menu loop ───────────────────────────────────────────
    device_d: Device | None = None

    while True:
        # Honour Ctrl+C between menu iterations
        if _stop_event.is_set():
            await action_end(host, devices, mocks, device_d)
            break

        # Run show_menu in executor; also watch for stop event so Ctrl+C
        # doesn't get stuck waiting for stdin.
        menu_task = asyncio.ensure_future(show_menu())
        stop_waiter = asyncio.ensure_future(_stop_event.wait())
        done, pending = await asyncio.wait(
            [menu_task, stop_waiter],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()

        if _stop_event.is_set():
            await action_end(host, devices, mocks, device_d)
            break

        choice = menu_task.result() if not menu_task.cancelled() else ""

        if choice == "1":
            host, vdc, devices, mocks = await action_breakdown_restore(
                host, vdc, devices, mocks, port
            )
            device_d = None  # Device D is lost after rebuild

        elif choice == "2":
            device_d = await action_save_template_create_d(host, vdc, devices)

        elif choice == "3":
            await action_end(host, devices, mocks, device_d)
            break

        else:
            warn(f"Unknown choice: '{choice}' — please enter 1, 2, or 3.")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    asyncio.run(main())
