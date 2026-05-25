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


def _receipts_dir(patient_root: str | Path) -> Path:
    d = patient_billing_root(patient_root) / "receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _new_receipt_path(patient_root: str | Path, prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _receipts_dir(patient_root) / f"{prefix}_{stamp}.pdf"


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
    return y_top - 28


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
    c = pdf_canvas.Canvas(out_path, pagesize=LETTER)
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
    c = pdf_canvas.Canvas(out_path, pagesize=LETTER)
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
    c = pdf_canvas.Canvas(out_path, pagesize=LETTER)
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
    out = _new_receipt_path(patient_root, "receipt")
    build_cash_receipt_pdf(
        out,
        patient_name=patient_name,
        patient_root=patient_root,
        posted=posted,
        payment=payment,
    )
    return out


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
    out = _new_receipt_path(patient_root, "settlement")
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
    out = _new_receipt_path(patient_root, "pi_case_statement")
    build_pi_case_pdf(
        out,
        patient_name=patient_name,
        patient_root=patient_root,
    )
    return out
