"""Tests for the PropertyStore persistence layer."""

from unittest.mock import patch

import pytest
import yaml

from pydsvdcapi.persistence import PropertyStore


@pytest.fixture
def store(tmp_path):
    """A PropertyStore pointing at a temporary directory."""
    return PropertyStore(tmp_path / "state.yaml")


@pytest.fixture
def sample_tree():
    """A minimal property tree for testing."""
    return {
        "vdcHost": {
            "dSUID": "198C033E330755E78015F97AD093DD1C00",
            "mac": "AA:BB:CC:DD:EE:FF",
            "port": 8444,
            "name": "Test Host",
            "model": "TestModel",
            "modelVersion": "1.0",
            "modelUID": "AABBCCDD" * 4 + "00",
            "hardwareGuid": "macaddress:AA:BB:CC:DD:EE:FF",
            "vendorName": "TestVendor",
        }
    }


# ---------------------------------------------------------------------------
# Basic save / load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_creates_file(self, store, sample_tree):
        store.save(sample_tree)
        assert store.path.is_file()

    def test_load_returns_saved_data(self, store, sample_tree):
        store.save(sample_tree)
        loaded = store.load()
        assert loaded == sample_tree

    def test_load_without_file_returns_none(self, store):
        assert store.load() is None

    def test_yaml_is_human_readable(self, store, sample_tree):
        store.save(sample_tree)
        content = store.path.read_text(encoding="utf-8")
        # Should contain readable keys, not flow-style JSON blobs
        assert "vdcHost:" in content
        assert "dSUID:" in content
        assert "name: Test Host" in content

    def test_roundtrip_preserves_types(self, store):
        tree = {
            "vdcHost": {
                "port": 8444,
                "name": "typed test",
                "active": True,
                "modelVersion": None,
            }
        }
        store.save(tree)
        loaded = store.load()
        assert loaded["vdcHost"]["port"] == 8444
        assert isinstance(loaded["vdcHost"]["port"], int)
        assert loaded["vdcHost"]["active"] is True
        assert loaded["vdcHost"]["modelVersion"] is None


# ---------------------------------------------------------------------------
# Backup mechanism
# ---------------------------------------------------------------------------


class TestBackup:
    def test_backup_created_on_second_save(self, store, sample_tree):
        store.save(sample_tree)
        assert not store.backup_path.is_file()

        # Second save should back up the first version.
        modified = {"vdcHost": {**sample_tree["vdcHost"], "name": "Updated Host"}}
        store.save(modified)
        assert store.backup_path.is_file()

        # Backup should contain the original data.
        with open(store.backup_path, encoding="utf-8") as fh:
            backup_data = yaml.safe_load(fh)
        assert backup_data["vdcHost"]["name"] == "Test Host"

    def test_backup_contains_previous_version(self, store, sample_tree):
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "V2"}})
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "V3"}})
        # Backup should be V2 (the version before the latest save)
        with open(store.backup_path, encoding="utf-8") as fh:
            backup_data = yaml.safe_load(fh)
        assert backup_data["vdcHost"]["name"] == "V2"


# ---------------------------------------------------------------------------
# Recovery from corrupt primary
# ---------------------------------------------------------------------------


class TestRecovery:
    def test_corrupt_primary_falls_back_to_backup(self, store, sample_tree):
        # Save twice to create a backup.
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "Latest"}})

        # Corrupt the primary file.
        store.path.write_text("{{{{not: valid: yaml::::", encoding="utf-8")

        # Load should fall back to backup.
        loaded = store.load()
        assert loaded is not None
        assert loaded["vdcHost"]["name"] == "Test Host"

    def test_missing_primary_falls_back_to_backup(self, store, sample_tree):
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "Latest"}})
        # Delete primary.
        store.path.unlink()

        loaded = store.load()
        assert loaded is not None
        assert loaded["vdcHost"]["name"] == "Test Host"

    def test_both_corrupt_returns_none(self, store, sample_tree):
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "Latest"}})
        store.path.write_text("corrupt!", encoding="utf-8")
        store.backup_path.write_text("also corrupt!", encoding="utf-8")

        assert store.load() is None

    def test_primary_restored_from_backup(self, store, sample_tree):
        """When loading from backup, the primary should be restored."""
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "Latest"}})
        store.path.unlink()

        store.load()  # should restore primary from backup

        assert store.path.is_file()
        with open(store.path, encoding="utf-8") as fh:
            restored = yaml.safe_load(fh)
        assert restored["vdcHost"]["name"] == "Test Host"

    def test_non_dict_primary_falls_back(self, store, sample_tree):
        """A YAML file that parses to a non-dict should be rejected."""
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "Latest"}})
        store.path.write_text("- just\n- a\n- list\n", encoding="utf-8")

        loaded = store.load()
        assert loaded is not None
        assert loaded["vdcHost"]["name"] == "Test Host"


# ---------------------------------------------------------------------------
# Atomic write safety
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_no_tmp_file_remains(self, store, sample_tree):
        store.save(sample_tree)
        tmp = store.path.with_suffix(store.path.suffix + ".tmp")
        assert not tmp.is_file()


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


class TestDirectoryCreation:
    def test_creates_parent_dirs(self, tmp_path, sample_tree):
        deep_path = tmp_path / "a" / "b" / "c" / "state.yaml"
        s = PropertyStore(deep_path)
        s.save(sample_tree)
        assert deep_path.is_file()


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Error-path coverage (T2)
# ---------------------------------------------------------------------------


class TestSaveErrorPaths:
    def test_backup_failure_does_not_abort_save(self, store, sample_tree):
        """A failed backup copy must be logged and ignored — save() continues."""
        store.save(sample_tree)  # create primary so backup is attempted next
        with patch(
            "pydsvdcapi.persistence.shutil.copy2", side_effect=OSError("disk full")
        ):
            store.save({"vdcHost": {"name": "V2"}})
        loaded = store.load()
        assert loaded is not None
        assert loaded["vdcHost"]["name"] == "V2"

    def test_tmp_write_failure_raises(self, store, sample_tree):
        """An OSError during yaml.dump must propagate out of save()."""
        with (
            patch("pydsvdcapi.persistence.yaml.dump", side_effect=OSError("no space")),
            pytest.raises(OSError),
        ):
            store.save(sample_tree)

    def test_atomic_replace_failure_raises(self, store, sample_tree):
        """An OSError from os.replace must propagate out of save()."""
        with (
            patch(
                "pydsvdcapi.persistence.os.replace", side_effect=OSError("cross-device")
            ),
            pytest.raises(OSError),
        ):
            store.save(sample_tree)


class TestLoadErrorPaths:
    def test_restore_copy_failure_still_returns_data(self, store, sample_tree):
        """When restoring primary from backup fails, load() still returns the data."""
        store.save(sample_tree)
        store.save({"vdcHost": {**sample_tree["vdcHost"], "name": "V2"}})
        store.path.unlink()  # remove primary to force backup fallback

        with patch(
            "pydsvdcapi.persistence.shutil.copy2", side_effect=OSError("disk full")
        ):
            loaded = store.load()

        assert loaded is not None
        assert loaded["vdcHost"]["name"] == "Test Host"
        assert not store.path.is_file()  # primary was not restored


class TestDelete:
    def test_delete_removes_files(self, store, sample_tree):
        store.save(sample_tree)
        store.save(sample_tree)  # creates backup
        store.delete()
        assert not store.path.exists()
        assert not store.backup_path.exists()

    def test_delete_when_nothing_exists(self, store):
        store.delete()  # should not raise

    def test_delete_continues_on_partial_failure(self, store, sample_tree):
        """delete() must not raise even if one file cannot be removed."""
        from pathlib import Path

        store.save(sample_tree)
        store.save(sample_tree)  # creates backup
        primary = store.path

        original_unlink = Path.unlink

        def conditional_unlink(self_path: Path, missing_ok: bool = False) -> None:
            if self_path == primary:
                raise OSError("locked")
            original_unlink(self_path, missing_ok=missing_ok)

        with patch.object(Path, "unlink", conditional_unlink):
            store.delete()  # must not raise

        # The backup was still deleted despite the primary failing.
        assert not store.backup_path.exists()


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr(self, store):
        r = repr(store)
        assert "PropertyStore" in r
        assert "state.yaml" in r
