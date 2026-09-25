import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stereo_calibration as sc


class StereoCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"PINPOINT_STEREO_PATH": self.temp.name})
        self.env.start()
        self.k = np.array([[570., 0., 320.], [0., 570., 200.], [0., 0., 1.]])
        self.d = np.zeros(5)
        self.lenses = [{"cameraMatrix": self.k.tolist(), "distCoeffs": self.d.tolist()} for _ in range(2)]
        self.r = cv2.Rodrigues(np.array([.03, -.04, .02]))[0]
        self.t = np.array([.005, -.085, .004])

    def tearDown(self):
        sc.pause_capture(False)
        self.env.stop()
        self.temp.cleanup()

    def data(self):
        board = {"columns": 5, "rows": 5, "squareMm": 25}
        grid = sc.grid_for(board)
        pairs = []
        for i in range(20):
            rv = np.array([.25 * np.sin(i), .3 * np.cos(i * .6), .05 * i])
            r1 = cv2.Rodrigues(rv)[0]
            t1 = np.array([-.13 + .018 * (i % 10), -.06 + .013 * (i % 5), .43 + .018 * (i % 7)])
            p1 = cv2.projectPoints(grid, rv, t1, self.k, self.d)[0].reshape(-1, 2)
            p2 = cv2.projectPoints(grid, cv2.Rodrigues(self.r @ r1)[0], self.r @ t1 + self.t, self.k, self.d)[0].reshape(-1, 2)
            p2 = sc.variants(p2, board)[i % 4]
            pairs.append({"points": [p1.tolist(), p2.tolist()], "offsetUs": 14})
        return {"id": "synthetic", "board": board, "lenses": self.lenses, "imageSize": [640, 400],
                "cameraIndices": [0, 1], "fingerprint": sc.fingerprint(self.lenses, [640, 400], [0, 1]), "pairs": pairs}

    def test_recovers_fixed_pair_with_rotated_corner_order_and_holdout(self):
        result = sc.solve_data(self.data())
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual((result["trainingPairs"], result["validationPairs"]), (15, 5))
        np.testing.assert_allclose(result["rotation"], self.r, atol=1e-5)
        np.testing.assert_allclose(result["translationM"], self.t, atol=1e-5)
        self.assertLess(result["validationRmsPx"], .001)

    def test_holdout_errors_do_not_get_fitted_away(self):
        data = self.data()
        for pair in data["pairs"][3::4]:
            pair["points"][1] = (np.asarray(pair["points"][1]) + [8, 0]).tolist()
        result = sc.solve_data(data)
        self.assertFalse(result["passed"])
        self.assertLess(result["rmsPx"], .001)
        self.assertGreater(result["validationRmsPx"], 7)

    def test_duplicate_pose_dataset_and_short_dataset_rejected(self):
        data = self.data()
        with self.assertRaisesRegex(ValueError, "at least"):
            sc.solve_data({**data, "pairs": data["pairs"][:10]})
        with self.assertRaisesRegex(ValueError, "variety"):
            sc.solve_data({**data, "pairs": [data["pairs"][0]] * 16})

    def test_activation_is_explicit_and_rejects_stale_lenses(self):
        sc.start(5, 5, 25)
        path, session = sc.session()
        data = self.data()
        data["id"] = session["id"]
        sc.write(path / "session.json", data)
        result = sc.solve()["candidate"]
        self.assertIsNone(sc.status()["active"])
        with patch.object(sc, "lens_inputs", return_value=self.lenses):
            with self.assertRaisesRegex(ValueError, "candidate"):
                sc.activate("wrong-id", [0, 1])
            with self.assertRaisesRegex(ValueError, "changed"):
                sc.activate(result["id"], [1, 0])
            sc.activate(result["id"], [0, 1])
            sc.activate(result["id"], [0, 1])
        self.assertEqual(sc.status()["active"]["id"], result["id"])
        self.assertEqual(len(list((sc.root() / "backups").glob("*.json"))), 1)
        lower_r = cv2.Rodrigues(np.array([.6, .2, .1]))[0]
        lower_t = np.array([.1, .2, .6])
        pose = sc.fixed_secondary_pose((self.k, self.d, lower_r, lower_t), (self.k, self.d), [640, 400], [0, 1])
        np.testing.assert_allclose(pose["rotation"], self.r @ lower_r, atol=1e-5)
        np.testing.assert_allclose(pose["translation"], self.r @ lower_t + self.t, atol=1e-5)
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            sc.fixed_secondary_pose((self.k * 1.01, self.d, lower_r, lower_t), (self.k, self.d), [640, 400], [0, 1])
        sc.start(5, 5, 25)
        self.assertEqual(sc.status()["active"]["id"], result["id"])

    def test_capture_uses_sensor_time_and_requires_both_boards(self):
        sc.start(5, 5, 25)
        image = np.zeros((400, 640, 3), np.uint8)
        with self.assertRaisesRegex(ValueError, "timestamps"):
            sc.capture_pair(image, image, [None, 100], [0, 1])
        with self.assertRaisesRegex(ValueError, "timing"):
            sc.capture_pair(image, image, [1e9, 1e9 + 300000], [0, 1])
        with patch.object(sc, "lens_inputs", return_value=self.lenses), patch.object(cv2, "findChessboardCornersSB", return_value=(False, None)):
            with self.assertRaisesRegex(ValueError, "not found"):
                sc.capture_pair(image, image, [1e9, 1e9 + 14000], [0, 1])
        self.assertEqual(sc.status()["pairs"], 0)

    def test_capture_persists_pair_and_rejects_same_pose(self):
        sc.start(5, 5, 25)
        image = np.zeros((400, 640, 3), np.uint8)
        points = np.array([[100+x*20, 100+y*20] for y in range(5) for x in range(5)], np.float32).reshape(-1, 1, 2)
        with patch.object(sc, "lens_inputs", return_value=self.lenses), patch.object(cv2, "findChessboardCornersSB", return_value=(True, points)):
            self.assertEqual(sc.capture_pair(image, image, [1e9, 1e9 + 14000], [0, 1])["pairs"], 1)
            with self.assertRaisesRegex(ValueError, "similar"):
                sc.capture_pair(image, image, [2e9, 2e9 + 14000], [0, 1])
        path, _ = sc.session()
        self.assertEqual(len(list(path.glob("*.png"))), 2)

    def test_bad_board_parameters_rejected(self):
        for args in ((2, 5, 25), (5.5, 5, 25), (5, 5, float("nan")), (5, 5, 0)):
            with self.assertRaises(ValueError):
                sc.start(*args)


class StereoProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from pinpoint_protocol import PinpointProtocol
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"PINPOINT_STEREO_PATH": self.temp.name,
                                          "PINPOINT_CAPTURE_BACKEND": "simulator"})
        self.env.start()
        self.messages = []
        async def send(value):
            self.messages.append(value)
        self.protocol = PinpointProtocol(send)

    async def asyncTearDown(self):
        await self.protocol.close()
        sc.pause_capture(False)
        self.env.stop()
        self.temp.cleanup()

    async def command(self, action, **kwargs):
        import json
        await self.protocol.receive_chunk((json.dumps({"id": "stereo", "type": "stereoCalibration",
                                                       "action": action, **kwargs}) + "\n").encode())
        return self.messages[-1]

    async def test_start_status_end_and_board_validation(self):
        self.assertEqual((await self.command("start", columns=2))["type"], "error")
        result = await self.command("start", columns=5, rows=5, squareMm=25)
        self.assertEqual(result["data"]["pairs"], 0)
        self.assertTrue(sc.capture_paused())
        await self.protocol.ball_presence_changed(True)
        self.assertFalse(self.protocol.ball_present)
        self.assertEqual((await self.command("solve"))["type"], "error")
        await self.command("end")
        self.assertFalse(sc.capture_paused())

    async def test_capture_reply_waits_for_camera_callback(self):
        async def complete():
            await asyncio.sleep(.01)
            await self.protocol.calibration_image_captured({"stereo": True, "data": {"pairs": 1}})
        def request(camera):
            self.assertEqual(camera, "stereo")
            asyncio.create_task(complete())
            return True
        self.protocol.request_calibration_capture = request
        response = await self.command("capture")
        self.assertEqual(response["data"]["pairs"], 1)
        self.assertFalse(any(m["type"] == "calibrationImage" for m in self.messages))

    async def test_camera_error_propagates_and_busy_flag_clears(self):
        def request(camera):
            asyncio.create_task(self.protocol.calibration_image_captured({"stereo": True, "error": "Top board missing"}))
            return True
        self.protocol.request_calibration_capture = request
        response = await self.command("capture")
        self.assertEqual(response["type"], "error")
        self.assertIn("Top board missing", response["message"])
        self.assertFalse(self.protocol._stereo_busy)

    async def test_processing_shot_blocks_calibration(self):
        self.protocol.state = "processing"
        self.assertEqual((await self.command("start"))["type"], "error")
        self.assertFalse(sc.capture_paused())


if __name__ == "__main__":
    unittest.main()
