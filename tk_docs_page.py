# tk_docs_page.py
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk
from datetime import datetime


def _safe_parse_mmddyyyy(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


class TkDocsPage(ttk.Frame):
    def __init__(
        self,
        parent,
        get_exam_names_fn,
        get_exam_path_fn,
        get_fallback_date_fn,
        on_open_exam,
        on_hover_exam=None,
        on_add_initial=None,
        on_add_reexam=None,
        on_add_rof=None,
        on_add_final=None,
        on_add_chiro=None,
        set_scroll_target_fn=None,
        get_current_exam_fn=None,
    ):
        super().__init__(parent)

        self.get_exam_names_fn = get_exam_names_fn
        self.get_exam_path_fn = get_exam_path_fn
        self.get_fallback_date_fn = get_fallback_date_fn
        self.on_open_exam = on_open_exam
        self.on_hover_exam = on_hover_exam


        # ✅ store callbacks safely
        self.on_add_initial = on_add_initial or (lambda: None)
        self.on_add_reexam  = on_add_reexam  or (lambda: None)
        self.on_add_rof     = on_add_rof     or (lambda: None)
        self.on_add_final   = on_add_final   or (lambda: None)
        self.on_add_chiro   = on_add_chiro   or (lambda: None)
        self.set_scroll_target_fn = set_scroll_target_fn
        self.get_current_exam_fn = get_current_exam_fn or (lambda: None)


        # ✅ define helper BEFORE buttons use it
        def _call_and_refresh(cb):
            def _run():
                try:
                    cb()
                finally:
                    self.after(100, self.refresh)
            return _run

        # --- header row ---
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(top, text="Docs (Timeline)", font=("Segoe UI", 12, "bold")).pack(side="left")

        btns = ttk.Frame(top)
        btns.pack(side="left", padx=10)

        ttk.Button(btns, text="+ Initial",
                   command=_call_and_refresh(self.on_add_initial)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="+ Re-Exam",
                   command=_call_and_refresh(self.on_add_reexam)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="+ ROF",
                   command=_call_and_refresh(self.on_add_rof)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="+ Final",
                   command=_call_and_refresh(self.on_add_final)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="+ Chiro Visit",
                   command=_call_and_refresh(self.on_add_chiro)).pack(side="left", padx=(0, 6))

        self.refresh_btn = ttk.Button(top, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side="right")

        # (keep the rest of your scroll/canvas setup below, unchanged)

        # --- scrollable area (canvas + frame) ---
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        self.vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        #self.inner.bind("<Motion>", self._on_inner_motion)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        def _focus_canvas(_e=None):
            try:
                self.canvas.focus_set()
            except Exception:
                pass

        self.canvas.configure(takefocus=True)

        # focus canvas when mouse enters the docs area
        self.canvas.bind("<Enter>", _focus_canvas, "+")
        self.inner.bind("<Enter>", _focus_canvas, "+")

        def _set_target_canvas(_e=None):
            if self.set_scroll_target_fn:
                self.set_scroll_target_fn(self.canvas)

        def _clear_target(_e=None):
            if self.set_scroll_target_fn:
                self.set_scroll_target_fn(None)

        # When mouse is anywhere in Docs, scroll should move the Docs canvas
        self.canvas.bind("<Enter>", _set_target_canvas)
        self.inner.bind("<Enter>", _set_target_canvas)
        self.canvas.bind("<Leave>", _clear_target)
        self.inner.bind("<Leave>", _clear_target)


        # --- global wheel capture so scrolling works over buttons too ---

        def _is_descendant(widget, ancestor) -> bool:
            w = widget
            while w is not None:
                if w == ancestor:
                    return True
                w = getattr(w, "master", None)
            return False

        def _pointer_over_this_page(event) -> bool:
            try:
                w = self.winfo_containing(event.x_root, event.y_root)
            except Exception:
                return False
            if not w:
                return False
            return _is_descendant(w, self)

        # def _wheel_global(event):
        #     if not self.winfo_viewable():
        #         return
        #     if not _pointer_over_this_page(event):
        #         return

        #     if getattr(event, "delta", 0):
        #         steps = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
        #         self.canvas.yview_scroll(steps, "units")
        #         return "break"

        # def _wheel_linux_up(event):
        #     if not self.winfo_viewable():
        #         return
        #     if not _pointer_over_this_page(event):
        #         return
        #     self.canvas.yview_scroll(-1, "units")
        #     return "break"

        # def _wheel_linux_down(event):
        #     if not self.winfo_viewable():
        #         return
        #     if not _pointer_over_this_page(event):
        #         return
        #     self.canvas.yview_scroll(1, "units")
        #     return "break"

        # bind globally so buttons don't block scroll
        # self.bind_all("<MouseWheel>", _wheel_global, add="+")
        # self.bind_all("<Button-4>", _wheel_linux_up, add="+")
        # self.bind_all("<Button-5>", _wheel_linux_down, add="+")


        # hover tracking (mouse move) — use ONLY this (delete _on_inner_motion binding)
        self.inner.bind("<Motion>", self._on_motion, "+")
        self.canvas.bind("<Motion>", self._on_motion, "+")
        self.inner.bind("<Leave>", self._on_leave, "+")
        self.canvas.bind("<Leave>", self._on_leave, "+")


        # resize behaviors
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # --- mousewheel: Docs owns scrolling, stop App.bind_all from stealing it ---
    


        self._last_hover_key = None




        self._rows: list[ttk.Button] = []

        


    def _on_motion(self, event):
        if not self.on_hover_exam:
            return

        # figure out what widget the mouse is actually over
        w = event.widget.winfo_containing(event.x_root, event.y_root)
        if not w:
            return

        # climb up until we find one of our exam buttons
        while w is not None and w not in self._rows:
            try:
                w = w.master
            except Exception:
                w = None

        if w is None:
            return

        exam_name = getattr(w, "_exam_name", None)
        date_str = getattr(w, "_date_str", None)
        if not exam_name or date_str is None:
            return

        # avoid spam-calling the callback
        key = (exam_name, date_str)
        if getattr(self, "_last_hover_key", None) == key:
            return
        self._last_hover_key = key

        try:
            self.on_hover_exam(exam_name, date_str)
        except Exception:
            pass

    def _on_mousewheel(self, event):
        if event.delta == 0:
            return "break"
        steps = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(steps, "units")
        return "break"

    def _on_mousewheel_linux_up(self, _event):
        self.canvas.yview_scroll(-1, "units")
        return "break"

    def _on_mousewheel_linux_down(self, _event):
        self.canvas.yview_scroll(1, "units")
        return "break"


    def _on_leave(self, _event=None):
        # optional: clear last hover so re-enter triggers immediately
        self._last_hover_key = None    

    
    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        # keep inner width same as canvas width
        self.canvas.itemconfigure(self.inner_id, width=e.width)    

    # def _on_mousewheel(self, event):
    #     if event.delta == 0:
    #         return "break"
    #     steps = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
    #     self.canvas.yview_scroll(steps, "units")
    #     return "break"  # <- STOP bubbling to App.bind_all

    # def _on_mousewheel_linux_up(self, _event):
    #     self.canvas.yview_scroll(-1, "units")
    #     return "break"

    # def _on_mousewheel_linux_down(self, _event):
    #     self.canvas.yview_scroll(1, "units")
    #     return "break"


    def _clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._rows.clear()

    def _exam_date_for(self, exam_name: str) -> datetime:
        """
        Prefer saved exam_date in that exam's JSON; fallback to demographics date.
        """
        path = self.get_exam_path_fn(exam_name)
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f) or {}
                patient = payload.get("patient", {}) or {}
                dt = _safe_parse_mmddyyyy(patient.get("exam_date", ""))
                if dt:
                    return dt
            except Exception:
                pass

        fb = self.get_fallback_date_fn()
        return _safe_parse_mmddyyyy(fb) or datetime.min

    def refresh(self):
        self._clear()

        exam_names = []
        for n in (self.get_exam_names_fn() or []):
            # ✅ hide legacy always-on Initial
            if (n or "").strip().lower() == "initial":
                continue

            p = self.get_exam_path_fn(n)
            if p and os.path.exists(p):
                exam_names.append(n)


        if not exam_names:
            ttk.Label(self.inner, text="(No documents yet)").pack(anchor="w", pady=6)
            return

        rows = []
        for name in exam_names:
            dt = self._exam_date_for(name)
            rows.append((dt, name))

        # newest first
        rows.sort(key=lambda x: x[0], reverse=True)

        current_exam = self.get_current_exam_fn()

        for dt, exam_name in rows:

            date_str = dt.strftime("%m/%d/%Y") if dt != datetime.min else "(no date)"
            label = f"{date_str}   {exam_name}"

            is_active = (exam_name == current_exam)

            b = ttk.Button(
                self.inner,
                text=label,
                command=lambda e=exam_name: self.on_open_exam(e)
            )

            b.pack(fill="x", pady=3)

            # Apply bold style if active exam
            if is_active:
                b.configure(style="ActiveExam.TButton")

            # scroll targeting
            if self.set_scroll_target_fn:
                b.bind("<Enter>", lambda _e: self.set_scroll_target_fn(self.canvas), "+")

            # metadata storage
            b._exam_name = exam_name
            b._date_str = date_str

            self._rows.append(b)


        # force scrollregion update
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
