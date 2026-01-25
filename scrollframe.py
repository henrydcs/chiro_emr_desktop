# scrollframe.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import platform


class ScrollFrame(ttk.Frame):
    """
    A reusable scrollable frame:
      - self.content is where you place all your widgets
      - mouse wheel only scrolls when the pointer is over the scroll area
      - supports Windows/macOS (MouseWheel) and Linux (Button-4/5)
    """

    def __init__(self, parent, *, use_x: bool = False):
        super().__init__(parent)

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)

        self.h_scrollbar = None
        if use_x:
            self.h_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)

        # inner content frame (put widgets here)
        self.content = ttk.Frame(self.canvas)

        # update scroll region when content changes size
        self.content.bind("<Configure>", self._on_content_configure)

        # keep content width in sync with canvas width (so it behaves like a normal page)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        if self.h_scrollbar:
            self.canvas.configure(xscrollcommand=self.h_scrollbar.set)

        # layout
        self.canvas.pack(side="left", fill="both", expand=True)
        self.v_scrollbar.pack(side="right", fill="y")
        if self.h_scrollbar:
            self.h_scrollbar.pack(side="bottom", fill="x")

        self._bind_wheel_on_hover()

    # ---------- sizing / scrollregion ----------
    def _on_content_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # make content frame match the canvas width (vertical-page feel)
        try:
            self.canvas.itemconfigure(self._window_id, width=event.width)
        except Exception:
            pass

    # ---------- mousewheel binding ----------
    def _bind_wheel_on_hover(self):
        self.canvas.bind("<Enter>", self._enable_mousewheel)
        self.canvas.bind("<Leave>", self._disable_mousewheel)
        self.content.bind("<Enter>", self._enable_mousewheel)
        self.content.bind("<Leave>", self._disable_mousewheel)

    def _enable_mousewheel(self, event=None):
        sys = platform.system()
        if sys in ("Windows", "Darwin"):
            self.bind_all("<MouseWheel>", self._on_mousewheel)
        else:
            self.bind_all("<Button-4>", self._on_mousewheel)
            self.bind_all("<Button-5>", self._on_mousewheel)

    def _disable_mousewheel(self, event=None):
        sys = platform.system()
        if sys in ("Windows", "Darwin"):
            self.unbind_all("<MouseWheel>")
        else:
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        # Linux (Button-4/5)
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
            return
        if getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
            return

        # Windows/macOS: MouseWheel with delta
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return

        if platform.system() == "Darwin":
            step = -1 if delta > 0 else 1
        else:
            step = -1 * int(delta / 120)

        if step:
            self.canvas.yview_scroll(step, "units")

    # ---------- convenience ----------
    def scroll_to_top(self):
        self.canvas.yview_moveto(0)

    def scroll_to_bottom(self):
        self.canvas.yview_moveto(1)
