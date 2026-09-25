from pathlib import Path
import math
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch_measurements import ball_difference, ball_edge_fit


def render_ball(center, radius, light=None, cut_above=None, blur=1.2, size=(200, 240), supersample=8):
    """A bright ball on a dark scene, anti-aliased so its true edge is known to sub-pixel accuracy."""
    height, width = size
    ys, xs = np.mgrid[0:height * supersample, 0:width * supersample]
    xs = (xs + 0.5) / supersample - 0.5
    ys = (ys + 0.5) / supersample - 0.5
    inside = (xs - center[0]) ** 2 + (ys - center[1]) ** 2 <= radius ** 2
    brightness = np.full(xs.shape, 160.0)
    if light is not None:
        # Lambert-style shading: bright toward the light, fading to a dim limb opposite.
        facing = ((xs - center[0]) * light[0] + (ys - center[1]) * light[1]) / radius
        brightness = 40 + 140 * np.clip(0.5 + 0.5 * facing, 0, 1)
    image = np.where(inside, brightness, 20.0)
    if cut_above is not None:
        image[ys < cut_above] = 20.0
    image = cv2.resize(image.astype(np.float32), (width, height), interpolation=cv2.INTER_AREA)
    if blur:
        image = cv2.GaussianBlur(image, (0, 0), blur)
    return np.clip(image, 0, 255).astype(np.uint8)


class BallEdgeFitTest(unittest.TestCase):
    background = np.full((200, 240), 20, np.uint8)

    def fit(self, frame, guess_center, guess_radius):
        return ball_edge_fit(ball_difference(frame, self.background), np.asarray(guess_center, float), guess_radius)

    def test_uniform_ball_radius_and_centre_are_sub_pixel(self):
        center, radius = (117.3, 96.6), 24.4
        result = self.fit(render_ball(center, radius), (115.0, 98.0), 30.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['radiusPx'], radius, delta=0.2)
        self.assertLess(np.linalg.norm(result['centerPx'] - center), 0.2)

    def test_apparent_size_far_from_the_resting_guess(self):
        # A ball flying away from the camera can shrink to half its resting size.
        center, radius = (120.2, 100.7), 11.3
        result = self.fit(render_ball(center, radius), (121.0, 100.0), 22.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['radiusPx'], radius, delta=0.25)

    def test_side_lit_ball_keeps_its_true_radius(self):
        center, radius = (118.5, 99.2), 22.7
        result = self.fit(render_ball(center, radius, light=(-0.7, -0.7)), center, radius)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['radiusPx'], radius, delta=0.35)

    def test_flat_shadow_cut_is_ignored(self):
        center, radius = (118.5, 99.2), 22.7
        result = self.fit(render_ball(center, radius, cut_above=center[1] - radius * 0.6), center, radius)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['radiusPx'], radius, delta=0.35)

    def test_no_ball_returns_none(self):
        self.assertIsNone(self.fit(self.background.copy(), (120.0, 100.0), 20.0))

    def test_ball_half_off_the_image_is_fitted_from_its_visible_arc(self):
        result = self.fit(render_ball((230.0, 100.0), 22.0), (230.0, 100.0), 22.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['radiusPx'], 22.0, delta=0.2)

    def test_a_sliver_of_ball_is_not_fitted(self):
        self.assertIsNone(self.fit(render_ball((250.0, 100.0), 22.0), (238.0, 100.0), 22.0))


class CompressionWindowTest(unittest.TestCase):
    def test_ball_size_is_not_used_while_the_ball_is_still_compressed(self):
        # Contact can be just before the first moving frame, so its size is never used;
        # at 250 fps a 5 ms recovery window also covers the next frame, 4 ms later.
        from unittest.mock import patch
        import launch_measurements
        background = np.full((200, 240), 20, np.uint8)
        rest, radius = np.array([40.0, 100.0]), 12.0
        frames, track = [], []
        for i in range(20):
            center = rest if i < 8 else rest + [(i - 7) * 9.0, 0.0]
            frames.append((i * 0.004, render_ball(center, radius)))
            track.append({'frameIndex': i, 'x': float(center[0]), 'y': float(center[1]), 'score': 0.99})
        bounds = (rest[0] - radius, rest[1] - radius, 2 * radius, 2 * radius)
        with patch.object(launch_measurements, 'BALL_RECOVERY_S', 0.005):
            _, _, observations = launch_measurements.trajectory_observations(frames, bounds, 8, track, background)
        for observation in observations[:2]:
            self.assertTrue(observation.get('compressionWindow'))
            self.assertIsNone(observation['radiusPx'])
        self.assertFalse(observations[2].get('compressionWindow'))
        later = [o for o in observations[2:] if o['radiusPx'] is not None]
        self.assertGreaterEqual(len(later), 5)
        for observation in later:
            self.assertAlmostEqual(observation['radiusPx'], radius, delta=0.3)


if __name__ == '__main__':
    unittest.main()
