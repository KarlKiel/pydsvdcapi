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
    DsUid, DsUidNamespace,
    Output, OutputFunction, OutputMode, OutputUsage,
    ColorGroup,
)

async def main():
    host = VdcHost(dsuid=DsUid.new_uuid_based(), name="My VDC Host")

    vdc = Vdc(dsuid=DsUid.new_uuid_based(), name="My VDC")
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

    await host.run()  # connects and blocks until stopped

asyncio.run(main())
```

See [`examples/getting_started.py`](examples/getting_started.py) for a minimal runnable example
and [`examples/full_showcase.py`](examples/full_showcase.py) for all 27 device classes.

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

API reference: [pydsvdcapi.readthedocs.io](https://pydsvdcapi.readthedocs.io)

Domain documentation lives in [`docs/`](docs/):
- [vDC API Properties](docs/vdc-api-properties.md)
- [VDC Host Behavior](docs/vdc-host-behavior.md)
- [Device Splitting Guidelines](docs/device-splitting-guidelines.md)

## License

GPLv3 — see [LICENSE](LICENSE).
