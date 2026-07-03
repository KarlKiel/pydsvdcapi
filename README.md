# pydsvdcapi

[![CI](https://github.com/KarlKiel/pyDSvDCAPI/actions/workflows/ci.yml/badge.svg)](https://github.com/KarlKiel/pyDSvDCAPI/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pydsvdcapi)](https://pypi.org/project/pydsvdcapi/)
[![Python](https://img.shields.io/pypi/pyversions/pydsvdcapi)](https://pypi.org/project/pydsvdcapi/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Python library for the **digitalSTROM virtual Device Connector (vDC) API**.

## What this library does

- Implements the full vDC protobuf protocol over TCP
- Manages the session lifecycle (hello/pong, announcement, reconnect)
- Models all device classes: lights, blinds, sensors, buttons, heating, audio, and more
- Provides a composable API: `VdcHost` → `Vdc` → `Vdsd` → components
- Persists device state across restarts via a YAML property store
- Automatically derives `modelFeatures` flags from configured components
- Supports value converters for uplink/downlink data transformation

## Installation

```bash
pip install pydsvdcapi
```

Requires Python 3.10+.

## Quick start

```python
import asyncio
from pydsvdcapi import (
    VdcHost, Vdc, Device, Vdsd,
    DsUid,
    Output, OutputFunction, OutputUsage,
    ColorGroup, DeviceLifecycleState,
)

async def main():
    host = VdcHost(name="My Gateway", state_path="state.yaml")

    vdc = Vdc(host=host, implementation_id="x-myapp-lights",
              name="My Lights", model="Light Controller")
    host.add_vdc(vdc)

    device = Device(vdc=vdc, dsuid=DsUid.from_gtin_serial("0000000000001", "001"))
    vdsd = Vdsd(device=device, primary_group=ColorGroup.YELLOW,
                name="Living Room Light", model="My Light v1")
    output = Output(vdsd=vdsd, function=OutputFunction.DIMMER,
                    output_usage=OutputUsage.ROOM)
    vdsd.set_output(output)

    async def apply_channels(out: Output, updates: dict) -> None:
        if 0 in updates:  # brightness = dsIndex 0
            print(f"Set brightness to {updates[0]:.1f}%")
    output.on_channel_applied = apply_channels

    await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    await host.start()
    await asyncio.Event().wait()

asyncio.run(main())
```

See the [Developer Guide](docs/guide.md) for a full walkthrough and API reference.

## Development

```bash
git clone https://github.com/KarlKiel/pyDSvDCAPI.git
cd pyDSvDCAPI
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

| Command | Purpose |
|---|---|
| `python -m pytest` | Run tests |
| `ruff check src/ tests/` | Lint |
| `ruff format src/ tests/` | Format |
| `mypy src/pydsvdcapi` | Type-check |

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidance.

## Documentation

- [Developer Guide](docs/guide.md) — introductory walkthrough and full API reference
- API reference: [pydsvdcapi.readthedocs.io](https://pydsvdcapi.readthedocs.io)

## License

GPLv3 — see [LICENSE](LICENSE).
