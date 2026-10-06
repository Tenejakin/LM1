import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exposure_calibration import (
    MAX_CLIPPED_FRACTION,
    MAX_ACCEPTABLE_MEAN,
    MIN_ACCEPTABLE_MEAN,
    TARGET_MEAN,
    FrameStats,
    Sample,
    calibrate_exposure,
    choose_sample,
    measure_frame,
    plan_exposures,
    suggest_gain,
)

LIMITS = {
    "min_us": 20,
    "max_us": 250,
    "step_us": 10,
    "min_gain": 1.0,
    "max_gain": 16.0,
    "gain_step": 0.25,
}


def frame_of(value: float, shape=(8, 8)) -> np.ndarray:
    return np.full(shape, value, dtype=np.uint8)


class MeasureFrameTests(unittest.TestCase):
    def test_reports_mean_of_a_flat_frame(self):
        stats = measure_frame(frame_of(120))
        self.assertAlmostEqual(stats.mean, 120.0)
        self.assertEqual(stats.clipped_fraction, 0.0)

    def test_counts_blown_out_pixels(self):
        frame = frame_of(10, shape=(10, 10))
        frame[0, :] = 255
        stats = measure_frame(frame)
        self.assertAlmostEqual(stats.clipped_fraction, 0.1)

    def test_averages_colour_channels(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        frame[..., 0] = 30
        frame[..., 1] = 60
        frame[..., 2] = 90
        self.assertAlmostEqual(measure_frame(frame).mean, 60.0)

    def test_rejects_an_empty_frame(self):
        with self.assertRaises(ValueError):
            measure_frame(np.zeros((0, 0), dtype=np.uint8))


class PlanExposuresTests(unittest.TestCase):
    def test_covers_the_whole_range_on_step_boundaries(self):
        plan = plan_exposures(20, 250, 10, steps=7)
        self.assertEqual(plan[0], 20)
        self.assertEqual(plan[-1], 250)
        self.assertTrue(all(value % 10 == 0 for value in plan))
        self.assertEqual(plan, sorted(set(plan)))

    def test_refuses_an_inverted_range(self):
        with self.assertRaises(ValueError):
            plan_exposures(250, 20, 10)


class ChooseSampleTests(unittest.TestCase):
    def test_prefers_the_shortest_usable_exposure(self):
        samples = [
            Sample(20, 1.0, FrameStats(mean=30, clipped_fraction=0.0)),
            Sample(80, 1.0, FrameStats(mean=95, clipped_fraction=0.0)),
            Sample(160, 1.0, FrameStats(mean=TARGET_MEAN, clipped_fraction=0.0)),
        ]
        # 160 sits exactly on target, but 80 is usable and freezes motion better.
        self.assertEqual(choose_sample(samples).exposure_us, 80)

    def test_ignores_a_bright_but_clipped_frame(self):
        samples = [
            Sample(40, 1.0, FrameStats(mean=110, clipped_fraction=MAX_CLIPPED_FRACTION * 5)),
            Sample(90, 1.0, FrameStats(mean=100, clipped_fraction=0.0)),
        ]
        self.assertEqual(choose_sample(samples).exposure_us, 90)

    def test_falls_back_to_the_closest_frame_when_none_are_usable(self):
        samples = [
            Sample(20, 1.0, FrameStats(mean=10, clipped_fraction=0.0)),
            Sample(250, 1.0, FrameStats(mean=60, clipped_fraction=0.0)),
        ]
        self.assertEqual(choose_sample(samples).exposure_us, 250)

    def test_requires_at_least_one_sample(self):
        with self.assertRaises(ValueError):
            choose_sample([])


class SuggestGainTests(unittest.TestCase):
    def test_scales_gain_towards_the_target(self):
        gain = suggest_gain(FrameStats(mean=50, clipped_fraction=0.0), 1.0, 1.0, 16.0, 0.25)
        self.assertAlmostEqual(gain, 2.0, places=1)

    def test_never_exceeds_the_sensor_limit(self):
        gain = suggest_gain(FrameStats(mean=1, clipped_fraction=0.0), 1.0, 1.0, 16.0, 0.25)
        self.assertEqual(gain, 16.0)

    def test_handles_a_black_frame(self):
        self.assertEqual(suggest_gain(FrameStats(mean=0, clipped_fraction=0.0), 1.0, 1.0, 16.0, 0.25), 16.0)


class CalibrateExposureTests(unittest.TestCase):
    def _camera(self, brightness_per_us, *, ceiling=255):
        """A fake sensor whose frame brightness scales with exposure and gain."""
        state = {"exposure_us": 0, "gain": 1.0}
        applied = []

        def apply_settings(exposure_us, gain):
            state["exposure_us"] = exposure_us
            state["gain"] = gain
            applied.append((exposure_us, gain))

        def grab_frame():
            value = state["exposure_us"] * brightness_per_us * state["gain"]
            return frame_of(min(ceiling, value))

        return apply_settings, grab_frame, state, applied

    def test_settles_on_a_short_well_exposed_shutter(self):
        apply_settings, grab_frame, state, _ = self._camera(1.4)
        result = calibrate_exposure(apply_settings, grab_frame, **LIMITS)
        self.assertTrue(result.usable)
        self.assertEqual(result.gain, 1.0)
        self.assertLessEqual(result.exposure_us, 100)
        self.assertEqual(state["exposure_us"], result.exposure_us)

    def test_raises_gain_only_when_the_room_is_dim(self):
        apply_settings, grab_frame, state, _ = self._camera(0.06)
        result = calibrate_exposure(apply_settings, grab_frame, **LIMITS)
        self.assertGreater(result.gain, 1.0)
        self.assertEqual(state["gain"], result.gain)
        self.assertIn("dim", result.note)

    def test_reports_when_even_the_darkest_setting_is_blown_out(self):
        apply_settings, grab_frame, _, _ = self._camera(40)
        result = calibrate_exposure(apply_settings, grab_frame, **LIMITS)
        self.assertFalse(result.usable)
        self.assertEqual(result.exposure_us, LIMITS["min_us"])

    def test_leaves_the_camera_on_the_chosen_pair(self):
        apply_settings, grab_frame, state, applied = self._camera(1.4)
        result = calibrate_exposure(apply_settings, grab_frame, **LIMITS)
        self.assertEqual(applied[-1], (result.exposure_us, result.gain))
        self.assertEqual((state["exposure_us"], state["gain"]), applied[-1])

    def test_discards_frames_still_carrying_the_previous_settings(self):
        seen = []
        state = {"exposure_us": 0}

        def apply_settings(exposure_us, gain):
            state["exposure_us"] = exposure_us

        def grab_frame():
            seen.append(state["exposure_us"])
            return frame_of(min(255, state["exposure_us"] * 1.4))

        calibrate_exposure(apply_settings, grab_frame, settle_frames=2, **LIMITS)
        # Three reads per probe: two thrown away, one measured.
        self.assertGreaterEqual(len(seen), 3 * len(plan_exposures(20, 250, 10)))

    def test_surfaces_a_camera_that_stops_delivering(self):
        def apply_settings(exposure_us, gain):
            return None

        with self.assertRaises(RuntimeError):
            calibrate_exposure(apply_settings, lambda: None, **LIMITS)

    def test_reports_the_measurements_it_used(self):
        apply_settings, grab_frame, _, _ = self._camera(1.4)
        payload = calibrate_exposure(apply_settings, grab_frame, **LIMITS).as_dict()
        self.assertEqual(
            set(payload),
            {
                "exposureUs",
                "gain",
                "meanBrightness",
                "ballLevel",
                "clippedFraction",
                "usable",
                "samplesTaken",
                "note",
            },
        )
        self.assertGreater(payload["samplesTaken"], 1)


def ball_on_dark_mat(level: float, shape=(400, 640), diameter=50) -> np.ndarray:
    """A black frame with one ball-sized disc: the mean is tiny, the ball is the only bright thing."""
    frame = np.zeros(shape, dtype=np.uint8)
    import cv2
    cv2.circle(frame, (shape[1] // 2, shape[0] // 2), diameter // 2, int(level), -1)
    return frame


class BrightestRegionTests(unittest.TestCase):
    """The ball is under 1 % of the pixels, so the frame average says almost nothing about it."""

    def test_the_level_follows_the_ball_not_the_average(self):
        stats = measure_frame(ball_on_dark_mat(120))
        self.assertLess(stats.mean, 3.0)
        self.assertGreater(stats.level, 110.0)
        self.assertEqual(stats.bright, stats.level)

    def test_a_dark_mat_with_a_well_exposed_ball_is_usable_although_the_mean_is_tiny(self):
        self.assertTrue(measure_frame(ball_on_dark_mat(120)).usable)
        self.assertFalse(measure_frame(ball_on_dark_mat(30)).usable)    # a dim ball is still too dark
        self.assertFalse(measure_frame(ball_on_dark_mat(250)).usable)   # a blown-out one is too bright

    def test_without_a_level_the_mean_is_used_as_before(self):
        self.assertEqual(FrameStats(mean=100, clipped_fraction=0.0).bright, 100)
        self.assertTrue(FrameStats(mean=100, clipped_fraction=0.0).usable)
        self.assertFalse(FrameStats(mean=30, clipped_fraction=0.0).usable)

    def test_an_evenly_lit_frame_gives_the_same_answer_by_level_or_mean(self):
        stats = measure_frame(frame_of(100))
        self.assertAlmostEqual(stats.level, stats.mean, delta=1.0)


class CurvedSensorTests(unittest.TestCase):
    """A real sensor's brightness grows more slowly than gain (the processor's curve) and the ball is a small bright disc."""

    def _camera(self, k, *, power=0.5):
        state = {"exposure_us": 0, "gain": 1.0}
        applied = []

        def apply_settings(exposure_us, gain):
            state["exposure_us"], state["gain"] = exposure_us, gain
            applied.append((exposure_us, gain))

        def grab_frame():
            signal = state["exposure_us"] * state["gain"]
            level = min(255.0, 255.0 * (signal / k) ** power)
            return ball_on_dark_mat(level)

        return apply_settings, grab_frame, applied

    def test_a_driver_shutter_in_a_dim_room_settles_on_a_moderate_gain_not_the_maximum(self):
        # k chosen so a 58 us shutter needs about gain 4 for a ball level of ~105 (as measured: ball 97 at 58 us x4)
        apply_settings, grab_frame, applied = self._camera(k=58 * 4 / (105 / 255) ** 2)
        limits = {**LIMITS, "max_us": 58}
        result = calibrate_exposure(apply_settings, grab_frame, **limits)
        self.assertTrue(result.usable)
        self.assertEqual(result.exposure_us, 58)
        self.assertLessEqual(result.gain, 6.0)
        self.assertGreaterEqual(result.gain, 3.0)
        self.assertGreater(result.level, MIN_ACCEPTABLE_MEAN)
        self.assertLess(result.level, MAX_ACCEPTABLE_MEAN)

    def test_later_gain_steps_make_up_for_a_curve_that_a_straight_line_underestimates(self):
        # Needs gain ~12; one straight-line step from a very dark first frame would fall short.
        apply_settings, grab_frame, applied = self._camera(k=58 * 12 / (105 / 255) ** 2)
        result = calibrate_exposure(apply_settings, grab_frame, **{**LIMITS, "max_us": 58})
        self.assertTrue(result.usable)
        self.assertAlmostEqual(result.gain, 12.0, delta=3.0)
        self.assertGreater(len([a for a in applied if a[1] > 1.0]), 1)     # more than one gain step was needed

    def test_when_gain_is_needed_the_longest_allowed_shutter_is_used_not_an_arbitrary_one(self):
        # The real sensor: at gain 1 every frame under ~230 units of shutter x gain is black (the processor's crush),
        # so all the sweep's samples tie at level 0 and "the best one" would be the first, the 20 us frame.
        state = {"exposure_us": 0, "gain": 1.0}
        applied = []

        def apply_settings(exposure_us, gain):
            state["exposure_us"], state["gain"] = exposure_us, gain
            applied.append((exposure_us, gain))

        def grab_frame():
            signal = state["exposure_us"] * state["gain"]
            level = 0.0 if signal < 150 else min(255.0, 255.0 * ((signal - 150) / 900.0) ** 0.5)
            return ball_on_dark_mat(level)

        result = calibrate_exposure(apply_settings, grab_frame, **{**LIMITS, "max_us": 58})
        self.assertEqual(result.exposure_us, 58)
        self.assertEqual(applied[-1][0], 58)
        self.assertLess(result.gain, 8.0)
        self.assertTrue(result.usable)

    def test_a_stale_black_frame_after_raising_the_gain_is_measured_again(self):
        state = {"exposure_us": 0, "gain": 1.0, "grabs_since_change": 99}
        applied = []

        def apply_settings(exposure_us, gain):
            state["exposure_us"], state["gain"], state["grabs_since_change"] = exposure_us, gain, 0
            applied.append((exposure_us, gain))

        def grab_frame():
            state["grabs_since_change"] += 1
            signal = state["exposure_us"] * state["gain"]
            level = 0.0 if signal < 150 else min(255.0, 255.0 * ((signal - 150) / 900.0) ** 0.5)
            # The first gain change is slow to take effect: its frames stay black for a few reads.
            if state["gain"] > 1.0 and len([a for a in applied if a[1] > 1.0]) == 1 and state["grabs_since_change"] <= 3:
                level = 0.0
            return ball_on_dark_mat(level)

        result = calibrate_exposure(apply_settings, grab_frame, **{**LIMITS, "max_us": 58}, settle_frames=1)
        self.assertTrue(result.usable)
        self.assertLess(result.gain, 16.0)

    def test_it_says_so_when_even_the_maximum_gain_is_not_enough(self):
        apply_settings, grab_frame, _ = self._camera(k=58 * 200 / (105 / 255) ** 2)
        result = calibrate_exposure(apply_settings, grab_frame, **{**LIMITS, "max_us": 58})
        self.assertFalse(result.usable)
        self.assertEqual(result.gain, 16.0)
        self.assertIn("Still dark", result.note)

    def test_an_overshoot_is_brought_back_down(self):
        # An extremely steep sensor: the first straight-line step lands far too bright.
        apply_settings, grab_frame, applied = self._camera(k=58 * 3 / (105 / 255) ** 4, power=0.25)
        result = calibrate_exposure(apply_settings, grab_frame, **{**LIMITS, "max_us": 58})
        self.assertLessEqual(result.level, MAX_ACCEPTABLE_MEAN + 40)
        self.assertLess(result.gain, 16.0)


if __name__ == "__main__":
    unittest.main()
