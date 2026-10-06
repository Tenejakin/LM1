"""v1.0.0: does lifting the shadows of saved frames recover club data on dark captures?

Read-only. Replays the newest real shots (ball above 3 m/s) from their own frames, lens data
and stereo pair, unchanged and with a gamma lift applied to both cameras before analysis,
and reports how many shots resolve club speed and how the ball numbers move.

    python scripts/replay-contrast.py /var/lib/pinpoint/rolling-captures out.json --limit 30 --gammas 0.6 0.45
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "raspberry_pi"))
_spec = importlib.util.spec_from_file_location("ground_modes", ROOT / "scripts" / "compare-ground-modes.py")
ground = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ground)


def lifted(frames, gamma):
    table = (255.0 * (np.arange(256) / 255.0) ** gamma).round().astype(np.uint8)
    return [(t, cv2.LUT(image, table)) for t, image in frames]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--gammas", type=float, nargs="+", default=[0.6, 0.45])
    args = parser.parse_args()
    folders = []
    for folder in sorted(args.directory.glob("capture-*"), reverse=True):
        try:
            manifest = json.loads((folder / "capture.json").read_text())
            original = json.loads((folder / "analysis.json").read_text())
        except (OSError, ValueError):
            continue
        measurements = original.get("measurements", {})
        speed = measurements.get("metrics", {}).get("ballSpeedMps", {}).get("value")
        evidence = (measurements.get("shotEvidence") or {}).get("status")
        if speed and speed > 3 and evidence != "not-a-strike" and (folder / "camera-secondary").exists() \
                and manifest.get("secondaryAprilTagCalibration") and manifest.get("stereoCalibration"):
            folders.append(folder)
        if len(folders) >= args.limit:
            break
    rows = []
    for folder in folders:
        try:
            manifest, original, lower, upper = ground.load_capture(folder)
            rig = ground.rig_pose.load_rig()
            rig = {"pitchDeg": rig["pitchDeg"], "rollDeg": rig["rollDeg"], "heightMm": rig["heightMm"]}
            row = {"id": folder.name, "brightness": float(np.mean([im.mean() for _, im in lower[:20]])),
                   "base": ground.values(ground.measure(manifest, original, lower, upper, "rig", rig))}
            for gamma in args.gammas:
                row[f"g{gamma}"] = ground.values(ground.measure(
                    manifest, original, lifted(lower, gamma), lifted(upper, gamma), "rig", rig))
        except Exception as error:
            print(json.dumps({"id": folder.name, "error": str(error)}), flush=True)
            continue
        print(json.dumps({"id": folder.name[-6:], "meanBrightness": round(row["brightness"], 1),
                          "club": [row["base"]["clubSpeedMps"]] + [row[f"g{g}"]["clubSpeedMps"] for g in args.gammas],
                          "ball": [row["base"]["ballSpeedMps"]] + [row[f"g{g}"]["ballSpeedMps"] for g in args.gammas]},
                         default=lambda v: None), flush=True)
        rows.append(row)
    args.output.write_text(json.dumps({"version": "1.0.0", "captures": rows}, indent=2))
    print(f"\n{len(rows)} shots")
    for key in ["base"] + [f"g{g}" for g in args.gammas]:
        have = [r for r in rows if isinstance(r[key]["clubSpeedMps"], (int, float))]
        attack = [r for r in rows if isinstance(r[key]["attackAngleDeg"], (int, float))]
        deltas = [abs(r[key]["ballSpeedMps"] - r["base"]["ballSpeedMps"]) for r in rows
                  if isinstance(r[key]["ballSpeedMps"], (int, float)) and isinstance(r["base"]["ballSpeedMps"], (int, float))]
        print(f"{key:>8}: club speed on {len(have):>2}/{len(rows)}, attack angle on {len(attack):>2}, "
              f"ball speed vs base median {statistics.median(deltas) if deltas else float('nan'):.3f} max {max(deltas) if deltas else float('nan'):.3f} m/s")
    dark = [r for r in rows if r["brightness"] < 15]
    if dark:
        print(f"\nDark captures (mean brightness under 15): {len(dark)}")
        for key in ["base"] + [f"g{g}" for g in args.gammas]:
            print(f"{key:>8}: club speed on {sum(1 for r in dark if isinstance(r[key]['clubSpeedMps'], (int, float)))}/{len(dark)}")


if __name__ == "__main__":
    main()
