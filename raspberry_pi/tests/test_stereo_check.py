"""Stereo cross-check: two cameras posed from one ground tag, a rendered ball in flight."""

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launch_measurements import GRAVITY, RADIUS, grade_metrics, unavailable  # noqa: E402
import launch_measurements as measurements  # noqa: E402
from stereo_check import StereoTrackingError, _circle_candidates, stereo_cross_check  # noqa: E402

MATRIX = np.array([[560., 0, 320], [0, 560., 200], [0, 0, 1]])
DISTORTION = np.zeros(5)
FPS = 242.0


def camera(height):
    """Looking along +x, 10 degrees down, like the vertical stand (lower 136 mm, top 222 mm)."""
    pitch = math.radians(10)
    forward = np.array([math.cos(pitch), 0, -math.sin(pitch)])
    right = np.array([0., -1, 0])
    down = np.cross(forward, right)
    rotation = np.vstack((right, down, forward))
    centre = np.array([-.55, 0., height])
    return rotation, -rotation @ centre


def render(points, cameras, count):
    """Paired bursts: a lit ball on a dark mat, resting until frame 20, gone after the flight."""
    bursts = []
    for rotation, translation in cameras:
        frames = []
        for index in range(count):
            image = np.full((400, 640, 3), 18, np.uint8)
            point = points[index]
            if point is not None:
                camera_point = rotation @ point + translation
                pixel = MATRIX @ camera_point
                centre = pixel[:2] / pixel[2]
                radius = MATRIX[0, 0] * RADIUS / camera_point[2]
                # Supersampled so sub-pixel centres survive rasterising.
                cv2.circle(image, tuple(int(round(v * 16)) for v in centre), int(round(radius * 16)), (235, 235, 235), -1,
                           cv2.LINE_AA, 4)
            frames.append((index / FPS, image))
        bursts.append(frames)
    return bursts


class StereoCrossCheckTests(unittest.TestCase):
    def setUp(self):
        self.lower, self.upper = camera(.136), camera(.222)

    def shot(self, speed, launch_deg, heading_deg, gravity=True, frames_out=16):
        # The ball starts left of centre and crosses the view, as it does on the stand.
        rest = np.array([0., .15, RADIUS])
        launch, heading = math.radians(launch_deg), math.radians(heading_deg)
        velocity = speed * np.array([math.cos(launch) * math.cos(heading), math.cos(launch) * math.sin(heading), math.sin(launch)])
        count, start = 100, 20
        points = [rest] * start
        for k in range(1, frames_out + 1):
            dt = k / FPS
            point = rest + velocity * dt
            point[2] -= .5 * GRAVITY * dt ** 2 if gravity else 0
            points.append(point)
        points += [None] * (count - len(points))
        lower_frames, upper_frames = render(points, (self.lower, self.upper), count)
        project = lambda p: (MATRIX @ (self.lower[0] @ p + self.lower[1]))
        pixel = lambda p: (project(p)[:2] / project(p)[2]).tolist()
        track = [{"frameIndex": start + k, "centerPx": pixel(points[start + k])} for k in range(frames_out)]
        return lower_frames, upper_frames, pixel(rest), track, (start - 1) / FPS, velocity

    def check(self, lower_frames, upper_frames, rest_px, track, start_time, mono_velocity, gravity=True):
        return stereo_cross_check(lower_frames, upper_frames, (MATRIX, DISTORTION, *self.lower),
                                  (MATRIX, DISTORTION, *self.upper), rest_px, track, start_time, mono_velocity, gravity)

    def test_triangulated_flight_matches_the_true_launch(self):
        *burst, velocity = self.shot(6.0, 25, -85)
        result = self.check(*burst, velocity)
        self.assertEqual(result["frames"], 16)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.06)
        self.assertAlmostEqual(result["launchDeg"], 25, delta=.5)
        self.assertAlmostEqual(result["headingDeg"], -85, delta=.5)
        self.assertLess(abs(result["restHeightErrorMm"]), 1.5)
        self.assertLess(result["medianRayGapMm"], 1)

    def test_disagreeing_single_camera_speed_is_reported(self):
        *burst, velocity = self.shot(6.0, 25, -85)
        result = self.check(*burst, velocity * 1.1)
        self.assertAlmostEqual(result["speedDifferencePct"], 9.1, delta=1)

    def test_stale_armed_box_recovers_persistent_resting_ball(self):
        lower_frames, upper_frames, rest_px, _, _, _ = self.shot(6.0, 25, -85)
        result = self.check(lower_frames, upper_frames, np.asarray(rest_px) + [30, 0], [], None, None, None)
        self.assertGreaterEqual(result["frames"], 10)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.2)

    def test_ground_fit_speed_matches_reported_horizontal_velocity(self):
        *burst, velocity = self.shot(4.0, 0, -85, gravity=False)
        result = self.check(*burst, velocity, gravity=False)
        self.assertEqual(result["velocityMps"][2], 0.0)
        self.assertAlmostEqual(result["speedMps"], np.linalg.norm(result["velocityMps"]), delta=.0001)

    def test_valid_stereo_replaces_a_biased_successful_single_camera_fit(self):
        lower_frames, upper_frames, rest_px, track, _, _ = self.shot(6.0, 25, -85)
        hints = [{"frameIndex": i, "x": rest_px[0], "y": rest_px[1], "score": 1.0} for i in (18, 19)]
        hints += [{"frameIndex": p["frameIndex"], "x": p["centerPx"][0], "y": p["centerPx"][1], "score": 1.0} for p in track]
        original_fit = measurements.fit_trajectory
        def biased_fit(*args):
            result = original_fit(*args)
            result["velocity"] = result["velocity"] * 1.2
            return result
        def stored(*args, camera="primary"):
            r, t = self.upper if camera == "secondary" else self.lower
            return {"rotation": r, "translation": t, "errorPx": .1, "frameIndex": None,
                    "source": "stored-calibration", "capturedAt": "2026-09-23T12:00:00Z"}
        with patch.object(measurements, "load_setup", return_value=(MATRIX, DISTORTION)), \
                patch.object(measurements, "stored_ground_pose", side_effect=stored), \
                patch.object(measurements, "fit_trajectory", side_effect=biased_fit), \
                patch.object(measurements, "resolve_target_heading", return_value=(0.0, "rolled-ball")), \
                patch.object(measurements, "measure_spin"), patch.object(measurements, "measure_club"):
            result = measurements.measure_launch(lower_frames, (rest_px[0]-21, rest_px[1]-21, 42, 42),
                                                 20, "sensor", 100, hints, upper_frames)
        self.assertEqual(result["method"], "shared-tag-stereo-v2")
        self.assertIn("monocularFit", result["diagnostics"])
        self.assertAlmostEqual(result["metrics"]["ballSpeedMps"]["value"], 6.0, delta=.2)
        self.assertGreater(result["diagnostics"]["stereo"]["speedDifferencePct"], 10)

    def test_failed_stereo_preserves_valid_single_camera_fit(self):
        lower_frames, upper_frames, rest_px, track, _, _ = self.shot(6.0, 25, -85)
        hints = [{"frameIndex": i, "x": rest_px[0], "y": rest_px[1], "score": 1.0} for i in (18, 19)]
        hints += [{"frameIndex": p["frameIndex"], "x": p["centerPx"][0],
                   "y": p["centerPx"][1], "score": 1.0} for p in track]
        def stored(*args, camera="primary"):
            r, t = self.upper if camera == "secondary" else self.lower
            return {"rotation": r, "translation": t, "errorPx": .1, "frameIndex": None,
                    "source": "stored-calibration", "capturedAt": "2026-09-23T12:00:00Z"}
        with patch.object(measurements, "load_setup", return_value=(MATRIX, DISTORTION)), \
                patch.object(measurements, "stored_ground_pose", side_effect=stored), \
                patch.object(measurements, "stereo_measurement", side_effect=ValueError("Only one stereo pair")), \
                patch.object(measurements, "resolve_target_heading", return_value=(0.0, "rolled-ball")), \
                patch.object(measurements, "measure_spin"), patch.object(measurements, "measure_club"):
            result = measurements.measure_launch(lower_frames, (rest_px[0]-21, rest_px[1]-21, 42, 42),
                                                 20, "sensor", 100, hints, upper_frames)
        self.assertNotIn("failure", result)
        self.assertEqual(result["method"], "apriltag-monocular-sphere-v1")
        self.assertAlmostEqual(result["metrics"]["ballSpeedMps"]["value"], 6.0, delta=.3)
        self.assertEqual(result["diagnostics"]["stereo"]["failure"], "Only one stereo pair")

    def test_recovers_from_wrong_primary_track_using_both_images(self):
        lower_frames, upper_frames, rest_px, track, start_time, _ = self.shot(6.0, 25, -85)
        wrong = [{"frameIndex": point["frameIndex"], "centerPx": [370, 124]} for point in track]
        result = self.check(lower_frames, upper_frames, rest_px, wrong, start_time, None)
        self.assertEqual(result["detection"], "independent-circles")
        self.assertIsInstance(result["candidateRejectedFrames"], list)
        self.assertGreaterEqual(result["frames"], 10)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.1)
        self.assertAlmostEqual(result["launchDeg"], 25, delta=1)

    def test_recovers_without_primary_track_or_departure_time(self):
        lower_frames, upper_frames, rest_px, _, _, _ = self.shot(6.0, 25, -85)
        result = self.check(lower_frames, upper_frames, rest_px, [], None, None)
        self.assertEqual(result["detection"], "independent-circles")
        self.assertGreaterEqual(result["frames"], 10)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.1)

    def test_three_paired_frames_produce_an_estimate(self):
        lower, upper, rest_px, track, start_time, velocity = self.shot(6.0, 25, -85, frames_out=3)
        result = self.check(lower, upper, rest_px, track, start_time, velocity)
        self.assertEqual(result["frames"], 3)
        self.assertAlmostEqual(result["speedMps"], 6.0, delta=.2)

    def test_two_paired_frames_estimate_speed_only_when_geometry_is_strong(self):
        lower, upper, rest_px, track, start_time, velocity = self.shot(15.0, 25, -85, frames_out=2)
        result = self.check(lower, upper, rest_px, track, start_time, velocity)
        self.assertTrue(result["speedOnly"])
        self.assertEqual(result["frameIndices"], [20, 21])
        self.assertAlmostEqual(result["speedMps"], 15.0, delta=.4)
        self.assertLess(result["speedUncertaintyPct"], 25)
        self.assertAlmostEqual(result["impactToFirstSpeedLowerBoundMps"], 15.0, delta=.5)
        self.assertNotIn("launchDeg", result)

    def test_two_paired_frames_with_weak_depth_are_rejected(self):
        lower, upper, rest_px, track, start_time, velocity = self.shot(6.0, 25, -85, frames_out=2)
        with self.assertRaisesRegex(StereoTrackingError, "too sensitive") as caught:
            self.check(lower, upper, rest_px, track, start_time, velocity)
        self.assertEqual(caught.exception.diagnostics["frames"], 2)
        self.assertGreater(caught.exception.diagnostics["speedUncertaintyPct"], 25)

    def test_two_point_pipeline_reports_speed_without_inventing_launch(self):
        lower, upper, rest_px, track, start_time, velocity = self.shot(15.0, 25, -85, frames_out=2)
        two_point = self.check(lower, upper, rest_px, track, start_time, velocity)
        two_point["accepted"] = True
        hints = [{"frameIndex": i, "x": rest_px[0], "y": rest_px[1], "score": 1.0} for i in (18, 19)]
        hints += [{"frameIndex": p["frameIndex"], "x": p["centerPx"][0],
                   "y": p["centerPx"][1], "score": 1.0} for p in track]
        with patch.object(measurements, "load_setup", return_value=(MATRIX, DISTORTION)), \
                patch.object(measurements, "stored_ground_pose", return_value={
                    "rotation": self.lower[0], "translation": self.lower[1], "errorPx": .1,
                    "frameIndex": None, "source": "stored-calibration", "capturedAt": "2026-09-23T12:00:00Z"}), \
                patch.object(measurements, "stereo_measurement", return_value=two_point), \
                patch.object(measurements, "resolve_target_heading", return_value=(0.0, "rolled-ball")):
            result = measurements.measure_launch(lower, (rest_px[0]-21, rest_px[1]-21, 42, 42),
                                                 20, "sensor", 100, hints, upper)
        self.assertEqual(result["method"], "shared-tag-stereo-two-point-v1")
        self.assertEqual(result["metrics"]["ballSpeedMps"]["status"], "estimated")
        self.assertAlmostEqual(result["metrics"]["ballSpeedMps"]["value"], 15.0, delta=.4)
        self.assertIsNone(result["metrics"]["launchAngleDeg"]["value"])
        self.assertIsNone(result["metrics"]["startDirectionDeg"]["value"])

    def test_weak_circle_recovery_still_uses_stereo_pairing(self):
        lower, upper, rest_px, track, start_time, _ = self.shot(6.0, 25, -85, frames_out=3)
        upper[21][1][0, 0] = (77, 77, 77)

        def miss_strong_upper_circle(image, radius, *, sensitive=False):
            if image[0, 0] == 77 and not sensitive:
                return []
            return _circle_candidates(image, radius, sensitive=sensitive)

        with patch("stereo_check._circle_candidates", side_effect=miss_strong_upper_circle):
            result = self.check(lower, upper, rest_px, track, start_time, None)
        self.assertEqual(result["frames"], 3)
        self.assertEqual([point["frameIndex"] for point in result["track"]], [20, 21, 22])

    def test_top_camera_that_cannot_see_the_ball_is_refused(self):
        lower_frames, upper_frames, rest_px, track, start_time, velocity = self.shot(6.0, 25, -85)
        blank = [(time, np.full_like(image, 18)) for time, image in upper_frames]
        with self.assertRaises(ValueError):
            self.check(lower_frames, blank, rest_px, track, start_time, velocity)

    def test_stereo_agreement_replaces_the_ball_size_check(self):
        result = {"metrics": unavailable("")}
        for key, value in (("ballSpeedMps", 6.0), ("launchAngleDeg", 25.0), ("startDirectionDeg", -3.0)):
            result["metrics"][key].update(value=value, status="estimated", reason="")
        fit = {"frames": 16, "rmsPx": .6, "ballSizeRatio": .9, "speedSigmaMps": .03, "launchSigmaDeg": .1,
               "headingSigmaDeg": .6}
        stereo = {"frames": 16, "medianRayGapMm": 1.7, "restHeightErrorMm": -.8, "startAnchorErrorMm": 2.0,
                  "maxPairOffsetUs": 10.0, "rmsPx": .6, "speedDifferencePct": .3,
                  "launchDifferenceDeg": .2, "headingDifferenceDeg": 1.0}
        grade_metrics(result, {"poseErrorPx": .1, "ballFit": fit, "stereo": stereo, "targetLineSource": "rolled-ball"})
        speed = result["metrics"]["ballSpeedMps"]
        self.assertEqual(speed["status"], "measured")
        self.assertFalse(any("Ball size" in check["label"] for check in speed["checks"]))
        self.assertTrue(any(check["label"].startswith("Stereo speed differs") for check in speed["checks"]))
        self.assertEqual(result["metrics"]["launchAngleDeg"]["status"], "measured")

        stereo["frames"] = 3
        result["metrics"]["ballSpeedMps"].update(status="estimated")
        grade_metrics(result, {"poseErrorPx": .1, "ballFit": fit, "stereo": stereo})
        self.assertEqual(result["metrics"]["ballSpeedMps"]["status"], "measured")
        self.assertTrue(any("Paired stereo frames" in check["label"] and check["passed"]
                            for check in result["metrics"]["ballSpeedMps"]["checks"]))
        stereo["frames"] = 16

        stereo["speedDifferencePct"] = 6.0
        result["metrics"]["ballSpeedMps"].update(status="estimated")
        grade_metrics(result, {"poseErrorPx": .1, "ballFit": fit, "stereo": stereo})
        self.assertEqual(result["metrics"]["ballSpeedMps"]["status"], "estimated")

        # Without stereo the ball-size check still decides, as before.
        grade_metrics(result, {"poseErrorPx": .1, "ballFit": fit})
        self.assertTrue(any("Ball size" in check["label"] for check in result["metrics"]["ballSpeedMps"]["checks"]))
        self.assertEqual(result["metrics"]["ballSpeedMps"]["status"], "estimated")


if __name__ == "__main__":
    unittest.main()
