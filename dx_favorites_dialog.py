# dx_favorites_dialog.py
"""Search Dx Favorites — named favorite blocks with CMS + list search."""
from __future__ import annotations

import copy
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog, ttk

from dx_favorites_storage import list_blocks, save_blocks
from icd10_lookup import Icd10Entry, display_for_entry, search_icd10


def _display(label: str, icd10: str) -> str:
    label = (label or "").strip()
    icd10 = (icd10 or "").strip()
    return f"{label} — {icd10}" if icd10 else label


def _matches_query(label: str, code: str, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    blob = f"{label} {code}".lower()
    return all(w in blob for w in q.split())


class _BlockPanel(ttk.Frame):
    """One favorite block tab: CMS search, list filter, favorites list."""

    def __init__(self, parent, block: dict, on_changed):
        super().__init__(parent, padding=8)
        self.block = block
        self.on_changed = on_changed

        self.cms_var = tk.StringVar(value="")
        self.filter_var = tk.StringVar(value="")
        self._cms_hits: list[Icd10Entry] = []
        self._visible_favs: list[tuple[str, str]] = []

        ttk.Label(
            self,
            text="Search CMS to add a diagnosis to this favorite block:",
        ).pack(anchor="w")
        cms_row = ttk.Frame(self)
        cms_row.pack(fill="x", pady=(4, 2))
        ttk.Label(cms_row, text="CMS:").pack(side="left")
        self.cms_entry = ttk.Entry(cms_row, textvariable=self.cms_var)
        self.cms_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        cms_lb_fr = ttk.Frame(self)
        cms_lb_fr.pack(fill="x", pady=(0, 8))
        self.cms_lb = tk.Listbox(
            cms_lb_fr,
            height=5,
            exportselection=False,
            activestyle="dotbox",
            font=("Segoe UI", 9),
        )
        cms_sb = ttk.Scrollbar(cms_lb_fr, orient="vertical", command=self.cms_lb.yview)
        self.cms_lb.configure(yscrollcommand=cms_sb.set)
        self.cms_lb.pack(side="left", fill="x", expand=True)
        cms_sb.pack(side="right", fill="y")

        ttk.Label(
            self,
            text="Search favorites in this block:",
        ).pack(anchor="w", pady=(4, 0))
        filter_row = ttk.Frame(self)
        filter_row.pack(fill="x", pady=(4, 2))
        ttk.Label(filter_row, text="Filter:").pack(side="left")
        self.filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var)
        self.filter_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

        fav_fr = ttk.LabelFrame(self, text="Favorites in this block", padding=6)
        fav_fr.pack(fill="both", expand=True, pady=(6, 0))

        fav_lb_fr = ttk.Frame(fav_fr)
        fav_lb_fr.pack(fill="both", expand=True)

        self.fav_lb = tk.Listbox(
            fav_lb_fr,
            height=10,
            exportselection=False,
            activestyle="dotbox",
            font=("Segoe UI", 10),
        )
        fav_sb = ttk.Scrollbar(fav_lb_fr, orient="vertical", command=self.fav_lb.yview)
        self.fav_lb.configure(yscrollcommand=fav_sb.set)
        self.fav_lb.pack(side="left", fill="both", expand=True)
        fav_sb.pack(side="right", fill="y")

        btn_row = ttk.Frame(fav_fr)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Edit label…", command=self._edit_label).pack(side="left")
        ttk.Button(btn_row, text="Remove", command=self._remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="↑", width=3, command=lambda: self._move_selected(-1)).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(btn_row, text="↓", width=3, command=lambda: self._move_selected(1)).pack(
            side="left", padx=(4, 0)
        )

        self.cms_var.trace_add("write", lambda *_: self._refresh_cms_results())
        self.filter_var.trace_add("write", lambda *_: self._refresh_fav_list())
        self.cms_lb.bind("<Double-Button-1>", lambda _e: self._add_selected_cms())
        self.cms_lb.bind("<Return>", lambda _e: self._add_selected_cms())
        self.fav_lb.bind("<Double-Button-1>", lambda _e: self._select_pick())
        self.fav_lb.bind("<Return>", lambda _e: self._select_pick())
        self.on_select_pick = None

        self._refresh_fav_list()

    def _select_pick(self) -> None:
        if callable(self.on_select_pick):
            self.on_select_pick()

    def _notify_changed(self) -> None:
        if callable(self.on_changed):
            self.on_changed()

    def _favorites(self) -> list[tuple[str, str]]:
        return self.block.setdefault("favorites", [])

    def _refresh_cms_results(self) -> None:
        self.cms_lb.delete(0, tk.END)
        self._cms_hits = search_icd10(self.cms_var.get(), limit=40)
        for ent in self._cms_hits:
            self.cms_lb.insert(tk.END, display_for_entry(ent))

    def _refresh_fav_list(self, *, select_display: str | None = None) -> None:
        self.fav_lb.delete(0, tk.END)
        self._visible_favs = []
        q = self.filter_var.get()
        select_idx = None
        for label, code in self._favorites():
            if not _matches_query(label, code, q):
                continue
            disp = _display(label, code)
            self._visible_favs.append((label, code))
            self.fav_lb.insert(tk.END, disp)
            if select_display and disp == select_display:
                select_idx = len(self._visible_favs) - 1
        if self._visible_favs:
            idx = select_idx if select_idx is not None else 0
            self.fav_lb.selection_set(idx)
            self.fav_lb.activate(idx)
            self.fav_lb.see(idx)

    def _selected_fav(self) -> tuple[str, str] | None:
        sel = self.fav_lb.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._visible_favs):
            return None
        return self._visible_favs[idx]

    def _selected_cms(self) -> Icd10Entry | None:
        sel = self.cms_lb.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._cms_hits):
            return None
        return self._cms_hits[idx]

    def _favorite_in_block(self, icd10: str) -> bool:
        code_key = icd10.strip().lower()
        for _, code in self._favorites():
            if code.strip().lower() == code_key:
                return True
        return False

    def _add_selected_cms(self) -> None:
        ent = self._selected_cms()
        if ent is None:
            q = self.cms_var.get().strip()
            if q:
                hits = search_icd10(q, limit=1)
                ent = hits[0] if hits else None
        if ent is None:
            messagebox.showinfo(
                "Search Dx Favorites",
                "Search CMS and select a diagnosis to add.",
                parent=self,
            )
            return
        if self._favorite_in_block(ent.code):
            self._refresh_fav_list(select_display=_display(ent.description, ent.code))
            return
        self._favorites().append((ent.description, ent.code))
        self._notify_changed()
        self._refresh_fav_list(select_display=_display(ent.description, ent.code))

    def _remove_selected(self) -> None:
        row = self._selected_fav()
        if row is None:
            messagebox.showinfo(
                "Search Dx Favorites",
                "Select a favorite to remove.",
                parent=self,
            )
            return
        label, code = row
        if not messagebox.askyesno(
            "Remove favorite",
            f"Remove from this favorite block?\n\n{_display(label, code)}",
            parent=self,
        ):
            return
        favs = self._favorites()
        for i, (lbl, c) in enumerate(favs):
            if lbl == label and c == code:
                favs.pop(i)
                break
        self._notify_changed()
        self._refresh_fav_list()

    def _move_selected(self, delta: int) -> None:
        row = self._selected_fav()
        if row is None:
            return
        label, code = row
        favs = self._favorites()
        idx = next((i for i, pair in enumerate(favs) if pair == (label, code)), None)
        if idx is None:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(favs):
            return
        favs[idx], favs[new_idx] = favs[new_idx], favs[idx]
        self._notify_changed()
        self._refresh_fav_list(select_display=_display(label, code))

    def _edit_label(self) -> None:
        row = self._selected_fav()
        if row is None:
            messagebox.showinfo(
                "Search Dx Favorites",
                "Select a favorite to edit.",
                parent=self,
            )
            return
        label, code = row
        new_label = simpledialog.askstring(
            "Edit label",
            f"Edit description for {code}:",
            initialvalue=label,
            parent=self,
        )
        if new_label is None:
            return
        new_label = new_label.strip()
        if not new_label or new_label == label:
            return
        favs = self._favorites()
        for i, (lbl, c) in enumerate(favs):
            if lbl == label and c == code:
                favs[i] = (new_label, code)
                break
        self._notify_changed()
        self._refresh_fav_list(select_display=_display(new_label, code))

    def get_selected_pick(self) -> tuple[str, str] | None:
        return self._selected_fav()


def open_search_dx_favorites_dialog(parent, *, on_saved=None) -> tuple[str, str] | None:
    """
    Pick a favorite from named favorite blocks for the active Dx block.
    Returns (label, icd10) when selected, else None.
    """
    blocks: list[dict] = copy.deepcopy(list_blocks())
    changed = False
    picked_result: list[tuple[str, str] | None] = [None]
    panels: dict[str, _BlockPanel] = {}

    dlg = tk.Toplevel(parent)
    dlg.title("Search Dx Favorites")
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    dlg.resizable(True, True)
    dlg.minsize(920, 680)
    dlg.geometry("980x720")

    wrap = ttk.Frame(dlg, padding=12)
    wrap.pack(fill="both", expand=True)

    ttk.Label(
        wrap,
        text="Choose a favorite block, search CMS to add favorites, or pick a diagnosis for this Dx block.",
        wraplength=900,
    ).pack(anchor="w", pady=(0, 8))

    toolbar = ttk.Frame(wrap)
    toolbar.pack(fill="x", pady=(0, 8))

    notebook = ttk.Notebook(wrap)
    notebook.pack(fill="both", expand=True)

    footer = ttk.Frame(wrap)
    footer.pack(fill="x", pady=(12, 0))

    def _mark_changed() -> None:
        nonlocal changed
        changed = True

    def _persist_if_needed() -> None:
        if changed:
            save_blocks(blocks)
            if callable(on_saved):
                on_saved()

    def _current_block_index() -> int | None:
        try:
            return notebook.index(notebook.select())
        except tk.TclError:
            return None

    def _current_block() -> dict | None:
        idx = _current_block_index()
        if idx is None or idx < 0 or idx >= len(blocks):
            return None
        return blocks[idx]

    def _rebuild_notebook(*, select_block_id: str | None = None) -> None:
        nonlocal panels
        for tab_id in notebook.tabs():
            notebook.forget(tab_id)
        panels = {}
        for block in blocks:
            panel = _BlockPanel(notebook, block, on_changed=_mark_changed)
            panel.on_select_pick = _select_favorite
            panels[block["id"]] = panel
            notebook.add(panel, text=block.get("name") or "Favorites")
        if select_block_id:
            for i, block in enumerate(blocks):
                if block.get("id") == select_block_id:
                    notebook.select(i)
                    break
        elif blocks:
            notebook.select(0)

    def _add_block():
        name = simpledialog.askstring(
            "Add Favorite Block",
            "Name for this favorite block:",
            initialvalue="New Favorites",
            parent=dlg,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning("Add Favorite Block", "Name cannot be empty.", parent=dlg)
            return
        block_id = uuid.uuid4().hex[:10]
        blocks.append({"id": block_id, "name": name, "favorites": []})
        _mark_changed()
        _rebuild_notebook(select_block_id=block_id)

    def _rename_block():
        block = _current_block()
        if block is None:
            messagebox.showinfo("Rename Favorite Block", "Add a favorite block first.", parent=dlg)
            return
        new_name = simpledialog.askstring(
            "Rename Favorite Block",
            "New name:",
            initialvalue=block.get("name") or "",
            parent=dlg,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == block.get("name"):
            return
        block["name"] = new_name
        _mark_changed()
        _rebuild_notebook(select_block_id=block.get("id"))

    def _delete_block():
        block = _current_block()
        if block is None:
            return
        if not messagebox.askyesno(
            "Delete Favorite Block",
            f"Delete favorite block \"{block.get('name', '')}\"?",
            parent=dlg,
        ):
            return
        block_id = block.get("id")
        blocks[:] = [b for b in blocks if b.get("id") != block_id]
        _mark_changed()
        _rebuild_notebook()

    def _apply_pick(label: str, code: str) -> None:
        _persist_if_needed()
        picked_result[0] = (label, code)
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()

    def _select_favorite():
        block = _current_block()
        if block is None:
            messagebox.showinfo(
                "Search Dx Favorites",
                "Add a favorite block and select a diagnosis.",
                parent=dlg,
            )
            return
        panel = panels.get(block.get("id", ""))
        if panel is None:
            return
        row = panel.get_selected_pick()
        if row is None:
            messagebox.showinfo(
                "Search Dx Favorites",
                "Select a favorite from this block first.",
                parent=dlg,
            )
            return
        label, code = row
        _apply_pick(label, code)

    def _close_without_pick():
        if changed:
            if messagebox.askyesno(
                "Search Dx Favorites",
                "Save changes to favorite blocks?",
                parent=dlg,
            ):
                _persist_if_needed()
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()

    ttk.Button(toolbar, text="Add Favorite Block", command=_add_block).pack(side="left")
    ttk.Button(toolbar, text="Rename Block", command=_rename_block).pack(side="left", padx=(8, 0))
    ttk.Button(toolbar, text="Delete Block", command=_delete_block).pack(side="left", padx=(8, 0))

    ttk.Button(footer, text="Select", command=_select_favorite).pack(side="right")
    ttk.Button(footer, text="Close", command=_close_without_pick).pack(side="right", padx=(0, 8))

    dlg.protocol("WM_DELETE_WINDOW", _close_without_pick)

    if blocks:
        _rebuild_notebook()
    else:
        empty = ttk.Frame(notebook, padding=20)
        notebook.add(empty, text="(no blocks)")
        ttk.Label(
            empty,
            text="No favorite blocks yet. Click \"Add Favorite Block\" to create one\n"
            "(e.g. CS Favorites, LS Favorites, Left UE Favorites).",
            justify="center",
        ).pack(expand=True)

    dlg.wait_window()
    return picked_result[0]


def open_dx_favorites_dialog(parent, *, on_saved=None) -> bool:
    saved = [False]

    def _mark_saved():
        saved[0] = True
        if callable(on_saved):
            on_saved()

    open_search_dx_favorites_dialog(parent, on_saved=_mark_saved)
    return saved[0]
