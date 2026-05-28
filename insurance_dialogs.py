# insurance_dialogs.py — Insurance billing dialogs (Phase 2–3).
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from insurance_billing_storage import (
    add_authorization,
    load_carc_rarc_codes,
    load_insurance_authorizations,
    update_authorization,
)
from insurance_engine import (
    appeal_claim,
    collect_insurance_copay,
    create_correction_or_void_claim,
    insurance_copay_outstanding_for_claim,
    suggest_auth_number_for_cpt,
    update_claim_line_auth_numbers,
)


def _make_modal(top: tk.Toplevel, parent: tk.Misc) -> None:
    top.transient(parent.winfo_toplevel())
    top.grab_set()
    top.focus_force()


class InsurancePostPayerDialog(tk.Toplevel):
    """Line-level payer remittance with CARC per line (Phase 3)."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        claim_state: dict,
        default_payer_paid: float = 0.0,
        on_complete: callable | None = None,
    ):
        super().__init__(parent)
        self.claim_state = claim_state
        self.on_complete = on_complete
        self.title("Post payer payment — line detail")
        self.geometry("760x520")
        self.minsize(640, 420)
        _make_modal(self, parent)

        snap = claim_state.get("snapshot") or {}
        self._lines = list(snap.get("lines") or [])
        carc_codes = list((load_carc_rarc_codes().get("carc") or {}).keys())
        if "45" not in carc_codes:
            carc_codes.append("45")
        if "197" not in carc_codes:
            carc_codes.append("197")
        self._carc_values = sorted(carc_codes, key=lambda x: (len(x), x))

        top = tk.Frame(self, padx=10, pady=8)
        top.pack(fill="x")
        from datetime import datetime

        tk.Label(top, text="Posting date:").pack(side="left")
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        tk.Entry(top, textvariable=self.date_var, width=12).pack(side="left", padx=(4, 12))
        tk.Label(top, text="Deposit ref:").pack(side="left")
        self.ref_var = tk.StringVar(value="")
        tk.Entry(top, textvariable=self.ref_var, width=18).pack(side="left", padx=4)
        self.full_denial_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            top,
            text="Full denial (all lines)",
            variable=self.full_denial_var,
            command=self._apply_full_denial,
        ).pack(side="right")

        cols = ("cpt", "charged", "allowed", "payer", "patient", "denied", "carc")
        grid_wrap = tk.Frame(self)
        grid_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.tree = ttk.Treeview(grid_wrap, columns=cols, show="headings", height=8)
        for col, title, w in [
            ("cpt", "CPT", 70),
            ("charged", "Charged", 80),
            ("allowed", "Allowed", 80),
            ("payer", "Payer paid", 80),
            ("patient", "Pat resp", 80),
            ("denied", "Denied", 50),
            ("carc", "CARC", 60),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(grid_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        self._row_vars: dict[str, dict] = {}
        total_charged = sum(float(ln.get("charge") or 0) for ln in self._lines) or 1.0
        ratio = float(default_payer_paid or 0) / total_charged if total_charged else 0.0
        for ln in self._lines:
            lid = str(ln.get("line_id") or "")
            charged = round(float(ln.get("charge") or 0), 2)
            payer_guess = round(charged * ratio, 2)
            allowed_guess = payer_guess
            self._row_vars[lid] = {
                "allowed": tk.StringVar(value=f"{allowed_guess:.2f}"),
                "payer": tk.StringVar(value=f"{payer_guess:.2f}"),
                "patient": tk.StringVar(value="0.00"),
                "denied": tk.BooleanVar(value=False),
                "carc": tk.StringVar(value="197"),
            }
            self.tree.insert(
                "",
                "end",
                iid=lid,
                values=(
                    ln.get("cpt") or "",
                    f"{charged:.2f}",
                    f"{allowed_guess:.2f}",
                    f"{payer_guess:.2f}",
                    "0.00",
                    "",
                    "",
                ),
            )
        self.tree.bind("<Double-Button-1>", self._edit_row)

        hint = tk.Label(
            self,
            text="Double-click a line to edit allowed / payer / patient / denial CARC.",
            padx=10,
        )
        hint.pack(anchor="w")

        btns = tk.Frame(self, padx=10, pady=10)
        btns.pack(fill="x")
        tk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btns, text="Save posting", command=self._save).pack(side="right")

    def _apply_full_denial(self) -> None:
        if not self.full_denial_var.get():
            return
        for lid, vars_ in self._row_vars.items():
            vars_["payer"].set("0.00")
            vars_["patient"].set("0.00")
            vars_["allowed"].set("0.00")
            vars_["denied"].set(True)
            vars_["carc"].set("197")

    def _edit_row(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        lid = str(sel[0])
        vars_ = self._row_vars.get(lid)
        if not vars_:
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Line {lid}")
        dlg.transient(self)
        dlg.grab_set()
        body = tk.Frame(dlg, padx=12, pady=12)
        body.pack()
        for i, (label, key) in enumerate(
            [
                ("Allowed ($)", "allowed"),
                ("Payer paid ($)", "payer"),
                ("Patient resp ($)", "patient"),
            ]
        ):
            tk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=3)
            tk.Entry(body, textvariable=vars_[key], width=14).grid(row=i, column=1, pady=3)
        tk.Checkbutton(body, text="Line denied", variable=vars_["denied"]).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=4
        )
        tk.Label(body, text="CARC").grid(row=4, column=0, sticky="w")
        ttk.Combobox(
            body,
            textvariable=vars_["carc"],
            values=self._carc_values,
            width=10,
        ).grid(row=4, column=1, sticky="w")

        def _ok() -> None:
            ln = next((x for x in self._lines if str(x.get("line_id")) == lid), {})
            charged = float(ln.get("charge") or 0)
            self.tree.item(
                lid,
                values=(
                    ln.get("cpt") or "",
                    f"{charged:.2f}",
                    vars_["allowed"].get(),
                    vars_["payer"].get(),
                    vars_["patient"].get(),
                    "Y" if vars_["denied"].get() else "",
                    vars_["carc"].get() if vars_["denied"].get() else "",
                ),
            )
            dlg.destroy()

        tk.Button(body, text="OK", command=_ok).grid(row=5, column=1, sticky="e", pady=(8, 0))

    def _build_line_postings(self) -> list[dict]:
        out: list[dict] = []
        for ln in self._lines:
            lid = str(ln.get("line_id") or "")
            vars_ = self._row_vars.get(lid) or {}
            charged = round(float(ln.get("charge") or 0), 2)
            try:
                allowed = round(float(vars_.get("allowed", tk.StringVar(value="0")).get() or 0), 2)
                payer = round(float(vars_.get("payer", tk.StringVar(value="0")).get() or 0), 2)
                patient = round(float(vars_.get("patient", tk.StringVar(value="0")).get() or 0), 2)
            except (ValueError, AttributeError):
                raise ValueError(f"Invalid amounts on line {lid}.")
            denied = bool(vars_.get("denied", tk.BooleanVar(value=False)).get())
            carc = (vars_.get("carc", tk.StringVar(value="")).get() or "").strip()
            adjustments = []
            if denied and carc:
                adjustments.append({"type": "denial", "carc": carc, "amount": -charged})
            elif allowed < charged - 0.001:
                adjustments.append({"type": "contractual", "carc": "45", "amount": round(allowed - charged, 2)})
            out.append(
                {
                    "line_id": lid,
                    "charged": charged,
                    "allowed": allowed,
                    "payer_paid": payer,
                    "patient_resp": patient,
                    "adjustments": adjustments,
                    "denial_carc": carc if denied else None,
                    "remark_rarc": None,
                }
            )
        return out

    def _save(self) -> None:
        try:
            line_postings = self._build_line_postings()
        except ValueError as e:
            messagebox.showerror("Post payer", str(e), parent=self)
            return
        totals = {
            "payer_paid": round(sum(float(x["payer_paid"]) for x in line_postings), 2),
            "patient_resp": round(sum(float(x["patient_resp"]) for x in line_postings), 2),
        }
        payload = {
            "payer_paid": totals["payer_paid"],
            "patient_resp": totals["patient_resp"],
            "posting_date": (self.date_var.get() or "").strip(),
            "deposit_ref": (self.ref_var.get() or "").strip(),
            "denial_carc": "",
            "line_postings": line_postings,
        }
        if self.full_denial_var.get():
            payload["denial_carc"] = "197"
        if self.on_complete:
            self.on_complete(payload)
        self.destroy()


class InsuranceAuthorizationDialog(tk.Toplevel):
    """Manage prior authorizations for the active patient."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        patient_id: str,
        recorded_by: str = "",
        on_saved: callable | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.patient_id = patient_id
        self.recorded_by = recorded_by
        self.on_saved = on_saved
        self.title("Insurance authorizations")
        self.geometry("720x480")
        _make_modal(self, parent)

        cols = ("auth", "payer", "effective", "expires", "units", "used", "cpts")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        for col, title, w in [
            ("auth", "Auth #", 100),
            ("payer", "Payer", 80),
            ("effective", "From", 90),
            ("expires", "To", 90),
            ("units", "Units", 60),
            ("used", "Used", 50),
            ("cpts", "CPTs", 200),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = tk.Frame(self, padx=10)
        form.pack(fill="x")
        self.auth_var = tk.StringVar()
        self.payer_var = tk.StringVar()
        self.eff_var = tk.StringVar()
        self.exp_var = tk.StringVar()
        self.units_var = tk.StringVar(value="0")
        self.cpts_var = tk.StringVar()
        self._auth_id = ""
        for i, (lbl, var) in enumerate(
            [
                ("Auth #", self.auth_var),
                ("Payer ID", self.payer_var),
                ("Effective", self.eff_var),
                ("Expires", self.exp_var),
                ("Units approved", self.units_var),
                ("Allowed CPTs (comma)", self.cpts_var),
            ]
        ):
            tk.Label(form, text=lbl).grid(row=i, column=0, sticky="w", pady=2)
            tk.Entry(form, textvariable=var, width=40).grid(row=i, column=1, sticky="w", pady=2)

        btns = tk.Frame(self, padx=10, pady=10)
        btns.pack(fill="x")
        tk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        tk.Button(btns, text="Save", command=self._save).pack(side="right", padx=6)
        tk.Button(btns, text="New", command=self._clear_form).pack(side="right", padx=6)
        self._reload()

    def _reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = load_insurance_authorizations(self.patient_root, patient_id=self.patient_id).get(
            "authorizations"
        ) or []
        for a in rows:
            iid = a.get("auth_id") or ""
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    a.get("auth_number") or "",
                    a.get("payer_id") or "",
                    a.get("effective_date") or "",
                    a.get("expiration_date") or "",
                    a.get("total_units_approved") or 0,
                    a.get("units_used") or 0,
                    ", ".join(a.get("allowed_cpts") or []),
                ),
            )

    def _on_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = str(sel[0])
        rows = load_insurance_authorizations(self.patient_root).get("authorizations") or []
        a = next((x for x in rows if (x.get("auth_id") or "") == iid), None)
        if not a:
            return
        self._auth_id = iid
        self.auth_var.set(a.get("auth_number") or "")
        self.payer_var.set(a.get("payer_id") or "")
        self.eff_var.set(a.get("effective_date") or "")
        self.exp_var.set(a.get("expiration_date") or "")
        self.units_var.set(str(a.get("total_units_approved") or 0))
        self.cpts_var.set(", ".join(a.get("allowed_cpts") or []))

    def _clear_form(self) -> None:
        self._auth_id = ""
        self.auth_var.set("")
        self.payer_var.set("")
        self.eff_var.set("")
        self.exp_var.set("")
        self.units_var.set("0")
        self.cpts_var.set("")

    def _parse_cpts(self) -> list[str]:
        return [c.strip() for c in (self.cpts_var.get() or "").replace(";", ",").split(",") if c.strip()]

    def _save(self) -> None:
        auth_no = (self.auth_var.get() or "").strip()
        if not auth_no:
            messagebox.showerror("Authorizations", "Auth number is required.", parent=self)
            return
        try:
            units = int(self.units_var.get() or 0)
        except ValueError:
            messagebox.showerror("Authorizations", "Units must be a number.", parent=self)
            return
        cpts = self._parse_cpts()
        if self._auth_id:
            update_authorization(
                self.patient_root,
                auth_id=self._auth_id,
                patient_id=self.patient_id,
                auth_number=auth_no,
                payer_id=(self.payer_var.get() or "").strip(),
                effective_date=(self.eff_var.get() or "").strip(),
                expiration_date=(self.exp_var.get() or "").strip(),
                total_units_approved=units,
                allowed_cpts=cpts,
            )
        else:
            add_authorization(
                self.patient_root,
                patient_id=self.patient_id,
                auth_number=auth_no,
                payer_id=(self.payer_var.get() or "").strip(),
                effective_date=(self.eff_var.get() or "").strip(),
                expiration_date=(self.exp_var.get() or "").strip(),
                allowed_cpts=cpts,
                total_units_approved=units,
                recorded_by=self.recorded_by,
            )
        self._reload()
        if self.on_saved:
            self.on_saved()
        messagebox.showinfo("Authorizations", "Saved.", parent=self)


class InsuranceClaimAuthDialog(tk.Toplevel):
    """Attach authorization numbers to claim lines before Ready."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        claim_state: dict,
        recorded_by: str = "",
        on_saved: callable | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.claim_state = claim_state
        self.recorded_by = recorded_by
        self.on_saved = on_saved
        self.title("Claim line authorizations")
        self.geometry("520x360")
        _make_modal(self, parent)

        snap = claim_state.get("snapshot") or {}
        pol = snap.get("policy_snapshot") or {}
        payer_id = pol.get("carrier_id") or claim_state.get("payer_id") or ""

        tk.Label(
            self,
            text="Set auth # for each line. Required CPTs come from the insurance catalog plan.",
            wraplength=480,
            justify="left",
            padx=10,
            pady=8,
        ).pack(anchor="w")

        auths = load_insurance_authorizations(patient_root).get("authorizations") or []
        auth_choices = [""] + [
            (a.get("auth_number") or "")
            for a in auths
            if (a.get("status") or "").lower() == "active"
        ]

        self._vars: dict[str, tk.StringVar] = {}
        grid = tk.Frame(self, padx=10)
        grid.pack(fill="both", expand=True)
        for ln in snap.get("lines") or []:
            lid = str(ln.get("line_id") or "")
            cpt = ln.get("cpt") or ""
            row = tk.Frame(grid)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{cpt}", width=10, anchor="w").pack(side="left")
            cur = (ln.get("auth_number") or "").strip()
            if not cur:
                cur = suggest_auth_number_for_cpt(patient_root, cpt, payer_id=payer_id)
            var = tk.StringVar(value=cur)
            self._vars[lid] = var
            cb = ttk.Combobox(row, textvariable=var, values=auth_choices, width=24)
            cb.pack(side="left", padx=8)

        btns = tk.Frame(self, padx=10, pady=10)
        btns.pack(fill="x")
        tk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btns, text="Save", command=self._save).pack(side="right")

    def _save(self) -> None:
        cid = self.claim_state.get("claim_id") or ""
        auth_map = {lid: (v.get() or "").strip() for lid, v in self._vars.items()}
        try:
            update_claim_line_auth_numbers(
                patient_root=self.patient_root,
                claim_id=cid,
                auth_by_line_id=auth_map,
                recorded_by=self.recorded_by,
            )
        except Exception as e:
            messagebox.showerror("Claim auth", str(e), parent=self)
            return
        if self.on_saved:
            self.on_saved()
        self.destroy()


class InsuranceCopayCheckoutDialog(tk.Toplevel):
    """Collect insurance EOB patient responsibility without posting full cash fees."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        claim_state: dict,
        outstanding: float,
        visit_already_posted: bool = False,
        recorded_by: str = "",
        on_complete: callable | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.claim_state = claim_state
        self.outstanding = round(float(outstanding), 2)
        self.visit_already_posted = visit_already_posted
        self.recorded_by = recorded_by or ""
        self.on_complete = on_complete
        self.title("Collect insurance copay")
        self.geometry("480x340")
        _make_modal(self, parent)

        snap = claim_state.get("snapshot") or {}
        pol = snap.get("policy_snapshot") or {}
        body = tk.Frame(self, padx=14, pady=14)
        body.pack(fill="both", expand=True)

        explain = (
            f"Payer assigned ${self.outstanding:,.2f} patient responsibility on this claim.\n"
            f"Payer: {pol.get('carrier_name') or '—'}  ·  DOS: {snap.get('date_of_service') or '—'}"
        )
        if visit_already_posted:
            explain += (
                "\n\nThis visit is already on the cash ledger. "
                "Only the copay amount below will be recorded as a payment "
                "(not the full visit cash balance)."
            )
        else:
            explain += (
                "\n\nOnly the copay amount will be posted to cash "
                "(not the full visit fee schedule)."
            )
        tk.Label(body, text=explain, justify="left", wraplength=440).pack(anchor="w", pady=(0, 12))

        grid = tk.Frame(body)
        grid.pack(fill="x")
        tk.Label(grid, text="Amount ($):").grid(row=0, column=0, sticky="w", pady=4)
        self.amt_var = tk.StringVar(value=f"{self.outstanding:.2f}")
        tk.Entry(grid, textvariable=self.amt_var, width=14).grid(row=0, column=1, sticky="w")

        tk.Label(grid, text="Method:").grid(row=1, column=0, sticky="w", pady=4)
        self.method_var = tk.StringVar(value="card")
        ttk.Combobox(
            grid,
            textvariable=self.method_var,
            values=["cash", "card", "check", "other"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w")

        from datetime import datetime

        tk.Label(grid, text="Payment date:").grid(row=2, column=0, sticky="w", pady=4)
        self.date_var = tk.StringVar(value=datetime.now().strftime("%m/%d/%Y"))
        tk.Entry(grid, textvariable=self.date_var, width=14).grid(row=2, column=1, sticky="w")

        btns = tk.Frame(body)
        btns.pack(fill="x", pady=(16, 0))
        tk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btns, text="Collect copay", command=self._save).pack(side="right")

    def _save(self) -> None:
        try:
            amt = float(self.amt_var.get() or 0)
        except ValueError:
            messagebox.showerror("Copay", "Enter a valid dollar amount.", parent=self)
            return
        cid = self.claim_state.get("claim_id") or ""
        try:
            result = collect_insurance_copay(
                patient_root=self.patient_root,
                claim_id=cid,
                amount=amt,
                method=(self.method_var.get() or "cash").strip(),
                payment_date=(self.date_var.get() or "").strip(),
                recorded_by=self.recorded_by,
            )
        except Exception as e:
            messagebox.showerror("Copay", str(e), parent=self)
            return
        if self.on_complete:
            self.on_complete(result)
        self.destroy()


def open_insurance_copay_checkout(
    parent: tk.Misc,
    *,
    patient_root: str,
    claim_state: dict,
    recorded_by: str = "",
    on_complete: callable | None = None,
) -> None:
    cid = claim_state.get("claim_id") or ""
    outstanding = insurance_copay_outstanding_for_claim(patient_root, cid)
    if outstanding <= 0.01:
        messagebox.showinfo(
            "Insurance copay",
            "No patient responsibility is outstanding on this claim.",
            parent=parent,
        )
        return
    from billing_ledger import is_encounter_posted

    snap = claim_state.get("snapshot") or {}
    exam_path = (snap.get("encounter_snapshot") or {}).get("exam_path") or ""
    visit_posted = bool(exam_path and is_encounter_posted(patient_root, exam_path))
    InsuranceCopayCheckoutDialog(
        parent,
        patient_root=patient_root,
        claim_state=claim_state,
        outstanding=outstanding,
        visit_already_posted=visit_posted,
        recorded_by=recorded_by,
        on_complete=on_complete,
    )


class InsuranceCorrectionDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, claim_id: str, on_complete: callable | None = None):
        super().__init__(parent)
        self.claim_id = claim_id
        self.on_complete = on_complete
        self.title("Correction / void claim")
        self.geometry("440x220")
        _make_modal(self, parent)

        body = tk.Frame(self, padx=12, pady=12)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text=f"Create a follow-up claim from:\n{claim_id}",
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="Claim frequency code:").pack(anchor="w")
        self.freq_var = tk.StringVar(value="7")
        fr = tk.Frame(body)
        fr.pack(anchor="w", pady=4)
        ttk.Radiobutton(fr, text="7 — Replacement / correction", variable=self.freq_var, value="7").pack(anchor="w")
        ttk.Radiobutton(fr, text="8 — Void of prior claim", variable=self.freq_var, value="8").pack(anchor="w")

        self.void_orig_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            body,
            text="Void original claim when using freq 8",
            variable=self.void_orig_var,
        ).pack(anchor="w", pady=(8, 0))

        btns = tk.Frame(body)
        btns.pack(fill="x", pady=(16, 0))
        tk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btns, text="Create", command=self._create).pack(side="right")

    def _create(self) -> None:
        if self.on_complete:
            self.on_complete(
                {
                    "frequency_code": self.freq_var.get(),
                    "void_original": bool(self.void_orig_var.get()),
                }
            )
        self.destroy()


class InsuranceDenialQueueDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        rows: list[dict],
        on_appeal: callable | None = None,
        on_mark_denied: callable | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.rows = rows
        self.on_appeal = on_appeal
        self.on_mark_denied = on_mark_denied
        self.title("Denial / appeal queue")
        self.geometry("720x400")
        _make_modal(self, parent)

        tk.Label(
            self,
            text="Denied, rejected, and appealed claims needing follow-up.",
            padx=10,
            pady=8,
        ).pack(anchor="w")

        cols = ("claim", "status", "payer", "dos", "patient_resp")
        tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for col, title, w in [
            ("claim", "Claim ID", 180),
            ("status", "Status", 100),
            ("payer", "Payer", 140),
            ("dos", "DOS", 90),
            ("patient_resp", "Pat resp", 90),
        ]:
            tree.heading(col, text=title)
            tree.column(col, width=w)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.tree = tree
        for row in rows:
            tree.insert(
                "",
                "end",
                iid=row.get("claim_id") or "",
                text=row.get("claim_id") or "",
                values=(
                    row.get("claim_id") or "",
                    row.get("status") or "",
                    row.get("payer_name") or "",
                    row.get("dos") or "",
                    f"${float(row.get('patient_resp') or 0):,.2f}",
                ),
            )

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        tk.Button(btns, text="Mark denied", command=lambda: self._action("denied")).pack(side="right", padx=6)
        tk.Button(btns, text="Mark appealed", command=lambda: self._action("appealed")).pack(side="right", padx=6)

    def _selected_claim_id(self) -> str:
        sel = self.tree.selection()
        return str(sel[0]) if sel else ""

    def _action(self, action: str) -> None:
        cid = self._selected_claim_id()
        if not cid:
            messagebox.showinfo("Denial queue", "Select a claim row first.", parent=self)
            return
        if action == "appealed" and self.on_appeal:
            self.on_appeal(cid)
        elif action == "denied" and self.on_mark_denied:
            self.on_mark_denied(cid)


class InsuranceArReportDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, report_text: str, patient_name: str = ""):
        super().__init__(parent)
        title = "Insurance A/R aging"
        if patient_name:
            title = f"{title} — {patient_name}"
        self.title(title)
        self.geometry("640x480")
        _make_modal(self, parent)

        txt = tk.Text(self, wrap="word", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", report_text or "")
        txt.configure(state="disabled")
        tk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))
