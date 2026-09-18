import asyncio
import json
import os
import sys
import unittest
from tempfile import NamedTemporaryFile
from unittest.mock import patch
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpoint_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    SERVICE_VERSION,
    PinpointProtocol,
    build_preview_event,
    encode_message_chunks,
)


class ProtocolHarness:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.message_available = asyncio.Event()

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self.message_available.set()

    async def command(self, protocol: PinpointProtocol, message: dict[str, Any]) -> None:
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode()
        for offset in range(0, len(encoded), 20):
            await protocol.receive_chunk(encoded[offset : offset + 20])

    async def wait_for_type(self, message_type: str) -> dict[str, Any]:
        for _ in range(20):
            match = next(
                (message for message in self.messages if message["type"] == message_type),
                None,
            )
            if match:
                return match
            self.message_available.clear()
            await asyncio.wait_for(self.message_available.wait(), timeout=1)
        raise AssertionError(f"No {message_type} message received")


class PinpointProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["PINPOINT_CAPTURE_BACKEND"] = "simulator"
        os.environ.pop("PINPOINT_NAME", None)
        os.environ["PINPOINT_CAMERA_DEVICE"] = "/nonexistent/lm1-test-camera"
        os.environ.pop("PINPOINT_CAMERA_CONNECTED", None)
        os.environ.pop("PINPOINT_CAMERA_FPS", None)
        os.environ.pop("PINPOINT_EXPOSURE_US", None)
        os.environ.pop("PINPOINT_BLE_PREVIEW", None)
        os.environ["PINPOINT_CALIBRATION_VERSION"] = "NOT-CALIBRATED"
        self.harness = ProtocolHarness()
        self.protocol = PinpointProtocol(self.harness.send, capture_delay=0.02)

    async def asyncTearDown(self) -> None:
        await self.protocol.close()
        os.environ.pop("PINPOINT_CAMERA_DEVICE", None)
        os.environ.pop("PINPOINT_CAMERA_CONNECTED", None)
        os.environ.pop("PINPOINT_BLE_PREVIEW", None)
        os.environ.pop("PINPOINT_CALIBRATION_VERSION", None)

    async def test_status_response_is_ble_only_and_camera_free(self) -> None:
        with patch("pinpoint_protocol.wifi_provisioning_available", return_value=True):
            await self.harness.command(self.protocol, {"id": "1", "type": "status"})
        response = await self.harness.wait_for_type("response")
        status = response["data"]
        self.assertEqual(response["id"], "1")
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["name"], "LM1 PRO")
        self.assertEqual(status["firmwareVersion"], SERVICE_VERSION)
        self.assertEqual(status["transport"], "ble")
        self.assertEqual(status["protocolVersion"], PROTOCOL_VERSION)
        self.assertTrue(status["wifiProvisioning"])
        self.assertEqual(status["captureBackend"], "simulator")
        self.assertFalse(status["cameraConnected"])

    async def test_auto_calibrate_exposure_hands_the_sweep_to_the_camera_loop(self) -> None:
        requested = []
        protocol = PinpointProtocol(
            self.harness.send,
            capture_delay=0.02,
            request_exposure_calibration=lambda: requested.append(True) or True,
        )
        with patch("pinpoint_protocol.uses_csi", return_value=True):
            await self.harness.command(protocol, {"id": "ax1", "type": "autoCalibrateExposure"})
        response = next(message for message in self.harness.messages if message.get("id") == "ax1")
        self.assertEqual(response["type"], "response")
        self.assertTrue(response["data"]["accepted"])
        self.assertEqual(len(requested), 1)
        await protocol.close()

    async def test_auto_calibrate_exposure_needs_a_camera_and_a_ready_device(self) -> None:
        protocol = PinpointProtocol(
            self.harness.send, capture_delay=0.02, request_exposure_calibration=lambda: True,
        )
        # No CSI camera at all.
        with patch("pinpoint_protocol.uses_csi", return_value=False):
            await self.harness.command(protocol, {"id": "ax2", "type": "autoCalibrateExposure"})
        error = next(message for message in self.harness.messages if message.get("id") == "ax2")
        self.assertEqual(error["type"], "error")
        self.assertIn("CSI camera", error["message"])

        # Armed: the sweep would fight the capture for the sensor.
        protocol.state = "armed"
        with patch("pinpoint_protocol.uses_csi", return_value=True):
            await self.harness.command(protocol, {"id": "ax3", "type": "autoCalibrateExposure"})
        error = next(message for message in self.harness.messages if message.get("id") == "ax3")
        self.assertEqual(error["type"], "error")
        self.assertIn("Stop tracking", error["message"])
        await protocol.close()

    async def test_auto_calibrate_exposure_reports_an_unavailable_camera_loop(self) -> None:
        protocol = PinpointProtocol(self.harness.send, capture_delay=0.02)
        with patch("pinpoint_protocol.uses_csi", return_value=True):
            await self.harness.command(protocol, {"id": "ax4", "type": "autoCalibrateExposure"})
        error = next(message for message in self.harness.messages if message.get("id") == "ax4")
        self.assertEqual(error["type"], "error")
        self.assertIn("unavailable", error["message"])
        await protocol.close()

    async def test_exposure_calibration_result_is_broadcast_with_fresh_status(self) -> None:
        await self.protocol.exposure_calibrated({"ok": True, "exposureUs": 90, "gain": 1.5})
        event = await self.harness.wait_for_type("exposureCalibration")
        self.assertEqual(event["data"]["exposureUs"], 90)
        status = await self.harness.wait_for_type("status")
        self.assertEqual(status["data"]["protocolVersion"], PROTOCOL_VERSION)

    async def test_status_mtu_sets_notification_chunk_size_and_resets_without_it(self) -> None:
        await self.harness.command(self.protocol, {"id": "m1", "type": "status", "mtu": 247})
        self.assertEqual(self.protocol.notification_chunk_bytes, 244)
        response = next(message for message in self.harness.messages if message.get("id") == "m1")
        self.assertEqual(response["data"]["notificationChunkBytes"], 244)
        await self.harness.command(self.protocol, {"id": "m2", "type": "status", "mtu": 185})
        self.assertEqual(self.protocol.notification_chunk_bytes, 182)
        await self.harness.command(self.protocol, {"id": "m3", "type": "status", "mtu": 9000})
        self.assertEqual(self.protocol.notification_chunk_bytes, 20)
        await self.harness.command(self.protocol, {"id": "m4", "type": "status", "mtu": 247})
        await self.harness.command(self.protocol, {"id": "m5", "type": "status"})
        self.assertEqual(self.protocol.notification_chunk_bytes, 20)
        chunks = encode_message_chunks({"payload": "x" * 1000}, 244)
        self.assertTrue(all(len(chunk) <= 244 for chunk in chunks))
        self.assertEqual(json.loads(b"".join(chunks)), {"payload": "x" * 1000})

    async def test_outgoing_unicode_message_uses_safe_twenty_byte_chunks(self) -> None:
        chunks = encode_message_chunks({"name": "Pinpoint · Pi"})
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        encoded = b"".join(chunks)
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn("·".encode(), encoded)
        self.assertEqual(json.loads(encoded), {"name": "Pinpoint · Pi"})

    async def test_configured_usb_camera_is_reported_without_enabling_real_measurements(self) -> None:
        with NamedTemporaryFile() as camera:
            os.environ["PINPOINT_CAMERA_DEVICE"] = camera.name
            status = self.protocol.status()

        self.assertTrue(status["cameraConnected"])
        self.assertEqual(status["captureBackend"], "simulator")
        self.assertEqual(status["fps"], 30)
        self.assertEqual(status["exposureUs"], 15700)
        self.assertEqual(status["calibrationVersion"], "NOT-CALIBRATED")

    async def test_camera_status_advertises_ble_preview_geometry(self) -> None:
        with NamedTemporaryFile() as camera:
            os.environ["PINPOINT_CAMERA_DEVICE"] = camera.name
            os.environ["PINPOINT_BLE_PREVIEW"] = "true"
            status = self.protocol.status()

        self.assertEqual(status["preview"]["transport"], "ble")
        self.assertEqual(status["preview"]["intervalMs"], 3000)
        self.assertEqual(status["preview"]["width"], 160)
        self.assertEqual(status["preview"]["height"], 120)
        self.assertEqual(status["preview"]["roi"], [0.05, 0.30, 0.95, 0.98])

    async def test_preview_event_is_base64_and_uses_normal_ble_framing(self) -> None:
        event = build_preview_event(b"jpeg-test")
        chunks = encode_message_chunks(event)
        decoded = json.loads(b"".join(chunks))

        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        self.assertEqual(decoded["type"], "preview")
        self.assertEqual(decoded["data"]["mimeType"], "image/jpeg")
        self.assertEqual(decoded["data"]["base64"], "anBlZy10ZXN0")

    async def test_apriltag_capture_returns_saved_metric_calibration(self) -> None:
        calibration = {
            "detected": True,
            "family": "tag36h11",
            "tagId": 0,
            "pixelsPerMm": 1.24,
            "rotationDeg": -2.5,
        }
        with patch("pinpoint_protocol.camera_diagnostics", return_value={"aprilTag": calibration}), patch(
            "pinpoint_protocol.capture_latest_apriltag_calibration",
            return_value=calibration,
        ):
            await self.harness.command(
                self.protocol,
                {"id": "tag-1", "type": "captureAprilTagCalibration"},
            )
        response = next(message for message in self.harness.messages if message.get("id") == "tag-1")
        self.assertEqual(response["data"], calibration)

    async def test_empty_plane_reset_invalidates_ground_geometry_and_target(self) -> None:
        self.protocol.reset_ball_calibration = lambda: True
        with patch('pinpoint_protocol.clear_apriltag_calibration') as clear_ground, patch(
            'pinpoint_protocol.clear_target_line'
        ) as clear_target:
            await self.harness.command(self.protocol, {'id':'reset-ground','type':'resetBallCalibration'})
        clear_ground.assert_called_once()
        clear_target.assert_called_once()
        self.protocol.state = 'processing'
        with patch('pinpoint_protocol.clear_apriltag_calibration') as clear_ground:
            await self.harness.command(self.protocol, {'id':'busy-reset','type':'resetBallCalibration'})
        clear_ground.assert_not_called()

    async def test_trigger_captures_usb_diagnostic_but_keeps_result_simulated(self) -> None:
        with NamedTemporaryFile() as camera:
            os.environ["PINPOINT_CAMERA_DEVICE"] = camera.name
            with patch(
                "pinpoint_protocol.capture_usb_test_frame",
                return_value=(1, 42),
            ) as capture:
                await self.harness.command(
                    self.protocol,
                    {"id": "camera-1", "type": "trigger"},
                )
                shot_event = await self.harness.wait_for_type("shot")

        capture.assert_called_once()
        self.assertEqual(shot_event["data"]["frameCount"], 1)
        self.assertEqual(shot_event["data"]["captureDurationMs"], 42)
        self.assertTrue(shot_event["data"]["simulated"])

    async def test_ball_presence_arms_then_removal_generates_result(self) -> None:
        await self.protocol.ball_presence_changed(True)
        presence = await self.harness.wait_for_type("ballPresence")
        self.assertTrue(presence["data"]["present"])
        self.assertEqual(self.protocol.state, "armed")
        armed_status = await self.harness.wait_for_type("status")
        self.assertEqual(armed_status["data"]["state"], "armed")

        self.harness.messages.clear()
        await self.protocol.ball_presence_changed(False, frame_count=14, duration_ms=620)
        presence = await self.harness.wait_for_type("ballPresence")
        self.assertFalse(presence["data"]["present"])
        self.assertEqual(self.protocol.state, "processing")
        shot_event = await self.harness.wait_for_type("shot")
        self.assertEqual(shot_event["data"]["frameCount"], 14)
        self.assertEqual(shot_event["data"]["captureDurationMs"], 620)
        self.assertTrue(shot_event["data"]["simulated"])

    async def test_preview_only_mode_does_not_open_second_camera_on_trigger(self) -> None:
        with patch.dict(os.environ, {"PINPOINT_AUTO_BALL_DETECTION": "false", "PINPOINT_BLE_PREVIEW": "true"}):
            with patch("pinpoint_protocol.capture_usb_test_frame") as capture:
                await self.harness.command(self.protocol, {"id": "preview-trigger", "type": "trigger"})
                shot = await self.harness.wait_for_type("shot")
        capture.assert_not_called()
        self.assertTrue(shot["data"]["simulated"])

    async def test_chunked_full_shot_command_produces_live_result(self) -> None:
        await self.harness.command(
            self.protocol,
            {"id": "2", "type": "arm", "clubId": "7-iron", "mode": "full-shot"},
        )
        self.assertEqual(self.protocol.state, "armed")
        self.harness.messages.clear()

        await self.harness.command(self.protocol, {"id": "3", "type": "trigger"})
        trigger_response = await self.harness.wait_for_type("response")
        self.assertTrue(trigger_response["data"]["accepted"])
        shot_event = await self.harness.wait_for_type("shot")
        self.assertEqual(shot_event["data"]["clubId"], "7-iron")
        self.assertTrue(shot_event["data"]["simulated"])
        self.assertEqual(self.protocol.state, "ready")

        self.harness.messages.clear()
        await self.harness.command(self.protocol, {"id": "4", "type": "listShots"})
        history = await self.harness.wait_for_type("response")
        self.assertEqual(len(history["data"]), 1)
        self.assertEqual(history["data"][0]["id"], shot_event["data"]["id"])

    async def test_selected_club_is_used_by_automatic_ball_capture(self) -> None:
        await self.harness.command(
            self.protocol,
            {"id": "club-1", "type": "setClub", "clubId": "7-iron"},
        )
        response = next(message for message in self.harness.messages if message.get("id") == "club-1")
        self.assertEqual(response["data"]["selectedClubId"], "7-iron")
        self.harness.messages.clear()
        await self.protocol.ball_presence_changed(True)
        await self.protocol.ball_presence_changed(
            False,
            frame_count=200,
            duration_ms=500,
            capture_id="capture-123",
            impact_frame_index=60,
        )
        shot_event = await self.harness.wait_for_type("shot")
        self.assertEqual(shot_event["data"]["clubId"], "7-iron")
        self.assertEqual(shot_event["data"]["captureId"], "capture-123")
        self.assertEqual(shot_event["data"]["impactFrameIndex"], 60)

    async def test_specific_capture_frame_is_returned(self) -> None:
        frame = {
            "mimeType": "image/jpeg",
            "base64": "anBlZw==",
            "captureId": "capture-123",
            "frameIndex": 60,
            "frameCount": 220,
            "timeMs": 300.0,
            "impactFrameIndex": 60,
        }
        with patch("pinpoint_protocol.capture_frame_preview", return_value=frame):
            await self.harness.command(
                self.protocol,
                {"id": "frame-1", "type": "captureFrame", "captureId": "capture-123", "frameIndex": 60},
            )
        response = next(message for message in self.harness.messages if message.get("id") == "frame-1")
        self.assertEqual(response["data"], frame)

    async def test_specific_capture_contact_sheet_is_returned(self) -> None:
        sheet = {"mimeType": "image/jpeg", "base64": "anBlZw==", "captureId": "capture-123"}
        with patch("pinpoint_protocol.capture_contact_sheet", return_value=sheet) as loader:
            await self.harness.command(
                self.protocol,
                {"id": "sheet-1", "type": "captureContactSheet", "captureId": "capture-123"},
            )
        loader.assert_called_once_with("capture-123")
        response = next(message for message in self.harness.messages if message.get("id") == "sheet-1")
        self.assertEqual(response["data"], sheet)

    async def test_putting_command_produces_putt(self) -> None:
        await self.harness.command(
            self.protocol,
            {"id": "5", "type": "arm", "clubId": "putter", "mode": "putting"},
        )
        self.harness.messages.clear()
        await self.harness.command(self.protocol, {"id": "6", "type": "trigger"})
        putt_event = await self.harness.wait_for_type("putt")
        self.assertTrue(putt_event["data"]["simulated"])
        self.assertIn("rollDistanceM", putt_event["data"])

    async def test_invalid_command_returns_correlated_error(self) -> None:
        await self.harness.command(self.protocol, {"id": "bad-1", "type": "nope"})
        error = await self.harness.wait_for_type("error")
        self.assertEqual(error["id"], "bad-1")
        self.assertIn("Unknown command", error["message"])

    async def test_set_exposure_applies_live_csi_value_and_returns_status(self) -> None:
        diagnostics = {"model": "ov9281", "fps": 200.0, "exposureUs": 180}
        control = {"configurable": True, "minUs": 20, "maxUs": 250, "stepUs": 10}
        with patch("pinpoint_protocol.uses_csi", return_value=True), patch(
            "pinpoint_protocol.camera_diagnostics", return_value=diagnostics,
        ), patch("pinpoint_protocol.exposure_configuration", return_value=control), patch(
            "pinpoint_protocol.set_camera_exposure", return_value={"exposureUs": 180, **control},
        ) as set_exposure:
            await self.harness.command(
                self.protocol,
                {"id": "exposure-1", "type": "setExposure", "exposureUs": 180},
            )

        response = next(message for message in self.harness.messages if message.get("id") == "exposure-1")
        set_exposure.assert_called_once_with(180)
        self.assertEqual(response["data"]["exposureUs"], 180)
        self.assertEqual(response["data"]["exposureControl"], control)
        self.assertTrue(any(message["type"] == "status" for message in self.harness.messages))

    async def test_set_exposure_is_rejected_while_armed(self) -> None:
        self.protocol.state = "armed"
        with patch("pinpoint_protocol.uses_csi", return_value=True), patch(
            "pinpoint_protocol.set_camera_exposure",
        ) as set_exposure:
            await self.harness.command(
                self.protocol,
                {"id": "exposure-armed", "type": "setExposure", "exposureUs": 180},
            )

        error = next(message for message in self.harness.messages if message.get("id") == "exposure-armed")
        set_exposure.assert_not_called()
        self.assertEqual(error["type"], "error")
        self.assertIn("Disarm", error["message"])

    async def test_set_gain_applies_live_csi_value_and_returns_status(self) -> None:
        diagnostics = {
            "model": "ov9281", "fps": 200.0, "exposureUs": 191,
            "gain": 2.5, "autoExposure": False,
        }
        control = {"configurable": True, "min": 1.0, "max": 16.0, "step": 0.25}
        with patch("pinpoint_protocol.uses_csi", return_value=True), patch(
            "pinpoint_protocol.camera_diagnostics", return_value=diagnostics,
        ), patch("pinpoint_protocol.gain_configuration", return_value=control), patch(
            "pinpoint_protocol.set_camera_gain", return_value={"gain": 2.5, **control},
        ) as set_gain:
            await self.harness.command(
                self.protocol,
                {"id": "gain-1", "type": "setGain", "gain": 2.5},
            )

        response = next(message for message in self.harness.messages if message.get("id") == "gain-1")
        set_gain.assert_called_once_with(2.5)
        self.assertEqual(response["data"]["camera"]["gain"], 2.5)
        self.assertEqual(response["data"]["gainControl"], control)
        self.assertTrue(any(message["type"] == "status" for message in self.harness.messages))

    async def test_set_gain_rejects_non_finite_value(self) -> None:
        with patch("pinpoint_protocol.uses_csi", return_value=True), patch(
            "pinpoint_protocol.set_camera_gain",
        ) as set_gain:
            await self.harness.command(
                self.protocol,
                {"id": "gain-bad", "type": "setGain", "gain": float("nan")},
            )

        error = next(message for message in self.harness.messages if message.get("id") == "gain-bad")
        set_gain.assert_not_called()
        self.assertEqual(error["type"], "error")
        self.assertIn("finite", error["message"])

    async def test_wifi_scan_returns_networks_over_existing_response_channel(self) -> None:
        networks = [
            {
                "ssid": "Jakin SUPER_5G",
                "signal": 97,
                "security": "WPA2",
                "secure": True,
                "supported": True,
                "connected": False,
            }
        ]
        with patch("pinpoint_protocol.scan_wifi_networks", return_value=networks):
            await self.harness.command(self.protocol, {"id": "wifi-1", "type": "wifiScan"})

        response = await self.harness.wait_for_type("response")
        self.assertEqual(response["id"], "wifi-1")
        self.assertEqual(response["data"], networks)

    async def test_capture_history_is_limited_to_newest_ten_records(self) -> None:
        self.protocol.captures = [
            {"id": f"capture-{index}", "track": [], "image": {"mimeType": "image/jpeg", "base64": "x"}}
            for index in range(12)
        ]

        await self.harness.command(self.protocol, {"id": "history-1", "type": "listCaptures"})

        response = next(message for message in self.harness.messages if message.get("id") == "history-1")
        self.assertEqual(len(response["data"]), 10)
        self.assertEqual(response["data"][0]["id"], "capture-0")
        self.assertEqual(response["data"][-1]["id"], "capture-9")

    async def test_wifi_connect_never_returns_password(self) -> None:
        wifi_status = {
            "available": True,
            "connected": True,
            "interface": "wlan0",
            "ssid": "Jakin SUPER_5G",
            "ipAddress": "192.168.8.42",
        }
        with patch("pinpoint_protocol.connect_wifi", return_value=wifi_status) as connect:
            await self.harness.command(
                self.protocol,
                {
                    "id": "wifi-2",
                    "type": "wifiConnect",
                    "ssid": "Jakin SUPER_5G",
                    "password": "super-secret",
                    "hidden": False,
                },
            )

        response = await self.harness.wait_for_type("response")
        connect.assert_called_once_with("Jakin SUPER_5G", "super-secret", hidden=False)
        self.assertEqual(response["data"], wifi_status)
        self.assertNotIn("super-secret", json.dumps(self.harness.messages))


if __name__ == "__main__":
    unittest.main()
