# schedule_page.py — Responsive clinic schedule (day / 5-day / 7-day views).
from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from datetime import date, timedelta
from tkinter import ttk

from schedule_dialogs import AppointmentDialog
from schedule_engine import (
    DISPLAY_STYLES,
    appt_block_label,
    calendar_row_span,
    day_slot_count,
    enrich_appointment,
    slot_index,
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
_MAX_SLOT_LANES = 4
_SCHED_LANE_COLS = 4
_SCHED_ADD_COL = 4
_SLOT_CONTENT_WEIGHT = 9   # ~90% for appointment(s)
_SLOT_ADD_STRIP_WEIGHT = 1  # ~10% white strip to add another appt


class SchedulePage(tk.Frame):
    """Day / 5-day / 7-day calendar with up to four patients per time slot."""

    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self._view = "7day"
        self._focus_date = date.today()
        self._appointments: list[dict] = []
        self._layout_compact: bool | None = None
        self._layout_after_id: str | None = None
        self._last_canvas_width: int = 0
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
            text="Day, 5-day, and 7-day views · up to 4 patients per slot",
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
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=5, cursor="hand2",
        )
        self._btn_day.pack(side="left", padx=(0, 4))
        self._btn_5day = tk.Button(
            toolbar, text="5-day", command=lambda: self._set_view("5day"),
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=self._font("base_bold"),
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=5, cursor="hand2",
        )
        self._btn_5day.pack(side="left", padx=(0, 4))
        self._btn_7day = tk.Button(
            toolbar, text="7-day", command=lambda: self._set_view("7day"),
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=self._font("base_bold"), padx=12, pady=5, cursor="hand2",
        )
        self._btn_7day.pack(side="left", padx=(0, 12))
        self._view_btns = {
            "day": self._btn_day,
            "5day": self._btn_5day,
            "7day": self._btn_7day,
        }

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
        self._last_canvas_width = event.width
        if hasattr(self, "_grid_host") and self._grid_host.winfo_children():
            self._apply_calendar_column_widths(self._view_day_count())

    def _apply_calendar_column_widths(self, num_days: int) -> None:
        """Stretch day columns to fill the full calendar canvas width."""
        host = self._grid_host
        if not host.winfo_exists():
            return
        width = getattr(self, "_last_canvas_width", 0) or self._canvas.winfo_width()
        if width < 120:
            return
        time_w = 46 if self._layout_compact else 52
        usable = max(width - time_w - (num_days * 2) - 4, num_days * 72)
        day_w = max(72, usable // num_days)
        host.columnconfigure(0, weight=0, minsize=time_w)
        for d in range(num_days):
            host.columnconfigure(d + 1, weight=1, minsize=day_w, uniform="sched_day")

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
            self._btn_day, self._btn_5day, self._btn_7day,
            self._btn_new, self._btn_refresh,
        ):
            btn.configure(font=self._font("base_bold") if btn is not self._btn_refresh else self._font("base"))
        self._date_label.configure(font=self._font("section"))
        self._paint_legend()
        self._render()

    def _set_view(self, view: str) -> None:
        if view not in self._view_btns:
            return
        self._view = view
        for key, btn in self._view_btns.items():
            if key == view:
                btn.configure(bg=COLOR_ACCENT, fg="#FFFFFF", highlightthickness=0)
            else:
                btn.configure(bg=COLOR_CARD, fg=COLOR_ACCENT, highlightthickness=1)
        self._render()

    def _week_start(self) -> date:
        # Monday-start week
        wd = self._focus_date.weekday()
        return self._focus_date - timedelta(days=wd)

    def _view_day_count(self) -> int:
        if self._view == "5day":
            return 5
        if self._view == "7day":
            return 7
        return 1

    def _view_start_date(self) -> date:
        if self._view == "day":
            return self._focus_date
        return self._week_start()

    def _view_end_date(self) -> date:
        return self._view_start_date() + timedelta(days=self._view_day_count() - 1)

    def _go_today(self) -> None:
        self._focus_date = date.today()
        self._render()

    def _go_prev(self) -> None:
        if self._view == "day":
            delta = timedelta(days=1)
        else:
            delta = timedelta(days=7)
        self._focus_date -= delta
        self._render()

    def _go_next(self) -> None:
        if self._view == "day":
            delta = timedelta(days=1)
        else:
            delta = timedelta(days=7)
        self._focus_date += delta
        self._render()

    def _update_date_label(self) -> None:
        if self._view == "day":
            self._date_var.set(self._focus_date.strftime("%A, %B %d, %Y"))
        else:
            start = self._view_start_date()
            end = self._view_end_date()
            self._date_var.set(
                f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
            )

    def _load_appointments(self) -> list[dict]:
        if self._view == "day":
            rows = list_appointments(day=self._focus_date)
        else:
            start = self._view_start_date()
            end = self._view_end_date()
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
            self._render_multi_day_view(1)
        else:
            self._render_multi_day_view(self._view_day_count())
        self._on_grid_configure()

    def _lane_column_layout(self, n_appts: int, lane: int) -> tuple[int, int]:
        """Map lane index to grid column + columnspan across the four lane columns."""
        if n_appts <= 0:
            return 0, 1
        base = _SCHED_LANE_COLS // n_appts
        extra = _SCHED_LANE_COLS % n_appts
        col = 0
        for i in range(n_appts):
            span = base + (1 if i < extra else 0)
            if i == lane:
                return col, span
            col += span
        return lane, 1

    def _plan_appt_slot_groups(self, n_slots: int) -> list[dict]:
        """Same-time appointments share width; each keeps its own vertical span."""
        by_slot_time: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for appt in self._appointments:
            day_key = appt.get("date") or ""
            start_time = appt.get("start_time") or ""
            if day_key and start_time:
                by_slot_time[(day_key, start_time)].append(appt)

        occupied: dict[tuple[str, int, int], bool] = defaultdict(bool)
        result: list[dict] = []

        for (day_key, start_time), appts in sorted(by_slot_time.items()):
            appts.sort(key=lambda a: (a.get("patient_label") or a.get("patient_id") or ""))
            remaining = list(appts)
            slot = slot_index(start_time)
            while remaining and slot < n_slots:
                batch = remaining[:_MAX_SLOT_LANES]
                placements: list[dict] = []
                for appt in batch:
                    span = calendar_row_span(appt)
                    lane = None
                    for candidate in range(_MAX_SLOT_LANES):
                        if all(
                            not occupied[(day_key, slot + offset, candidate)]
                            for offset in range(span)
                        ):
                            lane = candidate
                            break
                    if lane is None:
                        break
                    for offset in range(span):
                        occupied[(day_key, slot + offset, lane)] = True
                    placements.append({
                        "appt": appt,
                        "lane": lane,
                        "span": span,
                    })

                if not placements:
                    slot += 1
                    continue

                n_placed = len(placements)
                for item in placements:
                    grid_col, colspan = self._lane_column_layout(n_placed, item["lane"])
                    item["grid_col"] = grid_col
                    item["colspan"] = colspan

                result.append({
                    "day_key": day_key,
                    "start_time": start_time,
                    "slot": slot,
                    "placements": placements,
                })
                remaining = remaining[len(placements):]
                if remaining:
                    slot += 1
        return result

    def _render_multi_day_view(self, num_days: int) -> None:
        host = self._grid_host
        start = self._view_start_date()
        n_slots = day_slot_count()
        time_w = 46 if self._layout_compact else 52

        host.columnconfigure(0, weight=0, minsize=time_w)
        for d in range(num_days):
            host.columnconfigure(d + 1, weight=1, uniform="sched_day")

        if num_days > 1:
            tk.Label(host, text="", bg=COLOR_CARD, width=2).grid(row=0, column=0, sticky="nw")
            for d in range(num_days):
                day_date = start + timedelta(days=d)
                is_today = day_date == date.today()
                head_bg = "#EEF2FF" if is_today else "#F8FAFC"
                head = tk.Frame(
                    host, bg=head_bg,
                    highlightbackground=COLOR_BORDER, highlightthickness=1,
                )
                head.grid(row=0, column=d + 1, sticky="nsew", padx=(1, 0))
                tk.Label(
                    head, text=day_date.strftime("%a"), bg=head_bg, fg=COLOR_MUTED,
                    font=self._font("small"),
                ).pack(anchor="w", padx=4, pady=(4, 0))
                tk.Label(
                    head, text=str(day_date.day), bg=head_bg,
                    fg=COLOR_ACCENT if is_today else COLOR_TEXT,
                    font=self._font("section"),
                ).pack(anchor="w", padx=4, pady=(0, 4))
            grid_row_offset = 1
        else:
            grid_row_offset = 0

        slot_h = self._slot_h

        # Each day gets one frame spanning all slot rows.
        # Background cells and appointment blocks are ALL placed with place()
        # so their heights are pixel-exact and never influence each other.
        day_frames: dict[str, tk.Frame] = {}
        for d in range(num_days):
            day_date = start + timedelta(days=d)
            day_frame = tk.Frame(host, bg=COLOR_CARD)
            day_frame.grid(
                row=grid_row_offset, column=d + 1, rowspan=n_slots, sticky="nsew",
                padx=(1, 0),
            )
            day_frame.grid_propagate(False)
            day_frames[day_date.isoformat()] = day_frame

        for slot in range(n_slots):
            grid_row = grid_row_offset + slot
            host.rowconfigure(grid_row, minsize=slot_h, weight=0)
            if slot % 4 == 0:
                tk.Label(
                    host, text=time_label_for_slot(slot), bg=COLOR_CARD,
                    fg=COLOR_MUTED, font=self._font("small"),
                    anchor="e", width=6,
                ).grid(row=grid_row, column=0, sticky="ne", padx=(2, 4))

            for d in range(num_days):
                day_date = start + timedelta(days=d)
                day_frame = day_frames[day_date.isoformat()]
                # Full-width background cell at exact pixel position
                y = slot * slot_h
                self._make_slot_cell_placed(
                    day_frame, y=y, slot_h=slot_h,
                    day=day_date, slot=slot,
                )

        # Group appointments by day for easy lookup
        groups_by_day: dict[str, list[dict]] = defaultdict(list)
        for group in self._plan_appt_slot_groups(n_slots):
            groups_by_day[group["day_key"]].append(group)

        for d in range(num_days):
            day_date = start + timedelta(days=d)
            day_frame = day_frames[day_date.isoformat()]
            for group in groups_by_day.get(day_date.isoformat(), []):
                placements = group["placements"]
                n_appts = len(placements)
                if n_appts == 0:
                    continue

                slot = group["slot"]
                y = slot * slot_h
                # Normalize lane indices to 0-based positions within this group
                sorted_lanes = sorted(item["lane"] for item in placements)
                lane_pos = {lane: pos for pos, lane in enumerate(sorted_lanes)}

                content_relw = 0.9 if n_appts < _MAX_SLOT_LANES else 1.0
                lane_relw = content_relw / n_appts

                for item in placements:
                    pos = lane_pos[item["lane"]]
                    relx = pos * lane_relw
                    h = item["span"] * slot_h - 2
                    # Single-slot appts: always one line (no wrap).
                    # Multi-slot appts: allow wrap only when double-booked and narrow.
                    if item["span"] == 1:
                        wrap = 0
                    elif n_appts > 1:
                        wrap = max(40, int(lane_relw * 200))
                    else:
                        wrap = 0
                    block = self._make_appt_block_placed(
                        day_frame, item["appt"],
                        relx=relx, y=y + 1, relwidth=lane_relw, height=h,
                        wraplength=wrap,
                    )
                    try:
                        block.tkraise()
                    except tk.TclError:
                        pass

                if n_appts < _MAX_SLOT_LANES:
                    strip = self._make_slot_add_strip_placed(
                        day_frame,
                        day=day_date,
                        start_time=group["start_time"],
                        slot=slot,
                    )
                    strip.place(relx=content_relw, y=y + 1, relwidth=1.0 - content_relw, height=slot_h - 2)
                    try:
                        strip.tkraise()
                    except tk.TclError:
                        pass

        self._apply_calendar_column_widths(num_days)

    def _make_clickable_cell(self, frame: tk.Frame, bg: str, on_click) -> None:
        """Attach click + hover bindings to a frame and all its children."""
        def _hover_in(_e=None, w=frame, c=bg):
            try:
                if w.cget("bg") == c:
                    w.configure(bg="#F8FAFC")
            except tk.TclError:
                pass

        def _hover_out(_e=None, w=frame, c=bg):
            try:
                if w.cget("bg") == "#F8FAFC":
                    w.configure(bg=c)
            except tk.TclError:
                pass

        frame.bind("<Button-1>", lambda _e: on_click())
        frame.bind("<Enter>", _hover_in)
        frame.bind("<Leave>", _hover_out)

    def _make_slot_cell_placed(
        self,
        parent: tk.Misc,
        *,
        y: int,
        slot_h: int,
        day: date,
        slot: int,
    ) -> tk.Frame:
        """Full-width background cell positioned with place()."""
        cell = tk.Frame(
            parent, bg="#FFFFFF",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
            cursor="hand2",
        )
        cell.place(x=0, y=y, relwidth=1.0, height=slot_h)
        start_time = time_for_slot(slot)
        self._make_clickable_cell(
            cell, "#FFFFFF",
            lambda d=day, t=start_time: self._new_appointment(default_date=d, default_time=t),
        )
        return cell

    def _make_slot_add_strip_placed(
        self,
        parent: tk.Misc,
        *,
        day: date,
        slot: int,
        start_time: str | None = None,
    ) -> tk.Frame:
        """Right-edge ~10% strip to add another patient — positioned by caller."""
        strip = tk.Frame(
            parent, bg="#FFFFFF",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
            cursor="hand2",
        )
        book_time = (start_time or time_for_slot(slot)).strip()
        self._make_clickable_cell(
            strip, "#FFFFFF",
            lambda d=day, t=book_time: self._new_appointment(default_date=d, default_time=t),
        )
        return strip

    def _make_appt_block_placed(
        self,
        parent: tk.Misc,
        appt: dict,
        *,
        relx: float,
        y: int,
        relwidth: float,
        height: int,
        wraplength: int = 0,
    ) -> tk.Frame:
        """Appointment block positioned with place() — height is pixel-exact."""
        style = appt.get("display_style") or DISPLAY_STYLES["scheduled"]
        block = tk.Frame(
            parent, bg=style["bg"],
            highlightbackground=style["border"], highlightthickness=1,
            cursor="hand2",
        )
        block.place(relx=relx, y=y, relwidth=relwidth, height=height)

        label_text = appt_block_label(appt)
        if appt.get("chart_signed"):
            label_text += " ✓"

        lbl = tk.Label(
            block,
            text=label_text,
            bg=style["bg"], fg=style["fg"],
            font=self._font("small"),
            anchor="w", justify="left",
            wraplength=wraplength if wraplength > 0 else 0,
        )
        lbl.place(relx=0, rely=0.5, relwidth=1.0, anchor="w", x=4)

        for widget in (block, lbl):
            widget.bind("<Button-1>", lambda _e, a=appt: self._show_appt_menu(a))
            widget.bind("<Double-Button-1>", lambda _e, a=appt: self._edit_appointment(a))
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
