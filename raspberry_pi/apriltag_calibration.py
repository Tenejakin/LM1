"""AprilTag detection and planar calibration capture for the LM1 camera stream."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
except ModuleNotFoundError:  # The BLE service can still run without camera support.
    cv2 = None
    np = None


DEFAULT_CALIBRATION_PATH = Path("/var/lib/pinpoint/apriltag-calibration.json")
DEFAULT_SECONDARY_CALIBRATION_PATH = Path("/var/lib/pinpoint/apriltag-calibration-secondary.json")
# Live detections are published per camera under these diagnostics keys.
DETECTION_KEYS = {"primary": "aprilTag", "secondary": "secondaryAprilTag"}
APRILTAG_FAMILY = "tag36h11"


def tag_detector_parameters() -> Any:
    """Detector settings shared by live preview and shot analysis.

    OpenCV's default leaves tag corners at whole-pixel positions from the quad fit,
    and every launch value inherits the ground pose built from them. Sub-pixel corner
    refinement is cheap and moves each corner onto the actual edge intersection.
    """
    parameters = cv2.aruco.DetectorParameters()
    method = os.getenv("PINPOINT_APRILTAG_CORNER_REFINE", "subpix").lower()
    parameters.cornerRefinementMethod = {
        "none": cv2.aruco.CORNER_REFINE_NONE,
        "subpix": cv2.aruco.CORNER_REFINE_SUBPIX,
        "contour": cv2.aruco.CORNER_REFINE_CONTOUR,
        "apriltag": cv2.aruco.CORNER_REFINE_APRILTAG,
    }[method]
    parameters.cornerRefinementWinSize = 5
    parameters.cornerRefinementMaxIterations = 50
    parameters.cornerRefinementMinAccuracy = 0.01
    return parameters


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def calibration_path(camera: str = "primary") -> Path:
    if camera == "secondary":
        return Path(os.getenv("PINPOINT_SECONDARY_APRILTAG_CALIBRATION_PATH", str(DEFAULT_SECONDARY_CALIBRATION_PATH)))
    return Path(os.getenv("PINPOINT_APRILTAG_CALIBRATION_PATH", str(DEFAULT_CALIBRATION_PATH)))


def load_apriltag_calibration(camera: str = "primary") -> dict[str, Any] | None:
    path = calibration_path(camera)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("version") == 1 else None


def save_apriltag_calibration(calibration: dict[str, Any], camera: str = "primary") -> dict[str, Any]:
    path = calibration_path(camera)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    temporary.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    temporary.replace(path)
    return calibration


def capture_latest_apriltag_calibration(diagnostics: dict[str, Any], camera: str = "primary") -> dict[str, Any]:
    detection = diagnostics.get(DETECTION_KEYS[camera])
    if not isinstance(detection, dict) or not detection.get("detected"):
        view = "the top camera" if camera == "secondary" else "the camera"
        raise ValueError(f"AprilTag 36h11 ID 0 is not visible to {view}. Put the whole tag in frame and try again.")
    if detection.get("tagId") != int(os.getenv("PINPOINT_APRILTAG_ID", "0")):
        raise ValueError("The visible AprilTag does not match the configured tag ID.")
    calibration = {
        **detection,
        "version": 1,
        "capturedAt": utc_now(),
        "purpose": "planar image-to-millimetre calibration for launch analysis",
    }
    from launch_measurements import ground_pose_calibration
    calibration["groundPose"] = ground_pose_calibration(detection, camera)
    calibration["camera"] = camera
    calibration["purpose"] = "Stored ground pose for launch analysis; tag may be removed while camera stays fixed."
    return save_apriltag_calibration(calibration, camera)


def clear_apriltag_calibration(camera: str = "primary") -> None:
    calibration_path(camera).unlink(missing_ok=True)


def calibration_version() -> str | None:
    calibration = load_apriltag_calibration()
    if calibration is None:
        return None
    return f"APRILTAG-{calibration.get('family', APRILTAG_FAMILY)}-ID{calibration.get('tagId', 0)}-V1"


class AprilTagDetector:
    """Detect the configured 36h11 tag and calculate a planar metric transform."""

    def __init__(self) -> None:
        self.tag_id = int(os.getenv("PINPOINT_APRILTAG_ID", "0"))
        self.tag_size_mm = float(os.getenv("PINPOINT_APRILTAG_SIZE_MM", "100"))
        self.minimum_edge_pixels = float(os.getenv("PINPOINT_APRILTAG_MIN_EDGE_PIXELS", "24"))
        if self.tag_size_mm <= 0:
            raise ValueError("PINPOINT_APRILTAG_SIZE_MM must be positive")
        self.available = bool(
            cv2 is not None
            and np is not None
            and hasattr(cv2, "aruco")
            and hasattr(cv2.aruco, "DICT_APRILTAG_36h11")
        )
        self._detector: Any | None = None
        self._dictionary: Any | None = None
        self._parameters: Any | None = None
        if self.available:
            self._dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
            self._parameters = tag_detector_parameters()
            if hasattr(cv2.aruco, "ArucoDetector"):
                self._detector = cv2.aruco.ArucoDetector(self._dictionary, self._parameters)

    def detect(self, frame: Any) -> dict[str, Any]:
        if not self.available:
            return {
                "detected": False,
                "available": False,
                "family": APRILTAG_FAMILY,
                "tagId": self.tag_id,
                "message": "OpenCV AprilTag support is unavailable",
            }
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._detector is not None:
            corners, ids, _ = self._detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(
                gray,
                self._dictionary,
                parameters=self._parameters,
            )
        if ids is None:
            return self._not_detected()
        matching_index = next(
            (index for index, value in enumerate(ids.flatten().tolist()) if int(value) == self.tag_id),
            None,
        )
        if matching_index is None:
            return self._not_detected()
        height, width = frame.shape[:2]
        points = [(float(x), float(y)) for x, y in corners[matching_index].reshape(4, 2)]
        return self._measurement(points, width, height)

    def _not_detected(self) -> dict[str, Any]:
        return {
            "detected": False,
            "available": True,
            "family": APRILTAG_FAMILY,
            "tagId": self.tag_id,
        }

    def _measurement(
        self,
        points: list[tuple[float, float]],
        width: int,
        height: int,
    ) -> dict[str, Any]:
        edges = [math.dist(points[index], points[(index + 1) % 4]) for index in range(4)]
        mean_edge = sum(edges) / 4
        edge_variation = (max(edges) - min(edges)) / max(mean_edge, 1)
        image_points = np.asarray(points, dtype=np.float32)
        size = float(self.tag_size_mm)
        tag_points = np.asarray([(0, 0), (size, 0), (size, size), (0, size)], dtype=np.float32)
        homography = cv2.getPerspectiveTransform(image_points, tag_points)
        center_x = sum(point[0] for point in points) / 4
        center_y = sum(point[1] for point in points) / 4
        rotation = math.degrees(
            math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
        )
        quality = max(0.0, min(1.0, (mean_edge / max(self.minimum_edge_pixels, 1)) * (1 - min(edge_variation, 0.8))))
        result: dict[str, Any] = {
            "detected": mean_edge >= self.minimum_edge_pixels,
            "available": True,
            "family": APRILTAG_FAMILY,
            "tagId": self.tag_id,
            "tagSizeMm": self.tag_size_mm,
            "imageSize": [width, height],
            "corners": [[round(x / width, 6), round(y / height, 6)] for x, y in points],
            "center": [round(center_x / width, 6), round(center_y / height, 6)],
            "edgePixels": round(mean_edge, 2),
            "pixelsPerMm": round(mean_edge / self.tag_size_mm, 5),
            "rotationDeg": round(rotation, 2),
            "perspectiveError": round(edge_variation, 4),
            "quality": round(quality, 3),
            "imageToTagMm": [[round(float(value), 8) for value in row] for row in homography.tolist()],
        }
        focal_length = float(os.getenv("PINPOINT_CAMERA_FOCAL_LENGTH_PX", "0"))
        if focal_length > 0:
            result["distanceMm"] = round(self.tag_size_mm * focal_length / max(mean_edge, 1), 1)
        if not result["detected"]:
            result["message"] = "AprilTag is too small for a reliable calibration"
        return result
