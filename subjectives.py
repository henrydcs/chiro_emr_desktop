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

    def __init__(self, parent, on_change_callback, app, max_blocks: int = 10):
        super().__init__(parent)
        self.app = app
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
        self._sync_therapy_visibility()
        self._go_back_to_subjectives()

    
    def _open_therapy_modalities(self):
        try:
            self.app.plan_page.open_therapy_modalities_from_therapy_only()
        except Exception as e:
            messagebox.showerror("Therapy Modalities", f"Could not open Therapy Modalities.\n\n{e}")

    # Subjective Body Regions
    def clear_all_body_regions(self):
        """
        Helper function: resets Body region to "(none)" for ALL existing subjective blocks.

        Affects ONLY:
        - region_var for each block

        Does NOT modify:
        - pain scale
        - descriptors
        - notes
        - other subjective fields
        """

        try:
            # If you store blocks in a list (typical pattern)
            for block in getattr(self, "blocks", []):
                try:
                    if hasattr(block, "region_var"):
                        block.region_var.set("(none)")
                except Exception:
                    pass

        except Exception:
            pass


    def _wire_block_therapy_hooks(self, block):
        # Make therapy visibility update immediately whenever the radio changes
        if getattr(block, "_therapy_hooked", False):
            return
        block._therapy_hooked = True

        vv = getattr(block, "view_var", None)
        if vv is not None:
            vv.trace_add("write", lambda *_: self._sync_therapy_visibility())   
    
    
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

    
    def _show_therapy(self):
        if getattr(self, "_therapy_visible", False):
            return
        # show under nav, above content
        self._therapy_container.pack(fill="x", after=self.nav)
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
        vv = getattr(b, "view_var", None)
        mode = (vv.get() if vv else "") or ""
        mode = mode.strip().lower()

        # ✅ works whether value is "therapy", "therapy only", "therapy_only", etc.
        if "therapy" in mode:
            self._show_therapy()
        else:
            self._hide_therapy()


    def _on_block_mode_change(self, block_index: int, mode: str):
        # No "current block" logic anymore. Any block can turn therapy on/off.
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
            f"The patient states being primarily concerned with symptoms located in the following area(s): "
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

    def get_live_preview_runs(self) -> list[tuple[str, str | None]]:
        """
        Returns runs for Live Preview: therapy paragraph + auto-generated content
        from each block + narrative text box. Format: [(chunk, tag), ...] with
        tag "H_BOLD" for headings. Mirrors PDF structure: one line of space
        between last subjectives and narrative text.
        """
        runs = []
        therapy = self.build_therapy_paragraph().strip()

        # Check if any block has auto content (mirrors PDF: region blocks)
        has_block_content = any(
            (b.get_auto_generated_text() or "").strip() for b in self.blocks
        )
        has_block_narrative = any((b.get_narrative() or "").strip() for b in self.blocks)

        # Show Subjectives heading if we have ANY subjectives content (mirrors PDF)
        has_any_subjectives = bool(therapy or has_block_content or has_block_narrative)
        if has_any_subjectives:
            runs.append(("SUBJECTIVES\n", "H_BOLD"))
            runs.append(("\n", None))

        if therapy:
            runs.append((therapy + "\n\n", None))

        orphan_narratives = []
        for b in self.blocks:
            auto = (b.get_auto_generated_text() or "").strip()
            user_narr = (b.get_narrative() or "").strip()
            if auto:
                region_code = b.region_var.get()
                label = REGION_LABELS.get(region_code, "")
                if label:
                    runs.append((label + "\n", "H_BOLD"))
                    runs.append(("\n", None))
                runs.append((auto + "\n\n", None))
                # This block's textbox prints as last sentence(s) of this body region
                if user_narr:
                    runs.append((user_narr + "\n\n", None))
            elif user_narr:
                # Block has narrative but no auto (e.g. region is (none))
                orphan_narratives.append(user_narr)

        if orphan_narratives:
            runs.append(("\n", None))
            runs.append(("\n\n".join(orphan_narratives) + "\n\n", None))

        return runs

    
    def _confirm_reset(self):
        ok = messagebox.askyesno(
            "Reset Subjectives",
            "This will ERASE all Subjectives blocks on screen (it does not delete any saved files).\n\n"
            "Are you sure you want to continue?"
        )
        if ok:
            self.reset()

    def _go_therapy_only_home(self):
        """Switch to Therapy Only Home view (hides subjectives)."""
        self._therapy_only_home_frame.tkraise()

    def _go_back_to_subjectives(self):
        """Switch back to regular Subjectives view."""
        self._subjectives_frame.tkraise()
    
    # ---------- UI ----------
    def _build_ui(self):
        # Stack for tkraise: subjectives view vs therapy-only-home view
        self._stack = ttk.Frame(self)
        self._stack.pack(fill="both", expand=True)
        self._stack.rowconfigure(0, weight=1)
        self._stack.columnconfigure(0, weight=1)

        self._subjectives_frame = ttk.Frame(self._stack)
        self._subjectives_frame.grid(row=0, column=0, sticky="nsew")
        self._therapy_only_home_frame = ttk.Frame(self._stack)
        self._therapy_only_home_frame.grid(row=0, column=0, sticky="nsew")

        # --- All content below goes inside _subjectives_frame ---
        _host = self._subjectives_frame

        # Header row: Add, Reset
        top = ttk.Frame(_host)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Button(top, text="Add Block", command=self._add_block).pack(side="left")
        ttk.Button(top, text="Reset All Subjectives", command=self._confirm_reset).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="New Therapy Only Home", command=self._go_therapy_only_home).pack(side="left", padx=(8, 0))

        # Row of block navigation buttons
        self.nav = ttk.Frame(_host)
        self.nav.pack(fill="x", padx=10, pady=(0, 10))
        
        # --- Therapy Only section (GLOBAL, independent of blocks) ---
        self._therapy_container = ttk.Frame(_host)
        # start hidden (we'll pack it only when needed)
        self._therapy_visible = False

        self._therapy_frame = ttk.LabelFrame(self._therapy_container, text="Therapy Only")
        self._therapy_frame.pack(fill="x", padx=10, pady=(0, 10))

        hdr = ttk.Frame(self._therapy_frame)
        hdr.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ttk.Label(hdr, text="Select affected areas (first checked = main concern):").grid(row=0, column=0, sticky="w")
        ttk.Button(hdr, text="Reset Therapy", command=self._therapy_reset).grid(row=0, column=1, sticky="e")
        ttk.Button(hdr, text="Open Therapy Modalities", command=self._open_therapy_modalities).grid(row=0, column=2, sticky="e")

        cols = 5
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

        # Container where blocks live (stacked with grid, like your main app pages)
        self.content = ttk.Frame(_host)
        self.content.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        # Therapy Only Home area: minimal content + back button
        # Therapy Only Home area: Back button + Therapy Only block (same logic as radio view)
        therapy_home_top = ttk.Frame(self._therapy_only_home_frame)
        therapy_home_top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(
            therapy_home_top,
            text="Back to Subjectives",
            command=self._go_back_to_subjectives,
        ).pack(side="left")

        # --- Therapy Only block (mirrors _therapy_frame, uses same therapy_vars) ---
        self._therapy_only_home_frame_inner = ttk.LabelFrame(
            self._therapy_only_home_frame, text="Therapy Only"
        )
        self._therapy_only_home_frame_inner.pack(fill="x", padx=10, pady=(0, 10))

        hdr_home = ttk.Frame(self._therapy_only_home_frame_inner)
        hdr_home.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 4))
        hdr_home.grid_columnconfigure(0, weight=1)

        ttk.Label(hdr_home, text="Select affected areas (first checked = main concern):").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(hdr_home, text="Reset Therapy", command=self._therapy_reset).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Button(hdr_home, text="Open Therapy Modalities", command=self._open_therapy_modalities).grid(
            row=0, column=2, sticky="e"
        )

        cols_home = 5
        start_row_home = 1
        for i, name in enumerate(THERAPY_BODY_PARTS):
            r = start_row_home + (i // cols_home)
            c = i % cols_home
            ttk.Checkbutton(
                self._therapy_only_home_frame_inner,
                text=name,
                variable=self.therapy_vars[name],
            ).grid(row=r, column=c, sticky="w", padx=8, pady=2)

        for c in range(cols_home):
            self._therapy_only_home_frame_inner.grid_columnconfigure(c, weight=1)

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
        self._wire_block_therapy_hooks(block)         

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

    def focus_region_label(self, region_label: str) -> None:
        """
        Given a REGION_LABELS value from the Live Preview (e.g. "Cervical Spine"),
        find the first Subjectives block whose region label matches, show it,
        and switch to the Pain Descriptor view.
        """
        from config import REGION_LABELS  # local import to avoid circulars

        wanted = (region_label or "").strip()
        if not wanted:
            return

        for idx, block in enumerate(self.blocks):
            code = (block.region_var.get() or "").strip()
            label = (REGION_LABELS.get(code, "") or "").strip()
            if label == wanted:
                self.show_block(idx)
                if hasattr(block, "view_var"):
                    block.view_var.set("descriptor")
                    block._apply_view()
                return

    def focus_points_to(self, line_text: str = "") -> None:
        """
        Live Preview: user clicked a line containing 'points to'.
        Find the block whose muscles produced this sentence and switch
        that block's view to 'Patient Points To'.
        """
        from config import REGION_LABELS

        target_idx = None

        if line_text:
            for idx, block in enumerate(self.blocks):
                muscles = block.to_dict().get("muscles") or []
                if not muscles:
                    continue
                for m in muscles:
                    if m.lower() in line_text.lower():
                        target_idx = idx
                        break
                if target_idx is not None:
                    break

        if target_idx is None and self.blocks:
            target_idx = self.current_block_index

        if target_idx is not None and 0 <= target_idx < len(self.blocks):
            self.show_block(target_idx)
            blk = self.blocks[target_idx]
            if hasattr(blk, "view_var"):
                blk.view_var.set("points")
                blk._apply_view()

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
            block = DescriptorBlock(
                self.content,
                i,
                self.on_change_callback,
                on_mode_change=self._on_block_mode_change,   # keep if you want, but not required now
            )
            block.frame.grid(row=0, column=0, sticky="nsew")
            block.from_dict(bd or {})

            self._wire_block_therapy_hooks(block)  # ✅ MUST be inside loop

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
        
        self._refresh_nav_buttons()
        self._sync_therapy_visibility()   # ✅ force correct show/hide on load
        self.on_change_callback()
