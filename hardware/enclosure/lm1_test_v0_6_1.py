"""LM1 0.6.1: printer-friendly modular stereo stand (180 mm build envelope)."""
import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as cad
import lm1_test_v0_5_3 as dual


VERSION = '0.6.1'
OUT = Path(__file__).parent / 'stl' / 'v0.6.1-stereo-modular'
PITCH = 20.0
HEIGHT = 200.0
BASELINE = 90.0
MAST_X = 80.0
MAX_PRINT_MM = 180.0
B, C, U, D = cad.box, cad.cylinder, cad.union, cad.difference

cad.CASE_VERSION = VERSION
cad.CAMERA_PITCH_DEG = PITCH
cad.LENS_Z = HEIGHT
dual.CAMERA_PITCH_DEG = PITCH
dual.CAMERA_BASELINE_MM = BASELINE
dual.CAMERA_CENTRES_X = (-BASELINE / 2, BASELINE / 2)
dual.MAST_INTERFACE_X = MAST_X


def tray():
    pieces = [B((176, 150, 5), (0, 75, 2.5))]
    for x in (-85, 85):
        pieces.append(B((6, 150, 4), (x, 75, 7)))
    pi_holes = [(x, y) for x in (-39, 19) for y in (73.5, 122.5)]
    for x, y in pi_holes:
        pieces.append(C(3.5, 8, (x, y, 9)))
    cuts = [C(1.4, 18, (x, y, 6)) for x, y in pi_holes]
    for x in (-MAST_X, MAST_X):
        for y in (10, 38):
            cuts += [C(1.7, 14, (x, y, 5)), C(3.2, 2.4, (x, y, 1.2))]
    return D(U(pieces), cuts)


def mast_half(lower):
    """Lower or upper rigid frame; the two frames butt at z=120 mm."""
    if lower:
        z0, z1 = 8.0, 120.0
        pieces = [B((174, 36, 5), (0, 24, z0)), B((174, 6, 10), (0, 21, 70))]
    else:
        z0, z1 = 120.0, 235.0
        pieces = [B((174, 6, 10), (0, 21, 150)), B((174, 6, 10), (0, 21, 230))]
    for x in (-MAST_X, MAST_X):
        pieces.append(B((14, 6, z1 - z0), (x, 21, (z0 + z1) / 2)))
        if lower:
            pieces.append(B((14, 24, 20), (x, 24, 19)))
    frame = U(pieces)
    cuts = []
    if lower:
        for x in (-MAST_X, MAST_X):
            for y in (10, 38):
                cuts.append(C(1.7, 14, (x, y, 7)))
    else:
        for x in (-MAST_X, MAST_X):
            for z in (HEIGHT - 22, HEIGHT + 22):
                cuts.append(C(1.7, 18, (x, 21, z), axis=(0, 1, 0)))
    # M4 splice holes through each upright, shared with the external joiner plates.
    join_z = (105.0, 135.0)
    for x in (-MAST_X, MAST_X):
        for z in join_z:
            if z0 <= z <= z1:
                cuts.append(C(2.1, 16, (x, 21, z), axis=(0, 1, 0)))
    return D(frame, cuts)


def splice_plate():
    plate = B((30, 4, 50), (0, 0, 0))
    cuts = [C(2.1, 10, (0, 0, z), axis=(0, 1, 0)) for z in (-15, 15)]
    return D(plate, cuts)


def components(mesh):
    return len(mesh.split(only_watertight=False))


def export(name, mesh, orientation='flat'):
    printable = mesh.copy()
    if orientation == 'side':
        printable.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    printable = cad.on_bed(printable)
    printable.remove_unreferenced_vertices()
    path = OUT / f'lm1_{name}_v{VERSION}.stl'
    printable.export(path)
    checked = trimesh.load_mesh(path)
    size = np.round(checked.extents, 2).tolist()
    item = {'file': path.name, 'watertight': bool(checked.is_watertight), 'positive_volume': bool(checked.volume > 0),
            'connected_solids': components(checked), 'size_mm': size, 'fits_180mm_bed': max(size[:2]) <= MAX_PRINT_MM}
    assert item['watertight'] and item['positive_volume'] and item['connected_solids'] == 1 and item['fits_180mm_bed'], item
    return item


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base, lower, upper = tray(), mast_half(True), mast_half(False)
    bracket, joiner = dual.make_dual_camera_mount(), splice_plate()
    report = {'version': VERSION, 'units': 'mm', 'max_print_bed_mm': [180, 180], 'camera_count': 2,
              'camera_pitch_deg': PITCH, 'camera_height_mm': HEIGHT, 'camera_baseline_mm': BASELINE,
              'nominal_ground_intersection_mm': round(HEIGHT / math.tan(math.radians(PITCH)), 1), 'parts': []}
    report['parts'] += [export('stereo_tray', base), export('mast_lower', lower, 'side'),
                        export('mast_upper', upper, 'side'), export('dual_camera_bracket_20deg', bracket, 'side'),
                        export('mast_splice_plate', joiner)]
    assembly_bracket = bracket.copy(); assembly_bracket.apply_translation((0, 17.5, 0))
    left_plate = joiner.copy(); left_plate.apply_translation((-MAST_X, 16, 120))
    right_plate = joiner.copy(); right_plate.apply_translation((MAST_X, 16, 120))
    left_plate_rear = joiner.copy(); left_plate_rear.apply_translation((-MAST_X, 26, 120))
    right_plate_rear = joiner.copy(); right_plate_rear.apply_translation((MAST_X, 26, 120))
    assembly = trimesh.util.concatenate([base, lower, upper, assembly_bracket, left_plate, right_plate, left_plate_rear, right_plate_rear])
    assembly.export(OUT / f'assembly_reference_v{VERSION}.stl')
    cad.render_preview([(base, (115,143,128)), (lower,(80,105,94)), (upper,(80,105,94)),
                        (assembly_bracket,(164,173,162)), (left_plate,(190,150,70)), (right_plate,(190,150,70)),
                        (left_plate_rear,(190,150,70)), (right_plate_rear,(190,150,70))], OUT/'preview.png')
    (OUT/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
