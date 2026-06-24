"""Tests for the Device and Vdsd classes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.button_input import ButtonInput
from pydsvdcapi.device_property import DeviceProperty
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    BinaryInputType,
    BinaryInputUsage,
    ButtonType,
    ColorGroup,
    DeviceLifecycleState,
    OutputChannelType,
    OutputFunction,
    OutputMode,
    SensorType,
    SensorUsage,
)
from pydsvdcapi.output import Output
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import VdcHost
from pydsvdcapi.vdsd import ENTITY_TYPE_VDSD, Device, Vdsd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_host(tmp_path: Path | None = None, **kwargs: Any) -> VdcHost:
    kw: dict[str, Any] = {"name": "Test Host", "mac": "AA:BB:CC:DD:EE:FF"}
    if tmp_path is not None:
        kw["state_path"] = str(tmp_path / "state.yaml")
    kw.update(kwargs)
    host = VdcHost(**kw)
    host._cancel_auto_save()
    return host


def _make_vdc(host: VdcHost, **kwargs: Any) -> Vdc:
    defaults: dict[str, Any] = {
        "host": host,
        "implementation_id": "x-test-light",
        "name": "Test Light vDC",
        "model": "Test Light v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("test-device-1", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(
    device: Device,
    subdevice_index: int = 0,
    primary_group: ColorGroup = ColorGroup.YELLOW,
    **kwargs: Any,
) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "subdevice_index": subdevice_index,
        "primary_group": primary_group,
        "name": f"Test vdSD {subdevice_index}",
        "model": "Test vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


def _make_mock_session(
    response_code: int = 0,
) -> VdcSession:
    session = MagicMock(spec=VdcSession)
    session.is_active = True

    response = pb.Message()
    response.type = pb.GENERIC_RESPONSE
    response.generic_response.code = response_code

    session.send_request = AsyncMock(return_value=response)
    session.send_notification = AsyncMock()
    return session


# ===========================================================================
# Vdsd — construction and properties
# ===========================================================================


class TestVdsdConstruction:
    """Tests for Vdsd creation and default values."""

    def test_default_construction(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.entity_type == ENTITY_TYPE_VDSD
        assert vdsd.entity_type == "vdSD"
        assert vdsd.subdevice_index == 0
        assert vdsd.primary_group == ColorGroup.YELLOW
        assert vdsd.name == "Test vdSD 0"
        assert vdsd.zone_id == 0
        assert vdsd.is_announced is False
        assert vdsd.active is True
        assert vdsd.device is device

    def test_dsuid_derived_from_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        base = _base_dsuid()
        device = _make_device(vdc, base)
        vdsd = _make_vdsd(device, subdevice_index=3)

        expected = base.derive_subdevice(3)
        assert vdsd.dsuid == expected
        assert vdsd.dsuid.subdevice_index == 3

    def test_dsuid_subdevice_zero(self):
        host = _make_host()
        vdc = _make_vdc(host)
        base = _base_dsuid()
        device = _make_device(vdc, base)
        vdsd = _make_vdsd(device, subdevice_index=0)

        assert vdsd.dsuid == base.device_base()

    def test_display_id_is_hex_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.display_id == str(vdsd.dsuid)
        assert len(vdsd.display_id) == 34

    def test_model_uid_derived(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, model="Custom Model X")

        assert vdsd.model_uid is not None
        assert len(vdsd.model_uid) == 34  # full dSUID hex

    def test_explicit_model_uid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, model_uid="my-uid-123")

        assert vdsd.model_uid == "my-uid-123"

    def test_optional_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            hardware_version="hw-1.0",
            hardware_guid="macaddress:AABBCCDDEEFF",
            vendor_name="TestVendor",
            config_url="http://device.local",
            device_icon_16=b"\x89PNG",
            device_icon_name="icon-light",
            device_class="dS-FD",
            device_class_version="1",
        )

        assert vdsd.hardware_version == "hw-1.0"
        assert vdsd.hardware_guid == "macaddress:AABBCCDDEEFF"
        assert vdsd.vendor_name == "TestVendor"
        assert vdsd.config_url == "http://device.local"
        assert vdsd.device_icon_16 == b"\x89PNG"
        assert vdsd.device_icon_name == "icon-light"
        assert vdsd.device_class == "dS-FD"
        assert vdsd.device_class_version == "1"

    def test_primary_group_black_default(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = Vdsd(
            device=device, primary_group=ColorGroup.BLACK, name="Test", model="Test"
        )

        assert vdsd.primary_group == ColorGroup.BLACK


# ===========================================================================
# DeviceLifecycleState enum
# ===========================================================================


class TestDeviceLifecycleStateEnum:
    """DeviceLifecycleState enum has all required values."""

    def test_all_states_exist(self):
        assert DeviceLifecycleState.ACTIVE == "active"
        assert DeviceLifecycleState.INACTIVE == "inactive"
        assert DeviceLifecycleState.MAINTENANCE == "maintenance"
        assert DeviceLifecycleState.ERROR == "error"
        assert DeviceLifecycleState.REMOVED == "removed"

    def test_active_is_truthy_active(self):
        assert DeviceLifecycleState.ACTIVE == DeviceLifecycleState.ACTIVE
        assert DeviceLifecycleState.INACTIVE != DeviceLifecycleState.ACTIVE


# ===========================================================================
# Vdsd — model features
# ===========================================================================


class TestVdsdModelFeatures:
    def test_empty_by_default(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.model_features == set()

    def test_initial_features(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            model_features={"blink", "identification"},
        )

        assert vdsd.model_features == {"blink", "identification"}

    def test_add_feature(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        vdsd.add_model_feature("blink")
        assert "blink" in vdsd.model_features

    def test_remove_feature(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, model_features={"blink", "dontcare"})

        vdsd.remove_model_feature("blink")
        assert "blink" not in vdsd.model_features
        assert "dontcare" in vdsd.model_features

    def test_remove_nonexistent_is_noop(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        vdsd.remove_model_feature("nonexistent")  # should not raise

    def test_model_features_defensive_copy(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, model_features={"blink"})

        features = vdsd.model_features
        features.add("hacked")
        assert "hacked" not in vdsd.model_features


# ===========================================================================
# Vdsd — get_properties
# ===========================================================================


class TestVdsdGetProperties:
    def test_common_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()
        assert props["type"] == "vdSD"
        assert props["dSUID"] == str(vdsd.dsuid)
        assert props["displayId"] == str(vdsd.dsuid)
        assert props["name"] == "Test vdSD 0"
        assert props["active"] is True

    def test_vdsd_specific_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            primary_group=ColorGroup.GREY,
            zone_id=42,
            model_features={"blink", "shadeposition"},
        )

        props = vdsd.get_properties()
        assert props["primaryGroup"] == int(ColorGroup.GREY)
        assert props["zoneID"] == 42
        assert props["modelFeatures"] == {
            "blink": True,
            "shadeposition": True,
        }

    def test_empty_model_features(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()
        assert props["modelFeatures"] == {}


# ===========================================================================
# Vdsd — property tree (persistence)
# ===========================================================================


class TestVdsdPropertyTree:
    def test_structure(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            primary_group=ColorGroup.YELLOW,
            model_features={"blink"},
        )

        tree = vdsd.get_property_tree()
        assert tree["subdeviceIndex"] == 0
        assert tree["dSUID"] == str(vdsd.dsuid)
        assert tree["primaryGroup"] == int(ColorGroup.YELLOW)
        assert tree["modelFeatures"] == ["blink"]
        assert tree["name"] == "Test vdSD 0"

    def test_no_icon_bytes_in_tree(self):
        """Binary icon data should not be persisted to YAML."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, device_icon_16=b"\x89PNG")

        tree = vdsd.get_property_tree()
        assert "deviceIcon16" not in tree


# ===========================================================================
# Vdsd — state restoration
# ===========================================================================


class TestVdsdApplyState:
    def test_restore_basic_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        state = {
            "name": "Restored Name",
            "zoneID": 99,
            "primaryGroup": int(ColorGroup.GREY),
            "modelFeatures": ["blink", "shadeposition"],
        }
        vdsd._apply_state(state)

        assert vdsd.name == "Restored Name"
        assert vdsd.zone_id == 99
        assert vdsd.primary_group == ColorGroup.GREY
        assert vdsd.model_features == {"blink", "shadeposition"}

    def test_restore_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        new_dsuid = DsUid.random()
        vdsd._apply_state({"dSUID": str(new_dsuid)})
        assert vdsd.dsuid == new_dsuid

    def test_restore_preserves_unmentioned(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, vendor_name="OriginalVendor")

        vdsd._apply_state({"name": "Updated"})
        assert vdsd.name == "Updated"
        assert vdsd.vendor_name == "OriginalVendor"


# ===========================================================================
# Vdsd — auto-save
# ===========================================================================


class TestVdsdAutoSave:
    def test_tracked_attr_triggers_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        # Mutate a tracked attribute.
        vdsd.name = "Changed"
        assert host._save_timer is not None
        host._cancel_auto_save()

    def test_untracked_attr_no_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        vdsd._active = False  # not tracked
        assert host._save_timer is None


# ===========================================================================
# Device — construction and accessors
# ===========================================================================


class TestDeviceConstruction:
    def test_base_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        base = DsUid.random(subdevice_index=5)
        device = Device(vdc=vdc, dsuid=base)

        # Device stores device_base (index 0)
        assert device.dsuid == base.device_base()
        assert device.dsuid.subdevice_index == 0

    def test_vdc_reference(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)

        assert device.vdc is vdc

    def test_no_vdsds_initially(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)

        assert device.vdsds == {}
        assert device.is_announced is False


# ===========================================================================
# Device — vdSD management
# ===========================================================================


class TestDeviceVdsdManagement:
    def test_add_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)

        device.add_vdsd(vdsd)
        assert device.vdsds == {0: vdsd}

    def test_add_multiple_vdsds(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v1 = _make_vdsd(device, subdevice_index=1)
        v2 = _make_vdsd(device, subdevice_index=2)

        device.add_vdsd(v0)
        device.add_vdsd(v1)
        device.add_vdsd(v2)

        assert len(device.vdsds) == 3
        assert device.get_vdsd(1) is v1

    def test_add_vdsd_wrong_base_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        other_base = DsUid.random()
        bad_vdsd = Vdsd(
            device=Device(vdc=vdc, dsuid=other_base),
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="BadVdsd",
            model="Test",
        )
        # The bad_vdsd has a different base dSUID.
        with pytest.raises(ValueError, match="does not share"):
            device.add_vdsd(bad_vdsd)

    def test_add_replaces_same_index(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0a = _make_vdsd(device, subdevice_index=0, name="first")
        v0b = _make_vdsd(device, subdevice_index=0, name="second")

        device.add_vdsd(v0a)
        device.add_vdsd(v0b)
        assert device.get_vdsd(0).name == "second"  # type: ignore[union-attr]

    def test_remove_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        removed = device.remove_vdsd(0)
        assert removed is vdsd
        assert device.vdsds == {}

    def test_remove_nonexistent(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)

        assert device.remove_vdsd(99) is None

    def test_get_vdsd_by_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v2 = _make_vdsd(device, subdevice_index=2)
        device.add_vdsd(v0)
        device.add_vdsd(v2)

        found = device.get_vdsd_by_dsuid(v2.dsuid)
        assert found is v2

    def test_get_vdsd_by_dsuid_not_found(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)

        assert device.get_vdsd_by_dsuid(DsUid.random()) is None


# ===========================================================================
# Device — announcement
# ===========================================================================


class TestDeviceAnnouncement:
    async def test_announce_single_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        count = await device.announce(session)

        assert count == 1
        assert vdsd.is_announced is True
        assert device.is_announced is True
        session.send_request.assert_called_once()  # type: ignore[union-attr]

    async def test_announce_multi_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v1 = _make_vdsd(device, subdevice_index=1)
        device.add_vdsd(v0)
        device.add_vdsd(v1)

        session = _make_mock_session(pb.ERR_OK)
        count = await device.announce(session)

        assert count == 2
        assert v0.is_announced is True
        assert v1.is_announced is True
        assert device.is_announced is True

    async def test_announce_sends_correct_protobuf(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        msg = session.send_request.call_args[0][0]  # type: ignore[union-attr]
        assert msg.type == pb.VDC_SEND_ANNOUNCE_DEVICE
        assert msg.vdc_send_announce_device.dSUID == str(vdsd.dsuid)
        assert msg.vdc_send_announce_device.vdc_dSUID == str(vdc.dsuid)

    async def test_announce_failure(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_INSUFFICIENT_STORAGE)
        count = await device.announce(session)

        assert count == 0
        assert vdsd.is_announced is False
        assert device.is_announced is False

    async def test_announce_empty_device_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        session = _make_mock_session()

        with pytest.raises(RuntimeError, match="no vdSDs"):
            await device.announce(session)

    async def test_announce_already_announced_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        with pytest.raises(RuntimeError, match="already announced"):
            await device.announce(session)

    async def test_add_vdsd_to_announced_device_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        new_vdsd = _make_vdsd(device, subdevice_index=1)
        with pytest.raises(RuntimeError, match="announced device"):
            device.add_vdsd(new_vdsd)

    async def test_remove_vdsd_from_announced_device_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        with pytest.raises(RuntimeError, match="announced device"):
            device.remove_vdsd(0)

    async def test_announce_registers_device_with_vdc(self):
        """device.announce() must register the device in vdc.devices."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        assert str(device.dsuid) not in vdc.devices

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        assert str(device.dsuid) in vdc.devices


# ===========================================================================
# Device — vanish
# ===========================================================================


class TestDeviceVanish:
    async def test_vanish(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v1 = _make_vdsd(device, subdevice_index=1)
        device.add_vdsd(v0)
        device.add_vdsd(v1)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)
        assert device.is_announced is True

        await device.vanish(session)
        assert device.is_announced is False
        assert v0.is_announced is False
        assert v1.is_announced is False

    async def test_vanish_sends_correct_protobuf(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)
        await device.vanish(session)

        # send_notification should have been called for VDC_SEND_VANISH
        session.send_notification.assert_called_once()  # type: ignore[union-attr]
        msg = session.send_notification.call_args[0][0]  # type: ignore[union-attr]
        assert msg.type == pb.VDC_SEND_VANISH
        assert msg.vdc_send_vanish.dSUID == str(vdsd.dsuid)


# ===========================================================================
# Device — update (vanish + modify + re-announce)
# ===========================================================================


class TestDeviceUpdate:
    async def test_update_changes_name(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0, name="Original")
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        def modify(dev: Device) -> None:
            dev.get_vdsd(0).name = "Updated"  # type: ignore[union-attr]

        count = await device.update(session, modify)
        assert count == 1
        assert vdsd.name == "Updated"
        assert device.is_announced is True

    async def test_update_adds_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(v0)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        def modify(dev: Device) -> None:
            v2 = _make_vdsd(dev, subdevice_index=2, name="Added vdSD")
            dev.add_vdsd(v2)

        count = await device.update(session, modify)
        assert count == 2  # both v0 and v2 re-announced
        assert len(device.vdsds) == 2

    async def test_update_vanishes_before_modify(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        announced_during_modify = []

        def modify(dev: Device) -> None:
            announced_during_modify.append(dev.is_announced)

        await device.update(session, modify)
        assert announced_during_modify == [False]


# ===========================================================================
# Device — reset_announcement
# ===========================================================================


class TestDeviceResetAnnouncement:
    async def test_reset_all(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v1 = _make_vdsd(device, subdevice_index=1)
        device.add_vdsd(v0)
        device.add_vdsd(v1)

        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)

        device.reset_announcement()
        assert device.is_announced is False
        assert v0.is_announced is False
        assert v1.is_announced is False


# ===========================================================================
# Device — persistence
# ===========================================================================


class TestDevicePropertyTree:
    def test_tree_structure(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0, name="Light")
        v2 = _make_vdsd(
            device,
            subdevice_index=2,
            name="Shade",
            primary_group=ColorGroup.GREY,
        )
        device.add_vdsd(v0)
        device.add_vdsd(v2)

        tree = device.get_property_tree()
        assert tree["baseDsUID"] == str(device.dsuid)
        assert len(tree["vdsds"]) == 2
        assert tree["vdsds"][0]["subdeviceIndex"] == 0
        assert tree["vdsds"][1]["subdeviceIndex"] == 2


class TestDeviceApplyState:
    def test_restore_creates_vdsds(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)

        state = {
            "baseDsUID": str(device.dsuid),
            "vdsds": [
                {
                    "subdeviceIndex": 0,
                    "primaryGroup": int(ColorGroup.YELLOW),
                    "name": "Restored Light",
                    "zoneID": 10,
                },
                {
                    "subdeviceIndex": 2,
                    "primaryGroup": int(ColorGroup.GREY),
                    "name": "Restored Shade",
                    "zoneID": 20,
                },
            ],
        }
        device._apply_state(state)

        assert len(device.vdsds) == 2
        assert device.get_vdsd(0).name == "Restored Light"  # type: ignore[union-attr]
        assert device.get_vdsd(2).name == "Restored Shade"  # type: ignore[union-attr]
        assert device.get_vdsd(0).zone_id == 10  # type: ignore[union-attr]

    def test_restore_updates_existing(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)

        device._apply_state(
            {
                "vdsds": [{"subdeviceIndex": 0, "name": "Updated Name"}],
            }
        )
        assert vdsd.name == "Updated Name"


# ===========================================================================
# Vdc — device integration
# ===========================================================================


class TestVdcDeviceIntegration:
    def test_add_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(v0)

        vdc.add_device(device)
        assert str(device.dsuid) in vdc.devices

    def test_remove_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(v0)
        vdc.add_device(device)

        removed = vdc.remove_device(device.dsuid)
        assert removed is device
        assert vdc.devices == {}

    def test_get_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdc.add_device(device)

        found = vdc.get_device(device.dsuid)
        assert found is device

    def test_get_vdsd_by_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        v2 = _make_vdsd(device, subdevice_index=2)
        device.add_vdsd(v0)
        device.add_vdsd(v2)
        vdc.add_device(device)

        found = vdc.get_vdsd_by_dsuid(v2.dsuid)
        assert found is v2

    def test_get_vdsd_by_dsuid_not_found(self):
        host = _make_host()
        vdc = _make_vdc(host)

        assert vdc.get_vdsd_by_dsuid(DsUid.random()) is None

    async def test_announce_devices(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(v0)
        vdc.add_device(device)

        session = _make_mock_session(pb.ERR_OK)
        total = await vdc.announce_devices(session)

        assert total == 1
        assert v0.is_announced is True


# ===========================================================================
# Vdc — persistence round-trip with devices
# ===========================================================================


class TestVdcPersistenceWithDevices:
    def test_property_tree_includes_devices(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0, name="Light")
        device.add_vdsd(v0)
        vdc.add_device(device)

        tree = vdc.get_property_tree()
        assert "devices" in tree
        assert len(tree["devices"]) == 1
        assert tree["devices"][0]["baseDsUID"] == str(device.dsuid)

    def test_property_tree_no_devices_key_when_empty(self):
        host = _make_host()
        vdc = _make_vdc(host)

        tree = vdc.get_property_tree()
        assert "devices" not in tree

    def test_apply_state_restores_devices(self):
        host = _make_host()
        vdc = _make_vdc(host)

        base = _base_dsuid()
        state = {
            "devices": [
                {
                    "baseDsUID": str(base.device_base()),
                    "vdsds": [
                        {
                            "subdeviceIndex": 0,
                            "primaryGroup": int(ColorGroup.YELLOW),
                            "name": "Persisted Light",
                            "zoneID": 42,
                        }
                    ],
                }
            ],
        }
        vdc._apply_state(state)

        assert len(vdc.devices) == 1
        device = list(vdc.devices.values())[0]
        assert device.get_vdsd(0).name == "Persisted Light"  # type: ignore[union-attr]

    def test_full_persistence_roundtrip(self, tmp_path):
        """Save and reload via VdcHost YAML persistence."""
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        base = _base_dsuid()
        device = Device(vdc=vdc, dsuid=base)
        v0 = Vdsd(
            device=device,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="Kitchen Light",
            model="Light v1",
            zone_id=5,
            model_features={"blink", "identification"},
        )
        v2 = Vdsd(
            device=device,
            subdevice_index=2,
            primary_group=ColorGroup.GREY,
            name="Kitchen Shade",
            model="Shade v1",
            zone_id=5,
        )
        device.add_vdsd(v0)
        device.add_vdsd(v2)
        vdc.add_device(device)

        # Save.
        host.save()

        # Verify YAML has device data.
        state_path = tmp_path / "state.yaml"
        data = yaml.safe_load(state_path.read_text())
        vdc_data = data["vdcHost"]["vdcs"][0]
        assert "devices" in vdc_data
        assert len(vdc_data["devices"]) == 1
        assert len(vdc_data["devices"][0]["vdsds"]) == 2

        # Reload into a fresh host.
        host2 = VdcHost(
            name="Test Host",
            mac="AA:BB:CC:DD:EE:FF",
            state_path=str(state_path),
        )
        host2._cancel_auto_save()

        # The vDC and devices should be restored.
        vdc2 = host2.get_vdc(vdc.dsuid)
        assert vdc2 is not None

        assert len(vdc2.devices) == 1
        dev2 = list(vdc2.devices.values())[0]
        assert dev2.dsuid == base.device_base()
        assert len(dev2.vdsds) == 2

        r0 = dev2.get_vdsd(0)
        r2 = dev2.get_vdsd(2)
        assert r0 is not None
        assert r2 is not None
        assert r0.name == "Kitchen Light"
        assert r0.primary_group == ColorGroup.YELLOW
        assert r0.zone_id == 5
        assert r0.model_features == {"blink", "identification"}
        assert r2.name == "Kitchen Shade"
        assert r2.primary_group == ColorGroup.GREY


# ===========================================================================
# Vdc — reset_announcement cascades to devices
# ===========================================================================


class TestVdcResetCascade:
    async def test_reset_cascades(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)
        vdc.add_device(device)

        # Simulate announcement.
        session = _make_mock_session(pb.ERR_OK)
        await device.announce(session)
        assert vdsd.is_announced is True

        vdc.reset_announcement()
        assert vdc.is_announced is False
        assert device.is_announced is False
        assert vdsd.is_announced is False


# ===========================================================================
# VdcHost — property dispatch for vdSD entities
# ===========================================================================


class TestVdcHostVdsdPropertyDispatch:
    def test_resolve_vdsd_entity(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        props = host._resolve_entity(str(vdsd.dsuid))
        assert props is not None
        assert props["type"] == "vdSD"
        assert props["dSUID"] == str(vdsd.dsuid)

    def test_resolve_unknown_returns_none(self):
        host = _make_host()
        assert host._resolve_entity("FF" * 17) is None

    def test_get_property_for_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="Test Light",
        )
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        # Build a getProperty request for the vdSD.
        req = pb.Message()
        req.type = pb.VDSM_REQUEST_GET_PROPERTY
        req.message_id = 100
        req.vdsm_request_get_property.dSUID = str(vdsd.dsuid)
        # Wildcard query.
        req.vdsm_request_get_property.query.add()

        resp = host._handle_get_property(req)
        assert resp.type == pb.VDC_RESPONSE_GET_PROPERTY

    async def test_set_property_name_for_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0, name="Original")
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        # Build a setProperty request.
        req = pb.Message()
        req.type = pb.VDSM_REQUEST_SET_PROPERTY
        req.message_id = 200
        req.vdsm_request_set_property.dSUID = str(vdsd.dsuid)
        elem = req.vdsm_request_set_property.properties.add()
        elem.name = "name"
        elem.value.v_string = "New Name"

        resp = await host._handle_set_property(req)
        assert resp.generic_response.code == pb.ERR_OK
        assert vdsd.name == "New Name"

    async def test_set_property_zone_for_vdsd(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        req = pb.Message()
        req.type = pb.VDSM_REQUEST_SET_PROPERTY
        req.message_id = 201
        req.vdsm_request_set_property.dSUID = str(vdsd.dsuid)
        elem = req.vdsm_request_set_property.properties.add()
        elem.name = "zoneID"
        elem.value.v_uint64 = 42

        resp = await host._handle_set_property(req)
        assert resp.generic_response.code == pb.ERR_OK
        assert vdsd.zone_id == 42


# ===========================================================================
# W3 — progMode / currentConfigId / configurations (§4.1.1)
# ===========================================================================


class TestW3OptionalProperties:
    """Tests for the three W3 optional vdSD properties."""

    # --- construction defaults -----------------------------------------

    def test_defaults_are_none_or_empty(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        assert vdsd.prog_mode is None
        assert vdsd.current_config_id is None
        assert vdsd.configurations == []

    def test_construct_with_all_w3_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            prog_mode=True,
            current_config_id="profile-A",
            configurations=["profile-A", "profile-B"],
        )

        assert vdsd.prog_mode is True
        assert vdsd.current_config_id == "profile-A"
        assert vdsd.configurations == ["profile-A", "profile-B"]

    def test_configurations_defensive_copy(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        orig = ["a", "b"]
        vdsd = _make_vdsd(device, configurations=orig)

        # Mutating the source or the getter must not affect the internal list.
        orig.append("hacked")
        assert "hacked" not in vdsd.configurations
        returned = vdsd.configurations
        returned.append("hacked2")
        assert "hacked2" not in vdsd.configurations

    # --- get_properties ------------------------------------------------

    def test_get_properties_includes_w3_when_set(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            prog_mode=False,
            current_config_id="cfg-1",
            configurations=["cfg-1", "cfg-2"],
        )

        props = vdsd.get_properties()
        assert props["progMode"] is False
        assert props["currentConfigId"] == "cfg-1"
        assert props["configurations"] == {
            "0": {"id": "cfg-1"},
            "1": {"id": "cfg-2"},
        }

    def test_get_properties_includes_configurations_when_empty(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()
        assert props["configurations"] == {}

    def test_get_properties_prog_mode_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        props = vdsd.get_properties()
        assert props["progMode"] is None
        assert props["currentConfigId"] is None

    # --- property tree (persistence) -----------------------------------

    def test_property_tree_includes_w3(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            prog_mode=True,
            current_config_id="p-1",
            configurations=["p-1", "p-2"],
        )

        tree = vdsd.get_property_tree()
        assert tree["progMode"] is True
        assert tree["currentConfigId"] == "p-1"
        assert tree["configurations"] == ["p-1", "p-2"]

    def test_property_tree_omits_configurations_when_empty(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        tree = vdsd.get_property_tree()
        assert "configurations" not in tree

    # --- state restoration (_apply_state) ------------------------------

    def test_restore_w3_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device)

        vdsd._apply_state(
            {
                "progMode": True,
                "currentConfigId": "restored-cfg",
                "configurations": ["restored-cfg", "alt-cfg"],
            }
        )

        assert vdsd.prog_mode is True
        assert vdsd.current_config_id == "restored-cfg"
        assert vdsd.configurations == ["restored-cfg", "alt-cfg"]

    def test_restore_prog_mode_none(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, prog_mode=True)

        vdsd._apply_state({"progMode": None})
        assert vdsd.prog_mode is None

    def test_restore_preserves_w3_when_omitted(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(
            device,
            prog_mode=True,
            current_config_id="keep",
            configurations=["keep"],
        )

        vdsd._apply_state({"name": "Updated"})
        assert vdsd.prog_mode is True
        assert vdsd.current_config_id == "keep"
        assert vdsd.configurations == ["keep"]

    # --- setProperty (r/w progMode via vdc_host) -----------------------

    async def test_set_property_prog_mode(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        device = _make_device(vdc)
        vdsd = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(vdsd)
        vdc.add_device(device)
        host._cancel_auto_save()

        req = pb.Message()
        req.type = pb.VDSM_REQUEST_SET_PROPERTY
        req.message_id = 300
        req.vdsm_request_set_property.dSUID = str(vdsd.dsuid)
        elem = req.vdsm_request_set_property.properties.add()
        elem.name = "progMode"
        elem.value.v_bool = True

        resp = await host._handle_set_property(req)
        assert resp.generic_response.code == pb.ERR_OK
        assert vdsd.prog_mode is True


# ===========================================================================
# Multi-vdSD device — dSUID relationships
# ===========================================================================


class TestMultiVdsdDsuid:
    """Verifies that multi-vdSD devices correctly share base dSUIDs."""

    def test_siblings_same_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        base = DsUid.from_enocean("0512ABCD")
        device = Device(vdc=vdc, dsuid=base)

        v0 = Vdsd(
            device=device,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="v0",
            model="Test",
        )
        v2 = Vdsd(
            device=device,
            subdevice_index=2,
            primary_group=ColorGroup.GREY,
            name="v2",
            model="Test",
        )
        device.add_vdsd(v0)
        device.add_vdsd(v2)

        assert v0.dsuid.same_device(v2.dsuid)
        assert v0.dsuid != v2.dsuid
        assert v0.dsuid.subdevice_index == 0
        assert v2.dsuid.subdevice_index == 2

    def test_device_base_matches(self):
        host = _make_host()
        vdc = _make_vdc(host)
        base = DsUid.from_enocean("0512ABCD")
        device = Device(vdc=vdc, dsuid=base)
        v0 = Vdsd(
            device=device,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="v0",
            model="Test",
        )
        v3 = Vdsd(
            device=device,
            subdevice_index=3,
            primary_group=ColorGroup.YELLOW,
            name="v3",
            model="Test",
        )

        assert v0.dsuid.device_base() == device.dsuid
        assert v3.dsuid.device_base() == device.dsuid

    def test_separate_devices_different_base(self):
        host = _make_host()
        vdc = _make_vdc(host)

        d1 = Device(vdc=vdc, dsuid=DsUid.random())
        d2 = Device(vdc=vdc, dsuid=DsUid.random())

        v1 = Vdsd(
            device=d1,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="v1",
            model="Test",
        )
        v2 = Vdsd(
            device=d2,
            subdevice_index=0,
            primary_group=ColorGroup.YELLOW,
            name="v2",
            model="Test",
        )

        assert not v1.dsuid.same_device(v2.dsuid)


# ===========================================================================
# repr
# ===========================================================================


class TestRepr:
    def test_vdsd_repr(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, name="MyDevice")

        r = repr(vdsd)
        assert "Vdsd" in r
        assert "MyDevice" in r

    def test_device_repr(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        v0 = _make_vdsd(device, subdevice_index=0)
        device.add_vdsd(v0)

        r = repr(device)
        assert "Device" in r
        assert "vdsds=1" in r


# ===========================================================================
# derive_model_features — new rules
# ===========================================================================


class TestDeriveModelFeatures:
    """Unit tests for Vdsd.derive_model_features covering all new rules."""

    # ---- helpers ---------------------------------------------------------

    def _setup(self, primary_group: ColorGroup = ColorGroup.BLACK) -> tuple:
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, primary_group=primary_group)
        return vdsd, device

    # ---- transt ----------------------------------------------------------

    def test_transt_brightness_channel(self):
        vdsd, _ = self._setup()
        # DIMMER auto-creates BRIGHTNESS (channelType=1)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "transt" in vdsd.model_features

    def test_transt_color_temp_channel(self):
        vdsd, _ = self._setup()
        # DIMMER_COLOR_TEMP creates BRIGHTNESS (1) + COLOR_TEMPERATURE (4)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER_COLOR_TEMP,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "transt" in vdsd.model_features

    def test_transt_cooling_capacity_channel(self):
        # Start with no auto-channels, then add COOLING_CAPACITY (type=17 → in 14-18)
        vdsd, _ = self._setup()
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.INTERNALLY_CONTROLLED,
            name="output",
            default_group=1,
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.COOLING_CAPACITY)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "transt" in vdsd.model_features

    def test_no_transt_without_matching_channels(self):
        vdsd, _ = self._setup()
        # INTERNALLY_CONTROLLED has no auto-created channels
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.INTERNALLY_CONTROLLED,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "transt" not in vdsd.model_features

    def test_no_transt_for_positional_output(self):
        # POSITIONAL outputs use hardware motor timing, not software transition time.
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            name="output",
            default_group=16,
            active_group=16,
            groups={16},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "transt" not in vdsd.model_features

    # ---- button rules ----------------------------------------------------

    def test_button_basic_features(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbutton" in vdsd.model_features
        assert "pushbadvanced" in vdsd.model_features

    def test_button_group_not_8_adds_pushbarea(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.YELLOW)
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbarea" in vdsd.model_features
        assert "pushbsensor" not in vdsd.model_features
        assert "highlevel" not in vdsd.model_features

    def test_button_group_not_8_with_local_key_mode_adds_pushbdevice(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1, supports_local_key_mode=True)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbdevice" in vdsd.model_features

    def test_button_group_not_8_without_local_key_mode_no_pushbdevice(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1, supports_local_key_mode=False)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbdevice" not in vdsd.model_features

    def test_button_group_8_adds_pushbsensor_and_highlevel(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=8)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbsensor" in vdsd.model_features
        assert "highlevel" in vdsd.model_features
        assert "pushbarea" not in vdsd.model_features

    def test_button_type_2_to_5_no_pushbcombined(self):
        # pushbcombined is NOT SUPPORTED (hardware TKM device feature, buttonType
        # is read-only in the VDC protocol) — never auto-derived regardless of type
        for bt in (
            ButtonType.TWO_WAY_PUSHBUTTON,
            ButtonType.FOUR_WAY_NAVIGATION,
            ButtonType.FOUR_WAY_WITH_CENTER,
            ButtonType.EIGHT_WAY_WITH_CENTER,
        ):
            vdsd, _ = self._setup()
            btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1, button_type=bt)
            vdsd.add_button_input(btn)
            vdsd.derive_model_features()
            assert "pushbcombined" not in vdsd.model_features, (
                f"pushbcombined must not appear for {bt}"
            )

    def test_button_type_1_no_pushbcombined(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(
            vdsd=vdsd, ds_index=0, group=1, button_type=ButtonType.SINGLE_PUSHBUTTON
        )
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbcombined" not in vdsd.model_features

    def test_button_ds_index_1_no_twowayconfig(self):
        # twowayconfig is NOT SUPPORTED (buttonType is read-only in VDC protocol)
        vdsd, _ = self._setup()
        btn0 = ButtonInput(vdsd=vdsd, ds_index=0, group=1)
        btn1 = ButtonInput(vdsd=vdsd, ds_index=1, group=1)
        vdsd.add_button_input(btn0)
        vdsd.add_button_input(btn1)
        vdsd.derive_model_features()
        assert "twowayconfig" not in vdsd.model_features

    def test_button_ds_index_0_only_no_twowayconfig(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "twowayconfig" not in vdsd.model_features

    # ---- shade / outvalue8 rules ----------------------------------------

    def test_shade_primarygroup_grey_no_shadeprops(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=16,
                name="output",
                active_group=16,
                groups={16},
            )
        )
        vdsd.derive_model_features()
        assert "shadeprops" not in vdsd.model_features

    def test_shade_primarygroup_grey_function_positional_adds_shadeposition(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.POSITIONAL,
                default_group=16,
                name="output",
                active_group=16,
                groups={16},
            )
        )
        vdsd.derive_model_features()
        assert "shadeposition" in vdsd.model_features
        assert "outvalue8" not in vdsd.model_features

    def test_shade_position_with_blade_channels_adds_shadebladeang(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=17,
            name="output",
            active_group=17,
            groups={17},
        )
        output.add_channel(9)  # channelType 9 (blade angle)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "shadebladeang" in vdsd.model_features
        assert "motiontimefins" not in vdsd.model_features

    def test_shade_position_without_blade_channels_no_shadebladeang(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.POSITIONAL,
                default_group=16,
                name="output",
                active_group=16,
                groups={16},
            )
        )
        vdsd.derive_model_features()
        assert "shadebladeang" not in vdsd.model_features
        assert (
            "motiontimefins" not in vdsd.model_features
        )  # never derived — unsupported

    def test_non_shade_output_adds_outvalue8(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outvalue8" in vdsd.model_features

    def test_internally_controlled_gets_outvalue8(self):
        """INTERNALLY_CONTROLLED is no longer excluded from outvalue8."""
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.INTERNALLY_CONTROLLED,
                mode=OutputMode.DISABLED,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outvalue8" in vdsd.model_features

    # ---- outputchannels -------------------------------------------------

    def test_outputchannels_when_hue_and_saturation_present(self):
        vdsd, _ = self._setup()
        # FULL_COLOR_DIMMER auto-creates HUE (2) + SATURATION (3)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.FULL_COLOR_DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outputchannels" in vdsd.model_features

    def test_outputchannels_for_dimmer_color_temp(self):
        vdsd, _ = self._setup()
        # DIMMER_COLOR_TEMP has BRIGHTNESS + COLOR_TEMPERATURE → outputchannels
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER_COLOR_TEMP,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outputchannels" in vdsd.model_features

    def test_no_outputchannels_for_dimmer_only(self):
        vdsd, _ = self._setup()
        # DIMMER has only BRIGHTNESS (no HUE/SAT, no COLOR_TEMPERATURE)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outputchannels" not in vdsd.model_features

    # ---- binary input AKM -----------------------------------------------

    def test_binary_input_group8_adds_akmsensor(self):
        vdsd, _ = self._setup()
        bi = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_function=BinaryInputType.PRESENCE,
            input_usage=BinaryInputUsage.UNDEFINED,
            group=8,
        )
        vdsd.add_binary_input(bi)
        vdsd.derive_model_features()
        assert "akmsensor" in vdsd.model_features
        assert "akminput" not in vdsd.model_features
        assert "akmdelay" not in vdsd.model_features

    def test_binary_input_non_group8_also_adds_akmsensor(self):
        # Any binary input (regardless of group) enables the AKM sensor function UI
        vdsd, _ = self._setup()
        bi = BinaryInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_function=BinaryInputType.PRESENCE,
            input_usage=BinaryInputUsage.UNDEFINED,
            group=1,
        )
        vdsd.add_binary_input(bi)
        vdsd.derive_model_features()
        assert "akmsensor" in vdsd.model_features
        assert "akminput" not in vdsd.model_features
        assert "akmdelay" not in vdsd.model_features

    def test_akminput_akmdelay_are_unsupported(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="akminput"):
            vdsd.add_model_feature("akminput")
        with pytest.raises(ValueError, match="akmdelay"):
            vdsd.add_model_feature("akmdelay")

    # ---- primaryGroup-based rules ---------------------------------------

    def test_primary_group_3_adds_heatingprops_and_heatinggroup(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.BLUE)
        vdsd.derive_model_features()
        assert "heatingprops" in vdsd.model_features
        assert "heatinggroup" in vdsd.model_features

    def test_primary_group_3_with_output_adds_valvetype(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.BLUE)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "valvetype" in vdsd.model_features

    def test_primary_group_3_without_output_no_valvetype(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.BLUE)
        vdsd.derive_model_features()
        assert "valvetype" not in vdsd.model_features

    def test_no_heatingoutmode_auto_derived_for_primarygroup3_function0(self):
        # heatingoutmode is NOT auto-derived: it exposes a DS485 hardware mode selector
        # whose value is stored in dSS m_OutputMode and never forwarded to the VDC.
        vdsd, _ = self._setup(primary_group=ColorGroup.BLUE)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=48,
                name="output",
                active_group=48,
                groups={48},
            )
        )
        vdsd.derive_model_features()
        assert "heatingoutmode" not in vdsd.model_features
        assert "pwmvalue" in vdsd.model_features

    def test_no_heatingoutmode_for_non_heating_primarygroup(self):
        vdsd, _ = self._setup()  # default BLACK primaryGroup
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "heatingoutmode" not in vdsd.model_features
        assert "pwmvalue" not in vdsd.model_features

    def test_no_heatingoutmode_for_non_onoff_function(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.BLUE)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=48,
                name="output",
                active_group=48,
                groups={48},
            )
        )
        vdsd.derive_model_features()
        assert "heatingoutmode" not in vdsd.model_features

    def test_primary_group_2_outdoor_awning_adds_location_and_windawning(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "locationconfig" in vdsd.model_features
        assert "windprotectionconfigawning" in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features

    def test_primary_group_2_outdoor_blind_adds_location_and_windblind(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        output.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "locationconfig" in vdsd.model_features
        assert "windprotectionconfigblind" in vdsd.model_features
        assert "windprotectionconfigawning" not in vdsd.model_features

    def test_primary_group_2_indoor_curtain_has_location_but_no_wind(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "locationconfig" in vdsd.model_features
        assert "windprotectionconfigawning" not in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features
        assert "operationlock" not in vdsd.model_features

    def test_primary_group_2_indoor_blind_has_location_but_no_wind(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
        output.add_channel(OutputChannelType.SHADE_OPENING_ANGLE_INDOOR)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "locationconfig" in vdsd.model_features
        assert "windprotectionconfigawning" not in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features
        assert "operationlock" not in vdsd.model_features

    def test_primary_group_2_without_output_no_location(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        vdsd.derive_model_features()
        assert "locationconfig" not in vdsd.model_features
        assert "windprotectionconfigawning" not in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features

    def test_primary_group_other_no_location(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.YELLOW)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "locationconfig" not in vdsd.model_features
        assert "windprotectionconfigawning" not in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features

    # ---- does not clobber manually set features -------------------------

    def test_pre_set_features_preserved(self):
        vdsd, _ = self._setup()
        vdsd.add_model_feature("blink")
        vdsd.derive_model_features()
        assert "blink" in vdsd.model_features

    # ---- idempotent -----------------------------------------------------

    def test_derive_twice_is_idempotent(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        features_first = frozenset(vdsd.model_features)
        vdsd.derive_model_features()
        assert frozenset(vdsd.model_features) == features_first

    # ---- outmode --------------------------------------------------------

    def test_non_shade_output_no_outmode(self):
        """outmode is never auto-derived (standard vDCs don't support it)."""
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outmode" not in vdsd.model_features

    def test_internally_controlled_no_outmode(self):
        """outmode is never auto-derived."""
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.INTERNALLY_CONTROLLED,
                mode=OutputMode.DISABLED,
                name="output",
                default_group=1,
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outmode" not in vdsd.model_features

    def test_shade_output_no_outmode(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.POSITIONAL,
                default_group=2,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outmode" not in vdsd.model_features

    # ---- switch / outmodeswitch -----------------------------------------

    def test_onoff_non_shade_output_no_switch_or_outmodeswitch(self):
        """switch/outmodeswitch are never auto-derived."""
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "switch" not in vdsd.model_features
        assert "outmodeswitch" not in vdsd.model_features

    def test_dimmer_output_no_switch(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "switch" not in vdsd.model_features
        assert "outmodeswitch" not in vdsd.model_features

    # ---- extradimmer ----------------------------------------------------

    def test_dimmer_function_no_extradimmer(self):
        """extradimmer is never auto-derived."""
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "extradimmer" not in vdsd.model_features

    def test_ct_dimmer_no_extradimmer(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER_COLOR_TEMP,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "extradimmer" not in vdsd.model_features

    def test_onoff_no_extradimmer(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "extradimmer" not in vdsd.model_features

    # ---- consumption ----------------------------------------------------

    def test_active_power_sensor_adds_consumption(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.ACTIVE_POWER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=3680.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumption" in vdsd.model_features

    def test_electric_current_sensor_adds_consumption(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.ELECTRIC_CURRENT,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=16.0,
            resolution=0.01,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumption" in vdsd.model_features

    def test_energy_meter_sensor_adds_consumption(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.ENERGY_METER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=1000000.0,
            resolution=1.0,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumption" in vdsd.model_features

    def test_apparent_power_sensor_adds_consumption(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.APPARENT_POWER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=3680.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumption" in vdsd.model_features

    def test_temperature_sensor_no_consumption(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            min_value=-10.0,
            max_value=40.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumption" not in vdsd.model_features

    # ---- jokerconfig / optypeconfig -------------------------------------

    def test_primary_group_8_adds_jokerconfig(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.BLACK)
        vdsd.derive_model_features()
        assert "jokerconfig" in vdsd.model_features

    def test_primary_group_non_8_no_jokerconfig(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.YELLOW)
        vdsd.derive_model_features()
        assert "jokerconfig" not in vdsd.model_features

    # ---- ledauto (NOT SUPPORTED) ----------------------------------------

    def test_output_does_not_add_ledauto(self):
        # ledauto is NOT SUPPORTED — device LED is not API-controlled
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "ledauto" not in vdsd.model_features

    def test_no_output_no_ledauto(self):
        vdsd, _ = self._setup()
        vdsd.derive_model_features()
        assert "ledauto" not in vdsd.model_features

    # ---- highlevel — from button group=8 only, NOT from primaryGroup=8 ----

    def test_joker_primary_group_alone_does_not_add_highlevel(self):
        """primaryGroup=8 alone must NOT add highlevel — highlevel requires a button with group=8."""
        vdsd, _ = self._setup(primary_group=ColorGroup.BLACK)
        vdsd.derive_model_features()
        assert "highlevel" not in vdsd.model_features

    def test_non_joker_primary_group_no_highlevel_from_group(self):
        """Without buttons, non-joker primaryGroup must not add highlevel."""
        vdsd, _ = self._setup(primary_group=ColorGroup.YELLOW)
        vdsd.derive_model_features()
        assert "highlevel" not in vdsd.model_features

    # ---- blink / identification / blinkconfig ---------------------------

    def test_on_identify_adds_identification(self):
        vdsd, _ = self._setup()
        vdsd.on_identify = lambda _: None
        vdsd.derive_model_features()
        assert "identification" in vdsd.model_features
        assert "blink" not in vdsd.model_features
        assert "blinkconfig" not in vdsd.model_features

    def test_no_on_identify_no_identification(self):
        vdsd, _ = self._setup()
        vdsd.derive_model_features()
        assert "blink" not in vdsd.model_features
        assert "identification" not in vdsd.model_features
        assert "blinkconfig" not in vdsd.model_features

    # ---- blink auto-derive from output ----------------------------------

    def test_output_adds_blink(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "blink" in vdsd.model_features

    def test_no_output_no_blink(self):
        vdsd, _ = self._setup()
        vdsd.derive_model_features()
        assert "blink" not in vdsd.model_features

    # ---- outconfigswitch / impulseconfig from ON_OFF --------------------

    def test_on_off_output_adds_outconfigswitch_and_impulseconfig(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.ON_OFF,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outconfigswitch" in vdsd.model_features
        assert "impulseconfig" in vdsd.model_features

    def test_dimmer_output_no_outconfigswitch_or_impulseconfig(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "outconfigswitch" not in vdsd.model_features
        assert "impulseconfig" not in vdsd.model_features

    # ---- pushbdisabled from any button ----------------------------------

    def test_button_adds_pushbdisabled(self):
        vdsd, _ = self._setup()
        btn = ButtonInput(vdsd=vdsd, ds_index=0, group=1)
        vdsd.add_button_input(btn)
        vdsd.derive_model_features()
        assert "pushbdisabled" in vdsd.model_features

    def test_no_button_no_pushbdisabled(self):
        vdsd, _ = self._setup()
        vdsd.derive_model_features()
        assert "pushbdisabled" not in vdsd.model_features

    # ---- operationlock from grey + output --------------------------------

    def test_grey_outdoor_with_output_adds_operationlock(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "operationlock" in vdsd.model_features

    def test_grey_indoor_with_output_no_operationlock(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_INDOOR)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "operationlock" not in vdsd.model_features

    def test_grey_without_output_no_operationlock(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        vdsd.derive_model_features()
        assert "operationlock" not in vdsd.model_features

    def test_yellow_with_output_no_operationlock(self):
        vdsd, _ = self._setup(primary_group=ColorGroup.YELLOW)
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "operationlock" not in vdsd.model_features

    # ---- unsupported features raise ValueError --------------------------

    def test_add_unsupported_ledauto_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="ledauto"):
            vdsd.add_model_feature("ledauto")

    def test_add_unsupported_dimmodeconfig_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="dimmodeconfig"):
            vdsd.add_model_feature("dimmodeconfig")

    def test_add_unsupported_twowayconfig_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="twowayconfig"):
            vdsd.add_model_feature("twowayconfig")

    def test_add_unsupported_pushbcombined_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="pushbcombined"):
            vdsd.add_model_feature("pushbcombined")

    def test_add_unsupported_outmode_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="outmode"):
            vdsd.add_model_feature("outmode")

    def test_add_unsupported_consumptioneventled_raises(self):
        vdsd, _ = self._setup()
        with pytest.raises(ValueError, match="consumptioneventled"):
            vdsd.add_model_feature("consumptioneventled")

    def test_add_shadeprops_manually_allowed(self):
        # shadeprops is not auto-derived but may be added manually
        vdsd, _ = self._setup()
        vdsd.add_model_feature("shadeprops")
        assert "shadeprops" in vdsd.model_features

    def test_add_motiontimefins_manually_allowed(self):
        # motiontimefins is not auto-derived but may be added manually
        vdsd, _ = self._setup()
        vdsd.add_model_feature("motiontimefins")
        assert "motiontimefins" in vdsd.model_features

    def test_add_supported_blink_does_not_raise(self):
        # Verify that a legitimate optional feature can still be added manually
        vdsd, _ = self._setup()
        vdsd.add_model_feature("blink")  # must not raise
        assert "blink" in vdsd.model_features

    # ---- dimmodeconfig / customtransitiontime NOT auto-derived ----------

    def test_dimmer_does_not_add_dimmodeconfig(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "dimmodeconfig" not in vdsd.model_features

    def test_dimmer_does_not_add_customtransitiontime(self):
        vdsd, _ = self._setup()
        vdsd.set_output(
            Output(
                vdsd=vdsd,
                function=OutputFunction.DIMMER,
                default_group=1,
                name="output",
                active_group=1,
                groups={1},
            )
        )
        vdsd.derive_model_features()
        assert "customtransitiontime" not in vdsd.model_features

    def test_power_sensor_does_not_add_consumptioneventled(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.ACTIVE_POWER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=3680.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumptioneventled" not in vdsd.model_features

    def test_energy_meter_does_not_add_consumptiontimer(self):
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.ENERGY_METER,
            sensor_usage=SensorUsage.DEVICE_LEVEL,
            min_value=0.0,
            max_value=99999.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)
        vdsd.derive_model_features()
        assert "consumptiontimer" not in vdsd.model_features

    # ---- windprotection split (awning vs. blind) -------------------------

    def test_shade_awning_no_blade_channel(self):
        """Outdoor awning (type 7, no angle channel) → windprotectionconfigawning."""
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(OutputChannelType.SHADE_POSITION_OUTSIDE)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "windprotectionconfigawning" in vdsd.model_features
        assert "windprotectionconfigblind" not in vdsd.model_features

    def test_shade_blind_with_blade_channel(self):
        """POSITIONAL shade with channelType 9 → windprotectionconfigblind."""
        vdsd, _ = self._setup(primary_group=ColorGroup.GREY)
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.POSITIONAL,
            default_group=2,
            name="output",
            active_group=1,
            groups={1},
        )
        output.add_channel(9)  # channelType 9 (blade angle)
        vdsd.set_output(output)
        vdsd.derive_model_features()
        assert "windprotectionconfigblind" in vdsd.model_features


# ===========================================================================
# Vdsd — _wait_for_initial_values
# ===========================================================================


@pytest.mark.asyncio
class TestWaitForInitialValues:
    """Tests for Vdsd._wait_for_initial_values() and its integration with announce."""

    def _setup(self, **kwargs):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_device(vdc)
        vdsd = _make_vdsd(device, **kwargs)
        device.add_vdsd(vdsd)
        return vdsd, device

    async def test_no_components_returns_immediately(self):
        """A device with no value-bearing components passes instantly."""
        vdsd, _ = self._setup()
        await vdsd._wait_for_initial_values(timeout=0.1)

    async def test_all_values_pre_set_returns_immediately(self):
        """When all values are already set, the wait resolves without sleeping."""
        vdsd, _ = self._setup()
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            default_group=1,
            name="light",
            active_group=1,
            groups={1},
        )
        vdsd.set_output(output)
        ch = list(output.channels.values())[0]
        await ch.update_value(50.0)

        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st)
        st.value = 1

        await vdsd._wait_for_initial_values(timeout=0.1)

    async def test_timeout_raises_with_missing_component_names(self):
        """On timeout, RuntimeError lists the components that did not report."""
        vdsd, _ = self._setup()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="operatingState",
            options={0: "Off", 1: "Running"},
        )
        vdsd.add_device_state(st)

        prop = DeviceProperty(
            vdsd=vdsd,
            ds_index=0,
            name="batteryLevel",
            type="numeric",
        )
        vdsd.add_device_property(prop)

        with pytest.raises(RuntimeError) as exc_info:
            await vdsd._wait_for_initial_values(timeout=0.05)

        msg = str(exc_info.value)
        assert "operatingState" in msg
        assert "batteryLevel" in msg

    async def test_timeout_only_lists_still_missing(self):
        """Components that DO report in time are excluded from the error message."""
        vdsd, _ = self._setup()
        st_fast = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="fastState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st_fast)

        st_slow = DeviceState(
            vdsd=vdsd,
            ds_index=1,
            name="slowState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st_slow)

        # Provide the fast state immediately; let the slow one time out.
        st_fast.value = 1

        with pytest.raises(RuntimeError) as exc_info:
            await vdsd._wait_for_initial_values(timeout=0.05)

        msg = str(exc_info.value)
        assert "slowState" in msg
        assert "fastState" not in msg

    async def test_values_set_concurrently_resolves(self):
        """Values set after the wait starts satisfy the wait."""
        vdsd, _ = self._setup()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st)

        async def set_after_delay():
            await asyncio.sleep(0.02)
            st.value = 1

        await asyncio.gather(
            vdsd._wait_for_initial_values(timeout=1.0),
            set_after_delay(),
        )
        assert st.value == 1

    async def test_output_channel_waits_for_value(self):
        """OutputChannel without a value blocks announcement until set."""
        vdsd, _ = self._setup()
        output = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            default_group=1,
            name="light",
            active_group=1,
            groups={1},
        )
        vdsd.set_output(output)

        with pytest.raises(RuntimeError) as exc_info:
            await vdsd._wait_for_initial_values(timeout=0.05)

        assert "OutputChannel" in str(exc_info.value)

    async def test_sensor_input_waits_for_value(self):
        """SensorInput without a value blocks until update_value is called."""
        vdsd, _ = self._setup()
        si = SensorInput(
            vdsd=vdsd,
            ds_index=0,
            sensor_type=SensorType.TEMPERATURE,
            sensor_usage=SensorUsage.ROOM,
            min_value=-20.0,
            max_value=60.0,
            resolution=0.1,
        )
        vdsd.add_sensor_input(si)

        with pytest.raises(RuntimeError) as exc_info:
            await vdsd._wait_for_initial_values(timeout=0.05)

        assert "SensorInput" in str(exc_info.value)

    async def test_announce_waits_for_initial_values(self):
        """announce() blocks until values are ready, then sends the message."""
        vdsd, device = self._setup()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st)

        session = _make_mock_session(pb.ERR_OK)

        async def provide_value():
            await asyncio.sleep(0.02)
            st.value = 1

        result, _ = await asyncio.gather(
            device.announce(session),
            provide_value(),
        )

        assert result == 1
        assert vdsd.is_announced is True

    async def test_device_property_restored_from_persistence_is_ready(self):
        """A DeviceProperty restored from persistence counts as having a value."""
        vdsd, _ = self._setup()
        prop = DeviceProperty(
            vdsd=vdsd,
            ds_index=0,
            name="level",
            type="numeric",
        )
        vdsd.add_device_property(prop)

        # Simulate persistence restore setting a value.
        prop._apply_state({"value": 42.0})

        # Should not raise — the restored value satisfies the requirement.
        await vdsd._wait_for_initial_values(timeout=0.05)
        assert "windprotectionconfigawning" not in vdsd.model_features
