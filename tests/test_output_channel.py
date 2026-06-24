"""Tests for the OutputChannel component and its integration with Output.

Covers:
* OutputChannel construction and defaults
* CHANNEL_SPECS metadata table
* Value management (set, clamp, age tracking)
* Bidirectional value flow (device → vdSM push, vdSM → device apply)
* apply_now buffering
* Output function → auto-created channels
* Manual channel management (add/remove/get)
* Channel property dicts (description, settings, state)
* Persistence round-trips
* vdsd.get_properties() channel exposure
* vdc_host setOutputChannelValue dispatch
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import pydsvdcapi.vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    ColorGroup,
    OutputChannelType,
    OutputFunction,
    OutputUsage,
)
from pydsvdcapi.output import FUNCTION_CHANNELS, Output
from pydsvdcapi.output_channel import (
    CHANNEL_SPECS,
    OutputChannel,
    get_channel_spec,
)
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import VdcHost
from pydsvdcapi.vdsd import Device, Vdsd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_host(**kwargs: Any) -> VdcHost:
    kw: dict[str, Any] = {"name": "Test Host", "mac": "AA:BB:CC:DD:EE:FF"}
    kw.update(kwargs)
    host = VdcHost(**kw)
    host._cancel_auto_save()
    return host


def _make_vdc(host: VdcHost, **kwargs: Any) -> Vdc:
    defaults: dict[str, Any] = {
        "host": host,
        "implementation_id": "x-test-channel",
        "name": "Test Channel vDC",
        "model": "Test v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("channel-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "Channel Test vdSD",
        "model": "Test Channel vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_stack(**kwargs: Any):
    """Create host→vdc→device→vdsd stack."""
    host = _make_host()
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device, **kwargs)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdc, device, vdsd


def _make_output(vdsd: Vdsd, **kwargs: Any) -> Output:
    defaults: dict[str, Any] = {
        "vdsd": vdsd,
        "function": OutputFunction.DIMMER,
        "output_usage": OutputUsage.ROOM,
        "name": "Test Dimmer",
        "default_group": 1,
        "active_group": 1,
        "groups": {1},
    }
    defaults.update(kwargs)
    return Output(**defaults)


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
    return session


# ===========================================================================
# CHANNEL_SPECS metadata
# ===========================================================================


class TestChannelSpecs:
    """Tests for the CHANNEL_SPECS lookup table."""

    def test_all_standard_types_present(self):
        """All standard OutputChannelType values should have specs."""
        expected = {
            OutputChannelType.BRIGHTNESS,
            OutputChannelType.HUE,
            OutputChannelType.SATURATION,
            OutputChannelType.COLOR_TEMPERATURE,
            OutputChannelType.CIE_X,
            OutputChannelType.CIE_Y,
            OutputChannelType.SHADE_POSITION_OUTSIDE,
            OutputChannelType.SHADE_POSITION_INDOOR,
            OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
            OutputChannelType.SHADE_OPENING_ANGLE_INDOOR,
            OutputChannelType.TRANSPARENCY,
            OutputChannelType.HEATING_POWER,
            OutputChannelType.COOLING_CAPACITY,
            OutputChannelType.AIR_FLOW_INTENSITY,
            OutputChannelType.AIR_FLOW_DIRECTION,
            OutputChannelType.AIR_FLAP_POSITION,
            OutputChannelType.AIR_LOUVER_POSITION,
            OutputChannelType.AIR_LOUVER_AUTO,
            OutputChannelType.AIR_FLOW_AUTO,
            OutputChannelType.AUDIO_VOLUME,
            OutputChannelType.WATER_TEMPERATURE,
            OutputChannelType.WATER_FLOW_RATE,
            OutputChannelType.POWER_STATE,
            OutputChannelType.POWER_LEVEL,
            OutputChannelType.VIDEO_STATION,
            OutputChannelType.VIDEO_INPUT_SOURCE,
            OutputChannelType.FCU_OPERATION_MODE,
        }
        assert set(CHANNEL_SPECS.keys()) == expected

    def test_get_channel_spec_known(self):
        spec = get_channel_spec(OutputChannelType.BRIGHTNESS)
        assert spec is not None
        assert spec.name == "brightness"
        assert spec.min_value == 0
        assert spec.max_value == 100

    def test_get_channel_spec_unknown(self):
        assert get_channel_spec(193) is None  # type: ignore[arg-type]

    def test_brightness_spec(self):
        spec = CHANNEL_SPECS[OutputChannelType.BRIGHTNESS]
        assert spec.name == "brightness"
        assert spec.min_value == 0
        assert spec.max_value == 100
        assert spec.resolution == pytest.approx(100 / 255)

    def test_hue_spec(self):
        spec = CHANNEL_SPECS[OutputChannelType.HUE]
        assert spec.name == "hue"
        assert spec.min_value == 0
        assert spec.max_value == 360

    def test_color_temperature_spec(self):
        spec = CHANNEL_SPECS[OutputChannelType.COLOR_TEMPERATURE]
        assert spec.name == "colortemp"
        assert spec.min_value == 100
        assert spec.max_value == 1000

    def test_shade_spec(self):
        spec = CHANNEL_SPECS[OutputChannelType.SHADE_POSITION_OUTSIDE]
        assert spec.name == "shadePositionOutside"
        assert spec.min_value == 0
        assert spec.max_value == 100

    def test_channel_spec_is_frozen(self):
        spec = CHANNEL_SPECS[OutputChannelType.BRIGHTNESS]
        with pytest.raises(AttributeError):
            spec.name = "changed"  # type: ignore[misc]


# ===========================================================================
# OutputChannel construction
# ===========================================================================


class TestOutputChannelConstruction:
    """Tests for OutputChannel creation and default values."""

    def test_brightness_channel_defaults(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        assert ch.channel_type == OutputChannelType.BRIGHTNESS
        assert ch.ds_index == 0
        assert ch.name == "brightness"
        assert ch.min_value == 0
        assert ch.max_value == 100
        assert ch.resolution == pytest.approx(100 / 255)
        assert ch.value is None
        assert ch.age is None
        assert ch.output is out

    def test_custom_name(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
            name="My Light",
        )
        assert ch.name == "My Light"

    def test_custom_min_max_resolution(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
            min_value=10,
            max_value=200,
            resolution=0.5,
        )
        assert ch.min_value == 10
        assert ch.max_value == 200
        assert ch.resolution == 0.5

    def test_unknown_channel_type_defaults(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=193,  # Device-specific (unknown)
            ds_index=5,
        )
        assert ch.channel_type == 193  # Stored as raw int.
        assert ch.name == "channel_5"
        assert ch.min_value == 0.0
        assert ch.max_value == 100.0
        assert ch.resolution == 1.0

    def test_custom_channel_siunit_symbol_enum_values(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=240,  # Custom/proprietary type
            ds_index=0,
            name="operatingMode",
            min_value=0,
            max_value=3,
            resolution=1,
            siunit="",
            symbol="",
            enum_values={0: "off", 1: "heating", 2: "cooling", 3: "auto"},
        )
        desc = ch.get_description_properties()
        assert desc["name"] == "operatingMode"
        assert desc["min"] == 0
        assert desc["max"] == 3
        assert "siunit" not in desc  # empty string → omitted
        assert "symbol" not in desc
        assert desc["values"] == {
            "0": "off",
            "1": "heating",
            "2": "cooling",
            "3": "auto",
        }

    def test_custom_channel_siunit_symbol_in_description(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=241,
            ds_index=0,
            name="powerLevel",
            min_value=0,
            max_value=5000,
            resolution=1,
            siunit="watt",
            symbol="W",
        )
        desc = ch.get_description_properties()
        assert desc["siunit"] == "watt"
        assert desc["symbol"] == "W"
        assert "values" not in desc  # no enum_values given

    def test_predefined_channel_ignores_siunit_symbol_enum_values_params(self):
        # Predefined channel: spec is authoritative; caller params for
        # siunit/symbol/enum_values must be silently ignored.
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
            siunit="kelvin",  # must be ignored
            symbol="K",  # must be ignored
            enum_values={0: "x"},  # must be ignored
        )
        desc = ch.get_description_properties()
        assert desc["siunit"] == "percent"  # from spec
        assert desc["symbol"] == "%"  # from spec
        assert "values" not in desc  # spec has no enum_values

    def test_predefined_enum_channel_ignores_enum_values_param(self):
        # FCU_OPERATION_MODE is a predefined enum channel.
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.FCU_OPERATION_MODE,
            ds_index=0,
            enum_values={0: "wrong"},  # must be ignored
        )
        desc = ch.get_description_properties()
        assert desc["values"]["0"] == "off"  # from spec, not "wrong"
        assert desc["values"]["1"] == "heating"

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        r = repr(ch)
        assert "BRIGHTNESS" in r
        assert "dsIndex=0" in r


# ===========================================================================
# Value management
# ===========================================================================


class TestOutputChannelValue:
    """Tests for value handling, clamping, and age tracking."""

    @pytest.mark.asyncio
    async def test_update_value_stores_and_timestamps(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        assert ch.value is None
        assert ch.age is None

        await ch.update_value(75.0)
        assert ch.value == 75.0
        assert ch.age is not None
        assert ch.age < 1.0  # Should be very recent.

    @pytest.mark.asyncio
    async def test_update_value_clamps_high(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        await ch.update_value(999.0)
        assert ch.value == 100.0  # max for brightness

    @pytest.mark.asyncio
    async def test_update_value_clamps_low(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        await ch.update_value(-10.0)
        assert ch.value == 0.0  # min for brightness

    def test_set_value_from_vdsm(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        ch.set_value_from_vdsm(50.0)
        assert ch.value == 50.0
        # Age is None until confirmed.
        assert ch.age is None

    def test_set_value_from_vdsm_clamps(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        ch.set_value_from_vdsm(200.0)
        assert ch.value == 100.0

    def test_confirm_applied_sets_age(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        ch.set_value_from_vdsm(50.0)
        assert ch.age is None  # Not confirmed yet.

        ch.confirm_applied()
        assert ch.age is not None
        assert ch.age < 1.0

    def test_age_increases_over_time(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.BRIGHTNESS,
            ds_index=0,
        )
        # Manually set the timestamp to a past point.
        ch._last_update = time.monotonic() - 5.0
        assert ch.age is not None
        assert ch.age >= 4.5


# ===========================================================================
# Output function → auto-created channels
# ===========================================================================


class TestFunctionAutoChannels:
    """Tests for auto-creation of channels by output function."""

    def test_on_off_creates_brightness(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.ON_OFF)
        channels = out.channels
        assert len(channels) == 1
        assert channels[0].channel_type == OutputChannelType.BRIGHTNESS

    def test_dimmer_creates_brightness(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        assert len(out.channels) == 1
        assert out.channels[0].channel_type == OutputChannelType.BRIGHTNESS

    def test_dimmer_color_temp_creates_two(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        assert len(out.channels) == 2
        types = {ch.channel_type for ch in out.channels.values()}
        assert types == {
            OutputChannelType.BRIGHTNESS,
            OutputChannelType.COLOR_TEMPERATURE,
        }

    def test_full_color_dimmer_creates_six(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        assert len(out.channels) == 6
        types = {ch.channel_type for ch in out.channels.values()}
        assert types == {
            OutputChannelType.BRIGHTNESS,
            OutputChannelType.HUE,
            OutputChannelType.SATURATION,
            OutputChannelType.COLOR_TEMPERATURE,
            OutputChannelType.CIE_X,
            OutputChannelType.CIE_Y,
        }

    def test_positional_creates_none(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        assert len(out.channels) == 0

    def test_bipolar_creates_none(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.BIPOLAR)
        assert len(out.channels) == 0

    def test_internally_controlled_creates_none(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.INTERNALLY_CONTROLLED)
        assert len(out.channels) == 0

    def test_auto_channels_ds_indices(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        assert sorted(out.channels.keys()) == [0, 1, 2, 3, 4, 5]

    def test_function_channels_mapping_complete(self):
        """The FUNCTION_CHANNELS constant covers the expected functions."""
        assert OutputFunction.ON_OFF in FUNCTION_CHANNELS
        assert OutputFunction.DIMMER in FUNCTION_CHANNELS
        assert OutputFunction.DIMMER_COLOR_TEMP in FUNCTION_CHANNELS
        assert OutputFunction.FULL_COLOR_DIMMER in FUNCTION_CHANNELS
        # These should NOT be in the mapping.
        assert OutputFunction.POSITIONAL not in FUNCTION_CHANNELS
        assert OutputFunction.BIPOLAR not in FUNCTION_CHANNELS
        assert OutputFunction.INTERNALLY_CONTROLLED not in FUNCTION_CHANNELS


# ===========================================================================
# Manual channel management
# ===========================================================================


class TestChannelManagement:
    """Tests for add_channel / remove_channel / get_channel."""

    def test_add_channel_manual(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        assert len(out.channels) == 0

        ch = out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        assert ch.channel_type == OutputChannelType.SHADE_POSITION_OUTSIDE
        assert ch.ds_index == 0
        assert len(out.channels) == 1

    def test_add_channel_auto_index(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch1 = out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        ch2 = out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
        assert ch1.ds_index == 0
        assert ch2.ds_index == 1

    def test_add_channel_explicit_index(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE, ds_index=5)
        assert ch.ds_index == 5

    def test_add_channel_duplicate_index_raises(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE, ds_index=0)
        with pytest.raises(ValueError, match="ds_index 0 already in use"):
            out.add_channel(
                OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
                ds_index=0,
            )

    def test_add_channel_with_overrides(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = out.add_channel(
            OutputChannelType.SHADE_POSITION_OUTSIDE,
            name="Main Shade",
            min_value=5,
            max_value=95,
            resolution=0.1,
        )
        assert ch.name == "Main Shade"
        assert ch.min_value == 5
        assert ch.max_value == 95
        assert ch.resolution == 0.1

    def test_remove_channel(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        removed = out.remove_channel(0)
        assert removed is ch
        assert len(out.channels) == 0

    def test_remove_channel_nonexistent(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        assert out.remove_channel(99) is None

    def test_get_channel(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        assert ch is not None
        assert ch.channel_type == OutputChannelType.BRIGHTNESS

    def test_get_channel_nonexistent(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        assert out.get_channel(99) is None

    def test_get_channel_by_type(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel_by_type(OutputChannelType.BRIGHTNESS)
        assert ch is not None
        assert ch.ds_index == 0

    def test_get_channel_by_type_not_found(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        assert out.get_channel_by_type(OutputChannelType.HUE) is None


# ===========================================================================
# Channel property dicts
# ===========================================================================


class TestChannelPropertyDicts:
    """Tests for channel get_*_properties() methods."""

    def test_description_properties(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        desc = ch.get_description_properties()
        assert desc["name"] == "brightness"
        assert desc["channelType"] == 1
        assert desc["dsIndex"] == 0
        assert desc["min"] == 0
        assert desc["max"] == 100
        assert "resolution" in desc

    def test_settings_properties_empty(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        assert ch.get_settings_properties() == {}

    def test_state_properties_initial(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        state = ch.get_state_properties()
        assert (
            state["value"] == 0.0
        )  # uninitialized → 0.0, matching p44vdc v_double default
        assert state["age"] is None

    @pytest.mark.asyncio
    async def test_state_properties_after_update(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        await ch.update_value(42.0)
        state = ch.get_state_properties()
        assert state["value"] == 42.0
        assert state["age"] is not None
        assert state["age"] < 1.0

    def test_state_properties_after_vdsm_set(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(80.0)
        state = ch.get_state_properties()
        assert state["value"] == 80.0
        assert state["age"] is None  # Not confirmed.


# ===========================================================================
# Output-level channel property helpers
# ===========================================================================


class TestOutputChannelProperties:
    """Tests for Output.get_channel_descriptions/settings/states."""

    def test_channel_descriptions(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        desc = out.get_channel_descriptions()
        assert len(desc) == 2
        # Keys are channel name strings.
        assert "brightness" in desc
        assert "colortemp" in desc
        assert desc["brightness"]["channelType"] == int(OutputChannelType.BRIGHTNESS)
        assert desc["colortemp"]["channelType"] == int(
            OutputChannelType.COLOR_TEMPERATURE
        )
        # Name field is also present inside each element.
        assert desc["brightness"]["name"] == "brightness"
        assert desc["colortemp"]["name"] == "colortemp"

    def test_channel_settings(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        settings = out.get_channel_settings()
        assert len(settings) == 1
        # DIMMER uses channel name key (API v3+).
        assert settings["brightness"] == {}

    @pytest.mark.asyncio
    async def test_channel_states(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        await ch.update_value(60.0)
        states = out.get_channel_states()
        # DIMMER uses channel name key (API v3+).
        assert states["brightness"]["value"] == 60.0
        assert states["brightness"]["age"] is not None


# ===========================================================================
# Bidirectional value flow — device → vdSM push
# ===========================================================================


class TestDeviceToVdsmPush:
    """Tests for pushing channel state from device to vdSM."""

    @pytest.mark.asyncio
    async def test_push_when_push_changes_enabled(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.push_changes = True
        session = _make_mock_session()
        out.start_session(session)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        await ch.update_value(75.0)

        session.send_notification.assert_called_once()
        sent_msg = session.send_notification.call_args[0][0]
        assert sent_msg.type == pb.VDC_SEND_PUSH_NOTIFICATION

    @pytest.mark.asyncio
    async def test_no_push_when_push_changes_disabled(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.push_changes = False
        session = _make_mock_session()
        out.start_session(session)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        await ch.update_value(75.0)

        session.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_push_without_session(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.push_changes = True
        # No session started.
        vdsd.set_output(out)

        ch = out.get_channel(0)
        # Should not raise even without session.
        await ch.update_value(75.0)
        assert ch.value == 75.0

    @pytest.mark.asyncio
    async def test_push_contains_channel_state(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.push_changes = True
        session = _make_mock_session()
        out.start_session(session)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        await ch.update_value(42.0)

        sent_msg = session.send_notification.call_args[0][0]
        assert sent_msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)


# ===========================================================================
# Bidirectional value flow — vdSM → device (apply_now buffering)
# ===========================================================================


class TestVdsmToDeviceApply:
    """Tests for setOutputChannelValue handling and apply_now."""

    @pytest.mark.asyncio
    async def test_buffer_and_apply(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        applied = {}

        async def on_apply(output, updates):
            applied.update(updates)

        out.on_channel_applied = on_apply

        ch = out.get_channel(0)
        out.buffer_channel_value(ch, 80.0)
        # Not yet applied.
        assert ch.age is None
        assert len(applied) == 0

        await out.apply_pending_channels()
        assert applied[OutputChannelType.BRIGHTNESS] == 80.0
        assert ch.age is not None  # Confirmed.

    @pytest.mark.asyncio
    async def test_buffer_multiple_then_apply(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        vdsd.set_output(out)

        applied = {}

        async def on_apply(output, updates):
            applied.update(updates)

        out.on_channel_applied = on_apply

        ch_bright = out.get_channel_by_type(OutputChannelType.BRIGHTNESS)
        ch_ct = out.get_channel_by_type(OutputChannelType.COLOR_TEMPERATURE)

        out.buffer_channel_value(ch_bright, 50.0)
        out.buffer_channel_value(ch_ct, 400.0)

        await out.apply_pending_channels()
        assert applied[OutputChannelType.BRIGHTNESS] == 50.0
        assert applied[OutputChannelType.COLOR_TEMPERATURE] == 400.0
        assert ch_bright.age is not None
        assert ch_ct.age is not None

    @pytest.mark.asyncio
    async def test_apply_clears_pending(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        async def noop(output, updates):
            pass

        out.on_channel_applied = noop

        ch = out.get_channel(0)
        out.buffer_channel_value(ch, 50.0)
        await out.apply_pending_channels()
        assert out._pending_channel_updates == {}

    @pytest.mark.asyncio
    async def test_apply_no_pending_is_noop(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        call_count = 0

        async def on_apply(output, updates):
            nonlocal call_count
            call_count += 1

        out.on_channel_applied = on_apply

        await out.apply_pending_channels()
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_apply_without_callback(self):
        """apply_pending_channels works even without on_channel_applied."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        out.buffer_channel_value(ch, 60.0)
        await out.apply_pending_channels()
        # Value confirmed, no exception.
        assert ch.age is not None

    @pytest.mark.asyncio
    async def test_callback_exception_still_confirms(self):
        """Channels are confirmed even if callback raises."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        async def bad_callback(output, updates):
            raise RuntimeError("Hardware failure")

        out.on_channel_applied = bad_callback

        ch = out.get_channel(0)
        out.buffer_channel_value(ch, 40.0)
        await out.apply_pending_channels()
        # Confirmed despite exception.
        assert ch.age is not None


# ===========================================================================
# Persistence
# ===========================================================================


class TestChannelPersistence:
    """Tests for channel persistence round-trips."""

    def test_channel_property_tree(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        tree = ch.get_property_tree()
        assert tree["channelType"] == int(OutputChannelType.BRIGHTNESS)
        assert tree["dsIndex"] == 0
        assert tree["name"] == "brightness"
        assert tree["min"] == 0
        assert tree["max"] == 100
        assert "resolution" in tree
        # Predefined channel: siunit/symbol are stored (from spec).
        assert tree["siunit"] == "percent"
        assert tree["symbol"] == "%"
        assert "enumValues" not in tree  # brightness has no discrete values

    def test_custom_channel_property_tree_persists_siunit_symbol_enum_values(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch = OutputChannel(
            output=out,
            channel_type=240,
            ds_index=0,
            name="myMode",
            min_value=0,
            max_value=3,
            resolution=1,
            siunit="",
            symbol="",
            enum_values={0: "off", 1: "on", 2: "eco"},
        )
        tree = ch.get_property_tree()
        assert "siunit" not in tree  # empty string → not persisted
        assert "symbol" not in tree
        assert tree["enumValues"] == {"0": "off", "1": "on", "2": "eco"}

    def test_custom_channel_siunit_symbol_persisted_and_restored(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch1 = OutputChannel(
            output=out,
            channel_type=241,
            ds_index=0,
            name="powerWatts",
            min_value=0,
            max_value=5000,
            resolution=1,
            siunit="watt",
            symbol="W",
        )
        tree = ch1.get_property_tree()
        assert tree["siunit"] == "watt"
        assert tree["symbol"] == "W"

        # Restore into a new instance and verify description.
        ch2 = OutputChannel(output=out, channel_type=241, ds_index=0)
        ch2._apply_state(tree)
        desc = ch2.get_description_properties()
        assert desc["siunit"] == "watt"
        assert desc["symbol"] == "W"

    def test_custom_channel_enum_values_round_trip(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd)
        ch1 = OutputChannel(
            output=out,
            channel_type=242,
            ds_index=0,
            name="operMode",
            min_value=0,
            max_value=2,
            resolution=1,
            enum_values={0: "off", 1: "heat", 2: "cool"},
        )
        tree = ch1.get_property_tree()

        ch2 = OutputChannel(output=out, channel_type=242, ds_index=0)
        ch2._apply_state(tree)
        desc = ch2.get_description_properties()
        assert desc["values"] == {"0": "off", "1": "heat", "2": "cool"}

    def test_channel_apply_state(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = OutputChannel(
            output=out,
            channel_type=OutputChannelType.SHADE_POSITION_OUTSIDE,
            ds_index=0,
        )
        tree = {
            "channelType": int(OutputChannelType.SHADE_POSITION_OUTSIDE),
            "dsIndex": 0,
            "name": "Custom Name",
            "min": 5.0,
            "max": 95.0,
            "resolution": 0.5,
        }
        ch._apply_state(tree)
        assert ch.name == "Custom Name"
        assert ch.min_value == 5.0
        assert ch.max_value == 95.0
        assert ch.resolution == 0.5

    def test_output_property_tree_includes_channels(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        tree = out.get_property_tree()
        assert "channels" in tree
        assert len(tree["channels"]) == 1
        assert tree["channels"][0]["channelType"] == int(OutputChannelType.BRIGHTNESS)

    def test_output_restore_channels(self):
        _, _, _, vdsd = _make_stack()
        out1 = _make_output(vdsd, function=OutputFunction.DIMMER)
        tree = out1.get_property_tree()

        # Create new output and restore.
        out2 = _make_output(
            vdsd,
            function=OutputFunction.POSITIONAL,  # Different fn.
        )
        assert len(out2.channels) == 0  # POSITIONAL = no auto-channels.

        out2._apply_state(tree)
        assert out2.function == OutputFunction.DIMMER
        assert len(out2.channels) == 1
        assert out2.channels[0].channel_type == (OutputChannelType.BRIGHTNESS)

    def test_output_restore_without_channels_key(self):
        """If no 'channels' key, channels should be re-created from fn."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        # Restore with function=DIMMER but no channels key.
        out._apply_state({"function": int(OutputFunction.DIMMER)})
        assert len(out.channels) == 1
        assert out.channels[0].channel_type == (OutputChannelType.BRIGHTNESS)

    def test_full_color_dimmer_round_trip(self):
        _, _, _, vdsd = _make_stack()
        out1 = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        tree = out1.get_property_tree()

        out2 = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out2._apply_state(tree)

        assert len(out2.channels) == 6
        types = {ch.channel_type for ch in out2.channels.values()}
        assert OutputChannelType.BRIGHTNESS in types
        assert OutputChannelType.HUE in types
        assert OutputChannelType.SATURATION in types
        assert OutputChannelType.COLOR_TEMPERATURE in types
        assert OutputChannelType.CIE_X in types
        assert OutputChannelType.CIE_Y in types

    def test_manual_channels_round_trip(self):
        _, _, _, vdsd = _make_stack()
        out1 = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out1.add_channel(
            OutputChannelType.SHADE_POSITION_OUTSIDE,
            name="Roller",
            min_value=5,
            max_value=95,
        )
        out1.add_channel(
            OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
        )
        tree = out1.get_property_tree()

        out2 = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out2._apply_state(tree)

        assert len(out2.channels) == 2
        ch0 = out2.get_channel(0)
        assert ch0.name == "Roller"
        assert ch0.min_value == 5
        assert ch0.max_value == 95
        ch1 = out2.get_channel(1)
        assert ch1.channel_type == (OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)


# ===========================================================================
# vdsd.get_properties() integration
# ===========================================================================


class TestVdsdChannelProperties:
    """Tests for channel property exposure via vdsd.get_properties()."""

    def test_properties_include_channel_descriptions(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        props = vdsd.get_properties()
        assert "channelDescriptions" in props
        # DIMMER uses channel name key (API v3+).
        assert "brightness" in props["channelDescriptions"]
        assert props["channelDescriptions"]["brightness"]["name"] == "brightness"

    def test_properties_include_channel_states(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        props = vdsd.get_properties()
        assert "channelStates" in props
        # DIMMER uses channel name key (API v3+).
        assert "brightness" in props["channelStates"]
        assert props["channelStates"]["brightness"]["value"] == 0.0

    def test_properties_include_channel_settings(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        props = vdsd.get_properties()
        assert "channelSettings" in props
        # DIMMER uses channel name key (API v3+).
        assert "brightness" in props["channelSettings"]

    def test_no_channels_no_properties(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        vdsd.set_output(out)

        props = vdsd.get_properties()
        assert "channelDescriptions" not in props


# ===========================================================================
# vdc_host setOutputChannelValue dispatch
# ===========================================================================


class TestVdcHostSetOutputChannelValue:
    """Tests for vdc_host handling of VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE."""

    def _build_msg(
        self,
        dsuid_str: str,
        channel: int = 0,
        channel_id: str = "",
        value: float = 50.0,
        apply_now: bool = True,
    ) -> pb.Message:
        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE
        notif = msg.vdsm_send_output_channel_value
        notif.dSUID.append(dsuid_str)
        notif.channel = channel
        notif.channelId = channel_id
        notif.value = value
        notif.apply_now = apply_now
        return msg

    @pytest.mark.asyncio
    async def test_dispatch_sets_value_and_applies(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        applied = {}

        async def on_apply(output, updates):
            applied.update(updates)

        out.on_channel_applied = on_apply

        session = _make_mock_session()
        msg = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            channel=int(OutputChannelType.BRIGHTNESS),
            value=75.0,
            apply_now=True,
        )

        await host._dispatch_message(session, msg)

        assert applied[OutputChannelType.BRIGHTNESS] == 75.0
        ch = out.get_channel(0)
        assert ch.value == 75.0
        assert ch.age is not None

    @pytest.mark.asyncio
    async def test_dispatch_by_channel_id(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        applied = {}

        async def on_apply(output, updates):
            applied.update(updates)

        out.on_channel_applied = on_apply

        session = _make_mock_session()
        msg = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            channel_id="brightness",
            value=60.0,
            apply_now=True,
        )

        await host._dispatch_message(session, msg)
        assert applied[OutputChannelType.BRIGHTNESS] == 60.0

    @pytest.mark.asyncio
    async def test_dispatch_buffer_then_apply(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        vdsd.set_output(out)

        applied = {}

        async def on_apply(output, updates):
            applied.update(updates)

        out.on_channel_applied = on_apply

        session = _make_mock_session()

        # First: buffer brightness (apply_now=False).
        msg1 = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            channel=int(OutputChannelType.BRIGHTNESS),
            value=50.0,
            apply_now=False,
        )
        await host._dispatch_message(session, msg1)
        assert len(applied) == 0  # Not yet applied.

        # Second: set color temp with apply_now=True.
        msg2 = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            channel=int(OutputChannelType.COLOR_TEMPERATURE),
            value=400.0,
            apply_now=True,
        )
        await host._dispatch_message(session, msg2)

        # Both should be applied now.
        assert applied[OutputChannelType.BRIGHTNESS] == 50.0
        assert applied[OutputChannelType.COLOR_TEMPERATURE] == 400.0

    @pytest.mark.asyncio
    async def test_dispatch_unknown_dsuid(self):
        host, vdc, device, vdsd = _make_stack()
        session = _make_mock_session()
        msg = self._build_msg(
            dsuid_str="0000000000000000000000000000000000",
            value=50.0,
        )
        # Should not raise — just logs a warning.
        await host._dispatch_message(session, msg)

    @pytest.mark.asyncio
    async def test_dispatch_no_output(self):
        host, vdc, device, vdsd = _make_stack()
        # No output set on vdsd.
        session = _make_mock_session()
        msg = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            value=50.0,
        )
        # Should not raise.
        await host._dispatch_message(session, msg)

    @pytest.mark.asyncio
    async def test_dispatch_unknown_channel(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        session = _make_mock_session()
        msg = self._build_msg(
            dsuid_str=str(vdsd.dsuid),
            channel=999,  # Non-existent channel type.
            value=50.0,
        )
        # Should not raise.
        await host._dispatch_message(session, msg)

    @pytest.mark.asyncio
    async def test_dispatch_still_delegates_other_messages(self):
        """Other message types still go to the user callback."""
        host, vdc, device, vdsd = _make_stack()

        received = []

        async def on_msg(session, msg):
            received.append(msg.type)
            return None

        host._on_message = on_msg

        session = _make_mock_session()
        msg = pb.Message()
        msg.type = pb.VDSM_SEND_BYE  # not handled in _dispatch_message

        await host._dispatch_message(session, msg)
        assert pb.VDSM_SEND_BYE in received


# ===========================================================================
# Edge cases and integration
# ===========================================================================


class TestEdgeCases:
    """Various edge cases and integration tests."""

    @pytest.mark.asyncio
    async def test_clamp_on_update_value(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        await ch.update_value(150.0)
        assert ch.value == 100.0
        await ch.update_value(-50.0)
        assert ch.value == 0.0

    def test_clamp_on_set_value_from_vdsm(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(150.0)
        assert ch.value == 100.0

    def test_hue_channel_range(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        ch = out.get_channel_by_type(OutputChannelType.HUE)
        assert ch.min_value == 0
        assert ch.max_value == 360

    def test_color_temp_channel_range(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        ch = out.get_channel_by_type(OutputChannelType.COLOR_TEMPERATURE)
        assert ch.min_value == 100
        assert ch.max_value == 1000

    @pytest.mark.asyncio
    async def test_multiple_devices_independent(self):
        """Channels on different devices don't interfere."""
        host = _make_host()
        vdc = _make_vdc(host)

        d1_uid = DsUid.from_name_in_space("dev1", DsUidNamespace.VDC)
        d1 = Device(vdc=vdc, dsuid=d1_uid)
        vdsd1 = Vdsd(
            device=d1, primary_group=ColorGroup.YELLOW, name="D1", model="Test"
        )
        d1.add_vdsd(vdsd1)
        vdc.add_device(d1)

        d2_uid = DsUid.from_name_in_space("dev2", DsUidNamespace.VDC)
        d2 = Device(vdc=vdc, dsuid=d2_uid)
        vdsd2 = Vdsd(
            device=d2, primary_group=ColorGroup.YELLOW, name="D2", model="Test"
        )
        d2.add_vdsd(vdsd2)
        vdc.add_device(d2)

        host.add_vdc(vdc)

        out1 = Output(
            vdsd=vdsd1,
            function=OutputFunction.DIMMER,
            name="Out1",
            default_group=1,
            active_group=1,
            groups={1},
        )
        vdsd1.set_output(out1)
        out2 = Output(
            vdsd=vdsd2,
            function=OutputFunction.DIMMER,
            name="Out2",
            default_group=1,
            active_group=1,
            groups={1},
        )
        vdsd2.set_output(out2)

        ch1 = out1.get_channel(0)
        ch2 = out2.get_channel(0)

        await ch1.update_value(30.0)
        await ch2.update_value(70.0)

        assert ch1.value == 30.0
        assert ch2.value == 70.0

    def test_output_repr_unchanged(self):
        """Output repr doesn't crash with channels present."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        r = repr(out)
        assert "DIMMER" in r

    def test_channels_view_is_copy(self):
        """Output.channels returns a copy, not internal dict."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        view = out.channels
        view[99] = None  # Mutate the copy.
        assert 99 not in out.channels  # Internal not affected.

    def test_remove_channel_clears_pending(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        out.buffer_channel_value(ch, 50.0)
        assert 0 in out._pending_channel_updates
        out.remove_channel(0)
        assert 0 not in out._pending_channel_updates

    def test_vdsd_persistence_includes_channels(self):
        """vdsd.get_property_tree() includes output channels."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        tree = vdsd.get_property_tree()
        assert "output" in tree
        assert "channels" in tree["output"]

    def test_vdsd_restore_preserves_channels(self):
        """Round-trip vdsd with output and channels."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        tree = vdsd.get_property_tree()

        # Create fresh vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        dev2.add_vdsd(vdsd2)
        vdc2.add_device(dev2)
        host2.add_vdc(vdc2)

        vdsd2._apply_state(tree)
        assert vdsd2.output is not None
        assert len(vdsd2.output.channels) == 1


# ===========================================================================
# siunit / symbol in channel descriptions
# ===========================================================================


class TestChannelDescriptionSiunitSymbol:
    """Tests for siunit and symbol fields in channelDescriptions."""

    def test_channel_description_includes_siunit_and_symbol(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = out.get_channel(0)
        desc = ch.get_description_properties()
        assert "siunit" in desc
        assert "symbol" in desc
        assert desc["siunit"] == "percent"
        assert desc["symbol"] == "%"

    def test_shade_channel_description_includes_siunit_percent(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE, ds_index=0)
        desc = ch.get_description_properties()
        assert desc["siunit"] == "percent"
        assert desc["symbol"] == "%"

    def test_colortemp_channel_siunit(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        ch = out.get_channel_by_type(OutputChannelType.COLOR_TEMPERATURE)
        desc = ch.get_description_properties()
        assert desc["siunit"] == "reciprocal megakelvin"
        assert desc["symbol"] == "mired"

    def test_hue_channel_siunit(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        ch = out.get_channel_by_type(OutputChannelType.HUE)
        desc = ch.get_description_properties()
        assert desc["siunit"] == "degree"
        assert desc["symbol"] == "°"

    def test_cie_x_channel_no_siunit(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        ch = out.get_channel_by_type(OutputChannelType.CIE_X)
        desc = ch.get_description_properties()
        assert "siunit" not in desc
        assert "symbol" not in desc

    def test_air_flow_direction_no_siunit(self):
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        ch = out.add_channel(OutputChannelType.AIR_FLOW_DIRECTION, ds_index=0)
        desc = ch.get_description_properties()
        assert "siunit" not in desc
        assert "symbol" not in desc

    def test_shade_position_resolution_16bit(self):
        """Shade channels must use 16-bit resolution (100/65536)."""
        spec = CHANNEL_SPECS[OutputChannelType.SHADE_POSITION_OUTSIDE]
        assert spec.resolution == pytest.approx(100 / 65536)

    def test_shade_angle_resolution_16bit(self):
        spec = CHANNEL_SPECS[OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE]
        assert spec.resolution == pytest.approx(100 / 65536)

    def test_shade_indoor_resolution_16bit(self):
        spec = CHANNEL_SPECS[OutputChannelType.SHADE_POSITION_INDOOR]
        assert spec.resolution == pytest.approx(100 / 65536)

    def test_shade_angle_indoor_resolution_16bit(self):
        spec = CHANNEL_SPECS[OutputChannelType.SHADE_OPENING_ANGLE_INDOOR]
        assert spec.resolution == pytest.approx(100 / 65536)


# ===========================================================================
# __init__.py exports
# ===========================================================================


class TestExports:
    """Verify that key symbols are importable from the package."""

    def test_output_channel_exported(self):
        from pydsvdcapi import OutputChannel

        assert OutputChannel is not None

    def test_channel_specs_exported(self):
        from pydsvdcapi import CHANNEL_SPECS, ChannelSpec

        assert len(CHANNEL_SPECS) > 0
        assert isinstance(list(CHANNEL_SPECS.values())[0], ChannelSpec)

    def test_get_channel_spec_exported(self):
        from pydsvdcapi import get_channel_spec

        assert callable(get_channel_spec)

    def test_function_channels_exported(self):
        from pydsvdcapi import FUNCTION_CHANNELS

        assert OutputFunction.DIMMER in FUNCTION_CHANNELS


# ===========================================================================
# Function-based channel container key tests
# ===========================================================================


class TestChannelContainerKeyFormat:
    """All output functions use the channel name as the property-dict key (API v3+)."""

    def test_dimmer_keyed_by_name(self):
        """DIMMER: channelDescriptions/Settings/States keyed by channel name (API v3+)."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        ch = list(out.channels.values())[0]
        desc = out.get_channel_descriptions()
        assert ch.name in desc  # "brightness"
        # Numeric keys are now transparently resolvable (backward-compat).
        assert str(ch.ds_index) in desc  # "0" resolves to brightness via channel_by_key

    def test_on_off_keyed_by_name(self):
        """ON_OFF: channelDescriptions keyed by channel name (API v3+)."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.ON_OFF)
        ch = list(out.channels.values())[0]
        desc = out.get_channel_descriptions()
        assert ch.name in desc
        # Numeric keys are now transparently resolvable (backward-compat).
        assert str(ch.ds_index) in desc

    def test_positional_keyed_by_name(self):
        """POSITIONAL: shade channels keyed by channel name, matching p44vdc wire format.

        The outer key becomes channel.id in dSS.  The vdSM builds the OPC table
        from the channelType and dsIndex sub-element fields, not from the outer
        key, so the channel name is correct here (as p44vdc uses).
        """
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        out.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
        desc = out.get_channel_descriptions()
        assert "shadePositionOutside" in desc
        assert "shadeOpeningAngleOutside" in desc
        # Numeric keys are now transparently resolvable (backward-compat).
        assert "7" in desc  # shadePositionOutside (channelType=7)
        assert "9" in desc  # shadeOpeningAngleOutside (channelType=9)
        assert "0" in desc  # standard channel (resolves to first channel)

    def test_dimmer_color_temp_keyed_by_name(self):
        """DIMMER_COLOR_TEMP: all channels keyed by channel name."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        desc = out.get_channel_descriptions()
        assert "brightness" in desc
        assert "colortemp" in desc
        # Numeric keys are now transparently resolvable (backward-compat).
        assert "0" in desc  # standard channel (resolves to brightness)
        assert "1" in desc  # brightness (channelType=1)

    def test_full_color_dimmer_keyed_by_name(self):
        """FULL_COLOR_DIMMER: all channels keyed by channel name."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.FULL_COLOR_DIMMER)
        desc = out.get_channel_descriptions()
        assert "brightness" in desc
        assert "hue" in desc
        assert "saturation" in desc
        assert "colortemp" in desc
        # Numeric keys are now transparently resolvable (backward-compat).
        assert "0" in desc  # standard channel (resolves to brightness)

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
        assert ch.name in props["channelStates"]  # "brightness"
        assert str(ch.ds_index) not in props["channelStates"]  # NOT "0"

    @pytest.mark.asyncio
    async def test_push_notification_color_temp_keyed_by_name(self):
        """Push notification for DIMMER_COLOR_TEMP must use channel name key."""
        from pydsvdcapi.property_handling import elements_to_dict

        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        out.push_changes = True
        session = _make_mock_session()
        out.start_session(session)
        vdsd.set_output(out)

        ch = out.get_channel(0)  # brightness channel
        await ch.update_value(80.0)

        sent_msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(sent_msg.vdc_send_push_notification.changedproperties)
        assert "channelStates" in props
        assert ch.name in props["channelStates"]  # "brightness"
        assert str(ch.ds_index) not in props["channelStates"]  # not "0"


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
        container.name = property_name  # e.g. "channelDescriptions"
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
        out.get_channel(0).set_value_from_vdsm(75.0)
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
        from pydsvdcapi import vdc_messages_pb2 as pb
        from pydsvdcapi.property_handling import (
            build_get_property_response,
            elements_to_dict,
        )
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


class TestChannelSpecsAndEnums:
    """Channel type enum and CHANNEL_SPECS match the ds-basics §7 reference tables."""

    def test_water_flow_channel_name_is_waterFlow(self):
        """WATER_FLOW_RATE spec name must be 'waterFlow' not 'waterFlowRate'."""
        from pydsvdcapi.enums import OutputChannelType
        from pydsvdcapi.output_channel import get_channel_spec

        spec = get_channel_spec(OutputChannelType.WATER_FLOW_RATE)
        assert spec is not None
        assert spec.name == "waterFlow"

    def test_fcu_operation_mode_channel_type_exists(self):
        """OutputChannelType must have FCU_OPERATION_MODE = 192."""
        from pydsvdcapi.enums import OutputChannelType

        assert OutputChannelType.FCU_OPERATION_MODE == 192

    def test_fcu_operation_mode_has_channel_spec(self):
        """CHANNEL_SPECS must have an entry for FCU_OPERATION_MODE with name 'operationMode'."""
        from pydsvdcapi.enums import OutputChannelType
        from pydsvdcapi.output_channel import get_channel_spec

        spec = get_channel_spec(OutputChannelType.FCU_OPERATION_MODE)
        assert spec is not None
        assert spec.name == "operationMode"

    def test_color_class_standard_channel_lights(self):
        """COLOR_CLASS_STANDARD_CHANNEL[LIGHTS] == BRIGHTNESS."""
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        assert (
            COLOR_CLASS_STANDARD_CHANNEL[ColorClass.LIGHTS]
            == OutputChannelType.BRIGHTNESS
        )

    def test_color_class_standard_channel_blinds(self):
        """COLOR_CLASS_STANDARD_CHANNEL[BLINDS] == SHADE_POSITION_OUTSIDE."""
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        assert (
            COLOR_CLASS_STANDARD_CHANNEL[ColorClass.BLINDS]
            == OutputChannelType.SHADE_POSITION_OUTSIDE
        )

    def test_color_class_standard_channel_heating(self):
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        assert (
            COLOR_CLASS_STANDARD_CHANNEL[ColorClass.HEATING]
            == OutputChannelType.HEATING_POWER
        )

    def test_color_class_standard_channel_cooling(self):
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        assert (
            COLOR_CLASS_STANDARD_CHANNEL[ColorClass.COOLING]
            == OutputChannelType.COOLING_CAPACITY
        )

    def test_color_class_standard_channel_ventilation(self):
        from pydsvdcapi.enums import ColorClass, OutputChannelType
        from pydsvdcapi.output_channel import COLOR_CLASS_STANDARD_CHANNEL

        assert (
            COLOR_CLASS_STANDARD_CHANNEL[ColorClass.VENTILATION]
            == OutputChannelType.AIR_FLOW_INTENSITY
        )


# ===========================================================================
# channel_by_key() resolution
# ===========================================================================


class TestChannelByKey:
    """channel_by_key() resolves canonical names, numeric channelType, and standard-channel key."""

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


# ===========================================================================
# display_name — free label for channelDescriptions["name"]
# ===========================================================================


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
        # channelId (container key) is the canonical name, not the display_name
        assert ch.name == "shadePositionOutside"
        # but the "name" sub-field in the description uses display_name
        assert ch.get_description_properties()["name"] == "Living Room Shade"

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
        # container key (channelId) is still the channel's name, not display_name
        assert ch.name == "myMode"
