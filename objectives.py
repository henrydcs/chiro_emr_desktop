# objectives.py
import tkinter as tk
from tkinter import ttk, messagebox

from config import REGION_OPTIONS, REGION_LABELS, REGION_MUSCLES


# -----------------------------
# Severity scale (0-9)
# -----------------------------
SEVERITY_LABELS = {
    0: "Within Normal Levels",
    1: "Minimum",
    2: "Minimum to Mild",
    3: "Mild",
    4: "Mild to Moderate",
    5: "Moderate",
    6: "Moderate to Severe",
    7: "Severe",
    8: "Very Severe",
    9: "Intolerable",
}
SEVERITY_VALUES = list(range(10))

POSTURE_LEVELS = ["(none)", "Normal/Level", "Left high", "Right high"]
POSTURE_SEVERITY = ["(none)", "Mild", "Moderate", "Severe"]
LORDOSIS_LEVELS = ["(none)", "Normal", "Decreased", "Increased"]


# -----------------------------
# Region-specific Ortho + ROM
# -----------------------------
REGION_ORTHO_TESTS = {
    "CS": [
        "Cervical Compression",
        "Distraction",
        "Spurling's",
        "Shoulder Depression",
        "Soto Hall",
        "Valsalva",
    ],
    "TS": [
        "Spring Test",
        "Rib Compression",
    ],
    "LS": [
        "Straight Leg Raise (SLR)",
        "Braggard's",
        "Kemp's",
        "Slump",
        "FABER (Patrick)",
        "Gaenslen's",
        "Yeoman's",
    ],
}

REGION_ROM_MOTIONS = {
    # Spine
    "CS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
    "TS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],
    "LS": ["Flexion", "Extension", "Lateral Flexion", "Rotation"],

    # Shoulder
    "R_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
    "L_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
    "BL_SHOULDER": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],

    # Elbow / Forearm
    "R_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],
    "L_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],
    "BL_ELBOW": ["Flexion", "Extension", "Supination", "Pronation"],

    # Wrist
    "R_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],
    "L_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],
    "BL_WRIST": ["Flexion", "Extension", "Radial Deviation", "Ulnar Deviation"],

    # Hip
    "R_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
    "L_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],
    "BL_HIP": ["Flexion", "Extension", "Abduction", "Adduction", "Internal Rotation", "External Rotation"],

    # Knee
    "R_KNEE": ["Flexion", "Extension"],
    "L_KNEE": ["Flexion", "Extension"],
    "BL_KNEE": ["Flexion", "Extension"],

    # Ankle
    "R_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
    "L_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
    "BL_ANKLE": ["Dorsiflexion", "Plantarflexion", "Inversion", "Eversion"],
}


ADL_ITEMS = [
    "Sitting tolerance decreased",
    "Standing tolerance decreased",
    "Walking tolerance decreased",
    "Lifting/carrying limited",
    "Bending/twisting limited",
    "Driving tolerance decreased",
    "Sleep disrupted",
    "Work duties limited",
    "Household chores limited",
]

ADL_SEV_CHOICES = list(range(0, 10))  # 0-9



# -----------------------------
# Helpers
# -----------------------------

def _pretty_region(code: str) -> str:
    return REGION_LABELS.get(code, "") or ""


def _region_group_name(label: str) -> str:
    if not label:
        return "Spine"
    if "spine" in label.lower():
        return label
    return f"{label} Spine"


def _region_tag(code: str) -> str:
    c = (code or "").strip()
    mapping = {
        "CS": "C/S",
        "TS": "T/S",
        "LS": "L/S",

        "R_SHOULDER": "R Shoulder",
        "L_SHOULDER": "L Shoulder",
        "BL_SHOULDER": "B/L Shoulders",

        "R_ELBOW": "R Elbow",
        "L_ELBOW": "L Elbow",
        "BL_ELBOW": "B/L Elbows",

        "R_WRIST": "R Wrist",
        "L_WRIST": "L Wrist",
        "BL_WRIST": "B/L Wrists",

        "R_HIP": "R Hip",
        "L_HIP": "L Hip",
        "BL_HIP": "B/L Hips",

        "R_KNEE": "R Knee",
        "L_KNEE": "L Knee",
        "BL_KNEE": "B/L Knees",

        "R_ANKLE": "R Ankle",
        "L_ANKLE": "L Ankle",
        "BL_ANKLE": "B/L Ankles",
    }

    return mapping.get(c, c if c and c != "(none)" else "")



# -----------------------------
# Toggleable Radiobutton group (TTK-safe)
# Click same value again => deselect to -1
# -----------------------------
class ToggleRadioGroup(ttk.Frame):
    def __init__(self, parent, values, var: tk.IntVar, on_change=None, text_map=None, btn_width=3):
        super().__init__(parent)
        self.values = list(values)
        self.var = var
        self.on_change = on_change
        self.text_map = text_map or (lambda v: str(v))
        self.btn_width = btn_width
        self._build()

    def _build(self):
        for i, v in enumerate(self.values):
            rb = ttk.Radiobutton(
                self,
                text=self.text_map(v),
                value=v,
                variable=self.var,
                width=self.btn_width,
                takefocus=False,
            )
            rb.bind("<Button-1>", lambda e, vv=v: self._on_click(vv))
            rb.grid(row=0, column=i, sticky="w", padx=(0, 2))

    def _on_click(self, v):
        current = int(self.var.get())
        if current == v:
            self.var.set(-1)
        else:
            self.var.set(v)

        if callable(self.on_change):
            self.on_change()

        return "break"


# -----------------------------
# Collapsible auto-growing notes
# - grows by lines up to max_lines
# - no scrollbar
# - collapse hides the Text widget
# -----------------------------
class CollapsibleAutoNotes(ttk.Frame):
    def __init__(self, parent, title: str, var: tk.StringVar, on_change=None, min_lines=3, max_lines=10):
        super().__init__(parent)
        self.title = title
        self.var = var
        self.on_change = on_change
        self.min_lines = min_lines
        self.max_lines = max_lines

        self._open = tk.BooleanVar(value=True)

        # internal flags
        self._trace_id = None
        self._in_sync = False  # prevents feedback loops

        self._build()
        self._load_var_into_text()
        self._apply_open_state()

        # trace var updates from outside (rare)
        self._trace_id = self.var.trace_add("write", lambda *_: self._on_var_changed())

        # IMPORTANT: remove trace when this widget is destroyed
        self.bind("<Destroy>", self._on_destroy, add=True)

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x")

        self.btn = ttk.Button(top, text=f"{self.title}  ▲", command=self._toggle)
        self.btn.pack(side="left")

        self.text = tk.Text(self, height=self.min_lines, wrap="word")
        self.text.pack(fill="x", expand=True, pady=(4, 0))

        # sync text->var
        self.text.bind("<KeyRelease>", self._sync_from_text)
        self.text.bind("<<Modified>>", self._on_modified)

    def _on_destroy(self, event=None):
        # Only handle destruction of THIS frame, not every child widget
        if event is not None and event.widget is not self:
            return
        try:
            if self._trace_id is not None:
                self.var.trace_remove("write", self._trace_id)
                self._trace_id = None
        except Exception:
            pass

    def _toggle(self):
        self._open.set(not self._open.get())
        self._apply_open_state()

    def _apply_open_state(self):
        if self._open.get():
            self.btn.configure(text=f"{self.title}  ▲")
            if hasattr(self, "text") and self.text.winfo_exists() and not self.text.winfo_ismapped():
                self.text.pack(fill="x", expand=True, pady=(4, 0))
        else:
            self.btn.configure(text=f"{self.title}  ▼")
            if hasattr(self, "text") and self.text.winfo_exists() and self.text.winfo_ismapped():
                self.text.pack_forget()

    def _on_modified(self, _evt=None):
        if not (hasattr(self, "text") and self.text.winfo_exists()):
            return
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self._sync_from_text()

    def _sync_from_text(self, _evt=None):
        if self._in_sync:
            return
        if not (hasattr(self, "text") and self.text.winfo_exists()):
            return

        self._in_sync = True
        try:
            txt = self.text.get("1.0", "end-1c")
            # Only set if changed to avoid extra trace churn
            if (self.var.get() or "") != txt:
                self.var.set(txt)
            self._auto_resize(txt)
        finally:
            self._in_sync = False

        if callable(self.on_change):
            self.on_change()

    def _auto_resize(self, txt: str):
        if not (hasattr(self, "text") and self.text.winfo_exists()):
            return
        lines = (txt or "").count("\n") + 1
        lines = max(self.min_lines, min(self.max_lines, lines))
        try:
            self.text.configure(height=lines)
        except Exception:
            pass

    def _load_var_into_text(self):
        if not (hasattr(self, "text") and self.text.winfo_exists()):
            return
        self._in_sync = True
        try:
            self.text.delete("1.0", "end")
            v = self.var.get() or ""
            self.text.insert("1.0", v)
            self._auto_resize(v)
        finally:
            self._in_sync = False

    def _on_var_changed(self):
        # Guard: this callback can fire after widget destruction if trace wasn't removed
        if self._in_sync:
            return
        if not self.winfo_exists():
            return
        if not (hasattr(self, "text") and self.text.winfo_exists()):
            return

        # avoid fighting with user typing: only reload if text differs
        try:
            current = self.text.get("1.0", "end-1c")
        except Exception:
            return
        target = self.var.get() or ""
        if current != target:
            self._load_var_into_text()

    def reset(self):
        self.var.set("")
        self._open.set(True)
        self._load_var_into_text()
        self._apply_open_state()


# -----------------------------
# Palpation row:
# Left severity + centered label + Right severity
# -----------------------------
class LRSeverityRow(ttk.Frame):
    def __init__(self, parent, text: str, on_change):
        super().__init__(parent)
        self.on_change = on_change
        self.text = text

        self.l_sev = tk.IntVar(value=-1)  # -1 = not selected
        self.r_sev = tk.IntVar(value=-1)

        self._build()

    def _build(self):
        left_grp = ToggleRadioGroup(self, SEVERITY_VALUES, self.l_sev, on_change=self._changed, btn_width=3)
        left_grp.grid(row=0, column=0, sticky="w")

        ttk.Label(self, text=self.text, width=26, anchor="center").grid(row=0, column=1, sticky="ew", padx=8)

        right_grp = ToggleRadioGroup(self, SEVERITY_VALUES, self.r_sev, on_change=self._changed, btn_width=3)
        right_grp.grid(row=0, column=2, sticky="w")

        self.grid_columnconfigure(1, weight=1)

    def _changed(self):
        if callable(self.on_change):
            self.on_change()

    def get_state(self) -> dict:
        return {"l_sev": int(self.l_sev.get()), "r_sev": int(self.r_sev.get())}

    def set_state(self, data: dict):
        self.l_sev.set(int(data.get("l_sev", -1)))
        self.r_sev.set(int(data.get("r_sev", -1)))


# -----------------------------
# Orthopedic row:
# Left: (-1 none / 0 Neg / 1 Pos)  label  Right: (-1 / 0 / 1)
# -----------------------------
class LROrthoRow(ttk.Frame):
    def __init__(self, parent, text: str, on_change):
        super().__init__(parent)
        self.on_change = on_change
        self.text = text

        self.l_res = tk.IntVar(value=-1)
        self.r_res = tk.IntVar(value=-1)

        self._build()

    def _build(self):
        def ortho_text(v):
            return "Neg" if v == 0 else ("Pos" if v == 1 else "")

        left_grp = ToggleRadioGroup(self, [0, 1], self.l_res, on_change=self._changed, text_map=ortho_text, btn_width=4)
        left_grp.grid(row=0, column=0, sticky="w")

        ttk.Label(self, text=self.text, width=26, anchor="center").grid(row=0, column=1, sticky="ew", padx=8)

        right_grp = ToggleRadioGroup(self, [0, 1], self.r_res, on_change=self._changed, text_map=ortho_text, btn_width=4)
        right_grp.grid(row=0, column=2, sticky="w")

        self.grid_columnconfigure(1, weight=1)

    def _changed(self):
        if callable(self.on_change):
            self.on_change()

    def get_state(self) -> dict:
        return {"l_res": int(self.l_res.get()), "r_res": int(self.r_res.get())}

    def set_state(self, data: dict):
        self.l_res.set(int(data.get("l_res", -1)))
        self.r_res.set(int(data.get("r_res", -1)))


# -----------------------------
# ROM row:
# Left: -1 none / 0 WNL / 1-9 restricted severity
# Right same.
# -----------------------------
class LRROMRow(ttk.Frame):
    def __init__(self, parent, text: str, on_change, *, disable_right: bool = False):
        super().__init__(parent)
        self.on_change = on_change
        self.text = text
        self.disable_right = bool(disable_right)

        self.l_sev = tk.IntVar(value=-1)
        self.r_sev = tk.IntVar(value=-1)

        self.left_grp = None
        self.right_grp = None

        self._build()

        # If disabling, enforce it in two ways:
        # 1) visually disable widgets
        # 2) prevent right value from ever sticking
        if self.disable_right:
            self._set_right_enabled(False)

            def _force_right_off(*_):
                if int(self.r_sev.get()) != -1:
                    try:
                        self.r_sev.set(-1)
                    except Exception:
                        pass
            self.r_sev.trace_add("write", _force_right_off)

    def _build(self):
        self.left_grp = ToggleRadioGroup(self, SEVERITY_VALUES, self.l_sev, on_change=self._changed, btn_width=3)
        self.left_grp.grid(row=0, column=0, sticky="w")

        ttk.Label(self, text=self.text, width=26, anchor="center").grid(row=0, column=1, sticky="ew", padx=8)

        self.right_grp = ToggleRadioGroup(self, SEVERITY_VALUES, self.r_sev, on_change=self._changed, btn_width=3)
        self.right_grp.grid(row=0, column=2, sticky="w")

        self.grid_columnconfigure(1, weight=1)

    def _disable_widget_tree(self, w, state: str):
        """Recursively set state on widget + all descendants."""
        try:
            # ttk uses "disabled"/"normal"
            w.configure(state=state)
        except Exception:
            try:
                # some ttk widgets want state([..]) style; ignore if not supported
                w.state([state])
            except Exception:
                pass

        try:
            for c in w.winfo_children():
                self._disable_widget_tree(c, state)
        except Exception:
            pass

    def _set_right_enabled(self, enabled: bool):
        if not enabled:
            try:
                self.r_sev.set(-1)
            except Exception:
                pass

        state = "normal" if enabled else "disabled"

        if self.right_grp is not None:
            self._disable_widget_tree(self.right_grp, state)

    def _changed(self):
        # If right is disabled, don't allow right changes to propagate
        if self.disable_right:
            try:
                self.r_sev.set(-1)
            except Exception:
                pass

        if callable(self.on_change):
            self.on_change()

    def get_state(self) -> dict:
        return {"l_sev": int(self.l_sev.get()), "r_sev": int(self.r_sev.get())}

    def set_state(self, data: dict):
        self.l_sev.set(int(data.get("l_sev", -1)))
        self.r_sev.set(int(data.get("r_sev", -1)))

        if self.disable_right:
            self._set_right_enabled(False)


# -----------------------------
# Global (Vitals / Inspection) panel
# - collapsible
# - shows Vitals/Posture/Grip
# - each has its own Notes box
# -----------------------------
class VitalsInspectionPanel(ttk.Frame):
    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.on_change = on_change

        self._open = tk.BooleanVar(value=False)
        self.active = tk.StringVar(value="Vitals")  # Vitals|Posture|Grip

        # Vitals (one line)
        self.bp_var = tk.StringVar(value="")
        self.pulse_var = tk.StringVar(value="")
        self.resp_var = tk.StringVar(value="")
        self.temp_var = tk.StringVar(value="")
        self.height_var = tk.StringVar(value="")
        self.weight_var = tk.StringVar(value="")
        self.spo2_var = tk.StringVar(value="")

        # Posture (one line)
        self.shoulder_levels_var = tk.StringVar(value="(none)")
        self.kyphosis_ts_var = tk.StringVar(value="(none)")
        self.forward_head_cs_var = tk.StringVar(value="(none)")
        self.lordosis_ls_var = tk.StringVar(value="(none)")

        # Grip (one line)
        self.grip_left_var = tk.StringVar(value="")
        self.grip_right_var = tk.StringVar(value="")
        self.grip_compare_var = tk.StringVar(value="(none)")

        # --- ADLs / Functional Status (GLOBAL) ---
        self.adl_sev_var = tk.IntVar(value=-1)  # -1 = not selected
        self.adl_checks = {label: tk.BooleanVar(value=False) for label in ADL_ITEMS}
        self.adl_notes_var = tk.StringVar(value="")


        # Notes (separate)
        self.vitals_notes_var = tk.StringVar(value="")
        self.posture_notes_var = tk.StringVar(value="")
        self.grip_notes_var = tk.StringVar(value="")

        self._build_ui()
        self._wire_traces()

    def _wire_traces(self):
        vars_to_trace = [
            self.bp_var, self.pulse_var, self.resp_var, self.temp_var, self.height_var, self.weight_var, self.spo2_var,
            self.shoulder_levels_var, self.kyphosis_ts_var, self.forward_head_cs_var, self.lordosis_ls_var,
            self.grip_left_var, self.grip_right_var, self.grip_compare_var,
            self.vitals_notes_var, self.posture_notes_var, self.grip_notes_var,
            self.adl_notes_var,  # ✅ NEW
        ]
        for v in vars_to_trace:
            v.trace_add("write", lambda *_: self._changed())

        self.adl_sev_var.trace_add("write", lambda *_: self._changed())  # ✅ NEW
        for v in self.adl_checks.values():  # ✅ NEW
            v.trace_add("write", lambda *_: self._changed())

        self.active.trace_add("write", lambda *_: self._show_active())


    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(6, 6))

        ttk.Button(top, text="Vitals / Inspection", command=self._toggle_open).pack(side="left")

        self.radios_frame = ttk.Frame(top)
        self.radios_frame.pack(side="left", padx=(12, 0))

        self.container = ttk.Frame(self)
        self.container.pack(fill="x", padx=10, pady=(0, 8))
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.vitals_frame = ttk.Frame(self.container)
        self.posture_frame = ttk.Frame(self.container)
        self.grip_frame = ttk.Frame(self.container)
        self.adl_frame = ttk.Frame(self.container)  # ✅ NEW

        for f in (self.vitals_frame, self.posture_frame, self.grip_frame, self.adl_frame):
            f.grid(row=0, column=0, sticky="ew")


        self._build_vitals_panel()
        self._build_posture_panel()
        self._build_grip_panel()
        self._build_adl_panel()  # ✅ NEW


        self._apply_open_state()

    def _toggle_open(self):
        self._open.set(not self._open.get())
        self._apply_open_state()
        self._changed()

    def _apply_open_state(self):
        for w in self.radios_frame.winfo_children():
            w.destroy()

        if self._open.get():
            ttk.Radiobutton(self.radios_frame, text="Vitals", value="Vitals", variable=self.active).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(self.radios_frame, text="Posture", value="Posture", variable=self.active).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(self.radios_frame, text="Grip", value="Grip", variable=self.active).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(self.radios_frame, text="ADLs", value="ADLs", variable=self.active).pack(side="left")

            self.container.pack(fill="x", padx=10, pady=(0, 8))
            self._show_active()
        else:
            self.container.pack_forget()

    def _show_active(self):
        if not self._open.get():
            return
        which = self.active.get()
        if which == "Vitals":
            self.vitals_frame.tkraise()
        elif which == "Posture":
            self.posture_frame.tkraise()
        elif which == "Grip":
            self.grip_frame.tkraise()
        else:
            self.adl_frame.tkraise()


    def _build_vitals_row(self, f):
        ttk.Label(f, text="BP:").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.bp_var, width=10).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Pulse:").grid(row=0, column=2, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.pulse_var, width=8).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Resp:").grid(row=0, column=4, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.resp_var, width=8).grid(row=0, column=5, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Temp:").grid(row=0, column=6, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.temp_var, width=8).grid(row=0, column=7, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Ht:").grid(row=0, column=8, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.height_var, width=8).grid(row=0, column=9, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Wt:").grid(row=0, column=10, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.weight_var, width=8).grid(row=0, column=11, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="SpO₂:").grid(row=0, column=12, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.spo2_var, width=8).grid(row=0, column=13, sticky="w", padx=(0, 0), pady=2)

        f.grid_columnconfigure(99, weight=1)

    def _build_posture_row(self, f):
        ttk.Label(f, text="Shoulders:").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=2)
        ttk.Combobox(f, textvariable=self.shoulder_levels_var, values=POSTURE_LEVELS, state="readonly", width=12)\
            .grid(row=0, column=1, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Kyphosis (T/S):").grid(row=0, column=2, sticky="e", padx=(0, 4), pady=2)
        ttk.Combobox(f, textvariable=self.kyphosis_ts_var, values=POSTURE_SEVERITY, state="readonly", width=10)\
            .grid(row=0, column=3, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="FHP (C/S):").grid(row=0, column=4, sticky="e", padx=(0, 4), pady=2)
        ttk.Combobox(f, textvariable=self.forward_head_cs_var, values=POSTURE_SEVERITY, state="readonly", width=10)\
            .grid(row=0, column=5, sticky="w", padx=(0, 12), pady=2)

        ttk.Label(f, text="Lordosis (L/S):").grid(row=0, column=6, sticky="e", padx=(0, 4), pady=2)
        ttk.Combobox(f, textvariable=self.lordosis_ls_var, values=LORDOSIS_LEVELS, state="readonly", width=12)\
            .grid(row=0, column=7, sticky="w", padx=(0, 0), pady=2)

        f.grid_columnconfigure(99, weight=1)

    def _build_grip_row(self, f):
        ttk.Label(f, text="Left:").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.grip_left_var, width=8).grid(row=0, column=1, sticky="w", padx=(0, 14), pady=2)

        ttk.Label(f, text="Right:").grid(row=0, column=2, sticky="e", padx=(0, 4), pady=2)
        ttk.Entry(f, textvariable=self.grip_right_var, width=8).grid(row=0, column=3, sticky="w", padx=(0, 14), pady=2)

        ttk.Label(f, text="Comparison:").grid(row=0, column=4, sticky="e", padx=(0, 4), pady=2)
        ttk.Combobox(
            f,
            textvariable=self.grip_compare_var,
            values=["(none)", "Symmetric", "Left weaker", "Right weaker"],
            state="readonly",
            width=14,
        ).grid(row=0, column=5, sticky="w", padx=(0, 0), pady=2)

        f.grid_columnconfigure(99, weight=1)

    def _build_vitals_panel(self):
        f = self.vitals_frame
        self._build_vitals_row(f)
        notes = CollapsibleAutoNotes(f, "Vitals Notes", self.vitals_notes_var, on_change=self._changed)
        notes.grid(row=1, column=0, columnspan=100, sticky="ew", pady=(8, 0))

    def _build_posture_panel(self):
        f = self.posture_frame
        self._build_posture_row(f)
        notes = CollapsibleAutoNotes(f, "Posture Notes", self.posture_notes_var, on_change=self._changed)
        notes.grid(row=1, column=0, columnspan=100, sticky="ew", pady=(8, 0))

    def _build_grip_panel(self):
        f = self.grip_frame
        self._build_grip_row(f)
        notes = CollapsibleAutoNotes(f, "Grip Notes", self.grip_notes_var, on_change=self._changed)
        notes.grid(row=1, column=0, columnspan=100, sticky="ew", pady=(8, 0))

    def _build_adl_panel(self):
        f = self.adl_frame

        # Title row
        ttk.Label(f, text="Functional Status / ADLs", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        # Severity dropdown (0-9)
        ttk.Label(f, text="ADL Impact Severity (0–9):").grid(row=1, column=0, sticky="w", pady=(8, 2))

        self.adl_sev_cb = ttk.Combobox(
            f,
            values=["(select)"] + [str(i) for i in range(10)],
            width=10,
            state="readonly"
        )
        self.adl_sev_cb.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(8, 2))
        self.adl_sev_cb.set("(select)")

        def _adl_sev_changed(_evt=None):
            v = (self.adl_sev_cb.get() or "").strip()
            self.adl_sev_var.set(int(v) if v.isdigit() else -1)

        self.adl_sev_cb.bind("<<ComboboxSelected>>", _adl_sev_changed)

        # Checkboxes (2 columns)
        chk = ttk.Frame(f)
        chk.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        chk.columnconfigure(0, weight=1)
        chk.columnconfigure(1, weight=1)

        for i, label in enumerate(ADL_ITEMS):
            r, c = divmod(i, 2)
            ttk.Checkbutton(chk, text=label, variable=self.adl_checks[label]).grid(
                row=r, column=c, sticky="w", padx=6, pady=2
            )

        # Notes (collapsible like the others)
        notes = CollapsibleAutoNotes(f, "ADL Notes", self.adl_notes_var, on_change=self._changed)
        notes.grid(row=3, column=0, columnspan=100, sticky="ew", pady=(8, 0))


    def _changed(self):
        if callable(self.on_change):
            self.on_change()

    def has_content(self) -> bool:
        vitals_any = any([
            self.bp_var.get().strip(),
            self.pulse_var.get().strip(),
            self.resp_var.get().strip(),
            self.temp_var.get().strip(),
            self.height_var.get().strip(),
            self.weight_var.get().strip(),
            self.spo2_var.get().strip(),
            (self.vitals_notes_var.get() or "").strip(),
        ])
        posture_any = any([
            self.shoulder_levels_var.get() != "(none)",
            self.kyphosis_ts_var.get() != "(none)",
            self.forward_head_cs_var.get() != "(none)",
            self.lordosis_ls_var.get() != "(none)",
            (self.posture_notes_var.get() or "").strip(),
        ])
        grip_any = any([
            self.grip_left_var.get().strip(),
            self.grip_right_var.get().strip(),
            self.grip_compare_var.get() != "(none)",
            (self.grip_notes_var.get() or "").strip(),
        ])

        adl_any = (
            int(self.adl_sev_var.get()) != -1 or
            any(v.get() for v in self.adl_checks.values()) or
            (self.adl_notes_var.get() or "").strip()
        )


        return vitals_any or posture_any or grip_any or adl_any

    def to_dict(self) -> dict:
        return {
            "open": bool(self._open.get()),
            "active": self.active.get(),
            "vitals": {
                "bp": self.bp_var.get(),
                "pulse": self.pulse_var.get(),
                "resp": self.resp_var.get(),
                "temp": self.temp_var.get(),
                "height": self.height_var.get(),
                "weight": self.weight_var.get(),
                "spo2": self.spo2_var.get(),
                "notes": self.vitals_notes_var.get(),
            },
            "posture": {
                # IMPORTANT: match PDF keys exactly
                "shoulder_levels": self.shoulder_levels_var.get(),
                "kyphosis_ts": self.kyphosis_ts_var.get(),
                "forward_head_cs": self.forward_head_cs_var.get(),
                "lordosis_ls": self.lordosis_ls_var.get(),
                "notes": self.posture_notes_var.get(),
            },
            "grip": {
                "left": self.grip_left_var.get(),
                "right": self.grip_right_var.get(),
                "compare": self.grip_compare_var.get(),
                "notes": self.grip_notes_var.get(),
            },
            # ✅ NEW: ADLs
            "adl": {
                "severity": int(self.adl_sev_var.get()),
                "items": [k for k, v in self.adl_checks.items() if v.get()],
                "notes": self.adl_notes_var.get(),
            },
        }

    def from_dict(self, data: dict):
        data = data or {}
        self._open.set(bool(data.get("open", False)))
        self.active.set(data.get("active", "Vitals"))

        v = data.get("vitals") or {}
        self.bp_var.set(v.get("bp", ""))
        self.pulse_var.set(v.get("pulse", ""))
        self.resp_var.set(v.get("resp", ""))
        self.temp_var.set(v.get("temp", ""))
        self.height_var.set(v.get("height", ""))
        self.weight_var.set(v.get("weight", ""))
        self.spo2_var.set(v.get("spo2", ""))
        self.vitals_notes_var.set(v.get("notes", ""))

        p = data.get("posture") or {}
        self.shoulder_levels_var.set(p.get("shoulder_levels", "(none)"))
        self.kyphosis_ts_var.set(p.get("kyphosis_ts", "(none)"))
        self.forward_head_cs_var.set(p.get("forward_head_cs", "(none)"))
        self.lordosis_ls_var.set(p.get("lordosis_ls", "(none)"))
        self.posture_notes_var.set(p.get("notes", ""))

        g = data.get("grip") or {}
        self.grip_left_var.set(g.get("left", ""))
        self.grip_right_var.set(g.get("right", ""))
        self.grip_compare_var.set(g.get("compare", "(none)"))
        self.grip_notes_var.set(g.get("notes", ""))

                # ✅ ADLs restore
        adl = data.get("adl") or {}

        sev = int(adl.get("severity", -1))
        self.adl_sev_var.set(sev)

        # keep the combobox display in sync too
        if hasattr(self, "adl_sev_cb"):
            self.adl_sev_cb.set(str(sev) if 0 <= sev <= 9 else "(select)")

        # restore checkmarks
        selected = set(adl.get("items") or [])
        for label, var in self.adl_checks.items():
            var.set(label in selected)

        self.adl_notes_var.set(adl.get("notes", ""))


        self._apply_open_state()

    def reset(self):
        self.bp_var.set("")
        self.pulse_var.set("")
        self.resp_var.set("")
        self.temp_var.set("")
        self.height_var.set("")
        self.weight_var.set("")
        self.spo2_var.set("")

        self.shoulder_levels_var.set("(none)")
        self.kyphosis_ts_var.set("(none)")
        self.forward_head_cs_var.set("(none)")
        self.lordosis_ls_var.set("(none)")

        self.grip_left_var.set("")
        self.grip_right_var.set("")
        self.grip_compare_var.set("(none)")

        self.vitals_notes_var.set("")
        self.posture_notes_var.set("")
        self.grip_notes_var.set("")

        self.adl_sev_var.set(-1)
        if hasattr(self, "adl_sev_cb"):
            self.adl_sev_cb.set("(select)")
        for v in self.adl_checks.values():
            v.set(False)
        self.adl_notes_var.set("")

        self._open.set(False)
        self.active.set("Vitals")
        self._apply_open_state()
        self._changed()




# -----------------------------
# One Objectives Block (region-specific)
# - each section has its own Notes box
# -----------------------------
class ObjectivesBlock(ttk.Frame):
    def __init__(self, parent, block_index: int, on_change_callback, on_region_change=None):
        super().__init__(parent)
        self.block_index = block_index
        self.on_change_callback = on_change_callback
        self.on_region_change = on_region_change

        self.region_var = tk.StringVar(value="(none)")
        self.region_label_var = tk.StringVar(value="")

        self.palp_rows: dict[str, LRSeverityRow] = {}
        self.ortho_rows: dict[str, LROrthoRow] = {}
        self.rom_rows: dict[str, LRROMRow] = {}

        self.active_section = tk.StringVar(value="Palpation")  # Palpation|Orthopedic|ROM

        # Notes (one per section)
        self.palp_notes_var = tk.StringVar(value="")
        self.ortho_notes_var = tk.StringVar(value="")
        self.rom_notes_var = tk.StringVar(value="")

        self._build_header()
        self._build_section_tabs()
        self._build_section_frames()

        self._rebuild_for_region()
        self._show_section("Palpation")

        self.region_var.trace_add("write", lambda *_: self._on_region_change())
        self.active_section.trace_add("write", lambda *_: self._show_section(self.active_section.get()))

    def _build_header(self):
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(hdr, text="Body region:").pack(side="left")
        ttk.Combobox(
            hdr,
            textvariable=self.region_var,
            values=REGION_OPTIONS,
            state="readonly",
            width=10
        ).pack(side="left", padx=(8, 12))

        ttk.Label(hdr, textvariable=self.region_label_var, foreground="gray").pack(side="left")

    def _build_section_tabs(self):
        tabs = ttk.Frame(self)
        tabs.pack(fill="x", padx=10, pady=(0, 6))

        ttk.Label(tabs, text="Section:").pack(side="left", padx=(0, 10))

        def tab_button(label: str):
            ttk.Radiobutton(
                tabs,
                text=label,
                value=label,
                variable=self.active_section
            ).pack(side="left", padx=6)

        tab_button("Palpation")
        tab_button("Orthopedic")
        tab_button("ROM")

    def _build_section_frames(self):
        self.section_container = ttk.Frame(self)
        self.section_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.section_container.grid_rowconfigure(0, weight=1)
        self.section_container.grid_columnconfigure(0, weight=1)

        self.palp_frame = ttk.LabelFrame(self.section_container, text="Palpation")
        self.ortho_frame = ttk.LabelFrame(self.section_container, text="Orthopedic Exam")
        self.rom_frame = ttk.LabelFrame(self.section_container, text="Range of Motion")

        for f in (self.palp_frame, self.ortho_frame, self.rom_frame):
            f.grid(row=0, column=0, sticky="nsew")
            f.grid_columnconfigure(0, weight=1)

    def _clear_frame(self, frame):
        for c in frame.winfo_children():
            c.destroy()

    def _rebuild_for_region(self):
        code = self.region_var.get()
        label = _pretty_region(code)
        self.region_label_var.set(label)

        for f in (self.palp_frame, self.ortho_frame, self.rom_frame):
            self._clear_frame(f)

        self.palp_rows.clear()
        self.ortho_rows.clear()
        self.rom_rows.clear()

        if code == "(none)" or not label:
            ttk.Label(self.palp_frame, text="Select a region.").pack(anchor="w", padx=10, pady=10)
            ttk.Label(self.ortho_frame, text="Select a region.").pack(anchor="w", padx=10, pady=10)
            ttk.Label(self.rom_frame, text="Select a region.").pack(anchor="w", padx=10, pady=10)
            return

        # Palpation rows
        palp_items = REGION_MUSCLES.get(code, []) or []
        if palp_items:
            for item in palp_items:
                row = LRSeverityRow(self.palp_frame, item, self._changed)
                row.pack(fill="x", padx=10, pady=3)
                self.palp_rows[item] = row
        else:
            ttk.Label(self.palp_frame, text="(No palpation list configured)").pack(anchor="w", padx=10, pady=10)

        # Palpation notes
        palp_notes = CollapsibleAutoNotes(self.palp_frame, "Palpation Notes", self.palp_notes_var, on_change=self._changed)
        palp_notes.pack(fill="x", padx=10, pady=(10, 8))

        # Ortho rows
        ortho_items = REGION_ORTHO_TESTS.get(code, []) or []
        if ortho_items:
            for item in ortho_items:
                row = LROrthoRow(self.ortho_frame, item, self._changed)
                row.pack(fill="x", padx=10, pady=3)
                self.ortho_rows[item] = row
        else:
            ttk.Label(self.ortho_frame, text="(No orthopedic tests configured)").pack(anchor="w", padx=10, pady=10)

        # Ortho notes
        ortho_notes = CollapsibleAutoNotes(self.ortho_frame, "Orthopedic Notes", self.ortho_notes_var, on_change=self._changed)
        ortho_notes.pack(fill="x", padx=10, pady=(10, 8))

        # ROM rows
        rom_items = REGION_ROM_MOTIONS.get(code, []) or []
        if rom_items:
            code_norm = (code or "").strip().upper()
            is_spine = any(k in code_norm for k in ("CERV", "THOR", "LUMB", "C/S", "T/S", "L/S", "CS", "TS", "LS", "SPINE"))

            for item in rom_items:
                item_norm = (item or "").strip().lower()
                disable_right = is_spine and item_norm in ("flexion", "extension")

                row = LRROMRow(self.rom_frame, item, self._changed, disable_right=disable_right)
                row.pack(fill="x", padx=10, pady=3)
                self.rom_rows[item] = row
        else:
            ttk.Label(self.rom_frame, text="(No ROM list configured)").pack(anchor="w", padx=10, pady=10)


        # ROM notes
        rom_notes = CollapsibleAutoNotes(self.rom_frame, "ROM Notes", self.rom_notes_var, on_change=self._changed)
        rom_notes.pack(fill="x", padx=10, pady=(10, 8))

    def _show_section(self, which: str):
        if which == "Palpation":
            self.palp_frame.tkraise()
        elif which == "Orthopedic":
            self.ortho_frame.tkraise()
        else:
            self.rom_frame.tkraise()

    def _on_region_change(self):
        self._rebuild_for_region()
        self._changed()
        if callable(self.on_region_change):
            self.on_region_change()

    def _changed(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def has_content(self) -> bool:
        def any_selected_sev(rows: dict[str, LRSeverityRow]) -> bool:
            for r in rows.values():
                st = r.get_state()
                if st["l_sev"] != -1 or st["r_sev"] != -1:
                    return True
            return False

        def any_selected_ortho(rows: dict[str, LROrthoRow]) -> bool:
            for r in rows.values():
                st = r.get_state()
                if st["l_res"] != -1 or st["r_res"] != -1:
                    return True
            return False

        def any_selected_rom(rows: dict[str, LRROMRow]) -> bool:
            for r in rows.values():
                st = r.get_state()
                if st["l_sev"] != -1 or st["r_sev"] != -1:
                    return True
            return False

        code = self.region_var.get()
        label = _pretty_region(code)
        if code == "(none)" or not label:
            return False

        notes_any = any([
            (self.palp_notes_var.get() or "").strip(),
            (self.ortho_notes_var.get() or "").strip(),
            (self.rom_notes_var.get() or "").strip(),
        ])

        return (
            any_selected_sev(self.palp_rows) or
            any_selected_ortho(self.ortho_rows) or
            any_selected_rom(self.rom_rows) or
            notes_any
        )

    def to_dict(self) -> dict:
        return {
            "region": self.region_var.get(),
            "active_section": self.active_section.get(),
            "palpation": {k: v.get_state() for k, v in self.palp_rows.items()},
            "ortho": {k: v.get_state() for k, v in self.ortho_rows.items()},
            "rom": {k: v.get_state() for k, v in self.rom_rows.items()},
            "palpation_notes": self.palp_notes_var.get(),
            "ortho_notes": self.ortho_notes_var.get(),
            "rom_notes": self.rom_notes_var.get(),
        }

    def from_dict(self, data: dict):
        data = data or {}
        self.region_var.set(data.get("region", "(none)"))
        self._rebuild_for_region()

        palp = data.get("palpation") or {}
        for name, row in self.palp_rows.items():
            if isinstance(palp.get(name), dict):
                row.set_state(palp[name])

        ortho = data.get("ortho") or {}
        for name, row in self.ortho_rows.items():
            if isinstance(ortho.get(name), dict):
                row.set_state(ortho[name])

        rom = data.get("rom") or {}
        for name, row in self.rom_rows.items():
            if isinstance(rom.get(name), dict):
                row.set_state(rom[name])

        self.palp_notes_var.set(data.get("palpation_notes", ""))
        self.ortho_notes_var.set(data.get("ortho_notes", ""))
        self.rom_notes_var.set(data.get("rom_notes", ""))

        sec = data.get("active_section", "Palpation")
        if sec in ("Palpation", "Orthopedic", "ROM"):
            self.active_section.set(sec)
        else:
            self.active_section.set("Palpation")

    def reset(self):
        self.region_var.set("(none)")
        self.active_section.set("Palpation")
        self.palp_notes_var.set("")
        self.ortho_notes_var.set("")
        self.rom_notes_var.set("")
        self._rebuild_for_region()


# -----------------------------
# Objectives Page (Global + Blocks)
# -----------------------------
class ObjectivesPage(ttk.Frame):
    def __init__(self, parent, on_change_callback):
        super().__init__(parent)
        self.on_change_callback = on_change_callback

        self.global_panel = VitalsInspectionPanel(self, self._handle_change)

        self.blocks: list[ObjectivesBlock] = []
        self.active_index = -1

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Button(top, text="Add Block", command=self.add_block).pack(side="left")
        ttk.Button(top, text="Reset Objectives", command=self.reset).pack(side="left", padx=(8, 0))

        ttk.Label(top, text="Blocks:").pack(side="left", padx=(16, 6))
        self.btns_frame = ttk.Frame(top)
        self.btns_frame.pack(side="left")

        # Collapsible global panel (starts collapsed)
        self.global_panel.pack(fill="x", padx=0, pady=(6, 0))

        # Block container
        self.block_container = ttk.Frame(self)
        self.block_container.pack(fill="both", expand=True, padx=0, pady=0)

    def _rebuild_block_buttons(self):
        for c in self.btns_frame.winfo_children():
            c.destroy()

        for i, b in enumerate(self.blocks):
            tag = _region_tag(b.region_var.get())
            label = f"Block {i+1}" + (f" {tag}" if tag else "")
            ttk.Button(self.btns_frame, text=label, command=lambda ii=i: self.show_block(ii)).pack(side="left", padx=4)

    def add_block(self):
        idx = len(self.blocks) + 1
        block = ObjectivesBlock(
            self.block_container,
            idx,
            self._handle_change,
            on_region_change=self._rebuild_block_buttons
        )
        block.pack_forget()
        self.blocks.append(block)

        self._rebuild_block_buttons()
        self.show_block(len(self.blocks) - 1)

    def show_block(self, index: int):
        if index < 0 or index >= len(self.blocks):
            return
        for b in self.blocks:
            b.pack_forget()
        self.blocks[index].pack(fill="both", expand=True, padx=0, pady=0)
        self.active_index = index
        self._handle_change()

    def _handle_change(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def has_content(self) -> bool:
        return self.global_panel.has_content() or any(b.has_content() for b in self.blocks)

    def to_dict(self) -> dict:
        return {
            "global": self.global_panel.to_dict(),
            "blocks": [b.to_dict() for b in self.blocks],
        }

    def from_dict(self, data: dict):
        data = data or {}

        self.global_panel.from_dict(data.get("global") or {})

        for b in self.blocks:
            b.destroy()
        self.blocks.clear()
        self.active_index = -1

        blocks = data.get("blocks") or []
        for i, bd in enumerate(blocks, start=1):
            block = ObjectivesBlock(
                self.block_container,
                i,
                self._handle_change,
                on_region_change=self._rebuild_block_buttons
            )
            block.pack_forget()
            block.from_dict(bd or {})
            self.blocks.append(block)

        self._rebuild_block_buttons()

        if self.blocks:
            self.show_block(0)
        else:
            for c in self.block_container.winfo_children():
                c.pack_forget()

        self._handle_change()

    def reset(self):
        if not messagebox.askyesno("Reset Objectives", "Are you sure you want to clear ALL objectives?"):
            return

        self.global_panel.reset()

        for b in self.blocks:
            b.destroy()
        self.blocks.clear()
        self.active_index = -1
        self._rebuild_block_buttons()

        self._handle_change()







