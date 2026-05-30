# pydsvdcapi — vDC API Properties Complete Reference

This document consolidates the entire vDC API property surface into a single reference.
For every property it documents: the protocol key, access mode, type, description, and how
the dSS firmware reads, stores, or displays the value.

Sources used:
- Official vDC API Properties specification (vdc-API-properties/01–15)
- dSS mainline firmware source (`modelconst.h`, `vdc-connection.cpp`, `busscanner.cpp`,
  `backend-vdcs.cpp`, `businterface.cpp`, `device.cpp`, `model-features.cpp`)
- pydsvdcapi `enums.py` and `vdc-host-behavior.md`

**Conventions**

- `acc` column: `r` = readable, `w` = writable, `r/w` = both
- **dSS handling** column describes what the firmware actually does with the value
- `optional` = field may be absent; `getProperty` returns no entry (not an error)
- All strings are UTF-8 encoded

---

## 1. Basics

- A vDC host exposes a tree of named properties to the vdSM via the protobuf `getProperty` /
  `setProperty` calls.
- Three addressable entity types exist: **vdSD** (virtual device), **vDC** (logical connector),
  **vDChost** (gateway).
- Optional properties that are absent produce no response element on `getProperty`; they produce
  an error on `setProperty`.
- Property names and values are language-independent.

---

## 2. Common Properties — All Addressable Entities

These properties are required on every entity (vdSD, vDC, vDChost).

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `dSUID` | r | 34-hex-char string | Entity's dSUID. Normally carried in the protocol message, not the property tree; useful for debugging. | Used as the primary key for all dSS data structures. Backend VDC: `str2dsuid(spec.dSUID)`. |
| `displayId` | r | string | Human-readable label printed on the physical device, if any. | Stored in the vdSM display and passed upstream. Not parsed by dSS firmware. |
| `type` | r | string enum | Entity type: `"vdSD"`, `"vDC"`, `"vDChost"`, `"vdSM"` | Read by the vdSM to route properties correctly. |
| `model` | r | string | Human-readable model description. Maps to `hardwareInfo` in vdSM. | Stored via `dsm->setHardwareName()` (vDC) or `dev->setModel()` equivalent. Shown in the dSS configurator device tile. |
| `modelVersion` | r | optional string | Model/firmware version string shown to end users. | Stored via `dsm->setSoftwareVersion()` (vDC level). Shown in the configurator. |
| `modelUID` | r | string | System-unique ID for the functional model. Devices with identical dS functionality share the same `modelUID`. | Used as the key for the ModelFeatures database: `modelFeatures.setFeatures(color, modelUID, features)`. Must be unique per functional variant. |
| `hardwareVersion` | r | optional string | Hardware revision of the underlying physical device. | Stored via `dsm->setHardwareVersion()`. Shown in configurator hardware info. |
| `hardwareGuid` | r | optional string | Native hardware GUID in `schema:id` format (see §2.1). | Stored in device record. Used for device matching and vendor identification. |
| `hardwareModelGuid` | r | optional string | Native hardware model GUID. GS1 GTIN format most common: `gs1:(01)GTIN13`. | Stored in device record. **Different from `oemModelGuid`** — this identifies the hardware model, not the application layer. |
| `vendorName` | r | optional string | Free-text vendor/manufacturer name. | Stored and shown in configurator. Not parsed by firmware. |
| `vendorGuid` | r | optional string | Vendor identification in `schema:id` format. | Stored alongside `vendorId`. |
| `vendorId` | r | optional string | Short vendor identifier in `schema:id` format. | Read by `VdcHelper::getSpec()` → `ret.vendorId`. Stored in the vdSM record for vendor identification. |
| `oemGuid` | r | optional string | GUID of the product the hardware is embedded in (OEM product identity). | Stored via `dev->setVdsdSpec()` → `vdsdSpec.oemGuid`. |
| `oemModelGuid` | r | optional string | **GTIN** — GUID of the OEM product model; typically `gs1:(01)GTIN13`. | **Critical for complex devices.** Read by `VdcHelper::getSpec()` → `vdsdSpec.oemModelGuid`. Stripped of `gs1:(01)` prefix and looked up in the VdcDb at scan time to determine `hasActions` and seed state slots. See §7.2 for full behavior. |
| `configURL` | r | optional string | Full URL of the device's web configuration UI, if any. | Stored in device record. Shown as a link in the configurator. |
| `deviceIcon16` | r | optional binary | 16×16 PNG icon for this device in the configurator. | Read by `VdcHelper::getIcon()`. Displayed in the configurator device tile. |
| `deviceIconName` | r | optional string | Filename-safe icon name for caching (a–z, 0–9, `_`, `-`). | Used by the web UI to cache icons without re-fetching the binary for every device with the same icon. |
| `name` | r/w | string | User-assigned device name. vDC generates a descriptive default; vdSM propagates name changes from the dSS configurator back to the vDC. | Read at scan time and stored upstream. The dSS configurator allows renaming; `setProperty(name, ...)` is sent back to the vDC when the user renames the device. |
| `deviceClass` | r | optional string | dS-defined unique name for a device class profile. | Stored in device record. Used for configurator profile matching. |
| `deviceClassVersion` | r | optional string | Revision of the device class profile. | Stored alongside `deviceClass`. |
| `descriptionsGroup` | r | optional string | System identifier for the UI description group in the dSS configurator database. | Read by `VdcHelper::getSpec()` → `ret.descriptionsGroup`. Used by the configurator to select the correct UI template for the device. |
| `descriptionsClass` | r | optional string | System identifier for the UI description class (used with `descriptionsGroup`). | Read by `VdcHelper::getSpec()` → `ret.descriptionsClass`. |
| `active` | r | optional boolean | Operational state: `true` = device can operate normally; `false` = communication problem, range issue, missing config, etc. Changes are pushed via `VDC_SEND_PUSH_NOTIFICATION`. | Stored via `dev->setIsPresent()` / `dev->setIsConnected()`. Shown as device online/offline status in configurator. Backend-VDC: driven by `VdsdSpec_t.active`. |

### 2.1 GUID Schema Reference

| Schema example | Used for | Notes |
|---|---|---|
| `gs1:(01)4050300870342(21)3696724640` | `hardwareGuid` | GTIN + serial number (DALI, etc.) |
| `gs1:(01)4050300870342` | `hardwareModelGuid`, `oemModelGuid` | GTIN only (model identity / VdcDb lookup) |
| `gs1:(412)7640161170001` | `vendorId` | GS1 Global Location Number |
| `uuid:2f402f80-ea50-11e1-9b23-001778216465` | `hardwareGuid` | UUID-based (hue bridge, UPnP) |
| `macaddress:45:A2:00:BC:73:B8` | `hardwareGuid` | IP devices with no better ID |
| `enoceanaddress:A4BC23D2` | `hardwareGuid` | 32-bit EnOcean address |
| `enoceaneep:A50904` | `hardwareModelGuid` | 24-bit EnOcean Equipment Profile |
| `enoceanvendor:002:Thermokon` | `vendorId` | EnOcean vendor code |

---

## 3. vDC Properties

Properties on logical vDC entities (`type = "vDC"`). vDCs also expose all §2 common properties.

### 3.1 vDC-Level Properties

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `capabilities` | r | property list | Sub-properties describing the vDC's capabilities. See §3.2. | Read by `VdcHelper::getVdcSpec()`. Each capability drives specific dSS behavior — see §3.2 for details. |
| `zoneID` | r/w | integer | Default zone for the vDC. Updated by the vdSM to reflect the zone this vDC is physically installed in. | Stored and shown in the dSS zone/room assignment. The vDC may use it to optimize zone-scoped calls. |
| `implementationId` | r | string | Unique identifier for the vDC implementation. Non-digitalSTROM vDCs must use the `"x-company-"` prefix. | Read by `VdcHelper::getVdcSpec()` → `ret->implementationId`. For backend-VDC path: `specIn.implementationId = static_cast<const std::string&>(id)` (overwritten from the REST route ID). Used to detect specific vDC implementations (e.g., `"EnOcean_Bus_Container"` triggers `outmodeenoceanvalve` injection). |

### 3.2 vDC Capabilities

Sub-properties of the `capabilities` property.

| Capability | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `metering` | r | optional boolean | `true` = vDC provides power metering data from devices. | Read via `getVdcSpec()`. Backend-VDC: `dsm->setCapability_HasMetering(spec.capabilities.metering)` (backend-vdcs.cpp:197). Enables metering history in the dSS dashboard for devices under this vDC. |
| `identification` | r | optional boolean | `true` = vDC supports device identification (blinking LED, audible signal, etc.). | Backend-VDC: `dsm->setCapability_HasBlinking(spec.capabilities.identification)` (backend-vdcs.cpp:198). Maps to the `identification` model feature; enables the "Identify" button in the configurator. |
| `dynamicDefinitions` | r | optional boolean | **Critical for complex devices.** `true` = vDC provides device state/event/action/property descriptions dynamically via `getProperty`. When `false`, descriptions come from the static VdcDb only. | Backend-VDC: `dsm->setCapability_HasDynamicDefinitions(spec.capabilities.dynamicDefinitions)` (backend-vdcs.cpp:199). Classic-VDC path: similar flag on the DSMeter. **When `true`:** dSS ignores VdcDb description entries and queries the VDC live for `deviceStateDescriptions`, `deviceEventDescriptions`, `deviceActionDescriptions`, `devicePropertyDescriptions` (device-info.cpp:329–651). **When `false` and GTIN in VdcDb:** names come from VdcDb entries only. **Dependency:** Without `dynamicDefinitions=true`, custom state/event/action names declared by the VDC are never shown in the configurator. See §7.1 for the full dependency chain. |

---

## 4. vdSD Properties

Properties on virtual device entities (`type = "vdSD"`). vdSDs also expose all §2 common properties.

### 4.1 General Device Properties

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `primaryGroup` | r | integer (ApplicationType) | Basic class (colour) of the device. Determines which dS application UI the device appears on and which scene calls it responds to. | **Backend-VDC path:** `VdsdSpec_t.primaryGroup` → `modelDevice->addToGroup(spec.primaryGroup)` + `modelDevice->setActiveGroup(spec.primaryGroup)` (backend-vdcs.cpp:271–272). **Classic-VDC path:** vdSM translates to dS485 bus announcement; dSS reads via `DeviceSpec.activeGroup` / `DeviceSpec.Groups`. Firmware stores as `m_ActiveGroup` (cast to `ApplicationType` in switch statements). See §4.1.1 for valid values. |
| `zoneID` | r/w | integer | Global dS zone the device is assigned to. Updated by the vdSM when the user moves the device between rooms/zones. | The vDC may use this to optimize zone-scoped hardware calls (e.g., sending a single bus command when all devices in a zone share hardware). |
| `progMode` | r/w | optional boolean | Enables local programming mode for devices that support it. | Device-specific; firmware passes through to the device. Not processed further by the dSS core. |
| `modelFeatures` | r | property list (feature name → `true`) | Boolean flags that tell the dSS configurator which UI panels, settings, and API calls to expose for this device. Each present feature is a key with value `true`; absent features are omitted. | **Classic-VDC path:** Read by `VdcHelper::getSpec()` → `vdsdSpec.modelFeatures` (set\<ModelFeatureId\>). Then `modelFeatures.setFeatures(color, modelUID, features)` is called — but **this call throws for VDC devices** because `getDeviceClass()` returns -1 (FunctionID=0 for VDC devices), and color -1 is outside the valid range 1–9 (busscanner.cpp:519–523). Features are therefore NOT stored in the ModelFeatures database for VDC devices. The configurator reads features via `/apartment/getModelFeatures` REST endpoint. **Backend-VDC path:** VdsdSpec_t does not carry modelFeatures to `putVdcDevice()`. See §4.1.2 for all 65 feature definitions. |
| `currentConfigId` | r | optional string | ID of the configuration/profile currently active on the device. Changed via the `setConfiguration` generic request. | Stored and shown in configurator profile selector. |
| `configurations` | r | property list | List of configuration/profile IDs supported by this device. | Shown in configurator profile picker. |

#### 4.1.1 primaryGroup — Valid Values

Values are the firmware `ApplicationType` enum (`modelconst.h`). The same integers are used for `GroupID` constants; see §6 for the group ID space.

| Value | `ColorGroup` (primaryGroup) | `ColorClass` (output groups) | Firmware name | dSS UI surface | Notes |
|---|---|---|---|---|---|
| 0 | — | `NONE` | `none` | — | No application group; avoid for real devices |
| 1 | `YELLOW` | `LIGHTS` | `lights` | Light control | Dimmable lights, switched lights, RGB lights |
| 2 | `GREY` | `BLINDS` | `blinds` | Shade/blind control | **Both outdoor blinds AND indoor curtains** (channel type distinguishes them; see §4.4.1) |
| 3 | `BLUE` | `HEATING` | `heating` | Climate/heating panel | Heating valves, floor heating actuators. **For TCP/IP VDC, BLUE=3 covers ALL climate sub-types.** |
| 4 | `CYAN` | `AUDIO` | `audio` | Audio application | Playback devices, amplifiers |
| 5 | `MAGENTA` | `VIDEO` | `video` | Video application | Displays, projectors, media players |
| 6 | `RED` | `SECURITY` | `security` | Security *(deprecated)* | Deprecated in firmware; avoid for new devices |
| 7 | `GREEN` | `ACCESS` | `access` | Access *(deprecated)* | Deprecated in firmware; avoid for new devices |
| 8 | `BLACK` | `JOKER` | `joker` | Joker/configurable | Multi-purpose; can be assigned to any group via `jokerconfig` |
| 9 | `WHITE` | — | `cooling` / `ColorIDWhite` | Single Device | **For VDC devices**: confirmed as white/Single Device (Einzelgerät) on real hardware. Firmware source: `ApplicationType::cooling = 9` and `ColorIDWhite = 9` share the same integer; dSS resolves `primaryGroup=9` as white for VDC devices. **TCP/IP VDC: max valid `primaryGroup` value.** |
| 9 | `WHITE` | `COOLING` | `cooling` | Cooling | `ColorClass.COOLING=9` for the output `active_group` when device actively cools |
| 10 | *(backend-VDC only)* | `VENTILATION` | `ventilation` | Climate/ventilation | HRV units, AHUs, exhaust fans. **TCP/IP VDC: use `ColorGroup.BLUE=3` with `active_group=ColorClass.VENTILATION(10)`.** |
| 11 | *(backend-VDC only)* | `WINDOW` | `window` | Climate/window | Motorised window openers. TCP/IP VDC: use `ColorGroup.BLUE=3` with `active_group=ColorClass.WINDOW(11)`. |
| 12 | *(backend-VDC only)* | `RECIRCULATION` | `recirculation` | Climate/FCU | Fan coil units, split ACs. TCP/IP VDC: use `ColorGroup.BLUE=3` with `active_group=ColorClass.RECIRCULATION(12)`. |
| 48 | *(backend-VDC only)* | `TEMPERATURE_CONTROL` | `temperature` | Climate (temperature control) | Room temperature controllers; TCP/IP VDC: use `ColorGroup.BLUE=3`. |
| 64 | *(backend-VDC only)* | `APARTMENT_VENTILATION` | `apartmentVentilation` | Climate/ventilation (apartment) | `GroupIDGlobalAppDsVentilation = 64`. Cannot appear in `groups` (1–63 only). |
| 65 | *(backend-VDC only)* | `AWNINGS` | `awnings` | Shade/awning | **Own top-level group**, not a sub-type of GREY; `GroupIDGlobalAppDsAwnings = 65`. Cannot appear in `groups`. |
| 69 | *(backend-VDC only)* | `APARTMENT_RECIRCULATION` | `apartmentRecirculation` | Climate/FCU (apartment) | `GroupIDGlobalAppDsRecirculation = 69`. Cannot appear in `groups`. |

#### 4.1.2 Model Features — Complete Reference

Model features are boolean flags sent in the `modelFeatures` property. Each feature name is a key with value `true` when present. The full set is the firmware `ModelFeatureId` enum (65 features, IDs 0–64).

**Derivation key:**
- `auto: <condition>` — the pydsvdcapi library auto-sets this feature when the condition is met
- `not-tested` — can be set manually with `add_model_feature()`; full VDC behavior unconfirmed
- `manual` — must be set explicitly by the integrator; VDC behavior confirmed or plausible
- `not-supported-vdc` — **rejected with `ValueError`** by `add_model_feature()`; cannot work on TCP/IP VDC devices; never auto-derived
- `forbidden` — do NOT set from a vDC; dSS firmware injects/manages this automatically

> **VDC path:** For **classic TCP/IP VDC devices** (`BusMember_vDC`, the Python library path), the DSM layer translates the device's `primaryGroup` into `FunctionID` bits[15:12] (e.g. `primaryGroup=1` → `FunctionID=0x1000`). This makes `getDeviceClass()` return a valid color, so `ModelFeatures::setFeatures()` **succeeds** and declared features reach the `/apartment/getModelFeatures` REST endpoint that the configurator reads. For **backend VDC devices** (`BusMember_backendVdc`), the busscanner block is bypassed entirely — features are never registered. See `docs/dss-configurator-ui-composition.md §2` for the full flow analysis.

##### A — General Device Properties Panel

| ID | Feature | Effect | dSS API / configurator | Library derivation |
|---|---|---|---|---|
| 0 | `dontcare` | Enables the scene "don't care" flag. When active, a scene transition leaves the output unchanged instead of forcing a specific value. | `getSceneMode()` / `setSceneMode()` → `dontCare` parameter | `auto: any output present` |
| 7 | `outvalue8` | Enables 8-bit (0–255) scene output value entry. Without it, only binary on/off values (0 or 255) are offered. | `getSceneValue()` / `setSceneValue()` (full 0–255 range) | `auto: primaryGroup ≠ 2 (not an outdoor shade device)` |
| 4 | `transt` | Enables per-scene global transition time configuration (one preset). | `getTransitionTime()` / `setTransitionTime()` (dimtimeIndex 0) | `auto: channelType 1–12, 14–18, or 22–24 present` |
| 53 | `dimtimeconfig` | Extends `transt`: up to three independent transition time presets (dimtimeIndex 0–2) with separate up/down ramp times. | `getTransitionTime()` / `setTransitionTime()` (dimtimeIndex 0–2) | `auto: function in {DIMMER(1), DIMMER_COLOR_TEMP(3), FULL_COLOR_DIMMER(4)}` |
| 59 | `customtransitiontime` | Per-scene custom transition time. No vdSD property stores the value — may be stored on dSS/vdSM side. | Per-scene transition time editor | `not-tested` |
| 55 | `dimmodeconfig` | Dimmer characteristic curve selection (linear vs. logarithmic). Relates to physical dimmer hardware; VDC devices do not receive this information. **NOT supported for TCP/IP VDC.** | Dimmer mode selector in device properties | `not-supported-vdc` |
| 54 | `outmodeauto` | Adds an "automatic" mode option to the dimmer output mode selector. Firmware analysis shows it writes via DS485 `CfgFunction_Mode` and may block the "Edit Device Values" UI for multi-channel outputs — VDC behavior not confirmed. | `setOutputMode()` → AUTO mode | `not-tested` |
| 41 | `outconfigswitch` | Switch output threshold configuration UI (onThreshold). | Scene impulse configuration field | `auto: function=ON_OFF` |
| 39 | `impulseconfig` | "Impulse" tab in Device Properties for binary-output devices — configures impulse behavior. May be stored on dSS/vdSM. | `setOutputAfterImpulse()` / `getOutputAfterImpulse()` | `auto: function=ON_OFF` |

##### A.2 — Output Mode Selection

| ID | Feature | Available options | Typical devices | Derivation |
|---|---|---|---|---|
| 5 | `outmode` | Full dimmer mode set: dimmer modes + simple switch. **NOT supported for TCP/IP VDC** — UI writes hardware mode via DS485 `CfgFunction_Mode`; value is stored in dSS `m_OutputMode` and never forwarded to the VDC. | KM-2xx, TKM-2xx, SDM dimmer modules (GE group) | `not-supported-vdc` |
| 6 | `outmodeswitch` | Switch-only variant of `outmode`. **NOT supported for TCP/IP VDC** — same DS485-only write path as `outmode`. | KL-200 (GE), relay devices in yellow group | `not-supported-vdc` |
| 40 | `outmodegeneric` | Generic output mode set for non-standard actuators. Not assigned to any DS485 device feature set (possibly VDC-intended for Joker devices), but mode write path is DS485-only — **VDC support unclear, not confirmed.** | Generic output mode selector | `unclear-vdc` |
| 60 | `outmodetempcontrol` | Adds temperature-control output modes (regulation PWM=64, regulation switch=65) to the mode selector. **NOT supported for TCP/IP VDC** — same DS485 `CfgFunction_Mode` write path as `outmode`. | UMR-200 (SW), ZWS-205 | `not-supported-vdc` |
| 61 | `outmodeenoceanvalve` | EnOcean-specific valve output mode. **Firmware-managed — do NOT set from a vDC.** | EnOcean valve devices | `forbidden` |
| 35 | `umroutmode` | UMR-200 specific output mode variants (2/3-phase switch, bipolar, temperature control). **NOT supported for TCP/IP VDC** — UMR200 is always a physical DS485 bus device; value never reaches VDC. | UMR-200 (SW group) | `not-supported-vdc` |

##### A.3 — LED / Indicator Configuration

| ID | Feature | Effect | dSS API | Derivation |
|---|---|---|---|---|
| 2 | `ledauto` | "LED Mode" radio button (Auto / Off). Device LED is not API-controlled on VDC devices; no vdSD property reflects the state. **NOT supported for TCP/IP VDC.** | `getLedMode()` / `setLedMode()` | `not-supported-vdc` |
| 3 | `leddark` | "LED Mode" radio button (On / Dark / Off). Same reason as `ledauto` — hardware-only, no VDC path. **NOT supported for TCP/IP VDC.** | `setLedMode()` → modeSelect = dark | `not-supported-vdc` |

##### A.4 — Blink / Identification

| ID | Feature | Effect | dSS API | Requirement | Derivation |
|---|---|---|---|---|---|
| 1 | `blink` | Enables the per-scene "blink effect" checkbox. Scene calls with effect=4 produce a blink pattern on the output. | `scenes/[x]/effect` (=4 when selected) | Output present | `auto: any output present` |
| 34 | `blinkconfig` | Blink pattern configuration (pulse count, on-delay, off-delay). No vdSD property stores the config — may be stored on dSS/vdSM side. | `setBlinkConfig()` / `getBlinkConfig()` | `blink` must also be present | `not-tested` |
| 56 | `identification` | Enables the "Identify" menu entry in the configurator. Sends a Notify message to the VDC which triggers the `on_identify` callback. | Configurator "Identify" → `blink()` call | `capabilities.identification = true` | `auto: on_identify callback registered` |

##### B — Push Button / Input Configuration Panel

All require at least one `buttonInputDescription` entry.

| ID | Feature | Effect | dSS API / UI | vDC Properties required | Derivation |
|---|---|---|---|---|---|
| 8 | `pushbutton` | **Master gate.** Enables the "Button" tab in device properties. | Button tab in device settings | `buttonInputDescriptions` (≥1 entry) | `auto: any button configured` |
| 9 | `pushbdevice` | Enables "device button" assignment: button controls the device's own output. | Button assignment → "Device" option | `buttonInputDescriptions[n].supportsLocalKeyMode = true` | `auto: button with supportsLocalKeyMode=true` |
| 10 | `pushbsensor` | Enables sensor-trigger assignment for the button input. | Button assignment → sensor trigger | — | `auto: button with group=8` |
| 11 | `pushbarea` | Enables area scene assignment (areas 1–4). | Area scene configuration in button settings | — | `auto: button with group≠8` |
| 12 | `pushbadvanced` | Enables advanced button options: scene selection per event, button ID assignment. | Advanced button configuration | — | `auto: any button configured` |
| 13 | `pushbcombined` | Combined two-button operation (adjacent up/down buttons as single input). `ButtonDescription/buttonType` is **read-only** in the VDC protocol — values do not align with the UI options and this feature is hardware-specific to physical TKM/SDS devices. **NOT supported for TCP/IP VDC.** | Combined input mode toggle | `buttonType` ∈ {2,3,4,5} | `not-supported-vdc` |
| 49 | `pushbdisabled` | Dialog for disabling unused buttons from end-user UIs / Smarthome API. | "Disable button" option | Any button present | `auto: any button configured` |
| 25 | `twowayconfig` | Two-way (master/slave) pairing configuration. `ButtonDescription/buttonType` is **read-only** in the VDC protocol — same root cause as `pushbcombined`. **NOT supported for TCP/IP VDC.** | Two-way mode selector | `buttonInputDescriptions` with `dsIndex≥1` | `not-supported-vdc` |

##### C — AKM Sensor Input Configuration

| ID | Feature | Effect | dSS API | Prerequisite | Derivation |
|---|---|---|---|---|---|
| 22 | `akmsensor` | "Sensor Function" dropdown to configure the sensor type (motion, window…). | `setAKMInputProperty()` / `binaryInputSettings/sensorFunction` | Any binary input | `auto: any binary input` |
| 23 | `akminput` | "Input" dropdown to configure sensor behaviour (standard / inverted). **NOT supported for TCP/IP VDC** — configures via DS485 `setAKMInputProperty()` only; values are never forwarded to the VDC. | `setAKMInputProperty()` | `akmsensor` also present | `not-supported-vdc` |
| 24 | `akmdelay` | "Turn-on / Turn-off delay" dropdowns for delayed sensor response. **NOT supported for TCP/IP VDC** — configures via DS485 `setAKMInputTimeouts()` only; values are never forwarded to the VDC. | `setAKMInputTimeouts()` / `getAKMInputTimeouts()` | `akmsensor` or `akminput` present | `not-supported-vdc` |

##### D — Joker / Group Assignment (Black / SW Group)

Requires `primaryGroup=8` (Black) for `jokerconfig` and `jokertempcontrol` to take effect.

| ID | Feature | Effect | dSS API | Derivation |
|---|---|---|---|---|
| 19 | `highlevel` | Adds "App Button" as a selectable entry in the push-button type dropdown (requires `pushbutton`). Only visible when `buttonSettings/group == 8`, or when the `jokerconfig` Color Group UI is set to Joker. Selecting it sets `buttonSettings/function` to `APP` (15). | Push-button type dropdown | `auto: button with group=8` |
| 21 | `jokerconfig` | Enables joker group assignment in configurator. Device can be moved to any dS colour group. | `setJokerGroup()` | `auto: primaryGroup=8` |
| 52 | `jokertempcontrol` | Enables temperature control configuration for a joker device acting as heating actuator (e.g., ZWS-205). Requires `jokerconfig`. | Temperature control in joker panel | `manual` |
| 43 | `apartmentapplication` | Marks device for apartment-level application logic. **Firmware-managed — do NOT set from a vDC.** The only feature the dSS firmware itself checks at runtime (`supportsApartmentApplications()`). | Apartment-application filtering | `forbidden` |

##### E — Shade / Blind Properties Panel (Grey / GR Group)

Requires `primaryGroup=2` (GREY).

> **`shadeprops` and `motiontimefins` are NOT supported for TCP/IP VDC devices.**
> Both write motor timing via DS485 `setMaxMotionTime()` / `setMotionTime()`;
> the dSS stores the values internally without forwarding them to the VDC.
> `add_model_feature()` raises `ValueError` for both.

| ID | Feature | Effect | dSS API | Notes | Derivation |
|---|---|---|---|---|---|
| 14 | `shadeprops` | **NOT SUPPORTED.** Would enable shade properties panel. | `setMaxMotionTime()` | DS485-only path; VDC receives no write-back | `not-supported-vdc` |
| 15 | `shadeposition` | Enables shade position control (0–100%) per scene. | Scene editor position field | — | `auto: shade output + outputFunction=POSITIONAL` |
| 18 | `shadebladeang` | Enables slat/blade angle control (0–100°) for venetian blinds. | Scene editor angle field | Jalousie hardware only | `auto: shade output + channelType 9 or 10 present` |
| 16 | `motiontimefins` | **NOT SUPPORTED.** Would enable fin/slat rotation time calibration. | `setMotionTime()` | DS485-only path; VDC receives no write-back | `not-supported-vdc` |
| 17 | `optypeconfig` | Output type selector (Switched / Swiped / PowerSafe). Selection changes dSS `m_OutputMode` via DS485 `CfgFunction_Mode` — these mode IDs have no VDC equivalent. **NOT supported for TCP/IP VDC.** | Output type selector | — | `not-supported-vdc` |

##### F — Location & Wind Protection (GR Group)

Requires `primaryGroup=2`.

| ID | Feature | Effect | dSS API | Notes | Derivation |
|---|---|---|---|---|---|
| 36 | `locationconfig` | Direction/orientation dropdown (cardinal direction, floor) in Device Properties. Values stored on dSS side. | `setCardinalDirection()` / `setFloor()` | Used in wind protection calculation | `auto: primaryGroup=2 + any output` |
| 62 | `operationlock` | "Ignore operation lock for weather alarms" radio button in Device Properties → Advanced Settings. Stored on dSS/vdSM. | Operation lock control | Grey actuator devices | `auto: primaryGroup=2 + any output` |
| 37 | `windprotectionconfigawning` | Wind sensitivity class configuration for **awning** hardware. | `setWindProtectionClass()` / `getWindProtectionClass()` | Use for awnings only; not for blinds | `auto: primaryGroup=2 + output without channelType 9/10` |
| 38 | `windprotectionconfigblind` | Wind sensitivity class configuration for **blind/shutter/jalousie** hardware. | `setWindProtectionClass()` / `getWindProtectionClass()` | Use for blinds only; not for awnings | `auto: primaryGroup=2 + channelType 9 or 10 present` |

> Use **exactly one** of `windprotectionconfigawning` or `windprotectionconfigblind` per device.

##### G — Heating / Climate Properties Panel (Blue / BL Group)

Requires `primaryGroup=3` (`ColorGroup.BLUE` — covers all climate sub-types for TCP/IP VDC) unless combined with joker operation.

| ID | Feature | Effect | dSS API / UI | Notes | Derivation |
|---|---|---|---|---|---|
| 27 | `heatinggroup` | Enables heating sub-group assignment (Heating=3, Cooling=9, Ventilation=10, Recirculation=12, Temperature=48). | `setHeatingGroup()` | Required for group reassignment | `auto: primaryGroup=3` |
| 28 | `heatingoutmode` | Enables heating output mode selector (switched relay vs. PWM valve). **NOT supported for TCP/IP VDC** — UI writes hardware mode via DS485 `CfgFunction_Mode`; stored in dSS `m_OutputMode` and never forwarded to the VDC. (dSS does write `activeCoolingMode` back, but only for physical devices.) | Heating output mode selector | `not-supported-vdc` |
| 29 | `heatingprops` | **Gate for heating sub-features.** Enables the full heating properties panel. | Heating properties panel | Required for `pwmvalue`, `valvetype`, `extendedvalvetypes` | `auto: primaryGroup=3` |
| 30 | `pwmvalue` | Enables PWM valve configuration (period, min/max stroke, offset). | `setValvePwmMode()` / `getValvePwmMode()` | Requires `heatingprops` | `auto: primaryGroup ∈ {3,48} (BLUE / all climate; TCP/IP VDC: only 3 is valid) + outputFunction=ON_OFF` |
| 31 | `valvetype` | Enables valve type selection (normally-open / normally-closed). **dSS writes** `outputSettings.heatingSystemType` back when user changes valve type. | `setValveType()` | Requires `heatingprops` | `auto: primaryGroup=3 + any output` |
| 58 | `extendedvalvetypes` | Extends `valvetype` with additional types (piston, mixed-mode). **dSS writes** `heatingSystemType` with extended range. | Extended valve type selector | Requires `valvetype` and `heatingprops` | `auto: primaryGroup=3 + any output` |

##### H — Multi-Channel Output

| ID | Feature | Effect | vDC Properties required | Derivation |
|---|---|---|---|---|
| 26 | `outputchannels` | Enables multi-channel output configuration (RGBW, tunable white, etc.). All channel values and per-channel don't-care flags are configurable per scene. | `channelDescriptions` must include HUE+SAT (full colour) or BRIGHTNESS+COLOR_TEMPERATURE (tunable white) | `auto: channelType 2+3 both present OR channelType 1+4 both present` |

##### I — UMV / UMR Hardware Features

| ID | Feature | Effect | Notes | Derivation |
|---|---|---|---|---|
| 32 | `extradimmer` | Enables the additional dimmer circuit on UMV200/UMV210 devices (physical relay+dimmer combo hardware). **NOT supported for TCP/IP VDC** — hardware-specific; configuration writes via DS485. For VDC, declare separate output channels instead. | UMV-200/210 in GE group only | `not-supported-vdc` |
| 33 | `umvrelay` | "Relay Function" dropdown to configure relay/output interplay (UMV200/210). If relay logic is internal to the UMV hardware, config is invisible to VDC and this would be NOT SUPPORTED. VDC behavior not confirmed — use only if device has addressable relay via API. | Set with `extradimmer` | `not-tested` |
| 57 | `setumr200config` | Enables UMR-200 advanced configuration panel. **Firmware-managed — do NOT set from a vDC.** | Auto-injected for UMR-200 with revisionID ≥ 0x0370 | `forbidden` |

##### J — Temperature & Display (SK / FTW Room Controller)

| ID | Feature | Effect | dSS API | Prerequisite | Derivation |
|---|---|---|---|---|---|
| 42 | `temperatureoffset` | Temperature calibration offset for built-in sensor (−128 to +127 in 0.1 °C). | `setTemperatureOffset()` / `getTemperatureOffset()` | Device has built-in temperature sensor | `auto: sensorType=TEMPERATURE(1) + primaryGroup=3` |
| 44 | `ftwtempcontrolventilationselect` | Mode selection: "temperature only" vs. "temperature + ventilation" (SK-204). Hardware-specific; not tested for VDC. | `setSK204Config()` / `getSK204Config()` | SK-204 only | `not-tested` |
| 45 | `ftwdisplaysettings` | Display settings for SK-204 display panel. Hardware-specific to physical SK204/FTW panels; no VDC equivalent. **NOT supported for TCP/IP VDC.** | `setSK204DisplayMode()` / `getSK204DisplayMode()` | SK-204 only | `not-supported-vdc` |
| 46 | `ftwbacklighttimeout` | SK-204 display backlight timeout. Hardware-specific to physical SK204/FTW panels; no VDC equivalent. **NOT supported for TCP/IP VDC.** | `setSK204BacklightTimeout()` | SK-204 only | `not-supported-vdc` |
| 47 | `ventconfig` | Ventilation channel configuration UI. | Ventilation output device settings | Ventilation channel types present | `auto: any ventilation channel (types 12,13,14,15,20,21) present` |
| 48 | `fcu` | Fan Coil Unit profile — marks device as FCU with combined heat/cool/fan channels. | FCU-specific output channel configuration | Ventilation channels + output + primaryGroup=3 | `auto: primaryGroup=3 + output + ventilation channel present` |

##### K — Power Consumption

| ID | Feature | Effect | dSS API | Derivation |
|---|---|---|---|---|
| 20 | `consumption` | Enables power consumption display in device status view. | `setConsumptionVisualization()` | `auto: sensorType 14, 15, 16, or 17 present` |
| 50 | `consumptioneventled` | LED pulse on energy count pulse. Controls a hardware LED on the end device — no VDC parameter handles this. **NOT supported for TCP/IP VDC.** | LED pulse on energy event | — | `not-supported-vdc` |
| 51 | `consumptiontimer` | Consumption measurement timer UI. Not tested for VDC — may be stored on dSS/vdSM side. | Sampling timer configuration | — | `not-tested` |

##### L — Custom Actions & Activities

| ID | Feature | Effect | vDC Properties required | Derivation |
|---|---|---|---|---|
| 64 | `customactivityconfig` | Enables custom device activities configuration. For vDC devices with a `deviceActionDescriptions` property. | `deviceActionDescriptions` must be populated | `manual` |

##### M — Firmware-Managed (Do NOT Set from a vDC)

| ID | Feature | Injected when | Effect |
|---|---|---|---|
| 61 | `outmodeenoceanvalve` | `implementationId = "EnOcean_Bus_Container"` + valve device | Adds EnOcean valve output mode. Also `not-supported-vdc` (DS485-only path). |
| 43 | `apartmentapplication` | FunctionID subclass (bits 11–6) = 0x07, 0x08, or 0x09 | Apartment-level application filtering; the only model feature the dSS firmware itself reads at runtime |
| 57 | `setumr200config` | Device type = UMR-200, revisionID ≥ 0x0370, multiDeviceIndex ≤ 1 | UMR-200 block assignment configuration |
| 63 | `grkl387workaround` | Device class = KL, revisionID = 0x387, device number ∈ {200,210,220,230} | Hardware revision 0x387 behavior correction. Also `not-supported-vdc` — meaningless for VDC devices. |

> **Note on `operationlock`:** Physical KL hardware devices have this injected by firmware, but for TCP/IP VDC (grey/shade) devices it is auto-derived by the library (`primaryGroup=2 + any output`) because the UI state is stored on dSS/vdSM side. See Section F above.

##### N — Feature Combination Quick Reference

All features in the "Auto-derived features" column are produced automatically by `derive_model_features()` when the stated condition is met. Features in the "Add manually if needed" column require an explicit `add_model_feature()` call.

| Device scenario | Auto-derived features (from `derive_model_features()`) | Add manually if needed |
|---|---|---|
| Dimmable light (DIMMER function) | `dontcare`, `blink`, `outvalue8`, `transt`, `dimtimeconfig` | — |
| Switched light (ON_OFF function) | `dontcare`, `blink`, `outvalue8`, `transt`, `outconfigswitch`, `impulseconfig` | — |
| Color light (FULL_COLOR_DIMMER) | `dontcare`, `blink`, `outvalue8`, `transt`, `outputchannels`, `dimtimeconfig` | — |
| Roller shutter / awning | `dontcare`, `blink`, `shadeposition`, `locationconfig`, `operationlock`, `windprotectionconfigawning` | `shadeprops`, `motiontimefins` not supported |
| Venetian blind / jalousie | `dontcare`, `blink`, `shadeposition`, `shadebladeang`, `locationconfig`, `operationlock`, `windprotectionconfigblind` | `shadeprops`, `motiontimefins` not supported |
| Heating valve (ON/OFF) | `dontcare`, `blink`, `outvalue8`, `transt`, `pwmvalue`, `outconfigswitch`, `impulseconfig`, `heatinggroup`, `heatingprops`, `valvetype`, `extendedvalvetypes` | — |
| Heating valve (continuous/PWM) | `dontcare`, `blink`, `outvalue8`, `transt`, `dimtimeconfig`, `pwmvalue`, `heatinggroup`, `heatingprops`, `valvetype`, `extendedvalvetypes` | — |
| Joker with group assignment | `jokerconfig` (pg=8), `highlevel` (when button with group=8 present) | — |
| 1-way push button | `pushbutton`, `pushbadvanced`, `pushbdisabled`, `pushbarea` (group≠8), `pushbdevice` (if supportsLocalKeyMode) | — |
| AKM sensor input | `akmsensor`, `akminput`, `akmdelay` (any binary input) | — |
| Device with identification | `blink` (any output), `identification` (when on_identify callback registered) | `blinkconfig` (not-tested) |
| Room controller (temperature + Blue) | `heatingprops`, `heatinggroup`, `temperatureoffset` (TEMPERATURE sensor + pg=3) | `ftwtempcontrolventilationselect` (not-tested) |
| Ventilation / Fan Coil Unit | `dontcare`, `blink`, `outvalue8`, `transt`, `dimtimeconfig`, `ventconfig`, `heatinggroup`, `heatingprops`, `valvetype`, `extendedvalvetypes`, `fcu` | — |

> **Notes:**
> - `transt` for shade devices is derived from shade position channel types (7–10), which fall in `_TRANST_CHANNEL_TYPES`. A properly configured shade device always has these channels, so `transt` is always derived.
> - `identification` is auto-derived only when the `on_identify` callback is registered on the device; it is never added unconditionally.
> - `highlevel` for joker devices is auto-derived from the button loop when any button has `group=8`; no manual call is needed.

---

### 4.2 Inputs

#### 4.2.1 Button Input

##### Container Properties (device-level)

| Property | acc | Description |
|---|---|---|
| `buttonInputDescriptions` | r | List of button description property elements (indexed `"0"`, `"1"`, …). |
| `buttonInputSettings` | r/w | List of button setting property elements. |
| `buttonInputStates` | r/w | List of button state property elements. |

##### Button Input Description (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | r | string | Human-readable name (e.g. hardware connector label). | Stored in button info. Shown in configurator button list. |
| `dsIndex` | r | integer | 0…N-1 sequential button index. Index 0 = primary / default button. | Used to address this button in settings and states. |
| `supportsLocalKeyMode` | r | boolean | `true` = button can be configured as a "device button" (controls device output directly). | When `true` → enables `pushbdevice` feature auto-assignment. |
| `buttonID` | r | optional integer | Physical button ID. All elements of the same multi-function hardware button share the same `buttonID`. | No fixed assignment if absent. |
| `buttonType` | r | integer enum | Physical button form factor — see table below. | Read-only descriptor; `pushbcombined` is NOT supported for TCP/IP VDC devices (hardware-specific to physical TKM/SDS devices). |
| `buttonElementID` | r | integer enum | Which element of a multi-contact button this represents — see table below. | Used for direction mapping (up/down/left/right). |

**buttonType values:**

| Value | Meaning | `ButtonType` (Python) |
|---|---|---|
| 0 | Undefined / other | `UNDEFINED` |
| 1 | Single pushbutton | `SINGLE_PUSHBUTTON` |
| 2 | 2-way pushbutton (rocker) | `TWO_WAY_PUSHBUTTON` |
| 3 | 4-way navigation button | `FOUR_WAY_NAVIGATION` |
| 4 | 4-way navigation with center | `FOUR_WAY_WITH_CENTER` |
| 5 | 8-way navigation with center | `EIGHT_WAY_WITH_CENTER` |
| 6 | On/Off switch | `ON_OFF_SWITCH` |

**buttonElementID values:**

| Value | Meaning | `ButtonElementID` (Python) |
|---|---|---|
| 0 | Center | `CENTER` |
| 1 | Down | `DOWN` |
| 2 | Up | `UP` |
| 3 | Left | `LEFT` |
| 4 | Right | `RIGHT` |
| 5 | Upper left | `UPPER_LEFT` |
| 6 | Lower left | `LOWER_LEFT` |
| 7 | Upper right | `UPPER_RIGHT` |
| 8 | Lower right | `LOWER_RIGHT` |

##### Button Input Settings (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `group` | r/w | integer | Target dS group for scene calls from this button. See §6 for group IDs. | Stored persistently. Determines which group's scenes the button triggers. |
| `function` | r/w | integer 0–15, 255 | Logical function (LTNUM lower bits) — see table below. | Controls which zone/area scene level the button operates at. 255 = inactive. |
| `mode` | r/w | integer enum | Button input mode (firmware `ButtonInputMode` enum) — see table below. | Processed by the dSS firmware for button state machine routing. |
| `channel` | r/w | integer enum | Channel this button controls: `0` = default channel; 1–191 = standard channel types; 192–239 = device-specific. | Determines which output channel the button dims or switches. |
| `setsLocalPriority` | r/w | boolean | When `true`, pressing this button sets the output into local priority mode. | Stored persistently. |
| `callsPresent` | r/w | boolean | When `true`, pressing this button calls the "Present" apartment scene if the system is in "Absent" state. | Stored persistently. |

**function values** (`ButtonFunction`, Python):

| Value | Meaning |
|---|---|
| 0 | Device (controls device output) |
| 1 | Area 1 |
| 2 | Area 2 |
| 3 | Area 3 |
| 4 | Area 4 |
| 5 | Room (zone-level) |
| 6–9 | Extended zone 1–4 |
| 10–13 | Extended area 1–4 |
| 14 | Apartment |
| 15 | App (generic, no automatic routing) |
| 255 | Inactive |

**mode values** (`ButtonMode`, Python):

| Value | Meaning |
|---|---|
| 0 | Standard (1-way push button) |
| 1 | Turbo (1-way) |
| 2 | Switched / toggle |
| 5 | 2-way down, paired with input 1 |
| 6 | 2-way down, paired with input 2 |
| 7 | 2-way down, paired with input 3 |
| 8 | 2-way down, paired with input 4 |
| 9 | 2-way up, paired with input 1 |
| 10 | 2-way up, paired with input 2 |
| 11 | 2-way up, paired with input 3 |
| 12 | 2-way up, paired with input 4 |
| 13 | 2-way |
| 14 | 1-way (explicit) |
| 16 | AKM standard |
| 17 | AKM inverted |
| 18 | AKM on rising edge |
| 19 | AKM on falling edge |
| 20 | AKM off rising edge |
| 21 | AKM off falling edge |
| 22 | AKM rising edge |
| 23 | AKM falling edge |
| 65 | Heating push button (1-way) |
| 255 | Deactivated |

> **2-way button convention (§8.1):** Index 0 = down button (`mode=6`, TWO_WAY_DOWN_PAIRED_2); index 1 = up button (`mode=9`, TWO_WAY_UP_PAIRED_1).

##### Button Input State (per element)

Regular click state:

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `value` | r | boolean / NULL | `false` = inactive, `true` = active, `NULL` = unknown. | Triggers the button state machine in the dSS. |
| `clickType` | r | integer enum | Most recent click event — see table below. | Mapped to scene calls via the button state machine. |
| `age` | r | double / NULL | Age of the current state in seconds. `NULL` if no recent state. | Used by the dSS to filter stale button events. |
| `error` | r | integer enum | Input error status — see §4.2.4. | Shown in configurator as device status. |

**clickType values** (`ButtonClickType`, Python):

| Value | Meaning |
|---|---|
| 0 | Tip 1× |
| 1 | Tip 2× |
| 2 | Tip 3× |
| 3 | Tip 4× |
| 4 | Hold start |
| 5 | Hold repeat |
| 6 | Hold end |
| 7 | Click 1× |
| 8 | Click 2× |
| 9 | Click 3× |
| 10 | Short-long |
| 11 | Local off |
| 12 | Local on |
| 13 | Short-short-long |
| 14 | Local stop |
| 15 | Local dim |
| 255 | Idle (no recent click) |

Direct scene call (alternative to click — present instead of `value`/`clickType`):

| Property | acc | Type | Description |
|---|---|---|---|
| `actionId` | r | integer | Scene ID to call directly. |
| `actionMode` | r | integer enum | `0`=normal, `1`=force, `2`=undo. |

---

#### 4.2.2 Binary Input

##### Container Properties (device-level)

| Property | acc | Description |
|---|---|---|
| `binaryInputDescriptions` | r | List of binary input description elements. |
| `binaryInputSettings` | r/w | List of binary input setting elements. |
| `binaryInputStates` | r/w | List of binary input state elements. |

##### Binary Input Description (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | r | string | Human-readable input name. | Read by `businterface.cpp` into `BinaryInputDesc.inputName`. |
| `dsIndex` | r | integer | 0…N-1 sequential binary input index. | Used to address the input in settings and states. |
| `inputType` | r | integer | Change detection capability: `0` = poll only; `1` = detects state changes (can push). | Stored in input descriptor. |
| `inputUsage` | r | integer enum | Usage context — see table below. | Stored in input descriptor. |
| `sensorFunction` | r | integer enum | Hardwired function of this input when it is not freely configurable. **The firmware reads this value** from `binaryInputDescriptions[n].sensorFunction` via `businterface.cpp:107`: `inputReader["sensorFunction"].getValueAsInt()` → cast to `BinaryInputType`. Use the same values as in settings. `0` = generic/app-mode; `12` = battery low (hardwired). | **Critical:** this value is used by the dSS to register the input function at scan time. The same enum table as `binaryInputSettings.sensorFunction`. |
| `updateInterval` | r | double | How fast the physical state is tracked, in seconds. | Used by the dSS to determine staleness. |

**inputUsage values** (`BinaryInputUsage`, Python):

| Value | Meaning |
|---|---|
| 0 | Undefined |
| 1 | Room climate |
| 2 | Outdoor climate |
| 3 | Climate setting (user input) |

##### Binary Input Settings (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `group` | r/w | integer | Target dS group for this binary input. | Stored persistently. Determines which group receives events from this input. |
| `sensorFunction` | r/w | integer enum | Logical function of the binary input — see table below. | Stored in `BinaryInputDesc.sensorFunction`. **Only `BinaryInputId=APP_MODE (15)` (i.e., `sensorFunction=0`, GENERIC) is interpreted and acted upon by the dSS firmware itself** (via `BinaryInputId::APP_MODE`). All other values are forwarded to and processed by the dSM bus module. |

**sensorFunction values** (`BinaryInputType`, Python — firmware `BinaryInputType` enum, values 0–23):

| Value | Meaning | `BinaryInputType` (Python) | dSS action on event |
|---|---|---|---|
| 0 | Generic / App Mode | `GENERIC` | **dSS interprets directly** (`BinaryInputId::APP_MODE=15`). Triggers automation rules. |
| 1 | Presence | `PRESENCE` | Forwarded to dSM for routing |
| 2 | Room brightness (binary) | `BRIGHTNESS` | Forwarded |
| 3 | Presence in darkness | `PRESENCE_IN_DARKNESS` | Forwarded |
| 4 | Twilight | `TWILIGHT` | Forwarded |
| 5 | Motion detector | `MOTION` | Forwarded |
| 6 | Motion in darkness | `MOTION_IN_DARKNESS` | Forwarded |
| 7 | Smoke detector | `SMOKE` | Forwarded; triggers SceneSmoke if routing configured |
| 8 | Wind monitor | `WIND` | Forwarded; triggers SceneWindActive/Inactive |
| 9 | Rain monitor | `RAIN` | Forwarded; triggers SceneRainActive/Inactive |
| 10 | Sun radiation | `SUN_RADIATION` | Forwarded |
| 11 | Room thermostat | `THERMOSTAT` | Forwarded |
| 12 | Battery low | `BATTERY_LOW` | Forwarded; triggers low-battery status |
| 13 | Window contact (open=active) | `WINDOW_OPEN` | Forwarded |
| 14 | Door contact (open=active) | `DOOR_OPEN` | Forwarded |
| 15 | Window handle (close/open/tilted) | `WINDOW_TILTED` | Extended value: 0=closed, 1=open, 2=tilted |
| 16 | Garage door contact | `GARAGE_DOOR_OPEN` | Forwarded |
| 17 | Sun protection trigger | `SUN_PROTECTION` | Forwarded |
| 18 | Frost detector | `FROST` | Forwarded |
| 19 | Heating system enabled | `HEATING_SYSTEM_ENABLED` | Forwarded; heating change-over logic |
| 20 | Heating change-over (heat/cool) | `HEATING_CHANGE_OVER` | Forwarded; switches between heating and cooling mode |
| 21 | Initialization / power-up | `INITIALIZATION` | Forwarded; set during device startup |
| 22 | Malfunction | `MALFUNCTION` | Forwarded; device requires maintenance, operation may cease |
| 23 | Service required | `SERVICE` | Forwarded; device requires maintenance, normal operation continues |

##### Binary Input State (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `value` | r | boolean / NULL | `false`=inactive, `true`=active, `NULL`=unknown. | Triggers binary input event processing in dSS. |
| `extendedValue` | r | integer / NULL | Extended state value, replacing `value` when present. Used for window handle (0=closed, 1=open, 2=tilted). | dSS reads `extendedValue` when present instead of `value`. |
| `age` | r | double / NULL | Age of the current state in seconds. | Used for staleness filtering. |
| `error` | r | integer enum | Input error — see §4.2.4. | Shown in configurator. |

---

#### 4.2.3 Sensor Input

##### Container Properties (device-level)

| Property | acc | Description |
|---|---|---|
| `sensorDescriptions` | r | List of sensor description elements. |
| `sensorSettings` | r/w | List of sensor setting elements. |
| `sensorStates` | r/w | List of sensor state elements. |

##### Sensor Input Description (per element)

All fields are read by the dSS firmware via `businterface.cpp:60–87`.

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | r | string | Human-readable sensor name (also technical identifier). Read via `sensorReader.getName()` (v3 format) or `sensorReader["name"]` (legacy). | Stored as `SensorDesc.sensorName`. Used as the key in the sensor map. |
| `dsIndex` | r | integer | 0…N-1 sequential sensor index. | Used to address this sensor in settings and states. |
| `sensorType` | r | integer enum | Physical measurement type — see full table below. **The firmware reads this directly**: `static_cast<SensorType>(sensorReader["sensorType"].getValueAsInt())`. | Stored as `SensorDesc.sensorType`. Determines the unit, scale, and routing of sensor data in dSS. |
| `sensorUsage` | r | integer enum | Usage context — see table below. | Stored as `SensorDesc.sensorUsage`. |
| `min` | r | double | Minimum physical value in the sensor's unit. | Stored in `SensorDesc.min`. Used for range checking. |
| `max` | r | double | Maximum physical value in the sensor's unit. | Stored in `SensorDesc.max`. |
| `resolution` | r | double | Value of the least significant bit (precision of the sensor). | Stored in `SensorDesc.resolution`. |
| `updateInterval` | r | double | Expected update rate in seconds (time resolution the sensor provides). | Stored in `SensorDesc.updateInterval`. |
| `aliveSignInterval` | r | double | Maximum expected time between updates. If exceeded, the sensor is considered offline. | Used by the dSS for timeout / fault detection. |

**sensorType values** (`SensorType`, Python — firmware `SensorType` enum via `businterface.cpp`):

| Value | Physical quantity | Unit | `SensorType` (Python) |
|---|---|---|---|
| 0 | None / not defined | — | `NONE` |
| 1 | Temperature | °C | `TEMPERATURE` |
| 2 | Relative humidity | % | `HUMIDITY` |
| 3 | Illumination | lux | `ILLUMINATION` |
| 4 | Supply voltage | V | `SUPPLY_VOLTAGE` |
| 5 | CO concentration | ppm | `CO_CONCENTRATION` |
| 6 | Radon activity | Bq/m³ | `RADON_ACTIVITY` |
| 7 | Gas type sensor | — | `GAS_TYPE` |
| 8 | Particles \<10 µm | µg/m³ | `PARTICLES_PM10` |
| 9 | Particles \<2.5 µm | µg/m³ | `PARTICLES_PM2_5` |
| 10 | Particles \<1 µm | µg/m³ | `PARTICLES_PM1` |
| 11 | Room operating panel setpoint | 0–100 % | `ROOM_OPERATING_PANEL` |
| 12 | Fan speed | 0–1 (0=off, \<0=auto) | `FAN_SPEED` |
| 13 | Wind speed (average) | m/s | `WIND_SPEED` |
| 14 | Active power | W | `ACTIVE_POWER` |
| 15 | Electric current | A | `ELECTRIC_CURRENT` |
| 16 | Energy meter | kWh | `ENERGY_METER` |
| 17 | Apparent power | VA | `APPARENT_POWER` |
| 18 | Air pressure | hPa | `AIR_PRESSURE` |
| 19 | Wind direction | degrees | `WIND_DIRECTION` |
| 20 | Sound pressure level | dB | `SOUND_PRESSURE_LEVEL` |
| 21 | Precipitation intensity | mm/m² (last hour) | `PRECIPITATION` |
| 22 | CO₂ concentration | ppm | `CO2_CONCENTRATION` |
| 23 | Wind gust speed | m/s | `WIND_GUST_SPEED` |
| 24 | Wind gust direction | degrees | `WIND_GUST_DIRECTION` |
| 25 | Generated active power | W | `GENERATED_ACTIVE_POWER` |
| 26 | Generated energy | kWh | `GENERATED_ENERGY` |
| 27 | Water quantity | l | `WATER_QUANTITY` |
| 28 | Water flow rate | l/s | `WATER_FLOW_RATE` |
| 29 | Length | m | `LENGTH` |
| 30 | Mass | kg | `MASS` |
| 31 | Duration | s | `DURATION` |
| 32 | Percentage | % | `PERCENT` |
| 33 | Speed percentage | % | `PERCENT_SPEED` |
| 34 | Frequency | Hz | `FREQUENCY` |

> **Firmware note:** The firmware's own `SensorType` enum (modelconst.h) uses different numbering (e.g., `ActivePower=4`, `TemperatureIndoors=9`). The values in the table above are the **vDC API wire-protocol values** as read by `businterface.cpp` and used in `sensorDescriptions`. These are the values the Python library's `SensorType` enum uses.

**sensorUsage values** (`SensorUsage`, Python):

| Value | Meaning |
|---|---|
| 0 | Undefined |
| 1 | Room |
| 2 | Outdoor |
| 3 | User interaction (setting, dial) |
| 4 | Device level measurement (total/sum) |
| 5 | Device level last run |
| 6 | Device level average |

##### Sensor Input Settings (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `group` | r/w | integer | Target dS group for sensor data routing. | Stored persistently. |
| `minPushInterval` | r/w | double | Minimum interval between pushed state updates in seconds (default: 2). | Throttles push notifications from the vDC. |
| `changesOnlyInterval` | r/w | double | Minimum interval between pushes when the value has not changed (default: 0 = all updates forwarded). | Reduces redundant pushes for slow-changing sensors. |

##### Sensor Input State (per element)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `value` | r | double / NULL | Current sensor value in the unit given by `sensorType`. `NULL` = no recent value. | Stored and forwarded to the dSS data model. Triggers sensor event routing. |
| `age` | r | double / NULL | Age of the current value in seconds. | Used for staleness detection. |
| `contextId` | r | integer / NULL | Numerical context data ID (optional). | Used for sensor context disambiguation. |
| `contextMsg` | r | string / NULL | Text message for context data (optional). | Displayed alongside the sensor value if present. |
| `error` | r | integer enum | Input error — see §4.2.4. | Shown in configurator. |

---

#### 4.2.4 Input Error Codes (Shared)

Used by `buttonInputStates.error`, `binaryInputStates.error`, and `sensorStates.error`.

| Value | Meaning | `InputError` (Python) |
|---|---|---|
| 0 | OK | `OK` |
| 1 | Open circuit | `OPEN_CIRCUIT` |
| 2 | Short circuit | `SHORT_CIRCUIT` |
| 4 | Bus connection problem | `BUS_CONNECTION` |
| 5 | Low battery | `LOW_BATTERY` |
| 6 | Other device error | `OTHER_ERROR` |

---

#### 4.2.5 Action Descriptions

Available only when `dynamicDefinitions=true` **or** when the GTIN is in the VdcDb. See §7.1 and §7.2.

##### Container Properties

| Property | acc | Description |
|---|---|---|
| `deviceActionDescriptions` | r | Template action definitions (invariable). |
| `customActions` | r/w | User-created custom actions (persistent). |
| `standardActions` | r | Standard actions (invariable, prefixed `std.`). |
| `dynamicDeviceActions` | r | Dynamically created actions from the device side (prefixed `dynamic.`). |

##### Action Parameter Object (used in descriptions)

| Field | Required | Type | Description |
|---|---|---|---|
| `type` | yes | string enum | Data type: `"numeric"`, `"enumeration"`, `"string"` |
| `min` | no (numeric) | double | Minimum value |
| `max` | no (numeric) | double | Maximum value |
| `resolution` | no (numeric) | double | Precision (LSB size) |
| `siunit` | no (numeric) | string | SI unit string with prefix |
| `options` | no (enum) | key:value list | Enumeration options |
| `default` | no | varies | Default parameter value |

##### Device Action Description (per element in `deviceActionDescriptions`)

| Field | Required | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | yes | string | Template action name (technical identifier). | Used to invoke the action via `VDSM_REQUEST_GENERIC_REQUEST` with method `invokeDeviceAction`. |
| `params` | no | list of parameter objects | Parameter definitions for this action. | Shown as configurable fields in the configurator Activities tab. |
| `description` | no | string | Human-readable description of the action. | Shown in the configurator Activities tab. |

##### Standard Action (per element in `standardActions`)

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Unique ID, always prefixed `std.` |
| `action` | yes | string | Reference to the template action name. |
| `params` | no | key:value pairs | Parameter overrides relative to the template. |

##### Custom Action (per element in `customActions`)

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Unique ID, always prefixed `custom.` |
| `action` | yes | string | Reference to the template action name. |
| `title` | yes | string | Human-readable name (user-given). |
| `params` | no | key:value pairs | Parameter overrides relative to the template. |

##### Dynamic Device Action (per element in `dynamicDeviceActions`)

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Unique ID, always prefixed `dynamic.` |
| `title` | yes | string | Human-readable name. |

---

#### 4.2.6 Device States and Properties

Available via the GTIN lookup (VdcDb) and/or `dynamicDefinitions=true`. See §7.1 and §7.2.

##### Container Properties

| Property | acc | Description |
|---|---|---|
| `deviceStateDescriptions` | r | State descriptor list (invariable). |
| `deviceStates` | r/w | Current state values. |
| `devicePropertyDescriptions` | r | Property descriptor list (invariable). |
| `deviceProperties` | r/w | Current property values. |

##### Device State Description (per element in `deviceStateDescriptions`)

| Field | Required | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | yes | string | State identifier. | Used in automation rule conditions. Must match VdcDb state names for state-condition automation to work (see §7.2). |
| `options` | yes | key:value list | All possible state values (e.g. `0: Off`, `1: Running`, `2: Error`). | Shown as dropdown options in the configurator Scene Responder and UDA. |
| `description` | no | string | Human-readable description. | Shown in the configurator. |

##### Device State Value (per element in `deviceStates`)

| Field | Required | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | yes | string | State identifier (matching `deviceStateDescriptions`). | Used to look up the state in `m_states`. If not registered, `setStateValue()` is a no-op — automation conditions do not trigger. |
| `value` | yes | string | Current state option value. | Triggers `raiseEvent(createDeviceStateEvent())` unconditionally; triggers `setStateValue()` only if the state was registered from VdcDb. |

##### Device Property Description (per element in `devicePropertyDescriptions`)

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Property identifier. |
| `type` | yes | string enum | Data type: `"numeric"`, `"enumeration"`, `"string"`. |
| `min` | no (numeric) | double | Minimum value |
| `max` | no (numeric) | double | Maximum value |
| `resolution` | no (numeric) | double | Precision |
| `siunit` | no (numeric) | string | SI unit string |
| `options` | no (enum) | key:value list | Option values |
| `default` | no | varies | Default value |

##### Device Property Value (per element in `deviceProperties`)

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | Property identifier. |
| `value` | yes | string | Current property value. |

---

#### 4.2.7 Device Events

Available via the GTIN lookup (VdcDb) and/or `dynamicDefinitions=true`. See §7.1 and §7.2.

##### Container Properties

| Property | acc | Description |
|---|---|---|
| `deviceEventDescriptions` | r | Event descriptor list (invariable). |

##### Device Event Description (per element)

| Field | Required | Type | Description | dSS handling |
|---|---|---|---|---|
| `name` | yes | string | Event identifier. | When a push notification with this event name arrives, `raiseEvent(createDeviceEventEvent())` fires **unconditionally** — regardless of VdcDb registration. Automation rules triggered by `DeviceEventEvent` work without GTIN backing. |
| `description` | no | string | Human-readable description. | Shown in the configurator. |

---

### 4.3 Output

A vdSD has at most one output. Devices without output (pure button/sensor devices) do not return any output-related properties.

#### 4.3.1 Output Description (`outputDescription`)

Read-only hardware characteristics. Read by the dSS via `VdcHelper::getClimateSettings()` for `activeCoolingMode` (vdc-connection.cpp:269–276). The `function` field is **not read** by the dSS firmware — it is purely informational for configurator consumers.

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `function` | r | integer enum | Functional output type — see table below. | **Not read by dSS firmware.** Purely for configurator display and client code. The auto-created channels in pydsvdcapi are determined by this value, but the firmware ignores it. |
| `defaultGroup` | r | integer | Application Group ID for this output. Use `ColorClass` enum values (1–12, 48, 64, 65, 69). Informational only — zero runtime callers in the dSS firmware read this field for routing. Example: Yellow light: `defaultGroup=1` (`ColorClass.LIGHTS`); Grey blind: `defaultGroup=2` (`ColorClass.BLINDS`); Blue heating valve: `defaultGroup=3` (`ColorClass.HEATING`); Blue ventilation: `defaultGroup=10` (`ColorClass.VENTILATION`). |
| `outputUsage` | r | integer enum | Usage context beyond device colour — see table below. | Stored in output descriptor. Shown in configurator. |
| `variableRamp` | r | boolean | `true` = output supports variable-speed transitions. | Stored. Shown in configurator. |
| `maxPower` | r | optional double | Maximum output power in Watts. | Stored. Shown in configurator (power bar). |
| `activeCoolingMode` | r | optional boolean | `true` = device can actively cool (air-con, FCU). | **Read by dSS firmware** via `VdcHelper::getClimateSettings()` → `dev->setActiveCoolingMode()`. The dSS configurator also **writes this value back** to the vDC when the user switches a heating device to cooling mode. |
| `name` | r | string | Human-readable output name. | Stored. Shown in configurator. |

**function values** (`OutputFunction`, Python):

| Value | Meaning | Auto-created channels |
|---|---|---|
| 0 | ON_OFF — binary switch | brightness (type 1) |
| 1 | DIMMER — brightness with transitions | brightness (type 1) |
| 2 | POSITIONAL — absolute position, 0–100 % | none (add manually: type 7 or 8) |
| 3 | DIMMER_COLOR_TEMP — tunable white | brightness (1) + colortemp (4) |
| 4 | FULL_COLOR_DIMMER — RGB/RGBW | brightness (1) + hue (2) + saturation (3) + colortemp (4) + cieX (5) + cieY (6) |
| 5 | BIPOLAR — positive and negative range | none |
| 6 | INTERNALLY_CONTROLLED — device drives its own output | none |
| 127 | CUSTOM — action-output, no standard channels | none |

**outputUsage values** (`OutputUsage`, Python):

| Value | Meaning |
|---|---|
| 0 | Undefined |
| 1 | Room |
| 2 | Outdoors |
| 3 | User (display/indicator) |

#### 4.3.2 Output Settings (`outputSettings`)

Writable, persistently stored. The dSS firmware reads `heatingSystemType` from this group via `VdcHelper::getClimateSettings()` (vdc-connection.cpp:278–285). The dSS also **writes** `heatingSystemType` back when the user changes the valve type in the configurator.

> **Group-field processing note:** For the **backend-VDC path**, `activeGroup` and `groups` are **not read** by the dSS — it uses `primaryGroup` for both `addToGroup()` and `setActiveGroup()`. For the **classic TCP/IP VDC path**, the vdSM reads these fields and translates them to the dS485 bus protocol.

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `activeGroup` | r/w | integer | Application Group ID this output is currently active in. Use `ColorClass` enum values (1–12, 48, 64, 65, 69). Usually equals `defaultGroup`. Joker devices may differ (e.g. `primaryGroup=8`, `activeGroup=1` to join light scenes). Values < 64 must be present in `groups`. | **Backend-VDC:** not read — `primaryGroup` is used via `setActiveGroup(primaryGroup)`. **Classic-VDC:** vdSM → `DeviceSpec.activeGroup` → `m_ActiveGroup`. |
| `groups` | r/w | property list (`gid` → boolean) | Set of Application Group IDs this output belongs to. Only `true` entries are returned. Valid range: **1–63 only**. Global app groups ≥ 64 (`APARTMENT_VENTILATION=64`, `AWNINGS=65`, `APARTMENT_RECIRCULATION=69`) must NOT appear here — use them only in `activeGroup` and `defaultGroup`. | **Backend-VDC:** not read — only `primaryGroup` is added via `addToGroup()`. **Classic-VDC:** vdSM builds the dS485 groups bitmask → `addToGroup()` per entry. |
| `mode` | r/w | integer enum | Output capability hint — see table below. **Not read by the dSS firmware runtime** for TCP/IP VDC devices (the field is stored but never consumed by scene handling, dim timing, or any other runtime logic). The dSS **configurator** (web/app frontend) reads this value to decide which UI controls to render. Setting it incorrectly (or leaving it at 127/Default) causes the "Edit Device Values" dialog not to open. | Stored persistently in the vDC. |
| `pushChanges` | r/w | boolean | When `true`, locally generated output changes are pushed to the dSS via `VDC_SEND_PUSH_NOTIFICATION`. | Stored. Enables reactive device-to-dSS synchronization. |
| `onThreshold` | r/w | optional double | Minimum brightness (0–100 %) to switch on non-dimmable lamps. Defaults to 50 %. | Stored. Used by the dSS to determine when a non-dimmable lamp switches on. |
| `minBrightness` | r/w | optional double | Minimum brightness (0–100 %) the hardware supports. Used for `callSceneMin` and dim-down. | Stored. |
| `dimTimeUp` | r/w | optional integer | Dim-up time in dS 8-bit format: `4 MSBs=exp, 4 LSBs=lin, time = 100ms/32 × 2^exp × (17+lin)`. | Stored. Used by the dSS for transition timing. |
| `dimTimeDown` | r/w | optional integer | Dim-down time in dS 8-bit format. | Stored. |
| `dimTimeUpAlt1` | r/w | optional integer | Alternate 1 dim-up time (for `dimtimeconfig`). | Stored. |
| `dimTimeDownAlt1` | r/w | optional integer | Alternate 1 dim-down time. | Stored. |
| `dimTimeUpAlt2` | r/w | optional integer | Alternate 2 dim-up time (for `dimtimeconfig`). | Stored. |
| `dimTimeDownAlt2` | r/w | optional integer | Alternate 2 dim-down time. | Stored. |
| `heatingSystemCapability` | r/w | optional integer enum | How the `heatingLevel` control value is applied — see table below. | Stored. Used by the dSS to interpret `setControlValue(heatingLevel)`. |
| `heatingSystemType` | r/w | optional integer enum | Kind of heating/cooling actuator attached — see table below. | **Read by dSS firmware** at scan time via `VdcHelper::getClimateSettings()` → `dev->setValveType()`. **Written back** by the dSS when the user changes valve type in the configurator. |

**mode values** (`OutputMode`, Python):

| Value | Name | Configurator effect | Use with `OutputFunction` |
|---|---|---|---|
| 0 | `DISABLED` | No UI controls shown | `CUSTOM`, `INTERNALLY_CONTROLLED` |
| 1 | `BINARY` | On/off toggle only (no slider) | `ON_OFF` |
| 2 | `GRADUAL` | Full slider in "Edit Device Values" | `DIMMER`, `POSITIONAL`, `DIMMER_COLOR_TEMP`, `FULL_COLOR_DIMMER`, `BIPOLAR` |
| 127 | `DEFAULT` | **Avoid.** Configurator receives no hint → "Edit Device Values" typically does not open | — |

> **Note:** `OutputMode` values (0, 1, 2, 127) are from the vDC API protocol specification. They are completely different from `OutputHardwareMode` values (0, 16–42), which are physical hardware dimmer-circuit types used on the DS485 bus for physical devices. `OutputHardwareMode` has no meaning in the VDC context.

**heatingSystemCapability values** (`HeatingSystemCapability`, Python):

| Value | Meaning |
|---|---|
| 1 | Heating only (`heatingLevel` 0–100 → output 0–100) |
| 2 | Cooling only (`heatingLevel` 0 to −100 → output 0–100) |
| 3 | Heating and cooling (bipolar: `heatingLevel` −100–100 applied directly) |

**heatingSystemType values** (`HeatingSystemType`, Python):

| Value | Meaning |
|---|---|
| 0 | Undefined |
| 1 | Floor heating valve |
| 2 | Radiator valve |
| 3 | Wall heating valve |
| 4 | Convector (passive) |
| 5 | Convector (active) |
| 6 | Floor heating, low energy |

#### 4.3.3 Output State (`outputState`)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `localPriority` | r/w | boolean | When `true`, output ignores scene calls unless the scene has `ignoreLocalPriority` set or the call uses `force=true`. | Stored. Prevents remote scene calls from overriding local operation. |
| `error` | r | integer enum | Output error status — see table below. | Shown in configurator as device error indicator. |
| `transitionTime` | r/w | double | Time in seconds for the ongoing output transition. `0.0` when idle. | Not currently used by dSS firmware; carried for wire-format compatibility with p44vdc. |
| `movingState` | r/w | integer | Motor movement state for shade/blind outputs: `0` = idle, `1` = moving open/up, `-1` = moving closed/down. | Not currently read by dSS firmware; carried for wire-format compatibility with p44vdc `ShadowBehaviour`. |

**error values** (`OutputError`, Python):

| Value | Meaning |
|---|---|
| 0 | OK |
| 1 | Open circuit / lamp broken |
| 2 | Short circuit |
| 3 | Overload |
| 4 | Bus connection problem |
| 5 | Low battery |
| 6 | Other device error |

---

### 4.4 Output Channels

An output has zero or more channels. Each channel controls one independent physical dimension of the output (brightness, color, shade position, etc.). Channel index 0 is the primary/default channel.

> **Key format:** `channelDescriptions`, `channelSettings`, and `channelStates` are each transmitted as a **single** `PropertyElement` whose child elements are keyed by the channel's **dsIndex as a string** (e.g. `"0"`, `"1"`), matching the p44vdc wire format.  The channel name is carried as the `name` field *inside* each element.  The `channelId` field in `setOutputChannelValue` notifications carries the name string; `VdcHost` resolves channels by that name — this is independent of the property-tree key format.

#### 4.4.1 Channel Description (`channelDescriptions`)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `channelType` | r | integer | Numerical channel type ID — see table below. **Firmware reads and maps directly**: `static_cast<ChannelType>(value)` (modelconst.h). | Used for all channel-related API calls. Determines scene value interpretation. |
| `dsIndex` | r | integer | 0…N-1 sequential channel index. Index 0 = default/primary output channel. | Used for dS-OS and DSMAPI addressing of individual channels. |
| `name` | r | string | Human-readable channel name. | Shown in scene editor. |
| `min` | r | double | Minimum channel value. | Used as the "off" value in scenes and dim-to-minimum calls. |
| `max` | r | double | Maximum channel value. | Used as the "on" / dim-to-maximum value. |
| `resolution` | r | double | Value of the LSB (precision). | Used for value quantization. |
| `siunit` | r | string | SI unit name (e.g. `"percent"`, `"degree"`, `"reciprocal megakelvin"`, `"celsius"`). Optional — absent for dimensionless channels. | Used by dSS firmware for channel value validation and unit display. |
| `symbol` | r | string | Unit symbol string (e.g. `"%"`, `"°"`, `"mired"`, `"°C"`). Optional — absent for dimensionless channels. | Shown in the dSS configurator channel value displays. |

**channelType values** — firmware-verified from `ChannelType` enum in `modelconst.h`:

| ID | Name | Min | Max | Unit | `OutputChannelType` (Python) | Notes |
|---|---|---|---|---|---|---|
| 0 | default | — | — | — | `DEFAULT` | Generic default (type unspecified) |
| 1 | brightness | 0 | 100 | % | `BRIGHTNESS` | Light brightness |
| 2 | hue | 0 | 360 | degrees | `HUE` | Coloured light hue |
| 3 | saturation | 0 | 100 | % | `SATURATION` | Coloured light saturation |
| 4 | colortemp | 100 | 1000 | mired | `COLOR_TEMPERATURE` | Colour temperature (lower = warmer) |
| 5 | x (CIE) | 0 | 10000 | scaled 0.0–1.0 | `CIE_X` | CIE 1931 x coordinate |
| 6 | y (CIE) | 0 | 10000 | scaled 0.0–1.0 | `CIE_Y` | CIE 1931 y coordinate |
| 7 | shadePositionOutside | 0 | 100 | % | `SHADE_POSITION_OUTSIDE` | Blind/shutter position (outdoors) |
| 8 | shadePositionIndoor | 0 | 100 | % | `SHADE_POSITION_INDOOR` | Curtain position (indoors) |
| 9 | shadeOpeningAngleOutside | 0 | 100 | % | `SHADE_OPENING_ANGLE_OUTSIDE` | Blind slat angle (outdoors) |
| 10 | shadeOpeningAngleIndoor | 0 | 100 | % | `SHADE_OPENING_ANGLE_INDOOR` | Curtain opening angle (indoors) |
| 11 | transparency | 0 | 100 | % | `TRANSPARENCY` | Smart glass transparency |
| 12 | airFlowIntensity | 0 | 100 | % | `AIR_FLOW_INTENSITY` | Fan/ventilation intensity |
| 13 | airFlowDirection | 0 | 2 | enum | `AIR_FLOW_DIRECTION` | 0=both/undefined, 1=supply-in, 2=exhaust-out |
| 14 | airFlapPosition | 0 | 100 | % | `AIR_FLAP_POSITION` | Flap/damper opening angle |
| 15 | airLouverPosition | 0 | 100 | % | `AIR_LOUVER_POSITION` | Louver position |
| 16 | heatingPower | 0 | 100 | % | `HEATING_POWER` | Heating output level |
| 17 | coolingCapacity | 0 | 100 | % | `COOLING_CAPACITY` | Cooling output level |
| 18 | audioVolume | 0 | 100 | % | `AUDIO_VOLUME` | Loudness |
| 19 | powerState | 0 | 3 | enum | `POWER_STATE` | 0=off, 1=on, 2=forced-off, 3=standby |
| 20 | airLouverAuto | 0 | 1 | enum | `AIR_LOUVER_AUTO` | 0=not active, 1=auto swing |
| 21 | airFlowAuto | 0 | 1 | enum | `AIR_FLOW_AUTO` | 0=not active, 1=auto intensity |
| 22 | waterTemperature | 0 | 150 | °C | `WATER_TEMPERATURE` | Water temperature |
| 23 | waterFlowRate | 0 | 100 | % | `WATER_FLOW_RATE` | Water flow rate |
| 24 | powerLevel | 0 | 100 | % | `POWER_LEVEL` | Generic power level |
| 25 | videoStation | — | — | station# | `VIDEO_STATION` | Video channel/station number |
| 26 | videoInputSource | — | — | source# | `VIDEO_INPUT_SOURCE` | Video input source selector |
| 192+ | device-specific | — | — | — | — | Reserved for custom device channels |

> **Historical note:** Earlier documentation (pre-2024) listed shade channels at IDs 11–15, heating at 21, audio at 41, and power state at 53. Those were incorrect. The values in this table match the firmware's `ChannelType` enum and are the authoritative wire-protocol values.

#### 4.4.2 Channel Settings (`channelSettings`)

Currently no per-channel settings are defined. Querying this property returns an empty structure.

#### 4.4.3 Channel State (`channelStates`)

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `value` | r | double | Current channel value in the unit from `channelDescription`. | Written by the dSS via `setOutputChannelValue` notification. Read during state sync. |
| `age` | r | double | Age of the current value in seconds. `NULL` when a new value has been set but not yet applied to hardware. | Used by the dSS to detect pending vs. applied state. |

> Channel states must **not** be written via `setProperty`. Use the `VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE` notification message instead.

---

### 4.5 Scene Configuration (`scenes`)

A scene stores a set of output values to apply when the scene is called. Scenes are indexed by scene number (0–127).

| Property | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `channels` | r/w | property list | Per-channel scene values, keyed by `channelType` ID (string). Each entry contains a scene value — see §4.5.1. | Stored in the vDC scene table. Applied by `callScene()`. |
| `effect` | r/w | integer enum | Transition effect when scene is invoked — see table below. | Determines the fade curve applied when transitioning to the scene values. |
| `dontCare` | r/w | boolean | Scene-global don't-care: if `true`, this scene does not apply any channel values, regardless of per-channel flags. | Stored. When `true`, `callScene` on this scene is a no-op. |
| `ignoreLocalPriority` | r/w | boolean | When `true`, calling this scene overrides local priority. | Stored. Enables panic/alarm scenes to override manual control. |

**effect values** (`SceneEffect`, Python):

| Value | Meaning |
|---|---|
| 0 | NONE — immediate transition |
| 1 | SMOOTH — normal fade (former dimTimeSelector=0) |
| 2 | SLOW — slow fade (former dimTimeSelector=1) |
| 3 | VERY_SLOW — very slow fade (former dimTimeSelector=2) |
| 4 | ALERT — blink/alerting effect |

#### 4.5.1 Scene Value (per channel in `scenes.channels`)

| Property | acc | Type | Description |
|---|---|---|---|
| `value` | r/w | double | The value to apply to the channel when the scene is called. Range/unit from `channelDescription`. |
| `dontCare` | r/w | boolean | If `true`, calling this scene does not change this channel's value. |
| `automatic` | r/w | boolean | If `true`, calling this scene activates the device's internal automatic control logic for this channel. |

---

## 5. Control Values

Control values are write-only named values sent via `setControlValue` (not regular properties). They cannot be read.

| Name | acc | Type | Description | dSS handling |
|---|---|---|---|---|
| `heatingLevel` | w | double −100 to +100 | Heating/cooling intensity. `0` = no output; `100` = maximum heating; `−100` = maximum cooling. Interpretation depends on `heatingSystemCapability`. | Sent via `VDSM_NOTIFICATION_SET_CONTROL_VALUE`. Maps to sensor type 51 (`RoomTemperatureControlVariable`) in the dSS automation model. The dSS climate controller writes this to devices in the heating group based on the temperature control algorithm. |

---

## 6. Group ID Space

The dSS uses a unified integer space for group IDs. However, the same integer space serves two distinct purposes depending on the field:

- **`primaryGroup`** and **button/binary-input `group`** use **Application Group IDs** drawn from the range 1–12, 48. For TCP/IP VDC, `primaryGroup` is restricted to 1–9 only.
- **`outputDescription.defaultGroup`** and **`outputSettings.activeGroup`** use `ColorClass` enum values (Application Group IDs 1–12, 48, 64, 65, 69).
- **`outputSettings.groups`** also uses `ColorClass` values but is restricted to 1–63; global app groups ≥ 64 must not appear here.

All three output fields draw from the same integer space as `primaryGroup`, but while `primaryGroup` describes *which device color class* the device belongs to, the output fields describe *which application group(s)* the output participates in — these are the same integer space but the semantic scope differs for joker devices and apartment-level groups.

**GroupID / `primaryGroup` space:**

| Range | Type | Constants | Notes |
|---|---|---|---|
| 0 | Broadcast | `GroupIDBroadcast` | Address all groups simultaneously |
| 1 | Yellow — lights | `GroupIDYellow` | = `ApplicationType::lights` |
| 2 | Grey — shades | `GroupIDGray` | = `ApplicationType::blinds` |
| 3 | Blue — heating | `GroupIDHeating` | = `ApplicationType::heating` |
| 4 | Cyan — audio | `GroupIDCyan` | = `ApplicationType::audio` |
| 5 | Violet — video | `GroupIDViolet` | = `ApplicationType::video` |
| 6 | Red — security *(deprecated)* | `GroupIDRed` | = `ApplicationType::security` |
| 7 | Green — access *(deprecated)* | `GroupIDGreen` | = `ApplicationType::access` |
| 8 | Black — joker | `GroupIDBlack` | = `ApplicationType::joker` |
| 9 | Cooling / White single device | `GroupIDCooling` / `ColorIDWhite` | Same integer: cooling for hardware, white/single-device for VDC |
| 10 | Ventilation | `GroupIDVentilation` | = `ApplicationType::ventilation` |
| 11 | Window | `GroupIDWindow` | = `ApplicationType::window` |
| 12 | Recirculation | `GroupIDRecirculation` | = `ApplicationType::recirculation` |
| 13–15 | Reserved | — | Do not use |
| 16–39 | Clusters (user-defined groups) | `GroupIDAppUserMin`–`GroupIDAppUserMax` | User-configurable in dSS configurator |
| 40–47 | Zone user groups | `GroupIDUserGroupStart`–`GroupIDUserGroupEnd` | Per-zone user groups |
| 48 | Temperature control | `GroupIDControlTemperature` | = `ApplicationType::temperature` |
| 49–55 | Other control groups | `GroupIDControlGroupMin`–`GroupIDControlGroupMax` | Reserved control group range |
| 64 | Apartment ventilation | `GroupIDGlobalAppDsVentilation` | = `ApplicationType::apartmentVentilation` |
| 65 | Awnings | `GroupIDGlobalAppDsAwnings` | = `ApplicationType::awnings` |
| 69 | Apartment recirculation | `GroupIDGlobalAppDsRecirculation` | = `ApplicationType::apartmentRecirculation` |
| 64–187 | Global DS application groups | `GroupIDGlobalAppDsMin`–`GroupIDGlobalAppDsMax` | Managed by digitalSTROM |
| 188–249 | Global user application groups | `GroupIDGlobalAppUserMin`–`GroupIDGlobalAppUserMax` | User-definable global groups |
| 255 | Not applicable | `GroupIDNotApplicable` | Sentinel value |

**`isValidGroup()` logic** (firmware `modelconst.h:578`): Accepts default groups (1–15), clusters (16–39), zone user groups (40–47), control groups (48–55), and global app groups (64–249). Groups 0 and 255 are not valid for `addToGroup()`.

---

## 7. Dependencies and Behaviors

### 7.1 dynamicDefinitions — Dependency Chain

`dynamicDefinitions` is the master switch for all dynamic device feature display in the configurator.

```
vDC.capabilities.dynamicDefinitions = true
  └── dSS reads descriptions from VDC live (not from VdcDb):
        deviceStateDescriptions   → names/options shown in Scene Responder, UDA, condition editor
        deviceEventDescriptions   → events shown in automations
        deviceActionDescriptions  → actions shown in Activities tab
        devicePropertyDescriptions → properties shown in device details
```

**When `dynamicDefinitions = false`:**
- Descriptions come from VdcDb entries keyed by the device's GTIN (`oemModelGuid`)
- If GTIN is not in VdcDb → no descriptions at all → no Activities tab, no states, no events in UI
- If GTIN is in VdcDb → VdcDb description entries shown (static, not from VDC)

**When `dynamicDefinitions = true`:**
- dSS queries VDC live for all description properties
- VdcDb description entries are **ignored** for the description names/options
- The GTIN is still used for `hasActions` determination and state slot allocation (see §7.2)

**Push notification behavior** (independent of `dynamicDefinitions`):
- `raiseEvent(createDeviceStateEvent())` fires **unconditionally** on any `deviceStates` push — automation rules with `DeviceStateEvent` triggers work regardless
- `raiseEvent(createDeviceEventEvent())` fires **unconditionally** on any `deviceEventDescriptions` push — event-triggered automation works without VdcDb
- `setStateValue()` only succeeds if the state name was registered from VdcDb → state-**condition** evaluation requires VdcDb state name match

### 7.2 GTIN (oemModelGuid) — Behavior at Scan Time

The GTIN declared in `oemModelGuid` (format: `gs1:(01)GTIN13`) is looked up in the VdcDb SQLite database at device scan time. This happens in `busscanner.cpp:initializeDeviceFromSpec()`.

```
oemModelGuid = "gs1:(01)2345678901234"
  strip "gs1:(01)" prefix → eanString = "2345678901234"
  
  db->hasActionInterface(eanString)
    → SELECT name FROM device WHERE gtin = ?
    → found: hasActions = true → "Activities" tab visible in configurator
    → not found: hasActions = false → no Activities tab
  
  db->getStatesLegacy(eanString)
    → SELECT name, value FROM callGetStatesBase WHERE gtin = ?
    → populates m_states[name] slots for state-condition automation
    → VdSD state push names MUST match these names for conditions to trigger
```

**Practical consequences:**

| GTIN in VdcDb? | `dynamicDefinitions` | Result |
|---|---|---|
| Yes (any GTIN) | false | `hasActions=true`; descriptions from VdcDb; state conditions work if names match |
| Yes + matching names | true | `hasActions=true`; descriptions from VDC live; state conditions work (VdcDb seeds `m_states`); event-triggered automations work |
| No GTIN | false | `hasActions=false`; no Activities tab; no state conditions; events still trigger automations |
| No GTIN | true | `hasActions=false`; no Activities tab; descriptions from VDC shown in configurator; event-triggered automations work; no state conditions |

**Special GTINs in the digitalSTROM VdcDb:**

- `2345678901234` — General-purpose GTIN. In VdcDb: `hasActions=true`. States from VdcDb with this GTIN may be minimal; use with `dynamicDefinitions=true` so VDC provides the actual names.
- `7640156794076` (Generic Coffeemaker), `7640156793963` (Generic Washing Machine), `7640156794045` (Generic Dryer/Tumble Dryer), `7640156793970` (Generic Dishwasher), `7640156794052` (Generic Oven) — Template GTINs with predefined state/event/action/property entries in VdcDb. With `dynamicDefinitions=true`, the VDC's own descriptions override the VdcDb entries in the UI.

**State name matching requirement:**
When using a template GTIN, the state names pushed via `deviceStates` must match the VdcDb state names for **state-condition-based** automation to work. With `dynamicDefinitions=true`, names shown in the UI come from the VDC, but the `m_states` slots are seeded from the VdcDb names — mismatch means `setStateValue()` is a no-op for conditions.

### 7.3 outputSettings Groups vs. primaryGroup

Three group-related fields coexist with different semantics:

| Field | Level | What it means | Backend-VDC path | Classic-VDC path |
|---|---|---|---|---|
| `primaryGroup` | vdSD (device) | Application type/class of the device | `addToGroup(primaryGroup)` + `setActiveGroup(primaryGroup)` | vdSM → dS485 bus announcement |
| `outputSettings.activeGroup` | Output | GroupID the output is currently active in | **Not read** — `primaryGroup` used | vdSM → `DeviceSpec.activeGroup` → `m_ActiveGroup` |
| `outputSettings.groups` | Output | Set of all GroupIDs this output belongs to | **Not read** — only `addToGroup(primaryGroup)` | vdSM → dS485 groups bitmask → `addToGroup()` per entry |

For standard non-joker devices, all three values are the same integer (e.g., lighting device: `primaryGroup=1`, `activeGroup=1`, `groups={1}`). They diverge for joker devices that are reassigned to a specific group.

---

## 8. digitalSTROM Mapping Compatibility

### 8.1 2-Way Buttons

2-way rockers (common in EnOcean devices) must follow this convention:

- Button index 0 = **down** button: `buttonInputSettings[0].mode = TWO_WAY_DOWN_PAIRED_2 (6)`
- Button index 1 = **up** button: `buttonInputSettings[1].mode = TWO_WAY_UP_PAIRED_1 (9)`

### 8.2 Multiple vdSDs in One Physical Device

If one physical device contains multiple independent functional units:

- Each unit is a separate vdSD with its own dSUID.
- The first 16 bytes of the dSUID are shared across all units in the same hardware.
- The 17th byte (enumeration byte) distinguishes them starting at 0.
- Enumeration 0, 1, 2, … is standard; other schemes are valid if unambiguous.
- Only use shared-prefix dSUIDs when the number and enumeration of units is **fixed and permanent** for the hardware. Interchangeable modules that can be used independently must have fully independent dSUIDs.

### 8.3 Scene Value Compatibility

- Scene `dontCare=true` at the scene level: calling the scene leaves all outputs unchanged.
- Scene `dontCare=true` at the channel level: that channel is left unchanged when the scene is called; other channels may still be applied.
- `ignoreLocalPriority=true` scenes override local priority (use for panic, fire, alarm scenes).
- `automatic=true` channel flag activates the device's built-in automatic control (e.g., automatic temperature control).

### 8.4 Channel Naming Conventions

- Index 0 is always the primary output channel (brightness for lights, position for blinds, etc.).
- `channelType=0` (default) is used when the output type is unspecified (e.g., a generic relay switch).
- Device-specific channels use IDs 192–239.
