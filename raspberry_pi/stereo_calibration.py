"""Version 1.0: paired checkerboard calibration, staging, validation and activation.

Run `python stereo_calibration.py --help` for offline session solving. Intrinsics
stay fixed. R/T transform primary-camera coordinates into secondary coordinates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

LOCK = threading.RLock()
MIN_PAIRS = 16
MAX_PAIRS = 48
_pause_until = 0.0


def pause_capture(enabled=True):
    global _pause_until
    _pause_until = time.monotonic() + 120 if enabled else 0.0


def capture_paused():
    return time.monotonic() < _pause_until


def root():
    return Path(os.getenv("PINPOINT_STEREO_PATH", "/var/lib/pinpoint/stereo"))


def read(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def lens_inputs(size):
    from launch_measurements import load_setup
    return [{"cameraMatrix": k.tolist(), "distCoeffs": d.tolist()}
            for k, d in (load_setup(size), load_setup(size, "secondary"))]


def fingerprint(lenses, size, indices):
    return hashlib.sha256(json.dumps([lenses, list(size), indices], sort_keys=True).encode()).hexdigest()


def session():
    pointer = read(root() / "current.json")
    if not pointer:
        raise ValueError("Start a stereo calibration session first.")
    sid = str(uuid.UUID(pointer["id"]))
    path = root() / "sessions" / sid
    return path, read(path / "session.json")


def summary(result):
    if not result:
        return None
    return {key: result[key] for key in ("id", "passed", "rmsPx", "validationRmsPx", "validationMaxPx",
            "baselineMm", "trainingPairs", "validationPairs", "failures")}


def status():
    with LOCK:
        try:
            path, data = session()
        except ValueError:
            path, data = None, None
        return {"version": 1, "minimumPairs": MIN_PAIRS, "maximumPairs": MAX_PAIRS,
                "sessionId": data["id"] if data else None,
                "board": data["board"] if data else None,
                "pairs": len(data["pairs"]) if data else 0,
                "candidate": summary(read(path / "candidate.json")) if path else None,
                "active": summary(read(root() / "active.json"))}


def start(columns, rows, square_mm):
    if (isinstance(columns, bool) or isinstance(rows, bool) or not isinstance(columns, int)
            or not isinstance(rows, int) or not 3 <= columns <= 15 or not 3 <= rows <= 15
            or not isinstance(square_mm, (int, float)) or not math.isfinite(square_mm) or not 3 <= square_mm <= 100):
        raise ValueError("Use 3–15 inner corners per side and a measured square size of 3–100 mm.")
    with LOCK:
        sid = str(uuid.uuid4())
        write(root() / "sessions" / sid / "session.json", {"id": sid, "board": {
            "columns": columns, "rows": rows, "squareMm": square_mm}, "pairs": []})
        write(root() / "current.json", {"id": sid})
        return status()


def grid_for(board):
    cols, rows = board["columns"], board["rows"]
    grid = np.zeros((cols * rows, 3), np.float32)
    grid[:, :2] = np.mgrid[:cols, :rows].T.reshape(-1, 2) * board["squareMm"] / 1000
    return grid


def capture_pair(first, second, timestamps, indices):
    with LOCK:
        path, data = session()
        if second is None or first.shape != second.shape:
            raise ValueError("Both cameras must stream the same image size.")
        if not all(isinstance(t, (int, float)) and math.isfinite(t) and t > 0 for t in timestamps):
            raise ValueError("Both images need sensor timestamps.")
        offset = abs(timestamps[0] - timestamps[1]) / 1000
        if offset > 250:
            raise ValueError(f"Pair timing differs by {offset:.0f} µs; wait for synchronization.")
        size = list(first.shape[1::-1])
        lenses = lens_inputs(size)
        stamp = fingerprint(lenses, size, indices)
        if data.get("fingerprint", stamp) != stamp:
            raise ValueError("Camera order, lens calibration or resolution changed. Start a new session.")
        if len(data["pairs"]) >= MAX_PAIRS:
            raise ValueError("Session is full. Solve it or start a new session.")
        board = data["board"]
        points = []
        for label, frame in (("bottom", first), ("top", second)):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            ok, corners = cv2.findChessboardCornersSB(gray, (board["columns"], board["rows"]))
            if not ok:
                raise ValueError(f"Complete checkerboard not found in the {label} camera. Hold it still, improve light and check inner-corner counts.")
            xy = corners.reshape(-1, 2)
            if np.any(xy < 8) or np.any(xy > np.array(size) - 9):
                raise ValueError(f"Board is too close to the {label} image edge.")
            points.append(xy)
        # Compare sets, not ordering: symmetric boards may reverse corner order.
        for previous in data["pairs"]:
            old = np.asarray(previous["points"][0])
            distances = np.linalg.norm(points[0][:, None, :] - old[None, :, :], axis=2)
            if float(np.sqrt(np.mean(np.min(distances, axis=1) ** 2))) < 4:
                raise ValueError("This pose is too similar to a saved pair. Move or tilt the board.")
        index = len(data["pairs"])
        for label, frame in (("primary", first), ("secondary", second)):
            if not cv2.imwrite(str(path / f"pair-{index:03d}-{label}.png"), frame):
                raise OSError("Could not save paired calibration images.")
        data.update(imageSize=size, lenses=lenses, cameraIndices=indices, fingerprint=stamp)
        data["pairs"].append({"points": [p.tolist() for p in points], "timestampsNs": timestamps,
                              "offsetUs": offset})
        write(path / "session.json", data)
        # A result is only activatable for the exact dataset it was solved on.
        if (path / "candidate.json").exists():
            (path / "candidate.json").replace(path / "previous-candidate.json")
        return status()


def pose(grid, points, lens):
    ok, rv, t = cv2.solvePnP(grid, np.asarray(points, np.float32), np.asarray(lens["cameraMatrix"]),
                            np.asarray(lens["distCoeffs"]), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or t[2, 0] <= 0:
        raise ValueError("Checkerboard pose could not be solved.")
    return cv2.Rodrigues(rv)[0], t.reshape(3)


def variants(points, board):
    array = np.asarray(points, np.float32).reshape(board["rows"], board["columns"], 2)
    turns = (0, 1, 2, 3) if board["rows"] == board["columns"] else (0, 2)
    return [np.rot90(array, k).reshape(-1, 2).copy() for k in turns]


def align_training(grid, pairs, lenses, board):
    # Pick the fixed relative transform supported across varied board poses.
    choices = []
    for pair in pairs:
        r1, t1 = pose(grid, pair[0], lenses[0])
        group = []
        for p2 in variants(pair[1], board):
            r2, t2 = pose(grid, p2, lenses[1])
            r = r2 @ r1.T
            group.append((r, t2 - r @ t1, p2))
        choices.append(group)

    def distance(a, b):
        return np.linalg.norm(a[0] - b[0]) + 5 * np.linalg.norm(a[1] - b[1])

    best = min((candidate for group in choices for candidate in group),
               key=lambda candidate: sum(min(distance(candidate, option) for option in group) for group in choices))
    return [(np.asarray(pair[0], np.float32), min(group, key=lambda v: distance(best, v))[2])
            for pair, group in zip(pairs, choices)]


def solve_data(data):
    if len(data["pairs"]) < MIN_PAIRS:
        raise ValueError(f"Capture at least {MIN_PAIRS} distinct paired views (12 fit + 4 validation).")
    board, lenses, size = data["board"], data["lenses"], tuple(data["imageSize"])
    grid = grid_for(board)
    train = [p["points"] for i, p in enumerate(data["pairs"]) if i % 4 != 3]
    held = [p["points"] for i, p in enumerate(data["pairs"]) if i % 4 == 3]
    aligned = align_training(grid, train, lenses, board)
    centers = np.array([p[0].mean(axis=0) for p in aligned]) / np.array(size)
    normals = np.array([pose(grid, p[0], lenses[0])[0][:, 2] for p in aligned])
    if max(np.ptp(centers, axis=0)) < .12 or np.max(np.linalg.norm(normals - normals[0], axis=1)) < .15:
        raise ValueError("Not enough board position and tilt variety. Cover more of both images and tilt in different directions.")
    k1, k2 = [np.asarray(l["cameraMatrix"], float) for l in lenses]
    d1, d2 = [np.asarray(l["distCoeffs"], float) for l in lenses]
    rms, _, _, _, _, r, t, _, _ = cv2.stereoCalibrate(
        [grid] * len(aligned), [p[0] for p in aligned], [p[1] for p in aligned],
        k1, d1, k2, d2, size, flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-8))
    t = t.reshape(3)
    errors = []
    for p1, p2 in held:
        r1, t1 = pose(grid, p1, lenses[0])
        projected = cv2.projectPoints(grid, cv2.Rodrigues(r @ r1)[0], r @ t1 + t, k2, d2)[0].reshape(-1, 2)
        errors.append(min(float(np.sqrt(np.mean(np.sum((projected - v) ** 2, axis=1))))
                          for v in variants(p2, board)))
    validation = float(np.sqrt(np.mean(np.square(errors))))
    baseline = float(np.linalg.norm(t) * 1000)
    failures = []
    if not all(math.isfinite(v) for v in (rms, validation, baseline, *errors)):
        raise ValueError("Calibration produced non-finite values.")
    if rms > .7:
        failures.append("Training error exceeds 0.7 px; check lens calibration, board flatness and sharpness.")
    if validation > 1.0 or max(errors) > 2.0:
        failures.append("Unseen-view error exceeds 1 px RMS or 2 px on one view. Capture better distributed, sharper pairs.")
    if not 10 <= baseline <= 1000:
        failures.append("Camera separation is outside the supported 10–1000 mm range. Check board size and correspondences.")
    return {"version": 1, "id": str(uuid.uuid4()), "sessionId": data["id"], "passed": not failures,
            "rmsPx": float(rms), "validationRmsPx": validation, "validationMaxPx": max(errors),
            "baselineMm": baseline, "trainingPairs": len(train), "validationPairs": len(held),
            "failures": failures, "rotation": r.tolist(), "translationM": t.tolist(),
            "fingerprint": data["fingerprint"], "imageSize": list(size), "lenses": lenses,
            "cameraIndices": data["cameraIndices"], "board": board}


def solve():
    with LOCK:
        path, data = session()
        try:
            result = solve_data(data)
        except cv2.error as error:
            raise ValueError("Stereo solver could not fit these images. Check board dimensions and recapture sharper, varied pairs.") from error
        write(path / "candidate.json", result)
        return status()


def activate(candidate_id, indices):
    with LOCK:
        path, data = session()
        result = read(path / "candidate.json")
        if not result or result["id"] != candidate_id or not result["passed"]:
            raise ValueError("Solve and pass validation before activating this candidate.")
        if fingerprint(lens_inputs(result["imageSize"]), result["imageSize"], indices) != result["fingerprint"]:
            raise ValueError("Lens calibration or camera order changed. Start a new session.")
        destination = root() / "active.json"
        if destination.exists():
            backup = root() / "backups" / f"{uuid.uuid4()}.json"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
        write(destination, result)
        return status()


def fixed_secondary_pose(lower_camera, upper_lens, size, indices):
    """Return fixed-pair upper world pose, or None when no pair has been activated.

    An incompatible active calibration raises: never silently use stale geometry.
    """
    result = read(root() / "active.json")
    if result is None:
        return None
    lenses = [{"cameraMatrix": np.asarray(k).tolist(), "distCoeffs": np.asarray(d).tolist()}
              for k, d in (lower_camera[:2], upper_lens)]
    if fingerprint(lenses, size, indices) != result["fingerprint"]:
        raise ValueError("Stereo calibration no longer matches lenses, resolution or camera order; recalibrate the pair.")
    r, t = np.asarray(result["rotation"]), np.asarray(result["translationM"])
    if not result.get("passed") or r.shape != (3, 3) or t.shape != (3,) or not np.all(np.isfinite(t)) or not np.allclose(r.T @ r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1):
        raise ValueError("Saved stereo calibration is invalid; recalibrate the pair.")
    return {"rotation": r @ lower_camera[2], "translation": r @ lower_camera[3] + t,
            "errorPx": result["validationRmsPx"], "source": "fixed-pair", "calibrationId": result["id"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True, help="Saved session.json with paired corners and lens inputs")
    parser.add_argument("--output", type=Path, required=True, help="Candidate JSON output (never activates automatically)")
    args = parser.parse_args()
    candidate = solve_data(read(args.session))
    write(args.output, candidate)
    print(json.dumps(summary(candidate), indent=2))
