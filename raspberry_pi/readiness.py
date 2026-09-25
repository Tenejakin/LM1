"""Pre-shot readiness: find setup faults when the ball is placed, not after the swing.

Version 1.0.0. Each check reuses the gate that would fail the shot later, applied
to the still frames the detector already holds when it arms:

* ground calibration loads for the lower camera;
* the top camera sees the resting ball where the shared calibration puts it
  (the same 15 px and 5 mm limits the stereo fit applies after impact);
* the fixed exposure keeps motion blur within the 4 mm limit at this club's
  typical full-swing ball speed.

The result is advisory. A still frame can mislead the circle finder, so nothing
here blocks a capture; it only says which later gate is expected to fail and why.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np

from flight_model import CLUB_BALL_SPEED_MPS
from launch_measurements import (MAX_MOTION_BLUR_M, RADIUS, load_setup, secondary_camera,
                                 stored_ground_pose)

# Search the top view this far around the ground-plane prediction. Wider than the
# 15 px pass limit so a ball that is off can be found and the offset reported.
UPPER_SEARCH_PX = 60.0
MPS_TO_MPH = 2.23694


def _item(check_id: str, label: str, status: str, detail: str, **values: Any) -> dict[str, Any]:
    return {"id": check_id, "label": label, "status": status, "detail": detail, **values}


def _lower_rest_pixel(camera: dict[str, Any], image: Any, bounds: tuple[int, int, int, int]) -> np.ndarray:
    """Sub-pixel resting centre: the detector box refined by a ball-sized circle fit."""
    from stereo_check import _circle_candidates, _gray
    x, y, width, height = bounds
    approximate = np.array([x + width / 2, y + height / 2], float)
    radius = max(width, height) / 2
    nearby = [circle for circle in _circle_candidates(_gray(image), radius)
              if np.linalg.norm(circle[:2] - approximate) <= max(12.0, radius * 2.0)]
    if not nearby:
        return approximate
    return min(nearby, key=lambda circle: np.linalg.norm(circle[:2] - approximate))[:2].astype(float)


def stereo_rest_check(lower: dict[str, Any], upper: dict[str, Any], lower_image: Any, upper_image: Any,
                      bounds: tuple[int, int, int, int]) -> dict[str, Any]:
    """Locate the resting ball in both views and say whether the shared calibration still holds."""
    from stereo_check import (MAX_RAY_GAP_MM, MAX_REST_HEIGHT_ERROR_MM,
                              _circle_candidates, _gray, _project, _ray, _triangulate)
    label = "Camera alignment"
    rest_px = _lower_rest_pixel(lower, lower_image, bounds)
    origin, direction = _ray(lower, rest_px)
    if abs(direction[2]) < 1e-9:
        return _item("stereo-rest", label, "fail", "The lower camera's view of the ball never meets the ground plane.")
    assumed = origin + direction * (RADIUS - origin[2]) / direction[2]
    predicted = _project(upper, [assumed])[0]
    depth = float((upper["R"] @ assumed + upper["t"])[2])
    if depth <= 0:
        return _item("stereo-rest", label, "fail", "The ball is behind the top camera according to calibration; recalibrate both cameras.")
    radius = RADIUS * upper["K"][0, 0] / depth
    lower_ray = _ray(lower, rest_px)
    candidates = []
    for circle in _circle_candidates(_gray(upper_image), radius):
        if np.linalg.norm(circle[:2] - predicted) > UPPER_SEARCH_PX:
            continue
        point, gap = _triangulate(lower_ray, _ray(upper, circle[:2]))
        candidates.append((gap, circle[:2].astype(float), point))
    if not candidates:
        return _item("stereo-rest", label, "warn",
                     f"The top camera could not find the resting ball within {UPPER_SEARCH_PX:.0f} px of where "
                     "calibration expects it. It may be hidden, badly lit, or a camera has moved.")
    # The true ball is the circle whose ray meets the lower camera's ray.
    gap, upper_px, point = min(candidates, key=lambda item: item[0])
    offset_px = float(np.linalg.norm(upper_px - predicted))
    gap_mm = gap * 1000
    height_error_mm = (float(point[2]) - RADIUS) * 1000
    values = {"offsetPx": round(offset_px, 1), "rayGapMm": round(gap_mm, 2),
              "heightErrorMm": round(height_error_mm, 1)}
    if gap_mm > MAX_RAY_GAP_MM:
        return _item("stereo-rest", label, "fail",
                     f"The two cameras no longer agree on where the ball is (their views miss by {gap_mm:.0f} mm, "
                     f"limit {MAX_RAY_GAP_MM:.0f} mm). A camera or the stand has moved: recalibrate both cameras "
                     "with the AprilTag.", **values)
    where = "above" if height_error_mm > 0 else "below"
    if abs(height_error_mm) > MAX_REST_HEIGHT_ERROR_MM:
        return _item("stereo-rest", label, "fail",
                     f"The ball appears {abs(height_error_mm):.0f} mm {where} the calibrated ground (limit "
                     f"{MAX_REST_HEIGHT_ERROR_MM:.0f} mm): the stand has moved or the tag was calibrated on a "
                     "different surface. Recalibrate both cameras with the AprilTag.", **values)
    # Each shot takes its ground from the resting ball, so a surface a few mm off the
    # calibration (and the top-camera offset it causes) is corrected, not a fault.
    if abs(height_error_mm) >= 5:
        return _item("stereo-rest", label, "ok",
                     f"Both cameras agree on the ball. It sits {abs(height_error_mm):.0f} mm {where} the calibrated "
                     "ground; each shot uses the ball's own height, so this is corrected automatically.", **values)
    return _item("stereo-rest", label, "ok",
                 f"Both cameras agree on the ball position ({offset_px:.0f} px, {height_error_mm:+.0f} mm).", **values)


def exposure_check(exposure_us: float | None, club_id: str, mode: str) -> dict[str, Any]:
    label = "Exposure"
    if not exposure_us or exposure_us <= 0:
        return _item("exposure", label, "fail", "Auto exposure is on; set a fixed exposure so fast balls are not smeared.")
    limit = MAX_MOTION_BLUR_M / (exposure_us * 1e-6)
    values = {"exposureUs": round(float(exposure_us)), "maxBallSpeedMps": round(limit, 1)}
    if mode == "putting":
        return _item("exposure", label, "ok", f"Exposure {exposure_us:.0f} µs is short enough for putts.", **values)
    typical = CLUB_BALL_SPEED_MPS.get(club_id, CLUB_BALL_SPEED_MPS["driver"])
    needed_us = MAX_MOTION_BLUR_M / typical * 1e6
    if limit < typical:
        return _item("exposure", label, "warn",
                     f"Exposure {exposure_us:.0f} µs rejects balls faster than {limit:.0f} m/s "
                     f"({limit * MPS_TO_MPH:.0f} mph) for blur; a full {club_id.replace('-', ' ')} is about "
                     f"{typical:.0f} m/s. Add light, then lower exposure to {math.floor(needed_us):.0f} µs or less.",
                     **values, typicalBallSpeedMps=typical)
    return _item("exposure", label, "ok",
                 f"Exposure {exposure_us:.0f} µs keeps blur under {MAX_MOTION_BLUR_M * 1000:.0f} mm up to "
                 f"{limit:.0f} m/s ({limit * MPS_TO_MPH:.0f} mph).", **values)


BALL_DIAMETER_MM = 42.67
SENSOR_FRAME_S = 1 / 242
# Frames the analysis needs on each side of the ball.
TARGET_FRAMES = 5
# Calibrated on 16 real chips (2026-09-25): the head comes down diagonally from above and
# behind, so its visible path is ~1.4x the horizontal room behind the ball (club data
# appeared from ~105 px of room at 9 m/s); the first two frames after contact show the
# ball overlapping the club and cannot be used.
CLUB_PATH_FACTOR = 1.4
BALL_CONTACT_FRAMES = 2
# Ball diameters in the lower image that tracked reliably on 2026-09-25 (26-27 px and 61 px
# failed; 40-47 px worked).
MIN_BALL_DIAMETER_PX = 32
MAX_BALL_DIAMETER_PX = 56


def placement_geometry(image_shape: tuple[int, ...], bounds: tuple[int, int, int, int]) -> dict[str, Any]:
    """Room around the resting ball in millimetres, using the ball itself as the ruler."""
    height, width = image_shape[:2]
    x, y, w, h = bounds
    diameter = float(max(w, h))
    mm_per_px = BALL_DIAMETER_MM / max(diameter, 1.0)
    return {"id": "placement-geometry", "label": "", "status": "ok", "detail": "",
            "ballDiameterPx": round(diameter, 1), "mmPerPx": round(mm_per_px, 4),
            "behindMm": round(x * mm_per_px, 1), "aheadMm": round((width - x - w) * mm_per_px, 1),
            "aboveMm": round(y * mm_per_px, 1), "imageWidthPx": width}


def placement_check(geometry: dict[str, Any] | None, speeds: dict[str, float], mode: str) -> dict[str, Any] | None:
    """How many club and ball frames this spot allows at these speeds, and where to move the ball."""
    if geometry is None or mode == "putting":
        return None
    label = "Ball position"
    step_mm = lambda speed: speed * 1000 * SENSOR_FRAME_S
    club_step = step_mm(speeds["clubSpeedMps"])
    launch = math.radians(max(0.0, speeds["launchDeg"]))
    ahead_step = max(step_mm(speeds["ballSpeedMps"] * math.cos(launch)), 1e-6)
    up_step = max(step_mm(speeds["ballSpeedMps"] * math.sin(launch)), 1e-6)
    club_frames = CLUB_PATH_FACTOR * geometry["behindMm"] / club_step
    ball_frames = max(0.0, min(geometry["aheadMm"] / ahead_step, geometry["aboveMm"] / up_step) - BALL_CONTACT_FRAMES)
    basis = speeds["basis"]
    values = {"clubFrames": round(club_frames, 1), "ballFrames": round(ball_frames, 1),
              "ballDiameterPx": geometry["ballDiameterPx"], "speedBasis": basis}
    diameter = geometry["ballDiameterPx"]
    if diameter < MIN_BALL_DIAMETER_PX:
        return _item("placement", label, "warn",
                     f"The ball is small in the image ({diameter:.0f} px): move it closer to the cameras until it "
                     f"is about {MIN_BALL_DIAMETER_PX + 8} px across, or it may not be tracked.", **values)
    if diameter > MAX_BALL_DIAMETER_PX:
        return _item("placement", label, "warn",
                     f"The ball is very close to the cameras ({diameter:.0f} px): it leaves the view within a few "
                     f"frames. Move it further away until it is about {MAX_BALL_DIAMETER_PX - 12} px across.", **values)
    needed_behind = TARGET_FRAMES * club_step / CLUB_PATH_FACTOR
    needed_ahead = (TARGET_FRAMES + BALL_CONTACT_FRAMES) * ahead_step
    spare_behind = geometry["behindMm"] - needed_behind
    spare_ahead = geometry["aheadMm"] - needed_ahead
    summary = f"About {club_frames:.0f} club and {ball_frames:.0f} ball frames expected ({basis})."
    if club_frames >= TARGET_FRAMES and ball_frames >= TARGET_FRAMES:
        return _item("placement", label, "ok", summary, **values)
    if geometry["aboveMm"] / up_step < TARGET_FRAMES + BALL_CONTACT_FRAMES <= geometry["aheadMm"] / ahead_step:
        advice = "The ball leaves the top of the view first: move it further from the cameras."
    elif spare_behind < 0 <= spare_ahead:
        shift = min(-spare_behind, spare_ahead)
        advice = f"Move the ball about {shift / 10:.0f} cm towards the target to give the club more frames."
    elif spare_ahead < 0 <= spare_behind:
        shift = min(-spare_ahead, spare_behind)
        advice = f"Move the ball about {shift / 10:.0f} cm back (away from the target) so the flight stays in view."
    else:
        advice = ("There is not enough room at this distance for both club and flight: move the ball further from "
                  "the cameras (the view widens with distance).")
    # 3-4 predicted frames gave club data on only some real chips; 5+ did every time.
    return _item("placement", label, "warn", f"{summary} {advice}", **values)


def camera_checks(lower_image: Any, upper_image: Any, bounds: tuple[int, int, int, int] | None) -> list[dict[str, Any]]:
    """Calibration and alignment checks for the ball as it now rests. Never raises."""
    from stereo_check import _camera
    items: list[dict[str, Any]] = []
    if bounds is not None:
        items.append(placement_geometry(lower_image.shape, bounds))
    try:
        height, width = lower_image.shape[:2]
        matrix, distortion = load_setup((width, height))
        ground_id = int(os.getenv("PINPOINT_APRILTAG_ID", "0"))
        tag_size = float(os.getenv("PINPOINT_APRILTAG_SIZE_MM", "100")) / 1000
        pose = stored_ground_pose((width, height), ground_id, tag_size, matrix, distortion)
        if pose is None:
            raise ValueError("No saved ground calibration; capture the AprilTag with both cameras.")
        items.append(_item("ground", "Ground calibration", "ok",
                           f"Saved ground pose loaded (tag fit {pose['errorPx']:.2f} px)."))
        if upper_image is not None and bounds is not None:
            lower = _camera(matrix, distortion, pose["rotation"], pose["translation"])
            upper_size = upper_image.shape[1], upper_image.shape[0]
            upper_matrix, upper_distortion, upper_pose, _ = secondary_camera(
                (matrix, distortion, pose["rotation"], pose["translation"]), upper_size,
                ground_id, tag_size, pose.get("capturedAt"))
            upper = _camera(upper_matrix, upper_distortion, upper_pose["rotation"], upper_pose["translation"])
            items.append(stereo_rest_check(lower, upper, lower_image, upper_image, bounds))
    except (OSError, ValueError, KeyError, TypeError, np.linalg.LinAlgError) as error:
        items.append(_item("ground", "Ground calibration", "fail", str(error)))
    except Exception as error:  # cv2.error and friends: report, never break arming.
        items.append(_item("ground", "Ground calibration", "warn", f"Readiness check could not run: {error}"))
    return items


def club_profile_check(club_id: str, mode: str, club_name: str | None = None) -> dict[str, Any] | None:
    """Strike location needs the measured face size of the club in use.

    ``club_id`` is the active club key: a named bag club's id when one is selected.
    """
    if mode == "putting":
        return None
    from club_vision import load_club_profile
    profile = load_club_profile()
    label = "Strike location"
    if profile is None:
        return _item("club-profile", label, "warn",
                     f"No face measurement for {club_name or club_id}, so strike location will be unavailable. "
                     "Add the heel-toe width and face height to this club in the app.")
    if profile.get("clubId") and profile["clubId"] != club_id:
        return _item("club-profile", label, "warn",
                     f"The saved face measurement is for {profile.get('clubName') or profile['clubId']}, not "
                     f"{club_name or club_id}; strike location may be rejected. Add this club's face size in the app.")
    return _item("club-profile", label, "ok",
                 f"Face profile {profile['faceWidthMm']:.0f} × {profile['faceHeightMm']:.0f} mm.")


def expected_speeds(club_id: str, recent: list[dict[str, float]] | None) -> dict[str, Any]:
    """Median of the player's recent shots, else the club's typical full swing."""
    recent = [shot for shot in (recent or []) if shot.get("ballSpeedMps")]
    if recent:
        median = lambda key, fallback: float(sorted(s.get(key) or fallback for s in recent)[len(recent) // 2])
        ball = median("ballSpeedMps", 0.0)
        return {"ballSpeedMps": ball, "launchDeg": median("launchDeg", 25.0),
                "clubSpeedMps": median("clubSpeedMps", ball / 1.2),
                "basis": f"your last {len(recent)} {'shot' if len(recent) == 1 else 'shots'}"}
    from flight_model import CLUB_BALL_SPEED_MPS
    from pinpoint_protocol import CLUB_PROFILES
    club_speed, _, launch = CLUB_PROFILES.get(club_id, CLUB_PROFILES["7-iron"])
    return {"ballSpeedMps": CLUB_BALL_SPEED_MPS.get(club_id, 45.0), "launchDeg": launch,
            "clubSpeedMps": club_speed, "basis": "a typical full swing; hit a few shots for your own speeds"}


def readiness(camera_items: list[dict[str, Any]] | None, exposure_us: float | None,
              club_id: str, mode: str, bag_club: dict[str, Any] | None = None,
              recent_shots: list[dict[str, float]] | None = None) -> dict[str, Any]:
    """Combine the camera checks from the last arming with the current club and exposure.

    ``club_id`` is the club type (for speed); ``bag_club`` the named club, if any;
    ``recent_shots`` the player's latest measured speeds, for the placement check.
    """
    geometry = next((item for item in camera_items or [] if item["id"] == "placement-geometry"), None)
    items = [exposure_check(exposure_us, club_id, mode),
             *(item for item in camera_items or [] if item["id"] != "placement-geometry")]
    placement = placement_check(geometry, expected_speeds(club_id, recent_shots), mode)
    if placement is not None:
        items.append(placement)
    profile = club_profile_check(bag_club["id"] if bag_club else club_id, mode,
                                 bag_club["name"] if bag_club else None)
    if profile is not None:
        items.append(profile)
    return summarize(items)


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    status = "fail" if any(i["status"] == "fail" for i in items) else "warn" if any(i["status"] == "warn" for i in items) else "ok"
    return {"version": 1, "status": status, "items": items,
            "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
