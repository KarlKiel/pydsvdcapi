# Device Lifecycle States — Design Spec

**Goal:** Implement correct ping/pong presence handling (conformance finding #1) by adding a `DeviceLifecycleState` enum to `Vdsd`. Library users set the state via a single async method; the library handles all vdSM/dSS communication internally.

**Architecture:** Four files change. A new enum lives in `enums.py`. `Vdsd` replaces its bare `_active` bool with a lifecycle state and gains an async setter that pushes the `active` property and triggers vanish as needed. `VdcSession` gains an optional async presence-checker callback. `VdcHost` implements the dSUID lookup and registers the callback after `hello`.

**Tech Stack:** Python 3.11+, asyncio, protobuf (existing), pytest.

---

## Responsibility split

| Responsibility | Owner |
|---|---|
| Detect device health / choose state | Library user (their own polling / callbacks) |
| Push `active` property to dSS on change | Library (`Vdsd.set_lifecycle_state`) |
| Gate pong responses based on state | Library (`VdcSession._handle_ping`) |
| Trigger `vanish` when `REMOVED` | Library (`Vdsd.set_lifecycle_state` + ping handler) |

---

## 1. `DeviceLifecycleState` enum — `enums.py`

```python
class DeviceLifecycleState(str, Enum):
    ACTIVE      = "active"       # operational; pong + active=true
    INACTIVE    = "inactive"     # temporarily unavailable; no pong + active=false
    MAINTENANCE = "maintenance"  # scheduled downtime; no pong + active=false
    ERROR       = "error"        # hardware fault; no pong + active=false
    REMOVED     = "removed"      # decommissioned; vanish + no pong + active=false
```

`INACTIVE`, `MAINTENANCE`, and `ERROR` are semantically distinct (for the application developer's logging and reasoning) but are protocol-identical: they all suppress pong and push `active=false`. `REMOVED` additionally triggers the vanish procedure.

---

## 2. `Vdsd` changes — `vdsd.py`

### State storage

Replace:
```python
self._active: bool = True
```
With:
```python
self._lifecycle_state: DeviceLifecycleState = DeviceLifecycleState.ACTIVE
```

### `active` property (read-only, backward compatible)

The existing `active` getter is preserved as a derived property:
```python
@property
def active(self) -> bool:
    return self._lifecycle_state == DeviceLifecycleState.ACTIVE
```

The existing `active` setter is **removed**. `set_lifecycle_state()` is the new write path.

> **Breaking change:** Any existing code that writes `vdsd.active = False` must be updated to `await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)`. Code that only reads `vdsd.active` is unaffected.

### `lifecycle_state` property (read-only)

```python
@property
def lifecycle_state(self) -> DeviceLifecycleState:
    return self._lifecycle_state
```

### `async set_lifecycle_state(state: DeviceLifecycleState) -> None`

```python
async def set_lifecycle_state(self, state: DeviceLifecycleState) -> None:
    was_active = self._lifecycle_state == DeviceLifecycleState.ACTIVE
    self._lifecycle_state = state
    now_active = state == DeviceLifecycleState.ACTIVE

    if self._announced and self._session is not None:
        # Push active property if it changed
        if was_active != now_active:
            await self._push_active(now_active)
        # Trigger vanish for REMOVED state
        if state == DeviceLifecycleState.REMOVED:
            await self.vanish(self._session)
    # If not yet announced: store state silently; no session to push to
```

### `async _push_active(active: bool) -> None` (private helper)

Sends `VDC_SEND_PUSH_NOTIFICATION` with `changedproperties.active`:

```python
async def _push_active(self, active: bool) -> None:
    msg = pb.Message()
    msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
    msg.vdc_send_push_notification.dSUID = str(self._dsuid)
    elem = pb.PropertyElement()
    elem.name = "active"
    elem.value.v_bool = active
    msg.vdc_send_push_notification.changedproperties.append(elem)
    await self._session.send_notification(msg)
```

### `get_common_properties()` — no change needed

`active` is already derived from `_active` (now derived from `_lifecycle_state`); the property tree serialises the same value.

---

## 3. `VdcSession` changes — `session.py`

### Optional presence-checker callback

```python
self._presence_checker: Callable[[str], Awaitable[bool]] | None = None
```

A method to register it (called by `VdcHost`):

```python
def set_presence_checker(
    self, checker: Callable[[str], Awaitable[bool]]
) -> None:
    self._presence_checker = checker
```

### Updated `_handle_ping()`

```python
async def _handle_ping(self, msg: pb.Message) -> None:
    target_dsuid = msg.vdsm_send_ping.dSUID
    self._ping_count += 1

    if self._presence_checker is not None:
        present = await self._presence_checker(target_dsuid)
    else:
        present = True  # backward-compatible default

    if not present:
        logger.debug(
            "Ping #%d for %s — device not present, suppressing pong",
            self._ping_count,
            target_dsuid,
        )
        return

    pong = pb.Message()
    pong.type = pb.VDC_SEND_PONG
    pong.message_id = 0
    pong.vdc_send_pong.dSUID = target_dsuid or self._host_dsuid
    await self._conn.send(pong)
    logger.debug("Ping #%d for %s — pong sent", self._ping_count, target_dsuid)
```

**Backward compatibility:** If no presence checker is registered (e.g. in unit tests or custom session setups), the handler always pongs — identical to the current behaviour.

---

## 4. `VdcHost` changes — `vdc_host.py`

### `_find_vdsd(dsuid: str) -> Vdsd | None`

Traverses `host → vdc → device → vdsd`:

```python
def _find_vdsd(self, dsuid: str) -> Vdsd | None:
    for vdc in self._vdcs:
        for device in vdc.devices:
            for vdsd in device.vdsds:
                if str(vdsd.dsuid) == dsuid:
                    return vdsd
    return None
```

### Presence checker registration

After `hello` succeeds (in the existing `on_hello` handler), register the checker on the session. The inner function captures `self` (the `VdcHost` instance) and the current `session` object via closure:

```python
# session is the VdcSession just established (self._session at this point)
async def _presence_check(dsuid: str) -> bool:
    # Empty or host dSUID → always present
    if not dsuid or dsuid == self._host_dsuid:
        return True
    vdsd = self._find_vdsd(dsuid)
    if vdsd is None:
        return True  # unknown dSUID → pong (backward compat)
    if vdsd.lifecycle_state == DeviceLifecycleState.REMOVED:
        await vdsd.vanish(self._session)  # re-vanish on repeated ping
    return vdsd.lifecycle_state == DeviceLifecycleState.ACTIVE

self._session.set_presence_checker(_presence_check)
```

---

## 5. Ping flow summary

```
vdSM sends VDSM_SEND_PING(dSUID="abc123")
  → session._handle_ping()
      → presence_checker("abc123")
          → vdc_host._find_vdsd("abc123") → vdsd
          → vdsd.lifecycle_state == ACTIVE?
              ACTIVE       → return True  → pong sent
              INACTIVE     → return False → pong suppressed
              MAINTENANCE  → return False → pong suppressed
              ERROR        → return False → pong suppressed
              REMOVED      → vanish() then return False → pong suppressed
```

---

## 6. Lifecycle state transitions

```
              set_lifecycle_state(INACTIVE/MAINTENANCE/ERROR)
ACTIVE ──────────────────────────────────────────────────────► non-ACTIVE
  ◄──────────────────────────────────────────────────────────
              set_lifecycle_state(ACTIVE)

ACTIVE/non-ACTIVE ──► REMOVED  (vanish sent; no return from REMOVED)
```

On any transition that changes `active` (true↔false):
- `VDC_SEND_PUSH_NOTIFICATION` with `changedproperties.active` is sent immediately.
- dSS does not need to poll — it is notified proactively.

Repeated calls to `set_lifecycle_state()` with the same state are no-ops for the push (no change in `active` value); the state is stored but no notification is sent.

---

## 7. Testing

New test file: `tests/test_lifecycle_state.py` (or additions to `tests/test_vdsd.py`).

Key test cases:
- `test_default_state_is_active` — `vdsd.lifecycle_state == ACTIVE`, `vdsd.active == True`
- `test_set_inactive_pushes_active_false` — push notification sent with `active=False`
- `test_set_active_pushes_active_true` — push notification sent with `active=True`
- `test_no_push_if_active_unchanged` — INACTIVE → MAINTENANCE sends no push (both are `active=False`)
- `test_set_removed_sends_vanish` — `vanish()` called on session
- `test_removed_ping_triggers_revanish` — ping on REMOVED device calls `vanish()` again
- `test_inactive_ping_suppressed` — ping on INACTIVE device: no pong sent
- `test_active_ping_answered` — ping on ACTIVE device: pong sent
- `test_no_push_before_announced` — `set_lifecycle_state` before announce: no push, no error
- `test_no_presence_checker_always_pongs` — backward-compat: session without checker always pongs
- `test_unknown_dsuid_always_pongs` — unknown dSUID falls back to pong
