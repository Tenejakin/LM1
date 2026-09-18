"""IR crossbar tape-pad stand v1.0.1; dimensions in millimetres."""
from pathlib import Path
import json
import math
import numpy as np
import trimesh

VERSION = '1.0.1'
ROOT = Path(__file__).resolve().parent
WIDTH = 120.0
SPACING = 86.0
TARGET_DISTANCE = 500.0
ANGLE = math.atan((SPACING / 2) / TARGET_DISTANCE)

def box(size, center):
    m = trimesh.creation.box(extents=size)
    m.apply_translation(center)
    return m

def subtract(base, cuts):
    return trimesh.boolean.difference([base, *cuts], engine='manifold')

def frame(side):
    # Flat forward-facing tape pads; actual board footprint is not yet measured.
    base = box((32, 3, 38), (0, 0, 0))
    result = base
    result.apply_transform(trimesh.transformations.rotation_matrix(side * ANGLE, (0, 0, 1)))
    result.apply_translation((side * SPACING / 2, 0, 23))
    return result

def build():
    base = box((WIDTH, 28, 5), (0, 0, 2.5))
    holes = []
    for x in (-22, 22):
        h = trimesh.creation.cylinder(radius=1.7, height=12, sections=40)
        h.apply_translation((x, 7, 2.5))
        holes.append(h)
    # Centre sighting notch identifies the forward (+Y) edge.
    holes.append(box((3, 4, 12), (0, 13, 2.5)))
    base = subtract(base, holes)
    mesh = trimesh.boolean.union([base, frame(-1), frame(1)], engine='manifold')
    assert mesh.is_watertight and mesh.is_volume
    assert len(mesh.split()) == 1
    assert mesh.extents[0] <= WIDTH + 0.001
    # Validate intersections of nominal face-normal axes in plan view.
    axes = []
    for side in (-1, 1):
        direction = np.array((-side * math.sin(ANGLE), math.cos(ANGLE), 0))
        origin = np.array((side * SPACING / 2, 0, 23))
        point = origin + direction * TARGET_DISTANCE / direction[1]
        assert np.allclose(point, (0, TARGET_DISTANCE, 23))
        axes.append({'originMm': origin.tolist(), 'direction': direction.tolist()})
    filename = f'ir-crossbar-v{VERSION}.stl'
    mesh.export(ROOT / filename)
    report = {'version': VERSION, 'file': filename, 'dimensionsMm': mesh.extents.tolist(),
              'watertight': bool(mesh.is_watertight), 'connectedComponents': len(mesh.split()),
              'volumeMm3': float(mesh.volume), 'ledCentreSpacingMm': SPACING,
              'inwardAngleDegPerSide': math.degrees(ANGLE), 'intersectionMm': [0, 500, 23],
              'flatTapePadMm': [32, 38],
              'boardDimensionsVerified': False, 'axes': axes}
    (ROOT / 'build-report.json').write_text(json.dumps(report, indent=2))
    # Small orthographic CAD preview, generated from the actual exported mesh.
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1100, 700), '#eef2f5')
    draw = ImageDraw.Draw(image)
    view = trimesh.transformations.rotation_matrix(math.radians(24), (1, 0, 0))
    view = view @ trimesh.transformations.rotation_matrix(math.radians(-25), (0, 0, 1))
    vertices = trimesh.transform_points(mesh.vertices, view)
    projected = np.stack((vertices[:, 0], -vertices[:, 2]), axis=1) * 6
    projected += (550, 450)
    faces = sorted(mesh.faces, key=lambda f: -vertices[f, 1].mean())
    for f in faces:
        tri = vertices[f]
        n = np.cross(tri[1]-tri[0], tri[2]-tri[0])
        n /= max(np.linalg.norm(n), 1e-10)
        shade = int(115 + 65 * abs(n @ np.array((.3, -.5, .8))))
        draw.polygon([tuple(p) for p in projected[f]], fill=(40, shade, min(235,shade+45)))
    draw.text((35, 30), 'IR crossbar v1.0.1 - flat tape pads / board footprint unverified', fill='#172b3a')
    draw.text((35, 55), '120 mm overall | 86 mm LED centres | 4.92 degrees inward each | axes meet 500 mm ahead', fill='#172b3a')
    image.save(ROOT / 'preview.png')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    build()
