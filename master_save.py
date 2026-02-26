# master_save.py
from __future__ import annotations

import os
from contextlib import contextmanager
from tkinter import messagebox

from utils import safe_slug
from config import PATIENT_SUBDIR_PDFS


class MasterSaveController:
    """
    Master Save is intentionally isolated from App logic.

    It calls App's existing methods:
      - app.save_case_now()
      - app.export_current_exam_to_pdf_overwrite()

    Goal:
      - one click saves JSON (overwrites)
      - one click updates/overwrites the PDF
      - prevents PDF duplicates even when demographics change
      - shows ONE summary popup at the end
      - does NOT rewrite App’s save/export functions
    """

    def __init__(self, app):
        self.app = app

    # -----------------------------
    # Popup silencing (safe)
    # -----------------------------
    @contextmanager
    def _silence_info_warning(self):
        """
        Silence ONLY informational popups so Master Save can show ONE final summary.

        We do NOT touch askyesno, because other parts of the app may rely on it.
        We also do NOT silence showerror so failures are still visible.
        """
        orig_showinfo = messagebox.showinfo
        orig_showwarning = messagebox.showwarning
        try:
            messagebox.showinfo = lambda *a, **k: None
            messagebox.showwarning = lambda *a, **k: None
            yield
        finally:
            messagebox.showinfo = orig_showinfo
            messagebox.showwarning = orig_showwarning

    # -----------------------------
    # PDF cleanup to prevent duplicates
    # -----------------------------
    def _remove_existing_exam_pdfs(self, patient_root: str) -> int:
        """
        Deletes existing PDFs for the CURRENT exam in patient_root/pdfs/.
        This prevents duplicates when name/DOB/DOI changes (which affects filename).

        Returns number of deleted files.
        """
        pdf_dir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)
        if not os.path.isdir(pdf_dir):
            return 0

        exam = (self.app.current_exam.get() or "").strip()
        exam_slug = safe_slug(exam).lower()

        deleted = 0
        try:
            for fn in os.listdir(pdf_dir):
                low = fn.lower()
                # exporter uses: "{exam_slug}_<display>_DOB_<dob>_DOI_<doi>.pdf"
                if low.endswith(".pdf") and low.startswith(exam_slug + "_"):
                    try:
                        os.remove(os.path.join(pdf_dir, fn))
                        deleted += 1
                    except Exception:
                        pass
        except Exception:
            pass

        return deleted

    # -----------------------------
    # Main action
    # -----------------------------
    def run(self):
        app = self.app
        exam = (app.current_exam.get() or "").strip() or "Exam"

        # 1) Save JSON first (App handles correct folder naming/renaming)
        with self._silence_info_warning():
            try:
                app.save_case_now()
            except Exception as e:
                messagebox.showerror("Master Save", f"JSON save failed:\n\n{e}")
                return

        # 2) After save, compute the REAL current paths
        json_path = app.compute_exam_path()
        if not json_path:
            messagebox.showerror("Master Save", "Could not compute JSON path after save.")
            return

        patient_root = app.get_current_patient_root()
        if not patient_root:
            messagebox.showerror("Master Save", "Could not compute patient folder after save.")
            return

        # Determine whether a PDF existed before we export (for messaging)
        pdf_existed_before = False
        pdf_dir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)
        if os.path.isdir(pdf_dir):
            exam_slug = safe_slug(exam).lower()
            try:
                pdf_existed_before = any(
                    fn.lower().endswith(".pdf") and fn.lower().startswith(exam_slug + "_")
                    for fn in os.listdir(pdf_dir)
                )
            except Exception:
                pdf_existed_before = False

        # 3) Delete old exam PDFs (prevents duplicates), then export ONCE
        pdf_error = None
        deleted_count = 0

        with self._silence_info_warning():
            try:
                deleted_count = self._remove_existing_exam_pdfs(patient_root)
                app.export_current_exam_to_pdf_overwrite()
            except Exception as e:
                pdf_error = str(e)

        saved_pdf_path = ""
        try:
            saved_pdf_path = app.last_exam_pdf_paths.get(app.current_exam.get(), "") or ""
        except Exception:
            saved_pdf_path = ""

        # 4) One summary popup
        lines = [
            f"Exam: {exam}",
            "",
            "JSON: saved",
            f"  {json_path}",
            "",
        ]

        if pdf_error:
            lines += [
                "PDF: failed",
                f"  {pdf_error}",
            ]
        else:
            # If we deleted any, we definitely replaced/updated
            status = "updated" if (pdf_existed_before or deleted_count > 0) else "created"
            lines += [
                f"PDF: {status}",
                f"  {saved_pdf_path or '(unknown path)'}",
            ]

        messagebox.showinfo("Master Save", "\n".join(lines))