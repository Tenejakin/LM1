"""CSI camera ownership and live diagnostics, independent of shot simulation."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

MIN_EXPOSURE_US = 20
MAX_EXPOSURE_US = 250
EXPOSURE_STEP_US = 10
MIN_CAMERA_GAIN = 1.0
MAX_CAMERA_GAIN = 16.0
CAMERA_GAIN_STEP = 0.25
DEFAULT_CAMERA_SETTINGS_PATH = Path("/var/lib/pinpoint/camera-settings.json")

_lock = threading.Lock()
_live: dict[str, Any] = {}
_updated = 0.0
_active_capture: CsiCapture | None = None


def uses_csi() -> bool:
    return os.getenv("PINPOINT_CAMERA_SOURCE", "usb").lower() == "csi"


def camera_diagnostics() -> dict[str, Any]:
    with _lock:
        return dict(_live) if time.monotonic() - _updated < 5 else {}


def clear_camera_diagnostics() -> None:
    global _updated
    with _lock:
        _live.clear()
        _updated = 0.0


def record_camera_diagnostics(values: dict[str, Any]) -> None:
    global _updated
    with _lock:
        _live.update(values)
        _updated = time.monotonic()


def _settings_path() -> Path:
    return Path(os.getenv("PINPOINT_CAMERA_SETTINGS_PATH", str(DEFAULT_CAMERA_SETTINGS_PATH)))


def _load_camera_settings() -> dict[str, Any]:
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def configured_exposure_us() -> int:
    """Return the persisted manual exposure, falling back to the service environment."""
    exposure = _load_camera_settings().get("exposureUs")
    if isinstance(exposure, int) and not isinstance(exposure, bool) and exposure > 0:
        return exposure
    return int(os.getenv("PINPOINT_EXPOSURE_US", "0"))


def configured_camera_gain() -> float:
    """Return persisted analogue gain, falling back to the service environment."""
    gain = _load_camera_settings().get("gain")
    if isinstance(gain, (int, float)) and not isinstance(gain, bool) and math.isfinite(gain):
        if MIN_CAMERA_GAIN <= float(gain) <= MAX_CAMERA_GAIN:
            return float(gain)
    return float(os.getenv("PINPOINT_CAMERA_GAIN", "1"))


def exposure_configuration() -> dict[str, Any]:
    return {
        "configurable": uses_csi(),
        "minUs": MIN_EXPOSURE_US,
        "maxUs": MAX_EXPOSURE_US,
        "stepUs": EXPOSURE_STEP_US,
    }


def gain_configuration() -> dict[str, Any]:
    return {
        "configurable": uses_csi(),
        "min": MIN_CAMERA_GAIN,
        "max": MAX_CAMERA_GAIN,
        "step": CAMERA_GAIN_STEP,
    }


def _save_camera_setting(key: str, value: int | float) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    settings = _load_camera_settings()
    settings[key] = value
    temporary.write_text(
        json.dumps(settings, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def set_camera_exposure(exposure_us: int) -> dict[str, Any]:
    """Apply and persist a measurement-safe manual exposure on the active CSI camera."""
    if isinstance(exposure_us, bool) or not isinstance(exposure_us, int):
        raise ValueError("Exposure must be a whole number of microseconds.")
    if not MIN_EXPOSURE_US <= exposure_us <= MAX_EXPOSURE_US:
        raise ValueError(f"Exposure must be between {MIN_EXPOSURE_US} and {MAX_EXPOSURE_US} μs.")
    with _lock:
        capture = _active_capture
    if capture is None or not capture.isOpened():
        raise RuntimeError("The CSI camera is not ready for exposure changes.")

    previous = capture.exposure_us
    capture.set_exposure(exposure_us)
    try:
        _save_camera_setting("exposureUs", exposure_us)
    except OSError:
        capture.set_exposure(previous)
        raise
    return {"exposureUs": exposure_us, **exposure_configuration()}


def set_camera_gain(gain: float) -> dict[str, Any]:
    """Apply and persist analogue gain on the active manual-exposure CSI camera."""
    if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain):
        raise ValueError("Camera gain must be a finite number.")
    gain = round(float(gain), 2)
    if not MIN_CAMERA_GAIN <= gain <= MAX_CAMERA_GAIN:
        raise ValueError(f"Camera gain must be between {MIN_CAMERA_GAIN:g} and {MAX_CAMERA_GAIN:g}.")
    with _lock:
        capture = _active_capture
    if capture is None or not capture.isOpened():
        raise RuntimeError("The CSI camera is not ready for gain changes.")
    if capture.exposure_us <= 0:
        raise RuntimeError("Set a manual exposure before changing camera gain.")

    previous = capture.gain
    capture.set_gain(gain)
    try:
        _save_camera_setting("gain", gain)
    except OSError:
        capture.set_gain(previous)
        raise
    return {"gain": gain, **gain_configuration()}


def auto_calibrate_camera(grab_frame: "Callable[[], Any]") -> dict[str, Any]:
    """Find and store exposure/gain that suit the light the camera is looking at.

    ``grab_frame`` comes from whoever owns the stream (the detection loop), so the
    sweep never opens a second handle on the camera. Only the winning pair is
    written to disk; the probe settings are applied live and then replaced.
    """
    from exposure_calibration import calibrate_exposure

    with _lock:
        capture = _active_capture
    if capture is None or not capture.isOpened():
        raise RuntimeError("The CSI camera is not ready for exposure calibration.")

    previous_exposure = capture.exposure_us
    previous_gain = capture.gain

    def apply_settings(exposure_us: int, gain: float) -> None:
        capture.set_exposure(exposure_us)
        capture.set_gain(gain)

    try:
        result = calibrate_exposure(
            apply_settings,
            grab_frame,
            min_us=MIN_EXPOSURE_US,
            max_us=MAX_EXPOSURE_US,
            step_us=EXPOSURE_STEP_US,
            min_gain=MIN_CAMERA_GAIN,
            max_gain=MAX_CAMERA_GAIN,
            gain_step=CAMERA_GAIN_STEP,
        )
    except Exception:
        # Never strand the camera on a probe setting when the sweep fails.
        capture.set_exposure(previous_exposure)
        capture.set_gain(previous_gain)
        raise

    try:
        _save_camera_setting("exposureUs", result.exposure_us)
        _save_camera_setting("gain", result.gain)
    except OSError:
        capture.set_exposure(previous_exposure)
        capture.set_gain(previous_gain)
        raise

    return {**result.as_dict(), **exposure_configuration()}


class CsiCapture:
    """Picamera2 adapter returning OpenCV-compatible images from one owned stream."""

    def __init__(self) -> None:
        from picamera2 import Picamera2

        self.camera = None
        self.metadata: dict[str, Any] = {}
        width, height = map(int, os.getenv("PINPOINT_CAMERA_RESOLUTION", "1280x800").split("x"))
        fps = float(os.getenv("PINPOINT_CAMERA_FPS", "30"))
        if width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("Camera dimensions and frame rate must be positive")
        camera = Picamera2(int(os.getenv("PINPOINT_CAMERA_INDEX", "0")))
        try:
            controls: dict[str, Any] = {"FrameRate": fps, "AeEnable": True}
            exposure = configured_exposure_us()
            gain = configured_camera_gain()
            if exposure > 0:
                controls.update(AeEnable=False, ExposureTime=exposure,
                                AnalogueGain=gain)
            config = camera.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"},
                sensor={"output_size": (width, height), "bit_depth": 10},
                # Extra queued requests absorb short stalls in the detection loop
                # instead of dropping 200 fps frames (640x400 RGB is ~0.8 MB each).
                controls=controls, buffer_count=max(4, int(os.getenv("PINPOINT_CAMERA_BUFFER_COUNT", "8"))),
            )
            camera.configure(config)
            camera.start()
            self.model = str(camera.camera_properties.get("Model", "CSI camera"))
            self.exposure_us = exposure
            self.gain = gain
            self.camera = camera
            global _active_capture
            with _lock:
                _active_capture = self
        except Exception:
            camera.close()
            raise

    def isOpened(self) -> bool:
        return self.camera is not None

    def set_exposure(self, exposure_us: int) -> None:
        if self.camera is None:
            raise RuntimeError("The CSI camera is not open.")
        controls: dict[str, Any] = {"AeEnable": exposure_us <= 0}
        if exposure_us > 0:
            controls.update(
                ExposureTime=exposure_us,
                AnalogueGain=self.gain,
            )
        self.camera.set_controls(controls)
        self.exposure_us = exposure_us
        record_camera_diagnostics({
            "exposureUs": exposure_us,
            "autoExposure": exposure_us <= 0,
        })

    def set_gain(self, gain: float) -> None:
        if self.camera is None:
            raise RuntimeError("The CSI camera is not open.")
        self.camera.set_controls({"AnalogueGain": gain})
        self.gain = gain
        record_camera_diagnostics({"gain": gain})

    def read(self) -> tuple[bool, Any]:
        if self.camera is None:
            return False, None
        job = self.camera.capture_request(wait=False)
        try:
            request = self.camera.wait(job, timeout=2)
        except TimeoutError:
            self.camera.cancel_all_and_flush()
            raise RuntimeError("CSI camera stopped delivering frames") from None
        try:
            frame = request.make_array("main")
            self.metadata = request.get_metadata()
            duration = self.metadata.get("FrameDuration", 0)
            record_camera_diagnostics({
                "model": self.model, "width": frame.shape[1], "height": frame.shape[0],
                "fps": round(1_000_000 / duration, 1) if duration else 0,
                "exposureUs": self.metadata.get("ExposureTime", 0),
                "gain": round(self.metadata.get("AnalogueGain", 1), 2),
                "autoExposure": self.exposure_us <= 0,
                "autofocus": "AfMode" in self.camera.camera_controls,
            })
            return True, frame
        finally:
            request.release()

    def release(self) -> None:
        global _active_capture
        with _lock:
            if _active_capture is self:
                _active_capture = None
        if self.camera is not None:
            camera, self.camera = self.camera, None
            try:
                camera.stop()
            finally:
                camera.close()
        clear_camera_diagnostics()
