# Output Property Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five targeted additions to output and channel property serialisation: `movingState` in `outputState`, group 0 always present in `outputSettings.groups`, shadow motor timing defaults so fields are always emitted for shadow devices, a free-text `displayName` for channels independent of the channelId key, and a legacy `channelIndex` field alongside `dsIndex`.

**Architecture:** All changes are isolated to two source files (`output.py`, `output_channel.py`) and their two test files. No new files. No public API removals — all changes are additive except the groups serialisation tweak which updates four existing test assertions.

**Tech Stack:** Python 3.11+, pytest, pydsvdcapi internal module structure.

---

## File map

| File | Changes |
|---|---|
| `src/pydsvdcapi/output.py` | Task 1 (movingState field + property + state dict) · Task 2 (groups serialisation) · Task 5 (shadow timing defaults) |
| `src/pydsvdcapi/output_channel.py` | Task 3 (display_name param + property + description dict + persistence) · Task 4 (channelIndex in description) |
| `tests/test_output.py` | Task 1 (new state tests) · Task 2 (new + updated groups tests) · Task 5 (new + updated shadow timing tests) |
| `tests/test_output_channel.py` | Task 3 (new display_name tests) · Task 4 (new channelIndex tests) |

---

## Task 1: `outputState.movingState`

Add a `moving_state` integer field to `Output` that is surfaced as `"movingState"` in `get_state_properties()`. Values: `0` = idle, `1` = moving up/opening, `-1` = moving down/closing. Field is volatile (not persisted).

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class after `TestOutputStateProperties` in `tests/test_output.py`:

```python
class TestMovingState:
    """Tests for Output.moving_state and outputState["movingState"]."""

    def test_default_is_zero(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        assert out.moving_state == 0
        assert out.get_state_properties()["movingState"] == 0

    def test_set_to_moving_up(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.moving_state = 1
        assert out.get_state_properties()["movingState"] == 1

    def test_set_to_moving_down(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.moving_state = -1
        assert out.get_state_properties()["movingState"] == -1

    def test_not_in_property_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.moving_state = 1
        tree = out.get_property_tree()
        assert "movingState" not in tree
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestMovingState -v
```

Expected: 4 failures — `AttributeError: 'Output' object has no attribute 'moving_state'`

- [ ] **Step 3: Add `_moving_state` to `Output.__init__`**

In `src/pydsvdcapi/output.py`, in `Output.__init__`, find the volatile state block (around line 658):

```python
        # ---- state properties (volatile, NOT persisted) --------------
        self._local_priority: bool = False
        self._error: OutputError = OutputError.OK
        self._transition_time: float = 0.0
```

Change it to:

```python
        # ---- state properties (volatile, NOT persisted) --------------
        self._local_priority: bool = False
        self._error: OutputError = OutputError.OK
        self._transition_time: float = 0.0
        self._moving_state: int = 0
```

- [ ] **Step 4: Add `moving_state` property**

In `src/pydsvdcapi/output.py`, find the `transition_time` property (around line 992) and add the new property immediately after it:

```python
    @property
    def moving_state(self) -> int:
        """Motor movement state: 0=idle, 1=moving up/opening, -1=moving down/closing."""
        return self._moving_state

    @moving_state.setter
    def moving_state(self, value: int) -> None:
        self._moving_state = int(value)
```

- [ ] **Step 5: Include `movingState` in `get_state_properties()`**

In `src/pydsvdcapi/output.py`, find `get_state_properties()` (around line 1958):

```python
        return {
            "localPriority": self._local_priority,
            "transitionTime": self._transition_time,
            "error": int(self._error),
        }
```

Change it to:

```python
        return {
            "localPriority": self._local_priority,
            "transitionTime": self._transition_time,
            "movingState": self._moving_state,
            "error": int(self._error),
        }
```

- [ ] **Step 6: Run tests — all four must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestMovingState -v
```

Expected: 4 passed.

- [ ] **Step 7: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: add movingState to outputState for motor movement tracking"
```

---

## Task 2: Group 0 always present in `outputSettings.groups`

The `groups` dict in the `outputSettings` wire response must always include `"0": true` regardless of what groups the developer configured. The internal `_groups` set and the persisted property tree are unchanged — only the serialised form injected into the vdSM response gains the implicit group 0.

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write new failing tests**

Add a new test class in `tests/test_output.py` (after `TestOutputSettingsProperties`):

```python
class TestGroupZeroAlwaysPresent:
    """Group 0 must always appear in the serialised groups dict."""

    def test_empty_internal_groups_still_emits_group_0(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups=set())
        settings = out.get_settings_properties()
        assert settings["groups"] == {"0": True}

    def test_group_0_present_alongside_other_groups(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={2, 5})
        settings = out.get_settings_properties()
        assert settings["groups"]["0"] is True
        assert settings["groups"]["2"] is True
        assert settings["groups"]["5"] is True

    def test_group_0_not_added_to_internal_set(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={2})
        _ = out.get_settings_properties()
        assert 0 not in out.groups  # _groups is not mutated

    def test_group_0_already_in_internal_set_no_duplication(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={0, 2})
        settings = out.get_settings_properties()
        keys = list(settings["groups"].keys())
        assert keys.count("0") == 1  # appears exactly once
        assert settings["groups"] == {"0": True, "2": True}
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestGroupZeroAlwaysPresent -v
```

Expected: failures — group 0 absent from results.

- [ ] **Step 3: Implement the change in `get_settings_properties()`**

In `src/pydsvdcapi/output.py`, find `get_settings_properties()` (around line 1890):

```python
        settings["groups"] = {str(gid): True for gid in sorted(self._groups)}
```

Change it to:

```python
        all_groups = self._groups | {0}
        settings["groups"] = {str(gid): True for gid in sorted(all_groups)}
```

- [ ] **Step 4: Run new tests — all four must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestGroupZeroAlwaysPresent -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full output test suite to identify broken existing tests**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py -v 2>&1 | grep FAILED
```

Expected failures — these four assertions now include `"0": True` which the old tests did not expect:

| Test | Old assertion | New assertion |
|---|---|---|
| `TestOutputSettingsProperties::test_minimal` line 527 | `{"1": True}` | `{"0": True, "1": True}` |
| `TestOutputSettingsProperties::test_with_groups` line 537 | `{"1": True, "3": True, "5": True}` | `{"0": True, "1": True, "3": True, "5": True}` |
| `TestOutputEdgeCases::test_empty_groups_returns_empty_dict` line 1486 | `{}` | `{"0": True}` |
| `TestOutputEdgeCases::test_groups_sorted_in_settings` line 1504–1505 | `["1", "3", "7", "10"]` | `["0", "1", "3", "7", "10"]` |

- [ ] **Step 6: Fix the four broken existing tests**

In `tests/test_output.py`, apply these four edits:

**Edit 1** — `TestOutputSettingsProperties::test_minimal` (around line 527):
```python
        # old:
        assert settings["groups"] == {"1": True}
        # new:
        assert settings["groups"] == {"0": True, "1": True}
```

**Edit 2** — `TestOutputSettingsProperties::test_with_groups` (around line 537):
```python
        # old:
        assert settings["groups"] == {"1": True, "3": True, "5": True}
        # new:
        assert settings["groups"] == {"0": True, "1": True, "3": True, "5": True}
```

**Edit 3** — `TestOutputEdgeCases::test_empty_groups_returns_empty_dict` (around line 1486):
```python
        # old:
        assert settings["groups"] == {}
        # new:
        assert settings["groups"] == {"0": True}
```

**Edit 4** — `TestOutputEdgeCases::test_groups_sorted_in_settings` (around line 1504–1505):
```python
        # old:
        assert keys == ["1", "3", "7", "10"]
        # new:
        assert keys == ["0", "1", "3", "7", "10"]
```

- [ ] **Step 7: Run full output test suite — no failures**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: always include group 0 in outputSettings groups wire response"
```

---

## Task 3: `display_name` — free label for `channelDescriptions["name"]`

Currently the `name` parameter of `OutputChannel` sets both the container key (the `channelId`) and the `"name"` sub-field inside the channel's description dict. Add a separate `display_name` parameter that overrides only the `"name"` sub-field. The container key continues to use `ch.name` (the canonical channelId). `display_name` is persisted.

**Files:**
- Modify: `src/pydsvdcapi/output_channel.py`
- Test: `tests/test_output_channel.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class `TestDisplayName` in `tests/test_output_channel.py`. The helpers `_make_stack` and `_make_output` already exist in that file.

```python
class TestDisplayName:
    """display_name sets channelDescriptions 'name' independently of the channelId key."""

    def test_default_name_subfield_equals_spec_name(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        desc = ch.get_description_properties()
        assert desc["name"] == "brightness"

    def test_display_name_overrides_name_subfield(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
            display_name="Living Room Light",
        )
        desc = ch.get_description_properties()
        assert desc["name"] == "Living Room Light"

    def test_display_name_does_not_change_container_key(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.SHADE_POSITION_OUTSIDE,
            ds_index=0,
            display_name="Living Room Shade",
        )
        out.add_channel(ch)
        descs = out.get_channel_descriptions()
        assert "shadePositionOutside" in descs
        assert descs["shadePositionOutside"]["name"] == "Living Room Shade"

    def test_display_name_setter_and_clear(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        ch.display_name = "My Label"
        assert ch.get_description_properties()["name"] == "My Label"
        ch.display_name = None
        assert ch.get_description_properties()["name"] == "brightness"

    def test_display_name_persisted_in_property_tree(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
            display_name="Ceiling Light",
        )
        tree = ch.get_property_tree()
        assert tree["displayName"] == "Ceiling Light"

    def test_display_name_absent_from_tree_when_not_set(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        tree = ch.get_property_tree()
        assert "displayName" not in tree

    def test_display_name_restored_from_property_tree(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        ch._apply_state({"displayName": "Restored Label"})
        assert ch.get_description_properties()["name"] == "Restored Label"

    def test_custom_channel_display_name(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=255,
            ds_index=2,
            name="myMode",
            display_name="Operating Mode",
        )
        desc = ch.get_description_properties()
        assert desc["name"] == "Operating Mode"
        # container key is still the channel's name
        out.add_channel(ch)
        descs = out.get_channel_descriptions()
        assert "myMode" in descs
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output_channel.py::TestDisplayName -v
```

Expected: failures — `TypeError` (unexpected keyword argument `display_name`) or `AssertionError`.

- [ ] **Step 3: Add `display_name` parameter to `OutputChannel.__init__`**

In `src/pydsvdcapi/output_channel.py`, find the `__init__` signature (around line 445):

```python
    def __init__(
        self,
        *,
        output: Output,
        channel_type: OutputChannelType | int,
        ds_index: int = 0,
        name: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
        siunit: str | None = None,
        symbol: str | None = None,
        enum_values: dict[int, str] | None = None,
    ) -> None:
```

Change it to:

```python
    def __init__(
        self,
        *,
        output: Output,
        channel_type: OutputChannelType | int,
        ds_index: int = 0,
        name: str | None = None,
        display_name: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
        siunit: str | None = None,
        symbol: str | None = None,
        enum_values: dict[int, str] | None = None,
    ) -> None:
```

- [ ] **Step 4: Store `_display_name` in `__init__` body**

In `src/pydsvdcapi/output_channel.py`, immediately after the name resolution block (the `if name is not None: / elif spec: / else:` block, around line 482), add:

```python
        self._display_name: str | None = display_name
```

- [ ] **Step 5: Add `display_name` property**

In `src/pydsvdcapi/output_channel.py`, after the `name` property (around line 617), add:

```python
    @property
    def display_name(self) -> str | None:
        """Free-text label for the 'name' sub-field in channelDescriptions.

        When set, this overrides the canonical channel name in the property
        response without affecting the channelId container key.
        """
        return self._display_name

    @display_name.setter
    def display_name(self, value: str | None) -> None:
        self._display_name = value
```

- [ ] **Step 6: Use `display_name` in `get_description_properties()`**

In `src/pydsvdcapi/output_channel.py`, find `get_description_properties()` (around line 750). Change the `"name"` entry:

```python
        props: dict[str, Any] = {
            "name": self._name,
            ...
        }
```

to:

```python
        props: dict[str, Any] = {
            "name": self._display_name if self._display_name is not None else self._name,
            ...
        }
```

- [ ] **Step 7: Persist `display_name` in `get_property_tree()`**

In `src/pydsvdcapi/output_channel.py`, find `get_property_tree()` (around line 798). After the `"name": self._name` entry, add a conditional for `displayName`:

```python
        node: dict[str, Any] = {
            "channelType": int(self._channel_type),
            "dsIndex": self._ds_index,
            "name": self._name,
            ...
        }
        if self._display_name is not None:
            node["displayName"] = self._display_name
        if self._siunit:
            ...
```

- [ ] **Step 8: Restore `display_name` in `_apply_state()`**

In `src/pydsvdcapi/output_channel.py`, find `_apply_state()` (around line 824). After the `if "name" in state:` block, add:

```python
        if "displayName" in state:
            raw = state["displayName"]
            self._display_name = str(raw) if raw is not None else None
```

- [ ] **Step 9: Run tests — all eight must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output_channel.py::TestDisplayName -v
```

Expected: 8 passed.

- [ ] **Step 10: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output_channel.py tests/test_output.py -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add src/pydsvdcapi/output_channel.py tests/test_output_channel.py
git commit -m "feat: add display_name to OutputChannel for free-text channelDescriptions label"
```

---

## Task 4: `channelIndex` backward-compatibility field

Add `"channelIndex"` to `get_description_properties()` with the same value as `"dsIndex"`. This is the field name used by older vdSM versions before `dsIndex` was introduced; both always carry the same integer value.

**Files:**
- Modify: `src/pydsvdcapi/output_channel.py`
- Test: `tests/test_output_channel.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class `TestChannelIndex` in `tests/test_output_channel.py`:

```python
class TestChannelIndex:
    """channelIndex is emitted alongside dsIndex for backward compatibility."""

    def test_channel_index_present_in_description(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        desc = ch.get_description_properties()
        assert "channelIndex" in desc

    def test_channel_index_equals_ds_index_for_primary(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        desc = ch.get_description_properties()
        assert desc["channelIndex"] == desc["dsIndex"] == 0

    def test_channel_index_equals_ds_index_for_secondary(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
            ds_index=1,
        )
        desc = ch.get_description_properties()
        assert desc["channelIndex"] == desc["dsIndex"] == 1

    def test_channel_index_for_custom_channel(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=250,
            ds_index=3,
            name="customSensor",
        )
        desc = ch.get_description_properties()
        assert desc["channelIndex"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output_channel.py::TestChannelIndex -v
```

Expected: 4 failures — `KeyError: 'channelIndex'` or `AssertionError`.

- [ ] **Step 3: Add `channelIndex` to `get_description_properties()`**

In `src/pydsvdcapi/output_channel.py`, find `get_description_properties()` (around line 750). Add `"channelIndex"` alongside `"dsIndex"`:

```python
        props: dict[str, Any] = {
            "name": self._display_name if self._display_name is not None else self._name,
            "channelType": int(self._channel_type),
            "dsIndex": self._ds_index,
            "channelIndex": self._ds_index,
            "min": self._min_value,
            "max": self._max_value,
            "resolution": self._resolution,
        }
```

- [ ] **Step 4: Run tests — all four must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output_channel.py::TestChannelIndex -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full test suite — no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/output_channel.py tests/test_output_channel.py
git commit -m "feat: add channelIndex to channelDescriptions for API v2 backward compatibility"
```

---

## Task 5: Shadow motor timing defaults

When `primaryGroup == 2` (grey/shadow) **and** `function == POSITIONAL`, the five motor timing fields must always be present in the `outputSettings` wire response — using the developer's explicitly set value when available, or a built-in default otherwise.

The combined guard `pg == 2 AND function == POSITIONAL` is intentional:
- `pg == 2` alone would incorrectly emit timing for a grey `ON_OFF` or `BIPOLAR` device (e.g. a simple pulse actuator for a blind) that has no motor travel-time model.
- `function == POSITIONAL` alone would incorrectly emit timing for a positional device in a non-shadow group.
- Motor travel timing is only meaningful when both conditions hold.

Default values (rounded from p44vdc's 54/51/1/1/0):

| Field | Default |
|---|---|
| `openTime` | `50.0` s |
| `closeTime` | `50.0` s |
| `angleOpenTime` | `1.0` s |
| `angleCloseTime` | `1.0` s |
| `stopDelayTime` | `0.0` s |

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing tests**

Add a new test class `TestShadowTimingDefaults` in `tests/test_output.py` (after `TestShadowTimingFields`). Use `_make_stack(primary_group=ColorGroup.GREY)` to create a shadow device.

```python
class TestShadowTimingDefaults:
    """Shadow timing fields are always emitted for shadow devices with p44-compatible defaults."""

    def test_timing_defaults_emitted_when_nothing_set(self):
        host, vdc, device, vdsd = _make_stack(primary_group=ColorGroup.GREY)
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        s = out.get_settings_properties()
        assert s["openTime"] == 50.0
        assert s["closeTime"] == 50.0
        assert s["angleOpenTime"] == 1.0
        assert s["angleCloseTime"] == 1.0
        assert s["stopDelayTime"] == 0.0

    def test_explicit_value_overrides_default(self):
        host, vdc, device, vdsd = _make_stack(primary_group=ColorGroup.GREY)
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL, open_time=30.0)
        s = out.get_settings_properties()
        assert s["openTime"] == 30.0
        assert s["closeTime"] == 50.0   # still default

    def test_all_explicit_values_preserved(self):
        host, vdc, device, vdsd = _make_stack(primary_group=ColorGroup.GREY)
        out = _make_output(
            vdsd,
            function=OutputFunction.POSITIONAL,
            open_time=60.0,
            close_time=55.0,
            angle_open_time=2.0,
            angle_close_time=2.0,
            stop_delay_time=0.5,
        )
        s = out.get_settings_properties()
        assert s["openTime"] == 60.0
        assert s["closeTime"] == 55.0
        assert s["angleOpenTime"] == 2.0
        assert s["angleCloseTime"] == 2.0
        assert s["stopDelayTime"] == 0.5

    def test_timing_absent_for_non_shadow_device(self):
        host, vdc, device, vdsd = _make_stack()  # primaryGroup=YELLOW
        out = _make_output(vdsd)
        s = out.get_settings_properties()
        assert "openTime" not in s
        assert "closeTime" not in s
        assert "angleOpenTime" not in s
        assert "angleCloseTime" not in s
        assert "stopDelayTime" not in s

    def test_timing_absent_for_grey_non_positional_device(self):
        # Grey group but ON_OFF function (e.g. simple pulse actuator) — no motor timing.
        host, vdc, device, vdsd = _make_stack(primary_group=ColorGroup.GREY)
        out = _make_output(vdsd, function=OutputFunction.ON_OFF)
        s = out.get_settings_properties()
        assert "openTime" not in s
        assert "closeTime" not in s
        assert "angleOpenTime" not in s
        assert "angleCloseTime" not in s
        assert "stopDelayTime" not in s
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestShadowTimingDefaults -v
```

Expected: `test_timing_defaults_emitted_when_nothing_set` and `test_explicit_value_overrides_default` fail — timing fields absent from response.

- [ ] **Step 3: Add module-level default constants to `output.py`**

In `src/pydsvdcapi/output.py`, find the `_KNOWN_SETTING_KEYS` block (around line 168). Add these constants immediately before it:

```python
# Default motor timing values for shadow devices (primaryGroup 2).
# Rounded approximations of p44vdc ShadowBehaviour compiled-in defaults.
_SHADOW_DEFAULT_OPEN_TIME: float = 50.0
_SHADOW_DEFAULT_CLOSE_TIME: float = 50.0
_SHADOW_DEFAULT_ANGLE_OPEN_TIME: float = 1.0
_SHADOW_DEFAULT_ANGLE_CLOSE_TIME: float = 1.0
_SHADOW_DEFAULT_STOP_DELAY_TIME: float = 0.0
```

- [ ] **Step 4: Update the shadow timing block in `get_settings_properties()`**

In `src/pydsvdcapi/output.py`, find `get_settings_properties()` (around line 1928). The current shadow timing block is:

```python
        # Shadow motor timing settings (primaryGroup 2 = grey/shadow).
        if pg == 2:
            if self._open_time is not None:
                settings["openTime"] = self._open_time
            if self._close_time is not None:
                settings["closeTime"] = self._close_time
            if self._angle_open_time is not None:
                settings["angleOpenTime"] = self._angle_open_time
            if self._angle_close_time is not None:
                settings["angleCloseTime"] = self._angle_close_time
            if self._stop_delay_time is not None:
                settings["stopDelayTime"] = self._stop_delay_time
```

Replace it with:

```python
        # Shadow motor timing settings: only for grey positional outputs.
        # Always emitted when both conditions hold; falls back to p44-compatible defaults.
        if pg == 2 and int(self._function) == int(OutputFunction.POSITIONAL):
            settings["openTime"] = (
                self._open_time if self._open_time is not None
                else _SHADOW_DEFAULT_OPEN_TIME
            )
            settings["closeTime"] = (
                self._close_time if self._close_time is not None
                else _SHADOW_DEFAULT_CLOSE_TIME
            )
            settings["angleOpenTime"] = (
                self._angle_open_time if self._angle_open_time is not None
                else _SHADOW_DEFAULT_ANGLE_OPEN_TIME
            )
            settings["angleCloseTime"] = (
                self._angle_close_time if self._angle_close_time is not None
                else _SHADOW_DEFAULT_ANGLE_CLOSE_TIME
            )
            settings["stopDelayTime"] = (
                self._stop_delay_time if self._stop_delay_time is not None
                else _SHADOW_DEFAULT_STOP_DELAY_TIME
            )
```

- [ ] **Step 5: Run new tests — all four must pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py::TestShadowTimingDefaults -v
```

Expected: 4 passed.

- [ ] **Step 6: Update the now-misleading existing test**

`TestShadowTimingFields::test_shadow_timing_absent_when_not_set` (around line 3335) tests a YELLOW vdsd (not GREY), so it still passes technically. But its docstring claims "absent when not configured" which is now only true for non-shadow devices. Update the docstring and rename it to make the scope explicit:

```python
    def test_shadow_timing_absent_for_non_shadow_device(self):
        """Shadow timing fields are absent for non-shadow devices (primaryGroup != 2)."""
        host, vdc, device, vdsd = _make_stack()  # primaryGroup=YELLOW
        out = _make_output(vdsd)
        s = out.get_settings_properties()
        assert "openTime" not in s
        assert "closeTime" not in s
        assert "angleOpenTime" not in s
        assert "angleCloseTime" not in s
        assert "stopDelayTime" not in s
```

- [ ] **Step 7: Run full output test suite — no failures**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
pytest tests/test_output.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: always emit shadow motor timing in outputSettings with p44-compatible defaults"
```
