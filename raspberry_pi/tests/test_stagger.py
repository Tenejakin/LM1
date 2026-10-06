"""Staggered capture: the top camera's frames fall half a frame after the lower camera's."""

import math
import os
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PINPOINT_GROUND_MODE", "tag")

from launch_measurements import GRAVITY, RADIUS  # noqa: E402
from stereo_check import StereoTrackingError, is_staggered, stagger_offset_us, stereo_cross_check  # noqa: E402

MATRIX = np.array([[560., 0, 320], [0, 560., 200], [0, 0, 1]])
DISTORTION = np.zeros(5)
FPS = 242.0
PERIOD = 1 / FPS


def camera(height):
    """Looking along +x, 10 degrees down, like the vertical stand (lower 136 mm, top 222 mm)."""
    pitch = math.radians(10)
    forward = np.array([math.cos(pitch), 0, -math.sin(pitch)])
    right = np.array([0., -1, 0])
    down = np.cross(forward, right)
    rotation = np.vstack((right, down, forward))
    centre = np.array([-.55, 0., height])
    return rotation, -rotation @ centre


def draw(position, cam):
    image = np.full((400, 640, 3), 18, np.uint8)
    if position is not None:
        rotation, translation = cam
        camera_point = rotation @ position + translation
        pixel = MATRIX @ camera_point
        centre = pixel[:2] / pixel[2]
        radius = MATRIX[0, 0] * RADIUS / camera_point[2]
        cv2.circle(image, tuple(int(round(v * 16)) for v in centre), int(round(radius * 16)), (235, 235, 235), -1, cv2.LINE_AA, 4)
    return image


class StaggeredScene:
    """A ball resting until frame 20 then in flight, seen by cameras that are `offset` seconds apart."""

    REST = np.array([0., .15, RADIUS])
    START = 20
    COUNT = 100

    def __init__(self, speed, launch_deg, heading_deg, offset, contact_fraction=0.3, gravity=True):
        self.lower, self.upper = camera(.136), camera(.222)
        launch, heading = math.radians(launch_deg), math.radians(heading_deg)
        self.velocity = speed * np.array([math.cos(launch) * math.cos(heading), math.cos(launch) * math.sin(heading), math.sin(launch)])
        self.contact = (self.START - 1 + contact_fraction) * PERIOD
        self.offset, self.gravity = offset, gravity

    def position(self, time):
        if time <= self.contact:
            return self.REST
        dt = time - self.contact
        point = self.REST + self.velocity * dt
        point[2] -= .5 * GRAVITY * dt ** 2 if self.gravity else 0
        return point

    def frames(self):
        lower_frames, upper_frames = [], []
        for index in range(self.COUNT):
            t = index * PERIOD
            lower_frames.append((t, draw(self.position(t), self.lower)))
            upper_frames.append((t + self.offset, draw(self.position(t + self.offset), self.upper)))
        return lower_frames, upper_frames

    def pixel(self, position):
        cam = MATRIX @ (self.lower[0] @ position + self.lower[1])
        return (cam[:2] / cam[2]).tolist()

    def track(self, frames_out=16):
        return [{"frameIndex": self.START + k, "centerPx": self.pixel(self.position((self.START + k) * PERIOD))}
                for k in range(frames_out)]

    def check(self, lower_frames, upper_frames, track, mono_velocity, gravity=True):
        return stereo_cross_check(lower_frames, upper_frames, (MATRIX, DISTORTION, *self.lower),
                                  (MATRIX, DISTORTION, *self.upper), self.pixel(self.REST), track,
                                  (self.START - 1) * PERIOD, mono_velocity, gravity)


class LateHitScene(StaggeredScene):
    """A long address: the ball rests for 100 frames of a 180-frame burst, past the old search's half-way limit."""

    START = 100
    COUNT = 180


class LongAddressTests(unittest.TestCase):
    """The independent search used to look for the resting ball only in the first half of the burst,
    so a hit after the middle of the burst (frame ~100 of 182 in real captures) was never reached."""

    def test_a_hit_past_the_middle_of_the_burst_is_found_without_a_lower_track(self):
        for offset in (0.0, 0.5 * PERIOD):
            scene = LateHitScene(6.0, 25, -85, offset)
            lower_frames, upper_frames = scene.frames()
            result = scene.check(lower_frames, upper_frames, [], None, None)
            self.assertEqual(result["detection"], "independent-circles", offset)
            self.assertGreaterEqual(result["frames"], 8, offset)
            self.assertAlmostEqual(result["speedMps"], 6.0, delta=.25, msg=str(offset))
            self.assertAlmostEqual(result["launchDeg"], 25, delta=1.5, msg=str(offset))


class FlightSearchTests(unittest.TestCase):
    """When pairing circles frame by frame finds nothing, a launch anchored at the resting ball is searched
    for among everything ball-sized that appears after the hit, in either camera at any frame."""

    def search(self, scene, lower_frames, upper_frames):
        import stereo_check as sc
        lower, upper = sc._camera(MATRIX, DISTORTION, *scene.lower), sc._camera(MATRIX, DISTORTION, *scene.upper)
        rest_radii = [RADIUS * camera["K"][0, 0] / (camera["R"] @ scene.REST + camera["t"])[2] for camera in (lower, upper)]
        return sc._anchored_flight_search(lower, upper, lower_frames, upper_frames, scene.REST, scene.START - 1, rest_radii)

    def test_the_launch_is_found_from_unpaired_sightings_in_step_and_staggered(self):
        for speed, launch in ((25.0, 20), (36.0, 15), (40.0, 15)):
            for offset in (0.0, 0.5 * PERIOD):
                scene = LateHitScene(speed, launch, -85, offset, contact_fraction=0.5)
                lower_frames, upper_frames = scene.frames()
                fit = self.search(scene, lower_frames, upper_frames)
                label = f"{speed} m/s offset {offset}"
                self.assertAlmostEqual(fit["speed"], speed, delta=speed * 0.06, msg=label)
                self.assertAlmostEqual(fit["launch"], launch, delta=3.0, msg=label)
                self.assertAlmostEqual(fit["heading"], -85, delta=6.0, msg=label)
                self.assertGreaterEqual(fit["detections"], 4, label)
                self.assertLessEqual(fit["rms"], 3.5, label)

    def test_it_covers_iron_and_driver_speeds(self):
        import stereo_check as sc
        self.assertGreaterEqual(float(sc.SEARCH_SPEEDS.max()), 75.0)
        self.assertLessEqual(float(sc.SEARCH_SPEEDS.min()), 3.0)
        self.assertLessEqual(float(np.max(sc.SEARCH_SPEEDS[1:] / sc.SEARCH_SPEEDS[:-1])), 1.06)

    def test_an_empty_scene_does_not_invent_a_shot(self):
        scene = LateHitScene(0.0, 0, 0, 0.5 * PERIOD)
        scene.velocity = np.zeros(3)  # the ball never moves
        lower_frames, upper_frames = scene.frames()
        import stereo_check as sc
        with self.assertRaises(sc.FlightSearchError):
            self.search(scene, lower_frames, upper_frames)

    def test_the_result_carries_what_the_pipeline_grades(self):
        scene = LateHitScene(36.0, 15, -85, 0.5 * PERIOD, contact_fraction=0.5)
        lower_frames, upper_frames = scene.frames()
        fit = self.search(scene, lower_frames, upper_frames)
        for key in ("velocity", "ray_gaps", "track", "contact", "t_rest", "speed_sigma", "launch_sigma", "heading_sigma"):
            self.assertIn(key, fit)
        self.assertTrue(all({"frameIndex", "centerPx", "upperPx", "positionM"} <= set(point) for point in fit["track"]))
        self.assertLess(float(np.median(fit["ray_gaps"])), 6.0)


class StaggerDetectionTests(unittest.TestCase):
    def test_in_step_and_staggered_bursts_are_told_apart(self):
        for offset, expected in ((0.0, False), (25e-6, False), (0.5 * PERIOD, True), (-0.5 * PERIOD, True), (0.25 * PERIOD, True)):
            scene = StaggeredScene(6.0, 25, -85, offset)
            lower_frames, upper_frames = [(i * PERIOD, None) for i in range(50)], [(i * PERIOD + offset, None) for i in range(50)]
            self.assertEqual(is_staggered(lower_frames, upper_frames), expected, offset)
        nominal = stagger_offset_us([(i * PERIOD, None) for i in range(50)], [(i * PERIOD + 0.0021, None) for i in range(50)])
        self.assertAlmostEqual(nominal, 2100.0, places=3)


class StaggeredStereoTests(unittest.TestCase):
    def test_guided_fit_recovers_the_launch_from_half_a_frame_offset(self):
        scene = StaggeredScene(6.0, 25, -85, 0.5 * PERIOD)
        lower_frames, upper_frames = scene.frames()
        result = scene.check(lower_frames, upper_frames, scene.track(), scene.velocity)
        self.assertTrue(result["staggered"])
        self.assertAlmostEqual(result["staggerOffsetUs"], 0.5 * PERIOD * 1e6, delta=1)
        self.assertLess(result["maxPairOffsetUs"], 1.0)
        self.assertEqual(result["detection"], "epipolar-template")
        self.assertGreaterEqual(result["frames"], 12)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.1)
        self.assertAlmostEqual(result["launchDeg"], 25, delta=.7)
        self.assertAlmostEqual(result["headingDeg"], -85, delta=.7)
        self.assertLess(result["medianRayGapMm"], 2.5)

    def test_it_matters_that_the_offset_is_honoured(self):
        # Pretending the same frames were simultaneous smears the ball's motion into a depth error.
        scene = StaggeredScene(10.0, 25, -85, 0.5 * PERIOD)
        lower_frames, upper_frames = scene.frames()
        honest = scene.check(lower_frames, upper_frames, scene.track(), scene.velocity)
        pretend = [(t_lower, image) for (t_lower, _), (_, image) in zip(lower_frames, upper_frames)]
        try:
            naive = scene.check(lower_frames, pretend, scene.track(), scene.velocity)
        except StereoTrackingError:
            return  # the in-step matcher finds no ball at all in staggered frames: honouring the offset is what makes it work
        self.assertFalse(naive["staggered"])
        honest_error = abs(honest["speedMps"] - 10.0) + abs(honest["launchDeg"] - 25) + abs(honest["headingDeg"] + 85)
        naive_error = abs(naive["speedMps"] - 10.0) + abs(naive["launchDeg"] - 25) + abs(naive["headingDeg"] + 85)
        self.assertLess(honest_error, naive_error)

    def test_offsets_other_than_half_a_frame_and_negative_ones_work(self):
        for fraction in (0.3, 0.7, -0.4):
            scene = StaggeredScene(6.0, 25, -85, fraction * PERIOD)
            lower_frames, upper_frames = scene.frames()
            result = scene.check(lower_frames, upper_frames, scene.track(), scene.velocity)
            self.assertTrue(result["staggered"], fraction)
            self.assertAlmostEqual(result["speedMps"], 6.0, delta=.15, msg=str(fraction))
            self.assertAlmostEqual(result["launchDeg"], 25, delta=1.0, msg=str(fraction))

    def test_independent_detection_finds_the_ball_without_a_lower_track(self):
        scene = StaggeredScene(6.0, 25, -85, 0.5 * PERIOD)
        lower_frames, upper_frames = scene.frames()
        result = scene.check(lower_frames, upper_frames, [], None, None)
        self.assertEqual(result["detection"], "independent-circles")
        self.assertTrue(result["staggered"])
        self.assertGreaterEqual(result["frames"], 10)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.2)
        self.assertAlmostEqual(result["launchDeg"], 25, delta=1.5)

    def test_a_ball_that_leaves_quickly_still_gives_a_fit_in_step_or_staggered(self):
        # 20 m/s crosses the view in a handful of frames: the staggered burst has the same frames but
        # each camera samples different instants, so the fit is at least as well posed.
        counts = {}
        for name, offset in (("in step", 0.0), ("staggered", 0.5 * PERIOD)):
            scene = StaggeredScene(20.0, 20, -85, offset)
            lower_frames, upper_frames = scene.frames()
            try:
                result = scene.check(lower_frames, upper_frames, scene.track(8), scene.velocity)
            except StereoTrackingError:
                counts[name] = 0
                continue
            counts[name] = result["frames"]
            self.assertAlmostEqual(result["speedMps"], 20.0, delta=1.0, msg=name)
        self.assertGreaterEqual(counts["staggered"], 3)

    def test_two_staggered_pairs_give_a_full_fit_where_in_step_gets_nothing(self):
        # 54 m/s is in view for two frames in each camera. In step that is two triangulated points (a speed
        # at best, and here not even that); staggered it is four sample instants, enough to fit and to check.
        in_step = StaggeredScene(54.0, 14, -85, 0.0, contact_fraction=0.5)
        lower_frames, upper_frames = in_step.frames()
        with self.assertRaises(StereoTrackingError):
            in_step.check(lower_frames, upper_frames, in_step.track(6), in_step.velocity)
        staggered = StaggeredScene(54.0, 14, -85, 0.5 * PERIOD, contact_fraction=0.5)
        lower_frames, upper_frames = staggered.frames()
        result = staggered.check(lower_frames, upper_frames, staggered.track(6), staggered.velocity)
        self.assertEqual(result["frames"], 2)
        self.assertEqual(result["instants"], 4)
        self.assertNotIn("speedOnly", result)
        self.assertAlmostEqual(result["speedMps"], 54.0, delta=1.5)
        self.assertAlmostEqual(result["launchDeg"], 14, delta=1.0)
        self.assertAlmostEqual(result["headingDeg"], -85, delta=1.5)
        self.assertGreater(result["spanMs"], 5.0)

    def test_ground_roll_staggered(self):
        scene = StaggeredScene(4.0, 0, -85, 0.5 * PERIOD, gravity=False)
        lower_frames, upper_frames = scene.frames()
        result = scene.check(lower_frames, upper_frames, scene.track(), scene.velocity, gravity=False)
        self.assertEqual(result["velocityMps"][2], 0.0)
        self.assertAlmostEqual(result["speedMps"], 4.0, delta=.15)


if __name__ == "__main__":
    unittest.main()
