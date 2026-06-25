"""dSUID - digitalSTROM Unique Identifier.

Implements the dSUID (136-bit unique identifier) as specified in the
digitalSTROM system documentation (ds-basics v1.6) and the vDC API.

A dSUID consists of 17 bytes (34 hex characters):
  - Bytes 0-15 (128 bits): Base identifier — either a UUID (RFC 4122)
    or an EPC96 (SGTIN-96/GID-96) mapped into 16 bytes.
  - Byte 16: Sub-device enumeration index within the same hardware.

Generation is governed by the following prioritised rules:
  1. SGTIN-96 is available → use it directly.
  2. GTIN + serial number → form SGTIN-128 string, generate UUIDv5
     in the GS1-128 namespace.
  3. An existing UUID is available → use it directly.
  4. Another unique ID is available → generate UUIDv5 in the
     relevant namespace (EnOcean, IEEE MAC, vDC, …).
  5. No unique ID available → generate random UUIDv4 (must be
     persisted by the caller).

Reference: ds-basics v1.6, vDC API specification.
"""

from __future__ import annotations

import hashlib
import uuid
from enum import IntEnum, unique

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DSUID_BYTES = 17  # Total bytes in a dSUID
UUID_BYTES = 16  # Bytes occupied by the UUID/EPC96 part

SGTIN96_HEADER = 0x30  # 8-bit header for SGTIN-96 encoded dSUIDs
GID96_HEADER = 0x35  # 8-bit header for GID-96 (legacy) encoded dSUIDs

# GCP bit-length lookup indexed by partition value (0-6).
# Partition value + 1 = number of decimal digits for item reference
# including indicator/pad digit.
_GCP_BIT_LENGTH = (40, 37, 34, 30, 27, 24, 20)


# ---------------------------------------------------------------------------
# Well-known namespace UUIDs  (from digitalSTROM system documentation)
# ---------------------------------------------------------------------------


class DsUidNamespace:
    """Pre-defined namespace UUIDs for UUIDv5-based dSUID generation."""

    #: For SGTIN-128 strings: ``"(01)<GTIN>(21)<serial>"``
    GS1_128 = uuid.UUID("8ca838d5-4c40-47cc-bafa-37ac89658962")

    #: For EnOcean device addresses
    ENOCEAN = uuid.UUID("0ba94a7b-7c92-4dab-b8e3-5fe09e83d0f3")

    #: For generating a vDC dSUID from the MAC address of the hardware
    VDC = uuid.UUID("9888dd3d-b345-4109-b088-2673306d0c65")

    #: For generating a vdSM dSUID from the MAC address of the hardware
    VDSM = uuid.UUID("195de5c0-902f-4b71-a706-b43b80765e3d")


# ---------------------------------------------------------------------------
# dSUID type enumeration
# ---------------------------------------------------------------------------


@unique
class DsUidType(IntEnum):
    """Type of the identifier encoded in a dSUID."""

    UNDEFINED = 0
    GID = 1  # Legacy GID-96 encoded within dSUID
    SGTIN = 2  # SGTIN-96 encoded within dSUID
    UUID = 3  # UUID (v1/v4/v5) encoded within dSUID
    OTHER = 4  # Not yet identified sub-type


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class DsUid:
    """A 17-byte digitalSTROM Unique Identifier.

    Instances are immutable value objects.  Once created they cannot be
    modified — use one of the class-method constructors to build new
    instances for each use-case.

    The canonical string representation is **34 upper-case hex characters**
    (e.g. ``"198C033E330755E78015F97AD093DD1C00"``).
    """

    __slots__ = ("_raw", "_id_type")

    # ---- construction helpers (private) -----------------------------------

    def __init__(self) -> None:  # noqa: D107
        self._raw = bytearray(DSUID_BYTES)
        self._id_type = DsUidType.UNDEFINED

    def _detect_subtype(self) -> None:
        """Detect whether the raw bytes represent SGTIN-96, GID-96 or UUID."""
        if (
            self._raw[6] == 0
            and self._raw[7] == 0
            and self._raw[8] == 0
            and self._raw[9] == 0
        ):
            # EPC96 — bytes 6-9 are zero
            if self._raw[0] == SGTIN96_HEADER:
                self._id_type = DsUidType.SGTIN
            elif self._raw[0] == GID96_HEADER:
                self._id_type = DsUidType.GID
            else:
                self._id_type = DsUidType.OTHER
        else:
            self._id_type = DsUidType.UUID

    # ---- public class-method constructors ---------------------------------

    @classmethod
    def from_string(cls, value: str) -> DsUid:
        """Create a :class:`DsUid` from its hex-string representation.

        Accepts 34 hex characters (full dSUID) or a standard UUID string
        with dashes (in which case the sub-device index defaults to 0).

        Parameters
        ----------
        value:
            ``"198C…1C00"`` (34 hex) or
            ``"198c033e-3307-55e7-8015-f97ad093dd1c"`` (UUID with dashes).

        Raises
        ------
        ValueError
            If *value* cannot be parsed as a valid dSUID.
        """
        obj = cls()
        cleaned = value.replace("-", "")

        if len(cleaned) not in (32, 34):
            raise ValueError(
                f"Invalid dSUID string length: expected 32 or 34 hex chars, "
                f"got {len(cleaned)} (from {value!r})"
            )

        try:
            raw_bytes = bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError(
                f"Invalid hex characters in dSUID string: {value!r}"
            ) from exc

        if len(raw_bytes) == UUID_BYTES:
            # Pure UUID (32 hex / with dashes) → sub-device index = 0
            obj._raw[:UUID_BYTES] = raw_bytes
            obj._raw[UUID_BYTES] = 0
        else:
            obj._raw[:] = raw_bytes

        obj._detect_subtype()
        return obj

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> DsUid:
        """Create a :class:`DsUid` from a 17-byte binary representation.

        Parameters
        ----------
        data:
            Exactly 17 bytes.

        Raises
        ------
        ValueError
            If *data* is not exactly 17 bytes long.
        """
        if len(data) != DSUID_BYTES:
            raise ValueError(f"Expected {DSUID_BYTES} bytes, got {len(data)}")
        obj = cls()
        obj._raw[:] = data
        obj._detect_subtype()
        return obj

    @classmethod
    def from_uuid(cls, value: uuid.UUID, subdevice_index: int = 0) -> DsUid:
        """Create a dSUID from an existing :class:`~uuid.UUID`.

        This is generation method **3** (existing UUID).

        Parameters
        ----------
        value:
            A UUID object (any version).
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        obj = cls()
        obj._raw[:UUID_BYTES] = value.bytes
        obj._raw[UUID_BYTES] = subdevice_index & 0xFF
        obj._id_type = DsUidType.UUID
        return obj

    @classmethod
    def from_name_in_space(
        cls,
        name: str,
        namespace: uuid.UUID,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a UUIDv5-based dSUID from a *name* in a *namespace*.

        This is generation method **4** (and also used internally by
        methods 2 and 5).

        The algorithm follows RFC 4122 §4.3:
          1. Concatenate the 16-byte namespace UUID (network byte order)
             with the UTF-8 encoded *name*.
          2. Compute SHA-1 over the concatenation.
          3. Copy bytes 0-15 of the digest into the UUID.
          4. Set version nibble to 5, variant bits to RFC 4122.

        Parameters
        ----------
        name:
            Arbitrary string that is unique within *namespace*.
        namespace:
            A :class:`~uuid.UUID` identifying the namespace
            (see :class:`DsUidNamespace` for well-known values).
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        obj = cls()

        sha1 = hashlib.sha1()
        sha1.update(namespace.bytes)
        sha1.update(name.encode("utf-8"))
        digest = sha1.digest()

        obj._raw[:UUID_BYTES] = bytearray(digest[:UUID_BYTES])
        # Version 5
        obj._raw[6] = (obj._raw[6] & 0x0F) | 0x50
        # Variant RFC 4122  (10xx xxxx)
        obj._raw[8] = (obj._raw[8] & 0x3F) | 0x80
        obj._raw[UUID_BYTES] = subdevice_index & 0xFF

        obj._id_type = DsUidType.UUID
        return obj

    @classmethod
    def from_gtin_serial(
        cls,
        gtin: str,
        serial: str,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a UUIDv5-based dSUID from a GTIN and serial number.

        This is generation method **2**: combine GTIN and serial into an
        SGTIN-128 string ``"(01)<GTIN>(21)<serial>"`` and hash it with
        UUIDv5 in the GS1-128 namespace.

        Parameters
        ----------
        gtin:
            The Global Trade Item Number (e.g. ``"07640156791013"``).
        serial:
            The serial number string.
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        sgtin128 = f"(01){gtin}(21){serial}"
        return cls.from_name_in_space(sgtin128, DsUidNamespace.GS1_128, subdevice_index)

    @classmethod
    def from_sgtin96(
        cls,
        gcp: int,
        item_ref: int,
        partition: int,
        serial: int,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a dSUID directly from SGTIN-96 components.

        This is generation method **1** (SGTIN-96 available).

        The 96-bit EPC is mapped into the 17-byte dSUID layout with
        bytes 6-9 set to zero (EPC96 marker).

        Parameters
        ----------
        gcp:
            GS1 Company Prefix (numeric).
        item_ref:
            Item Reference (numeric).
        partition:
            Partition value (0-6) that encodes the split between GCP
            length and item-reference length.
        serial:
            38-bit serial number.
        subdevice_index:
            Sub-device enumeration byte (0-255).

        Raises
        ------
        ValueError
            If *partition* is out of range or *serial* exceeds 38 bits.
        """
        if not 0 <= partition <= 6:
            raise ValueError(f"Partition must be 0-6, got {partition}")
        if serial < 0 or serial.bit_length() > 38:
            raise ValueError(
                f"Serial must be a positive integer fitting in 38 bits, got {serial}"
            )

        obj = cls()
        obj._raw[0] = SGTIN96_HEADER

        # Total combined GCP + ItemRef field is always 44 bits.
        gcp_bits = _GCP_BIT_LENGTH[partition]
        binary_gtin = (gcp << (44 - gcp_bits)) | item_ref

        # Byte 1: filter (3 bits, fixed=1) | partition (3 bits) |
        #          top 2 bits of binary_gtin
        obj._raw[1] = (
            (0x01 << 5) | ((partition & 0x07) << 2) | ((binary_gtin >> 42) & 0x03)
        )
        # Bytes 2-5: next 32 bits of binary_gtin
        obj._raw[2] = (binary_gtin >> 34) & 0xFF
        obj._raw[3] = (binary_gtin >> 26) & 0xFF
        obj._raw[4] = (binary_gtin >> 18) & 0xFF
        obj._raw[5] = (binary_gtin >> 10) & 0xFF

        # Bytes 6-9: zeros  (EPC96 marker — already zero from init)

        # Bytes 10-11: bottom 10 bits of GTIN + top 6 bits of serial
        obj._raw[10] = (binary_gtin >> 2) & 0xFF
        obj._raw[11] = ((binary_gtin & 0x03) << 6) | ((serial >> 32) & 0x3F)

        # Bytes 12-15: lower 32 bits of serial
        obj._raw[12] = (serial >> 24) & 0xFF
        obj._raw[13] = (serial >> 16) & 0xFF
        obj._raw[14] = (serial >> 8) & 0xFF
        obj._raw[15] = serial & 0xFF

        # Byte 16: sub-device index
        obj._raw[16] = subdevice_index & 0xFF

        obj._id_type = DsUidType.SGTIN
        return obj

    @classmethod
    def from_gid96(
        cls,
        manager: int,
        object_class: int,
        serial: int,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a dSUID from a legacy GID-96 identifier.

        The GID-96 is the legacy dSID format (EPCglobal).

        Layout (96 bits):
          - 8-bit header: ``0x35``
          - 28-bit manager number (e.g. ``0x04175FE`` for digitalSTROM)
          - 24-bit object class
          - 36-bit serial number

        The 96 bits are mapped into the 17-byte dSUID layout with
        bytes 6-9 set to zero.

        Parameters
        ----------
        manager:
            28-bit EPCglobal manager number.
        object_class:
            24-bit object class (0 = device, 1 = meter, etc.).
        serial:
            36-bit serial number.
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        obj = cls()
        obj._raw[0] = GID96_HEADER

        # Pack 28-bit manager + 24-bit object class + 36-bit serial
        # into bytes 1-5 and 10-15, leaving 6-9 = 0.
        #
        # Total: header(8) + manager(28) + object_class(24) + serial(36) = 96
        # Pack sequentially into 12 bytes, then map to dSUID layout.
        epc = bytearray(12)
        epc[0] = GID96_HEADER
        # manager (28 bits) -> bits 8..35
        epc[1] = (manager >> 20) & 0xFF
        epc[2] = (manager >> 12) & 0xFF
        epc[3] = (manager >> 4) & 0xFF
        # bottom 4 bits of manager + top 4 bits of object_class
        epc[4] = ((manager & 0x0F) << 4) | ((object_class >> 20) & 0x0F)
        epc[5] = (object_class >> 12) & 0xFF
        # bottom 12 bits of object_class + top 4 bits of serial
        epc[6] = (object_class >> 4) & 0xFF
        epc[7] = ((object_class & 0x0F) << 4) | ((serial >> 32) & 0x0F)
        epc[8] = (serial >> 24) & 0xFF
        epc[9] = (serial >> 16) & 0xFF
        epc[10] = (serial >> 8) & 0xFF
        epc[11] = serial & 0xFF

        # Map 12-byte EPC96 into 17-byte dSUID layout:
        # Bytes 0-5 = epc[0-5], Bytes 6-9 = 0, Bytes 10-15 = epc[6-11]
        obj._raw[0:6] = epc[0:6]
        # obj._raw[6:10] already zero
        obj._raw[10:16] = epc[6:12]
        obj._raw[16] = subdevice_index & 0xFF

        obj._id_type = DsUidType.GID
        return obj

    @classmethod
    def from_mac_gid96(
        cls,
        mac: str,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a legacy GID-96 dSUID from an Ethernet MAC address.

        Uses the digitalSTROM manager number ``0x04175FE`` and object
        class range ``0xFF0000..0xFFFFFF``, encoding the MAC into the
        object class and serial fields.

        Parameters
        ----------
        mac:
            MAC address string, e.g. ``"12:34:56:78:90:AB"`` or
            ``"12-34-56-78-90-AB"`` or ``"1234567890AB"``.
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        mac_bytes = _parse_mac(mac)
        # Object class: 0xFF followed by first 2 bytes of MAC
        object_class = 0xFF0000 | (mac_bytes[0] << 8) | mac_bytes[1]
        # Serial: remaining 4 bytes of MAC (as 36-bit, upper 4 bits zero)
        serial = (
            (mac_bytes[2] << 24)
            | (mac_bytes[3] << 16)
            | (mac_bytes[4] << 8)
            | mac_bytes[5]
        )
        return cls.from_gid96(
            manager=0x04175FE,
            object_class=object_class,
            serial=serial,
            subdevice_index=subdevice_index,
        )

    @classmethod
    def from_vdc_mac(
        cls,
        mac: str,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a vDC dSUID from the hardware's MAC address.

        Uses UUIDv5 hashing with the well-known vDC namespace.

        Parameters
        ----------
        mac:
            MAC address string (any common format).
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        mac_normalised = _normalise_mac(mac)
        return cls.from_name_in_space(
            mac_normalised, DsUidNamespace.VDC, subdevice_index
        )

    @classmethod
    def from_enocean(
        cls,
        address: str | int,
        subdevice_index: int = 0,
    ) -> DsUid:
        """Create a dSUID for an EnOcean device.

        Uses UUIDv5 hashing with the well-known EnOcean namespace.

        Parameters
        ----------
        address:
            EnOcean 32-bit address as an integer or as an 8-character
            hex string (e.g. ``"0512ABCD"`` or ``0x0512ABCD``).
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        addr_str = f"{address:08X}" if isinstance(address, int) else address.upper()
        return cls.from_name_in_space(addr_str, DsUidNamespace.ENOCEAN, subdevice_index)

    @classmethod
    def random(cls, subdevice_index: int = 0) -> DsUid:
        """Create a random UUIDv4-based dSUID.

        This is generation method **5** (last resort).  The caller **must**
        persist the result so that it remains stable across restarts.

        Parameters
        ----------
        subdevice_index:
            Sub-device enumeration byte (0-255).
        """
        return cls.from_uuid(uuid.uuid4(), subdevice_index)

    # ---- sub-device derivation -------------------------------------------

    def derive_subdevice(self, subdevice_index: int) -> DsUid:
        """Return a new dSUID that shares the base identity but uses a
        different sub-device index (byte 17).

        This is the primary mechanism for representing **multiple vdSDs
        within a single physical device** (see vDC API §5.2).  All
        derived siblings share bytes 0-15 and differ only in byte 16.

        Parameters
        ----------
        subdevice_index:
            Enumeration byte for the sub-device (0-255).
        """
        obj = DsUid()
        obj._raw[:] = self._raw
        obj._raw[UUID_BYTES] = subdevice_index & 0xFF
        obj._id_type = self._id_type
        return obj

    def same_device(self, other: DsUid) -> bool:
        """Check whether *self* and *other* belong to the same hardware.

        Two dSUIDs belong to the same physical device when their first
        16 bytes (the base identity) are identical — only the sub-device
        enumeration byte (byte 17) may differ.  See vDC API §5.2.

        Parameters
        ----------
        other:
            Another :class:`DsUid` to compare against.
        """
        return self._raw[:UUID_BYTES] == other._raw[:UUID_BYTES]

    def device_base(self) -> DsUid:
        """Return the canonical *device-level* dSUID (sub-device index 0).

        This is useful as a dictionary/grouping key when you need to
        collect all vdSDs that belong to the same physical device.

        If *self* already has ``subdevice_index == 0`` a copy is still
        returned (dSUIDs are value objects).
        """
        return self.derive_subdevice(0)

    # ---- properties -------------------------------------------------------

    @property
    def id_type(self) -> DsUidType:
        """The type of identifier encoded in this dSUID."""
        return self._id_type

    @property
    def subdevice_index(self) -> int:
        """The sub-device enumeration index (byte 17)."""
        return self._raw[UUID_BYTES]

    @property
    def base_bytes(self) -> bytes:
        """The first 16 bytes (base identity, without sub-device index)."""
        return bytes(self._raw[:UUID_BYTES])

    @property
    def raw(self) -> bytes:
        """The full 17-byte binary representation (read-only copy)."""
        return bytes(self._raw)

    @property
    def uuid(self) -> uuid.UUID:
        """The base 16 bytes interpreted as a :class:`~uuid.UUID`.

        Raises
        ------
        ValueError
            If the dSUID is not UUID-based.
        """
        if self._id_type not in (DsUidType.UUID, DsUidType.OTHER):
            raise ValueError("Cannot interpret an EPC96-based dSUID as UUID")
        return uuid.UUID(bytes=self.base_bytes)

    @property
    def is_empty(self) -> bool:
        """``True`` if this dSUID has not been initialised."""
        return self._id_type == DsUidType.UNDEFINED

    # ---- string conversion ------------------------------------------------

    def __str__(self) -> str:
        """Return the canonical 34-character upper-case hex representation."""
        return self._raw.hex().upper()

    def __repr__(self) -> str:
        return f"DsUid('{self}')"

    # ---- equality and hashing ---------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DsUid):
            return self._raw == other._raw
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        if isinstance(other, DsUid):
            return self._raw != other._raw
        return NotImplemented

    def __lt__(self, other: DsUid) -> bool:
        if isinstance(other, DsUid):
            return self._raw < other._raw
        return NotImplemented

    def __le__(self, other: DsUid) -> bool:
        if isinstance(other, DsUid):
            return self._raw <= other._raw
        return NotImplemented

    def __gt__(self, other: DsUid) -> bool:
        if isinstance(other, DsUid):
            return self._raw > other._raw
        return NotImplemented

    def __ge__(self, other: DsUid) -> bool:
        if isinstance(other, DsUid):
            return self._raw >= other._raw
        return NotImplemented

    def __hash__(self) -> int:
        return hash(bytes(self._raw))

    def __bool__(self) -> bool:
        return not self.is_empty


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_mac(mac: str) -> bytes:
    """Parse a MAC address string into 6 bytes.

    Accepted formats:
      - ``"AA:BB:CC:DD:EE:FF"``
      - ``"AA-BB-CC-DD-EE-FF"``
      - ``"AABBCCDDEEFF"``
    """
    cleaned = mac.replace(":", "").replace("-", "")
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid MAC address: {mac!r}") from exc


def _normalise_mac(mac: str) -> str:
    """Return the upper-case colon-separated representation of *mac*."""
    b = _parse_mac(mac)
    return ":".join(f"{x:02X}" for x in b)
