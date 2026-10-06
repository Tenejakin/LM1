"""Frames for the ball detector built from the sensor's raw 10-bit data instead of the 8-bit picture.

The image processor's 8-bit output subtracts 64 counts of real signal and then applies a gamma curve, so a dim
scene (a ball lit only by short IR flashes in a dark room) comes out as nearly all zeros. The raw data is linear
and keeps that signal. `raw_to_gray8` maps raw counts straight to grey levels (counts_per_level counts per level,
1.0 by default: levels 0-255 cover the first quarter of the sensor's range, where a dark scene lives), and
`RawAnalysis` hands the detector those frames in place of the 8-bit ones when that helps.

Raw is not simply better. Measured on the Pi, with a ball well above the 64-count crush, the 8-bit picture had the
higher signal-to-noise (ball 79 against a perfectly black, noise-free background at 60 us, SNR 158, versus SNR 11 for
the raw-derived frame): the processor's black crush acts as a free noise gate. Raw only wins when the signal itself is
under about 64 counts, i.e. a dark scene lit by faint flashes. So in `auto` the detector gets raw-derived frames only
while the ring is strobing AND the scene is dark enough that 1 count per level does not saturate; the source switches
with hysteresis (a dwell of a few frames) and `consume_change()` tells the loop to restart the detector's calibration,
because an empty-plane reference learned from one kind of frame is wrong for the other.

PINPOINT_ANALYSIS_SOURCE:
  auto (default)  as above
  raw             always raw-derived
  isp             never
"""

from __future__ import annotations

import os
import time
from typing import Any

import cv2
import numpy as np

from camera_source import RAW_SCALE, raw_black_level

SOURCES = ("auto", "raw", "isp")
STATE_REFRESH_SECONDS = 1.0
DARK_COUNTS = 120.0     # a scene whose 99.5th percentile is under this fits in 8 bits at 1 count per level
BRIGHT_COUNTS = 200.0   # above this it would start to saturate, so the picture is used instead
DWELL_FRAMES = 12       # consecutive frames before the source changes (about 50 ms at 242 fps)


def analysis_source() -> str:
    value = os.getenv("PINPOINT_ANALYSIS_SOURCE", "auto").lower()
    return value if value in SOURCES else "auto"


def counts_per_level() -> float:
    try:
        return max(0.05, float(os.getenv("PINPOINT_RAW_COUNTS_PER_LEVEL", "1.0")))
    except ValueError:
        return 1.0


def raw_to_gray8(raw: Any, black_level: float | None = None, per_level: float | None = None) -> np.ndarray:
    """Linear 8-bit grey from raw words: (word - black) / (RAW_SCALE x counts-per-level), clipped to 0..255."""
    black = raw_black_level() if black_level is None else black_level
    step = RAW_SCALE * (counts_per_level() if per_level is None else per_level)
    levels = (np.asarray(raw, dtype=np.float32) - float(black)) / step
    return np.clip(levels + 0.5, 0, 255).astype(np.uint8)


class RawAnalysis:
    """Chooses, frame by frame, whether the detector gets the raw-derived frame or the 8-bit picture."""

    def __init__(self, light: Any = None, source: str | None = None) -> None:
        self._light = light
        self._source = source
        self._checked_at = 0.0
        self._strobing = False
        self._using_raw = False
        self._streak = 0
        self._changed = False

    def _is_strobing(self) -> bool:
        now = time.monotonic()
        if now - self._checked_at >= STATE_REFRESH_SECONDS:
            self._checked_at = now
            try:
                status = self._light.status() if self._light is not None else {}
            except Exception:  # noqa: BLE001 - a broken light link must never stop frames
                status = {}
            self._strobing = status.get("mode") == "strobe"
        return self._strobing

    def active(self) -> bool:
        """Whether the detector is currently being given raw-derived frames."""
        source = self._source or analysis_source()
        if source == "isp":
            return False
        if source == "raw":
            return True
        return self._using_raw and self._is_strobing()

    def _update_auto(self, raw: Any) -> None:
        """Hysteresis: raw while strobing in a dark scene, the picture otherwise."""
        if not self._is_strobing():
            wanted = False
        else:
            counts = (np.asarray(raw)[::4, ::4].astype(np.float32) - raw_black_level()) / RAW_SCALE
            level = float(np.percentile(counts, 99.5))
            wanted = (level < DARK_COUNTS) if not self._using_raw else (level < BRIGHT_COUNTS)
        if wanted == self._using_raw:
            self._streak = 0
            return
        self._streak += 1
        if not wanted or self._streak >= DWELL_FRAMES:
            # Leaving raw (strobe off or the scene brightened) is immediate; entering waits for a steady dark scene.
            self._using_raw = wanted
            self._streak = 0
            self._changed = True

    def consume_change(self) -> bool:
        """True once after the source switched: the detector must restart its calibration."""
        changed, self._changed = self._changed, False
        return changed

    def frame(self, picture: Any, metadata: dict[str, Any] | None, *, follow: bool = False) -> Any:
        """The 3-channel 8-bit frame the detector expects: raw-derived when wanted and available.

        Only the primary camera decides the source; `follow=True` (the second camera) just uses the decision, so the
        two views are always the same kind of frame and cannot flip it between them."""
        raw = (metadata or {}).get("RawFrame")
        if raw is None:
            return picture
        if not follow and (self._source or analysis_source()) == "auto":
            self._update_auto(raw)
        if not self.active():
            return picture
        return cv2.cvtColor(raw_to_gray8(raw), cv2.COLOR_GRAY2BGR)
