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
from launch_measurements import (RADIUS, camera_target_heading_rad, find_ground_tag_pose, fit_velocity, load_setup,
                                 measure_club, measure_launch, measure_roll, resolve_target_heading, rotation_between,
                                 sphere_center, surface_vectors, tag_pose, target_rotation, unavailable)
from ball_detector import RollingFrameBuffer


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.matrix = np.array([[800., 0, 640], [0, 800, 400], [0, 0, 1]])
        self.distortion = np.zeros(5)

    def test_off_axis_sphere_recovers_known_depth(self):
        center = np.array([0.15, 0.07, 0.8])
        axis = center / np.linalg.norm(center)
        first = np.cross(axis, [0, 1, 0]); first /= np.linalg.norm(first)
        second = np.cross(axis, first)
        angle = np.arcsin(RADIUS / np.linalg.norm(center))
        contour = []
        for phi in np.linspace(0, 2 * np.pi, 100, endpoint=False):
            ray = axis * np.cos(angle) + (first * np.cos(phi) + second * np.sin(phi)) * np.sin(angle)
            pixel = self.matrix @ ray
            contour.append(pixel[:2] / pixel[2])
        np.testing.assert_allclose(sphere_center(contour, self.matrix, self.distortion), center, atol=1e-6)

    def _sphere_outline(self, center, angle_scale=lambda phi: 1.0, count=200):
        axis = center / np.linalg.norm(center)
        first = np.cross(axis, [0, 1, 0]); first /= np.linalg.norm(first)
        second = np.cross(axis, first)
        angle = np.arcsin(RADIUS / np.linalg.norm(center))
        contour = []
        for phi in np.linspace(0, 2 * np.pi, count, endpoint=False):
            a = angle * angle_scale(phi)
            ray = axis * np.cos(a) + (first * np.cos(phi) + second * np.sin(phi)) * np.sin(a)
            pixel = self.matrix @ ray
            contour.append(pixel[:2] / pixel[2])
        return contour

    def test_seam_notch_in_silhouette_still_recovers_sphere(self):
        center = np.array([0.12, 0.05, 0.35])
        # A dark seam line cuts a narrow dent into the thresholded outline.
        notched = self._sphere_outline(center, lambda phi: 0.8 if 1.2 < phi < 1.6 else 1.0)
        np.testing.assert_allclose(sphere_center(notched, self.matrix, self.distortion), center, atol=1e-6)

    def test_seam_line_splitting_ball_silhouette_is_bridged(self):
        from launch_measurements import ball_contours
        background = np.full((400, 640), 30, np.uint8)
        frame = background.copy()
        cv2.circle(frame, (400, 250), 32, 220, -1)
        # A narrow dark seam line crossing the whole ball splits the thresholded disc in two.
        cv2.line(frame, (360, 270), (440, 230), 30, 2)
        halves, _ = cv2.findContours(cv2.threshold(cv2.subtract(frame, background), 20, 255, cv2.THRESH_BINARY)[1], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        self.assertEqual(len(halves), 2)
        found = ball_contours(frame, background, 33)
        self.assertEqual(len(found), 1)
        np.testing.assert_allclose(found[0][0], [400, 250], atol=2)

    def test_partial_silhouette_requires_guided_fill_gate(self):
        from launch_measurements import ball_contours
        background = np.full((400, 640), 30, np.uint8)
        frame = background.copy()
        cv2.circle(frame, (400, 250), 32, 220, -1)
        cv2.rectangle(frame, (404, 218), (432, 282), 30, -1)

        self.assertEqual(ball_contours(frame, background, 33), [])
        found = ball_contours(frame, background, 33, minimum_fill=.5)
        self.assertEqual(len(found), 1)

    def test_elongated_blob_is_still_rejected(self):
        center = np.array([0.12, 0.05, 0.35])
        # A ball merged with a club head reads as a stretched, non-circular outline.
        stretched = [(u * 1.6 - 0.6 * 928, v) for u, v in self._sphere_outline(center)]
        with self.assertRaises(ValueError):
            sphere_center(stretched, self.matrix, self.distortion)

    def test_tag_pose_and_world_axes_round_trip(self):
        points = np.array([[0., 0, 0], [.1, 0, 0], [.1, -.1, 0], [0, -.1, 0]])
        rotation = np.array([2.6, 0.1, 0.2])
        translation = np.array([0.1, -0.05, 0.8])
        corners = cv2.projectPoints(points, rotation, translation, self.matrix, self.distortion)[0].reshape(4, 2)
        r, t = tag_pose(corners, .1, self.matrix, self.distortion)
        np.testing.assert_allclose(t, translation, atol=1e-6)
        np.testing.assert_allclose(r, cv2.Rodrigues(rotation)[0], atol=1e-6)

    def test_ground_tag_search_uses_best_pose_not_first_detection(self):
        frames = [(i * .005, np.full((2, 2), i, np.uint8)) for i in range(25)]

        def detect(frame):
            index = int(frame[0, 0])
            return {0: np.full((4, 2), index, dtype=float)} if index in (10, 15) else {}

        def solve(corners, _size, _matrix, _distortion):
            index = int(corners[0, 0])
            error = 2.2 if index == 10 else .4
            return np.eye(3), np.array([0., 0., .8]), error

        with patch('launch_measurements.marker_map', side_effect=detect), patch('launch_measurements.solve_tag_pose', side_effect=solve):
            pose = find_ground_tag_pose(frames, 18, 0, .1, self.matrix, self.distortion)

        self.assertIsNotNone(pose)
        self.assertEqual(pose['frameIndex'], 15)
        self.assertAlmostEqual(pose['errorPx'], .4)

    def test_velocity_uses_nonuniform_actual_times(self):
        times = np.array([1, 1.005, 1.011, 1.016])
        expected = np.array([40., -2., 10.])
        velocity, error = fit_velocity(times, (times - times[0])[:, None] * expected + [0, 0, .03])
        np.testing.assert_allclose(velocity, expected, atol=1e-9)
        self.assertLess(error, 1e-9)

    def test_bad_timestamps_and_tracks_are_rejected(self):
        with self.assertRaises(ValueError): fit_velocity([0, 0, .01], np.zeros((3, 3)))
        with self.assertRaises(ValueError): fit_velocity([0, .005, .01], [[0, 0, 0], [1, 1, 1], [.1, 0, 0]])

    def test_surface_rotation_recovers_known_rotation(self):
        first = np.array([[.1, .2, -.97], [-.3, .1, -.95], [.2, -.4, -.89], [-.3, -.3, -.9]])
        first /= np.linalg.norm(first, axis=1)[:, None]
        expected = cv2.Rodrigues(np.array([.05, -.2, .03]))[0]
        np.testing.assert_allclose(rotation_between(first, first @ expected.T), expected, atol=1e-9)

    def test_center_ray_hits_front_ball_surface(self):
        vectors, valid = surface_vectors([[640, 400]], np.array([0, 0, .8]), self.matrix, self.distortion)
        self.assertTrue(valid[0])
        np.testing.assert_allclose(vectors[0], [0, 0, -1], atol=1e-8)

    def test_sensor_metadata_retained_with_ring(self):
        buffer = RollingFrameBuffer(2)
        for i in range(3):
            buffer.append(np.zeros((20, 20), np.uint8), metadata={'SensorTimestamp': 1_000_000_000 + i * 5_000_000, 'ExposureTime': 50})
        self.assertEqual(buffer.timestamp_source, 'sensor')
        self.assertAlmostEqual(buffer.frames[-1][0] - buffer.frames[0][0], .005)
        buffer.clear()
        self.assertEqual(buffer.timestamp_source, 'host')

    def test_calibration_resolution_mismatch_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with patch.dict(os.environ, {'PINPOINT_INTRINSICS_PATH': str(path)}):
                load_setup((1280, 800))
                with self.assertRaises(ValueError): load_setup((640, 400))

    def test_host_timing_never_returns_physical_metrics(self):
        result = measure_launch([(0, np.zeros((20, 20), np.uint8))], (2, 2, 10, 10), 0)
        self.assertTrue(all(metric['value'] is None for metric in result['metrics'].values()))
        self.assertIn('Sensor timestamps', result['failure'])

    def test_rendered_ball_burst_produces_launch_estimate(self):
        rotation = np.diag([1., -1., -1.])
        translation = np.array([0., 0., .8])
        tag_points = np.array([[0., 0, 0], [.1, 0, 0], [.1, -.1, 0], [0, -.1, 0]])
        corners = cv2.projectPoints(tag_points, cv2.Rodrigues(rotation)[0], translation, self.matrix, self.distortion)[0].reshape(4, 2)
        frames = []
        for i in range(18):
            elapsed = max(0, i - 7) * .005
            world = np.array([.05 + elapsed * 3, -.05, RADIUS + elapsed * .5])
            camera = rotation @ world + translation
            pixel = self.matrix @ camera; pixel = pixel[:2] / pixel[2]
            frame = np.full((800, 1280), 30, np.uint8)
            cv2.circle(frame, tuple(np.round(pixel * 16).astype(int)), round(800 * RADIUS / camera[2] * 16), 230, -1, shift=4)
            frames.append((1 + i * .005, frame))
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with patch.dict(os.environ, {'PINPOINT_INTRINSICS_PATH': str(path), 'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent.json')}), patch('launch_measurements.marker_map', return_value={0: corners}):
                result = measure_launch(frames, (669, 429, 45, 45), 8, 'sensor', 50)
        value = result['metrics']['ballSpeedMps']['value']
        self.assertIsNotNone(value, result.get('failure'))
        self.assertAlmostEqual(value, np.hypot(3, .5), delta=.25)
        self.assertIsNone(result['metrics']['clubSpeedMps']['value'])
        self.assertEqual(result['metrics']['ballSpeedMps']['status'], 'estimated')

    def test_tracker_guided_partial_silhouettes_produce_lower_confidence_estimate(self):
        frames = [(1 + i * .005, np.full((800, 1280), i, np.uint8)) for i in range(18)]
        velocity = np.array([3., -.5, .4])
        centers = {}
        contours = {}
        for i in range(8, 11):
            camera = np.array([.05, -.05, .8]) + (i - 8) * .005 * velocity
            contour = np.asarray(self._sphere_outline(camera), np.float32).reshape(-1, 1, 2)
            (x, y), _ = cv2.minEnclosingCircle(contour)
            centers[i] = np.array([x, y])
            contours[i] = contour
        motion_track = [
            {'frameIndex': i, 'x': float(centers[i][0]), 'y': float(centers[i][1]), 'score': .9}
            for i in range(8, 11)
        ]

        def contours_for_frame(frame, _background, _seed_radius, minimum_fill=.82):
            index = int(frame[0, 0])
            if minimum_fill < .82 and index in contours:
                return [(centers[index], contours[index])]
            return []

        pose = {'rotation': np.eye(3), 'translation': np.zeros(3), 'errorPx': .2, 'frameIndex': 7}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with (
                patch.dict(os.environ, {
                    'PINPOINT_INTRINSICS_PATH': str(path),
                    'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent-club.json'),
                    'PINPOINT_TARGET_LINE_PATH': str(Path(directory) / 'absent-target.json'),
                }),
                patch('launch_measurements.find_ground_tag_pose', return_value=pose),
                patch('launch_measurements.ball_contours', side_effect=contours_for_frame),
            ):
                result = measure_launch(
                    frames, (615, 375, 50, 50), 8, 'sensor', 50,
                    motion_track=motion_track,
                )
                rejected = measure_launch(
                    frames, (615, 375, 50, 50), 8, 'sensor', 50,
                    motion_track=motion_track[:2],
                )

        self.assertNotIn('failure', result)
        self.assertAlmostEqual(result['metrics']['ballSpeedMps']['value'], np.linalg.norm(velocity), delta=.25)
        self.assertEqual([point['frameIndex'] for point in result['ballTrack3d']], [8, 9, 10])
        self.assertIn('tracker-guided partial silhouette', result['warnings'][0].lower())
        self.assertIn('Tracker-guided partial-silhouette fallback', result['metrics']['ballSpeedMps']['reason'])
        self.assertIn('Fewer than three usable 3D', rejected['failure'])
        self.assertIn('tracked motion in 2', rejected['failure'])
        self.assertEqual(rejected['diagnostics']['guided']['longestRun'], 2)
        self.assertEqual([point['status'] for point in rejected['diagnostics']['guided']['frames']], ['accepted', 'accepted'])
        self.assertEqual(result['diagnostics']['calibration']['imageSize'], [1280, 800])
        self.assertEqual(result['diagnostics']['calibration']['groundTagSizeMm'], 100)
        self.assertEqual(result['diagnostics']['groundPose']['cameraHeightMm'], 0)

    def _side_camera(self):
        # 216 mm high, 450 mm from the ball, pitched 13 degrees down, like the bench rig.
        c, s = np.cos(np.radians(13)), np.sin(np.radians(13))
        rotation = np.array([[0., 1, 0], [s, 0, -c], [-c, 0, -s]])
        return rotation, -rotation @ np.array([.45, 0., .216])

    def _guided_shot(self, positions, silhouette_scales):
        rotation, translation = self._side_camera()
        frames = [(1 + i * .005, np.full((800, 1280), i, np.uint8)) for i in range(18)]
        centers, contours = {}, {}
        for i, (world, scale) in enumerate(zip(positions, silhouette_scales), start=8):
            camera = rotation @ np.asarray(world) + translation
            contour = np.asarray(self._sphere_outline(camera, lambda _phi, scale=scale: scale), np.float32).reshape(-1, 1, 2)
            (x, y), _ = cv2.minEnclosingCircle(contour)
            centers[i], contours[i] = np.array([x, y]), contour
        motion_track = [{'frameIndex': i, 'x': float(c[0]), 'y': float(c[1]), 'score': .9} for i, c in centers.items()]
        rest = self.matrix @ (rotation @ np.array([0., -.08, RADIUS]) + translation)
        rest = rest[:2] / rest[2]
        bounds = (round(rest[0]) - 25, round(rest[1]) - 25, 50, 50)

        def contours_for_frame(frame, _background, _seed_radius, minimum_fill=.82):
            index = int(frame[0, 0])
            return [(centers[index], contours[index])] if minimum_fill < .82 and index in contours else []

        pose = {'rotation': rotation, 'translation': translation, 'errorPx': .2, 'frameIndex': 7}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with (
                patch.dict(os.environ, {
                    'PINPOINT_INTRINSICS_PATH': str(path),
                    'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent-club.json'),
                    'PINPOINT_TARGET_LINE_PATH': str(Path(directory) / 'absent-target.json'),
                }),
                patch('launch_measurements.find_ground_tag_pose', return_value=pose),
                patch('launch_measurements.ball_contours', side_effect=contours_for_frame),
            ):
                return measure_launch(frames, bounds, 8, 'sensor', 50, motion_track=motion_track)

    def test_rolling_ball_with_growing_silhouette_reports_zero_launch(self):
        # Capture 1789481235085592832: the rolling ball's apparent radius grew 4% over
        # the three fitted frames, which single-view depth read as a 24 degree launch.
        positions = [[0., -.05 + k * .005, RADIUS] for k in range(3)]
        result = self._guided_shot(positions, [1.0, 1.02, 1.04])
        self.assertNotIn('failure', result)
        self.assertEqual(result['metrics']['launchAngleDeg']['value'], 0)
        self.assertIn('ground', result['metrics']['launchAngleDeg']['reason'])
        self.assertAlmostEqual(result['metrics']['ballSpeedMps']['value'], 1.0, delta=.05)
        self.assertEqual(result['metrics']['estimatedCarryM']['value'], 0)
        self.assertEqual(result['groundRoll']['velocitySource'], 'template-track')

    def test_rising_ball_keeps_measured_launch_angle(self):
        positions = [[0., -.05 + k * .015, RADIUS + k * .0075] for k in range(8)]
        result = self._guided_shot(positions, [1.0] * 8)
        self.assertNotIn('failure', result)
        self.assertNotIn('groundRoll', result)
        self.assertAlmostEqual(result['metrics']['launchAngleDeg']['value'], np.degrees(np.arctan2(1.5, 3)), delta=2)

    def _observed_shot(self, velocity, count=24, radius_scale=lambda k: 1.0, gravity=True, seed=3):
        """Side-camera image track of a ball leaving its resting spot at t=0."""
        from launch_measurements import GRAVITY
        rotation, translation = self._side_camera()
        rest = np.array([0., -.08, RADIUS])
        rng = np.random.default_rng(seed)
        # The ball leaves at frame 9's timestamp; observation k is frame 10 + k.
        frames = [((i - 9) / 242, np.zeros((800, 1280), np.uint8)) for i in range(count + 10)]
        observations = []
        for k in range(count):
            dt = (k + 1) / 242
            world = rest + np.asarray(velocity) * dt
            if gravity:
                world[2] -= .5 * GRAVITY * dt ** 2
            camera = rotation @ world + translation
            pixel = self.matrix @ camera
            radius = 800 * RADIUS / np.linalg.norm(camera) * radius_scale(k)
            observations.append({'frameIndex': 10 + k,
                                 'centerPx': (pixel[:2] / pixel[2] + rng.normal(0, .25, 2)).tolist(),
                                 'radiusPx': float(radius + rng.normal(0, .5))})
        rest_camera = self.matrix @ (rotation @ rest + translation)
        return frames, rest_camera[:2] / rest_camera[2], observations, rotation, translation

    def test_trajectory_fit_rolling_ball_ignores_growing_radius(self):
        from launch_measurements import fit_trajectory
        heading = np.radians(80)
        velocity = [np.cos(heading), np.sin(heading), 0.]
        frames, rest, observations, rotation, translation = self._observed_shot(
            velocity, radius_scale=lambda k: 1 + .004 * k, gravity=False)
        fit = fit_trajectory(frames, rest, (frames[9][0], frames[10][0]), observations,
                             self.matrix, np.zeros(5), rotation, translation)
        self.assertEqual(fit['model'], 'ground')
        self.assertAlmostEqual(np.linalg.norm(fit['velocity']), 1.0, delta=.03)
        self.assertAlmostEqual(fit['diagnostics']['headingDeg'], 80, delta=1.5)
        self.assertEqual(fit['velocity'][2], 0)

    def test_trajectory_fit_resolves_airborne_launch_and_direction(self):
        from launch_measurements import fit_trajectory
        launch, heading, speed = np.radians(20), np.radians(85), 5.
        velocity = speed * np.array([np.cos(launch) * np.cos(heading), np.cos(launch) * np.sin(heading), np.sin(launch)])
        frames, rest, observations, rotation, translation = self._observed_shot(velocity, count=14)
        fit = fit_trajectory(frames, rest, (frames[9][0], frames[10][0]), observations,
                             self.matrix, np.zeros(5), rotation, translation)
        self.assertEqual(fit['model'], 'flight')
        fitted = fit['velocity']
        self.assertAlmostEqual(np.linalg.norm(fitted), speed, delta=.25)
        self.assertAlmostEqual(np.degrees(np.arctan2(fitted[2], np.hypot(*fitted[:2]))), 20, delta=2)
        self.assertAlmostEqual(fit['diagnostics']['headingDeg'], 85, delta=2)
        self.assertIsNotNone(fit['diagnostics']['launchSigmaDeg'])

    def test_trajectory_fit_reestimates_start_of_nudged_ball(self):
        # Capture 1789480689809610280: a finger pushed the ball sideways before the roll.
        from launch_measurements import fit_trajectory
        heading = np.radians(80)
        frames, _, observations, rotation, translation = self._observed_shot(
            [.9 * np.cos(heading), .9 * np.sin(heading), 0.], gravity=False)
        stale = self.matrix @ (rotation @ np.array([.03, -.08, RADIUS]) + translation)
        fit = fit_trajectory(frames, stale[:2] / stale[2], (frames[0][0], frames[10][0]), observations,
                             self.matrix, np.zeros(5), rotation, translation)
        self.assertEqual(fit['model'], 'ground')
        self.assertEqual(fit['diagnostics']['startPoint'], 're-estimated')
        self.assertAlmostEqual(np.linalg.norm(fit['velocity']), .9, delta=.03)
        self.assertAlmostEqual(fit['diagnostics']['headingDeg'], 80, delta=1.5)

    def test_trajectory_fit_rejects_occluded_frames(self):
        # Capture 1789481235085592832: finger occlusion displaced early centres by ~9 px.
        from launch_measurements import fit_trajectory
        heading = np.radians(85)
        frames, rest, observations, rotation, translation = self._observed_shot(
            [np.cos(heading), np.sin(heading), 0.], gravity=False)
        for k in (1, 2):
            observations[k]['centerPx'][1] -= 9
        fit = fit_trajectory(frames, rest, (frames[9][0], frames[10][0]), observations,
                             self.matrix, np.zeros(5), rotation, translation)
        self.assertEqual(fit['diagnostics']['rejectedFrames'], [11, 12])
        self.assertEqual(fit['diagnostics']['startPoint'], 'resting-ball')
        self.assertAlmostEqual(np.linalg.norm(fit['velocity']), 1.0, delta=.03)
        self.assertLess(fit['diagnostics']['rmsPx'], 1)

    def test_measure_launch_uses_trajectory_fit_for_long_image_track(self):
        from target_line import heading_from_track
        rotation, translation = self._side_camera()
        rest = np.array([0., -.08, RADIUS])
        heading = np.radians(75)
        centers, contours = {}, {}
        motion_track = []
        for i in range(40):
            dt = max(0, i - 9) / 242
            world = rest + np.array([np.cos(heading), np.sin(heading), 0.]) * .9 * dt
            camera = rotation @ world + translation
            contour = np.asarray(self._sphere_outline(camera, lambda _phi, k=i: 1 + .003 * max(0, k - 9)), np.float32).reshape(-1, 1, 2)
            (x, y), _ = cv2.minEnclosingCircle(contour)
            centers[i], contours[i] = np.array([x, y]), contour
            motion_track.append({'frameIndex': i, 'x': float(x), 'y': float(y), 'score': .95})
        frames = [(1 + i / 242, np.full((800, 1280), i, np.uint8)) for i in range(40)]
        bounds = (round(centers[0][0]) - 25, round(centers[0][1]) - 25, 50, 50)

        def contours_for_frame(frame, _background, _seed_radius, minimum_fill=.82):
            index = int(frame[0, 0])
            return [(centers[index], contours[index])] if minimum_fill < .82 else []

        pose = {'rotation': rotation, 'translation': translation, 'errorPx': .2, 'frameIndex': 0}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with (
                patch.dict(os.environ, {
                    'PINPOINT_INTRINSICS_PATH': str(path),
                    'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent-club.json'),
                    'PINPOINT_TARGET_LINE_PATH': str(Path(directory) / 'absent-target.json'),
                }),
                patch('launch_measurements.find_ground_tag_pose', return_value=pose),
                patch('launch_measurements.ball_contours', side_effect=contours_for_frame),
            ):
                result = measure_launch(frames, bounds, 12, 'sensor', 50, motion_track=motion_track)
        self.assertNotIn('failure', result)
        self.assertEqual(result['diagnostics']['trajectoryFit']['model'], 'ground')
        self.assertEqual(result['metrics']['launchAngleDeg']['value'], 0)
        self.assertAlmostEqual(result['metrics']['ballSpeedMps']['value'], .9, delta=.03)
        self.assertIn('Anchored trajectory fit', result['metrics']['ballSpeedMps']['reason'])
        self.assertAlmostEqual(heading_from_track(result['ballTrack3d'])[0], 75, delta=1.5)

    def test_guided_rejection_identifies_invalid_depth(self):
        from launch_measurements import guided_ball_track
        frames = [(i * .005, np.zeros((100, 100), np.uint8)) for i in range(3)]
        contour = np.array([[[45, 50]], [[50, 45]], [[55, 50]], [[50, 55]]], np.float32)
        hints = [{'frameIndex': i, 'x': 50., 'y': 50., 'score': .9} for i in range(3)]
        diagnostics = {}
        with patch('launch_measurements.ball_contours', return_value=[(np.array([50., 50.]), contour)]), patch('launch_measurements.sphere_center', return_value=np.array([0., 0., .5])):
            result = guided_ball_track(frames, frames[0][1], 10, hints, np.array([10., 50.]), self.matrix, self.distortion,
                                       np.eye(3), np.array([0., 0., .6]), diagnostics)
        self.assertIsNone(result)
        self.assertEqual(diagnostics['longestRun'], 0)
        self.assertEqual([p['status'] for p in diagnostics['frames']], ['invalid-depth'] * 3)
        self.assertEqual(diagnostics['frames'][0]['heightMm'], -100)

    def test_capture_summary_keeps_diagnostics_on_disk_only(self):
        from pinpoint_protocol import PinpointProtocol
        capture = {'measurements': {'diagnostics': {'frames': list(range(1000))}, 'metrics': {'example': 1},
                                    'ballTrack3d': [1, 2], 'clubTrack3d': []}}
        summary = PinpointProtocol._capture_summary(capture)
        self.assertNotIn('diagnostics', summary['measurements'])
        self.assertEqual(summary['measurements']['metrics'], {'example': 1})
        self.assertIn('diagnostics', capture['measurements'])

    def test_imperfect_ground_tag_returns_lower_confidence_estimate(self):
        rotation = np.diag([1., -1., -1.])
        translation = np.array([0., 0., .8])
        frames = []
        for i in range(18):
            elapsed = max(0, i - 7) * .005
            world = np.array([.05 + elapsed * 3, -.05, RADIUS + elapsed * .5])
            camera = rotation @ world + translation
            pixel = self.matrix @ camera; pixel = pixel[:2] / pixel[2]
            frame = np.full((800, 1280), 30, np.uint8)
            cv2.circle(frame, tuple(np.round(pixel * 16).astype(int)), round(800 * RADIUS / camera[2] * 16), 230, -1, shift=4)
            frames.append((1 + i * .005, frame))
        pose = {'rotation': rotation, 'translation': translation, 'errorPx': 2.2, 'frameIndex': 12}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with patch.dict(os.environ, {'PINPOINT_INTRINSICS_PATH': str(path), 'PINPOINT_CLUB_MARKER_PATH': str(Path(directory) / 'absent.json')}), patch('launch_measurements.find_ground_tag_pose', return_value=pose):
                result = measure_launch(frames, (669, 429, 45, 45), 8, 'sensor', 50)

        self.assertIsNotNone(result['metrics']['ballSpeedMps']['value'], result.get('failure'))
        self.assertIn('lower-confidence estimates', result['warnings'][0])
        self.assertIn('2.20 px', result['metrics']['ballSpeedMps']['reason'])
        self.assertEqual(result['tagPoseFrameIndex'], 12)

    def test_ground_tag_above_estimation_limit_is_rejected(self):
        frames = [(i * .005, np.zeros((800, 1280), np.uint8)) for i in range(3)]
        pose = {'rotation': np.eye(3), 'translation': np.array([0., 0., .8]), 'errorPx': 3.01, 'frameIndex': 1}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'intrinsics.json'
            path.write_text(json.dumps({'imageSize': [1280, 800], 'cameraMatrix': self.matrix.tolist(), 'distCoeffs': [0]*5, 'rmsPx': .2}))
            with patch.dict(os.environ, {'PINPOINT_INTRINSICS_PATH': str(path)}), patch('launch_measurements.find_ground_tag_pose', return_value=pose):
                result = measure_launch(frames, (10, 10, 20, 20), 1, 'sensor', 50)

        self.assertIn('3.0 px estimation limit', result['failure'])
        self.assertTrue(all(metric['value'] is None for metric in result['metrics'].values()))

    def test_club_pose_speed_and_face_contact_geometry(self):
        frames = [(i * .005, np.zeros((800, 1280), np.uint8)) for i in range(7)]
        ground_translation = np.array([0., 0., 1.])
        marker_points = np.array([[0., 0, 0], [.02, 0, 0], [.02, -.02, 0], [0, -.02, 0]])
        maps = []
        for i in range(7):
            face = np.array([.1 - RADIUS - (6 - i) * .005 * 2, 0, .1])
            corners = cv2.projectPoints(marker_points, np.zeros(3), face + ground_translation, self.matrix, self.distortion)[0].reshape(4, 2)
            maps.append({1: corners})
        metrics = unavailable('fixture'); metrics['ballSpeedMps']['value'] = 3
        result = {'metrics': metrics}
        def put(key, value, reason): metrics[key].update(value=value, reason=reason)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'club.json'
            path.write_text(json.dumps({'clubId': 'driver', 'tagId': 1, 'tagSizeMm': 20, 'faceCenterM': [0,0,0], 'faceAxes': [[0,0,1],[1,0,0],[0,1,0]]}))
            with patch.dict(os.environ, {'PINPOINT_CLUB_MARKER_PATH': str(path)}), patch('launch_measurements.marker_map', side_effect=maps):
                measure_club(frames, 6, self.matrix, self.distortion, np.eye(3), ground_translation,
                             [{'frameIndex': 0, 'positionM': [.1, 0, .1]}], result, put)
        self.assertAlmostEqual(metrics['clubSpeedMps']['value'], 2, places=5)
        self.assertAlmostEqual(metrics['smashFactor']['value'], 1.5, places=5)
        self.assertAlmostEqual(metrics['strikeXmm']['value'], 0, places=4)
        self.assertAlmostEqual(metrics['strikeYmm']['value'], 0, places=4)

    def test_camera_axis_supplies_the_target_line_without_a_rolled_ball(self):
        # The live rig's stored ground pose. Its across-image axis is all but aligned
        # with the tag's top edge, which is what squaring the monitor to the target means.
        rotation = np.array([
            [0.9999533098858718, 0.005103651944612008, -0.008205533810640908],
            [-0.007129659055635766, -0.18352155158849573, -0.9829898311093057],
            [-0.006522730259615519, 0.9830024378603439, -0.1834765956480034]])
        heading = camera_target_heading_rad(rotation)
        self.assertAlmostEqual(math.degrees(heading), 0.29, places=2)
        # A ball running left to right across the image reads as straight.
        across = rotation.T @ np.array([1., 0., 0.])
        aligned = target_rotation(heading) @ np.array([across[0], across[1], 0.])
        self.assertAlmostEqual(-math.degrees(math.atan2(aligned[1], aligned[0])), 0.0, places=9)

    def test_camera_yaw_rotates_the_target_line_with_it(self):
        for degrees in (-40.0, -5.0, 17.5, 63.0):
            yaw = math.radians(degrees)
            spin = np.array([[math.cos(yaw), math.sin(yaw), 0.], [-math.sin(yaw), math.cos(yaw), 0.], [0., 0., 1.]])
            self.assertAlmostEqual(math.degrees(camera_target_heading_rad(spin)), degrees, places=9)

    def test_a_camera_rolled_to_portrait_has_no_ground_heading(self):
        # Image-right pointing straight up has no horizontal component to project.
        portrait = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])
        with self.assertRaises(ValueError) as raised:
            camera_target_heading_rad(portrait)
        self.assertIn('rolled too close to portrait', str(raised.exception))

    def test_a_saved_rolled_ball_line_still_wins_over_the_camera_axis(self):
        rotation = np.eye(3)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'target-line.json'
            path.write_text(json.dumps({'version': 1, 'headingDeg': 42.0}))
            with patch.dict(os.environ, {'PINPOINT_TARGET_LINE_PATH': str(path)}):
                heading, source = resolve_target_heading(rotation)
            self.assertAlmostEqual(math.degrees(heading), 42.0, places=9)
            self.assertEqual(source, 'rolled-ball')
            with patch.dict(os.environ, {'PINPOINT_TARGET_LINE_PATH': str(path / 'absent.json')}):
                heading, source = resolve_target_heading(rotation)
            self.assertAlmostEqual(math.degrees(heading), 0.0, places=9)
            self.assertEqual(source, 'camera-axis')

    def test_putt_stop_and_rolling_transition(self):
        frames = [(i * .01, None) for i in range(31)]
        track = [{'frameIndex': i, 'positionM': [min(i, 15) * .01, 0, RADIUS]} for i in range(31)]
        result = {'metrics': unavailable('fixture'), 'spinSamples': [
            {'frameIndex': i, 'nextFrameIndex': i+1, 'angularVelocityRadS': [0, 1/RADIUS, 0]} for i in range(3)]}
        def put(key, value, reason): result['metrics'][key].update(value=value, reason=reason)
        measure_roll(frames, track, result, put)
        self.assertAlmostEqual(result['metrics']['rollDistanceM']['value'], .15)
        self.assertAlmostEqual(result['metrics']['skidDistanceM']['value'], 0)


if __name__ == '__main__': unittest.main()
