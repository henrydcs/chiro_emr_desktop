# schedule_page.py — Responsive clinic schedule (day / week views).
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

from schedule_dialogs import AppointmentDialog
from schedule_engine import (
    DISPLAY_STYLES,
    day_slot_count,
    enrich_appointment,
    format_time_12h,
    patient_short_label,
    slot_index,
    slot_span,
    time_for_slot,
    time_label_for_slot,
)
from schedule_storage import list_appointments, upsert_appointment
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    FONT_SMALL,
    FONT_TITLE,
    make_card,
    patient_record_from_folder,
    write_shell_state,
)

_SCHEDULE_WIDE_MIN_WIDTH = 1240

_SCHEDULE_DESKTOP_FONTS = {
    "title": FONT_TITLE,
    "section": FONT_SECTION,
    "base": FONT_BASE,
    "base_bold": FONT_BASE_BOLD,
    "small": FONT_SMALL,
}

_SCHEDULE_LAPTOP_FONTS = {
    "title": ("Segoe UI", 14, "bold"),
    "section": ("Segoe UI", 10, "bold"),
    "base": ("Segoe UI", 9),
    "base_bold": ("Segoe UI", 9, "bold"),
    "small": ("Segoe UI", 8),
}

_DESKTOP_SLOT_H = 26
_LAPTOP_SLOT_H = 20


class SchedulePage(tk.Frame):
    """Day / week calendar with status color-coding and laptop-friendly layout."""

    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self._view = "day"
        self._focus_date = date.today()
        self._appointments: list[dict] = []
        self._layout_compact: bool | None = None
        self._layout_after_id: str | None = None
        self._fonts = dict(_SCHEDULE_DESKTOP_FONTS)
        self._slot_h = _DESKTOP_SLOT_H

        self._build()
        self.bind("<Configure>", self._on_configure, add="+")
        self.bind("<Map>", self._on_map, add="+")
        self.after_idle(self._refresh)

    def _font(self, key: str):
        return self._fonts.get(key, FONT_BASE)

    def _build(self) -> None:
        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        self._outer = outer

        header = tk.Frame(outer, bg=COLOR_BG_APP)
        header.pack(fill="x", pady=(0, 10))
        self._title_label = tk.Label(
            header, text="Schedule", bg=COLOR_BG_APP, fg=COLOR_TEXT,
            font=self._font("title"),
        )
        self._title_label.pack(side="left")
        self._subtitle_label = tk.Label(
            header,
            text="Day and week views · color updates when charts are signed",
            bg=COLOR_BG_APP, fg=COLOR_MUTED, font=self._font("small"),
        )
        self._subtitle_label.pack(side="left", padx=(10, 0))

        toolbar = tk.Frame(outer, bg=COLOR_BG_APP)
        toolbar.pack(fill="x", pady=(0, 8))
        self._toolbar = toolbar

        self._btn_today = tk.Button(
            toolbar, text="Today", command=self._go_today,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=5, cursor="hand2",
        )
        self._btn_today.pack(side="left", padx=(0, 6))
        self._btn_prev = tk.Button(
            toolbar, text="◀", command=self._go_prev,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=8, pady=5, cursor="hand2",
        )
        self._btn_prev.pack(side="left", padx=(0, 4))
        self._date_var = tk.StringVar()
        self._date_label = tk.Label(
            toolbar, textvariable=self._date_var,
            bg=COLOR_BG_APP, fg=COLOR_TEXT, font=self._font("section"),
            width=22, anchor="center",
        )
        self._date_label.pack(side="left", padx=(0, 4))
        self._btn_next = tk.Button(
            toolbar, text="▶", command=self._go_next,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=8, pady=5, cursor="hand2",
        )
        self._btn_next.pack(side="left", padx=(0, 12))

        self._btn_day = tk.Button(
            toolbar, text="Day", command=lambda: self._set_view("day"),
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=self._font("base_bold"), padx=12, pady=5, cursor="hand2",
        )
        self._btn_day.pack(side="left", padx=(0, 4))
        self._btn_week = tk.Button(
            toolbar, text="Week", command=lambda: self._set_view("week"),
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=5, cursor="hand2",
        )
        self._btn_week.pack(side="left", padx=(0, 12))

        self._btn_new = tk.Button(
            toolbar, text="+ New appointment", command=self._new_appointment,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=self._font("base_bold"), padx=12, pady=5, cursor="hand2",
        )
        self._btn_new.pack(side="right")
        self._btn_refresh = tk.Button(
            toolbar, text="Refresh", command=self._refresh,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=self._font("base"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=5, cursor="hand2",
        )
        self._btn_refresh.pack(side="right", padx=(0, 8))

        card, body = make_card(outer, "Calendar", "Click an empty time cell to add an appointment")
        self._cal_card = card
        self._cal_body = body
        card.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            body, bg=COLOR_CARD, highlightthickness=0, bd=0,
        )
        self._vsb = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vsb.grid(row=0, column=1, sticky="ns")

        self._grid_host = tk.Frame(self._canvas, bg=COLOR_CARD)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._grid_host, anchor="nw",
        )
        self._grid_host.bind("<Configure>", self._on_grid_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        legend = tk.Frame(outer, bg=COLOR_BG_APP)
        legend.pack(fill="x", pady=(8, 0))
        self._legend = legend
        self._paint_legend()

    def _paint_legend(self) -> None:
        for w in self._legend.winfo_children():
            w.destroy()
        items = [
            ("Scheduled", "scheduled"),
            ("Checked in", "checked_in"),
            ("In progress", "in_progress"),
            ("Signed / done", "signed"),
            ("No-show", "no_show"),
            ("Cancelled", "cancelled"),
        ]
        tk.Label(
            self._legend, text="Colors:", bg=COLOR_BG_APP,
            fg=COLOR_MUTED, font=self._font("small"),
        ).pack(side="left", padx=(0, 8))
        for label, key in items:
            style = DISPLAY_STYLES[key]
            chip = tk.Label(
                self._legend, text=f" {label} ",
                bg=style["bg"], fg=style["fg"],
                font=self._font("small"),
                highlightbackground=style["border"],
                highlightthickness=1, padx=4, pady=1,
            )
            chip.pack(side="left", padx=(0, 6))

    def _on_grid_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._canvas_window, width=event.width)

    def _on_configure(self, event) -> None:
        if event.widget is not self:
            return
        if event.width < 200:
            return
        after_id = self._layout_after_id
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._layout_after_id = self.after(120, self._sync_layout)

    def _on_map(self, _event=None) -> None:
        self.after_idle(self._sync_layout)
        self.after_idle(self._refresh)

    def _sync_layout(self) -> None:
        width = self.winfo_width()
        if width < 200:
            return
        compact = width <= _SCHEDULE_WIDE_MIN_WIDTH
        if compact == self._layout_compact:
            return
        self._layout_compact = compact
        self._fonts = dict(_SCHEDULE_LAPTOP_FONTS if compact else _SCHEDULE_DESKTOP_FONTS)
        self._slot_h = _LAPTOP_SLOT_H if compact else _DESKTOP_SLOT_H

        pad = 8 if compact else 16
        self._outer.pack_configure(padx=pad, pady=pad)
        self._title_label.configure(font=self._font("title"))
        self._subtitle_label.configure(font=self._font("small"))
        for btn in (
            self._btn_today, self._btn_prev, self._btn_next,
            self._btn_day, self._btn_week, self._btn_new, self._btn_refresh,
        ):
            btn.configure(font=self._font("base_bold") if btn is not self._btn_refresh else self._font("base"))
        self._date_label.configure(font=self._font("section"))
        self._paint_legend()
        self._render()

    def _set_view(self, view: str) -> None:
        self._view = view
        if view == "day":
            self._btn_day.configure(bg=COLOR_ACCENT, fg="#FFFFFF", highlightthickness=0)
            self._btn_week.configure(bg=COLOR_CARD, fg=COLOR_ACCENT, highlightthickness=1)
        else:
            self._btn_week.configure(bg=COLOR_ACCENT, fg="#FFFFFF", highlightthickness=0)
            self._btn_day.configure(bg=COLOR_CARD, fg=COLOR_ACCENT, highlightthickness=1)
        self._render()

    def _week_start(self) -> date:
        # Monday-start week
        wd = self._focus_date.weekday()
        return self._focus_date - timedelta(days=wd)

    def _go_today(self) -> None:
        self._focus_date = date.today()
        self._render()

    def _go_prev(self) -> None:
        delta = timedelta(days=1 if self._view == "day" else 7)
        self._focus_date -= delta
        self._render()

    def _go_next(self) -> None:
        delta = timedelta(days=1 if self._view == "day" else 7)
        self._focus_date += delta
        self._render()

    def _update_date_label(self) -> None:
        if self._view == "day":
            self._date_var.set(self._focus_date.strftime("%A, %B %d, %Y"))
        else:
            start = self._week_start()
            end = start + timedelta(days=6)
            self._date_var.set(
                f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
            )

    def _load_appointments(self) -> list[dict]:
        if self._view == "day":
            rows = list_appointments(day=self._focus_date)
        else:
            start = self._week_start()
            end = start + timedelta(days=6)
            rows = list_appointments(start=start, end=end)
        return [enrich_appointment(r) for r in rows]

    def _refresh(self) -> None:
        self._appointments = self._load_appointments()
        self._update_date_label()
        self._render()

    def _render(self) -> None:
        for w in self._grid_host.winfo_children():
            w.destroy()
        self._update_date_label()
        if self._view == "day":
            self._render_day_view()
        else:
            self._render_week_view()
        self._on_grid_configure()

    def _render_day_view(self) -> None:
        host = self._grid_host
        n_slots = day_slot_count()
        host.columnconfigure(0, weight=0, minsize=64 if self._layout_compact else 72)
        host.columnconfigure(1, weight=1)

        day_appts = [
            a for a in self._appointments
            if (a.get("date") or "") == self._focus_date.isoformat()
        ]
        day_appts.sort(key=lambda a: (a.get("start_time") or ""))

        for slot in range(n_slots):
            host.rowconfigure(slot, minsize=self._slot_h, weight=0)
            lbl = time_label_for_slot(slot)
            if slot % 4 == 0:
                tk.Label(
                    host, text=lbl, bg=COLOR_CARD, fg=COLOR_MUTED,
                    font=self._font("small"), anchor="e", width=8,
                ).grid(row=slot, column=0, sticky="ne", padx=(4, 6), pady=(0, 0))
            self._make_slot_cell(
                host, grid_row=slot, grid_col=1,
                day=self._focus_date, slot=slot,
            )

        placed: set[int] = set()
        for appt in day_appts:
            idx = slot_index(appt.get("start_time") or "")
            span = slot_span(int(appt.get("duration_min") or 15))
            if idx >= n_slots:
                continue
            while idx in placed and idx < n_slots - 1:
                idx += 1
            for s in range(idx, min(idx + span, n_slots)):
                placed.add(s)
            self._make_appt_block(
                host, appt,
                grid_row=idx, grid_col=1, rowspan=span,
            )

    def _render_week_view(self) -> None:
        host = self._grid_host
        start = self._week_start()
        n_slots = day_slot_count()
        time_w = 52 if self._layout_compact else 60

        host.columnconfigure(0, weight=0, minsize=time_w)
        for c in range(1, 8):
            host.columnconfigure(c, weight=1, uniform="weekday")

        # Corner + day headers (row 0)
        tk.Label(
            host, text="", bg=COLOR_CARD, width=2,
        ).grid(row=0, column=0, sticky="nw")

        day_cols: dict[str, int] = {}
        for c in range(7):
            d = start + timedelta(days=c)
            day_cols[d.isoformat()] = c + 1
            is_today = d == date.today()
            head_bg = "#EEF2FF" if is_today else "#F8FAFC"
            head = tk.Frame(
                host, bg=head_bg,
                highlightbackground=COLOR_BORDER, highlightthickness=1,
            )
            head.grid(
                row=0, column=c + 1, sticky="nsew",
                padx=(1, 0), pady=(0, 0),
            )
            tk.Label(
                head, text=d.strftime("%a"), bg=head_bg, fg=COLOR_MUTED,
                font=self._font("small"),
            ).pack(anchor="w", padx=4, pady=(4, 0))
            tk.Label(
                head, text=str(d.day), bg=head_bg,
                fg=COLOR_ACCENT if is_today else COLOR_TEXT,
                font=self._font("section"),
            ).pack(anchor="w", padx=4, pady=(0, 4))

        # Time grid (rows 1 … n_slots)
        for slot in range(n_slots):
            grid_row = 1 + slot
            host.rowconfigure(grid_row, minsize=self._slot_h, weight=0)
            if slot % 4 == 0:
                tk.Label(
                    host, text=time_label_for_slot(slot), bg=COLOR_CARD,
                    fg=COLOR_MUTED, font=self._font("small"),
                    anchor="e", width=6,
                ).grid(row=grid_row, column=0, sticky="ne", padx=(2, 4))
            for c in range(7):
                d = start + timedelta(days=c)
                self._make_slot_cell(
                    host, grid_row=grid_row, grid_col=c + 1,
                    day=d, slot=slot,
                )

        placed: dict[int, set[int]] = {c + 1: set() for c in range(7)}
        for appt in self._appointments:
            day_key = appt.get("date") or ""
            col = day_cols.get(day_key)
            if col is None:
                continue
            idx = slot_index(appt.get("start_time") or "")
            span = slot_span(int(appt.get("duration_min") or 15))
            if idx >= n_slots:
                continue
            occupied = placed[col]
            while idx in occupied and idx < n_slots - 1:
                idx += 1
            for s in range(idx, min(idx + span, n_slots)):
                occupied.add(s)
            self._make_appt_block(
                host, appt,
                grid_row=1 + idx, grid_col=col, rowspan=span,
                compact=True,
            )

    def _make_slot_cell(
        self,
        parent: tk.Misc,
        *,
        grid_row: int,
        grid_col: int,
        day: date,
        slot: int,
    ) -> tk.Frame:
        """Empty grid cell — bordered column slot, click to book."""
        cell = tk.Frame(
            parent, bg="#FFFFFF",
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            cursor="hand2",
        )
        cell.grid(row=grid_row, column=grid_col, sticky="nsew", padx=(1, 0), pady=(1, 0))

        start_time = time_for_slot(slot)

        def _open(_event=None, d=day, t=start_time):
            self._new_appointment(default_date=d, default_time=t)

        def _hover_in(_event=None, w=cell):
            try:
                if w.cget("bg") == "#FFFFFF":
                    w.configure(bg="#F8FAFC")
            except tk.TclError:
                pass

        def _hover_out(_event=None, w=cell):
            try:
                if w.cget("bg") == "#F8FAFC":
                    w.configure(bg="#FFFFFF")
            except tk.TclError:
                pass

        cell.bind("<Button-1>", _open)
        cell.bind("<Enter>", _hover_in)
        cell.bind("<Leave>", _hover_out)
        return cell

    def _make_appt_block(
        self,
        parent: tk.Misc,
        appt: dict,
        *,
        grid_row: int,
        grid_col: int,
        rowspan: int = 1,
        compact: bool = False,
    ) -> tk.Frame:
        style = appt.get("display_style") or DISPLAY_STYLES["scheduled"]
        block = tk.Frame(
            parent, bg=style["bg"],
            highlightbackground=style["border"], highlightthickness=1,
            cursor="hand2",
        )
        pad_x = (1, 2) if compact else (4, 8)
        block.grid(
            row=grid_row, column=grid_col, rowspan=rowspan,
            sticky="nsew", padx=pad_x, pady=1,
        )

        name = patient_short_label(appt)
        time_txt = format_time_12h(appt.get("start_time") or "")
        appt_type = (appt.get("appt_type") or "").strip()
        signed = " · ✓" if appt.get("chart_signed") else ""

        if compact:
            tk.Label(
                block, text=f"{time_txt}\n{name}{signed}",
                bg=style["bg"], fg=style["fg"], font=self._font("small"),
                anchor="nw", justify="left", wraplength=72,
            ).pack(fill="both", expand=True, padx=3, pady=2)
        else:
            tk.Label(
                block, text=f"{time_txt}  {name}",
                bg=style["bg"], fg=style["fg"], font=self._font("base_bold"),
                anchor="w",
            ).pack(fill="x", padx=6, pady=(4, 0))
            detail = appt_type or (appt.get("display_status") or "").title()
            if detail:
                tk.Label(
                    block, text=f"{detail}{signed}",
                    bg=style["bg"], fg=style["fg"], font=self._font("small"),
                    anchor="w",
                ).pack(fill="x", padx=6, pady=(0, 4))

        for widget in (block, *block.winfo_children()):
            widget.bind("<Button-1>", lambda _e, a=appt: self._show_appt_menu(a))
            widget.bind("<Double-Button-1>", lambda _e, a=appt: self._edit_appointment(a))
        try:
            block.tkraise()
        except tk.TclError:
            pass
        return block

    def _new_appointment(
        self,
        default_date: date | None = None,
        default_time: str | None = None,
    ) -> None:
        AppointmentDialog(
            self,
            default_date=default_date or self._focus_date,
            default_time=default_time,
            on_saved=lambda _r: self._refresh(),
        )

    def _edit_appointment(self, appt: dict) -> None:
        AppointmentDialog(
            self, appt=appt, on_saved=lambda _r: self._refresh(),
        )

    def _show_appt_menu(self, appt: dict) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Edit appointment…",
            command=lambda: self._edit_appointment(appt),
        )
        menu.add_separator()
        menu.add_command(
            label="Check in",
            command=lambda: self._set_status(appt, "checked_in"),
        )
        menu.add_command(
            label="Mark in progress",
            command=lambda: self._set_status(appt, "in_progress"),
        )
        menu.add_command(
            label="Mark completed",
            command=lambda: self._set_status(appt, "completed"),
        )
        menu.add_command(
            label="No-show",
            command=lambda: self._set_status(appt, "no_show"),
        )
        menu.add_command(
            label="Cancel",
            command=lambda: self._set_status(appt, "cancelled"),
        )
        menu.add_separator()
        exam_path = (appt.get("exam_path") or "").strip()
        if exam_path:
            menu.add_command(
                label="Open chart",
                command=lambda: self._open_chart(appt),
            )
        else:
            menu.add_command(
                label="Open patient chart",
                command=lambda: self._open_patient(appt),
            )
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _set_status(self, appt: dict, status: str) -> None:
        payload = dict(appt)
        payload["status"] = status
        upsert_appointment(payload)
        self._refresh()

    def _open_patient(self, appt: dict) -> None:
        pid = (appt.get("patient_id") or "").strip()
        folder = (appt.get("patient_folder") or "").strip()
        if not pid and not folder:
            return
        rec = None
        if folder:
            from pathlib import Path
            rec = patient_record_from_folder(Path(folder))
        if rec and self.shell.documents_page:
            self.shell.documents_page.set_active_patient(rec)
            write_shell_state({
                "active_patient_id": rec.get("patient_id"),
                "active_patient_folder": rec.get("folder"),
                "active_patient_label": rec.get("label"),
            })
        if pid and self.shell.documents_page:
            self.shell.documents_page.launch_soap_for_patient_id(pid)

    def _open_chart(self, appt: dict) -> None:
        exam_path = (appt.get("exam_path") or "").strip()
        if not exam_path:
            self._open_patient(appt)
            return
        folder = (appt.get("patient_folder") or "").strip()
        if folder and self.shell.documents_page:
            from pathlib import Path
            rec = patient_record_from_folder(Path(folder))
            if rec:
                self.shell.documents_page.set_active_patient(rec)
        if self.shell.documents_page:
            self.shell.documents_page.launch_soap_for_path(exam_path)
