"""Tests for the VdcConnection framing layer."""

import asyncio
import struct
from unittest.mock import patch

import pytest

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import MAX_MESSAGE_LENGTH, VdcConnection

# ---------------------------------------------------------------------------
# Helpers — in-memory streams for testing without real sockets
# ---------------------------------------------------------------------------


def _make_pair():
    """Create paired VdcConnections using in-memory streams.

    Returns (client_conn, server_conn) where data written by one can be
    read by the other.
    """
    # Build two independent (reader, writer) pairs wired back-to-back.
    client_reader = asyncio.StreamReader()
    server_reader = asyncio.StreamReader()

    # We use a simple mock for StreamWriter that feeds data into the
    # peer's StreamReader.
    class MockWriter:
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

    client_writer = MockWriter(server_reader)
    client_writer._extra["peername"] = ("127.0.0.1", 12345)

    server_writer = MockWriter(client_reader)
    server_writer._extra["peername"] = ("127.0.0.1", 54321)

    client_conn = VdcConnection(client_reader, client_writer)  # type: ignore[arg-type]
    server_conn = VdcConnection(server_reader, server_writer)  # type: ignore[arg-type]
    return client_conn, server_conn


# ---------------------------------------------------------------------------
# Framing round-trip
# ---------------------------------------------------------------------------


class TestFramingRoundtrip:
    @pytest.mark.asyncio
    async def test_send_receive_hello_request(self):
        client, server = _make_pair()

        msg = pb.Message()
        msg.type = pb.VDSM_REQUEST_HELLO
        msg.message_id = 1
        msg.vdsm_request_hello.dSUID = "A" * 34
        msg.vdsm_request_hello.api_version = 2

        await client.send(msg)
        received = await server.receive()

        assert received is not None
        assert received.type == pb.VDSM_REQUEST_HELLO
        assert received.message_id == 1
        assert received.vdsm_request_hello.dSUID == "A" * 34
        assert received.vdsm_request_hello.api_version == 2

    @pytest.mark.asyncio
    async def test_send_receive_generic_response(self):
        client, server = _make_pair()

        msg = pb.Message()
        msg.type = pb.GENERIC_RESPONSE
        msg.message_id = 42
        msg.generic_response.code = pb.ERR_OK

        await client.send(msg)
        received = await server.receive()

        assert received is not None
        assert received.type == pb.GENERIC_RESPONSE
        assert received.generic_response.code == pb.ERR_OK

    @pytest.mark.asyncio
    async def test_bidirectional_communication(self):
        client, server = _make_pair()

        # Client → Server
        ping = pb.Message()
        ping.type = pb.VDSM_SEND_PING
        ping.vdsm_send_ping.dSUID = "B" * 34
        await client.send(ping)

        # Server reads ...
        received_ping = await server.receive()
        assert received_ping is not None
        assert received_ping.type == pb.VDSM_SEND_PING

        # Server → Client
        pong = pb.Message()
        pong.type = pb.VDC_SEND_PONG
        pong.vdc_send_pong.dSUID = "B" * 34
        await server.send(pong)

        received_pong = await client.receive()
        assert received_pong is not None
        assert received_pong.type == pb.VDC_SEND_PONG

    @pytest.mark.asyncio
    async def test_multiple_messages_in_sequence(self):
        client, server = _make_pair()

        for i in range(5):
            msg = pb.Message()
            msg.type = pb.VDSM_SEND_PING
            msg.message_id = i
            msg.vdsm_send_ping.dSUID = f"{i:034d}"
            await client.send(msg)

        for i in range(5):
            received = await server.receive()
            assert received is not None
            assert received.message_id == i


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_close_marks_connection(self):
        client, server = _make_pair()
        assert not client.is_closed
        await client.close()
        assert client.is_closed

    @pytest.mark.asyncio
    async def test_double_close_is_safe(self):
        client, _ = _make_pair()
        await client.close()
        await client.close()  # should not raise

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        client, _ = _make_pair()
        await client.close()

        msg = pb.Message()
        msg.type = pb.GENERIC_RESPONSE
        with pytest.raises(ConnectionError):
            await client.send(msg)

    @pytest.mark.asyncio
    async def test_receive_after_close_raises(self):
        client, _ = _make_pair()
        await client.close()

        with pytest.raises(ConnectionError):
            await client.receive()

    @pytest.mark.asyncio
    async def test_eof_returns_none(self):
        """When the remote end closes, receive returns None (via IncompleteReadError)."""
        client, server = _make_pair()
        await client.close()  # sends EOF to server's reader

        with pytest.raises(asyncio.IncompleteReadError):
            await server.receive()

    @pytest.mark.asyncio
    async def test_send_oversized_payload_raises(self):
        """send() must raise ValueError when the serialized payload exceeds MAX_MESSAGE_LENGTH."""
        client, _ = _make_pair()
        msg = pb.Message()
        msg.type = pb.VDSM_SEND_PING
        # Patch the module constant so any non-empty message is "too large".
        with patch("pydsvdcapi.connection.MAX_MESSAGE_LENGTH", 0):
            with pytest.raises(ValueError, match="too large"):
                await client.send(msg)

    @pytest.mark.asyncio
    async def test_receive_zero_length_header_raises(self):
        """A received header with length == 0 should raise ValueError."""
        _, server = _make_pair()
        server._reader.feed_data(struct.pack("!H", 0))
        with pytest.raises(ValueError, match="zero-length"):
            await server.receive()

    @pytest.mark.asyncio
    async def test_close_swallows_feed_eof_exception(self):
        """close() must not propagate exceptions from feed_eof()."""
        _, server = _make_pair()
        with patch.object(server._reader, "feed_eof", side_effect=RuntimeError("eof failed")):
            await server.close()  # must not raise
        assert server.is_closed

    @pytest.mark.asyncio
    async def test_close_swallows_wait_closed_exception(self):
        """close() must not propagate exceptions from wait_closed()."""
        _, server = _make_pair()
        with patch.object(server._writer, "wait_closed", side_effect=OSError("broken")):
            await server.close()  # must not raise
        assert server.is_closed

    @pytest.mark.asyncio
    async def test_oversized_header_rejected(self):
        """A received length header > MAX_MESSAGE_LENGTH should raise."""
        _, server = _make_pair()

        # Feed an invalid header: length = MAX_MESSAGE_LENGTH + 1
        bad_length = MAX_MESSAGE_LENGTH + 1
        header = struct.pack("!H", bad_length)
        server._reader.feed_data(header)
        server._reader.feed_data(b"\x00" * bad_length)

        with pytest.raises(ValueError, match="exceeds maximum"):
            await server.receive()


# ---------------------------------------------------------------------------
# Corrupt protobuf payload (T5)
# ---------------------------------------------------------------------------


class TestCorruptProtobuf:
    @pytest.mark.asyncio
    async def test_receive_corrupt_protobuf_raises_value_error(self):
        """receive() must raise ValueError when the protobuf payload cannot be parsed."""
        _, server = _make_pair()
        corrupt_payload = b"\xff\xfe\xfd\xfc\xfb\xfa\xf9\xf8\xf7\xf6"
        server._reader.feed_data(struct.pack("!H", len(corrupt_payload)) + corrupt_payload)
        with pytest.raises(ValueError, match="Failed to parse protobuf"):
            await server.receive()


# ---------------------------------------------------------------------------
# repr / peername
# ---------------------------------------------------------------------------


class TestRepr:
    @pytest.mark.asyncio
    async def test_repr_shows_state(self):
        client, _ = _make_pair()
        assert "open" in repr(client)
        await client.close()
        assert "closed" in repr(client)

    @pytest.mark.asyncio
    async def test_peername(self):
        client, server = _make_pair()
        assert "12345" in client.peername
        assert "54321" in server.peername
