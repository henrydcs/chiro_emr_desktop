# HOI.py
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from HOIpdf import build_hoi_flowables

from scrollframe import ScrollFrame



AUTO_MOI_TAG = "[AUTO:MOI]"



def _clean(s: str) -> str:
    return (s or "").strip()

def _join_with_and(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


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

# ----------------------------
# ROF Imaging block (single type + multi body parts + facility + optional city)
# ----------------------------
class ROFImagingBlock(ttk.Frame):
    """
    One ROF imaging block associates:
      - ONE imaging type (combobox)
      - MULTI body parts (listbox)
      - ONE facility (combobox)
      - OPTIONAL city (entry)
    """

    def __init__(
        self,
        parent,
        index: int,
        on_change,
        on_remove,
        *,
        imaging_types: list[str],
        body_parts: list[str],
        facilities: list[str],
    ):
        super().__init__(parent)
        self.on_change = on_change
        self.on_remove = on_remove
        self.index = index

        self.title_var = tk.StringVar(value=f"Imaging #{index}")

        self.imaging_type_var = tk.StringVar(value="(none)")
        self.facility_var = tk.StringVar(value="(none)")
        self.city_var = tk.StringVar(value="")
        self.date_var = tk.StringVar(value="") 

        self.parts_listbox: tk.Listbox | None = None
        self._parts_all = list(body_parts or [])
        self._parts_selected: list[str] = []

        self._imaging_types = list(imaging_types or [])
        self._facilities = list(facilities or [])

        self._build_ui()

    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        # Header
        hdr = ttk.Frame(outer)
        hdr.pack(fill="x")
        ttk.Label(hdr, textvariable=self.title_var, font=("Segoe UI", 10, "bold")).pack(side="left")
        #ttk.Button(hdr, text="Remove", command=self.on_remove).pack(side="right")

        # Row 1: stacked type / facility / city, with Remove beside Type
        row1 = ttk.Frame(outer)
        row1.pack(fill="x", pady=(8, 0))

        left = ttk.Frame(row1)
        left.pack(side="left", fill="x", expand=True)

        # Row A: Type + Remove
        r_type = ttk.Frame(left)
        r_type.pack(fill="x", pady=(0, 2))

        ttk.Label(r_type, text="Type:").pack(side="left")

        cb_type = ttk.Combobox(
            r_type,
            textvariable=self.imaging_type_var,
            values=["(none)"] + [x for x in self._imaging_types if x],
            state="readonly",
            width=9,
        )
        cb_type.pack(side="left", padx=(6, 6))
        cb_type.bind("<<ComboboxSelected>>", lambda e: self._changed())

        ttk.Button(r_type, text="Remove", command=self.on_remove).pack(side="left", padx=(4, 0))

        # Row B: Facility
        r_fac = ttk.Frame(left)
        r_fac.pack(fill="x", pady=(0, 2))

        ttk.Label(r_fac, text="Facility:").pack(side="left")

        cb_fac = ttk.Combobox(
            r_fac,
            textvariable=self.facility_var,
            values=["(none)"] + [x for x in self._facilities if x],
            state="readonly",
            width=30,
        )
        cb_fac.pack(side="left", padx=(6, 0))
        cb_fac.bind("<<ComboboxSelected>>", lambda e: self._changed())

        # Row C: City
        r_city = ttk.Frame(left)
        r_city.pack(fill="x")

        ttk.Label(r_city, text="City (optional):").pack(side="left")

        ent_city = ttk.Entry(r_city, textvariable=self.city_var, width=14)
        ent_city.pack(side="left", padx=(6, 0))
        ent_city.bind("<KeyRelease>", lambda e: self._changed())

        # Row D: Date (optional)
        r_date = ttk.Frame(left)
        r_date.pack(fill="x", pady=(0, 2))

        ttk.Label(r_date, text="Date (optional):").pack(side="left")
        ent_date = ttk.Entry(r_date, textvariable=self.date_var, width=14)
        ent_date.pack(side="left", padx=(6, 0))
        ent_date.bind("<KeyRelease>", lambda e: self._changed())





        # Row 2: parts
        row2 = ttk.Frame(outer)
        row2.pack(fill="x", pady=(8, 0))

        ttk.Label(row2, text="Body parts (select all):").pack(anchor="w")

        lb = tk.Listbox(
            row2,
            selectmode="multiple",
            height=6,
            exportselection=False,
            width=28,     # ✅ tweak: 24–32 is a good range
        )
        for p in self._parts_all:
            lb.insert("end", p)

        lb.pack(anchor="w")  # ✅ IMPORTANT: remove fill="x"
        self.parts_listbox = lb             # ✅ REQUIRED
        lb.bind("<<ListboxSelect>>", lambda e: self._sync_parts())  # ✅ REQUIRED

        # ✅ wheel only when hovering this body-parts listbox
        # Note: HOIPage helper is not available here, so bind directly:
        def _lb_wheel(e):
            # Windows/Mac
            if getattr(e, "delta", 0):
                step = int(-1 * (e.delta / 120)) if abs(e.delta) >= 120 else (-1 if e.delta > 0 else 1)
                lb.yview_scroll(step, "units")
            return "break"

        def _lb_up(_e):
            lb.yview_scroll(-1, "units")
            return "break"

        def _lb_down(_e):
            lb.yview_scroll(1, "units")
            return "break"

        def _enable(_e=None):
            lb.bind("<MouseWheel>", _lb_wheel)
            lb.bind("<Button-4>", _lb_up)
            lb.bind("<Button-5>", _lb_down)

        def _disable(_e=None):
            lb.unbind("<MouseWheel>")
            lb.unbind("<Button-4>")
            lb.unbind("<Button-5>")

        lb.bind("<Enter>", _enable)
        lb.bind("<Leave>", _disable)



    def set_number(self, n: int):
        self.index = n
        self.title_var.set(f"Imaging #{n}")

    def _sync_parts(self):
        try:
            if self.parts_listbox is not None:
                self._parts_selected = [self.parts_listbox.get(i) for i in self.parts_listbox.curselection()]
        except Exception:
            pass
        self._changed()

    def _changed(self):
        if callable(self.on_change):
            self.on_change()

    def get_selected(self) -> dict:
        parts = list(self._parts_selected)

        # ✅ FORCE read from widget at export-time
        if self.parts_listbox is not None:
            try:
                parts = [self.parts_listbox.get(i) for i in self.parts_listbox.curselection()]
            except Exception:
                pass

        return {
            "type": self.imaging_type_var.get(),
            "facility": self.facility_var.get(),
            "city": self.city_var.get(),
            "date": self.date_var.get(),
            "parts": parts,
        }


    def to_dict(self) -> dict:
        return self.get_selected()

    def from_dict(self, d: dict):
        d = d or {}
        self.imaging_type_var.set(d.get("type", "(none)") or "(none)")
        self.facility_var.set(d.get("facility", "(none)") or "(none)")
        self.city_var.set(d.get("city", "") or "")
        self.date_var.set(d.get("date", "") or "")   # ✅ new

        self._parts_selected = list(d.get("parts") or [])

        # restore listbox selection
        if self.parts_listbox is not None:
            try:
                self.parts_listbox.selection_clear(0, "end")
                sel = {_clean(x).lower() for x in self._parts_selected}
                for i, item in enumerate(self._parts_all):
                    if _clean(item).lower() in sel:
                        self.parts_listbox.selection_set(i)
            except Exception:
                pass




# ----------------------------
# Imaging block (multi-select types + multi-select body parts)
# ----------------------------
class ImagingBlock(ttk.Frame):
    """
    One imaging block associates:
      - imaging types (multi-select)
      - body parts (multi-select)
    """

    def __init__(self, parent, index: int, on_change, on_remove):
        super().__init__(parent)
        self.on_change = on_change
        self.on_remove = on_remove

        self.index = index
        self.title_var = tk.StringVar(value=f"Imaging Block #{index}")

        self.types_listbox: tk.Listbox | None = None
        self.parts_listbox: tk.Listbox | None = None

        self._types_all: list[str] = []
        self._parts_all: list[str] = []

        self._types_selected: list[str] = []
        self._parts_selected: list[str] = []

        self._build_ui()

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 6))              
                
        ttk.Label(header, textvariable=self.title_var, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(header, text="Remove", command=self.on_remove).pack(side="right")

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        # Types
        types_frame = ttk.Frame(grid)
        types_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(types_frame, text="Imaging type (select all):").pack(anchor="w")
        lb_types = tk.Listbox(types_frame, selectmode="multiple", height=6, exportselection=False)
        lb_types.pack(anchor="w", fill="x")
        self.types_listbox = lb_types

        # Parts
        parts_frame = ttk.Frame(grid)
        parts_frame.grid(row=0, column=1, sticky="nsew")
        ttk.Label(parts_frame, text="Body parts imaged (select all):").pack(anchor="w")
        lb_parts = tk.Listbox(parts_frame, selectmode="multiple", height=6, exportselection=False)
        lb_parts.pack(anchor="w", fill="x")
        self.parts_listbox = lb_parts

        lb_types.bind("<<ListboxSelect>>", lambda e: self._sync_from_widgets())
        lb_parts.bind("<<ListboxSelect>>", lambda e: self._sync_from_widgets())

        # nice border feel
        self.configure(padding=0)

    def set_number(self, n: int):
        self.index = n
        self.title_var.set(f"Imaging Block #{n}")

    def set_options(self, imaging_types: list[str], body_parts: list[str]):
        self._types_all = list(imaging_types or [])
        self._parts_all = list(body_parts or [])

        if self.types_listbox is not None:
            self.types_listbox.delete(0, "end")
            for x in self._types_all:
                self.types_listbox.insert("end", x)

        if self.parts_listbox is not None:
            self.parts_listbox.delete(0, "end")
            for x in self._parts_all:
                self.parts_listbox.insert("end", x)

        # re-apply selections
        self._restore_selection(self.types_listbox, self._types_all, self._types_selected)
        self._restore_selection(self.parts_listbox, self._parts_all, self._parts_selected)

    def _restore_selection(self, lb: tk.Listbox | None, all_items: list[str], selected_items: list[str]):
        if lb is None:
            return
        try:
            lb.selection_clear(0, "end")
            sel = {_clean(x).lower() for x in (selected_items or [])}
            for i, item in enumerate(all_items):
                if _clean(item).lower() in sel:
                    lb.selection_set(i)
        except Exception:
            pass

    def _sync_from_widgets(self):
        try:
            if self.types_listbox is not None:
                self._types_selected = [self.types_listbox.get(i) for i in self.types_listbox.curselection()]
            if self.parts_listbox is not None:
                self._parts_selected = [self.parts_listbox.get(i) for i in self.parts_listbox.curselection()]
        except Exception:
            pass

        if callable(self.on_change):
            self.on_change()

    def get_selected(self) -> tuple[list[str], list[str]]:
        return (list(self._types_selected), list(self._parts_selected))

    def to_dict(self) -> dict:
        return {"types": list(self._types_selected), "parts": list(self._parts_selected)}

    def from_dict(self, d: dict):
        d = d or {}
        self._types_selected = list(d.get("types") or [])
        self._parts_selected = list(d.get("parts") or [])
        # Actual widget selection is restored once options are set


class HOIPage(ttk.Frame):
    """
    HOI page with dropdowns/radio buttons that IMMEDIATELY regenerate the MOI paragraph.

    Key behavior:
    - Auto-generate toggle (default ON):
        Any structured change regenerates MOI immediately.
    - Auto-generate OFF:
        MOI becomes manual and will not be overwritten.

    MOI always displays:
      - Patient first name from demographics if provided (else "The patient")
      - Pronouns based on sex radio selection (Male/Female/Unknown)
    """

    # -----------------------------
    # Options
    # -----------------------------
    INJURY_TYPES = ["(none)", "Auto Accident", "Slip and Fall", "Dog Bite", "Work Injury", "Other"]
    SEX_OPTIONS = ["(unknown)", "Female", "Male"]

    # Auto Accident specifics
    AA_ACCIDENT_TYPES = ["Moving Vehicle Accident", "Parked Vehicle Accident", "Intersection Accident", "Other"]
    AA_OTHER_VEHICLE_PART = ["front", "rear", "left side", "right side"]
    AA_PATIENT_SIDE = ["driver side", "passenger side", "front", "rear"]
    AA_RESEMBLES = ["rear-end", "T-bone", "head-on", "sideswipe", "other"]

    # Slip/Fall specifics
    SF_CIRCUMSTANCES = ["(none)", "a Slip", "a Trip", "a Missed step", "an Uneven surface", "a Wet floor", "Other"]
    SF_LANDING = ["(none)", "Back", "Side", "Front", "Knees", "Hands/Wrists", "Other"]

    # Dog bite specifics
    DB_LOCATION = ["(none)", "Hand", "Forearm", "Arm", "Leg", "Thigh", "Foot/Ankle", "Other"]
    DB_SEVERITY = ["(none)", "Superficial", "Puncture", "Laceration", "Other"]

    # Care / Treatment
    TREATMENT_RECEIVED = ["Did not receive", "Did receive"]
    CARE_SETTING = ["(none)", "Hospital", "Urgent Care", "Primary MD", "ER", "Chiropractic", "Physical Therapy", "Other"]

    # Medications
    MEDS_PRESCRIBED = ["Was not prescribed", "Was prescribed"]
    MED_CLASSES = [
        "Muscle Relaxers",
        "Anti-Inflammatories (NSAIDs)",
        "Pain Medications",
        "Steroids",
        "Injections",
        "Topical/Pain Patches",
        "Other",
    ]

    # Imaging
    IMAGING_DONE = ["No imaging", "Imaging performed"]
    IMAGING_TYPES = ["X-rays", "MRI", "CT", "Ultrasound", "Other"]
    IMAGING_BODYPART = [
        "(none)",
        "Cervical Spine", "Thoracic Spine", "Lumbar Spine",
        "Shoulder", "Elbow", "Wrist/Hand",
        "Hip", "Knee", "Ankle/Foot",
        "Other",
    ]

    # Clinical course
    COURSE = ["Improving", "Staying the same", "Getting worse"]

    # -----------------------------
    # helpers for smoother sentences
    # -----------------------------
    
        # ---------------- ROF helpers ----------------

    def _on_rof_input_mode_changed(self):
        if self._loading:
            return

        # show/hide the two areas (you'll set these refs below)
        mode = (self.rof_input_mode_var.get() or "Structured")

        try:
            if mode == "Text/Write":
                if getattr(self, "_rof_structured_wrap", None):
                    self._rof_structured_wrap.pack_forget()
                if getattr(self, "_rof_text_wrap", None):
                    self._rof_text_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            else:
                if getattr(self, "_rof_text_wrap", None):
                    self._rof_text_wrap.pack_forget()
                if getattr(self, "_rof_structured_wrap", None):
                    self._rof_structured_wrap.pack(fill="x", expand=False, padx=10, pady=(0, 8))
        except Exception:
            pass

        # regenerate preview/rof logic
        self._on_rof_struct_changed()


    def get_live_preview_runs(self):
        """
        Returns a list of (text, tag) tuples.
        tag can be None for normal text.
        """
        mode = _clean(self.rof_mode_var.get())
        if mode != "ROF":
            return []

        self._regen_rof_now()

        structured = _clean(self.rof_auto_paragraph_var.get())
        textwrite  = _clean(self.rof_manual_paragraph_var.get())

        if not (structured or textwrite):
            return []

        runs = []
        runs.append(("REVIEW OF FINDINGS\n", "H_BOLD"))
        runs.append(("\n", None))

        # structured first
        if structured:
            runs.append((structured + "\n\n", None))

        # text/write paragraph underneath
        if textwrite:
            runs.append((textwrite + "\n\n", None))

        return runs


    
    def _bind_wheel_to_widget(self, widget, *, yview_func=None, xview_func=None):
        """
        Routes mouse wheel to a specific widget only while the mouse is over it.
        - yview_func: callable like widget.yview_scroll
        - xview_func: callable like widget.xview_scroll (optional)
        Supports Windows/Mac (<MouseWheel>) and Linux (<Button-4/5>).
        """

        def _on_mousewheel(event):
            # SHIFT + wheel -> horizontal if provided
            if (event.state & 0x0001) and xview_func is not None:
                # Windows/Mac: event.delta; Linux: no delta on Button-4/5
                if hasattr(event, "delta") and event.delta:
                    step = -1 if event.delta > 0 else 1
                    xview_func(step, "units")
                return "break"

            if yview_func is not None:
                if hasattr(event, "delta") and event.delta:
                    # Windows: delta = 120 per notch; Mac may be smaller
                    step = int(-1 * (event.delta / 120)) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
                    yview_func(step, "units")
                return "break"

        def _on_linux_up(_event):
            if yview_func is not None:
                yview_func(-1, "units")
            return "break"

        def _on_linux_down(_event):
            if yview_func is not None:
                yview_func(1, "units")
            return "break"

        def _enable(_event=None):
            widget.bind("<MouseWheel>", _on_mousewheel)     # Win/Mac
            widget.bind("<Shift-MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_linux_up)         # Linux
            widget.bind("<Button-5>", _on_linux_down)

        def _disable(_event=None):
            widget.unbind("<MouseWheel>")
            widget.unbind("<Shift-MouseWheel>")
            widget.unbind("<Button-4>")
            widget.unbind("<Button-5>")

        widget.bind("<Enter>", _enable)
        widget.bind("<Leave>", _disable)

    
    
    def _layout_rof_blocks(self):
        if self._rof_blocks_row is None:
            return
        for child in self._rof_blocks_row.winfo_children():
            child.pack_forget()
        for i, blk in enumerate(self.rof_imaging_blocks, start=1):
            blk.set_number(i)
            blk.pack(side="left", padx=(0, 6), pady=(0, 8), fill="y")

    def _add_rof_block(self, from_dict: dict | None = None):
        if self._rof_blocks_row is None:
            return
        if len(self.rof_imaging_blocks) >= self.max_rof_blocks:
            return

        idx = len(self.rof_imaging_blocks) + 1
        block: ROFImagingBlock | None = None

        def remove_this():
            if block is not None:
                self._remove_rof_block(block)

        block = ROFImagingBlock(
            self._rof_blocks_row,
            index=idx,
            on_change=self._on_rof_struct_changed,
            on_remove=remove_this,
            imaging_types=self.IMAGING_TYPES,
            body_parts=[x for x in self.IMAGING_BODYPART if x and x != "(none)"],
            facilities=self.ROF_FACILITIES,
        )

        if from_dict:
            block.from_dict(from_dict)

        self.rof_imaging_blocks.append(block)
        self._layout_rof_blocks()
        self._on_rof_struct_changed()

    def _remove_rof_block(self, block: ROFImagingBlock):
        if block not in self.rof_imaging_blocks:
            return
        self.rof_imaging_blocks.remove(block)
        try:
            block.destroy()
        except Exception:
            pass
        self._layout_rof_blocks()
        self._on_rof_struct_changed()

    def _set_rof_auto_text(self, text: str):
        """
        Store the generated ROF paragraph.
        Display is handled by the Live Preview, not here.
        """
        self.rof_auto_paragraph_var.set(text or "")



    def _on_rof_struct_changed(self):
        if self._loading:
            return
        self._regen_rof_now()
        self._changed()

    def _regen_rof_now(self):
        if self._loading:
            return

        mode = _clean(self.rof_mode_var.get())

        # For now:
        # - ROF mode generates the imaging paragraph from blocks.
        # - Other modes leave auto paragraph blank (we'll add status-update templates later).
        if mode != "ROF":
            self._set_rof_auto_text("")
            return

        ctx = self._patient_ctx()
        first = _clean(ctx.get("first", "")) or "The patient"

        # collect meaningful entries (preserve the order blocks appear)
        entries: list[dict] = []
        for blk in self.rof_imaging_blocks:
            d = blk.get_selected() or {}
            itype = _clean(d.get("type", ""))
            parts = [p for p in (d.get("parts") or []) if _clean(p)]
            fac = _clean(d.get("facility", ""))
            city = _clean(d.get("city", ""))
            date = _clean(d.get("date", ""))


            # skip empty blocks
            if itype in ("", "(none)") and not parts and fac in ("", "(none)") and not city:
                continue

            entries.append({"type": itype, "parts": parts, "facility": fac, "city": city, "date": _clean(d.get("date", "")),})

        if not entries:
            self._set_rof_auto_text("")
            return

        # Group by (facility, city) but preserve first-seen order
        grouped_order: list[tuple[str, str]] = []
        grouped: dict[tuple[str, str], list[dict]] = {}

        for e in entries:
            key = (e["facility"], e["city"])
            if key not in grouped:
                grouped[key] = []
                grouped_order.append(key)
            grouped[key].append(e)

        # limit to 4 facilities (your design requirement)
        grouped_order = grouped_order[:4]

        def facility_text(facility: str, city: str) -> str:
            fac = _clean(facility)
            c = _clean(city)

            # normalize placeholders
            if fac.lower() in ("(none)", "none", "n/a"):
                fac = ""
            if c.lower() in ("(none)", "none", "n/a"):
                c = ""

            if fac and c:
                return f"{fac} in {c}"
            if fac:
                return fac
            if c:
                return c
            return ""


        def detail_for_items(items: list[dict]) -> str:
            phrase_list: list[str] = []
            for it in items:
                t = _clean(it.get("type", ""))
                parts_raw = it.get("parts") or []
                parts = [p.strip().lower() for p in parts_raw if _clean(p)]

                if t and t != "(none)" and parts:
                    phrase_list.append(f"{self._normalize_img_type(t)} of the {self._human_join(parts)}")
                elif t and t != "(none)":
                    phrase_list.append(f"{self._normalize_img_type(t)}")
                elif parts:
                    phrase_list.append(f"imaging of the {self._human_join(parts)}")

            phrase_list = [p for p in phrase_list if _clean(p)]
            return self._human_join(phrase_list)


        chunks: list[str] = []

        # Sentence 1 (neutral anchor — no global date)
        chunks.append(f"{first} underwent diagnostic imaging,")


        # Sentence templates for facilities 1–4
        # Each template expects: detail, facility_text (optional)
        templates = [
            ("which included {detail}{date_clause} at {place}.",
            "The imaging included {detail}{date_clause}."),

            ("The patient also received {detail}{date_clause} at {place}.",
            "The patient also received {detail}{date_clause}."),

            ("Additionally, {detail} were obtained{date_clause} at {place}.",
            "Additionally, {detail} were obtained{date_clause}."),

            ("Furthermore, {detail} were completed{date_clause} at {place}.",
            "Furthermore, {detail} were completed{date_clause}."),
        ]


        for idx, key in enumerate(grouped_order):
            facility, city = key
            items = grouped.get(key) or []

            detail = detail_for_items(items)
            if not detail:
                continue

            # Collect per-block dates for this facility group
            dates = [_clean(it.get("date", "")) for it in items if _clean(it.get("date", ""))]

            # If there's 1 unique date → " on <date>"
            # If multiple different dates exist → don't force one (keeps it clinically safer)
            uniq_dates = []
            seen = set()
            for d in dates:
                k = d.lower()
                if k not in seen:
                    seen.add(k)
                    uniq_dates.append(d)

            date_clause = f" on {uniq_dates[0]}" if len(uniq_dates) == 1 else ""


            place = facility_text(facility, city)

            # choose template
            t_with_place, t_no_place = templates[min(idx, len(templates) - 1)]

            if place:
                chunks.append(
                    t_with_place.format(
                        detail=detail,
                        place=place,
                        date_clause=date_clause
                    )
                )
            else:
                chunks.append(
                    t_no_place.format(
                        detail=detail,
                        date_clause=date_clause
                    )
                )


        final = " ".join([c for c in chunks if _clean(c)])
        self._set_rof_auto_text(final)


    
    
    def _ensure_period(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if s[-1] not in ".!?":
            return s + "."
        return s

    def _human_join(self, items: list[str]) -> str:
        items = [i.strip() for i in (items or []) if i and i.strip()]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"

    def _normalize_img_type(self, t: str) -> str:
        t = (t or "").strip()
        if not t:
            return ""
        mapping = {
            "X-rays": "x-ray films",
            "MRI": "MRI studies",
            "CT": "CT scans",
            "Ultrasound": "ultrasound images",
            "Other": "other imaging",
        }
        return mapping.get(t, t.lower())

    def _imaging_sentence_from_blocks(self) -> str:
        """
        Returns ONE smooth sentence that includes ALL blocks.
        Example:
          Diagnostic imaging was performed, including x-rays of the cervical spine, MRI of the lumbar spine, and CT scans of the elbow.
        """
        if self.imaging_done_var.get() != "Imaging performed":
            return ""

        phrases: list[str] = []

        # NEW blocks
        if self.imaging_blocks:
            for blk in self.imaging_blocks:
                types_raw, parts_raw = blk.get_selected()
                types = [self._normalize_img_type(x) for x in types_raw if _clean(x)]
                parts = [p.strip().lower() for p in parts_raw if _clean(p) and p != "(none)"]

                if not types and not parts:
                    continue

                type_txt = self._human_join(types) if types else "imaging"

                if parts:
                    part_txt = self._human_join(parts)
                    # "MRI of the lumbar spine"
                    if type_txt.lower() == "x-rays":
                        phrases.append(f"{type_txt} of the {part_txt}")
                    else:
                        phrases.append(f"{type_txt} of the {part_txt}")
                else:
                    phrases.append(f"{type_txt}")

        # Legacy fallback if no blocks exist
        if not phrases:
            legacy_types = [self._normalize_img_type(x) for x in (self._imaging_selected or []) if _clean(x)]
            legacy_bp = _clean(self.imaging_bodypart_var.get())
            if legacy_types and legacy_bp and legacy_bp != "(none)":
                phrases.append(f"{self._human_join(legacy_types)} of the {legacy_bp.lower()}")
            elif legacy_types:
                phrases.append(f"{self._human_join(legacy_types)}")
            elif legacy_bp and legacy_bp != "(none)":
                phrases.append(f"imaging of the {legacy_bp.lower()}")
            else:
                phrases.append("imaging studies")

        # if still nothing meaningful
        phrases = [p for p in phrases if _clean(p)]
        if not phrases:
            return ""

        return self._ensure_period("Diagnostic imaging was performed, including " + self._human_join(phrases))

    # -----------------------------
    # init
    # -----------------------------
    def __init__(self, parent, on_change_callback):
        super().__init__(parent)
        self.on_change_callback = on_change_callback

        #print("HOIPage INIT id:", id(self))       

                # ----------------
        # ROF / Status Update (new structured ROF block)
        # ----------------
        self.rof_mode_var = tk.StringVar(value="ROF")  # Initial / Re-Exam / ROF / Final
        
        # Facilities (edit this list anytime)
        self.ROF_FACILITIES = [
            "South Coast Imaging",
            "OC MRI & Radiology",
            "MemorialCare Imaging",
            "Hoag Radiology",
            "Other",
        ]

        # Two paragraphs: auto-generated + manual findings
        self.rof_auto_paragraph_var = tk.StringVar(value="")
        self.rof_manual_paragraph_var = tk.StringVar(value="")

        # UI refs        
        self._rof_manual_text: tk.Text | None = None
        self._rof_blocks_row: ttk.Frame | None = None

        # Imaging blocks (facility-aware)
        self.rof_imaging_blocks: list[ROFImagingBlock] = []
        self.max_rof_blocks = 4


        #Notes for Type of Injury
        self.course_notes_var = tk.StringVar(value="")  # type.course_notes (new)

        self.rof_input_mode_var = tk.StringVar(value="Structured")  # "Structured" or "Text"


        
        # Optional providers
        self._regions_provider = None
        self._patient_provider = None

        # Guards
        self._loading = False
        self._internal_set_moi = False  # prevent MOI typing from turning off auto during programmatic writes

        # Text widget bindings
        self._text_bindings: list[tuple[tk.Text, tk.StringVar]] = []
        self._moi_text: tk.Text | None = None

        # Auto toggle
        self.auto_moi_var = tk.BooleanVar(value=True)

        # ----------------
        # Vars (PDF-compatible keys)
        # ----------------
        self.active_block = tk.StringVar(value="History of Injury")

        self.moi_var = tk.StringVar(value="")               # history.moi
        self.doi_var = tk.StringVar(value="")               # doi.date
        self.injury_type_var = tk.StringVar(value="(none)") # type.injury_type

        self.prior_care_var = tk.StringVar(value="")        # prior_care.text
        self.meds_var = tk.StringVar(value="")              # meds.text
        self.diagnostics_var = tk.StringVar(value="")       # diagnostics.text
        self.other_notes_var = tk.StringVar(value="")       # other.text

        self.sex_var = tk.StringVar(value=self.SEX_OPTIONS[0])
        self.course_var = tk.StringVar(value=self.COURSE[0])

        # treatment
        self.treatment_received_var = tk.StringVar(value=self.TREATMENT_RECEIVED[0])
        self.care_setting_var = tk.StringVar(value="(none)")
        self.facility_name_var = tk.StringVar(value="")

        # meds
        self.meds_prescribed_var = tk.StringVar(value=self.MEDS_PRESCRIBED[0])
        self._meds_selected: list[str] = []
        self._meds_listbox: tk.Listbox | None = None

        # imaging
        self.imaging_done_var = tk.StringVar(value=self.IMAGING_DONE[0])

        # NEW: imaging blocks (lateral)
        self.imaging_blocks: list[ImagingBlock] = []
        self.max_imaging_blocks = 6  # adjust as you like
        self._imaging_blocks_row: ttk.Frame | None = None

        # legacy (backward compat)
        self._imaging_selected: list[str] = []
        self.imaging_bodypart_var = tk.StringVar(value="(none)")

        # auto accident
        self.aa_moving_var = tk.StringVar(value=self.AA_ACCIDENT_TYPES[0])
        self.aa_other_part_var = tk.StringVar(value=self.AA_OTHER_VEHICLE_PART[0])
        self.aa_patient_side_var = tk.StringVar(value=self.AA_PATIENT_SIDE[0])
        self.aa_resembles_var = tk.StringVar(value=self.AA_RESEMBLES[0])

        # slip/fall
        self.sf_circumstance_var = tk.StringVar(value=self.SF_CIRCUMSTANCES[0])
        self.sf_landing_var = tk.StringVar(value=self.SF_LANDING[0])

        # dog bite
        self.db_location_var = tk.StringVar(value=self.DB_LOCATION[0])
        self.db_severity_var = tk.StringVar(value=self.DB_SEVERITY[0])

        self._build_ui()
        self._wire_traces()
        self._show_block("History of Injury")
        self._regen_moi_now()

    # ---------------- Public hooks ----------------
    def set_regions_provider(self, fn):
        self._regions_provider = fn
        self._regen_moi_now()

    def set_patient_provider(self, fn):
        self._patient_provider = fn
        self._regen_moi_now()

    # ---------------- Change / autosave ----------------
    def _changed(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def _wire_traces(self):
        regen_drivers = [
            self.doi_var,
            self.injury_type_var,
            self.sex_var,
            self.course_var,
            self.course_notes_var,   # ✅ required
            self.treatment_received_var,
            self.care_setting_var,
            self.facility_name_var,
            self.meds_prescribed_var,
            self.imaging_done_var,
            self.aa_moving_var, self.aa_other_part_var,
            self.aa_patient_side_var, self.aa_resembles_var,
            self.sf_circumstance_var, self.sf_landing_var,
            self.db_location_var, self.db_severity_var,
            self.auto_moi_var,
            #self.rof_mode_var,
            #self.rof_imaging_date_var,
            #self.rof_include_city_var,
        ]
        for v in regen_drivers:
            v.trace_add("write", lambda *_: self._on_struct_changed())

                # -------------------------
        # ROF traces (DO NOT route through _on_struct_changed)
        # -------------------------
        for v in (self.rof_mode_var, self.rof_input_mode_var, self.rof_manual_paragraph_var):
            v.trace_add("write", lambda *_: self._on_rof_struct_changed())


        autosave_only = [
            self.moi_var,
            self.course_notes_var,      # ✅ new Clinical Course notes
            self.prior_care_var,
            self.meds_var,
            self.diagnostics_var,
            self.other_notes_var,
            self.active_block,
            self.rof_auto_paragraph_var,
            self.rof_manual_paragraph_var,
        ]

        for v in autosave_only:
            v.trace_add("write", lambda *_: self._changed())

    def _on_struct_changed(self):
        if self._loading:
            return

        # ✅ If user changes structured fields, force auto MOI ON
        if not self.auto_moi_var.get():
            self.auto_moi_var.set(True)

        self._regen_moi_now()
        self._changed()


    # ---------------- Text widget sync ----------------
    def _bind_text_to_var(self, widget: tk.Text, var: tk.StringVar, *, is_moi: bool = False):
        self._text_bindings.append((widget, var))

        def flush():
            try:
                var.set(widget.get("1.0", "end-1c"))
            except Exception:
                return

        def flush_and_changed(_evt=None):
            flush()
            if is_moi and (not self._internal_set_moi):
                if self.auto_moi_var.get():
                    self.auto_moi_var.set(False)
            self._changed()

        widget.bind("<KeyRelease>", flush_and_changed)
        widget.bind("<FocusOut>", flush_and_changed)
        widget.bind("<<Paste>>", lambda e: self.after(1, flush_and_changed))
        widget.bind("<<Cut>>", lambda e: self.after(1, flush_and_changed))

    def _flush_all_text_widgets(self):
        for w, v in self._text_bindings:
            try:
                v.set(w.get("1.0", "end-1c"))
            except Exception:
                pass

    def _push_vars_into_text_widgets(self):
        for w, v in self._text_bindings:
            try:
                w.delete("1.0", "end")
                w.insert("1.0", v.get() or "")
            except Exception:
                pass

    # ---------------- Patient helpers ----------------
    def _patient_ctx(self) -> dict:
        ctx = {"first": "", "sex": "", "doi": ""}

        if callable(self._patient_provider):
            try:
                d = self._patient_provider() or {}
                ctx["first"] = _clean(d.get("first", "")) or _clean(d.get("first_name", ""))
                ctx["sex"] = _clean(d.get("sex", ""))
                ctx["doi"] = _clean(d.get("doi", ""))
            except Exception:
                pass

        if _clean(self.sex_var.get()) not in ("", "(unknown)"):
            ctx["sex"] = _clean(self.sex_var.get())

        if _clean(self.doi_var.get()):
            ctx["doi"] = _clean(self.doi_var.get())

        return ctx

    def _pronouns(self, sex: str) -> dict:
        s = (sex or "").strip().lower()
        if s.startswith("m"):
            return {"subj": "he", "obj": "him", "poss": "his"}
        if s.startswith("f"):
            return {"subj": "she", "obj": "her", "poss": "her"}
        return {"subj": "they", "obj": "them", "poss": "their"}

    def _reports(self, first: str) -> str:
        return f"{first} reports" if first else "The patient reports"

    def _states(self, first: str) -> str:
        return f"{first} states" if first else "The patient states"

    def _injured_regions_from_provider(self) -> list[str]:
        if callable(self._regions_provider):
            try:
                vals = self._regions_provider() or []
                return _dedupe_preserve_order(vals)
            except Exception:
                return []
        return []

    # ---------------- Imaging blocks helpers ----------------
    def _add_imaging_block(self, from_dict: dict | None = None):
        if self._imaging_blocks_row is None:
            return
        if len(self.imaging_blocks) >= self.max_imaging_blocks:
            return

        idx = len(self.imaging_blocks) + 1

        block: ImagingBlock | None = None

        def remove_this():
            if block is not None:
                self._remove_imaging_block(block)

        block = ImagingBlock(
            self._imaging_blocks_row,
            index=idx,
            on_change=self._on_imaging_blocks_changed,
            on_remove=remove_this,
        )
        # Exclude "(none)" from parts in block UI
        block.set_options(self.IMAGING_TYPES, [x for x in self.IMAGING_BODYPART if x and x != "(none)"])

        if from_dict:
            block.from_dict(from_dict)

        self.imaging_blocks.append(block)
        self._layout_imaging_blocks()

        # reapply options to ensure selection restoration (safe even if redundant)
        if from_dict:
            block.set_options(self.IMAGING_TYPES, [x for x in self.IMAGING_BODYPART if x and x != "(none)"])

        self._on_imaging_blocks_changed()

    def _remove_imaging_block(self, block: ImagingBlock):
        if block not in self.imaging_blocks:
            return
        self.imaging_blocks.remove(block)
        try:
            block.destroy()
        except Exception:
            pass
        self._layout_imaging_blocks()
        self._on_imaging_blocks_changed()

    def _layout_imaging_blocks(self):
        if self._imaging_blocks_row is None:
            return

        # lateral packing
        for child in self._imaging_blocks_row.winfo_children():
            child.pack_forget()

        for i, blk in enumerate(self.imaging_blocks, start=1):
            blk.set_number(i)
            blk.pack(side="left", padx=(0, 12), pady=(0, 8), fill="y")

    def _on_imaging_blocks_changed(self):
        if self._loading:
            return

        # Update legacy fields from block #1 (compat)
        if self.imaging_blocks:
            types, parts = self.imaging_blocks[0].get_selected()
            self._imaging_selected = list(types)
            self.imaging_bodypart_var.set(parts[0] if parts else "(none)")
        else:
            self._imaging_selected = []
            self.imaging_bodypart_var.set("(none)")

        self._regen_moi_now()
        self._changed()
    
    # ---------------- MOI generation ----------------
    def _regen_moi_now(self):
        if self._loading:
            return
        if not self.auto_moi_var.get():
            return

        injury = _clean(self.injury_type_var.get())
        if not injury or injury == "(none)":
            self._set_moi_text("")
            return

        ctx = self._patient_ctx()
        first = ctx.get("first", "")
        sex = ctx.get("sex", "")
        pro = self._pronouns(sex)

        doi = _clean(ctx.get("doi", "")) or "____/____/________"

        reports = self._reports(first)
        states = self._states(first)

        # -------------------------
       # -------------------------
        # PARAGRAPH 1 – ACCIDENT / MECHANISM
        # -------------------------
        if injury == "Auto Accident":
            p1_parts = [
                f"{reports} {pro['subj']} was involved in a {self.aa_moving_var.get().strip().lower()} "
                f"on {doi}. The patient states the {self.aa_other_part_var.get().strip().lower()} portion of the "
                f"other vehicle struck {pro['poss']} vehicle on the "
                f"{self.aa_patient_side_var.get().strip().lower()}, and the mechanism of injury "
                f"most closely resembles a {self.aa_resembles_var.get().strip().lower()} collision."
            ]

            typed_course = _clean(self.course_notes_var.get())
            if typed_course:
                p1_parts.append(self._ensure_period(typed_course))

            p1 = " ".join(p1_parts)

        elif injury == "Slip and Fall":
            parts = [f"{reports} {pro['subj']} sustained a slip and fall injury on {doi}."]

            if self.sf_circumstance_var.get() != "(none)":
                parts.append(f"The patient states the incident involved {self.sf_circumstance_var.get().lower()}")
            if self.sf_landing_var.get() != "(none)":
                parts.append(f"and that {pro['subj']} landed primarily on the {self.sf_landing_var.get().lower()}.")

            typed_course = _clean(self.course_notes_var.get())
            if typed_course:
                parts.append(self._ensure_period(typed_course))

            p1 = " ".join(parts)

        elif injury == "Dog Bite":
            parts = [f"{reports} {pro['subj']} sustained injuries due to a dog bite on {doi}."]

            if self.db_location_var.get() != "(none)":
                parts.append(f"The patient states the bite involved the {self.db_location_var.get().lower()}")
            if self.db_severity_var.get() != "(none)":
                parts.append(f"and describes the bite as a {self.db_severity_var.get().lower()} type of wound.")

            typed_course = _clean(self.course_notes_var.get())
            if typed_course:
                parts.append(self._ensure_period(typed_course))

            p1 = " ".join(parts)

        else:
            parts = [f"{reports} sustained the following mechanism of injury on {doi}."]

            typed_course = _clean(self.course_notes_var.get())
            if typed_course:
                parts.append(self._ensure_period(typed_course))

            p1 = " ".join(parts)


        # -------------------------
        # PARAGRAPH 2 – MEDICAL
        # -------------------------
        medical_parts: list[str] = []

        if self.treatment_received_var.get() == "Did receive":
            setting = _clean(self.care_setting_var.get())
            facility = _clean(self.facility_name_var.get())
            if setting and setting != "(none)":
                line = f"The patient sought medical care at a {setting.lower()}"
                line += f", specifically at {facility}." if facility else "."
                medical_parts.append(line)
            typed_prior = _clean(self.prior_care_var.get())
            if typed_prior:
                medical_parts.append(self._ensure_period(typed_prior))
        else:
            medical_parts.append("The patient did not receive medical treatment immediately following the incident.")

        if self.meds_prescribed_var.get() == "Was prescribed" and self._meds_selected:
            meds = ", ".join([_clean(x).lower() for x in self._meds_selected if _clean(x)])
            if meds:
                medical_parts.append(f"The patient was prescribed medications including {meds}.")

        typed_meds = _clean(self.meds_var.get())
        if typed_meds and self.meds_prescribed_var.get() == "Was prescribed":
            medical_parts.append(self._ensure_period(typed_meds))

        img_sentence = _clean(self._imaging_sentence_from_blocks())
        if img_sentence:
            medical_parts.append(img_sentence)

        # Typed diagnostics notes flow as part of paragraph 2
        # Typed prior care notes (legacy textbox) as part of paragraph 2
        # Typed diagnostics notes flow as part of paragraph 2  ✅ MUST REMAIN LAST
        typed_diag = _clean(self.diagnostics_var.get())
        if typed_diag:
            medical_parts.append(self._ensure_period(typed_diag))


        p2 = " ".join([x for x in medical_parts if _clean(x)])

        # -------------------------
        # PARAGRAPH 3 – COURSE & REGIONS
        # -------------------------
        
        
        course = _clean(self.course_var.get()).lower()
        regions = self._injured_regions_from_provider()

        p3_parts: list[str] = []
        if course:
            p3_parts.append(f"Since the date of injury, the patient reports that the condition has been {course}.")
        #if regions:
            #p3_parts.append("The patient reports injuries involving the following body regions: " + ", ".join(regions) + ".")
        if regions:
            p3_parts.append(
                "The patient reports injuries to the following area or body regions: "
                + _join_with_and(regions) + "."
            )


        # ✅ NEW: typed course notes (final sentence of this paragraph area)
        #typed_course = _clean(self.course_notes_var.get())
        #if typed_course:
            #p3_parts.append(self._ensure_period(typed_course))


        p3 = " ".join([x for x in p3_parts if _clean(x)])

        # -------------------------
        # FINAL MOI
        # -------------------------
        final_moi = "\n\n".join(p for p in (p1, p2, p3, AUTO_MOI_TAG) if _clean(p))    
        self._set_moi_text(final_moi)       


    def _set_moi_text(self, text: str):
        text = text or ""
        self._internal_set_moi = True
        try:
            self.moi_var.set(text)
            if self._moi_text is not None and self._moi_text.winfo_exists():
                self._moi_text.delete("1.0", "end")
                self._moi_text.insert("1.0", text)
        finally:
            self._internal_set_moi = False

    # ---------------- UI ----------------
    def _build_ui(self):
        padx = 10

        self._section_buttons = {}

        style = ttk.Style()

        style.configure(
            "HOI.Section.TButton",
            font=("Segoe UI", 10, "normal")
        )

        style.configure(
            "HOI.Section.Active.TButton",
            font=("Segoe UI", 10, "bold")
        )

        # block buttons
        top = ttk.Frame(self)
        top.pack(fill="x", padx=padx, pady=(10, 6))

        ttk.Label(top, text="HOI Blocks:").pack(side="left", padx=(0, 8))

        self.block_buttons = ttk.Frame(top)
        self.block_buttons.pack(side="left", fill="x", expand=True)

        def add_btn(name):
            btn = tk.Button(
                self.block_buttons,
                text=name,
                font=("Segoe UI", 10),
                relief="raised",
                bd=1,
                command=lambda n=name: self._show_block(n),
            )
            btn.pack(side="left", padx=4)
            self._section_buttons[name] = btn



        add_btn("History of Injury")
        add_btn("Date of Injury")
        add_btn("Type of Injury")
        add_btn("Prior Care")
        add_btn("Medications")
        add_btn("Diagnostics")
        add_btn("Review of Findings")

                # container
        # ✅ Wrap everything below the top buttons in a vertical ScrollFrame
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, padx=padx, pady=(0, 10))

        self.container = ttk.Frame(self.scroll.content)
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)


        self.frames = {
            "History of Injury": self._build_history_block(self.container),
            "Date of Injury": self._build_doi_block(self.container),
            "Type of Injury": self._build_type_block(self.container),
            "Prior Care": self._build_prior_care_block(self.container),
            "Medications": self._build_meds_block(self.container),
            "Diagnostics": self._build_diagnostics_block(self.container),
            "Review of Findings": self._build_rof_block(self.container),

        }

        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")

    def _show_block(self, name: str):
        if name in self.frames:
            self.active_block.set(name)
            self.frames[name].tkraise()

            for key, btn in self._section_buttons.items():
                btn.configure(font=("Segoe UI", 10, "bold") if key == name else ("Segoe UI", 10))

            self._changed()



    # ---------------- Blocks ----------------
    def _build_history_block(self, parent):
        f = ttk.LabelFrame(parent, text="History of Injury")

        toggle_row = ttk.Frame(f)
        toggle_row.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Checkbutton(
            toggle_row,
            text="Auto-generate MOI from dropdowns (recommended)",
            variable=self.auto_moi_var,
            command=self._regen_moi_now,
        ).pack(side="left")

        ttk.Button(toggle_row, text="Regenerate now", command=self._regen_moi_now).pack(side="left", padx=(10, 0))

        ttk.Label(f, text="Mechanism of Injury (MOI):").pack(anchor="w", padx=10, pady=(6, 4))

        txt = tk.Text(f, height=12, wrap="word")
        txt.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._moi_text = txt
        txt.insert("1.0", self.moi_var.get() or "")
        self._bind_text_to_var(txt, self.moi_var, is_moi=True)
        return f

    def _build_doi_block(self, parent):
        f = ttk.LabelFrame(parent, text="Date of Injury / Patient Info")

        ttk.Label(f, text="Date of Injury (MM/DD/YYYY):").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Entry(f, textvariable=self.doi_var, width=18).grid(row=0, column=1, sticky="w", padx=10, pady=10)

        ttk.Label(f, text="Sex (for pronouns in MOI):").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Combobox(f, textvariable=self.sex_var, values=self.SEX_OPTIONS, state="readonly", width=18)\
            .grid(row=1, column=1, sticky="w", padx=10, pady=(0, 10))

        f.grid_columnconfigure(2, weight=1)
        return f

    def _build_type_block(self, parent):
        f = ttk.LabelFrame(parent, text="Type of Injury (Structured)")

        ttk.Label(f, text="Sex (pronouns):").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        sex_row = ttk.Frame(f)
        sex_row.grid(row=0, column=1, sticky="w", padx=10, pady=(10, 4))

        ttk.Radiobutton(sex_row, text="Male", value="Male", variable=self.sex_var).pack(side="left")
        ttk.Radiobutton(sex_row, text="Female", value="Female", variable=self.sex_var).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(sex_row, text="Unknown", value="(unknown)", variable=self.sex_var).pack(side="left", padx=(10, 0))

        ttk.Label(f, text="Type:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        ttk.Combobox(f, textvariable=self.injury_type_var, values=self.INJURY_TYPES, state="readonly", width=18)\
            .grid(row=1, column=1, sticky="w", padx=10, pady=10)

        panel = ttk.Frame(f)
        panel.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 10))
        panel.grid_columnconfigure(1, weight=1)

        aa = ttk.LabelFrame(panel, text="Auto Accident Details")
        aa.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        aa.grid_columnconfigure(1, weight=1)

        ttk.Label(aa, text="Accident type:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(aa, textvariable=self.aa_moving_var, values=self.AA_ACCIDENT_TYPES, state="readonly", width=26)\
            .grid(row=0, column=1, sticky="w", padx=8, pady=6)

        ttk.Label(aa, text="Other vehicle impact area:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(aa, textvariable=self.aa_other_part_var, values=self.AA_OTHER_VEHICLE_PART, state="readonly", width=26)\
            .grid(row=1, column=1, sticky="w", padx=8, pady=6)

        ttk.Label(aa, text="Struck patient vehicle on:").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(aa, textvariable=self.aa_patient_side_var, values=self.AA_PATIENT_SIDE, state="readonly", width=26)\
            .grid(row=2, column=1, sticky="w", padx=8, pady=6)

        ttk.Label(aa, text="Resembles:").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(aa, textvariable=self.aa_resembles_var, values=self.AA_RESEMBLES, state="readonly", width=26)\
            .grid(row=3, column=1, sticky="w", padx=8, pady=6)

        sf = ttk.LabelFrame(panel, text="Slip and Fall Details")
        sf.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        sf.grid_columnconfigure(1, weight=1)

        ttk.Label(sf, text="Circumstance:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(sf, textvariable=self.sf_circumstance_var, values=self.SF_CIRCUMSTANCES, state="readonly", width=26)\
            .grid(row=0, column=1, sticky="w", padx=8, pady=6)

        ttk.Label(sf, text="Primary landing area:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(sf, textvariable=self.sf_landing_var, values=self.SF_LANDING, state="readonly", width=26)\
            .grid(row=1, column=1, sticky="w", padx=8, pady=6)

        db = ttk.LabelFrame(panel, text="Dog Bite Details")
        db.grid(row=2, column=0, columnspan=4, sticky="ew")
        db.grid_columnconfigure(1, weight=1)

        ttk.Label(db, text="Bite location:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(db, textvariable=self.db_location_var, values=self.DB_LOCATION, state="readonly", width=26)\
            .grid(row=0, column=1, sticky="w", padx=8, pady=6)

        ttk.Label(db, text="Bite severity:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(db, textvariable=self.db_severity_var, values=self.DB_SEVERITY, state="readonly", width=26)\
            .grid(row=1, column=1, sticky="w", padx=8, pady=6)

        course = ttk.LabelFrame(panel, text="Clinical Course (Common)")
        course.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        course.grid_columnconfigure(1, weight=1)

        ttk.Label(course, text="Course:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Combobox(
            course,
            textvariable=self.course_var,
            values=self.COURSE,
            state="readonly",
            width=26
        ).grid(row=0, column=1, sticky="w", padx=8, pady=6)

        # ✅ NEW: small textbox appended to paragraph 3 (like Diagnostics behavior)
        ttk.Label(course, text="(Optional) Course notes (adds last sentence):", foreground="gray")\
            .grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))

        txt_course = tk.Text(course, height=3, wrap="word")  # small so it won’t hide bottom buttons
        txt_course.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        txt_course.insert("1.0", self.course_notes_var.get() or "")
        self._bind_text_to_var(txt_course, self.course_notes_var)


        def update_type_panels(*_):
            t = self.injury_type_var.get()
            for frame in (aa, sf, db):
                frame.grid_remove()
            if t == "Auto Accident":
                aa.grid()
            elif t == "Slip and Fall":
                sf.grid()
            elif t == "Dog Bite":
                db.grid()

        self.injury_type_var.trace_add("write", lambda *_: update_type_panels())
        update_type_panels()

        f.grid_columnconfigure(3, weight=1)
        return f

    def _build_prior_care_block(self, parent):
        f = ttk.LabelFrame(parent, text="Prior Care / Treatment (Structured)")

        ttk.Label(f, text="Medical treatment for current injuries:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Combobox(f, textvariable=self.treatment_received_var, values=self.TREATMENT_RECEIVED, state="readonly", width=18)\
            .grid(row=0, column=1, sticky="w", padx=10, pady=10)

        ttk.Label(f, text="Treatment setting:").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Combobox(f, textvariable=self.care_setting_var, values=self.CARE_SETTING, state="readonly", width=18)\
            .grid(row=1, column=1, sticky="w", padx=10, pady=(0, 10))

        ttk.Label(f, text="Facility name (optional):").grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Entry(f, textvariable=self.facility_name_var, width=32).grid(row=2, column=1, sticky="w", padx=10, pady=(0, 10))

        ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 10))
        ttk.Label(f, text="(Optional) Prior care notes (legacy):", foreground="gray")\
            .grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 4))

        txt = tk.Text(f, height=6, wrap="word")
        txt.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=10, pady=(0, 10))
        txt.insert("1.0", self.prior_care_var.get() or "")
        self._bind_text_to_var(txt, self.prior_care_var)

        f.grid_columnconfigure(2, weight=1)
        f.grid_rowconfigure(5, weight=1)
        return f

    def _build_meds_block(self, parent):
        f = ttk.LabelFrame(parent, text="Medications (Structured)")

        ttk.Label(f, text="Prescribed medications:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Combobox(f, textvariable=self.meds_prescribed_var, values=self.MEDS_PRESCRIBED, state="readonly", width=18)\
            .grid(row=0, column=1, sticky="w", padx=10, pady=10)

        ttk.Label(f, text="Medication classes (select all that apply):")\
            .grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        lb = tk.Listbox(f, selectmode="multiple", height=7, exportselection=False)
        for item in self.MED_CLASSES:
            lb.insert("end", item)
        lb.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))
        self._meds_listbox = lb

        def sync_meds(_evt=None):
            if self._loading:
                return
            self._meds_selected = [lb.get(i) for i in lb.curselection()]
            self._regen_moi_now()
            self._changed()

        lb.bind("<<ListboxSelect>>", sync_meds)

        ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 10))
        ttk.Label(f, text="(Optional) Medications notes (legacy):", foreground="gray")\
            .grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 4))

        txt = tk.Text(f, height=6, wrap="word")
        txt.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=10, pady=(0, 10))
        txt.insert("1.0", self.meds_var.get() or "")
        self._bind_text_to_var(txt, self.meds_var)

        f.grid_columnconfigure(2, weight=1)
        f.grid_rowconfigure(5, weight=1)
        return f

    def _build_diagnostics_block(self, parent):
        f = ttk.LabelFrame(parent, text="Diagnostics / Imaging (Structured)")

        ttk.Label(f, text="Imaging performed:").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Combobox(f, textvariable=self.imaging_done_var, values=self.IMAGING_DONE, state="readonly", width=18)\
            .grid(row=0, column=1, sticky="w", padx=10, pady=10)

        # controls row
        ctrls = ttk.Frame(f)
        ctrls.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        ttk.Button(ctrls, text="Add Imaging Block", command=self._add_imaging_block).pack(side="left")

        ttk.Label(ctrls, text="(Each block links imaging types to one or more body parts.)", foreground="gray")\
            .pack(side="left", padx=(10, 0))

        # lateral row
        row = ttk.Frame(f)
        row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 10))
        self._imaging_blocks_row = row

        # start with one block
        if not self.imaging_blocks:
            self._add_imaging_block()

        ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 10))
        ttk.Label(f, text="(Optional) Diagnostics notes (legacy):", foreground="gray")\
            .grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 4))

        txt = tk.Text(f, height=6, wrap="word")
        txt.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=10, pady=(0, 10))
        txt.insert("1.0", self.diagnostics_var.get() or "")
        self._bind_text_to_var(txt, self.diagnostics_var)

        f.grid_columnconfigure(2, weight=1)
        f.grid_rowconfigure(5, weight=1)
        return f

    def _build_rof_block(self, parent):
        f = ttk.LabelFrame(parent, text="Review of Findings")

        # =========================
        # Row 0: Mode + Entry toggle
        # =========================
        top = ttk.Frame(f)
        top.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Label(top, text="Mode:").pack(side="left")

        for label in ("Initial", "Re-Exam", "ROF", "Final"):
            ttk.Radiobutton(
                top,
                text=label,
                value=label,
                variable=self.rof_mode_var,
                command=self._on_rof_struct_changed,
            ).pack(side="left", padx=(10, 0))

        ttk.Label(top, text="   |   Entry:").pack(side="left", padx=(14, 0))

        ttk.Radiobutton(
            top,
            text="Structured",
            value="Structured",
            variable=self.rof_input_mode_var,
            command=self._on_rof_input_mode_changed,
        ).pack(side="left", padx=(8, 0))

        ttk.Radiobutton(
            top,
            text="Text/Write",
            value="Text/Write",
            variable=self.rof_input_mode_var,
            command=self._on_rof_input_mode_changed,
        ).pack(side="left", padx=(8, 0))

        # =========================
        # Two wraps (toggle visibility)
        # =========================
        structured_wrap = ttk.Frame(f)
        structured_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._rof_structured_wrap = structured_wrap

        text_wrap = ttk.Frame(f)
        self._rof_text_wrap = text_wrap  # not packed until Text/Write is active

        # =========================
        # STRUCTURED area (controls + imaging)
        # =========================
        row_ctrls = ttk.Frame(structured_wrap)
        row_ctrls.pack(fill="x", pady=(0, 6))

        ttk.Button(row_ctrls, text="Add Imaging", command=self._add_rof_block).pack(side="left")
        ttk.Label(
            row_ctrls,
            text="(Use multiple blocks if imaging occurred at different facilities.)",
            foreground="gray",
        ).pack(side="left", padx=(10, 0))

        # Imaging area should expand downward
        wrap = ttk.Frame(structured_wrap)
        wrap.pack(fill="both", expand=True)  # ✅ this is the key

        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(wrap, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")

        vbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns")

        hbar = ttk.Scrollbar(wrap, orient="horizontal", command=canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew")

        canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        inner = ttk.Frame(canvas)
        self._rof_blocks_row = inner
        canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(_evt=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_configure)

        # hover-only wheel routing
        self._bind_wheel_to_widget(canvas, yview_func=canvas.yview_scroll, xview_func=canvas.xview_scroll)
        self._bind_wheel_to_widget(inner,  yview_func=canvas.yview_scroll, xview_func=canvas.xview_scroll)

        if not self.rof_imaging_blocks:
            self._add_rof_block()

        # =========================
        # TEXT/WRITE area
        # =========================
        ttk.Label(text_wrap, text="Manual findings paragraph (you type):").pack(anchor="w", padx=10, pady=(0, 4))
        txt_manual = tk.Text(text_wrap, height=12, wrap="word")
        txt_manual.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._rof_manual_text = txt_manual
        txt_manual.insert("1.0", self.rof_manual_paragraph_var.get() or "")
        def _rof_manual_changed(_evt=None):
            if self._loading:
                return
            try:
                self.rof_manual_paragraph_var.set(txt_manual.get("1.0", "end-1c"))
            except Exception:
                return
            self._on_rof_struct_changed()  # ✅ this triggers ROF regen + _changed()

        txt_manual.bind("<KeyRelease>", _rof_manual_changed)
        txt_manual.bind("<FocusOut>", _rof_manual_changed)
        txt_manual.bind("<<Paste>>", lambda e: self.after(1, _rof_manual_changed))
        txt_manual.bind("<<Cut>>",   lambda e: self.after(1, _rof_manual_changed))

        # initialize visibility
        self._on_rof_input_mode_changed()
        self._regen_rof_now()
        return f




    # ---------------- Export ----------------
    def to_dict(self) -> dict:
        self._flush_all_text_widgets()

        # ✅ FORCE ROF flush (bulletproof)
        if self._rof_manual_text is not None and self._rof_manual_text.winfo_exists():
            self.rof_manual_paragraph_var.set(self._rof_manual_text.get("1.0", "end-1c"))
       

        #print("ROF manual widget preview:", self._rof_manual_text.get("1.0","end-1c")[:80] if self._rof_manual_text else None)
        #print("ROF manual var preview:", (self.rof_manual_paragraph_var.get() or "")[:80])
        #print("ROF blocks:", [b.get_selected() for b in (self.rof_imaging_blocks or [])])


        imaging_blocks_struct = [b.to_dict() for b in self.imaging_blocks] if self.imaging_blocks else []

        # ✅ REVIEW OF FINDINGS (NEW STRUCTURED)
        rof_blocks_struct = [b.to_dict() for b in self.rof_imaging_blocks] if self.rof_imaging_blocks else []

        return {
            "active_block": self.active_block.get(),

            "rof": {
                "mode": self.rof_mode_var.get(),
                "auto_paragraph": self.rof_auto_paragraph_var.get(),
                "manual_paragraph": self.rof_manual_paragraph_var.get(),
                "imaging_blocks": rof_blocks_struct,
            },

            "history": {"moi": self.moi_var.get()},
            "doi": {"date": self.doi_var.get()},
            "type": {"injury_type": self.injury_type_var.get()},
            "prior_care": {"text": self.prior_care_var.get()},
            "meds": {"text": self.meds_var.get()},
            "diagnostics": {"text": self.diagnostics_var.get()},
            "other": {"text": self.other_notes_var.get()},

            "struct": {
                "auto_moi": bool(self.auto_moi_var.get()),
                "sex": self.sex_var.get(),
                "course": self.course_var.get(),
                "course_notes": self.course_notes_var.get(),  # ✅ NEW (best place)
                "treatment_received": self.treatment_received_var.get(),
                "care_setting": self.care_setting_var.get(),
                "facility_name": self.facility_name_var.get(),
                "meds_prescribed": self.meds_prescribed_var.get(),
                "med_classes": list(self._meds_selected),

                "imaging_done": self.imaging_done_var.get(),
                "imaging_blocks": imaging_blocks_struct,

                "imaging_types": list(self._imaging_selected),
                "imaging_bodypart": self.imaging_bodypart_var.get(),

                "auto_accident": {
                    "accident_type": self.aa_moving_var.get(),
                    "other_vehicle_part": self.aa_other_part_var.get(),
                    "patient_side": self.aa_patient_side_var.get(),
                    "resembles": self.aa_resembles_var.get(),
                },
                "slip_fall": {
                    "circumstance": self.sf_circumstance_var.get(),
                    "landing": self.sf_landing_var.get(),
                },
                "dog_bite": {
                    "location": self.db_location_var.get(),
                    "severity": self.db_severity_var.get(),
                },
            }
        }


    def from_dict(self, data: dict):
        data = data or {}
        self._loading = True
        try:
            self.active_block.set(data.get("active_block", "History of Injury"))
            # -------- ROF (new structured) --------
            rof = data.get("rof") or {}

            self.rof_mode_var.set(rof.get("mode", "ROF") or "ROF")            
            self.rof_auto_paragraph_var.set(rof.get("auto_paragraph", "") or "")
            self.rof_manual_paragraph_var.set(rof.get("manual_paragraph", "") or "")

            # rebuild ROF imaging blocks
            for b in list(self.rof_imaging_blocks):
                try:
                    b.destroy()
                except Exception:
                    pass
            self.rof_imaging_blocks.clear()

            blocks = list(rof.get("imaging_blocks") or [])
            if blocks:
                for bd in blocks:
                    self._add_rof_block(from_dict=bd or {})
            else:
                # ensure at least one empty block exists
                self._add_rof_block()

            # push text into widgets if UI already built (ROF auto)
            txt = getattr(self, "_rof_auto_text", None)
            if txt is not None and txt.winfo_exists():
                try:
                    txt.configure(state="normal")   # ✅ temporarily unlock
                    txt.delete("1.0", "end")
                    txt.insert("1.0", self.rof_auto_paragraph_var.get() or "")
                finally:
                    try:
                        txt.configure(state="disabled")  # ✅ lock back
                    except Exception:
                        pass


            if self._rof_manual_text is not None and self._rof_manual_text.winfo_exists():
                try:
                    self._rof_manual_text.delete("1.0", "end")
                    self._rof_manual_text.insert("1.0", self.rof_manual_paragraph_var.get() or "")
                except Exception:
                    pass

            self.moi_var.set(((data.get("history") or {}).get("moi")) or "")
            self.doi_var.set(((data.get("doi") or {}).get("date")) or "")
            self.injury_type_var.set(((data.get("type") or {}).get("injury_type")) or "(none)")
            self.prior_care_var.set(((data.get("prior_care") or {}).get("text")) or "")
            self.meds_var.set(((data.get("meds") or {}).get("text")) or "")
            self.diagnostics_var.set(((data.get("diagnostics") or {}).get("text")) or "")
            self.other_notes_var.set(((data.get("other") or {}).get("text")) or "")

            struct = data.get("struct") or {}
            self.course_notes_var.set(struct.get("course_notes", ""))
            self.auto_moi_var.set(bool(struct.get("auto_moi", True)))

            self.sex_var.set(struct.get("sex", self.SEX_OPTIONS[0]))
            self.course_var.set(struct.get("course", self.COURSE[0]))

            self.treatment_received_var.set(struct.get("treatment_received", self.TREATMENT_RECEIVED[0]))
            self.care_setting_var.set(struct.get("care_setting", "(none)"))
            self.facility_name_var.set(struct.get("facility_name", ""))

            self.meds_prescribed_var.set(struct.get("meds_prescribed", self.MEDS_PRESCRIBED[0]))
            self._meds_selected = list(struct.get("med_classes") or [])

            self.imaging_done_var.set(struct.get("imaging_done", self.IMAGING_DONE[0]))

            # imaging blocks
            blocks = list(struct.get("imaging_blocks") or [])
            legacy_types = list(struct.get("imaging_types") or [])
            legacy_bp = _clean(struct.get("imaging_bodypart", "")) or "(none)"

            # Clear existing blocks
            for b in list(self.imaging_blocks):
                try:
                    b.destroy()
                except Exception:
                    pass
            self.imaging_blocks.clear()

            # Rebuild
            if blocks:
                for bd in blocks:
                    self._add_imaging_block(from_dict=bd or {})
            else:
                self._add_imaging_block(from_dict={
                    "types": legacy_types,
                    "parts": [legacy_bp] if legacy_bp not in ("", "(none)") else []
                })

            # update legacy vars too
            self._imaging_selected = legacy_types
            self.imaging_bodypart_var.set(legacy_bp)

            aa = struct.get("auto_accident") or {}
            self.aa_moving_var.set(aa.get("accident_type", self.AA_ACCIDENT_TYPES[0]))
            self.aa_other_part_var.set(aa.get("other_vehicle_part", self.AA_OTHER_VEHICLE_PART[0]))
            self.aa_patient_side_var.set(aa.get("patient_side", self.AA_PATIENT_SIDE[0]))
            self.aa_resembles_var.set(aa.get("resembles", self.AA_RESEMBLES[0]))

            sf = struct.get("slip_fall") or {}
            self.sf_circumstance_var.set(sf.get("circumstance", self.SF_CIRCUMSTANCES[0]))
            self.sf_landing_var.set(sf.get("landing", self.SF_LANDING[0]))

            db = struct.get("dog_bite") or {}
            self.db_location_var.set(db.get("location", self.DB_LOCATION[0]))
            self.db_severity_var.set(db.get("severity", self.DB_SEVERITY[0]))

            self._push_vars_into_text_widgets()
            self._restore_listbox_selection(self._meds_listbox, self.MED_CLASSES, self._meds_selected)

            if self._moi_text is not None and self._moi_text.winfo_exists():
                self._internal_set_moi = True
                try:
                    self._moi_text.delete("1.0", "end")
                    self._moi_text.insert("1.0", self.moi_var.get() or "")
                finally:
                    self._internal_set_moi = False

        finally:
            self._loading = False

        self._regen_moi_now()
        self._show_block(self.active_block.get())

    def _restore_listbox_selection(self, lb, all_items, selected_items):
        if lb is None:
            return
        try:
            lb.selection_clear(0, "end")
            sel_set = {_clean(x).lower() for x in (selected_items or [])}
            for i, item in enumerate(all_items):
                if _clean(item).lower() in sel_set:
                    lb.selection_set(i)
        except Exception:
            pass

    # ---------------- Utilities ----------------
    def has_content(self) -> bool:
        self._flush_all_text_widgets()

        # --- ROF checks (new model) ---
        # Manual ROF paragraph (Text/Write mode)
        if _clean(self.rof_manual_paragraph_var.get()):
            return True

        # Any structured imaging blocks content
        if any(
            _clean((b.get_selected() or {}).get("type", "")) not in ("", "(none)") or
            any(_clean(x) for x in ((b.get_selected() or {}).get("parts") or [])) or
            _clean((b.get_selected() or {}).get("facility", "")) not in ("", "(none)") or
            _clean((b.get_selected() or {}).get("city", "")) or
            _clean((b.get_selected() or {}).get("date", ""))
            for b in (self.rof_imaging_blocks or [])
        ):
            return True

        # Existing check
        if _clean(self.injury_type_var.get()) not in ("", "(none)"):
            return True

        return any(
            _clean(v.get())
            for v in (
                self.moi_var,
                self.doi_var,
                self.prior_care_var,
                self.meds_var,
                self.diagnostics_var,
                self.other_notes_var,
            )
        )


    def reset(self):
        if not messagebox.askyesno("Reset HOI", "Are you sure you want to clear ALL HOI fields?"):
            return

        self._loading = True
        try:
            self.active_block.set("History of Injury")

            self.auto_moi_var.set(True)

            self.moi_var.set("")
            self.doi_var.set("")
            self.injury_type_var.set("(none)")

            self.prior_care_var.set("")
            self.meds_var.set("")
            self.diagnostics_var.set("")
            self.other_notes_var.set("")

            self.sex_var.set(self.SEX_OPTIONS[0])
            self.course_var.set(self.COURSE[0])

            self.treatment_received_var.set(self.TREATMENT_RECEIVED[0])
            self.care_setting_var.set("(none)")
            self.facility_name_var.set("")

            self.meds_prescribed_var.set(self.MEDS_PRESCRIBED[0])
            self._meds_selected = []
            self._restore_listbox_selection(self._meds_listbox, self.MED_CLASSES, [])

            self.imaging_done_var.set(self.IMAGING_DONE[0])

            # reset imaging blocks to 1 empty
            for b in list(self.imaging_blocks):
                try:
                    b.destroy()
                except Exception:
                    pass
            self.imaging_blocks.clear()

            # =========================
            # ✅ INSERT ROF RESET HERE
            # =========================
            self.rof_mode_var.set("ROF")        
            self.rof_auto_paragraph_var.set("")
            self.rof_manual_paragraph_var.set("")

            for b in list(self.rof_imaging_blocks):
                try:
                    b.destroy()
                except Exception:
                    pass
            self.rof_imaging_blocks.clear()

        finally:
            self._loading = False

        # recreate one empty imaging block (after loading guard ends)
        if self._imaging_blocks_row is not None:
            self._add_imaging_block()

        # =========================
        # ✅ ADD THIS RIGHT AFTER imaging block recreation
        # =========================
        if self._rof_blocks_row is not None:
            self._add_rof_block()

        # legacy reset
        self._imaging_selected = []
        self.imaging_bodypart_var.set("(none)")

        self.aa_moving_var.set(self.AA_ACCIDENT_TYPES[0])
        self.aa_other_part_var.set(self.AA_OTHER_VEHICLE_PART[0])
        self.aa_patient_side_var.set(self.AA_PATIENT_SIDE[0])
        self.aa_resembles_var.set(self.AA_RESEMBLES[0])

        self.sf_circumstance_var.set(self.SF_CIRCUMSTANCES[0])
        self.sf_landing_var.set(self.SF_LANDING[0])

        self.db_location_var.set(self.DB_LOCATION[0])
        self.db_severity_var.set(self.DB_SEVERITY[0])

        self._push_vars_into_text_widgets()

        # optional: regenerate ROF auto paragraph after resetting blocks
        self._regen_rof_now()

        self._regen_moi_now()
        self._show_block("History of Injury")
        self._changed()
