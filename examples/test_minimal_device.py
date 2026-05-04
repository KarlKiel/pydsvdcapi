#!/usr/bin/env python3
"""Minimal VDC device — no model features, group 1, fn=0 ON_OFF, ch=brightness, value=50.

Usage::

    python examples/test_minimal_device.py [--port PORT]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from pydsvdcapi import (
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
from pydsvdcapi.enums import ColorClass, OutputUsage

DEFAULT_PORT = 8444
STATE_FILE = Path("/tmp/pydsvdcapi_minimal_test.yaml")

RESET = "\033[0m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
ANSI_GREY = "\033[90m"
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


async def wait_for_session(host: VdcHost, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while host.session is None or not host.session.is_active:
        if time.monotonic() > deadline:
            raise TimeoutError(f"No vdSM/dSS connected within {timeout:.0f}s")
        await asyncio.sleep(0.5)
    info(f"{GREEN}Session established with vdSM{RESET}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    setup_logging()

    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
            info(f"Removed leftover {p}")

    host = VdcHost(
        port=args.port,
        model="pyVDC Minimal Tester",
        name="minimal-test-host",
        vendor_name="pyDSvDCAPI",
        state_path=STATE_FILE,
    )

    vdc = Vdc(
        host=host,
        implementation_id="x-pydsvdcapi-minimal-test",
        name="Minimal Test vDC",
        model="pydsvdcapi-minimal-tester",
        capabilities=VdcCapabilities(
            metering=False,
            identification=True,
            dynamic_definitions=True,
        ),
    )
    host.add_vdc(vdc)

    # ---- Build the one device ----------------------------------------
    dsuid = DsUid.from_name_in_space("MinimalDevice", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=dsuid)

    vdsd = Vdsd(
        device=device,
        subdevice_index=0,
        name="MinimalDevice",
        model="pyVDC-Minimal",
        model_version="1.0.0",
        vendor_name="pyDSvDCAPI",
        vendor_guid="gs1:(01)0000000000000",
        hardware_guid="mac-address:00:11:22:33:44:01",
        hardware_model_guid="ean:(01)0000000000001",
        primary_group=ColorClass.YELLOW,  # primaryGroup=1
        zone_id=0,
    )
    device.add_vdsd(vdsd)

    # fn=0 ON_OFF — auto-creates brightness channel (type 1)
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.ON_OFF,
        mode=OutputMode.DEFAULT,
        output_usage=OutputUsage.UNDEFINED,
        name="output",
        default_group=1,
        active_group=1,
        groups={1},
    )
    vdsd.set_output(output)

    # Initialise brightness to 50 so dSS never sees NULL.
    # Override resolution to 1.0 (instead of 100/255 ≈ 0.392).
    ch = output.get_channel(0)
    if ch is not None:
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()  # mark initial value as hardware-confirmed (age != null)
        ch.resolution = 1.0

    # Log inbound SET commands.
    async def on_applied(out: Output, updates: dict) -> None:
        for ch_type, val in updates.items():
            info(f"{YELLOW}SET{RESET}  MinimalDevice  {ch_type.name}={val:.2f}")

    output.on_channel_applied = on_applied

    # Add outvalue8 explicitly before announcing.
    vdsd.add_model_feature("outvalue8")

    # Auto-derive model features from the configured output/inputs.
    vdsd.derive_model_features()
    derived = sorted(vdsd.model_features)
    info(
        f"{CYAN}FEATURES{RESET}  MinimalDevice  "
        f"auto-derived: [{', '.join(derived) if derived else '—'}]"
    )

    # ---- Start -------------------------------------------------------
    await host.start()
    info(f"Listening on port {args.port} — waiting for vdSM/dSS connection…")
    await wait_for_session(host, timeout=120.0)

    await device.announce(host.session)
    features = sorted(vdsd.model_features)
    info(
        f"{GREEN}Announced{RESET}  MinimalDevice  "
        f"dSUID={vdsd.dsuid}  "
        f"primaryGroup=1  fn=0  ch=brightness  "
        f"modelFeatures=[{', '.join(features) if features else '—'}]"
    )

    # Push initial value.
    if ch is not None:
        await ch.update_value(50.0)
        info(f"{CYAN}CHANNEL{RESET}  MinimalDevice  brightness → 50.0")

    # ---- Interactive loop --------------------------------------------
    loop = asyncio.get_running_loop()
    print(f"\n{BOLD}{CYAN}Interactive loop started.{RESET}")
    print("  q  → quit\n")
    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        if raw.strip().lower() == "q":
            info("Quitting…")
            break

    # ---- Cleanup -----------------------------------------------------
    await device.vanish(host.session)
    await host.stop()
    for p in [STATE_FILE, STATE_FILE.with_suffix(".yaml.bak")]:
        if p.exists():
            p.unlink()
    info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
