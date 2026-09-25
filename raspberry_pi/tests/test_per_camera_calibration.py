"""Per-camera lens calibration: separate folders, counts and installed intrinsics."""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ball_detector  # noqa: E402
from ball_detector import BallMonitor  # noqa: E402
from camera_source import DualCsiCapture  # noqa: E402
from pinpoint_protocol import PinpointProtocol  # noqa: E402
from tests.test_protocol import ProtocolHarness  # noqa: E402


def _frame() -> Any:
    return np.full((48, 64, 3), 127, dtype=np.uint8)


class PerCameraCalibrationStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        # patch.dict restores any outer value, so a surrounding isolation survives.
        environment = patch.dict(os.environ, {"PINPOINT_CALIBRATION_IMAGE_PATH": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_each_camera_keeps_its_own_views_and_counts(self) -> None:
        ball_detector.save_calibration_frame(_frame(), "primary")
        ball_detector.save_calibration_frame(_frame(), "primary")
        ball_detector.save_calibration_frame(_frame(), "secondary")

        status = ball_detector.calibration_capture_status()
        self.assertEqual(status["totalSaved"], 2, "top level stays the primary camera")
        self.assertEqual(status["cameras"]["primary"]["totalSaved"], 2)
        self.assertEqual(status["cameras"]["secondary"]["totalSaved"], 1)
        self.assertTrue((self.root / "primary" / "calib-0001.jpg").exists())
        self.assertTrue((self.root / "secondary" / "calib-0000.jpg").exists())

    def test_clearing_one_camera_leaves_the_other_intact(self) -> None:
        ball_detector.save_calibration_frame(_frame(), "primary")
        ball_detector.save_calibration_frame(_frame(), "secondary")

        cleared = ball_detector.clear_calibration_images("secondary")

        self.assertEqual(cleared, {"camera": "secondary", "totalSaved": 0, "totalWithCorners": 0})
        self.assertEqual(ball_detector.calibration_capture_status("primary")["totalSaved"], 1)

    def test_unknown_camera_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ball_detector.save_calibration_frame(_frame(), "upper")

    def test_views_saved_before_the_upgrade_become_the_primary_camera(self) -> None:
        (self.root / "calib-0000.jpg").write_bytes(b"jpeg")
        (self.root / "manifest.json").write_text(
            json.dumps([{"file": "calib-0000.jpg", "cornersFound": True}]), encoding="utf-8"
        )

        status = ball_detector.calibration_capture_status()

        self.assertEqual(status["cameras"]["primary"], {"camera": "primary", "totalSaved": 1, "totalWithCorners": 1})
        self.assertEqual(status["cameras"]["secondary"]["totalSaved"], 0)
        self.assertTrue((self.root / "primary" / "calib-0000.jpg").exists())
        self.assertFalse((self.root / "manifest.json").exists())

    def test_a_legacy_folder_that_cannot_be_moved_does_not_break_status(self) -> None:
        (self.root / "manifest.json").write_text("[]", encoding="utf-8")
        with patch.object(Path, "mkdir", side_effect=PermissionError("read-only")):
            status = ball_detector.calibration_capture_status()

        self.assertEqual(status["cameras"]["primary"]["totalSaved"], 0)
        self.assertTrue((self.root / "manifest.json").exists())

    def test_installed_intrinsics_are_reported_per_camera(self) -> None:
        with TemporaryDirectory() as intrinsics_directory:
            primary = Path(intrinsics_directory) / "intrinsics.json"
            secondary = Path(intrinsics_directory) / "intrinsics-secondary.json"
            environment = patch.dict(os.environ, {"PINPOINT_INTRINSICS_PATH": str(primary),
                                                  "PINPOINT_SECONDARY_INTRINSICS_PATH": str(secondary)})
            environment.start()
            self.addCleanup(environment.stop)
            primary.write_text(
                json.dumps({"cameraMatrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "rmsPx": 0.31,
                            "imageSize": [640, 400], "views": ["a", "b"]}),
                encoding="utf-8",
            )

            status = ball_detector.lens_calibration_status()

            self.assertEqual(status["primary"]["rmsPx"], 0.31)
            self.assertEqual(status["primary"]["views"], 2)
            self.assertNotIn("secondary", status, "an uncalibrated camera is simply absent")


class CalibrationCaptureRoutingTests(unittest.TestCase):
    """The detection loop must save the view of the camera the app asked for."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {"PINPOINT_CALIBRATION_IMAGE_PATH": self.directory.name})
        environment.start()
        self.addCleanup(environment.stop)

    def _run_once(self, camera: str, *, dual: bool) -> list[dict[str, Any]]:
        import threading

        stop = threading.Event()
        request = threading.Event()
        request.set()
        primary = np.full((48, 64, 3), 40, dtype=np.uint8)
        secondary = np.full((48, 64, 3), 200, dtype=np.uint8)

        def read() -> tuple[bool, Any]:
            stop.set()  # One pass through the loop is enough.
            return True, primary

        capture = Mock(spec=DualCsiCapture) if dual else Mock()
        capture.isOpened.return_value = True
        capture.read.side_effect = read
        capture.metadata = {}
        if dual:
            capture.secondary_frame = secondary

        results: list[dict[str, Any]] = []
        with patch.dict(os.environ, {"PINPOINT_CAMERA_SOURCE": "usb", "PINPOINT_AUTO_BALL_DETECTION": "false"}):
            monitor = BallMonitor(None)
            with (
                patch.object(monitor, "_open_camera", return_value=capture),
                patch.object(monitor, "_publish_preview"),
                patch("ball_detector.record_camera_diagnostics"),
            ):
                monitor.run(stop, Mock(), calibration_capture_event=request,
                            emit_calibration_result=results.append,
                            calibration_capture_camera=lambda: camera)
        return results

    def test_secondary_request_saves_the_second_camera_view(self) -> None:
        results = self._run_once("secondary", dual=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["camera"], "secondary")
        self.assertNotIn("error", results[0])
        self.assertEqual(ball_detector.calibration_capture_status("primary")["totalSaved"], 0)
        self.assertEqual(ball_detector.calibration_capture_status("secondary")["totalSaved"], 1)

    def test_secondary_request_without_a_second_stream_reports_the_reason(self) -> None:
        results = self._run_once("secondary", dual=False)

        self.assertEqual(len(results), 1)
        self.assertIn("not streaming", results[0]["error"])
        self.assertEqual(results[0]["camera"], "secondary")
        self.assertEqual(ball_detector.calibration_capture_status()["cameras"]["secondary"]["totalSaved"], 0)

    def test_primary_request_saves_the_detection_camera_view(self) -> None:
        results = self._run_once("primary", dual=True)

        self.assertEqual(results[0]["camera"], "primary")
        self.assertEqual(ball_detector.calibration_capture_status("primary")["totalSaved"], 1)
        self.assertEqual(ball_detector.calibration_capture_status("secondary")["totalSaved"], 0)


class PerCameraCalibrationCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["PINPOINT_CAPTURE_BACKEND"] = "simulator"
        self.harness = ProtocolHarness()
        self.requested: list[str] = []
        self.protocol = PinpointProtocol(
            self.harness.send,
            capture_delay=0.02,
            request_calibration_capture=lambda camera: self.requested.append(camera) or True,
        )

    async def asyncTearDown(self) -> None:
        await self.protocol.close()

    async def _response(self, request_id: str) -> dict[str, Any]:
        for _ in range(20):
            match = next((m for m in self.harness.messages if m.get("id") == request_id), None)
            if match:
                return match
            await asyncio.sleep(0.01)
        raise AssertionError(f"No response for {request_id}")

    async def test_capture_targets_the_requested_camera(self) -> None:
        with patch("pinpoint_protocol.camera_diagnostics", return_value={"cameraCount": 2}):
            await self.harness.command(
                self.protocol, {"id": "c1", "type": "captureCalibrationImage", "camera": "secondary"}
            )

        response = await self._response("c1")
        self.assertEqual(response["type"], "response")
        self.assertEqual(response["data"]["camera"], "secondary")
        self.assertEqual(self.requested, ["secondary"])

    async def test_capture_defaults_to_the_primary_camera(self) -> None:
        await self.harness.command(self.protocol, {"id": "c2", "type": "captureCalibrationImage"})

        self.assertEqual((await self._response("c2"))["data"]["camera"], "primary")
        self.assertEqual(self.requested, ["primary"])

    async def test_second_camera_capture_needs_a_second_stream(self) -> None:
        with patch("pinpoint_protocol.camera_diagnostics", return_value={"cameraCount": 1}):
            await self.harness.command(
                self.protocol, {"id": "c3", "type": "captureCalibrationImage", "camera": "secondary"}
            )

        response = await self._response("c3")
        self.assertEqual(response["type"], "error")
        self.assertIn("second camera", response["message"])
        self.assertEqual(self.requested, [])

    async def test_unknown_camera_is_refused(self) -> None:
        await self.harness.command(
            self.protocol, {"id": "c4", "type": "captureCalibrationImage", "camera": "upper"}
        )

        self.assertEqual((await self._response("c4"))["type"], "error")
        self.assertEqual(self.requested, [])

    async def test_a_secondary_solve_clears_only_its_own_ground_pose(self) -> None:
        result = {"camera": "secondary", "rmsPx": 0.3, "viewsUsed": 12, "viewsTotal": 12,
                  "imageSize": [640, 400], "savedTo": "/tmp/intrinsics-secondary.json"}
        with patch("pinpoint_protocol.run_lens_calibration", return_value=result) as solve, patch(
            "pinpoint_protocol.clear_apriltag_calibration"
        ) as clear_ground, patch("pinpoint_protocol.clear_target_line") as clear_line:
            await self.harness.command(
                self.protocol, {"id": "l1", "type": "runLensCalibration", "camera": "secondary"}
            )

        self.assertEqual((await self._response("l1"))["data"]["camera"], "secondary")
        solve.assert_called_once_with("secondary")
        clear_ground.assert_called_once_with("secondary")
        clear_line.assert_not_called()

    async def test_a_primary_solve_still_clears_the_dependent_geometry(self) -> None:
        result = {"camera": "primary", "rmsPx": 0.3, "viewsUsed": 12, "viewsTotal": 12,
                  "imageSize": [640, 400], "savedTo": "/tmp/intrinsics.json"}
        with patch("pinpoint_protocol.run_lens_calibration", return_value=result), patch(
            "pinpoint_protocol.clear_apriltag_calibration"
        ) as clear_ground, patch("pinpoint_protocol.clear_target_line") as clear_line:
            await self.harness.command(self.protocol, {"id": "l2", "type": "runLensCalibration"})

        await self._response("l2")
        clear_ground.assert_called_once_with("primary")
        clear_line.assert_called_once()


if __name__ == "__main__":
    unittest.main()
