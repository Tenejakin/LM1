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


class StrobeReportTests(unittest.TestCase):
    BASE = {"lightMode": "strobe", "separatesAboveMps": 45.0, "expectedSpeedMps": 62.0, "framesSearched": 14}

    def say(self, **report):
        return friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=52,
                                strobe={**self.BASE, **report})

    def test_the_exposure_is_never_blamed_for_a_strobe_shot(self):
        for report in ({"reason": "no-copies", "maxCopies": 0}, {"reason": "too-few-copies", "maxCopies": 1, "maxCopySpanBalls": 0.3},
                       {"reason": "no-fit", "maxCopies": 5}, {"reason": "not-strobing", "lightMode": "off"},
                       {"reason": "pattern-too-short", "gapsUs": [1970]}):
            text = self.say(**report)
            self.assertIn("Not measured", text)
            self.assertNotIn("too long", text)
            self.assertNotIn("smear", text)

    def test_a_ring_that_was_not_flashing_is_named(self):
        text = self.say(reason="not-strobing", lightMode="off", controllerError="no serial port")
        self.assertIn("ring was not flashing", text)
        self.assertIn("'off'", text)
        self.assertIn("no serial port", text)

    def test_a_pattern_with_too_few_flashes_is_not_blamed_on_the_ring(self):
        text = self.say(reason="pattern-too-short", gapsUs=[1970], expectedSpeedMps=29.8)
        self.assertIn("ring was flashing", text)
        self.assertIn("fits only 2 flashes in one frame", text)
        self.assertIn("set for 30 m/s", text)
        self.assertNotIn("not flashing", text)
        self.assertIn("1 flash", self.say(reason="pattern-too-short", gapsUs=[]))

    def test_a_slow_ball_says_what_speed_would_separate_the_copies(self):
        text = self.say(reason="too-few-copies", maxCopies=1, maxCopySpanBalls=0.2)
        self.assertIn("1 copy", text)
        self.assertIn("above about 45 m/s", text)
        self.assertIn("A fast hit is needed", text)

    def test_no_copies_in_a_lit_room_blames_the_room_light(self):
        lit = friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=52, scene_p995_counts=800,
                               strobe={**self.BASE, "reason": "no-copies", "maxCopies": 0})
        self.assertIn("room is lit", lit)

    def test_copies_that_do_not_fit_say_how_close_they_came(self):
        text = self.say(reason="no-fit", maxCopies=4, unreliableFit={"copies": 4, "fitResidualMm": 5.2, "ambiguous": False})
        self.assertIn("did not fit the flash pattern", text)
        self.assertIn("5.2 mm residual", text)

    def test_without_a_report_the_old_strobe_wording_remains(self):
        self.assertIn("strobe mode (3891 us exposure)", friendly_failure(EXPOSURE, exposure_us=3891, light_mode="strobe", ball_px=52))


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
