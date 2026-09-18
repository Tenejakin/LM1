"""v1.0.0: replay a saved burst and report measurement limits without changing it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'raspberry_pi'))
from launch_measurements import RADIUS, ball_background, measure_launch

VERSION = '1.0.0'


def point_on_ball_center_plane(pixel, matrix, distortion, rotation, translation):
    uv = cv2.undistortPoints(np.asarray([[pixel]], np.float64), matrix, distortion).reshape(2)
    camera = -rotation.T @ translation
    ray = rotation.T @ np.array([*uv, 1.])
    if abs(ray[2]) < 1e-8:
        return None
    scale = (RADIUS - camera[2]) / ray[2]
    return camera + ray * scale if scale > 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--intrinsics', type=Path, required=True,
                        help='Lens calibration applicable to this capture; record is preserved in the report.')
    parser.add_argument('--tag-size-mm', type=float, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.capture / 'capture.json').read_text())
    original = json.loads((args.capture / 'analysis.json').read_text())
    times = np.asarray(manifest['frameTimesMs'], float) / 1000
    frames = [(float(t), cv2.imread(str(args.capture / f'frame-{i:04d}.jpg'), 0)) for i, t in enumerate(times)]
    if any(frame is None for _, frame in frames):
        raise ValueError('Capture frames are incomplete.')
    impact = manifest['firstMovingFrameIndex']
    impact = manifest['impactFrameIndex'] if impact is None else impact
    metadata = manifest.get('frameMetadata', [])
    exposure = max((item.get('ExposureTime', 0) for item in metadata), default=0)
    os.environ['PINPOINT_INTRINSICS_PATH'] = str(args.intrinsics.resolve())
    os.environ['PINPOINT_APRILTAG_SIZE_MM'] = str(args.tag_size_mm)
    # Do not apply today's target heading to old footage.
    os.environ['PINPOINT_TARGET_LINE_PATH'] = str(args.output / 'unset-target-line.json')
    os.environ['PINPOINT_CLUB_MARKER_PATH'] = str(args.output / 'unset-club-marker.json')
    result = measure_launch(frames, tuple(manifest['ballBounds']), impact,
                            manifest.get('timestampSource', 'host'), exposure, original.get('track'))
    x, y, width, height = manifest['ballBounds']
    report = {'version': VERSION, 'captureId': args.capture.name, 'opencvVersion': cv2.__version__,
              'intrinsicsSha256': hashlib.sha256(args.intrinsics.read_bytes()).hexdigest(),
              'intrinsics': json.loads(args.intrinsics.read_text()),
              'frameCount': len(frames), 'exposureUs': exposure, 'measurements': result}
    gaps = np.diff(times) * 1000
    report['timing'] = {'fps': round(1000 / float(np.median(gaps)), 2),
                        'maxGapMs': round(float(gaps.max()), 4),
                        'largeGaps': int(np.count_nonzero(gaps > np.median(gaps) * 1.5))}
    # Same small patch inside the resting ball, well before the club arrives.
    count = min(100, max(0, impact - 30))
    values = np.array([frame[y+int(height*.2):y+int(height*.6),
                             x+int(width*.3):x+int(width*.7)].mean() for _, frame in frames[:count]])
    if len(values) and np.all(np.isfinite(values)):
        report['stationaryPatchBrightness'] = {
            'sampleFrames': count, 'min': round(float(values.min()), 2), 'max': round(float(values.max()), 2),
            'maxToMinRatio': round(float(values.max() / max(values.min(), 1)), 3),
            'note': 'Fixed image patch. Motion or occlusion also changes brightness; inspect the frames.'}
    diagnostics = result['diagnostics']
    if 'groundPose' in diagnostics:
        pose, calibration = diagnostics['groundPose'], diagnostics['calibration']
        matrix, distortion = np.array(calibration['cameraMatrix']), np.array(calibration['distCoeffs'])
        rotation, translation = np.array(pose['rotation']), np.array(pose['translationM'])
        frame_height, frame_width = frames[0][1].shape
        origin = (x + width / 2, y + height / 2)
        end = (frame_width - max(width, height) / 2 - 3, origin[1])
        first, last = [point_on_ball_center_plane(p, matrix, distortion, rotation, translation) for p in (origin, end)]
        if first is not None and last is not None and end[0] > origin[0]:
            distance = float(np.linalg.norm(last[:2] - first[:2]))
            fps = report['timing']['fps']
            report['leftToRightGroundView'] = {
                'distanceM': round(distance, 3),
                'maxSpeedForTwoIntervalsMps': round(distance * fps / 2, 1),
                'maxSpeedForThreeIntervalsMps': round(distance * fps / 3, 1),
                'note': 'Planning estimate for ground-level motion at the current image row; excludes club occlusion and assumes fixed apparent ball radius.'}
    (args.output / 'audit-v1.0.0.json').write_text(json.dumps(report, indent=2))
    background = ball_background(frames, impact)
    statuses = {item['frameIndex']: item['status'] for item in diagnostics.get('guided', {}).get('frames', [])}
    rows = []
    for index in [max(0, impact - 4), impact, min(len(frames)-1, impact+3), min(len(frames)-1, impact+6)]:
        gray = frames[index][1]
        normalized = np.clip(gray.astype(np.float32) * float(background.mean()) / max(float(gray.mean()), 1), 0, 255).astype(np.uint8)
        difference = cv2.subtract(normalized, background)
        threshold, _ = cv2.threshold(difference, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = cv2.threshold(difference, max(threshold, 20), 255, cv2.THRESH_BINARY)[1]
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        panels = []
        for title, image in [('Camera', gray), ('Ball/club difference mask', mask)]:
            panel = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            cv2.putText(panel, f'{title}: frame {index}', (10, 22), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 1)
            cv2.putText(panel, statuses.get(index, 'Reference / no qualified hint'), (10, 44), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1)
            panels.append(panel)
        rows.append(np.hstack(panels))
    cv2.imwrite(str(args.output / 'outline-audit-v1.0.0.jpg'), np.vstack(rows))
    print(json.dumps({key: value for key, value in report.items() if key not in ('measurements', 'intrinsics')}, indent=2))
    print(json.dumps({'failure': result.get('failure'), 'groundPose': diagnostics.get('groundPose'),
                      'strict': diagnostics['strict'], 'guided': diagnostics.get('guided')}, indent=2))


if __name__ == '__main__':
    main()
