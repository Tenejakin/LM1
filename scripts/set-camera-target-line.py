"""v1.0.0: set the target direction to camera-image left-to-right on the ground."""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'raspberry_pi'))
sys.path.append('/opt/pinpoint')
from launch_measurements import load_setup, find_ground_tag_pose, MAX_ESTIMATED_TAG_POSE_ERROR_PX
from target_line import save_target_line, target_line_path

VERSION = '1.0.0'


def ground_point(pixel, matrix, distortion, rotation, translation):
    normalized = cv2.undistortPoints(np.array([[pixel]], dtype=np.float64), matrix, distortion).reshape(2)
    ray = rotation.T @ np.array([*normalized, 1.0])
    camera = -rotation.T @ translation
    if abs(ray[2]) < 1e-8:
        raise ValueError('The target-line ray is parallel to the ground.')
    distance = -camera[2] / ray[2]
    if distance <= 0:
        raise ValueError('The target-line pixels do not intersect visible ground.')
    return camera + distance * ray


def main():
    root = Path(os.getenv('PINPOINT_ROLLING_CAPTURE_PATH', '/var/lib/pinpoint/rolling-captures'))
    capture = max(root.glob('capture-*/capture.json'), key=lambda p: p.stat().st_mtime)
    manifest = json.loads(capture.read_text())
    frames = [(t / 1000, cv2.imread(str(capture.parent / f'frame-{i:04d}.jpg'), 0))
              for i, t in enumerate(manifest['frameTimesMs'])]
    if any(frame is None for _, frame in frames):
        raise ValueError('Capture frames are incomplete.')
    height, width = frames[0][1].shape
    matrix, distortion = load_setup((width, height))
    pose = find_ground_tag_pose(frames, manifest['impactFrameIndex'],
                                int(os.getenv('PINPOINT_APRILTAG_ID', '0')),
                                float(os.getenv('PINPOINT_APRILTAG_SIZE_MM', '100')) / 1000,
                                matrix, distortion)
    if pose is None or pose['errorPx'] > MAX_ESTIMATED_TAG_POSE_ERROR_PX:
        raise ValueError('A usable ground-tag pose is required.')
    x, y, bw, bh = manifest['ballBounds']
    center = (x + bw / 2, y + bh / 2)
    pixels = [(max(2, center[0] - 50), center[1]),
              (min(width - 3, center[0] + 50), center[1])]
    points = [ground_point(pixel, matrix, distortion, pose['rotation'], pose['translation']) for pixel in pixels]
    delta = points[1] - points[0]
    displacement = float(np.linalg.norm(delta[:2]))
    if displacement < 0.001:
        raise ValueError('Target-line ground displacement is too small.')
    path = target_line_path()
    if path.exists():
        path.with_name('target-line-before-camera-v1.0.0.json').write_bytes(path.read_bytes())
    result = save_target_line(math.degrees(math.atan2(delta[1], delta[0])), 2, displacement)
    result.update({'calibrationToolVersion': VERSION, 'source': 'camera-left-to-right',
                   'captureId': capture.parent.name, 'imagePoints': pixels,
                   'tagPoseErrorPx': round(pose['errorPx'], 4)})
    temporary = path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(result, indent=2))
    temporary.replace(path)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
