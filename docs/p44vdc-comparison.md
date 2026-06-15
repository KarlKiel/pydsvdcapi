# p44vdc vs pydsvdcapi Message Structure Analysis

## Methodology

Sources consulted:

- **p44vdc** (reference C++ implementation):
  - `vdc_common/outputbehaviour.cpp` and `.hpp` — output property handling
  - `vdc_common/channelbehaviour.cpp` and `.hpp` — channel property handling
  - `behaviours/shadowbehaviour.cpp` and `.hpp` — shadow/shade specialisation
  - `vdc_common/device.cpp` — device-level property tree
  - `deviceclasses/custom/customdevice.cpp` — TCP/IP custom device
  - All fetched from `https://raw.githubusercontent.com/plan44/p44vdc/master/`

- **pydsvdcapi** (Python implementation):
  - `src/pydsvdcapi/output.py` — Output class
  - `src/pydsvdcapi/output_channel.py` — OutputChannel class
  - `src/pydsvdcapi/vdsd.py` — Vdsd class, `get_properties()`, `announce()`
  - `src/pydsvdcapi/vdc_host.py` — `_handle_set_output_channel_value()` and related handlers

All comparisons are based on the property-tree structure as seen in `VDSM_REQUEST_GET_PROPERTY` responses and `VDC_SEND_PUSH_NOTIFICATION` messages.

Last updated: 2026-06-15 (branch `Prepare-for-release-0.8.6`)

---

## 1. `outputDescription`

### p44vdc

Fields returned (from `outputDescriptionProperties` static array in `outputbehaviour.cpp`):

| Field name | Type | Notes |
|---|---|---|
| `function` | `uint64` | OutputFunction enum value |
| `outputUsage` | `uint64` | OutputUsage enum value |
| `variableRamp` | `bool` | |
| `maxPower` | `double` | |
| `x-p44-recommendedTransitionTime` | `double` | seconds; p44-specific extension |

**Not present in p44vdc `outputDescription`**: `name`, `defaultGroup`, `activeCoolingMode`.

### pydsvdcapi (current)

From `output.py` `get_description_properties()`:

| Field name | Type | Notes |
|---|---|---|
| `function` | int | OutputFunction enum value |
| `outputUsage` | int | OutputUsage enum value |
| `variableRamp` | bool | |
| `maxPower` | double | always present; `-1.0` when no value given |
| `name` | str | **optional** — only when explicitly set |
| `defaultGroup` | int | **optional** — only when explicitly set |
| `activeCoolingMode` | bool | **optional** — only when explicitly set |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `name` | NOT in `outputDescription` | Optional — only when set | INFO — no longer always injected; harmless when present |
| `defaultGroup` | NOT in `outputDescription` | Optional — only when set | INFO — no longer always injected; harmless when present |
| `activeCoolingMode` | NOT in base p44vdc | Optional — only when set | INFO — extension field, harmless |
| `maxPower` | Present; omitted when no value | Always present (`-1.0` for "no value") | INFO — `-1.0` sentinel matches dSS expectation for "unknown" |
| `x-p44-recommendedTransitionTime` | Present (p44 extension) | NOT present | INFO — p44-specific extension, not required |

---

## 2. `outputSettings`

### p44vdc

Fields returned (from `outputSettingsProperties` in `outputbehaviour.cpp`):

| Field name | Type | Notes |
|---|---|---|
| `mode` | `uint64` | OutputMode enum |
| `pushChanges` | `bool` | |
| `x-p44-bridgePushInterval` | `double` | p44-specific bridge push interval |
| `groups` | `bool`-container | Index-based boolean array; each index = group ID, value = membership |

**Critical detail on `groups`**: In p44vdc the property system encodes `groups` as a `propflag_container` of `apivalue_bool` properties. In protobuf this means a `PropertyElement` named `"groups"` that contains child `PropertyElement`s, each child having its name = the group number (as string, e.g. `"1"`, `"2"`, `"3"`) and its value as a `v_bool`. Groups **not** in the membership have value `false`; groups **in** the membership have value `true`. The container emits ALL indices in the range 0–63 (the full bitmask width), including `false` entries.

**Not present in p44vdc base `outputSettings`**: `activeGroup`, `onThreshold`. Light/climate/shadow-specific fields live in sub-behaviours (`LightBehaviour`, `HeatingBehaviour`, `ShadowBehaviour`).

**Shadow-specific fields** (from `ShadowBehaviour::accessField()`):

| Field | Type |
|---|---|
| `openTime` | `double` (seconds) |
| `closeTime` | `double` (seconds) |
| `angleOpenTime` | `double` (seconds) |
| `angleCloseTime` | `double` (seconds) |
| `stopDelayTime` | `double` (seconds) |

### pydsvdcapi (current)

From `output.py` `get_settings_properties()`:

| Field name | Type | Notes |
|---|---|---|
| `mode` | int | OutputMode enum |
| `pushChanges` | bool | |
| `activeGroup` | int | **optional** — only when explicitly set |
| `groups` | dict `{str: True}` | Only `true` entries emitted; e.g. `{"2": True}` |
| `onThreshold` | double | only for `function == ON_OFF`; default `50.0` |
| `minBrightness` | double | only when set **and** `primaryGroup == 1` (light) |
| `dimTimeUp/Down` + Alt1/Alt2 | int | only when set and `primaryGroup == 1` |
| `heatingSystemCapability` | int | only when set **and** `primaryGroup == 3` (climate) |
| `heatingSystemType` | int | only when set and `primaryGroup == 3` |
| `openTime` | double | only when set **and** `primaryGroup == 2` (shadow) |
| `closeTime` | double | only when set and `primaryGroup == 2` |
| `angleOpenTime` | double | only when set and `primaryGroup == 2` |
| `angleCloseTime` | double | only when set and `primaryGroup == 2` |
| `stopDelayTime` | double | only when set and `primaryGroup == 2` |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `groups` encoding | Boolean container — ALL indices 0–63 emitted (true/false) | Only `true` entries emitted | INFO — vdSM treats missing entries as `false`; functionally equivalent for reading |
| `activeGroup` | NOT in base `outputSettings` | Optional — only when set | INFO — extra field; not known to cause errors |
| `x-p44-bridgePushInterval` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `onThreshold` | Not in base outputbehaviour | Only for ON_OFF function | INFO — correct gating |
| Shadow timing fields | In ShadowBehaviour | Present when set, gated on `primaryGroup == 2` | **FIXED** — now implemented |

---

## 3. `channelDescriptions` — per channel

### p44vdc

From `channelDescProperties` in `channelbehaviour.cpp`:

| Field name | Type | Notes |
|---|---|---|
| `name` | `string` | Channel name, e.g. `"brightness"`, `"shadePositionOutside"` |
| `channelIndex` | `uint64` | **Deprecated in API v3+** — returns `mChannelIndex`; NOT returned for API version ≥ 3 |
| `dsIndex` | `uint64` | Returns `mChannelIndex`; always returned |
| `channelType` | `uint64` | DsChannelType enum value |
| `siunit` | `string` | SI unit name, e.g. `"percent"`, `"kelvin"`, `"degree"` |
| `symbol` | `string` | Unit symbol string, e.g. `"%"`, `"K"`, `"°"` |
| `min` | `double` | |
| `max` | `double` | |
| `resolution` | `double` | |
| `values` | object/container | Enum values list — only present when `!REDUCED_FOOTPRINT` |

**Key detail — element naming (keying)**: In p44vdc the channel container key is determined by `ChannelBehaviour::getApiId(aApiVersion)` (`channelbehaviour.cpp`), called from `Device::getDescriptorByIndex` for all three channel containers:

```cpp
string ChannelBehaviour::getApiId(int aApiVersion)
{
  if (aApiVersion>=3 && !mChannelId.empty()) {
    return mChannelId;   // channel name string, e.g. "brightness", "shadePositionOutside"
  }
  else {
    return string_format("%d", getChannelType());  // decimal channel TYPE (not dsIndex)
  }
}
```

- **API v3+** (current vdSM): key = channel **name string** (e.g. `"brightness"`, `"shadePositionOutside"`)
- **API v2 and earlier**: key = decimal string of the **channel type enum** (e.g. `"1"` for `channeltype_brightness`) — **not** the dsIndex

The `dsIndex` value (`mChannelIndex`) is **never** used as the container element key in any path. It appears only as a named field *inside* the channel's description object. This applies identically to `channelDescriptions`, `channelSettings`, and `channelStates`, for **all device classes** — verified:

- `LightBehaviour`, `ShadowBehaviour`: no override
- `ClimateControlBehaviour`: overrides only behaviour-level descriptors (`climatecontrol_key`), not channel container keys
- `AudioBehaviour`/`AudioScene`: overrides only scene-level properties (`audioscene_key`), not channel keys
- `CustomDevice`: no override of any channel key logic; inherits unchanged from `Device`

**`VDC_SEND_ANNOUNCE_DEVICE`**: carries no property data at all — only `vdc_dSUID`. The vdSM then issues `getProperty` requests after acknowledgment, which go through the standard path above.

**Incoming `setProperty`** (`Device::getDescriptorByName`): matches channel elements by the same `getApiId()` output — channel name string (API v3+), channel type decimal (API v2), or the literal `"0"` as a backward-compat alias for the first channel. `dsIndex` values are **not** a valid key for incoming property writes.

**Shade channel specs (from `shadowbehaviour.hpp`)**:

| Channel | `channelType` | name | min | max | resolution | siunit |
|---|---|---|---|---|---|---|
| ShadowPositionChannel | `channeltype_shade_position_outside` | `"shadePositionOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` |
| ShadowAngleChannel | `channeltype_shade_angle_outside` | `"shadeOpeningAngleOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` |

**dsIndex assignments for shadow channels**:
- Position channel: dsIndex = 0 (added first)
- Angle channel: dsIndex = 1 (added second)

### pydsvdcapi (current)

From `output_channel.py` `get_description_properties()`:

| Field name | Type | Notes |
|---|---|---|
| `name` | str | |
| `channelType` | int | |
| `dsIndex` | int | |
| `siunit` | str | **FIXED** — now always present from `ChannelSpec` |
| `symbol` | str | **FIXED** — now always present from `ChannelSpec` |
| `min` | float | |
| `max` | float | |
| `resolution` | float | |
| `values` | dict `{str: str}` | **NEW** — present for enum channels (e.g. FCU operation mode, power state) |

**Key detail — element naming (keying)**: pydsvdcapi keys channel containers by **channel name string** (e.g. `"shadePositionOutside"`), matching p44vdc's API v3+ behaviour. A backward-compat `_ChannelCompatDict` additionally resolves numeric keys (channel type decimal strings and `"0"` as default-channel alias) at `getProperty` time, covering the API v2 and legacy cases.

**Shade channel specs** from `CHANNEL_SPECS` in `output_channel.py`:

| Channel | `channelType` | name | min | max | resolution | siunit | symbol |
|---|---|---|---|---|---|---|---|
| SHADE_POSITION_OUTSIDE | enum value | `"shadePositionOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` | `"%"` |
| SHADE_POSITION_INDOOR | enum value | `"shadePositionIndoor"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` | `"%"` |
| SHADE_OPENING_ANGLE_OUTSIDE | enum value | `"shadeOpeningAngleOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` | `"%"` |
| SHADE_OPENING_ANGLE_INDOOR | enum value | `"shadeOpeningAngleIndoor"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` | `"%"` |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| Element key (container child name) | **Channel name string** for API v3+ (e.g. `"shadePositionOutside"`); channel type decimal for API v2 | **Channel name string** always; numeric compat layer covers type-decimal and `"0"` alias | None — identical for API v3+; compat layer covers older paths |
| `siunit` | Present | **FIXED** — now always present | ~~CRITICAL~~ → resolved |
| `symbol` | Present | **FIXED** — now always present | ~~CRITICAL~~ → resolved |
| `values` | Present (enum list, non-reduced builds) | Present for enum channels | INFO — now implemented for discrete-value channels |
| `channelIndex` | Present (deprecated, API < 3) | NOT present | INFO — deprecated field |
| `resolution` (shade) | 100/65536 ≈ 0.001526 | **FIXED** — 100/65536 ≈ 0.001526 | ~~WARN~~ → resolved |

---

## 4. `channelSettings` per channel

### p44vdc

From `channelbehaviour.cpp`: Settings properties are **empty** (`numSettingsProperties = 0`). No fields defined.

### pydsvdcapi (current)

Returns an **empty dict** `{}` for all channels.

### Differences

None — both return empty settings.

---

## 5. `channelStates` per channel

### p44vdc

From `channelStateProperties` in `channelbehaviour.cpp`:

| Field name | Type | Notes |
|---|---|---|
| `value` | `double` | Current channel value; `null` when unknown |
| `age` | `double` | Seconds since last hardware sync; `null` when `mChannelLastSync==Never` or volatile |
| `x-p44-transitional` | `double` | Intermediate value during transition (p44 extension) |
| `x-p44-transitiontimeleft` | `double` | Remaining transition time (p44 extension) |
| `x-p44-progress` | `double` | Transition completion % (p44 extension) |

**No `error` field** in channel states — error lives in `outputState` at the output level.

### pydsvdcapi (current)

From `output_channel.py` `get_state_properties()`:

| Field name | Type | Notes |
|---|---|---|
| `value` | float or None | `None` when unknown → serialised as null |
| `age` | float or None | `time.monotonic() - _last_update` when known; `None` when never set |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `x-p44-transitional` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `x-p44-transitiontimeleft` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `x-p44-progress` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `age` null semantics | `null` when never confirmed | `None` (null) when `_last_update is None` | INFO — same semantics |

---

## 6. Push notifications (`VDC_SEND_PUSH_NOTIFICATION`)

### p44vdc

p44vdc sends push notifications via `pushNotification` → `accessProperty` with the same API version as regular `getProperty` responses. The pushed property tree for a channel state update contains:

```
changedproperties:
  PropertyElement(name="channelStates"):
    PropertyElement(name="<channelId>"):   ← channel name string for API v3+ (e.g. "shadePositionOutside")
      PropertyElement(name="value", value=<double>)
      PropertyElement(name="age", value=<double>)
```

The element key is produced by the same `Device::getDescriptorByIndex` → `getApiId(aApiVersion)` path as `getProperty`. For API v3+ this is the **channel name string**.

### pydsvdcapi (current)

From `output.py` `_push_channel_state()`:

```python
push_tree = {
    "channelStates": {
        channel.name: state_dict,   ← channel name string, e.g. "shadePositionOutside"
    }
}
```

The element key within `channelStates` is the **channel name string**.

### Differences

| Aspect | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `channelStates` child element key in push | Channel name string for API v3+ (e.g. `"shadePositionOutside"`) | Channel name string (e.g. `"shadePositionOutside"`) | None — identical for API v3+ |
| Properties pushed | `value`, `age` | `value`, `age` | None |

**Note**: Earlier analysis incorrectly stated p44vdc uses `dsIndex` as the push key. The actual p44vdc source (`pushNotification` → `accessProperty` → `Device::getDescriptorByIndex` → `getApiId()`) returns the channel name string for API v3+, identical to pydsvdcapi.

---

## 7. `setOutputChannelValue` handling

### p44vdc

In `customdevice.cpp`, channel resolution for `setOutputChannelValue` uses three lookup methods in order:

1. `"index"` — integer field → `getChannelByIndex()`
2. `"type"` — DsChannelType integer → `getChannelByType()`
3. `"id"` — string field → `getChannelById()`

`getChannelById()` matches on the channel's **name string** (the `channelId` in the notification).

### pydsvdcapi (current)

From `vdc_host.py` `_handle_set_output_channel_value()`:

```python
# Priority 1: channelId (name string)
if notif.channelId:
    for ch in output.channels.values():
        if ch.name == notif.channelId:
            channel_obj = ch
            break

# Priority 2: channel (integer type)
if channel_obj is None and notif.HasField("channel"):
    ct = OutputChannelType(int(notif.channel))
    channel_obj = output.get_channel_by_type(ct)
```

### Differences

| Aspect | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| channelId lookup priority | index → type → id (name) | name (channelId) → type | INFO — functionally equivalent for API v3+; integer-index path is deprecated |
| Index-based fallback | Supported | NOT supported | INFO — deprecated path; not used by modern vdSM |
| Name matching | `getChannelId()` = channel name | `ch.name == notif.channelId` | None — same result |

---

## 8. `outputState`

### p44vdc

From `outputStateProperties` in `outputbehaviour.cpp`:

| Field | Type | Notes |
|---|---|---|
| `localPriority` | `bool` | |
| `transitionTime` | `double` | seconds; current transition time |

**No `error` field in outputState in base OutputBehaviour.**

### pydsvdcapi (current)

From `output.py` `get_state_properties()`:

| Field | Type | Notes |
|---|---|---|
| `localPriority` | bool | |
| `transitionTime` | double | **FIXED** — now present |
| `error` | int | OutputError enum value; extra field not in p44vdc base |

**Note**: `movingState` was present in earlier pydsvdcapi versions but has been **removed** — it was never part of the VDC API spec and not emitted by p44vdc.

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `transitionTime` | Present | **FIXED** — now present | ~~WARN~~ → resolved |
| `error` | NOT in base outputState | Always present | INFO — extra field; likely harmless |
| `movingState` | NOT in VDC API | **REMOVED** | resolved — no longer emitted |

---

## 9. `modelFeatures` encoding

### p44vdc

`modelFeatures` is encoded as a **boolean container array** (`apivalue_object + propflag_container`). Each enabled feature is a child element named by the feature name string with a boolean `true` value. p44vdc iterates features in canonical `ModelFeatureId` enum order (from `modelconst.h`).

### pydsvdcapi (current)

From `vdsd.py` `get_properties()`:

```python
_MODEL_FEATURE_ORDER = {
    "dontcare": 0, "blink": 1, "transt": 4, "outmode": 5, ...
}
props["modelFeatures"] = {
    f: True
    for f in sorted(self._model_features, key=lambda x: _MODEL_FEATURE_ORDER.get(x, 999))
}
```

An object (dict) where each key is the feature name string and each value is `True`. Absent features are not emitted. Order follows the canonical `ModelFeatureId` enum index from `modelconst.h`.

### Differences

| Aspect | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| Absent features | Explicitly emitted as `false` (full container) | Not emitted | INFO — absent = false; functionally equivalent |
| Feature ordering | Canonical enum index order | **FIXED** — now canonical enum index order | ~~INFO~~ → resolved |

---

## 10. `groups` in `outputSettings` — encoding detail

p44vdc emits `groups` as a container of 64 boolean values (indices 0–63), with `true` for member groups and `false` for non-member groups. pydsvdcapi emits only the `true` entries.

For **write-back** via `setProperty`, the vdSM sends group membership changes as individual `{index: bool}` entries — pydsvdcapi handles this correctly in `apply_settings()`. For **read** via `getProperty`, pydsvdcapi sends only true entries; the vdSM correctly infers non-listed groups as non-members.

Emitting all 64 entries was tested and found to cause excessive individual `groupMembership` queries from the vdSM (64 per device), significantly slowing announcement. The true-only format was deliberately retained.

---

## 11. Device-level properties (Vdsd.get_properties)

### p44vdc

Key fields sent in `VDC_SEND_ANNOUNCE_DEVICE` / `getProperty` response for a device:

| Field | Notes |
|---|---|
| `dSUID` | |
| `primaryGroup` | integer |
| `zoneID` | integer |
| `name` | |
| `model` | |
| `hardwareGuid` | |
| `vendorName` | |
| `modelFeatures` | bool container — canonical order |
| `outputDescription` | single object |
| `outputSettings` | single object |
| `outputState` | single object |
| `channelDescriptions` | container keyed by channel name string (API v3+) or channel type decimal (API v2) |
| `channelSettings` | container keyed by channel name string (API v3+) or channel type decimal (API v2) |
| `channelStates` | container keyed by channel name string (API v3+) or channel type decimal (API v2) |

### pydsvdcapi (current)

Same top-level fields. Channel containers are keyed by channel name (with numeric-key backward-compat resolution via `_ChannelCompatDict`).

---

## Summary: Current Status

### Resolved (previously CRITICAL/WARN)

1. ~~**`siunit` and `symbol` missing from `channelDescriptions`**~~ — **FIXED**: now always present from `ChannelSpec`.

2. ~~**`transitionTime` missing from `outputState`**~~ — **FIXED**: now present.

3. ~~**Shadow timing fields missing from `outputSettings`**~~ — **FIXED**: `openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` now implemented, gated on `primaryGroup == 2`.

4. ~~**`name` and `defaultGroup` always in `outputDescription`**~~ — **FIXED**: now optional, only when explicitly set.

5. ~~**`activeGroup` always in `outputSettings`**~~ — **FIXED**: now optional, only when explicitly set.

6. ~~**`modelFeatures` order was alphabetical**~~ — **FIXED**: now sorted by canonical `ModelFeatureId` enum index.

7. ~~**`movingState` in `outputState`**~~ — **REMOVED**: was non-standard, never in VDC API spec.

### Remaining Differences

| # | Area | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|---|
| A | `groups` encoding | All 64 entries (true/false) | True entries only | INFO — functionally equivalent; full-64 deliberately avoided (performance) |
| B | `resolution` for shade channels | 100/65536 ≈ 0.001526 | 100/65536 ≈ 0.001526 | ~~WARN~~ → resolved |
| C | Channel container key | Channel name string (API v3+); channel type decimal (API v2) | Channel name string; compat layer handles type-decimal and `"0"` alias | None — identical for API v3+ |
| D | `values` in channelDescriptions | All channels | Enum channels only | INFO — correctly scoped |
| E | `error` in `outputState` | NOT present | Always present | INFO — extra field, harmless |
| F | p44-specific extension fields | Present | NOT present | INFO — not required |
| G | `channelIndex` (deprecated) | Present (API < 3) | NOT present | INFO — correct for API v3+ |

### No open items

All previously identified CRITICAL and WARN differences have been resolved. The remaining differences (A, C–G) are all INFO-level and either deliberate design choices or non-standard extras that are harmless in practice.
