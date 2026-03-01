# patient_storage.py
"""
Centralized patient ID generation and patient folder path logic.
All patient/case paths and ID generation go through this module so
storage layout and behavior stay consistent. Folder naming remains
{last}_{first}__{patient_id} via utils.ensure_named_patient_folder.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from config import PATIENTS_ID_ROOT
from utils import ensure_named_patient_folder, find_patient_folder_by_id


def new_patient_id() -> str:
    """Generate a unique, stable patient ID (timestamp + short uuid)."""
    return datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]


def get_patient_root(patient_id: str, last: str = "", first: str = "") -> Path:
    """
    Return the filesystem path for this patient's folder.
    Creates the folder if needed; renames to {last}_{first}__{patient_id} when names are set.
    Compatible with existing id_cases layout.
    """
    root = Path(PATIENTS_ID_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return ensure_named_patient_folder(root, patient_id, (last or "").strip(), (first or "").strip())


def find_patient_root(patient_id: str) -> Path | None:
    """
    Find the existing folder for this patient_id (exact pid or *__pid).
    Returns None if not found.
    """
    if not (patient_id or "").strip():
        return None
    return find_patient_folder_by_id(Path(PATIENTS_ID_ROOT), patient_id.strip())
