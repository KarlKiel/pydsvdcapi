"""Tests for the VdcHost class."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.enums import ColorGroup
from pydsvdcapi.session import VdcSession
from pydsvdcapi.vdc import Vdc
from pydsvdcapi.vdc_host import (
    DEFAULT_VDC_PORT,
    VDC_SERVICE_TYPE,
    VdcHost,
)
from pydsvdcapi.vdsd import Device, Vdsd

# ---------------------------------------------------------------------------
# A fixed MAC for deterministic tests
# ---------------------------------------------------------------------------
TEST_MAC = "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_port(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.port == DEFAULT_VDC_PORT
        assert host.port == 8444

    def test_custom_port(self):
        host = VdcHost(mac=TEST_MAC, port=9999)
        assert host.port == 9999

    def test_entity_type(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.entity_type == "vDChost"

    def test_mac_stored(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.mac == TEST_MAC

    def test_default_name(self):
        host = VdcHost(mac=TEST_MAC)
        assert "vDC host on" in host.name

    def test_custom_name(self):
        host = VdcHost(mac=TEST_MAC, name="My Gateway")
        assert host.name == "My Gateway"

    def test_default_model(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.model == "pydsvdcapi vDC host"

    def test_custom_model(self):
        host = VdcHost(mac=TEST_MAC, model="Custom Model")
        assert host.model == "Custom Model"


# ---------------------------------------------------------------------------
# dSUID derivation
# ---------------------------------------------------------------------------


class TestDsuidDerivation:
    def test_dsuid_derived_from_mac(self):
        host = VdcHost(mac=TEST_MAC)
        expected = DsUid.from_vdc_mac(TEST_MAC)
        assert host.dsuid == expected

    def test_dsuid_deterministic(self):
        h1 = VdcHost(mac=TEST_MAC)
        h2 = VdcHost(mac=TEST_MAC)
        assert h1.dsuid == h2.dsuid

    def test_different_mac_different_dsuid(self):
        h1 = VdcHost(mac="11:22:33:44:55:66")
        h2 = VdcHost(mac="AA:BB:CC:DD:EE:FF")
        assert h1.dsuid != h2.dsuid

    def test_explicit_dsuid_overrides(self):
        custom = DsUid.random()
        host = VdcHost(mac=TEST_MAC, dsuid=custom)
        assert host.dsuid == custom

    def test_dsuid_string_is_34_hex(self):
        host = VdcHost(mac=TEST_MAC)
        assert len(str(host.dsuid)) == 34


# ---------------------------------------------------------------------------
# Auto-derived properties
# ---------------------------------------------------------------------------


class TestDerivedProperties:
    def test_hardware_guid_from_mac(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.hardware_guid == f"macaddress:{TEST_MAC}"

    def test_hardware_guid_explicit(self):
        host = VdcHost(mac=TEST_MAC, hardware_guid="uuid:test-1234")
        assert host.hardware_guid == "uuid:test-1234"

    def test_display_id_matches_dsuid(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.display_id == str(host.dsuid)

    def test_model_uid_deterministic(self):
        h1 = VdcHost(mac=TEST_MAC, model="TestModel")
        h2 = VdcHost(mac=TEST_MAC, model="TestModel")
        assert h1.model_uid == h2.model_uid

    def test_model_uid_differs_for_different_models(self):
        h1 = VdcHost(mac=TEST_MAC, model="ModelA")
        h2 = VdcHost(mac=TEST_MAC, model="ModelB")
        assert h1.model_uid != h2.model_uid

    def test_model_uid_explicit(self):
        host = VdcHost(mac=TEST_MAC, model_uid="custom-uid")
        assert host.model_uid == "custom-uid"


# ---------------------------------------------------------------------------
# Optional properties
# ---------------------------------------------------------------------------


class TestOptionalProperties:
    def test_optional_fields_default_none(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.model_version is None
        assert host.hardware_version is None
        assert host.hardware_model_guid is None
        assert host.vendor_name is None
        assert host.vendor_guid is None
        assert host.oem_guid is None
        assert host.oem_model_guid is None
        assert host.config_url is None
        assert host.device_icon_16 is None
        assert host.device_icon_name is None

    def test_optional_fields_set(self):
        host = VdcHost(
            mac=TEST_MAC,
            model_version="1.2.3",
            hardware_version="rev-B",
            vendor_name="TestCorp",
            config_url="http://192.168.1.1/config",
        )
        assert host.model_version == "1.2.3"
        assert host.hardware_version == "rev-B"
        assert host.vendor_name == "TestCorp"
        assert host.config_url == "http://192.168.1.1/config"


# ---------------------------------------------------------------------------
# Active state
# ---------------------------------------------------------------------------


class TestActiveState:
    def test_default_active(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.active is True

    def test_set_inactive(self):
        host = VdcHost(mac=TEST_MAC)
        host.active = False
        assert host.active is False


# ---------------------------------------------------------------------------
# get_properties()
# ---------------------------------------------------------------------------


class TestGetProperties:
    def test_returns_dict(self):
        host = VdcHost(mac=TEST_MAC, name="Test")
        props = host.get_properties()
        assert isinstance(props, dict)

    def test_contains_required_keys(self):
        host = VdcHost(mac=TEST_MAC)
        props = host.get_properties()
        required = {
            "dSUID",
            "displayId",
            "type",
            "model",
            "name",
            "active",
        }
        assert required.issubset(props.keys())

    def test_type_is_vdchost(self):
        host = VdcHost(mac=TEST_MAC)
        assert host.get_properties()["type"] == "vDChost"

    def test_dsuid_in_properties(self):
        host = VdcHost(mac=TEST_MAC)
        props = host.get_properties()
        assert props["dSUID"] == str(host.dsuid)

    def test_name_in_properties(self):
        host = VdcHost(mac=TEST_MAC, name="PropTest")
        assert host.get_properties()["name"] == "PropTest"


# ---------------------------------------------------------------------------
# Auto-detection of MAC (no MAC given)
# ---------------------------------------------------------------------------


class TestAutoMac:
    def test_auto_mac_produces_valid_dsuid(self):
        """When no MAC is given, the host should still produce a valid
        dSUID from the auto-detected MAC."""
        host = VdcHost()
        assert len(str(host.dsuid)) == 34
        assert host.mac  # non-empty


# ---------------------------------------------------------------------------
# DNS-SD announcement (mocked zeroconf)
# ---------------------------------------------------------------------------


class TestAnnouncement:
    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_announce_registers_service(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC)
        await host.announce()

        assert host.is_announced
        mock_zc.async_register_service.assert_called_once()

        # Inspect the ServiceInfo that was registered
        call_args = mock_zc.async_register_service.call_args
        info = call_args[0][0]
        assert info.type == VDC_SERVICE_TYPE
        assert info.port == DEFAULT_VDC_PORT

        await host.unannounce()

    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_announce_twice_is_noop(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC)
        await host.announce()
        await host.announce()  # second call should be a no-op

        assert MockAsyncZC.call_count == 1
        assert mock_zc.async_register_service.call_count == 1

        await host.unannounce()

    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_unannounce(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC)
        await host.announce()
        await host.unannounce()

        assert not host.is_announced
        mock_zc.async_unregister_service.assert_called_once()
        mock_zc.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_unannounce_without_announce_is_noop(self):
        host = VdcHost(mac=TEST_MAC)
        await host.unannounce()  # should not raise
        assert not host.is_announced

    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_service_contains_dsuid_txt(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC)
        await host.announce()

        info = mock_zc.async_register_service.call_args[0][0]
        # ServiceInfo properties should include the dSUID
        assert info.properties[b"dSUID"] == str(host.dsuid).encode("utf-8")

        await host.unannounce()

    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_custom_port_in_announcement(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC, port=9999)
        await host.announce()

        info = mock_zc.async_register_service.call_args[0][0]
        assert info.port == 9999

        await host.unannounce()

    @pytest.mark.asyncio
    @patch("pydsvdcapi.vdc_host.VdcHost._evict_stale_vdc_entries", new=AsyncMock())
    @patch("pydsvdcapi.vdc_host.AsyncZeroconf")
    async def test_service_name_uses_host_name(self, MockAsyncZC):
        mock_zc = MagicMock()
        mock_zc.async_register_service = AsyncMock()
        mock_zc.async_unregister_service = AsyncMock()
        mock_zc.async_close = AsyncMock()
        MockAsyncZC.return_value = mock_zc

        host = VdcHost(mac=TEST_MAC, name="My Custom Host")
        await host.announce()

        info = mock_zc.async_register_service.call_args[0][0]
        assert info.name.startswith("My Custom Host on ")

        await host.unannounce()


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_contains_key_info(self):
        host = VdcHost(mac=TEST_MAC, name="TestHost")
        r = repr(host)
        assert "VdcHost" in r
        assert "TestHost" in r
        assert str(host.port) in r


# ---------------------------------------------------------------------------
# remove handler (§6.3)
# ---------------------------------------------------------------------------


def _make_host_with_device():
    """Create a host → vdc → device → vdsd stack for remove tests."""
    host = VdcHost(mac=TEST_MAC, name="Remove Test Host")
    host._cancel_auto_save()
    vdc = Vdc(
        host=host,
        implementation_id="x-test-remove",
        name="Remove vDC",
        model="RM v1",
    )
    base = DsUid.from_name_in_space("remove-test", DsUidNamespace.VDC)
    device = Device(vdc=vdc, dsuid=base)
    vdsd = Vdsd(
        device=device,
        primary_group=ColorGroup.YELLOW,
        name="RemoveDev",
        model="Test vdSD",
    )
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    host.add_vdc(vdc)
    return host, vdc, device, vdsd


def _make_remove_msg(dsuid_str: str, msg_id: int = 42) -> pb.Message:
    """Build a VDSM_SEND_REMOVE protobuf message."""
    msg = pb.Message()
    msg.type = pb.VDSM_SEND_REMOVE
    msg.message_id = msg_id
    msg.vdsm_send_remove.dSUID = dsuid_str
    return msg


class TestHandleRemove:
    """Tests for VdcHost._handle_remove (§6.3)."""

    @pytest.mark.asyncio
    async def test_remove_success_default(self):
        """Without on_remove callback, removal is accepted."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)
        msg = _make_remove_msg(dsuid_str)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_OK
        assert resp.message_id == 42
        # Device should be gone from the vDC.
        assert vdc.get_device(vdsd.dsuid) is None

    @pytest.mark.asyncio
    async def test_remove_not_found(self):
        """Removing an unknown dSUID returns ERR_NOT_FOUND."""
        host, _, _, _ = _make_host_with_device()
        fake_dsuid = "00" * 17
        msg = _make_remove_msg(fake_dsuid)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_NOT_FOUND

    @pytest.mark.asyncio
    async def test_remove_callback_allows(self):
        """When on_remove returns True, removal proceeds."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)

        received_dsuids = []

        async def allow_remove(ds: str) -> bool:
            received_dsuids.append(ds)
            return True

        host._on_remove = allow_remove
        msg = _make_remove_msg(dsuid_str)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_OK
        assert dsuid_str in received_dsuids
        assert vdc.get_device(vdsd.dsuid) is None

    @pytest.mark.asyncio
    async def test_remove_callback_rejects(self):
        """When on_remove returns False, ERR_FORBIDDEN is returned."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)

        async def reject_remove(ds: str) -> bool:
            return False

        host._on_remove = reject_remove
        msg = _make_remove_msg(dsuid_str)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_FORBIDDEN
        # Device should still be present.
        assert vdc.get_device(vdsd.dsuid) is not None

    @pytest.mark.asyncio
    async def test_remove_callback_exception_rejects(self):
        """If on_remove raises, removal is rejected with ERR_FORBIDDEN."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)

        async def bad_callback(ds: str) -> bool:
            raise RuntimeError("oops")

        host._on_remove = bad_callback
        msg = _make_remove_msg(dsuid_str)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_FORBIDDEN
        # Device should still be present.
        assert vdc.get_device(vdsd.dsuid) is not None

    @pytest.mark.asyncio
    async def test_remove_lowercase_dsuid(self):
        """dSUID matching is case-insensitive."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid).lower()
        msg = _make_remove_msg(dsuid_str)

        resp = await host._handle_remove(msg)

        assert resp.generic_response.code == pb.ERR_OK

    @pytest.mark.asyncio
    async def test_remove_dispatch_integration(self):
        """VDSM_SEND_REMOVE is dispatched through _dispatch_message."""
        host, vdc, device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)
        msg = _make_remove_msg(dsuid_str)

        session = MagicMock(spec=VdcSession)
        session.is_active = True
        resp = await host._dispatch_message(session, msg)

        assert resp is not None
        assert resp.generic_response.code == pb.ERR_OK


# ---------------------------------------------------------------------------
# identify handler (§7.3.7 notification + §7.4.5 GenericRequest)
# ---------------------------------------------------------------------------


def _make_identify_notif_msg(
    *dsuid_strs: str,
) -> "pb.Message":
    """Build a VDSM_NOTIFICATION_IDENTIFY protobuf message."""
    msg = pb.Message()
    msg.type = pb.VDSM_NOTIFICATION_IDENTIFY
    for ds in dsuid_strs:
        msg.vdsm_send_identify.dSUID.append(ds)
    return msg


def _make_identify_generic_msg(
    dsuid_str: str,
    msg_id: int = 99,
) -> "pb.Message":
    """Build a GenericRequest 'identify' protobuf message."""
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
    msg.message_id = msg_id
    msg.vdsm_request_generic_request.methodname = "identify"
    msg.vdsm_request_generic_request.dSUID = dsuid_str
    return msg


class TestHandleIdentifyNotification:
    """Tests for VDSM_NOTIFICATION_IDENTIFY dispatch (§7.3.7)."""

    @pytest.mark.asyncio
    async def test_identify_invokes_callback(self):
        """identify notification calls Vdsd.identify()."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        cb = AsyncMock()
        vdsd.on_identify = cb

        msg = _make_identify_notif_msg(str(vdsd.dsuid))
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)

        cb.assert_awaited_once_with(vdsd)

    @pytest.mark.asyncio
    async def test_identify_unknown_dsuid_skipped(self):
        """identify for unknown dSUID is silently skipped."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        cb = AsyncMock()
        vdsd.on_identify = cb

        msg = _make_identify_notif_msg("00" * 17)
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)

        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_identify_no_callback_no_error(self):
        """identify without on_identify callback does not raise."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        assert vdsd.on_identify is None

        msg = _make_identify_notif_msg(str(vdsd.dsuid))
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)  # Should not raise

    @pytest.mark.asyncio
    async def test_identify_callback_exception_caught(self):
        """Exception in on_identify callback is caught, not propagated."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        cb = AsyncMock(side_effect=RuntimeError("boom"))
        vdsd.on_identify = cb

        msg = _make_identify_notif_msg(str(vdsd.dsuid))
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)  # Should not raise

        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_identify_multiple_dsuids(self):
        """identify notification with multiple dSUIDs calls each."""
        host = VdcHost(mac=TEST_MAC, name="Multi-ID Host")
        host._cancel_auto_save()
        vdc = Vdc(
            host=host,
            implementation_id="x-test-id",
            name="ID vDC",
            model="ID v1",
        )

        base1 = DsUid.from_name_in_space("id-test-1", DsUidNamespace.VDC)
        dev1 = Device(vdc=vdc, dsuid=base1)
        vdsd1 = Vdsd(
            device=dev1, primary_group=ColorGroup.YELLOW, name="Dev1", model="Test vdSD"
        )
        dev1.add_vdsd(vdsd1)
        vdc.add_device(dev1)

        base2 = DsUid.from_name_in_space("id-test-2", DsUidNamespace.VDC)
        dev2 = Device(vdc=vdc, dsuid=base2)
        vdsd2 = Vdsd(
            device=dev2, primary_group=ColorGroup.YELLOW, name="Dev2", model="Test vdSD"
        )
        dev2.add_vdsd(vdsd2)
        vdc.add_device(dev2)

        host.add_vdc(vdc)

        cb1 = AsyncMock()
        cb2 = AsyncMock()
        vdsd1.on_identify = cb1
        vdsd2.on_identify = cb2

        msg = _make_identify_notif_msg(str(vdsd1.dsuid), str(vdsd2.dsuid))
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)

        cb1.assert_awaited_once_with(vdsd1)
        cb2.assert_awaited_once_with(vdsd2)

    @pytest.mark.asyncio
    async def test_identify_sync_callback(self):
        """on_identify also works with a synchronous callback."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        called_with = []

        def sync_cb(v):
            called_with.append(v)

        vdsd.on_identify = sync_cb

        msg = _make_identify_notif_msg(str(vdsd.dsuid))
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        await host._dispatch_message(session, msg)

        assert called_with == [vdsd]


class TestHandleIdentifyGenericRequest:
    """Tests for GenericRequest 'identify' (§7.4.5)."""

    @pytest.mark.asyncio
    async def test_identify_generic_with_callback(self):
        """GenericRequest identify invokes on_identify callback."""
        host, _vdc, _device, _vdsd = _make_host_with_device()
        cb = AsyncMock()
        host._on_identify = cb

        vdc_dsuid = str(list(host._vdcs.values())[0].dsuid)
        msg = _make_identify_generic_msg(vdc_dsuid)
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK
        cb.assert_awaited_once_with(vdc_dsuid)

    @pytest.mark.asyncio
    async def test_identify_generic_no_callback(self):
        """GenericRequest identify without callback returns ERR_OK."""
        host, _vdc, _device, _vdsd = _make_host_with_device()
        assert host._on_identify is None

        vdc_dsuid = str(list(host._vdcs.values())[0].dsuid)
        msg = _make_identify_generic_msg(vdc_dsuid)
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK

    @pytest.mark.asyncio
    async def test_identify_generic_callback_exception(self):
        """GenericRequest identify with failing callback returns ERR_NOT_IMPLEMENTED."""
        host, _vdc, _device, _vdsd = _make_host_with_device()
        cb = AsyncMock(side_effect=RuntimeError("hardware fault"))
        host._on_identify = cb

        vdc_dsuid = str(list(host._vdcs.values())[0].dsuid)
        msg = _make_identify_generic_msg(vdc_dsuid)
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_NOT_IMPLEMENTED


# ---------------------------------------------------------------------------
# scanDevices handler (GenericRequest)
# ---------------------------------------------------------------------------


def _make_scan_devices_msg(
    dsuid_str: str, method: str = "scanDevices", msg_id: int = 55
) -> "pb.Message":
    """Build a GenericRequest 'scanDevices' protobuf message."""
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
    msg.message_id = msg_id
    msg.vdsm_request_generic_request.methodname = method
    msg.vdsm_request_generic_request.dSUID = dsuid_str
    return msg


def _make_ok_session() -> MagicMock:
    """Session mock whose send_request always returns ERR_OK."""
    ok_resp = pb.Message()
    ok_resp.generic_response.code = pb.ERR_OK
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_request = AsyncMock(return_value=ok_resp)
    return session


class TestHandleScanDevicesGenericRequest:
    """Tests for GenericRequest 'scanDevices' (and versioned variants).

    Re-announcement runs in a background asyncio task so that the OK
    response reaches dSS before any VDC_SEND_ANNOUNCE_* messages are
    sent (avoids a request/response deadlock).  Tests therefore call
    ``await asyncio.sleep(0)`` after dispatching to drain the task queue.
    """

    @pytest.mark.asyncio
    async def test_scan_devices_reannounces_vdc_and_devices(self):
        """scanDevices re-announces the addressed vDC and its device."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg(str(vdc.dsuid))
        resp = await host._dispatch_message(session, msg)
        await asyncio.sleep(0.05)  # let background re-announce task fully complete

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_versioned_method_name(self):
        """'scanDevices/6' is handled identically to 'scanDevices'."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg(str(vdc.dsuid), method="scanDevices/6")
        resp = await host._dispatch_message(session, msg)
        await asyncio.sleep(0.05)  # let background re-announce task fully complete

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_resets_announcement_flags(self):
        """scanDevices re-announces even if the vDC was already announced."""
        host, vdc, device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        # Pre-mark as announced — without reset_announcement() the handler
        # would skip devices (announce_devices only processes unannounced ones).
        vdc._announced = True
        device._announced = True

        msg = _make_scan_devices_msg(str(vdc.dsuid))
        resp = await host._dispatch_message(session, msg)
        await asyncio.sleep(0.05)  # let background re-announce task fully complete

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types
        # vDC should be re-marked announced after a successful re-announcement.
        assert vdc.is_announced is True

    @pytest.mark.asyncio
    async def test_scan_devices_host_dsuid_reannounces_all(self):
        """scanDevices with the host's own dSUID re-announces all vDCs."""
        host, _vdc, _device, _vdsd = _make_host_with_device()

        # Add a second vDC (no devices) to prove all vDCs are scanned.
        vdc2 = Vdc(
            host=host,
            implementation_id="x-test-scan-second",
            name="Second vDC",
            model="v2",
        )
        host.add_vdc(vdc2)

        session = _make_ok_session()
        msg = _make_scan_devices_msg(str(host.dsuid))
        resp = await host._dispatch_message(session, msg)
        await asyncio.sleep(0.05)  # let background re-announce task fully complete

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        vdc_announces = [t for t in sent_types if t == pb.VDC_SEND_ANNOUNCE_VDC]
        assert len(vdc_announces) == 2  # one per vDC
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_unknown_dsuid_returns_not_found(self):
        """scanDevices with an unknown dSUID returns ERR_NOT_FOUND."""
        host, _vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg("00" * 17)
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_NOT_FOUND
        session.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scan_devices_announce_failure_logged_not_propagated(self):
        """Announce errors in the background task are logged, not returned.

        scanDevices always returns ERR_OK immediately; any failure during
        the async re-announcement is only logged so the dSS side always
        gets a timely, successful response.
        """
        host, vdc, _device, _vdsd = _make_host_with_device()

        # Make send_request raise on the VDC_SEND_ANNOUNCE_VDC call.
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        session.send_request = AsyncMock(side_effect=ConnectionError("dropped"))

        msg = _make_scan_devices_msg(str(vdc.dsuid))
        resp = await host._dispatch_message(session, msg)
        await asyncio.sleep(0.05)  # let the background task fail

        # OK is returned regardless — the caller must not be blocked on errors.
        assert resp.generic_response.code == pb.ERR_OK


# ---------------------------------------------------------------------------
# _pending_vanish — persistence and flush infrastructure
# ---------------------------------------------------------------------------


class TestPendingVanishInfrastructure:
    """Tests for VdcHost._pending_vanish init, persistence, and flush."""

    def test_pending_vanish_empty_by_default(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        assert host._pending_vanish == set()

    def test_add_pending_vanish_updates_set(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._add_pending_vanish({"aabbcc", "ddeeff"})
        assert host._pending_vanish == {"aabbcc", "ddeeff"}

    def test_pending_vanish_serialised_in_property_tree(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"aabbcc"}
        tree = host.get_property_tree()
        assert "pendingVanish" in tree["vdcHost"]
        assert "aabbcc" in tree["vdcHost"]["pendingVanish"]

    def test_pending_vanish_omitted_when_empty(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        tree = host.get_property_tree()
        assert "pendingVanish" not in tree["vdcHost"]

    def test_apply_state_restores_pending_vanish(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._apply_state({"pendingVanish": ["aabbcc", "ddeeff"]})
        assert "aabbcc" in host._pending_vanish
        assert "ddeeff" in host._pending_vanish

    @pytest.mark.asyncio
    async def test_flush_sends_vanish_for_each_dsuid(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"aaaa", "bbbb"}

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        sent = {
            call.args[0].vdc_send_vanish.dSUID
            for call in session.send_notification.call_args_list
        }
        assert sent == {"aaaa", "bbbb"}

    @pytest.mark.asyncio
    async def test_flush_clears_pending_vanish(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        host._pending_vanish = {"cccc"}

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        assert host._pending_vanish == set()

    @pytest.mark.asyncio
    async def test_flush_noop_when_empty(self):
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()

        session = MagicMock(spec=VdcSession)
        session.send_notification = AsyncMock()

        await host._flush_pending_vanish(session)

        session.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_session_ready_flushes_pending_vanish(self):
        """_on_session_ready must send pending vanishes before announcing."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        host._pending_vanish = {"stale-dsuid"}

        ok_resp = pb.Message()
        ok_resp.generic_response.code = pb.ERR_OK
        session = MagicMock(spec=VdcSession)
        session.is_active = True
        session.send_notification = AsyncMock()
        session.send_request = AsyncMock(return_value=ok_resp)

        await host._on_session_ready(session)

        vanished = {
            call.args[0].vdc_send_vanish.dSUID
            for call in session.send_notification.call_args_list
            if call.args[0].type == pb.VDC_SEND_VANISH
        }
        assert "stale-dsuid" in vanished
        assert host._pending_vanish == set()


# ---------------------------------------------------------------------------
# _pending_vanish — wiring through remove_vdc / remove_device
# ---------------------------------------------------------------------------


class TestPendingVanishWiring:
    """Tests that remove_vdc and remove_device populate _pending_vanish."""

    def test_remove_vdc_adds_vdc_dsuid_to_pending_vanish(self):
        host, vdc, _device, _vdsd = _make_host_with_device()
        vdc_dsuid = str(vdc.dsuid)

        host.remove_vdc(vdc.dsuid)

        assert vdc_dsuid in host._pending_vanish

    def test_remove_vdc_adds_vdsd_dsuids_to_pending_vanish(self):
        host, vdc, _device, vdsd = _make_host_with_device()
        vdsd_dsuid = str(vdsd.dsuid)

        host.remove_vdc(vdc.dsuid)

        assert vdsd_dsuid in host._pending_vanish

    def test_remove_device_adds_vdsd_dsuids_to_pending_vanish(self):
        host, vdc, device, vdsd = _make_host_with_device()
        vdsd_dsuid = str(vdsd.dsuid)

        vdc.remove_device(device.dsuid)

        assert vdsd_dsuid in host._pending_vanish

    @pytest.mark.asyncio
    async def test_handle_remove_does_not_add_to_pending_vanish(self):
        """vdSM-initiated removal must NOT populate _pending_vanish."""
        host, _vdc, _device, vdsd = _make_host_with_device()
        dsuid_str = str(vdsd.dsuid)
        msg = _make_remove_msg(dsuid_str)

        await host._handle_remove(msg)

        assert host._pending_vanish == set()

    def test_remove_device_no_vdsds_does_not_add_to_pending_vanish(self):
        """Device with no vdsds: remove_device must not crash or pollute pending_vanish."""
        host = VdcHost(mac=TEST_MAC, name="PV Host")
        host._cancel_auto_save()
        vdc = Vdc(host=host, implementation_id="x-empty", name="Empty vDC", model="m")
        base = DsUid.from_name_in_space("empty-dev", DsUidNamespace.VDC)
        device = Device(vdc=vdc, dsuid=base)
        vdc.add_device(device)
        host.add_vdc(vdc)

        vdc.remove_device(device.dsuid)  # track_vanish=True, but device has no vdsds

        assert host._pending_vanish == set()
        assert vdc.get_device(device.dsuid) is None


class TestDisconnectCallback:
    """Tests for the on_disconnect callback mechanism."""

    def test_disconnect_callback_type_exists(self):
        from pydsvdcapi.vdc_host import DisconnectCallback
        assert DisconnectCallback is not None

    def test_stopping_flag_initially_false(self):
        host = VdcHost(mac=TEST_MAC)
        assert host._stopping is False

    def test_on_disconnect_initially_none(self):
        host = VdcHost(mac=TEST_MAC)
        assert host._on_disconnect is None

    @pytest.mark.asyncio
    async def test_start_accepts_on_disconnect(self):
        """on_disconnect parameter is accepted and stored."""
        host = VdcHost(mac=TEST_MAC, port=0)

        async def on_disc(h, exc):
            pass

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            await host.stop()

        assert host._on_disconnect is on_disc

    @pytest.mark.asyncio
    async def test_callback_fires_on_unexpected_disconnect(self):
        """Callback fires when session ends without stop() being called."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        err = ConnectionResetError("peer reset")
        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = err
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            await host._run_session(mock_session)
            await host.stop()

        assert len(fired) == 1
        assert fired[0][0] is host
        assert fired[0][1] is err

    @pytest.mark.asyncio
    async def test_callback_not_fired_when_stopping(self):
        """Callback must NOT fire when stop() initiated the disconnect."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = ConnectionResetError("peer reset")
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            host._stopping = True
            await host._run_session(mock_session)
            host._stopping = False
            await host.stop()

        assert fired == []

    @pytest.mark.asyncio
    async def test_callback_not_fired_when_no_callback_set(self):
        """No error when on_disconnect is None and session ends."""
        host = VdcHost(mac=TEST_MAC, port=0)

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = ConnectionResetError("peer reset")
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(announce=False)
            await host._run_session(mock_session)
            await host.stop()

    @pytest.mark.asyncio
    async def test_callback_receives_none_reason_on_clean_close(self):
        """Callback fires with None reason for clean EOF."""
        host = VdcHost(mac=TEST_MAC, port=0)
        fired: list[tuple] = []

        async def on_disc(h, exc):
            fired.append((h, exc))

        mock_session = MagicMock(spec=VdcSession)
        mock_session.run = AsyncMock(return_value=None)
        mock_session.disconnect_reason = None
        mock_session.vdsm_dsuid = "test-dsuid"

        with patch("pydsvdcapi.vdc_host.AsyncZeroconf"):
            await host.start(on_disconnect=on_disc, announce=False)
            await host._run_session(mock_session)
            await host.stop()

        assert len(fired) == 1
        assert fired[0][1] is None


class TestSetPropertyChannelStatesNumericKey:
    """setProperty channelStates with old-format numeric key updates the channel."""

    def _make_set_property_msg(
        self, dsuid_str: str, channel_key: str, value: float
    ):
        """Build a VDSM_REQUEST_SET_PROPERTY for channelStates with a numeric key."""
        from pydsvdcapi.vdcapi_pb2 import PropertyElement

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_SET_PROPERTY
        msg.message_id = 1
        msg.vdsm_request_set_property.dSUID = dsuid_str

        channel_states = PropertyElement()
        channel_states.name = "channelStates"

        channel_elem = PropertyElement()
        channel_elem.name = channel_key   # e.g. "1" (numeric channelType)

        value_elem = PropertyElement()
        value_elem.name = "value"
        value_elem.value.v_double = value
        channel_elem.elements.append(value_elem)
        channel_states.elements.append(channel_elem)
        msg.vdsm_request_set_property.properties.append(channel_states)
        return msg

    @pytest.mark.asyncio
    async def test_setproperty_channelstates_numeric_channeltype_key(self):
        """setProperty channelStates with key '1' (channelType=brightness) updates value."""
        from pydsvdcapi.enums import OutputFunction
        from pydsvdcapi.output import Output

        host = VdcHost(mac=TEST_MAC)
        vdc = Vdc(host=host, implementation_id="test-vdc", name="Test VDC", model="test-model")
        host.add_vdc(vdc)

        dsuid = DsUid.from_name_in_space("dev-numeric-key", DsUidNamespace.VDC)
        device = Device(vdc=vdc, dsuid=dsuid)
        vdsd = Vdsd(device=device, primary_group=ColorGroup.YELLOW, name="Dimmer", model="dimmer-model")
        device.add_vdsd(vdsd)
        vdc.add_device(device)

        output = Output(
            vdsd=vdsd,
            function=OutputFunction.DIMMER,
            name="brightness",
            default_group=1,
            active_group=1,
            groups={1},
        )
        channel_applied = AsyncMock()
        output.on_channel_applied = channel_applied
        vdsd.set_output(output)
        vdsd._is_announced = True  # simulate announced state

        dsuid_str = str(dsuid)
        msg = self._make_set_property_msg(dsuid_str, "1", 80.0)

        tasks = []
        original_create_task = asyncio.create_task

        def collect_task(coro):
            task = original_create_task(coro)
            tasks.append(task)
            return task

        with patch("pydsvdcapi.vdc_host.asyncio.create_task", side_effect=collect_task):
            host._handle_set_property(msg)

        if tasks:
            await asyncio.gather(*tasks)

        # channel_by_key("1") must resolve to the brightness channel
        brightness_ch = output.get_channel(0)
        assert brightness_ch is not None
        assert brightness_ch.name == "brightness"
        assert output.channel_by_key("1") is brightness_ch
        # The channel value must have been set to 80.0
        # (apply_pending_channels clears the dict after applying, so we check the actual value)
        assert brightness_ch.value == 80.0
