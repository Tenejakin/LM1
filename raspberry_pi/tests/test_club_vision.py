"""Synthetic geometry for the tag-free clubhead path.

A rendered head silhouette with a known world velocity must come back out of the
swing-plane back-projection at the speed it was drawn with. These tests fix the
geometry only; they say nothing about whether a real club segments this cleanly.
"""

import json
import math
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import club_vision
from club_vision import face_contact, fit_club_velocity, head_points, load_club_profile, plane_point, swing_plane
from launch_measurements import RADIUS, measure_club, unavailable


def side_on_camera(height=.2009, pitch_deg=10.57, distance=.5):
    """The real rig's geometry: low, near-horizontal, looking across the swing.

    World +X is the target line, +Y left, +Z up. The camera sits off to the -Y side
    so the ball's swing plane is broadside to it, which is the only placement that
    makes clubhead depth observable without a tag.
    """
    pitch = math.radians(pitch_deg)
    rotation = np.array([[1., 0., 0.],
                         [0., -math.sin(pitch), -math.cos(pitch)],
                         [0., math.cos(pitch), -math.sin(pitch)]])
    position = np.array([0., -distance, height])
    return rotation, -rotation @ position


class SwingPlaneTests(unittest.TestCase):
    def setUp(self):
        self.matrix = np.array([[800., 0, 640], [0, 800, 400], [0, 0, 1]])
        self.distortion = np.zeros(5)
        self.rotation, self.translation = side_on_camera()

    def _pixel(self, world):
        camera = self.rotation @ np.asarray(world, float) + self.translation
        pixel = self.matrix @ camera
        return pixel[:2] / pixel[2]

    def test_camera_fixture_is_a_valid_pose(self):
        np.testing.assert_allclose(self.rotation.T @ self.rotation, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(float(np.linalg.det(self.rotation)), 1.0, places=12)

    def test_camera_looking_along_the_swing_is_refused_rather_than_guessed(self):
        # A top-down camera's rays lie inside a vertical swing plane: depth is not
        # observable, and a silently returned number would be meaningless.
        overhead, overhead_translation = np.diag([1., -1., -1.]), np.array([0., 0., .8])
        ball = np.array([.05, 0., RADIUS])
        normal, _ = swing_plane(ball, np.array([3., 0., .3]))
        with self.assertRaises(ValueError) as raised:
            plane_point(np.array([640., 400.]), self.matrix, self.distortion,
                        overhead, overhead_translation, ball, normal)
        self.assertIn('look across the swing', str(raised.exception))

    def test_plane_point_recovers_a_world_point_on_the_plane(self):
        ball = np.array([.05, 0., RADIUS])
        normal, forward = swing_plane(ball, np.array([3., 0., .3]))
        np.testing.assert_allclose(forward, [1, 0, 0], atol=1e-9)
        target = np.array([-.04, 0., .06])
        recovered = plane_point(self._pixel(target), self.matrix, self.distortion,
                                self.rotation, self.translation, ball, normal)
        np.testing.assert_allclose(recovered, target, atol=1e-9)

    def test_swing_plane_needs_a_horizontal_ball_direction(self):
        with self.assertRaises(ValueError):
            swing_plane(np.array([0., 0., RADIUS]), np.array([0., 0., 4.]))

    def test_fit_rejects_a_track_that_does_not_move_in_a_straight_line(self):
        times = [i * .001 for i in range(6)]
        positions = [[i * .012, 0, .05 + (.09 if i == 3 else 0)] for i in range(6)]
        with self.assertRaises(ValueError) as raised:
            fit_club_velocity(times, positions)
        self.assertIn('not tracking cleanly', str(raised.exception))

    def test_head_band_discards_the_shaft_above_it(self):
        head = np.array([[x, y] for x in range(600, 660) for y in range(390, 440)], float)
        shaft = np.array([[x, y] for x in range(625, 635) for y in range(250, 390)], float)
        kept = head_points(np.vstack((head, shaft)), 22.0)
        self.assertLess(kept[:, 1].min(), 400)
        self.assertGreaterEqual(kept[:, 1].min(), 440 - 2.4 * 22 - 1)
        self.assertEqual(len(kept), np.count_nonzero(np.vstack((head, shaft))[:, 1] >= 439 - 2.4 * 22))


class StableRunTests(unittest.TestCase):
    """Areas taken from capture-1789685046360385423, where the head crosses a lighting edge."""

    REAL_AREAS = [806.0, 755.0, 769.0, 815.0, 817.0, 356.0, 376.0, 345.5, 360.5, 343.5]

    def _samples(self, areas, start=172):
        return [{"frameIndex": start + offset, "areaPx": area} for offset, area in enumerate(areas)]

    def test_lighting_step_splits_the_track_and_the_later_run_wins(self):
        kept = club_vision.stable_samples(self._samples(self.REAL_AREAS))
        self.assertEqual([sample["frameIndex"] for sample in kept], [177, 178, 179, 180, 181])

    def test_a_uniform_track_is_kept_whole(self):
        kept = club_vision.stable_samples(self._samples([400.0, 410.0, 395.0, 405.0, 402.0]))
        self.assertEqual(len(kept), 5)

    def test_a_frame_gap_breaks_the_run(self):
        # Frames the segmenter could not resolve leave a hole; the two sides are not
        # one track even though the area never changes across it.
        samples = self._samples([400.0] * 8)
        for sample in samples[4:]:
            sample["frameIndex"] += 5
        kept = club_vision.stable_samples(samples)
        self.assertEqual([sample["frameIndex"] for sample in kept], [181, 182, 183, 184])

    def test_three_clean_frames_between_edge_entry_and_contact_are_usable(self):
        # capture-1790292584248245554: head clipped at the image edge (148 px), three
        # clean frames, then merged with the ball at contact (124 px).
        kept = club_vision.stable_samples(self._samples([148.0, 439.0, 416.0, 394.0, 124.0], start=107))
        self.assertEqual([sample["frameIndex"] for sample in kept], [108, 109, 110])
        self.assertGreaterEqual(len(kept), club_vision.MIN_TRACK_FRAMES)

    def test_no_run_reaches_the_minimum_returns_the_longest_for_reporting(self):
        kept = club_vision.stable_samples(self._samples([400.0, 800.0, 1600.0, 400.0]))
        self.assertLess(len(kept), club_vision.MIN_TRACK_FRAMES)


class TaglessClubTests(unittest.TestCase):
    """Render a descending head and require the drawn velocity back."""

    SPEED_X = 12.0
    SPEED_Z = -1.2
    STEP_S = .001

    def setUp(self):
        self.matrix = np.array([[800., 0, 640], [0, 800, 400], [0, 0, 1]])
        self.distortion = np.zeros(5)
        self.rotation, self.translation = side_on_camera()
        self.ball = np.array([0., 0., RADIUS])
        self.impact_index = 12

    def _pixel(self, world):
        camera = self.rotation @ np.asarray(world, float) + self.translation
        pixel = self.matrix @ camera
        return pixel[:2] / pixel[2]

    def _radius_px(self, world):
        depth = float((self.rotation @ np.asarray(world, float) + self.translation)[2])
        return self.matrix[0, 0] * RADIUS / depth

    def _quad(self, frame, corners, shade):
        points = np.array([self._pixel(corner) for corner in corners])
        cv2.fillPoly(frame, [np.round(points * 16).astype(np.int32)], shade, shift=4)

    def _frames(self):
        background = np.full((800, 1280), 30, np.uint8)
        cv2.circle(background, tuple(np.round(self._pixel(self.ball) * 16).astype(int)),
                   round(self._radius_px(self.ball) * 16), 220, -1, shift=4)
        frames = []
        for index in range(self.impact_index + 1):
            frame = background.copy()
            x = -.2 + index * self.SPEED_X * self.STEP_S
            sole = .05 + index * self.SPEED_Z * self.STEP_S
            # Head: a 40 mm wide, 45 mm tall face slab in the ball's swing plane.
            self._quad(frame, [[x - .02, 0, sole], [x + .02, 0, sole],
                               [x + .02, 0, sole + .045], [x - .02, 0, sole + .045]], 200)
            # Shaft: far above the head band, so it must be discarded.
            self._quad(frame, [[x - .005, 0, sole + .045], [x + .005, 0, sole + .045],
                               [x + .06, 0, sole + .4], [x + .05, 0, sole + .4]], 180)
            frames.append((index * self.STEP_S, frame))
        return background, frames

    def _measure(self, heading=0.0, profile=None, ball_speed=18.0):
        background, frames = self._frames()
        ball_pixel = self._pixel(self.ball)
        radius_px = self._radius_px(self.ball)
        bounds = (ball_pixel[0] - radius_px, ball_pixel[1] - radius_px, radius_px * 2, radius_px * 2)
        metrics = unavailable('fixture')
        metrics['ballSpeedMps']['value'] = ball_speed
        result = {'metrics': metrics, 'diagnostics': {}}

        def put(key, value, reason, status='estimated'):
            if math.isfinite(value):
                metrics[key].update(value=round(float(value), 4), reason=reason, status=status)

        with TemporaryDirectory() as directory:
            environment = {'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent.json')}
            profile_path = Path(directory) / 'profile.json'
            if profile is not None:
                profile_path.write_text(json.dumps(profile))
            environment['PINPOINT_CLUB_PROFILE_PATH'] = str(profile_path)
            with patch.dict(os.environ, environment):
                measure_club(frames, self.impact_index, self.matrix, self.distortion,
                             self.rotation, self.translation,
                             [{'frameIndex': 0, 'positionM': self.ball.tolist()}], result, put,
                             background, bounds, np.array([3., 0., .3]), heading)
        return result, metrics

    def test_impossible_smash_leaves_club_values_unavailable(self):
        # Replayed chip 1790291608690789660: 19.5 m/s ball, 7.9 m/s club, smash 2.47.
        speed = math.hypot(self.SPEED_X, self.SPEED_Z)
        _, metrics = self._measure(ball_speed=speed * 2.2)
        for key in ('clubSpeedMps', 'smashFactor', 'attackAngleDeg'):
            self.assertIsNone(metrics[key]['value'])
        self.assertIn('above any real club', metrics['clubSpeedMps']['reason'])

    def test_speed_and_attack_angle_match_the_rendered_motion(self):
        result, metrics = self._measure()
        expected = math.hypot(self.SPEED_X, self.SPEED_Z)
        self.assertIsNotNone(metrics['clubSpeedMps']['value'], metrics['clubSpeedMps']['reason'])
        self.assertAlmostEqual(metrics['clubSpeedMps']['value'], expected, delta=.25)
        self.assertAlmostEqual(metrics['attackAngleDeg']['value'],
                               math.degrees(math.atan2(self.SPEED_Z, self.SPEED_X)), delta=1.0)
        self.assertAlmostEqual(metrics['smashFactor']['value'], 18.0 / expected, delta=.05)
        self.assertEqual(metrics['clubSpeedMps']['status'], 'estimated')
        self.assertIn('swing plane', metrics['clubSpeedMps']['reason'])
        self.assertGreaterEqual(result['diagnostics']['clubSilhouette']['acceptedFrames'],
                                club_vision.MIN_TRACK_FRAMES)
        self.assertEqual(len(result['clubTrack3d']),
                         result['diagnostics']['clubSilhouette']['acceptedFrames'])

    def test_club_path_is_refused_because_the_swing_plane_would_restate_start_direction(self):
        # The plane is built from the ball's horizontal direction, so a path taken from
        # it equals start direction by construction and would be a circular measurement.
        for heading in (None, 0.0, math.radians(12.0)):
            _, metrics = self._measure(heading=heading)
            self.assertIsNotNone(metrics['clubSpeedMps']['value'])
            self.assertIsNone(metrics['clubPathDeg']['value'])
            self.assertIn('Not observable without a club tag', metrics['clubPathDeg']['reason'])

    def test_attack_angle_survives_because_the_plane_does_not_constrain_vertical_motion(self):
        _, metrics = self._measure()
        self.assertAlmostEqual(metrics['attackAngleDeg']['value'],
                               math.degrees(math.atan2(self.SPEED_Z, self.SPEED_X)), delta=1.0)

    def test_strike_is_unavailable_without_a_measured_face_profile(self):
        _, metrics = self._measure()
        self.assertIsNone(metrics['strikeXmm']['value'])
        self.assertIn('Measure the clubface once', metrics['strikeXmm']['reason'])
        self.assertIn('no club tag is needed', metrics['strikeXmm']['reason'])

    def test_speed_survives_without_a_face_profile(self):
        _, metrics = self._measure()
        self.assertIsNotNone(metrics['clubSpeedMps']['value'])
        self.assertIsNotNone(metrics['attackAngleDeg']['value'])

    def test_missing_capture_context_reports_why_rather_than_guessing(self):
        metrics = unavailable('fixture')
        result = {'metrics': metrics}
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent.json')}):
                measure_club([], 0, self.matrix, self.distortion, self.rotation, self.translation,
                             [], result, lambda *a, **k: None)
        for key in ('clubSpeedMps', 'smashFactor', 'strikeXmm', 'strikeYmm', 'clubPathDeg', 'attackAngleDeg'):
            self.assertIsNone(metrics[key]['value'])
            self.assertIn('fitted ball velocity', metrics[key]['reason'])


class FaceContactTests(unittest.TestCase):
    def setUp(self):
        # 100 px across a 100 mm face, with the ball 21.335 mm in radius.
        self.radius_px = 21.335
        self.forward = np.array([1., 0.])
        self.profile = {'faceWidthMm': 100.0, 'faceHeightMm': 50.0, 'clubId': 'driver'}
        self.head = np.array([[x, y] for x in np.arange(600., 601.) for y in np.arange(400., 450.)])
        # Face spanning 100 px vertically (the across axis is image y for forward +x).
        self.head = np.array([[600. + dx, 400. + dy] for dx in range(2) for dy in range(101)])

    def test_centered_contact_reads_near_zero(self):
        ball = np.array([600., 450.])
        strike_x, strike_y, span = face_contact(self.head, ball, self.radius_px, self.forward, self.profile)
        self.assertAlmostEqual(span, 100.0, delta=1.5)
        self.assertAlmostEqual(strike_x, 0.0, delta=1.5)
        self.assertAlmostEqual(strike_y, 25.0, delta=1.5)

    def test_absent_profile_explains_the_one_off_measurement(self):
        with self.assertRaises(ValueError) as raised:
            face_contact(self.head, np.array([600., 450.]), self.radius_px, self.forward, None)
        self.assertIn('Measure the clubface once', str(raised.exception))

    def test_implausible_span_is_rejected_rather_than_reported(self):
        narrow = np.array([[600. + dx, 400. + dy] for dx in range(2) for dy in range(20)])
        with self.assertRaises(ValueError) as raised:
            face_contact(narrow, np.array([600., 410.]), self.radius_px, self.forward, self.profile)
        self.assertIn('plausible heel-toe width', str(raised.exception))

    def test_profile_for_the_wrong_club_is_rejected(self):
        with self.assertRaises(ValueError) as raised:
            face_contact(self.head, np.array([600., 450.]), self.radius_px, self.forward,
                         {'faceWidthMm': 60.0, 'faceHeightMm': 50.0})
        self.assertIn('disagrees with the saved', str(raised.exception))


class ClubProfileTests(unittest.TestCase):
    def _load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            path.write_text(json.dumps(payload))
            with patch.dict(os.environ, {'PINPOINT_CLUB_PROFILE_PATH': str(path)}):
                return load_club_profile()

    def test_valid_profile_loads(self):
        profile = self._load({'version': 1, 'faceWidthMm': 100, 'faceHeightMm': 50, 'clubId': 'driver'})
        self.assertEqual(profile['faceWidthMm'], 100.0)
        self.assertEqual(profile['clubId'], 'driver')

    def test_absent_file_is_not_an_error(self):
        with patch.dict(os.environ, {'PINPOINT_CLUB_PROFILE_PATH': '/nonexistent/profile.json'}):
            self.assertIsNone(load_club_profile())

    def test_out_of_range_face_size_is_refused(self):
        self.assertIsNone(self._load({'version': 1, 'faceWidthMm': 400, 'faceHeightMm': 50}))
        self.assertIsNone(self._load({'version': 1, 'faceWidthMm': 100, 'faceHeightMm': 500}))

    def test_unversioned_profile_is_refused(self):
        self.assertIsNone(self._load({'faceWidthMm': 100, 'faceHeightMm': 50}))


if __name__ == '__main__':
    unittest.main()
