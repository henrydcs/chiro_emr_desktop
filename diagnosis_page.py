# diagnosis_page.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

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

def set_value(self, text: str):
    """
    Backward-compat: allow older cases that only stored soap["diagnosis"] as a string
    to load into the text box.
    """
    self._loading = True
    try:
        self._text_is_manual = True  # treat as provider-entered text
        self._set_text(text or "")
        # Ensure UI frames reflect state (optional)
        # self.text_visible.set(True)
        # self._apply_collapse_states()
    finally:
        self._loading = False
    self._changed()



def _clean(s: str) -> str:
    return (s or "").strip()


# ----------------------------
# SINGLE unified Dx list (with ICD-10 shown)
# IMPORTANT: Many ICD-10 codes require laterality and/or 7th character;
# these are "starter defaults" you can edit/expand safely.
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
    ("Cervical disc displacement", "M50.20"),
    ("Cervical sprain/strain (whiplash)", "S13.4XXA"),  
    ("Radiculopathy, Cervical Region", "M54.12"),
    ("Cervical muscle spasm", "M62.838"),
    ("Cervical disc degeneration", "M50.30"),
    ("Cervical spinal stenosis", "M48.02"),
    ("Cervical spondylosis", "M47.812"),    
    ("Neck pain (cervicalgia)", "M54.2"),
    ("-----------------------------------", "-------------------------------"),

    # Thoracic
    ("Thoracic disc displacement", "M51.24"),
    ("Thoracic sprain/strain", "S23.3XXA"),
    ("Thoracic muscle spasm", "M62.830"),
    ("Thoracic radiculopathy", "M54.14"),
    ("Thoracic spine pain", "M54.6"),    
    ("Thoracic spondylosis", "M47.814"),
    ("----------------------------------", "--------------------------"),
    

    # Lumbar / SI
    ("Lumbar disc displacement", "M51.26"),
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
    "Physical Therapy", "Radiology", "Chiropractic Specialty", "Psychology"
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

        # if provider types in the textbox, stop overwriting until they click rebuild
        self._text_is_manual = False

        # collapse states
        self.blocks_visible = tk.BooleanVar(value=True)
        self.text_visible = tk.BooleanVar(value=False)  # START HIDDEN (requested)

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

    # ---------- UI ----------
    def _build_ui(self):
        padx = 10

        # Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=padx, pady=(10, 6))

        ttk.Button(top, text="Add Diagnosis", command=self.add_block).pack(side="left")
        ttk.Button(top, text="Reset Diagnosis", command=self._confirm_reset).pack(side="left", padx=(8, 0))

        ttk.Button(
            top,
            text="Rebuild Text From Dropdowns",
            command=self.rebuild_text_from_blocks
        ).pack(side="left", padx=(18, 0))


        self.manual_lock_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top,
            text="Lock Text (manual edits)",
            variable=self.manual_lock_var,
            command=self._changed
        ).pack(side="left", padx=(10, 0))



        # Collapse toggles (right side)
        self.toggle_blocks_btn = ttk.Button(top, text="Hide Blocks", command=self._toggle_blocks)
        self.toggle_blocks_btn.pack(side="right")

        self.toggle_text_btn = ttk.Button(top, text="Show Text Box", command=self._toggle_text)
        self.toggle_text_btn.pack(side="right", padx=(0, 8))

        ttk.Separator(self).pack(fill="x", padx=padx, pady=(6, 10))

        # -------------------------
        # Blocks grid frame (collapsible)  ✅ NOW SCROLLABLE
        # -------------------------
        self.blocks_frame = ttk.Frame(self)
        self.blocks_frame.pack(fill="both", expand=True, padx=padx, pady=(0, 10))

        # Canvas + Scrollbar container
        blocks_container = ttk.Frame(self.blocks_frame)
        blocks_container.pack(fill="both", expand=True)

        self.blocks_canvas = tk.Canvas(blocks_container, highlightthickness=0)
        self.blocks_vsb = ttk.Scrollbar(blocks_container, orient="vertical", command=self.blocks_canvas.yview)
        self.blocks_canvas.configure(yscrollcommand=self.blocks_vsb.set)

        self.blocks_canvas.pack(side="left", fill="both", expand=True)
        self.blocks_vsb.pack(side="right", fill="y")

        # Inner frame inside the canvas (this is where your grid goes)
        self.blocks_inner = ttk.Frame(self.blocks_canvas)
        self.blocks_window = self.blocks_canvas.create_window((0, 0), window=self.blocks_inner, anchor="nw")

        # ✅ your existing grid area lives inside blocks_inner
        self.grid_area = ttk.Frame(self.blocks_inner)
        self.grid_area.pack(fill="both", expand=True)

        # Only need to configure columns for 2-across layout
        self.grid_area.columnconfigure(0, weight=1)
        self.grid_area.columnconfigure(1, weight=1)


        # Keep scrollregion and width in sync
        self.blocks_inner.bind("<Configure>", self._on_blocks_inner_configure)
        self.blocks_canvas.bind("<Configure>", self._on_blocks_canvas_configure)

        # Mousewheel scrolling only when hovering over the diagnosis blocks area
        self.blocks_canvas.bind("<Enter>", lambda e: self._bind_blocks_mousewheel(True))
        self.blocks_canvas.bind("<Leave>", lambda e: self._bind_blocks_mousewheel(False))


        # -------------------------
        # -------------------------
        # Text box frame (collapsible)
        # -------------------------
        self.text_frame = ttk.Frame(self)
        # pack later in _apply_collapse_states

        # Two-column area inside text_frame
        self.text_area = ttk.Frame(self.text_frame)
        self.text_area.pack(fill="both", expand=True)

        self.text_area.columnconfigure(0, weight=2)  # left (diagnosis text)
        self.text_area.columnconfigure(1, weight=1)  # right (prognosis/imaging/referrals)

        left = ttk.Frame(self.text_area)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        right = ttk.Frame(self.text_area)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)

        # ---- LEFT: Diagnosis Text (editable) ----
        ttk.Label(left, text="Diagnosis Text (editable):").grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.text = tk.Text(left, height=8, wrap="word")
        self.text.grid(row=1, column=0, sticky="nsew", pady=(0, 6))

        # Reduce font size (optional: tweak)
        self.text.configure(font=("Segoe UI", 9))

        self.text.bind("<KeyRelease>", self._on_text_edited)
        self.text.bind("<<Paste>>", lambda e: self.after(1, self._on_text_edited))
        self.text.bind("<<Cut>>", lambda e: self.after(1, self._on_text_edited))
        self.text.bind("<<Modified>>", self._on_text_modified)

        # ---- RIGHT: Prognosis ----
        pro_box = ttk.Labelframe(right, text="Prognosis")
        pro_box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        pro_box.columnconfigure(0, weight=1)

        self.prognosis_cb = ttk.Combobox(
            pro_box,
            textvariable=self.prognosis_var,
            values=PROGNOSIS_CHOICES,
            state="readonly"
        )
        self.prognosis_cb.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.prognosis_cb.bind("<<ComboboxSelected>>", lambda e: self._changed())

        # ---- RIGHT: Imaging ----
        img_box = ttk.Labelframe(right, text="Imaging Recommendations")
        img_box.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        img_box.columnconfigure(0, weight=1)

        img_row = ttk.Frame(img_box)
        img_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        img_row.columnconfigure(0, weight=1)
        img_row.columnconfigure(1, weight=1)

        self.img_mod_var = tk.StringVar(value="(select)")
        self.img_part_var = tk.StringVar(value="(select)")

        ttk.Combobox(img_row, textvariable=self.img_mod_var, values=IMAGING_MODALITIES, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Combobox(img_row, textvariable=self.img_part_var, values=IMAGING_PARTS, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )

        img_btns = ttk.Frame(img_box)
        img_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(img_btns, text="Add", command=self._add_imaging_rec).pack(side="left")
        ttk.Button(img_btns, text="Remove Selected", command=self._remove_imaging_rec).pack(side="left", padx=(8, 0))

        self.imaging_list = tk.Listbox(img_box, height=4)
        self.imaging_list.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        # ---- RIGHT: Referrals ----
        ref_box = ttk.Labelframe(right, text="Referrals")
        ref_box.grid(row=2, column=0, sticky="ew")
        ref_box.columnconfigure(0, weight=1)

        self.ref_var = tk.StringVar(value="(select)")
        ttk.Combobox(ref_box, textvariable=self.ref_var, values=REFERRAL_CHOICES, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=8, pady=(8, 4)
        )

        ref_btns = ttk.Frame(ref_box)
        ref_btns.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Button(ref_btns, text="Add", command=self._add_referral).pack(side="left")
        ttk.Button(ref_btns, text="Remove Selected", command=self._remove_referral).pack(side="left", padx=(8, 0))

        self.ref_list = tk.Listbox(ref_box, height=4)
        self.ref_list.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        tip = (
            "Tip: Use ↑/↓ on a diagnosis block to change order. "
            "Diagnoses will auto-renumber. The text box rebuilds automatically unless you type into it."
        )
        self.tip_label = ttk.Label(self, text=tip, foreground="gray")
        # packed in _apply_collapse_states with text_frame visibility


    def _apply_collapse_states(self, startup: bool = False):
        """
        Apply visibility states to frames.
        Uses pack_forget()/pack() so it works with your current pack layout.
        """
        padx = 10

        # Blocks
        if self.blocks_visible.get():
            if not self.blocks_frame.winfo_ismapped():
                self.blocks_frame.pack(fill="x", padx=padx, pady=(0, 10))
            self.toggle_blocks_btn.configure(text="Hide Blocks")
        else:
            if self.blocks_frame.winfo_ismapped():
                self.blocks_frame.pack_forget()
            self.toggle_blocks_btn.configure(text="Show Blocks")

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
            on_move_up=lambda bb=b: self.move_block(bb, -1),
            on_move_down=lambda bb=b: self.move_block(bb, +1),
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



    # ---------- text sync ----------
    def _on_blocks_changed(self):
        if self._loading:
            return
        if not self.manual_lock_var.get():
            self._text_is_manual = False
            self.rebuild_text_from_blocks()
        self._changed()


    def rebuild_text_from_blocks(self):
        lines = [b.to_line(i + 1) for i, b in enumerate(self.blocks)]
        out = "\n".join(lines).strip()
        if out:
            out = out + "\n" + AUTO_TAG
        self._set_text(out)
        self._text_is_manual = False
        self._changed()

        # If user clicks rebuild, we can optionally auto-show the box
        # Comment out if you prefer it to remain hidden:
        # if not self.text_visible.get():
        #     self.text_visible.set(True)
        #     self._apply_collapse_states()

    def _set_text(self, s: str):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", s or "")
        try:
            self.text.edit_modified(False)
        except Exception:
            pass

    def _on_text_edited(self, _evt=None):
        if self._loading:
            return
        if self.manual_lock_var.get():
            self._text_is_manual = True
        self._changed()


    def _on_text_modified(self, _evt=None):
        try:
            if self.text.edit_modified():
                self.text.edit_modified(False)
                self._on_text_edited()
        except Exception:
            pass

    # ---------- public api ----------
    def has_content(self) -> bool:
        if self.blocks:
            return True
        return bool(_clean(self.get_value()))

    def get_value(self) -> str:
        # If the textbox is supposed to be auto-generated, force it to be correct
        # right before returning (covers hidden textbox + export edge cases).
        if not self._loading and not self._text_is_manual:
            self.rebuild_text_from_blocks()

        raw = _clean(self.text.get("1.0", "end-1c"))
        return _strip_auto_tag(raw)


    def reset(self):
        self._loading = True
        try:
            for b in list(self.blocks):
                b.destroy()
            self.blocks.clear()
            self._text_is_manual = False
            self._set_text("")
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

        finally:
            self._loading = False

        self.add_block()
        self._changed()

    def to_dict(self) -> dict:
        txt = self.get_value()
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "text": txt,
            "text_is_manual": self._text_is_manual,

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
            if "text_visible" in ui:
                self.text_visible.set(bool(ui.get("text_visible")))
            else:
                # default: start hidden (requested)
                self.text_visible.set(False)

            for b in list(self.blocks):
                b.destroy()
            self.blocks.clear()

            blocks = data.get("blocks") or []
            for bd in blocks:
                b = DxBlock(self.grid_area)

                b.bind_actions(
                    on_change=self._on_blocks_changed,
                    on_remove=lambda bb=b: self.remove_block(bb),
                    on_move_up=lambda bb=b: self.move_block(bb, -1),
                    on_move_down=lambda bb=b: self.move_block(bb, +1),
                )

                b.from_dict(bd or {})
                self.blocks.append(b)

            if not self.blocks:
                self._loading = False
                self.add_block()
                self._loading = True

            self._layout_blocks()


            self._text_is_manual = bool(data.get("text_is_manual", False))
            self._set_text(data.get("text") or "")

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



            if not _clean(self.get_value()):
                self._text_is_manual = False
                self.rebuild_text_from_blocks()

            # apply collapse states after loading
            self._apply_collapse_states(startup=True)

        finally:
            self._loading = False

        self._changed()

