"""LM1 0.5.3: dual-camera open bench bracket with 15-degree downward pitch."""
import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as cad
import lm1_test_v0_5_2 as previous


VERSION = '0.5.3'
OUT = Path(__file__).parent / 'stl' / 'v0.5.3-test'
CAMERA_PITCH_DEG = 15.0
CAMERA_BASELINE_MM = 58.0
CAMERA_CENTRES_X = (-CAMERA_BASELINE_MM / 2.0, CAMERA_BASELINE_MM / 2.0)
MAST_INTERFACE_X = 55.0
cad.CASE_VERSION = VERSION
cad.CAMERA_PITCH_DEG = CAMERA_PITCH_DEG
B, C, U, D = cad.box, cad.cylinder, cad.union, cad.difference


def camera_transform(x_offset=0.0):
    angle = math.radians(CAMERA_PITCH_DEG)
    transform = trimesh.transformations.rotation_matrix(angle, (1.0, 0.0, 0.0))
    transform[:3, 3] = (x_offset, 15.0, cad.LENS_Z)
    return transform


def local_to_camera(point, x_offset=0.0):
    homogeneous = np.array((point[0], point[1], point[2], 1.0))
    return (camera_transform(x_offset) @ homogeneous)[:3]


def make_dual_camera_mount():
    """Common, rigid carrier for two matched camera boards.

    The 58 mm horizontal optical baseline leaves a 4 mm nominal gap between
    54 mm PCBs. A central spine joins both plates so their relative pose cannot
    drift, while every lens and mounting pattern remains independent.
    """
    pieces = []
    for camera_x in CAMERA_CENTRES_X:
        plate = B((cad.CAMERA_BOARD_W, 3.0, cad.CAMERA_BOARD_H), (0.0, 0.0, 0.0))
        plate.apply_transform(camera_transform(camera_x))
        pieces.append(plate)

    # Join both plates into one calibration-stable carrier. The spine overlaps
    # each inner PCB plate edge by 1 mm and also acts as an anti-twist rib.
    spine = B((6.0, 3.0, cad.CAMERA_BOARD_H), (0.0, 0.0, 0.0))
    spine.apply_transform(camera_transform())
    pieces.append(spine)

    # Upper and lower rails connect camera plates across larger baselines and
    # resist relative yaw. They sit at the plate edges, clear of lens apertures
    # and all supported mounting-hole patterns.
    for local_z in (-25.0, 25.0):
        rail = B((CAMERA_BASELINE_MM + 12.0, 5.0, 8.0), (0.0, 1.0, local_z))
        rail.apply_transform(camera_transform())
        pieces.append(rail)

    # Preserve the proven v0.5.2 mast interface and brace each side into the
    # nearest camera plate. No stand or tray reprint is required.
    for x in (-MAST_INTERFACE_X, MAST_INTERFACE_X):
        pieces.append(B((10.0, 3.0, 58.0), (x, 6.5, cad.LENS_Z)))
        camera_x = CAMERA_CENTRES_X[0] if x < 0 else CAMERA_CENTRES_X[1]
        board_edge_x = camera_x + (-cad.CAMERA_BOARD_W / 2.0 if x < 0 else cad.CAMERA_BOARD_W / 2.0)
        for z in (cad.LENS_Z - 22.0, cad.LENS_Z + 22.0):
            plate_y = 15.0 - (z - cad.LENS_Z) * math.tan(math.radians(CAMERA_PITCH_DEG))
            span_x = abs(x - board_edge_x) + 4.0
            centre_x = (x + board_edge_x) / 2.0
            span_y = max(5.0, plate_y - 5.0)
            pieces.append(B((span_x, span_y, 6.0), (centre_x, 5.0 + span_y / 2.0, z)))

    mount = U(pieces)
    angle = math.radians(CAMERA_PITCH_DEG)
    normal = (0.0, -math.cos(angle), -math.sin(angle))
    cuts = []

    for camera_x in CAMERA_CENTRES_X:
        # Separate optical apertures prevent the carrier clipping either lens.
        cuts.append(C(11.0, 12.0, tuple(local_to_camera((0.0, 0.0, 0.0), camera_x)), axis=normal, sections=64))
        for sign_x in (-1.0, 1.0):
            for sign_z in (-1.0, 1.0):
                # Overlapping bores form diagonal adjustment slots supporting
                # nominal square hole patterns from 24 through 34 mm.
                for spacing in np.linspace(cad.CAMERA_SLOT_MIN / 2.0, cad.CAMERA_SLOT_MAX / 2.0, 4):
                    centre = local_to_camera((sign_x * spacing, 0.0, sign_z * spacing), camera_x)
                    cuts.append(C(1.4, 12.0, tuple(centre), axis=normal))

    for x in (-MAST_INTERFACE_X, MAST_INTERFACE_X):
        for z in (cad.LENS_Z - 22.0, cad.LENS_Z + 22.0):
            cuts.append(C(1.7, 10.0, (x, 6.5, z), axis=(0.0, 1.0, 0.0)))
    return D(mount, cuts)


def component_count(mesh):
    parent = list(range(len(mesh.vertices)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in mesh.faces:
        parent[find(int(b))] = find(int(a))
        parent[find(int(c))] = find(int(a))
    return len({find(i) for i in range(len(parent))})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base, stand = previous.tray(), previous.mast()
    bracket = make_dual_camera_mount()
    bracket.apply_translation((0, 17.5, 0))
    parts = [
        ('pi_tray', base, 'flat'),
        ('camera_mast', stand, 'side'),
        (f'dual_camera_bracket_{CAMERA_PITCH_DEG:g}deg', bracket, 'side'),
    ]
    report = {
        'version': VERSION,
        'units': 'mm',
        'camera_count': 2,
        'camera_pitch_deg': CAMERA_PITCH_DEG,
        'camera_baseline_mm': CAMERA_BASELINE_MM,
        'camera_centres_x_mm': list(CAMERA_CENTRES_X),
        'mast_interface_compatible_with': 'v0.5.2',
        'parts': [],
    }
    for name, mesh, orientation in parts:
        printable = mesh.copy()
        if orientation == 'side':
            printable.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
        printable = cad.on_bed(printable)
        printable.remove_unreferenced_vertices()
        file = f'lm1_test_{name}_v{VERSION}.stl'
        printable.export(OUT / file)
        checked = trimesh.load_mesh(OUT / file)
        item = {
            'file': file,
            'watertight': bool(checked.is_watertight),
            'positive_volume': bool(checked.volume > 0),
            'connected_solids': component_count(checked),
            'size_mm': np.round(checked.extents, 2).tolist(),
        }
        assert item['watertight'] and item['positive_volume'] and item['connected_solids'] == 1, item
        report['parts'].append(item)

    trimesh.util.concatenate([base, stand, bracket]).export(OUT / f'assembly_reference_v{VERSION}.stl')
    pcb = B((85, 56, 1.6), (0, 88, 11.8))
    cooler = B((40, 35, 20), (-5, 86, 22.6))
    cad.render_preview(
        [
            (base, (115, 143, 128)),
            (stand, (80, 105, 94)),
            (bracket, (164, 173, 162)),
            (pcb, (38, 126, 72)),
            (cooler, (65, 69, 72)),
        ],
        OUT / 'preview.png',
    )
    (OUT / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
