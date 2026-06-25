# pydsvdcapi — Developer Guide

## 1. Introduction

pydsvdcapi is a Python library for building **virtual Device Connectors (vDCs)** — software
bridges that make custom hardware or cloud services appear as native devices in a
digitalSTROM smart home installation.

### What is digitalSTROM?

digitalSTROM (dS) is a home-automation system based on powerline communication (230 V wiring
in walls). Every controllable device in a dS installation — a light, a blind, a thermostat —
is represented on the **dSS** (digitalSTROM server) as a logical entity with a stable unique ID,
zone assignment, scene memory, and group membership.

The system is entirely local: no cloud, no subscriptions. The dSS coordinates all communication
through the bus coupler firmware (vdSM) that runs inside the dSS box.

### What is the vDC API?

The **vDC API** is the protobuf-over-TCP protocol that lets software-defined devices join a dS
installation without any powerline hardware. A process implementing the vDC API announces
virtual devices to the vdSM, receives commands (scene calls, output value changes), and pushes
state updates back. From the dSS's point of view, vDC devices are indistinguishable from real
hardware devices.

The protocol defines three first-class entities:

| Entity | Role |
|--------|------|
| **vDChost** | The gateway process (one per machine/process). Owns the TCP socket. |
| **vDC** | A logical connector that groups related devices (one per integration type). |
| **vdSD** | A single virtual device, the smallest addressable unit. |

### What can you build with pydsvdcapi?

- An IP-to-dS bridge for lights, thermostats, smart plugs, or window actuators
- A MQTT, ZigBee, Z-Wave, KNX, or Modbus gateway into digitalSTROM
- A virtual "device" that represents a web service or cloud API
- Test harnesses and simulation drivers for dS integration testing

---

## 2. Installation

```bash
pip install pydsvdcapi
```

Requires Python ≥ 3.10.

For development (tests, linting, type checking):

```bash
pip install "pydsvdcapi[dev]"
```

For building the documentation:

```bash
pip install "pydsvdcapi[docs]"
make -C docs html
```

---

## 3. Quick Start

The minimal skeleton to get a dimmable light visible on the dSS:

```python
import asyncio
from pydsvdcapi import (
    VdcHost, Vdc, Device, Vdsd,
    DsUid,
    Output, OutputFunction, OutputMode, OutputUsage,
    ColorGroup, DeviceLifecycleState,
)


async def main():
    # 1. Gateway entity — one per process
    host = VdcHost(
        name="My Python Gateway",
        state_path="state.yaml",  # persist across restarts
    )

    # 2. Logical connector — one per integration type
    vdc = Vdc(
        implementation_id="x-myapp-lights",
        name="My Lights",
        model="Python Light Controller",
    )
    host.add_vdc(vdc)

    # 3. Physical device and its virtual representation
    device = Device(dsuid=DsUid.new_gtin_based("0000000000001", 0))
    vdsd = Vdsd(
        dsuid=DsUid.new_uuid_based(),
        name="Living Room Light",
    )

    # 4. Output: the single controllable output of this device
    output = Output(
        function=OutputFunction.DIMMER,
        mode=OutputMode.PWM,
        usage=OutputUsage.ROOM,
        group=ColorGroup.YELLOW,   # yellow = light group
    )
    vdsd.set_output(output)

    # 5. React to dSS commands
    brightness = output.channels["brightness"]

    @brightness.on_apply
    async def apply_brightness(value: float) -> None:
        print(f"Set brightness to {value:.1f}%")
        # → send to your physical hardware here

    # 6. React to identify (user touches device in configurator)
    async def on_identify(v: Vdsd) -> None:
        print(f"Identify: {v.name}")
    vdsd.on_identify = on_identify

    # 7. Report device health
    await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

    # 8. Assemble and run
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    await host.run()   # connects to dSS, blocks until stopped


asyncio.run(main())
```

The host will:

- Register itself via mDNS so the vdSM on the dSS can find it automatically
- Accept the TCP connection and perform the `hello` handshake
- Announce the vDC and all devices
- Dispatch incoming commands to your callbacks
- Push state changes to the dSS when you update a channel value
- Persist the device tree to `state.yaml` on any configuration change

---
