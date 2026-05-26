# package_dialogs.py — Tkinter Toplevel dialogs for the Package deals feature.
#
# Dialogs:
#   CatalogEditorDialog      — clinic-wide CRUD for package templates
#   SellPackageDialog        — sell a catalog template OR create an ad-hoc package
#   RedeemPromptDialog       — per-line redemption checkbox at Post-cash time (Gap A)
#   RefundPackageDialog      — pro-rata refund with both strategies side-by-side (Gap B)
#   CancelPackageDialog      — cancel without refund (forfeit) — requires reason memo
#   PackageDetailDialog      — read-only inspector of one package's events
#
# All dialogs are passive: they collect user input, validate it, and invoke a
# caller-supplied on_save callback. Persistence happens in package_storage /
# billing_ledger so business rules stay testable.

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from billing_storage import load_fee_schedules
from scrollframe import ScrollFrame
from service_catalog import get_active_items
from package_engine import (
    REFUND_STRATEGY_RETAIL_AUDIT,
    REFUND_STRATEGY_TRUE_PRORATA,
    add_months_iso,
    compute_package_state,
    compute_refund_quote,
    status_label,
    today_str,
)
from package_storage import (
    EVENT_CANCELLATION,
    EVENT_CONTRACT_FILED,
    EVENT_PAYMENT,
    EVENT_PURCHASE,
    EVENT_REFUND,
    all_events_for_package,
    append_event,
    find_purchase_event,
    list_catalog_templates,
    load_package_log,
    new_package_instance_id,
    post_encounter_to_package,
    record_package_payment,
    set_catalog_template_active,
    upsert_catalog_template,
)

from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_GREEN,
    COLOR_MUTED,
    COLOR_RED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    FONT_SMALL,
    FONT_TITLE,
)


# ---------------------------------------------------------------------------
# Small reusable helpers
# ---------------------------------------------------------------------------

def _parse_float(s: str) -> float | None:
    try:
        return float((s or "0").replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _parse_int(s: str) -> int | None:
    try:
        return int((s or "0").strip())
    except ValueError:
        return None


def _list_active_cpt_choices() -> list[tuple[str, str]]:
    """All active CPTs in the clinic catalog formatted as (cpt, 'CPT — short label')."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for cat in ("cmt", "em", "therapy"):
        for it in get_active_items(cat):
            cpt = str(it.get("cpt") or "").strip()
            if not cpt or cpt in seen or cpt == "0000":
                continue
            seen.add(cpt)
            label = (it.get("short_description") or "").strip()
            out.append((cpt, f"{cpt} — {label}" if label else cpt))
    out.sort(key=lambda x: x[0])
    return out


def _cash_fee_for(cpt: str) -> float:
    schedules = load_fee_schedules()
    return float((schedules.get("cash") or {}).get(cpt, 0.0))


def _make_modal(top: tk.Toplevel, *, focus_widget: tk.Widget | None = None) -> None:
    """
    Reliable modal setup that works across platforms:
      1. Wait for the window to become visible (avoids grab_set TclError on
         some Windows/WMs when called before the window is realized).
      2. Grab focus.
      3. Lift above the parent and focus the first writable widget.
    Safe to call any time during __init__ (best near the end).
    """
    def _go():
        try:
            top.wait_visibility()
        except tk.TclError:
            return
        try:
            top.grab_set()
        except tk.TclError:
            pass
        try:
            top.lift()
            top.focus_force()
        except tk.TclError:
            pass
        if focus_widget is not None:
            try:
                focus_widget.focus_set()
                # Select all text in Entry so typing replaces the default value.
                if hasattr(focus_widget, "select_range"):
                    focus_widget.select_range(0, "end")
            except tk.TclError:
                pass

    top.after(50, _go)


# ---------------------------------------------------------------------------
# Catalog editor (clinic-wide package templates)
# ---------------------------------------------------------------------------

class CatalogEditorDialog(tk.Toplevel):
    """List/edit clinic-wide package templates (parallel to FeeScheduleDialog)."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Package catalog")
        self.geometry("860x560")
        self.minsize(720, 480)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_BG_APP)
        # Catalog editor is non-modal (you might want both this and the template
        # editor open at once), but we still lift it above the parent.
        self.after(50, lambda: (self.lift(), self.focus_force()))

        head = tk.Frame(self, bg=COLOR_BG_APP)
        head.pack(fill="x", padx=12, pady=10)
        tk.Label(
            head,
            text="Clinic package catalog",
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_TITLE,
        ).pack(side="left")
        tk.Label(
            head,
            text="  Templates appear in Sell Package dialog. Discounts must be traceable to clinic fee schedule.",
            bg=COLOR_BG_APP,
            fg=COLOR_MUTED,
            font=FONT_SMALL,
        ).pack(side="left")

        cols = ("name", "visits", "price", "cpts", "expires", "active")
        wrap = tk.Frame(self, bg=COLOR_BORDER, padx=1, pady=1)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree = ttk.Treeview(
            wrap, columns=cols, show="headings", height=14, selectmode="browse",
        )
        for col, title, w, anchor in [
            ("name", "Name", 240, "w"),
            ("visits", "Visits", 60, "center"),
            ("price", "Price", 80, "e"),
            ("cpts", "CPT whitelist", 220, "w"),
            ("expires", "Expires (mo)", 90, "center"),
            ("active", "Active", 70, "center"),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor=anchor)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        btn = tk.Frame(self, bg=COLOR_BG_APP)
        btn.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(
            btn, text="New template", command=self._new,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=4, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn, text="Edit selected", command=self._edit,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=4, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn, text="Toggle active", command=self._toggle_active,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=FONT_BASE,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=12, pady=4, cursor="hand2",
        ).pack(side="left")
        tk.Button(btn, text="Close", command=self.destroy, relief="flat", cursor="hand2").pack(side="right")

        self.tree.bind("<Double-Button-1>", lambda _e: self._edit())
        self._reload()

    def _reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for t in list_catalog_templates():
            cpts = ", ".join(t.get("cpt_whitelist") or [])
            self.tree.insert(
                "", "end",
                iid=t.get("catalog_id"),
                values=(
                    t.get("name") or "",
                    int(t.get("total_visits") or 0),
                    f"${float(t.get('package_price') or 0):,.2f}",
                    cpts[:48] + ("…" if len(cpts) > 48 else ""),
                    int(t.get("expiration_months") or 0) or "(none)",
                    "Yes" if t.get("active", True) else "No",
                ),
            )

    def _selected_id(self) -> str:
        sel = self.tree.selection()
        return sel[0] if sel else ""

    def _new(self) -> None:
        CatalogTemplateEditor(self, on_save=self._after_save)

    def _edit(self) -> None:
        cid = self._selected_id()
        if not cid:
            messagebox.showinfo("Edit template", "Select a template first.", parent=self)
            return
        rec = next((t for t in list_catalog_templates() if t.get("catalog_id") == cid), None)
        if not rec:
            return
        CatalogTemplateEditor(self, template=rec, on_save=self._after_save)

    def _toggle_active(self) -> None:
        cid = self._selected_id()
        if not cid:
            return
        rec = next((t for t in list_catalog_templates() if t.get("catalog_id") == cid), None)
        if not rec:
            return
        set_catalog_template_active(cid, not bool(rec.get("active", True)))
        self._reload()

    def _after_save(self, _rec: dict) -> None:
        self._reload()


class CatalogTemplateEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        template: dict | None = None,
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.on_save = on_save or (lambda _r: None)
        self.template = template or {}
        self.title("New package template" if not template else "Edit package template")
        self.geometry("680x640")
        self.minsize(600, 480)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        # Pinned button row (always reachable, independent of scroll position)
        btn = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=10)
        btn.pack(side="bottom", fill="x")
        tk.Button(
            btn, text="Save template", command=self._save,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        # Scrollable form body
        sf = ScrollFrame(self)
        sf.pack(side="top", fill="both", expand=True)
        f = ttk.Frame(sf.content, padding=(20, 16, 20, 16))
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        # Name
        ttk.Label(f, text="Template name").grid(row=0, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar(value=self.template.get("name") or "")
        self.name_entry = ttk.Entry(f, textvariable=self.name_var, width=40)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=4)

        # Visits
        ttk.Label(f, text="Total visits").grid(row=1, column=0, sticky="w", pady=4)
        self.visits_var = tk.StringVar(value=str(self.template.get("total_visits") or "10"))
        ttk.Entry(f, textvariable=self.visits_var, width=10).grid(row=1, column=1, sticky="w", pady=4)

        # Price
        ttk.Label(f, text="Package price ($)").grid(row=2, column=0, sticky="w", pady=4)
        self.price_var = tk.StringVar(value=f"{float(self.template.get('package_price') or 0):.2f}")
        ttk.Entry(f, textvariable=self.price_var, width=12).grid(row=2, column=1, sticky="w", pady=4)

        # Expiration
        ttk.Label(f, text="Expiration (months, 0 = none)").grid(row=3, column=0, sticky="w", pady=4)
        self.expire_var = tk.StringVar(value=str(self.template.get("expiration_months") or "12"))
        ttk.Entry(f, textvariable=self.expire_var, width=10).grid(row=3, column=1, sticky="w", pady=4)

        # CPT whitelist (compact list of checkboxes — they live inside the scrollable form)
        ttk.Label(f, text="CPT whitelist").grid(row=4, column=0, sticky="nw", pady=4)
        cpt_box = ttk.Frame(f, padding=(0, 0))
        cpt_box.grid(row=4, column=1, sticky="ew", pady=4)
        existing = set(self.template.get("cpt_whitelist") or [])
        self._cpt_vars: dict[str, tk.BooleanVar] = {}
        for cpt, label in _list_active_cpt_choices():
            v = tk.BooleanVar(value=(cpt in existing))
            self._cpt_vars[cpt] = v
            ttk.Checkbutton(cpt_box, text=label, variable=v).pack(fill="x", anchor="w", padx=2, pady=1)

        # Notes
        ttk.Label(f, text="Notes").grid(row=5, column=0, sticky="nw", pady=4)
        self.notes_text = tk.Text(f, height=4, wrap="word", font=FONT_BASE,
                                  relief="solid", borderwidth=1)
        self.notes_text.grid(row=5, column=1, sticky="ew", pady=4)
        self.notes_text.insert("1.0", self.template.get("notes") or "")

        # Disclaimer (overrides default)
        ttk.Label(f, text="Custom disclaimer\n(blank = use default)").grid(row=6, column=0, sticky="nw", pady=4)
        self.disc_text = tk.Text(f, height=3, wrap="word", font=FONT_BASE,
                                 relief="solid", borderwidth=1)
        self.disc_text.grid(row=6, column=1, sticky="ew", pady=4)
        self.disc_text.insert("1.0", self.template.get("disclaimer_text") or "")

        # Active
        self.active_var = tk.BooleanVar(value=bool(self.template.get("active", True)))
        ttk.Checkbutton(
            f, text="Active (visible to staff at point of sale)",
            variable=self.active_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Live discount preview
        self.preview_var = tk.StringVar()
        tk.Label(
            f, textvariable=self.preview_var,
            bg="#EFF6FF", fg="#1E3A8A",
            font=FONT_BASE, padx=10, pady=8, justify="left", wraplength=520,
        ).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 8))

        for v in (self.visits_var, self.price_var):
            v.trace_add("write", self._update_preview)
        for cv in self._cpt_vars.values():
            cv.trace_add("write", self._update_preview)
        self._update_preview()

        _make_modal(self, focus_widget=self.name_entry)

    def _selected_cpts(self) -> list[str]:
        return [cpt for cpt, v in self._cpt_vars.items() if v.get()]

    def _update_preview(self, *_a) -> None:
        visits = _parse_int(self.visits_var.get()) or 0
        price = _parse_float(self.price_var.get()) or 0.0
        cpts = self._selected_cpts()
        if visits <= 0 or price <= 0 or not cpts:
            self.preview_var.set("Enter visits, price, and at least one CPT to see the discount preview.")
            return
        avg_fee = sum(_cash_fee_for(c) for c in cpts) / len(cpts)
        retail_total = avg_fee * visits
        prorated = price / visits
        if retail_total > 0:
            pct_off = max(0.0, 100.0 * (retail_total - price) / retail_total)
            self.preview_var.set(
                f"Retail value at full cash fee: ${retail_total:,.2f}  "
                f"({pct_off:.1f}% discount)\n"
                f"Pro-rata value per visit: ${prorated:,.2f}  ·  "
                f"Average whitelisted CPT cash fee: ${avg_fee:,.2f}"
            )
        else:
            self.preview_var.set(
                "No cash fee on file for the selected CPTs — "
                "set fees in the clinic Fee Schedule first to show a discount."
            )

    def _save(self) -> None:
        try:
            data = {
                "catalog_id": self.template.get("catalog_id") or "",
                "name": self.name_var.get(),
                "total_visits": _parse_int(self.visits_var.get()) or 0,
                "package_price": _parse_float(self.price_var.get()) or 0.0,
                "cpt_whitelist": self._selected_cpts(),
                "expiration_months": _parse_int(self.expire_var.get()) or 0,
                "disclaimer_text": self.disc_text.get("1.0", "end-1c"),
                "notes": self.notes_text.get("1.0", "end-1c"),
                "active": self.active_var.get(),
            }
            rec = upsert_catalog_template(data)
        except ValueError as e:
            messagebox.showerror("Invalid", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        self.on_save(rec)
        self.destroy()


# ---------------------------------------------------------------------------
# Sell package (catalog OR ad-hoc) — single dialog, two modes
# ---------------------------------------------------------------------------

class SellPackageDialog(tk.Toplevel):
    """
    Sell a package to the active patient. Two modes:
      mode='catalog': pick a template (defaults populate but stay editable)
      mode='adhoc':   freeform — requires a memo and is flagged is_adhoc=True
    User can also pre-populate from a Plan-page conversion via initial_*.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        patient_name: str,
        recorded_by: str = "",
        initial_visits: int | None = None,
        initial_objectives: str = "",
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.patient_name = patient_name
        self.recorded_by = recorded_by
        self.on_save = on_save or (lambda _r: None)
        self.title(f"Sell package — {patient_name}")
        self.geometry("720x720")
        self.minsize(620, 540)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        # Pinned action row at the bottom (always reachable)
        btn = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=10)
        btn.pack(side="bottom", fill="x")
        tk.Button(
            btn, text="Sell package + record payment", command=self._save,
            bg=COLOR_GREEN, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        # Live preview banner (also pinned so it's always visible while editing)
        self.preview_var = tk.StringVar(value="Fill visits, price, and CPTs to see the per-visit pro-rata value.")
        tk.Label(
            self, textvariable=self.preview_var,
            bg="#ECFDF5", fg="#065F46",
            font=FONT_BASE, padx=12, pady=8, justify="left", wraplength=680,
            anchor="w",
        ).pack(side="bottom", fill="x", padx=14, pady=(0, 6))

        # Scrollable form body
        sf = ScrollFrame(self)
        sf.pack(side="top", fill="both", expand=True)
        f = ttk.Frame(sf.content, padding=(20, 14, 20, 14))
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        # Load active templates first — drives mode default and UI state.
        self._templates = [t for t in list_catalog_templates() if t.get("active", True)]
        has_templates = bool(self._templates)

        # Mode toggle (default to Ad-hoc when no templates exist so the form is
        # immediately usable instead of stuck on an empty catalog dropdown).
        self.mode_var = tk.StringVar(value="catalog" if has_templates else "adhoc")
        mode_row = ttk.Frame(f)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.catalog_rb = ttk.Radiobutton(
            mode_row, text="From catalog", variable=self.mode_var, value="catalog",
            command=self._on_mode_change,
        )
        self.catalog_rb.pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            mode_row, text="Ad-hoc (custom)", variable=self.mode_var, value="adhoc",
            command=self._on_mode_change,
        ).pack(side="left", padx=(0, 12))
        # Helpful inline hint + shortcut when the catalog is empty.
        if not has_templates:
            self.catalog_rb.configure(state="disabled")
            ttk.Label(
                mode_row,
                text="(No catalog templates yet — using Ad-hoc)",
                foreground="#92400E",
            ).pack(side="left", padx=(0, 8))
            ttk.Button(
                mode_row, text="Open Catalog editor…",
                command=self._open_catalog_from_sell,
            ).pack(side="left")

        # Catalog picker (mode=catalog) — only meaningful when templates exist
        ttk.Label(f, text="Catalog template").grid(row=1, column=0, sticky="w", pady=4)
        self.template_var = tk.StringVar()
        if has_templates:
            cb_values = [
                f"{t.get('name')} — {int(t.get('total_visits') or 0)} visits "
                f"· ${float(t.get('package_price') or 0):,.2f}"
                for t in self._templates
            ]
        else:
            cb_values = ["(no templates available)"]
        self.template_cb = ttk.Combobox(
            f, textvariable=self.template_var,
            values=cb_values,
            state="readonly", width=44,
        )
        self.template_cb.grid(row=1, column=1, sticky="ew", pady=4)
        self.template_cb.bind("<<ComboboxSelected>>", self._on_template_selected)

        # Common editable fields
        ttk.Label(f, text="Plan name").grid(row=2, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(f, textvariable=self.name_var, width=40)
        self.name_entry.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="Total visits").grid(row=3, column=0, sticky="w", pady=4)
        self.visits_var = tk.StringVar(value=str(initial_visits) if initial_visits else "10")
        ttk.Entry(f, textvariable=self.visits_var, width=10).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Package price ($)").grid(row=4, column=0, sticky="w", pady=4)
        self.price_var = tk.StringVar(value="0.00")
        ttk.Entry(f, textvariable=self.price_var, width=12).grid(row=4, column=1, sticky="w", pady=4)

        # CPT whitelist — plain checkboxes inside the scrollable form (no nested canvas).
        ttk.Label(f, text="CPT whitelist").grid(row=5, column=0, sticky="nw", pady=4)
        cpt_box = ttk.Frame(f)
        cpt_box.grid(row=5, column=1, sticky="ew", pady=4)
        self._cpt_vars: dict[str, tk.BooleanVar] = {}
        for cpt, label in _list_active_cpt_choices():
            v = tk.BooleanVar()
            self._cpt_vars[cpt] = v
            ttk.Checkbutton(cpt_box, text=label, variable=v).pack(fill="x", anchor="w", padx=2, pady=1)

        # Expiration months
        ttk.Label(f, text="Expiration (months)").grid(row=6, column=0, sticky="w", pady=4)
        self.expire_var = tk.StringVar(value="12")
        ttk.Entry(f, textvariable=self.expire_var, width=10).grid(row=6, column=1, sticky="w", pady=4)

        # Payment
        ttk.Label(f, text="Payment method").grid(row=7, column=0, sticky="w", pady=4)
        self.method_var = tk.StringVar(value="card")
        ttk.Combobox(
            f, textvariable=self.method_var,
            values=["cash", "card", "check", "other"],
            state="readonly", width=12,
        ).grid(row=7, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Purchase date").grid(row=8, column=0, sticky="w", pady=4)
        self.date_var = tk.StringVar(value=today_str())
        ttk.Entry(f, textvariable=self.date_var, width=14).grid(row=8, column=1, sticky="w", pady=4)

        # Therapeutic objectives (required for state contract)
        ttk.Label(f, text="Therapeutic objectives\n(required, from prior exam)").grid(
            row=9, column=0, sticky="nw", pady=4,
        )
        self.objectives = tk.Text(f, height=4, wrap="word", font=FONT_BASE,
                                  relief="solid", borderwidth=1)
        self.objectives.grid(row=9, column=1, sticky="ew", pady=4)
        if initial_objectives:
            self.objectives.insert("1.0", initial_objectives)

        # Memo (required for ad-hoc)
        ttk.Label(f, text="Memo / reason").grid(row=10, column=0, sticky="w", pady=4)
        self.memo_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.memo_var, width=44).grid(row=10, column=1, sticky="ew", pady=4)

        # Signed contract checkbox
        self.signed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f,
            text="Signed contract is on file (front desk has paper/scan)",
            variable=self.signed_var,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Initial payment now (NEW — supports partial pay-as-you-go).
        # Defaults to 0; click "Pay full" to mirror the package price, or type a
        # partial amount. Any remaining balance is collected later via Take Payment.
        ttk.Label(f, text="Pay now ($, optional)").grid(row=12, column=0, sticky="w", pady=(10, 4))
        pay_row = ttk.Frame(f)
        pay_row.grid(row=12, column=1, sticky="ew", pady=(10, 4))
        self.pay_now_var = tk.StringVar(value="0.00")
        ttk.Entry(pay_row, textvariable=self.pay_now_var, width=12).pack(side="left")
        ttk.Button(
            pay_row, text="Pay full",
            command=lambda: self.pay_now_var.set(f"{(_parse_float(self.price_var.get()) or 0.0):.2f}"),
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            pay_row,
            text="  (0 = contract only, collect later)",
            foreground=COLOR_MUTED,
        ).pack(side="left")

        for v in (self.visits_var, self.price_var, self.expire_var, self.date_var, self.pay_now_var):
            v.trace_add("write", self._update_preview)
        for cv in self._cpt_vars.values():
            cv.trace_add("write", self._update_preview)
        self._on_mode_change()
        self._update_preview()

        _make_modal(self, focus_widget=self.name_entry)

    def _on_mode_change(self) -> None:
        is_catalog = self.mode_var.get() == "catalog"
        # Combobox stays disabled when there are no templates regardless of mode.
        if not self._templates:
            self.template_cb.configure(state="disabled")
            return
        self.template_cb.configure(state="readonly" if is_catalog else "disabled")
        if not is_catalog:
            self.template_var.set("")

    def _open_catalog_from_sell(self) -> None:
        """
        Open the Catalog editor (modeless) without closing the sell dialog.
        After the user creates a template they should re-open Sell package to
        see the new option in the dropdown (avoids complex live-refresh).
        """
        try:
            CatalogEditorDialog(self.master)
        except Exception as e:
            messagebox.showerror("Catalog editor", str(e), parent=self)
            return
        messagebox.showinfo(
            "Heads up",
            "After you add templates in the Catalog editor, close this Sell "
            "package window and reopen it to pick the new template.",
            parent=self,
        )

    def _on_template_selected(self, _e=None) -> None:
        idx = self.template_cb.current()
        if idx < 0 or idx >= len(self._templates):
            return
        t = self._templates[idx]
        self.name_var.set(t.get("name") or "")
        self.visits_var.set(str(int(t.get("total_visits") or 0)))
        self.price_var.set(f"{float(t.get('package_price') or 0):.2f}")
        self.expire_var.set(str(int(t.get("expiration_months") or 0)))
        whitelist = set(t.get("cpt_whitelist") or [])
        for cpt, v in self._cpt_vars.items():
            v.set(cpt in whitelist)
        self._update_preview()

    def _selected_cpts(self) -> list[str]:
        return [cpt for cpt, v in self._cpt_vars.items() if v.get()]

    def _update_preview(self, *_a) -> None:
        visits = _parse_int(self.visits_var.get()) or 0
        price = _parse_float(self.price_var.get()) or 0.0
        cpts = self._selected_cpts()
        if visits <= 0 or price <= 0 or not cpts:
            self.preview_var.set("Fill visits, price, and CPTs to see the per-visit pro-rata value.")
            return
        avg_fee = sum(_cash_fee_for(c) for c in cpts) / len(cpts) if cpts else 0.0
        retail = avg_fee * visits
        prorated = price / visits
        exp_date = add_months_iso(self.date_var.get(), _parse_int(self.expire_var.get()) or 0)
        line = (
            f"Pro-rata value per visit: ${prorated:,.2f}  ·  "
            f"Retail (avg fee × visits): ${retail:,.2f}"
        )
        if exp_date:
            line += f"  ·  Expires: {exp_date}"
        if retail > 0 and price < retail:
            line += f"  ·  Discount: {100*(retail-price)/retail:.1f}%"
        # Show resulting balance after the initial payment so the front desk
        # can verify it matches what the patient is handing over.
        pay_now = max(0.0, _parse_float(self.pay_now_var.get()) or 0.0)
        balance_after = max(0.0, price - pay_now)
        line += (
            f"\nPaying now: ${pay_now:,.2f}  ·  Balance after: ${balance_after:,.2f}"
            + ("  (paid in full)" if balance_after <= 0.01 else "  (collect later via Take Payment)")
        )
        self.preview_var.set(line)

    def _save(self) -> None:
        is_catalog = self.mode_var.get() == "catalog"
        catalog_id = ""
        if is_catalog:
            if not self._templates:
                messagebox.showerror(
                    "No catalog templates",
                    "There are no catalog templates yet.\n\n"
                    "Switch to Ad-hoc (custom) to record this package now, or "
                    "open the Catalog editor to create reusable templates first.",
                    parent=self,
                )
                return
            idx = self.template_cb.current()
            if idx < 0 or idx >= len(self._templates):
                messagebox.showerror(
                    "Pick a template",
                    "Choose a catalog template from the dropdown, or switch to Ad-hoc.",
                    parent=self,
                )
                return
            catalog_id = self._templates[idx].get("catalog_id") or ""

        visits = _parse_int(self.visits_var.get()) or 0
        price = _parse_float(self.price_var.get()) or 0.0
        cpts = self._selected_cpts()
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Required", "Plan name is required.", parent=self)
            return
        if visits <= 0:
            messagebox.showerror("Required", "Total visits must be > 0.", parent=self)
            return
        if price <= 0:
            messagebox.showerror("Required", "Package price must be > 0.", parent=self)
            return
        if not cpts:
            messagebox.showerror("Required", "Pick at least one CPT for coverage.", parent=self)
            return
        objectives = self.objectives.get("1.0", "end-1c").strip()
        if not objectives:
            if not messagebox.askyesno(
                "Missing objectives",
                "State law typically requires therapeutic objectives in the signed contract.\n\n"
                "Continue without objectives? (You can edit the contract PDF before printing.)",
                parent=self,
            ):
                return
        memo = self.memo_var.get().strip()
        if not is_catalog and not memo:
            messagebox.showerror(
                "Memo required",
                "Ad-hoc packages require a memo explaining the reason "
                "(e.g. \"manager approved\" or \"matches Dr. plan\").",
                parent=self,
            )
            return

        purchase_date = (self.date_var.get() or "").strip() or today_str()
        expire_months = _parse_int(self.expire_var.get()) or 0
        expiration_date = add_months_iso(purchase_date, expire_months) if expire_months > 0 else ""
        prorated = round(price / visits, 2) if visits else 0.0
        avg_fee = sum(_cash_fee_for(c) for c in cpts) / len(cpts) if cpts else 0.0

        package_id = new_package_instance_id()
        purchase_event = {
            "type": EVENT_PURCHASE,
            "package_id": package_id,
            "catalog_id": catalog_id,
            "is_adhoc": not is_catalog,
            "name": name,
            "total_visits": visits,
            "cpt_whitelist": cpts,
            "purchase_price": round(price, 2),
            "prorated_value_per_visit": prorated,
            "retail_value_per_visit": round(avg_fee, 2),
            "purchase_date": purchase_date,
            "expiration_date": expiration_date,
            "expiration_months": expire_months,
            "signed_contract_on_file": bool(self.signed_var.get()),
            "therapeutic_objectives": objectives,
            "memo": memo,
            "recorded_by": self.recorded_by,
            "payment_method": self.method_var.get(),
        }

        pay_now = max(0.0, _parse_float(self.pay_now_var.get()) or 0.0)
        if pay_now > price + 0.01:
            messagebox.showerror(
                "Overpayment",
                f"Pay-now amount (${pay_now:,.2f}) is greater than the package "
                f"price (${price:,.2f}). Lower the amount or raise the price.",
                parent=self,
            )
            return

        try:
            # 1) Append purchase event (source of truth)
            stored = append_event(self.patient_root, purchase_event)
            # 2) If patient is paying part/all today, append a EVENT_PAYMENT
            #    event to packages.json. NOTHING is written to cash_ledger.json
            #    — package money is fully separated from cash money.
            if pay_now > 0:
                record_package_payment(
                    patient_root=self.patient_root,
                    package_id=package_id,
                    amount=pay_now,
                    method=self.method_var.get(),
                    payment_date=purchase_date,
                    memo=f"Initial payment · {name}",
                    recorded_by=self.recorded_by,
                )
            # 3) If user confirmed signed contract was on file, log that too.
            if self.signed_var.get():
                append_event(self.patient_root, {
                    "type": EVENT_CONTRACT_FILED,
                    "package_id": package_id,
                    "recorded_by": self.recorded_by,
                    "memo": "Marked at point of sale",
                })
        except Exception as e:
            messagebox.showerror("Sale failed", str(e), parent=self)
            return

        self.on_save({"package_id": package_id, "purchase_event": stored})
        self.destroy()


# ---------------------------------------------------------------------------
# Redemption prompt (per-line checkboxes — Gap A)
# ---------------------------------------------------------------------------

class RedeemPromptDialog(tk.Toplevel):
    """
    Shown when posting cash on an encounter that has package_meta.suggested_redemptions.

    The user sees one row per eligible charge line with:
      [✓] CPT 98941 — Spinal 3-4 regions  ·  Full fee $75.00
          Apply package: [10-Visit Standard ▼]  (7 remaining)

    Unchecked lines are billed normally to the patient. Each checked line will
    consume one (1) visit from the selected package and add a negative adjustment
    equal to the full fee.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        suggestions: list[dict],
        on_confirm: Callable[[list[dict]], None],
        on_decline: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.on_confirm = on_confirm
        self.on_decline = on_decline or (lambda: None)
        self.title("Apply package coverage?")
        self.geometry("620x460")
        self.minsize(540, 380)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)
        _make_modal(self)

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=16)
        f.pack(fill="both", expand=True)

        tk.Label(
            f,
            text="Active package coverage detected",
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_SECTION,
        ).pack(anchor="w")
        tk.Label(
            f,
            text="Check the charge lines you want to cover with a package. "
                 "Each checked line consumes 1 visit and applies a contractual adjustment.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=560, justify="left",
        ).pack(anchor="w", pady=(2, 12))

        body_wrap = tk.Frame(f, bg=COLOR_BORDER, padx=1, pady=1)
        body_wrap.pack(fill="both", expand=True, pady=(0, 10))
        body = tk.Frame(body_wrap, bg=COLOR_CARD)
        body.pack(fill="both", expand=True)

        # Per-line rows
        self._rows: list[dict] = []
        for s in suggestions:
            row_frame = tk.Frame(body, bg=COLOR_CARD, padx=10, pady=6)
            row_frame.pack(fill="x")
            check_var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(
                row_frame, variable=check_var,
                bg=COLOR_CARD, activebackground=COLOR_CARD, selectcolor=COLOR_CARD,
            )
            cb.pack(side="left")

            text_block = tk.Frame(row_frame, bg=COLOR_CARD)
            text_block.pack(side="left", fill="x", expand=True, padx=(4, 8))
            tk.Label(
                text_block,
                text=f"CPT {s.get('cpt')}  ·  {s.get('description') or ''}",
                bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE_BOLD,
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                text_block,
                text=f"Full cash fee: ${float(s.get('full_fee_cash') or 0):,.2f}",
                bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
                anchor="w",
            ).pack(fill="x")

            # Package picker (one per line; defaults to first option)
            opts = s.get("package_options") or []
            pkg_var = tk.StringVar()
            cb_values = [
                f"{p.get('name') or '(unnamed)'} — {int(p.get('visits_remaining') or 0)} remaining"
                + (f" · expires {p.get('expires_on')}" if p.get('expires_on') else "")
                for p in opts
            ]
            pkg_cb = ttk.Combobox(
                row_frame, textvariable=pkg_var,
                values=cb_values, state="readonly", width=44,
            )
            pkg_cb.pack(side="right")
            if opts:
                pkg_cb.current(0)

            self._rows.append({
                "suggestion": s,
                "check_var": check_var,
                "pkg_var": pkg_var,
                "pkg_cb": pkg_cb,
                "options": opts,
            })

        # Footer
        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.pack(fill="x", pady=(4, 0))
        tk.Button(
            btn, text="Apply selected & post cash", command=self._confirm,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn, text="Skip — bill patient normally", command=self._decline,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            font=FONT_BASE, padx=12, pady=6, cursor="hand2",
        ).pack(side="left")
        tk.Button(
            btn, text="Cancel post", command=self._cancel,
            relief="flat", cursor="hand2",
        ).pack(side="right")

    def _confirm(self) -> None:
        redemptions: list[dict] = []
        for row in self._rows:
            if not row["check_var"].get():
                continue
            opts = row["options"]
            idx = row["pkg_cb"].current()
            if idx < 0 or idx >= len(opts):
                messagebox.showerror(
                    "Pick a package",
                    "Select which package to use for each checked line.",
                    parent=self,
                )
                return
            chosen = opts[idx]
            s = row["suggestion"]
            redemptions.append({
                "charge_line_id": s.get("charge_line_id") or "",
                "cpt": s.get("cpt") or "",
                "package_id": chosen.get("package_id") or "",
                "catalog_id": chosen.get("catalog_id") or "",
                "amount_offset": float(s.get("full_fee_cash") or 0.0),
                "value_recognized": float(chosen.get("prorated_value_per_visit") or 0.0),
            })
        self.destroy()
        # IMPORTANT: empty list means "post with no redemptions" (decline path).
        # Caller distinguishes via the user choice; we always call on_confirm here.
        self.on_confirm(redemptions)

    def _decline(self) -> None:
        self.destroy()
        self.on_confirm([])  # post with no redemptions = bill patient normally

    def _cancel(self) -> None:
        self.destroy()
        self.on_decline()


# ---------------------------------------------------------------------------
# Package post-visit (count this visit toward the package, redeem one visit)
# ---------------------------------------------------------------------------

class PackagePostVisitDialog(tk.Toplevel):
    """
    Apply the selected visit to an active package: redeems one (1) visit and
    writes a sidecar posted-package file so the encounter row shows the Pckg$
    badge. Does NOT touch the cash ledger.

    The whole VISIT is the unit of redemption — every encounter CPT is recorded
    on the redemption (the package whitelist set at sale time is informational
    only). One visit is consumed regardless of how many CPTs were performed,
    and a patient may redeem a visit with therapy only / E/M only / etc.

    The dialog presents:
      * dropdown of the patient's Active packages with visits remaining
      * the full CPT list from today's encounter
      * the "primary" CPT chosen as the visit's headline code (per the
        spinal-CMT > extremity-CMT > therapy > other priority).
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        exam_path: str,
        patient_name: str = "",
        recorded_by: str = "",
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.exam_path = exam_path
        self.recorded_by = recorded_by
        self.on_save = on_save or (lambda _r: None)
        self.title(f"Post visit to package — {patient_name or ''}".strip(" —"))
        self.geometry("640x520")
        self.minsize(560, 420)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        # Load active redeemable packages + this encounter's CPT lines.
        from package_engine import active_redeemable_packages
        from package_storage import load_package_log
        from billing_storage import load_or_refresh_shadow_encounter

        events = load_package_log(patient_root).get("events") or []
        self._active_states = active_redeemable_packages(events)

        try:
            shadow = load_or_refresh_shadow_encounter(patient_root, exam_path)
        except Exception:
            shadow = None
        self._shadow_lines: list[dict] = []
        self._date_of_service: str = ""
        if isinstance(shadow, dict):
            self._date_of_service = (shadow.get("date_of_service") or "").strip()
            for ln in shadow.get("lines") or []:
                if isinstance(ln, dict) and (ln.get("cpt_code") or "").strip():
                    self._shadow_lines.append(ln)

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        # Header explanation
        tk.Label(
            f,
            text="Apply this visit to a package deal",
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE_BOLD,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(
            f,
            text=(
                "Redeems one (1) visit from the package. ALL CPTs performed "
                "today are recorded on the package receipt; the \"primary\" "
                "code below is the headline used on summaries. No charges "
                "go to the cash ledger."
            ),
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=580, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Package picker
        ttk.Label(f, text="Package").grid(row=2, column=0, sticky="w", pady=4)
        self.pkg_var = tk.StringVar()
        pkg_values = []
        for s in self._active_states:
            purchase = s.get("purchase") or {}
            pkg_values.append(
                f"{purchase.get('name') or 'Package'}  ·  {int(s.get('visits_remaining') or 0)} left  "
                f"·  ${float(purchase.get('prorated_value_per_visit') or 0):,.2f}/visit"
                + (f"  ·  exp {purchase.get('expiration_date')}" if purchase.get("expiration_date") else "")
            )
        self.pkg_cb = ttk.Combobox(
            f, textvariable=self.pkg_var,
            values=pkg_values or ["(no active redeemable packages)"],
            state="readonly" if pkg_values else "disabled",
            width=56,
        )
        self.pkg_cb.grid(row=2, column=1, sticky="ew", pady=4)
        if pkg_values:
            self.pkg_cb.current(0)
        self.pkg_cb.bind("<<ComboboxSelected>>", self._refresh_breakdown)

        # Today's CPTs (read-only summary — full list, no whitelist filter).
        ttk.Label(f, text="Today's CPTs").grid(row=3, column=0, sticky="nw", pady=(8, 4))
        self.today_var = tk.StringVar(value="")
        tk.Label(
            f, textvariable=self.today_var,
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE,
            wraplength=480, justify="left", anchor="w",
        ).grid(row=3, column=1, sticky="ew", pady=(8, 4))

        # Primary CPT — the headline code chosen via clinic priority rules
        # (spinal CMT > extremity CMT > therapy 97xxx > first other).
        ttk.Label(f, text="Primary visit code").grid(row=4, column=0, sticky="nw", pady=4)
        self.primary_var = tk.StringVar(value="")
        tk.Label(
            f, textvariable=self.primary_var,
            bg=COLOR_CARD, fg=COLOR_GREEN, font=FONT_BASE_BOLD,
            wraplength=480, justify="left", anchor="w",
        ).grid(row=4, column=1, sticky="ew", pady=4)

        # Whitelist (informational — does NOT gate posting any more).
        ttk.Label(f, text="Package whitelist").grid(row=5, column=0, sticky="nw", pady=4)
        self.whitelist_var = tk.StringVar(value="")
        tk.Label(
            f, textvariable=self.whitelist_var,
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=480, justify="left", anchor="w",
        ).grid(row=5, column=1, sticky="ew", pady=4)

        # Status / hint line
        self.status_var = tk.StringVar(value="")
        tk.Label(
            f, textvariable=self.status_var,
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=580, justify="left", anchor="w",
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # Action row
        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=7, column=0, columnspan=2, pady=(20, 0))
        self.btn_post = tk.Button(
            btn, text="Post visit to package", command=self._save,
            bg=COLOR_GREEN, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        )
        self.btn_post.pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        self._refresh_breakdown()
        _make_modal(self, focus_widget=self.pkg_cb)

    def _selected_state(self) -> dict | None:
        idx = self.pkg_cb.current()
        if idx < 0 or idx >= len(self._active_states):
            return None
        return self._active_states[idx]

    def _all_encounter_cpts(self) -> list[str]:
        seen: list[str] = []
        for ln in self._shadow_lines:
            c = (ln.get("cpt_code") or "").strip()
            if c and c not in seen:
                seen.append(c)
        return seen

    def _refresh_breakdown(self, _e=None) -> None:
        from package_engine import pick_primary_cpt

        all_cpts = self._all_encounter_cpts()
        self._encounter_cpts = all_cpts  # cached for _save()
        self.today_var.set(", ".join(all_cpts) if all_cpts else "(none on the chart yet)")

        state = self._selected_state()
        if not state:
            self.primary_var.set("—")
            self.whitelist_var.set("—")
            self.status_var.set(
                "No active redeemable packages for this patient. Sell a package first."
            )
            self.btn_post.configure(state="disabled")
            return

        whitelist = [
            str(c).strip()
            for c in ((state.get("purchase") or {}).get("cpt_whitelist") or [])
        ]
        self.whitelist_var.set(
            ", ".join(sorted(whitelist)) + "   (informational — does not gate posting)"
            if whitelist
            else "(none defined — any CPT counts)"
        )

        primary = pick_primary_cpt(all_cpts)
        self._primary_cpt = primary
        if primary:
            self.primary_var.set(primary)
        else:
            self.primary_var.set("(no CPTs on encounter — visit slot only)")

        # Posting is always allowed when a package is selected — even with
        # zero CPTs (patient uses a visit slot for a no-charge follow-up).
        self.status_var.set(
            "Click 'Post visit to package' to redeem 1 visit. "
            "Every CPT above is recorded on the package receipt; "
            "the primary code is the headline shown on summaries."
        )
        self.btn_post.configure(state="normal")

    def _save(self) -> None:
        state = self._selected_state()
        if not state:
            return
        encounter_cpts = list(getattr(self, "_encounter_cpts", []))
        primary = (getattr(self, "_primary_cpt", "") or "").strip()
        package_id = state.get("package_id") or ""
        cpt_summary = ", ".join(encounter_cpts) if encounter_cpts else "(no CPTs)"
        primary_summary = primary or "(none — visit slot only)"
        if not messagebox.askyesno(
            "Confirm post",
            f"Apply this visit to '{((state.get('purchase') or {}).get('name') or 'Package')}'?\n\n"
            f"  CPTs recorded:  {cpt_summary}\n"
            f"  Primary code:   {primary_summary}\n"
            f"  Visits remaining after: {int(state.get('visits_remaining') or 1) - 1}\n\n"
            "No charges will be written to the cash ledger.",
            parent=self,
        ):
            return
        try:
            # Pass the primary CPT as a hint (storage will record the full
            # encounter CPT list automatically from the shadow encounter).
            posted, event = post_encounter_to_package(
                patient_root=self.patient_root,
                exam_path=self.exam_path,
                package_id=package_id,
                cpt=primary,
                date_of_service=self._date_of_service,
                posted_by=self.recorded_by,
            )
        except Exception as e:
            messagebox.showerror("Post failed", str(e), parent=self)
            return
        self.on_save({"posted": posted, "redemption": event})
        self.destroy()


# ---------------------------------------------------------------------------
# Take Payment — collect a partial / full payment toward a package balance
# ---------------------------------------------------------------------------

class PackageTakePaymentDialog(tk.Toplevel):
    """
    Collect a payment toward a package's outstanding contract balance.

    Lists every package with purchase_balance_due > 0 (still owes money) and
    pre-fills the amount to the remaining balance. Writes a EVENT_PAYMENT event
    to packages.json — does NOT touch cash_ledger.json.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        patient_name: str = "",
        recorded_by: str = "",
        preselect_package_id: str = "",
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.recorded_by = recorded_by
        self.on_save = on_save or (lambda _r: None)
        self.title(f"Take package payment — {patient_name or ''}".strip(" —"))
        self.geometry("620x440")
        self.minsize(540, 360)
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        # Load all packages with an outstanding balance (any status — patients
        # who owe money on a cancelled/refunded package can still make a payment)
        from package_engine import states_for_patient
        from package_storage import load_package_log

        events = load_package_log(patient_root).get("events") or []
        all_states = states_for_patient(events)
        self._unpaid_states = [
            s for s in all_states if float(s.get("purchase_balance_due") or 0.0) > 0.01
        ]

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        # Header
        tk.Label(
            f,
            text="Collect a payment toward a package balance",
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE_BOLD,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(
            f,
            text=(
                "Payment is recorded in the package ledger only — it does NOT "
                "appear on cash receipts. Cash visits stand alone from packages."
            ),
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=560, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Package picker
        ttk.Label(f, text="Package (balance)").grid(row=2, column=0, sticky="w", pady=4)
        self.pkg_var = tk.StringVar()
        pkg_values = []
        for s in self._unpaid_states:
            purchase = s.get("purchase") or {}
            pkg_values.append(
                f"{purchase.get('name') or 'Package'}  ·  "
                f"owes ${float(s.get('purchase_balance_due') or 0):,.2f} of "
                f"${float(s.get('purchase_price') or 0):,.2f}  ·  "
                f"{status_label(s.get('status') or '')}"
            )
        self.pkg_cb = ttk.Combobox(
            f, textvariable=self.pkg_var,
            values=pkg_values or ["(no package balances owing)"],
            state="readonly" if pkg_values else "disabled",
            width=56,
        )
        self.pkg_cb.grid(row=2, column=1, sticky="ew", pady=4)
        if pkg_values:
            initial = 0
            if preselect_package_id:
                for i, s in enumerate(self._unpaid_states):
                    if s.get("package_id") == preselect_package_id:
                        initial = i
                        break
            self.pkg_cb.current(initial)
        self.pkg_cb.bind("<<ComboboxSelected>>", self._refresh_amount_default)

        # Amount
        ttk.Label(f, text="Amount ($)").grid(row=3, column=0, sticky="w", pady=4)
        self.amount_var = tk.StringVar(value="0.00")
        amt_row = ttk.Frame(f)
        amt_row.grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Entry(amt_row, textvariable=self.amount_var, width=12).pack(side="left")
        ttk.Button(amt_row, text="Pay full balance",
                   command=self._refresh_amount_default).pack(side="left", padx=(6, 0))

        # Method
        ttk.Label(f, text="Method").grid(row=4, column=0, sticky="w", pady=4)
        self.method_var = tk.StringVar(value="card")
        ttk.Combobox(
            f, textvariable=self.method_var,
            values=["cash", "card", "check", "other"],
            state="readonly", width=12,
        ).grid(row=4, column=1, sticky="w", pady=4)

        # Date
        ttk.Label(f, text="Date").grid(row=5, column=0, sticky="w", pady=4)
        self.date_var = tk.StringVar(value=today_str())
        ttk.Entry(f, textvariable=self.date_var, width=14).grid(row=5, column=1, sticky="w", pady=4)

        # Memo
        ttk.Label(f, text="Memo (optional)").grid(row=6, column=0, sticky="w", pady=4)
        self.memo_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.memo_var, width=44).grid(row=6, column=1, sticky="ew", pady=4)

        # Action row
        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=7, column=0, columnspan=2, pady=(20, 0))
        self.btn_take = tk.Button(
            btn, text="Record payment", command=self._save,
            bg=COLOR_GREEN, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
            state="normal" if pkg_values else "disabled",
        )
        self.btn_take.pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        if pkg_values:
            self._refresh_amount_default()
        _make_modal(self, focus_widget=self.pkg_cb)

    def _selected_state(self) -> dict | None:
        idx = self.pkg_cb.current()
        if idx < 0 or idx >= len(self._unpaid_states):
            return None
        return self._unpaid_states[idx]

    def _refresh_amount_default(self, _e=None) -> None:
        state = self._selected_state()
        if not state:
            return
        bal = float(state.get("purchase_balance_due") or 0.0)
        self.amount_var.set(f"{bal:.2f}")

    def _save(self) -> None:
        state = self._selected_state()
        if not state:
            messagebox.showerror("No package", "No package with an outstanding balance.", parent=self)
            return
        amount = _parse_float(self.amount_var.get()) or 0.0
        if amount <= 0:
            messagebox.showerror("Amount required", "Enter a payment amount > 0.", parent=self)
            return
        bal = float(state.get("purchase_balance_due") or 0.0)
        if amount > bal + 0.01:
            if not messagebox.askyesno(
                "Overpayment",
                f"Amount (${amount:,.2f}) is greater than the remaining balance "
                f"(${bal:,.2f}). Record the overpayment anyway?",
                parent=self,
            ):
                return
        try:
            event = record_package_payment(
                patient_root=self.patient_root,
                package_id=state.get("package_id") or "",
                amount=amount,
                method=self.method_var.get(),
                payment_date=(self.date_var.get() or "").strip(),
                memo=(self.memo_var.get() or "").strip(),
                recorded_by=self.recorded_by,
            )
        except Exception as e:
            messagebox.showerror("Payment failed", str(e), parent=self)
            return
        self.on_save({"payment_event": event})
        self.destroy()


# ---------------------------------------------------------------------------
# Refund (both strategies — Gap B)
# ---------------------------------------------------------------------------

class RefundPackageDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        package_id: str,
        recorded_by: str = "",
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.package_id = package_id
        self.recorded_by = recorded_by
        self.on_save = on_save or (lambda _r: None)
        self.title("Refund package")
        self.geometry("620x540")
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        events = all_events_for_package(patient_root, package_id)
        self.state = compute_package_state(events)
        self.quote = compute_refund_quote(self.state)

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        purchase = self.state.get("purchase") or {}
        tk.Label(
            f, text=f"Refund: {purchase.get('name') or 'Package'}",
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_SECTION,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        summary = (
            f"Purchase price: ${float(purchase.get('purchase_price') or 0):,.2f}  ·  "
            f"Visits used: {self.state.get('visits_used') or 0}/{purchase.get('total_visits') or 0}  ·  "
            f"Already refunded: ${self.quote.get('already_refunded') or 0:,.2f}"
        )
        tk.Label(
            f, text=summary, bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Strategy radios — side by side
        self.strategy_var = tk.StringVar(value=REFUND_STRATEGY_TRUE_PRORATA)
        prorata = self.quote["strategy_true_pro_rata"]
        audit = self.quote["strategy_retail_audit"]

        s1_text = (
            "Strategy 1: True pro-rata (statute-default in NC, most states)\n"
            f"  Refund = ${prorata['refund_amount']:,.2f}\n"
            f"  Calc: {prorata['calc']}"
        )
        s2_text = (
            "Strategy 2: Retail audit (charge used visits at full fee)\n"
            f"  Refund = ${audit['refund_amount']:,.2f}\n"
            f"  Calc: {audit['calc']}"
        )

        for row_idx, (key, txt) in enumerate(
            [(REFUND_STRATEGY_TRUE_PRORATA, s1_text), (REFUND_STRATEGY_RETAIL_AUDIT, s2_text)],
            start=2,
        ):
            row = tk.Frame(f, bg=COLOR_CARD)
            row.grid(row=row_idx, column=0, columnspan=2, sticky="ew", pady=(0, 8))
            ttk.Radiobutton(
                row, variable=self.strategy_var, value=key,
                command=self._on_strategy_change,
            ).pack(side="left", anchor="n", padx=(0, 6))
            tk.Label(
                row, text=txt,
                bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE,
                justify="left", anchor="w",
            ).pack(side="left", fill="x", expand=True)

        # Refund amount (auto-populates from strategy)
        ttk.Label(f, text="Refund amount ($)").grid(row=4, column=0, sticky="w", pady=4)
        self.amount_var = tk.StringVar(value=f"{prorata['refund_amount']:.2f}")
        ttk.Entry(f, textvariable=self.amount_var, width=14).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Method").grid(row=5, column=0, sticky="w", pady=4)
        self.method_var = tk.StringVar(value="check")
        ttk.Combobox(
            f, textvariable=self.method_var,
            values=["check", "cash", "card_reversal", "other"],
            state="readonly", width=14,
        ).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Refund date").grid(row=6, column=0, sticky="w", pady=4)
        self.date_var = tk.StringVar(value=today_str())
        ttk.Entry(f, textvariable=self.date_var, width=14).grid(row=6, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Memo / reason").grid(row=7, column=0, sticky="w", pady=4)
        self.memo_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.memo_var, width=44).grid(row=7, column=1, sticky="ew", pady=4)

        tk.Label(
            f,
            text="Most state boards require the refund within 10 business days "
                 "of written termination notice.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=560, justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=9, column=0, columnspan=2, pady=(14, 0))
        tk.Button(
            btn, text="Issue refund", command=self._save,
            bg=COLOR_RED, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Cancel", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        _make_modal(self)

    def _on_strategy_change(self) -> None:
        key = self.strategy_var.get()
        if key == REFUND_STRATEGY_TRUE_PRORATA:
            self.amount_var.set(f"{self.quote['strategy_true_pro_rata']['refund_amount']:.2f}")
        else:
            self.amount_var.set(f"{self.quote['strategy_retail_audit']['refund_amount']:.2f}")

    def _save(self) -> None:
        amount = _parse_float(self.amount_var.get())
        if not amount or amount <= 0:
            messagebox.showerror("Invalid", "Enter a refund amount greater than zero.", parent=self)
            return
        max_allowed = float((self.state.get("purchase") or {}).get("purchase_price") or 0.0) \
                      - float(self.state.get("refund_paid") or 0.0)
        if amount > max_allowed + 0.01:
            messagebox.showerror(
                "Invalid",
                f"Refund cannot exceed the remaining deposit of ${max_allowed:,.2f}.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Confirm refund",
            f"Issue refund of ${amount:,.2f} via {self.method_var.get()}?\n\n"
            "This will:\n"
            "  • Append a refund event to the package log (locking the package as Refunded)\n"
            "  • Add a refund entry to the cash ledger",
            parent=self,
        ):
            return

        from billing_ledger import record_refund

        try:
            stored = append_event(self.patient_root, {
                "type": EVENT_REFUND,
                "package_id": self.package_id,
                "amount": round(amount, 2),
                "method": self.method_var.get(),
                "refund_date": (self.date_var.get() or "").strip() or today_str(),
                "memo": (self.memo_var.get() or "").strip(),
                "refund_strategy": self.strategy_var.get(),
                "visits_used_at_refund": int(self.state.get("visits_used") or 0),
                "recorded_by": self.recorded_by,
            })
            record_refund(
                patient_root=self.patient_root,
                amount=amount,
                method=self.method_var.get(),
                refund_date=(self.date_var.get() or "").strip(),
                memo=f"Package refund · {(self.memo_var.get() or '').strip()}",
                package_id=self.package_id,
                recorded_by=self.recorded_by,
            )
        except Exception as e:
            messagebox.showerror("Refund failed", str(e), parent=self)
            return
        self.on_save(stored)
        self.destroy()


# ---------------------------------------------------------------------------
# Cancel package (forfeit — no refund)
# ---------------------------------------------------------------------------

class CancelPackageDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        package_id: str,
        recorded_by: str = "",
        on_save: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.package_id = package_id
        self.recorded_by = recorded_by
        self.on_save = on_save or (lambda _r: None)
        self.title("Cancel package (no refund)")
        self.geometry("520x320")
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_CARD)

        f = tk.Frame(self, bg=COLOR_CARD, padx=20, pady=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        tk.Label(
            f,
            text="Cancel without refund — patient FORFEITS remaining visits",
            bg=COLOR_CARD, fg=COLOR_RED, font=FONT_BASE_BOLD,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(
            f,
            text="Use only with explicit patient acknowledgment OR clear policy "
                 "violation (e.g. extended no-show streak). In most states a refund "
                 "is required on demand — see RefundPackageDialog instead.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
            wraplength=460, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(f, text="Reason (required)").grid(row=2, column=0, sticky="nw", pady=4)
        self.reason_text = tk.Text(f, height=5, wrap="word", font=FONT_BASE,
                                   relief="solid", borderwidth=1)
        self.reason_text.grid(row=2, column=1, sticky="ew", pady=4)

        btn = tk.Frame(f, bg=COLOR_CARD)
        btn.grid(row=3, column=0, columnspan=2, pady=(14, 0))
        tk.Button(
            btn, text="Cancel package", command=self._save,
            bg=COLOR_RED, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(btn, text="Back", command=self.destroy, relief="flat", cursor="hand2").pack(side="left")

        _make_modal(self, focus_widget=self.reason_text)

    def _save(self) -> None:
        reason = self.reason_text.get("1.0", "end-1c").strip()
        if not reason:
            messagebox.showerror("Reason required", "Enter a reason for the cancellation.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirm cancel",
            "This will mark the package as Cancelled. The patient forfeits remaining visits "
            "and NO refund will be issued. This action cannot be undone.\n\nProceed?",
            parent=self,
        ):
            return
        try:
            stored = append_event(self.patient_root, {
                "type": EVENT_CANCELLATION,
                "package_id": self.package_id,
                "reason": reason,
                "recorded_by": self.recorded_by,
            })
        except Exception as e:
            messagebox.showerror("Cancel failed", str(e), parent=self)
            return
        self.on_save(stored)
        self.destroy()


# ---------------------------------------------------------------------------
# Package detail (read-only inspector)
# ---------------------------------------------------------------------------

class PackageDetailDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        patient_root: str,
        package_id: str,
        patient_name: str = "",
    ):
        super().__init__(parent)
        self.patient_root = patient_root
        self.package_id = package_id
        self.patient_name = patient_name
        self.title("Package detail")
        self.geometry("680x560")
        self.transient(parent.winfo_toplevel())
        self.configure(bg=COLOR_BG_APP)

        events = all_events_for_package(patient_root, package_id)
        state = compute_package_state(events)
        purchase = state.get("purchase") or {}

        head = tk.Frame(self, bg=COLOR_BG_APP)
        head.pack(fill="x", padx=12, pady=10)
        tk.Label(
            head,
            text=f"{purchase.get('name') or 'Package'}  ·  {status_label(state.get('status') or '')}",
            bg=COLOR_BG_APP, fg=COLOR_TEXT, font=FONT_TITLE,
        ).pack(side="left")
        tk.Button(
            head, text="Print contract", command=self._print_contract,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=10, pady=4, cursor="hand2",
        ).pack(side="right", padx=(0, 6))
        tk.Button(
            head, text="Print statement", command=self._print_statement,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=10, pady=4, cursor="hand2",
        ).pack(side="right", padx=(0, 6))

        body = tk.Text(self, wrap="word", font=("Consolas", 10),
                       bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
                       padx=12, pady=12)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.insert("1.0", self._format_detail(state))
        body.configure(state="disabled")

    def _format_detail(self, state: dict) -> str:
        purchase = state.get("purchase") or {}
        lines = []
        lines.append(f"Package ID:           {state.get('package_id') or ''}")
        lines.append(f"Catalog template:     {purchase.get('catalog_id') or '(ad-hoc)'}")
        lines.append(f"Plan name:            {purchase.get('name') or ''}")
        lines.append(f"Purchase date:        {purchase.get('purchase_date') or ''}")
        lines.append(f"Expiration:           {purchase.get('expiration_date') or '(none)'}")
        lines.append(f"Total visits:         {purchase.get('total_visits') or 0}")
        lines.append(f"CPT whitelist:        {', '.join(purchase.get('cpt_whitelist') or [])}")
        lines.append(f"Purchase price:       ${float(purchase.get('purchase_price') or 0):,.2f}")
        lines.append(f"Pro-rata per visit:   ${float(purchase.get('prorated_value_per_visit') or 0):,.2f}")
        lines.append("")
        lines.append(f"Visits used:          {state.get('visits_used') or 0}")
        lines.append(f"Visits remaining:     {state.get('visits_remaining') or 0}")
        lines.append(f"Amount paid (so far): ${float(state.get('amount_paid') or 0):,.2f}")
        lines.append(f"Balance owed:         ${float(state.get('purchase_balance_due') or 0):,.2f}")
        if state.get("is_paid_in_full"):
            lines.append("                      (paid in full)")
        lines.append(f"Revenue recognized:   ${float(state.get('value_recognized') or 0):,.2f}")
        lines.append(f"Refunds paid:         ${float(state.get('refund_paid') or 0):,.2f}")
        lines.append(f"Deferred remaining:   ${float(state.get('deferred_revenue_remaining') or 0):,.2f}")
        lines.append("")
        lines.append(f"Status: {status_label(state.get('status') or '')}")
        if purchase.get("therapeutic_objectives"):
            lines.append("")
            lines.append("THERAPEUTIC OBJECTIVES")
            lines.append(purchase.get("therapeutic_objectives") or "")
        if purchase.get("memo"):
            lines.append("")
            lines.append("Memo: " + purchase.get("memo"))

        # Event log
        lines.append("")
        lines.append("=" * 50)
        lines.append("EVENT LOG (append-only — source of truth)")
        lines.append("=" * 50)
        for e in all_events_for_package(self.patient_root, self.package_id):
            ts = (e.get("timestamp") or "").replace("T", " ")
            etype = (e.get("type") or "").upper()
            extra = ""
            if e.get("type") == "redemption":
                cpts_list = e.get("cpts_redeemed") or []
                if cpts_list:
                    cpt_label = "CPTs " + ", ".join(str(c) for c in cpts_list)
                else:
                    cpt_label = f"CPT {e.get('cpt_redeemed') or ''}"
                extra = (
                    f" · {cpt_label}"
                    f" · ${float(e.get('value_recognized') or 0):,.2f}"
                    f" · DOS {e.get('date_of_service') or ''}"
                )
            elif e.get("type") == "refund":
                extra = (
                    f" · ${float(e.get('amount') or 0):,.2f}"
                    f" · {e.get('method') or ''}"
                    f" · strategy: {e.get('refund_strategy') or ''}"
                )
            elif e.get("type") == "cancellation":
                extra = f" · {(e.get('reason') or '')[:60]}"
            elif e.get("type") == "payment":
                extra = (
                    f" · ${float(e.get('amount') or 0):,.2f}"
                    f" · {e.get('method') or ''}"
                    f" · {e.get('payment_date') or ''}"
                )
                if e.get("memo"):
                    extra += f" · {(e.get('memo') or '')[:40]}"
            lines.append(f"  {ts}  {etype}{extra}")
        return "\n".join(lines)

    def _print_contract(self) -> None:
        try:
            from package_pdf import build_contract_pdf

            out = build_contract_pdf(
                self.patient_root,
                patient_name=self.patient_name,
                package_id=self.package_id,
            )
        except RuntimeError as e:
            messagebox.showerror("Print contract", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("Print contract", f"Could not generate PDF:\n{e}", parent=self)
            return
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            pass
        messagebox.showinfo("Saved", f"Contract PDF saved:\n{out}", parent=self)

    def _print_statement(self) -> None:
        try:
            from package_pdf import build_statement_pdf

            out = build_statement_pdf(
                self.patient_root,
                patient_name=self.patient_name,
                package_id=self.package_id,
            )
        except RuntimeError as e:
            messagebox.showerror("Print statement", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("Print statement", f"Could not generate PDF:\n{e}", parent=self)
            return
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            pass
        messagebox.showinfo("Saved", f"Statement PDF saved:\n{out}", parent=self)
