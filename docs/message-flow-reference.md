# pydsvdcapi — Message Flow Reference

Complete reference for every vDC API message type: inbound (`vdSM → vDC`) and outbound (`vDC → vdSM`), including parameter mapping, state mutations, and response construction.

---

## Table of Contents

- [Architecture overview](#architecture-overview)
- [Session state machine](#session-state-machine)
- [Quick-reference table](#quick-reference-table)
- [Inbound messages (vdSM → vDC)](#inbound-messages-vdsm--vdc)
  - [VDSM_REQUEST_HELLO](#vdsm_request_hello)
  - [VDSM_SEND_PING](#vdsm_send_ping)
  - [VDSM_SEND_BYE](#vdsm_send_bye)
  - [VDSM_REQUEST_GET_PROPERTY](#vdsm_request_get_property)
  - [VDSM_REQUEST_SET_PROPERTY](#vdsm_request_set_property)
  - [VDSM_REQUEST_GENERIC_REQUEST](#vdsm_request_generic_request)
  - [VDSM_SEND_REMOVE](#vdsm_send_remove)
  - [VDSM_NOTIFICATION_CALL_SCENE](#vdsm_notification_call_scene)
  - [VDSM_NOTIFICATION_SAVE_SCENE](#vdsm_notification_save_scene)
  - [VDSM_NOTIFICATION_UNDO_SCENE](#vdsm_notification_undo_scene)
  - [VDSM_NOTIFICATION_SET_LOCAL_PRIO](#vdsm_notification_set_local_prio)
  - [VDSM_NOTIFICATION_CALL_MIN_SCENE](#vdsm_notification_call_min_scene)
  - [VDSM_NOTIFICATION_DIM_CHANNEL](#vdsm_notification_dim_channel)
  - [VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE](#vdsm_notification_set_output_channel_value)
  - [VDSM_NOTIFICATION_SET_CONTROL_VALUE](#vdsm_notification_set_control_value)
  - [VDSM_NOTIFICATION_IDENTIFY](#vdsm_notification_identify)
- [Outbound messages (vDC → vdSM)](#outbound-messages-vdc--vdsm)
  - [VDC_SEND_ANNOUNCE_VDC](#vdc_send_announce_vdc)
  - [VDC_SEND_ANNOUNCE_DEVICE](#vdc_send_announce_device)
  - [VDC_SEND_VANISH](#vdc_send_vanish)
  - [VDC_SEND_PUSH_NOTIFICATION — channel states](#vdc_send_push_notification--channel-states)
  - [VDC_SEND_PUSH_NOTIFICATION — output settings](#vdc_send_push_notification--output-settings)
  - [VDC_SEND_PUSH_NOTIFICATION — binary input state](#vdc_send_push_notification--binary-input-state)
  - [VDC_SEND_PUSH_NOTIFICATION — binary input settings](#vdc_send_push_notification--binary-input-settings)
  - [VDC_SEND_PUSH_NOTIFICATION — button input state](#vdc_send_push_notification--button-input-state)
  - [VDC_SEND_PUSH_NOTIFICATION — button input settings](#vdc_send_push_notification--button-input-settings)
  - [VDC_SEND_PUSH_NOTIFICATION — sensor input state](#vdc_send_push_notification--sensor-input-state)
  - [VDC_SEND_PUSH_NOTIFICATION — sensor input settings](#vdc_send_push_notification--sensor-input-settings)
  - [VDC_SEND_PUSH_NOTIFICATION — device state](#vdc_send_push_notification--device-state)
  - [VDC_SEND_PUSH_NOTIFICATION — device property](#vdc_send_push_notification--device-property)
  - [VDC_SEND_PUSH_NOTIFICATION — device event](#vdc_send_push_notification--device-event)
- [Response codes](#response-codes)

---

## Architecture overview

```
  vdSM (digitalSTROM server)                  pydsvdcapi (your vDC host)
  ══════════════════════════                  ══════════════════════════
                                              VdcHost
  ┌─────────────────────────┐                 │  session.py   vdc_host.py
  │  TCP connection (port   │◄───────────────►│  VdcSession   dispatch loop
  │  5440 or custom)        │  length-prefixed │
  └─────────────────────────┘  protobuf msgs  │
                                              │  Vdc (one or more)
  Requests (expect response):                 │  └── Vdsd / Device (N per vDC)
    VDSM_REQUEST_*                            │       ├── Output
    VDC_SEND_ANNOUNCE_*                       │       │    └── OutputChannel (N)
                                              │       ├── BinaryInput (N)
  Notifications (no response):               │       ├── ButtonInput (N)
    VDSM_NOTIFICATION_*                       │       ├── SensorInput (N)
    VDSM_SEND_PING / BYE                      │       ├── DeviceState (N)
    VDC_SEND_PUSH_NOTIFICATION                │       ├── DeviceProperty (N)
    VDC_SEND_VANISH                           │       ├── DeviceEvent (N)
    VDC_SEND_PONG                             │       └── Actions (N)
```

---

## Session state machine

```
  ┌─────────────┐    TCP connect     ┌─────────────┐
  │  CONNECTING │───────────────────►│   WAITING   │
  └─────────────┘                    └──────┬──────┘
                                            │  VDSM_REQUEST_HELLO received
                                            │  api_version >= 2
                                            ▼
                                     ┌─────────────┐
                              ┌──────│   ACTIVE    │──────┐
                              │      └──────┬──────┘      │
                              │             │              │
                    VDSM_SEND_BYE    TCP drop /      ERR_INCOMPATIBLE_API
                    received         timeout          (api_version < 2)
                              │             │              │
                              ▼             ▼              ▼
                           ┌──────────────────────────────────┐
                           │              CLOSED              │
                           └──────────────────────────────────┘
                                          │
                                          │  VdcHost reconnects after delay
                                          ▼
                                  (new TCP connection)
```

All messages except `VDSM_REQUEST_HELLO` require `ACTIVE` state. Unknown messages in `WAITING` state return `ERR_SERVICE_NOT_AVAILABLE`.

---

## Quick-reference table

| Message | Direction | Kind | ACTIVE required | Response |
|---|---|---|---|---|
| `VDSM_REQUEST_HELLO` | → vDC | request | no | `VDC_RESPONSE_HELLO` or `ERR_INCOMPATIBLE_API` |
| `VDSM_SEND_PING` | → vDC | notification | yes | `VDC_SEND_PONG` |
| `VDSM_SEND_BYE` | → vDC | request | yes | `GENERIC_RESPONSE ERR_OK` |
| `VDSM_REQUEST_GET_PROPERTY` | → vDC | request | yes | `VDC_RESPONSE_GET_PROPERTY` or `ERR_NOT_FOUND` |
| `VDSM_REQUEST_SET_PROPERTY` | → vDC | request | yes | `GENERIC_RESPONSE` |
| `VDSM_REQUEST_GENERIC_REQUEST` | → vDC | request | yes | `GENERIC_RESPONSE` |
| `VDSM_SEND_REMOVE` | → vDC | request | yes | `GENERIC_RESPONSE` |
| `VDSM_NOTIFICATION_CALL_SCENE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_SAVE_SCENE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_UNDO_SCENE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_SET_LOCAL_PRIO` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_CALL_MIN_SCENE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_DIM_CHANNEL` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_SET_CONTROL_VALUE` | → vDC | notification | yes | — |
| `VDSM_NOTIFICATION_IDENTIFY` | → vDC | notification | yes | — |
| `VDC_SEND_ANNOUNCE_VDC` | vDC → | request | yes | `GENERIC_RESPONSE` |
| `VDC_SEND_ANNOUNCE_DEVICE` | vDC → | request | yes | `GENERIC_RESPONSE` |
| `VDC_SEND_VANISH` | vDC → | notification | yes | — |
| `VDC_SEND_PUSH_NOTIFICATION` | vDC → | notification | yes | — |

---

## Inbound messages (vdSM → vDC)

---

### VDSM_REQUEST_HELLO

**Source**: `session.py` · **Precondition**: any state

```
vdSM                                              VdcSession
 │                                                     │
 │── VDSM_REQUEST_HELLO ──────────────────────────────►│
 │   message_id: N                                     │  1. read api_version
 │   dSUID: "<vdSM dSUID>"                             │  2. if api_version < 2:
 │   api_version: <int>                                │       → ERR_INCOMPATIBLE_API
 │                                                     │       state = CLOSED
 │◄─ VDC_RESPONSE_HELLO ───────────────────────────────│  3. store _vdsm_dsuid
 │   message_id: N  (echoed)                           │  4. state = ACTIVE
 │   dSUID: "<host dSUID>"                             │  5. invoke on_hello callback
 │                                                     │     (announces vDCs + devices)
```

| Field read | Type | Used for |
|---|---|---|
| `dSUID` | str | stored as `session._vdsm_dsuid` |
| `api_version` | int | compared against `SUPPORTED_API_VERSION` (2); session rejected if lower |
| `message_id` | int | echoed in response |

**Response fields** (`VDC_RESPONSE_HELLO`):

| Field | Value | Source |
|---|---|---|
| `message_id` | echoed | request |
| `dSUID` | host dSUID | `VdcHost.dsuid` |

---

### VDSM_SEND_PING

**Source**: `session.py` · **Precondition**: ACTIVE

```
vdSM                                              VdcSession
 │── VDSM_SEND_PING ──────────────────────────────────►│
 │   dSUID: "<target>"  (may be empty)                 │  1. update _last_activity
 │                                                     │  2. increment _ping_count
 │◄─ VDC_SEND_PONG ────────────────────────────────────│
 │   dSUID: "<target or host dSUID>"                   │
```

| Field read | Type | Used for |
|---|---|---|
| `dSUID` | str | echoed in pong; if empty, host dSUID is used |

---

### VDSM_SEND_BYE

**Source**: `session.py` · **Precondition**: ACTIVE

```
vdSM                                              VdcSession
 │── VDSM_SEND_BYE ───────────────────────────────────►│
 │   message_id: N                                     │  1. state = CLOSED
 │                                                     │  2. TCP connection closed
 │◄─ GENERIC_RESPONSE (ERR_OK) ────────────────────────│
 │   message_id: N
```

No application-level callbacks invoked. `on_disconnect` is **not** called (clean termination by vdSM).

---

### VDSM_REQUEST_GET_PROPERTY

**Source**: `vdc_host.py` · **Precondition**: ACTIVE

```
vdSM                                         VdcHost            Entity
 │                                               │                │
 │── VDSM_REQUEST_GET_PROPERTY ────────────────►│                │
 │   message_id: N                              │  1. normalize  │
 │   dSUID: "<entity>"                          │     dSUID      │
 │   query[]: PropertyElement paths            │  2. resolve    │
 │                                              │     entity ───►│
 │                                              │                │  build_get_property_response()
 │◄─ VDC_RESPONSE_GET_PROPERTY ────────────────│◄───────────────│
 │   message_id: N                             │                │
 │   properties[]: PropertyElement results     │                │
```

**Entity resolution order**:

```
dSUID matches host?  ──yes──► host.get_properties()
       │
       no
       │
dSUID in _vdcs?  ────yes──► vdc.get_properties()
       │
       no
       │
search all vDCs  ────found─► vdsd.get_properties()
       │
    not found
       │
       └──────────────────► ERR_NOT_FOUND
```

**Property subtrees returned** (driven by `query[]` path elements):

| Property key | Owner | Content |
|---|---|---|
| `dSUID` | all | device dSUID string |
| `name` | all | human name |
| `type` | all | entity type integer |
| `model` / `modelVersion` / `modelUID` / `modelFeatures` | vdSD | device model info |
| `hardwareVersion` / `firmwareVersion` | vdSD | version strings |
| `buttonInputDescriptions` / `buttonInputSettings` / `buttonInputStates` | vdSD | all button inputs |
| `binaryInputDescriptions` / `binaryInputSettings` / `binaryInputStates` | vdSD | all binary inputs |
| `sensorDescriptions` / `sensorSettings` / `sensorStates` | vdSD | all sensor inputs |
| `outputDescription` / `outputSettings` / `outputState` | vdSD | output (if present) |
| `channelDescriptions` / `channelSettings` / `channelStates` | vdSD | output channels |
| `deviceActionDescriptions` / `deviceActions` / `customActions` | vdSD | action catalog |
| `devicePropertyDescriptions` / `deviceProperties` | vdSD | device properties |
| `deviceStateDescriptions` / `deviceStates` | vdSD | device states |
| `deviceEventDescriptions` / `deviceEvents` | vdSD | device events |
| `scenes` | vdSD | scene table (indexed by scene number) |
| `zoneID` / `progMode` | vdSD | zone assignment, programming mode |

Channel container keys use the **channel name** string (e.g. `"brightness"`, `"shadePositionOutside"`) as outer key. Numeric keys (e.g. `"0"`, `"1"`) are also accepted in requests via `_ChannelCompatDict` for API v2 compatibility.

---

### VDSM_REQUEST_SET_PROPERTY

**Source**: `vdc_host.py` · **Precondition**: ACTIVE

```
vdSM                                         VdcHost
 │── VDSM_REQUEST_SET_PROPERTY ──────────────►│
 │   message_id: N                            │  1. normalize + resolve entity
 │   dSUID: "<entity>"                        │  2. elements_to_dict(properties[])
 │   properties[]: PropertyElement writes     │  3. dispatch to apply_* method
 │                                            │  4. schedule auto-save (debounced)
 │◄─ GENERIC_RESPONSE (ERR_OK) ──────────────│
 │   message_id: N
```

**Writable properties per entity type**:

**Host**:

| Key | Action |
|---|---|
| `name` | `host.name = value` |

**vDC**:

| Key | Action |
|---|---|
| `name` | `vdc.name = value` |
| `zoneID` | `vdc.zone_id = int(value)` |

**vdSD** — all with wildcard expansion (`""` key applies to all items at that level):

| Key | Expansion | Action | Callback |
|---|---|---|---|
| `name` | — | `vdsd.name = value` | — |
| `zoneID` | — | `vdsd.zone_id = int(value)` | — |
| `progMode` | — | `vdsd.prog_mode = bool(value)` | — |
| `buttonInputSettings[idx]` | per element | `btn.apply_settings(dict)` | `await btn.on_settings_changed(btn, dict)` |
| `binaryInputSettings[idx]` | per element | `bi.apply_settings(dict)` | `await bi.on_settings_changed(bi, dict)` |
| `sensorSettings[idx]` | per element | `si.apply_settings(dict)` | `await si.on_settings_changed(si, dict)` |
| `outputSettings` | — | `output.apply_settings(dict)` | `await output.on_settings_changed(output, dict)` |
| `outputState` | — | `output.apply_state(dict)` — `localPriority` only | — |
| `customActions[idx]` | per element | `action.apply_settings(dict)` | — |
| `channelStates[name\|idx]` | per element | `output.buffer_channel_value(ch, val)` → schedules `apply_pending_channels()` | `await output.on_channel_applied(output, {ch_type: val})` |
| `scenes[number]` | per element | `output.apply_scenes(dict)` | — |

**Writable sub-fields per settings type**:

`buttonInputSettings`:

| Sub-field | Type | Applied to |
|---|---|---|
| `group` | int | `btn._group` |
| `function` | int | `btn._function` (resolved via `button_function_for_group`) |
| `mode` | int | `btn._mode` (ButtonMode enum) |
| `channel` | int | `btn._channel` |
| `setsLocalPriority` | bool | `btn._sets_local_priority` |
| `callsPresent` | bool | `btn._calls_present` |

`binaryInputSettings`:

| Sub-field | Type | Applied to |
|---|---|---|
| `group` | int | `bi._group` |
| `sensorFunction` | int | `bi._sensor_function` (BinaryInputType enum) |

`sensorSettings`:

| Sub-field | Type | Applied to |
|---|---|---|
| `group` | int | `si._group` |
| `minPushInterval` | float | `si._min_push_interval` |
| `changesOnlyInterval` | float | `si._changes_only_interval` |

`outputSettings` (selection by `primaryGroup`):

| Sub-field | Type | All groups | Group 1 (light) | Group 2 (shade) | Group 3 (climate) |
|---|---|---|---|---|---|
| `mode` | int (OutputMode) | ✓ | | | |
| `activeGroup` | int | ✓ | | | |
| `pushChanges` | bool | ✓ | | | |
| `groups` | dict[str,bool] | ✓ | | | |
| `onThreshold` | float | ✓ | | | |
| `minBrightness` | float | | ✓ | | |
| `dimTimeUp/Down` (+Alt1/Alt2) | int | | ✓ | | |
| `openTime` / `closeTime` | float | | | ✓ | |
| `angleOpenTime` / `angleCloseTime` | float | | | ✓ | |
| `stopDelayTime` | float | | | ✓ | |
| `heatingSystemCapability` | int | | | | ✓ |
| `heatingSystemType` | int | | | | ✓ |
| _(unknown keys)_ | any | stored in `_extra_settings`, round-tripped | | | |

`outputState`:

| Sub-field | Type | Applied to |
|---|---|---|
| `localPriority` | bool | `output._local_priority` |
| `transitionTime` | float | `output._transition_time` |

---

### VDSM_REQUEST_GENERIC_REQUEST

**Source**: `vdc_host.py` · **Precondition**: ACTIVE

Dispatches on `methodname` (version suffix like `/6` is stripped before matching):

```
VDSM_REQUEST_GENERIC_REQUEST
│
├─ methodname = "invokeDeviceAction" ────────────────────────────────────────────┐
│   params["id"] → action ID                                                     │
│   remaining params → passed to action                                          │
│   → vdsd.invoke_action(id, params)  [async]                                    │
│   → on_invoke_action callback                                                  │
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "identify" (vDC host) ───────────────────────────────────────────┤
│   → host._on_identify(dsuid)  [async callback]                                 │
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "pair" ──────────────────────────────────────────────────────────┤
│   params["establish"] (bool, default True)                                     │
│   params["timeout"]   (int, default -1)                                        │
│   → host._on_pair(dsuid, establish, timeout, extra_params)  [async callback]  │
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "authenticate" ──────────────────────────────────────────────────┤
│   params["authData"]  (str, default "")                                        │
│   params["authScope"] (str, default "")                                        │
│   → host._on_authenticate(dsuid, authData, authScope, extra)  [async]         │
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "firmwareUpgrade" ───────────────────────────────────────────────┤
│   params["checkonly"]     (bool, default False)                                │
│   params["clearsettings"] (bool, default False)                                │
│   → host._on_firmware_upgrade(dsuid, checkonly, clearsettings, extra)  [async]│
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "setConfiguration" ──────────────────────────────────────────────┤
│   params["id"] (str) → config profile ID                                       │
│   → host._on_set_configuration(dsuid, id, extra)  [async]                     │
│   ← ERR_OK or ERR_NOT_IMPLEMENTED                                              │
│                                                                                │
├─ methodname = "scanDevices" (+ any version suffix) ────────────────────────────┤
│   dSUID → target vDC (or all vDCs if host dSUID)                               │
│   ← ERR_OK  [returned BEFORE re-announce to avoid deadlock]                    │
│   ↓ async task:                                                                │
│     vdc.reset_announcement()                                                   │
│     await vdc.announce(session)   → VDC_SEND_ANNOUNCE_VDC                     │
│     await vdc.announce_devices()  → VDC_SEND_ANNOUNCE_DEVICE (×N)             │
│                                                                                │
└─ methodname = anything else ───────────────────────────────────────────────────┘
    → host._on_message callback (if set) [async]
    ← callback return value, or ERR_NOT_IMPLEMENTED
```

---

### VDSM_SEND_REMOVE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE

```
vdSM                                         VdcHost
 │── VDSM_SEND_REMOVE ──────────────────────►│
 │   message_id: N                            │  1. find vdSD + owning vDC
 │   dSUID: "<vdSD to remove>"               │  2. call on_remove(dsuid) callback
 │                                            │     if returns False → ERR_FORBIDDEN
 │◄─ GENERIC_RESPONSE ───────────────────────│  3. vdc.remove_device(dsuid, track_vanish=False)
 │   code: ERR_OK / ERR_FORBIDDEN            │     (not added to pendingVanish list —
 │                                            │      removal was vdSM-initiated)
```

`track_vanish=False` is critical: devices removed by the vdSM are NOT queued in the `pendingVanish` list (which is only for devices removed while offline).

---

### VDSM_NOTIFICATION_CALL_SCENE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output
 │── VDSM_NOTIFICATION_CALL_SCENE ──────────►│
 │   dSUID[]: target vdSDs                   │  per matched vdSD:
 │   scene:   0–255                          │  1. _matches_zone_and_group(zone_id, group)
 │   force:   bool                           │  2. output.dispatch_scene(scene, force)
 │   group:   int  (0 = no filter)           │     └─ look up scene table entry
 │   zone_id: int  (0 = no filter)           │        apply channel values to buffer
                                             │     3. apply_pending_channels() [async task]
                                             │        └─ on_channel_applied callback
```

Zone/group filter: a vdSD is targeted if:
- `zone_id == 0` OR `vdsd.zone_id == zone_id`
- AND `group == 0` OR `vdsd.output.active_group == group`

---

### VDSM_NOTIFICATION_SAVE_SCENE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output
 │── VDSM_NOTIFICATION_SAVE_SCENE ──────────►│
 │   dSUID[]: target vdSDs                   │  per matched vdSD:
 │   scene:   0–255                          │  output.save_scene(scene)
 │   group:   int                            │  └─ snapshots current channel values
 │   zone_id: int                            │     into scene table entry [scene]
```

---

### VDSM_NOTIFICATION_UNDO_SCENE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output
 │── VDSM_NOTIFICATION_UNDO_SCENE ──────────►│
 │   dSUID[]: target vdSDs                   │  per matched vdSD:
 │   scene:   0–255                          │  output.undo_scene(scene, group)
 │   group:   int                            │  └─ restores channel values from
 │   zone_id: int                            │     scene table entry [scene]
                                             │  apply_pending_channels() [async]
                                             │  └─ on_channel_applied callback
```

---

### VDSM_NOTIFICATION_SET_LOCAL_PRIO

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output
 │── VDSM_NOTIFICATION_SET_LOCAL_PRIO ──────►│
 │   dSUID[]: target vdSDs                   │  per matched vdSD:
 │   scene:   int  (used only to check       │  if scene.dontCare == False:
 │            dontCare flag)                 │    output.local_priority = True
 │   group:   int
 │   zone_id: int
```

---

### VDSM_NOTIFICATION_CALL_MIN_SCENE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output → Channel
 │── VDSM_NOTIFICATION_CALL_MIN_SCENE ──────►│
 │   dSUID[]: target vdSDs                   │  per matched vdSD:
 │   scene:   int                            │  if scene.dontCare == False:
 │   group:   int                            │    primary_ch = channel[dsIndex=0]
 │   zone_id: int                            │    if primary_ch.value <= min_value:
                                             │      primary_ch.value = min_value + resolution
                                             │      (or output.min_brightness if set)
                                             │  apply_pending_channels() [async]
```

---

### VDSM_NOTIFICATION_DIM_CHANNEL

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output
 │── VDSM_NOTIFICATION_DIM_CHANNEL ─────────►│
 │   dSUID[]:   target vdSDs                 │
 │   channelId: str   ◄── preferred (API v3) │  channel resolution (priority order):
 │   channel:   int   ◄── fallback (API v1/2)│  1. by channelId name ("brightness")
 │   mode:      int   1=up, -1=down, 0=stop  │  2. by channel (OutputChannelType int)
 │   area:      int   0=none, 1–4=area       │  3. standard ch for color class (ch=0)
                                             │  4. first registered channel
                                             │
                                             │  output.dim_channel(ch, mode, area) [async]
                                             │  └─ on_dim_channel callback
```

---

### VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Output → Channel
 │── VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE ──►│
 │   dSUID[]:    target vdSDs                      │  same channel resolution as DIM_CHANNEL
 │   channelId:  str  (preferred)                  │
 │   channel:    int  (fallback)                   │  output.buffer_channel_value(ch, value)
 │   value:      float                             │
 │   apply_now:  bool (default True)               │  if apply_now:
                                                   │    apply_pending_channels() [async]
                                                   │    └─ on_channel_applied(output, {ch: val})
```

---

### VDSM_NOTIFICATION_SET_CONTROL_VALUE

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Vdsd
 │── VDSM_NOTIFICATION_SET_CONTROL_VALUE ───►│
 │   dSUID[]:  target vdSDs                  │  vdsd.set_control_value(name, value,
 │   name:     str  (control value name)     │      group, zone_id) [async]
 │   value:    float                         │  └─ on_control_value(vdsd, name, value)
 │   group:    int                           │     callback
 │   zone_id:  int
```

---

### VDSM_NOTIFICATION_IDENTIFY

**Source**: `vdc_host.py` · **Precondition**: ACTIVE · **No response**

```
vdSM                                         VdcHost → Vdsd
 │── VDSM_NOTIFICATION_IDENTIFY ────────────►│
 │   dSUID[]:  target vdSDs                  │  vdsd.identify() [async]
 │   group:    int                           │  └─ on_identify(vdsd) callback
 │   zone_id:  int
```

---

## Outbound messages (vDC → vdSM)

---

### VDC_SEND_ANNOUNCE_VDC

**Source**: `vdc.py` · **Trigger**: `await vdc.announce(session)`

```
VdcHost                                      vdSM
 │── VDC_SEND_ANNOUNCE_VDC ────────────────►│
 │   message_id: N  (expects response)      │
 │   dSUID: "<vDC dSUID>"                   │
 │                                          │
 │◄─ GENERIC_RESPONSE ──────────────────────│
 │   code: ERR_OK                           │  vdc._announced = True
 │       │ ERR_*                            │  vdc._announced = False + log warning
```

Called automatically after session `on_hello` and after `scanDevices`.

---

### VDC_SEND_ANNOUNCE_DEVICE

**Source**: `vdsd.py` · **Trigger**: `await vdsd.announce(session)`

```
VdcHost                                      vdSM
 │  Pre-flight:                              │
 │  1. wait for initial sensor/binary values │
 │  2. derive_model_features() if not set   │
 │  3. flush pendingVanish list first        │
 │                                          │
 │── VDC_SEND_ANNOUNCE_DEVICE ─────────────►│
 │   message_id: N  (expects response)      │
 │   dSUID:     "<vdSD dSUID>"              │
 │   vdc_dSUID: "<owning vDC dSUID>"        │
 │                                          │
 │◄─ GENERIC_RESPONSE ──────────────────────│
 │   code: ERR_OK                           │  vdsd._announced = True
 │                                          │  vdsd._session = session
 │                                          │  start alive timers (button/binary/sensor)
 │                                          │  push initial state for inputs with values
 │                                          │  output.start_session(session)
 │       │ ERR_*                            │  vdsd._announced = False + log warning
```

---

### VDC_SEND_VANISH

**Source**: `vdsd.py` · **Trigger**: `await vdsd.vanish(session)` or `vdc.remove_device()` while online

```
VdcHost                                      vdSM
 │── VDC_SEND_VANISH ──────────────────────►│  (notification, no response)
 │   message_id: 0
 │   dSUID: "<vdSD dSUID>"
 │
 │  Post:
 │  vdsd._announced = False
 │  vdsd._session = None
 │  stop alive timers on all inputs
 │  output.stop_session()
```

---

### VDC_SEND_PUSH_NOTIFICATION — channel states

**Source**: `output.py` · **Trigger**: `OutputChannel.update_value()` when `output.push_changes == True`

```
VdcHost                                      vdSM
 │── VDC_SEND_PUSH_NOTIFICATION ────────────►│  (notification, no response)
 │   message_id: 0
 │   dSUID: "<vdSD dSUID>"
 │   changedproperties[]:
 │     channelStates:
 │       "<channel_name>":         ◄── e.g. "brightness", "shadePositionOutside"
 │         value:          float   ◄── OutputChannel._value
 │         age:            float   ◄── seconds since last update (or null)
 │         transitionTime: float   ◄── 0.0 (hardware-applied)
```

Channel key is the channel's **name** string (not dsIndex). Predefined channels use `ChannelSpec.name`; custom channels use the caller-supplied name.

---

### VDC_SEND_PUSH_NOTIFICATION — output settings

**Source**: `output.py` · **Trigger**: `await output.push_settings()`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    outputSettings:
      mode:                     int    ◄── OutputMode enum
      activeGroup:              int
      pushChanges:              bool
      groups:                   {str: bool}
      onThreshold:              float  (if set)
      minBrightness:            float  (if set, group 1)
      dimTimeUp/Down/Alt1/Alt2: int    (if set, group 1)
      openTime / closeTime:     float  (if set, group 2)
      angleOpenTime/CloseTime:  float  (if set, group 2)
      stopDelayTime:            float  (if set, group 2)
      heatingSystemCapability:  int    (if set, group 3)
      heatingSystemType:        int    (if set, group 3)
      <extra keys>:             any    (from _extra_settings)
```

---

### VDC_SEND_PUSH_NOTIFICATION — binary input state

**Source**: `binary_input.py` · **Trigger**: `await bi.update_value(val)` or `update_extended_value(val)`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    binaryInputStates:
      "<ds_index>":
        value:         bool   ◄── bi._value          (or absent if extended)
        extendedValue: int    ◄── bi._extended_value  (if set; replaces value)
        age:           float  ◄── seconds since last update (or null)
        error:         int    ◄── InputError enum
```

Throttling: none. Every `update_value` / `update_extended_value` call triggers an immediate push if session is active and announced.

---

### VDC_SEND_PUSH_NOTIFICATION — binary input settings

**Source**: `binary_input.py` · **Trigger**: `await bi.push_settings()`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    binaryInputSettings:
      "<ds_index>":
        group:          int   ◄── bi._group
        sensorFunction: int   ◄── BinaryInputType enum
```

---

### VDC_SEND_PUSH_NOTIFICATION — button input state

**Source**: `button_input.py` · **Trigger**: click detection fires button event

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    buttonInputStates:
      "<ds_index>":
        value:       bool   ◄── btn._value (pressed state)
        clickType:   int    ◄── ButtonClickType enum (or absent if extended)
        buttonAction:int    ◄── btn._extended_value (if set; replaces clickType)
        age:         float  ◄── seconds since last update (or null)
        error:       int    ◄── InputError enum
```

Throttling: none. Button events are pushed immediately.

---

### VDC_SEND_PUSH_NOTIFICATION — button input settings

**Source**: `button_input.py` · **Trigger**: `await btn.push_settings()`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    buttonInputSettings:
      "<ds_index>":
        group:            int
        function:         int   ◄── ButtonFunction enum
        mode:             int   ◄── ButtonMode enum
        channel:          int
        setsLocalPriority:bool
        callsPresent:     bool
```

---

### VDC_SEND_PUSH_NOTIFICATION — sensor input state

**Source**: `sensor_input.py` · **Trigger**: `await si.update_value(val)` — with throttling

```
                    update_value(val) called
                           │
                    session active + announced?
                      no ──► return (no push)
                           │ yes
                    changesOnly mode?
                      yes ──► value changed since last push?
                                no ──► schedule deferred push at changesOnlyInterval
                                yes ──► continue
                    minPushInterval elapsed?
                      no ──► schedule deferred push at remaining interval
                           │ yes
                    _do_push()
                           │
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    sensorStates:
      "<ds_index>":
        value:       float  ◄── si._value  (may be null)
        age:         float  ◄── seconds since last update (or null)
        contextId:   int    (if set)
        contextMsg:  str    (if set)
        error:       int    ◄── InputError enum

  After push:
    _last_push_time = now
    _last_pushed_state = current state key
    alive timer reset
```

**Alive timer**: if `minPushInterval > 0` and no push has been sent in `minPushInterval` seconds, an alive push is triggered automatically (with the last known value).

---

### VDC_SEND_PUSH_NOTIFICATION — sensor input settings

**Source**: `sensor_input.py` · **Trigger**: `await si.push_settings()`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    sensorSettings:
      "<ds_index>":
        group:               int
        minPushInterval:     float   ◄── si._min_push_interval (seconds)
        changesOnlyInterval: float   ◄── si._changes_only_interval (seconds)
```

---

### VDC_SEND_PUSH_NOTIFICATION — device state

**Source**: `device_state.py` · **Trigger**: `await state.update_value(val)`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    deviceStates:
      "<state_name>":
        value:     str   ◄── encoded as string regardless of type
        age:       float ◄── seconds since last update (or null)
```

---

### VDC_SEND_PUSH_NOTIFICATION — device property

**Source**: `device_property.py` · **Trigger**: `await prop.update_value(val)`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  changedproperties[]:
    deviceProperties:
      "<property_name>": <value>   ◄── string, numeric, or enum int
```

---

### VDC_SEND_PUSH_NOTIFICATION — device event

**Source**: `device_event.py` · **Trigger**: `await event.raise_event()`

```
VDC_SEND_PUSH_NOTIFICATION
  dSUID: "<vdSD dSUID>"
  deviceevents[]:               ◄── separate field (not changedproperties)
    PropertyElement(name="<event_name>")
```

Device events use `deviceevents` (a separate repeated field), not `changedproperties`. This is the only `VDC_SEND_PUSH_NOTIFICATION` variant that does not use `changedproperties`.

---

## Response codes

All `GENERIC_RESPONSE` messages carry one of these codes:

| Code | Value | Meaning |
|---|---|---|
| `ERR_OK` | 0 | Success |
| `ERR_MESSAGE_UNKNOWN` | 1 | Unrecognised message type |
| `ERR_INCOMPATIBLE_API` | 2 | API version too old (< 2) |
| `ERR_SERVICE_NOT_AVAILABLE` | 3 | Session not yet active (before HELLO) |
| `ERR_INSUFFICIENT_STORAGE` | 4 | Storage full |
| `ERR_FORBIDDEN` | 5 | Operation rejected (e.g. `on_remove` returned `False`) |
| `ERR_NOT_IMPLEMENTED` | 6 | No handler registered for this method |
| `ERR_NO_CONTENT_FOR_ARRAY` | 7 | Array property has no elements |
| `ERR_INVALID_VALUE_TYPE` | 8 | Value type mismatch |
| `ERR_MISSING_SUBMESSAGE` | 9 | Required sub-message absent |
| `ERR_MISSING_DATA` | 10 | Required field missing |
| `ERR_NOT_FOUND` | 11 | Referenced entity (dSUID) not found |
| `ERR_NOT_AUTHORIZED` | 12 | Authorization failed |
