"""
Landscape patient status sheet: one row per patient with key exam dates
and blank status checkboxes (for manual marking on printouts).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

from billing_engine import classify_exam_type

PDF_FILENAME = "Patient_Status_Sheet.pdf"


def canonical_pdf_path() -> Path:
    from paths import get_data_dir

    out = get_data_dir() / "shell" / "analytics" / PDF_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _parse_mmddyyyy(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y")
    except Exception:
        return None


def _earliest_date(dates: list[str]) -> str:
    best: tuple[datetime, str] | None = None
    for d in dates:
        dt = _parse_mmddyyyy(d)
        if dt is None:
            continue
        if best is None or dt < best[0]:
            best = (dt, d.strip())
    if best:
        return best[1]
    for d in dates:
        if (d or "").strip():
            return d.strip()
    return ""


def _latest_date(dates: list[str]) -> str:
    best: tuple[datetime, str] | None = None
    for d in dates:
        dt = _parse_mmddyyyy(d)
        if dt is None:
            continue
        if best is None or dt > best[0]:
            best = (dt, d.strip())
    if best:
        return best[1]
    for d in dates:
        if (d or "").strip():
            return d.strip()
    return ""


def exam_dates_for_patient(visits: Iterable[dict]) -> tuple[str, str, str, datetime | None]:
    """
    From collect_visits_for_patient rows, return
    (initial_date, first_reexam_date, last_final_date, sort_key_for_initial).
    Skips chiro visits; uses classify_exam_type for initial / re_exam / final only.
    """
    initials: list[str] = []
    reexams: list[str] = []
    finals: list[str] = []

    for v in visits or []:
        name = (v.get("exam_name") or "").strip()
        kind = classify_exam_type(name)
        if kind == "chiro" or kind is None:
            continue
        date_s = (v.get("exam_date") or "").strip()
        if not date_s:
            continue
        if kind == "initial":
            initials.append(date_s)
        elif kind == "re_exam":
            reexams.append(date_s)
        elif kind == "final":
            finals.append(date_s)

    d_initial = _earliest_date(initials)
    d_reexam = _earliest_date(reexams)
    d_final = _latest_date(finals)
    sort_key = _parse_mmddyyyy(d_initial)
    return d_initial, d_reexam, d_final, sort_key


def build_patient_status_rows(
    patients: Iterable[dict],
    *,
    collect_visits,
) -> list[dict]:
    """Build sorted row dicts for the PDF table."""
    rows: list[dict] = []
    for rec in patients or []:
        folder_s = (rec.get("folder") or "").strip()
        visits = collect_visits(Path(folder_s)) if folder_s else []
        d_initial, d_reexam, d_final, sort_key = exam_dates_for_patient(visits)
        rows.append({
            "last": (rec.get("last") or "").strip(),
            "first": (rec.get("first") or "").strip(),
            "dob": (rec.get("dob") or "").strip(),
            "date_initial": d_initial,
            "date_reexam": d_reexam,
            "date_final": d_final,
            "_sort": sort_key or datetime.max,
            "_pid": rec.get("patient_id") or "",
        })

    rows.sort(key=lambda r: (r["_sort"], (r["last"] or "").lower(), (r["first"] or "").lower(), r["_pid"]))
    return rows


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _cell_para(text: str, style: ParagraphStyle) -> Paragraph:
    safe = _esc(text).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _checkbox_para(style: ParagraphStyle) -> Paragraph:
    """Empty cell; light border drawn via TableStyle (pen-friendly)."""
    return Paragraph("&#160;", style)


def build_patient_status_pdf(
    out_path: str | os.PathLike,
    *,
    rows: list[dict],
) -> str:
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab is not installed. Install with: pip install reportlab")

    out_path = str(out_path)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    page_w, page_h = landscape(letter)
    margin = 0.35 * inch

    doc = SimpleDocTemplate(
        out_path,
        pagesize=landscape(letter),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=0.45 * inch,
        title="Patient Status Sheet",
        author="Chiro EMR",
    )

    styles = getSampleStyleSheet()
    hdr = ParagraphStyle(
        "PssHdr",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=10,
        alignment=1,
    )
    cell = ParagraphStyle(
        "PssCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=10,
    )
    cell_center = ParagraphStyle(
        "PssCellC",
        parent=cell,
        alignment=1,
    )

    header = [
        _cell_para("Last", hdr),
        _cell_para("First", hdr),
        _cell_para("DOB", hdr),
        _cell_para("Initial", hdr),
        _cell_para("1st Re-Exam", hdr),
        _cell_para("Final", hdr),
        _cell_para("Active", hdr),
        _cell_para("Active NS", hdr),
        _cell_para("Auto Disch.", hdr),
        _cell_para("Dropped", hdr),
    ]

    body: list[list] = []
    for r in rows:
        body.append([
            _cell_para(r.get("last") or "", cell),
            _cell_para(r.get("first") or "", cell),
            _cell_para(r.get("dob") or "", cell),
            _cell_para(r.get("date_initial") or "", cell),
            _cell_para(r.get("date_reexam") or "", cell),
            _cell_para(r.get("date_final") or "", cell),
            _checkbox_para(cell_center),
            _checkbox_para(cell_center),
            _checkbox_para(cell_center),
            _checkbox_para(cell_center),
        ])

    if not body:
        body.append([_cell_para("(no patients on file)", cell)] + [_cell_para("", cell)] * 9)

    col_w = [
        1.35 * inch,
        1.15 * inch,
        0.85 * inch,
        0.85 * inch,
        0.95 * inch,
        0.85 * inch,
        0.62 * inch,
        0.72 * inch,
        0.95 * inch,
        0.62 * inch,
    ]

    table = Table([header] + body, colWidths=col_w, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (6, 1), (-1, -1), "CENTER"),
        ("BACKGROUND", (6, 1), (9, -1), colors.white),
        ("BOX", (6, 1), (9, -1), 0.35, colors.HexColor("#B8B8B8")),
        ("TOPPADDING", (6, 1), (9, -1), 7),
        ("BOTTOMPADDING", (6, 1), (9, -1), 7),
    ]))

    n_patients = len(rows)
    n_finals = sum(1 for r in rows if (r.get("date_final") or "").strip())
    summary_style = ParagraphStyle(
        "PssSummary",
        parent=cell,
        fontSize=10,
        leading=12,
    )
    summary = Paragraph(
        f"<b>Total Number of Patient</b> {n_patients}&#160;&#160;&#160;&#160;&#160;"
        f"<b>Total Number of Finals</b> {n_finals}",
        summary_style,
    )
    flow = [summary, Spacer(1, 0.12 * inch), table, Spacer(1, 0.05 * inch)]

    def _on_page(canv, doc_):
        canv.saveState()
        canv.setFont("Helvetica", 9)
        canv.setFillColor(colors.HexColor("#444444"))
        canv.drawRightString(page_w - margin, margin * 0.35, f"Page {doc_.page}")
        canv.restoreState()

    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    return out_path
