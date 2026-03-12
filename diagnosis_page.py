# diagnosis_page.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from scrollframe import ScrollFrame

AUTO_TAG = "[AUTO:DX]"

def _strip_auto_tag(text: str) -> str:
    """
    Removes the trailing AUTO_TAG line if present.
    Keeps your internal marker but prevents it from contaminating output.
    """
    lines = (text or "").splitlines()
    if lines and lines[-1].strip() == AUTO_TAG:
        lines = lines[:-1]
    return "\n".join(lines).strip()

def _clean(s: str) -> str:
    return (s or "").strip()

# ----------------------------
DX_LIST: list[tuple[str, str]] = [
    # Head / neuro
    ("Concussion without loss of consciousness (initial encounter)", "S06.0X0A"),
    ("Concussion with loss of consciousness (initial encounter)", "S06.0X9A"),
    ("Post-traumatic headache, not intractable", "G44.309"),
    ("Post-traumatic headache, intractable", "G44.301"),
    ("Cervicogenic headache (clinical correlation)", "R51.9"),
    ("Dizziness / vertigo (clinical correlation)", "R42"),
    ("----------------------------------", "-----------------------------------"),

    # Cervical
    ("Herniated disc, Cervical Spine", "M50.20"),
    ("Cervical sprain/strain (whiplash)", "S13.4XXA"),  
    ("Radiculopathy, Cervical Region", "M54.12"),
    ("Cervical muscle spasm", "M62.838"),
    ("Cervical disc degeneration", "M50.30"),
    ("Cervical spinal stenosis", "M48.02"),
    ("Cervical spondylosis", "M47.812"),    
    ("Neck pain (cervicalgia)", "M54.2"),
    ("-----------------------------------", "-------------------------------"),

    # Thoracic
    ("Herniated disc, Thoracic Spine", "M51.24"),
    ("Thoracic sprain/strain", "S23.3XXA"),
    ("Thoracic muscle spasm", "M62.830"),
    ("Thoracic radiculopathy", "M54.14"),
    ("Thoracic spine pain", "M54.6"),    
    ("Thoracic spondylosis", "M47.814"),
    ("----------------------------------", "--------------------------"),
    

    # Lumbar / SI
    ("Herniated disc, Lumbar Spine", "M51.26"),
    ("Lumbar sprain/strain", "S33.5XXA"),
    ("Lumbar radiculopathy", "M54.16"),
    ("Lumbar muscle spasm", "M62.830"),
    ("Sacroiliac joint dysfunction", "M53.3"),
    ("Low back pain", "M54.50"),        
    ("Lumbar disc degeneration", "M51.36"),
    ("Lumbar spinal stenosis", "M48.061"),
    ("Lumbar spondylosis", "M47.816"),    
    ("--------------------------------", "---------------------------"), 

    # Shoulder / UE pain (keeping generic to avoid laterality pitfalls)
    ("Right shoulder sprain", "S43.401A"),
    ("Left shoulder sprain", "S43.402A"),    
    ("Right elbow sprain", "S53.401A"),
    ("Left elbow sprain", "S53.402A"),
    ("Right wrist sprain", "S63.501A"),
    ("Left wrist sprain", "S63.502A"),
    ("Right hand sprain", "S63.601A"),
    ("Left hand sprain", "S63.602A"),
    ("Finger pain", "M79.646"),
    ("--------------------------------", "---------------------------"), 

    # Hip / LE pain (generic)
    ("Right hip sprain", "S73.101A"),
    ("Left hip sprain", "S73.102A"),
    ("Right knee sprain", "S83.91XA"),
    ("Left knee sprain", "S83.92XA"),
    ("Right ankle sprain", "S93.401A"),
    ("Left ankle sprain", "S93.402A"),
    ("Right foot sprain", "S93.601A"),
    ("Left foot sprain", "S93.602A"),
    ("--------------------------------", "---------------------------"),   

    # Incident / mechanism (useful in PI documentation)
    ("Driver injured in unspecified motor-vehicle accident, traffic (initial encounter)", "V89.2XXA"),
    ("Passenger injured in unspecified motor-vehicle accident, traffic (initial encounter)", "V89.2XXA"),
    ("Fall on same level from slipping/tripping (initial encounter)", "W01.0XXA"),
    ("Dog bite (initial encounter)", "W54.0XXA"),
    ("--------------------------------", "---------------------------"), 

    # Common soft tissue
    ("Myofascial pain syndrome (clinical correlation)", "M79.18"),
    ("Contusion (clinical correlation)", "T14.8XXA"),
    ("Other (free text)", ""),

    
]


PROGNOSIS_CHOICES = ["(select)", "Poor", "Guarded", "Fair", "Good", "Excellent"]

def generate_prognosis_paragraph(self):
    prognosis_level = (self.prognosis_var.get() or "").strip()

    if not prognosis_level:
        return ""

    # 🔹 Special case: Guarded
    if prognosis_level.lower() == "guarded":
        return (
            "Based on the patient’s reported symptoms, objective findings, "
            "and functional impairments, the prognosis is currently assessed "
            f"as {prognosis_level}. Clinical improvement is anticipated with "
            "consistent participation in care and adherence to prescribed "
            "therapeutic recommendations."
        )

    # 🔹 Default paragraph for all other selections
    return (
        "Based on the patient’s clinical presentation, examination findings, "
        f"and overall health status, the prognosis is considered {prognosis_level}. "
        "Progress will be monitored and reassessed throughout the course of care."
    )

IMAGING_MODALITIES = ["(select)", "X-ray", "MRI", "CT", "Ultrasound"]
IMAGING_PARTS = [
    "(select)",
    "Cervical Spine", "Thoracic Spine", "Lumbar Spine",
    "Right Shoulder", "Left Shoulder", "B/L Shoulders",
    "Right Elbow", "Left Elbow", "B/L Elbows",
    "Right Wrist", "Left Wrist", "B/L Wrists",
    "Right Hip", "Left Hip", "B/L Hips",
    "Right Knee", "Left Knee", "B/L Knees",
    "Right Ankle", "Left Ankle", "B/L Ankles",
]

REFERRAL_CHOICES = [
    "(select)",
    "Orthopedist", "Neurologist", "Pain Management", "Primary Care",
    "Physical Therapy", "Radiology", "Chiropractic Specialty", "Psychology", "None at this time"
]


def _dx_display(label: str, icd10: str) -> str:
    icd10 = _clean(icd10)
    return f"{label} — {icd10}" if icd10 else label


DX_DISPLAY_VALUES = [_dx_display(lbl, code) for (lbl, code) in DX_LIST]


def _parse_display_to_pair(display: str) -> tuple[str, str]:
    """
    Reverse the combobox display back into (label, icd10)
    """
    s = _clean(display)
    if " — " in s:
        left, right = s.split(" — ", 1)
        return _clean(left), _clean(right)
    for lbl, code in DX_LIST:
        if _clean(lbl) == s:
            return lbl, code
    return s, ""


class DxBlock(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        # callbacks (bound later)
        self._on_change = None
        self._on_remove = None
        self._on_move_up = None
        self._on_move_down = None

        self.number_var = tk.StringVar(value="Diagnosis #1")
        self.dx_display_var = tk.StringVar(value=DX_DISPLAY_VALUES[0])
        self.edit_var = tk.StringVar(value="")

        # header row
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 4))

        ttk.Label(header, textvariable=self.number_var, font=("Segoe UI", 10, "bold")).pack(side="left")

        self.remove_btn = ttk.Button(header, text="Remove", command=lambda: self._call(self._on_remove))
        self.remove_btn.pack(side="right")

        # dx dropdown row
        row1 = ttk.Frame(self)
        row1.pack(fill="x")

        ttk.Label(row1, text="Dx:").pack(side="left")
        self.dx_cb = ttk.Combobox(
            row1,
            textvariable=self.dx_display_var,
            values=DX_DISPLAY_VALUES,
            state="readonly",
            width=44,
        )
        self._disable_mousewheel_on_cb(self.dx_cb)
        self.dx_cb.pack(side="left", padx=(6, 0), fill="x", expand=True)

        # edit + move buttons
        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(6, 0))

        ttk.Label(row2, text="Edit:").pack(side="left")
        self.edit_entry = ttk.Entry(row2, textvariable=self.edit_var, width=30)
        self.edit_entry.pack(side="left", padx=(6, 8), fill="x", expand=True)

        self.up_btn = ttk.Button(row2, text="↑", width=3, command=lambda: self._call(self._on_move_up))
        self.up_btn.pack(side="left", padx=(0, 4))

        self.down_btn = ttk.Button(row2, text="↓", width=3, command=lambda: self._call(self._on_move_down))
        self.down_btn.pack(side="left")

        # traces call _on_change (if bound)
        self.dx_display_var.trace_add("write", lambda *_: self._call(self._on_change))
        self.edit_var.trace_add("write", lambda *_: self._call(self._on_change))

        self.configure(padding=4)

    def _call(self, fn):
        if callable(fn):
            fn()

    def _disable_mousewheel_on_cb(self, cb: ttk.Combobox):
        """Prevent mouse wheel from changing combobox selection when dropdown is closed."""
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")
    
    def bind_actions(self, on_change, on_remove, on_move_up, on_move_down):
        """Bind / rebind actions safely after the block exists."""
        self._on_change = on_change
        self._on_remove = on_remove
        self._on_move_up = on_move_up
        self._on_move_down = on_move_down

    def set_number(self, n: int):
        self.number_var.set(f"Diagnosis #{n}")

    def get_label_code(self) -> tuple[str, str]:
        return _parse_display_to_pair(self.dx_display_var.get())

    def to_line(self, n: int) -> str:
        lbl, code = self.get_label_code()
        edit = _clean(self.edit_var.get())
        text = edit if edit else _clean(lbl)
        return f"{n}. {text} ({code})" if _clean(code) else f"{n}. {text}"

    def to_dict(self) -> dict:
        lbl, code = self.get_label_code()
        return {
            "dx_label": lbl,
            "icd10": code,
            "dx_display": self.dx_display_var.get(),
            "edit_text": self.edit_var.get(),
        }

    def from_dict(self, d: dict):
        d = d or {}
        disp = _clean(d.get("dx_display", ""))
        if disp and disp in DX_DISPLAY_VALUES:
            self.dx_display_var.set(disp)
        else:
            lbl = _clean(d.get("dx_label", ""))
            code = _clean(d.get("icd10", ""))
            display = _dx_display(lbl, code) if lbl else DX_DISPLAY_VALUES[0]
            if display not in DX_DISPLAY_VALUES and lbl:
                self.dx_display_var.set(lbl)
            else:
                self.dx_display_var.set(display if display in DX_DISPLAY_VALUES else DX_DISPLAY_VALUES[0])

        self.edit_var.set(d.get("edit_text", "") or "")


class DiagnosisPage(ttk.Frame):
    """
    - Up to 9 Dx blocks laid out in 3 down x 3 across
    - Toggle buttons to collapse:
        1) Blocks grid
        2) Diagnosis Text box
    - Text box starts hidden by default
    - Auto-renumber always
    - Auto-build Diagnosis Text (editable) unless user starts typing into it
    """

    def __init__(self, parent, on_change_callback, max_blocks: int = 21):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self.max_blocks = max_blocks

        self._loading = False
        self.blocks: list[DxBlock] = []
        
        # collapse states
        self.blocks_visible = tk.BooleanVar(value=False)
        self.text_visible = tk.BooleanVar(value=True)  # START HIDDEN (requested)

        # --- Prognosis / Imaging / Referrals (structured) ---
        self.prognosis_var = tk.StringVar(value="(select)")

        self.imaging_recs: list[dict] = []   # [{"modality":"X-ray","body_part":"Thoracic Spine"}, ...]
        self.referrals: list[dict] = []      # [{"provider_type":"Orthopedist"}, ...]


        self._build_ui()
        self.add_block()  # start with #1
        
    def _on_blocks_inner_configure(self, _evt=None):
        # Update the scrollable region to encompass the inner frame
        try:
            self.blocks_canvas.configure(scrollregion=self.blocks_canvas.bbox("all"))
        except Exception:
            pass

    def _on_blocks_canvas_configure(self, event):
        # Make the inner frame match the canvas width (prevents weird clipping)
        try:
            self.blocks_canvas.itemconfig(self.blocks_window, width=event.width)
        except Exception:
            pass

    def _bind_blocks_mousewheel(self, bind: bool):
        # Windows / Mac
        if bind:
            self.blocks_canvas.bind_all("<MouseWheel>", self._on_blocks_mousewheel)
            # Linux
            self.blocks_canvas.bind_all("<Button-4>", self._on_blocks_mousewheel_linux_up)
            self.blocks_canvas.bind_all("<Button-5>", self._on_blocks_mousewheel_linux_down)
        else:
            self.blocks_canvas.unbind_all("<MouseWheel>")
            self.blocks_canvas.unbind_all("<Button-4>")
            self.blocks_canvas.unbind_all("<Button-5>")

    def _on_blocks_mousewheel(self, event):
        # Windows wheel: event.delta is typically ±120 per notch
        try:
            delta = int(-1 * (event.delta / 120))
            self.blocks_canvas.yview_scroll(delta, "units")
        except Exception:
            pass

    def _on_blocks_mousewheel_linux_up(self, _event):
        try:
            self.blocks_canvas.yview_scroll(-1, "units")
        except Exception:
            pass

    def _on_blocks_mousewheel_linux_down(self, _event):
        try:
            self.blocks_canvas.yview_scroll(+1, "units")
        except Exception:
            pass


        # apply startup collapsed state
        self._apply_collapse_states(startup=True)
    def _refresh_imaging_list(self):
        self.imaging_list.delete(0, "end")
        for it in self.imaging_recs:
            mod = _clean(it.get("modality", ""))
            part = _clean(it.get("body_part", ""))
            if mod and part:
                self.imaging_list.insert("end", f"{mod} of {part}")

    def _add_imaging_rec(self):
        mod = _clean(self.img_mod_var.get())
        part = _clean(self.img_part_var.get())
        if mod in ("", "(select)") or part in ("", "(select)"):
            return
        self.imaging_recs.append({"modality": mod, "body_part": part})
        self._refresh_imaging_list()
        self._changed()

    def _remove_imaging_rec(self):
        sel = list(self.imaging_list.curselection())
        if not sel:
            return
        for i in reversed(sel):
            if 0 <= i < len(self.imaging_recs):
                self.imaging_recs.pop(i)
        self._refresh_imaging_list()
        self._changed()

    def _refresh_ref_list(self):
        self.ref_list.delete(0, "end")
        for it in self.referrals:
            p = _clean(it.get("provider_type", ""))
            if p:
                self.ref_list.insert("end", p)

    def _add_referral(self):
        p = _clean(self.ref_var.get())
        if p in ("", "(select)"):
            return
        self.referrals.append({"provider_type": p})
        self._refresh_ref_list()
        self._changed()

    def _remove_referral(self):
        sel = list(self.ref_list.curselection())
        if not sel:
            return
        for i in reversed(sel):
            if 0 <= i < len(self.referrals):
                self.referrals.pop(i)
        self._refresh_ref_list()
        self._changed()    
    
    def _changed(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def _assessment_screen_refresh(self, preset_map: dict[str, str]):
        choice = (self.assessment_choice_var.get() or "").strip()

        if choice in ("", "(select)"):
            self.assess_preview.configure(text="")
            self.assess_custom_row.grid_remove()
        elif choice == "Custom (free text)":
            self.assess_preview.configure(text="Type your custom assessment one-liner below.")
            self.assess_custom_row.grid()
        else:
            self.assess_preview.configure(text=preset_map.get(choice, ""))
            self.assess_custom_row.grid_remove()

        self._changed()        

    def _causation_refresh(self, preset_map: dict[str, str]):
        choice = (getattr(self, "causation_choice_var", None).get() or "").strip()

        if choice in ("", "(select)"):
            self.causation_preview.configure(text="")
            self.causation_custom_row.grid_remove()
        elif choice == "Custom (free text)":
            self.causation_preview.configure(text="Type a custom causation statement below.")
            self.causation_custom_row.grid()
        else:
            self.causation_preview.configure(text=preset_map.get(choice, ""))
            self.causation_custom_row.grid_remove()

        self._changed()

    def _show_dx_block(self, name: str):
        """Raise the selected section frame and update button styling."""
        if name not in self._dx_frames:
            return
        self._dx_frames[name].tkraise()
        for n, btn in self._section_buttons.items():
            if n == name:
                btn.configure(relief="sunken", font=("Segoe UI", 10, "bold"))
            else:
                btn.configure(relief="raised", font=("Segoe UI", 10))

    def _disable_mousewheel_on_cb(self, cb: ttk.Combobox):
        """Prevent mouse wheel from changing combobox selection when dropdown is closed."""
        cb.bind("<MouseWheel>", lambda e: "break")
        cb.bind("<Button-4>", lambda e: "break")
        cb.bind("<Button-5>", lambda e: "break")

    def _sync_notes_to_var(self, text_widget: tk.Text, var: tk.StringVar):
        """Sync Text widget content to StringVar and mark changed."""
        try:
            var.set(text_widget.get("1.0", "end-1c"))
        except Exception:
            pass
        self._changed()
    
    def _build_assessment_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Assessment section frame (no back button)."""
        fr = ttk.Frame(parent)
        body = ttk.Frame(fr)
        body.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        body.columnconfigure(0, weight=1)

        if not hasattr(self, "assessment_choice_var"):
            self.assessment_choice_var = tk.StringVar(value="(select)")
        if not hasattr(self, "assessment_custom_var"):
            self.assessment_custom_var = tk.StringVar(value="")
        if not hasattr(self, "assessment_notes_var"):
            self.assessment_notes_var = tk.StringVar(value="")

        ASSESSMENT_STMT_CHOICES = [
            "(select)", "Standard exam / evaluation day", "Therapy-only visit",
            "Re-exam / progress visit", "Discharge / final visit", "Custom (free text)",
        ]
        self.ASSESSMENT_STMT_TEXT = {
            "Standard exam / evaluation day":
                "Clinical findings are consistent with the diagnoses listed below based on the patient's history and objective examination.",
            "Therapy-only visit":
                "The patient was seen for continuation of therapeutic treatment per the established plan of care. No re-examination was performed at this visit.",
            "Re-exam / progress visit":
                "Findings were reviewed and treatment response assessed. The diagnoses listed below remain consistent with the patient's presentation at this visit.",
            "Discharge / final visit":
                "The patient was seen for final assessment and disposition. Diagnoses and clinical status were reviewed, and ongoing recommendations are documented below.",
        }

        ttk.Label(body, text="Choose statement type:").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(body, textvariable=self.assessment_choice_var, values=ASSESSMENT_STMT_CHOICES, state="readonly", width=44)
        self._disable_mousewheel_on_cb(cb)
        cb.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda e: self._assessment_screen_refresh(self.ASSESSMENT_STMT_TEXT))

        self.assess_preview = ttk.Label(body, text="", wraplength=700, justify="left", foreground="gray")
        self.assess_preview.grid(row=2, column=0, sticky="w", pady=(0, 10))

        self.assess_custom_row = ttk.Frame(body)
        self.assess_custom_row.grid(row=3, column=0, sticky="ew")
        self.assess_custom_row.columnconfigure(0, weight=1)
        ttk.Label(self.assess_custom_row, text="Custom statement:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.assess_custom_row, textvariable=self.assessment_custom_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.assessment_custom_var.trace_add("write", lambda *_: self._changed())
        self.assess_custom_row.grid_remove()

        ttk.Label(body, text="Notes (general text):").grid(row=4, column=0, sticky="w", pady=(14, 4))
        self.assessment_notes = tk.Text(body, height=4, wrap="word", font=("Segoe UI", 9))
        self.assessment_notes.grid(row=5, column=0, sticky="nsew", pady=(0, 6))
        body.rowconfigure(5, weight=1)
        try:
            self.assessment_notes.delete("1.0", "end")
            self.assessment_notes.insert("1.0", self.assessment_notes_var.get() or "")
        except Exception:
            pass
        def _sync_assess_notes(*_):
            self._sync_notes_to_var(self.assessment_notes, self.assessment_notes_var)
        self.assessment_notes.bind("<KeyRelease>", lambda e: _sync_assess_notes())
        self.assessment_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_assess_notes))
        self.assessment_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_assess_notes))

        self._assessment_screen_refresh(self.ASSESSMENT_STMT_TEXT)
        return fr

    def _build_causation_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Causation section frame (no back button)."""
        fr = ttk.Frame(parent)
        body = ttk.Frame(fr)
        body.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        body.columnconfigure(0, weight=1)

        if not hasattr(self, "causation_choice_var"):
            self.causation_choice_var = tk.StringVar(value="(select)")
        if not hasattr(self, "causation_custom_var"):
            self.causation_custom_var = tk.StringVar(value="")
        if not hasattr(self, "causation_notes_var"):
            self.causation_notes_var = tk.StringVar(value="")
        if not hasattr(self, "causation_general_notes_var"):
            self.causation_general_notes_var = tk.StringVar(value="")

        CAUSATION_CHOICES = [
            "(select)", "Causally related (WDM certainty)", "Clinically consistent with reported mechanism (conservative)",
            "Aggravation of pre-existing condition", "Not causally related", "Unable to determine at this time", "Custom (free text)",
        ]
        CAUSATION_TEXT = {
            "Causally related (WDM certainty)":
                "Within a reasonable degree of medical certainty, the patient's diagnosed conditions are causally related to the reported mechanism of injury.",
            "Clinically consistent with reported mechanism (conservative)":
                "The patient's presentation and examination findings are clinically consistent with the reported mechanism of injury.",
            "Aggravation of pre-existing condition":
                "The current condition represents an aggravation of a pre-existing condition, as supported by the patient's history and current clinical findings.",
            "Not causally related":
                "Based on the available history and examination findings, the diagnosed conditions are not causally related to the reported mechanism of injury.",
            "Unable to determine at this time":
                "Causation cannot be determined at this time based on the available information; additional history, records, and/or diagnostic testing may be required.",
        }
        self._CAUSATION_TEXT_MAP = CAUSATION_TEXT

        ttk.Label(body, text="Select causation statement:").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(body, textvariable=self.causation_choice_var, values=CAUSATION_CHOICES, state="readonly", width=54)
        self._disable_mousewheel_on_cb(cb)
        cb.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda e: self._causation_refresh(CAUSATION_TEXT))

        self.causation_preview = ttk.Label(body, text="", wraplength=760, justify="left", foreground="gray")
        self.causation_preview.grid(row=2, column=0, sticky="w", pady=(0, 10))

        self.causation_custom_row = ttk.Frame(body)
        self.causation_custom_row.grid(row=3, column=0, sticky="ew")
        self.causation_custom_row.columnconfigure(0, weight=1)
        ttk.Label(self.causation_custom_row, text="Custom causation statement:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.causation_custom_row, textvariable=self.causation_custom_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.causation_custom_var.trace_add("write", lambda *_: self._changed())
        self.causation_custom_row.grid_remove()

        ttk.Label(body, text="Additional causation notes (optional):").grid(row=4, column=0, sticky="w", pady=(14, 4))
        self.causation_notes = tk.Text(body, height=5, wrap="word")
        self.causation_notes.grid(row=5, column=0, sticky="nsew")
        body.rowconfigure(5, weight=1)

        self.causation_notes.delete("1.0", "end")
        self.causation_notes.insert("1.0", self.causation_notes_var.get() or "")

        def _sync_causation_notes(*_):
            try:
                self.causation_notes_var.set(self.causation_notes.get("1.0", "end-1c"))
            except Exception:
                pass
            self._changed()

        self.causation_notes.bind("<KeyRelease>", lambda e: _sync_causation_notes())
        self.causation_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_causation_notes))
        self.causation_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_causation_notes))

        ttk.Label(body, text="Notes (general text):").grid(row=6, column=0, sticky="w", pady=(14, 4))
        self.causation_general_notes = tk.Text(body, height=4, wrap="word", font=("Segoe UI", 9))
        self.causation_general_notes.grid(row=7, column=0, sticky="nsew", pady=(0, 6))
        body.rowconfigure(7, weight=1)
        try:
            self.causation_general_notes.delete("1.0", "end")
            self.causation_general_notes.insert("1.0", self.causation_general_notes_var.get() or "")
        except Exception:
            pass
        def _sync_causation_general(*_):
            self._sync_notes_to_var(self.causation_general_notes, self.causation_general_notes_var)
        self.causation_general_notes.bind("<KeyRelease>", lambda e: _sync_causation_general())
        self.causation_general_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_causation_general))
        self.causation_general_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_causation_general))

        self._causation_refresh(CAUSATION_TEXT)
        return fr

    def _build_prognosis_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Prognosis section frame."""
        fr = ttk.Frame(parent)
        pro_box = ttk.Labelframe(fr, text="Prognosis")
        pro_box.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        pro_box.columnconfigure(0, weight=1)

        self.prognosis_cb = ttk.Combobox(pro_box, textvariable=self.prognosis_var, values=PROGNOSIS_CHOICES, state="readonly")
        self._disable_mousewheel_on_cb(self.prognosis_cb)
        self.prognosis_cb.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.prognosis_cb.bind("<<ComboboxSelected>>", lambda e: self._changed())

        if not hasattr(self, "prognosis_notes_var"):
            self.prognosis_notes_var = tk.StringVar(value="")
        ttk.Label(pro_box, text="Notes (general text):").grid(row=1, column=0, sticky="w", padx=8, pady=(14, 4))
        self.prognosis_notes = tk.Text(pro_box, height=4, wrap="word", font=("Segoe UI", 9))
        self.prognosis_notes.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        pro_box.rowconfigure(2, weight=1)
        try:
            self.prognosis_notes.delete("1.0", "end")
            self.prognosis_notes.insert("1.0", self.prognosis_notes_var.get() or "")
        except Exception:
            pass
        def _sync_prog_notes(*_):
            self._sync_notes_to_var(self.prognosis_notes, self.prognosis_notes_var)
        self.prognosis_notes.bind("<KeyRelease>", lambda e: _sync_prog_notes())
        self.prognosis_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_prog_notes))
        self.prognosis_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_prog_notes))
        return fr

    def _build_imaging_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Imaging section frame."""
        fr = ttk.Frame(parent)
        img_box = ttk.Labelframe(fr, text="Imaging Recommendations")
        img_box.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        img_box.columnconfigure(0, weight=1)

        img_row = ttk.Frame(img_box)
        img_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        img_row.columnconfigure(0, weight=1)
        img_row.columnconfigure(1, weight=1)

        self.img_mod_var = tk.StringVar(value="(select)")
        self.img_part_var = tk.StringVar(value="(select)")

        cb_img_mod = ttk.Combobox(img_row, textvariable=self.img_mod_var, values=IMAGING_MODALITIES, state="readonly")
        self._disable_mousewheel_on_cb(cb_img_mod)
        cb_img_mod.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        cb_img_part = ttk.Combobox(img_row, textvariable=self.img_part_var, values=IMAGING_PARTS, state="readonly")
        self._disable_mousewheel_on_cb(cb_img_part)
        cb_img_part.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        img_btns = ttk.Frame(img_box)
        img_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(img_btns, text="Add", command=self._add_imaging_rec).pack(side="left")
        ttk.Button(img_btns, text="Remove Selected", command=self._remove_imaging_rec).pack(side="left", padx=(8, 0))

        self.imaging_list = tk.Listbox(img_box, height=4)
        self.imaging_list.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        if not hasattr(self, "imaging_notes_var"):
            self.imaging_notes_var = tk.StringVar(value="")
        ttk.Label(img_box, text="Notes (general text):").grid(row=3, column=0, sticky="w", padx=8, pady=(14, 4))
        self.imaging_notes = tk.Text(img_box, height=4, wrap="word", font=("Segoe UI", 9))
        self.imaging_notes.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 8))
        img_box.rowconfigure(4, weight=1)
        try:
            self.imaging_notes.delete("1.0", "end")
            self.imaging_notes.insert("1.0", self.imaging_notes_var.get() or "")
        except Exception:
            pass
        def _sync_img_notes(*_):
            self._sync_notes_to_var(self.imaging_notes, self.imaging_notes_var)
        self.imaging_notes.bind("<KeyRelease>", lambda e: _sync_img_notes())
        self.imaging_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_img_notes))
        self.imaging_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_img_notes))
        return fr

    def _build_referrals_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Referrals section frame."""
        fr = ttk.Frame(parent)
        ref_box = ttk.Labelframe(fr, text="Referrals")
        ref_box.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        ref_box.columnconfigure(0, weight=1)

        self.ref_var = tk.StringVar(value="(select)")
        cb_ref = ttk.Combobox(ref_box, textvariable=self.ref_var, values=REFERRAL_CHOICES, state="readonly")
        self._disable_mousewheel_on_cb(cb_ref)
        cb_ref.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        ref_btns = ttk.Frame(ref_box)
        ref_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(ref_btns, text="Add", command=self._add_referral).pack(side="left")
        ttk.Button(ref_btns, text="Remove Selected", command=self._remove_referral).pack(side="left", padx=(8, 0))

        self.ref_list = tk.Listbox(ref_box, height=4)
        self.ref_list.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        if not hasattr(self, "referrals_notes_var"):
            self.referrals_notes_var = tk.StringVar(value="")
        ttk.Label(ref_box, text="Notes (general text):").grid(row=3, column=0, sticky="w", padx=8, pady=(14, 4))
        self.referrals_notes = tk.Text(ref_box, height=4, wrap="word", font=("Segoe UI", 9))
        self.referrals_notes.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 8))
        ref_box.rowconfigure(4, weight=1)
        try:
            self.referrals_notes.delete("1.0", "end")
            self.referrals_notes.insert("1.0", self.referrals_notes_var.get() or "")
        except Exception:
            pass
        def _sync_ref_notes(*_):
            self._sync_notes_to_var(self.referrals_notes, self.referrals_notes_var)
        self.referrals_notes.bind("<KeyRelease>", lambda e: _sync_ref_notes())
        self.referrals_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_ref_notes))
        self.referrals_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_ref_notes))
        return fr

    def _build_employment_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Current Work Stats section frame (no back button)."""
        fr = ttk.Frame(parent)
        body = ttk.Frame(fr)
        body.pack(fill="both", expand=True, padx=padx, pady=(10, 10))
        body.columnconfigure(0, weight=1)

        if not hasattr(self, "employment_status_var"):
            self.employment_status_var = tk.StringVar(value="(select)")
        if not hasattr(self, "work_plan_var"):
            self.work_plan_var = tk.StringVar(value="(select)")
        if not hasattr(self, "employment_notes_var"):
            self.employment_notes_var = tk.StringVar(value="")
        if not hasattr(self, "employment_other_var"):
            self.employment_other_var = tk.StringVar(value="")
        if not hasattr(self, "employment_general_notes_var"):
            self.employment_general_notes_var = tk.StringVar(value="")

        if not hasattr(self, "employment_status_choices"):
            self.employment_status_choices = [
                "(select)", "Employed Full-Time", "Employed Part-Time", "Self-Employed", "Unemployed",
                "a Student", "Retired", "a Homemaker", "Disabled / Unable to Work", "on a Leave of Absence", "Other (free text)",
            ]
        work_plan_choices = [
            "(select)", "Full Duty (No Restrictions)", "Modified Duty (Work Restrictions)",
            "Off Work / TTD (Temporary Total Disability)", "Off Work (Work Status Note Only)",
            "Work Restrictions Pending Re-evaluation", "Disability Note Requested", "Return to Work Note Requested",
            "FMLA / Leave Documentation Requested", "Referral for Work Capacity Evaluation",
        ]

        row = ttk.Frame(body)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        left_col = ttk.Frame(row)
        left_col.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        left_col.columnconfigure(0, weight=1)
        right_col = ttk.Frame(row)
        right_col.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        right_col.columnconfigure(0, weight=1)

        ttk.Label(left_col, text="Current employment status:").grid(row=0, column=0, sticky="w")
        self.employment_cb = ttk.Combobox(left_col, textvariable=self.employment_status_var, values=self.employment_status_choices, state="readonly")
        self._disable_mousewheel_on_cb(self.employment_cb)
        self.employment_cb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.employment_cb.bind("<<ComboboxSelected>>", lambda e: self._changed())

        ttk.Label(right_col, text="Work restrictions / disability plan:").grid(row=0, column=0, sticky="w")
        self.work_plan_cb = ttk.Combobox(right_col, textvariable=self.work_plan_var, values=work_plan_choices, state="readonly")
        self._disable_mousewheel_on_cb(self.work_plan_cb)
        self.work_plan_cb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.work_plan_cb.bind("<<ComboboxSelected>>", lambda e: self._changed())

        self.employment_other_row = ttk.Frame(body)
        self.employment_other_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.employment_other_row.columnconfigure(0, weight=1)
        ttk.Label(self.employment_other_row, text="Other employment status:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.employment_other_row, textvariable=self.employment_other_var).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.employment_other_var.trace_add("write", lambda *_: self._changed())
        self.employment_other_row.grid_remove()

        def _refresh_other_visibility(*_):
            if (self.employment_status_var.get() or "").strip() == "Other (free text)":
                self.employment_other_row.grid()
            else:
                self.employment_other_row.grid_remove()
            self._changed()

        self.employment_status_var.trace_add("write", _refresh_other_visibility)
        _refresh_other_visibility()

        ttk.Label(body, text="Additional notes (optional):").grid(row=2, column=0, sticky="w", pady=(14, 4))
        self.employment_notes = tk.Text(body, height=5, wrap="word")
        self.employment_notes.grid(row=3, column=0, sticky="nsew")
        body.rowconfigure(3, weight=1)

        self.employment_notes.delete("1.0", "end")
        self.employment_notes.insert("1.0", self.employment_notes_var.get() or "")

        def _sync_notes(*_):
            try:
                self.employment_notes_var.set(self.employment_notes.get("1.0", "end-1c"))
            except Exception:
                pass
            self._changed()

        self.employment_notes.bind("<KeyRelease>", lambda e: _sync_notes())
        self.employment_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_notes))
        self.employment_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_notes))

        ttk.Label(body, text="Notes (general text):").grid(row=4, column=0, sticky="w", pady=(14, 4))
        self.employment_general_notes = tk.Text(body, height=4, wrap="word", font=("Segoe UI", 9))
        self.employment_general_notes.grid(row=5, column=0, sticky="nsew", pady=(0, 6))
        body.rowconfigure(5, weight=1)
        try:
            self.employment_general_notes.delete("1.0", "end")
            self.employment_general_notes.insert("1.0", self.employment_general_notes_var.get() or "")
        except Exception:
            pass
        def _sync_emp_general(*_):
            self._sync_notes_to_var(self.employment_general_notes, self.employment_general_notes_var)
        self.employment_general_notes.bind("<KeyRelease>", lambda e: _sync_emp_general())
        self.employment_general_notes.bind("<<Paste>>", lambda e: parent.after(1, _sync_emp_general))
        self.employment_general_notes.bind("<<Cut>>", lambda e: parent.after(1, _sync_emp_general))
        return fr

    def _build_dx_block_frame(self, parent, padx=10) -> ttk.Frame:
        """Build Dx Block section frame — diagnosis blocks live here (no extra Notes)."""
        fr = ttk.Frame(parent)
        fr.columnconfigure(0, weight=1)
        fr.rowconfigure(0, weight=1)

        # Diagnosis blocks container (scrollable) — same structure as before, now inside tkRaise
        self.blocks_frame = ttk.Frame(fr)
        self.blocks_frame.pack(fill="both", expand=True, padx=padx, pady=(10, 10))

        blocks_container = ttk.Frame(self.blocks_frame)
        blocks_container.pack(fill="both", expand=True)

        self.blocks_canvas = tk.Canvas(blocks_container, highlightthickness=0)
        self.blocks_vsb = ttk.Scrollbar(blocks_container, orient="vertical", command=self.blocks_canvas.yview)
        self.blocks_canvas.configure(yscrollcommand=self.blocks_vsb.set)

        self.blocks_canvas.pack(side="left", fill="both", expand=True)
        self.blocks_vsb.pack(side="right", fill="y")

        self.blocks_inner = ttk.Frame(self.blocks_canvas)
        self.blocks_window = self.blocks_canvas.create_window((0, 0), window=self.blocks_inner, anchor="nw")

        self.grid_area = ttk.Frame(self.blocks_inner)
        self.grid_area.pack(fill="both", expand=True)
        self.grid_area.columnconfigure(0, weight=1)
        self.grid_area.columnconfigure(1, weight=1)

        self.blocks_inner.bind("<Configure>", self._on_blocks_inner_configure)
        self.blocks_canvas.bind("<Configure>", self._on_blocks_canvas_configure)
        self.blocks_canvas.bind("<Enter>", lambda e: self._bind_blocks_mousewheel(True))
        self.blocks_canvas.bind("<Leave>", lambda e: self._bind_blocks_mousewheel(False))

        # Notes (general text) for Dx Block
        if not hasattr(self, "dx_block_notes_var"):
            self.dx_block_notes_var = tk.StringVar(value="")
        notes_row = ttk.Frame(fr)
        notes_row.pack(fill="x", padx=padx, pady=(8, 10))
        notes_row.columnconfigure(0, weight=1)
        ttk.Label(notes_row, text="Notes (general text):").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.dx_block_notes = tk.Text(notes_row, height=4, wrap="word", font=("Segoe UI", 9))
        self.dx_block_notes.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        notes_row.columnconfigure(0, weight=1)
        try:
            self.dx_block_notes.delete("1.0", "end")
            self.dx_block_notes.insert("1.0", self.dx_block_notes_var.get() or "")
        except Exception:
            pass
        def _sync_dx_notes(*_):
            self._sync_notes_to_var(self.dx_block_notes, self.dx_block_notes_var)
        self.dx_block_notes.bind("<KeyRelease>", lambda e: _sync_dx_notes())
        self.dx_block_notes.bind("<<Paste>>", lambda e: self.after(1, _sync_dx_notes))
        self.dx_block_notes.bind("<<Cut>>", lambda e: self.after(1, _sync_dx_notes))

        return fr
    
    # ---------- UI ----------
    def _build_ui(self):
        padx = 10

        

        self.main_screen = ttk.Frame(self)
        self.main_screen.pack(fill="both", expand=True)

        # Top controls
        top = ttk.Frame(self.main_screen)
        top.pack(fill="x", padx=padx, pady=(10, 6))

        ttk.Button(top, text="Add Dx", command=self.add_block).pack(side="left")
        ttk.Button(top, text="Reset Dx", command=self._confirm_reset).pack(side="left", padx=(8, 0))

        self._section_buttons = {}
        ttk.Label(top, text="Sections:").pack(side="left", padx=(18, 8))

        block_btns = ttk.Frame(top)
        block_btns.pack(side="left", fill="x", expand=True)

        def _add_dx_btn(name):
            btn = tk.Button(
                block_btns, text=name, font=("Segoe UI", 10),
                relief="raised", bd=1,
                command=lambda n=name: self._show_dx_block(n),
            )
            btn.pack(side="left", padx=4)
            self._section_buttons[name] = btn

        _add_dx_btn("Dx Block")
        _add_dx_btn("Assessment")
        _add_dx_btn("Causation")
        _add_dx_btn("Prognosis")
        _add_dx_btn("Imaging")
        _add_dx_btn("Referrals")
        _add_dx_btn("Current Work Stats")

        # Collapse toggles (right side)
        self.toggle_blocks_btn = ttk.Button(top, text="Hide Blocks", command=self._toggle_blocks)
        #self.toggle_blocks_btn.pack(side="right")

        self.toggle_text_btn = ttk.Button(top, text="Show Text Box", command=self._toggle_text)
        self.toggle_text_btn.pack(side="right", padx=(0, 8))

        ttk.Separator(self.main_screen).pack(fill="x", padx=padx, pady=(6, 10))      

        # -------------------------        # -------------------------
        # Text box frame (collapsible)
        # -------------------------
        self.text_frame = ttk.Frame(self.main_screen)
        # pack later in _apply_collapse_states

        # Two-column area inside text_frame
                # Stacked area: top = tkRaise sections, bottom = Notes
        self.text_area = ttk.Frame(self.text_frame)
        self.text_area.pack(fill="both", expand=True)

        self.text_area.columnconfigure(0, weight=1)
        self.text_area.rowconfigure(0, weight=1)   # tkRaise sections get the space
        self.text_area.rowconfigure(1, weight=0)   # Notes takes natural height

        # Top: tkRaise container (Dx Block, Assessment, Prognosis, etc.)
        top_frame = ttk.Frame(self.text_area)
        top_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        top_frame.columnconfigure(0, weight=1)
        top_frame.rowconfigure(0, weight=1)

        # ---- tkRaise container (stacked section frames) ----
        self._dx_container = ttk.Frame(top_frame)
        self._dx_container.grid(row=0, column=0, sticky="nsew")
        self._dx_container.grid_rowconfigure(0, weight=1)
        self._dx_container.grid_columnconfigure(0, weight=1)

        self._dx_frames = {
            "Dx Block": self._build_dx_block_frame(self._dx_container, padx),
            "Assessment": self._build_assessment_frame(self._dx_container, padx),
            "Causation": self._build_causation_frame(self._dx_container, padx),
            "Prognosis": self._build_prognosis_frame(self._dx_container, padx),
            "Imaging": self._build_imaging_frame(self._dx_container, padx),
            "Referrals": self._build_referrals_frame(self._dx_container, padx),
            "Current Work Stats": self._build_employment_frame(self._dx_container, padx),
        }

        for fr in self._dx_frames.values():
            fr.grid(row=0, column=0, sticky="nsew")

        self._show_dx_block("Dx Block")

        tip = (
            "Tip: Use ↑/↓ on a diagnosis block to change order. "
            "Diagnoses will auto-renumber. Notes box is for general use."
        )
        self.tip_label = ttk.Label(self.main_screen, text=tip, foreground="gray")
        # packed in _apply_collapse_states with text_frame visibility


    def _apply_collapse_states(self, startup: bool = False):
        """
        Apply visibility states to frames.
        Uses pack_forget()/pack() so it works with your current pack layout.
        """
        padx = 10
        
        # Blocks: Dx Block now lives in tkRaise (not toggled here). Button kept for future use.
        self.toggle_blocks_btn.configure(text="Hide Blocks" if self.blocks_visible.get() else "Show Blocks")

        # Text box

        # Text box
        if self.text_visible.get():
            if not self.text_frame.winfo_ismapped():
                self.text_frame.pack(fill="both", expand=True, padx=padx, pady=(0, 10))
            if not self.tip_label.winfo_ismapped():
                self.tip_label.pack(anchor="w", padx=padx, pady=(0, 8))
            self.toggle_text_btn.configure(text="Hide Text Box")
        else:
            if self.text_frame.winfo_ismapped():
                self.text_frame.pack_forget()
            if self.tip_label.winfo_ismapped():
                self.tip_label.pack_forget()
            self.toggle_text_btn.configure(text="Show Text Box")

        # On startup, ensure button labels match state
        if startup:
            self.toggle_blocks_btn.configure(text="Hide Blocks" if self.blocks_visible.get() else "Show Blocks")
            self.toggle_text_btn.configure(text="Hide Text Box" if self.text_visible.get() else "Show Text Box")

    def _toggle_blocks(self):
        self.blocks_visible.set(not self.blocks_visible.get())
        self._apply_collapse_states()
        self._changed()

    def _toggle_text(self):
        self.text_visible.set(not self.text_visible.get())
        self._apply_collapse_states()
        self._changed()

    def _confirm_reset(self):
        ok = messagebox.askyesno(
            "Reset Diagnosis",
            "This will ERASE all Diagnosis blocks on screen (it does not delete any saved files).\n\n"
            "Are you sure you want to continue?"
        )
        if ok:
            self.reset()

    # ---------- blocks ----------
    def add_block(self):
        if len(self.blocks) >= self.max_blocks:
            return

        b = DxBlock(self.grid_area)

        # Bind AFTER creation so ↑/↓ always works immediately
        b.bind_actions(
            on_change=self._on_blocks_changed,
            on_remove=lambda bb=b: self.remove_block(bb),
            on_move_up=lambda bb=b: self.move_block(bb, -1),   # swap: down = move to larger number
            on_move_down=lambda bb=b: self.move_block(bb, +1), # swap: up = move to smaller number
        )

        self.blocks.append(b)
        self._layout_blocks()
        self._on_blocks_changed()

    def remove_block(self, b: DxBlock):
        if b not in self.blocks:
            return
        if len(self.blocks) == 1:
            if not messagebox.askyesno("Remove", "Remove the only diagnosis block?"):
                return
        self.blocks.remove(b)
        b.destroy()
        self._layout_blocks()
        self._on_blocks_changed()

    def move_block(self, b: DxBlock, delta: int):
        if b not in self.blocks:
            return
        idx = self.blocks.index(b)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.blocks):
            return
        self.blocks[idx], self.blocks[new_idx] = self.blocks[new_idx], self.blocks[idx]
        self._layout_blocks()
        self._on_blocks_changed()

    def _layout_blocks(self):
        for child in self.grid_area.winfo_children():
            child.grid_forget()

        for i, blk in enumerate(self.blocks):
            blk.set_number(i + 1)
            r = i // 2
            c = i % 2
            blk.grid(row=r, column=c, sticky="nsew", padx=6, pady=6)

        self.grid_area.update_idletasks()
        self._on_blocks_inner_configure()

    
    def _on_blocks_changed(self):
        if self._loading:
            return
        self._changed()
    
    def _set_text(self, s: str):
        """Backward compat: set the legacy 'text' into dx_block_notes when loading old saves."""
        if getattr(self, "dx_block_notes_var", None) is not None:
            self.dx_block_notes_var.set(s or "")
            if hasattr(self, "dx_block_notes") and self.dx_block_notes.winfo_exists():
                self.dx_block_notes.delete("1.0", "end")
                self.dx_block_notes.insert("1.0", s or "")
        try:
            if hasattr(self, "text") and self.text.winfo_exists():
                self.text.edit_modified(False)
        except Exception:
            pass

    def _on_text_edited(self, _evt=None):
        if self._loading:
            return
        self._changed()


    def _on_text_modified(self, _evt=None):
        try:
            if hasattr(self, "text") and self.text.winfo_exists() and self.text.edit_modified():
                self.text.edit_modified(False)
                self._on_text_edited()
        except Exception:
            pass

    # ---------- public api ----------
    def has_content(self) -> bool:
        if self.blocks:
            return True
        return bool(_clean(self.get_value()))

    def set_value(self, text: str):
        """
        Backward-compat: allow older cases that only stored soap["diagnosis"] as a string
        to load into the general notes text box.
        """
        self._loading = True
        try:
            self._set_text(text or "")
        finally:
            self._loading = False
        self._changed()

    def get_value(self) -> str:
        """Returns combined section notes for backward compat (e.g. soap['diagnosis'] string)."""
        parts = []
        for attr in ("dx_block_notes_var", "assessment_notes_var", "causation_general_notes_var",
                     "prognosis_notes_var", "imaging_notes_var", "referrals_notes_var", "employment_general_notes_var"):
            v = getattr(self, attr, None)
            if v is not None:
                t = (v.get() or "").strip()
                if t:
                    parts.append(t)
        return _strip_auto_tag("\n\n".join(parts))


    def reset(self):
        self._loading = True
        try:
            for b in list(self.blocks):
                b.destroy()
            self.blocks.clear()
            for attr in ("dx_block_notes_var", "assessment_notes_var", "causation_general_notes_var",
                         "prognosis_notes_var", "imaging_notes_var", "referrals_notes_var", "employment_general_notes_var"):
                v = getattr(self, attr, None)
                if v is not None:
                    v.set("")
            # ✅ NEW: clear Prognosis / Imaging / Referrals (structured)
            try:
                self.prognosis_var.set("(select)")
            except Exception:
                pass

            try:
                self.imaging_recs = []
            except Exception:
                self.imaging_recs = []
            try:
                self._refresh_imaging_list()
            except Exception:
                pass

            try:
                self.referrals = []
            except Exception:
                self.referrals = []
            try:
                self._refresh_ref_list()
            except Exception:
                pass

            # ✅ NEW: reset the “picker” combobox vars
            try:
                self.img_mod_var.set("(select)")
                self.img_part_var.set("(select)")
                self.ref_var.set("(select)")
            except Exception:
                pass

            try:
                self.assessment_choice_var.set("(select)")
                self.assessment_custom_var.set("")
            except Exception:
                pass

            try:
                self.employment_status_var.set("(select)")
                self.employment_other_var.set("")
                self.work_plan_var.set("(select)")
                self.employment_notes_var.set("")
            except Exception:
                pass
                       
            
            try:
                self.causation_choice_var.set("(select)")
                self.causation_custom_var.set("")
                self.causation_notes_var.set("")
            except Exception:
                pass

        finally:
            self._loading = False

        self.add_block()
        self._changed()

    def to_dict(self) -> dict:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "dx_block_notes": getattr(self.dx_block_notes_var, "get", lambda: "")(),
            "assessment_notes": getattr(self.assessment_notes_var, "get", lambda: "")(),
            "causation_general_notes": getattr(self.causation_general_notes_var, "get", lambda: "")(),
            "prognosis_notes": getattr(self.prognosis_notes_var, "get", lambda: "")(),
            "imaging_notes": getattr(self.imaging_notes_var, "get", lambda: "")(),
            "referrals_notes": getattr(self.referrals_notes_var, "get", lambda: "")(),
            "employment_general_notes": getattr(self.employment_general_notes_var, "get", lambda: "")(),
            "assessment_choice": self.assessment_choice_var.get(),
            "assessment_custom": self.assessment_custom_var.get(),
            "causation_choice": self.causation_choice_var.get() if hasattr(self, "causation_choice_var") else "(select)",
            "causation_custom": self.causation_custom_var.get() if hasattr(self, "causation_custom_var") else "",
            "causation_notes": (self.causation_notes.get("1.0", "end-1c") if hasattr(self, "causation_notes") else self.causation_notes_var.get()),
            "employment_status": self.employment_status_var.get(),
            "employment_other": self.employment_other_var.get(),
            "work_plan": self.work_plan_var.get(),
            "employment_notes": self.employment_notes_var.get(),
            "prognosis": self.prognosis_var.get(),
            "imaging_recs": list(self.imaging_recs),
            "referrals": list(self.referrals),

            "ui": {
                "blocks_visible": bool(self.blocks_visible.get()),
                "text_visible": bool(self.text_visible.get()),
            },
        }

    def from_dict(self, data: dict):
        data = data or {}
        self._loading = True
        try:
            # restore UI toggles if present
            ui = data.get("ui") or {}
            if "blocks_visible" in ui:
                self.blocks_visible.set(bool(ui.get("blocks_visible")))
            # if "text_visible" in ui:
            #     self.text_visible.set(bool(ui.get("text_visible")))
            # else:
            #     # default: start hidden (requested)
            #     self.text_visible.set(False)
                        # Always show tkRaise (Assessment, Prognosis, etc.) on load
            self.text_visible.set(True)
            for b in list(self.blocks):
                b.destroy()
            self.blocks.clear()

            blocks = data.get("blocks") or []
            for bd in blocks:
                b = DxBlock(self.grid_area)

                b.bind_actions(
                    on_change=self._on_blocks_changed,
                    on_remove=lambda bb=b: self.remove_block(bb),
                    on_move_up=lambda bb=b: self.move_block(bb, -1),   # swap: down = move to larger number
                    on_move_down=lambda bb=b: self.move_block(bb, +1), # swap: up = move to smaller number
                )

                b.from_dict(bd or {})
                self.blocks.append(b)

            if not self.blocks:
                self._loading = False
                self.add_block()
                self._loading = True

            self._layout_blocks()

            self._set_text(data.get("text") or "")

            # Per-section notes (Notes general text)
            for key, var_attr, widget_attr in (
                ("dx_block_notes", "dx_block_notes_var", "dx_block_notes"),
                ("assessment_notes", "assessment_notes_var", "assessment_notes"),
                ("causation_general_notes", "causation_general_notes_var", "causation_general_notes"),
                ("prognosis_notes", "prognosis_notes_var", "prognosis_notes"),
                ("imaging_notes", "imaging_notes_var", "imaging_notes"),
                ("referrals_notes", "referrals_notes_var", "referrals_notes"),
                ("employment_general_notes", "employment_general_notes_var", "employment_general_notes"),
            ):
                val = data.get(key) or ""
                var = getattr(self, var_attr, None)
                if var is not None:
                    var.set(val)
                w = getattr(self, widget_attr, None)
                if w is not None and hasattr(w, "delete"):
                    try:
                        w.delete("1.0", "end")
                        w.insert("1.0", val)
                    except Exception:
                        pass

            self.prognosis_var.set(data.get("prognosis") or "(select)")

            self.imaging_recs = data.get("imaging_recs") or []
            if not isinstance(self.imaging_recs, list):
                self.imaging_recs = []
            self.imaging_recs = [x for x in self.imaging_recs if isinstance(x, dict)]
            self._refresh_imaging_list()

            self.referrals = data.get("referrals") or []
            if not isinstance(self.referrals, list):
                self.referrals = []
            self.referrals = [x for x in self.referrals if isinstance(x, dict)]
            self._refresh_ref_list()

            try:
                self.img_mod_var.set("(select)")
                self.img_part_var.set("(select)")
                self.ref_var.set("(select)")
            except Exception:
                pass

            self.assessment_choice_var.set(data.get("assessment_choice") or "(select)")
            self.assessment_custom_var.set(data.get("assessment_custom") or "")
            

            try:
                self._assessment_screen_refresh(self.ASSESSMENT_STMT_TEXT)
            except Exception:
                pass

            try:
                self.employment_status_var.set(data.get("employment_status") or "(select)")
                self.employment_other_var.set(data.get("employment_other") or "")
                self.work_plan_var.set(data.get("work_plan") or "(select)")
                self.employment_notes_var.set(data.get("employment_notes") or "")
                if hasattr(self, "employment_notes"):
                    self.employment_notes.delete("1.0", "end")
                    self.employment_notes.insert("1.0", self.employment_notes_var.get() or "")
            except Exception:
                pass

            try:
                self.causation_choice_var.set(data.get("causation_choice") or "(select)")
                self.causation_custom_var.set(data.get("causation_custom") or "")
                self.causation_notes_var.set(data.get("causation_notes") or "")
                try:
                    if hasattr(self, "causation_notes"):
                        self.causation_notes.delete("1.0", "end")
                        self.causation_notes.insert("1.0", self.causation_notes_var.get() or "")
                except Exception:
                    pass
                self._causation_refresh(getattr(self, "_CAUSATION_TEXT_MAP", {}))
            except Exception:
                pass
            
            # apply collapse states after loading
            self._apply_collapse_states(startup=True)

        finally:
            self._loading = False

        self._changed()

