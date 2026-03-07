# plan_pdf.py
from __future__ import annotations

from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle

from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT

try:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib import colors
    REPORTLAB_OK = True
except ModuleNotFoundError:
    REPORTLAB_OK = False


def _should_print_schedule_pdf(d: dict) -> bool:
    """
    Standalone: defaults to True if key missing (backward compatible).
    """
    try:
        return bool((d or {}).get("print_schedule_pdf", True))
    except Exception:
        return True



def _clean(s: str) -> str:
    return (s or "").strip()


def _list_or_empty(x):
    return x if isinstance(x, (list, tuple)) else []


# =========================================================
# Services Provided Today helpers (for PDF)
# =========================================================
def _services_ctx(d: dict) -> dict:
    s = d.get("services") if isinstance(d, dict) else None
    return s if isinstance(s, dict) else {}


def _format_cmt_code_label(cmt_code: str) -> str:
    # "98941: Spinal, 3-4 regions" -> "Spinal, 3-4 Regions (98941)"
    s = _clean(cmt_code)
    if not s:
        return ""
    parts = s.split(":", 1)
    if len(parts) == 2:
        code = _clean(parts[0])
        desc = _clean(parts[1])
        if desc:
            # match your screenshot phrasing a bit
            desc = desc.replace("regions", "Regions")
            return f"{desc} ({code})"
        return code
    return s


def _tech_name_from_flag_list(flags):
    names = ["Activator", "Diversified", "Thompson Drop Technique"]
    out = []
    for i, nm in enumerate(names):
        try:
            if flags[i]:
                out.append(nm)
        except Exception:
            pass
    return out


def _format_modal_label(therapy_key: str) -> tuple[str, str]:
    # "97014: Electric Stimulation" -> ("97014", "Electric Stimulation")
    s = _clean(therapy_key)
    if not s:
        return ("", "")
    parts = s.split(": ", 1)
    if len(parts) == 2:
        return (_clean(parts[0]), _clean(parts[1]))
    return (_clean(parts[0]), "")


def _modality_display_name(code_num: str, mod_name: str) -> str:
    """
    Make the modality header look like your screenshot:
      - "E-Stim" instead of "Electric Stimulation" (optional)
      - "Hot / Cold Packs (97010)" style
    """
    name = _clean(mod_name)
    code = _clean(code_num)

    # simple friendly aliases (edit anytime)
    aliases = {
        "Electric Stimulation": "E-Stim",
        "Hot/Cold Pack": "Hot / Cold Packs",
        "Hot/Cold Packs": "Hot / Cold Packs",
        "Hot Cold Pack": "Hot / Cold Packs",
    }
    name = aliases.get(name, name)

    if name and code:
        # match screenshot style for hot/cold; for others, both are fine
        if "Hot / Cold" in name:
            return f"{name} ({code})"
        return f"{name}"
    return name or code


def _part_abbrev(part: str) -> str:
    """
    Convert body-part strings to shorter “C/S” style labels.
    """
    s = _clean(part)
    if not s:
        return ""

    mapping = {
        "Cervical Spine": "C/S",
        "Thoracic Spine": "T/S",
        "Lumbar Spine": "L/S",
        "Full Spine": "full spine",
        "Entire Spine": "full spine",
    }
    if s in mapping:
        return mapping[s]

    # fallback: your previous shortening rules
    t = s.replace(" Spine", "")
    t = t.replace("Right ", "R ").replace("Left ", "L ")
    return t


def _has_any_services(d: dict) -> bool:
    services = _services_ctx(d)
    cmt_code = _clean(services.get("cmt_code", ""))
    therapy_data = services.get("therapy_data", {}) or {}
    exam_code = _clean(services.get("em_code", services.get("exam_code", "")))
    exam_notes = _clean(services.get("exam_notes", ""))
    if cmt_code:
        return True
    if isinstance(therapy_data, dict):
        for _, v in therapy_data.items():
            if isinstance(v, dict) and v:
                return True
    if exam_code or exam_notes:
        return True
    return False


def _build_services_flowables(d: dict, B) -> list:
    """
    Build flowables for the "Services Provided Today" block:

    Services Provided Today (bold)
      Chiropractic CMT (bold)
        Adjustment Codes: ...
        Segments Adjusted:
          Cervical Technique(s): ...
          Thoracic Technique(s): ...

      Modalities (bold)
        Modality Code: 97012 — Mechanical Traction
          C/S — 15m
          T/S — 15m
        Modality Code: 97014 — E-Stim
          C/S — 10m
    """
        
    styles = getSampleStyleSheet()

    SERV_TITLE = ParagraphStyle(
        "SERV_TITLE",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        alignment=TA_LEFT,
        leftIndent=0,
        spaceBefore=6,
        spaceAfter=6,
    )

    SUBHEAD = ParagraphStyle(
        "SUBHEAD",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,     # ✅ consistent
        leading=12,
        alignment=TA_LEFT,
        leftIndent=14,
        spaceBefore=4,
        spaceAfter=2,
    )

    LINE = ParagraphStyle(
        "LINE",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,      # ✅ consistent
        leading=11,
        alignment=TA_LEFT,
        leftIndent=28,   # ✅ “tab in” for lines under subsection title
        spaceBefore=0,
        spaceAfter=1,
    )

    SUBLINE = ParagraphStyle(
        "SUBLINE",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
        leftIndent=42,   # ✅ “back-tab / extra indent” (Notes, segments, etc.)
        spaceBefore=0,
        spaceAfter=1,
    )
    
    services = _services_ctx(d)
    cmt_code = _clean(services.get("cmt_code", ""))
    cmt_data = services.get("cmt_data", {}) or {}
    cmt_notes = _clean(services.get("cmt_notes", ""))  # ✅ NEW
    therapy_data = services.get("therapy_data", {}) or {}
    exam_code  = _clean(services.get("exam_code", services.get("em_code", "")))
    exam_notes = _clean(services.get("exam_notes", ""))

    has_cmt = bool(cmt_code)
    has_therapy = isinstance(therapy_data, dict) and any(isinstance(v, dict) and v for v in therapy_data.values())
    has_em = bool(exam_code or exam_notes)
    if not (has_cmt or has_therapy or has_em):
        return []

    # --- Styles (indent levels) ---
    # 0: Services Provided Today
    # 1: Chiropractic CMT / Modalities
    # 2: Adjustment Codes / Modality Code
    # 3: Segments / body parts
    H0 = ParagraphStyle(
        "SvcH0", parent=B, fontName="Helvetica-Bold", fontSize=11, leading=12,
        spaceBefore=6, spaceAfter=6, leftIndent=0
    )
    H1 = ParagraphStyle(
        "SvcH1", parent=B, fontName="Helvetica-Bold", fontSize=10, leading=12,
        spaceBefore=0, spaceAfter=4, leftIndent=14
    )
    L2 = ParagraphStyle(
        "SvcL2", parent=B, fontName="Helvetica", fontSize=9, leading=11,
        spaceBefore=0, spaceAfter=2, leftIndent=28
    )
    L3 = ParagraphStyle(
        "SvcL3", parent=B, fontName="Helvetica", fontSize=9, leading=11,
        spaceBefore=0, spaceAfter=1, leftIndent=42
    )

    def esc(x: str) -> str:
        # escape ONLY dynamic data; keep our <b> tags intact
        return xml_escape(_clean(str(x or "")))

    story = []

    # =========================
    # Top header
    # =========================
    story.append(Paragraph("<b>SERVICES PROVIDED TODAY</b>", SERV_TITLE))

    # =========================
    # Chiropractic CMT
    # =========================
    if has_cmt:
        story.append(Paragraph("<b>Chiropractic Manipulative Treatment</b>", SUBHEAD))

        # 
        
        code_num = _clean(cmt_code.split(":")[0])
        code_desc = _format_cmt_code_label(cmt_code)

        if code_num and code_desc:
            story.append(
                Paragraph(
                    f"Adjustment Code: <b>{esc(code_num)}</b> \u2014 {esc(code_desc.replace(f'({code_num})','').strip())}", LINE))


        # Segments Adjusted
        seg_lines = []
        if isinstance(cmt_data, dict):
            for area, payload in cmt_data.items():
                try:
                    adjusted = bool(payload[0])
                    tech_flags = payload[1]
                except Exception:
                    continue

                if not adjusted:
                    continue

                techs = _tech_name_from_flag_list(tech_flags)
                area_lbl = esc(area)
                if techs:
                    tech_txt = esc(", ".join(techs))
                    seg_lines.append(f"<b>{area_lbl}</b> \u2014 Technique(s): {tech_txt}")

                else:
                    seg_lines.append(f"<b>{area_lbl}</b> \u2014 Technique(s):")

        if seg_lines:
            story.append(Paragraph("Segment(s) Adjusted:", LINE))
            for line in seg_lines:
                story.append(Paragraph(line, SUBLINE))
                
        if cmt_notes:
            safe_notes = esc(cmt_notes).replace("\n", "<br/>")
            story.append(Paragraph("CMT Notes:", LINE))
            story.append(Paragraph(safe_notes, SUBLINE))

        # blank line between CMT and modalities (as requested)
        story.append(Spacer(1, 6))

    # =========================
    # Modalities
    # =========================
    if has_therapy:
        story.append(Paragraph("<b>Therapeutic Modalities</b>", SUBHEAD))

        for therapy_key, parts_dict in (therapy_data or {}).items():
            if not isinstance(parts_dict, dict):
                continue

            code_num, mod_name = _format_modal_label(str(therapy_key))
            code_num = _clean(code_num)
            mod_name = _clean(mod_name)

            # Optional friendly name tweak (keeps your earlier aliasing)
            display_name = _modality_display_name(code_num, mod_name)  # e.g. "Mechanical Traction" or "E-Stim"
            display_name = _clean(display_name)

            # Gather checked parts
            checked = []
            for part, tup in parts_dict.items():
                try:
                    is_checked = bool(tup[0])
                    minutes = _clean(str(tup[1])) if tup[1] is not None else ""
                except Exception:
                    is_checked, minutes = False, ""

                if is_checked:
                    checked.append((_part_abbrev(str(part)), minutes))

            if not checked:
                continue

            # Modality header line: "Modality Code: #### — Name"
            # (If name missing, still show code)
            code_show = esc(code_num) if code_num else ""
            name_show = esc(display_name or mod_name) if (display_name or mod_name) else ""
            if code_show and name_show:
                story.append(Paragraph(f"Modality Code: <b>{code_show}</b> \u2014 {name_show}", LINE))
            elif code_show:
                story.append(Paragraph(f"Modality Code: <b>{code_show}</b>", LINE))
            else:
                story.append(Paragraph(f"Modality Code: {name_show}", LINE))

            # Body section, time lines
            for part_lbl, minutes in checked:
                part_show = esc(part_lbl) if part_lbl else "area"
                if minutes:
                    story.append(Paragraph(f"{part_show} \u2014 {esc(minutes)} minutes", SUBLINE))
                else:
                    story.append(Paragraph(f"{part_show}", SUBLINE))

            story.append(Spacer(1, 6))
            
    # =========================
    # Examination and Management
    # =========================
    exam_code  = _clean(services.get("em_code", services.get("exam_code", "")))
    exam_notes = _clean(services.get("exam_notes", ""))

    if exam_code or exam_notes:

        # Section title (matches Chiropractic CMT style)
        story.append(Paragraph("<b>Examination and Management</b>", SUBHEAD))

        # Exam Code line
        if exam_code:
            code_num = exam_code.split(":")[0].strip()
            story.append(
                Paragraph(f"Exam Code: <b>{esc(code_num)}</b>", LINE)
            )

        # Notes line (indented same level)
        if exam_notes:
            story.append(
                Paragraph(f"Notes: {esc(exam_notes)}", SUBLINE)
            )

        story.append(Spacer(1, 6))
        
    return story
    
def _services_to_plain_text(d: dict) -> str:
    """
    Build plain-text representation of Services Provided Today for Live Preview.
    Mirrors _build_services_flowables structure.
    """
    services = _services_ctx(d)
    cmt_code = _clean(services.get("cmt_code", ""))
    cmt_data = services.get("cmt_data", {}) or {}
    cmt_notes = _clean(services.get("cmt_notes", ""))
    therapy_data = services.get("therapy_data", {}) or {}
    exam_code = _clean(services.get("em_code", services.get("exam_code", "")))
    exam_notes = _clean(services.get("exam_notes", ""))

    has_cmt = bool(cmt_code)
    has_therapy = isinstance(therapy_data, dict) and any(
        isinstance(v, dict) and v for v in therapy_data.values()
    )
    has_em = bool(exam_code or exam_notes)
    if not (has_cmt or has_therapy or has_em):
        return ""

    lines: list[str] = []

    if has_cmt:
        lines.append("Chiropractic Manipulative Treatment")
        code_num = _clean((cmt_code or "").split(":")[0])
        code_desc = _format_cmt_code_label(cmt_code)
        if code_num and code_desc:
            lines.append(f"  Adjustment Code: {code_num} — {code_desc.replace(f'({code_num})', '').strip()}")
        seg_lines = []
        if isinstance(cmt_data, dict):
            for area, payload in cmt_data.items():
                try:
                    adjusted = bool(payload[0])
                    tech_flags = payload[1]
                except Exception:
                    continue
                if not adjusted:
                    continue
                techs = _tech_name_from_flag_list(tech_flags)
                area_lbl = _clean(str(area))
                if techs:
                    seg_lines.append(f"  {area_lbl} — Technique(s): {', '.join(techs)}")
                else:
                    seg_lines.append(f"  {area_lbl} — Technique(s):")
        if seg_lines:
            lines.append("  Segment(s) Adjusted:")
            lines.extend(seg_lines)
        if cmt_notes:
            lines.append("  CMT Notes:")
            for ln in (cmt_notes or "").splitlines():
                lines.append(f"    {ln.strip()}")

    if has_therapy:
        if lines:
            lines.append("")
        lines.append("Therapeutic Modalities")
        for therapy_key, parts_dict in (therapy_data or {}).items():
            if not isinstance(parts_dict, dict):
                continue
            code_num, mod_name = _format_modal_label(str(therapy_key))
            display_name = _modality_display_name(code_num, mod_name)
            display_name = _clean(display_name) or mod_name
            checked = []
            for part, tup in parts_dict.items():
                try:
                    is_checked = bool(tup[0])
                    minutes = _clean(str(tup[1])) if tup[1] is not None else ""
                except Exception:
                    is_checked, minutes = False, ""
                if is_checked:
                    checked.append((_part_abbrev(str(part)), minutes))
            if not checked:
                continue
            if code_num and display_name:
                lines.append(f"  Modality Code: {code_num} — {display_name}")
            elif code_num:
                lines.append(f"  Modality Code: {code_num}")
            else:
                lines.append(f"  Modality Code: {display_name}")
            for part_lbl, minutes in checked:
                if minutes:
                    lines.append(f"    {part_lbl} — {minutes} minutes")
                else:
                    lines.append(f"    {part_lbl}")

    if exam_code or exam_notes:
        if lines:
            lines.append("")
        lines.append("Examination and Management")
        if exam_code:
            code_num = (exam_code or "").split(":")[0].strip()
            lines.append(f"  Exam Code: {code_num}")
        if exam_notes:
            lines.append(f"  Notes: {exam_notes}")

    return "\n".join(lines).strip() if lines else ""

def plan_struct_to_live_preview_runs(
    plan_struct: dict, *, work_recs: str = ""
) -> list[tuple[str, str | None]]:
    """
    Build Live Preview runs from plan_struct, mirroring PDF Plan of Care section.
    Returns [(chunk, tag), ...] with tag "H_BOLD" for headings.
    """
    runs: list[tuple[str, str | None]] = []
    d = plan_struct or {}
    work_recs = _clean(work_recs)
    care = _list_or_empty(d.get("care_types"))
    regions = _list_or_empty(d.get("regions"))
    goals = _list_or_empty(d.get("goals"))
    freq = _clean(str(d.get("frequency_per_week", "")))
    dur = _clean(str(d.get("duration_weeks", "")))
    reeval = _clean(str(d.get("reeval", "")))
    if not _should_print_schedule_pdf(d):
        freq = ""
        dur = ""
        reeval = ""
    notes = _clean(d.get("custom_notes", ""))
    plan_text = _clean(d.get("plan_text", ""))

    had_auto = False
    if plan_text.startswith("[AUTO:PLAN]"):
        had_auto = True
        plan_text = plan_text.replace("[AUTO:PLAN]", "", 1).strip()
    if had_auto and work_recs:
        if work_recs.lower() not in (plan_text or "").lower():
            if plan_text and not plan_text.endswith((".", "!", "?")):
                plan_text += "."
            plan_text = (plan_text + " " + work_recs).strip()

    if not (care or regions or goals or freq or dur or reeval or notes or plan_text or _has_any_services(d)):
        return []

    def add_section(heading: str, body: str):
        if not (body or "").strip():
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        runs.append(((body or "").strip() + "\n\n", None))

    # Summary grid (Treatment Care Types, Regions, Schedule, Goals, Work Duties)
    grid_lines: list[str] = []
    if care:
        grid_lines.append(f"Care Type(s): {', '.join(care)}")
    if regions:
        grid_lines.append(f"Regions: {', '.join(regions)}")
    if freq:
        grid_lines.append(f"Frequency: {freq} / week")
    if dur:
        grid_lines.append(f"Duration: {dur} weeks")
    if reeval:
        grid_lines.append(f"Re-evaluation: {reeval}")
    if goals:
        grid_lines.append(f"Goals: {', '.join(goals)}")
    if work_recs:
        grid_lines.append(f"Work Duties: {work_recs}")
    if grid_lines:
        runs.append(("\n".join(grid_lines) + "\n\n", None))

    # Plan Narrative
    if plan_text:
        runs.append((plan_text.strip() + "\n\n", None))

    # Notes
    if notes:
        add_section("Notes", notes)

    # Services Provided Today
    svc_text = _services_to_plain_text(d)
    if svc_text:
        add_section("Services Provided Today", svc_text)

    return runs
# =========================================================
# Main builder
# =========================================================
def build_plan_flowables(plan_struct: dict, styles, *, work_recs: str = "") -> list:
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
    work_recs = _clean(work_recs)
    freq = _clean(str(d.get("frequency_per_week", "")))
    dur = _clean(str(d.get("duration_weeks", "")))
    reeval = _clean(str(d.get("reeval", "")))
    if not _should_print_schedule_pdf(d):
        # hide schedule lines in PDF only
        freq = ""
        dur = ""
        reeval = ""
    notes = _clean(d.get("custom_notes", ""))
    plan_text = _clean(d.get("plan_text", ""))

    # Strip AUTO tag if present
    had_auto = False
    if plan_text.startswith("[AUTO:PLAN]"):
        had_auto = True
        plan_text = plan_text.replace("[AUTO:PLAN]", "", 1).strip()

    # ✅ If this is the AUTO-generated plan paragraph, append Work Duties into it
    if had_auto and work_recs:
        # avoid duplicating if it’s already present (case-insensitive)
        if work_recs.lower() not in plan_text.lower():
            # ensure spacing + punctuation
            if plan_text and not plan_text.endswith(("." , "!", "?")):
                plan_text += "."
            plan_text = (plan_text + " " + work_recs).strip()

    # If everything is empty AND no services, return nothing
    if not (care or regions or goals or freq or dur or reeval or notes or plan_text or _has_any_services(d)):
        return []

    H = styles["Heading2"] if "Heading2" in styles else styles["Heading3"]
    B = styles["BodyText"]

    story = []

    story.append(Paragraph("<b>PLAN OF CARE</b>", H))
    story.append(Spacer(1, 6))

    # Summary grid
    label_w = 1.35 * inch
    value_w = 5.75 * inch

    label_style = ParagraphStyle(
        "PlanLabel",
        parent=B,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
    )

    value_style = ParagraphStyle(
        "PlanValue",
        parent=B,
        fontName="Helvetica",
        fontSize=9,
        leading=11,
    )

    def P(txt: str, style):
        return Paragraph(xml_escape(txt or ""), style)

    grid_rows = [
        ("Care Type(s):", ", ".join(care) if care else ""),
        ("Regions:", ", ".join(regions) if regions else ""),
        ("Frequency:", f"{freq} / week" if freq else ""),
        ("Duration:", f"{dur} weeks" if dur else ""),
        ("Re-evaluation:", reeval or ""),
        ("Goals:", ", ".join(goals) if goals else ""),
        ("Work Duties:", work_recs or ""),
    ]
    grid_rows = [(k, v) for (k, v) in grid_rows if _clean(v)]

    if grid_rows:
        grid_data = [[P(k, label_style), P(v, value_style)] for (k, v) in grid_rows]
        t = Table(grid_data, colWidths=[label_w, value_w])
        t.hAlign = "LEFT"
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
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

    # Notes
    if notes:
        safe = xml_escape(notes).replace("\n", "<br/>")
        story.append(Paragraph("<b>Notes:</b>", B))
        story.append(Spacer(1, 4))
        story.append(Paragraph(safe, B))
        story.append(Spacer(1, 8))

    # ---------------------------------------------------------
    # Services Provided Today (AFTER plan/goals/narrative/notes)
    # ---------------------------------------------------------
    svc_flowables = _build_services_flowables(d, B)
    if svc_flowables:
        story.append(Spacer(1, 6))
        story.extend(svc_flowables)
        story.append(Spacer(1, 6))

    return story
