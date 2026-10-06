import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import cv2
    import numpy as np
except ModuleNotFoundError:
    cv2 = None
    np = None

from ball_detector import (  # noqa: E402
    DEFAULT_DEPARTURE_TIMEOUT_SECONDS,
    DEFAULT_POST_IMPACT_FRAMES,
    DEFAULT_PRE_IMPACT_FRAMES,
    DEFAULT_PREVIEW_MAX_BYTES,
    BackgroundJob,
    BallMonitor,
    BallPresenceDetector,
    DetectionConfig,
    RollingFrameBuffer,
    ball_template_similarity,
    capture_contact_sheet,
    capture_frame_preview,
    capture_retention,
    encode_ble_preview,
    parse_roi,
)


@unittest.skipIf(cv2 is None or np is None, "OpenCV is installed on the Raspberry Pi")
class BallPresenceDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = DetectionConfig(
            roi=(0.1, 0.1, 0.9, 0.9),
            calibration_frames=3,
            present_frames=3,
            absent_frames=3,
            difference_threshold=20,
            min_area=80,
            max_area=3000,
            min_circularity=0.38,
            max_scene_change=0.18,
        )
        self.detector = BallPresenceDetector(self.config)
        self.empty = np.full((240, 320, 3), 70, dtype=np.uint8)

    def test_ball_placement_and_removal_are_debounced(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)

        ball = self.empty.copy()
        cv2.circle(ball, (160, 150), 16, (235, 235, 235), -1)
        observations = [self.detector.update(ball) for _ in range(3)]
        self.assertFalse(observations[0].present)
        self.assertTrue(observations[-1].present)
        self.assertTrue(observations[-1].changed)

        observations = [self.detector.update(self.empty) for _ in range(3)]
        self.assertTrue(observations[0].present)
        self.assertFalse(observations[-1].present)
        self.assertTrue(observations[-1].changed)

    def test_large_scene_change_does_not_report_ball_removed(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        ball = self.empty.copy()
        cv2.circle(ball, (160, 150), 16, (235, 235, 235), -1)
        for _ in range(3):
            self.detector.update(ball)

        covered = np.full_like(self.empty, 240)
        observations = [self.detector.update(covered) for _ in range(4)]
        self.assertTrue(all(observation.present for observation in observations))

    def test_preview_keeps_confirmed_box_during_removal_debounce(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        ball = self.empty.copy()
        cv2.circle(ball, (160, 150), 16, (235, 235, 235), -1)
        for _ in range(3):
            observation = self.detector.update(ball)
        confirmed = self.detector.preview_detection(observation, 320, 240)
        missed = self.detector.preview_detection(self.detector.update(self.empty), 320, 240)
        self.assertEqual(missed["state"], "detected")
        self.assertEqual(missed["bounds"], confirmed["bounds"])

    def test_preview_reports_calibration_waiting_detected_and_removal(self) -> None:
        first = self.detector.update(self.empty)
        self.assertEqual(self.detector.preview_detection(first, 320, 240)["state"], "calibrating")
        for _ in range(3):
            observation = self.detector.update(self.empty)
        self.assertEqual(self.detector.preview_detection(observation, 320, 240)["state"], "waiting")
        ball = self.empty.copy()
        cv2.circle(ball, (160, 150), 16, (235, 235, 235), -1)
        first = self.detector.update(ball)
        self.assertIsNone(self.detector.preview_detection(first, 320, 240)["bounds"])
        for _ in range(3):
            observation = self.detector.update(ball)
        preview = self.detector.preview_detection(observation, 320, 240)
        self.assertEqual(preview["state"], "detected")
        x, y, width, height = preview["bounds"]
        self.assertAlmostEqual(x + width / 2, 0.5, delta=0.01)
        self.assertAlmostEqual(y + height / 2, 150 / 240, delta=0.01)
        for _ in range(3):
            observation = self.detector.update(self.empty)
        self.assertEqual(self.detector.preview_detection(observation, 320, 240), {"state": "waiting", "bounds": None})

    def test_ball_outside_roi_does_not_arm(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        frame = self.empty.copy()
        cv2.circle(frame, (12, 150), 10, (235, 235, 235), -1)
        for _ in range(5):
            self.assertFalse(self.detector.update(frame).present)

    def test_large_scene_change_does_not_arm_a_round_candidate(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        frame = self.empty.copy()
        cv2.rectangle(frame, (40, 35), (155, 170), (235, 235, 235), -1)
        cv2.circle(frame, (230, 150), 16, (235, 235, 235), -1)
        for _ in range(5):
            self.assertFalse(self.detector.update(frame).present)

    def test_candidates_moving_between_locations_do_not_arm(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        left_ball = self.empty.copy()
        right_ball = self.empty.copy()
        cv2.circle(left_ball, (100, 150), 16, (235, 235, 235), -1)
        cv2.circle(right_ball, (220, 150), 16, (235, 235, 235), -1)

        observations = []
        for frame in (left_ball, right_ball, left_ball, right_ball, left_ball, right_ball):
            observations.append(self.detector.update(frame))

        self.assertTrue(all(not observation.present for observation in observations))

    def test_candidate_clipped_by_roi_edge_does_not_arm(self) -> None:
        for _ in range(3):
            self.detector.update(self.empty)
        frame = self.empty.copy()
        # ROI right edge is x=288; this otherwise ball-like contour is clipped.
        cv2.circle(frame, (288, 150), 16, (235, 235, 235), -1)
        for _ in range(5):
            self.assertFalse(self.detector.update(frame).present)

    def test_template_confirms_stationary_ball_and_rejects_empty_area(self) -> None:
        ball = self.empty.copy()
        cv2.circle(ball, (160, 150), 16, (235, 235, 235), -1)
        bounds = (143, 133, 35, 35)
        self.assertGreater(ball_template_similarity(ball, ball.copy(), bounds), 0.95)
        self.assertLess(ball_template_similarity(ball, self.empty, bounds), 0.72)

    def test_ble_preview_is_small_decodable_four_by_three_jpeg(self) -> None:
        preview = encode_ble_preview(self.empty)
        decoded = cv2.imdecode(np.frombuffer(preview, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)

        self.assertLessEqual(len(preview), DEFAULT_PREVIEW_MAX_BYTES)
        self.assertEqual(decoded.shape, (120, 160))

    def test_csi_preview_keeps_sensor_aspect_ratio_and_payload_bound(self) -> None:
        frame = np.random.default_rng(42).integers(0, 256, (800, 1280, 3), dtype=np.uint8)
        with patch.dict(os.environ, {"PINPOINT_CAMERA_SOURCE": "csi"}, clear=True):
            preview = encode_ble_preview(frame)
        decoded = cv2.imdecode(np.frombuffer(preview, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertLessEqual(len(preview), DEFAULT_PREVIEW_MAX_BYTES)
        self.assertAlmostEqual(decoded.shape[1] / decoded.shape[0], 1.6)

    def test_ble_preview_accepts_grayscale_rolling_frame(self) -> None:
        preview = encode_ble_preview(cv2.cvtColor(self.empty, cv2.COLOR_BGR2GRAY))
        decoded = cv2.imdecode(np.frombuffer(preview, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(decoded.shape, (120, 160))


class BallDetectorConfigurationTests(unittest.TestCase):
    def test_default_roi_is_the_left_half_hitting_area(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(DetectionConfig.from_environment().roi, (0.0, 0.30, 0.50, 0.98))

    @unittest.skipIf(cv2 is None or np is None, "OpenCV is installed on the Raspberry Pi")
    def test_default_zone_arms_left_but_not_centre_or_right(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = DetectionConfig.from_environment()
        empty = np.full((400, 640, 3), 70, dtype=np.uint8)
        for x, should_arm in ((160, True), (320, False), (420, False)):
            with self.subTest(x=x):
                detector = BallPresenceDetector(config)
                for _ in range(config.calibration_frames):
                    detector.update(empty)
                frame = empty.copy()
                cv2.circle(frame, (x, 210), 20, (235, 235, 235), -1)
                observations = [detector.update(frame) for _ in range(config.present_frames + 2)]
                self.assertEqual(observations[-1].present, should_arm)

    def test_roi_validation(self) -> None:
        self.assertEqual(parse_roi("0.1,0.2,0.8,0.9"), (0.1, 0.2, 0.8, 0.9))
        with self.assertRaises(ValueError):
            parse_roi("0.8,0.2,0.1,0.9")


@unittest.skipIf(cv2 is None or np is None, "OpenCV is installed on the Raspberry Pi")
class RollingFrameBufferTests(unittest.TestCase):
    def test_keeps_only_latest_frames_and_writes_manifest(self) -> None:
        buffer = RollingFrameBuffer(max_frames=3)
        for value in range(5):
            buffer.append(np.full((12, 16, 3), value, dtype=np.uint8), captured_at=value * 0.02)
        self.assertEqual(len(buffer.frames), 3)
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "capture"
            self.assertEqual(buffer.save(destination, fps=50), 3)
            self.assertEqual(len(list(destination.glob("frame-*.jpg"))), 3)
            manifest = json.loads((destination / "capture.json").read_text())
            self.assertEqual(manifest["captureId"], "capture")
            self.assertEqual(manifest["durationMs"], 40)
            self.assertEqual(manifest["measuredFps"], 50)
            self.assertEqual(manifest["frameTimesMs"], [0, 20, 40])

    def test_manifest_records_contact_window_and_coarse_trigger(self) -> None:
        buffer = RollingFrameBuffer(max_frames=20)
        for value in range(20):
            buffer.append(np.full((12, 16, 3), value, dtype=np.uint8))
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "capture"
            buffer.save(
                destination,
                fps=200,
                impact_frame_index=8,
                coarse_departure_frame_index=15,
                last_stationary_frame_index=7,
                first_moving_frame_index=8,
                ball_bounds=(31, 61, 19, 19),
            )
            manifest = json.loads((destination / "capture.json").read_text())
            self.assertEqual(manifest["impactFrameIndex"], 8)
            self.assertEqual(manifest["coarseDepartureFrameIndex"], 15)
            self.assertEqual(manifest["lastStationaryFrameIndex"], 7)
            self.assertEqual(manifest["firstMovingFrameIndex"], 8)
            self.assertEqual(manifest["ballBounds"], [31, 61, 19, 19])
            self.assertEqual(manifest["frameCount"], 20)

    def test_specific_capture_frame_can_be_replayed(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            capture = Path(directory) / "capture-123"
            buffer = RollingFrameBuffer(max_frames=3)
            for value in range(3):
                buffer.append(np.full((40, 64, 3), value * 60, dtype=np.uint8), captured_at=value * 0.005)
            buffer.save(
                capture,
                fps=200,
                impact_frame_index=1,
                coarse_departure_frame_index=2,
                last_stationary_frame_index=0,
                first_moving_frame_index=1,
            )
            with patch.dict(os.environ, {"PINPOINT_ROLLING_CAPTURE_PATH": directory}):
                preview = capture_frame_preview("capture-123", 1)
            self.assertEqual(preview["frameIndex"], 1)
            self.assertEqual(preview["frameCount"], 3)
            self.assertEqual(preview["impactFrameIndex"], 1)
            self.assertEqual(preview["coarseDepartureFrameIndex"], 2)
            self.assertEqual(preview["lastStationaryFrameIndex"], 0)
            self.assertEqual(preview["firstMovingFrameIndex"], 1)
            self.assertTrue(preview["base64"])

    @staticmethod
    def _raw_metadata(index: int, value: int) -> dict:
        return {"SensorTimestamp": 1_000_000_000 + index * 4_131_000, "ExposureTime": 100, "FrameDuration": 4131,
                "AnalogueGain": 1.0, "SensorBlackLevels": (4096, 4096, 4096, 4096),
                "RawFrame": np.full((12, 16), value, dtype=np.uint16)}

    def test_raw_frames_are_kept_in_a_short_ring_and_never_leak_into_the_manifest_metadata(self) -> None:
        with patch("ball_detector.RAW_RING_FRAMES", 4):
            buffer = RollingFrameBuffer(max_frames=10)
            for index in range(8):
                buffer.append(np.full((12, 16), index, dtype=np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        self.assertEqual(len(buffer.frames), 8)
        self.assertEqual(len(buffer.raw), 4)
        self.assertEqual(buffer.raw_black, 1024)
        self.assertEqual(sorted(buffer.raw_by_index()), [4, 5, 6, 7])
        self.assertTrue(all("RawFrame" not in entry for entry in buffer.metadata))

    def test_trimming_the_buffer_also_trims_the_raw_frames(self) -> None:
        buffer = RollingFrameBuffer(max_frames=10)
        for index in range(8):
            buffer.append(np.full((12, 16), index, dtype=np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        buffer.trim_after(5)
        self.assertEqual(len(buffer.frames), 6)
        self.assertEqual(sorted(buffer.raw_by_index()), [0, 1, 2, 3, 4, 5])

    def test_raw_frames_near_the_impact_are_saved_as_16_bit_pngs_with_a_manifest_entry(self) -> None:
        from tempfile import TemporaryDirectory
        with patch("ball_detector.RAW_SAVE_BEFORE", 1), patch("ball_detector.RAW_SAVE_AFTER", 2):
            buffer = RollingFrameBuffer(max_frames=10)
            for index in range(8):
                buffer.append(np.full((12, 16), index, dtype=np.uint8), metadata=self._raw_metadata(index, 1000 + index * 100))
            with TemporaryDirectory() as directory:
                destination = Path(directory) / "capture"
                buffer.save(destination, fps=242, impact_frame_index=4)
                names = sorted(path.name for path in destination.glob("raw-*.png"))
                self.assertEqual(names, ["raw-0003.png", "raw-0004.png", "raw-0005.png", "raw-0006.png"])
                saved = cv2.imread(str(destination / "raw-0004.png"), cv2.IMREAD_UNCHANGED)
                self.assertEqual(saved.dtype, np.uint16)
                self.assertTrue((saved == 1400).all())
                manifest = json.loads((destination / "capture.json").read_text())
                self.assertEqual(manifest["raw"]["frames"], [3, 4, 5, 6])
                self.assertEqual(manifest["raw"]["blackLevel"], 1024)
                self.assertEqual(manifest["raw"]["scale"], 64)
                self.assertEqual(len(list(destination.glob("frame-*.jpg"))), 8)

    def test_a_plain_ring_loses_the_frames_before_the_impact_and_pinning_keeps_them(self) -> None:
        # Reproduces the captures of 2026-10-01: the buffer reached 250 frames, the hit was at 141 and was only
        # confirmed ~100 frames later, by which time a "last 100 frames" ring had dropped everything before 150.
        plain = RollingFrameBuffer(max_frames=325)
        pinned = RollingFrameBuffer(max_frames=325)
        for index in range(250):
            for buffer in (plain, pinned):
                buffer.append(np.full((12, 16), 0, dtype=np.uint8), metadata=self._raw_metadata(index, 1000 + index))
            if index == 143:                      # the ball first looks gone, two frames after the hit
                pinned.pin_raw()
        self.assertEqual(min(plain.raw_by_index()), 150)          # the old behaviour: the impact is gone
        kept = pinned.raw_by_index()
        self.assertLessEqual(min(kept), 141 - 25)                 # covers 25 frames before the hit
        self.assertGreaterEqual(max(kept), 141 + 45)              # and 45 after it
        self.assertLessEqual(len(pinned.raw), 160)                # memory stays bounded
        pinned.trim_after(205)                                    # the service trims to impact + 64 before saving
        self.assertLessEqual(min(pinned.raw_by_index()), 141 - 25)
        self.assertGreaterEqual(max(pinned.raw_by_index()), 141 + 45)

    def test_pinning_stops_adding_raw_frames_after_the_window_and_covers_the_second_camera(self) -> None:
        buffer = RollingFrameBuffer(max_frames=325)
        for index in range(60):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index),
                          secondary_frame=np.zeros((12, 16), np.uint8), secondary_metadata=self._raw_metadata(index, 2000 + index))
        buffer.pin_raw(10)
        for index in range(60, 200):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index),
                          secondary_frame=np.zeros((12, 16), np.uint8), secondary_metadata=self._raw_metadata(index, 2000 + index))
        for cam in (buffer, buffer.secondary):
            kept = sorted(cam.raw_by_index())
            self.assertLessEqual(kept[0], 49)                      # at least the 10 frames before the pin point (frame 59)
            self.assertEqual(kept[-1], 59 + 60)                    # then 60 more (RAW_AFTER_PIN), then it stops
        self.assertEqual(len(buffer.raw), len(buffer.secondary.raw))

    def test_a_false_alarm_unpins_and_the_ring_rolls_again(self) -> None:
        buffer = RollingFrameBuffer(max_frames=325)
        for index in range(30):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        buffer.pin_raw(5)
        for index in range(30, 80):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        buffer.unpin_raw()
        for index in range(80, 400):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        kept = sorted(buffer.raw_by_index())
        self.assertEqual(len(kept), 100)                           # a plain rolling window again
        self.assertEqual(kept[-1], 324)
        buffer = RollingFrameBuffer(max_frames=325)
        for index in range(30):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        buffer.pin_raw(5)
        buffer.unpin_raw()
        for index in range(30, 300):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        self.assertEqual(len(buffer.raw), 100)                     # back to the plain 100-frame window
        self.assertEqual(min(buffer.raw_by_index()), 200)

    def test_clearing_the_buffer_also_clears_the_pin(self) -> None:
        buffer = RollingFrameBuffer(max_frames=325)
        for index in range(40):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index, 1000 + index))
        buffer.pin_raw()
        buffer.clear()
        for index in range(200):
            buffer.append(np.zeros((12, 16), np.uint8), metadata=self._raw_metadata(index + 40, 1000 + index))
        self.assertEqual(len(buffer.raw), 100)

    def test_no_raw_entry_when_the_camera_supplies_no_raw_frames(self) -> None:
        from tempfile import TemporaryDirectory
        buffer = RollingFrameBuffer(max_frames=3)
        for index in range(3):
            buffer.append(np.full((12, 16), index, dtype=np.uint8), captured_at=index * 0.02)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "capture"
            buffer.save(destination, fps=50)
            self.assertNotIn("raw", json.loads((destination / "capture.json").read_text()))
            self.assertEqual(list(destination.glob("raw-*.png")), [])

    def test_capture_replay_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            capture_frame_preview("../capture-123", 0)

    def test_specific_capture_contact_sheet_is_returned(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            buffer = RollingFrameBuffer(max_frames=3)
            for value in range(3):
                buffer.append(np.full((40, 64, 3), value * 60, dtype=np.uint8), captured_at=value * 0.005)
            buffer.save(Path(directory) / "capture-123", fps=200, impact_frame_index=1)
            with patch.dict(os.environ, {"PINPOINT_ROLLING_CAPTURE_PATH": directory}):
                sheet = capture_contact_sheet("capture-123")
                with self.assertRaises(ValueError):
                    capture_contact_sheet("capture-999")
            self.assertEqual(sheet["captureId"], "capture-123")
            self.assertEqual(sheet["mimeType"], "image/jpeg")
            self.assertTrue(sheet["base64"])
        with self.assertRaises(ValueError):
            capture_contact_sheet("../capture-123")

    def test_keeps_newest_one_hundred_capture_directories_by_default(self) -> None:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"PINPOINT_ROLLING_CAPTURE_PATH": directory},
            clear=False,
        ):
            os.environ.pop("PINPOINT_CAPTURE_RETENTION", None)
            root = Path(directory)
            for index in range(105):
                capture = root / f"capture-{index:03d}"
                capture.mkdir()
                os.utime(capture, (index + 1, index + 1))
            monitor = BallMonitor(None)
            monitor._keep_recent_rolling_captures()
            retained = sorted(path.name for path in root.iterdir())
            self.assertEqual(len(retained), 100)
            self.assertEqual(retained[0], "capture-005")
            self.assertEqual(capture_retention(), 100)

    def test_default_burst_is_short_but_keeps_departure_and_background(self) -> None:
        fps, stride, absent_frames = 200, 20, 5
        debounce = (absent_frames + 1) * stride
        total = DEFAULT_PRE_IMPACT_FRAMES + debounce + DEFAULT_POST_IMPACT_FRAMES
        self.assertLessEqual(total / fps, 1.5)
        # A forced (timed-out) removal fires this long after the departure.
        departure_from_end = round(DEFAULT_DEPARTURE_TIMEOUT_SECONDS * fps) + DEFAULT_POST_IMPACT_FRAMES
        self.assertGreaterEqual(total - departure_from_end, 60)


class BackgroundJobTests(unittest.TestCase):
    def test_runs_off_thread_and_refuses_work_while_busy(self) -> None:
        import threading
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        calls = []

        def job(value):
            calls.append((value, threading.current_thread().name))
            started.set()
            release.wait(2)
            done.set()

        worker = BackgroundJob(job, "test-job")
        try:
            self.assertTrue(worker.submit(1))
            self.assertTrue(started.wait(2))
            self.assertFalse(worker.submit(2))
            release.set()
            self.assertTrue(done.wait(2))
            for _ in range(200):
                if worker.submit(3):
                    break
                threading.Event().wait(0.005)
            else:
                self.fail("worker never became free")
        finally:
            release.set()
            worker.stop()
        self.assertEqual(calls[0], (1, "test-job"))
        self.assertNotIn(2, [value for value, _ in calls])
        self.assertFalse(worker.submit(4))

    def test_job_errors_do_not_kill_the_worker(self) -> None:
        import threading
        done = threading.Event()
        attempts = []

        def job(value):
            attempts.append(value)
            if value == "bad":
                raise RuntimeError("boom")
            done.set()

        worker = BackgroundJob(job, "test-job")
        try:
            with self.assertLogs("pinpoint.ball_detector", level="ERROR"):
                self.assertTrue(worker.submit("bad"))
                for _ in range(200):
                    if worker.submit("good"):
                        break
                    threading.Event().wait(0.005)
                self.assertTrue(done.wait(2))
        finally:
            worker.stop()
        self.assertEqual(attempts, ["bad", "good"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(cv2 is None, "OpenCV is required")
class CaptureClipTests(unittest.TestCase):
    def test_clip_crops_every_frame_the_same_and_stays_small(self):
        import base64
        from ball_detector import CLIP_MAX_BYTES, capture_clip
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"PINPOINT_ROLLING_CAPTURE_PATH": directory}):
            capture = Path(directory) / "capture-123"
            capture.mkdir()
            rng = np.random.default_rng(1)
            for index in range(12):
                frame = rng.integers(0, 40, (400, 640), dtype=np.uint8)
                cv2.circle(frame, (150 + 10 * index, 250), 22, 230, -1)
                cv2.imwrite(str(capture / f"frame-{index:04d}.jpg"), frame)
            (capture / "capture.json").write_text(json.dumps(
                {"frameCount": 12, "ballBounds": [128, 228, 44, 44], "impactFrameIndex": 6, "firstMovingFrameIndex": 6}))
            clip = capture_clip("capture-123", 4, 8)
            self.assertEqual([frame["frameIndex"] for frame in clip["frames"]], list(range(4, 12)))
            self.assertEqual(clip["firstMovingFrameIndex"], 6)
            x, y, w, h = clip["cropBox"]
            self.assertLessEqual(x, 150 - 5 * 22)  # room behind the ball for the club
            self.assertGreaterEqual(x + w, 150 + 8 * 22)  # and ahead for the flight
            for frame in clip["frames"]:
                self.assertLessEqual(len(base64.b64decode(frame["base64"])), CLIP_MAX_BYTES)
            with self.assertRaises(ValueError):
                capture_clip("capture-123", 0, 9)
            with self.assertRaises(ValueError):
                capture_clip("../etc", 0, 1)
