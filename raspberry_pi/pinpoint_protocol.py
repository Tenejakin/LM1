"""Transport-independent Pinpoint BLE protocol and camera-free test runtime."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SERVICE_VERSION = "0.2.0"
PROTOCOL_VERSION = "2.0.0"
MAX_HISTORY = 10
MAX_COMMAND_BYTES = 4096
BLE_CHUNK_BYTES = 20

SendMessage = Callable[[dict[str, Any]], Awaitable[None]]

VALID_CLUBS = {
    "driver",
    "3-wood",
    "5-wood",
    "3-hybrid",
    "4-hybrid",
    "4-iron",
    "5-iron",
    "6-iron",
    "7-iron",
    "8-iron",
    "9-iron",
    "pitching-wedge",
    "gap-wedge",
    "sand-wedge",
    "lob-wedge",
}

CLUB_PROFILES: dict[str, tuple[float, float, float]] = {
    "driver": (42.5, 1.46, 14.0),
    "3-wood": (40.2, 1.44, 15.0),
    "5-wood": (38.4, 1.42, 16.5),
    "3-hybrid": (37.0, 1.40, 17.0),
    "4-hybrid": (35.8, 1.39, 18.0),
    "4-iron": (34.5, 1.37, 17.0),
    "5-iron": (33.5, 1.36, 18.0),
    "6-iron": (32.4, 1.35, 19.0),
    "7-iron": (31.3, 1.34, 20.0),
    "8-iron": (30.0, 1.33, 22.0),
    "9-iron": (28.7, 1.32, 25.0),
    "pitching-wedge": (27.0, 1.30, 28.0),
    "gap-wedge": (25.5, 1.28, 31.0),
    "sand-wedge": (23.8, 1.25, 34.0),
    "lob-wedge": (22.0, 1.22, 38.0),
}


class CommandError(Exception):
    """An error safe to return to the connected app."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_temperature_c() -> float:
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
        return round(float(raw) / 1000, 1)
    except (OSError, ValueError):
        return 0.0


def storage_free_gb() -> float:
    return round(shutil.disk_usage("/").free / 1_000_000_000, 1)


def camera_is_available(capture_backend: str) -> bool:
    if capture_backend != "camera":
        return False
    override = os.getenv("PINPOINT_CAMERA_CONNECTED")
    if override is not None:
        return override.lower() in {"1", "true", "yes"}
    return any(Path("/dev").glob("video*"))


def encode_message_chunks(
    message: dict[str, Any],
    chunk_size: int = BLE_CHUNK_BYTES,
) -> list[bytes]:
    encoded = (
        json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return [encoded[offset : offset + chunk_size] for offset in range(0, len(encoded), chunk_size)]


class PinpointProtocol:
    def __init__(self, send_message: SendMessage, capture_delay: float = 1.15) -> None:
        self.send_message = send_message
        self.capture_delay = capture_delay
        self.name = os.getenv("PINPOINT_NAME", "Pinpoint LM · Raspberry Pi")
        self.capture_backend = os.getenv("PINPOINT_CAPTURE_BACKEND", "simulator").lower()
        if self.capture_backend not in {"simulator", "camera"}:
            raise ValueError("PINPOINT_CAPTURE_BACKEND must be 'simulator' or 'camera'")
        self.state = "ready"
        self.club_id = "driver"
        self.capture_mode = "full-shot"
        self.shots: list[dict[str, Any]] = []
        self.putts: list[dict[str, Any]] = []
        self._shot_number = 0
        self._putt_number = 0
        self._command_buffer = bytearray()
        self._receive_lock = asyncio.Lock()
        self._capture_task: asyncio.Task[None] | None = None

    def status(self) -> dict[str, Any]:
        camera_connected = camera_is_available(self.capture_backend)
        return {
            "name": self.name,
            "state": self.state,
            "firmwareVersion": SERVICE_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "transport": "ble",
            "captureBackend": self.capture_backend,
            "cameraConnected": camera_connected,
            "fps": int(os.getenv("PINPOINT_CAMERA_FPS", "300")) if camera_connected else 0,
            "exposureUs": int(os.getenv("PINPOINT_EXPOSURE_US", "125")) if camera_connected else 0,
            "temperatureC": read_temperature_c(),
            "storageFreeGb": storage_free_gb(),
            "calibrationVersion": os.getenv(
                "PINPOINT_CALIBRATION_VERSION",
                "NOT-CALIBRATED" if not camera_connected else "UNKNOWN",
            ),
            "lastSeenAt": utc_now(),
        }

    async def receive_chunk(self, chunk: bytes) -> None:
        async with self._receive_lock:
            self._command_buffer.extend(chunk)
            if len(self._command_buffer) > MAX_COMMAND_BYTES:
                self._command_buffer.clear()
                await self._send_error(None, "Command exceeded the BLE message limit.")
                return

            while b"\n" in self._command_buffer:
                raw_command, _, remainder = self._command_buffer.partition(b"\n")
                self._command_buffer = bytearray(remainder)
                if not raw_command:
                    continue
                try:
                    command = json.loads(raw_command.decode("utf-8"))
                    if not isinstance(command, dict):
                        raise CommandError("Command must be a JSON object.")
                    await self._handle_command(command)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self._send_error(None, "Command was not valid UTF-8 JSON.")
                except CommandError as error:
                    request_id = command.get("id") if isinstance(command, dict) else None
                    await self._send_error(request_id, str(error))

    async def _handle_command(self, command: dict[str, Any]) -> None:
        request_id = command.get("id")
        command_type = command.get("type")
        if not isinstance(request_id, str) or not request_id:
            raise CommandError("Command id is required.")
        if not isinstance(command_type, str):
            raise CommandError("Command type is required.")

        if command_type == "status":
            await self._respond(request_id, self.status())
            return
        if command_type == "listShots":
            await self._respond(request_id, self.shots)
            return
        if command_type == "listPutts":
            await self._respond(request_id, self.putts)
            return
        if command_type == "arm":
            await self._arm(request_id, command)
            return
        if command_type == "disarm":
            await self._disarm(request_id)
            return
        if command_type == "trigger":
            await self._trigger(request_id)
            return
        raise CommandError(f"Unknown command type: {command_type}")

    async def _arm(self, request_id: str, command: dict[str, Any]) -> None:
        if self.state == "processing":
            raise CommandError("A capture is already processing.")
        capture_mode = command.get("mode", "full-shot")
        club_id = command.get("clubId", "driver")
        if capture_mode not in {"full-shot", "putting"}:
            raise CommandError("Mode must be full-shot or putting.")
        if capture_mode == "putting":
            club_id = "putter"
        elif club_id not in VALID_CLUBS:
            raise CommandError("Unknown clubId.")

        self.club_id = club_id
        self.capture_mode = capture_mode
        self.state = "armed"
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _disarm(self, request_id: str) -> None:
        if self.state == "processing":
            raise CommandError("Wait for the current capture to finish.")
        self.state = "ready"
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _trigger(self, request_id: str) -> None:
        if self.state == "processing":
            raise CommandError("A capture is already processing.")
        if self.capture_backend != "simulator":
            raise CommandError("The camera capture backend is not installed yet.")

        self.state = "processing"
        await self._respond(request_id, {"accepted": True, "simulated": True})
        await self.send_message({"type": "status", "data": self.status()})
        await self.send_message({"type": "processing", "data": {"progress": 0.1}})
        self._capture_task = asyncio.create_task(self._finish_test_capture())

    async def _finish_test_capture(self) -> None:
        try:
            await asyncio.sleep(self.capture_delay * 0.7)
            await self.send_message({"type": "processing", "data": {"progress": 0.65}})
            await asyncio.sleep(self.capture_delay * 0.3)
            if self.capture_mode == "putting":
                result = self._create_putt()
                self.putts.insert(0, result)
                del self.putts[MAX_HISTORY:]
                event_type = "putt"
            else:
                result = self._create_shot()
                self.shots.insert(0, result)
                del self.shots[MAX_HISTORY:]
                event_type = "shot"
            self.state = "ready"
            await self.send_message({"type": event_type, "data": result})
            await self.send_message({"type": "status", "data": self.status()})
        finally:
            self._capture_task = None

    async def _respond(self, request_id: str, data: Any) -> None:
        await self.send_message({"type": "response", "id": request_id, "data": data})

    async def _send_error(self, request_id: Any, message: str) -> None:
        payload: dict[str, Any] = {"type": "error", "message": message}
        if isinstance(request_id, str):
            payload["id"] = request_id
        await self.send_message(payload)

    async def close(self) -> None:
        if self._capture_task:
            self._capture_task.cancel()
            await asyncio.gather(self._capture_task, return_exceptions=True)
            self._capture_task = None

    def _create_shot(self) -> dict[str, Any]:
        self._shot_number += 1
        number = self._shot_number
        phase = number % 5
        club_speed, smash, launch = CLUB_PROFILES[self.club_id]
        club_speed += (phase - 2) * 0.18
        smash += (phase - 2) * 0.006
        launch += (phase - 2) * 0.25
        ball_speed = club_speed * smash
        return {
            "id": f"pi-test-{uuid4().hex}",
            "number": number,
            "capturedAt": utc_now(),
            "clubId": self.club_id,
            "ballSpeedMps": round(ball_speed, 1),
            "clubSpeedMps": round(club_speed, 1),
            "smashFactor": round(smash, 2),
            "launchAngleDeg": round(launch, 1),
            "startDirectionDeg": round(-1.6 + phase * 0.8, 1),
            "strike": {"xMm": -4 + phase * 2.5, "yMm": -2 + phase * 1.2},
            "confidence": round(0.94 + phase * 0.006, 3),
            "frameCount": 0,
            "captureDurationMs": round(self.capture_delay * 1000),
            "simulated": True,
        }

    def _create_putt(self) -> dict[str, Any]:
        self._putt_number += 1
        number = self._putt_number
        phase = number % 5
        putter_speed = 1.23 + phase * 0.025
        smash = 1.39 + phase * 0.012
        return {
            "id": f"pi-test-putt-{uuid4().hex}",
            "number": number,
            "capturedAt": utc_now(),
            "ballSpeedMps": round(putter_speed * smash, 2),
            "putterSpeedMps": round(putter_speed, 2),
            "smashFactor": round(smash, 2),
            "launchDirectionDeg": round(-0.8 + phase * 0.38, 2),
            "launchAngleDeg": round(1.35 + phase * 0.1, 1),
            "strike": {"xMm": -2 + phase, "yMm": -0.5 + phase * 0.25},
            "confidence": round(0.95 + phase * 0.006, 3),
            "frameCount": 0,
            "captureDurationMs": round(self.capture_delay * 1000),
            "rollDistanceM": round(2.72 + phase * 0.13, 2),
            "skidDistanceM": round(0.18 + phase * 0.015, 2),
            "simulated": True,
        }
