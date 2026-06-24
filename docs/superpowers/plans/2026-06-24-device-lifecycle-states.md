# Device Lifecycle States Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `DeviceLifecycleState` to `Vdsd` so library users can express device health via a single async setter, with the library handling all vdSM/dSS communication (push `active` property, suppress pong, trigger vanish).

**Architecture:** Four files change. `enums.py` gets the new enum. `vdsd.py` replaces its bare `_active: bool` with `_lifecycle_state`, gains an async setter that pushes `active` and/or calls `vanish`. `session.py` gains an optional async presence-checker callback that gates pong responses. `vdc_host.py` adds a dSUID traversal helper and registers the checker after every successful `hello`.

**Tech Stack:** Python 3.11+, asyncio, pytest, existing `dict_to_elements` / `VDC_SEND_PUSH_NOTIFICATION` pattern already used in `device_state.py`.

---

## File map

| File | Task |
|---|---|
| `src/pydsvdcapi/enums.py` | Task 1 — new enum |
| `src/pydsvdcapi/__init__.py` | Task 1 — re-export |
| `src/pydsvdcapi/vdsd.py` | Task 2 — state field, properties, async setter, push |
| `src/pydsvdcapi/session.py` | Task 3 — presence checker + updated ping handler |
| `src/pydsvdcapi/vdc_host.py` | Task 4 — dSUID lookup + registration |
| `tests/test_vdsd.py` | Tasks 1 & 2 |
| `tests/test_session.py` | Task 3 |
| `tests/test_vdc_host.py` | Task 4 |

---

## Task 1: `DeviceLifecycleState` enum

**Files:**
- Modify: `src/pydsvdcapi/enums.py`
- Modify: `src/pydsvdcapi/__init__.py`
- Test: `tests/test_vdsd.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_vdsd.py`, add after the existing imports:

```python
from pydsvdcapi.enums import DeviceLifecycleState
```

Add a new test class after `TestVdsdConstruction`:

```python
class TestDeviceLifecycleStateEnum:
    """DeviceLifecycleState enum has all required values."""

    def test_all_states_exist(self):
        assert DeviceLifecycleState.ACTIVE == "active"
        assert DeviceLifecycleState.INACTIVE == "inactive"
        assert DeviceLifecycleState.MAINTENANCE == "maintenance"
        assert DeviceLifecycleState.ERROR == "error"
        assert DeviceLifecycleState.REMOVED == "removed"

    def test_active_is_truthy_active(self):
        assert DeviceLifecycleState.ACTIVE == DeviceLifecycleState.ACTIVE
        assert DeviceLifecycleState.INACTIVE != DeviceLifecycleState.ACTIVE
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdsd.py::TestDeviceLifecycleStateEnum -v
```

Expected: `ImportError: cannot import name 'DeviceLifecycleState'`

- [ ] **Step 3: Add enum to `enums.py`**

In `src/pydsvdcapi/enums.py`, change line 15 from:
```python
from enum import IntEnum, unique
```
to:
```python
from enum import Enum, IntEnum, unique
```

Then append at the very end of `enums.py` (after `VentilationScene`):

```python


# ---------------------------------------------------------------------------
#  Device lifecycle state
# ---------------------------------------------------------------------------


@unique
class DeviceLifecycleState(str, Enum):
    """Lifecycle state of a virtual device (vdSD).

    The library maps these states to the vdSM wire protocol automatically:

    * ``ACTIVE`` — device is operational; responds to ping with pong and
      reports ``active=true`` in common properties.
    * ``INACTIVE``, ``MAINTENANCE``, ``ERROR`` — device is temporarily
      unavailable; ping responses are suppressed and ``active=false`` is
      pushed to dSS on transition.
    * ``REMOVED`` — device has been decommissioned; ``vanish`` is sent to
      dSS and ping responses are suppressed.  Setting ``REMOVED`` is
      one-way: there is no meaningful return from this state.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"
    REMOVED = "removed"
```

- [ ] **Step 4: Export from `__init__.py`**

In `src/pydsvdcapi/__init__.py`, find the `from pydsvdcapi.enums import (` block (around line 194). Add `DeviceLifecycleState` in alphabetical order:

```python
    ColorGroup,
    DeviceLifecycleState,      # ← add this line
    DeviceScene,
```

Also add it to the `__all__` list if one exists (search for `"ColorGroup"` in `__all__` and add `"DeviceLifecycleState"` alongside it).

- [ ] **Step 5: Run test to verify it passes**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdsd.py::TestDeviceLifecycleStateEnum -v
```

Expected: 2 passed.

- [ ] **Step 6: Run full suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/enums.py src/pydsvdcapi/__init__.py tests/test_vdsd.py
git commit -m "feat: add DeviceLifecycleState enum"
```

---

## Task 2: Lifecycle state on `Vdsd`

Replace `_active: bool` with `_lifecycle_state: DeviceLifecycleState`. Add `lifecycle_state` property getter, `async set_lifecycle_state()` method, and private `async _push_active()` helper. Remove the `active` setter (breaking change documented in spec).

**Files:**
- Modify: `src/pydsvdcapi/vdsd.py`
- Test: `tests/test_vdsd.py`

- [ ] **Step 1: Write the failing tests**

Add import at the top of `tests/test_vdsd.py` (find the existing enums import block and add `DeviceLifecycleState` there if not already present from Task 1).

Add a new test class `TestVdsdLifecycleState`:

```python
class TestVdsdLifecycleState:
    """Vdsd.set_lifecycle_state manages state, active property, push, and vanish."""

    # ---- default state ---------------------------------------------------

    def test_default_lifecycle_state_is_active(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        assert vdsd.lifecycle_state == DeviceLifecycleState.ACTIVE
        assert vdsd.active is True

    # ---- active derivation -----------------------------------------------

    def test_active_true_when_active_state(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        assert vdsd.active is True

    # ---- transitions before announcement (no session) --------------------

    @pytest.mark.asyncio
    async def test_set_inactive_before_announced_stores_state_silently(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        # Should not raise even without a session
        await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)
        assert vdsd.lifecycle_state == DeviceLifecycleState.INACTIVE
        assert vdsd.active is False

    @pytest.mark.asyncio
    async def test_set_removed_before_announced_stores_state_silently(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        await vdsd.set_lifecycle_state(DeviceLifecycleState.REMOVED)
        assert vdsd.lifecycle_state == DeviceLifecycleState.REMOVED

    # ---- transitions after announcement (with session) -------------------

    @pytest.mark.asyncio
    async def test_set_inactive_pushes_active_false(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)
        elem = msg.vdc_send_push_notification.changedproperties[0]
        assert elem.name == "active"
        assert elem.value.v_bool is False

    @pytest.mark.asyncio
    async def test_set_active_pushes_active_true(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session
        # Start from inactive
        vdsd._lifecycle_state = DeviceLifecycleState.INACTIVE

        await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        elem = msg.vdc_send_push_notification.changedproperties[0]
        assert elem.name == "active"
        assert elem.value.v_bool is True

    @pytest.mark.asyncio
    async def test_no_push_when_active_flag_unchanged(self):
        """INACTIVE → MAINTENANCE: both active=False, no push needed."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session
        vdsd._lifecycle_state = DeviceLifecycleState.INACTIVE

        await vdsd.set_lifecycle_state(DeviceLifecycleState.MAINTENANCE)

        session.send_notification.assert_not_called()
        assert vdsd.lifecycle_state == DeviceLifecycleState.MAINTENANCE

    @pytest.mark.asyncio
    async def test_no_push_when_same_state_repeated(self):
        """Setting ACTIVE when already ACTIVE: no push."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

        session.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_removed_sends_vanish(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        await vdsd.set_lifecycle_state(DeviceLifecycleState.REMOVED)

        # send_notification is called for both push(active=False) and vanish
        calls = session.send_notification.call_args_list
        msg_types = [c[0][0].type for c in calls]
        assert pb.VDC_SEND_PUSH_NOTIFICATION in msg_types
        assert pb.VDC_SEND_VANISH in msg_types

    # ---- active property is derived, not stored directly ----------------

    def test_active_property_reflects_lifecycle_state(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        for state in [
            DeviceLifecycleState.INACTIVE,
            DeviceLifecycleState.MAINTENANCE,
            DeviceLifecycleState.ERROR,
            DeviceLifecycleState.REMOVED,
        ]:
            vdsd._lifecycle_state = state
            assert vdsd.active is False
        vdsd._lifecycle_state = DeviceLifecycleState.ACTIVE
        assert vdsd.active is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdsd.py::TestVdsdLifecycleState -v
```

Expected: `AttributeError: 'Vdsd' object has no attribute 'lifecycle_state'`

- [ ] **Step 3: Update `vdsd.py` imports**

In `src/pydsvdcapi/vdsd.py`, find line 78:
```python
from pydsvdcapi.enums import ColorGroup
```
Change to:
```python
from pydsvdcapi.enums import ColorGroup, DeviceLifecycleState
from pydsvdcapi.property_handling import dict_to_elements
```

- [ ] **Step 4: Replace `_active` with `_lifecycle_state` in `__init__`**

In `src/pydsvdcapi/vdsd.py`, find lines 357–359 (the runtime state block):
```python
        # --- runtime state --------------------------------------------
        self._active: bool = True
        self._announced: bool = False
        self._session: VdcSession | None = None
```
Change to:
```python
        # --- runtime state --------------------------------------------
        self._lifecycle_state: DeviceLifecycleState = DeviceLifecycleState.ACTIVE
        self._announced: bool = False
        self._session: VdcSession | None = None
```

- [ ] **Step 5: Replace `active` property and remove setter**

In `src/pydsvdcapi/vdsd.py`, find lines 411–418:
```python
    @property
    def active(self) -> bool:
        """Whether this vdSD is currently active / operational."""
        return self._active

    @active.setter
    def active(self, value: bool) -> None:
        self._active = bool(value)
```
Replace with:
```python
    @property
    def active(self) -> bool:
        """Whether this vdSD is currently active / operational.

        Derived from :attr:`lifecycle_state`.  ``True`` only when
        ``lifecycle_state == DeviceLifecycleState.ACTIVE``.
        Use :meth:`set_lifecycle_state` to change this value.
        """
        return self._lifecycle_state == DeviceLifecycleState.ACTIVE

    @property
    def lifecycle_state(self) -> DeviceLifecycleState:
        """Current lifecycle state of this vdSD."""
        return self._lifecycle_state

    @property
    def is_announced(self) -> bool:
        """Whether this vdSD has been announced to the vdSM."""
        return self._announced
```

- [ ] **Step 6: Add `_push_active()` private helper**

In `src/pydsvdcapi/vdsd.py`, find `get_common_properties` (search for `"active": self._active`). Just above it (or after the `lifecycle_state` property), add:

```python
    async def _push_active(self, active: bool) -> None:
        """Push a ``VDC_SEND_PUSH_NOTIFICATION`` for the ``active`` property."""
        if self._session is None:
            return
        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._dsuid)
        for elem in dict_to_elements({"active": active}):
            msg.vdc_send_push_notification.changedproperties.append(elem)
        try:
            await self._session.send_notification(msg)
            logger.debug(
                "vdSD '%s': pushed active=%s", self.name, active
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "vdSD '%s': failed to push active: %s", self.name, exc
            )
```

- [ ] **Step 7: Add `set_lifecycle_state()` async method**

Immediately after `_push_active`, add:

```python
    async def set_lifecycle_state(
        self, state: DeviceLifecycleState
    ) -> None:
        """Set the lifecycle state and handle all vdSM communication.

        * If ``active`` changes (``True`` ↔ ``False``) and the device is
          announced, pushes ``VDC_SEND_PUSH_NOTIFICATION`` with the new
          ``active`` value.
        * If *state* is ``REMOVED`` and the device is announced, also
          sends ``VDC_SEND_VANISH``.
        * If the device is not yet announced, stores the state silently.

        Parameters
        ----------
        state:
            The new lifecycle state.
        """
        was_active = self._lifecycle_state == DeviceLifecycleState.ACTIVE
        self._lifecycle_state = state
        now_active = state == DeviceLifecycleState.ACTIVE

        if self._announced and self._session is not None:
            if was_active != now_active:
                await self._push_active(now_active)
            if state == DeviceLifecycleState.REMOVED:
                await self.vanish(self._session)
```

- [ ] **Step 8: Fix `get_common_properties` reference**

In `src/pydsvdcapi/vdsd.py`, find the line (around 1546):
```python
            "active": self._active,
```
Change to:
```python
            "active": self._lifecycle_state == DeviceLifecycleState.ACTIVE,
```

- [ ] **Step 9: Run new tests — all must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdsd.py::TestVdsdLifecycleState -v
```

Expected: all pass.

- [ ] **Step 10: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/ -q
```

Expected: all pass. If any test asserts `vdsd.active = False` or sets `vdsd._active`, update it to use `vdsd._lifecycle_state = DeviceLifecycleState.INACTIVE` or `await vdsd.set_lifecycle_state(...)`.

- [ ] **Step 11: Commit**

```bash
git add src/pydsvdcapi/vdsd.py tests/test_vdsd.py
git commit -m "feat: replace Vdsd._active bool with DeviceLifecycleState + async setter"
```

---

## Task 3: `VdcSession` presence checker + updated ping handler

**Files:**
- Modify: `src/pydsvdcapi/session.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_session.py`, add a new test class after the existing ping tests:

```python
class TestPingPresenceChecker:
    """VdcSession respects a registered presence checker for ping/pong."""

    @pytest.mark.asyncio
    async def test_presence_checker_returning_true_sends_pong(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        session.set_presence_checker(AsyncMock(return_value=True))

        await vdsm.send(_hello_msg())
        await vdsm.send(_ping_msg(HOST_DSUID))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response
        pong = await vdsm.receive()
        assert pong is not None
        assert pong.type == pb.VDC_SEND_PONG
        await task

    @pytest.mark.asyncio
    async def test_presence_checker_returning_false_suppresses_pong(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        session.set_presence_checker(AsyncMock(return_value=False))

        await vdsm.send(_hello_msg())
        await vdsm.send(_ping_msg(HOST_DSUID))
        await vdsm.send(_bye_msg())
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response
        # Next message should be bye ack, NOT a pong
        msg = await vdsm.receive()
        assert msg is not None
        assert msg.type == pb.GENERIC_RESPONSE  # bye ack, not pong
        await task

    @pytest.mark.asyncio
    async def test_no_presence_checker_always_pongs(self):
        """Backward compat: no checker registered → always pong."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        # No set_presence_checker call

        await vdsm.send(_hello_msg())
        await vdsm.send(_ping_msg(HOST_DSUID))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response
        pong = await vdsm.receive()
        assert pong is not None
        assert pong.type == pb.VDC_SEND_PONG
        await task

    @pytest.mark.asyncio
    async def test_presence_checker_receives_target_dsuid(self):
        """The checker is called with the exact dSUID from the ping."""
        DEVICE_DSUID = "198C033E330755E78015F97AD093DD1C01"
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        checker = AsyncMock(return_value=True)
        session.set_presence_checker(checker)

        await vdsm.send(_hello_msg())
        await vdsm.send(_ping_msg(DEVICE_DSUID))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response
        await vdsm.receive()  # pong
        await task

        checker.assert_called_once_with(DEVICE_DSUID)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_session.py::TestPingPresenceChecker -v
```

Expected: `AttributeError: 'VdcSession' object has no attribute 'set_presence_checker'`

- [ ] **Step 3: Add `_presence_checker` to `VdcSession.__init__`**

In `src/pydsvdcapi/session.py`, find `__init__` (line 130). After `self.disconnect_reason: Exception | None = None`, add:

```python
        # Optional async callback for ping presence checks.
        # Signature: async (dsuid: str) -> bool
        # If None, all pings receive a pong (backward-compatible default).
        self._presence_checker: (
            Callable[[str], Awaitable[bool]] | None
        ) = None
```

- [ ] **Step 4: Add `set_presence_checker()` method**

In `src/pydsvdcapi/session.py`, after the `ping_count` property (around line 204), add:

```python
    def set_presence_checker(
        self,
        checker: Callable[[str], Awaitable[bool]],
    ) -> None:
        """Register an async callback that gates pong responses.

        The callback receives the dSUID from the ping message and must
        return ``True`` if the device is present (pong will be sent) or
        ``False`` to suppress the pong.

        If no checker is registered, every ping receives a pong
        (backward-compatible default).
        """
        self._presence_checker = checker
```

- [ ] **Step 5: Update `_handle_ping()` to consult the checker**

In `src/pydsvdcapi/session.py`, replace the current `_handle_ping` (lines 455–470):

```python
    async def _handle_ping(self, msg: pb.Message) -> None:
        """Respond to a ``VDSM_SEND_PING`` with ``VDC_SEND_PONG``.

        If a presence checker has been registered via
        :meth:`set_presence_checker`, it is called first; the pong is only
        sent if the checker returns ``True``.  With no checker registered,
        all pings receive a pong (backward-compatible behaviour).
        """
        target_dsuid = msg.vdsm_send_ping.dSUID
        self._ping_count += 1

        if self._presence_checker is not None:
            present = await self._presence_checker(target_dsuid)
        else:
            present = True

        if not present:
            logger.debug(
                "Ping #%d for %s — device not present, suppressing pong",
                self._ping_count,
                target_dsuid,
            )
            return

        logger.info(
            "Ping #%d for %s — sending pong",
            self._ping_count,
            target_dsuid,
        )
        pong = pb.Message()
        pong.type = pb.VDC_SEND_PONG
        pong.message_id = 0  # pong is a notification, no msg_id
        pong.vdc_send_pong.dSUID = target_dsuid or self._host_dsuid
        await self._conn.send(pong)
```

- [ ] **Step 6: Run new tests — all must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_session.py::TestPingPresenceChecker -v
```

Expected: 4 passed.

- [ ] **Step 7: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/session.py tests/test_session.py
git commit -m "feat: add presence checker callback to VdcSession for gated ping/pong"
```

---

## Task 4: `VdcHost` dSUID lookup + presence checker registration

Wire everything together: `VdcHost` traverses its device tree to find a `Vdsd` by dSUID and registers the presence checker on every new session.

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py`
- Test: `tests/test_vdc_host.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_vdc_host.py`, first check the existing imports and helper functions. The file already has `_make_host()`, `_make_vdc()`, `_make_device()`, `_make_vdsd()` helpers (check by reading its top section). Add `DeviceLifecycleState` to the imports.

Add a new test class `TestPresenceCheckerRegistration`:

```python
from pydsvdcapi.enums import DeviceLifecycleState


class TestPresenceCheckerRegistration:
    """VdcHost registers presence checker; pings respect device lifecycle state."""

    @pytest.mark.asyncio
    async def test_active_device_answers_ping(self, tmp_path):
        host, session = await _make_host_with_session(tmp_path)
        vdsd = _get_first_vdsd(host)
        assert vdsd.lifecycle_state == DeviceLifecycleState.ACTIVE

        ping_resp = await _send_ping(session, str(vdsd.dsuid))
        assert ping_resp is not None
        assert ping_resp.type == pb.VDC_SEND_PONG

    @pytest.mark.asyncio
    async def test_inactive_device_suppresses_pong(self, tmp_path):
        host, session = await _make_host_with_session(tmp_path)
        vdsd = _get_first_vdsd(host)
        await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)

        # After setting inactive, no pong should come back.
        # Send ping + bye so session terminates predictably.
        ping_resp = await _send_ping_expect_none(session, str(vdsd.dsuid))
        assert ping_resp is None  # pong was suppressed

    @pytest.mark.asyncio
    async def test_unknown_dsuid_answers_ping(self, tmp_path):
        """Unknown dSUID falls back to always-pong (backward compat)."""
        host, session = await _make_host_with_session(tmp_path)
        ping_resp = await _send_ping(session, "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00")
        assert ping_resp is not None
        assert ping_resp.type == pb.VDC_SEND_PONG

    @pytest.mark.asyncio
    async def test_removed_device_revanishes_on_ping(self, tmp_path):
        """A REMOVED vdSD re-triggers vanish on every subsequent ping."""
        host, session = await _make_host_with_session(tmp_path)
        # Retrieve the presence checker that _on_session_ready passed to the mock
        checker = session.set_presence_checker.call_args[0][0]

        vdsd = _get_first_vdsd(host)
        vdsd._lifecycle_state = DeviceLifecycleState.REMOVED
        vdsd._announced = True
        session.send_notification.reset_mock()

        result = await checker(str(vdsd.dsuid))

        assert result is False  # pong suppressed
        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_VANISH
```

In the same file, add the helper functions `_make_host_with_session`, `_get_first_vdsd`, `_send_ping`, and `_send_ping_expect_none`. Look at existing test helpers in the file for the pattern. A minimal version:

```python
async def _make_host_with_session(tmp_path):
    """Create a VdcHost with one vDC/device/vdsd and run its session."""
    # (Adapt to match the existing test infrastructure in test_vdc_host.py)
    host = _make_host(tmp_path)
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    session = _make_mock_session()
    # Simulate session ready
    await host._on_session_ready(session)
    host._session = session
    return host, session


def _get_first_vdsd(host):
    vdc = next(iter(host.vdcs.values()))
    device = next(iter(vdc.devices.values()))
    return next(iter(device.vdsds.values()))
```

**Note:** The exact helper pattern must match what already exists in `tests/test_vdc_host.py`. Read the top of that file first and adapt accordingly. The key assertions remain the same regardless of helper shape.

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdc_host.py::TestPresenceCheckerRegistration -v
```

Expected: `AttributeError` or assertion failures (presence checker not yet registered).

- [ ] **Step 3: Add `_find_vdsd()` to `VdcHost`**

In `src/pydsvdcapi/vdc_host.py`, after the `get_vdc()` method (around line 507), add:

```python
    def _find_vdsd(self, dsuid: str) -> "Vdsd | None":
        """Find a :class:`Vdsd` by its dSUID string.

        Traverses all registered vDCs → devices → vdSDs.
        Returns ``None`` if no vdSD with the given dSUID is found.
        """
        for vdc in self._vdcs.values():
            for device in vdc.devices.values():
                for vdsd in device.vdsds.values():
                    if str(vdsd.dsuid) == dsuid:
                        return vdsd
        return None
```

Add the `Vdsd` import at the top of `vdc_host.py` if not already there. Check the existing imports — `Vdsd` may need to be added:

```python
from pydsvdcapi.vdsd import Device, Vdsd  # add Vdsd if missing
```

Also add `DeviceLifecycleState` to the vdc_host imports:

```python
from pydsvdcapi.enums import DeviceLifecycleState  # add this line
```

- [ ] **Step 4: Register presence checker in `_on_session_ready()`**

In `src/pydsvdcapi/vdc_host.py`, find `_on_session_ready()` (line 1146). Add the presence checker registration at the **start** of the method, before the existing `_flush_pending_vanish` call:

```python
    async def _on_session_ready(self, session: VdcSession) -> None:
        """Auto-announce all registered vDCs and devices on *session*."""
        # Register presence checker so ping/pong respects device lifecycle state.
        host_dsuid = self._host_dsuid

        async def _presence_check(dsuid: str) -> bool:
            if not dsuid or dsuid == host_dsuid:
                return True
            vdsd = self._find_vdsd(dsuid)
            if vdsd is None:
                return True  # unknown dSUID → pong (backward compat)
            if vdsd.lifecycle_state == DeviceLifecycleState.REMOVED:
                if vdsd.is_announced:
                    await vdsd.vanish(session)
            return vdsd.lifecycle_state == DeviceLifecycleState.ACTIVE

        session.set_presence_checker(_presence_check)

        # The rest of _on_session_ready continues unchanged from here:
        await self._flush_pending_vanish(session)
```

- [ ] **Step 5: Run new tests — all must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_vdc_host.py::TestPresenceCheckerRegistration -v
```

Expected: all pass.

- [ ] **Step 6: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "feat: register device presence checker in VdcHost for correct ping/pong routing"
```
