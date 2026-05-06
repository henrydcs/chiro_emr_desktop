# insurance_demographics.py
"""
Insurance Demographics + Stats window.

Top-level Tk window (Notebook) that lets the user:
  - Maintain a clinic-wide insurance carrier directory (name, parent company,
    payer ID, claims address/phone/fax, portal, notes).
  - Manage a single patient's insurance policies (multiple per patient, with
    insurance type and primary/secondary/tertiary priority).
  - View Master Stats: top carriers by patient count, type/bucket breakdowns,
    and overall counters.
  - Print the carrier directory as a clinic-wide PDF that lands in the
    Global Vault → 'insurance' folder, accessible from any patient chart.

Modeled on attorney_demographics.py so the two subsystems behave the same
way (period filter helpers, "This Patient" tab, Manager dialog launched
from the directory tab, etc.).
"""
from __future__ import annotations

import calendar
import os
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import insurance_data as idata


# Wide range so the user always finds the year they want.
_YEAR_RANGE_BACK = 6
_YEAR_RANGE_FORWARD = 6

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_year_choices() -> tuple[list[str], list[str]]:
    now = datetime.now()
    years = [str(y) for y in range(now.year - _YEAR_RANGE_BACK, now.year + _YEAR_RANGE_FORWARD + 1)]
    return list(_MONTH_NAMES), years


# ===========================================================================
# Carrier picker (used by Patient tab "Add policy" → carrier dropdown)
# ===========================================================================
class CarrierPickerDialog(tk.Toplevel):
    """Modal: pick a carrier from the directory, or open the directory to add one.

    Result accessed via .result (a carrier record dict) or None if cancelled.
    """
    def __init__(self, master, title: str = "Select Insurance Carrier", preselect_id: str = ""):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.attributes("-topmost", True)
        self.geometry("560x440")
        self.minsize(440, 340)
        self.result: dict | None = None

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Pick a carrier from the list, or click 'Manage Carriers' to add a new one.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        search_row = ttk.Frame(outer)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        ent = ttk.Entry(search_row, textvariable=self._search_var)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._search_var.trace_add("write", lambda *_: self._refresh_list())

        list_wrap = ttk.Frame(outer)
        list_wrap.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(list_wrap, exportselection=False, activestyle="dotbox")
        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=sb.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._listbox.bind("<Double-Button-1>", lambda e: self._on_ok())

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Manage Carriers…", command=self._open_manager).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="right")
        ttk.Button(btns, text="Select", command=self._on_ok).pack(side="right", padx=(0, 6))

        self._all: list[dict] = []
        self._preselect_id = preselect_id or ""
        self._refresh_list()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()
        ent.focus_set()

    def _refresh_list(self):
        q = (self._search_var.get() or "").strip().lower()
        self._all = idata.list_carriers_alphabetical()
        self._listbox.delete(0, "end")
        idx_to_select = -1
        for rec in self._all:
            label = idata.carrier_display_label(rec)
            blob = " ".join([
                rec.get("name", ""), rec.get("parent_company", ""),
                rec.get("city", ""), rec.get("state", ""),
                rec.get("payer_id", ""), rec.get("claims_phone", ""),
            ]).lower()
            if q and q not in blob and q not in label.lower():
                continue
            self._listbox.insert("end", label)
            if rec.get("id") == self._preselect_id:
                idx_to_select = self._listbox.size() - 1
        if idx_to_select >= 0:
            self._listbox.selection_set(idx_to_select)
            self._listbox.see(idx_to_select)

    def _selected_record(self) -> dict | None:
        sel = self._listbox.curselection()
        if not sel:
            return None
        label = self._listbox.get(sel[0])
        for rec in self._all:
            if idata.carrier_display_label(rec) == label:
                return rec
        return None

    def _on_ok(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo("Select Carrier", "Please select a carrier.", parent=self)
            return
        self.result = rec
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _open_manager(self):
        win = InsuranceDemographicsWindow(self.master, start_tab="directory")
        self.wait_window(win)
        self._refresh_list()


# ===========================================================================
# Carrier editor (Add / Edit)
# ===========================================================================
class _CarrierEditor(tk.Toplevel):
    def __init__(self, master, record: dict | None = None):
        super().__init__(master)
        self.transient(master)
        self.attributes("-topmost", True)
        self.title("Edit Carrier" if record else "Add Carrier")
        self.geometry("640x600")
        self.minsize(540, 480)
        self.result: dict | None = None
        self._record = record or {}

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text=("Edit Insurance Carrier" if record else "New Insurance Carrier"),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(outer)
        form.pack(fill="both", expand=True)

        self._vars: dict[str, tk.StringVar] = {}

        rows = [
            ("Carrier name",        "name"),
            ("Parent company",      "parent_company"),
            ("Payer ID",            "payer_id"),
            ("Claims phone",        "claims_phone"),
            ("Claims fax",          "fax"),
            ("Claims address 1",    "claims_address1"),
            ("Claims address 2",    "claims_address2"),
            ("City",                "city"),
            ("State",               "state"),
            ("ZIP",                 "zip"),
            ("Provider portal URL", "portal_url"),
        ]

        for i, (label, key) in enumerate(rows):
            ttk.Label(form, text=label + ":").grid(row=i, column=0, sticky="e", padx=(0, 6), pady=3)
            v = tk.StringVar(value=(self._record.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(form, textvariable=v, width=48).grid(row=i, column=1, sticky="we", pady=3)

        # Default insurance type (drop-down).
        next_row = len(rows)
        ttk.Label(form, text="Default type:").grid(
            row=next_row, column=0, sticky="e", padx=(0, 6), pady=3,
        )
        self._default_type_var = tk.StringVar(
            value=(self._record.get("default_type") or "health"),
        )
        self._vars["default_type"] = self._default_type_var
        type_choices = [idata.INSURANCE_TYPE_LABELS[t] for t in idata.INSURANCE_TYPES]
        type_label_to_key = {idata.INSURANCE_TYPE_LABELS[t]: t for t in idata.INSURANCE_TYPES}
        self._type_label_to_key = type_label_to_key
        # Combobox shows labels but we store keys.
        self._default_type_label_var = tk.StringVar(
            value=idata.INSURANCE_TYPE_LABELS.get(
                self._default_type_var.get() or "health", "Health",
            ),
        )
        ttk.Combobox(
            form,
            textvariable=self._default_type_label_var,
            values=type_choices,
            state="readonly",
            width=46,
        ).grid(row=next_row, column=1, sticky="we", pady=3)

        form.columnconfigure(1, weight=1)

        notes_row = next_row + 1
        ttk.Label(form, text="Notes:").grid(
            row=notes_row, column=0, sticky="ne", padx=(0, 6), pady=(6, 3),
        )
        self._notes = tk.Text(form, wrap="word", height=5)
        self._notes.grid(row=notes_row, column=1, sticky="nsew", pady=(6, 3))
        form.rowconfigure(notes_row, weight=1)
        if self._record.get("notes"):
            self._notes.insert("1.0", self._record["notes"])

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

        self.grab_set()

    def _on_save(self):
        data = {k: (v.get() or "").strip() for k, v in self._vars.items() if k != "default_type"}
        # Map combobox label back to type key.
        label = (self._default_type_label_var.get() or "").strip()
        data["default_type"] = self._type_label_to_key.get(label, "health")
        data["notes"] = self._notes.get("1.0", "end").strip()
        if not data.get("name") and not data.get("parent_company"):
            messagebox.showinfo(
                "Missing info",
                "Please enter at least the Carrier name or Parent company.",
                parent=self,
            )
            return
        if self._record.get("id"):
            rec = idata.update_carrier(self._record["id"], data)
        else:
            rec = idata.add_carrier(data)
        self.result = rec
        self.grab_release()
        self.destroy()


# ===========================================================================
# Patient policy editor (Add / Edit)
# ===========================================================================
class _PolicyEditor(tk.Toplevel):
    def __init__(
        self,
        master,
        *,
        record: dict | None = None,
        preselect_carrier_id: str = "",
    ):
        super().__init__(master)
        self.transient(master)
        self.attributes("-topmost", True)
        self.title("Edit Policy" if record else "Add Policy")
        self.geometry("640x640")
        self.minsize(560, 520)
        self.result: dict | None = None
        self._record = record or {}

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text=("Edit Patient Policy" if record else "New Patient Policy"),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(outer)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        # ---- Carrier picker -------------------------------------------
        ttk.Label(form, text="Carrier:").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        carrier_row = ttk.Frame(form)
        carrier_row.grid(row=0, column=1, sticky="we", pady=3)
        self._carrier_id = (
            self._record.get("carrier_id") or preselect_carrier_id or ""
        )
        self._carrier_label_var = tk.StringVar(
            value=idata.carrier_display_label(idata.find_carrier(self._carrier_id))
            or "(none selected)"
        )
        ttk.Label(
            carrier_row, textvariable=self._carrier_label_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(carrier_row, text="Choose…", command=self._pick_carrier).pack(side="right")

        # ---- Insurance type & priority --------------------------------
        ttk.Label(form, text="Insurance type:").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)
        type_choices = [idata.INSURANCE_TYPE_LABELS[t] for t in idata.INSURANCE_TYPES]
        self._type_label_to_key = {
            idata.INSURANCE_TYPE_LABELS[t]: t for t in idata.INSURANCE_TYPES
        }
        cur_type = idata._normalize_type(self._record.get("insurance_type") or "")
        if not self._record:
            # Default to the carrier's preferred type when adding.
            c = idata.find_carrier(self._carrier_id) or {}
            cur_type = idata._normalize_type(c.get("default_type") or "health")
        self._type_label_var = tk.StringVar(
            value=idata.INSURANCE_TYPE_LABELS.get(cur_type, "Health"),
        )
        ttk.Combobox(
            form, textvariable=self._type_label_var,
            values=type_choices, state="readonly",
        ).grid(row=1, column=1, sticky="we", pady=3)

        ttk.Label(form, text="Priority:").grid(row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        pri_choices = [idata.PRIORITY_LABELS[p] for p in idata.PRIORITIES]
        self._pri_label_to_key = {
            idata.PRIORITY_LABELS[p]: p for p in idata.PRIORITIES
        }
        cur_pri = idata._normalize_priority(self._record.get("priority") or "primary")
        self._pri_label_var = tk.StringVar(
            value=idata.PRIORITY_LABELS.get(cur_pri, "Primary"),
        )
        ttk.Combobox(
            form, textvariable=self._pri_label_var,
            values=pri_choices, state="readonly",
        ).grid(row=2, column=1, sticky="we", pady=3)

        # ---- Policy / claim numbers -----------------------------------
        self._vars: dict[str, tk.StringVar] = {}
        text_rows = [
            ("Policy / member #", "policy_number"),
            ("Group #",           "group_number"),
            ("Claim #",           "claim_number"),
            ("Policyholder name", "policyholder_name"),
            ("Policyholder DOB",  "policyholder_dob"),
        ]
        for i, (label, key) in enumerate(text_rows, start=3):
            ttk.Label(form, text=label + ":").grid(row=i, column=0, sticky="e", padx=(0, 6), pady=3)
            v = tk.StringVar(value=(self._record.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(form, textvariable=v, width=48).grid(row=i, column=1, sticky="we", pady=3)
        next_row = 3 + len(text_rows)

        # ---- Relationship (combobox) ----------------------------------
        ttk.Label(form, text="Relationship:").grid(row=next_row, column=0, sticky="e", padx=(0, 6), pady=3)
        self._rel_var = tk.StringVar(
            value=(self._record.get("policyholder_relationship") or "self"),
        )
        ttk.Combobox(
            form, textvariable=self._rel_var,
            values=list(idata.POLICYHOLDER_RELATIONSHIPS),
            state="readonly",
        ).grid(row=next_row, column=1, sticky="we", pady=3)
        next_row += 1

        # ---- Adjuster -------------------------------------------------
        adj_rows = [
            ("Adjuster name",  "adjuster_name"),
            ("Adjuster phone", "adjuster_phone"),
            ("Adjuster email", "adjuster_email"),
            ("Effective date",   "effective_date"),
            ("Termination date", "termination_date"),
        ]
        for label, key in adj_rows:
            ttk.Label(form, text=label + ":").grid(row=next_row, column=0, sticky="e", padx=(0, 6), pady=3)
            v = tk.StringVar(value=(self._record.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(form, textvariable=v, width=48).grid(row=next_row, column=1, sticky="we", pady=3)
            next_row += 1

        # ---- Notes ----------------------------------------------------
        ttk.Label(form, text="Notes:").grid(row=next_row, column=0, sticky="ne", padx=(0, 6), pady=(6, 3))
        self._notes = tk.Text(form, wrap="word", height=4)
        self._notes.grid(row=next_row, column=1, sticky="nsew", pady=(6, 3))
        form.rowconfigure(next_row, weight=1)
        if self._record.get("notes"):
            self._notes.insert("1.0", self._record["notes"])

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

        self.grab_set()

    def _pick_carrier(self):
        dlg = CarrierPickerDialog(self, preselect_id=self._carrier_id)
        self.wait_window(dlg)
        if dlg.result:
            self._carrier_id = dlg.result.get("id") or ""
            self._carrier_label_var.set(idata.carrier_display_label(dlg.result))

    def _on_save(self):
        if not self._carrier_id:
            messagebox.showinfo(
                "Missing carrier",
                "Please choose an insurance carrier first.",
                parent=self,
            )
            return
        type_key = self._type_label_to_key.get(self._type_label_var.get() or "", "other")
        pri_key = self._pri_label_to_key.get(self._pri_label_var.get() or "", "primary")
        data = {k: (v.get() or "").strip() for k, v in self._vars.items()}
        data["carrier_id"] = self._carrier_id
        data["insurance_type"] = type_key
        data["priority"] = pri_key
        data["policyholder_relationship"] = (self._rel_var.get() or "").strip()
        data["notes"] = self._notes.get("1.0", "end").strip()
        self.result = data
        self.grab_release()
        self.destroy()


# ===========================================================================
# Main window
# ===========================================================================
class InsuranceDemographicsWindow(tk.Toplevel):
    """Notebook-style window with Patient + Directory + Stats tabs."""

    TAB_KEYS = ("patient", "directory", "master", "by_type", "alpha")

    def __init__(
        self,
        master,
        start_tab: str = "patient",
        *,
        get_current_patient_fn=None,
        on_change_callback=None,
    ):
        """``get_current_patient_fn`` should return the same shape as the
        attorney window expects:
            {
                "patient_id": str,
                "patient_name": str,         # "Last, First" preferred
                "patient_root": str,         # filesystem path
                "current_exam": str,         # optional, e.g. "Initial 1"
            }
        or None if no patient is loaded.
        """
        super().__init__(master)
        self.title("Insurance Demographics & Stats")
        self.transient(master)
        self.attributes("-topmost", True)

        self._get_current_patient_fn = get_current_patient_fn
        self._on_change_callback = on_change_callback

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1200, int(sw * 0.78))
        h = min(820,  int(sh * 0.82))
        self.geometry(f"{w}x{h}")
        self.minsize(900, 620)

        nb = ttk.Notebook(self)
        self._notebook = nb
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self._tabs: dict[str, ttk.Frame] = {}
        for key, label in [
            ("patient",   "This Patient"),
            ("directory", "Insurance Directory"),
            ("master",    "Master Stats"),
            ("by_type",   "Type Breakdown"),
            ("alpha",     "Alphabetical List"),
        ]:
            f = ttk.Frame(nb, padding=10)
            nb.add(f, text=label)
            self._tabs[key] = f

        self._build_patient_tab(self._tabs["patient"])
        self._build_directory_tab(self._tabs["directory"])
        self._build_master_tab(self._tabs["master"])
        self._build_by_type_tab(self._tabs["by_type"])
        self._build_alpha_tab(self._tabs["alpha"])

        # If no patient is loaded, fall back to the directory tab.
        if start_tab == "patient" and not self._current_patient_info():
            start_tab = "directory"
        if start_tab in self._tabs:
            nb.select(self._tabs[start_tab])

        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_all())

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="Refresh", command=self._refresh_all).pack(side="left")
        ttk.Button(bottom, text="Close", command=self.destroy).pack(side="right")

        self._refresh_all()

    # ------------------------------ shared -------------------------------
    def _current_patient_info(self) -> dict | None:
        if not self._get_current_patient_fn:
            return None
        try:
            info = self._get_current_patient_fn() or None
        except Exception:
            info = None
        if not info:
            return None
        if not (info.get("patient_root") or "").strip():
            return None
        return info

    def _notify_changed(self):
        if callable(self._on_change_callback):
            try:
                self._on_change_callback()
            except Exception:
                pass

    def _refresh_all(self):
        self._refresh_patient()
        self._refresh_directory()
        self._refresh_master()
        self._refresh_by_type()
        self._refresh_alpha()

    # ----------------------- Tab: This Patient ---------------------------
    def _build_patient_tab(self, parent: ttk.Frame):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 8))

        self._patient_title_var = tk.StringVar(value="Current Patient")
        ttk.Label(
            header, textvariable=self._patient_title_var,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")

        self._patient_subtitle_var = tk.StringVar(value="")
        ttk.Label(
            header, textvariable=self._patient_subtitle_var,
            foreground="gray",
        ).pack(anchor="w")

        ttk.Separator(parent).pack(fill="x", pady=(2, 10))

        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(
            toolbar, text="Patient Insurance Policies",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

        ttk.Button(toolbar, text="Add Policy", command=self._patient_add_policy).pack(side="right")
        ttk.Button(toolbar, text="Edit", command=self._patient_edit_policy).pack(side="right", padx=(0, 6))
        ttk.Button(toolbar, text="Delete", command=self._patient_delete_policy).pack(side="right", padx=(0, 6))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("type", "priority", "carrier", "policy_number", "claim_number", "adjuster")
        self._patient_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anc in [
            ("type",          "Type",       140, "w"),
            ("priority",      "Priority",   90,  "center"),
            ("carrier",       "Carrier",    260, "w"),
            ("policy_number", "Policy #",   140, "w"),
            ("claim_number",  "Claim #",    140, "w"),
            ("adjuster",      "Adjuster",   200, "w"),
        ]:
            self._patient_tree.heading(c, text=label)
            self._patient_tree.column(c, width=w, anchor=anc)
        sb = ttk.Scrollbar(body, orient="vertical", command=self._patient_tree.yview)
        self._patient_tree.configure(yscrollcommand=sb.set)
        self._patient_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._patient_tree.bind("<Double-Button-1>", lambda e: self._patient_edit_policy())
        self._patient_tree.bind("<<TreeviewSelect>>", lambda e: self._patient_update_detail())

        detail = ttk.LabelFrame(parent, text="Policy Details")
        detail.pack(fill="x", pady=(8, 0))
        self._patient_detail_var = tk.StringVar(value="(select a policy)")
        ttk.Label(
            detail, textvariable=self._patient_detail_var,
            justify="left", anchor="w",
        ).pack(fill="x", padx=8, pady=8)

        # No-patient banner.
        self._patient_no_patient_var = tk.StringVar(
            value="No patient loaded. Open or start a patient case to add insurance policies."
        )
        self._patient_no_patient_label = ttk.Label(
            parent, textvariable=self._patient_no_patient_var,
            foreground="gray", font=("Segoe UI", 10, "italic"),
        )
        # only packed when there's no patient

    def _refresh_patient(self):
        if not hasattr(self, "_patient_tree"):
            return

        info = self._current_patient_info()
        if not info:
            self._patient_title_var.set("Current Patient")
            self._patient_subtitle_var.set("")
            for iid in self._patient_tree.get_children():
                self._patient_tree.delete(iid)
            self._patient_detail_var.set("(no patient loaded)")
            try:
                self._patient_no_patient_label.pack(fill="x", pady=(8, 0))
            except Exception:
                pass
            return

        try:
            self._patient_no_patient_label.pack_forget()
        except Exception:
            pass

        name = (info.get("patient_name") or "").strip() or "(unnamed patient)"
        pid = (info.get("patient_id") or "").strip()
        exam = (info.get("current_exam") or "").strip()
        self._patient_title_var.set(f"Patient: {name}")
        sub_bits = []
        if pid:
            sub_bits.append(f"ID: {pid}")
        if exam:
            sub_bits.append(f"Current exam: {exam}")
        self._patient_subtitle_var.set("    ".join(sub_bits))

        for iid in self._patient_tree.get_children():
            self._patient_tree.delete(iid)

        policies = idata.load_patient_policies(info["patient_root"])
        for pol in policies:
            t = idata._normalize_type(pol.get("insurance_type"))
            pri = idata._normalize_priority(pol.get("priority"))
            carrier_label = pol.get("carrier_name") or idata.carrier_display_label(
                idata.find_carrier(pol.get("carrier_id") or "")
            ) or "(unknown carrier)"
            adj_bits = []
            if pol.get("adjuster_name"): adj_bits.append(pol["adjuster_name"])
            if pol.get("adjuster_phone"): adj_bits.append(pol["adjuster_phone"])
            self._patient_tree.insert(
                "", "end", iid=pol["id"],
                values=(
                    idata.INSURANCE_TYPE_LABELS.get(t, t),
                    idata.PRIORITY_LABELS.get(pri, pri),
                    carrier_label,
                    pol.get("policy_number", ""),
                    pol.get("claim_number", ""),
                    " — ".join(adj_bits),
                ),
            )
        self._patient_update_detail()

    def _patient_selected_id(self) -> str | None:
        sel = self._patient_tree.selection()
        return sel[0] if sel else None

    def _patient_update_detail(self):
        info = self._current_patient_info()
        pid = self._patient_selected_id()
        if not info or not pid:
            self._patient_detail_var.set("(select a policy)")
            return
        rec = idata.find_patient_policy(info["patient_root"], pid)
        if not rec:
            self._patient_detail_var.set("(record not found)")
            return
        carrier = idata.find_carrier(rec.get("carrier_id") or "") or {}
        addr_lines = []
        if carrier.get("claims_address1"): addr_lines.append(carrier["claims_address1"])
        if carrier.get("claims_address2"): addr_lines.append(carrier["claims_address2"])
        cs = ", ".join(filter(None, [carrier.get("city", ""), carrier.get("state", "")]))
        if cs or carrier.get("zip"):
            addr_lines.append((cs + " " + (carrier.get("zip") or "")).strip())
        addr = "\n".join(addr_lines) or "(no claims address on file)"

        details = [
            f"Carrier: {idata.carrier_display_label(carrier) or rec.get('carrier_name','')}",
            (
                f"Type: {idata.INSURANCE_TYPE_LABELS.get(idata._normalize_type(rec.get('insurance_type')))}    "
                f"Priority: {idata.PRIORITY_LABELS.get(idata._normalize_priority(rec.get('priority')))}"
            ),
            (
                f"Policy #: {rec.get('policy_number','')}    "
                f"Group #: {rec.get('group_number','')}    "
                f"Claim #: {rec.get('claim_number','')}"
            ),
            (
                f"Policyholder: {rec.get('policyholder_name','')}    "
                f"DOB: {rec.get('policyholder_dob','')}    "
                f"Relation: {rec.get('policyholder_relationship','')}"
            ),
            (
                f"Adjuster: {rec.get('adjuster_name','')}    "
                f"{rec.get('adjuster_phone','')}    "
                f"{rec.get('adjuster_email','')}"
            ),
            (
                f"Effective: {rec.get('effective_date','')}    "
                f"Terminated: {rec.get('termination_date','')}"
            ),
            f"Payer ID: {carrier.get('payer_id','')}",
            f"Claims Phone: {carrier.get('claims_phone','')}    Fax: {carrier.get('fax','')}",
            f"Claims Address:\n{addr}",
            f"Portal: {carrier.get('portal_url','')}",
        ]
        if rec.get("notes"):
            details.append(f"Notes: {rec.get('notes','')}")
        self._patient_detail_var.set("\n".join(details))

    def _patient_add_policy(self):
        info = self._current_patient_info()
        if not info:
            messagebox.showinfo(
                "No patient",
                "Open or start a patient case before adding policies.",
                parent=self,
            )
            return
        # Pick a carrier first to streamline the flow.
        picker = CarrierPickerDialog(self, title="Select carrier for new policy")
        self.wait_window(picker)
        if not picker.result:
            return
        ed = _PolicyEditor(self, preselect_carrier_id=picker.result.get("id") or "")
        self.wait_window(ed)
        if not ed.result:
            return
        idata.add_patient_policy(
            patient_root=info["patient_root"],
            patient_id=info.get("patient_id") or "",
            patient_name=info.get("patient_name") or "",
            data=ed.result,
        )
        self._refresh_all()
        self._notify_changed()

    def _patient_edit_policy(self):
        info = self._current_patient_info()
        if not info:
            return
        pid = self._patient_selected_id()
        if not pid:
            messagebox.showinfo("Edit", "Select a policy first.", parent=self)
            return
        rec = idata.find_patient_policy(info["patient_root"], pid)
        if not rec:
            return
        ed = _PolicyEditor(self, record=rec)
        self.wait_window(ed)
        if not ed.result:
            return
        idata.update_patient_policy(
            patient_root=info["patient_root"],
            policy_id=pid,
            data=ed.result,
        )
        self._refresh_all()
        self._notify_changed()

    def _patient_delete_policy(self):
        info = self._current_patient_info()
        if not info:
            return
        pid = self._patient_selected_id()
        if not pid:
            messagebox.showinfo("Delete", "Select a policy first.", parent=self)
            return
        rec = idata.find_patient_policy(info["patient_root"], pid)
        if not rec:
            return
        label = rec.get("carrier_name") or idata.carrier_display_label(
            idata.find_carrier(rec.get("carrier_id") or "")
        ) or "(unknown)"
        if not messagebox.askyesno(
            "Delete policy",
            f"Remove this policy from the patient?\n\n{label}",
            parent=self,
        ):
            return
        idata.delete_patient_policy(
            patient_root=info["patient_root"],
            policy_id=pid,
        )
        self._refresh_all()
        self._notify_changed()

    # --------------------- Tab: Insurance Directory ----------------------
    def _build_directory_tab(self, parent: ttk.Frame):
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 8))

        ttk.Label(
            top, text="Insurance Directory",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        ttk.Button(top, text="Add Carrier", command=self._dir_add).pack(side="right")
        ttk.Button(top, text="Edit", command=self._dir_edit).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Delete", command=self._dir_delete).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Print PDF…", command=self._dir_print_pdf).pack(side="right", padx=(0, 12))

        search_row = ttk.Frame(parent)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self._dir_search_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self._dir_search_var).pack(
            side="left", fill="x", expand=True, padx=(6, 0),
        )
        self._dir_search_var.trace_add("write", lambda *_: self._refresh_directory())

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("name", "parent", "payer_id", "phone", "fax", "city", "state")
        self._dir_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w in [
            ("name", "Carrier", 220),
            ("parent", "Parent / Group", 160),
            ("payer_id", "Payer ID", 100),
            ("phone", "Claims Phone", 130),
            ("fax", "Fax", 110),
            ("city", "City", 110),
            ("state", "State", 60),
        ]:
            self._dir_tree.heading(c, text=label)
            self._dir_tree.column(c, width=w, anchor="w")

        sb = ttk.Scrollbar(body, orient="vertical", command=self._dir_tree.yview)
        self._dir_tree.configure(yscrollcommand=sb.set)
        self._dir_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._dir_tree.bind("<Double-Button-1>", lambda e: self._dir_edit())

        detail = ttk.LabelFrame(parent, text="Carrier Details")
        detail.pack(fill="x", pady=(8, 0))
        self._dir_detail_var = tk.StringVar(value="(select a carrier)")
        ttk.Label(
            detail, textvariable=self._dir_detail_var,
            justify="left", anchor="w",
        ).pack(fill="x", padx=8, pady=8)
        self._dir_tree.bind("<<TreeviewSelect>>", lambda e: self._dir_update_detail())

    def _refresh_directory(self):
        q = (self._dir_search_var.get() or "").strip().lower() if hasattr(self, "_dir_search_var") else ""
        for iid in self._dir_tree.get_children():
            self._dir_tree.delete(iid)
        for rec in idata.list_carriers_alphabetical():
            blob = " ".join([
                rec.get("name", ""), rec.get("parent_company", ""),
                rec.get("payer_id", ""), rec.get("city", ""),
                rec.get("state", ""), rec.get("claims_phone", ""),
                rec.get("notes", ""),
            ]).lower()
            if q and q not in blob:
                continue
            self._dir_tree.insert(
                "", "end", iid=rec["id"],
                values=(
                    rec.get("name", ""),
                    rec.get("parent_company", ""),
                    rec.get("payer_id", ""),
                    rec.get("claims_phone", ""),
                    rec.get("fax", ""),
                    rec.get("city", ""),
                    rec.get("state", ""),
                ),
            )
        self._dir_update_detail()

    def _dir_selected_id(self) -> str | None:
        sel = self._dir_tree.selection()
        return sel[0] if sel else None

    def _dir_update_detail(self):
        cid = self._dir_selected_id()
        if not cid:
            self._dir_detail_var.set("(select a carrier)")
            return
        rec = idata.find_carrier(cid)
        if not rec:
            self._dir_detail_var.set("(record not found)")
            return
        addr_lines = []
        if rec.get("claims_address1"): addr_lines.append(rec["claims_address1"])
        if rec.get("claims_address2"): addr_lines.append(rec["claims_address2"])
        cs = ", ".join(filter(None, [rec.get("city", ""), rec.get("state", "")]))
        if cs or rec.get("zip"):
            addr_lines.append((cs + " " + (rec.get("zip") or "")).strip())
        addr = "\n".join(addr_lines) or "(no claims address on file)"
        default_t = idata._normalize_type(rec.get("default_type") or "health")
        self._dir_detail_var.set(
            f"Carrier: {rec.get('name','')}\n"
            f"Parent / Group: {rec.get('parent_company','')}\n"
            f"Default type: {idata.INSURANCE_TYPE_LABELS.get(default_t, default_t)}\n"
            f"Payer ID: {rec.get('payer_id','')}    "
            f"Claims Phone: {rec.get('claims_phone','')}    Fax: {rec.get('fax','')}\n"
            f"Portal: {rec.get('portal_url','')}\n"
            f"Claims Address:\n{addr}\n"
            f"Notes: {rec.get('notes','')}"
        )

    def _dir_add(self):
        ed = _CarrierEditor(self, record=None)
        self.wait_window(ed)
        if ed.result:
            self._refresh_all()
            self._regenerate_insurance_list_pdf_silent()

    def _dir_edit(self):
        cid = self._dir_selected_id()
        if not cid:
            messagebox.showinfo("Edit", "Select a carrier first.", parent=self)
            return
        rec = idata.find_carrier(cid)
        if not rec:
            return
        ed = _CarrierEditor(self, record=rec)
        self.wait_window(ed)
        if ed.result:
            self._refresh_all()
            self._regenerate_insurance_list_pdf_silent()

    def _dir_delete(self):
        cid = self._dir_selected_id()
        if not cid:
            messagebox.showinfo("Delete", "Select a carrier first.", parent=self)
            return
        rec = idata.find_carrier(cid)
        if not rec:
            return
        label = idata.carrier_display_label(rec)
        if not messagebox.askyesno(
            "Delete carrier",
            f"Delete this carrier and ALL patient policies that point to it?\n\n{label}",
            parent=self,
        ):
            return
        idata.delete_carrier(cid)
        self._refresh_all()
        self._regenerate_insurance_list_pdf_silent()

    # ----------------------- Insurance Directory PDF ---------------------
    def _build_insurance_list_pdf(self, *, open_after: bool, show_message: bool):
        """Generate / overwrite the canonical 'List of Insurance Carriers' PDF.

        Writes to <DATA_DIR>/global_vault/insurance/List_of_Insurance_Carriers.pdf
        so it's reachable from every chart's Global Vault tab.
        """
        try:
            from insurance_list_pdf import (
                build_insurance_list_pdf,
                canonical_pdf_paths,
                REPORTLAB_OK,
            )
        except Exception as e:
            if show_message:
                messagebox.showerror(
                    "Print PDF",
                    f"Could not load PDF generator:\n\n{e}",
                    parent=self,
                )
            return None
        if not REPORTLAB_OK:
            if show_message:
                messagebox.showerror(
                    "Print PDF",
                    "ReportLab is not installed. Install with:\n\npip install reportlab",
                    parent=self,
                )
            return None

        try:
            from config import CLINIC_NAME as _CFG_CLINIC
        except Exception:
            _CFG_CLINIC = ""
        clinic_name = (_CFG_CLINIC or "").strip()

        paths = canonical_pdf_paths()
        primary = str(paths["primary"])
        try:
            Path(primary).parent.mkdir(parents=True, exist_ok=True)
            build_insurance_list_pdf(
                primary,
                clinic_name=clinic_name,
                carriers=idata.list_carriers_alphabetical(),
            )
        except Exception as e:
            if show_message:
                messagebox.showerror("Print PDF", f"Could not build PDF:\n\n{e}", parent=self)
            return None

        if open_after:
            try:
                self._open_with_default_app(primary)
            except Exception:
                pass

        if show_message:
            messagebox.showinfo(
                "Insurance Directory — PDF",
                f"Saved to Global Vault → 'insurance':\n\n{primary}",
                parent=self,
            )
        return primary

    def _dir_print_pdf(self):
        self._build_insurance_list_pdf(open_after=True, show_message=True)

    def _regenerate_insurance_list_pdf_silent(self):
        """Called automatically after add/edit/delete so the same PDF stays
        in sync with the directory. No popups, no auto-open."""
        try:
            self._build_insurance_list_pdf(open_after=False, show_message=False)
        except Exception:
            pass

    @staticmethod
    def _open_with_default_app(path: str) -> None:
        import sys, subprocess
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # --------------------------- Tab: Master Stats -----------------------
    def _build_master_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent, text="Master Insurance Stats",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text="How many patients each carrier serves, plus overall counters.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        self._master_filter = self._build_period_filter(parent, on_change=self._refresh_master)

        # Counters band.
        counters = ttk.Frame(parent)
        counters.pack(fill="x", pady=(0, 6))
        self._master_counters_var = tk.StringVar(value="")
        ttk.Label(
            counters, textvariable=self._master_counters_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("rank", "carrier", "patients", "policies", "share", "bar")
        self._master_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anc in [
            ("rank",     "#",            40,  "center"),
            ("carrier",  "Carrier",      280, "w"),
            ("patients", "Patients",     90,  "center"),
            ("policies", "Policies",     90,  "center"),
            ("share",    "% of patients",110, "center"),
            ("bar",      "Volume",       260, "w"),
        ]:
            self._master_tree.heading(c, text=label)
            self._master_tree.column(c, width=w, anchor=anc)
        sb = ttk.Scrollbar(body, orient="vertical", command=self._master_tree.yview)
        self._master_tree.configure(yscrollcommand=sb.set)
        self._master_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _refresh_master(self):
        if not hasattr(self, "_master_tree"):
            return
        year, month = self._read_period_filter(self._master_filter)
        for iid in self._master_tree.get_children():
            self._master_tree.delete(iid)

        rows = idata.per_carrier_summary(year=year, month=month)
        stats = idata.overall_stats(year=year, month=month)
        total_patients = stats.get("total_patients_with_insurance", 0) or 0
        max_patients = max((r["patients"] for r in rows), default=0)

        for i, r in enumerate(rows, start=1):
            share = (r["patients"] / total_patients * 100.0) if total_patients else 0.0
            bar_len = 0
            if max_patients:
                bar_len = int(round((r["patients"] / max_patients) * 24))
            bar = "█" * bar_len + ("·" * (24 - bar_len) if bar_len < 24 else "")
            self._master_tree.insert(
                "", "end",
                values=(
                    i,
                    r["label"],
                    r["patients"],
                    r["policies"],
                    f"{share:.1f}%",
                    bar,
                ),
            )

        scope_blurb = self._period_blurb(self._master_filter)
        self._master_counters_var.set(
            f"Patients with insurance: {stats['total_patients_with_insurance']}    "
            f"Total policies: {stats['total_policies']}    "
            f"Carriers in directory: {stats['total_carriers']} "
            f"({stats['active_carriers']} active)"
            f"{('   |   ' + scope_blurb) if scope_blurb else ''}"
        )

    # -------------------------- Tab: Type Breakdown ----------------------
    def _build_by_type_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent, text="Insurance Type Breakdown",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text=(
                "How patient policies break down by insurance type. "
                "Auto types (PIP / Med-Pay / Liability) are also rolled up "
                "into a single 'Personal Injury / Auto' bucket."
            ),
            foreground="gray", justify="left", wraplength=900,
        ).pack(anchor="w", pady=(0, 8))

        self._type_filter = self._build_period_filter(parent, on_change=self._refresh_by_type)

        # Detailed (per type) table on top, bucket roll-up on the bottom.
        top_lf = ttk.LabelFrame(parent, text="By insurance type")
        top_lf.pack(fill="both", expand=True, pady=(0, 8))
        cols = ("type", "patients", "policies", "share")
        self._type_tree = ttk.Treeview(top_lf, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anc in [
            ("type",     "Type",         220, "w"),
            ("patients", "Patients",     100, "center"),
            ("policies", "Policies",     100, "center"),
            ("share",    "% of patients",120, "center"),
        ]:
            self._type_tree.heading(c, text=label)
            self._type_tree.column(c, width=w, anchor=anc)
        sb = ttk.Scrollbar(top_lf, orient="vertical", command=self._type_tree.yview)
        self._type_tree.configure(yscrollcommand=sb.set)
        self._type_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bot_lf = ttk.LabelFrame(parent, text="Rolled-up buckets")
        bot_lf.pack(fill="x")
        cols2 = ("bucket", "patients", "policies")
        self._bucket_tree = ttk.Treeview(bot_lf, columns=cols2, show="headings", selectmode="browse", height=6)
        for c, label, w, anc in [
            ("bucket",   "Bucket",   260, "w"),
            ("patients", "Patients", 100, "center"),
            ("policies", "Policies", 100, "center"),
        ]:
            self._bucket_tree.heading(c, text=label)
            self._bucket_tree.column(c, width=w, anchor=anc)
        self._bucket_tree.pack(fill="x")

    def _refresh_by_type(self):
        if not hasattr(self, "_type_tree"):
            return
        year, month = self._read_period_filter(self._type_filter)
        for iid in self._type_tree.get_children():
            self._type_tree.delete(iid)
        for iid in self._bucket_tree.get_children():
            self._bucket_tree.delete(iid)

        type_rows = idata.per_type_summary(year=year, month=month)
        bucket_rows = idata.per_bucket_summary(year=year, month=month)
        stats = idata.overall_stats(year=year, month=month)
        total_patients = stats.get("total_patients_with_insurance", 0) or 0

        for r in type_rows:
            if r["patients"] == 0 and r["policies"] == 0:
                continue  # hide empty rows so the table doesn't get cluttered
            share = (r["patients"] / total_patients * 100.0) if total_patients else 0.0
            self._type_tree.insert(
                "", "end",
                values=(r["label"], r["patients"], r["policies"], f"{share:.1f}%"),
            )
        if not self._type_tree.get_children():
            self._type_tree.insert("", "end", values=("(no policies in this period)", 0, 0, "0.0%"))

        for r in bucket_rows:
            self._bucket_tree.insert(
                "", "end",
                values=(r["bucket"], r["patients"], r["policies"]),
            )
        if not self._bucket_tree.get_children():
            self._bucket_tree.insert("", "end", values=("(none)", 0, 0))

    # ------------------------- Tab: Alphabetical List --------------------
    def _build_alpha_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent, text="All Carriers — Alphabetical",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)

        self._alpha_text = tk.Text(wrap, wrap="word", state="disabled")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._alpha_text.yview)
        self._alpha_text.configure(yscrollcommand=sb.set)
        self._alpha_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._alpha_text.tag_configure("hdr", font=("Segoe UI", 10, "bold"))
        self._alpha_text.tag_configure("dim", foreground="gray")

    def _refresh_alpha(self):
        if not hasattr(self, "_alpha_text"):
            return
        carriers = idata.list_carriers_alphabetical()
        t = self._alpha_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not carriers:
            t.insert(
                "end",
                "(no carriers yet — add one from the Insurance Directory tab)\n",
                ("dim",),
            )
        else:
            t.insert(
                "end",
                f"Total carriers on file: {len(carriers)}\n\n",
                ("hdr",),
            )
            for i, rec in enumerate(carriers, start=1):
                line = f"{i:>3}.  {idata.carrier_display_label(rec)}\n"
                t.insert("end", line)
                bits = []
                if rec.get("payer_id"):     bits.append(f"Payer ID: {rec['payer_id']}")
                if rec.get("claims_phone"): bits.append(f"Phone: {rec['claims_phone']}")
                if rec.get("fax"):          bits.append(f"Fax: {rec['fax']}")
                cs = ", ".join(filter(None, [rec.get("city", ""), rec.get("state", "")]))
                if cs: bits.append(cs)
                if bits:
                    t.insert("end", "      " + "   ".join(bits) + "\n", ("dim",))
        t.configure(state="disabled")

    # ------------------------ helpers: period filter ---------------------
    def _build_period_filter(self, parent: ttk.Frame, *, on_change) -> dict:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))

        months, years = _month_year_choices()
        scope_var = tk.StringVar(value="All time")
        month_var = tk.StringVar(value=_MONTH_NAMES[datetime.now().month - 1])
        year_var = tk.StringVar(value=str(datetime.now().year))

        ttk.Label(row, text="Period:").pack(side="left")
        scope_cb = ttk.Combobox(
            row, textvariable=scope_var,
            values=("All time", "By Year", "By Month"),
            state="readonly", width=10,
        )
        scope_cb.pack(side="left", padx=(6, 12))

        ttk.Label(row, text="Month:").pack(side="left")
        month_cb = ttk.Combobox(
            row, textvariable=month_var, values=months, state="readonly", width=12,
        )
        month_cb.pack(side="left", padx=(6, 12))

        ttk.Label(row, text="Year:").pack(side="left")
        year_cb = ttk.Combobox(
            row, textvariable=year_var, values=years, state="readonly", width=8,
        )
        year_cb.pack(side="left", padx=(6, 12))

        def _apply_state(*_):
            scope = scope_var.get()
            month_cb.configure(state="readonly" if scope == "By Month" else "disabled")
            year_cb.configure(state="readonly" if scope in ("By Month", "By Year") else "disabled")
            on_change()

        scope_var.trace_add("write", _apply_state)
        month_var.trace_add("write", lambda *_: on_change())
        year_var.trace_add("write", lambda *_: on_change())
        _apply_state()

        return {"scope": scope_var, "month": month_var, "year": year_var}

    def _read_period_filter(self, f: dict) -> tuple[int | None, int | None]:
        scope = f["scope"].get()
        if scope == "All time":
            return (None, None)
        try:
            year = int(f["year"].get())
        except Exception:
            year = None
        if scope == "By Year":
            return (year, None)
        try:
            month = _MONTH_NAMES.index(f["month"].get()) + 1
        except Exception:
            month = None
        return (year, month)

    def _period_blurb(self, f: dict) -> str:
        scope = f["scope"].get()
        if scope == "All time":
            return ""
        if scope == "By Year":
            return f"Year: {f['year'].get()}"
        return f"{f['month'].get()} {f['year'].get()}"
