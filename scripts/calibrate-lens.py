"""Calibrate the exact capture resolution/lens from diverse checkerboard views.

python scripts/calibrate-lens.py images --columns 9 --rows 6 --square-mm 20 --output intrinsics.json
Columns/rows count INNER corners. Keep focus and sensor crop identical to capture.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', type=Path)
    parser.add_argument('--columns', type=int, required=True)
    parser.add_argument('--rows', type=int, required=True)
    parser.add_argument('--square-mm', type=float, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if min(args.columns, args.rows) < 3 or args.square_mm <= 0:
        parser.error('Use at least 3x3 inner corners and a positive measured square size.')
    grid = np.zeros((args.columns * args.rows, 3), np.float32)
    grid[:, :2] = np.mgrid[:args.columns, :args.rows].T.reshape(-1, 2) * args.square_mm / 1000
    points, size, names = [], None, []
    for path in sorted(args.images.iterdir()):
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            continue
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        current_size = image.shape[::-1]
        if size is not None and current_size != size:
            raise ValueError('All calibration images must have identical resolution.')
        size = current_size
        ok, corners = cv2.findChessboardCornersSB(image, (args.columns, args.rows))
        if ok:
            points.append(corners.astype(np.float32))
            names.append(path.name)
    if len(points) < 12:
        raise ValueError('Need at least 12 readable, diverse tilted checkerboard views across the image.')
    rms, matrix, distortion, _, _ = cv2.calibrateCamera([grid] * len(points), points, size, None, None)
    if rms > 0.7 or not np.isfinite(rms):
        raise ValueError(f'Calibration rejected: {rms:.3f}px RMS exceeds 0.7px.')
    output = {'version': 1, 'imageSize': list(size), 'cameraMatrix': matrix.tolist(), 'distCoeffs': distortion.flatten().tolist(), 'rmsPx': rms, 'views': names}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    print(f'Saved {args.output}: {len(points)} views, RMS {rms:.3f}px. Validate at known distances before use.')


if __name__ == '__main__':
    main()
