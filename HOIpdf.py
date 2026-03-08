# HOIpdf.py
from reportlab.platypus import Paragraph, Spacer, KeepTogether
from reportlab.lib.units import inch
from xml.sax.saxutils import escape as xml_escape
import re

# Keep this in sync with HOI.py
AUTO_MOI_TAG = "[AUTO:MOI]"

def _clean_text(x) -> str:
    return (x or "").strip()

def _get(d: dict, *path, default=""):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default

def _strip_auto_tag(text: str) -> str:
    """
    Remove the [AUTO:MOI] marker from PDF output (but it can remain in JSON/UI).
    Case-insensitive and removes surrounding whitespace/newlines.
    """
    if not text:
        return ""
    cleaned = re.sub(r"\s*\[AUTO:MOI\]\s*", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def _format_multiline(text: str) -> str:
    """
    ReportLab Paragraph wants <br/> for line breaks.
    Escape XML safely and preserve blank lines.
    """
    safe = xml_escape(text or "")
    safe = safe.replace("\r\n", "\n").replace("\r", "\n")
    safe = safe.replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
    return safe

def _as_list(x):
    if isinstance(x, list):
        return x
    return []

def _clean_list(xs):
    return [s.strip() for s in (xs or []) if isinstance(s, str) and s.strip()]


def _title_case_join(items):
    items = _clean_list(items)
    return ", ".join(items)


def _build_imaging_lines(hoi_struct: dict) -> list[str]:
    """
    Build imaging summary lines from HOI struct.

    Preferred storage:
      hoi_struct["struct"]["imaging_blocks"] = [
        {"types": [...], "parts": [...]},
        ...
      ]

    Legacy fallback:
      hoi_struct["struct"]["imaging_types"] = [...]
      hoi_struct["struct"]["imaging_bodypart"] = "Cervical Spine"
    """
    struct = hoi_struct.get("struct") or {}
    imaging_done = _clean_text(struct.get("imaging_done", ""))

    if imaging_done != "Imaging performed":
        return []

    lines = []

    blocks = _as_list(struct.get("imaging_blocks"))
    if blocks:
        for b in blocks:
            if not isinstance(b, dict):
                continue
            types = _clean_list(b.get("types"))
            parts = _clean_list(b.get("parts"))

            if not types and not parts:
                continue

            type_txt = ", ".join([t.lower() for t in types]) if types else "imaging"
            if parts:
                part_txt = ", ".join([p.lower() for p in parts])
                lines.append(f"Imaging studies were performed in the form of {type_txt} involving the {part_txt}.")
            else:
                lines.append(f"Imaging studies were performed in the form of {type_txt}.")
        return lines

    # ---- Legacy fallback ----
    legacy_types = _clean_list(struct.get("imaging_types"))
    legacy_bp = _clean_text(struct.get("imaging_bodypart", ""))

    if not legacy_types and legacy_bp in ("", "(none)"):
        return ["Imaging studies were performed."]

    type_txt = ", ".join([t.lower() for t in legacy_types]) if legacy_types else "imaging"
    if legacy_bp and legacy_bp != "(none)":
        lines.append(f"Imaging studies were performed in the form of {type_txt} involving the {legacy_bp.lower()}.")
    else:
        lines.append(f"Imaging studies were performed in the form of {type_txt}.")
    return lines

def build_rof_flowables(
    hoi_struct: dict,
    styles,
    *,
    allow_modes: set[str] | None = None,
    deny_modes: set[str] | None = None,
) -> list:
    """
    Builds the ROF/Status Update/Introduction/Final Visit Summary section.

    Filtering:
      - If allow_modes is provided, only those rof_mode values will render.
      - If deny_modes is provided, those rof_mode values will NOT render.
    Notes:
      - rof_mode comes from hoi_struct["rof"]["mode"] (may be "", "ROF", "Initial", "Re-Exam", "Final", etc.)
      - legacy fallback uses hoi_struct["rof_text"] when struct is empty.
    """
    hoi_struct = hoi_struct or {}
    out = []

    rof_struct = hoi_struct.get("rof") or {}
    if not isinstance(rof_struct, dict):
        rof_struct = {}

    rof_mode = _clean_text(rof_struct.get("mode", ""))

    # ✅ MODE FILTERING (controls where this section prints)
    if allow_modes is not None and rof_mode not in allow_modes:
        return []
    if deny_modes is not None and rof_mode in deny_modes:
        return []

    rof_auto = _clean_text(rof_struct.get("auto_paragraph", ""))
    rof_manual = _clean_text(rof_struct.get("manual_paragraph", ""))
    legacy_rof = _clean_text(hoi_struct.get("rof_text", ""))

    heading = "REVIEW OF FINDINGS"
    if rof_mode and rof_mode != "ROF":
        if rof_mode == "Re-Exam":
            heading = "Status Update"
        elif rof_mode == "Initial":
            heading = "History of Present Illness"
        elif rof_mode == "Final":
            heading = "Final Visit Summary"
        else:
            heading = rof_mode

    rof_paragraphs = []
    if rof_auto:
        rof_paragraphs.append(rof_auto)
    if rof_manual:
        rof_paragraphs.append(rof_manual)

    if not rof_paragraphs and legacy_rof:
        rof_paragraphs = [legacy_rof]

    if not rof_paragraphs:
        return []

    out.append(Paragraph(f"<b>{xml_escape(heading)}</b>", styles["Heading2"]))
    out.append(Spacer(1, 0.08 * inch))

    for i, para in enumerate(rof_paragraphs):
        safe_para = _format_multiline(para)
        out.append(Paragraph(safe_para, styles["BodyText"]))  # or f"<i>{safe_para}</i>" if you want italics
        if i != (len(rof_paragraphs) - 1):
            out.append(Spacer(1, 0.10 * inch))

    out.append(Spacer(1, 0.14 * inch))
    return out

def build_hoi_flowables(hoi_struct: dict, styles, doc_width, include_rof: bool = True):
    hoi_struct = hoi_struct or {}
    out = []

    # ✅ Print beginning modes once (Initial/Re-Exam/Final/etc), but not ROF/blank
    if include_rof:
        out.extend(build_rof_flowables(hoi_struct, styles, deny_modes={"ROF", ""}))

    
    # History of Injury (existing behavior)    
    moi_raw = _clean_text(_get(hoi_struct, "history", "moi", default=""))
    moi_pdf = _strip_auto_tag(moi_raw)

    if not moi_pdf:
        return out if out else []
    
    out.append(
        KeepTogether(
            [
                Paragraph("<b>Mechanism of Injury (MOI):</b>", styles["Heading3"]),
                Spacer(1, 0.03 * inch),
                Paragraph(_format_multiline(moi_pdf), styles["BodyText"]),
                Spacer(1, 0.08 * inch),
            ]
        )
    )

    return out