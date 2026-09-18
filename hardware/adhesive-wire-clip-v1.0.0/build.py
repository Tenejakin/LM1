"""Adhesive-backed four-channel snap wire clip v1.0.0. Units: mm."""
import json
from pathlib import Path

import trimesh


VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parent

# Sized for common 1.5-3.8 mm electronics wires and small cable bundles.
WIDTH = 40.0
DEPTH = 12.0
HEIGHT = 8.5
BASE_THICKNESS = 2.0
CHANNEL_DIAMETER = 4.4
CHANNEL_OPENING = 3.0
CHANNEL_CENTERS = (-15.0, -5.0, 5.0, 15.0)


def box(size, center):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


def make_clip():
    body = box((WIDTH, DEPTH, HEIGHT), (0, 0, HEIGHT / 2))
    cuts = []
    for x in CHANNEL_CENTERS:
        channel = trimesh.creation.cylinder(
            radius=CHANNEL_DIAMETER / 2,
            height=DEPTH + 2,
            sections=64,
            transform=trimesh.transformations.rotation_matrix(
                angle=trimesh.util.np.pi / 2,
                direction=(1, 0, 0),
            ),
        )
        channel.apply_translation((x, 0, BASE_THICKNESS + CHANNEL_DIAMETER / 2))
        cuts.append(channel)
        # Narrow top entry leaves retaining lips on both sides of each channel.
        cuts.append(
            box(
                (CHANNEL_OPENING, DEPTH + 2, HEIGHT),
                (x, 0, BASE_THICKNESS + CHANNEL_DIAMETER + HEIGHT / 2),
            )
        )
    clip = trimesh.boolean.difference([body, *cuts], engine='manifold')
    clip.remove_unreferenced_vertices()
    return clip


def main():
    clip = make_clip()
    output = ROOT / f'lm1-adhesive-wire-clip-v{VERSION}.stl'
    clip.export(output)
    checked = trimesh.load_mesh(output)
    report = {
        'version': VERSION,
        'units': 'mm',
        'file': output.name,
        'dimensions_mm': [round(float(v), 2) for v in checked.extents],
        'channels': len(CHANNEL_CENTERS),
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
