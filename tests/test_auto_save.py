"""Tests for VdcHost debounced auto-save functionality."""

import asyncio
from unittest.mock import patch

import yaml

from pydsvdcapi.actions import CustomAction
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import AUTO_SAVE_DELAY, VdcHost
from pydsvdcapi.vdsd import Device, Vdsd

TEST_MAC = "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Helper — yield control long enough for the debounce handle to fire
# ---------------------------------------------------------------------------


async def _wait_for_auto_save(margin: float = 0.3) -> None:
    """Sleep long enough for the debounce handle to fire."""
    await asyncio.sleep(AUTO_SAVE_DELAY + margin)


# ---------------------------------------------------------------------------
# Auto-save triggers
# ---------------------------------------------------------------------------


class TestAutoSaveTriggers:
    async def test_changing_name_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="Initial")
        assert not path.exists()  # nothing saved yet

        host.name = "Changed"
        await _wait_for_auto_save()

        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "Changed"

    async def test_changing_model_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.model = "New Model"
        await _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["model"] == "New Model"

    async def test_changing_vendor_name_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.vendor_name = "AcmeCorp"
        await _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["vendorName"] == "AcmeCorp"

    async def test_all_tracked_attrs_trigger_save(self, tmp_path):
        """Every attribute in _TRACKED_ATTRS should trigger auto-save."""
        for attr in VdcHost._TRACKED_ATTRS:
            p = tmp_path / f"{attr}.yaml"
            host = VdcHost(mac=TEST_MAC, state_path=p)
            setattr(host, attr, "test_value")
            await _wait_for_auto_save()
            assert p.is_file(), f"Auto-save not triggered for {attr}"


# ---------------------------------------------------------------------------
# Debounce coalescence
# ---------------------------------------------------------------------------


class TestAutoSaveDebounce:
    async def test_rapid_changes_coalesce(self, tmp_path):
        """Multiple rapid changes should result in only the final state."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="V0")

        # Rapid successive changes — all within the debounce window.
        host.name = "V1"
        host.name = "V2"
        host.name = "V3"
        await _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "V3"

    async def test_rapid_changes_produce_single_write(self, tmp_path):
        """The PropertyStore.save method should only be called once."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        assert host._store is not None
        with patch.object(host._store, "save", wraps=host._store.save) as mock_save:
            host.name = "A"
            host.name = "B"
            host.name = "C"
            await _wait_for_auto_save()

            assert mock_save.call_count == 1


# ---------------------------------------------------------------------------
# No auto-save without persistence
# ---------------------------------------------------------------------------


class TestNoAutoSaveWithoutStore:
    async def test_no_handle_without_state_path(self):
        host = VdcHost(mac=TEST_MAC)
        assert not host._auto_save_enabled

        host.name = "Changed"
        assert host._save_handle is None

    async def test_init_does_not_trigger_immediate_save(self, tmp_path):
        """Property assignments during __init__ must not trigger an
        immediate (synchronous) save — only a debounced one."""
        path = tmp_path / "host.yaml"
        host = VdcHost(
            mac=TEST_MAC,
            state_path=path,
            name="Init",
            model="InitModel",
            vendor_name="InitVendor",
        )
        # File should NOT exist *immediately* — the debounced handle
        # has not fired yet.
        assert not path.exists()
        # But a handle IS scheduled for the initial save.
        assert host._save_handle is not None
        # Cancel it to avoid side effects.
        host._cancel_auto_save()

    async def test_init_auto_save_fires_after_delay(self, tmp_path):
        """After the debounce delay the initial state is persisted."""
        path = tmp_path / "host.yaml"
        VdcHost(
            mac=TEST_MAC,
            state_path=path,
            name="Delayed",
        )
        await _wait_for_auto_save()
        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "Delayed"


# ---------------------------------------------------------------------------
# No auto-save during load()
# ---------------------------------------------------------------------------


class TestNoAutoSaveDuringLoad:
    async def test_load_does_not_trigger_auto_save(self, tmp_path):
        path = tmp_path / "host.yaml"

        # Create and manually save.
        h1 = VdcHost(mac=TEST_MAC, state_path=path, name="Saved")
        h1.save()

        # Modify externally.
        data = yaml.safe_load(path.read_text())
        data["vdcHost"]["name"] = "External"
        path.write_text(yaml.dump(data))

        # Load should NOT schedule an auto-save.
        with patch.object(h1, "_schedule_auto_save") as mock_sched:
            h1.load()
            mock_sched.assert_not_called()

        assert h1.name == "External"


# ---------------------------------------------------------------------------
# flush()
# ---------------------------------------------------------------------------


class TestFlush:
    async def test_flush_saves_immediately(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="Before")

        host.name = "After"
        # Don't wait for debounce — flush immediately.
        host.flush()

        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "After"
        assert host._save_handle is None

    async def test_flush_noop_when_nothing_pending(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        # Flush the initial auto-save first.
        host.flush()
        assert path.is_file()

        # Delete the file to prove no *second* flush writes it.
        path.unlink()
        host.flush()
        assert not path.exists()

    async def test_flush_cancels_handle(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.name = "Changed"
        assert host._save_handle is not None

        host.flush()
        assert host._save_handle is None


# ---------------------------------------------------------------------------
# Manual save() cancels pending auto-save
# ---------------------------------------------------------------------------


class TestManualSaveCancels:
    async def test_save_cancels_pending_auto_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.name = "Changed"
        assert host._save_handle is not None

        host.save()
        assert host._save_handle is None

    async def test_no_spurious_auto_save_after_manual_save(self, tmp_path):
        """After manual save(), the debounce handle must not fire."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="V1")

        host.name = "V2"
        host.save()  # cancels the pending auto-save

        # Corrupt the file — if the handle fires it would overwrite.
        path.write_text("corrupted", encoding="utf-8")
        await _wait_for_auto_save()

        # File should still be corrupted — no auto-save fired.
        assert path.read_text() == "corrupted"


# ---------------------------------------------------------------------------
# Private attrs do NOT trigger auto-save
# ---------------------------------------------------------------------------


class TestPrivateAttrsIgnored:
    async def test_private_attrs_do_not_trigger(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        # Cancel the initial auto-save scheduled during __init__.
        host._cancel_auto_save()

        host._active = False
        host._port = 9999
        assert host._save_handle is None
        assert not path.exists()


# ---------------------------------------------------------------------------
# vdSD-level property persistence
# ---------------------------------------------------------------------------


def _make_persisted_scaffold(path):
    host = VdcHost(mac=TEST_MAC, state_path=path)
    vdc = Vdc(host=host, implementation_id="x-persist-test", name="Persist vDC", model="P1")
    base = DsUid.from_name_in_space("persist-dev", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=base)
    vdsd = Vdsd(device=device, primary_group=ColorGroup.YELLOW, name="PersistDev", model="PM")
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdsd


class TestVdsdPropertyPersistence:
    """Regression tests: vdSD property changes must be persisted to YAML."""

    def _vdsd_node(self, data: dict) -> dict:
        return data["vdcHost"]["vdcs"][0]["devices"][0]["vdsds"][0]

    async def test_prog_mode_change_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host, vdsd = _make_persisted_scaffold(path)

        vdsd.prog_mode = True
        host.flush()

        data = yaml.safe_load(path.read_text())
        assert self._vdsd_node(data)["progMode"] is True

    async def test_prog_mode_roundtrips_through_yaml(self, tmp_path):
        path = tmp_path / "host.yaml"
        host, vdsd = _make_persisted_scaffold(path)

        await host._apply_vdsd_set_property(vdsd, {"progMode": True})
        host.flush()

        data = yaml.safe_load(path.read_text())
        assert self._vdsd_node(data)["progMode"] is True

    async def test_custom_action_change_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host, vdsd = _make_persisted_scaffold(path)

        action = CustomAction(vdsd, ds_index=0, name="custom.test", action="play", title="Old")
        vdsd._custom_actions[0] = action

        await host._apply_vdsd_set_property(vdsd, {"customActions": {"0": {"title": "New"}}})
        host.flush()

        data = yaml.safe_load(path.read_text())
        assert self._vdsd_node(data)["customActions"][0]["title"] == "New"
