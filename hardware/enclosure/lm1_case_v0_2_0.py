"""Generate printable STL parts for the LM1 enclosure.

CAD version: 0.2.0

The model uses millimetres.  It deliberately keeps vendor-dependent camera,
OLED and LED dimensions together near the top of the file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw


CASE_VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "stl" / f"v{CASE_VERSION}"

# Main enclosure. Front is Y=0; rear is Y=BODY_D.
BODY_W = 210.0
BODY_D = 150.0
BODY_H = 188.0
WALL = 3.0
FLOOR = 4.0
LID_T = 4.0

# Optical layout.
LENS_X = 0.0
LENS_Y = 0.0
LENS_Z = 150.0
CAMERA_PITCH_DEG = 13.0
CAMERA_WINDOW_W = 82.0
CAMERA_WINDOW_H = 62.0
CAMERA_BOARD_W = 54.0
CAMERA_BOARD_H = 54.0
CAMERA_SLOT_MIN = 24.0
CAMERA_SLOT_MAX = 34.0

# Generic front lights. Adapt these to the chosen LED module.
LED_CENTER_X = 86.0
LED_CENTER_Z = 145.0
LED_BODY_DIA = 28.0
LED_CLEAR_DIA = 24.0

# Generic 2.79-inch 16:9 OLED. Confirm against the actual module.
OLED_CENTER_X = 0.0
OLED_CENTER_Y = 75.0
OLED_VISIBLE_W = 65.0
OLED_VISIBLE_H = 37.0
OLED_PCB_W = 80.0
OLED_PCB_H = 48.0
OLED_MOUNT_X = 72.0
OLED_MOUNT_Y = 42.0

# Raspberry Pi 5 board and standard mounting-hole locations.
PI_ORIGIN_X = -42.5
PI_ORIGIN_Y = 70.0
PI_HOLES = (
    (PI_ORIGIN_X + 3.5, PI_ORIGIN_Y + 3.5),
    (PI_ORIGIN_X + 61.5, PI_ORIGIN_Y + 3.5),
    (PI_ORIGIN_X + 3.5, PI_ORIGIN_Y + 52.5),
    (PI_ORIGIN_X + 61.5, PI_ORIGIN_Y + 52.5),
)


def box(size: tuple[float, float, float], centre: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(centre)
    return mesh


def cylinder(
    radius: float,
    height: float,
    centre: tuple[float, float, float],
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    sections: int = 48,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    align = trimesh.geometry.align_vectors((0.0, 0.0, 1.0), axis)
    if align is not None:
        mesh.apply_transform(align)
    mesh.apply_translation(centre)
    return mesh


def union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(meshes, engine="manifold", check_volume=False)


def difference(base: trimesh.Trimesh, cuts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.difference([base, *cuts], engine="manifold", check_volume=False)


def frame_xy(
    outer_w: float,
    outer_h: float,
    inner_w: float,
    inner_h: float,
    thickness: float,
) -> trimesh.Trimesh:
    outer = box((outer_w, outer_h, thickness), (0.0, 0.0, thickness / 2.0))
    inner = box((inner_w, inner_h, thickness + 2.0), (0.0, 0.0, thickness / 2.0))
    return difference(outer, [inner])


def slot_cut(
    length: float,
    diameter: float,
    height: float,
    centre: tuple[float, float, float],
) -> trimesh.Trimesh:
    straight = max(0.1, length - diameter)
    pieces = [box((straight, diameter, height), centre)]
    for direction in (-1.0, 1.0):
        pieces.append(
            cylinder(
                diameter / 2.0,
                height,
                (centre[0] + direction * straight / 2.0, centre[1], centre[2]),
            )
        )
    return union(pieces)


def make_chassis() -> trimesh.Trimesh:
    outer = box((BODY_W, BODY_D, BODY_H), (0.0, BODY_D / 2.0, BODY_H / 2.0))
    cavity = box(
        (BODY_W - 2 * WALL, BODY_D - 2 * WALL, BODY_H),
        (0.0, BODY_D / 2.0, FLOOR + BODY_H / 2.0),
    )
    shell = difference(outer, [cavity])

    additions: list[trimesh.Trimesh] = []

    # Raspberry Pi 5 standoffs: 7 mm above the enclosure floor.
    for x, y in PI_HOLES:
        additions.append(cylinder(3.6, 7.0, (x, y, FLOOR + 3.5)))

    # Lid screw bosses tied into the side walls near the top.
    for x in (-98.0, 98.0):
        for y in (10.0, 140.0):
            additions.append(cylinder(4.2, 24.0, (x, y, BODY_H - 12.0)))

    body = union([shell, *additions])

    cuts: list[trimesh.Trimesh] = []

    # Camera window and two LED openings through the front wall.
    cuts.append(box((CAMERA_WINDOW_W, 10.0, CAMERA_WINDOW_H), (LENS_X, 0.0, LENS_Z)))
    for x in (-LED_CENTER_X, LED_CENTER_X):
        cuts.append(cylinder(LED_BODY_DIA / 2.0, 10.0, (x, 0.0, LED_CENTER_Z), axis=(0.0, 1.0, 0.0)))

    # Camera bracket, polycarbonate retainer and hood mounting holes.
    for x in (-55.0, 55.0):
        for z in (128.0, 172.0):
            cuts.append(cylinder(1.7, 12.0, (x, 3.0, z), axis=(0.0, 1.0, 0.0)))
    for x in (-47.0, 47.0):
        for z in (135.0, 165.0):
            cuts.append(cylinder(1.55, 12.0, (x, 3.0, z), axis=(0.0, 1.0, 0.0)))
    for x in (-66.5, 66.5):
        for z in (116.0, 180.0):
            cuts.append(cylinder(1.7, 12.0, (x, 1.0, z), axis=(0.0, 1.0, 0.0)))

    # Raspberry Pi and lid fasteners.
    for x, y in PI_HOLES:
        cuts.append(cylinder(1.35, 12.0, (x, y, FLOOR + 5.0)))
    for x in (-98.0, 98.0):
        for y in (10.0, 140.0):
            cuts.append(cylinder(1.45, 30.0, (x, y, BODY_H - 10.0)))

    # Rear cable bay and optional 40 mm exhaust fan.
    cuts.append(box((78.0, 10.0, 25.0), (-45.0, BODY_D, 20.0)))
    cuts.append(cylinder(19.0, 10.0, (55.0, BODY_D, 72.0), axis=(0.0, 1.0, 0.0), sections=64))
    for x in (39.0, 71.0):
        for z in (56.0, 88.0):
            cuts.append(cylinder(1.7, 10.0, (x, BODY_D, z), axis=(0.0, 1.0, 0.0)))

    # Low and high side ventilation slots form a cross-flow path.
    for side_x in (-BODY_W / 2.0, BODY_W / 2.0):
        for y in (30.0, 50.0, 70.0, 90.0, 110.0):
            for z in (34.0, 104.0):
                cuts.append(box((10.0, 13.0, 5.0), (side_x, y, z)))

    return difference(body, cuts)


def make_lid() -> trimesh.Trimesh:
    plate = box((BODY_W + 4.0, BODY_D + 4.0, LID_T), (0.0, BODY_D / 2.0, BODY_H + LID_T / 2.0))

    # A shallow registration lip fits into the open body with 1 mm clearance.
    lip_outer = box((BODY_W - 6.0, BODY_D - 6.0, 3.0), (0.0, BODY_D / 2.0, BODY_H - 1.5))
    lip_inner = box((BODY_W - 10.0, BODY_D - 10.0, 5.0), (0.0, BODY_D / 2.0, BODY_H - 1.5))
    lip = difference(lip_outer, [lip_inner])

    # Short underside bosses clamp the OLED between lid and retainer.
    oled_bosses = []
    for x in (-OLED_MOUNT_X / 2.0, OLED_MOUNT_X / 2.0):
        for y in (OLED_CENTER_Y - OLED_MOUNT_Y / 2.0, OLED_CENTER_Y + OLED_MOUNT_Y / 2.0):
            oled_bosses.append(cylinder(3.2, 5.0, (x, y, BODY_H - 0.5)))

    lid = union([plate, lip, *oled_bosses])
    cuts: list[trimesh.Trimesh] = [
        box((OLED_VISIBLE_W, OLED_VISIBLE_H, 12.0), (OLED_CENTER_X, OLED_CENTER_Y, BODY_H + 1.0)),
        box((OLED_PCB_W, OLED_PCB_H, 3.0), (OLED_CENTER_X, OLED_CENTER_Y, BODY_H + 0.5)),
    ]
    for x in (-98.0, 98.0):
        for y in (10.0, 140.0):
            cuts.append(cylinder(1.7, 12.0, (x, y, BODY_H + 1.0)))
    for x in (-OLED_MOUNT_X / 2.0, OLED_MOUNT_X / 2.0):
        for y in (OLED_CENTER_Y - OLED_MOUNT_Y / 2.0, OLED_CENTER_Y + OLED_MOUNT_Y / 2.0):
            cuts.append(cylinder(1.4, 12.0, (x, y, BODY_H)))
    return difference(lid, cuts)


def make_sun_hood() -> trimesh.Trimesh:
    # Open U-shaped tunnel. Its 130 x 84 mm clear front avoids vignetting a
    # roughly 100-degree horizontal FOV with the lens set 10 mm behind the face.
    hood_depth = 42.0
    outer_w = 136.0
    side_t = 3.0
    inner_bottom = 108.0
    inner_top = 198.0
    top_t = 4.0
    y_centre = -hood_depth / 2.0 + 3.0
    pieces = [
        box((outer_w, hood_depth, top_t), (0.0, y_centre, inner_top + top_t / 2.0)),
        box((side_t, hood_depth, inner_top - inner_bottom + top_t), (-(outer_w - side_t) / 2.0, y_centre, (inner_top + inner_bottom + top_t) / 2.0)),
        box((side_t, hood_depth, inner_top - inner_bottom + top_t), ((outer_w - side_t) / 2.0, y_centre, (inner_top + inner_bottom + top_t) / 2.0)),
    ]
    hood = union(pieces)
    cuts = []
    for x in (-66.5, 66.5):
        for z in (116.0, 180.0):
            cuts.append(cylinder(1.7, 12.0, (x, 1.0, z), axis=(0.0, 1.0, 0.0)))
    return difference(hood, cuts)


def camera_transform() -> np.ndarray:
    angle = math.radians(CAMERA_PITCH_DEG)
    transform = trimesh.transformations.rotation_matrix(angle, (1.0, 0.0, 0.0))
    transform[:3, 3] = (0.0, 15.0, LENS_Z)
    return transform


def local_to_camera(point: tuple[float, float, float]) -> np.ndarray:
    homogeneous = np.array((point[0], point[1], point[2], 1.0))
    return (camera_transform() @ homogeneous)[:3]


def make_camera_mount() -> trimesh.Trimesh:
    plate = box((CAMERA_BOARD_W, 3.0, CAMERA_BOARD_H), (0.0, 0.0, 0.0))
    plate.apply_transform(camera_transform())

    # Flat flanges bolt to the inside front wall. Four arms bridge to the
    # pitched camera plate, leaving room for the ribbon cable.
    pieces = [plate]
    for x in (-55.0, 55.0):
        pieces.append(box((10.0, 3.0, 58.0), (x, 6.5, LENS_Z)))
        side = -1.0 if x < 0 else 1.0
        for z in (128.0, 172.0):
            plate_y = 15.0 - (z - LENS_Z) * math.tan(math.radians(CAMERA_PITCH_DEG))
            span_x = abs(x - side * CAMERA_BOARD_W / 2.0) + 4.0
            centre_x = (x + side * CAMERA_BOARD_W / 2.0) / 2.0
            span_y = max(5.0, plate_y - 5.0)
            pieces.append(box((span_x, span_y, 6.0), (centre_x, 5.0 + span_y / 2.0, z)))
    mount = union(pieces)

    # Optical and adjustable board holes are drilled normal to the plate.
    angle = math.radians(CAMERA_PITCH_DEG)
    normal = (0.0, -math.cos(angle), -math.sin(angle))
    cuts: list[trimesh.Trimesh] = [cylinder(11.0, 12.0, tuple(local_to_camera((0.0, 0.0, 0.0))), axis=normal, sections=64)]
    for sign_x in (-1.0, 1.0):
        for sign_z in (-1.0, 1.0):
            # Four overlapping bores form a short diagonal slot spanning the
            # common 24-34 mm square camera-board mounting patterns.
            for spacing in np.linspace(CAMERA_SLOT_MIN / 2.0, CAMERA_SLOT_MAX / 2.0, 4):
                centre = local_to_camera((sign_x * spacing, 0.0, sign_z * spacing))
                cuts.append(cylinder(1.4, 12.0, tuple(centre), axis=normal))
    for x in (-55.0, 55.0):
        for z in (128.0, 172.0):
            cuts.append(cylinder(1.7, 10.0, (x, 6.5, z), axis=(0.0, 1.0, 0.0)))
    return difference(mount, cuts)


def make_window_retainer() -> trimesh.Trimesh:
    frame = frame_xy(100.0, 76.0, 80.0, 60.0, 3.0)
    cuts = []
    for x in (-47.0, 47.0):
        for y in (-15.0, 15.0):
            cuts.append(cylinder(1.55, 8.0, (x, y, 1.5)))
    return difference(frame, cuts)


def make_oled_retainer() -> trimesh.Trimesh:
    frame = frame_xy(84.0, 52.0, 70.0, 40.0, 3.0)
    cuts = []
    for x in (-OLED_MOUNT_X / 2.0, OLED_MOUNT_X / 2.0):
        for y in (-OLED_MOUNT_Y / 2.0, OLED_MOUNT_Y / 2.0):
            cuts.append(cylinder(1.4, 8.0, (x, y, 1.5)))
    return difference(frame, cuts)


def make_led_adapter() -> trimesh.Trimesh:
    outer = cylinder(17.0, 4.0, (0.0, 0.0, 2.0), sections=64)
    inner = cylinder(LED_CLEAR_DIA / 2.0, 8.0, (0.0, 0.0, 2.0), sections=64)
    ring = difference(outer, [inner])
    for x in (-14.5, 14.5):
        tab = box((7.0, 10.0, 4.0), (x, 0.0, 2.0))
        ring = union([ring, tab])
    holes = [cylinder(1.55, 8.0, (x, 0.0, 2.0)) for x in (-14.5, 14.5)]
    return difference(ring, holes)


def on_bed(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_translation((0.0, 0.0, -result.bounds[0][2]))
    return result


def oriented_hood_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90.0), (0.0, 1.0, 0.0)))
    return on_bed(result)


def window_retainer_in_assembly(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90.0), (1.0, 0.0, 0.0)))
    result.apply_translation((0.0, 5.0, LENS_Z))
    return result


def render_preview(parts: list[tuple[trimesh.Trimesh, tuple[int, int, int]]], path: Path) -> None:
    width, height = 1100, 820
    canvas = Image.new("RGB", (width, height), (242, 244, 240))
    draw = ImageDraw.Draw(canvas)

    view = np.array((1.15, -1.45, 0.92), dtype=float)
    view /= np.linalg.norm(view)
    up = np.array((0.0, 0.0, 1.0), dtype=float)
    right = np.cross(view, up)
    right /= np.linalg.norm(right)
    screen_up = np.cross(right, view)
    screen_up /= np.linalg.norm(screen_up)
    light = np.array((-0.4, -0.5, 1.0), dtype=float)
    light /= np.linalg.norm(light)

    projected_parts = []
    all_points = []
    for mesh, colour in parts:
        vertices = mesh.vertices
        projected = np.column_stack((vertices @ right, vertices @ screen_up, vertices @ view))
        projected_parts.append((mesh, projected, colour))
        all_points.append(projected[:, :2])
    bounds = np.vstack(all_points)
    min_xy = bounds.min(axis=0)
    max_xy = bounds.max(axis=0)
    scale = min((width - 100) / (max_xy[0] - min_xy[0]), (height - 100) / (max_xy[1] - min_xy[1]))

    triangles = []
    for mesh, projected, colour in projected_parts:
        for face_index, face in enumerate(mesh.faces):
            pts = projected[face]
            depth = float(pts[:, 2].mean())
            normal = mesh.face_normals[face_index]
            shade = 0.55 + 0.45 * abs(float(normal @ light))
            shaded = tuple(max(0, min(255, round(component * shade))) for component in colour)
            screen = []
            for x, y, _ in pts:
                sx = 50 + (x - min_xy[0]) * scale
                sy = height - 50 - (y - min_xy[1]) * scale
                screen.append((round(sx), round(sy)))
            triangles.append((depth, screen, shaded))
    for _, polygon, colour in sorted(triangles, key=lambda item: item[0]):
        draw.polygon(polygon, fill=colour, outline=(60, 65, 62))

    draw.rounded_rectangle((24, 20, 355, 66), radius=10, fill=(18, 28, 24))
    draw.text((42, 33), f"LM1 enclosure v{CASE_VERSION} - assembly preview", fill=(230, 238, 230))
    canvas.save(path)


def export_part(name: str, mesh: trimesh.Trimesh, print_transform: str = "bed") -> dict[str, object]:
    if print_transform == "hood":
        printable = oriented_hood_for_print(mesh)
    else:
        printable = on_bed(mesh)
    # Manifold has already produced closed solids. Avoid trimesh.process here:
    # its connected-component validation adds an unnecessary SciPy dependency.
    printable.remove_unreferenced_vertices()
    path = OUTPUT / f"lm1_{name}_v{CASE_VERSION}.stl"
    printable.export(path, file_type="stl")
    return {
        "file": path.name,
        "watertight": bool(printable.is_watertight),
        "volume_mm3": round(float(printable.volume), 1),
        "size_mm": [round(float(value), 1) for value in printable.extents],
        "triangles": int(len(printable.faces)),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    chassis = make_chassis()
    lid = make_lid()
    hood = make_sun_hood()
    camera_mount = make_camera_mount()
    window_retainer = make_window_retainer()
    oled_retainer = make_oled_retainer()
    led_adapter = make_led_adapter()

    report = {
        "caseVersion": CASE_VERSION,
        "units": "millimetres",
        "parts": [
            export_part("chassis", chassis),
            export_part("top_oled", lid),
            export_part("sun_hood", hood, "hood"),
            export_part("camera_mount_13deg", camera_mount),
            export_part("window_retainer", window_retainer),
            export_part("oled_retainer", oled_retainer),
            export_part("led_adapter", led_adapter),
        ],
    }

    retainer_assembly = window_retainer_in_assembly(window_retainer)
    assembly = trimesh.util.concatenate((chassis, lid, hood, camera_mount, retainer_assembly))
    assembly_path = OUTPUT / f"lm1_assembly_reference_v{CASE_VERSION}.stl"
    assembly.export(assembly_path, file_type="stl")

    render_preview(
        [
            (chassis, (62, 76, 69)),
            (lid, (89, 114, 100)),
            (hood, (42, 53, 48)),
            (box((OLED_VISIBLE_W, OLED_VISIBLE_H, 1.0), (OLED_CENTER_X, OLED_CENTER_Y, BODY_H + LID_T + 0.5)), (24, 43, 39)),
            (box((CAMERA_WINDOW_W, 1.0, CAMERA_WINDOW_H), (LENS_X, -1.0, LENS_Z)), (86, 142, 151)),
        ],
        OUTPUT / f"lm1_assembly_preview_v{CASE_VERSION}.png",
    )

    report["assemblyReference"] = assembly_path.name
    report["allPrintablePartsWatertight"] = all(part["watertight"] for part in report["parts"])
    (OUTPUT / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
