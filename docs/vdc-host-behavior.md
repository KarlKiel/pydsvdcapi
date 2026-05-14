# pydsvdcapi — VDC Host Behavior Reference

> **Audience:** This document targets completed VDC implementations.
> It explains the *what* and *why* of configuration choices rather
> than implementation mechanics.  For API details, see the inline
> docstrings.  For device-type examples, see
> `docs/model-features-auto-assignment.md`.

---

## 1. The Three-Level Entity Hierarchy

A pydsvdcapi deployment has exactly three levels:

```
VdcHost  — one per gateway host (one MAC address / process)
  └─ Vdc  — one or more logical connectors (one per "integration type")
       └─ Device → Vdsd  — one or more virtual devices (one per physical thing)
```

The dSS and the configurator see all three levels.  The vdSM (the
low-level component inside the dSS that the host talks to) connects
to the VdcHost's TCP socket and discovers everything it contains via
the announcement protocol.

---

## 2. VdcHost — the gateway itself

### 2.1 What it is

The **VdcHost** represents the hardware or process that bridges
third-party systems into digitalSTROM.  It has its own dSUID, appears
as an addressable entity in the dSS property tree, and serves a single
TCP socket on port **8444** (configurable).

### 2.2 DNS-SD discovery

The VdcHost announces itself via mDNS (`_ds-vdc._tcp`) so that any
vdSM on the local network can find it automatically.  No manual IP
configuration is required on the dSS side.

### 2.3 Identity properties

| Property | Purpose |
|---|---|
| `name` | User-visible label in the dSS configurator ("My Light Gateway") |
| `model` | Implementation description ("ACME Bridge v1") |
| `model_uid` | Deterministically derived from `model` — ensures the dSS can distinguish different gateway types |
| `hardware_guid` | Derived from the MAC address; ties the dSUID to physical hardware |
| `vendor_name` | Optional vendor label displayed alongside the model |

### 2.4 Persistence

When a `state_path` is configured, the host saves its entire property
tree (all vDCs, devices, and their configuration) to a YAML file.  On
restart, state is restored automatically so devices do not lose their
dSS zone assignment, scene configuration, or other user-set properties.
The save is debounced — rapid changes coalesce into a single write.

### 2.5 Session and reconnect behaviour

The VdcHost runs one session at a time.  When the vdSM connects (or
reconnects after a restart or cable pull), the host:

1. Completes the protocol handshake (`hello`/`hello-response`)
2. Immediately re-announces all registered vDCs
3. Immediately re-announces all registered devices

No intervention from user code is required for reconnect.  Every vDC
and device declared before `host.start()` is automatically presented
to each new session.

---

## 3. Vdc — one logical connector per integration type

### 3.1 What it is

A **Vdc** is a named logical group of virtual devices that share the
same integration purpose.  A single VdcHost can contain multiple vDCs.
Typical partition patterns:

- One vDC per protocol (Zigbee, Z-Wave, Modbus…)
- One vDC per cloud integration (Hue, Shelly, Tesla…)
- One vDC per device class when capabilities differ between classes

### 3.2 Identity and implementation ID

The `implementation_id` is a stable, globally unique string (e.g.
`"x-acme-hue"`) that identifies the integration software.  It is
used to derive the vDC's dSUID deterministically, so the same
implementation always produces the same dSUID regardless of host.
The required `"x-"` prefix marks it as a non-digitalSTROM native
implementation.

### 3.3 Capabilities

```
VdcCapabilities(
    metering=True,           # the vDC provides energy metering
    identification=True,     # the vDC can identify itself (blink)
    dynamic_definitions=True # devices support live dynamic feature queries
)
```

**`dynamic_definitions`** is the most consequential capability.  When
set to `True`, the dSS will query device states, events, actions, and
properties live from the VDC rather than falling back to its static
database.  Set this to `True` whenever devices declare states, events,
or properties that the dSS should track in automation.  See
§ 9 for a detailed discussion of complex-device features.

### 3.4 Template support

The vDC can save and load device configurations as YAML templates.
Templates capture the structural definition of a device (output
channels, sensors, model features) and the specific field values that
differ between instances (name, dSUID, converter code), making it
easy to pre-configure a fleet of identical devices.

---

## 4. Device and Vdsd — one physical thing, one or more dSUIDs

### 4.1 The Device / Vdsd distinction

| Concept | What it maps to in dS |
|---|---|
| **Device** | One physical piece of hardware; a grouping container |
| **Vdsd** | One addressable entity with a dSUID; what the dSS sees and controls |

A single Device holds one or more Vdsd instances.  Each Vdsd has a
distinct dSUID derived by varying byte 17 of the base dSUID.

### 4.2 When to use one dSUID

Most physical devices map to exactly one Vdsd.  Use a single Vdsd
when the device has:

- One primary function (e.g. a light, a shutter, a temperature sensor)
- Inputs (buttons, sensors, binary inputs) that belong to that function

### 4.3 When to use multiple dSUIDs for one physical device

Use **multiple Vdsd instances** (and thus multiple dSUIDs) for one
physical device in these cases:

**Case A — independent outputs**
A device that controls both a light and a shutter must split them.
The dSS controls outputs independently by zone/group — two different
primary groups cannot share one dSUID.

**Case B — different zones**
A multi-zone controller (e.g. a thermostat head with two channels)
must split each zone into its own Vdsd so the dSS can assign them
to different rooms.

**Case C — specification-defined device profiles**
Some device classes require splitting by the vDC API specification.
When in doubt, consult `docs/device-splitting-guidelines.md`.

**What stays together:** Buttons, sensors, and binary inputs that
logically belong to the same physical function can share a Vdsd with
that function's output.  A button panel that controls a light belongs
on the same Vdsd as the light's output.

### 4.4 Sub-device index

Each Vdsd carries a `subdevice_index` (0–255) that occupies byte 17
of the dSUID.  Sub-device 0 is the "primary" Vdsd for the device.
The index is stable — it identifies which functional role a Vdsd
plays within the physical device and must not change between restarts.

### 4.5 Structural changes after announcement

The dSS cannot process in-place structural changes.  When the set of
Vdsd instances inside a Device needs to change (e.g. a new channel
is added), the Device must go through a *vanish → modify → re-announce*
cycle.  `device.update(session, callback)` manages this automatically.

---

## 5. Primary group (colour class) and its role

Every Vdsd declares a **primary group** that places the device into
one of the dS colour classes.  This is not just a cosmetic choice —
it controls:

- Which dS application UI the device appears on (light control,
  shade control, climate, etc.)
- Which scene calls and group commands the device responds to
- Which model-feature UI panels the dSS configurator shows
- Which FunctionID bits the dSM uses to classify the device

The primary group must match the device's physical function.  Values map
directly to the firmware's `ApplicationType` enum (`modelconst.h`):

| `ColorGroup` | Value | Physical use | Configurator surface |
|---|---|---|---|
| `YELLOW` | 1 | Lighting — dimmable, switched, RGB | Light control |
| `GREY` | 2 | Shades — outdoor blinds, roller shutters, **and indoor curtains** (same group; channel type distinguishes indoor vs outdoor) | Shade/blind control |
| `BLUE` | 3 | **All climate sub-types**: heating valves, floor heating, ventilation units, window openers, fan-coil units, room temperature controllers | Climate |
| `CYAN` | 4 | Audio — playback devices, amplifiers | Audio |
| `MAGENTA` | 5 | Video — displays, projectors, media players | Video |
| `RED` | 6 | Security — alarms, sensors *(deprecated in firmware)* | Security |
| `GREEN` | 7 | Access — door locks, gate openers *(deprecated in firmware)* | Access |
| `BLACK` | 8 | Joker — multi-purpose, custom integrations | Joker/configurable |
| `WHITE` | 9 | Single Device — apps, logic, generic automation devices | Single Device |

> **TCP/IP VDC limitation:** Only values 1–9 are valid for `primaryGroup` on TCP/IP VDC devices.  Values 10–12 (ventilation, window, recirculation) and 48+ are used by backend-VDC and physical hardware paths only.  For a TCP/IP VDC, all climate sub-types — heating valves, ventilation, windows, fan-coil units, and temperature controllers — all use `ColorGroup.BLUE = 3`.  The specific climate behaviour (ventilation vs. heating vs. FCU) is determined by the declared output channel types and model features, not by the `primaryGroup` value.

> **Indoor curtains vs outdoor blinds** — both use `GREY = 2`.  The
> distinction is at the output channel level: declare
> `SHADE_POSITION_INDOOR` (channel 8) for curtains and
> `SHADE_POSITION_OUTSIDE` (channel 7) for roller shutters.  There is no
> separate group for indoor shade in the firmware.
>
> **`WHITE = 9`** — setting `primaryGroup = 9` on a VDC device causes the
> dSS to treat it as a white / Single Device (Einzelgerät), confirmed on
> real hardware. (Do not confuse with colorClass=9, Cooling)

**Relation to output group fields** — `primaryGroup` is a device-level property
(type classification).  The output-level fields `default_group`, `active_group`,
and `groups` use `ColorClass` (Application Group ID) values from the same integer
space (1–12, 48, 64, 65, 69).  For most devices all four values carry the same integer.
They diverge for joker devices: a joker device can declare `primaryGroup=8` while having
its output `active_group=1` (LIGHTS) — making the joker output participate in light
scene calls.  They also diverge for apartment-level outputs (e.g. an apartment
ventilation device uses `primaryGroup=3` / BLUE with `active_group=64` /
APARTMENT_VENTILATION, since 64 is not valid in `primaryGroup` for TCP/IP VDC).
See §6.2 for details on how these three output fields differ and how the dSS
processes each one.

---

## 6. Output — the controllable function

### 6.1 Output function

The `function` enum determines the control model:

| `OutputFunction` | Value | Behaviour |
|---|---|---|
| `ON_OFF` | 0 | Binary switch; one channel, value 0 or 100 |
| `DIMMER` | 1 | Brightness with smooth transitions |
| `POSITIONAL` | 2 | Absolute position (0–100 %) with travel time; used for shades |
| `DIMMER_COLOR_TEMP` | 3 | Brightness + colour temperature (tunable white) |
| `FULL_COLOR_DIMMER` | 4 | Brightness + hue + saturation (full RGB/RGBW) |
| `BIPOLAR` | 5 | Bidirectional output (e.g. motorised valve ±) |
| `INTERNALLY_CONTROLLED` | 6 | Device drives its own output; dSS only stores scenes |
| `CUSTOM` | 127 | Action-output behaviour — no standard channels; used for pure SingleDevice outputs |

The function must match what the physical device actually supports.
Declaring `DIMMER` for a relay produces UI controls the device cannot
honour, which confuses end users.

### 6.2 Group-related output fields — three distinct concepts

An output carries three group-related fields that look similar but mean
different things and are processed differently by the dSS:

| Python field | Protocol key | Role |
|---|---|---|
| `Output.default_group` | `outputDescription.defaultGroup` | The application group this output *describes itself as* (read-only description, not routing logic) |
| `Output.active_group` | `outputSettings.activeGroup` | The GroupID this output is *currently active in* — drives scene routing and group commands |
| `Output.groups` | `outputSettings.groups` | The full set of GroupIDs this output belongs to — determines which group calls it responds to |

For most simple devices these three values are identical (e.g., all three are 1 for a
light).  They can differ for joker devices, which may declare `primaryGroup=8` (BLACK)
at the device level but have their output assigned to `active_group=1` (YELLOW) so it
participates in the standard lighting group.

**Valid value ranges** differ slightly between fields:

- `default_group` and `active_group`: use `ColorClass` (Application Group ID) values —
  the same integers as GroupIDs (1–12, 48, 64, 65, 69).  Most devices set all three
  output fields to match `primaryGroup`.  A Yellow light uses `default_group=1`
  (`ColorClass.LIGHTS`).  A Blue heating valve uses `default_group=3`
  (`ColorClass.HEATING`).  A Blue ventilation unit uses `default_group=10`
  (`ColorClass.VENTILATION`).

- `groups`: valid range is 1–63 only.  Global application groups ≥ 64
  (`APARTMENT_VENTILATION=64`, `AWNINGS=65`, `APARTMENT_RECIRCULATION=69`) **cannot**
  appear in `groups`.  For a device whose `active_group` is a global app group (≥ 64),
  put the corresponding regular group in `groups` instead — e.g. an apartment
  ventilation output uses `active_group=64` but `groups={10}` (VENTILATION).

**Backend-VDC path note**: when pydsvdcapi is used as a TCP/IP VDC (classic path), the
vDSM reads all three output fields from the VDC announcement and translates them into the
dS485 bus protocol.  When the dSS backend-VDC REST path is used instead, the dSS ignores
`outputSettings.activeGroup` and `outputSettings.groups` entirely — it calls
`addToGroup(primaryGroup)` and `setActiveGroup(primaryGroup)` using the device-level
`primaryGroup` value only.

**Application Group ID table** (use `ColorClass` enum for `default_group` / `active_group` / `groups`):

| `primaryGroup` (`ColorGroup`) | `ColorClass` | Value | Typical device type |
|---|---|---|---|
| YELLOW (1) | `LIGHTS` | 1 | Dimmable light, switched light, RGB light |
| GREY (2) | `BLINDS` | 2 | Outdoor roller shutter, venetian blind, indoor curtain, awning |
| GREY (2) | `AWNINGS` | 65 | Awnings (global app group; NOT in `groups`) |
| BLUE (3) | `HEATING` | 3 | Heating radiator valve, floor heating actuator |
| BLUE (3) | `COOLING` | 9 | Active cooling device |
| BLUE (3) | `VENTILATION` | 10 | Room ventilation unit (HRV, AHU, exhaust fan) |
| BLUE (3) | `WINDOW` | 11 | Motorised window opener |
| BLUE (3) | `RECIRCULATION` | 12 | Fan-coil unit, split AC, recirculation unit |
| BLUE (3) | `TEMPERATURE_CONTROL` | 48 | Room temperature controller (thermostat head) |
| BLUE (3) | `APARTMENT_VENTILATION` | 64 | Apartment-level ventilation unit (global app group; NOT in `groups`) |
| BLUE (3) | `APARTMENT_RECIRCULATION` | 69 | Apartment-level recirculation unit (global app group; NOT in `groups`) |
| CYAN (4) | `AUDIO` | 4 | Audio speaker / player instance |
| MAGENTA (5) | `VIDEO` | 5 | Video / TV device |
| RED (6) | `SECURITY` | 6 | Security / alarm output *(deprecated)* |
| GREEN (7) | `ACCESS` | 7 | Door lock, gate opener *(deprecated)* |
| BLACK (8) | `JOKER` | 8 | Generic joker / configurable device |
| WHITE (9) | `NONE` | 0 | Complex single device (no color logic) |

### 6.3 Output channels

Each controllable dimension of the output is a separate channel.
The complete set of standard channel types is:

| `OutputChannelType` | Value | Unit / range | Typical use |
|---|---|---|---|
| `DEFAULT` | 0 | — | Catch-all / unspecified |
| `BRIGHTNESS` | 1 | 0–100 % | Light level |
| `HUE` | 2 | 0–360 ° | Hue (RGB colour) |
| `SATURATION` | 3 | 0–100 % | Saturation (RGB colour) |
| `COLOR_TEMPERATURE` | 4 | 100–1000 mired | Colour temperature (tunable white) |
| `CIE_X` | 5 | 0.0–1.0 | CIE xy chromaticity X |
| `CIE_Y` | 6 | 0.0–1.0 | CIE xy chromaticity Y |
| `SHADE_POSITION_OUTSIDE` | 7 | 0–100 % | External blind / roller shutter position |
| `SHADE_POSITION_INDOOR` | 8 | 0–100 % | Indoor curtain / blind position |
| `SHADE_OPENING_ANGLE_OUTSIDE` | 9 | 0–100 % | External slat / blade tilt angle |
| `SHADE_OPENING_ANGLE_INDOOR` | 10 | 0–100 % | Indoor slat / blade tilt angle |
| `TRANSPARENCY` | 11 | 0–100 % | Electrochromic glass transparency |
| `AIR_FLOW_INTENSITY` | 12 | 0–100 % | Fan / ventilation speed |
| `AIR_FLOW_DIRECTION` | 13 | 0–100 % | Air flow direction (swing) |
| `AIR_FLAP_POSITION` | 14 | 0–100 % | Air flap / damper position |
| `AIR_LOUVER_POSITION` | 15 | 0–100 % | Louver position |
| `HEATING_POWER` | 16 | 0–100 % | Heating valve opening / PWM power |
| `COOLING_CAPACITY` | 17 | 0–100 % | Cooling capacity |
| `AUDIO_VOLUME` | 18 | 0–100 % | Audio volume level |
| `POWER_STATE` | 19 | 0 / 100 | Generic power on/off state |
| `AIR_LOUVER_AUTO` | 20 | 0 / 100 | Louver auto-swing on/off |
| `AIR_FLOW_AUTO` | 21 | 0 / 100 | Air flow auto-mode on/off |
| `WATER_TEMPERATURE` | 22 | °C | Water / boiler temperature setpoint |
| `WATER_FLOW_RATE` | 23 | l/min | Water flow rate |
| `POWER_LEVEL` | 24 | 0–100 % | Generic power level |
| `VIDEO_STATION` | 25 | integer | TV channel / video station number |
| `VIDEO_INPUT_SOURCE` | 26 | integer | Video input source selector |

Channel IDs 192–239 are reserved for device-specific (proprietary)
channels that do not correspond to any standard type.

Channels have configurable `min_value` / `max_value` so that the dSS
can present the correct UI ranges.  Value converters can translate
between the dSS 0–100 % range and a device's native units.

### 6.4 Scene management

The dSS stores output values per scene (0–127) per device.  The
VdcHost handles `callScene`, `saveScene`, `undoScene`, and `callMinScene`
automatically and invokes the output's `on_channel_applied` callback
with the resulting channel values.  User code only needs to send those
values to the physical device.

---

## 7. Inputs — sensors, buttons, binary inputs

### 7.1 Sensor inputs

Sensor inputs push analogue measurements to the dSS in physical units
(temperature in °C, power in W, etc.).  The dSS converts values for
display using the declared `sensor_type`.  Push throttling is
configurable:

- `min_push_interval` — minimum seconds between pushes (prevents
  flooding for fast-changing sensors)
- `changes_only_interval` — only push when the value changes within
  this window
- `alive_sign_interval` — periodic "I'm still alive" re-push even if
  value is unchanged; essential so the dSS does not mark the sensor as
  stale

Declared sensor types drive model-feature auto-assignment (e.g. a
power meter sensor automatically enables the `consumption` UI panel).

Complete list of sensor types:

| `SensorType` | Value | Physical quantity / unit |
|---|---|---|
| `NONE` | 0 | Unspecified |
| `TEMPERATURE` | 1 | Temperature (°C) |
| `HUMIDITY` | 2 | Relative humidity (%) |
| `ILLUMINATION` | 3 | Illuminance (lux) |
| `SUPPLY_VOLTAGE` | 4 | Supply voltage (V) |
| `CO_CONCENTRATION` | 5 | Carbon monoxide concentration (ppm) |
| `RADON_ACTIVITY` | 6 | Radon activity (Bq/m³) |
| `GAS_TYPE` | 7 | Gas type / presence (type index) |
| `PARTICLES_PM10` | 8 | Particulate matter PM10 (μg/m³) |
| `PARTICLES_PM2_5` | 9 | Particulate matter PM2.5 (μg/m³) |
| `PARTICLES_PM1` | 10 | Particulate matter PM1 (μg/m³) |
| `ROOM_OPERATING_PANEL` | 11 | Room operating panel value |
| `FAN_SPEED` | 12 | Fan speed (rpm or %) |
| `WIND_SPEED` | 13 | Wind speed (m/s) |
| `ACTIVE_POWER` | 14 | Active electrical power (W) |
| `ELECTRIC_CURRENT` | 15 | Electric current (A) |
| `ENERGY_METER` | 16 | Cumulative energy (kWh) |
| `APPARENT_POWER` | 17 | Apparent power (VA) |
| `AIR_PRESSURE` | 18 | Atmospheric pressure (hPa) |
| `WIND_DIRECTION` | 19 | Wind direction (°) |
| `SOUND_PRESSURE_LEVEL` | 20 | Sound pressure level (dB) |
| `PRECIPITATION` | 21 | Precipitation / rain amount (mm/h) |
| `CO2_CONCENTRATION` | 22 | Carbon dioxide concentration (ppm) |
| `WIND_GUST_SPEED` | 23 | Wind gust speed (m/s) |
| `WIND_GUST_DIRECTION` | 24 | Wind gust direction (°) |
| `GENERATED_ACTIVE_POWER` | 25 | Generated (feed-in) active power (W) |
| `GENERATED_ENERGY` | 26 | Generated cumulative energy (kWh) |
| `WATER_QUANTITY` | 27 | Water quantity / volume (l) |
| `WATER_FLOW_RATE` | 28 | Water flow rate (l/min) |
| `LENGTH` | 29 | Length / distance (m) |
| `MASS` | 30 | Mass / weight (kg) |
| `DURATION` | 31 | Duration / time (s) |
| `PERCENT` | 32 | Generic percentage (%) |
| `PERCENT_SPEED` | 33 | Speed as percentage of maximum (%) |
| `FREQUENCY` | 34 | Frequency (Hz) |

### 7.2 Binary inputs

Binary inputs push boolean (on/off) or extended integer state.  The
`input_type` tells the dSS what the input represents so it can render
the correct status icon and enable the right automation conditions.

> **Firmware note:** only `GENERIC` (0) is interpreted and acted upon
> directly by the dSS firmware itself.  All other types are forwarded
> to and processed by the dSM hardware bus module — they appear in the
> property tree and can be used in automations via the app add-ons.

| `BinaryInputType` | Value | Meaning |
|---|---|---|
| `GENERIC` | 0 | Generic / app-mode — interpreted by dSS firmware directly |
| `PRESENCE` | 1 | Presence detector |
| `BRIGHTNESS` | 2 | Brightness / daylight sensor |
| `PRESENCE_IN_DARKNESS` | 3 | Presence detector (only in darkness) |
| `TWILIGHT` | 4 | Twilight / dawn-dusk sensor |
| `MOTION` | 5 | Motion detector |
| `MOTION_IN_DARKNESS` | 6 | Motion detector (only in darkness) |
| `SMOKE` | 7 | Smoke detector |
| `WIND` | 8 | Wind alarm |
| `RAIN` | 9 | Rain detector |
| `SUN_RADIATION` | 10 | Sun radiation / insolation sensor |
| `THERMOSTAT` | 11 | Thermostat contact |
| `BATTERY_LOW` | 12 | Battery low indicator |
| `WINDOW_OPEN` | 13 | Window open/close contact |
| `DOOR_OPEN` | 14 | Door open/close contact |
| `WINDOW_TILTED` | 15 | Window tilted (tilt position) |
| `GARAGE_DOOR_OPEN` | 16 | Garage door open/close |
| `SUN_PROTECTION` | 17 | Sun protection active signal |
| `FROST` | 18 | Frost alarm |
| `HEATING_SYSTEM_ENABLED` | 19 | Heating system enabled signal |
| `HEATING_CHANGE_OVER` | 20 | Heating/cooling changeover signal |
| `INITIALIZATION` | 21 | Device initialisation / startup indicator |
| `MALFUNCTION` | 22 | Malfunction / fault indicator |
| `SERVICE` | 23 | Service required indicator |

### 7.3 Button inputs

Button inputs implement a click-detection state machine with support
for single-tap, double-tap, hold, and multi-button combinations.  The
`button_type` determines the physical layout of the button element:

| `ButtonType` | Value | Physical layout |
|---|---|---|
| `UNDEFINED` | 0 | Not specified |
| `SINGLE_PUSHBUTTON` | 1 | One momentary pushbutton |
| `TWO_WAY_PUSHBUTTON` | 2 | Two-way rocker / up+down pair |
| `FOUR_WAY_NAVIGATION` | 3 | Four-direction pad (no centre) |
| `FOUR_WAY_WITH_CENTER` | 4 | Four-direction pad with centre button |
| `EIGHT_WAY_WITH_CENTER` | 5 | Eight-direction pad with centre button |
| `ON_OFF_SWITCH` | 6 | Toggle on/off switch (latching) |

A button's `group` determines its scene-control role:

- `group ≠ 8` — scene button: the dSS shows it in the scene assignment
  UI and it can call scenes in a zone/group
- `group = 8` — sensor-mode: the dSS treats it as a binary sensor
  input that can trigger automations

The click events generated by the detection state machine
(`ButtonClickType`) cover: single/double/triple/quadruple tip, hold
start/repeat/end, single/double/triple click, short-long, and
short-short-long combinations.

---

## 8. Model features — UI panel visibility

Model features are a set of named capability flags that tell the dSS
configurator which UI panels to show for a device.  They do not affect
runtime behaviour directly — only UI rendering.

Most features are **auto-derived** from the declared components before
the device is announced.  Key auto-derivation rules:

- Any output → `dontcare`, `blink`
- ON_OFF function → `outconfigswitch`, `impulseconfig`
- DIMMER / DIMMER_COLOR_TEMP / FULL_COLOR_DIMMER function → `dimtimeconfig`
- Grey shade output with slat channel → `shadebladeang`, `motiontimefins`
- Any binary input → `akmsensor` (`akminput` and `akmdelay` are not supported for VDC devices)
- Any button → `pushbutton`, `pushbadvanced`, `pushbdisabled`

Some features are **not tested** (can be set manually, VDC behavior unconfirmed):

| Feature | When to consider adding |
|---|---|
| `blinkconfig` | Blink pattern configuration (config may be stored on dSS/vdSM) |
| `outmodegeneric` | Joker device with selectable output mode — VDC support unclear |
| `customactivityconfig` | Custom activity/app configuration UI |
| `ftwtempcontrolventilationselect` | Display panel (SK-204) with temp + ventilation mode select |
| `customtransitiontime` | Per-scene transition time (no vdSD storage confirmed) |

**Several features are explicitly NOT supported** and will raise `ValueError` if passed
to `add_model_feature()` — including `outmode`, `outmodeswitch`, `ledauto`, `leddark`,
`dimmodeconfig`, `extradimmer`, `heatingoutmode`, `twowayconfig`, `pushbcombined`,
`consumptioneventled`, and others.  These features write hardware state via DS485 and
have no VDC write-back path, or relate to hardware capabilities with no API equivalent.

See `docs/model-features-auto-assignment.md` for the complete rule
reference, including the full list of not-tested optional and not-supported features.

---

## 9. Complex devices — states, events, properties, and actions

Most dSS devices fit into well-understood categories.  A light dimmer
dims a light; a blind actuator moves a shutter; a heating valve
regulates temperature.  Their capabilities are standardised, their
scene behaviour is automatic, and the dSS configurator knows exactly
which controls to show.

Many real-world integrations don't fit this mould.  Consider a
connected oven: it doesn't belong to any standard output group, it has
programs to start and stop, it reports whether its door is open and how
much time remains on the current program, and it should fire an event
when preheating is complete.  Or consider a custom home-automation
unit with several operating modes and a handful of specific commands —
again, no standard output channel covers that.  These are **complex
devices**: devices that have individual, application-specific
capabilities that need to be explicitly described and integrated.

The dSS provides four mechanisms for this:

### 9.1 What complex devices can expose

| Feature | What it is for |
|---|---|
| **States** | A named condition that the device is in at any given moment — door open/closed, program running/idle, mode active/standby. The dSS tracks state changes and automation rules can react when a state reaches a specific value. |
| **Events** | A one-shot signal that something happened — program finished, alarm triggered, user interaction detected. Events fire automation rules immediately when they occur. |
| **Properties** | Named values that are useful to display or read back but don't drive automation — remaining program time, current temperature setpoint, progress percentage. Can be read or written from the dSS app and API. |
| **Actions** | Named commands that the dSS or the user can invoke — start a program, activate standby, set an operating mode. Appear in the Activities tab of dSS add-on apps and can be called from automation scripts. |

States are for persistent conditions worth tracking in automation; events
are for discrete occurrences worth reacting to immediately; properties
are for read-back and display; actions are for triggering something on
the device.

### 9.2 Prerequisites

Two things must be configured before any of the above features become
accessible in the dSS ecosystem.

**On the VDC — enable live descriptions**

The parent VDC must declare `dynamic_definitions=True`:

```python
Vdc(
    ...,
    capabilities=VdcCapabilities(dynamic_definitions=True),
)
```

Without this flag the dSS does not ask the VDC for the names and
descriptions of states, events, actions, and properties at all.  It
falls back to whatever it has internally, which for most custom devices
is nothing — custom feature names won't appear anywhere in the
configurator.

**On the VdSD — announce a known GTIN**

The `oem_model_guid` field (`"gs1:(01)<13-digit EAN>"`) tells the dSS
which device type this is.  The dSS looks up that EAN in its system
database at announcement time and uses the result to decide two things:

- Whether the **Activities tab** is shown in add-on apps (Scene
  Responder, User Defined States, Timers) — it is completely hidden
  for devices the dSS does not recognise by GTIN
- Which **state names** are eligible for automation-condition evaluation
  — the dSS allocates slots only for state names defined in its system
  database for that GTIN

Event-triggered automation is the exception: events always fire
automation rules regardless of GTIN.  But the Activities tab and
state-condition automation both require a known GTIN.

### 9.3 GTIN — choosing the right device identity

#### The `2345678901234` general-purpose GTIN

For custom or freestyle devices that don't match any specific appliance
type, GTIN **`2345678901234`** is the recommended starting point.  It is
present in the dSS system database on all standard firmware
installations and immediately unlocks the Activities tab for the device.

What this GTIN provides:

- Activities tab visible in all dSS add-on apps
- Events and actions shown in the Activities UI with the names the VDC
  announces (when `dynamic_definitions=True` is set)
- Event-triggered automation works with whatever event names the VDC
  declares — the dSS fires the rule immediately when the event arrives

**The one limitation — state-condition automation:**  
This GTIN has no state definitions in the dSS system database, so
device states cannot be used in automation conditions ("when state X
equals Y").  State values are still visible in the dSS app and API for
display purposes, but automation cannot react to them conditionally.
The practical workaround is to use **events** as automation triggers
instead: raise an event whenever a meaningful state transition occurs
and build automation rules on those events.

#### Device-type template GTINs

If the integration target matches a recognised appliance category, the
dSS system database includes a set of pre-defined "Generic" device-type
GTINs.  Each one defines a complete set of state names with allowed
values, events, actions, and read-only properties.  Using one of these
GTINs enables full state-condition automation for the defined states —
the dSS will react to state changes by name, not just by event.

A few important points about working with template GTINs:

- **State names and their allowed values are fixed.**  They must be
  pushed exactly as defined (case-sensitive).  Extra state names that
  are not in the system database remain visible in the API but will
  never trigger automation conditions.
- **Event and action names can be presented differently** in the
  configurator by using `dynamic_definitions=True` and declaring your
  own descriptions — the VDC's names take over in the UI.  The
  underlying system-database names still exist, but users see yours.
  Avoid changing these without good reason: some dSS components,
  including the mobile application, reference the standard names
  directly.
- **Only use a template GTIN when the real appliance is absent.**  If
  the matching real product is connected to the same dSS, both will
  share one definition and conflict.

---

**Generic Coffeemaker — `7640156794076`**

| | Names |
|---|---|
| **States** | `OperationMode`: `ModeInactive` / `ModeReady` / `ModeRun` / `ModeFinished` / `ModeAborting` / `ModeActionRequired` / `ModeError` |
| | `PowerState`: `PowerOn` / `PowerStandby` |
| | `RemoteControl`: `RemoteControlActive` / `RemoteStartActive` / `RemoteControlErrorTC` |
| **Events** | `LocallyOperated`, `ProgramFinished`, `ProgramStarted` |
| **Actions** | `CaffeLatte`, `Cappuccino`, `Coffee`, `Espresso`, `EspressoMacchiato`, `LatteMacchiato`, `PowerOn`, `StandBy`, `Stop` |
| **Properties** | `ProgramName`, `ProgramProgress` (0–100 %), `RemainingProgramTime`, `BeanAmount`, `FillQuantity` (0–400 ml) |

---

**Generic Oven — `7640156794083`**

| | Names |
|---|---|
| **States** | `DoorState`: `DoorClosed` / `DoorOpen` / `DoorLocked` |
| | `OperationMode`: `ModeInactive` / `ModeReady` / `ModeRun` / `ModeFinished` / `ModeAborting` / `ModeDelayedStart` / `ModePause` / `ModeActionRequired` / `ModeError` |
| | `PowerState`: `PowerOn` / `PowerStandby` |
| | `RemoteControl`: `RemoteControlInactive` / `RemoteControlActive` / `RemoteStartActive` / `RemoteControlErrorTC` |
| **Events** | `AlarmClockElapsed`, `LocallyOperated`, `PreheatFinished`, `ProgramFinished`, `ProgramStarted` |
| **Actions** | `HotAir`, `PizzaSetting`, `PowerOn`, `Preheating`, `StandBy`, `Stop`, `StopIfNotTimed`, `TopBottomHeating` |
| **Properties** | `ProgramName`, `ProgramProgress`, `RemainingProgramTime`, `ElapsedProgramTime`, `TargetTemperature` (0–300 °C) |

---

**Generic Washing Machine — `7640156794090`**

| | Names |
|---|---|
| **States** | `DoorState`: `DoorClosed` / `DoorOpen` / `DoorLocked` |
| | `OperationMode`: `ModeInactive` / `ModeReady` / `ModeRun` / `ModeFinished` / `ModeAborting` / `ModeDelayedStart` / `ModePause` / `ModeActionRequired` / `ModeError` |
| | `RemoteControl`: `RemoteControlInactive` / `RemoteControlActive` / `RemoteStartActive` / `RemoteControlErrorTC` |
| **Events** | `LocallyOperated`, `ProgramFinished`, `ProgramStarted` |
| **Actions** | `Cotton`, `DelicatesSilk`, `EasyCare`, `Mix`, `Stop`, `Wool` |
| **Properties** | `ProgramName`, `ProgramProgress`, `RemainingProgramTime`, `Temperature`, `SpinSpeed` |

---

**Generic Dryer — `7640156794106`**

| | Names |
|---|---|
| **States** | `DoorState`: `DoorClosed` / `DoorOpen` / `DoorLocked` |
| | `OperationMode`: `ModeInactive` / `ModeReady` / `ModeRun` / `ModeFinished` / `ModeAborting` / `ModeDelayedStart` / `ModePause` / `ModeActionRequired` / `ModeError` |
| | `RemoteControl`: `RemoteControlInactive` / `RemoteControlActive` / `RemoteStartActive` / `RemoteControlErrorTC` |
| **Events** | `LocallyOperated`, `ProgramFinished`, `ProgramStarted` |
| **Actions** | `Cotton`, `Mix`, `Stop`, `Synthetic` |
| **Properties** | `ProgramName`, `ProgramProgress`, `RemainingProgramTime`, `DryingTarget` |

---

**Generic Dishwasher — `7640156794120`**

| | Names |
|---|---|
| **States** | `DoorState`: `DoorClosed` / `DoorOpen` |
| | `OperationMode`: `ModeInactive` / `ModeReady` / `ModeRun` / `ModeFinished` / `ModeAborting` / `ModeDelayedStart` / `ModeActionRequired` |
| | `PowerState`: `PowerOn` / `PowerOff` |
| | `RemoteControl`: `RemoteControlInactive` / `RemoteControlActive` / `RemoteStartActive` / `RemoteControlErrorTC` |
| **Events** | `ProgramAborted`, `ProgramFinished`, `ProgramStarted` |
| **Actions** | `Auto3545`, `Auto4565`, `Auto6575`, `Eco50`, `PowerOff`, `PowerOn`, `QuickWash45`, `Stop` |
| **Properties** | `ProgramName`, `ProgramProgress`, `RemainingProgramTime`, `DelayedStart` (0–1439 min) |

---

#### Without a known GTIN (not recommended for complex devices)

Announcing a Vdsd without an `oem_model_guid`, or with a GTIN that is
not in the dSS system database, means the dSS treats the device as
unrecognised.

What still works:

- State values, event names, and action descriptions are visible in the
  dSS app and JSON API — useful for monitoring and display
- Events still trigger automation rules immediately when fired —
  event-based automation is never blocked by the absence of a GTIN
- Actions can be called from scripts via the API directly

What does not work:

- The Activities tab in add-on apps is completely hidden — users cannot
  discover or interact with the device's events and actions from Scene
  Responder, User Defined States, or Timers
- State-condition automation is unavailable — the dSS will not react to
  state changes conditionally

For complex devices that are meant to integrate properly into the dSS
automation ecosystem, not providing a known GTIN significantly limits
what users can do.  Reserve the no-GTIN approach for pure
monitoring or sensor devices where the Activities tab is genuinely not
needed.

### 9.4 Choosing the primary group

Complex devices are commonly announced with `primary_group =
ColorGroup.WHITE` (9), which places them on the "Single Device" surface
in the configurator — a neutral area with no standard output behaviour
that suits devices which don't belong to any conventional dSS group.
An oven, a coffee machine, or a custom logic unit is a natural fit.

This is not a requirement.  States, events, properties, and actions
work for any primary group.  The right choice depends on whether the
device also has standard output behaviour:

- **Use WHITE** when the device has no standard controllable output and
  belongs to no recognised dSS group.
- **Use the matching colour class** when the device is an extension of a
  standard type.  A light fitting that additionally reports energy
  consumption and accepts a custom "activate preset" action should
  remain YELLOW — it keeps full scene handling, zone control, and group
  behaviour, and gains the complex-device features on top.

---

## 10. Operational lifecycle

```
startup
  └─ VdcHost.__init__() → load persisted state
  └─ host.start() → TCP server starts + DNS-SD announces

vdSM connects
  └─ hello handshake
  └─ auto-announce vDCs → auto-announce all devices
  └─ dSM queries getProperty for each device

runtime
  └─ sensor pushes: si.update_value(new_val)
  └─ binary input changes: bi.update_value(True/False)
  └─ output channel applied: on_channel_applied callback
  └─ scene called: output.call_scene() → on_channel_applied callback
  └─ state changes: st.update_value("active")
  └─ events: evt.raise_event()

vdSM disconnects (network drop / dSS restart)
  └─ session ends → announcement state reset
  └─ vdSM reconnects → full re-announcement cycle (automatic)

shutdown
  └─ host.stop() → flush → unannounce DNS-SD → close session → stop TCP
```

---

## 11. Persistence and restart behaviour

The YAML state file captures:
- VdcHost identity properties (name, model, dSUID)
- All vDC properties and capabilities
- All device/vdSD identity properties, zone assignment, model features
- Input/output configuration (channel types, sensor types, settings)
- Scene table (all stored scene values per device)
- Custom action definitions (user-created)
- Device property values (retained across restarts)

The following are **not** persisted and are always re-initialised at
announce time:
- Current sensor/binary input state values (pushed fresh after reconnect)
- Control values received from the dSS
- Dynamic actions (transient, application-defined)

---

## 12. Key constraints and gotchas

| Constraint | Explanation |
|---|---|
| **One session at a time** | The VdcHost accepts one vdSM connection. A new connection closes the previous one. |
| **announce() is final for structure** | Once a device is announced, add/remove vdSDs only via `device.update()` (vanish + re-announce). |
| **modelFeatures are auto-derived at announce time** | Call `derive_model_features()` explicitly if you need to add or remove features before announcing. Features set via `add_model_feature()` before the call are preserved. |
| **State automation requires GTIN** | Without a registered GTIN in the vDC DB, device states are API-visible but do not trigger dSS automation. |
| **`dynamic_definitions` must be True for complex devices** | Without it, the dSS ignores live state/event/action descriptions from the VDC. |
| **State name matching is exact and case-sensitive** | A state name pushed from the VDC must match the DB-registered name character-for-character. |
| **Device property changes do not trigger automation** | Use device states (with GTIN) or device events for automation triggers. |
| **Events fire automation regardless of GTIN** | The recommended trigger for scenarios where GTIN registration is not available. |
