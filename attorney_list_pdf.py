# attorney_list_pdf.py
"""
PDF generator for the clinic-wide 'List of Attorneys' directory.

Public entry points:
    - build_attorney_list_pdf(out_path, *, clinic_name, attorneys)
    - canonical_pdf_paths(*, patient_root=None) -> dict
        Returns the canonical write paths the rest of the app uses so that
        every regeneration overwrites the SAME file (never creating
        list_of_attorneys (1).pdf, etc.).

Layout: portrait Letter, header band with clinic name + 'List of Attorneys',
generated date, and a paginated Table flowable listing each attorney with
firm, contact, phone, fax, email, and city/state.
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


# Filename is fixed so each regeneration overwrites the same file.
LIST_PDF_FILENAME = "List_of_Attorneys.pdf"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def canonical_pdf_paths(*, patient_root: str | os.PathLike | None = None) -> dict:
    """Where the 'List of Attorneys' PDF should always live.

    Returns:
        {
          "primary": <DATA_DIR>/exports/attorneys/List_of_Attorneys.pdf,
          "patient_copy": <patient_root>/vault/attorney/List_of_Attorneys.pdf
              (only present if patient_root is provided),
        }
    """
    from paths import exports_dir
    out: dict = {}
    primary = Path(exports_dir()) / "attorneys" / LIST_PDF_FILENAME
    out["primary"] = primary
    if patient_root:
        out["patient_copy"] = (
            Path(patient_root) / "vault" / "attorney" / LIST_PDF_FILENAME
        )
    return out


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
    """Paragraph for already-built HTML-ish markup (caller is responsible
    for escaping any user fragments inside)."""
    return Paragraph(html or "", style)


def _attorney_label_html(rec: dict) -> str:
    firm = (rec.get("firm_name") or "").strip()
    name = (rec.get("attorney_name") or "").strip()
    if firm and name:
        return f"<b>{_esc(firm)}</b><br/>{_esc(name)}"
    return f"<b>{_esc(firm or name or '(unnamed)')}</b>"


def _addr_line(rec: dict) -> str:
    cs = ", ".join(filter(None, [
        (rec.get("city") or "").strip(),
        (rec.get("state") or "").strip(),
    ]))
    z = (rec.get("zip") or "").strip()
    return (cs + " " + z).strip()


def _contact_line(rec: dict) -> str:
    bits = []
    if rec.get("contact_name"):
        bits.append(f"Contact: {rec['contact_name']}")
    if rec.get("paralegal_name"):
        bits.append(f"Paralegal: {rec['paralegal_name']}")
    if rec.get("case_manager"):
        bits.append(f"Case mgr: {rec['case_manager']}")
    return "  •  ".join(bits)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_attorney_list_pdf(
    out_path: str | os.PathLike,
    *,
    clinic_name: str,
    attorneys: Iterable[dict],
) -> str:
    """Render the 'List of Attorneys' PDF to out_path. Overwrites if exists."""
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab is not installed. Install with: pip install reportlab")

    out_path = str(out_path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    items = list(attorneys or [])

    page_w, page_h = LETTER
    margin = 0.5 * inch

    doc = SimpleDocTemplate(
        out_path,
        pagesize=LETTER,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="List of Attorneys",
        author="Chiro EMR",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AttyTitle", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=20, leading=24,
        alignment=1, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "AttySubtitle", parent=styles["Normal"],
        fontName="Helvetica", fontSize=10, leading=12,
        alignment=1, textColor=colors.HexColor("#444444"),
        spaceAfter=10,
    )
    h_style = ParagraphStyle(
        "AttyTableH", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=9, leading=11,
        textColor=colors.white, alignment=0,
    )
    cell_style = ParagraphStyle(
        "AttyCell", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, leading=11,
    )
    cell_dim_style = ParagraphStyle(
        "AttyCellDim", parent=cell_style,
        textColor=colors.HexColor("#555555"), fontSize=8, leading=10,
    )

    flow: list = []

    # --- Header band -----------------------------------------------------
    flow.append(_html_para(
        f"<b>{_esc((clinic_name or '').strip() or 'Attorney Directory')}</b>",
        subtitle_style,
    ))
    flow.append(_text_para("List of Attorneys", title_style))
    flow.append(_text_para(
        f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}  •  "
        f"{len(items)} attorney{'s' if len(items) != 1 else ''} on file",
        subtitle_style,
    ))
    flow.append(Spacer(1, 4))

    # --- Table -----------------------------------------------------------
    header_cells = [
        _text_para("#", h_style),
        _text_para("Firm / Attorney", h_style),
        _text_para("Phone", h_style),
        _text_para("Fax", h_style),
        _text_para("Email", h_style),
        _text_para("City, State", h_style),
    ]

    body_rows: list[list] = []
    for i, rec in enumerate(items, start=1):
        firm_cell_html = _attorney_label_html(rec)
        contact_line = _contact_line(rec)
        if contact_line:
            firm_cell_html += f"<br/><font size=8 color='#555555'>{_esc(contact_line)}</font>"

        # Address shown as smaller second line if present
        addr1 = (rec.get("address1") or "").strip()
        addr2 = (rec.get("address2") or "").strip()
        addr_extras = " ".join(filter(None, [addr1, addr2]))
        city_state_cell_html = _esc(_addr_line(rec))
        if addr_extras:
            city_state_cell_html = (
                f"{city_state_cell_html}"
                f"<br/><font size=8 color='#555555'>{_esc(addr_extras)}</font>"
            )

        body_rows.append([
            _text_para(str(i), cell_style),
            _html_para(firm_cell_html, cell_style),
            _text_para((rec.get("phone") or "").strip(), cell_style),
            _text_para((rec.get("fax") or "").strip(), cell_style),
            _text_para((rec.get("email") or "").strip(), cell_style),
            _html_para(city_state_cell_html, cell_style),
        ])

    if not body_rows:
        body_rows.append([
            _text_para("", cell_style),
            _html_para("<i>(no attorneys on file)</i>", cell_dim_style),
            _text_para("", cell_style), _text_para("", cell_style),
            _text_para("", cell_style), _text_para("", cell_style),
        ])

    table = Table(
        [header_cells] + body_rows,
        colWidths=[
            0.30 * inch,
            2.40 * inch,
            0.95 * inch,
            0.85 * inch,
            1.85 * inch,
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
        canv.drawString(margin, margin / 2, f"List of Attorneys — {datetime.now().strftime('%Y-%m-%d')}")
        page_str = f"Page {doc_.page}"
        canv.drawRightString(page_w - margin, margin / 2, page_str)
        canv.restoreState()

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    return out_path
