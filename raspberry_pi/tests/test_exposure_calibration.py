import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exposure_calibration import (
    MAX_CLIPPED_FRACTION,
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
                "clippedFraction",
                "usable",
                "samplesTaken",
                "note",
            },
        )
        self.assertGreater(payload["samplesTaken"], 1)


if __name__ == "__main__":
    unittest.main()
