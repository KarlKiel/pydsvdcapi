# Settings Callbacks and Push Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add (a) optional `on_settings_changed` callbacks that fire when the vdSM writes settings to any component, and (b) `push_settings()` methods on each component so device code can push settings changes to the vdSM via `VDC_SEND_PUSH_NOTIFICATION`.

**Architecture:** Each of the four settable component types (`Output`, `BinaryInput`, `ButtonInput`, `SensorInput`) gains a callback property and a push method, following the exact same pattern already used by channel-state pushes (`Output._push_channel_state`) and state pushes (`BinaryInput._push_state`). The `vdc_host.py` call sites for `apply_settings()` are extended to `await` an optional async callback after the apply. New callback type aliases are exported from `__init__.py`.

**Tech Stack:** Python 3.10+, asyncio, protobuf (`vdc_messages_pb2`), pytest-asyncio, existing `dict_to_elements()` helper.

---

## File Map

| File | Change |
|------|--------|
| `src/pydsvdcapi/output.py` | Add `OutputSettingsChangedCallback` type alias, `on_settings_changed` property, call in `apply_settings()`, add `push_settings()` method |
| `src/pydsvdcapi/binary_input.py` | Add `BinaryInputSettingsChangedCallback` type alias, `on_settings_changed` property, call in `apply_settings()`, add `push_settings()` method |
| `src/pydsvdcapi/button_input.py` | Add `ButtonInputSettingsChangedCallback` type alias, `on_settings_changed` property, call in `apply_settings()`, add `push_settings()` method |
| `src/pydsvdcapi/sensor_input.py` | Add `SensorInputSettingsChangedCallback` type alias, `on_settings_changed` property, call in `apply_settings()`, add `push_settings()` method |
| `src/pydsvdcapi/vdc_host.py` | Make `_apply_vdsd_set_property` async; `await` callbacks after each `apply_settings()` call |
| `src/pydsvdcapi/__init__.py` | Export the four new callback type aliases |
| `tests/test_settings_callbacks.py` | New test file: callback firing, push notification content, no-session guard |

---

## Invariants to preserve throughout

- The callback receives only the dict of settings that **arrived in the setProperty request** (the `incoming` / `settings` argument to `apply_settings()`), not the full settings object. This lets the application know exactly what changed.
- Callbacks are async. If they raise, the exception is logged and swallowed (same pattern as `on_channel_applied` in `output.py`).
- `push_settings()` is a no-op when no session is active or the vdSD is not yet announced (same guard as `_push_state()`).
- `apply_settings()` remains synchronous. The callback is invoked via `asyncio.ensure_future` / scheduled via `create_task` from `vdc_host.py` after the synchronous apply completes. Alternatively, `_apply_vdsd_set_property` is made `async` so it can `await` the callback directly — this is the cleaner approach (see Task 5).

---

## Task 1 — `OutputSettingsChangedCallback` + `Output.on_settings_changed` property

**Files:**
- Modify: `src/pydsvdcapi/output.py` (around line 104–120 for type alias; around line 660–670 for `__init__`; around line 998–1013 for property pattern)

- [ ] **Step 1: Add type alias after `DimChannelCallback` (line ~120)**

```python
#: Type alias for the output-settings-changed callback.
#: ``async def callback(output: Output, changed: dict[str, Any]) -> None``
#: *changed* is the dict of keys that arrived in the ``setProperty`` request.
OutputSettingsChangedCallback = Callable[
    ["Output", dict[str, Any]],
    Coroutine[Any, Any, None],
]
```

- [ ] **Step 2: Add instance attribute in `Output.__init__`** (after the `_on_dim_channel` line, ~line 666)

```python
#: Callback invoked when vdSM writes outputSettings.
self._on_settings_changed: OutputSettingsChangedCallback | None = None
```

- [ ] **Step 3: Add `on_settings_changed` property** (after the `on_dim_channel` setter, ~line 1013)

```python
@property
def on_settings_changed(self) -> OutputSettingsChangedCallback | None:
    """Callback invoked when the vdSM writes ``outputSettings``."""
    return self._on_settings_changed

@on_settings_changed.setter
def on_settings_changed(self, callback: OutputSettingsChangedCallback | None) -> None:
    self._on_settings_changed = callback
```

- [ ] **Step 4: Verify the file still passes ruff + mypy**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
ruff check src/pydsvdcapi/output.py
mypy src/pydsvdcapi/output.py
```

Expected: no errors.

- [ ] **Step 5: Commit (no tests yet — tests come in Task 7)**

```bash
git add src/pydsvdcapi/output.py
git commit -m "feat(output): add OutputSettingsChangedCallback type and on_settings_changed property"
```

---

## Task 2 — `BinaryInputSettingsChangedCallback` + `BinaryInput.on_settings_changed`

**Files:**
- Modify: `src/pydsvdcapi/binary_input.py` (imports area for type alias; `__init__` for attribute; new property after `apply_settings`)

- [ ] **Step 1: Add type alias near the top of `binary_input.py`** (after existing `Callable` / type alias imports)

Look for where `Callable` and `Coroutine` are imported from `collections.abc` / `typing`. Add:

```python
#: Type alias for the binary-input-settings-changed callback.
#: ``async def callback(binary_input: BinaryInput, changed: dict[str, Any]) -> None``
BinaryInputSettingsChangedCallback = Callable[
    ["BinaryInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]
```

- [ ] **Step 2: Add instance attribute in `BinaryInput.__init__`**

Grep for `self._session` init line in `__init__` (~line 151). Add directly after it:

```python
self._on_settings_changed: BinaryInputSettingsChangedCallback | None = None
```

- [ ] **Step 3: Add property after `apply_settings` method (after ~line 460)**

```python
@property
def on_settings_changed(self) -> BinaryInputSettingsChangedCallback | None:
    """Callback invoked when the vdSM writes ``binaryInputSettings``."""
    return self._on_settings_changed

@on_settings_changed.setter
def on_settings_changed(self, callback: BinaryInputSettingsChangedCallback | None) -> None:
    self._on_settings_changed = callback
```

- [ ] **Step 4: Verify ruff + mypy**

```bash
ruff check src/pydsvdcapi/binary_input.py
mypy src/pydsvdcapi/binary_input.py
```

- [ ] **Step 5: Commit**

```bash
git add src/pydsvdcapi/binary_input.py
git commit -m "feat(binary_input): add BinaryInputSettingsChangedCallback type and on_settings_changed property"
```

---

## Task 3 — `ButtonInputSettingsChangedCallback` + `ButtonInput.on_settings_changed`

**Files:**
- Modify: `src/pydsvdcapi/button_input.py`

- [ ] **Step 1: Add type alias near the top of `button_input.py`**

```python
#: Type alias for the button-input-settings-changed callback.
#: ``async def callback(button_input: ButtonInput, changed: dict[str, Any]) -> None``
ButtonInputSettingsChangedCallback = Callable[
    ["ButtonInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]
```

- [ ] **Step 2: Add instance attribute in `ButtonInput.__init__`**

```python
self._on_settings_changed: ButtonInputSettingsChangedCallback | None = None
```

- [ ] **Step 3: Add property after `apply_settings` method (~line 1050)**

```python
@property
def on_settings_changed(self) -> ButtonInputSettingsChangedCallback | None:
    """Callback invoked when the vdSM writes ``buttonInputSettings``."""
    return self._on_settings_changed

@on_settings_changed.setter
def on_settings_changed(self, callback: ButtonInputSettingsChangedCallback | None) -> None:
    self._on_settings_changed = callback
```

- [ ] **Step 4: Verify ruff + mypy**

```bash
ruff check src/pydsvdcapi/button_input.py
mypy src/pydsvdcapi/button_input.py
```

- [ ] **Step 5: Commit**

```bash
git add src/pydsvdcapi/button_input.py
git commit -m "feat(button_input): add ButtonInputSettingsChangedCallback type and on_settings_changed property"
```

---

## Task 4 — `SensorInputSettingsChangedCallback` + `SensorInput.on_settings_changed`

**Files:**
- Modify: `src/pydsvdcapi/sensor_input.py`

- [ ] **Step 1: Add type alias near the top of `sensor_input.py`**

```python
#: Type alias for the sensor-input-settings-changed callback.
#: ``async def callback(sensor_input: SensorInput, changed: dict[str, Any]) -> None``
SensorInputSettingsChangedCallback = Callable[
    ["SensorInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]
```

- [ ] **Step 2: Add instance attribute in `SensorInput.__init__`**

```python
self._on_settings_changed: SensorInputSettingsChangedCallback | None = None
```

- [ ] **Step 3: Add property after `apply_settings` method (~line 602)**

```python
@property
def on_settings_changed(self) -> SensorInputSettingsChangedCallback | None:
    """Callback invoked when the vdSM writes ``sensorSettings``."""
    return self._on_settings_changed

@on_settings_changed.setter
def on_settings_changed(self, callback: SensorInputSettingsChangedCallback | None) -> None:
    self._on_settings_changed = callback
```

- [ ] **Step 4: Verify ruff + mypy**

```bash
ruff check src/pydsvdcapi/sensor_input.py
mypy src/pydsvdcapi/sensor_input.py
```

- [ ] **Step 5: Commit**

```bash
git add src/pydsvdcapi/sensor_input.py
git commit -m "feat(sensor_input): add SensorInputSettingsChangedCallback type and on_settings_changed property"
```

---

## Task 5 — Wire callbacks in `vdc_host.py`

`_apply_vdsd_set_property` is currently synchronous. We make it `async` so it can `await` the optional callbacks after each `apply_settings()` call. The callers in `vdc_host.py` already run inside an async context and just need an `await` added.

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py` (line 1396 area and each `apply_settings()` call site)

- [ ] **Step 1: Make `_apply_vdsd_set_property` async**

Change line 1396:
```python
def _apply_vdsd_set_property(self, vdsd: Any, incoming: dict[str, Any]) -> None:
```
to:
```python
async def _apply_vdsd_set_property(self, vdsd: Any, incoming: dict[str, Any]) -> None:
```

- [ ] **Step 2: `await` the caller at line ~1373**

Find where `_apply_vdsd_set_property` is called. It looks like:
```python
self._apply_vdsd_set_property(vdsd, incoming)
```
Change to:
```python
await self._apply_vdsd_set_property(vdsd, incoming)
```

The enclosing method is already `async` (it's inside the message-handling coroutine), so this is safe.

- [ ] **Step 3: After `btn.apply_settings(settings)` (~line 1427), add callback invocation**

```python
btn.apply_settings(settings)
logger.info(
    "vdSD '%s' buttonInputSettings[%d] updated",
    vdsd.dsuid,
    idx,
)
if btn.on_settings_changed is not None:
    try:
        await btn.on_settings_changed(btn, settings)
    except Exception:
        logger.exception(
            "on_settings_changed callback raised for buttonInput[%d] on vdSD '%s'",
            idx,
            vdsd.dsuid,
        )
```

- [ ] **Step 4: After `bi.apply_settings(settings)` (~line 1446), add callback invocation**

```python
bi.apply_settings(settings)
logger.info(
    "vdSD '%s' binaryInputSettings[%d] updated",
    vdsd.dsuid,
    idx,
)
if bi.on_settings_changed is not None:
    try:
        await bi.on_settings_changed(bi, settings)
    except Exception:
        logger.exception(
            "on_settings_changed callback raised for binaryInput[%d] on vdSD '%s'",
            idx,
            vdsd.dsuid,
        )
```

- [ ] **Step 5: After `si.apply_settings(settings)` (~line 1465), add callback invocation**

```python
si.apply_settings(settings)
logger.info(
    "vdSD '%s' sensorSettings[%d] updated",
    vdsd.dsuid,
    idx,
)
if si.on_settings_changed is not None:
    try:
        await si.on_settings_changed(si, settings)
    except Exception:
        logger.exception(
            "on_settings_changed callback raised for sensorInput[%d] on vdSD '%s'",
            idx,
            vdsd.dsuid,
        )
```

- [ ] **Step 6: After `output.apply_settings(out_settings)` (~line 1477), add callback invocation**

```python
output.apply_settings(out_settings)
logger.info(
    "vdSD '%s' outputSettings updated",
    vdsd.dsuid,
)
if output.on_settings_changed is not None:
    try:
        await output.on_settings_changed(output, out_settings)
    except Exception:
        logger.exception(
            "on_settings_changed callback raised for output on vdSD '%s'",
            vdsd.dsuid,
        )
```

- [ ] **Step 7: Verify ruff + mypy on vdc_host**

```bash
ruff check src/pydsvdcapi/vdc_host.py
mypy src/pydsvdcapi/vdc_host.py
```

- [ ] **Step 8: Run existing test suite to confirm nothing broke**

```bash
pytest tests/ -x -q
```

Expected: all existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py
git commit -m "feat(vdc_host): invoke on_settings_changed callbacks after apply_settings"
```

---

## Task 6 — `push_settings()` on all four component types

Each component gets an async `push_settings()` method that sends `VDC_SEND_PUSH_NOTIFICATION` with the component's full settings subtree. The property-tree key matches what `vdsd.py` uses for `getProperty` responses:

| Component | Property key | Index key |
|-----------|-------------|-----------|
| `Output` | `outputSettings` | (no index, singleton) |
| `BinaryInput` | `binaryInputSettings` | `str(ds_index)` |
| `ButtonInput` | `buttonInputSettings` | `str(ds_index)` |
| `SensorInput` | `sensorSettings` | `str(ds_index)` |

### 6a — `Output.push_settings()`

**File:** `src/pydsvdcapi/output.py`

Add after `_push_channel_state()` (~line 1654):

```python
async def push_settings(self) -> None:
    """Push the current ``outputSettings`` to the vdSM.

    Sends a ``VDC_SEND_PUSH_NOTIFICATION`` with the full
    ``outputSettings`` property subtree.  A no-op if the session is
    not active or the vdSD has not been announced.
    """
    session = self._session
    if session is None:
        logger.debug(
            "No active session — skipping push_settings for output '%s'",
            self._name,
        )
        return
    if not self._vdsd.is_announced:
        logger.debug(
            "vdSD not announced — skipping push_settings for output '%s'",
            self._name,
        )
        return

    settings_dict = self.get_settings_properties()
    push_tree: dict[str, Any] = {"outputSettings": settings_dict}

    msg = pb.Message()
    msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
    msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
    for elem in dict_to_elements(push_tree):
        msg.vdc_send_push_notification.changedproperties.append(elem)

    try:
        await session.send_notification(msg)
        logger.debug(
            "Pushed outputSettings for vdSD %s: %s",
            self._vdsd.dsuid,
            settings_dict,
        )
    except (ConnectionError, OSError) as exc:
        logger.warning(
            "Failed to push outputSettings for vdSD %s: %s",
            self._vdsd.dsuid,
            exc,
        )
```

### 6b — `BinaryInput.push_settings()`

**File:** `src/pydsvdcapi/binary_input.py`

Add after `_push_state()` (~line 571):

```python
async def push_settings(self, session: VdcSession | None = None) -> None:
    """Push the current ``binaryInputSettings`` to the vdSM.

    Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
    ``binaryInputSettings`` subtree for this input.  A no-op if no
    session is active or the vdSD is not announced.
    """
    session = session or self._session
    if session is None:
        logger.debug(
            "BinaryInput[%d]: no active session — skipping push_settings",
            self._ds_index,
        )
        return
    if not self._vdsd.is_announced:
        logger.debug(
            "BinaryInput[%d]: vdSD not announced — skipping push_settings",
            self._ds_index,
        )
        return

    settings_dict = self.get_settings_properties()
    push_tree: dict[str, Any] = {
        "binaryInputSettings": {str(self._ds_index): settings_dict}
    }

    msg = pb.Message()
    msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
    msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
    for elem in dict_to_elements(push_tree):
        msg.vdc_send_push_notification.changedproperties.append(elem)

    try:
        await session.send_notification(msg)
        logger.debug(
            "BinaryInput[%d] '%s': pushed settings for vdSD %s",
            self._ds_index,
            self._name,
            self._vdsd.dsuid,
        )
    except (ConnectionError, OSError) as exc:
        logger.warning(
            "BinaryInput[%d] '%s': failed to push settings: %s",
            self._ds_index,
            self._name,
            exc,
        )
```

### 6c — `ButtonInput.push_settings()`

**File:** `src/pydsvdcapi/button_input.py`

Add after the `apply_settings` method and `on_settings_changed` property (~line 1055). Follow the exact same pattern as 6b, substituting:
- `BinaryInput` → `ButtonInput`
- `"binaryInputSettings"` → `"buttonInputSettings"`
- `self._ds_index` → `self._ds_index`
- log prefix `"ButtonInput"`.

Full method:

```python
async def push_settings(self, session: VdcSession | None = None) -> None:
    """Push the current ``buttonInputSettings`` to the vdSM.

    Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
    ``buttonInputSettings`` subtree for this input.  A no-op if no
    session is active or the vdSD is not announced.
    """
    session = session or self._session
    if session is None:
        logger.debug(
            "ButtonInput[%d]: no active session — skipping push_settings",
            self._ds_index,
        )
        return
    if not self._vdsd.is_announced:
        logger.debug(
            "ButtonInput[%d]: vdSD not announced — skipping push_settings",
            self._ds_index,
        )
        return

    settings_dict = self.get_settings_properties()
    push_tree: dict[str, Any] = {
        "buttonInputSettings": {str(self._ds_index): settings_dict}
    }

    msg = pb.Message()
    msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
    msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
    for elem in dict_to_elements(push_tree):
        msg.vdc_send_push_notification.changedproperties.append(elem)

    try:
        await session.send_notification(msg)
        logger.debug(
            "ButtonInput[%d]: pushed settings for vdSD %s",
            self._ds_index,
            self._vdsd.dsuid,
        )
    except (ConnectionError, OSError) as exc:
        logger.warning(
            "ButtonInput[%d]: failed to push settings: %s",
            self._ds_index,
            exc,
        )
```

### 6d — `SensorInput.push_settings()`

**File:** `src/pydsvdcapi/sensor_input.py`

Add after `_do_push` / `_on_deferred_push_fired` (~line 810). Follow the same pattern:

```python
async def push_settings(self, session: VdcSession | None = None) -> None:
    """Push the current ``sensorSettings`` to the vdSM.

    Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
    ``sensorSettings`` subtree for this sensor input.  A no-op if no
    session is active or the vdSD is not announced.
    """
    session = session or self._session
    if session is None:
        logger.debug(
            "SensorInput[%d]: no active session — skipping push_settings",
            self._ds_index,
        )
        return
    if not self._vdsd.is_announced:
        logger.debug(
            "SensorInput[%d]: vdSD not announced — skipping push_settings",
            self._ds_index,
        )
        return

    settings_dict = self.get_settings_properties()
    push_tree: dict[str, Any] = {
        "sensorSettings": {str(self._ds_index): settings_dict}
    }

    msg = pb.Message()
    msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
    msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
    for elem in dict_to_elements(push_tree):
        msg.vdc_send_push_notification.changedproperties.append(elem)

    try:
        await session.send_notification(msg)
        logger.debug(
            "SensorInput[%d] '%s': pushed settings for vdSD %s",
            self._ds_index,
            self._name,
            self._vdsd.dsuid,
        )
    except (ConnectionError, OSError) as exc:
        logger.warning(
            "SensorInput[%d] '%s': failed to push settings: %s",
            self._ds_index,
            self._name,
            exc,
        )
```

- [ ] **Step: After adding all four push_settings methods, run ruff + mypy + tests**

```bash
ruff check src/pydsvdcapi/output.py src/pydsvdcapi/binary_input.py src/pydsvdcapi/button_input.py src/pydsvdcapi/sensor_input.py
mypy src/pydsvdcapi/output.py src/pydsvdcapi/binary_input.py src/pydsvdcapi/button_input.py src/pydsvdcapi/sensor_input.py
pytest tests/ -x -q
```

- [ ] **Step: Commit all four push_settings methods**

```bash
git add src/pydsvdcapi/output.py src/pydsvdcapi/binary_input.py src/pydsvdcapi/button_input.py src/pydsvdcapi/sensor_input.py
git commit -m "feat: add push_settings() to Output, BinaryInput, ButtonInput, SensorInput"
```

---

## Task 7 — Export new types from `__init__.py`

**Files:**
- Modify: `src/pydsvdcapi/__init__.py`

- [ ] **Step 1: Add new callback type names to `__all__`**

In the `# Output` section of `__all__`, add after `"DimChannelCallback"`:

```python
"OutputSettingsChangedCallback",
```

In the `# Inputs` section, add:

```python
"BinaryInputSettingsChangedCallback",
"ButtonInputSettingsChangedCallback",
"SensorInputSettingsChangedCallback",
```

- [ ] **Step 2: Add import lines**

In the `from pydsvdcapi.output import` block, add `OutputSettingsChangedCallback`.

In the `from pydsvdcapi.binary_input import` block, add `BinaryInputSettingsChangedCallback`.

In the `from pydsvdcapi.button_input import` block, add `ButtonInputSettingsChangedCallback`.

In the `from pydsvdcapi.sensor_input import` block, add `SensorInputSettingsChangedCallback`.

- [ ] **Step 3: Verify ruff**

```bash
ruff check src/pydsvdcapi/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add src/pydsvdcapi/__init__.py
git commit -m "feat(__init__): export Settings*ChangedCallback type aliases"
```

---

## Task 8 — Tests

**Files:**
- Create: `tests/test_settings_callbacks.py`

Use the same test infrastructure pattern as `tests/test_binary_input.py` and `tests/test_output.py`: build a minimal `Vdc`/`Vdsd` from `VdcHost`, add a component, then exercise the callback and push paths.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_callbacks.py` with these test cases:

```python
"""Tests for settings-changed callbacks and push_settings() on all component types."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pydsvdcapi as api
from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.button_input import ButtonInput
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.output import Output
from pydsvdcapi.enums import (
    BinaryInputType,
    BinaryInputUsage,
    ButtonFunction,
    ButtonGroup,
    ButtonMode,
    ButtonType,
    OutputFunction,
    SensorType,
    SensorUsage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vdsd():
    """Return a minimal Vdsd with a mock session."""
    host = MagicMock()
    host._store = None
    host._session = None
    vdc = api.Vdc(dsuid=api.DsUid.new_random(), name="test-vdc")
    vdsd = api.Vdsd(dsuid=api.DsUid.new_random(), name="test-device", vdc=vdc)
    vdsd._is_announced = True  # pretend announced
    return vdsd


def _make_session():
    session = MagicMock()
    session.send_notification = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# BinaryInput
# ---------------------------------------------------------------------------

class TestBinaryInputSettingsCallback:
    def setup_method(self):
        vdsd = _make_vdsd()
        self.bi = vdsd.add_binary_input(
            input_type=BinaryInputType.PRESENCE,
            usage=BinaryInputUsage.ROOM,
        )

    @pytest.mark.asyncio
    async def test_callback_fired_when_settings_change(self):
        fired = []

        async def cb(bi, changed):
            fired.append((bi, changed))

        self.bi.on_settings_changed = cb
        self.bi.apply_settings({"group": 5})
        # apply_settings is synchronous; callback invocation is the host's job.
        # We test the callback by calling it directly as the host would.
        if self.bi.on_settings_changed is not None:
            await self.bi.on_settings_changed(self.bi, {"group": 5})

        assert len(fired) == 1
        bi_arg, changed = fired[0]
        assert bi_arg is self.bi
        assert changed == {"group": 5}

    def test_callback_default_is_none(self):
        assert self.bi.on_settings_changed is None

    def test_callback_can_be_cleared(self):
        async def cb(bi, changed): ...
        self.bi.on_settings_changed = cb
        self.bi.on_settings_changed = None
        assert self.bi.on_settings_changed is None

    @pytest.mark.asyncio
    async def test_push_settings_no_session(self):
        # Should not raise; just logs and returns.
        self.bi._session = None
        await self.bi.push_settings()  # no-op

    @pytest.mark.asyncio
    async def test_push_settings_sends_notification(self):
        session = _make_session()
        self.bi._session = session
        await self.bi.push_settings()

        session.send_notification.assert_awaited_once()
        msg = session.send_notification.call_args[0][0]
        # Decode changedproperties back to a dict to verify structure.
        from pydsvdcapi.property_handling import elements_to_dict
        props = elements_to_dict(list(msg.vdc_send_push_notification.changedproperties))
        assert "binaryInputSettings" in props
        bi_settings = props["binaryInputSettings"]
        ds_idx_str = str(self.bi.ds_index)
        assert ds_idx_str in bi_settings
        # The settings dict must contain at least "group" and "sensorFunction".
        inner = bi_settings[ds_idx_str]
        assert "group" in inner
        assert "sensorFunction" in inner


# ---------------------------------------------------------------------------
# ButtonInput
# ---------------------------------------------------------------------------

class TestButtonInputSettingsCallback:
    def setup_method(self):
        vdsd = _make_vdsd()
        self.btn = vdsd.add_button_input(
            button_type=ButtonType.SINGLE_01,
            group=ButtonGroup.YELLOW,
        )

    @pytest.mark.asyncio
    async def test_callback_fired(self):
        fired = []
        async def cb(btn, changed): fired.append(changed)
        self.btn.on_settings_changed = cb
        if self.btn.on_settings_changed:
            await self.btn.on_settings_changed(self.btn, {"group": 1})
        assert fired == [{"group": 1}]

    def test_callback_default_is_none(self):
        assert self.btn.on_settings_changed is None

    @pytest.mark.asyncio
    async def test_push_settings_no_session(self):
        self.btn._session = None
        await self.btn.push_settings()  # no-op

    @pytest.mark.asyncio
    async def test_push_settings_sends_notification(self):
        session = _make_session()
        self.btn._session = session
        await self.btn.push_settings()

        session.send_notification.assert_awaited_once()
        msg = session.send_notification.call_args[0][0]
        from pydsvdcapi.property_handling import elements_to_dict
        props = elements_to_dict(list(msg.vdc_send_push_notification.changedproperties))
        assert "buttonInputSettings" in props
        inner = props["buttonInputSettings"][str(self.btn.ds_index)]
        assert "group" in inner
        assert "function" in inner
        assert "mode" in inner


# ---------------------------------------------------------------------------
# SensorInput
# ---------------------------------------------------------------------------

class TestSensorInputSettingsCallback:
    def setup_method(self):
        vdsd = _make_vdsd()
        self.si = vdsd.add_sensor_input(
            sensor_type=SensorType.TEMPERATURE,
            usage=SensorUsage.ROOM,
        )

    @pytest.mark.asyncio
    async def test_callback_fired(self):
        fired = []
        async def cb(si, changed): fired.append(changed)
        self.si.on_settings_changed = cb
        if self.si.on_settings_changed:
            await self.si.on_settings_changed(self.si, {"group": 2})
        assert fired == [{"group": 2}]

    def test_callback_default_is_none(self):
        assert self.si.on_settings_changed is None

    @pytest.mark.asyncio
    async def test_push_settings_no_session(self):
        self.si._session = None
        await self.si.push_settings()  # no-op

    @pytest.mark.asyncio
    async def test_push_settings_sends_notification(self):
        session = _make_session()
        self.si._session = session
        await self.si.push_settings()

        session.send_notification.assert_awaited_once()
        msg = session.send_notification.call_args[0][0]
        from pydsvdcapi.property_handling import elements_to_dict
        props = elements_to_dict(list(msg.vdc_send_push_notification.changedproperties))
        assert "sensorSettings" in props
        inner = props["sensorSettings"][str(self.si.ds_index)]
        assert "group" in inner
        assert "minPushInterval" in inner
        assert "changesOnlyInterval" in inner


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class TestOutputSettingsCallback:
    def setup_method(self):
        vdsd = _make_vdsd()
        self.output = vdsd.add_output(function=OutputFunction.DIMMER)

    @pytest.mark.asyncio
    async def test_callback_fired(self):
        fired = []
        async def cb(out, changed): fired.append(changed)
        self.output.on_settings_changed = cb
        if self.output.on_settings_changed:
            await self.output.on_settings_changed(self.output, {"mode": 1})
        assert fired == [{"mode": 1}]

    def test_callback_default_is_none(self):
        assert self.output.on_settings_changed is None

    @pytest.mark.asyncio
    async def test_push_settings_no_session(self):
        self.output._session = None
        await self.output.push_settings()  # no-op

    @pytest.mark.asyncio
    async def test_push_settings_sends_notification(self):
        session = _make_session()
        self.output._session = session
        await self.output.push_settings()

        session.send_notification.assert_awaited_once()
        msg = session.send_notification.call_args[0][0]
        from pydsvdcapi.property_handling import elements_to_dict
        props = elements_to_dict(list(msg.vdc_send_push_notification.changedproperties))
        assert "outputSettings" in props
        inner = props["outputSettings"]
        assert "mode" in inner


# ---------------------------------------------------------------------------
# __init__ exports
# ---------------------------------------------------------------------------

def test_callback_types_exported():
    assert hasattr(api, "OutputSettingsChangedCallback")
    assert hasattr(api, "BinaryInputSettingsChangedCallback")
    assert hasattr(api, "ButtonInputSettingsChangedCallback")
    assert hasattr(api, "SensorInputSettingsChangedCallback")
```

- [ ] **Step 2: Run tests to verify they fail before implementation (TDD baseline)**

```bash
pytest tests/test_settings_callbacks.py -v
```

Expected: `AttributeError` / `ImportError` failures because the new types don't exist yet.

- [ ] **Step 3: After all Tasks 1–7 are complete, run tests again**

```bash
pytest tests/test_settings_callbacks.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -q
```

Expected: all tests pass (no regressions).

- [ ] **Step 5: Commit tests**

```bash
git add tests/test_settings_callbacks.py
git commit -m "test: add tests for settings callbacks and push_settings()"
```

---

## Task 9 — Final lint + type check pass

- [ ] **Step 1: ruff check across all modified files**

```bash
ruff check src/pydsvdcapi/output.py src/pydsvdcapi/binary_input.py \
  src/pydsvdcapi/button_input.py src/pydsvdcapi/sensor_input.py \
  src/pydsvdcapi/vdc_host.py src/pydsvdcapi/__init__.py \
  tests/test_settings_callbacks.py
```

Expected: no errors.

- [ ] **Step 2: mypy check across all modified source files**

```bash
mypy src/pydsvdcapi/output.py src/pydsvdcapi/binary_input.py \
  src/pydsvdcapi/button_input.py src/pydsvdcapi/sensor_input.py \
  src/pydsvdcapi/vdc_host.py src/pydsvdcapi/__init__.py
```

Expected: no errors.

- [ ] **Step 3: Full test suite one more time**

```bash
pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Final commit (if any lint fixes were needed)**

```bash
git add -p  # stage only the lint fixes
git commit -m "fix: ruff/mypy cleanup for settings callbacks feature"
```
