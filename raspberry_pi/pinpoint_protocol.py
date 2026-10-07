"""Transport-independent Pinpoint BLE protocol and camera-free test runtime."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from rig_pose import ground_mode, level_rig_pose, load_rig, rig_summary
from apriltag_calibration import calibration_version, capture_latest_apriltag_calibration, clear_apriltag_calibration, load_apriltag_calibration
from camera_source import (
    camera_diagnostics,
    configured_exposure_us,
    exposure_configuration,
    gain_configuration,
    set_camera_gain,
    active_light,
    light_mode,
    set_camera_exposure,
    blur_safe_exposure_us,
    set_exposure_cap_hint,
    set_light_mode,
    set_strobe_mode,
    strobe_mode_enabled,
    uses_csi,
)
from light_controller import get_light_controller, preset_for_club, strobe_pattern, indicator_state
from ball_detector import (
    DEFAULT_BALL_ROI,
    DEFAULT_ROLLING_CAPTURE_PATH,
    CALIBRATION_CAMERAS,
    calibration_capture_status,
    capture_retention,
    capture_contact_sheet,
    capture_clip,
    capture_frame_preview,
    clear_calibration_images,
    lens_calibration_status,
    latest_rolling_capture_preview,
    run_lens_calibration,
)

from target_line import clear_target_line, heading_from_track, load_target_line, save_target_line
from capture_quality import shot_evidence
from flight_model import carry_meters, select_spin
from frame_uploader import FrameUploadSource
from wifi_manager import (
    WifiProvisioningError,
    connect_wifi,
    get_wifi_status,
    scan_wifi_networks,
    wifi_provisioning_available,
)


SERVICE_VERSION = "0.62.4"
PROTOCOL_VERSION = "2.40.0"
MAX_HISTORY = 10
MAX_COMMAND_BYTES = 4096
BLE_CHUNK_BYTES = 20
# ATT notification payload is MTU - 3. 514 matches the 517-byte MTU Android can
# request; 244 was the old 247-byte MTU. Larger chunks mean fewer notifications and
# a faster transfer at the same pacing (same drop risk, ~2x throughput).
MAX_NOTIFICATION_CHUNK_BYTES = 514
DEFAULT_USB_CAPTURE_PATH = Path("/var/lib/pinpoint/usb-test-latest.jpg")

SendMessage = Callable[[dict[str, Any]], Awaitable[None]]
LOGGER = logging.getLogger("pinpoint.protocol")

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


def configured_camera_device() -> Path | None:
    configured = os.getenv("PINPOINT_CAMERA_DEVICE", "").strip()
    if configured:
        return Path(configured)

    camera_links = sorted(Path("/dev/v4l/by-id").glob("*-video-index0"))
    return camera_links[0] if camera_links else None


def camera_is_available(capture_backend: str) -> bool:
    if uses_csi():
        return bool(camera_diagnostics())
    override = os.getenv("PINPOINT_CAMERA_CONNECTED")
    if override is not None:
        return override.lower() in {"1", "true", "yes"}
    device = configured_camera_device()
    return device is not None and device.exists()


def preview_configuration(camera_connected: bool) -> dict[str, Any] | None:
    enabled = os.getenv("PINPOINT_BLE_PREVIEW", "false").lower() in {"1", "true", "yes"}
    if not enabled or (not camera_connected and not uses_csi()):
        return None
    try:
        roi = [
            float(value.strip())
            for value in os.getenv("PINPOINT_BALL_ROI", DEFAULT_BALL_ROI).split(",")
        ]
        if len(roi) != 4:
            raise ValueError
    except ValueError:
        roi = [0.0, 0.30, 0.50, 0.98]
    return {
        "transport": "ble",
        "intervalMs": round(
            float(os.getenv("PINPOINT_BLE_PREVIEW_INTERVAL_SECONDS", "3")) * 1000
        ),
        "width": int(os.getenv("PINPOINT_BLE_PREVIEW_WIDTH", "160")),
        "height": int(os.getenv("PINPOINT_BLE_PREVIEW_HEIGHT", "100" if uses_csi() else "120")),
        "roi": roi,
        "target": [round((roi[0] + roi[2]) / 2, 3), 0.72],
    }


def build_preview_event(jpeg_bytes: bytes, secondary_jpeg: bytes | None = None) -> dict[str, Any]:
    event = {
        "type": "preview",
        "data": {
            "mimeType": "image/jpeg",
            "base64": base64.b64encode(jpeg_bytes).decode("ascii"),
            "capturedAt": utc_now(),
        },
    }
    diagnostics = camera_diagnostics()
    if diagnostics:
        event["data"]["camera"] = diagnostics
    if secondary_jpeg is not None:
        event["data"]["secondaryBase64"] = base64.b64encode(secondary_jpeg).decode("ascii")
    return event


def capture_usb_test_frame(camera_device: Path) -> tuple[int, int]:
    """Capture one diagnostic frame while leaving all shot metrics synthetic."""
    output_path = Path(
        os.getenv("PINPOINT_USB_CAPTURE_PATH", str(DEFAULT_USB_CAPTURE_PATH))
    )
    temporary_path = output_path.with_suffix(".tmp.jpg")
    resolution = os.getenv("PINPOINT_CAMERA_RESOLUTION", "1280x720")
    frame_rate = os.getenv("PINPOINT_CAMERA_FPS", "30")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.unlink(missing_ok=True)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        "mjpeg",
        "-video_size",
        resolution,
        "-framerate",
        frame_rate,
        "-i",
        str(camera_device),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-y",
        str(temporary_path),
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        duration_ms = max(1, round((time.monotonic() - started) * 1000))
        if completed.returncode != 0 or not temporary_path.exists():
            detail = completed.stderr.strip() or f"ffmpeg exited {completed.returncode}"
            raise RuntimeError(detail)
        if temporary_path.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced an empty camera frame")
        temporary_path.replace(output_path)
        return 1, duration_ms
    finally:
        temporary_path.unlink(missing_ok=True)


def encode_message_chunks(
    message: dict[str, Any],
    chunk_size: int = BLE_CHUNK_BYTES,
) -> list[bytes]:
    encoded = (
        json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return [encoded[offset : offset + chunk_size] for offset in range(0, len(encoded), chunk_size)]


BAG_CLUB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_BAG_CLUB_NAME = 40


def parse_bag_club(value: Any) -> dict[str, Any] | None:
    """Validate a named club sent by the app; None clears the selection."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CommandError("bagClub must be an object.")
    club_id, name = value.get("id"), value.get("name")
    if not isinstance(club_id, str) or not BAG_CLUB_ID.match(club_id):
        raise CommandError("bagClub.id must be 1-64 letters, digits, dashes or underscores.")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_BAG_CLUB_NAME:
        raise CommandError(f"bagClub.name must be 1-{MAX_BAG_CLUB_NAME} characters.")
    club = {"id": club_id, "name": name.strip()}
    width, height = value.get("faceWidthMm"), value.get("faceHeightMm")
    if width is not None or height is not None:
        from club_vision import MAX_FACE_HEIGHT_MM, MAX_FACE_WIDTH_MM, MIN_FACE_HEIGHT_MM, MIN_FACE_WIDTH_MM
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (width, height))
        if (not numbers or not MIN_FACE_WIDTH_MM <= width <= MAX_FACE_WIDTH_MM
                or not MIN_FACE_HEIGHT_MM <= height <= MAX_FACE_HEIGHT_MM):
            raise CommandError(f"Face size must be {MIN_FACE_WIDTH_MM:.0f}-{MAX_FACE_WIDTH_MM:.0f} mm wide and "
                               f"{MIN_FACE_HEIGHT_MM:.0f}-{MAX_FACE_HEIGHT_MM:.0f} mm high.")
        club.update(faceWidthMm=float(width), faceHeightMm=float(height))
    return club


class PinpointProtocol:
    def __init__(
        self,
        send_message: SendMessage,
        capture_delay: float = 1.15,
        reset_ball_calibration: Callable[[], bool] | None = None,
        request_calibration_capture: Callable[[str], bool] | None = None,
        request_exposure_calibration: Callable[[], bool] | None = None,
    ) -> None:
        self.send_message = send_message
        self.capture_delay = capture_delay
        self.reset_ball_calibration = reset_ball_calibration
        self.request_calibration_capture = request_calibration_capture
        self.request_exposure_calibration = request_exposure_calibration
        self._stereo_future = None
        self._stereo_busy = False
        self._stereo_until = 0.0
        # BlueZ silently truncates a notification longer than the connection's MTU,
        # which bless cannot report, so the app states it in its status request.
        self.notification_chunk_bytes = BLE_CHUNK_BYTES
        self.name = os.getenv("PINPOINT_NAME", "LM1 PRO")
        self.capture_backend = os.getenv("PINPOINT_CAPTURE_BACKEND", "simulator").lower()
        if self.capture_backend not in {"simulator", "camera"}:
            raise ValueError("PINPOINT_CAPTURE_BACKEND must be 'simulator' or 'camera'")
        self.state = "ready"
        self.club_id = "driver"
        self.light = get_light_controller()
        if self.light:
            self.light.set_status_provider(lambda: indicator_state(self.state, getattr(self, "ball_present", False)))
        self._sync_ring()
        # A named club from the player's bag: {"id", "name"} plus optional face size.
        # club_id stays the club type the flight and spin models use.
        self.bag_club: dict[str, Any] | None = None
        self.capture_mode = "full-shot"
        self.shots: list[dict[str, Any]] = []
        self.putts: list[dict[str, Any]] = []
        self.captures: list[dict[str, Any]] = []
        capture_root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
        self.capture_retention = capture_retention()
        for path in sorted(capture_root.glob("capture-*/analysis.json"), reverse=True)[:self.capture_retention]:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(saved, dict) and all(key in saved for key in ("id", "image", "warnings", "classification", "frameCount")):
                    self.captures.append(saved)
            except (OSError, ValueError):
                LOGGER.warning("Could not restore capture analysis %s", path)
        self.ball_present = False
        self._shot_number = 0
        self._putt_number = 0
        self._command_buffer = bytearray()
        self._receive_lock = asyncio.Lock()
        self._capture_task: asyncio.Task[None] | None = None
        self._frame_upload_task: asyncio.Task[None] | None = None
        self._frame_upload_status: dict[str, Any] | None = None
        # Camera-side readiness from the most recent arming; club and exposure are
        # merged in at read time so a club change updates the verdict immediately.
        self._readiness_items: list[dict[str, Any]] | None = None

    def readiness_status(self) -> dict[str, Any] | None:
        """Pre-shot verdict for the ball as last placed, or None without a real camera."""
        if self.capture_backend != "camera":
            return None
        try:
            from readiness import readiness
            exposure = camera_diagnostics().get("exposureUs") if uses_csi() else None
            if not exposure:
                exposure = configured_exposure_us() if uses_csi() else int(os.getenv("PINPOINT_EXPOSURE_US", "0"))
            return readiness(self._readiness_items, exposure, self.club_id, self.capture_mode, self.bag_club,
                             self._recent_speeds())
        except Exception:  # Status must always answer; a broken check is logged, not fatal.
            LOGGER.exception("Readiness check failed")
            return None

    def _recent_speeds(self) -> list[dict[str, float]]:
        """Ball speed, launch and club speed of the last few measured full shots."""
        recent = []
        for capture in self.captures:
            if capture.get("mode") != "full-shot":
                continue
            metrics = (capture.get("measurements") or {}).get("metrics") or {}
            value = lambda key: (metrics.get(key) or {}).get("value")
            ball = value("ballSpeedMps")
            if isinstance(ball, (int, float)) and ball >= 2:
                recent.append({"ballSpeedMps": ball, "launchDeg": value("launchAngleDeg"),
                               "clubSpeedMps": value("clubSpeedMps")})
            if len(recent) == 5:
                break
        return recent

    async def readiness_checked(self, items: list[dict[str, Any]]) -> None:
        self._readiness_items = items
        verdict = self.readiness_status()
        if verdict is not None:
            await self.send_message({"type": "readiness", "data": verdict})

    @staticmethod
    def _rig_status() -> dict[str, Any]:
        """Which ground reference is in use and, for the level rig, its constants."""
        try:
            return rig_summary(load_rig())
        except ValueError as error:
            return {"mode": ground_mode(), "error": str(error)}

    def status(self) -> dict[str, Any]:
        camera_connected = camera_is_available(self.capture_backend)
        saved_ground = load_apriltag_calibration()
        saved_secondary_ground = load_apriltag_calibration("secondary")
        default_fps = "30" if self.capture_backend == "simulator" else "300"
        default_exposure_us = "15700" if self.capture_backend == "simulator" else "125"
        status: dict[str, Any] = {
            "automaticCapture": os.getenv("PINPOINT_AUTO_BALL_DETECTION", "false").lower() in {"1", "true", "yes"},
            "name": self.name,
            "state": self.state,
            "firmwareVersion": SERVICE_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "transport": "ble",
            "notificationChunkBytes": self.notification_chunk_bytes,
            "wifiProvisioning": wifi_provisioning_available(),
            "captureBackend": self.capture_backend,
            "captureMode": self.capture_mode,
            "selectedClubId": self.club_id,
            "selectedBagClub": ({"id": self.bag_club["id"], "name": self.bag_club["name"]}
                                if self.bag_club else None),
            "cameraConnected": camera_connected,
            "fps": int(os.getenv("PINPOINT_CAMERA_FPS", default_fps)) if camera_connected else 0,
            "exposureUs": (
                configured_exposure_us()
                if uses_csi()
                else int(os.getenv("PINPOINT_EXPOSURE_US", default_exposure_us))
            ) if camera_connected else 0,
            "temperatureC": read_temperature_c(),
            "storageFreeGb": storage_free_gb(),
            "calibrationVersion": os.getenv("PINPOINT_CALIBRATION_VERSION")
            or calibration_version()
            or ("NOT-CALIBRATED" if not camera_connected or self.capture_backend == "simulator" else "UNKNOWN"),
            "lastSeenAt": utc_now(),
            "calibrationCapture": calibration_capture_status(),
            "lensCalibration": lens_calibration_status(),
            "targetLine": load_target_line(),
            "rig": self._rig_status(),
            "groundCalibration": saved_ground if saved_ground and saved_ground.get("groundPose") else None,
            "secondaryGroundCalibration": saved_secondary_ground if saved_secondary_ground and saved_secondary_ground.get("groundPose") else None,
            "readiness": self.readiness_status(),
        }
        preview = preview_configuration(camera_connected)
        if uses_csi():
            diagnostics = camera_diagnostics()
            status["exposureControl"] = exposure_configuration()
            status["light"] = self.light_status()
            status["gainControl"] = gain_configuration()
            status["camera"] = diagnostics
            status["fps"] = diagnostics.get("fps", 0)
            status["exposureUs"] = diagnostics.get("exposureUs", 0)
        if preview is not None:
            status["preview"] = preview
        return status

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
        if self._stereo_busy and command_type != "status":
            raise CommandError("Wait for the stereo calibration operation to finish.")

        if command_type == "status":
            # Every app connection starts with status; one that states no MTU (older
            # builds) gets the always-safe minimum again.
            mtu = command.get("mtu")
            self.notification_chunk_bytes = (
                max(BLE_CHUNK_BYTES, min(MAX_NOTIFICATION_CHUNK_BYTES, mtu - 3))
                if isinstance(mtu, int) and not isinstance(mtu, bool) and 23 <= mtu <= 517
                else BLE_CHUNK_BYTES
            )
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
        if command_type == "listCaptures":
            await self._respond(
                request_id,
                [self._capture_summary(capture) for capture in self.captures[:MAX_HISTORY]],
            )
            return
        if command_type == "setClub":
            await self._set_club(request_id, command)
            return
        if command_type == "setExposure":
            await self._set_exposure(request_id, command)
            return
        if command_type == "setGain":
            await self._set_gain(request_id, command)
            return
        if command_type == "setStrobeMode":
            await self._set_strobe_mode(request_id, command)
            return
        if command_type == "setLightMode":
            await self._set_light_mode(request_id, command)
            return
        if command_type == "autoCalibrateExposure":
            await self._auto_calibrate_exposure(request_id)
            return
        if command_type == "disarm":
            await self._disarm(request_id)
            return
        if command_type == "trigger":
            await self._trigger(request_id)
            return
        if command_type == "resetBallCalibration":
            await self._reset_ball_calibration(request_id)
            return
        if command_type == "captureAprilTagCalibration":
            await self._capture_apriltag_calibration(request_id)
            return
        if command_type == "captureCalibrationImage":
            await self._capture_calibration_image(request_id, command)
            return
        if command_type == "clearCalibrationImages":
            await self._clear_calibration_images(request_id, command)
            return
        if command_type == "runLensCalibration":
            await self._run_lens_calibration(request_id, command)
            return
        if command_type == "stereoCalibration":
            await self._stereo_calibration(request_id, command)
            return
        if command_type == "shotCoverage":
            await self._shot_coverage(request_id)
            return
        if command_type == "setTargetLine":
            await self._set_target_line(request_id)
            return
        if command_type == "clearTargetLine":
            await self._clear_target_line(request_id)
            return
        if command_type == "latestCapturePreview":
            await self._latest_capture_preview(request_id)
            return
        if command_type == "captureFrame":
            await self._capture_frame(request_id, command)
            return
        if command_type == "captureClip":
            await self._capture_clip(request_id, command)
            return
        if command_type == "captureContactSheet":
            await self._capture_contact_sheet(request_id, command)
            return
        if command_type == "uploadCaptureFrames":
            await self._upload_capture_frames(request_id, command)
            return
        if command_type == "captureFrameUploadStatus":
            await self._respond(request_id, self._frame_upload_status)
            return
        if command_type == "wifiStatus":
            await self._wifi_status(request_id)
            return
        if command_type == "wifiScan":
            await self._wifi_scan(request_id)
            return
        if command_type == "wifiConnect":
            await self._wifi_connect(request_id, command)
            return
        raise CommandError(f"Unknown command type: {command_type}")

    async def _set_exposure(self, request_id: str, command: dict[str, Any]) -> None:
        exposure_us = command.get("exposureUs")
        if isinstance(exposure_us, bool) or not isinstance(exposure_us, int):
            raise CommandError("Exposure must be a whole number of microseconds.")
        if self.state != "ready":
            raise CommandError("Disarm LM1 and wait for processing to finish before changing exposure.")
        if not uses_csi():
            raise CommandError("Live exposure control requires the CSI camera.")
        try:
            await asyncio.to_thread(set_camera_exposure, exposure_us)
        except (OSError, RuntimeError, ValueError) as error:
            raise CommandError(str(error)) from error
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _set_gain(self, request_id: str, command: dict[str, Any]) -> None:
        gain = command.get("gain")
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain):
            raise CommandError("Camera gain must be a finite number.")
        if self.state != "ready":
            raise CommandError("Disarm LM1 and wait for processing to finish before changing gain.")
        if not uses_csi():
            raise CommandError("Live gain control requires the CSI camera.")
        try:
            await asyncio.to_thread(set_camera_gain, float(gain))
        except (OSError, RuntimeError, ValueError) as error:
            raise CommandError(str(error)) from error
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    def _ring_state(self) -> tuple[str, str | None, dict[str, Any] | None]:
        """What the ring should do for the light mode in use: mode, club group, flash pattern."""
        active = active_light()
        if active == "daylight":
            return "off", None, None
        if active == "strobe":
            club_speed, smash, _ = CLUB_PROFILES.get(self.club_id, (28.0, 1.30, 20.0))
            period_us = int(1e6 / float(os.getenv("PINPOINT_CAMERA_FPS", "242")))
            return "strobe", preset_for_club(self.club_id), strobe_pattern(club_speed * smash, period_us)
        return "flat", None, None

    def _sync_ring(self) -> None:
        if self.light is None:
            return
        try:
            self.light.set_mode(*self._ring_state())
        except ValueError as error:
            LOGGER.warning("Could not set the ring: %s", error)

    def light_status(self) -> dict[str, Any]:
        ring = self.light.status() if self.light is not None else {}
        return {
            "available": self.light is not None,
            "connected": bool(ring.get("connected")),
            "mode": light_mode(),
            "active": active_light(),
            "ring": ring.get("mode"),
            "preset": ring.get("preset"),
            "pattern": ring.get("pattern"),
            "error": ring.get("error"),
        }

    async def _set_light_mode(self, request_id: str, command: dict[str, Any]) -> None:
        mode = command.get("mode")
        if mode not in ("auto", "daylight", "flat", "strobe"):
            raise CommandError("Light mode must be auto, daylight, flat or strobe.")
        if self.state != "ready":
            raise CommandError("Disarm LM1 and wait for processing to finish before changing the light.")
        if not uses_csi():
            raise CommandError("Light modes require the CSI camera.")
        try:
            await asyncio.to_thread(set_light_mode, mode)
        except (OSError, RuntimeError, ValueError) as error:
            raise CommandError(str(error)) from error
        self._sync_ring()
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _set_strobe_mode(self, request_id: str, command: dict[str, Any]) -> None:
        enabled = command.get("enabled")
        if not isinstance(enabled, bool):
            raise CommandError("Strobe mode must be on or off.")
        if self.state != "ready":
            raise CommandError("Disarm LM1 and wait for processing to finish before changing strobe mode.")
        if not uses_csi():
            raise CommandError("Strobe mode requires the CSI camera.")
        try:
            await asyncio.to_thread(set_strobe_mode, enabled)
        except (OSError, RuntimeError, ValueError) as error:
            raise CommandError(str(error)) from error
        self._sync_ring()
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _auto_calibrate_exposure(self, request_id: str) -> None:
        if self.state != "ready":
            raise CommandError("Stop tracking and wait for the current shot to finish first.")
        if not uses_csi():
            raise CommandError("Automatic exposure needs the CSI camera.")
        if strobe_mode_enabled():
            raise CommandError("Automatic exposure is for normal shooting. Turn strobe mode off first.")
        # The club sets how fast the ball is, hence the longest shutter the measurement will accept.
        # (Putting is slow, so it keeps the full range.)
        club_speed, smash, _ = CLUB_PROFILES.get(self.club_id, (28.0, 1.30, 20.0))
        set_exposure_cap_hint(None if self.capture_mode == "putting" else blur_safe_exposure_us(club_speed * smash))
        if self.request_exposure_calibration is None or not self.request_exposure_calibration():
            set_exposure_cap_hint(None)
            raise CommandError("Automatic exposure is unavailable. Connect a camera-enabled LM1 first.")
        # The sweep runs in the detection loop and reports back over the
        # exposureCalibration event, so only the hand-off is acknowledged here.
        await self._respond(request_id, {"accepted": True})

    async def exposure_calibrated(self, result: dict[str, Any]) -> None:
        await self.send_message({"type": "exposureCalibration", "data": result})
        await self.send_message({"type": "status", "data": self.status()})

    async def _reset_ball_calibration(self, request_id: str) -> None:
        if self.state == "processing":
            raise CommandError("Wait for the current capture to finish before resetting the empty plane.")
        if self.reset_ball_calibration is None or not self.reset_ball_calibration():
            raise CommandError("Camera calibration reset is unavailable. Connect a camera-enabled LM1 first.")
        clear_apriltag_calibration()
        clear_apriltag_calibration("secondary")
        clear_target_line()
        await self._respond(request_id, {"accepted": True, "state": "calibrating"})
        self.state = "ready"
        self.ball_present = False
        await self.send_message({"type": "status", "data": self.status()})
        await self.send_message({"type": "ballPresence", "data": {"present": False}})

    async def _capture_apriltag_calibration(self, request_id: str) -> None:
        if self.state == "processing":
            raise CommandError("Wait for the current capture to finish before calibrating.")
        diagnostics = camera_diagnostics()
        try:
            calibration = await asyncio.to_thread(capture_latest_apriltag_calibration, diagnostics)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        # The top camera is calibrated from the same tag in the same moment, so both
        # poses share one ground frame. Its failure never discards the primary pose.
        if int(diagnostics.get("cameraCount", 1) or 1) >= 2:
            try:
                calibration = {**calibration, "secondary": await asyncio.to_thread(
                    capture_latest_apriltag_calibration, diagnostics, "secondary")}
            except (OSError, ValueError) as error:
                calibration = {**calibration, "secondaryError": str(error)}
        clear_target_line()
        await self._respond(request_id, calibration)
        await self.send_message({"type": "status", "data": self.status()})

    @staticmethod
    def _calibration_camera(command: dict[str, Any]) -> str:
        camera = command.get("camera", "primary")
        if camera not in CALIBRATION_CAMERAS:
            raise CommandError("Calibration camera must be 'primary' or 'secondary'.")
        return str(camera)

    async def _capture_calibration_image(self, request_id: str, command: dict[str, Any]) -> None:
        camera = self._calibration_camera(command)
        if camera == "secondary" and int(camera_diagnostics().get("cameraCount", 1) or 1) < 2:
            raise CommandError("The second camera is not streaming. Enable dual camera mode first.")
        if self.request_calibration_capture is None or not self.request_calibration_capture(camera):
            raise CommandError("Camera calibration capture is unavailable. Connect a camera-enabled LM1 first.")
        await self._respond(request_id, {"accepted": True, "camera": camera})

    async def calibration_image_captured(self, result: dict[str, Any]) -> None:
        if result.get("stereo"):
            if self._stereo_future is not None and not self._stereo_future.done():
                self._stereo_future.set_result(result)
            return
        await self.send_message({"type": "calibrationImage", "data": result})
        await self.send_message({"type": "status", "data": self.status()})

    async def _stereo_calibration(self, request_id: str, command: dict[str, Any]) -> None:
        import stereo_calibration as stereo
        action = command.get("action", "status")
        if self._stereo_busy:
            raise CommandError("Stereo calibration is busy; wait for the current operation.")
        if self.state == "processing":
            raise CommandError("Wait for the current shot to finish.")
        diagnostics = camera_diagnostics()
        indices = [diagnostics.get("primaryCameraIndex"), diagnostics.get("secondaryCameraIndex")]
        self._stereo_busy = True
        try:
            if action == "end":
                self._stereo_until = 0.0
                stereo.pause_capture(False)
                if self.reset_ball_calibration:
                    self.reset_ball_calibration()
                result = stereo.status()
            else:
                self._stereo_until = time.monotonic() + 120
                self.ball_present = False
                self.state = "ready"
                stereo.pause_capture()
                if action == "status":
                    result = await asyncio.to_thread(stereo.status)
                elif action == "start":
                    result = await asyncio.to_thread(stereo.start, command.get("columns", 5),
                                                     command.get("rows", 5), command.get("squareMm", 25))
                elif action == "capture":
                    self._stereo_future = asyncio.get_running_loop().create_future()
                    if self.request_calibration_capture is None or not self.request_calibration_capture("stereo"):
                        raise ValueError("Connect both cameras before capturing stereo pairs.")
                    captured = await asyncio.wait_for(self._stereo_future, timeout=25)
                    if captured.get("error"):
                        raise ValueError(captured["error"])
                    result = captured["data"]
                elif action == "solve":
                    result = await asyncio.to_thread(stereo.solve)
                elif action == "activate":
                    result = await asyncio.to_thread(stereo.activate, command.get("candidateId"), indices)
                else:
                    raise ValueError("Unknown stereo calibration action.")
            await self._respond(request_id, result)
        except (ValueError, OSError, asyncio.TimeoutError) as error:
            raise CommandError(str(error) or "Timed out waiting for a synchronized camera pair.") from error
        finally:
            self._stereo_future = None
            self._stereo_busy = False

    async def _clear_calibration_images(self, request_id: str, command: dict[str, Any]) -> None:
        status = await asyncio.to_thread(clear_calibration_images, self._calibration_camera(command))
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": self.status()})

    async def _run_lens_calibration(self, request_id: str, command: dict[str, Any]) -> None:
        camera = self._calibration_camera(command)
        try:
            result = await asyncio.to_thread(run_lens_calibration, camera)
            # A saved ground pose is only valid for the lens intrinsics it was solved with.
            clear_apriltag_calibration(camera)
            if camera == "primary":
                # Measurement geometry is built on the primary lens, so the target
                # line no longer matches the new intrinsics either.
                clear_target_line()
        except ValueError as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, result)
        await self.send_message({"type": "status", "data": self.status()})

    async def _shot_coverage(self, request_id: str) -> None:
        diagnostics = camera_diagnostics()
        if ground_mode() == "rig":
            try:
                from launch_measurements import load_setup
                size = [int(diagnostics["width"]), int(diagnostics["height"])]
                matrix, distortion = load_setup(size)
                level = level_rig_pose()
            except (KeyError, TypeError, ValueError, OSError) as error:
                raise CommandError(f"Shot coverage needs the lens calibration and the rig constants: {error}") from error
            pose = {"imageSize": size, "cameraMatrix": matrix.tolist(), "distCoeffs": distortion.tolist(),
                    "rotation": level["rotation"].tolist(), "translationM": level["translation"].tolist()}
        else:
            saved = load_apriltag_calibration()
            pose = saved.get("groundPose") if saved else None
            if not pose:
                raise CommandError("Save the lens calibration and the AprilTag ground calibration first.")
        fps = diagnostics.get("pairedFps") or diagnostics.get("fps") or float(os.getenv("PINPOINT_CAMERA_FPS", "0"))
        detection = diagnostics.get("ballDetection") or {}
        bounds = detection.get("bounds")
        ball = None
        if detection.get("state") == "detected" and bounds:
            ball = (bounds[0] + bounds[2] / 2, bounds[1] + bounds[3] / 2)
        try:
            # Imported here: it needs OpenCV, which a camera-less BLE service may lack.
            from shot_coverage import shot_coverage
            result = await asyncio.to_thread(shot_coverage, pose, float(fps), ball)
        except (ImportError, KeyError, TypeError, ValueError) as error:
            raise CommandError(str(error) or "Shot coverage could not be calculated.") from error
        await self._respond(request_id, result)

    async def _set_target_line(self, request_id: str) -> None:
        if not self.captures:
            raise CommandError("Roll a ball toward the target first; there is no capture to take the direction from.")
        saved_stamp = (load_apriltag_calibration() or {}).get("capturedAt")
        capture_stamp = (self.captures[0].get("measurements") or {}).get("diagnostics", {}).get("groundPose", {}).get("capturedAt")
        if saved_stamp and capture_stamp != saved_stamp:
            raise CommandError("Roll a new ball after the current ground calibration; the previous capture uses an older coordinate system.")
        track = (self.captures[0].get("measurements") or {}).get("ballTrack3d") or []
        try:
            heading_deg, displacement = heading_from_track(track)
        except ValueError as error:
            raise CommandError(str(error)) from error
        value = await asyncio.to_thread(save_target_line, heading_deg, len(track), displacement)
        await self._respond(request_id, value)
        await self.send_message({"type": "status", "data": self.status()})

    async def _clear_target_line(self, request_id: str) -> None:
        await asyncio.to_thread(clear_target_line)
        await self._respond(request_id, {"cleared": True})
        await self.send_message({"type": "status", "data": self.status()})

    async def _latest_capture_preview(self, request_id: str) -> None:
        preview = await asyncio.to_thread(latest_rolling_capture_preview)
        if preview is None:
            raise CommandError("No impact capture is available yet. Place and remove the ball first.")
        await self._respond(request_id, preview)

    async def _capture_clip(self, request_id: str, command: dict[str, Any]) -> None:
        capture_id, start, count = command.get("captureId"), command.get("startFrame"), command.get("count", 6)
        if not isinstance(capture_id, str) or not isinstance(start, int) or not isinstance(count, int):
            raise CommandError("Capture id, integer startFrame and count are required.")
        try:
            clip = await asyncio.to_thread(capture_clip, capture_id, start, count)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, clip)

    async def _capture_frame(self, request_id: str, command: dict[str, Any]) -> None:
        capture_id = command.get("captureId")
        frame_index = command.get("frameIndex")
        if not isinstance(capture_id, str) or not isinstance(frame_index, int):
            raise CommandError("Capture id and integer frame index are required.")
        try:
            preview = await asyncio.to_thread(capture_frame_preview, capture_id, frame_index)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, preview)

    async def _capture_contact_sheet(self, request_id: str, command: dict[str, Any]) -> None:
        capture_id = command.get("captureId")
        if not isinstance(capture_id, str):
            raise CommandError("Capture id is required.")
        try:
            sheet = await asyncio.to_thread(capture_contact_sheet, capture_id)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, sheet)

    async def _upload_capture_frames(self, request_id: str, command: dict[str, Any]) -> None:
        capture_id = command.get("captureId")
        ticket = command.get("ticket")
        expected_count = command.get("frameCount")
        indices = command.get("indices")
        if not isinstance(capture_id, str) or not isinstance(ticket, str) or not isinstance(expected_count, int):
            raise CommandError("Capture id, frame count, and upload ticket are required.")
        if not isinstance(indices, list) or len(indices) > 2000 or any(
            not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= expected_count
            for index in indices
        ):
            raise CommandError("Invalid frame upload indices.")
        if self._frame_upload_task is not None and not self._frame_upload_task.done():
            if self._frame_upload_status and self._frame_upload_status.get("captureId") == capture_id:
                await self._respond(request_id, self._frame_upload_status)
                return
            raise CommandError("Another capture is uploading. Try again when it finishes.")
        try:
            source = await asyncio.to_thread(FrameUploadSource, capture_id, expected_count)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        selected = sorted(set(indices))
        already_uploaded = source.frame_count - len(selected)
        self._frame_upload_status = {
            "captureId": capture_id,
            "uploaded": already_uploaded,
            "total": source.frame_count,
            "state": "complete" if not selected else "running",
        }
        if selected:
            self._frame_upload_task = asyncio.create_task(self._run_frame_upload(source, ticket, selected))
        await self._respond(request_id, self._frame_upload_status)

    async def _run_frame_upload(self, source: FrameUploadSource, ticket: str, indices: list[int]) -> None:
        completed = source.frame_count - len(indices)
        try:
            for index in indices:
                for attempt in range(3):
                    try:
                        await asyncio.to_thread(source.upload_frame, index, ticket)
                        break
                    except (OSError, ValueError, RuntimeError) as error:
                        if attempt == 2:
                            raise RuntimeError(f"Frame {index}: {error}") from error
                        await asyncio.sleep(2 ** attempt)
                completed += 1
                self._frame_upload_status = {
                    "captureId": source.capture_id, "uploaded": completed,
                    "total": source.frame_count, "state": "running",
                }
                if completed % 10 == 0 or completed == source.frame_count:
                    await self.send_message({"type": "frameUploadProgress", "data": self._frame_upload_status})
            self._frame_upload_status = {
                "captureId": source.capture_id, "uploaded": completed,
                "total": source.frame_count, "state": "complete",
            }
            await self.send_message({"type": "frameUploadProgress", "data": self._frame_upload_status})
        except Exception as error:
            LOGGER.exception("Original capture upload failed")
            self._frame_upload_status = {
                "captureId": source.capture_id, "uploaded": completed,
                "total": source.frame_count, "state": "error", "message": str(error),
            }
            await self.send_message({"type": "frameUploadProgress", "data": self._frame_upload_status})

    async def _wifi_status(self, request_id: str) -> None:
        try:
            status = await asyncio.to_thread(get_wifi_status)
        except WifiProvisioningError as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, status)

    async def _wifi_scan(self, request_id: str) -> None:
        try:
            networks = await asyncio.to_thread(scan_wifi_networks)
        except WifiProvisioningError as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, networks)

    async def _wifi_connect(self, request_id: str, command: dict[str, Any]) -> None:
        if self.state == "processing":
            raise CommandError("Wait for the current capture to finish before changing Wi-Fi.")
        ssid = command.get("ssid")
        password = command.get("password", "")
        hidden = command.get("hidden", False)
        if not isinstance(ssid, str):
            raise CommandError("Wi-Fi name is required.")
        if not isinstance(password, str):
            raise CommandError("Wi-Fi password must be text.")
        if not isinstance(hidden, bool):
            raise CommandError("Hidden network flag must be true or false.")
        try:
            status = await asyncio.to_thread(
                connect_wifi,
                ssid,
                password,
                hidden=hidden,
            )
        except WifiProvisioningError as error:
            raise CommandError(str(error)) from error
        await self._respond(request_id, status)

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
        bag_club = parse_bag_club(command.get("bagClub")) if capture_mode != "putting" else None

        self.club_id = club_id
        self._apply_bag_club(bag_club)
        self.capture_mode = capture_mode
        self.state = "armed"
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    async def _set_club(self, request_id: str, command: dict[str, Any]) -> None:
        if self.state == "processing":
            raise CommandError("Wait for the current capture to finish before changing clubs.")
        club_id = command.get("clubId")
        if club_id not in VALID_CLUBS:
            raise CommandError("Unknown clubId.")
        bag_club = parse_bag_club(command.get("bagClub"))
        self.club_id = club_id
        self._apply_bag_club(bag_club)
        self.capture_mode = "full-shot"
        if active_light() == "strobe":
            self._sync_ring()  # a different club needs a different flash pattern
        status = self.status()
        await self._respond(request_id, status)
        await self.send_message({"type": "status", "data": status})

    def _apply_bag_club(self, bag_club: dict[str, Any] | None) -> None:
        """Select a named club and make its face size the profile the analysis reads.

        Only a profile this service wrote (``source: app``) is ever replaced or removed;
        a hand-made club-profile.json is left alone when the club has no face size.
        """
        self.bag_club = bag_club
        path = Path(os.getenv("PINPOINT_CLUB_PROFILE_PATH", "/var/lib/pinpoint/club-profile.json"))
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        written_by_app = isinstance(existing, dict) and existing.get("source") == "app"
        try:
            if bag_club and "faceWidthMm" in bag_club:
                if existing is not None and not written_by_app:
                    LOGGER.info("Keeping the hand-made club profile at %s", path)
                    return
                profile = {"version": 1, "source": "app", "clubId": bag_club["id"], "clubName": bag_club["name"],
                           "faceWidthMm": bag_club["faceWidthMm"], "faceHeightMm": bag_club["faceHeightMm"]}
                if existing != profile:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(profile), encoding="utf-8")
                    temporary.replace(path)
            elif written_by_app:
                path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not update the club face profile at %s", path)

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
        if self.status()["automaticCapture"]:
            raise CommandError("Automatic capture is active. Place the ball and strike it; manual synthetic shots are disabled.")

        await self._start_test_capture(
            request_id=request_id,
            capture_camera=not any(
                os.getenv(name, "false").lower() in {"1", "true", "yes"}
                for name in ("PINPOINT_AUTO_BALL_DETECTION", "PINPOINT_BLE_PREVIEW")
            ),
        )

    async def ball_presence_changed(
        self,
        present: bool,
        frame_count: int = 0,
        duration_ms: int = 0,
        capture_id: str | None = None,
        impact_frame_index: int | None = None,
        analysis: dict[str, Any] | None = None,
    ) -> None:
        """Translate debounced camera presence into the existing app state machine."""
        if time.monotonic() < self._stereo_until:
            return
        self.ball_present = present
        if not present and self.state == "armed" and analysis is not None:
            self.state = "processing"
            self._capture_task = asyncio.create_task(self._finish_camera_capture(analysis, capture_id))
            return
        await self.send_message({"type": "ballPresence", "data": {"present": present}})
        if self.state == "processing":
            return
        if present:
            if self.state == "ready":
                self.state = "armed"
                await self.send_message({"type": "status", "data": self.status()})
            return
        if self.state != "armed":
            return
        if self.capture_backend == "camera" or self.status()["automaticCapture"]:
            self.state = "ready"
            await self._send_error(None, "Ball lost before a strike was captured. Replace the ball where the camera sees it clearly.")
            await self.send_message({"type": "status", "data": self.status()})
            return

        await self._start_test_capture(
            request_id=None,
            capture_camera=False,
            frame_count=frame_count,
            capture_duration_ms=duration_ms,
            capture_id=capture_id,
            impact_frame_index=impact_frame_index,
        )

    async def _finish_camera_capture(self, analysis: dict[str, Any], capture_id: str | None) -> None:
        result = {**analysis, "id": capture_id or f"capture-unsaved-{uuid4().hex}",
                  "captureId": capture_id, "capturedAt": utc_now(),
                  "clubId": self.club_id, "mode": self.capture_mode}
        if self.bag_club and self.capture_mode == "full-shot":
            result.update(bagClubId=self.bag_club["id"], bagClubName=self.bag_club["name"])
        measurements = result.get("measurements", {})
        evidence = shot_evidence(measurements, self.capture_mode)
        if evidence:
            measurements["shotEvidence"] = evidence
        # Tag-free silhouette tracking has no clubId: it is valid for whichever
        # club the user selected. Only a calibrated *marker* tied to a different
        # club must be rejected.
        if measurements.get("clubId") is not None and measurements["clubId"] != self.club_id:
            for key in ("clubSpeedMps", "smashFactor", "strikeXmm", "strikeYmm", "attackAngleDeg", "clubPathDeg"):
                metric = measurements.get("metrics", {}).get(key)
                if metric and metric.get("value") is not None:
                    metric.update(value=None, status="unavailable", reason="Club marker calibration does not match the selected club.")
        if self.capture_mode == "full-shot" and (evidence or {}).get("status") != "not-a-strike":
            metrics = measurements.get("metrics", {})
            speed = metrics.get("ballSpeedMps", {}).get("value")
            launch = metrics.get("launchAngleDeg", {}).get("value")
            direction = metrics.get("startDirectionDeg", {}).get("value")
            carry = metrics.setdefault("estimatedCarryM", {
                "value": None, "unit": "m", "status": "unavailable", "reason": "Awaiting flight model."})
            if all(isinstance(value, (int, float)) and math.isfinite(value)
                   for value in (speed, launch, direction)) and speed > 0:
                attack = metrics.get("attackAngleDeg", {}).get("value")
                has_attack = isinstance(attack, (int, float)) and math.isfinite(attack)
                spin, spin_source = select_spin(self.club_id, speed, launch, metrics.get("spinRpm", {}).get("value"),
                                                metrics.get("clubSpeedMps", {}).get("value"), attack)
                has_spin = spin_source == "camera"
                spin_text = {
                    "camera": "camera-measured spin.",
                    "impact-estimate": f"{spin} rpm backspin estimated from club speed, launch and attack angle.",
                    "club-attack-assumption": f"assumed {spin} rpm backspin for {self.club_id}, "
                                              + ("adjusted for measured attack angle." if has_attack
                                                 else "with attack angle unavailable."),
                }[spin_source]
                reason = ("Still-air flight model (fitted to tour averages) from ball speed, launch angle, "
                          f"target-line direction and {spin_text} Landing is not observed; wind, terrain and "
                          "spin axis are not modeled.")
                carry.update(value=carry_meters(speed, launch, direction, spin), status="estimated",
                             reason=reason, confidence=min(0.75 if has_spin else 0.6 if spin_source == "impact-estimate" else 0.5,
                             *(metrics.get(key, {}).get("confidence") or 0.7
                               for key in ("ballSpeedMps", "launchAngleDeg", "startDirectionDeg"))))
                measurements["carryModel"] = {
                    "version": 3, "spinSource": spin_source,
                    "spinRpmUsed": spin, "attackAngleDegUsed": attack if has_attack and not has_spin else None,
                }
        if capture_id is None:
            result["warnings"] = [*result["warnings"], "Burst could not be saved; only this preview is available."]
        self.captures.insert(0, result)
        del self.captures[self.capture_retention:]
        try:
            if capture_id is not None:
                root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
                destination = root / capture_id / "analysis.json"
                try:
                    await asyncio.to_thread(destination.write_text, json.dumps(result), encoding="utf-8")
                except OSError:
                    result["warnings"] = [*result["warnings"], "Analysis could not be persisted; keep this session open."]
            await self.send_message({"type": "ballPresence", "data": {"present": False}})
            await self.send_message({"type": "processing", "data": {"progress": 1}})
            await self.send_message({"type": "capture", "data": self._capture_summary(result)})
            shot = self._measurement_result(result)
            if shot is not None:
                history = self.putts if self.capture_mode == "putting" else self.shots
                history.insert(0, shot)
                del history[MAX_HISTORY:]
                await self.send_message({"type": "putt" if self.capture_mode == "putting" else "shot", "data": shot})
        except Exception:
            LOGGER.exception("Could not deliver capture result; retained for reconnect")
        finally:
            self.state = "armed" if self.ball_present else "ready"
            self._capture_task = None
            await self.send_message({"type": "status", "data": self.status()})

    def _measurement_result(self, capture: dict[str, Any]) -> dict[str, Any] | None:
        evidence = shot_evidence(capture.get("measurements", {}), self.capture_mode)
        if self.capture_mode == "full-shot" and evidence and evidence["status"] == "not-a-strike":
            return None
        metrics = capture.get("measurements", {}).get("metrics", {})
        required = ("ballSpeedMps", "clubSpeedMps", "smashFactor", "launchAngleDeg", "startDirectionDeg")
        if self.capture_mode != "putting":
            required += ("strikeXmm", "strikeYmm")
        values = {key: metrics.get(key, {}).get("value") for key in required}
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values.values()):
            return None
        if not 0 < values["smashFactor"] <= 2.2:
            return None
        putting = self.capture_mode == "putting"
        strike_x = metrics.get("strikeXmm", {}).get("value")
        strike_y = metrics.get("strikeYmm", {}).get("value")
        strike = ({"xMm": strike_x, "yMm": strike_y}
                  if all(isinstance(value, (int, float)) and math.isfinite(value)
                         for value in (strike_x, strike_y)) else None)
        if putting:
            self._putt_number += 1
        else:
            self._shot_number += 1
        result = {"id": capture["id"], "number": self._putt_number if putting else self._shot_number,
                  "capturedAt": capture["capturedAt"], "clubId": self.club_id,
                  **({"bagClubId": capture["bagClubId"], "bagClubName": capture.get("bagClubName")}
                     if capture.get("bagClubId") else {}),
                  "ballSpeedMps": values["ballSpeedMps"], "putterSpeedMps" if putting else "clubSpeedMps": values["clubSpeedMps"],
                  "smashFactor": values["smashFactor"], "launchAngleDeg": values["launchAngleDeg"],
                  "launchDirectionDeg" if putting else "startDirectionDeg": values["startDirectionDeg"],
                  "strike": strike,
                  "airborne": putting and values["launchAngleDeg"] > 10,
                  "frameCount": capture["frameCount"], "captureDurationMs": capture["captureDurationMs"],
                  "captureId": capture["captureId"], "impactFrameIndex": capture["impactFrameIndex"],
                  "simulated": False, "measurementSource": "monocular-estimate", "confidence": 0}
        for key in ("coarseDepartureFrameIndex", "lastStationaryFrameIndex", "firstMovingFrameIndex"):
            if isinstance(capture.get(key), int):
                result[key] = capture[key]
        for key in (("rollDistanceM", "skidDistanceM") if putting else ("spinRpm", "spinAxisDeg", "attackAngleDeg", "estimatedCarryM")):
            value = metrics.get(key, {}).get("value")
            if isinstance(value, (int, float)) and math.isfinite(value):
                result[key] = value
        return result

    @staticmethod
    def _capture_summary(capture: dict[str, Any]) -> dict[str, Any]:
        # Full 3D traces remain in analysis.json; BLE carries bounded tracking
        # evidence so the app can distinguish failed tracking from a low grade.
        result = {**capture, "track": []}
        if capture.get("measurements"):
            result["measurements"] = {key: value for key, value in capture["measurements"].items()
                                      if key not in ("ballTrack3d", "clubTrack3d", "spinSamples", "diagnostics")}
            result["measurements"].update(ballTrack3d=[], clubTrack3d=[])
            evidence = shot_evidence(capture["measurements"], capture.get("mode"))
            if evidence:
                result["measurements"]["shotEvidence"] = evidence
            diagnostics = capture["measurements"].get("diagnostics") or {}
            stereo = diagnostics.get("stereo") or {}
            speed = capture["measurements"].get("metrics", {}).get("ballSpeedMps", {}).get("value")
            stereo_failure = stereo.get("failure")
            mono_failure = (diagnostics.get("trajectoryFit") or {}).get("failure")
            if speed is None and stereo_failure:
                mono_failure = capture["measurements"].get("failure") or mono_failure
            speed_only = capture["measurements"].get("method") == "shared-tag-stereo-two-point-v1"
            source = ("stereo" if capture["measurements"].get("method") in ("shared-tag-stereo-v2", "shared-tag-stereo-two-point-v1")
                      else "single-camera" if speed is not None else None)
            result["measurements"]["tracking"] = {
                "status": "failed" if speed is None else "stereo-two-point" if speed_only else "stereo-matched" if source == "stereo" else "single-camera",
                "source": source,
                "speedOnly": speed_only,
                "speedUncertaintyPct": stereo.get("speedUncertaintyPct") if speed_only else None,
                "monoFallback": "used" if stereo_failure and source == "single-camera" else "failed" if stereo_failure and speed is None else "not-needed",
                "lowerFrames": diagnostics.get("motionTrackedFrames", 0),
                "pairedFrames": stereo.get("frames", 0),
                "pairedFrameIndices": (stereo.get("frameIndices") or [point["frameIndex"] for point in stereo.get("track", [])])[:48],
                "spanMs": stereo.get("spanMs"),
                "detection": stereo.get("detection"),
                "imageResidualPx": stereo.get("rmsPx"),
                "failure": capture["measurements"].get("failure") if speed is None else None,
                "stereoFailure": stereo_failure,
                "monoFailure": mono_failure if speed is None else None,
                "rejections": stereo.get("candidateRejections"),
            }
        return result

    async def _start_test_capture(
        self,
        request_id: str | None,
        capture_camera: bool,
        frame_count: int = 0,
        capture_duration_ms: int | None = None,
        capture_id: str | None = None,
        impact_frame_index: int | None = None,
    ) -> None:

        self.state = "processing"
        if request_id is not None:
            await self._respond(request_id, {"accepted": True, "simulated": True})
        await self.send_message({"type": "status", "data": self.status()})
        await self.send_message({"type": "processing", "data": {"progress": 0.1}})
        self._capture_task = asyncio.create_task(
            self._finish_test_capture(
                capture_camera=capture_camera,
                frame_count=frame_count,
                capture_duration_ms=capture_duration_ms,
                capture_id=capture_id,
                impact_frame_index=impact_frame_index,
            )
        )

    async def _finish_test_capture(
        self,
        capture_camera: bool = True,
        frame_count: int = 0,
        capture_duration_ms: int | None = None,
        capture_id: str | None = None,
        impact_frame_index: int | None = None,
    ) -> None:
        try:
            capture_started = time.monotonic()
            if capture_duration_ms is None:
                capture_duration_ms = round(self.capture_delay * 1000)
            camera_device = configured_camera_device()
            if capture_camera and not uses_csi() and camera_device is not None and camera_device.exists():
                try:
                    frame_count, capture_duration_ms = await asyncio.to_thread(
                        capture_usb_test_frame,
                        camera_device,
                    )
                    LOGGER.info(
                        "Saved USB test frame from %s to %s",
                        camera_device,
                        os.getenv("PINPOINT_USB_CAPTURE_PATH", str(DEFAULT_USB_CAPTURE_PATH)),
                    )
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    LOGGER.warning("USB test frame failed: %s", error)

            elapsed = time.monotonic() - capture_started
            await asyncio.sleep(max(0, self.capture_delay * 0.7 - elapsed))
            await self.send_message({"type": "processing", "data": {"progress": 0.65}})
            await asyncio.sleep(self.capture_delay * 0.3)
            if self.capture_mode == "putting":
                result = self._create_putt(frame_count, capture_duration_ms)
                self.putts.insert(0, result)
                del self.putts[MAX_HISTORY:]
                event_type = "putt"
            else:
                result = self._create_shot(
                    frame_count,
                    capture_duration_ms,
                    capture_id,
                    impact_frame_index,
                )
                self.shots.insert(0, result)
                del self.shots[MAX_HISTORY:]
                event_type = "shot"
            self.state = "ready"
            await self.send_message({"type": event_type, "data": result})
            await self.send_message({"type": "status", "data": self.status()})
        finally:
            self.state = "armed" if self.ball_present else "ready"
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

    def _create_shot(
        self,
        frame_count: int = 0,
        capture_duration_ms: int | None = None,
        capture_id: str | None = None,
        impact_frame_index: int | None = None,
    ) -> dict[str, Any]:
        self._shot_number += 1
        number = self._shot_number
        phase = number % 5
        club_speed, smash, launch = CLUB_PROFILES[self.club_id]
        club_speed += (phase - 2) * 0.18
        smash += (phase - 2) * 0.006
        launch += (phase - 2) * 0.25
        ball_speed = club_speed * smash
        result = {
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
            "frameCount": frame_count,
            "captureDurationMs": (
                capture_duration_ms
                if capture_duration_ms is not None
                else round(self.capture_delay * 1000)
            ),
            "simulated": True,
        }
        if capture_id is not None:
            result["captureId"] = capture_id
        if impact_frame_index is not None:
            result["impactFrameIndex"] = impact_frame_index
        return result

    def _create_putt(
        self,
        frame_count: int = 0,
        capture_duration_ms: int | None = None,
    ) -> dict[str, Any]:
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
            "frameCount": frame_count,
            "captureDurationMs": (
                capture_duration_ms
                if capture_duration_ms is not None
                else round(self.capture_delay * 1000)
            ),
            "rollDistanceM": round(2.72 + phase * 0.13, 2),
            "skidDistanceM": round(0.18 + phase * 0.015, 2),
            "simulated": True,
        }
