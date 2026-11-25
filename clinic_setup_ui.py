# clinic_setup_ui.py — first-run prompt and the Clinics screen.
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from clinic_profile import (
    current_fields,
    layout_fields,
    mark_setup_skipped,
    needs_first_run_prompt,
    save_profile,
    using_custom_logo,
)

_BG = "#F4F6FA"
_CARD = "#FFFFFF"
_TEXT = "#0F172A"
_MUTED = "#6B7280"
_ACCENT = "#2563EB"


class ClinicForm(tk.Frame):
    """Editable clinic identity. Save writes this computer's profile only."""

    def __init__(self, master: tk.Misc, *, on_saved=None):
        super().__init__(master, bg=_CARD)
        self._on_saved = on_saved
        self._logo_source: str | None = None
        self._vars = {
            "clinic_name": tk.StringVar(),
            "clinic_addr": tk.StringVar(),
            "clinic_phone_fax": tk.StringVar(),
            "clinic_email": tk.StringVar(),
            "provider_name": tk.StringVar(),
            "provider_license": tk.StringVar(),
            "provider_npi": tk.StringVar(),
            "logo_width": tk.StringVar(),
            "logo_height": tk.StringVar(),
            "clinic_name_size": tk.StringVar(),
            "clinic_detail_size": tk.StringVar(),
            "logo_y_offset": tk.StringVar(),
        }
        self._logo_var = tk.StringVar()
        self._status_var = tk.StringVar()
        self._build()
        self.reload()

    def _build(self) -> None:
        rows = (
            ("clinic_name", "Clinic name"),
            ("clinic_addr", "Address"),
            ("clinic_phone_fax", "Phone / fax"),
            ("clinic_email", "Email"),
            ("provider_name", "Provider name"),
            ("provider_license", "License"),
            ("provider_npi", "NPI"),
        )
        for row, (key, label) in enumerate(rows):
            tk.Label(self, text=label, bg=_CARD, fg=_TEXT, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=4
            )
            width = 28 if key == "provider_npi" else 54
            ttk.Entry(self, textvariable=self._vars[key], width=width).grid(
                row=row, column=1, sticky="we", pady=4
            )
        logo_row = len(rows)
        tk.Label(self, text="Logo", bg=_CARD, fg=_TEXT, anchor="w").grid(
            row=logo_row, column=0, sticky="w", padx=(0, 12), pady=4
        )
        logo_line = tk.Frame(self, bg=_CARD)
        logo_line.grid(row=logo_row, column=1, sticky="w", pady=4)
        tk.Button(
            logo_line,
            text="Choose PNG…",
            command=self._choose_logo,
            relief="flat",
            bg=_ACCENT,
            fg="#FFFFFF",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left")
        tk.Label(logo_line, textvariable=self._logo_var, bg=_CARD, fg=_MUTED).pack(
            side="left", padx=(8, 0)
        )
        size_rows = (
            ("logo_width", "Logo width"),
            ("logo_height", "Logo height"),
            ("clinic_name_size", "Clinic name size"),
            ("clinic_detail_size", "Address, phone, and email size"),
            ("logo_y_offset", "Logo vertical shift"),
        )
        for offset, (key, label) in enumerate(size_rows, start=1):
            tk.Label(self, text=label, bg=_CARD, fg=_TEXT, anchor="w").grid(
                row=logo_row + offset, column=0, sticky="w", padx=(0, 12), pady=4
            )
            ttk.Entry(self, textvariable=self._vars[key], width=10).grid(
                row=logo_row + offset, column=1, sticky="w", pady=4
            )
        self.columnconfigure(1, weight=1)

    def reload(self) -> None:
        values = current_fields()
        values.update(layout_fields())
        for key, var in self._vars.items():
            var.set(values.get(key) or "")
        self._logo_source = None
        if using_custom_logo():
            self._logo_var.set("Custom logo saved on this computer")
        else:
            self._logo_var.set("Using the logo included with the program")
        self._status_var.set("")

    def _choose_logo(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Choose clinic logo",
            filetypes=[("PNG logo", "*.png")],
        )
        if not path:
            return
        self._logo_source = path
        self._logo_var.set(path)

    def save(self) -> bool:
        fields = {key: var.get() for key, var in self._vars.items()}
        try:
            save_profile(fields, self._logo_source)
        except ValueError as exc:
            messagebox.showinfo("Clinic setup", str(exc), parent=self.winfo_toplevel())
            return False
        except OSError as exc:
            messagebox.showerror("Clinic setup", str(exc), parent=self.winfo_toplevel())
            return False
        self._logo_source = None
        self.reload()
        self._status_var.set("Saved on this computer. The next report uses this clinic.")
        if self._on_saved:
            self._on_saved()
        return True

    @property
    def status_var(self) -> tk.StringVar:
        return self._status_var


class ClinicSetupPage(tk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=_BG)
        wrap = tk.Frame(self, bg=_BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(wrap, text="Clinic setup", bg=_BG, fg=_TEXT, font=("Segoe UI", 16, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            wrap,
            text="Name, address, phone, logo, and provider for this computer only.",
            bg=_BG,
            fg=_MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 12))
        card = tk.Frame(wrap, bg=_CARD, highlightbackground="#E5E7EB", highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=_CARD)
        inner.pack(fill="x", padx=16, pady=16)
        self.form = ClinicForm(inner)
        self.form.pack(fill="x")
        bar = tk.Frame(inner, bg=_CARD)
        bar.pack(fill="x", pady=(12, 0))
        tk.Button(
            bar,
            text="Save",
            command=self.form.save,
            relief="flat",
            bg=_ACCENT,
            fg="#FFFFFF",
            padx=16,
            pady=6,
            cursor="hand2",
        ).pack(side="left")
        tk.Label(bar, textvariable=self.form.status_var, bg=_CARD, fg=_MUTED).pack(
            side="left", padx=(12, 0)
        )

    def reload(self) -> None:
        self.form.reload()


def offer_first_run_clinic_setup(parent: tk.Misc) -> None:
    """Ask once, before the documents window, when this computer has no profile."""
    if not needs_first_run_prompt():
        return
    dlg = tk.Toplevel(parent)
    dlg.title("Clinic setup")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.configure(bg=_BG)
    dlg.resizable(False, False)

    outer = tk.Frame(dlg, bg=_BG)
    outer.pack(fill="both", expand=True, padx=18, pady=16)
    tk.Label(
        outer,
        text="Set up this computer's clinic",
        bg=_BG,
        fg=_TEXT,
        font=("Segoe UI", 14, "bold"),
    ).pack(anchor="w")
    tk.Label(
        outer,
        text="Reports printed on this computer use the name, address, phone, and logo you save here.",
        bg=_BG,
        fg=_MUTED,
        wraplength=520,
        justify="left",
    ).pack(anchor="w", pady=(4, 12))

    card = tk.Frame(outer, bg=_CARD, highlightbackground="#E5E7EB", highlightthickness=1)
    card.pack(fill="x")
    inner = tk.Frame(card, bg=_CARD)
    inner.pack(fill="x", padx=14, pady=14)
    form = ClinicForm(inner)
    form.pack(fill="x")

    def skip() -> None:
        try:
            mark_setup_skipped()
        except OSError as exc:
            messagebox.showerror("Clinic setup", str(exc), parent=dlg)
            return
        dlg.destroy()

    def save() -> None:
        if form.save():
            dlg.destroy()

    bar = tk.Frame(outer, bg=_BG)
    bar.pack(fill="x", pady=(12, 0))
    tk.Button(
        bar,
        text="Save",
        command=save,
        relief="flat",
        bg=_ACCENT,
        fg="#FFFFFF",
        padx=16,
        pady=6,
        cursor="hand2",
    ).pack(side="left")
    tk.Button(
        bar,
        text="Skip for now",
        command=skip,
        relief="flat",
        bg=_CARD,
        fg=_TEXT,
        padx=12,
        pady=6,
        cursor="hand2",
    ).pack(side="left", padx=(8, 0))
    tk.Label(
        bar,
        text="Skip keeps the clinic information already in the program.",
        bg=_BG,
        fg=_MUTED,
    ).pack(side="left", padx=(12, 0))

    dlg.update_idletasks()
    parent.update_idletasks()
    px = parent.winfo_rootx() + max(0, (parent.winfo_width() - dlg.winfo_width()) // 2)
    py = parent.winfo_rooty() + max(0, (parent.winfo_height() - dlg.winfo_height()) // 2)
    dlg.geometry(f"+{px}+{py}")
    dlg.protocol("WM_DELETE_WINDOW", skip)
    parent.wait_window(dlg)
