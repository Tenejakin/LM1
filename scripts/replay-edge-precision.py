"""Replay every saved capture and report edge-precision figures, for before/after comparisons.

Usage: python scripts/replay-edge-precision.py <label>
Writes output/edge-precision/<label>.json. Captures without a saved armed-ball
reference still replay; the tracker then builds its reference from the burst.
"""
from collections import deque
from pathlib import Path
import json
import os
import sys

import cv2

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'raspberry_pi'))
from ball_detector import RollingFrameBuffer, analyze_departure  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else 'run'
out = root / 'output/edge-precision'
out.mkdir(parents=True, exist_ok=True)
os.environ['PINPOINT_INTRINSICS_PATH'] = str(root / 'tmp/ir-latest-review/intrinsics.json')
os.environ['PINPOINT_TARGET_LINE_PATH'] = str(out / 'unset-target.json')
os.environ['PINPOINT_CLUB_MARKER_PATH'] = str(out / 'unset-club.json')
os.environ.setdefault('PINPOINT_ANALYSIS_DENOISE', 'none')

results = {}
for capture in sorted((root / 'tmp').glob('capture-*')):
    manifest_path = capture / 'capture.json'
    if not manifest_path.exists():
        continue
    manifest = json.loads(manifest_path.read_text())
    if 'frameTimesMs' not in manifest or 'ballBounds' not in manifest:
        results[capture.name] = {'skipped': 'manifest lacks frame times or ball bounds'}
        continue
    buffer = RollingFrameBuffer(manifest['frameCount'])
    buffer.frames = deque((t / 1000, cv2.imread(str(capture / f'frame-{i:04d}.jpg'), 0))
                          for i, t in enumerate(manifest['frameTimesMs']))
    buffer.metadata = deque(manifest.get('frameMetadata', []))
    reference_path = capture / 'armed-ball-reference.png'
    reference = cv2.imread(str(reference_path), 0) if reference_path.exists() else None
    try:
        analysis = analyze_departure(buffer, tuple(manifest['ballBounds']), manifest['coarseDepartureFrameIndex'], reference)
    except Exception as error:  # A replay report should list failures, not stop at the first.
        results[capture.name] = {'error': f'{type(error).__name__}: {error}'}
        continue
    measured = analysis.get('measurements') or {}
    metrics = measured.get('metrics', {})
    fit = measured.get('diagnostics', {}).get('trajectoryFit') or {}
    results[capture.name] = {
        'failure': measured.get('failure'),
        'tagErrorPx': measured.get('tagPoseReprojectionErrorPx'),
        'fitRmsPx': fit.get('rmsPx'),
        'radiusRmsPx': fit.get('radiusRmsPx'),
        'radiusObservations': fit.get('radiusObservations'),
        'edgeFitFrames': fit.get('edgeFitFrames'),
        'edgeRmsPx': fit.get('edgeRmsPx'),
        'ballSizeRatio': fit.get('ballSizeRatio'),
        'fitFrames': fit.get('frames'),
        'model': fit.get('model'),
        'fitFailure': fit.get('failure'),
        'speedMps': (metrics.get('ballSpeedMps') or {}).get('value'),
        'speedSigmaMps': fit.get('speedSigmaMps'),
        'launchDeg': (metrics.get('launchAngleDeg') or {}).get('value'),
        'flightLaunchSigmaDeg': fit.get('flightLaunchSigmaDeg'),
        'headingSigmaDeg': fit.get('headingSigmaDeg'),
        'status': {key: value.get('status') for key, value in metrics.items() if value.get('value') is not None},
    }
(out / f'{label}.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
