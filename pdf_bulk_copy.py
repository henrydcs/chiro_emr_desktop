# pdf_bulk_copy.py — copy all patient exam PDFs + vault letter PDFs to a backup folder.
from __future__ import annotations

import shutil
from pathlib import Path

from config import PATIENTS_ID_ROOT, PATIENT_SUBDIR_PDFS

_VAULT_SUBDIR = "vault"


def _pdfs_under(patient_folder: Path, subdir: str) -> list[Path]:
    root = patient_folder / subdir
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.pdf") if p.is_file()]


def copy_all_patient_pdfs(dest_dir: str | Path) -> dict:
    """
    Copy each patient's pdfs/ and vault/**/*.pdf into:
      {dest}/{patient_folder_name}/pdfs/...
      {dest}/{patient_folder_name}/vault/...
    Overwrites matching destination paths.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    summary = {
        "patients_scanned": 0,
        "patients_with_pdfs": 0,
        "files_copied": 0,
        "files_overwritten": 0,
        "errors": [],
    }

    root = Path(PATIENTS_ID_ROOT)
    if not root.is_dir():
        return summary

    for patient_folder in sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.name.lower(),
    ):
        summary["patients_scanned"] += 1
        sources = _pdfs_under(patient_folder, PATIENT_SUBDIR_PDFS) + _pdfs_under(
            patient_folder, _VAULT_SUBDIR
        )
        if not sources:
            continue
        summary["patients_with_pdfs"] += 1
        for src in sources:
            rel = src.relative_to(patient_folder)
            dst = dest / patient_folder.name / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                existed = dst.exists()
                shutil.copy2(src, dst)
                summary["files_copied"] += 1
                if existed:
                    summary["files_overwritten"] += 1
            except Exception as exc:
                summary["errors"].append(f"{src}: {exc}")

    return summary
