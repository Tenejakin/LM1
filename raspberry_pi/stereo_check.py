"""Independent stereo cross-check of the single-camera launch fit.

The lower and top cameras are posed from the same ground AprilTag, so both live in
one world frame and need no separate stereo calibration. The ball's depth then comes
from triangulation instead of its apparent size, which is what the single-camera
ball-size check otherwise has to vouch for.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from launch_measurements import GRAVITY, RADIUS

# The top camera sees the ball on a curve fixed by the lower camera's ray; searching
# only near that curve keeps the club and feet from being matched instead.
EPIPOLAR_BAND_PX = 6
EPIPOLAR_DEPTHS_M = np.linspace(0.15, 2.5, 400)
MIN_MATCH_SCORE = 0.6
MIN_STEREO_FRAMES = 3
TWO_POINT_MAX_RELATIVE_SPEED_ERROR = 0.25
TWO_POINT_MAX_FRAME_GAP = 2
MEASURED_STEREO_FRAMES = 3
MIN_STEREO_TIME_SPAN_S = 0.008
MAX_CANDIDATE_RAY_GAP_MM = 6.0
MAX_CANDIDATE_RADIUS_ERROR = 0.35
MAX_CANDIDATE_PATH_ERROR_M = 0.035
REST_SEARCH_PX = 40
# The top camera's resting ball must sit where the lower camera's ground-plane
# assumption predicts; further away means the two poses do not describe one scene.
MAX_REST_PREDICTION_PX = 15.0
# Measured-grade gates.
MAX_RAY_GAP_MM = 3.0
MAX_REST_HEIGHT_ERROR_MM = 5.0
MAX_START_ANCHOR_ERROR_MM = 30.0
MAX_STEREO_RMS_PX = 3.0
MAX_PAIR_OFFSET_US = 250.0
MAX_SPEED_DIFFERENCE_PCT = 3.0
MAX_ANGLE_DIFFERENCE_DEG = 1.5


class StereoTrackingError(ValueError):
    """A failed stereo track with the frame evidence retained for review."""

    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def _camera(matrix, distortion, rotation, translation):
    rotation = np.asarray(rotation, float)
    translation = np.asarray(translation, float)
    return {"K": np.asarray(matrix, float), "D": np.asarray(distortion, float), "R": rotation, "t": translation,
            "rvec": cv2.Rodrigues(rotation)[0], "C": -rotation.T @ translation}


def _ray(camera, pixel):
    uv = cv2.undistortPoints(np.asarray([[pixel]], np.float64), camera["K"], camera["D"]).reshape(2)
    direction = camera["R"].T @ np.array([uv[0], uv[1], 1.0])
    return camera["C"], direction / np.linalg.norm(direction)


def _project(camera, points):
    points = np.asarray(points, np.float64).reshape(-1, 1, 3)
    return cv2.projectPoints(points, camera["rvec"], camera["t"], camera["K"], camera["D"])[0].reshape(-1, 2)


def _triangulate(first, second):
    """Midpoint of the shortest segment between two rays, and that segment's length."""
    (p, u), (q, v) = first, second
    w = p - q
    a, b, c, d, e = u @ u, u @ v, v @ v, u @ w, v @ w
    denominator = a * c - b * b
    if abs(denominator) < 1e-12:
        raise ValueError("Stereo rays are parallel.")
    s, r = (b * e - c * d) / denominator, (a * e - b * d) / denominator
    x, y = p + s * u, q + r * v
    return (x + y) / 2, float(np.linalg.norm(x - y))


def _two_point_speed(lower, upper, observations, rest_point, rest_gap, upper_rest, start_time,
                     detection, candidate_rejections, candidate_rejected_frames, skipped):
    """Estimate interval-average speed only; two points cannot validate a flight curve."""
    diagnostics = {"frames": 2, "frameIndices": [o["frameIndex"] for o in observations],
                   "candidateRejections": candidate_rejections,
                   "candidateRejectedFrames": candidate_rejected_frames, "detection": detection}
    first, second = observations
    span = second["lowerTime"] - first["lowerTime"]
    diagnostics["spanMs"] = round(span * 1000, 2)
    if second["frameIndex"] - first["frameIndex"] > TWO_POINT_MAX_FRAME_GAP or span < 0.003:
        raise StereoTrackingError("Two stereo points are too far apart or too close in time for an interval speed.", diagnostics)
    pair_offset = max(abs(o["upperTime"] - o["lowerTime"]) for o in observations) * 1e6
    diagnostics["maxPairOffsetUs"] = round(pair_offset, 2)
    if pair_offset > MAX_PAIR_OFFSET_US:
        raise StereoTrackingError("Camera-pair timing offset exceeds 250 µs for a two-point speed.", diagnostics)
    gaps = [o["rayGapMm"] for o in observations]
    diagnostics["maxRayGapMm"] = max(gaps)
    diagnostics["restHeightErrorMm"] = round((float(rest_point[2]) - RADIUS) * 1000, 2)
    if max(gaps) > MAX_RAY_GAP_MM or abs(diagnostics["restHeightErrorMm"]) > MAX_REST_HEIGHT_ERROR_MM or rest_gap * 1000 > MAX_RAY_GAP_MM:
        raise StereoTrackingError("Stereo rays or resting-ball calibration disagree for a two-point speed.", diagnostics)
    displacement = np.asarray(second["pointM"]) - np.asarray(first["pointM"])
    speed = float(np.linalg.norm(displacement) / span)
    diagnostics["speedMps"] = round(speed, 4)
    if not 0.1 <= speed <= 100:
        raise StereoTrackingError("Two-point ball speed is outside the supported range.", diagnostics)
    # Contact lies after the last still frame, not at an exact captured instant.
    # The resting ball therefore supplies a lower speed bound and a path check,
    # never a third equally timed velocity sample.
    rest_to_first = np.asarray(first["pointM"], float) - rest_point
    rest_interval = first["lowerTime"] - start_time
    if rest_interval <= 0:
        raise StereoTrackingError("Impact-to-first-ball timing is invalid.", diagnostics)
    lower_bound = float(np.linalg.norm(rest_to_first) / rest_interval)
    line_error = float(np.linalg.norm(np.cross(rest_to_first, displacement)) / max(np.linalg.norm(displacement), 1e-9))
    diagnostics["impactToFirstSpeedLowerBoundMps"] = round(lower_bound, 4)
    diagnostics["restToTrackLineErrorMm"] = round(line_error * 1000, 1)
    if speed < 0.8 * lower_bound or line_error > 0.03 or float(rest_to_first @ displacement) <= 0:
        raise StereoTrackingError("Two-point motion disagrees with the resting-ball impact-to-first-frame path.", diagnostics)
    # A one-pixel localization perturbation in either image bounds the speed
    # sensitivity. No trajectory residual can be estimated from just two points.
    position_errors = []
    for observation in observations:
        center = np.asarray(observation["pointM"], float)
        deviations = []
        for camera_name in ("lowerPx", "upperPx"):
            for axis in range(2):
                for offset in (-1., 1.):
                    pixels = {name: np.asarray(observation[name], float).copy() for name in ("lowerPx", "upperPx")}
                    pixels[camera_name][axis] += offset
                    point, _ = _triangulate(_ray(lower, pixels["lowerPx"]), _ray(upper, pixels["upperPx"]))
                    deviations.append(float(np.linalg.norm(point - center)))
        position_errors.append(max(deviations))
    relative_error = sum(position_errors) / max(float(np.linalg.norm(displacement)), 1e-9)
    diagnostics["speedUncertaintyPct"] = round(relative_error * 100, 1)
    if relative_error > TWO_POINT_MAX_RELATIVE_SPEED_ERROR:
        raise StereoTrackingError("Two-point speed is too sensitive to a one-pixel ball-centre error.", diagnostics)
    return {**diagnostics, "method": "shared-tag-stereo-two-point-v1", "speedOnly": True,
            "model": "two-point", "speedMps": round(speed, 4),
            "speedSigmaMps": round(speed * relative_error, 4),
            "medianRayGapMm": round(float(np.median(gaps)), 2),
            "restRayGapMm": round(rest_gap * 1000, 2),
            "upperRestPx": [round(float(v), 2) for v in upper_rest],
            "skippedFrames": skipped,
            "track": [{"frameIndex": o["frameIndex"], "centerPx": o["lowerPx"], "upperPx": o["upperPx"],
                       "score": o["score"], "rayGapMm": o["rayGapMm"], "positionM": o["pointM"]}
                      for o in observations]}


def _gray(frame):
    image = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return image.astype(np.float32)


def _subpixel_peak(score, x, y):
    dx = dy = 0.0
    if 0 < x < score.shape[1] - 1:
        left, centre, right = score[y, x - 1:x + 2]
        curvature = left - 2 * centre + right
        dx = 0.5 * (left - right) / curvature if curvature else 0.0
    if 0 < y < score.shape[0] - 1:
        up, centre, down = score[y - 1:y + 2, x]
        curvature = up - 2 * centre + down
        dy = 0.5 * (up - down) / curvature if curvature else 0.0
    return float(np.clip(dx, -0.5, 0.5)), float(np.clip(dy, -0.5, 0.5))


def _rest_template(upper, images, rest_indices, empty_indices, predicted):
    """Locate the resting ball in the top view and cut a matching template around it."""
    still = np.median([images(i) for i in rest_indices], axis=0)
    empty = np.median([images(i) for i in empty_indices], axis=0)
    difference = cv2.GaussianBlur(np.abs(still - empty), (5, 5), 0)
    x0, y0 = (int(round(v)) for v in predicted)
    height, width = difference.shape
    left, top = max(0, x0 - REST_SEARCH_PX), max(0, y0 - REST_SEARCH_PX)
    window = difference[top:min(height, y0 + REST_SEARCH_PX), left:min(width, x0 + REST_SEARCH_PX)]
    if window.size == 0 or window.max() <= 0:
        raise ValueError("Resting ball is outside the top camera's view.")
    mask = (window > 0.5 * window.max()).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        raise ValueError("Resting ball not found in the top camera.")
    blob = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    found = centroids[blob] + [left, top]
    half = int(math.ceil(math.sqrt(stats[blob, cv2.CC_STAT_AREA] / math.pi))) + 4
    # The difference blob can be lopsided where a moving club overlaps the ball.
    # A circle fit on the median resting image gives the actual sphere centre.
    circles = _circle_candidates(still, half)
    nearby = [circle for circle in circles if np.linalg.norm(circle[:2] - predicted) <= MAX_REST_PREDICTION_PX]
    if nearby:
        circle = min(nearby, key=lambda item: np.linalg.norm(item[:2] - predicted))
        found = circle[:2].astype(float)
        half = max(half, int(math.ceil(circle[2])) + 4)
    if np.linalg.norm(found - predicted) > MAX_REST_PREDICTION_PX:
        raise ValueError(f"Top camera sees the resting ball {np.linalg.norm(found - predicted):.0f} px from where the "
                         "ground calibration puts it; recalibrate both cameras with the AprilTag.")
    cx, cy = (int(round(v)) for v in found)
    if cx - half < 0 or cy - half < 0 or cx + half >= width or cy + half >= height:
        raise ValueError("Resting ball is too close to the top camera's edge.")
    return found, still[cy - half:cy + half + 1, cx - half:cx + half + 1], half


def _match_on_epipolar(lower, upper, image, template, half, lower_pixel):
    origin, direction = _ray(lower, lower_pixel)
    curve = _project(upper, origin + np.outer(EPIPOLAR_DEPTHS_M, direction))
    height, width = image.shape
    curve = curve[(curve[:, 0] > -half) & (curve[:, 0] < width + half) & (curve[:, 1] > -half) & (curve[:, 1] < height + half)]
    if not len(curve):
        return None, 0.0
    # Match only inside the band's bounding box; the template's top-left is offset by half.
    margin = half + EPIPOLAR_BAND_PX + 1
    left = int(max(0, np.floor(curve[:, 0].min()) - margin))
    top = int(max(0, np.floor(curve[:, 1].min()) - margin))
    right = int(min(width, np.ceil(curve[:, 0].max()) + margin))
    bottom = int(min(height, np.ceil(curve[:, 1].max()) + margin))
    if right - left <= template.shape[1] or bottom - top <= template.shape[0]:
        return None, 0.0
    score = cv2.matchTemplate(image[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
    band = np.zeros(score.shape, np.uint8)
    for x, y in curve:
        cv2.circle(band, (int(round(x - half - left)), int(round(y - half - top))), EPIPOLAR_BAND_PX, 1, -1)
    masked = np.where(band > 0, score, -1.0)
    y, x = np.unravel_index(int(np.argmax(masked)), masked.shape)
    dx, dy = _subpixel_peak(score, x, y)
    return np.array([x + dx + half + left, y + dy + half + top]), float(score[y, x])


def _circle_candidates(image, rest_radius, *, sensitive=False):
    """Find ball-sized circular edges without relying on either camera's track."""
    blurred = cv2.GaussianBlur(image.astype(np.uint8), (5, 5), 1.2)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.0,
        minDist=max(12, int(rest_radius)), param1=75, param2=22 if sensitive else 25,
        minRadius=max(5, int(rest_radius * 0.45)),
        maxRadius=max(8, int(rest_radius * 1.65)),
    )
    return [] if circles is None else circles[0]


def _independent_observations(lower, upper, lower_frames, upper_frames, rest_point, rest_end):
    """Pair independently found circles using calibrated rays and a smooth 3D path."""
    observations = []
    rejected = {"noCircle": 0, "noGeometricPair": 0, "pathMismatch": 0}
    rejected_frames = []

    def reject(index, reason):
        rejected[reason] += 1
        rejected_frames.append({"frameIndex": index, "reason": reason})

    start_time = lower_frames[rest_end][0]
    rest_radii = [RADIUS * camera["K"][0, 0] / (camera["R"] @ rest_point + camera["t"])[2]
                  for camera in (lower, upper)]
    for index in range(rest_end + 1, min(len(lower_frames), rest_end + 51)):
        if len(observations) >= MIN_STEREO_FRAMES and index - observations[-1]["frameIndex"] > 8:
            break
        images = (_gray(lower_frames[index][1]), _gray(upper_frames[index][1]))
        lower_circles = _circle_candidates(images[0], rest_radii[0])
        upper_circles = _circle_candidates(images[1], rest_radii[1])

        def geometric_pairs(first_circles, second_circles):
            matches = []
            for lx, ly, lr in first_circles:
                for ux, uy, ur in second_circles:
                    try:
                        position, gap = _triangulate(_ray(lower, (lx, ly)), _ray(upper, (ux, uy)))
                    except ValueError:
                        continue
                    if gap * 1000 > MAX_CANDIDATE_RAY_GAP_MM or not -0.01 <= position[2] <= 1.5:
                        continue
                    depths = [(camera["R"] @ position + camera["t"])[2] for camera in (lower, upper)]
                    if min(depths) <= 0:
                        continue
                    expected = [RADIUS * camera["K"][0, 0] / depth for camera, depth in zip((lower, upper), depths)]
                    radius_error = max(abs(radius / predicted - 1) for radius, predicted in zip((lr, ur), expected))
                    if radius_error > MAX_CANDIDATE_RADIUS_ERROR:
                        continue
                    matches.append((position, gap, radius_error, (lx, ly), (ux, uy)))
            return matches

        pairs = geometric_pairs(lower_circles, upper_circles)
        if not pairs:
            # A weaker edge response can still be a real ball, but it must pass
            # the same two-view geometry and coherent-path gates as a strong hit.
            lower_circles = _circle_candidates(images[0], rest_radii[0], sensitive=True)
            upper_circles = _circle_candidates(images[1], rest_radii[1], sensitive=True)
            pairs = geometric_pairs(lower_circles, upper_circles)
        if not pairs:
            reject(index, "noCircle" if not len(lower_circles) or not len(upper_circles) else "noGeometricPair")
            continue
        time = lower_frames[index][0]
        if len(observations) >= 2:
            recent = observations[-min(len(observations), 5):]
            times = np.array([o["lowerTime"] for o in recent])
            positions = np.array([o["pointM"] for o in recent])
            slope = np.linalg.lstsq(np.column_stack((times - times[0], np.ones(len(times)))), positions, rcond=None)[0]
            expected_position = slope[1] + slope[0] * (time - times[0])
        elif observations:
            previous = observations[-1]
            elapsed = max(previous["lowerTime"] - start_time, 1e-6)
            expected_position = rest_point + (np.asarray(previous["pointM"]) - rest_point) * ((time - start_time) / elapsed)
        else:
            expected_position = rest_point
        # A candidate must start near the ball and then continue its measured path.
        # Ray agreement alone can also describe a stationary circular object.
        ranked = sorted(pairs, key=lambda item: (float(np.linalg.norm(item[0] - expected_position)), item[1]))
        position, gap, radius_error, lower_px, upper_px = ranked[0]
        path_error = float(np.linalg.norm(position - expected_position))
        allowed = (0.10 if not observations else MAX_CANDIDATE_PATH_ERROR_M)
        if not observations and np.linalg.norm(position - rest_point) < 0.012:
            continue
        if path_error > allowed:
            reject(index, "pathMismatch")
            continue
        if not observations and time - start_time > 0.06:
            break
        observations.append({
            "frameIndex": index, "lowerPx": [float(v) for v in lower_px],
            "upperPx": [float(v) for v in upper_px], "score": round(1 - radius_error, 3),
            "rayGapMm": round(gap * 1000, 2), "pointM": position.tolist(),
            "lowerTime": time, "upperTime": upper_frames[index][0],
        })
    return observations, rejected, rejected_frames


def _find_rest_from_lower(lower, frames, approximate_px):
    """Recover the resting centre and last still timestamp when mono tracking failed."""
    origin, direction = _ray(lower, approximate_px)
    if abs(direction[2]) < 1e-9:
        raise ValueError("Resting ball ray does not meet the ground plane.")
    point = origin + direction * (RADIUS - origin[2]) / direction[2]
    depth = (lower["R"] @ point + lower["t"])[2]
    radius = RADIUS * lower["K"][0, 0] / depth
    found = []
    for index in range(min(len(frames) // 2, 150)):
        circles = _circle_candidates(_gray(frames[index][1]), radius)
        # The armed box can be stale after a small nudge. Recover the persistent
        # resting circle within one ball diameter, rather than assuming that box
        # is an exact current centre (the 16:19 capture was displaced by 34 px).
        nearby = [circle for circle in circles
                  if np.linalg.norm(circle[:2] - approximate_px) <= max(12.0, radius * 2.0)]
        if nearby:
            circle = min(nearby, key=lambda item: np.linalg.norm(item[:2] - approximate_px))
            found.append((index, circle[:2]))
        if len(found) >= 5 and index - found[-1][0] > 4:
            break
    if len(found) < 5:
        raise ValueError("Could not locate the resting ball in the lower-camera burst.")
    cluster = np.median([center for _, center in found], axis=0)
    stationary = [(index, center) for index, center in found
                  if np.linalg.norm(center - cluster) <= max(2.0, radius * 0.15)]
    if len(stationary) < 5:
        raise ValueError("Lower-camera ball candidates do not form a stable resting position.")
    rest_end = stationary[-1][0]
    rest_px = np.median([center for _, center in stationary[-8:]], axis=0)
    return rest_px, rest_end


def start_anchor(start, velocity, rest_point, window_s):
    """Distance (mm) from the fitted start to the nearest start contact could have produced.

    The fit places the ball at ``start`` at the last still frame. Contact happens some
    time Δ later, no later than the first tracked moving frame (``window_s``), so every
    physically possible start lies on rest - velocity * Δ for Δ in [0, window]. At 10.9 m/s
    a 4.1 ms frame interval allows up to 45 mm along the flight, which a plain distance to
    the resting ball wrongly failed against its 30 mm limit (2026-09-25). Also returns the
    implied contact time after the last still frame, in ms.
    """
    start, velocity, rest_point = (np.asarray(v, float) for v in (start, velocity, rest_point))
    speed_squared = float(velocity @ velocity)
    implied = float((rest_point - start) @ velocity / speed_squared) if speed_squared > 1e-12 else 0.0
    delta = min(max(implied, 0.0), max(0.0, float(window_s)))
    nearest = rest_point - velocity * delta
    return float(np.linalg.norm(start - nearest) * 1000), implied * 1000


def _fit(lower, upper, observations, start_time, gravity):
    """Joint least-squares flight in both views: start point and launch velocity."""
    t_lower = np.array([o["lowerTime"] for o in observations]) - start_time
    t_upper = np.array([o["upperTime"] for o in observations]) - start_time
    seen_lower = np.array([o["lowerPx"] for o in observations])
    seen_upper = np.array([o["upperPx"] for o in observations])
    acceleration = GRAVITY if gravity else 0.0

    def path(params, dts):
        points = params[:3] + np.outer(dts, params[3:6])
        points[:, 2] -= 0.5 * acceleration * dts ** 2
        if not gravity:
            points[:, 2] = params[2]
        return points

    def residuals(params):
        values = np.concatenate(((_project(lower, path(params, t_lower)) - seen_lower).ravel(),
                                 (_project(upper, path(params, t_upper)) - seen_upper).ravel()))
        # Huber weighting keeps a single mismatched frame from steering the fit.
        large = np.abs(values) > 2.0
        values[large] = np.sign(values[large]) * np.sqrt(4.0 * np.abs(values[large]) - 4.0)
        return values

    points = np.array([o["pointM"] for o in observations])
    design = np.column_stack((t_lower, np.ones(len(t_lower))))
    target = points.copy()
    target[:, 2] += 0.5 * acceleration * t_lower ** 2
    slope, intercept = np.linalg.lstsq(design, target, rcond=None)[0]
    params = np.concatenate((intercept, slope))
    if not gravity:
        params[5] = 0.0
    base = residuals(params)
    cost, damping = float(base @ base), 1e-3
    steps = np.array([1e-5, 1e-5, 1e-5, 1e-3, 1e-3, 1e-3])

    def jacobian(params, base):
        return np.column_stack([(residuals(params + np.eye(6)[k] * steps[k]) - base) / steps[k] for k in range(6)])

    for _ in range(100):
        jac = jacobian(params, base)
        normal = jac.T @ jac
        try:
            delta = -np.linalg.solve(normal + damping * np.diag(np.diag(normal) + 1e-9), jac.T @ base)
        except np.linalg.LinAlgError:
            break
        trial = residuals(params + delta)
        trial_cost = float(trial @ trial)
        if trial_cost < cost:
            improvement = cost - trial_cost
            params, base, cost, damping = params + delta, trial, trial_cost, damping * 0.3
            if improvement < 1e-10 * max(1.0, cost):
                break
        else:
            damping *= 10
            if damping > 1e8:
                break
    jac = jacobian(params, base)
    covariance = np.linalg.pinv(jac.T @ jac) * max(1.0, cost / max(1, len(base) - 6))
    lower_errors = np.linalg.norm(_project(lower, path(params, t_lower)) - seen_lower, axis=1)
    upper_errors = np.linalg.norm(_project(upper, path(params, t_upper)) - seen_upper, axis=1)
    return params, covariance, lower_errors, upper_errors


def stereo_cross_check(lower_frames, upper_frames, lower_camera, upper_camera, rest_px, track, start_time,
                       mono_velocity=None, gravity=None):
    """Triangulate paired ball observations and optionally compare with the mono fit.

    ``track`` contains lower-camera per-frame centers, either from the mono fit or the
    image-plane tracker. With no mono velocity this becomes an independent stereo fit,
    allowing stereo to recover a launch when apparent ball-size fitting failed.
    """
    lower = _camera(*lower_camera)
    upper = _camera(*upper_camera)
    if len(upper_frames) != len(lower_frames):
        raise ValueError("Top-camera burst does not pair frame-for-frame with the lower camera.")
    if start_time is None:
        rest_px, rest_index = _find_rest_from_lower(lower, lower_frames, np.asarray(rest_px, float))
        start_time = lower_frames[rest_index][0]
    first = track[0]["frameIndex"] if track else None
    # The tracker may not find a clean outgoing centre until many frames after
    # departure. Build the resting-ball template around the supplied last-still
    # timestamp, not a fixed offset from the first matched moving frame.
    rest_end = min(range(len(lower_frames)), key=lambda index: abs(lower_frames[index][0] - start_time))
    rest_indices = list(range(max(0, rest_end - 8), rest_end + 1))
    empty_indices = list(range(len(lower_frames) - 1, max((first or rest_end) + 40, len(lower_frames) - 60), -4))
    if len(rest_indices) < 3 or len(empty_indices) < 3:
        raise ValueError("Burst is too short around the shot for a stereo check.")
    cache = {}

    def image(index):
        if index not in cache:
            cache[index] = _gray(upper_frames[index][1])
        return cache[index]

    origin, direction = _ray(lower, rest_px)
    if abs(direction[2]) < 1e-9:
        raise ValueError("Resting ball ray does not meet the ground plane.")
    assumed_rest = origin + direction * (RADIUS - origin[2]) / direction[2]
    upper_rest, template, half = _rest_template(upper, image, rest_indices, empty_indices, _project(upper, [assumed_rest])[0])
    rest_point, rest_gap = _triangulate(_ray(lower, rest_px), _ray(upper, upper_rest))

    observations, skipped = [], []
    # The single-camera track is useful for a cross-check only when its own fit
    # succeeded. Recovery must not inherit its false ball centres.
    guided_track = (track or []) if mono_velocity is not None else []
    for point in guided_track:
        index = point["frameIndex"]
        upper_px, score = _match_on_epipolar(lower, upper, image(index), template, half, point["centerPx"])
        if upper_px is None or score < MIN_MATCH_SCORE:
            skipped.append(index)
            continue
        position, gap = _triangulate(_ray(lower, point["centerPx"]), _ray(upper, upper_px))
        observations.append({"frameIndex": index, "lowerPx": list(point["centerPx"]), "upperPx": upper_px.tolist(),
                             "score": round(score, 3), "rayGapMm": round(gap * 1000, 2), "pointM": position.tolist(),
                             "lowerTime": lower_frames[index][0], "upperTime": upper_frames[index][0]})
    detection = "epipolar-template"
    candidate_rejections = None
    candidate_rejected_frames = None
    if mono_velocity is None or len(observations) < MIN_STEREO_FRAMES:
        observations, candidate_rejections, candidate_rejected_frames = _independent_observations(
            lower, upper, lower_frames, upper_frames, rest_point, rest_end)
        detection = "independent-circles"
    if len(observations) == 2:
        return _two_point_speed(lower, upper, observations, rest_point, rest_gap, upper_rest, start_time,
                                detection, candidate_rejections, candidate_rejected_frames, skipped)
    if len(observations) < MIN_STEREO_FRAMES:
        raise StereoTrackingError(
            f"Stereo found {len(observations)} paired ball frames; needs {MIN_STEREO_FRAMES}. "
            f"Independent detection rejections: {candidate_rejections}.",
            {"frames": len(observations), "frameIndices": [o["frameIndex"] for o in observations],
             "candidateRejections": candidate_rejections, "candidateRejectedFrames": candidate_rejected_frames,
             "detection": detection},
        )
    span = observations[-1]["lowerTime"] - observations[0]["lowerTime"]
    if span < MIN_STEREO_TIME_SPAN_S:
        raise StereoTrackingError(
            f"Stereo paired frames span {span * 1000:.1f} ms; needs at least "
            f"{MIN_STEREO_TIME_SPAN_S * 1000:.0f} ms for a velocity estimate.",
            {"frames": len(observations), "frameIndices": [o["frameIndex"] for o in observations],
             "spanMs": round(span * 1000, 2), "candidateRejections": candidate_rejections,
             "candidateRejectedFrames": candidate_rejected_frames, "detection": detection},
        )

    if gravity is None:
        heights = np.asarray([o["pointM"][2] for o in observations], dtype=float)
        near_ground = (np.median(np.abs(heights - RADIUS)) <= 0.020
                       and float(np.ptp(heights)) <= 0.015)
        gravity = not near_ground
    params, covariance, lower_errors, upper_errors = _fit(lower, upper, observations, start_time, gravity)
    velocity = params[3:6]
    speed = float(np.linalg.norm(velocity))
    launch = lambda v: math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
    heading = lambda v: math.degrees(math.atan2(v[1], v[0]))
    if not gravity:
        velocity[2] = 0.0
    mono_velocity = np.asarray(mono_velocity, float) if mono_velocity is not None else None
    mono_speed = float(np.linalg.norm(mono_velocity)) if mono_velocity is not None else None
    heading_difference = ((heading(velocity) - heading(mono_velocity) + 180) % 360 - 180
                          if mono_velocity is not None else None)
    unit = velocity / max(speed, 1e-9)
    launch_gradient = np.zeros(6)
    heading_gradient = np.zeros(6)
    for axis in range(3):
        step = 1e-3
        shifted = velocity.copy()
        shifted[axis] += step
        launch_gradient[axis + 3] = (launch(shifted) - launch(velocity)) / step
        heading_gradient[axis + 3] = (heading(shifted) - heading(velocity)) / step
    launch_sigma = math.sqrt(max(0.0, float(launch_gradient @ covariance @ launch_gradient)))
    heading_sigma = math.sqrt(max(0.0, float(heading_gradient @ covariance @ heading_gradient)))
    median_ray_gap = float(np.median([o["rayGapMm"] for o in observations]))
    max_pair_offset = max(abs(o["upperTime"] - o["lowerTime"]) for o in observations) * 1e6
    start_anchor_error, contact_ms = start_anchor(params[:3], params[3:6], rest_point,
                                                 observations[0]["lowerTime"] - start_time)
    rms = float(np.sqrt(np.mean(np.concatenate((lower_errors, upper_errors)) ** 2)))
    return {
        "method": "shared-tag-epipolar-v2",
        "detection": detection,
        "candidateRejections": candidate_rejections,
        "candidateRejectedFrames": candidate_rejected_frames,
        "model": "flight" if gravity else "ground",
        "frames": len(observations),
        "frameIndices": [o["frameIndex"] for o in observations],
        "spanMs": round(span * 1000, 2),
        "skippedFrames": skipped,
        "upperRestPx": [round(float(v), 2) for v in upper_rest],
        "restPointMm": [round(float(v) * 1000, 1) for v in rest_point],
        "restHeightErrorMm": round((float(rest_point[2]) - RADIUS) * 1000, 2),
        "restRayGapMm": round(rest_gap * 1000, 2),
        "medianRayGapMm": round(median_ray_gap, 2),
        "maxRayGapMm": round(float(max(o["rayGapMm"] for o in observations)), 2),
        "rmsPx": round(rms, 3),
        "lowerRmsPx": round(float(np.sqrt(np.mean(lower_errors ** 2))), 3),
        "upperRmsPx": round(float(np.sqrt(np.mean(upper_errors ** 2))), 3),
        "startAnchorErrorMm": round(start_anchor_error, 2),
        "rawStartOffsetMm": round(float(np.linalg.norm(params[:3] - rest_point) * 1000), 2),
        "impliedContactMs": round(contact_ms, 2),
        "maxPairOffsetUs": round(max_pair_offset, 2),
        "speedMps": round(speed, 4),
        "speedSigmaMps": round(math.sqrt(max(0.0, float(unit @ covariance[3:6, 3:6] @ unit))), 4),
        "launchDeg": round(launch(velocity), 3),
        "launchSigmaDeg": round(launch_sigma, 3),
        "headingDeg": round(heading(velocity), 3),
        "headingSigmaDeg": round(heading_sigma, 3),
        "speedDifferencePct": (round(abs(speed - mono_speed) / max(mono_speed, 0.1) * 100, 3)
                                if mono_speed is not None else None),
        "launchDifferenceDeg": (round(abs(launch(velocity) - (launch(mono_velocity) if gravity else 0.0)), 3)
                                 if mono_velocity is not None else None),
        "headingDifferenceDeg": (round(abs(heading_difference), 3) if heading_difference is not None else None),
        "velocityMps": velocity.tolist(),
        "track": [{"frameIndex": o["frameIndex"], "centerPx": o["lowerPx"], "upperPx": o["upperPx"],
                   "score": o["score"], "rayGapMm": o["rayGapMm"], "positionM": o["pointM"]}
                  for o in observations],
    }
