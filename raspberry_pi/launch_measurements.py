"""AprilTag-referenced monocular launch estimates. All distances internally in metres.

World +X follows the tag's top edge (target), +Y points left, +Z up.
Single-view sphere depth is sensitive to silhouette errors, so a value is only labelled
measured when it passes every gate in grade_metrics; everything else is an estimate.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import cv2
import numpy as np

import club_vision
from capture_quality import shot_evidence
from apriltag_calibration import tag_detector_parameters
from rig_pose import ground_mode, level_rig_pose

RADIUS = 0.021335
STRICT_TAG_POSE_ERROR_PX = 1.0
# Longest ball smear accepted during one exposure; shared with the pre-shot readiness check.
MAX_MOTION_BLUR_M = 0.004
MAX_ESTIMATED_TAG_POSE_ERROR_PX = 3.0
# The level-rig camera height is a constant of the stand; the resting ball may correct it by this much.
RIG_MAX_SURFACE_OFFSET_MM = 40.0
# A single-camera fit slower than this is not a ball in flight: the tracker has locked onto something
# static (a shadow, the club shaft, a foot) after the ball left. It must not steer the two-camera search.
MIN_PLAUSIBLE_MONO_SPEED_MPS = 0.3
# Ground-pose sources that take the upper camera from the stereo pair and the height from the resting ball.
BALL_GROUNDED_SOURCES = ("stored-calibration", "level-rig")
MAX_GROUND_TAG_DETECTIONS = 12
# Below this the camera's across-image axis is too close to vertical to project onto the ground.
MIN_CAMERA_HEADING_HORIZONTAL = 0.1
STRICT_BALL_FILL = 0.82
GUIDED_BALL_FILL = 0.50
GUIDED_MIN_SEQUENCE = 3
GUIDED_RADIUS_RATIO = 1.12
# Single-view depth of a rolling ball wanders tens of mm with a few percent of
# silhouette error; a real launch rises steadily past these within the fit window.
GROUND_HEIGHT_TOLERANCE_M = 0.020
GROUND_RISE_TOLERANCE_M = 0.015
GROUND_TRACK_FRAMES = 12
# Anchored trajectory fit: the resting ball fixes the start point, sub-pixel image
# centres fix motion across the view, and apparent size weakly constrains the
# line-of-sight component that single-view depth otherwise gets wrong.
GRAVITY = 9.80665
# Three frames are the minimum for any fitted motion; every further frame joins the
# least-squares fit and averages its noise down.
TRAJECTORY_MIN_FRAMES = 3
TRAJECTORY_MAX_FRAMES = 48
TRAJECTORY_CENTER_SIGMA_PX = 0.5
TRAJECTORY_RADIUS_SIGMA_PX = 1.5
TRAJECTORY_MAX_RMS_PX = 3.0
TRAJECTORY_HUBER = 2.0
TRAJECTORY_MAX_ROLL_DECELERATION = 10.0
# Coarse launch grid for seeding the flight fit; the best few are refined.
FLIGHT_SEED_LAUNCH_DEG = (0.0, 10.0, 20.0, 30.0, 45.0, 60.0, 75.0)
FLIGHT_SEED_SPEED_MPS = (2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
FLIGHT_SEED_STARTS = 3
# Sub-pixel ball outline: radial brightness profiles around the tracked centre, each
# edge placed at its half-contrast crossing, then a robust circle fit.
EDGE_RAYS = 72
EDGE_STEP_PX = 0.25
EDGE_MIN_RAYS = 24
EDGE_MIN_CONTRAST = 12.0
EDGE_MAX_RMS_PX = 0.8
EDGE_MIN_RADIUS_PX = 4.0
EDGE_LIT_FRACTION = 0.5
EDGE_RANSAC_ITERATIONS = 200
EDGE_INLIER_PX = 0.6
EDGE_MIN_ARC_DEG = 150
# Measured frame-to-frame jitter of edge-fitted radii on real captures is 0.65-0.9 px.
TRAJECTORY_EDGE_RADIUS_SIGMA_PX = 1.0
BALL_SIZE_MIN_FRAMES = 3
# The free-start roll has five parameters: on a short track it fits any three points
# exactly, so it needs the frames the resting-ball anchor otherwise supplies.
FREE_START_MIN_FRAMES = 6
# A struck ball flattens on the face and rings for about a millisecond after leaving
# it. Its outline is only a 42.67 mm sphere again after that, so apparent size from
# the first moving frame and any within this long after it is not used.
BALL_RECOVERY_S = 0.003
METRICS = {
    "ballSpeedMps": "m/s", "clubSpeedMps": "m/s", "smashFactor": "",
    "launchAngleDeg": "deg", "startDirectionDeg": "deg", "strikeXmm": "mm",
    "strikeYmm": "mm", "spinRpm": "rpm", "spinAxisDeg": "deg",
    "estimatedCarryM": "m", "rollDistanceM": "m", "skidDistanceM": "m",
    "clubPathDeg": "deg", "attackAngleDeg": "deg",
}


# A value is labelled "measured" only when it was observed directly and every quality
# gate below passed. Anything else stays "estimated" and carries a confidence that
# drops with each failed gate, so a clean shot and a marginal one no longer look alike.
# Measured still means "passed this device's own checks", not "validated against a
# reference launch monitor".
MEASURED_TAG_POSE_ERROR_PX = STRICT_TAG_POSE_ERROR_PX
MEASURED_FIT_RMS_PX = 1.0
MEASURED_SPEED_SIGMA_RATIO = 0.03
MEASURED_ANGLE_SIGMA_DEG = 1.5
MEASURED_SPIN_SAMPLES = 4
MEASURED_CLUB_TAG_POSES = 5
MEASURED_BALL_SIZE_ERROR_PCT = 5.0
STEREO_MAX_CALIBRATION_SKEW_S = 5.0
MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.05


def unavailable(reason):
    return {key: {"value": None, "unit": unit, "status": "unavailable", "reason": reason} for key, unit in METRICS.items()}


def _limit_check(label, value, limit, unit, higher_is_better=False):
    """A numeric gate; a miss costs more the further the value is past its limit."""
    passed = value >= limit if higher_is_better else value <= limit
    ratio = (value / limit if higher_is_better else limit / value) if value > 0 else 0.0
    comparison = "≥" if higher_is_better else "≤"
    shown = f"{value:g}" if isinstance(value, int) else f"{value:.2f}"
    return {"label": f"{label} {shown}{unit} (needs {comparison} {limit:g}{unit})", "passed": passed,
            "penalty": 1.0 if passed else max(0.3, math.sqrt(max(0.0, ratio)))}


def _flag_check(label, passed, penalty):
    return {"label": label, "passed": bool(passed), "penalty": 1.0 if passed else penalty}


def _ground_check(context):
    """The ground reference gate: the tag fit, or for the level rig whether the resting ball confirmed the height."""
    if context.get("groundSource") == "level-rig":
        return _flag_check("Level rig: camera height confirmed by the resting ball (tilt is assumed level)",
                           context.get("rigHeightFromBall"), 0.8)
    return _limit_check("Ground tag pose error", context["poseErrorPx"], MEASURED_TAG_POSE_ERROR_PX, " px")


def _ball_checks(context):
    checks = [_ground_check(context)]
    if context.get("stereoFailure"):
        checks.append(_flag_check(f"Two-camera validation failed: {context['stereoFailure']}", False, 0.65))
    if context.get("blurExceeded"):
        checks.append(_flag_check("Motion blur stayed under 4 mm", False, 0.75))
    fit = context.get("ballFit")
    if fit is None:
        checks.append(_flag_check("Anchored trajectory fit (fell back to per-frame outline depth)", False, 0.75))
        if context.get("guided"):
            checks.append(_flag_check("Full ball outline (used a partial, tracker-guided outline)", False, 0.6))
    else:
        fit_label = (f"Two-camera trajectory fit over {fit['frames']} paired frames"
                     if fit.get("source") == "stereo" else f"Anchored trajectory fit over {fit['frames']} frames")
        checks.append(_flag_check(fit_label, True, 1.0))
        checks.append(_limit_check("Image residual", fit["rmsPx"], MEASURED_FIT_RMS_PX, " px"))
        stereo = context.get("stereo")
        if stereo is not None:
            from stereo_check import MEASURED_STEREO_FRAMES
            # A staggered pair samples two instants, one per camera, so it counts twice toward the minimum.
            checks.append(_limit_check("Stereo sample instants" if stereo.get("staggered") else "Paired stereo frames",
                                       stereo.get("instants", stereo["frames"]), MEASURED_STEREO_FRAMES, "",
                                       higher_is_better=True))
            # Triangulated depth vouches for the distance independently, so the apparent
            # ball size (whose outline is the least reliable measurement) is not needed.
            from stereo_check import (MAX_PAIR_OFFSET_US, MAX_RAY_GAP_MM, MAX_REST_HEIGHT_ERROR_MM,
                                      MAX_START_ANCHOR_ERROR_MM, MAX_STEREO_RMS_PX)
            checks.append(_limit_check("Stereo rays meet within", max(0.01, stereo["medianRayGapMm"]), MAX_RAY_GAP_MM, " mm"))
            checks.append(_limit_check("Stereo resting ball off the tag plane by",
                                       max(0.01, abs(stereo["restHeightErrorMm"])), MAX_REST_HEIGHT_ERROR_MM, " mm"))
            checks.append(_limit_check("Stereo start point differs from resting ball by",
                                       max(0.01, stereo["startAnchorErrorMm"]), MAX_START_ANCHOR_ERROR_MM, " mm"))
            checks.append(_limit_check("Paired-camera timestamp offset", stereo["maxPairOffsetUs"],
                                       MAX_PAIR_OFFSET_US, " µs"))
            checks.append(_limit_check("Stereo reprojection residual", stereo["rmsPx"], MAX_STEREO_RMS_PX, " px"))
            # The lower pose was already checked once above.
            if stereo.get("upperPoseErrorPx") is not None:
                checks.append(_limit_check("Upper tag pose error", stereo["upperPoseErrorPx"],
                                           MEASURED_TAG_POSE_ERROR_PX, " px"))
        elif fit.get("ballSizeRatio") is not None:
            checks.append(_limit_check("Ball size vs calibration (standard 42.67 mm ball) off by",
                                       max(0.01, abs(fit["ballSizeRatio"] - 1) * 100), MEASURED_BALL_SIZE_ERROR_PCT, "%"))
    return checks


def _club_checks(context, result):
    stereo = result.get("diagnostics", {}).get("clubStereo") or {}
    if stereo.get("used"):
        import club_stereo
        return [
            _flag_check("Club depth triangulated by both cameras", True, 1.0),
            _limit_check("Club frames", stereo["acceptedFrames"], club_stereo.MEASURED_FRAMES, "",
                         higher_is_better=True),
            _limit_check("Club median ray gap", stereo["medianRayGapMm"], club_stereo.MEASURED_RAY_GAP_MM, " mm"),
            _limit_check("Club path residual", stereo["fitResidualMm"], club_stereo.MEASURED_RESIDUAL_MM, " mm"),
        ]
    silhouette = result.get("diagnostics", {}).get("clubSilhouette")
    if silhouette is not None:
        return [
            _flag_check("Club depth from a club tag (assumed the ball's swing plane)", False, 0.7),
            _limit_check("Clubhead frames", silhouette.get("acceptedFrames", 0), club_vision.MEASURED_TRACK_FRAMES, "",
                         higher_is_better=True),
        ]
    return [
        _ground_check(context),
        _limit_check("Club tag poses", len(result.get("clubTrack3d", [])), MEASURED_CLUB_TAG_POSES, "",
                     higher_is_better=True),
    ]


def _grade(metric, checks):
    confidence = MAX_CONFIDENCE
    for check in checks:
        confidence *= check["penalty"]
    metric["status"] = "measured" if all(check["passed"] for check in checks) else "estimated"
    metric["confidence"] = round(min(MAX_CONFIDENCE, max(MIN_CONFIDENCE, confidence)), 2)
    metric["checks"] = [{"label": check["label"], "passed": check["passed"]} for check in checks]


def grade_metrics(result, context):
    """Label every reported value measured or estimated and explain which gates decided it."""
    metrics = result["metrics"]
    if context.get("poseErrorPx") is None:
        return
    ball = _ball_checks(context)
    fit = context.get("ballFit") or {}
    ball_speed = metrics["ballSpeedMps"]["value"]
    stereo = context.get("stereo") if fit else None
    if stereo is not None and fit.get("source") != "stereo":
        from stereo_check import MAX_ANGLE_DIFFERENCE_DEG, MAX_SPEED_DIFFERENCE_PCT
        agree = {}
        if stereo.get("speedDifferencePct") is not None:
            agree["ballSpeedMps"] = [_limit_check("Stereo speed differs by", max(0.01, stereo["speedDifferencePct"]),
                                                   MAX_SPEED_DIFFERENCE_PCT, "%")]
        if stereo.get("launchDifferenceDeg") is not None:
            agree["launchAngleDeg"] = [_limit_check("Stereo launch differs by", max(0.01, stereo["launchDifferenceDeg"]),
                                                     MAX_ANGLE_DIFFERENCE_DEG, "°")]
        if stereo.get("headingDifferenceDeg") is not None:
            agree["startDirectionDeg"] = [_limit_check("Stereo direction differs by", max(0.01, stereo["headingDifferenceDeg"]),
                                                        MAX_ANGLE_DIFFERENCE_DEG, "°")]
    else:
        agree = {}
    for key, extra in (
        ("ballSpeedMps", ([_limit_check("Speed fit uncertainty", 100 * fit["speedSigmaMps"] / max(ball_speed or 1, 0.1),
                                        100 * MEASURED_SPEED_SIGMA_RATIO, "%")] if fit else []) + agree.get("ballSpeedMps", [])),
        ("launchAngleDeg", ([_limit_check("Launch fit uncertainty", fit.get("launchSigmaDeg") or fit["flightLaunchSigmaDeg"],
                                          MEASURED_ANGLE_SIGMA_DEG, "°")] if fit else []) + agree.get("launchAngleDeg", [])),
        ("startDirectionDeg", ([_limit_check("Direction fit uncertainty", fit["headingSigmaDeg"], MEASURED_ANGLE_SIGMA_DEG, "°")]
                               if fit else []) + agree.get("startDirectionDeg", []) + [
            _flag_check("Direction reference available (camera-axis zero assumes the monitor is aligned to target)",
                        context.get("targetLineSource") in ("camera-axis", "rolled-ball"), 0.85)]),
    ):
        if metrics[key]["value"] is not None:
            _grade(metrics[key], ball + extra)
    if metrics["estimatedCarryM"]["value"] is not None:
        _grade(metrics["estimatedCarryM"], ball + [
            _flag_check("Modeled landing in still air; not observed", False, 0.7)])
    samples = len(result.get("spinSamples", []))
    for key in ("spinRpm", "spinAxisDeg"):
        if metrics[key]["value"] is not None:
            _grade(metrics[key], ball + [
                _limit_check("Surface-rotation samples", samples, MEASURED_SPIN_SAMPLES, "", higher_is_better=True)])
    for key in ("rollDistanceM", "skidDistanceM"):
        if metrics[key]["value"] is not None:
            _grade(metrics[key], ball + [_flag_check("Observed directly (distance from single-view depth track)", False, 0.8)])
    club = _club_checks(context, result)
    for key in ("clubSpeedMps", "attackAngleDeg", "clubPathDeg"):
        if metrics[key]["value"] is not None:
            _grade(metrics[key], club)
    for key in ("strikeXmm", "strikeYmm"):
        if metrics[key]["value"] is not None:
            _grade(metrics[key], club + [
                _flag_check("Contact seen directly (projected to the moment of impact)", False, 0.8)])
    smash = metrics["smashFactor"]
    if smash["value"] is not None:
        parts = [metrics["ballSpeedMps"], metrics["clubSpeedMps"]]
        smash["status"] = "measured" if all(part.get("status") == "measured" for part in parts) else "estimated"
        smash["confidence"] = min(part.get("confidence", MIN_CONFIDENCE) for part in parts)
        smash["checks"] = [{"label": f"{name} measured", "passed": part.get("status") == "measured"}
                           for name, part in zip(("Ball speed", "Club speed"), parts)]


def load_setup(image_size, camera="primary"):
    if camera == "secondary":
        path = Path(os.getenv("PINPOINT_SECONDARY_INTRINSICS_PATH", "/var/lib/pinpoint/intrinsics-secondary.json"))
    else:
        path = Path(os.getenv("PINPOINT_INTRINSICS_PATH", "/var/lib/pinpoint/intrinsics.json"))
    data = json.loads(path.read_text())
    matrix = np.asarray(data["cameraMatrix"], dtype=float)
    distortion = np.asarray(data["distCoeffs"], dtype=float)
    if list(image_size) != data["imageSize"]:
        raise ValueError("Lens calibration resolution differs from capture; recalibrate this sensor mode.")
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)) or min(matrix[0, 0], matrix[1, 1]) <= 0:
        raise ValueError("Invalid lens calibration matrix.")
    if not np.all(np.isfinite(distortion)) or not math.isfinite(data["rmsPx"]) or data["rmsPx"] > 0.7:
        raise ValueError("Lens calibration reprojection error exceeds 0.7 pixels.")
    return matrix, distortion


def solve_tag_pose(corners, size, matrix, distortion):
    """Solve a tag pose and return its reprojection error without applying a quality policy."""
    # +Y left and +Z above the printed side of the ground tag.
    points = np.array([[0, 0, 0], [size, 0, 0], [size, -size, 0], [0, -size, 0]], np.float64)
    corners = np.asarray(corners, np.float64)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError("AprilTag corners are invalid.")
    ok, rotation, translation = cv2.solvePnP(points, corners, matrix, distortion, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or translation[2, 0] <= 0:
        raise ValueError("AprilTag pose could not be solved.")
    projected, _ = cv2.projectPoints(points, rotation, translation, matrix, distortion)
    error = float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - corners) ** 2, axis=1))))
    if not math.isfinite(error):
        raise ValueError("AprilTag pose reprojection error is invalid.")
    return cv2.Rodrigues(rotation)[0], translation.reshape(3), error


def ground_pose_calibration(detection, camera="primary"):
    """Save pose and exact lens inputs from an explicitly captured ground tag."""
    image_size = detection.get("imageSize")
    if not isinstance(image_size, list) or len(image_size) != 2:
        raise ValueError("Ground-tag image size missing; capture a fresh calibration.")
    matrix, distortion = load_setup(image_size, camera)
    corners = np.asarray(detection.get("corners"), dtype=float)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError("Ground-tag corners missing; capture a fresh calibration.")
    size = float(detection["tagSizeMm"]) / 1000
    rotation, translation, error = solve_tag_pose(corners * np.asarray(image_size), size, matrix, distortion)
    if error > MAX_ESTIMATED_TAG_POSE_ERROR_PX:
        raise ValueError("Ground-tag pose error exceeds 3 pixels; improve calibration image.")
    camera_position, optical_axis = -rotation.T @ translation, rotation[2]
    return {"version": 1, "imageSize": image_size, "cameraMatrix": matrix.tolist(),
            "distCoeffs": distortion.tolist(), "rotation": rotation.tolist(),
            "translationM": translation.tolist(), "errorPx": error,
            "cameraHeightMm": round(float(camera_position[2]) * 1000, 1),
            "cameraPitchDeg": round(math.degrees(math.asin(float(np.clip(-optical_axis[2], -1, 1)))), 2)}


def ground_tag_thickness_m():
    """Height of the tag's printed face above the hitting surface (e.g. a 4 mm mounting plate)."""
    try:
        value = float(os.getenv("PINPOINT_GROUND_TAG_THICKNESS_MM", "0"))
    except ValueError:
        return 0.0
    return value / 1000 if math.isfinite(value) and 0 <= value <= 50 else 0.0


def ground_surface_pose(pose):
    """Move the world origin from the tag's face down onto the surface the ball rests on.

    Every ball model puts the resting centre one radius above z = 0. A tag on a 4 mm plate
    lifts z = 0 by 4 mm, so a ball on the mat reads 4 mm low and fails the 5 mm stereo
    resting-height gate. Shifting both cameras' world frames the same way leaves their
    relative geometry, and so every triangulation, unchanged.
    """
    thickness = ground_tag_thickness_m()
    if pose is None or not thickness:
        return pose
    rotation = np.asarray(pose["rotation"], float)
    # A surface point at z = 0 is at z = -thickness in the tag frame: x_cam = R (p - t e_z) + T.
    translation = np.asarray(pose["translation"], float) - thickness * rotation[:, 2]
    return {**pose, "translation": translation, "groundTagThicknessMm": round(thickness * 1000, 2)}


def shift_surface(rotation, translation, offset_m):
    """Camera translation after raising the world origin by ``offset_m`` (surface higher than calibrated)."""
    return np.asarray(translation, float) + offset_m * np.asarray(rotation, float)[:, 2]


# The resting ball is a 42.67 mm reference: its triangulated centre says where the surface
# under it actually is. Offsets up to this size are taken from the ball for the shot;
# larger ones mean the two views matched different things.
MAX_SURFACE_OFFSET_MM = 25.0
SURFACE_MAX_RAY_GAP_MM = 6.0


def resting_ball_surface(frames, secondary_frames, bounds, impact_index, lower_camera, upper_camera,
                         max_offset_mm=MAX_SURFACE_OFFSET_MM):
    """Height (m) of the surface under the resting ball relative to the calibrated ground, or None.

    Several still frames are tried (the club can hide the ball near impact) and the one
    whose two camera rays meet most closely is used.
    """
    import readiness
    from stereo_check import _camera
    lower, upper = _camera(*lower_camera), _camera(*upper_camera)
    best = None
    for index in sorted({0, max(0, impact_index - 30), max(0, impact_index - 15)}):
        try:
            check = readiness.stereo_rest_check(lower, upper, frames[index][1], secondary_frames[index][1],
                                                tuple(int(v) for v in bounds))
        except (ValueError, IndexError, cv2.error, np.linalg.LinAlgError):
            continue
        if check.get("heightErrorMm") is None or check["rayGapMm"] > SURFACE_MAX_RAY_GAP_MM:
            continue
        if best is None or check["rayGapMm"] < best["rayGapMm"]:
            best = {**check, "frameIndex": index}
    if best is None or abs(best["heightErrorMm"]) > max_offset_mm:
        return None, best
    return best["heightErrorMm"] / 1000, best


def stored_ground_pose(image_size, ground_id, size, matrix, distortion, camera="primary"):
    from apriltag_calibration import load_apriltag_calibration
    saved = load_apriltag_calibration(camera)
    if not saved or not saved.get("groundPose"):
        return None
    data = saved["groundPose"]
    try:
        if (saved["tagId"] != ground_id or not math.isclose(float(saved["tagSizeMm"]), size * 1000)
                or data["imageSize"] != list(image_size)
                or not np.array_equal(np.asarray(data["cameraMatrix"]), matrix)
                or not np.array_equal(np.asarray(data["distCoeffs"]), distortion)):
            raise ValueError("Stored ground calibration differs from current lens/tag setup; recalibrate with the tag visible.")
        rotation = np.asarray(data["rotation"], float)
        translation = np.asarray(data["translationM"], float)
        error = float(data["errorPx"])
        if (rotation.shape != (3,3) or translation.shape != (3,)
                or not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(translation))
                or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5)
                or not math.isclose(np.linalg.det(rotation), 1., abs_tol=1e-5)
                or not math.isfinite(error) or not 0 <= error <= MAX_ESTIMATED_TAG_POSE_ERROR_PX):
            raise ValueError("Stored ground pose invalid; recalibrate with the tag visible.")
        return ground_surface_pose({"rotation": rotation, "translation": translation, "errorPx": error,
                                    "frameIndex": None, "source": "stored-calibration",
                                    "capturedAt": saved.get("capturedAt")})
    except (KeyError, TypeError) as exc:
        raise ValueError("Stored ground calibration is incomplete; recalibrate with the tag visible.") from exc


def tag_pose(corners, size, matrix, distortion):
    """Strict pose used by moving club tags, whose per-frame position cannot be substituted."""
    rotation, translation, error = solve_tag_pose(corners, size, matrix, distortion)
    if error > STRICT_TAG_POSE_ERROR_PX:
        raise ValueError("AprilTag pose reprojection error exceeds one pixel.")
    return rotation, translation


def sphere_center(contour, matrix, distortion, radius=RADIUS):
    """Fit the tangent-ray cone of a known-radius sphere, including off-axis views."""
    points = np.asarray(contour, np.float64).reshape(-1, 2)
    if len(points) >= 8:
        # A ball's seam line, logo or shadowed edge dents the thresholded silhouette;
        # on real strikes those dents failed the distortion gate below on nearly every
        # frame. The sphere's outline is convex, so fit its convex hull points.
        hull = cv2.convexHull(points.astype(np.float32), returnPoints=False).reshape(-1)
        if len(hull) >= 5:
            points = points[np.sort(hull)]
    rays = cv2.undistortPoints(points.reshape(-1, 1, 2), matrix, distortion).reshape(-1, 2)
    rays = np.column_stack((rays, np.ones(len(rays))))
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    _, _, vh = np.linalg.svd(rays - rays.mean(axis=0), full_matrices=False)
    axis = vh[-1]
    if axis[2] < 0:
        axis = -axis
    cosine = float(np.mean(rays @ axis))
    sine = math.sqrt(max(0, 1 - cosine * cosine))
    if sine < 0.002 or np.std(rays @ axis) > max(0.00002, (1 - cosine) * 0.2):
        raise ValueError("Ball silhouette is too small or distorted for depth estimation.")
    return axis * radius / sine


def fit_velocity(times, positions):
    times, positions = np.asarray(times), np.asarray(positions)
    if len(times) < 3 or np.any(np.diff(times) <= 0):
        raise ValueError("At least three increasing sensor timestamps are required.")
    design = np.column_stack((times - times[0], np.ones(len(times))))
    model = np.linalg.lstsq(design, positions, rcond=None)[0]
    residual = float(np.sqrt(np.mean(np.sum((design @ model - positions) ** 2, axis=1))))
    if residual > 0.008:
        raise ValueError("3D track fit error exceeds 8 mm.")
    return model[0], residual


def marker_map(frame):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    parameters = tag_detector_parameters()
    if hasattr(cv2.aruco, "ArucoDetector"):
        corners, ids, _ = cv2.aruco.ArucoDetector(dictionary, parameters).detectMarkers(frame)
    else:
        corners, ids, _ = cv2.aruco.detectMarkers(frame, dictionary, parameters=parameters)
    return {} if ids is None else {int(tag): points.reshape(4, 2) for tag, points in zip(ids.flatten(), corners)}


def camera_target_heading_rad(rotation):
    """Target heading taken from the camera's own left-to-right axis, projected onto the ground.

    When the monitor is squared to the target, the ball's line is whatever runs across
    the image, so the camera defines the reference and no rolled-ball calibration is
    needed. This is independent of how the ground tag happens to be rotated, which is
    the whole reason the rolled-ball line existed. Degenerate only if the camera is
    rolled towards portrait, where image-right stops having a ground direction.
    """
    right = rotation.T @ np.array([1.0, 0.0, 0.0])
    if math.hypot(right[0], right[1]) < MIN_CAMERA_HEADING_HORIZONTAL:
        raise ValueError("The camera is rolled too close to portrait for its across-image axis to "
                         "define a target line. Level the monitor and recalibrate the ground plane.")
    return math.atan2(right[1], right[0])


def target_line_note(heading, source, pose_source=None):
    """State which reference the angle is measured against; the two are not interchangeable."""
    if pose_source == "level-rig":
        return ("Measured against the camera's across-image axis, taken as the direction of the target: "
                "the monitor is assumed to be squared to the target and level.")
    if source == "camera-axis":
        return (f"Measured against the camera's across-image axis ({math.degrees(heading):.1f}° from the tag), "
                f"which assumes the monitor is squared to the target.")
    return f"Measured against the saved rolled-ball target line ({math.degrees(heading):.1f}° from the tag)."


def resolve_target_heading(rotation):
    """Always use bottom-camera image-right projected onto the ground plane.

    Legacy saved roll headings are deliberately ignored: rotating the ground tag
    must not change the physical zero direction of this left-to-right rig.
    """
    try:
        return camera_target_heading_rad(rotation), "camera-axis"
    except ValueError:
        return None, "unavailable"


def target_rotation(heading):
    """Rotation about +Z taking the calibrated target heading onto +X (identity when unset)."""
    if heading is None:
        return np.eye(3)
    c, s = math.cos(-heading), math.sin(-heading)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def find_ground_tag_pose(frames, impact_index, ground_id, size, matrix, distortion):
    """Return the best static ground-tag pose from a bounded set of burst detections.

    The tag is static, so later or earlier frames can replace an imperfect detection near
    impact. Limiting valid detections bounds processing time while still comparing across
    lamp-flicker phases and temporary club/hand occlusion.
    """
    start = max(0, min(impact_index - 8, len(frames) - 1))
    order = [start]
    for step in range(5, len(frames), 5):
        for index in (start - step, start + step):
            if 0 <= index < len(frames):
                order.append(index)
    candidates = []
    for index in order:
        tags = marker_map(frames[index][1])
        if ground_id not in tags:
            continue
        try:
            rotation, translation, error = solve_tag_pose(tags[ground_id], size, matrix, distortion)
        except (ValueError, cv2.error, np.linalg.LinAlgError):
            continue
        candidates.append({"rotation": rotation, "translation": translation, "errorPx": error, "frameIndex": index})
        if len(candidates) >= MAX_GROUND_TAG_DETECTIONS:
            break
    return ground_surface_pose(min(candidates, key=lambda candidate: candidate["errorPx"])) if candidates else None


def to_gray(frame):
    return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def ball_background(frames, impact_index):
    """Median of the pre-departure frames: the resting ball cancels, so only what moves stands out.

    A global brightness threshold cannot separate a white ball from a white tag sheet or a
    lit mat; differencing against the scene itself can.
    """
    stop = min(len(frames), max(3, impact_index - 8))
    stride = max(1, stop // 60)
    stack = np.stack([to_gray(frames[i][1]) for i in range(0, stop, stride)])
    return np.median(stack, axis=0).astype(np.uint8)


def ball_contours(frame, background, seed_radius, minimum_fill=STRICT_BALL_FILL):
    # A ball's dark seam line cuts the white silhouette into two half-discs (or a
    # slit), each failing the fill test below; the closing kernel bridges gaps that narrow.
    mask = club_vision.motion_mask(frame, background, close=5)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    found = []
    for contour in contours:
        if len(contour) < 12:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        area = cv2.contourArea(contour)
        if not max(5, seed_radius * 0.45) <= radius <= seed_radius * 1.8 or area / (math.pi * radius ** 2) < minimum_fill:
            continue
        if min(x - radius, y - radius) < 2 or x + radius >= mask.shape[1] - 2 or y + radius >= mask.shape[0] - 2:
            continue
        found.append((np.array([x, y]), contour))
    return found


def ball_difference(frame, background):
    """Signed brightness change against the empty scene, flicker-corrected like motion_mask.

    Kept in floating point: the binary motion mask snaps the outline to whole pixels
    and its morphology shifts it, which is what the sub-pixel edge fit avoids.
    """
    gray = to_gray(frame).astype(np.float32)
    gain = float(background.mean()) / max(float(gray.mean()), 1.0)
    return gray * gain - background.astype(np.float32)


def _fit_circle(points):
    x, y = points[:, 0], points[:, 1]
    design = np.column_stack((x, y, np.ones(len(x))))
    solution = np.linalg.lstsq(design, x * x + y * y, rcond=None)[0]
    center = solution[:2] / 2
    radius = math.sqrt(max(0.0, solution[2] + center @ center))
    return center, radius


def _circular_arc(points):
    """Inliers of the largest genuinely circular part of an outline, or None.

    Real captures are not clean discs: a shadow line can cut the ball off flat and a
    side-lit ball's dark limb fades out. Averaging those into a circle biases the
    radius, and they can be the majority, so a median-based trim cannot remove them.
    RANSAC finds the circle most edge points agree on; the arc it keeps must still
    span enough of the ball to fix its size.
    """
    generator = np.random.default_rng(0)  # Replays of a capture must match exactly.
    best = None
    for _ in range(EDGE_RANSAC_ITERATIONS):
        sample = points[generator.choice(len(points), 3, replace=False)]
        try:
            center, radius = _fit_circle(sample)
        except np.linalg.LinAlgError:
            continue
        if not math.isfinite(radius) or radius < EDGE_MIN_RADIUS_PX:
            continue
        inliers = np.abs(np.linalg.norm(points - center, axis=1) - radius) <= EDGE_INLIER_PX
        if best is None or inliers.sum() > best.sum():
            best = inliers
    if best is None:
        return None
    for _ in range(2):  # Refit on the consensus set, then re-select against the refit.
        if best.sum() < EDGE_MIN_RAYS:
            return None
        center, radius = _fit_circle(points[best])
        best = np.abs(np.linalg.norm(points - center, axis=1) - radius) <= EDGE_INLIER_PX
    if best.sum() < EDGE_MIN_RAYS:
        return None
    angles = np.sort(np.arctan2(*(points[best] - center).T[::-1]))
    largest_gap = max(np.max(np.diff(angles), initial=0.0), angles[0] + 2 * math.pi - angles[-1])
    if 2 * math.pi - largest_gap < math.radians(EDGE_MIN_ARC_DEG):
        return None
    return best


def _coarse_edge_radius(difference, center, guess, angles):
    """Rough apparent radius, so the fine search windows sit on this frame's edge.

    The ball's image grows and shrinks several-fold as it moves toward or away from
    the camera, so the resting size is only an upper bound on where to look. Each ray
    takes the outermost point still above half its brightest near-centre value.
    """
    steps = np.arange(0.0, 2.0 * guess, 0.5)
    xs = center[0] + np.outer(np.cos(angles), steps)
    ys = center[1] + np.outer(np.sin(angles), steps)
    profiles = cv2.remap(difference, xs.astype(np.float32), ys.astype(np.float32), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    peak = float(np.percentile(profiles[:, steps <= 0.35 * guess], 75))
    if peak < EDGE_MIN_CONTRAST:
        return None
    distances = []
    for profile in profiles:
        above = np.flatnonzero(profile > peak / 2)
        if len(above):
            distances.append(steps[above[-1]])
    if len(distances) < EDGE_MIN_RAYS:
        return None
    radius = float(np.median(distances))
    return radius if radius >= EDGE_MIN_RADIUS_PX else None


def ball_edge_fit(difference, center, radius):
    """Sub-pixel outline of a ball near `center`, from radial brightness profiles.

    Each ray's edge is where its profile crosses halfway between the ball's own level
    and the background just outside it. That is the true edge of a blurred step, and
    searching inward from outside ignores the seam and logo inside the disc. Rays whose
    contrast is too low (clubhead, shadow, image border) are dropped, and a robust
    circle fit discards any that still disagree. Returns None when too few rays agree.
    """
    height, width = difference.shape[:2]
    angles = np.linspace(0, 2 * math.pi, EDGE_RAYS, endpoint=False)
    radius = _coarse_edge_radius(difference, center, radius, angles)
    if radius is None:
        return None
    for _ in range(2):  # A second pass re-centres the rays on the first fit.
        steps = np.arange(0.4 * radius, 1.7 * radius, EDGE_STEP_PX)
        xs = center[0] + np.outer(np.cos(angles), steps)
        ys = center[1] + np.outer(np.sin(angles), steps)
        inside_image = (xs.min(axis=1) >= 0) & (ys.min(axis=1) >= 0) & (xs.max(axis=1) <= width - 1) & (ys.max(axis=1) <= height - 1)
        profiles = cv2.remap(difference, xs.astype(np.float32), ys.astype(np.float32), cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        # The ball's level just inside its edge: a shaded ball is brighter further in,
        # which would pull a deeper sample's half-contrast crossing inward.
        inner, outer = (steps >= 0.65 * radius) & (steps <= 0.85 * radius), steps >= 1.35 * radius
        level_in, level_out = np.median(profiles[:, inner], axis=1), np.median(profiles[:, outer], axis=1)
        contrast = level_in - level_out
        # A side-lit ball's shadowed limb fades into the background with no sharp edge;
        # its half-contrast crossing drifts inward, so fit only the well-lit arc.
        floor = max(EDGE_MIN_CONTRAST, EDGE_LIT_FRACTION * float(np.median(contrast[inside_image])) if inside_image.any() else 0.0)
        points = []
        for ray, profile in enumerate(profiles):
            if not inside_image[ray] or contrast[ray] < floor:
                continue
            half = (level_in[ray] + level_out[ray]) / 2
            above = np.flatnonzero(profile[~outer] > half)
            if not len(above) or above[-1] + 1 >= len(profile):
                continue
            j = above[-1]
            fraction = (profile[j] - half) / max(profile[j] - profile[j + 1], 1e-6)
            distance = steps[j] + fraction * EDGE_STEP_PX
            if 0.6 * radius <= distance <= 1.3 * radius:
                points.append(center + distance * np.array([math.cos(angles[ray]), math.sin(angles[ray])]))
        if len(points) < EDGE_MIN_RAYS:
            return None
        points = np.asarray(points)
        keep = _circular_arc(points)
        if keep is None:
            return None
        center, radius = _fit_circle(points[keep])
    errors = np.abs(np.linalg.norm(points[keep] - center, axis=1) - radius)
    rms = float(np.sqrt(np.mean(errors ** 2)))
    if rms > EDGE_MAX_RMS_PX:
        return None
    return {"centerPx": center, "radiusPx": radius, "rmsPx": rms, "rays": int(keep.sum()), "points": points[keep]}


def circle_contour(center, radius, count=64):
    """Return a complete outline for a tracker-guided, partially visible ball disc."""
    angles = np.linspace(0, 2 * math.pi, count, endpoint=False)
    return np.column_stack((center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)))


def guided_ball_track(frames, background, seed_radius, motion_track, origin, matrix, distortion, rotation, translation, diagnostics=None):
    """Recover a short 3D track only where independent image-plane tracking agrees.

    The normal contour path deliberately requires a nearly complete disc. A club,
    seam, or background edge can clip that disc even though the template tracker
    follows the ball cleanly. This fallback lowers the fill gate only at the
    tracker's expected position, then requires three consecutive frames, stable
    apparent radius, and the existing 3D linear-fit gate.
    """
    if diagnostics is None:
        diagnostics = {}
    diagnostics.update(frames=[], longestRun=0, radiusRejectedWindows=0, fitRejectedWindows=0)
    hints = {}
    for hint in motion_track or []:
        index = hint.get("frameIndex")
        center = np.asarray([hint.get("x"), hint.get("y")], dtype=float)
        if (
            not isinstance(index, int)
            or not 0 <= index < len(frames)
            or not np.all(np.isfinite(center))
            or float(hint.get("score", 0)) < 0.75
            or np.linalg.norm(center - origin) <= seed_radius * 0.5
        ):
            continue
        hints[index] = center

    recovered = []
    for index, expected in sorted(hints.items()):
        candidates = []
        evidence = {"frameIndex": index, "status": "no-matching-outline"}
        for center, contour in ball_contours(
            frames[index][1], background, seed_radius, minimum_fill=GUIDED_BALL_FILL
        ):
            distance = float(np.linalg.norm(center - expected))
            if distance > seed_radius * 0.5:
                continue
            (_, _), radius = cv2.minEnclosingCircle(contour)
            try:
                camera_center = sphere_center(circle_contour(center, radius), matrix, distortion)
            except ValueError:
                evidence["status"] = "distorted-outline"
                continue
            point = rotation.T @ (camera_center - translation)
            if point[2] < -0.01 or np.linalg.norm(point) > 5:
                evidence.update(status="invalid-depth", heightMm=round(float(point[2]) * 1000, 1))
                continue
            candidates.append((distance, radius, center, point))
        if candidates:
            _, radius, center, point = min(candidates, key=lambda candidate: candidate[0])
            recovered.append({
                "frameIndex": index,
                "positionM": point.tolist(),
                "centerPx": center.tolist(),
                "radiusPx": float(radius),
            })
            evidence.update(status="accepted", radiusPx=round(float(radius), 2),
                            heightMm=round(float(point[2]) * 1000, 1))
        diagnostics["frames"].append(evidence)

    runs = []
    for point in recovered:
        if not runs or point["frameIndex"] != runs[-1][-1]["frameIndex"] + 1:
            runs.append([])
        runs[-1].append(point)
    diagnostics["longestRun"] = max((len(run) for run in runs), default=0)
    for run in runs:
        for start in range(max(1, len(run) - GUIDED_MIN_SEQUENCE + 1)):
            window = run[start:start + 8]
            if len(window) < GUIDED_MIN_SEQUENCE:
                continue
            radii = [point["radiusPx"] for point in window]
            while len(window) >= GUIDED_MIN_SEQUENCE and max(radii) / min(radii) > GUIDED_RADIUS_RATIO:
                window = window[:-1]
                radii = radii[:-1]
            if len(window) < GUIDED_MIN_SEQUENCE:
                diagnostics["radiusRejectedWindows"] += 1
                continue
            try:
                velocity, residual = fit_velocity(
                    [frames[point["frameIndex"]][0] for point in window],
                    [point["positionM"] for point in window],
                )
            except ValueError:
                diagnostics["fitRejectedWindows"] += 1
                continue
            clean = [{key: value for key, value in point.items() if key != "radiusPx"} for point in window]
            return clean, velocity, residual
    return None


def ground_point(pixel, matrix, distortion, rotation, translation):
    """Intersect a ball-centre pixel ray with the plane holding a resting ball's centre."""
    uv = cv2.undistortPoints(np.asarray([[pixel]], np.float64), matrix, distortion).reshape(2)
    camera = -rotation.T @ translation
    ray = rotation.T @ np.array([uv[0], uv[1], 1.0])
    if abs(ray[2]) < 1e-8:
        return None
    scale = (RADIUS - camera[2]) / ray[2]
    return camera + ray * scale if scale > 0 else None


def ground_roll(frames, launch_track, motion_track, velocity, residual, matrix, distortion, rotation, translation):
    """Recognise a ball that stayed on the ground and measure it along the ground plane.

    Sphere depth follows apparent size, so a rolling ball's estimated centre moves up
    and down with silhouette noise and a short fit reads that as a steep launch. When
    the fitted track stays at resting height without a sustained rise, report a ground
    roll: speed and direction come from ball-centre rays projected onto the plane.
    """
    times = np.array([frames[point["frameIndex"]][0] for point in launch_track])
    heights = np.array([point["positionM"][2] for point in launch_track])
    deviation = float(np.median(np.abs(heights - RADIUS)))
    rise = float(np.polyfit(times - times[0], heights, 1)[0] * (times[-1] - times[0]))
    if deviation > GROUND_HEIGHT_TOLERANCE_M or rise > GROUND_RISE_TOLERANCE_M:
        return None
    first = launch_track[0]["frameIndex"]
    hints = {}
    for hint in motion_track or []:
        index = hint.get("frameIndex")
        if isinstance(index, int) and first <= index < len(frames) and float(hint.get("score", 0)) >= 0.75:
            hints[index] = (hint["x"], hint["y"])
    sources = (
        ("template-track", sorted(hints.items())[:GROUND_TRACK_FRAMES]),
        ("ball-outlines", [(point["frameIndex"], point["centerPx"]) for point in launch_track if point.get("centerPx")]),
    )
    source, ground_velocity, ground_residual = "3d-horizontal", np.array(velocity, dtype=float), residual
    for name, samples in sources:
        points = [(index, ground_point(pixel, matrix, distortion, rotation, translation)) for index, pixel in samples]
        points = [(index, point) for index, point in points if point is not None]
        if len(points) < 3:
            continue
        try:
            ground_velocity, ground_residual = fit_velocity([frames[index][0] for index, _ in points], [point for _, point in points])
        except ValueError:
            continue
        source = name
        break
    ground_velocity = np.array(ground_velocity, dtype=float)
    ground_velocity[2] = 0.0
    evidence = {"medianHeightDeviationMm": round(deviation * 1000, 1), "heightRiseMm": round(rise * 1000, 1),
                "velocitySource": source}
    return ground_velocity, ground_residual, evidence


def trajectory_observations(frames, bounds, impact_index, motion_track, background):
    """Resting-ball pixel, departure time bracket and the contiguous outgoing image track."""
    x, y, bw, bh = bounds
    origin = np.array([x + bw / 2, y + bh / 2])
    seed_radius = min(bw, bh) / 2
    height, width = frames[0][1].shape[:2]
    points = {}
    for hint in motion_track or []:
        index = hint.get("frameIndex")
        center = np.asarray([hint.get("x"), hint.get("y")], dtype=float)
        if isinstance(index, int) and 0 <= index < len(frames) and np.all(np.isfinite(center)) and float(hint.get("score", 0)) >= 0.7:
            points[index] = center
    near = [(index, center) for index, center in sorted(points.items())
            if index < impact_index and np.linalg.norm(center - origin) <= seed_radius * 2.5]
    resting = []
    if near:
        # Early outgoing frames can precede the refined impact index; keep only
        # observations clustered on the resting ball itself.
        cluster = np.median([center for _, center in near], axis=0)
        resting = [(index, center) for index, center in near
                   if np.linalg.norm(center - cluster) <= max(1.5, seed_radius * 0.2)]
    rest = np.mean([center for _, center in resting[-8:]], axis=0) if resting else origin
    run = []
    for index, center in sorted(points.items()):
        if index < impact_index or np.linalg.norm(center - rest) <= seed_radius * 0.5:
            continue
        if run and index - run[-1][0] > 2:
            break
        # A ball clipped by the image edge has a biased centre and radius.
        if not (seed_radius <= center[0] <= width - seed_radius and seed_radius <= center[1] <= height - seed_radius):
            break
        run.append((index, center))
        if len(run) >= TRAJECTORY_MAX_FRAMES:
            break
    if len(run) < TRAJECTORY_MIN_FRAMES:
        raise ValueError(f"Trajectory fit needs {TRAJECTORY_MIN_FRAMES} tracked outgoing frames; found {len(run)}.")
    first_time = frames[run[0][0]][0]
    interval = float(np.median(np.diff([t for t, _ in frames])))
    # The ball cannot leave before it was last seen resting.
    lower = frames[resting[-1][0]][0] if resting and resting[-1][0] < run[0][0] else first_time - 2 * interval
    observations = []
    guess = seed_radius
    for index, center in run:
        radius, sigma = None, TRAJECTORY_RADIUS_SIGMA_PX
        # Contact can fall anywhere up to the first moving frame, so that frame may show
        # the ball at impact; recovery is timed from it, not from the last resting frame.
        if frames[index][0] - first_time < BALL_RECOVERY_S:
            # Still flattened or ringing from impact: its outline is not the 42.67 mm
            # sphere the depth model assumes, so only its position is used.
            observations.append({"frameIndex": index, "centerPx": center.tolist(), "radiusPx": None,
                                 "radiusSigmaPx": sigma, "edgeRmsPx": None, "compressionWindow": True})
            continue
        edge = ball_edge_fit(ball_difference(frames[index][1], background), center, guess)
        # The edge fit's centre is not used: which lit arc it locks onto shifts from
        # frame to frame, and on replays it raised the track residual from ~1.5 to ~2.1 px
        # against the template-matched centre.
        if edge is not None:
            radius, sigma, guess = edge["radiusPx"], TRAJECTORY_EDGE_RADIUS_SIGMA_PX, edge["radiusPx"]
        else:
            nearby = [(np.linalg.norm(found - center), contour) for found, contour in
                      ball_contours(frames[index][1], background, seed_radius, minimum_fill=GUIDED_BALL_FILL)]
            nearby = [item for item in nearby if item[0] <= seed_radius * 0.5]
            if nearby:
                radius = float(cv2.minEnclosingCircle(min(nearby, key=lambda item: item[0])[1])[1])
        observations.append({"frameIndex": index, "centerPx": center.tolist(), "radiusPx": radius,
                             "radiusSigmaPx": sigma, "edgeRmsPx": round(edge["rmsPx"], 3) if edge else None})
    return rest, (lower, first_time), observations


def fit_trajectory(frames, rest_px, time_bounds, observations, matrix, distortion, rotation, translation):
    """Fit ground-roll and flight models to the outgoing image track.

    Models start from the resting ball's known ground position ("ground", "flight").
    If the ball was nudged before it left (a finger or clubhead moving it while
    occluded) that anchor is wrong, so a roll whose start point is re-estimated on
    the ground plane ("ground-free") is the fallback. Flight is chosen only when it
    explains the track clearly better than a roll and its launch angle is resolved.
    Each model gets one round of rejecting occluded/mismatched frames.
    """
    anchor = ground_point(rest_px, matrix, distortion, rotation, translation)
    if anchor is None:
        raise ValueError("Resting ball ray does not meet the ground plane.")
    rvec = cv2.Rodrigues(rotation)[0]
    lower, upper = time_bounds
    counts = {"ground": 4, "flight": 4, "ground-free": 5}
    steps = np.array([1e-3, 1e-3, 1e-3, 1e-5, 1e-5])

    def unpack(obs):
        return (np.array([frames[o["frameIndex"]][0] for o in obs]), np.array([o["centerPx"] for o in obs], dtype=float),
                np.array([o["radiusPx"] is not None for o in obs]), np.array([o["radiusPx"] or 0.0 for o in obs]),
                np.array([o.get("radiusSigmaPx", TRAJECTORY_RADIUS_SIGMA_PX) for o in obs]))

    def positions(model, params, times):
        if model == "flight":
            dts = np.maximum(0.0, times - params[3])
            moved = anchor + np.outer(dts, params[:3])
            moved[:, 2] -= 0.5 * GRAVITY * dts ** 2
            return moved
        if model == "ground":
            start, dts = anchor, np.maximum(0.0, times - params[3])
        else:
            start, dts = np.array([params[3], params[4], RADIUS]), times - times[0]
        planar = np.array(params[:2])
        speed = float(np.linalg.norm(planar))
        direction = planar / speed if speed > 1e-9 else np.array([1.0, 0.0])
        travel = speed * dts - 0.5 * params[2] * dts ** 2
        return start + np.column_stack((np.outer(travel, direction), np.zeros(len(dts))))

    def predicted(points):
        pixels = cv2.projectPoints(points.reshape(-1, 1, 3), rvec, translation, matrix, distortion)[0].reshape(-1, 2)
        camera = points @ rotation.T + translation
        # Project two silhouette-edge offsets so lens distortion shapes the radius too.
        edges = [camera + RADIUS * np.array(axis) for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))]
        edge_pixels = [cv2.projectPoints(edge.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), matrix, distortion)[0].reshape(-1, 2)
                       for edge in edges]
        return pixels, np.mean([np.linalg.norm(edge - pixels, axis=1) for edge in edge_pixels], axis=0)

    def residuals(model, params, data):
        times, centers, mask, radii, sigmas = data
        pixels, radius = predicted(positions(model, params, times))
        values = np.concatenate((((pixels - centers) / TRAJECTORY_CENTER_SIGMA_PX).ravel(),
                                 ((radius - radii) / sigmas)[mask]))
        large = np.abs(values) > TRAJECTORY_HUBER
        values[large] = np.sign(values[large]) * np.sqrt(2 * TRAJECTORY_HUBER * np.abs(values[large]) - TRAJECTORY_HUBER ** 2)
        return values

    def jacobian(model, params, base, data):
        columns = []
        for k in range(counts[model]):
            shifted = params.copy()
            shifted[k] += steps[k]
            columns.append((residuals(model, shifted, data) - base) / steps[k])
        return np.column_stack(columns)

    def initial_guess(model, data):
        times, centers = data[0], data[1]
        # This is only a seed. A ball in flight climbs above the camera, so its later
        # rays never meet the ground plane; seed from the early frames that still do.
        seeds = [(time, ground_point(c, matrix, distortion, rotation, translation))
                 for time, c in zip(times[:12], centers[:12])]
        seeds = [(time, point) for time, point in seeds if point is not None]
        if len(seeds) < 2:
            raise ValueError("Tracked ball rays do not meet the ground plane.")
        planar = np.asarray([point for _, point in seeds], dtype=float)
        design = np.column_stack((np.array([time for time, _ in seeds]) - times[0], np.ones(len(planar))))
        slope, intercept = np.linalg.lstsq(design, planar[:, :2], rcond=None)[0]
        if model == "ground-free":
            return np.array([slope[0], slope[1], 0.0, intercept[0], intercept[1]])
        start = upper - np.linalg.norm(intercept - anchor[:2]) / max(float(np.linalg.norm(slope)), 1e-3)
        return np.array([slope[0], slope[1], 0.0, float(np.clip(start, lower, upper))])

    def flight_seeds(data):
        """Launch velocities from a coarse grid scored directly against the image track.

        The ground projection of a climbing ball runs away toward the horizon (metres
        out within a few frames), so it cannot seed flight on its own.
        """
        times, centers = data[0], data[1]
        start = 0.5 * (lower + upper)
        dts = np.maximum(0.0, times - start)
        heading, launch, speed = np.meshgrid(np.radians(np.arange(0.0, 360.0, 15.0)), np.radians(FLIGHT_SEED_LAUNCH_DEG),
                                             FLIGHT_SEED_SPEED_MPS, indexing="ij")
        velocity = np.stack((np.cos(launch) * np.cos(heading), np.cos(launch) * np.sin(heading), np.sin(launch)),
                            axis=-1).reshape(-1, 3) * speed.reshape(-1, 1)
        points = anchor + velocity[:, None, :] * dts[None, :, None]
        points[:, :, 2] -= 0.5 * GRAVITY * dts ** 2
        pixels = cv2.projectPoints(points.reshape(-1, 1, 3), rvec, translation, matrix, distortion)[0]
        pixels = pixels.reshape(len(velocity), len(times), 2)
        # Strong lens distortion folds points far outside the view back into it; only
        # candidates that stay in front of the camera are scored, with capped errors.
        depth = (points.reshape(-1, 3) @ rotation.T + translation)[:, 2].reshape(len(velocity), len(times))
        cost = np.minimum(np.linalg.norm(pixels - centers, axis=2), 200.0).sum(axis=1)
        cost[(depth <= 0.05).any(axis=1)] = np.inf
        return [np.array([*velocity[i], start]) for i in np.argsort(cost)[:FLIGHT_SEED_STARTS]]

    def solve(model, obs):
        data = unpack(obs)
        starts = []
        try:
            starts.append(initial_guess(model, data))
        except ValueError:
            if model != "flight":
                raise
        if model == "flight":
            starts.extend(flight_seeds(data))
        return min((refine(model, obs, data, params) for params in starts), key=lambda fit: fit["cost"])

    def refine(model, obs, data, params):
        base = residuals(model, params, data)
        cost, damping = float(base @ base), 1e-3
        for _ in range(80):
            jac = jacobian(model, params, base, data)
            normal = jac.T @ jac
            try:
                delta = -np.linalg.solve(normal + damping * np.diag(np.diag(normal) + 1e-9), jac.T @ base)
            except np.linalg.LinAlgError:
                break
            candidate = params + delta
            if model != "ground-free":
                candidate[3] = float(np.clip(candidate[3], lower, upper))
            trial = residuals(model, candidate, data)
            trial_cost = float(trial @ trial)
            if trial_cost < cost:
                improvement = cost - trial_cost
                params, base, cost, damping = candidate, trial, trial_cost, damping * 0.3
                if improvement < 1e-9 * max(1.0, cost):
                    break
            else:
                damping *= 10
                if damping > 1e8:
                    break
        jac = jacobian(model, params, base, data)
        covariance = np.linalg.pinv(jac.T @ jac) * max(1.0, cost / max(1, len(base) - counts[model]))
        pixels, _ = predicted(positions(model, params, data[0]))
        errors = np.linalg.norm(pixels - data[1], axis=1)
        return {"model": model, "params": params, "cost": cost, "covariance": covariance, "observations": obs,
                "errors": errors, "rms": float(np.sqrt(np.mean(errors ** 2)))}

    def robust(model):
        fit = solve(model, observations)
        keep = fit["errors"] <= max(3.0, 4 * float(np.median(fit["errors"])))
        removed = len(keep) - int(keep.sum())
        if 0 < removed <= len(keep) // 4 and int(keep.sum()) >= TRAJECTORY_MIN_FRAMES:
            refit = solve(model, [o for o, k in zip(observations, keep) if k])
            refit["rejected"] = [o["frameIndex"] for o, k in zip(observations, keep) if not k]
            return refit
        fit["rejected"] = []
        return fit

    def velocity_of(fit):
        p = fit["params"]
        return np.array([p[0], p[1], p[2] if fit["model"] == "flight" else 0.0])

    def sigma(fit, function):
        params, covariance = fit["params"], fit["covariance"]
        gradient = np.zeros(counts[fit["model"]])
        for k in range(3):
            shifted = params.copy()
            shifted[k] += steps[k]
            gradient[k] = (function(velocity_of({**fit, "params": shifted})) - function(velocity_of(fit))) / steps[k]
        return float(math.sqrt(max(0.0, gradient @ covariance @ gradient)))

    heading_of = lambda v: math.degrees(math.atan2(v[1], v[0]))
    launch_of = lambda v: math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
    speed_of = lambda v: float(np.linalg.norm(v))

    fits = {model: robust(model) for model in counts}
    flight, ground = fits["flight"], fits["ground"]
    flight_velocity = velocity_of(flight)
    flight_launch, flight_launch_sigma = launch_of(flight_velocity), sigma(flight, launch_of)
    # Compare flight against a roll on the same frames.
    ground_on_flight = residuals("ground", ground["params"], unpack(flight["observations"]))
    if (
        flight["rms"] <= TRAJECTORY_MAX_RMS_PX
        and flight_velocity[2] > 0
        and flight["cost"] + 9.0 < float(ground_on_flight @ ground_on_flight)
        and flight_launch > 3 * flight_launch_sigma
    ):
        chosen = flight
    else:
        free = fits["ground-free"]
        # A re-estimated start can absorb almost any short track, so it must also be
        # a physically plausible roll; prefer the resting-ball anchor unless the free
        # start explains the track clearly better (the ball was nudged first).
        free_ok = (free["rms"] <= TRAJECTORY_MAX_RMS_PX and abs(float(free["params"][2])) <= TRAJECTORY_MAX_ROLL_DECELERATION
                   and len(free["observations"]) >= FREE_START_MIN_FRAMES)
        if ground["rms"] <= TRAJECTORY_MAX_RMS_PX and not (free_ok and free["rms"] < 0.6 * ground["rms"]):
            chosen = ground
        elif free_ok:
            chosen = free
        else:
            chosen = None
    if chosen is None:
        best = min(fits.values(), key=lambda fit: fit["rms"])
        raise ValueError(f"Trajectory fit image residual {best['rms']:.1f} px exceeds {TRAJECTORY_MAX_RMS_PX:.1f} px.")

    model, params, used = chosen["model"], chosen["params"], chosen["observations"]
    times, _, mask, radii, _ = unpack(used)
    fitted = positions(model, params, times)
    _, radius = predicted(fitted)
    edge = np.array([o.get("edgeRmsPx") is not None for o in used])
    velocity = velocity_of(chosen)
    if model == "ground-free":
        impact_index = used[0]["frameIndex"]
        departure_ms = None
    else:
        impact_index = next((o["frameIndex"] for o, t in zip(used, times) if t >= params[3]), used[0]["frameIndex"])
        departure_ms = round((times[0] - params[3]) * 1000, 2)
    return {
        "model": "flight" if model == "flight" else "ground",
        "velocity": velocity,
        "impactFrameIndex": impact_index,
        "track": [{"frameIndex": o["frameIndex"], "positionM": p.tolist(), "centerPx": o["centerPx"]}
                  for o, p in zip(used, fitted)],
        "diagnostics": {
            "model": "flight" if model == "flight" else "ground",
            "startPoint": "re-estimated" if model == "ground-free" else "resting-ball",
            # Where the re-estimated roll starts relative to the stale resting position.
            "startOffsetMm": round(float(np.linalg.norm(params[3:5] - anchor[:2])) * 1000, 1) if model == "ground-free" else None,
            "frames": len(used),
            "rejectedFrames": chosen["rejected"],
            "firstFrameIndex": used[0]["frameIndex"],
            "lastFrameIndex": used[-1]["frameIndex"],
            "departureBeforeFirstMovingMs": departure_ms,
            "rmsPx": round(chosen["rms"], 3),
            "radiusObservations": int(mask.sum()),
            "edgeFitFrames": int(edge.sum()),
            # A standard 42.67 mm ball is a scale reference the calibration must agree with:
            # measured over predicted apparent size. Away from 1, the tag size, lens model or
            # ground pose is scaling every distance, and so every speed, by that much.
            "ballSizeRatio": round(float(np.median(radii[edge] / radius[edge])), 4) if edge.sum() >= BALL_SIZE_MIN_FRAMES else None,
            "edgeRmsPx": (round(float(np.median([o["edgeRmsPx"] for o in used if o.get("edgeRmsPx") is not None])), 3)
                          if any(o.get("edgeRmsPx") is not None for o in used) else None),
            "radiusRmsPx": round(float(np.sqrt(np.mean((radius - radii)[mask] ** 2))), 3) if mask.any() else None,
            "modelRmsPx": {name: round(fit["rms"], 3) for name, fit in fits.items()},
            "flightLaunchDeg": round(flight_launch, 2),
            "flightLaunchSigmaDeg": round(flight_launch_sigma, 2),
            "decelerationMps2": round(float(params[2]), 3) if model != "flight" else None,
            "speedSigmaMps": round(sigma(chosen, speed_of), 4),
            "launchSigmaDeg": round(flight_launch_sigma, 2) if model == "flight" else None,
            "headingDeg": round(heading_of(velocity), 2),
            "headingSigmaDeg": round(sigma(chosen, heading_of), 2),
        },
    }


def silhouette_launch(frames, bounds, impact_index, motion_track, matrix, distortion, rotation, translation, diagnostics, result):
    """Per-frame known-size silhouette depth, used when the image track is too short to fit."""
    x, y, bw, bh = bounds
    origin = np.array([x + bw / 2, y + bh / 2])
    previous = origin
    track = []
    seed_radius = min(bw, bh) / 2
    background = ball_background(frames, impact_index)
    # The impact hint comes from a coarse presence detector (one sample every
    # frame-stride frames, a removal debounce, and still-present rechecks), so the
    # real departure can sit over a hundred frames either side of it. Locate the
    # first clean moving silhouette anywhere in the burst, then track densely.
    start = 0
    for i in range(0, len(frames), 3):
        if ball_contours(frames[i][1], background, seed_radius):
            start = max(0, i - 3)
            break
    for i in range(start, len(frames)):
        candidates = ball_contours(frames[i][1], background, seed_radius)
        if not candidates:
            continue
        diagnostics["strict"]["candidateFrames"] += 1
        candidates.sort(key=lambda candidate: np.linalg.norm(candidate[0] - previous))
        center, contour = candidates[0]
        # While the ball overlaps its resting spot, or the club head passes over it,
        # the difference blob is not a clean disc; the first accepted silhouette can
        # be a dozen radii out, so only reject candidates that are absurdly far.
        if not track and np.linalg.norm(center - origin) > seed_radius * 40:
            continue
        if track and len(candidates) > 1 and np.linalg.norm(candidates[1][0] - previous) < np.linalg.norm(center - previous) * 1.25:
            continue  # Ambiguous identity: do not silently switch balls.
        try:
            point = rotation.T @ (sphere_center(contour, matrix, distortion) - translation)
        except ValueError:
            diagnostics["strict"]["distortedOutlines"] += 1
            continue
        if point[2] < -0.01 or np.linalg.norm(point) > 5:
            diagnostics["strict"]["invalidDepth"] += 1
            continue
        if track and np.linalg.norm(point - np.array(track[-1]["positionM"])) / (frames[i][0] - frames[track[-1]["frameIndex"]][0]) > 100:
            continue
        track.append({"frameIndex": i, "positionM": point.tolist(), "centerPx": center.tolist()})
        previous = center
    diagnostics["strict"]["acceptedFrames"] = len(track)
    outgoing = [p for p in track if np.linalg.norm(np.array(p["centerPx"]) - origin) > seed_radius * .5]
    guided = False
    if len(outgoing) < 3:
        diagnostics["guided"] = {}
        recovered = guided_ball_track(
            frames, background, seed_radius, motion_track, origin,
            matrix, distortion, rotation, translation, diagnostics=diagnostics["guided"],
        )
        if recovered is None:
            evidence = diagnostics["guided"]["frames"]
            accepted = sum(point["status"] == "accepted" for point in evidence)
            invalid_depth = sum(point["status"] == "invalid-depth" for point in evidence)
            raise ValueError(
                f"Fewer than three usable 3D ball outlines. Captured {len(frames)} frames; "
                f"tracked motion in {diagnostics['motionTrackedFrames']}. "
                f"Partial-outline checks accepted {accepted} frames, "
                f"with a longest consecutive run of {diagnostics['guided']['longestRun']}; "
                f"{invalid_depth} failed ground/depth checks. Check ball edges and ground calibration."
            )
        outgoing, velocity, residual = recovered
        track = outgoing
        guided = True
        result["warnings"].append(
            "Ball outline was reconstructed from a tracker-guided partial silhouette; validate this lower-confidence estimate."
        )
    launch_track = outgoing[:8]
    if not guided:
        times = [frames[p["frameIndex"]][0] for p in launch_track]
        velocity, residual = fit_velocity(times, [p["positionM"] for p in launch_track])
    ground = ground_roll(frames, launch_track, motion_track, velocity, residual,
                         matrix, distortion, rotation, translation)
    if ground is not None:
        velocity, residual, result["groundRoll"] = ground
    method_note = " Tracker-guided partial-silhouette fallback." if guided else ""
    if ground is not None:
        reason = (f"Ball stayed on the ground (height within {ground[2]['medianHeightDeviationMm']:.0f} mm of resting, "
                  f"rise {ground[2]['heightRiseMm']:.0f} mm); measured along the ground plane, fit residual "
                  f"{residual * 1000:.1f} mm.{method_note} Requires reference validation.")
    else:
        reason = f"Known-ball-size 3D estimate; fit residual {residual * 1000:.1f} mm.{method_note} Requires reference validation."
    launch = 0.0 if ground is not None else math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1])))
    return track, outgoing, velocity, launch, reason, reason, outgoing[0]["frameIndex"]


def secondary_camera(lower_camera, image_size, ground_id, tag_size, lower_captured_at, surface_offset_m=0.0):
    """Top-camera lens and world pose, from the fixed stereo pair or its own ground tag.

    Returns (matrix, distortion, pose, fixed_pair). Shared by shot analysis and the
    pre-shot readiness check so both judge the same calibration.
    """
    from datetime import datetime
    matrix, distortion = load_setup(image_size, "secondary")
    from stereo_calibration import fixed_secondary_pose
    pose = fixed_secondary_pose(lower_camera, (matrix, distortion), tuple(image_size),
                                [int(os.getenv("PINPOINT_CAMERA_INDEX", "0")),
                                 int(os.getenv("PINPOINT_SECONDARY_CAMERA_INDEX", "1"))])
    fixed_pair = pose is not None
    if not fixed_pair:
        pose = stored_ground_pose(tuple(image_size), ground_id, tag_size, matrix, distortion, camera="secondary")
    if pose is None:
        raise ValueError("Top camera has no AprilTag ground calibration; capture the tag with both cameras.")
    # Both poses must describe one tag placement; the app captures them together.
    if not fixed_pair:
        stamps = [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in (lower_captured_at, pose.get("capturedAt"))]
        if abs((stamps[0] - stamps[1]).total_seconds()) > STEREO_MAX_CALIBRATION_SKEW_S:
            raise ValueError("Lower and top cameras were calibrated at different times; capture the tag with both cameras again.")
        # A fixed pair is derived from the (already shifted) lower pose; an independent
        # top-camera pose has to be shifted the same way.
        if surface_offset_m:
            pose = {**pose, "translation": shift_surface(pose["rotation"], pose["translation"], surface_offset_m)}
    return matrix, distortion, pose, fixed_pair


def stereo_measurement(frames, secondary_frames, rest_px, fit, observations, start_time, lower_camera,
                       ground_id, tag_size, lower_captured_at, lower_pose_error_px, surface_offset_m=0.0):
    """Cross-check or independently recover the launch from both calibrated cameras."""
    from stereo_check import stereo_cross_check
    height, width = secondary_frames[0][1].shape[:2]
    matrix, distortion, pose, fixed_pair = secondary_camera(lower_camera, (width, height), ground_id, tag_size,
                                                            lower_captured_at, surface_offset_m)
    track = fit["track"] if fit is not None else (observations or [])
    stereo = stereo_cross_check(frames, secondary_frames, lower_camera,
                                (matrix, distortion, pose["rotation"], pose["translation"]), rest_px, track,
                                start_time, fit["velocity"] if fit is not None else None,
                                None)
    stereo["lowerPoseErrorPx"] = float(lower_pose_error_px)
    stereo["upperPoseErrorPx"] = float(lower_pose_error_px) if fixed_pair else float(pose["errorPx"])
    stereo["calibrationSource"] = "fixed-pair" if fixed_pair else "independent-ground-tags"
    if fixed_pair:
        stereo["stereoCalibrationId"] = pose["calibrationId"]
        stereo["pairValidationRmsPx"] = pose["errorPx"]
    if stereo.get("speedOnly"):
        if max(stereo["lowerPoseErrorPx"], stereo["upperPoseErrorPx"]) > STRICT_TAG_POSE_ERROR_PX:
            raise ValueError("Ground pose is too uncertain for a two-point speed estimate.")
        stereo["accepted"] = True
        return stereo
    from stereo_check import (MAX_PAIR_OFFSET_US, MAX_RAY_GAP_MM, MAX_REST_HEIGHT_ERROR_MM, MAX_START_ANCHOR_ERROR_MM,
                              MAX_STEREO_RMS_PX, SEARCH_MAX_RAY_GAP_MM, SEARCH_MAX_RMS_PX)
    # A launch found by the flight search rests on blurred, unpaired detections: it is accepted with looser
    # image and ray limits than a paired fit, and the grading below keeps it an estimate.
    searched = stereo.get("detection") == "anchored-flight-search"
    max_ray_gap = SEARCH_MAX_RAY_GAP_MM if searched else MAX_RAY_GAP_MM
    max_rms = SEARCH_MAX_RMS_PX if searched else MAX_STEREO_RMS_PX
    problems = []
    if stereo["maxPairOffsetUs"] > MAX_PAIR_OFFSET_US:
        problems.append(f"Camera pair timing offset {stereo['maxPairOffsetUs']:.0f} µs exceeds {MAX_PAIR_OFFSET_US:.0f} µs.")
    if stereo["medianRayGapMm"] > max_ray_gap:
        problems.append(f"Median stereo ray gap {stereo['medianRayGapMm']:.1f} mm exceeds {max_ray_gap:.1f} mm.")
    if abs(stereo["restHeightErrorMm"]) > MAX_REST_HEIGHT_ERROR_MM:
        problems.append(f"Stereo resting-ball height error {stereo['restHeightErrorMm']:.1f} mm exceeds {MAX_REST_HEIGHT_ERROR_MM:.1f} mm.")
    if stereo["startAnchorErrorMm"] > MAX_START_ANCHOR_ERROR_MM:
        problems.append(f"Stereo trajectory misses the resting ball by {stereo['startAnchorErrorMm']:.1f} mm "
                        "for any contact time between the last still and first moving frames.")
    if stereo["rmsPx"] > max_rms:
        problems.append(f"Stereo trajectory reprojection residual {stereo['rmsPx']:.1f} px exceeds {max_rms:.1f} px.")
    if not 0.1 <= stereo["speedMps"] <= 100:
        problems.append(f"Stereo ball speed {stereo['speedMps']:.1f} m/s is outside the supported 0.1-100 m/s range.")
    if not stereo["track"]:
        problems.append("Stereo fit did not produce a ball trajectory.")
    stereo["accepted"] = not problems
    if problems:
        stereo["failure"] = " ".join(problems)
        if fit is None:
            from stereo_check import StereoTrackingError
            raise StereoTrackingError(stereo["failure"], stereo)
    else:
        stereo["impactFrameIndex"] = stereo["track"][0]["frameIndex"]
    return stereo


def measure_launch(frames, bounds, impact_index, timestamp_source="host", exposure_us=None, motion_track=None,
                   secondary_frames=None):
    result = {"metrics": unavailable("Needs a calibrated ball/club track."), "ballTrack3d": [], "clubTrack3d": [], "warnings": [], "method": "apriltag-monocular-sphere-v1"}
    diagnostics = {"version": 1, "frameCount": len(frames), "motionTrackedFrames": sum(
        1 for point in motion_track or []
        if isinstance(point.get("frameIndex"), int) and impact_index <= point["frameIndex"] < len(frames)
    ), "strict": {"candidateFrames": 0, "distortedOutlines": 0, "invalidDepth": 0, "acceptedFrames": 0}}
    result["diagnostics"] = diagnostics
    metrics = result["metrics"]
    pose_note = None
    grading = {}
    def put(key, value, reason, status="estimated"):
        if math.isfinite(value):
            metrics[key] = {"value": round(float(value), 4), "unit": METRICS[key], "status": status, "reason": reason}
    try:
        if timestamp_source != "sensor":
            raise ValueError("Sensor timestamps required; host arrival timing cannot measure launch speed.")
        if len(frames) < 3 or not np.all(np.isfinite([t for t, _ in frames])) or np.any(np.diff([t for t, _ in frames]) <= 0):
            raise ValueError("Capture has missing or non-increasing sensor timestamps.")
        if exposure_us is None:
            # No exposure metadata at all means the blur check cannot run; that is a
            # data-integrity failure, not a quality one.
            raise ValueError("Camera exposure is unknown; set a fixed exposure before measuring.")
        height, width = frames[0][1].shape[:2]
        matrix, distortion = load_setup((width, height))
        ground_id = int(os.getenv("PINPOINT_APRILTAG_ID", "0"))
        tag_size = float(os.getenv("PINPOINT_APRILTAG_SIZE_MM", "100")) / 1000
        # Preserve the actual inputs used for this analysis. Later recalibration
        # must not silently change an offline replay of an older capture.
        diagnostics["calibration"] = {"imageSize": [width, height], "cameraMatrix": matrix.tolist(),
                                      "distCoeffs": distortion.tolist(), "groundTagId": ground_id,
                                      "groundTagSizeMm": tag_size * 1000}
        diagnostics["calibration"]["groundMode"] = ground_mode()
        if ground_mode() == "rig":
            # Gravity runs down the rig and the target is image-right: no tag is used.
            pose = level_rig_pose()
        else:
            pose = stored_ground_pose((width, height), ground_id, tag_size, matrix, distortion)
            if pose is None:
                pose = find_ground_tag_pose(frames, impact_index, ground_id, tag_size, matrix, distortion)
            if pose is None:
                raise ValueError("Capture ground AprilTag calibration first, or keep the tag visible in this burst.")
        rotation, translation, pose_error = pose["rotation"], pose["translation"], pose["errorPx"]
        grading["poseErrorPx"] = pose_error
        grading["groundSource"] = pose.get("source")
        # The camera axis can only supply a target line once its pose is known, so this
        # is resolved here rather than alongside the other calibration inputs above.
        heading, heading_source = resolve_target_heading(rotation)
        grading["targetLineSource"] = heading_source
        diagnostics["calibration"]["targetHeadingDeg"] = math.degrees(heading) if heading is not None else None
        diagnostics["calibration"]["targetHeadingSource"] = heading_source
        camera_position = -rotation.T @ translation
        optical_axis = rotation.T @ np.array([0., 0., 1.])
        diagnostics["groundPose"] = {
            "source": pose.get("source", "current-burst"), "capturedAt": pose.get("capturedAt"),
            "cameraHeightMm": round(float(camera_position[2]) * 1000, 1),
            "cameraPitchDeg": round(math.degrees(math.asin(float(np.clip(-optical_axis[2], -1, 1)))), 2),
            "rotation": rotation.tolist(), "translationM": translation.tolist(),
        }
        result["tagPoseFrameIndex"] = pose["frameIndex"]
        result["tagPoseReprojectionErrorPx"] = round(pose_error, 4)
        pose_note = ("Level-rig ground: the stand is assumed level with gravity down the rig and the target to the "
                     f"right of the camera (pitch {pose['rig']['pitchDeg']:.2f}°, height {pose['rig']['heightMm']:.0f} mm "
                     "before the resting-ball correction)."
                     if pose.get("source") == "level-rig" else
                     f"Stored ground calibration ({pose.get('capturedAt')}), pose error {pose_error:.2f} px; camera must remain fixed."
                     if pose.get("source") == "stored-calibration" else
                     f"Ground-tag pose error {pose_error:.2f} px from frame {pose['frameIndex']}.")
        if pose_error > MAX_ESTIMATED_TAG_POSE_ERROR_PX:
            result["warnings"].append(
                f"Ground AprilTag pose reprojection error is {pose_error:.2f} px (limit "
                f"{MAX_ESTIMATED_TAG_POSE_ERROR_PX:.1f} px); values are unreliable estimates."
            )
        elif pose_error > STRICT_TAG_POSE_ERROR_PX:
            result["warnings"].append(
                f"Ground AprilTag pose reprojection error is {pose_error:.2f} px; "
                "launch values are lower-confidence estimates."
            )
        # Take the ground under this shot from the resting ball itself (see resting_ball_surface).
        surface_offset = 0.0
        if secondary_frames and pose.get("source") in BALL_GROUNDED_SOURCES and bounds is not None:
            try:
                size = secondary_frames[0][1].shape[1], secondary_frames[0][1].shape[0]
                upper_matrix, upper_distortion, upper_pose, _ = secondary_camera(
                    (matrix, distortion, rotation, translation), size, ground_id, tag_size, pose.get("capturedAt"))
                offset, check = resting_ball_surface(
                    frames, secondary_frames, bounds, impact_index, (matrix, distortion, rotation, translation),
                    (upper_matrix, upper_distortion, upper_pose["rotation"], upper_pose["translation"]),
                    RIG_MAX_SURFACE_OFFSET_MM if pose.get("source") == "level-rig" else MAX_SURFACE_OFFSET_MM)
            except (OSError, ValueError, KeyError, TypeError) as error:
                diagnostics["surface"] = {"source": "calibration", "failure": str(error)}
            else:
                if offset is not None:
                    surface_offset = offset
                    translation = shift_surface(rotation, translation, offset)
                diagnostics["surface"] = {
                    "source": "resting-ball" if offset is not None else "calibration",
                    "offsetMm": round(offset * 1000, 2) if offset is not None else None,
                    "measuredHeightErrorMm": (check or {}).get("heightErrorMm"),
                    "rayGapMm": (check or {}).get("rayGapMm"), "frameIndex": (check or {}).get("frameIndex"),
                }
        grading["rigHeightFromBall"] = diagnostics.get("surface", {}).get("source") == "resting-ball"
        if pose.get("source") == "level-rig" and not grading["rigHeightFromBall"]:
            result["warnings"].append(
                "Level-rig camera height is the stand constant; the two cameras could not confirm it from the resting ball "
                f"({diagnostics.get('surface', {}).get('failure') or 'ball not matched in both views'}).")
        fit = None
        two_point = None
        rest_px = time_bounds = observations = None
        if motion_track:
            try:
                rest_px, time_bounds, observations = trajectory_observations(
                    frames, bounds, impact_index, motion_track, ball_background(frames, impact_index))
                fit = fit_trajectory(frames, rest_px, time_bounds, observations, matrix, distortion, rotation, translation)
            except (ValueError, np.linalg.LinAlgError, cv2.error) as error:
                diagnostics["trajectoryFit"] = {"failure": str(error)}
        if secondary_frames and pose.get("source") in BALL_GROUNDED_SOURCES:
            mono_is_static = fit is not None and float(np.linalg.norm(fit["velocity"])) < MIN_PLAUSIBLE_MONO_SPEED_MPS
            if mono_is_static:
                diagnostics["trajectoryFit"] = {**diagnostics.get("trajectoryFit", {}), "discarded":
                                                "Fit is slower than 0.3 m/s: the tracker followed a static object, so the two cameras search without it."}
            try:
                stereo_rest_px = rest_px if (rest_px is not None and not mono_is_static) else np.array(
                    [bounds[0] + bounds[2] / 2, bounds[1] + bounds[3] / 2], dtype=float)
                stereo = stereo_measurement(frames, secondary_frames, stereo_rest_px, None if mono_is_static else fit,
                                            observations,
                                            None if mono_is_static else (time_bounds[0] if time_bounds else None),
                                            (matrix, distortion, rotation, translation), ground_id, tag_size,
                                            pose.get("capturedAt"), pose_error, surface_offset)
            except (OSError, ValueError, KeyError, TypeError, np.linalg.LinAlgError, cv2.error) as error:
                diagnostics["stereo"] = {"failure": str(error), **getattr(error, "diagnostics", {})}
                grading["stereoFailure"] = str(error)
            else:
                diagnostics["stereo"] = stereo
                if stereo.get("speedOnly"):
                    two_point = stereo
                elif not stereo["accepted"]:
                    grading["stereoFailure"] = stereo["failure"]
                else:
                    grading["stereo"] = stereo
                    if fit is not None:
                        diagnostics["monocularFit"] = fit["diagnostics"]
                    velocity = np.asarray(stereo["velocityMps"], dtype=float)
                    launch = float(stereo["launchDeg"])
                    impact_index = stereo["impactFrameIndex"]
                    track = outgoing = stereo["track"]
                    fit_diagnostics = {
                        "source": "stereo", "model": stereo["model"], "frames": stereo["frames"],
                        "startPoint": "resting-ball", "startOffsetMm": stereo["startAnchorErrorMm"],
                        "rmsPx": stereo["rmsPx"], "speedSigmaMps": stereo["speedSigmaMps"],
                        "launchSigmaDeg": stereo["launchSigmaDeg"],
                        "flightLaunchSigmaDeg": stereo["launchSigmaDeg"],
                        "flightLaunchDeg": stereo["launchDeg"],
                        "headingSigmaDeg": stereo["headingSigmaDeg"], "ballSizeRatio": None,
                    }
                    fit = {"model": stereo["model"], "velocity": velocity, "track": track,
                           "impactFrameIndex": impact_index, "diagnostics": fit_diagnostics}
                    diagnostics["monoTrajectoryFailure"] = diagnostics.get("trajectoryFit", {}).get("failure")
                    diagnostics["trajectoryFit"] = fit_diagnostics
                    result["method"] = "shared-tag-stereo-v2"
                    if stereo.get("detection") == "anchored-flight-search":
                        result["warnings"].append(
                            "The ball was found by a flight search over blurred, unpaired detections in both cameras "
                            f"({stereo.get('instants')} sightings); treat speed, launch and direction as estimates.")
                    result["ballTrack3d"] = track
                    result["estimatedImpactFrameIndex"] = impact_index
                    basis = (f"Joint stereo trajectory fit over {stereo['frames']} paired frames; "
                             f"reprojection residual {stereo['rmsPx']:.2f} px.")
                    speed_reason = (f"{basis} Two-camera triangulation replaces ball-outline size for depth. "
                                    "Requires reference validation.")
                    direction_reason = speed_reason
                    launch_reason = (f"{basis} Vertical motion fitted with gravity. Requires reference validation."
                                     if stereo["model"] == "flight" else
                                     f"Ball stayed near the calibrated ground plane; stereo fit gives 0° launch. "
                                     f"{basis} Requires reference validation.")
        if fit is None and two_point is not None:
            speed = two_point["speedMps"]
            blurred = speed * exposure_us / 1e6 > MAX_MOTION_BLUR_M
            if blurred:
                result["warnings"].append(
                    f"Ball smeared {(speed * exposure_us / 1e6 * 1000):.1f} mm during the {exposure_us} µs exposure "
                    f"(limit {MAX_MOTION_BLUR_M * 1000:.0f} mm); speed is a lower-confidence estimate.")
            result["method"] = "shared-tag-stereo-two-point-v1"
            result["ballTrack3d"] = two_point["track"]
            result["estimatedImpactFrameIndex"] = two_point["track"][0]["frameIndex"]
            put("ballSpeedMps", speed,
                f"Two stereo ball positions {two_point['spanMs']:.1f} ms apart; interval-average speed only, "
                f"not a fitted launch trajectory. One-pixel sensitivity ±{two_point['speedUncertaintyPct']:.0f}%. "
                "Requires reference validation.")
            metrics["ballSpeedMps"]["confidence"] = 0.4 if blurred else 0.5
            checks = [
                {"label": "Only two stereo ball frames; launch trajectory not resolved", "passed": False},
                {"label": "Stereo geometry and timing passed two-point checks", "passed": True},
            ]
            if blurred:
                checks.append({"label": "Ball motion blur stayed under 4 mm", "passed": False})
            metrics["ballSpeedMps"]["checks"] = checks
            for key in ("launchAngleDeg", "startDirectionDeg", "estimatedCarryM"):
                metrics[key]["reason"] = "Two ball positions give interval speed but cannot validate launch angle, direction or carry."
            result["shotEvidence"] = shot_evidence(result)
            return result
        if fit is not None:
            fitted = fit["diagnostics"]
            diagnostics["trajectoryFit"] = fitted
            grading["ballFit"] = fitted
            track = outgoing = fit["track"]
            velocity = fit["velocity"]
            impact_index = fit["impactFrameIndex"]
            result["ballTrack3d"] = track
            result["estimatedImpactFrameIndex"] = impact_index
            start = ("from the resting ball" if fitted["startPoint"] == "resting-ball" else
                     f"with its ground start re-estimated {fitted['startOffsetMm']:.0f} mm from the resting ball (moved before release)")
            basis = (f"Joint two-camera trajectory fit to {fitted['frames']} paired ball frames; "
                     f"image residual {fitted['rmsPx']:.2f} px."
                     if fitted.get("source") == "stereo" else
                     f"Anchored trajectory fit to {fitted['frames']} tracked frames {start}; "
                     f"image residual {fitted['rmsPx']:.2f} px.")
            # Fit uncertainty excludes lens and ground-tag calibration error.
            speed_reason = f"{basis} Fit ±{fitted['speedSigmaMps']:.2f} m/s. Requires reference validation."
            direction_reason = f"{basis} Fit ±{fitted['headingSigmaDeg']:.1f}°. Requires reference validation."
            if fit["model"] == "ground":
                result["groundRoll"] = {"model": "trajectory-ground", "flightLaunchDeg": fitted["flightLaunchDeg"],
                                        "flightLaunchSigmaDeg": fitted["flightLaunchSigmaDeg"]}
                launch = 0.0
                launch_reason = (f"Ball stayed on the ground: a flight model did not explain the image track better "
                                 f"than a roll (flight estimate {fitted['flightLaunchDeg']:.1f}° ±"
                                 f"{fitted['flightLaunchSigmaDeg']:.1f}°). {basis} Requires reference validation.")
            else:
                launch = math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1])))
                launch_reason = f"{basis} Fit ±{fitted['launchSigmaDeg']:.1f}°. Requires reference validation."
        else:
            track, outgoing, velocity, launch, speed_reason, launch_reason, impact_index = silhouette_launch(
                frames, bounds, impact_index, motion_track, matrix, distortion, rotation, translation, diagnostics, result)
            direction_reason = speed_reason
            grading["guided"] = "guided" in diagnostics
            result["ballTrack3d"] = track
            result["estimatedImpactFrameIndex"] = impact_index
        speed = float(np.linalg.norm(velocity))
        if not 0.1 <= speed <= 100:
            raise ValueError(f"Ball speed {speed:.1f} m/s is outside the supported 0.1-100 m/s range.")
        if speed * exposure_us / 1e6 > MAX_MOTION_BLUR_M:
            # A smeared ball still yields a usable (if noisier) speed and launch; mark
            # them lower-confidence instead of throwing the whole shot away.
            result["warnings"].append(
                f"Ball smeared {(speed * exposure_us / 1e6 * 1000):.1f} mm during the {exposure_us} µs exposure "
                f"(limit {MAX_MOTION_BLUR_M * 1000:.0f} mm); speed and launch are lower-confidence estimates.")
            grading["blurExceeded"] = True
        put("ballSpeedMps", speed, speed_reason)
        put("launchAngleDeg", launch, launch_reason)
        if launch <= 0:
            put("estimatedCarryM", 0, "No positive launch; modeled air carry is zero.")
        # Speed and launch angle do not care which way the tag is rotated; only the
        # start direction needs a reference line, always the bottom camera axis.
        target = target_rotation(heading)
        if heading is None:
            metrics["startDirectionDeg"]["reason"] = (
                "The camera is rolled too close to portrait for its across-image axis to define a target "
                "line. Level the monitor and recalibrate the ground plane.")
        else:
            aligned = target @ velocity
            result["targetLineHeadingDeg"] = round(math.degrees(heading), 3)
            result["targetLineSource"] = heading_source
            put("startDirectionDeg", -math.degrees(math.atan2(aligned[1], aligned[0])),
                f"{direction_reason} {target_line_note(heading, heading_source, pose.get('source'))}")
        measure_spin(frames, outgoing, matrix, distortion, rotation, translation, result, put, target)
        measure_roll(frames, track, result, put)
        club_upper = None
        if secondary_frames and pose.get("source") in BALL_GROUNDED_SOURCES:
            from stereo_check import is_staggered
            if is_staggered(frames, secondary_frames):
                # Two-view club triangulation pairs frames as one instant; the club moves too far in half a
                # frame for that. The lower-camera club track still runs; a staggered club fit comes later.
                diagnostics["clubStereo"] = {"used": False, "failure": "Staggered capture: club stereo needs simultaneous views."}
            else:
                try:
                    size = secondary_frames[0][1].shape[1], secondary_frames[0][1].shape[0]
                    upper_matrix, upper_distortion, upper_pose, _ = secondary_camera(
                        (matrix, distortion, rotation, translation), size, ground_id, tag_size, pose.get("capturedAt"),
                        surface_offset)
                    club_upper = (secondary_frames, (upper_matrix, upper_distortion,
                                                     upper_pose["rotation"], upper_pose["translation"]))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    diagnostics["clubStereo"] = {"used": False, "failure": str(error)}
        measure_club(frames, impact_index, matrix, distortion, rotation, translation, track, result, put,
                     ball_background(frames, impact_index), bounds, velocity, heading, club_upper)
    except (OSError, ValueError, KeyError, TypeError, cv2.error, np.linalg.LinAlgError) as error:
        result["failure"] = str(error)
        for metric in metrics.values():
            if metric["value"] is None:
                metric["reason"] = str(error)
    for key in ("spinRpm", "spinAxisDeg"):
        if metrics[key]["value"] is None:
            metrics[key]["reason"] = "Needs at least three resolved surface marks and two consistent small-rotation frame pairs; increase magnification/frame rate."
    if metrics["rollDistanceM"]["value"] is None:
        metrics["rollDistanceM"]["reason"] = "Requires continuous in-frame tracking until a verified stop (at least 100 ms)."
    if metrics["skidDistanceM"]["value"] is None:
        metrics["skidDistanceM"]["reason"] = "Requires simultaneous translation and spin tracking through transition to true roll."
    if pose_note:
        for metric in metrics.values():
            if metric["value"] is not None and pose_note not in metric["reason"]:
                metric["reason"] = f"{metric['reason']} {pose_note}"
    grade_metrics(result, grading)
    evidence = shot_evidence(result)
    if evidence:
        result["shotEvidence"] = evidence
    return result


def surface_vectors(pixels, center, matrix, distortion):
    rays = cv2.undistortPoints(np.asarray(pixels, np.float64).reshape(-1, 1, 2), matrix, distortion).reshape(-1, 2)
    rays = np.column_stack((rays, np.ones(len(rays))))
    rays /= np.linalg.norm(rays, axis=1)[:, None]
    projection = rays @ center
    discriminant = projection ** 2 - (center @ center - RADIUS ** 2)
    valid = discriminant > 0
    points = rays * (projection - np.sqrt(np.maximum(0, discriminant)))[:, None]
    return (points - center) / RADIUS, valid


def rotation_between(first, second):
    u, _, vh = np.linalg.svd(first.T @ second)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(vh.T @ u.T)
    return vh.T @ correction @ u.T


def measure_spin(frames, track, matrix, distortion, world_rotation, world_translation, result, put, target=None):
    target = np.eye(3) if target is None else target
    rates = []
    samples = []
    for first, second in zip(track, track[1:]):
        i, j = first["frameIndex"], second["frameIndex"]
        if j != i + 1:
            continue
        a, b = frames[i][1], frames[j][1]
        if a.ndim == 3:
            a, b = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        ca = world_rotation @ first["positionM"] + world_translation
        cb = world_rotation @ second["positionM"] + world_translation
        radius_px = matrix[0, 0] * RADIUS / ca[2]
        if radius_px < 12:
            continue
        mask = np.zeros_like(a)
        cv2.circle(mask, tuple(np.round(first["centerPx"]).astype(int)), int(radius_px * 0.75), 255, -1)
        features = cv2.goodFeaturesToTrack(a, maxCorners=40, qualityLevel=0.03, minDistance=3, mask=mask)
        if features is None or len(features) < 3:
            continue
        guess = features + np.array(second["centerPx"], np.float32) - np.array(first["centerPx"], np.float32)
        moved, good, _ = cv2.calcOpticalFlowPyrLK(a, b, features, guess, flags=cv2.OPTFLOW_USE_INITIAL_FLOW, winSize=(15, 15), maxLevel=2)
        if moved is None:
            continue
        reverse, back, _ = cv2.calcOpticalFlowPyrLK(b, a, moved, None, winSize=(15, 15), maxLevel=2)
        if reverse is None:
            continue
        va, valid_a = surface_vectors(features, ca, matrix, distortion)
        vb, valid_b = surface_vectors(moved, cb, matrix, distortion)
        valid = good.flatten().astype(bool) & back.flatten().astype(bool) & valid_a & valid_b & (np.linalg.norm(reverse - features, axis=2).flatten() < 0.7)
        va, vb = va[valid], vb[valid]
        if len(va) < 3 or np.linalg.svd(va, compute_uv=False)[-1] < 0.05:
            continue
        rotation = rotation_between(va, vb)
        if np.median(np.linalg.norm(va @ rotation.T - vb, axis=1)) > 0.06:
            continue
        vector = cv2.Rodrigues(rotation)[0].flatten()
        if np.linalg.norm(vector) > math.pi / 3:
            continue  # Ambiguous rotation/feature correspondence at this frame rate.
        rate = target @ world_rotation.T @ vector / (frames[j][0] - frames[i][0])
        rates.append(rate)
        samples.append({"frameIndex": i, "nextFrameIndex": j, "angularVelocityRadS": rate.tolist()})
    result["spinSamples"] = samples
    if len(rates) < 2:
        return
    rate = np.median(rates, axis=0)
    if np.max(np.linalg.norm(np.asarray(rates) - rate, axis=1)) > max(10, np.linalg.norm(rate) * 0.25):
        return
    put("spinRpm", -rate[1] * 60 / (2 * math.pi), "Surface-feature sphere rotation estimate; signed backspin, negative for topspin.")
    put("spinAxisDeg", math.degrees(math.atan2(rate[2], -rate[1])), "Spin axis from tracked surface marks; positive sidespin curves left.")


def measure_roll(frames, track, result, put):
    if len(track) < 3:
        return
    positions = np.asarray([p["positionM"] for p in track])
    indexes = [p["frameIndex"] for p in track]
    times = np.array([frames[i][0] for i in indexes])
    if np.any(np.diff(indexes) != 1) or np.max(np.abs(positions[:, 2] - RADIUS)) > .008:
        return
    stopped = times >= times[-1] - .1
    if np.count_nonzero(stopped) >= 3 and times[-1] - times[stopped][0] >= .09 and np.ptp(positions[stopped], axis=0).max() < .003:
        put("rollDistanceM", np.linalg.norm(positions[-1, :2] - positions[0, :2]), "Estimated straight-line ground distance from stationary placement to observed stop.")
    rolling_streak = 0
    for sample in result.get("spinSamples", []):
        i = sample["frameIndex"]
        if i not in indexes or sample["nextFrameIndex"] not in indexes:
            rolling_streak = 0
            continue
        n = indexes.index(i)
        if n + 1 >= len(track):
            continue
        velocity = (positions[n + 1] - positions[n]) / (times[n + 1] - times[n])
        omega = np.array(sample["angularVelocityRadS"])
        slip = np.linalg.norm((velocity + np.cross(omega, [0, 0, -RADIUS]))[:2])
        rolling_streak = rolling_streak + 1 if slip < max(.03, np.linalg.norm(velocity[:2]) * .1) else 0
        if rolling_streak >= 3:
            put("skidDistanceM", np.linalg.norm(positions[max(0, n - 2), :2] - positions[0, :2]), "Estimated ground displacement before three consecutive low-slip surface-rotation pairs.")
            break


def contact_ball_center(frames, impact_index, ball_track, ball_velocity, ball_pixel,
                        matrix, distortion, world_rotation, world_translation):
    """Where the ball was at contact, which is where the swing plane is pinned.

    The anchored trajectory fit returns only outgoing frames, so there is usually
    nothing before impact to average. Walking the fitted track back to the impact
    timestamp uses the best-determined geometry in the capture; the resting pixel
    on the ball-centre plane is the fallback when no fit survived.
    """
    stationary = [point for point in ball_track if point["frameIndex"] < impact_index]
    if stationary:
        return np.median([point["positionM"] for point in stationary], axis=0)
    outgoing = sorted((point for point in ball_track if 0 <= point["frameIndex"] < len(frames)),
                      key=lambda point: point["frameIndex"])
    if outgoing and 0 <= impact_index < len(frames) and ball_velocity is not None:
        first = outgoing[0]
        elapsed = frames[first["frameIndex"]][0] - frames[impact_index][0]
        return np.asarray(first["positionM"], float) - np.asarray(ball_velocity, float) * elapsed
    try:
        # A ball at rest on the ground has its centre one radius up, so the
        # horizontal plane through that height resolves the pixel without a track.
        return club_vision.plane_point(ball_pixel, matrix, distortion, world_rotation, world_translation,
                                       np.array([0.0, 0.0, RADIUS]), np.array([0.0, 0.0, 1.0]))
    except (ValueError, cv2.error):
        return None


def measure_club_tagless(frames, impact_index, matrix, distortion, world_rotation, world_translation,
                         ball_track, result, put, background, bounds, ball_velocity, heading, upper=None):
    """Club speed, path and attack angle from the head silhouette, with no club tag.

    Depth comes from a swing plane pinned to the known ball position, so the head
    only has to be segmented, not identified. Face contact additionally needs a
    one-off measured face size: a silhouette alone cannot say how wide a head is.
    """
    metrics = result["metrics"]
    motion_keys = ("clubSpeedMps", "smashFactor", "clubPathDeg", "attackAngleDeg")
    strike_keys = ("strikeXmm", "strikeYmm")
    if background is None or bounds is None or ball_velocity is None:
        for key in motion_keys + strike_keys:
            metrics[key]["reason"] = ("Tag-free club tracking needs the capture background and a fitted "
                                      "ball velocity; this capture resolved neither.")
        return
    diagnostics = result.setdefault("diagnostics", {})
    # A key that already carries its own explanation must not be overwritten by a
    # later, unrelated failure: "set the target line" is more use than "no profile".
    explained = set()
    x, y, box_width, box_height = bounds
    ball_pixel = np.array([x + box_width / 2, y + box_height / 2], float)
    ball_radius_px = min(box_width, box_height) / 2
    ball = contact_ball_center(frames, impact_index, ball_track, ball_velocity,
                               ball_pixel, matrix, distortion, world_rotation, world_translation)
    try:
        if ball is None:
            raise ValueError("Could not locate the ball at contact to pin the swing plane to.")
        normal, forward = club_vision.swing_plane(ball, ball_velocity)
        samples, shaft = club_vision.club_head_track(
            frames, impact_index, background, ball_pixel, ball_radius_px,
            matrix, distortion, world_rotation, world_translation, ball, normal)
        kept = club_vision.stable_samples(samples)
        diagnostics["clubSilhouette"] = {
            "method": "swing-plane-silhouette-v1", "candidateFrames": len(samples), "acceptedFrames": len(kept),
            "shaftAngleDeg": round(float(np.median(shaft)), 2) if shaft else None,
        }
        if len(kept) < club_vision.MIN_TRACK_FRAMES:
            raise ValueError(f"Resolved a steady clubhead silhouette in {len(kept)} consecutive frames "
                             f"({len(samples)} of the {club_vision.MAX_TRACK_FRAMES} frames before impact had one); "
                             f"at least {club_vision.MIN_TRACK_FRAMES} are required. The head is in view only "
                             "briefly before impact: more room behind the ball in the image gives it more frames.")
        velocity, residual = club_vision.fit_club_velocity(
            [frames[sample["frameIndex"]][0] for sample in kept], [sample["positionM"] for sample in kept])
        speed = float(np.linalg.norm(velocity))
        if not club_vision.MIN_CLUB_SPEED_MPS < speed < club_vision.MAX_CLUB_SPEED_MPS:
            raise ValueError(f"Tag-free club speed {speed:.1f} m/s is outside the supported range.")
        ball_speed = metrics["ballSpeedMps"]["value"]
        problem = club_vision.implausible_club(
            speed, ball_speed, math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1]))))
        if problem:
            raise ValueError(f"Tag-free (single-camera) track: {problem}")
        result["clubTrack3d"] = [{"frameIndex": sample["frameIndex"], "positionM": sample["positionM"].tolist()}
                                 for sample in kept]
        diagnostics["clubSilhouette"].update(fitResidualMm=round(residual * 1000, 1), speedMps=round(speed, 3))
        basis = (f"Clubhead silhouette back-projected onto the swing plane through the ball over "
                 f"{len(kept)} frames; fit residual {residual * 1000:.0f} mm. Assumes the head travels in "
                 f"the ball's outgoing vertical plane, since no club tag fixes its depth. "
                 f"Single-camera fallback: on real chips it read about 20% below the two-camera hosel track. "
                 f"Requires reference validation.")
        put("clubSpeedMps", speed, basis)
        if isinstance(ball_speed, (int, float)) and math.isfinite(ball_speed):
            put("smashFactor", ball_speed / speed, f"Ratio of the estimated ball and club speeds. {basis}")
        put("attackAngleDeg", math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1]))),
            f"Vertical angle of the fitted clubhead track; negative is descending. {basis}")
        # Club path is NOT recoverable this way. The swing plane is built from the ball's
        # own horizontal direction, so projecting the head onto it forces the head's
        # heading to equal the ball's exactly: the output would restate start direction
        # while looking like an independent measurement. Horizontal club direction needs
        # depth the silhouette cannot supply.
        metrics["clubPathDeg"]["reason"] = (
            "Not observable without a club tag or a second camera: the swing plane that gives the "
            "head its depth is defined by the ball's own direction, so any path from it would just "
            "restate start direction.")
        explained.add("clubPathDeg")
        contact = kept[-1]
        strike_x, strike_y, span = club_vision.face_contact(
            contact["headPx"], ball_pixel, ball_radius_px,
            _image_forward(kept), club_vision.load_club_profile())
        diagnostics["clubSilhouette"]["faceSpanMm"] = round(span, 1)
        reason = (f"Contact estimated in frame {contact['frameIndex']} using the ball's own {RADIUS * 2000:.1f} mm "
                  f"diameter as the scale reference and the saved face profile; measured face span "
                  f"{span:.0f} mm. Verify with impact tape.")
        put("strikeXmm", strike_x, reason)
        put("strikeYmm", strike_y, reason)
    except (ValueError, IndexError, np.linalg.LinAlgError, cv2.error) as error:
        for key in motion_keys + strike_keys:
            if metrics[key]["value"] is None and key not in explained:
                metrics[key]["reason"] = str(error)
    if upper is not None and ball is not None:
        measure_club_stereo(frames, impact_index, (matrix, distortion, world_rotation, world_translation),
                            upper, ball, result, put, heading)


def measure_club_stereo(frames, impact_index, lower_camera, upper, ball_center, result, put, heading):
    """Club speed, attack angle and path from the hosel triangulated in both cameras.

    Replaces the single-camera swing-plane values when it succeeds; strike location
    still comes from the silhouette path, which needs the face profile either way.
    """
    import club_stereo
    from stereo_check import _camera
    metrics = result["metrics"]
    diagnostics = result.setdefault("diagnostics", {})
    upper_frames, upper_camera = upper
    try:
        ball_speed = metrics["ballSpeedMps"]["value"]

        def implausible(velocity):
            speed = float(np.linalg.norm(velocity))
            if not club_vision.MIN_CLUB_SPEED_MPS < speed < club_vision.MAX_CLUB_SPEED_MPS:
                return f"club speed {speed:.1f} m/s is outside the supported range."
            return club_vision.implausible_club(speed, ball_speed, club_stereo.attack_angle_deg(velocity))

        stereo = club_stereo.measure(frames, upper_frames, impact_index, _camera(*lower_camera), _camera(*upper_camera),
                                     ball_background(frames, impact_index), ball_background(upper_frames, impact_index),
                                     np.asarray(ball_center, float), accept=implausible)
        velocity = np.asarray(stereo["velocity"], float)
        speed = float(np.linalg.norm(velocity))
    except (ValueError, IndexError, np.linalg.LinAlgError, cv2.error) as error:
        diagnostics["clubStereo"] = {"used": False, "failure": str(error), **getattr(error, "diagnostics", {})}
        for key in ("clubSpeedMps", "smashFactor", "attackAngleDeg", "clubPathDeg"):
            if metrics[key]["value"] is None:
                metrics[key]["reason"] = f"Two cameras: {error} Single camera: {metrics[key]['reason']}"
        return
    info = stereo["diagnostics"]
    diagnostics["clubStereo"] = {"used": True, **info}
    result["clubTrack3d"] = [{"frameIndex": s["frameIndex"], "positionM": np.asarray(s["positionM"]).tolist()}
                             for s in stereo["track"]]
    point = "Club head centre" if info.get("point") == "head" else "Shaft/hosel point"
    basis = (f"{point} triangulated by both cameras in {info['acceptedFrames']} frames before impact "
             f"(median ray gap {info['medianRayGapMm']:.1f} mm, path residual {info['fitResidualMm']:.1f} mm, "
             f"{info['model']} fit). Measured at the hosel, which travels slightly slower than the face centre. "
             "Requires reference validation.")
    put("clubSpeedMps", speed, basis)
    if isinstance(ball_speed, (int, float)) and math.isfinite(ball_speed):
        put("smashFactor", ball_speed / speed, f"Ratio of the estimated ball and club speeds. {basis}")
    put("attackAngleDeg", club_stereo.attack_angle_deg(velocity),
        f"Vertical angle of the hosel's velocity at the last frame before impact; negative is descending. {basis}")
    if heading is not None:
        aligned = target_rotation(heading) @ velocity
        put("clubPathDeg", -math.degrees(math.atan2(aligned[1], aligned[0])),
            f"Horizontal direction of the hosel relative to the target line, same sign as start direction. {basis}")


def _image_forward(samples):
    """Unit image-space direction the head is travelling, from the accepted track."""
    delta = np.asarray(samples[-1]["centroidPx"], float) - np.asarray(samples[0]["centroidPx"], float)
    length = float(np.linalg.norm(delta))
    if length < 1e-6:
        raise ValueError("Clubhead silhouette did not move measurably across the accepted frames.")
    return delta / length


def measure_club(frames, impact_index, matrix, distortion, world_rotation, world_translation, ball_track, result, put,
                 background=None, bounds=None, ball_velocity=None, heading=None, upper=None):
    path = Path(os.getenv("PINPOINT_CLUB_MARKER_PATH", "/var/lib/pinpoint/club-marker.json"))
    if not path.exists():
        # No club tag means no PnP scale. The silhouette path borrows scale from the
        # ground plane and the ball instead, and labels everything it returns.
        measure_club_tagless(frames, impact_index, matrix, distortion, world_rotation, world_translation,
                             ball_track, result, put, background, bounds, ball_velocity, heading, upper)
        return
    config = json.loads(path.read_text())
    result["clubId"] = config.get("clubId")
    center = np.asarray(config["faceCenterM"], float)
    axes = np.asarray(config["faceAxes"], float)  # columns: toe, high, outward normal
    if center.shape != (3,) or axes.shape != (3, 3) or not np.allclose(axes.T @ axes, np.eye(3), atol=0.001) or np.linalg.det(axes) < .999 or not np.all(np.isfinite(center)):
        raise ValueError("Invalid club face transform.")
    if config["tagSizeMm"] <= 0 or config["tagId"] == int(os.getenv("PINPOINT_APRILTAG_ID", "0")):
        raise ValueError("Club tag must have positive size and a different ID from the ground tag.")
    club = []
    for i in range(max(0, impact_index - 16), impact_index + 1):
        tags = marker_map(frames[i][1])
        if config["tagId"] not in tags:
            continue
        rotation, translation = tag_pose(tags[config["tagId"]], config["tagSizeMm"] / 1000, matrix, distortion)
        world_center = world_rotation.T @ (rotation @ center + translation - world_translation)
        world_axes = world_rotation.T @ rotation @ axes
        club.append((i, world_center, world_axes))
    result["clubTrack3d"] = [{"frameIndex": i, "positionM": p.tolist()} for i, p, _ in club]
    if len(club) < 3:
        raise ValueError("Club tag needs at least three resolved pre-impact poses.")
    last = club[-5:]
    velocity, _ = fit_velocity([frames[i][0] for i, _, _ in last], [p for _, p, _ in last])
    speed = float(np.linalg.norm(velocity))
    if not 0.1 < speed < 80:
        raise ValueError("Club speed is outside supported range.")
    put("clubSpeedMps", speed, "Rigid club-tag pose and calibrated face-center offset.")
    put("smashFactor", result["metrics"]["ballSpeedMps"]["value"] / speed, "Ratio of estimated ball and club speeds.")
    # The tag resolves the head's depth on its own, so unlike the silhouette path this
    # direction is independent of the ball's and is worth reporting.
    put("attackAngleDeg", math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1]))),
        "Vertical angle of the club-tag track; negative is descending.")
    if heading is not None:
        aligned = target_rotation(heading) @ velocity
        put("clubPathDeg", -math.degrees(math.atan2(aligned[1], aligned[0])),
            "Horizontal club-tag direction relative to the target line.")
    stationary = [p for p in ball_track if p["frameIndex"] < impact_index]
    if not stationary:
        return
    ball = np.median([p["positionM"] for p in stationary], axis=0)
    i, face, axes = last[-1]
    # Extrapolate for at most one sensor interval; reject unsupported contact geometry.
    dt = frames[impact_index][0] - frames[i][0]
    if dt < 0 or dt > 0.01:
        return
    relative = axes.T @ (ball - (face + velocity * dt))
    if abs(abs(relative[2]) - RADIUS) > 0.01 or abs(relative[0]) > 0.06 or abs(relative[1]) > 0.04:
        return
    put("strikeXmm", relative[0] * 1000, "Club-face contact estimate at ball departure; verify with impact tape.")
    put("strikeYmm", relative[1] * 1000, "Club-face contact estimate at ball departure; verify with impact tape.")
