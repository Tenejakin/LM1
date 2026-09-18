"""Adhesive-backed single-channel vertical wire clip v1.2.0. Units: mm."""
import json
from pathlib import Path

import numpy as np
import trimesh


VERSION = '1.2.0'
ROOT = Path(__file__).resolve().parent
WIDTH = 10.0
LENGTH = 16.0
HEIGHT = 8.5
BASE_THICKNESS = 2.0
CHANNEL_DIAMETER = 4.4
CHANNEL_OPENING = 3.0


def box(size, center):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def make_clip():
    body = box((WIDTH, LENGTH, HEIGHT), (0, 0, HEIGHT / 2))
    channel = trimesh.creation.cylinder(
        radius=CHANNEL_DIAMETER / 2,
        height=LENGTH + 2,
        sections=64,
        transform=trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)),
    )
    channel.apply_translation((0, 0, BASE_THICKNESS + CHANNEL_DIAMETER / 2))
    opening = box(
        (CHANNEL_OPENING, LENGTH + 2, HEIGHT),
        (0, 0, BASE_THICKNESS + CHANNEL_DIAMETER + HEIGHT / 2),
    )
    clip = trimesh.boolean.difference([body, channel, opening], engine='manifold')
    clip.remove_unreferenced_vertices()
    return clip


def main():
    clip = make_clip()
    output = ROOT / f'lm1-vertical-1-wire-clip-v{VERSION}.stl'
    clip.export(output)
    checked = trimesh.load_mesh(output)
    report = {
        'version': VERSION,
        'units': 'mm',
        'file': output.name,
        'dimensions_mm': [round(float(v), 2) for v in checked.extents],
        'mounting_orientation': '16 mm channel axis vertical',
        'channels': 1,
        'nominal_channel_diameter_mm': CHANNEL_DIAMETER,
        'channel_opening_mm': CHANNEL_OPENING,
        'base_thickness_mm': BASE_THICKNESS,
        'watertight': bool(checked.is_watertight),
        'positive_volume': bool(checked.volume > 0),
        'connected_solids': len(checked.split()),
    }
    assert report['watertight'] and report['positive_volume'], report
    assert report['connected_solids'] == 1, report
    (ROOT / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
