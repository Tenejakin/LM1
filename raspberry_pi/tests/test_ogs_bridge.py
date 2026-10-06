"""OpenGolfSim bridge: the app's WebSocket must reach OpenGolfSim's TCP 3111 API.

On 2026-09-25 the app timed out ("OpenGolfSim did not respond") against OpenGolfSim on an
iPad because no bridge was running. The Pi now bridges, and finds the iPad by scanning.
"""

import asyncio
import base64
import ipaddress
import json
import os
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ogs_bridge  # noqa: E402


def masked_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    first = (0x80 if fin else 0) | opcode
    if length < 126:
        header = struct.pack("!BB", first, 0x80 | length)
    else:
        header = struct.pack("!BBH", first, 0x80 | 126, length)
    return header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


async def read_server_frame(reader):
    first, second = await reader.readexactly(2)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", await reader.readexactly(2))
    return first & 0x0F, await reader.readexactly(length)


async def open_client(port: int):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(
        (
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    response = (await reader.readuntil(b"\r\n\r\n")).decode()
    assert response.startswith("HTTP/1.1 101"), response
    assert ogs_bridge.accept_key(key) in response
    return reader, writer


class FakeOgs:
    """Records lines it receives and answers every shot with a result, like OpenGolfSim."""

    def __init__(self):
        self.lines: list[dict] = []
        self.connections = 0
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        self.connections += 1
        while line := await reader.readline():
            message = json.loads(line)
            self.lines.append(message)
            if message.get("type") == "shot":
                writer.write(b'{"type":"result","data":{"result":{"carry":180.5,"total":195.0}}}\n')
                await writer.drain()
        writer.close()


class OgsBridgeTest(unittest.IsolatedAsyncioTestCase):
    def test_accept_key_matches_rfc6455_example(self):
        # A wrong GUID passed self-consistent tests but real clients rejected the handshake.
        self.assertEqual(ogs_bridge.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    async def start_bridge(self, bridge):
        server = await ogs_bridge.serve("127.0.0.1", 0, bridge)
        self.addAsyncCleanup(self._close, server)
        return server.sockets[0].getsockname()[1]

    async def _close(self, server):
        server.close()
        await server.wait_closed()

    async def test_forwards_shot_and_result(self):
        ogs = FakeOgs()
        ogs_port = await ogs.start()
        self.addAsyncCleanup(self._close, ogs.server)
        port = await self.start_bridge(ogs_bridge.Bridge("127.0.0.1", ogs_port, networks=lambda: []))
        reader, writer = await open_client(port)

        opcode, payload = await read_server_frame(reader)
        self.assertEqual(opcode, ogs_bridge.OP_TEXT)
        self.assertEqual(json.loads(payload)["status"], "connected")

        shot = {"type": "shot", "unit": "metric", "shot": {"ballSpeed": 44.7}}
        text = json.dumps(shot).encode()
        # Fragmented across two frames, plus a ping in between.
        writer.write(masked_frame(ogs_bridge.OP_TEXT, text[:10], fin=False))
        writer.write(masked_frame(ogs_bridge.OP_PING, b"hi"))
        writer.write(masked_frame(ogs_bridge.OP_CONTINUATION, text[10:]))
        await writer.drain()

        self.assertEqual(await read_server_frame(reader), (ogs_bridge.OP_PONG, b"hi"))
        opcode, payload = await asyncio.wait_for(read_server_frame(reader), 2)
        self.assertEqual(json.loads(payload)["data"]["result"]["carry"], 180.5)
        self.assertEqual(ogs.lines, [shot])
        writer.close()

    async def test_malformed_json_is_rejected_not_forwarded(self):
        ogs = FakeOgs()
        ogs_port = await ogs.start()
        self.addAsyncCleanup(self._close, ogs.server)
        port = await self.start_bridge(ogs_bridge.Bridge("127.0.0.1", ogs_port, networks=lambda: []))
        reader, writer = await open_client(port)
        await read_server_frame(reader)
        writer.write(masked_frame(ogs_bridge.OP_TEXT, b"not json"))
        await writer.drain()
        _, payload = await read_server_frame(reader)
        self.assertEqual(json.loads(payload)["status"], "error")
        self.assertEqual(ogs.lines, [])
        writer.close()

    async def test_discovers_ogs_when_configured_host_is_gone(self):
        ogs = FakeOgs()
        ogs_port = await ogs.start()
        self.addAsyncCleanup(self._close, ogs.server)
        # 127.0.0.2 does not listen; the scan of 127.0.0.0/30 finds 127.0.0.1.
        bridge = ogs_bridge.Bridge("127.0.0.2", ogs_port, networks=lambda: [ipaddress.ip_network("127.0.0.0/30")])
        port = await self.start_bridge(bridge)
        reader, writer = await open_client(port)
        _, payload = await read_server_frame(reader)
        message = json.loads(payload)
        self.assertEqual(message["status"], "connected")
        self.assertEqual(message["host"], "127.0.0.1")
        self.assertEqual(bridge.last_host, "127.0.0.1")
        # The scan's connection is reused: OpenGolfSim on iPad dropped a client that
        # connected right after a probe closed (2026-09-25).
        self.assertEqual(ogs.connections, 1)
        writer.close()

    async def test_reports_error_when_no_ogs(self):
        bridge = ogs_bridge.Bridge(None, 1, networks=lambda: [])
        port = await self.start_bridge(bridge)
        reader, writer = await open_client(port)
        opcode, payload = await read_server_frame(reader)
        message = json.loads(payload)
        self.assertEqual(message["status"], "error")
        self.assertIn("No OpenGolfSim found", message["message"])
        opcode, _ = await read_server_frame(reader)
        self.assertEqual(opcode, ogs_bridge.OP_CLOSE)
        writer.close()

    async def test_plain_http_gets_status_page(self):
        port = await self.start_bridge(ogs_bridge.Bridge("192.168.0.192", 3111, networks=lambda: []))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        response = (await reader.read()).decode()
        self.assertIn("426", response)
        self.assertIn("192.168.0.192:3111", response)
        writer.close()


if __name__ == "__main__":
    unittest.main()
