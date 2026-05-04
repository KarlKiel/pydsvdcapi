#!/usr/bin/env python3
"""Minimal pydsvdcapi example — one VDC, one switchable light.

Usage:
    python examples/getting_started.py [--port PORT] [--debug]

The VDC connects on the given port (default: 8340) and announces
a single yellow light device.  Press Ctrl-C to stop.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from pydsvdcapi import (
    ColorGroup,
    Device,
    DsUid,
    Output,
    OutputFunction,
    OutputMode,
    OutputUsage,
    Vdc,
    VdcHost,
    Vdsd,
)


async def main(port: int) -> None:
    host = VdcHost(dsuid=DsUid.new_uuid_based(), name="Getting Started Host")

    vdc = Vdc(dsuid=DsUid.new_uuid_based(), name="Getting Started VDC")
    host.add_vdc(vdc)

    device = Device(dsuid=DsUid.new_gtin_based("0000000000001", 0))
    vdsd = Vdsd(dsuid=DsUid.new_uuid_based(), name="My Light")

    output = Output(
        function=OutputFunction.LIGHT,
        mode=OutputMode.SWITCH,
        usage=OutputUsage.ROOM,
        group=ColorGroup.YELLOW,
    )
    vdsd.set_output(output)
    device.add_vdsd(vdsd)
    vdc.add_device(device)

    logging.info("Starting VDC host on port %d — press Ctrl-C to stop", port)
    await host.run(port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pydsvdcapi getting-started example")
    parser.add_argument("--port", type=int, default=8340)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(main(args.port))
