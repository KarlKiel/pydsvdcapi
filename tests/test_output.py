"""Tests for the Output component."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    ColorGroup,
    HeatingSystemCapability,
    HeatingSystemType,
    OutputError,
    OutputFunction,
    OutputMode,
    OutputUsage,
)
from pydsvdcapi.output import Output
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
        "implementation_id": "x-test-output",
        "name": "Test Output vDC",
        "model": "Test Output v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("output-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "Output Test vdSD",
        "model": "Test Output vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


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
    return session


def _make_stack(**kwargs: Any):
    """Create a full host→vdc→device→vdsd stack, return (host, vdc, device, vdsd)."""
    host = _make_host()
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device, **kwargs)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdc, device, vdsd


# ===========================================================================
# Construction and defaults
# ===========================================================================


class TestOutputConstruction:
    """Tests for Output creation and default values."""

    def test_default_construction(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)

        assert out.function == OutputFunction.DIMMER
        assert out.output_usage == OutputUsage.ROOM
        assert out.name == "Test Dimmer"
        assert out.default_group == 1
        assert out.variable_ramp is False
        assert out.max_power is None
        assert out.active_cooling_mode is None
        assert out.vdsd is vdsd

    def test_default_settings(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd
        )  # _make_output uses OutputFunction.DIMMER → auto-derives GRADUAL

        assert out.mode == OutputMode.GRADUAL
        assert out.active_group == 1
        assert out.groups == {1}
        assert out.push_changes is False
        assert out.on_threshold is None
        assert out.min_brightness is None
        assert out.dim_time_up is None
        assert out.dim_time_down is None
        assert out.dim_time_up_alt1 is None
        assert out.dim_time_down_alt1 is None
        assert out.dim_time_up_alt2 is None
        assert out.dim_time_down_alt2 is None
        assert out.heating_system_capability is None
        assert out.heating_system_type is None

    def test_default_state(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)

        assert out.local_priority is False
        assert out.error == OutputError.OK

    def test_custom_construction(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.FULL_COLOR_DIMMER,
            output_usage=OutputUsage.OUTDOORS,
            name="RGB Flood",
            default_group=1,
            variable_ramp=True,
            max_power=120.0,
            active_cooling_mode=False,
            mode=OutputMode.GRADUAL,
            active_group=1,
            groups={1, 4, 8},
            push_changes=True,
            on_threshold=50.0,
            min_brightness=10.0,
            dim_time_up=100,
            dim_time_down=80,
            dim_time_up_alt1=150,
            dim_time_down_alt1=120,
            dim_time_up_alt2=200,
            dim_time_down_alt2=180,
            heating_system_capability=HeatingSystemCapability.HEATING_AND_COOLING,
            heating_system_type=HeatingSystemType.FLOOR_HEATING,
        )

        assert out.function == OutputFunction.FULL_COLOR_DIMMER
        assert out.output_usage == OutputUsage.OUTDOORS
        assert out.name == "RGB Flood"
        assert out.default_group == 1
        assert out.variable_ramp is True
        assert out.max_power == 120.0
        assert out.active_cooling_mode is False
        assert out.mode == OutputMode.GRADUAL
        assert out.active_group == 1
        assert out.groups == {1, 4, 8}
        assert out.push_changes is True
        assert out.on_threshold == 50.0
        assert out.min_brightness == 10.0
        assert out.dim_time_up == 100
        assert out.dim_time_down == 80
        assert out.dim_time_up_alt1 == 150
        assert out.dim_time_down_alt1 == 120
        assert out.dim_time_up_alt2 == 200
        assert out.dim_time_down_alt2 == 180
        assert (
            out.heating_system_capability == HeatingSystemCapability.HEATING_AND_COOLING
        )
        assert out.heating_system_type == HeatingSystemType.FLOOR_HEATING

    def test_construction_with_int_enums(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=1,  # DIMMER
            output_usage=2,  # OUTDOORS
            mode=2,  # GRADUAL
            heating_system_capability=1,  # HEATING_ONLY
            heating_system_type=3,  # WALL_HEATING
            name="test",
            default_group=1,
            active_group=1,
            groups={1},
        )

        assert out.function == OutputFunction.DIMMER
        assert out.output_usage == OutputUsage.OUTDOORS
        assert out.mode == OutputMode.GRADUAL
        assert out.heating_system_capability == HeatingSystemCapability.HEATING_ONLY
        assert out.heating_system_type == HeatingSystemType.WALL_HEATING

    def test_all_output_functions(self):
        host, vdc, device, vdsd = _make_stack()
        for func in OutputFunction:
            out = Output(
                vdsd=vdsd,
                function=func,
                name="test",
                default_group=1,
                active_group=1,
                groups={1},
            )
            assert out.function == func

    def test_all_output_modes(self):
        host, vdc, device, vdsd = _make_stack()
        for mode in OutputMode:
            out = Output(
                vdsd=vdsd,
                mode=mode,
                name="test",
                default_group=1,
                active_group=1,
                groups={1},
            )
            assert out.mode == mode

    def test_all_output_usages(self):
        host, vdc, device, vdsd = _make_stack()
        for usage in OutputUsage:
            out = Output(
                vdsd=vdsd,
                output_usage=usage,
                name="test",
                default_group=1,
                active_group=1,
                groups={1},
            )
            assert out.output_usage == usage


# ===========================================================================
# Repr
# ===========================================================================


class TestOutputRepr:
    """Test __repr__."""

    def test_repr(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        r = repr(out)
        assert "Output(" in r
        assert "DIMMER" in r
        assert "Test Dimmer" in r


# ===========================================================================
# Settings mutators
# ===========================================================================


class TestOutputSettingsMutators:
    """Test writable settings via property setters."""

    def test_mode_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.mode = OutputMode.BINARY
        assert out.mode == OutputMode.BINARY

    def test_mode_setter_int(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.mode = 2
        assert out.mode == OutputMode.GRADUAL

    def test_active_group_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.active_group = 5
        assert out.active_group == 5

    def test_groups_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.groups = {1, 3, 5}
        assert out.groups == {1, 3, 5}

    def test_groups_returns_copy(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1, 2})
        g = out.groups
        g.add(99)
        assert 99 not in out.groups

    def test_add_group(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups=set())
        out.add_group(7)
        out.add_group(12)
        assert out.groups == {7, 12}

    def test_remove_group(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1, 2, 3})
        out.remove_group(2)
        assert out.groups == {1, 3}

    def test_remove_group_absent(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1})
        out.remove_group(99)
        assert out.groups == {1}

    def test_push_changes_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.push_changes = True
        assert out.push_changes is True

    def test_on_threshold_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.on_threshold = 33.5
        assert out.on_threshold == 33.5

    def test_on_threshold_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, on_threshold=50.0)
        out.on_threshold = None
        assert out.on_threshold is None

    def test_min_brightness_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.min_brightness = 5.0
        assert out.min_brightness == 5.0

    def test_dim_time_setters(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.dim_time_up = 100
        out.dim_time_down = 80
        out.dim_time_up_alt1 = 150
        out.dim_time_down_alt1 = 120
        out.dim_time_up_alt2 = 200
        out.dim_time_down_alt2 = 180
        assert out.dim_time_up == 100
        assert out.dim_time_down == 80
        assert out.dim_time_up_alt1 == 150
        assert out.dim_time_down_alt1 == 120
        assert out.dim_time_up_alt2 == 200
        assert out.dim_time_down_alt2 == 180

    def test_dim_time_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, dim_time_up=100)
        out.dim_time_up = None
        assert out.dim_time_up is None

    def test_heating_system_capability_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.heating_system_capability = HeatingSystemCapability.COOLING_ONLY
        assert out.heating_system_capability == HeatingSystemCapability.COOLING_ONLY

    def test_heating_system_capability_setter_int(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.heating_system_capability = 3
        assert (
            out.heating_system_capability == HeatingSystemCapability.HEATING_AND_COOLING
        )

    def test_heating_system_capability_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd,
            heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        )
        out.heating_system_capability = None
        assert out.heating_system_capability is None

    def test_heating_system_type_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.heating_system_type = HeatingSystemType.FLOOR_HEATING
        assert out.heating_system_type == HeatingSystemType.FLOOR_HEATING

    def test_heating_system_type_setter_int(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.heating_system_type = 4
        assert out.heating_system_type == HeatingSystemType.CONVECTOR_PASSIVE

    def test_heating_system_type_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd,
            heating_system_type=HeatingSystemType.RADIATOR,
        )
        out.heating_system_type = None
        assert out.heating_system_type is None

    def test_name_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.name = "New Name"
        assert out.name == "New Name"


# ===========================================================================
# State mutators
# ===========================================================================


class TestOutputStateMutators:
    """Test volatile state property setters."""

    def test_local_priority_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.local_priority = True
        assert out.local_priority is True

    def test_error_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.error = OutputError.LAMP_BROKEN
        assert out.error == OutputError.LAMP_BROKEN

    def test_error_setter_int(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.error = 3
        assert out.error == OutputError.OVERLOAD

    def test_all_error_values(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        for err in OutputError:
            out.error = err
            assert out.error == err


# ===========================================================================
# Description properties dict
# ===========================================================================


class TestOutputDescriptionProperties:
    """Test get_description_properties()."""

    def test_minimal(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        desc = out.get_description_properties()

        assert desc["function"] == int(OutputFunction.DIMMER)
        assert desc["outputUsage"] == int(OutputUsage.ROOM)
        assert desc["name"] == "Test Dimmer"
        assert desc["defaultGroup"] == 1
        assert desc["variableRamp"] is False
        assert "maxPower" not in desc
        assert "activeCoolingMode" not in desc

    def test_with_optional_fields(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            max_power=240.5,
            active_cooling_mode=True,
            variable_ramp=True,
            default_group=8,
            name="optional-test",
            active_group=1,
            groups={1},
        )
        desc = out.get_description_properties()

        assert desc["maxPower"] == 240.5
        assert desc["activeCoolingMode"] is True
        assert desc["variableRamp"] is True
        assert desc["defaultGroup"] == 8


# ===========================================================================
# Settings properties dict
# ===========================================================================


class TestOutputSettingsProperties:
    """Test get_settings_properties()."""

    def test_minimal(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)  # DIMMER function → auto-derives GRADUAL
        settings = out.get_settings_properties()

        assert settings["mode"] == int(OutputMode.GRADUAL)
        assert settings["activeGroup"] == 1
        assert settings["pushChanges"] is False
        assert settings["groups"] == {"1": True}
        assert "onThreshold" not in settings
        assert "minBrightness" not in settings

    def test_with_groups(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1, 3, 5})
        settings = out.get_settings_properties()

        assert "groups" in settings
        assert settings["groups"] == {"1": True, "3": True, "5": True}

    def test_with_all_optional_fields(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            mode=OutputMode.GRADUAL,
            active_group=2,
            name="settings-test",
            default_group=1,
            groups={2},
            push_changes=True,
            on_threshold=50.0,
            min_brightness=5.0,
            dim_time_up=100,
            dim_time_down=80,
            dim_time_up_alt1=150,
            dim_time_down_alt1=120,
            dim_time_up_alt2=200,
            dim_time_down_alt2=180,
            heating_system_capability=HeatingSystemCapability.HEATING_AND_COOLING,
            heating_system_type=HeatingSystemType.RADIATOR,
        )
        settings = out.get_settings_properties()

        assert settings["mode"] == int(OutputMode.GRADUAL)
        assert settings["activeGroup"] == 2
        assert settings["pushChanges"] is True
        assert settings["onThreshold"] == 50.0
        assert settings["minBrightness"] == 5.0
        assert settings["dimTimeUp"] == 100
        assert settings["dimTimeDown"] == 80
        assert settings["dimTimeUpAlt1"] == 150
        assert settings["dimTimeDownAlt1"] == 120
        assert settings["dimTimeUpAlt2"] == 200
        assert settings["dimTimeDownAlt2"] == 180
        assert settings["heatingSystemCapability"] == int(
            HeatingSystemCapability.HEATING_AND_COOLING
        )
        assert settings["heatingSystemType"] == int(HeatingSystemType.RADIATOR)


# ===========================================================================
# State properties dict
# ===========================================================================


class TestOutputStateProperties:
    """Test get_state_properties()."""

    def test_defaults(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        state = out.get_state_properties()

        assert state["localPriority"] is False
        assert state["error"] == int(OutputError.OK)

    def test_after_mutation(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.local_priority = True
        out.error = OutputError.SHORT_CIRCUIT

        state = out.get_state_properties()
        assert state["localPriority"] is True
        assert state["error"] == int(OutputError.SHORT_CIRCUIT)

    def test_output_state_includes_transition_time(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        state = out.get_state_properties()
        assert "transitionTime" in state
        assert isinstance(state["transitionTime"], float)
        assert state["transitionTime"] == 0.0  # default

    def test_apply_state_stores_transition_time(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({"transitionTime": 0.5})
        assert out.get_state_properties()["transitionTime"] == 0.5

    def test_transition_time_property_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.transition_time = 2.5
        assert out.get_state_properties()["transitionTime"] == 2.5

    def test_apply_state_transition_time_none_falls_back_to_zero(self):
        """Applying None value for transitionTime falls back to default."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        # Arrange: set to non-zero first
        out.apply_state({"transitionTime": 1.5})
        # Act: apply None value
        out.apply_state({"transitionTime": None})
        # Assert: falls back to default
        assert out.get_state_properties()["transitionTime"] == 0.0

    def test_output_state_includes_moving_state(self):
        """movingState defaults to 0 (idle)."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        state = out.get_state_properties()
        assert "movingState" in state
        assert state["movingState"] == 0

    def test_apply_state_stores_moving_state(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({"movingState": 1})
        assert out.get_state_properties()["movingState"] == 1

    def test_moving_state_property_setter(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.moving_state = -1
        assert out.get_state_properties()["movingState"] == -1

    def test_moving_state_not_in_property_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.moving_state = 1
        tree = out.get_property_tree()
        # movingState must not appear in the property tree (it is volatile)
        assert "movingState" not in tree

    def test_apply_state_moving_state_none_falls_back_to_zero(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({"movingState": 1})
        out.apply_state({"movingState": None})
        assert out.get_state_properties()["movingState"] == 0


# ===========================================================================
# apply_settings
# ===========================================================================


class TestOutputApplySettings:
    """Test apply_settings() from vdSM setProperty."""

    def test_apply_mode(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"mode": 1})
        assert out.mode == OutputMode.BINARY

    def test_apply_active_group(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"activeGroup": 5})
        assert out.active_group == 5

    def test_apply_push_changes(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"pushChanges": True})
        assert out.push_changes is True

    def test_apply_groups_add(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"groups": {"1": True, "3": True, "5": True}})
        assert out.groups == {1, 3, 5}

    def test_apply_groups_remove(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1, 2, 3})
        out.apply_settings({"groups": {"2": False}})
        assert out.groups == {1, 3}

    def test_apply_groups_mixed(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={1, 2})
        out.apply_settings({"groups": {"2": False, "5": True}})
        assert out.groups == {1, 5}

    def test_apply_on_threshold(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"onThreshold": 42.0})
        assert out.on_threshold == 42.0

    def test_apply_on_threshold_none(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, on_threshold=50.0)
        out.apply_settings({"onThreshold": None})
        assert out.on_threshold is None

    def test_apply_min_brightness(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"minBrightness": 8.0})
        assert out.min_brightness == 8.0

    def test_apply_dim_times(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings(
            {
                "dimTimeUp": 100,
                "dimTimeDown": 80,
                "dimTimeUpAlt1": 150,
                "dimTimeDownAlt1": 120,
                "dimTimeUpAlt2": 200,
                "dimTimeDownAlt2": 180,
            }
        )
        assert out.dim_time_up == 100
        assert out.dim_time_down == 80
        assert out.dim_time_up_alt1 == 150
        assert out.dim_time_down_alt1 == 120
        assert out.dim_time_up_alt2 == 200
        assert out.dim_time_down_alt2 == 180

    def test_apply_dim_time_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, dim_time_up=100)
        out.apply_settings({"dimTimeUp": None})
        assert out.dim_time_up is None

    def test_apply_heating_system_capability(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"heatingSystemCapability": 2})
        assert out.heating_system_capability == HeatingSystemCapability.COOLING_ONLY

    def test_apply_heating_system_capability_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd,
            heating_system_capability=HeatingSystemCapability.HEATING_ONLY,
        )
        out.apply_settings({"heatingSystemCapability": None})
        assert out.heating_system_capability is None

    def test_apply_heating_system_type(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"heatingSystemType": 5})
        assert out.heating_system_type == HeatingSystemType.CONVECTOR_ACTIVE

    def test_apply_heating_system_type_reset(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd,
            heating_system_type=HeatingSystemType.RADIATOR,
        )
        out.apply_settings({"heatingSystemType": None})
        assert out.heating_system_type is None

    def test_apply_unknown_keys_now_stored(self):
        """Unknown keys are now stored (not silently dropped) — known key still applied."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"unknownKey": 42, "mode": 1})
        assert out.mode == OutputMode.BINARY
        # Unknown key must now be accessible via get_settings_properties.
        s = out.get_settings_properties()
        assert s["unknownKey"] == 42

    def test_apply_settings_stores_unknown_key(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"someUnknownKey": 42.0, "anotherKey": "hello"})
        s = out.get_settings_properties()
        assert s["someUnknownKey"] == 42.0
        assert s["anotherKey"] == "hello"

    def test_apply_settings_unknown_key_does_not_shadow_known(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"mode": 2, "someUnknownKey": 99})
        s = out.get_settings_properties()
        assert s["mode"] == 2  # known field handled normally
        assert s["someUnknownKey"] == 99  # unknown field stored

    def test_extra_settings_persisted_in_property_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"customField": "value"})
        tree = out.get_property_tree()
        assert tree.get("customField") == "value"

    def test_extra_settings_absent_when_empty(self):
        """No extra keys appear in settings when nothing unknown was stored."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        s = out.get_settings_properties()
        assert "someUnknownKey" not in s

    def test_extra_settings_cumulative_across_calls(self):
        """Successive apply_settings calls accumulate extra settings."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"firstKey": 1})
        out.apply_settings({"secondKey": 2})
        s = out.get_settings_properties()
        assert s["firstKey"] == 1
        assert s["secondKey"] == 2

    def test_extra_settings_round_trip(self):
        """Extra settings survive a get_property_tree / _apply_state round-trip."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings({"customField": "value", "numericExtra": 3.14})
        tree = out.get_property_tree()

        _, _, _, vdsd2 = _make_stack()
        out2 = _make_output(vdsd2)
        out2._apply_state(tree)

        s = out2.get_settings_properties()
        assert s["customField"] == "value"
        assert s["numericExtra"] == pytest.approx(3.14)

    def test_apply_empty_dict(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd
        )  # DIMMER → auto-derives GRADUAL; empty dict leaves it unchanged
        out.apply_settings({})
        assert out.mode == OutputMode.GRADUAL

    def test_apply_multiple_settings_at_once(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings(
            {
                "mode": 2,
                "activeGroup": 3,
                "pushChanges": True,
                "onThreshold": 30.0,
                "minBrightness": 5.0,
            }
        )
        assert out.mode == OutputMode.GRADUAL
        assert out.active_group == 3
        assert out.push_changes is True
        assert out.on_threshold == 30.0
        assert out.min_brightness == 5.0


# ===========================================================================
# apply_state
# ===========================================================================


class TestOutputApplyState:
    """Test apply_state() from vdSM setProperty."""

    def test_apply_local_priority(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({"localPriority": True})
        assert out.local_priority is True

    def test_apply_state_ignores_error(self):
        """error is read-only from the vdSM perspective."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({"error": 3})
        # error should NOT be changed by apply_state
        assert out.error == OutputError.OK

    def test_apply_state_empty(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_state({})
        assert out.local_priority is False


# ===========================================================================
# Property tree (persistence)
# ===========================================================================


class TestOutputPropertyTree:
    """Test get_property_tree() and _apply_state() round-trip."""

    def test_minimal_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        tree = out.get_property_tree()

        assert tree["function"] == int(OutputFunction.DIMMER)
        assert tree["outputUsage"] == int(OutputUsage.ROOM)
        assert tree["name"] == "Test Dimmer"
        assert tree["defaultGroup"] == 1
        assert tree["variableRamp"] is False
        assert tree["mode"] == int(OutputMode.GRADUAL)  # DIMMER → auto-derives GRADUAL
        assert tree["activeGroup"] == 1
        assert tree["pushChanges"] is False
        assert "maxPower" not in tree
        assert "activeCoolingMode" not in tree
        assert tree["groups"] == [1]

    def test_full_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.FULL_COLOR_DIMMER,
            output_usage=OutputUsage.USER,
            name="Full Colour",
            default_group=1,
            variable_ramp=True,
            max_power=300.0,
            active_cooling_mode=True,
            mode=OutputMode.GRADUAL,
            active_group=2,
            groups={1, 4, 8},
            push_changes=True,
            on_threshold=50.0,
            min_brightness=10.0,
            dim_time_up=100,
            dim_time_down=80,
            dim_time_up_alt1=150,
            dim_time_down_alt1=120,
            dim_time_up_alt2=200,
            dim_time_down_alt2=180,
            heating_system_capability=HeatingSystemCapability.HEATING_AND_COOLING,
            heating_system_type=HeatingSystemType.FLOOR_HEATING,
        )
        tree = out.get_property_tree()

        assert tree["function"] == int(OutputFunction.FULL_COLOR_DIMMER)
        assert tree["outputUsage"] == int(OutputUsage.USER)
        assert tree["name"] == "Full Colour"
        assert tree["defaultGroup"] == 1
        assert tree["variableRamp"] is True
        assert tree["maxPower"] == 300.0
        assert tree["activeCoolingMode"] is True
        assert tree["mode"] == int(OutputMode.GRADUAL)
        assert tree["activeGroup"] == 2
        assert tree["groups"] == [1, 4, 8]
        assert tree["pushChanges"] is True
        assert tree["onThreshold"] == 50.0
        assert tree["minBrightness"] == 10.0
        assert tree["dimTimeUp"] == 100
        assert tree["dimTimeDown"] == 80
        assert tree["dimTimeUpAlt1"] == 150
        assert tree["dimTimeDownAlt1"] == 120
        assert tree["dimTimeUpAlt2"] == 200
        assert tree["dimTimeDownAlt2"] == 180
        assert tree["heatingSystemCapability"] == int(
            HeatingSystemCapability.HEATING_AND_COOLING
        )
        assert tree["heatingSystemType"] == int(HeatingSystemType.FLOOR_HEATING)

    def test_state_not_in_tree(self):
        """Volatile state must NOT appear in the property tree."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.local_priority = True
        out.error = OutputError.SHORT_CIRCUIT
        out.transition_time = 1.5
        out.moving_state = 1
        tree = out.get_property_tree()

        assert "localPriority" not in tree
        assert "error" not in tree
        assert "transitionTime" not in tree
        assert "movingState" not in tree

    def test_round_trip(self):
        """Serialize → _apply_state → verify all properties match."""
        host, vdc, device, vdsd = _make_stack()
        original = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER_COLOR_TEMP,
            output_usage=OutputUsage.OUTDOORS,
            name="Colour Temp",
            default_group=3,
            variable_ramp=True,
            max_power=60.0,
            active_cooling_mode=False,
            mode=OutputMode.GRADUAL,
            active_group=3,
            groups={2, 7, 15},
            push_changes=True,
            on_threshold=25.0,
            min_brightness=3.0,
            dim_time_up=50,
            dim_time_down=40,
            dim_time_up_alt1=75,
            dim_time_down_alt1=60,
            dim_time_up_alt2=100,
            dim_time_down_alt2=90,
            heating_system_capability=HeatingSystemCapability.COOLING_ONLY,
            heating_system_type=HeatingSystemType.CONVECTOR_ACTIVE,
        )
        tree = original.get_property_tree()

        # Restore into a fresh Output.
        restored = Output(
            vdsd=vdsd, name="restored", default_group=0, active_group=0, groups=set()
        )
        restored._apply_state(tree)

        assert restored.function == original.function
        assert restored.output_usage == original.output_usage
        assert restored.name == original.name
        assert restored.default_group == original.default_group
        assert restored.variable_ramp == original.variable_ramp
        assert restored.max_power == original.max_power
        assert restored.active_cooling_mode == original.active_cooling_mode
        assert restored.mode == original.mode
        assert restored.active_group == original.active_group
        assert restored.groups == original.groups
        assert restored.push_changes == original.push_changes
        assert restored.on_threshold == original.on_threshold
        assert restored.min_brightness == original.min_brightness
        assert restored.dim_time_up == original.dim_time_up
        assert restored.dim_time_down == original.dim_time_down
        assert restored.dim_time_up_alt1 == original.dim_time_up_alt1
        assert restored.dim_time_down_alt1 == original.dim_time_down_alt1
        assert restored.dim_time_up_alt2 == original.dim_time_up_alt2
        assert restored.dim_time_down_alt2 == original.dim_time_down_alt2
        assert restored.heating_system_capability == original.heating_system_capability
        assert restored.heating_system_type == original.heating_system_type

    def test_groups_sorted_in_persistence(self):
        """Verify groups are stored as sorted list for determinism."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={30, 5, 15, 1})
        tree = out.get_property_tree()
        assert tree["groups"] == [1, 5, 15, 30]

    def test_apply_state_groups_from_dict(self):
        """_apply_state also handles groups in dict format."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd, name="tmp", default_group=0, active_group=0, groups=set()
        )
        out._apply_state({"groups": {"1": True, "5": True, "10": False}})
        assert out.groups == {1, 5}

    def test_apply_state_partial(self):
        """_apply_state with a subset of keys only modifies those."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            name="Original",
            mode=OutputMode.GRADUAL,
            default_group=1,
            active_group=1,
            groups={1},
        )
        out._apply_state({"name": "Changed"})
        assert out.name == "Changed"
        assert out.function == OutputFunction.DIMMER
        assert out.mode == OutputMode.GRADUAL


# ===========================================================================
# Vdsd integration
# ===========================================================================


class TestVdsdOutputIntegration:
    """Test Output integration with Vdsd."""

    def test_set_output(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        assert vdsd.output is out

    def test_set_output_replaces(self):
        host, vdc, device, vdsd = _make_stack()
        out1 = _make_output(vdsd, name="First")
        out2 = _make_output(vdsd, name="Second")
        vdsd.set_output(out1)
        vdsd.set_output(out2)
        assert vdsd.output is out2

    def test_set_output_wrong_vdsd(self):
        host, vdc, device, vdsd = _make_stack()
        other_device = Device(
            vdc=vdc,
            dsuid=DsUid.from_name_in_space("other", DsUidNamespace.VDC),
        )
        other_vdsd = Vdsd(
            device=other_device,
            primary_group=ColorGroup.BLACK,
            name="Other",
            model="Test",
        )
        other_device.add_vdsd(other_vdsd)

        out = Output(
            vdsd=other_vdsd, name="out", default_group=1, active_group=1, groups={1}
        )
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd.set_output(out)

    def test_remove_output(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        removed = vdsd.remove_output()
        assert removed is out
        assert vdsd.output is None

    def test_remove_output_none(self):
        host, vdc, device, vdsd = _make_stack()
        assert vdsd.remove_output() is None

    def test_output_none_by_default(self):
        host, vdc, device, vdsd = _make_stack()
        assert vdsd.output is None

    def test_output_in_get_properties(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        props = vdsd.get_properties()

        assert "outputDescription" in props
        assert "outputSettings" in props
        assert "outputState" in props
        assert props["outputDescription"]["function"] == int(OutputFunction.DIMMER)

    def test_no_output_in_get_properties(self):
        host, vdc, device, vdsd = _make_stack()
        props = vdsd.get_properties()

        assert "outputDescription" not in props
        assert "outputSettings" not in props
        assert "outputState" not in props

    def test_output_in_property_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        tree = vdsd.get_property_tree()

        assert "output" in tree
        assert tree["output"]["function"] == int(OutputFunction.DIMMER)
        assert tree["output"]["name"] == "Test Dimmer"

    def test_no_output_in_property_tree(self):
        host, vdc, device, vdsd = _make_stack()
        tree = vdsd.get_property_tree()
        assert "output" not in tree

    def test_output_restore_from_state(self):
        """Persist via property tree → restore via _apply_state."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="Blind Motor",
            mode=OutputMode.GRADUAL,
            default_group=9,
            active_group=9,
            groups={9},
        )
        vdsd.set_output(out)

        tree = vdsd.get_property_tree()

        # Restore into a fresh vdSD.
        host2, vdc2, device2, vdsd2 = _make_stack()
        vdsd2._apply_state(tree)

        assert vdsd2.output is not None
        assert vdsd2.output.function == OutputFunction.POSITIONAL
        assert vdsd2.output.name == "Blind Motor"
        assert vdsd2.output.mode == OutputMode.GRADUAL
        assert vdsd2.output.active_group == 9
        assert vdsd2.output.groups == {9}

    def test_output_restore_merges_with_existing(self):
        """If output already exists, _apply_state updates it."""
        host, vdc, device, vdsd = _make_stack()
        existing = Output(
            vdsd=vdsd, name="Existing", default_group=1, active_group=1, groups={1}
        )
        vdsd.set_output(existing)

        vdsd._apply_state(
            {
                "output": {
                    "function": int(OutputFunction.BIPOLAR),
                    "name": "Updated",
                }
            }
        )

        # Should be the same object, updated.
        assert vdsd.output is existing
        assert vdsd.output.name == "Updated"
        assert vdsd.output.function == OutputFunction.BIPOLAR


# ===========================================================================
# Session management
# ===========================================================================


class TestOutputSessionManagement:
    """Test start_session / stop_session."""

    def test_start_session(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        session = _make_mock_session()
        out.start_session(session)
        assert out._session is session

    def test_stop_session(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        session = _make_mock_session()
        out.start_session(session)
        out.stop_session()
        assert out._session is None

    def test_set_output_while_announced(self):
        """Setting output on an already-announced vdSD starts session."""
        host, vdc, device, vdsd = _make_stack()
        session = _make_mock_session()
        # Simulate announced state.
        vdsd._announced = True
        vdsd._session = session

        out = _make_output(vdsd)
        vdsd.set_output(out)
        assert out._session is session

    def test_remove_output_stops_session(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        session = _make_mock_session()
        out.start_session(session)
        vdsd.set_output(out)
        vdsd.remove_output()
        assert out._session is None


# ===========================================================================
# VdcHost setProperty integration
# ===========================================================================


class TestVdcHostOutputSetProperty:
    """Test VdcHost._apply_vdsd_set_property for outputSettings/outputState."""

    def test_apply_output_settings(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)

        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputSettings": {"mode": 2, "pushChanges": True},
            },
        )

        assert out.mode == OutputMode.GRADUAL
        assert out.push_changes is True

    def test_apply_output_state(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)

        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputState": {"localPriority": True},
            },
        )

        assert out.local_priority is True

    def test_apply_output_settings_no_output(self):
        """Settings for non-existing output should not crash."""
        host, vdc, device, vdsd = _make_stack()
        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputSettings": {"mode": 1},
            },
        )

    def test_apply_output_state_no_output(self):
        """State for non-existing output should not crash."""
        host, vdc, device, vdsd = _make_stack()
        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputState": {"localPriority": True},
            },
        )

    def test_apply_output_settings_not_dict(self):
        """Non-dict outputSettings should be silently ignored."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(
            vdsd
        )  # DIMMER → auto-derives GRADUAL; invalid settings leave it unchanged
        vdsd.set_output(out)
        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputSettings": "invalid",
            },
        )
        assert out.mode == OutputMode.GRADUAL

    def test_apply_output_state_not_dict(self):
        """Non-dict outputState should be silently ignored."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        host._apply_vdsd_set_property(
            vdsd,
            {
                "outputState": "invalid",
            },
        )
        assert out.local_priority is False

    def test_mixed_set_property(self):
        """Verify output + other settings applied together."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)

        host._apply_vdsd_set_property(
            vdsd,
            {
                "name": "Renamed",
                "zoneID": 42,
                "outputSettings": {"mode": 1},
                "outputState": {"localPriority": True},
            },
        )

        assert vdsd.name == "Renamed"
        assert vdsd.zone_id == 42
        assert out.mode == OutputMode.BINARY
        assert out.local_priority is True


# ===========================================================================
# Auto-save trigger
# ===========================================================================


class TestOutputAutoSave:
    """Verify that settings changes trigger auto-save via the Device chain."""

    def _setup(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        vdsd.set_output(out)
        return host, vdc, device, vdsd, out

    def test_mode_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.mode = OutputMode.BINARY
        device._schedule_auto_save.assert_called()

    def test_active_group_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.active_group = 5
        device._schedule_auto_save.assert_called()

    def test_groups_setter_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.groups = {1, 2, 3}
        device._schedule_auto_save.assert_called()

    def test_add_group_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.add_group(7)
        device._schedule_auto_save.assert_called()

    def test_remove_group_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.remove_group(7)
        device._schedule_auto_save.assert_called()

    def test_push_changes_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.push_changes = True
        device._schedule_auto_save.assert_called()

    def test_name_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.name = "New Name"
        device._schedule_auto_save.assert_called()

    def test_on_threshold_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.on_threshold = 50.0
        device._schedule_auto_save.assert_called()

    def test_min_brightness_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.min_brightness = 5.0
        device._schedule_auto_save.assert_called()

    def test_dim_time_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.dim_time_up = 100
        device._schedule_auto_save.assert_called()

    def test_heating_capability_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.heating_system_capability = HeatingSystemCapability.HEATING_ONLY
        device._schedule_auto_save.assert_called()

    def test_heating_type_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.heating_system_type = HeatingSystemType.RADIATOR
        device._schedule_auto_save.assert_called()

    def test_apply_settings_triggers_auto_save(self):
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.apply_settings({"mode": 2})
        device._schedule_auto_save.assert_called()

    def test_state_does_not_trigger_auto_save(self):
        """Volatile state changes must NOT trigger auto-save."""
        host, vdc, device, vdsd, out = self._setup()
        device._schedule_auto_save = MagicMock()
        out.local_priority = True
        out.error = OutputError.OVERLOAD
        device._schedule_auto_save.assert_not_called()


# ===========================================================================
# __init__.py export
# ===========================================================================


class TestOutputExport:
    """Verify Output is accessible from the top-level package."""

    def test_import_output(self):
        from pydsvdcapi import Output

        assert Output is not None

    def test_output_is_same_class(self):
        from pydsvdcapi import Output as PkgOutput

        assert PkgOutput is Output


# ===========================================================================
# Edge cases
# ===========================================================================


class TestOutputEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_groups_returns_empty_dict(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups=set())
        settings = out.get_settings_properties()
        assert settings["groups"] == {}

    def test_empty_groups_not_in_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups=set())
        tree = out.get_property_tree()
        assert "groups" not in tree

    def test_groups_sorted_in_tree(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={10, 3, 7, 1})
        tree = out.get_property_tree()
        assert tree["groups"] == [1, 3, 7, 10]

    def test_groups_sorted_in_settings(self):
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, groups={10, 3, 7, 1})
        settings = out.get_settings_properties()
        keys = list(settings["groups"].keys())
        assert keys == ["1", "3", "7", "10"]

    def test_on_off_output(self):
        """Basic on/off output (relay, socket)."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.ON_OFF,
            mode=OutputMode.BINARY,
            name="Relay",
            default_group=1,
            active_group=1,
            groups={1},
        )
        assert out.function == OutputFunction.ON_OFF
        assert out.mode == OutputMode.BINARY

    def test_bipolar_output(self):
        """Bipolar output (e.g. ventilation direction)."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.BIPOLAR,
            name="Ventilation",
            default_group=1,
            active_group=1,
            groups={1},
        )
        assert out.function == OutputFunction.BIPOLAR

    def test_internally_controlled_output(self):
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.INTERNALLY_CONTROLLED,
            name="Auto",
            default_group=1,
            active_group=1,
            groups={1},
        )
        assert out.function == OutputFunction.INTERNALLY_CONTROLLED

    def test_climate_output(self):
        """Climate control output with heating settings."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.ON_OFF,
            name="FCU Valve",
            default_group=1,
            active_group=1,
            groups={1},
            heating_system_capability=HeatingSystemCapability.HEATING_AND_COOLING,
            heating_system_type=HeatingSystemType.CONVECTOR_PASSIVE,
            active_cooling_mode=True,
        )
        desc = out.get_description_properties()
        settings = out.get_settings_properties()

        assert desc["activeCoolingMode"] is True
        assert settings["heatingSystemCapability"] == int(
            HeatingSystemCapability.HEATING_AND_COOLING
        )
        assert settings["heatingSystemType"] == int(HeatingSystemType.CONVECTOR_PASSIVE)

    def test_full_round_trip_through_vdsd(self):
        """Complete persistence round-trip through the vdSD."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            output_usage=OutputUsage.ROOM,
            name="Living Room Dimmer",
            default_group=1,
            mode=OutputMode.GRADUAL,
            active_group=1,
            groups={1},
            push_changes=True,
            dim_time_up=50,
            dim_time_down=40,
        )
        vdsd.set_output(out)

        # Persist.
        tree = vdsd.get_property_tree()

        # Restore.
        host2, vdc2, device2, vdsd2 = _make_stack()
        vdsd2._apply_state(tree)

        assert vdsd2.output is not None
        r = vdsd2.output
        assert r.function == OutputFunction.DIMMER
        assert r.output_usage == OutputUsage.ROOM
        assert r.name == "Living Room Dimmer"
        assert r.default_group == 1
        assert r.mode == OutputMode.GRADUAL
        assert r.active_group == 1
        assert r.groups == {1}
        assert r.push_changes is True
        assert r.dim_time_up == 50
        assert r.dim_time_down == 40
        # Volatile state should be defaults.
        assert r.local_priority is False
        assert r.error == OutputError.OK


# ===========================================================================
# Scene support
# ===========================================================================


class TestOutputScenes:
    """Tests for scene table management on Output."""

    def test_default_scene_table_contains_standard_entries(self):
        """After construction all 128 scenes (minus non-value scenes) have entries."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.output import _NON_VALUE_SCENES

        for nr in range(128):
            if nr in _NON_VALUE_SCENES:
                assert out.get_scene(nr) is None, (
                    f"Non-value scene {nr} should not be in table"
                )
            else:
                entry = out.get_scene(nr)
                assert entry is not None, f"Scene {nr} missing from default table"
                for idx in out.channels:
                    assert idx in entry.get("channels", {}), (
                        f"Channel {idx} missing in scene {nr}"
                    )

    def test_off_scene_defaults_to_min(self):
        """Off scenes should default primary channel to min_value."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        entry = out.get_scene(int(SceneNumber.PRESET_0))
        assert entry is not None
        assert entry["dontCare"] is False
        ch_vals = entry["channels"]
        # Brightness channel at index 0.
        assert ch_vals[0]["value"] == 0.0
        assert ch_vals[0]["dontCare"] is False

    def test_on_scene_defaults_to_max(self):
        """On scenes should default primary channel to max_value."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        entry = out.get_scene(int(SceneNumber.PRESET_1))
        assert entry is not None
        assert entry["dontCare"] is False
        ch_vals = entry["channels"]
        assert ch_vals[0]["value"] == 100.0  # brightness max
        assert ch_vals[0]["dontCare"] is False

    def test_non_standard_scene_defaults_to_dont_care(self):
        """Scenes not in OFF/ON/medium-preset sets default to global dontCare=True."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        # SUN_PROTECTION (56) is not off, on, or a medium-preset scene.
        entry = out.get_scene(int(SceneNumber.SUN_PROTECTION))
        assert entry is not None
        assert entry["dontCare"] is True

    def test_medium_preset_scene_defaults(self):
        """Medium preset scenes (17-31) have dontCare=False with fractional values."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        # PRESET_2 = scene 17 = 75 % of max (brightness: 0-100 → 75.0)
        entry = out.get_scene(int(SceneNumber.PRESET_2))
        assert entry is not None
        assert entry["dontCare"] is False
        assert entry["channels"][0]["value"] == pytest.approx(75.0)
        assert entry["channels"][0]["dontCare"] is False

        # PRESET_3 = scene 18 = 50 %
        entry3 = out.get_scene(int(SceneNumber.PRESET_3))
        assert entry3 is not None
        assert entry3["channels"][0]["value"] == pytest.approx(50.0)

        # PRESET_4 = scene 19 = 25 %
        entry4 = out.get_scene(int(SceneNumber.PRESET_4))
        assert entry4 is not None
        assert entry4["channels"][0]["value"] == pytest.approx(25.0)

    def test_call_scene_applies_values(self):
        """call_scene should apply stored channel values."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        # PRESET_1 = on → brightness = 100.
        ch = out.get_channel(0)
        assert ch is not None
        # Channel starts at None; calling on-scene should set it.
        out.call_scene(int(SceneNumber.PRESET_1))
        assert ch.value == 100.0

    def test_call_scene_respects_global_dont_care(self):
        """If scene has global dontCare, call_scene does nothing."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        # SUN_PROTECTION (56) is not off/on/medium → dontCare=True.
        out.call_scene(int(SceneNumber.SUN_PROTECTION))
        assert ch.value == 42.0  # unchanged

    def test_call_scene_blocked_by_local_priority(self):
        """Local priority blocks scene unless force or ignoreLP."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()
        out.local_priority = True

        # Normal call — blocked.
        out.call_scene(int(SceneNumber.PRESET_0))
        assert ch.value == 42.0

        # Force call — overrides.
        out.call_scene(int(SceneNumber.PRESET_0), force=True)
        assert ch.value == 0.0

    def test_call_scene_ignore_local_priority_flag(self):
        """Alarm scenes with ignoreLocalPriority override LP."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()
        out.local_priority = True

        # PANIC has ignoreLocalPriority=True by default.
        entry = out.get_scene(int(SceneNumber.PANIC))
        assert entry is not None
        assert entry["ignoreLocalPriority"] is True
        # But PANIC also defaults to dontCare for a standard dimmer.
        # Manually clear dontCare so we can test LP bypass.
        entry["dontCare"] = False
        entry["channels"][0]["dontCare"] = False
        entry["channels"][0]["value"] = 0.0

        out.call_scene(int(SceneNumber.PANIC))
        assert ch.value == 0.0  # applied despite LP

    def test_call_scene_respects_channel_dont_care(self):
        """Per-channel dontCare should skip that channel."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER_COLOR_TEMP)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        # Set initial values.
        brightness = out.get_channel(0)
        colortemp = out.get_channel(1)
        brightness.set_value_from_vdsm(50.0)
        brightness.confirm_applied()
        colortemp.set_value_from_vdsm(500.0)
        colortemp.confirm_applied()

        # Modify PRESET_1: set colortemp dontCare.
        entry = out.get_scene(int(SceneNumber.PRESET_1))
        entry["channels"][1]["dontCare"] = True

        out.call_scene(int(SceneNumber.PRESET_1))
        assert brightness.value == 100.0  # applied
        assert colortemp.value == 500.0  # unchanged (dontCare)

    def test_save_scene_captures_current_values(self):
        """save_scene should store current channel values."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(73.0)
        ch.confirm_applied()

        out.save_scene(5)  # PRESET_1

        entry = out.get_scene(5)
        assert entry is not None
        assert entry["dontCare"] is False
        assert entry["channels"][0]["value"] == 73.0
        assert entry["channels"][0]["dontCare"] is False

    def test_undo_scene_restores_previous_values(self):
        """undo_scene should restore the snapshot from before call."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        out.call_scene(int(SceneNumber.PRESET_0))
        assert ch.value == 0.0

        out.undo_scene(int(SceneNumber.PRESET_0))
        assert ch.value == 42.0

    def test_undo_scene_ignores_mismatch(self):
        """undo_scene with non-matching scene_nr does nothing."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import SceneNumber

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        out.call_scene(int(SceneNumber.PRESET_0))
        assert ch.value == 0.0

        # Undo with wrong scene number.
        out.undo_scene(int(SceneNumber.PRESET_1))
        assert ch.value == 0.0  # unchanged

    def test_scenes_persist_and_restore(self):
        """Scene data should survive a get_property_tree / _apply_state
        round-trip."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        # Modify a scene.
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(77.0)
        ch.confirm_applied()
        out.save_scene(5)

        tree = out.get_property_tree()
        assert "scenes" in tree

        # Restore into a fresh output.
        _, _, _, vdsd2 = _make_stack()
        out2 = _make_output(vdsd2, function=OutputFunction.DIMMER)
        vdsd2.set_output(out2)
        out2._apply_state(tree)

        entry = out2.get_scene(5)
        assert entry is not None
        assert entry["dontCare"] is False
        assert entry["channels"][0]["value"] == 77.0

        # All 128 scenes (minus non-value) should still be present.
        from pydsvdcapi.output import _NON_VALUE_SCENES

        for nr in range(128):
            if nr not in _NON_VALUE_SCENES:
                assert out2.get_scene(nr) is not None, (
                    f"Scene {nr} missing after restore"
                )

    def test_scenes_restore_upgrades_old_yaml(self):
        """Restoring a YAML that only has a subset of scenes (as written by
        older code iterating SceneNumber enum) must backfill the missing
        scenes with defaults so all 128 entries are present."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        # Simulate an old YAML: only include scenes that were in the
        # SceneNumber enum (scene 0 and scene 1 as representatives).
        from pydsvdcapi.output import _NON_VALUE_SCENES

        old_tree = out.get_property_tree()
        # Strip all scenes except 0 and 1 to mimic old code output.
        old_tree["scenes"] = {
            k: v for k, v in old_tree["scenes"].items() if k in ("0", "1")
        }

        _, _, _, vdsd2 = _make_stack()
        out2 = _make_output(vdsd2, function=OutputFunction.DIMMER)
        vdsd2.set_output(out2)
        out2._apply_state(old_tree)

        # Persisted scenes should be restored correctly.
        assert out2.get_scene(0)["dontCare"] is False  # PRESET_0 = off
        assert out2.get_scene(1)["dontCare"] is False  # PRESET_1 = on

        # All other scenes must have been backfilled with defaults.
        for nr in range(128):
            if nr not in _NON_VALUE_SCENES:
                assert out2.get_scene(nr) is not None, (
                    f"Scene {nr} missing after upgrade restore"
                )

    def test_scenes_exposed_in_vdsd_properties(self):
        """vdsd.get_properties() should include scenes."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        props = vdsd.get_properties()
        assert "scenes" in props
        scenes = props["scenes"]
        # Should have scene entries keyed by string number.
        assert "0" in scenes
        assert "5" in scenes
        # Each scene should have channels keyed by channel type.
        scene_0 = scenes["0"]
        assert "dontCare" in scene_0
        assert "ignoreLocalPriority" in scene_0
        assert "effect" in scene_0
        assert "channels" in scene_0

    def test_apply_scenes_from_vdsm(self):
        """apply_scenes should update scene values from API format."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        from pydsvdcapi.enums import OutputChannelType

        # API format: keyed by scene number (str), channels by type (str).
        scene_data = {
            "5": {
                "dontCare": False,
                "ignoreLocalPriority": True,
                "effect": 2,
                "channels": {
                    str(int(OutputChannelType.BRIGHTNESS)): {
                        "value": 66.0,
                        "dontCare": False,
                    },
                },
            }
        }
        out.apply_scenes(scene_data)

        entry = out.get_scene(5)
        assert entry is not None
        assert entry["dontCare"] is False
        assert entry["ignoreLocalPriority"] is True
        assert entry["effect"] == 2
        assert entry["channels"][0]["value"] == 66.0

    def test_add_channel_updates_scenes(self):
        """Adding a channel should add entries in all existing scenes."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.POSITIONAL)
        vdsd.set_output(out)

        from pydsvdcapi.enums import OutputChannelType

        # POSITIONAL has no auto-created channels.
        assert len(out.channels) == 0
        assert len(out._scenes) > 0  # defaults still generated

        # Add a channel.
        out.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)

        # All scenes should now have the new channel.
        for nr, entry in out._scenes.items():
            assert 0 in entry.get("channels", {}), (
                f"Scene {nr} missing channel 0 after add"
            )


class TestVdcHostSceneDispatch:
    """Tests for VdcHost scene notification dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_call_scene(self):
        """callScene notification routes to output.call_scene."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0  # PRESET_0 (off)

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert ch.value == 0.0

    @pytest.mark.asyncio
    async def test_dispatch_save_scene(self):
        """saveScene notification routes to output.save_scene."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(88.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SAVE_SCENE
        msg.vdsm_send_save_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_save_scene.scene = 5

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        entry = out.get_scene(5)
        assert entry["channels"][0]["value"] == 88.0

    @pytest.mark.asyncio
    async def test_dispatch_undo_scene(self):
        """undoScene notification routes to output.undo_scene."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        # Call scene to set up undo state.
        out.call_scene(0)
        assert ch.value == 0.0

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_UNDO_SCENE
        msg.vdsm_send_undo_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_undo_scene.scene = 0

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert ch.value == 42.0

    @pytest.mark.asyncio
    async def test_dispatch_set_local_priority(self):
        """setLocalPriority sets LP when scene is not dontCare."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        assert out.local_priority is False

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_LOCAL_PRIO
        msg.vdsm_send_set_local_prio.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_local_prio.scene = 0  # PRESET_0 is not dontCare

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert out.local_priority is True

    @pytest.mark.asyncio
    async def test_dispatch_set_local_priority_skips_dontcare(self):
        """setLocalPriority does NOT set LP when scene IS dontCare."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        from pydsvdcapi.enums import SceneNumber

        assert out.local_priority is False

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_LOCAL_PRIO
        msg.vdsm_send_set_local_prio.dSUID.append(str(vdsd.dsuid))
        # SUN_PROTECTION (56) is not off/on/medium → dontCare=True.
        msg.vdsm_send_set_local_prio.scene = int(SceneNumber.SUN_PROTECTION)

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert out.local_priority is False

    @pytest.mark.asyncio
    async def test_dispatch_call_min_scene(self):
        """callMinScene sets min-on when device is off."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        ch = out.get_channel(0)
        # Channel starts at None; init to 0 to simulate 'off'.
        ch.set_value_from_vdsm(0.0)
        ch.confirm_applied()
        assert ch.value == 0.0  # off

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_MIN_SCENE
        msg.vdsm_send_call_min_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_min_scene.scene = 0  # PRESET_0 not dontCare

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        # Should be set to min_on value (min + resolution).
        assert ch.value > 0.0

    @pytest.mark.asyncio
    async def test_set_property_scenes(self):
        """setProperty with scenes key routes to output.apply_scenes."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        from pydsvdcapi.enums import OutputChannelType
        from pydsvdcapi.property_handling import dict_to_elements

        scene_data = {
            "scenes": {
                "5": {
                    "dontCare": False,
                    "channels": {
                        str(int(OutputChannelType.BRIGHTNESS)): {
                            "value": 55.0,
                            "dontCare": False,
                        },
                    },
                },
            },
        }

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_SET_PROPERTY
        msg.vdsm_request_set_property.dSUID = str(vdsd.dsuid)
        for elem in dict_to_elements(scene_data):
            msg.vdsm_request_set_property.properties.append(elem)

        resp = host._handle_set_property(msg)
        assert resp.generic_response.code == pb.ERR_OK

        entry = out.get_scene(5)
        assert entry["channels"][0]["value"] == 55.0


# ===========================================================================
# dimChannel (§7.3.5) — Output.dim_channel + VdcHost dispatch
# ===========================================================================


class TestDimChannel:
    """Tests for the Output.dim_channel method and on_dim_channel callback."""

    def test_on_dim_channel_property_default_none(self):
        """on_dim_channel defaults to None."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd)
        assert out.on_dim_channel is None

    def test_on_dim_channel_property_set_get(self):
        """on_dim_channel can be set and retrieved."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd)
        cb = AsyncMock()
        out.on_dim_channel = cb
        assert out.on_dim_channel is cb

    def test_on_dim_channel_property_clear(self):
        """on_dim_channel can be cleared back to None."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.on_dim_channel = AsyncMock()
        out.on_dim_channel = None
        assert out.on_dim_channel is None

    @pytest.mark.asyncio
    async def test_dim_channel_calls_callback(self):
        """dim_channel() invokes the callback with correct arguments."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        ch = out.get_channel(0)

        cb = AsyncMock()
        out.on_dim_channel = cb

        await out.dim_channel(ch, mode=1, area=2)
        cb.assert_awaited_once_with(out, ch, 1, 2)

    @pytest.mark.asyncio
    async def test_dim_channel_no_callback_no_error(self):
        """dim_channel() with no callback does not raise."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        ch = out.get_channel(0)

        await out.dim_channel(ch, mode=0, area=0)  # Should not raise

    @pytest.mark.asyncio
    async def test_dim_channel_callback_exception_caught(self):
        """dim_channel() catches exceptions from the callback."""
        host, _vdc, _device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        ch = out.get_channel(0)

        cb = AsyncMock(side_effect=RuntimeError("boom"))
        out.on_dim_channel = cb

        await out.dim_channel(ch, mode=-1, area=0)  # Should not raise
        cb.assert_awaited_once()


class TestStepSceneRule6:
    """Tests for call_step_scene / dispatch_scene and ds-basics Rule 6.

    Rule 6: stepping commands must be ignored when the primary channel
    is at its minimum value.
    """

    @pytest.mark.asyncio
    async def test_decrement_at_min_is_ignored(self):
        """Rule 6: DECREMENT at min_value must be silently ignored."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(0.0)  # at minimum
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.DECREMENT))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_increment_at_min_is_ignored(self):
        """Rule 6: INCREMENT at min_value must also be silently ignored."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(0.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.INCREMENT))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_decrement_above_min_invokes_callback(self):
        """DECREMENT above minimum invokes on_dim_channel with mode=-1, area=0."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.DECREMENT))
        cb.assert_awaited_once_with(out, ch, -1, 0)

    @pytest.mark.asyncio
    async def test_increment_above_min_invokes_callback(self):
        """INCREMENT above minimum invokes on_dim_channel with mode=+1, area=0."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.INCREMENT))
        cb.assert_awaited_once_with(out, ch, 1, 0)

    @pytest.mark.asyncio
    async def test_area_dec_passes_area_to_callback(self):
        """AREA_1_DEC invokes callback with mode=-1 and area=1."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(30.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.AREA_1_DEC))
        cb.assert_awaited_once_with(out, ch, -1, 1)

    @pytest.mark.asyncio
    async def test_area_inc_passes_area_to_callback(self):
        """AREA_3_INC invokes callback with mode=+1 and area=3."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(30.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.AREA_3_INC))
        cb.assert_awaited_once_with(out, ch, 1, 3)

    @pytest.mark.asyncio
    async def test_area_stepping_continue_without_prior_is_noop(self):
        """AREA_STEPPING_CONTINUE with no prior direction does nothing."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.call_step_scene(int(SceneNumber.AREA_STEPPING_CONTINUE))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_area_stepping_continue_inherits_direction_and_area(self):
        """AREA_STEPPING_CONTINUE uses the direction and area of the last step."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        # Initial area decrement sets direction=-1, area=2.
        await out.call_step_scene(int(SceneNumber.AREA_2_DEC))
        cb.assert_awaited_once_with(out, ch, -1, 2)
        cb.reset_mock()

        # Continue should repeat direction=-1, area=2.
        await out.call_step_scene(int(SceneNumber.AREA_STEPPING_CONTINUE))
        cb.assert_awaited_once_with(out, ch, -1, 2)

    @pytest.mark.asyncio
    async def test_area_stepping_continue_blocked_by_rule6(self):
        """AREA_STEPPING_CONTINUE is also blocked by Rule 6 at minimum."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(10.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        # Establish direction.
        await out.call_step_scene(int(SceneNumber.DECREMENT))
        cb.assert_awaited_once()
        cb.reset_mock()

        # Drop to minimum.
        ch.set_value_from_vdsm(0.0)
        ch.confirm_applied()

        await out.call_step_scene(int(SceneNumber.AREA_STEPPING_CONTINUE))
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_scene_routes_step_to_call_step_scene(self):
        """dispatch_scene routes a stepping scene to call_step_scene."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(60.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.dispatch_scene(int(SceneNumber.INCREMENT))
        cb.assert_awaited_once_with(out, ch, 1, 0)

    @pytest.mark.asyncio
    async def test_dispatch_scene_routes_value_scene_to_call_scene(self):
        """dispatch_scene routes a stored-value scene to call_scene."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        await out.dispatch_scene(int(SceneNumber.PRESET_0))
        assert ch.value == pytest.approx(0.0)  # off scene applied

    @pytest.mark.asyncio
    async def test_dispatch_step_via_vdc_host_call_scene_message(self):
        """A CALL_SCENE stepping message through VdcHost invokes on_dim_channel."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = int(SceneNumber.DECREMENT)

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once_with(out, ch, -1, 0)

    @pytest.mark.asyncio
    async def test_dispatch_step_at_zero_via_vdc_host_is_ignored(self):
        """Rule 6 applies end-to-end: stepping at zero through VdcHost is a no-op."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(0.0)  # at minimum
        ch.confirm_applied()

        from pydsvdcapi.enums import SceneNumber

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = int(SceneNumber.DECREMENT)

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_not_awaited()


class TestVdcHostDimChannelDispatch:
    """Tests for VdcHost dispatch of VDSM_NOTIFICATION_DIM_CHANNEL."""

    @staticmethod
    def _make_dim_msg(
        dsuid: str,
        *,
        mode: int = 1,
        area: int = 0,
        channel: int = 0,
        channel_id: str = "",
    ) -> pb.Message:
        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_DIM_CHANNEL
        msg.vdsm_send_dim_channel.dSUID.append(dsuid)
        msg.vdsm_send_dim_channel.mode = mode
        msg.vdsm_send_dim_channel.area = area
        msg.vdsm_send_dim_channel.channel = channel
        if channel_id:
            msg.vdsm_send_dim_channel.channelId = channel_id
        return msg

    @pytest.mark.asyncio
    async def test_dispatch_dim_default_channel(self):
        """dimChannel with channel=0 resolves to first (default) channel."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        msg = self._make_dim_msg(str(vdsd.dsuid), mode=1, area=0, channel=0)
        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once()
        args = cb.await_args[0]
        assert args[0] is out  # output
        assert args[1] is out.get_channel(0)  # default channel
        assert args[2] == 1  # mode
        assert args[3] == 0  # area

    @pytest.mark.asyncio
    async def test_dispatch_dim_by_channel_type(self):
        """dimChannel with numeric channel type resolves correctly."""
        from pydsvdcapi.enums import OutputChannelType

        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        brightness_type = int(OutputChannelType.BRIGHTNESS)
        msg = self._make_dim_msg(
            str(vdsd.dsuid),
            mode=-1,
            area=1,
            channel=brightness_type,
        )
        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once()
        args = cb.await_args[0]
        assert args[0] is out
        assert args[1].channel_type == OutputChannelType.BRIGHTNESS
        assert args[2] == -1
        assert args[3] == 1

    @pytest.mark.asyncio
    async def test_dispatch_dim_by_channel_id(self):
        """dimChannel with channelId (API v3) resolves by name."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        ch = out.get_channel(0)
        channel_name = ch.name  # The name of the first channel

        cb = AsyncMock()
        out.on_dim_channel = cb

        msg = self._make_dim_msg(
            str(vdsd.dsuid),
            mode=0,
            area=0,
            channel_id=channel_name,
        )
        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once()
        args = cb.await_args[0]
        assert args[0] is out
        assert args[1] is ch
        assert args[2] == 0

    @pytest.mark.asyncio
    async def test_dispatch_dim_unknown_dsuid_skipped(self):
        """dimChannel for unknown dSUID is silently skipped."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        msg = self._make_dim_msg("0000000000000000000000000000000000", mode=1)
        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_dim_no_output_skipped(self):
        """dimChannel for vdSD without output is silently skipped."""
        host, vdc, device, vdsd = _make_stack()
        # Do NOT set an output on the vdSD
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        msg = self._make_dim_msg(str(vdsd.dsuid), mode=1)
        session = _make_mock_session()
        await host._dispatch_message(session, msg)  # Should not raise

    @pytest.mark.asyncio
    async def test_dispatch_dim_mode_stop(self):
        """dimChannel with mode=0 (stop) is dispatched correctly."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        msg = self._make_dim_msg(str(vdsd.dsuid), mode=0, area=3)
        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once()
        args = cb.await_args[0]
        assert args[2] == 0  # mode = stop
        assert args[3] == 3  # area

    @pytest.mark.asyncio
    async def test_dispatch_dim_area_values(self):
        """dimChannel passes area values 1-4 through correctly."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        cb = AsyncMock()
        out.on_dim_channel = cb

        for area_val in (1, 2, 3, 4):
            cb.reset_mock()
            msg = self._make_dim_msg(str(vdsd.dsuid), mode=1, area=area_val)
            session = _make_mock_session()
            await host._dispatch_message(session, msg)

            cb.assert_awaited_once()
            assert cb.await_args[0][3] == area_val


# ===========================================================================
# W6 — Scene zone/group filtering and per-group undo (§7.3.1–§7.3.6)
# ===========================================================================


class TestSceneGroupUndoTracking:
    """Tests for per-group undo tracking in Output.call_scene / undo_scene."""

    def test_call_scene_stores_undo_per_group(self):
        """Each call_scene with a different group should create a
        separate undo snapshot."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        # Call scene for group 1.
        out.call_scene(0, group=1)
        assert ch.value == 0.0

        ch.set_value_from_vdsm(75.0)
        ch.confirm_applied()

        # Call scene for group 2.
        out.call_scene(5, group=2)
        assert ch.value == 100.0

        # Undo group 2 → restore 75.
        out.undo_scene(5, group=2)
        assert ch.value == 75.0

        # Undo group 1 → restore 50.
        out.undo_scene(0, group=1)
        assert ch.value == 50.0

    def test_undo_wrong_group_ignored(self):
        """undo_scene with a non-matching group does nothing."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        out.call_scene(0, group=1)
        assert ch.value == 0.0

        # Undo with group=2 → nothing happens.
        out.undo_scene(0, group=2)
        assert ch.value == 0.0

    def test_undo_default_group_zero(self):
        """call_scene / undo_scene without explicit group uses group=0."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        out.call_scene(0)
        assert ch.value == 0.0

        out.undo_scene(0)
        assert ch.value == 42.0

    def test_second_call_same_group_overwrites_snapshot(self):
        """A second call_scene for the same group replaces the snapshot."""
        _, _, _, vdsd = _make_stack()
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        vdsd.set_output(out)

        ch = out.get_channel(0)
        ch.set_value_from_vdsm(10.0)
        ch.confirm_applied()

        out.call_scene(0, group=1)  # snapshot(1)=10
        assert ch.value == 0.0

        ch.set_value_from_vdsm(20.0)
        ch.confirm_applied()

        out.call_scene(5, group=1)  # snapshot(1)=20 (overwrites 10)
        assert ch.value == 100.0

        out.undo_scene(5, group=1)
        assert ch.value == 20.0  # restored to 20, not 10


class TestSceneZoneGroupFiltering:
    """Tests for zone/group filtering in VdcHost scene dispatch."""

    def _make_registered_stack(
        self,
        *,
        zone_id=0,
        primary_group=ColorGroup.YELLOW,
        active_group=None,
        groups=None,
    ):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            primary_group=primary_group,
            zone_id=zone_id,
        )
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        # Set the operationally relevant active_group on the output.
        if active_group is not None:
            out.active_group = active_group
        else:
            out.active_group = int(primary_group)
        if groups:
            out.groups = groups
        vdsd.set_output(out)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)
        host._cancel_auto_save()
        return host, vdc, device, vdsd, out

    # --- callScene filtering ---

    @pytest.mark.asyncio
    async def test_call_scene_matching_group_applies(self):
        """callScene with matching group applies the scene."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0
        msg.vdsm_send_call_scene.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_call_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 0.0

    @pytest.mark.asyncio
    async def test_call_scene_wrong_group_skips(self):
        """callScene with non-matching group skips the device."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0
        msg.vdsm_send_call_scene.group = int(ColorGroup.GREY)
        msg.vdsm_send_call_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 50.0  # unchanged

    @pytest.mark.asyncio
    async def test_call_scene_wrong_zone_skips(self):
        """callScene with non-matching zone skips the device."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0
        msg.vdsm_send_call_scene.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_call_scene.zone_id = 99  # wrong zone

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 50.0  # unchanged

    @pytest.mark.asyncio
    async def test_call_scene_zero_group_matches_all(self):
        """group=0 means 'not specified' and matches any device."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0
        # group and zone_id default to 0 (not specified)

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 0.0  # applied

    @pytest.mark.asyncio
    async def test_call_scene_secondary_group_matches(self):
        """callScene matches if group is in output.groups (secondary)."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
            groups={int(ColorGroup.GREY)},
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(50.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_scene.scene = 0
        msg.vdsm_send_call_scene.group = int(ColorGroup.GREY)
        msg.vdsm_send_call_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 0.0  # applied — GREY is in output.groups

    # --- saveScene filtering ---

    @pytest.mark.asyncio
    async def test_save_scene_matching_group_saves(self):
        """saveScene with matching group saves the scene."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(77.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SAVE_SCENE
        msg.vdsm_send_save_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_save_scene.scene = 5
        msg.vdsm_send_save_scene.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_save_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        entry = out.get_scene(5)
        assert entry["channels"][0]["value"] == 77.0

    @pytest.mark.asyncio
    async def test_save_scene_wrong_group_skips(self):
        """saveScene with non-matching group doesn't save."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(77.0)
        ch.confirm_applied()

        # Get the existing scene 5 value before.
        entry_before = out.get_scene(5)
        val_before = entry_before["channels"][0]["value"]

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SAVE_SCENE
        msg.vdsm_send_save_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_save_scene.scene = 5
        msg.vdsm_send_save_scene.group = int(ColorGroup.GREY)  # wrong
        msg.vdsm_send_save_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        entry_after = out.get_scene(5)
        assert entry_after["channels"][0]["value"] == val_before

    # --- undoScene filtering ---

    @pytest.mark.asyncio
    async def test_undo_scene_matching_group_undoes(self):
        """undoScene with matching group and matching scene undoes."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        # Call scene with group=1 via dispatch.
        call_msg = pb.Message()
        call_msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        call_msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        call_msg.vdsm_send_call_scene.scene = 0
        call_msg.vdsm_send_call_scene.group = int(ColorGroup.YELLOW)
        call_msg.vdsm_send_call_scene.zone_id = 10
        session = _make_mock_session()
        await host._dispatch_message(session, call_msg)
        assert ch.value == 0.0

        # Undo with same group.
        undo_msg = pb.Message()
        undo_msg.type = pb.VDSM_NOTIFICATION_UNDO_SCENE
        undo_msg.vdsm_send_undo_scene.dSUID.append(str(vdsd.dsuid))
        undo_msg.vdsm_send_undo_scene.scene = 0
        undo_msg.vdsm_send_undo_scene.group = int(ColorGroup.YELLOW)
        undo_msg.vdsm_send_undo_scene.zone_id = 10
        await host._dispatch_message(session, undo_msg)
        assert ch.value == 42.0

    @pytest.mark.asyncio
    async def test_undo_scene_wrong_group_no_undo(self):
        """undoScene with different group does not undo."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
            groups={int(ColorGroup.GREY)},
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(42.0)
        ch.confirm_applied()

        # Call scene with group YELLOW.
        call_msg = pb.Message()
        call_msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        call_msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        call_msg.vdsm_send_call_scene.scene = 0
        call_msg.vdsm_send_call_scene.group = int(ColorGroup.YELLOW)
        call_msg.vdsm_send_call_scene.zone_id = 10
        session = _make_mock_session()
        await host._dispatch_message(session, call_msg)
        assert ch.value == 0.0

        # Undo with group GREY → should NOT undo (different group).
        undo_msg = pb.Message()
        undo_msg.type = pb.VDSM_NOTIFICATION_UNDO_SCENE
        undo_msg.vdsm_send_undo_scene.dSUID.append(str(vdsd.dsuid))
        undo_msg.vdsm_send_undo_scene.scene = 0
        undo_msg.vdsm_send_undo_scene.group = int(ColorGroup.GREY)
        undo_msg.vdsm_send_undo_scene.zone_id = 10
        await host._dispatch_message(session, undo_msg)
        assert ch.value == 0.0  # unchanged

    # --- setLocalPriority filtering ---

    @pytest.mark.asyncio
    async def test_set_local_priority_matching_group(self):
        """setLocalPriority with matching group sets LP."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        assert out.local_priority is False

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_LOCAL_PRIO
        msg.vdsm_send_set_local_prio.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_local_prio.scene = 0
        msg.vdsm_send_set_local_prio.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_set_local_prio.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert out.local_priority is True

    @pytest.mark.asyncio
    async def test_set_local_priority_wrong_group_skips(self):
        """setLocalPriority with non-matching group does not set LP."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        assert out.local_priority is False

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_LOCAL_PRIO
        msg.vdsm_send_set_local_prio.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_local_prio.scene = 0
        msg.vdsm_send_set_local_prio.group = int(ColorGroup.GREY)
        msg.vdsm_send_set_local_prio.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert out.local_priority is False

    # --- callMinScene filtering ---

    @pytest.mark.asyncio
    async def test_call_min_scene_matching_group_applies(self):
        """callMinScene with matching group sets min-on."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(0.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_MIN_SCENE
        msg.vdsm_send_call_min_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_min_scene.scene = 0
        msg.vdsm_send_call_min_scene.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_call_min_scene.zone_id = 10

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value > 0.0

    @pytest.mark.asyncio
    async def test_call_min_scene_wrong_zone_skips(self):
        """callMinScene with non-matching zone does not act."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(0.0)
        ch.confirm_applied()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_CALL_MIN_SCENE
        msg.vdsm_send_call_min_scene.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_call_min_scene.scene = 0
        msg.vdsm_send_call_min_scene.group = int(ColorGroup.YELLOW)
        msg.vdsm_send_call_min_scene.zone_id = 99  # wrong zone

        session = _make_mock_session()
        await host._dispatch_message(session, msg)
        assert ch.value == 0.0  # unchanged

    # --- callScene passes group to Output for undo tracking ---

    @pytest.mark.asyncio
    async def test_call_and_undo_via_dispatch_uses_group(self):
        """Full roundtrip: callScene dispatch stores group-keyed undo
        that can only be undone with the same group."""
        host, _, _, vdsd, out = self._make_registered_stack(
            zone_id=10,
            primary_group=ColorGroup.YELLOW,
        )
        ch = out.get_channel(0)
        ch.set_value_from_vdsm(55.0)
        ch.confirm_applied()

        session = _make_mock_session()
        grp = int(ColorGroup.YELLOW)

        # Call scene 0 with group.
        call_msg = pb.Message()
        call_msg.type = pb.VDSM_NOTIFICATION_CALL_SCENE
        call_msg.vdsm_send_call_scene.dSUID.append(str(vdsd.dsuid))
        call_msg.vdsm_send_call_scene.scene = 0
        call_msg.vdsm_send_call_scene.group = grp
        call_msg.vdsm_send_call_scene.zone_id = 10
        await host._dispatch_message(session, call_msg)
        assert ch.value == 0.0

        # Undo with group.
        undo_msg = pb.Message()
        undo_msg.type = pb.VDSM_NOTIFICATION_UNDO_SCENE
        undo_msg.vdsm_send_undo_scene.dSUID.append(str(vdsd.dsuid))
        undo_msg.vdsm_send_undo_scene.scene = 0
        undo_msg.vdsm_send_undo_scene.group = grp
        undo_msg.vdsm_send_undo_scene.zone_id = 10
        await host._dispatch_message(session, undo_msg)
        assert ch.value == 55.0


class TestMatchesZoneAndGroup:
    """Unit tests for VdcHost._matches_zone_and_group helper.

    Group matching uses output.active_group (the operationally assigned
    dS Application ID from OutputSettings §4.8.2), not vdsd.primary_group.
    """

    def test_both_zero_matches(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert host._matches_zone_and_group(vdsd, out, 0, 0) is True

    def test_matching_zone_and_active_group(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert (
            host._matches_zone_and_group(vdsd, out, 42, int(ColorGroup.YELLOW)) is True
        )

    def test_wrong_zone(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert (
            host._matches_zone_and_group(vdsd, out, 99, int(ColorGroup.YELLOW)) is False
        )

    def test_wrong_group(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert (
            host._matches_zone_and_group(vdsd, out, 42, int(ColorGroup.GREY)) is False
        )

    def test_primary_group_alone_does_not_match(self):
        """primary_group on vdsd is NOT used — only active_group matters."""
        host = _make_host()
        _, _, _, vdsd = _make_stack(
            primary_group=ColorGroup.YELLOW,
            zone_id=42,
        )
        out = _make_output(vdsd, function=OutputFunction.DIMMER, groups=set())
        out.active_group = int(ColorGroup.GREY)  # different from primary
        assert (
            host._matches_zone_and_group(vdsd, out, 42, int(ColorGroup.YELLOW)) is False
        )  # YELLOW is primary but NOT active_group

    def test_secondary_group_matches(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        out.groups = {int(ColorGroup.GREY)}
        assert host._matches_zone_and_group(vdsd, out, 42, int(ColorGroup.GREY)) is True

    def test_zone_zero_matches_any(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert (
            host._matches_zone_and_group(vdsd, out, 0, int(ColorGroup.YELLOW)) is True
        )

    def test_group_zero_matches_any(self):
        host = _make_host()
        _, _, _, vdsd = _make_stack(zone_id=42)
        out = _make_output(vdsd, function=OutputFunction.DIMMER)
        out.active_group = int(ColorGroup.YELLOW)
        assert host._matches_zone_and_group(vdsd, out, 42, 0) is True


# ===========================================================================
# Shadow motor timing fields
# ===========================================================================


class TestShadowTimingFields:
    """Tests for shadow motor timing fields in outputSettings."""

    def test_shadow_timing_fields_in_settings(self):
        """Shadow timing fields appear in outputSettings when set."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out._open_time = 60.0
        out._close_time = 55.0
        out._angle_open_time = 1.5
        out._angle_close_time = 1.5
        out._stop_delay_time = 0.5
        s = out.get_settings_properties()
        assert s["openTime"] == 60.0
        assert s["closeTime"] == 55.0
        assert s["angleOpenTime"] == 1.5
        assert s["angleCloseTime"] == 1.5
        assert s["stopDelayTime"] == 0.5

    def test_shadow_timing_absent_when_not_set(self):
        """Shadow timing fields are absent when not configured."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        s = out.get_settings_properties()
        assert "openTime" not in s
        assert "closeTime" not in s
        assert "angleOpenTime" not in s
        assert "angleCloseTime" not in s
        assert "stopDelayTime" not in s

    def test_apply_settings_stores_shadow_timing(self):
        """apply_settings stores shadow timing values correctly."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        out.apply_settings(
            {
                "openTime": 45.0,
                "closeTime": 40.0,
                "angleOpenTime": 2.0,
                "angleCloseTime": 2.0,
                "stopDelayTime": 0.3,
            }
        )
        s = out.get_settings_properties()
        assert s["openTime"] == 45.0
        assert s["closeTime"] == 40.0
        assert s["angleOpenTime"] == 2.0
        assert s["angleCloseTime"] == 2.0
        assert s["stopDelayTime"] == 0.3

    def test_shadow_timing_init_params(self):
        """Shadow timing fields can be set at construction time."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="Blind Motor",
            default_group=8,
            active_group=8,
            groups={8},
            open_time=60.0,
            close_time=55.0,
            angle_open_time=1.5,
            angle_close_time=1.5,
            stop_delay_time=0.5,
        )
        assert out.open_time == 60.0
        assert out.close_time == 55.0
        assert out.angle_open_time == 1.5
        assert out.angle_close_time == 1.5
        assert out.stop_delay_time == 0.5

    def test_shadow_timing_default_none(self):
        """Shadow timing fields default to None."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        assert out.open_time is None
        assert out.close_time is None
        assert out.angle_open_time is None
        assert out.angle_close_time is None
        assert out.stop_delay_time is None

    def test_shadow_timing_persisted_in_tree(self):
        """Shadow timing fields appear in get_property_tree when set."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="Blind",
            default_group=8,
            active_group=8,
            groups={8},
            open_time=60.0,
            close_time=55.0,
            angle_open_time=1.5,
            angle_close_time=1.5,
            stop_delay_time=0.5,
        )
        tree = out.get_property_tree()
        assert tree["openTime"] == 60.0
        assert tree["closeTime"] == 55.0
        assert tree["angleOpenTime"] == 1.5
        assert tree["angleCloseTime"] == 1.5
        assert tree["stopDelayTime"] == 0.5

    def test_shadow_timing_absent_from_tree_when_not_set(self):
        """Shadow timing fields are absent from property tree when None."""
        host, vdc, device, vdsd = _make_stack()
        out = _make_output(vdsd)
        tree = out.get_property_tree()
        assert "openTime" not in tree
        assert "closeTime" not in tree
        assert "angleOpenTime" not in tree
        assert "angleCloseTime" not in tree
        assert "stopDelayTime" not in tree

    def test_shadow_timing_round_trip(self):
        """Shadow timing survives get_property_tree / _apply_state round-trip."""
        host, vdc, device, vdsd = _make_stack()
        original = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="Blind",
            default_group=8,
            active_group=8,
            groups={8},
            open_time=60.0,
            close_time=55.0,
            angle_open_time=1.5,
            angle_close_time=1.5,
            stop_delay_time=0.5,
        )
        tree = original.get_property_tree()

        restored = Output(
            vdsd=vdsd, name="restored", default_group=0, active_group=0, groups=set()
        )
        restored._apply_state(tree)

        assert restored.open_time == 60.0
        assert restored.close_time == 55.0
        assert restored.angle_open_time == 1.5
        assert restored.angle_close_time == 1.5
        assert restored.stop_delay_time == 0.5

    def test_apply_settings_none_resets_shadow_timing(self):
        """apply_settings with None resets shadow timing fields."""
        host, vdc, device, vdsd = _make_stack()
        out = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="Blind",
            default_group=8,
            active_group=8,
            groups={8},
            open_time=60.0,
        )
        out.apply_settings({"openTime": None})
        assert out.open_time is None
        assert "openTime" not in out.get_settings_properties()
