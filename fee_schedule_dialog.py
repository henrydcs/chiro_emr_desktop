# fee_schedule_dialog.py — Clinic charge catalog + fees (Plan & Billing).
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from billing_storage import load_fee_schedules, set_fee_for_cpt
from service_catalog import (
    NO_CMT_CODE,
    category_label,
    default_em_long_for_line,
    ensure_charge_catalog,
    find_item_by_id,
    format_display_line,
    get_active_items,
    save_em_long_description,
    set_item_active,
    upsert_catalog_item,
)
from em_long_description_dialog import EmLongDescriptionDialog
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    make_card,
)


class FeeScheduleDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_close: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._on_close = on_close
        self.title("Clinic fee schedule — CMT / E/M / Therapy")
        self.geometry("820x580")
        self.minsize(700, 480)
        self.configure(bg=COLOR_BG_APP)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)

        ensure_charge_catalog()

        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            outer,
            text="Charge catalog & fees",
            bg=COLOR_BG_APP,
            fg=COLOR_TEXT,
            font=FONT_SECTION,
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="Changes sync to Services Provided Today dropdowns and Billing. "
            "Type controls where each code appears (CMT, E/M, or Therapy).",
            bg=COLOR_BG_APP,
            fg=COLOR_MUTED,
            font=FONT_BASE,
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        card, body = make_card(outer, "All codes")
        card.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("cpt", "mod", "label", "typ", "cash", "pi")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=12)
        for col, title, w in [
            ("cpt", "CPT", 58),
            ("mod", "Mod", 40),
            ("label", "Short label", 240),
            ("typ", "Type", 56),
            ("cash", "Cash $", 68),
            ("pi", "PI/UCR $", 68),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form_card, form = make_card(outer, "Add or edit")
        form_card.pack(fill="x", pady=(0, 10))

        r1 = tk.Frame(form, bg=COLOR_CARD)
        r1.pack(fill="x", pady=2)
        self.cpt_var = tk.StringVar()
        self.mod_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.type_var = tk.StringVar(value="therapy")
        self._catalog_em_long = ""
        for lbl, var, w in [
            ("CPT", self.cpt_var, 8),
            ("Mod", self.mod_var, 5),
            ("Short label", self.label_var, 32),
        ]:
            tk.Label(r1, text=lbl, bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).pack(side="left", padx=(0, 4))
            ttk.Entry(r1, textvariable=var, width=w).pack(side="left", padx=(0, 12))

        type_col = tk.Frame(r1, bg=COLOR_CARD)
        type_col.pack(side="left", padx=(0, 12))
        tk.Label(type_col, text="Type", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).pack(anchor="w")
        ttk.Combobox(
            type_col,
            textvariable=self.type_var,
            values=["cmt", "em", "therapy"],
            state="readonly",
            width=10,
        ).pack(anchor="w")
        self.em_long_btn = tk.Button(
            type_col,
            text="EM Long Desc.",
            command=self._open_em_long_popup,
            relief="flat",
            font=FONT_BASE,
            cursor="hand2",
        )
        self.em_long_btn.pack(anchor="w", pady=(4, 0))

        r2 = tk.Frame(form, bg=COLOR_CARD)
        r2.pack(fill="x", pady=(6, 2))
        self.cash_var = tk.StringVar(value="0.00")
        self.pi_var = tk.StringVar(value="0.00")
        tk.Label(r2, text="Cash $", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).pack(side="left")
        ttk.Entry(r2, textvariable=self.cash_var, width=10).pack(side="left", padx=(4, 12))
        tk.Label(r2, text="PI/UCR $", bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).pack(side="left")
        ttk.Entry(r2, textvariable=self.pi_var, width=10).pack(side="left", padx=(4, 12))

        tk.Button(
            r2,
            text="Save row",
            command=self._save_row,
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            relief="flat",
            font=FONT_BASE_BOLD,
            padx=12,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            r2,
            text="Clear form",
            command=self._clear_form,
            relief="flat",
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            r2,
            text="Deactivate selected",
            command=self._deactivate,
            relief="flat",
            fg=COLOR_MUTED,
            font=FONT_BASE,
            cursor="hand2",
        ).pack(side="right")

        self.type_var.trace_add("write", lambda *_: self._sync_em_long_btn())
        self._selected_id: str | None = None
        self._reload_tree()
        self._clear_form()
        self._sync_em_long_btn()

        btn_row = tk.Frame(outer, bg=COLOR_BG_APP)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="Close", command=self._close, relief="flat", cursor="hand2").pack(side="right")

    def _reload_tree(self) -> None:
        self._schedules = load_fee_schedules()
        self.tree.delete(*self.tree.get_children())
        cash = self._schedules.get("cash") or {}
        pi = self._schedules.get("pi_ucr") or {}
        for it in get_active_items():
            cpt = str(it.get("cpt") or "")
            iid = str(it.get("id") or cpt)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    cpt,
                    it.get("modifier") or "",
                    (it.get("short_description") or "")[:40],
                    category_label(str(it.get("category") or "")),
                    f"{float(cash.get(cpt, 0)):,.2f}",
                    f"{float(pi.get(cpt, 0)):,.2f}",
                ),
            )

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        it = find_item_by_id(iid)
        if not it:
            return
        self._selected_id = iid
        self.cpt_var.set(str(it.get("cpt") or ""))
        self.mod_var.set(str(it.get("modifier") or ""))
        self.label_var.set(str(it.get("short_description") or ""))
        self.type_var.set(str(it.get("category") or "therapy"))
        self._catalog_em_long = (
            str(it.get("long_description") or "")
            if str(it.get("category") or "").lower() == "em"
            else ""
        )
        cpt = str(it.get("cpt") or "")
        self.cash_var.set(f"{float((self._schedules.get('cash') or {}).get(cpt, 0)):,.2f}")
        self.pi_var.set(f"{float((self._schedules.get('pi_ucr') or {}).get(cpt, 0)):,.2f}")
        self._sync_em_long_btn()

    def _clear_form(self) -> None:
        self._selected_id = None
        self.cpt_var.set("")
        self.mod_var.set("")
        self.label_var.set("")
        self.type_var.set("therapy")
        self.cash_var.set("0.00")
        self.pi_var.set("0.00")
        self._catalog_em_long = ""
        self.tree.selection_remove(self.tree.selection())
        self._sync_em_long_btn()

    def _sync_em_long_btn(self) -> None:
        is_em = (self.type_var.get() or "").strip().lower() == "em"
        if is_em:
            self.em_long_btn.config(state="normal")
        else:
            self.em_long_btn.config(state="disabled")
            self._catalog_em_long = ""

    def _open_em_long_popup(self) -> None:
        if (self.type_var.get() or "").strip().lower() != "em":
            return

        def _on_save(text: str) -> None:
            self._catalog_em_long = text
            cpt = (self.cpt_var.get() or "").strip()
            if not cpt:
                messagebox.showinfo(
                    "CPT required",
                    "Enter a CPT code before saving the long description.",
                    parent=self,
                )
                return
            try:
                saved = save_em_long_description(
                    text,
                    cpt=cpt,
                    modifier=(self.mod_var.get() or "").strip(),
                    short_description=(self.label_var.get() or "").strip(),
                    item_id=self._selected_id,
                )
                self._catalog_em_long = saved
            except ValueError as e:
                messagebox.showerror("Cannot save", str(e), parent=self)

        initial = self._catalog_em_long
        if not initial and self._selected_id:
            it = find_item_by_id(self._selected_id)
            if it:
                initial = default_em_long_for_line(format_display_line(it))
        EmLongDescriptionDialog(
            self,
            initial_text=initial,
            on_save=_on_save,
        )

    def _parse_money(self, raw: str) -> float:
        return float((raw or "0").replace(",", "").replace("$", "").strip() or "0")

    def _save_row(self) -> None:
        cpt = (self.cpt_var.get() or "").strip()
        if not cpt:
            messagebox.showinfo("CPT required", "Enter a CPT code.", parent=self)
            return
        try:
            cash = self._parse_money(self.cash_var.get())
            pi = self._parse_money(self.pi_var.get())
            cat = (self.type_var.get() or "therapy").strip()
            long_kw: dict = {}
            if cat == "em":
                long_kw["long_description"] = self._catalog_em_long
            rec = upsert_catalog_item(
                cpt=cpt,
                modifier=(self.mod_var.get() or "").strip(),
                short_description=(self.label_var.get() or "").strip(),
                category=cat,
                cash=cash,
                pi_ucr=pi,
                item_id=self._selected_id,
                **long_kw,
            )
        except ValueError as e:
            messagebox.showerror("Cannot save", str(e), parent=self)
            return
        self._selected_id = rec.get("id")
        self._reload_tree()
        preview = format_display_line(rec)
        messagebox.showinfo(
            "Saved",
            f"Saved to catalog and fee schedule.\n\n"
            f"Appears in: {category_label(str(rec.get('category')))}\n"
            f"Display: {preview}",
            parent=self,
        )

    def _deactivate(self) -> None:
        if not self._selected_id:
            messagebox.showinfo("Select a row", "Select a code to deactivate.", parent=self)
            return
        it = find_item_by_id(self._selected_id)
        if it and str(it.get("cpt")) == NO_CMT_CODE:
            messagebox.showinfo("Protected", "No CMT (0000) must stay available.", parent=self)
            return
        if not messagebox.askyesno(
            "Deactivate",
            "Hide this code from new visits? (Existing saved exams are unchanged.)",
            parent=self,
        ):
            return
        try:
            set_item_active(self._selected_id, False)
        except ValueError as e:
            messagebox.showerror("Error", str(e), parent=self)
            return
        self._clear_form()
        self._reload_tree()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass
