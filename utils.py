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

def ensure_named_patient_folder(root: Path, pid: str, last: str, first: str, dob: str = "") -> Path:
    """
    Ensures a patient folder exists. If demographics are available, renames the folder
    to a name-based format for alphabetized browsing.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    # Find existing folder (pid-only or already-named)
    current = find_patient_folder_by_id(root, pid)
    if current is None:
        current = root / pid
        current.mkdir(parents=True, exist_ok=True)

    # If no usable name yet, keep pid folder
    last = (last or "").strip()
    first = (first or "").strip()
    dob = (dob or "").strip()
    if not (last or first):
        return current

    # Desired alphabetized folder name
    desired_name = patient_folder_name(pid, last, first, dob)
    desired = root / desired_name

    # Already correct
    if current.resolve() == desired.resolve():
        return current

    # If a folder with the desired name already exists, use it
    if desired.exists():
        return desired

    # Rename
    try:
        current.rename(desired)
        return desired
    except Exception:
        # Fallback: if rename fails, keep using current
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

def patient_folder_name(pid: str, last: str, first: str, dob: str = "") -> str:
    def clean(s: str) -> str:
        return safe_slug(s).replace("-", "_")

    last_c = clean(last)
    first_c = clean(first)

    dob_c = (dob or "").strip()
    dob_part = f"DOB_{clean(dob_c)}" if dob_c else "DOB_unknown"

    # ✅ alphabetizes by last name
    return f"{last_c}_{first_c}__{dob_part}__{pid}"


# def get_patient_root_dir(last: str, first: str, dob: str, doi: str) -> str | None:
#     ensure_year_root()

#     last = (last or "").strip()
#     first = (first or "").strip()

#     dob_n = normalize_mmddyyyy(dob)
#     doi_n = normalize_mmddyyyy(doi)

#     # Require all fields
#     if not (last and first and dob_n and doi_n):
#         return None

#     # Require DOB/DOI to be REAL dates so the folder name won't change later
#     try:
#         datetime.strptime(dob_n, "%m/%d/%Y")
#         datetime.strptime(doi_n, "%m/%d/%Y")
#     except Exception:
#         return None

#     folder = patient_folder_name(last, first, dob_n, doi_n)
#     return os.path.join(str(YEAR_CASES_ROOT), folder)



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


def build_sentence(region_label: str,
                   desc1: str,
                   desc2: str,
                   radic_symptom: str,
                   radic_location: str) -> str:
    """
    Builds a clean, non-duplicative subjective sentence.
    Region headers are handled elsewhere (UI / PDF).
    """

    region = (region_label or "").strip().lower()

    # Lead sentence (NEW)
    lead = f"The patient reports symptoms in the {region}."

    # Pain descriptors (ensure each descriptor ends with "pain")
    raw = [
        d.strip()
        for d in (desc1, desc2)
        if d and d not in ("(none)", "")
    ]

    def _as_pain_phrase(s: str) -> str:
        t = s.strip().lower()
        if not t:
            return ""
        # If the descriptor already contains "pain", keep it
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
        pain_sentence = "The patient describes the pain."

    # Radiculopathy
    radic_sentence = ""
    if radic_symptom and radic_symptom != "None":
        if radic_location and radic_location != "(select)":
            radic_sentence = (
                f"The patient complains of {radic_symptom.lower()} "
                f"into the {radic_location.lower()}."
            )
        else:
            radic_sentence = f"The patient complains of {radic_symptom.lower()}."

    return " ".join(s for s in (lead, pain_sentence, radic_sentence) if s)

def narrative_block_has_content(block: dict) -> bool:
    region = (block.get("region") or "").strip()
    narrative = (block.get("narrative") or "").strip()
    return (region in REGION_LABELS) and bool(narrative)
