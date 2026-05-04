"""Tests for device state handling (§4.6.1 / §4.6.2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.device_state import DeviceState
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
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
        "implementation_id": "x-test-state",
        "name": "Test State vDC",
        "model": "Test State v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("state-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: DsUid | None = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.YELLOW,
        "name": "State Test vdSD",
        "model": "Test State vdSD",
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
# DeviceState construction and properties
# ===========================================================================


class TestDeviceStateConstruction:
    """Tests for DeviceState creation and property access."""

    def test_default_construction(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="operatingState",
            options={0: "Off", 1: "Running"},
        )

        assert st.vdsd is vdsd
        assert st.ds_index == 0
        assert st.name == "operatingState"
        assert st.options == {0: "Off", 1: "Running"}
        assert st.description is None
        assert st.value is None

    def test_full_construction(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=2,
            name="errorState",
            options={0: "OK", 1: "Warning", 2: "Error"},
            description="Current error state",
        )

        assert st.ds_index == 2
        assert st.name == "errorState"
        assert st.options == {0: "OK", 1: "Warning", 2: "Error"}
        assert st.description == "Current error state"

    def test_empty_options(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        assert st.options == {}

    def test_setters(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")

        st.name = "newName"
        assert st.name == "newName"

        st.options = {10: "A", 20: "B"}
        assert st.options == {10: "A", 20: "B"}

        st.description = "Updated description"
        assert st.description == "Updated description"

        st.value = 10
        assert st.value == 10

    def test_repr(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        r = repr(st)
        assert "DeviceState" in r
        assert "test" in r

    def test_repr_with_value(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        st.value = 1
        r = repr(st)
        assert "value=1" in r

    def test_options_copy_safety(self):
        """options property returns a copy, not the internal dict."""
        _, _, _, vdsd = _make_stack()
        opts = {0: "Off", 1: "On"}
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test", options=opts)

        # Mutating the returned copy must not affect internal state.
        returned = st.options
        returned[99] = "Extra"
        assert 99 not in st.options

        # Mutating the original must not affect internal state.
        opts[99] = "Extra2"
        assert 99 not in st.options


# ===========================================================================
# Description properties
# ===========================================================================


class TestDeviceStateDescriptionProperties:
    """Tests for get_description_properties()."""

    def test_minimal(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="test",
            options={0: "Off", 1: "On"},
        )
        desc = st.get_description_properties()
        assert desc["name"] == "test"
        assert desc["value"] == {"values": {"Off": NO_VALUE, "On": NO_VALUE}}
        assert "description" not in desc

    def test_with_description(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="test",
            options={0: "Off"},
            description="A test state",
        )
        desc = st.get_description_properties()
        assert desc["description"] == "A test state"

    def test_empty_options_included(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        desc = st.get_description_properties()
        assert desc["name"] == "test"
        assert desc["value"] == {"values": {}}


# ===========================================================================
# State properties
# ===========================================================================


class TestDeviceStateProperties:
    """Tests for get_state_properties()."""

    def test_no_value(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")

        props = st.get_state_properties()
        assert props["name"] == "test"
        assert props["value"] is None

    def test_with_value(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        st.value = 1

        props = st.get_state_properties()
        assert props["name"] == "test"
        # No options → fallback to str(value)
        assert props["value"] == "1"

    def test_value_returns_label(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Running", 2: "Error"},
        )
        st.value = 1

        props = st.get_state_properties()
        assert props["value"] == "Running"

    def test_value_returns_label_for_all_options(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Running", 2: "Error"},
        )
        for key, expected in {0: "Off", 1: "Running", 2: "Error"}.items():
            st.value = key
            props = st.get_state_properties()
            assert props["value"] == expected


# ===========================================================================
# Persistence
# ===========================================================================


class TestDeviceStatePersistence:
    """Tests for property tree and state restoration."""

    def test_get_property_tree_minimal(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        tree = st.get_property_tree()
        assert tree["dsIndex"] == 0
        assert tree["name"] == "test"
        # No options key when empty (only stored when non-empty)
        # Actually we do store it:
        assert "options" not in tree or tree.get("options") == {}

    def test_get_property_tree_full(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=1,
            name="opState",
            options={0: "Off", 1: "Init", 2: "Running"},
            description="Operating state",
        )
        tree = st.get_property_tree()
        assert tree["dsIndex"] == 1
        assert tree["name"] == "opState"
        assert tree["options"] == {"0": "Off", "1": "Init", "2": "Running"}
        assert tree["description"] == "Operating state"

    def test_value_not_persisted(self):
        """State values are volatile — not in the property tree."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        st.value = 1
        tree = st.get_property_tree()
        assert "value" not in tree

    def test_roundtrip(self):
        """Persist → restore preserves description props."""
        _, _, _, vdsd = _make_stack()
        orig = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Running"},
            description="My state",
        )
        orig.value = 1
        tree = orig.get_property_tree()

        restored = DeviceState(vdsd=vdsd, ds_index=0, name="")
        restored._apply_state(tree)

        assert restored.name == "opState"
        assert restored.options == {0: "Off", 1: "Running"}
        assert restored.description == "My state"
        assert restored.value is None  # value not persisted

    def test_apply_state_partial(self):
        """Only provided fields are updated."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="original",
            options={0: "A"},
        )
        st._apply_state({"name": "updated"})
        assert st.name == "updated"
        assert st.options == {0: "A"}  # unchanged


# ===========================================================================
# Vdsd integration — management methods
# ===========================================================================


class TestVdsdDeviceStateManagement:
    """Tests for add/remove/get device states on Vdsd."""

    def test_add_and_get(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="test",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st)

        assert vdsd.get_device_state(0) is st
        assert 0 in vdsd.device_states
        assert len(vdsd.device_states) == 1

    def test_add_replace(self):
        _, _, _, vdsd = _make_stack()
        st1 = DeviceState(vdsd=vdsd, ds_index=0, name="first")
        st2 = DeviceState(vdsd=vdsd, ds_index=0, name="second")

        vdsd.add_device_state(st1)
        vdsd.add_device_state(st2)
        assert vdsd.get_device_state(0) is st2

    def test_remove(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        vdsd.add_device_state(st)

        removed = vdsd.remove_device_state(0)
        assert removed is st
        assert vdsd.get_device_state(0) is None
        assert len(vdsd.device_states) == 0

    def test_remove_nonexistent(self):
        _, _, _, vdsd = _make_stack()
        assert vdsd.remove_device_state(99) is None

    def test_wrong_vdsd_raises(self):
        host = _make_host()
        vdc = _make_vdc(host)
        dev1 = _make_device(vdc, DsUid.from_name_in_space("d1", DsUidNamespace.VDC))
        dev2 = _make_device(vdc, DsUid.from_name_in_space("d2", DsUidNamespace.VDC))
        vdsd1 = _make_vdsd(dev1)
        vdsd2 = _make_vdsd(dev2)

        st = DeviceState(vdsd=vdsd1, ds_index=0, name="test")
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd2.add_device_state(st)

    def test_device_states_returns_copy(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        vdsd.add_device_state(st)

        copy = vdsd.device_states
        copy[99] = "junk"
        assert 99 not in vdsd.device_states

    def test_multiple_states(self):
        _, _, _, vdsd = _make_stack()
        st0 = DeviceState(
            vdsd=vdsd, ds_index=0, name="state0", options={0: "Off", 1: "On"}
        )
        st1 = DeviceState(
            vdsd=vdsd, ds_index=1, name="state1", options={0: "Low", 1: "High"}
        )
        vdsd.add_device_state(st0)
        vdsd.add_device_state(st1)

        assert len(vdsd.device_states) == 2
        assert vdsd.get_device_state(0) is st0
        assert vdsd.get_device_state(1) is st1


# ===========================================================================
# Vdsd integration — get_properties
# ===========================================================================


class TestVdsdDeviceStateProperties:
    """Tests for deviceStateDescriptions / deviceStates in get_properties."""

    def test_no_states_no_keys(self):
        _, _, _, vdsd = _make_stack()
        props = vdsd.get_properties()
        assert "deviceStateDescriptions" not in props
        assert "deviceStates" not in props

    def test_with_states(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
            description="Operating state",
        )
        vdsd.add_device_state(st)

        props = vdsd.get_properties()
        assert "deviceStateDescriptions" in props
        assert "deviceStates" in props

        desc = props["deviceStateDescriptions"]
        assert "opState" in desc
        assert desc["opState"]["name"] == "opState"
        assert desc["opState"]["description"] == "Operating state"
        assert desc["opState"]["value"] == {"values": {"Off": NO_VALUE, "On": NO_VALUE}}

        states = props["deviceStates"]
        assert "opState" in states
        assert states["opState"]["name"] == "opState"
        assert states["opState"]["value"] is None  # no value set yet

    def test_with_value_set(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        st.value = 1
        vdsd.add_device_state(st)

        props = vdsd.get_properties()
        # Value is now the string label, not the integer key.
        assert props["deviceStates"]["opState"]["value"] == "On"


# ===========================================================================
# Vdsd integration — persistence
# ===========================================================================


class TestVdsdDeviceStatePersistence:
    """Tests for device state persistence roundtrip via Vdsd."""

    def test_property_tree_includes_states(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Running"},
            description="test",
        )
        vdsd.add_device_state(st)

        tree = vdsd.get_property_tree()
        assert "deviceStates" in tree
        assert len(tree["deviceStates"]) == 1
        assert tree["deviceStates"][0]["name"] == "opState"

    def test_apply_state_restores_states(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Running"},
        )
        vdsd.add_device_state(st)
        tree = vdsd.get_property_tree()

        # Create fresh vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        dev2.add_vdsd(vdsd2)
        vdc2.add_device(dev2)

        vdsd2._apply_state(tree)
        assert len(vdsd2.device_states) == 1
        restored = vdsd2.get_device_state(0)
        assert restored is not None
        assert restored.name == "opState"
        assert restored.options == {0: "Off", 1: "Running"}

    def test_full_roundtrip(self):
        """get_property_tree → new vdsd._apply_state roundtrip."""
        _, _, _, vdsd1 = _make_stack()
        st0 = DeviceState(
            vdsd=vdsd1,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Init", 2: "Running"},
            description="Operating state",
        )
        st1 = DeviceState(
            vdsd=vdsd1,
            ds_index=1,
            name="errorState",
            options={0: "OK", 1: "Error"},
        )
        vdsd1.add_device_state(st0)
        vdsd1.add_device_state(st1)

        tree = vdsd1.get_property_tree()

        # Create a new vdsd and restore.
        host2 = _make_host()
        vdc2 = _make_vdc(host2)
        dev2 = _make_device(vdc2)
        vdsd2 = _make_vdsd(dev2)
        vdsd2._apply_state(tree)

        assert len(vdsd2.device_states) == 2
        assert vdsd2.get_device_state(0).name == "opState"
        assert vdsd2.get_device_state(0).options == {0: "Off", 1: "Init", 2: "Running"}
        assert vdsd2.get_device_state(0).description == "Operating state"
        assert vdsd2.get_device_state(1).name == "errorState"
        assert vdsd2.get_device_state(1).options == {0: "OK", 1: "Error"}


# ===========================================================================
# Push notification — update_value
# ===========================================================================


class TestDeviceStateUpdateValue:
    """Tests for update_value() push notification."""

    @pytest.mark.asyncio
    async def test_update_value_pushes(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        vdsd.add_device_state(st)

        session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = session

        await st.update_value(1)

        assert st.value == 1
        assert session.send_notification.call_count == 1

        # Verify the message structure.
        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert msg.vdc_send_push_notification.dSUID == str(vdsd.dsuid)

        # Decode the pushed properties.
        pushed = elements_to_dict(msg.vdc_send_push_notification.changedproperties)
        assert "deviceStates" in pushed
        assert "0" in pushed["deviceStates"]
        assert pushed["deviceStates"]["0"]["name"] == "opState"
        # Value is the string label, not the integer key.
        assert pushed["deviceStates"]["0"]["value"] == "On"

    @pytest.mark.asyncio
    async def test_update_value_int_stored_as_int(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await st.update_value(2)
        assert st.value == 2
        assert isinstance(st.value, int)

    @pytest.mark.asyncio
    async def test_update_value_string_parsed_to_int(self):
        """A string that looks like an int is parsed to int."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await st.update_value("3")
        assert st.value == 3
        assert isinstance(st.value, int)

    @pytest.mark.asyncio
    async def test_update_value_text_label_resolved(self):
        """A text label is resolved to the integer option key."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Init", 2: "Running"},
        )
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await st.update_value("Running")
        assert st.value == 2

    @pytest.mark.asyncio
    async def test_update_value_unknown_label_raises(self):
        """An unknown text label raises ValueError."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "On"},
        )
        with pytest.raises(ValueError, match="unknown option label"):
            await st.update_value("Bogus")

    @pytest.mark.asyncio
    async def test_update_value_no_session(self):
        """Value is recorded but no push when no session."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")

        await st.update_value(1)
        assert st.value == 1

    @pytest.mark.asyncio
    async def test_update_value_not_announced(self):
        """Value is recorded but no push when not announced."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        vdsd._session = _make_mock_session()
        vdsd._announced = False

        await st.update_value(1)
        assert st.value == 1
        assert vdsd._session.send_notification.call_count == 0

    @pytest.mark.asyncio
    async def test_update_value_connection_error(self):
        """Push failure is logged, not raised."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        session = _make_mock_session()
        session.send_notification = AsyncMock(side_effect=ConnectionError("lost"))
        vdsd._announced = True
        vdsd._session = session

        await st.update_value(1)  # should not raise
        assert st.value == 1

    @pytest.mark.asyncio
    async def test_update_value_explicit_session(self):
        """Explicit session overrides the vdSD's session."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")

        internal_session = _make_mock_session()
        explicit_session = _make_mock_session()
        vdsd._announced = True
        vdsd._session = internal_session

        await st.update_value(1, session=explicit_session)
        assert explicit_session.send_notification.call_count == 1
        assert internal_session.send_notification.call_count == 0


# ===========================================================================
# Vdsd convenience — update_device_state
# ===========================================================================


class TestVdsdUpdateDeviceState:
    """Tests for vdsd.update_device_state() convenience method."""

    @pytest.mark.asyncio
    async def test_update_device_state(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd, ds_index=0, name="test", options={0: "Off", 1: "On"}
        )
        vdsd.add_device_state(st)
        vdsd._announced = True
        vdsd._session = _make_mock_session()

        await vdsd.update_device_state(0, 1)
        assert st.value == 1

    @pytest.mark.asyncio
    async def test_update_device_state_not_found(self):
        _, _, _, vdsd = _make_stack()
        with pytest.raises(KeyError, match="No DeviceState"):
            await vdsd.update_device_state(99, 1)

    @pytest.mark.asyncio
    async def test_value_setter_text_label(self):
        """Setting value via property with a text label resolves to int."""
        _, _, _, vdsd = _make_stack()
        st = DeviceState(
            vdsd=vdsd,
            ds_index=0,
            name="opState",
            options={0: "Off", 1: "Init", 2: "Running"},
        )
        st.value = "Running"
        assert st.value == 2

        st.value = "Off"
        assert st.value == 0

    def test_value_setter_none_clears(self):
        _, _, _, vdsd = _make_stack()
        st = DeviceState(vdsd=vdsd, ds_index=0, name="test")
        st.value = 5
        assert st.value == 5
        st.value = None
        assert st.value is None
