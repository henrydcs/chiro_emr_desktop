# closeout_dialog.py — Phase 4 attorney packet builder UI.
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from billing_closeout import build_attorney_packet, open_packet_folder
from billing_case_export import save_case_exports
from billing_pi_case import load_pi_case, save_pi_case
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    make_card,
)


class CloseoutDialog(tk.Toplevel):
    """Build a full attorney/carrier billing packet for case close-out."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        patient_name: str,
        on_complete=None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.patient_name = patient_name
        self.on_complete = on_complete
        self.title("Admin close-out — Attorney packet")
        self.geometry("520x480")
        self.minsize(480, 420)
        self.configure(bg=COLOR_BG_APP)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            outer,
            text="Build attorney packet",
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_SECTION,
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="Assembles cover sheet, ledger summary, superbill, clinical PDFs, and vault documents.",
            bg=COLOR_BG_APP,
            fg=COLOR_MUTED,
            font=FONT_BASE,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        card, body = make_card(outer, "Options")
        card.pack(fill="both", expand=True)

        row = 0
        ttk.Label(body, text="From DOS (MM/DD/YYYY)").grid(row=row, column=0, sticky="w", pady=6)
        self.from_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.from_var, width=14).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(body, text="To DOS (MM/DD/YYYY)").grid(row=row, column=0, sticky="w", pady=6)
        self.to_var = tk.StringVar()
        ttk.Entry(body, textvariable=self.to_var, width=14).grid(row=row, column=1, sticky="w")
        row += 1

        self.inc_clinical = tk.BooleanVar(value=True)
        self.inc_attorney = tk.BooleanVar(value=True)
        self.inc_billing = tk.BooleanVar(value=True)
        self.inc_liens = tk.BooleanVar(value=True)
        self.mark_settled = tk.BooleanVar(value=False)

        for label, var in [
            ("Include clinical exam PDFs (date range)", self.inc_clinical),
            ("Include vault — Attorney folder", self.inc_attorney),
            ("Include vault — Billing folder", self.inc_billing),
            ("Include vault — Doctors on Liens", self.inc_liens),
        ]:
            ttk.Checkbutton(body, text=label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=4
            )
            row += 1
        ttk.Checkbutton(
            body,
            text="Mark PI case status as Settled after build",
            variable=self.mark_settled,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        btn_row = tk.Frame(outer, bg=COLOR_BG_APP)
        btn_row.pack(fill="x", pady=(14, 0))
        tk.Button(
            btn_row,
            text="Build packet folder",
            command=self._build_packet,
            bg="#7C3AED",
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn_row,
            text="Quick export (TXT+CSV only)",
            command=self._quick_export,
            bg=COLOR_CARD,
            fg=COLOR_ACCENT,
            relief="flat",
            font=FONT_BASE,
            highlightthickness=1,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(
            side="right"
        )

    def _build_packet(self) -> None:
        try:
            packet_dir = build_attorney_packet(
                patient_root=self.patient_root,
                patient_name=self.patient_name,
                date_from=self.from_var.get().strip(),
                date_to=self.to_var.get().strip(),
                include_clinical_pdfs=self.inc_clinical.get(),
                include_vault_attorney=self.inc_attorney.get(),
                include_vault_billing=self.inc_billing.get(),
                include_vault_liens=self.inc_liens.get(),
            )
        except Exception as e:
            messagebox.showerror("Packet failed", str(e), parent=self)
            return
        if self.mark_settled.get():
            case = load_pi_case(self.patient_root) or {}
            case["case_status"] = "settled"
            save_pi_case(self.patient_root, case)
        n_files = len(list(packet_dir.rglob("*")))
        if messagebox.askyesno(
            "Packet ready",
            f"Attorney packet created:\n{packet_dir}\n\n"
            f"({n_files} items)\n\nOpen folder now?",
            parent=self,
        ):
            try:
                open_packet_folder(packet_dir)
            except Exception as e:
                messagebox.showwarning("Open folder", str(e), parent=self)
        if self.on_complete:
            try:
                self.on_complete()
            except Exception:
                pass
        self.destroy()

    def _quick_export(self) -> None:
        try:
            txt_p, csv_p = save_case_exports(
                self.patient_root,
                patient_name=self.patient_name,
                date_from=self.from_var.get().strip(),
                date_to=self.to_var.get().strip(),
            )
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self)
            return
        messagebox.showinfo(
            "Exported",
            f"Summary:\n{txt_p}\n\nSuperbill CSV:\n{csv_p}",
            parent=self,
        )
        if self.on_complete:
            try:
                self.on_complete()
            except Exception:
                pass
