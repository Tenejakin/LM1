"""Pre-shot readiness: faults that failed real shots must be caught when the ball is placed.

On 2026-09-24/25 the stereo fit failed after impact with "resting-ball height error
-16 mm" and "top camera sees the resting ball 20 px from where the ground calibration
puts it", and exposure 150 us rejected every shot above 27 m/s for blur.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import launch_measurements  # noqa: E402
from launch_measurements import RADIUS  # noqa: E402
import readiness  # noqa: E402
from stereo_check import _camera  # noqa: E402
from test_stereo_check import DISTORTION, MATRIX, camera, render  # noqa: E402


def still_views(ball, lower_pose, upper_pose):
    lower_frames, upper_frames = render([ball], (lower_pose, upper_pose), 1)
    return lower_frames[0][1], upper_frames[0][1]


def bounds_of(ball, pose):
    point = pose[0] @ ball + pose[1]
    pixel = MATRIX @ point
    centre = pixel[:2] / pixel[2]
    radius = MATRIX[0, 0] * RADIUS / point[2]
    return (int(round(centre[0] - radius)), int(round(centre[1] - radius)),
            int(round(2 * radius)), int(round(2 * radius)))


class StereoRestTests(unittest.TestCase):
    def setUp(self):
        self.lower_pose, self.upper_pose = camera(.136), camera(.222)
        self.lower = _camera(MATRIX, DISTORTION, *self.lower_pose)
        self.upper = _camera(MATRIX, DISTORTION, *self.upper_pose)

    def check(self, ball, rendered_upper=None):
        lower_image, upper_image = still_views(ball, self.lower_pose, rendered_upper or self.upper_pose)
        return readiness.stereo_rest_check(self.lower, self.upper, lower_image, upper_image,
                                           bounds_of(ball, self.lower_pose))

    def test_ball_on_the_calibrated_ground_passes(self):
        result = self.check(np.array([0., .15, RADIUS]))
        self.assertEqual(result["status"], "ok", result["detail"])
        self.assertLess(abs(result["heightErrorMm"]), 2)

    def test_ball_on_a_mat_is_reported_before_the_shot(self):
        result = self.check(np.array([0., .15, RADIUS + .016]))
        self.assertEqual(result["status"], "fail")
        self.assertIn("above the calibrated ground", result["detail"])
        self.assertIn("mat or tee", result["detail"])

    def test_moved_top_camera_is_reported_before_the_shot(self):
        rotation, translation = self.upper_pose
        bumped = (rotation, translation + np.array([.02, 0., 0.]))  # 20 mm sideways in the camera frame.
        result = self.check(np.array([0., .15, RADIUS]), bumped)
        self.assertEqual(result["status"], "fail")
        self.assertIn("recalibrate", result["detail"].lower())


class GroundTagThicknessTests(unittest.TestCase):
    """A tag on a 4 mm plate put z = 0 above the mat: balls read about 4 mm low (2026-09-25)."""

    def setUp(self):
        self.lower_pose, self.upper_pose = camera(.136), camera(.222)

    def check(self, thickness_mm, tag_height_m):
        # Calibrate as if the tag face were tag_height_m above the ground the ball rests on.
        shift = lambda pose: (pose[0], pose[1] + pose[0] @ np.array([0, 0, tag_height_m]))
        with patch.dict(os.environ, {"PINPOINT_GROUND_TAG_THICKNESS_MM": str(thickness_mm)}):
            poses = [launch_measurements.ground_surface_pose({"rotation": r, "translation": t})
                     for r, t in map(shift, (self.lower_pose, self.upper_pose))]
        cameras = [_camera(MATRIX, DISTORTION, pose["rotation"], pose["translation"]) for pose in poses]
        ball = np.array([0., .15, RADIUS])
        lower_image, upper_image = still_views(ball, self.lower_pose, self.upper_pose)
        return readiness.stereo_rest_check(*cameras, lower_image, upper_image, bounds_of(ball, self.lower_pose))

    def test_uncorrected_plate_reads_the_ball_low(self):
        self.assertAlmostEqual(self.check(0, 0.004)["heightErrorMm"], -4, delta=1)

    def test_configured_thickness_puts_the_ball_back_on_the_surface(self):
        result = self.check(4, 0.004)
        self.assertAlmostEqual(result["heightErrorMm"], 0, delta=1)
        self.assertEqual(result["status"], "ok")

    def test_invalid_thickness_is_ignored(self):
        with patch.dict(os.environ, {"PINPOINT_GROUND_TAG_THICKNESS_MM": "not-a-number"}):
            self.assertEqual(launch_measurements.ground_tag_thickness_m(), 0.0)


class ExposureTests(unittest.TestCase):
    def test_measured_exposure_warns_for_a_full_sand_wedge(self):
        result = readiness.exposure_check(150, "sand-wedge", "full-shot")
        self.assertEqual(result["status"], "warn")
        self.assertAlmostEqual(result["maxBallSpeedMps"], 26.7, places=1)
        self.assertIn("127 µs", result["detail"])

    def test_short_exposure_passes(self):
        self.assertEqual(readiness.exposure_check(66, "sand-wedge", "full-shot")["status"], "ok")

    def test_putting_ignores_full_swing_speed(self):
        self.assertEqual(readiness.exposure_check(150, "driver", "putting")["status"], "ok")

    def test_auto_exposure_fails(self):
        self.assertEqual(readiness.exposure_check(0, "driver", "full-shot")["status"], "fail")


class CombinedReadinessTests(unittest.TestCase):
    def test_missing_face_profile_is_named_and_worst_status_wins(self):
        with TemporaryDirectory() as temporary, patch.dict(
                os.environ, {"PINPOINT_CLUB_PROFILE_PATH": str(Path(temporary) / "club-profile.json")}):
            verdict = readiness.readiness(
                [{"id": "stereo-rest", "label": "Camera alignment", "status": "fail", "detail": "x"}],
                66, "sand-wedge", "full-shot")
        self.assertEqual(verdict["status"], "fail")
        self.assertEqual([item["id"] for item in verdict["items"]], ["exposure", "stereo-rest", "club-profile"])
        self.assertEqual(verdict["items"][2]["status"], "warn")

    def test_profile_for_another_club_warns(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "club-profile.json"
            path.write_text('{"version": 1, "clubId": "driver", "faceWidthMm": 110, "faceHeightMm": 55}')
            with patch.dict(os.environ, {"PINPOINT_CLUB_PROFILE_PATH": str(path)}):
                item = readiness.club_profile_check("sand-wedge", "full-shot")
                self.assertEqual(item["status"], "warn")
                self.assertEqual(readiness.club_profile_check("driver", "full-shot")["status"], "ok")
                self.assertIsNone(readiness.club_profile_check("driver", "putting"))

    def test_camera_checks_never_raise_without_calibration(self):
        with TemporaryDirectory() as temporary, patch.dict(
                os.environ, {"PINPOINT_INTRINSICS_PATH": str(Path(temporary) / "missing.json")}):
            items = readiness.camera_checks(np.zeros((400, 640, 3), np.uint8), None, (300, 200, 20, 20))
        self.assertEqual(items[0]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
