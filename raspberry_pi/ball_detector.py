"""Debounced golf-ball presence detection for the LM1 PRO USB test camera."""

from __future__ import annotations

import base64
import logging
import math
import os
import json
import re
import shutil
import statistics
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apriltag_calibration import AprilTagDetector, load_apriltag_calibration
from camera_source import (
    CsiCapture, DualCsiCapture, RAW_SCALE, auto_calibrate_light, light_mode, raw_black_level,
    record_camera_diagnostics, set_exposure_cap_hint, take_exposure_cap_hint, uses_csi,
)
from adaptive_capture import CHECK_INTERVAL_S, AdaptivePolicy, ViewSample, club_exposure_cap_us
from light_controller import get_light_controller
from raw_frames import RawAnalysis
from rejection_hints import friendly_failure
from strobe_copies import estimate_with_report, metrics_from_fit

try:
    import cv2
    import numpy as np
except ModuleNotFoundError:  # BLE can still start if the optional camera package is absent.
    cv2 = None
    np = None


LOGGER = logging.getLogger("pinpoint.ball_detector")
DEFAULT_CAPTURE_PATH = Path("/var/lib/pinpoint/usb-test-latest.jpg")
DEFAULT_PREVIEW_WIDTH = 160
DEFAULT_PREVIEW_HEIGHT = 120
DEFAULT_PREVIEW_QUALITY = 20
DEFAULT_PREVIEW_MAX_BYTES = 2200
DEFAULT_BALL_ROI = "0,0.30,0.50,0.98"
DEFAULT_ROLLING_CAPTURE_PATH = Path("/var/lib/pinpoint/rolling-captures")
DEFAULT_CAPTURE_RETENTION = 100
# At 200 fps a struck ball crosses the view in about 40 ms. The buffer is
# pre + removal debounce + post frames; the departure sits roughly one debounce
# (plus at most the departure timeout) before the end, so 120 pre frames still
# leave ~0.6 s of resting-ball background for launch analysis.
DEFAULT_PRE_IMPACT_FRAMES = 120
DEFAULT_POST_IMPACT_FRAMES = 30
# 64, not 48: the stereo ball check needs ~60 empty frames after the shot, so a shorter
# saved burst could never be replayed through it.
DEFAULT_FULL_SHOT_TAIL_FRAMES = 64
DEFAULT_DEPARTURE_TIMEOUT_SECONDS = 0.5
DEFAULT_CALIBRATION_IMAGE_PATH = Path("/var/lib/pinpoint/calibration-images")


def capture_retention() -> int:
    """Return the number of complete rolling bursts kept on the Pi."""
    try:
        value = int(os.getenv("PINPOINT_CAPTURE_RETENTION", str(DEFAULT_CAPTURE_RETENTION)))
    except ValueError as error:
        raise ValueError("PINPOINT_CAPTURE_RETENTION must be a positive integer") from error
    if value <= 0:
        raise ValueError("PINPOINT_CAPTURE_RETENTION must be a positive integer")
    return value


def latest_rolling_capture_preview() -> dict[str, Any] | None:
    """Return a deliberately small contact sheet suitable for BLE transfer."""
    root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
    captures = sorted(
        (path for path in root.glob("capture-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not captures:
        return None
    preview = captures[0] / "contact-sheet.jpg"
    if not preview.exists():
        return None
    return _contact_sheet_payload(captures[0].name, preview)


# The result is sent before a burst's frames reach the disk, so the app can ask for
# a burst that is still being written. Those requests wait for the write instead.
_pending_saves: dict[str, threading.Event] = {}
_pending_saves_lock = threading.Lock()
CAPTURE_SAVE_WAIT_S = 30.0


def _begin_capture_save(capture_id: str) -> None:
    with _pending_saves_lock:
        _pending_saves[capture_id] = threading.Event()


def _finish_capture_save(capture_id: str) -> None:
    with _pending_saves_lock:
        done = _pending_saves.pop(capture_id, None)
    if done is not None:
        done.set()


def _wait_for_capture_save(capture_id: str) -> None:
    with _pending_saves_lock:
        pending = _pending_saves.get(capture_id)
    if pending is not None:
        pending.wait(CAPTURE_SAVE_WAIT_S)


def capture_contact_sheet(capture_id: str) -> dict[str, Any]:
    """Return the saved contact sheet of one specific burst for BLE review."""
    if not re.fullmatch(r"capture-\d+", capture_id):
        raise ValueError("Invalid capture id")
    _wait_for_capture_save(capture_id)
    root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
    preview = root / capture_id / "contact-sheet.jpg"
    if not preview.exists():
        raise ValueError("Contact sheet is no longer available for this capture")
    return _contact_sheet_payload(capture_id, preview)


def _contact_sheet_payload(capture_id: str, preview: Path) -> dict[str, Any]:
    return {
        "mimeType": "image/jpeg",
        "base64": base64.b64encode(preview.read_bytes()).decode("ascii"),
        "captureId": capture_id,
    }


CALIBRATION_CAMERAS = ("primary", "secondary")


def _camera_key(camera: str | None) -> str:
    key = (camera or "primary").lower()
    if key not in CALIBRATION_CAMERAS:
        raise ValueError("Calibration camera must be 'primary' or 'secondary'.")
    return key


def _migrate_legacy_calibration_images(root: Path) -> None:
    """Move pre-per-camera views into the primary folder so counts survive the upgrade."""
    legacy_manifest = root / "manifest.json"
    if not legacy_manifest.exists():
        return
    destination = root / "primary"
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for path in [*sorted(root.glob("calib-*.jpg")), legacy_manifest]:
            path.replace(destination / path.name)
    except OSError as error:
        # Status reads call this; a read-only folder must not break them.
        LOGGER.warning("Could not move legacy calibration views into %s: %s", destination, error)


def _calibration_root(camera: str = "primary") -> Path:
    root = Path(os.getenv("PINPOINT_CALIBRATION_IMAGE_PATH", str(DEFAULT_CALIBRATION_IMAGE_PATH)))
    _migrate_legacy_calibration_images(root)
    return root / _camera_key(camera)


def _calibration_manifest(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return manifest if isinstance(manifest, list) else []


def _camera_capture_status(camera: str) -> dict[str, Any]:
    manifest = _calibration_manifest(_calibration_root(camera))
    return {
        "camera": _camera_key(camera),
        "totalSaved": len(manifest),
        "totalWithCorners": sum(1 for entry in manifest if entry.get("cornersFound")),
    }


def calibration_capture_status(camera: str | None = None) -> dict[str, Any]:
    """Counts for one camera, or every camera with the primary kept at the top level."""
    if camera is not None:
        return _camera_capture_status(camera)
    cameras = {key: _camera_capture_status(key) for key in CALIBRATION_CAMERAS}
    return {**cameras["primary"], "cameras": cameras}


def _intrinsics_path(camera: str) -> Path:
    if _camera_key(camera) == "primary":
        return Path(os.getenv("PINPOINT_INTRINSICS_PATH", "/var/lib/pinpoint/intrinsics.json"))
    return Path(
        os.getenv("PINPOINT_SECONDARY_INTRINSICS_PATH", "/var/lib/pinpoint/intrinsics-secondary.json")
    )


def lens_calibration_status() -> dict[str, dict[str, Any]]:
    """Report the installed intrinsics per camera so the app can show what is calibrated."""
    status: dict[str, dict[str, Any]] = {}
    for camera in CALIBRATION_CAMERAS:
        path = _intrinsics_path(camera)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(saved, dict) or "cameraMatrix" not in saved:
            continue
        status[camera] = {
            "rmsPx": saved.get("rmsPx"),
            "imageSize": saved.get("imageSize"),
            "views": len(saved.get("views") or []),
            "savedTo": str(path),
        }
    return status


def clear_calibration_images(camera: str = "primary") -> dict[str, Any]:
    """Discard one camera's saved checkerboard views so a bad batch can be redone."""
    root = _calibration_root(camera)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return calibration_capture_status(camera)


def save_calibration_frame(frame: Any, camera: str = "primary") -> dict[str, Any]:
    """Save one on-demand full-resolution frame and report whether its checkerboard resolved.

    Runs inline in the camera thread so the app gets near-instant feedback per shutter
    press, instead of discovering hours later (via SSH) that a whole batch was unusable.
    Each camera keeps its own folder and manifest; their views are never mixed.
    """
    root = _calibration_root(camera)
    root.mkdir(parents=True, exist_ok=True)
    manifest = _calibration_manifest(root)
    columns = int(os.getenv("PINPOINT_CALIBRATION_COLUMNS", "5"))
    rows = int(os.getenv("PINPOINT_CALIBRATION_ROWS", "5"))
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    found, _ = cv2.findChessboardCornersSB(gray, (columns, rows))
    index = len(manifest)
    filename = f"calib-{index:04d}.jpg"
    if not cv2.imwrite(str(root / filename), frame, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"Could not save calibration frame {filename}")
    manifest.append({"file": filename, "cornersFound": bool(found)})
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "index": index,
        "cornersFound": bool(found),
        "columns": columns,
        "rows": rows,
        "image": {"mimeType": "image/jpeg", "base64": base64.b64encode(encode_ble_preview(frame)).decode("ascii")},
        **calibration_capture_status(camera),
    }


def run_lens_calibration(camera: str = "primary") -> dict[str, Any]:
    """Run the checkerboard solve over one camera's saved views and install the result."""
    from lens_calibration import calibrate_from_images

    key = _camera_key(camera)
    root = _calibration_root(key)
    manifest = _calibration_manifest(root)
    if not manifest:
        raise ValueError("No calibration images saved yet. Capture at least 12 diverse checkerboard views first.")
    columns = int(os.getenv("PINPOINT_CALIBRATION_COLUMNS", "5"))
    rows = int(os.getenv("PINPOINT_CALIBRATION_ROWS", "5"))
    square_mm = float(os.getenv("PINPOINT_CALIBRATION_SQUARE_MM", "25"))
    paths = [root / entry["file"] for entry in manifest]
    result = calibrate_from_images(paths, columns, rows, square_mm)
    destination = _intrinsics_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {
        "camera": key,
        "rmsPx": result["rmsPx"],
        "viewsUsed": len(result["views"]),
        "viewsTotal": len(manifest),
        "imageSize": result["imageSize"],
        "savedTo": str(destination),
    }


@dataclass(frozen=True)
class BallEvent:
    present: bool
    frame_count: int = 0
    duration_ms: int = 0
    confidence: float = 0.0
    rolling_capture_frames: int = 0
    capture_id: str | None = None
    impact_frame_index: int | None = None
    analysis: dict[str, Any] | None = None


@dataclass(frozen=True)
class DetectionObservation:
    present: bool
    changed: bool
    confidence: float
    bounds: tuple[int, int, int, int] | None


def _is_staggered(capture: Any) -> bool:
    """True only for a real dual camera running staggered; fakes and single cameras are never staggered."""
    return isinstance(capture, DualCsiCapture) and getattr(capture, "stagger", False) is True


# Raw 10-bit frames are 0.5 MB each and the Pi has 1 GB, so only a short window around the shot is kept
# (about 100 frames per camera, 50 MB) and only the frames near the impact are written to disk.
RAW_RING_FRAMES = int(os.getenv("PINPOINT_RAW_BUFFER_FRAMES", "100"))
RAW_SAVE_BEFORE = int(os.getenv("PINPOINT_RAW_SAVE_BEFORE", "25"))
RAW_SAVE_AFTER = int(os.getenv("PINPOINT_RAW_SAVE_AFTER", "45"))
# The detector only confirms a departure ~100 frames after the hit, by which time a plain "last 100 frames" ring has
# already thrown away the frames before the impact (measured: every raw capture started 20 frames AFTER the hit).
# So the ring is pinned the moment the ball first looks gone: it keeps everything from just before that, adds the
# next RAW_AFTER_PIN frames and then stops adding raw frames (memory), until the departure is confirmed or dismissed.
RAW_PIN_BACK = RAW_SAVE_BEFORE + 5
RAW_AFTER_PIN = RAW_SAVE_AFTER + 15
RAW_HARD_CAP = int(os.getenv("PINPOINT_RAW_BUFFER_HARD_CAP", "160"))


class RollingFrameBuffer:
    """Keeps a compact diagnostic history until the ball leaves the view."""

    def __init__(self, max_frames: int) -> None:
        self.frames: deque[tuple[float, Any]] = deque(maxlen=max(1, max_frames))
        self.metadata: deque[dict[str, Any]] = deque(maxlen=max(1, max_frames))
        # (sensor timestamp, raw frame): the most recent RAW_RING_FRAMES, or from the pin point while pinned.
        self.raw: deque[tuple[int, Any]] = deque()
        self._raw_limit = max(1, min(max_frames, RAW_RING_FRAMES))
        self._raw_pin_stamp: int | None = None
        self._raw_after_pin = 0
        self.raw_black = 0
        self.secondary: RollingFrameBuffer | None = None

    def append(self, frame: Any, captured_at: float | None = None, metadata: dict[str, Any] | None = None,
               *, secondary_frame: Any = None, secondary_metadata: dict[str, Any] | None = None) -> None:
        if secondary_frame is not None:
            if self.secondary is None:
                if self.frames:
                    raise RuntimeError("Cannot add a second camera halfway through a burst")
                self.secondary = RollingFrameBuffer(self.frames.maxlen)
            self.secondary.append(secondary_frame, metadata=secondary_metadata)
        elif self.secondary is not None:
            raise RuntimeError("Second camera frame missing from paired burst")
        raw_frame = (metadata or {}).get("RawFrame")
        raw_black = raw_black_level(metadata) if raw_frame is not None else 0
        metadata = {key: value for key, value in (metadata or {}).items() if key in ("SensorTimestamp", "ExposureTime", "FrameDuration", "AnalogueGain") and isinstance(value, (int, float))}
        if metadata.get("SensorTimestamp"):
            captured_at = metadata["SensorTimestamp"] / 1e9
        if raw_frame is not None and metadata.get("SensorTimestamp"):
            self.raw_black = raw_black
            if self._raw_pin_stamp is None:
                self.raw.append((int(metadata["SensorTimestamp"]), raw_frame))
            else:
                self._raw_after_pin += 1
                if self._raw_after_pin <= RAW_AFTER_PIN:
                    self.raw.append((int(metadata["SensorTimestamp"]), raw_frame))
            self._evict_raw()
        # Callers pass a freshly-allocated array (see _append_capture_frame), so no copy
        # is needed here: duplicating every frame ~doubles peak memory on a 1 GB Pi.
        self.frames.append((time.time() if captured_at is None else captured_at, frame))
        self.metadata.append(metadata)

    @property
    def timestamp_source(self) -> str:
        return "sensor" if self.metadata and all(m.get("SensorTimestamp") for m in self.metadata) else "host"

    def _evict_raw(self) -> None:
        while len(self.raw) > RAW_HARD_CAP:
            self.raw.popleft()
        while len(self.raw) > self._raw_limit and (self._raw_pin_stamp is None or self.raw[0][0] < self._raw_pin_stamp):
            self.raw.popleft()

    def pin_raw(self, back_frames: int = RAW_PIN_BACK) -> None:
        """Keep the raw frames from `back_frames` before now: the ball has just looked gone (see RAW_AFTER_PIN)."""
        if self._raw_pin_stamp is None and self.metadata:
            index = max(0, len(self.metadata) - 1 - back_frames)
            self._raw_pin_stamp = self.metadata[index].get("SensorTimestamp") or None
            self._raw_after_pin = 0
        if self.secondary is not None:
            self.secondary.pin_raw(back_frames)

    def unpin_raw(self) -> None:
        """The departure was a false alarm: go back to a plain rolling window."""
        self._raw_pin_stamp = None
        self._raw_after_pin = 0
        self._evict_raw()
        if self.secondary is not None:
            self.secondary.unpin_raw()

    def clear(self) -> None:
        self.frames.clear()
        self.metadata.clear()
        self.raw.clear()
        self._raw_pin_stamp = None
        self._raw_after_pin = 0
        if self.secondary is not None:
            self.secondary.clear()

    def trim_after(self, last_index: int) -> None:
        """Discard detector-confirmation frames beyond the useful shot window."""
        while len(self.frames) > last_index + 1:
            self.frames.pop()
            self.metadata.pop()
        if self.raw and self.metadata:
            last_stamp = self.metadata[-1].get("SensorTimestamp") or 0
            while self.raw and self.raw[-1][0] > last_stamp:
                self.raw.pop()
        if self.secondary is not None:
            self.secondary.trim_after(last_index)

    def raw_by_index(self) -> dict[int, Any]:
        """Raw frames keyed by their position in `frames`, for the frames that still have one."""
        if not self.raw:
            return {}
        by_stamp = {stamp: frame for stamp, frame in self.raw}
        return {index: by_stamp[m["SensorTimestamp"]] for index, m in enumerate(self.metadata)
                if m.get("SensorTimestamp") in by_stamp}

    def _save_raw(self, destination: Path, impact_frame_index: int | None) -> dict[str, Any] | None:
        """Write the raw frames around the impact as 16-bit PNGs (value = 10-bit count x RAW_SCALE)."""
        frames = self.raw_by_index()
        if not frames:
            return None
        centre = impact_frame_index if impact_frame_index is not None else max(frames)
        wanted = sorted(index for index in frames if centre - RAW_SAVE_BEFORE <= index <= centre + RAW_SAVE_AFTER)
        for index in wanted:
            # Light compression: this runs on the Pi after the result has already been sent.
            if not cv2.imwrite(str(destination / f"raw-{index:04d}.png"), frames[index], [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                raise RuntimeError(f"Could not write raw frame {index}")
        return {"format": "png16", "valueIs": f"10-bit count x {RAW_SCALE}", "scale": RAW_SCALE,
                "blackLevel": self.raw_black, "frames": wanted}

    def save(
        self,
        destination: Path,
        fps: int,
        impact_frame_index: int | None = None,
        *,
        coarse_departure_frame_index: int | None = None,
        last_stationary_frame_index: int | None = None,
        first_moving_frame_index: int | None = None,
        ball_bounds: tuple[int, int, int, int] | None = None,
        include_calibration: bool = True,
        capture_id: str | None = None,
    ) -> int:
        if cv2 is None or not self.frames:
            return 0
        destination.mkdir(parents=True, exist_ok=True)
        started_at = self.frames[0][0]
        frame_times_ms = [round((captured_at - started_at) * 1000, 3) for captured_at, _ in self.frames]
        measured_duration_ms = frame_times_ms[-1] if len(frame_times_ms) > 1 else 0.0
        measured_fps = (
            round((len(frame_times_ms) - 1) * 1000 / measured_duration_ms, 2)
            if measured_duration_ms > 0
            else None
        )
        for index, (_, frame) in enumerate(self.frames):
            image_path = destination / f"frame-{index:04d}.jpg"
            if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"Could not write rolling capture frame {image_path}")
        self._save_contact_sheet(destination, impact_frame_index)
        raw_manifest = self._save_raw(destination, impact_frame_index)
        manifest = {
            "captureId": capture_id or destination.name,
            "capturedAtUnix": time.time() if self.timestamp_source == "sensor" else started_at,
            "timestampSource": self.timestamp_source,
            "frameMetadata": list(self.metadata),
            "frameCount": len(self.frames),
            "fps": fps,
            "measuredFps": measured_fps,
            "durationMs": round(measured_duration_ms, 3),
            "frameTimesMs": frame_times_ms,
            "impactFrameIndex": impact_frame_index,
            "coarseDepartureFrameIndex": coarse_departure_frame_index,
            "lastStationaryFrameIndex": last_stationary_frame_index,
            "firstMovingFrameIndex": first_moving_frame_index,
            "ballBounds": list(ball_bounds) if ball_bounds is not None else None,
            "purpose": "Ball departure evidence; physical launch metrics require validated tracking and calibration",
        }
        if raw_manifest is not None:
            manifest["raw"] = raw_manifest
        if self.secondary is not None:
            if len(self.secondary.frames) != len(self.frames) or self.timestamp_source != "sensor" or self.secondary.timestamp_source != "sensor":
                raise RuntimeError("Paired capture has incomplete frames or sensor timestamps")
            self.secondary.save(destination / "camera-secondary", fps, impact_frame_index,
                                include_calibration=False, capture_id=destination.name)
            offsets = [(b["SensorTimestamp"] - a["SensorTimestamp"]) / 1000
                       for a, b in zip(self.metadata, self.secondary.metadata)]
            absolute_offsets = sorted(abs(value) for value in offsets)
            median_offset = statistics.median(offsets)
            staggered = abs(median_offset) > 600.0
            manifest["dualCamera"] = {
                "mode": "stagger" if staggered else "software", "frameCount": len(offsets),
                "staggered": staggered, "staggerOffsetUs": round(median_offset, 1) if staggered else None,
                "primaryCameraIndex": int(os.getenv("PINPOINT_CAMERA_INDEX", "0")),
                "secondaryCameraIndex": int(os.getenv("PINPOINT_SECONDARY_CAMERA_INDEX", "1")),
                "secondaryPath": "camera-secondary", "pairOffsetsUs": offsets,
                "maxAbsOffsetUs": max(absolute_offsets),
                "medianAbsOffsetUs": absolute_offsets[len(absolute_offsets) // 2],
                "stereoCalibrated": False,
                "note": ("The top camera runs half a frame behind the lower one; analyse each view at its own timestamp."
                         if staggered else "Both views share the trigger. Stereo measurements are not calibrated."),
            }
        apriltag_calibration = load_apriltag_calibration() if include_calibration else None
        if apriltag_calibration is not None:
            manifest["aprilTagCalibration"] = apriltag_calibration
        secondary_calibration = load_apriltag_calibration("secondary") if include_calibration and self.secondary else None
        if secondary_calibration is not None:
            manifest["secondaryAprilTagCalibration"] = secondary_calibration
        if include_calibration and self.secondary:
            from stereo_calibration import read, root
            manifest["stereoCalibration"] = read(root() / "active.json")
        (destination / "capture.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        return len(self.frames)

    def _save_contact_sheet(self, destination: Path, impact_frame_index: int | None = None) -> None:
        sample_count = min(12, len(self.frames))
        if impact_frame_index is None:
            indexes = [round(index * (len(self.frames) - 1) / max(sample_count - 1, 1)) for index in range(sample_count)]
        else:
            offsets = (-30, -20, -12, -8, -4, -2, 0, 1, 2, 4, 8, 16)
            indexes = [min(len(self.frames) - 1, max(0, impact_frame_index + offset)) for offset in offsets]
        thumbnails = [
            cv2.resize(self.frames[index][1], (160, 100), interpolation=cv2.INTER_AREA)
            for index in indexes
        ]
        while len(thumbnails) % 4:
            thumbnails.append(thumbnails[-1].copy())
        rows = [cv2.hconcat(thumbnails[offset : offset + 4]) for offset in range(0, len(thumbnails), 4)]
        while len(rows) < 3:
            rows.append(rows[-1].copy())
        if not cv2.imwrite(str(destination / "contact-sheet.jpg"), cv2.vconcat(rows), [cv2.IMWRITE_JPEG_QUALITY, 65]):
            raise RuntimeError("Could not write rolling capture contact sheet")


@dataclass(frozen=True)
class DetectionConfig:
    roi: tuple[float, float, float, float]
    calibration_frames: int
    present_frames: int
    absent_frames: int
    difference_threshold: int
    min_area: float
    max_area: float
    min_circularity: float
    max_scene_change: float

    @classmethod
    def from_environment(cls) -> "DetectionConfig":
        return cls(
            roi=parse_roi(os.getenv("PINPOINT_BALL_ROI", DEFAULT_BALL_ROI)),
            calibration_frames=int(os.getenv("PINPOINT_BALL_CALIBRATION_FRAMES", "20")),
            present_frames=int(os.getenv("PINPOINT_BALL_PRESENT_FRAMES", "8")),
            absent_frames=int(os.getenv("PINPOINT_BALL_ABSENT_FRAMES", "5")),
            difference_threshold=int(os.getenv("PINPOINT_BALL_DIFFERENCE", "24")),
            min_area=float(os.getenv("PINPOINT_BALL_MIN_AREA", "180")),
            max_area=float(os.getenv("PINPOINT_BALL_MAX_AREA", "6000")),
            min_circularity=float(os.getenv("PINPOINT_BALL_MIN_CIRCULARITY", "0.38")),
            max_scene_change=float(os.getenv("PINPOINT_BALL_MAX_SCENE_CHANGE", "0.18")),
        )


def parse_roi(raw_value: str) -> tuple[float, float, float, float]:
    try:
        left, top, right, bottom = (float(value.strip()) for value in raw_value.split(","))
    except (TypeError, ValueError) as error:
        raise ValueError("PINPOINT_BALL_ROI must contain four comma-separated numbers") from error
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("PINPOINT_BALL_ROI must satisfy 0 <= left < right <= 1 and top < bottom")
    return left, top, right, bottom


def encode_ble_preview(frame: Any) -> bytes:
    """Compress a bounded grayscale placement preview for the BLE event channel."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for BLE camera previews")
    width = int(os.getenv("PINPOINT_BLE_PREVIEW_WIDTH", str(DEFAULT_PREVIEW_WIDTH)))
    height = int(os.getenv("PINPOINT_BLE_PREVIEW_HEIGHT", "100" if uses_csi() else str(DEFAULT_PREVIEW_HEIGHT)))
    quality = int(os.getenv("PINPOINT_BLE_PREVIEW_QUALITY", str(DEFAULT_PREVIEW_QUALITY)))
    max_bytes = int(
        os.getenv("PINPOINT_BLE_PREVIEW_MAX_BYTES", str(DEFAULT_PREVIEW_MAX_BYTES))
    )
    grayscale = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    for scale in (1.0, 0.8, 0.6):
        size = (max(48, round(width * scale)), max(36, round(height * scale)))
        resized = cv2.resize(grayscale, size, interpolation=cv2.INTER_AREA)
        encoded_ok, encoded = cv2.imencode(
            ".jpg",
            resized,
            [cv2.IMWRITE_JPEG_QUALITY, quality],
        )
        if not encoded_ok:
            continue
        payload = encoded.tobytes()
        if len(payload) <= max_bytes:
            return payload
    raise RuntimeError(f"BLE preview exceeded the {max_bytes}-byte limit")


def capture_frame_preview(capture_id: str, frame_index: int) -> dict[str, Any]:
    """Return one compact frame from a specific saved burst for BLE review."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for capture replay")
    if not re.fullmatch(r"capture-\d+", capture_id):
        raise ValueError("Invalid capture id")
    _wait_for_capture_save(capture_id)
    root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
    capture = root / capture_id
    manifest_path = capture / "capture.json"
    if not manifest_path.exists():
        raise ValueError("Capture is no longer available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_count = int(manifest.get("frameCount", 0))
    if not 0 <= frame_index < frame_count:
        raise ValueError(f"Frame index must be between 0 and {max(0, frame_count - 1)}")
    frame = cv2.imread(str(capture / f"frame-{frame_index:04d}.jpg"))
    if frame is None:
        raise ValueError("Capture frame is missing")
    result = {
        "mimeType": "image/jpeg",
        "base64": base64.b64encode(encode_ble_preview(frame)).decode("ascii"),
        "captureId": capture_id,
        "frameIndex": frame_index,
        "frameCount": frame_count,
        "timeMs": (manifest.get("frameTimesMs") or [None] * frame_count)[frame_index],
        "impactFrameIndex": manifest.get("impactFrameIndex"),
        "coarseDepartureFrameIndex": manifest.get("coarseDepartureFrameIndex"),
        "lastStationaryFrameIndex": manifest.get("lastStationaryFrameIndex"),
        "firstMovingFrameIndex": manifest.get("firstMovingFrameIndex"),
    }
    if manifest.get("dualCamera"):
        other = cv2.imread(str(capture / "camera-secondary" / f"frame-{frame_index:04d}.jpg"))
        if other is None:
            raise ValueError("Second camera capture frame is missing")
        result["secondaryBase64"] = base64.b64encode(encode_ble_preview(other)).decode("ascii")
        result["pairOffsetUs"] = manifest["dualCamera"]["pairOffsetsUs"][frame_index]
    return result


# Swing-loop clip: a fixed crop around the ball, club and early flight, small enough
# that a 24-frame loop crosses BLE (~12-16 KB/s) in a few seconds.
CLIP_MAX_FRAMES_PER_REQUEST = 8
CLIP_WIDTH_PX = 192
CLIP_MAX_BYTES = 2600
CLIP_BEHIND_RADII = 7.0
CLIP_AHEAD_RADII = 11.0
CLIP_ABOVE_RADII = 8.0
CLIP_BELOW_RADII = 3.0
# Display only: the short exposure leaves frames dark. One fixed curve for every frame, so
# the loop does not flicker; measurements never see it.
CLIP_DISPLAY_GAMMA = 0.55
_CLIP_LUT = None


def clip_crop_box(manifest: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """(x, y, w, h) around the resting ball: room behind for the club, ahead and above for flight."""
    bounds = manifest.get("ballBounds")
    if not bounds or len(bounds) != 4:
        return 0, 0, width, height
    x, y, w, h = bounds
    cx, cy, r = x + w / 2, y + h / 2, max(w, h) / 2
    left = int(max(0, cx - CLIP_BEHIND_RADII * r))
    right = int(min(width, cx + CLIP_AHEAD_RADII * r))
    top = int(max(0, cy - CLIP_ABOVE_RADII * r))
    bottom = int(min(height, cy + CLIP_BELOW_RADII * r))
    return left, top, max(1, right - left), max(1, bottom - top)


def encode_clip_frame(frame: Any, box: tuple[int, int, int, int]) -> bytes:
    x, y, w, h = box
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    global _CLIP_LUT
    if _CLIP_LUT is None:
        _CLIP_LUT = np.clip(((np.arange(256) / 255.0) ** CLIP_DISPLAY_GAMMA) * 255, 0, 255).astype(np.uint8)
    crop = cv2.LUT(gray[y:y + h, x:x + w], _CLIP_LUT)
    scale = min(1.0, CLIP_WIDTH_PX / max(1, crop.shape[1]))
    if scale < 1.0:
        crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    for quality in (40, 32, 24):
        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(encoded) <= CLIP_MAX_BYTES:
            return encoded.tobytes()
    ok, encoded = cv2.imencode(".jpg", cv2.resize(crop, None, fx=0.7, fy=0.7), [cv2.IMWRITE_JPEG_QUALITY, 25])
    if not ok:
        raise RuntimeError("Could not encode a clip frame")
    return encoded.tobytes()


def capture_clip(capture_id: str, start_frame: int, count: int) -> dict[str, Any]:
    """A batch of cropped lower-camera frames from a saved burst, for the app's swing loop."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for capture replay")
    if not re.fullmatch(r"capture-\d+", capture_id):
        raise ValueError("Invalid capture id")
    if not 1 <= count <= CLIP_MAX_FRAMES_PER_REQUEST:
        raise ValueError(f"Request 1-{CLIP_MAX_FRAMES_PER_REQUEST} frames at a time")
    _wait_for_capture_save(capture_id)
    root = Path(os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH)))
    capture = root / capture_id
    manifest_path = capture / "capture.json"
    if not manifest_path.exists():
        raise ValueError("Capture is no longer available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frame_count = int(manifest.get("frameCount", 0))
    if not 0 <= start_frame < frame_count:
        raise ValueError(f"Frame index must be between 0 and {max(0, frame_count - 1)}")
    times = manifest.get("frameTimesMs") or [None] * frame_count
    box = None
    frames = []
    for index in range(start_frame, min(frame_count, start_frame + count)):
        frame = cv2.imread(str(capture / f"frame-{index:04d}.jpg"))
        if frame is None:
            raise ValueError("Capture frame is missing")
        if box is None:
            box = clip_crop_box(manifest, frame.shape[1], frame.shape[0])
        frames.append({"frameIndex": index, "timeMs": times[index],
                       "base64": base64.b64encode(encode_clip_frame(frame, box)).decode("ascii")})
    return {
        "captureId": capture_id, "mimeType": "image/jpeg", "frameCount": frame_count,
        "cropBox": list(box), "frames": frames,
        "impactFrameIndex": manifest.get("impactFrameIndex"),
        "firstMovingFrameIndex": manifest.get("firstMovingFrameIndex"),
        "lastStationaryFrameIndex": manifest.get("lastStationaryFrameIndex"),
    }


def ball_template_similarity(
    reference_frame: Any,
    current_frame: Any,
    bounds: tuple[int, int, int, int],
) -> float:
    """Compare the armed ball with the same area after a possible departure."""
    x, y, width, height = bounds
    frame_height, frame_width = reference_frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame_width, x + width), min(frame_height, y + height)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return 0.0
    reference_crop = reference_frame[y0:y1, x0:x1]
    reference = reference_crop if len(reference_crop.shape) == 2 else cv2.cvtColor(reference_crop, cv2.COLOR_BGR2GRAY)
    if float(reference.std()) < 6:
        return 0.0  # A flat crop correlates with any flat surface; it cannot confirm a ball.
    margin_x = max(4, width // 4)
    margin_y = max(4, height // 4)
    search_x0, search_y0 = max(0, x0 - margin_x), max(0, y0 - margin_y)
    search_x1 = min(frame_width, x1 + margin_x)
    search_y1 = min(frame_height, y1 + margin_y)
    search_crop = current_frame[search_y0:search_y1, search_x0:search_x1]
    search = search_crop if len(search_crop.shape) == 2 else cv2.cvtColor(search_crop, cv2.COLOR_BGR2GRAY)
    if search.shape[0] < reference.shape[0] or search.shape[1] < reference.shape[1]:
        return 0.0
    scores = cv2.matchTemplate(search, reference, cv2.TM_CCOEFF_NORMED)
    return float(scores.max()) if scores.size else 0.0


def scale_bounds(bounds: tuple[int, int, int, int], source: tuple[int, int], target: tuple[int, int]) -> tuple[int, int, int, int]:
    """Convert detector coordinates to the full-resolution capture."""
    return tuple(round(value * target[index % 2] / source[index % 2]) for index, value in enumerate(bounds))


def _track_ball_from_stable_reference(
    frames: list[tuple[float, Any]],
    bounds: tuple[int, int, int, int],
    coarse_departure_index: int,
    ball_reference: Any | None = None,
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """Locate the last resting ball and first consistent outgoing observation.

    The presence detector is intentionally sampled and debounced, so its trigger
    can be later than the actual motion.  Tracking must therefore start from a
    known resting-ball image, never from ``coarse_departure_index - 1`` (which
    may already be an empty frame).
    """
    if not frames:
        return [], None, None
    x, y, width, height = bounds
    frame_height, frame_width = frames[0][1].shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(frame_width, x + width), min(frame_height, y + height)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return [], None, None

    # Production passes the confirmed armed-ball frame, but the ball can arm while
    # the placing hand still touches it. The earliest burst frame is a second
    # resting-ball candidate (and the only one for unit/offline analysis).
    references = [ball_reference] if ball_reference is not None else []
    references.append(frames[0][1])

    def prepare(image: Any) -> tuple[Any, Any, int] | None:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0 or float(crop.std()) < 5:
            return None
        # Blurring preserves the ball silhouette while reducing sensitivity to
        # dimple rotation, JPEG ringing and very short exposure noise.
        crop = cv2.GaussianBlur(crop, (5, 5), 0)
        # Full-resolution matching over every whole frame took ~17 ms per frame on the
        # Pi (4.6 s of a 5.9 s analysis). Find the best location at half resolution,
        # then re-score a small full-resolution window so scores keep their meaning.
        scale = 2 if min(crop.shape[:2]) >= 20 else 1
        small = cv2.resize(
            crop, (crop.shape[1] // scale, crop.shape[0] // scale), interpolation=cv2.INTER_AREA
        ) if scale > 1 else crop
        return crop, small, scale

    origin = np.array([x0 + (x1 - x0 - 1) / 2, y0 + (y1 - y0 - 1) / 2], dtype=float)
    seed_radius = max(3.0, min(x1 - x0, y1 - y0) / 2)

    def locate(frame_index: int, prepared: tuple[Any, Any, int]) -> dict[str, Any]:
        template, small_template, scale = prepared
        refine = 2 * scale
        frame = frames[frame_index][1]
        gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        search = cv2.GaussianBlur(gray, (5, 5), 0)
        left = top = 0
        if scale > 1:
            small = cv2.resize(search, (search.shape[1] // scale, search.shape[0] // scale), interpolation=cv2.INTER_AREA)
            _, _, _, coarse = cv2.minMaxLoc(cv2.matchTemplate(small, small_template, cv2.TM_CCOEFF_NORMED))
            left = max(0, coarse[0] * scale - refine)
            top = max(0, coarse[1] * scale - refine)
            right = min(search.shape[1], coarse[0] * scale + template.shape[1] + refine)
            bottom = min(search.shape[0], coarse[1] * scale + template.shape[0] + refine)
            search = search[top:bottom, left:right]
        scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, peak = cv2.minMaxLoc(scores)

        def subpixel(before: float, center: float, after: float) -> float:
            # Parabolic peak interpolation: whole-pixel centres quantised speed and
            # direction to ~1 px per frame.
            curvature = before - 2 * center + after
            return 0.0 if curvature >= 0 else float(np.clip(0.5 * (before - after) / curvature, -0.5, 0.5))

        px, py = peak
        dx = subpixel(scores[py, px - 1], score, scores[py, px + 1]) if 0 < px < scores.shape[1] - 1 else 0.0
        dy = subpixel(scores[py - 1, px], score, scores[py + 1, px]) if 0 < py < scores.shape[0] - 1 else 0.0
        location = (px + dx + left, py + dy + top)
        # Pixel-centre convention: a 23-pixel template starting at column 59 is centred on 70.
        center = np.array([location[0] + (template.shape[1] - 1) / 2, location[1] + (template.shape[0] - 1) / 2])
        return {
            "frameIndex": frame_index,
            "x": float(center[0]),
            "y": float(center[1]),
            "score": float(score),
            "distance": float(np.linalg.norm(center - origin)),
        }

    templates = [prepared for prepared in map(prepare, references) if prepared is not None]
    if not templates:
        return [], None, None
    template = templates[0]
    if len(templates) > 1:
        # Score how well each candidate finds a resting ball near the placement
        # bounds on a few pre-trigger frames (frame 0 excluded: it would match
        # itself perfectly). Keep the armed image unless the burst is clearly cleaner.
        last = min(len(frames), coarse_departure_index) - 1
        samples = sorted({1 + round(i * (last - 1) / 11) for i in range(12)}) if last >= 1 else [0]

        def resting_quality(prepared: tuple[Any, Any, int]) -> float:
            matches = (locate(index, prepared) for index in samples)
            return float(np.median([m["score"] if m["distance"] <= seed_radius * 2.5 else 0.0 for m in matches]))

        armed_quality, burst_quality = resting_quality(templates[0]), resting_quality(templates[1])
        if burst_quality > armed_quality + 0.05:
            template = templates[1]
    candidates = [locate(frame_index, template) for frame_index in range(len(frames))]

    # The placement bounds can precede a small ball adjustment. Re-anchor only
    # to three strong, nearby, stationary matches before the coarse trigger;
    # a far-away static lookalike must never become the resting-ball origin.
    for start in range(max(0, min(len(candidates), coarse_departure_index) - 2)):
        anchor = candidates[start:start + 3]
        centers = np.array([(point["x"], point["y"]) for point in anchor])
        center = centers.mean(axis=0)
        if (
            min(point["score"] for point in anchor) >= 0.78
            and np.linalg.norm(center - origin) <= seed_radius * 2.5
            and np.max(np.linalg.norm(centers - center, axis=1)) <= seed_radius * 0.2
        ):
            origin = center
            for point in candidates:
                point["distance"] = float(np.linalg.norm(np.array([point["x"], point["y"]]) - origin))
            break

    def outgoing(sequence: list[dict[str, Any]]) -> bool:
        # A persistent correlation at an offset location is stationary, even
        # when its distance from the placement bounds exceeds the threshold.
        return len(sequence) >= 3 and sequence[-1]["distance"] - sequence[0]["distance"] >= seed_radius * 0.5

    resting_indices = [
        candidate["frameIndex"] for candidate in candidates
        if candidate["score"] >= 0.78 and candidate["distance"] <= seed_radius * 0.4
    ]

    def departure(sequence: list[dict[str, Any]]) -> bool:
        return (
            outgoing(sequence)
            # A departing ball leaves from where it rested; a hand or club
            # lookalike moving elsewhere in the frame does not.
            and sequence[0]["distance"] <= seed_radius * 4.5
            # A resting ball matched again afterwards never left.
            and sum(index > sequence[-1]["frameIndex"] for index in resting_indices) < 3
        )

    # Require a short, spatially coherent outward sequence. This rejects an
    # isolated club/foot correlation elsewhere in the frame while accepting a
    # rotating dimpled ball whose template score naturally varies by frame.
    sequences: list[list[dict[str, Any]]] = []
    moving_sequence: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["score"] < 0.68 or candidate["distance"] <= seed_radius * 0.5:
            continue
        if moving_sequence:
            previous = moving_sequence[-1]
            frame_gap = candidate["frameIndex"] - previous["frameIndex"]
            step = math.dist((candidate["x"], candidate["y"]), (previous["x"], previous["y"]))
            if (
                frame_gap > 2
                or step > seed_radius * 4.5 * frame_gap
                or candidate["distance"] < previous["distance"] - seed_radius * 0.25
            ):
                sequences.append(moving_sequence)
                moving_sequence = [candidate]
                continue
        moving_sequence.append(candidate)
    sequences.append(moving_sequence)

    # The debounced trigger follows the real departure, so earlier outward
    # sequences are nudges or occlusion: use the last one before the trigger.
    departures = [sequence for sequence in sequences if departure(sequence)]
    before_trigger = [sequence for sequence in departures if sequence[0]["frameIndex"] <= coarse_departure_index + 2]
    moving_sequence = before_trigger[-1] if before_trigger else (departures[0] if departures else [])
    first_moving = moving_sequence[0]["frameIndex"] if moving_sequence else None
    stationary_limit = first_moving if first_moving is not None else min(len(frames), coarse_departure_index + 1)
    stationary = [
        candidate for candidate in candidates[:stationary_limit]
        if candidate["score"] >= 0.78 and candidate["distance"] <= seed_radius * 0.4
    ]
    last_stationary = stationary[-1]["frameIndex"] if stationary else None
    recent_stationary = stationary[-8:]
    track = [
        {"frameIndex": point["frameIndex"], "x": point["x"], "y": point["y"], "score": round(point["score"], 3)}
        for point in [*recent_stationary, *moving_sequence]
    ]
    return track, last_stationary, first_moving


def denoise_analysis_frames(frames, ball_reference=None):
    """Single-frame edge-preserving filter; never alters the retained raw burst."""
    mode = os.getenv("PINPOINT_ANALYSIS_DENOISE", "bilateral")
    if mode == "none":
        return frames, ball_reference
    if mode != "bilateral":
        raise ValueError("PINPOINT_ANALYSIS_DENOISE must be bilateral or none")
    def filtered(image):
        return cv2.bilateralFilter(image, 5, 12, 3) if image is not None else None
    return [(stamp, filtered(image)) for stamp, image in frames], filtered(ball_reference)


def analyze_departure(
    buffer: RollingFrameBuffer,
    bounds: tuple[int, int, int, int],
    impact_index: int,
    ball_reference: Any | None = None,
) -> dict[str, Any]:
    """Inspect actual frames without inventing physical launch measurements.

    Template matches provide image-plane motion evidence only. A hand can move
    a ball too, so even a consistent track is not proof of club contact.
    """
    import numpy as np
    from launch_measurements import measure_launch

    frames = list(buffer.frames)
    raw_frames = frames
    denoise_started = time.monotonic()
    frames, ball_reference = denoise_analysis_frames(frames, ball_reference)
    denoise_ms = (time.monotonic() - denoise_started) * 1000
    coarse_departure_index = max(0, min(impact_index, len(frames) - 1))
    x, y, width, height = bounds
    track, last_stationary_index, first_moving_index = _track_ball_from_stable_reference(
        frames, bounds, coarse_departure_index, ball_reference
    )
    analysis_index = first_moving_index if first_moving_index is not None else coarse_departure_index
    moving = [point for point in track if first_moving_index is not None and point["frameIndex"] >= first_moving_index
              and math.dist((point["x"], point["y"]), (x + width / 2, y + height / 2)) > max(width, height)]
    intervals = np.diff([stamp for stamp, _ in frames])
    valid_timing = bool(len(intervals) and np.all(intervals > 0))
    duration = frames[-1][0] - frames[0][0]
    fps = (len(frames) - 1) / duration if valid_timing else None
    warnings = ["Ball departure does not prove club contact; lifting the ball can trigger a capture."]
    if buffer.timestamp_source != "sensor":
        warnings.append("Observed FPS uses host frame-arrival times, not sensor exposure timestamps.")
    exposures = [m.get("ExposureTime") for m in buffer.metadata]
    exposure = max(exposures) if exposures and all(isinstance(v, (int, float)) and v > 0 for v in exposures) else None
    measurements = measure_launch(
        frames, bounds, analysis_index, buffer.timestamp_source, exposure,
        motion_track=track, secondary_frames=list(buffer.secondary.frames) if buffer.secondary is not None else None,
    )
    try:
        light = get_light_controller()
        strobe, strobe_report = estimate_with_report(
            raw_frames, bounds, analysis_index, light.status() if light else None,
            raw_frames=buffer.raw_by_index(), raw_black=buffer.raw_black or 1024.0)
    except Exception:  # noqa: BLE001 - an optional estimate must never break the analysis
        LOGGER.exception("Strobe copy analysis failed")
        strobe, strobe_report = None, None
    try:
        light_status = get_light_controller().status() if get_light_controller() else {}
        raw_scene = None
        if buffer.raw:
            counts = (np.asarray(buffer.raw[-1][1])[::4, ::4].astype(np.float32) - (buffer.raw_black or 1024)) / RAW_SCALE
            raw_scene = float(np.percentile(counts, 99.5))
        picture_scene = float(np.percentile(np.asarray(frames[len(frames) // 2][1])[::4, ::4], 99.5))
        original_failure = measurements.get("failure")
        measurements["failure"] = None if strobe is not None else friendly_failure(
            original_failure, exposure_us=exposure, light_mode=light_status.get("mode"),
            ball_px=float(max(bounds[2], bounds[3])), scene_p995_counts=raw_scene, picture_p995=picture_scene,
            strobe=strobe_report)
        if measurements["failure"] != original_failure:
            # A strobe fit measured the shot, so the ordinary path's exposure complaint no longer applies.
            measurements.setdefault("diagnostics", {})["rejection"] = {"original": original_failure}
    except Exception:  # noqa: BLE001 - explaining a failure must never turn it into a different one
        LOGGER.exception("Could not explain the rejection")
    measurements.setdefault("diagnostics", {})["preprocessing"] = {
        "version": 1, "denoise": os.getenv("PINPOINT_ANALYSIS_DENOISE", "bilateral"),
        "diameter": 5, "sigmaColor": 12, "sigmaSpace": 3,
        "elapsedMs": round(denoise_ms, 1), "rawFramesPreserved": True,
    }
    if strobe_report is not None:
        measurements["diagnostics"]["strobe"] = strobe_report
    if strobe is not None:
        metrics = measurements.setdefault("metrics", {})
        for key, entry in metrics_from_fit(strobe["fit"]).items():
            if (metrics.get(key) or {}).get("status", "unavailable") == "unavailable":
                metrics[key] = entry
        measurements["diagnostics"]["strobe"].update({"frameIndex": strobe["frameIndex"], "copies": strobe["fit"]["copies"],
                                                      "fitResidualMm": strobe["fit"]["fitResidualMm"], "source": strobe["source"]})
        warnings.append("Ball speed and launch angle come from flash copies across %d frames (two per frame): image-plane estimates."
                        % strobe["fit"]["frames"] if strobe["fit"].get("method") == "pairs"
                        else "Ball speed and launch angle come from flash copies in one frame: image-plane estimates.")
    measured_first_moving = measurements.get("estimatedImpactFrameIndex")
    if isinstance(measured_first_moving, int):
        first_moving_index = min(first_moving_index, measured_first_moving) if first_moving_index is not None else measured_first_moving
    index = first_moving_index if first_moving_index is not None else coarse_departure_index
    reference_index = last_stationary_index if last_stationary_index is not None else max(0, index - 1)
    reference = raw_frames[reference_index][1]
    if measurements.get("failure"):
        warnings.append(measurements["failure"])
    warnings.extend(warning for warning in measurements.get("warnings", []) if warning not in warnings)
    stereo = measurements.get("diagnostics", {}).get("stereo") or {}
    if "speedMps" in stereo:
        warnings.append("Ball depth cross-checked by the top camera; values still need validation against a reference launch monitor.")
    else:
        warnings.append("Monocular measurements are estimates pending physical reference validation.")
    tracked = [p["centerPx"] for p in measurements.get("ballTrack3d", []) if p.get("centerPx")]
    motion_observed = len(moving) >= 3 or len(tracked) >= 3
    if not motion_observed:
        warnings.append("Too few outgoing ball matches to resolve motion. Check exposure, lighting, field of view and frame rate.")
    if first_moving_index is None:
        warnings.append("Contact window unavailable; the saved marker is only the coarse disappearance trigger, not measured impact.")
    elif last_stationary_index is not None:
        warnings.append("Contact is bounded by the last stationary and first moving frames; exact club contact can fall between exposures.")
    if not valid_timing or (fps and float(intervals.max()) > 2.5 / fps):
        warnings.append("Frame timing is irregular or frames were dropped; speed measurement is unsafe.")
    annotated = cv2.cvtColor(reference, cv2.COLOR_GRAY2BGR) if len(reference.shape) == 2 else reference.copy()
    cv2.rectangle(annotated, (x, y), (x + width, y + height), (0, 220, 255), 2)
    for point in moving:
        cv2.circle(annotated, (round(point["x"]), round(point["y"])), 3, (0, 220, 255), -1)
    for px, py in tracked:
        cv2.circle(annotated, (round(px), round(py)), 4, (80, 255, 120), 1)
    return {"classification": "motion-observed" if motion_observed else "unconfirmed-departure",
            "frameCount": len(frames), "captureDurationMs": round(max(0, duration) * 1000),
            "measuredFps": round(fps, 1) if fps else None, "impactFrameIndex": index,
            "coarseDepartureFrameIndex": coarse_departure_index,
            "lastStationaryFrameIndex": last_stationary_index,
            "firstMovingFrameIndex": first_moving_index,
            "imageFrameIndex": reference_index, "track": track, "warnings": warnings,
            "measurements": measurements,
            "image": {"mimeType": "image/jpeg", "base64": base64.b64encode(encode_ble_preview(annotated)).decode("ascii")}}


class BallPresenceDetector:
    """Detect a newly placed compact round object against an empty-scene reference."""

    def __init__(self, config: DetectionConfig | None = None) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for automatic ball detection")
        self.config = config or DetectionConfig.from_environment()
        self.background: Any | None = None
        self.calibration_count = 0
        self.present_streak = 0
        self.absent_streak = 0
        self.stable_present = False
        self.candidate_bounds: tuple[int, int, int, int] | None = None
        self.stable_bounds: tuple[int, int, int, int] | None = None
        # Largest foreground blob of the last sample, accepted or not, so a marginal
        # ball can be diagnosed from the diagnostics instead of guessed at.
        self.last_candidate: dict[str, Any] | None = None
        self._kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    @property
    def calibrated(self) -> bool:
        return self.calibration_count >= self.config.calibration_frames

    def preview_detection(self, observation: DetectionObservation, width: int, height: int) -> dict[str, Any]:
        # A single lighting/noise sample may temporarily hide the contour. Keep
        # the last confirmed bounds while the debounced state remains present.
        bounds = self.stable_bounds if observation.present else None
        preview: dict[str, Any] = {
            "state": "calibrating" if not self.calibrated else "detected" if observation.present else "waiting",
            "bounds": [bounds[0] / width, bounds[1] / height, bounds[2] / width, bounds[3] / height] if bounds else None,
        }
        if self.last_candidate is not None:
            preview["candidate"] = self.last_candidate
        return preview

    def update(self, frame: Any) -> DetectionObservation:
        left, top, right, bottom = self._pixel_roi(frame)
        gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if not self.calibrated:
            if self.background is None:
                self.background = gray.copy()
            else:
                self.background = cv2.addWeighted(gray, 0.18, self.background, 0.82, 0)
            self.calibration_count += 1
            return DetectionObservation(False, False, 0.0, None)

        # Mains/PWM lamp flicker beats against the sample cadence and shifts the whole
        # frame's brightness by more than the difference threshold in the lit band,
        # which reads as a huge scene change; scale to the background's mean first.
        gain = float(self.background.mean()) / max(float(gray.mean()), 1.0)
        if 0.5 < gain < 2.0 and abs(gain - 1.0) > 0.005:
            gray = np.clip(gray.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        # Brighter-than-background only: a white ball is; the dark hole it leaves
        # behind once it has been baked into the background (or its shadow) is not,
        # and an absolute difference armed on exactly such holes as "balls".
        difference = cv2.subtract(gray, self.background)
        _, mask = cv2.threshold(
            difference,
            self.config.difference_threshold,
            255,
            cv2.THRESH_BINARY,
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel_close)
        changed_ratio = cv2.countNonZero(mask) / float(mask.shape[0] * mask.shape[1])
        raw_present, confidence, bounds = self._best_candidate(mask, left, top)
        scene_busy = changed_ratio > self.config.max_scene_change
        if scene_busy and not self.stable_present:
            raw_present, confidence, bounds = False, 0.0, None

        changed = False
        if not self.stable_present:
            if raw_present and self._same_candidate(bounds, self.candidate_bounds):
                self.present_streak += 1
            elif raw_present:
                self.present_streak = 1
            else:
                self.present_streak = 0
            self.candidate_bounds = bounds if raw_present else None
            self.absent_streak = 0
        else:
            matches_armed_ball = raw_present and self._same_candidate(bounds, self.stable_bounds)
            if matches_armed_ball:
                self.absent_streak = 0
            elif scene_busy:
                # A busy scene (swing, follow-through, the player's arm) neither confirms
                # nor clears the ball: hold the streak rather than restarting it, or a
                # long follow-through postpones the removal until the departure has
                # scrolled out of the frame buffer.
                bounds = None
            else:
                self.absent_streak += 1
                bounds = None

        if not self.stable_present and self.present_streak >= self.config.present_frames:
            self.stable_present = True
            self.stable_bounds = bounds
            self.absent_streak = 0
            changed = True
        elif self.stable_present and self.absent_streak >= self.config.absent_frames:
            self.stable_present = False
            self.present_streak = 0
            self.candidate_bounds = None
            self.stable_bounds = None
            changed = True

        if not self.stable_present and not raw_present and changed_ratio < 0.03:
            self.background = cv2.addWeighted(gray, 0.03, self.background, 0.97, 0)

        return DetectionObservation(self.stable_present, changed, confidence, bounds)

    def foreground_fraction(self, detection_gray: Any, bounds: tuple[int, int, int, int], margin: float = 1.0) -> float:
        """Share of the armed ball's neighbourhood that is brighter than the learned background.

        A club head resting on the ball at address covers a region several times the
        ball's size; the ball being gone leaves the neighbourhood looking like background.
        """
        if self.background is None:
            return 0.0
        left, top, right, bottom = self._pixel_roi(detection_gray)
        gray = cv2.GaussianBlur(detection_gray[top:bottom, left:right], (5, 5), 0)
        gain = float(self.background.mean()) / max(float(gray.mean()), 1.0)
        if 0.5 < gain < 2.0:
            gray = np.clip(gray.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        _, mask = cv2.threshold(cv2.subtract(gray, self.background), self.config.difference_threshold, 255, cv2.THRESH_BINARY)
        x, y, width, height = bounds
        x0 = max(0, int(x - left - width * margin))
        y0 = max(0, int(y - top - height * margin))
        x1 = min(mask.shape[1], int(x - left + width * (1 + margin)))
        y1 = min(mask.shape[0], int(y - top + height * (1 + margin)))
        region = mask[y0:y1, x0:x1]
        return float((region > 0).mean()) if region.size else 0.0

    @staticmethod
    def _same_candidate(
        current: tuple[int, int, int, int] | None,
        previous: tuple[int, int, int, int] | None,
    ) -> bool:
        if current is None:
            return False
        if previous is None:
            return True
        current_x, current_y, current_width, current_height = current
        previous_x, previous_y, previous_width, previous_height = previous
        current_center = (current_x + current_width / 2, current_y + current_height / 2)
        previous_center = (previous_x + previous_width / 2, previous_y + previous_height / 2)
        distance = math.dist(current_center, previous_center)
        movement_limit = max(18.0, max(previous_width, previous_height) * 1.25)
        width_ratio = current_width / max(previous_width, 1)
        height_ratio = current_height / max(previous_height, 1)
        return (
            distance <= movement_limit
            and 0.5 <= width_ratio <= 2.0
            and 0.5 <= height_ratio <= 2.0
        )

    def _pixel_roi(self, frame: Any) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        left, top, right, bottom = self.config.roi
        return (
            round(left * width),
            round(top * height),
            round(right * width),
            round(bottom * height),
        )

    def _best_candidate(
        self,
        mask: Any,
        offset_x: int,
        offset_y: int,
    ) -> tuple[bool, float, tuple[int, int, int, int] | None]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_confidence = 0.0
        best_bounds: tuple[int, int, int, int] | None = None
        largest: dict[str, Any] | None = None
        for contour in contours:
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            circularity = 4 * math.pi * area / (perimeter * perimeter)
            x, y, width, height = cv2.boundingRect(contour)
            aspect_ratio = width / max(height, 1)
            if area >= 40 and (largest is None or area > largest["area"]):
                rejected = (
                    "area" if not self.config.min_area <= area <= self.config.max_area
                    else "circularity" if circularity < self.config.min_circularity
                    else "aspect" if not 0.48 <= aspect_ratio <= 2.1
                    else None
                )
                largest = {"area": int(area), "circularity": round(circularity, 2), "aspect": round(aspect_ratio, 2),
                           "bounds": [x + offset_x, y + offset_y, width, height], "rejected": rejected}
            if not self.config.min_area <= area <= self.config.max_area:
                continue
            if circularity < self.config.min_circularity or not 0.48 <= aspect_ratio <= 2.1:
                continue
            # A contour clipped by the ROI boundary is usually a hand, shadow,
            # or illumination change outside the hitting zone. A placed ball
            # must be fully enclosed so its roundness and size are meaningful.
            edge_margin = 2
            if (
                x <= edge_margin
                or y <= edge_margin
                or x + width >= mask.shape[1] - edge_margin
                or y + height >= mask.shape[0] - edge_margin
            ):
                continue
            area_score = min(1.0, area / max(self.config.min_area * 3, 1))
            confidence = min(0.99, circularity * 0.75 + area_score * 0.25)
            if confidence > best_confidence:
                best_confidence = confidence
                best_bounds = (x + offset_x, y + offset_y, width, height)
        self.last_candidate = largest
        return best_bounds is not None, best_confidence, best_bounds


class BackgroundJob:
    """Run one slow job at a time on a worker thread, refusing new work while busy."""

    def __init__(self, job: Callable[..., None], name: str) -> None:
        self._job = job
        self._pending: tuple[Any, ...] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, *args: Any) -> bool:
        with self._lock:
            if self._stopped or self._pending is not None:
                return False
            self._pending = args
        self._wake.set()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._stopped = True
        self._wake.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                if self._stopped:
                    return
                args = self._pending
            if args is None:
                continue
            try:
                self._job(*args)
            except Exception:
                LOGGER.exception("Background job failed")
            finally:
                with self._lock:
                    self._pending = None


def _calibration_brightness(result: dict[str, Any]) -> float | None:
    """The brightness a completed exposure sweep reports, for the adaptive policy."""
    for key in ("ballLevel", "meanBrightness"):
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


class BallMonitor:
    """Own one CSI/USB stream for detection, BLE previews, and focus snapshots."""

    def __init__(self, camera_device: Path | None) -> None:
        self.camera_device = camera_device
        self.width = int(os.getenv("PINPOINT_DETECTOR_WIDTH", "640"))
        self.height = int(os.getenv("PINPOINT_DETECTOR_HEIGHT", "400" if uses_csi() else "480"))
        self.fps = int(os.getenv("PINPOINT_CAMERA_FPS", "30"))
        self.frame_stride = max(1, int(os.getenv("PINPOINT_BALL_FRAME_STRIDE", "4" if uses_csi() else "3")))
        self.raw_analysis = RawAnalysis(get_light_controller())
        # Cached light mode so the raw-frame gate below never re-reads settings per frame.
        self._light_mode_cache = "auto"
        self._light_mode_checked_at = 0.0
        self.preview_interval = max(
            1.0,
            float(os.getenv("PINPOINT_BLE_PREVIEW_INTERVAL_SECONDS", "3")),
        )
        self.output_path = Path(
            os.getenv("PINPOINT_USB_CAPTURE_PATH", str(DEFAULT_CAPTURE_PATH))
        )
        self.pre_impact_frames = max(1, int(os.getenv("PINPOINT_PRE_IMPACT_FRAMES", str(DEFAULT_PRE_IMPACT_FRAMES))))
        self.post_impact_frames = max(1, int(os.getenv("PINPOINT_POST_IMPACT_FRAMES", str(DEFAULT_POST_IMPACT_FRAMES))))
        self.full_shot_tail_frames = max(1, int(os.getenv("PINPOINT_FULL_SHOT_TAIL_FRAMES", str(DEFAULT_FULL_SHOT_TAIL_FRAMES))))
        self.departure_timeout_s = float(
            os.getenv("PINPOINT_DEPARTURE_TIMEOUT_SECONDS", str(DEFAULT_DEPARTURE_TIMEOUT_SECONDS))
        )
        self.rolling_capture_path = Path(
            os.getenv("PINPOINT_ROLLING_CAPTURE_PATH", str(DEFAULT_ROLLING_CAPTURE_PATH))
        )

    def run(
        self,
        stop_event: threading.Event,
        emit: Callable[[BallEvent], None],
        emit_preview: Callable[[bytes], None] | None = None,
        reset_event: threading.Event | None = None,
        calibration_capture_event: threading.Event | None = None,
        emit_calibration_result: Callable[[dict[str, Any]], None] | None = None,
        exposure_calibration_event: threading.Event | None = None,
        emit_exposure_calibration: Callable[[dict[str, Any]], None] | None = None,
        calibration_capture_camera: Callable[[], str] | None = None,
        capture_mode: Callable[[], str] | None = None,
        current_club: Callable[[], str] | None = None,
        emit_readiness: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for automatic ball detection")
        # Continuous auto light mode: re-sweep when the club or the room changes.
        adaptive = AdaptivePolicy() if uses_csi() else None
        while not stop_event.is_set():
            try:
                capture = self._open_camera()
            except Exception:
                LOGGER.exception("Camera open failed; retrying in two seconds")
                stop_event.wait(2)
                continue
            if not capture.isOpened():
                LOGGER.warning("Cannot open ball-detection camera %s; retrying", self.camera_device)
                capture.release()
                stop_event.wait(2)
                continue

            detector = BallPresenceDetector()
            apriltag_detector = AprilTagDetector()
            preview_job = BackgroundJob(
                lambda preview_frame, roi, secondary: self._publish_preview(preview_frame, roi, apriltag_detector, emit_preview, secondary),
                "pinpoint-preview",
            )
            # Circle fits in both views take tens of milliseconds; off the acquisition loop.
            readiness_job = BackgroundJob(
                lambda lower, upper, bounds: emit_readiness(self._readiness_checks(lower, upper, bounds)),
                "pinpoint-readiness",
            ) if emit_readiness is not None else None
            frame_index = 0
            failed_reads = 0
            ball_started = 0.0
            observed_ball_frames = 0
            last_ball_frame: Any | None = None
            armed_ball_bounds: tuple[int, int, int, int] | None = None
            suspected_departure_at: float | None = None
            false_removal_rejections = 0
            occlusion_rejections = 0
            calibration_logged = False
            last_preview_at = 0.0
            stereo_was_paused = False
            # Stable removal is intentionally debounced. Retain those sampled
            # frames as well, otherwise the actual impact is overwritten before
            # the capture is saved.
            removal_debounce_frames = (detector.config.absent_frames + 1) * self.frame_stride
            rolling_frames = RollingFrameBuffer(
                self.pre_impact_frames + removal_debounce_frames + self.post_impact_frames
            )
            warmup_until = time.monotonic() + (3 if uses_csi() else 0)
            adaptive_checked_at = 0.0
            detection_enabled = os.getenv("PINPOINT_AUTO_BALL_DETECTION", "false").lower() in {"1", "true", "yes"}
            LOGGER.info("Ball monitor opened %s", "CSI/Picamera2" if uses_csi() else self.camera_device)
            try:
                while not stop_event.is_set():
                    if reset_event is not None and reset_event.is_set():
                        detector = BallPresenceDetector()
                        ball_started = 0.0
                        observed_ball_frames = 0
                        last_ball_frame = None
                        armed_ball_bounds = None
                        suspected_departure_at = None
                        false_removal_rejections = 0
                        occlusion_rejections = 0
                        rolling_frames.clear()
                        calibration_logged = False
                        reset_event.clear()
                        LOGGER.info("Ball detector empty-plane calibration reset; keep the detection area clear")
                    if _is_staggered(capture):
                        # The second camera may only be restarted while the mat is empty.
                        capture.idle = not detector.stable_present and suspected_departure_at is None
                    ok, frame = capture.read()
                    if not ok:
                        failed_reads += 1
                        if failed_reads >= 10:
                            LOGGER.warning("Camera reads failed repeatedly; reopening the device")
                            if detection_enabled:
                                emit(BallEvent(False))
                            break
                        continue
                    failed_reads = 0
                    frame_index += 1
                    self.raw_analysis.hold = bool(detector.stable_present or armed_ball_bounds is not None
                                                  or suspected_departure_at is not None)
                    frame = self._analysis_frames(capture, frame)
                    if self.raw_analysis.consume_change():
                        # An empty-plane reference learned from one kind of frame is wrong for the other.
                        LOGGER.info("Analysis frames switched to %s; restarting ball detector calibration",
                                    "raw 10-bit" if self.raw_analysis.active() else "the 8-bit picture")
                        if detection_enabled and (detector.stable_present or armed_ball_bounds is not None):
                            # The restart forgets the ball; say so, or the app and the status LED keep showing a ball
                            # the detector no longer has.
                            emit(BallEvent(False))
                        detector = BallPresenceDetector()
                        rolling_frames.clear()
                        calibration_logged = False
                        armed_ball_bounds = None
                        suspected_departure_at = None
                        warmup_until = time.monotonic() + 3
                        continue
                    if _is_staggered(capture) and capture.pairing_ok is False:
                        # Out of step or re-locking: nothing measured now would pair up, so the ball cannot arm.
                        # The camera re-locks itself as soon as the mat is empty.
                        rolling_frames.clear()
                        continue
                    if calibration_capture_event is not None and calibration_capture_event.is_set():
                        calibration_capture_event.clear()
                        requested = calibration_capture_camera() if calibration_capture_camera else "primary"
                        if requested not in (*CALIBRATION_CAMERAS, "stereo"):
                            requested = "primary"
                        try:
                            source = frame
                            if requested == "secondary":
                                if not isinstance(capture, DualCsiCapture) or capture.secondary_frame is None:
                                    raise RuntimeError("The second camera is not streaming.")
                                source = capture.secondary_frame.copy()
                            if requested == "stereo":
                                from stereo_calibration import capture_pair
                                if not isinstance(capture, DualCsiCapture):
                                    raise ValueError("Both cameras must be streaming for a stereo pair.")
                                if _is_staggered(capture):
                                    raise ValueError("Calibrate the camera pair with staggered capture off (PINPOINT_CAMERA_STAGGER): "
                                                     "the two views must be taken at the same instant.")
                                result = {"stereo": True, "data": capture_pair(
                                    frame, capture.secondary_frame,
                                    [capture.metadata.get("SensorTimestamp"), capture.secondary_metadata.get("SensorTimestamp")],
                                    [camera.index for camera in capture.cameras])}
                            else:
                                result = save_calibration_frame(source, requested)
                        except (OSError, RuntimeError, ValueError, cv2.error) as error:
                            LOGGER.warning("Calibration frame capture failed: %s", error)
                            if emit_calibration_result is not None:
                                emit_calibration_result({
                                    "error": str(error),
                                    **({"stereo": True} if requested == "stereo" else calibration_capture_status(requested)),
                                })
                        else:
                            if emit_calibration_result is not None:
                                emit_calibration_result(result)
                    if exposure_calibration_event is not None and exposure_calibration_event.is_set():
                        exposure_calibration_event.clear()
                        # The sweep borrows this loop's own reads, so it never opens a
                        # second handle on the camera or races the detector for frames.
                        exposure_result = self._run_exposure_calibration(capture, stop_event)
                        if adaptive is not None:
                            bright = _calibration_brightness(exposure_result)
                            if bright is None:
                                bright = ViewSample.from_frame(frame).bright
                            adaptive.record(current_club() if current_club else None, bright, time.monotonic())
                        if emit_exposure_calibration is not None:
                            emit_exposure_calibration(exposure_result)
                        # Probe frames are not of the hitting area as it will be, and the
                        # new exposure changes what "empty" looks like.
                        detector = BallPresenceDetector()
                        rolling_frames.clear()
                        calibration_logged = False
                        warmup_until = time.monotonic() + (3 if uses_csi() else 0)
                        continue
                    # Continuous auto light mode: re-sweep when the club or the room
                    # changed while the mat is empty. The manual event above shares the
                    # same sweep, so both paths record into the policy to avoid a repeat.
                    adaptive_now = time.monotonic()
                    if adaptive is not None and adaptive_now >= warmup_until and adaptive_now - adaptive_checked_at >= CHECK_INTERVAL_S:
                        adaptive_checked_at = adaptive_now
                        if (
                            not detector.stable_present
                            and armed_ball_bounds is None
                            and suspected_departure_at is None
                            and light_mode() == "auto"
                        ):
                            club_id = current_club() if current_club else None
                            sample = ViewSample.from_frame(frame)
                            reason = adaptive.should_recalibrate(club_id, sample, adaptive_now)
                            if reason is not None:
                                LOGGER.info("Auto light/exposure sweep (%s) for club %s", reason, club_id)
                                set_exposure_cap_hint(club_exposure_cap_us(
                                    club_id, bool(capture_mode and capture_mode() == "putting")))
                                exposure_result = self._run_exposure_calibration(capture, stop_event)
                                bright = _calibration_brightness(exposure_result)
                                adaptive.record(club_id, bright if bright is not None else sample.bright, time.monotonic())
                                if emit_exposure_calibration is not None:
                                    emit_exposure_calibration(exposure_result)
                                # The new exposure changes what "empty" looks like.
                                detector = BallPresenceDetector()
                                rolling_frames.clear()
                                calibration_logged = False
                                armed_ball_bounds = None
                                suspected_departure_at = None
                                warmup_until = time.monotonic() + (3 if uses_csi() else 0)
                                continue
                    from stereo_calibration import capture_paused
                    if capture_paused():
                        stereo_was_paused = True
                        rolling_frames.clear()
                        if time.monotonic() - last_preview_at >= self.preview_interval:
                            secondary = capture.secondary_frame.copy() if isinstance(capture, DualCsiCapture) else None
                            if preview_job.submit(frame.copy(), detector._pixel_roi(frame), secondary):
                                last_preview_at = time.monotonic()
                        continue
                    if stereo_was_paused:
                        detector = BallPresenceDetector()
                        rolling_frames.clear()
                        calibration_logged = False
                        armed_ball_bounds = None
                        suspected_departure_at = None
                        warmup_until = time.monotonic() + 3
                        stereo_was_paused = False
                    if detector.calibrated:
                        self._append_capture_frame(rolling_frames, capture, frame)
                    if frame_index % self.frame_stride:
                        continue

                    current_time = time.monotonic()
                    if current_time < warmup_until:
                        continue
                    observation = None
                    if detection_enabled:
                        detection_frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
                        observation = detector.update(detection_frame)
                        record_camera_diagnostics({"ballDetection": detector.preview_detection(observation, self.width, self.height)})
                    else:
                        record_camera_diagnostics({"ballDetection": {"state": "disabled", "bounds": None}})
                    if (
                        current_time - last_preview_at >= self.preview_interval
                    ):
                        # AprilTag detection, the focus metric and two JPEG encodes take
                        # tens of milliseconds. Run inline they overflowed the camera's
                        # request queue and dropped frames, sometimes right at impact.
                        secondary = capture.secondary_frame.copy() if isinstance(capture, DualCsiCapture) else None
                        if preview_job.submit(frame.copy(), detector._pixel_roi(frame), secondary):
                            if observation is not None:
                                LOGGER.info("Ball detection %s", detector.preview_detection(observation, self.width, self.height))
                            last_preview_at = current_time
                    if not detection_enabled:
                        continue
                    assert observation is not None
                    if detector.calibrated and not calibration_logged:
                        LOGGER.info("Ball detector calibrated; place the ball in the detection area")
                        calibration_logged = True

                    if (
                        observation.present
                        and observation.bounds is None
                        and suspected_departure_at is not None
                        and rolling_frames.frames
                        and rolling_frames.frames[-1][0] - suspected_departure_at > self.departure_timeout_s
                    ):
                        # Lost and never re-confirmed: declare the removal now so the
                        # departure is still inside the buffer. If the ball is in fact
                        # still there, the still-present probes below reject it.
                        detector.stable_present = False
                        detector.present_streak = 0
                        detector.candidate_bounds = None
                        detector.stable_bounds = None
                        detector.absent_streak = 0
                        observation = DetectionObservation(False, True, observation.confidence, None)

                    if observation.present and observation.bounds is not None:
                        # The bounds below are fixed when the ball arms. A slow roll
                        # still matches the presence detector for several samples, so
                        # a shifted image must never be paired with the old bounds.
                        # The ball can also arm while the placing hand still touches
                        # it: refresh the reference only while it rests in those bounds.
                        if last_ball_frame is None:
                            last_ball_frame = frame.copy()
                        elif armed_ball_bounds is not None and max(
                            abs(current - armed) for current, armed in zip(observation.bounds, armed_ball_bounds)
                        ) <= max(2, round(0.1 * max(armed_ball_bounds[2:]))):
                            last_ball_frame = frame.copy()
                        observed_ball_frames += 1
                        if suspected_departure_at is not None:
                            rolling_frames.unpin_raw()
                        suspected_departure_at = None
                        false_removal_rejections = 0  # A real ball re-confirms; a static ghost never does.
                    elif observation.present and suspected_departure_at is None and rolling_frames.frames:
                        # Anchor the burst when the armed ball first disappears,
                        # before scene-busy/removal debounce can delay the event.
                        # This is only a hint: a club addressing the ball can trip it
                        # early, so measure_launch searches well beyond it.
                        suspected_departure_at = rolling_frames.frames[-1][0]
                        rolling_frames.pin_raw()

                    if not observation.changed:
                        continue
                    if observation.present:
                        ball_started = time.monotonic()
                        observed_ball_frames = max(1, observed_ball_frames)
                        armed_ball_bounds = detector.stable_bounds
                        false_removal_rejections = 0
                        occlusion_rejections = 0
                        LOGGER.info(
                            "Ball detected (confidence %.2f); arming LM1 PRO",
                            observation.confidence,
                        )
                        emit(BallEvent(True, confidence=observation.confidence))
                        if readiness_job is not None and armed_ball_bounds is not None:
                            readiness_job.submit(
                                frame.copy(),
                                capture.secondary_frame.copy() if isinstance(capture, DualCsiCapture) else None,
                                scale_bounds(armed_ball_bounds, (self.width, self.height), (frame.shape[1], frame.shape[0])),
                            )
                    else:
                        duration_ms = (
                            max(1, round((time.monotonic() - ball_started) * 1000))
                            if ball_started
                            else 0
                        )
                        if last_ball_frame is not None:
                            self._save_frame(last_ball_frame)
                        self._capture_post_impact_frames(capture, rolling_frames)
                        sensor_bounds = None
                        if (
                            last_ball_frame is not None
                            and armed_ball_bounds is not None
                            and rolling_frames.frames
                        ):
                            sensor_bounds = scale_bounds(armed_ball_bounds, (self.width, self.height), (frame.shape[1], frame.shape[0]))
                            count = len(rolling_frames.frames)
                            # The final frame alone is fooled by a club that has since moved
                            # in to address a ball the detector merely lost sight of; the
                            # debounce frames before that still show it sitting there.
                            probes = {
                                count - 1,
                                max(0, count - 1 - self.post_impact_frames),
                                max(0, count - 1 - self.post_impact_frames - removal_debounce_frames // 2),
                            }
                            similarity = max(
                                ball_template_similarity(last_ball_frame, rolling_frames.frames[index][1], sensor_bounds)
                                for index in probes
                            )
                            if similarity < 0.72:
                                # Not visibly still there: is it buried under something big
                                # (a club head at address), or actually gone?
                                covered = min(
                                    detector.foreground_fraction(
                                        cv2.resize(rolling_frames.frames[index][1], (self.width, self.height), interpolation=cv2.INTER_AREA),
                                        armed_ball_bounds,
                                    )
                                    for index in probes
                                )
                                if covered >= 0.6:
                                    occlusion_rejections += 1
                                    if occlusion_rejections <= 10:
                                        LOGGER.info("Armed ball is covered (%.0f%% foreground around it); waiting rather than capturing", covered * 100)
                                        detector.stable_present = True
                                        detector.stable_bounds = armed_ball_bounds
                                        detector.candidate_bounds = armed_ball_bounds
                                        detector.absent_streak = 0
                                        detector.present_streak = detector.config.present_frames
                                        suspected_departure_at = None
                                        continue
                            if similarity >= 0.72:
                                false_removal_rejections += 1
                                if false_removal_rejections >= 3:
                                    # The presence detector keeps losing an object whose
                                    # image never changes. Disarm and let it be re-detected
                                    # rather than looping every 0.8 s. Never relearn the
                                    # background here: if this is a real ball the detector
                                    # merely sees poorly, baking it in leaves a ball-shaped
                                    # hole that then gets armed as a ball itself.
                                    LOGGER.warning(
                                        "Armed object rejected removal %d times without changing; disarming",
                                        false_removal_rejections,
                                    )
                                    detector.stable_present = False
                                    detector.present_streak = 0
                                    detector.candidate_bounds = None
                                    detector.stable_bounds = None
                                    detector.absent_streak = 0
                                    ball_started = 0.0
                                    observed_ball_frames = 0
                                    last_ball_frame = None
                                    armed_ball_bounds = None
                                    suspected_departure_at = None
                                    false_removal_rejections = 0
                                    emit(BallEvent(False))
                                    continue
                                LOGGER.info(
                                    "Rejected false removal; armed ball is still present (similarity %.2f)",
                                    similarity,
                                )
                                detector.stable_present = True
                                detector.stable_bounds = armed_ball_bounds
                                detector.candidate_bounds = armed_ball_bounds
                                detector.absent_streak = 0
                                detector.present_streak = detector.config.present_frames
                                suspected_departure_at = None
                                continue
                        # A hint older than the buffer (a long busy scene before the
                        # strike) would otherwise snap to frame 0.
                        if suspected_departure_at is None or suspected_departure_at < rolling_frames.frames[0][0]:
                            impact_frame_index = max(
                                0,
                                len(rolling_frames.frames)
                                - self.post_impact_frames
                                - detector.config.absent_frames * self.frame_stride,
                            )
                        else:
                            impact_frame_index = min(
                                range(len(rolling_frames.frames)),
                                key=lambda index: abs(rolling_frames.frames[index][0] - suspected_departure_at),
                            )
                        coarse_departure_frame_index = impact_frame_index
                        analysis = analyze_departure(
                            rolling_frames,
                            scale_bounds(armed_ball_bounds, (self.width, self.height), (frame.shape[1], frame.shape[0])),
                            impact_frame_index,
                            ball_reference=last_ball_frame,
                        ) if armed_ball_bounds and rolling_frames.frames else None
                        if analysis is not None:
                            impact_frame_index = analysis["impactFrameIndex"]
                            if rolling_frames.secondary is not None:
                                other = rolling_frames.secondary.frames[analysis["imageFrameIndex"]][1]
                                analysis["secondaryImage"] = {"mimeType": "image/jpeg", "base64": base64.b64encode(encode_ble_preview(other)).decode("ascii")}
                        # Debouncing a disappearance needs a long live buffer, but a
                        # full swing does not need those empty frames in its saved
                        # burst. Keep them for putting, where the roll is useful.
                        if capture_mode is None or capture_mode() != "putting":
                            last_useful_index = max(
                                [impact_frame_index + self.full_shot_tail_frames]
                                + ([analysis["imageFrameIndex"]] if analysis is not None else [])
                                + [point["frameIndex"] for point in (analysis or {}).get("track", [])]
                            )
                            rolling_frames.trim_after(last_useful_index)
                            if analysis is not None:
                                saved_count = len(rolling_frames.frames)
                                saved_duration_ms = max(0.0, rolling_frames.frames[-1][0] - rolling_frames.frames[0][0]) * 1000
                                analysis["frameCount"] = saved_count
                                analysis["captureDurationMs"] = round(saved_duration_ms)
                                analysis["measuredFps"] = round((saved_count - 1) * 1000 / saved_duration_ms, 1) if saved_duration_ms > 0 else None
                        # The result goes out before the frames are written: saving both
                        # cameras' bursts takes seconds on the Pi and the app only needs
                        # the frames later, for replay. The folder exists first because
                        # the protocol writes analysis.json into it.
                        rolling_capture_frames, capture_id, capture_duration_ms = self._reserve_rolling_capture(rolling_frames)
                        LOGGER.info("Ball removed; sending result before saving frames")
                        emit(
                            BallEvent(
                                False,
                                frame_count=observed_ball_frames,
                                duration_ms=capture_duration_ms or duration_ms,
                                confidence=observation.confidence,
                                rolling_capture_frames=rolling_capture_frames,
                                capture_id=capture_id,
                                impact_frame_index=impact_frame_index,
                                analysis=analysis,
                            )
                        )
                        if capture_id is not None:
                            self._save_rolling_capture(
                                rolling_frames,
                                capture_id,
                                impact_frame_index,
                                coarse_departure_frame_index=(analysis or {}).get("coarseDepartureFrameIndex", coarse_departure_frame_index),
                                last_stationary_frame_index=(analysis or {}).get("lastStationaryFrameIndex"),
                                first_moving_frame_index=(analysis or {}).get("firstMovingFrameIndex"),
                                ball_bounds=sensor_bounds,
                                ball_reference=last_ball_frame,
                            )
                        ball_started = 0.0
                        observed_ball_frames = 0
                        last_ball_frame = None
                        armed_ball_bounds = None
                        suspected_departure_at = None
                        false_removal_rejections = 0
                        occlusion_rejections = 0
            except Exception:
                LOGGER.exception("Camera stream failed; reopening")
                if detection_enabled:
                    emit(BallEvent(False))
            finally:
                preview_job.stop()
                if readiness_job is not None:
                    readiness_job.stop()
                capture.release()
            stop_event.wait(2)

    @staticmethod
    def _readiness_checks(lower: Any, upper: Any, bounds: tuple[int, int, int, int]) -> list[dict[str, Any]]:
        from readiness import camera_checks  # Imports the measurement stack; loaded only when a ball arms.
        return camera_checks(lower, upper, bounds)

    def _publish_preview(
        self,
        frame: Any,
        roi: tuple[int, int, int, int],
        apriltag_detector: Any,
        emit_preview: Callable[[bytes], None] | None,
        secondary: Any = None,
    ) -> None:
        try:
            record_camera_diagnostics({"aprilTag": apriltag_detector.detect(frame)})
            if secondary is not None:
                record_camera_diagnostics({"secondaryAprilTag": apriltag_detector.detect(secondary)})
            if uses_csi():
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                left, top, right, bottom = roi
                focus = cv2.Laplacian(gray[top:bottom, left:right], cv2.CV_64F).var()
                record_camera_diagnostics({"focusScore": round(float(focus), 1)})
                self._save_frame(frame, Path(os.getenv("PINPOINT_CAMERA_SNAPSHOT_PATH", "/var/lib/pinpoint/camera-latest.jpg")))
            if emit_preview is not None:
                if secondary is not None:
                    self._save_frame(secondary, Path(os.getenv("PINPOINT_SECONDARY_SNAPSHOT_PATH", "/var/lib/pinpoint/camera-secondary-latest.jpg")))
                    emit_preview(encode_ble_preview(frame), encode_ble_preview(secondary))
                else:
                    emit_preview(encode_ble_preview(frame))
        except (OSError, RuntimeError, cv2.error) as error:
            LOGGER.warning("BLE preview frame failed: %s", error)

    def _run_exposure_calibration(self, capture: Any, stop_event: threading.Event) -> dict[str, Any]:
        """Sweep the shutter for the current light and report what was chosen."""
        def grab_frame() -> Any:
            if stop_event.is_set():
                raise RuntimeError("LM1 stopped before calibration finished.")
            ok, probe = capture.read()
            if not ok:
                raise RuntimeError("The camera stopped delivering frames during calibration.")
            return probe

        try:
            result = auto_calibrate_light(grab_frame, get_light_controller(), take_exposure_cap_hint())
        except Exception as error:  # noqa: BLE001 - the app shows whatever went wrong
            LOGGER.warning("Exposure calibration failed: %s", error)
            return {"ok": False, "error": str(error)}
        LOGGER.info("Exposure calibration chose %s", result)
        return {"ok": True, **result}

    def _open_camera(self) -> Any:
        if uses_csi():
            if os.getenv("PINPOINT_DUAL_CAMERA", "false").lower() in {"1", "true", "yes"}:
                return DualCsiCapture()
            return CsiCapture()
        capture = cv2.VideoCapture(str(self.camera_device), cv2.CAP_V4L2)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _save_frame(self, frame: Any, output_path: Path | None = None) -> None:
        output_path = output_path or self.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(
            f"{output_path.stem}.tmp{output_path.suffix}"
        )
        if not cv2.imwrite(str(temporary_path), frame):
            raise RuntimeError(f"Could not save diagnostic frame to {temporary_path}")
        temporary_path.replace(output_path)

    def _reserve_rolling_capture(self, rolling_frames: RollingFrameBuffer) -> tuple[int, str | None, int]:
        """Create the burst's folder and mark it pending, before any frame is written."""
        if not rolling_frames.frames:
            return 0, None, 0
        destination = self.rolling_capture_path / f"capture-{time.time_ns()}"
        try:
            destination.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            LOGGER.warning("Could not create rolling capture folder: %s", error)
            return 0, None, 0
        _begin_capture_save(destination.name)
        capture_duration_ms = round(max(0.0, rolling_frames.frames[-1][0] - rolling_frames.frames[0][0]) * 1000)
        return len(rolling_frames.frames), destination.name, capture_duration_ms

    def _save_rolling_capture(
        self,
        rolling_frames: RollingFrameBuffer,
        capture_id: str,
        impact_frame_index: int | None = None,
        *,
        coarse_departure_frame_index: int | None = None,
        last_stationary_frame_index: int | None = None,
        first_moving_frame_index: int | None = None,
        ball_bounds: tuple[int, int, int, int] | None = None,
        ball_reference: Any | None = None,
    ) -> int:
        destination = self.rolling_capture_path / capture_id
        started = time.monotonic()
        try:
            frame_count = rolling_frames.save(
                destination,
                self.fps,
                impact_frame_index,
                coarse_departure_frame_index=coarse_departure_frame_index,
                last_stationary_frame_index=last_stationary_frame_index,
                first_moving_frame_index=first_moving_frame_index,
                ball_bounds=ball_bounds,
            )
            if ball_reference is not None:
                # Lossless replay reference, paired with the manifest's ballBounds.
                # This cannot be reconstructed from a later moving-ball frame.
                if not cv2.imwrite(str(destination / "armed-ball-reference.png"), ball_reference):
                    raise RuntimeError("Could not save the armed-ball reference")
            self._keep_recent_rolling_captures()
            LOGGER.info("Saved %s diagnostic rolling-capture frames to %s in %.1f s",
                        frame_count, destination, time.monotonic() - started)
            return frame_count
        except (OSError, RuntimeError, cv2.error) as error:
            LOGGER.warning("Could not save rolling capture: %s", error)
            shutil.rmtree(destination, ignore_errors=True)
            return 0
        finally:
            _finish_capture_save(capture_id)

    def _capture_post_impact_frames(self, capture: Any, rolling_frames: RollingFrameBuffer) -> None:
        for _ in range(self.post_impact_frames):
            ok, frame = capture.read()
            if not ok:
                LOGGER.warning("Camera stopped while collecting post-impact frames")
                return
            frame = self._analysis_frames(capture, frame)
            self._append_capture_frame(rolling_frames, capture, frame)

    def _analysis_frames(self, capture: Any, frame: Any) -> Any:
        """The frames the detector and buffer see: raw-derived while strobing (see raw_frames.py), else the picture."""
        converted = self.raw_analysis.frame(frame, getattr(capture, "metadata", None))
        if isinstance(capture, DualCsiCapture) and capture.secondary_frame is not None:
            capture.secondary_frame = self.raw_analysis.frame(
                capture.secondary_frame, getattr(capture, "secondary_metadata", None), follow=True)
        return converted

    def _current_light_mode(self) -> str:
        """light_mode() reads its settings file; refresh it at most once a second."""
        now = time.monotonic()
        if now - self._light_mode_checked_at >= 1.0:
            self._light_mode_checked_at = now
            self._light_mode_cache = light_mode()
        return self._light_mode_cache

    def _append_capture_frame(self, rolling_frames: RollingFrameBuffer, capture: Any, frame: Any) -> None:
        extra = {}
        metadata = getattr(capture, "metadata", None)
        # The raw 10-bit frame is ~0.5 MB and only the strobe-copy path reads it back
        # from the replay ring. Drop it outside strobe mode so the ring (100 frames x
        # two cameras) does not hold ~100 MB the measurement will never use.
        if metadata is not None and self._current_light_mode() != "strobe":
            metadata = {key: value for key, value in metadata.items() if key != "RawFrame"}
        if isinstance(capture, DualCsiCapture):
            secondary_metadata = capture.secondary_metadata
            if secondary_metadata is not None and self._current_light_mode() != "strobe":
                secondary_metadata = {key: value for key, value in secondary_metadata.items() if key != "RawFrame"}
            extra = {"secondary_frame": cv2.cvtColor(capture.secondary_frame, cv2.COLOR_BGR2GRAY),
                     "secondary_metadata": secondary_metadata}
        rolling_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                              metadata=metadata, **extra)

    def _keep_recent_rolling_captures(self) -> None:
        if not self.rolling_capture_path.exists():
            return
        captures = sorted(
            (path for path in self.rolling_capture_path.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_capture in captures[capture_retention():]:
            shutil.rmtree(old_capture, ignore_errors=True)
