"""v1.0.0: replay saved captures with the AprilTag ground pose and with the level-rig pose.

Read-only. Each capture is measured again from its own frames, lens data and stereo pair
(all taken from its manifest, so both runs see identical inputs), once with the saved tag
pose and once with the level rig. The report says how far the rig moves every metric and
what height correction the resting ball asked of the rig's camera-height constant.

    python scripts/compare-ground-modes.py /var/lib/pinpoint/rolling-captures out.json \
        --limit 40 --rig-from-manifest --perturb-pitch 0.5
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "raspberry_pi"))
import launch_measurements as lm  # noqa: E402
import rig_pose  # noqa: E402
import stereo_calibration  # noqa: E402

METRICS = ("ballSpeedMps", "launchAngleDeg", "startDirectionDeg", "clubSpeedMps", "smashFactor",
           "attackAngleDeg", "clubPathDeg")


def load_capture(folder: Path):
    manifest = json.loads((folder / "capture.json").read_text())
    original = json.loads((folder / "analysis.json").read_text())
    secondary = json.loads((folder / "camera-secondary/capture.json").read_text())
    epoch = manifest["frameMetadata"][0]["SensorTimestamp"]

    def frames(directory, metadata):
        return [((m["SensorTimestamp"] - epoch) / 1e9, cv2.imread(str(directory / f"frame-{i:04d}.jpg"), cv2.IMREAD_GRAYSCALE))
                for i, m in enumerate(metadata)]

    lower = frames(folder, manifest["frameMetadata"])
    upper = frames(folder / "camera-secondary", secondary["frameMetadata"])
    if any(image is None for _, image in lower + upper):
        raise ValueError("some frames are missing")
    diagnostics = original["measurements"]["diagnostics"]
    if diagnostics.get("preprocessing", {}).get("denoise") == "bilateral":
        lower = [(t, cv2.bilateralFilter(im, 5, 12, 3)) for t, im in lower]
    return manifest, original, lower, upper


def tag_pose(manifest, camera):
    calibration = manifest["secondaryAprilTagCalibration" if camera == "secondary" else "aprilTagCalibration"]
    data = calibration["groundPose"]
    return lm.ground_surface_pose({"rotation": np.array(data["rotation"]), "translation": np.array(data["translationM"]),
                                   "errorPx": data["errorPx"], "capturedAt": calibration["capturedAt"],
                                   "source": "stored-calibration", "frameIndex": None})


def rig_from_manifest(manifest):
    """Rig constants fused from both tag poses through the stereo pair, as ``rig_pose --from-tags`` does."""
    lower, upper = tag_pose(manifest, "primary"), tag_pose(manifest, "secondary")
    return rig_pose.derive_from_tags(lower, upper, np.array(manifest["stereoCalibration"]["rotation"]))


def measure(manifest, original, lower, upper, mode, rig=None):
    stereo = manifest["stereoCalibration"]
    calibrations = [manifest["aprilTagCalibration"], manifest["secondaryAprilTagCalibration"]]

    def setup(image_size, camera="primary"):
        data = calibrations[camera == "secondary"]["groundPose"]
        assert list(image_size) == data["imageSize"]
        return np.array(data["cameraMatrix"]), np.array(data["distCoeffs"])

    def stored(image_size, ground_id, size, matrix, distortion, camera="primary"):
        return tag_pose(manifest, camera)

    def fixed_pair(lower_camera, upper_lens, size, indices):
        r, t = np.asarray(stereo["rotation"]), np.asarray(stereo["translationM"])
        return {"rotation": r @ lower_camera[2], "translation": r @ lower_camera[3] + t,
                "errorPx": stereo["validationRmsPx"], "source": "fixed-pair", "calibrationId": stereo["id"]}

    with tempfile.TemporaryDirectory() as scratch:
        env = {"PINPOINT_GROUND_MODE": mode, "PINPOINT_CLUB_MARKER_PATH": str(Path(scratch) / "no-club-marker.json"),
               "PINPOINT_RIG_PATH": str(Path(scratch) / "rig.json")}
        if rig is not None:
            (Path(scratch) / "rig.json").write_text(json.dumps({**rig, "version": 1, "source": "replay"}))
        with patch.dict(os.environ, env), patch.object(lm, "load_setup", side_effect=setup), \
                patch.object(lm, "stored_ground_pose", side_effect=stored), \
                patch.object(stereo_calibration, "fixed_secondary_pose", side_effect=fixed_pair):
            return lm.measure_launch(lower, manifest["ballBounds"],
                                     original.get("firstMovingFrameIndex") or original["coarseDepartureFrameIndex"],
                                     "sensor", max(m["ExposureTime"] for m in manifest["frameMetadata"]),
                                     original["track"], upper)


def values(result):
    metrics = result.get("metrics", {})
    out = {key: metrics.get(key, {}).get("value") for key in METRICS}
    diagnostics = result.get("diagnostics", {})
    out["_method"] = result.get("method")
    out["_stereo"] = bool((diagnostics.get("stereo") or {}).get("accepted"))
    surface = diagnostics.get("surface") or {}
    out["_surfaceOffsetMm"] = surface.get("offsetMm")
    out["_failure"] = result.get("failure")
    out["_status"] = {key: metrics.get(key, {}).get("status") for key in ("ballSpeedMps", "launchAngleDeg", "startDirectionDeg")}
    return out


def summarize(rows, label, key):
    deltas = {metric: [] for metric in METRICS}
    for row in rows:
        a, b = row["tag"], row[key]
        for metric in METRICS:
            if isinstance(a[metric], (int, float)) and isinstance(b[metric], (int, float)):
                deltas[metric].append(b[metric] - a[metric])
    lines = [f"--- {label} minus tag ---", f"{'metric':<20}{'n':>4}{'mean':>9}{'median':>9}{'sd':>8}{'max|d|':>9}"]
    for metric, items in deltas.items():
        if not items:
            lines.append(f"{metric:<20}{0:>4}")
            continue
        sd = statistics.pstdev(items) if len(items) > 1 else 0.0
        lines.append(f"{metric:<20}{len(items):>4}{statistics.fmean(items):>9.3f}{statistics.median(items):>9.3f}{sd:>8.3f}"
                     f"{max(abs(v) for v in items):>9.3f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=40, help="Newest N usable shots")
    parser.add_argument("--rig-from-manifest", action="store_true",
                        help="Derive rig constants from each capture's own tag calibration (else rig.json / defaults)")
    parser.add_argument("--perturb-pitch", type=float, default=0.0, help="Also run the rig with pitch +/- this many degrees")
    parser.add_argument("--perturb-roll", type=float, default=0.0, help="Also run the rig with roll +/- this many degrees")
    args = parser.parse_args()

    folders = []
    for folder in sorted(args.directory.glob("capture-*"), reverse=True):
        try:
            manifest = json.loads((folder / "capture.json").read_text())
            original = json.loads((folder / "analysis.json").read_text())
        except (OSError, ValueError):
            continue
        speed = original.get("measurements", {}).get("metrics", {}).get("ballSpeedMps", {}).get("value")
        if speed and (folder / "camera-secondary").exists() and manifest.get("secondaryAprilTagCalibration") \
                and manifest.get("stereoCalibration"):
            folders.append(folder)
        if len(folders) >= args.limit:
            break
    rows = []
    for folder in folders:
        try:
            manifest, original, lower, upper = load_capture(folder)
            rig = rig_from_manifest(manifest) if args.rig_from_manifest else None
            if rig is None:
                rig = rig_pose.load_rig()
            rig = {"pitchDeg": rig["pitchDeg"], "rollDeg": rig["rollDeg"], "heightMm": rig["heightMm"]}
            row = {"id": folder.name, "capturedAt": original.get("capturedAt"), "rig": rig,
                   "original": values(original["measurements"]),
                   "tag": values(measure(manifest, original, lower, upper, "tag")),
                   "rig_level": values(measure(manifest, original, lower, upper, "rig", rig))}
            for name, kwargs in (("pitch+", {"pitchDeg": rig["pitchDeg"] + args.perturb_pitch}),
                                 ("pitch-", {"pitchDeg": rig["pitchDeg"] - args.perturb_pitch}),
                                 ("roll+", {"rollDeg": rig["rollDeg"] + args.perturb_roll}),
                                 ("roll-", {"rollDeg": rig["rollDeg"] - args.perturb_roll})):
                amount = args.perturb_pitch if name.startswith("pitch") else args.perturb_roll
                if amount:
                    row[f"rig_{name}"] = values(measure(manifest, original, lower, upper, "rig", {**rig, **kwargs}))
        except Exception as error:  # a broken capture must not stop the comparison
            print(json.dumps({"id": folder.name, "error": str(error)}), flush=True)
            continue
        tag, level = row["tag"], row["rig_level"]
        print(json.dumps({"id": folder.name[-8:],
                          "speed": [tag["ballSpeedMps"], level["ballSpeedMps"]],
                          "launch": [tag["launchAngleDeg"], level["launchAngleDeg"]],
                          "dir": [tag["startDirectionDeg"], level["startDirectionDeg"]],
                          "stereo": [tag["_stereo"], level["_stereo"]],
                          "rigHeightFix": level["_surfaceOffsetMm"], "tagHeightFix": tag["_surfaceOffsetMm"]}), flush=True)
        rows.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"version": "1.0.0", "captures": rows}, indent=2))
    print()
    print(f"{len(rows)} captures replayed")
    print(summarize(rows, "level rig", "rig_level"))
    for name in ("pitch+", "pitch-", "roll+", "roll-"):
        if all(f"rig_{name}" in row for row in rows) and rows:
            print(summarize(rows, f"level rig {name}", f"rig_{name}"))
    fixes = [row["rig_level"]["_surfaceOffsetMm"] for row in rows if row["rig_level"]["_surfaceOffsetMm"] is not None]
    if fixes:
        print(f"\nresting-ball height correction of the rig's camera height (mm): n={len(fixes)} "
              f"mean={statistics.fmean(fixes):.1f} sd={statistics.pstdev(fixes):.1f} min={min(fixes):.1f} max={max(fixes):.1f}")
    both_stereo = sum(1 for row in rows if row["tag"]["_stereo"] and row["rig_level"]["_stereo"])
    print(f"stereo accepted in both modes: {both_stereo} of {len(rows)}; tag only: "
          f"{sum(1 for r in rows if r['tag']['_stereo'] and not r['rig_level']['_stereo'])}; rig only: "
          f"{sum(1 for r in rows if r['rig_level']['_stereo'] and not r['tag']['_stereo'])}")


if __name__ == "__main__":
    main()
