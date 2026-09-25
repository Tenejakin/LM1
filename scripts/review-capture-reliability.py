"""Read-only saved-capture audit/replay, version 1.0.0.

Uses each capture's original camera calibration and common sensor clock. Replay
outputs go to a separate report; original analysis and images are never replaced.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "raspberry_pi"))
import launch_measurements as lm


def summary(result):
    d = result.get("diagnostics", {})
    s = d.get("stereo", {})
    return {
        "method": result.get("method"), "failure": result.get("failure"),
        "metrics": {k: {n: v.get(n) for n in ("value", "status", "reason", "checks")}
                    for k, v in result.get("metrics", {}).items()},
        "fit": d.get("trajectoryFit"), "club": d.get("clubSilhouette"),
        "shotEvidence": result.get("shotEvidence"),
        "stereo": {k: v for k, v in s.items() if k != "track"},
    }


def replay(folder, original, manifest):
    calibrations = [manifest["aprilTagCalibration"], manifest["secondaryAprilTagCalibration"]]
    def setup(image_size, camera="primary"):
        p = calibrations[camera == "secondary"]["groundPose"]
        assert list(image_size) == p["imageSize"]
        return np.array(p["cameraMatrix"]), np.array(p["distCoeffs"])
    def pose(image_size, ground_id, size, matrix, distortion, camera="primary"):
        c = calibrations[camera == "secondary"]
        p = c["groundPose"]
        return {"rotation": np.array(p["rotation"]), "translation": np.array(p["translationM"]),
                "errorPx": p["errorPx"], "capturedAt": c["capturedAt"],
                "source": "stored-calibration", "frameIndex": None}
    secondary = json.loads((folder / "camera-secondary/capture.json").read_text())
    # Independently zeroing each camera's timestamps would erase their timing offset.
    epoch = manifest["frameMetadata"][0]["SensorTimestamp"]
    def frames(directory, metadata):
        return [((m["SensorTimestamp"] - epoch) / 1e9,
                 cv2.imread(str(directory / f"frame-{i:04d}.jpg"), cv2.IMREAD_GRAYSCALE))
                for i, m in enumerate(metadata)]
    lower = frames(folder, manifest["frameMetadata"])
    upper = frames(folder / "camera-secondary", secondary["frameMetadata"])
    if any(image is None for _, image in lower + upper):
        raise ValueError("Some captured frames have not been downloaded")
    d = original["measurements"]["diagnostics"]
    if d.get("preprocessing", {}).get("denoise") == "bilateral":
        lower = [(t, cv2.bilateralFilter(im, 5, 12, 3)) for t, im in lower]
    heading = d["calibration"].get("targetHeadingDeg")
    with patch.object(lm, "load_setup", side_effect=setup), patch.object(lm, "stored_ground_pose", side_effect=pose), \
            patch.object(lm, "resolve_target_heading", return_value=(math.radians(heading) if heading is not None else None,
                         d["calibration"].get("targetHeadingSource"))):
        return lm.measure_launch(lower, manifest["ballBounds"],
                                 original.get("firstMovingFrameIndex") or original["coarseDepartureFrameIndex"],
                                 "sensor", max(m["ExposureTime"] for m in manifest["frameMetadata"]),
                                 original["track"], upper)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    rows = []
    previous_rotation = None
    for folder in sorted(args.directory.glob("capture-*")):
        original = json.loads((folder / "analysis.json").read_text())
        manifest = json.loads((folder / "capture.json").read_text())
        poses = [manifest[key]["groundPose"] for key in ("aprilTagCalibration", "secondaryAprilTagCalibration")]
        rotations = [np.array(p["rotation"]) for p in poses]
        centres = [-r.T @ np.array(p["translationM"]) for r, p in zip(rotations, poses)]
        rotation = rotations[0]
        frame_dts = np.diff([m["SensorTimestamp"] for m in manifest["frameMetadata"]]) / 1e6
        row = {"id": folder.name, "capturedAt": original["capturedAt"],
               "fps": manifest["measuredFps"], "maxFrameGapMs": float(frame_dts.max()),
               "medianFrameGapMs": float(np.median(frame_dts)),
               "maxPairOffsetUs": manifest["dualCamera"]["maxAbsOffsetUs"],
               "exposureUs": max(m["ExposureTime"] for m in manifest["frameMetadata"]),
               "calibrationAt": manifest["aprilTagCalibration"]["capturedAt"],
               "baselineMm": float(np.linalg.norm(centres[0] - centres[1]) * 1000),
               "relativeCameraAngleDeg": math.degrees(math.acos(float(np.clip((np.trace(rotations[1] @ rotation.T) - 1) / 2, -1, 1)))),
               "groundRotationChangeDeg": (math.degrees(math.acos(float(np.clip((np.trace(rotation @ previous_rotation.T) - 1) / 2, -1, 1))))
                                           if previous_rotation is not None else None),
               "original": summary(original["measurements"])}
        previous_rotation = rotation
        if args.replay:
            row["replay"] = summary(replay(folder, original, manifest))
        rows.append(row)
        current = row.get("replay", row["original"])
        print(json.dumps({"id": folder.name, "speed": current["metrics"]["ballSpeedMps"]["value"],
                          "launch": current["metrics"]["launchAngleDeg"]["value"],
                          "stereoFrames": current["stereo"].get("frames"),
                          "stereoFailure": current["stereo"].get("failure"),
                          "shotEvidence": current.get("shotEvidence")}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"version": "1.0.0", "captures": rows}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
