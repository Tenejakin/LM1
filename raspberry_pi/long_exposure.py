"""Ball speed and launch angle from long-exposure (strobe-mode) frames.

Strobe mode exposes for about 3.9 ms, so a moving ball is a smear, not a disc, and the
usual silhouette fit cannot run (launch measurement requires an exposure of 250 us or
less). The middle of the smear is still where the ball was half way through the
exposure, so following that middle frame to frame gives a usable image-plane speed and
launch angle. Where the room is dark enough that the ring's flashes dominate, a frame
holds several separate ball copies; this tracker follows the one nearest the predicted
position, so those frames work too, only less completely than a purpose-built copy fit.

Everything here is an estimate:

* distances use the resting ball's width as the scale (42.67 mm), so motion toward or
  away from the camera is not seen and the scale drifts as the ball changes distance;
* the image is assumed to look side-on at the flight, with the target to the right.

The numbers are labelled "estimated" with that reason wherever they are shown.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

BALL_DIAMETER_MM = 42.67
THRESHOLD = 35          # grey levels brighter than the empty scene (the ball against a dark mat)
MIN_AREA_RATIO = 0.5    # blob area as a fraction of the resting ball's disc
MAX_AREA_RATIO = 2.0    # a smeared ball is at most about 1.7x; the club head is 2.5x or more
MIN_CIRCULARITY = 0.5   # a smeared ball is a rounded capsule, not a perfect disc
MAX_ASPECT = 2.0
MAX_MISSES = 2          # lost frames before the track ends
MAX_TRACK_FRAMES = 40
FIT_POINTS = 4          # moving points used for the speed fit
MIN_MOVE_BALL_WIDTHS = 0.6  # first moving point is this far from the resting ball


def _gray(image: Any) -> np.ndarray:
    array = np.asarray(image)
    return array if array.ndim == 2 else cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)


def _blobs(frame: np.ndarray, background: np.ndarray, ball_px: float) -> list[dict[str, float]]:
    """Round, ball-sized regions that are brighter than the empty scene.

    The club head and shaft are brighter than the empty scene too, but they are large and
    elongated; the ball is a compact round smear. Shape, not size alone, tells them apart.
    """
    difference = cv2.GaussianBlur(frame, (5, 5), 0).astype(np.int16) - background.astype(np.int16)
    mask = (difference > THRESHOLD).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ball_area = math.pi * (ball_px / 2.0) ** 2
    found = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not MIN_AREA_RATIO * ball_area <= area <= MAX_AREA_RATIO * ball_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        circularity = 4.0 * math.pi * area / (perimeter * perimeter + 1e-6)
        x, y, w, h = cv2.boundingRect(contour)
        aspect = max(w, h) / max(1.0, min(w, h))
        fill = area / float(w * h)
        if circularity < MIN_CIRCULARITY or aspect > MAX_ASPECT or fill < 0.5:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            continue
        found.append({
            "x": moments["m10"] / moments["m00"], "y": moments["m01"] / moments["m00"], "area": area,
            "width": float(w), "height": float(h), "circularity": circularity,
        })
    return found


def _background(frames: Sequence[tuple[float, Any]]) -> np.ndarray:
    return np.median(
        np.stack([cv2.GaussianBlur(_gray(image), (5, 5), 0) for _, image in frames[-3:]]), axis=0,
    ).astype(np.uint8)


def _follow(blob_lists: Sequence[list[dict[str, float]]], times: Sequence[float], first_index: int,
            last: tuple[float, float], velocity: tuple[float, float], ball_px: float,
            points: list[dict[str, float]]) -> list[dict[str, float]]:
    """Greedy nearest-to-prediction tracking, one ball-sized blob per frame."""
    misses = 0
    for index in range(first_index, min(len(blob_lists), first_index + MAX_TRACK_FRAMES)):
        predicted = (last[0] + velocity[0], last[1] + velocity[1])
        reach = max(1.2 * ball_px, 1.6 * math.hypot(*velocity) + 0.8 * ball_px)
        best = None
        for blob in blob_lists[index]:
            distance = math.hypot(blob["x"] - predicted[0], blob["y"] - predicted[1])
            if distance > reach:
                continue
            # A ball-sized smear beats a club, a leg or a shadow that happens to be close.
            size = blob["area"] / (math.pi * (ball_px / 2.0) ** 2)
            score = distance / reach + 0.15 * abs(math.log(size)) + 0.3 * (1.0 - blob["circularity"])
            if best is None or score < best[0]:
                best = (score, blob)
        if best is None:
            misses += 1
            if misses > MAX_MISSES:
                break
            continue
        misses = 0
        blob = best[1]
        velocity = (blob["x"] - last[0], blob["y"] - last[1])
        last = (blob["x"], blob["y"])
        points.append({"frameIndex": index, "t": float(times[index]), "x": blob["x"], "y": blob["y"],
                       "area": blob["area"], "extentPx": max(blob["width"], blob["height"])})
    return points


def track_blurred_ball(frames: Sequence[tuple[float, Any]], bounds: Sequence[float], start_index: int,
                       free_start: bool = False) -> list[dict[str, float]]:
    """Follow the ball from its resting position through the frames after `start_index`.

    `frames` are (seconds, image) pairs; `bounds` is the resting ball's (x, y, w, h) box.
    The background is the median of the last three frames, where the ball has left.
    `free_start` is for saved capture folders, which keep only the frames around the hit, so
    the ball may already be well away from its resting spot: it then tries every blob in the
    first frames as a starting point and keeps the track that travels furthest, which is
    the ball and not a foot or a shadow.
    """
    if len(frames) < start_index + 4:
        return []
    background = _background(frames)
    times = [t for t, _ in frames]
    x, y, w, h = bounds
    ball_px = float(max(w, h))
    blob_lists = [_blobs(_gray(image), background, ball_px) for _, image in frames[:-3]]
    resting = (x + w / 2.0, y + h / 2.0)

    if not free_start:
        points = _follow(blob_lists, times, max(0, start_index), resting, (0.0, 0.0), ball_px, [])
    else:
        best: list[dict[str, float]] = []
        best_travel = 0.0
        for k in range(0, min(3, len(blob_lists))):
            for blob in blob_lists[k]:
                seed = {"frameIndex": k, "t": float(times[k]), "x": blob["x"], "y": blob["y"],
                        "area": blob["area"], "extentPx": max(blob["width"], blob["height"])}
                track = _follow(blob_lists, times, k + 1, (blob["x"], blob["y"]), (0.0, 0.0), ball_px, [seed])
                travel = max(math.hypot(p["x"] - seed["x"], p["y"] - seed["y"]) for p in track)
                if len(track) >= 4 and travel > best_travel:
                    best, best_travel = track, travel
        return best

    # Keep only the part of the path after the ball has really left its resting spot.
    return [p for p in points if math.hypot(p["x"] - resting[0], p["y"] - resting[1]) >= MIN_MOVE_BALL_WIDTHS * ball_px]


def estimate_launch(points: Sequence[dict[str, float]], ball_px: float, exposure_us: float | None = None
                    ) -> dict[str, Any] | None:
    """Speed and launch angle from the first few moving points."""
    if len(points) < 3 or ball_px <= 0:
        return None
    fit = list(points[:FIT_POINTS])
    t = np.array([p["t"] for p in fit]) - fit[0]["t"]
    if np.ptp(t) <= 0:
        return None
    scale = BALL_DIAMETER_MM / ball_px  # mm per pixel at the resting ball
    vx = float(np.polyfit(t, [p["x"] for p in fit], 1)[0])
    vy = float(np.polyfit(t, [p["y"] for p in fit], 1)[0])
    speed = math.hypot(vx, vy) * scale / 1000.0
    angle = math.degrees(math.atan2(-vy, abs(vx)))
    # Residual of the straight-line fit, in millimetres, as a quality number.
    px = np.polyval(np.polyfit(t, [p["x"] for p in fit], 1), t)
    py = np.polyval(np.polyfit(t, [p["y"] for p in fit], 1), t)
    residual = float(np.sqrt(np.mean((px - [p["x"] for p in fit]) ** 2 + (py - [p["y"] for p in fit]) ** 2))) * scale
    blur_mm = speed * 1000.0 * (exposure_us or 0) / 1e6
    return {
        "ballSpeedMps": round(speed, 2),
        "launchAngleDeg": round(angle, 1),
        "fitPoints": len(fit),
        "fitResidualMm": round(residual, 1),
        "smearMm": round(blur_mm, 1),
        "mmPerPx": round(scale, 3),
        "movesRight": vx >= 0,
    }


def analyse_capture(frames: Sequence[tuple[float, Any]], bounds: Sequence[float], start_index: int,
                    exposure_us: float | None, free_start: bool = False) -> dict[str, Any]:
    """Track the ball and estimate its launch; always returns a dict (`estimate` may be None)."""
    ball_px = float(max(bounds[2], bounds[3]))
    points = track_blurred_ball(frames, bounds, start_index, free_start)
    return {"points": points, "estimate": estimate_launch(points, ball_px, exposure_us), "ballPx": ball_px}


def metrics_from_estimate(estimate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The metric entries the app understands, all marked as estimates with the reason."""
    reason = ("Image-plane estimate from blurred long-exposure frames: the ball's smear centre, scaled by the "
              "resting ball's width. Depth and aim direction are not measured.")
    return {
        "ballSpeedMps": {"value": estimate["ballSpeedMps"], "unit": "m/s", "status": "estimated", "reason": reason},
        "launchAngleDeg": {"value": estimate["launchAngleDeg"], "unit": "deg", "status": "estimated", "reason": reason},
    }


def load_saved_capture(directory: Path) -> tuple[list[tuple[float, Any]], dict[str, Any], int]:
    """Frames, manifest and first saved frame index of a capture folder (the service keeps 20 frames)."""
    manifest = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
    present = sorted(int(path.name[6:10]) for path in directory.glob("frame-*.jpg"))
    times = manifest["frameTimesMs"]
    frames = [(times[index] / 1000.0, cv2.imread(str(directory / f"frame-{index:04d}.jpg"), cv2.IMREAD_GRAYSCALE))
              for index in present]
    return frames, manifest, present[0]


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: long_exposure.py <capture-folder> [--write]")
        return 2
    directory = Path(argv[0])
    frames, manifest, first = load_saved_capture(directory)
    exposure = (manifest.get("frameMetadata") or [{}])[0].get("ExposureTime")
    # Saved folders keep only the frames around the hit, so start at the first one.
    result = analyse_capture(frames, manifest["ballBounds"], 0, exposure, free_start=True)
    for point in result["points"]:
        print(f"  frame {first + int(point['frameIndex'])}: ({point['x']:.0f}, {point['y']:.0f}) extent {point['extentPx']:.0f}px")
    print("estimate:", result["estimate"])
    if "--write" in argv and result["estimate"]:
        path = directory / "long-exposure.json"
        path.write_text(json.dumps({**result, "exposureUs": exposure}, indent=2), encoding="utf-8")
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
