"""Level-rig ground pose: the world frame taken from the rig itself, with no AprilTag.

Version 1.0.0. The launch monitor stands on the surface the ball is hit from, so:

* gravity runs top to bottom of the rig: the lower camera looks down at a fixed pitch
  and its image x axis is horizontal (roll 0);
* the target is to the right of where the camera points, so the target direction is
  the camera's image-right axis, which is horizontal in that frame;
* the camera height above the surface is a constant of the stand. Each shot corrects
  it from the resting ball (see ``launch_measurements.resting_ball_surface``), because
  a mat is a few millimetres thick and the stand may not sit exactly on it.

World axes match the ground-tag frame the rest of the pipeline uses: +X toward the
target, +Y left, +Z up, origin on the surface directly below the lower camera.

The pitch and height are per-unit constants written once to ``rig.json``. Tilt error
matters: an error of e degrees in pitch shifts start direction by about e x tan(launch);
an error in roll shifts launch angle by about e. ``python rig_pose.py --from-tags``
derives the constants from the saved tag calibrations of both cameras, fused through
the stereo pair, and writes the file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

RIG_VERSION = 1
DEFAULT_RIG_PATH = "/var/lib/pinpoint/rig.json"
# Design values of the v0.7 vertical stand, used only when no rig.json has been written.
DEFAULT_PITCH_DEG = 8.5
DEFAULT_HEIGHT_MM = 157.5
PITCH_RANGE_DEG = (-10.0, 60.0)
ROLL_LIMIT_DEG = 5.0
HEIGHT_RANGE_MM = (30.0, 600.0)
# Roll under this is treated as measurement noise when deriving the rig from tags.
ROLL_NOISE_DEG = 1.0


def ground_mode() -> str:
    """'rig' (default): level-rig world frame. 'tag': saved AprilTag ground calibration."""
    return "tag" if os.getenv("PINPOINT_GROUND_MODE", "rig").strip().lower() == "tag" else "rig"


def rig_path() -> Path:
    return Path(os.getenv("PINPOINT_RIG_PATH", DEFAULT_RIG_PATH))


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_rig(data: dict[str, Any]) -> dict[str, Any]:
    pitch, roll, height = data.get("pitchDeg"), data.get("rollDeg", 0.0), data.get("heightMm")
    if not (_finite(pitch) and PITCH_RANGE_DEG[0] <= pitch <= PITCH_RANGE_DEG[1]):
        raise ValueError(f"Rig pitch must be {PITCH_RANGE_DEG[0]:.0f} to {PITCH_RANGE_DEG[1]:.0f} degrees.")
    if not (_finite(roll) and abs(roll) <= ROLL_LIMIT_DEG):
        raise ValueError(f"Rig roll must be within {ROLL_LIMIT_DEG:.0f} degrees; level the stand.")
    if not (_finite(height) and HEIGHT_RANGE_MM[0] <= height <= HEIGHT_RANGE_MM[1]):
        raise ValueError(f"Rig height must be {HEIGHT_RANGE_MM[0]:.0f} to {HEIGHT_RANGE_MM[1]:.0f} mm.")
    return {**data, "version": RIG_VERSION, "pitchDeg": float(pitch), "rollDeg": float(roll), "heightMm": float(height)}


def default_rig() -> dict[str, Any]:
    return {"version": RIG_VERSION, "pitchDeg": DEFAULT_PITCH_DEG, "rollDeg": 0.0, "heightMm": DEFAULT_HEIGHT_MM,
            "source": "default", "createdAt": None}


def load_rig() -> dict[str, Any]:
    """The saved rig constants, or the design defaults when none were written. Invalid files raise."""
    path = rig_path()
    if not path.exists():
        return default_rig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Rig file {path} is unreadable: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Rig file {path} is not an object.")
    return {**validate_rig(data), "source": data.get("source", "file")}


def save_rig(pitch_deg: float, height_mm: float, roll_deg: float = 0.0, source: str = "file", **extra: Any) -> dict[str, Any]:
    rig = validate_rig({"pitchDeg": pitch_deg, "rollDeg": roll_deg, "heightMm": height_mm, "source": source,
                        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), **extra})
    path = rig_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    temporary.write_text(json.dumps(rig, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return rig


def gravity_in_camera(pitch_deg: float, roll_deg: float = 0.0) -> np.ndarray:
    """Unit vector of gravity (down) in lower-camera coordinates: x right, y down, z forward.

    A camera pitched down by p has its optical axis p below horizontal, so gravity has
    component sin(p) along z. Positive roll turns gravity toward image left (right side up).
    """
    pitch, roll = math.radians(pitch_deg), math.radians(roll_deg)
    return np.array([-math.sin(roll) * math.cos(pitch), math.cos(roll) * math.cos(pitch), math.sin(pitch)])


def level_rig_rotation(pitch_deg: float, roll_deg: float = 0.0) -> np.ndarray:
    """Rotation taking world coordinates to lower-camera coordinates (columns are the world axes)."""
    up = -gravity_in_camera(pitch_deg, roll_deg)
    right = np.array([1.0, 0.0, 0.0])
    target = right - float(right @ up) * up
    norm = float(np.linalg.norm(target))
    if norm < 0.5:
        raise ValueError("Rig roll leaves no horizontal image-right axis; level the stand.")
    target /= norm
    left = np.cross(up, target)
    return np.column_stack((target, left, up))


def level_rig_pose(rig: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ground pose in the same form as ``stored_ground_pose``: x_cam = R x_world + t."""
    rig = validate_rig(rig) if rig is not None else load_rig()
    rotation = level_rig_rotation(rig["pitchDeg"], rig["rollDeg"])
    translation = -(rig["heightMm"] / 1000.0) * rotation[:, 2]
    return {"rotation": rotation, "translation": translation, "errorPx": 0.0, "frameIndex": None,
            "source": "level-rig", "capturedAt": rig.get("createdAt"), "rig": rig}


def rig_summary(rig: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the app shows: no arrays, just the constants and where they came from."""
    rig = rig or load_rig()
    return {"mode": ground_mode(), "pitchDeg": round(rig["pitchDeg"], 2), "rollDeg": round(rig["rollDeg"], 2),
            "heightMm": round(rig["heightMm"], 1), "source": rig.get("source", "file"), "createdAt": rig.get("createdAt")}


def up_in_lower_camera(lower_rotation: np.ndarray, upper_rotation: np.ndarray | None,
                       stereo_rotation: np.ndarray | None) -> np.ndarray:
    """Vertical in lower-camera coordinates, fusing both cameras' ground-tag poses through the stereo pair.

    Each camera's tag pose gives the tag normal (world up) in its own frame. The stereo
    rotation carries the upper camera's observation into the lower frame, so a noisy
    single-tag tilt is averaged with a second view and held consistent with the
    well-conditioned checkerboard geometry.
    """
    up = np.asarray(lower_rotation, float)[:, 2]
    if upper_rotation is not None and stereo_rotation is not None:
        up = up + np.asarray(stereo_rotation, float).T @ np.asarray(upper_rotation, float)[:, 2]
    return up / np.linalg.norm(up)


def pitch_roll_from_up(up: np.ndarray) -> tuple[float, float]:
    """Pitch (optical axis below horizontal) and roll (positive: right side up) from the vertical."""
    pitch = math.degrees(math.atan2(-up[2], math.hypot(up[0], up[1])))
    roll = math.degrees(math.atan2(up[0], -up[1]))
    return pitch, roll


def derive_from_tags(lower_pose: dict[str, Any], upper_pose: dict[str, Any] | None = None,
                     stereo_rotation: np.ndarray | None = None) -> dict[str, Any]:
    """Rig constants from saved tag poses; roll inside the noise floor is taken as level."""
    lower_rotation = np.asarray(lower_pose["rotation"], float)
    lower_translation = np.asarray(lower_pose["translation"], float)
    up = up_in_lower_camera(lower_rotation, None if upper_pose is None else np.asarray(upper_pose["rotation"], float),
                            stereo_rotation)
    pitch, measured_roll = pitch_roll_from_up(up)
    height_mm = float((-lower_rotation.T @ lower_translation)[2]) * 1000
    return {"pitchDeg": pitch, "rollDeg": 0.0 if abs(measured_roll) <= ROLL_NOISE_DEG else measured_roll,
            "heightMm": height_mm, "measuredRollDeg": round(measured_roll, 3),
            "fusedWithUpperCamera": upper_pose is not None and stereo_rotation is not None}


def _tag_poses() -> tuple[dict[str, Any], dict[str, Any] | None, np.ndarray | None]:
    """Saved tag poses (thickness-corrected) for both cameras and the active stereo rotation."""
    from apriltag_calibration import load_apriltag_calibration
    from launch_measurements import ground_surface_pose

    def pose(camera: str) -> dict[str, Any] | None:
        saved = load_apriltag_calibration(camera)
        data = (saved or {}).get("groundPose")
        if not data:
            return None
        return ground_surface_pose({"rotation": np.asarray(data["rotation"], float),
                                    "translation": np.asarray(data["translationM"], float)})

    lower = pose("primary")
    if lower is None:
        raise ValueError("No saved ground-tag calibration for the lower camera to derive the rig from.")
    stereo_rotation = None
    try:
        from stereo_calibration import read, root
        active = read(root() / "active.json")
        if active and active.get("passed"):
            stereo_rotation = np.asarray(active["rotation"], float)
    except (ImportError, OSError, ValueError, KeyError):
        stereo_rotation = None
    return lower, pose("secondary"), stereo_rotation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-tags", action="store_true", help="Derive from the saved ground-tag calibrations and write rig.json")
    group.add_argument("--set", nargs=2, type=float, metavar=("PITCH_DEG", "HEIGHT_MM"), help="Write measured constants")
    group.add_argument("--show", action="store_true", help="Print the rig constants in use")
    parser.add_argument("--dry-run", action="store_true", help="With --from-tags: print, do not write")
    args = parser.parse_args()
    if args.show:
        print(json.dumps(rig_summary(), indent=2))
    elif args.set:
        print(json.dumps(save_rig(args.set[0], args.set[1], source="measured"), indent=2))
    else:
        lower_pose, upper_pose, stereo_rotation = _tag_poses()
        derived = derive_from_tags(lower_pose, upper_pose, stereo_rotation)
        print(json.dumps(derived, indent=2))
        if not args.dry_run:
            saved = save_rig(derived["pitchDeg"], derived["heightMm"], derived["rollDeg"], source="tag-derived",
                             measuredRollDeg=derived["measuredRollDeg"], fusedWithUpperCamera=derived["fusedWithUpperCamera"])
            print(f"Wrote {rig_path()}: pitch {saved['pitchDeg']:.2f} deg, height {saved['heightMm']:.1f} mm")
