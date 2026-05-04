# dSS modelFeatures — Complete Reference (Firmware Re-Engineering)

> Source: `dss-mainline-master` firmware, reverse-engineered from source.
> Key files: `src/model/modelconst.h`, `src/model/modelconst.cpp`, `src/model-features.cpp`,
> `src/model/device.cpp`, `src/model/busscanner.cpp`, `src/web/handler/jsonhelper.cpp`,
> `src/backend-vdcs.cpp`, `src/vdc-connection.cpp`

---

## Table of Contents

1. [Architecture — How modelFeatures Flow Through dSS](#1-architecture--how-modelfeatures-flow-through-dss)
2. [VDC Feature Registration: Two Paths](#2-vdc-feature-registration-two-paths)
3. [Complete ModelFeatureId Reference (all 65 features)](#3-complete-modelfeatureid-reference)
4. [Predefined Feature Sets by Device Color / Class](#4-predefined-feature-sets-by-device-color--class)
5. [Feature Semantics by Category](#5-feature-semantics-by-category)
6. [VDC Device Guidance — What to Declare and What to Expect](#6-vdc-device-guidance)
7. [Other UI-Controlling VDC Properties](#7-other-ui-controlling-vdc-properties)
8. [Known Firmware Limitations](#8-known-firmware-limitations)

---

## 1. Architecture — How modelFeatures Flow Through dSS

### 1.1 Two Separate Feature Storage Systems

There are **two independent systems** in the dSS firmware that carry model feature data, and they are not connected:

| System | Type | Source | What reads it | Accessible via |
|---|---|---|---|---|
| `Device::m_modelFeatures` | `std::map<ModelFeatureId, bool>` | Hardware-derived at runtime | `device.getModelFeatures()` | `/apartment/getDevices` JSON |
| `ModelFeatures` database | `m_dynamicFeatureMatrix[color][modelUID]` | VDC announcement + static presets | Frontend app via REST | `/apartment/getModelFeatures` |

For **physical hardware devices** both systems are populated. For **classic TCP/IP VDC devices** (`BusMember_vDC`, i.e. Python library devices), both systems are populated when the DSM layer correctly encodes `primaryGroup` into FunctionID. For **backend VDC devices** (`BusMember_backendVdc`, cloud/HTTP), features fail to register. See §2 for details.

### 1.2 Physical Device Feature Flow

```
Device specification (FunctionID, RevisionID, DeviceType)
  │
  └─→ Device::updateModelFeatures()   [device.cpp:2445]
        └─→ m_modelFeatures           [per-device map]
              └─→ jsonhelper.cpp:76   → "modelFeatures" in getDevices JSON
```

### 1.3 VDC Device Feature Flow

There are **two distinct VDC paths** with fundamentally different behavior:

**Path A — Classic TCP/IP VDC (`BusMember_vDC`, used by the Python library):**
```
VDC announces modelFeatures and primaryGroup via vdcapi (TCP/IP)
  │
  └─→ DSM layer (hardware or vDSM) translates primaryGroup → FunctionID bits[15:12]
        e.g. primaryGroup=1 (GE/Yellow) → FunctionID=0x1000
  │
  └─→ busscanner: getDevicesInZone() → DeviceInfo_by_index() returns spec.FunctionID
        setupBaseDevice(dev, spec)  →  m_FunctionID = spec.FunctionID  [non-zero!]
  │
  └─→ VdcHelper::getSpec()            [vdc-connection.cpp]
        Filters: only boolean=true features
        Converts: string → ModelFeatureId enum
        Stores: VdsdSpec_t.modelFeatures  (set<ModelFeatureId>)
  │
  └─→ busscanner: dev->setVdsdSpec()  → stores spec on device
  │
  └─→ busscanner: ModelFeatures::setFeatures(getDeviceClass(), modelUID, features)
        getDeviceClass() reads m_FunctionID bits[15:12] → valid ColorID (e.g. 1 = GE)
        setFeatures(1, modelUID, features)  → SUCCEEDS → features stored in ModelFeatures DB
  │
  └─→ /apartment/getModelFeatures returns features for this modelUID ✓
```

**Path B — Backend VDC (`BusMember_backendVdc`, cloud/HTTP devices):**
```
VDC device registered via putVdcDevice() [backend-vdcs.cpp]
  │
  └─→ dev->setVdsdSpec(spec)  →  m_FunctionID remains 0 (never set)
  │
  └─→ busscanner block is bypassed entirely (see busscanner.cpp lines 820-822)
        setFeatures() is never called
        features NOT registered in ModelFeatures DB
```

### 1.4 Key Source Files

| File | Role |
|---|---|
| `src/model/modelconst.h` | `ModelFeatureId` enum (all 65 values), ColorID, GroupID constants |
| `src/model/modelconst.cpp` | String↔enum mapping for all ModelFeatureIds |
| `src/model-features.cpp` | Predefined feature sets per physical device model; `setFeatures()`, `getFeatures()` |
| `src/model/device.cpp` | `updateModelFeatures()` (hardware-derived), `getDeviceClass()`, `isValveDevice()` |
| `src/model/busscanner.cpp` | VDC device registration, feature registration attempt |
| `src/vdc-connection.cpp` | `VdcHelper::getSpec()` — parses VDC announcement including modelFeatures |
| `src/backend-vdcs.cpp` | `putVdcDevice()` — stores VdsdSpec on device |
| `src/web/handler/jsonhelper.cpp` | `toJSON()` — serializes device to JSON including modelFeatures |
| `src/web/handler/apartmentrequesthandler.cpp` | REST endpoints `getModelFeatures`, `getModelFeatures2` |

---

## 2. VDC Feature Registration: Two Paths

### 2.1 The Feature Registration Code (busscanner.cpp)

When a classic `BusMember_vDC` device is scanned, `busscanner.cpp` stores its features in the ModelFeatures database:

```cpp
// busscanner.cpp lines 518-523
try {
  auto& modelFeatures = *m_Apartment.getModelFeatures();
  modelFeatures.setFeatures(static_cast<int>(dev->getDeviceClass()),
                             vdsdSpec.modelUID,
                             std::vector(vdsdSpec.modelFeatures.begin(),
                                         vdsdSpec.modelFeatures.end()));
} catch (const std::exception& e) {
  DS_ERROR("Failed to register model features.", e);  // ← error if color invalid
}
```

`dev->getDeviceClass()` reads `m_FunctionID` bits [15:12]:
```cpp
DeviceClasses_t Device::getDeviceClass() const {
  if (m_FunctionID == 0) return DeviceClasses_t::DEVICE_CLASS_INVALID;  // = -1
  int c = (m_FunctionID & 0xf000) >> 12;
  switch (c) {
    case 1: return DEVICE_CLASS_GE;  // 0x1000
    case 2: return DEVICE_CLASS_GR;  // 0x2000
    // ...
  }
}
```

`ModelFeatures::setFeatures()` validates color ∈ [1…9]; color=-1 throws `"can not save feature: unsupported device color"`.

### 2.2 Path A: Classic VDC (`BusMember_vDC`, Python library) — Features WORK

For classic VDC devices (TCP/IP, Python library), `m_FunctionID` is set from the DSM layer:

1. `busscanner.scanZone()` calls `m_Interface.getDevicesInZone(dsm->getDSID(), zone)`
2. `dsmQueryBus()` routes to `m_ds485Query` for `BusMember_vDC`
3. `DSStructureQueryBusInterface::getDevicesInZone()` calls `DeviceInfo_by_index(m_DSMApiHandle, ...)` which returns `spec.FunctionID`
4. The DSM layer translates the VDC's `primaryGroup` into FunctionID bits[15:12] (e.g. `primaryGroup=1` → `FunctionID=0x1000`)
5. `setupBaseDevice(dev, spec)` → `dev->setPartiallyFromSpec(spec)` → `m_FunctionID = spec.FunctionID` (non-zero)
6. `getDeviceClass()` returns valid color → `setFeatures(color, modelUID, features)` **SUCCEEDS**

**Result for `BusMember_vDC`:** Features registered in ModelFeatures DB → `/apartment/getModelFeatures` returns them → configurator frontend can use them. This is why empirical testing shows `modelFeatures` influencing UI behavior.

### 2.3 Path B: Backend VDC (`BusMember_backendVdc`) — Features FAIL

For backend VDC devices (cloud/HTTP API), the entire busscanner flow is bypassed:

1. `backend-vdcs.cpp:putVdcDevice()` stores VdsdSpec but never sets `m_FunctionID`
2. `busscanner.cpp` lines 820-822: `case BusMember_backendVdc: break;` — explicitly skipped
3. `m_FunctionID` remains 0 → `getDeviceClass()` returns `DEVICE_CLASS_INVALID = -1`
4. Feature registration is never even attempted for backend VDC devices

**Result for `BusMember_backendVdc`:** Features never registered.

### 2.4 Feature Paths Summary

| Path | Physical device | Classic VDC (`BusMember_vDC`) | Backend VDC (`BusMember_backendVdc`) |
|---|---|---|---|
| `m_modelFeatures` (device JSON) | Populated from hardware | Empty (hardware-only) | Empty |
| ModelFeatures database (`getModelFeatures`) | From predefined static sets | **Populated from VDC announcement** ✓ | Never registered |
| `m_FunctionID` | From hardware spec | From DSM layer (`DeviceInfo_by_index`) | 0 (never set) |

**Note:** `device.getModelFeatures()` (the per-device map, shown in device JSON) is still empty for VDC devices — it is only populated by `updateModelFeatures()` for 5 hardware-specific features. The configurator uses `/apartment/getModelFeatures` (the database keyed by `color+modelUID`), NOT the per-device JSON field.

### 2.5 Only Backend Check of modelFeatures in dSS Backend

There is exactly **one place** in the entire dSS backend C++ that reads modelFeatures for functional logic:

```cpp
// device.cpp:3048
bool Device::supportsApartmentApplications() const {
  return m_modelFeatures.count(ModelFeatureId::apartmentapplication) > 0;
}
```

This checks `m_modelFeatures` (the per-device map), which is **never populated for VDC devices** (neither classic nor backend). All other feature-related UI behavior is driven by the external configurator frontend reading `/apartment/getModelFeatures`.

### 2.6 What This Means for VDC Implementation

For **classic VDC devices** (`BusMember_vDC`, Python library):
- Features declared in `modelFeatures` **do** propagate to the ModelFeatures database (keyed by `color+modelUID`)
- The configurator frontend **can use** them to show/hide UI panels
- `primaryGroup` additionally controls the color band, default scenes, and category icon

For **backend VDC devices** (`BusMember_backendVdc`):
- Declared `modelFeatures` are **never registered** in the ModelFeatures DB
- `primaryGroup` remains the only UI routing mechanism

---

## 3. Complete ModelFeatureId Reference

All 65 features defined in `src/model/modelconst.h` (enum class `ModelFeatureId`) with their string names from `src/model/modelconst.cpp`.

| ID | String Name | Category | Description / Physical Usage |
|---|---|---|---|
| 0 | `dontcare` | Output | "Don't care" scene flag for the output value |
| 1 | `blink` | Blink | Device supports blink/flash output behavior |
| 2 | `ledauto` | LED | LED indicator auto-mode (follows output state). **NOT supported for TCP/IP VDC** — device LED is not API-controlled; no vdSD property reflects the state. |
| 3 | `leddark` | LED | LED indicator dark/inverted mode. **NOT supported for TCP/IP VDC** — same reason as `ledauto`; hardware-only. |
| 4 | `transt` | Output | Configurable transition/fade time |
| 5 | `outmode` | Output | Output mode selection (dimmer/switch/disabled). **NOT supported for TCP/IP VDC** — UI writes hardware mode via DS485 `CfgFunction_Mode`; value stored in dSS `m_OutputMode` and never forwarded to VDC. |
| 6 | `outmodeswitch` | Output | Switch-only output mode variant. **NOT supported for TCP/IP VDC** — same DS485-only write path as `outmode`. |
| 7 | `outvalue8` | Output | 8-bit (0–255) output value control |
| 8 | `pushbutton` | Button | Device has push-button input(s) |
| 9 | `pushbdevice` | Button | Push-button can be routed to device level |
| 10 | `pushbsensor` | Button | Push-button sensor function (Black/UMR devices) |
| 11 | `pushbarea` | Button | Push-button can be routed to area level |
| 12 | `pushbadvanced` | Button | Advanced push-button configuration available |
| 13 | `pushbcombined` | Button | Combined push-button modes (SDS20/22 2-button). **NOT supported for TCP/IP VDC** — `ButtonDescription/buttonType` is **read-only** in the VDC protocol and hardware-specific to physical TKM/SDS devices; the value does not align with the UI options. |
| 14 | `shadeprops` | Shade | Shade/blind movement properties configurable |
| 15 | `shadeposition` | Shade | Shade/blind position tracking supported |
| 16 | `motiontimefins` | Shade | Venetian blind slat rotation time configurable |
| 17 | `optypeconfig` | Output | Output type configurable (switch/dimmer selector) |
| 18 | `shadebladeang` | Shade | Venetian blind blade angle configurable |
| 19 | `highlevel` | Joker | High-level scene/application control |
| 20 | `consumption` | Joker | Power consumption measurement/reporting |
| 21 | `jokerconfig` | Joker | Joker device group-assignment UI |
| 22 | `akmsensor` | AKM | AKM bus sensor input |
| 23 | `akminput` | AKM | AKM bus digital input |
| 24 | `akmdelay` | AKM | AKM input delay configurable |
| 25 | `twowayconfig` | Config | Two-way/bidirectional operation configurable. **NOT supported for TCP/IP VDC** — same reason as `pushbcombined`; `buttonType` is read-only and hardware-specific. |
| 26 | `outputchannels` | Output | Multiple output channels supported (RGB, dimmer+relay) |
| 27 | `heatinggroup` | Heating | Heating application group assignment UI |
| 28 | `heatingoutmode` | Heating | Heating output mode configurable. **NOT supported for TCP/IP VDC** — UI writes hardware mode via DS485; stored in dSS `m_OutputMode`, never forwarded to VDC. |
| 29 | `heatingprops` | Heating | Heating/valve properties section shown |
| 30 | `pwmvalue` | Heating | PWM duty cycle value configurable |
| 31 | `valvetype` | Heating | Attached valve/terminal device type selectable |
| 32 | `extradimmer` | Output | Extra dimmer circuit on UMV200/UMV210 (physical relay+dimmer combo). **NOT supported for TCP/IP VDC** — hardware-specific; configuration writes via DS485. For VDC, use separate output channels. |
| 33 | `umvrelay` | Output | Relay toggle on UMV200/UMV210 (companion to `extradimmer`). **NOT supported for TCP/IP VDC** — same hardware-specific DS485 path. |
| 34 | `blinkconfig` | Blink | Blink pattern/rate configurable |
| 35 | `umroutmode` | Output | UMR-200 output mode configurable. **NOT supported for TCP/IP VDC** — UMR200 is always a physical DS485 bus device; value never reaches VDC. |
| 36 | `locationconfig` | Shade | Shade/awning installation location configurable |
| 37 | `windprotectionconfigawning` | Shade | Wind protection settings for awnings |
| 38 | `windprotectionconfigblind` | Shade | Wind protection settings for venetian blinds |
| 39 | `impulseconfig` | Config | Impulse/pulse output configurable |
| 40 | `outmodegeneric` | Output | Generic output mode (non-specific). **VDC support unclear** — not assigned to any DS485 device; may be VDC-intended for Joker devices, but mode write path is DS485-only with no confirmed VDC property write-back. |
| 41 | `outconfigswitch` | Config | Output configuration for switch behavior |
| 42 | `temperatureoffset` | Climate | Temperature sensor offset configurable |
| 43 | `apartmentapplication` | Special | Device supports apartment-level application routing |
| 44 | `ftwtempcontrolventilationselect` | Climate | FTW thermostat ventilation mode selector |
| 45 | `ftwdisplaysettings` | Climate | FTW thermostat display settings. **NOT supported for TCP/IP VDC** — hardware-specific to physical SK204/FTW display panels; no VDC equivalent. |
| 46 | `ftwbacklighttimeout` | Climate | FTW thermostat backlight timeout. **NOT supported for TCP/IP VDC** — same hardware-specific reason as `ftwdisplaysettings`. |
| 47 | `ventconfig` | Climate | Ventilation configuration panel |
| 48 | `fcu` | Climate | Fan Coil Unit (FCU) specific options |
| 49 | `pushbdisabled` | Button | Push-button input present but disabled (ZWS205) |
| 50 | `consumptioneventled` | Joker | Consumption event LED indicator. **NOT supported for TCP/IP VDC** — controls a hardware LED on the end device; no VDC parameter handles this. |
| 51 | `consumptiontimer` | Joker | Consumption measurement timer. NOT TESTED for TCP/IP VDC — may be stored on dSS/vdSM side. |
| 52 | `jokertempcontrol` | Joker | Joker device temperature control mode |
| 53 | `dimtimeconfig` | Config | Dimming time (ramp speed) configurable |
| 54 | `outmodeauto` | Output | Adds "auto-detect" option to the dimmer mode selector (DS485 mode ID 31). **NOT supported for TCP/IP VDC** — writes via DS485 `CfgFunction_Mode`; also blocks "Edit Device Values" UI for multi-channel outputs. |
| 55 | `dimmodeconfig` | Config | Dimming mode (leading/trailing edge etc.) configurable. **NOT supported for TCP/IP VDC** — relates to physical dimmer hardware capability; VDC devices do not receive this information and cannot handle the setting. |
| 56 | `identification` | Special | Device supports identification/locate function |
| 57 | `setumr200config` | Special | UMR200 extended configuration UI |
| 58 | `extendedvalvetypes` | Heating | Extended valve type options |
| 59 | `customtransitiontime` | Config | Custom (non-preset) transition time input |
| 60 | `outmodetempcontrol` | Output | Adds temperature-control modes to the mode selector (regulation PWM=64, regulation switch=65). **NOT supported for TCP/IP VDC** — same DS485 `CfgFunction_Mode` write path as `outmode`. |
| 61 | `outmodeenoceanvalve` | Special | EnOcean valve output mode. Auto-injected by `busscanner.cpp` for EnOcean VDC container devices. **NOTE:** Although EnOcean devices are VDC-connected, the mode configuration UI still writes via DS485 `CfgFunction_Mode` — there is no VDC write-back path. This is a firmware design limitation. **Firmware-managed — do NOT set from a vDC.** |
| 62 | `operationlock` | Special | Operation lock functionality (KL hardware only) |
| 63 | `grkl387workaround` | Special | GR-KL387 hardware workaround flag (internal). **NOT supported for TCP/IP VDC** — firmware-injected for specific KL 0x387 hardware bug; meaningless for VDC. |
| 64 | `customactivityconfig` | Special | Custom activity/scene configuration UI |

> **Note on feature string serialization:** Features are serialized by string name (not integer ID) in the VDC protocol and JSON API. An unrecognized name is logged as a warning and discarded by `VdcHelper::getSpec()`.

---

## 4. Predefined Feature Sets by Device Color / Class

These are the **static, compile-time feature sets** from `src/model-features.cpp` for physical hardware devices. They serve as the authoritative reference for what each feature is intended to enable. VDC devices should declare the equivalent set for their closest physical hardware analog.

The color/class mapping (from `src/model/modelconst.h`):

| ColorID | DeviceClass | Group | Application |
|---|---|---|---|
| 1 | DEVICE_CLASS_GE | GroupIDYellow (1) | Lighting / Dimming |
| 2 | DEVICE_CLASS_GR | GroupIDGray (2) | Shadow / Blinds / Shading |
| 3 | DEVICE_CLASS_BL | GroupIDHeating (3) | Heating / Climate |
| 4 | DEVICE_CLASS_TK | GroupIDCyan (4) | Audio |
| 5 | DEVICE_CLASS_MG | GroupIDViolet (5) | Video (no predefined sets) |
| 6 | DEVICE_CLASS_RT | GroupIDRed (6) | Security (deprecated) |
| 7 | DEVICE_CLASS_GN | GroupIDGreen (7) | Access (deprecated) |
| 8 | DEVICE_CLASS_SW | GroupIDBlack (8) | Joker |
| 9 | DEVICE_CLASS_WE | — | White (no predefined sets) |

---

### 4.1 Yellow / GE — Lighting & Dimming (ColorID 1)

All yellow devices support standard output and push-button features. Newer 300-generation devices add advanced dimming controls.

**KM220 / KM2 / SDM20** (Standard dimmer, older generation):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig
```

**KL200** (Switch-mode variant):
```
dontcare, blink, identification, ledauto, transt, outmodeswitch, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig
```

**TKM210** (Touch keypad, no ledauto):
```
dontcare, blink, identification, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig
```

**TKM220 / TKM230** (Touch keypad, button-only, no output features):
```
blink, identification, leddark,
pushbutton, pushbarea, pushbadvanced
```

**TKM2** (Legacy touch keypad, button-only Yellow variant; distinct from TKM220/TKM230 — adds `impulseconfig` and `blinkconfig`):
```
blink, identification, leddark,
pushbutton, pushbarea, pushbadvanced,
impulseconfig, blinkconfig
```

**KM300 / ZWD300** (300-generation, advanced dimming):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
outconfigswitch, impulseconfig, blinkconfig,
dimtimeconfig, outmodeauto, dimmodeconfig, customtransitiontime
```

**TKM300** (300-generation touch keypad with AKM):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced, pushbsensor,
akminput, akmsensor, akmdelay,
outconfigswitch, impulseconfig, blinkconfig,
dimtimeconfig, outmodeauto, dimmodeconfig, customtransitiontime,
setumr200config
```

**SDM300 / SDM301** (300-generation sensor dimmer):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig,
dimtimeconfig, outmodeauto, dimmodeconfig, customtransitiontime
```

**SDS210** (2-way switch):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
twowayconfig, outconfigswitch, impulseconfig, blinkconfig
```

**SDS20 / SDS22** (2-button 2-way):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced, pushbcombined,
twowayconfig, outconfigswitch, impulseconfig, blinkconfig
```

**SDS2** (Standard 2-way):
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
twowayconfig, outconfigswitch, impulseconfig, blinkconfig
```

**ZWS2** (Z-Wave switch, no outmode):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig
```

**UMV204** (Multi-function, no extradimmer):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
outconfigswitch, impulseconfig, blinkconfig
```

**UMV200** (Multi-function with relay):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
extradimmer, umvrelay,
outconfigswitch, impulseconfig, blinkconfig
```

**UMV210** (Multi-function with multi-channel):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
extradimmer, umvrelay, outputchannels,
outconfigswitch, impulseconfig, blinkconfig
```

**Key Yellow features for VDC dimmer device:**
Minimum set for a simple dimmer: `dontcare, outvalue8, transt, ledauto, identification`
Full modern dimmer: add `outmode, dimtimeconfig, outmodeauto, dimmodeconfig, customtransitiontime`

---

### 4.2 Grey / GR — Shadow / Blinds / Shading (ColorID 2)

> **Important:** Grey (GroupIDGray=2) means the Shadow/Shading application group. The grey hardware color of push-button devices is a physical hardware indicator color — it is **not** the same as primaryGroup=2. Push-button-only VDC devices should use Black (joker) or the specific target group.

All GR devices are shade/blind actuators. They do NOT have `outvalue8`, `transt`, or `outmode` (no dimmer output). The primary output features are position and movement properties.

**KL210** (Awning/roller blind, with push-buttons):
```
dontcare, blink, identification, ledauto,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
shadeprops, shadeposition,
locationconfig, windprotectionconfigawning
```

**KL220** (Venetian blind, with push-buttons):
```
dontcare, blink, identification, ledauto,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
shadeprops, shadeposition, motiontimefins, shadebladeang,
locationconfig, windprotectionconfigblind
```

**KL230** (Venetian blind, no push-buttons):
```
dontcare, blink, identification, ledauto,
shadeprops, shadeposition, motiontimefins, shadebladeang,
locationconfig, windprotectionconfigblind
```

**KL300** (Terminal block 0 — main blind control):
```
dontcare, identification, ledauto,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
shadeprops, shadeposition, motiontimefins, shadebladeang,
locationconfig, windprotectionconfigblind
```

**KL300** (Terminal block 1 — AKM sensor input):
```
identification,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
akmsensor, akminput, akmdelay
```

**HKL330** (Heavy-duty blind):
```
dontcare, blink, identification, ledauto,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
shadeprops, shadeposition, motiontimefins, shadebladeang,
locationconfig, windprotectionconfigblind
```

**KL2** (Legacy blind actuator):
```
dontcare, blink, identification, ledauto,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
shadeprops, shadeposition,
locationconfig, windprotectionconfigblind
```

**TKM2** (Touch keypad, button-only):
```
blink, identification, leddark,
pushbutton, pushbarea, pushbadvanced
```

**Key Grey features for VDC shade device:**
Roller blind: `dontcare, shadeprops, shadeposition, identification`
Venetian blind: add `motiontimefins, shadebladeang`
With wind protection: add `locationconfig, windprotectionconfigblind` or `windprotectionconfigawning`

---

### 4.3 Blue / BL — Heating & Climate (ColorID 3)

**KM200 / KM300 / SDS200** (Standard heating valve actuator):
```
dontcare, ledauto, identification, outvalue8,
pushbutton, pushbdevice, pushbadvanced,
heatinggroup, heatingoutmode, heatingprops, pwmvalue, valvetype
```

**UMV200-BL** (Multi-function in heating application, NOT a full valve device):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
extradimmer, umvrelay,
outconfigswitch, impulseconfig, blinkconfig,
heatinggroup
```
(Note: only `heatinggroup`, not the full valve set)

**KL2-BL** (Minimal climate indicator):
```
dontcare, ledauto, identification
```

**SK204 / BL-SK204** (Wireless thermostat/room controller):
```
temperatureoffset,
ftwtempcontrolventilationselect, ftwdisplaysettings, ftwbacklighttimeout,
ventconfig, identification
```

**Key Blue features for VDC heating valve:**
Standard valve: `dontcare, outvalue8, heatinggroup, heatingoutmode, heatingprops, pwmvalue, valvetype, identification`

**Note on `isValveDevice()`:** This function returns `true` only for physical hardware with specific device type/revision/class values. VDC devices always return `false`, blocking `setHeatingGroup`, `setValvePwmMode`, `getValveType` API calls regardless of declared features. See §8.

---

### 4.4 Cyan / TK — Audio (ColorID 4)

**TKM2** (Audio keypad):
```
blink, identification, leddark,
pushbutton, pushbarea
```

No output features. TK devices in the static set are button-only.

---

### 4.5 Red / RT — Security (ColorID 6, deprecated)

**KM2-RT**:
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8
```

**TKM2-RT**:
```
dontcare, blink, identification, transt, outmode, outvalue8
```

**SDM2-RT**:
```
blink, identification, leddark, outmode, outvalue8
```

---

### 4.6 Green / GN — Access (ColorID 7, deprecated)

**KM2-GN**:
```
dontcare, blink, identification, ledauto, transt, outmode, outvalue8
```

**TKM2-GN**:
```
dontcare, blink, identification, transt, outmode, outvalue8
```

---

### 4.7 Black / SW — Joker (ColorID 8)

Joker devices are generalist/multi-purpose devices. The core joker features (`jokerconfig`, `highlevel`) appear on all.

**TKM2-SW** (Button-only joker):
```
blink, identification, leddark,
pushbutton, pushbarea, pushbadvanced,
highlevel, jokerconfig, twowayconfig
```

**KL2-SW / ZWS2-SW** (Output joker with consumption):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced,
optypeconfig, highlevel, consumption, jokerconfig,
outconfigswitch, impulseconfig, blinkconfig
```

**KL213 / KL214** (Output joker, no push-button):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
optypeconfig, highlevel, consumption, jokerconfig,
outconfigswitch, impulseconfig, blinkconfig
```

**SDS20-SW / SDS22-SW** (Button joker, 2-way):
```
blink, identification, leddark,
pushbutton, pushbarea, pushbadvanced,
highlevel, jokerconfig, twowayconfig
```

**AKM2** (AKM sensor input module):
```
akmsensor, akminput, akmdelay, identification
```

**ZWS205** (Z-Wave multi-function with heating):
```
dontcare, blink, identification, ledauto, transt, outvalue8,
pushbutton, pushbdevice, pushbarea, pushbadvanced, pushbdisabled,
heatingprops, highlevel, consumption, consumptioneventled, consumptiontimer,
jokerconfig, jokertempcontrol,
outconfigswitch, impulseconfig,
valvetype, blinkconfig, outmodeswitch, outmodetempcontrol
```

**UMR200** (Universal metering relay):
```
blink, identification, dontcare, outvalue8,
pushbutton, pushbsensor, pushbarea, pushbadvanced,
highlevel, jokerconfig, twowayconfig,
akminput, akmsensor, akmdelay,
blinkconfig, impulseconfig,
umroutmode, outconfigswitch, outmodetempcontrol
```

**SK20** (Temperature sensor):
```
temperatureoffset, identification
```

**TNY2** (Tiny module):
```
identification
```

**SKM300** (Sensor keypad):
```
identification, dontcare,
pushbutton, pushbsensor, pushbarea, pushbadvanced,
highlevel, jokerconfig, twowayconfig,
akminput, akmsensor, akmdelay,
setumr200config
```

---

### 4.8 Violet / MG and White / WE

No predefined feature sets exist in the firmware for ColorIDViolet (5) or ColorIDWhite (9). The `staticFeatureMatrix` entries for these are `nullptr`.

---

## 5. Feature Semantics by Category

### 5.1 Core Output Features

| Feature | ID | Meaning |
|---|---|---|
| `dontcare` | 0 | Device supports the "don't care" flag per scene. Scene can be set to "don't care" = don't change output when scene is called. |
| `outvalue8` | 7 | Output has an 8-bit (0–100% or 0–255) numeric value. Enables the output value slider. |
| `transt` | 4 | Transition/fade time is configurable. Adds transition time input fields to configuration UI. |
| `ledauto` | 2 | Device's LED indicator follows output state automatically. Enables LED auto-mode option. |
| `leddark` | 3 | LED indicator in dark/inverted mode (LED off = device on). Replaces `ledauto` on button-only and touch devices. |
| `outmode` | 5 | Output mode is selectable (e.g., dimmer/switch/disabled). Enables output mode dropdown. |
| `outmodeswitch` | 6 | Output mode forced to switch (only on/off). Present instead of `outmode` on switch-only devices. |
| `outmodegeneric` | 40 | Generic output mode, non-specific variant. |
| `outmodeauto` | 54 | Output mode with automatic detection/switching (300-gen dimmers). |
| `outmodetempcontrol` | 60 | Output mode with integrated temperature control. |
| `outmodeenoceanvalve` | 61 | EnOcean valve output mode. Only added automatically by busscanner for EnOcean-container valve devices. |
| `outputchannels` | 26 | Device has multiple output channels (RGB dimmer+relay). Enables multi-channel output configuration. |
| `extradimmer` | 32 | Secondary dimmer output channel present (UMV devices). |
| `umvrelay` | 33 | Relay output on UMV multi-function device. |

### 5.2 Push-Button Features

These enable various push-button configuration UI panels. Typically co-occur in groups.

| Feature | ID | Meaning |
|---|---|---|
| `pushbutton` | 8 | Device has a push-button input. Base feature required for all button config UI. |
| `pushbdevice` | 9 | Button can control at device level (directly dim/switch its own output). |
| `pushbsensor` | 10 | Button operates as sensor/detection input (Black devices). |
| `pushbarea` | 11 | Button can be assigned to control an area. |
| `pushbadvanced` | 12 | Advanced button configuration (press type, double-press, etc.). |
| `pushbcombined` | 13 | Combined button mode for multi-button devices (SDS20/22). |
| `pushbdisabled` | 49 | Button present in hardware but disabled (ZWS205 feature). |

### 5.3 Shade / Blind Features

| Feature | ID | Meaning |
|---|---|---|
| `shadeprops` | 14 | Shade/blind movement properties (travel time, motor inertia) are configurable. |
| `shadeposition` | 15 | Shade/blind position can be tracked and reported. |
| `motiontimefins` | 16 | Venetian blind fin/slat rotation time configurable (separate from main travel time). |
| `shadebladeang` | 18 | Venetian blind blade angle can be set and tracked. Enables angle control UI. |
| `optypeconfig` | 17 | Output type (e.g., blind vs. awning) is user-configurable (Black devices). |
| `locationconfig` | 36 | Shade installation location configurable (affects auto-sun-protection behavior). |
| `windprotectionconfigawning` | 37 | Wind protection settings specific to awnings. |
| `windprotectionconfigblind` | 38 | Wind protection settings specific to venetian blinds. |

### 5.4 Heating / Valve Features

| Feature | ID | Meaning |
|---|---|---|
| `heatinggroup` | 27 | Heating application group can be changed (heating/cooling/ventilation/recirculation). Adds "Application" dropdown. |
| `heatingoutmode` | 28 | Heating output mode is configurable. Adds heating-specific output mode selector. |
| `heatingprops` | 29 | Heating/valve properties section shown in device details. |
| `pwmvalue` | 30 | PWM duty cycle configurable. Requires `isValveDevice()` for the edit button (always blocked for VDC devices). |
| `valvetype` | 31 | Attached valve/terminal type selectable (normally open, normally closed, etc.). |
| `extendedvalvetypes` | 58 | Extended valve type options beyond the standard set. |

### 5.5 Climate / Thermostat Features

These appear on room controller devices (SK204, BL-SK204) and FTW thermostat-controller devices.

| Feature | ID | Meaning |
|---|---|---|
| `temperatureoffset` | 42 | Temperature sensor offset is configurable. |
| `ftwtempcontrolventilationselect` | 44 | FTW thermostat ventilation mode selection. |
| `ftwdisplaysettings` | 45 | FTW thermostat display brightness/settings. |
| `ftwbacklighttimeout` | 46 | FTW thermostat backlight timeout. |
| `ventconfig` | 47 | Ventilation configuration panel. |
| `fcu` | 48 | Fan coil unit (FCU) specific settings. |

### 5.6 AKM Sensor Features

These appear on devices with AKM (alternative input) bus connections.

| Feature | ID | Meaning |
|---|---|---|
| `akmsensor` | 22 | AKM bus sensor input present. |
| `akminput` | 23 | AKM bus digital input present. |
| `akmdelay` | 24 | AKM input trigger delay is configurable. |

### 5.7 Identification / Blink Features

| Feature | ID | Meaning |
|---|---|---|
| `identification` | 56 | Device supports the identify/locate function (LED flash). |
| `blink` | 1 | Device output can blink/flash as a scene action. |
| `blinkconfig` | 34 | Blink pattern and rate are configurable. |

### 5.8 Configuration Features

| Feature | ID | Meaning |
|---|---|---|
| `outconfigswitch` | 41 | Output can be configured as a switch (enables switch config options). |
| `impulseconfig` | 39 | Output impulse/pulse mode is configurable. |
| `twowayconfig` | 25 | Two-way/bidirectional operation is configurable (2-switch wiring). |
| `dimtimeconfig` | 53 | Dimming ramp-up/ramp-down time configurable (300-gen). |
| `dimmodeconfig` | 55 | Dimming mode (trailing edge, leading edge, etc.) configurable (300-gen). |
| `customtransitiontime` | 59 | Free-form custom transition time input (beyond preset list). |

### 5.9 Joker / Consumption Features

| Feature | ID | Meaning |
|---|---|---|
| `jokerconfig` | 21 | Joker device group-assignment UI shown. Allows reassigning device to a color group. |
| `highlevel` | 19 | Adds "App Button" as a selectable entry in the push-button type dropdown (requires `pushbutton`). The entry is only visible when the button's `buttonSettings/group` is 8 (Joker), or when the `jokerconfig` "Color Group" UI is present and set to Joker. Selecting it sets `buttonSettings/function` to `APP` (15). |
| `consumption` | 20 | Power consumption measurement is available. |
| `consumptioneventled` | 50 | LED event driven by consumption threshold (ZWS205). |
| `consumptiontimer` | 51 | Consumption measurement timer configurable (ZWS205). |
| `jokertempcontrol` | 52 | Joker device temperature control mode (ZWS205). |

### 5.10 Special / Firmware-Internal Features

| Feature | ID | Meaning |
|---|---|---|
| `apartmentapplication` | 43 | Device supports apartment-level application routing. **The only feature checked in backend C++** (`supportsApartmentApplications()`). Set by `updateModelFeatures()` based on FunctionID subclass bits. |
| `setumr200config` | 57 | UMR200 extended configuration UI. Set by `updateModelFeatures()` for UMR200 hardware. |
| `umroutmode` | 35 | UMR output mode (UMR200 Black devices). |
| `operationlock` | 62 | Operation lock (KL hardware, firmware-internal). |
| `grkl387workaround` | 63 | GR-KL387 hardware workaround flag. Internal use only. |
| `customactivityconfig` | 64 | Custom activity/scene configuration UI. |

---

## 6. VDC Device Guidance

### 6.1 Feature Declaration per Device Group

For classic VDC devices (`BusMember_vDC`, Python library), features declared here are stored in the ModelFeatures database and used by the configurator frontend. Declare features matching the equivalent physical device for the target group.

> **Recommended:** Use `derive_model_features()` (called automatically at announcement) instead of building feature lists manually. It derives all confirmed-working features from the declared output, sensors, binary inputs, and buttons. See `docs/model-features-auto-assignment.md` for the complete rule reference. The examples below reflect what `derive_model_features()` produces.

**Yellow (primaryGroup=1) — Lighting VDC device:**
```python
# Dimmable light (OutputFunction.DIMMER)
# derive_model_features() produces:
features = ["dontcare", "blink", "outvalue8", "transt", "dimtimeconfig", "identification"]

# Switched light (OutputFunction.ON_OFF)
features = ["dontcare", "blink", "outvalue8", "outconfigswitch", "impulseconfig", "identification"]

# Color light (OutputFunction.FULL_COLOR_DIMMER)
features = ["dontcare", "blink", "outvalue8", "transt", "outputchannels", "dimtimeconfig", "identification"]
```

**Grey (primaryGroup=2) — Shade VDC device:**
```python
# Roller blind / awning (OutputFunction.POSITIONAL, no slat channel)
# derive_model_features() produces:
features = ["dontcare", "blink", "shadeprops", "shadeposition",
            "locationconfig", "operationlock", "windprotectionconfigawning", "identification"]

# Venetian blind (POSITIONAL + channelType 9 or 10)
features = ["dontcare", "blink", "shadeprops", "shadeposition",
            "motiontimefins", "shadebladeang",
            "locationconfig", "operationlock", "windprotectionconfigblind", "identification"]
```

**Blue (primaryGroup=3) — Heating valve VDC device:**
```python
# Standard ON/OFF valve (OutputFunction.ON_OFF)
# derive_model_features() produces:
features = ["dontcare", "blink", "outvalue8", "pwmvalue",
            "outconfigswitch", "impulseconfig",
            "heatinggroup", "heatingprops", "valvetype", "extendedvalvetypes",
            "identification"]
# Note: "heatingoutmode" is NOT supported — it writes via DS485, not via VDC
```

**Cyan (primaryGroup=4) — Audio VDC device:**
```python
# Audio device with volume control:
features = ["dontcare", "blink", "outvalue8", "transt", "identification"]
```

**Black (primaryGroup=8) — Joker VDC device:**
```python
# Generic switch joker (OutputFunction.ON_OFF):
# derive_model_features() produces:
features = ["dontcare", "blink", "outvalue8", "outconfigswitch", "impulseconfig",
            "jokerconfig", "identification"]

# Sensor/input only (no output, button with group=8):
features = ["jokerconfig", "highlevel", "pushbsensor", "pushbutton",
            "pushbadvanced", "pushbdisabled", "identification"]
```

### 6.2 Feature Registration Flow Analysis (Classic VDC / Python library)

When a classic `BusMember_vDC` device announces with `modelFeatures`:

1. `VdcHelper::getSpec()` parses the `modelFeatures` from the VDC response
   - Only `true`-valued features are stored
   - Unknown feature names → warning logged, feature ignored
   - Result: `VdsdSpec_t.modelFeatures` (a `set<ModelFeatureId>`)

2. `setupBaseDevice(dev, spec)` → `m_FunctionID = spec.FunctionID` (from DSM API layer)
   - DSM layer has translated the device's `primaryGroup` into FunctionID bits[15:12]

3. `busscanner` calls `ModelFeatures::setFeatures(getDeviceClass(), modelUID, features)`
   - `getDeviceClass()` returns valid ColorID (e.g. 1 for GE/Yellow) from `m_FunctionID`
   - `setFeatures(1, modelUID, features)` → **features stored in ModelFeatures DB** ✓

4. Device JSON (`getDevices` response) contains `"modelFeatures": {}` (empty per-device map)
   - The per-device map `m_modelFeatures` is separate from the ModelFeatures DB
   - `m_modelFeatures` is only populated by `updateModelFeatures()` (hardware-specific features)

5. The `/apartment/getModelFeatures` API endpoint returns the declared features by `modelUID`
   - The configurator frontend reads this endpoint to determine UI panels

### 6.3 Impact on UI Rendering

For classic VDC devices (`BusMember_vDC`, Python library):
- Declared `modelFeatures` **do reach** the `/apartment/getModelFeatures` API
- The configurator frontend **can use** them to show/hide UI panels
- `primaryGroup` controls the color band, default scenes, and category icon

For backend VDC devices (`BusMember_backendVdc`):
- Declared `modelFeatures` are **never registered**
- `primaryGroup` remains the only UI routing mechanism

---

## 7. Other UI-Controlling VDC Properties

### 7.1 VDC Entry in Meters & Controllers

Fields from `VdcHelper::getVdcSpec()` shown in the "Meters & Controllers" panel:

| VDC property | Stored as | UI field |
|---|---|---|
| `name` | DSMeter name | VDC entry label |
| `model` | hwName | Hardware model |
| `modelVersion` | swVersion | Software version |
| `hardwareVersion` | hwVersionString | Hardware version |
| `configURL` | VdcConfigURL | "Configure" link button |
| `displayId` | DisplayID | Serial / identifier |
| `capabilities.identification = true` | hasBlinking | "Identify" right-click menu item |
| `capabilities.metering = true` | hasMetering | Energy metering panel |
| `capabilities.dynamicDefinitions = true` | hasDynamicDefinitions | Live VdSD property queries |

### 7.2 Device Overview Fields (Common to All Groups)

From `jsonhelper.cpp::toJSON(DeviceReference)`:

| JSON field | Source | Notes |
|---|---|---|
| `name` | `spec.name` | Device display name |
| `dSUID` | `spec.dSUID` | Device unique ID |
| `DisplayID` | `spec.displayId` | Serial / identifier |
| `functionID` | From DSM layer (`BusMember_vDC`) or 0 (`BusMember_backendVdc`) | Encodes device class in bits[15:12] |
| `modelFeatures` | `device.getModelFeatures()` | Empty for all VDC devices (per-device map, not ModelFeatures DB) |
| `isVdcDevice` | true | VDC device flag |
| `outputMode` | from OutputMode enum | Active output mode |
| `groups` | `[primaryGroup]` | Group memberships |
| `isPresent` | true when connected | Connectivity state |
| `VdcConfigURL` | `spec.configURL` | Per-device configure link |
| `VdcHardwareInfo` | `spec.model` | Hardware model name |
| `VdcHardwareVersion` | `spec.hardwareVersion` | Hardware version |
| `hasActions` | OEM EAN lookup | Activities tab enabled |

### 7.3 Output Channel Types

`channelDescriptions` response structure controls which output UI is shown. All 27 standard channel types from `src/model/modelconst.h` (ChannelType, DS_REFLECTED_ENUM, IDs 0–26):

| ID | Firmware name | Python `OutputChannelType` | Typical UI |
|---|---|---|---|
| 0 | `none` | `DEFAULT` | Catch-all / unspecified (on/off toggle) |
| 1 | `brightness` | `BRIGHTNESS` | Brightness slider (0–100 %) |
| 2 | `hue` | `HUE` | Hue (colour wheel, 0–360°) |
| 3 | `saturation` | `SATURATION` | Saturation (0–100 %) |
| 4 | `colortemp` | `COLOR_TEMPERATURE` | Colour temperature slider (100–1000 mired) |
| 5 | `x` | `CIE_X` | CIE xy chromaticity X (0.0–1.0) |
| 6 | `y` | `CIE_Y` | CIE xy chromaticity Y (0.0–1.0) |
| 7 | `shadePositionOutside` | `SHADE_POSITION_OUTSIDE` | External blind / roller shutter position (0–100 %) |
| 8 | `shadePositionIndoor` | `SHADE_POSITION_INDOOR` | Indoor curtain / blind position (0–100 %) |
| 9 | `shadeOpeningAngleOutside` | `SHADE_OPENING_ANGLE_OUTSIDE` | External slat / blade tilt angle (0–100 %) |
| 10 | `shadeOpeningAngleIndoor` | `SHADE_OPENING_ANGLE_INDOOR` | Indoor slat / blade tilt angle (0–100 %) |
| 11 | `transparency` | `TRANSPARENCY` | Electrochromic glass transparency (0–100 %) |
| 12 | `airFlowIntensity` | `AIR_FLOW_INTENSITY` | Fan / ventilation speed (0–100 %) |
| 13 | `airFlowDirection` | `AIR_FLOW_DIRECTION` | Air flow direction / swing |
| 14 | `airFlapPosition` | `AIR_FLAP_POSITION` | Air flap / damper position (0–100 %) |
| 15 | `airLouverPosition` | `AIR_LOUVER_POSITION` | Louver position (0–100 %) |
| 16 | `heatingPower` | `HEATING_POWER` | Heating valve opening / PWM power (0–100 %) |
| 17 | `coolingCapacity` | `COOLING_CAPACITY` | Cooling capacity (0–100 %) |
| 18 | `audioVolume` | `AUDIO_VOLUME` | Audio volume slider (0–100 %) |
| 19 | `powerState` | `POWER_STATE` | Generic power on/off state (0 or 100) |
| 20 | `airLouverAuto` | `AIR_LOUVER_AUTO` | Louver auto-swing on/off |
| 21 | `airFlowAuto` | `AIR_FLOW_AUTO` | Air flow auto-mode on/off |
| 22 | `waterTemperature` | `WATER_TEMPERATURE` | Water / boiler temperature setpoint (°C) |
| 23 | `waterFlowRate` | `WATER_FLOW_RATE` | Water flow rate (l/min) |
| 24 | `powerLevel` | `POWER_LEVEL` | Generic power level (0–100 %) |
| 25 | `videoStation` | `VIDEO_STATION` | TV channel / video station number |
| 26 | `videoInputSource` | `VIDEO_INPUT_SOURCE` | Video input source selector |

Channel IDs 192–239 are reserved for proprietary / device-specific channels.

For enum/dropdown channels, add `values` sub-elements:
```
channelDescriptions.myChannel:
  dsIndex:     0
  channelType: <type>
  values:
    "0": "Option A"    ← element name = key, v_string = display label
    "1": "Option B"
```

### 7.4 Binary Inputs

Declared in VdSD spec (not queried live). All three arrays must use identical IDs in identical order.

```
binaryInputDescriptions:
  "inputName":
    dsIndex:        0          ← 0-based index
    sensorFunction: 1          ← BinaryInputType enum value
    updateInterval: 0
binaryInputSettings:
  "inputName":
    group:          2          ← target group for this input
binaryInputStates:
  "inputName":
    value:          0          ← 0=inactive, 1=active
    error:          0
```

**BinaryInputType values** (`sensorFunction`). Firmware C++ enum names from `src/model/modelconst.h`; Python library uses different symbolic names (`BinaryInputType` in `enums.py`):

| Value | Firmware C++ name | Python `BinaryInputType` |
|---|---|---|
| 0 | `AppMode` | `GENERIC` |
| 1 | `Presence` | `PRESENCE` |
| 2 | `RoomBrightness` | `BRIGHTNESS` |
| 3 | `PresenceInDarkness` | `PRESENCE_IN_DARKNESS` |
| 4 | `TwilightExternal` | `TWILIGHT` |
| 5 | `Movement` | `MOTION` |
| 6 | `MovementInDarkness` | `MOTION_IN_DARKNESS` |
| 7 | `SmokeDetector` | `SMOKE` |
| 8 | `WindDetector` | `WIND` |
| 9 | `RainDetector` | `RAIN` |
| 10 | `SunRadiation` | `SUN_RADIATION` |
| 11 | `RoomThermostat` | `THERMOSTAT` |
| 12 | `BatteryLow` | `BATTERY_LOW` |
| 13 | `WindowContact` | `WINDOW_OPEN` |
| 14 | `DoorContact` | `DOOR_OPEN` |
| 15 | `WindowTilt` | `WINDOW_TILTED` |
| 16 | `GarageDoorContact` | `GARAGE_DOOR_OPEN` |
| 17 | `SunProtection` | `SUN_PROTECTION` |
| 18 | `FrostDetector` | `FROST` |
| 19 | `HeatingSystem` | `HEATING_SYSTEM_ENABLED` |
| 20 | `HeatingSystemMode` | `HEATING_CHANGE_OVER` |
| 21 | `PowerUp` | `INITIALIZATION` |
| 22 | `Malfunction` | `MALFUNCTION` |
| 23 | `Service` | `SERVICE` |

### 7.5 Sensor Inputs

Queried live from VdSD via `sensorDescriptions` (requires `capabilities.dynamicDefinitions = true`):

```
sensorDescriptions:
  "roomTemperature":
    dsIndex:        0
    sensorType:     1          ← SensorType ID (VDC API numbering: 1 = TEMPERATURE °C)
    sensorUsage:    0
    min:            -40.0
    max:            85.0
    resolution:     0.1
    updateInterval: 60
```

> **Important:** The `sensorType` integer in VDC API (`sensorDescriptions`) uses the **VDC API numbering** (Python `SensorType` enum, values 0–34), **not** the dSS firmware's internal hardware-bus `SensorType` enum (which uses non-sequential values like TemperatureIndoors=9, ActivePowerVA=65, etc.). These two numbering systems are completely independent; always use the VDC API values (0–34) when building sensor descriptions.

### 7.6 Device States and Properties

**States** (declared in `deviceStateDescriptions`, live value in `deviceStates`):
```
deviceStateDescriptions:
  "powerState":
    value:
      values:
        "on":  true
        "off": true
```

**Properties** (declared in `devicePropertyDescriptions`, live value in `deviceProperties`):
```
devicePropertyDescriptions:
  "targetTemperature":
    type:       "numeric"
    min:        15.0
    max:        30.0
    resolution: 0.5
    siunit:     "°C"
  "fanMode":
    type:   "enumeration"
    values:
      "auto": true
      "low":  true
      "high": true
```

### 7.7 Scene Configuration

VdSD must handle `getProperty` / `setProperty` for scene values:

```
scenes:
  "<sceneNum>":            ← 0–63 standard, 64–127 apartment
    channels:
      "<channelId>":
        value:    50.0
        dontCare: false
        command:  ""         ← for action-type channels
```

Queried by dSS via `getOutputChannelSceneValue2`; written via `setOutputChannelSceneValue2`.

---

## 8. Known Firmware Limitations

### 8.1 `isValveDevice()` Always False for VDC Devices

```cpp
bool Device::isValveDevice() const {
  return (hasOutput() && (
    (!isInternallyControlled() && (getDeviceClass() == DEVICE_CLASS_BL)) ||
    ((getDeviceType() == DEVICE_TYPE_UMR) && (getRevisionID() >= 0x0383)) ||
    ((getDeviceType() == DEVICE_TYPE_UMV) && (getDeviceNumber() == 200)) ||
    ((getDeviceType() == DEVICE_TYPE_ZWS) && (getDeviceNumber() == 205))
  ));
}
```

For classic VDC (`BusMember_vDC`), `m_FunctionID` IS set from the DSM layer (bits[15:12] encode the device class from `primaryGroup`). However, `isValveDevice()` checks for `getDeviceClass() == DEVICE_CLASS_BL` using `m_FunctionID` bits[15:12], **not** via `primaryGroup`. For Blue (BL) VDC devices with `primaryGroup=3`, the DSM layer sets `FunctionID=0x3000`, so `getDeviceClass()` returns `DEVICE_CLASS_BL`. BUT `isValveDevice()` also checks `!isInternallyControlled()` — this may or may not pass depending on the device configuration.

For backend VDC (`BusMember_backendVdc`), `m_FunctionID=0` → `getDeviceClass()` returns `DEVICE_CLASS_INVALID` → `isValveDevice()` is always `false`.

**Blocked API methods (backend VDC only, where FunctionID=0):**

| Method | Condition checked | Error |
|---|---|---|
| `setHeatingGroup` | `!isValveDevice()` | "Cannot change group for this device" |
| `setValvePwmMode` | `!isValveDevice()` | fails |
| `getValvePwmMode` | `!isValveDevice()` | fails |
| `setValveControlMode` | `!isValveDevice()` | fails |
| `getValveType` | `!isValveDevice()` | fails |
| `setValveType` | `!isValveDevice()` | fails |

The `heatinggroup`, `valvetype`, `heatingoutmode`, `heatingprops` model features affect UI presentation via `/apartment/getModelFeatures` for classic VDC devices. The valve API calls additionally require `isValveDevice()`.

### 8.2 `functionID` in Device JSON vs Internal FunctionID

The **device JSON** `functionID` field (from `jsonhelper.cpp`) reports the same value as `m_FunctionID`:
- Classic VDC (`BusMember_vDC`): `functionID` = DSM-layer-derived value (e.g. `0x1000` for Yellow)
- Backend VDC (`BusMember_backendVdc`): `functionID=0` (never set by `putVdcDevice()`)

`productID=0` for all VDC devices (not announced via vdcapi protocol).

### 8.3 `hasActions` Requires OEM EAN Registration

The `hasActions` flag (required for `getApartmentScenes` and `setSceneValue(command=...)`) is set from OEM EAN database lookup. VDC devices without a registered OEM GTIN have `hasActions=false`.

Standard scene value configuration (`setSceneValue?value=<n>`) works without `hasActions`.

### 8.4 Device JSON `modelFeatures` Field vs ModelFeatures Database

**Device JSON `modelFeatures` field** (from `device.getModelFeatures()` in `jsonhelper.cpp:76`):
- Populated by `updateModelFeatures()` — hardware-specific features only (5 total, none for VDC)
- Always `{}` for all VDC devices (both classic and backend)

**ModelFeatures database** (from `/apartment/getModelFeatures` REST endpoint):
- Keyed by `color + modelUID`
- For classic VDC (`BusMember_vDC`): populated from VDC announcement → configurator can use them ✓
- For backend VDC (`BusMember_backendVdc`): never populated

The configurator frontend uses `/apartment/getModelFeatures`, not the per-device JSON field. Declaring `modelFeatures` in a classic VDC device announcement therefore **does** influence UI behavior.
