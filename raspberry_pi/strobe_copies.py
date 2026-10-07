"""Ball speed and launch angle from the several ball copies one strobed frame holds.

In strobe mode the ESP32 fires a burst of short IR flashes inside one long exposure, so a
moving ball is recorded once per flash: a row of sharp bright discs, not one smear. The gaps
between flashes are known and uneven (see `light_controller.strobe_pattern`), so:

1. `find_copies` picks out the compact bright discs;
2. `fit_flash_track` works out which flash made each disc, by trying every possible start
   in the repeating flash sequence and keeping the one whose positions are straightest
   against the known flash times (the uneven gaps make a wrong start fit badly);
3. the slope of position against time, scaled by the ball's known diameter, is the speed.

Everything here is an image-plane estimate (side-on view, target to the right, scale from
the resting ball), and it only works when the flashes dominate the picture: in a dark room,
or with an ambient-only reference frame to subtract. It has been developed against synthetic
frames; real dark-room captures are still needed to tune the thresholds.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import cv2
import numpy as np

BALL_DIAMETER_MM = 42.67
MIN_AREA_RATIO = 0.25     # copy area as a fraction of the resting ball's disc
MAX_AREA_RATIO = 1.8
MIN_CIRCULARITY = 0.55
MIN_LEVEL = 8.0           # grey levels a copy must stand above the background (8-bit frames)
RAW_MIN_LEVEL = 15.0      # the same in raw 10-bit counts (about 2 eight-bit levels): raw has no processor curve crushing the dark end
RAW_SCALE = 64            # a raw frame word is the 10-bit count times this (words step by 64)
NOISE_SIGMAS = 6.0
AMBIGUITY_RATIO = 2.0     # the best start must fit this much better than the runner-up
MAX_RESIDUAL_MM = 3.0     # a fit looser than this is not trusted (a right pattern fits to well under 1 mm)
MIN_LAUNCH_DEG = -10.0    # a ball leaving the ground cannot head steeply down
MAX_LAUNCH_DEG = 80.0
THREE_COPY_SPEED_RANGE = (0.6, 1.6)  # three copies always fit a line, so they must also match the club's expected speed


def raw_to_counts(raw: Any, black_level: float) -> np.ndarray:
    """A raw frame as float 10-bit counts above the sensor's black level."""
    return (np.asarray(raw).astype(np.float32) - float(black_level)) / RAW_SCALE


def find_copies(frame: Any, ball_px: float, background: Any | None = None,
                min_level: float | None = None) -> list[dict[str, float]]:
    """Compact bright discs in the frame, with the empty/ambient `background` removed first."""
    image = np.asarray(frame)
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    difference = image.astype(np.float32)
    if background is not None:
        reference = np.asarray(background)
        if reference.ndim == 3:
            reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        difference -= reference.astype(np.float32)
    difference = cv2.GaussianBlur(difference, (0, 0), 1.5)
    median = float(np.median(difference))
    sigma = 1.4826 * float(np.median(np.abs(difference - median)))
    level = max(MIN_LEVEL if min_level is None else min_level, median + NOISE_SIGMAS * sigma)
    mask = (difference > level).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    disc = math.pi * (ball_px / 2.0) ** 2
    copies = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if not MIN_AREA_RATIO * disc <= area <= MAX_AREA_RATIO * disc:
            continue
        perimeter = cv2.arcLength(contour, True)
        circularity = 4.0 * math.pi * area / (perimeter * perimeter + 1e-6)
        if circularity < MIN_CIRCULARITY:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        peak = float(difference[y:y + h, x:x + w].max())
        copies.append({"x": moments["m10"] / moments["m00"], "y": moments["m01"] / moments["m00"],
                       "area": area, "peak": peak, "circularity": circularity})
    return copies


def flash_times_us(gaps_us: Sequence[float], period_us: float, count: int) -> list[float]:
    """Start time of each of the next `count` flashes: bursts repeat every `period_us`."""
    starts = [0.0]
    for gap in gaps_us:
        starts.append(starts[-1] + float(gap))
    per_burst = len(starts)
    return [(index // per_burst) * period_us + starts[index % per_burst] for index in range(count)]


def fit_flash_track(copies: Sequence[dict[str, float]], gaps_us: Sequence[float], period_us: float,
                    ball_px: float, expected_speed_mps: float | None = None) -> dict[str, Any] | None:
    """Speed and launch angle of the copies, or None when they do not line up.

    The copies are ordered along their direction of travel (to the right), then matched to
    consecutive flashes of the repeating sequence for every possible start; the start whose
    straight-line fit is tightest wins.
    """
    if len(copies) < 3 or ball_px <= 0:
        return None
    points = np.array([[c["x"], c["y"]] for c in copies], dtype=np.float64)
    centred = points - points.mean(axis=0)
    direction = np.linalg.svd(centred, full_matrices=False)[2][0]
    if direction[0] < 0:
        direction = -direction
    along = centred @ direction
    order = np.argsort(along)
    along = along[order]
    across = (centred @ np.array([-direction[1], direction[0]]))[order]
    if along[-1] - along[0] < 0.8 * ball_px:
        return None  # a stationary ball: nothing to time
    if np.ptp(across) > 0.9 * ball_px:
        return None  # not a straight row
    per_burst = len(gaps_us) + 1
    scale = BALL_DIAMETER_MM / ball_px
    fits = []
    for start in range(per_burst):
        times = np.array(flash_times_us(gaps_us, period_us, start + len(along))[start:])
        slope, intercept = np.polyfit(times, along, 1)
        if slope <= 0:
            continue
        residual = float(np.sqrt(np.mean((along - (slope * times + intercept)) ** 2)))
        speed = slope * 1e6 * scale / 1000.0  # px/us -> m/s
        fits.append((residual, start, float(speed), float(slope)))
    if not fits:
        return None
    if expected_speed_mps:
        # With few copies two starts can fit alike; the player's typical speed breaks the tie.
        fits.sort(key=lambda fit: (fit[0] / max(ball_px, 1.0)) + 0.002 * abs(fit[2] - expected_speed_mps))
    else:
        fits.sort(key=lambda fit: fit[0])
    best = fits[0]
    runner_up = fits[1][0] if len(fits) > 1 else float("inf")
    ambiguous = best[0] > 0 and runner_up < AMBIGUITY_RATIO * best[0] and len(along) < 5
    angle = math.degrees(math.atan2(-direction[1], direction[0]))
    residual_mm = best[0] * scale
    plausible = MIN_LAUNCH_DEG <= angle <= MAX_LAUNCH_DEG
    if len(along) >= 4:
        enough = True
    elif len(along) == 3 and expected_speed_mps:
        enough = THREE_COPY_SPEED_RANGE[0] * expected_speed_mps <= best[2] <= THREE_COPY_SPEED_RANGE[1] * expected_speed_mps
    else:
        enough = False
    return {
        "ballSpeedMps": round(best[2], 2),
        "launchAngleDeg": round(angle, 1),
        "copies": int(len(along)),
        "startFlash": int(best[1]),
        "fitResidualMm": round(best[0] * scale, 2),
        "ambiguous": bool(ambiguous),
        "reliable": bool(not ambiguous and residual_mm <= MAX_RESIDUAL_MM and plausible and enough),
        "mmPerPx": round(scale, 3),
    }


def fit_flash_pairs(pairs: Sequence[tuple[int, Sequence[dict[str, float]]]], gap_us: float, period_us: float,
                    ball_px: float, expected_speed_mps: float | None = None) -> dict[str, Any] | None:
    """Speed and launch angle from frames that each hold two flash copies (a one-gap pattern, used for slow balls).

    Slow balls need wide gaps between flashes, so a frame only holds two. `pairs` is `(n, copies)` per frame:
    `n` counts flash periods since the first pair frame and `copies` are the two discs of that frame.
    Because the camera's exposure is longer than the burst, the two flashes in a frame are either the burst's own
    pair (`gap_us` apart) or the last flash of one burst and the first of the next (`period_us - gap_us` apart);
    the same flash repeats every `period_us` from frame to frame. Both timings are fitted, the one whose points
    lie on the straighter line wins, and a near tie is marked ambiguous.
    """
    if len(pairs) < 2 or ball_px <= 0 or gap_us <= 0 or period_us <= gap_us:
        return None
    points = np.array([[c["x"], c["y"]] for _, copies in pairs for c in copies], dtype=np.float64)
    mean = points.mean(axis=0)
    direction = np.linalg.svd(points - mean, full_matrices=False)[2][0]
    if direction[0] < 0:
        direction = -direction
    scale = BALL_DIAMETER_MM / ball_px
    across_axis = np.array([-direction[1], direction[0]])
    along, base_times, slots, across = [], [], [], []
    for n, copies in pairs:
        ordered = sorted(copies, key=lambda c: (c["x"] - mean[0]) * direction[0] + (c["y"] - mean[1]) * direction[1])
        for slot, copy in enumerate(ordered):
            offset = np.array([copy["x"] - mean[0], copy["y"] - mean[1]])
            along.append(float(offset @ direction))
            across.append(float(offset @ across_axis))
            base_times.append(n * period_us)
            slots.append(slot)
    along = np.array(along)
    if along.max() - along.min() < 0.8 * ball_px:
        return None  # a stationary ball: nothing to time
    if np.ptp(across) > 0.9 * ball_px:
        return None  # not a straight row
    fits = []
    for gap, name in ((gap_us, "burst"), (period_us - gap_us, "cross-burst")):
        times = np.array(base_times, dtype=np.float64) + np.array(slots) * gap
        slope, intercept = np.polyfit(times, along, 1)
        if slope <= 0:
            continue
        residual = float(np.sqrt(np.mean((along - (slope * times + intercept)) ** 2)))
        fits.append((residual, float(slope * 1e6 * scale / 1000.0), name, gap))
    if not fits:
        return None
    fits.sort(key=lambda fit: fit[0])
    best = fits[0]
    runner_up = fits[1][0] if len(fits) > 1 else float("inf")
    ambiguous = runner_up < AMBIGUITY_RATIO * max(best[0], 0.1)
    angle = math.degrees(math.atan2(-direction[1], direction[0]))
    residual_mm = best[0] * scale
    speed = best[1]
    speed_ok = (not expected_speed_mps) or (
        THREE_COPY_SPEED_RANGE[0] * expected_speed_mps <= speed <= THREE_COPY_SPEED_RANGE[1] * expected_speed_mps)
    return {
        "ballSpeedMps": round(speed, 2),
        "launchAngleDeg": round(angle, 1),
        "copies": int(len(along)),
        "frames": int(len(pairs)),
        "method": "pairs",
        "pairTiming": best[2],
        "gapUs": int(best[3]),
        "startFlash": 0,
        "fitResidualMm": round(residual_mm, 2),
        "ambiguous": bool(ambiguous),
        "reliable": bool(not ambiguous and residual_mm <= MAX_RESIDUAL_MM and MIN_LAUNCH_DEG <= angle <= MAX_LAUNCH_DEG
                         and speed_ok),
        "mmPerPx": round(scale, 3),
    }


def analyse_frame(frame: Any, gaps_us: Sequence[float], period_us: float, ball_px: float,
                  background: Any | None = None, expected_speed_mps: float | None = None,
                  min_level: float | None = None) -> dict[str, Any]:
    """Find the copies in one frame and fit them. `fit` is None when nothing consistent was found."""
    copies = find_copies(frame, ball_px, background, min_level)
    return {"copies": copies, "fit": fit_flash_track(copies, gaps_us, period_us, ball_px, expected_speed_mps)}


def separation_speed_mps(gaps_us: Sequence[float]) -> float | None:
    """Speed above which the copies of the two closest flashes stop touching (one ball width apart)."""
    gaps = [float(g) for g in gaps_us if g and g > 0]
    return round(BALL_DIAMETER_MM / 1000.0 / (min(gaps) / 1e6), 1) if gaps else None


def _span_in_balls(copies: Sequence[dict[str, float]], ball_px: float) -> float:
    if len(copies) < 2 or ball_px <= 0:
        return 0.0
    xs = [c["x"] for c in copies]
    ys = [c["y"] for c in copies]
    return float(math.hypot(max(xs) - min(xs), max(ys) - min(ys)) / ball_px)


def estimate_from_frames(frames: Sequence[tuple[float, Any]], bounds: Sequence[float], start_index: int,
                         light: dict[str, Any] | None, search_frames: int = 14,
                         raw_frames: dict[int, Any] | None = None, raw_black: float = 1024.0) -> dict[str, Any] | None:
    """Best reliable fit over the frames just after the ball leaves, or None (see `estimate_with_report`)."""
    return estimate_with_report(frames, bounds, start_index, light, search_frames, raw_frames, raw_black)[0]


def estimate_with_report(frames: Sequence[tuple[float, Any]], bounds: Sequence[float], start_index: int,
                         light: dict[str, Any] | None, search_frames: int = 14,
                         raw_frames: dict[int, Any] | None = None, raw_black: float = 1024.0,
                         ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Best reliable fit over the frames just after the ball leaves, plus a report of how far the search got.

    `light` is the light controller's status: it only counts while the ring was strobing,
    and it carries the exact flash pattern and rate the ESP32 was running. The empty-scene
    background is the median of the last three frames, where the ball is gone. The report is
    always returned, with a `reason` code when no fit came out, so a failed strobe shot says
    whether the ring was not strobing, no copies showed, the copies merged, or they did not fit.
    """
    light = light or {}
    pattern = light.get("pattern") or {}
    gaps = pattern.get("gapsUs") or []
    report: dict[str, Any] = {
        "lightMode": light.get("mode"), "controllerConnected": light.get("connected"),
        "controllerReportedMode": light.get("reportedMode"), "controllerError": light.get("error"),
        "rateHz": light.get("rateHz"), "pulseUs": pattern.get("pulseUs"), "gapsUs": list(gaps),
        "expectedSpeedMps": pattern.get("ballSpeedMps"), "separatesAboveMps": separation_speed_mps(gaps),
        "framesSearched": 0, "maxCopies": 0, "maxCopySpanBalls": 0.0, "reason": None,
    }
    if not light:
        report["reason"] = "no-controller"
        return None, report
    if light.get("mode") != "strobe":
        report["reason"] = "not-strobing"
        return None, report
    if not pattern:
        report["reason"] = "no-pattern"
        return None, report
    if len(gaps) < 1 or len(frames) < start_index + 5:
        report["reason"] = "pattern-too-short" if len(gaps) < 1 else "too-few-frames"
        return None, report
    pair_mode = len(gaps) == 1   # a slow ball's pattern: two flashes per frame, so the fit runs across frames
    need = 2 if pair_mode else 3
    pairs: list[tuple[int, float, list[dict[str, float]]]] = []
    period_us = 1_000_000 // int(light.get("rateHz") or 242)
    ball_px = float(max(bounds[2], bounds[3]))
    report["ballPx"] = round(ball_px, 1)
    # Prefer the raw 10-bit frames: linear, and the faint flash copies are not crushed to black.
    tail = [raw_frames[i] for i in range(len(frames) - 3, len(frames)) if raw_frames and i in raw_frames]
    use_raw = bool(raw_frames) and len(tail) == 3
    if use_raw:
        background = np.median(np.stack([raw_to_counts(raw, raw_black) for raw in tail]), axis=0)
    else:
        background = np.median(np.stack([_gray_frame(image) for _, image in frames[-3:]]), axis=0).astype(np.uint8)
    report["source"] = "raw" if use_raw else "8bit"
    best = None
    unreliable = None
    for index in range(max(0, start_index - 1), min(len(frames) - 3, start_index + search_frames)):
        if use_raw and index in raw_frames:
            image, level = raw_to_counts(raw_frames[index], raw_black), RAW_MIN_LEVEL
        else:
            image, level = _gray_frame(frames[index][1]), None
            if use_raw:
                continue  # raw background cannot be subtracted from an 8-bit frame
        result = analyse_frame(image, gaps, period_us, ball_px, background,
                               expected_speed_mps=pattern.get("ballSpeedMps"), min_level=level)
        report["framesSearched"] += 1
        found = len(result["copies"])
        report["maxCopies"] = max(report["maxCopies"], found)
        report["maxCopySpanBalls"] = round(max(report["maxCopySpanBalls"], _span_in_balls(result["copies"], ball_px)), 2)
        fit = result["fit"]
        if pair_mode and found == 2:
            pairs.append((index, frames[index][0], result["copies"]))
        if fit and not fit["reliable"] and (unreliable is None or fit["copies"] > unreliable["copies"]):
            unreliable = fit
        if not fit or not fit["reliable"]:
            continue
        rank = (fit["copies"], -fit["fitResidualMm"])
        if best is None or rank > best["rank"]:
            best = {"rank": rank, "frameIndex": index, "fit": fit, "copiesFound": len(result["copies"]),
                    "source": "raw" if use_raw else "8bit"}
    if pair_mode:
        report["pairFrames"] = len(pairs)
        if len(pairs) >= 2:
            base = pairs[0][1]
            fit = fit_flash_pairs([(round((stamp - base) * 1e6 / period_us), copies) for _, stamp, copies in pairs],
                                  float(gaps[0]), float(period_us), ball_px, pattern.get("ballSpeedMps"))
            if fit and fit["reliable"]:
                best = {"frameIndex": pairs[0][0], "fit": fit, "copiesFound": fit["copies"],
                        "source": "raw" if use_raw else "8bit"}
            elif fit:
                unreliable = fit
    if best is None:
        if report["framesSearched"] == 0:
            report["reason"] = "no-usable-frames"
        elif report["maxCopies"] == 0:
            report["reason"] = "no-copies"
        elif report["maxCopies"] < need:
            report["reason"] = "too-few-copies"
        elif pair_mode and len(pairs) < 2:
            report["reason"] = "too-few-pairs"
        elif unreliable is not None:
            report["reason"] = "no-fit"
            report["unreliableFit"] = {key: unreliable[key] for key in ("copies", "fitResidualMm", "ambiguous", "ballSpeedMps")}
        else:
            report["reason"] = "no-fit"
        return None, report
    best.pop("rank", None)
    report["bestCopies"] = best["fit"]["copies"]
    if best["fit"].get("method") == "pairs":
        report["pairTiming"] = best["fit"]["pairTiming"]
    return best, report


def _gray_frame(image: Any) -> np.ndarray:
    array = np.asarray(image)
    return array if array.ndim == 2 else cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)


def metrics_from_fit(fit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Metric entries the app understands, marked as estimates with the reason."""
    if fit.get("method") == "pairs":
        reason = (f"Image-plane estimate from {fit['copies']} flash copies in {fit['frames']} frames (two per frame), timed by "
                  "the known flash gap and period. Depth and aim direction are not measured.")
    else:
        reason = (f"Image-plane estimate from {fit['copies']} flash copies of the ball in one frame, timed by the known "
                  "flash gaps. Depth and aim direction are not measured.")
    return {
        "ballSpeedMps": {"value": fit["ballSpeedMps"], "unit": "m/s", "status": "estimated", "reason": reason},
        "launchAngleDeg": {"value": fit["launchAngleDeg"], "unit": "deg", "status": "estimated", "reason": reason},
    }
