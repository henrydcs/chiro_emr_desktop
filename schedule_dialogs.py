# schedule_dialogs.py — New / edit appointment dialogs.
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

from appt_types_storage import (
    default_duration_for_label,
    list_active_appt_type_labels,
)
from providers_storage import default_provider_label, list_active_provider_labels
from schedule_engine import DAY_END_HOUR, DAY_START_HOUR, SLOT_MINUTES
from schedule_storage import (
    APPT_STATUSES,
    DEFAULT_DURATION_MIN,
    delete_appointment,
    new_appointment_id,
    upsert_appointment,
)
from shell_app import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    list_all_patients,
)


def _time_choices() -> list[str]:
    out: list[str] = []
    start = DAY_START_HOUR * 60
    last = DAY_END_HOUR * 60
    t = start
    while t <= last:
        h = t // 60
        m = t % 60
        out.append(f"{h:02d}:{m:02d}")
        t += SLOT_MINUTES
    return out


class AppointmentDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        appt: dict | None = None,
        default_date: date | None = None,
        default_time: str | None = None,
        on_saved: callable | None = None,
    ):
        super().__init__(master)
        self.title("Appointment")
        self.configure(bg=COLOR_CARD)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self._appt = dict(appt or {})
        self._on_saved = on_saved
        self._patients = list_all_patients()
        self._patient_by_label: dict[str, dict] = {}
        for rec in self._patients:
            lbl = rec.get("label") or ""
            if lbl:
                self._patient_by_label[lbl] = rec

        self._build(default_date or date.today(), default_time)
        self.update_idletasks()
        self.geometry("460x560")
        self.minsize(460, 480)
        self.resizable(True, True)

    def _build(self, default_date: date, default_time: str | None = None) -> None:
        outer = tk.Frame(self, bg=COLOR_CARD)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        wrap = tk.Frame(outer, bg=COLOR_CARD)
        wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=(14, 8))

        tk.Label(wrap, text="Appointment", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_SECTION).pack(anchor="w", pady=(0, 10))

        tk.Label(wrap, text="Patient", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        search_row = tk.Frame(wrap, bg=COLOR_CARD)
        search_row.pack(fill="x", pady=(2, 8))
        self._search_var = tk.StringVar()
        ent = tk.Entry(
            search_row, textvariable=self._search_var, font=FONT_BASE,
            relief="solid", bd=1, highlightthickness=1,
            highlightbackground=COLOR_BORDER,
        )
        ent.pack(side="left", fill="x", expand=True, ipady=4)
        ent.bind("<KeyRelease>", self._filter_patients)

        labels = sorted(self._patient_by_label.keys(), key=str.lower)
        self._patient_var = tk.StringVar(
            value=(self._appt.get("patient_label") or "")
        )
        self._patient_combo = ttk.Combobox(
            wrap, textvariable=self._patient_var, values=labels,
            state="readonly", font=FONT_BASE,
        )
        self._patient_combo.pack(fill="x", pady=(0, 8))

        tk.Label(wrap, text="Date (YYYY-MM-DD)", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        self._date_var = tk.StringVar(
            value=(self._appt.get("date") or default_date.isoformat())
        )
        tk.Entry(
            wrap, textvariable=self._date_var, font=FONT_BASE,
            relief="solid", bd=1, highlightthickness=1,
            highlightbackground=COLOR_BORDER,
        ).pack(fill="x", ipady=4, pady=(2, 8))

        tk.Label(wrap, text="Type", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        type_labels = list_active_appt_type_labels()
        if not type_labels:
            type_labels = ["Chiro Visit"]
        default_type = (self._appt.get("appt_type") or type_labels[0]).strip()
        if default_type not in type_labels:
            type_labels = [default_type] + type_labels
        self._type_var = tk.StringVar(value=default_type)
        type_combo = ttk.Combobox(
            wrap, textvariable=self._type_var, values=type_labels,
            state="readonly", font=FONT_BASE,
        )
        type_combo.pack(fill="x", pady=(2, 8))
        type_combo.bind("<<ComboboxSelected>>", self._on_type_selected)

        row = tk.Frame(wrap, bg=COLOR_CARD)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="Time", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).grid(row=0, column=0, sticky="w")
        tk.Label(row, text="Duration (min)", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).grid(row=0, column=1, sticky="w", padx=(12, 0))

        times = _time_choices()
        default_time = (
            self._appt.get("start_time")
            or default_time
            or "09:00"
        )
        if default_time not in times:
            times = [default_time] + times
        self._time_var = tk.StringVar(value=default_time)
        ttk.Combobox(
            row, textvariable=self._time_var, values=times,
            state="readonly", width=10, font=FONT_BASE,
        ).grid(row=1, column=0, sticky="w")

        self._dur_var = tk.StringVar(
            value=str(int(
                self._appt.get("duration_min")
                or default_duration_for_label(default_type)
                or DEFAULT_DURATION_MIN
            ))
        )
        ttk.Combobox(
            row, textvariable=self._dur_var,
            values=["15", "30", "45", "60", "90"],
            state="readonly", width=8, font=FONT_BASE,
        ).grid(row=1, column=1, sticky="w", padx=(12, 0))

        tk.Label(wrap, text="Provider", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        provider_labels = list_active_provider_labels()
        default_provider = (self._appt.get("provider") or default_provider_label() or "").strip()
        if default_provider and default_provider not in provider_labels:
            provider_labels = [default_provider] + provider_labels
        if not provider_labels:
            provider_labels = [""]
        self._provider_var = tk.StringVar(value=default_provider)
        prov_state = "readonly" if provider_labels and provider_labels != [""] else "normal"
        ttk.Combobox(
            wrap, textvariable=self._provider_var, values=provider_labels,
            state=prov_state, font=FONT_BASE,
        ).pack(fill="x", pady=(2, 8))

        tk.Label(wrap, text="Status", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        self._status_var = tk.StringVar(value=(self._appt.get("status") or "scheduled"))
        ttk.Combobox(
            wrap, textvariable=self._status_var, values=list(APPT_STATUSES),
            state="readonly", font=FONT_BASE,
        ).pack(fill="x", pady=(2, 8))

        tk.Label(wrap, text="Notes", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_BASE).pack(anchor="w")
        self._notes = tk.Text(
            wrap, height=3, font=FONT_BASE, relief="solid", bd=1,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        self._notes.pack(fill="x", pady=(2, 4))
        if self._appt.get("notes"):
            self._notes.insert("1.0", self._appt.get("notes"))

        btn_bar = tk.Frame(
            outer, bg="#F8FAFC",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
        )
        btn_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        btns = tk.Frame(btn_bar, bg="#F8FAFC", padx=4, pady=10)
        btns.pack(fill="x")
        if self._appt.get("appt_id"):
            tk.Button(
                btns, text="Delete", command=self._delete,
                bg="#F8FAFC", fg="#B91C1C", relief="flat",
                font=FONT_BASE, cursor="hand2",
            ).pack(side="left")
        save_label = "Save changes" if self._appt.get("appt_id") else "Create appointment"
        tk.Button(
            btns, text="Cancel", command=self.destroy,
            bg="#F8FAFC", fg=COLOR_MUTED, relief="flat",
            font=FONT_BASE, padx=8, cursor="hand2",
        ).pack(side="right", padx=(6, 0))
        tk.Button(
            btns, text=save_label, command=self._save,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

    def _on_type_selected(self, _event=None) -> None:
        label = (self._type_var.get() or "").strip()
        if label:
            self._dur_var.set(str(default_duration_for_label(label)))

    def _filter_patients(self, _event=None) -> None:
        q = (self._search_var.get() or "").strip().lower()
        if not q:
            labels = sorted(self._patient_by_label.keys(), key=str.lower)
        else:
            labels = sorted(
                [
                    lbl for lbl, rec in self._patient_by_label.items()
                    if q in lbl.lower()
                    or q in (rec.get("last") or "").lower()
                    or q in (rec.get("first") or "").lower()
                    or q in (rec.get("patient_id") or "").lower()
                ],
                key=str.lower,
            )
        self._patient_combo.configure(values=labels)
        if len(labels) == 1:
            self._patient_var.set(labels[0])

    def _save(self) -> None:
        label = (self._patient_var.get() or "").strip()
        rec = self._patient_by_label.get(label)
        if not rec:
            messagebox.showerror("Appointment", "Select a patient.", parent=self)
            return
        raw_date = (self._date_var.get() or "").strip()
        try:
            date.fromisoformat(raw_date)
        except Exception:
            messagebox.showerror("Appointment", "Enter date as YYYY-MM-DD.", parent=self)
            return
        try:
            duration = int(self._dur_var.get() or DEFAULT_DURATION_MIN)
        except Exception:
            duration = DEFAULT_DURATION_MIN

        payload = {
            "appt_id": self._appt.get("appt_id") or new_appointment_id(),
            "patient_id": rec.get("patient_id") or "",
            "patient_label": label,
            "patient_folder": rec.get("folder") or "",
            "date": raw_date,
            "start_time": (self._time_var.get() or "09:00").strip(),
            "duration_min": duration,
            "appt_type": (self._type_var.get() or "Follow-up").strip(),
            "provider": (self._provider_var.get() or "").strip(),
            "status": (self._status_var.get() or "scheduled").strip(),
            "notes": self._notes.get("1.0", "end-1c").strip(),
            "exam_path": self._appt.get("exam_path") or "",
            "created_at": self._appt.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        }
        saved = upsert_appointment(payload)
        if self._on_saved:
            self._on_saved(saved)
        self.destroy()

    def _delete(self) -> None:
        aid = (self._appt.get("appt_id") or "").strip()
        if not aid:
            self.destroy()
            return
        if not messagebox.askyesno(
            "Delete appointment",
            "Remove this appointment from the schedule?",
            parent=self,
        ):
            return
        delete_appointment(aid)
        if self._on_saved:
            self._on_saved(None)
        self.destroy()
