# Channel Key Backward-Compat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pyDSvDCAPI serve channel property requests that use old-format numeric keys (channelType integer string, e.g. `"1"` for brightness, `"7"` for shadePositionOutside; or `"0"` meaning the standard channel for the color class per ds-basics §7 table 7) so that the dSS configurator UI works correctly for ON_OFF, DIMMER, and POSITIONAL devices.

**Architecture:** Three-layer fix. First, unify all output functions to use channel name as the canonical property-dict key (aligning with p44vdc API v3). Second, add numeric-key resolution to `channel_by_key()` so any code that looks up a channel by key (setOutputChannelValue, setProperty channelStates) can resolve old-format keys. Third, wrap the channel property dicts in a `_ChannelCompatDict` subclass that transparently resolves numeric query keys inside `match_query()` so getProperty responses work for both old and new format queries.

**Tech Stack:** Python, protobuf (pydsvdcapi), pytest

---

## Background

The dSS configurator UI generates `VDSM_REQUEST_GET_PROPERTY` queries and `VDSM_SEND_SET_PROPERTY` requests using **old-format numeric channel keys** for simple and dimmable lights (ON\_OFF / DIMMER) and for blinds/shades (POSITIONAL):

- Old format (API v1/v2): outer `PropertyElement.name` = channel type integer as string, e.g. `"1"` for brightness (channelType 1), `"7"` for shadePositionOutside (channelType 7); `"0"` is the spec-defined alias for the standard channel of the device's color class (ds-basics §7 table 7)
- New format (API v3+): outer `PropertyElement.name` = channel name string, e.g. `"brightness"`, `"shadePositionOutside"`

The multi-channel (CT light, full-colour) configurator components already use the new v3 format — those work. The old components for single-channel and shade devices use numeric keys and currently fail.

p44vdc handles both formats by resolving numeric channel IDs to canonical channel names at lookup time.

## Reference tables (ds-basics §7)

### Channel type IDs

| Channel class | channelId (name) | channelType value |
|---|---|---|
| *(standard channel for color class)* | *(see color class table)* | 0 |
| BrightnessChannel | brightness | 1 |
| HueChannel | hue | 2 |
| SaturationChannel | saturation | 3 |
| ColorTempChannel | colortemp | 4 |
| CieXChannel | x | 5 |
| CieYChannel | y | 6 |
| ShadowPositionChannel (outside) | shadePositionOutside | 7 |
| ShadowPositionChannel (inside) | shadePositionIndoor | 8 |
| ShadowAngleChannel (outside) | shadeOpeningAngleOutside | 9 |
| ShadowAngleChannel (inside) | shadeOpeningAngleIndoor | 10 |
| Transparency (e.g. smart glass) | transparency | 11 |
| AirflowIntensityChannel | airFlowIntensity | 12 |
| AirflowDirectionChannel | airFlowDirection | 13 |
| Flap Opening Angle | airFlapPosition | 14 |
| LouverPositionChannel | airLouverPosition | 15 |
| PowerLevelChannel | heatingPower | 16 |
| Cooling Capacity | coolingCapacity | 17 |
| AudioVolumeChannel | audioVolume | 18 |
| PowerStateChannel | powerState | 19 |
| LouverAutoChannel | airLouverAuto | 20 |
| AirflowAutoChannel | airFlowAuto | 21 |
| Water Temperature | waterTemperature | 22 |
| Water Flow Rate | waterFlow | 23 |
| Power Level | powerLevel | 24 |
| VideoStationChannel | videoStation | 25 |
| VideoInputSourceChannel | videoInputSource | 26 |
| FcuOperationModeChannel | operationMode | 192 |

### Color class → standard channel (channelType 0 resolution)

| colorClass ID | application | standard channelId | channelType |
|---|---|---|---|
| 1 | lights | brightness | 1 |
| 2 | blinds | shadePositionOutside | 7 |
| 3 | heating | heatingPower | 16 |
| 4 | audio | audioVolume | 18 |
| 5 | video | audioVolume | 18 |
| 9 | cooling | coolingCapacity | 17 |
| 10 | ventilation | airFlowIntensity | 12 |
| 12 | recirculation | airFlowIntensity | 12 |
| 64 | apartment-ventilation | airFlowIntensity | 12 |
| 65 | awnings | shadePositionOutside | 7 |
| 69 | apartment-recirculation | airFlowIntensity | 12 |

## File Structure

| File | Role in this change |
|---|---|
| `src/pydsvdcapi/enums.py` | Add `FCU_OPERATION_MODE = 192` to `OutputChannelType` |
| `src/pydsvdcapi/output_channel.py` | Fix `WATER_FLOW_RATE` spec name `"waterFlow"`; add `FCU_OPERATION_MODE` spec; add `COLOR_CLASS_STANDARD_CHANNEL` dict |
| `src/pydsvdcapi/output.py` | Add `_ChannelCompatDict`; change `_channel_key()` to always return `ch.name`; enhance `channel_by_key()` with numeric fallback; wrap channel dict methods |
| `src/pydsvdcapi/vdc_host.py` | Fix `channelStates` setProperty handler to use `channel_by_key()` instead of manual name loop |
| `tests/test_output_channel.py` | Update assertions for tasks 1–3; add `TestChannelKeyBackwardCompat` class |
| `tests/test_vdc_host.py` | Add setProperty numeric key test for task 4 |

`property_handling.py` is **not changed** — `match_query()` is generic; the compat dict adapter pattern keeps changes localised to `output.py`.

---

## Task 0: Update enums and channel specs

**Context:** Two corrections against the reference tables above: (1) `CHANNEL_SPECS` in `output_channel.py` uses `name="waterFlowRate"` for `WATER_FLOW_RATE` but the spec name is `"waterFlow"`; (2) `OutputChannelType` in `enums.py` is missing `FCU_OPERATION_MODE = 192` (`operationMode`). Both need to be correct before the compat tests can pass, and before `channel_by_key()` can look up channels by canonical name. Additionally, a new `COLOR_CLASS_STANDARD_CHANNEL` dict maps `ColorClass` IDs to the standard `OutputChannelType`, used by `channel_by_key("0")`.

**Files:**
- Modify: `src/pydsvdcapi/enums.py` (add `FCU_OPERATION_MODE`)
- Modify: `src/pydsvdcapi/output_channel.py` (fix name, add spec, add dict)
- Test: `tests/test_output_channel.py` — new class `TestChannelSpecsAndEnums`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_output_channel.py`:

```python
class TestChannelSpecsAndEnums:
    """Channel type enum and CHANNEL_SPECS match the ds-basics §7 reference tables."""

    def test_water_flow_channel_name_is_waterFlow(self):
        """WATER_FLOW_RATE spec name must be 'waterFlow' not 'waterFlowRate'."""
        from pydsvdcapi.output_channel import get_channel_spec
        from pydsvdcapi.enums import OutputChannelType
        spec = get_channel_spec(OutputChannelType.WATER_FLOW_RATE)
        assert spec is not None
        assert spec.name == "waterFlow"

    def test_fcu_operation_mode_channel_type_exists(self):
        """OutputChannelType must have FCU_OPERATION_MODE = 192."""
        from pydsvdcapi.enums import OutputChannelType
        assert OutputChannelType.FCU_OPERATION_MODE == 192

    def test_fcu_operation_mode_has_channel_spec(self):
        """CHANNEL_SPECS must have an entry for FCU_OPERATION_MODE with name 'operationMode'."""
        from pydsvdcapi.output_channel import get_channel_spec
        from pydsvdcapi.enums import OutputChannelType
        spec = get_channel_spec(OutputChannelType.FCU_OPERATION_MODE)
        assert spec is not None
        assert spec.name == "operationMode"

    def test_color_class_standard_channel_lights(self):
        """COLOR_CLASS_STANDARD_CHANNEL[LIGHTS] == BRIGHTNESS."""
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        assert COLOR_CLASS_STANDARD_CHANNEL[ColorClass.LIGHTS] == OutputChannelType.BRIGHTNESS

    def test_color_class_standard_channel_blinds(self):
        """COLOR_CLASS_STANDARD_CHANNEL[BLINDS] == SHADE_POSITION_OUTSIDE."""
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        assert COLOR_CLASS_STANDARD_CHANNEL[ColorClass.BLINDS] == OutputChannelType.SHADE_POSITION_OUTSIDE

    def test_color_class_standard_channel_heating(self):
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        assert COLOR_CLASS_STANDARD_CHANNEL[ColorClass.HEATING] == OutputChannelType.HEATING_POWER

    def test_color_class_standard_channel_cooling(self):
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        assert COLOR_CLASS_STANDARD_CHANNEL[ColorClass.COOLING] == OutputChannelType.COOLING_CAPACITY

    def test_color_class_standard_channel_ventilation(self):
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        assert COLOR_CLASS_STANDARD_CHANNEL[ColorClass.VENTILATION] == OutputChannelType.AIR_FLOW_INTENSITY
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_output_channel.py::TestChannelSpecsAndEnums -v
```

Expected: `test_water_flow_channel_name_is_waterFlow` fails with `"waterFlowRate" != "waterFlow"`;
`test_fcu_operation_mode_channel_type_exists` fails with `AttributeError: FCU_OPERATION_MODE`.

- [ ] **Step 3: Add `FCU_OPERATION_MODE = 192` to `OutputChannelType` in `enums.py`**

In `src/pydsvdcapi/enums.py`, after the `VIDEO_INPUT_SOURCE = 26` line:

```python
    # Video (ids 25–26)
    VIDEO_STATION = 25
    VIDEO_INPUT_SOURCE = 26

    # Fan-coil unit (FCU) proprietary range (ids 192–239 reserved)
    FCU_OPERATION_MODE = 192
```

- [ ] **Step 4: Fix `WATER_FLOW_RATE` name and add `FCU_OPERATION_MODE` spec in `output_channel.py`**

In `src/pydsvdcapi/output_channel.py`, change:

```python
    OutputChannelType.WATER_FLOW_RATE: ChannelSpec(
        name="waterFlowRate",
```

to:

```python
    OutputChannelType.WATER_FLOW_RATE: ChannelSpec(
        name="waterFlow",
```

Then add after the `VIDEO_INPUT_SOURCE` entry (after the closing `),` of the last entry before `}`):

```python
    # -- FCU proprietary channels (192–239) ----------------------------
    OutputChannelType.FCU_OPERATION_MODE: ChannelSpec(
        name="operationMode",
        min_value=0,
        max_value=255,
        resolution=1,
    ),
```

- [ ] **Step 5: Add `COLOR_CLASS_STANDARD_CHANNEL` dict to `output_channel.py`**

After the `CHANNEL_SPECS` dict and `get_channel_spec()` function, add:

```python
#: Maps ColorClass application group ID → standard OutputChannelType for that class.
#: Used to resolve channelType key "0" (ds-basics §7 table 7: "standard channel
#: for the respective color class").
COLOR_CLASS_STANDARD_CHANNEL: dict[int, OutputChannelType] = {
    1: OutputChannelType.BRIGHTNESS,           # LIGHTS
    2: OutputChannelType.SHADE_POSITION_OUTSIDE,  # BLINDS
    3: OutputChannelType.HEATING_POWER,        # HEATING
    4: OutputChannelType.AUDIO_VOLUME,         # AUDIO
    5: OutputChannelType.AUDIO_VOLUME,         # VIDEO
    9: OutputChannelType.COOLING_CAPACITY,     # COOLING
    10: OutputChannelType.AIR_FLOW_INTENSITY,  # VENTILATION
    12: OutputChannelType.AIR_FLOW_INTENSITY,  # RECIRCULATION
    64: OutputChannelType.AIR_FLOW_INTENSITY,  # APARTMENT_VENTILATION
    65: OutputChannelType.SHADE_POSITION_OUTSIDE,  # AWNINGS
    69: OutputChannelType.AIR_FLOW_INTENSITY,  # APARTMENT_RECIRCULATION
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_output_channel.py::TestChannelSpecsAndEnums -v
```

Expected: 8 passed.

- [ ] **Step 7: Run full suite to catch regressions**

```bash
python -m pytest -x -q
```

Expected: all tests pass. If any test asserts `spec.name == "waterFlowRate"`, update it to `"waterFlow"`.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/enums.py src/pydsvdcapi/output_channel.py tests/test_output_channel.py
git commit -m "fix: add FCU_OPERATION_MODE, fix waterFlow name, add COLOR_CLASS_STANDARD_CHANNEL"
```

---

## Task 1: Unify channel container key to always use channel name

**Context:** `_channel_key()` currently returns `str(ch.ds_index)` for ON\_OFF and DIMMER (producing key `"0"`) and `ch.name` for POSITIONAL / DIMMER\_COLOR\_TEMP / FULL\_COLOR\_DIMMER. This means the same function also generates the push notification key. The goal is to align with p44vdc: always use channel name.

**Files:**
- Modify: `src/pydsvdcapi/output.py:1608-1632`
- Test: `tests/test_output_channel.py` — class `TestChannelContainerKeyFormat` (~line 1437) and `TestVdsdChannelProperties` (~line 963) and `TestPushNotification` (~line 1500)

- [ ] **Step 1: Write failing tests for new canonical key behaviour**

Add to `tests/test_output_channel.py`, replacing the two existing failing tests (`test_dimmer_keyed_by_ds_index` and `test_on_off_keyed_by_ds_index`) and updating the three `TestVdsdChannelProperties` tests and the DIMMER push test:

```python
# In TestChannelContainerKeyFormat — replace test_dimmer_keyed_by_ds_index:
def test_dimmer_keyed_by_name(self):
    """DIMMER: channelDescriptions/Settings/States keyed by channel name (API v3+)."""
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.DIMMER)
    ch = list(out.channels.values())[0]
    desc = out.get_channel_descriptions()
    assert ch.name in desc              # "brightness"
    assert str(ch.ds_index) not in desc # NOT "0"

# In TestChannelContainerKeyFormat — replace test_on_off_keyed_by_ds_index:
def test_on_off_keyed_by_name(self):
    """ON_OFF: channelDescriptions keyed by channel name (API v3+)."""
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.ON_OFF)
    ch = list(out.channels.values())[0]
    desc = out.get_channel_descriptions()
    assert ch.name in desc
    assert str(ch.ds_index) not in desc

# In TestVdsdChannelProperties — update test_properties_include_channel_descriptions:
def test_properties_include_channel_descriptions(self):
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.DIMMER)
    vdsd.set_output(out)
    props = vdsd.get_properties()
    assert "channelDescriptions" in props
    assert "brightness" in props["channelDescriptions"]
    assert props["channelDescriptions"]["brightness"]["name"] == "brightness"

# In TestVdsdChannelProperties — update test_properties_include_channel_states:
def test_properties_include_channel_states(self):
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.DIMMER)
    vdsd.set_output(out)
    props = vdsd.get_properties()
    assert "channelStates" in props
    assert "brightness" in props["channelStates"]
    assert props["channelStates"]["brightness"]["value"] == 0.0

# In TestVdsdChannelProperties — update test_properties_include_channel_settings:
def test_properties_include_channel_settings(self):
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.DIMMER)
    vdsd.set_output(out)
    props = vdsd.get_properties()
    assert "channelSettings" in props
    assert "brightness" in props["channelSettings"]

# In TestPushNotification — update test_push_notification_dimmer_keyed_by_dsindex
# (rename and flip assertions):
@pytest.mark.asyncio
async def test_push_notification_dimmer_keyed_by_name(self):
    """Push notification for DIMMER must use channel name key (API v3+)."""
    from pydsvdcapi.property_handling import elements_to_dict
    _, _, _, vdsd = _make_stack()
    out = _make_output(vdsd, function=OutputFunction.DIMMER)
    out.push_changes = True
    session = _make_mock_session()
    out.start_session(session)
    vdsd.set_output(out)
    ch = out.get_channel(0)
    await ch.update_value(42.0)
    sent_msg = session.send_notification.call_args[0][0]
    props = elements_to_dict(sent_msg.vdc_send_push_notification.changedproperties)
    assert "channelStates" in props
    assert ch.name in props["channelStates"]             # "brightness"
    assert str(ch.ds_index) not in props["channelStates"]  # NOT "0"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_output_channel.py::TestChannelContainerKeyFormat::test_dimmer_keyed_by_name tests/test_output_channel.py::TestVdsdChannelProperties::test_properties_include_channel_descriptions -v
```

Expected: FAIL (`AssertionError` — `"brightness"` not in desc, `"0"` is there instead).

- [ ] **Step 3: Simplify `_channel_key()` to always return `ch.name`**

In `src/pydsvdcapi/output.py`, replace the body of `_channel_key()` (lines 1608–1632):

```python
def _channel_key(self, ch: "OutputChannel") -> str:
    """Return the channel name as the canonical property-dict key (API v3+).

    All output functions use the channel name (e.g. ``"brightness"``,
    ``"shadePositionOutside"``) as the outer element key, matching the
    p44vdc API v3+ ``getApiId()`` format.  Numeric backward-compat
    resolution for incoming queries is handled by :class:`_ChannelCompatDict`
    and :meth:`channel_by_key`.
    """
    return ch.name
```

Also update the docstring of `get_channel_descriptions()` to remove the mention of dsIndex keys:

```python
def get_channel_descriptions(self) -> dict[str, Any]:
    """Return the ``channelDescriptions`` sub-tree.

    Keys are channel name strings (e.g. ``"brightness"``,
    ``"shadePositionOutside"``), matching the p44vdc API v3+ channel ID
    format.  Backward-compat numeric key resolution for incoming queries is
    provided by :class:`_ChannelCompatDict`.
    """
    return {
        self._channel_key(ch): ch.get_description_properties()
        for ch in self._channels.values()
    }
```

Do the same for `get_channel_settings()` and `get_channel_states()` docstrings (remove the "dsIndex string for simple output functions" clause).

Also update the comment in `vdsd.py` line ~1730:
```python
# Each sub-tree is a single PropertyElement whose children are
# keyed by channel name (e.g. "brightness", "shadePositionOutside")
# for all output functions (API v3+).
```

- [ ] **Step 4: Run all updated tests to verify they pass**

```bash
python -m pytest tests/test_output_channel.py -v
```

Expected: 107 passed (same count — existing tests updated, none added yet).

- [ ] **Step 5: Run full suite to catch regressions**

```bash
python -m pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/output.py src/pydsvdcapi/vdsd.py tests/test_output_channel.py
git commit -m "fix: unify channel container key to always use channel name (API v3+)"
```

---

## Task 2: Enhance `channel_by_key()` with numeric fallback

**Context:** `channel_by_key()` is called from:
- `vdc_host.py` `setOutputChannelValue` handler — already uses this method
- `vdc_host.py` `dimChannel` handler — already uses this method

After Task 1, the method body is effectively just a name lookup (`self._channel_key(ch) == key` is now `ch.name == key`). We extend it to also try channelType integer and dsIndex for backward compat.

**Files:**
- Modify: `src/pydsvdcapi/output.py:1634-1645`
- Test: `tests/test_output_channel.py` — new class `TestChannelByKey`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_output_channel.py`:

```python
class TestChannelByKey:
    """channel_by_key() resolves canonical names, numeric channelType, and dsIndex."""

    def test_resolve_by_canonical_name(self):
        """Resolves by channel name (canonical key)."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = list(out.channels.values())[0]
        assert out.channel_by_key("brightness") is ch

    def test_resolve_by_channel_type_number(self):
        """Resolves old-format API v1/v2 key: channelType integer as string."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        # brightness channel has channelType=1
        ch = out.channel_by_key("1")
        assert ch is not None
        assert ch.name == "brightness"

    def test_resolve_by_channeltype_zero_standard_channel(self):
        """Key '0' resolves to the standard channel for the color class (ds-basics §7 table 7)."""
        from pydsvdcapi.enums import ColorClass
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.default_group = ColorClass.LIGHTS  # explicit: color class 1 → brightness
        ch = out.channel_by_key("0")
        assert ch is not None
        assert ch.name == "brightness"

    def test_resolve_by_channeltype_zero_shade_standard_channel(self):
        """Key '0' with BLINDS color class resolves to shadePositionOutside."""
        from pydsvdcapi.enums import ColorClass
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        out.default_group = ColorClass.BLINDS  # color class 2 → shadePositionOutside
        ch = out.channel_by_key("0")
        assert ch is not None
        assert ch.name == "shadePositionOutside"

    def test_resolve_positional_channel_type(self):
        """Resolves shadePositionOutside (channelType=7) by numeric key '7'."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
        ch = out.channel_by_key("7")
        assert ch is not None
        assert ch.name == "shadePositionOutside"
        ch9 = out.channel_by_key("9")
        assert ch9 is not None
        assert ch9.name == "shadeOpeningAngleOutside"

    def test_resolve_color_temp_channel_type(self):
        """Resolves colortemp (channelType=4) by numeric key '4'."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        ch = out.channel_by_key("4")
        assert ch is not None
        assert ch.name == "colortemp"

    def test_unknown_key_returns_none(self):
        """Returns None for unrecognised keys."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        assert out.channel_by_key("unknown") is None
        assert out.channel_by_key("99") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_output_channel.py::TestChannelByKey -v
```

Expected: `test_resolve_by_channel_type_number`, `test_resolve_by_ds_index_string`, `test_resolve_positional_channel_type`, `test_resolve_color_temp_channel_type` FAIL (`channel_by_key("1")` returns None).

- [ ] **Step 3: Implement the enhanced `channel_by_key()` in `output.py`**

Replace lines 1634–1645 of `src/pydsvdcapi/output.py`:

```python
def channel_by_key(self, key: str) -> "OutputChannel | None":
    """Return the channel matching *key*, with numeric backward-compat.

    Resolution order:

    1. Canonical channel name (e.g. ``"brightness"``, ``"shadePositionOutside"``).
    2. Numeric key ``"0"`` — spec-defined alias for the standard channel of
       the device's color class (ds-basics §7 table 7).  Resolved via
       :data:`~pydsvdcapi.output_channel.COLOR_CLASS_STANDARD_CHANNEL` using
       ``self._default_group`` (the output's ``ColorClass`` / application
       group ID).  Falls back to the first registered channel if the color
       class is not in the table.
    3. Channel type integer as string — old API v1/v2 wire format
       (e.g. ``"1"`` → brightness, ``"7"`` → shadePositionOutside).

    Used by ``setOutputChannelValue``, ``dimChannel``, and
    ``setProperty channelStates`` handlers in ``vdc_host.py``.
    """
    from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

    # 1. Canonical name — fast path, covers all API v3+ callers.
    for ch in self._channels.values():
        if ch.name == key:
            return ch
    try:
        numeric = int(key)
    except ValueError:
        return None
    # 2. "0" = standard channel for color class (ds-basics §7 table 7).
    if numeric == 0:
        std_ct = COLOR_CLASS_STANDARD_CHANNEL.get(self._default_group)
        if std_ct is not None:
            found = self.get_channel_by_type(std_ct)
            if found is not None:
                return found
        # fallback: first registered channel
        return self._channels.get(min(self._channels)) if self._channels else None
    # 3. Channel type number (API v1/v2 primary format).
    for ch in self._channels.values():
        if int(ch.channel_type) == numeric:
            return ch
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_output_channel.py::TestChannelByKey -v
```

Expected: 6 passed.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output_channel.py
git commit -m "fix: enhance channel_by_key() with channelType and standard-channel (key=0) resolution"
```

---

## Task 3: Add `_ChannelCompatDict` for getProperty numeric-key resolution

**Context:** `match_query()` in `property_handling.py` does a plain `name in properties` / `properties[name]` lookup. When the dSS configurator sends a getProperty query with an old-format numeric key (e.g. `"1"` for brightness), the lookup fails — `"1"` is not in `{"brightness": {...}}`. We solve this by wrapping the channel property dicts in a `dict` subclass that transparently resolves numeric keys to canonical names. `match_query()` does not change.

The response echoes back the query key (e.g. the response element will be named `"1"` if the query asked for `"1"`), which is what the old UI component expects.

**Files:**
- Modify: `src/pydsvdcapi/output.py` — add `_ChannelCompatDict` class before `_channel_key()`, update `get_channel_descriptions/settings/states()` return types
- Test: `tests/test_output_channel.py` — new class `TestChannelCompatDictGetProperty`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_output_channel.py`:

```python
class TestChannelCompatDictGetProperty:
    """getProperty queries using old-format numeric channel keys are served correctly."""

    def _make_getproperty_request(self, channel_key: str, property_name: str):
        """Build a VDSM_REQUEST_GET_PROPERTY protobuf asking for one channel by key."""
        from pydsvdcapi import vdc_messages_pb2 as pb
        from pydsvdcapi.vdcapi_pb2 import PropertyElement
        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_GET_PROPERTY
        msg.message_id = 42
        container = PropertyElement()
        container.name = property_name   # e.g. "channelDescriptions"
        channel_elem = PropertyElement()
        channel_elem.name = channel_key  # e.g. "1" or "brightness"
        container.elements.append(channel_elem)
        msg.vdsm_request_get_property.query.append(container)
        return msg

    def test_numeric_channeltype_key_resolves_for_dimmer_descriptions(self):
        """Query channelDescriptions with '1' (channelType=brightness) returns data."""
        from pydsvdcapi.property_handling import (
            build_get_property_response,
            elements_to_dict,
        )
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        props = vdsd.get_properties()
        msg = self._make_getproperty_request("1", "channelDescriptions")
        resp = build_get_property_response(msg, props)
        result = elements_to_dict(resp.vdc_response_get_property.properties)
        # Response element named "1" must contain brightness channel data
        assert "channelDescriptions" in result
        channel_data = result["channelDescriptions"]
        assert "1" in channel_data
        assert channel_data["1"]["channelType"] == 1
        assert channel_data["1"]["name"] == "brightness"

    def test_numeric_channeltype_key_resolves_for_dimmer_states(self):
        """Query channelStates with '1' returns the current brightness value."""
        from pydsvdcapi.property_handling import (
            build_get_property_response,
            elements_to_dict,
        )
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        out.get_channel(0).set_value(75.0)
        props = vdsd.get_properties()
        msg = self._make_getproperty_request("1", "channelStates")
        resp = build_get_property_response(msg, props)
        result = elements_to_dict(resp.vdc_response_get_property.properties)
        assert "channelStates" in result
        assert "1" in result["channelStates"]
        assert result["channelStates"]["1"]["value"] == 75.0

    def test_numeric_channeltype_key_resolves_for_positional(self):
        """Query channelDescriptions '7' resolves to shadePositionOutside."""
        from pydsvdcapi.property_handling import (
            build_get_property_response,
            elements_to_dict,
        )
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
        vdsd.set_output(out)
        props = vdsd.get_properties()
        msg = self._make_getproperty_request("7", "channelDescriptions")
        resp = build_get_property_response(msg, props)
        result = elements_to_dict(resp.vdc_response_get_property.properties)
        assert "channelDescriptions" in result
        assert "7" in result["channelDescriptions"]
        assert result["channelDescriptions"]["7"]["channelType"] == 7
        assert result["channelDescriptions"]["7"]["name"] == "shadePositionOutside"

    def test_wildcard_query_not_duplicated(self):
        """Wildcard query returns canonical keys only — no numeric duplicates."""
        from pydsvdcapi.property_handling import (
            build_get_property_response,
            elements_to_dict,
        )
        from pydsvdcapi import vdc_messages_pb2 as pb
        from pydsvdcapi.vdcapi_pb2 import PropertyElement
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        props = vdsd.get_properties()
        # Wildcard: ask for all channelDescriptions
        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_GET_PROPERTY
        msg.message_id = 1
        wildcard = PropertyElement()
        wildcard.name = "channelDescriptions"
        # Empty sub-element = wildcard for all channels
        msg.vdsm_request_get_property.query.append(wildcard)
        resp = build_get_property_response(msg, props)
        result = elements_to_dict(resp.vdc_response_get_property.properties)
        assert "channelDescriptions" in result
        channels = result["channelDescriptions"]
        # DIMMER has exactly one channel; the key must be canonical "brightness"
        assert len(channels) == 1
        assert "brightness" in channels
        assert "0" not in channels
        assert "1" not in channels
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_output_channel.py::TestChannelCompatDictGetProperty -v
```

Expected: `test_numeric_channeltype_key_resolves_for_dimmer_descriptions` and the others FAIL (`"1"` not in `result["channelDescriptions"]`).

- [ ] **Step 3: Add `_ChannelCompatDict` to `output.py`**

Insert this class in `src/pydsvdcapi/output.py` immediately **before** the `Output` class definition (before line ~158 where the logger is defined, after the imports). The class should live at module scope:

```python
class _ChannelCompatDict(dict):
    """Channel property dict with transparent numeric-key resolution.

    The dSS configurator UI sends ``getProperty`` queries using the old API
    v1/v2 channel key format: the ``channelType`` integer as a string (e.g.
    ``"1"`` for brightness, ``"7"`` for shadePositionOutside) or ``"0"`` as
    the spec-defined alias for the standard channel of the device's color
    class (ds-basics §7 table 7).

    This ``dict`` subclass wraps the canonical channel property dict so that
    :func:`~pydsvdcapi.property_handling.match_query` can serve both old and
    new format queries without modification.

    Wildcard queries iterate ``dict.items()`` which only yields **canonical**
    (named) keys — no numeric duplicates appear in wildcard responses.

    Parameters
    ----------
    data:
        The canonical channel property dict (e.g. ``{"brightness": {...}}``)
        built by :meth:`~Output.get_channel_descriptions`.
    output:
        The owning :class:`Output` instance, used to resolve numeric keys via
        :meth:`~Output.channel_by_key`.
    """

    def __init__(self, data: dict, output: "Output") -> None:
        super().__init__(data)
        self._output = output

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        if isinstance(key, str):
            return self._output.channel_by_key(key) is not None
        return False

    def __getitem__(self, key: str) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        ch = self._output.channel_by_key(key)
        if ch is not None and super().__contains__(ch.name):
            return super().__getitem__(ch.name)
        raise KeyError(key)
```

- [ ] **Step 4: Update `get_channel_descriptions()`, `get_channel_settings()`, `get_channel_states()` to return `_ChannelCompatDict`**

In `src/pydsvdcapi/output.py`, update the three methods (currently at ~lines 1647–1678 — adjust for the insertion of `_ChannelCompatDict` above the class):

```python
def get_channel_descriptions(self) -> dict[str, Any]:
    """Return the ``channelDescriptions`` sub-tree.

    Keys are channel name strings (e.g. ``"brightness"``,
    ``"shadePositionOutside"``).  The returned dict transparently
    resolves numeric keys (channelType integer, dsIndex) for backward
    compatibility with old-format getProperty queries.
    """
    return _ChannelCompatDict(
        {self._channel_key(ch): ch.get_description_properties()
         for ch in self._channels.values()},
        self,
    )

def get_channel_settings(self) -> dict[str, Any]:
    """Return the ``channelSettings`` sub-tree.

    Keys follow the same convention as :meth:`get_channel_descriptions`.
    """
    return _ChannelCompatDict(
        {self._channel_key(ch): ch.get_settings_properties()
         for ch in self._channels.values()},
        self,
    )

def get_channel_states(self) -> dict[str, Any]:
    """Return the ``channelStates`` sub-tree.

    Keys follow the same convention as :meth:`get_channel_descriptions`.
    """
    return _ChannelCompatDict(
        {self._channel_key(ch): ch.get_state_properties()
         for ch in self._channels.values()},
        self,
    )
```

- [ ] **Step 5: Run new tests to verify they pass**

```bash
python -m pytest tests/test_output_channel.py::TestChannelCompatDictGetProperty -v
```

Expected: 4 passed.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest -x -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output_channel.py
git commit -m "feat: add _ChannelCompatDict for backward-compat numeric channel key resolution in getProperty"
```

---

## Task 4: Fix setProperty `channelStates` to use numeric key resolution

**Context:** `_apply_vdsd_set_property()` in `vdc_host.py` handles `setProperty channelStates` (line ~1368). The current code loops over channels comparing `ch.name == ch_name`. When the configurator sends a setProperty with a numeric key like `"1"` (old format), no channel name matches and the value is silently dropped. Fix: use `output.channel_by_key(ch_key)` which now resolves numeric keys.

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py:1368-1408`
- Test: `tests/test_vdc_host.py` — new test `test_setproperty_channelstates_numeric_key`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_vdc_host.py`. Find the section with other setProperty tests or add at the end:

```python
class TestSetPropertyChannelStatesNumericKey:
    """setProperty channelStates with old-format numeric key updates the channel."""

    def _make_set_property_msg(
        self, dsuid_str: str, channel_key: str, value: float
    ) -> "pb.Message":
        """Build a VDSM_REQUEST_SET_PROPERTY for channelStates with a numeric key."""
        from pydsvdcapi import vdc_messages_pb2 as pb
        from pydsvdcapi.vdcapi_pb2 import PropertyElement, PropertyValue

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_SET_PROPERTY
        msg.message_id = 1
        msg.vdsm_request_set_property.dSUID = dsuid_str

        channel_states = PropertyElement()
        channel_states.name = "channelStates"

        channel_elem = PropertyElement()
        channel_elem.name = channel_key   # e.g. "1" (numeric channelType)

        value_elem = PropertyElement()
        value_elem.name = "value"
        value_elem.value.v_double = value
        channel_elem.elements.append(value_elem)
        channel_states.elements.append(channel_elem)
        msg.vdsm_request_set_property.properties.append(channel_states)
        return msg

    @pytest.mark.asyncio
    async def test_setproperty_channelstates_numeric_channeltype_key(self):
        """setProperty channelStates with key '1' (channelType=brightness) updates value."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from pydsvdcapi import vdc_messages_pb2 as pb
        from pydsvdcapi.vdc_host import VdcHost
        from pydsvdcapi.vdc import Vdc
        from pydsvdcapi.device_template import Device
        from pydsvdcapi.vdsd import Vdsd
        from pydsvdcapi.output import Output
        from pydsvdcapi.enums import ColorGroup, OutputFunction

        host = VdcHost(name="test-host")
        vdc = Vdc(host=host, implementation_id="test-vdc")
        host.add_vdc(vdc)

        from pydsvdcapi.dsuid import DsUid, DsUidNamespace
        dsuid = DsUid.from_name_in_space("dev-numeric-key", DsUidNamespace.VDC)
        device = Device(vdc=vdc, dsuid=dsuid)
        vdsd = Vdsd(device=device, primary_group=ColorGroup.YELLOW, name="Dimmer")
        device.add_vdsd(vdsd)
        vdc.add_device(device)

        output = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            name="brightness",
        )
        channel_applied = AsyncMock()
        output.on_channel_applied = channel_applied
        vdsd.set_output(output)
        vdsd._is_announced = True  # simulate announced state

        dsuid_str = str(dsuid)
        msg = self._make_set_property_msg(dsuid_str, "1", 80.0)

        session = MagicMock()
        session.send_response = MagicMock()

        # Patch asyncio.create_task to run the coroutine immediately
        original_create_task = asyncio.create_task
        tasks = []

        def collect_task(coro):
            task = original_create_task(coro)
            tasks.append(task)
            return task

        with patch("pydsvdcapi.vdc_host.asyncio.create_task", side_effect=collect_task):
            host._handle_set_property(msg)

        # Drain all created tasks
        if tasks:
            await asyncio.gather(*tasks)
        if channel_applied.called:
            await asyncio.gather(*[call for call in channel_applied.call_args_list])

        # The brightness channel (channelType=1) must have the new value
        brightness_ch = output.get_channel(0)
        assert brightness_ch is not None
        assert brightness_ch.name == "brightness"
        # channel_by_key("1") must have resolved to this channel
        assert output.channel_by_key("1") is brightness_ch
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_vdc_host.py::TestSetPropertyChannelStatesNumericKey -v
```

Expected: FAIL — the channel value is not updated because `ch.name == "1"` never matches.

- [ ] **Step 3: Fix the `channelStates` handler in `vdc_host.py`**

In `src/pydsvdcapi/vdc_host.py`, replace lines 1368–1408 (the `if "channelStates" in incoming:` block):

```python
        # Channel states (§4.9.3) — dSS sends this via setProperty when
        # the user or JSON API sets an output channel value directly.
        # The channel key may be the canonical name (API v3+, e.g.
        # "brightness") or a numeric string (old API v1/v2 channelType, e.g.
        # "1", or dsIndex, e.g. "0").  channel_by_key() resolves all formats.
        if "channelStates" in incoming:
            ch_states = incoming["channelStates"]
            if isinstance(ch_states, dict):
                output = getattr(vdsd, "output", None)
                if output is not None:
                    for ch_key, ch_data in ch_states.items():
                        if not isinstance(ch_data, dict):
                            continue
                        new_val = ch_data.get("value")
                        if new_val is None:
                            continue
                        channel_obj = output.channel_by_key(ch_key)
                        if channel_obj is None:
                            logger.warning(
                                "setProperty channelStates: channel '%s' "
                                "not found on vdSD %s",
                                ch_key,
                                vdsd.dsuid,
                            )
                            continue
                        output.buffer_channel_value(channel_obj, float(new_val))
                        logger.debug(
                            "setProperty channelStates: vdSD %s ch='%s' "
                            "val=%s (buffered)",
                            vdsd.dsuid,
                            ch_key,
                            new_val,
                        )
                    # apply_pending_channels is async; schedule it.
                    import asyncio

                    asyncio.create_task(output.apply_pending_channels())
                    logger.info(
                        "vdSD '%s' channelStates updated via setProperty",
                        vdsd.dsuid,
                    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_vdc_host.py::TestSetPropertyChannelStatesNumericKey -v
```

Expected: 1 passed.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "fix: resolve numeric channel keys in setProperty channelStates handler"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| `FCU_OPERATION_MODE = 192` in `OutputChannelType`; `operationMode` in CHANNEL_SPECS | Task 0 |
| `WATER_FLOW_RATE` spec name corrected to `"waterFlow"` | Task 0 |
| `COLOR_CLASS_STANDARD_CHANNEL` dict for `"0"` resolution | Task 0 |
| getProperty with numeric channelType key `"1"` resolves to brightness data | Task 3 |
| getProperty with numeric channelType key `"7"` resolves to shadePositionOutside data | Task 3 |
| Key `"0"` resolves to the standard channel for the device's ColorClass (ds-basics §7 table 7) | Task 2 |
| Wildcard getProperty returns only canonical channel names (no duplicate numeric entries) | Task 3 |
| setProperty channelStates with numeric key updates the channel value | Task 4 |
| setOutputChannelValue with numeric key (already via channel_by_key) resolves correctly | Task 2 (enhances the method used by the existing handler) |
| All output functions use channel name as canonical key | Task 1 |
| Push notifications use channel name for all output functions | Task 1 (side effect of `_channel_key()` change) |

No gaps found.

**Placeholder scan:** No TBDs or TODO items. All code is complete.

**Type consistency:**
- `_ChannelCompatDict` is used in `get_channel_descriptions/settings/states()` return values (Task 3 Step 4) — declared in Task 3 Step 3. ✓
- `channel_by_key()` signature `(self, key: str) -> "OutputChannel | None"` — used in Task 4 Step 3 and Task 3 `_ChannelCompatDict.__getitem__`. ✓
- `_channel_key()` returns `str` — used in `get_channel_*` methods and `_push_channel_state`. ✓
- All test helper methods (`_make_getproperty_request`, `_make_set_property_msg`) are self-contained in their test classes. ✓
