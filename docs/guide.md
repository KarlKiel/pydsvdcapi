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

## 4. Architecture

### Entity hierarchy

```
VdcHost          — gateway process, owns the TCP socket and DNS-SD announcement
└── Vdc          — logical connector grouping related devices (one per integration type)
    └── Device   — library grouping for a single piece of hardware
        └── Vdsd — the actual protocol device entity (one dSUID each)
```

### Device vs Vdsd

`Device` groups one or more `Vdsd` instances that share the same physical hardware —
identified by the same base dSUID (bytes 0–15). Each `Vdsd` represents one
addressable software sub-device; the sub-device index is stored in byte 17 of the
dSUID.

Example: a 4-button remote is **one Device** with **four Vdsd instances** (sub-device
indices 0–3). All four share bytes 0–15 of the dSUID and differ only in byte 17.

### Protocol entities

The vDC API protocol knows three first-class entities that are announced to the
vdSM: `VdcHost`, `Vdc`, and `Vdsd`. `Device` is a **library-level grouping only** —
it has no protocol representation of its own.

### Naming quick reference

| Class | Role |
|-------|------|
| `VdcHost` | Gateway process; owns the TCP socket |
| `Vdc` | Logical connector (one per integration type) |
| `Device` | Library grouping for one piece of hardware (not a protocol entity) |
| `Vdsd` | A single virtual device with its own dSUID |

---

## 5. VdcHost Reference

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

## 6. Vdc Reference

`Vdc` is a logical connector that groups related virtual devices. Each distinct
integration type (e.g. KNX lights, a cloud thermostat API) should have its own
`Vdc`.

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

## 7. Device and Vdsd Reference

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
- **`lifecycle_state`** — read-only property returning the current
  `DeviceLifecycleState`.
- **`async set_lifecycle_state(state)`** — set lifecycle state; handles all vdSM
  communication (`ACTIVE` pushes the `active` property, `REMOVED` triggers
  `VDC_SEND_VANISH`, non-`ACTIVE` states suppress the session pong).
- **`async send_identify()`** — send a `VDC_SEND_IDENTIFY` notification (fire-and-
  forget); use this when the user presses a physical pairing/identify button on the
  hardware.

---

## 8. DsUid — Unique Identifiers

Every entity in the dS system has a **17-byte dSUID** (digitalSTROM Unique
Identifier). The canonical string form is **34 upper-case hex characters**, e.g.
`"198C033E330755E78015F97AD093DD1C00"`. The first 16 bytes encode a UUID or an
EPC96 identifier; byte 17 (index 16, zero-based) is the **sub-device index**.

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
