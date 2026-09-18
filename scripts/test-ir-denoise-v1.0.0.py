"""Offline single-frame CV denoising experiment v1.0.0; originals untouched."""
from pathlib import Path
import json
import cv2
import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
source = root / 'tmp/ir-latest-review/ir-on-new-supply-v1.0.6.jpg'
out = root / 'output/ir-denoise-v1.0.0'
out.mkdir(parents=True, exist_ok=True)
original = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
assert original is not None
variants = {'original': original,
            'bilateral': cv2.bilateralFilter(original, 5, 12, 3),
            'nonlocal-h3': cv2.fastNlMeansDenoising(original, None, 3, 7, 21)}
canvas = Image.new('RGB', (1280, 870), '#20252b')
draw = ImageDraw.Draw(canvas)
results = {}
detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11))
for i, (name, frame) in enumerate(variants.items()):
    cv2.imwrite(str(out / (name + '.png')), frame)
    # A common 4x display lift shows dark structure; it is not denoising or extra captured light.
    lifted = np.clip(frame.astype(np.float32) * 4, 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / (name + '-display-4x.png')), lifted)
    y = i * 290
    draw.text((15, y + 8), name + ' / captured brightness', fill='white')
    draw.text((655, y + 8), name + ' / same 4x display lift', fill='white')
    canvas.paste(Image.fromarray(frame).convert('RGB').resize((640, 250)), (0, y + 35))
    canvas.paste(Image.fromarray(lifted).convert('RGB').resize((640, 250)), (640, y + 35))
    _, ids, _ = detector.detectMarkers(frame)
    _, lifted_ids, _ = detector.detectMarkers(lifted)
    results[name] = {'detectedTagIds': [] if ids is None else ids.flatten().tolist(),
                     'displayLiftDetectedTagIds': [] if lifted_ids is None else lifted_ids.flatten().tolist(),
                     'meanAbsoluteChangeGreyLevels': float(np.mean(np.abs(frame.astype(float)-original))),
                     'note': 'No noise/accuracy score: no clean reference, confirmed ball ROI or ground truth.'}
canvas.save(out / 'comparison.png')
(out / 'report.json').write_text(json.dumps({'version': '1.0.0', 'source': str(source),
    'opencv': cv2.__version__, 'results': results,
    'limitation': 'Single compressed snapshot; no claim of motion tracking or spin improvement. Offline only.'}, indent=2))
print(json.dumps(results, indent=2))
