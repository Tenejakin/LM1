"""LM1 above-camera dual IR bracket v1.3.0; dimensions in millimetres."""
from pathlib import Path
import json
import math
import shutil

import numpy as np
import trimesh


VERSION = "1.3.0"
ROOT = Path(__file__).resolve().parent
MOUNT_SPACING = 110.0
MOUNT_HOLE_DIAMETER = 3.4
BRIDGE_WIDTH = 122.0
BRIDGE_HEIGHT = 10.0
BACK_THICKNESS = 4.0
PAD_WIDTH = 32.0
PAD_HEIGHT = 38.0
PAD_MIN_THICKNESS = 3.0
PAD_CENTRE_HEIGHT = 28.0
LED_SPACING = 86.0
TARGET_DISTANCE = 500.0
INWARD_ANGLE = math.atan((LED_SPACING / 2.0) / TARGET_DISTANCE)
DOWNWARD_PITCH_DEG = 28.0
DOWNWARD_PITCH = math.radians(DOWNWARD_PITCH_DEG)
TOE_RISE = PAD_WIDTH * math.tan(INWARD_ANGLE)
PITCH_RISE = PAD_HEIGHT * math.tan(DOWNWARD_PITCH)


def box(size, center):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def aimed_pad(side):
    """Planar adhesive face aimed inward and down; side is -1 left, +1 right."""
    cx = side * LED_SPACING / 2.0
    x0, x1 = cx - PAD_WIDTH / 2.0, cx + PAD_WIDTH / 2.0
    z0 = PAD_CENTRE_HEIGHT - PAD_HEIGHT / 2.0
    z1 = PAD_CENTRE_HEIGHT + PAD_HEIGHT / 2.0
    # Outside edge is thicker, which turns the face normal toward centre.
    t0 = PAD_MIN_THICKNESS + (TOE_RISE if side < 0 else 0.0)
    t1 = PAD_MIN_THICKNESS + (TOE_RISE if side > 0 else 0.0)
    vertices = np.array([
        (x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1),
        (x0, t0, z0), (x1, t1, z0),
        (x1, t1 + PITCH_RISE, z1), (x0, t0 + PITCH_RISE, z1),
    ])
    faces = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def make_bracket():
    parts = [box((BRIDGE_WIDTH, BACK_THICKNESS, BRIDGE_HEIGHT),
                 (0, BACK_THICKNESS / 2.0, 0))]
    for side in (-1, 1):
        # Short neck joins each pad to the bridge without crossing the camera.
        parts.append(box((12, BACK_THICKNESS, 16),
                         (side * LED_SPACING / 2.0, BACK_THICKNESS / 2.0, 7)))
        parts.append(aimed_pad(side))
    solid = trimesh.boolean.union(parts, engine="manifold")
    holes = []
    for x in (-MOUNT_SPACING / 2.0, MOUNT_SPACING / 2.0):
        hole = trimesh.creation.cylinder(
            radius=MOUNT_HOLE_DIAMETER / 2.0,
            height=12.0,
            sections=48,
            transform=trimesh.geometry.align_vectors((0, 0, 1), (0, 1, 0)),
        )
        hole.apply_translation((x, 3.0, 0))
        holes.append(hole)
    mesh = trimesh.boolean.difference([solid, *holes], engine="manifold")
    mesh.remove_unreferenced_vertices()
    assert mesh.is_watertight and mesh.is_volume and len(mesh.split()) == 1
    return mesh


def render_preview(bracket):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 760), "#edf1f4")
    draw = ImageDraw.Draw(image)
    installed = bracket.copy()
    installed.apply_translation((0, 0, 172))
    camera = box((42, 8, 42), (0, 0, 0))
    camera.apply_transform(trimesh.transformations.rotation_matrix(
        -DOWNWARD_PITCH, (1, 0, 0)))
    camera.apply_translation((0, 2, 150))
    objects = [
        installed,
        box((12, 5, 176), (-55, -2.5, 96)),
        box((12, 5, 176), (55, -2.5, 96)),
        box((122, 5, 8), (0, -2.5, 180)),
        camera,
    ]
    colors = [(226, 70, 119), (229, 220, 197), (229, 220, 197),
              (229, 220, 197), (55, 62, 72)]
    view = trimesh.transformations.rotation_matrix(math.radians(17), (1, 0, 0))
    view = view @ trimesh.transformations.rotation_matrix(math.radians(-18), (0, 0, 1))
    transformed = [trimesh.transform_points(mesh.vertices, view) for mesh in objects]
    points = np.vstack(transformed)
    span = np.ptp(points[:, [0, 2]], axis=0)
    scale = min(950 / span[0], 610 / span[1])
    for mesh, vertices, color in zip(objects, transformed, colors):
        projected = np.stack((vertices[:, 0], -vertices[:, 2]), axis=1) * scale
        projected += (600, 650)
        for face in sorted(mesh.faces, key=lambda f: -vertices[f, 1].mean()):
            tri = vertices[face]
            normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
            normal /= max(np.linalg.norm(normal), 1e-10)
            shade = 0.72 + 0.28 * abs(normal @ np.array((0.25, -0.55, 0.8)))
            draw.polygon([tuple(point) for point in projected[face]],
                         fill=tuple(int(channel * shade) for channel in color))
    draw.text((35, 28), "LM1 above-camera IR bracket v1.3.0", fill="#152735")
    draw.text((35, 55), "Pink = printable bracket; cream/black = reference geometry", fill="#152735")
    draw.text((35, 82), "28 deg down | 4.92 deg inward | mounts on upper M3 pair", fill="#152735")
    image.save(ROOT / "preview.png")


def main():
    mesh = make_bracket()
    filename = f"lm1-ir-top-bracket-v{VERSION}.stl"
    mesh.export(ROOT / filename)
    checked = trimesh.load_mesh(ROOT / filename)
    report = {
        "version": VERSION,
        "units": "mm",
        "file": filename,
        "dimensionsMm": np.round(checked.extents, 3).tolist(),
        "watertight": bool(checked.is_watertight),
        "connectedComponents": len(checked.split()),
        "volumeMm3": round(float(checked.volume), 3),
        "mountHoleSpacingMm": MOUNT_SPACING,
        "mountHoleDiameterMm": MOUNT_HOLE_DIAMETER,
        "nominalLedCentreSpacingMm": LED_SPACING,
        "ledCentreAboveUpperScrewsMm": PAD_CENTRE_HEIGHT,
        "downwardPitchDeg": DOWNWARD_PITCH_DEG,
        "inwardAngleDegPerSide": math.degrees(INWARD_ANGLE),
        "nominalAxisIntersectionDistanceMm": TARGET_DISTANCE,
    }
    assert report["watertight"] and report["connectedComponents"] == 1
    (ROOT / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    render_preview(mesh)
    archive = Path(shutil.make_archive(
        str(ROOT.parent / f"lm1-ir-top-bracket-v{VERSION}"), "zip", ROOT))
    print(json.dumps({**report, "archive": archive.name}, indent=2))


if __name__ == "__main__":
    main()
