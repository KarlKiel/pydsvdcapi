"""Tests for device action handling (§4.5)."""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.vdcapi_pb2 import PropertyElement, PropertyValue
from pydsvdcapi.actions import (
    ActionParameter,
    CustomAction,
    DeviceActionDescription,
    DynamicAction,
    StandardAction,
)
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
from pydsvdcapi.property_handling import elements_to_dict
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import VdcHost
from pydsvdcapi.vdsd import Device, InvokeActionCallback, Vdsd


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
        "implementation_id": "x-test-action",
        "name": "Test Action vDC",
        "model": "Test Action v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space(
        "action-test-device", DsUidNamespace.VDC
    )


def _make_device(vdc: Vdc, dsuid: Optional[DsUid] = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "Action Test vdSD",
        "model": "Test Action vdSD",
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
# ActionParameter
# ===========================================================================


class TestActionParameter:
    """Tests for ActionParameter construction and property generation."""

    def test_default_construction(self):
        p = ActionParameter(name="volume", type="numeric")
        assert p.name == "volume"
        assert p.type == "numeric"
        assert p.min_value is None
        assert p.max_value is None
        assert p.resolution is None
        assert p.siunit is None
        assert p.options is None
        assert p.default is None

    def test_numeric_properties(self):
        p = ActionParameter(
            name="level", type="numeric",
            min_value=0.0, max_value=100.0,
            resolution=0.5, siunit="%", default=50.0,
        )
        props = p.get_properties()
        assert props == {
            "type": "numeric",
            "min": 0.0,
            "max": 100.0,
            "resolution": 0.5,
            "siunit": "%",
            "default": 50.0,
        }

    def test_enumeration_properties(self):
        p = ActionParameter(
            name="mode", type="enumeration",
            options={0: "Off", 1: "On", 2: "Auto"},
            default="Auto",
        )
        props = p.get_properties()
        assert props["type"] == "enumeration"
        assert props["options"] == {"0": "Off", "1": "On", "2": "Auto"}
        assert props["default"] == "Auto"
        # numeric fields should NOT be present for enumeration
        assert "min" not in props
        assert "max" not in props

    def test_string_properties(self):
        p = ActionParameter(name="url", type="string", default="http://")
        props = p.get_properties()
        assert props == {"type": "string", "default": "http://"}

    def test_property_tree_roundtrip(self):
        p = ActionParameter(
            name="temp", type="numeric",
            min_value=-10.0, max_value=40.0,
            resolution=0.1, siunit="°C", default=20.0,
        )
        tree = p.get_property_tree()
        assert tree["name"] == "temp"
        assert tree["type"] == "numeric"
        assert tree["minValue"] == -10.0
        assert tree["maxValue"] == 40.0

        restored = ActionParameter.from_persisted(tree)
        assert restored.name == "temp"
        assert restored.type == "numeric"
        assert restored.min_value == -10.0
        assert restored.max_value == 40.0
        assert restored.resolution == 0.1
        assert restored.siunit == "°C"
        assert restored.default == 20.0

    def test_enumeration_tree_roundtrip(self):
        p = ActionParameter(
            name="mode", type="enumeration",
            options={0: "Off", 1: "On"},
        )
        tree = p.get_property_tree()
        restored = ActionParameter.from_persisted(tree)
        assert restored.options == {0: "Off", 1: "On"}

    def test_setters(self):
        p = ActionParameter(name="x")
        p.name = "y"
        p.type = "numeric"
        p.min_value = 1.0
        p.max_value = 99.0
        p.resolution = 0.5
        p.siunit = "V"
        p.options = {0: "Low"}
        p.default = 42.0
        assert p.name == "y"
        assert p.type == "numeric"
        assert p.min_value == 1.0
        assert p.max_value == 99.0
        assert p.resolution == 0.5
        assert p.siunit == "V"
        assert p.options == {0: "Low"}
        assert p.default == 42.0

    def test_repr(self):
        p = ActionParameter(name="vol", type="numeric")
        assert "vol" in repr(p)
        assert "numeric" in repr(p)


# ===========================================================================
# DeviceActionDescription
# ===========================================================================


class TestDeviceActionDescription:
    """Tests for DeviceActionDescription construction and properties."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
        )
        assert desc.vdsd is vdsd
        assert desc.ds_index == 0
        assert desc.name == "play"
        assert desc.params == []
        assert desc.description is None

    def test_with_params_and_description(self):
        _, _, _, vdsd = _make_stack()
        p1 = ActionParameter(name="volume", type="numeric", min_value=0, max_value=100)
        p2 = ActionParameter(name="source", type="string")
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
            params=[p1, p2],
            description="Play media",
        )
        props = desc.get_description_properties()
        assert props["name"] == "play"
        assert props["description"] == "Play media"
        assert "volume" in props["params"]
        assert props["params"]["volume"]["type"] == "numeric"
        assert "source" in props["params"]
        assert props["params"]["source"]["type"] == "string"

    def test_no_params_omitted(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="stop",
        )
        props = desc.get_description_properties()
        assert "params" not in props
        assert "description" not in props

    def test_property_tree_roundtrip(self):
        _, _, _, vdsd = _make_stack()
        p = ActionParameter(name="vol", type="numeric", default=50.0)
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=2, name="play",
            params=[p], description="Play media",
        )
        tree = desc.get_property_tree()
        assert tree["dsIndex"] == 2
        assert tree["name"] == "play"
        assert len(tree["params"]) == 1
        assert tree["params"][0]["name"] == "vol"

        # Restore
        desc2 = DeviceActionDescription(vdsd=vdsd, ds_index=2)
        desc2._apply_state(tree)
        assert desc2.name == "play"
        assert desc2.description == "Play media"
        assert len(desc2.params) == 1
        assert desc2.params[0].name == "vol"
        assert desc2.params[0].default == 50.0

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd)
        desc.name = "play"
        desc.description = "Play it"
        p = ActionParameter(name="x")
        desc.params = [p]
        assert desc.name == "play"
        assert desc.description == "Play it"
        assert len(desc.params) == 1

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        r = repr(desc)
        assert "play" in r
        assert "DeviceActionDescription" in r


# ===========================================================================
# StandardAction
# ===========================================================================


class TestStandardAction:
    """Tests for StandardAction construction and properties."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play",
            action="play",
        )
        assert std.vdsd is vdsd
        assert std.ds_index == 0
        assert std.name == "std.play"
        assert std.action == "play"
        assert std.params is None

    def test_with_params(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play",
            action="play", params={"volume": 80},
        )
        props = std.get_properties()
        assert props["name"] == "std.play"
        assert props["action"] == "play"
        assert props["params"] == {"volume": 80}

    def test_no_params_omitted(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.stop",
            action="stop",
        )
        props = std.get_properties()
        assert "params" not in props

    def test_property_tree_roundtrip(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=1, name="std.play",
            action="play", params={"volume": 80},
        )
        tree = std.get_property_tree()
        assert tree["dsIndex"] == 1
        assert tree["action"] == "play"

        std2 = StandardAction(vdsd=vdsd, ds_index=1)
        std2._apply_state(tree)
        assert std2.name == "std.play"
        assert std2.action == "play"
        assert std2.params == {"volume": 80}

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(vdsd=vdsd)
        std.name = "std.x"
        std.action = "x"
        std.params = {"a": 1}
        assert std.name == "std.x"
        assert std.action == "x"
        assert std.params == {"a": 1}

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(vdsd=vdsd, ds_index=0, name="std.play", action="play")
        assert "std.play" in repr(std)


# ===========================================================================
# CustomAction
# ===========================================================================


class TestCustomAction:
    """Tests for CustomAction construction, properties, and writability."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.loud",
            action="play", title="Play Loud",
        )
        assert cust.vdsd is vdsd
        assert cust.ds_index == 0
        assert cust.name == "custom.loud"
        assert cust.action == "play"
        assert cust.title == "Play Loud"
        assert cust.params is None

    def test_with_params(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.loud",
            action="play", title="Play Loud",
            params={"volume": 100},
        )
        props = cust.get_properties()
        assert props["name"] == "custom.loud"
        assert props["action"] == "play"
        assert props["title"] == "Play Loud"
        assert props["params"] == {"volume": 100}

    def test_apply_settings(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="Old Title",
        )
        cust.apply_settings({
            "action": "stop",
            "title": "New Title",
            "params": {"key": "value"},
        })
        assert cust.action == "stop"
        assert cust.title == "New Title"
        assert cust.params == {"key": "value"}

    def test_apply_settings_partial(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="Title",
        )
        cust.apply_settings({"title": "Updated"})
        assert cust.title == "Updated"
        assert cust.action == "play"  # unchanged

    def test_property_tree_roundtrip(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=3, name="custom.loud",
            action="play", title="Loud Play",
            params={"volume": 100},
        )
        tree = cust.get_property_tree()
        assert tree["dsIndex"] == 3
        assert tree["title"] == "Loud Play"

        cust2 = CustomAction(vdsd=vdsd, ds_index=3)
        cust2._apply_state(tree)
        assert cust2.name == "custom.loud"
        assert cust2.action == "play"
        assert cust2.title == "Loud Play"
        assert cust2.params == {"volume": 100}

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(vdsd=vdsd)
        cust.name = "custom.x"
        cust.action = "x"
        cust.title = "X Title"
        cust.params = {"a": 1}
        assert cust.name == "custom.x"
        assert cust.action == "x"
        assert cust.title == "X Title"
        assert cust.params == {"a": 1}

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, name="custom.a", action="play", title="Title"
        )
        r = repr(cust)
        assert "custom.a" in r
        assert "play" in r
        assert "Title" in r


# ===========================================================================
# DynamicAction
# ===========================================================================


class TestDynamicAction:
    """Tests for DynamicAction construction and properties."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(
            vdsd=vdsd, ds_index=0, name="dynamic.special",
            title="Special Mode",
        )
        assert dyn.vdsd is vdsd
        assert dyn.ds_index == 0
        assert dyn.name == "dynamic.special"
        assert dyn.title == "Special Mode"

    def test_properties(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(
            vdsd=vdsd, ds_index=0, name="dynamic.x",
            title="X Mode",
        )
        props = dyn.get_properties()
        assert props == {
            "name": "dynamic.x",
            "title": "X Mode",
        }

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(vdsd=vdsd)
        dyn.name = "dynamic.y"
        dyn.title = "Y Mode"
        assert dyn.name == "dynamic.y"
        assert dyn.title == "Y Mode"

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(vdsd=vdsd, name="dynamic.z", title="Z")
        assert "dynamic.z" in repr(dyn)


# ===========================================================================
# Vdsd integration
# ===========================================================================


class TestVdsdActionRegistration:
    """Tests for adding/removing/querying actions on Vdsd."""

    def test_add_action_description(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
        )
        vdsd.add_device_action_description(desc)
        assert vdsd.action_descriptions == {0: desc}
        assert vdsd.get_device_action_description(0) is desc

    def test_add_action_description_wrong_vdsd(self):
        _, _, _, vdsd1 = _make_stack()
        host2, vdc2, dev2, vdsd2 = _make_stack()
        desc = DeviceActionDescription(
            vdsd=vdsd2, ds_index=0, name="play",
        )
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd1.add_device_action_description(desc)

    def test_remove_action_description(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        vdsd.add_device_action_description(desc)
        removed = vdsd.remove_device_action_description(0)
        assert removed is desc
        assert vdsd.action_descriptions == {}

    def test_add_standard_action(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play", action="play",
        )
        vdsd.add_standard_action(std)
        assert vdsd.standard_actions == {0: std}
        assert vdsd.get_standard_action(0) is std

    def test_add_standard_action_wrong_vdsd(self):
        _, _, _, vdsd1 = _make_stack()
        _, _, _, vdsd2 = _make_stack()
        std = StandardAction(vdsd=vdsd2, ds_index=0, name="std.x", action="x")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd1.add_standard_action(std)

    def test_remove_standard_action(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(vdsd=vdsd, ds_index=0, name="std.x", action="x")
        vdsd.add_standard_action(std)
        assert vdsd.remove_standard_action(0) is std
        assert vdsd.standard_actions == {}

    def test_add_custom_action(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="A",
        )
        vdsd.add_custom_action(cust)
        assert vdsd.custom_actions == {0: cust}
        assert vdsd.get_custom_action(0) is cust

    def test_add_custom_action_wrong_vdsd(self):
        _, _, _, vdsd1 = _make_stack()
        _, _, _, vdsd2 = _make_stack()
        cust = CustomAction(vdsd=vdsd2, name="custom.a", action="a", title="A")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd1.add_custom_action(cust)

    def test_remove_custom_action(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="A",
        )
        vdsd.add_custom_action(cust)
        assert vdsd.remove_custom_action(0) is cust
        assert vdsd.custom_actions == {}

    def test_add_dynamic_action(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(
            vdsd=vdsd, ds_index=0, name="dynamic.x", title="X",
        )
        vdsd.add_dynamic_action(dyn)
        assert vdsd.dynamic_actions == {0: dyn}
        assert vdsd.get_dynamic_action(0) is dyn

    def test_add_dynamic_action_wrong_vdsd(self):
        _, _, _, vdsd1 = _make_stack()
        _, _, _, vdsd2 = _make_stack()
        dyn = DynamicAction(vdsd=vdsd2, name="dynamic.x", title="X")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd1.add_dynamic_action(dyn)

    def test_remove_dynamic_action(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(vdsd=vdsd, ds_index=0, name="dynamic.x", title="X")
        vdsd.add_dynamic_action(dyn)
        assert vdsd.remove_dynamic_action(0) is dyn
        assert vdsd.dynamic_actions == {}

    def test_remove_nonexistent_returns_none(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.remove_device_action_description(99) is None
        assert vdsd.remove_standard_action(99) is None
        assert vdsd.remove_custom_action(99) is None
        assert vdsd.remove_dynamic_action(99) is None


# ===========================================================================
# get_properties SingleDevice integration
# ===========================================================================


class TestGetPropertiesActions:
    """Tests for action containers in get_properties()."""

    def test_actions_trigger_single_device(self):
        """Adding action descriptions should trigger SingleDevice containers."""
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        vdsd.add_device_action_description(desc)
        props = vdsd.get_properties()
        assert "deviceActionDescriptions" in props
        assert "standardActions" in props
        assert "customActions" in props
        assert "dynamicActionDescriptions" in props

    def test_action_descriptions_in_properties(self):
        _, _, _, vdsd = _make_stack()
        p = ActionParameter(name="vol", type="numeric", min_value=0, max_value=100)
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
            params=[p], description="Play",
        )
        vdsd.add_device_action_description(desc)
        props = vdsd.get_properties()
        ad = props["deviceActionDescriptions"]
        assert "play" in ad
        assert ad["play"]["name"] == "play"
        assert ad["play"]["description"] == "Play"
        assert "vol" in ad["play"]["params"]

    def test_standard_actions_in_properties(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        vdsd.add_device_action_description(desc)
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play",
            action="play", params={"volume": 80},
        )
        vdsd.add_standard_action(std)
        props = vdsd.get_properties()
        sa = props["standardActions"]
        assert "std.play" in sa
        assert sa["std.play"]["name"] == "std.play"
        assert sa["std.play"]["action"] == "play"
        assert sa["std.play"]["params"] == {"volume": 80}

    def test_custom_actions_in_properties(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        vdsd.add_device_action_description(desc)
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.loud",
            action="play", title="Loud", params={"volume": 100},
        )
        vdsd.add_custom_action(cust)
        props = vdsd.get_properties()
        ca = props["customActions"]
        assert "custom.loud" in ca
        assert ca["custom.loud"]["name"] == "custom.loud"
        assert ca["custom.loud"]["title"] == "Loud"

    def test_dynamic_actions_in_properties(self):
        _, _, _, vdsd = _make_stack()
        desc = DeviceActionDescription(vdsd=vdsd, ds_index=0, name="play")
        vdsd.add_device_action_description(desc)
        dyn = DynamicAction(
            vdsd=vdsd, ds_index=0, name="dynamic.x", title="X",
        )
        vdsd.add_dynamic_action(dyn)
        props = vdsd.get_properties()
        da = props["dynamicActionDescriptions"]
        assert "dynamic.x" in da
        assert da["dynamic.x"]["name"] == "dynamic.x"
        assert da["dynamic.x"]["title"] == "X"

    def test_empty_containers_when_only_states(self):
        """With only states defined, action containers should be empty."""
        from pydsvdcapi.device_state import DeviceState

        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd, ds_index=0, name="state",
            options={0: "Off"},
        )
        vdsd.add_device_state(st)
        props = vdsd.get_properties()
        assert props["deviceActionDescriptions"] == {}
        assert props["standardActions"] == {}
        assert props["customActions"] == {}
        assert props["dynamicActionDescriptions"] == {}

    def test_no_single_device_without_features(self):
        """Without any SingleDevice feature, action containers absent."""
        _, _, _, vdsd = _make_stack()
        props = vdsd.get_properties()
        assert "deviceActionDescriptions" not in props
        assert "standardActions" not in props
        assert "customActions" not in props
        assert "dynamicActionDescriptions" not in props


# ===========================================================================
# Persistence
# ===========================================================================


class TestActionPersistence:
    """Tests for action persistence via get_property_tree / _apply_state."""

    def test_persist_action_descriptions(self):
        _, _, _, vdsd = _make_stack()
        p = ActionParameter(name="vol", type="numeric", default=50.0)
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
            params=[p], description="Play media",
        )
        vdsd.add_device_action_description(desc)
        tree = vdsd.get_property_tree()
        assert "actionDescriptions" in tree
        assert len(tree["actionDescriptions"]) == 1
        assert tree["actionDescriptions"][0]["name"] == "play"

    def test_persist_standard_actions(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play",
            action="play", params={"vol": 80},
        )
        vdsd.add_standard_action(std)
        tree = vdsd.get_property_tree()
        assert "standardActions" in tree
        assert tree["standardActions"][0]["name"] == "std.play"

    def test_persist_custom_actions(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.loud",
            action="play", title="Loud",
        )
        vdsd.add_custom_action(cust)
        tree = vdsd.get_property_tree()
        assert "customActions" in tree
        assert tree["customActions"][0]["title"] == "Loud"

    def test_dynamic_actions_not_persisted(self):
        _, _, _, vdsd = _make_stack()
        dyn = DynamicAction(
            vdsd=vdsd, ds_index=0, name="dynamic.x", title="X",
        )
        vdsd.add_dynamic_action(dyn)
        tree = vdsd.get_property_tree()
        # Dynamic actions are transient — not in property tree.
        assert "dynamicActions" not in tree

    def test_restore_action_descriptions(self):
        _, _, _, vdsd = _make_stack()
        p = ActionParameter(name="vol", type="numeric", default=50.0)
        desc = DeviceActionDescription(
            vdsd=vdsd, ds_index=0, name="play",
            params=[p], description="Play",
        )
        vdsd.add_device_action_description(desc)
        tree = vdsd.get_property_tree()

        # Create a fresh vdsd and restore.
        _, _, _, vdsd2 = _make_stack()
        vdsd2._apply_state(tree)
        assert len(vdsd2.action_descriptions) == 1
        restored = vdsd2.get_device_action_description(0)
        assert restored is not None
        assert restored.name == "play"
        assert restored.description == "Play"
        assert len(restored.params) == 1
        assert restored.params[0].name == "vol"

    def test_restore_standard_actions(self):
        _, _, _, vdsd = _make_stack()
        std = StandardAction(
            vdsd=vdsd, ds_index=0, name="std.play",
            action="play", params={"vol": 80},
        )
        vdsd.add_standard_action(std)
        tree = vdsd.get_property_tree()

        _, _, _, vdsd2 = _make_stack()
        vdsd2._apply_state(tree)
        restored = vdsd2.get_standard_action(0)
        assert restored is not None
        assert restored.name == "std.play"
        assert restored.action == "play"
        assert restored.params == {"vol": 80}

    def test_restore_custom_actions(self):
        _, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.loud",
            action="play", title="Loud",
            params={"vol": 100},
        )
        vdsd.add_custom_action(cust)
        tree = vdsd.get_property_tree()

        _, _, _, vdsd2 = _make_stack()
        vdsd2._apply_state(tree)
        restored = vdsd2.get_custom_action(0)
        assert restored is not None
        assert restored.name == "custom.loud"
        assert restored.action == "play"
        assert restored.title == "Loud"
        assert restored.params == {"vol": 100}


# ===========================================================================
# invokeDeviceAction callback
# ===========================================================================


class TestInvokeAction:
    """Tests for the invoke_action callback mechanism."""

    def test_on_invoke_action_property(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.on_invoke_action is None

        async def handler(v, action_id, params):
            pass

        vdsd.on_invoke_action = handler
        assert vdsd.on_invoke_action is handler
        vdsd.on_invoke_action = None
        assert vdsd.on_invoke_action is None

    @pytest.mark.asyncio
    async def test_invoke_action_calls_callback(self):
        _, _, _, vdsd = _make_stack()
        received = []

        async def handler(v, action_id, params):
            received.append((action_id, params))

        vdsd.on_invoke_action = handler
        await vdsd.invoke_action("std.play", {"volume": 80})
        assert len(received) == 1
        assert received[0] == ("std.play", {"volume": 80})

    @pytest.mark.asyncio
    async def test_invoke_action_no_callback_no_error(self):
        _, _, _, vdsd = _make_stack()
        # Should not raise even without a callback.
        await vdsd.invoke_action("std.play", {"volume": 80})

    @pytest.mark.asyncio
    async def test_invoke_action_default_params(self):
        _, _, _, vdsd = _make_stack()
        received = []

        async def handler(v, action_id, params):
            received.append((action_id, params))

        vdsd.on_invoke_action = handler
        await vdsd.invoke_action("std.stop")
        assert received[0] == ("std.stop", {})

    @pytest.mark.asyncio
    async def test_invoke_action_sync_callback(self):
        """Sync callbacks should also work."""
        _, _, _, vdsd = _make_stack()
        received = []

        def handler(v, action_id, params):
            received.append((action_id, params))

        vdsd.on_invoke_action = handler
        await vdsd.invoke_action("std.play", {"volume": 50})
        assert len(received) == 1


# ===========================================================================
# VdcHost generic request handling
# ===========================================================================


class TestVdcHostGenericRequest:
    """Tests for VdcHost._handle_generic_request."""

    def _make_invoke_msg(
        self,
        dsuid: str,
        action_id: str,
        params: Optional[dict] = None,
    ) -> pb.Message:
        """Build a VDSM_REQUEST_GENERIC_REQUEST for invokeDeviceAction."""
        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
        msg.message_id = 99
        msg.vdsm_request_generic_request.dSUID = dsuid
        msg.vdsm_request_generic_request.methodname = "invokeDeviceAction"

        # Add 'id' param.
        id_elem = PropertyElement()
        id_elem.name = "id"
        id_elem.value.v_string = action_id
        msg.vdsm_request_generic_request.params.append(id_elem)

        # Add any extra params.
        if params:
            for k, v in params.items():
                pe = PropertyElement()
                pe.name = k
                if isinstance(v, str):
                    pe.value.v_string = v
                elif isinstance(v, float):
                    pe.value.v_double = v
                elif isinstance(v, int):
                    pe.value.v_int64 = v
                elif isinstance(v, bool):
                    pe.value.v_bool = v
                msg.vdsm_request_generic_request.params.append(pe)

        return msg

    @pytest.mark.asyncio
    async def test_invoke_action_dispatches_to_vdsd(self):
        host, vdc, device, vdsd = _make_stack()
        received = []

        async def handler(v, action_id, params):
            received.append((action_id, params))

        vdsd.on_invoke_action = handler

        session = _make_mock_session()
        msg = self._make_invoke_msg(
            str(vdsd.dsuid), "std.play", {"volume": 80},
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert len(received) == 1
        assert received[0][0] == "std.play"
        assert received[0][1] == {"volume": 80}

    @pytest.mark.asyncio
    async def test_invoke_action_not_found(self):
        host, _, _, _ = _make_stack()
        session = _make_mock_session()
        msg = self._make_invoke_msg(
            "0000000000000000000000000000000099",
            "std.play",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_FOUND

    @pytest.mark.asyncio
    async def test_invoke_action_callback_error(self):
        host, _, _, vdsd = _make_stack()

        async def handler(v, action_id, params):
            raise RuntimeError("Action failed")

        vdsd.on_invoke_action = handler
        session = _make_mock_session()
        msg = self._make_invoke_msg(str(vdsd.dsuid), "std.play")
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_unknown_method_delegates_to_callback(self):
        """Unknown generic request methods should reach the on_message callback."""
        host, _, _, _ = _make_stack()
        received = []

        async def on_msg(session, msg):
            received.append(msg.type)
            resp = pb.Message()
            resp.type = pb.GENERIC_RESPONSE
            resp.message_id = msg.message_id
            resp.generic_response.code = pb.ERR_OK
            return resp

        host._on_message = on_msg
        session = _make_mock_session()

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
        msg.message_id = 55
        msg.vdsm_request_generic_request.dSUID = str(host.dsuid)
        msg.vdsm_request_generic_request.methodname = "someUnknownMethod"

        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert pb.VDSM_REQUEST_GENERIC_REQUEST in received

    @pytest.mark.asyncio
    async def test_unknown_method_no_callback(self):
        """Without on_message, unknown methods should return ERR_NOT_IMPLEMENTED."""
        host, _, _, _ = _make_stack()
        session = _make_mock_session()

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
        msg.message_id = 55
        msg.vdsm_request_generic_request.dSUID = str(host.dsuid)
        msg.vdsm_request_generic_request.methodname = "unknownMethod"

        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED


# ===========================================================================
# §7.4 configuration GenericRequest methods  (pair, authenticate, …)
# ===========================================================================


def _make_config_gr_msg(
    dsuid: str, method: str, **params: Any
) -> pb.Message:
    """Build a ``VDSM_REQUEST_GENERIC_REQUEST`` with simple scalar params."""
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
    msg.message_id = 200
    msg.vdsm_request_generic_request.dSUID = dsuid
    msg.vdsm_request_generic_request.methodname = method

    for key, val in params.items():
        elem = msg.vdsm_request_generic_request.params.add()
        elem.name = key
        if isinstance(val, bool):
            elem.value.v_bool = val
        elif isinstance(val, int):
            elem.value.v_int64 = val
        elif isinstance(val, float):
            elem.value.v_double = val
        elif isinstance(val, str):
            elem.value.v_string = val
    return msg


class TestGenericRequestPair:
    """Tests for the ``pair`` GenericRequest handler (§7.4.1)."""

    @pytest.mark.asyncio
    async def test_pair_callback_called(self):
        host, _, _, _ = _make_stack()
        received = []

        async def on_pair(dsuid, establish, timeout, params):
            received.append((dsuid, establish, timeout, params))

        host._on_pair = on_pair
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "pair",
            establish=True, timeout=30,
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert len(received) == 1
        assert received[0][0] == str(host.dsuid)
        assert received[0][1] is True
        assert received[0][2] == 30

    @pytest.mark.asyncio
    async def test_pair_no_callback(self):
        host, _, _, _ = _make_stack()
        session = _make_mock_session()

        msg = _make_config_gr_msg(str(host.dsuid), "pair", establish=False)
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_pair_callback_error(self):
        host, _, _, _ = _make_stack()

        async def on_pair(dsuid, establish, timeout, params):
            raise RuntimeError("pair failed")

        host._on_pair = on_pair
        session = _make_mock_session()

        msg = _make_config_gr_msg(str(host.dsuid), "pair", establish=True)
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED
        assert "pair failed" in resp.generic_response.description


class TestGenericRequestAuthenticate:
    """Tests for the ``authenticate`` GenericRequest handler (§7.4.2)."""

    @pytest.mark.asyncio
    async def test_authenticate_callback_called(self):
        host, _, _, _ = _make_stack()
        received = []

        async def on_auth(dsuid, auth_data, auth_scope, params):
            received.append((dsuid, auth_data, auth_scope, params))

        host._on_authenticate = on_auth
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "authenticate",
            authData='{"token":"abc"}', authScope="user1",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert len(received) == 1
        assert received[0][1] == '{"token":"abc"}'
        assert received[0][2] == "user1"

    @pytest.mark.asyncio
    async def test_authenticate_no_callback(self):
        host, _, _, _ = _make_stack()
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "authenticate", authData="x",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED


class TestGenericRequestFirmwareUpgrade:
    """Tests for the ``firmwareUpgrade`` GenericRequest handler (§7.4.3)."""

    @pytest.mark.asyncio
    async def test_firmware_upgrade_callback_called(self):
        host, _, _, _ = _make_stack()
        received = []

        async def on_fw(dsuid, check_only, clear_settings, params):
            received.append((dsuid, check_only, clear_settings, params))

        host._on_firmware_upgrade = on_fw
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "firmwareUpgrade",
            checkonly=True, clearsettings=False,
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert len(received) == 1
        assert received[0][1] is True   # check_only
        assert received[0][2] is False  # clear_settings

    @pytest.mark.asyncio
    async def test_firmware_upgrade_no_callback(self):
        host, _, _, _ = _make_stack()
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "firmwareUpgrade", checkonly=False,
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_firmware_upgrade_callback_error(self):
        host, _, _, _ = _make_stack()

        async def on_fw(dsuid, check_only, clear_settings, params):
            raise RuntimeError("upgrade failed")

        host._on_firmware_upgrade = on_fw
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "firmwareUpgrade", checkonly=False,
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED
        assert "upgrade failed" in resp.generic_response.description


class TestGenericRequestSetConfiguration:
    """Tests for the ``setConfiguration`` GenericRequest handler (§7.4.4)."""

    @pytest.mark.asyncio
    async def test_set_configuration_callback_called(self):
        host, _, _, _ = _make_stack()
        received = []

        async def on_cfg(dsuid, config_id, params):
            received.append((dsuid, config_id, params))

        host._on_set_configuration = on_cfg
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "setConfiguration", id="profile_2",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_OK
        assert len(received) == 1
        assert received[0][1] == "profile_2"
        assert received[0][2] == {}  # 'id' stripped from params

    @pytest.mark.asyncio
    async def test_set_configuration_no_callback(self):
        host, _, _, _ = _make_stack()
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "setConfiguration", id="x",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_set_configuration_callback_error(self):
        host, _, _, _ = _make_stack()

        async def on_cfg(dsuid, config_id, params):
            raise ValueError("bad config")

        host._on_set_configuration = on_cfg
        session = _make_mock_session()

        msg = _make_config_gr_msg(
            str(host.dsuid), "setConfiguration", id="x",
        )
        resp = await host._handle_generic_request(session, msg)
        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED
        assert "bad config" in resp.generic_response.description


# ===========================================================================
# setProperty for customActions
# ===========================================================================


class TestSetPropertyCustomActions:
    """Tests for setProperty writes to customActions."""

    def test_apply_custom_action_settings(self):
        host, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="Old",
        )
        vdsd.add_custom_action(cust)

        incoming = {
            "customActions": {
                "0": {"title": "New Title", "params": {"vol": 99}},
            }
        }
        host._apply_vdsd_set_property(vdsd, incoming)
        assert cust.title == "New Title"
        assert cust.params == {"vol": 99}

    def test_apply_custom_action_nonexistent_index_ignored(self):
        host, _, _, vdsd = _make_stack()
        cust = CustomAction(
            vdsd=vdsd, ds_index=0, name="custom.a",
            action="play", title="Title",
        )
        vdsd.add_custom_action(cust)

        incoming = {
            "customActions": {
                "5": {"title": "Should be ignored"},
            }
        }
        # Should not raise.
        host._apply_vdsd_set_property(vdsd, incoming)
        assert cust.title == "Title"  # unchanged
