"""Simple triangular IR aiming wedge v1.0.2. Units: mm."""
from pathlib import Path
import math
import json
import numpy as np
import trimesh

VERSION = '1.0.2'
ROOT = Path(__file__).resolve().parent
WIDTH, LENGTH = 32.0, 38.0
ANGLE = math.atan(43.0 / 500.0)
HEIGHT = WIDTH * math.tan(ANGLE)
# Triangular XZ section, extruded along Y. Flat mounting face at Z=0.
vertices = np.array([(0, y, 0) for y in (0, LENGTH)] +
                    [(WIDTH, y, 0) for y in (0, LENGTH)] +
                    [(WIDTH, y, HEIGHT) for y in (0, LENGTH)])
faces = [(0, 2, 4), (1, 5, 3), (0, 1, 3), (0, 3, 2),
         (2, 3, 5), (2, 5, 4), (4, 5, 1), (4, 1, 0)]
mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
mesh.fix_normals()
assert mesh.is_watertight and mesh.is_volume and len(mesh.split()) == 1
assert math.isclose(math.degrees(math.atan2(HEIGHT, WIDTH)), math.degrees(ANGLE))
mesh.export(ROOT / f'ir-wedge-v{VERSION}.stl')
report = {'version': VERSION, 'angleDeg': math.degrees(ANGLE),
          'dimensionsMm': mesh.extents.tolist(), 'watertight': bool(mesh.is_watertight),
          'connectedComponents': len(mesh.split()), 'volumeMm3': float(mesh.volume),
          'nominalLedSpacingMmFor500mmIntersection': 86}
(ROOT / 'build-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
