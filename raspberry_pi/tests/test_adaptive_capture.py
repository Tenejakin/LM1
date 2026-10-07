"""Tests for the club-aware auto light/exposure policy (no camera or serial I/O)."""

import time
import unittest

from adaptive_capture import AdaptivePolicy, ViewSample, club_ball_speed_mps, club_exposure_cap_us


class ClubCapTests(unittest.TestCase):
    def test_club_ball_speed_defaults_to_driver(self) -> None:
        self.assertEqual(club_ball_speed_mps("driver"), 61.32)
        self.assertEqual(club_ball_speed_mps(None), club_ball_speed_mps("driver"))
        self.assertEqual(club_ball_speed_mps("no-such-club"), club_ball_speed_mps("driver"))

    def test_putting_has_no_blur_cap(self) -> None:
        self.assertIsNone(club_exposure_cap_us("driver", putting=True))

    def test_faster_club_gets_a_shorter_shutter(self) -> None:
        self.assertEqual(club_exposure_cap_us("driver"), 58)
        self.assertGreater(club_exposure_cap_us("lob-wedge"), 100)
        self.assertGreater(club_exposure_cap_us("7-iron"), club_exposure_cap_us("driver"))


class AdaptivePolicyTests(unittest.TestCase):
    def test_first_call_is_startup(self) -> None:
        policy = AdaptivePolicy()
        self.assertEqual(
            policy.should_recalibrate("driver", ViewSample(100.0), time.monotonic()), "startup"
        )

    def test_club_change_bypasses_the_cooldown(self) -> None:
        policy = AdaptivePolicy(cooldown_s=1000.0)
        now = time.monotonic()
        policy.record("driver", 100.0, now)
        self.assertEqual(
            policy.should_recalibrate("7-iron", ViewSample(100.0), now + 0.1), "club"
        )

    def test_within_cooldown_no_drift_does_not_recalibrate(self) -> None:
        policy = AdaptivePolicy(cooldown_s=8.0)
        now = time.monotonic()
        policy.record("driver", 100.0, now)
        self.assertIsNone(policy.should_recalibrate("driver", ViewSample(120.0), now + 1.0))

    def test_brightness_drift_after_cooldown_recalibrates(self) -> None:
        policy = AdaptivePolicy(cooldown_s=2.0)
        now = time.monotonic()
        policy.record("driver", 100.0, now)
        self.assertEqual(
            policy.should_recalibrate("driver", ViewSample(160.0), now + 3.0), "drift"
        )

    def test_small_drift_does_not_recalibrate(self) -> None:
        policy = AdaptivePolicy(cooldown_s=2.0)
        now = time.monotonic()
        policy.record("driver", 100.0, now)
        self.assertIsNone(policy.should_recalibrate("driver", ViewSample(120.0), now + 3.0))

    def test_recording_updates_the_baseline(self) -> None:
        policy = AdaptivePolicy(cooldown_s=2.0)
        now = time.monotonic()
        policy.record("driver", 100.0, now)
        policy.record("driver", 160.0, now + 3.0)
        self.assertIsNone(policy.should_recalibrate("driver", ViewSample(170.0), now + 4.0))


if __name__ == "__main__":
    unittest.main()
