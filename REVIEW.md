# pydsvdcapi — Pre-Launch Review

> Reviewed: 2026-05-04 · Branch: `Code-review-and-documentation`

## Current State Summary

| Dimension | Status |
|---|---|
| Tests | ✅ 1 429 passing, 0 failures |
| Coverage | ✅ 92 % overall |
| Mypy | ❌ 11 errors in 6 files (1 is a runtime bug) |
| Ruff | ❌ 1 162 violations (mostly auto-fixable style) |
| CI / CD | ❌ No GitHub Actions workflow exists |
| PyPI readiness | ❌ Version not bumped, no publish workflow |
| Public API | ⚠️ One constant missing from `__init__` exports |
| Documentation | ⚠️ Old package name used in several doc files |

---

## Findings & Inconsistencies

### Runtime Bug (blocking)

**`vdsd.py:2183` — `force` keyword not accepted by `BinaryInput._push_state`**

```python
# vdsd.py – called on every reconnect / re-announcement:
await bi._push_state(session, force=True)   # TypeError at runtime

# binary_input.py – actual signature:
async def _push_state(self, session: Optional[VdcSession]) -> None: ...
```

The `force=True` keyword is passed unconditionally during device re-announcement but the method signature does not declare it. This raises `TypeError` whenever a device that has binary inputs re-announces (e.g. after a restart or reconnect). The equivalent call on `SensorInput._push_state` does accept `force`.

---

### Mypy Errors (11 total, 6 files)

| File | Line | Rule | Description |
|---|---|---|---|
| `persistence.py` | 40 | `import-untyped` | Missing `types-PyYAML` stubs |
| `vdc.py` | 511 | `import-untyped` | Missing `types-PyYAML` stubs (same) |
| `conversion.py` | 98 | `no-any-return` | `namespace["_converter"]` is `Any`; return type is `Callable[[Any], Any]` |
| `vdsd.py` | 2183 | `call-arg` | `force` not in `BinaryInput._push_state` signature (see runtime bug above) |
| `vdc.py` | 446 | `no-any-return` | Method declared `-> int` returns `Any` |
| `vdc.py` | 560 | `name-defined` | `"DeviceTemplate"` string annotation used but `DeviceTemplate` not imported in `TYPE_CHECKING` block |
| `session.py` | 397 | `misc` | `self._on_hello` is `Optional[HelloCallback]` — called without `None` guard; mypy reports `"None" not callable` |
| `session.py` | 447 | `assignment` | `int` literal assigned to variable typed as `ResultCode` |
| `output.py` | 1353 | `unused-ignore` | `# type: ignore[arg-type]` but actual error is `[assignment]` — wrong ignore code |
| `output.py` | 1353 | `assignment` | `channel.value` is `float \| None`, stored in buffer typed `float` |
| `output.py` | 1373 | `index` | `ds_index` is `int`; dict key type is `OutputChannelType` |

---

### Ruff Violations (1 162 total)

| Count | Rule | Description | Auto-fix? |
|---|---|---|---|
| 542 | UP045 | `Optional[X]` → `X \| None` | unsafe-fix |
| 289 | UP006 | `Dict`/`List`/`Tuple` → `dict`/`list`/`tuple` in annotations | unsafe-fix |
| 104 | UP007 | `Union[X, Y]` → `X \| Y` | unsafe-fix |
| 72 | UP037 | Remove quotes from type annotations | fix |
| 65 | F401 | Unused imports (src and tests) | fix |
| 40 | UP035 | Deprecated `typing.Dict`, `typing.List`, etc. | — |
| 35 | I001 | Unsorted / unformatted import blocks | fix |
| 3 | E402 | Module-level import not at top of file (`test_vdsd.py:2176-77`, `vdc_messages_pb2.py:25`) | — |
| 3 | F841 | Unused local variables | — |
| 2 | UP009 | UTF-8 encoding declaration redundant | fix |
| 1 | B007 | Loop control variable unused (`test_button_input.py:1217`) | — |
| 1 | B008 | `VdcCapabilities()` call in default argument (`vdc.py:236`) | — |
| 1 | F811 | Redefinition of unused `ChannelSpec` (`test_output_channel.py:1379`) | — |
| 1 | F821 | Undefined name `DeviceTemplate` (`vdc.py:560`) — same as mypy error | — |
| 1 | SIM102 | Collapsible `if` | — |
| 1 | SIM108 | `if/else` block can be a ternary | — |

**Important:** All source files already have `from __future__ import annotations`, so the UP045 / UP006 / UP007 unsafe-fixes are completely safe — annotations are already evaluated lazily as strings on Python 3.9.

Quick fix breakdown: `ruff check --fix` auto-removes 179 violations; `ruff check --unsafe-fix` handles the remaining ~1 000 style fixes.

---

### Public API Inconsistencies

1. **Missing export — `ENTITY_TYPE_VDC_HOST`**
   `vdc_host.py` defines `ENTITY_TYPE_VDC_HOST = "vDChost"` but it is not exported from `__init__.py`, whereas `ENTITY_TYPE_VDC` (from `vdc.py`) and `ENTITY_TYPE_VDSD` (from `vdsd.py`) are both exported. Users who need the host entity-type string must reach into the sub-module directly.

2. **`compile_converter` / `apply_converter` not exported**
   `conversion.py` provides the converter utilities that users invoke when configuring components. They are not currently exposed through the top-level `pydsvdcapi` namespace, forcing users to import from the internal module.

3. **No `__all__` in `__init__.py`**
   Without an explicit `__all__`, tools like auto-complete and `from pydsvdcapi import *` have no machine-readable contract for the public surface.

---

### Stale / Incorrect Configuration

1. **`pyproject.toml` coverage `omit` references non-existent file**
   ```toml
   # current (wrong):
   omit = ["src/pydsvdcapi/genericVDC_pb2.py"]
   # should be:
   omit = ["src/pydsvdcapi/vdc_messages_pb2.py", "src/pydsvdcapi/vdcapi_pb2.py"]
   ```
   `genericVDC_pb2.py` was the old name; both generated proto files have very low coverage (19 % and 54 %) and should be excluded.

2. **`src/pydsvdcapi.egg-info/SOURCES.txt` lists old files**
   References `genericVDC_pb2.py` and `genericVDC_pb2.pyi` (both deleted). The egg-info is auto-generated but a clean rebuild is needed before publish.

3. **Stale `__pycache__` in `examples/`**
   `.pyc` files exist for source files that have since been deleted (`developer_guide_demo.py`, `dynamic_features_working.py`, `experiment_state_approaches.py`, `mock_devices.py`, `realworld_demo.py`, and several others). These are harmless but create noise and should be cleaned up.

---

### Versioning & Changelog

- `__version__ = "0.1.0"` everywhere, but the `[Unreleased]` section of `CHANGELOG.md` documents substantial additions (device template system, converter support, `derive_model_features()`, etc.).
- The package is not "0.1.0-equivalent" anymore. A version bump to **0.2.0** (or 1.0.0 if considered stable) and converting `[Unreleased]` to a dated release block is required before PyPI publish.

---

### Documentation Naming Inconsistency

The old repository/package name `pyDSvDCAPI` appears in several docs files after the rename to `pydsvdcapi`:

| File | Occurrences |
|---|---|
| `docs/model-features-auto-assignment.md` | 1 |
| `docs/vdc-db-device-catalogue.md` | 1 |
| `docs/vdc-api-properties.md` | 3 |
| `docs/vdc-host-behavior.md` | 4+ |

---

### Example Quality

- `full_showcase.py` still imports from `typing` using old style (`Dict`, `List`, `Optional`) — inconsistent with the src modernization being planned.
- There is only one example file; all others have been deleted (their `.pyc` files remain). A simple "getting started" example (10–20 lines) alongside the full showcase would lower the barrier for new users.

---

### File Size Concerns (non-blocking, post-launch)

| File | Lines | Note |
|---|---|---|
| `vdsd.py` | 2 636 | Vdsd class + Device dataclass. Good candidate for a future split. |
| `vdc_host.py` | 2 115 | Message-dispatch logic could be extracted. |
| `output.py` | 1 880 | Output + scene handling; dense but coherent. |

These are not blocking for first publish but should be tracked as tech-debt.

---

## Phase Plan to First Publish

### Phase 1 — Fix Real Bugs (blocking)

**Goal:** Zero mypy errors, no runtime TypeError on reconnect.

| # | Action | File | Effort |
|---|---|---|---|
| 1.1 | Add `force: bool = False` parameter to `BinaryInput._push_state` | `binary_input.py:521` | Small |
| 1.2 | Guard `_on_hello` for `None` before awaiting | `session.py:397` | Trivial |
| 1.3 | Fix `int` → `ResultCode` assignment | `session.py:447` | Trivial |
| 1.4 | Add `DeviceTemplate` to `TYPE_CHECKING` import block in `vdc.py` | `vdc.py:55-58` | Trivial |
| 1.5 | Fix `output.py:1353` — correct `type: ignore` code or fix the real type issue | `output.py:1353` | Small |
| 1.6 | Fix `output.py:1373` — `ds_index` lookup via correct key type | `output.py:1373` | Small |
| 1.7 | Fix `vdc.py:446` return type or cast | `vdc.py:446` | Trivial |
| 1.8 | Cast `namespace["_converter"]` in `compile_converter` to satisfy mypy | `conversion.py:98` | Trivial |

**Done when:** `mypy src/pydsvdcapi` reports 0 errors (after `types-PyYAML` added in Phase 3).

---

### Phase 2 — Code Quality (style + lint)

**Goal:** `ruff check src/ tests/` reports 0 errors.

| # | Action | Effort |
|---|---|---|
| 2.1 | Run `ruff check --fix src/ tests/` — auto-removes 179 violations (I001, F401-fixable, UP037, UP009, UP015) | Automated |
| 2.2 | Run `ruff check --unsafe-fix src/ tests/` — modernises ~1 000 type annotations (UP045, UP006, UP007, UP035) | Automated |
| 2.3 | Run `ruff format src/ tests/` | Automated |
| 2.4 | Fix `B008` in `vdc.py:236` — move `VdcCapabilities()` out of default argument | Manual / Small |
| 2.5 | Fix `F841` unused variables (3 instances across tests) | Manual / Trivial |
| 2.6 | Fix `SIM102` (collapsible if) and `SIM108` (ternary) | Manual / Trivial |
| 2.7 | Fix `B007` unused loop variable in `test_button_input.py:1217` | Manual / Trivial |
| 2.8 | Fix `E402` in `test_vdsd.py:2176-77` — move conditional imports to top | Manual / Small |
| 2.9 | Fix `F811` redefined `ChannelSpec` in `test_output_channel.py:1379` | Manual / Trivial |
| 2.10 | Update `full_showcase.py` imports to modern style | Manual / Small |

**Done when:** `ruff check src/ tests/ examples/` exits 0.

---

### Phase 3 — API Surface & Packaging

**Goal:** Clean public API, correct metadata, CI pipeline.

| # | Action | Effort |
|---|---|---|
| 3.1 | Export `ENTITY_TYPE_VDC_HOST` from `__init__.py` | Trivial |
| 3.2 | Export `compile_converter` and `apply_converter` from `__init__.py` | Trivial |
| 3.3 | Add `__all__` to `__init__.py` listing every public name | Small |
| 3.4 | Fix `pyproject.toml` coverage `omit` (replace stale `genericVDC_pb2.py` with actual proto files) | Trivial |
| 3.5 | Add `types-PyYAML` to `[project.optional-dependencies] dev` | Trivial |
| 3.6 | Bump `requires-python` to `>=3.10`; update classifiers; remove `3.9` classifier | Trivial |
| 3.7 | Remove `from __future__ import annotations` from all source files (no longer needed on 3.10+) | Automated |
| 3.8 | Bump version to `0.8.0` in `pyproject.toml` and `__init__.py` | Trivial |
| 3.9 | Convert CHANGELOG `[Unreleased]` → `[0.8.0] - 2026-05-XX` with date | Small |
| 3.10 | Create `src/pydsvdcapi/addons/converter/` sub-package: move `conversion.py` into it as `__init__.py` or `core.py`; expose `compile_converter` and `apply_converter` via `pydsvdcapi.converters` | Medium |
| 3.11 | Re-export `compile_converter` / `apply_converter` from top-level `__init__.py` for convenience | Trivial |
| 3.12 | Add GitHub Actions CI workflow: pytest + ruff + mypy on Python 3.10–3.13 | Medium |
| 3.13 | Add GitHub Actions PyPI publish workflow (on tag push `v*`) | Small |
| 3.14 | Delete `examples/__pycache__` stale `.pyc` files | Trivial |
| 3.15 | Add `examples/` to `.gitignore` for `__pycache__` | Trivial |
| 3.16 | Verify `py.typed` and `*.pyi` included in sdist (already in `package-data`) | Verify |

**Done when:** `pip install -e ".[dev]"` installs cleanly, `mypy src/pydsvdcapi` passes, CI is green on Python 3.10–3.13.

---

### Phase 4 — Documentation & Examples

**Goal:** Consistent naming, useful README, API reference, at least two examples.

| # | Action | Effort |
|---|---|---|
| 4.1 | Replace all `pyDSvDCAPI` occurrences in `docs/` with `pydsvdcapi` | Small |
| 4.2 | Expand `README.md`: add CI badge, PyPI badge, Python versions badge | Small |
| 4.3 | Add feature highlights section to `README.md` (what the library does in 5 bullets) | Small |
| 4.4 | Add a short "Quick-start" example (20–30 lines) to `README.md` | Small |
| 4.5 | Write a minimal `examples/getting_started.py` (single VDC + one device) | Medium |
| 4.6 | Verify all links in `CONTRIBUTING.md` and `CHANGELOG.md` resolve correctly | Trivial |
| 4.7 | Set up Sphinx (or MkDocs) with `autodoc` extension pointed at `src/pydsvdcapi` | Medium |
| 4.8 | Configure Read the Docs (or GitHub Pages) deployment for the generated docs | Small |
| 4.9 | Add a `docs/` link / badge to `README.md` once hosted | Trivial |

**Done when:** README is self-contained for a new user, all docs use the correct package name, API reference is browsable online.

---

## Open Topics

### Resolved

| Topic | Decision |
|---|---|
| Version number | **0.8.0** — not fully tested yet, `0.x` accurately signals that |
| `compile_converter` / `apply_converter` | **Public**, moved to `src/pydsvdcapi/addons/converter/` sub-package; importable as `pydsvdcapi.addons.converter` (see Phase 3) |
| File size / module split | **Keep `vdsd.py` as one file** for now |
| Sphinx / MkDocs API docs | **In scope for Phase 4** |
| Python 3.9 support | **Drop it** — bump `requires-python` to `>=3.10`; removes need for `from __future__ import annotations` |

### Still Open

> None — all pre-launch questions are resolved.

---

## Quick-Reference Checklist (for first publish)

```
Phase 1 — Bugs
[ ] 1.1  BinaryInput._push_state accepts force parameter
[ ] 1.2  session.py _on_hello None guard
[ ] 1.3  session.py ResultCode assignment
[ ] 1.4  vdc.py DeviceTemplate in TYPE_CHECKING
[ ] 1.5  output.py:1353 type: ignore corrected
[ ] 1.6  output.py:1373 index type fixed
[ ] 1.7  vdc.py:446 return type fixed
[ ] 1.8  conversion.py:98 cast added

Phase 2 — Code Quality
[ ] 2.1  ruff check --fix
[ ] 2.2  ruff check --unsafe-fix
[ ] 2.3  ruff format
[ ] 2.4  B008 VdcCapabilities default
[ ] 2.5  F841 unused variables
[ ] 2.6  SIM102 / SIM108
[ ] 2.7  B007 loop variable
[ ] 2.8  E402 test_vdsd.py imports
[ ] 2.9  F811 ChannelSpec redef
[ ] 2.10 full_showcase.py typing imports

Phase 3 — API & Packaging
[ ] 3.1  Export ENTITY_TYPE_VDC_HOST
[ ] 3.2  __all__ in __init__.py
[ ] 3.3  Coverage omit fix (genericVDC_pb2 → actual proto files)
[ ] 3.4  types-PyYAML in dev deps
[ ] 3.5  Bump requires-python to >=3.10; update classifiers
[ ] 3.6  Remove from __future__ import annotations from all source files
[ ] 3.7  Version bump to 0.8.0
[ ] 3.8  CHANGELOG Unreleased → 0.8.0
[ ] 3.9  Create src/pydsvdcapi/addons/converter/ sub-package
[ ] 3.10 Re-export converters from top-level __init__.py
[ ] 3.11 GitHub Actions CI workflow (3.10–3.13)
[ ] 3.12 GitHub Actions PyPI publish workflow
[ ] 3.13 Delete stale __pycache__ in examples/
[ ] 3.14 .gitignore examples/__pycache__
[ ] 3.15 Verify py.typed / *.pyi in sdist

Phase 4 — Docs & Examples
[ ] 4.1  Replace pyDSvDCAPI with pydsvdcapi in docs/
[ ] 4.2  README badges
[ ] 4.3  README feature highlights
[ ] 4.4  README quick-start snippet
[ ] 4.5  examples/getting_started.py
[ ] 4.6  Verify all doc links
[ ] 4.7  Set up Sphinx / MkDocs with autodoc
[ ] 4.8  Configure hosted docs (ReadTheDocs or GitHub Pages)
[ ] 4.9  README docs badge
```
