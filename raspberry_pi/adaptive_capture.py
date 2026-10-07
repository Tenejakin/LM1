"""Club-aware automatic light/exposure policy (pure logic, no camera or serial I/O).

The sweep itself (``exposure_calibration.calibrate_exposure`` and
``camera_source.auto_calibrate_light``) already chooses daylight vs flat and picks
an exposure and gain for a given blur ceiling. What was missing is the *trigger*:
re-running that sweep when the player changes club (a faster ball needs a shorter
shutter) or when the room changes (the sun moves, a light is switched on). This
module owns that trigger so it can be tested without any hardware.

The decision loop lives in ``BallMonitor.run``; this module only says "run now,
and why", then remembers what it last saw so the same sweep is not repeated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from camera_source import blur_safe_exposure_us
from flight_model import CLUB_BALL_SPEED_MPS

# How often the detection loop may re-check the view while the mat is empty.
CHECK_INTERVAL_S = 3.0
# How far the scene brightness may move (in 8-bit levels) before the auto sweep is
# run again. Wide enough to ignore normal ball/grain noise, narrow enough to catch
# a light being switched on or the sun moving.
DRIFT_BRIGHT = 40.0
DEFAULT_COOLDOWN_S = 8.0
MIN_COOLDOWN_S = 2.0


def club_ball_speed_mps(club_id: str | None) -> float:
    """Typical full-swing ball speed for a club, metres per second."""
    return CLUB_BALL_SPEED_MPS.get(club_id or "", CLUB_BALL_SPEED_MPS["driver"])


def club_exposure_cap_us(club_id: str | None, putting: bool = False) -> int | None:
    """Longest shutter the measurement accepts for this club; None means no cap.

    Putting is slow, so it keeps the full range; a faster ball needs a shorter
    shutter to stay under the 4 mm motion-blur limit.
    """
    if putting:
        return None
    return blur_safe_exposure_us(club_ball_speed_mps(club_id))


@dataclass(frozen=True)
class ViewSample:
    """A live frame reduced to the one number the drift policy needs."""

    bright: float

    @classmethod
    def from_frame(cls, frame: Any) -> "ViewSample":
        """Measure the frame the same way the exposure sweep does (the ball, not the average)."""
        from exposure_calibration import measure_frame

        return cls(bright=measure_frame(frame).bright)


class AdaptivePolicy:
    """Remembers the last sweep and says when the auto sweep should run again.

    The decision is deliberately cheap and conservative: re-run on startup, when
    the club changes, and (after a cooldown) when the scene brightness drifts far
    from what the last sweep saw. A club change bypasses the cooldown so the new
    club's shutter is applied promptly; everything else is throttled so a dim room
    that simply cannot reach a fast club's blur limit does not re-sweep forever.
    """

    def __init__(
        self,
        *,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        drift_bright: float = DRIFT_BRIGHT,
    ) -> None:
        self.cooldown_s = max(MIN_COOLDOWN_S, float(cooldown_s))
        self.drift_bright = float(drift_bright)
        self._last_at: float | None = None
        self._last_club: str | None = None
        self._last_bright: float | None = None

    def should_recalibrate(
        self, club_id: str | None, sample: ViewSample, now: float
    ) -> str | None:
        """Why the auto sweep should run now, or None to leave it alone."""
        if self._last_at is None:
            return "startup"
        if club_id != self._last_club:
            return "club"
        if now - self._last_at < self.cooldown_s:
            return None
        if self._last_bright is None or abs(sample.bright - self._last_bright) > self.drift_bright:
            return "drift"
        return None

    def record(self, club_id: str | None, bright: float, now: float) -> None:
        """Remember what one sweep saw so the next check can judge drift against it."""
        self._last_at = now
        self._last_club = club_id
        self._last_bright = float(bright)
