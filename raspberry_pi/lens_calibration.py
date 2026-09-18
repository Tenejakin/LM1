"""Checkerboard lens-calibration core shared by the Pi service's in-app flow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


def calibrate_from_images(
    image_paths: list[Path],
    columns: int,
    rows: int,
    square_mm: float,
) -> dict[str, Any]:
    if min(columns, rows) < 3 or square_mm <= 0:
        raise ValueError("Use at least 3x3 inner corners and a positive measured square size.")
    grid = np.zeros((columns * rows, 3), np.float32)
    grid[:, :2] = np.mgrid[:columns, :rows].T.reshape(-1, 2) * square_mm / 1000
    points, size, names = [], None, []
    for path in image_paths:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        current_size = image.shape[::-1]
        if size is not None and current_size != size:
            raise ValueError("All calibration images must have identical resolution.")
        size = current_size
        ok, corners = cv2.findChessboardCornersSB(image, (columns, rows))
        if ok:
            points.append(corners.astype(np.float32))
            names.append(path.name)
    if len(points) < 12:
        raise ValueError(
            f"Need at least 12 readable, diverse tilted checkerboard views across the image; found {len(points)}."
        )
    rms, matrix, distortion, _, _ = cv2.calibrateCamera([grid] * len(points), points, size, None, None)
    if rms > 0.7 or not np.isfinite(rms):
        raise ValueError(f"Calibration rejected: {rms:.3f}px RMS exceeds 0.7px.")
    focal_x, focal_y = float(matrix[0, 0]), float(matrix[1, 1])
    if not (0.7 <= focal_x / focal_y <= 1.4):
        raise ValueError(
            f"Calibration is degenerate (fx={focal_x:.0f}px, fy={focal_y:.0f}px from a "
            "square-pixel sensor); vary the board's tilt (forward/back and left/right) "
            "more across shots, not just its position, and retry."
        )
    return {
        "version": 1,
        "imageSize": list(size),
        "cameraMatrix": matrix.tolist(),
        "distCoeffs": distortion.flatten().tolist(),
        "rmsPx": rms,
        "views": names,
    }
