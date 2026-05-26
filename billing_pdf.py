# billing_pdf.py — Modern PDF receipts for cash and PI ledger documents.
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

from config import CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX, LOGO_PATH
from billing_ledger import compute_cash_balance, encounter_amount_due
from billing_pi_case import case_status_label, load_pi_case
from billing_pi_ledger import compute_pi_balance, list_pi_posted_encounters, load_pi_ledger
from billing_storage import patient_billing_root


COLOR_PRIMARY = "#1E3A8A"
COLOR_ACCENT = "#2563EB"
COLOR_BORDER = "#CBD5E1"
COLOR_TEXT_DARK = "#0F172A"
COLOR_TEXT_MUTED = "#475569"
COLOR_BG_BAND = "#F1F5F9"
COLOR_BG_TOTAL = "#EFF6FF"


def _require_reportlab() -> None:
    if not REPORTLAB_OK:
        raise RuntimeError(
            "ReportLab is required for PDF receipts.\nInstall with: pip install reportlab"
        )


# --------------------------------------------------------------------------
# Page numbering — shared across every billing / package / referral PDF
# --------------------------------------------------------------------------
# ReportLab's low-level canvas can't know the total page count until the
# document is finished. The canonical fix is the "two-pass" NumberedCanvas
# pattern: override showPage() to defer the actual emit, snapshot every
# page's state, and on save() iterate through the snapshots stamping
# "Page N of M" before truly emitting each page.
#
# Builders that previously instantiated `pdf_canvas.Canvas(...)` directly
# now build a `NumberedCanvas(...)` instead; nothing else needs to change
# in their drawing code, and the footer is drawn on every page including
# any page-breaks triggered mid-loop by `_ensure_room()`-style helpers.

if REPORTLAB_OK:
    class NumberedCanvas(pdf_canvas.Canvas):
        """Canvas that stamps 'Page N of M' bottom-right on every page."""

        _PAGE_NUM_FONT = "Helvetica"
        _PAGE_NUM_SIZE = 8
        _PAGE_NUM_RIGHT_MARGIN = 0.55 * inch
        _PAGE_NUM_BASELINE = 0.40 * inch

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict] = []

        def showPage(self):  # type: ignore[override]
            # Snapshot the canvas state and start a fresh page WITHOUT
            # emitting the current one — final emit happens in save().
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):  # type: ignore[override]
            total = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_page_number(total)
                # Bypass our overridden showPage() to actually emit.
                pdf_canvas.Canvas.showPage(self)
            pdf_canvas.Canvas.save(self)

        def _draw_page_number(self, total_pages: int) -> None:
            page_w, _page_h = self._pagesize
            self.saveState()
            try:
                self.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
                self.setFont(self._PAGE_NUM_FONT, self._PAGE_NUM_SIZE)
                self.drawRightString(
                    page_w - self._PAGE_NUM_RIGHT_MARGIN,
                    self._PAGE_NUM_BASELINE,
                    f"Page {self._pageNumber} of {total_pages}",
                )
            finally:
                self.restoreState()
else:
    # ReportLab is missing; provide a stub so type-checking imports still
    # work. _require_reportlab() will raise before anything calls this.
    NumberedCanvas = None  # type: ignore[assignment,misc]


def _new_pdf_canvas(out_path: str | Path, *, pagesize=LETTER):
    """
    Factory for the page-numbered canvas. Use this in place of
    `pdf_canvas.Canvas(out_path, pagesize=...)` so every billing-style PDF
    gets a "Page N of M" footer for free.
    """
    _require_reportlab()
    return NumberedCanvas(str(out_path), pagesize=pagesize)


def _receipts_dir(patient_root: str | Path, subfolder: str = "") -> Path:
    """
    Returns the receipts directory (optionally a subfolder). The base layout is:

        <patient>/billing/receipts/                    (legacy flat folder)
        <patient>/billing/receipts/cash/               (cash receipts)
        <patient>/billing/receipts/package/            (package contracts/statements)
        <patient>/billing/receipts/pi/                 (PI summaries / settlements)
        <patient>/billing/receipts/insurance/          (reserved for future)
        <patient>/billing/receipts/membership/         (reserved for future)

    Receipts in subfolders are still surfaced by list_billing_documents() so
    the in-app Receipt folder dialog shows everything in one list.
    """
    base = patient_billing_root(patient_root) / "receipts"
    if subfolder:
        d = base / subfolder.strip().strip("/").strip("\\")
    else:
        d = base
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename_key(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (s or "").strip())


def _new_receipt_path(
    patient_root: str | Path,
    prefix: str,
    subfolder: str = "",
    *,
    unique_key: str = "",
) -> Path:
    """
    Build a PDF path inside the receipts folder.

    When `unique_key` is provided, the path uses that key INSTEAD of a timestamp
    suffix, so re-saving for the same encounter/package OVERWRITES the previous
    PDF (one receipt per visit / one contract per package). When omitted, a
    timestamp suffix is used (legacy behavior — produces a new file each call).
    """
    if unique_key:
        suffix = _safe_filename_key(unique_key)
    else:
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _receipts_dir(patient_root, subfolder=subfolder) / f"{prefix}_{suffix}.pdf"


def _draw_header_band(c: "pdf_canvas.Canvas", page_w: float, page_h: float) -> float:
    """Logo + clinic block. Returns the Y coord just below the band."""
    margin = 0.55 * inch
    band_top = page_h - margin
    logo_w = 1.05 * inch
    logo_h = 1.05 * inch

    logo_x = margin
    logo_y = band_top - logo_h

    text_x = logo_x + logo_w + 14
    text_top = band_top - 4

    if LOGO_PATH and os.path.exists(LOGO_PATH):
        try:
            img = ImageReader(LOGO_PATH)
            c.drawImage(
                img,
                logo_x,
                logo_y,
                width=logo_w,
                height=logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
    c.setFont("Helvetica-Bold", 15)
    c.drawString(text_x, text_top - 14, (CLINIC_NAME or "Clinic").strip())

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.drawString(text_x, text_top - 30, (CLINIC_ADDR or "").strip())
    c.drawString(text_x, text_top - 44, (CLINIC_PHONE_FAX or "").strip())

    rule_y = logo_y - 14
    c.setStrokeColor(colors.HexColor(COLOR_BORDER))
    c.setLineWidth(0.6)
    c.line(margin, rule_y, page_w - margin, rule_y)

    return rule_y - 12


def _draw_title_block(
    c: "pdf_canvas.Canvas",
    page_w: float,
    y_top: float,
    *,
    title: str,
    subtitle: str = "",
    receipt_no: str = "",
) -> float:
    margin = 0.55 * inch

    c.setFillColor(colors.HexColor(COLOR_PRIMARY))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, y_top - 22, title)

    next_y = y_top - 24
    if subtitle:
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.setFont("Helvetica", 10)
        c.drawString(margin, next_y - 14, subtitle)
        next_y -= 16

    if receipt_no:
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.setFont("Helvetica", 10)
        c.drawRightString(page_w - margin, y_top - 16, f"Receipt #: {receipt_no}")
        c.drawRightString(
            page_w - margin,
            y_top - 30,
            f"Issued: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
        )

    return next_y - 16


def _draw_info_grid(
    c: "pdf_canvas.Canvas",
    page_w: float,
    y_top: float,
    *,
    title: str,
    pairs_left: list[tuple[str, str]],
    pairs_right: list[tuple[str, str]],
) -> float:
    margin = 0.55 * inch
    inner_w = page_w - 2 * margin

    c.setFillColor(colors.HexColor(COLOR_BG_BAND))
    c.rect(margin, y_top - 18, inner_w, 18, stroke=0, fill=1)

    c.setFillColor(colors.HexColor(COLOR_PRIMARY))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 10, y_top - 13, title.upper())

    line_y = y_top - 18 - 14
    col_gap = 18
    col_w = (inner_w - col_gap) / 2
    label_font = ("Helvetica", 9)
    value_font = ("Helvetica-Bold", 10)
    row_height = 16

    n_rows = max(len(pairs_left), len(pairs_right))
    for i in range(n_rows):
        row_y = line_y - i * row_height
        if i < len(pairs_left):
            label, value = pairs_left[i]
            c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
            c.setFont(*label_font)
            c.drawString(margin, row_y, label)
            c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
            c.setFont(*value_font)
            c.drawString(margin + 80, row_y, str(value or "—"))
        if i < len(pairs_right):
            label, value = pairs_right[i]
            col_x = margin + col_w + col_gap
            c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
            c.setFont(*label_font)
            c.drawString(col_x, row_y, label)
            c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
            c.setFont(*value_font)
            c.drawString(col_x + 80, row_y, str(value or "—"))

    bottom_y = line_y - n_rows * row_height
    return bottom_y - 4


def _draw_section_header(
    c: "pdf_canvas.Canvas",
    page_w: float,
    y_top: float,
    title: str,
) -> float:
    margin = 0.55 * inch
    c.setFillColor(colors.HexColor(COLOR_PRIMARY))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y_top - 14, title.upper())
    c.setStrokeColor(colors.HexColor(COLOR_BORDER))
    c.setLineWidth(0.7)
    c.line(margin, y_top - 20, page_w - margin, y_top - 20)
    # Leave a clear gap (~16px) between the section underline and the first
    # data row. Without this, bold values like "pkg_6d4cc7e92beb" visually
    # collide with the line above them — see the Statement of Account PDF
    # where Package ID / Payment status / Visits / Event log all sit right
    # under their dividers. This single bump (was 8px) applies to every
    # PDF that uses this helper.
    return y_top - 36


def _draw_charges_table(
    c: "pdf_canvas.Canvas",
    page_w: float,
    y_top: float,
    *,
    lines: list[dict],
) -> float:
    margin = 0.55 * inch
    inner_w = page_w - 2 * margin

    col_cpt_x = margin
    col_desc_x = margin + 0.7 * inch
    col_units_x = page_w - margin - 1.8 * inch
    col_amt_x = page_w - margin

    c.setFillColor(colors.HexColor(COLOR_BG_BAND))
    c.rect(margin, y_top - 16, inner_w, 16, stroke=0, fill=1)
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(col_cpt_x + 4, y_top - 12, "CPT")
    c.drawString(col_desc_x + 2, y_top - 12, "DESCRIPTION")
    c.drawRightString(col_units_x + 0.5 * inch, y_top - 12, "UNITS")
    c.drawRightString(col_amt_x - 4, y_top - 12, "AMOUNT")

    row_y = y_top - 16
    c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
    c.setFont("Helvetica", 10)
    for ln in lines or []:
        if not isinstance(ln, dict):
            continue
        row_y -= 18
        cpt = ln.get("cpt_code") or ""
        mod = ln.get("modifier_1") or ""
        cpt_text = f"{cpt}-{mod}" if mod else cpt
        desc = (ln.get("description") or "").strip()
        units = ln.get("units") or 1
        amt = float(ln.get("amount") or 0)

        c.setFont("Helvetica-Bold", 10)
        c.drawString(col_cpt_x + 4, row_y, cpt_text)
        c.setFont("Helvetica", 10)
        c.drawString(col_desc_x + 2, row_y, desc[:48])
        c.drawRightString(col_units_x + 0.5 * inch, row_y, f"{float(units):g}")
        c.drawRightString(col_amt_x - 4, row_y, f"${amt:,.2f}")

        c.setStrokeColor(colors.HexColor(COLOR_BORDER))
        c.setLineWidth(0.3)
        c.line(margin, row_y - 6, page_w - margin, row_y - 6)

    return row_y - 14


def _draw_totals_box(
    c: "pdf_canvas.Canvas",
    page_w: float,
    y_top: float,
    *,
    rows: list[tuple[str, str, bool]],
) -> float:
    """rows: list of (label, value_text, emphasized)."""
    margin = 0.55 * inch
    box_w = 2.9 * inch
    box_x = page_w - margin - box_w

    line_h = 18
    box_h = line_h * len(rows) + 14

    c.setFillColor(colors.HexColor(COLOR_BG_TOTAL))
    c.setStrokeColor(colors.HexColor(COLOR_ACCENT))
    c.setLineWidth(0.8)
    c.roundRect(box_x, y_top - box_h, box_w, box_h, 6, stroke=1, fill=1)

    y = y_top - 18
    for label, value, emph in rows:
        if emph:
            c.setFillColor(colors.HexColor(COLOR_PRIMARY))
            c.setFont("Helvetica-Bold", 12)
        else:
            c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
            c.setFont("Helvetica", 10)
        c.drawString(box_x + 14, y, label)
        c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
        if emph:
            c.setFont("Helvetica-Bold", 13)
        else:
            c.setFont("Helvetica", 11)
        c.drawRightString(box_x + box_w - 14, y, value)
        y -= line_h

    return y_top - box_h - 16


def _draw_footer(
    c: "pdf_canvas.Canvas",
    page_w: float,
    page_h: float,
    *,
    note: str = "Thank you for your visit.",
) -> None:
    margin = 0.55 * inch
    c.setStrokeColor(colors.HexColor(COLOR_BORDER))
    c.setLineWidth(0.6)
    c.line(margin, 0.7 * inch, page_w - margin, 0.7 * inch)
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(margin, 0.55 * inch, note)
    c.drawRightString(
        page_w - margin,
        0.55 * inch,
        f"Generated {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def build_cash_receipt_pdf(
    out_path: str | Path,
    *,
    patient_name: str,
    patient_root: str | Path,
    posted: dict,
    payment: dict | None = None,
) -> str:
    _require_reportlab()
    out_path = str(out_path)
    page_w, page_h = LETTER
    c = _new_pdf_canvas(out_path, pagesize=LETTER)
    c.setTitle("Service Receipt" if not payment else "Payment Receipt")
    c.setAuthor("Chiro EMR")

    y = _draw_header_band(c, page_w, page_h)

    receipt_no = (posted.get("encounter_id") or "").upper()[-6:] or datetime.now().strftime("%H%M%S")
    title = "PAYMENT RECEIPT" if payment else "SERVICE RECEIPT"
    subtitle = "Cash / Self-pay desk transaction"
    y = _draw_title_block(c, page_w, y, title=title, subtitle=subtitle, receipt_no=receipt_no)

    dos = posted.get("date_of_service") or "—"
    exam = posted.get("exam_name") or "Visit"
    provider = posted.get("provider") or "—"

    y = _draw_info_grid(
        c,
        page_w,
        y,
        title="Patient & Visit",
        pairs_left=[
            ("Patient", patient_name or "—"),
            ("Date of Service", dos),
            ("Visit", exam),
        ],
        pairs_right=[
            ("Provider", provider),
            ("Status", "Posted to cash ledger"),
        ],
    )

    y = _draw_section_header(c, page_w, y, "Charges")
    y = _draw_charges_table(c, page_w, y, lines=posted.get("lines") or [])

    total = float(posted.get("amount_charged") or 0)
    exam_path = posted.get("exam_path") or ""
    visit_due = encounter_amount_due(patient_root, exam_path) if exam_path else total
    account_balance = compute_cash_balance(patient_root)["balance_due"]

    rows: list[tuple[str, str, bool]] = [
        ("Visit total", f"${total:,.2f}", False),
    ]
    if payment:
        pamt = float(payment.get("amount") or 0)
        method = (payment.get("method") or "cash").title()
        rows.append((f"Paid ({method})", f"${pamt:,.2f}", False))
    if visit_due <= 0.01:
        rows.append(("Visit balance", "PAID IN FULL", True))
    else:
        rows.append(("Visit balance", f"${visit_due:,.2f}", True))
    rows.append(("Account balance", f"${account_balance:,.2f}", False))

    y = _draw_totals_box(c, page_w, y, rows=rows)

    _draw_footer(c, page_w, page_h, note="Thank you for your visit.")

    c.showPage()
    c.save()
    return out_path


def build_settlement_pdf(
    out_path: str | Path,
    *,
    patient_name: str,
    patient_root: str | Path,
    settlement_amount: float,
    write_off: float,
    balance_before: float,
    payment_date: str,
    payer: str,
    memo: str = "",
) -> str:
    _require_reportlab()
    out_path = str(out_path)
    page_w, page_h = LETTER
    c = _new_pdf_canvas(out_path, pagesize=LETTER)
    c.setTitle("PI Settlement Receipt")
    c.setAuthor("Chiro EMR")

    y = _draw_header_band(c, page_w, page_h)

    case = load_pi_case(patient_root) or {}
    bal = compute_pi_balance(patient_root)

    receipt_no = datetime.now().strftime("S%Y%m%d-%H%M%S")
    y = _draw_title_block(
        c,
        page_w,
        y,
        title="SETTLEMENT RECEIPT",
        subtitle="Personal Injury case — lump-sum payment",
        receipt_no=receipt_no,
    )

    atty = case.get("attorney") or {}
    atty_line = (atty.get("name") or "—").strip()
    if atty.get("firm"):
        atty_line = f"{atty_line} — {atty['firm']}".strip(" —")

    y = _draw_info_grid(
        c,
        page_w,
        y,
        title="Patient & Case",
        pairs_left=[
            ("Patient", patient_name or "—"),
            ("Date of Injury", (case.get("date_of_injury") or "").strip() or "—"),
            ("Claim #", (case.get("claim_number") or "").strip() or "—"),
        ],
        pairs_right=[
            ("Case status", case_status_label(case.get("case_status") or "")),
            ("Attorney", atty_line[:38]),
            ("Payment date", payment_date or "—"),
        ],
    )

    y = _draw_section_header(c, page_w, y, "Settlement")
    margin = 0.55 * inch
    c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Received from: {(payer or 'attorney').strip().title()}")
    if memo:
        c.drawString(margin, y - 16, f"Memo: {memo[:80]}")
        y -= 18
    y -= 22

    rows: list[tuple[str, str, bool]] = [
        ("Balance before", f"${balance_before:,.2f}", False),
        ("Settlement received", f"${settlement_amount:,.2f}", False),
    ]
    if write_off > 0.01:
        rows.append(("Write-off (auto)", f"${write_off:,.2f}", False))
    rows.append(("Case balance now", f"${bal['balance_due']:,.2f}", True))

    y = _draw_totals_box(c, page_w, y, rows=rows)

    y = _draw_section_header(c, page_w, y, "Case Totals")
    c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
    c.setFont("Helvetica", 10)
    for label, value in (
        ("Total charges", f"${bal['total_charges']:,.2f}"),
        ("Total payments", f"${bal['total_payments']:,.2f}"),
        ("Total adjustments", f"${bal['total_adjustments']:,.2f}"),
    ):
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.setFont("Helvetica", 10)
        c.drawString(margin, y, label)
        c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(page_w - margin, y, value)
        y -= 16

    _draw_footer(c, page_w, page_h, note="Confidential — for billing records.")

    c.showPage()
    c.save()
    return out_path


def build_pi_case_pdf(
    out_path: str | Path,
    *,
    patient_name: str,
    patient_root: str | Path,
) -> str:
    _require_reportlab()
    out_path = str(out_path)
    page_w, page_h = LETTER
    c = _new_pdf_canvas(out_path, pagesize=LETTER)
    c.setTitle("PI Case Statement")
    c.setAuthor("Chiro EMR")

    y = _draw_header_band(c, page_w, page_h)

    case = load_pi_case(patient_root) or {}
    bal = compute_pi_balance(patient_root)
    settlement = case.get("settlement") if isinstance(case.get("settlement"), dict) else None

    receipt_no = (case.get("case_id") or "").replace("case_", "").upper()[:8] or "—"
    title = "PI CASE STATEMENT"
    subtitle = case_status_label(case.get("case_status") or "active") + " case"
    y = _draw_title_block(c, page_w, y, title=title, subtitle=subtitle, receipt_no=receipt_no)

    atty = case.get("attorney") or {}
    atty_line = (atty.get("name") or "—").strip()
    if atty.get("firm"):
        atty_line = f"{atty_line} — {atty['firm']}".strip(" —")

    y = _draw_info_grid(
        c,
        page_w,
        y,
        title="Patient & Case",
        pairs_left=[
            ("Patient", patient_name or "—"),
            ("Date of Injury", (case.get("date_of_injury") or "").strip() or "—"),
            ("Claim #", (case.get("claim_number") or "").strip() or "—"),
        ],
        pairs_right=[
            ("Case status", case_status_label(case.get("case_status") or "")),
            ("Attorney", atty_line[:38]),
            ("Visits posted", str(len(list_pi_posted_encounters(patient_root)))),
        ],
    )

    y = _draw_section_header(c, page_w, y, "Financial Summary")
    rows: list[tuple[str, str, bool]] = [
        ("Total charges", f"${bal['total_charges']:,.2f}", False),
        ("Total payments", f"${bal['total_payments']:,.2f}", False),
        ("Total adjustments", f"${bal['total_adjustments']:,.2f}", False),
        ("Balance due", f"${bal['balance_due']:,.2f}", True),
    ]
    y = _draw_totals_box(c, page_w, y, rows=rows)

    if settlement:
        y = _draw_section_header(c, page_w, y, "Settlement on File")
        margin = 0.55 * inch
        s_rows = [
            ("Settlement amount", f"${float(settlement.get('amount') or 0):,.2f}"),
            ("Write-off", f"${float(settlement.get('write_off') or 0):,.2f}"),
            ("Payment date", (settlement.get("payment_date") or "—")),
            ("Received from", (settlement.get("payer") or "—").title()),
        ]
        for label, value in s_rows:
            c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
            c.setFont("Helvetica", 10)
            c.drawString(margin, y, label)
            c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(page_w - margin, y, str(value))
            y -= 16

    y -= 6
    y = _draw_section_header(c, page_w, y, "Visits / Charge Detail")

    margin = 0.55 * inch
    visits = list_pi_posted_encounters(patient_root)
    if not visits:
        c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(margin, y, "No PI-posted visits on file.")
    else:
        c.setFont("Helvetica", 9)
        for enc in visits:
            if y < 1.2 * inch:
                _draw_footer(c, page_w, page_h, note="Confidential — for billing records.")
                c.showPage()
                y = _draw_header_band(c, page_w, page_h)
                y = _draw_section_header(c, page_w, y, "Visits / Charge Detail (cont.)")

            dos = enc.get("date_of_service") or "—"
            exam = enc.get("exam_name") or "Visit"
            amt = float(enc.get("amount_charged") or 0)
            c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, y, f"{dos}  ·  {exam}")
            c.drawRightString(page_w - margin, y, f"${amt:,.2f}")
            y -= 14
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor(COLOR_TEXT_MUTED))
            for ln in enc.get("lines") or []:
                if not isinstance(ln, dict):
                    continue
                cpt = ln.get("cpt_code") or ""
                mod = ln.get("modifier_1") or ""
                cpt_text = f"{cpt}-{mod}" if mod else cpt
                desc = (ln.get("description") or "").strip()
                units = ln.get("units") or 1
                line_amt = float(ln.get("amount") or 0)
                c.drawString(margin + 14, y, f"{cpt_text}  ×{float(units):g}  {desc[:48]}")
                c.drawRightString(page_w - margin, y, f"${line_amt:,.2f}")
                y -= 12
            y -= 6

    _draw_footer(c, page_w, page_h, note="Confidential — for billing records.")

    c.showPage()
    c.save()
    return out_path


def build_cash_receipt_to_receipts(
    patient_root: str | Path,
    *,
    patient_name: str,
    posted: dict,
    payment: dict | None = None,
) -> Path:
    # One receipt per visit — keyed by encounter_id (preferred) or exam stem so
    # re-clicking Create PDF on the same visit OVERWRITES the previous file
    # instead of leaving piles of timestamped duplicates in the cash folder.
    unique_key = (posted.get("encounter_id") or "").strip()
    if not unique_key:
        unique_key = Path(posted.get("exam_path") or "").stem or ""
    out = _new_receipt_path(
        patient_root, "receipt", subfolder="cash", unique_key=unique_key,
    )
    build_cash_receipt_pdf(
        out,
        patient_name=patient_name,
        patient_root=patient_root,
        posted=posted,
        payment=payment,
    )
    return out


def build_pdf_from_text(out_path: Path, text: str) -> Path:
    """
    Fallback PDF builder — renders the given plain text as a single-document
    monospaced PDF. Used when a cash receipt has a .txt on disk but no
    properly-formatted .pdf and the original posted-encounter data isn't
    available for `build_cash_receipt_pdf()`.
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab not installed; cannot generate PDF.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = _new_pdf_canvas(out_path, pagesize=LETTER)
    page_w, page_h = LETTER
    margin = 0.75 * inch
    line_h = 12
    y = page_h - margin
    c.setFont("Courier", 10)
    for raw in (text or "").splitlines() or [""]:
        if y < margin:
            c.showPage()
            c.setFont("Courier", 10)
            y = page_h - margin
        # ReportLab Courier supports basic ASCII; non-ascii chars need encoding.
        try:
            c.drawString(margin, y, raw)
        except Exception:
            c.drawString(margin, y, raw.encode("ascii", "replace").decode("ascii"))
        y -= line_h
    c.save()
    return out_path


def ensure_cash_receipt_pdf(
    patient_root: str | Path,
    pdf_path: Path,
    *,
    patient_name: str,
    text_sidecar: Path | None = None,
) -> Path:
    """
    Ensure a cash receipt PDF exists at `pdf_path`, lazy-generating it if not.

    Lookup strategy when the file is missing:
      1) If the filename is `receipt_<encounter_id>.pdf`, look up the posted
         encounter by id and render the full formatted receipt
         (`build_cash_receipt_pdf`).
      2) Otherwise — or if step 1 fails — fall back to a monospaced text-only
         PDF built from `text_sidecar` (so the user still gets a printable
         document).

    Returns the path to the now-existing PDF.
    """
    if pdf_path.exists():
        return pdf_path

    # Try the structured path first: receipt_<encounter_id>.pdf
    stem = pdf_path.stem
    if stem.startswith("receipt_"):
        encounter_id = stem[len("receipt_"):]
        if encounter_id.startswith("enc_"):
            try:
                from billing_ledger import find_posted_encounter_by_id
                posted = find_posted_encounter_by_id(patient_root, encounter_id)
            except Exception:
                posted = None
            if posted:
                try:
                    return build_cash_receipt_to_receipts(
                        patient_root,
                        patient_name=patient_name,
                        posted=posted,
                        payment=None,
                    )
                except Exception:
                    pass  # fall through to text fallback

    # Fallback: render the .txt sidecar (or a placeholder) as a simple PDF.
    text = ""
    if text_sidecar is not None and text_sidecar.is_file():
        try:
            text = text_sidecar.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    if not text:
        text = (
            f"Cash receipt\n"
            f"Patient: {patient_name}\n"
            f"(Original receipt content was not available on disk.)"
        )
    return build_pdf_from_text(pdf_path, text)


def build_settlement_to_receipts(
    patient_root: str | Path,
    *,
    patient_name: str,
    settlement_amount: float,
    write_off: float,
    balance_before: float,
    payment_date: str,
    payer: str,
    memo: str = "",
) -> Path:
    out = _new_receipt_path(patient_root, "settlement", subfolder="pi")
    build_settlement_pdf(
        out,
        patient_name=patient_name,
        patient_root=patient_root,
        settlement_amount=settlement_amount,
        write_off=write_off,
        balance_before=balance_before,
        payment_date=payment_date,
        payer=payer,
        memo=memo,
    )
    return out


def build_pi_case_to_receipts(
    patient_root: str | Path,
    *,
    patient_name: str,
) -> Path:
    out = _new_receipt_path(patient_root, "pi_case_statement", subfolder="pi")
    build_pi_case_pdf(
        out,
        patient_name=patient_name,
        patient_root=patient_root,
    )
    return out
