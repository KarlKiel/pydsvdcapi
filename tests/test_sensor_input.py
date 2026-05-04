"""Tests for the SensorInput component."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    SENSOR_TYPE_VALID_USAGES,
    ColorGroup,
    InputError,
    SensorType,
    SensorUsage,
    validate_sensor_type_usage,
)
from pydsvdcapi.property_handling import elements_to_dict
from pydsvdcapi.sensor_input import SensorInput
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
        "implementation_id": "x-test-si",
        "name": "Test SI vDC",
        "model": "Test SI v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("si-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.BLACK,
        "name": "SI Test vdSD",
        "model": "Test SI vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_sensor_input(vdsd: Vdsd, **kwargs: Any) -> SensorInput:
    defaults: dict[str, Any] = {
        "vdsd": vdsd,
        "ds_index": 0,
        "sensor_type": SensorType.TEMPERATURE,
        "sensor_usage": SensorUsage.ROOM,
        "name": "Room Temperature",
        "min_value": -20.0,
        "max_value": 60.0,
        "resolution": 0.1,
    }
    defaults.update(kwargs)
    return SensorInput(**defaults)


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
    return session


# ===========================================================================
# Construction and defaults
# ===========================================================================


class TestSensorInputConstruction:
    """Tests for SensorInput creation and default values."""

    def test_default_construction(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        assert si.ds_index == 0
        assert si.name == "Room Temperature"
        assert si.sensor_type == SensorType.TEMPERATURE
        assert si.sensor_usage == SensorUsage.ROOM
        assert si.min_value == -20.0
        assert si.max_value == 60.0
        assert si.resolution == 0.1
        assert si.update_interval == 0.0
        assert si.group == 0
        assert si.min_push_interval == 2.0  # sensor default
        assert si.changes_only_interval == 0.0
        assert si.vdsd is vdsd

    def test_custom_construction(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si = SensorInput(
            vdsd=vdsd,
            ds_index=2,
            sensor_type=SensorType.HUMIDITY,
            sensor_usage=SensorUsage.OUTDOOR,
            group=5,
            name="Outdoor Humidity",
            min_value=0.0,
            max_value=100.0,
            resolution=1.0,
            update_interval=10.0,
            alive_sign_interval=60.0,
            min_push_interval=5.0,
            changes_only_interval=30.0,
        )

        assert si.ds_index == 2
        assert si.name == "Outdoor Humidity"
        assert si.sensor_type == SensorType.HUMIDITY
        assert si.sensor_usage == SensorUsage.OUTDOOR
        assert si.group == 5
        assert si.min_value == 0.0
        assert si.max_value == 100.0
        assert si.resolution == 1.0
        assert si.update_interval == 10.0
        assert si.alive_sign_interval == 60.0
        assert si.min_push_interval == 5.0
        assert si.changes_only_interval == 30.0

    def test_repr(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        r = repr(si)
        assert "SensorInput" in r
        assert "ds_index=0" in r
        assert "Room Temperature" in r
        assert "TEMPERATURE" in r


# ===========================================================================
# State defaults
# ===========================================================================


class TestSensorInputStateDefaults:
    """Tests for initial state values."""

    def test_initial_value_is_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        assert si.value is None
        assert si.age is None
        assert si.context_id is None
        assert si.context_msg is None
        assert si.error == InputError.OK

    def test_error_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.error = InputError.LOW_BATTERY
        assert si.error == InputError.LOW_BATTERY

        si.error = 2  # SHORT_CIRCUIT
        assert si.error == InputError.SHORT_CIRCUIT


# ===========================================================================
# Settings (writable, persisted)
# ===========================================================================


class TestSensorInputSettings:
    """Tests for settings property accessors."""

    def test_group_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.group = 3
        assert si.group == 3

    def test_min_push_interval_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.min_push_interval = 5.0
        assert si.min_push_interval == 5.0

    def test_changes_only_interval_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.changes_only_interval = 10.0
        assert si.changes_only_interval == 10.0

    def test_apply_settings(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.apply_settings(
            {
                "group": 4,
                "minPushInterval": 3.0,
                "changesOnlyInterval": 8.0,
            }
        )

        assert si.group == 4
        assert si.min_push_interval == 3.0
        assert si.changes_only_interval == 8.0

    def test_apply_settings_partial(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, group=1)

        si.apply_settings({"group": 9})

        assert si.group == 9
        # Other settings unchanged.
        assert si.min_push_interval == 2.0
        assert si.changes_only_interval == 0.0


# ===========================================================================
# Description properties
# ===========================================================================


class TestSensorInputDescriptionProperties:
    """Tests for the description property dict."""

    def test_description_dict(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            update_interval=5.0,
            alive_sign_interval=60.0,
        )

        desc = si.get_description_properties()

        assert desc["name"] == "Room Temperature"
        assert desc["dsIndex"] == 0
        assert desc["sensorType"] == int(SensorType.TEMPERATURE)
        assert desc["sensorUsage"] == int(SensorUsage.ROOM)
        assert desc["min"] == -20.0
        assert desc["max"] == 60.0
        assert desc["resolution"] == 0.1
        assert desc["updateInterval"] == 5.0
        assert desc["aliveSignInterval"] == 60.0


# ===========================================================================
# Settings properties dict
# ===========================================================================


class TestSensorInputSettingsProperties:
    """Tests for the settings property dict."""

    def test_settings_dict(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            group=3,
            min_push_interval=5.0,
            changes_only_interval=10.0,
        )

        settings = si.get_settings_properties()

        assert settings["group"] == 3
        assert settings["minPushInterval"] == 5.0
        assert settings["changesOnlyInterval"] == 10.0


# ===========================================================================
# State properties dict
# ===========================================================================


class TestSensorInputStateProperties:
    """Tests for the state property dict."""

    def test_state_dict_initial(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        state = si.get_state_properties()

        assert state["value"] is None
        assert state["age"] is None
        assert state["error"] == int(InputError.OK)
        assert "contextId" not in state
        assert "contextMsg" not in state

    def test_state_dict_with_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si._value = 21.5
        si._last_update = time.monotonic()

        state = si.get_state_properties()

        assert state["value"] == 21.5
        assert state["age"] is not None
        assert state["age"] >= 0.0

    def test_state_dict_with_context(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si._value = 22.0
        si._last_update = time.monotonic()
        si._context_id = 42
        si._context_msg = "calibrated"

        state = si.get_state_properties()

        assert state["contextId"] == 42
        assert state["contextMsg"] == "calibrated"

    def test_state_dict_with_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.error = InputError.LOW_BATTERY

        state = si.get_state_properties()
        assert state["error"] == int(InputError.LOW_BATTERY)


# ===========================================================================
# Value updates and push notifications
# ===========================================================================


class TestSensorInputValueUpdate:
    """Tests for update_value."""

    @pytest.mark.asyncio
    async def test_update_value_sets_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(21.5)

        assert si.value == 21.5
        assert si.age is not None
        assert si.age < 1.0

    @pytest.mark.asyncio
    async def test_update_value_with_context(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(22.0, context_id=7, context_msg="calibrated")

        assert si.value == 22.0
        assert si.context_id == 7
        assert si.context_msg == "calibrated"

    @pytest.mark.asyncio
    async def test_update_value_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(None)
        assert si.value is None

    @pytest.mark.asyncio
    async def test_update_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_error(InputError.OPEN_CIRCUIT)
        assert si.error == InputError.OPEN_CIRCUIT

    @pytest.mark.asyncio
    async def test_context_preserved_across_updates(self):
        """Context fields are sticky — only overwritten if explicitly set."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(21.0, context_id=1, context_msg="first")
        await si.update_value(22.0)  # no context args

        assert si.value == 22.0
        assert si.context_id == 1  # preserved
        assert si.context_msg == "first"  # preserved


# ===========================================================================
# Push notifications
# ===========================================================================


class TestSensorInputPushNotification:
    """Tests for the push notification logic."""

    @pytest.mark.asyncio
    async def test_push_sent_when_announced(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)

        session = _make_mock_session()
        vdsd._announced = True

        await si.update_value(21.5, session)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)

        # Verify the pushed properties tree.
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        assert "sensorStates" in props
        states = props["sensorStates"]
        assert "0" in states
        assert states["0"]["value"] == 21.5

    @pytest.mark.asyncio
    async def test_push_not_sent_when_not_announced(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        session = _make_mock_session()
        # vdsd._announced is False by default

        await si.update_value(21.5, session)

        session.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_not_sent_when_no_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd._announced = True

        # No session passed.
        await si.update_value(21.5)
        # Should not raise.

    @pytest.mark.asyncio
    async def test_push_error_update(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_error(InputError.SHORT_CIRCUIT, session)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        assert props["sensorStates"]["0"]["error"] == int(InputError.SHORT_CIRCUIT)

    @pytest.mark.asyncio
    async def test_push_handles_connection_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd._announced = True

        session = _make_mock_session()
        session.send_notification = AsyncMock(
            side_effect=ConnectionError("disconnected")
        )

        # Should not raise despite connection error.
        await si.update_value(21.5, session)
        assert si.value == 21.5

    @pytest.mark.asyncio
    async def test_push_for_multiple_sensors(self):
        """Each sensor pushes its own state independently."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si0 = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            name="Temperature",
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            min_value=-20.0,
            max_value=60.0,
            resolution=0.1,
        )
        si1 = SensorInput(
            vdsd=vdsd,
            ds_index=1,
            name="Humidity",
            sensor_type=SensorType.HUMIDITY,
            sensor_usage=SensorUsage.ROOM,
            min_value=0.0,
            max_value=100.0,
            resolution=1.0,
        )
        vdsd.add_sensor_input(si0)
        vdsd.add_sensor_input(si1)
        vdsd._announced = True

        session = _make_mock_session()

        await si0.update_value(21.5, session)
        await si1.update_value(55.0, session)

        assert session.send_notification.call_count == 2

        # First call pushes index 0.
        msg0 = session.send_notification.call_args_list[0][0][0]
        props0 = elements_to_dict(msg0.vdc_send_push_notification.changedproperties)
        assert "0" in props0["sensorStates"]

        # Second call pushes index 1.
        msg1 = session.send_notification.call_args_list[1][0][0]
        props1 = elements_to_dict(msg1.vdc_send_push_notification.changedproperties)
        assert "1" in props1["sensorStates"]

    @pytest.mark.asyncio
    async def test_push_includes_context(self):
        """Context data should appear in the pushed state."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session, context_id=99, context_msg="test")

        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        state = props["sensorStates"]["0"]
        assert state["contextId"] == 99
        assert state["contextMsg"] == "test"


# ===========================================================================
# Vdsd integration — add/remove/get sensor inputs
# ===========================================================================


class TestVdsdSensorInputManagement:
    """Tests for add/remove/get sensor input methods on Vdsd."""

    def test_add_sensor_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        vdsd.add_sensor_input(si)

        assert si.ds_index in vdsd.sensor_inputs
        assert vdsd.get_sensor_input(0) is si

    def test_add_sensor_input_wrong_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd1 = _make_vdsd(device)
        vdsd2 = _make_vdsd(device, subdevice_index=1)

        si = _make_sensor_input(vdsd1)

        with pytest.raises(ValueError, match="different vdSD"):
            vdsd2.add_sensor_input(si)

    def test_remove_sensor_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)

        removed = vdsd.remove_sensor_input(0)
        assert removed is si
        assert vdsd.get_sensor_input(0) is None

    def test_remove_nonexistent(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.remove_sensor_input(99) is None

    def test_get_sensor_input_nonexistent(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.get_sensor_input(0) is None

    def test_sensor_inputs_dict_is_copy(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)

        inputs = vdsd.sensor_inputs
        inputs.clear()  # Should not affect internal state.
        assert len(vdsd.sensor_inputs) == 1

    def test_replace_existing_index(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si_old = _make_sensor_input(vdsd, name="Old")
        si_new = _make_sensor_input(vdsd, name="New")

        vdsd.add_sensor_input(si_old)
        vdsd.add_sensor_input(si_new)

        assert vdsd.get_sensor_input(0) is si_new
        restored = vdsd.get_sensor_input(0)
        assert restored is not None
        assert restored.name == "New"


# ===========================================================================
# Vdsd property exposure — sensor inputs in get_properties()
# ===========================================================================


class TestVdsdSensorInputProperties:
    """Tests for sensor input properties in Vdsd.get_properties()."""

    def test_no_sensor_inputs_no_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()

        assert "sensorDescriptions" not in props
        assert "sensorSettings" not in props
        assert "sensorStates" not in props

    def test_sensor_input_properties_exposed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)

        props = vdsd.get_properties()

        assert "sensorDescriptions" in props
        assert "sensorSettings" in props
        assert "sensorStates" in props

        # Descriptions keyed by str(dsIndex).
        descs = props["sensorDescriptions"]
        assert "0" in descs
        assert descs["0"]["name"] == "Room Temperature"
        assert descs["0"]["dsIndex"] == 0
        assert descs["0"]["sensorType"] == int(SensorType.TEMPERATURE)
        assert descs["0"]["min"] == -20.0
        assert descs["0"]["max"] == 60.0

        # Settings.
        settings = props["sensorSettings"]
        assert "0" in settings
        assert settings["0"]["group"] == 0
        assert settings["0"]["minPushInterval"] == 2.0

        # States.
        states = props["sensorStates"]
        assert "0" in states
        assert states["0"]["value"] is None

    def test_multiple_sensor_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si0 = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            name="Temperature",
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            min_value=-20.0,
            max_value=60.0,
            resolution=0.1,
        )
        si1 = SensorInput(
            vdsd=vdsd,
            ds_index=1,
            name="Humidity",
            sensor_type=SensorType.HUMIDITY,
            sensor_usage=SensorUsage.ROOM,
            min_value=0.0,
            max_value=100.0,
            resolution=1.0,
        )
        vdsd.add_sensor_input(si0)
        vdsd.add_sensor_input(si1)

        props = vdsd.get_properties()
        descs = props["sensorDescriptions"]
        assert "0" in descs
        assert "1" in descs
        assert descs["0"]["name"] == "Temperature"
        assert descs["1"]["name"] == "Humidity"


# ===========================================================================
# Persistence — get_property_tree / _apply_state round-trip
# ===========================================================================


class TestSensorInputPersistence:
    """Tests for SensorInput persistence."""

    def test_get_property_tree(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            group=5,
            update_interval=30.0,
            alive_sign_interval=120.0,
            min_push_interval=3.0,
            changes_only_interval=15.0,
        )

        tree = si.get_property_tree()

        assert tree["dsIndex"] == 0
        assert tree["name"] == "Room Temperature"
        assert tree["sensorType"] == int(SensorType.TEMPERATURE)
        assert tree["sensorUsage"] == int(SensorUsage.ROOM)
        assert tree["min"] == -20.0
        assert tree["max"] == 60.0
        assert tree["resolution"] == 0.1
        assert tree["updateInterval"] == 30.0
        assert tree["aliveSignInterval"] == 120.0
        assert tree["group"] == 5
        assert tree["minPushInterval"] == 3.0
        assert tree["changesOnlyInterval"] == 15.0

    def test_apply_state(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = SensorInput._restore(vdsd=vdsd, ds_index=0)

        si._apply_state(
            {
                "dsIndex": 3,
                "name": "Restored Sensor",
                "sensorType": int(SensorType.HUMIDITY),
                "sensorUsage": int(SensorUsage.OUTDOOR),
                "min": 0.0,
                "max": 100.0,
                "resolution": 0.5,
                "updateInterval": 15.0,
                "aliveSignInterval": 60.0,
                "group": 7,
                "minPushInterval": 4.0,
                "changesOnlyInterval": 20.0,
            }
        )

        assert si.ds_index == 3
        assert si.name == "Restored Sensor"
        assert si.sensor_type == SensorType.HUMIDITY
        assert si.sensor_usage == SensorUsage.OUTDOOR
        assert si.min_value == 0.0
        assert si.max_value == 100.0
        assert si.resolution == 0.5
        assert si.update_interval == 15.0
        assert si.alive_sign_interval == 60.0
        assert si.group == 7
        assert si.min_push_interval == 4.0
        assert si.changes_only_interval == 20.0

    def test_round_trip(self):
        """Save → restore should yield identical properties."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        original = SensorInput(
            vdsd=vdsd,
            ds_index=1,
            sensor_type=SensorType.CO2_CONCENTRATION,
            sensor_usage=SensorUsage.ROOM,
            group=8,
            name="CO2 Sensor",
            min_value=0.0,
            max_value=5000.0,
            resolution=1.0,
            update_interval=60.0,
            alive_sign_interval=300.0,
            min_push_interval=5.0,
            changes_only_interval=30.0,
        )

        tree = original.get_property_tree()

        restored = SensorInput._restore(vdsd=vdsd, ds_index=99)
        restored._apply_state(tree)

        assert restored.ds_index == original.ds_index
        assert restored.name == original.name
        assert restored.sensor_type == original.sensor_type
        assert restored.sensor_usage == original.sensor_usage
        assert restored.min_value == original.min_value
        assert restored.max_value == original.max_value
        assert restored.resolution == original.resolution
        assert restored.update_interval == original.update_interval
        assert restored.alive_sign_interval == original.alive_sign_interval
        assert restored.group == original.group
        assert restored.min_push_interval == original.min_push_interval
        assert restored.changes_only_interval == original.changes_only_interval

    def test_state_not_persisted(self):
        """State values must NOT appear in the property tree."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si._value = 21.5
        si._context_id = 42
        si._context_msg = "test"
        si._error = InputError.LOW_BATTERY
        si._last_update = time.monotonic()

        tree = si.get_property_tree()

        assert "value" not in tree
        assert "contextId" not in tree
        assert "contextMsg" not in tree
        assert "age" not in tree
        assert "error" not in tree


# ===========================================================================
# Vdsd persistence with sensor inputs
# ===========================================================================


class TestVdsdSensorInputPersistence:
    """Tests for sensor inputs in Vdsd property tree persistence."""

    def test_vdsd_tree_includes_sensor_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, group=2)
        vdsd.add_sensor_input(si)

        tree = vdsd.get_property_tree()

        assert "sensorInputs" in tree
        assert len(tree["sensorInputs"]) == 1
        assert tree["sensorInputs"][0]["dsIndex"] == 0
        assert tree["sensorInputs"][0]["group"] == 2

    def test_vdsd_tree_no_sensor_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        tree = vdsd.get_property_tree()
        assert "sensorInputs" not in tree

    def test_vdsd_apply_state_restores_sensor_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        # Save a vdSD with a sensor input.
        si = _make_sensor_input(vdsd, group=4)
        vdsd.add_sensor_input(si)
        tree = vdsd.get_property_tree()

        # Create a fresh vdSD and restore.
        vdsd2 = _make_vdsd(device, subdevice_index=0)
        vdsd2._apply_state(tree)

        assert len(vdsd2.sensor_inputs) == 1
        restored_si = vdsd2.get_sensor_input(0)
        assert restored_si is not None
        assert restored_si.name == "Room Temperature"
        assert restored_si.group == 4
        assert restored_si.sensor_type == SensorType.TEMPERATURE

    def test_vdsd_apply_state_updates_existing_sensor_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        # Pre-create a sensor input.
        si = _make_sensor_input(vdsd, group=0)
        vdsd.add_sensor_input(si)

        # Apply saved state with updated group.
        vdsd._apply_state(
            {
                "sensorInputs": [
                    {
                        "dsIndex": 0,
                        "name": "Updated Temp",
                        "group": 9,
                        "minPushInterval": 5.0,
                    }
                ],
            }
        )

        assert si.name == "Updated Temp"
        assert si.group == 9
        assert si.min_push_interval == 5.0

    def test_vdsd_full_round_trip(self):
        """Vdsd with sensor inputs → save → restore → compare."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si0 = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            name="Temperature",
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            group=1,
            min_value=-20.0,
            max_value=60.0,
            resolution=0.1,
        )
        si1 = SensorInput(
            vdsd=vdsd,
            ds_index=1,
            name="Humidity",
            sensor_type=SensorType.HUMIDITY,
            sensor_usage=SensorUsage.OUTDOOR,
            group=3,
            min_value=0.0,
            max_value=100.0,
            resolution=1.0,
            update_interval=5.0,
        )
        vdsd.add_sensor_input(si0)
        vdsd.add_sensor_input(si1)

        tree = vdsd.get_property_tree()

        # Restore.
        vdsd2 = _make_vdsd(device, subdevice_index=0)
        vdsd2._apply_state(tree)

        assert len(vdsd2.sensor_inputs) == 2

        r0 = vdsd2.get_sensor_input(0)
        assert r0 is not None
        assert r0.name == "Temperature"
        assert r0.sensor_type == SensorType.TEMPERATURE
        assert r0.group == 1

        r1 = vdsd2.get_sensor_input(1)
        assert r1 is not None
        assert r1.name == "Humidity"
        assert r1.sensor_type == SensorType.HUMIDITY
        assert r1.group == 3
        assert r1.update_interval == 5.0


# ===========================================================================
# VdcHost setProperty integration for sensorSettings
# ===========================================================================


class TestVdcHostSensorInputSetProperty:
    """Tests for setProperty handling of sensorSettings."""

    def _setup(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, group=0)
        vdsd.add_sensor_input(si)
        device.add_vdsd(vdsd)
        host.add_vdc(vdc)
        vdc.add_device(device)
        return host, vdc, device, vdsd, si

    def test_set_sensor_settings(self):
        host, vdc, device, vdsd, si = self._setup()

        incoming = {
            "sensorSettings": {
                "0": {
                    "group": 5,
                    "minPushInterval": 10.0,
                    "changesOnlyInterval": 30.0,
                },
            },
        }

        host._apply_vdsd_set_property(vdsd, incoming)

        assert si.group == 5
        assert si.min_push_interval == 10.0
        assert si.changes_only_interval == 30.0

    def test_set_sensor_settings_partial(self):
        host, vdc, device, vdsd, si = self._setup()

        incoming = {
            "sensorSettings": {
                "0": {"group": 8},
            },
        }

        host._apply_vdsd_set_property(vdsd, incoming)

        assert si.group == 8
        assert si.min_push_interval == 2.0  # unchanged default

    def test_set_sensor_settings_unknown_index(self):
        host, vdc, device, vdsd, si = self._setup()

        incoming = {
            "sensorSettings": {
                "99": {"group": 1},
            },
        }

        # Should not raise.
        host._apply_vdsd_set_property(vdsd, incoming)
        assert si.group == 0  # unchanged

    def test_set_property_via_message(self):
        """Full message dispatch for setProperty sensorSettings."""
        host, vdc, device, vdsd, si = self._setup()

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_SET_PROPERTY
        msg.message_id = 42
        msg.vdsm_request_set_property.dSUID = str(vdsd.dsuid)

        # Build property tree: sensorSettings.0.group = 6
        si_elem = msg.vdsm_request_set_property.properties.add()
        si_elem.name = "sensorSettings"
        idx_elem = si_elem.elements.add()
        idx_elem.name = "0"
        group_elem = idx_elem.elements.add()
        group_elem.name = "group"
        group_elem.value.v_uint64 = 6

        resp = host._handle_set_property(msg)

        assert resp.generic_response.code == pb.ERR_OK
        assert si.group == 6


# ===========================================================================
# Auto-save triggering
# ===========================================================================


class TestSensorInputAutoSave:
    """Tests that settings changes trigger auto-save."""

    def test_group_setter_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            si.group = 5
            mock_save.assert_called()

    def test_min_push_interval_setter_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            si.min_push_interval = 5.0
            mock_save.assert_called()

    def test_changes_only_interval_setter_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            si.changes_only_interval = 10.0
            mock_save.assert_called()

    def test_apply_settings_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            si.apply_settings({"group": 3})
            mock_save.assert_called()


# ===========================================================================
# Age calculation
# ===========================================================================


class TestSensorInputAge:
    """Tests for the age property."""

    def test_age_none_initially(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        assert si.age is None

    @pytest.mark.asyncio
    async def test_age_after_update(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(21.5)
        age = si.age

        assert age is not None
        assert age >= 0.0
        assert age < 1.0  # should be near-instant

    @pytest.mark.asyncio
    async def test_age_increases(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(21.5)
        age1 = si.age
        assert age1 is not None

        # Nudge the timestamp back 1 second.
        assert si._last_update is not None
        si._last_update -= 1.0
        age2 = si.age
        assert age2 is not None

        assert age2 > age1


# ===========================================================================
# Push throttling — minPushInterval
# ===========================================================================


class TestMinPushInterval:
    """Tests for minPushInterval rate-limiting."""

    @pytest.mark.asyncio
    async def test_first_push_always_goes_through(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=5.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        await si.update_value(21.5, session)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_push_within_interval_deferred(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=5.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        # First push goes through.
        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Second push is deferred (within 5s).
        await si.update_value(22.0, session)
        assert session.send_notification.call_count == 1

        # A deferred push handle should be scheduled.
        assert si._deferred_push_handle is not None

    @pytest.mark.asyncio
    async def test_push_after_interval_elapsed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=0.5)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Simulate time passing beyond interval.
        assert si._last_push_time is not None
        si._last_push_time -= 1.0

        await si.update_value(22.0, session)
        assert session.send_notification.call_count == 2

    @pytest.mark.asyncio
    async def test_deferred_push_fires(self):
        """The deferred push should fire after the delay."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=0.05)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Trigger a deferred push.
        await si.update_value(22.0, session)
        assert session.send_notification.call_count == 1

        # Wait for the deferred push to fire.
        await asyncio.sleep(0.1)
        assert session.send_notification.call_count == 2

    @pytest.mark.asyncio
    async def test_deferred_push_cancelled_on_stop(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=5.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        await si.update_value(22.0, session)
        assert si._deferred_push_handle is not None

        si.stop_alive_timer()
        assert si._deferred_push_handle is None


# ===========================================================================
# Push throttling — changesOnlyInterval
# ===========================================================================


class TestChangesOnlyInterval:
    """Tests for changesOnlyInterval duplicate suppression."""

    @pytest.mark.asyncio
    async def test_same_value_suppressed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, changes_only_interval=10.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Same value again — should be suppressed.
        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

    @pytest.mark.asyncio
    async def test_different_value_not_suppressed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            changes_only_interval=10.0,
            min_push_interval=0.0,
        )
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Different value — should push.
        await si.update_value(22.0, session)
        assert session.send_notification.call_count == 2

    @pytest.mark.asyncio
    async def test_same_value_after_interval_elapsed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, changes_only_interval=1.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Simulate interval elapsed.
        assert si._last_push_time is not None
        si._last_push_time -= 2.0

        # Same value but interval elapsed — should push.
        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 2


# ===========================================================================
# Force bypass (used by alive timer)
# ===========================================================================


class TestPushForce:
    """Tests that force=True bypasses throttling."""

    @pytest.mark.asyncio
    async def test_force_bypasses_min_push_interval(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, min_push_interval=999.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Force push ignores minPushInterval.
        await si._push_state(session, force=True)
        assert session.send_notification.call_count == 2

    @pytest.mark.asyncio
    async def test_force_bypasses_changes_only_interval(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, changes_only_interval=999.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Force push ignores changesOnlyInterval.
        await si._push_state(session, force=True)
        assert session.send_notification.call_count == 2


# ===========================================================================
# Alive timer
# ===========================================================================


class TestAliveTimer:
    """Tests for the alive timer (periodic heartbeat push)."""

    def test_start_stores_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, alive_sign_interval=10.0)

        session = _make_mock_session()
        si.start_alive_timer(session)

        assert si._session is session

    def test_stop_clears_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, alive_sign_interval=10.0)

        session = _make_mock_session()
        si.start_alive_timer(session)
        si.stop_alive_timer()

        assert si._session is None
        assert si._alive_timer_handle is None

    @pytest.mark.asyncio
    async def test_alive_timer_fires(self):
        """Alive timer should re-push state after the interval."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, alive_sign_interval=0.05)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        # Set initial value.
        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Start alive timer.
        si.start_alive_timer(session)

        # Wait for the alive timer to fire.
        await asyncio.sleep(0.15)

        # Should have re-pushed at least once.
        assert session.send_notification.call_count >= 2

    @pytest.mark.asyncio
    async def test_alive_timer_does_not_start_when_zero(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, alive_sign_interval=0.0)

        session = _make_mock_session()
        si.start_alive_timer(session)

        # Timer not scheduled.
        assert si._alive_timer_handle is None
        # But session IS stored.
        assert si._session is session

    @pytest.mark.asyncio
    async def test_alive_timer_reset_after_push(self):
        """A regular push should reset the alive timer."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            alive_sign_interval=0.2,
            min_push_interval=0.0,
        )
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        si.start_alive_timer(session)

        # Push 3 times within the alive interval.
        for i in range(3):
            await si.update_value(20.0 + i, session)
            await asyncio.sleep(0.05)

        # Only value-change pushes, no alive timer fire yet.
        assert session.send_notification.call_count == 3

    @pytest.mark.asyncio
    async def test_alive_timer_cancelled_on_vanish(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd, alive_sign_interval=10.0)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        si.start_alive_timer(session)
        assert si._alive_timer_handle is not None

        # Simulate vanish.
        vdsd.reset_announcement()
        assert si._alive_timer_handle is None
        assert si._session is None


# ===========================================================================
# Session fallback — update_value without explicit session
# ===========================================================================


class TestSessionFallback:
    """Tests that update methods use the stored session as fallback."""

    @pytest.mark.asyncio
    async def test_update_value_uses_stored_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        si.start_alive_timer(session)

        # No session passed — should use stored session.
        await si.update_value(21.5)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_error_uses_stored_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        si.start_alive_timer(session)

        await si.update_error(InputError.LOW_BATTERY)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_session_overrides_stored(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        stored_session = _make_mock_session()
        explicit_session = _make_mock_session()
        si.start_alive_timer(stored_session)

        # Explicit session takes precedence.
        await si.update_value(21.5, explicit_session)

        explicit_session.send_notification.assert_called_once()
        stored_session.send_notification.assert_not_called()


# ===========================================================================
# Vdsd announce/vanish alive timer integration
# ===========================================================================


class TestVdsdAliveTimerLifecycle:
    """Tests that Vdsd announce/vanish/reset manage alive timers."""

    def test_add_sensor_input_after_announce_starts_timer(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        si = _make_sensor_input(vdsd, alive_sign_interval=10.0)
        vdsd.add_sensor_input(si)

        assert si._session is session

    def test_reset_announcement_stops_all_timers(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        si0 = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            alive_sign_interval=10.0,
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            min_value=-20.0,
            max_value=60.0,
            resolution=0.1,
        )
        si1 = SensorInput(
            vdsd=vdsd,
            ds_index=1,
            alive_sign_interval=20.0,
            sensor_type=SensorType.HUMIDITY,
            sensor_usage=SensorUsage.ROOM,
            min_value=0.0,
            max_value=100.0,
            resolution=1.0,
        )
        vdsd.add_sensor_input(si0)
        vdsd.add_sensor_input(si1)

        session = _make_mock_session()
        si0.start_alive_timer(session)
        si1.start_alive_timer(session)

        vdsd.reset_announcement()

        assert si0._session is None
        assert si1._session is None
        assert si0._alive_timer_handle is None
        assert si1._alive_timer_handle is None

    def test_vdsd_stores_session_on_announce(self):
        """When vdSD is announced, it stores the session."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        assert vdsd._session is session

        vdsd.reset_announcement()
        assert vdsd._session is None


# ===========================================================================
# State key tracking
# ===========================================================================


class TestCurrentStateKey:
    """Tests for _current_state_key used in changesOnlyInterval."""

    def test_initial_state_key(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        assert si._current_state_key() == (None,)

    @pytest.mark.asyncio
    async def test_state_key_after_value_update(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        await si.update_value(21.5)
        assert si._current_state_key() == (21.5,)

    @pytest.mark.asyncio
    async def test_last_pushed_state_tracked(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()
        await si.update_value(21.5, session)

        assert si._last_pushed_state == (21.5,)
        assert si._last_push_time is not None


# ===========================================================================
# Combined min_push + changes_only
# ===========================================================================


class TestCombinedThrottling:
    """Tests with both minPushInterval and changesOnlyInterval set."""

    @pytest.mark.asyncio
    async def test_changes_only_checked_before_min_push(self):
        """changesOnlyInterval suppression should take priority over
        minPushInterval deferral (no deferred push scheduled for
        same-value duplicates)."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            min_push_interval=5.0,
            changes_only_interval=10.0,
        )
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Same value within changesOnlyInterval — suppressed entirely.
        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1
        # No deferred push scheduled (changesOnly wins).
        assert si._deferred_push_handle is None

    @pytest.mark.asyncio
    async def test_different_value_deferred_by_min_push(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(
            vdsd,
            min_push_interval=5.0,
            changes_only_interval=10.0,
        )
        vdsd.add_sensor_input(si)
        vdsd._announced = True

        session = _make_mock_session()

        await si.update_value(21.5, session)
        assert session.send_notification.call_count == 1

        # Different value — not suppressed by changesOnly, but
        # deferred by minPushInterval.
        await si.update_value(22.0, session)
        assert session.send_notification.call_count == 1
        assert si._deferred_push_handle is not None


# ===========================================================================
# Name setter
# ===========================================================================


class TestSensorInputNameSetter:
    """Tests for the name property setter."""

    def test_name_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        si = _make_sensor_input(vdsd)

        si.name = "New Name"
        assert si.name == "New Name"


# ===========================================================================
# All SensorType enum values
# ===========================================================================


class TestSensorTypeEnumValues:
    """Verify that all documented sensor types are in the enum."""

    @pytest.mark.parametrize(
        "value, name",
        [
            (0, "NONE"),
            (1, "TEMPERATURE"),
            (2, "HUMIDITY"),
            (3, "ILLUMINATION"),
            (4, "SUPPLY_VOLTAGE"),
            (5, "CO_CONCENTRATION"),
            (6, "RADON_ACTIVITY"),
            (7, "GAS_TYPE"),
            (8, "PARTICLES_PM10"),
            (9, "PARTICLES_PM2_5"),
            (10, "PARTICLES_PM1"),
            (11, "ROOM_OPERATING_PANEL"),
            (12, "FAN_SPEED"),
            (13, "WIND_SPEED"),
            (14, "ACTIVE_POWER"),
            (15, "ELECTRIC_CURRENT"),
            (16, "ENERGY_METER"),
            (17, "APPARENT_POWER"),
            (18, "AIR_PRESSURE"),
            (19, "WIND_DIRECTION"),
            (20, "SOUND_PRESSURE_LEVEL"),
            (21, "PRECIPITATION"),
            (22, "CO2_CONCENTRATION"),
            (23, "WIND_GUST_SPEED"),
            (24, "WIND_GUST_DIRECTION"),
            (25, "GENERATED_ACTIVE_POWER"),
            (26, "GENERATED_ENERGY"),
            (27, "WATER_QUANTITY"),
            (28, "WATER_FLOW_RATE"),
        ],
    )
    def test_sensor_type(self, value: int, name: str):
        st = SensorType(value)
        assert st.name == name

    @pytest.mark.parametrize(
        "value, name",
        [
            (0, "UNDEFINED"),
            (1, "ROOM"),
            (2, "OUTDOOR"),
            (3, "USER_INTERACTION"),
            (4, "DEVICE_LEVEL"),
            (5, "DEVICE_LAST_RUN"),
            (6, "DEVICE_AVERAGE"),
        ],
    )
    def test_sensor_usage(self, value: int, name: str):
        su = SensorUsage(value)
        assert su.name == name


# ===========================================================================
# Sensor type / usage validation  (ds-basics Table 23)
# ===========================================================================


class TestSensorTypeUsageValidation:
    """Tests for validate_sensor_type_usage and SENSOR_TYPE_VALID_USAGES."""

    # ---- standalone function ----

    def test_none_type_rejected(self):
        with pytest.raises(ValueError, match="NONE"):
            validate_sensor_type_usage(SensorType.NONE, SensorUsage.ROOM)

    def test_undefined_usage_rejected(self):
        with pytest.raises(ValueError, match="UNDEFINED"):
            validate_sensor_type_usage(SensorType.TEMPERATURE, SensorUsage.UNDEFINED)

    def test_type_not_in_table23_accepts_any_explicit_usage(self):
        # SUPPLY_VOLTAGE is not in Table 23 → any non-UNDEFINED usage is accepted
        validate_sensor_type_usage(SensorType.SUPPLY_VOLTAGE, SensorUsage.ROOM)
        validate_sensor_type_usage(SensorType.SUPPLY_VOLTAGE, SensorUsage.OUTDOOR)
        validate_sensor_type_usage(SensorType.SUPPLY_VOLTAGE, SensorUsage.DEVICE_LEVEL)

    def test_type_not_in_table23_rejects_undefined_usage(self):
        with pytest.raises(ValueError, match="UNDEFINED"):
            validate_sensor_type_usage(SensorType.SUPPLY_VOLTAGE, SensorUsage.UNDEFINED)

    @pytest.mark.parametrize(
        "usage",
        [
            SensorUsage.ROOM,
            SensorUsage.OUTDOOR,
            SensorUsage.DEVICE_LEVEL,
            SensorUsage.DEVICE_LAST_RUN,
            SensorUsage.DEVICE_AVERAGE,
        ],
    )
    def test_temperature_valid_usages(self, usage: SensorUsage):
        validate_sensor_type_usage(SensorType.TEMPERATURE, usage)

    def test_temperature_rejects_user_interaction(self):
        with pytest.raises(ValueError, match="USER_INTERACTION"):
            validate_sensor_type_usage(
                SensorType.TEMPERATURE, SensorUsage.USER_INTERACTION
            )

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.CO_CONCENTRATION,
            SensorType.CO2_CONCENTRATION,
        ],
    )
    def test_concentration_room_only_valid(self, sensor_type: SensorType):
        validate_sensor_type_usage(sensor_type, SensorUsage.ROOM)

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.CO_CONCENTRATION,
            SensorType.CO2_CONCENTRATION,
        ],
    )
    def test_concentration_rejects_outdoor(self, sensor_type: SensorType):
        with pytest.raises(ValueError, match="OUTDOOR"):
            validate_sensor_type_usage(sensor_type, SensorUsage.OUTDOOR)

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.AIR_PRESSURE,
            SensorType.WIND_SPEED,
            SensorType.WIND_DIRECTION,
            SensorType.WIND_GUST_SPEED,
            SensorType.WIND_GUST_DIRECTION,
            SensorType.PRECIPITATION,
        ],
    )
    def test_outdoor_only_types_accept_outdoor(self, sensor_type: SensorType):
        validate_sensor_type_usage(sensor_type, SensorUsage.OUTDOOR)

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.AIR_PRESSURE,
            SensorType.WIND_SPEED,
            SensorType.WIND_DIRECTION,
            SensorType.WIND_GUST_SPEED,
            SensorType.WIND_GUST_DIRECTION,
            SensorType.PRECIPITATION,
        ],
    )
    def test_outdoor_only_types_reject_room(self, sensor_type: SensorType):
        with pytest.raises(ValueError, match="ROOM"):
            validate_sensor_type_usage(sensor_type, SensorUsage.ROOM)

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.ACTIVE_POWER,
            SensorType.ELECTRIC_CURRENT,
            SensorType.ENERGY_METER,
            SensorType.APPARENT_POWER,
            SensorType.SOUND_PRESSURE_LEVEL,
            SensorType.GENERATED_ACTIVE_POWER,
            SensorType.GENERATED_ENERGY,
            SensorType.WATER_QUANTITY,
            SensorType.WATER_FLOW_RATE,
            SensorType.LENGTH,
            SensorType.MASS,
            SensorType.DURATION,
        ],
    )
    @pytest.mark.parametrize(
        "usage",
        [
            SensorUsage.DEVICE_LEVEL,
            SensorUsage.DEVICE_LAST_RUN,
            SensorUsage.DEVICE_AVERAGE,
        ],
    )
    def test_device_only_types_accept_device_usages(
        self, sensor_type: SensorType, usage: SensorUsage
    ):
        validate_sensor_type_usage(sensor_type, usage)

    @pytest.mark.parametrize(
        "sensor_type",
        [
            SensorType.ACTIVE_POWER,
            SensorType.ENERGY_METER,
            SensorType.APPARENT_POWER,
        ],
    )
    def test_device_only_types_reject_room(self, sensor_type: SensorType):
        with pytest.raises(ValueError, match="ROOM"):
            validate_sensor_type_usage(sensor_type, SensorUsage.ROOM)

    def test_error_message_contains_valid_usages(self):
        with pytest.raises(ValueError, match="Valid usages"):
            validate_sensor_type_usage(SensorType.WIND_SPEED, SensorUsage.ROOM)

    # ---- validation via SensorInput constructor ----

    def _make_base(self) -> tuple:
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        return vdsd

    def test_constructor_accepts_valid_combination(self):
        vdsd = self._make_base()
        si = SensorInput(
            vdsd=vdsd,
            sensor_type=SensorType.ACTIVE_POWER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=4096.0,
            resolution=1.0,
        )
        assert si.sensor_type == SensorType.ACTIVE_POWER

    def test_constructor_rejects_invalid_combination(self):
        vdsd = self._make_base()
        with pytest.raises(
            ValueError, match="ROOM.*not valid.*ACTIVE_POWER|ACTIVE_POWER.*ROOM"
        ):
            SensorInput(
                vdsd=vdsd,
                sensor_type=SensorType.ACTIVE_POWER,
                sensor_usage=SensorUsage.ROOM,
                min_value=0.0,
                max_value=4096.0,
                resolution=1.0,
            )

    # ---- SENSOR_TYPE_VALID_USAGES coverage ----

    def test_all_table23_types_have_entries(self):
        expected = {
            SensorType.TEMPERATURE,
            SensorType.HUMIDITY,
            SensorType.ILLUMINATION,
            SensorType.CO_CONCENTRATION,
            SensorType.CO2_CONCENTRATION,
            SensorType.AIR_PRESSURE,
            SensorType.WIND_SPEED,
            SensorType.WIND_DIRECTION,
            SensorType.WIND_GUST_SPEED,
            SensorType.WIND_GUST_DIRECTION,
            SensorType.PRECIPITATION,
            SensorType.ACTIVE_POWER,
            SensorType.ELECTRIC_CURRENT,
            SensorType.ENERGY_METER,
            SensorType.APPARENT_POWER,
            SensorType.SOUND_PRESSURE_LEVEL,
            SensorType.GENERATED_ACTIVE_POWER,
            SensorType.GENERATED_ENERGY,
            SensorType.WATER_QUANTITY,
            SensorType.WATER_FLOW_RATE,
            SensorType.LENGTH,
            SensorType.MASS,
            SensorType.DURATION,
        }
        assert expected.issubset(set(SENSOR_TYPE_VALID_USAGES.keys()))
