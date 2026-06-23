"""Tests for on_settings_changed callbacks and push_settings() methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pydsvdcapi as api
from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.button_input import ButtonInput
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    BinaryInputType,
    BinaryInputUsage,
    ButtonElementID,
    ButtonType,
    ColorGroup,
    OutputFunction,
    OutputUsage,
    SensorType,
    SensorUsage,
)
from pydsvdcapi.output import Output
from pydsvdcapi.property_handling import elements_to_dict
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import VdcHost
from pydsvdcapi.vdsd import Device, Vdsd

# ---------------------------------------------------------------------------
# Shared helpers
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
        "implementation_id": "x-test-cb",
        "name": "Test CB vDC",
        "model": "Test CB v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid(name: str = "cb-test-device") -> DsUid:
    return DsUid.from_name_in_space(name, DsUidNamespace.VDC)


def _make_device(vdc: Vdc, name: str = "cb-test-device") -> Device:
    return Device(vdc=vdc, dsuid=_base_dsuid(name))


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.BLACK,
        "name": "CB Test vdSD",
        "model": "Test CB vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
    return session


def _make_binary_input(vdsd: Vdsd, **kwargs: Any) -> BinaryInput:
    defaults: dict[str, Any] = {
        "vdsd": vdsd,
        "ds_index": 0,
        "sensor_function": BinaryInputType.PRESENCE,
        "input_usage": BinaryInputUsage.ROOM_CLIMATE,
        "name": "Test PIR",
    }
    defaults.update(kwargs)
    return BinaryInput(**defaults)


def _make_button_input(vdsd: Vdsd, **kwargs: Any) -> ButtonInput:
    defaults: dict[str, Any] = {
        "vdsd": vdsd,
        "ds_index": 0,
        "button_type": ButtonType.SINGLE_PUSHBUTTON,
        "button_element_id": ButtonElementID.CENTER,
        "button_id": 0,
        "name": "Test Button",
    }
    defaults.update(kwargs)
    return ButtonInput(**defaults)


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


def _scaffold() -> tuple[VdcHost, Vdc, Device, Vdsd]:
    host = _make_host()
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdc, device, vdsd


# ===========================================================================
# BinaryInput
# ===========================================================================


class TestBinaryInputCallback:
    """Tests for BinaryInput.on_settings_changed callback."""

    def test_binary_input_callback_default_is_none(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd)
        assert bi.on_settings_changed is None

    def test_binary_input_callback_settable_and_clearable(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd)

        async def cb(b, settings):
            pass

        bi.on_settings_changed = cb
        assert bi.on_settings_changed is cb

        bi.on_settings_changed = None
        assert bi.on_settings_changed is None

    async def test_binary_input_callback_receives_correct_args(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd)

        received: list[Any] = []

        async def cb(component, settings):
            received.append((component, settings))

        bi.on_settings_changed = cb
        await bi.on_settings_changed(bi, {"group": 5})

        assert len(received) == 1
        assert received[0][0] is bi
        assert received[0][1] == {"group": 5}

    async def test_binary_input_push_settings_no_session(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd)
        bi._session = None
        # Must not raise
        await bi.push_settings()

    async def test_binary_input_push_settings_not_announced(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd)
        vdsd.add_binary_input(bi)

        session = _make_mock_session()
        bi._session = session
        vdsd._announced = False

        await bi.push_settings()
        session.send_notification.assert_not_called()

    async def test_binary_input_push_settings_sends_notification(self):
        _, _, _, vdsd = _scaffold()
        bi = _make_binary_input(vdsd, ds_index=2, group=3,
                                sensor_function=BinaryInputType.SMOKE)
        vdsd.add_binary_input(bi)

        session = _make_mock_session()
        bi._session = session
        vdsd._announced = True

        await bi.push_settings()

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)

        assert "binaryInputSettings" in props
        inner = props["binaryInputSettings"][str(bi.ds_index)]
        assert "group" in inner
        assert "sensorFunction" in inner


# ===========================================================================
# ButtonInput
# ===========================================================================


class TestButtonInputCallback:
    """Tests for ButtonInput.on_settings_changed callback and push_settings."""

    def test_button_input_callback_default_is_none(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.on_settings_changed is None

    async def test_button_input_push_settings_no_session(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn._session = None
        # Must not raise
        await btn.push_settings()

    async def test_button_input_push_settings_sends_notification(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd, ds_index=1)
        vdsd.add_button_input(btn)

        session = _make_mock_session()
        btn._session = session
        vdsd._announced = True

        await btn.push_settings()

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)

        assert "buttonInputSettings" in props
        inner = props["buttonInputSettings"][str(btn.ds_index)]
        assert "group" in inner
        assert "function" in inner
        assert "mode" in inner


# ===========================================================================
# SensorInput
# ===========================================================================


class TestSensorInputCallback:
    """Tests for SensorInput.on_settings_changed callback and push_settings."""

    def test_sensor_input_callback_default_is_none(self):
        _, _, _, vdsd = _scaffold()
        si = _make_sensor_input(vdsd)
        assert si.on_settings_changed is None

    async def test_sensor_input_push_settings_no_session(self):
        _, _, _, vdsd = _scaffold()
        si = _make_sensor_input(vdsd)
        si._session = None
        # Must not raise
        await si.push_settings()

    async def test_sensor_input_push_settings_sends_notification(self):
        _, _, _, vdsd = _scaffold()
        si = _make_sensor_input(vdsd, ds_index=0)
        vdsd.add_sensor_input(si)

        session = _make_mock_session()
        si._session = session
        vdsd._announced = True

        await si.push_settings()

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)

        assert "sensorSettings" in props
        inner = props["sensorSettings"][str(si.ds_index)]
        assert "group" in inner
        assert "minPushInterval" in inner
        assert "changesOnlyInterval" in inner


# ===========================================================================
# Output
# ===========================================================================


class TestOutputCallback:
    """Tests for Output.on_settings_changed callback and push_settings."""

    def test_output_callback_default_is_none(self):
        _, _, _, vdsd = _scaffold()
        out = _make_output(vdsd)
        assert out.on_settings_changed is None

    async def test_output_push_settings_no_session(self):
        _, _, _, vdsd = _scaffold()
        out = _make_output(vdsd)
        out._session = None
        # Must not raise
        await out.push_settings()

    async def test_output_push_settings_not_announced(self):
        _, _, _, vdsd = _scaffold()
        out = _make_output(vdsd)
        vdsd.set_output(out)

        session = _make_mock_session()
        out.start_session(session)
        vdsd._announced = False

        await out.push_settings()
        session.send_notification.assert_not_called()

    async def test_output_push_settings_sends_notification(self):
        _, _, _, vdsd = _scaffold()
        out = _make_output(vdsd)
        vdsd.set_output(out)

        session = _make_mock_session()
        out.start_session(session)
        vdsd._announced = True

        await out.push_settings()

        session.send_notification.assert_called_once()
        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(msg.vdc_send_push_notification.changedproperties)

        assert "outputSettings" in props
        inner = props["outputSettings"]
        assert "mode" in inner


# ===========================================================================
# Exports
# ===========================================================================


class TestCallbackTypeExports:
    """Verify all four callback types are exported from pydsvdcapi."""

    def test_callback_types_exported(self):
        assert hasattr(api, "BinaryInputSettingsChangedCallback")
        assert hasattr(api, "ButtonInputSettingsChangedCallback")
        assert hasattr(api, "SensorInputSettingsChangedCallback")
        assert hasattr(api, "OutputSettingsChangedCallback")
