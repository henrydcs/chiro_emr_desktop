# pdf_export.py
from __future__ import annotations

import os
import re
from xml.sax.saxutils import escape as xml_escape

from HOIpdf import build_hoi_flowables
from plan_pdf import build_plan_flowables


from config import (
    LOGO_PATH, CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX,
    EXAMS, REGION_LABELS
)
from utils import normalize_mmddyyyy, today_mmddyyyy

# ----------- OPTIONAL: ReportLab (PDF export) -----------
try:
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, Flowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as canvas_module
    from reportlab.lib.utils import ImageReader
    REPORTLAB_OK = True
except ModuleNotFoundError:
    REPORTLAB_OK = False
   

_RE_REEXAM = re.compile(r"^\s*Re-Exam\s+\d+\s*$", re.IGNORECASE)
_RE_ROF    = re.compile(r"^\s*Review of Findings\s+\d+\s*$", re.IGNORECASE)

from xml.sax.saxutils import escape as xml_escape
from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.units import inch

def _as_paragraph(text: str, styles):
    t = (text or "").strip()
    if not t:
        return None
    safe = xml_escape(t).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])


def _hoi_manual_text_for_exam(exam_name: str, hoi_struct: dict) -> str:
    ex = (exam_name or "").strip().lower()
    hoi_struct = hoi_struct or {}

    if ex == "initial":
        return (hoi_struct.get("manual_initial") or "").strip()

    if ex.startswith("re-exam"):
        return (hoi_struct.get("manual_reexam") or "").strip()

    if ex.startswith("review of findings"):
        return (hoi_struct.get("manual_rof") or "").strip()

    if ex == "final":
        return (hoi_struct.get("manual_final") or "").strip()

    return ""


def pdf_exam_label(exam_name: str) -> str:
    s = (exam_name or "").strip()
    if _RE_REEXAM.match(s):
        return "Re-Exam"
    if _RE_ROF.match(s):
        return "Review of Findings"
    return s


def _join_with_and(items: list[str]) -> str:
    items = [s.strip() for s in (items or []) if s and s.strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"

def _imaging_sentence(dx_struct: dict) -> str:
    recs = dx_struct.get("imaging_recs") or []
    if not isinstance(recs, list):
        return ""
    parts = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        mod = (r.get("modality") or "").strip()
        bp = (r.get("body_part") or "").strip()
        if mod and bp:
            parts.append(f"{mod} of {bp}")
    joined = _join_with_and(parts)
    if not joined:
        return ""
    return ("Due to the patient's ongoing subjective complaints along with positive objective findings, "
            f"the patient will need to undergo imaging studies as follows: {joined}.")

def _referral_sentence(dx_struct: dict) -> str:
    refs = dx_struct.get("referrals") or []
    if not isinstance(refs, list):
        return ""
    parts = []
    for r in refs:
        if not isinstance(r, dict):
            continue
        p = (r.get("provider_type") or "").strip()
        if p and p != "(select)":
            parts.append(p)
    joined = _join_with_and(parts)
    return f"Referrals: {joined}." if joined else ""



# =======================================================
# Subjectives: "semi-bold" token markup
# =======================================================
def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for s in items or []:
        key = (s or "").strip().lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((s or "").strip())
    return out


def tokens_from_subjective_block(block: dict) -> list[str]:
    block = block or {}
    toks: list[str] = []

    for k in ("desc1", "desc2"):
        v = (block.get(k) or "").strip()
        if v and v != "(none)":
            toks.append(v)

    rs = (block.get("radic_symptom") or "").strip()
    if rs and rs != "None":
        toks.append(rs)

    rl = (block.get("radic_location") or "").strip()
    if rl and rl != "(select)":
        toks.append(rl)

    for m in (block.get("muscles") or []):
        m = (m or "").strip()
        if m:
            toks.append(m)

    ps = (block.get("pain_scale") or "").strip()
    if ps and ps != "None":
        toks.append(ps)

    return _dedupe_preserve_order(toks)


def semibold_markup(text: str, tokens: list[str]) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    escaped = xml_escape(s)
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\n\n", "<br/><br/>")
    escaped = escaped.replace("\n", "<br/>")

    toks = [t.strip() for t in (tokens or []) if (t or "").strip()]
    toks.sort(key=len, reverse=True)
    if not toks:
        return escaped

    for tok in toks:
        tok_e = xml_escape(tok)
        if not tok_e:
            continue
        pattern = re.compile(re.escape(tok_e), re.IGNORECASE)

        def repl(m):
            return f'<font name="Helvetica-Bold">{m.group(0)}</font>'

        escaped = pattern.sub(repl, escaped)

    return escaped


# =======================================================
# Objectives: structured rendering helpers
# Expects:
#   soap["objectives_struct"] = {"global": {...}, "blocks":[...]}
# =======================================================
SEVERITY_LABELS = {
    0: "Within Normal Levels",
    1: "Minimum",
    2: "Minimum to Mild",
    3: "Mild",
    4: "Mild to Moderate",
    5: "Moderate",
    6: "Moderate to Severe",
    7: "Severe",
    8: "Very Severe",
    9: "Intolerable",
}

SPINE_CODES = {"CS", "TS", "LS"}

EXTREMITY_CODES = {
    "R_SHOULDER","L_SHOULDER","BL_SHOULDER",
    "R_ELBOW","L_ELBOW","BL_ELBOW",
    "R_WRIST","L_WRIST","BL_WRIST",
    "R_HIP","L_HIP","BL_HIP",
    "R_KNEE","L_KNEE","BL_KNEE",
    "R_ANKLE","L_ANKLE","BL_ANKLE",
}

def _is_spine_region(code: str) -> bool:
    return (code or "").strip() in SPINE_CODES

def _is_bilateral_region(code: str) -> bool:
    c = (code or "").strip()
    return c.startswith("BL_") or c.startswith("B/L_")  # support older naming if needed

def _sev_label(v) -> str:
    try:
        iv = int(v)
    except Exception:
        return ""
    if iv == -1:
        return ""
    return SEVERITY_LABELS.get(iv, "")


def _rom_style_lines(motion: str, l_sev: int, r_sev: int, *, region_code: str) -> list[str]:
    """
    Spine:
      Flexion/Extension: no Left/Right, show Restricted + worst severity.
      Lat Flex/Rotation: show Left block + Right block (with a small spacer line).

    Extremities:
      If bilateral region: ALWAYS show Left block + Right block for every motion.
      If unilateral region: show only the relevant side (Left or Right).
    """
    motion = (motion or "").strip()
    ml = motion.lower()

    left_txt  = _sev_label(l_sev)
    right_txt = _sev_label(r_sev)

    # Nothing selected
    if not left_txt and not right_txt:
        return []

    code = (region_code or "").strip()
    is_spine = _is_spine_region(code)
    is_bilat = _is_bilateral_region(code)

    # ---------------- SPINE RULES ----------------
    if is_spine:
        # Flex/Ext are not left/right for spine
        if ml in ("flexion", "extension"):
            best_guess = ""
            try:
                best_guess = _sev_label(max(int(l_sev), int(r_sev)))
            except Exception:
                best_guess = left_txt or right_txt
            return ["Restricted", best_guess or "Restricted"]

        # Lat flex / rotation: show left + right if present
        lines: list[str] = []
        if left_txt:
            lines.append("Left Side - Restricted")
            lines.append(left_txt)
        if left_txt and right_txt:
            lines.append("")  # spacer between sides
        if right_txt:
            lines.append("Right Side - Restricted")
            lines.append(right_txt)
        return lines

    # ---------------- EXTREMITY RULES ----------------
    # Bilateral extremity: always show both sides if any selected
    if is_bilat:
        lines: list[str] = []
        if left_txt:
            lines.append("Left Side - Restricted")
            lines.append(left_txt)
        if left_txt and right_txt:
            lines.append("")  # spacer between sides
        if right_txt:
            lines.append("Right Side - Restricted")
            lines.append(right_txt)
        return lines

    # Unilateral extremity: show only the relevant side
    # R_* shows right only, L_* shows left only (fallback: show whatever exists)
    if code.startswith("R_"):
        return ["Restricted", right_txt or left_txt or "Restricted"]
    if code.startswith("L_"):
        return ["Restricted", left_txt or right_txt or "Restricted"]

    # fallback
    return ["Restricted", left_txt or right_txt or "Restricted"]


def rom_block(title: str, lines: list[str], styles):
    """
    Left-aligned ROM block using Heading4/BodyText.
    """
    title = (title or "").strip()
    if not title or not lines:
        return []

    out = []
    out.append(Paragraph(f"<b>{xml_escape(title)}</b>", styles["Heading4"]))
    for line in lines:
        line = (line or "").strip()
        if not line:
            continue
        out.append(Spacer(1, 0.02 * inch))
        out.append(Paragraph(xml_escape(line), styles["BodyText"]))
    out.append(Spacer(1, 0.06 * inch))
    return out


def _clean_val(v) -> str:
    v = "" if v is None else str(v)
    v = v.strip()
    if not v or v == "(none)":
        return ""
    return v


def _pretty_region(code: str) -> str:
    return REGION_LABELS.get(code, "") or ""


def _region_group_name(label: str) -> str:
    if not label:
        return ""

    l = label.lower()

    # Explicit spine regions
    if "spine" in l or label in ("Cervical", "Thoracic", "Lumbar"):
        return label if "spine" in l else f"{label} Spine"

    # Everything else is a joint — DO NOT append "Spine"
    return label



def _region_tag(code: str) -> str:
    c = (code or "").strip()
    mapping = {
        "CS": "(C/S)",
        "TS": "(T/S)",
        "LS": "(L/S)",

        "R_SHOULDER": "(R Shoulder)",
        "L_SHOULDER": "(L Shoulder)",
        "BL_SHOULDER": "(B/L Shoulders)",

        "R_ELBOW": "(R Elbow)",
        "L_ELBOW": "(L Elbow)",
        "BL_ELBOW": "(B/L Elbows)",

        "R_WRIST": "(R Wrist)",
        "L_WRIST": "(L Wrist)",
        "BL_WRIST": "(B/L Wrists)",

        "R_HIP": "(R Hip)",
        "L_HIP": "(L Hip)",
        "BL_HIP": "(B/L Hips)",

        "R_KNEE": "(R Knee)",
        "L_KNEE": "(L Knee)",
        "BL_KNEE": "(B/L Knees)",

        "R_ANKLE": "(R Ankle)",
        "L_ANKLE": "(L Ankle)",
        "BL_ANKLE": "(B/L Ankles)",
    }

    return mapping.get(c, f"({c})") if c and c != "(none)" else ""



def _fmt_ortho(res: int) -> str:
    if res == 1:
        return "Positive"
    if res == 0:
        return "Negative"
    return ""


def _fmt_rom(sev: int) -> str:
    if sev == 0:
        return "WNL"
    if sev in SEVERITY_LABELS:
        return f"Restricted — {SEVERITY_LABELS[sev]}"
    return ""


def _fmt_severity(sev: int) -> str:
    if sev in SEVERITY_LABELS:
        return SEVERITY_LABELS[sev]
    return ""


def _norm_name(s: str) -> str:
    return (s or "").strip().lower()


def _strip_parens_suffix(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s*\(.*?\)\s*$", "", s).strip()
    return s


def _merge_findings_lists(items_list: list[list[tuple[str, str, str]]], strip_parens: bool = False):
    out = []
    seen = set()
    for items in items_list or []:
        for name, line2, line3 in (items or []):
            base = _strip_parens_suffix(name) if strip_parens else (name or "").strip()
            key = _norm_name(base)
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append((base, line2, line3))
    return out


def _merge_rom_struct(region_blocks: list[dict]) -> dict:
    """
    Merge ROM across multiple region blocks into:
      {"Flexion": {"l_sev": int, "r_sev": int}, ...}

    We keep the WORST (max) severity per side, ignoring -1.
    """
    merged: dict[str, dict[str, int]] = {}

    for b in region_blocks or []:
        if not isinstance(b, dict):
            continue
        rom = b.get("rom") or {}
        if not isinstance(rom, dict):
            continue

        for motion, st in rom.items():
            if not isinstance(st, dict):
                continue

            motion_name = _strip_parens_suffix(str(motion))
            try:
                l = int(st.get("l_sev", -1))
            except Exception:
                l = -1
            try:
                r = int(st.get("r_sev", -1))
            except Exception:
                r = -1

            cur = merged.get(motion_name, {"l_sev": -1, "r_sev": -1})

            if l != -1:
                cur["l_sev"] = l if cur["l_sev"] == -1 else max(cur["l_sev"], l)
            if r != -1:
                cur["r_sev"] = r if cur["r_sev"] == -1 else max(cur["r_sev"], r)

            merged[motion_name] = cur

    return merged


def _collect_objectives_findings(block: dict):
    block = block or {}
    palp = block.get("palpation") or {}
    ortho = block.get("ortho") or {}
    rom = block.get("rom") or {}

    palp_left, palp_right = [], []
    for name, st in palp.items():
        if not isinstance(st, dict):
            continue
        l = int(st.get("l_sev", -1))
        r = int(st.get("r_sev", -1))
        if l != -1:
            lbl = _fmt_severity(l)
            if lbl:
                palp_left.append((name, lbl, ""))
        if r != -1:
            lbl = _fmt_severity(r)
            if lbl:
                palp_right.append((name, lbl, ""))

    ortho_left, ortho_right = [], []
    for name, st in ortho.items():
        if not isinstance(st, dict):
            continue
        l = int(st.get("l_res", st.get("l_sev", -1)))
        r = int(st.get("r_res", st.get("r_sev", -1)))
        lf = _fmt_ortho(l)
        rf = _fmt_ortho(r)
        if lf:
            ortho_left.append((name, lf, ""))
        if rf:
            ortho_right.append((name, rf, ""))

    # NOTE: We still return ROM findings as lists here (for table-style rendering if needed),
    # but the ROM section below uses _merge_rom_struct(region_blocks) for motion-by-motion rendering.
    rom_left, rom_right = [], []
    for name, st in rom.items():
        if not isinstance(st, dict):
            continue
        l = int(st.get("l_sev", -1))
        r = int(st.get("r_sev", -1))
        lf = _fmt_rom(l) if l != -1 else ""
        rf = _fmt_rom(r) if r != -1 else ""
        if lf:
            rom_left.append((name, lf, ""))
        if rf:
            rom_right.append((name, rf, ""))

    return {
        "PALPATION": (palp_left, palp_right),
        "ORTHOPEDIC EXAM": (ortho_left, ortho_right),
        "RANGE OF MOTION": (rom_left, rom_right),
    }


def _build_centered_lr_table(left_items, right_items, styles, col_widths):
    head_style = styles["ObjColHead"]
    cell_style = styles["ObjColBody"]

    def cell_markup(item):
        if not item:
            return ""
        name, line2, line3 = item
        lines = []
        if (name or "").strip():
            lines.append(xml_escape(name.strip()))
        if (line2 or "").strip():
            lines.append(xml_escape(line2.strip()))
        if (line3 or "").strip():
            lines.append(xml_escape(line3.strip()))
        return "<br/>".join(lines)

    max_len = max(len(left_items), len(right_items), 1)
    L = list(left_items) + [None] * (max_len - len(left_items))
    R = list(right_items) + [None] * (max_len - len(right_items))

    data = [
        [Paragraph("LEFT SIDE", head_style), Paragraph("RIGHT SIDE", head_style)]
    ]

    for i in range(max_len):
        ltxt = cell_markup(L[i]) if L[i] else ""
        rtxt = cell_markup(R[i]) if R[i] else ""
        data.append([Paragraph(ltxt or " ", cell_style), Paragraph(rtxt or " ", cell_style)])
        data.append([Paragraph(" ", cell_style), Paragraph(" ", cell_style)])  # spacer row

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.hAlign = "LEFT"
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),

        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),

        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ]))
    return t


def _notes_paragraph(notes: str, styles):
    notes = (notes or "").strip()
    if not notes:
        return None
    safe = xml_escape(notes).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
    return Paragraph(f"<b>Notes:</b><br/>{safe}", styles["BodyText"])


def _build_vitals_table(vitals: dict, doc_width: float):
    if not isinstance(vitals, dict):
        return None

    fields = [
        ("BP:", "bp"),
        ("Pulse:", "pulse"),
        ("Resp:", "resp"),
        ("Temp:", "temp"),
        ("Height:", "height"),
        ("Weight:", "weight"),
        ("SpO₂:", "spo2"),
    ]

    pairs = []
    for label, key in fields:
        val = _clean_val(vitals.get(key, ""))
        if val:
            pairs.append((label, val))

    if not pairs:
        return None

    max_pairs_per_row = 4
    rows = []
    for i in range(0, len(pairs), max_pairs_per_row):
        chunk = pairs[i:i + max_pairs_per_row]
        row = []
        for lab, val in chunk:
            row.extend([lab, val])
        rows.append(row)

    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")

    colw = []
    for _ in range(max_cols // 2):
        colw.extend([0.7 * inch, 1.1 * inch])

    total = sum(colw)
    if total > doc_width:
        scale = doc_width / total
        colw = [w * scale for w in colw]

    t = Table(rows, colWidths=colw)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _build_posture_paragraph(posture: dict, styles):
    if not isinstance(posture, dict):
        return None

    shoulder = _clean_val(posture.get("shoulder_levels"))
    kyph = _clean_val(posture.get("kyphosis_ts"))
    fwd = _clean_val(posture.get("forward_head_cs"))
    lord = _clean_val(posture.get("lordosis_ls"))

    if not any([shoulder, kyph, fwd, lord]):
        return None

    lines = []
    if shoulder:
        lines.append(f"Shoulder Levels: {shoulder}")
    if kyph:
        lines.append(f"Kyphosis (T/S): {kyph}")
    if fwd:
        lines.append(f"Forward Head Posture (C/S): {fwd}")
    if lord:
        lines.append(f"Lordosis (L/S): {lord}")

    safe = xml_escape("\n".join(lines)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])


def _build_grip_paragraph(grip: dict, styles):
    grip = grip or {}
    left = _clean_val(grip.get("left"))
    right = _clean_val(grip.get("right"))
    comp = _clean_val(grip.get("compare"))

    if not (left or right or comp):
        return None

    lines = []
    if left or right:
        parts = []
        if left:
            parts.append(f"Left: {left}")
        if right:
            parts.append(f"Right: {right}")
        lines.append("    ".join(parts))

    if comp == "Left weaker":
        lines.append("Left grip reveals weakness compared to the right hand.")
    elif comp == "Right weaker":
        lines.append("Right grip reveals weakness compared to the left hand.")
    elif comp == "Symmetric":
        lines.append("Grip strength appears grossly symmetric bilaterally.")

    safe = xml_escape("\n".join(lines)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])

def _rom_cell_flowables(motion: str, lines: list[str], styles):
    """
    Flowables for a ROM cell. Interprets "" as a deliberate blank line spacer.
    """
    if not lines:
        return [Paragraph(" ", styles["BodyText"])]

    out = []

    # ✅ Use a ROM-specific style with zero spacing so both columns align perfectly
    head_style = styles["ROMMotion"] if "ROMMotion" in styles.byName else styles["BodyText"]
    out.append(Paragraph(xml_escape(motion), head_style))

    for line in lines:
        if line is None:
            continue

        # If line is "", treat as extra vertical spacing
        if str(line) == "":
            out.append(Spacer(1, 0.07 * inch))  # blank line between groups or L/R
            continue

        out.append(Spacer(1, 0.01 * inch))
        out.append(Paragraph(xml_escape(str(line).strip()), styles["BodyText"]))

    return out

def _build_adl_paragraph(adl: dict, styles):
    if not isinstance(adl, dict):
        return None

    sev = adl.get("severity", -1)
    try:
        sev = int(sev)
    except Exception:
        sev = -1

    items = adl.get("items") or []
    if not isinstance(items, list):
        items = []

    notes = (adl.get("notes") or "").strip()

    if sev == -1 and not items and not notes:
        return None

    parts = []
    if sev != -1:
        # uses your existing SEVERITY_LABELS mapping
        parts.append(f"Severity: {sev} — {SEVERITY_LABELS.get(sev, '')}".strip())

    clean_items = [str(x).strip() for x in items if str(x).strip()]
    if clean_items:
        parts.append("Affected ADLs: " + ", ".join(clean_items))

    if notes:
        parts.append("Notes: " + notes)

    safe = xml_escape("\n".join(parts)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])



def build_objectives_flowables(objectives_struct: dict, styles, doc_width: float, *, include_adl: bool = True):

    rom_merged = {}
    rom_notes = None


    out = []
    objectives_struct = objectives_struct or {}
    printed_any = False

    # ---------- GLOBAL ----------
    global_struct = objectives_struct.get("global") or {}
    if isinstance(global_struct, dict):
        vitals = global_struct.get("vitals") or {}
        posture = global_struct.get("posture") or {}
        grip = global_struct.get("grip") or {}

        adl_para = None
        if include_adl:
            adl = global_struct.get("adl") or {}
            adl_para = _build_adl_paragraph(adl, styles)


        vit_tbl = _build_vitals_table(vitals, doc_width)
        pos_para = _build_posture_paragraph(posture, styles)
        grip_para = _build_grip_paragraph(grip, styles)

        vit_notes = _notes_paragraph(_clean_val(vitals.get("notes")), styles)
        pos_notes = _notes_paragraph(_clean_val(posture.get("notes")), styles)
        grip_notes = _notes_paragraph(_clean_val(grip.get("notes")), styles)

        if vit_tbl or pos_para or grip_para or adl_para or vit_notes or pos_notes or grip_notes:
            printed_any = True
            out.append(Paragraph("<b>VITALS / INSPECTION</b>", styles["Heading3"]))
            out.append(Spacer(1, 0.08 * inch))

            if vit_tbl or vit_notes:
                out.append(Paragraph("<b>Vitals</b>", styles["Heading4"]))
                out.append(Spacer(1, 0.05 * inch))
                if vit_tbl:
                    out.append(vit_tbl)
                if vit_notes:
                    out.append(Spacer(1, 0.10 * inch))
                    out.append(vit_notes)
                out.append(Spacer(1, 0.12 * inch))

            if pos_para or pos_notes:
                out.append(Paragraph("<b>Posture</b>", styles["Heading4"]))
                out.append(Spacer(1, 0.05 * inch))
                if pos_para:
                    out.append(pos_para)
                if pos_notes:
                    out.append(Spacer(1, 0.10 * inch))
                    out.append(pos_notes)
                out.append(Spacer(1, 0.12 * inch))

            if grip_para or grip_notes:
                out.append(Paragraph("<b>Grip Strength (Jamar)</b>", styles["Heading4"]))
                out.append(Spacer(1, 0.05 * inch))
                if grip_para:
                    out.append(grip_para)
                if grip_notes:
                    out.append(Spacer(1, 0.10 * inch))
                    out.append(grip_notes)
                out.append(Spacer(1, 0.12 * inch))            


            # if adl_para:
            #     out.append(Paragraph("<b>Functional Status / ADLs</b>", styles["Heading4"]))
            #     out.append(Spacer(1, 0.05 * inch))
            #     out.append(adl_para)
            #     out.append(Spacer(1, 0.12 * inch))

            out.append(Spacer(1, 0.06 * inch))

    # ---------- REGION BLOCKS ----------
    blocks = objectives_struct.get("blocks") or []
    if not isinstance(blocks, list):
        return out if printed_any else []

    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        code = (b.get("region") or "").strip() or "(none)"
        if code not in grouped:
            grouped[code] = []
            order.append(code)
        grouped[code].append(b)

    col_widths = [doc_width / 2.0, doc_width / 2.0]

    def first_note(region_blocks, key: str) -> str:
        for bb in region_blocks:
            txt = _clean_val(bb.get(key, ""))
            if txt:
                return txt
        return ""

    for code in order:
        region_blocks = grouped.get(code, [])
        if not region_blocks:
            continue

        label = _pretty_region(code) if code != "(none)" else ""
        if not label:
            continue

        region_title = _region_group_name(label)

        palp_L_all, palp_R_all = [], []
        ortho_L_all, ortho_R_all = [], []

        for b in region_blocks:
            findings = _collect_objectives_findings(b)
            pL, pR = findings["PALPATION"]
            oL, oR = findings["ORTHOPEDIC EXAM"]

            palp_L_all.append(pL)
            palp_R_all.append(pR)
            ortho_L_all.append(oL)
            ortho_R_all.append(oR)

        palp_left = _merge_findings_lists(palp_L_all)
        palp_right = _merge_findings_lists(palp_R_all)
        ortho_left = _merge_findings_lists(ortho_L_all)
        ortho_right = _merge_findings_lists(ortho_R_all)

        # IMPORTANT: ROM is rendered using the true ROM dict structure (merged per region).
        # You must have _merge_rom_struct(region_blocks) defined elsewhere in this file.
        rom_merged = {}        
        if region_blocks:
            try:
                rom_merged = _merge_rom_struct(region_blocks) or {}
            except Exception:
                rom_merged = {}


        palp_notes = _notes_paragraph(first_note(region_blocks, "palpation_notes"), styles)
        ortho_notes = _notes_paragraph(first_note(region_blocks, "ortho_notes"), styles)
        rom_notes = _notes_paragraph(first_note(region_blocks, "rom_notes"), styles)

        has_any = bool(
            palp_left or palp_right or palp_notes or
            ortho_left or ortho_right or ortho_notes or
            rom_merged or rom_notes
        )
        if not has_any:
            continue

        printed_any = True
        out.append(Paragraph(f"<b>{xml_escape(region_title)}</b>", styles["Heading3"]))
        out.append(Spacer(1, 0.10 * inch))

        tag = _region_tag(code)

        if palp_left or palp_right or palp_notes:
            out.append(Paragraph(f"<b>PALPATION {xml_escape(tag)}</b>", styles["ObjSectionCenter"]))
            out.append(Spacer(1, 0.06 * inch))
            if palp_left or palp_right:
                out.append(_build_centered_lr_table(palp_left, palp_right, styles, col_widths))
            if palp_notes:
                out.append(Spacer(1, 0.10 * inch))
                out.append(palp_notes)
            out.append(Spacer(1, 0.14 * inch))

        if ortho_left or ortho_right or ortho_notes:
            out.append(Paragraph(f"<b>ORTHOPEDIC EXAM {xml_escape(tag)}</b>", styles["ObjSectionCenter"]))
            out.append(Spacer(1, 0.06 * inch))
            if ortho_left or ortho_right:
                out.append(_build_centered_lr_table(ortho_left, ortho_right, styles, col_widths))
            if ortho_notes:
                out.append(Spacer(1, 0.10 * inch))
                out.append(ortho_notes)
            out.append(Spacer(1, 0.14 * inch))

                   # ---------- ROM (dynamic boxed cells: 2 columns, N rows) ----------
        if rom_merged or rom_notes:
            out.append(Paragraph(f"<b>RANGE OF MOTION {xml_escape(tag)}</b>", styles["Heading3"]))
            out.append(Spacer(1, 0.05 * inch))

            # Pull motion list from the SAME source as ObjectivesPage uses.
            # Easiest: define a local mapping here (or import from config if you move it there).
            REGION_ROM_MOTIONS_PDF = {
                "CS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
                "TS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
                "LS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],

                "R_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                "L_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                "BL_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],

                "R_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],
                "L_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],
                "BL_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],

                "R_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],
                "L_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],
                "BL_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],

                "R_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                "L_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                "BL_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],

                "R_KNEE": ["Flexion", "Extension"],
                "L_KNEE": ["Flexion", "Extension"],
                "BL_KNEE": ["Flexion", "Extension"],

                "R_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
                "L_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
                "BL_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
            }

            motions = REGION_ROM_MOTIONS_PDF.get(code, ["Flexion", "Extension", "Lateral Flexion", "Rotation"])

            def motion_lines(motion: str) -> list[str]:
                st = (rom_merged or {}).get(motion) or {}
                try:
                    l_sev = int(st.get("l_sev", -1))
                except Exception:
                    l_sev = -1
                try:
                    r_sev = int(st.get("r_sev", -1))
                except Exception:
                    r_sev = -1
                return _rom_style_lines(motion, l_sev, r_sev, region_code=code)


            def _cell_paragraph(motion: str, lines: list[str]):
                parts = [f"<b>{xml_escape(motion)}</b>"]
                if not lines:
                    parts.append(" ")
                else:
                    for ln in lines:
                        if ln is None:
                            continue
                        ln = str(ln)
                        if ln in ("__LR_BREAK__", "__LR_TIGHT__"):
                            parts.append('<font size="4">&nbsp;</font>')
                            continue
                        if ln.strip() == "":
                            parts.append("")
                            continue
                        parts.append(xml_escape(ln.strip()))
                html = "<br/>".join(parts)
                return Paragraph(html, styles["BodyText"])

            # Build all cells in order
            cells = []
            for m in motions:
                cells.append(_cell_paragraph(m, motion_lines(m)))

            # 2 columns layout, pad last row if needed
            rows = []
            for i in range(0, len(cells), 2):
                row = [cells[i]]
                if i + 1 < len(cells):
                    row.append(cells[i + 1])
                else:
                    row.append(Paragraph(" ", styles["BodyText"]))  # empty box if odd count
                rows.append(row)

            cell_w = doc_width / 2.0
            rom_table = Table(rows, colWidths=[cell_w, cell_w])

            rom_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]))

            out.append(rom_table)

            if rom_notes:
                out.append(Spacer(1, 0.06 * inch))
                out.append(rom_notes)

            out.append(Spacer(1, 0.14 * inch))






            #out.append(Spacer(1, 0.06 * inch))


    return out if printed_any else []



# =======================================================
# Header / Canvas
# =======================================================
class ExamStart(Flowable):
    def __init__(self, exam_name: str, patient: dict, exam_date: str):
        super().__init__()
        self.exam_name = exam_name
        self.patient = patient or {}
        self.exam_date = exam_date

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        c = self.canv
        c._current_exam_name = self.exam_name
        c._current_patient = self.patient
        c._current_exam_date = self.exam_date


class HeaderExamNumberedCanvas(canvas_module.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_exam_name = ""
        self._current_patient = {}
        self._current_exam_date = ""
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def _draw_header(self, exam_name: str, patient: dict, exam_date: str, page_in_exam: int, total_in_exam: int):
        page_w, page_h = LETTER
        left = 72
        right = page_w - 72

        y_top = page_h - 40
        clinic_block_height = 58

        logo_w, logo_h = 50, 50
        PDF_LOGO_X_OFFSET = 0
        PDF_LOGO_Y_OFFSET = -35

        text_top = y_top + 10
        text_line_gap = 16
        text_lines = 3
        text_block_height = text_line_gap * text_lines

        logo_x = left + PDF_LOGO_X_OFFSET
        logo_y = (text_top - ((logo_h - text_block_height) / 2)) + PDF_LOGO_Y_OFFSET

        text_x = left + logo_w + 10
        text_y = text_top

        self.saveState()
        if os.path.exists(LOGO_PATH):
            try:
                img = ImageReader(LOGO_PATH)
                self.drawImage(
                    img, logo_x, logo_y,
                    width=logo_w, height=logo_h,
                    preserveAspectRatio=True,
                    mask="auto"
                )
            except Exception:
                pass

        self.setFont("Helvetica-Bold", 14)
        self.drawString(text_x, text_y, CLINIC_NAME)
        self.setFont("Helvetica", 11)
        self.drawString(text_x, text_y - 16, CLINIC_ADDR)
        self.drawString(text_x, text_y - 32, CLINIC_PHONE_FAX)

        sep_y = y_top - clinic_block_height
        self.setLineWidth(0.5)
        self.setStrokeColor(colors.lightgrey)
        self.line(left, sep_y, right, sep_y)
        self.restoreState()

        y2 = sep_y - 10
        line_gap = 12

        name = (patient.get("display_name") or patient.get("name") or "").strip()
        dob = normalize_mmddyyyy(patient.get("dob", ""))
        doi = normalize_mmddyyyy(patient.get("doi", ""))
        exam_date = normalize_mmddyyyy(exam_date) or today_mmddyyyy()

        header_lines = []
        if name:
            header_lines.append(name)
        header_lines.append(f"DOB: {dob}" if dob else "DOB: ")
        header_lines.append(f"DOI: {doi}" if doi else "DOI: ")
        header_lines.append(f"Visit Date: {exam_date}")

        print_name = pdf_exam_label(exam_name)
        exam_line = (
            f"{print_name} — Page {page_in_exam} of {total_in_exam}"
            if print_name else
            f"Page {page_in_exam} of {total_in_exam}"
        )


        self.saveState()
        self.setFont("Helvetica", 9)

        y = y2
        for line in header_lines:
            self.drawString(left, y, line)
            y -= line_gap

        self.setFont("Helvetica-Bold", 9)
        self.drawRightString(right, y2, exam_line)

        self.setLineWidth(0.5)
        self.setStrokeColor(colors.lightgrey)
        self.line(left, y2 - (len(header_lines) * line_gap) - 2, right, y2 - (len(header_lines) * line_gap) - 2)
        self.restoreState()

    def save(self):
        exam_pages = {}
        page_exam_name = []

        for state in self._saved_page_states:
            ex = (state.get("_current_exam_name") or "").strip() or "Exam"
            page_exam_name.append(ex)
            exam_pages[ex] = exam_pages.get(ex, 0) + 1

        seen_in_exam = {}
        for idx, state in enumerate(self._saved_page_states):
            self.__dict__.update(state)
            ex = page_exam_name[idx]
            seen_in_exam[ex] = seen_in_exam.get(ex, 0) + 1

            self._draw_header(
                ex,
                state.get("_current_patient") or {},
                state.get("_current_exam_date") or "",
                seen_in_exam[ex],
                exam_pages[ex]
            )
            super().showPage()

        super().save()


DX_AUTO_TAG = "[AUTO:DX]"

def _strip_dx_auto_tag(text: str) -> str:
    lines = (text or "").splitlines()
    if lines and lines[-1].strip() == DX_AUTO_TAG:
        lines = lines[:-1]
    return "\n".join(lines).strip()
       

def _diagnosis_text_from_struct(dx_struct: dict) -> str:
    """
    Convert DiagnosisPage.to_dict() format into a printable text block.
    Prefers dx_struct["text"] if present, else builds from blocks.
    """
    if not isinstance(dx_struct, dict):
        return ""

    # If the page stored a text box value, use it
    txt = (dx_struct.get("text") or "").strip()
    if txt:
        return _strip_dx_auto_tag(txt)


    blocks = dx_struct.get("blocks") or []
    if not isinstance(blocks, list) or not blocks:
        return ""

    lines = []
    n = 1
    for b in blocks:
        if not isinstance(b, dict):
            continue

        label = (b.get("dx_label") or "").strip()
        code = (b.get("icd10") or "").strip()
        edit = (b.get("edit_text") or "").strip()

        text = edit or label
        if not text:
            continue

        if code:
            lines.append(f"{n}. {text} ({code})")
        else:
            lines.append(f"{n}. {text}")
        n += 1

    return "\n".join(lines).strip()




# =======================================================
# Payload parsing
# =======================================================
def payload_to_exam_sections(payload: dict):
    payload = payload or {}
    exam_name = payload.get("exam", "Exam")
    patient = payload.get("patient", {}) or {}
    soap = payload.get("soap", {}) or {}
    subj = soap.get("subjectives") or {}

    narratives = []
    for b in (subj.get("blocks") or []):
        region = (b.get("region") or "").strip()
        if region in REGION_LABELS:
            title = REGION_LABELS[region]
            text = (b.get("narrative") or "").strip()
            if text:
                narratives.append({
                    "title": title,
                    "text": text,
                    "tokens": tokens_from_subjective_block(b),
                })

    family_social = (soap.get("family_social") or "").strip()

    objectives_text = (soap.get("objectives") or "").strip()
    objectives_struct = soap.get("objectives_struct") or {}

    dx_text = (soap.get("diagnosis") or "").strip()
    if not dx_text:
        dx_struct = soap.get("diagnosis_struct") or {}
        dx_text = _diagnosis_text_from_struct(dx_struct)

    diagnosis = dx_text

    plan_struct = soap.get("plan", {}) or {}

    exam_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
    return exam_name, patient, narratives, family_social, objectives_text, objectives_struct, diagnosis, plan_struct, exam_date



# =======================================================
# PDF builder
# =======================================================
def build_combined_pdf(path: str, payloads: list):
    styles = getSampleStyleSheet()

    rom_motion = ParagraphStyle(
        name="ROMMotion",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        spaceBefore=0,
        spaceAfter=0,
    )
    if "ROMMotion" not in styles.byName:
        styles.add(rom_motion)

    
    subj_body = ParagraphStyle(
        name="SubjectiveBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        spaceBefore=0,
        spaceAfter=0,
    )
    if "SubjectiveBody" not in styles.byName:
        styles.add(subj_body)

    obj_col_head = ParagraphStyle(
        name="ObjColHead",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        alignment=1,
        spaceBefore=0,
        spaceAfter=0,
    )
    obj_col_body = ParagraphStyle(
        name="ObjColBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        alignment=1,
        spaceBefore=0,
        spaceAfter=0,
    )
    if "ObjColHead" not in styles.byName:
        styles.add(obj_col_head)
    if "ObjColBody" not in styles.byName:
        styles.add(obj_col_body)

    obj_section_center = ParagraphStyle(
        name="ObjSectionCenter",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        alignment=1,
        spaceBefore=0,
        spaceAfter=0,
    )
    if "ObjSectionCenter" not in styles.byName:
        styles.add(obj_section_center)

    _RE_REEXAM_NUM = re.compile(r"^\s*Re-Exam\s+(\d+)\s*$", re.IGNORECASE)
    _RE_ROF_NUM    = re.compile(r"^\s*Review of Findings\s+(\d+)\s*$", re.IGNORECASE)

    def _exam_sort_key(name: str):
        s = (name or "").strip()

        # Put Initial first if present
        if s.lower() == "initial":
            return (0, 0)

        m = _RE_ROF_NUM.match(s)
        if m:
            return (1, int(m.group(1)))

        m = _RE_REEXAM_NUM.match(s)
        if m:
            return (2, int(m.group(1)))

        # everything else after
        return (9, 0)

    payloads = sorted(payloads or [], key=lambda p: _exam_sort_key((p or {}).get("exam", "")))


    doc = SimpleDocTemplate(
        path,
        pagesize=LETTER,
        rightMargin=72,
        leftMargin=72,
        topMargin=170,
        bottomMargin=72
    )
    doc_width = doc.width

    story = []
    for idx, payload in enumerate(payloads):
        exam_name, patient, narratives, family_social, objectives_text, objectives_struct, diagnosis, plan_struct, exam_date = payload_to_exam_sections(payload)


        story.append(ExamStart(exam_name, patient, exam_date))
        print_name = pdf_exam_label(exam_name)
        story.append(Paragraph(f"<b>Chiropractic PI – {xml_escape(print_name)}</b>", styles["Title"]))

        story.append(Spacer(1, 0.15 * inch))

        display_name = (patient.get("display_name") or patient.get("name") or "")

        data = [
            ["Patient:", display_name, "DOB:", patient.get("dob", "")],
            ["DOI:", patient.get("doi", ""), "Visit Date:", exam_date],
            ["Claim #:", patient.get("claim", ""), "Provider (DC):", patient.get("provider", "")],
        ]

        table = Table(data, colWidths=[1.2 * inch, 2.8 * inch, 1.3 * inch, 1.7 * inch])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.18 * inch))

        # HOI (History of Injury)
        soap = payload.get("soap", {}) or {}
        hoi_struct = soap.get("hoi_struct") or {}
        hoi_flow = build_hoi_flowables(hoi_struct, styles, doc_width)
        if hoi_flow:
            story.extend(hoi_flow)
            story.append(Spacer(1, 0.12 * inch))

        # manual = _hoi_manual_text_for_exam(exam_name, hoi_struct)
        # if manual:
        #     story.append(Paragraph("<b>Additional Notes</b>", styles["Heading3"]))
        #     story.append(Spacer(1, 0.06 * inch))
        #     safe = xml_escape(manual).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
        #     story.append(Paragraph(safe, styles["BodyText"]))
        #     story.append(Spacer(1, 0.12 * inch))


        # Subjectives
        story.append(Paragraph("<b>Subjectives</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.08 * inch))

        if narratives:
            for item in narratives:
                title = item["title"]
                text = item["text"]
                tokens = item.get("tokens") or []

                heading = Paragraph(f"<b>{xml_escape(title)}</b>", styles["Heading3"])
                heading.keepWithNext = False

                body_markup = semibold_markup(text, tokens)
                body = Paragraph(body_markup, styles["SubjectiveBody"])

                story.append(heading)
                story.append(Spacer(1, 0.04 * inch))
                story.append(body)
                story.append(Spacer(1, 0.10 * inch))
        else:
            story.append(Paragraph("—", styles["BodyText"]))

        story.append(Spacer(1, 0.12 * inch))

        # ✅ Functional Status / ADLs — printed after Subjectives
        adl_para = None
        try:
            gs = (objectives_struct or {}).get("global") or {}
            adl = gs.get("adl") or {}
            adl_para = _build_adl_paragraph(adl, styles)
        except Exception:
            adl_para = None

        if adl_para:
            story.append(Paragraph("<b>Functional Status / ADLs</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.08 * inch))
            story.append(adl_para)
            #story.append(Spacer(1, 0.12 * inch))

        # ✅ Family / Social History (between Subjectives and Objectives)
        story.append(Paragraph("<b>Family / Social History</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.08 * inch))

        if family_social:
            safe_fs = xml_escape(family_social).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
            story.append(Paragraph(safe_fs, styles["BodyText"]))
        else:
            story.append(Paragraph("—", styles["BodyText"]))

        story.append(Spacer(1, 0.12 * inch))


        # Objectives
        story.append(Paragraph("<b>Objectives</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.10 * inch))

        obj_flow = build_objectives_flowables(objectives_struct, styles, doc_width)

        if obj_flow:
            story.extend(obj_flow)
        else:
            safe_obj = (objectives_text or "").strip()
            if safe_obj:
                safe_obj = xml_escape(safe_obj).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
                story.append(Paragraph(safe_obj, styles["BodyText"]))
            else:
                story.append(Paragraph("—", styles["BodyText"]))

        story.append(Spacer(1, 0.10 * inch))

        def _dx_text_from_soap(soap: dict) -> str:
            soap = soap or {}
            dx_struct = soap.get("diagnosis_struct") or {}

            # 1) Prefer dx_struct["text"] if present
            if isinstance(dx_struct, dict):
                t = (dx_struct.get("text") or "").strip()
                if t:
                    return _strip_dx_auto_tag(t)


                # 2) Else build from blocks
                blocks = dx_struct.get("blocks") or []
                if isinstance(blocks, list) and blocks:
                    lines = []
                    n = 1
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        label = (b.get("dx_label") or "").strip()
                        code = (b.get("icd10") or "").strip()
                        edit = (b.get("edit_text") or "").strip()

                        text = edit or label
                        if not text:
                            continue

                        lines.append(f"{n}. {text}" + (f" ({code})" if code else ""))
                        n += 1

                    out = "\n".join(lines).strip()
                    if out:
                        return out

            # 3) Fallback to legacy string if struct missing
            return _strip_dx_auto_tag((soap.get("diagnosis") or "").strip())



        # Diagnosis / Plan
        def add_section(title: str, content: str):
            story.append(Paragraph(f"<b>{xml_escape(title)}</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.08 * inch))

            safe = (content or "").strip()
            if safe:
                safe = xml_escape(safe).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
                story.append(Paragraph(safe, styles["BodyText"]))
            else:
                story.append(Paragraph("—", styles["BodyText"]))

            story.append(Spacer(1, 0.14 * inch))

        dx_text = _dx_text_from_soap(soap)
        add_section("Diagnosis", dx_text)

        dx_struct = soap.get("diagnosis_struct") or {}

        prog = (dx_struct.get("prognosis") or "").strip()
        if prog and prog != "(select)":
            add_section("Prognosis", prog)

        img = _imaging_sentence(dx_struct)
        if img:
            add_section("Imaging", img)

        ref = _referral_sentence(dx_struct)
        if ref:
            add_section("Referrals", ref)


        # ✅ Plan (structured PDF rendering)
        plan_flow = build_plan_flowables(plan_struct, styles)
        if plan_flow:
            story.extend(plan_flow)
            story.append(Spacer(1, 0.14 * inch))
        else:
            add_section("Plan", "")


        story.append(Spacer(1, 0.18 * inch))
        story.append(Paragraph("Provider Signature: ________________________________", styles["Normal"]))

        if idx < len(payloads) - 1:
            story.append(PageBreak())

    doc.build(story, canvasmaker=HeaderExamNumberedCanvas)








