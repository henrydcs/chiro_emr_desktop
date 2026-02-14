# subjectives.py
import tkinter as tk
from tkinter import ttk, messagebox

from ui_blocks import DescriptorBlock
from config import REGION_LABELS

THERAPY_BODY_PARTS = [
    "Neck", "Upper Back", "Mid-Back", "Low Back", "Pelvic Area",
    "Left Hip", "Right Hip", "Left Buttock", "Right Buttock",
    "Left Thigh", "Right Thigh", "Left Knee", "Right Knee",
    "Left Ankle", "Right Ankle", "Left Foot", "Right Foot",
    "Left Toes", "Right Toes",
    "Left Shoulder", "Right Shoulder",
    "Left Arm", "Right Arm",
    "Left Elbow", "Right Elbow",
    "Left Forearm", "Right Forearm",
    "Left Wrist", "Right Wrist",
    "Left Hand", "Right Hand",
    "Left Fingers", "Right Fingers",
]

def join_with_and(items: list[str]) -> str:
    items = [x for x in items if x]
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"



class SubjectivesPage(ttk.Frame):
    """
    Objectives-style Subjectives:
    - No scrolling canvas
    - Multiple blocks exist, but only ONE is shown at a time
    - Top row has buttons: Block 1 C/S, Block 2 T/S, etc
    - Buttons auto-update when each block's region changes
    """

    def __init__(self, parent, on_change_callback, max_blocks: int = 10):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self.max_blocks = max_blocks        

        self.blocks: list[DescriptorBlock] = []
        self.block_buttons: list[ttk.Button] = []
        self.current_block_index = 0  # 0-based

        self.therapy_vars = {name: tk.BooleanVar(value=False) for name in THERAPY_BODY_PARTS}

        self._therapy_main: str | None = None

        self._therapy_order: list[str] = []      # first item = main concern
        self._therapy_loading = False            # guard while programmatically resetting/loading



        self._build_ui()
        self._add_block()  # start with block 1

    
    def _on_therapy_var_change(self, name: str):
        if getattr(self, "_therapy_loading", False):
            return

        v = self.therapy_vars[name].get()

        if v:
            # checked -> append to order if new
            if name not in self._therapy_order:
                self._therapy_order.append(name)
        else:
            # unchecked -> remove from order if present
            if name in self._therapy_order:
                self._therapy_order.remove(name)

        # If no selections -> fresh state
        if not self._therapy_order:
            self._therapy_main = None
        else:
            self._therapy_main = self._therapy_order[0]  # FIRST checked since last empty

        if callable(self.on_change_callback):
            self.on_change_callback()


    def _therapy_reset(self):
        self._therapy_loading = True
        try:
            for v in self.therapy_vars.values():
                v.set(False)
            self._therapy_order.clear()
            self._therapy_main = None
        finally:
            self._therapy_loading = False

        if callable(self.on_change_callback):
            self.on_change_callback()


    # def _on_therapy_toggle(self, name):
    #     # Current checked items (in your fixed order)
    #     selected = [p for p in THERAPY_BODY_PARTS if self.therapy_vars[p].get()]

    #     # If everything is empty -> fresh state
    #     if not selected:
    #         self._therapy_main = None
    #         if callable(self.on_change_callback):
    #             self.on_change_callback()
    #         return

    #     # If we have a main but it's no longer checked, clear it
    #     if self._therapy_main and self._therapy_main not in selected:
    #         self._therapy_main = None

    #     # If no main yet, set it to the FIRST checked (fixed order)
    #     if self._therapy_main is None:
    #         self._therapy_main = selected[0]

    #     if callable(self.on_change_callback):
    #         self.on_change_callback()



    
    def _show_therapy(self):
        if getattr(self, "_therapy_visible", False):
            return
        # Put Therapy Only BELOW the block UI (so the radio buttons stay on top)
        self._therapy_container.pack(fill="x", padx=10, pady=(0, 10), after=self.content)
        self._therapy_visible = True

    def _hide_therapy(self):
        if not getattr(self, "_therapy_visible", False):
            return
        self._therapy_container.pack_forget()
        self._therapy_visible = False


    def _sync_therapy_visibility(self):
        if not self.blocks:
            self._hide_therapy()
            return

        b = self.blocks[self.current_block_index]
        mode = getattr(b, "view_var", None).get() if getattr(b, "view_var", None) else "descriptor"

        if (mode or "").strip().lower() == "therapy":
            self._show_therapy()
        else:
            self._hide_therapy()
    
    def _on_block_mode_change(self, block_index: int, mode: str):
        # Only react if the change came from the currently shown block
        current_block_num = self.current_block_index + 1  # because your DescriptorBlock stores 1-based
        if block_index != current_block_num:
            return
        
        self._sync_therapy_visibility()    

    def _therapy_selected_ordered(self) -> list[str]:
        out = []
        for name in THERAPY_BODY_PARTS:
            if self.therapy_vars[name].get():
                out.append(name)
        return out

    def build_therapy_paragraph(self) -> str:
        selected = [name for name in THERAPY_BODY_PARTS if self.therapy_vars[name].get()]

        # if nothing checked -> clear main and return nothing
        if not selected:
            self._therapy_main = None
            return ""

        # Always recompute main from CURRENT state (ignore old stored value)
        main = selected[0]
        self._therapy_main = main   # keep internal state consistent

        others = selected[1:]

        s1 = (
            "The patient states that today the worst symptoms are located in the following area: "
            f"{main} region."
        )

        if not others:
            return s1

        s2 = f"The patient also feels symptoms in the {join_with_and(others)}."
        return s1 + " " + s2


    def get_narrative(self) -> str:
        """
        Combined Subjectives narrative:
        1) Therapy paragraph FIRST (if any)
        2) Then block narratives (existing logic unchanged)
        """
        parts = []

        therapy = self.build_therapy_paragraph().strip()
        if therapy:
            parts.append(therapy)

        for b in self.blocks:
            txt = (b.get_narrative() or "").strip()
            if txt:
                parts.append(txt)

        return "\n\n".join(parts).strip()

    
    def _confirm_reset(self):
        ok = messagebox.askyesno(
            "Reset Subjectives",
            "This will ERASE all Subjectives blocks on screen (it does not delete any saved files).\n\n"
            "Are you sure you want to continue?"
        )
        if ok:
            self.reset()   
    
    # ---------- UI ----------
    def _build_ui(self):
        # Header row: Add, Reset
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Button(top, text="Add Block", command=self._add_block).pack(side="left")
        ttk.Button(top, text="Reset Subjectives", command=self._confirm_reset).pack(side="left", padx=(8, 0))


        # Row of block navigation buttons
        self.nav = ttk.Frame(self)
        self.nav.pack(fill="x", padx=10, pady=(0, 10))

        # --- Therapy Only section (GLOBAL, independent of blocks) ---
        self._therapy_container = ttk.Frame(self)
        #self._therapy_container.pack(fill="x", padx=10, pady=(0, 10))

        self._therapy_blank = ttk.Frame(self._therapy_container)
        self._therapy_frame = ttk.LabelFrame(self._therapy_container, text="Therapy Only")
        hdr = ttk.Frame(self._therapy_frame)
        hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ttk.Label(hdr, text="Select affected areas (first checked = main concern):").grid(row=0, column=0, sticky="w")
        ttk.Button(hdr, text="Reset Therapy", command=self._therapy_reset).grid(row=0, column=1, sticky="e")


        for f in (self._therapy_blank, self._therapy_frame):
            f.grid(row=0, column=0, sticky="ew")
        self._therapy_container.grid_columnconfigure(0, weight=1)

        cols = 3
        start_row = 1

        for name, var in self.therapy_vars.items():
            var.trace_add("write", lambda *_ , n=name: self._on_therapy_var_change(n))


        for i, name in enumerate(THERAPY_BODY_PARTS):
            r = start_row + (i // cols)
            c = i % cols
            ttk.Checkbutton(
                self._therapy_frame,
                text=name,
                variable=self.therapy_vars[name],
            ).grid(row=r, column=c, sticky="w", padx=8, pady=2)


        for c in range(cols):
            self._therapy_frame.grid_columnconfigure(c, weight=1)

        # Start hidden
        self._therapy_visible = False


        # Start hidden until Therapy Only is selected
        self._therapy_blank.tkraise()


        # Container where blocks live (stacked with grid, like your main app pages)
        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

    # ---------- Block label helpers ----------
    def _region_short(self, region_code: str) -> str:
        """
        Turn your region code into a short label:
          C/S, T/S, L/S, RUE, LUE, RLE, LLE, etc.
        Falls back to the raw code if unknown.
        """
        code = (region_code or "").strip()

        mapping = {
            "C/S": "C/S",
            "T/S": "T/S",
            "L/S": "L/S",
            "RUE": "RUE",
            "LUE": "LUE",
            "RLE": "RLE",
            "LLE": "LLE",
        }
        if code in mapping:
            return mapping[code]

        # If your REGION_OPTIONS use codes like "CS", "TS", etc, normalize here:
        normalize = {
            "CS": "C/S",
            "TS": "T/S",
            "LS": "L/S",
        }
        if code in normalize:
            return normalize[code]

        # If it’s "(none)" or unknown, show blank marker
        if code in ("(none)", "", "(select)"):
            return "--"

        return code

    def _button_text_for_block(self, idx_0: int) -> str:
        block_num = idx_0 + 1
        region_code = self.blocks[idx_0].region_var.get() if idx_0 < len(self.blocks) else "(none)"
        short = self._region_short(region_code)
        return f"Block {block_num} {short}"

    def _refresh_nav_buttons(self):
        for i, btn in enumerate(self.block_buttons):
            btn.configure(text=self._button_text_for_block(i))
            # Disable the active one (nice UX)
            if i == self.current_block_index:
                btn.state(["disabled"])
            else:
                btn.state(["!disabled"])

    # ---------- Navigation ----------
    def show_block(self, idx_0: int):
        if idx_0 < 0 or idx_0 >= len(self.blocks):
            return

        self.current_block_index = idx_0
        self.blocks[idx_0].frame.tkraise()
        self._refresh_nav_buttons()
        self._sync_therapy_visibility()


    # ---------- Add / Reset ----------
    def _add_block(self):
        if len(self.blocks) >= self.max_blocks:
            return

        idx_0 = len(self.blocks)
        block_num = idx_0 + 1

        block = DescriptorBlock(
            self.content,
            block_num,
            self.on_change_callback,
            on_mode_change=self._on_block_mode_change
        )


        block.frame.grid(row=0, column=0, sticky="nsew")  # stack all blocks in same cell

        self.blocks.append(block)

        # Create nav button for this block
        btn = ttk.Button(self.nav, text=f"Block {block_num} --", command=lambda i=idx_0: self.show_block(i))
        btn.pack(side="left", padx=(0, 6))
        self.block_buttons.append(btn)

        # Whenever region changes, update button labels
        block.region_var.trace_add("write", lambda *_: self._refresh_nav_buttons())

        # Show the newest block immediately
        self.show_block(idx_0)

        self._sync_therapy_visibility()


        # Trigger autosave scheduling
        self.on_change_callback()

    # -------- Public API --------
    def reset(self):
        # destroy all blocks + buttons
        for b in self.blocks:
            b.frame.destroy()
        self.blocks.clear()

        for btn in self.block_buttons:
            btn.destroy()
        self.block_buttons.clear()

        self.current_block_index = 0

        # ---------- IMPORTANT: reset Therapy Only ----------
        self._therapy_loading = True
        try:
            for v in self.therapy_vars.values():
                v.set(False)
            self._therapy_order.clear()
            self._therapy_main = None
        finally:
            self._therapy_loading = False

        self._therapy_main = None   # THIS is what fixes your ordering reset

        self._add_block()
        self.on_change_callback()

    def has_content(self) -> bool:
        # therapy counts as content (prevents dash when dropdown empty)
        if self._therapy_selected_ordered():
            return True

        for b in self.blocks:
            if b.is_active() and b.get_narrative().strip():
                return True
        return False


    def to_dict(self) -> dict:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "therapy_only": {k: v.get() for k, v in self.therapy_vars.items()},
            "therapy_main": self._therapy_main,
            "therapy_order": list(self._therapy_order),
        }
        


    def from_dict(self, data: dict):
        blocks = (data or {}).get("blocks") or []

        # clear existing
        for b in self.blocks:
            b.frame.destroy()
        self.blocks.clear()

        for btn in self.block_buttons:
            btn.destroy()
        self.block_buttons.clear()

        self.current_block_index = 0

        # rebuild from saved
        for i, bd in enumerate(blocks, start=1):
            block = DescriptorBlock(self.content, i, self.on_change_callback)
            block.frame.grid(row=0, column=0, sticky="nsew")
            block.from_dict(bd or {})
            self.blocks.append(block)

            idx_0 = i - 1
            btn = ttk.Button(self.nav, text=f"Block {i} --", command=lambda j=idx_0: self.show_block(j))
            btn.pack(side="left", padx=(0, 6))
            self.block_buttons.append(btn)

            block.region_var.trace_add("write", lambda *_: self._refresh_nav_buttons())

        if not self.blocks:
            self._add_block()
        else:
            self.show_block(0)

        therapy_state = (data or {}).get("therapy_only") or {}

        self._therapy_loading = True
        try:
            any_on = False
            for k, var in self.therapy_vars.items():
                val = bool(therapy_state.get(k, False))
                var.set(val)
                any_on = any_on or val

            # Rebuild order deterministically:
            # if you saved therapy_order, use it; else fall back to fixed list order
            saved_order = (data or {}).get("therapy_order") or []
            if isinstance(saved_order, list) and saved_order:
                self._therapy_order = [x for x in saved_order if x in THERAPY_BODY_PARTS and self.therapy_vars[x].get()]
            else:
                self._therapy_order = [x for x in THERAPY_BODY_PARTS if self.therapy_vars[x].get()]

            self._therapy_main = self._therapy_order[0] if self._therapy_order else None

        finally:
            self._therapy_loading = False

        # show/hide therapy UI
        if any_on:
            self._therapy_frame.tkraise()
        else:
            self._therapy_blank.tkraise()


        

        self._refresh_nav_buttons()
        self.on_change_callback()
