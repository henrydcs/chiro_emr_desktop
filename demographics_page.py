# demographics_page.py — Shell hub for Patients, Insurance, and Attorneys.
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from attorney_demographics import AttorneyDemographicsPanel
from insurance_demographics import InsuranceDemographicsPanel
from shell_app import (
    COLOR_BG_APP,
    COLOR_CARD,
    COLOR_SIDEBAR_ACTIVE_BG,
    COLOR_SIDEBAR_ACTIVE_FG,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_TITLE,
    PatientsPage,
    patient_record_from_folder,
    read_shell_state,
)


class DemographicsPage(tk.Frame):
    """Patients registry plus embedded insurance and attorney demographics."""

    _SUB_TABS: tuple[tuple[str, str], ...] = (
        ("patients", "Patients"),
        ("insurance", "Insurance"),
        ("attorneys", "Attorneys"),
    )

    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self._active_tab = "patients"
        self._tab_btns: dict[str, tk.Button] = {}
        self._panels: dict[str, tk.Frame] = {}
        self._built: set[str] = set()

        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=20, pady=20)

        header = tk.Frame(outer, bg=COLOR_BG_APP)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(
            header,
            text="Demographics",
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_TITLE,
        ).pack(side="left")

        nav_row = tk.Frame(outer, bg=COLOR_BG_APP)
        nav_row.pack(fill="x", pady=(0, 12))
        for key, label in self._SUB_TABS:
            btn = tk.Button(
                nav_row,
                text=label,
                command=lambda k=key: self.show_subtab(k),
                bg=COLOR_CARD,
                fg=COLOR_TEXT,
                relief="flat",
                font=FONT_BASE,
                padx=12,
                pady=6,
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = btn

        self._content = tk.Frame(outer, bg=COLOR_BG_APP)
        self._content.pack(fill="both", expand=True)

        self.show_subtab("patients")
        self.bind("<Map>", lambda _e: self.refresh(), add="+")

    def _shell_patient_info(self) -> dict | None:
        """Patient snapshot for insurance / attorney panels."""
        rec: dict | None = None

        doc = getattr(self.shell, "documents_page", None)
        if doc and doc.active_patient:
            rec = doc.active_patient

        if not rec:
            state = read_shell_state()
            folder = (state.get("active_patient_folder") or "").strip()
            if folder:
                rec = patient_record_from_folder(Path(folder))

        if not rec:
            patients_page = self._panels.get("patients")
            if isinstance(patients_page, PatientsPage):
                selected = getattr(patients_page, "_selected_rec", None)
                if selected:
                    rec = selected

        if not rec:
            return None

        folder = (rec.get("folder") or "").strip()
        if not folder:
            return None

        return {
            "patient_id": (rec.get("patient_id") or "").strip(),
            "patient_name": (rec.get("label") or "").strip(),
            "patient_root": folder,
            "current_exam": "",
        }

    def _ensure_panel(self, tab: str) -> None:
        if tab in self._built:
            return

        if tab == "patients":
            panel = PatientsPage(self._content, self.shell)
        elif tab == "insurance":
            has_patient = bool(self._shell_patient_info())
            start = "patient" if has_patient else "directory"
            panel = InsuranceDemographicsPanel(
                self._content,
                start_tab=start,
                get_current_patient_fn=self._shell_patient_info,
                shell_theme=True,
            )
        elif tab == "attorneys":
            has_patient = bool(self._shell_patient_info())
            start = "patient" if has_patient else "directory"
            panel = AttorneyDemographicsPanel(
                self._content,
                start_tab=start,
                get_current_patient_fn=self._shell_patient_info,
                shell_theme=True,
            )
        else:
            return

        self._panels[tab] = panel
        self._built.add(tab)

    def show_subtab(self, tab: str) -> None:
        if tab not in dict(self._SUB_TABS):
            return
        self._active_tab = tab
        self._ensure_panel(tab)

        for panel in self._panels.values():
            panel.pack_forget()
        self._panels[tab].pack(fill="both", expand=True)

        for key, btn in self._tab_btns.items():
            if key == tab:
                btn.configure(
                    bg=COLOR_SIDEBAR_ACTIVE_BG,
                    fg=COLOR_SIDEBAR_ACTIVE_FG,
                    font=FONT_BASE_BOLD,
                )
            else:
                btn.configure(bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE)

        if tab == "patients":
            page = self._panels.get("patients")
            if isinstance(page, PatientsPage):
                try:
                    page._on_page_shown()
                except Exception:
                    pass
        elif tab in ("insurance", "attorneys"):
            panel = self._panels.get(tab)
            if panel is not None:
                try:
                    panel._refresh_all()
                except Exception:
                    pass

    def refresh(self) -> None:
        """Re-sync when the page becomes visible."""
        self.show_subtab(self._active_tab)
