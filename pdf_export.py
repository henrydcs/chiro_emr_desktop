# pdf_export.py
from __future__ import annotations

import os
import re
from xml.sax.saxutils import escape as xml_escape

from HOIpdf import build_hoi_flowables
from plan_pdf import build_plan_flowables

from reportlab.platypus import Table, TableStyle, KeepTogether, Paragraph
from reportlab.lib import colors

from reportlab.lib.styles import getSampleStyleSheet
from HOIpdf import build_rof_flowables

from config import (
    LOGO_PATH, CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX,
    REGION_LABELS
)
from utils import normalize_mmddyyyy, today_mmddyyyy, build_sentence

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

#from xml.sax.saxutils import escape as xml_escape
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
    if s.lower().startswith("initial"):
        return "Initial Evaluation"
    if _RE_REEXAM.match(s):
        return "Re-Evaluation"
    if _RE_ROF.match(s):
        return "Review of Findings"
    if s.lower().startswith("final"):
        return "Final Evaluation"
    # ✅ NEW: Chiropractic Treatment Note (no numbering)
    if s.lower().startswith("chiro visit"):
        return "Chiropractic Treatment Note"    
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
    # Group by modality (order of first occurrence); value = list of body parts, no duplicates per modality
    groups = {}
    for r in recs:
        if not isinstance(r, dict):
            continue
        mod = (r.get("modality") or "").strip()
        bp = (r.get("body_part") or "").strip()
        if not mod or not bp:
            continue
        if mod not in groups:
            groups[mod] = []
        if bp not in groups[mod]:
            groups[mod].append(bp)
    # One phrase per modality: "X-ray of Thoracic Spine" or "X-ray of the Thoracic Spine and Cervical Spine"
    parts = []
    for mod, body_parts in groups.items():
        if len(body_parts) == 1:
            parts.append(f"{mod} of {body_parts[0]}")
        else:
            body_joined = _join_with_and(body_parts)
            parts.append(f"{mod} of the {body_joined}")
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
    return f"Due to medical necessity, the patient will need to be referred to the following provider(s): {joined}." if joined else ""

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


def _auto_text_from_block(
    block: dict,
    first_name: str = "",
    last_name: str = "",
    use_first_name: bool = True,
) -> str:
    """
    Rebuild the auto-generated subjective paragraph from block dict.
    Same logic as DescriptorBlock.get_auto_generated_text(), but allows
    using patient's first or last name instead of generic 'The patient'.
    """
    block = block or {}

    # Decide which name to use as the subject in sentences.
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()

    if use_first_name and first_name:
        subject = first_name
    elif last_name:
        subject = last_name
    else:
        subject = "The patient"

    region = (block.get("region") or "").strip()
    label = REGION_LABELS.get(region, "")
    if not region or region == "(none)" or not label:
        return ""

    base = build_sentence(
        label,
        block.get("desc1", ""),
        block.get("desc2", ""),
        block.get("radic_symptom", "None"),
        block.get("radic_location", "(select)"),
        subject=subject,
    )

    muscles = block.get("muscles") or []
    tenderness = ""
    if len(muscles) == 1:
        tenderness = (
            f"Our patient indicates or points to the {muscles[0]} as the area of tenderness."
        )
    elif len(muscles) == 2:
        tenderness = (
            f"Our patient indicates or points to the {muscles[0]} and the {muscles[1]} "
            f"as the areas of tenderness."
        )
    elif len(muscles) > 2:
        mid = ", ".join(muscles[:-1])
        last = muscles[-1]
        tenderness = (
            f"Our patient indicates or points to the {mid}, and the {last} "
            f"as the areas of tenderness."
        )

    scale = (block.get("pain_scale") or "None").strip().lower()
    pain_line = f"{subject} states the overall discomfort in this area is {scale}."

    parts = [base]
    if tenderness:
        parts.append(tenderness)
    if scale.lower() != "select":
        parts.append(pain_line)
    return "\n\n".join(p for p in parts if p.strip())


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


def _build_sublux_paragraph(sx: dict, styles):
    """
    Returns ONLY the subluxation summary paragraph (no Notes: line).
    Notes are handled separately by _notes_paragraph() to match other sections.
    """
    if not isinstance(sx, dict):
        return None

    regions = sx.get("regions") or {}
    if not isinstance(regions, dict):
        regions = {}

    levels = sx.get("levels") or {}
    if not isinstance(levels, dict):
        levels = {}

    # Region sentence
    region_names = {"CS": "Cervical Spine", "TS": "Thoracic Spine", "LS": "Lumbar Spine"}
    selected_regions = [region_names[k] for k, v in regions.items() if bool(v) and k in region_names]

    # Sort levels: C#, then T#, then L#
    def sort_key(lv: str):
        lv = (lv or "").strip().upper()
        if not lv:
            return (9, 999)
        order = {"C": 0, "T": 1, "L": 2}
        try:
            num = int(lv[1:])
        except Exception:
            num = 999
        return (order.get(lv[0], 9), num)

    level_parts = []
    for lv in sorted(levels.keys(), key=sort_key):
        st = levels.get(lv) or {}
        if not isinstance(st, dict):
            st = {}

        listing = (st.get("listing") or "").strip()
        motion = st.get("motion") or []
        if not isinstance(motion, list):
            motion = []

        # ✅ ALWAYS include the level if it exists in the dict
        piece = lv

        if listing and listing != "(none)":
            piece += f" {listing}"

        motion_clean = [str(x).strip() for x in motion if str(x).strip()]
        if motion_clean:
            piece += " MR: " + ", ".join(motion_clean)

        level_parts.append(piece)

    # If no content at all, return None
    if not selected_regions and not level_parts:
        return None

    lines = []
    if selected_regions:
        lines.append(
            "Restricted joint motion consistent with segmental dysfunction was noted in the " +
            _join_with_and(selected_regions) +
            "."
        )

    if level_parts:
        lines.append(
            "Specific levels: " +
            _join_with_and(level_parts) +
            "."
        )

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
        parts.append(f"ADL Overall Impact Severity: {sev} — {SEVERITY_LABELS.get(sev, '')}".strip())

    clean_items = [str(x).strip() for x in items if str(x).strip()]
    if clean_items:
        parts.append("Activities of Daily Living: " + ", ".join(clean_items))

    if notes:
        parts.append("Notes: " + notes)

    safe = xml_escape("\n".join(parts)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])

def adl_dict_to_plain_text(adl: dict) -> str:
    """
    Build plain-text ADL content for Live Preview, mirroring _build_adl_paragraph.
    Returns empty string if no content.
    """
    if not isinstance(adl, dict):
        return ""

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
        return ""

    parts = []
    if sev != -1:
        parts.append(f"ADL Overall Impact Severity: {sev} — {SEVERITY_LABELS.get(sev, '')}".strip())

    clean_items = [str(x).strip() for x in items if str(x).strip()]
    if clean_items:
        parts.append("Activities of Daily Living: " + ", ".join(clean_items))

    if notes:
        parts.append("Notes: " + notes)

    return "\n".join(parts)

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
        sublux = global_struct.get("sublux") or {}
        sublux_para = _build_sublux_paragraph(sublux, styles)
        sublux_notes = _notes_paragraph(_clean_val(sublux.get("notes")), styles)

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

        if vit_tbl or pos_para or grip_para or adl_para or vit_notes or pos_notes or grip_notes or sublux_para or sublux_notes:

            printed_any = True            

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

            if sublux_para or sublux_notes:
                out.append(Paragraph("<b>Spinal Palpatory Inspection</b>", styles["Heading4"]))  # ✅ same size/style as others
                out.append(Spacer(1, 0.05 * inch))
                if sublux_para:
                    out.append(sublux_para)
                if sublux_notes:
                    out.append(Spacer(1, 0.10 * inch))
                    out.append(sublux_notes)
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

        # ✅ FILTER OUT motions where both sides are -1
        rom_merged = {
            m: st for m, st in (rom_merged or {}).items()
            if int((st or {}).get("l_sev", -1)) != -1 or int((st or {}).get("r_sev", -1)) != -1
        }
        rom_has_findings = bool(rom_merged)

        palp_notes = _notes_paragraph(first_note(region_blocks, "palpation_notes"), styles)
        ortho_notes = _notes_paragraph(first_note(region_blocks, "ortho_notes"), styles)
        rom_notes = _notes_paragraph(first_note(region_blocks, "rom_notes"), styles)

        has_any = bool(
            palp_left or palp_right or palp_notes or
            ortho_left or ortho_right or ortho_notes or
            rom_has_findings or rom_notes
        )
        if not has_any:
            continue

        printed_any = True
        out.append(Paragraph(f"<b>{xml_escape(region_title)}</b>", styles["Heading3"]))
        out.append(Spacer(1, 0.10 * inch))

        tag = _region_tag(code)

        if palp_left or palp_right or palp_notes:
            out.append(Paragraph(f"<b>SOFT TISSUE PALPATION {xml_escape(tag)}</b>", styles["ObjSectionCenter"]))
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
                                   
    return out if printed_any else []

def objectives_struct_to_live_preview_runs(objectives_struct: dict, *, include_adl: bool = True) -> list[tuple[str, str | None]]:
    """
    Build Live Preview runs from objectives_struct, mirroring PDF structure.
    Returns [(chunk, tag), ...] with tag "H_BOLD" for headings.
    """
    runs: list[tuple[str, str | None]] = []
    objectives_struct = objectives_struct or {}
    global_struct = objectives_struct.get("global") or {}
    if not isinstance(global_struct, dict):
        global_struct = {}

    def add_section(heading: str, body: str):
        if not body.strip():
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        runs.append((body.strip() + "\n\n", None))

    # Vitals
    vitals = global_struct.get("vitals") or {}
    if isinstance(vitals, dict):
        fields = [("BP:", "bp"), ("Pulse:", "pulse"), ("Resp:", "resp"), ("Temp:", "temp"),
                  ("Height:", "height"), ("Weight:", "weight"), ("SpO₂:", "spo2")]
        pairs = []
        for label, key in fields:
            val = _clean_val(vitals.get(key, ""))
            if val:
                pairs.append(f"{label} {val}")
        if pairs:
            lines = [" ".join(pairs[i:i+4]) for i in range(0, len(pairs), 4)]
            body = "\n".join(lines)
            vit_notes = _clean_val(vitals.get("notes"))
            if vit_notes:
                body += "\n\nNotes: " + vit_notes
            add_section("Vitals", body)

    # Posture
    posture = global_struct.get("posture") or {}
    if isinstance(posture, dict):
        lines = []
        for label, key in [("Shoulder Levels", "shoulder_levels"), ("Kyphosis (T/S)", "kyphosis_ts"),
                           ("Forward Head Posture (C/S)", "forward_head_cs"), ("Lordosis (L/S)", "lordosis_ls")]:
            val = _clean_val(posture.get(key))
            if val:
                lines.append(f"{label}: {val}")
        if lines:
            body = "\n".join(lines)
            pos_notes = _clean_val(posture.get("notes"))
            if pos_notes:
                body += "\n\nNotes: " + pos_notes
            add_section("Posture", body)

    # Spinal Palpatory Inspection (sublux)
    sublux = global_struct.get("sublux") or {}
    if isinstance(sublux, dict):
        regions = sublux.get("regions") or {}
        region_names = {"CS": "Cervical Spine", "TS": "Thoracic Spine", "LS": "Lumbar Spine"}
        selected = [region_names[k] for k, v in regions.items() if bool(v) and k in region_names]
        levels = sublux.get("levels") or {}
        level_parts = []
        for lv in sorted(levels.keys(), key=lambda x: ({"C": 0, "T": 1, "L": 2}.get((x or "")[0:1].upper(), 9), int((x or "0")[1:] or 0))):
            st = levels.get(lv) or {}
            piece = lv
            listing = (st.get("listing") or "").strip()
            if listing and listing != "(none)":
                piece += f" {listing}"
            motion = st.get("motion") or []
            motion_clean = [str(x).strip() for x in motion if str(x).strip()]
            if motion_clean:
                piece += " MR: " + ", ".join(motion_clean)
            level_parts.append(piece)
        if selected or level_parts:
            lines = []
            if selected:
                lines.append("Restricted joint motion consistent with segmental dysfunction was noted in the " + _join_with_and(selected) + ".")
            if level_parts:
                lines.append(" ".join(level_parts))
            body = "\n".join(lines)
            sx_notes = _clean_val(sublux.get("notes"))
            if sx_notes:
                body += "\n\nNotes: " + sx_notes
            add_section("Spinal Palpatory Inspection", body)

    # Grip Strength
    grip = global_struct.get("grip") or {}
    if isinstance(grip, dict):
        left = _clean_val(grip.get("left"))
        right = _clean_val(grip.get("right"))
        compare = _clean_val(grip.get("compare"))
        if left or right or compare:
            parts = []
            if left:
                parts.append(f"Left: {left}")
            if right:
                parts.append(f"Right: {right}")
            if compare:
                parts.append(f"Compare: {compare}")
            body = "\n".join(parts)
            grip_notes = _clean_val(grip.get("notes"))
            if grip_notes:
                body += "\n\nNotes: " + grip_notes
            add_section("Grip Strength (Jamar)", body)

    # Region blocks
    blocks = objectives_struct.get("blocks") or []
    if isinstance(blocks, list):
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

        for code in order:
            region_blocks = grouped.get(code, [])
            if not region_blocks:
                continue
            label = _pretty_region(code)
            if not label:
                continue
            region_title = _region_group_name(label)
            tag = _region_tag(code)

            palp_left_all, palp_right_all = [], []
            ortho_left_all, ortho_right_all = [], []
            for b in region_blocks:
                findings = _collect_objectives_findings(b)
                pL, pR = findings["PALPATION"]
                oL, oR = findings["ORTHOPEDIC EXAM"]
                palp_left_all.append(pL)
                palp_right_all.append(pR)
                ortho_left_all.append(oL)
                ortho_right_all.append(oR)

            def merge_findings(lsts):
                seen = set()
                out = []
                for L in lsts:
                    for item in L:
                        key = (item[0], item[1]) if len(item) >= 2 else (item[0],)
                        if key not in seen:
                            seen.add(key)
                            out.append(item)
                return out

            palp_left = merge_findings(palp_left_all)
            palp_right = merge_findings(palp_right_all)
            ortho_left = merge_findings(ortho_left_all)
            ortho_right = merge_findings(ortho_right_all)

            try:
                rom_merged = _merge_rom_struct(region_blocks) or {}
            except Exception:
                rom_merged = {}
            rom_merged = {m: st for m, st in (rom_merged or {}).items()
                         if int((st or {}).get("l_sev", -1)) != -1 or int((st or {}).get("r_sev", -1)) != -1}

            def first_note(region_blocks, key):
                for bb in region_blocks:
                    txt = _clean_val(bb.get(key, ""))
                    if txt:
                        return txt
                return ""

            palp_notes = first_note(region_blocks, "palpation_notes")
            ortho_notes = first_note(region_blocks, "ortho_notes")
            rom_notes = first_note(region_blocks, "rom_notes")

            has_any = bool(palp_left or palp_right or palp_notes or ortho_left or ortho_right or ortho_notes or rom_merged or rom_notes)
            if not has_any:
                continue

            runs.append((region_title + "\n", "H_BOLD"))
            runs.append(("\n", None))

            if palp_left or palp_right or palp_notes:
                runs.append((f"SOFT TISSUE PALPATION {tag}\n", "H_BOLD"))
                if palp_left or palp_right:
                    for i in range(max(len(palp_left), len(palp_right), 1)):
                        lstr = f"{palp_left[i][0]}: {palp_left[i][1]}" if i < len(palp_left) else ""
                        rstr = f"{palp_right[i][0]}: {palp_right[i][1]}" if i < len(palp_right) else ""
                        runs.append((f"LEFT: {lstr}  |  RIGHT: {rstr}\n", None))
                if palp_notes:
                    runs.append((f"Notes: {palp_notes}\n\n", None))

            if ortho_left or ortho_right or ortho_notes:
                runs.append((f"ORTHOPEDIC EXAM {tag}\n", "H_BOLD"))
                if ortho_left or ortho_right:
                    for i in range(max(len(ortho_left), len(ortho_right), 1)):
                        lstr = f"{ortho_left[i][0]}: {ortho_left[i][1]}" if i < len(ortho_left) else ""
                        rstr = f"{ortho_right[i][0]}: {ortho_right[i][1]}" if i < len(ortho_right) else ""
                        runs.append((f"LEFT: {lstr}  |  RIGHT: {rstr}\n", None))
                if ortho_notes:
                    runs.append((f"Notes: {ortho_notes}\n\n", None))

            if rom_merged or rom_notes:
                runs.append((f"RANGE OF MOTION {tag}\n", "H_BOLD"))
                REGION_ROM_MOTIONS = {
                    "CS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
                    "TS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
                    "LS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
                    "R_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                    "L_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                    "BL_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
                }
                motions = REGION_ROM_MOTIONS.get(code, ["Flexion", "Extension", "Lateral Flexion", "Rotation"])
                for m in motions:
                    st = (rom_merged or {}).get(m) or {}
                    l_sev = int(st.get("l_sev", -1))
                    r_sev = int(st.get("r_sev", -1))
                    if l_sev != -1 or r_sev != -1:
                        l_txt = SEVERITY_LABELS.get(l_sev, "") if l_sev != -1 else ""
                        r_txt = SEVERITY_LABELS.get(r_sev, "") if r_sev != -1 else ""
                        runs.append((f"{m}: L={l_txt or '-'} R={r_txt or '-'}\n", None))
                if rom_notes:
                    runs.append((f"Notes: {rom_notes}\n\n", None))

            runs.append(("\n", None))

    return runs

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
    Always builds from blocks (diagnosis section). The "text" field is general notes.
    """
    if not isinstance(dx_struct, dict):
        return ""

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
# Subjectives: Therapy Only (checkbox paragraph)
# =======================================================
THERAPY_BODY_PARTS = [
    "Neck", "Upper Back", "Mid-Back", "Low Back", "Pelvic Area",
    "Left Hip", "Right Hip", "Left Buttock", "Right Buttock",
    "Left Thigh", "Right Thigh", "Left Knee", "Right Knee",
    "Left Ankle", "Right Ankle", "Left Foot", "Right Foot",
    "Left Toes", "Right Toes",
    "Left Shoulder", "Right Shoulder",
    "Left Arm", "Right Arm",
    "Left Elbow", "Right Elbow",
    "Left Forearm", "Right Forearm",
    "Left Wrist", "Right Wrist",
    "Left Hand", "Right Hand",
    "Left Fingers", "Right Fingers",
]

def therapy_paragraph_from_subjectives(subj: dict, first_name: str = "") -> tuple[str, list[str]]:
    """
    Returns: (text, tokens)
    Uses subj["therapy_main"] if present and still checked.
    Falls back to fixed list order if missing.
    """
    subj = subj or {}
    first_name = (first_name or "").strip()
    therapy_state = subj.get("therapy_only") or {}
    if not isinstance(therapy_state, dict):
        return "", []

    selected = [name for name in THERAPY_BODY_PARTS if bool(therapy_state.get(name, False))]
    if not selected:
        return "", []

    main = (subj.get("therapy_main") or "").strip()
    if main not in selected:
        main = selected[0]

    others = [x for x in selected if x != main]

    s1 = (
        f"{first_name} states being primarily concerned with symptoms located in the following area(s): "
        f"{main} region."
    )
    if not others:
        return s1, selected

    s2 = f"The patient also feels discomfort in the {_join_with_and(others)}."
    return (s1 + " " + s2), selected

# =======================================================
# Payload parsing
# =======================================================
def payload_to_exam_sections(payload: dict):
    payload = payload or {}
    exam_name = payload.get("exam", "Exam")
    patient = payload.get("patient", {}) or {}
    first_name = (patient.get("first_name") or "").strip()
    soap = payload.get("soap", {}) or {}
    subj = soap.get("subjectives") or {}

    narratives = []
    user_narratives = []
    for b in (subj.get("blocks") or []):
        region = (b.get("region") or "").strip()
        user_text = (b.get("narrative") or "").strip()
        included_in_narrative = False

        if region in REGION_LABELS:
            tokens = tokens_from_subjective_block(b)
            if tokens:
                auto_text = _auto_text_from_block(
                    b,
                    first_name=first_name,
                    last_name=patient.get("last_name", ""),
                    use_first_name=True,
                )
                if auto_text:
                    # Append this block's textbox as last sentence(s) of this body region block
                    combined_text = auto_text + ("\n\n" + user_text if user_text else "")
                    narratives.append({
                        "title": REGION_LABELS[region],
                        "text": combined_text,
                        "tokens": tokens,
                    })
                    included_in_narrative = True

        if user_text and not included_in_narrative:
            user_narratives.append(user_text)

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
    return exam_name, patient, narratives, user_narratives, family_social, objectives_text, objectives_struct, diagnosis, plan_struct, exam_date

def _assessment_paragraph(dx_struct: dict, styles):
    dx_struct = dx_struct or {}

    choice = (dx_struct.get("assessment_choice") or "").strip()
    custom = (dx_struct.get("assessment_custom") or "").strip()

    ASSESSMENT_TEXT = {
        "Standard exam / evaluation day":
            "Clinical findings are consistent with the diagnoses listed below based on the patient’s history and objective examination.",
        "Therapy-only visit":
            "The patient was seen for continuation of therapeutic treatment per the established plan of care. No re-examination was performed at this visit.",
        "Re-exam / progress visit":
            "Findings were reviewed and treatment response assessed. The diagnoses listed below remain consistent with the patient’s presentation at this visit.",
        "Discharge / final visit":
            "The patient was seen for final assessment and disposition. Diagnoses and clinical status were reviewed, and ongoing recommendations are documented below.",
    }

    if choice == "Custom (free text)" and custom:
        text = custom
    else:
        text = ASSESSMENT_TEXT.get(choice, "")

    if not text:
        return None

    safe = xml_escape(text).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])

def _employment_current_status_paragraph(dx_struct: dict, styles):
    """
    Assessment-side: current employment + optional work plan + notes.
    Heading handled outside (so you can control layout).
    """
    dx_struct = dx_struct or {}

    status = (dx_struct.get("employment_status") or "").strip()
    other  = (dx_struct.get("employment_other") or "").strip()
    #work_plan = (dx_struct.get("work_plan") or "").strip()
    notes = (dx_struct.get("employment_notes") or "").strip()

    lines = []

    if status and status != "(select)":
        if status == "Other (free text)" and other:
            lines.append(f"The patient is {other}")
        else:
            lines.append(f"The patient is {status}")
   
    if notes:
        lines.append(f"Notes: {notes}")

    if not lines:
        return None

    safe = xml_escape("\n".join(lines)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])


def diagnosis_struct_to_live_preview_runs(dx_struct: dict) -> list[tuple[str, str | None]]:
    """
    Build Live Preview runs from diagnosis_struct, mirroring PDF Assessment section.
    Returns [(chunk, tag), ...] with tag "H_BOLD" for headings.
    """
    runs: list[tuple[str, str | None]] = []
    dx_struct = dx_struct or {}

    def add_section(heading: str, body: str):
        if not (body or "").strip():
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        runs.append(((body or "").strip() + "\n\n", None))

    # Assessment statement (choice or custom)
    ASSESSMENT_TEXT = {
        "Standard exam / evaluation day":
            "Clinical findings are consistent with the diagnoses listed below based on the patient's history and objective examination.",
        "Therapy-only visit":
            "The patient was seen for continuation of therapeutic treatment per the established plan of care. No re-examination was performed at this visit.",
        "Re-exam / progress visit":
            "Findings were reviewed and treatment response assessed. The diagnoses listed below remain consistent with the patient's presentation at this visit.",
        "Discharge / final visit":
            "The patient was seen for final assessment and disposition. Diagnoses and clinical status were reviewed, and ongoing recommendations are documented below.",
    }
    choice = (dx_struct.get("assessment_choice") or "").strip()
    custom = (dx_struct.get("assessment_custom") or "").strip()
    if choice == "Custom (free text)" and custom:
        assessment_text = custom
    else:
        assessment_text = ASSESSMENT_TEXT.get(choice, "")
    if assessment_text:
        runs.append((assessment_text.strip() + "\n\n", None))
    assessment_notes = (dx_struct.get("assessment_notes") or "").strip()
    if assessment_notes:
        runs.append(("\n", None))
        runs.append((assessment_notes + "\n\n", None))

    # Diagnosis
    dx_text = _diagnosis_text_from_struct(dx_struct)
    if dx_text:
        add_section("Diagnosis", dx_text)
    dx_block_notes = (dx_struct.get("dx_block_notes") or "").strip()
    if dx_block_notes:
        runs.append(("\n", None))
        runs.append((dx_block_notes + "\n\n", None))

    # Causation
    CAUSATION_TEXT = {
        "Causally related (WDM certainty)":
            "Within a reasonable degree of medical probability, it is my professional opinion that the patient's diagnosed conditions are directly related to the reported mechanism of injury. The forces typically generated by the described type of accident are biomechanically capable of producing the patient's documented symptom pattern. The reported complaints, functional limitations, and objective findings demonstrate a clear clinical correlation consistent with the mechanism described.",
        "Clinically consistent with reported mechanism (conservative)":
            "The patient's presentation and examination findings are clinically consistent with the reported mechanism of injury.",
        "Aggravation of pre-existing condition":
            "The current condition represents an aggravation of a pre-existing condition, as supported by the patient's history and current clinical findings.",
        "Not causally related":
            "Based on the available history and examination findings, the diagnosed conditions are not causally related to the reported mechanism of injury.",
        "Unable to determine at this time":
            "Causation cannot be determined at this time based on the available information; additional history, records, and/or diagnostic testing may be required.",
    }
    causation_choice = (dx_struct.get("causation_choice") or "").strip()
    causation_custom = (dx_struct.get("causation_custom") or "").strip()
    causation_notes = (dx_struct.get("causation_notes") or "").strip()
    causation_lines = []
    if causation_choice == "Custom (free text)" and causation_custom:
        causation_lines.append(causation_custom)
    else:
        preset = CAUSATION_TEXT.get(causation_choice, "")
        if preset:
            causation_lines.append(preset)
    if causation_notes:
        causation_lines.append(f"Additional Notes: {causation_notes}")
    if causation_lines:
        add_section("Causation", "\n\n".join(causation_lines))
    causation_general_notes = (dx_struct.get("causation_general_notes") or "").strip()
    if causation_general_notes:
        runs.append(("\n", None))
        runs.append((causation_general_notes + "\n\n", None))

    # Prognosis
    prog = (dx_struct.get("prognosis") or "").strip()
    if prog and prog != "(select)":
        if prog.lower() == "guarded":
            prognosis_text = (
                "Based on the patient’s reported symptoms, objective findings, "
                "and functional impairments, the prognosis is currently assessed "
                f"as {prog}. Positive outcomes are expected, contingent "
                "upon the patient’s active engagement in care and treatment compliance."
            )
        else:
            prognosis_text = (
                "Based on the patient's clinical presentation and examination findings, "
                f"the prognosis is currently assessed as {prog}. Progress will be monitored "
                "and reassessed throughout the course of care."
            )
        add_section("Prognosis", prognosis_text)
    prognosis_notes = (dx_struct.get("prognosis_notes") or "").strip()
    if prognosis_notes:
        runs.append(("\n", None))
        runs.append((prognosis_notes + "\n\n", None))

    # Imaging
    img = _imaging_sentence(dx_struct)
    if img:
        add_section("Imaging", img)
    imaging_notes = (dx_struct.get("imaging_notes") or "").strip()
    if imaging_notes:
        runs.append(("\n", None))
        runs.append((imaging_notes + "\n\n", None))

    # Referrals
    ref = _referral_sentence(dx_struct)
    if ref:
        add_section("Referrals", ref)
    referrals_notes = (dx_struct.get("referrals_notes") or "").strip()
    if referrals_notes:
        runs.append(("\n", None))
        runs.append((referrals_notes + "\n\n", None))

    # Current Work Status
    status = (dx_struct.get("employment_status") or "").strip()
    other = (dx_struct.get("employment_other") or "").strip()
    notes = (dx_struct.get("employment_notes") or "").strip()
    emp_lines = []
    if status and status != "(select)":
        if status == "Other (free text)" and other:
            emp_lines.append(f"The patient is {other}")
        else:
            emp_lines.append(f"The patient is {status}")
    if notes:
        emp_lines.append(f"Notes: {notes}")
    if emp_lines:
        add_section("Current Work Status", "\n".join(emp_lines))
    employment_general_notes = (dx_struct.get("employment_general_notes") or "").strip()
    if employment_general_notes:
        runs.append(("\n", None))
        runs.append((employment_general_notes + "\n\n", None))

    return runs


def _causation_paragraph(dx_struct: dict, styles):
    dx_struct = dx_struct or {}

    choice = (dx_struct.get("causation_choice") or "").strip()
    custom = (dx_struct.get("causation_custom") or "").strip()
    notes = (dx_struct.get("causation_notes") or "").strip()

    

    CAUSATION_TEXT = {
        "Causally related (WDM certainty)":
            "Within a reasonable degree of medical probability, it is my professional opinion that the patient’s diagnosed conditions are directly related to the reported mechanism of injury. The forces typically generated by the described type of accident are biomechanically capable of producing the patient’s documented symptom pattern. The reported complaints, functional limitations, and objective findings demonstrate a clear clinical correlation consistent with the mechanism described.",
        "Clinically consistent with reported mechanism (conservative)":
            "The patient’s presentation and examination findings are clinically consistent with the reported mechanism of injury.",
        "Aggravation of pre-existing condition":
            "The current condition represents an aggravation of a pre-existing condition, as supported by the patient’s history and current clinical findings.",
        "Not causally related":
            "Based on the available history and examination findings, the diagnosed conditions are not causally related to the reported mechanism of injury.",
        "Unable to determine at this time":
            "Causation cannot be determined at this time based on the available information; additional history, records, and/or diagnostic testing may be required.",
    }

    lines = []

    if choice == "Custom (free text)" and custom:
        lines.append(custom)
    else:
        preset = CAUSATION_TEXT.get(choice, "")
        if preset:
            lines.append(preset)

    if notes:
        lines.append(f"Additional Notes: {notes}")

    if not lines:
        return None

    safe = xml_escape("\n\n".join(lines)).replace("\n", "<br/>")
    return Paragraph(safe, styles["BodyText"])

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
    
    def _visit_date_key(p: dict) -> tuple:
        """
        Ascending date (oldest -> newest).
        Falls back to '' if missing so those sort first.
        """
        patient = (p or {}).get("patient") or {}
        d = normalize_mmddyyyy(patient.get("exam_date", ""))  # returns MM/DD/YYYY or ""
        # Convert MM/DD/YYYY -> YYYY-MM-DD for proper lexical sort
        if d and re.match(r"^\d{2}/\d{2}/\d{4}$", d):
            mm, dd, yyyy = d.split("/")
            iso = f"{yyyy}-{mm}-{dd}"
        else:
            iso = ""
        return (iso,)

    def _combined_sort_key(p: dict) -> tuple:
        ex = (p or {}).get("exam", "")
        return _visit_date_key(p) + _exam_sort_key(ex)

    payloads = sorted(payloads or [], key=_combined_sort_key)


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
        exam_name, patient, narratives, user_narratives, family_social, objectives_text, objectives_struct, diagnosis, plan_struct, exam_date = payload_to_exam_sections(payload)


        story.append(ExamStart(exam_name, patient, exam_date))
        print_name = pdf_exam_label(exam_name)
        story.append(Paragraph(f"<b>{xml_escape(print_name)}</b>", styles["Title"]))


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

        # Subjectives
        story.append(Paragraph("<b>SUBJECTIVES</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.08 * inch))

                # ✅ NEW: Therapy paragraph prints FIRST (independent of dropdown/blocks)
        subj = (soap.get("subjectives") or {})
        first_name = (patient.get("first_name") or "").strip()
        therapy_text, therapy_tokens = therapy_paragraph_from_subjectives(subj, first_name=first_name)

        printed_any_subjectives = False

        if (therapy_text or "").strip():
            printed_any_subjectives = True
            # ✅ bold the selected body parts inside the therapy paragraph
            body_markup = semibold_markup(therapy_text, therapy_tokens or [])
            story.append(Paragraph(body_markup, styles["SubjectiveBody"]))
            story.append(Spacer(1, 0.10 * inch))

            printed_any_subjectives = True

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
            printed_any_subjectives = True

        if user_narratives:
            story.append(Spacer(1, 0.10 * inch))
            combined = "\n\n".join(user_narratives)
            story.append(Paragraph(semibold_markup(combined, []), styles["SubjectiveBody"]))
            printed_any_subjectives = True

        # ✅ Only print dash if NOTHING exists (no therapy + no narratives + no user narrative)
        if not printed_any_subjectives:
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
            story.append(Paragraph("<b>Functional Status</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.08 * inch))
            story.append(adl_para)
            story.append(Spacer(1, 0.12 * inch))

        # ✅ Family / Social History (print ONLY if not empty)
        if family_social:
            story.append(Paragraph("<b>FAMILY / SOCIAL HISTORY</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.08 * inch))

            safe_fs = xml_escape(family_social).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
            story.append(Paragraph(safe_fs, styles["BodyText"]))

            story.append(Spacer(1, 0.12 * inch))
        
        # Objectives
        obj_flow = build_objectives_flowables(objectives_struct, styles, doc_width)

        safe_obj = (objectives_text or "").strip()

        # ✅ If nothing is selected/entered, do NOT print the Objectives title at all
        if obj_flow or safe_obj:
            story.append(Paragraph("<b>OBJECTIVES</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.10 * inch))

            if obj_flow:
                story.extend(obj_flow)
            else:
                safe_obj = xml_escape(safe_obj).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
                story.append(Paragraph(safe_obj, styles["BodyText"]))

            story.append(Spacer(1, 0.10 * inch))

        rof_struct = (hoi_struct or {}).get("rof") or {}
        also_print = False
        if isinstance(rof_struct, dict):
            also_print = bool(rof_struct.get("also_print_rof_after_objectives", False))

        if also_print:
            # print ROF text even when mode is Initial/Re-Exam/Final
            story.extend(build_rof_flowables(hoi_struct, styles))
        else:
            # current behavior: only classic ROF/legacy
            story.extend(build_rof_flowables(hoi_struct, styles, allow_modes={"ROF", ""}))


        def _dx_text_from_soap(soap: dict) -> str:
            soap = soap or {}
            dx_struct = soap.get("diagnosis_struct") or {}

            # Match Live Preview: always build diagnosis from blocks
            if isinstance(dx_struct, dict):
                dx_text = _diagnosis_text_from_struct(dx_struct)
                if dx_text:
                    return dx_text

            # Fallback for legacy cases that only have soap["diagnosis"] string
            return _strip_dx_auto_tag((soap.get("diagnosis") or "").strip())


        # Diagnosis / Plan
        def add_section(title: str, content: str):
            story.append(Paragraph(f"<b>{xml_escape(title)}</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.08 * inch))

            safe = (content or "").strip()
            if safe:
                safe = xml_escape(safe).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
                story.append(Paragraph(safe, styles["BodyText"]))
            else:
                story.append(Paragraph("", styles["BodyText"]))
                #"The patient presented for therapeutic management consistent with the established plan of care. No additional examination was performed at this time."
            story.append(Spacer(1, 0.14 * inch))

        dx_text = _dx_text_from_soap(soap)
                
        # ================================
        # ASSESSMENT SECTION
        # ================================
        story.append(Paragraph("<b>ASSESSMENT</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.08 * inch))

        dx_struct = soap.get("diagnosis_struct") or {}

        assessment_para = _assessment_paragraph(dx_struct, styles)
        causation_para  = _causation_paragraph(dx_struct, styles)
        emp_current_para = _employment_current_status_paragraph(dx_struct, styles)

        if assessment_para:
            story.append(assessment_para)
            story.append(Spacer(1, 0.10 * inch))
        assessment_notes = (dx_struct.get("assessment_notes") or "").strip()
        if assessment_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(assessment_notes).replace("\n", "<br/>"), styles["BodyText"]))

        story.append(Spacer(1, 0.14 * inch))

        #if dx_text.strip():
        add_section("Diagnosis", dx_text)
        dx_block_notes = (dx_struct.get("dx_block_notes") or "").strip()
        if dx_block_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(dx_block_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))
        
        if causation_para:
            story.append(Paragraph("<b>Causation</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.04 * inch))
            story.append(causation_para)
            story.append(Spacer(1, 0.10 * inch))
        causation_general_notes = (dx_struct.get("causation_general_notes") or "").strip()
        if causation_general_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(causation_general_notes).replace("\n", "<br/>"), styles["BodyText"]))
        
        bold_body = ParagraphStyle(
            'BoldBody',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold'
        )               
                               
        prog = (dx_struct.get("prognosis") or "").strip()
        if prog and prog != "(select)":
            if prog.lower() == "guarded":
                prognosis_text = (
                    "Based on the patient’s reported symptoms, objective findings, "
                    "and functional impairments, the prognosis is currently assessed "
                    f"as {prog}. Positive outcomes are expected, contingent "
                    "upon the patient’s active engagement in care and treatment compliance."
                )
            else:
                prognosis_text = (
                    "Based on the patient’s clinical presentation and examination findings, "
                    f"the prognosis is currently assessed as {prog}. Progress will be monitored "
                    "and reassessed throughout the course of care."
                )

            add_section("Prognosis", prognosis_text)
        prognosis_notes = (dx_struct.get("prognosis_notes") or "").strip()
        if prognosis_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(prognosis_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))
                    
            
        img = _imaging_sentence(dx_struct)
        if img:
            add_section("Imaging", img)
        imaging_notes = (dx_struct.get("imaging_notes") or "").strip()
        if imaging_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(imaging_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))

        ref = _referral_sentence(dx_struct)
        if ref:
            add_section("Referrals", ref)
        referrals_notes = (dx_struct.get("referrals_notes") or "").strip()
        if referrals_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(referrals_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))
            
        if emp_current_para:
            story.append(Paragraph("<b>Current Work Status</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.04 * inch))
            story.append(emp_current_para)
            story.append(Spacer(1, 0.10 * inch))
        employment_general_notes = (dx_struct.get("employment_general_notes") or "").strip()
        if employment_general_notes:
            story.append(Spacer(1, 0.06 * inch))
            story.append(Paragraph(xml_escape(employment_general_notes).replace("\n", "<br/>"), styles["BodyText"]))

        # ✅ Plan (structured PDF rendering)
        dx_struct = soap.get("diagnosis_struct") or {}

        # Build a clean, plan-style work recommendation string
        work_recs = ""
        wp = (dx_struct.get("work_plan") or "").strip()
        if wp and wp != "(select)":
            mapping = {
                "Full Duty (No Restrictions)":
                    "Return to work full duty with no restrictions.",
                "Modified Duty (Work Restrictions)":
                    "Recommend modified duty with appropriate work restrictions.",
                "Off Work / TTD (Temporary Total Disability)":
                    "Recommend the patient remain off work at this time (TTD) pending clinical improvement and re-evaluation.",
                "Off Work (Work Status Note Only)":
                    "Work status note provided; patient advised to remain off work at this time as clinically indicated.",
                "Work Restrictions Pending Re-evaluation":
                    "Work restrictions are pending re-evaluation at the next visit based on treatment response.",
                "Disability Note Requested":
                    "Disability documentation requested; provide as clinically appropriate based on examination findings.",
                "Return to Work Note Requested":
                    "Return-to-work documentation requested; provide based on current work status and clinical findings.",
                "FMLA / Leave Documentation Requested":
                    "FMLA/leave documentation requested; provide as clinically appropriate.",
                "Referral for Work Capacity Evaluation":
                    "Recommend referral for a work capacity evaluation to better define functional limitations and work restrictions.",
            }

            work_recs = mapping.get(wp, wp)

        plan_flow = build_plan_flowables(plan_struct, styles, work_recs=work_recs)
        if plan_flow:
            story.extend(plan_flow)
            story.append(Spacer(1, 0.14 * inch))
        else:
            add_section("Plan", "")          
                               
        provider = ((payload.get("patient") or {}).get("provider") or "").strip()

        sig_block = [
            Spacer(1, 0.18 * inch),
            Paragraph("Provider Signature: ________________________________", styles["Normal"]),
        ]

        if provider:
            indent = "&nbsp;" * 34
            sig_block.append(Paragraph(indent + provider, styles["Normal"]))

        story.append(KeepTogether(sig_block))

        if idx < len(payloads) - 1:
            story.append(PageBreak())

    doc.build(story, canvasmaker=HeaderExamNumberedCanvas)








