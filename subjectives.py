# subjectives.py
import tkinter as tk
from tkinter import ttk, messagebox

from ui_blocks import DescriptorBlock
from config import REGION_LABELS


class SubjectivesPage(ttk.Frame):
    """
    Objectives-style Subjectives:
    - No scrolling canvas
    - Multiple blocks exist, but only ONE is shown at a time
    - Top row has buttons: Block 1 C/S, Block 2 T/S, etc
    - Buttons auto-update when each block's region changes
    """

    def __init__(self, parent, on_change_callback, max_blocks: int = 5):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self.max_blocks = max_blocks

        self.blocks: list[DescriptorBlock] = []
        self.block_buttons: list[ttk.Button] = []
        self.current_block_index = 0  # 0-based

        self._build_ui()
        self._add_block()  # start with block 1

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

    # ---------- Add / Reset ----------
    def _add_block(self):
        if len(self.blocks) >= self.max_blocks:
            return

        idx_0 = len(self.blocks)
        block_num = idx_0 + 1

        block = DescriptorBlock(self.content, block_num, self.on_change_callback)
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

        self._add_block()
        self.on_change_callback()

    def has_content(self) -> bool:
        for b in self.blocks:
            if b.is_active() and b.get_narrative().strip():
                return True
        return False

    def to_dict(self) -> dict:
        return {"blocks": [b.to_dict() for b in self.blocks]}

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

        self._refresh_nav_buttons()
        self.on_change_callback()
