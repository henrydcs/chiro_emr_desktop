# em_long_description_dialog.py — Chart / PDF long E/M description editor (shared UI).
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from shell_app import COLOR_BG_APP


class EmLongDescriptionDialog(tk.Toplevel):
    """Popup editor for E/M long chart/PDF narrative (catalog default or per-visit)."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        initial_text: str = "",
        on_save: Callable[[str], None] | None = None,
    ):
        super().__init__(parent)
        self._on_save = on_save
        self.title("Chart / PDF Description (long; optional)")
        self.geometry("520x360")
        self.minsize(440, 280)
        self.configure(bg=COLOR_BG_APP)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Chart / PDF description (long, optional):",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="Dropdown shows the short label only. This text appears in Live Preview and the PDF.",
            font=("Segoe UI", 8),
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(0, 12))

        self._text = tk.Text(text_frame, height=10, wrap="word", font=("Segoe UI", 9))
        self._text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(text_frame, command=self._text.yview)
        scroll.pack(side="right", fill="y")
        self._text.config(yscrollcommand=scroll.set)

        if initial_text:
            self._text.insert("1.0", initial_text)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Save and Exit", command=self._save).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=self._cancel).pack(side="left", padx=(10, 0))

    def _save(self) -> None:
        text = self._text.get("1.0", "end-1c").strip()
        if self._on_save:
            try:
                self._on_save(text)
            except Exception:
                pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
