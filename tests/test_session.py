"""Tests for the VdcSession protocol state machine."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import VdcConnection
from pydsvdcapi.session import SessionState, VdcSession

HOST_DSUID = "198C033E330755E78015F97AD093DD1C00"
VDSM_DSUID = "AABBCCDDEEFF00112233445566778899AA"


# ---------------------------------------------------------------------------
# Helpers — in-memory paired connections
# ---------------------------------------------------------------------------


class MockWriter:
    """Minimal StreamWriter mock that feeds data to a paired reader."""

    def __init__(self, peer_reader):
        self._peer = peer_reader
        self._closed = False
        self._extra = {}

    def write(self, data):
        self._peer.feed_data(data)

    async def drain(self):
        pass

    def close(self):
        self._closed = True
        self._peer.feed_eof()

    async def wait_closed(self):
        pass

    def get_extra_info(self, key, default=None):
        return self._extra.get(key, default)


def _make_pair():
    """Create (vdsm_conn, vdc_conn) — data flows vdsm→vdc and vdc→vdsm."""
    vdsm_reader = asyncio.StreamReader()
    vdc_reader = asyncio.StreamReader()

    vdsm_writer = MockWriter(vdc_reader)
    vdsm_writer._extra["peername"] = ("127.0.0.1", 11111)

    vdc_writer = MockWriter(vdsm_reader)
    vdc_writer._extra["peername"] = ("127.0.0.1", 22222)

    vdsm_conn = VdcConnection(vdsm_reader, vdsm_writer)  # type: ignore[arg-type]
    vdc_conn = VdcConnection(vdc_reader, vdc_writer)  # type: ignore[arg-type]
    return vdsm_conn, vdc_conn


def _hello_msg(dsuid=VDSM_DSUID, api_version=2, msg_id=1):
    """Build a hello request message."""
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_HELLO
    msg.message_id = msg_id
    msg.vdsm_request_hello.dSUID = dsuid
    msg.vdsm_request_hello.api_version = api_version
    return msg


def _ping_msg(dsuid=HOST_DSUID):
    """Build a ping message."""
    msg = pb.Message()
    msg.type = pb.VDSM_SEND_PING
    msg.vdsm_send_ping.dSUID = dsuid
    return msg


def _bye_msg(msg_id=2):
    """Build a bye message."""
    msg = pb.Message()
    msg.type = pb.VDSM_SEND_BYE
    msg.message_id = msg_id
    return msg


def _generic_response(msg_id, code=pb.ERR_OK):
    """Build a GenericResponse (simulates vdSM response to vDC request)."""
    msg = pb.Message()
    msg.type = pb.GENERIC_RESPONSE
    msg.message_id = msg_id
    msg.generic_response.code = code
    return msg


# ---------------------------------------------------------------------------
# Hello handshake
# ---------------------------------------------------------------------------


class TestHello:
    @pytest.mark.asyncio
    async def test_successful_hello(self):
        """A valid hello should transition the session to ACTIVE and
        return the vDC host's dSUID."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        # Send hello and immediately close (EOF) so session.run() ends.
        await vdsm.send(_hello_msg())
        vdsm._writer.close()

        await session.run()

        assert session.vdsm_dsuid == VDSM_DSUID
        assert session.api_version == 2

    @pytest.mark.asyncio
    async def test_hello_response_contains_host_dsuid(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        vdsm._writer.close()

        # Run session in a task so we can read the response.
        task = asyncio.create_task(session.run())

        response = await vdsm.receive()
        assert response is not None
        assert response.type == pb.VDC_RESPONSE_HELLO
        assert response.vdc_response_hello.dSUID == HOST_DSUID
        assert response.message_id == 1  # same as request

        await task

    @pytest.mark.asyncio
    async def test_incompatible_api_version(self):
        """API version < SUPPORTED should be rejected."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(api_version=1))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        response = await vdsm.receive()
        assert response is not None
        assert response.type == pb.GENERIC_RESPONSE
        assert response.generic_response.code == pb.ERR_INCOMPATIBLE_API

        await task
        assert session.state is SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_re_hello_resets_session(self):
        """A second hello on the same connection resets the session."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        # First hello.
        await vdsm.send(_hello_msg(msg_id=1))
        # Second hello with different dsuid.
        new_dsuid = "1122334455667788990011223344556677"
        await vdsm.send(_hello_msg(dsuid=new_dsuid, msg_id=2))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        # Read both responses.
        r1 = await vdsm.receive()
        r2 = await vdsm.receive()
        assert r1 is not None
        assert r2 is not None
        assert r1.type == pb.VDC_RESPONSE_HELLO
        assert r2.type == pb.VDC_RESPONSE_HELLO
        assert r2.message_id == 2

        await task
        # Session should reflect the second hello.
        assert session.vdsm_dsuid == new_dsuid

    @pytest.mark.asyncio
    async def test_on_hello_callback_is_invoked(self):
        """The on_hello callback should fire after a successful hello."""
        vdsm, vdc = _make_pair()
        called = asyncio.Event()

        async def hello_cb(sess):
            called.set()

        session = VdcSession(vdc, HOST_DSUID, on_hello=hello_cb)

        await vdsm.send(_hello_msg())
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        # The callback is scheduled via create_task, give it a moment.
        await asyncio.wait_for(called.wait(), timeout=2.0)
        assert called.is_set()

        await task

    @pytest.mark.asyncio
    async def test_on_hello_callback_not_called_on_incompatible_api(self):
        """on_hello should NOT be called when hello is rejected."""
        vdsm, vdc = _make_pair()
        called = False

        async def hello_cb(sess):
            nonlocal called
            called = True

        session = VdcSession(vdc, HOST_DSUID, on_hello=hello_cb)

        await vdsm.send(_hello_msg(api_version=1))
        vdsm._writer.close()

        await session.run()
        assert not called


# ---------------------------------------------------------------------------
# Ping / Pong
# ---------------------------------------------------------------------------


class TestPingPong:
    @pytest.mark.asyncio
    async def test_ping_receives_pong(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        await vdsm.send(_ping_msg(HOST_DSUID))
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        # Read hello response.
        hello_resp = await vdsm.receive()
        assert hello_resp is not None
        assert hello_resp.type == pb.VDC_RESPONSE_HELLO

        # Read pong.
        pong = await vdsm.receive()
        assert pong is not None
        assert pong.type == pb.VDC_SEND_PONG
        assert pong.vdc_send_pong.dSUID == HOST_DSUID

        await task

    @pytest.mark.asyncio
    async def test_ping_before_hello_rejected(self):
        """Ping before hello should get an error response."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_ping_msg())
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        error = await vdsm.receive()
        assert error is not None
        assert error.type == pb.GENERIC_RESPONSE
        assert error.generic_response.code == pb.ERR_SERVICE_NOT_AVAILABLE

        await task

    @pytest.mark.asyncio
    async def test_multiple_pings(self):
        """Multiple pings should each get a pong."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        for _ in range(3):
            await vdsm.send(_ping_msg())
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        # Hello response.
        await vdsm.receive()

        # 3 pongs.
        for _ in range(3):
            pong = await vdsm.receive()
            assert pong is not None
            assert pong.type == pb.VDC_SEND_PONG

        await task


# ---------------------------------------------------------------------------
# Bye
# ---------------------------------------------------------------------------


class TestBye:
    @pytest.mark.asyncio
    async def test_bye_acknowledged(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        await vdsm.send(_bye_msg(msg_id=5))
        # Don't close the writer — bye should terminate the session.

        task = asyncio.create_task(session.run())

        # Hello response.
        hello_resp = await vdsm.receive()
        assert hello_resp is not None
        assert hello_resp.type == pb.VDC_RESPONSE_HELLO

        # Bye acknowledgement.
        bye_resp = await vdsm.receive()
        assert bye_resp is not None
        assert bye_resp.type == pb.GENERIC_RESPONSE
        assert bye_resp.generic_response.code == pb.ERR_OK
        assert bye_resp.message_id == 5

        await task
        assert session.state is SessionState.CLOSED


# ---------------------------------------------------------------------------
# Message callback
# ---------------------------------------------------------------------------


class TestMessageCallback:
    @pytest.mark.asyncio
    async def test_callback_invoked_for_unhandled_messages(self):
        """Messages that are not hello/ping/bye should be forwarded to
        the on_message callback."""
        received_messages = []

        async def handler(session, msg):
            received_messages.append(msg.type)
            return None

        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID, on_message=handler)

        await vdsm.send(_hello_msg())
        # Send a getProperty request (which the session doesn't handle
        # internally).
        gp = pb.Message()
        gp.type = pb.VDSM_REQUEST_GET_PROPERTY
        gp.message_id = 10
        gp.vdsm_request_get_property.dSUID = HOST_DSUID
        await vdsm.send(gp)
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        # Read hello response.
        await vdsm.receive()
        await task

        assert pb.VDSM_REQUEST_GET_PROPERTY in received_messages

    @pytest.mark.asyncio
    async def test_callback_response_sent_back(self):
        """If the callback returns a Message, it should be sent."""

        async def handler(session, msg):
            resp = pb.Message()
            resp.type = pb.GENERIC_RESPONSE
            resp.message_id = msg.message_id
            resp.generic_response.code = pb.ERR_OK
            return resp

        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID, on_message=handler)

        await vdsm.send(_hello_msg())
        sp = pb.Message()
        sp.type = pb.VDSM_REQUEST_SET_PROPERTY
        sp.message_id = 20
        sp.vdsm_request_set_property.dSUID = HOST_DSUID
        await vdsm.send(sp)
        vdsm._writer.close()

        task = asyncio.create_task(session.run())

        # Hello response.
        await vdsm.receive()
        # Handler response.
        resp = await vdsm.receive()
        assert resp is not None
        assert resp.type == pb.GENERIC_RESPONSE
        assert resp.message_id == 20
        assert resp.generic_response.code == pb.ERR_OK

        await task


# ---------------------------------------------------------------------------
# Connection loss
# ---------------------------------------------------------------------------


class TestConnectionLoss:
    @pytest.mark.asyncio
    async def test_eof_ends_session(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        task = asyncio.create_task(session.run())

        # Read hello response.
        await vdsm.receive()

        # Close the connection.
        vdsm._writer.close()
        await task

        assert session.state is SessionState.CLOSED


# ---------------------------------------------------------------------------
# send_message (outbound from vDC host)
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_during_active_session(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())

        task = asyncio.create_task(session.run())
        # Read hello response.
        await vdsm.receive()

        # Now send a message from the vDC host side.
        announce = pb.Message()
        announce.type = pb.VDC_SEND_ANNOUNCE_VDC
        announce.vdc_send_announce_vdc.dSUID = "C" * 34
        await session.send_message(announce)

        received = await vdsm.receive()
        assert received is not None
        assert received.type == pb.VDC_SEND_ANNOUNCE_VDC
        assert received.vdc_send_announce_vdc.dSUID == "C" * 34

        # Clean up.
        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_message_before_active_raises(self):
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PONG
        with pytest.raises(ConnectionError, match="AWAITING_HELLO"):
            await session.send_message(msg)


# ---------------------------------------------------------------------------
# Session close
# ---------------------------------------------------------------------------


class TestSessionClose:
    @pytest.mark.asyncio
    async def test_close_terminates_session(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response

        await session.close()
        await task
        assert session.state is SessionState.CLOSED


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------


class TestSessionRepr:
    @pytest.mark.asyncio
    async def test_repr_before_hello(self):
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        r = repr(session)
        assert "AWAITING_HELLO" in r

    @pytest.mark.asyncio
    async def test_repr_after_hello(self):
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg())
        vdsm._writer.close()

        await session.run()
        assert "CLOSED" in repr(session)


# ---------------------------------------------------------------------------
# Message ID tracking
# ---------------------------------------------------------------------------


class TestMessageIdTracking:
    @pytest.mark.asyncio
    async def test_hello_updates_last_known_id(self):
        """Receiving a hello with msg_id=1 should set last_known to 1."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        assert session.last_known_message_id == 0

        await vdsm.send(_hello_msg(msg_id=5))
        vdsm._writer.close()

        await session.run()
        assert session.last_known_message_id == 5

    @pytest.mark.asyncio
    async def test_last_known_tracks_max_received(self):
        """last_known_message_id should track the max of all received IDs."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=3))
        # Send a getProperty with higher msg_id.
        gp = pb.Message()
        gp.type = pb.VDSM_REQUEST_GET_PROPERTY
        gp.message_id = 10
        gp.vdsm_request_get_property.dSUID = HOST_DSUID
        await vdsm.send(gp)
        # Then a bye with lower msg_id — should NOT decrease.
        await vdsm.send(_bye_msg(msg_id=7))

        task = asyncio.create_task(session.run())
        # Consume responses.
        await vdsm.receive()  # hello response
        await task

        assert session.last_known_message_id == 10

    @pytest.mark.asyncio
    async def test_notifications_have_zero_id(self):
        """Notifications (like ping, with default msg_id=0) should not
        increase the counter."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        await vdsm.send(_ping_msg())
        vdsm._writer.close()

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello
        await vdsm.receive()  # pong
        await task

        # Only the hello's msg_id should be tracked.
        assert session.last_known_message_id == 1


# ---------------------------------------------------------------------------
# send_request (outgoing request with auto message ID)
# ---------------------------------------------------------------------------


class TestSendRequest:
    @pytest.mark.asyncio
    async def test_send_request_assigns_next_id(self):
        """send_request should assign last_known + 1 as message_id."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))

        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response

        # Now send_request from the vDC host side.
        announce = pb.Message()
        announce.type = pb.VDC_SEND_ANNOUNCE_VDC
        announce.vdc_send_announce_vdc.dSUID = "C" * 34

        async def send_and_respond():
            req_task = asyncio.create_task(session.send_request(announce, timeout=2.0))
            # Read what was sent.
            received = await vdsm.receive()
            assert received is not None
            assert received.type == pb.VDC_SEND_ANNOUNCE_VDC
            assert received.message_id == 2  # last_known was 1 → next == 2

            # Send back a GenericResponse with the same ID.
            await vdsm.send(_generic_response(received.message_id))

            resp = await req_task
            assert resp.type == pb.GENERIC_RESPONSE
            assert resp.generic_response.code == pb.ERR_OK

        await send_and_respond()

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_request_increments_per_call(self):
        """Each send_request should use a monotonically increasing ID."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response

        ids_seen = []

        async def do_request():
            msg = pb.Message()
            msg.type = pb.VDC_SEND_ANNOUNCE_DEVICE
            msg.vdc_send_announce_device.dSUID = "D" * 34
            req_task = asyncio.create_task(session.send_request(msg, timeout=2.0))
            received = await vdsm.receive()
            assert received is not None
            ids_seen.append(received.message_id)
            await vdsm.send(_generic_response(received.message_id))
            await req_task

        await do_request()
        await do_request()
        await do_request()

        assert ids_seen == [2, 3, 4]

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_request_id_after_high_incoming_id(self):
        """If vdSM sends msg_id=50, next outgoing request should be 51."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=50))
        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello response

        announce = pb.Message()
        announce.type = pb.VDC_SEND_ANNOUNCE_VDC
        announce.vdc_send_announce_vdc.dSUID = "E" * 34

        req_task = asyncio.create_task(session.send_request(announce, timeout=2.0))
        received = await vdsm.receive()
        assert received is not None
        assert received.message_id == 51

        await vdsm.send(_generic_response(51))
        await req_task

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_request_timeout(self):
        """send_request should raise TimeoutError if no response."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()  # hello

        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_VDC
        msg.vdc_send_announce_vdc.dSUID = "F" * 34

        with pytest.raises(asyncio.TimeoutError):
            await session.send_request(msg, timeout=0.05)

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_request_before_active_raises(self):
        """send_request before hello should raise ConnectionError."""
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_VDC
        with pytest.raises(ConnectionError, match="AWAITING_HELLO"):
            await session.send_request(msg)

    @pytest.mark.asyncio
    async def test_send_request_cleans_up_on_timeout(self):
        """After timeout, pending request should be cleaned up."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_VDC
        msg.vdc_send_announce_vdc.dSUID = "G" * 34

        with pytest.raises(asyncio.TimeoutError):
            await session.send_request(msg, timeout=0.05)

        # Pending request should be cleaned up.
        assert len(session._pending_requests) == 0

        vdsm._writer.close()
        await task


# ---------------------------------------------------------------------------
# send_notification (outgoing with message_id = 0)
# ---------------------------------------------------------------------------


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_send_notification_sets_zero_id(self):
        """send_notification should set message_id to 0."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        push = pb.Message()
        push.type = pb.VDC_SEND_PUSH_NOTIFICATION
        push.vdc_send_push_notification.dSUID = HOST_DSUID

        await session.send_notification(push)

        received = await vdsm.receive()
        assert received is not None
        assert received.type == pb.VDC_SEND_PUSH_NOTIFICATION
        assert received.message_id == 0

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_send_notification_before_active_raises(self):
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        with pytest.raises(ConnectionError, match="AWAITING_HELLO"):
            await session.send_notification(msg)


# ---------------------------------------------------------------------------
# GENERIC_RESPONSE correlation
# ---------------------------------------------------------------------------


class TestResponseCorrelation:
    @pytest.mark.asyncio
    async def test_response_matched_to_pending_request(self):
        """A GENERIC_RESPONSE with matching msg_id resolves the future."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        announce = pb.Message()
        announce.type = pb.VDC_SEND_ANNOUNCE_VDC
        announce.vdc_send_announce_vdc.dSUID = "A" * 34

        req_task = asyncio.create_task(session.send_request(announce, timeout=2.0))
        outgoing = await vdsm.receive()
        assert outgoing is not None

        # Simulate vdSM responding.
        await vdsm.send(_generic_response(outgoing.message_id, pb.ERR_OK))
        resp = await req_task

        assert resp.generic_response.code == pb.ERR_OK
        assert len(session._pending_requests) == 0

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_error_response_forwarded_correctly(self):
        """An error GENERIC_RESPONSE should still resolve the future."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        announce = pb.Message()
        announce.type = pb.VDC_SEND_ANNOUNCE_DEVICE
        announce.vdc_send_announce_device.dSUID = "B" * 34

        req_task = asyncio.create_task(session.send_request(announce, timeout=2.0))
        outgoing = await vdsm.receive()
        assert outgoing is not None
        await vdsm.send(
            _generic_response(outgoing.message_id, pb.ERR_INSUFFICIENT_STORAGE)
        )
        resp = await req_task

        assert resp.generic_response.code == pb.ERR_INSUFFICIENT_STORAGE

        vdsm._writer.close()
        await task

    @pytest.mark.asyncio
    async def test_unmatched_generic_response_forwarded_to_callback(self):
        """A GENERIC_RESPONSE whose msg_id doesn't match any pending
        request should go to the on_message callback."""
        forwarded = []

        async def handler(session, msg):
            forwarded.append(msg)
            return None

        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID, on_message=handler)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        # Send a GENERIC_RESPONSE with an ID that has no pending request.
        await vdsm.send(_generic_response(999))
        # Give event loop time to process.
        await asyncio.sleep(0.01)

        vdsm._writer.close()
        await task

        assert len(forwarded) == 1
        assert forwarded[0].type == pb.GENERIC_RESPONSE
        assert forwarded[0].message_id == 999

    @pytest.mark.asyncio
    async def test_close_cancels_pending_requests(self):
        """Closing the session should cancel all pending request futures."""
        vdsm, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        await vdsm.send(_hello_msg(msg_id=1))
        task = asyncio.create_task(session.run())
        await vdsm.receive()

        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_VDC
        msg.vdc_send_announce_vdc.dSUID = "X" * 34

        req_task = asyncio.create_task(session.send_request(msg, timeout=5.0))
        # Let the request be sent.
        await vdsm.receive()

        # Close the session — should cancel the pending future.
        await session.close()
        await task

        with pytest.raises((asyncio.CancelledError, ConnectionError)):
            await req_task


# ---------------------------------------------------------------------------
# disconnect_reason attribute
# ---------------------------------------------------------------------------


class TestDisconnectReason:
    async def test_disconnect_reason_initially_none(self):
        """disconnect_reason must be None before the session runs."""
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)
        assert session.disconnect_reason is None

    async def test_disconnect_reason_set_on_connection_error(self):
        """ConnectionError during receive should be stored as disconnect_reason."""
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        exc = ConnectionResetError("connection reset by peer")
        with patch.object(vdc, "receive", new_callable=AsyncMock, side_effect=exc):
            await session.run()

        assert isinstance(session.disconnect_reason, ConnectionResetError)
        assert session.disconnect_reason is exc

    async def test_disconnect_reason_set_on_incomplete_read(self):
        """asyncio.IncompleteReadError during receive should be stored as disconnect_reason."""
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        exc = asyncio.IncompleteReadError(b"", 2)
        with patch.object(vdc, "receive", new_callable=AsyncMock, side_effect=exc):
            await session.run()

        assert isinstance(session.disconnect_reason, asyncio.IncompleteReadError)
        assert session.disconnect_reason is exc

    async def test_disconnect_reason_none_on_clean_eof(self):
        """Clean EOF (receive returns None) must leave disconnect_reason as None."""
        _, vdc = _make_pair()
        session = VdcSession(vdc, HOST_DSUID)

        # Simulate receive() returning None — the clean-EOF code path.
        with patch.object(vdc, "receive", new_callable=AsyncMock, return_value=None):
            await session.run()

        assert session.disconnect_reason is None
