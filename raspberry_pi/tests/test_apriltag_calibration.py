import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import apriltag_calibration as april


class _Matrix:
    def tolist(self):
        return [[1.0, 0.0, -10.0], [0.0, 1.0, -20.0], [0.0, 0.0, 1.0]]


class AprilTagCalibrationTests(unittest.TestCase):
    def test_measurement_produces_metric_planar_transform(self):
        fake_cv2 = SimpleNamespace(
            getPerspectiveTransform=lambda _source, _target: _Matrix(),
        )
        fake_np = SimpleNamespace(float32="float32", asarray=lambda value, dtype: value)
        detector = AprilTagDetectorWithoutOpenCv()
        with patch.object(april, "cv2", fake_cv2), patch.object(april, "np", fake_np):
            result = detector._measurement(
                [(10.0, 20.0), (110.0, 20.0), (110.0, 120.0), (10.0, 120.0)],
                200,
                160,
            )
        self.assertTrue(result["detected"])
        self.assertEqual(result["pixelsPerMm"], 1.0)
        self.assertEqual(result["rotationDeg"], 0.0)
        self.assertEqual(result["corners"][0], [0.05, 0.125])
        self.assertEqual(len(result["imageToTagMm"]), 3)

    def test_capture_persists_latest_matching_detection(self):
        detection = {
            "detected": True,
            "available": True,
            "family": "tag36h11",
            "tagId": 0,
            "tagSizeMm": 100.0,
            "pixelsPerMm": 1.5,
        }
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "calibration.json"
            with patch.dict(os.environ, {"PINPOINT_APRILTAG_CALIBRATION_PATH": str(destination)}), patch(
                "launch_measurements.ground_pose_calibration", return_value={"version": 1}
            ):
                captured = april.capture_latest_apriltag_calibration({"aprilTag": detection})
                loaded = april.load_apriltag_calibration()
                self.assertTrue(destination.exists())
                self.assertEqual(loaded, captured)
                self.assertEqual(april.calibration_version(), "APRILTAG-tag36h11-ID0-V1")

    def test_capture_rejects_missing_tag(self):
        with self.assertRaisesRegex(ValueError, "not visible"):
            april.capture_latest_apriltag_calibration({"aprilTag": {"detected": False}})


class AprilTagDetectorWithoutOpenCv(april.AprilTagDetector):
    def __init__(self):
        self.tag_id = 0
        self.tag_size_mm = 100.0
        self.minimum_edge_pixels = 24.0


if __name__ == "__main__":
    unittest.main()
