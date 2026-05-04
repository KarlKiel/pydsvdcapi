"""Tests for device event handling (§4.7)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.device_event import DeviceEvent
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
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
        "implementation_id": "x-test-evt",
        "name": "Test Event vDC",
        "model": "Test Event v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("evt-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "Event Test vdSD",
        "model": "Test Event vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
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
# DeviceEvent construction and properties
# ===========================================================================


class TestDeviceEventConstruction:
    """Tests for DeviceEvent creation and property access."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="doorbell")

        assert evt.vdsd is vdsd
        assert evt.ds_index == 0
        assert evt.name == "doorbell"
        assert evt.description is None

    def test_full_construction(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(
            vdsd=vdsd,
            ds_index=1,
            name="motion",
            description="Motion detected",
        )
        assert evt.ds_index == 1
        assert evt.name == "motion"
        assert evt.description == "Motion detected"

    def test_name_setter(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, name="old")
        evt.name = "new"
        assert evt.name == "new"

    def test_description_setter(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, name="x")
        evt.description = "Updated"
        assert evt.description == "Updated"
        evt.description = None
        assert evt.description is None

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=2, name="tap")
        r = repr(evt)
        assert "ds_index=2" in r
        assert "name='tap'" in r


# ===========================================================================
# Description properties
# ===========================================================================


class TestDeviceEventDescriptionProperties:
    """Tests for get_description_properties()."""

    def test_name_only(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, name="doorbell")
        props = evt.get_description_properties()
        assert props == {"name": "doorbell"}
        assert "description" not in props

    def test_with_description(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, name="ring", description="Ring pressed")
        props = evt.get_description_properties()
        assert props == {"name": "ring", "description": "Ring pressed"}


# ===========================================================================
# Persistence
# ===========================================================================


class TestDeviceEventPersistence:
    """Tests for get_property_tree() and _apply_state()."""

    def test_property_tree_minimal(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        tree = evt.get_property_tree()
        assert tree == {"dsIndex": 0, "name": "bell"}

    def test_property_tree_full(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(
            vdsd=vdsd,
            ds_index=3,
            name="knock",
            description="Someone knocked",
        )
        tree = evt.get_property_tree()
        assert tree == {
            "dsIndex": 3,
            "name": "knock",
            "description": "Someone knocked",
        }

    def test_apply_state(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="")
        evt._apply_state({"name": "restored", "description": "From YAML"})
        assert evt.name == "restored"
        assert evt.description == "From YAML"

    def test_apply_state_partial(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="orig", description="kept")
        evt._apply_state({"name": "changed"})
        assert evt.name == "changed"
        # description not in state → unchanged
        assert evt.description == "kept"

    def test_roundtrip(self):
        """get_property_tree → _apply_state roundtrip."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(
            vdsd=vdsd,
            ds_index=5,
            name="press",
            description="Button press",
        )
        tree = evt.get_property_tree()

        restored = DeviceEvent(vdsd=vdsd, ds_index=5, name="")
        restored._apply_state(tree)
        assert restored.name == "press"
        assert restored.description == "Button press"


# ===========================================================================
# Vdsd device event management
# ===========================================================================


class TestVdsdDeviceEventManagement:
    """Tests for Vdsd.add/remove/get_device_event."""

    def test_add_and_get(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        vdsd.add_device_event(evt)

        assert vdsd.get_device_event(0) is evt
        assert len(vdsd.device_events) == 1

    def test_add_replaces_at_same_index(self):
        _, _, _, vdsd = _make_stack()
        evt1 = DeviceEvent(vdsd=vdsd, ds_index=0, name="old")
        evt2 = DeviceEvent(vdsd=vdsd, ds_index=0, name="new")
        vdsd.add_device_event(evt1)
        vdsd.add_device_event(evt2)

        assert vdsd.get_device_event(0) is evt2
        assert len(vdsd.device_events) == 1

    def test_add_wrong_vdsd_raises(self):
        _, _, _, vdsd1 = _make_stack()
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(
            vdc2,
            dsuid=DsUid.from_name_in_space("other", DsUidNamespace.VDC),
        )
        vdsd2 = _make_vdsd(dev2, name="Other")

        evt = DeviceEvent(vdsd=vdsd2, ds_index=0, name="x")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd1.add_device_event(evt)

    def test_remove(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        vdsd.add_device_event(evt)
        removed = vdsd.remove_device_event(0)

        assert removed is evt
        assert vdsd.get_device_event(0) is None
        assert len(vdsd.device_events) == 0

    def test_remove_missing(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.remove_device_event(99) is None

    def test_get_missing(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.get_device_event(0) is None

    def test_multiple_events(self):
        _, _, _, vdsd = _make_stack()
        evt0 = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        evt1 = DeviceEvent(vdsd=vdsd, ds_index=1, name="motion")
        vdsd.add_device_event(evt0)
        vdsd.add_device_event(evt1)

        assert len(vdsd.device_events) == 2
        assert vdsd.get_device_event(0).name == "bell"
        assert vdsd.get_device_event(1).name == "motion"

    def test_device_events_property_is_copy(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        vdsd.add_device_event(evt)
        copy = vdsd.device_events
        copy[99] = "injected"
        assert vdsd.get_device_event(99) is None


# ===========================================================================
# get_properties exposure
# ===========================================================================


class TestDeviceEventsInProperties:
    """Tests for deviceEventDescriptions in get_properties()."""

    def test_no_events_no_key(self):
        _, _, _, vdsd = _make_stack()
        props = vdsd.get_properties()
        assert "deviceEventDescriptions" not in props

    def test_events_in_properties(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(
            vdsd=vdsd,
            ds_index=0,
            name="bell",
            description="Doorbell",
        )
        vdsd.add_device_event(evt)

        props = vdsd.get_properties()
        desc = props["deviceEventDescriptions"]
        assert "bell" in desc
        assert desc["bell"]["name"] == "bell"
        assert desc["bell"]["description"] == "Doorbell"

    def test_multiple_events_in_properties(self):
        _, _, _, vdsd = _make_stack()
        vdsd.add_device_event(DeviceEvent(vdsd=vdsd, ds_index=0, name="bell"))
        vdsd.add_device_event(DeviceEvent(vdsd=vdsd, ds_index=1, name="motion"))

        props = vdsd.get_properties()
        desc = props["deviceEventDescriptions"]
        assert len(desc) == 2
        assert desc["bell"]["name"] == "bell"
        assert desc["motion"]["name"] == "motion"


# ===========================================================================
# Vdsd persistence of device events
# ===========================================================================


class TestDeviceEventVdsdPersistence:
    """Tests for device events in vdsd property tree / apply state."""

    def test_property_tree_includes_events(self):
        _, _, _, vdsd = _make_stack()
        vdsd.add_device_event(
            DeviceEvent(vdsd=vdsd, ds_index=0, name="bell", description="Doorbell ring")
        )
        tree = vdsd.get_property_tree()

        assert "deviceEvents" in tree
        assert len(tree["deviceEvents"]) == 1
        assert tree["deviceEvents"][0]["name"] == "bell"
        assert tree["deviceEvents"][0]["dsIndex"] == 0

    def test_property_tree_no_events_key(self):
        _, _, _, vdsd = _make_stack()
        tree = vdsd.get_property_tree()
        assert "deviceEvents" not in tree

    def test_apply_state_restores_events(self):
        _, _, _, vdsd = _make_stack()
        state = {
            "deviceEvents": [
                {"dsIndex": 0, "name": "bell", "description": "Ring"},
                {"dsIndex": 1, "name": "motion"},
            ]
        }
        vdsd._apply_state(state)

        assert len(vdsd.device_events) == 2
        assert vdsd.get_device_event(0).name == "bell"
        assert vdsd.get_device_event(0).description == "Ring"
        assert vdsd.get_device_event(1).name == "motion"
        assert vdsd.get_device_event(1).description is None

    def test_apply_state_updates_existing_event(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="old")
        vdsd.add_device_event(evt)

        vdsd._apply_state(
            {
                "deviceEvents": [
                    {"dsIndex": 0, "name": "updated", "description": "New"},
                ]
            }
        )
        assert vdsd.get_device_event(0).name == "updated"
        assert vdsd.get_device_event(0) is evt  # Same instance

    def test_full_roundtrip(self):
        """get_property_tree → new vdsd._apply_state roundtrip."""
        _, _, _, vdsd = _make_stack()
        vdsd.add_device_event(
            DeviceEvent(vdsd=vdsd, ds_index=0, name="bell", description="Ding dong")
        )
        vdsd.add_device_event(DeviceEvent(vdsd=vdsd, ds_index=1, name="motion"))
        tree = vdsd.get_property_tree()

        # Create a new vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        vdsd2._apply_state(tree)

        assert len(vdsd2.device_events) == 2
        assert vdsd2.get_device_event(0).name == "bell"
        assert vdsd2.get_device_event(0).description == "Ding dong"
        assert vdsd2.get_device_event(1).name == "motion"
        assert vdsd2.get_device_event(1).description is None


# ===========================================================================
# Raising events (push notification)
# ===========================================================================


class TestRaiseDeviceEvent:
    """Tests for DeviceEvent.raise_event()."""

    @pytest.mark.asyncio
    async def test_raise_event_sends_notification(self):
        """raise_event sends a VDC_SEND_PUSH_NOTIFICATION message."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        await evt.raise_event(session)

        session.send_notification.assert_awaited_once()
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION

    @pytest.mark.asyncio
    async def test_raise_event_contains_dsuid(self):
        """The push message contains the vdSD's dSUID."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        await evt.raise_event(session)

        msg = session.send_notification.call_args[0][0]
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)

    @pytest.mark.asyncio
    async def test_raise_event_wire_contains_deviceevents(self):
        """The message carries the deviceevents field natively."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        await evt.raise_event(session)

        msg = session.send_notification.call_args[0][0]
        notif = msg.vdc_send_push_notification

        assert notif.dSUID == str(vdsd.dsuid)
        assert len(notif.deviceevents) == 1
        assert notif.deviceevents[0].name == "bell"

    @pytest.mark.asyncio
    async def test_raise_event_different_index(self):
        """Event at index 2 produces element name '2'."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=2, name="motion")

        session = _make_mock_session()
        await evt.raise_event(session)

        msg = session.send_notification.call_args[0][0]
        notif = msg.vdc_send_push_notification

        assert notif.deviceevents[0].name == "motion"

    @pytest.mark.asyncio
    async def test_raise_event_uses_vdsd_session(self):
        """When no session argument is given, uses the vdSD's session."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        vdsd._session = session
        await evt.raise_event()

        session.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raise_event_no_session_does_not_raise(self):
        """No active session → warning logged, no exception."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        # vdsd._session is None by default.
        await evt.raise_event()  # Should not raise.

    @pytest.mark.asyncio
    async def test_raise_event_inactive_session_does_not_send(self):
        """Inactive session → skipped."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        session.is_active = False
        await evt.raise_event(session)

        session.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raise_event_connection_error_handled(self):
        """ConnectionError in send_notification is caught."""
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")

        session = _make_mock_session()
        session.send_notification.side_effect = ConnectionError("gone")
        await evt.raise_event(session)
        # No exception raised — just logged.


# ===========================================================================
# Vdsd.raise_device_event convenience method
# ===========================================================================


class TestVdsdRaiseDeviceEvent:
    """Tests for Vdsd.raise_device_event()."""

    @pytest.mark.asyncio
    async def test_raises_registered_event(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        vdsd.add_device_event(evt)

        session = _make_mock_session()
        vdsd._session = session
        await vdsd.raise_device_event(0)

        session.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_with_explicit_session(self):
        _, _, _, vdsd = _make_stack()
        evt = DeviceEvent(vdsd=vdsd, ds_index=0, name="bell")
        vdsd.add_device_event(evt)

        session = _make_mock_session()
        await vdsd.raise_device_event(0, session=session)

        session.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_key_error_for_missing_event(self):
        _, _, _, vdsd = _make_stack()
        with pytest.raises(KeyError, match="No DeviceEvent"):
            await vdsd.raise_device_event(42)
