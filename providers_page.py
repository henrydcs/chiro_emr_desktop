# providers_page.py — Clinic provider directory.
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from providers_storage import (
    delete_provider,
    list_providers,
    new_provider_id,
    provider_label,
    upsert_provider,
)
from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    make_card,
)


class ProvidersPage(tk.Frame):
    def __init__(self, parent: tk.Misc, shell):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell
        self._build()
        self.bind("<Map>", lambda _e: self.refresh(), add="+")
        self.refresh()

    def _build(self) -> None:
        wrap = tk.Frame(self, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(wrap, text="Providers", bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=FONT_TITLE).pack(anchor="w")
        tk.Label(
            wrap,
            text="Doctors and clinicians who appear on visits, SOAP notes, and appointments.",
            bg=COLOR_BG_APP, fg=COLOR_MUTED, font=FONT_BASE,
        ).pack(anchor="w", pady=(4, 14))

        card, body = make_card(wrap, "Provider roster", "Active providers show in Schedule")
        card.pack(fill="both", expand=True)
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)

        toolbar = tk.Frame(body, bg=COLOR_CARD)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Button(
            toolbar, text="+ Add Provider", command=self._add_provider,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=12, pady=5, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            toolbar, text="Edit", command=self._edit_selected,
            bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat",
            font=FONT_BASE_BOLD, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            toolbar, text="Delete", command=self._delete_selected,
            bg=COLOR_CARD, fg="#B91C1C", relief="flat",
            font=FONT_BASE, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="left")
        tk.Button(
            toolbar, text="Refresh", command=self.refresh,
            bg=COLOR_CARD, fg=COLOR_TEXT, relief="flat",
            font=FONT_BASE, highlightthickness=1,
            highlightbackground=COLOR_BORDER, padx=10, pady=5, cursor="hand2",
        ).pack(side="right")

        tree_wrap = tk.Frame(body, bg=COLOR_CARD)
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        cols = ("name", "credentials", "npi", "phone", "email", "default", "active")
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=14)
        for col, title, width in [
            ("name", "Name", 180),
            ("credentials", "Credentials", 90),
            ("npi", "NPI", 100),
            ("phone", "Phone", 110),
            ("email", "Email", 180),
            ("default", "Default", 70),
            ("active", "Active", 60),
        ]:
            self.tree.heading(col, text=title, anchor="center")
            self.tree.column(col, width=width, anchor="center")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-Button-1>", lambda _e: self._edit_selected())

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in list_providers():
            self.tree.insert(
                "",
                "end",
                iid=row.get("provider_id") or "",
                values=(
                    row.get("display_name") or "",
                    row.get("credentials") or "",
                    row.get("npi") or "",
                    row.get("phone") or "",
                    row.get("email") or "",
                    "Yes" if row.get("is_default") else "",
                    "Yes" if row.get("active", True) else "No",
                ),
            )

    def _selected_id(self) -> str:
        sel = self.tree.selection()
        return str(sel[0]) if sel else ""

    def _selected_row(self) -> dict | None:
        from providers_storage import find_provider
        pid = self._selected_id()
        return find_provider(pid) if pid else None

    def _add_provider(self) -> None:
        ProviderEditDialog(
            self,
            row={"provider_id": new_provider_id(), "active": True, "is_default": False},
            on_saved=lambda _r: self.refresh(),
        )

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if not row:
            messagebox.showinfo("Edit provider", "Select a provider first.", parent=self)
            return
        ProviderEditDialog(self, row=row, on_saved=lambda _r: self.refresh())

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if not row:
            messagebox.showinfo("Delete provider", "Select a provider first.", parent=self)
            return
        label = provider_label(row)
        if not messagebox.askyesno(
            "Delete provider",
            f"Remove {label} from the roster?",
            parent=self,
        ):
            return
        delete_provider(row.get("provider_id") or "")
        self.refresh()


class ProviderEditDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, *, row: dict, on_saved: callable | None = None):
        super().__init__(master)
        is_new = not any(
            (r.get("provider_id") or "") == (row.get("provider_id") or "")
            for r in list_providers()
        )
        self.title("Add provider" if is_new else "Edit provider")
        self.configure(bg=COLOR_CARD)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self._row = dict(row)
        self._on_saved = on_saved
        self._is_new = is_new

        self._build()
        self.update_idletasks()
        self.geometry("420x520")
        self.minsize(420, 480)
        self.resizable(True, True)

    def _build(self) -> None:
        outer = tk.Frame(self, bg=COLOR_CARD)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        wrap = tk.Frame(outer, bg=COLOR_CARD)
        wrap.grid(row=0, column=0, sticky="nsew", padx=16, pady=(14, 8))

        tk.Label(
            wrap,
            text="Add provider" if self._is_new else "Edit provider",
            bg=COLOR_CARD, fg=COLOR_TEXT, font=FONT_BASE_BOLD,
        ).pack(anchor="w", pady=(0, 10))

        fields = [
            ("Display name", "display_name"),
            ("Credentials (e.g. DC)", "credentials"),
            ("NPI", "npi"),
            ("Phone", "phone"),
            ("Email", "email"),
        ]
        self._vars: dict[str, tk.StringVar] = {}
        for label, key in fields:
            tk.Label(wrap, text=label, bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_SMALL).pack(anchor="w")
            var = tk.StringVar(value=(self._row.get(key) or ""))
            self._vars[key] = var
            tk.Entry(
                wrap, textvariable=var, font=FONT_BASE,
                relief="solid", bd=1, highlightthickness=1,
                highlightbackground=COLOR_BORDER,
            ).pack(fill="x", ipady=4, pady=(2, 8))

        self._default_var = tk.BooleanVar(value=bool(self._row.get("is_default")))
        tk.Checkbutton(
            wrap, text="Default provider for new visits",
            variable=self._default_var, bg=COLOR_CARD, fg=COLOR_TEXT,
            font=FONT_BASE, activebackground=COLOR_CARD,
        ).pack(anchor="w", pady=(0, 4))

        self._active_var = tk.BooleanVar(value=bool(self._row.get("active", True)))
        tk.Checkbutton(
            wrap, text="Active (show in Schedule)",
            variable=self._active_var, bg=COLOR_CARD, fg=COLOR_TEXT,
            font=FONT_BASE, activebackground=COLOR_CARD,
        ).pack(anchor="w", pady=(0, 4))

        btn_bar = tk.Frame(
            outer, bg="#F8FAFC",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
        )
        btn_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        btns = tk.Frame(btn_bar, bg="#F8FAFC", padx=4, pady=10)
        btns.pack(fill="x")
        tk.Button(
            btns, text="Cancel", command=self.destroy,
            bg="#F8FAFC", fg=COLOR_MUTED, relief="flat", font=FONT_BASE,
            padx=8, cursor="hand2",
        ).pack(side="right", padx=(6, 0))
        save_text = "Add provider" if self._is_new else "Save"
        tk.Button(
            btns, text=save_text, command=self._save,
            bg=COLOR_ACCENT, fg="#FFFFFF", relief="flat",
            font=FONT_BASE_BOLD, padx=16, pady=6, cursor="hand2",
        ).pack(side="right")

    def _save(self) -> None:
        name = (self._vars["display_name"].get() or "").strip()
        if not name:
            messagebox.showerror("Provider", "Display name is required.", parent=self)
            return
        payload = dict(self._row)
        for key, var in self._vars.items():
            payload[key] = (var.get() or "").strip()
        payload["is_default"] = bool(self._default_var.get())
        payload["active"] = bool(self._active_var.get())
        saved = upsert_provider(payload)
        if self._on_saved:
            self._on_saved(saved)
        self.destroy()
