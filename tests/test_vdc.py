"""Tests for the Vdc class and its integration with VdcHost."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import VdcConnection
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import ENTITY_TYPE_VDC, Vdc, VdcCapabilities
from pydsvdcapi.vdc_host import VdcHost

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_host(tmp_path: Path | None = None, **kwargs: Any) -> VdcHost:
    """Create a VdcHost suitable for testing."""
    kw: dict[str, Any] = {"name": "Test Host", "mac": "AA:BB:CC:DD:EE:FF"}
    if tmp_path is not None:
        kw["state_path"] = str(tmp_path / "state.yaml")
    kw.update(kwargs)
    host = VdcHost(**kw)
    # Cancel any pending auto-save timers.
    host._cancel_auto_save()
    return host


def _make_vdc(host: VdcHost, **kwargs) -> Vdc:
    """Create a Vdc for testing."""
    defaults = {
        "host": host,
        "implementation_id": "x-test-light",
        "name": "Test Light vDC",
        "model": "Test Light v1",
    }
    defaults.update(kwargs)
    vdc = Vdc(**defaults)
    return vdc


# ---------------------------------------------------------------------------
# VdcCapabilities
# ---------------------------------------------------------------------------


class TestVdcCapabilities:
    """Tests for the VdcCapabilities dataclass."""

    def test_defaults_are_false(self):
        caps = VdcCapabilities()
        assert caps.metering is False
        assert caps.identification is False
        assert caps.dynamic_definitions is False

    def test_custom_values(self):
        caps = VdcCapabilities(
            metering=True, identification=True, dynamic_definitions=False
        )
        assert caps.metering is True
        assert caps.identification is True
        assert caps.dynamic_definitions is False

    def test_to_dict(self):
        caps = VdcCapabilities(metering=True)
        d = caps.to_dict()
        assert d == {
            "metering": True,
            "identification": False,
            "dynamicDefinitions": False,
        }

    def test_from_dict(self):
        d = {
            "metering": False,
            "identification": True,
            "dynamicDefinitions": True,
        }
        caps = VdcCapabilities.from_dict(d)
        assert caps.metering is False
        assert caps.identification is True
        assert caps.dynamic_definitions is True

    def test_from_dict_missing_keys(self):
        caps = VdcCapabilities.from_dict({})
        assert caps.metering is False
        assert caps.identification is False
        assert caps.dynamic_definitions is False

    def test_round_trip(self):
        original = VdcCapabilities(
            metering=True, identification=False, dynamic_definitions=True
        )
        restored = VdcCapabilities.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# Vdc — basic construction and properties
# ---------------------------------------------------------------------------


class TestVdcConstruction:
    """Tests for Vdc construction and property defaults."""

    def test_minimal_construction(self):
        host = _make_host()
        vdc = Vdc(
            host=host,
            implementation_id="x-test-vdc",
            name="x-test-vdc",
            model="pydsvdcapi vDC",
        )
        assert vdc.implementation_id == "x-test-vdc"
        assert vdc.name == "x-test-vdc"  # explicit name
        assert vdc.model == "pydsvdcapi vDC"
        assert vdc.entity_type == ENTITY_TYPE_VDC
        assert vdc.entity_type == "vDC"
        assert vdc.active is True
        assert vdc.is_announced is False
        assert vdc.host is host
        assert vdc.zone_id == 0

    def test_custom_name_and_model(self):
        host = _make_host()
        vdc = _make_vdc(host, name="My Light", model="Light v2")
        assert vdc.name == "My Light"
        assert vdc.model == "Light v2"

    def test_dsuid_derived_from_implementation_id(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-alpha")
        vdc2 = _make_vdc(host, implementation_id="x-test-alpha")
        vdc3 = _make_vdc(host, implementation_id="x-test-beta")
        # Same implementation_id → same dSUID
        assert vdc1.dsuid == vdc2.dsuid
        # Different implementation_id → different dSUID
        assert vdc1.dsuid != vdc3.dsuid

    def test_explicit_dsuid(self):
        host = _make_host()
        explicit = DsUid.from_name_in_space("custom", DsUidNamespace.VDC)
        vdc = _make_vdc(host, dsuid=explicit)
        assert vdc.dsuid == explicit

    def test_display_id_is_dsuid_hex(self):
        host = _make_host()
        vdc = _make_vdc(host)
        assert vdc.display_id == str(vdc.dsuid)

    def test_model_uid_derived(self):
        host = _make_host()
        vdc = _make_vdc(host, model="MyModel")
        expected = str(DsUid.from_name_in_space("MyModel", DsUidNamespace.VDC))
        assert vdc.model_uid == expected

    def test_explicit_model_uid(self):
        host = _make_host()
        vdc = _make_vdc(host, model_uid="custom-uid")
        assert vdc.model_uid == "custom-uid"

    def test_capabilities_default(self):
        host = _make_host()
        vdc = _make_vdc(host)
        caps = vdc.capabilities
        assert caps.metering is False
        assert caps.identification is False
        assert caps.dynamic_definitions is False

    def test_capabilities_custom(self):
        host = _make_host()
        caps = VdcCapabilities(metering=True, identification=True)
        vdc = _make_vdc(host, capabilities=caps)
        assert vdc.capabilities.metering is True
        assert vdc.capabilities.identification is True

    def test_active_setter(self):
        host = _make_host()
        vdc = _make_vdc(host)
        assert vdc.active is True
        vdc.active = False
        assert vdc.active is False

    def test_all_common_properties_settable(self):
        host = _make_host()
        vdc = _make_vdc(
            host,
            hardware_version="1.0",
            hardware_guid="macaddress:00:11:22:33:44:55",
            hardware_model_guid="gs1:(01)1234",
            vendor_name="ACME",
            vendor_guid="vendorname:ACME",
            oem_guid="gs1:(01)5678(21)9999",
            oem_model_guid="gs1:(01)5678",
            config_url="http://192.168.1.1/config",
            device_icon_16=b"\x89PNG",
            device_icon_name="light-icon",
            device_class="dSLight",
            device_class_version="1",
            zone_id=42,
        )
        assert vdc.hardware_version == "1.0"
        assert vdc.hardware_guid == "macaddress:00:11:22:33:44:55"
        assert vdc.hardware_model_guid == "gs1:(01)1234"
        assert vdc.vendor_name == "ACME"
        assert vdc.vendor_guid == "vendorname:ACME"
        assert vdc.oem_guid == "gs1:(01)5678(21)9999"
        assert vdc.oem_model_guid == "gs1:(01)5678"
        assert vdc.config_url == "http://192.168.1.1/config"
        assert vdc.device_icon_16 == b"\x89PNG"
        assert vdc.device_icon_name == "light-icon"
        assert vdc.device_class == "dSLight"
        assert vdc.device_class_version == "1"
        assert vdc.zone_id == 42

    def test_repr(self):
        host = _make_host()
        vdc = _make_vdc(host)
        r = repr(vdc)
        assert "Vdc(" in r
        assert "x-test-light" in r
        assert "Test Light vDC" in r


# ---------------------------------------------------------------------------
# Vdc — get_properties / get_property_tree
# ---------------------------------------------------------------------------


class TestVdcProperties:
    """Tests for Vdc.get_properties() and get_property_tree()."""

    def test_get_properties_includes_all_keys(self):
        host = _make_host()
        vdc = _make_vdc(host)
        props = vdc.get_properties()
        expected_keys = {
            "dSUID",
            "displayId",
            "type",
            "model",
            "modelVersion",
            "modelUID",
            "hardwareVersion",
            "hardwareGuid",
            "hardwareModelGuid",
            "vendorName",
            "vendorId",
            "vendorGuid",
            "descriptionsGroup",
            "descriptionsClass",
            "oemGuid",
            "oemModelGuid",
            "configURL",
            "deviceIcon16",
            "deviceIconName",
            "name",
            "deviceClass",
            "deviceClassVersion",
            "active",
            "implementationId",
            "capabilities",
            "zoneID",
        }
        assert set(props.keys()) == expected_keys

    def test_get_properties_type_is_vdc(self):
        host = _make_host()
        vdc = _make_vdc(host)
        assert vdc.get_properties()["type"] == "vDC"

    def test_get_property_tree_structure(self):
        host = _make_host()
        vdc = _make_vdc(
            host,
            implementation_id="x-test-sensor",
            name="Sensor vDC",
            zone_id=5,
        )
        tree = vdc.get_property_tree()

        assert tree["implementationId"] == "x-test-sensor"
        assert tree["name"] == "Sensor vDC"
        assert tree["zoneID"] == 5
        assert "capabilities" in tree
        assert isinstance(tree["capabilities"], dict)
        assert tree["dSUID"] == str(vdc.dsuid)

    def test_get_property_tree_capabilities(self):
        host = _make_host()
        caps = VdcCapabilities(metering=True, dynamic_definitions=True)
        vdc = _make_vdc(host, capabilities=caps)
        tree = vdc.get_property_tree()
        assert tree["capabilities"]["metering"] is True
        assert tree["capabilities"]["identification"] is False
        assert tree["capabilities"]["dynamicDefinitions"] is True


# ---------------------------------------------------------------------------
# Vdc — auto-save integration
# ---------------------------------------------------------------------------


class TestVdcAutoSave:
    """Tests for auto-save triggering through the host."""

    async def test_tracked_attr_change_triggers_host_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        vdc.name = "New Name"
        # A handle should now be scheduled on the host.
        assert host._save_handle is not None
        host._cancel_auto_save()

    def test_non_tracked_attr_does_not_trigger(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        vdc._announced = True  # not tracked
        assert host._save_handle is None

    async def test_zone_id_is_tracked(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        vdc.zone_id = 99
        assert host._save_handle is not None
        host._cancel_auto_save()

    async def test_capabilities_setter_triggers_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        vdc.capabilities = VdcCapabilities(metering=True)
        assert host._save_handle is not None
        host._cancel_auto_save()

    def test_auto_save_disabled_during_init(self, tmp_path):
        host = _make_host(tmp_path)
        host._cancel_auto_save()

        # Creating a vDC should NOT trigger host auto-save
        # because _auto_save_enabled is False during __init__.
        _make_vdc(host)
        assert host._save_handle is None


# ---------------------------------------------------------------------------
# Vdc — state restoration (_apply_state)
# ---------------------------------------------------------------------------


class TestVdcApplyState:
    """Tests for Vdc._apply_state()."""

    def test_apply_state_restores_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        state = {
            "name": "Restored Name",
            "model": "Restored Model",
            "vendorName": "ACME Corp",
            "zoneID": 42,
            "capabilities": {
                "metering": True,
                "identification": False,
                "dynamicDefinitions": True,
            },
        }
        vdc._apply_state(state)

        assert vdc.name == "Restored Name"
        assert vdc.model == "Restored Model"
        assert vdc.vendor_name == "ACME Corp"
        assert vdc.zone_id == 42
        assert vdc.capabilities.metering is True
        assert vdc.capabilities.dynamic_definitions is True

    def test_apply_state_restores_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        original_dsuid = str(vdc.dsuid)

        new_dsuid = DsUid.from_name_in_space("other", DsUidNamespace.VDC)
        vdc._apply_state({"dSUID": str(new_dsuid)})
        assert str(vdc.dsuid) == str(new_dsuid)
        assert str(vdc.dsuid) != original_dsuid

    def test_apply_state_does_not_trigger_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        vdc._apply_state({"name": "No-save", "zoneID": 7})
        assert host._save_handle is None

    def test_apply_state_partial(self):
        host = _make_host()
        vdc = _make_vdc(host, name="Original", model="Model A")
        vdc._apply_state({"model": "Model B"})
        assert vdc.name == "Original"
        assert vdc.model == "Model B"

    def test_apply_state_all_common_properties(self):
        host = _make_host()
        vdc = _make_vdc(host)
        state = {
            "modelVersion": "2.0",
            "modelUID": "uid-123",
            "hardwareVersion": "hw-1.0",
            "hardwareGuid": "macaddress:AA:BB:CC:DD:EE:FF",
            "hardwareModelGuid": "gs1:(01)9999",
            "vendorGuid": "vendorname:Test",
            "oemGuid": "oemguid-1",
            "oemModelGuid": "oemmodel-1",
            "configURL": "http://example.com",
            "deviceIconName": "icon-sensor",
            "deviceClass": "dSSensor",
            "deviceClassVersion": "3",
        }
        vdc._apply_state(state)
        assert vdc.model_version == "2.0"
        assert vdc.model_uid == "uid-123"
        assert vdc.hardware_version == "hw-1.0"
        assert vdc.hardware_guid == "macaddress:AA:BB:CC:DD:EE:FF"
        assert vdc.hardware_model_guid == "gs1:(01)9999"
        assert vdc.vendor_guid == "vendorname:Test"
        assert vdc.oem_guid == "oemguid-1"
        assert vdc.oem_model_guid == "oemmodel-1"
        assert vdc.config_url == "http://example.com"
        assert vdc.device_icon_name == "icon-sensor"
        assert vdc.device_class == "dSSensor"
        assert vdc.device_class_version == "3"


# ---------------------------------------------------------------------------
# VdcHost — vDC management (add, remove, get)
# ---------------------------------------------------------------------------


class TestVdcHostVdcManagement:
    """Tests for VdcHost.add_vdc / remove_vdc / get_vdc / vdcs."""

    def test_add_vdc(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        assert str(vdc.dsuid) in host.vdcs
        assert host.get_vdc(vdc.dsuid) is vdc

    def test_add_vdc_replaces_existing(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-1")
        host.add_vdc(vdc1)
        # Create a second vdc with the same impl_id → same dSUID
        vdc2 = _make_vdc(host, implementation_id="x-test-1", name="New")
        host.add_vdc(vdc2)
        assert host.get_vdc(vdc1.dsuid) is vdc2
        assert len(host.vdcs) == 1

    def test_remove_vdc(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        removed = host.remove_vdc(vdc.dsuid)
        assert removed is vdc
        assert host.get_vdc(vdc.dsuid) is None
        assert len(host.vdcs) == 0

    def test_remove_vdc_nonexistent(self):
        host = _make_host()
        fake_dsuid = DsUid.from_name_in_space("fake", DsUidNamespace.VDC)
        assert host.remove_vdc(fake_dsuid) is None

    def test_get_vdc_nonexistent(self):
        host = _make_host()
        fake_dsuid = DsUid.from_name_in_space("fake", DsUidNamespace.VDC)
        assert host.get_vdc(fake_dsuid) is None

    def test_vdcs_returns_copy(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        copy = host.vdcs
        copy.clear()
        # Original registry should be unaffected.
        assert len(host.vdcs) == 1

    def test_multiple_vdcs(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-alpha")
        vdc2 = _make_vdc(host, implementation_id="x-test-beta")
        host.add_vdc(vdc1)
        host.add_vdc(vdc2)
        assert len(host.vdcs) == 2
        assert host.get_vdc(vdc1.dsuid) is vdc1
        assert host.get_vdc(vdc2.dsuid) is vdc2


# ---------------------------------------------------------------------------
# VdcHost — property tree with vDCs
# ---------------------------------------------------------------------------


class TestVdcHostPropertyTreeWithVdcs:
    """Tests for VdcHost.get_property_tree() including vDCs."""

    def test_property_tree_without_vdcs(self):
        host = _make_host()
        tree = host.get_property_tree()
        assert "vdcs" not in tree["vdcHost"]

    def test_property_tree_with_vdcs(self):
        host = _make_host()
        vdc = _make_vdc(host, implementation_id="x-test-sensor")
        host.add_vdc(vdc)
        tree = host.get_property_tree()

        assert "vdcs" in tree["vdcHost"]
        vdc_list = tree["vdcHost"]["vdcs"]
        assert len(vdc_list) == 1
        assert vdc_list[0]["implementationId"] == "x-test-sensor"
        assert vdc_list[0]["dSUID"] == str(vdc.dsuid)

    def test_property_tree_multiple_vdcs(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-a")
        vdc2 = _make_vdc(host, implementation_id="x-test-b")
        host.add_vdc(vdc1)
        host.add_vdc(vdc2)
        tree = host.get_property_tree()

        vdc_list = tree["vdcHost"]["vdcs"]
        assert len(vdc_list) == 2
        impl_ids = {v["implementationId"] for v in vdc_list}
        assert impl_ids == {"x-test-a", "x-test-b"}


# ---------------------------------------------------------------------------
# VdcHost — persistence with vDCs
# ---------------------------------------------------------------------------


class TestVdcHostPersistenceWithVdcs:
    """Tests for save/load round-trip including vDCs."""

    def test_save_and_load_with_vdcs(self, tmp_path):
        state_path = str(tmp_path / "state.yaml")

        # Phase 1: create host with vDC and save.
        host1 = VdcHost(
            name="Persist Host",
            mac="AA:BB:CC:DD:EE:01",
            state_path=state_path,
        )
        host1._cancel_auto_save()
        vdc = Vdc(
            host=host1,
            implementation_id="x-test-persist",
            name="Persist vDC",
            model="Persist Model",
            zone_id=7,
            capabilities=VdcCapabilities(metering=True),
        )
        host1.add_vdc(vdc)
        host1._cancel_auto_save()
        host1.save()

        # Verify YAML on disk.
        data = yaml.safe_load(Path(state_path).read_text())
        assert "vdcs" in data["vdcHost"]
        assert len(data["vdcHost"]["vdcs"]) == 1
        assert data["vdcHost"]["vdcs"][0]["name"] == "Persist vDC"
        assert data["vdcHost"]["vdcs"][0]["zoneID"] == 7

        # Phase 2: create a new host, add same vDC, and load.
        host2 = VdcHost(
            name="Persist Host",
            mac="AA:BB:CC:DD:EE:01",
            state_path=state_path,
        )
        host2._cancel_auto_save()
        vdc2 = Vdc(
            host=host2,
            implementation_id="x-test-persist",
            name="Default Name",
            model="Test Persist vDC",
        )
        host2.add_vdc(vdc2)
        host2._cancel_auto_save()
        loaded = host2.load()

        assert loaded is True
        restored_vdc = host2.get_vdc(vdc2.dsuid)
        assert restored_vdc is not None
        assert restored_vdc.name == "Persist vDC"
        assert restored_vdc.model == "Persist Model"
        assert restored_vdc.zone_id == 7
        assert restored_vdc.capabilities.metering is True

    def test_load_restores_vdcs_from_constructor(self, tmp_path):
        """Test that VdcHost constructor restores vDC state from YAML."""
        state_path = str(tmp_path / "state.yaml")

        # Phase 1: create host, add vDC, save.
        host1 = VdcHost(
            name="Host A",
            mac="11:22:33:44:55:66",
            state_path=state_path,
        )
        host1._cancel_auto_save()
        vdc = Vdc(
            host=host1,
            implementation_id="x-test-restore",
            name="Restored vDC",
            model="Test Restore vDC",
            zone_id=99,
        )
        host1.add_vdc(vdc)
        host1._cancel_auto_save()
        host1.save()

        # Phase 2: create new host — vDCs should be restored from YAML.
        host2 = VdcHost(
            name="Host A",
            mac="11:22:33:44:55:66",
            state_path=state_path,
        )
        host2._cancel_auto_save()

        assert len(host2.vdcs) == 1
        restored = list(host2.vdcs.values())[0]
        assert restored.implementation_id == "x-test-restore"
        assert restored.name == "Restored vDC"
        assert restored.zone_id == 99

    def test_save_without_vdcs_excludes_key(self, tmp_path):
        state_path = str(tmp_path / "state.yaml")
        host = VdcHost(
            name="No vDC Host",
            mac="AA:BB:CC:DD:EE:02",
            state_path=state_path,
        )
        host._cancel_auto_save()
        host.save()

        data = yaml.safe_load(Path(state_path).read_text())
        assert "vdcs" not in data["vdcHost"]

    async def test_add_vdc_triggers_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        host._cancel_auto_save()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        assert host._save_handle is not None
        host._cancel_auto_save()

    async def test_remove_vdc_triggers_auto_save(self, tmp_path):
        host = _make_host(tmp_path)
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        host.remove_vdc(vdc.dsuid)
        assert host._save_handle is not None
        host._cancel_auto_save()


# ---------------------------------------------------------------------------
# Vdc — announcement
# ---------------------------------------------------------------------------


def _make_mock_session(response_code: int = 0) -> VdcSession:
    """Create a mock VdcSession with a stubbed send_request."""
    session = MagicMock(spec=VdcSession)
    session.is_active = True

    response = pb.Message()
    response.type = pb.GENERIC_RESPONSE
    response.generic_response.code = response_code

    session.send_request = AsyncMock(return_value=response)
    return session


class TestVdcAnnouncement:
    """Tests for Vdc.announce()."""

    async def test_announce_success(self):
        host = _make_host()
        vdc = _make_vdc(host)
        session = _make_mock_session(pb.ERR_OK)

        result = await vdc.announce(session)
        assert result is True
        assert vdc.is_announced is True

        # Verify the sent message.
        session.send_request.assert_called_once()  # type: ignore[union-attr]
        msg: pb.Message = session.send_request.call_args[0][0]  # type: ignore[union-attr]
        assert msg.type == pb.VDC_SEND_ANNOUNCE_VDC
        assert msg.vdc_send_announce_vdc.dSUID == str(vdc.dsuid)

    async def test_announce_failure(self):
        host = _make_host()
        vdc = _make_vdc(host)
        session = _make_mock_session(pb.ERR_INSUFFICIENT_STORAGE)

        result = await vdc.announce(session)
        assert result is False
        assert vdc.is_announced is False

    async def test_announce_sets_correct_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host, implementation_id="x-test-unique")
        session = _make_mock_session(pb.ERR_OK)

        await vdc.announce(session)

        msg: pb.Message = session.send_request.call_args[0][0]  # type: ignore[union-attr]
        assert msg.vdc_send_announce_vdc.dSUID == str(vdc.dsuid)

    async def test_reset_announcement(self):
        host = _make_host()
        vdc = _make_vdc(host)
        session = _make_mock_session(pb.ERR_OK)

        await vdc.announce(session)
        assert vdc.is_announced is True

        vdc.reset_announcement()
        assert vdc.is_announced is False


# ---------------------------------------------------------------------------
# VdcHost — announce_vdcs
# ---------------------------------------------------------------------------


class TestVdcHostAnnounceVdcs:
    """Tests for VdcHost.announce_vdcs()."""

    async def test_announce_vdcs_no_session(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()
        with pytest.raises(ConnectionError, match="no active session"):
            await host.announce_vdcs()

    async def test_announce_vdcs_success(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-a")
        vdc2 = _make_vdc(host, implementation_id="x-test-b")
        host.add_vdc(vdc1)
        host.add_vdc(vdc2)
        host._cancel_auto_save()

        session = _make_mock_session(pb.ERR_OK)
        host._session = session

        count = await host.announce_vdcs()
        assert count == 2
        assert vdc1.is_announced is True
        assert vdc2.is_announced is True

    async def test_announce_vdcs_partial_failure(self):
        host = _make_host()
        vdc1 = _make_vdc(host, implementation_id="x-test-ok")
        vdc2 = _make_vdc(host, implementation_id="x-test-fail")
        host.add_vdc(vdc1)
        host.add_vdc(vdc2)
        host._cancel_auto_save()

        # First call succeeds, second fails.
        resp_ok = pb.Message()
        resp_ok.type = pb.GENERIC_RESPONSE
        resp_ok.generic_response.code = pb.ERR_OK

        resp_fail = pb.Message()
        resp_fail.type = pb.GENERIC_RESPONSE
        resp_fail.generic_response.code = pb.ERR_INSUFFICIENT_STORAGE

        session = MagicMock(spec=VdcSession)
        session.is_active = True
        session.send_request = AsyncMock(side_effect=[resp_ok, resp_fail])
        host._session = session

        count = await host.announce_vdcs()
        assert count == 1

    async def test_session_cleanup_resets_announcements(self):
        """Verify that ending a session resets vDC announcement state."""
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        # Simulate announced state.
        vdc._announced = True

        # Create a mock session.
        mock_conn = MagicMock(spec=VdcConnection)
        mock_conn.peername = "test:1234"
        mock_conn.receive = AsyncMock(return_value=None)  # EOF
        mock_conn.close = AsyncMock()

        session = VdcSession(
            connection=mock_conn,
            host_dsuid=str(host.dsuid),
        )
        host._session = session

        await host._run_session(session)

        assert vdc.is_announced is False


# ---------------------------------------------------------------------------
# VdcHost — _find_vdc_for_state
# ---------------------------------------------------------------------------


class TestFindVdcForState:
    """Tests for VdcHost._find_vdc_for_state()."""

    def test_find_by_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        host.add_vdc(vdc)
        host._cancel_auto_save()

        result = host._find_vdc_for_state({"dSUID": str(vdc.dsuid)})
        assert result is vdc

    def test_find_by_implementation_id(self):
        host = _make_host()
        vdc = _make_vdc(host, implementation_id="x-test-impl")
        host.add_vdc(vdc)
        host._cancel_auto_save()

        result = host._find_vdc_for_state({"implementationId": "x-test-impl"})
        assert result is vdc

    def test_find_no_match(self):
        host = _make_host()
        result = host._find_vdc_for_state(
            {"dSUID": "0000000000000000000000000000000000"}
        )
        assert result is None

    def test_dsuid_takes_priority(self):
        host = _make_host()
        vdc = _make_vdc(host, implementation_id="x-test-prio")
        host.add_vdc(vdc)
        host._cancel_auto_save()

        # Provide both dSUID (matching) and implementationId (non-matching)
        result = host._find_vdc_for_state(
            {
                "dSUID": str(vdc.dsuid),
                "implementationId": "x-other",
            }
        )
        assert result is vdc
