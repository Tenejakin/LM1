"""OpenGolfSim bridge: WebSocket (app) <-> newline-delimited JSON over TCP (OpenGolfSim).

The Pinpoint app can only open WebSockets; OpenGolfSim (Desktop or the iPad app) listens
for newline-delimited JSON on TCP 3111. This is the Python equivalent of
bridge/opengolfsim-bridge.cjs so the Pi can bridge without Node.js or extra packages.

When PINPOINT_OGS_HOST is unset, or the configured host stops answering, the bridge scans
the Pi's local /24 for port 3111. That keeps working after an iPad gets a new DHCP address.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import os
import socket
import struct

LOG = logging.getLogger("ogs_bridge")

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE_BYTES = 64 * 1024
MAX_HEADER_BYTES = 8 * 1024
CONNECT_TIMEOUT_S = 1.5
SCAN_TIMEOUT_S = 0.6
SCAN_CONCURRENCY = 64

OP_CONTINUATION, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class ProtocolError(Exception):
    pass


def accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + WEBSOCKET_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode: int, payload: bytes) -> bytes:
    """Server frames are never masked."""
    length = len(payload)
    if length < 126:
        header = struct.pack("!BB", 0x80 | opcode, length)
    elif length < 1 << 16:
        header = struct.pack("!BBH", 0x80 | opcode, 126, length)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
    return header + payload


async def read_frame(reader: asyncio.StreamReader) -> tuple[bool, int, bytes]:
    first, second = await reader.readexactly(2)
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        (length,) = struct.unpack("!H", await reader.readexactly(2))
    elif length == 127:
        (length,) = struct.unpack("!Q", await reader.readexactly(8))
    if not masked:
        raise ProtocolError("client frames must be masked")
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError("message too large")
    mask = await reader.readexactly(4)
    data = await reader.readexactly(length)
    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    return fin, opcode, payload


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False

    async def send_text(self, text: str) -> None:
        if self.closed:
            return
        self.writer.write(encode_frame(OP_TEXT, text.encode("utf-8")))
        await self.writer.drain()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.writer.write(encode_frame(OP_CLOSE, struct.pack("!H", code) + reason.encode("utf-8")[:120]))
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            pass
        self.writer.close()

    async def messages(self):
        """Yield complete text messages; answers pings and stops on close."""
        parts: list[bytes] = []
        while not self.closed:
            fin, opcode, payload = await read_frame(self.reader)
            if opcode == OP_PING:
                self.writer.write(encode_frame(OP_PONG, payload))
                await self.writer.drain()
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                await self.close()
                return
            if opcode in (OP_TEXT, OP_BINARY):
                parts = [payload]
            elif opcode == OP_CONTINUATION and parts:
                parts.append(payload)
            else:
                raise ProtocolError(f"unexpected opcode {opcode}")
            if sum(len(part) for part in parts) > MAX_MESSAGE_BYTES:
                raise ProtocolError("message too large")
            if fin:
                message = b"".join(parts).decode("utf-8", errors="replace")
                parts = []
                yield message


async def handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, status_text: str) -> bool:
    """Complete the HTTP upgrade. A plain HTTP GET gets a one-line status page instead."""
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return False
    if len(raw) > MAX_HEADER_BYTES:
        return False
    lines = raw.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if value:
            headers[name.strip().lower()] = value.strip()
    key = headers.get("sec-websocket-key")
    if headers.get("upgrade", "").lower() != "websocket" or not key:
        body = (status_text + "\n").encode("utf-8")
        writer.write(
            b"HTTP/1.1 426 Upgrade Required\r\nContent-Type: text/plain; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + body
        )
        await writer.drain()
        return False
    writer.write(
        (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
        ).encode("ascii")
    )
    await writer.drain()
    return True


def local_networks() -> list[ipaddress.IPv4Network]:
    """The /24 of the interface that carries the default route (no packets are sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return []
    finally:
        probe.close()
    if address.startswith("127."):
        return []
    return [ipaddress.ip_network(f"{address}/24", strict=False)]


async def try_connect(host: str, port: int, timeout: float):
    try:
        return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (OSError, asyncio.TimeoutError):
        return None


async def scan_for_ogs(port: int, networks: list[ipaddress.IPv4Network]):
    """Return (host, reader, writer) for the first host that accepts, keeping that connection.

    OpenGolfSim on iPad drops a new client when a probe connection closes just before
    it, so the connection that answered the scan is the one the app session uses.
    """
    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def probe(host: str):
        async with semaphore:
            streams = await try_connect(host, port, SCAN_TIMEOUT_S)
            return (host, *streams) if streams else None

    tasks = [asyncio.create_task(probe(str(host))) for network in networks for host in network.hosts()]
    found = None
    try:
        for result in asyncio.as_completed(tasks):
            hit = await result
            if hit:
                found = hit
                break
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            if task.done() and not task.cancelled() and task.result() and task.result() is not found:
                task.result()[2].close()
    return found


class Bridge:
    def __init__(self, ogs_host: str | None, ogs_port: int, networks=local_networks):
        self.configured_host = ogs_host
        self.ogs_port = ogs_port
        self.networks = networks
        self.last_host: str | None = ogs_host
        self._lookup = asyncio.Lock()

    def status_text(self) -> str:
        target = f"{self.last_host}:{self.ogs_port}" if self.last_host else f"auto-discovery on port {self.ogs_port}"
        return f"LM1 OpenGolfSim bridge. OpenGolfSim: {target}"

    async def open_ogs(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        async with self._lookup:
            candidates = [host for host in dict.fromkeys([self.last_host, self.configured_host]) if host]
            for host in candidates:
                try:
                    return await self._connect(host)
                except (OSError, asyncio.TimeoutError):
                    LOG.info("OpenGolfSim not reachable at %s:%s", host, self.ogs_port)
            networks = self.networks()
            found = await scan_for_ogs(self.ogs_port, networks) if networks else None
            if not found:
                raise ConnectionError(
                    f"No OpenGolfSim found on port {self.ogs_port}. Open OpenGolfSim on the same Wi-Fi as LM1."
                )
            host, reader, writer = found
            LOG.info("Found OpenGolfSim at %s:%s", host, self.ogs_port)
            return self._use(host, reader, writer)

    async def _connect(self, host: str):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, self.ogs_port), timeout=CONNECT_TIMEOUT_S)
        return self._use(host, reader, writer)

    def _use(self, host: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.last_host = host
        return reader, writer

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            if not await handshake(reader, writer, self.status_text()):
                writer.close()
                return
        except (ConnectionError, OSError):
            writer.close()
            return
        websocket = WebSocket(reader, writer)
        try:
            ogs_reader, ogs_writer = await self.open_ogs()
        except (OSError, asyncio.TimeoutError) as error:
            await websocket.send_text(json.dumps({"type": "bridge", "status": "error", "message": str(error)}))
            await websocket.close(1011, "OpenGolfSim unreachable")
            return

        LOG.info("App %s connected; forwarding to %s:%s", peer, self.last_host, self.ogs_port)
        await websocket.send_text(json.dumps({"type": "bridge", "status": "connected", "host": self.last_host}))

        async def ogs_to_app():
            while True:
                line = await ogs_reader.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    if '"result"' in text:
                        LOG.info("OpenGolfSim result: %s", text)
                    await websocket.send_text(text)

        async def app_to_ogs():
            async for message in websocket.messages():
                try:
                    payload = json.loads(message)
                except ValueError:
                    await websocket.send_text(
                        json.dumps({"type": "bridge", "status": "error", "message": "The app sent malformed JSON."})
                    )
                    continue
                if isinstance(payload, dict) and payload.get("type") == "shot":
                    LOG.info("Shot to OpenGolfSim: %s", message.strip())
                ogs_writer.write(message.strip().encode("utf-8") + b"\n")
                await ogs_writer.drain()

        tasks = [asyncio.create_task(ogs_to_app()), asyncio.create_task(app_to_ogs())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                if task.exception() and not isinstance(task.exception(), (ConnectionError, asyncio.IncompleteReadError)):
                    LOG.warning("Bridge session ended: %s", task.exception())
        finally:
            ogs_writer.close()
            await websocket.close(1011, "OpenGolfSim connection closed")
            LOG.info("App %s disconnected", peer)


async def serve(listen_host: str, listen_port: int, bridge: Bridge) -> asyncio.base_events.Server:
    return await asyncio.start_server(bridge.handle, listen_host, listen_port, limit=MAX_HEADER_BYTES * 2)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    listen_host = os.environ.get("PINPOINT_OGS_BRIDGE_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("PINPOINT_OGS_BRIDGE_PORT", "3112"))
    ogs_host = os.environ.get("PINPOINT_OGS_HOST", "").strip() or None
    ogs_port = int(os.environ.get("PINPOINT_OGS_PORT", "3111"))
    bridge = Bridge(ogs_host, ogs_port)
    server = await serve(listen_host, listen_port, bridge)
    LOG.info("Listening on ws://%s:%s; %s", listen_host, listen_port, bridge.status_text())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
