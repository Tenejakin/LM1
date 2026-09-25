"""Two-camera club measurement from the shaft/hosel vertex or the head. Version 1.1.0.

On the stand the clubhead is dark against a dark mat and barely segments; what
both cameras do see is the lit shaft and the hosel/top-line highlight, a "check"
shape whose lowest point is the hosel. That vertex is one physical point in both
views, so it is triangulated like the ball: no swing-plane assumption, no club
tag. Its 3D track gives club speed, attack angle and club path.

The single-camera swing-plane path read club speed about 25% low on real chips:
it pinned the hosel, which sits nearer the golfer than the ball, to a plane
through the ball. Replaying 15 real sand-wedge chips (2026-09-25) this path
resolved 12 of 15, with smash mostly 1.16-1.38 against 1.35-1.61 before.

A visible head (a chrome club, 2026-09-25) breaks the vertex: the lowest point then lies on
the rounded sole, which the two cameras see at different spots, and over a light floor the
head is darker than the background, so a brighter-only mask keeps just the shaft. The head
is therefore also found by absolute change in a ground-level window behind the ball, and
whichever point gives the longer consistent track is used.

Three frames are the minimum. Every further consistent frame joins the fit; with
five or more a constant-acceleration term follows the swing arc, so the velocity
is the one at the last frame before impact rather than the window's average
chord, which matters most for attack angle.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

import club_vision
from stereo_check import RADIUS, _project, _ray, _triangulate

MIN_FRAMES = 3
SEARCH_FRAMES = 12
# Rays through the two views' vertices must meet this closely to be one point.
# Measured gaps on real chips were 0-7 mm; the ball's gate is 3 mm on a sharper target.
MAX_RAY_GAP_M = 0.010
# Largest deviation of any kept frame from the fitted path. A larger jump means the
# vertex switched features (shaft end at the image edge, club meeting the ball).
# 10 mm recovered one more real chip than 8 mm; 12 mm admitted a track with a 29° path.
MAX_RESIDUAL_M = 0.010
CURVED_FIT_FRAMES = 5
MAX_FRAME_STEP = 2
MAX_HOSEL_HEIGHT_M = 0.3
EDGE_MARGIN_PX = 3
# Head window around the resting ball, in ball radii: ground level only, so the
# golfer's feet and the upper shaft are not part of the head.
HEAD_WINDOW_ABOVE_RADII = 3.0
HEAD_WINDOW_BELOW_RADII = 2.5
HEAD_WINDOW_AHEAD_RADII = 1.0
HEAD_CHANGE_THRESHOLD = 25
# The last frame before the ball moves can show the club already touching it. Neither
# keeping nor dropping it was better on real chips (2 shots each way), so both are tried.
CONTACT_FRAME_OPTIONS = (0, 1)
# Measured-grade gates.
MEASURED_FRAMES = 5
MEASURED_RAY_GAP_MM = 6.0
MEASURED_RESIDUAL_MM = 5.0


def hosel_pixel(frame, background, ball_pixel, ball_radius_px, ignore=None):
    """Sub-pixel lowest point of the moving club blob: the shaft/hosel vertex."""
    points = club_vision.club_silhouette(frame, background, ball_pixel, ball_radius_px, ignore)
    if points is None:
        return None
    height, width = frame.shape[:2]
    lowest = points[:, 1].max()
    vertex = points[points[:, 1] >= lowest - 1.5].mean(axis=0)
    # A blob cut by the image border has a false lowest point.
    if not (EDGE_MARGIN_PX <= vertex[0] < width - EDGE_MARGIN_PX and lowest < height - EDGE_MARGIN_PX):
        return None
    return vertex


def head_pixel(frame, background, ball_pixel, ball_radius_px, ignore=None):
    """Centroid of the club head: pixels that changed either way, at ground level behind the ball."""
    gray = club_vision.to_gray(frame)
    difference = cv2.GaussianBlur(cv2.absdiff(gray, background), (3, 3), 0)
    _, mask = cv2.threshold(difference, HEAD_CHANGE_THRESHOLD, 255, cv2.THRESH_BINARY)
    if ignore is not None:
        mask[ignore > 0] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    height, width = mask.shape
    x_stop = int(min(width, ball_pixel[0] + HEAD_WINDOW_AHEAD_RADII * ball_radius_px))
    y_start = int(max(0, ball_pixel[1] - HEAD_WINDOW_ABOVE_RADII * ball_radius_px))
    y_stop = int(min(height, ball_pixel[1] + HEAD_WINDOW_BELOW_RADII * ball_radius_px))
    window = np.zeros_like(mask)
    window[y_start:y_stop, :x_stop] = mask[y_start:y_stop, :x_stop]
    cv2.circle(window, tuple(int(round(v)) for v in ball_pixel), int(ball_radius_px * 1.15), 0, -1)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(window)
    if count < 2:
        return None
    blob = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[blob, cv2.CC_STAT_AREA] < max(40.0, 0.4 * ball_radius_px ** 2):
        return None
    if stats[blob, cv2.CC_STAT_LEFT] <= EDGE_MARGIN_PX:
        return None  # The head is still entering the view: its centroid is biased.
    return centroids[blob].astype(float)


def fit_motion(times, positions):
    """Velocity at the last sample and each sample's distance from the fitted path."""
    times, positions = np.asarray(times, float), np.asarray(positions, float)
    dt = times - times[-1]
    columns = [dt, np.ones(len(dt))]
    if len(dt) >= CURVED_FIT_FRAMES:
        columns.append(0.5 * dt ** 2)
    design = np.column_stack(columns)
    coefficients = np.linalg.lstsq(design, positions, rcond=None)[0]
    return coefficients[0], np.linalg.norm(design @ coefficients - positions, axis=1)


def consistent_run(samples):
    """Longest run of near-consecutive frames that one smooth path explains; latest wins ties."""
    best = []
    for start in range(len(samples)):
        for stop in range(start + MIN_FRAMES, len(samples) + 1):
            run = samples[start:stop]
            if run[-1]["frameIndex"] - run[-2]["frameIndex"] > MAX_FRAME_STEP:
                break
            _, residuals = fit_motion([s["time"] for s in run], [s["positionM"] for s in run])
            if residuals.max() <= MAX_RESIDUAL_M and (len(run), run[-1]["frameIndex"]) >= (
                    len(best), best[-1]["frameIndex"] if best else -1):
                best = run
    return best


def measure(lower_frames, upper_frames, impact_index, lower, upper, lower_background, upper_background,
            ball_center, accept=None):
    """Triangulated hosel track before impact and its velocity at the last tracked frame.

    ``lower``/``upper`` are stereo_check camera dicts; ``ball_center`` is the resting
    ball's world centre, used to mask it out of both views. ``accept(velocity)`` returns a
    reason a track is physically impossible, or None. Tracks are ranked by length and
    residual; a lower-ranked one is used only when every better one is impossible. Raises
    ValueError with the reason when no track of three consistent frames is acceptable.
    """
    if len(upper_frames) != len(lower_frames):
        raise ValueError("Top-camera burst does not pair frame-for-frame with the lower camera.")
    views = []
    for camera in (lower, upper):
        depth = float((camera["R"] @ ball_center + camera["t"])[2])
        if depth <= 0:
            raise ValueError("Ball is behind a camera; recalibrate both cameras.")
        views.append((_project(camera, [ball_center])[0], RADIUS * camera["K"][0, 0] / depth))
    window = range(max(0, impact_index - SEARCH_FRAMES), impact_index)
    ignore = [club_vision.persistent_change([burst[index][1] for index in window], background)
              for burst, background in ((lower_frames, lower_background), (upper_frames, upper_background))]
    located = {}
    for name, locate in (("hosel", hosel_pixel), ("head", head_pixel)):
        samples, gaps = [], []
        for index in window:
            lower_px = locate(lower_frames[index][1], lower_background, *views[0], ignore[0])
            upper_px = locate(upper_frames[index][1], upper_background, *views[1], ignore[1])
            if lower_px is None or upper_px is None:
                continue
            point, gap = _triangulate(_ray(lower, lower_px), _ray(upper, upper_px))
            gaps.append(round(gap * 1000, 1))
            if gap > MAX_RAY_GAP_M or not -0.01 <= point[2] <= MAX_HOSEL_HEIGHT_M:
                continue
            samples.append({"frameIndex": index, "time": lower_frames[index][0], "positionM": point,
                            "rayGapMm": gap * 1000, "lowerPx": list(map(float, lower_px)),
                            "upperPx": list(map(float, upper_px))})
        located[name] = (samples, gaps)

    candidates = []
    for name, (samples, gaps) in located.items():
        for excluded in CONTACT_FRAME_OPTIONS:
            run = consistent_run([s for s in samples if s["frameIndex"] < impact_index - excluded])
            if len(run) < MIN_FRAMES:
                candidates.append((len(run), 0.0, name, excluded, run, None))
                continue
            velocity, residuals = fit_motion([s["time"] for s in run], [s["positionM"] for s in run])
            candidates.append((len(run), -float(residuals.max()), name, excluded, run, velocity))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rejections = []
    chosen = None
    for length, _, name, excluded, run, velocity in candidates:
        if length < MIN_FRAMES:
            break
        problem = accept(velocity) if accept else None
        if problem is None:
            chosen = (name, excluded, run)
            break
        rejections.append(f"{name}{' without contact frame' if excluded else ''}: {problem}")
    best = candidates[0]
    point_used, excluded, run = chosen if chosen else (best[2], best[3], best[4])
    samples, gaps = located[point_used]
    diagnostics = {"method": "stereo-hosel-v1" if point_used == "hosel" else "stereo-head-v1",
                   "point": point_used, "contactFrameExcluded": bool(excluded),
                   "candidateFrames": len(gaps), "rayGapsMm": gaps, "triangulatedFrames": len(samples),
                   "runsByPoint": {name: max(len(item[4]) for item in candidates if item[2] == name) for name in located},
                   "rejectedTracks": rejections}
    if chosen is None and best[0] >= MIN_FRAMES:
        error = ValueError(f"Every consistent club track is physically impossible: {rejections[0]}")
        error.diagnostics = diagnostics
        raise error
    if len(run) < MIN_FRAMES:
        error = ValueError(
            f"Both cameras resolved the club ({point_used}) in {len(samples)} of the {SEARCH_FRAMES} frames before "
            f"impact, with {len(run)} following one smooth path; at least {MIN_FRAMES} are required. The head is "
            "in full view only briefly behind the ball: more room behind the ball in the image gives it more frames.")
        error.diagnostics = diagnostics
        raise error
    velocity, residuals = fit_motion([s["time"] for s in run], [s["positionM"] for s in run])
    rms = float(np.sqrt(np.mean(residuals ** 2)))
    diagnostics.update(
        acceptedFrames=len(run), frameIndices=[s["frameIndex"] for s in run],
        model="constant-acceleration" if len(run) >= CURVED_FIT_FRAMES else "constant-velocity",
        fitResidualMm=round(rms * 1000, 2), maxResidualMm=round(float(residuals.max()) * 1000, 2),
        medianRayGapMm=round(float(np.median([s["rayGapMm"] for s in run])), 2),
        speedMps=round(float(np.linalg.norm(velocity)), 3))
    return {"velocity": velocity, "track": run, "diagnostics": diagnostics}


def attack_angle_deg(velocity):
    return math.degrees(math.atan2(velocity[2], math.hypot(velocity[0], velocity[1])))
