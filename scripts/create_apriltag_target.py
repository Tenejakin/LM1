from pathlib import Path

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parents[1]
TAG_IMAGE = ROOT / "tmp" / "apriltag" / "lm1-apriltag-36h11-id0.png"
OUTPUT = ROOT / "output" / "pdf" / "lm1-apriltag-36h11-id0-100mm-v1.1.0.pdf"
TAG_SIZE_MM = 100


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(OUTPUT), pagesize=A4)
    page_width, page_height = A4
    margin = 18 * mm
    tag_size = TAG_SIZE_MM * mm
    tag_x = (page_width - tag_size) / 2
    tag_y = page_height - margin - tag_size - 20 * mm

    canvas.setFillColor(HexColor("#101417"))
    canvas.setFont("Helvetica-Bold", 19)
    canvas.drawCentredString(page_width / 2, page_height - margin, "LM1 Camera Calibration Tag")
    canvas.setFillColor(HexColor("#394247"))
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(page_width / 2, page_height - margin - 6 * mm, "AprilTag 36h11 - ID 0 - black outside edge is exactly 100 mm")

    canvas.setFillColor(black)
    canvas.drawImage(str(TAG_IMAGE), tag_x, tag_y, width=tag_size, height=tag_size, mask="auto")

    canvas.setStrokeColor(HexColor("#C7F36B"))
    canvas.setLineWidth(0.6)
    canvas.rect(tag_x, tag_y, tag_size, tag_size, fill=0, stroke=1)

    text_y = tag_y - 15 * mm
    canvas.setFillColor(HexColor("#101417"))
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(margin, text_y, "Keep the tag fixed and visible during each capture.")
    canvas.setFillColor(HexColor("#394247"))
    canvas.setFont("Helvetica", 9)
    instructions = [
        "1. Print at 100% / Actual size. Do not use Fit to page.",
        "2. Measure the green outline: it must be 100 mm on every side.",
        "3. Lay flat beside the ball; point its top edge toward the target. Keep it visible during capture.",
        "4. Recalibrate whenever the camera, hitting mat, or ball location moves.",
    ]
    for index, instruction in enumerate(instructions):
        canvas.drawString(margin, text_y - (7 + index * 5.6) * mm, instruction)

    ruler_y = 28 * mm
    ruler_x = (page_width - 100 * mm) / 2
    canvas.setStrokeColor(HexColor("#101417"))
    canvas.setLineWidth(0.8)
    canvas.line(ruler_x, ruler_y, ruler_x + 100 * mm, ruler_y)
    for index in range(0, 101, 10):
        tick = 5 * mm if index % 50 == 0 else 3 * mm
        canvas.line(ruler_x + index * mm, ruler_y, ruler_x + index * mm, ruler_y + tick)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(ruler_x + index * mm, ruler_y - 4 * mm, str(index))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawCentredString(page_width / 2, ruler_y + 8 * mm, "100 mm print check")
    canvas.setFillColor(HexColor("#69736E"))
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(page_width / 2, 14 * mm, "LM1 AprilTag target v1.0.0 - keep flat, clean, and evenly lit")
    canvas.save()


if __name__ == "__main__":
    main()
