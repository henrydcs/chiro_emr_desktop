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
    PROVIDER_NAME,
    REGION_LABELS,
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
    from reportlab.lib.enums import TA_LEFT
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
# Auto imaging recommendation letter (exam data only; no extra UI)
# =======================================================
def _ordered_imaging_groups(dx_struct: dict) -> list[tuple[str, list[str]]]:
    """Return [(modality, [body parts...]), ...] preserving first-seen modality order."""
    dx_struct = dx_struct or {}
    recs = dx_struct.get("imaging_recs") or []
    if not isinstance(recs, list):
        return []
    order: list[str] = []
    groups: dict[str, list[str]] = {}
    for r in recs:
        if not isinstance(r, dict):
            continue
        mod = (r.get("modality") or "").strip()
        bp = (r.get("body_part") or "").strip()
        if not mod or not bp or mod == "(select)" or bp == "(select)":
            continue
        if mod not in groups:
            groups[mod] = []
            order.append(mod)
        if bp not in groups[mod]:
            groups[mod].append(bp)
    return [(m, groups[m]) for m in order]


def imaging_recommendation_letter_should_generate(payload: dict) -> bool:
    soap = (payload or {}).get("soap") or {}
    dx_struct = soap.get("diagnosis_struct") or {}
    return bool(_ordered_imaging_groups(dx_struct if isinstance(dx_struct, dict) else {}))


def _article_for_modality(mod: str) -> str:
    m = (mod or "").strip().lower()
    if m in ("x-ray", "mri", "ultrasound"):
        return "an"
    return "a"


def _injury_event_phrase(hoi_struct: dict) -> str:
    t = ((hoi_struct or {}).get("type") or {}).get("injury_type") or ""
    t = (t or "").strip()
    if not t or t == "(none)":
        return "the reported injury event"
    return {
        "Auto Accident": "a motor vehicle collision",
        "Slip and Fall": "a slip-and-fall incident",
        "Dog Bite": "a dog bite",
        "Work Injury": "a work-related injury",
        "Other": "the reported injury event",
    }.get(t, t.lower())


def _doi_for_imaging_letter(patient: dict, hoi_struct: dict) -> str:
    hdoi = normalize_mmddyyyy(((hoi_struct or {}).get("doi") or {}).get("date") or "")
    pdoi = normalize_mmddyyyy((patient or {}).get("doi") or "")
    return hdoi or pdoi


# Match diagnosis rows to imaging body parts (labels + ICD prefixes for spine).
# Used only for the imaging recommendation letter "Diagnostic Codes" line.
_IMAGING_BODY_PART_MATCH_HINTS: dict[str, tuple[str, ...]] = {
    "Cervical Spine": (
        "cervical",
        "neck",
        "neck ",
        " neck",
        "whiplash",
        "cervicogenic",
        "radiculopathy, cervical",
        "(c/s)",
        "c/s)",
    ),
    "Thoracic Spine": (
        "thoracic",
        "mid-back",
        "mid back",
        "t-spine",
        "t spine",
        "radiculopathy, thoracic",
    ),
    "Lumbar Spine": (
        "lumbar",
        "low back",
        "lumb",
        "sacroiliac",
        "si joint",
        "radiculopathy, lumbar",
        "sacral",
    ),
    "Right Shoulder": ("right shoulder",),
    "Left Shoulder": ("left shoulder",),
    "B/L Shoulders": ("right shoulder", "left shoulder", "b/l shoulder", "bilateral shoulder", "b/l shoulders"),
    "Right Elbow": ("right elbow",),
    "Left Elbow": ("left elbow",),
    "B/L Elbows": ("right elbow", "left elbow", "b/l elbow", "bilateral elbow"),
    "Right Wrist": ("right wrist",),
    "Left Wrist": ("left wrist",),
    "B/L Wrists": ("right wrist", "left wrist", "b/l wrist", "bilateral wrist"),
    "Right Hip": ("right hip",),
    "Left Hip": ("left hip",),
    "B/L Hips": ("right hip", "left hip", "b/l hip", "bilateral hip"),
    "Right Knee": ("right knee",),
    "Left Knee": ("left knee",),
    "B/L Knees": ("right knee", "left knee", "b/l knee", "bilateral knee"),
    "Right Ankle": ("right ankle",),
    "Left Ankle": ("left ankle",),
    "B/L Ankles": ("right ankle", "left ankle", "b/l ankle", "bilateral ankle"),
}

# Secondary match: ICD-10 text starts with these (aligned with common chiropractic dx list).
_SPINE_ICD_PREFIXES: dict[str, tuple[str, ...]] = {
    "Cervical Spine": (
        "S13", "S14", "S16", "M50", "M54.12", "M54.2", "M48.02", "M47.812",
    ),
    "Thoracic Spine": (
        "S22", "S23", "S24", "M51.24", "M54.14", "M54.6", "M47.814",
    ),
    "Lumbar Spine": (
        "S32", "S33", "M51.26", "M54.16", "M54.50", "M53.3", "M51.36", "M48.061", "M47.816",
    ),
}

_DX_LIST_ICD_CACHE: dict[str, str] | None = None


def _dx_list_label_to_icd_map() -> dict[str, str]:
    """Exact label -> ICD from diagnosis_page.DX_LIST (separator / blank-code rows skipped)."""
    global _DX_LIST_ICD_CACHE
    if _DX_LIST_ICD_CACHE is not None:
        return _DX_LIST_ICD_CACHE
    out: dict[str, str] = {}
    try:
        from diagnosis_page import DX_LIST
    except ImportError:
        _DX_LIST_ICD_CACHE = {}
        return _DX_LIST_ICD_CACHE
    for lbl, code in DX_LIST:
        lbl = (lbl or "").strip()
        code = (code or "").strip()
        if not lbl or not code:
            continue
        if lbl.startswith("-") or code.startswith("-"):
            continue
        out[lbl] = code
    _DX_LIST_ICD_CACHE = out
    return out


def _resolve_icd_from_dx_block(block: dict) -> str:
    """
    ICD for PDF/preview/imaging: use saved icd10 when set; otherwise parse dx_display
    ('Label — ICD'); otherwise exact-match edit_text / dx_label against DX_LIST.
    Does not invent codes outside DX_LIST / stored fields.
    """
    if not isinstance(block, dict):
        return ""
    code = (block.get("icd10") or "").strip()
    if code:
        return code
    disp = (block.get("dx_display") or "").strip()
    if " — " in disp:
        right = disp.split(" — ", 1)[1].strip()
        if right and not right.startswith("-"):
            return right
    lut = _dx_list_label_to_icd_map()
    for key in (
        (block.get("edit_text") or "").strip(),
        (block.get("dx_label") or "").strip(),
    ):
        if key and key in lut:
            return lut[key]
    return ""


def _dx_block_text_for_imaging_match(block: dict) -> str:
    parts = [
        (block.get("edit_text") or "").strip(),
        (block.get("dx_label") or "").strip(),
    ]
    return " ".join(parts).lower()


def _icd_matches_prefixes(icd_raw: str, prefixes: tuple[str, ...]) -> bool:
    icd = (icd_raw or "").strip().upper().replace(" ", "")
    if not icd:
        return False
    return any(icd.startswith(p.upper().replace(" ", "")) for p in prefixes)


def _diagnosis_block_matches_imaging_body_part(block: dict, body_part: str) -> bool:
    """True if this dx row is clinically tied to the requested imaging region."""
    hints = _IMAGING_BODY_PART_MATCH_HINTS.get(body_part)
    if hints:
        text = _dx_block_text_for_imaging_match(block)
        if any(h.lower() in text for h in hints):
            return True
    spine_prefs = _SPINE_ICD_PREFIXES.get(body_part)
    if spine_prefs:
        icd = _resolve_icd_from_dx_block(block)
        if _icd_matches_prefixes(icd, spine_prefs):
            return True
    return False


def _ordered_imaging_body_parts_unique(dx_struct: dict) -> list[str]:
    """Order-preserving unique body_part values from imaging_recs."""
    out: list[str] = []
    seen: set[str] = set()
    for r in dx_struct.get("imaging_recs") or []:
        if not isinstance(r, dict):
            continue
        bp = (r.get("body_part") or "").strip()
        if not bp or bp == "(select)":
            continue
        if bp not in seen:
            seen.add(bp)
            out.append(bp)
    return out


def imaging_modalities_in_payload(payload: dict) -> list[str]:
    """First-seen order of distinct modalities in imaging_recs (display casing preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    soap = (payload or {}).get("soap") or {}
    dx = soap.get("diagnosis_struct") or {}
    for r in (dx.get("imaging_recs") or []) if isinstance(dx, dict) else []:
        if not isinstance(r, dict):
            continue
        m = (r.get("modality") or "").strip()
        if not m or m == "(select)":
            continue
        k = m.lower()
        if k not in seen:
            seen.add(k)
            out.append(m)
    return out


def _payload_with_single_imaging_modality(payload: dict, modality: str) -> dict:
    """Shallow copy of payload with imaging_recs limited to one modality (for per-modality letters)."""
    modality_key = (modality or "").strip().lower()
    p = dict(payload or {})
    soap = dict(p.get("soap") or {})
    dx = dict(soap.get("diagnosis_struct") or {})
    recs = dx.get("imaging_recs") or []
    filtered = [
        dict(r)
        for r in (recs if isinstance(recs, list) else [])
        if isinstance(r, dict) and (r.get("modality") or "").strip().lower() == modality_key
    ]
    dx["imaging_recs"] = filtered
    soap["diagnosis_struct"] = dx
    p["soap"] = soap
    return p


# --- Imaging letter diagnostic code selection ---
# ICDs come from diagnosis_struct.blocks (chart order). Empty icd10 is resolved from dx_display
# or DX_LIST via _resolve_icd_from_dx_block; selection is region-based and user-pick-driven.


def _icd_codes_for_imaging_body_parts_only(dx_struct: dict) -> list[str]:
    """
    ICD-10 codes only (no labels), in diagnosis block order, deduped,
    limited to rows that match at least one requested imaging body region.
    """
    requested = _ordered_imaging_body_parts_unique(dx_struct)
    return _icd_codes_for_modality_and_regions(dx_struct, None, requested)


def _icd_codes_for_modality_and_regions(
    dx_struct: dict, modality: str | None, body_parts: list[str]
) -> list[str]:
    """
    modality: None or lowercase. Matching is strictly region-based against existing diagnosis rows.
    body_parts: regions requested for this letter (this imaging type only).
    """
    if not isinstance(dx_struct, dict):
        return []
    if not body_parts:
        return []

    blocks = dx_struct.get("blocks") or []
    if not isinstance(blocks, list):
        return []

    out: list[str] = []
    seen_icd: set[str] = set()

    for b in blocks:
        if not isinstance(b, dict):
            continue
        icd = _resolve_icd_from_dx_block(b)
        if not icd or icd in seen_icd:
            continue
        for bp in body_parts:
            if not _diagnosis_block_matches_imaging_body_part(b, bp):
                continue
            out.append(icd)
            seen_icd.add(icd)
            break

    return out


def _norm_imaging_body_part_key(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _icd_from_body_part_selection_map(sel: dict[str, str] | None, body_part: str) -> str:
    """Lookup stored ICD for this imaging body part; keys matched with normalized spacing/case."""
    if not sel or not isinstance(sel, dict):
        return ""
    bp = (body_part or "").strip()
    if bp in sel and isinstance(sel[bp], str):
        return (sel[bp] or "").strip()
    nk = _norm_imaging_body_part_key(bp)
    for k, v in sel.items():
        if not isinstance(k, str):
            continue
        if _norm_imaging_body_part_key(k) != nk:
            continue
        if isinstance(v, str):
            return (v or "").strip()
    return ""


def _icd_first_match_for_single_body_part(dx_struct: dict, body_part: str) -> str:
    """First diagnosis row ICD that matches exactly one imaging body region (no cross-part dedupe)."""
    if not isinstance(dx_struct, dict):
        return ""
    blocks = dx_struct.get("blocks") or []
    if not isinstance(blocks, list):
        return ""
    for b in blocks:
        if not isinstance(b, dict):
            continue
        icd = _resolve_icd_from_dx_block(b)
        if not icd:
            continue
        if _diagnosis_block_matches_imaging_body_part(b, body_part):
            return icd
    return ""


def imaging_dx_choices_by_body_part(payload: dict, modality: str) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    """
    Returns ordered body parts for a single modality and available diagnosis choices per body part.
    Each choice is sourced from existing diagnosis_struct.blocks only:
      {"icd": "...", "label": "...", "display": "Label - ICD"}.
    """
    sub = _payload_with_single_imaging_modality(payload or {}, modality or "")
    full_dx = ((payload or {}).get("soap") or {}).get("diagnosis_struct") or {}
    sub_dx = ((sub or {}).get("soap") or {}).get("diagnosis_struct") or {}
    if not isinstance(full_dx, dict) or not isinstance(sub_dx, dict):
        return [], {}

    body_parts = _ordered_imaging_body_parts_unique(sub_dx)
    if not body_parts:
        return [], {}

    blocks = full_dx.get("blocks") or []
    if not isinstance(blocks, list):
        return body_parts, {bp: [] for bp in body_parts}

    out: dict[str, list[dict[str, str]]] = {}

    for bp in body_parts:
        seen_icd: set[str] = set()
        choices: list[dict[str, str]] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if not _diagnosis_block_matches_imaging_body_part(b, bp):
                continue
            icd = _resolve_icd_from_dx_block(b)
            if not icd or icd in seen_icd:
                continue
            label = (b.get("dx_label") or "").strip() or (b.get("edit_text") or "").strip() or icd
            display = f"{label} - {icd}" if label and label != icd else icd
            choices.append({"icd": icd, "label": label, "display": display})
            seen_icd.add(icd)
        out[bp] = choices
    return body_parts, out


def imaging_dx_all_ui_choices(payload: dict) -> list[dict[str, str]]:
    """
    Every diagnosis row from the chart (soap.diagnosis_struct.blocks), in UI order — one entry
    per block. Rows that share the same ICD (e.g. cervical vs lumbar disc) are all included;
    duplicate display strings get a numeric suffix so the combobox can distinguish them.
    """
    soap = (payload or {}).get("soap") or {}
    dx_struct = soap.get("diagnosis_struct") or {}
    if not isinstance(dx_struct, dict):
        return []
    blocks = dx_struct.get("blocks") or []
    if not isinstance(blocks, list):
        return []
    out: list[dict[str, str]] = []
    display_use_count: dict[str, int] = {}
    for b in blocks:
        if not isinstance(b, dict):
            continue
        icd = _resolve_icd_from_dx_block(b)
        if not icd:
            continue
        label = (b.get("dx_label") or "").strip() or (b.get("edit_text") or "").strip() or icd
        base_display = f"{label} - {icd}" if label and label != icd else icd
        n = display_use_count.get(base_display, 0)
        display_use_count[base_display] = n + 1
        display = base_display if n == 0 else f"{base_display} ({n + 1})"
        out.append({"icd": icd, "label": label, "display": display})
    return out


def imaging_recommendation_letter_title_and_body(payload: dict) -> tuple[str, str] | None:
    """
    Build title + a single general paragraph from existing exam fields only.
    Returns None if there are no structured imaging recommendations.
    """
    payload = payload or {}
    patient = payload.get("patient") or {}
    soap = payload.get("soap") or {}
    hoi_struct = soap.get("hoi_struct") or {}
    dx_struct = soap.get("diagnosis_struct") or {}
    if not isinstance(dx_struct, dict):
        return None

    groups = _ordered_imaging_groups(dx_struct)
    if not groups:
        return None

    clauses: list[str] = []
    for mod, body_parts in groups:
        art = _article_for_modality(mod)
        if len(body_parts) == 1:
            clauses.append(f"{art} {mod} of the {body_parts[0]}")
        else:
            clauses.append(f"{art} {mod} of the {_join_with_and(body_parts)}")
    studies = _join_with_and(clauses)
    if not studies:
        return None

    inj = _injury_event_phrase(hoi_struct if isinstance(hoi_struct, dict) else {})
    doi = _doi_for_imaging_letter(patient if isinstance(patient, dict) else {}, hoi_struct if isinstance(hoi_struct, dict) else {})
    doi_part = f" The documented date of injury is {doi}." if doi else ""

    body = (
        f"The patient remains under clinical care following {inj}.{doi_part} "
        f"We are submitting this notice to recommend {studies} for further evaluation and to assist with ongoing therapeutic management."
    )

    if len(groups) == 1:
        mod0 = groups[0][0]
        ml = (mod0 or "").strip().lower()
        if ml == "x-ray":
            title = "X-Ray Recommendation Letter"
        elif ml == "mri":
            title = "MRI Recommendation Letter"
        elif ml == "ct":
            title = "CT Recommendation Letter"
        elif ml == "ultrasound":
            title = "Ultrasound Recommendation Letter"
        else:
            title = f"{mod0} Recommendation Letter"
    else:
        title = "Imaging Recommendation Letter"

    return title, body


def imaging_recommendation_letter_editable_text(
    payload: dict,
    modality: str,
    selected_icd_by_body_part: dict[str, str] | None = None,
) -> str:
    """
    Draft editable letter text from salutation through signature (no title/header/footer).
    """
    sub = _payload_with_single_imaging_modality(payload, modality)
    tb = imaging_recommendation_letter_title_and_body(sub)
    if not tb:
        return ""
    _title, body = tb

    patient = (payload or {}).get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}

    full_dx = (payload.get("soap") or {}).get("diagnosis_struct") or {}
    sub_dx = (sub.get("soap") or {}).get("diagnosis_struct") or {}
    body_parts = (
        _ordered_imaging_body_parts_unique(sub_dx)
        if isinstance(sub_dx, dict)
        else []
    )
    icd_only: list[str] = []
    if isinstance(full_dx, dict) and body_parts:
        for bp in body_parts:
            picked = ""
            if selected_icd_by_body_part is not None:
                picked = _icd_from_body_part_selection_map(selected_icd_by_body_part, bp)
            if not picked:
                picked = _icd_first_match_for_single_body_part(full_dx, bp)
            icd_only.append(picked if picked else "—")

    lines: list[str] = []
    lines.append("To Whom It May Concern,")
    lines.append("")
    lines.append(body.strip())
    if icd_only:
        lines.append("")
        lines.append("Diagnostic Codes:")
        lines.extend(icd_only)
    lines.append("")
    lines.append("Sincerely,")
    lines.append("")
    prov = ((patient.get("provider") or "").strip() or (PROVIDER_NAME or "").strip())
    if prov:
        lines.append(prov)
    return "\n".join(lines).strip()


def _modalities_checked_parts_with_times(parts_map: dict) -> list[tuple[str, str]]:
    """From a modality's region dict, return [(region_label, minutes_str), ...] for checked regions."""

    def _is_checked_value(v) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            t = v.strip().lower()
            if t in ("1", "true", "yes", "y", "on", "checked"):
                return True
            if t in ("0", "false", "no", "n", "off", "unchecked", ""):
                return False
        return bool(v)

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    if not isinstance(parts_map, dict):
        return out

    for bp, pair in parts_map.items():
        bps = (bp or "").strip()
        if not bps or bps in seen:
            continue
        checked = False
        minutes = ""
        if isinstance(pair, (list, tuple)) and pair:
            checked = _is_checked_value(pair[0])
            if len(pair) > 1 and pair[1] is not None:
                minutes = str(pair[1]).strip()
            if not checked and minutes:
                checked = True
        elif isinstance(pair, dict):
            checked = _is_checked_value(pair.get("checked"))
            minutes = (str(pair.get("minutes") or pair.get("time") or "")).strip()
            if not checked and minutes:
                checked = True
        elif isinstance(pair, bool):
            checked = pair
        elif isinstance(pair, str):
            checked = _is_checked_value(pair)
        if checked:
            seen.add(bps)
            out.append((bps, minutes))
    return out


def _staff_modalities_letter_groups_from_payload(payload: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Staff physiotherapy modalities letter lines from Plan > Treatment (Care Types), not billing.
    plan.services.staff_modalities_letter_data: {care_type: {region: [checked, minutes]}}
    plan.services.staff_modalities_letter_exclude: {care_type: true} -> omit from letter
    """
    soap = (payload or {}).get("soap") or {}
    plan = soap.get("plan") or soap.get("plan_struct") or {}
    services = (plan.get("services") or {}) if isinstance(plan, dict) else {}
    if not isinstance(services, dict):
        return []

    raw_data = services.get("staff_modalities_letter_data") or {}
    if not isinstance(raw_data, dict):
        raw_data = {}

    exclude_map = services.get("staff_modalities_letter_exclude") or {}
    if not isinstance(exclude_map, dict):
        exclude_map = {}

    groups: list[tuple[str, list[tuple[str, str]]]] = []
    for modality_key, parts_map in raw_data.items():
        label = (modality_key or "").strip()
        if not label:
            continue
        ex = exclude_map.get(label)
        if ex is True or (isinstance(ex, str) and ex.strip().lower() in ("1", "true", "yes")):
            continue
        checked = _modalities_checked_parts_with_times(parts_map if isinstance(parts_map, dict) else {})
        if checked:
            groups.append((label, checked))
    return groups


def _format_staff_letter_body_part(part: str, minutes: str) -> str:
    p = (part or "").strip()
    m = (minutes or "").strip()
    if not m:
        return p
    low = m.lower()
    if "min" in low:
        return f"{p} ({m})"
    return f"{p} ({m} minutes)"


def modalities_recommendation_letter_should_generate(payload: dict) -> bool:
    return bool(_staff_modalities_letter_groups_from_payload(payload))


def modalities_recommendation_letter_editable_text(payload: dict) -> str:
    groups = _staff_modalities_letter_groups_from_payload(payload)
    patient = (payload or {}).get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    lines: list[str] = []
    lines.append("Therapy Staff,")
    lines.append("")
    lines.append("The patient is prescribed the following physiotherapy regimen. Please carry out this treatment plan exactly as directed.")
    lines.append("")
    for mod, part_rows in groups:
        formatted = [_format_staff_letter_body_part(p, t) for p, t in part_rows]
        lines.append(f"• {mod}: {_join_with_and(formatted)}")
    lines.append("")
    lines.append("Thank you,")
    lines.append("")
    lines.append("")
    lines.append("")
    prov = ((patient.get("provider") or "").strip() or (PROVIDER_NAME or "").strip())
    if prov:
        lines.append(prov)
    return "\n".join(lines).strip()


def build_modalities_recommendation_letter_pdf(
    path: str,
    payload: dict,
    editable_letter_text: str | None = None,
) -> bool:
    """One-page modalities instruction letter (single combined letter for all selected therapies)."""
    if not REPORTLAB_OK:
        return False
    if not modalities_recommendation_letter_should_generate(payload):
        return False

    patient = (payload or {}).get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    exam_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
    exam_name = "Current Physiotherapy Modalities"
    title = exam_name
    last = (patient.get("last_name") or "").strip()
    first = (patient.get("first_name") or "").strip()
    display = (patient.get("display_name") or "").strip() or f"{last}, {first}".strip(", ")
    doi = normalize_mmddyyyy(patient.get("doi", ""))
    dob = normalize_mmddyyyy(patient.get("dob", ""))
    re_line = f"RE: {last}, {first}".strip()
    if doi:
        re_line += f" | DOI: {doi}"
    if dob:
        re_line += f" | DOB: {dob}"

    patient_header = {
        "display_name": display,
        "first_name": first,
        "last_name": last,
        "dob": dob,
        "doi": patient.get("doi") or "",
        "provider": (patient.get("provider") or "").strip(),
        "exam_date": exam_date,
    }

    try:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="ModalitiesLetterTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            spaceAfter=10,
            alignment=1,
        )
        if "ModalitiesLetterTitle" not in styles.byName:
            styles.add(title_style)
        body_style = ParagraphStyle(
            name="ModalitiesLetterBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=0,
        )
        if "ModalitiesLetterBody" not in styles.byName:
            styles.add(body_style)

        letter_text = (editable_letter_text or "").strip()
        if not letter_text:
            letter_text = modalities_recommendation_letter_editable_text(payload)

        story = []
        story.append(ExamStart(exam_name, patient_header, exam_date))
        story.append(Spacer(1, 0.22 * inch))
        story.append(Paragraph(xml_escape(title.strip()), styles["ModalitiesLetterTitle"]))
        story.append(Spacer(1, 0.12 * inch))
        re_safe = xml_escape(re_line.strip()).replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{re_safe}</b>", styles["ModalitiesLetterBody"]))
        story.append(Spacer(1, 0.14 * inch))

        lines = letter_text.replace("\r\n", "\n").split("\n")
        for line in lines:
            if not line.strip():
                story.append(Spacer(1, 0.12 * inch))
                continue
            story.append(Paragraph(xml_escape(line), styles["ModalitiesLetterBody"]))

        doc = SimpleDocTemplate(
            path,
            pagesize=LETTER,
            rightMargin=72,
            leftMargin=72,
            topMargin=170,
            bottomMargin=72,
        )
        doc.build(story, canvasmaker=HeaderExamNumberedCanvas)
        return True
    except Exception:
        return False


# =======================================================
# Medical Referral Recommendation Letters
# (mirrors the imaging-letter system but works off
#  diagnosis_struct.referrals[*].provider_type)
# =======================================================
def _referral_provider_types(dx_struct: dict) -> list[str]:
    """First-seen order of distinct, valid referral provider types.
    Filters out empty strings, '(select)', and 'None at this time'."""
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(dx_struct, dict):
        return out
    for r in dx_struct.get("referrals") or []:
        if not isinstance(r, dict):
            continue
        p = (r.get("provider_type") or "").strip()
        if not p:
            continue
        low = p.lower()
        if low in ("(select)", "none at this time"):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(p)
    return out


def referral_letter_should_generate(payload: dict) -> bool:
    """True iff there is at least one structured referral (excluding placeholders)."""
    soap = (payload or {}).get("soap") or {}
    dx = soap.get("diagnosis_struct") or {}
    return bool(_referral_provider_types(dx if isinstance(dx, dict) else {}))


def referral_provider_types_in_payload(payload: dict) -> list[str]:
    """Public accessor: distinct provider types in their original UI order."""
    soap = (payload or {}).get("soap") or {}
    dx = soap.get("diagnosis_struct") or {}
    return _referral_provider_types(dx if isinstance(dx, dict) else {})


def _referral_provider_phrase(provider_type: str) -> str:
    """Human-friendly noun phrase for the body paragraph.

    'Pain Management'      -> 'a Pain Management specialist'
    'Orthopedist'          -> 'an Orthopedist'
    'Primary Care'         -> 'a Primary Care provider'
    'Physical Therapy'     -> 'a Physical Therapist'
    'Chiropractic Specialty' -> 'a Chiropractic Specialist'
    'Radiology'            -> 'a Radiologist'
    'Psychology'           -> 'a Psychologist'
    'Neurologist'          -> 'a Neurologist'
    """
    p = (provider_type or "").strip()
    if not p:
        return "an appropriate specialist"
    pl = p.lower()
    overrides = {
        "pain management":         "a Pain Management specialist",
        "primary care":            "a Primary Care provider",
        "physical therapy":        "a Physical Therapist",
        "chiropractic specialty":  "a Chiropractic Specialist",
        "radiology":               "a Radiologist",
        "psychology":              "a Psychologist",
    }
    if pl in overrides:
        return overrides[pl]
    art = "an" if p[:1].lower() in ("a", "e", "i", "o", "u") else "a"
    return f"{art} {p}"


def _referral_letter_title(provider_type: str) -> str:
    p = (provider_type or "").strip()
    if not p:
        return "Medical Referral Letter"
    return f"{p} Referral Letter"


def _referral_letter_body(payload: dict, provider_type: str) -> str:
    """Single body paragraph for a medical referral letter (no salutation/signature)."""
    payload = payload or {}
    patient = payload.get("patient") or {}
    soap = payload.get("soap") or {}
    hoi_struct = soap.get("hoi_struct") or {}

    inj = _injury_event_phrase(hoi_struct if isinstance(hoi_struct, dict) else {})
    doi = _doi_for_imaging_letter(
        patient if isinstance(patient, dict) else {},
        hoi_struct if isinstance(hoi_struct, dict) else {},
    )
    doi_part = f" The documented date of injury is {doi}." if doi else ""

    phrase = _referral_provider_phrase(provider_type)

    return (
        f"The above-named patient remains under our chiropractic care following {inj}.{doi_part} "
        f"Despite a course of conservative therapy to date, the patient continues to "
        f"experience symptoms warranting specialist evaluation. We are therefore "
        f"referring this patient to {phrase} for further assessment and management. "
        f"We respectfully request your consultation and any recommendations you may "
        f"have to assist with ongoing therapeutic management."
    )


# Bullet styling shared by editor preview and PDF rendering.
# A leading TAB in the editor text marks an indented bullet line; the PDF
# builder strips the TAB and renders that line with leftIndent.
_REFERRAL_BULLET_PREFIX = "\t\u2022 "  # tab + • + space
_REFERRAL_HEADER_LABEL = "Specialist Referral:"


def referral_letter_editable_text(payload: dict, provider_type: str) -> str:
    """Editable letter body for a single referral provider type, salutation
    through signature. The 'Specialist Referral:' block lists ONLY the
    provider this letter is addressed to (one bullet per letter)."""
    if not referral_letter_should_generate(payload):
        return ""
    body = _referral_letter_body(payload, provider_type)

    prov_label = (provider_type or "").strip()
    bullet_line = (
        f"{_REFERRAL_BULLET_PREFIX}{prov_label}" if prov_label else ""
    )

    patient = (payload or {}).get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    prov = ((patient.get("provider") or "").strip() or (PROVIDER_NAME or "").strip())

    lines: list[str] = []
    lines.append("To Whom It May Concern,")
    lines.append("")
    lines.append(body.strip())
    if bullet_line:
        lines.append("")
        lines.append(_REFERRAL_HEADER_LABEL)
        lines.append("")  # extra space between header and the bullet
        lines.append(bullet_line)
    lines.append("")
    lines.append("Sincerely,")
    lines.append("")
    lines.append("")  # two extra blank lines before the signature
    lines.append("")
    if prov:
        lines.append(prov)
    return "\n".join(lines).rstrip()


def build_referral_letter_pdf(
    path: str,
    payload: dict,
    provider_type: str,
    editable_letter_text: str | None = None,
) -> bool:
    """One-page medical referral letter for a single provider type
    (Pain Management, Orthopedist, etc.). Mirrors the imaging-letter PDF."""
    if not REPORTLAB_OK:
        return False
    if not referral_letter_should_generate(payload):
        return False

    title = _referral_letter_title(provider_type)
    patient = payload.get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    exam_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
    exam_name = title.strip()

    last = (patient.get("last_name") or "").strip()
    first = (patient.get("first_name") or "").strip()
    display = (patient.get("display_name") or "").strip() or f"{last}, {first}".strip(", ")
    doi = _doi_for_imaging_letter(patient, (payload.get("soap") or {}).get("hoi_struct") or {})
    dob = normalize_mmddyyyy(patient.get("dob", ""))

    re_line = f"RE: {last}, {first}".strip()
    if doi:
        re_line += f" | DOI: {doi}"
    if dob:
        re_line += f" | DOB: {dob}"

    patient_header = {
        "display_name": display,
        "first_name": first,
        "last_name": last,
        "dob": dob,
        "doi": patient.get("doi") or "",
        "provider": (patient.get("provider") or "").strip(),
        "exam_date": exam_date,
    }

    try:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="ReferralLetterTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            spaceAfter=10,
            alignment=1,
        )
        if "ReferralLetterTitle" not in styles.byName:
            styles.add(title_style)

        letter_body = ParagraphStyle(
            name="ReferralLetterBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=0,
        )
        if "ReferralLetterBody" not in styles.byName:
            styles.add(letter_body)

        bullet_body = ParagraphStyle(
            name="ReferralLetterBullet",
            parent=letter_body,
            leftIndent=28,
            firstLineIndent=0,
            spaceAfter=0,
        )
        if "ReferralLetterBullet" not in styles.byName:
            styles.add(bullet_body)

        story = []
        story.append(ExamStart(exam_name, patient_header, exam_date))
        story.append(Spacer(1, 0.22 * inch))
        story.append(Paragraph(xml_escape(title.strip()), styles["ReferralLetterTitle"]))
        story.append(Spacer(1, 0.12 * inch))
        re_safe = xml_escape(re_line.strip()).replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{re_safe}</b>", styles["ReferralLetterBody"]))

        letter_text = (editable_letter_text or "").strip()
        if not letter_text:
            letter_text = referral_letter_editable_text(payload, provider_type)

        lines = letter_text.replace("\r\n", "\n").split("\n")
        if lines:
            story.append(Spacer(1, 0.14 * inch))
            for line in lines:
                if not line.strip():
                    story.append(Spacer(1, 0.12 * inch))
                    continue
                stripped = line.strip()
                low = stripped.lower()
                # Bold section headers (current + legacy "Diagnostic Codes:"
                # / plural "Specialist Referrals:" from prior saved overrides).
                if low in (
                    _REFERRAL_HEADER_LABEL.lower(),
                    "specialist referrals:",
                    "diagnostic codes:",
                ):
                    story.append(Paragraph(
                        f"<b>{xml_escape(stripped)}</b>",
                        styles["ReferralLetterBody"],
                    ))
                    continue
                # Lines the editor (or user) marked as indented bullets get the
                # bullet paragraph style so the indent is preserved in the PDF.
                if line.startswith("\t") or line.startswith("    "):
                    story.append(Paragraph(
                        xml_escape(stripped),
                        styles["ReferralLetterBullet"],
                    ))
                else:
                    story.append(Paragraph(
                        xml_escape(line),
                        styles["ReferralLetterBody"],
                    ))

        story.append(Spacer(1, 0.18 * inch))

        doc = SimpleDocTemplate(
            path,
            pagesize=LETTER,
            rightMargin=72,
            leftMargin=72,
            topMargin=170,
            bottomMargin=72,
        )
        doc.build(story, canvasmaker=HeaderExamNumberedCanvas)
        return True
    except Exception:
        return False


def build_imaging_recommendation_letter_pdf(
    path: str,
    payload: dict,
    modality: str,
    selected_icd_by_body_part: dict[str, str] | None = None,
    editable_letter_text: str | None = None,
) -> bool:
    """
    One-page letter for a single imaging modality (MRI, X-ray, etc.).
    `payload` is the full exam payload; pass modality matching imaging_recs rows.
    Diagnostic codes: one line per requested body part (stored picks, then first chart match per region).
    """
    if not REPORTLAB_OK:
        return False
    sub = _payload_with_single_imaging_modality(payload, modality)
    tb = imaging_recommendation_letter_title_and_body(sub)
    if not tb:
        return False
    title, body = tb

    patient = payload.get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    exam_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
    exam_name = title.strip()

    last = (patient.get("last_name") or "").strip()
    first = (patient.get("first_name") or "").strip()
    display = (patient.get("display_name") or "").strip() or f"{last}, {first}".strip(", ")
    doi = _doi_for_imaging_letter(patient, (payload.get("soap") or {}).get("hoi_struct") or {})
    dob = normalize_mmddyyyy(patient.get("dob", ""))

    re_line = f"RE: {last}, {first}".strip()
    if doi:
        re_line += f" | DOI: {doi}"
    if dob:
        re_line += f" | DOB: {dob}"

    patient_header = {
        "display_name": display,
        "first_name": first,
        "last_name": last,
        "dob": dob,
        "doi": patient.get("doi") or "",
        "provider": (patient.get("provider") or "").strip(),
        "exam_date": exam_date,
    }

    try:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="ImagingLetterTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            spaceAfter=10,
            alignment=1,
        )
        if "ImagingLetterTitle" not in styles.byName:
            styles.add(title_style)

        letter_body = ParagraphStyle(
            name="ImagingLetterBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=0,
        )
        if "ImagingLetterBody" not in styles.byName:
            styles.add(letter_body)

        story = []
        story.append(ExamStart(exam_name, patient_header, exam_date))
        story.append(Spacer(1, 0.22 * inch))
        story.append(Paragraph(xml_escape(title.strip()), styles["ImagingLetterTitle"]))
        story.append(Spacer(1, 0.12 * inch))
        re_safe = xml_escape(re_line.strip()).replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{re_safe}</b>", styles["ImagingLetterBody"]))
        letter_text = (editable_letter_text or "").strip()
        if not letter_text:
            letter_text = imaging_recommendation_letter_editable_text(
                payload,
                modality,
                selected_icd_by_body_part,
            )
        lines = letter_text.replace("\r\n", "\n").split("\n")
        if lines:
            story.append(Spacer(1, 0.14 * inch))
            for line in lines:
                if not line.strip():
                    # Preserve user-inserted blank lines from popup editor.
                    story.append(Spacer(1, 0.12 * inch))
                    continue
                safe_line = xml_escape(line)
                if line.strip().lower() == "diagnostic codes:":
                    story.append(Paragraph(f"<b>{safe_line}</b>", styles["ImagingLetterBody"]))
                else:
                    story.append(Paragraph(safe_line, styles["ImagingLetterBody"]))

        story.append(Spacer(1, 0.18 * inch))

        doc = SimpleDocTemplate(
            path,
            pagesize=LETTER,
            rightMargin=72,
            leftMargin=72,
            topMargin=170,
            bottomMargin=72,
        )
        doc.build(story, canvasmaker=HeaderExamNumberedCanvas)
        return True
    except Exception:
        return False


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
    Returns [(chunk, tag), ...] with:
      - tag "H_BOLD" for headings
      - tag "PREVIEW_MONO" for aligned table-like body content
    """
    runs: list[tuple[str, str | None]] = []
    objectives_struct = objectives_struct or {}
    global_struct = objectives_struct.get("global") or {}
    if not isinstance(global_struct, dict):
        global_struct = {}

    def add_section(heading: str, body: str):
        if not (body or "").strip():
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        runs.append(((body or "").strip() + "\n\n", None))

    # ---------- Global sections (unchanged behavior) ----------
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

    # ---------- Objective region rendering (PDF-like in monospaced text) ----------
    blocks = objectives_struct.get("blocks") or []
    if not isinstance(blocks, list):
        return runs

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

    # Slightly narrower columns so RIGHT SIDE starts more to the left
    # and avoids wrap spillover in tk.Text preview.
    COL_W = 26
    SEP = " "

    def _fit_cell(text: str, width: int) -> str:
        s = (text or "").strip()
        if len(s) <= width:
            return s
        # hard trim keeps table alignment stable in preview
        return s[: width - 1] + "…"

    def _fmt_row(left: str, right: str) -> str:
        l = _fit_cell(left, COL_W).ljust(COL_W)
        r = _fit_cell(right, COL_W).ljust(COL_W)
        return f"{l}{SEP}{r}"

    def _item_lines(item) -> list[str]:
        if not item:
            return []
        name = (item[0] or "").strip() if len(item) > 0 else ""
        line2 = (item[1] or "").strip() if len(item) > 1 else ""
        line3 = (item[2] or "").strip() if len(item) > 2 else ""
        out = []
        if name:
            out.append(name)
        if line2:
            out.append(line2)
        if line3:
            out.append(line3)
        return out or [""]

    def _append_lr_section(section_title: str, left_items: list, right_items: list, notes: str = ""):
        if not left_items and not right_items and not notes:
            return

        runs.append((section_title + "\n", "H_BOLD"))
        runs.append(("\n", None))

        table_lines = []
        table_lines.append(_fmt_row("LEFT SIDE", "RIGHT SIDE"))
        table_lines.append(_fmt_row("-" * 9, "-" * 10))
        table_lines.append("")

        max_len = max(len(left_items), len(right_items), 1)
        for i in range(max_len):
            l_lines = _item_lines(left_items[i]) if i < len(left_items) else [""]
            r_lines = _item_lines(right_items[i]) if i < len(right_items) else [""]
            h = max(len(l_lines), len(r_lines))
            for j in range(h):
                ltxt = l_lines[j] if j < len(l_lines) else ""
                rtxt = r_lines[j] if j < len(r_lines) else ""
                table_lines.append(_fmt_row(ltxt, rtxt))
            table_lines.append("")

        runs.append(("\n".join(table_lines).rstrip() + "\n\n", "PREVIEW_MONO"))

        if notes:
            runs.append((f"Notes: {notes}\n\n", None))

    def _append_rom_grid(section_title: str, code: str, rom_merged: dict, notes: str = ""):
        if not rom_merged and not notes:
            return

        runs.append((section_title + "\n", "H_BOLD"))
        runs.append(("\n", None))

        REGION_ROM_MOTIONS = {
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

        motions = REGION_ROM_MOTIONS.get(code, ["Flexion", "Extension", "Lateral Flexion", "Rotation"])

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

        def make_cell(motion: str) -> list[str]:
            lines = [motion]
            lines.extend(motion_lines(motion))
            if len(lines) < 4:
                lines.extend([""] * (4 - len(lines)))
            return [_fit_cell(ln, COL_W).ljust(COL_W) for ln in lines]

        box_lines = []
        hline = "+" + "-" * COL_W + "+" + "-" * COL_W + "+"

        cells = [make_cell(m) for m in motions]
        for i in range(0, len(cells), 2):
            left = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else [" " * COL_W for _ in range(len(left))]
            row_h = max(len(left), len(right))
            if len(left) < row_h:
                left += [" " * COL_W] * (row_h - len(left))
            if len(right) < row_h:
                right += [" " * COL_W] * (row_h - len(right))

            box_lines.append(hline)
            for j in range(row_h):
                box_lines.append(f"{left[j]}{right[j]}")
        box_lines.append(hline)

        runs.append(("\n".join(box_lines) + "\n\n", "PREVIEW_MONO"))

        if notes:
            runs.append((f"Notes: {notes}\n\n", None))

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

        rom_merged = {
            m: st for m, st in (rom_merged or {}).items()
            if int((st or {}).get("l_sev", -1)) != -1 or int((st or {}).get("r_sev", -1)) != -1
        }

        def first_note(region_blocks, key):
            for bb in region_blocks:
                txt = _clean_val(bb.get(key, ""))
                if txt:
                    return txt
            return ""

        palp_notes = first_note(region_blocks, "palpation_notes")
        ortho_notes = first_note(region_blocks, "ortho_notes")
        rom_notes = first_note(region_blocks, "rom_notes")

        has_any = bool(
            palp_left or palp_right or palp_notes or
            ortho_left or ortho_right or ortho_notes or
            rom_merged or rom_notes
        )
        if not has_any:
            continue

        runs.append((region_title + "\n", "H_BOLD"))
        runs.append(("\n", None))

        _append_lr_section(f"SOFT TISSUE PALPATION {tag}", palp_left, palp_right, palp_notes)
        _append_lr_section(f"ORTHOPEDIC EXAM {tag}", ortho_left, ortho_right, ortho_notes)
        _append_rom_grid(f"RANGE OF MOTION {tag}", code, rom_merged, rom_notes)

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
        code = _resolve_icd_from_dx_block(b)
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
# Family / Social History (PDF)
# =======================================================

# Built-in PDF fonts (e.g. Helvetica) lack glyphs for geometric bullets (○●■□); viewers
# substitute wrong shapes. Register a Unicode-capable TTF family so this section body matches
# what's shown in the Note builder / Live Preview.
_FS_FONT_FAMILY: "str | None" = None  # set after first successful registration

# Family candidates: (normal, bold, italic, bold-italic). First entry whose Regular face
# exists AND covers the bullet codepoints is used.
_FS_FONT_CANDIDATES: tuple[tuple[str, str, str, str, str], ...] = (
    # display name, Regular, Bold, Italic, BoldItalic  (file basenames)
    ("Arial",      "arial.ttf",       "arialbd.ttf",   "ariali.ttf",     "arialbi.ttf"),
    ("DejaVuSans", "DejaVuSans.ttf",  "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    ("SegoeUI",    "segoeui.ttf",     "segoeuib.ttf",  "segoeuii.ttf",   "segoeuiz.ttf"),
)

# Codepoints we need correct rendering for in the F/S body (geometric bullet shapes).
_FS_REQUIRED_BULLETS: tuple[int, ...] = (0x25CB, 0x25CF, 0x25A0, 0x25A1, 0x2022, 0x2013)


def _font_search_dirs() -> list[str]:
    dirs: list[str] = []
    win = os.environ.get("WINDIR")
    if win:
        dirs.append(os.path.join(win, "Fonts"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    dirs.extend([
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts",
    ])
    return [d for d in dirs if d and os.path.isdir(d)]


def _find_font_file(basename: str) -> "str | None":
    if not basename:
        return None
    for d in _font_search_dirs():
        p = os.path.join(d, basename)
        if os.path.isfile(p):
            return p
    return None


def _font_covers_bullets(path: str) -> bool:
    """Inspect the cmap (format 4, platform 3 / encoding 1) and confirm all required
    geometric-shape codepoints map to a non-zero glyph id."""
    try:
        import struct
        with open(path, "rb") as fh:
            data = fh.read()

        def u16(o: int) -> int:
            return struct.unpack(">H", data[o:o + 2])[0]

        def u32(o: int) -> int:
            return struct.unpack(">I", data[o:o + 4])[0]

        # Skip TTC wrapper (first font only).
        offset = 0
        if data[:4] == b"ttcf":
            offset = u32(12)

        num_tables = u16(offset + 4)
        cmap_off = None
        for i in range(num_tables):
            rec = offset + 12 + i * 16
            if data[rec:rec + 4] == b"cmap":
                cmap_off = u32(rec + 8)
                break
        if cmap_off is None:
            return False

        num_sub = u16(cmap_off + 2)
        sub_off = None
        for i in range(num_sub):
            r = cmap_off + 4 + i * 8
            pid = u16(r)
            eid = u16(r + 2)
            off = u32(r + 4)
            if pid == 3 and eid == 1 and u16(cmap_off + off) == 4:
                sub_off = cmap_off + off
                break
        if sub_off is None:
            return False

        seg_count = u16(sub_off + 6) // 2
        end_arr = sub_off + 14
        end = [u16(end_arr + i * 2) for i in range(seg_count)]
        start_arr = end_arr + seg_count * 2 + 2
        start = [u16(start_arr + i * 2) for i in range(seg_count)]
        delta_arr = start_arr + seg_count * 2
        delta = [struct.unpack(">h", data[delta_arr + i * 2:delta_arr + i * 2 + 2])[0] for i in range(seg_count)]
        ro_arr = delta_arr + seg_count * 2
        ro = [u16(ro_arr + i * 2) for i in range(seg_count)]

        for cp in _FS_REQUIRED_BULLETS:
            gid = 0
            for i in range(seg_count):
                if start[i] <= cp <= end[i]:
                    if ro[i] == 0:
                        gid = (cp + delta[i]) & 0xFFFF
                    else:
                        addr = ro_arr + i * 2 + ro[i] + (cp - start[i]) * 2
                        gid = u16(addr)
                        if gid != 0:
                            gid = (gid + delta[i]) & 0xFFFF
                    break
            if gid == 0:
                return False
        return True
    except Exception:
        return False


def _ensure_unicode_font_family() -> "str | None":
    """Register a Unicode-capable TTF family with ReportLab. Returns the family name
    to use as fontName, or None if nothing usable was found."""
    global _FS_FONT_FAMILY
    if _FS_FONT_FAMILY:
        return _FS_FONT_FAMILY

    try:
        import reportlab
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily, getRegisteredFontNames
    except Exception:
        return None

    registered = set(getRegisteredFontNames() or [])

    for family, reg, bold, ital, boldit in _FS_FONT_CANDIDATES:
        reg_path = _find_font_file(reg)
        if not reg_path or not _font_covers_bullets(reg_path):
            continue
        # Register Regular (required); register optional faces only when present so
        # bold/italic markup degrades gracefully if a specific face is missing.
        try:
            if family not in registered:
                pdfmetrics.registerFont(TTFont(family, reg_path))

            def _maybe(name: str, basename: str) -> str:
                if not basename:
                    return family
                if name in registered:
                    return name
                p = _find_font_file(basename)
                if not p:
                    return family
                pdfmetrics.registerFont(TTFont(name, p))
                return name

            bold_name   = _maybe(f"{family}-Bold",       bold)
            ital_name   = _maybe(f"{family}-Italic",     ital)
            boldit_name = _maybe(f"{family}-BoldItalic", boldit)

            registerFontFamily(
                family,
                normal=family,
                bold=bold_name,
                italic=ital_name,
                boldItalic=boldit_name,
            )
            _FS_FONT_FAMILY = family
            return _FS_FONT_FAMILY
        except Exception:
            continue

    # Final fallback: ReportLab-bundled Vera (does NOT cover geometric shapes, but at least
    # keeps PDF renderable when no system font is available).
    try:
        import reportlab
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        root = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        pdfmetrics.registerFont(TTFont("Vera",          os.path.join(root, "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("Vera-Bold",     os.path.join(root, "VeraBd.ttf")))
        pdfmetrics.registerFont(TTFont("Vera-Italic",   os.path.join(root, "VeraIt.ttf")))
        pdfmetrics.registerFont(TTFont("Vera-BoldItalic", os.path.join(root, "VeraBI.ttf")))
        registerFontFamily("Vera", normal="Vera", bold="Vera-Bold",
                           italic="Vera-Italic", boldItalic="Vera-BoldItalic")
        _FS_FONT_FAMILY = "Vera"
    except Exception:
        _FS_FONT_FAMILY = None
    return _FS_FONT_FAMILY


def _get_family_social_body_style(styles) -> object:
    """ParagraphStyle for F/S block bodies: Unicode-capable font so bullets render correctly."""
    from reportlab.lib.styles import ParagraphStyle

    family = _ensure_unicode_font_family()
    if not family:
        return styles["BodyText"]
    name = f"FamilySocialBody_{family}"
    if name in styles.byName:
        return styles[name]
    sty = ParagraphStyle(name=name, parent=styles["BodyText"], fontName=family)
    styles.add(sty)
    return sty


_FS_BULLET_HANG_LINE = re.compile(
    r"^(\t*(?:[\-–•●○■□]+\s*)?[^:]+:\s*)(.*)$"
)

# Matches tab-indented bullet lines that have NO colon (e.g. "\t• X-Ray").
# Used when a primary selection has no associated option chosen.
_FS_TAB_BULLET_NO_COLON_LINE = re.compile(
    r"^(\t+[\-–•●○■□]+\s*)(.+)$"
)

_FS_HANG_STYLE_SEQ = [0]


def _fs_pdf_prefix_width_pt(prefix_plain: str, font_name: str, font_size: float) -> float:
    """Width in points for tab + bullet + label + ': ' (continuation lines align after this)."""
    try:
        from reportlab.pdfbase import pdfmetrics
    except Exception:
        return float(len(prefix_plain.replace("\t", "        ")) * 0.52 * (font_size or 10))
    tabbed = prefix_plain.replace("\t", "        ")
    try:
        w = float(pdfmetrics.stringWidth(tabbed, font_name, font_size or 10))
    except Exception:
        w = float(len(tabbed) * 0.52 * (font_size or 10))
    return w * 1.06 + 2.4


# Regex to split a rich XML string into tag tokens vs. text-node tokens.
_FS_XML_TOKEN = re.compile(r"(<[^>]+>)")


def _pdf_preserve_whitespace(plain: str) -> str:
    """Convert tabs and multi-space runs to non-breaking spaces so ReportLab
    preserves the visual spacing instead of collapsing it to a single space."""
    plain = plain.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    plain = re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group(0)), plain)
    return plain


def _pdf_preserve_whitespace_in_rich(rich: str) -> str:
    """Apply `_pdf_preserve_whitespace` to text nodes only inside a rich XML
    string, leaving tag tokens (e.g. <b>, </i>) untouched."""
    parts = _FS_XML_TOKEN.split(rich)
    return "".join(
        part if part.startswith("<") else _pdf_preserve_whitespace(part)
        for part in parts
    )


def _fs_pdf_tab_indent_pt(font_name: str, font_size: float) -> float:
    """Width in points of one '\\t' rendered as 8 spaces (matches the prefix-width calc)."""
    try:
        from reportlab.pdfbase import pdfmetrics

        return float(pdfmetrics.stringWidth("        ", font_name, font_size or 10))
    except Exception:
        return 8 * 0.52 * (font_size or 10)


def _fs_pdf_bullet_hang_style(
    base_style: object,
    hang_pt: float,
    styles: object,
    tab_indent_pt: float = 0.0,
) -> object:
    """leftIndent + firstLineIndent = hanging wrap under the body start (after label).

    `tab_indent_pt` shifts the WHOLE bullet block to the right by one tab so the
    bullet character itself sits indented (matching the Live Preview / textbox).
    `hang_pt` is the full prefix width INCLUDING that tab, so we offset
    `firstLineIndent` by `tab_indent_pt` to land the first character at
    `base_left + tab_indent_pt` while wrapped lines still align after the label.
    """
    from reportlab.lib.styles import ParagraphStyle

    base_left = getattr(base_style, "leftIndent", 0) or 0
    _FS_HANG_STYLE_SEQ[0] += 1
    nm = f"FSHang_{int(hang_pt * 100)}_{int(tab_indent_pt * 100)}_{_FS_HANG_STYLE_SEQ[0]}"
    if nm in styles.byName:
        return styles[nm]
    st = ParagraphStyle(
        name=nm,
        parent=base_style,
        leftIndent=base_left + hang_pt,
        firstLineIndent=-(hang_pt - tab_indent_pt),
    )
    styles.add(st)
    return st


def _fs_block_has_pdf_bullets(plain: str) -> bool:
    """True if plain text has tab/bullet sentence-builder lines (with or without a label colon)."""
    for raw in (plain or "").splitlines():
        line = raw.rstrip("\r")
        if _FS_BULLET_HANG_LINE.match(line):
            return True
        if _FS_TAB_BULLET_NO_COLON_LINE.match(line):
            return True
    return False


def _fs_pdf_flowables_from_note_plain(text: str, base_style: object, styles: object) -> list:
    """
    One Paragraph per narrative chunk; each builder bullet line becomes its own hanging Paragraph
    so wrapped lines align with the body text (e.g. after 'MRI: ').
    """
    out: list = []
    buf: list[str] = []
    font_name = getattr(base_style, "fontName", "Helvetica") or "Helvetica"
    font_size = getattr(base_style, "fontSize", 10) or 10

    def flush_buf() -> None:
        if not buf:
            return
        cleaned = [x for x in buf if x is not None]
        if not any((s or "").strip() for s in cleaned):
            buf.clear()
            return
        chunk = "<br/>".join(_pdf_preserve_whitespace(xml_escape(x)) for x in cleaned)
        out.append(Paragraph(chunk, base_style))
        buf.clear()

    prev_was_tab_bullet = False
    # pending_bullet: accumulates the current bullet paragraph's display lines so
    # that user-typed continuation lines (no \t prefix, typed right after a bullet
    # without a blank-line separator) are joined into the same Paragraph and
    # inherit the leftIndent style — matching the Live Preview's lmargin2 behaviour.
    pending_bullet_lines: list[str] = []
    pending_bullet_hst: object = base_style

    def flush_pending_bullet() -> None:
        nonlocal pending_bullet_lines, pending_bullet_hst
        if not pending_bullet_lines:
            return
        combined = "<br/>".join(pending_bullet_lines)
        out.append(Paragraph(combined, pending_bullet_hst))
        pending_bullet_lines = []

    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            flush_pending_bullet()
            buf.append("")
            prev_was_tab_bullet = False
            continue
        m = _FS_BULLET_HANG_LINE.match(line)
        m_nc = None if m else _FS_TAB_BULLET_NO_COLON_LINE.match(line)
        if m:
            flush_pending_bullet()
            flush_buf()
            is_tab_bullet = line.startswith("\t")
            # Insert a blank-line gap when transitioning from a non-tab
            # "header"/prefix line (e.g. "Template 3 prefix:") into the first
            # tab-indented bullet line, so the PDF matches the Live Preview
            # and the bottom textbox spacing.
            if is_tab_bullet and not prev_was_tab_bullet and out:
                out.append(Spacer(1, 0.12 * inch))
            prefix, body = m.group(1), m.group(2)
            display = prefix.replace("\t", "", 1) + body
            hang = _fs_pdf_prefix_width_pt(prefix, font_name, font_size)
            tab_pt = (
                _fs_pdf_tab_indent_pt(font_name, font_size) if is_tab_bullet else 0.0
            )
            pending_bullet_hst = _fs_pdf_bullet_hang_style(base_style, hang, styles, tab_pt)
            pending_bullet_lines = [_pdf_preserve_whitespace(xml_escape(display)).replace("\n", "<br/>")]
            prev_was_tab_bullet = is_tab_bullet
        elif m_nc:
            # Tab-indented bullet with no associated option (no "Label:" colon).
            flush_pending_bullet()
            flush_buf()
            if not prev_was_tab_bullet and out:
                out.append(Spacer(1, 0.12 * inch))
            prefix = m_nc.group(1)
            body = m_nc.group(2)
            display = prefix.replace("\t", "", 1) + body
            hang = _fs_pdf_prefix_width_pt(prefix, font_name, font_size)
            tab_pt = _fs_pdf_tab_indent_pt(font_name, font_size)
            pending_bullet_hst = _fs_pdf_bullet_hang_style(base_style, hang, styles, tab_pt)
            pending_bullet_lines = [_pdf_preserve_whitespace(xml_escape(display)).replace("\n", "<br/>")]
            prev_was_tab_bullet = True
        else:
            flush_pending_bullet()
            buf.append(line)
            prev_was_tab_bullet = False
    flush_pending_bullet()
    flush_buf()
    return out


# Strip <b>/<i>/<u> (and similar) tags from a rich line so the plain-text
# bullet regex can still detect bullet structure while keeping the
# original rich line intact for actual rendering.
_FS_RICH_TAG_STRIP = re.compile(r"<[^>]+>")
_FS_RICH_BR_SPLIT = re.compile(r"<br\s*/?>")


def _fs_pdf_flowables_from_note_rich(
    rich: str, base_style: object, styles: object
) -> list:
    """Per-line PDF flowables from a builder rich_text string.

    Mirrors `_fs_pdf_flowables_from_note_plain` but consumes the rich string
    produced by `FamilySocialSectionCore.get_rich_value()` so that
    bold/italic/underline (`<b>`, `<i>`, `<u>`) tags survive into the PDF.

    Tags in rich_text are guaranteed not to span `<br/>` boundaries because
    `get_rich_value()` wraps each annotated chunk individually and bullet
    line prefixes (which contain the newlines) are emitted as untagged
    chunks. Splitting on `<br/>` therefore yields per-visual-line segments
    whose markup is already balanced.
    """
    out: list = []
    if not (rich or "").strip():
        return out

    font_name = getattr(base_style, "fontName", "Helvetica") or "Helvetica"
    font_size = getattr(base_style, "fontSize", 10) or 10

    rich_lines = _FS_RICH_BR_SPLIT.split(rich)
    buf: list[str] = []

    def flush_buf() -> None:
        if not buf:
            return
        # Keep internal blank lines but trim trailing blanks to avoid an
        # empty trailing paragraph after a bullet block.
        cleaned = list(buf)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        if not any(s.strip() for s in cleaned):
            buf.clear()
            return
        chunk = "<br/>".join(_pdf_preserve_whitespace_in_rich(x) for x in cleaned)
        out.append(Paragraph(chunk, base_style))
        buf.clear()

    prev_was_tab_bullet = False
    # pending_bullet: accumulates the current bullet paragraph's display lines so
    # that user-typed continuation lines (no \t prefix, typed right after a bullet
    # without a blank-line separator) are joined into the same Paragraph.
    pending_bullet_lines: list[str] = []
    pending_bullet_hst: object = base_style

    def flush_pending_bullet() -> None:
        nonlocal pending_bullet_lines, pending_bullet_hst
        if not pending_bullet_lines:
            return
        combined = "<br/>".join(pending_bullet_lines)
        out.append(Paragraph(combined, pending_bullet_hst))
        pending_bullet_lines = []

    for rich_line in rich_lines:
        # Detect bullet structure on the plain-text projection so XML markup
        # cannot interfere with the regex.
        plain_line = _FS_RICH_TAG_STRIP.sub("", rich_line)
        if not plain_line.strip():
            flush_pending_bullet()
            buf.append("")
            prev_was_tab_bullet = False
            continue
        m = _FS_BULLET_HANG_LINE.match(plain_line)
        m_nc = None if m else _FS_TAB_BULLET_NO_COLON_LINE.match(plain_line)
        if m:
            flush_pending_bullet()
            flush_buf()
            is_tab_bullet = rich_line.startswith("\t") or plain_line.startswith("\t")
            # Insert a blank-line gap when transitioning from a non-tab
            # "header"/prefix line (e.g. "Template 3 prefix:") into the first
            # tab-indented bullet line, so the PDF matches the Live Preview
            # and the bottom textbox spacing.
            if is_tab_bullet and not prev_was_tab_bullet and out:
                out.append(Spacer(1, 0.12 * inch))
            prefix_plain = m.group(1)
            # Display: drop the leading tab to match the plain-text version's
            # one-tab strip (the hang style supplies the indent visually).
            display_rich = rich_line[1:] if rich_line.startswith("\t") else rich_line
            hang = _fs_pdf_prefix_width_pt(prefix_plain, font_name, font_size)
            tab_pt = (
                _fs_pdf_tab_indent_pt(font_name, font_size) if is_tab_bullet else 0.0
            )
            pending_bullet_hst = _fs_pdf_bullet_hang_style(base_style, hang, styles, tab_pt)
            pending_bullet_lines = [_pdf_preserve_whitespace_in_rich(display_rich)]
            prev_was_tab_bullet = is_tab_bullet
        elif m_nc:
            # Tab-indented bullet with no associated option (no "Label:" colon).
            flush_pending_bullet()
            flush_buf()
            if not prev_was_tab_bullet and out:
                out.append(Spacer(1, 0.12 * inch))
            prefix_plain = m_nc.group(1)
            display_rich = rich_line[1:] if rich_line.startswith("\t") else rich_line
            hang = _fs_pdf_prefix_width_pt(prefix_plain, font_name, font_size)
            tab_pt = _fs_pdf_tab_indent_pt(font_name, font_size)
            pending_bullet_hst = _fs_pdf_bullet_hang_style(base_style, hang, styles, tab_pt)
            pending_bullet_lines = [_pdf_preserve_whitespace_in_rich(display_rich)]
            prev_was_tab_bullet = True
        else:
            flush_pending_bullet()
            buf.append(rich_line)
            prev_was_tab_bullet = False
    flush_pending_bullet()
    flush_buf()
    return out


def build_family_social_flowables(soap: dict, styles) -> list:
    """Heading2 main title; v2 builder uses Heading3 per block. Legacy: single body."""
    soap = soap or {}
    if soap.get("family_social_section_skipped"):
        return []
    out: list = []
    b = soap.get("family_social_builder")
    if isinstance(b, dict) and int(b.get("v") or 0) == 2:
        nonempty: list[tuple[str, str, str]] = []
        for bl in b.get("blocks") or []:
            if not isinstance(bl, dict):
                continue
            text = (bl.get("text") or "").strip()
            if not text:
                continue
            rich = (bl.get("rich_text") or "").strip()
            nonempty.append(((bl.get("heading") or "").strip(), text, rich))
        if not nonempty:
            return []
        out.append(Paragraph("<b>FAMILY / SOCIAL HISTORY</b>", styles["Heading2"]))
        out.append(Spacer(1, 0.08 * inch))
        fs_body = _get_family_social_body_style(styles)
        for heading, text, rich in nonempty:
            if heading:
                out.append(Paragraph(f"<b>{xml_escape(heading)}</b>", styles["Heading3"]))
                out.append(Spacer(1, 0.04 * inch))
            if rich:
                if _fs_block_has_pdf_bullets(text):
                    for fl in _fs_pdf_flowables_from_note_rich(rich, fs_body, styles):
                        out.append(fl)
                else:
                    out.append(Paragraph(_pdf_preserve_whitespace_in_rich(rich), fs_body))
            else:
                for fl in _fs_pdf_flowables_from_note_plain(text, fs_body, styles):
                    out.append(fl)
            out.append(Spacer(1, 0.10 * inch))
        return out

    family_social = (soap.get("family_social") or "").strip()
    if not family_social:
        return []
    out.append(Paragraph("<b>FAMILY / SOCIAL HISTORY</b>", styles["Heading2"]))
    out.append(Spacer(1, 0.08 * inch))
    fs_body_legacy = _get_family_social_body_style(styles)
    if _fs_block_has_pdf_bullets(family_social):
        for fl in _fs_pdf_flowables_from_note_plain(family_social, fs_body_legacy, styles):
            out.append(fl)
    else:
        safe_fs = _pdf_preserve_whitespace(xml_escape(family_social)).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
        out.append(Paragraph(safe_fs, fs_body_legacy))
    out.append(Spacer(1, 0.12 * inch))
    return out


def build_subjectives_canvas_flowables(subj: dict, styles) -> list:
    """
    Render Subjectives-on-Canvas content inside the SUBJECTIVES section.
    Supports v2 builder blocks with rich_text; falls back to plain canvas text.
    """
    subj = subj or {}
    canvas = subj.get("canvas")
    if not isinstance(canvas, dict):
        return []
    if bool(canvas.get("section_skipped")):
        return []

    out: list = []
    body_style = _get_family_social_body_style(styles)
    builder = canvas.get("builder_state")

    if isinstance(builder, dict) and int(builder.get("v") or 0) == 2:
        nonempty: list[tuple[str, str, str]] = []
        for bl in builder.get("blocks") or []:
            if not isinstance(bl, dict):
                continue
            text = (bl.get("text") or "").strip()
            if not text:
                continue
            heading = (bl.get("heading") or "").strip()
            rich = (bl.get("rich_text") or "").strip()
            nonempty.append((heading, text, rich))

        if nonempty:
            for heading, text, rich in nonempty:
                if heading:
                    out.append(Paragraph(f"<b>{xml_escape(heading)}</b>", styles["Heading3"]))
                    out.append(Spacer(1, 0.04 * inch))
                if rich:
                    if _fs_block_has_pdf_bullets(text):
                        for fl in _fs_pdf_flowables_from_note_rich(rich, body_style, styles):
                            out.append(fl)
                    else:
                        out.append(Paragraph(_pdf_preserve_whitespace_in_rich(rich), body_style))
                else:
                    for fl in _fs_pdf_flowables_from_note_plain(text, body_style, styles):
                        out.append(fl)
                out.append(Spacer(1, 0.10 * inch))
            return out

    plain = (canvas.get("text") or "").strip()
    if not plain:
        return []
    if _fs_block_has_pdf_bullets(plain):
        for fl in _fs_pdf_flowables_from_note_plain(plain, body_style, styles):
            out.append(fl)
    else:
        safe_plain = _pdf_preserve_whitespace(xml_escape(plain)).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
        out.append(Paragraph(safe_plain, body_style))
    out.append(Spacer(1, 0.10 * inch))
    return out


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
        """Only adds when body is non-empty (legacy single-arg use)."""
        if not (body or "").strip():
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        runs.append(((body or "").strip() + "\n\n", None))

    def add_section_with_notes(heading: str, body: str, notes: str):
        """Shows heading when there is body OR notes; then body (if any), then notes (if any)."""
        body_s = (body or "").strip()
        notes_s = (notes or "").strip()
        if not body_s and not notes_s:
            return
        runs.append((heading + "\n", "H_BOLD"))
        runs.append(("\n", None))
        if body_s:
            runs.append((body_s + "\n\n", None))
        if notes_s:
            runs.append((notes_s + "\n\n", None))

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
    dx_block_notes = (dx_struct.get("dx_block_notes") or "").strip()
    add_section_with_notes("Diagnosis", dx_text, dx_block_notes)

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
    causation_body = "\n\n".join(causation_lines) if causation_lines else ""
    causation_general_notes = (dx_struct.get("causation_general_notes") or "").strip()
    add_section_with_notes("Causation", causation_body, causation_general_notes)
    # Prognosis
    prog = (dx_struct.get("prognosis") or "").strip()
    prognosis_text = ""
    if prog and prog != "(select)":
        if prog.lower() == "guarded":
            prognosis_text = (
                "Based on the patient's reported symptoms, objective findings, "
                "and functional impairments, the prognosis is currently assessed "
                f"as {prog}. Positive outcomes are expected, contingent "
                "upon the patient's active engagement in care and treatment compliance."
            )
        else:
            prognosis_text = (
                "Based on the patient's clinical presentation and examination findings, "
                f"the prognosis is currently assessed as {prog}. Progress will be monitored "
                "and reassessed throughout the course of care."
            )
    prognosis_notes = (dx_struct.get("prognosis_notes") or "").strip()
    add_section_with_notes("Prognosis", prognosis_text, prognosis_notes)

    # Imaging
    img = _imaging_sentence(dx_struct) or ""
    imaging_notes = (dx_struct.get("imaging_notes") or "").strip()
    add_section_with_notes("Imaging", img, imaging_notes)

    ref = _referral_sentence(dx_struct) or ""
    referrals_notes = (dx_struct.get("referrals_notes") or "").strip()
    add_section_with_notes("Referrals", ref, referrals_notes)

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
    emp_body = "\n".join(emp_lines) if emp_lines else ""
    employment_general_notes = (dx_struct.get("employment_general_notes") or "").strip()
    add_section_with_notes("Current Work Status", emp_body, employment_general_notes)

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

        subj_canvas_flow = build_subjectives_canvas_flowables(subj, styles)
        if subj_canvas_flow:
            if printed_any_subjectives:
                story.append(Spacer(1, 0.10 * inch))
            story.extend(subj_canvas_flow)
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

        fs_flow = build_family_social_flowables(soap, styles)
        if fs_flow:
            story.extend(fs_flow)
        
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

        def add_section_with_notes(title: str, content: str, notes: str):
            """Show heading only when there is content or notes; then content, then notes."""
            content_s = (content or "").strip()
            notes_s = (notes or "").strip()
            if not content_s and not notes_s:
                return
            story.append(Paragraph(f"<b>{xml_escape(title)}</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.08 * inch))
            if content_s:
                safe = xml_escape(content_s).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
                story.append(Paragraph(safe, styles["BodyText"]))
                story.append(Spacer(1, 0.06 * inch))
            if notes_s:
                story.append(Paragraph(xml_escape(notes_s).replace("\n", "<br/>"), styles["BodyText"]))
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
        dx_block_notes = (dx_struct.get("dx_block_notes") or "").strip()
        add_section_with_notes("Diagnosis", dx_text, dx_block_notes)
        
        causation_general_notes = (dx_struct.get("causation_general_notes") or "").strip()
        if causation_para or causation_general_notes:
            story.append(Paragraph("<b>Causation</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.04 * inch))
            if causation_para:
                story.append(causation_para)
                story.append(Spacer(1, 0.10 * inch))
            if causation_general_notes:
                story.append(Spacer(1, 0.06 * inch))
                story.append(Paragraph(xml_escape(causation_general_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))
        
        bold_body = ParagraphStyle(
            'BoldBody',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold'
        )               
                               
        prog = (dx_struct.get("prognosis") or "").strip()
        prognosis_text = ""
        if prog and prog != "(select)":
            if prog.lower() == "guarded":
                prognosis_text = (
                    "Based on the patient's reported symptoms, objective findings, "
                    "and functional impairments, the prognosis is currently assessed "
                    f"as {prog}. Positive outcomes are expected, contingent "
                    "upon the patient's active engagement in care and treatment compliance."
                )
            else:
                prognosis_text = (
                    "Based on the patient's clinical presentation and examination findings, "
                    f"the prognosis is currently assessed as {prog}. Progress will be monitored "
                    "and reassessed throughout the course of care."
                )
        prognosis_notes = (dx_struct.get("prognosis_notes") or "").strip()
        add_section_with_notes("Prognosis", prognosis_text, prognosis_notes)
                    
            
        img = _imaging_sentence(dx_struct) or ""
        imaging_notes = (dx_struct.get("imaging_notes") or "").strip()
        add_section_with_notes("Imaging", img, imaging_notes)

        ref = _referral_sentence(dx_struct) or ""
        referrals_notes = (dx_struct.get("referrals_notes") or "").strip()
        add_section_with_notes("Referrals", ref, referrals_notes)
        
        employment_general_notes = (dx_struct.get("employment_general_notes") or "").strip()
        if emp_current_para or employment_general_notes:
            story.append(Paragraph("<b>Current Work Status</b>", styles["Heading3"]))
            story.append(Spacer(1, 0.04 * inch))
            if emp_current_para:
                story.append(emp_current_para)
                story.append(Spacer(1, 0.10 * inch))
            if employment_general_notes:
                story.append(Spacer(1, 0.06 * inch))
                story.append(Paragraph(xml_escape(employment_general_notes).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 0.14 * inch))
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








