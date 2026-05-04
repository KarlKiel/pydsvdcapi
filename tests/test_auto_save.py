"""Tests for VdcHost debounced auto-save functionality."""

import time
from unittest.mock import patch

import yaml

from pydsvdcapi.vdc_host import AUTO_SAVE_DELAY, VdcHost

TEST_MAC = "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Helper — wait for auto-save to complete (with safety margin)
# ---------------------------------------------------------------------------


def _wait_for_auto_save(margin: float = 0.3) -> None:
    """Sleep long enough for the debounce timer to fire."""
    time.sleep(AUTO_SAVE_DELAY + margin)


# ---------------------------------------------------------------------------
# Auto-save triggers
# ---------------------------------------------------------------------------


class TestAutoSaveTriggers:
    def test_changing_name_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="Initial")
        assert not path.exists()  # nothing saved yet

        host.name = "Changed"
        _wait_for_auto_save()

        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "Changed"

    def test_changing_model_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.model = "New Model"
        _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["model"] == "New Model"

    def test_changing_vendor_name_triggers_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.vendor_name = "AcmeCorp"
        _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["vendorName"] == "AcmeCorp"

    def test_all_tracked_attrs_trigger_save(self, tmp_path):
        """Every attribute in _TRACKED_ATTRS should trigger auto-save."""
        for attr in VdcHost._TRACKED_ATTRS:
            p = tmp_path / f"{attr}.yaml"
            host = VdcHost(mac=TEST_MAC, state_path=p)
            setattr(host, attr, "test_value")
            _wait_for_auto_save()
            assert p.is_file(), f"Auto-save not triggered for {attr}"


# ---------------------------------------------------------------------------
# Debounce coalescence
# ---------------------------------------------------------------------------


class TestAutoSaveDebounce:
    def test_rapid_changes_coalesce(self, tmp_path):
        """Multiple rapid changes should result in only the final state."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="V0")

        # Rapid successive changes — all within the debounce window.
        host.name = "V1"
        host.name = "V2"
        host.name = "V3"
        _wait_for_auto_save()

        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "V3"

    def test_rapid_changes_produce_single_write(self, tmp_path):
        """The PropertyStore.save method should only be called once."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        assert host._store is not None
        with patch.object(host._store, "save", wraps=host._store.save) as mock_save:
            host.name = "A"
            host.name = "B"
            host.name = "C"
            _wait_for_auto_save()

            assert mock_save.call_count == 1


# ---------------------------------------------------------------------------
# No auto-save without persistence
# ---------------------------------------------------------------------------


class TestNoAutoSaveWithoutStore:
    def test_no_timer_without_state_path(self):
        host = VdcHost(mac=TEST_MAC)
        assert not host._auto_save_enabled

        host.name = "Changed"
        assert host._save_timer is None

    def test_init_does_not_trigger_immediate_save(self, tmp_path):
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
        # File should NOT exist *immediately* — the debounced timer
        # has not fired yet.
        assert not path.exists()
        # But a timer IS scheduled for the initial save.
        assert host._save_timer is not None
        # Cancel it to avoid side effects.
        host._cancel_auto_save()

    def test_init_auto_save_fires_after_delay(self, tmp_path):
        """After the debounce delay the initial state is persisted."""
        path = tmp_path / "host.yaml"
        VdcHost(
            mac=TEST_MAC,
            state_path=path,
            name="Delayed",
        )
        _wait_for_auto_save()
        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "Delayed"


# ---------------------------------------------------------------------------
# No auto-save during load()
# ---------------------------------------------------------------------------


class TestNoAutoSaveDuringLoad:
    def test_load_does_not_trigger_auto_save(self, tmp_path):
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
    def test_flush_saves_immediately(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="Before")

        host.name = "After"
        # Don't wait for debounce — flush immediately.
        host.flush()

        assert path.is_file()
        data = yaml.safe_load(path.read_text())
        assert data["vdcHost"]["name"] == "After"
        assert host._save_timer is None

    def test_flush_noop_when_nothing_pending(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        # Flush the initial auto-save first.
        host.flush()
        assert path.is_file()

        # Delete the file to prove no *second* flush writes it.
        path.unlink()
        host.flush()
        assert not path.exists()

    def test_flush_cancels_timer(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.name = "Changed"
        assert host._save_timer is not None

        host.flush()
        assert host._save_timer is None


# ---------------------------------------------------------------------------
# Manual save() cancels pending auto-save
# ---------------------------------------------------------------------------


class TestManualSaveCancels:
    def test_save_cancels_pending_auto_save(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        host.name = "Changed"
        assert host._save_timer is not None

        host.save()
        assert host._save_timer is None

    def test_no_spurious_auto_save_after_manual_save(self, tmp_path):
        """After manual save(), the debounce timer must not fire."""
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="V1")

        host.name = "V2"
        host.save()  # cancels the pending auto-save

        # Corrupt the file — if the timer fires it would overwrite.
        path.write_text("corrupted", encoding="utf-8")
        _wait_for_auto_save()

        # File should still be corrupted — no auto-save fired.
        assert path.read_text() == "corrupted"


# ---------------------------------------------------------------------------
# Private attrs do NOT trigger auto-save
# ---------------------------------------------------------------------------


class TestPrivateAttrsIgnored:
    def test_private_attrs_do_not_trigger(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path)

        # Cancel the initial auto-save scheduled during __init__.
        host._cancel_auto_save()

        host._active = False
        host._port = 9999
        assert host._save_timer is None
        assert not path.exists()
