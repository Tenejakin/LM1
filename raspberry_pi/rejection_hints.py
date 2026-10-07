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


def _strobe_failure(report: dict[str, Any], exposure_us: float, lit: bool) -> str:
    """Why the flash-copy search found nothing, from `strobe_copies.estimate_with_report`.

    The long strobe exposure is never the cause: the copy search does not use the 250 us rule,
    which only guards the ordinary frame-by-frame measurement.
    """
    reason = report.get("reason")
    tail = "Switch Light to Auto, Flat or Daylight to measure shots in this light."
    if reason == "pattern-too-short":
        gaps = report.get("gapsUs") or []
        expected = report.get("expectedSpeedMps")
        return (f"Not measured: the ring was flashing, but this club's flash pattern"
                f"{f' (set for {expected:.0f} m/s)' if expected else ''} fits only {len(gaps) + 1} flash"
                f"{'' if len(gaps) == 0 else 'es'} in one frame, and the copy search needs at least 2 flashes per frame. "
                "A very slow ball needs wide gaps between flashes so the copies do not overlap, and a frame is only about 4 ms long. "
                "For this club use Auto, Flat or Daylight.")
    if reason in ("no-controller", "not-strobing", "no-pattern"):
        seen = report.get("lightMode") or "unknown"
        detail = report.get("controllerError")
        return (f"Not measured: Light is set to Strobe, but the ring was not flashing when this shot was analysed (the light "
                f"controller reported '{seen}'{f', error: {detail}' if detail else ''}), so there were no flash copies to find. "
                "Check the ESP32 is connected on the Pi's USB port, then set Light to Strobe again. " + tail)
    found = int(report.get("maxCopies") or 0)
    searched = int(report.get("framesSearched") or 0)
    speed = report.get("separatesAboveMps")
    expected = report.get("expectedSpeedMps")
    head = (f"Not measured: strobe mode looks for separate flash copies of the ball in the frames after it leaves "
            f"(the {exposure_us:.0f} us exposure is expected, not the problem). ")
    if reason == "too-few-copies" and report.get("maxCopySpanBalls", 0.0) < 0.8:
        return (head + f"The best of {searched} frames held {found} cop{'y' if found == 1 else 'ies'}, and the copies sat within {report.get('maxCopySpanBalls', 0):.1f} "
                "ball widths of each other: the ball moved too little between flashes, so they merged into one. "
                + (f"This flash pattern separates the copies above about {speed:.0f} m/s" if speed else "The flashes are too close together for this speed")
                + (f" (set for {expected:.0f} m/s)" if expected else "") + ". A fast hit is needed. ")
    if reason == "too-few-pairs":
        pair_frames = int(report.get("pairFrames") or 0)
        return (head + f"This club's pattern puts 2 flashes in a frame, and only {pair_frames} frame{'' if pair_frames == 1 else 's'} "
                "held two separate copies; at least 2 frames are needed to time the ball. The ball may have left the view "
                "after one frame, or the copies merged or were lost in the room light. " + tail)
    if reason in ("no-copies", "no-usable-frames"):
        cause = ("the room is lit, so the flashes are lost in the room light" if lit
                 else "no bright round copy stood out from the background; check the ring is on and the room is dark")
        return head + f"None was found in {searched} frames: {cause}. " + tail
    if reason == "too-few-copies":
        need = 2 if len(report.get("gapsUs") or []) == 1 else 3
        return head + f"At most {found} copies were found in {searched} frames and at least {need} are needed. " + tail
    fit = report.get("unreliableFit") or {}
    extra = (f" Best attempt: {fit.get('copies')} copies, {fit.get('fitResidualMm')} mm residual"
             f"{', ambiguous start' if fit.get('ambiguous') else ''}." if fit else "")
    return head + f"{found} copies were found but they did not fit the flash pattern.{extra} " + tail


def friendly_failure(failure: str | None, *, exposure_us: float | None, light_mode: str | None, ball_px: float | None,
                     scene_p995_counts: float | None = None, picture_p995: float | None = None,
                     strobe: dict[str, Any] | None = None) -> str | None:
    """The failure text with the cause first; unrelated or empty failures are returned unchanged."""
    if not failure:
        return failure
    if failure.startswith(EXPOSURE_GATE_PREFIX) and exposure_us:
        e = float(exposure_us)
        if strobe and strobe.get("reason") and (light_mode == "strobe" or e > STROBE_EXPOSURE_US):
            return _strobe_failure(strobe, e, _bright_scene(scene_p995_counts, picture_p995))
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
