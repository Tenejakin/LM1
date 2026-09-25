"""Evidence-driven workflow regressions; synthetic frames are test fixtures only."""
import asyncio
import os
from pathlib import Path
import sys
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ball_detector import BallMonitor, DetectionObservation, RollingFrameBuffer, analyze_departure, ball_template_similarity, scale_bounds
from pinpoint_protocol import PinpointProtocol


def burst(moving=False, irregular=False):
    buffer = RollingFrameBuffer(20)
    for i in range(20):
        frame = np.full((120, 160), 40, dtype=np.uint8)
        if i < 8 or moving:
            cv2.circle(frame, (40 + (i - 7) * 5 if i >= 8 else 40, 70), 7, 230, -1)
        buffer.append(frame, i * 0.005 + (0.1 if irregular and i >= 10 else 0))
    return buffer


class AnalysisTests(unittest.TestCase):
    def test_ble_capture_summary_reports_tracking_without_full_trace(self):
        capture = {'measurements': {
            'metrics': {'ballSpeedMps': {'value': None}},
            'diagnostics': {'motionTrackedFrames': 4, 'stereo': {
                'failure': 'Only two paired frames', 'frames': 2,
                'frameIndices': [118, 120], 'candidateRejections': {'noCircle': 3},
            }},
            'ballTrack3d': [{'frameIndex': 118, 'positionM': [0, 0, 0]}],
        }, 'track': [{'frameIndex': 118}], 'image': {'base64': 'test'}}
        summary = PinpointProtocol._capture_summary(capture)
        tracking = summary['measurements']['tracking']
        self.assertEqual(tracking['status'], 'failed')
        self.assertEqual(tracking['pairedFrames'], 2)
        self.assertEqual(tracking['pairedFrameIndices'], [118, 120])
        self.assertEqual(tracking['lowerFrames'], 4)
        self.assertNotIn('diagnostics', summary['measurements'])
        self.assertEqual(summary['measurements']['ballTrack3d'], [])

    def test_lift_without_outgoing_track_is_not_a_measured_shot(self):
        result = analyze_departure(burst(), (31, 61, 19, 19), 8)
        self.assertEqual(result['classification'], 'unconfirmed-departure')
        self.assertEqual(result['coarseDepartureFrameIndex'], 8)
        self.assertEqual(result['lastStationaryFrameIndex'], 7)
        self.assertIsNone(result['firstMovingFrameIndex'])
        self.assertEqual(result['impactFrameIndex'], 8)
        self.assertNotIn('ballSpeedMps', result)
        self.assertTrue(result['image']['base64'])
        self.assertEqual(result['measuredFps'], 200)

    def test_motion_is_evidence_not_claim_of_club_contact(self):
        result = analyze_departure(burst(moving=True), (31, 61, 19, 19), 8)
        self.assertEqual(result['classification'], 'motion-observed')
        self.assertEqual(result['lastStationaryFrameIndex'], 7)
        self.assertEqual(result['firstMovingFrameIndex'], 8)
        self.assertEqual(result['impactFrameIndex'], 8)
        self.assertTrue(any('does not prove' in warning for warning in result['warnings']))

    def test_late_coarse_trigger_is_refined_to_full_rate_motion_window(self):
        buffer = RollingFrameBuffer(24)
        reference = None
        for i in range(24):
            frame = np.full((180, 320), 35, dtype=np.uint8)
            if i <= 7:
                center = (70, 120)
            else:
                center = (70 + (i - 7) * 38, 120 - (i - 7) * 7)
            if center[0] < frame.shape[1] - 10:
                cv2.circle(frame, center, 10, 225, -1)
                cv2.circle(frame, (center[0] - 3, center[1] - 2), 2, 90, -1)
            buffer.append(frame, i * 0.005)
            if i == 4:
                reference = frame.copy()

        result = analyze_departure(buffer, (59, 109, 23, 23), 17, ball_reference=reference)

        self.assertEqual(result['coarseDepartureFrameIndex'], 17)
        self.assertEqual(result['lastStationaryFrameIndex'], 7)
        self.assertEqual(result['firstMovingFrameIndex'], 8)
        self.assertEqual(result['impactFrameIndex'], 8)
        self.assertEqual(result['imageFrameIndex'], 7)
        self.assertEqual(result['classification'], 'motion-observed')

    def test_dropped_frames_report_timing_warning(self):
        result = analyze_departure(burst(irregular=True), (31, 61, 19, 19), 8)
        self.assertTrue(any('dropped' in warning for warning in result['warnings']))

    def test_offset_resting_ball_is_not_motion_at_start_of_burst(self):
        reference = np.full((180, 320), 35, dtype=np.uint8)
        cv2.circle(reference, (90, 120), 10, 225, -1)
        buffer = RollingFrameBuffer(24)
        for i in range(24):
            frame = np.full_like(reference, 35)
            center = (65 if i < 8 else 65 + (i - 7) * 12, 120)
            cv2.circle(frame, center, 10, 225, -1)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (79, 109, 23, 23), 17, ball_reference=reference)
        self.assertEqual(result['lastStationaryFrameIndex'], 7)
        self.assertEqual(result['firstMovingFrameIndex'], 8)
        self.assertEqual(result['imageFrameIndex'], 7)

    def test_static_offset_match_without_resting_anchor_is_not_outgoing(self):
        reference = np.full((180, 320), 35, dtype=np.uint8)
        cv2.circle(reference, (90, 120), 10, 225, -1)
        buffer = RollingFrameBuffer(24)
        for i in range(24):
            frame = np.full_like(reference, 35)
            cv2.circle(frame, (240, 120), 10, 225, -1)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (79, 109, 23, 23), 17, ball_reference=reference)
        self.assertIsNone(result['firstMovingFrameIndex'])

    def test_lookalike_moving_while_ball_rests_is_not_departure(self):
        # Capture 1789479880648283083: a hand matched the ball template and moved
        # outward long before the real roll; the resting ball stayed visible.
        buffer = RollingFrameBuffer(40)
        for i in range(40):
            frame = np.full((180, 320), 35, dtype=np.uint8)
            cv2.circle(frame, (70 if i < 25 else 70 + (i - 24) * 8, 120), 10, 225, -1)
            if 5 <= i <= 7:
                cv2.circle(frame, (70, 95 - (i - 5) * 7), 10, 225, -1)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (59, 109, 23, 23), 30)
        self.assertEqual(result['firstMovingFrameIndex'], 25)
        self.assertEqual(result['lastStationaryFrameIndex'], 24)

    def test_armed_reference_with_placing_hand_falls_back_to_clean_resting_ball(self):
        # Capture 1789480689809610280: the ball armed while fingers still held it.
        reference = np.full((180, 320), 35, dtype=np.uint8)
        cv2.circle(reference, (70, 120), 10, 225, -1)
        cv2.rectangle(reference, (50, 104), (100, 124), 150, -1)
        buffer = RollingFrameBuffer(40)
        for i in range(40):
            frame = np.full_like(reference, 35)
            cv2.circle(frame, (70 if i < 25 else 70 + (i - 24) * 8, 120), 10, 225, -1)
            cv2.rectangle(frame, (150, 20), (200, 40), 150, -1)
            cv2.circle(frame, (175, 36), 10, 225, -1)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (59, 109, 23, 23), 30, ball_reference=reference)
        self.assertEqual(result['firstMovingFrameIndex'], 25)
        self.assertEqual(result['lastStationaryFrameIndex'], 24)

    def test_early_nudge_before_later_roll_uses_motion_nearest_trigger(self):
        # A finger nudges the ball outward and occludes it, then the real roll
        # starts just before the debounced trigger.
        buffer = RollingFrameBuffer(60)
        for i in range(60):
            frame = np.full((180, 320), 35, dtype=np.uint8)
            if i < 10:
                center = (70, 120)
            elif i < 14:
                center = (70 + (i - 9) * 4, 120)
            elif i < 40:
                center = None
            else:
                center = (90 + (i - 39) * 8, 120)
            if center is not None:
                cv2.circle(frame, center, 10, 225, -1)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (59, 109, 23, 23), 42)
        self.assertEqual(result['firstMovingFrameIndex'], 40)

    def test_tracked_centres_are_subpixel(self):
        buffer = RollingFrameBuffer(40)
        for i in range(40):
            frame = np.full((180, 320), 35, dtype=np.uint8)
            x = 70 if i < 10 else 70 + (i - 9) * 2.5
            cv2.circle(frame, (round(x * 16), 120 * 16), 10 * 16, 225, -1, lineType=cv2.LINE_AA, shift=4)
            buffer.append(frame, i / 242)
        result = analyze_departure(buffer, (59, 109, 23, 23), 30)
        moving = [p for p in result['track'] if p['frameIndex'] >= 10]
        self.assertTrue(any(abs(p['x'] - round(p['x'])) > .2 for p in moving))
        for point in moving:
            self.assertAlmostEqual(point['x'], 70 + (point['frameIndex'] - 9) * 2.5, delta=.25)

    def test_measurement_quality_warning_reaches_capture(self):
        measurements = {'metrics': {}, 'ballTrack3d': [], 'clubTrack3d': [],
                        'warnings': ['Ground AprilTag pose is a lower-confidence estimate.']}
        with patch('launch_measurements.measure_launch', return_value=measurements):
            result = analyze_departure(burst(), (31, 61, 19, 19), 8)
        self.assertIn(measurements['warnings'][0], result['warnings'])

    def test_false_removal_uses_sensor_coordinates(self):
        frame = np.full((800, 1280), 40, dtype=np.uint8)
        cv2.circle(frame, (800, 600), 30, 230, -1)
        bounds = scale_bounds((383, 283, 34, 34), (640, 400), (1280, 800))
        self.assertGreater(ball_template_similarity(frame, frame, bounds), 0.95)
        self.assertLess(ball_template_similarity(frame, np.full_like(frame, 40), bounds), 0.72)

    def test_short_contact_sheet_is_rectangular(self):
        for count in (1, 3, 5, 9):
            buffer = RollingFrameBuffer(count)
            for i in range(count):
                buffer.append(np.full((20, 32), i, dtype=np.uint8), i * 0.005)
            with TemporaryDirectory() as directory:
                buffer.save(Path(directory), 200)
                self.assertEqual(cv2.imread(str(Path(directory) / 'contact-sheet.jpg')).shape[:2], (300, 640))


class ArmedReferenceTests(unittest.TestCase):
    def test_slow_motion_keeps_reference_paired_with_arming_bounds(self):
        armed = np.full((120, 160, 3), 30, np.uint8)
        cv2.circle(armed, (40, 70), 10, (220, 220, 220), -1)
        shifted = np.full_like(armed, 30)
        cv2.circle(shifted, (55, 70), 10, (220, 220, 220), -1)
        empty = np.full_like(armed, 30)
        analyze, save = self._run_monitor([armed, shifted, empty], [
            DetectionObservation(True, True, .9, (29, 59, 23, 23)),
            DetectionObservation(True, False, .9, (44, 59, 23, 23)),
            DetectionObservation(False, True, .9, None),
        ])
        np.testing.assert_array_equal(analyze.call_args.kwargs['ball_reference'], armed)
        np.testing.assert_array_equal(save.call_args.kwargs['ball_reference'], armed)
        self.assertEqual(save.call_args.kwargs['ball_bounds'], (29, 59, 23, 23))

    def test_resting_ball_refreshes_reference_after_placing_hand_leaves(self):
        placing = np.full((120, 160, 3), 30, np.uint8)
        cv2.circle(placing, (40, 70), 10, (220, 220, 220), -1)
        cv2.rectangle(placing, (30, 55), (80, 66), (150, 150, 150), -1)
        resting = np.full_like(placing, 30)
        cv2.circle(resting, (40, 70), 10, (220, 220, 220), -1)
        empty = np.full_like(placing, 30)
        analyze, save = self._run_monitor([placing, resting, empty], [
            DetectionObservation(True, True, .9, (29, 59, 23, 23)),
            DetectionObservation(True, False, .9, (29, 59, 23, 23)),
            DetectionObservation(False, True, .9, None),
        ])
        np.testing.assert_array_equal(analyze.call_args.kwargs['ball_reference'], resting)
        np.testing.assert_array_equal(save.call_args.kwargs['ball_reference'], resting)

    def test_one_departure_saves_both_views_with_one_trigger(self):
        frames = [np.full((120, 160, 3), value, np.uint8) for value in (30, 40, 20)]
        analyze, save = self._run_monitor(frames, [
            DetectionObservation(True, True, .9, (29, 59, 23, 23)),
            DetectionObservation(True, False, .9, (29, 59, 23, 23)),
            DetectionObservation(False, True, .9, None),
        ], dual=True)
        save.assert_called_once()
        buffer = save.call_args.args[0]
        self.assertEqual(len(buffer.frames), len(buffer.secondary.frames))
        self.assertEqual(len(buffer.frames), 3)
        self.assertIn('secondaryImage', analyze.return_value)

    def _run_monitor(self, frames, observations, dual=False):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock
        from camera_source import DualCsiCapture

        stop = threading.Event()
        incoming = iter(frames)

        def read():
            frame = next(incoming, None)
            if frame is None:
                stop.set()
                return False, None
            if dual:
                camera.secondary_frame = 255 - frame
                camera.metadata = {'SensorTimestamp': 1_000_000_000 + read.count * 5_000_000}
                camera.secondary_metadata = {'SensorTimestamp': camera.metadata['SensorTimestamp'] + 20_000}
                read.count += 1
            return True, frame

        read.count = 0
        camera = Mock(spec=DualCsiCapture) if dual else Mock()
        camera.isOpened.return_value = True
        camera.read.side_effect = read
        camera.metadata = {}
        detector = Mock()
        detector.calibrated = True
        detector.config = SimpleNamespace(absent_frames=1, present_frames=1)
        detector.stable_bounds = (29, 59, 23, 23)
        detector.update.side_effect = observations
        detector.foreground_fraction.return_value = 0
        detector.preview_detection.return_value = {}
        detector._pixel_roi.return_value = (0, 0, 160, 120)
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
            'PINPOINT_CAMERA_SOURCE': 'usb', 'PINPOINT_AUTO_BALL_DETECTION': 'true',
            'PINPOINT_BALL_FRAME_STRIDE': '1', 'PINPOINT_DETECTOR_WIDTH': '160', 'PINPOINT_DETECTOR_HEIGHT': '120',
            'PINPOINT_CAMERA_DIAGNOSTICS_PATH': str(Path(directory) / 'diagnostics.json'),
        }):
            monitor = BallMonitor(None)
            with (
                patch.object(monitor, '_open_camera', return_value=camera),
                patch('ball_detector.BallPresenceDetector', return_value=detector),
                patch('ball_detector.record_camera_diagnostics'),
                patch.object(monitor, '_publish_preview'),
                patch.object(monitor, '_save_frame'),
                patch.object(monitor, '_capture_post_impact_frames'),
                patch.object(monitor, '_reserve_rolling_capture', return_value=(3, 'capture-1', 10)),
                patch.object(monitor, '_save_rolling_capture', side_effect=lambda *a, **k: self.order.append('save') or 3) as save,
                patch('ball_detector.ball_template_similarity', return_value=0),
                patch('ball_detector.analyze_departure', return_value={'impactFrameIndex': 1, 'imageFrameIndex': 1}) as analyze,
            ):
                self.order = []
                self.emit = Mock(side_effect=lambda event: self.order.append('emit' if event.analysis else 'presence'))
                monitor.run(stop, self.emit)
        return analyze, save

    def test_saved_capture_retains_lossless_reference(self):
        reference = np.arange(300, dtype=np.uint8).reshape(10, 10, 3)
        buffer = RollingFrameBuffer(3)
        buffer.append(np.zeros((10, 10), np.uint8), 0)
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'PINPOINT_ROLLING_CAPTURE_PATH': directory}):
            monitor = BallMonitor(None)
            count, capture_id, _ = monitor._reserve_rolling_capture(buffer)
            self.assertEqual(count, 1)
            self.assertEqual(monitor._save_rolling_capture(buffer, capture_id, 0, ball_reference=reference), 1)
            saved = cv2.imread(str(Path(directory) / capture_id / 'armed-ball-reference.png'))
            np.testing.assert_array_equal(saved, reference)

    def test_result_is_sent_before_frames_are_saved(self):
        frames = [np.full((120, 160, 3), value, np.uint8) for value in (30, 40, 20)]
        self._run_monitor(frames, [
            DetectionObservation(True, True, .9, (29, 59, 23, 23)),
            DetectionObservation(True, False, .9, (29, 59, 23, 23)),
            DetectionObservation(False, True, .9, None),
        ])
        self.assertEqual([step for step in self.order if step != 'presence'], ['emit', 'save'])
        result = next(call.args[0] for call in self.emit.call_args_list if call.args[0].analysis)
        self.assertEqual(result.capture_id, 'capture-1')
        self.assertEqual(result.rolling_capture_frames, 3)

    def test_replay_waits_for_a_capture_still_being_saved(self):
        import ball_detector
        buffer = RollingFrameBuffer(3)
        buffer.append(np.zeros((10, 10, 3), np.uint8), 0)
        buffer.append(np.zeros((10, 10, 3), np.uint8), .004)
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'PINPOINT_ROLLING_CAPTURE_PATH': directory}):
            monitor = BallMonitor(None)
            _, capture_id, _ = monitor._reserve_rolling_capture(buffer)
            saver = threading.Timer(.3, lambda: monitor._save_rolling_capture(buffer, capture_id, 0))
            saver.start()
            preview = ball_detector.capture_frame_preview(capture_id, 1)
            saver.join()
            self.assertEqual(preview['frameCount'], 2)


class CameraWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.capture_directory = TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'PINPOINT_CAPTURE_BACKEND': 'camera',
            'PINPOINT_AUTO_BALL_DETECTION': 'true',
            'PINPOINT_ROLLING_CAPTURE_PATH': self.capture_directory.name,
        })
        self.env.start()
        self.messages = []
        async def send(message):
            self.messages.append(message)
        self.protocol = PinpointProtocol(send)

    async def asyncTearDown(self):
        await self.protocol.close()
        self.env.stop()
        self.capture_directory.cleanup()

    async def test_ball_arm_departure_analysis_image_and_rearm(self):
        for _ in range(2):
            await self.protocol.ball_presence_changed(True)
            self.assertEqual(self.protocol.state, 'armed')
            await self.protocol.ball_presence_changed(False, analysis=analyze_departure(burst(True), (31, 61, 19, 19), 8))
            self.assertEqual(self.protocol.state, 'processing')
            await self.protocol._capture_task
            self.assertEqual(self.protocol.state, 'ready')
        captures = [m for m in self.messages if m['type'] == 'capture']
        self.assertEqual(len(captures), 2)
        self.assertTrue(captures[0]['data']['image']['base64'])
        self.assertFalse(any(m['type'] in ('shot', 'putt') for m in self.messages))

    async def test_missing_evidence_never_generates_synthetic_metrics(self):
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(False)
        self.assertEqual(self.protocol.state, 'ready')
        self.assertTrue(any(m['type'] == 'error' for m in self.messages))
        self.assertFalse(self.protocol.shots)

    async def test_complete_measurements_reach_existing_shot_contract(self):
        from launch_measurements import unavailable
        analysis = analyze_departure(burst(), (31, 61, 19, 19), 8)
        metrics = unavailable('test fixture')
        for key, value in {'ballSpeedMps': 40, 'clubSpeedMps': 30, 'smashFactor': 40/30,
                           'launchAngleDeg': 12, 'startDirectionDeg': 2, 'strikeXmm': 4, 'strikeYmm': 3}.items():
            metrics[key].update(value=value, status='estimated')
        analysis['measurements'] = {'metrics': metrics, 'clubId': 'driver',
                                    'shotEvidence': {'status': 'club-motion-observed', 'clubFrames': 3,
                                                     'reason': 'Test fixture club motion.'}}
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(False, analysis=analysis)
        await self.protocol._capture_task
        shot = next(message['data'] for message in self.messages if message['type'] == 'shot')
        self.assertEqual(shot['ballSpeedMps'], 40)
        self.assertEqual(shot['coarseDepartureFrameIndex'], 8)
        self.assertEqual(shot['lastStationaryFrameIndex'], 7)
        self.assertEqual(shot['measurementSource'], 'monocular-estimate')
        self.assertFalse(shot['simulated'])
        self.assertNotIn('spinRpm', shot)
        self.assertGreater(shot['estimatedCarryM'], 0)
        self.assertIn('assumed', self.protocol.captures[0]['measurements']['metrics']['estimatedCarryM']['reason'])

    async def test_mismatched_club_calibration_blocks_complete_shot(self):
        from launch_measurements import unavailable
        analysis = analyze_departure(burst(), (31, 61, 19, 19), 8)
        metrics = unavailable('fixture')
        for metric in metrics.values(): metric.update(value=1, status='estimated')
        analysis['measurements'] = {'metrics': metrics, 'clubId': '7-iron'}
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(False, analysis=analysis)
        await self.protocol._capture_task
        self.assertFalse(any(m['type'] == 'shot' for m in self.messages))
        self.assertIsNone(self.protocol.captures[0]['measurements']['metrics']['clubSpeedMps']['value'])

    async def test_tagless_club_speed_survives_selected_club_check(self):
        from launch_measurements import unavailable
        analysis = analyze_departure(burst(), (31, 61, 19, 19), 8)
        metrics = unavailable('fixture')
        for key, value in {'ballSpeedMps': 6.9369, 'clubSpeedMps': 4.776,
                           'smashFactor': 6.9369 / 4.776, 'launchAngleDeg': 27.9601,
                           'startDirectionDeg': 0.4079, 'attackAngleDeg': -8}.items():
            metrics[key].update(value=value, status='estimated')
        analysis['measurements'] = {
            'metrics': metrics,
            'diagnostics': {'clubSilhouette': {'acceptedFrames': 10, 'speedMps': 4.776}},
        }
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(False, analysis=analysis)
        await self.protocol._capture_task
        capture = next(message['data'] for message in self.messages if message['type'] == 'capture')
        kept = capture['measurements']['metrics']
        self.assertEqual(kept['clubSpeedMps']['value'], 4.776)
        self.assertEqual(kept['attackAngleDeg']['value'], -8)
        self.assertEqual(capture['measurements']['carryModel']['attackAngleDegUsed'], -8)
        self.assertEqual(capture['measurements']['shotEvidence']['status'], 'club-motion-observed')

    async def test_new_ball_during_transfer_is_armed_afterwards(self):
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(False, analysis=analyze_departure(burst(), (31, 61, 19, 19), 8))
        task = self.protocol._capture_task
        await self.protocol.ball_presence_changed(True)
        await task
        self.assertEqual(self.protocol.state, 'armed')

    async def test_send_failure_recovers_and_retains_capture(self):
        await self.protocol.ball_presence_changed(True)
        async def fail(message):
            if message['type'] == 'capture':
                raise OSError('disconnected')
        self.protocol.send_message = fail
        await self.protocol.ball_presence_changed(False, analysis=analyze_departure(burst(), (31, 61, 19, 19), 8))
        with self.assertLogs('pinpoint.protocol', level='ERROR'):
            await self.protocol._capture_task
        self.assertEqual(self.protocol.state, 'ready')
        self.assertEqual(len(self.protocol.captures), 1)


if __name__ == '__main__':
    unittest.main()
