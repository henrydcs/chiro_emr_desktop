# insurance_catalog_dialog.py — Clinic insurance catalog editor (Phase 3).
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from insurance_billing_storage import load_insurance_catalog, save_insurance_catalog
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    make_card,
)


class InsuranceCatalogDialog(tk.Toplevel):
  def __init__(self, parent: tk.Misc):
    super().__init__(parent)
    self.title("Insurance catalog — payers & plans")
    self.geometry("820x560")
    self.minsize(680, 440)
    self.configure(bg=COLOR_BG_APP)
    self.transient(parent.winfo_toplevel())
    self.grab_set()

    self._catalog = load_insurance_catalog()
    self._plans: list[dict] = list(self._catalog.get("plans") or [])

    outer = tk.Frame(self, bg=COLOR_BG_APP)
    outer.pack(fill="both", expand=True, padx=16, pady=16)
    tk.Label(
      outer,
      text="Insurance catalog",
      bg=COLOR_BG_APP,
      fg=COLOR_TEXT,
      font=FONT_SECTION,
    ).pack(anchor="w")
    tk.Label(
      outer,
      text="Plans define which CPT codes require prior authorization (requires_auth_for). "
      "Match plan_id on the patient policy or carrier_id when plan_id is blank.",
      bg=COLOR_BG_APP,
      fg=COLOR_MUTED,
      font=FONT_BASE,
      wraplength=760,
      justify="left",
    ).pack(anchor="w", pady=(0, 8))

    card, body = make_card(outer, "Plans")
    card.pack(fill="both", expand=True, pady=(0, 10))
    cols = ("plan_id", "carrier", "name", "auth_cpts")
    self.tree = ttk.Treeview(body, columns=cols, show="headings", height=10)
    for col, title, w in [
      ("plan_id", "Plan ID", 120),
      ("carrier", "Carrier ID", 100),
      ("name", "Name", 180),
      ("auth_cpts", "Requires auth (CPTs)", 280),
    ]:
      self.tree.heading(col, text=title)
      self.tree.column(col, width=w, anchor="w")
    self.tree.pack(fill="both", expand=True, side="left")
    vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
    self.tree.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    self.tree.bind("<<TreeviewSelect>>", self._on_select)

    form = tk.Frame(outer, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER)
    form.pack(fill="x", pady=(0, 8))
    inner = tk.Frame(form, bg=COLOR_CARD, padx=10, pady=10)
    inner.pack(fill="x")
    self.plan_id_var = tk.StringVar()
    self.carrier_var = tk.StringVar()
    self.name_var = tk.StringVar()
    self.auth_var = tk.StringVar()
    for row, (label, var) in enumerate(
      [
        ("Plan ID", self.plan_id_var),
        ("Carrier ID", self.carrier_var),
        ("Plan name", self.name_var),
        ("Requires auth CPTs (comma-separated)", self.auth_var),
      ]
    ):
      tk.Label(inner, text=label, bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE).grid(
        row=row, column=0, sticky="w", pady=3
      )
      tk.Entry(inner, textvariable=var, width=52).grid(row=row, column=1, sticky="ew", pady=3)
    inner.columnconfigure(1, weight=1)

    btns = tk.Frame(outer, bg=COLOR_BG_APP)
    btns.pack(fill="x")
    tk.Button(
      btns,
      text="Add plan",
      command=self._add_plan,
      bg=COLOR_CARD,
      fg=COLOR_ACCENT,
      relief="flat",
      font=FONT_BASE_BOLD,
      padx=10,
      pady=4,
      cursor="hand2",
    ).pack(side="left", padx=(0, 6))
    tk.Button(
      btns,
      text="Save plan",
      command=self._save_plan,
      bg=COLOR_ACCENT,
      fg="#FFFFFF",
      relief="flat",
      font=FONT_BASE_BOLD,
      padx=10,
      pady=4,
      cursor="hand2",
    ).pack(side="left", padx=(0, 6))
    tk.Button(
      btns,
      text="Remove plan",
      command=self._remove_plan,
      bg=COLOR_CARD,
      fg=COLOR_TEXT,
      relief="flat",
      font=FONT_BASE,
      padx=10,
      pady=4,
      cursor="hand2",
    ).pack(side="left", padx=(0, 6))
    tk.Button(
      btns,
      text="Close",
      command=self.destroy,
      relief="flat",
      font=FONT_BASE,
      padx=12,
      pady=4,
      cursor="hand2",
    ).pack(side="right")

    self._reload_tree()

  def _reload_tree(self) -> None:
    self.tree.delete(*self.tree.get_children())
    for i, p in enumerate(self._plans):
      auth = ", ".join(p.get("requires_auth_for") or [])
      iid = str(i)
      self.tree.insert(
        "",
        "end",
        iid=iid,
        values=(
          p.get("plan_id") or "",
          p.get("carrier_id") or "",
          p.get("name") or "",
          auth,
        ),
      )

  def _on_select(self, _e=None) -> None:
    sel = self.tree.selection()
    if not sel:
      return
    p = self._plans[int(sel[0])]
    self.plan_id_var.set(p.get("plan_id") or "")
    self.carrier_var.set(p.get("carrier_id") or "")
    self.name_var.set(p.get("name") or "")
    self.auth_var.set(", ".join(p.get("requires_auth_for") or []))

  def _parse_auth_cpts(self) -> list[str]:
    raw = (self.auth_var.get() or "").replace(";", ",")
    return [c.strip() for c in raw.split(",") if c.strip()]

  def _add_plan(self) -> None:
    self._plans.append(
      {
        "plan_id": f"plan_{len(self._plans) + 1}",
        "carrier_id": "",
        "name": "New plan",
        "requires_auth_for": [],
      }
    )
    self._reload_tree()

  def _save_plan(self) -> None:
    pid = (self.plan_id_var.get() or "").strip()
    if not pid:
      messagebox.showerror("Catalog", "Plan ID is required.", parent=self)
      return
    entry = {
      "plan_id": pid,
      "carrier_id": (self.carrier_var.get() or "").strip(),
      "name": (self.name_var.get() or "").strip(),
      "requires_auth_for": self._parse_auth_cpts(),
    }
    replaced = False
    for i, p in enumerate(self._plans):
      if (p.get("plan_id") or "") == pid:
        self._plans[i] = entry
        replaced = True
        break
    if not replaced:
      self._plans.append(entry)
    cat = copy.deepcopy(self._catalog)
    cat["plans"] = self._plans
    save_insurance_catalog(cat)
    self._catalog = cat
    self._reload_tree()
    messagebox.showinfo("Catalog", "Plan saved.", parent=self)

  def _remove_plan(self) -> None:
    pid = (self.plan_id_var.get() or "").strip()
    if not pid:
      return
    self._plans = [p for p in self._plans if (p.get("plan_id") or "") != pid]
    cat = copy.deepcopy(self._catalog)
    cat["plans"] = self._plans
    save_insurance_catalog(cat)
    self._catalog = cat
    self._reload_tree()
