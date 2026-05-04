#!/usr/bin/env python3
"""OutputFunction × channel-type matrix test.

Announces 9 vdSDs on one shared VDC (dynamicDefinitions=True):

  Device 1  — group 1, fn=1 DIMMER (brightness auto)
  Device 2  — group 2, fn=2 POSITIONAL (shadePositionOutside)
  Device 3  — group 3, fn=2 POSITIONAL (heatingPower)
  Device 4  — group 4, fn=2 POSITIONAL (audioVolume)
  Device 5  — group 5, fn=2 POSITIONAL (audioVolume)
  Device 6  — group 1, fn=3 DIMMER_COLOR_TEMP (brightness+colortemp auto)
  Device 7  — group 2, fn=2 POSITIONAL (shadePositionOutside+shadeOpeningAngleOutside)
  Device 8  — group 1, fn=4 FULL_COLOR_DIMMER (brightness+hue+sat+cct+x+y auto)
  Device 9  — group 8, fn=6 INTERNALLY_CONTROLLED (powerState)

Usage::

    python examples/test_matrix_dynamic.py [--port PORT]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydsvdcapi import (
    ColorGroup,
    Device,
    DsUid,
    DsUidNamespace,
    Output,
    OutputChannelType,
    OutputFunction,
    OutputMode,
    Vdc,
    VdcCapabilities,
    VdcHost,
    Vdsd,
)
from pydsvdcapi.enums import ColorClass
from pydsvdcapi.output_channel import CHANNEL_SPECS, OutputChannel

# ---------------------------------------------------------------------------
# Device configuration table
# ---------------------------------------------------------------------------


@dataclass
class DeviceConfig:
    name: str
    # ColorClass value (= primaryGroup sent to dSS)
    color_class: ColorClass
    # Output application group (ColorGroup int, matches color_class for 1–8)
    output_group: int
    # OutputFunction for the output
    output_function: OutputFunction
    # Explicit channel types to add; empty = auto-created by the OutputFunction
    channel_types: list[OutputChannelType] = field(default_factory=list)
    # Extra model features to add manually before derive_model_features()
    extra_features: list[str] = field(default_factory=list)
    # Optional GTIN
    gtin: str | None = None
    # Note for the summary
    note: str = ""

    @property
    def initial_channel_value(self) -> float:
        """Midpoint of the primary channel's range per CHANNEL_SPECS."""
        ct = (
            self.channel_types[0]
            if self.channel_types
            else OutputChannelType.BRIGHTNESS
        )
        spec = CHANNEL_SPECS.get(ct)
        if spec is None:
            return 0.0
        return round((spec.min_value + spec.max_value) / 2.0, 2)


# Devices under test
DEVICES: list[DeviceConfig] = [
    # 1 — standard light dimmer (group 1)
    DeviceConfig(
        name="PG1_Yellow_Lights",
        color_class=ColorClass.YELLOW,
        output_group=int(ColorGroup.YELLOW),
        output_function=OutputFunction.DIMMER,
        note="fn=1 DIMMER: brightness auto-created",
    ),
    # 2 — shade positional (group 2)
    DeviceConfig(
        name="PG2_Grey_Shades",
        color_class=ColorClass.GREY,
        output_group=int(ColorGroup.GREY),
        output_function=OutputFunction.POSITIONAL,
        channel_types=[OutputChannelType.SHADE_POSITION_OUTSIDE],
        note="fn=2 POSITIONAL: shadePositionOutside (11)",
    ),
    # 3 — heating (group 3)
    DeviceConfig(
        name="PG3_Blue_Heating",
        color_class=ColorClass.BLUE_CLIMATE,
        output_group=int(ColorGroup.BLUE),
        output_function=OutputFunction.POSITIONAL,
        channel_types=[OutputChannelType.HEATING_POWER],
        extra_features=["heatingoutmode", "pwmvalue"],
        note="fn=2 POSITIONAL: heatingPower (primary per ds-basics Table 7); heatingoutmode+pwmvalue added manually",
    ),
    # 4 — audio (group 4)
    DeviceConfig(
        name="PG4_Cyan_Audio",
        color_class=ColorClass.CYAN,
        output_group=int(ColorGroup.CYAN),
        output_function=OutputFunction.POSITIONAL,
        channel_types=[OutputChannelType.AUDIO_VOLUME],
        note="fn=2 POSITIONAL: audioVolume (41)",
    ),
    # 5 — video (group 5)
    DeviceConfig(
        name="PG5_Magenta_Video",
        color_class=ColorClass.MAGENTA,
        output_group=int(ColorGroup.MAGENTA),
        output_function=OutputFunction.POSITIONAL,
        channel_types=[
            OutputChannelType.AUDIO_VOLUME,  # dsIndex=0: primary per ds-basics Table 7
            OutputChannelType.POWER_STATE,
            OutputChannelType.VIDEO_INPUT_SOURCE,
            OutputChannelType.VIDEO_STATION,
        ],
        note="fn=2 POSITIONAL: audioVolume(18) primary, powerState(19)+videoInputSource(26)+videoStation(25)",
    ),
    # 6 — tunable white light (group 1, fn=3 DIMMER_COLOR_TEMP)
    DeviceConfig(
        name="PG1_TunableWhite",
        color_class=ColorClass.YELLOW,
        output_group=int(ColorGroup.YELLOW),
        output_function=OutputFunction.DIMMER_COLOR_TEMP,
        note="fn=3 DIMMER_COLOR_TEMP: brightness+colortemp auto-created",
    ),
    # 7 — shade with position+angle (group 2, fn=2 POSITIONAL, chs 11+13)
    DeviceConfig(
        name="PG2_Shades_PosAngle",
        color_class=ColorClass.GREY,
        output_group=int(ColorGroup.GREY),
        output_function=OutputFunction.POSITIONAL,
        channel_types=[
            OutputChannelType.SHADE_POSITION_OUTSIDE,
            OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
        ],
        note="fn=2 POSITIONAL: shadePositionOutside (11) + shadeOpeningAngleOutside (13)",
    ),
    # 8 — full colour light (group 1, fn=4 FULL_COLOR_DIMMER)
    DeviceConfig(
        name="PG1_FullColour",
        color_class=ColorClass.YELLOW,
        output_group=int(ColorGroup.YELLOW),
        output_function=OutputFunction.FULL_COLOR_DIMMER,
        note="fn=4 FULL_COLOR_DIMMER: brightness+hue+sat+cct+x+y auto-created",
    ),
    # 9 — internally controlled joker (group 8, fn=6, powerState ch 53)
    DeviceConfig(
        name="PG8_InternalControl",
        color_class=ColorClass.BLACK,
        output_group=int(ColorGroup.BLACK),
        output_function=OutputFunction.INTERNALLY_CONTROLLED,
        channel_types=[OutputChannelType.POWER_STATE],
        note="fn=6 INTERNALLY_CONTROLLED: powerState (53)",
    ),
]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8444
STATE_FILE = Path("/tmp/pydsvdcapi_matrix_test.yaml")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
ANSI_GREY = "\033[90m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RED = "\033[91m"


class ColourFormatter(logging.Formatter):
    LEVEL_COLOURS = {
        logging.DEBUG: ANSI_GREY,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self.LEVEL_COLOURS.get(record.levelno, "")
        ts = self.formatTime(record, "%H:%M:%S")
        return f"{ANSI_GREY}{ts}{RESET} {colour}{record.getMessage()}{RESET}"


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
# Per-device runtime state
# ---------------------------------------------------------------------------


@dataclass
class DeviceRuntime:
    cfg: DeviceConfig
    device: Device
    vdsd: Vdsd
    output: Output
    channel: OutputChannel | None


# ---------------------------------------------------------------------------
# Build one device
# ---------------------------------------------------------------------------


def build_device(vdc: Vdc, cfg: DeviceConfig) -> DeviceRuntime:
    dsuid = DsUid.from_name_in_space(cfg.name, DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    hw_suffix = abs(hash(cfg.name)) % 0xFF
    vdsd_kwargs: dict = dict(
        device=device,
        subdevice_index=0,
        name=cfg.name,
        model=f"pyVDC-GroupTest-{cfg.name}",
        model_version="1.0.0",
        vendor_name="pyDSvDCAPI",
        vendor_guid="gs1:(01)0000000000000",
        hardware_guid=f"mac-address:00:11:22:33:44:{hw_suffix:02x}",
        hardware_model_guid="ean:(01)0000000000001",
        primary_group=cfg.color_class,
        zone_id=0,
    )
    if cfg.gtin is not None:
        vdsd_kwargs["oem_model_guid"] = cfg.gtin

    vdsd = Vdsd(**vdsd_kwargs)
    device.add_vdsd(vdsd)

    # Output — function and channel follow ds-basics Tables 6 & 7
    output = Output(
        vdsd=vdsd,
        function=cfg.output_function,
        name="output",
        mode=OutputMode.DEFAULT,
        default_group=cfg.output_group,
        active_group=cfg.output_group,
        groups={cfg.output_group},
    )
    for idx, ct in enumerate(cfg.channel_types):
        output.add_channel(ct, ds_index=idx)
    vdsd.set_output(output)

    # Initialise ALL channels to their midpoint so the dSS never sees NULL.
    for ch in output.channels.values():
        spec = CHANNEL_SPECS.get(ch.channel_type)
        if spec is not None:
            mid = round((spec.min_value + spec.max_value) / 2.0, 2)
        else:
            mid = 0.0
        ch.set_value_from_vdsm(mid)
        ch.confirm_applied()  # mark initial value as hardware-confirmed (age != null)

    # Bind the primary channel for later push.
    channel: OutputChannel | None = output.get_channel(0)

    # Log inbound value changes from the dSS.
    device_name = cfg.name  # close over for the callback

    async def on_applied(out: Output, updates: dict) -> None:
        for ch_type, val in updates.items():
            info(f"{YELLOW}SET{RESET}  {device_name}  {ch_type.name}={val:.2f}")

    output.on_channel_applied = on_applied

    # Manually add any extra features specified in the config
    # (e.g. heatingoutmode/pwmvalue for POSITIONAL heating — derivation
    # only auto-adds these for ON_OFF, but HEATING_POWER requires POSITIONAL).
    for feat in cfg.extra_features:
        vdsd.add_model_feature(feat)
    # highlevel is only meaningful for joker (BLACK/group-8) devices.
    if cfg.color_class == ColorClass.BLACK:
        vdsd.add_model_feature("highlevel")
    vdsd.derive_model_features()

    return DeviceRuntime(
        cfg=cfg, device=device, vdsd=vdsd, output=output, channel=channel
    )


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


async def interactive_loop(runtimes: list[DeviceRuntime]) -> None:
    loop = asyncio.get_running_loop()

    print(f"\n{BOLD}{CYAN}Interactive loop started.{RESET}")
    print("  q      → quit\n")

    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = raw.strip().lower()

        if cmd == "q":
            info("Quitting…")
            break


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    setup_logging()

    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
            info(f"Removed leftover {p}")

    # ---- Build host + VDC ------------------------------------------
    host = VdcHost(
        port=args.port,
        model="pyVDC Group+Channel Tester",
        name="group-channel-test-host",
        vendor_name="pyDSvDCAPI",
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-group-channel-test",
        name="Group+Channel Test vDC",
        model="pydsvdcapi-group-channel-tester",
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    # ---- Build all devices ------------------------------------------
    runtimes: list[DeviceRuntime] = []
    for cfg in DEVICES:
        rt = build_device(vdc, cfg)
        runtimes.append(rt)

    # ---- Print summary table ----------------------------------------
    info(f"{BOLD}Device matrix:{RESET}")
    hdr = f"  {'#':<2}  {'Name':<26}  {'ColorClass':<18}  {'Fn':>2}  {'Channel':<28}  {'GTIN'}"
    info(hdr)
    info(f"  {'─' * 2}  {'─' * 26}  {'─' * 18}  {'─' * 2}  {'─' * 28}  {'─' * 24}")
    for i, rt in enumerate(runtimes, 1):
        c = rt.cfg
        fn = int(c.output_function)
        ch = (
            "+".join(ct.name for ct in c.channel_types) if c.channel_types else "(auto)"
        )
        gtin = c.gtin or "(none)"
        info(
            f"  {i:<2}  {c.name:<26}  {c.color_class.name:<18}  {fn:>2}  {ch:<28}  {gtin}"
        )
    info("")
    info("  Notes:")
    for i, rt in enumerate(runtimes, 1):
        info(f"    {i}. {rt.cfg.note}")
    info("")
    info(
        f"dynamicDefinitions=True · {len(runtimes)} devices covering fn=1,2,3,4,6 and multi-channel configs"
    )
    info("")

    # ---- Start host and wait for session ----------------------------
    await host.start()
    info(f"Listening on port {args.port} — waiting for vdSM/dSS connection…")
    await wait_for_session(host, timeout=120.0)

    # ---- Announce all devices ---------------------------------------
    for rt in runtimes:
        await rt.device.announce(host.session)
        features = sorted(rt.vdsd.model_features)
        info(
            f"{GREEN}Announced{RESET}  {rt.cfg.name}  "
            f"dSUID={rt.vdsd.dsuid}  "
            f"primaryGroup={int(rt.cfg.color_class)}  "
            f"modelFeatures=[{', '.join(features) if features else '—'}]"
        )

    info("")
    info(f"{BOLD}All {len(runtimes)} devices announced.{RESET}")
    info("  1. Check which groups/tabs devices appear in (dSS room view)")
    info("  2. Verify channel counts match expectations per OutputFunction")
    info("")

    # ---- Initial channel value push (all channels) -----------------
    for rt in runtimes:
        for ch in rt.output.channels.values():
            spec = CHANNEL_SPECS.get(ch.channel_type)
            mid = round((spec.min_value + spec.max_value) / 2.0, 2) if spec else 0.0
            await ch.update_value(mid)
        info(
            f"{CYAN}CHANNEL{RESET}  {rt.cfg.name}  "
            f"pushed {len(rt.output.channels)} ch(s) initial values"
        )

    # ---- Interactive loop -------------------------------------------
    await interactive_loop(runtimes)

    # ---- Cleanup ----------------------------------------------------
    for rt in runtimes:
        await rt.device.vanish(host.session)
    await host.stop()
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
    info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
