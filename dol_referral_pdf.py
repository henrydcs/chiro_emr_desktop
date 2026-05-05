# dol_referral_pdf.py
"""
PDF generator for the Doctors on Liens — New Patient Referral Log.

The output mimics the official one-page form provided by Doctors on Liens INC:
    - Top-left: 'Doctors onLiens INC' logo / word-mark area.
    - Top-right: bordered header box with title, email, clinic name, city,
      and 'Referral Dates: <Month 1st – Nth>, <Year>'.
    - Body: 3-column table (NUMBER OF PATIENTS / ATTORNEY-FIRM NAME /
      ADDRESS / PHONE NUMBER) populated with that month's referrals.

Public entry point: build_dol_referral_log_pdf(out_path, ...)
"""
from __future__ import annotations

import calendar
import os
from typing import Iterable

try:
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _ord(n: int) -> str:
    """Return ordinal suffix for n (1st, 2nd, 3rd, 4th, ...)."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def referral_date_phrase(year: int, month: int) -> str:
    """e.g. 'April 1st – 30th, 2026' (matches the printed form)."""
    last = calendar.monthrange(year, month)[1]
    return f"{_MONTH_NAMES[month - 1]} {_ord(1)} \u2013 {_ord(last)}, {year}"


def referral_log_filename(year: int, month: int) -> str:
    """Canonical filename for one monthly log."""
    return f"DoL_Referral_Log_{year:04d}-{month:02d}.pdf"


# ---------------------------------------------------------------------------
# Internal drawing helpers
# ---------------------------------------------------------------------------
def _draw_logo(c: "pdf_canvas.Canvas", x: float, y: float, w: float, h: float) -> None:
    """Render a clean text-based 'Doctors / onLiens INC' word-mark stacked
    on two lines, mirroring the printed form. The EMR does not ship the
    official logo asset, so we draw a faithful approximation."""
    c.setFillColor(colors.black)

    # Line 1: "Doctors"
    line1_font = ("Helvetica-Bold", 30)
    c.setFont(*line1_font)
    line1_y = y + h * 0.62
    c.drawString(x, line1_y, "Doctors")

    # Line 2: small italic "on" + large bold "Liens" + small "INC" superscript
    line2_y = y + h * 0.18

    on_font = ("Helvetica-Oblique", 18)
    liens_font = ("Helvetica-Bold", 30)
    inc_font = ("Helvetica-Bold", 9)

    c.setFont(*on_font)
    on_w = c.stringWidth("on", *on_font)
    c.drawString(x, line2_y, "on")

    c.setFont(*liens_font)
    liens_x = x + on_w + 2
    c.drawString(liens_x, line2_y, "Liens")
    liens_w = c.stringWidth("Liens", *liens_font)

    c.setFont(*inc_font)
    inc_x = liens_x + liens_w + 2
    inc_y = line2_y + 14  # superscript-like
    c.drawString(inc_x, inc_y, "INC")

    # Subtle horizontal underline beneath the wordmark
    c.setStrokeColor(colors.HexColor("#222222"))
    c.setLineWidth(0.6)
    underline_w = (inc_x + c.stringWidth("INC", *inc_font)) - x
    c.line(x, line2_y - 4, x + underline_w, line2_y - 4)


def _draw_header_box(
    c: "pdf_canvas.Canvas",
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    clinic_name: str,
    city: str,
    referral_date_text: str,
) -> None:
    """Top-right bordered box with the form title and clinic fields."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.9)
    c.rect(x, y, w, h, stroke=1, fill=0)

    pad_x = 8
    line_y = y + h - 16

    # Title
    c.setFont("Times-Bold", 13)
    c.drawCentredString(x + w / 2, line_y, "NEW PATIENT REFERRAL LOG")

    # Email line, slightly smaller
    line_y -= 14
    c.setFont("Times-Roman", 10)
    c.drawCentredString(x + w / 2, line_y, "EMAIL  DolReferrals@gmail.com")

    # Clinic Name
    line_y -= 16
    c.setFont("Times-Roman", 10)
    label = "Clinic Name: "
    c.drawString(x + pad_x, line_y, label)
    label_w = c.stringWidth(label, "Times-Roman", 10)
    field_x0 = x + pad_x + label_w
    field_x1 = x + w - pad_x
    if (clinic_name or "").strip():
        c.drawString(field_x0 + 1, line_y, (clinic_name or "").strip())
    c.setLineWidth(0.5)
    c.line(field_x0, line_y - 2, field_x1, line_y - 2)

    # City
    line_y -= 14
    label = "City: "
    c.drawString(x + pad_x, line_y, label)
    label_w = c.stringWidth(label, "Times-Roman", 10)
    field_x0 = x + pad_x + label_w
    if (city or "").strip():
        c.drawString(field_x0 + 1, line_y, (city or "").strip())
    c.line(field_x0, line_y - 2, x + w - pad_x, line_y - 2)

    # Referral Dates
    line_y -= 14
    c.setFont("Times-Roman", 10)
    c.drawString(x + pad_x, line_y, f"Referral Dates: {referral_date_text}")


def _draw_table(
    c: "pdf_canvas.Canvas",
    x: float,
    y_top: float,
    width: float,
    height: float,
    *,
    rows: list[dict],
    n_data_rows: int = 22,
) -> None:
    """3-column data table: # / Attorney-Firm / Address-Phone.

    Draws a header row, then n_data_rows data rows (filled with provided rows
    first, leaving any remaining blank for handwriting if needed)."""
    col_w = (
        width * 0.16,
        width * 0.42,
        width * 0.42,
    )
    col_x = (
        x,
        x + col_w[0],
        x + col_w[0] + col_w[1],
    )

    header_h = 36
    body_top = y_top - header_h
    body_h = height - header_h
    row_h = body_h / n_data_rows

    # ----- outer frame -----
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.0)
    c.rect(x, y_top - height, width, height, stroke=1, fill=0)

    # ----- header row -----
    c.setLineWidth(0.7)
    c.line(x, body_top, x + width, body_top)

    # column dividers (header)
    c.line(col_x[1], y_top, col_x[1], y_top - height)
    c.line(col_x[2], y_top, col_x[2], y_top - height)

    c.setFont("Times-Bold", 10)
    # NUMBER OF PATIENTS — wrap to 3 lines
    cx = col_x[0] + col_w[0] / 2
    c.drawCentredString(cx, y_top - 12, "NUMBER")
    c.drawCentredString(cx, y_top - 22, "OF")
    c.drawCentredString(cx, y_top - 32, "PATIENTS")
    c.drawCentredString(col_x[1] + col_w[1] / 2, y_top - 22, "ATTORNEY/FIRM NAME")
    c.drawCentredString(col_x[2] + col_w[2] / 2, y_top - 22, "ADDRESS/PHONE NUMBER")

    # ----- body row separators -----
    c.setLineWidth(0.5)
    for i in range(1, n_data_rows):
        ry = body_top - i * row_h
        c.line(x, ry, x + width, ry)

    # ----- fill in data -----
    c.setFont("Times-Roman", 9)
    for i in range(n_data_rows):
        row_y_top = body_top - i * row_h
        row_center_y = row_y_top - row_h / 2

        rec = rows[i] if i < len(rows) else None

        # # column
        num_text = str(i + 1) if rec else ""
        c.setFont("Times-Roman", 10)
        c.drawCentredString(col_x[0] + col_w[0] / 2, row_center_y - 3, num_text)

        if rec:
            atty = (rec.get("attorney_label") or "").strip()
            addr_phone = (rec.get("address_phone") or "").strip()
            c.setFont("Times-Roman", 9)
            _draw_clipped_text(
                c, atty, col_x[1] + 4, row_center_y - 3,
                max_width=col_w[1] - 8,
            )
            _draw_clipped_text(
                c, addr_phone, col_x[2] + 4, row_center_y - 3,
                max_width=col_w[2] - 8,
            )


def _draw_clipped_text(
    c: "pdf_canvas.Canvas",
    text: str,
    x: float,
    y: float,
    *,
    max_width: float,
    font_name: str = "Times-Roman",
    font_size: float = 9.0,
) -> None:
    """Single-line draw with right-edge ellipsis if too wide."""
    s = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if not s:
        return
    if c.stringWidth(s, font_name, font_size) <= max_width:
        c.drawString(x, y, s)
        return
    # binary search for max prefix that fits with "..."
    ellipsis = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = s[:mid] + ellipsis
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    c.drawString(x, y, s[:lo] + ellipsis)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_dol_referral_log_pdf(
    out_path: str,
    *,
    clinic_name: str,
    city: str,
    year: int,
    month: int,
    rows: Iterable[dict],
    n_data_rows: int = 22,
) -> str:
    """Build the Doctors on Liens referral log PDF.

    rows: iterable of dicts with keys:
        - 'patient_name': str (informational, not drawn on the form;
          the official form lists attorneys, not patients, but we keep
          it on the record-keeping side for our own exports.)
        - 'attorney_label': str (firm + attorney name)
        - 'address_phone': str (combined address + phone for the right column)
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab is not installed. Install with: pip install reportlab")

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    rows_list = list(rows or [])

    page_w, page_h = LETTER
    margin = 0.5 * inch

    c = pdf_canvas.Canvas(out_path, pagesize=LETTER)
    c.setTitle("Doctors on Liens — New Patient Referral Log")
    c.setAuthor("Chiro EMR")

    # ----- top band: logo (left) + header box (right) -----
    band_h = 1.45 * inch
    band_y_top = page_h - margin

    logo_w = 2.7 * inch
    logo_h = band_h
    _draw_logo(
        c,
        x=margin,
        y=band_y_top - logo_h,
        w=logo_w,
        h=logo_h,
    )

    box_x = margin + logo_w + 0.15 * inch
    box_w = page_w - margin - box_x
    box_h = band_h
    _draw_header_box(
        c,
        x=box_x,
        y=band_y_top - box_h,
        w=box_w,
        h=box_h,
        clinic_name=clinic_name,
        city=city,
        referral_date_text=referral_date_phrase(year, month),
    )

    # ----- body table -----
    table_top = band_y_top - band_h - 0.15 * inch
    table_width = page_w - 2 * margin
    table_height = table_top - margin

    _draw_table(
        c,
        x=margin,
        y_top=table_top,
        width=table_width,
        height=table_height,
        rows=rows_list,
        n_data_rows=n_data_rows,
    )

    c.showPage()
    c.save()
    return out_path
