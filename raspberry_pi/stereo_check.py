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
# A staggered pair is two sample instants (one per camera), so two pairs already give four and the fit can be
# checked against its residuals; the velocity baseline is then a frame plus the offset, not eight milliseconds.
MIN_STAGGERED_PAIRS = 2
MIN_STAGGERED_TIME_SPAN_S = 0.005
MAX_CANDIDATE_RAY_GAP_MM = 6.0
MAX_CANDIDATE_RADIUS_ERROR = 0.35
MAX_CANDIDATE_PATH_ERROR_M = 0.035
REST_SEARCH_PX = 40
# The top camera's resting ball must sit where the lower camera's ground-plane
# assumption predicts; further away means the two poses do not describe one scene.
MAX_REST_PREDICTION_PX = 15.0
# Measured-grade gates.
MAX_RAY_GAP_MM = 3.0
# The ground under each shot is now taken from the resting ball (launch_measurements.
# resting_ball_surface), so a surface 9-12 mm off the calibration no longer matters for
# speed, launch or direction. What remains is a gross check that both views saw the ball.
MAX_REST_HEIGHT_ERROR_MM = 25.0
MAX_START_ANCHOR_ERROR_MM = 30.0
MAX_STEREO_RMS_PX = 3.0
MAX_PAIR_OFFSET_US = 250.0
MAX_SPEED_DIFFERENCE_PCT = 3.0
MAX_ANGLE_DIFFERENCE_DEG = 1.5
# Staggered capture: the top camera's frames fall between the lower camera's, half a frame later,
# so a pair is two instants. Above this median upper-minus-lower time the burst is staggered.
STAGGER_MIN_OFFSET_US = 600.0
# Longest lower-camera ball step (px) between two frames that is still interpolated across.
MAX_STAGGER_STEP_PX = 160.0


def stagger_offset_us(lower_frames, upper_frames):
    """Nominal upper-minus-lower frame time (microseconds) of a staggered burst, or None when in step."""
    offsets = [(upper[0] - lower[0]) * 1e6 for lower, upper in zip(lower_frames, upper_frames)]
    if not offsets:
        return None
    nominal = float(np.median(offsets))
    return nominal if abs(nominal) > STAGGER_MIN_OFFSET_US else None


def is_staggered(lower_frames, upper_frames):
    return stagger_offset_us(lower_frames, upper_frames) is not None


def _ptime(observation):
    """The instant an observation's triangulated point belongs to."""
    return observation.get("pointTime", observation["lowerTime"])


def _pixel_at(times, pixels, when, max_extrapolation, max_span):
    """Linear interpolation of a pixel track at ``when``; short extrapolation off either end."""
    if len(times) < 2:
        return None
    i = int(np.searchsorted(times, when))
    if i == 0:
        if times[0] - when > max_extrapolation:
            return None
        a, b = 0, 1
    elif i >= len(times):
        if when - times[-1] > max_extrapolation:
            return None
        a, b = len(times) - 2, len(times) - 1
    else:
        a, b = i - 1, i
    span = times[b] - times[a]
    if span <= 0 or span > max_span:
        return None
    return pixels[a] + (pixels[b] - pixels[a]) * ((when - times[a]) / span)


# ---- anchored flight search ------------------------------------------------------------------------------
# A fast ball is in view for only two or three frames, and a blurred or dark one is not found as a clean
# circle in every frame of either camera, so pairing circles frame by frame finds nothing. This instead
# looks for what is actually there: a ball-sized patch that differs from the empty scene, bright on the mat
# or dark against the window. It tries thousands of launches from the known resting ball (speed, launch
# angle, direction, contact time), scores each by how many of those patches, in either camera at any frame,
# it explains, keeps the best, then centres each patch and refines the launch.
SEARCH_SPEEDS = 3.0 * 1.05 ** np.arange(0, 68)   # 3 to 80 m/s in 5 percent steps: a chip to a driver
SEARCH_LAUNCHES = np.arange(-6.0, 57.0, 3.0)
SEARCH_HEADINGS = np.arange(-60.0, 61.0, 6.0)
SEARCH_CONTACT_FRACTIONS = (0.1, 0.35, 0.6, 0.85)
SEARCH_FRAMES = 14
SEARCH_DIFFERENCE = 24.0      # gray levels a pixel must differ from the empty scene
SEARCH_HIT = 0.5              # evidence needed for a patch to count as the ball
SEARCH_REFINE_PX = 9.0
SEARCH_MIN_DETECTIONS = 4
SEARCH_MAX_RMS_PX = 3.5
# Median distance (mm) from each sighting's ray to the fitted ball; centred blur costs a few millimetres.
SEARCH_MAX_RAY_GAP_MM = 6.0


class FlightSearchError(ValueError):
    """No launch from the resting ball explains enough of what appears after the hit."""


def _search_background(frames, rest_end):
    """The scene as it stood just before the hit: the person is already in the pose they hit from, so only
    what moves after contact differs. (The end of the burst is worse: they have walked or turned by then.)"""
    indices = list(range(max(0, rest_end - 16), max(1, rest_end - 3), 2)) or [rest_end]
    return np.median([_gray(frames[i][1]) for i in indices], axis=0)


def _search_maps(frames, first, last, background, radius, rest_pixel):
    """Per frame: the foreground mask and a ball-shaped evidence map (fill of a disc-sized box minus its surround).

    The resting ball is part of the background, so the spot it left shows as a ball-sized ghost in every later
    frame; it is blanked, the ball having gone from there.
    """
    half = max(3, int(round(radius)))
    inner, outer = 2 * half + 1, 2 * int(round(2.3 * half)) + 1
    ring_inner = 2 * int(round(1.5 * half)) + 1
    maps = {}
    for index in range(first, last):
        difference = cv2.GaussianBlur(np.abs(_gray(frames[index][1]) - background), (5, 5), 0)
        mask = (difference > SEARCH_DIFFERENCE).astype(np.float32)
        cv2.circle(mask, (int(round(rest_pixel[0])), int(round(rest_pixel[1]))), int(round(1.4 * radius)), 0.0, -1)
        fill = cv2.boxFilter(mask, -1, (inner, inner), normalize=True, borderType=cv2.BORDER_CONSTANT)
        outer_sum = cv2.boxFilter(mask, -1, (outer, outer), normalize=False, borderType=cv2.BORDER_CONSTANT)
        inner_sum = cv2.boxFilter(mask, -1, (ring_inner, ring_inner), normalize=False, borderType=cv2.BORDER_CONSTANT)
        ring = (outer_sum - inner_sum) / max(1.0, outer * outer - ring_inner * ring_inner)
        evidence = fill - 0.7 * ring
        image = _gray(frames[index][1])
        found = list(_circle_candidates(image, radius)) + list(_circle_candidates(image, radius, sensitive=True))
        unique = []
        for circle in found:
            if all(math.hypot(circle[0] - other[0], circle[1] - other[1]) > 4.0 for other in unique):
                unique.append(circle)
        circles = np.array(unique, float).reshape(-1, 3)
        maps[index] = (mask, cv2.dilate(evidence, np.ones((5, 5), np.uint8)), circles)
    return maps


def _blob_centre(mask, predicted, radius):
    """Centre of the ball-sized foreground blob nearest the predicted pixel, or None."""
    half = int(round(2.0 * radius))
    x0, y0 = int(round(predicted[0])), int(round(predicted[1]))
    left, top = max(0, x0 - half), max(0, y0 - half)
    right, bottom = min(mask.shape[1], x0 + half + 1), min(mask.shape[0], y0 + half + 1)
    window = (mask[top:bottom, left:right] > 0.5).astype(np.uint8)
    if window.size == 0 or not window.any():
        return None
    count, _, stats, centroids = cv2.connectedComponentsWithStats(window)
    best = None
    area_ball = math.pi * radius ** 2
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if not 0.3 * area_ball <= area <= 2.6 * area_ball:
            continue
        centre = centroids[label] + [left, top]
        distance = math.hypot(centre[0] - predicted[0], centre[1] - predicted[1])
        if best is None or distance < best[0]:
            best = (distance, centre)
    return None if best is None or best[0] > 1.6 * radius else best[1]


def _anchored_flight_search(lower, upper, lower_frames, upper_frames, rest_point, rest_end, rest_radii):
    """Fit a launch from the resting ball to ball-sized patches seen in either camera after the hit."""
    cameras = (lower, upper)
    frames = (lower_frames, upper_frames)
    height, width = lower_frames[0][1].shape[:2]
    gaps = np.diff([frame[0] for frame in lower_frames])
    period = float(np.median(gaps)) if len(gaps) else 1 / 242
    t_rest = lower_frames[rest_end][0]
    first, last = rest_end + 1, min(len(lower_frames), rest_end + 1 + SEARCH_FRAMES)
    if last - first < 3:
        raise FlightSearchError("Too few frames after the last still frame.")
    backgrounds = [_search_background(f, rest_end) for f in frames]
    rest_pixels = [_project(camera, [rest_point])[0] for camera in cameras]
    maps = [_search_maps(frames[c], first, last, backgrounds[c], rest_radii[c], rest_pixels[c]) for c in (0, 1)]
    speed, launch, heading, fraction = (a.ravel() for a in np.meshgrid(
        SEARCH_SPEEDS, SEARCH_LAUNCHES, SEARCH_HEADINGS, SEARCH_CONTACT_FRACTIONS, indexing="ij"))
    launch_r, heading_r = np.radians(launch), np.radians(heading)
    velocity = np.column_stack((speed * np.cos(launch_r) * np.cos(heading_r),
                                speed * np.cos(launch_r) * np.sin(heading_r), speed * np.sin(launch_r)))
    contact = t_rest + fraction * period

    def predict(camera_index, time, velocities, contacts):
        tau = np.maximum(time - contacts, 0.0)
        position = rest_point + velocities * tau[:, None]
        position[:, 2] -= 0.5 * GRAVITY * tau ** 2
        camera = cameras[camera_index]
        depth = (position @ camera["R"].T + camera["t"])[:, 2]
        pixel = np.nan_to_num(_project(camera, position), nan=-1e4, posinf=-1e4, neginf=-1e4)
        inside = (pixel[:, 0] >= 0) & (pixel[:, 0] < width) & (pixel[:, 1] >= 0) & (pixel[:, 1] < height)
        return pixel, (depth > 0.05) & (tau > 2e-4) & inside

    scores = np.zeros(len(speed))
    sightings = []
    for camera_index in (0, 1):
        for index in range(first, last):
            time = frames[camera_index][index][0]
            pixel, ok = predict(camera_index, time, velocity, contact)
            evidence, circles = maps[camera_index][index][1], maps[camera_index][index][2]
            x = np.clip(np.round(pixel[:, 0]).astype(int), 0, width - 1)
            y = np.clip(np.round(pixel[:, 1]).astype(int), 0, height - 1)
            value = np.minimum(evidence[y, x], 1.0)
            if len(circles):
                near = np.min(np.hypot(pixel[:, None, 0] - circles[None, :, 0], pixel[:, None, 1] - circles[None, :, 1]), axis=1)
                value = np.maximum(value, np.where(near < 7.0, 1.0 - near / 10.5, 0.0))
            scores += np.where(ok & (value >= SEARCH_HIT), value, 0.0)
            sightings.append((camera_index, index, time))
    best = int(np.argmax(scores))
    if scores[best] < 3.0:
        raise FlightSearchError("No launch from the resting ball explains enough of what appears after the hit.")
    # Distinct launches that explain the sightings nearly as well as the best: each is refined, and the
    # answer is only ambiguous if a rival still fits about as well after refinement.
    def alike(i, j):
        return (abs(speed[i] - speed[j]) <= max(3.0, 0.2 * speed[j]) and abs(launch[i] - launch[j]) <= 9.0
                and abs(heading[i] - heading[j]) <= 13.0)

    representatives = []
    for i in np.argsort(-scores)[:600]:
        if scores[i] < 0.85 * scores[best] or len(representatives) >= 4:
            break
        if not any(alike(i, j) for j in representatives):
            representatives.append(int(i))
    steps = np.array([1e-3, 1e-3, 1e-3, 1e-6])

    def gather(current, radius=SEARCH_REFINE_PX):
        """Centre of the blob nearest the predicted ball in every (camera, frame) where there is one."""
        found = []
        for camera_index, index, time in sightings:
            pixel, ok = predict(camera_index, time, current[None, :3], np.array([current[3]]))
            if not ok[0]:
                continue
            centre = None
            circles = maps[camera_index][index][2]
            if len(circles):
                distance = np.hypot(circles[:, 0] - pixel[0, 0], circles[:, 1] - pixel[0, 1])
                j = int(np.argmin(distance))
                if distance[j] < radius:
                    centre = circles[j, :2]
            if centre is None:
                centre = _blob_centre(maps[camera_index][index][0], pixel[0], rest_radii[camera_index])
            if centre is not None and math.hypot(centre[0] - pixel[0, 0], centre[1] - pixel[0, 1]) < radius:
                found.append({"cam": camera_index, "index": index, "time": time, "seen": np.asarray(centre, float)})
        return found

    def residuals(current, matched):
        values = []
        for detection in matched:
            pixel, _ = predict(detection["cam"], detection["time"], current[None, :3], np.array([current[3]]))
            values.extend(pixel[0] - detection["seen"])
        return np.array(values)

    def optimise(current, subset):
        base = residuals(current, subset)
        cost, damping = float(base @ base), 1e-3
        for _ in range(40):
            jac = np.column_stack([(residuals(current + np.eye(4)[k] * steps[k], subset) - base) / steps[k] for k in range(4)])
            normal = jac.T @ jac
            try:
                delta = -np.linalg.solve(normal + damping * np.diag(np.diag(normal) + 1e-9), jac.T @ base)
            except np.linalg.LinAlgError:
                break
            trial = residuals(current + delta, subset)
            trial_cost = float(trial @ trial)
            if trial_cost < cost:
                improvement = cost - trial_cost
                current, base, cost, damping = current + delta, trial, trial_cost, damping * 0.3
                if improvement < 1e-9 * max(1.0, cost):
                    break
            else:
                damping *= 10
                if damping > 1e8:
                    break
        return current

    def rms_of(current, subset):
        per_detection = np.linalg.norm(residuals(current, subset).reshape(-1, 2), axis=1)
        return float(np.sqrt(np.mean(per_detection ** 2))), per_detection

    def refine(start):
        current = np.array(start, float)
        # The grid launch is only roughly right, so start with a wide net and tighten it as the fit improves.
        found = gather(current, 2.0 * SEARCH_REFINE_PX)
        for radius in (1.5 * SEARCH_REFINE_PX, 1.2 * SEARCH_REFINE_PX, SEARCH_REFINE_PX):
            if len(found) < SEARCH_MIN_DETECTIONS:
                raise FlightSearchError("Too few ball-sized patches match the launch.")
            current = optimise(current, found)
            found = gather(current, radius)
        if len(found) < SEARCH_MIN_DETECTIONS:
            raise FlightSearchError("Too few ball-sized patches match the refined launch.")
        # One badly centred patch can spoil an otherwise clean fit: drop the worst and refit while enough remain.
        error, per_detection = rms_of(current, found)
        while error > SEARCH_MAX_RMS_PX and len(found) > SEARCH_MIN_DETECTIONS:
            found = [d for i, d in enumerate(found) if i != int(np.argmax(per_detection))]
            current = optimise(current, found)
            error, per_detection = rms_of(current, found)
        cameras_used = {d["cam"] for d in found}
        instants = {round(d["time"], 6) for d in found}
        if len(cameras_used) < 2 or len(instants) < 3 or len({d["index"] for d in found}) < 2:
            raise FlightSearchError("The matched patches come from one camera or too few instants.")
        if error > SEARCH_MAX_RMS_PX:
            raise FlightSearchError(f"Best launch leaves {error:.1f} px of residual.")
        fitted = float(np.linalg.norm(current[:3]))
        fitted_angle = math.degrees(math.atan2(current[2], math.hypot(current[0], current[1])))
        if not 2.0 <= fitted <= 70.0 or not -10.0 <= fitted_angle <= 75.0:
            raise FlightSearchError("Best launch is physically implausible.")
        return {"params": current, "matched": found, "rms": error, "speed": fitted, "launch": fitted_angle,
                "heading": math.degrees(math.atan2(current[1], current[0]))}

    refined, last_error = [], None
    for i in representatives:
        try:
            refined.append(refine(np.concatenate((velocity[i], [contact[i]]))))
        except FlightSearchError as error:
            last_error = error
    if not refined:
        raise last_error or FlightSearchError("No candidate launch survived refinement.")
    refined.sort(key=lambda r: (r["rms"], -len(r["matched"])))
    chosen = refined[0]
    for rival in refined[1:]:
        different = (abs(rival["speed"] - chosen["speed"]) > max(2.0, 0.12 * chosen["speed"])
                     or abs(rival["launch"] - chosen["launch"]) > 6.0 or abs(rival["heading"] - chosen["heading"]) > 10.0)
        if different and rival["rms"] <= 1.15 * chosen["rms"] and len(rival["matched"]) >= len(chosen["matched"]) - 1:
            raise FlightSearchError("Two different launches explain what appears equally well.")
    params, matched, rms = chosen["params"], chosen["matched"], chosen["rms"]
    base = residuals(params, matched)
    frame_indices = sorted({d["index"] for d in matched})
    launch_v = params[:3]
    fitted_speed = float(np.linalg.norm(launch_v))
    fitted_launch = math.degrees(math.atan2(launch_v[2], math.hypot(launch_v[0], launch_v[1])))
    if not 2.0 <= fitted_speed <= 70.0 or not -10.0 <= fitted_launch <= 75.0:
        raise FlightSearchError("Best launch is physically implausible.")
    jac = np.column_stack([(residuals(params + np.eye(4)[k] * steps[k], matched) - base) / steps[k] for k in range(4)])
    covariance = np.linalg.pinv(jac.T @ jac) * max(1.0, float(base @ base) / max(1, len(base) - 4))
    launch_fn = lambda v: math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))
    heading_fn = lambda v: math.degrees(math.atan2(v[1], v[0]))
    unit = launch_v / fitted_speed
    launch_grad, heading_grad = np.zeros(4), np.zeros(4)
    for axis in range(3):
        shifted = launch_v.copy()
        shifted[axis] += 1e-3
        launch_grad[axis] = (launch_fn(shifted) - launch_fn(launch_v)) / 1e-3
        heading_grad[axis] = (heading_fn(shifted) - heading_fn(launch_v)) / 1e-3

    def model_at(time):
        tau = max(time - params[3], 0.0)
        point = rest_point + launch_v * tau
        point[2] -= 0.5 * GRAVITY * tau ** 2
        return point

    ray_gaps, track = [], {}
    for detection in matched:
        origin, direction = _ray(cameras[detection["cam"]], detection["seen"])
        gap = float(np.linalg.norm(np.cross(direction, model_at(detection["time"]) - origin))) * 1000
        ray_gaps.append(gap)
        entry = track.setdefault(detection["index"], {"frameIndex": detection["index"], "centerPx": None, "upperPx": None,
                                                      "score": 1.0, "rayGapMm": 0.0,
                                                      "positionM": model_at(lower_frames[detection["index"]][0]).tolist()})
        entry["centerPx" if detection["cam"] == 0 else "upperPx"] = [float(v) for v in detection["seen"]]
        entry["rayGapMm"] = round(max(entry["rayGapMm"], gap), 2)
    for entry in track.values():
        for key, camera_index in (("centerPx", 0), ("upperPx", 1)):
            if entry[key] is None:
                model = model_at(frames[camera_index][entry["frameIndex"]][0])
                entry[key] = [float(v) for v in _project(cameras[camera_index], [model])[0]]
    per_camera = {0: [], 1: []}
    for detection, value in zip(matched, np.split(base, len(matched))):
        per_camera[detection["cam"]].append(float(np.linalg.norm(value)))
    times = [d["time"] for d in matched]
    return {
        "velocity": launch_v, "speed": fitted_speed, "launch": fitted_launch, "heading": heading_fn(launch_v),
        "contact": float(params[3]), "t_rest": t_rest, "rms": rms,
        "lower_rms": float(np.sqrt(np.mean(np.square(per_camera[0])))) if per_camera[0] else 0.0,
        "upper_rms": float(np.sqrt(np.mean(np.square(per_camera[1])))) if per_camera[1] else 0.0,
        "speed_sigma": math.sqrt(max(0.0, float(np.append(unit, 0) @ covariance @ np.append(unit, 0)))),
        "launch_sigma": math.sqrt(max(0.0, float(launch_grad @ covariance @ launch_grad))),
        "heading_sigma": math.sqrt(max(0.0, float(heading_grad @ covariance @ heading_grad))),
        "detections": len(matched), "frame_indices": frame_indices, "span": max(times) - min(times),
        "ray_gaps": ray_gaps, "track": [track[i] for i in sorted(track)], "score": float(scores[best]),
    }


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
    span = _ptime(second) - _ptime(first)
    diagnostics["spanMs"] = round(span * 1000, 2)
    if second["frameIndex"] - first["frameIndex"] > TWO_POINT_MAX_FRAME_GAP or span < 0.003:
        raise StereoTrackingError("Two stereo points are too far apart or too close in time for an interval speed.", diagnostics)
    pair_offset = max(abs((o["upperTime"] - o["lowerTime"]) * 1e6 - (o.get("staggerOffsetUs") or 0.0)) for o in observations)
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
    rest_interval = _ptime(first) - start_time
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
                         "two-camera geometry puts it. The ball may be touching a foot or hand so its outline in the lower "
                         "camera is wrong (keep it clear of both), or a camera or the stand has moved (recalibrate the pair).")
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


def _geometric_pairs(lower, upper, first_circles, second_circles):
    """Circle pairs (lower, upper) whose rays meet on a plausible ball of the right apparent size."""
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


def _independent_observations(lower, upper, lower_frames, upper_frames, rest_point, rest_end, stagger_us=None):
    """Pair independently found circles using calibrated rays and a smooth 3D path.

    With ``stagger_us`` the top camera's frame k is half a frame after the lower camera's frame k, so
    each top-camera circle is paired with the lower camera's ball interpolated to that instant from the
    two neighbouring lower frames. The observation keeps the raw lower circle of frame k and its own
    time; the joint fit is what combines the two instants.
    """
    observations = []
    rejected = {"noCircle": 0, "noGeometricPair": 0, "pathMismatch": 0}
    rejected_frames = []

    def reject(index, reason):
        rejected[reason] += 1
        rejected_frames.append({"frameIndex": index, "reason": reason})

    start_time = lower_frames[rest_end][0]
    rest_radii = [RADIUS * camera["K"][0, 0] / (camera["R"] @ rest_point + camera["t"])[2]
                  for camera in (lower, upper)]
    circle_cache = {}

    def circles(camera_index, frames, index, sensitive):
        key = (camera_index, index, sensitive)
        if key not in circle_cache:
            circle_cache[key] = _circle_candidates(_gray(frames[index][1]), rest_radii[camera_index], sensitive=sensitive)
        return circle_cache[key]

    def staggered_pairs(index, sensitive):
        """(pairs, raw lower circle by interpolated candidate) for the top frame at ``index``."""
        first, second = (index, index + 1) if stagger_us > 0 else (index - 1, index)
        if first < 0 or second >= len(lower_frames):
            return [], {}
        t0, t1 = lower_frames[first][0], lower_frames[second][0]
        weight = (upper_frames[index][0] - t0) / (t1 - t0) if t1 > t0 else 0.0
        raw_by_candidate, candidates = {}, []
        for a in circles(0, lower_frames, first, sensitive):
            for b in circles(0, lower_frames, second, sensitive):
                if float(np.hypot(a[0] - b[0], a[1] - b[1])) > MAX_STAGGER_STEP_PX:
                    continue
                candidate = (a[0] + (b[0] - a[0]) * weight, a[1] + (b[1] - a[1]) * weight, a[2] + (b[2] - a[2]) * weight)
                candidates.append(candidate)
                raw = a if first == index else b
                raw_by_candidate[(round(float(candidate[0]), 4), round(float(candidate[1]), 4))] = (float(raw[0]), float(raw[1]))
        return _geometric_pairs(lower, upper, candidates, circles(1, upper_frames, index, sensitive)), raw_by_candidate

    for index in range(rest_end + 1, min(len(lower_frames), rest_end + 51)):
        if len(observations) >= MIN_STEREO_FRAMES and index - observations[-1]["frameIndex"] > 8:
            break
        raw_lower = {}
        if stagger_us is None:
            images = (_gray(lower_frames[index][1]), _gray(upper_frames[index][1]))
            lower_circles = _circle_candidates(images[0], rest_radii[0])
            upper_circles = _circle_candidates(images[1], rest_radii[1])
            pairs = _geometric_pairs(lower, upper, lower_circles, upper_circles)
            if not pairs:
                # A weaker edge response can still be a real ball, but it must pass
                # the same two-view geometry and coherent-path gates as a strong hit.
                lower_circles = _circle_candidates(images[0], rest_radii[0], sensitive=True)
                upper_circles = _circle_candidates(images[1], rest_radii[1], sensitive=True)
                pairs = _geometric_pairs(lower, upper, lower_circles, upper_circles)
        else:
            pairs, raw_lower = staggered_pairs(index, False)
            lower_circles = circles(0, lower_frames, index, False)
            upper_circles = circles(1, upper_frames, index, False)
            if not pairs:
                pairs, raw_lower = staggered_pairs(index, True)
                lower_circles = circles(0, lower_frames, index, True)
                upper_circles = circles(1, upper_frames, index, True)
        if not pairs:
            reject(index, "noCircle" if not len(lower_circles) or not len(upper_circles) else "noGeometricPair")
            continue
        time = upper_frames[index][0] if stagger_us is not None else lower_frames[index][0]
        if len(observations) >= 2:
            recent = observations[-min(len(observations), 5):]
            times = np.array([_ptime(o) for o in recent])
            positions = np.array([o["pointM"] for o in recent])
            slope = np.linalg.lstsq(np.column_stack((times - times[0], np.ones(len(times)))), positions, rcond=None)[0]
            expected_position = slope[1] + slope[0] * (time - times[0])
        elif observations:
            previous = observations[-1]
            elapsed = max(_ptime(previous) - start_time, 1e-6)
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
        observation = {
            "frameIndex": index, "lowerPx": [float(v) for v in lower_px],
            "upperPx": [float(v) for v in upper_px], "score": round(1 - radius_error, 3),
            "rayGapMm": round(gap * 1000, 2), "pointM": position.tolist(),
            "lowerTime": lower_frames[index][0], "upperTime": upper_frames[index][0],
        }
        if stagger_us is not None:
            raw = raw_lower.get((round(float(lower_px[0]), 4), round(float(lower_px[1]), 4)))
            if raw is None:
                continue
            observation.update(lowerPx=list(raw), pointTime=time, staggerOffsetUs=stagger_us)
        observations.append(observation)
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
    last_index = -1
    # Scan the whole burst: a long address puts the hit well past the middle (frame ~100 of 182 on
    # 2026-09-29), and a search that stopped at the half way point never reached the departure.
    for index in range(len(frames)):
        circles = _circle_candidates(_gray(frames[index][1]), radius)
        # The armed box can be stale after a small nudge. Recover the persistent
        # resting circle within one ball diameter, rather than assuming that box
        # is an exact current centre (the 16:19 capture was displaced by 34 px).
        nearby = [circle for circle in circles
                  if np.linalg.norm(circle[:2] - approximate_px) <= max(12.0, radius * 2.0)]
        if nearby:
            circle = min(nearby, key=lambda item: np.linalg.norm(item[:2] - approximate_px))
            found.append((index, circle[:2]))
            last_index = index
        # The club can hide the ball for a few frames at address; only a long absence means it has gone.
        if len(found) >= 5 and index - last_index > 40:
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
    t_point = np.array([_ptime(o) for o in observations]) - start_time
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
    design = np.column_stack((t_point, np.ones(len(t_point))))
    target = points.copy()
    target[:, 2] += 0.5 * acceleration * t_point ** 2
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


def _search_result(fit, lower_frames, upper_frames, rest_point, rest_gap, upper_rest, stagger,
                   candidate_rejections, candidate_rejected_frames, skipped):
    """The stereo result dictionary for a flight found by the anchored search."""
    velocity = fit["velocity"]
    return {
        "method": "shared-tag-epipolar-v2",
        "detection": "anchored-flight-search",
        "candidateRejections": candidate_rejections,
        "candidateRejectedFrames": candidate_rejected_frames,
        "model": "flight",
        "frames": len(fit["frame_indices"]),
        "instants": fit["detections"],
        "frameIndices": fit["frame_indices"],
        "spanMs": round(fit["span"] * 1000, 2),
        "skippedFrames": skipped,
        "upperRestPx": [round(float(v), 2) for v in upper_rest],
        "restPointMm": [round(float(v) * 1000, 1) for v in rest_point],
        "restHeightErrorMm": round((float(rest_point[2]) - RADIUS) * 1000, 2),
        "restRayGapMm": round(rest_gap * 1000, 2),
        "medianRayGapMm": round(float(np.median(fit["ray_gaps"])), 2),
        "maxRayGapMm": round(float(max(fit["ray_gaps"])), 2),
        "rmsPx": round(fit["rms"], 3),
        "lowerRmsPx": round(fit["lower_rms"], 3),
        "upperRmsPx": round(fit["upper_rms"], 3),
        # The launch is anchored at the resting ball by construction.
        "startAnchorErrorMm": 0.0,
        "rawStartOffsetMm": 0.0,
        "impliedContactMs": round((fit["contact"] - fit["t_rest"]) * 1000, 2),
        "maxPairOffsetUs": 0.0,
        "staggered": stagger is not None,
        "staggerOffsetUs": None if stagger is None else round(stagger, 1),
        "speedMps": round(fit["speed"], 4),
        "speedSigmaMps": round(fit["speed_sigma"], 4),
        "launchDeg": round(fit["launch"], 3),
        "launchSigmaDeg": round(fit["launch_sigma"], 3),
        "headingDeg": round(fit["heading"], 3),
        "headingSigmaDeg": round(fit["heading_sigma"], 3),
        "speedDifferencePct": None, "launchDifferenceDeg": None, "headingDifferenceDeg": None,
        "velocityMps": velocity.tolist(),
        "searchScore": round(fit["score"], 2),
        "track": fit["track"],
    }


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
    stagger = stagger_offset_us(lower_frames, upper_frames)
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
    if stagger is not None and guided_track:
        ordered = sorted(guided_track, key=lambda item: lower_frames[item["frameIndex"]][0])
        track_times = np.array([lower_frames[item["frameIndex"]][0] for item in ordered])
        track_pixels = np.array([item["centerPx"] for item in ordered], float)
        gaps_s = np.diff([frame[0] for frame in lower_frames])
        period = float(np.median(gaps_s)) if len(gaps_s) else 1 / 242
    for point in guided_track:
        index = point["frameIndex"]
        if stagger is None:
            match_pixel = point["centerPx"]
            point_time = None
        else:
            # The top camera saw the ball half a frame later than the lower one: look for it on the
            # epipolar line of where the lower camera's track puts the ball at that instant.
            point_time = upper_frames[index][0]
            match_pixel = _pixel_at(track_times, track_pixels, point_time, period, 1.6 * period)
            if match_pixel is None:
                skipped.append(index)
                continue
        upper_px, score = _match_on_epipolar(lower, upper, image(index), template, half, match_pixel)
        if upper_px is None or score < MIN_MATCH_SCORE:
            skipped.append(index)
            continue
        position, gap = _triangulate(_ray(lower, match_pixel), _ray(upper, upper_px))
        observation = {"frameIndex": index, "lowerPx": list(point["centerPx"]), "upperPx": upper_px.tolist(),
                       "score": round(score, 3), "rayGapMm": round(gap * 1000, 2), "pointM": position.tolist(),
                       "lowerTime": lower_frames[index][0], "upperTime": upper_frames[index][0]}
        if stagger is not None:
            observation.update(pointTime=point_time, staggerOffsetUs=stagger)
        observations.append(observation)
    detection = "epipolar-template"
    candidate_rejections = None
    candidate_rejected_frames = None
    minimum_pairs = MIN_STAGGERED_PAIRS if stagger is not None else MIN_STEREO_FRAMES
    if mono_velocity is None or len(observations) < minimum_pairs:
        observations, candidate_rejections, candidate_rejected_frames = _independent_observations(
            lower, upper, lower_frames, upper_frames, rest_point, rest_end, stagger)
        detection = "independent-circles"
    searched = None
    if len(observations) < minimum_pairs or (len(observations) == 2 and stagger is None):
        # Pairing frame by frame failed or is thin. Try the anchored search over unpaired circles.
        try:
            rest_radii = [RADIUS * camera["K"][0, 0] / (camera["R"] @ rest_point + camera["t"])[2]
                          for camera in (lower, upper)]
            searched = _anchored_flight_search(lower, upper, lower_frames, upper_frames, rest_point, rest_end, rest_radii)
        except FlightSearchError as error:
            candidate_rejections = {**(candidate_rejections or {}), "flightSearch": str(error)}
    if searched is not None:
        return _search_result(searched, lower_frames, upper_frames, rest_point, rest_gap, upper_rest, stagger,
                              candidate_rejections, candidate_rejected_frames, skipped)
    if len(observations) == 2 and stagger is None:
        return _two_point_speed(lower, upper, observations, rest_point, rest_gap, upper_rest, start_time,
                                detection, candidate_rejections, candidate_rejected_frames, skipped)
    if len(observations) < minimum_pairs:
        raise StereoTrackingError(
            f"Stereo found {len(observations)} paired ball frames; needs {minimum_pairs}. "
            f"Independent detection rejections: {candidate_rejections}.",
            {"frames": len(observations), "frameIndices": [o["frameIndex"] for o in observations],
             "candidateRejections": candidate_rejections, "candidateRejectedFrames": candidate_rejected_frames,
             "detection": detection},
        )
    if stagger is not None:
        # The velocity baseline is the first to the last sample of either camera, not the triangulated points.
        raw_times = [t for o in observations for t in (o["lowerTime"], o["upperTime"])]
        span = max(raw_times) - min(raw_times)
    else:
        span = _ptime(observations[-1]) - _ptime(observations[0])
    minimum_span = MIN_STAGGERED_TIME_SPAN_S if stagger is not None else MIN_STEREO_TIME_SPAN_S
    if span < minimum_span:
        raise StereoTrackingError(
            f"Stereo paired frames span {span * 1000:.1f} ms; needs at least "
            f"{minimum_span * 1000:.0f} ms for a velocity estimate.",
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
    # For a staggered pair this is the jitter around the nominal offset, the quantity the timing gate limits.
    max_pair_offset = max(abs((o["upperTime"] - o["lowerTime"]) * 1e6 - (stagger or 0.0)) for o in observations)
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
        "instants": len(observations) * (2 if stagger is not None else 1),
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
        "staggered": stagger is not None,
        "staggerOffsetUs": None if stagger is None else round(stagger, 1),
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
