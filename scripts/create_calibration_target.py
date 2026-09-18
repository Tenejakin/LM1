"""Create the LM1 v1.0.0 portable camera calibration target."""

from reportlab.lib.colors import black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


OUTPUT = "output/pdf/lm1-portable-calibration-target-v1.0.0.pdf"
SQUARE_MM = 25
SQUARES = 6
BOARD_MM = SQUARE_MM * SQUARES


def centered_text(pdf, value, y, font, size):
    pdf.setFont(font, size)
    pdf.drawCentredString(A4[0] / 2, y, value)


def main():
    pdf = canvas.Canvas(OUTPUT, pagesize=A4)
    page_width, page_height = A4

    pdf.setTitle("LM1 Portable Calibration Target v1.0.0")
    pdf.setAuthor("LM1")

    pdf.setFillColor(black)
    centered_text(pdf, "LM1 PORTABLE CALIBRATION TARGET", page_height - 22 * mm, "Helvetica-Bold", 17)
    centered_text(pdf, "v1.0.0 - 6 x 6 checkerboard - 25 mm squares", page_height - 30 * mm, "Helvetica", 9)

    board_left = (page_width - BOARD_MM * mm) / 2
    board_bottom = (page_height - BOARD_MM * mm) / 2 - 4 * mm
    pdf.setFillColor(black)
    pdf.rect(board_left - 2 * mm, board_bottom - 2 * mm, (BOARD_MM + 4) * mm, (BOARD_MM + 4) * mm, fill=1, stroke=0)
    for row in range(SQUARES):
        for column in range(SQUARES):
            color = white if (row + column) % 2 == 0 else black
            pdf.setFillColor(color)
            x = board_left + column * SQUARE_MM * mm
            y = board_bottom + (SQUARES - 1 - row) * SQUARE_MM * mm
            pdf.rect(x, y, SQUARE_MM * mm, SQUARE_MM * mm, fill=1, stroke=0)

    # Registration line: lets a printed copy be checked with a ruler.
    rule_y = board_bottom - 20 * mm
    pdf.setStrokeColor(black)
    pdf.setLineWidth(0.6)
    pdf.line(board_left, rule_y, board_left + 100 * mm, rule_y)
    for tick in range(0, 101, 10):
        x = board_left + tick * mm
        pdf.line(x, rule_y - (3 if tick % 50 == 0 else 2) * mm, x, rule_y + 2 * mm)
        if tick % 50 == 0:
            pdf.setFont("Helvetica", 7)
            pdf.drawCentredString(x, rule_y - 6 * mm, str(tick))
    pdf.setFont("Helvetica", 7)
    pdf.drawString(board_left + 103 * mm, rule_y - 2.5 * mm, "mm - verify this is 100 mm")

    pdf.setFillColor(black)
    centered_text(pdf, "Print at 100% / Actual size. Do not use Fit to page.", 42 * mm, "Helvetica-Bold", 10)
    centered_text(pdf, "Place the board flat beside the ball with its top edge parallel to the target line.", 35 * mm, "Helvetica", 9)
    centered_text(pdf, "Keep the complete board visible during calibration; re-calibrate whenever LM1 is moved.", 29 * mm, "Helvetica", 9)
    centered_text(pdf, "For durable use, mount the print on a rigid, matte backing.", 23 * mm, "Helvetica-Oblique", 8)

    pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    main()
