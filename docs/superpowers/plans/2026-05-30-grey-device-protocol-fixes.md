# Grey Device Protocol Compatibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five wire-format discrepancies between pydsvdcapi and p44vdc that cause errors on grey (shade/blind) devices, add shadow-specific `outputSettings` timing fields, and ensure unknown `setProperty` keys are stored and returned instead of silently dropped.

**Architecture:** All changes are additive or corrective field changes in `output_channel.py`, `output.py`, and `vdc_host.py`. No new classes or files needed. Each task is self-contained and can be tested independently.

**Tech Stack:** Python 3.10+, pytest, protobuf (vdcapi), pydsvdcapi internal library.

**Branch:** `fix-grey-device-protocol-0.8.8`

**Reference:** Analysis document at `docs/p44vdc-comparison.md` (git-ignored, local only).

---

## Change Notes for This Branch

### What is being fixed and why

**CRITICAL-1 — `siunit` and `symbol` missing from `channelDescriptions`**
p44vdc sends `siunit` (e.g. `"percent"`) and `symbol` (e.g. `"%"`) in every channel description element. pydsvdcapi omits both. The dSS firmware uses `siunit` for channel value validation and unit display. Their absence is identified as the most likely root cause of grey-device errors.

**CRITICAL-2 — Shade channel resolution 250× too coarse**
p44vdc uses `100/65536 ≈ 0.001526` (16-bit precision) for shade position and angle channels. pydsvdcapi uses `100/255 ≈ 0.392` (8-bit). This was identified in the p44vdc analysis and matches the reference implementation.

**CRITICAL-3 — Channel container keys use channel name instead of dsIndex**
p44vdc keys all channel containers (`channelDescriptions`, `channelSettings`, `channelStates` in both GET responses and push notifications) by integer dsIndex as string (e.g. `"0"`). pydsvdcapi 0.8.6 switched to channel name keys everywhere. This change reverts the key format back to dsIndex for all four locations — GET responses and push notifications — to match p44vdc exactly. The `setOutputChannelValue` and `setProperty channelStates` handlers in `vdc_host.py` (which look up channels by name from the notification payload) are unchanged.

**WARN-4 — Shadow-specific `outputSettings` fields missing**
p44vdc's `ShadowBehaviour` adds `openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` (all double, seconds) to `outputSettings` for grey devices. dSS reads and writes these to configure motor timing. pydsvdcapi silently ignores them.

**WARN-5 — `transitionTime` missing from `outputState`**
p44vdc includes `transitionTime` (double, seconds) in `outputState`. dSS may use this to track whether a transition is in progress. pydsvdcapi omits it.

**NEW — Unknown `setProperty` keys stored instead of silently dropped**
Currently `Output.apply_settings()` says "Unknown keys are silently ignored." If dSS writes a setting the library doesn't recognise, it disappears. After this change, any unrecognised key is stored in `Output._extra_settings` and returned in future `get_settings_properties()` responses.

---

## File Map

| File | Changes |
|---|---|
| `src/pydsvdcapi/output_channel.py` | Add `siunit`/`symbol` to `ChannelSpec`; populate all channel specs; expose in `get_description_properties()`; fix shade resolutions |
| `src/pydsvdcapi/output.py` | All channel container keys → dsIndex (GET responses + push); add shadow timing fields; add `transitionTime`; add `_extra_settings` |
| `tests/test_output_channel.py` | Assert `siunit`/`symbol` present; assert correct shade resolution |
| `tests/test_output.py` | Assert push uses dsIndex key; assert shadow fields round-trip; assert `transitionTime` present; assert extra settings persist |

---

## Task 1: Add `siunit` and `symbol` to `ChannelSpec` and all channel specs

**Files:**
- Modify: `src/pydsvdcapi/output_channel.py`
- Test: `tests/test_output_channel.py`

- [ ] **Step 1: Write the failing tests**

```python
# In TestChannelSpec / TestOutputChannel (test_output_channel.py)

def test_channel_description_includes_siunit_and_symbol():
    ch = OutputChannel(channel_type=OutputChannelType.BRIGHTNESS, ds_index=0, output=...)
    desc = ch.get_description_properties()
    assert "siunit" in desc
    assert "symbol" in desc
    assert desc["siunit"] == "percent"
    assert desc["symbol"] == "%"

def test_shade_channel_description_includes_siunit_percent():
    ch = OutputChannel(
        channel_type=OutputChannelType.SHADE_POSITION_OUTSIDE, ds_index=0, output=...
    )
    desc = ch.get_description_properties()
    assert desc["siunit"] == "percent"
    assert desc["symbol"] == "%"

def test_colortemp_channel_siunit():
    ch = OutputChannel(
        channel_type=OutputChannelType.COLOR_TEMPERATURE, ds_index=1, output=...
    )
    desc = ch.get_description_properties()
    assert desc["siunit"] == "reciprocal megakelvin"
    assert desc["symbol"] == "mired"

def test_hue_channel_siunit():
    ch = OutputChannel(
        channel_type=OutputChannelType.HUE, ds_index=1, output=...
    )
    desc = ch.get_description_properties()
    assert desc["siunit"] == "degree"
    assert desc["symbol"] == "°"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output_channel.py -k "siunit or symbol" -v
```
Expected: FAIL — `KeyError: 'siunit'`

- [ ] **Step 3: Add `siunit` and `symbol` to `ChannelSpec` dataclass**

In `output_channel.py`, extend the `ChannelSpec` dataclass:

```python
@dataclass(frozen=True)
class ChannelSpec:
    name: str
    min_value: float
    max_value: float
    resolution: float
    siunit: str = ""
    symbol: str = ""
```

- [ ] **Step 4: Populate `siunit`/`symbol` in `CHANNEL_SPECS`**

Update every entry in `CHANNEL_SPECS`. Full values (derived from p44vdc channel constructors):

```python
CHANNEL_SPECS: dict[OutputChannelType, ChannelSpec] = {
    OutputChannelType.BRIGHTNESS: ChannelSpec(
        name="brightness", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.HUE: ChannelSpec(
        name="hue", min_value=0, max_value=360, resolution=360/255,
        siunit="degree", symbol="°",
    ),
    OutputChannelType.SATURATION: ChannelSpec(
        name="saturation", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.COLOR_TEMPERATURE: ChannelSpec(
        name="colortemp", min_value=100, max_value=1000, resolution=900/255,
        siunit="reciprocal megakelvin", symbol="mired",
    ),
    OutputChannelType.CIE_X: ChannelSpec(
        name="x", min_value=0, max_value=10000, resolution=10000/255,
        siunit="", symbol="",
    ),
    OutputChannelType.CIE_Y: ChannelSpec(
        name="y", min_value=0, max_value=10000, resolution=10000/255,
        siunit="", symbol="",
    ),
    # -- Shade channels (resolution matches p44vdc 16-bit precision) ------
    OutputChannelType.SHADE_POSITION_OUTSIDE: ChannelSpec(
        name="shadePositionOutside", min_value=0, max_value=100, resolution=100/65536,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.SHADE_POSITION_INDOOR: ChannelSpec(
        name="shadePositionIndoor", min_value=0, max_value=100, resolution=100/65536,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE: ChannelSpec(
        name="shadeOpeningAngleOutside", min_value=0, max_value=100, resolution=100/65536,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.SHADE_OPENING_ANGLE_INDOOR: ChannelSpec(
        name="shadeOpeningAngleIndoor", min_value=0, max_value=100, resolution=100/65536,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.TRANSPARENCY: ChannelSpec(
        name="transparency", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    # -- Climate channels -------------------------------------------------
    OutputChannelType.HEATING_POWER: ChannelSpec(
        name="heatingPower", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.COOLING_CAPACITY: ChannelSpec(
        name="coolingCapacity", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    # -- Ventilation channels ---------------------------------------------
    OutputChannelType.AIR_FLOW_INTENSITY: ChannelSpec(
        name="airFlowIntensity", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.AIR_FLOW_DIRECTION: ChannelSpec(
        name="airFlowDirection", min_value=0, max_value=2, resolution=1,
        siunit="", symbol="",
    ),
    OutputChannelType.AIR_LOUVER_POSITION: ChannelSpec(
        name="airLouverPosition", min_value=0, max_value=100, resolution=100/255,
        siunit="percent", symbol="%",
    ),
    OutputChannelType.AIR_LOUVER_AUTO: ChannelSpec(
        name="airLouverAuto", min_value=0, max_value=1, resolution=1,
        siunit="", symbol="",
    ),
    OutputChannelType.AIR_FLOW_AUTO: ChannelSpec(
        name="airFlowAuto", min_value=0, max_value=1, resolution=1,
        siunit="", symbol="",
    ),
    OutputChannelType.AIR_TEMP_SETPOINT: ChannelSpec(
        name="airTemperatureSetpoint", min_value=0, max_value=45, resolution=0.01,
        siunit="celsius", symbol="°C",
    ),
}
```

Note: check the existing `CHANNEL_SPECS` in `output_channel.py` for the full list of channel types and preserve any entries not listed here. This step also simultaneously implements Task 2 (shade resolution fix) — shade channels get `resolution=100/65536`.

- [ ] **Step 5: Add `siunit`/`symbol` to `get_description_properties()`**

In `OutputChannel.get_description_properties()`, add the two fields:

```python
def get_description_properties(self) -> dict[str, Any]:
    spec = get_channel_spec(self._channel_type)
    props = {
        "name": spec.name,
        "channelType": int(self._channel_type),
        "dsIndex": self._ds_index,
        "min": spec.min_value,
        "max": spec.max_value,
        "resolution": spec.resolution,
    }
    if spec.siunit:
        props["siunit"] = spec.siunit
    if spec.symbol:
        props["symbol"] = spec.symbol
    return props
```

Only include the fields when non-empty so unknown/unspecified channels don't send empty strings.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_output_channel.py -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/output_channel.py tests/test_output_channel.py
git commit -m "feat: add siunit/symbol to channelDescriptions; fix shade channel resolution to 16-bit"
```

---

## Task 2: Fix shade channel resolution (already done in Task 1)

This is folded into Task 1 Step 4 above — the shade channel `CHANNEL_SPECS` entries already use `resolution=100/65536`. No separate task needed.

---

## Task 3: Channel container keys — dsIndex everywhere (GET responses + push)

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Modify: `src/pydsvdcapi/output_channel.py` (module docstring only)
- Test: `tests/test_output_channel.py`
- Test: `tests/test_output.py`

**Scope:** All four locations that emit channel container keys now use `str(channel.ds_index)` (e.g. `"0"`, `"1"`), matching p44vdc exactly:

1. `get_channel_descriptions()` — property GET response
2. `get_channel_settings()` — property GET response
3. `get_channel_states()` — property GET response
4. `_push_channel_state()` — push notification

**NOT changed:**
- The `setOutputChannelValue` handler in `vdc_host.py` — it already resolves channels by `ch.name == notif.channelId` (name string), which is correct for API v3+ and independent of the property key format.
- The `setProperty channelStates` handler in `vdc_host.py` — it also looks up by channel name (dSS sends name strings there too).

The `deviceOutputIndex:255` errors that 0.8.6 addressed are now understood to have been caused by missing `siunit` (CRITICAL-1) and coarse resolution (CRITICAL-2), not by the key format. Aligning with p44vdc wire format here is the correct fix.

- [ ] **Step 1: Write failing tests**

In `tests/test_output_channel.py`:

```python
def test_channel_descriptions_keyed_by_dsindex(output_with_dimmer):
    """channelDescriptions must be keyed by dsIndex string, not channel name."""
    out = output_with_dimmer
    desc = out.get_channel_descriptions()
    ch = list(out.channels.values())[0]
    assert str(ch.ds_index) in desc          # e.g. "0"
    assert ch.name not in desc               # "brightness" must NOT be a key

def test_channel_states_keyed_by_dsindex(output_with_dimmer):
    out = output_with_dimmer
    states = out.get_channel_states()
    ch = list(out.channels.values())[0]
    assert str(ch.ds_index) in states
    assert ch.name not in states
```

In `tests/test_output.py`:

```python
async def test_push_channel_state_uses_dsindex_key(output_with_session):
    """Push notification must key channelStates by dsIndex string."""
    out, mock_session = output_with_session
    ch = list(out.channels.values())[0]
    ch.update_value(50.0)
    await asyncio.sleep(0)

    msg = mock_session.send_notification.call_args[0][0]
    pushed = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
    channel_states = pushed.get("channelStates", {})
    assert str(ch.ds_index) in channel_states
    assert ch.name not in channel_states
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output_channel.py tests/test_output.py -k "dsindex" -v
```
Expected: FAIL — keys are channel name strings.

- [ ] **Step 3: Update `get_channel_descriptions()`, `get_channel_settings()`, `get_channel_states()`**

In `output.py`, change the three GET-response methods to key by dsIndex:

```python
def get_channel_descriptions(self) -> dict[str, Any]:
    """Return ``channelDescriptions`` sub-tree keyed by dsIndex string.

    Each key is the channel's numeric index as a string (e.g. ``"0"``,
    ``"1"``), matching the p44vdc wire format.  The channel name is
    carried inside each element as the ``name`` field.
    """
    return {
        str(ch.ds_index): ch.get_description_properties()
        for ch in self._channels.values()
    }

def get_channel_settings(self) -> dict[str, Any]:
    """Return ``channelSettings`` sub-tree keyed by dsIndex string."""
    return {
        str(ch.ds_index): ch.get_settings_properties()
        for ch in self._channels.values()
    }

def get_channel_states(self) -> dict[str, Any]:
    """Return ``channelStates`` sub-tree keyed by dsIndex string."""
    return {
        str(ch.ds_index): ch.get_state_properties()
        for ch in self._channels.values()
    }
```

- [ ] **Step 4: Update `_push_channel_state()`**

```python
async def _push_channel_state(self, channel: OutputChannel) -> None:
    """Push a single channel's state to the vdSM.

    Sends a ``VDC_SEND_PUSH_NOTIFICATION`` with a ``channelStates``
    payload keyed by the channel's **dsIndex** as a string (e.g.
    ``{"channelStates": {"0": {"value": 75.0, …}}}``), matching
    p44vdc wire format.
    """
    ...
    state_dict = channel.get_state_properties()
    push_tree: dict[str, Any] = {
        "channelStates": {
            str(channel.ds_index): state_dict,
        }
    }
    ...
```

- [ ] **Step 5: Update module docstring in `output_channel.py`**

The `.. important::` block currently says "dSS identifies channels by their name" and "use the channel name as the element key." Replace with:

```
.. important::

   All three property sub-trees (``channelDescriptions``,
   ``channelSettings``, ``channelStates``) and push notifications use
   the channel's **dsIndex** as the element key (e.g. ``"0"``, ``"1"``),
   matching the p44vdc wire format.  The channel name is carried as the
   ``name`` field *inside* each element.

   The ``setOutputChannelValue`` notification from dSS carries the
   channel name in the ``channelId`` field (API v3+), which is resolved
   by name-matching in :class:`~pydsvdcapi.vdc_host.VdcHost` — this
   is independent of the property key format.
```

- [ ] **Step 6: Update existing tests that assert name-based keys**

In `tests/test_output_channel.py`, update all assertions that previously checked for name-based keys (e.g. `assert "brightness" in desc`) to use dsIndex strings (e.g. `assert "0" in desc`). These were changed to name-based in 0.8.6 — revert them to dsIndex.

- [ ] **Step 7: Run full output tests**

```bash
pytest tests/test_output_channel.py tests/test_output.py -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/output.py src/pydsvdcapi/output_channel.py \
        tests/test_output_channel.py tests/test_output.py
git commit -m "fix: channel container keys use dsIndex (aligns with p44vdc wire format)"
```

---

## Task 4: Shadow-specific `outputSettings` fields

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

The five fields `openTime`, `closeTime`, `angleOpenTime`, `angleCloseTime`, `stopDelayTime` (all `float | None`) represent motor travel timing for shade devices. dSS reads and writes them. They must appear in `outputSettings` responses and be storable via `apply_settings()`.

- [ ] **Step 1: Write failing tests**

```python
def test_shadow_timing_fields_in_settings():
    """Shadow timing fields appear in outputSettings when set."""
    out = Output(vdsd=..., function=OutputFunction.POSITIONAL,
                 output_usage=OutputUsage.UNDEFINED, name="output",
                 default_group=16, active_group=16, groups={16},
                 open_time=60.0, close_time=55.0,
                 angle_open_time=1.5, angle_close_time=1.5,
                 stop_delay_time=0.5)
    s = out.get_settings_properties()
    assert s["openTime"] == 60.0
    assert s["closeTime"] == 55.0
    assert s["angleOpenTime"] == 1.5
    assert s["angleCloseTime"] == 1.5
    assert s["stopDelayTime"] == 0.5

def test_shadow_timing_absent_when_not_set():
    """Shadow timing fields are absent when not configured."""
    out = Output(vdsd=..., function=OutputFunction.POSITIONAL, ...)
    s = out.get_settings_properties()
    assert "openTime" not in s

def test_apply_settings_stores_shadow_timing():
    out = Output(...)
    out.apply_settings({"openTime": 45.0, "closeTime": 40.0})
    s = out.get_settings_properties()
    assert s["openTime"] == 45.0
    assert s["closeTime"] == 40.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output.py -k "shadow_timing" -v
```
Expected: FAIL — `TypeError` on unknown constructor arg, `KeyError` on settings.

- [ ] **Step 3: Add shadow timing fields to `Output.__init__`**

After the existing optional params, add:

```python
# Shadow motor timing (shade devices only, optional)
open_time: float | None = None,
close_time: float | None = None,
angle_open_time: float | None = None,
angle_close_time: float | None = None,
stop_delay_time: float | None = None,
```

Store them:

```python
self._open_time: float | None = open_time
self._close_time: float | None = close_time
self._angle_open_time: float | None = angle_open_time
self._angle_close_time: float | None = angle_close_time
self._stop_delay_time: float | None = stop_delay_time
```

- [ ] **Step 4: Expose in `get_settings_properties()`**

Add after the existing optional settings block:

```python
# Shadow motor timing (grey/shade devices — ShadowBehaviour fields).
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

- [ ] **Step 5: Handle in `apply_settings()`**

Add to the existing `apply_settings()` method:

```python
if "openTime" in settings:
    val = settings["openTime"]
    self._open_time = float(val) if val is not None else None
if "closeTime" in settings:
    val = settings["closeTime"]
    self._close_time = float(val) if val is not None else None
if "angleOpenTime" in settings:
    val = settings["angleOpenTime"]
    self._angle_open_time = float(val) if val is not None else None
if "angleCloseTime" in settings:
    val = settings["angleCloseTime"]
    self._angle_close_time = float(val) if val is not None else None
if "stopDelayTime" in settings:
    val = settings["stopDelayTime"]
    self._stop_delay_time = float(val) if val is not None else None
```

- [ ] **Step 6: Add to persistence (save/restore)**

Locate the `_save_state()` / `_apply_state()` / `to_dict()` / `from_dict()` methods in `output.py` and add the five fields. Follow the existing pattern for optional float fields (e.g. `onThreshold`).

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/test_output.py -k "shadow_timing" -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: add shadow motor timing fields to outputSettings (openTime/closeTime/angleOpenTime/angleCloseTime/stopDelayTime)"
```

---

## Task 5: Add `transitionTime` to `outputState`

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

```python
def test_output_state_includes_transition_time():
    out = Output(...)
    state = out.get_state_properties()
    assert "transitionTime" in state
    assert isinstance(state["transitionTime"], float)

def test_apply_state_stores_transition_time():
    out = Output(...)
    out.apply_state({"transitionTime": 0.5})
    assert out.get_state_properties()["transitionTime"] == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output.py -k "transition_time" -v
```
Expected: FAIL — `KeyError: 'transitionTime'`.

- [ ] **Step 3: Add `_transition_time` to `Output.__init__`**

```python
self._transition_time: float = 0.0
```

- [ ] **Step 4: Expose in `get_state_properties()`**

```python
def get_state_properties(self) -> dict[str, Any]:
    return {
        "localPriority": self._local_priority,
        "transitionTime": self._transition_time,
        "error": int(self._error),
    }
```

- [ ] **Step 5: Handle in `apply_state()`**

Find `apply_state()` and add:

```python
if "transitionTime" in state:
    val = state["transitionTime"]
    self._transition_time = float(val) if val is not None else 0.0
```

Also expose a `transition_time` setter property so device code can update it when a transition starts/ends.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_output.py -k "transition_time" -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: add transitionTime to outputState (matches p44vdc outputStateProperties)"
```

---

## Task 6: Store unknown `setProperty` keys instead of silently dropping them

**Files:**
- Modify: `src/pydsvdcapi/output.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

```python
def test_apply_settings_stores_unknown_key():
    out = Output(...)
    out.apply_settings({"someUnknownKey": 42.0, "anotherKey": "hello"})
    s = out.get_settings_properties()
    assert s["someUnknownKey"] == 42.0
    assert s["anotherKey"] == "hello"

def test_apply_settings_unknown_key_does_not_shadow_known():
    out = Output(...)
    out.apply_settings({"mode": 2, "someUnknownKey": 99})
    s = out.get_settings_properties()
    assert s["mode"] == 2          # known field handled normally
    assert s["someUnknownKey"] == 99  # unknown field stored
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_output.py -k "unknown_key" -v
```
Expected: FAIL — unknown keys are silently dropped.

- [ ] **Step 3: Add `_extra_settings` to `Output.__init__`**

```python
self._extra_settings: dict[str, Any] = {}
```

- [ ] **Step 4: Store unknown keys in `apply_settings()`**

The known keys form a static set. After processing all known keys, collect anything left:

```python
_KNOWN_SETTING_KEYS: frozenset[str] = frozenset({
    "mode", "activeGroup", "pushChanges", "groups",
    "onThreshold", "minBrightness",
    "dimTimeUp", "dimTimeDown",
    "dimTimeUpAlt1", "dimTimeDownAlt1",
    "dimTimeUpAlt2", "dimTimeDownAlt2",
    "heatingSystemCapability", "heatingSystemType",
    "openTime", "closeTime",
    "angleOpenTime", "angleCloseTime",
    "stopDelayTime",
})
```

At the end of `apply_settings()`:

```python
for key, val in settings.items():
    if key not in _KNOWN_SETTING_KEYS:
        self._extra_settings[key] = val
        logger.debug("outputSettings: stored unknown key '%s' = %r", key, val)
```

- [ ] **Step 5: Include `_extra_settings` in `get_settings_properties()`**

At the end of `get_settings_properties()`:

```python
# Unknown keys received via setProperty — returned verbatim.
settings.update(self._extra_settings)
return settings
```

- [ ] **Step 6: Add to persistence**

In save/restore, include `_extra_settings` as a dict under a key like `"_extraSettings"`.

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/test_output.py -k "unknown_key" -v
```
Expected: all pass.

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/pydsvdcapi/output.py tests/test_output.py
git commit -m "feat: store unknown outputSettings keys from setProperty instead of silently dropping them"
```

---

## Final Steps

- [ ] **Update CHANGELOG.md** — add `## [0.8.8]` section describing all six changes.

- [ ] **Bump version** — `pyproject.toml` and `__init__.py` to `"0.8.8"`.

- [ ] **Run ruff format + check**

```bash
ruff format src/ tests/ examples/
ruff check src/ tests/ examples/
```

- [ ] **Full test suite**

```bash
pytest tests/ -q
```

- [ ] **Final commit**

```bash
git commit -m "release: bump version to 0.8.8"
```
