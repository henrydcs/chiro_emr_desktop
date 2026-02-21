from __future__ import annotations

import json
from pathlib import Path

# Fallback location if settings_local.json is missing or broken
#DEFAULT_DATA_DIR = r"C:\EMR_Data\EMR"
DEFAULT_DATA_DIR = r"C:\EMR_Data\HOME"


def get_data_dir() -> Path:
    """
    Returns the base PHI-safe data directory.
    Reads settings_local.json from the repo root.
    """
    repo_root = Path(__file__).resolve().parent
    settings_path = repo_root / "settings_local.json"

    data_dir = DEFAULT_DATA_DIR

    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            data_dir = cfg.get("DATA_DIR", data_dir)
        except Exception:
            # If the file exists but is malformed, fall back safely
            pass

    base = Path(data_dir)

    # Ensure required subfolders exist
    (base / "patients").mkdir(parents=True, exist_ok=True)
    (base / "exports").mkdir(parents=True, exist_ok=True)
    (base / "uploads").mkdir(parents=True, exist_ok=True)
    (base / "db").mkdir(parents=True, exist_ok=True)

    return base


def patients_dir() -> Path:
    """Root folder for patient/case data"""
    return get_data_dir() / "patients"


def exports_dir() -> Path:
    """Root folder for generated PDFs"""
    return get_data_dir() / "exports"


def uploads_dir() -> Path:
    """Root folder for imaging and document uploads"""
    return get_data_dir() / "uploads"


def db_dir() -> Path:
    """Root folder for SQLite databases"""
    return get_data_dir() / "db"
