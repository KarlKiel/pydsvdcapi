# pydsvdcapi — Developer Guide

## Contents

1. [Introduction](#1-introduction)
2. [DsUid — Unique Identifiers](#2-dsuid--unique-identifiers)
   - [The three protocol artefacts](#the-three-protocol-artefacts)
   - [Device: grouping vdSDs by hardware identity](#device-grouping-vdsds-by-hardware-identity)
3. [Architecture](#3-architecture)
4. [Installation](#4-installation)
5. [Quick Start](#5-quick-start)
6. [VdcHost Reference](#6-vdchost-reference)
7. [Vdc Reference](#7-vdc-reference)
8. [Device and Vdsd Reference](#8-device-and-vdsd-reference)
9. [Output Reference](#9-output-reference)
10. [Output Channels Reference](#10-output-channels-reference)
11. [BinaryInput Reference](#11-binaryinput-reference)
12. [ButtonInput Reference](#12-buttoninput-reference)
13. [SensorInput Reference](#13-sensorinput-reference)
14. [Model Features Reference](#14-model-features-reference)
15. [Dynamic Features](#15-dynamic-features)
    - [Prerequisites](#prerequisites)
    - [State evaluation gap](#state-evaluation-gap)
16. [Device States Reference](#16-device-states-reference)
17. [Device Events Reference](#17-device-events-reference)
18. [Device Properties Reference](#18-device-properties-reference)
19. [Device Actions Reference](#19-device-actions-reference)
20. [Generic Framework GTIN](#20-generic-framework-gtin)
21. [Device Template Catalogue](#21-device-template-catalogue)
    - [Template family reference](#template-family-reference)
    - [Full walkthrough — washing machine](#full-walkthrough--washing-machine)
22. [Device Lifecycle](#section-22-device-lifecycle)
23. [Persistence (PropertyStore)](#section-23-persistence-propertystore)
24. [Value Converters](#section-24-value-converters)
25. [Device Templates (library)](#section-25-device-templates)
26. [Session Constants](#section-26-session-constants)

---

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

The protocol defines three first-class entities, each identified in the dSS by its own
dSUID (see [Section 2](#2-dsuid--unique-identifiers)):

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

## 2. DsUid — Unique Identifiers

Every entity that the digitalSTROM system tracks is identified by a stable **17-byte
dSUID** (digitalSTROM Unique Identifier). The dSS persists all scene assignments, zone
memberships, group configurations, and automation rules under the dSUID — so the same
dSUID must be reused across restarts for the dSS to recognise a device as the same
object it already knows.

### The three protocol artefacts

The vDC API announces three entity types to the vdSM, each with its own dSUID:

| Entity | Library class | dSUID assigned by |
|--------|--------------|-------------------|
| **vDChost** | `VdcHost` | Derived automatically from the host machine's MAC address (or set explicitly) |
| **vDC** | `Vdc` | Derived automatically from `implementation_id` + host MAC |
| **vdSD** | `Vdsd` | Your code — choose from the factory methods below |

pydsvdcapi manages the vDChost and vDC dSUIDs automatically. **Your only responsibility
is to supply stable, persistent dSUIDs for your `Vdsd` instances.**

### Device: grouping vdSDs by hardware identity

pydsvdcapi introduces a fourth object, `Device`, which has **no protocol identity of its
own** — it is a library-level grouping for one or more `Vdsd` instances that represent
the same physical piece of hardware. The hardware's identity is captured in the dSUID:

- All `Vdsd` instances within one `Device` share the same **base UUID (bytes 0–15)**.
- Each `Vdsd` has a unique **sub-device index** in byte 17 (zero-based index 16).

```python
base = DsUid.from_gtin_serial("07640156791013", "SN001")
# Two relay outputs on the same hardware unit:
relay_0 = base.derive_subdevice(0)
relay_1 = base.derive_subdevice(1)
```

The dSS treats sibling sub-devices as logically related and groups them in the
configurator under the same hardware object.

### dSUID format

The canonical string form is **34 upper-case hex characters**, e.g.
`"198C033E330755E78015F97AD093DD1C00"`. The first 16 bytes encode a UUID or EPC96
identifier; byte 17 (index 16, zero-based) is the sub-device index.

### Factory methods

| Method | Use case |
|--------|----------|
| `DsUid.from_string(value)` | Parse from a 34-hex or UUID-with-dashes string |
| `DsUid.from_bytes(data)` | Parse from 17 raw bytes |
| `DsUid.from_uuid(uuid_obj, subdevice_index=0)` | Wrap an existing `uuid.UUID` |
| `DsUid.from_name_in_space(name, namespace, subdevice_index=0)` | UUIDv5 from name + namespace (general purpose) |
| `DsUid.from_gtin_serial(gtin, serial, subdevice_index=0)` | UUIDv5 from GTIN + serial number (SGTIN-128 in the GS1-128 namespace) |
| `DsUid.from_sgtin96(gcp, item_ref, partition, serial, subdevice_index=0)` | Direct SGTIN-96 binary encoding |
| `DsUid.from_gid96(manager, object_class, serial, subdevice_index=0)` | Legacy GID-96 encoding |
| `DsUid.from_mac_gid96(mac, subdevice_index=0)` | Legacy GID-96 derived from a MAC address |
| `DsUid.from_vdc_mac(mac, subdevice_index=0)` | UUIDv5 from MAC in the vDC namespace |
| `DsUid.from_enocean(address, subdevice_index=0)` | UUIDv5 from an EnOcean 32-bit device address |
| `DsUid.random(subdevice_index=0)` | Random UUIDv4-based dSUID (last resort — **must be persisted**) |

### Sub-device derivation

```python
base = DsUid.from_gtin_serial("07640156791013", "SN001")
button0 = base.derive_subdevice(0)  # same base, index 0
button1 = base.derive_subdevice(1)
button2 = base.derive_subdevice(2)
button3 = base.derive_subdevice(3)
```

**`derive_subdevice(index)`** returns a new `DsUid` with the same base UUID (bytes
0–15) but a different sub-device index byte. This is the canonical way to build
sibling vdSDs from a single hardware dSUID.

### DsUidNamespace

Well-known namespace UUIDs for use with `from_name_in_space`:

| Constant | Namespace |
|----------|-----------|
| `DsUidNamespace.GS1_128` | SGTIN-128 strings (used internally by `from_gtin_serial`) |
| `DsUidNamespace.ENOCEAN` | EnOcean device addresses |
| `DsUidNamespace.VDC` | vDC dSUIDs derived from MAC |
| `DsUidNamespace.VDSM` | vdSM dSUIDs derived from MAC |

### Selection guide

- **Hardware with a GTIN (EAN barcode) and a serial number** → `from_gtin_serial`
- **GTIN-only hardware (no individual serial)** → `from_gtin_serial` with a fixed
  placeholder serial, or `from_sgtin96` with the raw EPC components
- **You already have a UUID** → `from_uuid`
- **Any unique string ID** → `from_name_in_space` with a custom namespace UUID
- **EnOcean device** → `from_enocean`
- **No unique hardware ID / prototype** → `random()` — but **persist** the result to
  `state_path` or another store so the same dSUID is reused across restarts

> **Note on GTIN and VdcDb:** The GTIN embedded in a dSUID via `from_gtin_serial()`
> is used only for stable unique identification. The dSS firmware database (VdcDb) is
> keyed by `vdsd.oem_model_guid`, not by the dSUID GTIN. See
> [Dynamic Features](#15-dynamic-features) and
> [Device Template Catalogue](#21-device-template-catalogue) for details.

---

## 3. Architecture

### Entity hierarchy

All three protocol entities — vDChost, vDC, and vdSD — carry their own dSUID (see
[Section 2](#2-dsuid--unique-identifiers)) and are announced individually to the vdSM.
`Device` is a library-only grouping with no protocol identity:

```
VdcHost  — gateway process; dSUID derived from MAC address      [protocol entity]
└── Vdc  — logical connector; dSUID derived from impl. ID + MAC [protocol entity]
    └── Device  — hardware grouping; no dSUID, not known to dSS [library only]
        └── Vdsd  — virtual device; dSUID = base + sub-index    [protocol entity]
```

### Device vs Vdsd

A `Device` groups one or more `Vdsd` instances that represent the same physical piece
of hardware. The relationship is encoded directly in the dSUID:

- All `Vdsd` instances within a `Device` share the same base UUID (bytes 0–15) —
  taken from the `Device`'s own dSUID.
- Each `Vdsd` has a unique sub-device index in byte 17, making it independently
  addressable by the dSS.

Example: a two-relay irrigation controller. Both relays share the hardware's
GTIN + serial dSUID base and differ only in sub-device index:

```python
base = DsUid.from_gtin_serial("07640156791013", "SN001")
device = Device(vdc=vdc, dsuid=base)
relay_a = Vdsd(device=device, ...)                            # dSUID: base + index 0
relay_b = Vdsd(device=device, subdevice_index=1, ...)         # dSUID: base + index 1
```

The dSS sees `relay_a` and `relay_b` as two independent addressable devices that happen
to share a hardware identity.

### Naming quick reference

| Class | Role |
|-------|------|
| `VdcHost` | Gateway process; owns the TCP socket; announced with its own dSUID |
| `Vdc` | Logical connector (one per integration type); announced with its own dSUID |
| `Device` | Library grouping for one piece of hardware; **not known to the dSS** |
| `Vdsd` | A single virtual device; announced with dSUID = Device base + sub-device index |

---

## 4. Installation

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

## 5. Quick Start

The minimal skeleton to get a dimmable light visible on the dSS:

```python
import asyncio
from pydsvdcapi import (
    VdcHost, Vdc, Device, Vdsd,
    DsUid,
    Output, OutputFunction, OutputUsage,
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
        host=host,
        implementation_id="x-myapp-lights",
        name="My Lights",
        model="Python Light Controller",
    )
    host.add_vdc(vdc)

    # 3. Hardware device (base dSUID) and its virtual representation
    device = Device(vdc=vdc, dsuid=DsUid.from_gtin_serial("0000000000001", "001"))
    vdsd = Vdsd(
        device=device,
        primary_group=ColorGroup.YELLOW,   # yellow = light group
        name="Living Room Light",
        model="My Light v1",
    )

    # 4. Output: the single controllable output of this device
    output = Output(
        vdsd=vdsd,
        function=OutputFunction.DIMMER,
        output_usage=OutputUsage.ROOM,
    )
    vdsd.set_output(output)

    # 5. React to dSS commands (updates: {dsIndex: value}, brightness = dsIndex 0)
    async def apply_channels(out: Output, updates: dict) -> None:
        if 0 in updates:
            print(f"Set brightness to {updates[0]:.1f}%")
            # → send to your physical hardware here
    output.on_channel_applied = apply_channels

    # 6. React to identify (user touches device in configurator)
    async def on_identify(v: Vdsd) -> None:
        print(f"Identify: {v.name}")
    vdsd.on_identify = on_identify

    # 7. Set initial device health
    await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

    # 8. Assemble and run
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    await host.start()           # start TCP server + DNS-SD announce
    await asyncio.Event().wait() # run forever (until process is killed)


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


---

## 6. VdcHost Reference

`VdcHost` is the top-level entity. It opens the TCP server socket that the vdSM
connects to and registers the service via mDNS/DNS-SD so vdSMs can discover it
automatically.

### Constructor

All parameters are keyword-only.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `name` | `"vDC host on <hostname>"` | User-facing name |
| `model` | `"pydsvdcapi vDC host"` | Human-readable model description |
| `model_version` | `None` | Firmware / version string |
| `model_uid` | auto-derived | System-unique functional model ID (derived from `model` when omitted) |
| `mac` | auto-detected | MAC address string; used to derive the dSUID and `hardwareGuid` |
| `port` | `8444` | TCP port |
| `dsuid` | auto-derived | Explicit dSUID (derived from `mac` when omitted) |
| `hardware_version` | `None` | Hardware version string |
| `hardware_guid` | `"macaddress:<MAC>"` | Native hardware GUID; auto-derived from `mac` when omitted |
| `hardware_model_guid` | `None` | Native hardware model GUID |
| `vendor_name` | `None` | Human-readable vendor name |
| `vendor_guid` | `None` | Globally unique vendor identifier |
| `oem_guid` | `None` | OEM product GUID |
| `oem_model_guid` | `None` | OEM product-model GUID |
| `config_url` | `None` | URL to web configuration interface |
| `device_icon_16` | `None` | 16×16 PNG icon as `bytes` |
| `device_icon_name` | `None` | Icon filename for caching |
| `state_path` | `None` | YAML persistence path; enables auto-save when given |
| `watchdog_timeout` | `90.0` | Session watchdog timeout in seconds |

### vDC management methods

- **`add_vdc(vdc)`** — register a `Vdc` with the host.
- **`remove_vdc(dsuid)`** — remove a `Vdc`; schedules `VDC_SEND_VANISH` for all its
  vdSDs.
- **`get_vdc(dsuid)`** — look up a `Vdc` by dSUID; returns `None` if not found.
- **`vdcs`** — read-only property returning `dict[str, Vdc]` keyed by dSUID string.

### Lifecycle methods

```python
await host.start(
    on_remove=...,
    on_identify=...,
    announce=True,          # register DNS-SD service immediately
    bind_address="0.0.0.0", # network interface to bind
)
# ... wait forever (or until a shutdown signal) ...
await asyncio.Event().wait()
# ...
await host.stop()
```

- **`async start(*, on_message, on_remove, on_identify, on_pair, on_authenticate, on_firmware_upgrade, on_set_configuration, on_disconnect, announce=True, bind_address="0.0.0.0")`**
  — start the TCP server and optionally announce via DNS-SD. Accepts all event
  callbacks described below.

- **`async stop()`** — ordered shutdown: flush auto-save → unannounce DNS-SD →
  close session → stop server.

- **`flush()`** — force an immediate persist of pending changes (e.g. before an
  external shutdown signal).

### Auto-save

When `state_path` is set, mutations to any tracked attribute (`name`, `model`,
`model_version`, `model_uid`, `hardware_version`, `hardware_guid`,
`hardware_model_guid`, `vendor_name`, `vendor_guid`, `oem_guid`, `oem_model_guid`,
`config_url`, `device_icon_name`) are debounced and written to YAML within ~1 s.
Rapid successive changes are coalesced into a single write.

### Callbacks (`start` parameters)

| Callback | Signature | Notes |
|----------|-----------|-------|
| `on_remove` | `(dsuid: str) -> bool` | Return `True` to allow removal, `False` to reject (`ERR_FORBIDDEN`). `None` means always allow. |
| `on_identify` | `(dsuid: str) -> None` | Host-level identify (e.g. LED blink). For device-level, set `Vdsd.on_identify` instead. |
| `on_pair` | `(dsuid, establish, timeout, params) -> None` | Learn-in / learn-out |
| `on_authenticate` | `(dsuid, auth_data, auth_scope, params) -> None` | Authentication |
| `on_firmware_upgrade` | `(dsuid, check_only, clear_settings, params) -> None` | OTA update |
| `on_set_configuration` | `(dsuid, config_id, params) -> None` | Configuration change |
| `on_disconnect` | `(host, reason) -> None` | Called on unexpected connection loss; `reason` is the exception or `None` for a clean EOF |

---


---

## 7. Vdc Reference

`Vdc` is the logical connector that groups related virtual devices of the implementation purpose(e.g. for a device bridge, or a dedicated device) Normally, there will be only one Vdc implemented per VdcHost - Nevertheless, the library also supports several Vdc implementations on one host.

### Constructor

All parameters are keyword-only. `host`, `implementation_id`, `name`, and `model`
are required; `name` and `model` must be non-empty strings.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | — | Owning `VdcHost` |
| `implementation_id` | — | Stable unique ID for this integration; used to derive the vDC dSUID. Non-digitalSTROM implementations should use an `"x-company-"` prefix. |
| `name` | — | User-facing name (required) |
| `model` | — | Human-readable model description (required) |
| `model_version` | `None` | Version string |
| `model_uid` | auto-derived | Derived deterministically from `model` when omitted |
| `hardware_version` | `None` | Hardware version string |
| `hardware_guid` | `None` | Native hardware GUID in `schema:id` format |
| `hardware_model_guid` | `None` | Native hardware model GUID |
| `vendor_name` | `None` | Human-readable vendor name |
| `vendor_id` | `None` | Short vendor identifier (e.g. `enoceanvendor:002:Themokon`) |
| `vendor_guid` | `None` | Globally unique vendor identifier |
| `oem_guid` | `None` | OEM product GUID |
| `oem_model_guid` | `None` | OEM product-model GUID |
| `config_url` | `None` | URL to web configuration interface |
| `device_icon_16` | `None` | 16×16 PNG icon as `bytes` |
| `device_icon_name` | `None` | Icon filename for caching |
| `descriptions_group` | `None` | dSS configurator UI database group ID |
| `descriptions_class` | `None` | dSS configurator UI database class ID |
| `device_class` | `None` | digitalSTROM device class profile name |
| `device_class_version` | `None` | Revision of the device class profile |
| `template_path` | `None` | Path for storing/loading device templates |
| `capabilities` | `VdcCapabilities()` | Capability flags (`metering`, `identification`, `dynamic_definitions`); see [GTIN choice and dSS firmware behavior](#gtin-choice-and-dss-firmware-behavior) |
| `zone_id` | `0` | Default dS zone ID |

### Device management methods

- **`add_device(device)`** — register a `Device` with this vDC.
- **`remove_device(dsuid, track_vanish=True)`** — remove a `Device`; when
  `track_vanish=True` (default), the vdSD dSUIDs are added to the pending-vanish
  list so the vdSM removes them cleanly. Pass `track_vanish=False` when the removal
  was already initiated by the vdSM.
- **`get_device(dsuid)`** — look up a `Device` by base dSUID; returns `None` if not
  found.
- **`get_vdsd_by_dsuid(dsuid)`** — find a `Vdsd` by its full (sub-device) dSUID
  across all devices in this vDC.
- **`devices`** — read-only property returning `dict[str, Device]` keyed by base
  dSUID string.

### Template methods

- **`save_template(vdsd)`** — save a snapshot of a `Vdsd`'s configuration as a
  reusable template (requires `template_path` to be set).
- **`load_template(dsuid)`** — load and restore a previously saved device template.

---


---

## 8. Device and Vdsd Reference

### Device

`Device` is a **library-level grouping** — it has no protocol representation.
Its role is to keep related `Vdsd` instances together and coordinate announcement,
vanish, and persistence as a unit.

**Constructor** (all keyword-only):

```python
device = Device(vdc=vdc, dsuid=DsUid.from_gtin_serial("07640156791013", "SN001"))
```

| Parameter | Description |
|-----------|-------------|
| `vdc` | Owning `Vdc` |
| `dsuid` | The hardware base dSUID (sub-device index 0). Individual Vdsd instances derive their dSUIDs from this via `derive_subdevice(index)`. |

**Key attributes and methods**:

- **`dsuid`** — the hardware base dSUID (read-only).
- **`vdsds`** — `dict[int, Vdsd]` of sub-device index → `Vdsd` (read-only copy).
- **`add_vdsd(vdsd)`** — attach a `Vdsd`. Raises `RuntimeError` if the device is
  already announced; raises `ValueError` if the vdSD's base dSUID does not match.
- **`remove_vdsd(subdevice_index)`** — remove a `Vdsd` by sub-device index; returns
  the removed instance or `None`.

### Vdsd

`Vdsd` is the actual protocol device entity. Each `Vdsd` has a unique dSUID
(derived from the parent `Device`'s base dSUID and the sub-device index) and is
announced individually to the vdSM.

**Constructor** (all keyword-only):

```python
device = Device(vdc=vdc, dsuid=DsUid.from_gtin_serial("07640156791013", "SN001"))
vdsd = Vdsd(
    device=device,
    primary_group=ColorGroup.YELLOW,
    name="Living Room Light",
    model="Smart Dimmer v2",
)
device.add_vdsd(vdsd)
vdc.add_device(device)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `device` | — | Parent `Device` |
| `primary_group` | — | `ColorGroup` enum value (determines device class / colour) |
| `subdevice_index` | `0` | Sub-device byte (0–255); determines byte 17 of the dSUID |
| `name` | — | User-facing name (required, must be non-empty) |
| `model` | — | Model description (required, must be non-empty) |
| `model_version` | `None` | Firmware / version string |
| `model_uid` | auto-derived | Derived from `model` when omitted |
| `hardware_version` | `None` | Hardware version string |
| `hardware_guid` | `None` | Native hardware GUID |
| `hardware_model_guid` | `None` | Native hardware model GUID |
| `vendor_name` | `None` | Human-readable vendor name |
| `vendor_id` | `None` | Short vendor identifier |
| `vendor_guid` | `None` | Globally unique vendor identifier |
| `descriptions_group` | `None` | dSS configurator UI database group ID |
| `descriptions_class` | `None` | dSS configurator UI database class ID |
| `oem_guid` | `None` | OEM product GUID |
| `oem_model_guid` | `None` | OEM product-model GUID |
| `config_url` | `None` | URL to web configuration interface |
| `device_icon_16` | `None` | 16×16 PNG icon as `bytes` |
| `device_icon_name` | `None` | Icon filename for caching |
| `device_class` | `None` | digitalSTROM device class profile name |
| `device_class_version` | `None` | Revision of the device class profile |
| `zone_id` | `0` | dS zone (assigned by vdSM; 0 means unassigned) |
| `model_features` | `None` | Set of model-feature flag strings |

**Key attributes and methods**:

- **`dsuid`** — the device's full dSUID (base + sub-device index); read-only.
- **`set_output(output)`** — configure the single controllable output (`Output`).
- **`add_binary_input(bi)`** — attach a `BinaryInput`.
- **`add_button_input(btn)`** — attach a `ButtonInput`.
- **`add_sensor_input(si)`** — attach a `SensorInput`.
- **`add_device_state(st)`** — attach a `DeviceState`.
- **`add_device_event(evt)`** — attach a `DeviceEvent`.
- **`add_device_property(prop)`** — attach a `DeviceProperty`.
- **`add_model_feature(feature)`** — add a model-feature flag string to
  `modelFeatures`.
- **`derive_model_features()`** — auto-derive `modelFeatures` from the configured
  components (output, inputs, states, events, properties).
- **`on_identify`** — settable async callback `(vdsd: Vdsd) -> None`; called when
  the vdSM requests device-level identification.
- **`on_settings_changed`** — settable async callback
  `(vdsd: Vdsd, changed: dict[str, Any]) -> None`; called by the host after DSS
  writes vdSD-level properties via `setProperty`. `changed` contains only the keys
  that were actually applied — a subset of `{"name", "zoneID", "progMode",
  "active"}`. A key appears whenever DSS wrote it, even if the value is unchanged.
- **`lifecycle_state`** — read-only property returning the current
  `DeviceLifecycleState`.
- **`async set_lifecycle_state(state)`** — set lifecycle state; handles all vdSM
  communication (`ACTIVE` pushes the `active` property, `REMOVED` triggers
  `VDC_SEND_VANISH`, non-`ACTIVE` states suppress the session pong).
- **`async send_identify()`** — send a `VDC_SEND_IDENTIFY` notification (fire-and-
  forget); use this when the user presses a physical pairing/identify button on the
  hardware.
- **`async push_property(properties)`** — push arbitrary vdSD property changes to
  DSS immediately via `VDC_SEND_PUSH_NOTIFICATION`, without a vanish+re-announce
  cycle. `properties` is a dict using the same property names as `getProperty`
  responses (e.g. `{"name": "New Name", "zoneID": 5}`). No-op when the device is
  not announced or has no active session.

---


---

## 9. Output Reference

`Output` represents the single controllable output of a vdSD. It owns a set of
output channels (e.g. brightness, shade position, colour), a scene table, and three
property groups visible to the vdSM: `outputDescription`, `outputSettings`, and
`outputState`.

Each vdSD may have **at most one** output. Attach it with `vdsd.set_output(output)`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.output import Output
from pydsvdcapi.enums import OutputFunction, OutputMode, OutputUsage, ColorClass

output = Output(
    vdsd=my_vdsd,
    function=OutputFunction.DIMMER,
    output_usage=OutputUsage.ROOM,
    name="Dimmable Light",
    default_group=ColorClass.LIGHTS,
)
my_vdsd.set_output(output)
```

#### Description parameters (read-only after construction)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `function` | `OutputFunction \| int` | `ON_OFF` | Functional type; controls which channels are auto-created |
| `output_usage` | `OutputUsage \| int` | `UNDEFINED` | Usage context |
| `name` | `str \| None` | `None` | Human-readable output name; omitted from `outputDescription` when `None` |
| `default_group` | `int \| None` | `None` | dS Application Group ID (use `ColorClass` values); informational only |
| `variable_ramp` | `bool` | `False` | Whether variable-speed transitions are supported |
| `max_power` | `float` | `-1.0` | Maximum output power in Watts; `-1.0` means undefined |
| `active_cooling_mode` | `bool \| None` | `None` | `True` if the device can actively cool (FCU / air-con); `None` if not applicable |

#### Settings parameters (writable, persisted)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | `OutputMode \| int \| None` | auto-derived | Output mode; when `None`, auto-derived from `function` (see `OutputMode`) |
| `active_group` | `int \| None` | `None` | dS Application Group ID this output is active in; drives scene routing |
| `groups` | `set[int] \| None` | `None` | Set of Application Group IDs (1–63) this output belongs to |
| `push_changes` | `bool` | `False` | Whether locally-generated output changes are pushed to the vdSM |
| `on_threshold` | `float \| None` | `None` | Minimum brightness (0–100 %) to switch on non-dimmable lamps (ON_OFF outputs) |
| `min_brightness` | `float \| None` | `None` | Minimum brightness the hardware supports (light outputs) |
| `dim_time_up` | `int \| None` | `None` | Dim-up time in dS 8-bit format |
| `dim_time_down` | `int \| None` | `None` | Dim-down time in dS 8-bit format |
| `dim_time_up_alt1` | `int \| None` | `None` | Alternate 1 dim-up time |
| `dim_time_down_alt1` | `int \| None` | `None` | Alternate 1 dim-down time |
| `dim_time_up_alt2` | `int \| None` | `None` | Alternate 2 dim-up time |
| `dim_time_down_alt2` | `int \| None` | `None` | Alternate 2 dim-down time |
| `open_time` | `float \| None` | `None` | Motor open travel time in seconds (shade outputs) |
| `close_time` | `float \| None` | `None` | Motor close travel time in seconds (shade outputs) |
| `angle_open_time` | `float \| None` | `None` | Blade angle open time in seconds (shade outputs) |
| `angle_close_time` | `float \| None` | `None` | Blade angle close time in seconds (shade outputs) |
| `stop_delay_time` | `float \| None` | `None` | Stop delay time in seconds (shade outputs) |

### OutputFunction enum

| Member | Int | Description |
|--------|-----|-------------|
| `ON_OFF` | 0 | Binary on/off; auto-creates `BRIGHTNESS` channel |
| `DIMMER` | 1 | Continuously dimmable; auto-creates `BRIGHTNESS` channel |
| `POSITIONAL` | 2 | Positional actuator (shade/blind/valve); no auto-created channels |
| `DIMMER_COLOR_TEMP` | 3 | Tunable white; auto-creates `BRIGHTNESS` + `COLOR_TEMPERATURE` |
| `FULL_COLOR_DIMMER` | 4 | Full colour (RGB / RGBW); auto-creates `BRIGHTNESS`, `COLOR_TEMPERATURE`, `HUE`, `SATURATION`, `CIE_X`, `CIE_Y` |
| `BIPOLAR` | 5 | Bipolar actuator; no auto-created channels |
| `INTERNALLY_CONTROLLED` | 6 | Device controls itself; no auto-created channels |
| `CUSTOM` | 127 | Custom action output; no auto-created channels |

### OutputMode enum

`Output` auto-derives the correct mode from `function` when `mode` is not
passed explicitly.

| Member | Int | Description |
|--------|-----|-------------|
| `DISABLED` | 0 | Output disabled; no controls shown in the configurator |
| `BINARY` | 1 | Binary on/off; configurator shows a toggle only |
| `GRADUAL` | 2 | Continuous-range; configurator shows a slider. Used for all dimmer, positional, and bipolar outputs |
| `DEFAULT` | 127 | Sentinel; do not use directly |

Auto-derivation rules: `ON_OFF` → `BINARY`; `INTERNALLY_CONTROLLED` / `CUSTOM` →
`DISABLED`; all other functions → `GRADUAL`.

### OutputUsage enum

| Member | Int | Description |
|--------|-----|-------------|
| `UNDEFINED` | 0 | Not specified |
| `ROOM` | 1 | Indoor room device |
| `OUTDOORS` | 2 | Outdoor device |
| `USER` | 3 | User-controlled output |

### Auto-created channels by OutputFunction

| OutputFunction | Channels created (in dsIndex order) |
|----------------|-------------------------------------|
| `ON_OFF` | `BRIGHTNESS` (0) |
| `DIMMER` | `BRIGHTNESS` (0) |
| `DIMMER_COLOR_TEMP` | `BRIGHTNESS` (0), `COLOR_TEMPERATURE` (1) |
| `FULL_COLOR_DIMMER` | `BRIGHTNESS` (0), `COLOR_TEMPERATURE` (1), `HUE` (2), `SATURATION` (3), `CIE_X` (4), `CIE_Y` (5) |
| `POSITIONAL` | — (add manually via `add_channel()`) |
| `BIPOLAR` | — (add manually via `add_channel()`) |
| `INTERNALLY_CONTROLLED` | — (add manually via `add_channel()`) |
| `CUSTOM` | — (add manually via `add_channel()`) |

### Key attributes and methods

#### Channel access

- **`channels`** — `dict[int, OutputChannel]`: all channels keyed by `dsIndex`
  (returns a shallow copy).
- **`channel_by_key(key: str) -> OutputChannel | None`** — look up a channel by
  name string (e.g. `"brightness"`) or by a numeric string (the `channelType`
  integer as used by the old API v1/v2 wire format, or `"0"` for the standard
  channel of the device's colour class).
- **`get_channel(ds_index: int) -> OutputChannel | None`** — look up by `dsIndex`.
- **`get_channel_by_type(channel_type) -> OutputChannel | None`** — look up the
  first channel with the given `OutputChannelType`.

#### Adding and removing channels

- **`add_channel(channel_type, *, ds_index=None, name=None, min_value=None, max_value=None, resolution=None, siunit=None, symbol=None, enum_values=None) -> OutputChannel`**
  — add a channel to this output. `ds_index` is auto-assigned (next free) when
  omitted. Use this for `POSITIONAL`, `BIPOLAR`, `INTERNALLY_CONTROLLED`, and
  `CUSTOM` outputs. Raises `ValueError` if `ds_index` is already in use.

- **`remove_channel(ds_index: int) -> OutputChannel | None`** — remove a channel
  by `dsIndex`; returns the removed instance or `None`.

#### Callbacks

- **`on_channel_applied`** — settable async callback, invoked when the vdSM sends
  `apply_now` (i.e. the channel values should be written to hardware):

  ```python
  async def handle_apply(output: Output, updates: dict[OutputChannelType | int, float]) -> None:
      brightness = updates.get(OutputChannelType.BRIGHTNESS)
      if brightness is not None:
          await my_device.set_brightness(brightness)

  output.on_channel_applied = handle_apply
  ```

  `updates` maps `OutputChannelType` (or raw `int` for device-specific channels)
  to the new value. Multiple channel changes for one hardware apply arrive together
  in a single call.

- **`on_dim_channel`** — settable async callback for continuous dimming
  notifications (vDC API §7.3.5):

  ```python
  async def handle_dim(output: Output, channel: OutputChannel, mode: int, area: int) -> None:
      # mode: 1 = dim up, -1 = dim down, 0 = stop
      ...

  output.on_dim_channel = handle_dim
  ```

- **`on_settings_changed`** — settable async callback, invoked when the vdSM
  writes `outputSettings`:

  ```python
  async def handle_settings(output: Output, changed: dict[str, Any]) -> None:
      if "mode" in changed:
          ...

  output.on_settings_changed = handle_settings
  ```

#### Pushing device-side values

Use `OutputChannel.update_value()` (see Section 10) to push a new channel value
from the device to the dSS. If `push_changes` is enabled on the output, this
automatically sends a `VDC_SEND_PUSH_NOTIFICATION` to the vdSM.

### Shade / blind output setup

POSITIONAL outputs require channels to be added manually:

```python
from pydsvdcapi.enums import OutputFunction, OutputUsage, ColorClass, ColorGroup, OutputChannelType

output = Output(
    vdsd=my_vdsd,
    function=OutputFunction.POSITIONAL,
    output_usage=OutputUsage.ROOM,
    default_group=ColorClass.BLINDS,
    open_time=50.0,
    close_time=50.0,
    angle_open_time=1.0,
    angle_close_time=1.0,
    stop_delay_time=0.0,
)
# Add channels manually
pos_ch = output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
angle_ch = output.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
my_vdsd.set_output(output)
```

For a device with `primaryGroup=ColorGroup.GREY` the shadow motor timing settings
(`open_time`, `close_time`, etc.) are included in `outputSettings` automatically.

---

## 10. Output Channels Reference

### OutputChannelType enum

Standard channel type identifiers. IDs 0–191 are reserved for standard types;
IDs 192–239 are available for device-specific (proprietary) channels.

| Enum member | Int | Name string | Unit | Description |
|-------------|-----|-------------|------|-------------|
| `DEFAULT` | 0 | — | — | Catch-all / none |
| `BRIGHTNESS` | 1 | `brightness` | % (0–100) | Light dimming level |
| `HUE` | 2 | `hue` | ° (0–360) | Colour hue |
| `SATURATION` | 3 | `saturation` | % (0–100) | Colour saturation |
| `COLOR_TEMPERATURE` | 4 | `colortemp` | mired (100–1000) | Colour temperature |
| `CIE_X` | 5 | `x` | 0–10000 | CIE x chromaticity |
| `CIE_Y` | 6 | `y` | 0–10000 | CIE y chromaticity |
| `SHADE_POSITION_OUTSIDE` | 7 | `shadePositionOutside` | % (0–100) | External blind / roller shutter position |
| `SHADE_POSITION_INDOOR` | 8 | `shadePositionIndoor` | % (0–100) | Indoor curtain / blind position |
| `SHADE_OPENING_ANGLE_OUTSIDE` | 9 | `shadeOpeningAngleOutside` | % (0–100) | External slat / blade opening angle |
| `SHADE_OPENING_ANGLE_INDOOR` | 10 | `shadeOpeningAngleIndoor` | % (0–100) | Indoor slat / blade opening angle |
| `TRANSPARENCY` | 11 | `transparency` | % (0–100) | Transparency level |
| `AIR_FLOW_INTENSITY` | 12 | `airFlowIntensity` | % (0–100) | Fan / ventilation speed |
| `AIR_FLOW_DIRECTION` | 13 | `airFlowDirection` | enum | Supply (0) / exhaust (1) / both (2) |
| `AIR_FLAP_POSITION` | 14 | `airFlapPosition` | % (0–100) | Air flap position |
| `AIR_LOUVER_POSITION` | 15 | `airLouverPosition` | % (0–100) | Louvre position |
| `HEATING_POWER` | 16 | `heatingPower` | % (0–100) | Heating valve / power level |
| `COOLING_CAPACITY` | 17 | `coolingCapacity` | % (0–100) | Cooling capacity level |
| `AUDIO_VOLUME` | 18 | `audioVolume` | % (0–100) | Audio volume |
| `POWER_STATE` | 19 | `powerState` | enum | Off (0) / on (1) / standby (2) / extendedStandby (3) |
| `AIR_LOUVER_AUTO` | 20 | `airLouverAuto` | enum | Off (0) / auto (1) |
| `AIR_FLOW_AUTO` | 21 | `airFlowAuto` | enum | Off (0) / auto (1) |
| `WATER_TEMPERATURE` | 22 | `waterTemperature` | — (0–150) | Water temperature |
| `WATER_FLOW_RATE` | 23 | `waterFlow` | % (0–100) | Water flow rate |
| `POWER_LEVEL` | 24 | `powerLevel` | % (0–100) | Generic power level |
| `VIDEO_STATION` | 25 | `videoStation` | 0–65535 | Video station / channel number |
| `VIDEO_INPUT_SOURCE` | 26 | `videoInputSource` | 0–255 | Video input source selector |
| `FCU_OPERATION_MODE` | 192 | `operationMode` | enum | FCU mode: off (0), heating (1), cooling (2), fanOnly (3), dry (4), auto (5) |

The **name string** is the channel identifier used in all property trees
(`channelDescriptions`, `channelSettings`, `channelStates`) and in push
notifications. It is also the `channelId` field sent by the dSS in
`setOutputChannelValue` notifications.

### OutputChannel class

`OutputChannel` represents one controllable dimension of a device output. Instances
are created automatically by `Output.add_channel()` (or by the auto-create logic on
`Output` construction) — you do not instantiate them directly.

#### Key attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `ds_index` | `int` | Zero-based channel index within the device |
| `channel_type` | `OutputChannelType \| int` | Channel type ID |
| `name` | `str` | Canonical channel name (e.g. `"brightness"`) |
| `min_value` | `float` | Minimum value in the channel's unit |
| `max_value` | `float` | Maximum value in the channel's unit |
| `resolution` | `float` | Smallest distinguishable step (writable) |
| `value` | `float \| None` | Current channel value; `None` if never set |
| `age` | `float \| None` | Seconds since last hardware confirmation; `None` if not yet confirmed |
| `display_name` | `str \| None` | Optional free-text label for the `name` sub-field in `channelDescriptions` (does not affect the channel key) |

#### `async update_value(value: float) -> None`

Push a new value from the **device** to the dSS. Call this when the physical
device reports a state change.

- The value is clamped to `[min_value, max_value]`.
- If an uplink converter is set, it is applied first.
- The hardware-confirmation timestamp is recorded (so `age` starts counting from
  now).
- If the owning output has `push_changes=True` and an active session, a
  `VDC_SEND_PUSH_NOTIFICATION` is sent to the vdSM.

```python
# Notify the dSS that brightness has changed on the device side
await output.channels[0].update_value(75.0)
```

### Value converters

Converters let you scale values between the device's native range and the
digitalSTROM protocol range without modifying your callback logic.

Two converters can be set per channel:

- **Uplink converter** — applied in the **device → dSS** direction when
  `update_value()` is called.
- **Downlink converter** — applied in the **dSS → device** direction when the vdSM
  sets a channel value via `setOutputChannelValue`.

Both are Python expression snippets. The snippet receives `value` (a `float`) and
must assign the converted result back to `value`. The library appends
`return value` automatically.

```python
ch = output.channels[0]  # e.g. BRIGHTNESS, dS range 0–100 %

# Scale dS 0–100 % to device 0–255 (dSS → device direction)
ch.set_downlink_converter("value = int(round(value * 255.0 / 100.0))")

# Scale device 0–255 to dS 0–100 % (device → dSS direction)
ch.set_uplink_converter("value = value / 255.0 * 100.0")
```

Pass `None` to either method to remove a previously set converter.

Both methods raise `SyntaxError` if the snippet cannot be compiled.

The converter code is persisted alongside the channel description in the YAML state
file, so converters survive restarts without re-registration.

---

## 11. BinaryInput Reference

`BinaryInput` models one binary (two-state) sensor input on a vdSD. Typical uses
include contact sensors, motion detectors, door/window sensors, smoke alarms, and
tamper switches. It maps to the vDC API `binaryInputs` property group (comprising
`binaryInputDescriptions`, `binaryInputSettings`, and `binaryInputStates`).

Attach to a vdSD with `vdsd.add_binary_input(bi)`. A device can have multiple binary
inputs; each must have a unique `ds_index`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.enums import BinaryInputType, BinaryInputUsage

bi = BinaryInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_function=BinaryInputType.PRESENCE,
    input_usage=BinaryInputUsage.ROOM_CLIMATE,
    name="PIR Sensor",
)
my_vdsd.add_binary_input(bi)
```

#### Description parameters (read-only after construction)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all binary inputs of this device; must be unique |
| `sensor_function` | `BinaryInputType` | `GENERIC` | The configured sensor function (writable setting, persisted; set the user-facing function here) |
| `input_type` | `int` | `1` | `0` = poll-only, `1` = detects changes (default) |
| `input_usage` | `BinaryInputUsage` | `UNDEFINED` | Usage context |
| `name` | `str` | `""` | Human-readable label |
| `update_interval` | `float` | `0.0` | Physical tracking interval in seconds; `0.0` = on-change only |
| `hardwired_function` | `BinaryInputType` | `GENERIC` | If the function is fixed in hardware, set this to the matching type; `GENERIC` means freely configurable |

#### Settings parameters (writable, persisted)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `group` | `int` | `0` | dS group number |

### Key attributes and methods

| Attribute / method | Description |
|--------------------|-------------|
| `ds_index` | Zero-based index (read-only) |
| `sensor_function` | Configured sensor function; writable, persisted |
| `input_usage` | Usage context (read-only) |
| `update_interval` | Physical tracking interval in seconds (read-only) |
| `group` | dS group number; writable, persisted |
| `value` | Current boolean value (`True` / `False` / `None` = unknown); volatile |
| `extended_value` | Current integer extended value (`None` = unknown); takes precedence over `value` when set |
| `age` | Seconds since the last value update (`None` = unknown) |
| `error` | Current `InputError` status; writable |
| `on_settings_changed` | Settable async callback `(bi: BinaryInput, changed: dict) -> None`; called when the vdSM writes `binaryInputSettings` |

#### `async update_value(value: bool | None, session: VdcSession | None = None) -> None`

Set the boolean state and push a `binaryInputStates` notification to the vdSM. Pass
`True` for active/detected, `False` for inactive, `None` for unknown. If `session`
is `None` the stored session is used (set automatically when the vdSD is announced).

#### `async update_extended_value(value: int | None, session: VdcSession | None = None) -> None`

Set an integer extended value and push state. Used for sensors with more than two
states (e.g. window handle: 0 = closed, 1 = open, 2 = tilted). Extended value takes
precedence over `value` in the push payload.

#### `async update_error(error: InputError | int, session: VdcSession | None = None) -> None`

Set the error status and push state.

### Uplink converter

An optional Python snippet can transform the raw incoming value before it is stored
and pushed. The snippet receives `value` and must assign the result back to `value`;
the library appends `return value` automatically.

```python
# Invert a normally-closed contact sensor
bi.set_uplink_converter("value = not value")
```

Pass `None` to `set_uplink_converter()` to remove a previously set converter. Raises
`SyntaxError` if the snippet cannot be compiled. The code is persisted to YAML.

### BinaryInputType enum

| Member | Int | Typical sensor |
|--------|-----|----------------|
| `GENERIC` | 0 | Freely configurable / app-mode input |
| `PRESENCE` | 1 | Presence detector (room occupancy) |
| `BRIGHTNESS` | 2 | Light level threshold |
| `PRESENCE_IN_DARKNESS` | 3 | Presence in darkness |
| `TWILIGHT` | 4 | Twilight / dusk detector |
| `MOTION` | 5 | Motion detector |
| `MOTION_IN_DARKNESS` | 6 | Motion in darkness |
| `SMOKE` | 7 | Smoke / fire alarm |
| `WIND` | 8 | Wind alarm |
| `RAIN` | 9 | Rain detector |
| `SUN_RADIATION` | 10 | Solar radiation threshold |
| `THERMOSTAT` | 11 | Thermostat contact |
| `BATTERY_LOW` | 12 | Low battery indicator |
| `WINDOW_OPEN` | 13 | Window open sensor |
| `DOOR_OPEN` | 14 | Door open sensor |
| `WINDOW_TILTED` | 15 | Window tilted (tilt position) |
| `GARAGE_DOOR_OPEN` | 16 | Garage door open |
| `SUN_PROTECTION` | 17 | Sun protection active |
| `FROST` | 18 | Frost alarm |
| `HEATING_SYSTEM_ENABLED` | 19 | Heating system enabled |
| `HEATING_CHANGE_OVER` | 20 | Heating/cooling changeover |
| `INITIALIZATION` | 21 | Sensor initialising |
| `MALFUNCTION` | 22 | Sensor malfunction |
| `SERVICE` | 23 | Service required |

### BinaryInputUsage enum

| Member | Int | Description |
|--------|-----|-------------|
| `UNDEFINED` | 0 | Not specified |
| `ROOM_CLIMATE` | 1 | Indoor climate input |
| `OUTDOOR_CLIMATE` | 2 | Outdoor climate input |
| `CLIMATE_SETTING` | 3 | Climate configuration input |

### Code example

```python
import asyncio
from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.enums import BinaryInputType, BinaryInputUsage

bi = BinaryInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_function=BinaryInputType.DOOR_OPEN,
    input_usage=BinaryInputUsage.ROOM_CLIMATE,
    name="Front Door",
)
my_vdsd.add_binary_input(bi)

# When the physical sensor reports a change:
async def on_door_state_changed(is_open: bool) -> None:
    await bi.update_value(is_open)
```

---

## 12. ButtonInput Reference

`ButtonInput` models one button element on a vdSD. A single physical button can
have one element (single pushbutton) or multiple elements (two-way rocker, 4-way
navigation pad, etc.). Each element is a separate `ButtonInput` instance. Maps to
the vDC API `buttonInputs` property group.

Attach to a vdSD with `vdsd.add_button_input(btn)`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.button_input import ButtonInput
from pydsvdcapi.enums import ButtonType, ButtonElementID, ButtonFunction, ButtonMode

btn = ButtonInput(
    vdsd=my_vdsd,
    ds_index=0,
    button_id=0,
    button_type=ButtonType.SINGLE_PUSHBUTTON,
    button_element_id=ButtonElementID.CENTER,
    name="Main Button",
)
my_vdsd.add_button_input(btn)
```

#### Description parameters (read-only after construction)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all button inputs of this device; must be unique |
| `name` | `str` | `""` | Human-readable label for this element |
| `supports_local_key_mode` | `bool` | `False` | Whether this button can act as a local button |
| `button_id` | `int \| None` | `None` | Physical button ID; all elements of a multi-contact button share the same `button_id` |
| `button_type` | `ButtonType` | `UNDEFINED` | Physical button type; determines element arrangement |
| `button_element_id` | `ButtonElementID` | `CENTER` | Which element of the button this instance represents |

#### Settings parameters (writable, persisted)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `group` | `int` | `0` | dS group this button controls |
| `function` | `ButtonFunction \| ButtonFunctionJoker \| int` | `DEVICE` | Button function / LTNUM |
| `mode` | `ButtonMode \| int` | `STANDARD` | Button input mode / LTMODE |
| `channel` | `int` | `0` | Output channel this button controls; `0` = default channel |
| `sets_local_priority` | `bool` | `False` | Whether button sets local priority |
| `calls_present` | `bool` | `False` | Whether button calls present when system state is absent |

### Key attributes and methods

| Attribute / method | Description |
|--------------------|-------------|
| `ds_index` | Zero-based index (read-only) |
| `button_type` | Physical button type (read-only) |
| `button_element_id` | Element identifier (read-only) |
| `button_id` | Physical button ID shared by all elements (read-only) |
| `click_detector` | The built-in `ClickDetector` state machine (read-only) |
| `value` | Current pressed state (`True` = pressed, `False` = released, `None` = unknown); volatile |
| `click_type` | Most recent resolved click type (`ButtonClickType`); volatile |
| `action_id` | Scene number of the most recent direct action call; `None` when last event was a click |
| `action_mode` | `ActionMode` of the most recent direct action call |
| `age` | Seconds since the last state event (`None` = unknown) |
| `error` | Current `InputError` status; writable |
| `on_settings_changed` | Settable async callback `(btn: ButtonInput, changed: dict) -> None` |

#### State machine mode — `press()` / `release()`

Feed raw press/release events into the built-in `ClickDetector`. The state machine
resolves timing patterns and automatically pushes the resulting `ButtonClickType` to
the vdSM:

```python
# Called by hardware interrupt:
btn.press()    # button physically pressed
btn.release()  # button physically released — ClickDetector resolves and pushes
```

#### `async update_click(click_type: ButtonClickType | int, value: bool | None = None, session: VdcSession | None = None) -> None`

Push a pre-resolved click event directly, bypassing the `ClickDetector`. Use when
the physical device can already determine click types:

```python
await btn.update_click(ButtonClickType.CLICK_1X)
```

#### `async update_action(action_id: int, action_mode: ActionMode | int = ActionMode.NORMAL, session: VdcSession | None = None) -> None`

Push a direct scene call. The push payload uses `actionId` / `actionMode` instead of
`clickType`. Use this when the button directly calls a scene:

```python
await btn.update_action(action_id=5, action_mode=ActionMode.NORMAL)
```

### ClickDetector

The built-in `ClickDetector` state machine converts raw press/release timings into
`ButtonClickType` events. It is created automatically with each `ButtonInput`.

Timing can be customised via `click_detector_config` (a dict passed to the
constructor):

| Key | Default | Description |
|-----|---------|-------------|
| `tip_timeout` | `0.25` s | Maximum press duration for a short press; longer presses start a hold sequence |
| `multi_click_window` | `0.3` s | Maximum gap between presses in a multi-click sequence |
| `hold_repeat_interval` | `1.0` s | Interval between `HOLD_REPEAT` events while button is held |
| `use_tip_events` | `False` | When `True`, emits `TIP_1X`/`TIP_2X`/`TIP_3X`/`TIP_4X` instead of `CLICK_1X`/`CLICK_2X`/`CLICK_3X` |

Click patterns the state machine can produce:

| Pattern | Event emitted |
|---------|---------------|
| 1 short press | `CLICK_1X` (or `TIP_1X`) |
| 2 short presses | `CLICK_2X` (or `TIP_2X`) |
| 3+ short presses | `CLICK_3X` (or `TIP_3X`/`TIP_4X`) |
| Hold (no short press before) | `HOLD_START` → repeated `HOLD_REPEAT` → `HOLD_END` |
| 1 short press + hold | `SHORT_LONG` |
| 2+ short presses + hold | `SHORT_SHORT_LONG` |

### Multi-element buttons — `create_button_group()`

For multi-contact buttons (e.g. two-way rocker) use the `create_button_group()`
helper, which creates all required `ButtonInput` instances automatically:

```python
from pydsvdcapi.button_input import create_button_group
from pydsvdcapi.enums import ButtonType

buttons = create_button_group(
    vdsd=my_vdsd,
    button_id=0,
    button_type=ButtonType.TWO_WAY_PUSHBUTTON,
    start_index=0,
    name_prefix="Rocker",
)
for btn in buttons:
    my_vdsd.add_button_input(btn)
# Creates: ButtonInput(ds_index=0, element=DOWN) and ButtonInput(ds_index=1, element=UP)
```

### ButtonType enum

| Member | Int | Elements | Description |
|--------|-----|---------|-------------|
| `UNDEFINED` | 0 | — | No standard layout; create elements manually |
| `SINGLE_PUSHBUTTON` | 1 | CENTER | Single momentary pushbutton |
| `TWO_WAY_PUSHBUTTON` | 2 | DOWN, UP | Two-way rocker switch |
| `FOUR_WAY_NAVIGATION` | 3 | DOWN, UP, LEFT, RIGHT | Four-direction pad (no center) |
| `FOUR_WAY_WITH_CENTER` | 4 | CENTER, DOWN, UP, LEFT, RIGHT | Four-direction pad with center press |
| `EIGHT_WAY_WITH_CENTER` | 5 | CENTER + 8 directions | Eight-direction pad with center |
| `ON_OFF_SWITCH` | 6 | DOWN (off), UP (on) | Dedicated on/off switch |

### ButtonElementID enum

| Member | Int | Description |
|--------|-----|-------------|
| `CENTER` | 0 | Center element |
| `DOWN` | 1 | Down / lower element |
| `UP` | 2 | Up / upper element |
| `LEFT` | 3 | Left element |
| `RIGHT` | 4 | Right element |
| `UPPER_LEFT` | 5 | Upper-left diagonal |
| `LOWER_LEFT` | 6 | Lower-left diagonal |
| `UPPER_RIGHT` | 7 | Upper-right diagonal |
| `LOWER_RIGHT` | 8 | Lower-right diagonal |

### ButtonClickType enum

| Member | Int | Description |
|--------|-----|-------------|
| `TIP_1X` | 0 | Single short press (tip variant) |
| `TIP_2X` | 1 | Double short press (tip variant) |
| `TIP_3X` | 2 | Triple short press (tip variant) |
| `TIP_4X` | 3 | Quadruple (or more) short press (tip variant) |
| `HOLD_START` | 4 | Hold started (no prior short press) |
| `HOLD_REPEAT` | 5 | Periodic repeat while button is held |
| `HOLD_END` | 6 | Button released after hold |
| `CLICK_1X` | 7 | Single click |
| `CLICK_2X` | 8 | Double click |
| `CLICK_3X` | 9 | Triple (or more) click |
| `SHORT_LONG` | 10 | One short press followed by a hold |
| `LOCAL_OFF` | 11 | Local off event |
| `LOCAL_ON` | 12 | Local on event |
| `SHORT_SHORT_LONG` | 13 | Two short presses followed by a hold |
| `LOCAL_STOP` | 14 | Local stop event |
| `LOCAL_DIM` | 15 | Local dim event |
| `IDLE` | 255 | No recent event (initial / reset state) |

### ButtonMode enum (selection)

| Member | Int | Description |
|--------|-----|-------------|
| `STANDARD` | 0 | Standard 1-way pushbutton |
| `TURBO` | 1 | 1-way turbo mode |
| `SWITCHED` | 2 | Toggle / switched mode |
| `TWO_WAY` | 13 | 2-way mode |
| `ONE_WAY` | 14 | 1-way (explicit) |
| `HEATING_PUSHBUTTON` | 65 | 1-way heating pushbutton |
| `DEACTIVATED` | 255 | Deactivated |

Additional paired two-way modes (`TWO_WAY_DOWN_PAIRED_1` – `TWO_WAY_DOWN_PAIRED_4`,
`TWO_WAY_UP_PAIRED_1` – `TWO_WAY_UP_PAIRED_4`) and AKM contact-module modes
(`AKM_STANDARD` through `AKM_FALLING_EDGE`) are also available.

### Code example — two-way rocker with click detection

```python
import asyncio
from pydsvdcapi.button_input import ButtonInput
from pydsvdcapi.enums import ButtonType, ButtonElementID, ButtonClickType

# Down element (index 0)
btn_down = ButtonInput(
    vdsd=my_vdsd,
    ds_index=0,
    button_id=0,
    button_type=ButtonType.TWO_WAY_PUSHBUTTON,
    button_element_id=ButtonElementID.DOWN,
    name="Rocker Down",
)
# Up element (index 1)
btn_up = ButtonInput(
    vdsd=my_vdsd,
    ds_index=1,
    button_id=0,
    button_type=ButtonType.TWO_WAY_PUSHBUTTON,
    button_element_id=ButtonElementID.UP,
    name="Rocker Up",
)
my_vdsd.add_button_input(btn_down)
my_vdsd.add_button_input(btn_up)

# Hardware events feed the ClickDetector:
async def on_button_event(element: str, pressed: bool) -> None:
    btn = btn_down if element == "down" else btn_up
    if pressed:
        btn.press()
    else:
        btn.release()

# Or push a pre-resolved click directly:
async def send_single_click_up() -> None:
    await btn_up.update_click(ButtonClickType.CLICK_1X)
```

---

## 13. SensorInput Reference

`SensorInput` models one analogue (continuous-value) sensor on a vdSD. Typical uses
include temperature, humidity, CO₂, illuminance, power consumption, air pressure,
and similar continuous readings. Maps to the vDC API `sensorInputs` property group
(comprising `sensorDescriptions`, `sensorSettings`, and `sensorStates`).

Attach to a vdSD with `vdsd.add_sensor_input(si)`.

### Constructor

All parameters are keyword-only. `sensor_type`, `min_value`, `max_value`, and
`resolution` are required.

```python
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.enums import SensorType, SensorUsage

si = SensorInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_type=SensorType.TEMPERATURE,
    sensor_usage=SensorUsage.ROOM,
    name="Room Temperature",
    min_value=-20.0,
    max_value=60.0,
    resolution=0.1,
)
my_vdsd.add_sensor_input(si)
```

The constructor validates the `(sensor_type, sensor_usage)` combination against
ds-basics Table 23 and raises `ValueError` if they are incompatible (e.g.
`SensorType.CO_CONCENTRATION` with `SensorUsage.OUTDOOR`).

#### Description parameters (read-only after construction)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `sensor_type` | `SensorType` | — | Physical quantity measured (required); `SensorType.NONE` is not valid |
| `sensor_usage` | `SensorUsage` | `UNDEFINED` | Usage context; `UNDEFINED` is not valid for deployed sensors |
| `ds_index` | `int` | `0` | Zero-based index among all sensor inputs of this device; must be unique |
| `name` | `str` | `""` | Human-readable label |
| `min_value` | `float` | — | Minimum value in the sensor's unit (required) |
| `max_value` | `float` | — | Maximum value in the sensor's unit (required) |
| `resolution` | `float` | — | Hardware resolution (LSB size) in the sensor's unit (required) |
| `update_interval` | `float` | `0.0` | Physical tracking interval in seconds; `0.0` = on-change only |
| `alive_sign_interval` | `float` | `0.0` | Maximum seconds between pushes before the sensor is considered out of order; `0.0` disables alive signalling |

#### Settings parameters (writable, persisted)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `group` | `int` | `0` | dS group number |
| `min_push_interval` | `float` | `2.0` | Minimum seconds between consecutive push notifications; rapid changes within this window are coalesced |
| `changes_only_interval` | `float` | `0.0` | Minimum seconds between pushes of the same (unchanged) value; `0.0` means every hardware update triggers a push |

### Key attributes and methods

| Attribute / method | Description |
|--------------------|-------------|
| `ds_index` | Zero-based index (read-only) |
| `sensor_type` | Physical quantity the sensor measures (read-only) |
| `sensor_usage` | Usage context (read-only) |
| `min_value` / `max_value` | Sensor range (read-only) |
| `resolution` | Hardware resolution (read-only) |
| `update_interval` | Physical tracking interval (read-only) |
| `alive_sign_interval` | Maximum seconds between pushes before out-of-order detection (read-only) |
| `group` | dS group number; writable, persisted |
| `min_push_interval` | Minimum push interval; writable, persisted |
| `changes_only_interval` | Same-value push suppression interval; writable, persisted |
| `value` | Current sensor reading (`float \| None`); `None` = unknown; volatile |
| `age` | Seconds since the last value update (`None` = unknown) |
| `context_id` | Optional numerical context ID attached to the last push |
| `context_msg` | Optional text context message attached to the last push |
| `error` | Current `InputError` status; writable |
| `on_settings_changed` | Settable async callback `(si: SensorInput, changed: dict) -> None` |

#### `async update_value(value: float | None, session: VdcSession | None = None, *, context_id: int | None = None, context_msg: str | None = None) -> None`

Set the sensor reading and push a `sensorStates` notification. Pass `None` for
unknown. Push frequency is subject to `min_push_interval` and
`changes_only_interval` throttling. If a session is not provided the stored session
(set when the vdSD is announced) is used.

#### `async update_error(error: InputError | int, session: VdcSession | None = None) -> None`

Set the error status and push state.

### Push throttling

Two settings control how often state is pushed to the vdSM:

- **`min_push_interval`** — rapid value changes within this window are coalesced into
  one deferred push. Default is `2.0` seconds.
- **`changes_only_interval`** — hardware re-reports of an unchanged value are
  suppressed within this window. Default `0.0` means every call to `update_value()`
  triggers a push regardless of whether the value changed.

### Alive signalling

When `alive_sign_interval` is non-zero the library automatically re-pushes the
current state at that interval as a heartbeat. The timer is reset after each push.
If no push arrives within the interval the vdSM can consider the sensor out of order.

### Uplink converter

An optional Python snippet transforms the raw incoming value before it is stored and
pushed:

```python
# Convert Fahrenheit to Celsius
si.set_uplink_converter("value = (value - 32.0) * 5.0 / 9.0")
```

Pass `None` to remove a previously set converter. Raises `SyntaxError` if the snippet
cannot be compiled. The code is persisted to YAML.

### SensorType enum

| Member | Int | Typical unit | Description |
|--------|-----|-------------|-------------|
| `NONE` | 0 | — | No sensor / placeholder (not valid for deployed sensors) |
| `TEMPERATURE` | 1 | °C | Temperature |
| `HUMIDITY` | 2 | % | Relative humidity |
| `ILLUMINATION` | 3 | lux | Illuminance |
| `SUPPLY_VOLTAGE` | 4 | V | Supply voltage |
| `CO_CONCENTRATION` | 5 | ppm | Carbon monoxide concentration |
| `RADON_ACTIVITY` | 6 | Bq/m³ | Radon activity |
| `GAS_TYPE` | 7 | — | Gas type indicator |
| `PARTICLES_PM10` | 8 | µg/m³ | Particulate matter PM10 |
| `PARTICLES_PM2_5` | 9 | µg/m³ | Particulate matter PM2.5 |
| `PARTICLES_PM1` | 10 | µg/m³ | Particulate matter PM1 |
| `ROOM_OPERATING_PANEL` | 11 | — | Room operating panel value |
| `FAN_SPEED` | 12 | rpm | Fan speed |
| `WIND_SPEED` | 13 | m/s | Wind speed |
| `ACTIVE_POWER` | 14 | W | Active power consumption |
| `ELECTRIC_CURRENT` | 15 | A | Electric current |
| `ENERGY_METER` | 16 | kWh | Cumulative energy |
| `APPARENT_POWER` | 17 | VA | Apparent power |
| `AIR_PRESSURE` | 18 | hPa | Atmospheric pressure |
| `WIND_DIRECTION` | 19 | ° | Wind direction |
| `SOUND_PRESSURE_LEVEL` | 20 | dB | Sound pressure level |
| `PRECIPITATION` | 21 | mm/m² | Precipitation |
| `CO2_CONCENTRATION` | 22 | ppm | Carbon dioxide concentration |
| `WIND_GUST_SPEED` | 23 | m/s | Wind gust speed |
| `WIND_GUST_DIRECTION` | 24 | ° | Wind gust direction |
| `GENERATED_ACTIVE_POWER` | 25 | W | Generated / exported active power |
| `GENERATED_ENERGY` | 26 | kWh | Cumulative generated energy |
| `WATER_QUANTITY` | 27 | l | Water quantity / volume |
| `WATER_FLOW_RATE` | 28 | l/min | Water flow rate |
| `LENGTH` | 29 | m | Length / distance |
| `MASS` | 30 | kg | Mass / weight |
| `DURATION` | 31 | s | Duration / time |
| `PERCENT` | 32 | % | Generic percentage |
| `PERCENT_SPEED` | 33 | %/s | Percentage rate of change |
| `FREQUENCY` | 34 | Hz | Frequency |

### SensorUsage enum

| Member | Int | Description |
|--------|-----|-------------|
| `UNDEFINED` | 0 | Not specified (not valid for deployed sensors) |
| `ROOM` | 1 | Indoor room sensor |
| `OUTDOOR` | 2 | Outdoor sensor |
| `USER_INTERACTION` | 3 | User-interaction context |
| `DEVICE_LEVEL` | 4 | Device-level measurement (e.g. power consumption of the device itself) |
| `DEVICE_LAST_RUN` | 5 | Measurement from the device's last operating cycle |
| `DEVICE_AVERAGE` | 6 | Running average of device-level measurements |

The ds-basics specification constrains which sensor types are valid with which
usages. For example, `CO_CONCENTRATION` and `CO2_CONCENTRATION` are room-only;
`AIR_PRESSURE`, wind sensors, and precipitation are outdoor-only; power and energy
sensors require a device-level usage. The constructor validates this and raises
`ValueError` on violation.

### Code example — temperature and CO₂ sensor

```python
import asyncio
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.enums import SensorType, SensorUsage

# Temperature sensor
si_temp = SensorInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_type=SensorType.TEMPERATURE,
    sensor_usage=SensorUsage.ROOM,
    name="Room Temperature",
    min_value=-20.0,
    max_value=60.0,
    resolution=0.1,
    update_interval=30.0,
    alive_sign_interval=120.0,
)
my_vdsd.add_sensor_input(si_temp)

# CO₂ sensor
si_co2 = SensorInput(
    vdsd=my_vdsd,
    ds_index=1,
    sensor_type=SensorType.CO2_CONCENTRATION,
    sensor_usage=SensorUsage.ROOM,
    name="CO2 Level",
    min_value=0.0,
    max_value=5000.0,
    resolution=1.0,
)
my_vdsd.add_sensor_input(si_co2)

# When hardware delivers new readings:
async def on_sensor_update(temperature: float, co2: float) -> None:
    await si_temp.update_value(temperature)
    await si_co2.update_value(co2)
```

---

## 14. Model Features Reference

### Overview

`modelFeatures` is a set of boolean capability flags announced in the vdSD's
`modelFeatures` property. The dSS and the dS configurator use these flags to decide
which UI panels to display, which hardware integrations to enable, and which
behaviours to apply to the device. Some flags are derived automatically from the
device's configured components; others must be added manually when a specific
capability cannot be inferred.

### Auto-derived features

`vdsd.derive_model_features()` analyses the vdSD's configured output, channels,
sensors, binary inputs, and button inputs and adds the appropriate flags
automatically. If you do not call `derive_model_features()` before announcement,
the library runs it once automatically at announcement time.

| Feature | Auto-derived when |
|---------|-------------------|
| `dontcare` | Any output is configured |
| `blink` | Any output is configured |
| `transt` | Any output with a non-POSITIONAL function that includes a channel type supporting transitions (brightness, colour, heating/cooling, audio, etc.) |
| `shadeposition` | `primaryGroup` GREY (2) + POSITIONAL output function |
| `shadebladeang` | `primaryGroup` GREY (2) + POSITIONAL output + slat/angle channel (`SHADE_OPENING_ANGLE_OUTSIDE` or `SHADE_OPENING_ANGLE_INDOOR`) present |
| `outvalue8` | Any output present and `primaryGroup` is not GREY (2) |
| `outputchannels` | Both HUE and SATURATION channels present, or both BRIGHTNESS and COLOR_TEMPERATURE channels present |
| `dimtimeconfig` | Output function is DIMMER, DIMMER_COLOR_TEMP, or FULL_COLOR_DIMMER |
| `outconfigswitch` | Output function is ON_OFF |
| `impulseconfig` | Output function is ON_OFF |
| `pwmvalue` | `primaryGroup` BLUE (3) + ON_OFF output, or HEATING_POWER channel present |
| `ventconfig` | Any ventilation channel present (AIR_FLOW_INTENSITY, AIR_FLOW_DIRECTION, AIR_FLAP_POSITION, AIR_LOUVER_POSITION, AIR_LOUVER_AUTO, AIR_FLOW_AUTO) |
| `consumption` | Any power or energy sensor present (ACTIVE_POWER, ELECTRIC_CURRENT, ENERGY_METER, or APPARENT_POWER) |
| `temperatureoffset` | TEMPERATURE sensor present and `primaryGroup` is BLUE (3) |
| `akmsensor` | Any binary input is configured |
| `pushbutton` | Any button input is configured |
| `pushbadvanced` | Any button input is configured |
| `pushbdisabled` | Any button input is configured |
| `pushbarea` | Any button input with `group` ≠ 8 is configured |
| `pushbdevice` | Any button input with `group` ≠ 8 and `supports_local_key_mode=True` |
| `pushbsensor` | Any button input with `group` == 8 (Joker) is configured |
| `highlevel` | Any button input with `group` == 8 (Joker) is configured |
| `heatingprops` | `primaryGroup` BLUE (3) |
| `heatinggroup` | `primaryGroup` BLUE (3) |
| `valvetype` | `primaryGroup` BLUE (3) + output configured |
| `extendedvalvetypes` | `primaryGroup` BLUE (3) + output configured |
| `fcu` | `primaryGroup` BLUE (3) + output configured + ventilation channel types present |
| `locationconfig` | `primaryGroup` GREY (2) + output configured |
| `operationlock` | `primaryGroup` GREY (2) + output configured + outdoor channel (`SHADE_POSITION_OUTSIDE` or `SHADE_OPENING_ANGLE_OUTSIDE`) present |
| `windprotectionconfigblind` | `primaryGroup` GREY (2) + `SHADE_OPENING_ANGLE_OUTSIDE` (type 9) channel present |
| `windprotectionconfigawning` | `primaryGroup` GREY (2) + outdoor position only (no slat/angle channel) |
| `jokerconfig` | `primaryGroup` BLACK (8) |
| `identification` | `vdsd.on_identify` callback is registered |

### Manually addable features

Some features are valid and useful but cannot be inferred automatically. Add them
explicitly with `vdsd.add_model_feature("featurename")` after constructing the
device.

| Feature | What it enables in the configurator |
|---------|-------------------------------------|
| `shadeprops` | Motor timing configuration panel for grey shade devices; enables position-calibration and travel-time fields in the configurator |
| `motiontimefins` | Fine position / motion-time configuration for jalousie / Venetian blind devices; enables blade calibration fields |
| `blinkconfig` | Blink configuration panel; allows the user to configure alert-blink duration and parameters |
| `consumptiontimer` | Consumption timer panel; enables energy-measurement scheduling in the configurator |
| `outmodegeneric` | Generic output-mode selector; shows an additional mode-selection UI element for devices that expose multiple generic output modes |
| `outmodeauto` | Automatic output-mode UI; enables an auto-mode selection control in the configurator |

### Blocked / unsupported features

The following features raise `ValueError` if passed to `add_model_feature()` because
they write to DS485 bus registers or physical hardware registers that are never
forwarded to a TCP/IP VDC device. Declaring them would cause the configurator to show
controls that have no effect.

| Feature | Reason blocked |
|---------|----------------|
| `ledauto` | Controls LED indicators via a DS485 hardware register; no VDC write-back path |
| `leddark` | Controls LED indicators via a DS485 hardware register; no VDC write-back path |
| `dimmodeconfig` | Selects the physical dimmer circuit type via DS485; no VDC path |
| `consumptioneventled` | Triggers LED flash on consumption events via DS485; no VDC path |
| `outmode` | Output-mode selector that writes via `CfgFunction_Mode` on DS485; not forwarded to VDC |
| `outmodeswitch` | Same as `outmode`; DS485 only |
| `heatingoutmode` | Heating output-mode selector via DS485 |
| `umroutmode` | Universal module relay output-mode selector via DS485 |
| `extradimmer` | Extra-dimmer hardware flag; DS485 only |
| `optypeconfig` | Output type configuration via DS485 hardware register |
| `outmodetempcontrol` | Temperature-control output-mode selector; DS485 only |
| `outmodeenoceanvalve` | EnOcean valve output-mode selector; DS485 only |
| `twowayconfig` | Two-way TKM pushbutton hardware type; no VDC equivalent |
| `pushbcombined` | Combined pushbutton mode for physical TKM hardware; no VDC equivalent |
| `ftwdisplaysettings` | FTW display settings; physical device only |
| `ftwbacklighttimeout` | FTW backlight timeout; physical device only |
| `grkl387workaround` | Hardware-specific workaround for a physical device model |
| `akminput` | AKM contact-module input configuration via DS485 bus register; never reaches VDC |
| `akmdelay` | AKM contact-module delay configuration via DS485 bus register; never reaches VDC |

### Complete feature reference

All known feature strings, their canonical index in the dSS firmware enum, and what
they enable:

| Feature string | Firmware index | Description |
|----------------|---------------|-------------|
| `dontcare` | 0 | Device supports "don't care" scene behaviour; enables scene-assignment controls in the configurator |
| `blink` | 1 | Device can blink/alert on scene call; enables the blink alert action |
| `transt` | 4 | Device supports software transition time; enables dim-speed and transition-time controls in the configurator |
| `outmode` | 5 | (Blocked) DS485 output-mode selector |
| `outmodeswitch` | 6 | (Blocked) DS485 output-mode switch selector |
| `outvalue8` | 7 | Device uses 8-bit output value reporting; enables the output value display in the configurator for non-shade devices |
| `shadeposition` | 15 | Device reports shade position; enables the position display and calibration panel for grey shade devices |
| `shadebladeang` | 18 | Device reports blade/slat angle; enables the blade angle calibration panel |
| `consumption` | 20 | Device has power/energy sensors; enables the consumption display in the configurator |
| `outputchannels` | 26 | Device has multiple independent output channels (colour, tunable white); enables the multi-channel output panel |
| `heatingoutmode` | 28 | (Blocked) DS485 heating output-mode selector |
| `heatingprops` | 29 | Device is a climate device; enables heating/cooling properties in the configurator |
| `pwmvalue` | 30 | Device uses PWM-style value reporting (0–100 % heating valve or ON_OFF climate output); enables the heating-power display |
| `blinkconfig` | 34 | Device supports blink-duration configuration; enables the blink configuration panel |
| `umroutmode` | 35 | (Blocked) DS485 universal module relay output-mode selector |
| `impulseconfig` | 39 | Device supports impulse output configuration; enables the impulse-duration configuration panel for ON_OFF outputs |
| `outmodegeneric` | 40 | Device supports a generic output-mode selector; enables the generic mode-selection UI |
| `outconfigswitch` | 41 | Device output can be configured as a binary switch; enables switch-configuration options for ON_OFF outputs |
| `ventconfig` | 47 | Device supports ventilation control; enables the ventilation stage and fan-speed configuration panel |
| `consumptioneventled` | 50 | (Blocked) LED flash on consumption threshold events; DS485 only |
| `consumptiontimer` | 51 | Device supports consumption timer scheduling; enables the energy-measurement schedule panel |
| `dimtimeconfig` | 53 | Device supports dim time configuration; enables the dim-up/dim-down timing controls |
| `outmodeauto` | 54 | Device supports automatic output mode; enables the auto-mode selection control |
| `outmodetempcontrol` | 60 | (Blocked) DS485 temperature-control output-mode selector |
| `outmodeenoceanvalve` | 61 | (Blocked) DS485 EnOcean valve output-mode selector |
| `shadeprops` | — | Enables the motor timing configuration panel for shade devices (travel time, stop delay, etc.) |
| `motiontimefins` | — | Enables blade/slat fine-calibration panel for jalousie devices |
| `temperatureoffset` | — | Climate device with temperature sensor; enables the temperature offset calibration control |
| `akmsensor` | — | Device has binary inputs; enables the binary-input / AKM sensor function panel |
| `pushbutton` | — | Device has button inputs; enables the button configuration panel |
| `pushbadvanced` | — | Enables advanced button options (long-press, multi-click configuration) |
| `pushbdisabled` | — | Enables the option to disable individual button elements |
| `pushbarea` | — | Button controls a zone area; enables area-assignment for the button |
| `pushbdevice` | — | Button supports local key mode; enables local-device-key configuration |
| `pushbsensor` | — | Joker-group button; enables sensor-button assignment panel |
| `highlevel` | — | Joker button with high-level scene calls; enables the high-level scene assignment panel |
| `heatinggroup` | — | Climate device belongs to a heating/cooling group; enables group-assignment for climate devices |
| `valvetype` | — | Climate output device; enables valve type selection (heating-only, cooling-only, combined) |
| `extendedvalvetypes` | — | Climate output device; enables extended valve type options beyond the basic three |
| `fcu` | — | Fan-coil unit (FCU) / ventilation device; enables FCU-specific controls (operation mode, louver, flow direction) |
| `locationconfig` | — | Shade device with output; enables the indoor/outdoor location configuration for the shade |
| `operationlock` | — | Outdoor shade with position channel; enables the operation lock (wind/rain/sun protection) |
| `windprotectionconfigblind` | — | Outdoor jalousie/blind (has slat angle channel); enables the blind-specific wind protection settings |
| `windprotectionconfigawning` | — | Outdoor awning/roller blind (no slat channel); enables awning-specific wind protection settings |
| `jokerconfig` | — | Joker/Black device; enables the joker configuration panel for freely assignable functions |
| `identification` | — | Device has an `on_identify` callback; enables the identify button in the configurator |

### Code example

```python
from pydsvdcapi import Vdsd

# Auto-derive features from the configured output, sensors, inputs, and buttons.
# This is the recommended approach — call it once after all components are attached.
vdsd.derive_model_features()

# Manually add a feature that cannot be auto-derived.
# For a grey shade device that supports motor timing configuration:
vdsd.add_model_feature("shadeprops")
vdsd.add_model_feature("motiontimefins")

# For a dimmer that supports blink-duration configuration:
vdsd.add_model_feature("blinkconfig")

# Remove a feature that was auto-derived but is not applicable:
vdsd.remove_model_feature("blink")

# Inspect the current feature set (returns a copy):
print(vdsd.model_features)
```

After `derive_model_features()` is called the flag `_features_derived` is set.
Subsequent calls to `announce()` will not run auto-derivation again, so any manual
additions or removals made after `derive_model_features()` are preserved.

### Note on oem_model_guid and firmware model feature injection

If the vdSD's `oem_model_guid` matches a GTIN in the dSS firmware's internal device
database (VdcDb), the dSS may automatically inject additional `modelFeatures` flags
from that database entry — independently of what the vDC announces. The features
declared by the vDC and the firmware-injected features are merged by the dSS; the
result visible in the configurator may therefore include flags that were never
explicitly set in your code.

Note: this injection is driven by `oem_model_guid`, not by any GTIN embedded in the
dSUID. See [Device Template Catalogue](#21-device-template-catalogue) for details.

---

## 15. Dynamic Features

The dSS exposes four distinct mechanisms that let virtual devices participate in
automation and the configurator beyond simple output control: device states, device
events, device properties, and device actions. Enabling them correctly requires two
prerequisites and an understanding of how each mechanism interacts with the dSS
firmware's built-in device database (VdcDb).

### What the dSS exposes

| Feature | Protocol entity | Purpose |
|---------|----------------|---------|
| Device States | `deviceStates` | Discrete enumerated status values (e.g. OperationMode, DoorState) |
| Device Events | `deviceEventDescriptions` / push | One-shot notifications (e.g. ProgramFinished) |
| Device Properties | `deviceProperties` | Read/write named values persisted by the VDC |
| Device Actions | `deviceActionDescriptions` | Callable operations the dSS can invoke on the device |

### What a template GTIN activates

The dSS firmware looks up `vdsd.oem_model_guid` in VdcDb and activates features
accordingly:

| GTIN has … | Effect in dSS |
|---|---|
| ≥ 1 row in actions or events table | `hasActionInterface=True` → Actions and Events from the VDC appear as automation triggers |
| ≥ 1 row in states table | Allocates `StateType_Device` slots in `/usr/states/` → device appears in the automation state picker |
| Rows in properties table | Property descriptions loaded; `dynamic_definitions=True` → VDC's names shown |
| Any entry | dSS may inject additional `modelFeatures` flags (see [Section 14](#14-model-features-reference)) |

### Prerequisites

Before device states, events, properties, or actions are usable in dSS automation
and the configurator, two prerequisites must be met:

**1. Set `oem_model_guid` on the vdSD to a VdcDb-registered GTIN:**

```python
vdsd.oem_model_guid = "gs1:(01)<13-digit-GTIN>"
```

Without a matching VdcDb entry, `hasActionInterface` remains `False` and the device
does not appear in the automation state picker. See [Section 20](#20-generic-framework-gtin)
for the generic test GTIN and [Section 21](#21-device-template-catalogue) for
device-specific GTINs.

**2. Enable `dynamic_definitions` on the VDC:**

```python
from pydsvdcapi import VdcCapabilities

vdc = Vdc(
    host=host,
    implementation_id="x-myapp",
    name="My VDC",
    model="My Gateway",
    capabilities=VdcCapabilities(dynamic_definitions=True),
)
```

Without `dynamic_definitions=True`, the dSS shows generic names from VdcDb instead
of the names your VDC provides for states, events, actions, and properties.

### State evaluation gap

States involve four separate mechanisms in the dSS. Understanding their interaction
is critical for reliable automation:

| Mechanism | Works with any VDC-pushed state? | Requires VdcDb state rows? |
|---|---|---|
| Device appears in automation state-picker device list | No | Yes — `initStates()` only runs when VdcDb has state rows for the GTIN |
| State names shown in condition / trigger picker | Yes — with `dynamic_definitions=True` | No — VDC's names override VdcDb |
| `DeviceStateEvent` fires on state push (event-triggered automation) | **Yes** | No |
| State **condition** evaluates in automation rule | **No** | State name must exactly match a VdcDb-pre-allocated slot in `/usr/states/` |

**Practical consequence:** Event-triggered automation (`when ProgramFinished event fires →
do something`) works reliably with any template GTIN. State-condition automation (`when
OperationMode == Running → do something`) only works if the state name in `DeviceState.name`
exactly matches the VdcDb-registered name for that GTIN.

---

## 16. Device States Reference

### Prerequisites

Device states are visible in the dSS configurator and automation engine only when
both prerequisites from [Section 15](#15-dynamic-features) are met:

1. `vdsd.oem_model_guid` is set to a GTIN that has state rows in VdcDb.
2. `dynamic_definitions=True` is set on the VDC (to show your state names in the picker).

For state-condition automation, the `DeviceState.name` must exactly match the
VdcDb-pre-allocated slot name for your GTIN (see [state evaluation gap](#state-evaluation-gap)).

`DeviceState` models one discrete enumerated device state on a vdSD. States
are used to report device-specific status information to the dSS — for example
an operating mode, an error code, or any other multi-valued status. Unlike
sensors (which carry continuous readings), a device state has a fixed set of
labeled options (e.g. `{0: "Off", 1: "Running", 2: "Error"}`).

Device states map to the vDC API `deviceStates` property group (comprising
`deviceStateDescriptions` and `deviceStates`). State descriptions are
persisted; current values are volatile and not saved across restarts.

Attach to a vdSD with `vdsd.add_device_state(st)`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.device_state import DeviceState

st = DeviceState(
    vdsd=my_vdsd,
    ds_index=0,
    name="operatingState",
    options={0: "Off", 1: "Initializing", 2: "Running", 3: "Shutdown"},
    description="Current operating state of the device",
)
my_vdsd.add_device_state(st)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all device states of this device; must be unique |
| `name` | `str` | `""` | State name as reported to the dSS (e.g. `"operatingState"`) |
| `options` | `dict[int \| str, str] \| None` | `None` | Mapping of integer or string keys to human-readable labels (e.g. `{0: "Off", 1: "Running"}`) |
| `description` | `str \| None` | `None` | Optional human-readable description |

### Key attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `ds_index` | `int` | Zero-based index (read-only) |
| `name` | `str` | State name; writable |
| `options` | `dict` | Option key → label mapping; writable (returns a copy) |
| `description` | `str \| None` | Human-readable description; writable |
| `value` | `int \| None` | Current state as integer option key; `None` = unknown; volatile (not persisted) |
| `uplink_converter_code` | `str \| None` | Stored uplink converter snippet, or `None` |

### Key methods

#### `async update_value(value: int | str, session=None) -> None`

Update the state value and push a `deviceStates` notification to the vdSM.

- `value` accepts an integer option key or a text label (resolved via the
  `options` dictionary). Passing a label string (e.g. `"Running"`) performs a
  reverse lookup and stores the corresponding integer key.
- If `session` is `None`, the owning vdSD's current session is used.
- If no active session is available, the value is recorded locally but the push
  is skipped with a warning.
- If an uplink converter is set, it is applied before option resolution.

```python
await st.update_value(2)          # by integer key
await st.update_value("Running")  # by label — resolved to key 2
```

#### `set_uplink_converter(code: str | None) -> None`

Set or clear an uplink converter. The snippet manipulates `value` (the raw
incoming int or str) before option resolution. The library appends
`return value` automatically. Pass `None` to remove. Raises `SyntaxError` if
the snippet cannot be compiled. The code is persisted to YAML.

```python
st.set_uplink_converter("""
mapping = {"STOPPED": 0, "PLAYING": 2}
value = mapping.get(str(value), 0)
""")
```

### Code example

```python
from pydsvdcapi.device_state import DeviceState

# Declare the state
st = DeviceState(
    vdsd=my_vdsd,
    ds_index=0,
    name="operatingState",
    options={0: "Off", 1: "Initializing", 2: "Running", 3: "Error"},
    description="Device operating state",
)
my_vdsd.add_device_state(st)

# When the hardware reports a state change:
async def on_hardware_state_changed(raw_state: int) -> None:
    await st.update_value(raw_state)
```

---

## 17. Device Events Reference

### Prerequisites

Device events appear as automation triggers in the dSS configurator only when both
prerequisites from [Section 15](#15-dynamic-features) are met:

1. `vdsd.oem_model_guid` is set to a GTIN that has action or event rows in VdcDb
   (`hasActionInterface=True`).
2. `dynamic_definitions=True` is set on the VDC (to show your event names in the trigger picker).

`DeviceEvent` models one stateless one-shot event on a vdSD. Device events are
push notifications sent from the device to the dSS when something notable
happens — for example a doorbell press, an alarm trigger, or a protocol-level
button event. Unlike device states, events carry no persistent state; each
invocation is a distinct occurrence.

Device events map to the vDC API `deviceEventDescriptions` property group and
are sent via `VDC_SEND_PUSH_NOTIFICATION` with a `deviceevents` payload. Only
the event description (name and optional description) is persisted; occurrences
are transient.

Attach to a vdSD with `vdsd.add_device_event(evt)`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.device_event import DeviceEvent

evt = DeviceEvent(
    vdsd=my_vdsd,
    ds_index=0,
    name="doorbell",
    description="Doorbell button pressed",
)
my_vdsd.add_device_event(evt)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all device events of this device; must be unique |
| `name` | `str` | `""` | Event name as reported to the dSS (e.g. `"doorbell"`) |
| `description` | `str \| None` | `None` | Optional human-readable description |

### Key attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `ds_index` | `int` | Zero-based index (read-only) |
| `name` | `str` | Event name; writable |
| `description` | `str \| None` | Human-readable description; writable |

### `async raise_event(session=None) -> None`

Fire the event — sends a `VDC_SEND_PUSH_NOTIFICATION` to the vdSM with the
`deviceevents` payload containing this event's name.

- If `session` is `None`, the owning vdSD's current session is used.
- If no active session is available, the call is silently skipped with a
  warning.

### Code example

```python
from pydsvdcapi.device_event import DeviceEvent

evt = DeviceEvent(
    vdsd=my_vdsd,
    ds_index=0,
    name="alarmTriggered",
    description="Motion alarm was triggered",
)
my_vdsd.add_device_event(evt)

# When the physical device fires the alarm:
async def on_alarm() -> None:
    await evt.raise_event()
```

---

## 18. Device Properties Reference

### Prerequisites

Device properties are shown in the dSS configurator's property panel only when both
prerequisites from [Section 15](#15-dynamic-features) are met:

1. `vdsd.oem_model_guid` is set to a GTIN that has property rows in VdcDb.
2. `dynamic_definitions=True` is set on the VDC (to show your property names).

`DeviceProperty` models one generic device property on a vdSD. Properties
differ from device states in that they are not limited to a fixed set of
labeled options — they can be numeric, enumeration, or free-form string values.
Property values are read/write from the dSS perspective and are **persisted**
across restarts (unlike device state values, which are volatile).

Device properties map to the vDC API `deviceProperties` property group
(comprising `devicePropertyDescriptions` and `deviceProperties`). The dSS can
display and edit these properties in the configurator.

Attach to a vdSD with `vdsd.add_device_property(prop)`.

### Constructor

All parameters are keyword-only.

```python
from pydsvdcapi.device_property import DeviceProperty

prop = DeviceProperty(
    vdsd=my_vdsd,
    ds_index=0,
    name="batteryLevel",
    type="numeric",
    min_value=0.0,
    max_value=100.0,
    resolution=1.0,
    siunit="%",
    default=100.0,
    description="Battery charge level",
)
my_vdsd.add_device_property(prop)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all device properties of this device; must be unique |
| `name` | `str` | `""` | Property name as reported to the dSS (e.g. `"batteryLevel"`) |
| `type` | `str` | `"string"` | Data type: `"numeric"`, `"enumeration"`, or `"string"` |
| `min_value` | `float \| None` | `None` | Minimum value (numeric only) |
| `max_value` | `float \| None` | `None` | Maximum value (numeric only) |
| `resolution` | `float \| None` | `None` | Resolution / LSB size (numeric only) |
| `siunit` | `str \| None` | `None` | SI unit string, e.g. `"%"` or `"°C"` (numeric only) |
| `options` | `dict[int \| str, str] \| None` | `None` | Option key → label mapping (enumeration only) |
| `default` | `float \| str \| None` | `None` | Default value (all types) |
| `description` | `str \| None` | `None` | Optional human-readable description |

### Key attributes and methods

| Attribute | Type | Description |
|-----------|------|-------------|
| `ds_index` | `int` | Zero-based index (read-only) |
| `name` | `str` | Property name; writable |
| `type` | `str` | Data type identifier; writable |
| `min_value` / `max_value` | `float \| None` | Range bounds (numeric); writable |
| `resolution` | `float \| None` | Resolution (numeric); writable |
| `siunit` | `str \| None` | SI unit (numeric); writable |
| `options` | `dict \| None` | Enumeration options; writable (returns a copy) |
| `default` | `float \| str \| None` | Default value; writable |
| `description` | `str \| None` | Human-readable description; writable |
| `value` | `float \| str \| None` | Current value (persisted); settable directly |
| `uplink_converter_code` | `str \| None` | Stored uplink converter snippet, or `None` |

#### `async update_value(value: float | int | str, session=None) -> None`

Update the property value, persist it, and push a `deviceProperties`
notification to the vdSM.

- For `"numeric"` properties the value is stored as `float`.
- For `"enumeration"` properties an integer key is automatically resolved to
  the corresponding text label via the `options` dictionary.
- For `"string"` properties the value is stored as `str`.
- If `session` is `None`, the owning vdSD's current session is used.
- If no active session is available, the value is still saved locally but the
  push is skipped with a warning.
- Also triggers an auto-save since property values are persisted.

#### `set_uplink_converter(code: str | None) -> None`

Set or clear an uplink converter applied in `update_value()` before type
conversion. Same mechanics as for `DeviceState` and `OutputChannel`. Pass
`None` to remove. Raises `SyntaxError` if the snippet cannot be compiled.

```python
prop.set_uplink_converter("value = round(float(value), 2)")
```

### Code example

```python
from pydsvdcapi.device_property import DeviceProperty

# Numeric property — battery level
prop = DeviceProperty(
    vdsd=my_vdsd,
    ds_index=0,
    name="batteryLevel",
    type="numeric",
    min_value=0.0,
    max_value=100.0,
    resolution=1.0,
    siunit="%",
    default=100.0,
    description="Battery charge level",
)
my_vdsd.add_device_property(prop)

# Enumeration property — connection status
prop_conn = DeviceProperty(
    vdsd=my_vdsd,
    ds_index=1,
    name="connectionStatus",
    type="enumeration",
    options={0: "Disconnected", 1: "Connected", 2: "Pairing"},
    description="Device connection status",
)
my_vdsd.add_device_property(prop_conn)

# When hardware reports a new battery reading:
async def on_battery_update(percent: float) -> None:
    await prop.update_value(percent)
```

---

## 19. Device Actions Reference

### Prerequisites

Device actions are invokable from the dSS configurator and automation engine only
when both prerequisites from [Section 15](#15-dynamic-features) are met:

1. `vdsd.oem_model_guid` is set to a GTIN that has action rows in VdcDb
   (`hasActionInterface=True`).
2. `dynamic_definitions=True` is set on the VDC (to show your action names in the
   configurator).

Actions are operations that the dSS can invoke on the device. The vdSM sends
action requests via `VDSM_REQUEST_GENERIC_REQUEST` with
`methodname="invokeDeviceAction"`. Each action is identified by a string ID and
may carry parameters.

The actions system has four layers:

| Class | Protocol group | Prefix | Notes |
|-------|---------------|--------|-------|
| `DeviceActionDescription` | `deviceActionDescriptions` | (none) | Template: describes a callable operation and its parameter schema |
| `StandardAction` | `standardActions` | `"std."` | Static pre-defined action based on a template; persisted |
| `CustomAction` | `customActions` | `"custom."` | User-configurable action; persisted |
| `DynamicAction` | `dynamicDeviceActions` | `"dynamic."` | Device-managed action; transient (recreated after restart) |

All action-related classes are in `pydsvdcapi.actions`.

### ActionParameter

`ActionParameter` describes one input parameter of an action template.

```python
from pydsvdcapi.actions import ActionParameter

param = ActionParameter(
    name="volume",
    type="numeric",
    min_value=0,
    max_value=100,
    default=50.0,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `""` | Parameter name (used as the key in `params`) |
| `type` | `str` | `"string"` | Data type: `"numeric"`, `"enumeration"`, or `"string"` |
| `min_value` | `float \| None` | `None` | Minimum value (numeric only) |
| `max_value` | `float \| None` | `None` | Maximum value (numeric only) |
| `resolution` | `float \| None` | `None` | Resolution / LSB size (numeric only) |
| `siunit` | `str \| None` | `None` | SI unit string (numeric only) |
| `options` | `dict[int \| str, str] \| None` | `None` | Option key → label mapping (enumeration only) |
| `default` | `float \| str \| None` | `None` | Default value (all types) |

### DeviceActionDescription

`DeviceActionDescription` is an action template — it describes an operation the
device supports, including its parameter schema. Action instances
(`StandardAction`, `CustomAction`) reference templates by name.

```python
from pydsvdcapi.actions import ActionParameter, DeviceActionDescription

param = ActionParameter(name="volume", type="numeric", min_value=0, max_value=100)
tmpl = DeviceActionDescription(
    vdsd=my_vdsd,
    ds_index=0,
    name="play",
    params=[param],
    description="Play media on the device",
)
my_vdsd.add_device_action_description(tmpl)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all action descriptions; must be unique |
| `name` | `str` | `""` | Action template name (e.g. `"play"`) |
| `params` | `list[ActionParameter] \| None` | `None` | Optional list of parameter descriptors |
| `description` | `str \| None` | `None` | Optional human-readable description |

Attach with **`vdsd.add_device_action_description(desc)`**.

### StandardAction

`StandardAction` is a static, immutable pre-defined action based on a template.
Its name must be prefixed `"std."`. Standard actions are defined by the device
and persisted.

```python
from pydsvdcapi.actions import StandardAction

std = StandardAction(
    vdsd=my_vdsd,
    ds_index=0,
    name="std.play-loud",
    action="play",       # references the template name
    params={"volume": 100},
)
my_vdsd.add_standard_action(std)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all standard actions; must be unique |
| `name` | `str` | `""` | Unique action ID, must start with `"std."` |
| `action` | `str` | `""` | Name of the template action this standard action is based on |
| `params` | `dict[str, Any] \| None` | `None` | Parameter value overrides relative to the template defaults |

Attach with **`vdsd.add_standard_action(std)`**.

### CustomAction

`CustomAction` is a user-configurable action based on a template. Its name must
be prefixed `"custom."`. Custom actions can be created and modified via the dSS
API and are persisted.

```python
from pydsvdcapi.actions import CustomAction

cust = CustomAction(
    vdsd=my_vdsd,
    ds_index=0,
    name="custom.morning-play",
    action="play",
    title="Morning Playlist",
    params={"volume": 60},
)
my_vdsd.add_custom_action(cust)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all custom actions; must be unique |
| `name` | `str` | `""` | Unique action ID, must start with `"custom."` |
| `action` | `str` | `""` | Reference name of the template action |
| `title` | `str` | `""` | Human-readable name assigned by the user |
| `params` | `dict[str, Any] \| None` | `None` | Parameter value overrides |

Attach with **`vdsd.add_custom_action(cust)`**.

### DynamicAction

`DynamicAction` is an action created and managed by the device itself at
runtime. Its name must be prefixed `"dynamic."`. Dynamic actions can appear,
change, or disappear based on device state. They are transient — not persisted
across restarts and must be re-registered after startup.

```python
from pydsvdcapi.actions import DynamicAction

dyn = DynamicAction(
    vdsd=my_vdsd,
    ds_index=0,
    name="dynamic.special-mode",
    title="Special Mode",
)
my_vdsd.add_dynamic_action(dyn)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `vdsd` | `Vdsd` | — | Owning vdSD (required) |
| `ds_index` | `int` | `0` | Zero-based index among all dynamic actions; must be unique |
| `name` | `str` | `""` | Unique action ID, must start with `"dynamic."` |
| `title` | `str` | `""` | Human-readable name |

Attach with **`vdsd.add_dynamic_action(dyn)`**.

### Handling action invocations

When the vdSM invokes an action on a device (`invokeDeviceAction`), the library
calls the `on_invoke_action` callback on the `Vdsd`. Set this callback to react
to all action invocations:

```python
async def handle_action(vdsd: Vdsd, action_id: str, params: dict) -> None:
    if action_id in ("std.play-loud", "custom.morning-play"):
        volume = params.get("volume", 50)
        await my_player.play(volume=volume)
    elif action_id == "dynamic.special-mode":
        await my_device.enter_special_mode()

vdsd.on_invoke_action = handle_action
```

**Callback signature:**

```python
async def callback(vdsd: Vdsd, action_id: str, params: dict[str, Any]) -> None: ...
# sync is also accepted:
def callback(vdsd: Vdsd, action_id: str, params: dict[str, Any]) -> None: ...
```

- `vdsd` — the `Vdsd` instance that received the invocation
- `action_id` — the action name string (e.g. `"std.play-loud"`, `"custom.morning-play"`)
- `params` — dict of parameter name → value pairs (may be empty)

### Complete code example

```python
from pydsvdcapi.actions import (
    ActionParameter,
    DeviceActionDescription,
    StandardAction,
    CustomAction,
    DynamicAction,
)

# 1. Define a parameter and a template action
vol_param = ActionParameter(
    name="volume", type="numeric",
    min_value=0, max_value=100, default=50.0,
)
tmpl = DeviceActionDescription(
    vdsd=my_vdsd, ds_index=0,
    name="play",
    params=[vol_param],
    description="Play audio on the device",
)
my_vdsd.add_device_action_description(tmpl)

# 2. A standard action — always available at full volume
std = StandardAction(
    vdsd=my_vdsd, ds_index=0,
    name="std.play-max",
    action="play",
    params={"volume": 100},
)
my_vdsd.add_standard_action(std)

# 3. A custom action — user-configurable name and parameters
cust = CustomAction(
    vdsd=my_vdsd, ds_index=0,
    name="custom.evening",
    action="play",
    title="Evening Mode",
    params={"volume": 40},
)
my_vdsd.add_custom_action(cust)

# 4. A dynamic action — available only when device reports a special state
dyn = DynamicAction(
    vdsd=my_vdsd, ds_index=0,
    name="dynamic.alarm",
    title="Alarm Tone",
)
my_vdsd.add_dynamic_action(dyn)

# 5. Handle all invocations via a single callback
async def handle_action(vdsd, action_id: str, params: dict) -> None:
    volume = params.get("volume", 50)
    if action_id.startswith(("std.play", "custom.", "dynamic.alarm")):
        await my_player.play(volume=volume)

my_vdsd.on_invoke_action = handle_action
```

---

## 20. Generic Framework GTIN

For VDC implementations that do not map to a specific physical product, the dSS
firmware database includes internal test GTINs that can be used to enable
`hasActionInterface` and related configurator features without implementing a
device-specific contract.

Set `oem_model_guid` and enable `dynamic_definitions` as described in
[Section 15](#15-dynamic-features) before using either GTIN.

### `2345678901234` — recommended for custom VDC implementations

```python
vdsd.oem_model_guid = "gs1:(01)2345678901234"
```

Registered as `FrameworkTestDeviceWithoutRegressionImpact`. Has action and event
database rows (so `hasActionInterface=True`) but **no state rows** — no state slots
are pre-allocated, so the device never appears in the automation state-picker.

| Feature | Status |
|---|---|
| Actions visible as automation triggers | ✅ your `DeviceActionDescription` names |
| Events visible as automation triggers | ✅ your `DeviceEvent` names |
| State values visible in Hardware tab | ✅ pushed via `DeviceState.update_value()` |
| Device appears in automation state picker | ❌ no state rows in VdcDb |
| State conditions / triggers evaluate | ❌ |

Use this GTIN when your device primarily exposes commands (actions) and notifications
(events) without needing state-condition automation.

### `1234567890123` — do not use for custom implementations

Registered as `RegressionTestDevice`. The dSS regression suite depends on its exact
definition and it must not change. It pre-allocates one state (`dummyState`, options:
`d` / `mm` / `u` / `y`) plus action/event rows. With `dynamic_definitions=True`, your
VDC's own state names appear in the picker — but condition evaluation still only works
for a state named exactly `dummyState`. Not suitable for production use.

---

## 21. Device Template Catalogue

The dSS firmware ships with a built-in device database (VdcDb) that maps product
GTINs to pre-defined contracts of states, events, actions, and properties. When a
vdSD's `oem_model_guid` matches a GTIN in this database, the dSS activates those
contract entries for the device — enabling automation and configurator features that
the vDC API cannot set directly.

**`oem_model_guid` is the only lookup key.** The GTIN in the dSUID (set via
`from_gtin_serial()`) is not consulted for this purpose; it is used only for stable
unique identification. The format is always:

```python
vdsd.oem_model_guid = "gs1:(01)<13-digit-GTIN>"
```

Also enable `dynamic_definitions` on the VDC so the configurator shows your VDC's own
state/event/action names rather than the generic names stored in VdcDb:

```python
vdc = Vdc(
    host=host,
    implementation_id="x-myapp",
    name="My VDC",
    model="My Gateway",
    capabilities=VdcCapabilities(dynamic_definitions=True),
)
```

### Template family reference

Each row shows the **recommended generic GTIN** for that device family, the exact
State / Property / Action / Event names registered in VdcDb, and a link to the
implementation notes below.

| Device family | Generic GTIN | States | Properties | Actions | Events |
|---|---|---|---|---|---|
| Coffee Maker | `7640156794144` | OperationMode · PowerState · RemoteControl | BeanAmount · FillQuantity · ProgramName · ProgramProgress · RemainingProgramTime | CaffeLatte · Cappuccino · Coffee · Espresso · EspressoMacchiato · LatteMacchiato · PowerOn · StandBy · Stop | LocallyOperated · ProgramFinished · ProgramStarted |
| Cooktop | `7640156794298` | OperationMode · PowerState · RemoteControl | — | — | AlarmClockElapsed · LocallyOperated · PreheatFinished · ProgramFinished · ProgramStarted |
| Dishwasher | `7640156794120` | DoorState · OperationMode · PowerState · RemoteControl | DelayedStart · ProgramName · ProgramProgress · RemainingProgramTime | Auto3545 · Auto4565 · Auto6575 · Eco50 · PowerOff · PowerOn · QuickWash45 · Stop | ProgramAborted · ProgramFinished · ProgramStarted |
| Dryer | `7640156794106` | DoorState · OperationMode · RemoteControl | DryingTarget · ProgramName · ProgramProgress · RemainingProgramTime | Cotton · Mix · Stop · Synthetic | LocallyOperated · ProgramFinished · ProgramStarted |
| Fridge / Fridge-Freezer | `7640156794113` | DoorState | FreezerSuperMode · FreezerTargetTemperature · FridgeSuperMode · FridgeTargetTemperature | CancelFreezerSuperMode · CancelFridgeSuperMode · SetFreezerSuperMode · SetFridgeSuperMode | — |
| Hood | `7640156794304` | OperationMode · PowerState · RemoteControl | ElapsedProgramTime · ProgramName · ProgramProgress · RemainingProgramTime | ActAutomaticMode · ActFanIntense1 · ActFanIntense2 · ActFanLevel1 · ActFanLevel2 · ActFanLevel3 · ActFanRunOn · PowerOff | LocalyOperated · ProgramFinished · ProgramStarted |
| Oven | `7640156794083` | DoorState · OperationMode · PowerState · RemoteControl | ElapsedProgramTime · ProgramName · ProgramProgress · RemainingProgramTime · TargetTemperature | HotAir · PizzaSetting · PowerOn · Preheating · StandBy · Stop · StopIfNotTimed · TopBottomHeating | AlarmClockElapsed · LocallyOperated · PreheatFinished · ProgramFinished · ProgramStarted |
| Washing Machine | `7640156794090` | DoorState · OperationMode · RemoteControl | ProgramName · ProgramProgress · RemainingProgramTime · SpinSpeed · Temperature | Cotton · DelicatesSilk · EasyCare · Mix · Stop · Wool | LocallyOperated · ProgramFinished · ProgramStarted |
| Door Lock (Dormakaba) | `7640156793871` | StatusDoorState | — | OpenDoor | DoorUnlockedKey1 … DoorUnlockedKey10 |
| Video Door Station (DoorBird) | `7640156794496` | — | — | ActDoorUnlock · ActIrLightOn · ActSwitchRelay2 | — |
| Logitech Harmony | `7640156792072` | OperationMode | AvActivityName · NonAvActivityName | PowerOffAvActivity · StopAllActivities | — |
| Panasonic TV | `7640156794465` | StaInputMode · StaMute · StaNotLevel · StaOpMode | PropIp | ActTurnOn · ActTurnOff · ActIncrVol · ActDecrVol · ActMute · ActUnmute · ActSetVol · ActSetInputMode · … | — |
| Sonos | `7640156794625` | StatusInputMode · StatusMute · StatusOperationMode · StatusPlaybackModeRepeat · StatusPlaybackModeShuffle · StatusPlaybackType | PropertyIpAddress · PropertyPlaybackArtist · PropertyPlaybackTitle · PropertySerialNumber | ActionMute · ActionNextTrack · ActionPause · ActionPlay · ActionPreviousTrack · ActionUnmute | — |
| Samsung Vacuum Robot | `7640156793826` | StaOpMode · StaRemoteCtrl · StaSuckPwr | — | ActGoHome · ActSetPwr · ActStart · ActStop | — |
| V-ZUG Adora (Dishwasher) | `7640156794403` | OperationMode · RemoteControl · SwStatus | CurrentProgram · SwVersion | Stop | EmptyingTankEnded · PowerSupplyInterrupted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramInterrupted · ProgramStarted · TopupSalt |
| V-ZUG Adora S (Washer) | `7640156794380` | OperationMode · RemoteControl · SwStatus | CurrentEndTime · CurrentProgram · SwVersion · WaterHardness | Pause · SmartStart | LooseningUpStarted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramStarted |
| V-ZUG Adora T (Dryer) | `7640156794397` | OperationMode · RemoteControl · SwStatus | CurrentEndTime · CurrentProgram · SwVersion | SmartStart · Stop | CreaseGuardFinishes · PowerSupplyInterrupted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramInterrupted · ProgramStarted |
| V-ZUG Combair (Oven) | `7640156794366` | OperationMode · RemoteControl · SwStatus | CurrentEndTime · CurrentFoodTemperature · CurrentProgram · CurrentTemperature · RemainingDuration · SetEndFoodTemperature · SetTemperature · SwVersion | BottomHeat · Grill · HotAir · PizzaPlus · SmartStart · Stop · StopIfNotTimed · TopBottomHeat · … | IntroduceFood · ProgramAborted · ProgramFinished · ProgramStarted · TimerFinished · … |
| V-ZUG Combi-Steam | `7640156794373` | OperationMode · RemoteControl · SwStatus | CurrentEndTime · CurrentProgram · CurrentTemperature · RemainingDuration · SwVersion · … | HotAir · SmartStart · Steam · Stop · … | ProgramAborted · ProgramFinished · ProgramStarted · RefillWater · … |
| Dornbracht Smart Water | `7640156792591` | StaHandShower · StaOutlet · StatusOpMode · StatusError · … | PossibleMappings · PropCScenarioName · PropRemainingWaterAmount | ActionShowerSettingOn · ActionShowerOff · ActionWaterOff · ActionScenarioOff · … | EvWaterTurnedOn · EvWaterTurnedOff · EvTargetWaterTempReached · EvFillingCompleted |
| Securiton SecuriSafe | `7640156794342` | armingPrevention · armingState | — | armExternal · armInternal · Alarm1 … Alarm6 · NoAlarm1 … NoAlarm6 | Alarm1 … Alarm6 · NoAlarm1 … NoAlarm6 · disarmed · extArmed · intArmed · … |
| Smarter iKettle 2.0 | `7640156791945` | operation | currentTemperature · defaulttemperature · waterLevel · … | boilandcooldown · heat · stop | BoilingStarted · BoilingFinished · KeepWarm · KettleAttached · KettleReleased · … |
| Tielsa Liftmodule | `7640156792850` | CurrentPosition · OperationMode | BottomHeight · DeviceType · LevelHeight · OffsetHeight · TopHeight | MoveDown · MoveToLevel · MoveUp · Stop · … | LevelReached · MaxPosReached · MinPosReached · MovingDown · MovingUp · … |

### Full walkthrough — washing machine

This example implements the complete VdcDb contract for GTIN `7640156794090` (Generic
Washing Machine): three states, five properties, six actions, three events.

```python
import asyncio
from pydsvdcapi import (
    VdcHost, Vdc, Device, Vdsd,
    DsUid, VdcCapabilities,
    ColorGroup, DeviceLifecycleState,
    DeviceState, DeviceEvent, DeviceProperty, DeviceActionDescription,
)
from pydsvdcapi.device_property import PROPERTY_TYPE_NUMERIC, PROPERTY_TYPE_STRING


async def main():
    host = VdcHost(name="Appliance Gateway", state_path="state.yaml")
    vdc = Vdc(
        host=host,
        implementation_id="x-myapp-appliances",
        name="Home Appliances",
        model="Appliance VDC",
        capabilities=VdcCapabilities(dynamic_definitions=True),
    )
    host.add_vdc(vdc)

    device = Device(vdc=vdc, dsuid=DsUid.random())
    vdsd = Vdsd(
        device=device,
        primary_group=ColorGroup.BLACK,
        name="Washing Machine",
        model="Generic Washer",
    )
    # Activate the VdcDb template — must match the GTIN exactly
    vdsd.oem_model_guid = "gs1:(01)7640156794090"

    # ── States ──────────────────────────────────────────────────────────────
    # Names MUST match the VdcDb registration for state-condition automation.
    # Options keys are integers; values are human-readable labels.
    door_state = DeviceState(
        vdsd=vdsd, ds_index=0, name="DoorState",
        options={0: "Closed", 1: "Open"},
        description="Door open/closed",
    )
    vdsd.add_device_state(door_state)

    op_mode = DeviceState(
        vdsd=vdsd, ds_index=1, name="OperationMode",
        options={0: "Inactive", 1: "Ready", 2: "Running", 3: "Pause", 4: "Finished"},
    )
    vdsd.add_device_state(op_mode)

    remote_ctrl = DeviceState(
        vdsd=vdsd, ds_index=2, name="RemoteControl",
        options={0: "Inactive", 1: "Active"},
    )
    vdsd.add_device_state(remote_ctrl)

    # ── Properties ──────────────────────────────────────────────────────────
    prog_name = DeviceProperty(
        vdsd=vdsd, ds_index=0, name="ProgramName", type=PROPERTY_TYPE_STRING,
    )
    vdsd.add_device_property(prog_name)

    prog_progress = DeviceProperty(
        vdsd=vdsd, ds_index=1, name="ProgramProgress",
        type=PROPERTY_TYPE_NUMERIC, min_value=0.0, max_value=100.0,
        resolution=1.0, siunit="%",
    )
    vdsd.add_device_property(prog_progress)

    remaining_time = DeviceProperty(
        vdsd=vdsd, ds_index=2, name="RemainingProgramTime",
        type=PROPERTY_TYPE_NUMERIC, min_value=0.0, siunit="s",
    )
    vdsd.add_device_property(remaining_time)

    spin_speed = DeviceProperty(
        vdsd=vdsd, ds_index=3, name="SpinSpeed",
        type=PROPERTY_TYPE_NUMERIC, min_value=0.0, max_value=1600.0,
        resolution=100.0, siunit="rpm",
    )
    vdsd.add_device_property(spin_speed)

    temperature = DeviceProperty(
        vdsd=vdsd, ds_index=4, name="Temperature",
        type=PROPERTY_TYPE_NUMERIC, min_value=0.0, max_value=90.0,
        resolution=10.0, siunit="°C",
    )
    vdsd.add_device_property(temperature)

    # ── Events ──────────────────────────────────────────────────────────────
    ev_started = DeviceEvent(vdsd=vdsd, ds_index=0, name="ProgramStarted")
    vdsd.add_device_event(ev_started)

    ev_finished = DeviceEvent(vdsd=vdsd, ds_index=1, name="ProgramFinished")
    vdsd.add_device_event(ev_finished)

    ev_local = DeviceEvent(vdsd=vdsd, ds_index=2, name="LocallyOperated")
    vdsd.add_device_event(ev_local)

    # ── Actions ─────────────────────────────────────────────────────────────
    # DeviceActionDescription takes vdsd as a positional argument.
    for i, (name, title) in enumerate([
        ("Cotton",       "Cotton"),
        ("DelicatesSilk","Delicates / Silk"),
        ("EasyCare",     "Easy Care"),
        ("Mix",          "Mix"),
        ("Stop",         "Stop"),
        ("Wool",         "Wool"),
    ]):
        vdsd.add_device_action_description(
            DeviceActionDescription(vdsd, ds_index=i, name=name, description=title)
        )

    # ── Action handler ───────────────────────────────────────────────────────
    async def handle_action(v: Vdsd, action_id: str, params: dict) -> None:
        if action_id == "Stop":
            await op_mode.update_value(0)           # → Inactive
        elif action_id in ("Cotton", "DelicatesSilk", "EasyCare", "Mix", "Wool"):
            await prog_name.update_value(action_id)
            await op_mode.update_value(2)           # → Running
            await ev_started.raise_event()

    vdsd.on_invoke_action = handle_action

    # ── Announce and start ───────────────────────────────────────────────────
    await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    await host.start()
    await asyncio.Event().wait()


asyncio.run(main())
```

Push live updates from your hardware integration whenever the physical device changes:

```python
# Door opened
await door_state.update_value(1)          # 1 = "Open" (option key)

# Cycle finished
await op_mode.update_value(4)             # 4 = "Finished"
await prog_progress.update_value(100.0)
await ev_finished.raise_event()
```

### Sonos — all six states must be pushed

The Sonos GTIN (`7640156794625`) pre-allocates six state slots. If any of the six
names is not pushed by the VDC, the state list in the configurator appears empty when
drilled into. All six names must be present in your `DeviceState` definitions and
pushed with initial values before the slot list appears populated:

`StatusInputMode` · `StatusMute` · `StatusOperationMode` · `StatusPlaybackModeRepeat`
· `StatusPlaybackModeShuffle` · `StatusPlaybackType`

---

## Part 7 — Advanced Topics

---

## 22. Device Lifecycle

### DeviceLifecycleState

`DeviceLifecycleState` is a `str` enum defined in `pydsvdcapi.enums`. Each vdSD
starts in `ACTIVE` state and can transition to any other state at runtime via
`set_lifecycle_state()`.

| State | String value | Meaning |
|---|---|---|
| `ACTIVE` | `"active"` | Device is fully operational. Responds to ping with pong. Reports `active=true`. |
| `INACTIVE` | `"inactive"` | Device is temporarily unavailable (e.g. powered off). Ping suppressed, `active=false` pushed to dSS. |
| `MAINTENANCE` | `"maintenance"` | Device is in a maintenance or update mode. Ping suppressed, `active=false` pushed. |
| `ERROR` | `"error"` | Device has encountered an error condition. Ping suppressed, `active=false` pushed. |
| `REMOVED` | `"removed"` | Device has been decommissioned. `VDC_SEND_VANISH` is sent to dSS and ping is suppressed. Transitioning to `REMOVED` is effectively one-way. |

### set_lifecycle_state()

```python
await vdsd.set_lifecycle_state(state: DeviceLifecycleState) -> None
```

Sets the lifecycle state and handles all required vdSM wire-protocol communication
automatically:

- If the `active` boolean changes (`True` ↔ `False`) and the device is already
  announced, a `VDC_SEND_PUSH_NOTIFICATION` is sent to dSS carrying the new
  `active` value. Push errors (`ConnectionError`, `OSError`) are logged and
  suppressed.
- If `state` is `REMOVED` and the device is announced, `VDC_SEND_VANISH` is also
  sent. Errors from the vanish call propagate to the caller.
- If the device has not yet been announced, the state is stored silently without
  any network communication.

### vdsd.lifecycle_state

Read-only property returning the current `DeviceLifecycleState`.

### vdsd.active

Computed read-only bool. Returns `True` only when
`lifecycle_state == DeviceLifecycleState.ACTIVE`. Do not set this directly; use
`set_lifecycle_state()`.

### vdsd.send_identify()

```python
await vdsd.send_identify() -> None
```

Sends a `VDC_SEND_IDENTIFY` notification to the vdSM, identifying this specific
vdSD by its dSUID. This is a fire-and-forget call — no response is expected. Use
it when the physical hardware signals a user-identification gesture (for example,
the user presses a pairing button on the device). The vdSM uses the incoming dSUID
to associate the physical device with a slot in the configurator without requiring
manual dSUID entry.

If the device is not yet announced or has no active session, the call is a no-op.

### vdsd.on_settings_changed

```python
async def handler(vdsd: Vdsd, changed: dict[str, Any]) -> None:
    ...

vdsd.on_settings_changed = handler
```

Called by `VdcHost` after DSS writes vdSD-level properties via `setProperty`. The
`changed` dict contains only the keys that were actually written — a subset of
`{"name", "zoneID", "progMode", "active"}`. A key appears whenever DSS sent it,
even if the value equals the current one.

When DSS marks a device active or inactive via `setProperty` (either as a top-level
`active` key or nested under `commonProperties`), the host calls
`set_lifecycle_state()` before firing this callback, so `vdsd.lifecycle_state` is
already updated when the callback runs.

```python
from pydsvdcapi import Vdsd, VdsdSettingsChangedCallback
from typing import Any

async def handle_vdsd_settings(vdsd: Vdsd, changed: dict[str, Any]) -> None:
    if "name" in changed:
        print(f"Device renamed to: {changed['name']}")
    if "zoneID" in changed:
        print(f"Moved to zone: {changed['zoneID']}")
    if "active" in changed:
        print(f"Active state changed: {changed['active']}")
        # vdsd.lifecycle_state is already updated at this point

vdsd.on_settings_changed = handle_vdsd_settings
```

> **Do not call `push_property` inside `on_settings_changed`.** DSS triggered the
> `setProperty` itself and already knows the new value. Pushing it back is
> redundant and sends the push notification *before* the `GENERIC_RESPONSE` for
> the `setProperty` is delivered, which some vdSM firmware versions log as an
> unexpected property notification. Use `on_settings_changed` only to update your
> integration's state in reaction to DSS-driven changes.

### vdsd.push_property()

```python
await vdsd.push_property(properties: dict[str, Any]) -> None
```

Pushes property changes from vDC to DSS via `VDC_SEND_PUSH_NOTIFICATION`. Use
this after changing a property **on the vDC side** (e.g. renaming the device or
updating its zone from your integration code) to notify DSS immediately without a
vanish+re-announce cycle. Do **not** call this in response to a DSS-initiated
`setProperty` (i.e. from inside `on_settings_changed`).

`properties` uses the same key names as `getProperty` responses:

```python
# After changing the device name in your integration:
vdsd.name = "Living Room Dimmer"
await vdsd.push_property({"name": vdsd.name})

# After moving the device to a different zone:
vdsd.zone_id = 12
await vdsd.push_property({"zoneID": vdsd.zone_id})
```

No-op when the device is not yet announced or has no active session. Connection
errors are logged as warnings and suppressed.

### Example: state transitions

```python
from pydsvdcapi.enums import DeviceLifecycleState

# Device starts ACTIVE by default after announce.

# Signal a temporary outage:
await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)

# Recover:
await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

# Signal an error (e.g. hardware fault detected):
await vdsd.set_lifecycle_state(DeviceLifecycleState.ERROR)

# Permanently remove the device from dSS:
await vdsd.set_lifecycle_state(DeviceLifecycleState.REMOVED)
# VDC_SEND_VANISH has been sent; do not re-announce this device.
```

---

## 23. Persistence (PropertyStore)

### Enabling auto-save

Pass a file path as `state_path` to `VdcHost` at construction time to enable
automatic YAML persistence:

```python
host = VdcHost(
    dsuid=host_dsuid,
    implementation_id="x-myintegration",
    state_path="/var/lib/myvdc/state.yaml",
)
```

When `state_path` is set, any change to a tracked property (device names, sensor
descriptions, output settings, etc.) triggers a debounced write. Rapid successive
changes are coalesced into a single write. The default debounce delay is
`AUTO_SAVE_DELAY = 1.0` second.

### flush()

To force an immediate write without waiting for the debounce delay:

```python
host.flush()
```

`flush()` is a no-op when no `state_path` was provided.

### What is persisted

The YAML file stores a complete structural snapshot of the entire vDC host:

- `VdcHost` common properties (name, model, version, etc.)
- `Vdc` properties (implementation ID, name, etc.)
- Device structure: which devices exist, their base dSUIDs, sub-device indices
- vdSD common properties (name, model, primary group, zone ID, progMode, model features, etc.)
- Output and output-channel descriptions and settings
- Scene settings (per scene: dontCare, ignoreLocalPriority, effect, channel values)
- Sensor input descriptions and settings
- Binary input descriptions and settings
- Button input descriptions and settings
- Device state descriptions and device property descriptions and values
- Device event descriptions
- Action descriptions, standard actions, custom actions

**Auto-save triggers:** any change to a tracked vdSD property (`name`, `zone_id`,
`prog_mode`, …) immediately schedules a debounced save. Component settings changes
(via `apply_settings`, `apply_scenes`) also trigger the same chain. There is no
need to call `host.flush()` manually in normal operation; call it before shutdown to
guarantee all pending writes are flushed to disk.

### What is NOT persisted

The following values are volatile runtime state and are intentionally excluded from
the YAML file:

- Sensor readings (current sensor values) — these change continuously and are
  re-acquired from the physical device after reconnection
- Output channel current values after a session disconnect
- Binary input state (current high/low readings)
- Button click state
- Device lifecycle state (`active` / `inactive`) — devices start as `ACTIVE` on
  every restart; the owning integration is responsible for restoring a non-active
  state if needed
- Dynamic actions (always runtime-only)
- Control values received from DSS

### Three-file persistence strategy

For a `state_path` of `/var/lib/myvdc/state.yaml`, the library automatically
manages three sibling files:

| File | Purpose |
|------|---------|
| `state.yaml` | Primary YAML file — the authoritative snapshot |
| `state.yaml.bak` | Backup of the previous save — used for recovery if the primary is corrupt |
| `state.yaml.tmp` | Atomic write staging — replaced onto the primary via `os.replace()` |

**Back up all three files together.** Backing up only `state.yaml` means a corrupt
primary at restore time has no `.bak` to fall back on.

### PropertyStore class

`PropertyStore` (in `pydsvdcapi.persistence`) is the underlying YAML store used
by `VdcHost` internally. It implements atomic writes with a backup/recovery
strategy:

- Writes go through `.tmp`, then atomically replace the primary via `os.replace()`.
- Before each write the previous primary is copied to `.bak`.
- On load, if the primary is missing or corrupt, the backup is tried automatically.

Users typically do not instantiate `PropertyStore` directly. Configure persistence
through `VdcHost(state_path=...)` and call `host.flush()` as needed.

### Caution: do not edit the YAML file while the library is running

The YAML file is human-readable and can be inspected at any time. However, do not
modify it by hand while the library is running: the next auto-save will overwrite
your changes.

---

## 24. Value Converters

### Purpose

Converters scale or transform values between the digitalSTROM protocol range and
the physical device range. They are small Python code snippets evaluated at
runtime. The converter system is available on:

- `OutputChannel` — uplink and downlink
- `SensorInput` — uplink
- `BinaryInput` — uplink
- `DeviceProperty` — uplink and downlink
- `DeviceState` — uplink and downlink

### Two directions

- **Uplink** (device → dS): applied when a value arrives from the physical
  device and is about to be reported to the dSS.
- **Downlink** (dS → device): applied when a value is received from the dSS
  and is about to be forwarded to the physical device.

### Snippet format

A converter is a string of Python code. The snippet operates on a pre-bound
variable `value` and may reassign it any number of times. The library
automatically appends `return value`, so no return statement is needed:

```python
# Single-line expression:
"value = value * 100.0 / 255.0"

# Multi-line block:
"""
mapping = {"stopped": 0, "paused": 1, "playing": 2}
value = mapping.get(str(value), 0)
"""

# None-guarded conversion:
"""
if value is None:
    value = 0.0
else:
    value = float(value) * 2.0
"""
```

Standard library modules can be imported inside the snippet if needed
(`import math`). The snippet is compiled eagerly at configuration time so syntax
errors surface immediately.

### API

```python
# On OutputChannel, SensorInput, BinaryInput, DeviceProperty, DeviceState:
component.set_uplink_converter(code: str | None)    # device → dS
component.set_downlink_converter(code: str | None)  # dS → device
```

Pass `None` to remove a converter and revert to pass-through.

The internal function `compile_converter(code)` in `pydsvdcapi.addons.converter`
compiles a snippet string into a callable. It is used internally and is not part
of the public component API, but can be called directly if custom converter logic
is needed.

### Concrete examples

```python
# Temperature: Fahrenheit from the device → Celsius for dS (uplink)
sensor.set_uplink_converter("value = (value - 32) / 1.8")

# Brightness: dS percentage (0–100) → device byte (0–255) (downlink)
channel.set_downlink_converter("value = int(round(value * 255.0 / 100.0))")

# Clamp a sensor reading to a valid range (uplink)
sensor.set_uplink_converter("value = max(0.0, min(100.0, value))")

# Remove a converter:
sensor.set_uplink_converter(None)
```

### Error handling

If the converter snippet raises an exception at runtime, a `WARNING` is logged
(including the component identity, direction, and error) and the **original
unconverted value** is returned unchanged. This fail-open behaviour ensures data
is never silently dropped.

---

## 25. Device Templates

### Purpose

A device template is a structural snapshot of a `Device` configuration (component
types, descriptions, settings, model features) with instance-specific values
stripped out. Templates allow you to save a device configuration once and later
restore it quickly, providing the per-instance details at restore time without
re-building the entire structure from scratch.

Templates are stored as YAML files on disk. The `template_path` parameter on
`Vdc` specifies the base directory.

### Saving a template

```python
vdc = Vdc(
    host=host,
    implementation_id="x-acme-light",
    template_path="/var/lib/myvdc/templates",
)

# After building and announcing a device, save its structural configuration:
vdc.save_template(
    device,
    template_type="generic",        # "generic" or "model"
    integration="x-acme-light",     # used as a sub-folder
    name="dimmable-light",          # file stem
    description="Standard dimmable light bulb",
)
# Saves to: /var/lib/myvdc/templates/generic_templates/x-acme-light/dimmable-light.yaml
```

`save_template()` raises `RuntimeError` if `template_path` was not set on the
`Vdc` instance.

### Loading and instantiating a template

```python
# Load the structural snapshot from disk:
tmpl = vdc.load_template(
    template_type="generic",
    integration="x-acme-light",
    name="dimmable-light",
)

# Supply per-instance required fields (at minimum: vdsd names):
tmpl.configure({"vdsds[0].name": "Kitchen Light"})

# Check that all required fields are set before instantiating:
if tmpl.is_ready():
    device = tmpl.instantiate(vdc=vdc, dsuid=my_dsuid)

    # Attach runtime callbacks (required callbacks are enumerated in
    # tmpl.required_callbacks):
    device.vdsds[0].output.on_channel_applied = my_channel_handler
    device.vdsds[0].on_identify = my_identify_handler

    await device.announce(session)
```

`instantiate()` raises `TemplateNotConfiguredError` if `is_ready()` is `False`.

### TemplateNotConfiguredError

Raised when `DeviceTemplate.instantiate()` is called before all required fields
have been supplied via `configure()`. The exception's `missing_fields` attribute
lists the field-path strings that are still `None`.

### AnnouncementNotReadyError

Raised by `Device.announce()` when required callbacks (recorded in the template's
`requiredCallbacks` manifest) have not been set on the instantiated device. The
exception's `missing_callbacks` attribute lists the callback-path strings that
are still unset.

Required callbacks are determined from the device structure at template-save time:

- `vdsds[N].on_invoke_action` — if the vdSD has action descriptions or standard actions
- `vdsds[N].on_identify` — if `"identification"` is in model features
- `vdsds[N].on_control_value` — if the vdSD uses control values
- `vdsds[N].output.on_channel_applied` — if the vdSD has an output

### When templates are useful

- **Multiple identical devices**: configure once, instantiate many times with
  different dSUIDs and names.
- **Devices re-created on restart**: use `state_path` (see Section 23) for full
  state persistence, or use templates to restore the device structure and re-attach
  callbacks without re-building components manually.

---

## 26. Session Constants

The following module-level constants are defined in `pydsvdcapi.vdc_host` and
`pydsvdcapi.session`. They can be imported directly if needed.

### From pydsvdcapi.vdc_host

```python
from pydsvdcapi.vdc_host import DEFAULT_VDC_PORT, AUTO_SAVE_DELAY
```

| Constant | Value | Description |
|---|---|---|
| `DEFAULT_VDC_PORT` | `8444` | Default TCP port the `VdcHost` listens on when no `port` argument is passed. |
| `AUTO_SAVE_DELAY` | `1.0` | Debounce delay in seconds before a triggered auto-save is written to disk. |

### From pydsvdcapi.session

```python
from pydsvdcapi.session import SUPPORTED_API_VERSION, MAX_SUPPORTED_API_VERSION
```

| Constant | Value | Description |
|---|---|---|
| `SUPPORTED_API_VERSION` | `2` | Minimum vDC API version accepted during the hello handshake. |
| `MAX_SUPPORTED_API_VERSION` | `4` | Maximum vDC API version accepted. Versions above this are rejected with `ERR_INCOMPATIBLE_API`. |

The library negotiates the API version during every new session. If the vdSM
announces an API version outside the range
`[SUPPORTED_API_VERSION, MAX_SUPPORTED_API_VERSION]` the session is immediately
closed with an incompatible-API error.
