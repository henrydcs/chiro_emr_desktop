# insurance_pdf.py — Insurance statement / EOB PDFs.
from __future__ import annotations

from pathlib import Path

from billing_pdf import (
    REPORTLAB_OK,
    _draw_footer,
    _draw_header_band,
    _draw_title_block,
    _new_pdf_canvas,
    _new_receipt_path,
    _require_reportlab,
    _safe_filename_key,
)
from insurance_engine import claim_postings, get_claim_state
from insurance_receipt import (
    build_insurance_claim_summary_text,
    build_insurance_eob_text,
    save_insurance_claim_summary_receipt,
)

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors

    from billing_pdf import COLOR_TEXT_DARK, COLOR_TEXT_MUTED
except Exception:
    LETTER = None  # type: ignore


def _render_text_pdf(out_path: Path, *, title: str, body: str, subtitle: str = "") -> Path:
    _require_reportlab()
    page_w, page_h = LETTER
    c = _new_pdf_canvas(str(out_path), pagesize=LETTER)
    c.setTitle(title)
    y = _draw_header_band(c, page_w, page_h)
    y = _draw_title_block(c, page_w, y, title=title, subtitle=subtitle)
    margin = 0.55 * inch
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor(COLOR_TEXT_DARK))
    for raw_line in (body or "").splitlines():
        if y < margin + 50:
            c.showPage()
            y = page_h - margin - 20
        c.drawString(margin, y, raw_line[:110])
        y -= 12
    _draw_footer(c, page_w, page_h, note="Insurance billing record — confidential.")
    c.showPage()
    c.save()
    return out_path


def build_insurance_statement_pdf(
    patient_root: str | Path,
    *,
    patient_name: str,
    claim_id: str,
) -> Path:
    """Statement PDF + matching .txt sidecar for one claim."""
    st = get_claim_state(str(patient_root), claim_id)
    if not st:
        raise ValueError("Claim not found.")
    save_insurance_claim_summary_receipt(
        patient_root,
        patient_name=patient_name,
        claim_state=st,
    )
    postings = claim_postings(str(patient_root), claim_id)
    body = build_insurance_claim_summary_text(
        patient_name=patient_name,
        claim_state=st,
        postings=postings,
    )
    key = _safe_filename_key(claim_id)
    out = _new_receipt_path(
        patient_root,
        "insurance_statement",
        subfolder="insurance",
        unique_key=key,
    )
    return _render_text_pdf(
        out,
        title="Insurance Claim Statement",
        body=body,
        subtitle=f"Claim {claim_id}",
    )


def build_insurance_eob_pdf(
    patient_root: str | Path,
    *,
    patient_name: str,
    claim_id: str,
    posting: dict | None = None,
) -> Path:
    st = get_claim_state(str(patient_root), claim_id)
    if not st:
        raise ValueError("Claim not found.")
    posts = claim_postings(str(patient_root), claim_id)
    if not posts and not posting:
        raise ValueError("No payer posting on file for this claim.")
    post = posting or posts[-1]
    body = build_insurance_eob_text(
        patient_name=patient_name,
        claim_state=st,
        posting=post,
    )
    key = _safe_filename_key(claim_id)
    out = _new_receipt_path(
        patient_root,
        "insurance_eob",
        subfolder="insurance",
        unique_key=key,
    )
    from insurance_receipt import save_insurance_eob_receipt

    save_insurance_eob_receipt(
        patient_root,
        patient_name=patient_name,
        claim_state=st,
        posting=post,
    )
    return _render_text_pdf(
        out,
        title="Insurance Remittance / EOB",
        body=body,
        subtitle=f"Claim {claim_id}",
    )
