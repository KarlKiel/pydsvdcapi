"""Tests for the ButtonInput component and ClickDetector state machine."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.button_input import (
    BUTTON_TYPE_ELEMENTS,
    ButtonInput,
    ClickDetector,
    create_button_group,
    get_required_elements,
)
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import (
    ColorGroup,
    ActionMode,
    ButtonClickType,
    ButtonElementID,
    ButtonFunction,
    ButtonMode,
    ButtonType,
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
        "implementation_id": "x-test-btn",
        "name": "Test Btn vDC",
        "model": "Test Btn v1",
    }
    defaults.update(kwargs)
    return Vdc(**defaults)


def _base_dsuid() -> DsUid:
    return DsUid.from_name_in_space("btn-test-device", DsUidNamespace.VDC)


def _make_device(vdc: Vdc, dsuid: Optional[DsUid] = None) -> Device:
    return Device(vdc=vdc, dsuid=dsuid or _base_dsuid())


def _make_vdsd(device: Device, **kwargs: Any) -> Vdsd:
    defaults: dict[str, Any] = {
        "device": device,
        "primary_group": ColorGroup.BLACK,
        "name": "Btn Test vdSD",
        "model": "Test Btn vdSD",
    }
    defaults.update(kwargs)
    return Vdsd(**defaults)


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


def _make_mock_session() -> MagicMock:
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_notification = AsyncMock()
    return session


def _scaffold() -> Tuple[VdcHost, Vdc, Device, Vdsd]:
    """Create the full host → vdc → device → vdsd chain."""
    host = _make_host()
    vdc = _make_vdc(host)
    device = _make_device(vdc)
    vdsd = _make_vdsd(device)
    return host, vdc, device, vdsd


# ===========================================================================
# Construction and defaults
# ===========================================================================


class TestButtonInputConstruction:
    """Tests for ButtonInput creation and default values."""

    def test_default_construction(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)

        assert btn.ds_index == 0
        assert btn.name == "Test Button"
        assert btn.supports_local_key_mode is False
        assert btn.button_id == 0
        assert btn.button_type == ButtonType.SINGLE_PUSHBUTTON
        assert btn.button_element_id == ButtonElementID.CENTER
        assert btn.vdsd is vdsd

    def test_custom_construction(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=3,
            name="Rocker Up",
            supports_local_key_mode=True,
            button_id=1,
            button_type=ButtonType.TWO_WAY_PUSHBUTTON,
            button_element_id=ButtonElementID.UP,
            group=1,
            function=ButtonFunction.ROOM,
            mode=ButtonMode.STANDARD,
            channel=5,
            sets_local_priority=True,
            calls_present=True,
        )

        assert btn.ds_index == 3
        assert btn.name == "Rocker Up"
        assert btn.supports_local_key_mode is True
        assert btn.button_id == 1
        assert btn.button_type == ButtonType.TWO_WAY_PUSHBUTTON
        assert btn.button_element_id == ButtonElementID.UP
        assert btn.group == 1
        assert btn.function == ButtonFunction.ROOM
        assert btn.mode == ButtonMode.STANDARD
        assert btn.channel == 5
        assert btn.sets_local_priority is True
        assert btn.calls_present is True

    def test_no_button_id(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd, ds_index=0, button_id=None, name="No ID"
        )
        assert btn.button_id is None

    def test_click_detector_config(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="Custom Timing",
            click_detector_config={
                "tip_timeout": 0.5,
                "multi_click_window": 0.6,
                "hold_repeat_interval": 2.0,
                "use_tip_events": True,
                "unknown_key": "ignored",
            },
        )
        cd = btn.click_detector
        assert cd.tip_timeout == 0.5
        assert cd.multi_click_window == 0.6
        assert cd.hold_repeat_interval == 2.0
        assert cd.use_tip_events is True

    def test_repr(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd, name="MyBtn")
        r = repr(btn)
        assert "ButtonInput" in r
        assert "MyBtn" in r
        assert "SINGLE_PUSHBUTTON" in r
        assert "CENTER" in r


# ===========================================================================
# State defaults
# ===========================================================================


class TestButtonInputStateDefaults:
    """State properties start at unknown / IDLE / OK."""

    def test_value_none(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.value is None

    def test_click_type_idle(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.click_type == ButtonClickType.IDLE

    def test_action_id_none(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.action_id is None

    def test_action_mode_none(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.action_mode is None

    def test_age_none(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.age is None

    def test_error_ok(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        assert btn.error == InputError.OK


# ===========================================================================
# Settings accessors
# ===========================================================================


class TestButtonInputSettings:
    """Writable settings properties."""

    def test_group_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.group = 3
        assert btn.group == 3

    def test_function_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.function = ButtonFunction.ROOM
        assert btn.function == ButtonFunction.ROOM

    def test_function_from_int(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.function = 5  # type: ignore[assignment]
        assert btn.function == ButtonFunction.ROOM

    def test_mode_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.mode = ButtonMode.SWITCHED
        assert btn.mode == ButtonMode.SWITCHED

    def test_channel_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.channel = 42
        assert btn.channel == 42

    def test_sets_local_priority_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.sets_local_priority = True
        assert btn.sets_local_priority is True

    def test_calls_present_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.calls_present = True
        assert btn.calls_present is True

    def test_error_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.error = InputError.LOW_BATTERY
        assert btn.error == InputError.LOW_BATTERY

    def test_name_setter(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.name = "New Name"
        assert btn.name == "New Name"


# ===========================================================================
# Property dicts
# ===========================================================================


class TestButtonInputDescriptionProperties:
    """Description property dict for getProperty responses."""

    def test_description_keys(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd, button_id=2)
        desc = btn.get_description_properties()
        assert desc["name"] == "Test Button"
        assert desc["dsIndex"] == 0
        assert desc["supportsLocalKeyMode"] is False
        assert desc["buttonType"] == int(ButtonType.SINGLE_PUSHBUTTON)
        assert desc["buttonElementID"] == int(ButtonElementID.CENTER)
        assert desc["buttonID"] == 2

    def test_description_without_button_id(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd, ds_index=0, button_id=None, name="No ID"
        )
        desc = btn.get_description_properties()
        assert "buttonID" not in desc


class TestButtonInputSettingsProperties:
    """Settings property dict for getProperty responses."""

    def test_settings_keys(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="B",
            group=2,
            function=ButtonFunction.AREA_1,
            mode=ButtonMode.SWITCHED,
            channel=10,
            sets_local_priority=True,
            calls_present=True,
        )
        s = btn.get_settings_properties()
        assert s["group"] == 2
        assert s["function"] == int(ButtonFunction.AREA_1)
        assert s["mode"] == int(ButtonMode.SWITCHED)
        assert s["channel"] == 10
        assert s["setsLocalPriority"] is True
        assert s["callsPresent"] is True


class TestButtonInputStateProperties:
    """State property dict — click mode vs action mode."""

    def test_click_mode_default(self):
        """Default state is click mode with value=None, clickType=IDLE."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        st = btn.get_state_properties()
        assert "value" in st
        assert st["value"] is None
        assert st["clickType"] == int(ButtonClickType.IDLE)
        assert "actionId" not in st
        assert "actionMode" not in st
        assert st["age"] is None
        assert st["error"] == int(InputError.OK)

    @pytest.mark.asyncio
    async def test_click_mode_after_update_click(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_click(ButtonClickType.CLICK_1X, value=False)
        st = btn.get_state_properties()
        assert st["value"] is False
        assert st["clickType"] == int(ButtonClickType.CLICK_1X)
        assert "actionId" not in st

    @pytest.mark.asyncio
    async def test_action_mode_after_update_action(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_action(action_id=5, action_mode=ActionMode.FORCE)
        st = btn.get_state_properties()
        assert st["actionId"] == 5
        assert st["actionMode"] == int(ActionMode.FORCE)
        assert "value" not in st
        assert "clickType" not in st
        assert st["error"] == int(InputError.OK)

    @pytest.mark.asyncio
    async def test_mode_switch_action_then_click(self):
        """Switching from action to click mode returns click properties."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_action(action_id=10)
        assert "actionId" in btn.get_state_properties()
        await btn.update_click(ButtonClickType.HOLD_START, value=True)
        st = btn.get_state_properties()
        assert "value" in st
        assert "clickType" in st
        assert "actionId" not in st

    @pytest.mark.asyncio
    async def test_age_updates(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_click(ButtonClickType.CLICK_1X)
        age = btn.age
        assert age is not None
        assert age >= 0.0


# ===========================================================================
# Direct click update
# ===========================================================================


class TestButtonInputUpdateClick:
    """Tests for update_click (direct click type reporting)."""

    @pytest.mark.asyncio
    async def test_update_click_basic(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_click(ButtonClickType.CLICK_2X, value=False)
        assert btn.click_type == ButtonClickType.CLICK_2X
        assert btn.value is False

    @pytest.mark.asyncio
    async def test_update_click_from_int(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_click(7)  # CLICK_1X
        assert btn.click_type == ButtonClickType.CLICK_1X

    @pytest.mark.asyncio
    async def test_update_click_preserves_value(self):
        """When value=None, existing value is kept."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn._value = True
        await btn.update_click(ButtonClickType.HOLD_START)
        assert btn.value is True  # unchanged

    @pytest.mark.asyncio
    async def test_update_click_pushes(self):
        """update_click pushes state when vdSD is announced."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn._session = session
        await btn.update_click(ButtonClickType.CLICK_1X)
        session.send_notification.assert_awaited_once()


# ===========================================================================
# Direct action update
# ===========================================================================


class TestButtonInputUpdateAction:
    """Tests for update_action (direct scene call)."""

    @pytest.mark.asyncio
    async def test_update_action_basic(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_action(action_id=14, action_mode=ActionMode.UNDO)
        assert btn.action_id == 14
        assert btn.action_mode == ActionMode.UNDO

    @pytest.mark.asyncio
    async def test_update_action_default_mode(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_action(action_id=0)
        assert btn.action_mode == ActionMode.NORMAL

    @pytest.mark.asyncio
    async def test_update_action_from_int(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        await btn.update_action(action_id=5, action_mode=1)
        assert btn.action_mode == ActionMode.FORCE

    @pytest.mark.asyncio
    async def test_update_action_pushes(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn._session = session
        await btn.update_action(action_id=5)
        session.send_notification.assert_awaited_once()


# ===========================================================================
# Error update
# ===========================================================================


class TestButtonInputUpdateError:
    """Tests for update_error."""

    @pytest.mark.asyncio
    async def test_update_error(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn._session = session
        await btn.update_error(InputError.LOW_BATTERY)
        assert btn.error == InputError.LOW_BATTERY
        session.send_notification.assert_awaited_once()


# ===========================================================================
# Push notifications
# ===========================================================================


class TestButtonInputPushNotifications:
    """Push notification behaviour."""

    @pytest.mark.asyncio
    async def test_no_push_without_session(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd._announced = True
        # No session → no crash, no push.
        await btn.update_click(ButtonClickType.CLICK_1X)

    @pytest.mark.asyncio
    async def test_no_push_when_not_announced(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        btn._session = session
        vdsd._announced = False
        await btn.update_click(ButtonClickType.CLICK_1X)
        session.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_push_click_state_format(self):
        """Push carries buttonInputStates with click mode fields."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn._session = session

        await btn.update_click(ButtonClickType.CLICK_1X, value=False)

        msg = session.send_notification.call_args[0][0]
        assert msg.type == pb.VDC_SEND_PUSH_NOTIFICATION
        props = elements_to_dict(
            msg.vdc_send_push_notification.changedproperties
        )
        assert "buttonInputStates" in props
        state = props["buttonInputStates"]["0"]
        assert state["value"] is False
        assert state["clickType"] == int(ButtonClickType.CLICK_1X)
        assert "actionId" not in state

    @pytest.mark.asyncio
    async def test_push_action_state_format(self):
        """Push carries buttonInputStates with action mode fields."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn._session = session

        await btn.update_action(action_id=42, action_mode=ActionMode.FORCE)

        msg = session.send_notification.call_args[0][0]
        props = elements_to_dict(
            msg.vdc_send_push_notification.changedproperties
        )
        state = props["buttonInputStates"]["0"]
        assert state["actionId"] == 42
        assert state["actionMode"] == int(ActionMode.FORCE)
        assert "value" not in state

    @pytest.mark.asyncio
    async def test_push_with_explicit_session(self):
        """update_click with explicit session parameter works."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        # Not stored session — pass explicitly.
        await btn.update_click(
            ButtonClickType.HOLD_START, value=True, session=session
        )
        session.send_notification.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_push_handles_connection_error(self):
        """ConnectionError during push doesn't raise."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        session.send_notification = AsyncMock(
            side_effect=ConnectionError("gone")
        )
        vdsd._announced = True
        btn._session = session
        # Should not raise.
        await btn.update_click(ButtonClickType.CLICK_1X)


# ===========================================================================
# Settings mutation (apply_settings)
# ===========================================================================


class TestButtonInputApplySettings:
    """apply_settings from vdc_host setProperty."""

    def test_apply_all(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.apply_settings(
            {
                "group": 4,
                "function": int(ButtonFunction.AREA_2),
                "mode": int(ButtonMode.SWITCHED),
                "channel": 20,
                "setsLocalPriority": True,
                "callsPresent": True,
            }
        )
        assert btn.group == 4
        assert btn.function == ButtonFunction.AREA_2
        assert btn.mode == ButtonMode.SWITCHED
        assert btn.channel == 20
        assert btn.sets_local_priority is True
        assert btn.calls_present is True

    def test_apply_partial(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.apply_settings({"group": 7})
        assert btn.group == 7
        assert btn.function == ButtonFunction.DEVICE  # unchanged

    def test_apply_empty(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.apply_settings({})
        assert btn.group == 0


# ===========================================================================
# Persistence
# ===========================================================================


class TestButtonInputPersistence:
    """get_property_tree and _apply_state round-trip."""

    def test_property_tree_keys(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=1,
            name="Rocker Down",
            supports_local_key_mode=True,
            button_id=3,
            button_type=ButtonType.TWO_WAY_PUSHBUTTON,
            button_element_id=ButtonElementID.DOWN,
            group=2,
            function=ButtonFunction.ROOM,
            mode=ButtonMode.STANDARD,
            channel=5,
            sets_local_priority=True,
            calls_present=True,
        )
        tree = btn.get_property_tree()
        assert tree["dsIndex"] == 1
        assert tree["name"] == "Rocker Down"
        assert tree["supportsLocalKeyMode"] is True
        assert tree["buttonID"] == 3
        assert tree["buttonType"] == int(ButtonType.TWO_WAY_PUSHBUTTON)
        assert tree["buttonElementID"] == int(ButtonElementID.DOWN)
        assert tree["group"] == 2
        assert tree["function"] == int(ButtonFunction.ROOM)
        assert tree["mode"] == int(ButtonMode.STANDARD)
        assert tree["channel"] == 5
        assert tree["setsLocalPriority"] is True
        assert tree["callsPresent"] is True

    def test_property_tree_no_button_id(self):
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd, ds_index=0, button_id=None, name="X"
        )
        tree = btn.get_property_tree()
        assert "buttonID" not in tree

    def test_round_trip(self):
        """Persist → restore → compare."""
        _, _, _, vdsd = _scaffold()
        original = ButtonInput(
            vdsd=vdsd,
            ds_index=2,
            name="Original",
            supports_local_key_mode=True,
            button_id=5,
            button_type=ButtonType.FOUR_WAY_WITH_CENTER,
            button_element_id=ButtonElementID.LEFT,
            group=3,
            function=ButtonFunction.EXTENDED_1,
            mode=ButtonMode.TWO_WAY_DOWN_PAIRED_1,
            channel=100,
            sets_local_priority=True,
            calls_present=True,
        )
        tree = original.get_property_tree()

        restored = ButtonInput(vdsd=vdsd, ds_index=0, name="Blank")
        restored._apply_state(tree)

        assert restored.ds_index == 2
        assert restored.name == "Original"
        assert restored.supports_local_key_mode is True
        assert restored.button_id == 5
        assert restored.button_type == ButtonType.FOUR_WAY_WITH_CENTER
        assert restored.button_element_id == ButtonElementID.LEFT
        assert restored.group == 3
        assert restored.function == ButtonFunction.EXTENDED_1
        assert restored.mode == ButtonMode.TWO_WAY_DOWN_PAIRED_1
        assert restored.channel == 100
        assert restored.sets_local_priority is True
        assert restored.calls_present is True
        # State is NOT persisted.
        assert restored.value is None
        assert restored.click_type == ButtonClickType.IDLE

    def test_apply_state_partial(self):
        """_apply_state with partial dict keeps other defaults."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn._apply_state({"group": 8, "channel": 50})
        assert btn.group == 8
        assert btn.channel == 50
        assert btn.function == ButtonFunction.DEVICE  # unchanged


# ===========================================================================
# vdsd integration
# ===========================================================================


class TestVdsdButtonInputIntegration:
    """Integration of ButtonInput with Vdsd."""

    def test_add_button_input(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd, ds_index=0)
        vdsd.add_button_input(btn)
        assert len(vdsd.button_inputs) == 1
        assert vdsd.get_button_input(0) is btn

    def test_add_replaces_same_index(self):
        _, _, _, vdsd = _scaffold()
        btn1 = _make_button_input(vdsd, ds_index=0, name="First")
        btn2 = _make_button_input(vdsd, ds_index=0, name="Second")
        vdsd.add_button_input(btn1)
        vdsd.add_button_input(btn2)
        assert len(vdsd.button_inputs) == 1
        assert vdsd.get_button_input(0).name == "Second"

    def test_add_wrong_vdsd_raises(self):
        _, _, _, vdsd1 = _scaffold()
        _, _, _, vdsd2 = _scaffold()
        btn = _make_button_input(vdsd1)
        with pytest.raises(ValueError, match="different vdSD"):
            vdsd2.add_button_input(btn)

    def test_remove_button_input(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)
        removed = vdsd.remove_button_input(0)
        assert removed is btn
        assert vdsd.get_button_input(0) is None

    def test_remove_nonexistent(self):
        _, _, _, vdsd = _scaffold()
        assert vdsd.remove_button_input(99) is None

    def test_get_nonexistent(self):
        _, _, _, vdsd = _scaffold()
        assert vdsd.get_button_input(99) is None

    def test_button_input_in_properties(self):
        """get_properties includes button descriptions/settings/states."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)
        props = vdsd.get_properties()
        assert "buttonInputDescriptions" in props
        assert "buttonInputSettings" in props
        assert "buttonInputStates" in props
        assert "0" in props["buttonInputDescriptions"]

    def test_button_input_not_in_properties_when_empty(self):
        _, _, _, vdsd = _scaffold()
        props = vdsd.get_properties()
        assert "buttonInputDescriptions" not in props

    def test_button_input_in_property_tree(self):
        """get_property_tree includes buttonInputs."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)
        tree = vdsd.get_property_tree()
        assert "buttonInputs" in tree
        assert len(tree["buttonInputs"]) == 1

    def test_button_input_persistence_round_trip(self):
        """Vdsd persistence restores button inputs."""
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="Persisted",
            button_type=ButtonType.SINGLE_PUSHBUTTON,
            button_element_id=ButtonElementID.CENTER,
            button_id=0,
            group=5,
            function=ButtonFunction.ROOM,
        )
        vdsd.add_button_input(btn)
        tree = vdsd.get_property_tree()

        # Create new vdsd and restore.
        _, _, device2, vdsd2 = _scaffold()
        vdsd2._apply_state(tree)

        assert len(vdsd2.button_inputs) == 1
        restored = vdsd2.get_button_input(0)
        assert restored is not None
        assert restored.name == "Persisted"
        assert restored.group == 5
        assert restored.function == ButtonFunction.ROOM

    def test_multiple_button_inputs(self):
        """Two button inputs can coexist on same vdSD."""
        _, _, _, vdsd = _scaffold()
        btn0 = _make_button_input(vdsd, ds_index=0, name="Down")
        btn1 = _make_button_input(
            vdsd,
            ds_index=1,
            name="Up",
            button_element_id=ButtonElementID.UP,
        )
        vdsd.add_button_input(btn0)
        vdsd.add_button_input(btn1)
        assert len(vdsd.button_inputs) == 2
        assert vdsd.get_button_input(0).name == "Down"
        assert vdsd.get_button_input(1).name == "Up"


# ===========================================================================
# Session management
# ===========================================================================


class TestButtonInputSessionManagement:
    """start_alive_timer / stop_alive_timer (session hooks)."""

    def test_start_alive_timer_stores_session(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        btn.start_alive_timer(session)
        assert btn._session is session

    def test_stop_alive_timer_clears_session(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        btn.start_alive_timer(session)
        btn.stop_alive_timer()
        assert btn._session is None

    def test_stop_alive_timer_stops_click_detector(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        btn.start_alive_timer(session)
        btn.stop_alive_timer()
        assert btn.click_detector.state == "idle"

    @pytest.mark.asyncio
    async def test_update_click_uses_stored_session(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        session = _make_mock_session()
        vdsd._announced = True
        btn.start_alive_timer(session)
        await btn.update_click(ButtonClickType.CLICK_1X)
        session.send_notification.assert_awaited_once()


# ===========================================================================
# VdcHost setProperty integration
# ===========================================================================


class TestVdcHostButtonInputSetProperty:
    """buttonInputSettings via _apply_vdsd_set_property."""

    def test_set_button_settings(self):
        host, vdc, device, vdsd = _scaffold()
        host.add_vdc(vdc)
        vdc.add_device(device)
        device.add_vdsd(vdsd)

        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)

        incoming = {
            "buttonInputSettings": {
                "0": {
                    "group": 3,
                    "function": int(ButtonFunction.AREA_1),
                    "mode": int(ButtonMode.STANDARD),
                    "channel": 15,
                },
            },
        }
        host._apply_vdsd_set_property(vdsd, incoming)

        assert btn.group == 3
        assert btn.function == ButtonFunction.AREA_1
        assert btn.channel == 15


# ===========================================================================
# Auto-save chain
# ===========================================================================


class TestButtonInputAutoSave:
    """Settings changes trigger auto-save up the chain."""

    def test_group_setter_triggers_auto_save(self):
        host, vdc, device, vdsd = _scaffold()
        host.add_vdc(vdc)
        vdc.add_device(device)
        device.add_vdsd(vdsd)
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)

        with patch.object(device, "_schedule_auto_save") as mock_save:
            btn.group = 5
            mock_save.assert_called()

    def test_function_setter_triggers_auto_save(self):
        host, vdc, device, vdsd = _scaffold()
        host.add_vdc(vdc)
        vdc.add_device(device)
        device.add_vdsd(vdsd)
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)

        with patch.object(device, "_schedule_auto_save") as mock_save:
            btn.function = ButtonFunction.ROOM
            mock_save.assert_called()


# ===========================================================================
# ClickDetector — state machine
# ===========================================================================


class TestClickDetectorConstruction:
    """ClickDetector creation and default values."""

    def test_default_state(self):
        cd = ClickDetector(on_click=MagicMock())
        assert cd.state == "idle"
        assert cd.tip_count == 0

    def test_custom_timings(self):
        cd = ClickDetector(
            on_click=MagicMock(),
            tip_timeout=0.5,
            multi_click_window=0.6,
            hold_repeat_interval=2.0,
            use_tip_events=True,
        )
        assert cd.tip_timeout == 0.5
        assert cd.multi_click_window == 0.6
        assert cd.hold_repeat_interval == 2.0
        assert cd.use_tip_events is True

    def test_repr(self):
        cd = ClickDetector(on_click=MagicMock())
        r = repr(cd)
        assert "ClickDetector" in r
        assert "idle" in r


class TestClickDetectorSingleClick:
    """Single click detection (press + release within tip_timeout)."""

    @pytest.mark.asyncio
    async def test_single_click_click_mode(self):
        """Short press → CLICK_1X after multi-click window."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.05,
        )
        cd.press()
        assert cd.state == "pressed"
        await asyncio.sleep(0.02)  # within tip_timeout
        cd.release()
        assert cd.state == "tip_wait"
        assert cd.tip_count == 1
        await asyncio.sleep(0.1)  # multi_click_window expires
        assert cd.state == "idle"
        assert len(events) == 1
        assert events[0] == (ButtonClickType.CLICK_1X, False)

    @pytest.mark.asyncio
    async def test_single_click_tip_mode(self):
        """Short press with use_tip_events → TIP_1X."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.05,
            use_tip_events=True,
        )
        cd.press()
        await asyncio.sleep(0.02)
        cd.release()
        await asyncio.sleep(0.1)
        assert events[-1] == (ButtonClickType.TIP_1X, False)


class TestClickDetectorDoubleClick:
    """Double click detection."""

    @pytest.mark.asyncio
    async def test_double_click(self):
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
        )
        # First press/release
        cd.press()
        await asyncio.sleep(0.02)
        cd.release()
        await asyncio.sleep(0.02)  # within multi-click window
        # Second press/release
        cd.press()
        await asyncio.sleep(0.02)
        cd.release()
        await asyncio.sleep(0.15)  # multi_click_window expires

        assert len(events) == 1
        assert events[0] == (ButtonClickType.CLICK_2X, False)

    @pytest.mark.asyncio
    async def test_triple_click(self):
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
        )
        for _ in range(3):
            cd.press()
            await asyncio.sleep(0.02)
            cd.release()
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.15)

        assert len(events) == 1
        assert events[0] == (ButtonClickType.CLICK_3X, False)

    @pytest.mark.asyncio
    async def test_quad_click_caps_at_3x(self):
        """4+ clicks in click mode cap at CLICK_3X."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
        )
        for _ in range(4):
            cd.press()
            await asyncio.sleep(0.02)
            cd.release()
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.15)

        assert events[-1][0] == ButtonClickType.CLICK_3X

    @pytest.mark.asyncio
    async def test_quad_click_tip_mode(self):
        """4+ clicks in tip mode emit TIP_4X."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
            use_tip_events=True,
        )
        for _ in range(4):
            cd.press()
            await asyncio.sleep(0.02)
            cd.release()
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.15)

        assert events[-1][0] == ButtonClickType.TIP_4X


class TestClickDetectorHold:
    """Hold detection (press held past tip_timeout)."""

    @pytest.mark.asyncio
    async def test_hold_start(self):
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            hold_repeat_interval=10.0,  # prevent repeat during test
        )
        cd.press()
        await asyncio.sleep(0.1)  # past tip_timeout
        assert cd.state == "holding"
        assert len(events) >= 1
        assert events[0] == (ButtonClickType.HOLD_START, True)

    @pytest.mark.asyncio
    async def test_hold_end(self):
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            hold_repeat_interval=10.0,
        )
        cd.press()
        await asyncio.sleep(0.1)
        cd.release()
        await asyncio.sleep(0)  # let ensure_future run
        assert cd.state == "idle"
        assert events[-1] == (ButtonClickType.HOLD_END, False)

    @pytest.mark.asyncio
    async def test_hold_repeat(self):
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            hold_repeat_interval=0.05,
        )
        cd.press()
        await asyncio.sleep(0.2)  # tip + several repeats
        cd.release()
        await asyncio.sleep(0)  # let ensure_future run

        repeat_events = [
            e for e in events if e[0] == ButtonClickType.HOLD_REPEAT
        ]
        assert len(repeat_events) >= 1
        for ct, val in repeat_events:
            assert val is True

        assert events[-1] == (ButtonClickType.HOLD_END, False)


class TestClickDetectorCombos:
    """Short-long and short-short-long combo detection."""

    @pytest.mark.asyncio
    async def test_short_long(self):
        """One short press + hold → SHORT_LONG."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
            hold_repeat_interval=10.0,
        )
        # First: short press
        cd.press()
        await asyncio.sleep(0.02)
        cd.release()
        await asyncio.sleep(0.02)  # within multi-click window
        # Second: long press (hold)
        cd.press()
        await asyncio.sleep(0.1)  # past tip_timeout
        assert cd.state == "holding"

        combo_events = [
            e for e in events if e[0] == ButtonClickType.SHORT_LONG
        ]
        assert len(combo_events) == 1
        assert combo_events[0] == (ButtonClickType.SHORT_LONG, True)

        cd.release()
        await asyncio.sleep(0)  # let ensure_future run
        assert events[-1] == (ButtonClickType.HOLD_END, False)

    @pytest.mark.asyncio
    async def test_short_short_long(self):
        """Two short presses + hold → SHORT_SHORT_LONG."""
        events: List[Tuple[ButtonClickType, bool]] = []

        async def on_click(ct, val):
            events.append((ct, val))

        cd = ClickDetector(
            on_click=on_click,
            tip_timeout=0.05,
            multi_click_window=0.08,
            hold_repeat_interval=10.0,
        )
        # Two short presses
        for _ in range(2):
            cd.press()
            await asyncio.sleep(0.02)
            cd.release()
            await asyncio.sleep(0.02)
        # Long press
        cd.press()
        await asyncio.sleep(0.1)

        combo_events = [
            e for e in events
            if e[0] == ButtonClickType.SHORT_SHORT_LONG
        ]
        assert len(combo_events) == 1
        assert combo_events[0] == (
            ButtonClickType.SHORT_SHORT_LONG,
            True,
        )

        cd.release()
        await asyncio.sleep(0)  # let ensure_future run
        assert events[-1] == (ButtonClickType.HOLD_END, False)


class TestClickDetectorEdgeCases:
    """Edge case handling in the state machine."""

    @pytest.mark.asyncio
    async def test_double_press_ignored(self):
        """Pressing while already pressed is ignored."""
        cd = ClickDetector(on_click=MagicMock())
        cd.press()
        assert cd.state == "pressed"
        cd.press()  # duplicate — should be ignored
        assert cd.state == "pressed"

    @pytest.mark.asyncio
    async def test_release_in_idle_ignored(self):
        """Release without press is ignored."""
        cd = ClickDetector(on_click=MagicMock())
        cd.release()  # no-op
        assert cd.state == "idle"

    @pytest.mark.asyncio
    async def test_stop_resets(self):
        """stop() cancels timers and returns to idle."""
        cd = ClickDetector(
            on_click=MagicMock(),
            tip_timeout=0.05,
        )
        cd.press()
        assert cd.state == "pressed"
        cd.stop()
        assert cd.state == "idle"
        assert cd.tip_count == 0

    def test_press_without_event_loop(self):
        """press() without running event loop doesn't crash."""
        cd = ClickDetector(on_click=MagicMock())
        # No event loop — timer scheduling silently fails.
        cd.press()
        assert cd.state == "pressed"

    @pytest.mark.asyncio
    async def test_callback_exception_logged(self):
        """Exception in callback is caught and logged."""

        def bad_callback(ct, val):
            raise RuntimeError("boom")

        cd = ClickDetector(
            on_click=bad_callback,
            tip_timeout=0.05,
            multi_click_window=0.05,
        )
        cd.press()
        await asyncio.sleep(0.02)
        cd.release()
        await asyncio.sleep(0.1)
        # Should not raise, state returns to idle.
        assert cd.state == "idle"


# ===========================================================================
# ButtonInput + ClickDetector integration
# ===========================================================================


class TestButtonInputClickDetectorIntegration:
    """press() / release() on ButtonInput via ClickDetector."""

    @pytest.mark.asyncio
    async def test_press_sets_value_true(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.press()
        assert btn.value is True

    @pytest.mark.asyncio
    async def test_release_sets_value_false(self):
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        btn.press()
        btn.release()
        assert btn.value is False

    @pytest.mark.asyncio
    async def test_single_click_pushes(self):
        """press+release resolves CLICK_1X and pushes."""
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="Quick",
            click_detector_config={
                "tip_timeout": 0.05,
                "multi_click_window": 0.05,
            },
        )
        session = _make_mock_session()
        vdsd._announced = True
        btn.start_alive_timer(session)

        btn.press()
        await asyncio.sleep(0.02)
        btn.release()
        await asyncio.sleep(0.1)

        assert btn.click_type == ButtonClickType.CLICK_1X
        assert btn.value is False
        session.send_notification.assert_awaited()

    @pytest.mark.asyncio
    async def test_hold_pushes_sequence(self):
        """Long press pushes HOLD_START → HOLD_END."""
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="Hold",
            click_detector_config={
                "tip_timeout": 0.05,
                "hold_repeat_interval": 10.0,
            },
        )
        session = _make_mock_session()
        vdsd._announced = True
        btn.start_alive_timer(session)

        btn.press()
        await asyncio.sleep(0.1)
        assert btn.click_type == ButtonClickType.HOLD_START
        assert btn.value is True

        btn.release()
        await asyncio.sleep(0.02)
        assert btn.click_type == ButtonClickType.HOLD_END
        assert btn.value is False

        # At least 2 pushes: HOLD_START + HOLD_END.
        assert session.send_notification.await_count >= 2

    @pytest.mark.asyncio
    async def test_stop_session_stops_detector(self):
        """stop_alive_timer stops the click detector."""
        _, _, _, vdsd = _scaffold()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=0,
            name="StopTest",
            click_detector_config={"tip_timeout": 0.05},
        )
        session = _make_mock_session()
        btn.start_alive_timer(session)
        btn.press()
        assert btn.click_detector.state == "pressed"
        btn.stop_alive_timer()
        assert btn.click_detector.state == "idle"
        assert btn._session is None


# ===========================================================================
# Helper functions
# ===========================================================================


class TestGetRequiredElements:
    """get_required_elements helper."""

    def test_single_pushbutton(self):
        elems = get_required_elements(ButtonType.SINGLE_PUSHBUTTON)
        assert elems == [ButtonElementID.CENTER]

    def test_two_way_pushbutton(self):
        elems = get_required_elements(ButtonType.TWO_WAY_PUSHBUTTON)
        assert elems == [ButtonElementID.DOWN, ButtonElementID.UP]

    def test_four_way_navigation(self):
        elems = get_required_elements(ButtonType.FOUR_WAY_NAVIGATION)
        assert len(elems) == 4
        assert ButtonElementID.DOWN in elems
        assert ButtonElementID.UP in elems
        assert ButtonElementID.LEFT in elems
        assert ButtonElementID.RIGHT in elems

    def test_four_way_with_center(self):
        elems = get_required_elements(ButtonType.FOUR_WAY_WITH_CENTER)
        assert len(elems) == 5
        assert ButtonElementID.CENTER in elems

    def test_eight_way_with_center(self):
        elems = get_required_elements(ButtonType.EIGHT_WAY_WITH_CENTER)
        assert len(elems) == 9
        assert ButtonElementID.UPPER_LEFT in elems
        assert ButtonElementID.LOWER_RIGHT in elems

    def test_on_off_switch(self):
        elems = get_required_elements(ButtonType.ON_OFF_SWITCH)
        assert elems == [ButtonElementID.DOWN, ButtonElementID.UP]

    def test_undefined_returns_empty(self):
        elems = get_required_elements(ButtonType.UNDEFINED)
        assert elems == []


class TestCreateButtonGroup:
    """create_button_group factory helper."""

    def test_single_pushbutton(self):
        _, _, _, vdsd = _scaffold()
        buttons = create_button_group(
            vdsd,
            button_id=0,
            button_type=ButtonType.SINGLE_PUSHBUTTON,
            name_prefix="Main",
        )
        assert len(buttons) == 1
        assert buttons[0].button_element_id == ButtonElementID.CENTER
        assert buttons[0].button_id == 0
        assert buttons[0].ds_index == 0
        assert "Center" in buttons[0].name

    def test_two_way_pushbutton(self):
        _, _, _, vdsd = _scaffold()
        buttons = create_button_group(
            vdsd,
            button_id=1,
            button_type=ButtonType.TWO_WAY_PUSHBUTTON,
            start_index=5,
        )
        assert len(buttons) == 2
        assert buttons[0].ds_index == 5
        assert buttons[0].button_element_id == ButtonElementID.DOWN
        assert buttons[1].ds_index == 6
        assert buttons[1].button_element_id == ButtonElementID.UP
        assert all(b.button_id == 1 for b in buttons)
        assert all(
            b.button_type == ButtonType.TWO_WAY_PUSHBUTTON
            for b in buttons
        )

    def test_settings_propagated(self):
        _, _, _, vdsd = _scaffold()
        buttons = create_button_group(
            vdsd,
            button_id=0,
            button_type=ButtonType.SINGLE_PUSHBUTTON,
            group=3,
            function=ButtonFunction.ROOM,
            mode=ButtonMode.SWITCHED,
            channel=10,
            sets_local_priority=True,
            calls_present=True,
        )
        btn = buttons[0]
        assert btn.group == 3
        assert btn.function == ButtonFunction.ROOM
        assert btn.mode == ButtonMode.SWITCHED
        assert btn.channel == 10
        assert btn.sets_local_priority is True
        assert btn.calls_present is True

    def test_undefined_raises(self):
        _, _, _, vdsd = _scaffold()
        with pytest.raises(ValueError, match="no standard element"):
            create_button_group(
                vdsd,
                button_id=0,
                button_type=ButtonType.UNDEFINED,
            )

    def test_click_detector_config_propagated(self):
        _, _, _, vdsd = _scaffold()
        buttons = create_button_group(
            vdsd,
            button_id=0,
            button_type=ButtonType.SINGLE_PUSHBUTTON,
            click_detector_config={"tip_timeout": 0.5},
        )
        assert buttons[0].click_detector.tip_timeout == 0.5

    def test_eight_way_with_center_elements(self):
        _, _, _, vdsd = _scaffold()
        buttons = create_button_group(
            vdsd,
            button_id=0,
            button_type=ButtonType.EIGHT_WAY_WITH_CENTER,
        )
        assert len(buttons) == 9
        element_ids = {b.button_element_id for b in buttons}
        expected = set(
            BUTTON_TYPE_ELEMENTS[ButtonType.EIGHT_WAY_WITH_CENTER]
        )
        assert element_ids == expected


# ===========================================================================
# Enum completeness
# ===========================================================================


class TestButtonEnumCompleteness:
    """Verify enum values against documentation."""

    def test_click_type_values(self):
        assert ButtonClickType.TIP_1X == 0
        assert ButtonClickType.TIP_4X == 3
        assert ButtonClickType.HOLD_START == 4
        assert ButtonClickType.HOLD_REPEAT == 5
        assert ButtonClickType.HOLD_END == 6
        assert ButtonClickType.CLICK_1X == 7
        assert ButtonClickType.CLICK_3X == 9
        assert ButtonClickType.SHORT_LONG == 10
        assert ButtonClickType.SHORT_SHORT_LONG == 13
        assert ButtonClickType.IDLE == 255

    def test_button_type_values(self):
        assert ButtonType.UNDEFINED == 0
        assert ButtonType.SINGLE_PUSHBUTTON == 1
        assert ButtonType.TWO_WAY_PUSHBUTTON == 2
        assert ButtonType.FOUR_WAY_NAVIGATION == 3
        assert ButtonType.FOUR_WAY_WITH_CENTER == 4
        assert ButtonType.EIGHT_WAY_WITH_CENTER == 5
        assert ButtonType.ON_OFF_SWITCH == 6

    def test_button_element_id_values(self):
        assert ButtonElementID.CENTER == 0
        assert ButtonElementID.DOWN == 1
        assert ButtonElementID.UP == 2
        assert ButtonElementID.LEFT == 3
        assert ButtonElementID.RIGHT == 4
        assert ButtonElementID.UPPER_LEFT == 5
        assert ButtonElementID.LOWER_LEFT == 6
        assert ButtonElementID.UPPER_RIGHT == 7
        assert ButtonElementID.LOWER_RIGHT == 8

    def test_action_mode_values(self):
        assert ActionMode.NORMAL == 0
        assert ActionMode.FORCE == 1
        assert ActionMode.UNDO == 2

    def test_button_function_values(self):
        assert ButtonFunction.DEVICE == 0
        assert ButtonFunction.ROOM == 5
        assert ButtonFunction.APP == 15

    def test_button_type_elements_coverage(self):
        """Every non-UNDEFINED ButtonType has elements defined."""
        for bt in ButtonType:
            if bt == ButtonType.UNDEFINED:
                assert BUTTON_TYPE_ELEMENTS[bt] == []
            else:
                assert len(BUTTON_TYPE_ELEMENTS[bt]) >= 1


# ===========================================================================
# __init__.py exports
# ===========================================================================


class TestExports:
    """Verify all new exports are importable."""

    def test_button_input_importable(self):
        from pydsvdcapi import ButtonInput  # noqa: F811

        assert ButtonInput is not None

    def test_click_detector_importable(self):
        from pydsvdcapi import ClickDetector  # noqa: F811

        assert ClickDetector is not None

    def test_action_mode_importable(self):
        from pydsvdcapi import ActionMode  # noqa: F811

        assert ActionMode is not None

    def test_create_button_group_importable(self):
        from pydsvdcapi import create_button_group  # noqa: F811

        assert create_button_group is not None

    def test_get_required_elements_importable(self):
        from pydsvdcapi import get_required_elements  # noqa: F811

        assert get_required_elements is not None

    def test_button_type_elements_importable(self):
        from pydsvdcapi import BUTTON_TYPE_ELEMENTS  # noqa: F811

        assert BUTTON_TYPE_ELEMENTS is not None


# ===========================================================================
# Announcement lifecycle
# ===========================================================================


class TestAnnouncementLifecycle:
    """ButtonInput session hooks during vdSD announce/vanish/reset."""

    @pytest.mark.asyncio
    async def test_announce_starts_session(self):
        """When vdSD is announced, button inputs get the session."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)

        session = _make_mock_session()
        # Simulate announcement response.
        response = pb.Message()
        response.generic_response.code = pb.ERR_OK
        session.send_request = AsyncMock(return_value=response)

        await vdsd.announce(session)

        assert btn._session is session

    @pytest.mark.asyncio
    async def test_vanish_clears_session(self):
        """Vanish stops the click detector and clears session."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)

        session = _make_mock_session()
        response = pb.Message()
        response.generic_response.code = pb.ERR_OK
        session.send_request = AsyncMock(return_value=response)
        session.send_notification = AsyncMock()

        await vdsd.announce(session)
        assert btn._session is session

        await vdsd.vanish(session)
        assert btn._session is None

    def test_reset_announcement_clears_session(self):
        """reset_announcement stops buttons."""
        _, _, _, vdsd = _scaffold()
        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)
        btn._session = _make_mock_session()
        vdsd.reset_announcement()
        assert btn._session is None

    @pytest.mark.asyncio
    async def test_add_after_announce(self):
        """Adding a button after announcement starts session hook."""
        _, _, _, vdsd = _scaffold()
        session = _make_mock_session()
        response = pb.Message()
        response.generic_response.code = pb.ERR_OK
        session.send_request = AsyncMock(return_value=response)

        await vdsd.announce(session)

        btn = _make_button_input(vdsd)
        vdsd.add_button_input(btn)
        assert btn._session is session
