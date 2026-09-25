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
    from stereo_check import (MAX_RAY_GAP_MM, MAX_REST_HEIGHT_ERROR_MM, MAX_REST_PREDICTION_PX,
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
    if abs(height_error_mm) > MAX_REST_HEIGHT_ERROR_MM:
        where = "above" if height_error_mm > 0 else "below"
        return _item("stereo-rest", label, "fail",
                     f"The ball sits {abs(height_error_mm):.0f} mm {where} the calibrated ground (limit "
                     f"{MAX_REST_HEIGHT_ERROR_MM:.0f} mm). If you hit off a mat or tee, recalibrate with the tag "
                     "lying on that surface; otherwise the stand has moved.", **values)
    if offset_px > MAX_REST_PREDICTION_PX:
        return _item("stereo-rest", label, "fail",
                     f"The top camera sees the ball {offset_px:.0f} px from where calibration puts it (limit "
                     f"{MAX_REST_PREDICTION_PX:.0f} px). Recalibrate both cameras with the AprilTag.", **values)
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


def camera_checks(lower_image: Any, upper_image: Any, bounds: tuple[int, int, int, int] | None) -> list[dict[str, Any]]:
    """Calibration and alignment checks for the ball as it now rests. Never raises."""
    from stereo_check import _camera
    items: list[dict[str, Any]] = []
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


def club_profile_check(club_id: str, mode: str) -> dict[str, Any] | None:
    """Strike location needs the measured face size of the club in use."""
    if mode == "putting":
        return None
    from club_vision import load_club_profile
    profile = load_club_profile()
    label = "Strike location"
    if profile is None:
        return _item("club-profile", label, "warn",
                     "No clubface measurement saved, so strike location will be unavailable. Measure the face "
                     "(heel-toe width and face height) and save it as the club profile.")
    if profile.get("clubId") and profile["clubId"] != club_id:
        return _item("club-profile", label, "warn",
                     f"The saved face measurement is for {profile['clubId']}, not {club_id}; strike location "
                     "may be rejected. Measure this club's face.")
    return _item("club-profile", label, "ok",
                 f"Face profile {profile['faceWidthMm']:.0f} × {profile['faceHeightMm']:.0f} mm.")


def readiness(camera_items: list[dict[str, Any]] | None, exposure_us: float | None,
              club_id: str, mode: str) -> dict[str, Any]:
    """Combine the camera checks from the last arming with the current club and exposure."""
    items = [exposure_check(exposure_us, club_id, mode), *(camera_items or [])]
    profile = club_profile_check(club_id, mode)
    if profile is not None:
        items.append(profile)
    return summarize(items)


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    status = "fail" if any(i["status"] == "fail" for i in items) else "warn" if any(i["status"] == "warn" for i in items) else "ok"
    return {"version": 1, "status": status, "items": items,
            "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
