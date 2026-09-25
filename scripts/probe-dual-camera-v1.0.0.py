"""Short hardware diagnostic; run with the LM1 service stopped."""
import json
import time
import numpy as np
import cv2
from picamera2 import Picamera2
from libcamera import controls

cameras = []
try:
    for index in (0, 1):
        camera = Picamera2(index)
        cameras.append(camera)
        camera.configure(camera.create_video_configuration(
            main={"size": (640, 400), "format": "RGB888"},
            sensor={"output_size": (640, 400), "bit_depth": 10},
            controls={"FrameRate": 200, "AeEnable": False, "ExposureTime": 75,
                      "AnalogueGain": 4.0, "SyncMode": controls.rpi.SyncModeEnum.Server if index == 0 else controls.rpi.SyncModeEnum.Client},
            buffer_count=8))
    cameras[1].start()
    cameras[0].start()
    timestamps = [[], []]
    deadline = time.monotonic() + 9
    metadata = [{}, {}]
    frames = [None, None]
    while time.monotonic() < deadline:
        jobs = [c.capture_request(wait=False) for c in cameras]
        for i, (camera, job) in enumerate(zip(cameras, jobs)):
            request = camera.wait(job, timeout=2)
            try:
                metadata[i] = request.get_metadata()
                frames[i] = request.make_array("main")
                timestamps[i].append(metadata[i]["SensorTimestamp"])
            finally:
                request.release()
    for i in (0, 1):
        cv2.imwrite('/tmp/lm1-camera-%d-v1.0.0.jpg' % i, frames[i])
    first, second = [np.array(t[-400:]) for t in timestamps]
    offsets = np.min(np.abs(first[:, None] - second[None, :]), axis=1) / 1000
    print(json.dumps({"frames": [len(t) for t in timestamps],
                      "metadata": metadata, "brightness": [float(f.mean()) for f in frames],
                      "offsetUsP50": float(np.median(offsets)), "offsetUsP95": float(np.percentile(offsets,95)),
                      "offsetUsMax": float(offsets.max())}, default=str))
finally:
    for camera in reversed(cameras):
        try:
            camera.stop()
        finally:
            camera.close()
