# plan_page.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

AUTO_PLAN_TAG = "[AUTO:PLAN]"


def _clean(s: str) -> str:
    return (s or "").strip()


def _dedupe_preserve_order(items):
    seen = set()
    out = []
    for x in items or []:
        s = _clean(x)
        k = s.lower()
        if not s or k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out

class CollapsibleSection(ttk.Frame):
    """
    Simple collapsible section: a header row with a toggle button,
    and a content frame that can be shown/hidden.
    """
    def __init__(self, parent, title: str, start_open: bool = True):
        super().__init__(parent)

        self._open = tk.BooleanVar(value=start_open)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self._btn = ttk.Button(header, text="▼" if start_open else "▶", width=2, command=self.toggle)
        self._btn.grid(row=0, column=0, sticky="w")

        ttk.Label(header, text=title, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.content = ttk.Frame(self)
        self.content.grid(row=1, column=0, sticky="nsew")

        self.columnconfigure(0, weight=1)

        if not start_open:
            self.content.grid_remove()

    def toggle(self):
        is_open = self._open.get()
        self._open.set(not is_open)
        if is_open:
            self._btn.configure(text="▶")
            self.content.grid_remove()
        else:
            self._btn.configure(text="▼")
            self.content.grid()



class PlanPage(ttk.Frame):
    """
    Plan section page:
      - Care types (multi-check)
      - Regions treated (multi-check)
      - Frequency + duration
      - Goals (multi-check)
      - Re-eval timing
      - Custom notes (free text)
      - Auto-generated plan narrative (Text) with AUTO tag logic like HOI MOI
    """

    CARE_TYPES = [
        "Chiropractic manipulation",
        "Manual therapy",
        "Therapeutic exercise",
        "Neuromuscular re-education",
        "Modalities (e-stim / ultrasound / heat/ice)",
        "Home exercise program (HEP)",
        "Referral / co-management",
    ]

    REGIONS = [
        "Cervical",
        "Thoracic",
        "Lumbar",
        "Pelvis / SI",
        "Right shoulder",
        "Left shoulder",
        "Right elbow",
        "Left elbow",
        "Right wrist/hand",
        "Left wrist/hand",
        "Right hip",
        "Left hip",
        "Right knee",
        "Left knee",
        "Right ankle/foot",
        "Left ankle/foot",
    ]

    GOALS = [
        "Decrease pain",
        "Decrease spasm",
        "Improve range of motion",
        "Improve strength / stability",
        "Improve ADLs / function",
        "Improve sleep tolerance",
        "Return to work / sport",
    ]

    FREQ_CHOICES = ["1", "2", "3", "4", "5", "(other)"]
    DURATION_CHOICES = ["2", "3", "4", "6", "8", "12", "(other)"]
    REEVAL_CHOICES = ["2 weeks", "4 weeks", "6 weeks", "8 weeks", "12 visits", "18 visits", "(other)"]

    def has_content(self) -> bool:
        try:
            s = self.get_struct() or {}
            return bool((s.get("plan_text") or "").strip())
        except Exception:
            return False

    
    def reset(self):
        """
        Clears PlanPage UI to clean defaults.
        Safe to call for Start New Case / Clear Exam.
        """
        self._loading = True
        try:
            # --- Defaults (match your __init__ defaults) ---
            self.freq_var.set("3")
            self.duration_var.set("6")
            self.reeval_var.set("12 visits")

            self.freq_other_var.set("")
            self.duration_other_var.set("")
            self.reeval_other_var.set("")

            self.auto_plan_var.set(True)  # you start in auto mode
            self.custom_notes_var.set("")

            # --- Uncheck all multi-selects ---
            for v in self._care_vars.values():
                v.set(False)
            for v in self._region_vars.values():
                v.set(False)
            for v in self._goal_vars.values():
                v.set(False)

            # --- Clear text widgets ---
            try:
                self.custom_notes.delete("1.0", "end")
            except Exception:
                pass

            try:
                self.plan_text.delete("1.0", "end")
            except Exception:
                pass

            # keep UI states correct
            self._sync_other_entries()

        finally:
            self._loading = False

        # After clearing, regenerate (since auto is True)
        self._regen_plan_now()
        self._notify_change()



    def __init__(self, parent, on_change=None):
        super().__init__(parent)
        self.on_change = on_change

        self._loading = False

        # optional providers (like HOI): can be set by app
        self._patient_provider = None  # fn -> dict
        self._dx_provider = None       # fn -> list[str] or dict

        # vars
        self.freq_var = tk.StringVar(value="3")
        self.duration_var = tk.StringVar(value="6")
        self.reeval_var = tk.StringVar(value="12 visits")

        self.freq_other_var = tk.StringVar(value="")
        self.duration_other_var = tk.StringVar(value="")
        self.reeval_other_var = tk.StringVar(value="")

        self.auto_plan_var = tk.BooleanVar(value=True)
        self._last_auto_plan = bool(self.auto_plan_var.get())  # ✅ track toggle state

        self.custom_notes_var = tk.StringVar(value="")

        # multi-check stores
        self._care_vars = {label: tk.BooleanVar(value=False) for label in self.CARE_TYPES}
        self._region_vars = {label: tk.BooleanVar(value=False) for label in self.REGIONS}
        self._goal_vars = {label: tk.BooleanVar(value=False) for label in self.GOALS}

        # UI
        self._build_ui()
        self._wire_triggers()

        # start with generated narrative
        self._regen_plan_now()

    # ---------------- providers ----------------
    def set_patient_provider(self, fn):
        """
        fn -> dict: {"first":"", "last":"", "sex":"Male/Female/(unknown)"}
        """
        self._patient_provider = fn
        self._regen_plan_now()

    def set_dx_provider(self, fn):
        """
        fn -> list[str] or dict with relevant info; optional.
        """
        self._dx_provider = fn
        self._regen_plan_now()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)

        title = ttk.Label(self, text="PLAN OF CARE", font=("Segoe UI", 14, "bold"))
        title.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))

        # Main panels
        top = ttk.Frame(self)
        top.grid(row=1, column=0, sticky="ew", padx=10)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        treat_section = CollapsibleSection(top, "Treatment", start_open=True)
        treat_section.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        treat_section.columnconfigure(0, weight=1)

        sched_section = CollapsibleSection(top, "Schedule", start_open=True)
        sched_section.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        sched_section.columnconfigure(0, weight=1)

        left = treat_section.content
        right = sched_section.content

        left.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)


        # Care types
        care_box = ttk.Labelframe(left, text="Care Type(s)")
        care_box.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        care_box.columnconfigure(0, weight=1)

        for i, label in enumerate(self.CARE_TYPES):
            cb = ttk.Checkbutton(care_box, text=label, variable=self._care_vars[label])
            cb.grid(row=i, column=0, sticky="w", padx=8, pady=2)

        reg_section = CollapsibleSection(left, "Regions Treated", start_open=True)
        reg_section.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        reg_box = reg_section.content
        reg_box.columnconfigure(0, weight=1)
        reg_box.columnconfigure(1, weight=1)


        # two columns for regions
        for i, label in enumerate(self.REGIONS):
            r = i // 2
            c = i % 2
            cb = ttk.Checkbutton(reg_box, text=label, variable=self._region_vars[label])
            cb.grid(row=r, column=c, sticky="w", padx=8, pady=2)

        # Schedule controls
        ttk.Label(right, text="Visits per week:").grid(row=0, column=0, sticky="w", padx=8, pady=(10, 4))
        self.freq_cb = ttk.Combobox(right, textvariable=self.freq_var, values=self.FREQ_CHOICES, width=12, state="readonly")
        self.freq_cb.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 4))
        self.freq_other_entry = ttk.Entry(right, textvariable=self.freq_other_var, width=16)
        self.freq_other_entry.grid(row=0, column=2, sticky="w", padx=8, pady=(10, 4))
        ttk.Label(right, text="(if other)").grid(row=0, column=3, sticky="w", padx=4, pady=(10, 4))

        ttk.Label(right, text="Duration (weeks):").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.duration_cb = ttk.Combobox(right, textvariable=self.duration_var, values=self.DURATION_CHOICES, width=12, state="readonly")
        self.duration_cb.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.duration_other_entry = ttk.Entry(right, textvariable=self.duration_other_var, width=16)
        self.duration_other_entry.grid(row=1, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(right, text="(if other)").grid(row=1, column=3, sticky="w", padx=4, pady=4)

        ttk.Label(right, text="Re-evaluation:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.reeval_cb = ttk.Combobox(right, textvariable=self.reeval_var, values=self.REEVAL_CHOICES, width=12, state="readonly")
        self.reeval_cb.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.reeval_other_entry = ttk.Entry(right, textvariable=self.reeval_other_var, width=16)
        self.reeval_other_entry.grid(row=2, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(right, text="(if other)").grid(row=2, column=3, sticky="w", padx=4, pady=4)

        auto_row = ttk.Frame(right)
        auto_row.grid(row=3, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 2))
        ttk.Checkbutton(auto_row, text="Auto-generate Plan narrative", variable=self.auto_plan_var).pack(side="left")

        # Goals + notes
        mid = ttk.Frame(self)
        mid.grid(row=2, column=0, sticky="ew", padx=10)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)

        goals_box = ttk.Labelframe(mid, text="Goals")
        goals_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=6)
        goals_box.columnconfigure(0, weight=1)

        for i, label in enumerate(self.GOALS):
            cb = ttk.Checkbutton(goals_box, text=label, variable=self._goal_vars[label])
            cb.grid(row=i, column=0, sticky="w", padx=8, pady=2)

        notes_box = ttk.Labelframe(mid, text="Custom Notes (optional)")
        notes_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=6)
        notes_box.columnconfigure(0, weight=1)

        self.custom_notes = tk.Text(notes_box, height=10, wrap="word")
        self.custom_notes.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        # Narrative (collapsible)
        narr_section = CollapsibleSection(self, "Plan Narrative", start_open=False)  # collapsed by default
        narr_section.grid(row=3, column=0, sticky="nsew", padx=10, pady=(6, 12))
        narr_section.columnconfigure(0, weight=1)

        bottom = narr_section.content  # <-- use this as the container

        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=1)

        self.plan_text = tk.Text(bottom, height=10, wrap="word")
        self.plan_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        btns = ttk.Frame(bottom)
        btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Regenerate", command=self._regen_plan_now).pack(side="left")
        ttk.Button(btns, text="Clear", command=self._clear_plan_text).pack(side="left", padx=(8, 0))


        # enable/disable (other) entries initially
        self._sync_other_entries()

    def _wire_triggers(self):
        def _general_changed(*_):
            if self._loading:
                return

            self._sync_other_entries()

            # Only regenerate on general changes if auto is enabled
            if self.auto_plan_var.get():
                self._regen_plan_now()

            self._notify_change()

        def _auto_toggled(*_):
            if self._loading:
                return

            now_auto = bool(self.auto_plan_var.get())
            last_auto = getattr(self, "_last_auto_plan", now_auto)

            # Only act when it truly changed
            if now_auto == last_auto:
                return

            if now_auto:
                # turned ON -> generate immediately
                self._regen_plan_now()
            else:
                # turned OFF -> clear ONLY if current content is auto-generated
                cur = self.plan_text.get("1.0", "end").strip()
                if cur.startswith(AUTO_PLAN_TAG):
                    self._clear_plan_text()

            self._last_auto_plan = now_auto
            self._notify_change()

        # combobox selections
        self.freq_var.trace_add("write", _general_changed)
        self.duration_var.trace_add("write", _general_changed)
        self.reeval_var.trace_add("write", _general_changed)

        self.freq_other_var.trace_add("write", _general_changed)
        self.duration_other_var.trace_add("write", _general_changed)
        self.reeval_other_var.trace_add("write", _general_changed)

        # auto checkbox gets its OWN handler
        self.auto_plan_var.trace_add("write", _auto_toggled)

        # checkbox changes
        for v in list(self._care_vars.values()) + list(self._region_vars.values()) + list(self._goal_vars.values()):
            v.trace_add("write", _general_changed)

        # text widgets
        self.custom_notes.bind("<<Modified>>", self._on_custom_notes_modified)
        self.plan_text.bind("<<Modified>>", self._on_plan_text_modified)

    def _notify_change(self):
        if callable(self.on_change):
            try:
                self.on_change()
            except Exception:
                pass

    def _sync_other_entries(self):
        self.freq_other_entry.configure(state=("normal" if self.freq_var.get() == "(other)" else "disabled"))
        self.duration_other_entry.configure(state=("normal" if self.duration_var.get() == "(other)" else "disabled"))
        self.reeval_other_entry.configure(state=("normal" if self.reeval_var.get() == "(other)" else "disabled"))

    def _on_custom_notes_modified(self, _evt):
        if self._loading:
            self.custom_notes.edit_modified(False)
            return
        self.custom_notes.edit_modified(False)
        if self.auto_plan_var.get():
            self._regen_plan_now()
        self._notify_change()

    def _on_plan_text_modified(self, _evt):
        if self._loading:
            self.plan_text.edit_modified(False)
            return
        # user edited the narrative: keep it, but if it still has AUTO tag we keep it as auto
        self.plan_text.edit_modified(False)
        self._notify_change()

    def _clear_plan_text(self):
        self._set_plan_text("")

    # ---------------- Data extraction ----------------
    def _selected(self, var_map):
        return [k for (k, v) in var_map.items() if v.get()]

    def _patient_ctx(self):
        if callable(self._patient_provider):
            try:
                return self._patient_provider() or {}
            except Exception:
                return {}
        return {}

    def _dx_ctx(self):
        if callable(self._dx_provider):
            try:
                return self._dx_provider() or []
            except Exception:
                return []
        return []

    def _freq_value(self) -> str:
        v = _clean(self.freq_var.get())
        if v == "(other)":
            return _clean(self.freq_other_var.get())
        return v

    def _duration_value(self) -> str:
        v = _clean(self.duration_var.get())
        if v == "(other)":
            return _clean(self.duration_other_var.get())
        return v

    def _reeval_value(self) -> str:
        v = _clean(self.reeval_var.get())
        if v == "(other)":
            return _clean(self.reeval_other_var.get())
        return v

    # ---------------- Narrative generation ----------------
    def _regen_plan_now(self):
        if self._loading:
            return
        if not self.auto_plan_var.get():
            return

        care = self._selected(self._care_vars)
        regions = self._selected(self._region_vars)
        goals = self._selected(self._goal_vars)

        freq = self._freq_value()
        dur = self._duration_value()
        reeval = self._reeval_value()

        notes = self.custom_notes.get("1.0", "end").strip()

        # name/pronouns optional (kept simple)
        ctx = self._patient_ctx()
        first = _clean(ctx.get("first", ""))
        # dx optional
        dx = self._dx_ctx()
        dx_list = []
        if isinstance(dx, dict):
            dx_list = [str(x) for x in dx.get("dx", [])] if "dx" in dx else []
        elif isinstance(dx, (list, tuple)):
            dx_list = [str(x) for x in dx]
        dx_list = _dedupe_preserve_order(dx_list)

        parts = []
        parts.append(AUTO_PLAN_TAG)

        # Sentence 1: treatment types + regions
        if care and regions:
            parts.append(
                f"The patient will receive {self._join_human(care)} directed to {self._join_human(regions)}."
            )
        elif care:
            parts.append(f"The patient will receive {self._join_human(care)}.")
        elif regions:
            parts.append(f"Care will be directed to {self._join_human(regions)}.")
        else:
            parts.append("A plan of care is recommended as clinically indicated.")

        # Sentence 2: schedule
        if freq and dur:
            parts.append(f"Recommended frequency is {freq} visit(s) per week for {dur} week(s).")
        elif freq:
            parts.append(f"Recommended frequency is {freq} visit(s) per week.")
        elif dur:
            parts.append(f"Recommended duration is {dur} week(s).")

        # Sentence 3: goals
        if goals:
            parts.append(f"Treatment goals include {self._join_human(goals, lower_first=True)}.")
        else:
            parts.append("Treatment goals include improving function and reducing symptoms.")

        # Sentence 4: dx reference optional
        if dx_list:
            parts.append(f"This plan is based on clinical findings consistent with: {self._join_human(dx_list)}.")

        # Sentence 5: reeval
        if reeval:
            parts.append(f"The patient will be re-evaluated at {reeval} to assess response and modify care as indicated.")

        # Sentence 6: consent
        parts.append("The patient verbalizes understanding and agrees with the plan of care.")

        # Optional notes appended at end
        # if notes:
        #     parts.append(notes)

        txt = " ".join([p for p in parts if _clean(p)])
        self._set_plan_text(txt)

    def _set_plan_text(self, txt: str):
        self._loading = True
        try:
            self.plan_text.delete("1.0", "end")
            self.plan_text.insert("1.0", txt or "")
        finally:
            self._loading = False

    @staticmethod
    def _join_human(items, lower_first=False) -> str:
        items = [str(x).strip() for x in (items or []) if str(x).strip()]
        if not items:
            return ""
        if lower_first and items:
            # lower-case first char for smoother mid-sentence list (Decrease pain -> decrease pain)
            items = [items[0][:1].lower() + items[0][1:]] + items[1:]
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"

    # ---------------- Public struct API (save/load) ----------------
    def get_struct(self) -> dict:
        return {
            "care_types": self._selected(self._care_vars),
            "regions": self._selected(self._region_vars),
            "frequency_per_week": self._freq_value(),
            "duration_weeks": self._duration_value(),
            "goals": self._selected(self._goal_vars),
            "reeval": self._reeval_value(),
            "custom_notes": self.custom_notes.get("1.0", "end").strip(),
            "auto_enabled": bool(self.auto_plan_var.get()),
            "plan_text": self.plan_text.get("1.0", "end").strip(),
        }

    def load_struct(self, d: dict):
        d = d or {}
        self._loading = True
        try:
            # checks
            care = set(d.get("care_types", []) or [])
            regions = set(d.get("regions", []) or [])
            goals = set(d.get("goals", []) or [])

            for k, v in self._care_vars.items():
                v.set(k in care)
            for k, v in self._region_vars.items():
                v.set(k in regions)
            for k, v in self._goal_vars.items():
                v.set(k in goals)

            # schedule values
            freq = _clean(str(d.get("frequency_per_week", ""))) or "3"
            dur  = _clean(str(d.get("duration_weeks", ""))) or "6"
            reeval = _clean(str(d.get("reeval", ""))) or "12 visits"


            # if not in list, map to (other)
            self._set_combo_or_other(self.freq_var, self.freq_other_var, self.FREQ_CHOICES, freq)
            self._set_combo_or_other(self.duration_var, self.duration_other_var, self.DURATION_CHOICES, dur)
            self._set_combo_or_other(self.reeval_var, self.reeval_other_var, self.REEVAL_CHOICES, reeval)

            self.auto_plan_var.set(bool(d.get("auto_enabled", True)))

            # text areas
            self.custom_notes.delete("1.0", "end")
            self.custom_notes.insert("1.0", d.get("custom_notes", "") or "")

            self.plan_text.delete("1.0", "end")
            self.plan_text.insert("1.0", d.get("plan_text", "") or "")

            self._sync_other_entries()
        finally:
            self._loading = False

        # If auto is enabled and plan is blank or auto-tagged, regen
        if self.auto_plan_var.get():
            current = self.plan_text.get("1.0", "end").strip()
            if not current or current.startswith(AUTO_PLAN_TAG):
                self._regen_plan_now()

    @staticmethod
    def _set_combo_or_other(combo_var: tk.StringVar, other_var: tk.StringVar, choices: list, value: str):
        value = _clean(value)
        if not value:
            return
        if value in choices and value != "(other)":
            combo_var.set(value)
            other_var.set("")
            return
        # not a preset -> other
        combo_var.set("(other)")
        other_var.set(value)

        # ---------------- Compatibility with older TextPage API ----------------
    def get_value(self) -> str:
        """
        Backwards-compatible: return the Plan narrative text only.
        This lets existing chiro_app.py code keep using .get_value().
        """
        return self.plan_text.get("1.0", "end").strip()

    def set_value(self, text: str):
        """
        Backwards-compatible: set only the Plan narrative text.
        If the text looks auto-generated, keep auto enabled.
        """
        self._loading = True
        try:
            self.plan_text.delete("1.0", "end")
            self.plan_text.insert("1.0", text or "")
        finally:
            self._loading = False

