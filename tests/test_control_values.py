"""Tests for control value handling (§7.3.8 / §4.11)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup, OutputFunction, OutputUsage
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
        "implementation_id": "x-test-cv",
        "name": "Test CV vDC",
        "model": "Test CV v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("cv-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "CV Test vdSD",
        "model": "Test CV vdSD",
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
    """Create a full host→vdc→device→vdsd stack."""
    host = _make_host()
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device, **kwargs)
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdc, device, vdsd


# ===========================================================================
# Vdsd control value storage
# ===========================================================================


class TestVdsdControlValues:
    """Tests for Vdsd control-value storage and accessors."""

    @pytest.mark.asyncio
    async def test_set_and_get_control_value(self):
        """set_control_value stores and get_control_value retrieves."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 42.5)
        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == 42.5
        assert entry["group"] is None
        assert entry["zone_id"] is None

    @pytest.mark.asyncio
    async def test_set_control_value_with_group_and_zone(self):
        """Optional group and zone_id are stored."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", -50.0, group=8, zone_id=42)
        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == -50.0
        assert entry["group"] == 8
        assert entry["zone_id"] == 42

    @pytest.mark.asyncio
    async def test_overwrite_control_value(self):
        """Subsequent set overwrites the previous value."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 10.0)
        await vdsd.set_control_value("heatingLevel", 99.0, group=3)
        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == 99.0
        assert entry["group"] == 3

    @pytest.mark.asyncio
    async def test_multiple_control_values(self):
        """Different control value names are stored independently."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 10.0)
        await vdsd.set_control_value("coolingCapacity", 75.0)
        await vdsd.set_control_value("outsideTemperature", 22.5)

        assert vdsd.get_control_value("heatingLevel")["value"] == 10.0
        assert vdsd.get_control_value("coolingCapacity")["value"] == 75.0
        assert vdsd.get_control_value("outsideTemperature")["value"] == 22.5

    def test_get_missing_control_value_returns_none(self):
        """get_control_value returns None for unset names."""
        _, _, _, vdsd = _make_stack()
        assert vdsd.get_control_value("nonExistent") is None

    def test_control_values_property_empty(self):
        """control_values returns empty dict when nothing stored."""
        _, _, _, vdsd = _make_stack()
        assert vdsd.control_values == {}

    @pytest.mark.asyncio
    async def test_control_values_property_snapshot(self):
        """control_values returns a snapshot of all stored values."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 33.0)
        await vdsd.set_control_value("coolingCapacity", 66.0)

        cv = vdsd.control_values
        assert len(cv) == 2
        assert cv["heatingLevel"]["value"] == 33.0
        assert cv["coolingCapacity"]["value"] == 66.0

    @pytest.mark.asyncio
    async def test_control_values_property_is_copy(self):
        """Mutating the returned dict does not affect internal state."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 50.0)

        cv = vdsd.control_values
        cv["heatingLevel"]["value"] = 999.0
        cv["injected"] = {"value": 1.0, "group": None, "zone_id": None}

        # Internal state should be unaffected.
        assert vdsd.get_control_value("heatingLevel")["value"] == 50.0
        assert vdsd.get_control_value("injected") is None

    @pytest.mark.asyncio
    async def test_get_control_value_returns_copy(self):
        """Mutating a get_control_value result doesn't change internals."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 50.0)

        entry = vdsd.get_control_value("heatingLevel")
        entry["value"] = 999.0

        assert vdsd.get_control_value("heatingLevel")["value"] == 50.0


# ===========================================================================
# Callback
# ===========================================================================


class TestControlValueCallback:
    """Tests for the on_control_value callback."""

    @pytest.mark.asyncio
    async def test_sync_callback_invoked(self):
        """A synchronous callback is invoked on set_control_value."""
        _, _, _, vdsd = _make_stack()
        calls = []

        def on_cv(dev, name, value, group, zone_id):
            calls.append((dev, name, value, group, zone_id))

        vdsd.on_control_value = on_cv
        await vdsd.set_control_value("heatingLevel", 42.0, group=1)

        assert len(calls) == 1
        assert calls[0] == (vdsd, "heatingLevel", 42.0, 1, None)

    @pytest.mark.asyncio
    async def test_async_callback_invoked(self):
        """An async callback is awaited on set_control_value."""
        _, _, _, vdsd = _make_stack()
        calls = []

        async def on_cv(dev, name, value, group, zone_id):
            calls.append((dev, name, value, group, zone_id))

        vdsd.on_control_value = on_cv
        await vdsd.set_control_value("temp", 21.5, zone_id=7)

        assert len(calls) == 1
        assert calls[0] == (vdsd, "temp", 21.5, None, 7)

    @pytest.mark.asyncio
    async def test_no_callback_does_not_raise(self):
        """No callback set should not cause any error."""
        _, _, _, vdsd = _make_stack()
        assert vdsd.on_control_value is None
        await vdsd.set_control_value("heatingLevel", 10.0)
        # No assertion needed — just verifying no exception.

    @pytest.mark.asyncio
    async def test_callback_set_and_cleared(self):
        """Callback can be set then removed."""
        _, _, _, vdsd = _make_stack()
        calls = []

        vdsd.on_control_value = lambda *a: calls.append(a)
        await vdsd.set_control_value("x", 1.0)
        assert len(calls) == 1

        vdsd.on_control_value = None
        await vdsd.set_control_value("x", 2.0)
        assert len(calls) == 1  # No additional call.


# ===========================================================================
# get_properties exposure
# ===========================================================================


class TestControlValuesInProperties:
    """Tests for control value exposure in get_properties()."""

    def test_no_control_values_no_key(self):
        """When no control values set, get_properties has no controlValues."""
        _, _, _, vdsd = _make_stack()
        props = vdsd.get_properties()
        assert "controlValues" not in props

    @pytest.mark.asyncio
    async def test_control_values_in_properties(self):
        """Stored control values appear in get_properties."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 55.0, group=8)
        await vdsd.set_control_value("outsideTemp", 18.0)

        props = vdsd.get_properties()
        cv = props["controlValues"]
        assert cv["heatingLevel"]["value"] == 55.0
        assert cv["heatingLevel"]["group"] == 8
        assert cv["outsideTemp"]["value"] == 18.0
        assert cv["outsideTemp"]["group"] is None

    @pytest.mark.asyncio
    async def test_control_values_not_in_property_tree(self):
        """Control values are volatile and NOT persisted."""
        _, _, _, vdsd = _make_stack()
        await vdsd.set_control_value("heatingLevel", 42.0)

        tree = vdsd.get_property_tree()
        assert "controlValues" not in tree
        # Also verify they don't appear anywhere in the tree values.
        flat = str(tree)
        assert "heatingLevel" not in flat


# ===========================================================================
# VdcHost dispatch
# ===========================================================================


class TestVdcHostControlValueDispatch:
    """Tests for VdcHost routing SET_CONTROL_VALUE to vdSDs."""

    @pytest.mark.asyncio
    async def test_dispatch_set_control_value(self):
        """SET_CONTROL_VALUE notification routes to vdsd.set_control_value."""
        host, vdc, device, vdsd = _make_stack()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 72.5

        session = _make_mock_session()
        result = await host._dispatch_message(session, msg)
        assert result is None

        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == 72.5

    @pytest.mark.asyncio
    async def test_dispatch_with_group_and_zone(self):
        """Group and zone_id are passed through from the notification."""
        host, vdc, device, vdsd = _make_stack()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = -30.0
        msg.vdsm_send_set_control_value.group = 8
        msg.vdsm_send_set_control_value.zone_id = 99

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == -30.0
        assert entry["group"] == 8
        assert entry["zone_id"] == 99

    @pytest.mark.asyncio
    async def test_dispatch_multiple_dsuids(self):
        """SET_CONTROL_VALUE with multiple dSUIDs routes to all."""
        host = _make_host()
        vdc = _make_vdc(host)

        # Device 1.
        dsuid1 = DsUid.from_name_in_space("cv-dev-1", DsUidNamespace.VDC)
        dev1 = Device(vdc=vdc, dsuid=dsuid1)
        vdsd1 = _make_vdsd(dev1, name="Dev 1")
        dev1.add_vdsd(vdsd1)
        vdc.add_device(dev1)

        # Device 2.
        dsuid2 = DsUid.from_name_in_space("cv-dev-2", DsUidNamespace.VDC)
        dev2 = Device(vdc=vdc, dsuid=dsuid2)
        vdsd2 = _make_vdsd(dev2, name="Dev 2")
        dev2.add_vdsd(vdsd2)
        vdc.add_device(dev2)

        host.add_vdc(vdc)

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd1.dsuid))
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd2.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 50.0

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert vdsd1.get_control_value("heatingLevel")["value"] == 50.0
        assert vdsd2.get_control_value("heatingLevel")["value"] == 50.0

    @pytest.mark.asyncio
    async def test_dispatch_unknown_dsuid_logs_warning(self):
        """Unknown dSUID is silently skipped (logged but no error)."""
        host, vdc, device, vdsd = _make_stack()

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append("DEADBEEF" * 4)
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 10.0

        session = _make_mock_session()
        # Should not raise.
        await host._dispatch_message(session, msg)

        # The real vdSD did not receive any value.
        assert vdsd.get_control_value("heatingLevel") is None

    @pytest.mark.asyncio
    async def test_dispatch_triggers_callback(self):
        """Dispatch routes through to the on_control_value callback."""
        host, vdc, device, vdsd = _make_stack()
        calls = []

        async def on_cv(dev, name, value, group, zone_id):
            calls.append((name, value, group, zone_id))

        vdsd.on_control_value = on_cv

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 88.0

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        assert len(calls) == 1
        assert calls[0] == ("heatingLevel", 88.0, None, None)

    @pytest.mark.asyncio
    async def test_dispatch_callback_exception_does_not_propagate(self):
        """An exception in the callback is caught, not propagated."""
        host, vdc, device, vdsd = _make_stack()

        async def bad_cb(dev, name, value, group, zone_id):
            raise RuntimeError("boom")

        vdsd.on_control_value = bad_cb

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 1.0

        session = _make_mock_session()
        # Should not raise — exception is caught and logged.
        await host._dispatch_message(session, msg)

        # Value should still be stored despite the callback error.
        # (The set_control_value stores before calling the callback.)
        # Actually, the exception is in the callback, which is called
        # inside set_control_value. The VdcHost handler wraps the whole
        # call in try/except, so the value IS stored before the callback.
        entry = vdsd.get_control_value("heatingLevel")
        assert entry is not None
        assert entry["value"] == 1.0

    @pytest.mark.asyncio
    async def test_dispatch_does_not_invoke_on_message(self):
        """SET_CONTROL_VALUE should NOT fall through to on_message."""
        host, vdc, device, vdsd = _make_stack()
        on_message_calls = []

        async def on_msg(session, msg):
            on_message_calls.append(msg)
            return None

        host.on_message = on_msg

        msg = pb.Message()
        msg.type = pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE
        msg.vdsm_send_set_control_value.dSUID.append(str(vdsd.dsuid))
        msg.vdsm_send_set_control_value.name = "heatingLevel"
        msg.vdsm_send_set_control_value.value = 5.0

        session = _make_mock_session()
        await host._dispatch_message(session, msg)

        # The user callback should NOT have been called.
        assert len(on_message_calls) == 0
