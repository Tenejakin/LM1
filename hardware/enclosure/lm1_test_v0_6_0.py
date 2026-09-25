"""LM1 0.6.0: performance-oriented synchronized stereo camera stand."""
import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as cad
import lm1_test_v0_5_3 as dual


VERSION = '0.6.0'
OUT = Path(__file__).parent / 'stl' / 'v0.6.0-stereo'
CAMERA_PITCH_DEG = 20.0
CAMERA_HEIGHT_MM = 200.0
CAMERA_BASELINE_MM = 120.0
MAST_INTERFACE_X = 95.0
CAMERA_CENTRES_X = (-CAMERA_BASELINE_MM / 2.0, CAMERA_BASELINE_MM / 2.0)
TRAY_W = 220.0
TRAY_D = 150.0
MAST_H = 235.0

cad.CASE_VERSION = VERSION
cad.CAMERA_PITCH_DEG = CAMERA_PITCH_DEG
cad.LENS_Z = CAMERA_HEIGHT_MM
B, C, U, D = cad.box, cad.cylinder, cad.union, cad.difference

# Reuse the validated dual-carrier construction with the expanded stereo geometry.
dual.VERSION = VERSION
dual.OUT = OUT
dual.CAMERA_PITCH_DEG = CAMERA_PITCH_DEG
dual.CAMERA_BASELINE_MM = CAMERA_BASELINE_MM
dual.CAMERA_CENTRES_X = CAMERA_CENTRES_X
dual.MAST_INTERFACE_X = MAST_INTERFACE_X

PI_HOLES = [(x, y) for x in (-39, 19) for y in (73.5, 122.5)]
FOOT_HOLES = [(x, y) for x in (-95, 95) for y in (10, 38)]


def tray():
    """Wide, deep base resisting roll from the larger stereo crossbar."""
    pieces = [B((TRAY_W, TRAY_D, 5), (0, TRAY_D / 2, 2.5))]
    for x in (-107, 107):
        pieces.append(B((6, TRAY_D, 4), (x, TRAY_D / 2, 7)))
    for x, y in PI_HOLES:
        pieces.append(C(3.5, 8, (x, y, 9)))
    cuts = [C(1.4, 18, (x, y, 6)) for x, y in PI_HOLES]
    for x, y in FOOT_HOLES:
        cuts.append(C(1.7, 14, (x, y, 5)))
        cuts.append(C(3.2, 2.4, (x, y, 1.2)))
    # Ballast/tie slots sit outside the Pi footprint.
    for x in (-82, 82):
        cuts.append(B((5, 22, 14), (x, 92, 5)))
    return D(U(pieces), cuts)


def mast():
    """Wider twin-upright mast with two cross-ties to suppress stereo twist."""
    pieces = [B((210, 36, 5), (0, 24, 7.5))]
    for x in (-MAST_INTERFACE_X, MAST_INTERFACE_X):
        pieces.append(B((14, 6, MAST_H - 12), (x, 21, (MAST_H + 12) / 2)))
        pieces.append(B((14, 24, 20), (x, 24, 19)))
    pieces.extend([
        B((204, 6, 10), (0, 21, MAST_H - 5)),
        B((204, 6, 10), (0, 21, 145)),
        # Rear diagonal-equivalent web at the camera zone reduces yaw flex.
        B((204, 4, 8), (0, 25, CAMERA_HEIGHT_MM)),
    ])
    cuts = [C(1.7, 14, (x, y, 7)) for x, y in FOOT_HOLES]
    for x in (-MAST_INTERFACE_X, MAST_INTERFACE_X):
        for z in (CAMERA_HEIGHT_MM - 22, CAMERA_HEIGHT_MM + 22):
            cuts.append(C(1.7, 18, (x, 21, z), axis=(0, 1, 0)))
    return D(U(pieces), cuts)


def main():
    # Inject this revision's stand parts into the shared, validated exporter.
    dual.previous.tray = tray
    dual.previous.mast = mast
    dual.main()

    report_path = OUT / 'build-report.json'
    report = json.loads(report_path.read_text())
    report.update({
        'design': 'performance_stereo',
        'camera_height_mm': CAMERA_HEIGHT_MM,
        'nominal_ground_intersection_mm': round(CAMERA_HEIGHT_MM / math.tan(math.radians(CAMERA_PITCH_DEG)), 1),
        'tray_footprint_mm': [TRAY_W, TRAY_D],
        'requires_new_mast_and_tray': True,
        'camera_requirement': 'matched externally synchronized global-shutter pair',
    })
    report.pop('mast_interface_compatible_with', None)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
