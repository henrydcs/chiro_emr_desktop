# icd10_search_dialog.py
"""Modal ICD-10-CM search dialog backed by the local CMS codes file."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from icd10_lookup import (
    Icd10Entry,
    display_for_entry,
    icd10_file_status,
    load_icd10_entries,
    search_icd10,
)


def open_icd10_search_dialog(parent) -> tuple[str, str] | None:
    """
    Open a search dialog. Returns (description, dotted_icd10) on Select,
    or None if cancelled.
    """
    ok, status_msg = icd10_file_status()
    if not ok:
        messagebox.showerror("ICD-10 Lookup", status_msg, parent=parent)
        return None

    try:
        load_icd10_entries()
    except Exception as e:
        messagebox.showerror(
            "ICD-10 Lookup",
            f"Could not load ICD-10 codes file:\n{e}",
            parent=parent,
        )
        return None

    result: list[tuple[str, str] | None] = [None]
    hits: list[Icd10Entry] = []

    dlg = tk.Toplevel(parent)
    dlg.title("Search ICD-10")
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    dlg.resizable(True, True)
    dlg.minsize(560, 420)

    wrap = ttk.Frame(dlg, padding=12)
    wrap.pack(fill="both", expand=True)

    ttk.Label(
        wrap,
        text="Search by code or keywords (e.g. M54.2 or cervicalgia)",
    ).pack(anchor="w")

    search_var = tk.StringVar(value="")
    entry = ttk.Entry(wrap, textvariable=search_var)
    entry.pack(fill="x", pady=(6, 4))

    status_var = tk.StringVar(value="Type to search…")
    ttk.Label(wrap, textvariable=status_var, foreground="#555555").pack(anchor="w")

    list_fr = ttk.Frame(wrap)
    list_fr.pack(fill="both", expand=True, pady=(8, 8))

    lb = tk.Listbox(
        list_fr,
        height=16,
        activestyle="dotbox",
        exportselection=False,
        font=("Segoe UI", 10),
    )
    sb = ttk.Scrollbar(list_fr, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    btn_row = ttk.Frame(wrap)
    btn_row.pack(fill="x")

    def _close():
        try:
            dlg.grab_release()
        except Exception:
            pass
        dlg.destroy()

    def _apply_selection():
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("ICD-10 Lookup", "Select a diagnosis code first.", parent=dlg)
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(hits):
            return
        ent = hits[idx]
        result[0] = (ent.description, ent.code)
        _close()

    def _refresh_results(*_):
        q = search_var.get()
        lb.delete(0, tk.END)
        hits.clear()
        q_stripped = (q or "").strip()
        if not q_stripped:
            status_var.set("Type to search…")
            return
        found = search_icd10(q_stripped, limit=60)
        hits.extend(found)
        for ent in found:
            lb.insert(tk.END, display_for_entry(ent))
        if found:
            status_var.set(f"{len(found)} result{'s' if len(found) != 1 else ''}")
            lb.selection_set(0)
            lb.activate(0)
        else:
            status_var.set("No matches")

    ttk.Button(btn_row, text="Select", command=_apply_selection).pack(side="right")
    ttk.Button(btn_row, text="Cancel", command=_close).pack(side="right", padx=(0, 8))

    search_var.trace_add("write", _refresh_results)
    entry.bind("<Return>", lambda _e: _apply_selection())
    lb.bind("<Double-Button-1>", lambda _e: _apply_selection())
    lb.bind("<Return>", lambda _e: _apply_selection())
    dlg.protocol("WM_DELETE_WINDOW", _close)

    try:
        entry.focus_set()
    except Exception:
        pass

    dlg.wait_window()
    return result[0]
