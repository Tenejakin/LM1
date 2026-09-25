"""Two-camera club measurement from the shaft/hosel vertex. Version 1.0.0.

On the stand the clubhead is dark against a dark mat and barely segments; what
both cameras do see is the lit shaft and the hosel/top-line highlight, a "check"
shape whose lowest point is the hosel. That vertex is one physical point in both
views, so it is triangulated like the ball: no swing-plane assumption, no club
tag. Its 3D track gives club speed, attack angle and club path.

The single-camera swing-plane path read club speed about 25% low on real chips:
it pinned the hosel, which sits nearer the golfer than the ball, to a plane
through the ball. Replaying 15 real sand-wedge chips (2026-09-25) this path
resolved 12 of 15, with smash mostly 1.16-1.38 against 1.35-1.61 before.

Three frames are the minimum. Every further consistent frame joins the fit; with
five or more a constant-acceleration term follows the swing arc, so the velocity
is the one at the last frame before impact rather than the window's average
chord, which matters most for attack angle.
"""

from __future__ import annotations

import math

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
# Measured-grade gates.
MEASURED_FRAMES = 5
MEASURED_RAY_GAP_MM = 6.0
MEASURED_RESIDUAL_MM = 5.0


def hosel_pixel(frame, background, ball_pixel, ball_radius_px):
    """Sub-pixel lowest point of the moving club blob: the shaft/hosel vertex."""
    points = club_vision.club_silhouette(frame, background, ball_pixel, ball_radius_px)
    if points is None:
        return None
    height, width = frame.shape[:2]
    lowest = points[:, 1].max()
    vertex = points[points[:, 1] >= lowest - 1.5].mean(axis=0)
    # A blob cut by the image border has a false lowest point.
    if not (EDGE_MARGIN_PX <= vertex[0] < width - EDGE_MARGIN_PX and lowest < height - EDGE_MARGIN_PX):
        return None
    return vertex


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
            ball_center):
    """Triangulated hosel track before impact and its velocity at the last tracked frame.

    ``lower``/``upper`` are stereo_check camera dicts; ``ball_center`` is the resting
    ball's world centre, used to mask it out of both views. Raises ValueError with the
    reason when fewer than three consistent frames survive.
    """
    if len(upper_frames) != len(lower_frames):
        raise ValueError("Top-camera burst does not pair frame-for-frame with the lower camera.")
    views = []
    for camera in (lower, upper):
        depth = float((camera["R"] @ ball_center + camera["t"])[2])
        if depth <= 0:
            raise ValueError("Ball is behind a camera; recalibrate both cameras.")
        views.append((_project(camera, [ball_center])[0], RADIUS * camera["K"][0, 0] / depth))
    samples, gaps = [], []
    for index in range(max(0, impact_index - SEARCH_FRAMES), impact_index):
        lower_px = hosel_pixel(lower_frames[index][1], lower_background, *views[0])
        upper_px = hosel_pixel(upper_frames[index][1], upper_background, *views[1])
        if lower_px is None or upper_px is None:
            continue
        point, gap = _triangulate(_ray(lower, lower_px), _ray(upper, upper_px))
        gaps.append(round(gap * 1000, 1))
        if gap > MAX_RAY_GAP_M or not -0.01 <= point[2] <= MAX_HOSEL_HEIGHT_M:
            continue
        samples.append({"frameIndex": index, "time": lower_frames[index][0], "positionM": point,
                        "rayGapMm": gap * 1000, "lowerPx": lower_px.tolist(), "upperPx": upper_px.tolist()})
    diagnostics = {"method": "stereo-hosel-v1", "candidateFrames": len(gaps), "rayGapsMm": gaps,
                   "triangulatedFrames": len(samples)}
    run = consistent_run(samples)
    if len(run) < MIN_FRAMES:
        error = ValueError(
            f"Both cameras resolved the shaft/hosel in {len(samples)} of the {SEARCH_FRAMES} frames before impact, "
            f"with {len(run)} following one smooth path; at least {MIN_FRAMES} are required.")
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
