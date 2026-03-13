# utils.py
import os
import re
from datetime import datetime
from pathlib import Path

from config import (
    YEAR_CASES_ROOT,
    PATIENT_SUBDIR_EXAMS, PATIENT_SUBDIR_PDFS, PATIENT_SUBDIR_ROFS, PATIENT_SUBDIR_INFO,
    PATIENT_SUBDIR_IMAGING, PATIENT_SUBDIR_ATTORNEY, PATIENT_SUBDIR_BILLING, PATIENT_SUBDIR_MESSAGES,
    REGION_LABELS
)

def ensure_named_patient_folder(root: Path, pid: str, last: str, first: str) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    # Find existing folder (pid-only or already-named)
    current = find_patient_folder_by_id(root, pid)
    if current is None:
        current = root / pid
        current.mkdir(parents=True, exist_ok=True)

    last = (last or "").strip()
    first = (first or "").strip()

    # If no usable name yet, keep pid folder
    if not (last or first):
        return current

    desired_name = patient_folder_name(pid, last, first)
    desired = root / desired_name

    # Already correct
    if current.resolve() == desired.resolve():
        return current

    # If desired exists, use it
    if desired.exists():
        return desired

    try:
        current.rename(desired)
        return desired
    except Exception:
        return current


def find_patient_folder_by_id(root: Path, pid: str) -> Path | None:
    # exact match (old style)
    p = root / pid
    if p.exists():
        return p

    # new style: LAST_FIRST__...__PID
    for child in root.iterdir():
        if child.is_dir() and child.name.endswith(f"__{pid}"):
            return child

    return None


def safe_slug(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    t = re.sub(r"[^a-z0-9]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    return t

def normalize_mmddyyyy(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t):
        # normalize to 2-digit month/day to avoid folder churn like 1/1/2026 -> 01/01/2026
        try:
            dt = datetime.strptime(t, "%m/%d/%Y")
            return dt.strftime("%m/%d/%Y")
        except Exception:
            return t
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        try:
            dt = datetime.strptime(t, "%Y-%m-%d")
            return dt.strftime("%m/%d/%Y")
        except Exception:
            return t
    return t

def today_mmddyyyy() -> str:
    return datetime.now().strftime("%m/%d/%Y")

def to_last_first(last: str, first: str) -> str:
    last = (last or "").strip()
    first = (first or "").strip()
    if not last and not first:
        return ""
    if last and first:
        return f"{last}, {first}"
    return last or first

def ensure_year_root():
    os.makedirs(str(YEAR_CASES_ROOT), exist_ok=True)

def _date_for_folder(mmddyyyy_or_yyyy_mm_dd: str) -> str:
    """
    Convert MM/DD/YYYY (or YYYY-MM-DD) into YYYY-MM-DD for folder sorting.
    Uses normalize_mmddyyyy first to stabilize formats and prevent extra folders.
    """
    s = normalize_mmddyyyy(mmddyyyy_or_yyyy_mm_dd)  # normalize to MM/DD/YYYY if possible
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # fallback, still stable-ish
        return s.replace("/", "-").strip()
    
def patient_folder_name(pid: str, last: str, first: str) -> str:
    def clean(s: str) -> str:
        return safe_slug(s).replace("-", "_")

    last_c = clean(last) or "unknown"
    first_c = clean(first) or "unknown"

    return f"{last_c}_{first_c}__{pid}"


def ensure_patient_dirs(patient_root: str | os.PathLike):
    root = os.fspath(patient_root)  # converts Path -> str, leaves str alone

    os.makedirs(root, exist_ok=True)

    os.makedirs(os.path.join(root, PATIENT_SUBDIR_EXAMS), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_PDFS), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_ROFS), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_INFO), exist_ok=True)

    os.makedirs(os.path.join(root, PATIENT_SUBDIR_IMAGING), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_ATTORNEY), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_BILLING), exist_ok=True)
    os.makedirs(os.path.join(root, PATIENT_SUBDIR_MESSAGES), exist_ok=True)


def build_sentence(
    region_label: str,
    desc1: str,
    desc2: str,
    radic_symptom: str,
    radic_location: str,
    subject: str | None = None,
) -> str:
    """
    Builds a clean, non-duplicative subjective sentence.

    Region headers are handled elsewhere (UI / PDF).

    Parameters
    ----------
    region_label:
        Human-readable region label (e.g. "cervical spine").
    desc1, desc2:
        Primary / secondary pain descriptors.
    radic_symptom, radic_location:
        Radiculopathy selections.
    subject:
        Optional subject phrase, e.g. "John", "Mr. Smith", "John Smith",
        or "The patient". If not provided or blank, defaults to "The patient".
    """
    region = (region_label or "").strip().lower()
    subject = (subject or "").strip() or "The patient"

    # Lead sentence
    lead = f"{subject} reports symptoms in the {region}."

    # Pain descriptors (ensure each descriptor ends with "pain")
    raw = [
        (desc1 or "").strip(),
        (desc2 or "").strip(),
    ]
    raw = [d for d in raw if d and d not in ("(none)", "")]

    def _as_pain_phrase(s: str) -> str:
        t = (s or "").strip().lower()
        if not t:
            return ""
        if "pain" in t:
            return t
        return f"{t} pain"

    descriptors = [_as_pain_phrase(d) for d in raw if _as_pain_phrase(d)]

    if descriptors:
        if len(descriptors) == 1:
            pain_sentence = f"The patient describes those symptoms as {descriptors[0]}."
        else:
            pain_sentence = (
                f"The patient describes those symptoms as "
                f"{descriptors[0]} along with {descriptors[1]}."
            )
    else:
        pain_sentence = ""

    # Radiculopathy
    radic_sentence = ""
    if radic_symptom and radic_symptom != "None":
        rs = (radic_symptom or "").strip().lower()
        rl = (radic_location or "").strip().lower()
        if radic_location and radic_location != "(select)":
            radic_sentence = f"Associated symptoms of {rs} into the {rl} were also reported."
        else:
            radic_sentence = f"Associated symptoms of {rs} were also reported."

    return " ".join(s for s in (lead, pain_sentence, radic_sentence) if s)

def narrative_block_has_content(block: dict) -> bool:
    region = (block.get("region") or "").strip()
    narrative = (block.get("narrative") or "").strip()
    return (region in REGION_LABELS) and bool(narrative)
