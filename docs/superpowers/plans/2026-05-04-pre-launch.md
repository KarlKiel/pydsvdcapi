# pydsvdcapi Pre-Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `pydsvdcapi` to a clean, publishable 0.8.0 state: zero mypy errors, zero ruff violations, correct public API, complete packaging, and first-pass documentation.

**Architecture:** Four sequential phases — Phase 1 fixes real bugs, Phase 2 auto-modernises code style, Phase 3 restructures the public API and adds packaging infrastructure, Phase 4 adds documentation and examples. Each phase leaves the test suite green and ruff/mypy cleaner than before.

**Tech Stack:** Python ≥ 3.10, setuptools src-layout, protobuf, pytest, ruff, mypy, GitHub Actions, Sphinx (or MkDocs — decided in Task 13).

---

## File Map

### Modified
| File | Change |
|---|---|
| `src/pydsvdcapi/binary_input.py` | Add `force` param to `_push_state` |
| `src/pydsvdcapi/session.py` | Guard `_on_hello` None, fix `code` annotation |
| `src/pydsvdcapi/vdc.py` | Add `DeviceTemplate` to `TYPE_CHECKING`, fix `int` return, fix `B008` |
| `src/pydsvdcapi/output.py` | Fix `buffer_channel_value` type, fix `apply_pending_channels` key type |
| `src/pydsvdcapi/conversion.py` | Delete (content moves to `addons/converter/`) |
| `src/pydsvdcapi/__init__.py` | Add `ENTITY_TYPE_VDC_HOST`, add converters re-export, add `__all__`, bump version |
| `pyproject.toml` | Fix coverage omit, add `types-PyYAML`, bump `requires-python`, update classifiers, bump version |
| `CHANGELOG.md` | Convert `[Unreleased]` → `[0.8.0]` |
| `docs/*.md` | Replace old `pyDSvDCAPI` name |
| `README.md` | Badges, feature list, quick-start |
| `examples/full_showcase.py` | Modernise typing imports |
| `.gitignore` | Ignore `examples/__pycache__` |
| All `src/` and `tests/` files | ruff auto-fixes (import sort, type annotations) |

### Created
| File | Purpose |
|---|---|
| `src/pydsvdcapi/addons/__init__.py` | `addons` namespace package |
| `src/pydsvdcapi/addons/converter/__init__.py` | Public converter API (`compile_converter`, `apply_converter`) |
| `tests/addons/__init__.py` | Test package init |
| `tests/addons/test_converter.py` | Converter sub-package tests (replacing `tests/test_conversion.py` content) |
| `.github/workflows/ci.yml` | Pytest + ruff + mypy matrix on 3.10–3.13 |
| `.github/workflows/publish.yml` | PyPI publish on `v*` tags |
| `examples/getting_started.py` | Minimal single-device example |
| `docs/conf.py` **or** `mkdocs.yml` | API doc tooling config |

---

## Phase 1 — Fix Real Bugs

> Gate: `mypy src/pydsvdcapi` 0 errors; `pytest` 0 failures.

---

### Task 1: Add `force` parameter to `BinaryInput._push_state`

**Files:**
- Modify: `src/pydsvdcapi/binary_input.py:521-525`
- Test: `tests/test_binary_input.py`

The call site in `vdsd.py:2183` passes `force=True` but `BinaryInput._push_state` doesn't accept it.
Mirror the signature from `SensorInput._push_state` (line 681–686).

- [ ] **Write a failing test** that calls `_push_state` with `force=True`

  Add to `tests/test_binary_input.py` (find the class `TestBinaryInputPushState` or equivalent, add at the end of its existing tests):

  ```python
  @pytest.mark.asyncio
  async def test_push_state_accepts_force_keyword():
      """Regression: _push_state must accept force=True without TypeError."""
      vdsd = Vdsd(dsuid=DsUid.new_uuid_based(), name="test")
      bi = BinaryInput(
          binary_input_type=BinaryInputType.MOTION,
          usage=BinaryInputUsage.ROOM,
          parent=vdsd,
      )
      # Should not raise TypeError
      await bi._push_state(None, force=True)
      await bi._push_state(None, force=False)
  ```

- [ ] **Run the test to verify it fails**

  ```bash
  .venv/bin/pytest tests/test_binary_input.py::test_push_state_accepts_force_keyword -v
  ```
  Expected: `FAILED` with `TypeError: _push_state() got an unexpected keyword argument 'force'`

- [ ] **Add `force: bool = False` to `_push_state`** in `src/pydsvdcapi/binary_input.py`

  Current (line 521–524):
  ```python
  async def _push_state(
      self,
      session: Optional[VdcSession],
  ) -> None:
  ```

  Replace with:
  ```python
  async def _push_state(
      self,
      session: Optional[VdcSession],
      *,
      force: bool = False,
  ) -> None:
  ```

  The `force` parameter is intentionally unused for now — `BinaryInput` has no throttle logic, so `force` is a no-op. Add `noqa: ARG002` only if ruff later flags it; for now the param simply makes the call site valid.

- [ ] **Run the test to verify it passes**

  ```bash
  .venv/bin/pytest tests/test_binary_input.py::test_push_state_accepts_force_keyword -v
  ```
  Expected: `PASSED`

- [ ] **Run the full suite to check for regressions**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```
  Expected: all existing tests pass.

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/binary_input.py tests/test_binary_input.py
  git commit -m "fix: add force parameter to BinaryInput._push_state

  Callers in vdsd.py pass force=True on reconnect; the missing
  parameter caused a TypeError at runtime. Mirrors the existing
  SensorInput._push_state signature."
  ```

---

### Task 2: Fix `session.py` type errors

**Files:**
- Modify: `src/pydsvdcapi/session.py:394-397` and the `_send_generic_error` signature
- Test: `tests/test_session.py`

Two mypy errors: `_invoke_on_hello` calls `self._on_hello` without asserting it's not None; `_send_generic_error` receives `int` but assigns to a field typed `ResultCode`.

- [ ] **Verify the current mypy errors**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/session.py
  ```
  Expected output includes:
  ```
  session.py:397: error: "None" not callable  [misc]
  session.py:447: error: Incompatible types in assignment ... "ResultCode"  [assignment]
  ```

- [ ] **Fix `_invoke_on_hello`** — add an assertion before the call

  Current (`session.py:394-399`):
  ```python
  async def _invoke_on_hello(self) -> None:
      """Wrapper that invokes *_on_hello* with error handling."""
      try:
          await self._on_hello(self)
      except Exception:  # noqa: BLE001
          logger.exception("Error in on_hello callback")
  ```

  Replace with:
  ```python
  async def _invoke_on_hello(self) -> None:
      """Wrapper that invokes *_on_hello* with error handling."""
      assert self._on_hello is not None  # guarded by caller
      try:
          await self._on_hello(self)
      except Exception:  # noqa: BLE001
          logger.exception("Error in on_hello callback")
  ```

- [ ] **Fix `_send_generic_error`** — suppress the protobuf enum assignment via `type: ignore[assignment]`

  Locate the line (around 447):
  ```python
  response.generic_response.code = code
  ```
  Change to:
  ```python
  response.generic_response.code = code  # type: ignore[assignment]  # protobuf accepts int for enum fields at runtime
  ```

- [ ] **Verify mypy now passes on session.py**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/session.py
  ```
  Expected: `Success: no issues found in 1 source file`

- [ ] **Run full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```
  Expected: all tests pass.

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/session.py
  git commit -m "fix: resolve mypy errors in session.py

  Assert _on_hello is not None inside _invoke_on_hello (caller already
  guards). Suppress protobuf enum assignment type mismatch with a
  targeted type: ignore."
  ```

---

### Task 3: Fix `vdc.py` type errors

**Files:**
- Modify: `src/pydsvdcapi/vdc.py:55-58` (TYPE_CHECKING block) and `~446` (return cast)

Two mypy errors: `DeviceTemplate` used as a string annotation in `load_template`'s return type but not imported under `TYPE_CHECKING`; `_announce_one` inner function returns `Any` from `device.announce()`.

- [ ] **Verify current mypy errors**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/vdc.py 2>&1 | grep error
  ```
  Expected: lines for `name-defined` (DeviceTemplate) and `no-any-return`.

- [ ] **Add `DeviceTemplate` to the `TYPE_CHECKING` block**

  Find the block starting at `if TYPE_CHECKING:` (around line 55):
  ```python
  if TYPE_CHECKING:
      from pydsvdcapi.session import VdcSession
      from pydsvdcapi.vdc_host import VdcHost
      from pydsvdcapi.vdsd import Device, Vdsd
  ```

  Replace with:
  ```python
  if TYPE_CHECKING:
      from pydsvdcapi.device_template import DeviceTemplate
      from pydsvdcapi.session import VdcSession
      from pydsvdcapi.vdc_host import VdcHost
      from pydsvdcapi.vdsd import Device, Vdsd
  ```

- [ ] **Fix `_announce_one` return** — cast to `int`

  Find `_announce_one` (around line 444):
  ```python
  async def _announce_one(device) -> int:
      try:
          return await device.announce(session)
      except Exception:  # noqa: BLE001
          logger.exception(
              "Failed to announce device %s", device.dsuid
          )
          return 0
  ```

  Replace with:
  ```python
  async def _announce_one(device: Any) -> int:
      try:
          result = await device.announce(session)
          return int(result)
      except Exception:  # noqa: BLE001
          logger.exception(
              "Failed to announce device %s", device.dsuid
          )
          return 0
  ```

  (`Any` is already imported at the top of `vdc.py`.)

- [ ] **Verify mypy passes on vdc.py**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/vdc.py
  ```
  Expected: `Success: no issues found in 1 source file`

- [ ] **Run full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/vdc.py
  git commit -m "fix: resolve mypy errors in vdc.py

  Import DeviceTemplate under TYPE_CHECKING for load_template return
  annotation. Cast device.announce() result to int to fix no-any-return."
  ```

---

### Task 4: Fix `output.py` type errors

**Files:**
- Modify: `src/pydsvdcapi/output.py:1340-1373`

Two related errors: `buffer_channel_value` stores `channel.value` (typed `float | None`) in a `Dict[int, float]` with a wrong `type: ignore` code; `apply_pending_channels` assigns to a local `Dict[OutputChannelType, float]` using a key that may be `int`.

- [ ] **Verify current mypy errors**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/output.py 2>&1 | grep error
  ```
  Expected: `unused-ignore` and `assignment` on line 1353; `index` on line 1373.

- [ ] **Fix `buffer_channel_value`** — use the `value` parameter instead of `channel.value`

  Current (`output.py:1350-1354`):
  ```python
  channel.set_value_from_vdsm(value)
  self._pending_channel_updates[channel.ds_index] = (
      channel.value  # type: ignore[arg-type]
  )
  ```

  Replace with:
  ```python
  channel.set_value_from_vdsm(value)
  self._pending_channel_updates[channel.ds_index] = value
  ```

  `value: float` is already the parameter — using it directly avoids the `float | None` issue that `channel.value` introduces.

- [ ] **Fix `apply_pending_channels`** — widen the `updates` dict key type

  Current (`output.py:1369`):
  ```python
  updates: Dict[OutputChannelType, float] = {}
  ```

  Replace with:
  ```python
  updates: Dict[OutputChannelType | int, float] = {}
  ```

  `OutputChannelType` is already imported. `channel_type` is typed `OutputChannelType | int` (channels created with raw int channel IDs remain as `int`), so the dict must accept both.

- [ ] **Verify mypy passes on output.py**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/output.py
  ```
  Expected: `Success: no issues found in 1 source file`

- [ ] **Run full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/output.py
  git commit -m "fix: resolve mypy errors in output.py

  buffer_channel_value: use the 'value' parameter directly instead of
  re-reading channel.value (avoids float|None mismatch).
  apply_pending_channels: widen updates dict key to OutputChannelType|int
  to match OutputChannel.channel_type's declared type."
  ```

---

### Task 5: Fix `conversion.py` mypy error

**Files:**
- Modify: `src/pydsvdcapi/conversion.py:92-98`

`compile_converter` returns `namespace["_converter"]` which is `Any`; the declared return type is `Callable[[Any], Any]`.

- [ ] **Verify the error**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/conversion.py
  ```
  Expected: `error: Returning Any from function declared to return "Callable[[Any], Any]"  [no-any-return]`

- [ ] **Add a cast** at the return site

  `cast` is available from `typing` which is already imported.

  Current (`conversion.py:96-98`):
  ```python
  namespace: dict = {}
  exec(compiled, namespace)  # noqa: S102
  return namespace["_converter"]
  ```

  Replace with:
  ```python
  namespace: dict = {}
  exec(compiled, namespace)  # noqa: S102
  return cast(Callable[[Any], Any], namespace["_converter"])
  ```

  Add `cast` to the existing `from typing import ...` import line at the top:
  ```python
  from typing import Any, Callable, Optional, cast
  ```

- [ ] **Verify mypy passes on conversion.py**

  ```bash
  .venv/bin/mypy src/pydsvdcapi/conversion.py
  ```
  Expected: `Success: no issues found in 1 source file`

- [ ] **Run full mypy to confirm Phase 1 is complete** (except PyYAML stubs added in Phase 3)

  ```bash
  .venv/bin/mypy src/pydsvdcapi 2>&1 | grep "error:"
  ```
  Expected: only `import-untyped` errors for yaml (fixed in Task 9); no other errors.

- [ ] **Run full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/conversion.py
  git commit -m "fix: cast compile_converter return to satisfy mypy

  exec() places the compiled function in a plain dict typed as Any.
  Cast to Callable[[Any], Any] to match the declared return type."
  ```

---

## Phase 2 — Code Quality

> Gate: `ruff check src/ tests/ examples/` exits 0; `ruff format --check src/ tests/ examples/` exits 0.

---

### Task 6: Ruff auto-fix pass

**Files:** All `src/pydsvdcapi/*.py`, `tests/*.py`, `examples/full_showcase.py`

This task is fully automated. Ruff fixes 179 violations with `--fix` and ~1 000 more with `--unsafe-fix`. The unsafe fixes are safe here because every source file already has `from __future__ import annotations`.

- [ ] **Run `--fix` (safe fixes only)**

  ```bash
  .venv/bin/ruff check --fix src/ tests/ examples/
  ```
  Expected: "Fixed N violations." (I001, F401-fixable, UP037, UP009, UP015)

- [ ] **Run `--unsafe-fix` (annotation modernisation)**

  ```bash
  .venv/bin/ruff check --unsafe-fix src/ tests/ examples/
  ```
  Expected: "Fixed N violations." (UP045 `Optional[X]`→`X|None`, UP006 `Dict`→`dict`, UP007 `Union`→`|`, UP035 deprecated imports)

- [ ] **Format**

  ```bash
  .venv/bin/ruff format src/ tests/ examples/
  ```

- [ ] **Run the test suite to confirm nothing broke**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```
  Expected: same pass count as before (1 429+).

- [ ] **Check how many violations remain**

  ```bash
  .venv/bin/ruff check src/ tests/ examples/ --statistics 2>&1
  ```
  Expected: only the rules that require manual fixes (B008, F841, SIM102, SIM108, B007, F811, E402).

- [ ] **Commit**

  ```bash
  git add -u
  git commit -m "style: apply ruff auto-fixes across src, tests, examples

  Modernises type annotations (Optional→X|None, Dict→dict, Union→X|Y),
  removes unused imports, sorts import blocks, removes UTF-8 encoding
  declarations. All changes are safe with from __future__ import
  annotations present."
  ```

---

### Task 7: Manual ruff fixes

**Files:**
- `src/pydsvdcapi/vdc.py` (B008)
- `tests/test_vdc.py` (F841)
- `tests/test_auto_save.py` (F841)
- `tests/test_button_input.py` (B007)
- `tests/test_output_channel.py` (F811)
- `tests/test_vdsd.py` (E402)
- Any remaining SIM102 / SIM108 location (run `ruff check` to find exact file)

- [ ] **Fix B008 in `vdc.py`** — mutable default argument

  Find `Vdc.__init__` signature (around line 236):
  ```python
  def __init__(
      self,
      ...
      capabilities: VdcCapabilities = VdcCapabilities(),
      ...
  ) -> None:
  ```

  Replace with:
  ```python
  def __init__(
      self,
      ...
      capabilities: VdcCapabilities | None = None,
      ...
  ) -> None:
  ```

  At the start of `__init__`, add:
  ```python
  if capabilities is None:
      capabilities = VdcCapabilities()
  ```

- [ ] **Fix F841 unused variables in tests**

  In `tests/test_vdc.py` near line 342: remove or use `vdc` if assigned but never referenced.
  In `tests/test_auto_save.py` near line 143: remove `host = ` from the assignment, or prefix with `_`.

  Find exact lines:
  ```bash
  .venv/bin/ruff check tests/test_vdc.py tests/test_auto_save.py --select F841
  ```

  For each: either delete the unused variable or prefix with `_` if it must be assigned (e.g. context manager side-effects).

- [ ] **Fix B007 in `test_button_input.py`**

  Find line 1217 — a `for ct in ...:` loop where `ct` is never used inside the body. Replace `ct` with `_`:
  ```python
  for _ in ...:
  ```

- [ ] **Fix F811 in `test_output_channel.py`**

  Near line 1379, `ChannelSpec` is imported again (re-defining the import from line 37). Remove the duplicate import.

- [ ] **Fix E402 in `test_vdsd.py`**

  Lines 2176-2177 have module-level imports after test code. Move them to the top of the file with the other imports, using a `# noqa: E402` comment only if moving them would cause a circular import (unlikely in a test file).

- [ ] **Fix SIM102 / SIM108** — find the exact location

  ```bash
  .venv/bin/ruff check src/ tests/ --select SIM102,SIM108
  ```

  For SIM102 (nested if → single if with `and`):
  ```python
  # before
  if a:
      if b:
          ...
  # after
  if a and b:
      ...
  ```

  For SIM108 (if/else → ternary):
  ```python
  # before
  if condition:
      x = a
  else:
      x = b
  # after
  x = a if condition else b
  ```

- [ ] **Verify zero remaining violations**

  ```bash
  .venv/bin/ruff check src/ tests/ examples/
  ```
  Expected: `All checks passed.`

- [ ] **Run test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add -u
  git commit -m "fix: resolve remaining ruff violations requiring manual edits

  B008: move VdcCapabilities() default out of Vdc.__init__ signature.
  F841/B007/F811: remove or rename unused variables in tests.
  E402: move late imports to top of test_vdsd.py.
  SIM102/SIM108: simplify nested conditions."
  ```

---

## Phase 3 — API Surface & Packaging

> Gate: `pip install -e ".[dev]"` clean; `mypy src/pydsvdcapi` 0 errors; CI green.

---

### Task 8: Create `addons/converter` sub-package

**Files:**
- Create: `src/pydsvdcapi/addons/__init__.py`
- Create: `src/pydsvdcapi/addons/converter/__init__.py`
- Create: `tests/addons/__init__.py`
- Create: `tests/addons/test_converter.py`
- Modify: `src/pydsvdcapi/__init__.py` (add re-export — done in Task 9)

The current `conversion.py` moves into the `addons/converter` namespace. The old `conversion.py` becomes an internal import shim that re-exports from the new location for backward compatibility during this transition (removed after confirming no user code imports `pydsvdcapi.conversion` directly, which is a private module).

- [ ] **Create `src/pydsvdcapi/addons/__init__.py`** (empty namespace package)

  ```python
  """pydsvdcapi add-ons namespace."""
  ```

- [ ] **Create `src/pydsvdcapi/addons/converter/__init__.py`**

  Copy the full content of `src/pydsvdcapi/conversion.py` verbatim, then update the module docstring first line to:

  ```python
  """Value converter helpers — pydsvdcapi.addons.converter.

  ...rest of existing docstring unchanged...
  """
  ```

  The imports and the two public functions (`compile_converter`, `apply_converter`) remain identical.

- [ ] **Update `src/pydsvdcapi/conversion.py`** to a re-export shim

  Replace the entire file content with:

  ```python
  """Backward-compatible re-export shim.

  Import from pydsvdcapi.addons.converter instead.
  """
  from pydsvdcapi.addons.converter import apply_converter, compile_converter

  __all__ = ["apply_converter", "compile_converter"]
  ```

- [ ] **Write tests for the new sub-package path**

  Create `tests/addons/__init__.py` (empty).

  Create `tests/addons/test_converter.py`:

  ```python
  """Tests for pydsvdcapi.addons.converter public API."""

  import pytest
  from pydsvdcapi.addons.converter import apply_converter, compile_converter


  def test_compile_converter_simple_expression():
      fn = compile_converter("value = value * 2")
      assert fn(5) == 10


  def test_compile_converter_multiline():
      fn = compile_converter("""
          if value > 100:
              value = 100
      """)
      assert fn(200) == 100
      assert fn(50) == 50


  def test_compile_converter_syntax_error_raises():
      with pytest.raises(SyntaxError):
          compile_converter("value = ??? bad syntax")


  def test_apply_converter_none_is_passthrough():
      assert apply_converter(None, 42, component_id="x", direction="uplink") == 42


  def test_apply_converter_calls_fn():
      fn = compile_converter("value = value + 1")
      assert apply_converter(fn, 10, component_id="x", direction="uplink") == 11


  def test_apply_converter_on_exception_returns_original(caplog):
      fn = compile_converter("raise ValueError('boom')")
      result = apply_converter(fn, 99, component_id="my_sensor", direction="downlink")
      assert result == 99
      assert "Converter error" in caplog.text
  ```

- [ ] **Run the new tests**

  ```bash
  .venv/bin/pytest tests/addons/test_converter.py -v
  ```
  Expected: all 6 tests `PASSED`.

- [ ] **Run the full suite** (the shim in `conversion.py` keeps old tests passing)

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/addons/ tests/addons/
  git add src/pydsvdcapi/conversion.py
  git commit -m "feat: move converter utilities to addons/converter sub-package

  compile_converter and apply_converter are now the public API at
  pydsvdcapi.addons.converter. conversion.py becomes a re-export shim
  for any internal code still referencing the old path."
  ```

---

### Task 9: Fix `__init__.py` exports and `__all__`

**Files:**
- Modify: `src/pydsvdcapi/__init__.py`

Add the missing `ENTITY_TYPE_VDC_HOST` export, the converters re-export, and define `__all__`.

- [ ] **Add `ENTITY_TYPE_VDC_HOST` to the `vdc_host` import block**

  Find the block:
  ```python
  from pydsvdcapi.vdc_host import (  # noqa: F401
      AUTO_SAVE_DELAY,
      AuthenticateCallback,
      DEFAULT_VDC_PORT,
      ...
  )
  ```

  Add `ENTITY_TYPE_VDC_HOST` to the list (alphabetically among the other constants):
  ```python
  from pydsvdcapi.vdc_host import (  # noqa: F401
      AUTO_SAVE_DELAY,
      AuthenticateCallback,
      DEFAULT_VDC_PORT,
      ENTITY_TYPE_VDC_HOST,
      FirmwareUpgradeCallback,
      ...
  )
  ```

- [ ] **Add the converters re-export block** at the end of the imports:

  ```python
  from pydsvdcapi.addons.converter import (  # noqa: F401
      apply_converter,
      compile_converter,
  )
  ```

- [ ] **Add `__all__`** immediately after `__version__`:

  ```python
  __version__ = "0.1.0"  # updated in Task 11

  __all__ = [
      # Version
      "__version__",
      # Enums
      "ActionMode",
      "AirFlowDirection",
      "ApartmentScene",
      "ApartmentTemperatureMode",
      "ApartmentVentilationLevel",
      "AudioDeviceScene",
      "AudioScene",
      "AwningScene",
      "BinaryInputGroup",
      "BinaryInputType",
      "BinaryInputUsage",
      "ButtonClickType",
      "ButtonElementID",
      "ButtonFunction",
      "ButtonFunctionJoker",
      "ButtonGroup",
      "ButtonMode",
      "ButtonType",
      "button_function_for_group",
      "ClimateDeviceScene",
      "ColorClass",
      "ColorGroup",
      "DeviceScene",
      "EntityType",
      "ErrorType",
      "HeatingSystemCapability",
      "HeatingSystemType",
      "InputError",
      "LightScene",
      "MessageType",
      "OutputChannelType",
      "OutputError",
      "OutputFunction",
      "OutputHardwareMode",
      "OutputMode",
      "OutputUsage",
      "PowerState",
      "ResultCode",
      "SceneEffect",
      "SceneNumber",
      "SceneScope",
      "SensorGroup",
      "SensorType",
      "SensorUsage",
      "ShadeScene",
      "TemperatureControlScene",
      "TemperatureDeviceScene",
      "VentilationScene",
      "ZoneScene",
      "ZoneTemperatureMode",
      # DsUid
      "DSUID_BYTES",
      "DsUid",
      "DsUidNamespace",
      "DsUidType",
      # Connection
      "MAX_MESSAGE_LENGTH",
      "VdcConnection",
      # Persistence
      "PropertyStore",
      # Session
      "SUPPORTED_API_VERSION",
      "HelloCallback",
      "MessageCallback",
      "SessionState",
      "VdcSession",
      # VdcHost
      "AUTO_SAVE_DELAY",
      "AuthenticateCallback",
      "DEFAULT_VDC_PORT",
      "ENTITY_TYPE_VDC_HOST",
      "FirmwareUpgradeCallback",
      "IdentifyCallback",
      "PairCallback",
      "RemoveCallback",
      "SetConfigurationCallback",
      "VdcHost",
      # Vdc
      "ENTITY_TYPE_VDC",
      "Vdc",
      "VdcCapabilities",
      # Vdsd / Device
      "ControlValueCallback",
      "ENTITY_TYPE_VDSD",
      "Device",
      "DeviceIdentifyCallback",
      "InvokeActionCallback",
      "Vdsd",
      # Actions
      "ActionParameter",
      "CustomAction",
      "DeviceActionDescription",
      "DynamicAction",
      "StandardAction",
      # Inputs
      "BinaryInput",
      "BUTTON_TYPE_ELEMENTS",
      "ButtonInput",
      "ClickDetector",
      "SensorInput",
      "create_button_group",
      "get_required_elements",
      # Events / States / Properties
      "DeviceEvent",
      "DeviceState",
      "PROPERTY_TYPE_ENUMERATION",
      "PROPERTY_TYPE_NUMERIC",
      "PROPERTY_TYPE_STRING",
      "VALID_PROPERTY_TYPES",
      "DeviceProperty",
      # Output
      "DimChannelCallback",
      "FUNCTION_CHANNELS",
      "Output",
      "CHANNEL_SPECS",
      "ChannelSpec",
      "OutputChannel",
      "get_channel_spec",
      # Property handling
      "NO_VALUE",
      "build_get_property_response",
      "dict_to_elements",
      "elements_to_dict",
      "expand_setproperty_wildcards",
      "match_query",
      # Device template
      "AnnouncementNotReadyError",
      "DeviceTemplate",
      "TemplateNotConfiguredError",
      # Converters (add-on)
      "apply_converter",
      "compile_converter",
  ]
  ```

- [ ] **Verify the public API is importable**

  ```bash
  .venv/bin/python -c "import pydsvdcapi; print(pydsvdcapi.ENTITY_TYPE_VDC_HOST)"
  ```
  Expected: `vDChost`

  ```bash
  .venv/bin/python -c "import pydsvdcapi; print(pydsvdcapi.compile_converter)"
  ```
  Expected: `<function compile_converter at 0x...>`

- [ ] **Run full suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add src/pydsvdcapi/__init__.py
  git commit -m "feat: add __all__, ENTITY_TYPE_VDC_HOST, and converters to public API

  Defines an explicit __all__ for the top-level namespace. Exports the
  previously missing ENTITY_TYPE_VDC_HOST constant. Re-exports
  compile_converter / apply_converter from the new addons/converter
  sub-package."
  ```

---

### Task 10: Update `pyproject.toml` and version

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/pydsvdcapi/__init__.py`
- Modify: `CHANGELOG.md`

- [ ] **Fix coverage `omit`, add `types-PyYAML`, bump Python version and project version**

  In `pyproject.toml`, apply these changes:

  *Section `[project]`* — version and requires-python:
  ```toml
  version = "0.8.0"
  requires-python = ">=3.10"
  ```

  *Section `[project]` classifiers* — remove `"Programming Language :: Python :: 3.9"`, keep 3.10–3.13.

  *Section `[project.optional-dependencies]` dev* — add:
  ```toml
  "types-PyYAML>=6.0",
  ```

  *Section `[tool.mypy]`*:
  ```toml
  python_version = "3.10"
  ```

  *Section `[tool.coverage.run]`*:
  ```toml
  omit = [
      "src/pydsvdcapi/vdc_messages_pb2.py",
      "src/pydsvdcapi/vdcapi_pb2.py",
  ]
  ```

- [ ] **Bump version in `__init__.py`**

  ```python
  __version__ = "0.8.0"
  ```

- [ ] **Update `CHANGELOG.md`** — convert `[Unreleased]` to `[0.8.0]`

  Change the heading:
  ```markdown
  ## [0.8.0] - 2026-05-04
  ```

  Update the link at the bottom:
  ```markdown
  [0.8.0]: https://github.com/KarlKiel/pyDSvDCAPI/compare/v0.1.0...v0.8.0
  [0.1.0]: https://github.com/KarlKiel/pyDSvDCAPI/releases/tag/v0.1.0
  ```

  Remove the old `[Unreleased]: ...` link line.

- [ ] **Reinstall to pick up new dev deps**

  ```bash
  .venv/bin/pip install -e ".[dev]"
  ```

- [ ] **Verify mypy is now fully clean**

  ```bash
  .venv/bin/mypy src/pydsvdcapi
  ```
  Expected: `Success: no issues found in N source files`

- [ ] **Verify version**

  ```bash
  .venv/bin/python -c "import pydsvdcapi; print(pydsvdcapi.__version__)"
  ```
  Expected: `0.8.0`

- [ ] **Run full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```

- [ ] **Commit**

  ```bash
  git add pyproject.toml src/pydsvdcapi/__init__.py CHANGELOG.md
  git commit -m "chore: bump to 0.8.0, require Python >=3.10, fix pyproject metadata

  - Version 0.8.0 (pre-release, not fully tested)
  - Drop Python 3.9 support (EOL Oct 2025)
  - Add types-PyYAML to dev deps (fixes mypy import-untyped errors)
  - Fix coverage omit: replace deleted genericVDC_pb2 with actual proto files
  - Update CHANGELOG: Unreleased → 0.8.0"
  ```

---

### Task 11: Add GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Create `.github/workflows/` directory**

  ```bash
  mkdir -p .github/workflows
  ```

- [ ] **Write `.github/workflows/ci.yml`**

  ```yaml
  name: CI

  on:
    push:
      branches: [main]
    pull_request:
      branches: [main]

  jobs:
    test:
      name: "Test / Python ${{ matrix.python-version }}"
      runs-on: ubuntu-latest
      strategy:
        fail-fast: false
        matrix:
          python-version: ["3.10", "3.11", "3.12", "3.13"]

      steps:
        - uses: actions/checkout@v4

        - uses: actions/setup-python@v5
          with:
            python-version: ${{ matrix.python-version }}

        - name: Install dependencies
          run: pip install -e ".[dev]"

        - name: Run tests
          run: python -m pytest --tb=short -q

        - name: Lint (ruff check)
          run: ruff check src/ tests/ examples/

        - name: Format check (ruff format)
          run: ruff format --check src/ tests/ examples/

        - name: Type-check (mypy)
          run: mypy src/pydsvdcapi
  ```

- [ ] **Commit**

  ```bash
  git add .github/workflows/ci.yml
  git commit -m "ci: add GitHub Actions workflow for pytest, ruff, mypy on Python 3.10–3.13"
  ```

---

### Task 12: Add PyPI publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

Uses PyPI's trusted publisher (OIDC) — no API token stored in secrets.

- [ ] **Write `.github/workflows/publish.yml`**

  ```yaml
  name: Publish to PyPI

  on:
    push:
      tags:
        - "v*"

  jobs:
    build-and-publish:
      name: Build and publish to PyPI
      runs-on: ubuntu-latest
      environment: pypi
      permissions:
        id-token: write   # required for OIDC trusted publisher

      steps:
        - uses: actions/checkout@v4

        - uses: actions/setup-python@v5
          with:
            python-version: "3.12"

        - name: Install build tools
          run: pip install build

        - name: Build sdist and wheel
          run: python -m build

        - name: Publish to PyPI
          uses: pypa/gh-action-pypi-publish@release/v1
  ```

  > **Before first publish:** Set up the trusted publisher on PyPI: go to pypi.org → your account → Publishing → Add a new pending publisher. Enter owner `KarlKiel`, repo `pyDSvDCAPI`, workflow `publish.yml`, environment `pypi`. Then create the `pypi` environment in the GitHub repo settings.

- [ ] **Commit**

  ```bash
  git add .github/workflows/publish.yml
  git commit -m "ci: add PyPI publish workflow triggered on v* tags

  Uses OIDC trusted publisher — no API tokens required. Requires the
  'pypi' environment to be configured in GitHub and the trusted
  publisher to be registered on PyPI."
  ```

---

### Task 13: Cleanup — stale pycache and gitignore

**Files:**
- Modify: `.gitignore`
- Delete: `examples/__pycache__/` directory and contents

- [ ] **Delete stale pycache**

  ```bash
  rm -rf examples/__pycache__
  ```

- [ ] **Add to `.gitignore`**

  Open `.gitignore`. Add the following if not already present:
  ```gitignore
  # Examples pycache
  examples/__pycache__/
  ```

- [ ] **Verify pycache does not reappear in git status**

  ```bash
  git status
  ```
  Expected: no `examples/__pycache__` in the output.

- [ ] **Commit**

  ```bash
  git add .gitignore
  git rm -r --cached examples/__pycache__/ 2>/dev/null || true
  git commit -m "chore: remove stale examples/__pycache__ and ignore it in .gitignore"
  ```

---

## Phase 4 — Documentation & Examples

> Gate: README self-contained for new users; API docs browsable online; both examples run without errors.

---

### Task 14: Fix naming inconsistency in `docs/`

**Files:**
- Modify: `docs/model-features-auto-assignment.md`
- Modify: `docs/vdc-db-device-catalogue.md`
- Modify: `docs/vdc-api-properties.md`
- Modify: `docs/vdc-host-behavior.md`

- [ ] **Find all occurrences**

  ```bash
  grep -rn "pyDSvDCAPI" docs/
  ```

- [ ] **Replace all** `pyDSvDCAPI` with `pydsvdcapi` in each file

  ```bash
  sed -i 's/pyDSvDCAPI/pydsvdcapi/g' docs/model-features-auto-assignment.md
  sed -i 's/pyDSvDCAPI/pydsvdcapi/g' docs/vdc-db-device-catalogue.md
  sed -i 's/pyDSvDCAPI/pydsvdcapi/g' docs/vdc-api-properties.md
  sed -i 's/pyDSvDCAPI/pydsvdcapi/g' docs/vdc-host-behavior.md
  ```

- [ ] **Verify no occurrences remain**

  ```bash
  grep -rn "pyDSvDCAPI" docs/ || echo "All clear"
  ```

- [ ] **Commit**

  ```bash
  git add docs/
  git commit -m "docs: replace old 'pyDSvDCAPI' name with 'pydsvdcapi' throughout"
  ```

---

### Task 15: Expand `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Replace the entire `README.md`** with the following content (adapt the badge URLs once CI is confirmed active):

  ````markdown
  # pydsvdcapi

  [![CI](https://github.com/KarlKiel/pyDSvDCAPI/actions/workflows/ci.yml/badge.svg)](https://github.com/KarlKiel/pyDSvDCAPI/actions/workflows/ci.yml)
  [![PyPI](https://img.shields.io/pypi/v/pydsvdcapi)](https://pypi.org/project/pydsvdcapi/)
  [![Python](https://img.shields.io/pypi/pyversions/pydsvdcapi)](https://pypi.org/project/pydsvdcapi/)
  [![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

  Python library for the **digitalSTROM virtual Device Connector (vDC) API**.

  ## What this library does

  - Implements the full vDC protobuf protocol over TCP
  - Manages the session lifecycle (hello/pong, announcement, reconnect)
  - Models all device classes: lights, blinds, sensors, buttons, heating, audio, and more
  - Provides a composable API: `VdcHost` → `Vdc` → `Vdsd` → components
  - Persists device state across restarts via a YAML property store
  - Automatically derives `modelFeatures` flags from configured components
  - Supports value converters for uplink/downlink data transformation

  ## Installation

  ```bash
  pip install pydsvdcapi
  ```

  Requires Python 3.10+.

  ## Quick start

  ```python
  import asyncio
  from pydsvdcapi import (
      VdcHost, Vdc, Device, Vdsd,
      DsUid, DsUidNamespace,
      Output, OutputFunction, OutputMode, OutputUsage,
      ColorGroup,
  )

  async def main():
      host = VdcHost(dsuid=DsUid.new_uuid_based(), name="My VDC Host")

      vdc = Vdc(dsuid=DsUid.new_uuid_based(), name="My VDC")
      host.add_vdc(vdc)

      device = Device(dsuid=DsUid.new_gtin_based("0000000000001", 0))
      vdsd = Vdsd(dsuid=DsUid.new_uuid_based(), name="My Light")
      output = Output(
          function=OutputFunction.LIGHT,
          mode=OutputMode.SWITCH,
          usage=OutputUsage.ROOM,
          group=ColorGroup.YELLOW,
      )
      vdsd.set_output(output)
      device.add_vdsd(vdsd)
      vdc.add_device(device)

      await host.run()  # connects and blocks until stopped

  asyncio.run(main())
  ```

  See [`examples/getting_started.py`](examples/getting_started.py) for a minimal runnable example
  and [`examples/full_showcase.py`](examples/full_showcase.py) for all 27 device classes.

  ## Development

  ```bash
  git clone https://github.com/KarlKiel/pyDSvDCAPI.git
  cd pyDSvDCAPI
  python -m venv .venv && source .venv/bin/activate
  pip install -e ".[dev]"
  ```

  | Command | Purpose |
  |---|---|
  | `python -m pytest` | Run tests |
  | `ruff check src/ tests/` | Lint |
  | `ruff format src/ tests/` | Format |
  | `mypy src/pydsvdcapi` | Type-check |

  See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidance.

  ## Documentation

  API reference: *(link added after Task 16 — hosted docs)*

  Domain documentation lives in [`docs/`](docs/):
  - [vDC API Properties](docs/vdc-api-properties.md)
  - [VDC Host Behavior](docs/vdc-host-behavior.md)
  - [Device Splitting Guidelines](docs/device-splitting-guidelines.md)

  ## License

  GPLv3 — see [LICENSE](LICENSE).
  ````

- [ ] **Verify the README renders correctly** (visual check in IDE or browser)

- [ ] **Commit**

  ```bash
  git add README.md
  git commit -m "docs: expand README with badges, feature list, quick-start, and dev table"
  ```

---

### Task 16: Write `examples/getting_started.py`

**Files:**
- Create: `examples/getting_started.py`

A minimal 50-line example that demonstrates one VDC + one switchable light device. Should run against a real dSS or produce a clean "waiting for connection" log line.

- [ ] **Create `examples/getting_started.py`**

  ```python
  #!/usr/bin/env python3
  """Minimal pydsvdcapi example — one VDC, one switchable light.

  Usage:
      python examples/getting_started.py [--port PORT] [--debug]

  The VDC connects on the given port (default: 8340) and announces
  a single yellow light device.  Press Ctrl-C to stop.
  """

  from __future__ import annotations

  import argparse
  import asyncio
  import logging

  from pydsvdcapi import (
      ColorGroup,
      Device,
      DsUid,
      Output,
      OutputFunction,
      OutputMode,
      OutputUsage,
      Vdc,
      VdcHost,
      Vdsd,
  )


  async def main(port: int) -> None:
      host = VdcHost(dsuid=DsUid.new_uuid_based(), name="Getting Started Host")

      vdc = Vdc(dsuid=DsUid.new_uuid_based(), name="Getting Started VDC")
      host.add_vdc(vdc)

      device = Device(dsuid=DsUid.new_gtin_based("0000000000001", 0))
      vdsd = Vdsd(dsuid=DsUid.new_uuid_based(), name="My Light")

      output = Output(
          function=OutputFunction.LIGHT,
          mode=OutputMode.SWITCH,
          usage=OutputUsage.ROOM,
          group=ColorGroup.YELLOW,
      )
      vdsd.set_output(output)
      device.add_vdsd(vdsd)
      vdc.add_device(device)

      logging.info("Starting VDC host on port %d — press Ctrl-C to stop", port)
      await host.run(port=port)


  if __name__ == "__main__":
      parser = argparse.ArgumentParser(description="pydsvdcapi getting-started example")
      parser.add_argument("--port", type=int, default=8340)
      parser.add_argument("--debug", action="store_true")
      args = parser.parse_args()

      logging.basicConfig(
          level=logging.DEBUG if args.debug else logging.INFO,
          format="%(asctime)s %(levelname)s %(name)s: %(message)s",
      )

      asyncio.run(main(args.port))
  ```

- [ ] **Verify it imports cleanly** (even without a dSS present)

  ```bash
  .venv/bin/python -c "import examples.getting_started"
  ```
  Expected: no ImportError or SyntaxError.

- [ ] **Commit**

  ```bash
  git add examples/getting_started.py
  git commit -m "docs: add minimal getting_started.py example"
  ```

---

### Task 17: Set up API documentation tooling

**Decision point:** Sphinx is the Python standard and integrates well with ReadTheDocs. MkDocs with mkdocstrings is simpler to configure. Choose based on preference; steps below cover **Sphinx**. If you prefer MkDocs, swap `sphinx` for `mkdocs + mkdocstrings[python]` and create `mkdocs.yml` instead of `docs/conf.py`.

**Files:**
- Modify: `pyproject.toml` (add `docs` optional deps)
- Create: `docs/conf.py`
- Create: `docs/index.rst`
- Create: `.readthedocs.yaml`

- [ ] **Add docs dependencies to `pyproject.toml`**

  Under `[project.optional-dependencies]`:
  ```toml
  docs = [
      "sphinx>=7.0",
      "sphinx-autodoc-typehints>=1.25",
      "furo>=2024.0",          # clean theme
  ]
  ```

- [ ] **Install docs deps**

  ```bash
  .venv/bin/pip install -e ".[docs]"
  ```

- [ ] **Generate a starter Sphinx config**

  ```bash
  .venv/bin/sphinx-quickstart docs --quiet \
      --project pydsvdcapi \
      --author "KarlKiel" \
      --release 0.8.0 \
      --language en \
      --ext-autodoc \
      --ext-viewcode \
      --no-sep
  ```

  This creates `docs/conf.py` and `docs/index.rst`.

- [ ] **Update `docs/conf.py`** — add the src path and enable typehints

  Add near the top (after `import os, sys`):
  ```python
  import os
  import sys
  sys.path.insert(0, os.path.abspath("../src"))
  ```

  In the `extensions` list, add `"sphinx_autodoc_typehints"`:
  ```python
  extensions = [
      "sphinx.ext.autodoc",
      "sphinx.ext.viewcode",
      "sphinx_autodoc_typehints",
  ]
  ```

  Set theme:
  ```python
  html_theme = "furo"
  ```

- [ ] **Write `docs/index.rst`**

  ```rst
  pydsvdcapi
  ==========

  Python library for the digitalSTROM virtual Device Connector (vDC) API.

  .. toctree::
     :maxdepth: 2
     :caption: Contents

     api

  API Reference
  =============

  .. autosummary::
     :toctree: generated
     :nosignatures:

     pydsvdcapi
  ```

- [ ] **Create `docs/api.rst`**

  ```rst
  API Reference
  =============

  .. automodule:: pydsvdcapi
     :members:
     :undoc-members:
     :show-inheritance:
  ```

- [ ] **Build docs locally**

  ```bash
  .venv/bin/sphinx-build -b html docs docs/_build/html
  ```
  Expected: `build succeeded` with at most a few warnings about missing docstrings.

- [ ] **Create `.readthedocs.yaml`** for hosted deployment

  ```yaml
  version: 2

  build:
    os: ubuntu-22.04
    tools:
      python: "3.12"

  python:
    install:
      - method: pip
        path: .
        extra_requirements:
          - docs

  sphinx:
    configuration: docs/conf.py
  ```

- [ ] **Add `docs/_build/` to `.gitignore`**

  ```gitignore
  docs/_build/
  ```

- [ ] **Update README** — replace the placeholder API reference link:

  ```markdown
  API reference: [pydsvdcapi.readthedocs.io](https://pydsvdcapi.readthedocs.io)
  ```

- [ ] **Commit**

  ```bash
  git add docs/conf.py docs/index.rst docs/api.rst .readthedocs.yaml pyproject.toml README.md .gitignore
  git commit -m "docs: add Sphinx configuration and ReadTheDocs setup"
  ```

---

### Task 18: Final verification

- [ ] **Full ruff check**

  ```bash
  .venv/bin/ruff check src/ tests/ examples/
  ```
  Expected: `All checks passed.`

- [ ] **Full mypy check**

  ```bash
  .venv/bin/mypy src/pydsvdcapi
  ```
  Expected: `Success: no issues found`

- [ ] **Full test suite**

  ```bash
  .venv/bin/pytest --tb=short -q
  ```
  Expected: 1 429+ passed, 0 failed.

- [ ] **Verify version**

  ```bash
  .venv/bin/python -c "import pydsvdcapi; print(pydsvdcapi.__version__)"
  ```
  Expected: `0.8.0`

- [ ] **Verify __all__ is importable star-style**

  ```bash
  .venv/bin/python -c "from pydsvdcapi import *; print(ENTITY_TYPE_VDC_HOST, compile_converter)"
  ```
  Expected: `vDChost <function compile_converter at 0x...>`

- [ ] **Docs build clean**

  ```bash
  .venv/bin/sphinx-build -b html docs docs/_build/html -W
  ```
  Expected: 0 warnings (or only acceptable `autodoc` ones for generated proto files).

- [ ] **Tag the release**

  ```bash
  git tag v0.8.0
  git push origin main --tags
  ```
  This triggers the publish workflow on GitHub Actions.

---

## Self-Review

**Spec coverage check:**

| REVIEW.md item | Task |
|---|---|
| 1.1 BinaryInput._push_state force | Task 1 |
| 1.2 session.py _on_hello None guard | Task 2 |
| 1.3 session.py ResultCode assignment | Task 2 |
| 1.4 vdc.py DeviceTemplate TYPE_CHECKING | Task 3 |
| 1.5 output.py:1353 type: ignore | Task 4 |
| 1.6 output.py:1373 index type | Task 4 |
| 1.7 vdc.py:446 return type | Task 3 |
| 1.8 conversion.py:98 cast | Task 5 |
| 2.1–2.3 ruff auto-fix | Task 6 |
| 2.4–2.9 ruff manual fix | Task 7 |
| 2.10 full_showcase.py | Task 6 (covered by ruff) |
| 3.1 Export ENTITY_TYPE_VDC_HOST | Task 9 |
| 3.2 __all__ | Task 9 |
| 3.3 Coverage omit fix | Task 10 |
| 3.4 types-PyYAML | Task 10 |
| 3.5 requires-python >=3.10 | Task 10 |
| 3.6 Remove from __future__ (optional — kept, still valid) | — |
| 3.7 Version 0.8.0 | Task 10 |
| 3.8 CHANGELOG | Task 10 |
| 3.9 addons/converter sub-package | Task 8 |
| 3.10 Re-export converters | Task 9 |
| 3.11 CI workflow | Task 11 |
| 3.12 PyPI publish workflow | Task 12 |
| 3.13–3.14 __pycache__ cleanup | Task 13 |
| 3.15 Verify py.typed in sdist | Task 18 |
| 4.1 Naming in docs/ | Task 14 |
| 4.2–4.4 README | Task 15 |
| 4.5 getting_started.py | Task 16 |
| 4.6 Verify doc links | Task 18 |
| 4.7–4.9 Sphinx + hosted docs | Task 17 |

**Note on item 3.6 (remove `from __future__ import annotations`):** Kept as-is. On Python 3.10+, the import is still idiomatic and avoids forward-reference issues. Removing it is a mechanical change with non-zero risk; there's no functional benefit.
