"""Version 1.1.0: separate visible ball movement from evidence of a swing.

A missing club track no longer discards a shot whose ball was measured: that
shot is kept with its club values unavailable. Only movement that cannot be a
strike at all (an address nudge, a re-placed ball, a roll with no club) is
classified ``not-a-strike`` in full-shot mode.
"""

import math

# Short chips leave faster than this; address nudges and re-placed balls were
# measured at 0.1-0.9 m/s on real captures.
MIN_STRIKE_SPEED_MPS = 2.0
# A ball knocked sideways or backwards while being set up, not a shot at the target.
MAX_STRIKE_DIRECTION_DEG = 60.0
# A ball that stays on the ground with no club seen is a roll, not a strike.
MAX_ROLL_LAUNCH_DEG = 1.0


def _value(metrics, key):
    value = (metrics.get(key) or {}).get("value")
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def non_strike_reason(measurements, club_observed):
    """Why a measured ball movement cannot be a full-shot strike, or None."""
    metrics = measurements.get("metrics") or {}
    speed = _value(metrics, "ballSpeedMps")
    if speed is None:
        return None  # A tracking failure, not a classification.
    if speed < MIN_STRIKE_SPEED_MPS:
        return (f"Ball moved at {speed:.1f} m/s, slower than any strike "
                f"(minimum {MIN_STRIKE_SPEED_MPS:.0f} m/s): an address nudge or re-placed ball.")
    direction = _value(metrics, "startDirectionDeg")
    if direction is not None and abs(direction) > MAX_STRIKE_DIRECTION_DEG:
        return (f"Ball left {abs(direction):.0f}° off the target line (limit {MAX_STRIKE_DIRECTION_DEG:.0f}°): "
                "knocked or re-placed, not hit toward the target.")
    launch = _value(metrics, "launchAngleDeg")
    if not club_observed and launch is not None and launch <= MAX_ROLL_LAUNCH_DEG:
        return "Ball rolled along the ground with no club detected: not counted as a strike."
    return None


def shot_evidence(measurements, mode=None):
    diagnostics = measurements.get("diagnostics") or {}
    silhouette = diagnostics.get("clubSilhouette")
    tagged = measurements.get("clubTrack3d") or []
    if silhouette is None and not tagged and "diagnostics" not in measurements:
        return measurements.get("shotEvidence")
    stereo_club = diagnostics.get("clubStereo") or {}
    # Any club seen near the ball counts as swing evidence, even when no track passed the
    # measurement checks: a topped chip with the club in view in all 10 frames was
    # classified as a roll with no club (2026-09-25).
    frames = max(len(tagged), (silhouette or {}).get("acceptedFrames", 0),
                 (silhouette or {}).get("candidateFrames", 0), stereo_club.get("triangulatedFrames", 0))
    observed = frames >= 3
    rejection = non_strike_reason(measurements, observed) if mode == "full-shot" else None
    if rejection:
        return {"status": "not-a-strike", "clubFrames": frames, "reason": rejection}
    return {
        "status": "club-motion-observed" if observed else "motion-only",
        "clubFrames": frames,
        "reason": (f"Club motion near the ball tracked in {frames} frames. Contact remains inferred."
                   if observed else "Ball tracked, but no pre-impact club track was resolved; "
                                    "club speed, smash and strike are unavailable for this shot."),
    }
