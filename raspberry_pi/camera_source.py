"""CSI camera ownership and live diagnostics, independent of shot simulation."""

from __future__ import annotations

import json
import logging
import math
import os
import statistics
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("pinpoint.camera")

# Staggered capture: the second sensor is held half a frame behind the first, so the pair samples two
# instants and the cameras together see the ball at twice the frame rate. Both sensors run free (no
# libcamera sync); their phase is stable to microseconds, so it is chosen once by restarting the second
# camera until it lands near half a frame, then watched on every pair.
STAGGER_TARGET = 0.5
STAGGER_LOCK_TOLERANCE = 0.15   # accept a lock within 0.35 to 0.65 of a frame
STAGGER_LOCKED = 0.20           # phase within 0.3 to 0.7: fully usable
STAGGER_SOON = 0.30             # within 0.2 to 0.8: usable, re-lock at the next idle moment
STAGGER_MAX_ATTEMPTS = 30
STAGGER_MEASURE_SECONDS = 0.45


def stagger_enabled() -> bool:
    return os.getenv("PINPOINT_CAMERA_STAGGER", "false").strip().lower() in {"1", "true", "yes"}


def stagger_distance(phase: float) -> float:
    """How far a phase (fraction of a frame) is from the half-frame target, 0 to 0.5."""
    return abs(((phase - STAGGER_TARGET + 0.5) % 1.0) - 0.5)


def stagger_state(phases: "list[float] | tuple[float, ...]") -> str:
    """'locked', 'drift-soon' or 'drifted' from the recent pair phases (median, so one late frame is ignored)."""
    if not phases:
        return "locking"
    distance = stagger_distance(statistics.median(phases))
    return "locked" if distance <= STAGGER_LOCKED else "drift-soon" if distance <= STAGGER_SOON else "drifted"


def phase_of(a_stamps: "list[int]", b_stamp: int, period_ns: float) -> "float | None":
    """Phase of one B frame after the latest A frame at or before it, as a fraction of a frame."""
    import bisect
    i = bisect.bisect_right(a_stamps, b_stamp) - 1
    if i < 0 or period_ns <= 0:
        return None
    return ((b_stamp - a_stamps[i]) % period_ns) / period_ns


# Raw 10-bit capture. The sensor reads 10 bits, but the image processor squeezes them to an 8-bit
# picture with its own curve that turns the darkest ~3 % of the range (about 30 of 1023 levels) into
# black, which is exactly where a faint flash lives. With PINPOINT_CAMERA_RAW=true each frame also
# carries its raw data: linear, 10 bits stored left-aligned in a 16-bit word (value = 10-bit count x 64,
# so words step by 64 and full scale is 65472). Measured on the Pi: the sensor has already removed its own
# pedestal, so the data floor is only ~16 counts (word ~1024). libcamera reports SensorBlackLevels = 4096
# (64 counts), but that is what the image processor subtracts: it throws away 64 counts of real signal
# before its gamma curve, which is why faint flashes come out as exactly 0 in the 8-bit picture.
RAW_SCALE = 64
DEFAULT_RAW_BLACK_LEVEL = 1024  # the measured floor of the data, in raw words

# MIN/MAX_EXPOSURE_US are the measurement-safe range the automatic sweep chooses from. A shutter set by hand is
# limited only by the sensor (hardware_exposure_limits): the measurement still rejects frames above 250 us itself.
MIN_EXPOSURE_US = 20
MAX_EXPOSURE_US = 250
# A ball that moves further than this during one exposure is rejected by the measurement (launch_measurements
# MAX_MOTION_BLUR_M), so the longest usable shutter is this distance divided by the ball's speed.
BLUR_LIMIT_M = 0.004
BLUR_SAFETY = 0.9
EXPOSURE_STEP_US = 10  # the automatic sweep's step
MANUAL_EXPOSURE_STEP_US = 1  # a shutter set by hand: any whole microsecond the sensor takes
# Strobe mode: a long exposure (just under one 242 fps frame) with the IR ring flashing
# a burst inside it, so one frame holds several sharp copies of the ball. The normal
# measurement limit above still applies whenever strobe mode is off.
STROBE_MAX_EXPOSURE_US = 4000
STROBE_DEFAULT_EXPOSURE_US = 3900
DEFAULT_NORMAL_EXPOSURE_US = 100
# Light modes: what the IR ring does and which exposure suits it. Each mode remembers
# its own exposure and gain, so moving between a sunny garden and a dim room (or the
# strobe) never costs you the settings you tuned for the other.
LIGHT_MODES = ("auto", "daylight", "flat", "strobe")
DAYLIGHT_DEFAULT = (30, 1.0)
STROBE_DEFAULT = (STROBE_DEFAULT_EXPOSURE_US, 1.0)
# Auto picks daylight only when the ring-off sweep is usable at or below this exposure.
DAYLIGHT_MAX_EXPOSURE_US = 100
MIN_CAMERA_GAIN = 1.0
MAX_CAMERA_GAIN = 16.0
CAMERA_GAIN_STEP = 0.25
DEFAULT_CAMERA_SETTINGS_PATH = Path("/var/lib/pinpoint/camera-settings.json")

_lock = threading.Lock()
_live: dict[str, Any] = {}
_updated = 0.0
_active_capture: CsiCapture | DualCsiCapture | None = None
# The sensor's own shutter range at the running frame rate, read from libcamera when a camera opens.
_hardware_exposure: tuple[int, int] | None = None


def blur_safe_exposure_us(ball_speed_mps: float) -> int:
    """Longest exposure that keeps a ball at this speed within the blur limit, inside the allowed range."""
    if not ball_speed_mps or ball_speed_mps <= 0:
        return MAX_EXPOSURE_US
    return int(max(MIN_EXPOSURE_US, min(MAX_EXPOSURE_US, BLUR_SAFETY * BLUR_LIMIT_M / ball_speed_mps * 1e6)))


# The club chosen in the app sets how fast the ball will be, hence how short the shutter must be. The protocol leaves
# that limit here for the next automatic exposure sweep, which runs in the detection loop and takes it once.
_exposure_cap_hint: int | None = None


def set_exposure_cap_hint(exposure_us: int | None) -> None:
    global _exposure_cap_hint
    _exposure_cap_hint = exposure_us


def take_exposure_cap_hint() -> int | None:
    global _exposure_cap_hint
    hint, _exposure_cap_hint = _exposure_cap_hint, None
    return hint


def raw_capture_enabled() -> bool:
    """Raw frames are wanted and possible (10-bit sensor mode)."""
    wanted = os.getenv("PINPOINT_CAMERA_RAW", "false").lower() in {"1", "true", "yes"}
    return wanted and int(os.getenv("PINPOINT_CAMERA_BIT_DEPTH", "10")) == 10


def raw_black_level(metadata: dict[str, Any] | None = None) -> int:
    """Floor of the raw data in raw words (see RAW_SCALE). libcamera's SensorBlackLevels (4096) is what the image
    processor subtracts, not where this data starts, so it is deliberately not used; PINPOINT_RAW_BLACK_LEVEL
    overrides the measured default."""
    try:
        return max(0, int(os.getenv("PINPOINT_RAW_BLACK_LEVEL", DEFAULT_RAW_BLACK_LEVEL)))
    except ValueError:
        return DEFAULT_RAW_BLACK_LEVEL


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


def strobe_mode_enabled() -> bool:
    return _load_camera_settings().get("strobeMode") is True


def frame_period_us() -> int:
    """One frame at the configured rate: no exposure can be longer without slowing the camera down."""
    return int(1_000_000 / float(os.getenv("PINPOINT_CAMERA_FPS", "30")))


def _sensor_exposure_limits(camera: Any) -> tuple[int, int]:
    """The shutter range libcamera reports for this camera, capped at one frame period."""
    period = frame_period_us()
    controls = getattr(camera, "camera_controls", None)
    limits = controls.get("ExposureTime") if isinstance(controls, dict) else None
    if (isinstance(limits, (tuple, list)) and len(limits) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in limits[:2])):
        low, high = int(limits[0]), int(limits[1])
    else:
        low, high = 1, period
    low = max(1, low)
    return low, max(low, min(high, period))


def _publish_hardware_limits(limits: tuple[int, int] | None) -> None:
    global _hardware_exposure
    with _lock:
        _hardware_exposure = limits


def hardware_exposure_limits() -> tuple[int, int]:
    """Shortest and longest shutter the sensor accepts; before a camera opens, 1 us to one frame."""
    with _lock:
        limits = _hardware_exposure
    return limits if limits else (1, frame_period_us())


def max_exposure_us() -> int:
    return hardware_exposure_limits()[1]


def light_mode() -> str:
    """The mode the player chose: auto, daylight, flat or strobe."""
    settings = _load_camera_settings()
    saved = settings.get("lightMode")
    if saved in LIGHT_MODES:
        return saved
    # A fresh unit starts in auto: the detection loop then watches the view and
    # picks daylight/flat (and the right exposure) for the room and the club.
    return "strobe" if settings.get("strobeMode") is True else "auto"


def active_light() -> str:
    """The light actually in use: daylight, flat or strobe (auto resolves to one of the first two)."""
    settings = _load_camera_settings()
    mode = light_mode()
    if mode != "auto":
        return mode
    return settings.get("activeLight") if settings.get("activeLight") in ("daylight", "flat") else "flat"


def exposure_configuration() -> dict[str, Any]:
    low, high = hardware_exposure_limits()
    return {
        "configurable": uses_csi(),
        "minUs": low,
        "maxUs": high,
        "stepUs": MANUAL_EXPOSURE_STEP_US,
        # Above this the launch measurement rejects the frames (motion blur); the shutter itself may go further.
        "measurementMaxUs": MAX_EXPOSURE_US,
        "strobeMode": strobe_mode_enabled(),
        "lightMode": light_mode(),
        "activeLight": active_light(),
    }


def gain_configuration() -> dict[str, Any]:
    return {
        "configurable": uses_csi(),
        "min": MIN_CAMERA_GAIN,
        "max": MAX_CAMERA_GAIN,
        "step": CAMERA_GAIN_STEP,
    }


def _save_camera_setting(key: str, value: int | float | bool) -> None:
    _save_camera_settings({key: value})


def _save_camera_settings(updates: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    settings = _load_camera_settings()
    settings.update(updates)
    temporary.write_text(
        json.dumps(settings, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _applied_exposure_us(capture: Any, requested: int, wait_s: float = 0.3) -> int | None:
    """The shutter the sensor actually used once the change reached a frame (it rounds to whole lines)."""
    deadline = time.monotonic() + wait_s
    applied = None
    while time.monotonic() < deadline:
        time.sleep(0.03)
        applied = (getattr(capture, "metadata", None) or {}).get("ExposureTime")
        # A line is a few microseconds; anything within 2 % (or 20 us) is this request, not the old value.
        if isinstance(applied, (int, float)) and abs(applied - requested) <= max(20, requested * 0.02):
            return int(applied)
    return int(applied) if isinstance(applied, (int, float)) else None


def set_camera_exposure(exposure_us: int) -> dict[str, Any]:
    """Apply and persist any shutter the sensor supports, in every light mode.

    The measurement keeps its own blur rule (frames above 250 us are not measured); this only refuses what the
    hardware cannot do. A shutter set by hand also leaves Auto, so the next automatic sweep cannot overwrite it.
    """
    if isinstance(exposure_us, bool) or not isinstance(exposure_us, int):
        raise ValueError("Exposure must be a whole number of microseconds.")
    low, high = hardware_exposure_limits()
    if not low <= exposure_us <= high:
        raise ValueError(f"Exposure must be between {low} and {high} μs (the sensor's range at "
                         f"{1_000_000 / frame_period_us():.0f} fps).")
    with _lock:
        capture = _active_capture
    if capture is None or not capture.isOpened():
        raise RuntimeError("The CSI camera is not ready for exposure changes.")

    previous = capture.exposure_us
    capture.set_exposure(exposure_us)
    updates: dict[str, Any] = {"exposureUs": exposure_us}
    if light_mode() == "auto":
        updates["lightMode"] = active_light()
    try:
        _save_camera_settings(updates)
    except OSError:
        capture.set_exposure(previous)
        raise
    return {"exposureUs": exposure_us, "appliedExposureUs": _applied_exposure_us(capture, exposure_us),
            **exposure_configuration()}


def _profile(settings: dict[str, Any], profiles: dict[str, Any], mode: str,
             current: tuple[int, float]) -> tuple[int, float]:
    """The exposure and gain a light mode starts from the next time it is chosen."""
    saved = profiles.get(mode)
    if isinstance(saved, dict):
        exposure, gain = saved.get("exposureUs"), saved.get("gain")
        if (isinstance(exposure, int) and not isinstance(exposure, bool) and isinstance(gain, (int, float))
                and not isinstance(gain, bool) and MIN_CAMERA_GAIN <= float(gain) <= MAX_CAMERA_GAIN):
            low, high = hardware_exposure_limits()
            if low <= exposure <= high:
                return exposure, float(gain)
    if mode == "daylight":
        return DAYLIGHT_DEFAULT
    if mode == "strobe":
        return STROBE_DEFAULT
    exposure, gain = current
    if MIN_EXPOSURE_US <= exposure <= MAX_EXPOSURE_US:
        return exposure, gain
    return DEFAULT_NORMAL_EXPOSURE_US, configured_camera_gain()


def set_light_mode(mode: str) -> dict[str, Any]:
    """Choose how the scene is lit and move the camera to that mode's exposure and gain.

    The ring itself is switched by the caller (the light controller); this only keeps
    the camera in step and persists the choice. Leaving a mode stores its exposure and
    gain, so turning strobe off puts the normal shutter speed back and a forgotten
    strobe mode can never leave measurements running on a 4 ms shutter.
    """
    if mode not in LIGHT_MODES:
        raise ValueError("Light mode must be auto, daylight, flat or strobe.")
    with _lock:
        capture = _active_capture
    if capture is None or not capture.isOpened():
        raise RuntimeError("The CSI camera is not ready for light changes.")

    settings = _load_camera_settings()
    profiles = dict(settings.get("lightProfiles") or {})
    leaving = active_light()
    target = "flat" if mode == "auto" else mode
    if mode == "auto" and settings.get("activeLight") in ("daylight", "flat"):
        target = settings["activeLight"]

    previous = (capture.exposure_us, capture.gain)
    if capture.exposure_us > 0:
        profiles[leaving] = {"exposureUs": int(capture.exposure_us), "gain": float(capture.gain)}
    exposure, gain = _profile(settings, profiles, target, previous)

    capture.set_gain(gain)
    capture.set_exposure(exposure)
    try:
        _save_camera_settings({
            "lightMode": mode, "activeLight": target, "strobeMode": target == "strobe",
            "exposureUs": exposure, "gain": gain, "lightProfiles": profiles,
        })
    except OSError:
        capture.set_gain(previous[1])
        capture.set_exposure(previous[0])
        raise
    return {"exposureUs": exposure, "gain": gain, **exposure_configuration()}


def set_strobe_mode(enabled: bool) -> dict[str, Any]:
    """Compatibility wrapper for services and apps that only know the strobe switch."""
    if not isinstance(enabled, bool):
        raise ValueError("Strobe mode must be on or off.")
    return set_light_mode("strobe" if enabled else "flat")


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


def auto_calibrate_camera(grab_frame: "Callable[[], Any]", max_exposure_us: int | None = None) -> dict[str, Any]:
    """Find and store exposure/gain that suit the light the camera is looking at.

    `max_exposure_us` is the blur-safe limit for the club (see blur_safe_exposure_us): a faster ball needs a shorter
    shutter, so the sweep stays under it and buys brightness with gain instead; when even that is too dark the
    result says so rather than quietly choosing a shutter the measurement would reject.

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
    cap = MAX_EXPOSURE_US if not max_exposure_us else max(MIN_EXPOSURE_US, min(MAX_EXPOSURE_US, int(max_exposure_us)))

    def apply_settings(exposure_us: int, gain: float) -> None:
        capture.set_exposure(exposure_us)
        capture.set_gain(gain)

    try:
        result = calibrate_exposure(
            apply_settings,
            grab_frame,
            min_us=MIN_EXPOSURE_US,
            max_us=cap,
            step_us=EXPOSURE_STEP_US,
            min_gain=MIN_CAMERA_GAIN,
            max_gain=MAX_CAMERA_GAIN,
            gain_step=CAMERA_GAIN_STEP,
            settle_frames=12 if isinstance(capture, DualCsiCapture) else 2,
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

    summary = result.as_dict()
    if cap < MAX_EXPOSURE_US:
        summary["blurLimitUs"] = cap
        if not result.usable:
            summary["note"] = (f"Still dark at the {cap} us shutter this club needs (a fast ball smears at anything longer). "
                               "Add light, or pick a slower club's setting for shorter shots.")
    return {**summary, **exposure_configuration()}


def auto_calibrate_light(grab_frame: "Callable[[], Any]", light: Any = None,
                         max_exposure_us: int | None = None) -> dict[str, Any]:
    """Choose daylight or flat light for the scene, then size the exposure for it.

    With the ring off, the normal exposure sweep says whether the ambient light alone
    is enough: a usable picture at a short exposure means daylight, and the ring stays
    off. Otherwise the ring goes steady and the sweep runs again. Without a connected
    light controller the ring cannot be switched, so this is the plain exposure sweep.
    """
    if light is None or not light.status().get("connected"):
        return {**auto_calibrate_camera(grab_frame, max_exposure_us), "light": active_light()}

    chosen = "flat"
    try:
        light.set_mode("off")
        time.sleep(0.2)  # let the ring go dark before the first probe
        result = auto_calibrate_camera(grab_frame, max_exposure_us)
        if result.get("usable") and result["exposureUs"] <= DAYLIGHT_MAX_EXPOSURE_US:
            chosen = "daylight"
        else:
            light.set_mode("flat")
            time.sleep(0.2)
            result = auto_calibrate_camera(grab_frame, max_exposure_us)
    except Exception:
        light.set_mode("flat")  # never strand the ring off after a failed sweep
        raise

    settings = _load_camera_settings()
    profiles = dict(settings.get("lightProfiles") or {})
    profiles[chosen] = {"exposureUs": int(result["exposureUs"]), "gain": float(result["gain"])}
    _save_camera_settings({"lightMode": "auto", "activeLight": chosen, "strobeMode": False,
                           "lightProfiles": profiles})
    return {**result, **exposure_configuration(), "light": chosen}


class CsiCapture:
    """Picamera2 adapter returning OpenCV-compatible images from one owned stream."""

    def __init__(self, index: int | None = None, *, sync_mode: Any = None,
                 start: bool = True, publish: bool = True) -> None:
        from picamera2 import Picamera2

        self.camera = None
        self.publish = publish
        self.metadata: dict[str, Any] = {}
        self.raw_enabled = raw_capture_enabled()
        width, height = map(int, os.getenv("PINPOINT_CAMERA_RESOLUTION", "1280x800").split("x"))
        fps = float(os.getenv("PINPOINT_CAMERA_FPS", "30"))
        if width <= 0 or height <= 0 or fps <= 0:
            raise ValueError("Camera dimensions and frame rate must be positive")
        self.index = int(os.getenv("PINPOINT_CAMERA_INDEX", "0")) if index is None else index
        camera = Picamera2(self.index)
        try:
            controls: dict[str, Any] = {"FrameRate": fps, "AeEnable": True}
            if sync_mode is not None:
                controls["SyncMode"] = sync_mode
            exposure = configured_exposure_us()
            gain = configured_camera_gain()
            if exposure > 0:
                controls.update(AeEnable=False, ExposureTime=exposure,
                                AnalogueGain=gain)
            streams: dict[str, Any] = {}
            if self.raw_enabled:
                streams["raw"] = {"size": (width, height), "format": "R10"}
            config = camera.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"},
                sensor={"output_size": (width, height), "bit_depth": int(os.getenv("PINPOINT_CAMERA_BIT_DEPTH", "10"))},
                **streams,
                # Extra queued requests absorb short stalls in the detection loop
                # instead of dropping 200 fps frames (640x400 RGB is ~0.8 MB each).
                controls=controls, buffer_count=max(4, int(os.getenv("PINPOINT_CAMERA_BUFFER_COUNT", "8"))),
            )
            camera.configure(config)
            self.exposure_limits = _sensor_exposure_limits(camera)
            if publish:
                _publish_hardware_limits(self.exposure_limits)
            if start:
                camera.start()
            self.model = str(camera.camera_properties.get("Model", "CSI camera"))
            self.exposure_us = exposure
            self.gain = gain
            self.camera = camera
            global _active_capture
            if publish:
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
        return self.finish_read(job)

    def finish_read(self, job: Any) -> tuple[bool, Any]:
        """Complete a request already queued, allowing both sensors to run together."""
        try:
            request = self.camera.wait(job, timeout=2)
        except TimeoutError:
            self.camera.cancel_all_and_flush()
            raise RuntimeError("CSI camera stopped delivering frames") from None
        try:
            frame = request.make_array("main")
            self.metadata = request.get_metadata()
            if self.raw_enabled:
                # The request's buffer is reused as soon as it is released, so the raw frame is copied out.
                # The raw array is bytes (h, 2w): view it as 16-bit words, dropping any row padding.
                self.metadata["RawFrame"] = request.make_array("raw").view("<u2")[:, :frame.shape[1]].copy()
            duration = self.metadata.get("FrameDuration", 0)
            diagnostics = {
                "model": self.model, "width": frame.shape[1], "height": frame.shape[0],
                "fps": round(1_000_000 / duration, 1) if duration else 0,
                "exposureUs": self.metadata.get("ExposureTime", 0),
                "gain": round(self.metadata.get("AnalogueGain", 1), 2),
                "autoExposure": self.exposure_us <= 0,
                "autofocus": "AfMode" in self.camera.camera_controls,
            }
            if self.publish:
                record_camera_diagnostics(diagnostics)
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
        if self.publish:
            _publish_hardware_limits(None)
            clear_camera_diagnostics()


class DualCsiCapture:
    """One owner for two software-synchronised OV9281 streams.

    Frames are paired by their sensor clocks, never by host read order. A missing
    camera or lost timing lock fails the pair so the detector cannot arm on an
    incomplete capture. This is acquisition, not stereo calibration/measurement.
    """

    def __init__(self) -> None:
        from libcamera import controls

        self.cameras: list[CsiCapture] = []
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._queues = [deque(maxlen=16), deque(maxlen=16)]
        self._threads: list[threading.Thread] = []
        self._error: Exception | None = None
        self._pair_times: deque[int] = deque(maxlen=128)
        self.metadata: dict[str, Any] = {}
        self.secondary_metadata: dict[str, Any] = {}
        self.secondary_frame = None
        # Staggered capture state (see the module constants). ``idle`` is set by the detection loop:
        # true when no ball is on the mat, the only time the second camera may be restarted.
        self.stagger = stagger_enabled()
        self.stagger_state = "locking" if self.stagger else "off"
        self.stagger_error: str | None = None
        self.stagger_attempts = 0
        self.stagger_relocks = 0
        self._failed_at = 0.0
        self._last_stagger_log = 0.0
        self.idle = True
        self._phases: deque[float] = deque(maxlen=24)
        self._a_stamps: deque[int] = deque(maxlen=1024)
        self._pause_b = threading.Event()
        self._b_idle = threading.Event()
        self.tolerance_us = float(os.getenv("PINPOINT_CAMERA_SYNC_TOLERANCE_US", "250"))
        fps = float(os.getenv("PINPOINT_CAMERA_FPS", "200"))
        if not 0 < self.tolerance_us < 500_000 / fps:
            raise ValueError("Camera sync tolerance must be positive and less than half a frame")
        primary = int(os.getenv("PINPOINT_CAMERA_INDEX", "0"))
        secondary = int(os.getenv("PINPOINT_SECONDARY_CAMERA_INDEX", "1"))
        if primary == secondary:
            raise ValueError("Dual cameras must have different indexes")
        try:
            if self.stagger:
                try:
                    self._open_staggered(primary, secondary)
                except Exception as error:
                    # Never leave the monitor dead: fall back to the in-step pair and say so.
                    LOGGER.warning("Staggered capture unavailable (%s); running the cameras in step", error)
                    self.stagger, self.stagger_state, self.stagger_error = False, "failed", str(error)
                    self._close_cameras()
            if not self.cameras:
                for index, mode in ((primary, controls.rpi.SyncModeEnum.Server),
                                    (secondary, controls.rpi.SyncModeEnum.Client)):
                    self.cameras.append(CsiCapture(index, sync_mode=mode, start=False, publish=False))
                self.cameras[1].camera.start()
                self.cameras[0].camera.start()
            self.exposure_us = self.cameras[0].exposure_us
            self.gain = self.cameras[0].gain
            # Both sensors get the same shutter, so only the range both accept is offered.
            ranges = [r for r in (getattr(c, "exposure_limits", None) for c in self.cameras)
                      if isinstance(r, tuple) and len(r) == 2 and all(isinstance(v, int) for v in r)]
            _publish_hardware_limits((max(r[0] for r in ranges), min(r[1] for r in ranges)) if ranges else None)
            for index in range(2):
                thread = threading.Thread(target=self._collect, args=(index,),
                                          name=f"lm1-camera-{index}", daemon=True)
                self._threads.append(thread)
                thread.start()
            global _active_capture
            with _lock:
                _active_capture = self
        except Exception:
            self.release()
            raise

    def isOpened(self) -> bool:
        return len(self.cameras) == 2 and all(c.isOpened() for c in self.cameras)

    @property
    def pairing_ok(self) -> bool:
        """False while the staggered pair is out of step or being re-locked: detection must not arm."""
        return not self.stagger or self.stagger_state in ("locked", "drift-soon")

    def _close_cameras(self) -> None:
        cameras, self.cameras = self.cameras, []
        for camera in reversed(cameras):
            try:
                camera.release()
            except Exception:
                pass

    @staticmethod
    def _drain_stamps(camera: Any, seconds: float, sink: "list[int]") -> None:
        """Collect sensor timestamps from one camera for a while, discarding the images."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                job = camera.capture_request(wait=False)
                request = camera.wait(job, timeout=1)
            except Exception:
                return
            try:
                stamp = request.get_metadata().get("SensorTimestamp")
            finally:
                request.release()
            if stamp:
                sink.append(int(stamp))

    def _measure_b_phase(self, a_stamps: "list[int]", drain_a: bool) -> "float | None":
        """Phase of camera B behind camera A over a short window; None when either stream is too thin."""
        first, second = (c.camera for c in self.cameras)
        b_stamps: list[int] = []
        threads = [threading.Thread(target=self._drain_stamps, args=(second, STAGGER_MEASURE_SECONDS, b_stamps), daemon=True)]
        if drain_a:
            threads.append(threading.Thread(target=self._drain_stamps, args=(first, STAGGER_MEASURE_SECONDS, a_stamps), daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(STAGGER_MEASURE_SECONDS + 2)
        a = sorted(a_stamps if drain_a else list(self._a_stamps))
        if len(b_stamps) < 40 or len(a) < 40:
            return None
        period_ns = (a[-1] - a[-40]) / 39.0
        settled = b_stamps[len(b_stamps) // 3:]
        phases = [phase_of(a, stamp, period_ns) for stamp in settled]
        phases = [p for p in phases if p is not None]
        if not phases:
            return None
        import math as _math
        s = sum(_math.sin(2 * _math.pi * p) for p in phases) / len(phases)
        c = sum(_math.cos(2 * _math.pi * p) for p in phases) / len(phases)
        return (_math.atan2(s, c) % (2 * _math.pi)) / (2 * _math.pi)

    def _lock_second_camera(self, drain_a: bool, attempt_limit: int = STAGGER_MAX_ATTEMPTS) -> int:
        """Restart camera B until it sits near half a frame behind A. Returns the attempts used."""
        second = self.cameras[1].camera
        a_stamps: list[int] = list(self._a_stamps)
        for attempt in range(1, attempt_limit + 1):
            second.start()
            phase = self._measure_b_phase(a_stamps, drain_a)
            if phase is not None and stagger_distance(phase) <= STAGGER_LOCK_TOLERANCE:
                self._phases.clear()
                self._phases.append(phase)
                return attempt
            try:
                second.stop()
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"The cameras did not settle half a frame apart in {attempt_limit} tries")

    def _open_staggered(self, primary: int, secondary: int) -> None:
        for index in (primary, secondary):
            self.cameras.append(CsiCapture(index, sync_mode=None, start=False, publish=False))
        self.cameras[0].camera.start()
        # Camera A must be drained while B is measured, or its request queue backs up.
        a_stamps: list[int] = []
        drain = threading.Thread(target=self._drain_stamps, args=(self.cameras[0].camera, 1.0, a_stamps), daemon=True)
        drain.start()
        drain.join(3)
        self._a_stamps.extend(a_stamps)
        self.stagger_attempts = self._lock_second_camera(drain_a=True)
        self.stagger_state = "locked"
        LOGGER.info("Staggered capture locked after %d tries at phase %.3f", self.stagger_attempts, self._phases[-1])

    def resync(self) -> bool:
        """Re-lock the second camera while nothing is on the mat. Blocks for a few seconds."""
        if not self.stagger or not self.isOpened():
            return False
        self.stagger_state = "resyncing"
        record_camera_diagnostics({"staggerState": "resyncing"})
        self._pause_b.set()
        self._b_idle.wait(1.0)
        try:
            self.cameras[1].camera.stop()
            attempts = self._lock_second_camera(drain_a=False)
            self.stagger_relocks += 1
            self.stagger_state = "locked"
            LOGGER.info("Staggered capture re-locked after %d tries at phase %.3f", attempts, self._phases[-1])
            return True
        except Exception as error:
            self.stagger_state = "failed"
            self.stagger_error = str(error)
            self._failed_at = time.monotonic()
            LOGGER.warning("Staggered re-lock failed: %s", error)
            return False
        finally:
            with self._condition:
                for queue in self._queues:
                    queue.clear()
                self._a_stamps.clear()
            self._pause_b.clear()

    def _set_both(self, method: str, value: Any, previous: Any) -> None:
        try:
            for camera in self.cameras:
                getattr(camera, method)(value)
            with self._condition:
                for queue in self._queues:
                    queue.clear()
        except Exception:
            for camera in self.cameras:
                getattr(camera, method)(previous)
            raise

    def set_exposure(self, exposure_us: int) -> None:
        self._set_both("set_exposure", exposure_us, self.exposure_us)
        self.exposure_us = exposure_us

    def set_gain(self, gain: float) -> None:
        self._set_both("set_gain", gain, self.gain)
        self.gain = gain

    def _collect(self, index: int) -> None:
        """Drain each stream independently so pairing cannot chase newer frames."""
        try:
            camera = self.cameras[index]
            sync_ready = False
            while not self._stop.is_set():
                if index == 1 and self._pause_b.is_set():
                    self._b_idle.set()
                    time.sleep(0.01)
                    continue
                if index == 1:
                    self._b_idle.clear()
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError(f"Camera {camera.index} stopped delivering frames")
                metadata = dict(camera.metadata)
                # libcamera reports SyncReady intermittently, not on every frame.
                # Retain its last explicit state; timestamp tolerance is still
                # checked for every individual pair, including after a drift.
                if "SyncReady" in metadata:
                    sync_ready = bool(metadata["SyncReady"])
                metadata["SyncReady"] = sync_ready
                if not metadata.get("SensorTimestamp"):
                    raise RuntimeError("Both cameras must supply sensor timestamps")
                if index == 0 and self.stagger:
                    self._a_stamps.append(int(metadata["SensorTimestamp"]))
                with self._condition:
                    self._queues[index].append((frame, metadata))
                    self._condition.notify_all()
        except Exception as error:
            with self._condition:
                self._error = error
                self._condition.notify_all()

    def _read_staggered(self) -> "tuple[bool, Any]":
        """Pair each A frame with the B frame that follows it by about half a frame."""
        if self.idle and (self.stagger_state in ("drift-soon", "drifted")
                          or (self.stagger_state == "failed" and time.monotonic() - self._failed_at > 30)):
            self.resync()
        deadline = time.monotonic() + 5
        with self._condition:
            while True:
                if self._error is not None:
                    raise RuntimeError(f"Dual camera capture failed: {self._error}") from self._error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Dual camera timing did not lock within five seconds")
                if not all(self._queues):
                    self._condition.wait(min(remaining, 0.1))
                    continue
                frame, metadata = self._queues[0][0]
                other, other_metadata = self._queues[1][0]
                a, b = metadata["SensorTimestamp"], other_metadata["SensorTimestamp"]
                duration_ns = (metadata.get("FrameDuration") or 4132) * 1000.0
                fraction = (b - a) / duration_ns
                if 0.1 <= fraction <= 0.9:
                    self._queues[0].popleft()
                    self._queues[1].popleft()
                    break
                # B earlier than A means B belongs to the previous A: drop it; B a frame late: drop A.
                self._queues[1 if fraction < 0.1 else 0].popleft()
        self._phases.append(fraction)
        if self.stagger_state not in ("resyncing", "failed"):
            previous = self.stagger_state
            self.stagger_state = stagger_state(list(self._phases)[-12:])
            if self.stagger_state != previous:
                LOGGER.info("Staggered pair %s -> %s at phase %.3f", previous, self.stagger_state, fraction)
        now = time.monotonic()
        if now - self._last_stagger_log >= 60:
            self._last_stagger_log = now
            recent = list(self._phases)[-48:]
            LOGGER.info("Staggered pair %s: phase %.3f (recent %.3f to %.3f), %d re-locks",
                        self.stagger_state, fraction, min(recent), max(recent), self.stagger_relocks)
        self.metadata, self.secondary_metadata, self.secondary_frame = metadata, other_metadata, other
        self._pair_times.append(a)
        elapsed = self._pair_times[-1] - self._pair_times[0]
        paired_fps = round((len(self._pair_times) - 1) * 1e9 / elapsed, 1) if elapsed > 0 else 0
        first, second = self.cameras
        duration = metadata.get("FrameDuration", 0)
        secondary_duration = other_metadata.get("FrameDuration", 0)
        record_camera_diagnostics({
            "model": first.model, "width": frame.shape[1], "height": frame.shape[0],
            "fps": round(1_000_000 / duration, 1) if duration else 0,
            "exposureUs": metadata.get("ExposureTime", 0),
            "gain": round(metadata.get("AnalogueGain", 1), 2),
            "autoExposure": self.exposure_us <= 0, "autofocus": False,
            "cameraCount": 2, "primaryCameraIndex": first.index, "pairedFps": paired_fps,
            "secondaryCameraIndex": second.index, "syncMode": "stagger", "syncReady": self.pairing_ok,
            "syncOffsetUs": round((b - a) / 1000, 1), "syncToleranceUs": self.tolerance_us,
            "staggerState": self.stagger_state, "staggerPhase": round(fraction, 3),
            "staggerRelocks": self.stagger_relocks,
            "secondaryFps": round(1_000_000 / secondary_duration, 1) if secondary_duration else 0,
            "secondaryExposureUs": other_metadata.get("ExposureTime", 0),
            "secondaryGain": round(other_metadata.get("AnalogueGain", 1), 2),
        })
        return True, frame

    def read(self) -> tuple[bool, Any]:
        if not self.isOpened():
            return False, None
        if self.stagger:
            return self._read_staggered()
        first, second = self.cameras
        deadline = time.monotonic() + 5
        with self._condition:
            while True:
                if self._error is not None:
                    raise RuntimeError(f"Dual camera capture failed: {self._error}") from self._error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Dual camera timing did not lock within five seconds")
                if not all(self._queues):
                    self._condition.wait(min(remaining, 0.1))
                    continue
                frame, metadata = self._queues[0][0]
                other, other_metadata = self._queues[1][0]
                a, b = metadata["SensorTimestamp"], other_metadata["SensorTimestamp"]
                offset = (b - a) / 1000
                if bool(other_metadata.get("SyncReady")) and abs(offset) <= self.tolerance_us:
                    self._queues[0].popleft()
                    self._queues[1].popleft()
                    break
                record_camera_diagnostics({"cameraCount": 2, "syncReady": False, "syncOffsetUs": offset})
                self._queues[0 if a <= b else 1].popleft()
        self.metadata = metadata
        self.secondary_metadata = other_metadata
        self.secondary_frame = other
        self._pair_times.append(metadata["SensorTimestamp"])
        elapsed = self._pair_times[-1] - self._pair_times[0]
        paired_fps = round((len(self._pair_times) - 1) * 1e9 / elapsed, 1) if elapsed > 0 else 0
        duration = self.metadata.get("FrameDuration", 0)
        secondary_duration = self.secondary_metadata.get("FrameDuration", 0)
        record_camera_diagnostics({
            "model": first.model, "width": frame.shape[1], "height": frame.shape[0],
            "fps": round(1_000_000 / duration, 1) if duration else 0,
            "exposureUs": self.metadata.get("ExposureTime", 0),
            "gain": round(self.metadata.get("AnalogueGain", 1), 2),
            "autoExposure": self.exposure_us <= 0, "autofocus": False,
            "cameraCount": 2, "primaryCameraIndex": first.index,
            "pairedFps": paired_fps,
            "secondaryCameraIndex": second.index, "syncMode": "software",
            "syncReady": True, "syncOffsetUs": round(offset, 1),
            "syncToleranceUs": self.tolerance_us,
            "secondaryFps": round(1_000_000 / secondary_duration, 1) if secondary_duration else 0,
            "secondaryExposureUs": self.secondary_metadata.get("ExposureTime", 0),
            "secondaryGain": round(self.secondary_metadata.get("AnalogueGain", 1), 2),
        })
        return True, frame

    def release(self) -> None:
        global _active_capture
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.5)
        with _lock:
            if _active_capture is self:
                _active_capture = None
        cameras, self.cameras = self.cameras, []
        try:
            for camera in reversed(cameras):
                try:
                    camera.release()
                except Exception:
                    # Always attempt to close the other sensor too.
                    pass
        finally:
            self.secondary_frame = None
            for queue in self._queues:
                queue.clear()
            _publish_hardware_limits(None)
            clear_camera_diagnostics()
