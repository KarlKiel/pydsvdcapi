"""Integration tests for VdcHost ↔ PropertyStore persistence."""

import yaml

from pydsvdcapi.vdc_host import VdcHost

TEST_MAC = "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Save & restore round-trip
# ---------------------------------------------------------------------------


class TestVdcHostPersistence:
    def test_save_creates_yaml(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="SaveTest")
        host.save()
        assert path.is_file()

    def test_yaml_contains_property_tree(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(mac=TEST_MAC, state_path=path, name="TreeTest")
        host.save()

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        assert "vdcHost" in data
        assert data["vdcHost"]["name"] == "TreeTest"
        assert data["vdcHost"]["dSUID"] == str(host.dsuid)
        assert data["vdcHost"]["mac"] == TEST_MAC
        assert data["vdcHost"]["port"] == 8444

    def test_restore_from_saved_state(self, tmp_path):
        path = tmp_path / "host.yaml"

        # Create and save a host with specific settings.
        original = VdcHost(
            mac=TEST_MAC,
            state_path=path,
            name="Original",
            model="Model-X",
            vendor_name="VendorCorp",
            port=9999,
        )
        original.save()

        # Create a new host from the same state file — should restore.
        restored = VdcHost(state_path=path)
        assert restored.name == "Original"
        assert restored.model == "Model-X"
        assert restored.vendor_name == "VendorCorp"
        assert str(restored.dsuid) == str(original.dsuid)
        assert restored.mac == TEST_MAC
        assert restored.port == 9999

    def test_explicit_params_override_persisted(self, tmp_path):
        path = tmp_path / "host.yaml"

        VdcHost(mac=TEST_MAC, state_path=path, name="Saved").save()

        # Explicit name should override persisted name.
        host = VdcHost(state_path=path, name="Override")
        assert host.name == "Override"

    def test_dsuid_stability_across_restarts(self, tmp_path):
        path = tmp_path / "host.yaml"

        h1 = VdcHost(mac=TEST_MAC, state_path=path)
        h1.save()
        dsuid1 = str(h1.dsuid)

        h2 = VdcHost(state_path=path)
        assert str(h2.dsuid) == dsuid1

    def test_save_without_state_path_is_noop(self):
        host = VdcHost(mac=TEST_MAC)
        host.save()  # should not raise

    def test_load_without_state_path_returns_false(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.load() is False


# ---------------------------------------------------------------------------
# Backup recovery through VdcHost
# ---------------------------------------------------------------------------


class TestVdcHostBackupRecovery:
    def test_corrupt_primary_recovers_from_backup(self, tmp_path):
        path = tmp_path / "host.yaml"

        # Save twice to create a backup.
        h1 = VdcHost(mac=TEST_MAC, state_path=path, name="V1")
        h1.save()
        h1.name = "V2"
        h1.save()

        # Corrupt primary.
        path.write_text("{{corrupt yaml", encoding="utf-8")

        # New host should recover from backup (V1).
        h2 = VdcHost(state_path=path)
        assert h2.name == "V1"

    def test_no_files_starts_fresh(self, tmp_path):
        path = tmp_path / "host.yaml"
        host = VdcHost(state_path=path)
        # Should get default values, not crash.
        assert "vDC host on" in host.name


# ---------------------------------------------------------------------------
# Property tree structure
# ---------------------------------------------------------------------------


class TestPropertyTree:
    def test_tree_is_nested_dict(self, tmp_path):
        host = VdcHost(mac=TEST_MAC, state_path=tmp_path / "h.yaml")
        tree = host.get_property_tree()
        assert isinstance(tree, dict)
        assert isinstance(tree["vdcHost"], dict)

    def test_tree_contains_all_common_props(self, tmp_path):
        host = VdcHost(
            mac=TEST_MAC,
            state_path=tmp_path / "h.yaml",
            name="TreeTest",
            model="M",
            model_version="1.0",
            vendor_name="V",
            config_url="http://test",
        )
        tree = host.get_property_tree()["vdcHost"]
        expected_keys = {
            "dSUID",
            "mac",
            "port",
            "name",
            "model",
            "modelVersion",
            "modelUID",
            "hardwareVersion",
            "hardwareGuid",
            "hardwareModelGuid",
            "vendorName",
            "vendorGuid",
            "oemGuid",
            "oemModelGuid",
            "configURL",
            "deviceIconName",
        }
        assert expected_keys.issubset(tree.keys())

    def test_tree_does_not_contain_binary_icon(self):
        """Binary data (deviceIcon16) is not in the tree — not YAML-safe."""
        host = VdcHost(mac=TEST_MAC, device_icon_16=b"\x89PNG")
        tree = host.get_property_tree()["vdcHost"]
        assert "deviceIcon16" not in tree


# ---------------------------------------------------------------------------
# Reload (load method on existing instance)
# ---------------------------------------------------------------------------


class TestReload:
    def test_load_updates_existing_host(self, tmp_path):
        path = tmp_path / "host.yaml"

        h1 = VdcHost(mac=TEST_MAC, state_path=path, name="Initial")
        h1.save()

        # Modify the file externally.
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data["vdcHost"]["name"] = "Modified"
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh)

        assert h1.load() is True
        assert h1.name == "Modified"
