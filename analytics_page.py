# analytics_page.py — Patient status sheet (printable PDF).
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from shell_app import (
    COLOR_BG_APP,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_TITLE,
    collect_visits_for_patient,
    list_all_patients,
)


class AnalyticsPage(tk.Frame):
    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell

        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=20, pady=(16, 12))

        tk.Label(
            outer,
            text="Analytics",
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_TITLE,
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            outer,
            text=(
                "Generates a landscape patient status sheet from Encounters data "
                "(Initial, first Re-Exam, and last Final dates; chiropractic visits omitted). "
                "Status checkboxes are blank for manual marking on the printed copy."
            ),
            bg=COLOR_BG_APP,
            fg=COLOR_MUTED,
            font=FONT_BASE,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        tk.Button(
            outer,
            text="Print Patient Status",
            command=self._print_patient_status,
            font=FONT_BASE,
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(anchor="w")

    def _print_patient_status(self) -> None:
        try:
            from patient_status_pdf import (
                REPORTLAB_OK,
                build_patient_status_pdf,
                build_patient_status_rows,
                canonical_pdf_path,
            )
        except Exception as e:
            messagebox.showerror(
                "Print Patient Status",
                f"Could not load PDF generator:\n\n{e}",
                parent=self,
            )
            return

        if not REPORTLAB_OK:
            messagebox.showerror(
                "Print Patient Status",
                "ReportLab is not installed. Install with:\n\npip install reportlab",
                parent=self,
            )
            return

        try:
            patients = list_all_patients()
            rows = build_patient_status_rows(
                patients,
                collect_visits=collect_visits_for_patient,
            )
            out = canonical_pdf_path()
            build_patient_status_pdf(out, rows=rows)
        except Exception as e:
            messagebox.showerror(
                "Print Patient Status",
                f"Could not build PDF:\n\n{e}",
                parent=self,
            )
            return

        path = str(out.resolve())
        try:
            self._print_pdf(path)
        except Exception as e:
            messagebox.showerror(
                "Print Patient Status",
                f"PDF saved to:\n{path}\n\nCould not open print dialog:\n{e}",
                parent=self,
            )
            return

        messagebox.showinfo(
            "Print Patient Status",
            f"Sent to the system print dialog.\n\nSaved copy:\n{path}",
            parent=self,
        )

    @staticmethod
    def _print_pdf(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path, "print")  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["lpr", path])
        else:
            subprocess.Popen(["lpr", path])
