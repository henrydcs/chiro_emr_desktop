# attorney_demographics.py
"""
Attorney Demographics + Referral Stats window.

Top-level Tk window (Notebook) that lets the user:
  - Maintain a clinic-wide attorney directory (firm, contact, address, phone,
    fax, email, paralegal, case manager, website, notes).
  - View Doctors-on-Liens referral logs by month/year.
  - View counts of incoming attorney referrals (non-DoL) and outgoing
    (clinic-to-attorney) referrals.
  - View a master summary of all referral activity.
  - Browse all attorneys alphabetically as a plain text list.

Also exposes AttorneyPickerDialog: a small modal dialog used by the main app
to pick (or create) an attorney when the user toggles a referral button.
"""
from __future__ import annotations

import calendar
import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

import attorney_data as adata


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


def _month_label(year: int, month: int) -> str:
    """e.g. 'April 1st – 30th, 2026' (matches the Doctors on Liens form)."""
    name = _MONTH_NAMES[month - 1]
    last_day = calendar.monthrange(year, month)[1]
    def _ord(n: int) -> str:
        if 10 <= n % 100 <= 20:
            suf = "th"
        else:
            suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf}"
    return f"{name} {_ord(1)} – {_ord(last_day)}, {year}"


# ===========================================================================
# Attorney picker (used by the toggle buttons in the main app)
# ===========================================================================
class AttorneyPickerDialog(tk.Toplevel):
    """Modal: pick an attorney from the directory, or open the directory to add one.

    Result accessed via .result (an attorney record dict) or None if cancelled.
    """
    def __init__(self, master, title: str = "Select Attorney", preselect_id: str = ""):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.attributes("-topmost", True)
        self.geometry("520x420")
        self.minsize(420, 320)
        self.result: dict | None = None

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Pick an attorney from the list. Click 'Manage Attorneys' to add a new one.",
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
        ttk.Button(btns, text="Manage Attorneys…", command=self._open_manager).pack(side="left")
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
        self._all = adata.list_attorneys_alphabetical()
        self._listbox.delete(0, "end")
        idx_to_select = -1
        for i, rec in enumerate(self._all):
            label = adata.attorney_display_label(rec)
            blob = " ".join([
                rec.get("firm_name", ""), rec.get("attorney_name", ""),
                rec.get("city", ""), rec.get("state", ""),
                rec.get("phone", ""), rec.get("email", ""),
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
            if adata.attorney_display_label(rec) == label:
                return rec
        return None

    def _on_ok(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo("Select Attorney", "Please select an attorney.", parent=self)
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
        win = AttorneyDemographicsWindow(self.master, start_tab="directory")
        self.wait_window(win)
        self._refresh_list()


# ===========================================================================
# Attorney editor (Add / Edit)
# ===========================================================================
class _AttorneyEditor(tk.Toplevel):
    def __init__(self, master, record: dict | None = None):
        super().__init__(master)
        self.transient(master)
        self.attributes("-topmost", True)
        self.title("Edit Attorney" if record else "Add Attorney")
        self.geometry("620x540")
        self.minsize(520, 440)
        self.result: dict | None = None
        self._record = record or {}

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text=("Edit Attorney" if record else "New Attorney"),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        form = ttk.Frame(outer)
        form.pack(fill="both", expand=True)

        self._vars: dict[str, tk.StringVar] = {}

        rows = [
            ("Firm name",      "firm_name"),
            ("Attorney name",  "attorney_name"),
            ("Contact name",   "contact_name"),
            ("Paralegal",      "paralegal_name"),
            ("Case manager",   "case_manager"),
            ("Address line 1", "address1"),
            ("Address line 2", "address2"),
            ("City",           "city"),
            ("State",          "state"),
            ("ZIP",            "zip"),
            ("Phone",          "phone"),
            ("Fax",            "fax"),
            ("Email",          "email"),
            ("Website",        "website"),
        ]

        for i, (label, key) in enumerate(rows):
            ttk.Label(form, text=label + ":").grid(row=i, column=0, sticky="e", padx=(0, 6), pady=3)
            v = tk.StringVar(value=(self._record.get(key) or ""))
            self._vars[key] = v
            ttk.Entry(form, textvariable=v, width=48).grid(row=i, column=1, sticky="we", pady=3)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Notes:").grid(row=len(rows), column=0, sticky="ne", padx=(0, 6), pady=(6, 3))
        self._notes = tk.Text(form, wrap="word", height=5)
        self._notes.grid(row=len(rows), column=1, sticky="nsew", pady=(6, 3))
        form.rowconfigure(len(rows), weight=1)
        existing_notes = self._record.get("notes") or ""
        if existing_notes:
            self._notes.insert("1.0", existing_notes)

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

        self.grab_set()

    def _on_save(self):
        data = {k: (v.get() or "").strip() for k, v in self._vars.items()}
        data["notes"] = self._notes.get("1.0", "end").strip()
        if not data.get("firm_name") and not data.get("attorney_name"):
            messagebox.showinfo(
                "Missing info",
                "Please enter at least the Firm name or Attorney name.",
                parent=self,
            )
            return
        if self._record.get("id"):
            rec = adata.update_attorney(self._record["id"], data)
        else:
            rec = adata.add_attorney(data)
        self.result = rec
        self.grab_release()
        self.destroy()


# ===========================================================================
# Main window
# ===========================================================================
class AttorneyDemographicsWindow(tk.Toplevel):
    """Notebook-style window with Directory + multiple Stats tabs."""

    TAB_KEYS = ("patient", "directory", "dol", "att_in", "att_out", "master", "alpha")

    def __init__(
        self,
        master,
        start_tab: str = "patient",
        *,
        get_current_patient_fn=None,
        on_change_callback=None,
    ):
        """
        get_current_patient_fn() should return a dict like:
            {
                "patient_id": str,
                "patient_name": str,         # "Last, First" preferred
                "patient_root": str,         # filesystem path
                "current_exam": str,         # optional, e.g. "Initial 1"
            }
        or None if no patient is loaded.

        on_change_callback() is called any time the window mutates this
        patient's referral state, so the parent can refresh its UI.
        """
        super().__init__(master)
        self.title("Attorney Demographics & Referrals")
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
            ("directory", "Attorneys Directory"),
            ("dol",       "Doctors on Liens — Referral Log"),
            ("att_in",    "Attorney Referrals (Incoming)"),
            ("att_out",   "Clinic Referrals to Attorneys"),
            ("master",    "Master Stats"),
            ("alpha",     "Alphabetical List"),
        ]:
            f = ttk.Frame(nb, padding=10)
            nb.add(f, text=label)
            self._tabs[key] = f

        self._build_patient_tab(self._tabs["patient"])
        self._build_directory_tab(self._tabs["directory"])
        self._build_dol_tab(self._tabs["dol"])
        self._build_incoming_tab(self._tabs["att_in"])
        self._build_outgoing_tab(self._tabs["att_out"])
        self._build_master_tab(self._tabs["master"])
        self._build_alpha_tab(self._tabs["alpha"])

        # If no patient is loaded, fall back to the directory tab even if caller
        # asked for "patient", so we don't open onto an empty stub.
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

    # -------------------------------- shared --------------------------------
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
        self._refresh_dol()
        self._refresh_incoming()
        self._refresh_outgoing()
        self._refresh_master()
        self._refresh_alpha()

    # ----------------------- Tab: This Patient ------------------------------
    def _build_patient_tab(self, parent: ttk.Frame):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 8))

        self._patient_title_var = tk.StringVar(value="Current Patient")
        ttk.Label(
            header,
            textvariable=self._patient_title_var,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")

        self._patient_subtitle_var = tk.StringVar(value="")
        ttk.Label(
            header,
            textvariable=self._patient_subtitle_var,
            foreground="gray",
        ).pack(anchor="w")

        ttk.Separator(parent).pack(fill="x", pady=(2, 10))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        # Three labelframes side-by-side; on narrow windows they stack.
        self._patient_section_widgets: dict[str, dict] = {}

        for col, (direction, title) in enumerate((
            ("from_dol",       "Doctors on Liens"),
            ("from_attorney",  "Attorney Referred Patient"),
            ("to_attorney",    "We Referred to Attorney"),
        )):
            lf = ttk.LabelFrame(body, text=title)
            lf.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0), pady=0)
            body.columnconfigure(col, weight=1)
            body.rowconfigure(0, weight=1)

            inner = ttk.Frame(lf, padding=10)
            inner.pack(fill="both", expand=True)

            status_var = tk.StringVar(value="(not set)")
            ttk.Label(
                inner, textvariable=status_var,
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")

            details_var = tk.StringVar(value="")
            details_lbl = ttk.Label(
                inner, textvariable=details_var, justify="left", anchor="w",
            )
            details_lbl.pack(fill="x", pady=(6, 0))

            btn_row = ttk.Frame(inner)
            btn_row.pack(fill="x", pady=(10, 0))

            set_btn = ttk.Button(
                btn_row,
                text="Set / Change…",
                command=lambda d=direction: self._patient_set(d),
            )
            set_btn.pack(side="left")

            clear_btn = ttk.Button(
                btn_row,
                text="Clear",
                command=lambda d=direction: self._patient_clear(d),
            )
            clear_btn.pack(side="left", padx=(6, 0))

            view_btn = ttk.Button(
                btn_row,
                text="Edit Attorney…",
                command=lambda d=direction: self._patient_edit_linked(d),
            )
            view_btn.pack(side="left", padx=(6, 0))

            self._patient_section_widgets[direction] = {
                "status_var": status_var,
                "details_var": details_var,
                "set_btn": set_btn,
                "clear_btn": clear_btn,
                "view_btn": view_btn,
            }

        # No-patient overlay message
        self._patient_no_patient_var = tk.StringVar(
            value="No patient loaded. Open or start a patient case to see their attorney."
        )
        self._patient_no_patient_label = ttk.Label(
            parent,
            textvariable=self._patient_no_patient_var,
            foreground="gray",
            font=("Segoe UI", 10, "italic"),
        )
        # only packed when there's no patient

    def _refresh_patient(self):
        if not hasattr(self, "_patient_section_widgets"):
            return

        info = self._current_patient_info()
        if not info:
            self._patient_title_var.set("Current Patient")
            self._patient_subtitle_var.set("")
            for d, w in self._patient_section_widgets.items():
                w["status_var"].set("(no patient loaded)")
                w["details_var"].set("")
                w["set_btn"].state(["disabled"])
                w["clear_btn"].state(["disabled"])
                w["view_btn"].state(["disabled"])
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

        state = adata.load_patient_referral_state(info["patient_root"])
        for direction, widgets in self._patient_section_widgets.items():
            entry = state.get(direction) or {}
            aid = (entry.get("attorney_id") or "").strip()
            set_at = (entry.get("set_at") or "").strip()
            widgets["set_btn"].state(["!disabled"])
            if aid:
                rec = adata.find_attorney(aid)
                if rec:
                    widgets["status_var"].set("✓  " + adata.attorney_display_label(rec))
                    widgets["details_var"].set(self._format_attorney_block(rec, set_at))
                    widgets["clear_btn"].state(["!disabled"])
                    widgets["view_btn"].state(["!disabled"])
                else:
                    widgets["status_var"].set("(linked attorney was deleted)")
                    widgets["details_var"].set("")
                    widgets["clear_btn"].state(["!disabled"])
                    widgets["view_btn"].state(["disabled"])
            else:
                widgets["status_var"].set("(not set)")
                widgets["details_var"].set("Click 'Set / Change…' to link this patient to an attorney.")
                widgets["clear_btn"].state(["disabled"])
                widgets["view_btn"].state(["disabled"])

    @staticmethod
    def _format_attorney_block(rec: dict, set_at: str = "") -> str:
        addr_lines = []
        if rec.get("address1"): addr_lines.append(rec["address1"])
        if rec.get("address2"): addr_lines.append(rec["address2"])
        cs = ", ".join(filter(None, [rec.get("city", ""), rec.get("state", "")]))
        if cs or rec.get("zip"):
            addr_lines.append((cs + " " + (rec.get("zip") or "")).strip())
        addr = "\n".join(addr_lines)

        contact_bits = []
        if rec.get("contact_name"):    contact_bits.append(f"Contact: {rec['contact_name']}")
        if rec.get("paralegal_name"):  contact_bits.append(f"Paralegal: {rec['paralegal_name']}")
        if rec.get("case_manager"):    contact_bits.append(f"Case mgr: {rec['case_manager']}")
        contact_line = "    ".join(contact_bits)

        comm_bits = []
        if rec.get("phone"):   comm_bits.append(f"Phone: {rec['phone']}")
        if rec.get("fax"):     comm_bits.append(f"Fax: {rec['fax']}")
        if rec.get("email"):   comm_bits.append(f"Email: {rec['email']}")
        if rec.get("website"): comm_bits.append(f"Web: {rec['website']}")
        comm_line = "    ".join(comm_bits)

        parts = []
        if contact_line:
            parts.append(contact_line)
        if comm_line:
            parts.append(comm_line)
        if addr:
            parts.append(addr)
        if rec.get("notes"):
            parts.append(f"Notes: {rec['notes']}")
        if set_at:
            parts.append(f"Linked: {set_at}")
        return "\n".join(parts) if parts else "(no contact info on file)"

    def _patient_set(self, direction: str):
        info = self._current_patient_info()
        if not info:
            return
        state = adata.load_patient_referral_state(info["patient_root"])
        preselect = (state.get(direction, {}) or {}).get("attorney_id") or ""

        title_map = {
            "from_dol":      "Select the Doctors on Liens attorney",
            "from_attorney": "Select the referring attorney",
            "to_attorney":   "Select the attorney we referred this patient to",
        }
        dlg = AttorneyPickerDialog(self, title=title_map.get(direction, "Select attorney"), preselect_id=preselect)
        self.wait_window(dlg)
        if not dlg.result:
            return

        adata.set_patient_referral(
            patient_root=info["patient_root"],
            patient_id=info.get("patient_id") or "",
            patient_name=info.get("patient_name") or "",
            direction=direction,
            attorney_id=dlg.result.get("id") or "",
            exam_label=info.get("current_exam") or "",
        )
        self._refresh_all()
        self._notify_changed()

    def _patient_clear(self, direction: str):
        info = self._current_patient_info()
        if not info:
            return
        labels = {
            "from_dol": "Doctors on Liens",
            "from_attorney": "Attorney Referred Patient",
            "to_attorney": "We Referred to Attorney",
        }
        if not messagebox.askyesno(
            "Clear referral",
            f"Remove the '{labels.get(direction, direction)}' link for this patient?\n\n"
            "This also removes the referral entry from the stats log.",
            parent=self,
        ):
            return
        adata.clear_patient_referral(
            patient_root=info["patient_root"],
            patient_id=info.get("patient_id") or "",
            direction=direction,
        )
        self._refresh_all()
        self._notify_changed()

    def _patient_edit_linked(self, direction: str):
        info = self._current_patient_info()
        if not info:
            return
        state = adata.load_patient_referral_state(info["patient_root"])
        aid = (state.get(direction, {}) or {}).get("attorney_id") or ""
        rec = adata.find_attorney(aid) if aid else None
        if not rec:
            return
        ed = _AttorneyEditor(self, record=rec)
        self.wait_window(ed)
        if ed.result:
            self._refresh_all()
            self._notify_changed()

    # ---------------------- Tab: Attorneys Directory -----------------------
    def _build_directory_tab(self, parent: ttk.Frame):
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 8))

        ttk.Label(
            top,
            text="Attorneys Directory",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        ttk.Button(top, text="Add Attorney", command=self._dir_add).pack(side="right")
        ttk.Button(top, text="Edit", command=self._dir_edit).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Delete", command=self._dir_delete).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Print PDF…", command=self._dir_print_pdf).pack(side="right", padx=(0, 12))

        search_row = ttk.Frame(parent)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self._dir_search_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self._dir_search_var).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )
        self._dir_search_var.trace_add("write", lambda *_: self._refresh_directory())

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("firm", "attorney", "phone", "email", "city", "state")
        self._dir_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w in [
            ("firm", "Firm", 220),
            ("attorney", "Attorney", 180),
            ("phone", "Phone", 120),
            ("email", "Email", 200),
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

        # Detail panel
        detail = ttk.LabelFrame(parent, text="Details")
        detail.pack(fill="x", pady=(8, 0))
        self._dir_detail_var = tk.StringVar(value="(select an attorney)")
        ttk.Label(
            detail, textvariable=self._dir_detail_var, justify="left", anchor="w",
        ).pack(fill="x", padx=8, pady=8)
        self._dir_tree.bind("<<TreeviewSelect>>", lambda e: self._dir_update_detail())

    def _refresh_directory(self):
        q = (self._dir_search_var.get() or "").strip().lower() if hasattr(self, "_dir_search_var") else ""
        for iid in self._dir_tree.get_children():
            self._dir_tree.delete(iid)
        for rec in adata.list_attorneys_alphabetical():
            blob = " ".join([
                rec.get("firm_name", ""), rec.get("attorney_name", ""),
                rec.get("city", ""), rec.get("state", ""),
                rec.get("phone", ""), rec.get("email", ""),
            ]).lower()
            if q and q not in blob:
                continue
            self._dir_tree.insert(
                "", "end", iid=rec["id"],
                values=(
                    rec.get("firm_name", ""),
                    rec.get("attorney_name", ""),
                    rec.get("phone", ""),
                    rec.get("email", ""),
                    rec.get("city", ""),
                    rec.get("state", ""),
                ),
            )
        self._dir_update_detail()

    def _dir_selected_id(self) -> str | None:
        sel = self._dir_tree.selection()
        return sel[0] if sel else None

    def _dir_update_detail(self):
        aid = self._dir_selected_id()
        if not aid:
            self._dir_detail_var.set("(select an attorney)")
            return
        rec = adata.find_attorney(aid)
        if not rec:
            self._dir_detail_var.set("(record not found)")
            return
        addr_lines = []
        if rec.get("address1"): addr_lines.append(rec["address1"])
        if rec.get("address2"): addr_lines.append(rec["address2"])
        cs = ", ".join(filter(None, [rec.get("city", ""), rec.get("state", "")]))
        if cs or rec.get("zip"):
            addr_lines.append((cs + " " + (rec.get("zip") or "")).strip())
        addr = "\n".join(addr_lines) or "(no address on file)"
        self._dir_detail_var.set(
            f"Firm: {rec.get('firm_name','')}\n"
            f"Attorney: {rec.get('attorney_name','')}\n"
            f"Contact: {rec.get('contact_name','')}    Paralegal: {rec.get('paralegal_name','')}    Case mgr: {rec.get('case_manager','')}\n"
            f"Phone: {rec.get('phone','')}    Fax: {rec.get('fax','')}\n"
            f"Email: {rec.get('email','')}    Website: {rec.get('website','')}\n"
            f"Address:\n{addr}\n"
            f"Notes: {rec.get('notes','')}"
        )

    def _dir_add(self):
        ed = _AttorneyEditor(self, record=None)
        self.wait_window(ed)
        if ed.result:
            self._refresh_all()
            self._regenerate_attorney_list_pdf_silent()

    def _dir_edit(self):
        aid = self._dir_selected_id()
        if not aid:
            messagebox.showinfo("Edit", "Select an attorney first.", parent=self)
            return
        rec = adata.find_attorney(aid)
        if not rec:
            return
        ed = _AttorneyEditor(self, record=rec)
        self.wait_window(ed)
        if ed.result:
            self._refresh_all()
            self._regenerate_attorney_list_pdf_silent()

    def _dir_delete(self):
        aid = self._dir_selected_id()
        if not aid:
            messagebox.showinfo("Delete", "Select an attorney first.", parent=self)
            return
        rec = adata.find_attorney(aid)
        if not rec:
            return
        label = adata.attorney_display_label(rec)
        if not messagebox.askyesno(
            "Delete attorney",
            f"Delete this attorney and ALL referral entries that point to them?\n\n{label}",
            parent=self,
        ):
            return
        adata.delete_attorney(aid)
        self._refresh_all()
        self._regenerate_attorney_list_pdf_silent()

    # ---------------- Attorneys Directory: List of Attorneys PDF -----------
    def _build_attorney_list_pdf(self, *, open_after: bool, show_message: bool):
        """Generate / overwrite the canonical 'List of Attorneys' PDF.

        - Always writes to <DATA_DIR>/exports/attorneys/List_of_Attorneys.pdf
          (single canonical file; never accumulates duplicates).
        - If a patient is currently loaded, also overwrites the same filename
          inside that patient's vault/attorney/ folder so it surfaces in the
          Doc Vault → 'attorney' section.
        Returns the primary path (str) or None on failure.
        """
        try:
            from attorney_list_pdf import (
                build_attorney_list_pdf,
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

        # Pull clinic name from the same field the DoL tab uses (or config).
        try:
            from config import CLINIC_NAME as _CFG_CLINIC
        except Exception:
            _CFG_CLINIC = ""
        clinic_name = ""
        if hasattr(self, "_dol_clinic_name"):
            clinic_name = (self._dol_clinic_name.get() or "").strip()
        if not clinic_name:
            saved = self._read_dol_settings() if hasattr(self, "_read_dol_settings") else {}
            clinic_name = (saved.get("clinic_name") or _CFG_CLINIC or "").strip()

        info = self._current_patient_info()
        patient_root = info.get("patient_root") if info else None
        paths = canonical_pdf_paths(patient_root=patient_root)

        primary = str(paths["primary"])
        try:
            build_attorney_list_pdf(
                primary,
                clinic_name=clinic_name,
                attorneys=adata.list_attorneys_alphabetical(),
            )
        except Exception as e:
            if show_message:
                messagebox.showerror("Print PDF", f"Could not build PDF:\n\n{e}", parent=self)
            return None

        # Mirror to current patient's vault/attorney/ if applicable.
        copied_to_patient = False
        if "patient_copy" in paths:
            try:
                import shutil
                dest = paths["patient_copy"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = str(dest) + ".tmp"
                shutil.copy2(primary, tmp)
                os.replace(tmp, dest)
                copied_to_patient = True
            except Exception:
                copied_to_patient = False

        if open_after:
            try:
                self._open_with_default_app(primary)
            except Exception:
                pass

        if show_message:
            msg = [f"Saved: {primary}"]
            if copied_to_patient:
                msg.append(f"Also filed in: {paths['patient_copy']}")
            messagebox.showinfo("List of Attorneys — PDF", "\n".join(msg), parent=self)

        return primary

    def _dir_print_pdf(self):
        self._build_attorney_list_pdf(open_after=True, show_message=True)

    def _regenerate_attorney_list_pdf_silent(self):
        """Called automatically after add/edit/delete so the same PDF stays
        in sync with the directory. No popups, no auto-open."""
        try:
            self._build_attorney_list_pdf(open_after=False, show_message=False)
        except Exception:
            pass

    # ----------------------- Tab: Doctors on Liens -------------------------
    def _build_dol_tab(self, parent: ttk.Frame):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(
            header,
            text="DOCTORS ON LIENS — NEW PATIENT REFERRAL LOG",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Email: DolReferrals@gmail.com",
            foreground="gray",
        ).pack(anchor="w")

        period_row = ttk.Frame(parent)
        period_row.pack(fill="x", pady=(2, 8))

        months, years = _month_year_choices()
        now = datetime.now()
        self._dol_month = tk.StringVar(value=_MONTH_NAMES[now.month - 1])
        self._dol_year = tk.StringVar(value=str(now.year))

        ttk.Label(period_row, text="Referral Period — Month:").pack(side="left")
        ttk.Combobox(
            period_row, textvariable=self._dol_month, values=months,
            state="readonly", width=12,
        ).pack(side="left", padx=(6, 12))
        ttk.Label(period_row, text="Year:").pack(side="left")
        ttk.Combobox(
            period_row, textvariable=self._dol_year, values=years,
            state="readonly", width=8,
        ).pack(side="left", padx=(6, 12))

        self._dol_period_label = tk.StringVar(value="")
        ttk.Label(
            period_row, textvariable=self._dol_period_label,
            font=("Segoe UI", 10, "italic"),
        ).pack(side="left", padx=(6, 0))

        # --- form-field row (Clinic Name / City) so the printed PDF matches the
        # Doctors on Liens form exactly ---
        clinic_row = ttk.Frame(parent)
        clinic_row.pack(fill="x", pady=(0, 4))

        from config import CLINIC_NAME as _CFG_CLINIC, CLINIC_ADDR as _CFG_ADDR
        saved = self._read_dol_settings()

        self._dol_clinic_name = tk.StringVar(
            value=(saved.get("clinic_name") or _CFG_CLINIC or "").strip()
        )
        self._dol_city = tk.StringVar(
            value=(saved.get("city") or self._guess_city_from_addr(_CFG_ADDR) or "").strip()
        )

        ttk.Label(clinic_row, text="Clinic Name:").pack(side="left")
        ttk.Entry(
            clinic_row, textvariable=self._dol_clinic_name, width=28,
        ).pack(side="left", padx=(6, 12))
        ttk.Label(clinic_row, text="City:").pack(side="left")
        ttk.Entry(
            clinic_row, textvariable=self._dol_city, width=18,
        ).pack(side="left", padx=(6, 12))
        ttk.Button(
            clinic_row, text="Print PDF…",
            command=self._dol_print_pdf,
        ).pack(side="right")

        def _on_change(*_):
            self._refresh_dol()
        self._dol_month.trace_add("write", _on_change)
        self._dol_year.trace_add("write", _on_change)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("num", "patient", "attorney", "address_phone")
        self._dol_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anc in [
            ("num", "#", 50, "center"),
            ("patient", "Patient", 220, "w"),
            ("attorney", "Attorney / Firm Name", 280, "w"),
            ("address_phone", "Address / Phone Number", 360, "w"),
        ]:
            self._dol_tree.heading(c, text=label)
            self._dol_tree.column(c, width=w, anchor=anc)

        sb = ttk.Scrollbar(body, orient="vertical", command=self._dol_tree.yview)
        self._dol_tree.configure(yscrollcommand=sb.set)
        self._dol_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(8, 0))
        self._dol_total_var = tk.StringVar(value="Number of patients: 0")
        ttk.Label(
            footer, textvariable=self._dol_total_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

        ttk.Label(
            footer,
            text="   The 'Print PDF' button generates a one-page form matching the Doctors on Liens template.",
            foreground="gray",
        ).pack(side="left")

    def _refresh_dol(self):
        if not hasattr(self, "_dol_tree"):
            return
        try:
            month = _MONTH_NAMES.index(self._dol_month.get()) + 1
            year = int(self._dol_year.get())
        except Exception:
            return
        self._dol_period_label.set(f"({_month_label(year, month)})")

        for iid in self._dol_tree.get_children():
            self._dol_tree.delete(iid)

        rows = adata.referrals_table_for_period(direction="from_dol", year=year, month=month)
        for i, r in enumerate(rows, start=1):
            addr_phone = " | ".join(filter(None, [r.get("address", ""), r.get("phone", "")]))
            self._dol_tree.insert(
                "", "end",
                values=(i, r.get("patient_name", ""), r.get("attorney_label", ""), addr_phone),
            )
        self._dol_total_var.set(f"Number of patients: {len(rows)}")

    # ----- DoL print/settings helpers --------------------------------------
    @staticmethod
    def _guess_city_from_addr(addr: str) -> str:
        """Best-effort: pull a 'City' substring from a freeform clinic address.
        Tries '<street>, <City>, <ST> <ZIP>' and similar."""
        s = (addr or "").strip()
        if not s:
            return ""
        parts = [p.strip() for p in s.split(",") if p.strip()]
        # Heuristic: if last looks like 'ST ZIP', the one before is the city.
        if len(parts) >= 2:
            last = parts[-1]
            if any(ch.isdigit() for ch in last) and len(last.split()) <= 4:
                return parts[-2]
            return parts[-1]
        return ""

    @staticmethod
    def _dol_settings_path():
        from config import SETTINGS_PATH
        return SETTINGS_PATH

    def _read_dol_settings(self) -> dict:
        import json
        from pathlib import Path
        p = Path(self._dol_settings_path())
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f) or {}
        except Exception:
            return {}
        return (obj.get("dol_referral_log") or {}) if isinstance(obj, dict) else {}

    def _save_dol_settings(self, **kw) -> None:
        import json
        from pathlib import Path
        p = Path(self._dol_settings_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            base = json.load(open(p, "r", encoding="utf-8")) if p.exists() else {}
        except Exception:
            base = {}
        if not isinstance(base, dict):
            base = {}
        cur = base.get("dol_referral_log") or {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update({k: (v or "").strip() for k, v in kw.items()})
        base["dol_referral_log"] = cur
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(base, f, indent=2)
        except Exception:
            pass

    def _dol_print_pdf(self):
        """Build the Doctors on Liens referral log PDF for the selected month
        and (a) save it to the EMR exports folder, (b) copy it into each
        DoL-flagged patient's vault/doctors_on_liens/ folder, (c) open it."""
        try:
            from dol_referral_pdf import (
                build_dol_referral_log_pdf,
                referral_log_filename,
                REPORTLAB_OK,
            )
        except Exception as e:
            messagebox.showerror(
                "Print PDF",
                f"Could not load PDF generator:\n\n{e}",
                parent=self,
            )
            return
        if not REPORTLAB_OK:
            messagebox.showerror(
                "Print PDF",
                "ReportLab is not installed. Install with:\n\npip install reportlab",
                parent=self,
            )
            return

        try:
            month = _MONTH_NAMES.index(self._dol_month.get()) + 1
            year = int(self._dol_year.get())
        except Exception:
            messagebox.showerror("Print PDF", "Invalid month/year.", parent=self)
            return

        clinic_name = (self._dol_clinic_name.get() or "").strip()
        city = (self._dol_city.get() or "").strip()
        self._save_dol_settings(clinic_name=clinic_name, city=city)

        rows_raw = adata.referrals_table_for_period(
            direction="from_dol", year=year, month=month,
        )
        pdf_rows = []
        for r in rows_raw:
            addr_phone_bits = []
            addr = (r.get("address") or "").strip()
            phone = (r.get("phone") or "").strip()
            if addr:
                addr_phone_bits.append(addr)
            if phone:
                addr_phone_bits.append(phone)
            pdf_rows.append({
                "patient_name": r.get("patient_name", ""),
                "attorney_label": r.get("attorney_label", ""),
                "address_phone": " — ".join(addr_phone_bits),
            })

        # Output path under EMR exports
        from paths import exports_dir
        out_dir = exports_dir() / "dol_referrals"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / referral_log_filename(year, month)

        try:
            build_dol_referral_log_pdf(
                str(out_path),
                clinic_name=clinic_name,
                city=city,
                year=year,
                month=month,
                rows=pdf_rows,
            )
        except Exception as e:
            messagebox.showerror("Print PDF", f"Could not build PDF:\n\n{e}", parent=self)
            return

        # File a copy into each DoL patient's vault/doctors_on_liens folder
        copies = self._distribute_dol_pdf_to_patient_vaults(
            pdf_path=str(out_path),
            year=year, month=month,
        )

        # Open the PDF
        try:
            self._open_with_default_app(str(out_path))
        except Exception:
            pass

        msg_lines = [f"Saved: {out_path}"]
        if copies:
            msg_lines.append(f"Filed in {copies} patient vault(s) → 'doctors on liens'.")
        messagebox.showinfo("Doctors on Liens — PDF", "\n".join(msg_lines), parent=self)

    def _distribute_dol_pdf_to_patient_vaults(
        self, *, pdf_path: str, year: int, month: int,
    ) -> int:
        """Copy the PDF into vault/doctors_on_liens/ of every patient that
        had at least one 'from_dol' referral in (year, month).

        Returns the number of patient vaults touched."""
        import shutil
        from utils import find_patient_folder_by_id
        from config import PATIENTS_ID_ROOT
        from pathlib import Path

        seen_pids: set[str] = set()
        for r in adata.list_referrals(direction="from_dol", year=year, month=month):
            pid = (r.get("patient_id") or "").strip()
            if pid:
                seen_pids.add(pid)

        copies = 0
        for pid in seen_pids:
            try:
                pr = find_patient_folder_by_id(Path(PATIENTS_ID_ROOT), pid)
            except Exception:
                pr = None
            if not pr:
                continue
            dest_dir = Path(pr) / "vault" / "doctors_on_liens"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / os.path.basename(pdf_path)
            try:
                tmp = str(dest) + ".tmp"
                shutil.copy2(pdf_path, tmp)
                os.replace(tmp, dest)
                copies += 1
            except Exception:
                continue
        return copies

    @staticmethod
    def _open_with_default_app(path: str) -> None:
        import sys, subprocess
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ------------------ Tab: Attorney Referrals (Incoming) -----------------
    def _build_incoming_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Attorney Referrals (NOT through Doctors on Liens)",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text="Counts of patients each attorney has directly referred to our clinic.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        self._att_in_filter = self._build_period_filter(parent, on_change=self._refresh_incoming)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("attorney", "count")
        self._att_in_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self._att_in_tree.heading("attorney", text="Attorney / Firm")
        self._att_in_tree.heading("count", text="Patients Referred")
        self._att_in_tree.column("attorney", width=420, anchor="w")
        self._att_in_tree.column("count", width=140, anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=self._att_in_tree.yview)
        self._att_in_tree.configure(yscrollcommand=sb.set)
        self._att_in_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._att_in_total_var = tk.StringVar(value="Total: 0")
        ttk.Label(
            parent, textvariable=self._att_in_total_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(8, 0))

    def _refresh_incoming(self):
        if not hasattr(self, "_att_in_tree"):
            return
        year, month = self._read_period_filter(self._att_in_filter)
        for iid in self._att_in_tree.get_children():
            self._att_in_tree.delete(iid)

        counts = adata.count_referrals_by_attorney(direction="from_attorney", year=year, month=month)
        attorneys = {a["id"]: a for a in adata.list_attorneys()}
        rows = []
        for aid, n in counts.items():
            label = adata.attorney_display_label(attorneys.get(aid)) if aid in attorneys else "(unknown attorney)"
            rows.append((label, n))
        rows.sort(key=lambda x: (-x[1], x[0].lower()))
        total = 0
        for label, n in rows:
            self._att_in_tree.insert("", "end", values=(label, n))
            total += n
        self._att_in_total_var.set(f"Total: {total}")

    # ------------------ Tab: Clinic Referrals (Outgoing) -------------------
    def _build_outgoing_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Clinic Referrals to Attorneys",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text="Counts of patients we (the clinic) referred OUT to each attorney.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        self._att_out_filter = self._build_period_filter(parent, on_change=self._refresh_outgoing)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("attorney", "count")
        self._att_out_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        self._att_out_tree.heading("attorney", text="Attorney / Firm")
        self._att_out_tree.heading("count", text="Patients We Referred")
        self._att_out_tree.column("attorney", width=420, anchor="w")
        self._att_out_tree.column("count", width=160, anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=self._att_out_tree.yview)
        self._att_out_tree.configure(yscrollcommand=sb.set)
        self._att_out_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._att_out_total_var = tk.StringVar(value="Total: 0")
        ttk.Label(
            parent, textvariable=self._att_out_total_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(8, 0))

    def _refresh_outgoing(self):
        if not hasattr(self, "_att_out_tree"):
            return
        year, month = self._read_period_filter(self._att_out_filter)
        for iid in self._att_out_tree.get_children():
            self._att_out_tree.delete(iid)

        counts = adata.count_referrals_by_attorney(direction="to_attorney", year=year, month=month)
        attorneys = {a["id"]: a for a in adata.list_attorneys()}
        rows = []
        for aid, n in counts.items():
            label = adata.attorney_display_label(attorneys.get(aid)) if aid in attorneys else "(unknown attorney)"
            rows.append((label, n))
        rows.sort(key=lambda x: (-x[1], x[0].lower()))
        total = 0
        for label, n in rows:
            self._att_out_tree.insert("", "end", values=(label, n))
            total += n
        self._att_out_total_var.set(f"Total: {total}")

    # --------------------------- Tab: Master Stats -------------------------
    def _build_master_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Master Referral Stats",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text="All three categories combined, broken down by attorney.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        self._master_filter = self._build_period_filter(parent, on_change=self._refresh_master)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        cols = ("attorney", "from_dol", "from_attorney", "to_attorney", "total")
        self._master_tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, label, w, anc in [
            ("attorney", "Attorney / Firm", 320, "w"),
            ("from_dol", "From DoL", 110, "center"),
            ("from_attorney", "From Attorney", 130, "center"),
            ("to_attorney", "To Attorney", 110, "center"),
            ("total", "Total", 90, "center"),
        ]:
            self._master_tree.heading(c, text=label)
            self._master_tree.column(c, width=w, anchor=anc)
        sb = ttk.Scrollbar(body, orient="vertical", command=self._master_tree.yview)
        self._master_tree.configure(yscrollcommand=sb.set)
        self._master_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        totals = ttk.Frame(parent)
        totals.pack(fill="x", pady=(8, 0))
        self._master_totals_var = tk.StringVar(value="")
        ttk.Label(
            totals, textvariable=self._master_totals_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

    def _refresh_master(self):
        if not hasattr(self, "_master_tree"):
            return
        year, month = self._read_period_filter(self._master_filter)

        for iid in self._master_tree.get_children():
            self._master_tree.delete(iid)

        rows = adata.per_attorney_summary(year=year, month=month)
        rows.sort(key=lambda r: -r["total"])
        sum_dol = sum_in = sum_out = sum_all = 0
        for r in rows:
            self._master_tree.insert(
                "", "end",
                values=(r["label"], r["from_dol"], r["from_attorney"], r["to_attorney"], r["total"]),
            )
            sum_dol += r["from_dol"]
            sum_in += r["from_attorney"]
            sum_out += r["to_attorney"]
            sum_all += r["total"]

        # If there are referrals pointing at deleted attorneys, surface them too.
        for d in adata.REFERRAL_DIRECTIONS:
            for ref in adata.list_referrals(direction=d, year=year, month=month):
                if not adata.find_attorney(ref.get("attorney_id") or ""):
                    pass  # already counted in sums above only if attorney exists

        self._master_totals_var.set(
            f"Totals — From DoL: {sum_dol}    From Attorney: {sum_in}    "
            f"To Attorney: {sum_out}    GRAND TOTAL: {sum_all}"
        )

    # ------------------------- Tab: Alphabetical List ----------------------
    def _build_alpha_tab(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="All Attorneys — Alphabetical",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)

        self._alpha_text = tk.Text(wrap, wrap="word", state="disabled")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._alpha_text.yview)
        self._alpha_text.configure(yscrollcommand=sb.set)
        self._alpha_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # styling
        self._alpha_text.tag_configure("hdr", font=("Segoe UI", 10, "bold"))
        self._alpha_text.tag_configure("dim", foreground="gray")

    def _refresh_alpha(self):
        if not hasattr(self, "_alpha_text"):
            return
        attorneys = adata.list_attorneys_alphabetical()
        t = self._alpha_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not attorneys:
            t.insert("end", "(no attorneys yet — add one from the Attorneys Directory tab)\n", ("dim",))
        else:
            t.insert("end", f"Total attorneys on file: {len(attorneys)}\n\n", ("hdr",))
            for i, rec in enumerate(attorneys, start=1):
                line = f"{i:>3}.  {adata.attorney_display_label(rec)}\n"
                t.insert("end", line)
                bits = []
                if rec.get("phone"): bits.append(f"Phone: {rec['phone']}")
                if rec.get("email"): bits.append(f"Email: {rec['email']}")
                cs = ", ".join(filter(None, [rec.get("city", ""), rec.get("state", "")]))
                if cs: bits.append(cs)
                if bits:
                    t.insert("end", "      " + "   ".join(bits) + "\n", ("dim",))
        t.configure(state="disabled")

    # ------------------------- helpers: period filter ----------------------
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

        return {
            "scope": scope_var,
            "month": month_var,
            "year": year_var,
        }

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
