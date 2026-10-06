import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rejection_hints import friendly_failure

EXPOSURE = "Use fixed exposure at or below 250 us and adequate lighting; faster shots may require shorter exposure."
OUTLINES = "Fewer than three usable 3D ball outlines. Captured 250 frames; tracked motion in 4."


class ExposureGateTests(unittest.TestCase):
    def test_a_strobe_shot_in_a_lit_room_says_why_and_what_to_switch_to(self):
        text = friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=47, scene_p995_counts=780)
        self.assertIn("strobe mode (3891 us exposure)", text)
        self.assertIn("room is lit", text)
        self.assertIn("Switch Light to Auto, Flat or Daylight", text)

    def test_a_strobe_shot_in_a_dark_room_asks_for_flash_copies_not_a_brighter_room(self):
        text = friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=47, scene_p995_counts=60)
        self.assertNotIn("room is lit", text)
        self.assertIn("flash copies", text)

    def test_the_8_bit_picture_is_used_when_there_is_no_raw_scene_measurement(self):
        lit = friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=47, picture_p995=250)
        dark = friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=47, picture_p995=80)
        self.assertIn("room is lit", lit)
        self.assertNotIn("room is lit", dark)

    def test_a_long_exposure_outside_strobe_points_at_auto_set(self):
        text = friendly_failure(EXPOSURE, exposure_us=994, light_mode="flat", ball_px=47)
        self.assertIn("994 us shutter is too long", text)
        self.assertIn("Auto-set", text)
        self.assertNotIn("strobe", text.lower())
        self.assertIn("9.9 mm", text)   # a 10 m/s chip at 994 us smears 9.9 mm against the 4 mm limit

    def test_a_strobe_exposure_is_recognised_even_if_the_light_state_is_unknown(self):
        self.assertIn("strobe mode", friendly_failure(EXPOSURE, exposure_us=3891, light_mode=None, ball_px=47))

    def test_without_an_exposure_the_original_message_stays(self):
        self.assertEqual(friendly_failure(EXPOSURE, exposure_us=None, light_mode="flat", ball_px=47), EXPOSURE)


class OutlinesTests(unittest.TestCase):
    def test_a_small_ball_is_told_to_move_the_camera_closer(self):
        text = friendly_failure(OUTLINES, exposure_us=95, light_mode="flat", ball_px=18)
        self.assertIn("only 18 px wide", text)
        self.assertIn("move the camera closer", text)
        self.assertIn(OUTLINES, text)

    def test_a_good_sized_ball_gets_the_fast_shot_advice(self):
        text = friendly_failure(OUTLINES, exposure_us=95, light_mode="flat", ball_px=48)
        self.assertNotIn("move the camera closer", text)
        self.assertIn("left the view", text)


class OtherTests(unittest.TestCase):
    def test_unrelated_and_empty_failures_are_unchanged(self):
        self.assertIsNone(friendly_failure(None, exposure_us=95, light_mode="flat", ball_px=48))
        self.assertEqual(friendly_failure("", exposure_us=95, light_mode="flat", ball_px=48), "")
        self.assertEqual(friendly_failure("Sensor timestamps required", exposure_us=95, light_mode="flat", ball_px=48),
                         "Sensor timestamps required")


if __name__ == "__main__":
    unittest.main()
