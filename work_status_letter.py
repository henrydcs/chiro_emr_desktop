# work_status_letter.py — Work restrictions / disability status letters.
from __future__ import annotations

import re
from datetime import datetime, timedelta
from xml.sax.saxutils import escape as xml_escape

from config import CLINIC_NAME, PROVIDER_NAME
from pdf_export import (
    REPORTLAB_OK,
    ExamStart,
    HeaderExamNumberedCanvas,
    _doi_for_imaging_letter,
    _injury_event_phrase,
)
from utils import normalize_mmddyyyy, today_mmddyyyy

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
except Exception:
    LETTER = None  # type: ignore

WORK_STATUS_LETTER_TITLE = "Functional Work Status"

WORK_STATUS_PATIENT_NAME_TOKEN = "{PATIENT_NAME}"
WORK_STATUS_FIRST_NAME_TOKEN = "{FIRST_NAME}"
WORK_STATUS_LAST_NAME_TOKEN = "{LAST_NAME}"
WORK_STATUS_DOI_TOKEN = "{DATE_OF_INJURY}"
WORK_STATUS_INCIDENT_TOKEN = "{INCIDENT}"
WORK_STATUS_WORK_STATUS_TOKEN = "{WORK_STATUS}"
WORK_STATUS_DURATION_TOKEN = "{DURATION_LABEL}"
WORK_STATUS_DURATION_DAYS_TOKEN = "{DURATION_DAYS}"
WORK_STATUS_RTW_TOKEN = "{RETURN_TO_WORK_DATE}"
WORK_STATUS_PROVIDER_TOKEN = "{PROVIDER_NAME}"
WORK_STATUS_CLINIC_TOKEN = "{CLINIC_NAME}"
WORK_STATUS_EVAL_DATE_TOKEN = "{EVAL_DATE}"

_FULL_DUTY = "Full Duty (No Restrictions)"


def work_status_letter_should_generate(payload: dict) -> bool:
    dx = ((payload or {}).get("soap") or {}).get("diagnosis_struct") or {}
    if not isinstance(dx, dict):
        return False
    wp = (dx.get("work_plan") or "").strip()
    if not wp or wp == "(select)" or wp == _FULL_DUTY:
        return False
    dur = (dx.get("work_duration") or "").strip()
    return bool(dur and dur != "(select)")


def _incident_mechanism_text(hoi_struct: dict) -> str:
    """Letter incident phrase from HOI → Type of Injury → Type (injury_type)."""
    hoi_struct = hoi_struct if isinstance(hoi_struct, dict) else {}
    injury_type = ((hoi_struct.get("type") or {}).get("injury_type") or "").strip()
    if not injury_type or injury_type in ("(none)", ""):
        return "the reported incident"
    return _injury_event_phrase(hoi_struct) or injury_type


def duration_label_to_days(label: str) -> int | None:
    s = (label or "").strip().lower()
    if not s or s == "(select)":
        return None
    m = re.match(r"^(\d+)\s+day", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)\s+week", s)
    if m:
        return int(m.group(1)) * 7
    m = re.match(r"^(\d+)\s+month", s)
    if m:
        return int(m.group(1)) * 30
    m = re.search(r"(\d+)", s)
    if m and "month" in s:
        return int(m.group(1)) * 30
    if m and "week" in s:
        return int(m.group(1)) * 7
    if m and "day" in s:
        return int(m.group(1))
    return None


def _add_days_mmddyyyy(date_str: str, days: int) -> str:
    base = normalize_mmddyyyy(date_str) or today_mmddyyyy()
    try:
        dt = datetime.strptime(base, "%m/%d/%Y") + timedelta(days=max(days, 0))
        return dt.strftime("%m/%d/%Y")
    except Exception:
        return base


def work_status_letter_dynamic_parts(payload: dict) -> dict[str, str]:
    payload = payload or {}
    patient = payload.get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    soap = payload.get("soap") or {}
    dx = soap.get("diagnosis_struct") or {}
    if not isinstance(dx, dict):
        dx = {}
    hoi = soap.get("hoi_struct") or {}
    if not isinstance(hoi, dict):
        hoi = {}

    first = (patient.get("first_name") or "").strip()
    last = (patient.get("last_name") or "").strip()
    display = (patient.get("display_name") or "").strip() or f"{last}, {first}".strip(", ")

    doi = normalize_mmddyyyy((patient.get("doi") or "").strip()) or _doi_for_imaging_letter(patient, hoi)
    eval_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
    work_status = (dx.get("work_plan") or "").strip()
    duration_label = (dx.get("work_duration") or "").strip()
    if duration_label == "(select)":
        duration_label = ""

    days = duration_label_to_days(duration_label) if duration_label else None
    duration_days = str(days) if days is not None else ""
    rtw = _add_days_mmddyyyy(eval_date, days) if days is not None else ""

    provider = ((patient.get("provider") or "").strip() or (PROVIDER_NAME or "").strip())
    clinic = (CLINIC_NAME or "").strip()

    return {
        "patient_name": display,
        "first_name": first,
        "last_name": last,
        "date_of_injury": doi,
        "incident": _incident_mechanism_text(hoi),
        "work_status": work_status,
        "duration_label": duration_label,
        "duration_days": duration_days,
        "return_to_work_date": rtw,
        "provider_name": provider,
        "clinic_name": clinic,
        "eval_date": eval_date,
    }


def _apply_work_status_tokens(text: str, parts: dict[str, str]) -> str:
    mapping = {
        WORK_STATUS_PATIENT_NAME_TOKEN: parts.get("patient_name") or "",
        WORK_STATUS_FIRST_NAME_TOKEN: parts.get("first_name") or "",
        WORK_STATUS_LAST_NAME_TOKEN: parts.get("last_name") or "",
        WORK_STATUS_DOI_TOKEN: parts.get("date_of_injury") or "",
        WORK_STATUS_INCIDENT_TOKEN: parts.get("incident") or "",
        WORK_STATUS_WORK_STATUS_TOKEN: parts.get("work_status") or "",
        WORK_STATUS_DURATION_TOKEN: parts.get("duration_label") or "",
        WORK_STATUS_DURATION_DAYS_TOKEN: parts.get("duration_days") or "",
        WORK_STATUS_RTW_TOKEN: parts.get("return_to_work_date") or "",
        WORK_STATUS_PROVIDER_TOKEN: parts.get("provider_name") or "",
        WORK_STATUS_CLINIC_TOKEN: parts.get("clinic_name") or "",
        WORK_STATUS_EVAL_DATE_TOKEN: parts.get("eval_date") or "",
    }
    out = text
    for token, val in mapping.items():
        out = out.replace(token, val)
    return out.replace("\r\n", "\n")


def factory_work_status_letter_text(payload: dict) -> str:
    parts = work_status_letter_dynamic_parts(payload)
    template = f"""RE: {WORK_STATUS_LETTER_TITLE}

Patient Name: {WORK_STATUS_PATIENT_NAME_TOKEN}

Date of Injury/Incident: {WORK_STATUS_DOI_TOKEN}

Mechanism of Injury: {WORK_STATUS_INCIDENT_TOKEN}

To Whom It May Concern,

Please be advised that the above-named patient is currently undergoing active clinical management under my care for injuries sustained in {WORK_STATUS_INCIDENT_TOKEN} on {WORK_STATUS_DOI_TOKEN}.

Following a comprehensive physical evaluation and review of the patient's objective clinical findings, it has been determined that the patient's current functional capacity is restricted. To facilitate proper healing and prevent further exacerbation of their condition, the following medical work status is mandated effective immediately:

Current Work Status: {WORK_STATUS_WORK_STATUS_TOKEN}

Duration of Status: {WORK_STATUS_DURATION_TOKEN} from the date of this evaluation.

Anticipated Return-to-Work Date: {WORK_STATUS_RTW_TOKEN}

The patient will be re-evaluated at the conclusion of this period to determine if an extension or modification of this status is clinically indicated.

Should you require further clarification regarding the patient's specific functional limitations, please contact my office directly.

Respectfully submitted,

{WORK_STATUS_PROVIDER_TOKEN}

{WORK_STATUS_CLINIC_TOKEN}"""
    return _apply_work_status_tokens(template, parts).strip()


def work_status_letter_from_template(template: str, payload: dict) -> str:
    tpl = (template or "").replace("\r\n", "\n")
    if not tpl.strip():
        return ""
    parts = work_status_letter_dynamic_parts(payload)
    return _apply_work_status_tokens(tpl, parts)


def work_status_letter_edited_to_template(edited_text: str, payload: dict) -> str:
    text = (edited_text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    parts = work_status_letter_dynamic_parts(payload)

    doi = parts.get("date_of_injury") or ""
    incident = parts.get("incident") or ""
    if incident and doi:
        text = text.replace(
            f"injuries sustained in {incident} on {doi}",
            f"injuries sustained in {WORK_STATUS_INCIDENT_TOKEN} on {WORK_STATUS_DOI_TOKEN}",
        )
    if incident:
        text = text.replace(
            f"injuries sustained in {incident}",
            f"injuries sustained in {WORK_STATUS_INCIDENT_TOKEN} on {WORK_STATUS_DOI_TOKEN}",
        )
    if doi:
        text = text.replace(f"Date of Injury/Incident: {doi}", f"Date of Injury/Incident: {WORK_STATUS_DOI_TOKEN}")
        text = text.replace(doi, WORK_STATUS_DOI_TOKEN)

    if incident:
        text = text.replace(f"Mechanism of Injury: {incident}", f"Mechanism of Injury: {WORK_STATUS_INCIDENT_TOKEN}")
        text = text.replace(f"injuries sustained in a {incident}", f"injuries sustained in {WORK_STATUS_INCIDENT_TOKEN} on {WORK_STATUS_DOI_TOKEN}")
        if incident in text:
            text = text.replace(incident, WORK_STATUS_INCIDENT_TOKEN)

    injury_type = (
        ((payload.get("soap") or {}).get("hoi_struct") or {}).get("type") or {}
    ).get("injury_type") or ""
    injury_type = (injury_type or "").strip()
    if injury_type and injury_type not in ("(none)", "") and injury_type in text:
        text = text.replace(injury_type, WORK_STATUS_INCIDENT_TOKEN)

    for legacy in (
        "the aforementioned incident",
        "aforementioned incident",
    ):
        if legacy in text:
            text = text.replace(legacy, WORK_STATUS_INCIDENT_TOKEN)

    patient_name = parts.get("patient_name") or ""
    if patient_name:
        text = text.replace(f"Patient Name: {patient_name}", f"Patient Name: {WORK_STATUS_PATIENT_NAME_TOKEN}")

    work_status = parts.get("work_status") or ""
    if work_status:
        text = text.replace(f"Current Work Status: {work_status}", f"Current Work Status: {WORK_STATUS_WORK_STATUS_TOKEN}")

    duration = parts.get("duration_label") or ""
    if duration:
        text = text.replace(f"Duration of Status: {duration}", f"Duration of Status: {WORK_STATUS_DURATION_TOKEN}")

    rtw = parts.get("return_to_work_date") or ""
    if rtw:
        text = text.replace(f"Anticipated Return-to-Work Date: {rtw}", f"Anticipated Return-to-Work Date: {WORK_STATUS_RTW_TOKEN}")

    provider = parts.get("provider_name") or ""
    if provider and provider in text:
        text = text.replace(provider, WORK_STATUS_PROVIDER_TOKEN)

    clinic = parts.get("clinic_name") or ""
    if clinic and clinic in text:
        text = text.replace(clinic, WORK_STATUS_CLINIC_TOKEN)

    return text.replace("\r\n", "\n")


def build_work_status_letter_pdf(
    path: str,
    payload: dict,
    editable_letter_text: str | None = None,
) -> bool:
    if not REPORTLAB_OK:
        return False
    if not work_status_letter_should_generate(payload):
        return False

    patient = payload.get("patient") or {}
    if not isinstance(patient, dict):
        patient = {}
    exam_date = normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy()
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

    letter_text = (editable_letter_text or "").replace("\r\n", "\n")
    if not letter_text.strip():
        letter_text = factory_work_status_letter_text(payload)

    try:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="WorkStatusLetterTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            spaceAfter=10,
            alignment=1,
        )
        if "WorkStatusLetterTitle" not in styles.byName:
            styles.add(title_style)
        body_style = ParagraphStyle(
            name="WorkStatusLetterBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            alignment=0,
            spaceAfter=0,
        )
        if "WorkStatusLetterBody" not in styles.byName:
            styles.add(body_style)

        story = []
        story.append(ExamStart(WORK_STATUS_LETTER_TITLE, patient_header, exam_date))
        story.append(Spacer(1, 0.22 * inch))
        story.append(Paragraph(xml_escape(WORK_STATUS_LETTER_TITLE), styles["WorkStatusLetterTitle"]))
        story.append(Spacer(1, 0.12 * inch))
        re_safe = xml_escape(re_line.strip()).replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{re_safe}</b>", styles["WorkStatusLetterBody"]))
        story.append(Spacer(1, 0.14 * inch))

        for line in letter_text.replace("\r\n", "\n").split("\n"):
            if not line.strip():
                story.append(Spacer(1, 0.12 * inch))
                continue
            low = line.strip().lower()
            if low.startswith("re:") or low.startswith("patient name:"):
                story.append(Paragraph(f"<b>{xml_escape(line.strip())}</b>", styles["WorkStatusLetterBody"]))
            else:
                story.append(Paragraph(xml_escape(line), styles["WorkStatusLetterBody"]))

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
