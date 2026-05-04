"""Tests for device property handling (§4.6.3 / §4.6.4)."""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.device_property import (
    PROPERTY_TYPE_ENUMERATION,
    PROPERTY_TYPE_NUMERIC,
    PROPERTY_TYPE_STRING,
    VALID_PROPERTY_TYPES,
    DeviceProperty,
)
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup, OutputFunction, OutputUsage
from pydsvdcapi.output import Output
from pydsvdcapi.property_handling import NO_VALUE, elements_to_dict
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
        "implementation_id": "x-test-prop",
        "name": "Test Prop vDC",
        "model": "Test Prop v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space(
        "prop-test-device", DsUidNamespace.VDC
    )


def _make_device(vdc: Vdc, dsuid: Optional[DsUid] = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "Prop Test vdSD",
        "model": "Test Prop vdSD",
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
# DeviceProperty construction and properties
# ===========================================================================


class TestDevicePropertyConstruction:
    """Tests for DeviceProperty creation and property access."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="batteryLevel",
            type=PROPERTY_TYPE_NUMERIC,
        )

        assert prop.vdsd is vdsd
        assert prop.ds_index == 0
        assert prop.name == "batteryLevel"
        assert prop.type == "numeric"
        assert prop.min_value is None
        assert prop.max_value is None
        assert prop.resolution is None
        assert prop.siunit is None
        assert prop.options is None
        assert prop.default is None
        assert prop.description is None
        assert prop.value is None

    def test_full_numeric_construction(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="temperature",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=-40.0, max_value=80.0,
            resolution=0.1, siunit="°C",
            default=20.0,
            description="Measured temperature",
        )

        assert prop.min_value == -40.0
        assert prop.max_value == 80.0
        assert prop.resolution == 0.1
        assert prop.siunit == "°C"
        assert prop.default == 20.0
        assert prop.description == "Measured temperature"

    def test_enumeration_construction(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
            options={0: "Auto", 1: "Manual", 2: "Eco"},
            default="0",
        )

        assert prop.type == "enumeration"
        assert prop.options == {0: "Auto", 1: "Manual", 2: "Eco"}
        assert prop.default == "0"

    def test_string_construction(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="serialNumber",
            type=PROPERTY_TYPE_STRING,
            default="N/A",
        )

        assert prop.type == "string"
        assert prop.default == "N/A"

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")

        prop.name = "newName"
        assert prop.name == "newName"

        prop.type = "numeric"
        assert prop.type == "numeric"

        prop.min_value = -10.0
        assert prop.min_value == -10.0

        prop.max_value = 100.0
        assert prop.max_value == 100.0

        prop.resolution = 0.5
        assert prop.resolution == 0.5

        prop.siunit = "K"
        assert prop.siunit == "K"

        prop.options = {0: "A", 1: "B"}
        assert prop.options == {0: "A", 1: "B"}

        prop.default = 42.0
        assert prop.default == 42.0

        prop.description = "Updated"
        assert prop.description == "Updated"

        prop.value = 99.0
        assert prop.value == 99.0

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test", type="numeric"
        )
        r = repr(prop)
        assert "DeviceProperty" in r
        assert "test" in r
        assert "numeric" in r

    def test_options_copy_safety(self):
        """options property returns a copy, not the internal dict."""
        _, _, _, vdsd = _make_stack()
        opts = {0: "A", 1: "B"}
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_ENUMERATION,
            options=opts,
        )

        returned = prop.options
        returned[99] = "Extra"
        assert 99 not in prop.options

        opts[99] = "Extra2"
        assert 99 not in prop.options

    def test_options_none_returns_none(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")
        assert prop.options is None

    def test_valid_property_types(self):
        assert "numeric" in VALID_PROPERTY_TYPES
        assert "enumeration" in VALID_PROPERTY_TYPES
        assert "string" in VALID_PROPERTY_TYPES
        assert len(VALID_PROPERTY_TYPES) == 3


# ===========================================================================
# Description properties
# ===========================================================================


class TestDevicePropertyDescriptionProperties:
    """Tests for get_description_properties()."""

    def test_numeric_minimal(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="value",
            type=PROPERTY_TYPE_NUMERIC,
        )
        desc = prop.get_description_properties()
        assert desc["name"] == "value"
        assert desc["type"] == "numeric"
        assert "min" not in desc
        assert "max" not in desc
        assert "resolution" not in desc
        assert "siunit" not in desc
        assert "values" not in desc
        assert "default" not in desc
        assert "description" not in desc

    def test_numeric_full(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="temp",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
            resolution=0.1, siunit="%",
            default=50.0,
            description="Temperature",
        )
        desc = prop.get_description_properties()
        assert desc["name"] == "temp"
        assert desc["description"] == "Temperature"
        assert desc["min"] == 0.0
        assert desc["max"] == 100.0
        assert desc["resolution"] == 0.1
        assert desc["siunit"] == "%"
        assert desc["default"] == 50.0

    def test_enumeration(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
            options={0: "Auto", 1: "Manual"},
        )
        desc = prop.get_description_properties()
        assert desc["type"] == "enumeration"
        assert desc["values"] == {"Auto": NO_VALUE, "Manual": NO_VALUE}
        # Numeric fields should not be present even if set
        assert "min" not in desc
        assert "max" not in desc

    def test_string_type(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="serial",
            type=PROPERTY_TYPE_STRING,
            default="unknown",
        )
        desc = prop.get_description_properties()
        assert desc["type"] == "string"
        assert desc["default"] == "unknown"
        assert "values" not in desc

    def test_enumeration_empty_options_not_included(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_ENUMERATION,
        )
        desc = prop.get_description_properties()
        assert "values" not in desc


# ===========================================================================
# Value properties
# ===========================================================================


class TestDevicePropertyValueProperties:
    """Tests for get_value_properties()."""

    def test_no_value(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")

        val = prop.get_value_properties()
        assert val is None

    def test_with_value(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")
        prop.value = 42.0

        val = prop.get_value_properties()
        assert val == 42.0


# ===========================================================================
# Persistence
# ===========================================================================


class TestDevicePropertyPersistence:
    """Tests for property tree and state restoration."""

    def test_get_property_tree_minimal(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_STRING,
        )
        tree = prop.get_property_tree()
        assert tree["dsIndex"] == 0
        assert tree["name"] == "test"
        assert tree["type"] == "string"
        assert "value" not in tree

    def test_get_property_tree_numeric_full(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=1, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
            resolution=1.0, siunit="%",
            default=100.0,
            description="Battery level",
        )
        prop.value = 85.0
        tree = prop.get_property_tree()
        assert tree["dsIndex"] == 1
        assert tree["name"] == "battery"
        assert tree["type"] == "numeric"
        assert tree["minValue"] == 0.0
        assert tree["maxValue"] == 100.0
        assert tree["resolution"] == 1.0
        assert tree["siunit"] == "%"
        assert tree["default"] == 100.0
        assert tree["description"] == "Battery level"
        assert tree["value"] == 85.0  # value IS persisted

    def test_get_property_tree_enumeration(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
            options={0: "Auto", 1: "Manual"},
        )
        tree = prop.get_property_tree()
        assert tree["options"] == {"0": "Auto", "1": "Manual"}

    def test_value_is_persisted(self):
        """Unlike device states, property values ARE persisted."""
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_STRING,
        )
        prop.value = "hello"
        tree = prop.get_property_tree()
        assert tree["value"] == "hello"

    def test_roundtrip(self):
        """Persist → restore preserves all fields including value."""
        _, _, _, vdsd = _make_stack()
        orig = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
            resolution=1.0, siunit="%",
            default=100.0,
            description="Battery level",
        )
        orig.value = 73.5
        tree = orig.get_property_tree()

        restored = DeviceProperty(vdsd=vdsd, ds_index=0, name="")
        restored._apply_state(tree)

        assert restored.name == "battery"
        assert restored.type == "numeric"
        assert restored.min_value == 0.0
        assert restored.max_value == 100.0
        assert restored.resolution == 1.0
        assert restored.siunit == "%"
        assert restored.default == 100.0
        assert restored.description == "Battery level"
        assert restored.value == 73.5

    def test_roundtrip_enumeration(self):
        _, _, _, vdsd = _make_stack()
        orig = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
            options={0: "Auto", 1: "Manual"},
        )
        orig.value = "1"
        tree = orig.get_property_tree()

        restored = DeviceProperty(vdsd=vdsd, ds_index=0, name="")
        restored._apply_state(tree)

        assert restored.options == {0: "Auto", 1: "Manual"}
        assert restored.value == "1"

    def test_apply_state_partial(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="original",
            type=PROPERTY_TYPE_STRING,
        )
        prop._apply_state({"name": "updated"})
        assert prop.name == "updated"
        assert prop.type == "string"  # unchanged


# ===========================================================================
# Vdsd integration — management methods
# ===========================================================================


class TestVdsdDevicePropertyManagement:
    """Tests for add/remove/get device properties on Vdsd."""

    def test_add_and_get(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_STRING,
        )
        vdsd.add_device_property(prop)

        assert vdsd.get_device_property(0) is prop
        assert 0 in vdsd.device_properties
        assert len(vdsd.device_properties) == 1

    def test_add_replace(self):
        _, _, _, vdsd = _make_stack()
        p1 = DeviceProperty(vdsd=vdsd, ds_index=0, name="first")
        p2 = DeviceProperty(vdsd=vdsd, ds_index=0, name="second")

        vdsd.add_device_property(p1)
        vdsd.add_device_property(p2)
        assert vdsd.get_device_property(0) is p2

    def test_remove(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")
        vdsd.add_device_property(prop)

        removed = vdsd.remove_device_property(0)
        assert removed is prop
        assert vdsd.get_device_property(0) is None
        assert len(vdsd.device_properties) == 0

    def test_remove_nonexistent(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.remove_device_property(99) is None

    def test_wrong_vdsd_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        dev1 = _make_device(vdc, DsUid.from_name_in_space("d1", DsUidNamespace.VDC))
        dev2 = _make_device(vdc, DsUid.from_name_in_space("d2", DsUidNamespace.VDC))
        vdsd1 = _make_vdsd(dev1)
        vdsd2 = _make_vdsd(dev2)

        prop = DeviceProperty(vdsd=vdsd1, ds_index=0, name="test")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd2.add_device_property(prop)

    def test_device_properties_returns_copy(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(vdsd=vdsd, ds_index=0, name="test")
        vdsd.add_device_property(prop)

        copy = vdsd.device_properties
        copy[99] = "junk"
        assert 99 not in vdsd.device_properties

    def test_multiple_properties(self):
        _, _, _, vdsd = _make_stack()
        p0 = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
        )
        p1 = DeviceProperty(
            vdsd=vdsd, ds_index=1, name="serial",
            type=PROPERTY_TYPE_STRING,
        )
        vdsd.add_device_property(p0)
        vdsd.add_device_property(p1)

        assert len(vdsd.device_properties) == 2
        assert vdsd.get_device_property(0) is p0
        assert vdsd.get_device_property(1) is p1


# ===========================================================================
# Vdsd integration — get_properties
# ===========================================================================


class TestVdsdDevicePropertyProperties:
    """Tests for devicePropertyDescriptions / deviceProperties in get_properties."""

    def test_no_properties_no_keys(self):
        _, _, _, vdsd = _make_stack()
        props = vdsd.get_properties()
        assert "devicePropertyDescriptions" not in props
        assert "deviceProperties" not in props

    def test_with_properties(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
            resolution=1.0, siunit="%",
            description="Battery level",
        )
        vdsd.add_device_property(prop)

        props = vdsd.get_properties()
        assert "devicePropertyDescriptions" in props
        assert "deviceProperties" in props

        desc = props["devicePropertyDescriptions"]
        assert "battery" in desc
        assert desc["battery"]["name"] == "battery"
        assert desc["battery"]["type"] == "numeric"
        assert desc["battery"]["min"] == 0.0
        assert desc["battery"]["max"] == 100.0
        assert desc["battery"]["resolution"] == 1.0
        assert desc["battery"]["siunit"] == "%"
        assert desc["battery"]["description"] == "Battery level"

        vals = props["deviceProperties"]
        assert "battery" in vals
        assert vals["battery"] is None  # no value set yet

    def test_with_value_set(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
        )
        prop.value = 85.0
        vdsd.add_device_property(prop)

        props = vdsd.get_properties()
        assert props["deviceProperties"]["battery"] == 85.0


# ===========================================================================
# Vdsd integration — persistence
# ===========================================================================


class TestVdsdDevicePropertyPersistence:
    """Tests for device property persistence roundtrip via Vdsd."""

    def test_property_tree_includes_properties(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
        )
        prop.value = 85.0
        vdsd.add_device_property(prop)

        tree = vdsd.get_property_tree()
        assert "deviceProperties" in tree
        assert len(tree["deviceProperties"]) == 1
        assert tree["deviceProperties"][0]["name"] == "battery"
        assert tree["deviceProperties"][0]["value"] == 85.0

    def test_apply_state_restores_properties(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
        )
        prop.value = 73.5
        vdsd.add_device_property(prop)
        tree = vdsd.get_property_tree()

        # Create fresh vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        dev2.add_vdsd(vdsd2)
        vdc2.add_device(dev2)

        vdsd2._apply_state(tree)
        assert len(vdsd2.device_properties) == 1
        restored = vdsd2.get_device_property(0)
        assert restored is not None
        assert restored.name == "battery"
        assert restored.type == "numeric"
        assert restored.min_value == 0.0
        assert restored.max_value == 100.0
        assert restored.value == 73.5

    def test_full_roundtrip(self):
        """get_property_tree → new vdsd._apply_state roundtrip."""
        _, _, _, vdsd1 = _make_stack()
        p0 = DeviceProperty(
            vdsd=vdsd1, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
            min_value=0.0, max_value=100.0,
            resolution=1.0, siunit="%",
            default=100.0,
            description="Battery level",
        )
        p0.value = 85.0
        p1 = DeviceProperty(
            vdsd=vdsd1, ds_index=1, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
            options={0: "Auto", 1: "Manual"},
        )
        p1.value = "1"
        vdsd1.add_device_property(p0)
        vdsd1.add_device_property(p1)

        tree = vdsd1.get_property_tree()

        # Create a new vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        vdsd2._apply_state(tree)

        assert len(vdsd2.device_properties) == 2

        rp0 = vdsd2.get_device_property(0)
        assert rp0.name == "battery"
        assert rp0.value == 85.0
        assert rp0.min_value == 0.0
        assert rp0.siunit == "%"

        rp1 = vdsd2.get_device_property(1)
        assert rp1.name == "mode"
        assert rp1.options == {0: "Auto", 1: "Manual"}
        assert rp1.value == "1"


# ===========================================================================
# Push notification — update_value
# ===========================================================================


class TestDevicePropertyUpdateValue:
    """Tests for update_value() push notification."""

    @pytest.mark.asyncio
    async def test_update_numeric_value_pushes(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
        )
        vdsd.add_device_property(prop)

        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        await prop.update_value(85.0)

        assert prop.value == 85.0
        assert session.send_notification.call_count == 1

        # Verify the message structure.
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)

        # Decode the pushed properties.
        pushed = elements_to_dict(
            msg.vdc_send_push_notification.changedproperties
        )
        assert "deviceProperties" in pushed
        assert "battery" in pushed["deviceProperties"]
        assert pushed["deviceProperties"]["battery"] == 85.0

    @pytest.mark.asyncio
    async def test_update_string_value(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="serial",
            type=PROPERTY_TYPE_STRING,
        )
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await prop.update_value("ABC123")
        assert prop.value == "ABC123"

    @pytest.mark.asyncio
    async def test_update_numeric_converts_to_float(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_NUMERIC,
        )
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await prop.update_value(42)  # int
        assert prop.value == 42.0
        assert isinstance(prop.value, float)

    @pytest.mark.asyncio
    async def test_update_enumeration_stores_as_string(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="mode",
            type=PROPERTY_TYPE_ENUMERATION,
        )
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await prop.update_value(1)
        assert prop.value == "1"
        assert isinstance(prop.value, str)

    @pytest.mark.asyncio
    async def test_update_value_no_session(self):
        """Value is recorded but no push when no session."""
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_NUMERIC,
        )

        await prop.update_value(42.0)
        assert prop.value == 42.0

    @pytest.mark.asyncio
    async def test_update_value_not_announced(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_NUMERIC,
        )
        vdsd._session = _make_mock_session()
        vdsd._announced = False

        await prop.update_value(42.0)
        assert prop.value == 42.0
        assert vdsd._session.send_notification.call_count == 0

    @pytest.mark.asyncio
    async def test_update_value_connection_error(self):
        """Push failure is logged, not raised."""
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_NUMERIC,
        )
        session = _make_mock_session()
        session.send_notification = AsyncMock(
            side_effect=ConnectionError("lost")
        )
        vdsd._announced = True
        vdsd._session = session

        await prop.update_value(42.0)  # should not raise
        assert prop.value == 42.0

    @pytest.mark.asyncio
    async def test_update_value_explicit_session(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="test",
            type=PROPERTY_TYPE_NUMERIC,
        )

        internal_session = _make_mock_session()
        explicit_session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = internal_session

        await prop.update_value(42.0, session=explicit_session)
        assert explicit_session.send_notification.call_count == 1
        assert internal_session.send_notification.call_count == 0


# ===========================================================================
# Vdsd convenience — update_device_property
# ===========================================================================


class TestVdsdUpdateDeviceProperty:
    """Tests for vdsd.update_device_property() convenience method."""

    @pytest.mark.asyncio
    async def test_update_device_property(self):
        _, _, _, vdsd = _make_stack()
        prop = DeviceProperty(
            vdsd=vdsd, ds_index=0, name="battery",
            type=PROPERTY_TYPE_NUMERIC,
        )
        vdsd.add_device_property(prop)
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await vdsd.update_device_property(0, 85.0)
        assert prop.value == 85.0

    @pytest.mark.asyncio
    async def test_update_device_property_not_found(self):
        _, _, _, vdsd = _make_stack()
        with pytest.raises(KeyError, match="No DeviceProperty"):
            await vdsd.update_device_property(99, 42.0)
