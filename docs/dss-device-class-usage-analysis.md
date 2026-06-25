# dSS — How `deviceClass` and `deviceClassVersion` Are Handled

**Scope:** Code-based analysis of how the digitalSTROM Server (dSS) receives, processes, and uses
the `deviceClass` and `deviceClassVersion` properties delivered by a vdSD during device
enumeration.

**Source:** `dss-mainline-master` firmware source tree.

---

## Terminology note: two unrelated concepts share a name

Before the analysis it is critical to separate two things that both use the word "deviceClass":

| Term | Where | What it is |
|---|---|---|
| `deviceClass` **string** | vDC API — `PropertyValue.v_string` | The profile name sent by the vdSD over protobuf, e.g. `"kettle"`, `"washingmachine"` |
| `DeviceClasses_t` **enum** | dSS internal C++ code | An integer enum for the colour/application group of a powerline device (yellow = lights, green = blinds, etc.) |

These two concepts are **completely unrelated**. Every `deviceClass` reference in
`device.cpp`, `powerline.cpp`, `jscluster.cpp`, and `apartmentrequesthandler.cpp` refers to the
**integer enum**, not to the vDC API string. The analysis below focuses exclusively on the vDC API
string.

---

## 1. Where `deviceClass` enters dSS — the spec fetch

During device discovery the bus scanner (`src/model/busscanner.cpp:488`) calls
`VdcHelper::getSpec()` for every newly found vdSD:

```cpp
// busscanner.cpp:488
auto vdsdSpec = VdcHelper::getSpec(dev->getDSMeterDSID(), dev->getDSID());
dev->setVdsdSpec(std::move(vdsdSpec));
```

`VdcHelper::getSpec()` is defined in `src/vdc-connection.cpp` and issues a single
`VDSM_REQUEST_GET_PROPERTY` over protobuf requesting a fixed list of property names:

```cpp
// vdc-connection.cpp:44-48
VdsdSpec_t VdcHelper::getSpec(dsuid_t _vdsm, dsuid_t _device) {
  vdcapi::Message message = VdcConnection::getProperty(
      _vdsm, _device,
      {"hardwareModelGuid", "modelUID", "modelFeatures", "vendorGuid", "vendorId",
       "vendorName", "oemGuid", "oemModelGuid", "configURL", "hardwareGuid",
       "model", "modelVersion", "hardwareVersion", "name", "displayId",
       "deviceClass", "deviceClassVersion"});   // ← both fetched
  ...
```

So dSS does request both properties from the vdSD.

---

## 2. What dSS does with the response

The complete response-parsing block that follows reads individual fields from the response:

```cpp
// vdc-connection.cpp:52-88
VdcElementReader rootReader(message.vdc_response_get_property().properties());
ret.hardwareModelGuid = rootReader["hardwareModelGuid"].getValueAsString();
ret.vendorGuid        = rootReader["vendorGuid"].getValueAsString();
ret.oemGuid           = rootReader["oemGuid"].getValueAsString();
ret.oemModelGuid      = rootReader["oemModelGuid"].getValueAsString();
ret.configURL         = rootReader["configURL"].getValueAsString();
ret.hardwareGuid      = rootReader["hardwareGuid"].getValueAsString();
ret.model             = rootReader["model"].getValueAsString();
ret.modelUID          = rootReader["modelUID"].getValueAsString();
ret.hardwareVersion   = rootReader["hardwareVersion"].getValueAsString();
ret.name              = rootReader["name"].getValueAsString();
ret.vendorId          = rootReader["vendorId"].getValueAsString();
ret.vendorName        = rootReader["vendorName"].getValueAsString();
ret.modelVersion      = rootReader["modelVersion"].getValueAsString();
ret.displayId         = rootReader["displayId"].getValueAsString();
ret.descriptionsGroup = rootReader["descriptionsGroup"].getValueAsString();
ret.descriptionsClass = rootReader["descriptionsClass"].getValueAsString();
// ... modelFeatures loop below
```

**`deviceClass` and `deviceClassVersion` are not read from `rootReader`.**
There is no `ret.deviceClass = ...` or `ret.deviceClassVersion = ...` anywhere in `getSpec()`.

---

## 3. The `VdsdSpec_t` struct has no fields for them

The struct that holds all vdSD identification data is defined in `src/vdc-connection.h:70-103`:

```cpp
struct VdsdSpec_t {
    std::string oemGuid;
    std::string oemModelGuid;       // ← GTIN — the actual device lookup key
    std::string vendorGuid;
    std::string vendorId;
    std::string hardwareGuid;
    std::string hardwareModelGuid;
    std::string modelUID;
    std::string descriptionsGroup;
    std::string descriptionsClass;  // different from deviceClass — see §7
    std::string name;
    std::string model;
    std::string displayId;
    std::string hardwareVersion;
    std::string modelVersion;
    std::string vendorName;
    std::string dSUID;
    int primaryGroup;
    // ... binary input vectors ...
    std::string configURL;
    bool active;
    std::set<ModelFeatureId> modelFeatures;
    // NO deviceClass field
    // NO deviceClassVersion field
};
```

The struct has no fields for the vDC API `deviceClass` or `deviceClassVersion` values.

---

## 4. Conclusion: the values are fetched but completely discarded

The entire lifecycle of `deviceClass` and `deviceClassVersion` in the current dSS firmware is:

```
vdSD sends PropertyValue { v_string: "kettle" }
    → dSS deserialises protobuf response
    → rootReader["deviceClass"] is never called
    → value is discarded when the temporary Message object is destroyed
```

No code path in dSS stores, logs, exports, or acts on these values. This is confirmed by a
full-codebase search: there are **zero** references to `deviceClass` or `deviceClassVersion` in any
file other than `vdc-connection.cpp:48` (the fetch request line itself).

---

## 5. The device database uses GTIN, not `deviceClass`

The local device database (`data/vdc-db.sql`) provides all device profile data — states, actions,
sensors, outputs, scene templates, and UI label translations. Every query in `src/vdc-db.cpp` is
keyed by **GTIN** extracted from `spec.oemModelGuid`:

```cpp
// busscanner.cpp:500
eanString = dev->getVdsdSpec().oemModelGuid;
// → eanString is then used for all db.getStates(), db.getActions(), db.getSensors(), ...

// vdc-db.cpp:189 (typical query pattern)
std::string sql = "select * from callGetStatesBase where gtin=?";
query.bind(gtin);
```

Example GTIN-based device entries from `vdc-db.sql`:

```sql
insert into device values(18, "7640156791945", "vDC smarter iKettle 2.0", "1", 0);
insert into device values(26, "7640156792096", "Siemens Coffee Maker CT636LES6", "", 4);
insert into device values(75, "7640156792942", "Siemens Oven CN878G4S6", "", 3);
```

The `device_template` table (referenced via `device.device_template_id`) groups devices that
share a profile. Template names like `"Oven"`, `"Coffee Maker"`, `"Washer"`, `"Dryer"` are purely
internal labels — they are not the vDC API `deviceClass` string and are not exposed to vdSD
devices.

---

## 6. The `device_class` SQL table is empty

The schema defines a `device_class` table and a `device_class_id` column on nearly every
device-related table:

```sql
create table "device_class"(id primary key, name);
create table "device_template"(id primary key, name, device_class_id);
create table "device_status"(id primary key, device_id, name, tags, device_template_id, device_class_id);
-- ... same pattern on device_labels, device_outputs, device_sensors, device_events, ...
```

However, there are **zero `insert into device_class` statements** in the entire `vdc-db.sql`. The
table exists in the schema but contains no data. None of the compiled SQL view queries (`callGetStatesBase`,
`callGetActionsBase`, etc.) join on `device_class_id`. The column is present but unused.

This is likely a placeholder schema element designed for a future grouping mechanism that was never
implemented, or a legacy remnant from an earlier design.

---

## 7. `descriptionsClass` and `descriptionsGroup` — a different property

`VdsdSpec_t` has two fields named `descriptionsClass` and `descriptionsGroup`. These are
**not** `deviceClass` and `deviceClassVersion`. They are a separate pair of properties read from the
vdSD response (`vdc-connection.cpp:67-68`) and passed to the configurator UI via `device-info.cpp`:

```cpp
// device-info.cpp:286-287
insert("descriptionsGroup", spec.descriptionsGroup);
insert("descriptionsClass", spec.descriptionsClass);
```

These fields carry UI localisation grouping metadata for the configurator. They do NOT appear in
the `getProperty` request list (the request only asks for `deviceClass` and `deviceClassVersion`,
not for `descriptionsClass`/`descriptionsGroup`), so in practice they return empty strings for all
standard p44vdc devices.

---

## 8. The JSON API does not expose `deviceClass`

The `VdcHardwareInfo` and similar fields are exposed in the dSS JSON API via
`src/web/handler/jsonhelper.cpp:80-92`:

```cpp
if (device.isVdcDevice()) {
    const auto& vdsd = device.getVdsdSpec();
    _json.add("VdcHardwareModelGuid", vdsd.hardwareModelGuid);
    _json.add("VdcModelUID",          vdsd.modelUID);
    _json.add("VdcModelVersion",      vdsd.modelVersion);
    _json.add("VdcVendorGuid",        vdsd.vendorGuid);
    _json.add("VdcOemGuid",           vdsd.oemGuid);
    _json.add("VdcConfigURL",         vdsd.configURL);
    _json.add("VdcHardwareGuid",      vdsd.hardwareGuid);
    _json.add("VdcHardwareInfo",      vdsd.model);
    _json.add("VdcHardwareVersion",   vdsd.hardwareVersion);
    _json.add("hasActions",           bool(device.getHasActions()));
}
```

Neither `deviceClass` nor `deviceClassVersion` appear here. Since they are not in `VdsdSpec_t`,
they cannot be exposed.

---

## 9. Model features — also GTIN/modelUID keyed, not `deviceClass` keyed

At device discovery the model features sent by the vdSD are registered keyed by
`modelUID` and by the integer colour group (not by the `deviceClass` string):

```cpp
// busscanner.cpp:519-520
modelFeatures.setFeatures(
    static_cast<int>(dev->getDeviceClass()),  // integer colour enum, not the string
    vdsdSpec.modelUID,                        // hardware model ID
    std::vector(vdsdSpec.modelFeatures.begin(), vdsdSpec.modelFeatures.end()));
```

The `deviceClass` string plays no role here.

---

## 10. Summary

| Question | Answer |
|---|---|
| Does dSS request `deviceClass` and `deviceClassVersion` from the vdSD? | **Yes** — they are in the `getProperty` request list |
| Does dSS parse the returned values? | **No** — `rootReader["deviceClass"]` is never called |
| Does `VdsdSpec_t` store either value? | **No** — the struct has no such fields |
| Does the local device database use `deviceClass` for lookups? | **No** — all lookups use GTIN (`oemModelGuid`) |
| Is the `device_class` SQL table populated? | **No** — the table is defined but empty |
| Is `deviceClass` exposed via the JSON API? | **No** |
| Is `deviceClassVersion` used as a type-version discriminator anywhere? | **No** |
| What is the practical effect of sending `deviceClass = "kettle"` vs. not sending it? | **Identical** — the value is discarded either way |

**Bottom line:** In the current dSS mainline firmware, `deviceClass` and `deviceClassVersion` sent
by a vdSD are silently discarded immediately after the `getProperty` response is received. The
property values play no role in device identification, database lookup, UI configuration, feature
registration, or JSON API exposure. The device profile lookup is GTIN-based throughout.

The names "washingmachine", "kettle", "oven" appear in p44vdc's internal configuration-file
loading (`loadSettingsFromFiles()`, `loadScenesFromFiles()`), which is a p44vdc-side feature for
loading device profiles from local files — not a dSS-side lookup driven by this property.
