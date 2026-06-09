# Lost-Connection Callback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `on_disconnect` callback to `VdcHost` that fires when the vdSM TCP connection is lost unexpectedly, passing `(host: VdcHost, reason: Exception | None)` to the caller.

**Architecture:** `VdcSession.run()` already catches disconnect exceptions internally; we add a `disconnect_reason` attribute so the caller can read it. `VdcHost._run_session()` fires the callback in its `finally` block, but only when `self._stopping` is `False` (guarding against intentional `stop()` calls). The callback is registered via `on_disconnect` on `VdcHost.start()`.

**Tech Stack:** Python 3.10+, asyncio, pydsvdcapi internal session/host modules, pytest-asyncio.

---

### Task 1: Store disconnect reason in VdcSession

**Files:**
- Modify: `src/pydsvdcapi/session.py:124-152` (`__init__`), `src/pydsvdcapi/session.py:204-251` (`run`)
- Test: `tests/test_session.py` (create if missing, otherwise append)

- [ ] **Step 1: Write the failing test**

Check if `tests/test_session.py` exists. If not, create it. Add this test class:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydsvdcapi.session import VdcSession, SessionState


def _make_session(reader=None, writer=None):
    """Return a VdcSession backed by mock reader/writer."""
    from pydsvdcapi.connection import VdcConnection
    r = reader or MagicMock(spec=asyncio.StreamReader)
    w = writer or MagicMock(spec=asyncio.StreamWriter)
    w.is_closing.return_value = False
    w.wait_closed = AsyncMock()
    w.close = MagicMock()
    conn = VdcConnection(r, w)
    return VdcSession(connection=conn, host_dsuid="0" * 34)


class TestDisconnectReason:
    def test_disconnect_reason_initially_none(self):
        session = _make_session()
        assert session.disconnect_reason is None

    @pytest.mark.asyncio
    async def test_disconnect_reason_set_on_connection_error(self):
        from pydsvdcapi.connection import VdcConnection
        r = MagicMock(spec=asyncio.StreamReader)
        err = ConnectionResetError("peer reset")
        r.readexactly = AsyncMock(side_effect=err)
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.wait_closed = AsyncMock()
        w.close = MagicMock()
        conn = VdcConnection(r, w)
        session = VdcSession(connection=conn, host_dsuid="0" * 34)
        await session.run()
        assert isinstance(session.disconnect_reason, ConnectionResetError)

    @pytest.mark.asyncio
    async def test_disconnect_reason_set_on_incomplete_read(self):
        from pydsvdcapi.connection import VdcConnection
        r = MagicMock(spec=asyncio.StreamReader)
        err = asyncio.IncompleteReadError(b"", 4)
        r.readexactly = AsyncMock(side_effect=err)
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.wait_closed = AsyncMock()
        w.close = MagicMock()
        conn = VdcConnection(r, w)
        session = VdcSession(connection=conn, host_dsuid="0" * 34)
        await session.run()
        assert isinstance(session.disconnect_reason, asyncio.IncompleteReadError)

    @pytest.mark.asyncio
    async def test_disconnect_reason_none_on_clean_eof(self):
        from pydsvdcapi.connection import VdcConnection
        r = MagicMock(spec=asyncio.StreamReader)
        # read returns empty bytes → EOF
        r.readexactly = AsyncMock(return_value=b"")
        w = MagicMock(spec=asyncio.StreamWriter)
        w.is_closing.return_value = False
        w.wait_closed = AsyncMock()
        w.close = MagicMock()
        conn = VdcConnection(r, w)
        session = VdcSession(connection=conn, host_dsuid="0" * 34)
        await session.run()
        assert session.disconnect_reason is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_session.py::TestDisconnectReason -v
```

Expected: `AttributeError: 'VdcSession' object has no attribute 'disconnect_reason'`

- [ ] **Step 3: Add `disconnect_reason` attribute to `VdcSession`**

In `src/pydsvdcapi/session.py`, add to `__init__` after `self._ping_count: int = 0`:

```python
        # Reason the session ended (set in run() when a network error is
        # the cause; None for clean close or close() call).
        self.disconnect_reason: Exception | None = None
```

Then update `run()` — change the two `except` clauses inside the while loop to capture the exception:

```python
            except asyncio.IncompleteReadError as exc:
                logger.info(
                    "Connection from %s closed (incomplete read)",
                    self._conn.peername,
                )
                self.disconnect_reason = exc
                break
            except (ConnectionError, ValueError) as exc:
                logger.warning(
                    "Connection error from %s: %s",
                    self._conn.peername,
                    exc,
                )
                self.disconnect_reason = exc
                break
```

The `msg is None` (EOF) and bye branches do NOT set `disconnect_reason` — they leave it as `None` (clean close).

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_session.py::TestDisconnectReason -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest --tb=short -q
```

Expected: all existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/session.py tests/test_session.py
git commit -m "feat: add disconnect_reason attribute to VdcSession"
```

---

### Task 2: Add DisconnectCallback type and `_stopping` flag to VdcHost

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py:55-84` (type aliases), `src/pydsvdcapi/vdc_host.py:319-344` (`__init__` runtime state)
- Test: `tests/test_vdc_host.py` (append new test class)

- [ ] **Step 1: Write the failing test**

Append this test class to `tests/test_vdc_host.py`:

```python
class TestDisconnectCallback:
    """Tests for the on_disconnect callback mechanism."""

    def test_disconnect_callback_type_exists(self):
        from pydsvdcapi.vdc_host import DisconnectCallback
        assert DisconnectCallback is not None

    @pytest.mark.asyncio
    async def test_start_accepts_on_disconnect(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        fired = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            await host.stop()

        assert host._on_disconnect is on_disc
```

- [ ] **Step 2: Run the failing test**

```bash
pytest tests/test_vdc_host.py::TestDisconnectCallback -v
```

Expected: `ImportError: cannot import name 'DisconnectCallback'`

- [ ] **Step 3: Add `DisconnectCallback` type alias**

In `src/pydsvdcapi/vdc_host.py`, after the `SetConfigurationCallback` line (around line 82), add:

```python
#: Callback invoked when the vdSM TCP connection is lost unexpectedly.
#: Receives the :class:`VdcHost` instance and the exception that caused
#: the disconnect (or ``None`` for a clean EOF / bye).
#: Not called when :meth:`VdcHost.stop` initiated the disconnect.
DisconnectCallback = Callable[["VdcHost", Exception | None], Awaitable[None]]
```

Also add `DisconnectCallback` to the module's `__all__` if one exists, or just leave it public.

- [ ] **Step 4: Add `_stopping` and `_on_disconnect` to `__init__`**

In `src/pydsvdcapi/vdc_host.py`, in the `# --- TCP server / session state` block (around line 325), add after `self._on_set_configuration`:

```python
        self._on_disconnect: DisconnectCallback | None = None
        self._stopping: bool = False
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_vdc_host.py::TestDisconnectCallback -v
```

Expected: 3 tests PASS

- [ ] **Step 6: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "feat: add DisconnectCallback type and _stopping flag to VdcHost"
```

---

### Task 3: Wire callback into start() and _run_session()

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py:820-908` (`start()`), `src/pydsvdcapi/vdc_host.py:981-995` (`_run_session()`)
- Test: `tests/test_vdc_host.py` (extend `TestDisconnectCallback`)

- [ ] **Step 1: Write the failing tests**

Append these tests to the `TestDisconnectCallback` class in `tests/test_vdc_host.py`:

```python
    @pytest.mark.asyncio
    async def test_callback_fires_on_unexpected_disconnect(self):
        """Callback fires when session ends without stop() being called."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        err = ConnectionResetError("peer reset")
        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = err
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            # Directly call _run_session (simulates a connection arriving)
            await host._run_session(mock_session)
            await host.stop()

        assert len(fired) == 1
        assert fired[0][0] is host
        assert fired[0][1] is err

    @pytest.mark.asyncio
    async def test_callback_not_fired_when_stopping(self):
        """Callback must NOT fire when stop() initiated the disconnect."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = ConnectionResetError("peer reset")
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            host._stopping = True  # simulate stop() in progress
            await host._run_session(mock_session)
            host._stopping = False
            await host.stop()

        assert fired == []

    @pytest.mark.asyncio
    async def test_callback_not_fired_when_no_callback_set(self):
        """No error when on_disconnect is None and session ends."""
        host = VdcHost(mac=TEST_MAC, port=0)

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = ConnectionResetError("peer reset")
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(announce=False)
            # Should not raise even with no callback registered
            await host._run_session(mock_session)
            await host.stop()

    @pytest.mark.asyncio
    async def test_callback_receives_none_reason_on_clean_close(self):
        """Callback fires with None reason for clean EOF."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = None  # clean EOF
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            await host._run_session(mock_session)
            await host.stop()

        assert len(fired) == 1
        assert fired[0][1] is None
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/test_vdc_host.py::TestDisconnectCallback -v
```

Expected: new tests FAIL (callback not yet wired)

- [ ] **Step 3: Add `on_disconnect` parameter to `start()`**

In `src/pydsvdcapi/vdc_host.py`, add `on_disconnect` to the `start()` signature after `on_set_configuration`:

```python
    async def start(
        self,
        *,
        on_message: MessageCallback | None = None,
        on_remove: RemoveCallback | None = None,
        on_identify: IdentifyCallback | None = None,
        on_pair: PairCallback | None = None,
        on_authenticate: AuthenticateCallback | None = None,
        on_firmware_upgrade: FirmwareUpgradeCallback | None = None,
        on_set_configuration: SetConfigurationCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
        announce: bool = True,
        bind_address: str = "0.0.0.0",
    ) -> None:
```

In the body of `start()`, after `self._on_set_configuration = on_set_configuration`, add:

```python
        self._on_disconnect = on_disconnect
```

Add the parameter to the docstring after the `on_set_configuration` entry:

```
        on_disconnect:
            Optional async callback invoked when the vdSM TCP connection
            is lost unexpectedly (network drop, dSS restart, etc.).
            Receives ``(host, reason)`` where *reason* is the exception
            that caused the disconnect, or ``None`` for a clean EOF / bye.
            **Not called** when :meth:`stop` initiated the disconnect.
```

- [ ] **Step 4: Set `_stopping` in `stop()` and fire callback in `_run_session()`**

In `src/pydsvdcapi/vdc_host.py`, update `stop()` to set `_stopping` around the session close:

```python
    async def stop(self) -> None:
        # ... (existing docstring unchanged) ...
        self.flush()
        await self.unannounce()

        self._stopping = True
        try:
            await self._close_session()
        finally:
            self._stopping = False

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("TCP server stopped")
```

Update `_run_session()` to fire the callback:

```python
    async def _run_session(self, session: VdcSession) -> None:
        """Run a session and clean up when it ends."""
        try:
            await session.run()
        except Exception:  # noqa: BLE001
            logger.exception("Session error")
        finally:
            if self._session is session:
                self._session = None
                self._session_task = None
            for vdc in self._vdcs.values():
                vdc.reset_announcement()
            logger.info("Session with %s cleaned up", session.vdsm_dsuid)

            if not self._stopping and self._on_disconnect is not None:
                try:
                    await self._on_disconnect(self, session.disconnect_reason)
                except Exception:  # noqa: BLE001
                    logger.exception("on_disconnect callback raised")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_vdc_host.py::TestDisconnectCallback -v
```

Expected: all 8 tests PASS

- [ ] **Step 6: Run full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "feat: wire on_disconnect callback into VdcHost.start() and _run_session()"
```

---

### Task 4: Update documentation

**Files:**
- Modify: `docs/vdc-host-behavior.md`

- [ ] **Step 1: Find the callbacks section in `docs/vdc-host-behavior.md`**

Read `docs/vdc-host-behavior.md`. Locate the section describing `host.start()` parameters and the lifecycle table (around lines 828–878). The goal is to add `on_disconnect` to both.

- [ ] **Step 2: Add on_disconnect to the start() parameter description**

In the section that describes `host.start()` options (or the lifecycle table at the end of the file), add a row or bullet for `on_disconnect`:

```markdown
| `on_disconnect` | `DisconnectCallback` | Optional | Called when the vdSM connection is lost unexpectedly. Receives `(host, reason)` where `reason` is the exception or `None` for a clean close. Not called when `host.stop()` initiated the disconnect. |
```

- [ ] **Step 3: Add on_disconnect to the lifecycle diagram text**

In the lifecycle section (around line 845 "vdSM disconnects"), add:

```markdown
vdSM disconnects (network drop / dSS restart)
  └─ all vDC announcement flags reset
  └─ on_disconnect(host, reason) called (if set)
  └─ vdSM reconnects → full re-announcement cycle (automatic)
```

- [ ] **Step 4: Verify the doc renders correctly**

```bash
grep -n "on_disconnect\|DisconnectCallback" docs/vdc-host-behavior.md
```

Expected: at least 2 hits.

- [ ] **Step 5: Commit**

```bash
git add docs/vdc-host-behavior.md
git commit -m "docs: document on_disconnect callback in vdc-host-behavior.md"
```

---

### Task 5: Final validation

- [ ] **Step 1: Run the full test suite one last time**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest --tb=short -q
```

Expected: all tests pass, no warnings about unclosed resources.

- [ ] **Step 2: Run ruff**

```bash
ruff check src/ tests/
```

Expected: no errors.

- [ ] **Step 3: Check public API export**

```bash
python -c "from pydsvdcapi.vdc_host import DisconnectCallback, VdcHost; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Verify callback signature is usable end-to-end**

```bash
python -c "
import asyncio
from pydsvdcapi import VdcHost

host = VdcHost(port=0)

async def on_disc(h, exc):
    print('disconnected:', exc)

async def main():
    await host.start(on_disconnect=on_disc, announce=False)
    await host.stop()

asyncio.run(main())
print('OK')
"
```

Expected: `OK` (no exception, no spurious callback during `stop()`).
