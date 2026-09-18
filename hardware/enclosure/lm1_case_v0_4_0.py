"""Generate the LM1 flat-pack case with a tilted swivelling OLED pod.

CAD version: 0.4.0

The OLED is fixed at 35 degrees above horizontal and can swivel 35 degrees
left or right. This lets a left- or right-handed player aim it toward their
address position without changing the camera calibration.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as core
import lm1_case_v0_3_0 as flatpack


CASE_VERSION = "0.4.0"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "stl" / f"v{CASE_VERSION}"
OLED_TILT_DEG = 35.0
OLED_YAW_LIMIT_DEG = 35.0
OLED_REFERENCE_YAW_DEG = 25.0
POD_CENTRE = np.array((0.0, core.OLED_CENTER_Y, flatpack.PANEL_TOP + flatpack.LID_T))

core.CASE_VERSION = CASE_VERSION

box = core.box
cylinder = core.cylinder
union = core.union
difference = core.difference


def triangular_prism_x(
    x_centre: float,
    width: float,
    yz_points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> trimesh.Trimesh:
    """Create a watertight triangular prism whose long axis is X."""
    x_low = x_centre - width / 2.0
    x_high = x_centre + width / 2.0
    vertices = np.array(
        [(x_low, y, z) for y, z in yz_points] + [(x_high, y, z) for y, z in yz_points],
        dtype=float,
    )
    faces = np.array(
        (
            (0, 2, 1),
            (3, 4, 5),
            (0, 1, 4), (0, 4, 3),
            (1, 2, 5), (1, 5, 4),
            (2, 0, 3), (2, 3, 5),
        ),
        dtype=int,
    )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def arc_holes(
    centre_x: float,
    centre_y: float,
    radius: float,
    start_deg: float,
    end_deg: float,
    z: float,
) -> list[trimesh.Trimesh]:
    """Overlapping bores form a slicer-friendly curved adjustment slot."""
    holes = []
    for angle_deg in np.linspace(start_deg, end_deg, 19):
        angle = math.radians(float(angle_deg))
        holes.append(
            cylinder(
                1.9,
                12.0,
                (centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle), z),
                sections=32,
            )
        )
    return holes


def make_swivel_lid() -> trimesh.Trimesh:
    z_centre = flatpack.PANEL_TOP + flatpack.LID_T / 2.0
    lid = box(
        (flatpack.BODY_W + 4.0, flatpack.BODY_D + 4.0, flatpack.LID_T),
        (0.0, flatpack.BODY_D / 2.0, z_centre),
    )
    cuts: list[trimesh.Trimesh] = []

    # Corner-rail fasteners.
    for x in (-flatpack.RAIL_X, flatpack.RAIL_X):
        for y in (flatpack.RAIL_FRONT_Y, flatpack.RAIL_REAR_Y):
            cuts.append(cylinder(1.7, 12.0, (x, y, z_centre)))
            cuts.append(
                cylinder(
                    3.2,
                    2.2,
                    (x, y, flatpack.PANEL_TOP + flatpack.LID_T - 1.1),
                    sections=48,
                )
            )

    # The collar in the rotating base uses this hole as a bearing and cable pass-through.
    cuts.append(cylinder(9.3, 12.0, tuple(POD_CENTRE)))

    # Two opposed arc slots lock the OLED anywhere from -35 to +35 degrees.
    cuts.extend(
        arc_holes(
            POD_CENTRE[0],
            POD_CENTRE[1],
            38.0,
            -OLED_YAW_LIMIT_DEG,
            OLED_YAW_LIMIT_DEG,
            z_centre,
        )
    )
    cuts.extend(
        arc_holes(
            POD_CENTRE[0],
            POD_CENTRE[1],
            38.0,
            180.0 - OLED_YAW_LIMIT_DEG,
            180.0 + OLED_YAW_LIMIT_DEG,
            z_centre,
        )
    )
    return difference(lid, cuts)


def make_oled_swivel_base() -> trimesh.Trimesh:
    plate = box((110.0, 85.0, 4.0), (0.0, 0.0, 2.0))
    collar_outer = cylinder(9.0, 3.0, (0.0, 0.0, -1.5), sections=64)
    base = union((plate, collar_outer))

    cuts: list[trimesh.Trimesh] = [
        cylinder(7.0, 14.0, (0.0, 0.0, 0.0), sections=64),
        cylinder(1.7, 12.0, (-38.0, 0.0, 1.0)),
        cylinder(1.7, 12.0, (38.0, 0.0, 1.0)),
    ]
    # Four screws attach the tilted cradle to the rotating plate.
    for x in (-43.0, 43.0):
        for y in (-30.0, 30.0):
            cuts.append(cylinder(1.7, 12.0, (x, y, 1.0)))
    return difference(base, cuts)


def make_flat_oled_bezel() -> trimesh.Trimesh:
    outer = box((92.0, 60.0, 4.0), (0.0, 0.0, 2.0))
    cuts: list[trimesh.Trimesh] = [
        box((core.OLED_VISIBLE_W, core.OLED_VISIBLE_H, 10.0), (0.0, 0.0, 2.0)),
        # A rear pocket seats the provisional 80 x 48 mm OLED PCB.
        box((core.OLED_PCB_W, core.OLED_PCB_H, 2.6), (0.0, 0.0, 1.3)),
    ]
    for x in (-core.OLED_MOUNT_X / 2.0, core.OLED_MOUNT_X / 2.0):
        for y in (-core.OLED_MOUNT_Y / 2.0, core.OLED_MOUNT_Y / 2.0):
            cuts.append(cylinder(1.4, 10.0, (x, y, 2.0)))
    return difference(outer, cuts)


def make_oled_tilt_cradle() -> trimesh.Trimesh:
    angle = math.radians(OLED_TILT_DEG)
    bezel = make_flat_oled_bezel()
    bezel_transform = trimesh.transformations.rotation_matrix(angle, (1.0, 0.0, 0.0))
    lower_edge_compensation = 3.0 + 30.0 * math.sin(angle)
    bezel_transform[:3, 3] = (0.0, 0.0, lower_edge_compensation)
    bezel.apply_transform(bezel_transform)

    projected_half_depth = 30.0 * math.cos(angle)
    upper_height = 3.0 + 60.0 * math.sin(angle) + 4.0 * math.cos(angle)
    support_points = (
        (-projected_half_depth, 3.0),
        (projected_half_depth, 3.0),
        (projected_half_depth, upper_height),
    )
    pieces = [bezel]
    for x in (-44.0, 44.0):
        pieces.append(box((8.0, 70.0, 3.0), (x, 0.0, 1.5)))
        pieces.append(triangular_prism_x(x, 4.0, support_points))
    cradle = union(pieces)

    cuts = []
    for x in (-43.0, 43.0):
        for y in (-30.0, 30.0):
            cuts.append(cylinder(1.7, 10.0, (x, y, 1.5)))
    return difference(cradle, cuts)


def rotate_local_part(mesh: trimesh.Trimesh, yaw_deg: float, world_origin: np.ndarray) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(
        trimesh.transformations.rotation_matrix(math.radians(yaw_deg), (0.0, 0.0, 1.0))
    )
    result.apply_translation(world_origin)
    return result


def cradle_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(
        trimesh.transformations.rotation_matrix(math.radians(90.0), (0.0, 1.0, 0.0))
    )
    return core.on_bed(result)


def swivel_base_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(
        trimesh.transformations.rotation_matrix(math.radians(180.0), (1.0, 0.0, 0.0))
    )
    return core.on_bed(result)


def export_part(
    name: str,
    mesh: trimesh.Trimesh,
    quantity: int = 1,
    orientation: str = "bed",
) -> dict[str, object]:
    if orientation == "panel":
        printable = flatpack.panel_for_print(mesh)
    elif orientation == "rail":
        printable = flatpack.rail_for_print(mesh)
    elif orientation == "hood":
        printable = core.oriented_hood_for_print(mesh)
    elif orientation == "cradle":
        printable = cradle_for_print(mesh)
    elif orientation == "swivel":
        printable = swivel_base_for_print(mesh)
    else:
        printable = core.on_bed(mesh)
    printable.remove_unreferenced_vertices()
    path = OUTPUT / f"lm1_{name}_v{CASE_VERSION}.stl"
    printable.export(path, file_type="stl")
    return {
        "file": path.name,
        "printQuantity": quantity,
        "watertight": bool(printable.is_watertight),
        "volume_mm3": round(float(printable.volume), 1),
        "size_mm": [round(float(value), 1) for value in printable.extents],
        "triangles": int(len(printable.faces)),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    base = flatpack.make_base()
    front = flatpack.make_front_panel()
    rear = flatpack.make_rear_panel()
    side_flat = flatpack.make_side_panel_flat()
    side_left = flatpack.side_panel_in_assembly(side_flat, -1.0)
    side_right = flatpack.side_panel_in_assembly(side_flat, 1.0)
    rail = flatpack.make_corner_rail()
    rails = [
        flatpack.rail_in_assembly(rail, x, y)
        for x in (-flatpack.RAIL_X, flatpack.RAIL_X)
        for y in (flatpack.RAIL_FRONT_Y, flatpack.RAIL_REAR_Y)
    ]
    lid = make_swivel_lid()
    hood = core.make_sun_hood()
    camera_mount = core.make_camera_mount()
    window_retainer = core.make_window_retainer()
    oled_retainer = core.make_oled_retainer()
    led_adapter = core.make_led_adapter()
    swivel_base = make_oled_swivel_base()
    tilt_cradle = make_oled_tilt_cradle()

    report = {
        "caseVersion": CASE_VERSION,
        "units": "millimetres",
        "assembledBodySize_mm": [
            flatpack.BODY_W + 4.0,
            flatpack.BODY_D + 4.0,
            flatpack.PANEL_TOP + flatpack.LID_T,
        ],
        "oledTilt_deg": OLED_TILT_DEG,
        "oledYawAdjustment_deg": [-OLED_YAW_LIMIT_DEG, OLED_YAW_LIMIT_DEG],
        "parts": [
            export_part("base", base),
            export_part("front_sensor_panel", front, orientation="panel"),
            export_part("rear_service_panel", rear, orientation="panel"),
            export_part("side_panel", side_flat, quantity=2),
            export_part("corner_rail", rail, quantity=4, orientation="rail"),
            export_part("top_swivel", lid),
            export_part("oled_swivel_base", swivel_base, orientation="swivel"),
            export_part("oled_tilt_cradle_35deg", tilt_cradle, orientation="cradle"),
            export_part("oled_retainer", oled_retainer),
            export_part("sun_hood", hood, orientation="hood"),
            export_part("camera_mount_13deg", camera_mount),
            export_part("window_retainer", window_retainer),
            export_part("led_adapter", led_adapter, quantity=2),
        ],
    }

    swivel_world = rotate_local_part(swivel_base, OLED_REFERENCE_YAW_DEG, POD_CENTRE)
    cradle_world = rotate_local_part(
        tilt_cradle,
        OLED_REFERENCE_YAW_DEG,
        POD_CENTRE + np.array((0.0, 0.0, 4.0)),
    )
    retainer_world = rotate_local_part(
        oled_retainer,
        OLED_REFERENCE_YAW_DEG,
        POD_CENTRE + np.array((0.0, 0.0, 4.0)),
    )
    # The retainer is omitted from the visual assembly position because it
    # mounts normal to the tilted bezel; it remains a verified printable part.
    del retainer_world

    assembled_parts = [
        base,
        front,
        rear,
        side_left,
        side_right,
        *rails,
        lid,
        hood,
        camera_mount,
        flatpack.window_retainer_in_assembly(window_retainer),
        swivel_world,
        cradle_world,
    ]
    assembly = trimesh.util.concatenate(tuple(assembled_parts))
    assembly_path = OUTPUT / f"lm1_assembly_reference_v{CASE_VERSION}.stl"
    assembly.export(assembly_path, file_type="stl")

    core.render_preview(
        [
            (base, (54, 67, 61)),
            (front, (67, 84, 75)),
            (rear, (67, 84, 75)),
            (side_left, (80, 101, 90)),
            (side_right, (80, 101, 90)),
            *[(item, (37, 48, 43)) for item in rails],
            (lid, (102, 127, 111)),
            (hood, (42, 53, 48)),
            (swivel_world, (48, 61, 55)),
            (cradle_world, (104, 132, 114)),
            (box((core.CAMERA_WINDOW_W, 1.0, core.CAMERA_WINDOW_H), (0.0, -1.0, core.LENS_Z)), (80, 137, 148)),
        ],
        OUTPUT / f"lm1_assembly_preview_v{CASE_VERSION}.png",
    )

    report["assemblyReference"] = assembly_path.name
    report["allPrintablePartsWatertight"] = all(part["watertight"] for part in report["parts"])
    (OUTPUT / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
