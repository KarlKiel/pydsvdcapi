"""Tests for the DsUid class."""

import uuid

import pytest

from pydsvdcapi.dsuid import (
    DSUID_BYTES,
    DsUid,
    DsUidNamespace,
    DsUidType,
)

# ---------------------------------------------------------------------------
# Construction from string
# ---------------------------------------------------------------------------


class TestFromString:
    """Tests for DsUid.from_string()."""

    def test_34_hex_chars(self):
        s = "198C033E330755E78015F97AD093DD1C00"
        d = DsUid.from_string(s)
        assert str(d) == s
        assert len(d.raw) == DSUID_BYTES
        assert d.subdevice_index == 0x00

    def test_34_hex_lowercase(self):
        s = "198c033e330755e78015f97ad093dd1c00"
        d = DsUid.from_string(s)
        assert str(d) == s.upper()

    def test_subdevice_nonzero(self):
        s = "198C033E330755E78015F97AD093DD1C05"
        d = DsUid.from_string(s)
        assert d.subdevice_index == 0x05

    def test_uuid_with_dashes(self):
        uid = "198c033e-3307-55e7-8015-f97ad093dd1c"
        d = DsUid.from_string(uid)
        # sub-device index defaults to 0
        assert d.subdevice_index == 0
        assert d.id_type == DsUidType.UUID

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="length"):
            DsUid.from_string("AABB")

    def test_invalid_hex(self):
        with pytest.raises(ValueError, match="hex"):
            DsUid.from_string("ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ")


# ---------------------------------------------------------------------------
# Construction from bytes
# ---------------------------------------------------------------------------


class TestFromBytes:
    def test_roundtrip(self):
        original = bytes(range(17))
        d = DsUid.from_bytes(original)
        assert d.raw == original

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="17"):
            DsUid.from_bytes(b"\x00" * 10)


# ---------------------------------------------------------------------------
# Construction from UUID
# ---------------------------------------------------------------------------


class TestFromUuid:
    def test_from_uuid4(self):
        u = uuid.uuid4()
        d = DsUid.from_uuid(u)
        assert d.id_type == DsUidType.UUID
        assert d.base_bytes == u.bytes
        assert d.subdevice_index == 0

    def test_uuid_property_roundtrip(self):
        u = uuid.uuid4()
        d = DsUid.from_uuid(u, subdevice_index=3)
        assert d.uuid == u
        assert d.subdevice_index == 3

    def test_subdevice_index(self):
        u = uuid.uuid4()
        d = DsUid.from_uuid(u, subdevice_index=42)
        assert d.subdevice_index == 42


# ---------------------------------------------------------------------------
# Construction from name in namespace (UUIDv5)
# ---------------------------------------------------------------------------


class TestFromNameInSpace:
    def test_deterministic(self):
        d1 = DsUid.from_name_in_space("test", DsUidNamespace.ENOCEAN)
        d2 = DsUid.from_name_in_space("test", DsUidNamespace.ENOCEAN)
        assert d1 == d2

    def test_different_names_differ(self):
        d1 = DsUid.from_name_in_space("foo", DsUidNamespace.ENOCEAN)
        d2 = DsUid.from_name_in_space("bar", DsUidNamespace.ENOCEAN)
        assert d1 != d2

    def test_different_namespaces_differ(self):
        d1 = DsUid.from_name_in_space("same", DsUidNamespace.ENOCEAN)
        d2 = DsUid.from_name_in_space("same", DsUidNamespace.VDC)
        assert d1 != d2

    def test_uuid_version_and_variant(self):
        d = DsUid.from_name_in_space("check-v5", DsUidNamespace.GS1_128)
        # Version nibble (byte 6, upper 4 bits) must be 5
        assert (d.raw[6] >> 4) == 5
        # Variant (byte 8, top 2 bits) must be 0b10
        assert (d.raw[8] >> 6) == 0b10

    def test_matches_stdlib_uuid5(self):
        """Our UUIDv5 generation must produce the same result as
        ``uuid.uuid5()`` from the standard library."""
        ns = DsUidNamespace.ENOCEAN
        name = "verification-test"
        d = DsUid.from_name_in_space(name, ns)
        expected = uuid.uuid5(ns, name)
        assert d.base_bytes == expected.bytes


# ---------------------------------------------------------------------------
# Construction from GTIN + Serial (SGTIN-128 / method 2)
# ---------------------------------------------------------------------------


class TestFromGtinSerial:
    def test_deterministic(self):
        d1 = DsUid.from_gtin_serial("07640156791013", "12345")
        d2 = DsUid.from_gtin_serial("07640156791013", "12345")
        assert d1 == d2

    def test_is_uuid_type(self):
        d = DsUid.from_gtin_serial("07640156791013", "99")
        assert d.id_type == DsUidType.UUID

    def test_different_serials_differ(self):
        d1 = DsUid.from_gtin_serial("07640156791013", "1")
        d2 = DsUid.from_gtin_serial("07640156791013", "2")
        assert d1 != d2

    def test_matches_name_in_space_manually(self):
        """Should be equivalent to hashing the SGTIN-128 string in
        the GS1-128 namespace."""
        gtin, serial = "07640156791013", "42"
        d = DsUid.from_gtin_serial(gtin, serial)
        expected = DsUid.from_name_in_space(
            f"(01){gtin}(21){serial}", DsUidNamespace.GS1_128
        )
        assert d == expected


# ---------------------------------------------------------------------------
# Construction from SGTIN-96 (method 1)
# ---------------------------------------------------------------------------


class TestFromSgtin96:
    def test_header_byte(self):
        d = DsUid.from_sgtin96(gcp=123456, item_ref=1, partition=2, serial=1)
        assert d.raw[0] == 0x30

    def test_epc96_marker(self):
        """Bytes 6-9 must be zero for any EPC96-based dSUID."""
        d = DsUid.from_sgtin96(gcp=123456, item_ref=7, partition=2, serial=99)
        assert d.raw[6:10] == b"\x00\x00\x00\x00"

    def test_id_type_is_sgtin(self):
        d = DsUid.from_sgtin96(gcp=1, item_ref=0, partition=0, serial=0)
        assert d.id_type == DsUidType.SGTIN

    def test_invalid_partition(self):
        with pytest.raises(ValueError, match="Partition"):
            DsUid.from_sgtin96(gcp=1, item_ref=0, partition=7, serial=0)

    def test_invalid_serial(self):
        with pytest.raises(ValueError, match="(?i)serial"):
            DsUid.from_sgtin96(gcp=1, item_ref=0, partition=0, serial=2**38)

    def test_subdevice(self):
        d = DsUid.from_sgtin96(
            gcp=1, item_ref=0, partition=0, serial=0, subdevice_index=3
        )
        assert d.subdevice_index == 3


# ---------------------------------------------------------------------------
# Construction from GID-96 (legacy)
# ---------------------------------------------------------------------------


class TestFromGid96:
    def test_header_byte(self):
        d = DsUid.from_gid96(manager=0x04175FE, object_class=0, serial=0)
        assert d.raw[0] == 0x35

    def test_epc96_marker(self):
        d = DsUid.from_gid96(
            manager=0x04175FE, object_class=0xFF0000, serial=0x567890AB
        )
        assert d.raw[6:10] == b"\x00\x00\x00\x00"

    def test_id_type_is_gid(self):
        d = DsUid.from_gid96(manager=0x04175FE, object_class=0, serial=0)
        assert d.id_type == DsUidType.GID

    def test_mac_gid96_known_example(self):
        """Verify against the documented example:
        MAC 12:34:56:78:90:AB → dSID '3504175FEFF12340567890AB'
        (12-byte GID-96 representation)."""
        d = DsUid.from_mac_gid96("12:34:56:78:90:AB")
        # The documented 24-char dSID maps into our 34-char dSUID:
        # bytes 0-5 of epc + 0000 + bytes 6-11 of epc + subdevice 00
        dsid_hex = "3504175FEFF12340567890AB"
        epc_bytes = bytes.fromhex(dsid_hex)
        # Map to dSUID layout
        expected = bytearray(17)
        expected[0:6] = epc_bytes[0:6]
        expected[10:16] = epc_bytes[6:12]
        expected[16] = 0
        assert d.raw == bytes(expected)


# ---------------------------------------------------------------------------
# vDC MAC-based dSUID
# ---------------------------------------------------------------------------


class TestFromVdcMac:
    def test_is_uuid_type(self):
        d = DsUid.from_vdc_mac("AA:BB:CC:DD:EE:FF")
        assert d.id_type == DsUidType.UUID

    def test_deterministic(self):
        d1 = DsUid.from_vdc_mac("AA:BB:CC:DD:EE:FF")
        d2 = DsUid.from_vdc_mac("AA:BB:CC:DD:EE:FF")
        assert d1 == d2

    def test_mac_format_independence(self):
        """All common MAC notations must produce the same dSUID."""
        d1 = DsUid.from_vdc_mac("AA:BB:CC:DD:EE:FF")
        d2 = DsUid.from_vdc_mac("AA-BB-CC-DD-EE-FF")
        d3 = DsUid.from_vdc_mac("AABBCCDDEEFF")
        assert d1 == d2 == d3


# ---------------------------------------------------------------------------
# EnOcean
# ---------------------------------------------------------------------------


class TestFromEnocean:
    def test_deterministic(self):
        d1 = DsUid.from_enocean("0512ABCD")
        d2 = DsUid.from_enocean(0x0512ABCD)
        assert d1 == d2

    def test_is_uuid_type(self):
        d = DsUid.from_enocean(0x01020304)
        assert d.id_type == DsUidType.UUID


# ---------------------------------------------------------------------------
# Random (UUIDv4)
# ---------------------------------------------------------------------------


class TestRandom:
    def test_unique(self):
        d1 = DsUid.random()
        d2 = DsUid.random()
        assert d1 != d2

    def test_is_uuid_type(self):
        d = DsUid.random()
        assert d.id_type == DsUidType.UUID

    def test_length(self):
        d = DsUid.random()
        assert len(str(d)) == 34

    def test_subdevice(self):
        d = DsUid.random(subdevice_index=7)
        assert d.subdevice_index == 7


# ---------------------------------------------------------------------------
# Sub-device derivation
# ---------------------------------------------------------------------------


class TestDeriveSubdevice:
    def test_same_base(self):
        parent = DsUid.random()
        child = parent.derive_subdevice(5)
        assert parent.base_bytes == child.base_bytes
        assert child.subdevice_index == 5

    def test_parent_unchanged(self):
        parent = DsUid.random()
        original_str = str(parent)
        _ = parent.derive_subdevice(3)
        assert str(parent) == original_str


# ---------------------------------------------------------------------------
# same_device / device_base
# ---------------------------------------------------------------------------


class TestSameDevice:
    """Tests for DsUid.same_device() — §5.2 multi-vdSD grouping."""

    def test_same_device_derived(self):
        base = DsUid.random()
        d0 = base.derive_subdevice(0)
        d1 = base.derive_subdevice(1)
        d2 = base.derive_subdevice(2)
        assert d0.same_device(d1)
        assert d1.same_device(d2)
        assert d0.same_device(d2)

    def test_same_device_self(self):
        d = DsUid.random(subdevice_index=3)
        assert d.same_device(d)

    def test_not_same_device(self):
        d1 = DsUid.random()
        d2 = DsUid.random()
        assert not d1.same_device(d2)

    def test_same_device_sparse_enumeration(self):
        """§5.2 allows sparse enumeration (e.g. 0, 2 for dual rocker)."""
        base = DsUid.from_enocean("0512ABCD")
        rocker_a = base.derive_subdevice(0)
        rocker_b = base.derive_subdevice(2)
        assert rocker_a.same_device(rocker_b)
        assert rocker_a.subdevice_index == 0
        assert rocker_b.subdevice_index == 2

    def test_same_device_symmetry(self):
        base = DsUid.random()
        a = base.derive_subdevice(1)
        b = base.derive_subdevice(5)
        assert a.same_device(b) == b.same_device(a)


class TestDeviceBase:
    """Tests for DsUid.device_base() — canonical device key."""

    def test_device_base_index_zero(self):
        d = DsUid.random(subdevice_index=7)
        base = d.device_base()
        assert base.subdevice_index == 0
        assert d.same_device(base)

    def test_device_base_already_zero(self):
        d = DsUid.random(subdevice_index=0)
        base = d.device_base()
        assert base == d

    def test_device_base_as_grouping_key(self):
        """All siblings produce the same device_base() — usable as dict key."""
        parent = DsUid.from_enocean("AABBCCDD")
        siblings = [parent.derive_subdevice(i) for i in (0, 1, 2, 5)]
        bases = {s.device_base() for s in siblings}
        assert len(bases) == 1

    def test_device_base_preserves_type(self):
        d = DsUid.from_enocean("0512ABCD", subdevice_index=3)
        base = d.device_base()
        assert base.id_type == d.id_type


# ---------------------------------------------------------------------------
# Equality, hashing, ordering
# ---------------------------------------------------------------------------


class TestComparisons:
    def test_equal(self):
        s = "198C033E330755E78015F97AD093DD1C00"
        assert DsUid.from_string(s) == DsUid.from_string(s)

    def test_not_equal_different(self):
        d1 = DsUid.random()
        d2 = DsUid.random()
        assert d1 != d2

    def test_hashable(self):
        d = DsUid.random()
        s = {d}
        assert d in s

    def test_ordering(self):
        d1 = DsUid.from_string("00" * 17)
        d2 = DsUid.from_string("FF" * 17)
        assert d1 < d2
        assert d2 > d1

    def test_bool_true(self):
        d = DsUid.random()
        assert bool(d) is True

    def test_bool_false(self):
        d = DsUid()
        assert bool(d) is False


# ---------------------------------------------------------------------------
# repr / str
# ---------------------------------------------------------------------------


class TestRepr:
    def test_str_length(self):
        d = DsUid.random()
        assert len(str(d)) == 34

    def test_repr(self):
        d = DsUid.from_string("198C033E330755E78015F97AD093DD1C00")
        assert repr(d) == "DsUid('198C033E330755E78015F97AD093DD1C00')"
