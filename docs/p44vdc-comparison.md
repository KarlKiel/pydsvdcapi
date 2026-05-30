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

### pydsvdcapi

From `output.py` `get_description_properties()` (line 1492–1508):

| Field name | Type | Notes |
|---|---|---|
| `function` | int | OutputFunction enum value |
| `outputUsage` | int | OutputUsage enum value |
| `name` | str | always included |
| `defaultGroup` | int | always included |
| `variableRamp` | bool | |
| `maxPower` | double | only when not None |
| `activeCoolingMode` | bool | only when not None |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `name` | NOT present in `outputDescription` | ALWAYS present | WARN — dSS may ignore; no known error impact for output description |
| `defaultGroup` | NOT present in `outputDescription` | ALWAYS present | WARN — dSS may ignore; no known error impact |
| `activeCoolingMode` | NOT present in p44vdc source | Present when set | INFO — p44vdc extension pydsvdcapi borrowed, not in p44vdc core |
| `x-p44-recommendedTransitionTime` | Present (p44 extension) | NOT present | INFO — p44-specific extension, not required by spec |

**Assessment**: The extra fields pydsvdcapi sends (`name`, `defaultGroup`) are not in the p44vdc model but appear to be harmless — the vdSM ignores unknown fields in `outputDescription`. These fields are not the cause of grey-device errors.

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

**Not present in p44vdc `outputSettings`**: `activeGroup`, `onThreshold`, `minBrightness`, `dimTimeUp`, `dimTimeDown`, `dimTimeUp/DownAlt1/2`, `heatingSystemCapability`, `heatingSystemType`.

### pydsvdcapi

From `output.py` `get_settings_properties()` (line 1510–1548):

| Field name | Type | Notes |
|---|---|---|
| `mode` | int | OutputMode enum |
| `activeGroup` | int | always present |
| `pushChanges` | bool | |
| `groups` | dict `{str: True}` | Only `true` entries; e.g. `{"1": True, "3": True}` |
| `onThreshold` | double | only when not None |
| `minBrightness` | double | only when not None |
| `dimTimeUp/Down` + Alt1/Alt2 | int | only when not None |
| `heatingSystemCapability` | int | only when not None |
| `heatingSystemType` | int | only when not None |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `groups` encoding | Boolean container — ALL indices 0–63 emitted (true/false) | Dict with only `true` entries | **WARN** — p44vdc emits both true and false entries; pydsvdcapi only emits true entries. The vdSM reads this correctly since missing = false, but write-back via `setProperty` may behave differently. Read direction: likely OK. |
| `activeGroup` | NOT present in `outputSettings` | Always present | WARN — extra field; not known to cause errors |
| `x-p44-bridgePushInterval` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| Dimming/climate fields | NOT in base outputbehaviour (may be in sub-behaviour) | Present when set | INFO — sub-behaviour fields; may be in LightBehaviour for p44vdc |

**Note on shadow devices**: For shadow/shade devices in p44vdc, `outputSettings` is handled by `ShadowBehaviour` and **adds** extra fields:

| Field | p44vdc (ShadowBehaviour) | pydsvdcapi | Severity |
|---|---|---|---|
| `openTime` | `double` (seconds) — in `outputSettings` | NOT present | **WARN** — shadow-specific motor timing; if dSS sends this, pydsvdcapi ignores it |
| `closeTime` | `double` (seconds) — in `outputSettings` | NOT present | WARN |
| `angleOpenTime` | `double` (seconds) — in `outputSettings` | NOT present | WARN |
| `angleCloseTime` | `double` (seconds) — in `outputSettings` | NOT present | WARN |
| `stopDelayTime` | `double` (seconds) — in `outputSettings` | NOT present | WARN |

These five shadow-specific settings fields are added by `ShadowBehaviour::accessField()` under the `settings_key_offset` domain. pydsvdcapi does not implement them. They are not a cause of errors during device announcement but will be missing when dSS reads back settings for grey devices.

---

## 3. `channelDescriptions` — per channel

### p44vdc

From `channelDescProperties` in `channelbehaviour.cpp`:

| Field name | Type | Notes |
|---|---|---|
| `name` | `string` | Channel name, e.g. `"brightness"`, `"shadePositionOutside"` |
| `channelIndex` | `uint64` | **Deprecated in API v3+** — returns `mChannelIndex`; NOT returned for API version ≥ 3 |
| `dsIndex` | `uint64` | Returns `mChannelIndex` (same value as channelIndex); always returned |
| `channelType` | `uint64` | DsChannelType enum value |
| `siunit` | `string` | SI unit name, e.g. `"percent"`, `"kelvin"`, `"degree"` |
| `symbol` | `string` | Unit symbol string, e.g. `"%"`, `"K"`, `"°"` |
| `min` | `double` | |
| `max` | `double` | |
| `resolution` | `double` | |
| `values` | object/container | Enum values list — only present when `!REDUCED_FOOTPRINT` |

**Key detail — element naming (keying)**: In p44vdc the channel description sub-tree is a container keyed by the **channel's `dsIndex` integer** (as string), not by channel name. Each child `PropertyElement` is named with the channel's numeric index (e.g. `"0"`, `"1"`), and within that element the `name` field carries the channel name string.

**Shade channel specs (from `shadowbehaviour.hpp`)**:

| Channel | `channelType` | name | min | max | resolution | siunit |
|---|---|---|---|---|---|---|
| ShadowPositionChannel | `channeltype_shade_position_outside` | `"shadePositionOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` |
| ShadowAngleChannel | `channeltype_shade_angle_outside` | `"shadeOpeningAngleOutside"` | 0 | 100 | 100/65536 ≈ 0.001526 | `"percent"` |

**dsIndex assignments for shadow channels**:
- Position channel: dsIndex = 0 (added first)
- Angle channel: dsIndex = 1 (added second)

### pydsvdcapi

From `output_channel.py` `get_description_properties()` (line 622–636):

| Field name | Type | Notes |
|---|---|---|
| `name` | str | |
| `channelType` | int | |
| `dsIndex` | int | |
| `min` | float | |
| `max` | float | |
| `resolution` | float | |

**Key detail — element naming (keying)**: pydsvdcapi keys channel descriptions by **channel name** (e.g. `"shadePositionOutside"`), not by integer dsIndex. This is documented explicitly in `output_channel.py` docstring and `output.py` (lines 36–39).

**Shade channel specs** from `CHANNEL_SPECS` in `output_channel.py`:

| Channel | `channelType` | name | min | max | resolution |
|---|---|---|---|---|---|
| SHADE_POSITION_OUTSIDE | enum value | `"shadePositionOutside"` | 0 | 100 | 100/255 ≈ 0.3922 |
| SHADE_POSITION_INDOOR | enum value | `"shadePositionIndoor"` | 0 | 100 | 100/255 ≈ 0.3922 |
| SHADE_OPENING_ANGLE_OUTSIDE | enum value | `"shadeOpeningAngleOutside"` | 0 | 100 | 100/255 ≈ 0.3922 |
| SHADE_OPENING_ANGLE_INDOOR | enum value | `"shadeOpeningAngleIndoor"` | 0 | 100 | 100/255 ≈ 0.3922 |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| Element key (container child name) | **Integer dsIndex as string** (e.g. `"0"`, `"1"`) | **Channel name string** (e.g. `"shadePositionOutside"`) | **CRITICAL** — This is the most fundamental structural difference; see discussion below |
| `siunit` | Present — e.g. `"percent"` for shade channels | **NOT present** | **CRITICAL** — dSS firmware may rely on `siunit` to render units correctly |
| `symbol` | Present — e.g. `"%"` for shade channels | **NOT present** | WARN — unit symbol for display |
| `channelIndex` | Present (deprecated, API < 3) | NOT present | INFO — deprecated field |
| `resolution` | 100/65536 ≈ 0.001526 for shade channels | 100/255 ≈ 0.392 for shade channels | **WARN** — p44vdc uses higher-resolution 16-bit scale; pydsvdcapi uses 8-bit scale |
| `values` | Present (enum value list, non-reduced builds) | NOT present | INFO — rarely needed |

**CRITICAL discussion on element key format**:

The comment in `pydsvdcapi/output.py` lines 36–39 says that using channel name as key was intentional to fix a `deviceOutputIndex:255` error. However, p44vdc itself uses the integer dsIndex as the element key. The vdSM uses `getChannelById()` in p44vdc to resolve `channelId` strings — this works because the channel *name* field **inside** the element (not the element key) is used for lookup, while the **element key** is the numeric index.

The vdSM therefore sees `channelDescriptions` keyed by integers (p44vdc) vs keyed by names (pydsvdcapi). This discrepancy likely does not cause a direct crash, but:
- For grey/shade devices specifically, the dSS firmware does position/angle lookups by channel type or channel name from within the descriptor element — which pydsvdcapi correctly provides.
- However, if dSS iterates the container expecting integer keys and tries to use them as indices, it would fail silently or produce wrong results with pydsvdcapi's name keys.

---

## 4. `channelSettings` per channel

### p44vdc

From `channelbehaviour.cpp`: Settings properties are **empty** (`numSettingsProperties = 0`). No fields defined.

### pydsvdcapi

From `output_channel.py` `get_settings_properties()` (line 638–645):

Returns an **empty dict** `{}` for all channels.

### Differences

None — both return empty settings. No difference.

---

## 5. `channelStates` per channel

### p44vdc

From `channelStateProperties` in `channelbehaviour.cpp`:

| Field name | Type | Notes |
|---|---|---|
| `value` | `double` | Current channel value; `null` when unknown |
| `age` | `double` | Seconds since last hardware sync as double; `null` when `mChannelLastSync==Never` or value is volatile |
| `x-p44-transitional` | `double` | Intermediate value during transition (p44 extension) |
| `x-p44-transitiontimeleft` | `double` | Remaining transition time (p44 extension) |
| `x-p44-progress` | `double` | Transition completion % (p44 extension) |

**No `error` field** in channel states. Error lives in `outputState` at the output level, not per channel.

**`age` semantics**: `age` is `null` (not `0`) when the value was never confirmed, or when `mChannelLastSync` is `Never`. When a value has been confirmed, `age` is `(MainLoop::now() - mChannelLastSync) / Second` as a double.

### pydsvdcapi

From `output_channel.py` `get_state_properties()` (line 647–657):

| Field name | Type | Notes |
|---|---|---|
| `value` | float or None | `None` when unknown → serialised as null |
| `age` | float or None | `time.monotonic() - _last_update` when known; `None` when `_last_update is None` |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `x-p44-transitional` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `x-p44-transitiontimeleft` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `x-p44-progress` | Present (p44 extension) | NOT present | INFO — p44 extension only |
| `age` null semantics | `null` when never confirmed | `None` (null) when `_last_update is None` | INFO — same semantics, consistent |
| `error` | NOT in channelStates (only in outputState) | NOT in channelStates | None — both agree |

**Assessment**: Channel states match well between p44vdc and pydsvdcapi. The only differences are p44-specific extension fields that pydsvdcapi does not include. This area is unlikely to cause errors.

---

## 6. Push notifications (`VDC_SEND_PUSH_NOTIFICATION`)

### p44vdc

p44vdc sends push notifications via `pushOutputState()` / `reportOutputState()`. The pushed property tree for a channel state update contains:

```
changedproperties:
  PropertyElement(name="channelStates"):
    PropertyElement(name="<dsIndex>"):   ← integer string, e.g. "0"
      PropertyElement(name="value", value=<double>)
      PropertyElement(name="age", value=<double>)
```

The element key within `channelStates` is the **integer dsIndex** (as string, e.g. `"0"` for the position channel), consistent with how `getProperty` responses are structured.

### pydsvdcapi

From `output.py` `_push_channel_state()` (line 1408–1453):

```python
push_tree = {
    "channelStates": {
        channel.name: state_dict,   ← channel name string, e.g. "shadePositionOutside"
    }
}
```

The element key within `channelStates` is the **channel name string** (e.g. `"shadePositionOutside"`).

### Differences

| Aspect | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `channelStates` child element key in push | Integer dsIndex as string, e.g. `"0"` | Channel name string, e.g. `"shadePositionOutside"` | **CRITICAL** for grey devices — see discussion |
| Properties pushed | `value`, `age` | `value`, `age` | None |

**CRITICAL discussion on push notification key format for grey devices**:

This is the most likely root cause of errors on grey (shade) devices:

- The vdSM (dSS firmware) receives a `VDC_SEND_PUSH_NOTIFICATION` for `channelStates`.
- It tries to match the child element name against its registered channel lookup table.
- For yellow (dimmer/CT/RGB) devices: p44vdc uses `"0"` for brightness. dSS may look up channel index 0 and find the brightness channel. When pydsvdcapi sends `"brightness"`, dSS may also accept this because it falls back to name lookup — explaining why yellow devices work.
- For grey (shade) devices: p44vdc uses `"0"` for position, `"1"` for angle. If dSS does integer-index matching, pydsvdcapi's `"shadePositionOutside"` key will not match index `"0"`, causing the push to be silently ignored or logged as `deviceOutputIndex:255`.
- However, the pydsvdcapi comment in `output.py` line 39 states that switching *to* name-keying fixed the `deviceOutputIndex:255` errors. This suggests dSS for API v3+ does support name-keyed lookup. The discrepancy vs p44vdc may be in which API version the push notification uses.

**Conclusion**: The key format difference exists but may be intentional in pydsvdcapi. The `deviceOutputIndex:255` errors users see are more likely caused by item 3 (missing `siunit` in channelDescriptions) or item 7 (channelId matching in setOutputChannelValue) than by the push key format.

---

## 7. `setOutputChannelValue` handling

### p44vdc

In `customdevice.cpp`, channel resolution for `setOutputChannelValue` uses three lookup methods in order:

1. `"index"` — integer field → `getChannelByIndex()`
2. `"type"` — DsChannelType integer → `getChannelByType()`
3. `"id"` — string field → `getChannelById()`

`getChannelById()` matches on the channel's **name string** (the `channelId` in the notification).

In `outputbehaviour.cpp`, the `getChannelById()` implementation iterates all channels and returns the first one where `cb->getChannelId() == aId`. The `getChannelId()` of a channel returns its **name string** (e.g. `"shadePositionOutside"`).

The `VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE` protobuf message has a `channelId` field that carries the channel name string (API v3+) and a `channel` field that carries the integer type (API v1/v2).

### pydsvdcapi

From `vdc_host.py` `_handle_set_output_channel_value()` (line 1868–1938):

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
| channelId lookup priority | index → type → id (name) | name (channelId) → type | INFO — functionally equivalent for API v3+; index-based is not supported in pydsvdcapi |
| Index-based fallback | Supported (`"index"` field) | NOT supported | INFO — deprecated path; not used by modern vdSM |
| Name matching | `getChannelId()` = channel name string | `ch.name == notif.channelId` | None — same result |

**Assessment**: Channel lookup for `setOutputChannelValue` is functionally equivalent for API v3+ (which uses `channelId` = name string). The missing index-based lookup is a deprecated fallback and not the cause of grey device errors.

---

## 8. `outputState` (formerly `outputState` vs `outputState`)

### p44vdc

From `outputStateProperties` in `outputbehaviour.cpp`:

| Field | Type | Notes |
|---|---|---|
| `localPriority` | `bool` | |
| `transitionTime` | `double` | seconds; current transition time |

**No `error` field in outputState in base OutputBehaviour.**

### pydsvdcapi

From `output.py` `get_state_properties()` (line 1550–1558):

| Field | Type | Notes |
|---|---|---|
| `localPriority` | bool | |
| `error` | int | OutputError enum value |

### Differences

| Field | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| `transitionTime` | Present (double, seconds) | NOT present | WARN — dSS may read this to track active transitions |
| `error` | NOT in base outputState | Always present (int) | **WARN** — pydsvdcapi sends an extra `error` field; not expected by dSS; likely harmless but non-standard |

---

## 9. `modelFeatures` encoding

### p44vdc

`modelFeatures` is encoded in the property tree as a **boolean container array** (`apivalue_object + propflag_container`). Each enabled feature is a child element named by the feature name string with a boolean `true` value. p44vdc iterates over `numModelFeatures` known features in order.

### pydsvdcapi

From `vdsd.py` `get_properties()` (line 1556–1560):

```python
props["modelFeatures"] = {f: True for f in sorted(self._model_features)}
```

An object (dict) where each key is the feature name string and each value is `True`. Absent features are simply not included.

### Differences

| Aspect | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|
| Absent features | Explicitly emitted as `false` values (full container) | Not emitted at all | WARN — Functionally equivalent since absent = false, but dSS may iterate a fixed set |
| Feature ordering | Fixed canonical order by enum index | Alphabetical sort | INFO — irrelevant to semantics |

---

## 10. `groups` in `outputSettings` — encoding detail

This is a known subtlety. p44vdc emits `groups` as a container of 64 boolean values (indices 0–63), with `true` for member groups and `false` for non-member groups. pydsvdcapi emits only the `true` entries as a dict.

For **write-back** via `setProperty`, the vdSM sends group membership changes as individual `{index: bool}` entries. pydsvdcapi handles this correctly in `apply_settings()`. For **read** via `getProperty`, pydsvdcapi sends only true entries; this should be fine as the vdSM initialises group membership from the true entries.

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
| `modelFeatures` | bool container, see section 9 |
| `outputDescription` | single object |
| `outputSettings` | single object |
| `outputState` | single object |
| `channelDescriptions` | container keyed by integer dsIndex |
| `channelSettings` | container keyed by integer dsIndex |
| `channelStates` | container keyed by integer dsIndex |

### pydsvdcapi

Same top-level fields, with differences noted above. Channel containers are keyed by channel name instead of integer dsIndex.

---

## Summary: Most Critical Differences

### CRITICAL

1. **`siunit` and `symbol` missing from `channelDescriptions`** (section 3):
   p44vdc sends `siunit` (e.g. `"percent"`) and `symbol` (e.g. `"%"`) for every channel. pydsvdcapi omits these entirely. The dSS firmware uses `siunit` to validate channel value ranges and to display units in the UI. For grey devices, missing `siunit` on shade channels may cause the dSS to reject or misinterpret the channel descriptors.

2. **`resolution` value differs significantly for shade channels** (section 3):
   p44vdc uses `100/65536 ≈ 0.001526` (16-bit precision) for shade position and angle channels. pydsvdcapi uses `100/255 ≈ 0.392` (8-bit precision). A higher-resolution value from p44vdc allows finer positioning. If dSS firmware validates that transmitted values are multiples of resolution, pydsvdcapi's coarser resolution could trigger rounding errors.

3. **Push notification key format discrepancy** (section 6):
   p44vdc keys `channelStates` children by integer dsIndex; pydsvdcapi keys by channel name. While pydsvdcapi's approach appears to work for yellow devices (confirmed by users), the root of the `deviceOutputIndex:255` errors on grey devices may lie in this area if the dSS firmware uses different code paths for grey (shade) vs yellow (light) channel state updates.

### WARN

4. **`openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` missing** (section 2):
   These shadow-specific settings fields are present in p44vdc's `ShadowBehaviour` and are part of `outputSettings` for grey devices. pydsvdcapi does not include them. If dSS firmware tries to read motor timing from these fields and they are absent, it falls back to defaults, which should be non-fatal. If dSS writes these fields, pydsvdcapi's `apply_settings()` silently ignores them.

5. **`transitionTime` missing from `outputState`** (section 8):
   pydsvdcapi does not include `transitionTime` in `outputState`. The dSS may read this to track whether a transition is in progress (especially relevant for position-based shade movements). This could cause the dSS shade control logic to mis-time movements.

6. **`error` extra field in `outputState`** (section 8):
   pydsvdcapi always sends `error: 0` in outputState. p44vdc base does not include this field. Likely harmless but non-standard.

7. **`groups` encoding in `outputSettings`** (section 10):
   p44vdc sends all 64 group indices (true/false). pydsvdcapi sends only true entries. Functionally equivalent for reading but different in wire format.

### INFO

8. Extra fields in `outputDescription` (`name`, `defaultGroup`) — harmless.
9. Missing p44-specific extension fields (`x-p44-recommendedTransitionTime`, `x-p44-bridgePushInterval`, `x-p44-transitional`, `x-p44-transitiontimeleft`, `x-p44-progress`) — not required.
10. `channelIndex` (deprecated) missing — correct for API v3+.
11. `values` (enum value list) missing from channelDescriptions — rarely used.

---

## Recommended Fixes (Priority Order)

1. **Add `siunit` and `symbol` to `channelDescriptions`** in `OutputChannel.get_description_properties()`. Shade channels should report `siunit="percent"`, `symbol="%"`. Light channels: `brightness` → `siunit="percent"`, `symbol="%"`; `colortemp` → `siunit="reciprocal megakelvin"`, `symbol="mired"`; `hue` → `siunit="degree"`, `symbol="°"`.

2. **Review `resolution` for shade channels**: Consider whether the p44vdc value of `100/65536` is more appropriate than `100/255`. The spec likely expects this to match the hardware's actual positioning granularity.

3. **Add `transitionTime` to `outputState`**: Add a `transitionTime` field (float, seconds, current active transition duration) to `Output.get_state_properties()`.

4. **Investigate push notification key format**: Verify experimentally whether grey-device push failures are due to the name vs integer key in `channelStates` push notifications.

5. **Add shadow-specific outputSettings fields**: Add `openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` as optional float fields to `Output` (and handle them in `apply_settings()`), to match what p44vdc's ShadowBehaviour exposes.
