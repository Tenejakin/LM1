"""Regression checks for the September 23 ten-capture measurement audit."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_quality import shot_evidence
from target_line import load_target_line, save_target_line
from pinpoint_protocol import PinpointProtocol


class ReliabilityTests(unittest.TestCase):
    def test_long_ball_roll_without_club_is_not_swing_evidence(self):
        measurements = {"diagnostics": {"motionTrackedFrames": 234,
                        "clubSilhouette": {"acceptedFrames": 0}, "stereo": {"frames": 48}},
                        "metrics": {"ballSpeedMps": {"value": .2}}}
        evidence = shot_evidence(measurements)
        self.assertEqual(evidence["status"], "motion-only")
        capture = PinpointProtocol._capture_summary({"measurements": measurements})
        self.assertEqual(capture["measurements"]["shotEvidence"], evidence)

    def test_gentle_chip_can_have_swing_evidence_without_speed_threshold(self):
        evidence = shot_evidence({"diagnostics": {"clubSilhouette": {"acceptedFrames": 5}},
                                  "metrics": {"ballSpeedMps": {"value": .4}}})
        self.assertEqual(evidence["status"], "club-motion-observed")

    def test_full_shot_rejects_movement_that_cannot_be_a_strike(self):
        """Measured on 2026-09-24/25: 0.1-0.9 m/s, 0° launch, 168-175° direction."""
        def capture(speed, launch, direction, club_frames):
            return {"diagnostics": {"clubSilhouette": {"acceptedFrames": club_frames}},
                    "metrics": {"ballSpeedMps": {"value": speed}, "launchAngleDeg": {"value": launch},
                                "startDirectionDeg": {"value": direction}}}
        self.assertEqual(shot_evidence(capture(0.7, 0.0, 167.7, 6), "full-shot")["status"], "not-a-strike")
        self.assertEqual(shot_evidence(capture(12.0, 20.0, 80.4, 6), "full-shot")["status"], "not-a-strike")
        self.assertEqual(shot_evidence(capture(4.0, 0.0, 2.0, 0), "full-shot")["status"], "not-a-strike")
        # A struck ball whose club was not tracked is kept, not discarded.
        self.assertEqual(shot_evidence(capture(18.3, 5.7, -2.4, 2), "full-shot")["status"], "motion-only")
        self.assertEqual(shot_evidence(capture(12.2, 29.3, -2.4, 5), "full-shot")["status"], "club-motion-observed")
        # Putts are slow by design and are never classified this way.
        self.assertEqual(shot_evidence(capture(0.7, 0.0, 1.0, 0), "putting")["status"], "motion-only")
        # A tracking failure is not a classification.
        self.assertEqual(shot_evidence(capture(None, None, None, 0), "full-shot")["status"], "motion-only")

    def test_summary_classifies_with_the_capture_mode(self):
        measurements = {"diagnostics": {"clubSilhouette": {"acceptedFrames": 6}},
                        "metrics": {"ballSpeedMps": {"value": .3}, "launchAngleDeg": {"value": 0.0},
                                    "startDirectionDeg": {"value": 1.5}}}
        summary = PinpointProtocol._capture_summary({"mode": "full-shot", "measurements": measurements})
        self.assertEqual(summary["measurements"]["shotEvidence"]["status"], "not-a-strike")

    def test_old_target_line_is_invalid_after_ground_recalibration(self):
        with TemporaryDirectory() as temporary, patch.dict(os.environ, {"PINPOINT_TARGET_LINE_PATH": str(Path(temporary) / "target.json")}):
            with patch("apriltag_calibration.load_apriltag_calibration", return_value={"capturedAt": "2026-09-23T13:00:00Z"}):
                saved = save_target_line(-37.8, 9, .257)
                self.assertEqual(load_target_line(), saved)
            with patch("apriltag_calibration.load_apriltag_calibration", return_value={"capturedAt": "2026-09-23T14:23:24Z"}):
                self.assertIsNone(load_target_line())
            # Version 3.15 records predate the calibration association field.
            saved.pop("groundCalibrationAt")
            saved["capturedAt"] = "2026-09-23T14:19:15Z"
            Path(temporary, "target.json").write_text(json.dumps(saved))
            with patch("apriltag_calibration.load_apriltag_calibration", return_value={"capturedAt": "2026-09-23T14:23:24Z"}):
                self.assertIsNone(load_target_line())


if __name__ == "__main__":
    unittest.main()
