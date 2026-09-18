"""LM1 side-mounted IR brackets v1.2.0; dimensions in millimetres."""
from pathlib import Path
import json
import math
import shutil

import numpy as np
import trimesh


VERSION = "1.2.0"
ROOT = Path(__file__).resolve().parent
PAD_WIDTH = 32.0
PAD_HEIGHT = 38.0
PAD_MIN_THICKNESS = 3.0
MOUNT_RAIL_WIDTH = 12.0
MOUNT_RAIL_HEIGHT = 56.0
MOUNT_RAIL_THICKNESS = 4.0
MOUNT_HOLE_SPACING = 44.0
MOUNT_HOLE_DIAMETER = 3.4
INWARD_OFFSET = 12.0
LED_SPACING = 86.0
TARGET_DISTANCE = 500.0
INWARD_ANGLE = math.atan((LED_SPACING / 2.0) / TARGET_DISTANCE)
WEDGE_RISE = PAD_WIDTH * math.tan(INWARD_ANGLE)
DOWNWARD_PITCH_DEG = 28.0
DOWNWARD_PITCH = math.radians(DOWNWARD_PITCH_DEG)
PITCH_RISE = PAD_HEIGHT * math.tan(DOWNWARD_PITCH)


def box(size, center):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def wedge_pad(inward_sign):
    """Rear face is flat; the front face toes the emitter toward centre."""
    x0 = inward_sign * INWARD_OFFSET - PAD_WIDTH / 2.0
    x1 = inward_sign * INWARD_OFFSET + PAD_WIDTH / 2.0
    # For either handed part, the outside edge is thicker than the inside edge.
    thickness_at_x0 = PAD_MIN_THICKNESS + (WEDGE_RISE if inward_sign > 0 else 0.0)
    thickness_at_x1 = PAD_MIN_THICKNESS + (WEDGE_RISE if inward_sign < 0 else 0.0)
    z0, z1 = -PAD_HEIGHT / 2.0, PAD_HEIGHT / 2.0
    vertices = np.array([
        (x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1),
        (x0, thickness_at_x0, z0), (x1, thickness_at_x1, z0),
        (x1, thickness_at_x1 + PITCH_RISE, z1),
        (x0, thickness_at_x0 + PITCH_RISE, z1),
    ])
    faces = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def make_bracket(inward_sign):
    rail = box((MOUNT_RAIL_WIDTH, MOUNT_RAIL_THICKNESS, MOUNT_RAIL_HEIGHT),
               (0, MOUNT_RAIL_THICKNESS / 2.0, 0))
    solid = trimesh.boolean.union([rail, wedge_pad(inward_sign)], engine="manifold")
    holes = []
    for z in (-MOUNT_HOLE_SPACING / 2.0, MOUNT_HOLE_SPACING / 2.0):
        hole = trimesh.creation.cylinder(
            radius=MOUNT_HOLE_DIAMETER / 2.0,
            height=12.0,
            sections=48,
            transform=trimesh.geometry.align_vectors((0, 0, 1), (0, 1, 0)),
        )
        hole.apply_translation((0, 3.0, z))
        holes.append(hole)
    result = trimesh.boolean.difference([solid, *holes], engine="manifold")
    result.remove_unreferenced_vertices()
    assert result.is_watertight and result.is_volume
    assert len(result.split()) == 1
    return result


def render_preview(left, right):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 760), "#edf1f4")
    draw = ImageDraw.Draw(image)
    assembly = []
    for mesh, x in ((left, -55), (right, 55)):
        item = mesh.copy()
        item.apply_translation((x, 0, 150))
        assembly.append(item)
    # Pale reference geometry: the two mast uprights and camera position.
    camera = box((42, 8, 42), (0, 0, 0))
    camera.apply_transform(trimesh.transformations.rotation_matrix(
        -DOWNWARD_PITCH, (1, 0, 0)))
    camera.apply_translation((0, 2, 150))
    assembly.extend([
        box((12, 5, 176), (-55, -2.5, 96)),
        box((12, 5, 176), (55, -2.5, 96)),
        camera,
    ])
    colors = [(226, 70, 119), (226, 70, 119), (229, 220, 197),
              (229, 220, 197), (55, 62, 72)]
    view = trimesh.transformations.rotation_matrix(math.radians(17), (1, 0, 0))
    view = view @ trimesh.transformations.rotation_matrix(math.radians(-18), (0, 0, 1))
    transformed = []
    for mesh in assembly:
        transformed.append(trimesh.transform_points(mesh.vertices, view))
    all_points = np.vstack(transformed)
    span = np.ptp(all_points[:, [0, 2]], axis=0)
    scale = min(950 / span[0], 610 / span[1])
    for mesh, verts, color in zip(assembly, transformed, colors):
        projected = np.stack((verts[:, 0], -verts[:, 2]), axis=1) * scale
        projected += (600, 650)
        faces = sorted(mesh.faces, key=lambda face: -verts[face, 1].mean())
        for face in faces:
            tri = verts[face]
            normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
            normal /= max(np.linalg.norm(normal), 1e-10)
            shade = 0.72 + 0.28 * abs(normal @ np.array((0.25, -0.55, 0.8)))
            fill = tuple(int(channel * shade) for channel in color)
            draw.polygon([tuple(point) for point in projected[face]], fill=fill)
    draw.text((35, 28), "LM1 IR side brackets v1.2.0", fill="#152735")
    draw.text((35, 55), "Pink = printable parts; cream/black = mast and camera reference only", fill="#152735")
    draw.text((35, 82), "28 deg down | 4.92 deg inward | existing 44 mm M3 hole spacing", fill="#152735")
    image.save(ROOT / "preview.png")


def main():
    left = make_bracket(1)
    right = make_bracket(-1)
    parts = {"left": left, "right": right}
    report = {
        "version": VERSION,
        "units": "mm",
        "mountHoleSpacingMm": MOUNT_HOLE_SPACING,
        "mountHoleDiameterMm": MOUNT_HOLE_DIAMETER,
        "tapePadMm": [PAD_WIDTH, PAD_HEIGHT],
        "padInwardOffsetFromUprightMm": INWARD_OFFSET,
        "nominalLedCentreSpacingMm": LED_SPACING,
        "inwardAngleDegPerSide": math.degrees(INWARD_ANGLE),
        "downwardPitchDeg": DOWNWARD_PITCH_DEG,
        "nominalAxisIntersectionDistanceMm": TARGET_DISTANCE,
        "parts": [],
    }
    for name, mesh in parts.items():
        filename = f"lm1-ir-side-bracket-{name}-v{VERSION}.stl"
        mesh.export(ROOT / filename)
        checked = trimesh.load_mesh(ROOT / filename)
        item = {
            "file": filename,
            "dimensionsMm": np.round(checked.extents, 3).tolist(),
            "watertight": bool(checked.is_watertight),
            "connectedComponents": len(checked.split()),
            "volumeMm3": round(float(checked.volume), 3),
        }
        assert item["watertight"] and item["connectedComponents"] == 1
        report["parts"].append(item)
    (ROOT / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    render_preview(left, right)
    archive_base = ROOT.parent / f"lm1-ir-side-bracket-v{VERSION}"
    archive = Path(shutil.make_archive(str(archive_base), "zip", ROOT))
    print(json.dumps({**report, "archive": archive.name}, indent=2))


if __name__ == "__main__":
    main()
