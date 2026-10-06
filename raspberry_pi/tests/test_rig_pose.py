"""Level-rig ground pose: world frame from the rig, no AprilTag."""

import json
import math
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rig_pose  # noqa: E402
from launch_measurements import RADIUS, measure_launch  # noqa: E402

MATRIX = np.array([[800., 0, 640], [0, 800., 400], [0, 0, 1]])


def rot_x(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_z(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


class RigGeometryTests(unittest.TestCase):
    def test_world_axes_are_right_handed_and_target_is_image_right(self):
        for pitch, roll in ((8.5, 0.0), (0.0, 0.0), (27.3, 0.0), (8.5, 2.0), (8.5, -3.0)):
            rotation = rig_pose.level_rig_rotation(pitch, roll)
            np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(rotation), 1.0, places=12)
            target, left, up = rotation[:, 0], rotation[:, 1], rotation[:, 2]
            np.testing.assert_allclose(np.cross(target, left), up, atol=1e-12)
            # Gravity is straight down the rig, the target axis is horizontal.
            np.testing.assert_allclose(up, -rig_pose.gravity_in_camera(pitch, roll), atol=1e-12)
            self.assertAlmostEqual(float(target @ up), 0.0, places=12)

    def test_unrolled_rig_targets_exactly_image_right(self):
        rotation = rig_pose.level_rig_rotation(8.5, 0.0)
        np.testing.assert_allclose(rotation[:, 0], [1, 0, 0], atol=1e-12)

    def test_camera_sits_above_the_origin_looking_across_the_target_line(self):
        pose = rig_pose.level_rig_pose({"pitchDeg": 8.5, "rollDeg": 0.0, "heightMm": 157.5})
        rotation, translation = pose["rotation"], pose["translation"]
        position = -rotation.T @ translation
        np.testing.assert_allclose(position, [0, 0, 0.1575], atol=1e-12)
        axis = rotation.T @ np.array([0., 0., 1.])
        pitch = math.radians(8.5)
        # +Y is the golfer's left: a camera on the right looks that way, pitched down.
        np.testing.assert_allclose(axis, [0, math.cos(pitch), -math.sin(pitch)], atol=1e-12)
        # The pitch the pipeline reports (as in the diagnostics) is the pitch we set.
        self.assertAlmostEqual(math.degrees(math.asin(-axis[2])), 8.5, places=9)

    def test_image_centre_ray_lands_where_geometry_says(self):
        pose = rig_pose.level_rig_pose({"pitchDeg": 10.0, "rollDeg": 0.0, "heightMm": 200.0})
        rotation, translation = pose["rotation"], pose["translation"]
        position = -rotation.T @ translation
        ray = rotation.T @ np.array([0., 0., 1.])
        ground = position + ray * (-position[2] / ray[2])
        np.testing.assert_allclose(ground, [0, 0.2 / math.tan(math.radians(10.0)), 0], atol=1e-9)

    def test_a_ball_at_rest_on_the_ground_projects_to_the_expected_pixel(self):
        pose = rig_pose.level_rig_pose({"pitchDeg": 8.5, "rollDeg": 0.0, "heightMm": 157.5})
        point = pose["rotation"] @ np.array([0.0, 0.5, RADIUS]) + pose["translation"]
        self.assertGreater(point[2], 0)
        pixel = MATRIX @ point
        pixel = pixel[:2] / pixel[2]
        self.assertAlmostEqual(pixel[0], 640.0, places=6)  # straight ahead of the image column
        self.assertTrue(0 < pixel[1] < 800)

    def test_invalid_constants_are_rejected(self):
        for bad in ({"pitchDeg": 80, "heightMm": 150}, {"pitchDeg": 8, "heightMm": 5},
                    {"pitchDeg": 8, "heightMm": 150, "rollDeg": 20}, {"pitchDeg": float("nan"), "heightMm": 150},
                    {"pitchDeg": "8", "heightMm": 150}):
            with self.assertRaises(ValueError, msg=str(bad)):
                rig_pose.validate_rig(bad)

    def test_a_rig_rolled_close_to_portrait_has_no_target_axis(self):
        with self.assertRaises(ValueError):
            rig_pose.level_rig_rotation(8.5, 89.0)


class RigFileTests(unittest.TestCase):
    def test_default_then_saved_constants_round_trip(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"PINPOINT_RIG_PATH": str(Path(directory) / "rig.json")}):
            rig = rig_pose.load_rig()
            self.assertEqual(rig["source"], "default")
            saved = rig_pose.save_rig(9.25, 160.0, source="measured")
            loaded = rig_pose.load_rig()
            self.assertEqual((loaded["pitchDeg"], loaded["heightMm"], loaded["rollDeg"]), (9.25, 160.0, 0.0))
            self.assertEqual(loaded["source"], "measured")
            self.assertEqual(saved["createdAt"], loaded["createdAt"])
            self.assertEqual(rig_pose.rig_summary(loaded)["pitchDeg"], 9.25)

    def test_a_corrupt_file_raises_instead_of_silently_using_defaults(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rig.json"
            path.write_text("{not json")
            with patch.dict(os.environ, {"PINPOINT_RIG_PATH": str(path)}), self.assertRaises(ValueError):
                rig_pose.load_rig()
            path.write_text(json.dumps({"pitchDeg": 200, "heightMm": 150}))
            with patch.dict(os.environ, {"PINPOINT_RIG_PATH": str(path)}), self.assertRaises(ValueError):
                rig_pose.load_rig()

    def test_ground_mode_defaults_to_rig_and_can_be_switched_to_tag(self):
        with patch.dict(os.environ, {"PINPOINT_GROUND_MODE": "rig"}):
            self.assertEqual(rig_pose.ground_mode(), "rig")
        with patch.dict(os.environ, {"PINPOINT_GROUND_MODE": " TAG "}):
            self.assertEqual(rig_pose.ground_mode(), "tag")
        with patch.dict(os.environ, {"PINPOINT_GROUND_MODE": "nonsense"}):
            self.assertEqual(rig_pose.ground_mode(), "rig")


class DeriveFromTagsTests(unittest.TestCase):
    """The tag world can be rotated any way; the vertical it implies is what matters."""

    def tag_view(self, pitch, roll, tag_yaw, tilt_deg=0.0):
        """Tag-to-camera rotation of a rig with the given true pitch/roll, tag turned by tag_yaw about vertical."""
        level = rig_pose.level_rig_rotation(pitch, roll)
        rotation = level @ rot_z(tag_yaw)
        # A pose error tilts the whole frame about the camera x axis.
        return rot_x(tilt_deg) @ rotation

    def test_pitch_is_recovered_whatever_way_the_tag_is_turned(self):
        for yaw in (-70.0, 0.0, 47.0, 120.0):
            up = rig_pose.up_in_lower_camera(self.tag_view(8.5, 0.0, yaw), None, None)
            pitch, roll = rig_pose.pitch_roll_from_up(up)
            self.assertAlmostEqual(pitch, 8.5, places=9)
            self.assertAlmostEqual(roll, 0.0, places=9)

    def test_a_second_camera_through_the_stereo_pair_halves_a_tilt_error(self):
        stereo = rot_x(19.0) @ rot_z(2.0)  # lower to upper camera rotation
        upper = stereo @ self.tag_view(8.5, 0.0, 47.0)  # exact upper view of the same tag
        lower = {"rotation": self.tag_view(8.5, 0.0, 47.0, 0.6), "translation": np.array([0, 0, 0.0])}
        alone = rig_pose.derive_from_tags(lower)
        fused = rig_pose.derive_from_tags(lower, {"rotation": upper}, stereo)
        self.assertAlmostEqual(abs(alone["pitchDeg"] - 8.5), 0.6, delta=0.01)
        self.assertLess(abs(fused["pitchDeg"] - 8.5), 0.35)
        self.assertTrue(fused["fusedWithUpperCamera"])

    def test_roll_inside_the_noise_floor_is_taken_as_level_and_kept_as_information(self):
        rotation = self.tag_view(8.5, 0.4, 0.0)
        derived = rig_pose.derive_from_tags({"rotation": rotation, "translation": -rotation @ np.array([0, 0, 0.1575])})
        self.assertEqual(derived["rollDeg"], 0.0)
        self.assertAlmostEqual(derived["measuredRollDeg"], 0.4, places=2)
        self.assertAlmostEqual(derived["heightMm"], 157.5, places=6)
        big = self.tag_view(8.5, 3.0, 0.0)
        derived = rig_pose.derive_from_tags({"rotation": big, "translation": -big @ np.array([0, 0, 0.1575])})
        self.assertAlmostEqual(derived["rollDeg"], 3.0, places=2)


class RigMeasurementTests(unittest.TestCase):
    """A rendered ball flight, measured with no tag anywhere."""

    def render(self, velocity, rig):
        pose = rig_pose.level_rig_pose(rig)
        frames, first = [], None
        for i in range(18):
            elapsed = max(0, i - 7) * .005
            world = np.array([-0.2, 0.35, RADIUS]) + elapsed * np.asarray(velocity)
            camera = pose["rotation"] @ world + pose["translation"]
            pixel = MATRIX @ camera
            pixel = pixel[:2] / pixel[2]
            if first is None:
                first = (pixel, camera[2])
            frame = np.full((800, 1280), 30, np.uint8)
            cv2.circle(frame, tuple(np.round(pixel * 16).astype(int)), round(800 * RADIUS / camera[2] * 16), 230, -1, shift=4)
            frames.append((1 + i * .005, frame))
        (x, y), depth = first
        radius = 800 * RADIUS / depth
        return frames, (int(x - radius), int(y - radius), int(2 * radius), int(2 * radius))

    def measure(self, velocity, rig=None):
        rig = rig or {"pitchDeg": 8.5, "rollDeg": 0.0, "heightMm": 157.5}
        frames, bounds = self.render(velocity, rig)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "intrinsics.json"
            path.write_text(json.dumps({"imageSize": [1280, 800], "cameraMatrix": MATRIX.tolist(), "distCoeffs": [0] * 5, "rmsPx": .2}))
            Path(directory, "rig.json").write_text(json.dumps({**rig, "version": 1, "source": "measured"}))
            env = {"PINPOINT_GROUND_MODE": "rig", "PINPOINT_INTRINSICS_PATH": str(path),
                   "PINPOINT_RIG_PATH": str(Path(directory) / "rig.json"),
                   "PINPOINT_CLUB_MARKER_PATH": str(Path(directory) / "absent.json"),
                   "PINPOINT_APRILTAG_CALIBRATION_PATH": str(Path(directory) / "no-tag.json")}
            with patch.dict(os.environ, env), \
                    patch("launch_measurements.marker_map", side_effect=AssertionError("the tag must not be looked for")):
                return measure_launch(frames, bounds, 8, "sensor", 50)

    def test_speed_launch_and_direction_come_out_with_no_tag(self):
        result = self.measure([3.0, 0.0, 0.5])
        metrics = result["metrics"]
        self.assertIsNotNone(metrics["ballSpeedMps"]["value"], result.get("failure"))
        self.assertAlmostEqual(metrics["ballSpeedMps"]["value"], math.hypot(3, .5), delta=.25)
        # One camera sizes the ball to get depth, which is good to a few mm per frame: launch to a few degrees.
        self.assertAlmostEqual(metrics["launchAngleDeg"]["value"], math.degrees(math.atan2(.5, 3)), delta=3.0)
        # Direction rides on the same depth estimate; the two-camera fit (not this single-camera path) is the precise one.
        self.assertLess(abs(metrics["startDirectionDeg"]["value"]), 10.0)
        self.assertEqual(result["diagnostics"]["groundPose"]["source"], "level-rig")
        self.assertEqual(result["diagnostics"]["calibration"]["groundMode"], "rig")
        self.assertEqual(result["diagnostics"]["calibration"]["targetHeadingSource"], "camera-axis")
        self.assertAlmostEqual(result["diagnostics"]["groundPose"]["cameraPitchDeg"], 8.5, places=2)
        self.assertAlmostEqual(result["diagnostics"]["groundPose"]["cameraHeightMm"], 157.5, places=1)

    def test_a_ball_moving_away_from_the_camera_reads_left(self):
        # Away from the camera is +Y, toward the golfer's left; the app shows that as L (negative).
        # A large depth motion (27 degrees) stands well clear of the single-camera depth noise.
        expected = math.degrees(math.atan2(1.5, 3.0))
        result = self.measure([3.0, 1.5, 0.5])
        direction = result["metrics"]["startDirectionDeg"]["value"]
        self.assertIsNotNone(direction, result.get("failure"))
        self.assertLess(direction, -12.0)
        self.assertGreater(direction, -expected - 6.0)
        result = self.measure([3.0, -1.5, 0.5])
        self.assertGreater(result["metrics"]["startDirectionDeg"]["value"], 12.0)

    def test_the_result_says_the_rig_was_assumed_level_and_why_it_is_only_an_estimate(self):
        result = self.measure([3.0, 0.0, 0.5])
        self.assertIn("Level-rig", result["metrics"]["ballSpeedMps"]["reason"])
        self.assertEqual(result["metrics"]["ballSpeedMps"]["status"], "estimated")
        self.assertIn("across-image axis", result["metrics"]["startDirectionDeg"]["reason"])
        self.assertTrue(any("stand constant" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
