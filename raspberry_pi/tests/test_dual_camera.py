"""Dual acquisition and paired evidence regression tests (service 0.30.0)."""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from camera_source import DualCsiCapture, camera_diagnostics, clear_camera_diagnostics
from ball_detector import RollingFrameBuffer, capture_frame_preview
from pinpoint_protocol import build_preview_event


class DualCameraTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('camera_source.threading.Thread')
        patcher.start()
        self.addCleanup(patcher.stop)

    def enqueue(self, pair, index, timestamps):
        for timestamp in timestamps:
            pair._queues[index].append((np.full((4,4,3), index+1, dtype=np.uint8),
                                       {'SensorTimestamp': timestamp, 'FrameDuration': 5000, 'SyncReady': True}))

    def tearDown(self):
        clear_camera_diagnostics()

    def fake_camera(self, index, timestamps):
        camera = MagicMock()
        camera.index = index
        camera.model = 'ov9281'
        camera.exposure_us = 75
        camera.gain = 4.0
        camera.metadata = {}
        frames = iter(timestamps)
        def read(*args):
            camera.metadata = {'SensorTimestamp': next(frames), 'FrameDuration': 5000, 'SyncReady': True}
            return True, np.full((4, 4, 3), index + 1, dtype=np.uint8)
        camera.finish_read.side_effect = read
        camera.read.side_effect = read
        return camera

    def open_pair(self, first, second):
        controls = SimpleNamespace(rpi=SimpleNamespace(SyncModeEnum=SimpleNamespace(Server=1, Client=2)))
        return patch.dict(sys.modules, {'libcamera': SimpleNamespace(controls=controls)}), patch('camera_source.CsiCapture', side_effect=[first, second])

    def test_dropped_frame_advances_older_stream_and_preserves_pair(self):
        first = self.fake_camera(0, [1_000_000_000, 1_005_000_000])
        second = self.fake_camera(1, [1_005_021_000])
        modules, factory = self.open_pair(first, second)
        with modules, factory, patch.dict(os.environ, {'PINPOINT_CAMERA_FPS': '200'}):
            pair = DualCsiCapture()
            try:
                self.enqueue(pair, 0, [1_000_000_000, 1_005_000_000])
                self.enqueue(pair, 1, [1_005_021_000])
                ok, frame = pair.read()
                self.assertTrue(ok)
                self.assertEqual(pair.metadata['SensorTimestamp'], 1_005_000_000)
                self.assertEqual(pair.secondary_metadata['SensorTimestamp'], 1_005_021_000)
                self.assertEqual(camera_diagnostics()['syncOffsetUs'], 21)
                self.assertEqual(int(frame[0, 0, 0]), 1)
                self.assertEqual(int(pair.secondary_frame[0, 0, 0]), 2)
                self.assertFalse(pair._queues[0])
            finally:
                pair.release()
        first.release.assert_called_once()
        second.release.assert_called_once()

    def test_second_open_failure_releases_first_camera(self):
        first = self.fake_camera(0, [])
        modules, _ = self.open_pair(first, None)
        with modules, patch('camera_source.CsiCapture', side_effect=[first, RuntimeError('unavailable')]):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                DualCsiCapture()
        first.release.assert_called_once()

    def test_both_controls_change_and_rollback_on_second_failure(self):
        first, second = self.fake_camera(0, []), self.fake_camera(1, [])
        modules, factory = self.open_pair(first, second)
        with modules, factory:
            pair = DualCsiCapture()
            try:
                pair.set_gain(6)
                first.set_gain.assert_called_with(6)
                second.set_gain.assert_called_with(6)
                second.set_exposure.side_effect = [RuntimeError('failed'), None]
                with self.assertRaisesRegex(RuntimeError, 'failed'):
                    pair.set_exposure(100)
                first.set_exposure.assert_called_with(75)
                self.assertEqual(pair.exposure_us, 75)
            finally:
                pair.release()

    def test_missing_timestamp_fails_instead_of_returning_false_pair(self):
        first, second = self.fake_camera(0, [0]), self.fake_camera(1, [1_000_000_000])
        modules, factory = self.open_pair(first, second)
        with modules, factory:
            pair = DualCsiCapture()
            try:
                pair._collect(0)
                with self.assertRaisesRegex(RuntimeError, 'timestamps'):
                    pair.read()
            finally:
                pair.release()

    def test_lock_timeout_fails_instead_of_returning_false_pair(self):
        first = self.fake_camera(0, [1_000_000_000])
        second = self.fake_camera(1, [1_002_000_000])
        modules, factory = self.open_pair(first, second)
        with modules, factory:
            pair = DualCsiCapture()
            try:
                with patch('camera_source.time.monotonic', side_effect=[0, 6]):
                    with self.assertRaisesRegex(RuntimeError, 'timing'):
                        pair.read()
            finally:
                pair.release()

    def test_bounded_burst_save_replay_and_clear_keep_both_views_aligned(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'PINPOINT_ROLLING_CAPTURE_PATH': folder}):
            buffer = RollingFrameBuffer(3)
            for i in range(5):
                buffer.append(np.full((40, 64), i * 10, dtype=np.uint8),
                              metadata={'SensorTimestamp': 1_000_000_000 + i * 5_000_000},
                              secondary_frame=np.full((40, 64), 100 + i * 10, dtype=np.uint8),
                              secondary_metadata={'SensorTimestamp': 1_000_020_000 + i * 5_000_000})
            path = Path(folder) / 'capture-123'
            self.assertEqual(buffer.save(path, 200, 1), 3)
            manifest = json.loads((path / 'capture.json').read_text())
            self.assertEqual(manifest['dualCamera']['pairOffsetsUs'], [20, 20, 20])
            self.assertEqual(len(list((path / 'camera-secondary').glob('frame-*.jpg'))), 3)
            upper_manifest = json.loads((path / 'camera-secondary' / 'capture.json').read_text())
            self.assertEqual(upper_manifest['captureId'], manifest['captureId'])
            replay = capture_frame_preview('capture-123', 1)
            self.assertEqual(replay['pairOffsetUs'], 20)
            self.assertIn('secondaryBase64', replay)
            self.assertNotEqual(replay['base64'], replay['secondaryBase64'])
            buffer.clear()
            self.assertEqual(len(buffer.secondary.frames), 0)
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                buffer.append(np.zeros((40, 64), dtype=np.uint8))

    def test_optional_preview_remains_compatible_with_single_camera(self):
        self.assertNotIn('secondaryBase64', build_preview_event(b'lower')['data'])
        self.assertEqual(build_preview_event(b'lower', b'upper')['data']['secondaryBase64'], 'dXBwZXI=')

    def test_intermittent_sync_metadata_retains_last_explicit_state(self):
        first, second = self.fake_camera(0, []), self.fake_camera(1, [])
        modules, factory = self.open_pair(first, second)
        with modules, factory:
            pair = DualCsiCapture()
            states = iter([{'SyncReady': True}, {}, {'SyncReady': False}])
            def read():
                state = next(states)
                second.metadata = {'SensorTimestamp': 1_000_000_000, **state}
                if state.get('SyncReady') is False:
                    pair._stop.set()
                return True, np.zeros((4, 4, 3), np.uint8)
            second.read.side_effect = read
            try:
                pair._collect(1)
                self.assertEqual([m['SyncReady'] for _, m in pair._queues[1]], [True, True, False])
                self.assertIsNone(pair._error)
            finally:
                pair.release()


if __name__ == '__main__':
    unittest.main()
