# Persistent `pendingVanish` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a vDC or device is removed while the session is offline, persist the deleted dSUIDs in YAML and flush `VDC_SEND_VANISH` messages to the vdSM on the next reconnect, so the vdSM database never retains stale entries.

**Architecture:** `VdcHost` owns a `_pending_vanish: set[str]` (dSUID strings). `remove_vdc()` adds the vDC dSUID plus all its Vdsd dSUIDs; `Vdc.remove_device()` adds all Vdsd dSUIDs. Both paths go through a `_add_pending_vanish()` helper that updates the set and schedules an auto-save. `get_property_tree()` serialises the set as `pendingVanish`; `_apply_state()` restores it. `_on_session_ready()` calls `_flush_pending_vanish()` before re-announcing surviving vDCs, which sends `VDC_SEND_VANISH` for each entry, clears the set, and saves. vdSM-initiated removals (`_handle_remove`) pass `track_vanish=False` to `Vdc.remove_device()` so they do NOT populate the list — the vdSM already removed those devices itself.

**Tech Stack:** Python 3.10+, asyncio, protobuf (`vdc_messages_pb2`), pytest-asyncio, `unittest.mock`.

---

## File Structure

- **Modify:** `src/pydsvdcapi/vdc_host.py`
  - `__init__`: initialise `_pending_vanish`
  - `remove_vdc()`: collect dSUIDs before removing, call `_add_pending_vanish()`
  - `get_property_tree()`: serialise `pendingVanish` when non-empty
  - `_apply_state()`: restore `_pending_vanish` from saved state
  - New `_add_pending_vanish()`: update set + schedule save
  - New `_flush_pending_vanish()`: send vanishes + clear + save
  - `_on_session_ready()`: call flush before announcing
  - `_handle_remove()`: pass `track_vanish=False`

- **Modify:** `src/pydsvdcapi/vdc.py`
  - `remove_device()`: add `track_vanish: bool = True` parameter; call `self._host._add_pending_vanish()` when True

- **Modify:** `tests/test_vdc_host.py` — append two new test classes
- **Modify:** `docs/vdc-host-behavior.md` — add §2.7

---

### Task 1: `_pending_vanish` infrastructure in `VdcHost`

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py`
- Modify: `tests/test_vdc_host.py` (append after line 841)

- [ ] **Step 1: Write the failing tests**

Append this class at the end of `tests/test_vdc_host.py`:

```python
# ---------------------------------------------------------------------------
# _pending_vanish — persistence and flush infrastructure
# ---------------------------------------------------------------------------


class TestPendingVanishInfrastructure:
    """Tests for VdcHost._pending_vanish init, persistence, and flush."""

    def test_pending_vanish_empty_by_default(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        assert host._pending_vanish == set()

    def test_add_pending_vanish_updates_set(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._add_pending_vanish({"aabbcc", "ddeeff"})
        assert host._pending_vanish == {"aabbcc", "ddeeff"}

    def test_pending_vanish_serialised_in_property_tree(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"aabbcc"}
        tree = host.get_property_tree()
        assert "pendingVanish" in tree["vdcHost"]
        assert "aabbcc" in tree["vdcHost"]["pendingVanish"]

    def test_pending_vanish_omitted_when_empty(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        tree = host.get_property_tree()
        assert "pendingVanish" not in tree["vdcHost"]

    def test_apply_state_restores_pending_vanish(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._apply_state({"pendingVanish": ["aabbcc", "ddeeff"]})
        assert "aabbcc" in host._pending_vanish
        assert "ddeeff" in host._pending_vanish

    @pytest.mark.asyncio
    async def test_flush_sends_vanish_for_each_dsuid(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"aaaa", "bbbb"}

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        sent = {
            call.args[0].vdc_send_vanish.dSUID
            for call in session.send_notification.call_args_list
        }
        assert sent == {"aaaa", "bbbb"}

    @pytest.mark.asyncio
    async def test_flush_clears_pending_vanish(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"cccc"}

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        assert host._pending_vanish == set()

    @pytest.mark.asyncio
    async def test_flush_noop_when_empty(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        session.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_session_ready_flushes_pending_vanish(self):
        """_on_session_ready must send pending vanishes before announcing."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        host._pending_vanish = {"stale-dsuid"}

        ok_resp = pb.Message()
        ok_resp.generic_response.code = pb.ERR_OK
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        session.send_notification = AsyncMock()
        session.send_request = AsyncMock(return_value=ok_resp)

        await host._on_session_ready(session)

        vanished = {
            call.args[0].vdc_send_vanish.dSUID
            for call in session.send_notification.call_args_list
            if call.args[0].type == pb.VDC_SEND_VANISH
        }
        assert "stale-dsuid" in vanished
        assert host._pending_vanish == set()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestPendingVanishInfrastructure -v
```

Expected: all 9 tests FAIL — `AttributeError: 'VdcHost' object has no attribute '_pending_vanish'`.

- [ ] **Step 3: Implement the infrastructure in `vdc_host.py`**

**Edit 1** — initialise `_pending_vanish` in `__init__`. Locate this block (around line 336):

```python
        # --- vDC registry ---------------------------------------------
        self._vdcs: dict[str, Vdc] = {}  # keyed by dSUID string

        # --- auto-save ------------------------------------------------
```

Replace with:

```python
        # --- vDC registry ---------------------------------------------
        self._vdcs: dict[str, Vdc] = {}  # keyed by dSUID string

        # --- pending vanish -------------------------------------------
        self._pending_vanish: set[str] = set()

        # --- auto-save ------------------------------------------------
```

**Edit 2** — serialise `_pending_vanish` in `get_property_tree()`. Locate this block (around line 573):

```python
        if self._vdcs:
            host_node["vdcs"] = [vdc.get_property_tree() for vdc in self._vdcs.values()]

        return {"vdcHost": host_node}
```

Replace with:

```python
        if self._vdcs:
            host_node["vdcs"] = [vdc.get_property_tree() for vdc in self._vdcs.values()]

        if self._pending_vanish:
            host_node["pendingVanish"] = sorted(self._pending_vanish)

        return {"vdcHost": host_node}
```

**Edit 3** — restore `_pending_vanish` in `_apply_state()`. Locate the end of the method (around line 700), the last `if "deviceIconName"` block:

```python
        if "deviceIconName" in state:
            self.device_icon_name = state["deviceIconName"]

        # Restore vDC properties from persisted state.
```

Replace with:

```python
        if "deviceIconName" in state:
            self.device_icon_name = state["deviceIconName"]

        if "pendingVanish" in state:
            self._pending_vanish.update(state["pendingVanish"])

        # Restore vDC properties from persisted state.
```

**Edit 4** — add `_add_pending_vanish()` helper. Place it in the persistence section, just before `save()` (around line 580). Find:

```python
    # ---- persistence -------------------------------------------------

    def save(self) -> None:
```

Insert before `save()`:

```python
    # ---- persistence -------------------------------------------------

    def _add_pending_vanish(self, dsuids: set[str]) -> None:
        """Track dSUIDs that must be vanished on the next session.

        Called when a vDC or device is removed while no session is active.
        The set is persisted in YAML so a restart does not lose the list.
        """
        self._pending_vanish.update(dsuids)
        if self._auto_save_enabled:
            self._schedule_auto_save()

    def save(self) -> None:
```

**Edit 5** — add `_flush_pending_vanish()`. Place it just before `_on_session_ready()` (around line 980). Find:

```python
    async def _on_session_ready(self, session: VdcSession) -> None:
```

Insert before it:

```python
    async def _flush_pending_vanish(self, session: VdcSession) -> None:
        """Send VDC_SEND_VANISH for every dSUID in _pending_vanish, then clear.

        Runs at the start of _on_session_ready() so the vdSM processes
        offline deletions before receiving re-announcement of survivors.
        """
        if not self._pending_vanish:
            return
        logger.info("Flushing %d pending vanish(es)", len(self._pending_vanish))
        for dsuid_str in list(self._pending_vanish):
            msg = pb.Message()
            msg.type = pb.VDC_SEND_VANISH
            msg.vdc_send_vanish.dSUID = dsuid_str
            try:
                await session.send_notification(msg)
                logger.debug("Sent pending vanish for %s", dsuid_str)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to send pending vanish for %s", dsuid_str)
        self._pending_vanish.clear()
        if self._auto_save_enabled:
            self._schedule_auto_save()

    async def _on_session_ready(self, session: VdcSession) -> None:
```

**Edit 6** — call `_flush_pending_vanish` at the start of `_on_session_ready()`. Find:

```python
    async def _on_session_ready(self, session: VdcSession) -> None:
        """Auto-announce all registered vDCs and devices on *session*.

        Called by the session's ``on_hello`` hook after the hello
        handshake completes.  This ensures that whenever a vdSM
        (re-)connects, every vDC and device is properly announced on
        the new session — without requiring the caller to re-drive
        the announcement manually.
        """
        logger.info(
            "Session ready — auto-announcing %d vDC(s)",
            len(self._vdcs),
        )
```

Replace with:

```python
    async def _on_session_ready(self, session: VdcSession) -> None:
        """Auto-announce all registered vDCs and devices on *session*.

        Called by the session's ``on_hello`` hook after the hello
        handshake completes.  This ensures that whenever a vdSM
        (re-)connects, every vDC and device is properly announced on
        the new session — without requiring the caller to re-drive
        the announcement manually.
        """
        await self._flush_pending_vanish(session)
        logger.info(
            "Session ready — auto-announcing %d vDC(s)",
            len(self._vdcs),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestPendingVanishInfrastructure -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/ -q
```

Expected: all existing tests plus 9 new ones pass.

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "feat: add _pending_vanish infrastructure to VdcHost"
```

---

### Task 2: Wire `remove_vdc()` and `Vdc.remove_device()` to populate `_pending_vanish`

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py` (lines ~473, ~1665)
- Modify: `src/pydsvdcapi/vdc.py` (line ~409)
- Modify: `tests/test_vdc_host.py` (append after Task 1's class)

- [ ] **Step 1: Write the failing tests**

Append this class at the end of `tests/test_vdc_host.py`:

```python
# ---------------------------------------------------------------------------
# _pending_vanish — wiring through remove_vdc / remove_device
# ---------------------------------------------------------------------------


class TestPendingVanishWiring:
    """Tests that remove_vdc and remove_device populate _pending_vanish."""

    def test_remove_vdc_adds_vdc_dsuid_to_pending_vanish(self):
        host, vdc, _device, _vdsd = _make_host_with_device()
        vdc_dsuid = str(vdc.dsuid)

        host.remove_vdc(vdc.dsuid)

        assert vdc_dsuid in host._pending_vanish

    def test_remove_vdc_adds_vdsd_dsuids_to_pending_vanish(self):
        host, vdc, _device, vdsd = _make_host_with_device()
        vdsd_dsuid = str(vdsd.dsuid)

        host.remove_vdc(vdc.dsuid)

        assert vdsd_dsuid in host._pending_vanish

    def test_remove_device_adds_vdsd_dsuids_to_pending_vanish(self):
        host, vdc, device, vdsd = _make_host_with_device()
        vdsd_dsuid = str(vdsd.dsuid)

        vdc.remove_device(device.dsuid)

        assert vdsd_dsuid in host._pending_vanish

    @pytest.mark.asyncio
    async def test_handle_remove_does_not_add_to_pending_vanish(self):
        """vdSM-initiated removal must NOT populate _pending_vanish."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)
        msg = _make_remove_msg(dsuid_str)

        await host._handle_remove(msg)

        assert host._pending_vanish == set()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestPendingVanishWiring -v
```

Expected: all 4 tests FAIL.

- [ ] **Step 3: Update `VdcHost.remove_vdc()` in `vdc_host.py`**

Locate `remove_vdc()` (around line 473):

```python
    def remove_vdc(self, dsuid: DsUid) -> Vdc | None:
        """Remove a registered vDC by its dSUID.

        Returns the removed :class:`Vdc` or ``None`` if no vDC with
        the given dSUID was registered.
        """
        key = str(dsuid)
        vdc = self._vdcs.pop(key, None)
        if vdc is not None:
            logger.info("Removed vDC '%s' (dSUID %s)", vdc.name, key)
            if self._auto_save_enabled:
                self._schedule_auto_save()
        return vdc
```

Replace with:

```python
    def remove_vdc(self, dsuid: DsUid) -> Vdc | None:
        """Remove a registered vDC by its dSUID.

        Returns the removed :class:`Vdc` or ``None`` if no vDC with
        the given dSUID was registered.
        """
        key = str(dsuid)
        vdc = self._vdcs.pop(key, None)
        if vdc is not None:
            logger.info("Removed vDC '%s' (dSUID %s)", vdc.name, key)
            dsuids: set[str] = {key}
            for device in vdc.devices.values():
                for vdsd in device.vdsds.values():
                    dsuids.add(str(vdsd.dsuid))
            self._add_pending_vanish(dsuids)  # also schedules auto-save
        return vdc
```

- [ ] **Step 4: Update `Vdc.remove_device()` in `vdc.py`**

Locate `remove_device()` (around line 409):

```python
    def remove_device(self, dsuid: DsUid) -> Device | None:
        """Remove a device by its base dSUID.

        Returns the removed :class:`Device` or ``None``.
        """
        key = str(dsuid.device_base())
        device = self._devices.pop(key, None)
        if device is not None:
            logger.info("Removed device %s from vDC '%s'", key, self.name)
            if getattr(self, "_auto_save_enabled", False):
                self._host._schedule_auto_save()
        return device
```

Replace with:

```python
    def remove_device(self, dsuid: DsUid, track_vanish: bool = True) -> Device | None:
        """Remove a device by its base dSUID.

        Returns the removed :class:`Device` or ``None``.

        Set ``track_vanish=False`` when the removal was initiated by the
        vdSM (VDSM_SEND_REMOVE) — in that case the vdSM already removed
        the device from its own database and no vanish is needed.
        """
        key = str(dsuid.device_base())
        device = self._devices.pop(key, None)
        if device is not None:
            logger.info("Removed device %s from vDC '%s'", key, self.name)
            if track_vanish:
                dsuids = {str(vdsd.dsuid) for vdsd in device.vdsds.values()}
                if dsuids:
                    self._host._add_pending_vanish(dsuids)  # also schedules save
                    return device
            if getattr(self, "_auto_save_enabled", False):
                self._host._schedule_auto_save()
        return device
```

- [ ] **Step 5: Pass `track_vanish=False` in `_handle_remove()` in `vdc_host.py`**

Locate this line in `_handle_remove()` (around line 1665):

```python
        # Remove the device from the vDC.
        owning_vdc.remove_device(dsuid)
```

Replace with:

```python
        # Remove the device from the vDC.
        # track_vanish=False: the vdSM initiated this removal and has
        # already deleted the device from its own database.
        owning_vdc.remove_device(dsuid, track_vanish=False)
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestPendingVanishWiring -v
```

Expected: all 4 tests PASS.

- [ ] **Step 7: Run the full test suite to check for regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py src/pydsvdcapi/vdc.py tests/test_vdc_host.py
git commit -m "feat: populate _pending_vanish on remove_vdc / remove_device"
```

---

### Task 3: Update documentation

**Files:**
- Modify: `docs/vdc-host-behavior.md`

- [ ] **Step 1: Add §2.7 to `docs/vdc-host-behavior.md`**

Locate the end of §2.6 in `docs/vdc-host-behavior.md`. Find the closing line of §2.6:

```markdown
> **Version suffix:** The vdSM may send `scanDevices/6` (or another
> version number) rather than the bare `scanDevices`.  pydsvdcapi strips
> the suffix before dispatch, so all firmware versions are supported.
```

Append immediately after that block:

```markdown

### 2.7 Offline deletions and `pendingVanish`

The vdSM requires an explicit `VDC_SEND_VANISH` to remove a device or vDC
from its database — it does **not** reconcile on re-announcement.  This
means a device deleted while the vDC host is offline must still receive a
vanish message on the next reconnect.

pydsvdcapi handles this automatically via a persistent `pendingVanish` list:

1. When `host.remove_vdc(dsuid)` is called, the vDC dSUID and all its
   devices' Vdsd dSUIDs are added to `_pending_vanish`.
2. When `vdc.remove_device(dsuid)` is called, all Vdsd dSUIDs of that
   device are added to `_pending_vanish`.
3. The set is persisted in the YAML state file under `pendingVanish` so a
   process restart does not lose it.
4. When a new session is established, `_on_session_ready()` calls
   `_flush_pending_vanish()` **before** re-announcing surviving vDCs.
   This sends `VDC_SEND_VANISH` for every entry, then clears the set and
   saves.

> **vdSM-initiated removals:** When the vdSM itself sends
> `VDSM_SEND_REMOVE`, pydsvdcapi removes the device from its registry but
> does **not** add it to `pendingVanish` — the vdSM already removed it
> from its own database.
```

- [ ] **Step 2: Run the full test suite**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/ -q
```

Expected: all tests still pass.

- [ ] **Step 3: Commit**

```bash
git add docs/vdc-host-behavior.md
git commit -m "docs: document pendingVanish offline-deletion behaviour"
```
