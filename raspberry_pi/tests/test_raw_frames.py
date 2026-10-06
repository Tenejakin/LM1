import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ball_detector import BallMonitor
from camera_source import DualCsiCapture
from raw_frames import RawAnalysis, analysis_source, counts_per_level, raw_to_gray8

PICTURE = np.full((4, 6, 3), 77, np.uint8)
RAW = np.full((4, 6), 1024 + 64 * 40, np.uint16)   # 40 counts above the data floor


def light(mode):
    fake = MagicMock()
    fake.status.return_value = {"mode": mode}
    return fake


class RawToGrayTests(unittest.TestCase):
    def test_maps_counts_straight_to_grey_levels_and_clips(self):
        raw = np.array([[1024, 1024 + 640, 1024 + 64 * 300, 500]], np.uint16)   # floor, +10, +300, below the floor
        self.assertEqual(raw_to_gray8(raw).tolist(), [[0, 10, 255, 0]])

    def test_counts_per_level_scales_the_range(self):
        raw = np.array([[1024 + 64 * 100]], np.uint16)
        self.assertEqual(raw_to_gray8(raw, per_level=2.0).tolist(), [[50]])
        self.assertEqual(raw_to_gray8(raw, per_level=0.5).tolist(), [[200]])

    def test_a_faint_signal_the_picture_would_lose_survives(self):
        # +30 counts: the image processor subtracts 64 counts first, so its picture shows 0 here.
        raw = np.full((2, 2), 1024 + 64 * 30, np.uint16)
        self.assertTrue((raw_to_gray8(raw) == 30).all())

    def test_settings_come_from_the_environment_with_safe_fallbacks(self):
        with patch.dict(os.environ, {"PINPOINT_ANALYSIS_SOURCE": "RAW", "PINPOINT_RAW_COUNTS_PER_LEVEL": "2"}):
            self.assertEqual(analysis_source(), "raw")
            self.assertEqual(counts_per_level(), 2.0)
        with patch.dict(os.environ, {"PINPOINT_ANALYSIS_SOURCE": "nonsense", "PINPOINT_RAW_COUNTS_PER_LEVEL": "x"}):
            self.assertEqual(analysis_source(), "auto")
            self.assertEqual(counts_per_level(), 1.0)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(analysis_source(), "auto")


class RawAnalysisTests(unittest.TestCase):
    DARK = np.full((8, 8), 1024 + 64 * 40, np.uint16)      # 40 counts: a dark scene
    MIDDLE = np.full((8, 8), 1024 + 64 * 150, np.uint16)   # between the two limits
    BRIGHT = np.full((8, 8), 1024 + 64 * 500, np.uint16)   # would saturate at 1 count per level

    def feed(self, analysis, raw, frames):
        out = None
        for _ in range(frames):
            out = analysis.frame(PICTURE, {"RawFrame": raw})
        return out

    def test_auto_switches_to_raw_only_after_a_steady_dark_strobing_scene(self):
        analysis = RawAnalysis(light("strobe"), source="auto")
        self.assertIs(self.feed(analysis, self.DARK, 5), PICTURE)          # not steady yet
        self.assertFalse(analysis.consume_change())
        derived = self.feed(analysis, self.DARK, 10)
        self.assertEqual(derived.shape, (8, 8, 3))
        self.assertTrue((derived == 40).all())
        self.assertTrue(analysis.consume_change())
        self.assertFalse(analysis.consume_change())                         # reported once

    def test_auto_never_uses_raw_when_not_strobing_or_when_the_scene_is_bright(self):
        flat = RawAnalysis(light("flat"), source="auto")
        self.assertIs(self.feed(flat, self.DARK, 30), PICTURE)
        self.assertFalse(flat.consume_change())
        lit = RawAnalysis(light("strobe"), source="auto")
        self.assertIs(self.feed(lit, self.BRIGHT, 30), PICTURE)
        self.assertFalse(lit.consume_change())

    def test_hysteresis_keeps_raw_in_the_middle_band_and_leaves_at_once_when_it_brightens(self):
        analysis = RawAnalysis(light("strobe"), source="auto")
        self.feed(analysis, self.DARK, 15)
        analysis.consume_change()
        self.assertTrue((self.feed(analysis, self.MIDDLE, 20) == 150).all())   # still raw
        self.assertFalse(analysis.consume_change())
        self.assertIs(self.feed(analysis, self.BRIGHT, 1), PICTURE)           # saturating: back to the picture now
        self.assertTrue(analysis.consume_change())

    def test_a_middle_band_scene_does_not_start_raw(self):
        analysis = RawAnalysis(light("strobe"), source="auto")
        self.assertIs(self.feed(analysis, self.MIDDLE, 30), PICTURE)

    def test_leaving_strobe_returns_to_the_picture_immediately(self):
        fake = light("strobe")
        analysis = RawAnalysis(fake, source="auto")
        self.feed(analysis, self.DARK, 15)
        analysis.consume_change()
        fake.status.return_value = {"mode": "flat"}
        with patch("raw_frames.time.monotonic", return_value=time.monotonic() + 100.0):    # past the once-a-second refresh
            self.assertIs(self.feed(analysis, self.DARK, 1), PICTURE)
        self.assertTrue(analysis.consume_change())

    def test_only_the_primary_camera_decides_so_the_two_views_stay_alike(self):
        analysis = RawAnalysis(light("strobe"), source="auto")
        for _ in range(20):
            primary = analysis.frame(PICTURE, {"RawFrame": self.DARK})
            secondary = analysis.frame(PICTURE, {"RawFrame": self.BRIGHT}, follow=True)
        self.assertTrue((primary == 40).all())
        self.assertTrue((secondary == 255).all())     # converted the same way, never flipping the decision

    def test_isp_never_and_raw_always(self):
        self.assertIs(RawAnalysis(light("strobe"), source="isp").frame(PICTURE, {"RawFrame": RAW}), PICTURE)
        forced = RawAnalysis(light("flat"), source="raw")
        self.assertTrue((forced.frame(PICTURE, {"RawFrame": RAW}) == 40).all())
        self.assertFalse(forced.consume_change())

    def test_the_picture_is_kept_when_there_is_no_raw_frame(self):
        analysis = RawAnalysis(light("strobe"), source="raw")
        self.assertIs(analysis.frame(PICTURE, {}), PICTURE)
        self.assertIs(analysis.frame(PICTURE, None), PICTURE)

    def test_a_broken_light_link_is_treated_as_not_strobing(self):
        broken = MagicMock()
        broken.status.side_effect = RuntimeError("serial gone")
        self.assertIs(self.feed(RawAnalysis(broken, source="auto"), self.DARK, 30), PICTURE)
        self.assertIs(self.feed(RawAnalysis(None, source="auto"), self.DARK, 30), PICTURE)

    def test_the_light_state_is_only_re_read_once_a_second(self):
        fake = light("strobe")
        analysis = RawAnalysis(fake, source="auto")
        with patch("raw_frames.time.monotonic", side_effect=[10.0, 10.2, 10.5, 11.3]):
            for _ in range(4):
                analysis._is_strobing()
        self.assertEqual(fake.status.call_count, 2)


class DetectorHookTests(unittest.TestCase):
    def monitor(self, source):
        monitor = BallMonitor.__new__(BallMonitor)
        monitor.raw_analysis = RawAnalysis(light("strobe"), source=source)
        return monitor

    def test_a_single_camera_frame_is_converted_from_its_own_metadata(self):
        capture = MagicMock()
        capture.metadata = {"RawFrame": RAW}
        derived = self.monitor("raw")._analysis_frames(capture, PICTURE)
        self.assertTrue((derived == 40).all())

    def test_both_cameras_of_a_dual_capture_are_converted(self):
        capture = MagicMock(spec=DualCsiCapture)
        capture.metadata = {"RawFrame": RAW}
        capture.secondary_metadata = {"RawFrame": RAW + 64 * 10}
        capture.secondary_frame = PICTURE.copy()
        derived = self.monitor("raw")._analysis_frames(capture, PICTURE)
        self.assertTrue((derived == 40).all())
        self.assertTrue((capture.secondary_frame == 50).all())

    def test_nothing_changes_when_the_picture_is_wanted(self):
        capture = MagicMock(spec=DualCsiCapture)
        capture.metadata = {"RawFrame": RAW}
        capture.secondary_metadata = {"RawFrame": RAW}
        capture.secondary_frame = PICTURE.copy()
        picture = self.monitor("isp")._analysis_frames(capture, PICTURE)
        self.assertIs(picture, PICTURE)
        self.assertTrue((capture.secondary_frame == 77).all())

    def test_a_capture_without_metadata_is_left_alone(self):
        capture = object()
        self.assertIs(self.monitor("raw")._analysis_frames(capture, PICTURE), PICTURE)


if __name__ == "__main__":
    unittest.main()
