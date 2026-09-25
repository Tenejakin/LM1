"""How many frames each kind of shot gets inside the calibrated camera view.

At about 240 fps a driver ball travels ~30 cm between frames, so launch values
depend far more on how much of the ball's early path the camera sees than on the
frame rate. This projects typical launches from the ball's resting place through
the saved lens + ground pose and counts the frames in which the whole ball is
inside the image. It is geometry only; lighting, blur and occlusion by the club
can still lose frames that this counts.
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from launch_measurements import RADIUS, ground_point, resolve_target_heading

# Representative amateur launches; the exact values matter less than the order of magnitude.
SHOT_PROFILES = (
    {"id": "putt", "label": "Putt", "ballSpeedMps": 3.0, "launchDeg": 0.0},
    {"id": "wedge", "label": "Wedge", "ballSpeedMps": 30.0, "launchDeg": 30.0},
    {"id": "iron", "label": "7-iron", "ballSpeedMps": 54.0, "launchDeg": 17.0},
    {"id": "driver", "label": "Driver", "ballSpeedMps": 70.0, "launchDeg": 12.0},
)
# The speed/launch fit needs three positions; a fourth gives it a residual to check.
MIN_FRAMES = 3
GOOD_FRAMES = 4
STEP_M = 0.004
MAX_PATH_M = 4.0
EDGE_MARGIN_PX = 2.0
DEFAULT_BALL_PIXEL = (0.5, 0.72)


def _visible_mask(points: np.ndarray, matrix: np.ndarray, distortion: np.ndarray,
                  rotation: np.ndarray, translation: np.ndarray, image_size: tuple[int, int]) -> np.ndarray:
    """True where the whole ball (centre +/- its apparent radius) lies inside the image."""
    camera = points @ rotation.T + translation
    depth = camera[:, 2]
    visible = depth > 0.05
    projected, _ = cv2.projectPoints(points.reshape(-1, 1, 3), cv2.Rodrigues(rotation)[0],
                                     translation.reshape(3, 1), matrix, distortion)
    x, y = projected.reshape(-1, 2).T
    radius = matrix[0, 0] * RADIUS / np.maximum(depth, 1e-6) + EDGE_MARGIN_PX
    width, height = image_size
    return visible & (x > radius) & (x < width - radius) & (y > radius) & (y < height - radius)


def _visible_length(start: np.ndarray, direction: np.ndarray, *args: Any) -> float:
    """Distance along ``direction`` until the ball first leaves the view."""
    steps = np.arange(0.0, MAX_PATH_M + STEP_M, STEP_M)
    mask = _visible_mask(start + steps[:, None] * direction, *args)
    if not mask[0]:
        return 0.0
    exits = np.flatnonzero(~mask)
    return float(steps[exits[0] - 1]) if len(exits) else MAX_PATH_M


def _launch_direction(heading: float, launch_deg: float) -> np.ndarray:
    elevation = math.radians(launch_deg)
    return np.array([math.cos(heading) * math.cos(elevation),
                     math.sin(heading) * math.cos(elevation),
                     math.sin(elevation)])


def _rating(minimum: int) -> str:
    if minimum >= GOOD_FRAMES:
        return "good"
    if minimum >= MIN_FRAMES:
        return "marginal"
    return "insufficient"


def shot_coverage(ground_pose: dict[str, Any], fps: float,
                  ball_pixel: tuple[float, float] | None = None) -> dict[str, Any]:
    """Frame budget per shot type for a saved ground pose.

    ``ball_pixel`` is the resting ball centre in normalised image coordinates;
    without one the preview's placement target is assumed and reported as such.
    """
    if not fps or fps <= 0:
        raise ValueError("The camera frame rate is unknown; wait for the live camera before checking coverage.")
    matrix = np.asarray(ground_pose["cameraMatrix"], float)
    distortion = np.asarray(ground_pose["distCoeffs"], float)
    rotation = np.asarray(ground_pose["rotation"], float)
    translation = np.asarray(ground_pose["translationM"], float)
    width, height = (int(value) for value in ground_pose["imageSize"])
    view = (matrix, distortion, rotation, translation, (width, height))

    source = "live-ball" if ball_pixel is not None else "assumed-placement"
    normalised = ball_pixel if ball_pixel is not None else DEFAULT_BALL_PIXEL
    rest = ground_point((normalised[0] * width, normalised[1] * height), matrix, distortion, rotation, translation)
    if rest is None or not _visible_mask(rest.reshape(1, 3), *view)[0]:
        raise ValueError("The resting ball position is not fully inside the calibrated view.")

    heading, heading_source = resolve_target_heading(rotation)
    if heading is None:
        raise ValueError("No camera-axis target direction: level the monitor and recalibrate the ground plane.")

    downrange = _visible_length(rest, _launch_direction(heading, 0.0), *view)
    behind = _visible_length(rest, -_launch_direction(heading, 0.0), *view)
    depth = float((rotation @ rest + translation)[2])
    frame_s = 1.0 / fps

    shots = []
    for profile in SHOT_PROFILES:
        path = _visible_length(rest, _launch_direction(heading, profile["launchDeg"]), *view)
        travel = profile["ballSpeedMps"] * frame_s
        # Contact falls at an unknown point inside a frame interval, so the count of
        # in-view exposures after it is floor(path / travel) or one more.
        minimum = int(path // travel)
        shots.append({
            **profile,
            "travelPerFrameMm": round(travel * 1000, 1),
            "visiblePathMm": round(path * 1000),
            "framesMin": minimum,
            "framesMax": minimum + 1,
            "pathNeededMm": round(travel * MIN_FRAMES * 1000),
            "rating": _rating(minimum),
        })

    notes = []
    if behind > 0.25 * (behind + downrange):
        notes.append(
            f"{round(behind * 100)} cm of the view is behind the ball. Placing the ball nearer the "
            f"upstream edge of the image adds that to the downrange path."
        )
    driver = next(shot for shot in shots if shot["id"] == "driver")
    if driver["rating"] == "insufficient":
        scale = driver["pathNeededMm"] / max(driver["visiblePathMm"], 1)
        notes.append(
            f"Full swings need about {driver['pathNeededMm'] / 10:.0f} cm of visible path; this view has "
            f"{driver['visiblePathMm'] / 10:.0f} cm. Moving the camera about {scale:.1f}x further from the "
            f"ball widens the view that much, at the cost of a smaller ball in the image."
        )
    if source == "assumed-placement":
        notes.append("No ball was detected, so the preview's placement point was assumed. "
                     "Place a ball and check again for its real position.")

    return {
        "version": 1,
        "fps": round(fps, 1),
        "frameIntervalMs": round(frame_s * 1000, 2),
        "ballSource": source,
        "ballPixel": [round(normalised[0], 4), round(normalised[1], 4)],
        "ballDiameterPx": round(float(2 * matrix[0, 0] * RADIUS / depth), 1),
        "cameraToBallMm": round(depth * 1000),
        "headingSource": heading_source,
        "downrangePathMm": round(downrange * 1000),
        "behindBallMm": round(behind * 1000),
        "minimumFrames": MIN_FRAMES,
        "shots": shots,
        "notes": notes,
        "camera": "primary",
    }
