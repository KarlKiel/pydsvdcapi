# vDC API Conformance Analysis: pydsvdcapi vs p44vdc

Systematic comparison of pydsvdcapi (Python library) against p44vdc (C++ reference implementation).
Both must conform to the same vdSM ↔ vDC protobuf API (versions 2–3).

**Sources compared:**
- `docs/message-flow-reference.md` — pydsvdcapi behavior
- `docs/p44vdc-message-flow-reference.md` — p44vdc behavior
- `pbuf/vdcapi.proto` — authoritative protobuf wire format (what the vdSM actually sends)

**Severity scale:**

| Level | Meaning |
|-------|---------|
| 🔴 CRITICAL | Silent data loss or protocol failure; vdSM command has no effect or wrong effect |
| 🟠 HIGH | Significant behavioral divergence; basic use works but specific scenarios fail |
| 🟡 MEDIUM | Feature gap; pydsvdcapi ignores a parameter or method the vdSM may send |
| 🟢 LOW | Implementation detail or convention difference; no observable protocol impact |
| ⚪ N/A | Not part of the protobuf API; JSON-API-only feature, vdSM does not send via protobuf |

---

## Proto-vs-implementation note

The `.proto` file (`pbuf/vdcapi.proto`) is the authoritative definition of what the standard vdSM sends.
p44vdc also exposes a JSON API (for tools like `p44mbrd`, the Matter bridge daemon), which supports
additional parameters not present in the protobuf schema. Several findings from the initial
analysis were based on the C++ handler code without cross-checking the proto; those findings
are re-classified below.

### Why the proto schema is conclusive — typed fields vs. PropertyElement

The vDC API uses two fundamentally different wire structures, and only one of them is generic:

**Typed proto fields** — used by all notification messages (`setOutputChannelValue`, `dimChannel`,
`callScene`, etc.). Each field has a fixed field number and a concrete type (`int32`, `double`,
`bool`, `string`). The vdSM serialises only defined fields at their assigned field numbers. A
field like `move` has no assigned field number in `vdsm_NotificationSetOutputChannelValue`, so
the vdSM has no way to include it in the binary encoding. On the p44vdc side,
`getObjectFromMessageFields()` iterates the compiled C proto descriptor, reading only the typed
fields the proto defines — it cannot see a key named `"move"` because no such typed field exists.

**PropertyElement trees** — the generic `{ name: string, value: PropertyValue, elements: [...] }`
structure that IS arbitrary key-value. But PropertyElement appears only in:
`getProperty` (query + response), `setProperty` (properties), `genericRequest` (params), and
`pushNotification` (changedproperties/deviceevents). It is absent from every notification message.

The extra parameters (`move`, `rate`, `dimPerMS`, `transitionTime`, `duration`, `preload`, etc.)
appear in p44vdc's C++ handler functions because the **same handler is called from both the typed
protobuf path and the JSON/genericRequest path**. When invoked from a standard vdSM typed
notification, `aParams->get("move")` returns null and the branch is never taken. The C++ comment
`// TODO: implement "direction" (as sent by p44mbrd)` explicitly identifies `p44mbrd` (the Matter
bridge daemon, which uses the JSON API) as the source — not the vdSM.

**Protobuf schema of the most-affected messages:**

```protobuf
message vdsm_NotificationCallScene {
    repeated string dSUID = 1;
    optional int32 scene = 2;
    optional bool force = 3;
    optional int32 group = 4;
    optional int32 zone_id = 5;
    // no transitionTime
}

message vdsm_NotificationDimChannel {
    repeated string dSUID = 1;
    optional int32 channel = 2;
    optional int32 mode = 3;
    optional int32 area = 4;
    optional int32 group = 5;
    optional int32 zone_id = 6;
    optional string channelId = 7;  // API v3
    // no dimPerMS, fullRangeTime, force, autoStop, stopActions
}

message vdsm_NotificationSetOutputChannelValue {
    repeated string dSUID = 1;
    optional bool apply_now = 2 [default = true];
    optional int32 channel = 3;
    optional double value = 4;
    optional string channelId = 5;  // API v3
    // no move, rate, transitionTime, direction, sync, previous, onoff, coupling
}

message vdsm_NotificationIdentify {
    repeated string dSUID = 1;
    optional int32 group = 2;
    optional int32 zone_id = 3;
    // no duration
}

message vdsm_RequestSetProperty {
    optional string dSUID = 1;
    repeated PropertyElement properties = 2;
    // no preload
}
```

---

## Summary table

| # | Message / Area | Severity | Direction of gap |
|---|----------------|----------|-----------------|
| 1 | `VDSM_SEND_PING` — presence check implemented via `DeviceLifecycleState` | ✅ | **resolved in v0.9.0** |
| 2 | `hello` — API version bounds + vdSM identity check | ✅ | **resolved in v0.9.0** |
| 3 | `VDC_SEND_IDENTIFY` outbound not implemented | 🟡 | pydsvdcapi missing |
| 4 | `x-p44-*` device methods not implemented | 🟡 | pydsvdcapi missing |
| 5 | `channelStates` push — p44vdc explicitly not implemented for DS API | 🟢 | p44vdc missing (pydsvdcapi correct) |
| 6 | `setControlValue` — pydsvdcapi passes `group`/`zone_id` to callback | 🟢 | harmless extension |
| 7 | `VDSM_SEND_BYE` — pydsvdcapi requires ACTIVE state; p44vdc accepts out-of-session | 🟢 | minor divergence |
| 8 | `setOutputChannelValue` — `move`/`rate` parameters | ⚪ | JSON-API-only, vdSM does not send |
| 9 | `setOutputChannelValue` — `transitionTime`, `sync`, `coupling`, etc. | ⚪ | JSON-API-only, vdSM does not send |
| 10 | `callScene` — `transitionTime` override | ⚪ | JSON-API-only, vdSM does not send |
| 11 | `dimChannel` — `dimPerMS`, `fullRangeTime`, `force`, `autoStop`, `stopActions` | ⚪ | JSON-API-only, vdSM does not send |
| 12 | `identify` — `duration` parameter | ⚪ | JSON-API-only, vdSM does not send |
| 13 | `setProperty` — `preload` flag | ⚪ | JSON-API-only, vdSM does not send |
| 14 | `stopOutput` notification | ⚪ | JSON-API-only, vdSM does not send |

---

## Detailed findings

---

### ✅ #1 — `VDSM_SEND_PING`: presence check implemented via `DeviceLifecycleState` *(resolved v0.9.0)*

**p44vdc** (`dsaddressable.cpp:390` → `pingResultHandler`):
1. Audience-resolves the target device by dSUID
2. Calls `checkPresence()` (may be async; device-specific, can talk to hardware)
3. Sends `VDC_SEND_PONG` **only** if the device reports itself as present
4. Updates `mPresent` state; if changed, pushes `"active"` property to vdSM

**pydsvdcapi** (v0.9.0+, `vdsd.py` / `session.py` / `vdc_host.py`):
1. Library user calls `await vdsd.set_lifecycle_state(DeviceLifecycleState.X)` when device health changes
2. `VdcHost` registers an async presence checker on each session that resolves the target dSUID to a `Vdsd`
3. `_handle_ping` calls the checker before sending pong:
   - `ACTIVE` → pong sent + no push (no change)
   - `INACTIVE` / `MAINTENANCE` / `ERROR` → pong suppressed
   - `REMOVED` → `VDC_SEND_VANISH` sent (re-triggered on every subsequent ping) + pong suppressed
4. On any `active` state change (true↔false), `VDC_SEND_PUSH_NOTIFICATION` with `changedproperties.active` is sent immediately — dSS does not need to poll

**Remaining difference**: p44vdc's `checkPresence()` can actively query hardware (the device decides its own presence). pydsvdcapi instead requires the library user to poll their hardware and call `set_lifecycle_state()`. This is by design: the library user owns the device-level health check; the library owns the protocol communication.

The pong dSUID behaviour is unchanged: pydsvdcapi echoes the incoming dSUID field directly. The wire value is the same as p44vdc.

---

### ✅ #2 — `hello`: API version bounds + vdSM identity check *(resolved v0.9.0)*

**p44vdc** (`vdchost.cpp:1310`):
Accepts `VDC_API_VERSION_MIN (2) ≤ api_version ≤ VDC_API_VERSION_MAX (3)`. Versions outside
that range are rejected with `ERR_INCOMPATIBLE_API`. Same-dSUID re-hello resets the session
and re-announces; different-dSUID hello during an active session is rejected with
`ERR_SERVICE_NOT_AVAILABLE`.

**pydsvdcapi** (v0.9.0+, `session.py`):

1. **API version range** — `SUPPORTED_API_VERSION (2) ≤ api_version ≤ MAX_SUPPORTED_API_VERSION (4)`. Both bounds are enforced with `ERR_INCOMPATIBLE_API`. The upper bound is set to 4 (one beyond p44vdc's current maximum of 3) to allow for imminent protocol updates while preventing silent mishandling of further-future breaking versions.

2. **Unknown vdSM during active session** — a hello from a dSUID that does not match the currently connected vdSM is rejected with `ERR_SERVICE_NOT_AVAILABLE`. The existing session is preserved.

3. **Same vdSM reconnect** — a re-hello from the same dSUID signals the vdSM has lost track of the still-open connection. The session is reset (`_reset_session_state`: pending requests cancelled, counters zeroed) and `on_hello` fires again so `VdcHost` re-announces all vDCs and devices, restoring stable communication.

---

### 🟡 #3 — `VDC_SEND_IDENTIFY` outbound message not implemented

**Proto definition**: `message vdc_SendIdentify { optional string dSUID = 1; }` — this IS a proper
protobuf message (type `VDCAPI__TYPE__VDC_SEND_IDENTIFY`), not JSON-API-only.

**p44vdc** (`pbufvdcapi.cpp:1569`): Can send `VDC_SEND_IDENTIFY` to notify the vdSM that a device
has identified itself (e.g. physically learned-in via button press).

**pydsvdcapi**: This outbound message is not documented and not sent. The `identify` method in the
genericRequest handler is an inbound handler (vdSM → vDC), not an outbound push.

**Impact**: If a pydsvdcapi device supports hardware learn-in (physical pairing), there is no
mechanism to notify the vdSM that identification occurred. This affects pair/unpair workflows that
rely on the vDC proactively reporting that a device has been physically identified.

---

### 🟡 #4 — `x-p44-*` device methods not implemented

Dispatched via `genericRequest` with those method names — `genericRequest` IS in the protobuf proto
(`vdsm_RequestGenericRequest`), so these ARE reachable from the standard vdSM.

**p44vdc** handles the following methods on `Device`:

| Method | Purpose |
|--------|---------|
| `x-p44-removeDevice` | Software-initiated device removal (for disconnectable devices) |
| `x-p44-teachInSignal` | Send a teach-in radio signal from the device (`variant` param) |
| `x-p44-syncChannels` | Read current channel values from hardware, return to caller |

None of these appear in pydsvdcapi. They would fall through to the `on_message` catch-all callback
if set, otherwise return `ERR_NOT_IMPLEMENTED`.

**Impact**: Low for most use cases. `x-p44-syncChannels` is used by the dSS configurator to
synchronise displayed values with actual hardware state; without it the configurator may show
stale values. `x-p44-removeDevice` and `x-p44-teachInSignal` are p44-proprietary extensions
unlikely to be sent to non-p44vdc vDCs.

---

### 🟢 #5 — `channelStates` push: p44vdc not implemented for DS API; pydsvdcapi is

**p44vdc** (`outputbehaviour.cpp:313`): The code block that would push `channelStates` to the vdSM
is explicitly marked as dead code with a TODO comment: *"pushing to dS is not yet implemented"*.
Channel state updates only go to the JSON Bridge API.

**pydsvdcapi**: `output.push_changes == True` causes a `VDC_SEND_PUSH_NOTIFICATION` with
`changedproperties.channelStates` to be sent whenever `OutputChannel.update_value()` is called.

**Classification**: pydsvdcapi is ahead of p44vdc here. The push is part of the vDC API spec and
pydsvdcapi correctly implements it. This is not a conformance problem for pydsvdcapi.

---

### 🟢 #6 — `setControlValue`: pydsvdcapi passes `group`/`zone_id` to callback

**p44vdc**: After audience routing, only `name` and `value` are used at the device handler level.
`group` and `zone_id` are used only for audience resolution, not forwarded to device logic.

**pydsvdcapi**: Passes all four (`name`, `value`, `group`, `zone_id`) to the `on_control_value`
callback.

**Classification**: Harmless extension. Giving application code more context is not a protocol
violation. The vdSM sends these fields regardless; pydsvdcapi just surfaces them.

---

### 🟢 #7 — `VDSM_SEND_BYE` session requirement

**p44vdc** (`vdchost.cpp:1358`): Explicitly accepts and responds to `bye` even without an active
session ("always confirm Bye, even out-of-session").

**pydsvdcapi**: `ACTIVE` state required for `bye`. Out-of-session bye would be silently ignored or
cause an error.

**Classification**: In practice, `bye` is only ever sent after `hello` has been acknowledged, so
this divergence is unlikely to matter.

---

### ⚪ #8 — `setOutputChannelValue`: `move`/`rate` parameters (JSON-API-only)

The protobuf `vdsm_NotificationSetOutputChannelValue` has no `move` or `rate` field. These
parameters exist only in p44vdc's JSON API path, used by tools such as `p44mbrd` (the Matter bridge
daemon). The standard vdSM never sends them via the protobuf protocol.

**Shadow device note**: `move`/`rate` map to `ChannelBehaviour::moveChannelValue()`, which is a
generic mechanism that works for any channel with a non-zero dimPerMS rate. Shadow position channels
do have a non-zero dimPerMS (derived from `mFullRangeTime`, default 50 s). But the standard
vdSM controls shade/blind position via `callScene` (absolute position) and `dimChannel` (motor
start/stop). The `move` parameter in `setOutputChannelValue` is not part of the standard vdSM
control flow for any device type including shadow.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #9 — `setOutputChannelValue`: extra value parameters (JSON-API-only)

`transitionTime`, `direction`, `sync`, `previous`, `onoff`, `coupling` — none of these are in the
protobuf schema for `vdsm_NotificationSetOutputChannelValue`. They are JSON-API-only parameters.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #10 — `callScene`: `transitionTime` override (JSON-API-only)

The protobuf `vdsm_NotificationCallScene` has no `transitionTime` field. It is a JSON-API-only
parameter.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #11 — `dimChannel`: extra parameters (JSON-API-only)

`dimPerMS`, `fullRangeTime`, `force`, `autoStop`, `stopActions` — none of these are in the
protobuf schema for `vdsm_NotificationDimChannel`. They are JSON-API-only parameters.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #12 — `identify`: `duration` parameter (JSON-API-only)

The protobuf `vdsm_NotificationIdentify` has no `duration` field. It is a JSON-API-only parameter.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #13 — `setProperty`: `preload` flag (JSON-API-only)

The protobuf `vdsm_RequestSetProperty` has no `preload` field. It is a JSON-API-only parameter.

**Not a gap vs. the standard vdSM protobuf API.**

---

### ⚪ #14 — `stopOutput` notification (JSON-API-only)

`stopOutput` has no dedicated protobuf message type and is not in `vdcapi.proto`. In p44vdc it is
handled when arriving as a JSON API notification or embedded in a JSON `genericRequest`. The
standard vdSM does not send this via protobuf.

**Not a gap vs. the standard vdSM protobuf API.**

---

## Cross-cutting observations

### Presence / liveness model — resolved in v0.9.0

p44vdc models device presence as a queryable hardware state: ping triggers `checkPresence()`, which
can query the physical device, and the result is pushed as an `"active"` property change. pydsvdcapi
now implements equivalent semantics via `DeviceLifecycleState`: library users call
`await vdsd.set_lifecycle_state(...)` when device health changes, and the library handles all
vdSM communication (pong suppression, `active` push, vanish). The model is push-based rather than
query-based, which is appropriate for a Python library where hardware access belongs to the
application layer.

### JSON-API-only parameters are not a conformance gap

A large portion of the parameters handled by p44vdc's C++ code (for `setOutputChannelValue`,
`dimChannel`, `callScene`, `identify`, `setProperty`) exist only in the JSON API path and are not
part of the protobuf wire format. Cross-checking against `vdcapi.proto` before raising a conformance
issue is essential — the handler code and the proto schema do not always match.

### Protobuf API coverage is essentially complete

For all message types and fields defined in `vdcapi.proto`, pydsvdcapi correctly handles the
mandatory and optional fields that the standard vdSM sends. The remaining real gaps (#3–#4) are missing outbound/inbound genericRequest support for
p44-proprietary extensions. Findings #1 and #2 are resolved in v0.9.0.
