# p44vdc Message Flow Reference

> Based strictly on source code. API version range: MIN=2, MAX=3 (`p44vdc_common.hpp:36-37`).
> JSON bridge API extensions (`#if ENABLE_JSONBRIDGEAPI`) are out of scope; this document
> covers only the `VDC_API_DOMAIN` (vdSM ↔ vDC) path.

---

## Architecture

```
vdSM (dS System Manager)
        |
        |  TCP socket — 2-byte big-endian length prefix + protobuf payload
        |  MAX_DATA_SIZE = 16384 bytes  (pbufvdcapi.cpp:1091)
        ↓
VdcPbufApiConnection.gotData()         pbufvdcapi.cpp
  └─ parse 2-byte header → mExpectedMsgBytes
  └─ accumulate until complete
  └─ processMessage()
        ├─ vdcapi__message__unpack()   (protobuf-c decode)
        ├─ switch(decodedMsg->type)    → method string + paramsMsg + responseType
        ├─ if has_message_id → method call  → mApiRequestHandler(conn, request, method, params)
        └─ else              → notification → mApiRequestHandler(conn, nil,     method, params)

VdcHost.vdcApiRequestHandler()         vdchost.cpp
  ├─ if request (has message_id):
  │     ├─ "hello" → helloHandler()
  │     ├─ "bye"   → byeHandler()
  │     └─ (session active) → handleMethodForParams()
  │           ├─ resolve dSUID / itemSpec → DsAddressable
  │           ├─ if device + method "remove" → removeHandler()
  │           └─ else → addressable.handleMethod()
  └─ if notification (no message_id):
        └─ (session active) → handleNotificationForParams()
              ├─ resolve audience: dSUID array | itemSpec | zone_id+group
              └─ deliverToAudience() → addressable.handleNotificationFromConnection()
                    └─ addressable.handleNotification()
```

---

## Transport Layer

**Framing** (`pbufvdcapi.cpp:1189–1207`):

- Each message is prefixed by a 2-byte big-endian length: `[size>>8, size&0xFF]`
- Receiver accumulates bytes until `receivedMessage.size() >= mExpectedMsgBytes`
- Messages larger than 16384 bytes are rejected with error 413

**Sending** (`pbufvdcapi.cpp:1183–1225`):

- `sendMessage()` packs with `vdcapi__message__pack()`, prepends 2-byte header
- If transmit buffer is non-empty, message is appended; otherwise sent immediately
- Remaining bytes buffered in `mTransmitBuffer` and flushed by `canSendData` callback

---

## Session State

```
  [TCP connect]
       ↓
  vdcApiConnectionStatusHandler() sets up request handler
       ↓
  [waiting for hello]
       ↓
  VDSM_REQUEST_HELLO received
       │
       ├─ api_version out of range → ERR_INCOMPATIBLE_API, close
       ├─ vdSM dSUID != existing session's dSUID → ERR_SERVICE_NOT_AVAILABLE, close
       └─ ok → save connection as mVdsmSessionConnection
              → VDC_RESPONSE_HELLO (vDC dSUID)
              → postEvent(vdchost_vdcapi_connected)
              → startAnnouncing()
                   ↓
              [SESSION ACTIVE — methods and notifications processed]
                   ↓
              VDSM_SEND_BYE  or  connection drop
                   ↓
              resetAnnouncing(), mVdsmSessionConnection = nullptr
              postEvent(vdchost_vdcapi_disconnected)
```

---

## Inbound Messages (vdSM → vDC)

### VDSM_REQUEST_HELLO → `"hello"`

**Source**: `pbufvdcapi.cpp:1315–1321`  
**Handler**: `VdcHost::helloHandler()` (`vdchost.cpp:1298`)

| Field | Type | Action |
|-------|------|--------|
| `api_version` | int | Must be in `[VDC_API_VERSION_MIN=2, VDC_API_VERSION_MAX=3]`; saved with `aRequest->connection()->setApiVersion()` |
| `dSUID` | binary | Parsed as `DsUid`; must match `mConnectedVdsm` if session already active |

**Response**: `VDC_RESPONSE_HELLO`
- Result object: `{ "dSUID": <vDC host dSUID binary> }`
- On version mismatch: `ERR_INCOMPATIBLE_API` + `closeAfterSend()`
- On session conflict: `ERR_SERVICE_NOT_AVAILABLE` + `closeAfterSend()`

**Side effects**: Sets `mVdsmSessionConnection`, calls `startAnnouncing()`, posts `vdchost_vdcapi_connected` event.

---

### VDSM_SEND_BYE → `"bye"`

**Source**: `pbufvdcapi.cpp:1346–1350`  
**Handler**: `VdcHost::byeHandler()` (`vdchost.cpp:1358`)

No parameters. Always acknowledged even if out-of-session.

**Response**: `GENERIC_RESPONSE` (ERR_OK, null result)  
**Side effects**: `closeAfterSend()` — connection closes after response is sent.

---

### VDSM_REQUEST_GET_PROPERTY → `"getProperty"`

**Source**: `pbufvdcapi.cpp:1323–1329`  
**Routing**: `handleMethodForParams()` → `addressable->handleMethod()` → `DsAddressable::handleMethod()` (`dsaddressable.cpp:172`)

| Field | Type | Action |
|-------|------|--------|
| `dSUID` | binary | Selects target addressable (VdcHost if missing) |
| `query` | PropertyElement tree | Passed to `accessProperty(access_read, ...)` |

**Response**: `VDC_RESPONSE_GET_PROPERTY`
- On success: result = property tree built by `accessProperty()`
- On failure: `GENERIC_RESPONSE` with error code

**Addressable resolution** (`handleMethodForParams`, `vdchost.cpp:1497`):
1. Parse `dSUID` from params; if missing/empty → check `x-p44-itemSpec` → else default to VdcHost itself
2. Find `DsAddressable` in `mDSDevices` + `mVdcs` map

---

### VDSM_REQUEST_SET_PROPERTY → `"setProperty"`

**Source**: `pbufvdcapi.cpp:1331–1337`  
**Routing**: `handleMethodForParams()` → `addressable->handleMethod()` → `DsAddressable::handleMethod()` (`dsaddressable.cpp:183`)

| Field | Type | Action |
|-------|------|--------|
| `dSUID` | binary | Selects target addressable |
| `properties` | PropertyElement tree | Passed to `accessProperty(access_write, ...)` or `access_write_preload` |
| `preload` | bool (optional) | If true, uses `access_write_preload` mode |

**Response**: `GENERIC_RESPONSE` (ERR_OK on success)
- On success: result = null (write returns nothing unless a new object was created)

**Note**: Property writes traverse the same `PropertyContainer::accessProperty()` tree as reads, dispatching to `accessField()` overrides throughout the class hierarchy.

---

### VDSM_REQUEST_GENERIC_REQUEST → `"genericRequest"`

**Source**: `pbufvdcapi.cpp:1352–1358`  
**Routing**: `handleMethodForParams()` → `addressable->handleMethod()` → `DsAddressable::handleMethod()` (`dsaddressable.cpp:199`)

| Field | Type | Action |
|-------|------|--------|
| `dSUID` | binary | Selects target addressable |
| `methodname` | string | Name of the inner method to call |
| `params` | object | Forwarded as params to the inner call |

**Dispatch logic** (`dsaddressable.cpp:199–228`):
1. Extract `methodname` and `params`
2. Call `handleMethod(request, methodname, params)` recursively
3. If that returns error 405 (unknown method) → try as notification via `handleNotificationFromConnection()`
4. Recursive call to `genericRequest` itself returns 415

**Response**: Whatever the inner method returns (GENERIC_RESPONSE or VDC_RESPONSE_GET_PROPERTY).

**Sub-methods dispatched on Vdc** (`vdc.cpp:818`):

| Method | Handler | Key params |
|--------|---------|------------|
| `scanDevices` | `Vdc::handleMethod()` | `incremental` (bool), `exhaustive` (bool), `reenumerate` (bool), `clearconfig` (bool) — vdSM session: only `incremental` allowed |
| `pair` | `Vdc::performPair()` | `establish` (bool/null), `disableProximityCheck` (bool), `timeout` (int, seconds) |

**Sub-methods dispatched on SingleDevice** (`singledevice.cpp:1686`):

| Method | Handler | Key params |
|--------|---------|------------|
| `invokeDeviceAction` | `SingleDevice::handleMethod()` | `id` (string action ID), `params` (object) |

**Sub-methods dispatched on DsAddressable** (`dsaddressable.cpp:224–276`):

| Method | Handler | Key params |
|--------|---------|------------|
| `loglevel` | inline | `value` (int 0–7, or 8 for stats dump) |
| `logleveloffset` | inline | `value` (int), `topic` (optional string) |
| `logoptions` | inline | `deltas` (bool), `symbols` (bool), `colors` (bool) |

**Sub-methods dispatched on Device** (`device.cpp:760`):

| Method | Handler | Key params |
|--------|---------|------------|
| `setConfiguration` | inline | `configurationId` (string) |
| `x-p44-removeDevice` | inline | _(none, device must be software-disconnectable)_ |
| `x-p44-teachInSignal` | inline | `variant` (uint8) |
| `x-p44-syncChannels` | inline | _(none)_ — result sent async after sync completes |

---

### VDSM_SEND_REMOVE → `"remove"`

**Source**: `pbufvdcapi.cpp:1339–1344`  
**Note**: `dSUID` is extracted explicitly (`getDsUid` goto path) then `paramsMsg` is set to NULL.  
**Routing**: `handleMethodForParams()` → if Device → `removeHandler()`

**Handler** (`vdchost.cpp:1539`):
```
aDevice->disconnect(true, callback)
  → removeResultHandler(device, request, disconnected)
      if disconnected: sendResult(null)
      else:            sendError(403, "Device cannot be removed, is still connected")
```

**Response**: `GENERIC_RESPONSE` (ERR_OK) on success, 403 on failure.

---

### VDSM_SEND_PING → `"ping"`

**Source**: `pbufvdcapi.cpp:1360–1365`  
**Note**: `dSUID` extracted explicitly via `getDsUid` path; no message_id → notification.  
**Routing**: Audience resolution → `addressable->handleNotification()` → `DsAddressable::handleNotification()` (`dsaddressable.cpp:390`)

No parameters (dSUID only).

**Side effect**: Calls `checkPresence()` → result passed to `pingResultHandler()`:
- If present: sends `VDC_SEND_PONG` (notification, no response expected)
- If not present: logs only, no pong

---

### VDSM_NOTIFICATION_CALL_SCENE → `"callScene"`

**Routing**: Audience resolution → `handleNotification()` or optimized path via `notificationPrepare()`  
**Handler**: `Device::notificationPrepare()` + `callScenePrepare()` (`device.cpp:1080`)

| Field | Type | Action |
|-------|------|--------|
| `dSUID` | binary array | Target device(s) |
| `zone_id` + `group` | uint16 | Alternative audience targeting |
| `scene` | int32 | Scene number (SceneNo) |
| `force` | bool | Force call even if local priority set |
| `transitionTime` | double (seconds) | Optional transition time override |

**Effect**: `callScenePrepare()` → scene lookup → `callScenePrepare2()` → loads channel values from scene → `requestApplyingChannels()`  
No response (notification).

---

### VDSM_NOTIFICATION_SAVE_SCENE → `"saveScene"`

**Handler**: `Device::handleNotification()` (`device.cpp:843`)

| Field | Type | Action |
|-------|------|--------|
| `scene` | int32 | Scene number to save |

**Effect**: `saveScene(sceneNo)` — stores current channel values into scene.  
No response.

---

### VDSM_NOTIFICATION_UNDO_SCENE → `"undoScene"`

**Handler**: `Device::handleNotification()` (`device.cpp:854`)

| Field | Type | Action |
|-------|------|--------|
| `scene` | int32 | Scene number to restore |

**Effect**: `undoScene(sceneNo)`.  
No response.

---

### VDSM_NOTIFICATION_SET_LOCAL_PRIO → `"setLocalPriority"`

**Handler**: `Device::handleNotification()` (`device.cpp:865`)

| Field | Type | Action |
|-------|------|--------|
| `scene` | int32 | Scene number used to determine area |

**Effect**: `setLocalPriority(sceneNo)`.  
No response.

---

### VDSM_NOTIFICATION_SET_CONTROL_VALUE → `"setControlValue"`

**Handler**: `Device::handleNotification()` (`device.cpp:876`)

| Field | Type | Action |
|-------|------|--------|
| `name` | string | Control value name |
| `value` | double | Control value |

**Effect**: `processControlValue(name, value)` → if returns true: `stopSceneActions()` + `requestApplyingChannels()`.  
No response.

---

### VDSM_NOTIFICATION_CALL_MIN_SCENE → `"callSceneMin"`

**Handler**: `Device::handleNotification()` (`device.cpp:897`)

| Field | Type | Action |
|-------|------|--------|
| `scene` | int32 | Scene number |

**Effect**: `callSceneMin(sceneNo)` — activates device at minimum output if currently off.  
No response.

---

### VDSM_NOTIFICATION_IDENTIFY → `"identify"`

**Handler**: `DsAddressable::handleNotification()` (`dsaddressable.cpp:396`)

| Field | Type | Action |
|-------|------|--------|
| `duration` | double (seconds, optional) | Duration for identify (0 = device default) |

**Effect**: `identifyToUser(duration)` — device-specific visual/audio feedback.  
No response.

---

### VDSM_NOTIFICATION_DIM_CHANNEL → `"dimChannel"`

**Handler**: `Device::notificationPrepare()` → `dimChannelForAreaPrepare()` (`device.cpp:1141`)

| Field | Type | Action |
|-------|------|--------|
| `channel` | int32 | Channel type (channeltype_*) |
| `channelId` | string | Alternative: channel by ID |
| `mode` | int32 | `0`=stop, positive=up, negative=down |
| `area` | int32 (optional) | Area number (0=all) |
| `dimPerMS` | double (optional) | Custom dim rate in units/ms |
| `fullRangeTime` | double (optional) | Time for full range traverse (seconds) |
| `force` | bool (optional) | Force dim even if device is off |
| `autoStop` | bool (optional) | Auto-stop dimming (default true) |
| `stopActions` | bool (optional) | Stop scene actions (default: true on stop, false on start) |

**Effect**: `dimChannelForAreaPrepare()` → if not suppressed by local priority → `dimChannel()` starts or stops dimming.  
No response.

---

### VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE → `"setOutputChannelValue"`

**Handler**: `Device::handleNotification()` (`device.cpp:909`)

| Field | Type | Action |
|-------|------|--------|
| `channel` | int32 | Channel type |
| `channelId` | string | Alternative: channel by ID |
| `value` | double | Target value (if not `move`) |
| `move` | int32 (optional) | Start/stop movement: 0=stop, +1=open/up, -1=close/down |
| `rate` | double (optional) | Movement rate (seconds per unit, used with `move`) |
| `transitionTime` | double (seconds, optional) | Transition duration |
| `direction` | string (optional) | `"up"`, `"down"`, `"shortest"`, `"longest"` |
| `sync` | int8 (optional) | Sync mode: 0=jump, 1=pickup, 2=scaling |
| `previous` | double (optional) | Previous controller value (used with `sync`) |
| `onoff` | bool (optional) | Suppress transition through zero for mindim channels |
| `coupling` | bool (optional, default true) | Enable channel coupling |
| `apply_now` | bool (optional, default true) | Immediately apply to hardware |

**Effect**:
1. Resolve channel by type or ID
2. If `move`: `channel->moveChannelValue(dir, rate, coupling)`
3. Else: apply sync mode logic → `channel->setChannelValue(newValue, transitionTime, ...)`
4. If `apply_now`: `requestApplyingChannels()` (cancels pending native scene updates first)

No response.

---

## Outbound Messages (vDC → vdSM)

### VDC_RESPONSE_HELLO

Sent in response to `VDSM_REQUEST_HELLO`.

| Field | Value |
|-------|-------|
| `dSUID` | VdcHost's dSUID as binary |

---

### VDC_RESPONSE_GET_PROPERTY

Sent in response to `VDSM_REQUEST_GET_PROPERTY`.

| Field | Value |
|-------|-------|
| result | Protobuf PropertyElement tree built by `accessProperty()` |

---

### GENERIC_RESPONSE

Sent in response to: `VDSM_REQUEST_SET_PROPERTY`, `VDSM_SEND_REMOVE`, `VDSM_SEND_BYE`, `VDSM_REQUEST_GENERIC_REQUEST` and all variants.

| Field | Value |
|-------|-------|
| `code` | `ResultCode` enum (ERR_OK=0, or error code) |
| `description` | Error description string (if error) |

**ResultCode mapping** (`pbufvdcapi.cpp:1247–1257`):

| HTTP | Protobuf enum | Meaning |
|------|--------------|---------|
| 0/200 | ERR_OK | Success |
| 401 | ERR_NOT_AUTHORIZED | No session |
| 403 | ERR_FORBIDDEN | Not allowed |
| 404 | ERR_NOT_FOUND | Target not found |
| 405 | ERR_MESSAGE_UNKNOWN | Unknown method |
| 410 | ERR_MISSING_DATA | Gone / unpaired |
| 413 | _(internal)_ | Message too large |
| 415 | ERR_INVALID_VALUE_TYPE | Type mismatch |
| 501 | ERR_NOT_IMPLEMENTED | Not implemented |
| 503 | ERR_SERVICE_NOT_AVAILABLE | Session conflict |
| 505 | ERR_INCOMPATIBLE_API | Version mismatch |
| 507 | ERR_INSUFFICIENT_STORAGE | Storage full |

---

### VDC_SEND_ANNOUNCE_VDC → `"announcevdc"`

Sent by `VdcHost::announceNext()` (`vdchost.cpp:1617`).  
Expects `GENERIC_RESPONSE` back (handled by `announceResultHandler()`).

| Field | Value |
|-------|-------|
| `dSUID` | vDC's dSUID as binary (prepended by `sendRequest()` automatically) |

**Sequence**:
1. VdcHost iterates all vDCs with `mAnnounced==Never`
2. Sends `announcevdc` with `message_id` (expects response)
3. Schedules retry ticket (`ANNOUNCE_TIMEOUT`)
4. On acknowledgement: `mAnnounced = now()`, `mAnnouncing = Never`, `vdSMAnnouncementAcknowledged()`
5. After pause (`ANNOUNCE_PAUSE`), calls `announceNext()` again → proceeds to devices

---

### VDC_SEND_ANNOUNCE_DEVICE → `"announcedevice"`

Sent by `VdcHost::announceNext()` (`vdchost.cpp:1643`).  
Expects `GENERIC_RESPONSE` back (handled by `announceResultHandler()`).

| Field | Value |
|-------|-------|
| `dSUID` | Device dSUID as binary |
| `vdc_dSUID` | Container vDC dSUID as binary |

**Precondition**: The device's containing vDC must already be announced (`mVdcP->isAnnounced()`).

---

### VDC_SEND_PONG → `"pong"`

Sent by `DsAddressable::pingResultHandler()` (`dsaddressable.cpp:454`) after `checkPresence()` returns true.

| Field | Value |
|-------|-------|
| `dSUID` | Device dSUID as binary (prepended by `sendRequest()`) |

No response expected.

---

### VDC_SEND_VANISH → `"vanish"`

Sent by `DsAddressable::reportVanished()` (`dsaddressable.cpp:93`).  
Only sent if `isAnnounced()` is true.

| Field | Value |
|-------|-------|
| `dSUID` | Device or vDC dSUID as binary |

No response expected. Triggered by `Device::hasVanished()` → `reportVanished()` → `disconnect()`.

---

### VDC_SEND_PUSH_NOTIFICATION → `"pushNotification"`

Sent by `DsAddressable::pushPropertyReady()` (`dsaddressable.cpp:354`).  
Only sent if `isAnnounced()` is true (checked in `pushNotification()`).

**Construction** (`pushPropertyReady`, `dsaddressable.cpp:356`):
```
params = {}
if aResultObject:  params["changedproperties"] = aResultObject   // property values read from tree
if aEvents:        params["deviceevents"]       = aEvents         // device event list
```

Both fields are optional; at least one is always present.

**Triggering paths**:

#### Presence change → `"active"` property push

`DsAddressable::updatePresenceState()` (`dsaddressable.cpp:462`):
```
query = wrapNull("active")
pushNotification(api, query, nullptr)
  → accessProperty(read, "active") → pushPropertyReady()
```

| Push content | Value |
|-------------|-------|
| `changedproperties.active` | bool (true/false) |

#### Channel state change → `"channelStates"` push

`OutputBehaviour::reportOutputState()` (`outputbehaviour.cpp:280`):
- Note: DS-side push to vdSM is **not yet implemented** in p44vdc source
  (`outputbehaviour.cpp:313–327` contains dead code with a TODO comment)
- Channel state pushes go to JSON Bridge API only (`ENABLE_JSONBRIDGEAPI` path)

#### Device state change → `"deviceStates"` + optional `"deviceevents"` push

`DeviceState::push()` (`singledevice.cpp:1039`):
```
query = { "deviceStates": { <stateId>: null } }
pushNotification(api, query, events)
  → accessProperty(read, "deviceStates.<stateId>") → pushPropertyReady()
```

| Push content | Value |
|-------------|-------|
| `changedproperties.deviceStates.<id>` | current state value |
| `deviceevents` | event list (if events present) |

#### Device event without state change → `"deviceevents"` only push

`DeviceEvent::push()` (`singledevice.cpp:1409`):
```
events = [ { eventId: <id> } ]
pushNotification(api, nullptr, events)   // no property query
  → pushPropertyReady() with null result
```

| Push content | Value |
|-------------|-------|
| `deviceevents` | list of event objects |

#### Device property change → `"deviceProperties"` push

`DeviceProperty::push()` (`singledevice.cpp:1459`):
```
query = wrapNull(<propName>) wrapped as "deviceProperties"
pushNotification(api, query, nullptr)
```

| Push content | Value |
|-------------|-------|
| `changedproperties.deviceProperties.<name>` | current property value |

#### Vanished device property deletion → forward push

`DeviceProperty::reportVanished()` (`singledevice.cpp:361`):
```
pushNotification(api, q, nullptr, removed=true)  // aForwardQuery=true
```
Forwards the query as-is (reports removal).

---

### VDC_SEND_IDENTIFY → `"identify"`

**Note**: Different from the incoming `VDSM_NOTIFICATION_IDENTIFY`. This outbound message
is sent from vDC to vdSM to notify that a device has identified itself (learned in).

Sent via `sendRequest()` with method `"identify"` (`pbufvdcapi.cpp:1569`).  
Protobuf type: `VDCAPI__TYPE__VDC_SEND_IDENTIFY`.

| Field | Value |
|-------|-------|
| `dSUID` | Device dSUID |

---

## Message Dispatch: Responses to Outgoing Requests

When p44vdc sends a request expecting a response (e.g. `announcevdc`, `announcedevice`), the response is matched by `message_id` from `mPendingAnswers` map (`pbufvdcapi.cpp:1426`):

```
GENERIC_RESPONSE or VDC_RESPONSE_* arrives with has_message_id=true and code/fields
  ↓
pbufvdcapi.cpp: responseForId = decodedMsg->message_id
  ↓
look up mPendingAnswers[responseForId] → VdcApiResponseCB callback
  ↓
erase from map, call callback(connection, request, err, resultObject)
```

If `message_id` is not in the pending map, an error is logged and the response is dropped.

---

## Property Tree Access

All `getProperty` and `setProperty` calls use `PropertyContainer::accessProperty()`, which:

1. Iterates the query/value tree of `PropertyElement` nodes
2. For each node, calls `getDescriptorByIndex()` or `getDescriptorByName()` to find the property
3. Calls `prepareAccess()` for any needed async preparation (e.g. `active` triggers `checkPresence()`)
4. Calls `accessField()` on the owning object (or recurses into sub-containers)
5. Builds result tree from returned values

The property tree is defined by a cascade of `numProps()` + `getDescriptorByIndex()` overrides throughout: `PropertyContainer` → `DsAddressable` → `Vdc` / `Device` → `DsBehaviour` → `OutputBehaviour` / `DsBehaviour` sub-classes.

---

## Key File Reference

| File | Responsibility |
|------|---------------|
| `vdc_common/pbufvdcapi.cpp` | TCP framing, protobuf encode/decode, `processMessage()` dispatch switch, `sendRequest()` method→type mapping |
| `vdc_common/vdchost.cpp` | Session management, `vdcApiRequestHandler()`, `helloHandler()`, `byeHandler()`, `handleMethodForParams()`, `handleNotificationForParams()`, `announceNext()`, `removeHandler()` |
| `vdc_common/dsaddressable.cpp` | `handleMethod()` for `getProperty`/`setProperty`/`genericRequest`, `handleNotification()` for `ping`/`identify`, `pushNotification()`, `pingResultHandler()`, `reportVanished()` |
| `vdc_common/device.cpp` | `handleMethod()` for device-specific methods, `handleNotification()` for all scene/channel/output notifications, `notificationPrepare()` for optimized delivery |
| `vdc_common/vdc.cpp` | `handleMethod()` for `scanDevices`, `pair` |
| `vdc_common/singledevice.cpp` | `handleMethod()` for `invokeDeviceAction`, `DeviceState::push()`, `DeviceEvent::push()`, `DeviceProperty::push()` |
| `vdc_common/outputbehaviour.cpp` | `reportOutputState()`, `pushOutputState()` (DS push not yet implemented in source) |
| `vdc_common/p44vdc_common.hpp` | `VDC_API_VERSION_MIN=2`, `VDC_API_VERSION_MAX=3` |
