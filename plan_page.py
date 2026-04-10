# plan_page.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from scrollframe import ScrollFrame

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
        "Manual therapy (MRT)",
        "Vibratory Massage",
        "Therapeutic exercise",
        "Neuromuscular re-education",
        "Modalities (e-stim / heat and/or ice, spinal traction therapy)",
        "Home exercise program (HEP)",
        "Referral / co-management",
        "Final Evaluation - Released from Active Chiropractic Care. The patient will continue treatment with his pain management doctor."
    ]

    REGIONS = [
        "Cervical",
        "Cervical / Thoracic",
        "Thoracic",
        "Thoracic / Lumbar",
        "Lumbar",
        "Pelvis / SI",
        "Bilateral shoulders",
        "Right shoulder",
        "Left shoulder",
        "Bilateral elbows",
        "Right elbow",
        "Left elbow",
        "Bilateral wrists/hands",
        "Right wrist/hand",
        "Left wrist/hand",
        "Bilateral hips",
        "Right hip",
        "Left hip",
        "Bilateral knees",
        "Right knee",
        "Left knee",
        "Bilateral ankles/feet",
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
    DURATION_CHOICES = ["2", "3", "4", "4 to 6", "6", "8", "12", "(other)"]
    REEVAL_CHOICES = ["2 weeks", "4 weeks", "4 to 6 weeks", "6 weeks", "8 weeks", "12 visits", "18 visits", "(other)"]

    def _disable_mousewheel_on_cb(self, cb: ttk.Combobox):
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")
    
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
            self.freq_var.set("")
            self.duration_var.set("")
            self.reeval_var.set("")

            self.freq_other_var.set("")
            self.duration_other_var.set("")
            self.reeval_other_var.set("")

            self.auto_plan_var.set(True)  # you start in auto mode
            self.custom_notes_var.set("")
            
            self.current_em_code.set("")
            self.exam_notes_var.set("")

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
            
            try:
                self.clear_all_plan_checkboxes()
            except Exception:
                pass

            # 2) schedule vars (examples — rename to your actual vars)
            for v in getattr(self, "_schedule_vars", {}).values():
                try: v.set("")
                except Exception: pass

            for attr in ("_freq_var", "_duration_var", "_reeval_var"):
                v = getattr(self, attr, None)
                if v is not None:
                    try: v.set("")
                    except Exception: pass

            # --- Clear Services Provided Today ---
            self.therapy_data.clear()
            self.cmt_data.clear()
            self.current_cmt_notes.set("")
            try:
                self.cmt_notes_text.delete("1.0", "end")
            except Exception:
                pass
            self.current_cmt_code.set("")
            self.last_cmt_code = ""
            try:
                self.update_services_summary_labels()
            except Exception:
                pass
            
            self.print_schedule_var.set(True)
            try:
                self._refresh_print_schedule_btn()
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
        self._section_buttons = {}

        # optional providers (like HOI): can be set by app
        self._patient_provider = None  # fn -> dict
        self._dx_provider = None       # fn -> list[str] or dict

        # vars
        self.freq_var = tk.StringVar(value="3")
        self.duration_var = tk.StringVar(value="4")
        self.reeval_var = tk.StringVar(value="4 weeks")

        self.freq_other_var = tk.StringVar(value="")
        self.duration_other_var = tk.StringVar(value="")
        self.reeval_other_var = tk.StringVar(value="")

        self.auto_plan_var = tk.BooleanVar(value=True)
        self._last_auto_plan = bool(self.auto_plan_var.get())  # ✅ track toggle state

        # PDF / output toggle: if False, schedule lines do NOT print on PDF
        self.print_schedule_var = tk.BooleanVar(value=True)


        self.custom_notes_var = tk.StringVar(value="")

        # multi-check stores
        self._care_vars = {label: tk.BooleanVar(value=False) for label in self.CARE_TYPES}
        self._region_vars = {label: tk.BooleanVar(value=False) for label in self.REGIONS}
        self._goal_vars = {label: tk.BooleanVar(value=False) for label in self.GOALS}

                # -----------------------------
        # Services Provided Today (CMT + Therapy)
        # -----------------------------
        self.therapy_data = {}  # dict[str, dict[str, tuple[bool,str]]]
        self.cmt_data = {}      # dict[str, tuple[bool, list[bool]]]
        self.current_cmt_code = tk.StringVar(value="")
        self.last_cmt_code = ""  # used to detect code changes + clear details
        
        self.current_cmt_notes = tk.StringVar()

        self.current_em_code = tk.StringVar(value="")
        self.exam_notes_var  = tk.StringVar(value="")
        
        # E/M (Exam) code + exam notes (no PDF yet)
        # self.current_em_code = tk.StringVar(value="")
        # self.exam_notes = ""  # stored as plain string for now
        
        # UI
        self._build_ui()
        self._wire_triggers()

        # start with generated narrative
        self._regen_plan_now()

    
    def open_therapy_modalities_from_therapy_only(self):
        """
        Therapy Only shortcut:
        opens Services Provided Today and jumps the user to Therapy Modalities list.
        Uses the exact same PlanPage popup + state.
        """
        self.open_services_main_popup()

        # After the popup is created, your listbox exists; focus it.
        try:
            if getattr(self, "_therapy_listbox", None) is not None:
                self._therapy_listbox.focus_set()
                # optional: make sure the top of the list is visible
                self._therapy_listbox.see(0)
        except Exception:
            pass
    
    
    def set_subjectives_clear_regions_fn(self, fn):
        """
        fn: callable that clears ALL subjective block body regions to "(none)"
        """
        self._subjectives_clear_regions_fn = fn
    
    def clear_all_plan_checkboxes(self):
        """
        Helper function: unchecks all Plan of Care checkboxes.

        Affects ONLY:
        - Care Types
        - Regions Treated
        - Goals
        - Narratives

        Does NOT modify:
        - Schedule
        - Narrative
        - Services
        - Notes
        - Any other state
        """

        # Care Types
        for var in self._care_vars.values():
            try:
                var.set(False)
            except Exception:
                pass

        # Regions Treated
        for var in self._region_vars.values():
            try:
                var.set(False)
            except Exception:
                pass

        # Goals
        for var in self._goal_vars.values():
            try:
                var.set(False)
            except Exception:
                pass

        # Auto-generate Plan narrative checkbox
        try:
            self.auto_plan_var.set(False)
        except Exception:
            pass

        # Clear narrative textbox
        try:
            self._clear_plan_text()
        except Exception:
            pass


    def _toggle_print_schedule(self):
        """
        Standalone toggle: affects PDF output only.
        Does NOT touch schedule UI, does NOT change narrative generation.
        """
        self.print_schedule_var.set(not bool(self.print_schedule_var.get()))
        try:
            self._refresh_print_schedule_btn()
        except Exception:
            pass
        self.clear_all_plan_checkboxes()

        # NEW: clear Subjectives body regions via callback
        fn = getattr(self, "_subjectives_clear_regions_fn", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
        
        self._notify_change()       
        
    
    def _refresh_print_schedule_btn(self):
        """
        Makes the button look/feel like a toggle.
        """
        on = bool(self.print_schedule_var.get())
        # You can rename these labels however you like
        txt = "Schedule: ON (PDF)" if on else "Schedule: OFF (PDF)"
        try:
            self._btn_print_schedule.configure(text=txt)
        except Exception:
            pass

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

        # --- Permanent buttons (like HOI Blocks) ---
        top = ttk.Frame(self)
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text="Plan Sections:").pack(side="left", padx=(0, 8))

        self.block_buttons = ttk.Frame(top)
        self.block_buttons.pack(side="left", fill="x", expand=True)

        def add_btn(name):
            btn = tk.Button(
                self.block_buttons,
                text=name,
                font=("Segoe UI", 10),
                relief="raised",
                bd=1,
                command=lambda n=name: self._show_plan_block(n),
            )
            btn.pack(side="left", padx=4)
            self._section_buttons[name] = btn

        add_btn("Treatment")
        add_btn("Schedule")
        add_btn("Regions Treated")
        add_btn("Services Provided Today")
        add_btn("Goals")
        add_btn("Notes")
        add_btn("Plan Narrative")

        # --- Container (stacked frames, like HOI) ---
        self.scroll = ScrollFrame(self)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rowconfigure(2, weight=1)

        self._plan_container = ttk.Frame(self.scroll.content)
        self._plan_container.pack(fill="both", expand=True)
        self._plan_container.grid_rowconfigure(0, weight=1)
        self._plan_container.grid_columnconfigure(0, weight=1)

        self._plan_frames = {
            "Treatment": self._build_treatment_frame(self._plan_container),
            "Schedule": self._build_schedule_frame(self._plan_container),
            "Regions Treated": self._build_regions_frame(self._plan_container),
            "Services Provided Today": self._build_services_frame(self._plan_container),
            "Goals": self._build_goals_frame(self._plan_container),
            "Notes": self._build_notes_frame(self._plan_container),
            "Plan Narrative": self._build_narrative_frame(self._plan_container),
        }

        for f in self._plan_frames.values():
            f.grid(row=0, column=0, sticky="nsew")

        # Show Treatment by default
        self._show_plan_block("Treatment")

        # enable/disable (other) entries initially
        self._sync_other_entries()

    def _build_treatment_frame(self, parent):
        """Treatment / Care types block."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)

        treat_section = CollapsibleSection(f, "Treatment", start_open=True)
        treat_section.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))
        treat_section.columnconfigure(0, weight=1)

        treat_box = treat_section.content
        treat_box.columnconfigure(0, weight=1)

        care_box = ttk.Labelframe(treat_box, text="Care Type(s)")
        care_box.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        care_box.columnconfigure(0, weight=1)

        for i, label in enumerate(self.CARE_TYPES):
            cb = ttk.Checkbutton(care_box, text=label, variable=self._care_vars[label])
            cb.grid(row=i, column=0, sticky="w", padx=8, pady=2)

        return f

    def _build_schedule_frame(self, parent):
        """Schedule block (frequency, duration, re-eval, auto-generate, print toggle)."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)

        sched_section = CollapsibleSection(f, "Schedule", start_open=True)
        sched_section.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))
        sched_section.columnconfigure(0, weight=1)

        sched_box = sched_section.content
        sched_box.columnconfigure(1, weight=1)

        ttk.Label(sched_box, text="Visits per week:").grid(row=0, column=0, sticky="w", padx=8, pady=(10, 4))
        self.freq_cb = ttk.Combobox(
            sched_box, textvariable=self.freq_var, values=self.FREQ_CHOICES, width=12, state="readonly"
        )
        self._disable_mousewheel_on_cb(self.freq_cb)
        self.freq_cb.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 4))
        self.freq_other_entry = ttk.Entry(sched_box, textvariable=self.freq_other_var, width=16)
        self.freq_other_entry.grid(row=0, column=2, sticky="w", padx=8, pady=(10, 4))
        ttk.Label(sched_box, text="(if other)").grid(row=0, column=3, sticky="w", padx=4, pady=(10, 4))

        ttk.Label(sched_box, text="Duration (weeks):").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.duration_cb = ttk.Combobox(
            sched_box, textvariable=self.duration_var, values=self.DURATION_CHOICES, width=12, state="readonly"
        )
        self._disable_mousewheel_on_cb(self.duration_cb)
        self.duration_cb.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.duration_other_entry = ttk.Entry(sched_box, textvariable=self.duration_other_var, width=16)
        self.duration_other_entry.grid(row=1, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(sched_box, text="(if other)").grid(row=1, column=3, sticky="w", padx=4, pady=4)

        ttk.Label(sched_box, text="Re-evaluation:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.reeval_cb = ttk.Combobox(
            sched_box, textvariable=self.reeval_var, values=self.REEVAL_CHOICES, width=12, state="readonly"
        )
        self._disable_mousewheel_on_cb(self.reeval_cb)
        self.reeval_cb.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.reeval_other_entry = ttk.Entry(sched_box, textvariable=self.reeval_other_var, width=16)
        self.reeval_other_entry.grid(row=2, column=2, sticky="w", padx=8, pady=4)
        ttk.Label(sched_box, text="(if other)").grid(row=2, column=3, sticky="w", padx=4, pady=4)

        auto_row = ttk.Frame(sched_box)
        auto_row.grid(row=3, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 2))
        ttk.Checkbutton(
            auto_row,
            text="Auto-generate Plan narrative",
            variable=self.auto_plan_var
        ).pack(side="left")

        self._btn_print_schedule = ttk.Button(
            sched_box,
            text="Schedule: ON (PDF)",
            command=self._toggle_print_schedule
        )
        self._btn_print_schedule.grid(row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 8))
        self._refresh_print_schedule_btn()

        return f
    
    def _build_regions_frame(self, parent):
        """Regions Treated block (region checkboxes only)."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)

        reg_section = CollapsibleSection(f, "Regions Treated", start_open=True)
        reg_section.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))
        reg_section.columnconfigure(0, weight=1)

        reg_box = reg_section.content
        reg_box.columnconfigure(0, weight=1)
        reg_box.columnconfigure(1, weight=1)

        regions_frame = ttk.Frame(reg_box)
        regions_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        regions_frame.columnconfigure(0, weight=1)
        regions_frame.columnconfigure(1, weight=1)

        for i, label in enumerate(self.REGIONS):
            r = i // 2
            c = i % 2
            cb = ttk.Checkbutton(regions_frame, text=label, variable=self._region_vars[label])
            cb.grid(row=r, column=c, sticky="w", padx=8, pady=2)

        return f
    
    def _build_services_frame(self, parent):
        """Services Provided Today block (button + summary)."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        self._build_services_ui(f)

        return f
    
    def _build_goals_frame(self, parent):
        """Goals block."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)

        goals_box = ttk.Labelframe(f, text="Goals")
        goals_box.grid(row=0, column=0, sticky="nsew", padx=0, pady=6)
        goals_box.columnconfigure(0, weight=1)

        for i, label in enumerate(self.GOALS):
            cb = ttk.Checkbutton(goals_box, text=label, variable=self._goal_vars[label])
            cb.grid(row=i, column=0, sticky="w", padx=8, pady=2)

        return f
    
    def _build_notes_frame(self, parent):
        """Notes block (custom notes textbox)."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        notes_box = ttk.Labelframe(f, text="Notes")
        notes_box.grid(row=0, column=0, sticky="nsew", padx=0, pady=6)
        notes_box.columnconfigure(0, weight=1)
        notes_box.rowconfigure(0, weight=1)

        self.custom_notes = tk.Text(notes_box, height=10, wrap="word")
        self.custom_notes.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        return f
    
    def _build_narrative_frame(self, parent):
        """Plan Narrative block."""
        f = ttk.Frame(parent)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        narr_section = CollapsibleSection(f, "Plan Narrative", start_open=False)
        narr_section.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 12))
        narr_section.columnconfigure(0, weight=1)

        bottom = narr_section.content
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=1)

        self.plan_text = tk.Text(bottom, height=10, wrap="word")
        self.plan_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        btns = ttk.Frame(bottom)
        btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Regenerate", command=self._regen_plan_now).pack(side="left")
        ttk.Button(btns, text="Clear", command=self._clear_plan_text).pack(side="left", padx=(8, 0))

        return f
    
    def _show_plan_block(self, name: str):
        """Raise the selected plan block frame (tkRaise pattern, like HOI Blocks)."""
        if name in self._plan_frames:
            self._plan_frames[name].tkraise()
            for key, btn in self._section_buttons.items():
                btn.configure(font=("Segoe UI", 10, "bold") if key == name else ("Segoe UI", 10))

    # -------- Public focus helpers (for Live Preview clicks) --------
    def focus_care_types_block(self) -> None:
        """Live Preview: 'Care Type(s):' -> Treatment block."""
        self._show_plan_block("Treatment")

    def focus_schedule_block(self) -> None:
        """Live Preview: 'Frequency'/'Duration'/'Re-evaluation' -> Schedule block."""
        self._show_plan_block("Schedule")

    def focus_regions_treated_block(self) -> None:
        """Live Preview: 'Regions:' -> Regions Treated block."""
        self._show_plan_block("Regions Treated")

    def focus_services_block(self) -> None:
        """Live Preview: 'Services Provided Today' -> Services block."""
        self._show_plan_block("Services Provided Today")

    def focus_goals_block(self) -> None:
        """Live Preview: 'Goals:' -> Goals block."""
        self._show_plan_block("Goals")

    def focus_cmt_popup(self) -> None:
        """Live Preview: open Services Provided Today popup (CMT code selection)."""
        self._show_plan_block("Services Provided Today")
        self.open_services_main_popup()

    def focus_cmt_details_popup(self) -> None:
        """Live Preview: open CMT details popup (segments/techniques)."""
        self._show_plan_block("Services Provided Today")
        root = self.winfo_toplevel()
        selection = (self.current_cmt_code.get() or "").strip()
        if selection:
            self.open_cmt_details_popup(root)
        else:
            self.open_services_main_popup()

    def focus_therapy_popup(self, modality_code: str = "") -> None:
        """Live Preview: open therapy details popup for a specific modality code."""
        self._show_plan_block("Services Provided Today")
        root = self.winfo_toplevel()
        if not modality_code:
            self.open_services_main_popup()
            return
        therapy_name = ""
        list_idx = 0
        for i, opt in enumerate(getattr(self, "_therapy_options", [])):
            if opt.startswith(modality_code):
                therapy_name = opt
                list_idx = i
                break
        if therapy_name:
            self.open_therapy_details_popup(root, therapy_name, list_idx)
        else:
            self.open_therapy_details_popup(root, therapy_name, list_idx)

    def focus_exam_popup(self) -> None:
        """Live Preview: open Services Provided Today popup (exam fields live there)."""
        self._show_plan_block("Services Provided Today")
        self.open_services_main_popup()
    
    
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
    
    # =========================================================
    # Services Provided Today (embedded in PlanPage)
    # =========================================================

    def _build_services_ui(self, parent: ttk.Frame):
        """
        Right-side UI next to Regions Treated:
          - Button opens popup
          - Scrollable summary area (centered labels)
        """
        btn = ttk.Button(parent, text="Services Provided Today", command=self.open_services_main_popup)
        btn.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        parent.columnconfigure(0, weight=1)

        # Scrollable summary container
        container = ttk.Frame(parent)
        container.grid(row=1, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self._services_canvas = tk.Canvas(container, highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=self._services_canvas.yview)
        self._services_canvas.configure(yscrollcommand=sb.set)

        self._services_canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._services_inner = ttk.Frame(self._services_canvas)
        self._services_window = self._services_canvas.create_window((0, 0), window=self._services_inner, anchor="nw")

        def _on_inner_configure(_e=None):
            self._services_canvas.configure(scrollregion=self._services_canvas.bbox("all"))

        def _on_canvas_configure(e):
            # keep inner frame width equal to canvas width so labels center nicely
            self._services_canvas.itemconfigure(self._services_window, width=e.width)

        self._services_inner.bind("<Configure>", _on_inner_configure)
        self._services_canvas.bind("<Configure>", _on_canvas_configure)

        # This is where summary labels go
        self._services_label_frame = ttk.Frame(self._services_inner)
        self._services_label_frame.pack(fill="both", expand=True)

        # initial paint
        self.update_services_summary_labels()

    def update_services_summary_labels(self):
        # Clear existing labels
        try:
            for w in self._services_label_frame.winfo_children():
                w.destroy()
        except Exception:
            return

        # 1) CMT Summary
        if self.cmt_data and (self.current_cmt_code.get() or "").strip():
            code_num = (self.current_cmt_code.get().split(":")[0] or "").strip()

            area_map = {
                "Cervical": "CS", "Thoracic": "TS", "Lumbar": "LS",
                "Sacral": "S", "Pelvic": "P",
                "Right Shoulder": "R Shld", "Left Shoulder": "L Shld",
                "Right Elbow": "R Elb", "Left Elbow": "L Elb",
                "Right Wrist": "R Wst", "Left Wrist": "L Wst",
                "Right Hip": "R Hip", "Left Hip": "L Hip",
            }

            adjusted_areas = []
            techs_used = set()

            for area, data in self.cmt_data.items():
                # data = (adjusted_bool, [tech_bool...])
                if data and data[0]:
                    adjusted_areas.append(area_map.get(area, area))
                    for i, tech in enumerate(["Activator", "Diversified", "Thompson Drop Technique"]):
                        try:
                            if data[1][i]:
                                techs_used.add(tech)
                        except Exception:
                            pass

            area_str = f": {', '.join(adjusted_areas)}" if adjusted_areas else ""
            tech_str = f"\n{', '.join(sorted(techs_used))}" if techs_used else ""
            cmt_text = f"• {code_num}{area_str}{tech_str}"

            ttk.Label(
                self._services_label_frame,
                text=cmt_text,
                font=("Segoe UI", 9),
                justify="center",
            ).pack(anchor="center", pady=(0, 8))
            
        # 1.5) Exam CPT Summary (E/M)
        em = (self.current_em_code.get() or "").strip()
        notes = (self.exam_notes_var.get() or "").strip()

        if em or notes:
            code_num = em.split(":")[0].strip() if em and ":" in em else (em.strip() if em else "")
            lines = []
            if code_num:
                lines.append(f"• {code_num}: Exam Code")
            else:
                lines.append("• Exam Notes")  # if notes exist but no code selected

            if notes:
                lines.append(notes)

            ttk.Label(
                self._services_label_frame,
                text="\n".join(lines),
                font=("Segoe UI", 9),
                justify="center",
                wraplength=340,
            ).pack(anchor="center", pady=(0, 8))

        # 2) Therapy Summaries
        for therapy, data in (self.therapy_data or {}).items():
            parts = (therapy or "").split(": ")
            code_num = parts[0].strip() if parts else ""
            modality_name = parts[1].strip() if len(parts) > 1 else ""

            parts_summary = []
            for part, values in (data or {}).items():
                try:
                    checked = bool(values[0])
                    minutes = (values[1] or "").strip()
                except Exception:
                    checked, minutes = False, ""

                if checked:
                    short_part = (part or "").replace(" Spine", "S").replace("Right ", "R ").replace("Left ", "L ")
                    short_part = short_part.replace("CervicalS", "CS").replace("ThoracicS", "TS").replace("LumbarS", "LS")
                    if minutes:
                        parts_summary.append(f"({short_part} {minutes}m)")
                    else:
                        parts_summary.append(f"{short_part}")

            if parts_summary:
                ther_text = f"• {code_num}: {modality_name}\n{', '.join(parts_summary)}"
                ttk.Label(
                    self._services_label_frame,
                    text=ther_text,
                    font=("Segoe UI", 9),
                    justify="center",
                ).pack(anchor="center", pady=(0, 8))

    # -------------------------
    # MAIN POPUP
    # -------------------------
    def open_services_main_popup(self):
        root = self.winfo_toplevel()
        popup = tk.Toplevel(root)
        popup.title("Services Provided Today")
        popup.geometry("500x600")
        popup.grab_set()

        frame = ttk.Frame(popup, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Chiropractic CMT (Pick One):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))

        cmt_options = [
            "98940: Spinal, 1-2 regions",
            "98941: Spinal, 3-4 regions",
            "98942: Spinal, 5 regions",
            "98943: Extraspinal",
            "0000: No CMT Today",
        ]

        cmt_combo = ttk.Combobox(frame, textvariable=self.current_cmt_code, values=cmt_options, state="readonly", width=50)
        self._disable_mousewheel_on_cb(cmt_combo)
        cmt_combo.pack(pady=(0, 20))
        cmt_combo.bind("<<ComboboxSelected>>", lambda e: self.handle_cmt_interaction(popup))
        
                
        ttk.Label(
            frame,
            text="CMT Notes (Optional):",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", pady=(10, 5))

        notes_frame = ttk.Frame(frame)
        notes_frame.pack(fill="both", expand=True)

        self.cmt_notes_text = tk.Text(
            notes_frame,
            height=4,
            wrap="word",
            font=("Segoe UI", 9)
        )
        self.cmt_notes_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(notes_frame, command=self.cmt_notes_text.yview)
        scroll.pack(side="right", fill="y")

        self.cmt_notes_text.config(yscrollcommand=scroll.set)
        
        # preload saved notes (if any)
        try:
            self.cmt_notes_text.delete("1.0", "end")
            self.cmt_notes_text.insert("1.0", self.current_cmt_notes.get() or "")
        except Exception:
            pass

        # ---- NEW: E/M Exam CPT (Pick One) ----
        ttk.Label(frame, text="CPT Exam Code (Pick One):", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 5)
        )
                
        em_options = [
            "99202: Office or other outpatient visit for the evaluation and management of a new patient, which requires a medically appropriate history and/or examination and straightforward medical decision making.",      
            "99202-25: A significant, separately identifiable evaluation and management service was performed alongside today's CMT to conduct a formal re-evaluation of the patient’s progress, encompassing a medically appropriate history, physical examination, and low-level medical decision-making to update the treatment plan.",
            "99203: Office or other outpatient visit for the evaluation and management (E/M) of a new patient, which requires a medically appropriate history and/or examination and low level of medical decision making (MDM).",
            "99203-25: In addition to the CMT and/or physiotherpay performed today, a significant and separately identifiable E/M service was provided for this new patient, requiring a medically appropriate history, physical examination, and a moderate level of medical decision-making to establish the clinical baseline and treatment plan.",
            "99212: Office or other outpatient visit for the evaluation and management of a new patient, which requires a medically appropriate history and/or examination and straightforward medical decision making.", 
            "99212-25: A significant, separately identifiable evaluation and management service was performed alongside today's CMT to conduct a formal re-evaluation of the patient’s progress, encompassing a medically appropriate history, physical examination, and low-level medical decision-making to update the treatment plan.",
            "99213: Office or other outpatient visit for the evaluation and management (E/M) of a new patient, which requires a medically appropriate history and/or examination and low level of medical decision making (MDM).",
            "99213-25: A significant, separately identifiable evaluation and management service was performed alongside the CMT and/or physiotherapy to facilitate a re-evaluation of the patient's condition, including a medically appropriate history and examination with low to moderate medical decision-making to assess clinical improvement.",
            "99214: Office/outpatient visit (moderate complexity)",
            "99214-25: Office/outpatient visit (moderate complexity)",
        ]

        em_combo = ttk.Combobox(
            frame,
            textvariable=self.current_em_code,
            values=em_options,
            state="readonly",
            width=50
        )
        self._disable_mousewheel_on_cb(em_combo)
        em_combo.pack(pady=(0, 12))

        # ---- NEW: Exam Notes (starts 1 line, expands) ----
        ttk.Label(frame, text="Exam Notes:", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 5)
        )

        notes_box = tk.Text(frame, height=1, wrap="word")
        notes_box.pack(fill="x", pady=(0, 16))

        # preload saved notes (if any)
        try:
            notes_box.insert("1.0", self.exam_notes_var.get() or "")
        except Exception:
            pass

        def delete_exam():
            self.current_em_code.set("")
            self.exam_notes_var.set("")
            try:
                notes_box.delete("1.0", "end")
            except Exception:
                pass
            self.update_services_summary_labels()            
        
        ttk.Button(frame, style='Right.TButton', text="Delete Exam", command=delete_exam).pack(pady=(0,10))

        def _autosize_notes(_evt=None):
            """
            Expand/shrink Text height based on content lines.
            Clamped so it doesn't grow forever inside the popup.
            """
            try:
                # count display lines roughly by newline count
                lines = int(notes_box.index("end-1c").split(".")[0])
                lines = max(1, min(lines, 6))  # 1..6 lines max
                notes_box.configure(height=lines)
            except Exception:
                pass

        notes_box.bind("<KeyRelease>", _autosize_notes)
        _autosize_notes()


        ttk.Label(frame, text="Therapy Modalities (Click once to Setup):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="x", pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self._therapy_listbox = tk.Listbox(
            list_frame,
            selectmode="multiple",
            height=8,
            exportselection=0,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._therapy_listbox.yview)

        self._therapy_options = [
            "97012: Mechanical Traction",
            "97014: Electric Stimulation",
            "97124: MRT / Vibratory Massage",
            "97110: Therapeutic Exercise",
            "97140: Manual Therapy",
            "97035: Ultrasound",
            "97010: Hot/Cold Pack",
            "97112: Neuromuscular Re-ed",
        ]

        self._therapy_listbox.delete(0, "end")
        for item in self._therapy_options:
            self._therapy_listbox.insert("end", item)
            if item in (self.therapy_data or {}):
                self._therapy_listbox.selection_set(self._therapy_options.index(item))

        self._therapy_listbox.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._therapy_listbox.bind("<ButtonRelease-1>", self.handle_therapy_click)

        def on_close():
            
            # Save CMT notes
            try:
                self.current_cmt_notes.set(self.cmt_notes_text.get("1.0", "end-1c").strip())
            except Exception:
                self.current_cmt_notes.set("")
            
            try:
                self.exam_notes_var.set(notes_box.get("1.0", "end-1c").strip())
            except Exception:
                self.exam_notes_var.set("")                
            

            self.update_services_summary_labels()
            popup.destroy()

        ttk.Button(frame, text="Save and Exit", command=on_close).pack(side="bottom", pady=10)

    # -------------------------
    # CMT LOGIC
    # -------------------------
    def handle_cmt_interaction(self, parent_win):
        new_selection = (self.current_cmt_code.get() or "").strip()
        if new_selection != (self.last_cmt_code or ""):
            self.cmt_data.clear()
            self.last_cmt_code = new_selection
        self.open_cmt_details_popup(parent_win)

    def open_cmt_details_popup(self, parent_win):
        selection = (self.current_cmt_code.get() or "").strip()
        if not selection:
            return

        c_win = tk.Toplevel(parent_win)
        c_win.title(f"Details: {selection.split(':')[0]}")
        c_win.geometry("450x500")
        c_win.grab_set()

        if "98943" in selection:
            areas = ["Right Shoulder", "Left Shoulder", "Right Elbow", "Left Elbow", "Right Wrist", "Left Wrist", "Right Hip", "Left Hip"]
        else:
            areas = ["Cervical", "Thoracic", "Lumbar", "Sacral", "Pelvic"]

        container = ttk.Frame(c_win)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)

        scroll_frame = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _on_scrollframe_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfigure(win_id, width=e.width)

        scroll_frame.bind("<Configure>", _on_scrollframe_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        active_cmt_ui_vars = {}

        for area in areas:
            saved_adj, saved_techs = self.cmt_data.get(area, (False, [False, False, False]))
            adj_var = tk.BooleanVar(value=bool(saved_adj))
            tech_vars = [tk.BooleanVar(value=bool(t)) for t in (saved_techs or [False, False, False])]

            af = ttk.LabelFrame(scroll_frame, text=area, padding=5)
            af.pack(fill="x", pady=5, padx=5)

            ttk.Checkbutton(af, text=f"Adjusted {area}", variable=adj_var).pack(anchor="w")

            tf = ttk.Frame(af)
            tf.pack(padx=20)

            for i, name in enumerate(["Activator", "Diversified", "Thompson"]):
                ttk.Checkbutton(tf, text=name, variable=tech_vars[i]).pack(side="left", padx=2)

            active_cmt_ui_vars[area] = (adj_var, tech_vars)

        def save_cmt():
            for a, vars_ in active_cmt_ui_vars.items():
                self.cmt_data[a] = (vars_[0].get(), [t.get() for t in vars_[1]])
            self.update_services_summary_labels()
            c_win.destroy()

        def delete_cmt():
            self.cmt_data.clear()
            self.last_cmt_code = ""
            self.current_cmt_code.set("")
            self.update_services_summary_labels()
            c_win.destroy()

        btn_f = ttk.Frame(c_win)
        btn_f.pack(pady=10)

        ttk.Button(btn_f, text="Save Adjustments", command=save_cmt).pack(side="left", padx=5)
        ttk.Button(btn_f, text="Delete Sections", command=delete_cmt).pack(side="left", padx=5)

    # -------------------------
    # THERAPY LOGIC
    # -------------------------
    def handle_therapy_click(self, event):
        lb = event.widget
        idx = lb.nearest(event.y)
        therapy_name = lb.get(idx)
        lb.selection_set(idx)
        self.open_therapy_details_popup(event.widget.winfo_toplevel(), therapy_name, idx)

    def open_therapy_details_popup(self, parent_win, therapy_name, list_idx):
        t_win = tk.Toplevel(parent_win)
        t_win.title(f"Setup: {therapy_name}")
        t_win.geometry("500x600")
        t_win.grab_set()

        body_parts = [
            "Cervical Spine / Thoracic Spine / Lumbar Spine", "Cervical Spine", "Cervical / Thoracic Spine", "Thoracic Spine", "Lumbar Spine",
            "Thoracic / Lumbar Spine", "Bilateral Shoulders", "Right Shoulder", "Left Shoulder",
            "Bilateral Elbows", "Right Elbow", "Left Elbow", "Bilateral Hips", "Right Hip", "Left Hip", "Bilateral Knees", "Right Knee", "Left Knee",
            "Bilateral Ankles/Feet", "Right Ankle/Foot", "Left Ankle/Foot",
        ]

        active_therapy_vars = {}

        for part in body_parts:
            saved_checked, saved_time = self.therapy_data.get(therapy_name, {}).get(part, (False, ""))
            b_var = tk.BooleanVar(value=bool(saved_checked))
            s_var = tk.StringVar(value=str(saved_time) if saved_time is not None else "")

            def on_toggle(bv=b_var, sv=s_var):
                if not bv.get():
                    # unchecked -> clear minutes
                    sv.set("")
                    return

                # checked -> default minutes if blank (do NOT overwrite edits)
                if not (sv.get() or "").strip():
                    sv.set("15")

            row = ttk.Frame(t_win, padding=2)
            row.pack(fill="x", padx=20)

            ttk.Entry(row, textvariable=s_var, width=5).pack(side="right")
            ttk.Checkbutton(row, text=part, variable=b_var, command=on_toggle).pack(
                side="left", fill="x", expand=True
            )

            active_therapy_vars[part] = (b_var, s_var)

        def save_therapy():
            self.therapy_data[therapy_name] = {p: (v[0].get(), v[1].get()) for p, v in active_therapy_vars.items()}
            self.update_services_summary_labels()
            t_win.destroy()

        def delete_therapy():
            if therapy_name in self.therapy_data:
                del self.therapy_data[therapy_name]
            try:
                self._therapy_listbox.selection_clear(list_idx)
            except Exception:
                pass
            self.update_services_summary_labels()
            t_win.destroy()

        btn_frame = ttk.Frame(t_win)
        btn_frame.pack(pady=20)

        ttk.Button(btn_frame, text="Save This Therapy", command=save_therapy).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Delete Sections", command=delete_therapy).pack(side="left", padx=5)


    # ---------------- Public struct API (save/load) ----------------
    def get_struct(self) -> dict:
        return {
            "print_schedule_pdf": bool(self.print_schedule_var.get()),

            # Existing fields (KEEP for backward compatibility)
            "care_types": self._selected(self._care_vars),
            "regions": self._selected(self._region_vars),

            # These are used by PDF + narrative generation
            "frequency_per_week": self._freq_value(),
            "duration_weeks": self._duration_value(),
            "reeval": self._reeval_value(),

            "goals": self._selected(self._goal_vars),
            "custom_notes": self.custom_notes.get("1.0", "end").strip(),
            "auto_enabled": bool(self.auto_plan_var.get()),
            "plan_text": self.plan_text.get("1.0", "end").strip(),

            # NEW — preserves combobox selection state exactly
            "schedule_state": {
                "freq_choice": self.freq_var.get(),
                "freq_other": self.freq_other_var.get(),

                "duration_choice": self.duration_var.get(),
                "duration_other": self.duration_other_var.get(),

                "reeval_choice": self.reeval_var.get(),
                "reeval_other": self.reeval_other_var.get(),
            },

            # Services Provided Today
            "services": {
                "cmt_code": (self.current_cmt_code.get() or ""),
                "last_cmt_code": (self.last_cmt_code or ""),
                "cmt_data": self.cmt_data or {},
                "cmt_notes": (self.current_cmt_notes.get() or ""),
                "em_code": (self.current_em_code.get() or ""),
                "exam_notes": (self.exam_notes_var.get() or ""),
                "therapy_data": self.therapy_data or {},
            },
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
            freq   = _clean(str(d.get("frequency_per_week", "")))
            dur    = _clean(str(d.get("duration_weeks", "")))
            reeval = _clean(str(d.get("reeval", "")))

            # Restore exact combobox state (including "(other)")
            sched = d.get("schedule_state") or {}            
            

            if sched:
                self.freq_var.set(sched.get("freq_choice", self.freq_var.get()))
                self.freq_other_var.set(sched.get("freq_other", ""))

                self.duration_var.set(sched.get("duration_choice", self.duration_var.get()))
                self.duration_other_var.set(sched.get("duration_other", ""))

                self.reeval_var.set(sched.get("reeval_choice", self.reeval_var.get()))
                self.reeval_other_var.set(sched.get("reeval_other", ""))

            self.print_schedule_var.set(bool(d.get("print_schedule_pdf", True)))
            try:
                self._refresh_print_schedule_btn()
            except Exception:
                pass


            self._sync_other_entries()

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
            
            # --- Services Provided Today ---
            services = d.get("services") or {}
            self.current_cmt_code.set(services.get("cmt_code", "") or "")
            self.last_cmt_code = services.get("last_cmt_code", "") or ""
            self.cmt_data = services.get("cmt_data", {}) or {}
            self.current_cmt_notes.set(services.get("cmt_notes", "") or "") 
            self.current_em_code.set(services.get("em_code", "") or "")
            self.exam_notes_var.set(services.get("exam_notes", "") or "")
            self.therapy_data = services.get("therapy_data", {}) or {}            

            self._sync_other_entries()
        finally:
            self._loading = False
            
        try:
            self.update_services_summary_labels()
        except Exception:
            pass

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

