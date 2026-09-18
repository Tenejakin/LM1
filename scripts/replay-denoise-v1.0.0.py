"""Replay latest downloaded shot through identical raw/filtered analysis."""
from pathlib import Path
import os, sys, json, time
import cv2
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'raspberry_pi'))
from ball_detector import RollingFrameBuffer, analyze_departure
capture = root / 'tmp/capture-1789515451301879262'
out = root / 'output/shot-denoise-v1.0.0'
out.mkdir(parents=True, exist_ok=True)
m = json.loads((capture / 'capture.json').read_text())
os.environ['PINPOINT_INTRINSICS_PATH'] = str(root / 'tmp/ir-latest-review/intrinsics.json')
os.environ['PINPOINT_TARGET_LINE_PATH'] = str(out / 'unset-target.json')
os.environ['PINPOINT_CLUB_MARKER_PATH'] = str(out / 'unset-club.json')
summary = {}
for mode in ('none', 'bilateral'):
    os.environ['PINPOINT_ANALYSIS_DENOISE'] = mode
    b = RollingFrameBuffer(m['frameCount'])
    # Populate deques directly to retain the exact saved sensor-relative timestamps.
    from collections import deque
    b.frames = deque((t / 1000, cv2.imread(str(capture / f'frame-{i:04d}.jpg'), 0))
                     for i,t in enumerate(m['frameTimesMs']))
    b.metadata = deque(m['frameMetadata'])
    reference = cv2.imread(str(capture / 'armed-ball-reference.png'), 0)
    started = time.perf_counter()
    a = analyze_departure(b, tuple(m['ballBounds']), m['coarseDepartureFrameIndex'], reference)
    elapsed = time.perf_counter() - started
    a.pop('image', None)
    (out / (mode + '.json')).write_text(json.dumps(a, indent=2))
    measured = a['measurements']
    summary[mode] = {'elapsedSeconds': elapsed, 'firstMovingFrame': a['firstMovingFrameIndex'],
        'imageMatches': len(a['track']), 'points3d': len(measured['ballTrack3d']),
        'speedMps': measured['metrics']['ballSpeedMps']['value'],
        'launchDeg': measured['metrics']['launchAngleDeg']['value'],
        'spinRpm': measured['metrics']['spinRpm']['value'],
        'trajectoryFit': measured.get('diagnostics', {}).get('trajectoryFit'),
        'tagErrorPx': measured.get('tagPoseReprojectionErrorPx'),
        'preprocessing': measured['diagnostics']['preprocessing']}
print(json.dumps(summary, indent=2))
(out / 'comparison.json').write_text(json.dumps({'version':'1.0.0', 'captureId':capture.name,
    'results':summary, 'limitations':'JPEG replay; no physical ground truth. Target heading omitted equally.'}, indent=2))
