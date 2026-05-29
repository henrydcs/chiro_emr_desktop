# appt_types_page.py — Manage appointment types (aligned with SOAP exam types).
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from appt_types_storage import (
    EXAM_TYPE_LABELS,
    list_appt_types,
    reset_appt_types_to_defaults,
    upsert_appt_type,
)
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    make_card,
)


class ApptTypesPage(tk.Frame):
    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self._build()
        self.bind("<Map>", lambda _e: self.refresh(), add="+")
        self.refresh()

    def _build(self) -> None:
        wrap = tk.Frame(self, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(wrap, text="Appointment types", bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=FONT_TITLE).pack(anchor="w")
        tk.Label(
            wrap,
            text="Schedule types mirror SOAP exam categories (Initial, Re-Exam, ROF, Chiro Visit, Final, etc.).",
            bg=COLOR_BG_APP, fg=COLOR_MUTED, font=FONT_BASE,
        ).pack(anchor="w", pady=(4, 14))

        card, body = make_card(wrap, "Types catalog", "Used in Schedule → New appointment")
        card.pack(fill="both", expand=True)
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)

        toolbar = tk.Frame(body, bg=COLOR_CARD)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Button(
            toolbar, text="Add type", command=self._add_type,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=5, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            toolbar, text="Edit", command=self._edit_selected,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            toolbar, text="Reset defaults", command=self._reset_defaults,
            bg=COLOR_CARD, fg=COLOR_MUTED, relief="flat",
            font=FONT_BASE, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="left")
        tk.Button(
            toolbar, text="Refresh", command=self.refresh,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=FONT_BASE, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="right")

        tree_wrap = tk.Frame(body, bg=COLOR_CARD)
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        cols = ("label", "exam", "duration", "active", "color")
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=12)
        for col, title, width in [
            ("label", "Appointment type", 180),
            ("exam", "Exam category", 160),
            ("duration", "Default min", 90),
            ("active", "Active", 70),
            ("color", "Color", 90),
        ]:
            self.tree.heading(col, text=title, anchor="center")
            self.tree.column(col, width=width, anchor="center")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit_selected())

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in list_appt_types():
            exam_key = (row.get("exam_type") or "").strip()
            exam_label = EXAM_TYPE_LABELS.get(exam_key, exam_key or "—")
            active = "Yes" if row.get("active", True) else "No"
            self.tree.insert(
                "",
                "end",
                iid=row.get("type_id") or "",
                values=(
                    row.get("label") or "",
                    exam_label,
                    str(int(row.get("duration_min") or 15)),
                    active,
                    (row.get("color_bg") or "")[:7],
                ),
            )

    def _selected_type_id(self) -> str:
        sel = self.tree.selection()
        return str(sel[0]) if sel else ""

    def _selected_row(self) -> dict | None:
        tid = self._selected_type_id()
        if not tid:
            return None
        for row in list_appt_types():
            if (row.get("type_id") or "") == tid:
                return dict(row)
        return None

    def _add_type(self) -> None:
        label = simpledialog.askstring("Add appointment type", "Type name:", parent=self)
        if not label or not label.strip():
            return
        label = label.strip()
        upsert_appt_type({
            "label": label,
            "exam_type": "chiro",
            "duration_min": 15,
            "color_bg": "#F3F4F6",
            "color_fg": "#374151",
            "active": True,
            "builtin": False,
        })
        self.refresh()

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if not row:
            messagebox.showinfo("Edit", "Select a type first.", parent=self)
            return
        ApptTypeEditDialog(self, row=row, on_saved=lambda _r: self.refresh())

    def _reset_defaults(self) -> None:
        if not messagebox.askyesno(
            "Reset defaults",
            "Restore the built-in exam-aligned appointment types?\n\nCustom types will be removed.",
            parent=self,
        ):
            return
        reset_appt_types_to_defaults()
        self.refresh()


class ApptTypeEditDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, *, row: dict, on_saved: callable | None = None):
        super().__init__(master)
        self.title("Edit appointment type")
        self.configure(bg=COLOR_CARD)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.resizable(False, False)
        self._row = dict(row)
        self._on_saved = on_saved

        wrap = tk.Frame(self, bg=COLOR_CARD, padx=16, pady=14)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="Edit type", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE_BOLD).pack(anchor="w", pady=(0, 10))

        tk.Label(wrap, text="Label", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(anchor="w")
        self._label_var = tk.StringVar(value=row.get("label") or "")
        name_state = "normal" if not row.get("builtin") else "disabled"
        tk.Entry(
            wrap, textvariable=self._label_var, font=FONT_BASE,
            state=name_state, relief="solid", bd=1,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        ).pack(fill="x", ipady=4, pady=(2, 8))

        tk.Label(wrap, text="Exam category", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(anchor="w")
        exam_labels = list(EXAM_TYPE_LABELS.values())
        exam_key = (row.get("exam_type") or "chiro").strip()
        self._exam_key_by_label = {v: k for k, v in EXAM_TYPE_LABELS.items()}
        self._exam_var = tk.StringVar(value=EXAM_TYPE_LABELS.get(exam_key, "Chiro Visit"))
        ttk.Combobox(
            wrap, textvariable=self._exam_var, values=exam_labels,
            state="disabled" if row.get("builtin") else "readonly",
            font=FONT_BASE,
        ).pack(fill="x", pady=(2, 8))

        tk.Label(wrap, text="Default duration (minutes)", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(anchor="w")
        self._dur_var = tk.StringVar(value=str(int(row.get("duration_min") or 15)))
        ttk.Combobox(
            wrap, textvariable=self._dur_var,
            values=["15", "30", "45", "60", "90"],
            state="readonly", font=FONT_BASE,
        ).pack(fill="x", pady=(2, 8))

        self._active_var = tk.BooleanVar(value=bool(row.get("active", True)))
        tk.Checkbutton(
            wrap, text="Active (show in Schedule)", variable=self._active_var,
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE,
            activebackground=COLOR_CARD,
        ).pack(anchor="w", pady=(4, 12))

        btns = tk.Frame(wrap, bg=COLOR_CARD)
        btns.pack(fill="x")
        tk.Button(
            btns, text="Cancel", command=self.destroy,
            bg=COLOR_CARD, fg=COLOR_MUTED, relief="flat", font=FONT_BASE,
        ).pack(side="right", padx=(6, 0))
        tk.Button(
            btns, text="Save", command=self._save,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=4,
        ).pack(side="right")

        self.geometry("380x340")

    def _save(self) -> None:
        try:
            duration = int(self._dur_var.get() or 15)
        except Exception:
            duration = 15
        payload = dict(self._row)
        if not payload.get("builtin"):
            payload["label"] = (self._label_var.get() or "").strip()
        payload["exam_type"] = self._exam_key_by_label.get(
            (self._exam_var.get() or "").strip(), payload.get("exam_type") or "chiro",
        )
        payload["duration_min"] = duration
        payload["active"] = bool(self._active_var.get())
        upsert_appt_type(payload)
        if self._on_saved:
            self._on_saved(payload)
        self.destroy()
