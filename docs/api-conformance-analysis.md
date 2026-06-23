# vDC API Conformance Analysis: pydsvdcapi vs p44vdc

Systematic comparison of pydsvdcapi (Python library) against p44vdc (C++ reference implementation).
Both must conform to the same vdSM ↔ vDC protobuf API (versions 2–3).

**Sources compared:**
- `docs/message-flow-reference.md` — pydsvdcapi behavior
- `docs/p44vdc-message-flow-reference.md` — p44vdc behavior

**Severity scale:**

| Level | Meaning |
|-------|---------|
| 🔴 CRITICAL | Silent data loss or protocol failure; vdSM command has no effect or wrong effect |
| 🟠 HIGH | Significant behavioral divergence; basic use works but specific scenarios fail |
| 🟡 MEDIUM | Feature gap; pydsvdcapi ignores a parameter the vdSM may send |
| 🟢 LOW | Implementation detail or convention difference; no observable protocol impact |

---

## Summary table

| # | Message / Area | Severity | Direction of gap |
|---|----------------|----------|-----------------|
| 1 | `setOutputChannelValue` — `move` parameter missing | 🔴 | pydsvdcapi missing |
| 2 | `stopOutput` notification — no handler | 🔴 | pydsvdcapi missing |
| 3 | `VDSM_SEND_PING` — pydsvdcapi skips presence check, always pongs | 🟠 | behavior difference |
| 4 | `hello` — no upper bound on `api_version` | 🟠 | pydsvdcapi more permissive |
| 5 | `callScene` — `transitionTime` parameter ignored | 🟠 | pydsvdcapi missing |
| 6 | `dimChannel` — several parameters ignored | 🟠 | pydsvdcapi missing |
| 7 | `setOutputChannelValue` — `transitionTime`, `sync`, `coupling` and others ignored | 🟠 | pydsvdcapi missing |
| 8 | `scanDevices` — dangerous modes not restricted from vdSM session | 🟡 | pydsvdcapi more permissive |
| 9 | `pair` — `disableProximityCheck` parameter missing | 🟡 | pydsvdcapi missing |
| 10 | `identify` — `duration` parameter missing | 🟡 | pydsvdcapi missing |
| 11 | `setProperty` — `preload` flag not handled | 🟡 | pydsvdcapi missing |
| 12 | `x-p44-*` device methods not implemented | 🟡 | pydsvdcapi missing |
| 13 | `VDC_SEND_IDENTIFY` outbound not implemented | 🟡 | pydsvdcapi missing |
| 14 | `channelStates` push — p44vdc explicitly not implemented for DS API | 🟢 | p44vdc missing (pydsvdcapi correct) |
| 15 | `setControlValue` — pydsvdcapi passes `group`/`zone_id` to callback | 🟢 | harmless extension |
| 16 | `VDSM_SEND_BYE` — pydsvdcapi requires ACTIVE state; p44vdc accepts out-of-session | 🟢 | minor divergence |

---

## Detailed findings

---

### 🔴 #1 — `setOutputChannelValue`: `move` parameter not implemented

**Message**: `VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE`

**p44vdc** (`device.cpp:909`):
```
move     int32  — 0=stop, +1=open/up, -1=close/down (motor movement mode)
rate     double — time per unit (seconds), used together with move
```
When `move` is present, the command starts or stops continuous motor movement via `channel->moveChannelValue(dir, timePerUnit, withCoupling)`. The `value` field is ignored.

**pydsvdcapi** (`vdc_host.py`):
Only processes `value` (float) and `apply_now`. There is no `move` or `rate` handling.

**Impact**: Motor-driven devices (blinds, awnings, shutters) receive position-set commands from the vdSM using `move`+`rate` to start and stop motor movement. pydsvdcapi silently ignores these commands. Any shade/blind device built on pydsvdcapi will not respond to motor-start/stop commands from the dSS configurator or scene calls that use motor-mode control.

Related missing parameters in the same message:
- `transitionTime` (double, seconds) — ignored; transition always uses `output._transition_time`
- `direction` (string: "up"/"down"/"shortest"/"longest") — ignored
- `sync` (int8, pickup/scaling sync modes) — ignored
- `previous` (double) — ignored
- `onoff` (bool) — ignored; affects mindim behaviour
- `coupling` (bool, default true) — ignored

---

### 🔴 #2 — `stopOutput` notification has no handler

**Message**: `VDSM_NOTIFICATION_*` (sent as notification method `"stopOutput"`)

**p44vdc** (`device.cpp:1017`):
```
transitions  bool (default true) — stop channel transitions in progress
sceneactions bool (default true) — stop scene scripts, animations, blinking
```
After stopping, calls `reportOutputState()`.

**pydsvdcapi**:
No handler for `"stopOutput"`. The notification is silently dropped (falls through the unrecognised notification path with no effect).

**Impact**: When the vdSM or a scene calls `stopOutput` (e.g. to abort a running transition or stop blinking during identify), pydsvdcapi does nothing. Transitions and scene actions continue running indefinitely. For motor devices this is especially problematic — a motor-stop command sent as `stopOutput` will be ignored.

---

### 🟠 #3 — `VDSM_SEND_PING`: presence check skipped; pong always sent

**p44vdc** (`dsaddressable.cpp:390` → `pingResultHandler`):
1. Audience-resolves the target device by dSUID
2. Calls `checkPresence()` (may be async; device-specific, can talk to hardware)
3. Sends `VDC_SEND_PONG` **only** if the device reports itself as present
4. Updates `mPresent` state; if changed, pushes `"active"` property to vdSM

**pydsvdcapi** (`session.py`):
1. Reads `dSUID` from ping
2. Immediately sends `VDC_SEND_PONG` with that dSUID (or host dSUID if empty)
3. No presence check; no `"active"` push

**Impact**: The vdSM uses ping/pong to determine whether a device is reachable. pydsvdcapi always answers pong regardless of actual device reachability. The vdSM can never detect that a device is offline/unreachable via the ping mechanism. This affects device health monitoring and may delay vdSM fault detection.

The pong dSUID behaviour also differs: p44vdc sends pong from the addressed device (with its own dSUID added by `sendRequest()`); pydsvdcapi echoes the incoming dSUID field, which is the same value but set via a different path.

---

### 🟠 #4 — `hello`: no upper bound on `api_version`

**p44vdc** (`vdchost.cpp:1310`):
Accepts `VDC_API_VERSION_MIN (2) ≤ api_version ≤ VDC_API_VERSION_MAX (3)`. A version of 4 or higher is rejected with `ERR_INCOMPATIBLE_API`.

**pydsvdcapi** (`session.py`):
Accepts `api_version ≥ SUPPORTED_API_VERSION (2)`. No upper bound. A version of 4 would be accepted and the session would proceed using API v2 semantics.

**Impact**: If the vdSM ever negotiates a higher API version (e.g. v4 with breaking changes), pydsvdcapi will accept the session and silently mishandle new message formats or semantics. The failure would be silent rather than an explicit version rejection. This is a forward-compatibility risk, not a current interoperability failure.

**Additional hello difference**: p44vdc allows the same vdSM (same `dSUID`) to restart a session while one is already active; it resets and re-announces. A different vdSM's hello is rejected with `ERR_SERVICE_NOT_AVAILABLE`. pydsvdcapi's session model does not distinguish same vs. different vdSM reconnects.

---

### 🟠 #5 — `callScene`: `transitionTime` override parameter ignored

**Message**: `VDSM_NOTIFICATION_CALL_SCENE`

**p44vdc** (`device.cpp:1082`):
```
transitionTime  double (seconds, optional) — overrides scene's stored transition time
```
Passed to `callScenePrepare(..., transitionTimeOverride)`.

**pydsvdcapi**:
Not documented or handled. The scene's stored transition time is always used.

**Impact**: The vdSM uses `transitionTime` to perform faster or slower scene transitions (e.g. panic-off vs. slow fade-in). pydsvdcapi ignores this override and applies the preset scene transition speed in all cases.

---

### 🟠 #6 — `dimChannel`: several parameters ignored

**Message**: `VDSM_NOTIFICATION_DIM_CHANNEL`

**p44vdc** (`device.cpp:1141`) handles additional parameters beyond the basic `channel`/`channelId` and `mode`:

| Parameter | Type | Meaning |
|-----------|------|---------|
| `dimPerMS` | double | Custom dim rate (units/ms) |
| `fullRangeTime` | double (seconds) | Time to traverse full range; converted to dimPerMS |
| `force` | bool | Dim up even if the output is currently off |
| `autoStop` | bool (default true) | Auto-stop dimming after timeout |
| `stopActions` | bool (default: true on stop, false on start) | Whether to stop scene actions |

**pydsvdcapi**:
Only handles `channelId`, `channel`, `mode`, and `area`. All five additional parameters are ignored.

**Impact**:
- `dimPerMS`/`fullRangeTime`: Custom dimming speeds requested by the vdSM are silently ignored; the library's default dim step interval is always used.
- `force`: A forced dim-up on an off device (used for some control flows) has no effect.
- `autoStop`: Auto-stop cannot be disabled; dimming always stops after the internal timeout.
- `stopActions`: Scene actions are never stopped on dim start; behaviour diverges from p44vdc default.

---

### 🟠 #7 — `setOutputChannelValue`: additional value parameters ignored (non-move case)

*(The `move`/`rate` gap is filed as #1. This covers the non-move case.)*

**p44vdc** parameters ignored by pydsvdcapi even for plain `value` set commands:

| Parameter | Impact of ignoring |
|-----------|-------------------|
| `transitionTime` | Per-command transition time override is ignored; `output._transition_time` always used |
| `direction` ("up"/"down"/"shortest"/"longest") | Transition direction hint ignored; always transitions by shortest path |
| `sync` (0=jump, 1=pickup, 2=scaling) | Dial/knob sync modes not implemented; value always applied as absolute jump |
| `previous` | Required for pickup/scaling sync; irrelevant since sync is ignored |
| `onoff` | Prevents transition through zero for mindim channels; not implemented |
| `coupling` (default true) | Channel coupling on value set not implemented |

---

### 🟡 #8 — `scanDevices`: dangerous modes not restricted when called from vdSM session

**p44vdc** (`vdc.cpp:830`): When the caller is the vdSM session connection, only `incremental` mode is allowed. Parameters `exhaustive`, `reenumerate`, and `clearconfig` are silently forced to false.

**pydsvdcapi**: Accepts the method from any caller without restriction. All mode parameters are not surfaced to application code anyway (pydsvdcapi always does a reset-and-re-announce), but the guard logic does not exist.

**Impact**: Low severity in practice because pydsvdcapi's scanDevices implementation is simpler than p44vdc's; it doesn't have a concept of exhaustive/reenumerate/clearconfig rescan. However, the safety boundary that p44vdc enforces is absent.

---

### 🟡 #9 — `pair`: `disableProximityCheck` parameter not passed through

**p44vdc** (`vdc.cpp:852`):
```
disableProximityCheck  bool — disable hardware proximity detection for pairing
```

**pydsvdcapi** (`vdc_host.py` genericRequest handler):
```
establish  bool (default True)
timeout    int  (default -1)
```
`disableProximityCheck` is not extracted or passed to the `on_pair` callback.

**Impact**: Technologies that support proximity-based pairing (e.g. EnOcean learn-in) cannot be told to skip the proximity check via the vdSM. This only affects use cases where the configurator explicitly requests `disableProximityCheck=true`.

---

### 🟡 #10 — `identify`: `duration` parameter ignored

**Message**: `VDSM_NOTIFICATION_IDENTIFY`

**p44vdc** (`dsaddressable.cpp:398`):
```
duration  double (seconds, optional) — 0 means device-default duration
```

**pydsvdcapi**: No `duration` parameter extracted or passed to the `on_identify` callback.

**Impact**: The vdSM can request a specific identify duration (e.g. blink for 3 seconds vs. indefinitely). pydsvdcapi ignores this; the application's `on_identify` callback always uses its own fixed duration.

---

### 🟡 #11 — `setProperty`: `preload` flag not handled

**p44vdc** (`dsaddressable.cpp:183`):
```
preload  bool (optional) — if true, use access_write_preload mode
```
`access_write_preload` is a write mode that stages values without immediately applying them (used for batch scene writes).

**pydsvdcapi**: The `preload` field in `VDSM_REQUEST_SET_PROPERTY` is not read. All writes are applied immediately.

**Impact**: Staged/preload write sequences from the vdSM will be applied immediately instead of being buffered. For scene programming operations that use preload this could result in intermediate channel states being applied to hardware prematurely.

---

### 🟡 #12 — `x-p44-*` device methods not implemented

**p44vdc** handles the following methods on `Device` (dispatched via `genericRequest`):

| Method | Purpose |
|--------|---------|
| `x-p44-removeDevice` | Software-initiated device removal (for disconnectable devices) |
| `x-p44-teachInSignal` | Send a teach-in radio signal from the device (`variant` param) |
| `x-p44-syncChannels` | Read current channel values from hardware, return to caller |

None of these appear in pydsvdcapi. They would fall through to the `on_message` catch-all callback if set, otherwise return `ERR_NOT_IMPLEMENTED`.

**Impact**: Low for most use cases. `x-p44-syncChannels` is used by the dSS configurator to synchronise displayed values with actual hardware state; without it the configurator may show stale values.

---

### 🟡 #13 — `VDC_SEND_IDENTIFY` outbound message not implemented

**p44vdc** (`pbufvdcapi.cpp:1569`): Can send `VDC_SEND_IDENTIFY` (type `VDCAPI__TYPE__VDC_SEND_IDENTIFY`) to notify the vdSM that a device has identified itself (e.g. learned in via physical button press).

**pydsvdcapi**: This outbound message is not documented and not sent. The `identify` method in the genericRequest handler is an inbound handler (vdSM → vDC), not an outbound push.

**Impact**: If a pydsvdcapi device supports hardware learn-in (physical pairing), there is no mechanism to notify the vdSM that identification occurred. This affects pair/unpair workflows that rely on the vDC proactively reporting a device has been physically identified.

---

### 🟢 #14 — `channelStates` push: p44vdc not implemented; pydsvdcapi is

**p44vdc** (`outputbehaviour.cpp:313`): The code block that would push `channelStates` to the vdSM is explicitly marked as dead code with a TODO comment: *"pushing to dS is not yet implemented"*. Channel state updates only go to the JSON Bridge API.

**pydsvdcapi**: `output.push_changes == True` causes a `VDC_SEND_PUSH_NOTIFICATION` with `changedproperties.channelStates` to be sent whenever `OutputChannel.update_value()` is called.

**Classification**: pydsvdcapi is ahead of p44vdc here. The push is part of the vDC API spec, and pydsvdcapi correctly implements it. This is not a conformance problem for pydsvdcapi; it is a gap in p44vdc. Noted for completeness.

---

### 🟢 #15 — `setControlValue`: pydsvdcapi passes `group`/`zone_id` to callback

**p44vdc**: After audience routing, only `name` and `value` are used. `group` and `zone_id` are not passed to the device handler.

**pydsvdcapi**: Passes all four (`name`, `value`, `group`, `zone_id`) to the `on_control_value` callback.

**Classification**: Harmless extension. Giving application code more context is not a protocol violation. The vdSM sends these fields regardless; pydsvdcapi just surfaces them.

---

### 🟢 #16 — `VDSM_SEND_BYE` session requirement

**p44vdc** (`vdchost.cpp:1358`): Explicitly accepts and responds to `bye` even without an active session ("always confirm Bye, even out-of-session").

**pydsvdcapi** (quick-reference table): `ACTIVE` state required for `bye`. Out-of-session bye would likely be silently ignored or cause an error.

**Classification**: In practice, `bye` is only ever sent after `hello` has been acknowledged, so this divergence is unlikely to matter. Low severity.

---

## Cross-cutting observations

### setOutputChannelValue is the most critical gap

Items #1 and #7 together mean that `setOutputChannelValue` — one of the most frequently used control messages — handles only a subset of its spec. Any device type that relies on motor-mode (`move`), custom transition times, or dial-sync modes is non-functional under pydsvdcapi.

### Presence / liveness model is fundamentally different

p44vdc models device presence as a queryable hardware state: ping triggers `checkPresence()`, which can query the physical device, and the result is pushed as an `"active"` property change. pydsvdcapi has no device-level presence model; it always reports present by responding to pong immediately. This means the vdSM cannot detect offline/unavailable devices through pydsvdcapi.

### Missing notifications reduce control surface

`stopOutput` (#2) and `transitionTime` on `callScene` (#5) mean that smooth/controlled stop and custom fade transitions — both common dSS features — have no effect on pydsvdcapi devices. This would be visible to end users operating scenes.
