"""AprilTag-referenced monocular launch estimates. All distances internally in metres.

World +X follows the tag's top edge (target), +Y points left, +Z up.
Single-view sphere depth is sensitive to silhouette errors; never label it measured 3D.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import cv2
import numpy as np

import club_vision
from target_line import target_heading_rad

RADIUS = 0.021335
STRICT_TAG_POSE_ERROR_PX = 1.0
MAX_ESTIMATED_TAG_POSE_ERROR_PX = 3.0
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
TRAJECTORY_MIN_FRAMES = 6
TRAJECTORY_MAX_FRAMES = 48
TRAJECTORY_CENTER_SIGMA_PX = 0.5
TRAJECTORY_RADIUS_SIGMA_PX = 1.5
TRAJECTORY_MAX_RMS_PX = 3.0
TRAJECTORY_HUBER = 2.0
TRAJECTORY_MAX_ROLL_DECELERATION = 10.0
METRICS = {
    "ballSpeedMps": "m/s", "clubSpeedMps": "m/s", "smashFactor": "",
    "launchAngleDeg": "deg", "startDirectionDeg": "deg", "strikeXmm": "mm",
    "strikeYmm": "mm", "spinRpm": "rpm", "spinAxisDeg": "deg",
    "estimatedCarryM": "m", "rollDistanceM": "m", "skidDistanceM": "m",
    "clubPathDeg": "deg", "attackAngleDeg": "deg",
}


def unavailable(reason):
    return {key: {"value": None, "unit": unit, "status": "unavailable", "reason": reason} for key, unit in METRICS.items()}


def load_setup(image_size):
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


def ground_pose_calibration(detection):
    """Save pose and exact lens inputs from an explicitly captured ground tag."""
    image_size = detection.get("imageSize")
    if not isinstance(image_size, list) or len(image_size) != 2:
        raise ValueError("Ground-tag image size missing; capture a fresh calibration.")
    matrix, distortion = load_setup(image_size)
    corners = np.asarray(detection.get("corners"), dtype=float)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError("Ground-tag corners missing; capture a fresh calibration.")
    size = float(detection["tagSizeMm"]) / 1000
    rotation, translation, error = solve_tag_pose(corners * np.asarray(image_size), size, matrix, distortion)
    if error > MAX_ESTIMATED_TAG_POSE_ERROR_PX:
        raise ValueError("Ground-tag pose error exceeds 3 pixels; improve calibration image.")
    return {"version": 1, "imageSize": image_size, "cameraMatrix": matrix.tolist(),
            "distCoeffs": distortion.tolist(), "rotation": rotation.tolist(),
            "translationM": translation.tolist(), "errorPx": error}


def stored_ground_pose(image_size, ground_id, size, matrix, distortion):
    from apriltag_calibration import load_apriltag_calibration
    saved = load_apriltag_calibration()
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
        return {"rotation": rotation, "translation": translation, "errorPx": error,
                "frameIndex": None, "source": "stored-calibration", "capturedAt": saved.get("capturedAt")}
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
    parameters = cv2.aruco.DetectorParameters()
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
                         "define a target line. Level the monitor, or set the target line by rolling a ball.")
    return math.atan2(right[1], right[0])


def target_line_note(heading, source):
    """State which reference the angle is measured against; the two are not interchangeable."""
    if source == "camera-axis":
        return (f"Measured against the camera's across-image axis ({math.degrees(heading):.1f}° from the tag), "
                f"which assumes the monitor is squared to the target.")
    return f"Measured against the saved rolled-ball target line ({math.degrees(heading):.1f}° from the tag)."


def resolve_target_heading(rotation):
    """Explicit rolled-ball line if one is saved, otherwise the camera's across-image axis."""
    heading = target_heading_rad()
    if heading is not None:
        return heading, "rolled-ball"
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
    return min(candidates, key=lambda candidate: candidate["errorPx"]) if candidates else None


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
    observations = []
    for index, center in run:
        radius = None
        nearby = [(np.linalg.norm(found - center), contour) for found, contour in
                  ball_contours(frames[index][1], background, seed_radius, minimum_fill=GUIDED_BALL_FILL)]
        nearby = [item for item in nearby if item[0] <= seed_radius * 0.5]
        if nearby:
            radius = float(cv2.minEnclosingCircle(min(nearby, key=lambda item: item[0])[1])[1])
        observations.append({"frameIndex": index, "centerPx": center.tolist(), "radiusPx": radius})
    first_time = frames[run[0][0]][0]
    interval = float(np.median(np.diff([t for t, _ in frames])))
    # The ball cannot leave before it was last seen resting.
    lower = frames[resting[-1][0]][0] if resting and resting[-1][0] < run[0][0] else first_time - 2 * interval
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
                np.array([o["radiusPx"] is not None for o in obs]), np.array([o["radiusPx"] or 0.0 for o in obs]))

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
        times, centers, mask, radii = data
        pixels, radius = predicted(positions(model, params, times))
        values = np.concatenate((((pixels - centers) / TRAJECTORY_CENTER_SIGMA_PX).ravel(),
                                 (radius - radii)[mask] / TRAJECTORY_RADIUS_SIGMA_PX))
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
        planar = [ground_point(c, matrix, distortion, rotation, translation) for c in centers[:12]]
        if any(point is None for point in planar):
            raise ValueError("Tracked ball rays do not meet the ground plane.")
        planar = np.asarray(planar, dtype=float)
        design = np.column_stack((times[:len(planar)] - times[0], np.ones(len(planar))))
        slope, intercept = np.linalg.lstsq(design, planar[:, :2], rcond=None)[0]
        if model == "ground-free":
            return np.array([slope[0], slope[1], 0.0, intercept[0], intercept[1]])
        start = upper - np.linalg.norm(intercept - anchor[:2]) / max(float(np.linalg.norm(slope)), 1e-3)
        return np.array([slope[0], slope[1], 0.0, float(np.clip(start, lower, upper))])

    def solve(model, obs):
        data = unpack(obs)
        params = initial_guess(model, data)
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
        free_ok = free["rms"] <= TRAJECTORY_MAX_RMS_PX and abs(float(free["params"][2])) <= TRAJECTORY_MAX_ROLL_DECELERATION
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
    times, _, mask, radii = unpack(used)
    fitted = positions(model, params, times)
    _, radius = predicted(fitted)
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


def measure_launch(frames, bounds, impact_index, timestamp_source="host", exposure_us=None, motion_track=None):
    result = {"metrics": unavailable("Needs a calibrated ball/club track."), "ballTrack3d": [], "clubTrack3d": [], "warnings": [], "method": "apriltag-monocular-sphere-v1"}
    diagnostics = {"version": 1, "frameCount": len(frames), "motionTrackedFrames": sum(
        1 for point in motion_track or []
        if isinstance(point.get("frameIndex"), int) and impact_index <= point["frameIndex"] < len(frames)
    ), "strict": {"candidateFrames": 0, "distortedOutlines": 0, "invalidDepth": 0, "acceptedFrames": 0}}
    result["diagnostics"] = diagnostics
    metrics = result["metrics"]
    pose_note = None
    def put(key, value, reason, status="estimated"):
        if math.isfinite(value):
            metrics[key] = {"value": round(float(value), 4), "unit": METRICS[key], "status": status, "reason": reason}
    try:
        if timestamp_source != "sensor":
            raise ValueError("Sensor timestamps required; host arrival timing cannot measure launch speed.")
        if len(frames) < 3 or not np.all(np.isfinite([t for t, _ in frames])) or np.any(np.diff([t for t, _ in frames]) <= 0):
            raise ValueError("Capture has missing or non-increasing sensor timestamps.")
        if exposure_us is None or not 0 < exposure_us <= 250:
            raise ValueError("Use fixed exposure at or below 250 us and adequate lighting; faster shots may require shorter exposure.")
        height, width = frames[0][1].shape[:2]
        matrix, distortion = load_setup((width, height))
        ground_id = int(os.getenv("PINPOINT_APRILTAG_ID", "0"))
        tag_size = float(os.getenv("PINPOINT_APRILTAG_SIZE_MM", "100")) / 1000
        # Preserve the actual inputs used for this analysis. Later recalibration
        # must not silently change an offline replay of an older capture.
        diagnostics["calibration"] = {"imageSize": [width, height], "cameraMatrix": matrix.tolist(),
                                      "distCoeffs": distortion.tolist(), "groundTagId": ground_id,
                                      "groundTagSizeMm": tag_size * 1000}
        pose = stored_ground_pose((width, height), ground_id, tag_size, matrix, distortion)
        if pose is None:
            pose = find_ground_tag_pose(frames, impact_index, ground_id, tag_size, matrix, distortion)
        if pose is None:
            raise ValueError("Capture ground AprilTag calibration first, or keep the tag visible in this burst.")
        rotation, translation, pose_error = pose["rotation"], pose["translation"], pose["errorPx"]
        # The camera axis can only supply a target line once its pose is known, so this
        # is resolved here rather than alongside the other calibration inputs above.
        heading, heading_source = resolve_target_heading(rotation)
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
        if pose_error > MAX_ESTIMATED_TAG_POSE_ERROR_PX:
            raise ValueError(
                f"Ground AprilTag pose reprojection error {pose_error:.2f} px exceeds "
                f"the {MAX_ESTIMATED_TAG_POSE_ERROR_PX:.1f} px estimation limit."
            )
        pose_note = (f"Stored ground calibration ({pose.get('capturedAt')}), pose error {pose_error:.2f} px; camera must remain fixed."
                     if pose.get("source") == "stored-calibration" else
                     f"Ground-tag pose error {pose_error:.2f} px from frame {pose['frameIndex']}.")
        if pose_error > STRICT_TAG_POSE_ERROR_PX:
            result["warnings"].append(
                f"Ground AprilTag pose reprojection error is {pose_error:.2f} px; "
                "launch values are lower-confidence estimates."
            )
        fit = None
        if motion_track:
            try:
                rest_px, time_bounds, observations = trajectory_observations(
                    frames, bounds, impact_index, motion_track, ball_background(frames, impact_index))
                fit = fit_trajectory(frames, rest_px, time_bounds, observations, matrix, distortion, rotation, translation)
            except (ValueError, np.linalg.LinAlgError, cv2.error) as error:
                diagnostics["trajectoryFit"] = {"failure": str(error)}
        if fit is not None:
            fitted = fit["diagnostics"]
            diagnostics["trajectoryFit"] = fitted
            track = outgoing = fit["track"]
            velocity = fit["velocity"]
            impact_index = fit["impactFrameIndex"]
            result["ballTrack3d"] = track
            result["estimatedImpactFrameIndex"] = impact_index
            start = ("from the resting ball" if fitted["startPoint"] == "resting-ball" else
                     f"with its ground start re-estimated {fitted['startOffsetMm']:.0f} mm from the resting ball (moved before release)")
            basis = (f"Anchored trajectory fit to {fitted['frames']} tracked frames {start}; "
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
            result["ballTrack3d"] = track
            result["estimatedImpactFrameIndex"] = impact_index
        speed = float(np.linalg.norm(velocity))
        if not 0.1 <= speed <= 100:
            raise ValueError(f"Ball speed {speed:.1f} m/s is outside the supported 0.1-100 m/s range.")
        if speed * exposure_us / 1e6 > 0.004:
            raise ValueError("Estimated motion blur exceeds 4 mm; shorten exposure for this shot speed.")
        put("ballSpeedMps", speed, speed_reason)
        put("launchAngleDeg", launch, launch_reason)
        # Speed and launch angle do not care which way the tag is rotated; only the
        # start direction needs a reference line, and that comes from the camera axis
        # unless a rolled-ball line was saved.
        target = target_rotation(heading)
        if heading is None:
            metrics["startDirectionDeg"]["reason"] = (
                "The camera is rolled too close to portrait for its across-image axis to define a target "
                "line. Level the monitor, or roll a ball toward the target and use Set target line.")
        else:
            aligned = target @ velocity
            result["targetLineHeadingDeg"] = round(math.degrees(heading), 3)
            result["targetLineSource"] = heading_source
            put("startDirectionDeg", -math.degrees(math.atan2(aligned[1], aligned[0])),
                f"{direction_reason} {target_line_note(heading, heading_source)}")
        put("estimatedCarryM", max(0, speed ** 2 * math.sin(2 * math.radians(launch)) / 9.80665), "Vacuum ballistic estimate to launch height; excludes lift, drag, wind and terrain.")
        measure_spin(frames, outgoing, matrix, distortion, rotation, translation, result, put, target)
        measure_roll(frames, track, result, put)
        measure_club(frames, impact_index, matrix, distortion, rotation, translation, track, result, put,
                     ball_background(frames, impact_index), bounds, velocity, heading)
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
    if len(track) < 5:
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
                         ball_track, result, put, background, bounds, ball_velocity, heading):
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
            raise ValueError(f"Resolved the clubhead silhouette in {len(kept)} of the "
                             f"{club_vision.MAX_TRACK_FRAMES} frames before impact; at least "
                             f"{club_vision.MIN_TRACK_FRAMES} are required. Improve lighting on the club.")
        velocity, residual = club_vision.fit_club_velocity(
            [frames[sample["frameIndex"]][0] for sample in kept], [sample["positionM"] for sample in kept])
        speed = float(np.linalg.norm(velocity))
        if not club_vision.MIN_CLUB_SPEED_MPS < speed < club_vision.MAX_CLUB_SPEED_MPS:
            raise ValueError(f"Tag-free club speed {speed:.1f} m/s is outside the supported range.")
        result["clubTrack3d"] = [{"frameIndex": sample["frameIndex"], "positionM": sample["positionM"].tolist()}
                                 for sample in kept]
        diagnostics["clubSilhouette"].update(fitResidualMm=round(residual * 1000, 1), speedMps=round(speed, 3))
        basis = (f"Clubhead silhouette back-projected onto the swing plane through the ball over "
                 f"{len(kept)} frames; fit residual {residual * 1000:.0f} mm. Assumes the head travels in "
                 f"the ball's outgoing vertical plane, since no club tag fixes its depth. "
                 f"Requires reference validation.")
        put("clubSpeedMps", speed, basis)
        ball_speed = metrics["ballSpeedMps"]["value"]
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


def _image_forward(samples):
    """Unit image-space direction the head is travelling, from the accepted track."""
    delta = np.asarray(samples[-1]["centroidPx"], float) - np.asarray(samples[0]["centroidPx"], float)
    length = float(np.linalg.norm(delta))
    if length < 1e-6:
        raise ValueError("Clubhead silhouette did not move measurably across the accepted frames.")
    return delta / length


def measure_club(frames, impact_index, matrix, distortion, world_rotation, world_translation, ball_track, result, put,
                 background=None, bounds=None, ball_velocity=None, heading=None):
    path = Path(os.getenv("PINPOINT_CLUB_MARKER_PATH", "/var/lib/pinpoint/club-marker.json"))
    if not path.exists():
        # No club tag means no PnP scale. The silhouette path borrows scale from the
        # ground plane and the ball instead, and labels everything it returns.
        measure_club_tagless(frames, impact_index, matrix, distortion, world_rotation, world_translation,
                             ball_track, result, put, background, bounds, ball_velocity, heading)
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
