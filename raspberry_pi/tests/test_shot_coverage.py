"""Frame budget per shot type, using the lens and ground pose from a real 242 fps capture."""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shot_coverage  # noqa: E402
from pinpoint_protocol import PinpointProtocol  # noqa: E402
from tests.test_protocol import ProtocolHarness  # noqa: E402

# Lower camera ~21 cm above the mat, pitched 31 deg, ball ~34 cm away (capture 1789515451301879262).
POSE = {
    "imageSize": [640, 400],
    "cameraMatrix": [[565.5682086088923, 0.0, 333.99531573783196],
                     [0.0, 555.3127902177599, 198.2253920075832], [0.0, 0.0, 1.0]],
    "distCoeffs": [-0.41222274907597806, -0.15125792643235048, 0.00618740376985397,
                   -0.005089721793506736, 0.8164134693071088],
    "rotation": [[0.9919329622586305, -0.1258816678821431, 0.01492662306176272],
                 [-0.05207136607489521, -0.5119856261170791, -0.8574143056216154],
                 [0.11557495931174876, 0.8497202624044647, -0.5144102491585635]],
    "translationM": [-0.2537128788493225, -0.028105483059967386, 0.4475133389617133],
}
RESTING_BALL = (329.0 / 640, 220.6 / 400)


def moved_back(pose: dict[str, Any], factor: float) -> dict[str, Any]:
    """Same aim, camera pulled back along its optical axis to ``factor`` x the ball distance."""
    rotation = np.asarray(pose["rotation"])
    translation = np.asarray(pose["translationM"])
    centre = -rotation.T @ translation
    axis = rotation.T @ np.array([0.0, 0.0, 1.0])
    rest = np.array([0.235, -0.139, 0.021335])
    distance = float((rotation @ rest + translation)[2])
    new_centre = centre - axis * distance * (factor - 1)
    return {**pose, "translationM": (-rotation @ new_centre).tolist()}


def by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {shot["id"]: shot for shot in result["shots"]}


class ShotCoverageTests(unittest.TestCase):
    def test_close_camera_covers_putts_but_not_full_swings(self) -> None:
        result = shot_coverage.shot_coverage(POSE, 241.6, RESTING_BALL)
        shots = by_id(result)

        self.assertEqual(shots["putt"]["rating"], "good")
        self.assertEqual(shots["driver"]["rating"], "insufficient")
        self.assertLess(shots["driver"]["framesMin"], shot_coverage.MIN_FRAMES)
        self.assertAlmostEqual(shots["driver"]["travelPerFrameMm"], 289.7, places=1)
        self.assertEqual(result["headingSource"], "camera-axis")
        self.assertTrue(any("behind the ball" in note for note in result["notes"]))
        self.assertTrue(any("Full swings" in note for note in result["notes"]))

    def test_placing_the_ball_upstream_adds_downrange_path(self) -> None:
        centred = shot_coverage.shot_coverage(POSE, 241.6, RESTING_BALL)
        upstream = shot_coverage.shot_coverage(POSE, 241.6, (60 / 640, RESTING_BALL[1]))

        self.assertGreater(upstream["downrangePathMm"], 1.5 * centred["downrangePathMm"])
        self.assertLess(upstream["behindBallMm"], centred["behindBallMm"])

    def test_about_a_metre_away_with_the_ball_upstream_gives_a_driver_enough_frames(self) -> None:
        near = shot_coverage.shot_coverage(POSE, 241.6, RESTING_BALL)
        upstream = (0.1, RESTING_BALL[1])
        far_centred = shot_coverage.shot_coverage(moved_back(POSE, 3.0), 241.6, RESTING_BALL)
        far_upstream = shot_coverage.shot_coverage(moved_back(POSE, 3.0), 241.6, upstream)

        # Distance alone is not enough while half the view is behind the ball.
        self.assertLess(by_id(far_centred)["driver"]["framesMin"], shot_coverage.MIN_FRAMES)
        self.assertGreaterEqual(by_id(far_upstream)["driver"]["framesMin"], shot_coverage.MIN_FRAMES)
        self.assertGreater(far_upstream["cameraToBallMm"], 900)
        self.assertGreater(far_upstream["ballDiameterPx"], 20)
        self.assertLess(far_upstream["ballDiameterPx"], near["ballDiameterPx"] / 2.5)

    def test_higher_frame_rate_increases_frames_for_the_same_view(self) -> None:
        slow = by_id(shot_coverage.shot_coverage(POSE, 120, RESTING_BALL))["putt"]
        fast = by_id(shot_coverage.shot_coverage(POSE, 240, RESTING_BALL))["putt"]

        self.assertAlmostEqual(fast["framesMin"] / max(slow["framesMin"], 1), 2, delta=0.2)

    def test_placement_is_assumed_and_said_so_without_a_detected_ball(self) -> None:
        result = shot_coverage.shot_coverage(POSE, 241.6)

        self.assertEqual(result["ballSource"], "assumed-placement")
        self.assertTrue(any("assumed" in note for note in result["notes"]))

    def test_ball_outside_the_view_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not fully inside"):
            shot_coverage.shot_coverage(POSE, 241.6, (0.001, 0.55))

    def test_unknown_frame_rate_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "frame rate"):
            shot_coverage.shot_coverage(POSE, 0, RESTING_BALL)


class ShotCoverageCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["PINPOINT_CAPTURE_BACKEND"] = "simulator"
        self.harness = ProtocolHarness()
        self.protocol = PinpointProtocol(self.harness.send, capture_delay=0.02)

    async def asyncTearDown(self) -> None:
        await self.protocol.close()

    async def _reply(self, request_id: str) -> dict[str, Any]:
        for _ in range(50):
            match = next((m for m in self.harness.messages if m.get("id") == request_id), None)
            if match:
                return match
            await asyncio.sleep(0.01)
        raise AssertionError(f"No reply to {request_id}")

    async def test_needs_a_saved_ground_calibration(self) -> None:
        with patch("pinpoint_protocol.load_apriltag_calibration", return_value=None):
            await self.harness.command(self.protocol, {"id": "s1", "type": "shotCoverage"})

        reply = await self._reply("s1")
        self.assertEqual(reply["type"], "error")
        self.assertIn("AprilTag ground calibration", reply["message"])

    async def test_uses_the_live_ball_and_paired_frame_rate(self) -> None:
        diagnostics = {"pairedFps": 241.6, "fps": 242.1,
                       "ballDetection": {"state": "detected", "bounds": [0.48, 0.52, 0.07, 0.07]}}
        with patch("pinpoint_protocol.load_apriltag_calibration", return_value={"groundPose": POSE}), patch(
            "pinpoint_protocol.camera_diagnostics", return_value=diagnostics
        ):
            await self.harness.command(self.protocol, {"id": "s2", "type": "shotCoverage"})

        reply = await self._reply("s2")
        self.assertEqual(reply["type"], "response")
        self.assertEqual(reply["data"]["ballSource"], "live-ball")
        self.assertEqual(reply["data"]["fps"], 241.6)
        self.assertEqual([shot["id"] for shot in reply["data"]["shots"]], ["putt", "wedge", "iron", "driver"])


if __name__ == "__main__":
    unittest.main()
