import os
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera_source import (
    CsiCapture,
    camera_diagnostics,
    clear_camera_diagnostics,
    configured_camera_gain,
    configured_exposure_us,
    exposure_configuration,
    gain_configuration,
    record_camera_diagnostics,
    set_camera_gain,
    set_camera_exposure,
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
            self.assertEqual(saved, {"exposureUs": 180})
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
            result = set_camera_exposure(20)
            self.assertEqual(result["exposureUs"], 20)
            self.assertEqual(result["minUs"], 20)
            camera.set_controls.assert_called_once_with({
                "AeEnable": False,
                "ExposureTime": 20,
                "AnalogueGain": 1.0,
            })
            capture.release()

    def test_live_exposure_rejects_values_outside_measurement_range(self):
        with self.assertRaisesRegex(ValueError, "between 20 and 250"):
            set_camera_exposure(251)
        with self.assertRaisesRegex(ValueError, "between 20 and 250"):
            set_camera_exposure(19)

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
            self.assertEqual(saved, {"exposureUs": 180, "gain": 2.5})
            capture.release()

    def test_live_gain_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 16"):
            set_camera_gain(16.25)
        with self.assertRaisesRegex(ValueError, "finite number"):
            set_camera_gain(float("nan"))
