"""Tests for VdcHost TCP server integration."""

import asyncio

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import VdcConnection
from pydsvdcapi.vdc_host import VdcHost

TEST_MAC = "AA:BB:CC:DD:EE:FF"
VDSM_DSUID = "AABBCCDDEEFF00112233445566778899AA"

# Bind to localhost only to avoid port-per-address-family issues with port=0.
BIND = "127.0.0.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _connect_to_host(host: VdcHost):
    """Open a raw TCP connection to a running VdcHost and wrap it."""
    reader, writer = await asyncio.open_connection(BIND, host.port)
    return VdcConnection(reader, writer)


def _hello_msg(dsuid=VDSM_DSUID, api_version=2, msg_id=1):
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_HELLO
    msg.message_id = msg_id
    msg.vdsm_request_hello.dSUID = dsuid
    msg.vdsm_request_hello.api_version = api_version
    return msg


def _ping_msg(dsuid=""):
    msg = pb.Message()
    msg.type = pb.VDSM_SEND_PING
    msg.vdsm_send_ping.dSUID = dsuid
    return msg


def _bye_msg(msg_id=2):
    msg = pb.Message()
    msg.type = pb.VDSM_SEND_BYE
    msg.message_id = msg_id
    return msg


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


class TestServerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)
        assert host.is_serving
        assert host.port != 0

        await host.stop()
        assert not host.is_serving

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)
        port = host.port
        await host.start(announce=False, bind_address=BIND)
        assert host.port == port
        await host.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        host = VdcHost(mac=TEST_MAC)
        await host.stop()  # should not raise


# ---------------------------------------------------------------------------
# Hello handshake via real TCP
# ---------------------------------------------------------------------------


class TestTcpHello:
    @pytest.mark.asyncio
    async def test_hello_over_tcp(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)

        try:
            conn = await _connect_to_host(host)
            await conn.send(_hello_msg())

            response = await conn.receive()
            assert response is not None
            assert response.type == pb.VDC_RESPONSE_HELLO
            assert response.vdc_response_hello.dSUID == str(host.dsuid)

            await conn.close()
            await asyncio.sleep(0.05)
        finally:
            await host.stop()

    @pytest.mark.asyncio
    async def test_session_established_after_hello(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)

        try:
            conn = await _connect_to_host(host)
            await conn.send(_hello_msg())
            await conn.receive()  # hello response

            await asyncio.sleep(0.05)
            assert host.session is not None
            assert host.session.vdsm_dsuid == VDSM_DSUID
            assert host.session.is_active

            await conn.close()
            await asyncio.sleep(0.05)
        finally:
            await host.stop()


# ---------------------------------------------------------------------------
# Ping / Pong via real TCP
# ---------------------------------------------------------------------------


class TestTcpPingPong:
    @pytest.mark.asyncio
    async def test_ping_pong_over_tcp(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)

        try:
            conn = await _connect_to_host(host)
            await conn.send(_hello_msg())
            await conn.receive()  # hello response

            target = str(host.dsuid)
            await conn.send(_ping_msg(target))
            pong = await conn.receive()
            assert pong is not None
            assert pong.type == pb.VDC_SEND_PONG
            assert pong.vdc_send_pong.dSUID == target

            await conn.close()
            await asyncio.sleep(0.05)
        finally:
            await host.stop()


# ---------------------------------------------------------------------------
# Bye via real TCP
# ---------------------------------------------------------------------------


class TestTcpBye:
    @pytest.mark.asyncio
    async def test_bye_over_tcp(self):
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)

        try:
            conn = await _connect_to_host(host)
            await conn.send(_hello_msg())
            await conn.receive()  # hello response

            await conn.send(_bye_msg(msg_id=99))
            resp = await conn.receive()
            assert resp is not None
            assert resp.type == pb.GENERIC_RESPONSE
            assert resp.generic_response.code == pb.ERR_OK
            assert resp.message_id == 99

            await asyncio.sleep(0.05)
            assert host.session is None  # session cleaned up

            await conn.close()
        finally:
            await host.stop()


# ---------------------------------------------------------------------------
# Message callback
# ---------------------------------------------------------------------------


class TestTcpCallback:
    @pytest.mark.asyncio
    async def test_on_message_callback(self):
        received = []

        async def handler(session, msg):
            received.append(msg.type)
            resp = pb.Message()
            resp.type = pb.GENERIC_RESPONSE
            resp.message_id = msg.message_id
            resp.generic_response.code = pb.ERR_OK
            return resp

        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, on_message=handler, bind_address=BIND)

        try:
            conn = await _connect_to_host(host)
            await conn.send(_hello_msg())
            await conn.receive()  # hello response

            # Use a generic request — a message type that is NOT
            # intercepted internally by VdcHost (GET_PROPERTY and
            # SET_PROPERTY are now handled by the property dispatch).
            gr = pb.Message()
            gr.type = pb.VDSM_REQUEST_GENERIC_REQUEST
            gr.message_id = 42
            gr.vdsm_request_generic_request.dSUID = str(host.dsuid)
            gr.vdsm_request_generic_request.methodname = "testMethod"
            await conn.send(gr)

            resp = await conn.receive()
            assert resp is not None
            assert resp.type == pb.GENERIC_RESPONSE
            assert resp.message_id == 42
            assert pb.VDSM_REQUEST_GENERIC_REQUEST in received

            await conn.close()
            await asyncio.sleep(0.05)
        finally:
            await host.stop()


# ---------------------------------------------------------------------------
# Connection replacement
# ---------------------------------------------------------------------------


class TestConnectionReplacement:
    @pytest.mark.asyncio
    async def test_new_connection_replaces_old(self):
        """A new TCP connection should close the old session."""
        host = VdcHost(mac=TEST_MAC, port=0)
        await host.start(announce=False, bind_address=BIND)

        try:
            # First connection.
            conn1 = await _connect_to_host(host)
            await conn1.send(_hello_msg(msg_id=1))
            await conn1.receive()  # hello response
            await asyncio.sleep(0.05)
            assert host.session is not None

            # Second connection -- should replace the first.
            conn2 = await _connect_to_host(host)
            await asyncio.sleep(0.05)

            await conn2.send(_hello_msg(dsuid="1" * 34, msg_id=2))
            resp = await conn2.receive()
            assert resp is not None
            assert resp.type == pb.VDC_RESPONSE_HELLO

            await asyncio.sleep(0.05)
            assert host.session is not None
            assert host.session.vdsm_dsuid == "1" * 34

            await conn2.close()
            await asyncio.sleep(0.05)
        finally:
            await host.stop()
