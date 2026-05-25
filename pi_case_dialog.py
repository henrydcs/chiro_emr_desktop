# pi_case_dialog.py — Edit PI case metadata.
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from billing_pi_case import case_status_label, load_pi_case, save_pi_case, sync_pi_case_from_chart
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    make_card,
)


class PiCaseEditorDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, patient_root: str, patient_id: str = "", on_saved=None):
        super().__init__(parent)
        self.patient_root = patient_root
        self.patient_id = patient_id
        self.on_saved = on_saved
        self.title("PI case")
        self.geometry("520x480")
        self.minsize(480, 400)
        self.configure(bg=COLOR_BG_APP)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._case = load_pi_case(patient_root) or sync_pi_case_from_chart(
            patient_root, patient_id=patient_id
        )

        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        card, body = make_card(outer, "Case information")
        card.pack(fill="both", expand=True)

        row = 0
        for label, var_name in [
            ("Date of injury", "doi_var"),
            ("Claim number", "claim_var"),
            ("Case status", "status_var"),
            ("Attorney name", "atty_name_var"),
            ("Law firm", "atty_firm_var"),
            ("Notes", "notes_var"),
        ]:
            tk.Label(body, text=label, bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).grid(
                row=row, column=0, sticky="nw", pady=6, padx=(0, 8)
            )
            row += 1

        atty = self._case.get("attorney") or {}
        self.doi_var = tk.StringVar(value=self._case.get("date_of_injury") or "")
        self.claim_var = tk.StringVar(value=self._case.get("claim_number") or "")
        self.status_var = tk.StringVar(value=self._case.get("case_status") or "active")
        self.atty_name_var = tk.StringVar(value=atty.get("name") or "")
        self.atty_firm_var = tk.StringVar(value=atty.get("firm") or "")
        self.notes_var = tk.StringVar(value=self._case.get("notes") or "")

        ttk.Entry(body, textvariable=self.doi_var, width=28).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Entry(body, textvariable=self.claim_var, width=28).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Combobox(
            body,
            textvariable=self.status_var,
            values=["active", "settled", "closed"],
            state="readonly",
            width=26,
        ).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Entry(body, textvariable=self.atty_name_var, width=28).grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Entry(body, textvariable=self.atty_firm_var, width=28).grid(row=4, column=1, sticky="ew", pady=6)
        notes = tk.Text(body, height=5, width=32, font=FONT_BASE)
        notes.grid(row=5, column=1, sticky="ew", pady=6)
        notes.insert("1.0", self._case.get("notes") or "")
        self._notes_widget = notes
        body.columnconfigure(1, weight=1)

        carriers = self._case.get("carriers") or []
        tk.Label(
            body,
            text="Carriers (from insurance)",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=FONT_BASE_BOLD,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
        car_txt = "\n".join(
            f"• {c.get('type_label')}: {c.get('carrier_name')} — {c.get('claim_number') or 'no claim #'}"
            for c in carriers
            if isinstance(c, dict)
        ) or "(Add auto PIP/Med-Pay/Liability policies in patient insurance.)"
        tk.Label(body, text=car_txt, bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE, justify="left").grid(
            row=7, column=0, columnspan=2, sticky="w"
        )

        btn_row = tk.Frame(outer, bg=COLOR_BG_APP)
        btn_row.pack(fill="x", pady=(12, 0))
        tk.Button(
            btn_row,
            text="Sync from chart",
            command=self._sync,
            relief="flat",
            fg=COLOR_ACCENT,
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="left")
        tk.Button(
            btn_row,
            text="Save",
            command=self._save,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=14,
            cursor="hand2",
        ).pack(side="right")
        tk.Button(btn_row, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(
            side="right", padx=(0, 8)
        )

    def _sync(self) -> None:
        self._case = sync_pi_case_from_chart(self.patient_root, patient_id=self.patient_id)
        atty = self._case.get("attorney") or {}
        self.doi_var.set(self._case.get("date_of_injury") or "")
        self.claim_var.set(self._case.get("claim_number") or "")
        self.status_var.set(self._case.get("case_status") or "active")
        self.atty_name_var.set(atty.get("name") or "")
        self.atty_firm_var.set(atty.get("firm") or "")
        messagebox.showinfo(
            "Synced",
            "DOI, claim, attorney, and carriers refreshed from patient chart.",
            parent=self,
        )

    def _save(self) -> None:
        atty = dict(self._case.get("attorney") or {})
        atty["name"] = (self.atty_name_var.get() or "").strip()
        atty["firm"] = (self.atty_firm_var.get() or "").strip()
        self._case["date_of_injury"] = (self.doi_var.get() or "").strip()
        self._case["claim_number"] = (self.claim_var.get() or "").strip()
        self._case["case_status"] = (self.status_var.get() or "active").strip()
        self._case["attorney"] = atty
        self._case["notes"] = self._notes_widget.get("1.0", "end-1c").strip()
        save_pi_case(self.patient_root, self._case)
        if self.on_saved:
            self.on_saved(self._case)
        messagebox.showinfo(
            "Saved",
            f"PI case saved ({case_status_label(self._case.get('case_status') or '')}).",
            parent=self,
        )
        self.destroy()
