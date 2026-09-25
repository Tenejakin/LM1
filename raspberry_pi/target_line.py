"""Calibrated target-line heading, so start direction does not depend on how the ground tag is rotated."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TARGET_LINE_PATH = Path("/var/lib/pinpoint/target-line.json")


def target_line_path() -> Path:
    return Path(os.getenv("PINPOINT_TARGET_LINE_PATH", str(DEFAULT_TARGET_LINE_PATH)))


def load_target_line() -> dict[str, Any] | None:
    try:
        value = json.loads(target_line_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("headingDeg"), (int, float)):
        return None
    if not math.isfinite(value["headingDeg"]):
        return None
    # A heading lives in the ground tag's coordinate frame. Re-solving a moved or
    # rotated tag invalidates the previous heading even when the cameras stayed put.
    from apriltag_calibration import load_apriltag_calibration
    calibration = load_apriltag_calibration()
    stamp = (calibration or {}).get("capturedAt")
    if stamp:
        if value.get("groundCalibrationAt") and value["groundCalibrationAt"] != stamp:
            return None
        try:
            if datetime.fromisoformat(value["capturedAt"].replace("Z", "+00:00")) < datetime.fromisoformat(stamp.replace("Z", "+00:00")):
                return None
        except (KeyError, TypeError, ValueError):
            return None
    return value


def target_heading_rad() -> float | None:
    value = load_target_line()
    return math.radians(value["headingDeg"]) if value else None


def save_target_line(heading_deg: float, points: int, displacement_m: float) -> dict[str, Any]:
    from apriltag_calibration import load_apriltag_calibration
    value = {
        "version": 1,
        "headingDeg": round(float(heading_deg), 3),
        "points": int(points),
        "displacementM": round(float(displacement_m), 4),
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "groundCalibrationAt": (load_apriltag_calibration() or {}).get("capturedAt"),
    }
    path = target_line_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)
    return value


def clear_target_line() -> None:
    target_line_path().unlink(missing_ok=True)


def heading_from_track(track: list[dict[str, Any]]) -> tuple[float, float]:
    """Heading (degrees from the tag's +X toward +Y) of a resolved ground-plane ball track."""
    positions = [p["positionM"] for p in track if isinstance(p.get("positionM"), list) and len(p["positionM"]) == 3]
    if len(positions) < 3:
        raise ValueError("Roll a ball toward the target first; the last capture has no resolved ball track.")
    dx = positions[-1][0] - positions[0][0]
    dy = positions[-1][1] - positions[0][1]
    displacement = math.hypot(dx, dy)
    if displacement < 0.05:
        raise ValueError("The last capture's ball moved less than 5 cm; roll it further toward the target.")
    return math.degrees(math.atan2(dy, dx)), displacement
