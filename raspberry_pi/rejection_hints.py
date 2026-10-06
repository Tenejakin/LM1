"""Plain-language reasons for a rejected shot, with what to change.

The measurement's own messages are written for the code ("Use fixed exposure at or below 250 us...", "Fewer than three
usable 3D ball outlines...") and gave no hint of the cause. Across 99 retained captures the two of them accounted for
every rejection: 50 shots had too few outlines (the success rate rose from 28 % with a 15-20 px ball to 69 % at
39-47 px) and 18 were thrown away by the exposure gate, all of them taken in strobe mode in a lit room. This keeps the
original text but leads with the cause and the fix. Nothing here changes whether a shot is measured.
"""

from __future__ import annotations

from typing import Any

EXPOSURE_GATE_PREFIX = "Use fixed exposure"
OUTLINES_PREFIX = "Fewer than three usable 3D ball outlines"
STROBE_EXPOSURE_US = 1500        # anything longer is a strobe-mode exposure
GOOD_BALL_PX = 40                # shots measure best from here (about 40-56 px)
MAX_EXPOSURE_US = 250
BLUR_LIMIT_MM = 4.0


def _bright_scene(scene_p995_counts: float | None, picture_p995: float | None) -> bool:
    if scene_p995_counts is not None:
        return scene_p995_counts > 300.0     # raw 10-bit counts: the flashes (tens of counts) are lost in it
    return picture_p995 is not None and picture_p995 > 200.0


def friendly_failure(failure: str | None, *, exposure_us: float | None, light_mode: str | None, ball_px: float | None,
                     scene_p995_counts: float | None = None, picture_p995: float | None = None) -> str | None:
    """The failure text with the cause first; unrelated or empty failures are returned unchanged."""
    if not failure:
        return failure
    if failure.startswith(EXPOSURE_GATE_PREFIX) and exposure_us:
        e = float(exposure_us)
        if light_mode == "strobe" or e > STROBE_EXPOSURE_US:
            lit = _bright_scene(scene_p995_counts, picture_p995)
            cause = ("the room is lit, so the ring's flashes are lost in the room light and the ball is just a smear"
                     if lit else "the ball has to show as separate flash copies, which needs a dark room")
            return (f"Not measured: strobe mode ({e:.0f} us exposure) only measures from flash copies of the ball, and {cause}. "
                    "Switch Light to Auto, Flat or Daylight to measure shots in this light.")
        smear = 0.01 * e  # mm of smear for a 10 m/s ball (a chip): speed x time
        return (f"Not measured: the {e:.0f} us shutter is too long (limit {MAX_EXPOSURE_US} us; a 10 m/s chip already smears "
                f"{smear:.1f} mm against a {BLUR_LIMIT_MM:.0f} mm limit, and faster shots need a shorter one). "
                "Run Auto-set for this room and club, which keeps the shutter short and raises the brightness boost instead.")
    if failure.startswith(OUTLINES_PREFIX):
        if ball_px is not None and ball_px < GOOD_BALL_PX - 5:
            hint = (f"The ball is only {ball_px:.0f} px wide here and shots measure best at {GOOD_BALL_PX} px or more "
                    "(28 % of shots with a 15-20 px ball measured, 69 % at 39-47 px): move the camera closer.")
        else:
            hint = ("The ball left the view within a frame or two, or its edge was unclear: check the ball stands out "
                    "from the surface, and for fast shots use a shorter shutter or a wider view.")
        return f"Not measured: {hint} (Details: {failure})"
    return failure
