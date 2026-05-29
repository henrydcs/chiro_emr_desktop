# schedule_engine.py — Appointment display rules and chart linkage.
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from config import PATIENT_SUBDIR_EXAMS
from utils import normalize_mmddyyyy

SLOT_MINUTES = 15
DAY_START_HOUR = 8   # 8:00 AM
DAY_END_HOUR = 19    # last bookable start time 7:00 PM

DISPLAY_STYLES: dict[str, dict[str, str]] = {
    "scheduled": {"bg": "#DBEAFE", "fg": "#1E40AF", "border": "#93C5FD"},
    "checked_in": {"bg": "#FEF3C7", "fg": "#92400E", "border": "#FCD34D"},
    "in_progress": {"bg": "#FFEDD5", "fg": "#C2410C", "border": "#FDBA74"},
    "completed": {"bg": "#E5E7EB", "fg": "#4B5563", "border": "#D1D5DB"},
    "signed": {"bg": "#E5E7EB", "fg": "#6B7280", "border": "#D1D5DB"},
    "no_show": {"bg": "#FEE2E2", "fg": "#B91C1C", "border": "#FCA5A5"},
    "cancelled": {"bg": "#F3F4F6", "fg": "#9CA3AF", "border": "#E5E7EB"},
}


def infer_chart_signed(exam_path: str) -> bool:
    path = (exam_path or "").strip()
    if not path:
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    sig = payload.get("signed") or payload.get("signed_at") or payload.get("locked")
    return bool(sig)


def _iso_to_mmddyyyy(iso_date: str) -> str:
    try:
        d = date.fromisoformat(iso_date)
        return d.strftime("%m/%d/%Y")
    except Exception:
        return ""


def find_exam_for_appointment(patient_folder: str, iso_date: str) -> str:
    """Best-effort link: patient exam JSON whose exam_date matches appointment date."""
    folder = Path(patient_folder or "")
    if not folder.is_dir():
        return ""
    target = _iso_to_mmddyyyy(iso_date)
    if not target:
        return ""
    exams_dir = folder / PATIENT_SUBDIR_EXAMS
    if not exams_dir.is_dir():
        return ""
    best_path = ""
    best_dt = datetime.min
    for p in exams_dir.glob("*.json"):
        if p.name.lower() == "_exam_index.json":
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        patient = payload.get("patient") or {}
        if not isinstance(patient, dict):
            continue
        exam_date = normalize_mmddyyyy(patient.get("exam_date") or "") or ""
        if exam_date != target:
            continue
        try:
            dt = datetime.strptime(exam_date, "%m/%d/%Y")
        except Exception:
            dt = datetime.min
        if dt >= best_dt:
            best_dt = dt
            best_path = str(p.resolve())
    return best_path


def enrich_appointment(appt: dict) -> dict:
    """Attach resolved exam_path and display style metadata."""
    out = dict(appt)
    exam_path = (out.get("exam_path") or "").strip()
    if not exam_path:
        exam_path = find_exam_for_appointment(
            out.get("patient_folder") or "",
            out.get("date") or "",
        )
        if exam_path:
            out["exam_path"] = exam_path
    signed = infer_chart_signed(exam_path)
    out["chart_signed"] = signed
    style_key = resolve_style_key(out, signed=signed)
    out["display_style"] = DISPLAY_STYLES.get(style_key, DISPLAY_STYLES["scheduled"])
    out["display_status"] = style_key.replace("_", " ")
    return out


def resolve_style_key(appt: dict, *, signed: bool | None = None) -> str:
    status = (appt.get("status") or "scheduled").strip().lower()
    if status == "cancelled":
        return "cancelled"
    if status == "no_show":
        return "no_show"
    if signed is None:
        signed = infer_chart_signed(appt.get("exam_path") or "")
    if signed or status == "completed":
        return "signed" if signed else "completed"
    if status in DISPLAY_STYLES:
        return status
    return "scheduled"


def parse_start_minutes(start_time: str) -> int:
    raw = (start_time or "").strip()
    if not raw:
        return DAY_START_HOUR * 60
    try:
        parts = raw.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return h * 60 + m
    except Exception:
        return DAY_START_HOUR * 60


def format_time_12h(start_time: str) -> str:
    mins = parse_start_minutes(start_time)
    h24 = mins // 60
    m = mins % 60
    suffix = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def format_time_short(start_time: str) -> str:
    """12-hour clock without AM/PM — e.g. 11:30."""
    mins = parse_start_minutes(start_time)
    h24 = mins // 60
    m = mins % 60
    h12 = h24 % 12 or 12
    return f"{h12}:{m:02d}"


def slot_index(start_time: str) -> int:
    return max(0, (parse_start_minutes(start_time) - DAY_START_HOUR * 60) // SLOT_MINUTES)


def slot_span(duration_min: int) -> int:
    return max(1, int(duration_min or SLOT_MINUTES) // SLOT_MINUTES)


def calendar_row_span(appt: dict) -> int:
    """Visual rows on the 15-minute grid (Initial = 2, Chiro Visit = 1)."""
    label = (appt.get("appt_type") or "").strip().lower()
    if "initial" in label:
        return 2
    if "chiro visit" in label or label == "chiro":
        return 1
    return max(1, slot_span(int(appt.get("duration_min") or 15)))


def day_slot_count() -> int:
    """Rows from DAY_START_HOUR through DAY_END_HOUR inclusive (e.g. 8 AM – 7 PM)."""
    return ((DAY_END_HOUR - DAY_START_HOUR) * 60) // SLOT_MINUTES + 1


def time_for_slot(slot: int) -> str:
    """24h HH:MM for a grid row index."""
    minutes = DAY_START_HOUR * 60 + slot * SLOT_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_label_for_slot(slot: int) -> str:
    return format_time_short(time_for_slot(slot))


def patient_short_label(appt: dict) -> str:
    label = (appt.get("patient_label") or "").strip()
    if label:
        return label.split(",")[0].strip()
    return (appt.get("patient_id") or "Patient").strip()


def patient_last_name(appt: dict) -> str:
    label = (appt.get("patient_label") or "").strip()
    if label:
        if "," in label:
            return label.split(",")[0].strip()
        parts = label.split()
        if len(parts) >= 2:
            return parts[-1]
        return parts[0]
    return (appt.get("patient_id") or "Patient").strip()


def appt_block_label(appt: dict) -> str:
    """Single-line calendar label: 11:30 Smith Chiro Visit."""
    parts = [
        format_time_short(appt.get("start_time") or ""),
        patient_last_name(appt),
    ]
    appt_type = (appt.get("appt_type") or "").strip()
    if appt_type:
        parts.append(appt_type)
    return " ".join(parts)
