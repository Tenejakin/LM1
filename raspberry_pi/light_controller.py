"""USB link to the ESP32 that drives the IR ring: off, steady (flat) or strobing.

The ESP32 boots in flat (steady) light and, while strobing, drops back to flat by
itself when it stops hearing from the host, so a crashed service can never leave
the ring flickering. This side keeps a heartbeat going, reconnects when the cable
is unplugged and re-applies the wanted mode after every reconnect.

Nothing here is required: without PINPOINT_LIGHT_CONTROL=esp32 the service runs
exactly as it did before and `get_light_controller()` returns None.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from typing import Any, Callable

LOGGER = logging.getLogger("pinpoint.light")

RING_MODES = ("off", "flat", "strobe")
STROBE_PRESETS = ("driver", "iron", "chip")
HEARTBEAT_SECONDS = 1.0
RECONNECT_SECONDS = 2.0
BAUD = 115200

def indicator_state(device_state: str, ball_present: bool) -> str:
    if device_state == "processing":
        return "processing"
    return "ready" if ball_present else "searching"


def preset_for_club(club_id: str | None) -> str:
    """Pick the flash pattern for a club type: wide gaps for slow balls, tight for fast."""
    club = (club_id or "").lower()
    if club == "driver" or "wood" in club or "hybrid" in club:
        return "driver"
    if "wedge" in club or "putter" in club:
        return "chip"
    return "iron"


BALL_DIAMETER_MM = 42.67
MAX_PATTERN_GAPS = 15


def strobe_pattern(ball_speed_mps: float, period_us: int) -> dict[str, Any]:
    """Flash pulse and gaps for one burst, sized for a club's expected ball speed.

    The gaps keep neighbouring ball copies from overlapping even when the ball is 20 %
    slower than expected (1.1 ball widths apart), and grow 8 % each so every copy can be
    told from its neighbours. The pulse blurs the ball by about 1.2 mm: short for fast
    balls, longer (more light) for slow ones. A burst may fill 82 % of the frame, and
    the quiet stretch before the next frame's burst must also be a usable gap, so slow
    shots get fewer flashes - down to one per frame.
    """
    speed = min(95.0, max(8.0, float(ball_speed_mps)))
    pulse = int(min(60, max(15, round(1200.0 / speed))))
    first_gap = 1.375 * BALL_DIAMETER_MM / speed * 1000.0
    budget = 0.82 * period_us
    gaps: list[int] = []
    while len(gaps) < MAX_PATTERN_GAPS:
        gap = int(round(first_gap * 1.08 ** len(gaps) / 10.0) * 10)
        burst = pulse + sum(gaps) + gap
        if burst > budget or period_us - burst < 0.95 * first_gap:
            break
        gaps.append(gap)
    return {"pulseUs": pulse, "gapsUs": gaps, "ballSpeedMps": round(speed, 1)}


def _find_port() -> str | None:
    explicit = os.getenv("PINPOINT_LIGHT_PORT")
    if explicit:
        return explicit
    for pattern in ("/dev/serial/by-id/*Espressif*", "/dev/serial/by-id/*ESP32*", "/dev/ttyACM*"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def _open_serial(port: str) -> Any:
    import serial  # pyserial; imported late so the service starts without it

    return serial.Serial(port, BAUD, timeout=0.2, write_timeout=1.0)


class LightController:
    def __init__(self, *, fps: int = 242, find_port: Callable[[], str | None] = _find_port,
                 open_port: Callable[[str], Any] = _open_serial,
                 heartbeat_seconds: float = HEARTBEAT_SECONDS) -> None:
        self._fps = int(fps)
        self._find_port = find_port
        self._open_port = open_port
        self._heartbeat = heartbeat_seconds
        self._lock = threading.RLock()
        self._serial: Any = None
        self._port: str | None = None
        self._mode = "flat"
        self._preset = "driver"
        self._pattern: dict[str, Any] | None = None
        self._reported_mode: str | None = None
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_provider: Callable[[], str] | None = None
        self._sent_status: str | None = None

    def set_status_provider(self, provider: Callable[[], str]) -> None:
        self._status_provider = provider

    def _update_status_locked(self) -> None:
        if self._serial is None or self._status_provider is None:
            return
        state = self._status_provider()
        if state not in {"searching", "ready", "processing"}:
            return
        if state != self._sent_status:
            self._serial.write(f"led {state}\n".encode("ascii"))
            self._sent_status = state

    # -- public -----------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="light-controller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._close()

    def set_mode(self, mode: str, preset: str | None = None, pattern: dict[str, Any] | None = None) -> bool:
        """Remember the wanted ring mode and send it now if the ESP32 is connected.

        In strobe, `pattern` ({pulseUs, gapsUs}) overrides the named preset, which is then
        only a label for the club group."""
        if mode not in RING_MODES:
            raise ValueError("Ring mode must be off, flat or strobe.")
        if preset is not None and preset not in STROBE_PRESETS:
            raise ValueError("Unknown strobe preset.")
        with self._lock:
            self._mode = mode
            if preset is not None:
                self._preset = preset
            self._pattern = dict(pattern) if pattern and mode == "strobe" else None
            return self._apply_locked()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": True,
                "connected": self._serial is not None,
                "port": self._port,
                "mode": self._mode,
                "rateHz": self._fps,
                "preset": self._preset if self._mode == "strobe" else None,
                "pattern": self._pattern if self._mode == "strobe" else None,
                "reportedMode": self._reported_mode,
                "error": self._error,
            }

    # -- internals --------------------------------------------------------------
    def _commands(self) -> list[str]:
        if self._mode == "strobe":
            commands = [f"rate {self._fps}"]
            if self._pattern:
                gaps = [int(gap) for gap in self._pattern["gapsUs"]]
                commands.append(f"p {int(self._pattern['pulseUs'])}")
                commands.append("i " + " ".join(str(gap) for gap in gaps) if gaps else "f 1 1000")
                commands.append("mode strobe")
            else:
                commands.append(f"mode strobe {self._preset}")
            return commands
        return [f"mode {self._mode}"]

    def _apply_locked(self) -> bool:
        if self._serial is None:
            return False
        try:
            for command in self._commands():
                self._serial.write((command + "\n").encode("ascii"))
            self._serial.flush()
            return True
        except Exception as error:  # noqa: BLE001 - any serial failure means reconnect
            self._fail(error)
            return False

    def _fail(self, error: Exception) -> None:
        self._error = str(error)
        LOGGER.warning("Light controller link lost: %s", error)
        self._close()

    def _close(self) -> None:
        with self._lock:
            serial, self._serial = self._serial, None
            self._reported_mode = None
            self._sent_status = None
        if serial is not None:
            try:
                serial.close()
            except Exception:  # noqa: BLE001
                pass

    def _read_replies(self) -> None:
        serial = self._serial
        if serial is None:
            return
        try:
            data = serial.read(512)
        except Exception as error:  # noqa: BLE001
            self._fail(error)
            return
        for line in data.decode("ascii", errors="replace").splitlines():
            line = line.strip()
            if line.startswith(("OK", "PONG")):
                for part in line.split():
                    if part.startswith("mode="):
                        self._reported_mode = part[5:]
            elif line.startswith("WATCHDOG"):
                self._reported_mode = "flat"
                LOGGER.warning("ESP32 watchdog returned the ring to flat light")

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                connected = self._serial is not None
            if not connected:
                port = self._find_port()
                if port is None:
                    self._error = "No ESP32 found on USB."
                    self._stop.wait(RECONNECT_SECONDS)
                    continue
                try:
                    opened = self._open_port(port)
                except Exception as error:  # noqa: BLE001
                    self._error = str(error)
                    self._stop.wait(RECONNECT_SECONDS)
                    continue
                with self._lock:
                    self._serial, self._port, self._error = opened, port, None
                    self._apply_locked()
                LOGGER.info("Light controller connected on %s, mode %s", port, self._mode)
            with self._lock:
                if self._serial is not None:
                    try:
                        self._serial.write(b"ping\n")
                        self._update_status_locked()
                    except Exception as error:  # noqa: BLE001
                        self._fail(error)
            self._read_replies()
            self._stop.wait(min(self._heartbeat, 0.2) if self._status_provider else self._heartbeat)


_controller: LightController | None = None
_controller_lock = threading.Lock()


def get_light_controller() -> LightController | None:
    """The shared controller, or None unless PINPOINT_LIGHT_CONTROL=esp32 is set."""
    if os.getenv("PINPOINT_LIGHT_CONTROL", "").lower() not in {"esp32", "1", "true", "yes"}:
        return None
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = LightController(fps=int(float(os.getenv("PINPOINT_CAMERA_FPS", "242"))))
            _controller.start()
        return _controller
