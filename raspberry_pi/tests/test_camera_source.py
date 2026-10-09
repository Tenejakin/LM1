import os
import json
import sys
import numpy as np
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera_source import (
    CsiCapture,
    active_light,
    auto_calibrate_camera,
    auto_calibrate_light,
    blur_safe_exposure_us,
    set_exposure_cap_hint,
    take_exposure_cap_hint,
    camera_diagnostics,
    light_mode,
    raw_black_level,
    raw_capture_enabled,
    set_light_mode,
    clear_camera_diagnostics,
    configured_camera_gain,
    configured_exposure_us,
    exposure_configuration,
    gain_configuration,
    record_camera_diagnostics,
    set_camera_gain,
    set_camera_exposure,
    set_strobe_mode,
    strobe_mode_enabled,
)
from pinpoint_protocol import PinpointProtocol, build_preview_event


class CsiCameraTests(unittest.TestCase):
    def setUp(self):
        self.settings_directory = TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "PINPOINT_CAMERA_SOURCE": "csi", "PINPOINT_EXPOSURE_US": "0",
            "PINPOINT_CAMERA_RESOLUTION": "1280x800", "PINPOINT_CAMERA_FPS": "30",
            "PINPOINT_CAPTURE_BACKEND": "simulator", "PINPOINT_BLE_PREVIEW": "true",
            "PINPOINT_CAMERA_SETTINGS_PATH": str(
                Path(self.settings_directory.name) / "camera-settings.json"
            ),
        }, clear=True)
        self.env.start()
        clear_camera_diagnostics()

    def tearDown(self):
        clear_camera_diagnostics()
        self.env.stop()
        self.settings_directory.cleanup()

    def test_status_requires_live_frames_not_device_node(self):
        protocol = PinpointProtocol(MagicMock())
        self.assertFalse(protocol.status()["cameraConnected"])
        self.assertEqual(protocol.status()["preview"]["height"], 100)
        record_camera_diagnostics({"model": "ov9281", "fps": 30.0, "exposureUs": 18000})
        status = protocol.status()
        self.assertTrue(status["cameraConnected"])
        self.assertEqual(status["exposureUs"], 18000)
        self.assertEqual(status["captureBackend"], "simulator")
        with patch("camera_source.time.monotonic", return_value=10**12):
            self.assertFalse(protocol.status()["cameraConnected"])

    def test_preview_carries_live_focus_and_exposure(self):
        record_camera_diagnostics({"model": "ov9281", "focusScore": 24.2, "exposureUs": 10000})
        self.assertEqual(build_preview_event(b"jpeg")["data"]["camera"]["focusScore"], 24.2)

    def test_capture_returns_full_frame_and_releases_request(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        camera.camera_controls = {"ExposureTime": (), "AeEnable": ()}
        request = camera.wait.return_value
        request.make_array.return_value = SimpleNamespace(shape=(800, 1280, 3))
        request.get_metadata.return_value = {"FrameDuration": 33333, "ExposureTime": 20000}
        with patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))}):
            capture = CsiCapture()
            self.assertTrue(camera.create_video_configuration.call_args.kwargs["controls"]["AeEnable"])
            self.assertTrue(capture.read()[0])
            request.release.assert_called_once()
            self.assertEqual(camera_diagnostics()["width"], 1280)
            self.assertFalse(camera_diagnostics()["autofocus"])
            capture.release()
        camera.close.assert_called_once()
        self.assertEqual(camera_diagnostics(), {})

    def test_timeout_cancels_pending_capture_and_allows_cleanup(self):
        camera = MagicMock()
        camera.wait.side_effect = TimeoutError
        with patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))}):
            capture = CsiCapture()
            with self.assertRaisesRegex(RuntimeError, "stopped delivering"):
                capture.read()
            capture.release()
        camera.cancel_all_and_flush.assert_called_once()
        camera.close.assert_called_once()

    def test_configuration_failure_closes_camera(self):
        camera = MagicMock()
        camera.configure.side_effect = RuntimeError("configuration failed")
        with patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))}):
            with self.assertRaisesRegex(RuntimeError, "configuration failed"):
                CsiCapture()
        camera.close.assert_called_once()

    def test_live_exposure_is_applied_and_persisted(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"PINPOINT_CAMERA_SETTINGS_PATH": str(Path(directory) / "camera-settings.json")},
        ), patch.dict(
            sys.modules,
            {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            result = set_camera_exposure(180)
            camera.set_controls.assert_called_once_with({
                "AeEnable": False,
                "ExposureTime": 180,
                "AnalogueGain": 1.0,
            })
            self.assertEqual(result["exposureUs"], 180)
            self.assertTrue(result["configurable"])
            self.assertEqual(configured_exposure_us(), 180)
            saved = json.loads((Path(directory) / "camera-settings.json").read_text(encoding="utf-8"))
            # A shutter set by hand leaves Auto, so the automatic sweep cannot overwrite it.
            self.assertEqual(saved, {"exposureUs": 180, "lightMode": "flat"})
            capture.release()
        self.assertTrue(exposure_configuration()["configurable"])

    def test_live_exposure_accepts_short_motion_freezing_value(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"PINPOINT_CAMERA_SETTINGS_PATH": str(Path(directory) / "camera-settings.json")},
        ), patch.dict(
            sys.modules,
            {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            result = set_camera_exposure(5)
            self.assertEqual(result["exposureUs"], 5)
            self.assertEqual(result["minUs"], 1)
            camera.set_controls.assert_called_once_with({
                "AeEnable": False,
                "ExposureTime": 5,
                "AnalogueGain": 1.0,
            })
            capture.release()

    def test_live_exposure_is_limited_only_by_the_sensor(self):
        # No camera open: 1 us up to one frame period (30 fps here).
        with self.assertRaisesRegex(ValueError, "between 1 and 33333"):
            set_camera_exposure(33334)
        with self.assertRaisesRegex(ValueError, "between 1 and 33333"):
            set_camera_exposure(0)

    def test_sensor_range_comes_from_libcamera_capped_at_one_frame(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        camera.camera_controls = {"ExposureTime": (9, 1_000_000, 100)}
        with patch.dict(os.environ, {"PINPOINT_CAMERA_FPS": "242"}), patch.dict(
            sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            config = exposure_configuration()
            self.assertEqual((config["minUs"], config["maxUs"]), (9, 4132))
            self.assertEqual(config["measurementMaxUs"], 250)
            with self.assertRaisesRegex(ValueError, "between 9 and 4132"):
                set_camera_exposure(8)
            with self.assertRaisesRegex(ValueError, "between 9 and 4132"):
                set_camera_exposure(4133)
            self.assertEqual(set_camera_exposure(4132)["exposureUs"], 4132)
            capture.release()
        # Closing the camera forgets its range.
        self.assertEqual(exposure_configuration()["maxUs"], 33333)

    def test_applied_exposure_is_read_back_from_the_frames(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        with patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))}):
            capture = CsiCapture()
            capture.metadata = {"ExposureTime": 3891}
            self.assertEqual(set_camera_exposure(3900)["appliedExposureUs"], 3891)
            capture.release()

    def test_strobe_mode_raises_the_exposure_limit_and_restores_the_normal_exposure(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"PINPOINT_CAMERA_SETTINGS_PATH": str(Path(directory) / "camera-settings.json")},
        ), patch.dict(
            sys.modules,
            {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            set_camera_exposure(150)
            self.assertFalse(strobe_mode_enabled())
            # The shutter range no longer depends on the light mode: only the sensor limits it.
            self.assertEqual(exposure_configuration()["maxUs"], 33333)
            self.assertFalse(exposure_configuration()["strobeMode"])

            result = set_strobe_mode(True)
            self.assertEqual(result["exposureUs"], 3900)
            self.assertEqual(result["maxUs"], 33333)
            self.assertTrue(result["strobeMode"])
            self.assertTrue(strobe_mode_enabled())
            self.assertEqual(configured_exposure_us(), 3900)
            self.assertEqual(set_camera_exposure(2000)["exposureUs"], 2000)
            # Turning it on twice must not overwrite the remembered normal exposure.
            set_strobe_mode(True)

            result = set_strobe_mode(False)
            self.assertEqual(result["exposureUs"], 150)
            self.assertEqual(result["maxUs"], 33333)
            self.assertFalse(strobe_mode_enabled())
            self.assertEqual(configured_exposure_us(), 150)
            capture.release()

    def _open_camera(self, directory=None):
        # setUp already points the settings file at a temporary directory.
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        entered = patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))})
        entered.start()
        self.addCleanup(entered.stop)
        return CsiCapture()

    def test_each_light_mode_remembers_its_own_exposure_and_gain(self):
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            set_camera_exposure(143)
            set_camera_gain(8.0)

            sun = set_light_mode("daylight")
            self.assertEqual((sun["exposureUs"], sun["gain"]), (30, 1.0))
            self.assertEqual(sun["activeLight"], "daylight")
            self.assertEqual(sun["maxUs"], 33333)
            set_camera_exposure(40)

            room = set_light_mode("flat")
            self.assertEqual((room["exposureUs"], room["gain"]), (143, 8.0))
            self.assertEqual(set_light_mode("daylight")["exposureUs"], 40)

            dark = set_light_mode("strobe")
            self.assertEqual(dark["exposureUs"], 3900)
            self.assertEqual(dark["maxUs"], 33333)
            self.assertEqual(light_mode(), "strobe")
            self.assertEqual(set_light_mode("flat")["exposureUs"], 143)
            self.assertEqual(active_light(), "flat")
            capture.release()

    def test_auto_light_uses_the_last_decision_and_rejects_bad_modes(self):
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            with self.assertRaisesRegex(ValueError, "auto, daylight, flat or strobe"):
                set_light_mode("disco")
            result = set_light_mode("auto")
            self.assertEqual(result["lightMode"], "auto")
            self.assertEqual(result["activeLight"], "flat")
            capture.release()

    def _light(self, connected=True):
        light = MagicMock()
        light.status.return_value = {"connected": connected}
        return light

    def test_auto_light_picks_daylight_when_the_ring_off_sweep_is_short(self):
        sweep = {"exposureUs": 40, "gain": 1.0, "usable": True, "note": "Matched the light in the room."}
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            light = self._light()
            with patch("camera_source.auto_calibrate_camera", return_value=dict(sweep)) as calibrate, \
                    patch("camera_source.time.sleep"):
                result = auto_calibrate_light(lambda: None, light)
            self.assertEqual(result["light"], "daylight")
            calibrate.assert_called_once()
            self.assertEqual([call.args[0] for call in light.set_mode.call_args_list], ["off"])
            self.assertEqual(light_mode(), "auto")
            self.assertEqual(active_light(), "daylight")
            capture.release()

    def test_auto_light_turns_the_ring_on_when_ambient_light_is_not_enough(self):
        dark = {"exposureUs": 250, "gain": 1.0, "usable": False, "note": "Still dark"}
        lit = {"exposureUs": 143, "gain": 8.0, "usable": True, "note": "ok"}
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            light = self._light()
            with patch("camera_source.auto_calibrate_camera", side_effect=[dark, lit]), \
                    patch("camera_source.time.sleep"):
                result = auto_calibrate_light(lambda: None, light)
            self.assertEqual(result["light"], "flat")
            self.assertEqual(result["exposureUs"], 143)
            self.assertEqual([call.args[0] for call in light.set_mode.call_args_list], ["off", "flat"])
            self.assertEqual(active_light(), "flat")
            capture.release()

    def test_auto_light_never_leaves_the_ring_off_after_a_failed_sweep(self):
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            light = self._light()
            with patch("camera_source.auto_calibrate_camera", side_effect=RuntimeError("no frames")), \
                    patch("camera_source.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "no frames"):
                    auto_calibrate_light(lambda: None, light)
            self.assertEqual(light.set_mode.call_args_list[-1].args[0], "flat")
            capture.release()

    def test_auto_light_is_a_plain_sweep_without_a_connected_controller(self):
        sweep = {"exposureUs": 100, "gain": 2.0, "usable": True, "note": "ok"}
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            for light in (None, self._light(connected=False)):
                with patch("camera_source.auto_calibrate_camera", return_value=dict(sweep)):
                    result = auto_calibrate_light(lambda: None, light)
                self.assertEqual(result["exposureUs"], 100)
            self.assertEqual(light.set_mode.call_count, 0)
            capture.release()

    def _raw_camera(self, width=640, height=400, with_raw=True):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        raw_words = (np.arange(height * width, dtype=np.uint16) % 997 + 1100).reshape(height, width)
        # libcamera hands over raw as bytes with a 2-byte-per-pixel stride, possibly padded.
        padded = np.zeros((height, width + 8), np.uint16)
        padded[:, :width] = raw_words
        request = MagicMock()
        request.make_array.side_effect = lambda stream: {
            "main": np.zeros((height, width, 3), np.uint8),
            "raw": padded.view(np.uint8),
        }[stream]
        request.get_metadata.return_value = {"SensorTimestamp": 123, "FrameDuration": 4131, "ExposureTime": 100,
                                             "AnalogueGain": 1.0, "SensorBlackLevels": (4096, 4096, 4096, 4096)}
        camera.wait.return_value = request
        return camera, request, raw_words

    def test_raw_capture_adds_the_raw_stream_and_returns_the_frame_as_16_bit_words(self):
        camera, request, raw_words = self._raw_camera()
        env = {"PINPOINT_CAMERA_RAW": "true", "PINPOINT_CAMERA_RESOLUTION": "640x400", "PINPOINT_CAMERA_BIT_DEPTH": "10"}
        with patch.dict(os.environ, env), patch.dict(
            sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            config_call = camera.create_video_configuration.call_args.kwargs
            self.assertEqual(config_call["raw"], {"size": (640, 400), "format": "R10"})
            ok, frame = capture.read()
            self.assertTrue(ok)
            raw = capture.metadata["RawFrame"]
            self.assertEqual(raw.dtype, np.uint16)
            self.assertEqual(raw.shape, (400, 640))
            self.assertTrue(np.array_equal(raw, raw_words))
            self.assertEqual(raw_black_level(capture.metadata), 1024)
            capture.release()

    def test_raw_capture_is_off_by_default_and_never_with_an_8_bit_sensor_mode(self):
        for env in ({}, {"PINPOINT_CAMERA_RAW": "true", "PINPOINT_CAMERA_BIT_DEPTH": "8"}):
            camera, _, _ = self._raw_camera()
            with patch.dict(os.environ, {"PINPOINT_CAMERA_RESOLUTION": "640x400", **env}), patch.dict(
                sys.modules, {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
            ):
                capture = CsiCapture()
                self.assertNotIn("raw", camera.create_video_configuration.call_args.kwargs)
                self.assertFalse(raw_capture_enabled())
                capture.release()

    def test_black_level_falls_back_to_the_measured_floor(self):
        # libcamera's 4096 is what the image processor subtracts; the data's own floor is ~1024 words.
        self.assertEqual(raw_black_level({}), 1024)
        self.assertEqual(raw_black_level({"SensorBlackLevels": (4096, 4096, 4096, 4096)}), 1024)
        with patch.dict(os.environ, {"PINPOINT_RAW_BLACK_LEVEL": "1200"}):
            self.assertEqual(raw_black_level(), 1200)
        with patch.dict(os.environ, {"PINPOINT_RAW_BLACK_LEVEL": "nonsense"}):
            self.assertEqual(raw_black_level(), 1024)

    def test_the_blur_safe_exposure_falls_with_ball_speed_and_stays_in_range(self):
        # 4 mm of smear with a 10 % margin: driver 62 m/s -> 58 us, 7-iron 42 -> 85, pitching wedge 35 -> 102
        self.assertEqual(blur_safe_exposure_us(62.0), 58)
        self.assertEqual(blur_safe_exposure_us(42.0), 85)
        self.assertEqual(blur_safe_exposure_us(35.0), 102)
        self.assertEqual(blur_safe_exposure_us(5.0), 250)
        self.assertEqual(blur_safe_exposure_us(500.0), 20)
        self.assertEqual(blur_safe_exposure_us(0), 250)

    def test_the_exposure_cap_hint_is_taken_once(self):
        set_exposure_cap_hint(60)
        self.assertEqual(take_exposure_cap_hint(), 60)
        self.assertIsNone(take_exposure_cap_hint())

    def test_the_automatic_sweep_stays_under_the_clubs_blur_limit_and_says_so_when_too_dark(self):
        from exposure_calibration import CalibrationResult
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            seen = {}

            def fake(apply_settings, grab_frame, **kwargs):
                seen.update(kwargs)
                return CalibrationResult(exposure_us=58, gain=16.0, mean=40.0, clipped_fraction=0.0, usable=False,
                                         samples=8, note="Still dark at the brightest safe setting - add light to the hitting area.")

            with patch("exposure_calibration.calibrate_exposure", side_effect=fake):
                capped = auto_calibrate_camera(lambda: None, 58)
                self.assertEqual(seen["max_us"], 58)
                self.assertEqual(capped["blurLimitUs"], 58)
                self.assertIn("58 us shutter this club needs", capped["note"])
                uncapped = auto_calibrate_camera(lambda: None)
                self.assertEqual(seen["max_us"], 250)
                self.assertNotIn("blurLimitUs", uncapped)
            capture.release()

    def test_the_cap_is_clamped_to_the_allowed_range(self):
        from exposure_calibration import CalibrationResult
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            seen = {}

            def fake(apply_settings, grab_frame, **kwargs):
                seen.update(kwargs)
                return CalibrationResult(exposure_us=20, gain=1.0, mean=100.0, clipped_fraction=0.0, usable=True,
                                         samples=1, note="ok")

            with patch("exposure_calibration.calibrate_exposure", side_effect=fake):
                auto_calibrate_camera(lambda: None, 5)
                self.assertEqual(seen["max_us"], 20)
                auto_calibrate_camera(lambda: None, 9999)
                self.assertEqual(seen["max_us"], 250)
            capture.release()

    def test_auto_light_passes_the_cap_to_both_sweeps(self):
        dark = {"exposureUs": 58, "gain": 16.0, "usable": False, "note": "dark"}
        lit = {"exposureUs": 58, "gain": 12.0, "usable": True, "note": "ok"}
        with TemporaryDirectory() as directory:
            capture = self._open_camera(directory)
            light = self._light()
            with patch("camera_source.auto_calibrate_camera", side_effect=[dark, lit]) as calibrate, \
                    patch("camera_source.time.sleep"):
                auto_calibrate_light(lambda: None, light, 58)
            self.assertEqual([call.args[1] for call in calibrate.call_args_list], [58, 58])
            capture.release()

    def test_strobe_mode_needs_an_open_camera_and_a_real_boolean(self):
        with self.assertRaisesRegex(ValueError, "on or off"):
            set_strobe_mode("yes")  # type: ignore[arg-type]
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            set_strobe_mode(True)

    def test_live_gain_is_applied_persisted_and_reused_by_exposure(self):
        camera = MagicMock()
        camera.camera_properties = {"Model": "ov9281"}
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "PINPOINT_CAMERA_SETTINGS_PATH": str(Path(directory) / "camera-settings.json"),
                "PINPOINT_EXPOSURE_US": "200",
            },
        ), patch.dict(
            sys.modules,
            {"picamera2": SimpleNamespace(Picamera2=MagicMock(return_value=camera))},
        ):
            capture = CsiCapture()
            result = set_camera_gain(2.5)
            camera.set_controls.assert_called_once_with({"AnalogueGain": 2.5})
            self.assertEqual(result["gain"], 2.5)
            self.assertEqual(configured_camera_gain(), 2.5)
            self.assertEqual(gain_configuration()["max"], 16.0)

            camera.reset_mock()
            set_camera_exposure(180)
            camera.set_controls.assert_called_once_with({
                "AeEnable": False,
                "ExposureTime": 180,
                "AnalogueGain": 2.5,
            })
            saved = json.loads((Path(directory) / "camera-settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, {"exposureUs": 180, "gain": 2.5, "lightMode": "flat"})
            capture.release()

    def test_live_gain_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 16"):
            set_camera_gain(16.25)
        with self.assertRaisesRegex(ValueError, "finite number"):
            set_camera_gain(float("nan"))
