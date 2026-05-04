"""Tests for the BinaryInput component."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.binary_input import (
    INPUT_TYPE_DETECTS_CHANGES,
    INPUT_TYPE_POLL_ONLY,
    BinaryInput,
)
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    BinaryInputType,
    BinaryInputUsage,
    ColorGroup,
    InputError,
)
from pydsvdcapi.property_handling import elements_to_dict
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
        "implementation_id": "x-test-bi",
        "name": "Test BI vDC",
        "model": "Test BI v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("bi-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.BLACK,
        "name": "BI Test vdSD",
        "model": "Test BI vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_binary_input(vdsd: Vdsd, **kwargs: Any) -> BinaryInput:
    defaults: dict[str, Any] = {
        "vdsd": vdsd,
        "ds_index": 0,
        "sensor_function": BinaryInputType.PRESENCE,
        "input_usage": BinaryInputUsage.ROOM_CLIMATE,
        "name": "PIR Sensor",
    }
    defaults.update(kwargs)
    return BinaryInput(**defaults)


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
    return session


# ===========================================================================
# Construction and defaults
# ===========================================================================


class TestBinaryInputConstruction:
    """Tests for BinaryInput creation and default values."""

    def test_default_construction(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        assert bi.ds_index == 0
        assert bi.name == "PIR Sensor"
        assert bi.input_type == INPUT_TYPE_DETECTS_CHANGES
        assert bi.input_usage == BinaryInputUsage.ROOM_CLIMATE
        assert bi.hardwired_function == BinaryInputType.GENERIC
        assert bi.sensor_function == BinaryInputType.PRESENCE
        assert bi.group == 0
        assert bi.update_interval == 0.0
        assert bi.vdsd is vdsd

    def test_custom_construction(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi = BinaryInput(
            vdsd=vdsd,
            ds_index=2,
            sensor_function=BinaryInputType.SMOKE,
            input_type=INPUT_TYPE_POLL_ONLY,
            input_usage=BinaryInputUsage.OUTDOOR_CLIMATE,
            group=5,
            name="Smoke Detector",
            update_interval=10.0,
            hardwired_function=BinaryInputType.SMOKE,
        )

        assert bi.ds_index == 2
        assert bi.name == "Smoke Detector"
        assert bi.input_type == INPUT_TYPE_POLL_ONLY
        assert bi.input_usage == BinaryInputUsage.OUTDOOR_CLIMATE
        assert bi.hardwired_function == BinaryInputType.SMOKE
        assert bi.sensor_function == BinaryInputType.SMOKE
        assert bi.group == 5
        assert bi.update_interval == 10.0

    def test_repr(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        r = repr(bi)
        assert "BinaryInput" in r
        assert "ds_index=0" in r
        assert "PIR Sensor" in r
        assert "PRESENCE" in r


# ===========================================================================
# State defaults
# ===========================================================================


class TestBinaryInputStateDefaults:
    """Tests for initial state values."""

    def test_initial_value_is_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        assert bi.value is None
        assert bi.extended_value is None
        assert bi.age is None
        assert bi.error == InputError.OK

    def test_error_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi.error = InputError.LOW_BATTERY
        assert bi.error == InputError.LOW_BATTERY

        bi.error = 2  # SHORT_CIRCUIT
        assert bi.error == InputError.SHORT_CIRCUIT


# ===========================================================================
# Settings (writable, persisted)
# ===========================================================================


class TestBinaryInputSettings:
    """Tests for settings property accessors."""

    def test_group_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi.group = 3
        assert bi.group == 3

    def test_sensor_function_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi.sensor_function = BinaryInputType.WIND
        assert bi.sensor_function == BinaryInputType.WIND

        bi.sensor_function = 7  # SMOKE
        assert bi.sensor_function == BinaryInputType.SMOKE

    def test_apply_settings(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi.apply_settings({"group": 4, "sensorFunction": 12})

        assert bi.group == 4
        assert bi.sensor_function == BinaryInputType.BATTERY_LOW

    def test_apply_settings_partial(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd, group=1)

        bi.apply_settings({"group": 9})

        assert bi.group == 9
        # sensor_function unchanged
        assert bi.sensor_function == BinaryInputType.PRESENCE


# ===========================================================================
# Description properties
# ===========================================================================


class TestBinaryInputDescriptionProperties:
    """Tests for the description property dict."""

    def test_description_dict(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(
            vdsd,
            hardwired_function=BinaryInputType.BATTERY_LOW,
            update_interval=5.0,
        )

        desc = bi.get_description_properties()

        assert desc["name"] == "PIR Sensor"
        assert desc["dsIndex"] == 0
        assert desc["inputType"] == INPUT_TYPE_DETECTS_CHANGES
        assert desc["inputUsage"] == int(BinaryInputUsage.ROOM_CLIMATE)
        assert desc["sensorFunction"] == int(BinaryInputType.BATTERY_LOW)
        assert desc["updateInterval"] == 5.0


# ===========================================================================
# Settings properties dict
# ===========================================================================


class TestBinaryInputSettingsProperties:
    """Tests for the settings property dict."""

    def test_settings_dict(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd, group=3)

        settings = bi.get_settings_properties()

        assert settings["group"] == 3
        assert settings["sensorFunction"] == int(BinaryInputType.PRESENCE)


# ===========================================================================
# State properties dict
# ===========================================================================


class TestBinaryInputStateProperties:
    """Tests for the state property dict."""

    def test_state_dict_initial(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        state = bi.get_state_properties()

        # Initially no value and no age.
        assert state["value"] is None
        assert state["age"] is None
        assert state["error"] == int(InputError.OK)
        assert "extendedValue" not in state

    def test_state_dict_with_bool_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        # Manually set value.
        bi._value = True
        bi._last_update = time.monotonic()

        state = bi.get_state_properties()

        assert state["value"] is True
        assert state["age"] is not None
        assert state["age"] >= 0.0
        assert "extendedValue" not in state

    def test_state_dict_with_extended_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi._extended_value = 2  # e.g. tilted
        bi._last_update = time.monotonic()

        state = bi.get_state_properties()

        assert state["extendedValue"] == 2
        assert "value" not in state  # extendedValue takes precedence
        assert state["age"] is not None

    def test_state_dict_with_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi.error = InputError.LOW_BATTERY

        state = bi.get_state_properties()
        assert state["error"] == int(InputError.LOW_BATTERY)


# ===========================================================================
# Value updates and push notifications
# ===========================================================================


class TestBinaryInputValueUpdate:
    """Tests for update_value / update_extended_value."""

    @pytest.mark.asyncio
    async def test_update_value_sets_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_value(True)

        assert bi.value is True
        assert bi.extended_value is None
        assert bi.age is not None
        assert bi.age < 1.0

    @pytest.mark.asyncio
    async def test_update_value_clears_extended(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi._extended_value = 5
        await bi.update_value(False)

        assert bi.value is False
        assert bi.extended_value is None

    @pytest.mark.asyncio
    async def test_update_extended_value_sets_extended(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_extended_value(2)

        assert bi.extended_value == 2
        assert bi.value is None

    @pytest.mark.asyncio
    async def test_update_extended_value_clears_bool(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi._value = True
        await bi.update_extended_value(1)

        assert bi.value is None
        assert bi.extended_value == 1

    @pytest.mark.asyncio
    async def test_update_value_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_value(None)
        assert bi.value is None

    @pytest.mark.asyncio
    async def test_update_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_error(InputError.OPEN_CIRCUIT)
        assert bi.error == InputError.OPEN_CIRCUIT


# ===========================================================================
# Push notifications
# ===========================================================================


class TestBinaryInputPushNotification:
    """Tests for the push notification logic."""

    @pytest.mark.asyncio
    async def test_push_sent_when_announced(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        session = _make_mock_session()
        vdsd._announced = True  # simulate announced state

        await bi.update_value(True, session)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)

        # Verify the pushed properties tree.
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        assert "binaryInputStates" in props
        states = props["binaryInputStates"]
        assert "0" in states
        assert states["0"]["value"] is True

    @pytest.mark.asyncio
    async def test_push_not_sent_when_not_announced(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        session = _make_mock_session()
        # vdsd._announced is False by default

        await bi.update_value(True, session)

        session.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_not_sent_when_no_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd._announced = True

        # No session passed.
        await bi.update_value(True)
        # Should not raise.

    @pytest.mark.asyncio
    async def test_push_extended_value(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd._announced = True

        session = _make_mock_session()

        await bi.update_extended_value(2, session)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        states = props["binaryInputStates"]["0"]
        assert states["extendedValue"] == 2
        assert "value" not in states

    @pytest.mark.asyncio
    async def test_push_error_update(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd._announced = True

        session = _make_mock_session()

        await bi.update_error(InputError.SHORT_CIRCUIT, session)

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        assert props["binaryInputStates"]["0"]["error"] == int(InputError.SHORT_CIRCUIT)

    @pytest.mark.asyncio
    async def test_push_handles_connection_error(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd._announced = True

        session = _make_mock_session()
        session.send_notification = AsyncMock(
            side_effect=ConnectionError("disconnected")
        )

        # Should not raise despite connection error.
        await bi.update_value(True, session)
        assert bi.value is True

    @pytest.mark.asyncio
    async def test_push_for_multiple_inputs(self):
        """Each binary input pushes its own state independently."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi0 = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            name="Presence",
            sensor_function=BinaryInputType.PRESENCE,
        )
        bi1 = BinaryInput(
            vdsd=vdsd,
            ds_index=1,
            name="Window",
            sensor_function=BinaryInputType.WINDOW_OPEN,
        )
        vdsd.add_binary_input(bi0)
        vdsd.add_binary_input(bi1)
        vdsd._announced = True

        session = _make_mock_session()

        await bi0.update_value(True, session)
        await bi1.update_extended_value(2, session)

        assert session.send_notification.call_count == 2

        # First call pushes index 0.
        msg0 = session.send_notification.call_args_list[0][0][0]
        props0 = elements_to_dict(msg0.vdc_send_push_notification.changedproperties)
        assert "0" in props0["binaryInputStates"]

        # Second call pushes index 1.
        msg1 = session.send_notification.call_args_list[1][0][0]
        props1 = elements_to_dict(msg1.vdc_send_push_notification.changedproperties)
        assert "1" in props1["binaryInputStates"]


# ===========================================================================
# Vdsd integration — add/remove/get binary inputs
# ===========================================================================


class TestVdsdBinaryInputManagement:
    """Tests for add/remove/get binary input methods on Vdsd."""

    def test_add_binary_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        vdsd.add_binary_input(bi)

        assert bi.ds_index in vdsd.binary_inputs
        assert vdsd.get_binary_input(0) is bi

    def test_add_binary_input_wrong_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd1 = _make_vdsd(device)
        vdsd2 = _make_vdsd(device, subdevice_index=1)

        bi = _make_binary_input(vdsd1)

        with pytest.raises(ValueError, match="different vdSD"):
            vdsd2.add_binary_input(bi)

    def test_remove_binary_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        removed = vdsd.remove_binary_input(0)
        assert removed is bi
        assert vdsd.get_binary_input(0) is None

    def test_remove_nonexistent(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.remove_binary_input(99) is None

    def test_get_binary_input_nonexistent(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.get_binary_input(0) is None

    def test_binary_inputs_dict_is_copy(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        inputs = vdsd.binary_inputs
        inputs.clear()  # Should not affect internal state.
        assert len(vdsd.binary_inputs) == 1

    def test_replace_existing_index(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi_old = _make_binary_input(vdsd, name="Old")
        bi_new = _make_binary_input(vdsd, name="New")

        vdsd.add_binary_input(bi_old)
        vdsd.add_binary_input(bi_new)

        assert vdsd.get_binary_input(0) is bi_new
        restored = vdsd.get_binary_input(0)
        assert restored is not None
        assert restored.name == "New"


# ===========================================================================
# Vdsd property exposure — binary inputs in get_properties()
# ===========================================================================


class TestVdsdBinaryInputProperties:
    """Tests for binary input properties in Vdsd.get_properties()."""

    def test_no_binary_inputs_no_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()

        assert "binaryInputDescriptions" not in props
        assert "binaryInputSettings" not in props
        assert "binaryInputStates" not in props

    def test_binary_input_properties_exposed(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        props = vdsd.get_properties()

        assert "binaryInputDescriptions" in props
        assert "binaryInputSettings" in props
        assert "binaryInputStates" in props

        # Descriptions keyed by str(dsIndex).
        descs = props["binaryInputDescriptions"]
        assert "0" in descs
        assert descs["0"]["name"] == "PIR Sensor"
        assert descs["0"]["dsIndex"] == 0

        # Settings.
        settings = props["binaryInputSettings"]
        assert "0" in settings
        assert settings["0"]["group"] == 0

        # States.
        states = props["binaryInputStates"]
        assert "0" in states
        assert states["0"]["value"] is None

    def test_multiple_binary_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi0 = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            name="PIR",
            sensor_function=BinaryInputType.PRESENCE,
        )
        bi1 = BinaryInput(
            vdsd=vdsd,
            ds_index=1,
            name="Window",
            sensor_function=BinaryInputType.WINDOW_OPEN,
        )
        vdsd.add_binary_input(bi0)
        vdsd.add_binary_input(bi1)

        props = vdsd.get_properties()
        descs = props["binaryInputDescriptions"]
        assert "0" in descs
        assert "1" in descs
        assert descs["0"]["name"] == "PIR"
        assert descs["1"]["name"] == "Window"


# ===========================================================================
# Persistence — get_property_tree / _apply_state round-trip
# ===========================================================================


class TestBinaryInputPersistence:
    """Tests for BinaryInput persistence."""

    def test_get_property_tree(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(
            vdsd,
            group=5,
            hardwired_function=BinaryInputType.BATTERY_LOW,
            update_interval=30.0,
        )

        tree = bi.get_property_tree()

        assert tree["dsIndex"] == 0
        assert tree["name"] == "PIR Sensor"
        assert tree["inputType"] == INPUT_TYPE_DETECTS_CHANGES
        assert tree["inputUsage"] == int(BinaryInputUsage.ROOM_CLIMATE)
        assert tree["hardwiredFunction"] == int(BinaryInputType.BATTERY_LOW)
        assert tree["updateInterval"] == 30.0
        assert tree["group"] == 5
        assert tree["sensorFunction"] == int(BinaryInputType.PRESENCE)

    def test_apply_state(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = BinaryInput(vdsd=vdsd, ds_index=0)

        bi._apply_state(
            {
                "dsIndex": 3,
                "name": "Restored Sensor",
                "inputType": INPUT_TYPE_POLL_ONLY,
                "inputUsage": int(BinaryInputUsage.OUTDOOR_CLIMATE),
                "hardwiredFunction": int(BinaryInputType.SMOKE),
                "updateInterval": 15.0,
                "group": 7,
                "sensorFunction": int(BinaryInputType.WIND),
            }
        )

        assert bi.ds_index == 3
        assert bi.name == "Restored Sensor"
        assert bi.input_type == INPUT_TYPE_POLL_ONLY
        assert bi.input_usage == BinaryInputUsage.OUTDOOR_CLIMATE
        assert bi.hardwired_function == BinaryInputType.SMOKE
        assert bi.update_interval == 15.0
        assert bi.group == 7
        assert bi.sensor_function == BinaryInputType.WIND

    def test_round_trip(self):
        """Save → restore should yield identical properties."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        original = BinaryInput(
            vdsd=vdsd,
            ds_index=1,
            sensor_function=BinaryInputType.WINDOW_OPEN,
            input_type=INPUT_TYPE_POLL_ONLY,
            input_usage=BinaryInputUsage.CLIMATE_SETTING,
            group=8,
            name="Window Contact",
            update_interval=60.0,
            hardwired_function=BinaryInputType.WINDOW_OPEN,
        )

        tree = original.get_property_tree()

        restored = BinaryInput(vdsd=vdsd, ds_index=99)
        restored._apply_state(tree)

        assert restored.ds_index == original.ds_index
        assert restored.name == original.name
        assert restored.input_type == original.input_type
        assert restored.input_usage == original.input_usage
        assert restored.hardwired_function == original.hardwired_function
        assert restored.update_interval == original.update_interval
        assert restored.group == original.group
        assert restored.sensor_function == original.sensor_function

    def test_state_not_persisted(self):
        """State values must NOT appear in the property tree."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        bi._value = True
        bi._extended_value = 5
        bi._error = InputError.LOW_BATTERY
        bi._last_update = time.monotonic()

        tree = bi.get_property_tree()

        assert "value" not in tree
        assert "extendedValue" not in tree
        assert "age" not in tree
        assert "error" not in tree


# ===========================================================================
# Vdsd persistence with binary inputs
# ===========================================================================


class TestVdsdBinaryInputPersistence:
    """Tests for binary inputs in Vdsd property tree persistence."""

    def test_vdsd_tree_includes_binary_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd, group=2)
        vdsd.add_binary_input(bi)

        tree = vdsd.get_property_tree()

        assert "binaryInputs" in tree
        assert len(tree["binaryInputs"]) == 1
        assert tree["binaryInputs"][0]["dsIndex"] == 0
        assert tree["binaryInputs"][0]["group"] == 2

    def test_vdsd_tree_no_binary_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        tree = vdsd.get_property_tree()
        assert "binaryInputs" not in tree

    def test_vdsd_apply_state_restores_binary_inputs(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        # Save a vdSD with a binary input.
        bi = _make_binary_input(vdsd, group=4)
        vdsd.add_binary_input(bi)
        tree = vdsd.get_property_tree()

        # Create a fresh vdSD and restore.
        vdsd2 = _make_vdsd(device, subdevice_index=0)
        vdsd2._apply_state(tree)

        assert len(vdsd2.binary_inputs) == 1
        restored_bi = vdsd2.get_binary_input(0)
        assert restored_bi is not None
        assert restored_bi.name == "PIR Sensor"
        assert restored_bi.group == 4
        assert restored_bi.sensor_function == BinaryInputType.PRESENCE

    def test_vdsd_apply_state_updates_existing_binary_input(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        # Pre-create a binary input.
        bi = _make_binary_input(vdsd, group=0)
        vdsd.add_binary_input(bi)

        # Apply saved state with updated group.
        vdsd._apply_state(
            {
                "binaryInputs": [
                    {
                        "dsIndex": 0,
                        "name": "Updated PIR",
                        "group": 9,
                        "sensorFunction": int(BinaryInputType.MOTION),
                    }
                ],
            }
        )

        assert bi.name == "Updated PIR"
        assert bi.group == 9
        assert bi.sensor_function == BinaryInputType.MOTION

    def test_vdsd_full_round_trip(self):
        """Vdsd with binary inputs → save → restore → compare."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi0 = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            name="PIR",
            sensor_function=BinaryInputType.PRESENCE,
            input_usage=BinaryInputUsage.ROOM_CLIMATE,
            group=1,
        )
        bi1 = BinaryInput(
            vdsd=vdsd,
            ds_index=1,
            name="Window",
            sensor_function=BinaryInputType.WINDOW_OPEN,
            input_usage=BinaryInputUsage.OUTDOOR_CLIMATE,
            group=3,
            update_interval=5.0,
        )
        vdsd.add_binary_input(bi0)
        vdsd.add_binary_input(bi1)

        tree = vdsd.get_property_tree()

        # Restore.
        vdsd2 = _make_vdsd(device, subdevice_index=0)
        vdsd2._apply_state(tree)

        assert len(vdsd2.binary_inputs) == 2

        r0 = vdsd2.get_binary_input(0)
        assert r0 is not None
        assert r0.name == "PIR"
        assert r0.sensor_function == BinaryInputType.PRESENCE
        assert r0.group == 1

        r1 = vdsd2.get_binary_input(1)
        assert r1 is not None
        assert r1.name == "Window"
        assert r1.sensor_function == BinaryInputType.WINDOW_OPEN
        assert r1.group == 3
        assert r1.update_interval == 5.0


# ===========================================================================
# VdcHost setProperty integration for binaryInputSettings
# ===========================================================================


class TestVdcHostBinaryInputSetProperty:
    """Tests for setProperty handling of binaryInputSettings."""

    def _setup(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd, group=0)
        vdsd.add_binary_input(bi)
        device.add_vdsd(vdsd)
        host.add_vdc(vdc)
        vdc.add_device(device)
        return host, vdc, device, vdsd, bi

    def test_set_binary_input_settings(self):
        host, vdc, device, vdsd, bi = self._setup()

        incoming = {
            "binaryInputSettings": {
                "0": {
                    "group": 5,
                    "sensorFunction": int(BinaryInputType.SMOKE),
                },
            },
        }

        host._apply_vdsd_set_property(vdsd, incoming)

        assert bi.group == 5
        assert bi.sensor_function == BinaryInputType.SMOKE

    def test_set_binary_input_settings_partial(self):
        host, vdc, device, vdsd, bi = self._setup()

        incoming = {
            "binaryInputSettings": {
                "0": {"group": 8},
            },
        }

        host._apply_vdsd_set_property(vdsd, incoming)

        assert bi.group == 8
        assert bi.sensor_function == BinaryInputType.PRESENCE  # unchanged

    def test_set_binary_input_unknown_index(self):
        host, vdc, device, vdsd, bi = self._setup()

        incoming = {
            "binaryInputSettings": {
                "99": {"group": 1},
            },
        }

        # Should not raise.
        host._apply_vdsd_set_property(vdsd, incoming)
        assert bi.group == 0  # unchanged

    def test_set_property_via_message(self):
        """Full message dispatch for setProperty binaryInputSettings."""
        host, vdc, device, vdsd, bi = self._setup()

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_SET_PROPERTY
        msg.message_id = 42
        msg.vdsm_request_set_property.dSUID = str(vdsd.dsuid)

        # Build property tree: binaryInputSettings.0.group = 6
        bi_elem = msg.vdsm_request_set_property.properties.add()
        bi_elem.name = "binaryInputSettings"
        idx_elem = bi_elem.elements.add()
        idx_elem.name = "0"
        group_elem = idx_elem.elements.add()
        group_elem.name = "group"
        group_elem.value.v_uint64 = 6

        resp = host._handle_set_property(msg)

        assert resp.generic_response.code == pb.ERR_OK
        assert bi.group == 6


# ===========================================================================
# Auto-save triggering
# ===========================================================================


class TestBinaryInputAutoSave:
    """Tests that settings changes trigger auto-save."""

    def test_group_setter_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            bi.group = 5
            mock_save.assert_called()

    def test_sensor_function_setter_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            bi.sensor_function = BinaryInputType.RAIN
            mock_save.assert_called()

    def test_apply_settings_triggers_auto_save(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host.add_vdc(vdc)

        with patch.object(host, "_schedule_auto_save") as mock_save:
            bi.apply_settings({"group": 3})
            mock_save.assert_called()


# ===========================================================================
# Age calculation
# ===========================================================================


class TestBinaryInputAge:
    """Tests for the age property."""

    def test_age_none_initially(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        assert bi.age is None

    @pytest.mark.asyncio
    async def test_age_after_update(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_value(True)
        age = bi.age

        assert age is not None
        assert age >= 0.0
        assert age < 1.0  # should be near-instant

    @pytest.mark.asyncio
    async def test_age_increases(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)

        await bi.update_value(True)
        age1 = bi.age
        assert age1 is not None

        # Nudge the timestamp back 1 second.
        assert bi._last_update is not None
        bi._last_update -= 1.0
        age2 = bi.age
        assert age2 is not None

        assert age2 > age1


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
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        vdsd._announced = True

        session = _make_mock_session()
        bi.start_alive_timer(session)

        # No session passed — should use stored session.
        await bi.update_value(True)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_extended_value_uses_stored_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        vdsd._announced = True

        session = _make_mock_session()
        bi.start_alive_timer(session)

        await bi.update_extended_value(2)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_error_uses_stored_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        vdsd._announced = True

        session = _make_mock_session()
        bi.start_alive_timer(session)

        await bi.update_error(InputError.LOW_BATTERY)

        session.send_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_session_overrides_stored(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)
        vdsd._announced = True

        stored_session = _make_mock_session()
        explicit_session = _make_mock_session()
        bi.start_alive_timer(stored_session)

        # Explicit session takes precedence.
        await bi.update_value(True, explicit_session)

        explicit_session.send_notification.assert_called_once()
        stored_session.send_notification.assert_not_called()


# ===========================================================================
# Vdsd announce/vanish alive timer integration
# ===========================================================================


class TestVdsdAliveTimerLifecycle:
    """Tests that Vdsd announce/vanish/reset manage session storage."""

    def test_add_binary_input_after_announce_starts_timer(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        assert bi._session is session

    def test_reset_announcement_clears_all_sessions(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        bi0 = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_function=BinaryInputType.PRESENCE,
        )
        bi1 = BinaryInput(
            vdsd=vdsd,
            ds_index=1,
            sensor_function=BinaryInputType.WINDOW_OPEN,
        )
        vdsd.add_binary_input(bi0)
        vdsd.add_binary_input(bi1)

        session = _make_mock_session()
        bi0.start_alive_timer(session)
        bi1.start_alive_timer(session)

        vdsd.reset_announcement()

        assert bi0._session is None
        assert bi1._session is None

    def test_vdsd_stores_session_on_announce(self):
        """When vdSD is announced, it stores the session."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        session = _make_mock_session()
        # Simulate announce() setting the session.
        vdsd._announced = True
        vdsd._session = session

        assert vdsd._session is session

        vdsd.reset_announcement()
        assert vdsd._session is None


# ===========================================================================
# Force parameter for _push_state
# ===========================================================================


class TestBinaryInputPushStateForce:
    """Tests for the force parameter in _push_state."""

    @pytest.mark.asyncio
    async def test_push_state_accepts_force_keyword(self):
        """Regression: _push_state must accept force=True without TypeError."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        bi = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_function=BinaryInputType.MOTION,
            input_usage=BinaryInputUsage.ROOM_CLIMATE,
            name="Test Input",
        )
        # Should not raise TypeError
        await bi._push_state(None, force=True)
        await bi._push_state(None, force=False)
