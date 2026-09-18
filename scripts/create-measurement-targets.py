"""Generate vector AprilTags in physical millimetres. Print at 100%, no scaling."""
from pathlib import Path
import cv2

root = Path(__file__).resolve().parents[1] / 'output' / 'measurement-targets-3.4.0'
root.mkdir(parents=True, exist_ok=True)
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
for tag_id, size in ((0, 100), (1, 20)):
    marker = cv2.aruco.generateImageMarker(dictionary, tag_id, 8)
    cells = ''.join(f'<rect x="{20 + x * size / 8}" y="{40 + y * size / 8}" width="{size / 8}" height="{size / 8}"/>' for y in range(8) for x in range(8) if marker[y, x] == 0)
    title = 'Ground tag: +X target direction →' if tag_id == 0 else 'Club tag: measure rigid transform to face'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">
<rect width="210" height="297" fill="white"/><g font-family="sans-serif" fill="black">
<text x="20" y="15" font-size="6">LM1 3.4.0 — AprilTag 36h11 ID {tag_id}</text>
<text x="20" y="25" font-size="4">{title}</text>
<text x="20" y="33" font-size="3.5">Print at 100%. Measure outer black square: {size} × {size} mm.</text>
{cells}<text x="20" y="{size + 55}" font-size="3.5">Keep a white margin. Do not cover or distort the tag.</text>
<path d="M20 220 H120 M20 217 V223 M120 217 V223" stroke="black" fill="none"/>
<text x="20" y="230" font-size="4">This line must measure exactly 100 mm.</text></g></svg>'''
    (root / f'tag36h11-id{tag_id}-{size}mm.svg').write_text(svg, encoding='utf-8')
print(root)
