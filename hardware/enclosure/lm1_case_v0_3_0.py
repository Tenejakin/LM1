"""Generate the narrower, flat-pack LM1 enclosure.

CAD version: 0.3.0

The enclosure uses screw-together flat panels and universal corner rails. All
measurements are millimetres. Front is Y=0 and the rear is Y=BODY_D.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh

import lm1_case_v0_2_0 as core


CASE_VERSION = "0.3.0"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "stl" / f"v{CASE_VERSION}"
# The shared preview renderer reads this value for its image label.
core.CASE_VERSION = CASE_VERSION

# Narrower enclosure sized for a common 220 x 220 mm printer.
BODY_W = 170.0
BODY_D = 140.0
PANEL_BOTTOM = 5.0
PANEL_TOP = 185.0
PANEL_H = PANEL_TOP - PANEL_BOTTOM
PANEL_T = 4.0
BASE_T = 5.0
LID_T = 4.0

# Universal 10 x 10 mm rails sit just inside the four panel corners.
RAIL_SIZE = 10.0
RAIL_X = BODY_W / 2.0 - PANEL_T - RAIL_SIZE / 2.0
RAIL_FRONT_Y = PANEL_T + RAIL_SIZE / 2.0
RAIL_REAR_Y = BODY_D - PANEL_T - RAIL_SIZE / 2.0
FRONT_RAIL_SCREW_Z = (30.0, 95.0, 160.0)
SIDE_RAIL_SCREW_Z = (50.0, 120.0)

# LEDs move below the camera so the body can be 40 mm narrower than v0.2.0.
LED_X = 55.0
LED_Z = 92.0


box = core.box
cylinder = core.cylinder
union = core.union
difference = core.difference


def make_base() -> trimesh.Trimesh:
    pieces = [box((BODY_W, BODY_D, BASE_T), (0.0, BODY_D / 2.0, BASE_T / 2.0))]

    # Standard Raspberry Pi 5 58 x 49 mm mounting pattern.
    for x, y in core.PI_HOLES:
        pieces.append(cylinder(3.6, 7.0, (x, y, BASE_T + 3.5)))
    base = union(pieces)

    cuts: list[trimesh.Trimesh] = []
    for x, y in core.PI_HOLES:
        cuts.append(cylinder(1.35, 13.0, (x, y, BASE_T + 3.5)))

    # M3 screws enter each corner rail from below; heads are recessed.
    for x in (-RAIL_X, RAIL_X):
        for y in (RAIL_FRONT_Y, RAIL_REAR_Y):
            cuts.append(cylinder(1.7, 10.0, (x, y, BASE_T / 2.0)))
            cuts.append(cylinder(3.2, 2.2, (x, y, 1.1), sections=48))

    # Optional M4 holes for bolting a ballast plate under the enclosure.
    for x in (-62.0, 62.0):
        for y in (25.0, 115.0):
            cuts.append(cylinder(2.15, 10.0, (x, y, BASE_T / 2.0)))
            cuts.append(cylinder(4.1, 2.2, (x, y, 1.1), sections=48))
    return difference(base, cuts)


def panel_fastener_cuts(y: float) -> list[trimesh.Trimesh]:
    cuts = []
    for x in (-RAIL_X, RAIL_X):
        for z in FRONT_RAIL_SCREW_Z:
            cuts.append(cylinder(1.7, 12.0, (x, y, z), axis=(0.0, 1.0, 0.0)))
    return cuts


def make_front_panel() -> trimesh.Trimesh:
    width = BODY_W - 2.0 * PANEL_T
    panel = box((width, PANEL_T, PANEL_H), (0.0, PANEL_T / 2.0, (PANEL_BOTTOM + PANEL_TOP) / 2.0))
    cuts: list[trimesh.Trimesh] = [
        box((core.CAMERA_WINDOW_W, 12.0, core.CAMERA_WINDOW_H), (0.0, PANEL_T / 2.0, core.LENS_Z)),
    ]
    for x in (-LED_X, LED_X):
        cuts.append(cylinder(core.LED_BODY_DIA / 2.0, 12.0, (x, PANEL_T / 2.0, LED_Z), axis=(0.0, 1.0, 0.0)))

    # Interchangeable camera mount, window clamp and hood.
    for x in (-55.0, 55.0):
        for z in (128.0, 172.0):
            cuts.append(cylinder(1.7, 12.0, (x, PANEL_T / 2.0, z), axis=(0.0, 1.0, 0.0)))
    for x in (-47.0, 47.0):
        for z in (135.0, 165.0):
            cuts.append(cylinder(1.55, 12.0, (x, PANEL_T / 2.0, z), axis=(0.0, 1.0, 0.0)))
    for x in (-66.5, 66.5):
        for z in (116.0, 180.0):
            cuts.append(cylinder(1.7, 12.0, (x, PANEL_T / 2.0, z), axis=(0.0, 1.0, 0.0)))
    cuts.extend(panel_fastener_cuts(PANEL_T / 2.0))
    return difference(panel, cuts)


def make_rear_panel() -> trimesh.Trimesh:
    width = BODY_W - 2.0 * PANEL_T
    y = BODY_D - PANEL_T / 2.0
    panel = box((width, PANEL_T, PANEL_H), (0.0, y, (PANEL_BOTTOM + PANEL_TOP) / 2.0))
    cuts: list[trimesh.Trimesh] = [
        box((66.0, 12.0, 25.0), (-37.0, y, 21.0)),
        cylinder(19.0, 12.0, (45.0, y, 72.0), axis=(0.0, 1.0, 0.0), sections=64),
    ]
    for x in (29.0, 61.0):
        for z in (56.0, 88.0):
            cuts.append(cylinder(1.7, 12.0, (x, y, z), axis=(0.0, 1.0, 0.0)))
    cuts.extend(panel_fastener_cuts(y))
    return difference(panel, cuts)


def make_side_panel_flat() -> trimesh.Trimesh:
    """One reversible panel; print two copies."""
    depth = BODY_D - 2.0 * PANEL_T
    panel = box((depth, PANEL_H, PANEL_T), (0.0, 0.0, PANEL_T / 2.0))
    cuts: list[trimesh.Trimesh] = []

    # Fasteners meet the front and rear universal rails.
    rail_local_x = depth / 2.0 - RAIL_SIZE / 2.0
    for x in (-rail_local_x, rail_local_x):
        for world_z in SIDE_RAIL_SCREW_Z:
            cuts.append(cylinder(1.7, 12.0, (x, world_z - 95.0, PANEL_T / 2.0)))

    # Two separated vent banks support bottom-to-top cross-flow.
    for world_y in (30.0, 50.0, 70.0, 90.0, 110.0):
        for world_z in (34.0, 104.0):
            cuts.append(box((13.0, 5.0, 12.0), (world_y - BODY_D / 2.0, world_z - 95.0, PANEL_T / 2.0)))
    return difference(panel, cuts)


def side_panel_in_assembly(flat: trimesh.Trimesh, side: float) -> trimesh.Trimesh:
    result = flat.copy()
    if side > 0:
        rotation = np.array(
            ((0.0, 0.0, 1.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        )
        translation = (BODY_W / 2.0 - PANEL_T, BODY_D / 2.0, 95.0)
    else:
        rotation = np.array(
            ((0.0, 0.0, -1.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        )
        translation = (-BODY_W / 2.0 + PANEL_T, BODY_D / 2.0, 95.0)
    result.apply_transform(rotation)
    result.apply_translation(translation)
    return result


def make_corner_rail() -> trimesh.Trimesh:
    rail = box((RAIL_SIZE, RAIL_SIZE, PANEL_H), (0.0, 0.0, PANEL_H / 2.0))
    cuts: list[trimesh.Trimesh] = []

    # Front/rear panel screws use the Y-axis holes.
    for world_z in FRONT_RAIL_SCREW_Z:
        cuts.append(cylinder(1.35, 14.0, (0.0, 0.0, world_z - PANEL_BOTTOM), axis=(0.0, 1.0, 0.0)))

    # Side-panel screws are vertically staggered to prevent collisions.
    for world_z in SIDE_RAIL_SCREW_Z:
        cuts.append(cylinder(1.35, 14.0, (0.0, 0.0, world_z - PANEL_BOTTOM), axis=(1.0, 0.0, 0.0)))

    # Base and lid screws enter the rail ends.
    cuts.append(cylinder(1.35, PANEL_H + 2.0, (0.0, 0.0, PANEL_H / 2.0)))
    return difference(rail, cuts)


def rail_in_assembly(rail: trimesh.Trimesh, x: float, y: float) -> trimesh.Trimesh:
    result = rail.copy()
    result.apply_translation((x, y, PANEL_BOTTOM))
    return result


def make_lid() -> trimesh.Trimesh:
    z_centre = PANEL_TOP + LID_T / 2.0
    pieces = [box((BODY_W + 4.0, BODY_D + 4.0, LID_T), (0.0, BODY_D / 2.0, z_centre))]

    # OLED clamping bosses point down from the removable top.
    for x in (-core.OLED_MOUNT_X / 2.0, core.OLED_MOUNT_X / 2.0):
        for y in (core.OLED_CENTER_Y - core.OLED_MOUNT_Y / 2.0, core.OLED_CENTER_Y + core.OLED_MOUNT_Y / 2.0):
            pieces.append(cylinder(3.2, 5.0, (x, y, PANEL_TOP - 0.5)))
    lid = union(pieces)

    cuts: list[trimesh.Trimesh] = [
        box((core.OLED_VISIBLE_W, core.OLED_VISIBLE_H, 12.0), (0.0, core.OLED_CENTER_Y, PANEL_TOP + 1.0)),
        box((core.OLED_PCB_W, core.OLED_PCB_H, 3.0), (0.0, core.OLED_CENTER_Y, PANEL_TOP + 0.5)),
    ]
    for x in (-RAIL_X, RAIL_X):
        for y in (RAIL_FRONT_Y, RAIL_REAR_Y):
            cuts.append(cylinder(1.7, 12.0, (x, y, z_centre)))
            cuts.append(cylinder(3.2, 2.2, (x, y, PANEL_TOP + LID_T - 1.1), sections=48))
    for x in (-core.OLED_MOUNT_X / 2.0, core.OLED_MOUNT_X / 2.0):
        for y in (core.OLED_CENTER_Y - core.OLED_MOUNT_Y / 2.0, core.OLED_CENTER_Y + core.OLED_MOUNT_Y / 2.0):
            cuts.append(cylinder(1.4, 12.0, (x, y, PANEL_TOP)))
    return difference(lid, cuts)


def window_retainer_in_assembly(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90.0), (1.0, 0.0, 0.0)))
    result.apply_translation((0.0, 7.0, core.LENS_Z))
    return result


def panel_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90.0), (1.0, 0.0, 0.0)))
    return core.on_bed(result)


def rail_for_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    result = mesh.copy()
    result.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90.0), (0.0, 1.0, 0.0)))
    return core.on_bed(result)


def export_part(
    name: str,
    mesh: trimesh.Trimesh,
    quantity: int = 1,
    orientation: str = "bed",
) -> dict[str, object]:
    if orientation == "panel":
        printable = panel_for_print(mesh)
    elif orientation == "rail":
        printable = rail_for_print(mesh)
    elif orientation == "hood":
        printable = core.oriented_hood_for_print(mesh)
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

    base = make_base()
    front = make_front_panel()
    rear = make_rear_panel()
    side_flat = make_side_panel_flat()
    side_left = side_panel_in_assembly(side_flat, -1.0)
    side_right = side_panel_in_assembly(side_flat, 1.0)
    rail = make_corner_rail()
    rails = [
        rail_in_assembly(rail, x, y)
        for x in (-RAIL_X, RAIL_X)
        for y in (RAIL_FRONT_Y, RAIL_REAR_Y)
    ]
    lid = make_lid()
    hood = core.make_sun_hood()
    camera_mount = core.make_camera_mount()
    window_retainer = core.make_window_retainer()
    oled_retainer = core.make_oled_retainer()
    led_adapter = core.make_led_adapter()

    report = {
        "caseVersion": CASE_VERSION,
        "units": "millimetres",
        "assembledSizeExcludingHood_mm": [BODY_W + 4.0, BODY_D + 4.0, PANEL_TOP + LID_T],
        "parts": [
            export_part("base", base),
            export_part("front_sensor_panel", front, orientation="panel"),
            export_part("rear_service_panel", rear, orientation="panel"),
            export_part("side_panel", side_flat, quantity=2),
            export_part("corner_rail", rail, quantity=4, orientation="rail"),
            export_part("top_oled", lid),
            export_part("sun_hood", hood, orientation="hood"),
            export_part("camera_mount_13deg", camera_mount),
            export_part("window_retainer", window_retainer),
            export_part("oled_retainer", oled_retainer),
            export_part("led_adapter", led_adapter, quantity=2),
        ],
    }

    assembled_parts = [base, front, rear, side_left, side_right, *rails, lid, hood, camera_mount, window_retainer_in_assembly(window_retainer)]
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
            (box((core.OLED_VISIBLE_W, core.OLED_VISIBLE_H, 1.0), (0.0, core.OLED_CENTER_Y, PANEL_TOP + LID_T + 0.5)), (22, 42, 38)),
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
