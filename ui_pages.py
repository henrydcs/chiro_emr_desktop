# ui_pages.py
import tkinter as tk
from tkinter import ttk


class TextPage(ttk.Frame):
    def __init__(self, parent, title: str, on_change_callback):
        super().__init__(parent)
        self.on_change_callback = on_change_callback

        ttk.Label(self, text=title).pack(anchor="w", padx=10, pady=(10, 4))

        self.text = tk.Text(self, width=110, height=20, wrap="word")
        self.text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.text.bind("<KeyRelease>", lambda e: self.on_change_callback())

    def get_value(self) -> str:
        return self.text.get("1.0", tk.END).strip()

    def set_value(self, value: str):
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, value or "")

    def has_content(self) -> bool:
        return bool(self.get_value().strip())

    def reset(self):
        self.set_value("")
