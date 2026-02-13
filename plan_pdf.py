# plan_pdf.py
from __future__ import annotations
from reportlab.lib.units import inch

from xml.sax.saxutils import escape as xml_escape

try:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib import colors
    REPORTLAB_OK = True
except ModuleNotFoundError:
    REPORTLAB_OK = False


def _clean(s: str) -> str:
    return (s or "").strip()


def _list_or_empty(x):
    return x if isinstance(x, (list, tuple)) else []


def build_plan_flowables(plan_struct: dict, styles) -> list:
    """
    Returns a list of ReportLab flowables for the Plan section.
    plan_struct is expected to be what PlanPage.get_struct() returns.
    """
    if not REPORTLAB_OK:
        return []

    d = plan_struct or {}
    care = _list_or_empty(d.get("care_types"))
    regions = _list_or_empty(d.get("regions"))
    goals = _list_or_empty(d.get("goals"))
    freq = _clean(str(d.get("frequency_per_week", "")))
    dur = _clean(str(d.get("duration_weeks", "")))
    reeval = _clean(str(d.get("reeval", "")))
    notes = _clean(d.get("custom_notes", ""))
    plan_text = _clean(d.get("plan_text", ""))

    # Strip AUTO tag if present
    if plan_text.startswith("[AUTO:PLAN]"):
        plan_text = plan_text.replace("[AUTO:PLAN]", "", 1).strip()

    # If everything is empty, return nothing (prevents blank section)
    if not (care or regions or goals or freq or dur or reeval or notes or plan_text):
        return []

    # Match your other major section titles (Diagnosis/Objectives)
    H = styles["Heading2"] if "Heading2" in styles else styles["Heading3"]
    B = styles["BodyText"]

    story = []

    # Upright + bold title (no italics)
    story.append(Paragraph("<b>PLAN OF CARE</b>", H))
    story.append(Spacer(1, 6))

        
    # Summary grid (quick scan)
    grid_data = [
        ["Care Type(s):", ", ".join(care) if care else ""],
        ["Regions:", ", ".join(regions) if regions else ""],
        ["Frequency:", f"{freq} / week" if freq else ""],
        ["Duration:", f"{dur} weeks" if dur else ""],
        ["Re-evaluation:", reeval],
        ["Goals:", ", ".join(goals) if goals else ""],
    ]

    label_w = 1.35 * inch
    value_w = 5.75 * inch

    t = Table(grid_data, colWidths=[label_w, value_w])

    # remove completely empty rows (label+blank)
    grid_data = [row for row in grid_data if _clean(row[1])]
    

    if grid_data:
        # Let the table size naturally so it aligns flush with the left margin
        t = Table(grid_data)
        t.hAlign = "LEFT"
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),

                    # Make the table start exactly where the title starts
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),

                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 8))

    # Narrative
    if plan_text:
        safe = xml_escape(plan_text).replace("\n", "<br/>")
        story.append(Paragraph(safe, B))
        story.append(Spacer(1, 8))

    # Notes (always separate paragraph)
    if notes:
        story.append(Spacer(1, 8))
        safe = xml_escape(notes).replace("\n", "<br/>")
        story.append(Paragraph("<b>Notes:</b>", B))
        story.append(Spacer(1, 4))
        story.append(Paragraph(safe, B))
        story.append(Spacer(1, 8))



    return [KeepTogether(story)]

