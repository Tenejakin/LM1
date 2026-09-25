"""Printable lens-calibration checkerboard matching the Pi's default board settings.

The Pi looks for PINPOINT_CALIBRATION_COLUMNS x PINPOINT_CALIBRATION_ROWS inner
corners (default 5 x 5) on squares of PINPOINT_CALIBRATION_SQUARE_MM (default 25),
so this draws 6 x 6 squares of 25 mm. OpenCV needs a white quiet zone around the
board, so there is deliberately no frame around the squares.
"""

from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
INNER_COLUMNS = 5
INNER_ROWS = 5
SQUARE_MM = 25
OUTPUT = ROOT / "output" / "pdf" / f"lm1-lens-checkerboard-{INNER_COLUMNS}x{INNER_ROWS}-{SQUARE_MM}mm-v{VERSION}.pdf"
INK = HexColor("#101417")
MUTED = HexColor("#394247")

STEPS = (
    "Print at 100% / Actual size (not Fit to page). Check the scale bar reads 100 mm and one square 25 mm.",
    "Glue the print flat onto stiff board (foam board or card). A bent sheet ruins the calibration.",
    "In the app: Calibration > Lens calibration capture. Pick Lower CAM0 or Upper CAM1.",
    "Hold the board so it fills about half of that camera's preview, with white paper visible around all squares.",
    "Capture 15-20 views: centre, all four corners and edges, near and far. Tilt it 30-45 degrees forward/back and left/right.",
    "Keep views with 'Corners found'. At 12 or more, press Run calibration. Then repeat for the other camera.",
    "Do not change lens focus afterwards. Refocusing or changing resolution needs a new calibration.",
)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(OUTPUT), pagesize=A4)
    canvas.setTitle(f"LM1 lens calibration checkerboard v{VERSION}")
    page_width, page_height = A4
    margin = 18 * mm

    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 19)
    canvas.drawCentredString(page_width / 2, page_height - margin, "LM1 Lens Calibration Checkerboard")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(
        page_width / 2, page_height - margin - 6 * mm,
        f"{INNER_COLUMNS + 1} x {INNER_ROWS + 1} squares - {SQUARE_MM} mm each - "
        f"{INNER_COLUMNS} x {INNER_ROWS} inner corners - for each camera separately",
    )

    square = SQUARE_MM * mm
    board_width = (INNER_COLUMNS + 1) * square
    board_height = (INNER_ROWS + 1) * square
    left = (page_width - board_width) / 2
    top = page_height - margin - 22 * mm
    canvas.setStrokeColor(white)
    for row in range(INNER_ROWS + 1):
        for column in range(INNER_COLUMNS + 1):
            canvas.setFillColor(black if (row + column) % 2 == 0 else white)
            canvas.rect(left + column * square, top - (row + 1) * square, square, square, fill=1, stroke=0)
    bottom = top - board_height

    # 100 mm scale bar with a 25 mm square-size check.
    bar_y = bottom - 16 * mm
    bar_left = (page_width - 100 * mm) / 2
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(0.6)
    canvas.line(bar_left, bar_y, bar_left + 100 * mm, bar_y)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    for tick in range(0, 101, 10):
        height = 3.2 * mm if tick % 50 == 0 else 1.8 * mm
        x = bar_left + tick * mm
        canvas.line(x, bar_y, x, bar_y + height)
        canvas.drawCentredString(x, bar_y - 3.5 * mm, str(tick))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(INK)
    canvas.drawCentredString(page_width / 2, bar_y + 5 * mm, "100 mm print check")

    text_y = bar_y - 13 * mm
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(margin, text_y, "Hold it in front of one camera at a time - do not lay it on the mat.")
    canvas.setFont("Helvetica", 8.6)
    canvas.setFillColor(MUTED)
    for number, step in enumerate(STEPS, start=1):
        text_y -= 5.4 * mm
        canvas.drawString(margin, text_y, f"{number}. {step}")

    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(
        page_width / 2, 10 * mm,
        f"LM1 checkerboard v{VERSION} - matches PINPOINT_CALIBRATION_COLUMNS={INNER_COLUMNS}, "
        f"ROWS={INNER_ROWS}, SQUARE_MM={SQUARE_MM} (Pi defaults)",
    )
    canvas.showPage()
    canvas.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
