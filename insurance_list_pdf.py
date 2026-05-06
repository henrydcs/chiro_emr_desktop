# insurance_list_pdf.py
"""
PDF generator for the clinic-wide 'List of Insurance Carriers' directory.

Public entry points:
    - build_insurance_list_pdf(out_path, *, clinic_name, carriers)
    - canonical_pdf_paths() -> dict
        Returns the canonical write path the rest of the app uses so that
        every regeneration overwrites the SAME file (never creating
        list_of_insurances (1).pdf, etc.). The PDF lives in the shared
        Global Vault and is reachable from every patient chart.

Layout: portrait Letter, header band with clinic name + 'List of Insurance
Carriers', generated date, and a paginated Table flowable listing each
carrier with name/parent, payer ID, claims phone, fax, claims address,
portal, and notes.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


LIST_PDF_FILENAME = "List_of_Insurance_Carriers.pdf"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def canonical_pdf_paths() -> dict:
    """Where the 'List of Insurance Carriers' PDF should always live.

    The Insurance Directory is a clinic-wide reference document, so it lives
    in the shared Global Vault (visible from every patient chart's Global
    Vault tab).
    """
    from paths import global_vault_dir
    return {
        "primary": Path(global_vault_dir()) / "insurance" / LIST_PDF_FILENAME,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _esc(text: str) -> str:
    """XML-escape user-supplied text so it can be safely embedded into a
    ReportLab Paragraph that we build using HTML-ish tags (<b>, <br/>, etc.)."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _text_para(text: str, style: ParagraphStyle) -> Paragraph:
    """Paragraph for plain user text. Auto-escapes and converts \\n -> <br/>."""
    safe = _esc(text).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _html_para(html: str, style: ParagraphStyle) -> Paragraph:
    """Paragraph for already-built HTML-ish markup."""
    return Paragraph(html or "", style)


def _carrier_label_html(rec: dict) -> str:
    name = (rec.get("name") or "").strip()
    parent = (rec.get("parent_company") or "").strip()
    if name and parent and parent.lower() != name.lower():
        return f"<b>{_esc(name)}</b><br/><font size=8 color='#555555'>{_esc(parent)}</font>"
    return f"<b>{_esc(name or parent or '(unnamed carrier)')}</b>"


def _addr_block(rec: dict) -> str:
    a1 = (rec.get("claims_address1") or "").strip()
    a2 = (rec.get("claims_address2") or "").strip()
    cs = ", ".join(filter(None, [
        (rec.get("city") or "").strip(),
        (rec.get("state") or "").strip(),
    ]))
    z = (rec.get("zip") or "").strip()
    last_line = (cs + " " + z).strip()
    bits = [b for b in (a1, a2, last_line) if b]
    return "<br/>".join(_esc(b) for b in bits)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_insurance_list_pdf(
    out_path: str | os.PathLike,
    *,
    clinic_name: str,
    carriers: Iterable[dict],
) -> str:
    """Render the 'List of Insurance Carriers' PDF to out_path. Overwrites if exists."""
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab is not installed. Install with: pip install reportlab")

    out_path = str(out_path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    items = list(carriers or [])

    page_w, page_h = LETTER
    margin = 0.5 * inch

    doc = SimpleDocTemplate(
        out_path,
        pagesize=LETTER,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="List of Insurance Carriers",
        author="Chiro EMR",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InsTitle", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=20, leading=24,
        alignment=1, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "InsSubtitle", parent=styles["Normal"],
        fontName="Helvetica", fontSize=10, leading=12,
        alignment=1, textColor=colors.HexColor("#444444"),
        spaceAfter=10,
    )
    h_style = ParagraphStyle(
        "InsTableH", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=9, leading=11,
        textColor=colors.white, alignment=0,
    )
    cell_style = ParagraphStyle(
        "InsCell", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, leading=11,
    )
    cell_dim_style = ParagraphStyle(
        "InsCellDim", parent=cell_style,
        textColor=colors.HexColor("#555555"), fontSize=8, leading=10,
    )

    flow: list = []

    # --- Header band -----------------------------------------------------
    flow.append(_html_para(
        f"<b>{_esc((clinic_name or '').strip() or 'Insurance Directory')}</b>",
        subtitle_style,
    ))
    flow.append(_text_para("List of Insurance Carriers", title_style))
    flow.append(_text_para(
        f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}  •  "
        f"{len(items)} carrier{'s' if len(items) != 1 else ''} on file",
        subtitle_style,
    ))
    flow.append(Spacer(1, 4))

    # --- Table -----------------------------------------------------------
    header_cells = [
        _text_para("#", h_style),
        _text_para("Carrier", h_style),
        _text_para("Payer ID", h_style),
        _text_para("Claims Phone", h_style),
        _text_para("Fax", h_style),
        _text_para("Claims Address", h_style),
        _text_para("Portal / Notes", h_style),
    ]

    body_rows: list[list] = []
    for i, rec in enumerate(items, start=1):
        carrier_cell = _carrier_label_html(rec)
        addr_html = _addr_block(rec) or "—"

        portal = (rec.get("portal_url") or "").strip()
        notes = (rec.get("notes") or "").strip()
        portal_bits = []
        if portal:
            portal_bits.append(_esc(portal))
        if notes:
            portal_bits.append(f"<font size=8 color='#555555'>{_esc(notes)}</font>")
        portal_html = "<br/>".join(portal_bits) if portal_bits else "—"

        body_rows.append([
            _text_para(str(i), cell_style),
            _html_para(carrier_cell, cell_style),
            _text_para((rec.get("payer_id") or "").strip(), cell_style),
            _text_para((rec.get("claims_phone") or "").strip(), cell_style),
            _text_para((rec.get("fax") or "").strip(), cell_style),
            _html_para(addr_html, cell_style),
            _html_para(portal_html, cell_style),
        ])

    if not body_rows:
        body_rows.append([
            _text_para("", cell_style),
            _html_para("<i>(no carriers on file)</i>", cell_dim_style),
            _text_para("", cell_style), _text_para("", cell_style),
            _text_para("", cell_style), _text_para("", cell_style),
            _text_para("", cell_style),
        ])

    table = Table(
        [header_cells] + body_rows,
        colWidths=[
            0.30 * inch,
            1.85 * inch,
            0.75 * inch,
            0.95 * inch,
            0.85 * inch,
            1.65 * inch,
            1.15 * inch,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white, colors.HexColor("#F4F7FB"),
        ]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#1F4E79")),
        ("INNERGRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#D8DEE7")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1F4E79")),
    ]))

    flow.append(table)

    def _on_page(canv, doc_):
        canv.saveState()
        canv.setFont("Helvetica", 8)
        canv.setFillColor(colors.HexColor("#666666"))
        canv.drawString(margin, margin / 2, f"List of Insurance Carriers — {datetime.now().strftime('%Y-%m-%d')}")
        page_str = f"Page {doc_.page}"
        canv.drawRightString(page_w - margin, margin / 2, page_str)
        canv.restoreState()

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    return out_path
