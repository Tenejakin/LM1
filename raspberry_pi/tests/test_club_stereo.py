"""Two-camera hosel tracking: a rendered shaft/hosel "check" with known motion.

On the stand the dark head does not segment; the lit shaft and hosel highlight do.
These fixtures draw only that bright shape in both cameras and require the drawn
3D velocity, attack angle and path back. They fix the geometry and fitting only.
"""

import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import club_stereo  # noqa: E402
from launch_measurements import RADIUS  # noqa: E402
from stereo_check import _camera  # noqa: E402
from test_stereo_check import DISTORTION, FPS, MATRIX, camera  # noqa: E402

BALL = np.array([0.0, 0.15, RADIUS])


def project(pose, point):
    pixel = MATRIX @ (pose[0] @ point + pose[1])
    return pixel[:2] / pixel[2]


class StereoHoselTests(unittest.TestCase):
    def setUp(self):
        self.poses = camera(.136), camera(.222)
        self.cameras = [_camera(MATRIX, DISTORTION, *pose) for pose in self.poses]

    def render(self, velocity, impact=30, count=40, jump_frame=None):
        """Hosel travelling at ``velocity`` to arrive just behind the ball at ``impact``."""
        contact = BALL + np.array([-0.03, 0.0, -0.005])
        bursts = []
        for pose in self.poses:
            frames = []
            for index in range(count):
                image = np.full((400, 640), 12, np.uint8)
                cv2.circle(image, tuple(int(round(v)) for v in project(pose, BALL)), 9, 200, -1)
                if index < impact:
                    hosel = contact + velocity * (index - impact) / FPS
                    if index == jump_frame:
                        hosel = hosel + np.array([0.0, 0.0, 0.06])  # The vertex switches features.
                    grip = hosel + np.array([-0.05, 0.02, 0.35])    # Shaft up and back toward the hands.
                    toe = hosel + np.array([0.02, -0.06, 0.012])    # Short top-line highlight.
                    for end in (grip, toe):
                        cv2.line(image, tuple(int(round(v * 16)) for v in project(pose, hosel)),
                                 tuple(int(round(v * 16)) for v in project(pose, end)), 235, 2, cv2.LINE_AA, 4)
                frames.append((index / FPS, image))
            bursts.append(frames)
        backgrounds = [frames[-1][1].copy() for frames in bursts]  # Club gone, resting ball kept.
        return bursts, backgrounds

    def measure(self, velocity, **kwargs):
        (lower, upper), (lower_bg, upper_bg) = self.render(velocity, **kwargs)
        return club_stereo.measure(lower, upper, kwargs.get("impact", 30), *self.cameras,
                                   lower_bg, upper_bg, BALL)

    def test_speed_attack_angle_and_path_come_back(self):
        # 10 m/s, 6° descending, 4° across the line: a wedge chip.
        attack, path = math.radians(-6), math.radians(4)
        velocity = 10 * np.array([math.cos(attack) * math.cos(path), math.cos(attack) * math.sin(path), math.sin(attack)])
        result = self.measure(velocity)
        measured = np.asarray(result["velocity"])
        self.assertAlmostEqual(float(np.linalg.norm(measured)), 10.0, delta=0.3)
        self.assertAlmostEqual(club_stereo.attack_angle_deg(measured), -6.0, delta=1.0)
        self.assertAlmostEqual(math.degrees(math.atan2(measured[1], measured[0])), 4.0, delta=1.5)
        self.assertGreaterEqual(result["diagnostics"]["acceptedFrames"], club_stereo.MIN_FRAMES)
        self.assertLess(result["diagnostics"]["medianRayGapMm"], 3.0)

    def test_more_frames_are_averaged_with_the_curved_model(self):
        # A slow putting-style stroke stays in both views long enough for 5+ frames.
        velocity = np.array([3.0, 0.0, -0.2])
        result = self.measure(velocity)
        self.assertGreaterEqual(result["diagnostics"]["acceptedFrames"], club_stereo.CURVED_FIT_FRAMES)
        self.assertEqual(result["diagnostics"]["model"], "constant-acceleration")
        self.assertAlmostEqual(float(np.linalg.norm(result["velocity"])), float(np.linalg.norm(velocity)), delta=0.2)

    def test_three_frames_are_enough(self):
        velocity = np.array([9.0, 0.0, -0.8])
        (lower, upper), backgrounds = self.render(velocity)
        # Only the last three frames before impact show the club in the top camera.
        upper = [(t, backgrounds[1].copy()) if index < 27 else (t, image) for index, (t, image) in enumerate(upper)]
        result = club_stereo.measure(lower, upper, 30, *self.cameras, *backgrounds, BALL)
        self.assertEqual(result["diagnostics"]["acceptedFrames"], 3)
        self.assertAlmostEqual(float(np.linalg.norm(result["velocity"])), float(np.linalg.norm(velocity)), delta=0.4)

    def test_a_feature_jump_is_left_out_of_the_fit(self):
        velocity = np.array([10.0, 0.0, -1.0])
        result = self.measure(velocity, jump_frame=29)
        self.assertNotIn(29, result["diagnostics"]["frameIndices"])
        self.assertAlmostEqual(float(np.linalg.norm(result["velocity"])), float(np.linalg.norm(velocity)), delta=0.3)

    def test_fewer_than_three_frames_is_refused_with_a_reason(self):
        (lower, upper), backgrounds = self.render(np.array([9.0, 0.0, -0.8]))
        upper = [(t, backgrounds[1].copy()) if index < 28 else (t, image) for index, (t, image) in enumerate(upper)]
        with self.assertRaises(ValueError) as caught:
            club_stereo.measure(lower, upper, 30, *self.cameras, *backgrounds, BALL)
        self.assertIn("at least 3", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics["triangulatedFrames"], 2)


class MotionFitTests(unittest.TestCase):
    def test_curved_fit_returns_velocity_at_impact_not_the_window_average(self):
        # Descending along an arc: 16 m/s² upward acceleration flattens the path into impact.
        times = np.arange(8) / FPS
        final = np.array([10.0, 0.0, -0.5])
        acceleration = np.array([0.0, 0.0, 400.0])
        dt = times - times[-1]
        positions = final * dt[:, None] + 0.5 * acceleration * dt[:, None] ** 2
        velocity, residuals = club_stereo.fit_motion(times, positions)
        np.testing.assert_allclose(velocity, final, atol=1e-6)
        self.assertLess(residuals.max(), 1e-9)


if __name__ == "__main__":
    unittest.main()
