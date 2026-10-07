import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from light_controller import strobe_pattern
from strobe_copies import (
    analyse_frame, estimate_from_frames, estimate_with_report, fit_flash_pairs, fit_flash_track, find_copies,
    flash_times_us, metrics_from_fit, raw_to_counts, separation_speed_mps,
)

PERIOD_US = 4132
BALL_PX = 52.0
MM_PER_PX = 42.67 / BALL_PX


def synthetic_frame(speed_mps, angle_deg, gaps_us, *, start_flash=0, start_xy=(60.0, 300.0), pulse_boost=1.0,
                    noise=1.5, ambient=3.0, missing=(), extra_blobs=(), seed=1):
    """A dark frame with one bright disc per flash along a straight line at a known speed."""
    rng = np.random.default_rng(seed)
    image = np.full((400, 640), ambient, np.float32) + rng.normal(0, noise, (400, 640)).astype(np.float32)
    times = flash_times_us(gaps_us, PERIOD_US, start_flash + 12)[start_flash:]
    t0 = times[0]
    vx = math.cos(math.radians(angle_deg)) * speed_mps * 1000.0 / MM_PER_PX / 1e6  # px per us
    vy = -math.sin(math.radians(angle_deg)) * speed_mps * 1000.0 / MM_PER_PX / 1e6
    truth = []
    for index, t in enumerate(times):
        x, y = start_xy[0] + vx * (t - t0), start_xy[1] + vy * (t - t0)
        if x > 600 or y < 40:
            break
        if index in missing:
            continue
        truth.append((x, y))
        cv2.circle(image, (round(x), round(y)), int(BALL_PX / 2), 60.0 * pulse_boost, -1)
    for x, y, radius, level in extra_blobs:
        cv2.circle(image, (x, y), radius, level, -1)
    image = cv2.GaussianBlur(image, (0, 0), 1.2)
    return np.clip(image, 0, 255).astype(np.uint8), truth


class FindCopiesTests(unittest.TestCase):
    def test_finds_every_flash_as_a_separate_round_copy(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        image, truth = synthetic_frame(62.0, 15.0, gaps)
        copies = find_copies(image, BALL_PX)
        self.assertEqual(len(copies), len(truth))
        for found, (x, y) in zip(sorted(copies, key=lambda c: c["x"]), truth):
            self.assertAlmostEqual(found["x"], x, delta=2.0)
            self.assertAlmostEqual(found["y"], y, delta=2.0)

    def test_rejects_things_that_are_not_ball_sized_and_round(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        # A big club head and a thin shaft, both bright.
        image, truth = synthetic_frame(62.0, 15.0, gaps, extra_blobs=[(300, 90, 60, 80.0)])
        cv2.rectangle(image, (560, 20), (572, 110), 90, -1)
        self.assertEqual(len(find_copies(image, BALL_PX)), len(truth))

    def test_a_static_background_can_be_subtracted(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        image, truth = synthetic_frame(62.0, 15.0, gaps)
        background = np.full(image.shape, 70.0, np.float32)
        lit = np.clip(image.astype(np.float32) + background, 0, 255).astype(np.uint8)
        self.assertEqual(len(find_copies(lit, BALL_PX, background.astype(np.uint8))), len(truth))


class FitTests(unittest.TestCase):
    def check(self, speed, angle, gaps, **kwargs):
        image, truth = synthetic_frame(speed, angle, gaps, **kwargs)
        result = analyse_frame(image, gaps, PERIOD_US, BALL_PX, expected_speed_mps=speed * 0.95)
        fit = result["fit"]
        self.assertIsNotNone(fit, (speed, angle))
        return fit

    def test_recovers_driver_speed_and_angle(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        fit = self.check(62.0, 14.0, gaps)
        self.assertAlmostEqual(fit["ballSpeedMps"], 62.0, delta=62.0 * 0.03)
        self.assertAlmostEqual(fit["launchAngleDeg"], 14.0, delta=1.5)
        self.assertGreaterEqual(fit["copies"], 4)

    def test_recovers_each_club_family(self):
        for speed in (62.0, 55.0, 46.0, 42.0, 35.0):
            gaps = strobe_pattern(speed, PERIOD_US)["gapsUs"]
            if len(gaps) < 2:
                continue
            fit = self.check(speed, 20.0, gaps)
            self.assertAlmostEqual(fit["ballSpeedMps"], speed, delta=speed * 0.04, msg=f"{speed} m/s")

    def test_any_start_flash_in_the_burst_is_recognised(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        for start in range(len(gaps) + 1):
            fit = self.check(62.0, 10.0, gaps, start_flash=start, seed=start + 5)
            self.assertAlmostEqual(fit["ballSpeedMps"], 62.0, delta=62.0 * 0.04, msg=f"start {start}")

    def test_a_missing_middle_flash_does_not_break_the_fit_when_enough_copies_remain(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        image, truth = synthetic_frame(62.0, 12.0, gaps, start_flash=0, missing=(len(gaps),))
        self.assertGreaterEqual(len(truth), 3)
        result = analyse_frame(image, gaps, PERIOD_US, BALL_PX, expected_speed_mps=60.0)
        self.assertIsNotNone(result["fit"])

    def test_a_stationary_ball_gives_no_fit(self):
        copies = [{"x": 100.0 + dx, "y": 200.0 + dy} for dx, dy in ((0, 0), (1, 0), (2, 1), (1, 1))]
        self.assertIsNone(fit_flash_track(copies, [950, 1020, 1100], PERIOD_US, BALL_PX))

    def test_copies_that_are_not_in_a_row_give_no_fit(self):
        copies = [{"x": 100.0, "y": 100.0}, {"x": 160.0, "y": 300.0}, {"x": 220.0, "y": 100.0}, {"x": 280.0, "y": 300.0}]
        self.assertIsNone(fit_flash_track(copies, [950, 1020, 1100], PERIOD_US, BALL_PX))

    def test_a_steeply_downward_row_is_not_trusted(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        image, _ = synthetic_frame(62.0, -60.0, gaps, start_xy=(60.0, 40.0))
        fit = analyse_frame(image, gaps, PERIOD_US, BALL_PX, expected_speed_mps=60.0)["fit"]
        self.assertTrue(fit is None or not fit["reliable"])

    def test_three_copies_are_not_trusted_when_the_gaps_are_nearly_equal(self):
        # With gaps that grow only about 7 % each, three copies fit two different starting flashes
        # almost equally well, so the speed could be off by 4 % or more: better to report nothing.
        gaps = [950, 1020, 1100]
        times = flash_times_us(gaps, PERIOD_US, 3)
        px_per_us = 62.0 * 1000.0 / (42.67 / BALL_PX) / 1e6
        copies = [{"x": 100.0 + px_per_us * t, "y": 300.0 - 0.25 * px_per_us * t} for t in times]
        for expected in (60.0, 25.0, None):
            fit = fit_flash_track(copies, gaps, PERIOD_US, BALL_PX, expected_speed_mps=expected)
            self.assertFalse(fit["reliable"], expected)
        self.assertTrue(fit_flash_track(copies, gaps, PERIOD_US, BALL_PX, expected_speed_mps=60.0)["ambiguous"])

    def test_too_few_copies_give_no_fit(self):
        copies = [{"x": 100.0, "y": 200.0}, {"x": 160.0, "y": 200.0}]
        self.assertIsNone(fit_flash_track(copies, [950, 1020, 1100], PERIOD_US, BALL_PX))

    def test_a_right_pattern_fits_tightly_and_a_wrong_one_is_marked_unreliable(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        image, _ = synthetic_frame(62.0, 14.0, gaps)
        right = analyse_frame(image, gaps, PERIOD_US, BALL_PX)["fit"]
        self.assertTrue(right["reliable"])
        self.assertLess(right["fitResidualMm"], 1.0)
        for factor in (0.8, 1.25, 1.5):
            wrong = analyse_frame(image, [gap * factor for gap in gaps], PERIOD_US, BALL_PX)["fit"]
            self.assertTrue(wrong is None or not wrong["reliable"], factor)
            self.assertGreater(wrong["fitResidualMm"], 5.0)

    def test_noise_does_not_break_the_fit(self):
        gaps = strobe_pattern(62.0, PERIOD_US)["gapsUs"]
        for seed in range(6):
            image, _ = synthetic_frame(62.0, 14.0, gaps, noise=4.0, seed=seed)
            fit = analyse_frame(image, gaps, PERIOD_US, BALL_PX, expected_speed_mps=60.0)["fit"]
            self.assertIsNotNone(fit, seed)
            self.assertTrue(fit["reliable"], seed)
            self.assertAlmostEqual(fit["ballSpeedMps"], 62.0, delta=62.0 * 0.04, msg=f"seed {seed}")


class WholeCaptureTests(unittest.TestCase):
    LIGHT = {"mode": "strobe", "rateHz": 242,
             "pattern": {"pulseUs": 19, "gapsUs": [950, 1020, 1100], "ballSpeedMps": 62.0}}

    def frames(self, gaps, speed=62.0, moving_from=10, total=30):
        """Ball resting, then flying; the last frames are empty."""
        frames = []
        for index in range(total):
            t = index * 0.004131
            if index < moving_from:
                image = np.full((400, 640), 3.0, np.float32)
                cv2.circle(image, (200, 300), int(BALL_PX / 2), 60.0, -1)   # stacked copies on one spot
                image = np.clip(cv2.GaussianBlur(image, (0, 0), 1.2), 0, 255).astype(np.uint8)
            elif index < moving_from + 3:
                image, _ = synthetic_frame(speed, 15.0, gaps, start_xy=(200.0 + 40 * (index - moving_from), 300.0),
                                           seed=index)
            else:
                image = np.full((400, 640), 3.0, np.uint8)
            frames.append((t, image))
        return frames

    def test_finds_the_flight_after_the_ball_leaves_and_ignores_the_resting_ball(self):
        gaps = self.LIGHT["pattern"]["gapsUs"]
        found = estimate_from_frames(self.frames(gaps), (174, 274, 52, 52), 9, self.LIGHT)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(found["frameIndex"], 10)
        self.assertAlmostEqual(found["fit"]["ballSpeedMps"], 62.0, delta=62.0 * 0.04)
        self.assertTrue(found["fit"]["reliable"])

    def test_gives_nothing_unless_the_ring_was_strobing_with_a_known_pattern(self):
        gaps = self.LIGHT["pattern"]["gapsUs"]
        frames = self.frames(gaps)
        self.assertIsNone(estimate_from_frames(frames, (174, 274, 52, 52), 9, None))
        self.assertIsNone(estimate_from_frames(frames, (174, 274, 52, 52), 9, {**self.LIGHT, "mode": "flat"}))
        self.assertIsNone(estimate_from_frames(frames, (174, 274, 52, 52), 9, {**self.LIGHT, "pattern": None}))
        self.assertIsNone(estimate_from_frames(
            frames, (174, 274, 52, 52), 9, {**self.LIGHT, "pattern": {"gapsUs": [], "ballSpeedMps": 30.0}}))

    def test_gives_nothing_when_no_frame_holds_a_reliable_row(self):
        gaps = self.LIGHT["pattern"]["gapsUs"]
        rng = np.random.default_rng(3)
        frames = [(i * 0.004131, np.clip(rng.normal(3, 2, (400, 640)), 0, 255).astype(np.uint8)) for i in range(30)]
        self.assertIsNone(estimate_from_frames(frames, (174, 274, 52, 52), 9, self.LIGHT))

    def test_metrics_are_marked_as_estimates(self):
        fit = {"ballSpeedMps": 61.9, "launchAngleDeg": 14.2, "copies": 6}
        metrics = metrics_from_fit(fit)
        self.assertEqual(metrics["ballSpeedMps"]["status"], "estimated")
        self.assertEqual(metrics["ballSpeedMps"]["value"], 61.9)
        self.assertEqual(metrics["launchAngleDeg"]["unit"], "deg")
        self.assertIn("6 flash copies", metrics["ballSpeedMps"]["reason"])


class PairFitTests(unittest.TestCase):
    """A slow ball's pattern has one gap, so a frame holds two flash copies and the fit runs across frames."""
    GAP = 1970
    LIGHT = {"mode": "strobe", "rateHz": 242, "pattern": {"pulseUs": 40, "gapsUs": [GAP], "ballSpeedMps": 29.8}}
    BOUNDS = (174, 274, 52, 52)
    FRAME_S = 0.004131

    def flash_frames(self, speed, angle=12.0, first_frame=10, count=5, cross_burst=False, start_x=100.0, total=30,
                     noise_seed=1):
        """Frames at 242 fps: resting ball, then `count` frames with two flash copies each, then empty."""
        mm_per_px = 42.67 / BALL_PX
        vx = math.cos(math.radians(angle)) * speed * 1000.0 / mm_per_px / 1e6
        vy = -math.sin(math.radians(angle)) * speed * 1000.0 / mm_per_px / 1e6
        frames = []
        for index in range(total):
            rng = np.random.default_rng(noise_seed + index)
            image = np.full((400, 640), 3.0, np.float32) + rng.normal(0, 1.5, (400, 640)).astype(np.float32)
            k = index - first_frame
            if index < first_frame:
                cv2.circle(image, (start_x.__int__(), 300), int(BALL_PX / 2), 60.0, -1)
            elif k < count:
                period = 1_000_000 // 242
                if cross_burst:
                    times = (self.GAP + k * period, (k + 1) * period)
                else:
                    times = (k * period, k * period + self.GAP)
                for t in times:
                    x, y = start_x + vx * t, 300.0 + vy * t
                    if 20 < x < 620 and 40 < y < 380:
                        cv2.circle(image, (round(x), round(y)), int(BALL_PX / 2), 60.0, -1)
            image = np.clip(cv2.GaussianBlur(image, (0, 0), 1.2), 0, 255).astype(np.uint8)
            frames.append((index * self.FRAME_S, image))
        return frames

    def test_recovers_a_wedge_speed_and_angle_from_two_copies_per_frame(self):
        found, report = estimate_with_report(self.flash_frames(30.0), self.BOUNDS, 9, self.LIGHT)
        self.assertIsNotNone(found, report)
        fit = found["fit"]
        self.assertEqual(fit["method"], "pairs")
        self.assertAlmostEqual(fit["ballSpeedMps"], 30.0, delta=30.0 * 0.05)
        self.assertAlmostEqual(fit["launchAngleDeg"], 12.0, delta=2.0)
        self.assertEqual(fit["pairTiming"], "burst")
        self.assertGreaterEqual(fit["frames"], 3)
        self.assertEqual(report["pairFrames"], fit["frames"])

    def test_the_other_pairing_of_flashes_is_recognised_and_gives_the_same_speed(self):
        found, report = estimate_with_report(self.flash_frames(30.0, cross_burst=True), self.BOUNDS, 9, self.LIGHT)
        self.assertIsNotNone(found, report)
        self.assertEqual(found["fit"]["pairTiming"], "cross-burst")
        self.assertAlmostEqual(found["fit"]["ballSpeedMps"], 30.0, delta=30.0 * 0.05)

    def test_speeds_across_the_wedge_to_short_iron_range(self):
        for speed in (24.0, 30.0, 36.0):
            with self.subTest(speed=speed):
                light = {**self.LIGHT, "pattern": {**self.LIGHT["pattern"], "ballSpeedMps": speed}}
                found, report = estimate_with_report(self.flash_frames(speed, count=4), self.BOUNDS, 9, light)
                self.assertIsNotNone(found, report)
                self.assertAlmostEqual(found["fit"]["ballSpeedMps"], speed, delta=speed * 0.06)

    def test_a_speed_far_from_the_clubs_expected_range_is_not_trusted(self):
        light = {**self.LIGHT, "pattern": {**self.LIGHT["pattern"], "ballSpeedMps": 70.0}}
        found, report = estimate_with_report(self.flash_frames(30.0), self.BOUNDS, 9, light)
        self.assertIsNone(found)
        self.assertEqual(report["reason"], "no-fit")

    def test_one_pair_frame_is_not_enough(self):
        found, report = estimate_with_report(self.flash_frames(30.0, count=1), self.BOUNDS, 9, self.LIGHT)
        self.assertIsNone(found)
        self.assertEqual(report["reason"], "too-few-pairs")
        self.assertEqual(report["pairFrames"], 1)

    def test_a_ball_that_barely_moves_gives_no_fit(self):
        found, report = estimate_with_report(self.flash_frames(1.0), self.BOUNDS, 9, self.LIGHT)
        self.assertIsNone(found)
        self.assertIn(report["reason"], ("too-few-copies", "too-few-pairs", "no-fit"))

    def test_frames_with_one_or_three_copies_are_ignored_not_guessed(self):
        frames = self.flash_frames(30.0)
        stray = frames[12][1].copy()
        cv2.circle(stray, (500, 100), 26, 60, -1)
        frames[12] = (frames[12][0], stray)
        found, report = estimate_with_report(frames, self.BOUNDS, 9, self.LIGHT)
        self.assertLess(report["pairFrames"], 5)

    def test_dropped_frames_keep_their_place_in_the_timing(self):
        frames = self.flash_frames(30.0, count=6)
        frames = [f for i, f in enumerate(frames) if i != 12]   # a lost frame between pair frames
        found, report = estimate_with_report(frames, self.BOUNDS, 9, self.LIGHT)
        self.assertIsNotNone(found, report)
        self.assertAlmostEqual(found["fit"]["ballSpeedMps"], 30.0, delta=30.0 * 0.06)

    def test_the_metrics_say_which_frames_the_estimate_came_from(self):
        found, _ = estimate_with_report(self.flash_frames(30.0), self.BOUNDS, 9, self.LIGHT)
        reason = metrics_from_fit(found["fit"])["ballSpeedMps"]["reason"]
        self.assertIn("two per frame", reason)
        self.assertIn("frames", reason)


class ReportTests(unittest.TestCase):
    LIGHT = WholeCaptureTests.LIGHT
    BOUNDS = (174, 274, 52, 52)

    def frames(self, **kwargs):
        return WholeCaptureTests().frames(self.LIGHT["pattern"]["gapsUs"], **kwargs)

    def test_a_good_shot_reports_the_copies_it_found(self):
        found, report = estimate_with_report(self.frames(), self.BOUNDS, 9, self.LIGHT)
        self.assertIsNotNone(found)
        self.assertIsNone(report["reason"])
        self.assertEqual(report["lightMode"], "strobe")
        self.assertGreaterEqual(report["bestCopies"], 4)
        self.assertGreater(report["framesSearched"], 0)

    def test_the_wrapper_returns_the_same_fit(self):
        frames = self.frames()
        self.assertEqual(estimate_from_frames(frames, self.BOUNDS, 9, self.LIGHT),
                         estimate_with_report(frames, self.BOUNDS, 9, self.LIGHT)[0])

    def test_names_why_the_ring_was_not_used(self):
        frames = self.frames()
        self.assertEqual(estimate_with_report(frames, self.BOUNDS, 9, None)[1]["reason"], "no-controller")
        report = estimate_with_report(frames, self.BOUNDS, 9, {**self.LIGHT, "mode": "flat"})[1]
        self.assertEqual((report["reason"], report["lightMode"]), ("not-strobing", "flat"))
        self.assertEqual(estimate_with_report(frames, self.BOUNDS, 9, {**self.LIGHT, "pattern": None})[1]["reason"], "no-pattern")
        short = {**self.LIGHT, "pattern": {"gapsUs": [], "ballSpeedMps": 30.0}}
        self.assertEqual(estimate_with_report(frames, self.BOUNDS, 9, short)[1]["reason"], "pattern-too-short")

    def test_an_empty_dark_scene_reports_no_copies(self):
        rng = np.random.default_rng(3)
        frames = [(i * 0.004131, np.clip(rng.normal(3, 2, (400, 640)), 0, 255).astype(np.uint8)) for i in range(30)]
        found, report = estimate_with_report(frames, self.BOUNDS, 9, self.LIGHT)
        self.assertIsNone(found)
        self.assertEqual(report["reason"], "no-copies")
        self.assertEqual(report["maxCopies"], 0)

    def test_a_slow_ball_reports_merged_copies_and_the_speed_that_would_separate_them(self):
        # 1 m/s: the copies land a few mm apart, so they merge into one ball-sized blob.
        frames = self.frames(speed=1.0)
        found, report = estimate_with_report(frames, self.BOUNDS, 9, self.LIGHT)
        self.assertIsNone(found)
        self.assertEqual(report["reason"], "too-few-copies")
        self.assertLess(report["maxCopySpanBalls"], 0.8)
        self.assertEqual(report["separatesAboveMps"], separation_speed_mps(self.LIGHT["pattern"]["gapsUs"]))

    def test_separation_speed_is_one_ball_width_over_the_shortest_gap(self):
        self.assertAlmostEqual(separation_speed_mps([950, 1020, 1100]), 44.9, delta=0.1)
        self.assertIsNone(separation_speed_mps([]))


class RawFrameTests(unittest.TestCase):
    """Raw 10-bit frames keep copies that the processor's 8-bit curve turns to black."""
    LIGHT = WholeCaptureTests.LIGHT
    BLACK = 1024

    def make(self, copy_counts=30.0):
        """Frames as raw words and as the processor's 8-bit picture of the same scene."""
        gaps = self.LIGHT["pattern"]["gapsUs"]
        raws, eights, frames = {}, {}, []
        for index in range(30):
            counts = np.full((400, 640), 6.0, np.float32)            # a little ambient
            if 10 <= index < 13:
                scene, _ = synthetic_frame(62.0, 15.0, gaps, start_xy=(200.0 + 40 * (index - 10), 300.0), seed=index,
                                           noise=0.0, ambient=0.0)
                counts += (scene.astype(np.float32) / 60.0) * copy_counts   # copies are `copy_counts` bright
            rng = np.random.default_rng(index)
            counts += rng.normal(0, 3.0, counts.shape).astype(np.float32)   # 10-bit read noise
            raw = np.clip((counts + 16.0) * 64.0, 0, 65535).astype(np.uint16)   # data floor ~16 counts
            # The processor subtracts 64 counts (4096 words) before its gamma curve, so a signal under that is exactly 0.
            eight = np.clip((counts - 48.0) / 4.0, 0, 255).astype(np.uint8)
            raws[index] = raw
            frames.append((index * 0.004131, eight))
        return frames, raws

    def test_raw_counts_are_linear_and_black_subtracted(self):
        raw = np.array([[1024, 1024 + 640, 1024 + 6400]], np.uint16)
        self.assertEqual(raw_to_counts(raw, 1024).tolist(), [[0.0, 10.0, 100.0]])

    def test_raw_finds_copies_that_are_invisible_in_the_8_bit_picture(self):
        frames, raws = self.make(copy_counts=30.0)
        bounds = (174, 274, 52, 52)
        self.assertGreater(float(frames[11][1].max()), -1)   # sanity: the 8-bit frame exists
        self.assertIsNone(estimate_from_frames(frames, bounds, 9, self.LIGHT))
        found = estimate_from_frames(frames, bounds, 9, self.LIGHT, raw_frames=raws, raw_black=16 * 64)
        self.assertIsNotNone(found)
        self.assertEqual(found["source"], "raw")
        self.assertAlmostEqual(found["fit"]["ballSpeedMps"], 62.0, delta=62.0 * 0.05)

    def test_falls_back_to_the_8_bit_frames_when_the_raw_tail_is_missing(self):
        frames, raws = self.make(copy_counts=400.0)   # bright copies: the 8-bit picture shows them too
        partial = {i: r for i, r in raws.items() if i < 20}   # no raw for the last frames
        found = estimate_from_frames(frames, (174, 274, 52, 52), 9, self.LIGHT, raw_frames=partial, raw_black=16 * 64)
        self.assertIsNotNone(found)
        self.assertEqual(found["source"], "8bit")


class FlashTimesTests(unittest.TestCase):
    def test_bursts_repeat_every_period(self):
        times = flash_times_us([950, 1020, 1100], PERIOD_US, 8)
        self.assertEqual(times[:4], [0.0, 950.0, 1970.0, 3070.0])
        self.assertEqual(times[4], PERIOD_US)
        self.assertEqual(times[5], PERIOD_US + 950.0)


if __name__ == "__main__":
    unittest.main()
