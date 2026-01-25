# ui_blocks.py

import tkinter as tk
from tkinter import ttk
import re

from config import (
    PAIN_DESCRIPTORS, RADIC_SYMPTOMS, RADIC_LOCATIONS,
    REGION_OPTIONS, REGION_LABELS, REGION_MUSCLES
)
from utils import build_sentence


PAIN_SCALE_OPTIONS = [
    "None",
    "Minimum",
    "Minimum to Mild",
    "Mild",
    "Mild to Moderate",
    "Moderate",
    "Moderate to Severe",
    "Severe",
    "Unbearable",
]

# Optional: vary the muscle sentence a little (keeps it clinically defensible)
MUSCLE_TEMPLATES_ONE = [
    "The patient points to the {a} as the area of tenderness.",
    "Tenderness is localized to the {a}.",
    "The patient indicates the {a} as the primary area of tenderness.",
]
MUSCLE_TEMPLATES_TWO = [
    "The patient points to the {a} along with the {b} as the area of tenderness.",
    "Tenderness is noted in the {a} and the {b}.",
    "The patient indicates tenderness in the {a} as well as the {b}.",
]
MUSCLE_TEMPLATES_MANY = [
    "The patient points to the {mid}, along with the {last} as the area of tenderness.",
    "Tenderness is reported in the {mid}, and the {last}.",
    "The patient indicates tenderness across the {mid}, as well as the {last}.",
]


class DescriptorBlock:
    """
    Key behaviors:
    - Randomization occurs ONLY when we auto-generate.
    - When loading a saved case, we never re-roll or overwrite the saved narrative.
    - Changing dropdowns/checkmarks re-generates ONLY if the current narrative looks auto-generated.
    """

    def __init__(self, parent, block_index: int, on_change_callback):
        self.block_index = block_index
        self.on_change_callback = on_change_callback

        # --- internal flags ---
        self._loading_block = False
        self._last_region_code = "(none)"

        # --- vars ---
        self.region_var = tk.StringVar(value="(none)")
        self.desc1_var = tk.StringVar(value=PAIN_DESCRIPTORS[0])
        self.desc2_var = tk.StringVar(value="(none)")
        self.radic_symptom_var = tk.StringVar(value="None")
        self.radic_location_var = tk.StringVar(value="(select)")
        self.pain_scale_var = tk.StringVar(value="None")

        self.frame = ttk.LabelFrame(parent, text=f"Pain Descriptor Block {block_index}")
        self._build_widgets()

        self._last_region_code = self.region_var.get()

        # Region change: rebuild muscles + update narrative (if auto)
        self.region_var.trace_add("write", lambda *_: self._on_region_change())

        # Other dropdowns: update narrative (if auto)
        for v in (
            self.desc1_var,
            self.desc2_var,
            self.radic_symptom_var,
            self.radic_location_var,
            self.pain_scale_var,
        ):
            v.trace_add("write", lambda *_: self._on_descriptor_change())

        # Guard radic location when symptom is None
        self.radic_symptom_var.trace_add("write", lambda *_: self._radic_guard())

        # User typing: do not auto-overwrite from that point onward unless it still matches auto patterns
        self.narrative_text.bind("<KeyRelease>", self._auto_resize_text)


        # initial auto-fill
        self.update_narrative(overwrite_if_auto=True)

    def _build_widgets(self):
        self._loading_block = True
        try:
            padx, pady = 10, 6

            ttk.Label(self.frame, text="Body region:").grid(
                row=0, column=0, sticky="w", padx=padx, pady=pady
            )
            ttk.Combobox(
                self.frame,
                textvariable=self.region_var,
                values=REGION_OPTIONS,
                state="readonly",
                width=10
            ).grid(row=0, column=1, sticky="w", padx=padx, pady=pady)

            # Region label (pretty name)
            self.region_label_var = tk.StringVar(value="")
            ttk.Label(self.frame, textvariable=self.region_label_var, foreground="gray").grid(
                row=0, column=2, sticky="w", padx=padx, pady=pady
            )

            # ✅ must exist BEFORE _rebuild_muscles()
            self.muscle_vars: dict[str, tk.BooleanVar] = {}

            # Primary / secondary descriptors
            ttk.Label(self.frame, text="Primary pain descriptor:").grid(
                row=1, column=0, sticky="w", padx=padx, pady=pady
            )
            ttk.Combobox(
                self.frame,
                textvariable=self.desc1_var,
                values=PAIN_DESCRIPTORS,
                state="readonly",
                width=26
            ).grid(row=1, column=1, columnspan=2, sticky="w", padx=padx, pady=pady)

            ttk.Label(self.frame, text="Secondary pain descriptor:").grid(
                row=2, column=0, sticky="w", padx=padx, pady=pady
            )
            ttk.Combobox(
                self.frame,
                textvariable=self.desc2_var,
                values=["(none)"] + PAIN_DESCRIPTORS,
                state="readonly",
                width=26
            ).grid(row=2, column=1, columnspan=2, sticky="w", padx=padx, pady=pady)

            # Radiculopathy
            ttk.Label(self.frame, text="Radiculopathy symptom:").grid(
                row=3, column=0, sticky="w", padx=padx, pady=pady
            )
            ttk.Combobox(
                self.frame,
                textvariable=self.radic_symptom_var,
                values=RADIC_SYMPTOMS,
                state="readonly",
                width=26
            ).grid(row=3, column=1, columnspan=2, sticky="w", padx=padx, pady=pady)

            ttk.Label(self.frame, text="Radiculopathy location:").grid(
                row=4, column=0, sticky="w", padx=padx, pady=pady
            )
            ttk.Combobox(
                self.frame,
                textvariable=self.radic_location_var,
                values=RADIC_LOCATIONS,
                state="readonly",
                width=26
            ).grid(row=4, column=1, columnspan=2, sticky="w", padx=padx, pady=pady)

            # Overall pain scale (ROW 5)
            ttk.Label(self.frame, text="Overall pain scale:").grid(
                row=5, column=0, sticky="w", padx=padx, pady=pady
            )
            self.pain_scale_cb = ttk.Combobox(
                self.frame,
                textvariable=self.pain_scale_var,
                values=PAIN_SCALE_OPTIONS,
                state="readonly",
                width=26
            )
            self.pain_scale_cb.grid(row=5, column=1, columnspan=2, sticky="w", padx=padx, pady=pady)
            self.pain_scale_cb.bind("<<ComboboxSelected>>", lambda e: self._on_descriptor_change())

            # Narrative label + textbox (ROWS 6 & 7)
            ttk.Label(self.frame, text="Narrative (edit if desired):").grid(
                row=6, column=0, columnspan=3, sticky="w", padx=padx, pady=(10, 0)
            )
            self.narrative_text = tk.Text(self.frame, height=6, wrap="word")
            self.narrative_text.grid(row=7, column=0, columnspan=3, sticky="we", padx=padx, pady=(0, 10))

            # --- Patient points to (moved BELOW Narrative) ---
            ttk.Label(
                self.frame,
                text="Patient points to:",
                font=("Segoe UI", 9, "bold")
            ).grid(row=8, column=0, columnspan=3, sticky="w", padx=padx, pady=(0, 2))

            self.muscles_frame = ttk.Frame(self.frame)
            self.muscles_frame.grid(row=9, column=0, columnspan=3, sticky="ew", padx=padx, pady=(0, 10))
            self.muscles_frame.grid_columnconfigure(0, weight=1)
            self.muscles_frame.grid_columnconfigure(1, weight=1)

            # Narrative bold style
            bold_font = ("Segoe UI", 10, "bold")
            self.narrative_text.tag_configure("bold", font=bold_font)

            # Let the narrative area expand
            self.frame.grid_columnconfigure(2, weight=1)

            # ✅ NOW safe: muscles_frame + muscle_vars exist
            self._rebuild_muscles()

        finally:
            self._loading_block = False
        

    
    def _bold_phrases(self, phrases: list[str]):
        text = self.narrative_text.get("1.0", tk.END)

        for phrase in phrases:
            if not phrase:
                continue

            start = "1.0"
            while True:
                pos = self.narrative_text.search(
                    phrase, start, stopindex=tk.END, nocase=True
                )
                if not pos:
                    break

                end = f"{pos}+{len(phrase)}c"
                self.narrative_text.tag_add("bold", pos, end)
                start = end       
    
    
    def _rebuild_muscles(self):

        if not hasattr(self, "muscles_frame") or not hasattr(self, "muscle_vars"):
            return

        # Preserve current selection before clearing
        previously_selected = {m for m, v in self.muscle_vars.items() if v.get()}

        for child in self.muscles_frame.winfo_children():
            child.destroy()
        self.muscle_vars.clear()

        code = self.region_var.get()
        muscles = REGION_MUSCLES.get(code, [])
        if not muscles:
            return

        for i, m in enumerate(muscles):
            v = tk.BooleanVar(value=(m in previously_selected))
            self.muscle_vars[m] = v

            cb = ttk.Checkbutton(
                self.muscles_frame,
                text=m,
                variable=v,
                command=self._on_descriptor_change  # do not rebuild muscles here
            )
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 10))
            


    def _radic_guard(self):
        if self.radic_symptom_var.get() == "None":
            self.radic_location_var.set("(select)")

    def _on_region_change(self):
        if getattr(self, "_loading_block", False) or getattr(self, "_loading_from_file", False):
            return

        code = self.region_var.get()
        if code != self._last_region_code:
            self._last_region_code = code
            self._rebuild_muscles()

        self.update_narrative(overwrite_if_auto=True)
        if callable(self.on_change_callback):
            self.on_change_callback()


    def _on_descriptor_change(self):
        if getattr(self, "_loading_block", False) or getattr(self, "_loading_from_file", False):
            return

        self.update_narrative(overwrite_if_auto=True)
        if callable(self.on_change_callback):
            self.on_change_callback()



    def is_active(self) -> bool:
        return self.region_var.get() in REGION_LABELS

    def get_narrative(self) -> str:
        return self.narrative_text.get("1.0", tk.END).strip()
       
    
    def update_narrative(self, overwrite_if_auto: bool):
        # Never regenerate while loading a saved file
        if getattr(self, "_loading_from_file", False):
            return

        code = self.region_var.get()
        label = REGION_LABELS.get(code, "")
        self.region_label_var.set(label)

        # If no region, clear only if allowed
        if code == "(none)" or not label:
            if overwrite_if_auto:
                self.narrative_text.delete("1.0", tk.END)
            return

        # 1) Base sentence (region + descriptors + radic)
        base_sentence = build_sentence(
            label,
            self.desc1_var.get(),
            self.desc2_var.get(),
            self.radic_symptom_var.get(),
            self.radic_location_var.get()
        )

        # 2) Deterministic muscle tenderness sentence (NO RANDOM)
        selected = [m for m, v in self.muscle_vars.items() if v.get()]

        tenderness_sentence = ""
        if selected:
            if len(selected) == 1:
                tenderness_sentence = f"The patient indicates or points to the {selected[0]} as the area of tenderness."
            elif len(selected) == 2:
                tenderness_sentence = f"The patient indicates or points to the {selected[0]} and the {selected[1]} as the areas of tenderness."
            else:
                # Oxford comma style: a, b, and c
                mid = ", ".join(selected[:-1])
                last = selected[-1]
                tenderness_sentence = f"The patient indicates or points to the {mid}, and the {last} as the areas of tenderness."

        # 3) Pain scale sentence
        scale = (self.pain_scale_var.get() or "None").strip()
        pain_line = f"The patient states the overall discomfort in this area is {scale.lower()}."

        # Final narrative (paragraph style)
        parts = [base_sentence]
        if tenderness_sentence:
            parts.append(tenderness_sentence)
        parts.append(pain_line)
        auto_sentence = "\n\n".join(p for p in parts if p.strip())

        # 4) Overwrite decision logic (only overwrite if blank or looks auto-generated)
        current = self.get_narrative()

        lead_re = re.compile(r"\bThe patient reports symptoms in the\b", re.IGNORECASE)
        tenderness_re = re.compile(r"\bTenderness is localized to the\b", re.IGNORECASE)
        pain_line_re = re.compile(r"\boverall discomfort in this area\b", re.IGNORECASE)

        if (
            not current
            or lead_re.search(current)
            or tenderness_re.search(current)
            or pain_line_re.search(current)
        ):
            self.narrative_text.delete("1.0", tk.END)
            self.narrative_text.insert(tk.END, auto_sentence)

            # ---- APPLY BOLDING (AFTER INSERT) ----
            bold_terms = []

            # pain descriptors
            for d in (self.desc1_var.get(), self.desc2_var.get()):
                if d and d not in ("(none)",):
                    bold_terms.append(d)

            # radiculopathy
            if self.radic_symptom_var.get() != "None":
                bold_terms.append(self.radic_symptom_var.get())
            if self.radic_location_var.get() != "(select)":
                bold_terms.append(self.radic_location_var.get())

            # muscles
            bold_terms.extend([m for m, v in self.muscle_vars.items() if v.get()])

            # pain scale
            if self.pain_scale_var.get() != "None":
                bold_terms.append(self.pain_scale_var.get())

            self._bold_phrases(bold_terms)



    def reset(self):
        self._loading_block = True
        try:
            self.region_var.set("(none)")
            self.desc1_var.set(PAIN_DESCRIPTORS[0])
            self.desc2_var.set("(none)")
            self.radic_symptom_var.set("None")
            self.radic_location_var.set("(select)")
            self.pain_scale_var.set("None")
            self.narrative_text.delete("1.0", tk.END)
            self.region_label_var.set("")
            self._rebuild_muscles()
        finally:
            self._loading_block = False

    def _auto_resize_text(self, event=None):
        """
        Automatically resize the narrative Text widget height
        based on number of lines, within sane bounds.
        """
        MIN_LINES = 10
        MAX_LINES = 18

        # Count visible lines
        lines = int(self.narrative_text.index("end-1c").split(".")[0])
        lines = max(MIN_LINES, min(lines, MAX_LINES))

        self.narrative_text.configure(height=lines)


    def to_dict(self) -> dict:
        selected_muscles = [m for m, v in self.muscle_vars.items() if v.get()]
        return {
            "region": self.region_var.get(),
            "desc1": self.desc1_var.get(),
            "desc2": self.desc2_var.get(),
            "radic_symptom": self.radic_symptom_var.get(),
            "radic_location": self.radic_location_var.get(),
            "pain_scale": self.pain_scale_var.get(),  # ✅ SAVE IT
            "muscles": selected_muscles,
            "narrative": self.get_narrative(),        # ✅ LOCKED TEXT
        }

    def from_dict(self, data: dict):
        """
        IMPORTANT:
        - Do NOT call update_narrative() here.
        - Load the saved narrative EXACTLY as-is to avoid re-randomizing on load.
        """
        self._loading_from_file = True
        try:
            self.region_var.set(data.get("region", "(none)"))
            self.desc1_var.set(data.get("desc1", PAIN_DESCRIPTORS[0]))
            self.desc2_var.set(data.get("desc2", "(none)"))
            self.radic_symptom_var.set(data.get("radic_symptom", "None"))
            self.radic_location_var.set(data.get("radic_location", "(select)"))

            # ✅ THIS WAS MISSING
            self.pain_scale_var.set(data.get("pain_scale", "None"))

            self._rebuild_muscles()
            saved = set(data.get("muscles") or [])
            for m, v in self.muscle_vars.items():
                v.set(m in saved)

            # Load narrative verbatim
            self.narrative_text.delete("1.0", tk.END)
            self.narrative_text.insert(tk.END, data.get("narrative", ""))

        finally:
            self._loading_from_file = False

        # ✅ Only auto-generate if narrative is empty
        if not self.get_narrative():
            self.update_narrative(overwrite_if_auto=True)




