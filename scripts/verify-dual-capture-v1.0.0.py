"""Exercise real paired acquisition, saving and replay with LM1 stopped.

Usage: python verify-dual-capture-v1.0.0.py /path/to/raspberry_pi /path/to/evidence
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, sys.argv[1])
os.environ.update(PINPOINT_CAMERA_SOURCE='csi', PINPOINT_DUAL_CAMERA='true',
                  PINPOINT_CAMERA_INDEX='0', PINPOINT_SECONDARY_CAMERA_INDEX='1',
                  PINPOINT_CAMERA_RESOLUTION='640x400',
                  PINPOINT_ROLLING_CAPTURE_PATH=sys.argv[2])
os.environ.setdefault('PINPOINT_CAMERA_FPS', '200')
from camera_source import DualCsiCapture, camera_diagnostics
from ball_detector import BallMonitor, RollingFrameBuffer, capture_frame_preview

buffer = RollingFrameBuffer(325)
camera = DualCsiCapture()
try:
    start = time.monotonic()
    count = 0
    while time.monotonic() - start < 10:
        ok, frame = camera.read()
        assert ok
        BallMonitor._append_capture_frame(buffer, camera, frame)
        count += 1
    folder = Path(sys.argv[2]) / ('capture-%d' % time.time_ns())
    buffer.save(folder, int(os.environ['PINPOINT_CAMERA_FPS']), 160)
    replay = capture_frame_preview(folder.name, 160)
    assert replay.get('secondaryBase64')
    manifest = json.loads((folder / 'capture.json').read_text())
    summary = {'version': '1.0.0', 'purpose': 'Hardware diagnostic, not a golf shot',
               'camera': camera_diagnostics(), 'capturePath': str(folder),
               'observedFps': manifest['measuredFps'], 'framesPerCamera': manifest['frameCount'],
               'durationMs': manifest['durationMs'], 'maxAbsOffsetUs': manifest['dualCamera']['maxAbsOffsetUs'],
               'medianAbsOffsetUs': manifest['dualCamera']['medianAbsOffsetUs'],
               'brightness': [float(buffer.frames[-1][1].mean()), float(buffer.secondary.frames[-1][1].mean())],
               'pairedReplayVerified': True}
    Path(sys.argv[2], 'verification-v1.0.0.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
finally:
    camera.release()
