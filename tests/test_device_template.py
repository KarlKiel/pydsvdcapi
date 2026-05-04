"""Tests for the device template system.

Covers:
* DeviceTemplate construction, configure(), is_ready(), instantiate()
* TemplateNotConfiguredError / AnnouncementNotReadyError
* Device.get_template_tree() — instance field stripping
* Vdc.save_template() / Vdc.load_template() — round-trip
* Device.announce() callback guard for template-created devices
* build_required_fields() / build_required_callbacks() helpers
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from pydsvdcapi.binary_input import BinaryInput
from pydsvdcapi.device_template import (
    AnnouncementNotReadyError,
    DeviceTemplate,
    TemplateNotConfiguredError,
    build_required_callbacks,
    build_required_fields,
    strip_instance_fields,
)
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
from pydsvdcapi.output import Output
from pydsvdcapi.sensor_input import SensorInput
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import VdcHost
from pydsvdcapi.vdsd import Device, Vdsd


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_host(**kwargs: Any) -> VdcHost:
    kw: Dict[str, Any] = {"name": "Test Host", "mac": "AA:BB:CC:DD:EE:FF"}
    kw.update(kwargs)
    host = VdcHost(**kw)
    host._cancel_auto_save()
    return host


def _make_vdc(host: VdcHost, **kwargs: Any) -> Vdc:
    defaults: Dict[str, Any] = {
        "host": host,
        "implementation_id": "x-test",
        "name": "Test vDC",
        "model": "Test v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("tmpl-test-device", DsUidNamespace.VDC)


def _make_simple_device(vdc: Vdc, name: str = "Test Light") -> Device:
    """Create a Device with a single plain vdSD (no output, no actions)."""
    device = Device(vdc=vdc, dsuid=_base_dsuid())
    vdsd = Vdsd(
        device=device,
        primary_group=ColorGroup.YELLOW,
        name=name,
        model="Test Model",
        zone_id=0,
    )
    device.add_vdsd(vdsd)
    return device


def _make_output_device(vdc: Vdc, name: str = "Dimmer") -> Device:
    """Create a Device with a single vdSD that has an output channel."""
    device = Device(vdc=vdc, dsuid=_base_dsuid())
    vdsd = Vdsd(
        device=device,
        primary_group=ColorGroup.YELLOW,
        name=name,
        model="Dimmer Model",
    )
    output = Output(
        vdsd=vdsd,
        name="output",
        default_group=1,
        active_group=1,
        groups={1},
    )
    output.add_channel(1)  # channel_type 1 = brightness
    vdsd.set_output(output)
    device.add_vdsd(vdsd)
    return device


def _make_session() -> VdcSession:
    """Minimal mock VdcSession."""
    session = MagicMock(spec=VdcSession)
    session.send_request = AsyncMock(return_value=MagicMock(result_code=0))
    return session


# ---------------------------------------------------------------------------
# strip_instance_fields
# ---------------------------------------------------------------------------


class TestStripInstanceFields:
    def test_removes_device_level_base_dsuid(self):
        tree = {
            "baseDsUID": "AABBCC",
            "vdsds": [],
        }
        result = strip_instance_fields(tree)
        assert "baseDsUID" not in result

    def test_removes_vdsd_instance_fields(self):
        tree = {
            "baseDsUID": "AABBCC",
            "vdsds": [
                {
                    "subdeviceIndex": 0,
                    "dSUID": "DDEEFF",
                    "name": "Kitchen Light",
                    "zoneID": 5,
                    "model": "Dimmer v1",
                }
            ],
        }
        result = strip_instance_fields(tree)
        vdsd = result["vdsds"][0]
        assert "dSUID" not in vdsd
        assert "name" not in vdsd
        assert "zoneID" not in vdsd
        # structural fields must be retained
        assert vdsd["subdeviceIndex"] == 0
        assert vdsd["model"] == "Dimmer v1"

    def test_does_not_mutate_original(self):
        tree = {
            "baseDsUID": "AABBCC",
            "vdsds": [{"dSUID": "DD", "name": "X", "zoneID": 1}],
        }
        strip_instance_fields(tree)
        # original must be unchanged
        assert tree["baseDsUID"] == "AABBCC"
        assert tree["vdsds"][0]["name"] == "X"


# ---------------------------------------------------------------------------
# build_required_fields
# ---------------------------------------------------------------------------


class TestBuildRequiredFields:
    def test_one_vdsd(self):
        fields = build_required_fields([{"subdeviceIndex": 0}])
        assert fields == {"vdsds[0].name": None}

    def test_two_vdsds(self):
        fields = build_required_fields([{}, {}])
        assert "vdsds[0].name" in fields
        assert "vdsds[1].name" in fields

    def test_empty(self):
        assert build_required_fields([]) == {}


# ---------------------------------------------------------------------------
# build_required_callbacks
# ---------------------------------------------------------------------------


class TestBuildRequiredCallbacks:
    def test_no_callbacks_for_plain_vdsd(self):
        tree = [{"subdeviceIndex": 0}]
        cbs = build_required_callbacks(tree)
        assert cbs == {}

    def test_output_requires_channel_applied(self):
        tree = [{"output": {"channels": []}}]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].output.on_channel_applied" in cbs

    def test_action_descriptions_require_invoke_action(self):
        tree = [{"actionDescriptions": [{"id": "std.play"}]}]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].on_invoke_action" in cbs

    def test_standard_actions_require_invoke_action(self):
        tree = [{"standardActions": [{"id": "std.play"}]}]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].on_invoke_action" in cbs

    def test_identification_feature_requires_on_identify(self):
        tree = [{"modelFeatures": ["identification", "blink"]}]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].on_identify" in cbs

    def test_control_values_require_on_control_value(self):
        tree = [{"controlValues": {"heatingLevel": {}}}]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].on_control_value" in cbs

    def test_multiple_vdsds(self):
        tree = [
            {"output": {"channels": []}},
            {"actionDescriptions": [{"id": "play"}]},
        ]
        cbs = build_required_callbacks(tree)
        assert "vdsds[0].output.on_channel_applied" in cbs
        assert "vdsds[1].on_invoke_action" in cbs
        assert "vdsds[0].on_invoke_action" not in cbs


# ---------------------------------------------------------------------------
# DeviceTemplate construction, configure, is_ready
# ---------------------------------------------------------------------------


class TestDeviceTemplate:
    def _make_template(self, **kwargs: Any) -> DeviceTemplate:
        defaults = {
            "template_type": "generic",
            "integration": "x-test",
            "name": "test-light",
            "tree": {"vdsds": [{"subdeviceIndex": 0, "model": "M"}]},
            "required_fields": {"vdsds[0].name": None},
            "required_callbacks": {},
        }
        defaults.update(kwargs)
        return DeviceTemplate(**defaults)

    def test_is_ready_false_when_name_is_none(self):
        tmpl = self._make_template()
        assert not tmpl.is_ready()

    def test_is_ready_true_after_configure(self):
        tmpl = self._make_template()
        tmpl.configure({"vdsds[0].name": "My Light"})
        assert tmpl.is_ready()

    def test_configure_returns_self_for_chaining(self):
        tmpl = self._make_template()
        result = tmpl.configure({"vdsds[0].name": "L"})
        assert result is tmpl

    def test_configure_rejects_unknown_key(self):
        tmpl = self._make_template()
        with pytest.raises(KeyError, match="unknown_key"):
            tmpl.configure({"unknown_key": "value"})

    def test_required_fields_copy(self):
        tmpl = self._make_template()
        copy = tmpl.required_fields
        copy["vdsds[0].name"] = "hacked"
        # internal state must be unaffected
        assert tmpl.required_fields["vdsds[0].name"] is None

    def test_description_and_created_at_are_stored(self):
        tmpl = self._make_template(
            description="A nice light", created_at="2024-01-01T00:00:00+00:00"
        )
        assert tmpl.description == "A nice light"
        assert tmpl.created_at == "2024-01-01T00:00:00+00:00"

    def test_created_at_defaults_to_iso_timestamp(self):
        tmpl = self._make_template()
        assert tmpl.created_at is not None
        # Should look like an ISO timestamp
        assert "T" in tmpl.created_at


# ---------------------------------------------------------------------------
# DeviceTemplate.instantiate()
# ---------------------------------------------------------------------------


class TestDeviceTemplateInstantiate:
    def test_raises_when_not_configured(self):
        host = _make_host()
        vdc = _make_vdc(host)
        tmpl = DeviceTemplate(
            template_type="generic",
            integration="x-test",
            name="t",
            tree={"vdsds": [{"subdeviceIndex": 0, "primaryGroup": 1}]},
            required_fields={"vdsds[0].name": None},
            required_callbacks={},
        )
        with pytest.raises(TemplateNotConfiguredError) as exc_info:
            tmpl.instantiate(vdc=vdc)
        assert "vdsds[0].name" in exc_info.value.missing_fields

    def test_returns_device_with_correct_structure(self):
        host = _make_host()
        vdc = _make_vdc(host)
        tmpl = DeviceTemplate(
            template_type="generic",
            integration="x-test",
            name="t",
            tree={
                "vdsds": [
                    {
                        "subdeviceIndex": 0,
                        "primaryGroup": int(ColorGroup.YELLOW),
                        "model": "Dimmer Model",
                    }
                ]
            },
            required_fields={"vdsds[0].name": None},
            required_callbacks={},
        )
        tmpl.configure({"vdsds[0].name": "My Dimmer"})
        dsuid = DsUid.from_name_in_space("dev-inst-1", DsUidNamespace.VDC)
        device = tmpl.instantiate(vdc=vdc, dsuid=dsuid)

        assert isinstance(device, Device)
        assert 0 in device.vdsds
        assert device.vdsds[0].name == "My Dimmer"
        assert device.vdsds[0].model == "Dimmer Model"

    def test_uses_random_dsuid_when_none_given(self):
        host = _make_host()
        vdc = _make_vdc(host)
        tmpl = DeviceTemplate(
            template_type="generic",
            integration="x-test",
            name="t",
            tree={"vdsds": [{"subdeviceIndex": 0, "primaryGroup": 1}]},
            required_fields={"vdsds[0].name": "Auto"},
            required_callbacks={},
        )
        device = tmpl.instantiate(vdc=vdc)
        assert device.dsuid is not None

    def test_required_callbacks_stored_on_device(self):
        host = _make_host()
        vdc = _make_vdc(host)
        tmpl = DeviceTemplate(
            template_type="generic",
            integration="x-test",
            name="t",
            tree={"vdsds": [{"subdeviceIndex": 0, "primaryGroup": 1}]},
            required_fields={"vdsds[0].name": "Lamp"},
            required_callbacks={"vdsds[0].on_identify": None},
        )
        device = tmpl.instantiate(vdc=vdc)
        assert device._required_callbacks == {"vdsds[0].on_identify": None}


# ---------------------------------------------------------------------------
# Device.get_template_tree()
# ---------------------------------------------------------------------------


class TestDeviceGetTemplateTree:
    def test_strips_base_dsuid(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        tree = device.get_template_tree()
        assert "baseDsUID" not in tree

    def test_strips_vdsd_dsuid_and_name_and_zone(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc, name="Kitchen Light")
        tree = device.get_template_tree()
        vdsd_tree = tree["vdsds"][0]
        assert "dSUID" not in vdsd_tree
        assert "name" not in vdsd_tree
        assert "zoneID" not in vdsd_tree

    def test_retains_structural_fields(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        vdsd = list(device.vdsds.values())[0]
        tree = device.get_template_tree()
        vdsd_tree = tree["vdsds"][0]
        assert vdsd_tree["subdeviceIndex"] == vdsd.subdevice_index
        assert vdsd_tree["model"] == vdsd.model

    def test_full_property_tree_still_has_instance_fields(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc, name="Light")
        full_tree = device.get_property_tree()
        # sanity: full tree has everything
        assert "baseDsUID" in full_tree
        assert "dSUID" in full_tree["vdsds"][0]
        assert "name" in full_tree["vdsds"][0]


# ---------------------------------------------------------------------------
# Device.announce() callback guard
# ---------------------------------------------------------------------------


class TestDeviceAnnounceCallbackGuard:
    def test_no_guard_for_non_template_device(self):
        """Device created directly (not via template) must announce freely."""
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        session = _make_session()
        # Should not raise — no _required_callbacks set
        asyncio.get_event_loop().run_until_complete(
            device.announce(session)
        )

    def test_raises_when_callbacks_missing(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        # Manually set required_callbacks (simulating template.instantiate)
        device._required_callbacks = {"vdsds[0].on_identify": None}
        session = _make_session()
        with pytest.raises(AnnouncementNotReadyError) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                device.announce(session)
            )
        assert "vdsds[0].on_identify" in exc_info.value.missing_callbacks

    def test_no_raise_when_callback_is_set(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        device._required_callbacks = {"vdsds[0].on_identify": None}
        vdsd = list(device.vdsds.values())[0]
        vdsd.on_identify = lambda v: None
        session = _make_session()
        # Should not raise
        asyncio.get_event_loop().run_until_complete(
            device.announce(session)
        )

    def test_raises_when_output_callback_missing(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_output_device(vdc)
        device._required_callbacks = {
            "vdsds[0].output.on_channel_applied": None
        }
        session = _make_session()
        with pytest.raises(AnnouncementNotReadyError) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                device.announce(session)
            )
        assert (
            "vdsds[0].output.on_channel_applied"
            in exc_info.value.missing_callbacks
        )

    def test_no_raise_when_output_callback_set(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_output_device(vdc)
        device._required_callbacks = {
            "vdsds[0].output.on_channel_applied": None
        }
        vdsd = list(device.vdsds.values())[0]
        vdsd._output.on_channel_applied = lambda o, u: None
        session = _make_session()
        asyncio.get_event_loop().run_until_complete(
            device.announce(session)
        )


# ---------------------------------------------------------------------------
# Vdc.save_template() / Vdc.load_template() round-trip
# ---------------------------------------------------------------------------


class TestVdcTemplatePersistence:
    def test_save_raises_without_template_path(self):
        host = _make_host()
        vdc = _make_vdc(host)
        device = _make_simple_device(vdc)
        with pytest.raises(RuntimeError, match="template_path"):
            vdc.save_template(
                device,
                template_type="generic",
                integration="x-test",
                name="light",
            )

    def test_load_raises_without_template_path(self):
        host = _make_host()
        vdc = _make_vdc(host)
        with pytest.raises(RuntimeError, match="template_path"):
            vdc.load_template("generic", "x-test", "light")

    def test_save_creates_yaml_file(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_simple_device(vdc)
        saved = vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="plain-light",
        )
        assert saved.exists()
        assert saved.suffix == ".yaml"
        assert saved.parent.name == "x-test"
        assert "generic_templates" in str(saved)

    def test_saved_yaml_is_valid(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_simple_device(vdc, name="Test")
        saved = vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="light",
            description="Round-trip test",
        )
        with saved.open() as fh:
            data = yaml.safe_load(fh)
        assert data["templateType"] == "generic"
        assert data["integration"] == "x-test"
        assert data["name"] == "light"
        assert data["description"] == "Round-trip test"
        assert "requiredFields" in data
        assert "requiredCallbacks" in data
        assert "tree" in data

    def test_round_trip_restores_template(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_simple_device(vdc, name="Original Name")
        vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="light",
        )

        tmpl = vdc.load_template("generic", "x-test", "light")
        assert isinstance(tmpl, DeviceTemplate)
        assert tmpl.template_type == "generic"
        assert tmpl.integration == "x-test"
        assert tmpl.name == "light"
        assert "vdsds[0].name" in tmpl.required_fields

    def test_instantiate_after_round_trip(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_simple_device(vdc, name="Original")
        vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="light",
        )

        tmpl = vdc.load_template("generic", "x-test", "light")
        tmpl.configure({"vdsds[0].name": "New Instance"})
        new_device = tmpl.instantiate(vdc=vdc)
        assert new_device.vdsds[0].name == "New Instance"

    def test_model_template_goes_in_model_templates_folder(
        self, tmp_path: Path
    ):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_simple_device(vdc)
        saved = vdc.save_template(
            device,
            template_type="model",
            integration="x-acme",
            name="bulb",
        )
        assert "model_templates" in str(saved)

    def test_load_raises_for_missing_file(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        with pytest.raises(FileNotFoundError):
            vdc.load_template("generic", "x-test", "nonexistent")

    def test_template_path_property(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        assert vdc.template_path == tmp_path

    def test_template_path_none_by_default(self):
        host = _make_host()
        vdc = _make_vdc(host)
        assert vdc.template_path is None

    def test_template_with_output_device(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_output_device(vdc, name="Dimmer")
        vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="dimmer",
        )
        tmpl = vdc.load_template("generic", "x-test", "dimmer")
        # Output devices should require on_channel_applied
        assert "vdsds[0].output.on_channel_applied" in tmpl.required_callbacks

    def test_required_callbacks_list_in_yaml(self, tmp_path: Path):
        host = _make_host()
        vdc = _make_vdc(host, template_path=tmp_path)
        device = _make_output_device(vdc)
        saved = vdc.save_template(
            device,
            template_type="generic",
            integration="x-test",
            name="dimmer",
        )
        with saved.open() as fh:
            data = yaml.safe_load(fh)
        assert isinstance(data["requiredCallbacks"], list)
        assert "vdsds[0].output.on_channel_applied" in data["requiredCallbacks"]


# ---------------------------------------------------------------------------
# DeviceTemplate.to_dict() / from_dict() serialisation
# ---------------------------------------------------------------------------


class TestDeviceTemplateSerialization:
    def test_to_dict_round_trip(self):
        tmpl = DeviceTemplate(
            template_type="model",
            integration="x-acme",
            name="bulb",
            tree={"vdsds": [{"subdeviceIndex": 0}]},
            required_fields={"vdsds[0].name": None},
            required_callbacks={"vdsds[0].on_identify": None},
            description="Test",
            created_at="2024-06-01T00:00:00+00:00",
        )
        d = tmpl.to_dict()
        restored = DeviceTemplate.from_dict(d)

        assert restored.template_type == "model"
        assert restored.integration == "x-acme"
        assert restored.name == "bulb"
        assert restored.description == "Test"
        assert restored.created_at == "2024-06-01T00:00:00+00:00"
        assert restored.required_fields == {"vdsds[0].name": None}
        assert "vdsds[0].on_identify" in restored.required_callbacks

    def test_required_callbacks_stored_as_list_not_dict(self):
        tmpl = DeviceTemplate(
            template_type="generic",
            integration="x-test",
            name="t",
            tree={},
            required_fields={},
            required_callbacks={"vdsds[0].on_invoke_action": None},
        )
        d = tmpl.to_dict()
        assert isinstance(d["requiredCallbacks"], list)
        assert "vdsds[0].on_invoke_action" in d["requiredCallbacks"]
