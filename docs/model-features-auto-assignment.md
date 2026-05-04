# modelFeatures Reference

> Source: `pydsvdcapi` library — `Vdsd.derive_model_features()` in
> `src/pydsvdcapi/vdsd.py`.  
> UI/firmware analysis: `dss-configurator-ui-composition.md`.

---

## Overview

`modelFeatures` is a list of capability flags sent during device announcement
that tells the dSS configurator which UI panels and controls to render.

`derive_model_features()` inspects the fully configured `Vdsd` object and adds
flags automatically based on the declared components. It runs at announcement
time unless called explicitly first (in which case your manual
additions/removals are preserved).

Features fall into three categories:

1. **Supported** — auto-derived or manually addable with confirmed effect
2. **Not Tested** — optional, can be set manually; full behaviour unconfirmed
3. **Not Supported** — rejected with `ValueError`; no effect on TCP/IP VDC devices

---

## 1. Supported Features

These are automatically derived by `derive_model_features()` based on the
configured components.  All have a confirmed data path back to the vdSD.

### Output / Channel Rules

| Trigger | Features added | Configurator UI |
|---|---|---|
| Any output present | `dontcare` | Per-scene "retain current value" checkbox |
| Any output present | `blink` | Per-scene "blink effect" checkbox |
| Channel type in {1–12, 14–18, 22–24} | `transt` | Per-scene transition-time radio button (standard / slow) |
| `primaryGroup ≠ 2` (non-shade) | `outvalue8` | 8-bit "Edit Output Value" slider/input |
| `function == ON_OFF` | `outconfigswitch` | Switch output threshold configuration UI |
| `function == ON_OFF` | `impulseconfig` | "Impulse" tab in Device Properties for binary-output devices |
| Both channel types 2 (HUE) + 3 (SAT) **or** 1 (BRIGHTNESS) + 4 (COLOR_TEMP) | `outputchannels` | Additional channel controls in "Edit Output Values" (pre-requisite: `outvalue8`) |
| `function` in {DIMMER(1), DIMMER_COLOR_TEMP(3), FULL_COLOR_DIMMER(4)} | `dimtimeconfig` | Dim time settings (dimTimeUp / dimTimeDown) |
| Channel type 16 (HEATING_POWER) **or** `primaryGroup == 3` + `function == ON_OFF` | `pwmvalue` | PWM-mode indicator in "Edit Output Values" (pre-requisite: `outvalue8`) |
| Any ventilation channel (types 12, 13, 14, 15, 20, 21) | `ventconfig` | Ventilation speed/flap configuration UI |

### Grey / Shade Rules (primaryGroup == 2)

| Trigger | Features added | Configurator UI |
|---|---|---|
| `primaryGroup == 2` + any output | `shadeprops` | "Device Properties Shade" pop-up for positional timing |
| `primaryGroup == 2` + `function == POSITIONAL` | `shadeposition` | 16-bit position slider/input and up/down/increment/decrement buttons |
| POSITIONAL + channel type 9 or 10 (blade/slat) | `shadebladeang`, `motiontimefins` | Blade angle input/slider; blade motion timing in shade pop-up |
| `primaryGroup == 2` + any output | `locationconfig` | Direction/orientation dropdown in Device Properties |
| `primaryGroup == 2` + any output | `operationlock` | "Ignore operation lock for weather alarms" radio button (Advanced Settings) |
| `primaryGroup == 2` + output + channel type 9 or 10 | `windprotectionconfigblind` | Wind protection class for jalousie/blind (stored on dSS) |
| `primaryGroup == 2` + output + **no** channel 9/10 | `windprotectionconfigawning` | Wind protection class for awning/roller blind (stored on dSS) |

### Blue / Climate Rules (primaryGroup == 3)

| Trigger | Features added | Configurator UI |
|---|---|---|
| `primaryGroup == 3` | `heatinggroup` | "Heating Group" dropdown (heatingSystemCapability) |
| `primaryGroup == 3` | `heatingprops` | "Device Properties Climate" pop-up for valve/PWM settings |
| `primaryGroup == 3` + output | `valvetype` | "Attached terminal device" dropdown (heatingSystemType) |
| `primaryGroup == 3` + output | `extendedvalvetypes` | Extended valve type options in the terminal device dropdown |
| `primaryGroup == 3` + output + ventilation channel | `fcu` | Fan coil unit profile (airflow channels imply FCU/ventilation) |

### Sensor Rules

| Trigger | Features added | Configurator UI |
|---|---|---|
| Any sensor type in {14, 15, 16, 17} (ACTIVE_POWER, ELECTRIC_CURRENT, ENERGY_METER, APPARENT_POWER) | `consumption` | Energy monitoring / consumption events menu |
| Sensor type 1 (TEMPERATURE) + `primaryGroup == 3` | `temperatureoffset` | Temperature offset adjustment UI |

### Binary Input Rules

| Trigger | Features added | Configurator UI |
|---|---|---|
| Any binary input present | `akmsensor` | "Sensor Function" dropdown to configure the sensor type |
| Any binary input present | `akminput` | "Input" dropdown to configure sensor behaviour (standard / inverted) |
| Any binary input present | `akmdelay` | "Turn-on / Turn-off delay" dropdowns for delayed sensor response |

> **Note on `akminput` / `akmdelay`:** These UI controls have not been
> confirmed to store their values back to the vdSD (config may be stored on
> the dSS/vdSM side). They are auto-derived because the three AKM features
> always appear together on physical hardware.

### Button Rules

| Trigger | Features added | Configurator UI |
|---|---|---|
| Any button present | `pushbutton` | "Push Button" type dropdown (Room Push Button, etc.) |
| Any button present | `pushbadvanced` | Per-preset click-type config dropdowns + local priority / coming-home checkboxes |
| Any button present | `pushbdisabled` | Dialog for disabling unused buttons in end-user UIs |
| Button with `group ≠ 8` | `pushbarea` | Adds "Area Push-Button" entry to the button type dropdown |
| Button with `group ≠ 8` + `supports_local_key_mode` | `pushbdevice` | Adds "Device Push-Button" entry to the button type dropdown |
| Button with `group == 8` | `pushbsensor` | Adds "Sensor" entry to the button type dropdown |
| Button with `group == 8` | `highlevel` | Adds "App Button" entry to the button type dropdown |

### Primary-Group Rules

| Trigger | Features added | Configurator UI |
|---|---|---|
| `primaryGroup == 8` (BLACK/Joker) | `jokerconfig` | "Color Group" dropdown in Device Properties for re-assigning button / output group |

### Identification Rule

| Trigger | Features added | Configurator UI |
|---|---|---|
| `on_identify` callback registered | `identification` | "Identify" menu entry — sends Notify message to the VDC |

---

## How Auto-Derivation Interacts with Manual Configuration

```
construct Vdsd + add components
        │
        │   option A: implicit derivation
        ▼
announce()
  └─→ derive_model_features() runs automatically
  └─→ sends {derived features}

        │   option B: explicit control
        ▼
derive_model_features()              ← derive from current config
add_model_feature("blinkconfig")     ← add extras (NOT TESTED ok, not unsupported)
remove_model_feature("ventconfig")   ← suppress unwanted
        │
        ▼
announce()                           ← uses modified set; does NOT re-derive
```

Once `derive_model_features()` has been called (explicitly or via
`remove_model_feature()`), the `_features_derived` flag is set and
`announce()` skips automatic derivation.

---

## 2. Not-Tested Optional Features

These features can be added manually with `add_model_feature()` and are not
rejected by the library. Their UI effect has been partially identified, but
their full data path for TCP/IP VDC devices has not been confirmed.

Use them when you believe they apply to your device and test the result with
the dSS configurator.

| Feature | UI description | Status / notes |
|---|---|---|
| `blinkconfig` | Configuration menu for BLINK behaviour | No vdSD property stores the config — behaviour may be stored on dSS/vdSM side |
| `customtransitiontime` | Per-scene transition time configuration | No vdSD property stores the config — may be stored on dSS/vdSM; if confirmed working, consider raising a library issue to auto-derive it |
| `consumptiontimer` | Consumption timer / run-time UI panel | Not tested for TCP/IP VDC; auto-derivation removed until confirmed |
| `outmodegeneric` | Output mode selection with generic values (0–6) | Possibly applicable to VDC since values 0–6 map to `outputSettings/mode`; needs testing |
| `outmodeauto` | Adds "auto" mode to the output mode selector | Unknown if this enables/disables any VDC-accessible UI; not documented |
| `jokertempcontrol` | Joker/Black device with temperature-controlled output | Not tested for VDC |
| `umvrelay` | "Relay Function" dropdown to configure relay/output interplay | May be relevant only if device has multiple dS-UIDs with combined relay; config path unclear |
| `ftwtempcontrolventilationselect` | Display panel combined temperature control + ventilation mode selector | Hardware-specific; applies to FTW/SK204 physical panels — not tested for VDC |
| `setumr200config` | Hardware-specific UMR200 configuration | Not tested for VDC |
| `apartmentapplication` | Apartment application integration | Not tested; dSS firmware injects this for physical hardware based on FunctionID |
| `customactivityconfig` | Custom activity / app configuration UI | Not tested — needs evaluation whether configurator UI extensions can call custom activities |

---

## 3. Not-Supported Features

The following features are **rejected with `ValueError`** when passed to
`add_model_feature()`. They will also never be auto-derived.

Two root causes explain why they cannot work on TCP/IP VDC devices:

**A — Output-mode selectors write via DS485, not via VDC:**  
The configurator UI calls `setDeviceConfig(CfgClassFunction, CfgFunction_Mode, value)`
which sends the selection over the DS485 bus and stores it in the dSS device
model (`m_OutputMode`). **No `setVdcProperty()` call is made.** The value is
never forwarded to the VDC, which neither receives the selection nor can act
on it.

**B — Hardware-only features with no VDC write-back path:**  
These features control physical hardware capabilities (LED indicators, dimmer
hardware type, TKM button hardware) that have no corresponding VDC property or
API interaction.

| Feature | Why not supported |
|---|---|
| `outmode` | **(A)** Full dimmer mode set (dimmer / soft-dimmer / switch / disabled) — UI writes via DS485 `CfgFunction_Mode`; VDC devices use `outputSettings/mode` instead |
| `outmodeswitch` | **(A)** Switch-only variant of `outmode` (switched / disabled) — same DS485-only path |
| `heatingoutmode` | **(A)** Heating valve mode (switched / PWM / disabled) — same DS485-only path; dSS only writes `activeCoolingMode` back to VDC |
| `umroutmode` | **(A)** UMR200 special modes (2-phase / 3-phase / bipolar / temp-control) — same DS485-only path; UMR200 is always a physical bus device |
| `extradimmer` | **(A)** UMV200/UMV210 additional dimmer circuit (relay + dimmer combo) — hardware-specific DS485 path; for VDC, declare separate output channels instead |
| `optypeconfig` | **(A)** Dropdown for "Switched" / "Swiped" / "PowerSafe" output modes — changes DS485 `m_OutputMode`; these mode IDs have no VDC equivalent |
| `outmodetempcontrol` | **(A)** Temperature-control output modes (regulation PWM=64, regulation switch=65) — DS485-only path |
| `outmodeenoceanvalve` | **(A)** EnOcean valve output mode — DS485-only; additionally injected by dSS firmware for specific physical devices |
| `ledauto` | **(B)** "LED Mode" radio button (Auto / Off) — device LED is not API-controlled; no vdSD property reflects the state |
| `leddark` | **(B)** "LED Mode" radio button (On / Dark / Off) — same reason as `ledauto` |
| `dimmodeconfig` | **(B)** Dimmer hardware type selection (RMS / trailing-edge / etc.) — relates to physical dimmer hardware capability; VDC devices do not receive this information and cannot handle these settings |
| `consumptioneventled` | **(B)** LED indicator on consumption threshold events — controls a hardware LED on the end device; no VDC parameter handles this |
| `twowayconfig` | **(B)** Two-way push-button pairing UI — configures `buttonType` which is **read-only** in the VDC protocol (`ButtonDescription/buttonType`); the value does not align with the UI options and is hardware-specific to physical TKM devices |
| `pushbcombined` | **(B)** "Button Function" dropdown for multi-contact buttons — same reason as `twowayconfig`; `buttonType` is read-only and this feature is tied to physical TKM hardware |
| `ftwdisplaysettings` | **(B)** FTW display panel settings (brightness, contrast) — hardware-specific to physical SK204/FTW display panels; no VDC equivalent |
| `ftwbacklighttimeout` | **(B)** FTW display panel backlight timeout — same hardware-specific reason |
| `grkl387workaround` | **(B)** Hardware workaround for specific KL 0x387 firmware bug — injected by dSS firmware for physical KL devices; meaningless for VDC |

---

## Recommended Feature Sets by Device Type

### Yellow — Dimmable Light

```python
device = Vdsd(primary_group=ColorGroup.YELLOW, ...)
output = Output(default_group=ColorClass.LIGHTS, active_group=ColorClass.LIGHTS,
                groups={ColorClass.LIGHTS}, function=OutputFunction.DIMMER)
device.set_output(output)
# Auto-derived: dontcare, blink, transt, outvalue8, dimtimeconfig
```

### Yellow — RGB Full-Colour Light

```python
device = Vdsd(primary_group=ColorGroup.YELLOW, ...)
output = Output(default_group=ColorClass.LIGHTS, active_group=ColorClass.LIGHTS,
                groups={ColorClass.LIGHTS}, function=OutputFunction.FULL_COLOR_DIMMER)
# Auto-derived: dontcare, blink, transt, outvalue8, outputchannels, dimtimeconfig
```

### Yellow — Switched Light

```python
device = Vdsd(primary_group=ColorGroup.YELLOW, ...)
output = Output(default_group=ColorClass.LIGHTS, active_group=ColorClass.LIGHTS,
                groups={ColorClass.LIGHTS}, function=OutputFunction.ON_OFF)
device.set_output(output)
# Auto-derived: dontcare, blink, outvalue8, outconfigswitch, impulseconfig
```

### Grey — Jalousie / Venetian Blind

```python
device = Vdsd(primary_group=ColorGroup.GREY, ...)
output = Output(default_group=ColorClass.BLINDS, active_group=ColorClass.BLINDS,
                groups={ColorClass.BLINDS}, function=OutputFunction.POSITIONAL)
output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
output.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
device.set_output(output)
# Auto-derived: dontcare, blink, shadeprops, shadeposition, shadebladeang,
#               motiontimefins, locationconfig, operationlock,
#               windprotectionconfigblind
```

### Grey — Roller Shutter / Awning

```python
device = Vdsd(primary_group=ColorGroup.GREY, ...)
output = Output(default_group=ColorClass.BLINDS, active_group=ColorClass.BLINDS,
                groups={ColorClass.BLINDS}, function=OutputFunction.POSITIONAL)
output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
device.set_output(output)
# Auto-derived: dontcare, blink, shadeprops, shadeposition, locationconfig,
#               operationlock, windprotectionconfigawning
```

### Blue — Heating Valve (ON/OFF)

```python
device = Vdsd(primary_group=ColorGroup.BLUE, ...)
output = Output(default_group=ColorClass.HEATING, active_group=ColorClass.HEATING,
                groups={ColorClass.HEATING}, function=OutputFunction.ON_OFF)
device.set_output(output)
# Auto-derived: dontcare, blink, outvalue8, pwmvalue, outconfigswitch, impulseconfig,
#               heatingprops, heatinggroup, valvetype, extendedvalvetypes
```

### Blue — Room Temperature Controller

```python
device = Vdsd(primary_group=ColorGroup.BLUE, ...)
device.add_sensor_input(SensorInput(sensor_type=SensorType.TEMPERATURE, ...))
# Auto-derived: heatingprops, heatinggroup, temperatureoffset
# Optional (not tested) for display panel devices:
device.add_model_feature("ftwtempcontrolventilationselect")
```

### Blue — Ventilation / Fan Coil Unit

```python
device = Vdsd(primary_group=ColorGroup.BLUE, ...)
output = Output(default_group=ColorClass.VENTILATION, active_group=ColorClass.VENTILATION,
                groups={ColorClass.VENTILATION}, function=OutputFunction.POSITIONAL)
output.add_channel(OutputChannelType.AIR_FLOW_INTENSITY)
device.set_output(output)
# Auto-derived: dontcare, blink, transt, outvalue8, ventconfig,
#               heatingprops, heatinggroup, valvetype, extendedvalvetypes, fcu
```

### Black — Joker with Power Meter

```python
device = Vdsd(primary_group=ColorGroup.BLACK, ...)
output = Output(default_group=ColorClass.JOKER, active_group=ColorClass.JOKER,
                groups={ColorClass.JOKER}, function=OutputFunction.ON_OFF)
device.set_output(output)
device.add_sensor_input(SensorInput(sensor_type=SensorType.ACTIVE_POWER, ...))
device.add_sensor_input(SensorInput(sensor_type=SensorType.ENERGY_METER, ...))
# Auto-derived: dontcare, blink, outvalue8, outconfigswitch, impulseconfig,
#               jokerconfig, consumption
```
