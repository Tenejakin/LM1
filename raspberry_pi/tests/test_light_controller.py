import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import light_controller
from light_controller import LightController, get_light_controller, preset_for_club, strobe_pattern, indicator_state


class FakeSerial:
    def __init__(self, replies=b""):
        self.written: list[str] = []
        self.replies = replies
        self.closed = False
        self.fail_writes = False

    def write(self, data):
        if self.fail_writes:
            raise OSError("cable pulled")
        self.written.append(data.decode().strip())
        return len(data)

    def flush(self):
        pass

    def read(self, size):
        reply, self.replies = self.replies, b""
        time.sleep(0.005)
        return reply

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class PresetTests(unittest.TestCase):
    def test_status_processing_takes_priority_over_ball_presence(self):
        self.assertEqual(indicator_state("processing", True), "processing")
        self.assertEqual(indicator_state("processing", False), "processing")
        self.assertEqual(indicator_state("armed", True), "ready")
        self.assertEqual(indicator_state("ready", False), "searching")

    def test_status_changes_sent_once_and_reapplied_after_reconnect(self):
        serial = FakeSerial()
        controller = LightController()
        controller._serial = serial
        state = ["searching"]
        controller.set_status_provider(lambda: state[0])
        controller._update_status_locked()
        controller._update_status_locked()
        state[0] = "ready"
        controller._update_status_locked()
        state[0] = "processing"
        controller._update_status_locked()
        self.assertEqual(serial.written, ["led searching", "led ready", "led processing"])
        controller._close()
        reconnected = FakeSerial()
        controller._serial = reconnected
        controller._update_status_locked()
        self.assertEqual(reconnected.written, ["led processing"])

    def test_fast_clubs_get_tight_gaps_and_slow_ones_wide_gaps(self):
        self.assertEqual(preset_for_club("driver"), "driver")
        self.assertEqual(preset_for_club("3-wood"), "driver")
        self.assertEqual(preset_for_club("4-hybrid"), "driver")
        self.assertEqual(preset_for_club("7-iron"), "iron")
        self.assertEqual(preset_for_club("pitching-wedge"), "chip")
        self.assertEqual(preset_for_club("putter"), "chip")
        self.assertEqual(preset_for_club(None), "iron")


class PatternTests(unittest.TestCase):
    PERIOD = 4132  # 242 fps

    def test_copies_never_overlap_even_for_a_ball_20_percent_slower_than_expected(self):
        for speed in (62.0, 55.0, 42.0, 35.0, 27.0, 22.0):
            pattern = strobe_pattern(speed, self.PERIOD)
            slowest = speed * 0.8
            gaps = pattern["gapsUs"]
            burst = pattern["pulseUs"] + sum(gaps)
            wrap = self.PERIOD - burst
            self.assertLessEqual(burst, 0.82 * self.PERIOD)
            for gap in gaps + ([wrap] if gaps else []):
                travelled_mm = slowest * gap / 1000.0
                self.assertGreaterEqual(travelled_mm, 42.67, (speed, gap))

    def test_faster_balls_get_shorter_pulses_and_tighter_gaps(self):
        driver = strobe_pattern(62.0, self.PERIOD)
        iron = strobe_pattern(42.0, self.PERIOD)
        wedge = strobe_pattern(35.0, self.PERIOD)
        lob = strobe_pattern(26.8, self.PERIOD)
        self.assertLess(driver["pulseUs"], iron["pulseUs"])
        self.assertLess(iron["pulseUs"], wedge["pulseUs"])
        self.assertLess(wedge["pulseUs"], lob["pulseUs"])
        self.assertLess(driver["gapsUs"][0], iron["gapsUs"][0])
        self.assertLess(iron["gapsUs"][0], wedge["gapsUs"][0])
        self.assertGreater(len(driver["gapsUs"]), len(wedge["gapsUs"]))
        # Two flashes cannot stay clear of each other inside one 4.1 ms frame at this speed.
        self.assertEqual(lob["gapsUs"], [])

    def test_gaps_are_all_different_so_each_copy_can_be_identified(self):
        gaps = strobe_pattern(62.0, self.PERIOD)["gapsUs"]
        self.assertEqual(len(gaps), len(set(gaps)))
        self.assertEqual(gaps, sorted(gaps))

    def test_very_slow_balls_get_a_single_flash_per_frame(self):
        self.assertEqual(strobe_pattern(12.0, self.PERIOD)["gapsUs"], [])

    def test_speed_is_clamped_to_a_sane_range(self):
        self.assertEqual(strobe_pattern(500.0, self.PERIOD)["pulseUs"], 15)
        self.assertGreaterEqual(strobe_pattern(0.0, self.PERIOD)["pulseUs"], 15)


class LightControllerTests(unittest.TestCase):
    def make(self, port_name="/dev/fake", serial=None):
        serial = serial or FakeSerial()
        controller = LightController(
            fps=242, find_port=lambda: port_name, open_port=lambda port: serial, heartbeat_seconds=0.02,
        )
        self.addCleanup(controller.stop)
        return controller, serial

    def test_connects_applies_the_wanted_mode_and_sends_heartbeats(self):
        controller, serial = self.make()
        controller.set_mode("strobe", "driver")
        self.assertFalse(controller.status()["connected"])
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["connected"]))
        self.assertTrue(wait_for(lambda: serial.written.count("ping") >= 2))
        self.assertIn("rate 242", serial.written)
        self.assertIn("mode strobe driver", serial.written)
        self.assertEqual(controller.status()["mode"], "strobe")
        self.assertEqual(controller.status()["preset"], "driver")

    def test_a_pattern_is_sent_as_pulse_and_gaps_instead_of_a_preset(self):
        controller, serial = self.make()
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["connected"]))
        controller.set_mode("strobe", "iron", {"pulseUs": 29, "gapsUs": [1400, 1510, 1630], "ballSpeedMps": 42.0})
        self.assertEqual(serial.written[-4:], ["rate 242", "p 29", "i 1400 1510 1630", "mode strobe"])
        status = controller.status()
        self.assertEqual(status["preset"], "iron")
        self.assertEqual(status["pattern"]["gapsUs"], [1400, 1510, 1630])
        controller.set_mode("strobe", "chip", {"pulseUs": 60, "gapsUs": []})
        self.assertEqual(serial.written[-4:], ["rate 242", "p 60", "f 1 1000", "mode strobe"])
        controller.set_mode("flat")
        self.assertIsNone(controller.status()["pattern"])

    def test_set_mode_sends_immediately_when_connected(self):
        controller, serial = self.make()
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["connected"]))
        self.assertTrue(controller.set_mode("off"))
        self.assertIn("mode off", serial.written)
        self.assertIsNone(controller.status()["preset"])

    def test_rejects_unknown_modes_and_presets(self):
        controller, _ = self.make()
        with self.assertRaises(ValueError):
            controller.set_mode("disco")
        with self.assertRaises(ValueError):
            controller.set_mode("strobe", "laser")

    def test_a_failed_write_drops_the_link_and_reconnects_with_the_wanted_mode(self):
        controller, serial = self.make()
        controller.set_mode("flat")
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["connected"]))
        serial.fail_writes = True
        self.assertTrue(wait_for(lambda: not controller.status()["connected"]))
        self.assertTrue(serial.closed)
        serial.fail_writes = False
        serial.closed = False
        controller.set_mode("off")  # remembered while disconnected
        self.assertTrue(wait_for(lambda: controller.status()["connected"]))
        self.assertTrue(wait_for(lambda: "mode off" in serial.written))

    def test_reports_the_mode_the_esp32_confirms_and_a_watchdog_fallback(self):
        serial = FakeSerial(replies=b"OK mode=strobe preset=driver rate=242\n")
        controller, _ = self.make(serial=serial)
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["reportedMode"] == "strobe"))
        serial.replies = b"WATCHDOG no host for 3 s, back to flat light\n"
        self.assertTrue(wait_for(lambda: controller.status()["reportedMode"] == "flat"))

    def test_reports_when_no_esp32_is_found(self):
        controller = LightController(find_port=lambda: None, open_port=lambda port: FakeSerial(),
                                     heartbeat_seconds=0.02)
        self.addCleanup(controller.stop)
        controller.start()
        self.assertTrue(wait_for(lambda: controller.status()["error"] == "No ESP32 found on USB."))
        self.assertFalse(controller.status()["connected"])


class FactoryTests(unittest.TestCase):
    def test_disabled_unless_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_light_controller())

    def test_enabled_by_the_environment(self):
        created = []

        class Recorder(LightController):
            def __init__(self, **kwargs):
                super().__init__(find_port=lambda: None, **kwargs)
                created.append(self)

            def start(self):
                pass

        with patch.dict(os.environ, {"PINPOINT_LIGHT_CONTROL": "esp32", "PINPOINT_CAMERA_FPS": "242"}, clear=True), \
                patch.object(light_controller, "_controller", None), \
                patch.object(light_controller, "LightController", Recorder):
            first = get_light_controller()
            self.assertIs(first, get_light_controller())
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]._fps, 242)


if __name__ == "__main__":
    unittest.main()
