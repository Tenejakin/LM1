import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpoint_protocol import PinpointProtocol, encode_message_chunks  # noqa: E402


class ProtocolHarness:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.message_available = asyncio.Event()

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self.message_available.set()

    async def command(self, protocol: PinpointProtocol, message: dict[str, Any]) -> None:
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        for offset in range(0, len(encoded), 20):
            await protocol.receive_chunk(encoded[offset : offset + 20])

    async def wait_for_type(self, message_type: str) -> dict[str, Any]:
        for _ in range(20):
            match = next(
                (message for message in self.messages if message["type"] == message_type),
                None,
            )
            if match:
                return match
            self.message_available.clear()
            await asyncio.wait_for(self.message_available.wait(), timeout=1)
        raise AssertionError(f"No {message_type} message received")


class PinpointProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["PINPOINT_CAPTURE_BACKEND"] = "simulator"
        self.harness = ProtocolHarness()
        self.protocol = PinpointProtocol(self.harness.send, capture_delay=0.02)

    async def asyncTearDown(self) -> None:
        await self.protocol.close()

    async def test_status_response_is_ble_only_and_camera_free(self) -> None:
        await self.harness.command(self.protocol, {"id": "1", "type": "status"})
        response = await self.harness.wait_for_type("response")
        status = response["data"]
        self.assertEqual(response["id"], "1")
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["transport"], "ble")
        self.assertEqual(status["protocolVersion"], "2.0.0")
        self.assertEqual(status["captureBackend"], "simulator")
        self.assertFalse(status["cameraConnected"])

    async def test_outgoing_unicode_message_uses_safe_twenty_byte_chunks(self) -> None:
        chunks = encode_message_chunks({"name": "Pinpoint · Pi"})
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        encoded = b"".join(chunks)
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn("·".encode(), encoded)
        self.assertEqual(json.loads(encoded), {"name": "Pinpoint · Pi"})

    async def test_chunked_full_shot_command_produces_live_result(self) -> None:
        await self.harness.command(
            self.protocol,
            {"id": "2", "type": "arm", "clubId": "7-iron", "mode": "full-shot"},
        )
        self.assertEqual(self.protocol.state, "armed")
        self.harness.messages.clear()

        await self.harness.command(self.protocol, {"id": "3", "type": "trigger"})
        trigger_response = await self.harness.wait_for_type("response")
        self.assertTrue(trigger_response["data"]["accepted"])
        shot_event = await self.harness.wait_for_type("shot")
        self.assertEqual(shot_event["data"]["clubId"], "7-iron")
        self.assertTrue(shot_event["data"]["simulated"])
        self.assertEqual(self.protocol.state, "ready")

        self.harness.messages.clear()
        await self.harness.command(self.protocol, {"id": "4", "type": "listShots"})
        history = await self.harness.wait_for_type("response")
        self.assertEqual(len(history["data"]), 1)
        self.assertEqual(history["data"][0]["id"], shot_event["data"]["id"])

    async def test_putting_command_produces_putt(self) -> None:
        await self.harness.command(
            self.protocol,
            {"id": "5", "type": "arm", "clubId": "putter", "mode": "putting"},
        )
        self.harness.messages.clear()
        await self.harness.command(self.protocol, {"id": "6", "type": "trigger"})
        putt_event = await self.harness.wait_for_type("putt")
        self.assertTrue(putt_event["data"]["simulated"])
        self.assertIn("rollDistanceM", putt_event["data"])

    async def test_invalid_command_returns_correlated_error(self) -> None:
        await self.harness.command(self.protocol, {"id": "bad-1", "type": "nope"})
        error = await self.harness.wait_for_type("error")
        self.assertEqual(error["id"], "bad-1")
        self.assertIn("Unknown command", error["message"])


if __name__ == "__main__":
    unittest.main()
