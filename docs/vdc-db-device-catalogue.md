# vdc-db Device Catalogue

This document lists all device types registered in the dSS `vdc-db.sql` database
that are relevant for VDC implementations.  For each device the table shows which
**States**, **Properties**, **Actions**, and **Events** a VDC must implement in
order for the dSS to present the full integration experience.

## Background: dSS UI Architecture and the Role of the GTIN

### The dSS Configurator UI

The dSS Configurator presents devices through several distinct views.  Understanding
which view is driven by which data source is essential for knowing what a VDC
implementation actually needs to provide.

#### Hardware Tab

The Hardware tab shows all announced devices and offers device-level configuration.
The specific menus and controls available here are entirely governed by the device's
**`modelFeatures`** set:

- General device properties and settings (affects `*Settings*` properties that
  are write-enabled on the vdSD).
- Colour-group-specific setting menus (e.g. heating valve type, shade position).
- For devices with an output: a control to adjust the current output value.  The
  exact UI widget is derived from `modelFeatures` — a simple dimmer slider for a
  1-channel light, a colour picker for an RGB light, dual sliders (position +
  blade angle) for a blind with fins, etc.
- For sensors and binary inputs: the last reported value.
- For outputs: output mode and input mode configuration.

The Hardware tab has **no awareness** of SingleDevice states, properties, events,
or actions.  Those are not surfaced here at all.

#### System Tab / Property Tree

The System tab exposes the full dSS property tree, including the complete device
configuration subtree for every announced device.  This is the view where:

- The `hasActions` flag is visible per device (set from the database at scan time).
- States loaded from the database (`callGetStatesBase`) appear as `State` objects
  under `/usr/states/dev.<dsuid>.<name>` — even if the VDC has not yet pushed any
  runtime value for them (they exist with `State_Invalid` value until the VDC
  pushes a matching update).
- States from a VDC that has **no** database row for that GTIN/name are not
  visible here at all — push notifications only update pre-existing `State` objects,
  they cannot create new ones.

**Important:** Actions and Events are **not** part of the property tree at all —
neither for database-defined devices nor for custom VDC devices.  They cannot be
inspected in this view.

#### Apps: Scene Responder and User-Defined Actions

The primary surface for automation and logic in dSS is the **Apps** layer, in
particular the **Scene Responder** and **User-Defined Actions** apps.  These
allow building automations by reacting to things that happen in the system and
applying conditions.  The four feature types — States, Properties, Actions, Events —
appear in these apps as follows:

| Feature type | Appears as automation trigger? | Appears as automation condition? | Notes |
|---|---|---|---|
| **Events** | ✅ VDC's own names | ✅ | Requires `hasActionInterface = true` (GTIN with ≥1 action or event DB row) |
| **Actions** | ✅ VDC's own names | ✅ | Same `hasActionInterface` flag |
| **States** | ⚠️ Visible in picker, evaluation fails | ⚠️ Visible in picker, evaluation fails | Requires GTIN with ≥1 DB state row + `dynamicDefinitions=True`; see below |
| **Properties** | ❌ | ❌ | Not exposed to the automation layer |

### How States Work — Four Independent Mechanisms

States are the most complex feature type because they involve four separate
code paths in dSS, each driven by different data sources.

#### Mechanism 1 — Device appears in the "has states" list

The automation app first enumerates which devices have any states at all by
reading `/usr/states/`.  A device only appears in this list if `initStates()`
allocated at least one `State` object for it at scan time — which only happens
when the device's GTIN has rows in `callGetStatesBase`.

> **Path naming note:** Despite the `/usr/` prefix, `/usr/states/` is _not_ the
> user-defined-state (UDS/BDZ) path.  It is the general apartment-scoped registry
> for `StateType_Device`, `StateType_Group`, `StateType_Service`,
> `StateType_Circuit`, and `StateType_Apartment` — verified in
> `src/model/state.cpp:publishToPropertyTree()`.  
> User-Defined States live at the separate path
> `/usr/addon-states/system-addon-user-defined-states/` (`StateType_Script`).

**Requirement:** GTIN must have ≥ 1 row in `callGetStatesBase`.

#### Mechanism 2 — State names shown in the picker (conditions and triggers)

Once a device is in the list, the app calls `device/getInfo?filter=stateDesc`
which resolves through `DeviceInfo::getStateDescriptions()`.  The source depends
on the VDC's `dynamicDefinitions` capability:

- **`dynamicDefinitions=False`** (e.g. official product VDC addons) → falls back
  to the DB state definitions for the GTIN → shows the GTIN's exact state names.
- **`dynamicDefinitions=True`** (pydsvdcapi default) → queries the VDC's own
  `deviceStateDescriptions` property → shows the VDC's own custom state names,
  completely overriding any DB content.

With `dynamicDefinitions=True` and any GTIN that has ≥ 1 DB state row, the
**VDC's own state names** (`DeviceState` definitions) appear in both the trigger
picker and the condition picker — confirmed by live testing with GTIN
`1234567890123` and VDC-defined state `pyVDC_State`.

#### Mechanism 3 — State change fires as an automation trigger

When a VDC pushes a state change via `VDC_SEND_PUSH_NOTIFICATION` (`deviceStates`
payload), `modelmaintenance.cpp::onVdceEvent` calls
`raiseEvent(createDeviceStateEvent(device, name, value))` — a `DeviceStateEvent`
dSS event carrying the state name and new value.  This event path is **completely
independent of `/usr/states/`** and fires for any VDC-pushed state update
regardless of whether that state name was pre-registered in the DB.

**Result:** Custom VDC state names work as triggers the moment a value is pushed.

#### Mechanism 4 — Condition and trigger evaluation at runtime

This is the **unresolved gap**.  When an automation rule evaluates a state
condition or a state-based trigger, the dSS reads from `/usr/states/` using the
`"states"` condition key.  This path is **not** affected by `dynamicDefinitions`
— it only knows the states that `initStates()` pre-allocated from the DB at
scan time.

For GTIN `1234567890123`, that means `/usr/states/` contains `dummyState`
(options: `d` / `mm` / `u` / `y`) and nothing else.  The VDC-defined names
`pyVDC_State` and `pyVDC_Mode` have no entry in `/usr/states/` — so no
 automation rule evaluating `pyVDC_State == running` will ever match, even
though the Hardware tab displays the pushed values correctly.

> **Why the Hardware tab works but automation does not:**  
> The VDC push notification (`deviceStates` payload) updates `m_data->states`
> inside the device model — the data shown in the Hardware tab status column.
> It does **not** write to `/usr/states/`.  Automation evaluation reads
> `/usr/states/`; the Hardware tab reads `m_data->states`.  These are two
> completely separate collections.

The condition and trigger pickers correctly show the VDC state names (mechanism 2),
and `DeviceStateEvent` does fire on every push (mechanism 3), but the value
check inside the automation rule always fails because the state does not exist
in `/usr/states/`.

**Observed Sonos GTIN behaviour:**
A custom VDC using the Sonos GTIN (`7640156794625`) with `dynamicDefinitions=True`
and its own (non-Sonos) state names will:
- Appear in the automation device list ✅ (the 6 Sonos DB slots in `/usr/states/`)
- Show the VDC's own state names in the condition and trigger pickers ✅ (dynamicDefs)
- Fire `DeviceStateEvent` correctly ✅
- Never match an automation trigger or condition ❌ (no `/usr/states/` entry for VDC names)

### Summary: What a GTIN Actually Unlocks

| GTIN has … | Effect |
|---|---|
| Any row in `callGetActionsBase` or `callGetEventsBase` | `hasActionInterface = true` → actions and events from the VDC are shown as triggers in automation apps |
| Rows in `callGetStatesBase` | Pre-allocates `StateType_Device` slots in `/usr/states/`, making the device appear in the automation "has states" list. With `dynamicDefinitions=True` the VDC's own state names appear in the condition and trigger pickers (visible only); actual evaluation reads `/usr/states/` which only contains the DB-allocated names — automation rules based on custom VDC state names never match. |
| Rows in `callGetPropertiesBase` | Property descriptions loaded; with `dynamicDefinitions=True` the VDC's own property descriptions are shown instead |
| `template_id = 0` with no state/action rows | Only the basic `hasActionInterface` eligibility check; no state slots allocated, so the device never appears in the automation state picker |

To be recognised as a specific product a vdSD sets:

```python
vdsd.oem_model_guid = "gs1:(01)<GTIN>"  # 13-digit GTIN without spaces
```

---

## How to Read the Tables

- **GTIN** — the 13-digit GS1 GTIN.  For template families the generic/representative
  device GTIN is listed; a note shows how many device variants share the same
  template.
- **States** — names from `callGetStatesBase`.  These are pre-allocated in the dSS
  state registry at scan time and become available as **automation conditions**.
  The VDC must push runtime values using these exact names for the slots to be
  populated; otherwise the list appears empty in the UI.
- **Properties** — names from `callGetPropertiesBase`; readable and (where write-
  enabled) settable from the System tab property tree.
- **Actions** — command IDs from `callGetActionsBase`; enable the `hasActionInterface`
  flag and appear as **automation triggers** in Scene Responder / User-Defined Actions.
- **Events** — names from `callGetEventsBase`; also contribute to `hasActionInterface`
  and appear as **automation triggers**.
- **—** means no entries of that type are registered in the database.

---

## Template Families

Devices in the same template family share an identical States / Properties /
Actions / Events contract.  For each family the contract is described once; all
known GTINs are then listed.  Any GTIN from the list can be used in `oemModelGuid`
to activate that contract.

### BSH / Siemens — Coffee Maker (7 variants)

**States:** OperationMode · PowerState · RemoteControl  
**Properties:** BeanAmount · FillQuantity · ProgramName · ProgramProgress · RemainingProgramTime  
**Actions:** CaffeLatte · Cappuccino · Coffee · Espresso · EspressoMacchiato · LatteMacchiato · PowerOn · StandBy · Stop  
**Events:** LocallyOperated · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794137` | Bosch Coffee Maker CTL636EB6 |
| `7640156794182` | Bosch Coffee Maker CTL636ES6 |
| `7640156794144` | Coffee Maker (generic) |
| `7640156794076` | Generic Coffeemaker |
| `7640156792096` | Siemens Coffee Maker CT636LES6 |
| `7640156792898` | Siemens Coffee Maker CT836LEB6 |
| `7640156792102` | Siemens Coffee Maker EQ.9 connect s900 |

---

### BSH — Cooktop (3 variants)

**States:** OperationMode · PowerState · RemoteControl  
**Properties:** —  
**Actions:** —  
**Events:** AlarmClockElapsed · LocallyOperated · PreheatFinished · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794267` | Bosch Cooktop PXY875KW1E |
| `7640156794298` | Bosch Generic Cooktop |
| `7640156794311` | Siemens Generic Cooktop |

---

### BSH / Siemens — Dishwasher (16 variants)

**States:** DoorState · OperationMode · PowerState · RemoteControl  
**Properties:** DelayedStart · ProgramName · ProgramProgress · RemainingProgramTime  
**Actions:** Auto3545 · Auto4565 · Auto6575 · Eco50 · PowerOff · PowerOn · QuickWash45 · Stop  
**Events:** ProgramAborted · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794243` | Bosch Dishwasher SMV88TX16D |
| `7640156794250` | Bosch Generic Dishwasher |
| `7640156794120` | Generic Dishwasher |
| `7640156793420` | SN278I36TE |
| `7640156793390` | SN578S36TE |
| `7640156792829` | Siemens Dishwasher |
| `7640156793413` | Siemens Dishwasher SN478S36TE |
| `7640156793352` | Siemens Dishwasher SN658X06PE |
| `7640156793314` | Siemens Dishwasher SN658X16PE |
| `7640156793307` | Siemens Dishwasher SN678X16TD |
| `7640156793406` | Siemens Dishwasher SX558S06TE |
| `7640156793345` | Siemens Dishwasher SX658X06TE |
| `7640156793369` | Siemens Dishwasher SX678X36TE |
| `7640156793338` | Siemens Dishwasher SX758X06TE |
| `7640156793901` | Siemens Dishwasher SX778D16TE |
| `7640156793321` | Siemens Dishwasher SX858D06PE |

---

### BSH / Siemens — Dryer (5 variants)

**States:** DoorState · OperationMode · RemoteControl  
**Properties:** DryingTarget · ProgramName · ProgramProgress · RemainingProgramTime  
**Actions:** Cotton · Mix · Stop · Synthetic  
**Events:** LocallyOperated · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794281` | Bosch Generic Dryer |
| `7640156794106` | Generic Dryer |
| `7640156792805` | Siemens Dryer |
| `7640156793154` | Siemens Dryer WT7UH641 |
| `7640156793161` | Siemens Dryer WT7YH701 |

---

### BSH / Siemens — Fridge / Fridge-Freezer (16 variants)

**States:** DoorState  
**Properties:** FreezerSuperMode · FreezerTargetTemperature · FridgeSuperMode · FridgeTargetTemperature  
**Actions:** CancelFreezerSuperMode · CancelFridgeSuperMode · SetFreezerSuperMode · SetFridgeSuperMode  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156794229` | Bosch Fridge-Freezer KGN56HI3P |
| `7640156794236` | Bosch Generic Fridge |
| `7640156794113` | Generic Refrigerator |
| `7640156792812` | Siemens Fridge |
| `7640156793291` | Siemens Fridge KA92DAI30 |
| `7640156793284` | Siemens Fridge KA92DSB30 |
| `7640156793260` | Siemens Fridge KG36NAI45 |
| `7640156793208` | Siemens Fridge KG36NHI32 |
| `7640156793246` | Siemens Fridge KG39FPB45 |
| `7640156793239` | Siemens Fridge KG39FPI45 |
| `7640156793215` | Siemens Fridge KG39FSB45 |
| `7640156793222` | Siemens Fridge KG39FSW45 |
| `7640156793253` | Siemens Fridge KG39NAI45 |
| `7640156793192` | Siemens Fridge KG56FPI40 |
| `7640156793185` | Siemens Fridge KG56FSB40 |
| `7640156793178` | Siemens Fridge KI86SHD40 |

---

### BSH — Hood (3 variants)

**States:** OperationMode · PowerState · RemoteControl  
**Properties:** ElapsedProgramTime · ProgramName · ProgramProgress · RemainingProgramTime  
**Actions:** ActAutomaticMode · ActFanIntense1 · ActFanIntense2 · ActFanLevel1 · ActFanLevel2 · ActFanLevel3 · ActFanRunOn · PowerOff  
**Events:** LocalyOperated · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794304` | Bosch Generic Hood |
| `7640156794199` | Bosch Hood DWF97RV60 |
| `7640156794328` | Siemens Generic Hood |

---

### BSH / Siemens — Oven (19 variants)

**States:** DoorState · OperationMode · PowerState · RemoteControl  
**Properties:** ElapsedProgramTime · ProgramName · ProgramProgress · RemainingProgramTime · TargetTemperature  
**Actions:** HotAir · PizzaSetting · PowerOn · Preheating · StandBy · Stop · StopIfNotTimed · TopBottomHeating  
**Events:** AlarmClockElapsed · LocallyOperated · PreheatFinished · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794212` | Bosch Generic Oven |
| `7640156794205` | Bosch Oven HNG6764S6 |
| `7640156794083` | Generic Oven |
| `7640156793895` | Siemens Oven CM676G0S6 |
| `7640156793048` | Siemens Oven CM836GPB6 |
| `7640156792959` | Siemens Oven CN678G4S6 |
| `7640156792942` | Siemens Oven CN878G4S6 |
| `7640156792966` | Siemens Oven CS658GRS6 |
| `7640156792980` | Siemens Oven HB678GBS6 |
| `7640156793017` | Siemens Oven HB836GVS6 |
| `7640156793000` | Siemens Oven HB876G8S6 |
| `7640156792973` | Siemens Oven HM638GRS6 |
| `7640156792997` | Siemens Oven HM676G0S6 |
| `7640156793031` | Siemens Oven HM836GPB6 |
| `7640156793024` | Siemens Oven HM876G2B6 |
| `7640156792928` | Siemens Oven HN678G4S6 |
| `7640156792904` | Siemens Oven HN878G4S6 |
| `7640156792935` | Siemens Oven HS658GXS6 |
| `7640156792911` | Siemens Oven HS858GXS6 |

---

### BSH / Siemens — Washer (13 variants)

**States:** DoorState · OperationMode · RemoteControl  
**Properties:** ProgramName · ProgramProgress · RemainingProgramTime · SpinSpeed · Temperature  
**Actions:** Cotton · DelicatesSilk · EasyCare · Mix · Stop · Wool  
**Events:** LocallyOperated · ProgramFinished · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156794274` | Bosch Generic Washing Machine |
| `7640156794090` | Generic Washing Machine |
| `7640156792799` | Siemens Washer |
| `7640156793062` | Siemens Washer WM4UH641 |
| `7640156793116` | Siemens Washer WM4YH741 |
| `7640156793147` | Siemens Washer WM4YH790 |
| `7640156793109` | Siemens Washer WM4YH7W0 |
| `7640156793086` | Siemens Washer WM6YH740 |
| `7640156793093` | Siemens Washer WM6YH741 |
| `7640156793123` | Siemens Washer WM6YH790 |
| `7640156793055` | Siemens Washer WM6YH840 |
| `7640156793079` | Siemens Washer WM6YH841 |
| `7640156793734` | Siemens Washer WM6YH891 |

---

### Doorbird — Video Door Station (15 variants)

**States:** —  
**Properties:** —  
**Actions:** ActDoorUnlock · ActIrLightOn · ActSwitchRelay2  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156794038` | BirdGuard B101 |
| `7640156794519` | BirdGuard B10x |
| `7640156793918` | DoorBird IP Video Door Station D101 |
| `7640156793925` | DoorBird IP Video Door Station D101S |
| `7640156794496` | DoorBird IP Video Door Station D10x |
| `7640156794021` | DoorBird IP Video Door Station D204 |
| `7640156794014` | DoorBird IP Video Door Station D20x |
| `7640156793987` | DoorBird IP Video Door Station D2101BV |
| `7640156793932` | DoorBird IP Video Door Station D2101V |
| `7640156793994` | DoorBird IP Video Door Station D2102BV |
| `7640156793949` | DoorBird IP Video Door Station D2102V |
| `7640156794007` | DoorBird IP Video Door Station D2103BV |
| `7640156793956` | DoorBird IP Video Door Station D2103V |
| `7640156794502` | DoorBird IP Video Door Station D21x |
| `7640156794588` | DoorBird IP Video Door Station Series D110x |

---

### Sonos (1 variant)

**States:** StatusInputMode · StatusMute · StatusOperationMode · StatusPlaybackModeRepeat · StatusPlaybackModeShuffle · StatusPlaybackType  
**Properties:** PropertyIpAddress · PropertyPlaybackArtist · PropertyPlaybackTitle · PropertySerialNumber  
**Actions:** ActionMute · ActionNextTrack · ActionPause · ActionPlay · ActionPreviousTrack · ActionUnmute  
**Events:** —

> **Note:** Using this GTIN with a VDC that does not push all 6 state names causes
> the state list to appear empty when drilled into (the DB creates the slots but
> the VDC must fill them with values under the exact same names).

| GTIN | Device Name |
|---|---|
| `7640156794625` | Sonos |

---

### Samsung — Vacuum Robot (2 variants)

**States:** StaOpMode · StaRemoteCtrl · StaSuckPwr  
**Properties:** —  
**Actions:** ActGoHome · ActSetPwr · ActStart · ActStop  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156793833` | VR10M7039WG |
| `7640156793826` | VR20M7079WD |

---

### V-ZUG — Adora (Dishwasher, 8 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentProgram · SwVersion  
**Actions:** Stop  
**Events:** EmptyingTankEnded · PowerSupplyInterrupted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramInterrupted · ProgramStarted · TopupSalt

| GTIN | Device Name |
|---|---|
| `7640156792416` | V-ZUG Adora 55 SL |
| `7640156792423` | V-ZUG Adora 55 SL |
| `7640156792461` | V-ZUG Adora 55 SL |
| `7640156792430` | V-ZUG Adora 60 SL |
| `7640156792447` | V-ZUG Adora 60 SL |
| `7640156792478` | V-ZUG Adora 60 SL |
| `7640156792454` | V-ZUG Adora 60 SLWP |
| `7640156794403` | V-ZUG Dishwasher |

---

### V-ZUG — Adora S (Washing Machine, 4 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentProgram · SwVersion · WaterHardness *(Adora SLQ additionally: ApiVersion)*  
**Actions:** Pause · SmartStart  
**Events:** LooseningUpStarted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramStarted

| GTIN | Device Name | Notes |
|---|---|---|
| `7640156792201` | V-ZUG Adora SL | base contract |
| `7640156791938` | V-ZUG Adora SLQ | + ApiVersion property |
| `7640156792218` | V-ZUG Adora SLQ WP | base contract |
| `7640156794380` | V-ZUG Adora Washing Machine | base contract |

---

### V-ZUG — Adora T (Dryer, 3 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentProgram · SwVersion  
**Actions:** SmartStart · Stop  
**Events:** CreaseGuardFinishes · PowerSupplyInterrupted · ProgramAborted · ProgramAbortedDueToError · ProgramFinished · ProgramInterrupted · ProgramStarted

| GTIN | Device Name |
|---|---|
| `7640156792225` | V-ZUG Adora TS WP |
| `7640156791921` | V-ZUG Adora TSLQ WP |
| `7640156794397` | VZUG Adora Dryer |

---

### V-ZUG — Combair (Oven, 9 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentFoodTemperature · CurrentProgram · CurrentTemperature · RemainingDuration · SetEndFoodTemperature · SetTemperature · SwVersion  
**Actions:** BottomHeat · Grill · GrillForcedConvection · HotAir · HotAirHumid · PizzaPlus · SmartStart · Stop · StopIfNotTimed · TopBottomHeat · TopBottomHeatHumid  
**Events:** IntroduceFood · PluginFoodProbe · ProgramAborted · ProgramFinished · ProgramStarted · RemoveFoodProbe · TimerFinished

| GTIN | Device Name |
|---|---|
| `7640156794366` | V-ZUG Combair |
| `7640156792294` | V-ZUG Combair SL |
| `7640156792232` | V-ZUG Combair SL |
| `7640156792249` | V-ZUG Combair SL |
| `7640156792263` | V-ZUG Combair SLP |
| `7640156792270` | V-ZUG Combair SLP |
| `7640156792256` | V-ZUG Combair XSL |
| `7640156792300` | V-ZUG Combair XSL |
| `7640156792287` | V-ZUG Combair XSLP |

---

### V-ZUG — Combair-Steam (Combi Oven with Steam, 4 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentFoodTemperature · CurrentProgram · CurrentTemperature · RemainingDuration · SetEndFoodTemperature · SetTemperature · SwVersion · WaterHardness  
**Actions:** BottomHeat · Grill · GrillForcedConvection · HotAir · HotAirHumid · HotAirWithSteaming · PizzaPlus · Regeneration · SmartStart · Steam · Stop · StopIfNotTimed · TopBottomHeat · TopBottomHeatHumid  
**Events:** CheckWaterInlet · InsertWaterTank · IntroduceFood · PluginFoodProbe · ProgramAborted · ProgramFinished · ProgramStarted · RefillWater · RemoveFoodProbe · TimerFinished

| GTIN | Device Name |
|---|---|
| `7640156792379` | V-ZUG Combair-Steam SL |
| `7640156792386` | V-ZUG Combair-Steam SL 60 |
| `7640156792393` | V-ZUG Combair-Steam SL 60 |
| `7640156794373` | V-ZUG Combi-Steam |

---

### V-ZUG — Combi-Steam (Steam Oven, 6 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentFoodTemperature · CurrentProgram · CurrentTemperature · RemainingDuration · SetEndFoodTemperature · SetTemperature · SwVersion · WaterHardness  
**Actions:** HotAir · HotAirHumid · HotAirWithSteaming · Regeneration · SmartStart · Steam · Stop · StopIfNotTimed  
**Events:** CheckWaterInlet · InsertWaterTank · IntroduceFood · PluginFoodProbe · ProgramAborted · ProgramFinished · ProgramStarted · RefillWater · RemoveFoodProbe · TimerFinished

| GTIN | Device Name |
|---|---|
| `7640156792317` | V-ZUG Combi-Steam HSL |
| `7640156792324` | V-ZUG Combi-Steam HSL 60 |
| `7640156792331` | V-ZUG Combi-Steam XSL 60 |
| `7640156792362` | V-ZUG Combi-Steam XSL 60 |
| `7640156792348` | V-ZUG Combi-Steam XSL 60 |
| `7640156792355` | V-ZUG Combi-Steam XSL 60 |

---

### V-ZUG — Cooktop (2 variants)

**States:** OperationMode · RemoteControl · StaPwrSetting\_Zone1 · StaPwrSetting\_Zone2 · StaPwrSetting\_Zone3 · StaPwrSetting\_Zone4 · StaPwrSetting\_Zone5 · StaPwrSetting\_Zone6 · SwStatus  
**Properties:** CurrentProgram · PropRemaingingTime\_Zone1 · PropRemaingingTime\_Zone2 · PropRemaingingTime\_Zone3 · PropRemaingingTime\_Zone4 · PropRemaingingTime\_Zone5 · PropRemaingingTime\_Zone6 · SwVersion  
**Actions:** —  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156794410` | V-ZUG Cooktop |
| `7640156793888` | V-ZUG GK11TIFK |

---

### V-ZUG — MSLQ (Microwave Combi Oven, 2 variants)

**States:** OperationMode · RemoteControl · SwStatus  
**Properties:** CurrentEndTime · CurrentFoodTemperature · CurrentProgram · CurrentTemperature · RemainingDuration · SetEndFoodTemperature · SetTemperature · SwVersion · WaterHardness  
**Actions:** BottomHeat · Grill · GrillForcedConvection · HotAir · HotAirHumid · HotAirWithSteaming · Microwave · PizzaPlus · PowerRegeneration · PowerSteam · Regeneration · SmartStart · Steam · Stop · StopIfNotTimed · TopBottomHeat · TopBottomHeatHumid  
**Events:** CheckWaterInlet · InsertWaterTank · IntroduceFood · PluginFoodProbe · ProgramAborted · ProgramFinished · ProgramStarted · RefillWater · RemoveFoodProbe · TimerFinished

| GTIN | Device Name |
|---|---|
| `7640156792409` | V-ZUG MSLQ |
| `7640156791914` | V-Zug MSLQ 60 |

---

### Dornbracht — Smart Water Devices (19 variants)

Most of the 19 water device variants share the same base contract.  The **Sensory
Sky** (`7640156792546`) has an extended contract with additional fragrance and
light controls.

**States (base — 18 variants):** OutChnSideSprayBtmState · OutChnSideSprayMidState · OutChnSideSprayTopState · StaAffusionPipe · StaBodySpray · StaHandShower · StaHeadSpray · StaLegSprayBack · StaLegSpraySide · StaMsgJets · StaOutlet · StaOutletLeft · StaOutletRight · StaWaterBarButtUpLeg · StaWaterBarLowLegFoot · StaWaterBarNeckBack · StatusDrain · StatusError · StatusOpMode  
**States (Sensory Sky only, additional):** StaColdWaterMist · StaRainCurtain · StatusShowerLight

**Properties (base):** PossibleMappings · PropCScenarioName · PropRemainingWaterAmount  
**Properties (Sensory Sky only, additional):** PropRemainingCounterFragrance1 · PropRemainingCounterFragrance2 · PropRemainingCounterFragrance3

**Actions (base):** ActionAffusionPipeOff · ActionAffusionPipeSettingOn · ActionDoseSetting · ActionDrainClose · ActionDrainOpen · ActionFillContainerSetting · ActionFillSetting · ActionFootBathMassageJetsSettingOn · ActionHandShowerOff · ActionHandShowerSettingOn · ActionLeftOutletSettingOn · ActionMakeScenarioColder · ActionMakeScenarioHotter · ActionMakeScenarioStronger · ActionMakeScenarioWeaker · ActionOutletSettingOn · ActionRightOutletSettingOn · ActionScenarioOff · ActionShowerOff · ActionShowerSettingOn · ActionWaterOff  
**Actions (Sensory Sky only, additional):** ActionFragrance1On · ActionFragrance2On · ActionFragrance3On · ActionFragranceOff · ActionShowerLightOff · ActionShowerLightOn

**Events (all variants):** EvFillingCompleted · EvTargetWaterTempReached · EvWaterTurnedOff · EvWaterTurnedOn

| GTIN | Device Name | Contract |
|---|---|---|
| `7640156792591` | Big Rain and Hand Shower | base |
| `7640156792553` | Comfort Shower | base |
| `7640156792560` | Comfort Shower with Leg Shower | base |
| `7640156792676` | Foot Bath | base |
| `7640156792669` | Kitchen | base |
| `7640156792577` | Leg Shower | base |
| `7640156792584` | Shower with 1 Outlet | base |
| `7640156792683` | Shower with 2 Outlets | base |
| `7640156793864` | Shower with 3 Outlets | base |
| `7640156794533` | Shower with 4 Outlets | base |
| `7640156792607` | Smart Set Bathtub | base |
| `7640156792652` | Smart Set Bidet | base |
| `7640156792744` | Vertical Shower | base |
| `7640156792614` | Washbasin 1 Outlet | base |
| `7640156792621` | Washbasin 1 Outlet and Foot Sensor | base |
| `7640156792638` | Washbasin 2 Outlets | base |
| `7640156792645` | Washbasin 2 Outlets and Foot Sensor | base |
| `7640156792737` | eUnit Horizontal Shower | base |
| `7640156792546` | Sensory Sky | **extended** |

---

## Individual Devices (No Template Family)

These devices each have a unique registration with no template siblings.

### Dormakaba — Door Lock

**States:** StatusDoorState  
**Properties:** —  
**Actions:** OpenDoor  
**Events:** DoorUnlockedKey1 · DoorUnlockedKey2 · DoorUnlockedKey3 · DoorUnlockedKey4 · DoorUnlockedKey5 · DoorUnlockedKey6 · DoorUnlockedKey7 · DoorUnlockedKey8 · DoorUnlockedKey9 · DoorUnlockedKey10

| GTIN | Device Name |
|---|---|
| `7640156793871` | Dormakaba Door Lock |

---

### Dornbracht — Standalone Water Devices

Two Dornbracht devices are registered outside the smart-water-devices template.

| GTIN | Device Name | States | Properties | Actions | Events |
|---|---|---|---|---|---|
| `7640156792089` | Dornbracht Shower Sensory Sky (standalone) | — | innerRingWaterCounter · innerRingWaterSession · outerRingWaterCounter · outerRingWaterSession | alloff · dose · fill · flow · off · on · stop · temperature | — |
| `7640156792119` | Dornbracht eUnit Kitchen | — | — | alloff · dose · fill · flow · off · on · stop · temperature | — |

---

### Logitech Harmony

**States:** OperationMode  
**Properties:** AvActivityName · NonAvActivityName  
**Actions:** PowerOffAvActivity · StopAllActivities  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156792072` | Logitech Harmony |

---

### Miele

All Miele devices are individually registered (no shared template).

| GTIN | Device Name | States | Properties | Actions | Events |
|---|---|---|---|---|---|
| `7640156793130` | Miele Dishwasher | DoorState · OperationMode · ProgramPhase · RemoteControlState | ProgramID · RemainingProgramTime · StartTime | ActionChangeDelayedStart · ActionStart · ActionStop | EvProgramFailure · EvProgramFinished · EvProgramStarted |
| `7640156793567` | Miele Hood | LightingStatus · OperationMode · RemoteControlState | HoodPower · ProgramID · RemainingProgramTime | ActionLightOff · ActionLightOn · ActionStop | EvProgramFailure |
| `7640156793376` | Miele Washing Machine | DoorState · OperationMode · ProgramPhase · RemoteControlState | ProgramID · RemainingProgramTime · SpinSpeed · StartTime · TargetTemperature | ActionChangeDelayedStart · ActionStart · ActionStop | EvProgramFailure · EvProgramFinished · EvProgramStarted |
| `7640156793277` | Miele Wine Cooler | DoorState · OperationMode · RemoteControlState | WineFridgeCurrentTemp · WineFridgeTargetTemp | ActionLightOff · ActionLightOn | EvProgramFailure |

---

### Netatmo Weather Devices

All Netatmo devices are weather/environment sensors with no actions or events.

| GTIN | Device Name | States | Properties |
|---|---|---|---|
| `7640156793741` | Netatmo Weather Station Indoor Base | StatusTempTrend | MeasurementTimestamp · SwVersion |
| `7640156793758` | Netatmo Weather Station Outdoor Module | StatusBattery · StatusPressureTrend · StatusTempTrend | MeasurementTimestamp · SwVersion |
| `7640156793765` | Netatmo Additional Indoor Module | StatusBattery · StatusTempTrend | MeasurementTimestamp · SwVersion |
| `7640156793772` | Netatmo Healthy Home Coach | StatusHealthIndex | MeasurementTimestamp · SwVersion |

---

### Panasonic TV

**States:** StaInputMode · StaMute · StaNotLevel · StaOpMode  
**Properties:** PropIp  
**Actions:** ActAlarm · ActDecrChn · ActDecrVol · ActDisableDoNotDisturb · ActDisableNotifications · ActDoorbell · ActEnableDoNotDisturb · ActFire · ActHail · ActIncrChn · ActIncrVol · ActMute · ActPanic · ActSetChn · ActSetInputApps · ActSetInputHDMI1 · ActSetInputMode · ActSetInputMyApps · ActSetInputTV · ActSetInputVideo1 · ActSetVol · ActTurnOff · ActTurnOn · ActUnmute  
**Events:** —

| GTIN | Device Name |
|---|---|
| `7640156794465` | Panasonic TV |

---

### Securiton SecuriSafe

**States:** armingPrevention · armingState  
**Properties:** —  
**Actions:** Alarm1 · Alarm2 · Alarm3 · Alarm4 · Alarm5 · Alarm6 · NoAlarm1 · NoAlarm2 · NoAlarm3 · NoAlarm4 · NoAlarm5 · NoAlarm6 · armExternal · armInternal  
**Events:** Alarm1 · Alarm2 · Alarm3 · Alarm4 · Alarm5 · Alarm6 · NoAlarm1 · NoAlarm2 · NoAlarm3 · NoAlarm4 · NoAlarm5 · NoAlarm6 · accessControl · disarmed · extArmed · extArmingPreventionPresent · intArmed · intArmingPreventionPresent · leavingControl

| GTIN | Device Name |
|---|---|
| `7640156794342` | Securiton SecuriSafe |

---

### Smarter iKettle

Two generations, each individually registered.

| GTIN | Device Name | States | Properties | Actions | Events |
|---|---|---|---|---|---|
| `7640156791945` | smarter iKettle 2.0 (vDC) | operation | currentTemperature · defaultcooldowntemperature · defaultkeepwarmtime · defaulttemperature · waterLevel | boilandcooldown · heat · stop | BabycoolingFinished · BabycoolingStarted · BoilingFinished · BoilingStarted · KeepWarm · KeepWarmAfterBabycooling · KeepwarmAborted · KettleAttached · KettleReleased |
| `7640156793710` | smarter iKettle 3.0 | operation | defaultcooldowntemperature · defaultkeepwarmtime · defaulttemperature · formulamode · targetcooldowntemperature · targetkeepwarmtime · targettemperature | boilandcooldown · heat · stop | BabyCoolingAbortedAndKettleReleased · BabycoolingAborted · BabycoolingFinished · BabycoolingStarted · BoilingAborted · BoilingAbortedAndKettleReleased · BoilingFinished · BoilingStarted · KeepWarm · KeepWarmAbortedAndKettleReleased · KeepWarmAfterBabycooling · KeepWarmAfterBoiling · KeepWarmFinished · KeepwarmAborted · KettleAttached · KettleReleased |

---

### Tielsa Liftmodule

Seven Liftmodule variants are individually registered.  The Bar and Table variants
share one contract; the TV and Spice-Rack share a different (simpler) one.

**Bar / Table / Basic contract:**  
States: CurrentPosition · OperationMode  
Properties: BottomHeight · DeviceType · LevelHeight · OffsetHeight · TopHeight  
Actions: MoveDown · MoveToHighest · MoveToLevel · MoveToLowest · MoveToPos · MoveUp · Stop  
Events: LevelReached · MaxPosReached · MinPosReached · MovingDown · MovingUp · PositionReached · SafetyProtectionTriggered · Stopped

**TV / Spice-Rack contract:**  
States: CurrentPosition · OperationMode  
Properties: DeviceType *(TV additionally: OffsetHeight)*  
Actions: MoveToExtended · MoveToRetracted · Stop  
Events: ExtendedPosReached · MovingDown · MovingUp · RetractedPosReached · SafetyProtectionTriggered · Stopped

| GTIN | Device Name | Contract |
|---|---|---|
| `7640156792850` | Tielsa Liftmodule Basic | Bar/Table/Basic |
| `7640156792867` | Tielsa Liftmodule Bar 130 | Bar/Table/Basic |
| `7640156792874` | Tielsa Liftmodule Bar 207 | Bar/Table/Basic |
| `7640156792881` | Tielsa Liftmodule Bar 390 | Bar/Table/Basic |
| `7640156792539` | Tielsa Liftmodule Table 130 | Bar/Table/Basic |
| `7640156792690` | Tielsa Liftmodule Table 207 | Bar/Table/Basic |
| `7640156792706` | Tielsa Liftmodule Table 390 | Bar/Table/Basic |
| `7640156792713` | Tielsa Liftmodule TV | TV/Spice-Rack |
| `7640156792720` | Tielsa Liftmodule Spice-Rack | TV/Spice-Rack |
python examples/test_gtin_1234_dynamic.py --port 8444python examples/test_gtin_1234_dynamic.py --port 8444python examples/test_gtin_1234_dynamic.py --port 8444
---

## dSS Internal Test GTINs

Two GTINs in `vdc-db.sql` exist solely as internal test entries and are not
associated with any real product.  Both can be used during VDC development, but
they differ in what the dSS pre-allocates at scan time.

### `1234567890123` — RegressionTestDevice

> **Do not change** (dSS regression suite depends on its exact state/action/event set)

Registered as `RegressionTestDevice`, `template_id = 0`.  Has a full set of DB
entries covering states, actions, events, outputs, and properties — the dSS
regression tests verify behaviour against this exact definition.

**What the dSS pre-allocates for this GTIN:**
- 4 `dummyState` enum entries in `callGetStatesBase` → `dummyState` pre-allocated in `/usr/states/` and visible as an automation **condition** ✅
- Actions and events → `hasActionInterface = true`, triggers visible in automation apps ✅

**With `dynamicDefinitions=True` — confirmed by live test:**
The VDC's own `DeviceState` names (e.g. `pyVDC_State`) override the DB names in
the automation picker (mechanisms 1+2) and appear in both the trigger picker and
the condition picker.  State-change triggers fire correctly via `DeviceStateEvent`
(mechanism 3).  Condition *evaluation* (mechanism 4) still reads `/usr/states/`
which only has `dummyState` — a condition on `pyVDC_State` will never fire unless
the VDC pushes a state whose name exactly matches `dummyState`.

Because the regression suite depends on the exact `dummyState` definition, a VDC
using this GTIN must push a state named exactly `dummyState` if it wants condition
evaluation to work.  **Not recommended for custom VDC use.**

### `2345678901234` — FrameworkTestDeviceWithoutRegressionImpact

Registered as `FrameworkTestDeviceWithoutRegressionImpact`, `template_id = 0`.
Carries **no state definitions**, so no state slots are pre-allocated and no
automation conditions become available for this device type.  However it **has**
action and event rows — enough for `hasActionInterface()` to return `true`.

```python
vdsd.oem_model_guid = "gs1:(01)2345678901234"
```

This is the recommended value for custom VDC implementations: it enables
action/event triggers in the automation apps without locking you into any
pre-defined state contract.

**What works with this GTIN:**
- Actions defined via `deviceActionDescriptions` → visible as automation triggers ✅
- Events defined via `deviceEventDescriptions` → visible as automation triggers ✅
- States defined via `DeviceState` → pushed values visible in Hardware tab status column ✅
- States defined via `DeviceState` → visible in automation picker (with `dynamicDefinitions=True` + any GTIN with ≥1 DB state row) ⚠️
- States defined via `DeviceState` → fire/evaluate in automation conditions or triggers ❌

States pushed via `deviceStates` update `m_data->states` (shown in the Hardware
tab), but do **not** write to `/usr/states/`.  The automation layer reads
`/usr/states/` for condition and trigger evaluation — so conditions and triggers
based on VDC state names never match, even though the picker shows the names and
the Hardware tab shows the values correctly.

> **Note on the stored test actions/events:** The actions (`Cat0Act1`, `Cat1Act1`,
> …) and events (`Cat0Evt1`, …) stored for both GTINs are purely test artefacts.
> The dSS does not surface these stored entries directly — what appears in the
> automation apps comes from the `deviceActionDescriptions` / `deviceEventDescriptions`
> property responses that your VDC sends.  The stored rows exist only to make
> `hasActionInterface()` return `true`.

---

*Source: `data/vdc-db.sql` from the dSS mainline source tree, queried via the
`callGetStatesBase`, `callGetPropertiesBase`, `callGetActionsBase`, and
`callGetEventsBase` views.*
