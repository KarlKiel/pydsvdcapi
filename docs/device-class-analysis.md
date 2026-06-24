# `deviceClass` and `deviceClassVersion` — Deep Analysis

**Scope:** How p44vdc and pydsvdcapi handle the two common device properties `deviceClass` and
`deviceClassVersion`: where values come from, what types are used, what is sent on the wire, and
where the two implementations diverge.

---

## Part 1 — p44vdc (C++ reference implementation)

*All findings are grounded in actual source code fetched from
[github.com/plan44/p44vdc](https://github.com/plan44/p44vdc). Nothing is inferred.*

### 1.1 Affected files

Only **five files** across the entire p44vdc codebase reference `deviceClass` or
`deviceClassVersion`:

| File | Role |
|---|---|
| `vdc_common/device.hpp` | Base class virtual method declarations |
| `vdc_common/device.cpp` | API property exposure + settings-file lookup |
| `vdc_common/dsscene.cpp` | Scene settings-file lookup |
| `deviceclasses/custom/customdevice.hpp` | Only override: member + virtual declaration |
| `deviceclasses/custom/customdevice.cpp` | Only override: initialization from JSON params |

No other device class — not DALI, not EnOcean, not Hue, not HomeConnect, not any of the
light/shadow/climate behaviour subclasses — overrides or references either property.

---

### 1.2 `deviceClass`

#### Base class declaration (`device.hpp`)

```cpp
/// device class (for grouping functionally equivalent single devices)
/// @note usually, only single devices do have a deviceClass
/// @return name of the device class, such as "washingmachine" or "kettle" or "oven".
///         Empty string if no device class exists.
virtual string deviceClass() { return ""; }
```

- **Type:** `string` (C++ `std::string`)
- **Default:** empty string `""`
- **Virtual:** yes

#### Only override (`customdevice.hpp` + `customdevice.cpp`)

```cpp
// customdevice.hpp
string mDevClass;  ///< device class
virtual string deviceClass() P44_OVERRIDE { return mDevClass; }

// customdevice.cpp — populated from JSON init parameters
if (aInitParams->get("deviceclass", o)) {
    mDevClass = o->stringValue();
}
```

The value is whatever string the external device descriptor passes in the JSON key `"deviceclass"`.
Examples given in p44vdc documentation: `"washingmachine"`, `"kettle"`, `"oven"`.

---

### 1.3 `deviceClassVersion`

#### Base class declaration (`device.hpp`)

```cpp
/// device class version number.
/// @note This allows different versions of the functional representation of the device class
///   to coexist in a system.
/// @return version or 0 if no version exists
virtual uint32_t deviceClassVersion() { return 0; }
```

- **Type:** `uint32_t` (32-bit unsigned integer)
- **Default:** `0`
- **Virtual:** yes

#### Only override (`customdevice.hpp` + `customdevice.cpp`)

```cpp
// customdevice.hpp
uint32_t mDevClassVersion;  ///< device class version
virtual uint32_t deviceClassVersion() P44_OVERRIDE { return mDevClassVersion; }

// customdevice.cpp — constructor default
mDevClassVersion(0),

// configureDevice() — populated from JSON init parameters
if (aInitParams->get("deviceclassversion", o)) {
    mDevClassVersion = o->int32Value();
}
```

The value is the integer passed in the JSON key `"deviceclassversion"`.

---

### 1.4 API property exposure (`device.cpp` — `accessField()`)

```cpp
// Property descriptor registration
{ "deviceClass",        apivalue_string,  deviceClass_key,        OKEY(device_obj) },
{ "deviceClassVersion", apivalue_uint64,  deviceClassVersion_key, OKEY(device_obj) },

// Property read handler
case deviceClass_key:
    if (deviceClass().size() > 0) {
        aPropValue->setStringValue(deviceClass());
        return true;
    }
    else return false;  // omitted from API response if empty

case deviceClassVersion_key:
    if (deviceClassVersion() > 0) {
        aPropValue->setUint32Value(deviceClassVersion());
        return true;
    }
    else return false;  // omitted from API response if zero
```

**Critical observations:**

1. `deviceClass` is registered as `apivalue_string` → serialized to `PropertyValue.v_string`.
2. `deviceClassVersion` is registered as `apivalue_uint64` → serialized to `PropertyValue.v_uint64`.
3. Both properties are **conditionally omitted**: `deviceClass` is not sent if empty, and
   `deviceClassVersion` is not sent if zero. No explicit NULL is placed on the wire.

---

### 1.5 How values are used internally

Both properties are used to construct file-name IDs for loading device settings and scene defaults
from configuration files (a feature guarded by `#if ENABLE_SETTINGS_FROM_FILES`):

```cpp
// device.cpp — loadSettingsFromFiles()
levelids[1] = string_format("%s_%d_class", deviceClass().c_str(), deviceClassVersion());
// → e.g. "washingmachine_1_class"

// dsscene.cpp — loadScenesFromFiles()
levelids[2] = string_format("%s_%d_class", mDevice.deviceClass().c_str(), mDevice.deviceClassVersion());
// → e.g. "washingmachine_1_class"
```

These IDs are also used by the dSS configurator to look up device profiles and matching UI
descriptions for the connected device.

---

### 1.6 Which entity types carry these properties in p44vdc

In p44vdc's **C++ class hierarchy**, `deviceClass` and `deviceClassVersion` are virtual methods on
the `Device` class (the vdSD equivalent). The `Vdc` class is a separate hierarchy and does not
inherit from `Device`, so it does not carry these properties:

| p44vdc class | Has `deviceClass`/`deviceClassVersion`? | Note |
|---|---|---|
| `Device` (vdSD equivalent) | **Base class default** (`""` / `0`) | Omitted from API if at default |
| `CustomDevice` extends `Device` | **Yes — the only override** | Set from JSON init params |
| DALI device | No | Inherits base class → empty/zero → omitted |
| Hue device | No | Same |
| EnOcean device | No | Same |
| `Vdc` (vDC connector class) | **No** | Separate class hierarchy, not a `Device` subclass |
| `VdcHost` | **No** | Same |

**Important framing note:** This is a p44vdc **implementation choice**, not a protocol constraint.
The vDC API protocol has no "device" concept distinct from vdSD — the three first-class protocol
entities are vdc-host, vdc, and vdSD, each of which can carry properties. p44vdc simply does not
implement `deviceClass`/`deviceClassVersion` on its `Vdc` objects.

---

### 1.7 Complete value inventory

| Property | Type | Default (base) | Possible non-default values | Condition to appear on wire |
|---|---|---|---|---|
| `deviceClass` | `std::string` | `""` | Any string passed in JSON `"deviceclass"` key, e.g. `"washingmachine"`, `"kettle"`, `"oven"` | Non-empty string |
| `deviceClassVersion` | `uint32_t` | `0` | Any non-zero uint32 passed in JSON `"deviceclassversion"` key | > 0 |

Wire format: `deviceClass` → `PropertyValue.v_string`; `deviceClassVersion` → `PropertyValue.v_uint64`.

---

## Part 2 — pydsvdcapi (Python library)

*All findings are grounded in actual source code from the local repository.*

### 2.1 Affected files

| File | Role |
|---|---|
| `src/pydsvdcapi/vdsd.py` | `Vdsd` class — attribute, constructor, serializers, persistence |
| `src/pydsvdcapi/vdc.py` | `Vdc` class — identical pattern |
| `src/pydsvdcapi/property_handling.py` | Wire serialization of Python values |
| `tests/test_vdsd.py` | Test examples with real values |
| `tests/test_vdc.py` | Test examples with real values |

No enum or validation layer exists for either property.

---

### 2.2 Data type and defaults

Both `Vdsd` and `Vdc` use the same pattern:

```python
# Attribute declaration (both classes)
device_class: str | None = None          # constructor parameter
device_class_version: str | None = None  # constructor parameter

# Instance attribute initialization
self.device_class: str | None = device_class
self.device_class_version: str | None = device_class_version
```

**Type:** `str | None` for **both** properties.  
**Default:** `None`.

Note: in pydsvdcapi `deviceClassVersion` is stored and transmitted as a **string** (e.g. `"1"`),
not as an integer.

---

### 2.3 Constructor parameters

```python
# Vdsd.__init__()  (vdsd.py:289-290)
def __init__(
    self,
    *,
    device: Device,
    primary_group: ColorGroup,
    # ... other params ...
    device_class: str | None = None,
    device_class_version: str | None = None,
    # ...
) -> None:

# Vdc.__init__()  (vdc.py:248-249)  — identical signature
```

Library users set the values at construction time:

```python
vdsd = Vdsd(
    device=device,
    primary_group=ColorGroup.YELLOW,
    name="Kettle",
    model="Smart Kettle v1",
    device_class="kettle",
    device_class_version="1",
)
```

Values can also be changed via direct attribute assignment after construction:

```python
vdsd.device_class = "washingmachine"
vdsd.device_class_version = "2"
```

---

### 2.4 Serialization — `get_properties()`

```python
# vdsd.py:1596-1597
def get_properties(self) -> dict[str, Any]:
    props: dict[str, Any] = {
        # ...
        "deviceClass": self.device_class,
        "deviceClassVersion": self.device_class_version,
        # ...
    }
    return props
```

The dict is then converted to `PropertyElement` protobuf structures by
`property_handling.dict_to_elements()`, using this type mapping (`property_handling.py:97-116`):

```python
if value is None:
    return _PropertyValue()          # empty PropertyValue — explicit NULL on wire

elif isinstance(value, str):
    pv.v_string = value              # → PropertyValue.v_string
```

**Resulting wire format:**

| Python value | Wire field |
|---|---|
| `"kettle"` | `PropertyValue { v_string: "kettle" }` |
| `"1"` | `PropertyValue { v_string: "1" }` |
| `None` | `PropertyValue {}` (empty — explicit NULL) |

---

### 2.5 Auto-save and persistence

Both properties are listed in `_TRACKED_ATTRS` (`vdsd.py:249-250`, `vdc.py:202-203`):

```python
_TRACKED_ATTRS: ClassVar[frozenset] = frozenset({
    # ...
    "device_class",
    "device_class_version",
    # ...
})
```

Any mutation triggers a debounced YAML write. Values are restored via `_apply_state()`:

```python
# vdsd.py:1994-1997
if "deviceClass" in state:
    self.device_class = state["deviceClass"]
if "deviceClassVersion" in state:
    self.device_class_version = state["deviceClassVersion"]
```

---

### 2.6 Which entity types carry these properties

| Entity | Has `device_class`/`device_class_version`? |
|---|---|
| `Vdsd` (virtualised device) | Yes — any instance |
| `Vdc` (vDC connector) | Yes — any instance |
| `VdcHost` | No |

Unlike p44vdc, pydsvdcapi exposes these properties on **both** the vdSD and the vDC connector
entities.

---

### 2.7 Known values from test suite

| Value | Property | Source |
|---|---|---|
| `"dSLight"` | `device_class` | `test_vdc.py:205` |
| `"dS-FD"` | `device_class` | `test_vdsd.py:186` |
| `"dSSensor"` | `device_class` | `test_vdc.py:435` |
| `"1"` | `device_class_version` | `test_vdc.py:206`, `test_vdsd.py:187` |
| `"3"` | `device_class_version` | `test_vdc.py:436` |

No enum or validated allowlist exists. Any string (or `None`) is accepted.

---

## Part 3 — Comparison and Differences

### 3.1 `deviceClassVersion` type mismatch — wire format incompatibility

This is the most significant difference.

| Aspect | p44vdc | pydsvdcapi |
|---|---|---|
| C++/Python type | `uint32_t` | `str \| None` |
| Wire field | `PropertyValue.v_uint64` | `PropertyValue.v_string` |
| Example value on wire | `v_uint64 = 1` | `v_string = "1"` |
| API descriptor type | `apivalue_uint64` | *(implicit from Python `str`)* |

When a dSS receives `deviceClassVersion` from pydsvdcapi as `v_string = "1"` but expects
`v_uint64 = 1` (as p44vdc sends it), the dSS may:

- Silently misinterpret the value (treat it as the wrong type),
- Discard the property (if the dSS parser is strict about `apivalue_uint64`),
- Or accept it if the dSS parser is lenient.

**Fix:** Change `device_class_version` in `Vdsd` and `Vdc` from `str | None` to `int | None`, and
ensure `dict_to_elements` maps it to `v_uint64` (which it already does for non-negative integers).
The constructor, persistence, and restoration code would also need updating.

---

### 3.2 Conditional omission vs. explicit NULL

| Aspect | p44vdc | pydsvdcapi |
|---|---|---|
| When property is at default | **Omitted from response** (not sent) | **Explicit NULL sent** (`PropertyValue {}`) |
| Condition for omission | `deviceClass == ""` OR `deviceClassVersion == 0` | Property is never automatically omitted |
| Trigger | `return false` in `accessField()` | `None` maps to empty `PropertyValue()` |

In p44vdc, if a device has no device class, the `deviceClass` and `deviceClassVersion` keys simply
do not appear in the `getProperty` response. In pydsvdcapi, if the library user leaves both at
`None`, the response contains:

```
PropertyElement { name: "deviceClass",        value: PropertyValue {} }
PropertyElement { name: "deviceClassVersion",  value: PropertyValue {} }
```

The dSS firmware's behaviour when it receives an explicit NULL for these properties (versus not
receiving them at all) is unspecified. For well-behaved vdSM implementations, both should be
equivalent (treat absent = treat null = "no device class"). However, it deviates from p44vdc's
established pattern.

**Recommendation:** When `device_class` is `None`, omit the key entirely from the response dict
(or use `NO_VALUE` sentinel) rather than emitting an explicit NULL. Same for
`device_class_version`.

---

### 3.3 Scope: `Vdc` entity

| Entity | p44vdc | pydsvdcapi |
|---|---|---|
| vdSD equivalent (`Device` / `Vdsd`) | Yes | Yes |
| vDC connector (`Vdc`) | **No** — p44vdc's `Vdc` is a separate class hierarchy | **Yes** — `Vdc` has `device_class` |

The vDC API protocol treats vdc-host, vdc, and vdSD as three distinct first-class entities — none
of them is a sub-concept of another. p44vdc's internal C++ class hierarchy happens to put
`deviceClass` only on `Device` (vdSD), not on `Vdc`, but this is a p44vdc implementation detail.

pydsvdcapi exposing `device_class`/`device_class_version` on `Vdc` is therefore **consistent with
the protocol** — the protocol does not restrict these properties to vdSD. p44vdc simply does not
implement them there.

---

### 3.4 Architectural role: built-in vs. custom devices

| Aspect | p44vdc | pydsvdcapi |
|---|---|---|
| Built-in device types (DALI, Hue, EnOcean, …) | **Never set** `deviceClass` (return `""`) | N/A — pydsvdcapi has no built-in device types |
| Custom/external device types | Only `CustomDevice` sets `deviceClass` | **Every** `Vdsd` can set `deviceClass` |
| Value source | JSON init parameter from external config | Constructor argument or property assignment |
| Validation | None (free-form string from JSON) | None (free-form `str`) |

Every pydsvdcapi integration is, architecturally, in the `CustomDevice` role — the library user
always controls the device class value. This is appropriate but means pydsvdcapi users must know
the correct dSS-defined `deviceClass` strings for their devices without guidance from the library.

---

### 3.5 Summary of all differences

| # | Area | p44vdc | pydsvdcapi | Severity |
|---|---|---|---|---|
| 1 | **`deviceClassVersion` wire type** | `v_uint64` (integer) | `v_string` (string) | 🔴 **Critical** — type mismatch on the wire |
| 2 | **Omission when at default** | Property omitted (not sent) | Explicit NULL sent | 🟡 Medium — behavioural divergence, likely benign in practice |
| 3 | **`Vdc` entity carries `deviceClass`** | No (p44vdc implementation choice) | Yes | 🟢 Low — pydsvdcapi is protocol-correct; p44vdc simply doesn't implement it on `Vdc` |
| 4 | **Built-in device types always omit** | Yes (DALI, Hue, etc. return `""`) | N/A | ⚪ N/A — architectural difference, not a conformance issue |
| 5 | **Type validation / enum** | None (free-form JSON string) | None | 🟢 Low — equally unvalidated |

---

### 3.6 Recommended fixes

**Fix 1 (Critical) — correct the type of `device_class_version`:**

```python
# Before (in vdsd.py and vdc.py)
device_class_version: str | None = None
self.device_class_version: str | None = device_class_version

# After
device_class_version: int | None = None
self.device_class_version: int | None = device_class_version
```

`property_handling.dict_to_elements()` already maps non-negative `int` → `PropertyValue.v_uint64`,
so no change to the serialization layer is needed. Update persistence/restore to store and load as
integer, and update the test examples (`"1"` → `1`).

**Fix 2 (Medium) — omit properties when `None` instead of sending explicit NULL:**

Use the `NO_VALUE` sentinel in `get_properties()` for unset optional identification fields, or
filter `None` values before building the response. This brings behaviour in line with p44vdc's
conditional-omit pattern for defaulted properties.
