"""LM1 0.7.2 vertical-stereo development stand.

The design keeps both 150 mm CSI ribbons in the optical head, locates the
150 x 65 x 30 mm power pack low in the base, and leaves an adjustable strap
area for an as-yet unmeasured LiPo. Dimensions are millimetres.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as cad


VERSION = "0.7.2"
OUT = Path(__file__).parent / "stl" / "v0.7.2-vertical-development"
MAX_PRINT_MM = 180.0

# Optical assumptions; keep these grouped for adjustment after physical fit.
CAMERA_PITCH_DEG = 18.0
CAMERA_CENTRE_HEIGHT_MM = 205.0
CAMERA_BASELINE_MM = 85.0
LOWER_CAMERA_Z = CAMERA_CENTRE_HEIGHT_MM - CAMERA_BASELINE_MM / 2.0
UPPER_CAMERA_Z = CAMERA_CENTRE_HEIGHT_MM + CAMERA_BASELINE_MM / 2.0
CAMERA_BOARD_MM = 54.0
CAMERA_SLOT_MIN_MM = 24.0
CAMERA_SLOT_MAX_MM = 34.0
LIGHT_LENS_DIA_MM = 20.0
RING_ASSUMED_OD_MM = 80.0
RING_CLEAR_DIA_MM = 32.0

# Power-pack envelope supplied by the user. The LiPo area is deliberately
# strap-based until its exact dimensions and connector exit are measured.
POWER_PACK_MM = (65.0, 150.0, 30.0)
LIPO_ASSUMED_MM = (55.0, 100.0, 20.0)
BASE_W, BASE_D = 176.0, 170.0
MAST_X = 80.0

B, C, U, D = cad.box, cad.cylinder, cad.union, cad.difference
cad.CASE_VERSION = VERSION


def pitched_transform(z: float) -> np.ndarray:
    transform = trimesh.transformations.rotation_matrix(
        math.radians(CAMERA_PITCH_DEG), (1.0, 0.0, 0.0)
    )
    transform[:3, 3] = (0.0, 17.0, z)
    return transform


def optical_point(x: float, z_local: float, centre_z: float) -> np.ndarray:
    point = np.array((x, 0.0, z_local, 1.0))
    return (pitched_transform(centre_z) @ point)[:3]


def base_tray() -> trimesh.Trimesh:
    """Mostly flat base; battery walls moved to separately printable boxes."""
    pieces = [B((BASE_W, BASE_D, 5), (0, BASE_D / 2, 2.5))]
    # Low perimeter ribs stiffen the plate without the tall thin slicer walls
    # that made v0.7.1 awkward to print.
    pieces += [
        B((5, BASE_D, 4), (-85.5, BASE_D / 2, 7)),
        B((5, BASE_D, 4), (85.5, BASE_D / 2, 7)),
        B((BASE_W, 5, 4), (0, 2.5, 7)),
        B((BASE_W, 5, 4), (0, BASE_D - 2.5, 7)),
    ]
    # Mast feet sit at the front edge, outside both battery zones.
    for x in (-MAST_X, MAST_X):
        pieces.append(B((14, 32, 10), (x, 20, 10)))

    cuts = []
    for x in (-MAST_X, MAST_X):
        for y in (10, 30):
            cuts.append(C(2.1, 18, (x, y, 7)))
            cuts.append(C(4.0, 2.4, (x, y, 1.2)))
    # M3 holes for the separate power-bank and provisional LiPo enclosures.
    # Rear crosswise power-pack box: safely behind both mast feet.
    for x in (-73, 73):
        for y in (85.5, 164.5):
            cuts.append(C(1.7, 12, (x, y, 5)))
    # Front-centre LiPo box: between, rather than beneath, the mast uprights.
    for x in (-55, 55):
        for y in (18, 86):
            cuts.append(C(1.7, 12, (x, y, 5)))
    # Tie-down/ballast slots along the rear edge.
    for x in (-65, 0, 65):
        cuts.append(B((22, 5, 12), (x, 164, 5)))
    return D(U(pieces), cuts)


def open_box(inner_w: float, inner_d: float, inner_h: float, wall: float = 3.0) -> trimesh.Trimesh:
    """Support-free tray, open at the top and printed on its solid floor."""
    outer = B((inner_w + 2 * wall, inner_d + 2 * wall, inner_h + wall),
              (0, 0, (inner_h + wall) / 2))
    void = B((inner_w, inner_d, inner_h + 2), (0, 0, wall + (inner_h + 2) / 2))
    return D(outer, [void])


def enclosure_lid(inner_w: float, inner_d: float, lip_h: float = 5.0, wall: float = 3.0) -> trimesh.Trimesh:
    """Flat lid with a shallow locating rim; prints without support, rim upward."""
    plate = B((inner_w + 2 * wall + 1.0, inner_d + 2 * wall + 1.0, wall), (0, 0, wall / 2))
    outer = B((inner_w + 0.8, inner_d + 0.8, lip_h), (0, 0, wall + lip_h / 2))
    inner = B((inner_w - 2 * wall, inner_d - 2 * wall, lip_h + 2), (0, 0, wall + lip_h / 2))
    return U([plate, D(outer, [inner])])


def power_pack_box() -> trimesh.Trimesh:
    tray = open_box(152, 67, 18)
    tabs = [B((18, 12, 3), (x, y, 1.5)) for x in (-73, 73) for y in (-39.5, 39.5)]
    part = U([tray, *tabs])
    cuts = [C(1.7, 10, (x, y, 1.5)) for x in (-73, 73) for y in (-39.5, 39.5)]
    # Cable exit at one end; remaining height is retained by the matching lid.
    cuts.append(B((24, 10, 12), (0, -78, 17)))
    return D(part, cuts)


def lipo_box() -> trimesh.Trimesh:
    tray = open_box(102, 57, 14)
    tabs = [B((16, 12, 3), (x, y, 1.5)) for x in (-55, 55) for y in (-34, 34)]
    part = U([tray, *tabs])
    cuts = [C(1.7, 10, (x, y, 1.5)) for x in (-55, 55) for y in (-34, 34)]
    cuts += [B((5, 18, 10), (x, 0, 5)) for x in (-20, 20)]
    return D(part, cuts)


def mast_half(lower: bool) -> trimesh.Trimesh:
    """Split rigid mast so every part fits a 180 mm printer."""
    z0, z1 = ((8.0, 132.0) if lower else (132.0, 282.0))
    pieces = []
    for x in (-MAST_X, MAST_X):
        pieces.append(B((14, 7, z1 - z0), (x, 20, (z0 + z1) / 2)))
        if lower:
            pieces.append(B((14, 32, 22), (x, 20, 19)))
    for z in ((18, 95) if lower else (165, 270)):
        pieces.append(B((174, 7, 10), (0, 20, z)))
    cuts = []
    if lower:
        for x in (-MAST_X, MAST_X):
            for y in (10, 30):
                cuts.append(C(2.1, 20, (x, y, 7), axis=(0, 0, 1)))
    # Splice holes, two per upright and half.
    for x in (-MAST_X, MAST_X):
        for z in (117, 147):
            if z0 <= z <= z1:
                cuts.append(C(2.1, 20, (x, 20, z), axis=(0, 1, 0)))
    # Optical-carrier and Pi-cradle interfaces on the upper section.
    if not lower:
        for x in (-MAST_X, MAST_X):
            for z in (183, 227):
                cuts.append(C(1.7, 20, (x, 20, z), axis=(0, 1, 0)))
    return D(U(pieces), cuts)


def splice_plate() -> trimesh.Trimesh:
    plate = B((30, 4, 50), (0, 0, 0))
    return D(plate, [C(2.1, 10, (0, 0, z), axis=(0, 1, 0)) for z in (-15, 15)])


def camera_light_carrier() -> trimesh.Trimesh:
    """Flat, support-free face plate for cameras, ring, and side lights."""
    mount = B((172, 4, 150), (0, 0, 0))
    normal = (0.0, 1.0, 0.0)
    cuts = []
    for local_z in (-CAMERA_BASELINE_MM / 2, CAMERA_BASELINE_MM / 2):
        cuts.append(C(12, 12, (0, 0, local_z), axis=normal, sections=64))
        for sx in (-1, 1):
            for sz in (-1, 1):
                for spacing in np.linspace(CAMERA_SLOT_MIN_MM / 2, CAMERA_SLOT_MAX_MM / 2, 4):
                    cuts.append(C(1.45, 12, (sx * spacing, 0, local_z + sz * spacing), axis=normal))
    for x in (-68.0, 68.0):
        cuts.append(C((LIGHT_LENS_DIA_MM + 2) / 2, 12,
                      (x, 0, -CAMERA_BASELINE_MM / 2), axis=normal, sections=64))
        for dz in (-18, 18):
            cuts.append(C(1.7, 12, (x, 0, -CAMERA_BASELINE_MM / 2 + dz), axis=normal))
    # Ring-retainer attachment points around the lower camera.
    for x in (-48, 48):
        cuts.append(C(1.7, 12, (x, 0, -CAMERA_BASELINE_MM / 2), axis=normal))
    # Four outer holes fasten the flat plate to the two printed tilt rails.
    for x in (-78, 78):
        for z in (-55, 55):
            cuts.append(C(1.7, 12, (x, 0, z), axis=normal))
    # Large weight/air openings leave 12 mm structural webs around devices.
    cuts += [
        B((52, 12, 20), (0, 0, 0)),
        B((27, 12, 28), (-50, 0, 37)), B((27, 12, 28), (50, 0, 37)),
    ]
    return D(mount, cuts)


def tilt_rail() -> trimesh.Trimesh:
    """One support-free side rail; print two copies on the broad triangular side."""
    half_w = 7.0
    half_h = 68.0
    face_bottom = 48.0
    face_top = 4.0
    vertices = np.array([
        [-half_w, 0, -half_h], [-half_w, 0, half_h],
        [-half_w, face_top, half_h], [-half_w, face_bottom, -half_h],
        [half_w, 0, -half_h], [half_w, 0, half_h],
        [half_w, face_top, half_h], [half_w, face_bottom, -half_h],
    ])
    faces = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2],
        [1, 2, 6], [1, 6, 5], [0, 4, 7], [0, 7, 3],
    ])
    rail = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if rail.volume < 0:
        rail.invert()
    # Rear holes mount to the mast. Front holes follow the pitched face normal.
    cuts = [C(1.7, 60, (0, 12, z), axis=(0, 1, 0)) for z in (-22, 22)]
    angle = math.radians(CAMERA_PITCH_DEG)
    face_normal = (0, math.cos(angle), math.sin(angle))
    for z in (-55, 55):
        y = 26.0 - z * math.tan(angle)
        cuts.append(C(1.7, 24, (0, y, z), axis=face_normal))
    return D(rail, cuts)


def ring_retainer() -> trimesh.Trimesh:
    """Provisional 80 mm IR-ring carrier with strap slots for fit adjustment."""
    outer = C(RING_ASSUMED_OD_MM / 2 + 4, 3, (0, 0, 1.5))
    ring = D(outer, [C(RING_CLEAR_DIA_MM / 2, 8, (0, 0, 1.5), sections=64)])
    tabs = [B((18, 16, 3), (x, 0, 1.5)) for x in (-48, 48)]
    part = U([ring, *tabs])
    cuts = []
    # Camera-carrier screws plus four zip-tie slots for uncertain PCB diameter.
    for x in (-48, 48):
        cuts.append(C(1.7, 8, (x, 0, 1.5)))
    for x, y, sx, sy in ((0, 34, 14, 4), (0, -34, 14, 4), (34, 0, 4, 14), (-34, 0, 4, 14)):
        cuts.append(B((sx, sy, 8), (x, y, 1.5)))
    return D(part, cuts)


def pi_head_cradle() -> trimesh.Trimesh:
    """Ventilated Pi 5 plate mounted behind the optical carrier."""
    plate = B((78, 68, 4), (0, 0, 2))
    pieces = [plate]
    for x in (-29, 29):
        for z in (-24.5, 24.5):
            pieces.append(C(3.5, 7, (x, z, 7.5)))
    for x in (-48, 48):
        pieces.append(B((22, 18, 4), (x, 0, 2)))
    cradle = U(pieces)
    cuts = [C(1.4, 14, (x, z, 6)) for x in (-29, 29) for z in (-24.5, 24.5)]
    cuts += [C(1.7, 10, (x, 0, 2)) for x in (-48, 48)]
    # Large centre vent leaves room for airflow and cable routing.
    cuts.append(B((38, 32, 12), (0, 0, 2)))
    return D(cradle, cuts)


def camera_board_cover() -> trimesh.Trimesh:
    """Rear cover for one camera PCB; print two, open face upward."""
    shell = open_box(56, 56, 16, wall=2.0)
    # CSI cable exits through one wall without forcing the ribbon to fold.
    return D(shell, [B((18, 10, 8), (0, -29, 14))])


def pi5_cover() -> trimesh.Trimesh:
    """Ventilated removable cover around the Pi in the optical head."""
    shell = open_box(88, 60, 24, wall=2.5)
    cuts = [B((5, 32, 8), (x, 0, 26)) for x in (-30, -15, 0, 15, 30)]
    cuts += [B((20, 10, 12), (44, y, 15)) for y in (-18, 18)]
    return D(shell, cuts)


def side_light_pod() -> trimesh.Trimesh:
    """Generic protective pod for one 20 mm optic; print two."""
    flange = B((34, 38, 3), (0, 0, 1.5))
    barrel = D(C(14, 18, (0, 0, 9)), [C(11, 22, (0, 0, 9), sections=64)])
    part = U([flange, barrel])
    return D(part, [C(1.7, 10, (0, y, 1.5)) for y in (-18, 18)])


def ring_shroud() -> trimesh.Trimesh:
    """Shallow housing around the provisional 80 mm IR ring."""
    body = D(C(46, 12, (0, 0, 6), sections=96), [C(17, 16, (0, 0, 6), sections=64)])
    tabs = [B((18, 18, 3), (x, 0, 1.5)) for x in (-50, 50)]
    part = U([body, *tabs])
    return D(part, [C(1.7, 10, (x, 0, 1.5)) for x in (-50, 50)])


def components(mesh: trimesh.Trimesh) -> int:
    return len(mesh.split(only_watertight=False))


def export(name: str, mesh: trimesh.Trimesh, orientation: str = "flat") -> dict:
    printable = mesh.copy()
    if orientation == "side":
        printable.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    elif orientation == "rail":
        printable.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    printable = cad.on_bed(printable)
    printable.remove_unreferenced_vertices()
    path = OUT / f"lm1_{name}_v{VERSION}.stl"
    printable.export(path)
    checked = trimesh.load_mesh(path)
    size = np.round(checked.extents, 2).tolist()
    item = {
        "file": path.name,
        "watertight": bool(checked.is_watertight),
        "positive_volume": bool(checked.volume > 0),
        "connected_solids": components(checked),
        "size_mm": size,
        "fits_180mm_bed": max(size[:2]) <= MAX_PRINT_MM,
    }
    assert item["watertight"] and item["positive_volume"] and item["connected_solids"] == 1, item
    assert item["fits_180mm_bed"], item
    return item


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base = base_tray()
    lower, upper = mast_half(True), mast_half(False)
    carrier = camera_light_carrier()
    rail = tilt_rail()
    joiner, ring, pi_cradle = splice_plate(), ring_retainer(), pi_head_cradle()
    power_box, power_lid = power_pack_box(), enclosure_lid(152, 67)
    lipo_case, lipo_lid = lipo_box(), enclosure_lid(102, 57)
    camera_cover, pi_cover = camera_board_cover(), pi5_cover()
    light_pod, ir_shroud = side_light_pod(), ring_shroud()

    report = {
        "version": VERSION,
        "status": "development-fit prototype",
        "units": "mm",
        "max_print_bed_mm": [180, 180],
        "camera_layout": "vertical parallel stereo",
        "camera_pitch_deg": CAMERA_PITCH_DEG,
        "camera_baseline_mm": CAMERA_BASELINE_MM,
        "camera_heights_mm": [LOWER_CAMERA_Z, UPPER_CAMERA_Z],
        "power_pack_envelope_mm": list(POWER_PACK_MM),
        "lipo_provisional_envelope_mm": list(LIPO_ASSUMED_MM),
        "base_layout": "mast feet front/outboard; LiPo front-centre; power pack crosswise at rear",
        "provisional_dimensions": {
            "ir_ring_outer_diameter_mm": RING_ASSUMED_OD_MM,
            "ir_ring_clear_diameter_mm": RING_CLEAR_DIA_MM,
            "light_lens_diameter_mm": LIGHT_LENS_DIA_MM,
            "camera_board_max_mm": CAMERA_BOARD_MM,
        },
        "parts": [],
    }
    report["parts"] = [
        export("vertical_base", base),
        export("vertical_mast_lower", lower, "side"),
        export("vertical_mast_upper", upper, "side"),
        export("vertical_camera_light_carrier", carrier, "side"),
        export("camera_tilt_rail_18deg", rail, "rail"),
        export("mast_splice_plate", joiner),
        export("ir_ring_retainer_80mm", ring),
        export("pi5_head_cradle", pi_cradle),
        export("power_pack_box", power_box),
        export("power_pack_lid", power_lid),
        export("lipo_box_provisional", lipo_case),
        export("lipo_lid_provisional", lipo_lid),
        export("camera_board_cover", camera_cover),
        export("pi5_cover", pi_cover),
        export("side_light_pod_20mm", light_pod),
        export("ir_ring_shroud_80mm", ir_shroud),
    ]

    # Assembly reference. The Pi cradle is shown behind the optics; it is not a print file.
    plate_positions = []
    for x in (-MAST_X, MAST_X):
        for y in (14, 26):
            p = joiner.copy(); p.apply_translation((x, y, 132)); plate_positions.append(p)
    carrier_assembly = carrier.copy()
    carrier_transform = pitched_transform(CAMERA_CENTRE_HEIGHT_MM)
    carrier_transform[1, 3] = 46.0
    carrier_assembly.apply_transform(carrier_transform)
    rail_assemblies = []
    for x in (-78, 78):
        placed = rail.copy(); placed.apply_translation((x, 20, CAMERA_CENTRE_HEIGHT_MM)); rail_assemblies.append(placed)
    ring_assembly = ring.copy()
    ring_transform = pitched_transform(LOWER_CAMERA_Z)
    ring_transform[1, 3] = 43.0
    ring_assembly.apply_transform(ring_transform)
    pi_assembly = pi_cradle.copy()
    pi_assembly.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    pi_assembly.apply_translation((0, 40, CAMERA_CENTRE_HEIGHT_MM))
    power_box_assembly = power_box.copy(); power_box_assembly.apply_translation((0, 125, 5))
    lipo_box_assembly = lipo_case.copy(); lipo_box_assembly.apply_translation((0, 52, 5))
    assembly_parts = [base, lower, upper, carrier_assembly, ring_assembly, pi_assembly,
                      power_box_assembly, lipo_box_assembly, *rail_assemblies, *plate_positions]
    trimesh.util.concatenate(assembly_parts).export(OUT / f"assembly_reference_v{VERSION}.stl")
    cad.render_preview(
        [
            (base, (93, 115, 105)), (lower, (71, 91, 83)), (upper, (71, 91, 83)),
            (carrier_assembly, (175, 181, 170)), (ring_assembly, (114, 66, 62)),
            (pi_assembly, (56, 91, 125)),
            (power_box_assembly, (92, 98, 104)), (lipo_box_assembly, (92, 98, 104)),
            *[(part, (105, 120, 142)) for part in rail_assemblies],
            *[(part, (193, 151, 70)) for part in plate_positions],
        ], OUT / "preview.png"
    )
    # Component mockups make placement and clearance visible before hardware is fitted.
    power_mock = B((150, 65, 30), (0, 125, 23))
    lipo_mock = B((100, 55, 20), (0, 52, 18))
    camera_mocks = []
    lens_mocks = []
    for local_z in (-CAMERA_BASELINE_MM / 2, CAMERA_BASELINE_MM / 2):
        pcb = B((54, 2, 54), (0, -4, local_z)); pcb.apply_transform(carrier_transform); camera_mocks.append(pcb)
        lens = C(9, 16, (0, -10, local_z), axis=(0, 1, 0), sections=64)
        lens.apply_transform(carrier_transform); lens_mocks.append(lens)
    light_mocks = []
    for x in (-68, 68):
        light = C(10, 20, (x, -10, -CAMERA_BASELINE_MM / 2), axis=(0, 1, 0), sections=64)
        light.apply_transform(carrier_transform); light_mocks.append(light)
    pi_mock = B((85, 3, 56), (0, 51, CAMERA_CENTRE_HEIGHT_MM))
    component_parts = [base, lower, upper, carrier_assembly, ring_assembly, pi_assembly,
                       power_box_assembly, lipo_box_assembly, *rail_assemblies, *plate_positions]
    cad.render_preview(
        [
            *[(part, (76, 92, 84)) for part in component_parts],
            (power_mock, (45, 48, 54)), (lipo_mock, (45, 74, 120)),
            *[(part, (36, 115, 74)) for part in camera_mocks],
            *[(part, (35, 37, 40)) for part in lens_mocks],
            *[(part, (139, 71, 39)) for part in light_mocks],
            (pi_mock, (42, 122, 74)),
        ], OUT / "component-render.png"
    )
    (OUT / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
