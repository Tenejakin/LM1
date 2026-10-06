"""Staggered capture: lock, pairing, drift states and the idle-only re-lock (no hardware)."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import camera_source
from camera_source import DualCsiCapture, camera_diagnostics, clear_camera_diagnostics, stagger_distance, stagger_state

PERIOD_NS = 4_132_000
HALF_NS = PERIOD_NS // 2


class PhaseHelperTests(unittest.TestCase):
    def test_distance_from_half_a_frame_wraps(self):
        self.assertAlmostEqual(stagger_distance(0.5), 0.0)
        self.assertAlmostEqual(stagger_distance(0.0), 0.5)
        self.assertAlmostEqual(stagger_distance(1.0), 0.5)
        self.assertAlmostEqual(stagger_distance(0.7), 0.2)
        self.assertAlmostEqual(stagger_distance(0.3), 0.2)

    def test_states_follow_the_median_so_one_late_frame_is_ignored(self):
        self.assertEqual(stagger_state([0.5] * 12), "locked")
        self.assertEqual(stagger_state([0.68] * 12), "locked")
        self.assertEqual(stagger_state([0.75] * 12), "drift-soon")
        self.assertEqual(stagger_state([0.22] * 12), "drift-soon")
        self.assertEqual(stagger_state([0.9] * 12), "drifted")
        self.assertEqual(stagger_state([0.5] * 11 + [0.99]), "locked")
        self.assertEqual(stagger_state([]), "locking")


class StaggeredPairTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('camera_source.threading.Thread')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(clear_camera_diagnostics)

    def fake_camera(self, index):
        camera = MagicMock()
        camera.index = index
        camera.model = 'ov9281'
        camera.exposure_us = 75
        camera.gain = 4.0
        camera.metadata = {}
        return camera

    def open_pair(self, lock_phase=0.5):
        first, second = self.fake_camera(0), self.fake_camera(1)
        controls = SimpleNamespace(rpi=SimpleNamespace(SyncModeEnum=SimpleNamespace(Server=1, Client=2)))

        def fake_open(pair, primary, secondary):
            pair.cameras.extend([first, second])
            pair.stagger_state = 'locked'
            pair._phases.append(lock_phase)

        env = patch.dict(os.environ, {'PINPOINT_CAMERA_STAGGER': '1', 'PINPOINT_CAMERA_FPS': '242'})
        modules = patch.dict(sys.modules, {'libcamera': SimpleNamespace(controls=controls)})
        return env, modules, patch.object(DualCsiCapture, '_open_staggered', fake_open), first, second

    def enqueue(self, pair, a_stamps, b_stamps):
        for index, stamps in ((0, a_stamps), (1, b_stamps)):
            for stamp in stamps:
                pair._queues[index].append((np.full((4, 4, 3), index + 1, np.uint8),
                                            {'SensorTimestamp': stamp, 'FrameDuration': 4132, 'SyncReady': False}))

    def test_each_a_frame_pairs_with_the_b_frame_half_a_frame_later(self):
        env, modules, opener, *_ = self.open_pair()
        with env, modules, opener:
            pair = DualCsiCapture()
            try:
                self.assertTrue(pair.stagger)
                a = [1_000_000_000 + k * PERIOD_NS for k in range(4)]
                b = [stamp + HALF_NS for stamp in a]
                self.enqueue(pair, a, b)
                for k in range(4):
                    ok, frame = pair.read()
                    self.assertTrue(ok)
                    self.assertEqual(pair.metadata['SensorTimestamp'], a[k])
                    self.assertEqual(pair.secondary_metadata['SensorTimestamp'], b[k])
                    self.assertEqual(int(pair.secondary_frame[0, 0, 0]), 2)
                diagnostics = camera_diagnostics()
                self.assertEqual(diagnostics['syncMode'], 'stagger')
                self.assertEqual(diagnostics['staggerState'], 'locked')
                self.assertAlmostEqual(diagnostics['staggerPhase'], 0.5, places=2)
                self.assertAlmostEqual(diagnostics['syncOffsetUs'], HALF_NS / 1000, delta=1)
                self.assertTrue(diagnostics['syncReady'])
                self.assertTrue(pair.pairing_ok)
            finally:
                pair.release()

    def test_an_early_b_frame_is_dropped_and_a_late_one_costs_the_a_frame(self):
        env, modules, opener, *_ = self.open_pair()
        with env, modules, opener:
            pair = DualCsiCapture()
            try:
                a = [1_000_000_000 + k * PERIOD_NS for k in range(3)]
                # B's first frame precedes A's first frame (it belongs to the frame before): dropped.
                b = [a[0] - HALF_NS] + [stamp + HALF_NS for stamp in a]
                self.enqueue(pair, a, b)
                ok, _ = pair.read()
                self.assertEqual(pair.metadata['SensorTimestamp'], a[0])
                self.assertEqual(pair.secondary_metadata['SensorTimestamp'], a[0] + HALF_NS)
            finally:
                pair.release()

    def test_phase_drift_moves_through_soon_then_drifted_and_blocks_pairing(self):
        env, modules, opener, *_ = self.open_pair()
        with env, modules, opener:
            pair = DualCsiCapture()
            try:
                pair.idle = False  # a ball is on the mat: never restart the camera now
                base = 2_000_000_000
                offsets = [0.5] * 12 + [0.25] * 14 + [0.15] * 14
                states = []
                for k, fraction in enumerate(offsets):
                    a = base + k * PERIOD_NS
                    self.enqueue(pair, [a], [a + int(fraction * PERIOD_NS)])  # the queues hold only 16 frames
                    pair.read()
                    states.append(pair.stagger_state)
                self.assertEqual(states[11], 'locked')
                self.assertIn('drift-soon', states)
                self.assertEqual(states[-1], 'drifted')
                self.assertFalse(pair.pairing_ok)
                self.assertFalse(camera_diagnostics()['syncReady'])
            finally:
                pair.release()

    def test_the_second_camera_is_restarted_only_when_nothing_is_on_the_mat(self):
        env, modules, opener, *_ = self.open_pair()
        with env, modules, opener:
            pair = DualCsiCapture()
            try:
                pair._phases.extend([0.75] * 12)  # the state is recomputed from recent phases on every pair
                pair.stagger_state = 'drift-soon'
                a = [1_000_000_000 + k * PERIOD_NS for k in range(2)]
                self.enqueue(pair, a, [stamp + HALF_NS for stamp in a])
                with patch.object(pair, 'resync') as resync:
                    pair.idle = False
                    pair.read()
                    resync.assert_not_called()
                    pair.idle = True
                    pair.read()
                    resync.assert_called_once()
            finally:
                pair.release()

    def test_a_failed_relock_is_retried_after_thirty_seconds_when_idle(self):
        env, modules, opener, *_ = self.open_pair()
        with env, modules, opener:
            pair = DualCsiCapture()
            try:
                pair.stagger_state = 'failed'
                pair._failed_at = 100.0
                a = [1_000_000_000 + k * PERIOD_NS for k in range(2)]
                self.enqueue(pair, a, [stamp + HALF_NS for stamp in a])
                with patch.object(pair, 'resync') as resync, patch('camera_source.time.monotonic', return_value=110.0):
                    pair.read()
                    resync.assert_not_called()
                with patch.object(pair, 'resync') as resync, patch('camera_source.time.monotonic', return_value=135.0):
                    self.enqueue(pair, [a[-1] + PERIOD_NS], [a[-1] + PERIOD_NS + HALF_NS])
                    pair.read()
                    resync.assert_called_once()
            finally:
                pair.release()

    def test_lock_keeps_restarting_the_second_camera_until_the_phase_is_near_half(self):
        env, modules, opener, first, second = self.open_pair()
        del opener
        with env, modules, patch('camera_source.CsiCapture', side_effect=lambda index, **kwargs: first if index == 0 else second),                 patch.object(DualCsiCapture, '_open_staggered', side_effect=RuntimeError('unused')):
            pair = DualCsiCapture()  # builds an in-step pair via the fallback so we can exercise the lock loop
            try:
                pair.cameras[1].camera = MagicMock()
                phases = iter([None, 0.05, 0.9, 0.62])
                with patch.object(pair, '_measure_b_phase', side_effect=lambda *a, **k: next(phases)), \
                        patch('camera_source.time.sleep'):
                    attempts = pair._lock_second_camera(drain_a=True)
                self.assertEqual(attempts, 4)
                self.assertEqual(pair.cameras[1].camera.start.call_count, 4)
                self.assertEqual(pair.cameras[1].camera.stop.call_count, 3)
                self.assertAlmostEqual(pair._phases[-1], 0.62)
                with patch.object(pair, '_measure_b_phase', return_value=0.0), patch('camera_source.time.sleep'):
                    with self.assertRaisesRegex(RuntimeError, 'did not settle'):
                        pair._lock_second_camera(drain_a=True, attempt_limit=3)
            finally:
                pair.release()

    def test_a_lock_failure_falls_back_to_an_in_step_pair_and_says_so(self):
        first, second = self.fake_camera(0), self.fake_camera(1)
        controls = SimpleNamespace(rpi=SimpleNamespace(SyncModeEnum=SimpleNamespace(Server=1, Client=2)))
        opened = []

        def fail(pair, primary, secondary):
            pair.cameras.append(self.fake_camera(9))
            raise RuntimeError('the cameras did not settle')

        def factory(index, **kwargs):
            opened.append(kwargs.get('sync_mode'))
            return first if index == 0 else second

        with patch.dict(os.environ, {'PINPOINT_CAMERA_STAGGER': '1', 'PINPOINT_CAMERA_FPS': '242'}), \
                patch.dict(sys.modules, {'libcamera': SimpleNamespace(controls=controls)}), \
                patch.object(DualCsiCapture, '_open_staggered', fail), patch('camera_source.CsiCapture', side_effect=factory):
            pair = DualCsiCapture()
            try:
                self.assertFalse(pair.stagger)
                self.assertEqual(pair.stagger_state, 'failed')
                self.assertIn('did not settle', pair.stagger_error)
                self.assertEqual(opened, [1, 2])  # in-step server and client
                self.assertTrue(pair.pairing_ok)
            finally:
                pair.release()


if __name__ == '__main__':
    unittest.main()
