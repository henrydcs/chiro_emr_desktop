# demographics_styling.py — Shell look for embedded Insurance / Attorneys panels.
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from shell_app import (
    COLOR_ACCENT,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_MUTED,
    COLOR_SIDEBAR_ACTIVE_BG,
    COLOR_SIDEBAR_ACTIVE_FG,
    COLOR_TEXT,
    FONT_BASE,
    FONT_BASE_BOLD,
    FONT_SECTION,
    FONT_SMALL,
)

PREFIX = "Demographics"


def setup_demographics_ttk_theme(root: tk.Misc) -> None:
    """Register ttk styles that match shell_app / Patients tab."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    p = PREFIX

    style.configure(f"{p}.TFrame", background=COLOR_BG_APP)
    style.configure(f"{p}.Card.TFrame", background=COLOR_CARD)

    style.configure(
        f"{p}.TNotebook",
        background=COLOR_BG_APP,
        borderwidth=0,
        tabmargins=[2, 4, 2, 0],
    )
    style.configure(
        f"{p}.TNotebook.Tab",
        background=COLOR_CARD,
        foreground=COLOR_TEXT,
        padding=[12, 6],
        font=FONT_BASE,
        borderwidth=0,
    )
    style.map(
        f"{p}.TNotebook.Tab",
        background=[("selected", COLOR_SIDEBAR_ACTIVE_BG)],
        foreground=[("selected", COLOR_SIDEBAR_ACTIVE_FG)],
        font=[("selected", FONT_BASE_BOLD), ("!selected", FONT_BASE)],
    )

    style.configure(
        f"{p}.Treeview",
        background=COLOR_CARD,
        fieldbackground=COLOR_CARD,
        foreground=COLOR_TEXT,
        rowheight=28,
        borderwidth=0,
        font=FONT_BASE,
    )
    style.configure(
        f"{p}.Treeview.Heading",
        background="#F8FAFC",
        foreground=COLOR_MUTED,
        font=("Segoe UI", 9, "bold"),
        relief="flat",
    )
    style.layout(f"{p}.Treeview", [(f"{p}.Treeview.treearea", {"sticky": "nswe"})])

    for suffix, fg, font in (
        ("TLabel", COLOR_TEXT, FONT_BASE),
        ("Muted.TLabel", COLOR_MUTED, FONT_SMALL),
        ("Title.TLabel", COLOR_TEXT, ("Segoe UI", 13, "bold")),
        ("Section.TLabel", COLOR_TEXT, FONT_SECTION),
        ("Heading.TLabel", COLOR_TEXT, ("Segoe UI", 12, "bold")),
        ("Italic.TLabel", COLOR_MUTED, ("Segoe UI", 10, "italic")),
    ):
        style.configure(
            f"{p}.{suffix}",
            background=COLOR_BG_APP,
            foreground=fg,
            font=font,
        )
        style.configure(
            f"{p}.Card.{suffix}",
            background=COLOR_CARD,
            foreground=fg,
            font=font,
        )

    style.configure(
        f"{p}.TLabelframe",
        background=COLOR_CARD,
        foreground=COLOR_TEXT,
        bordercolor=COLOR_BORDER,
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        f"{p}.TLabelframe.Label",
        background=COLOR_CARD,
        foreground=COLOR_TEXT,
        font=FONT_BASE_BOLD,
    )

    style.configure(f"{p}.TEntry", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT)
    style.configure(f"{p}.TCombobox", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT)
    style.configure(f"{p}.TSeparator", background=COLOR_BORDER)


class DemographicsShellThemeMixin:
    """Widget factories for shell-themed embedded demographics panels."""

    _shell_theme: bool = False

    def _init_shell_theme(self, master: tk.Misc, shell_theme: bool) -> None:
        self._shell_theme = bool(shell_theme)
        if self._shell_theme:
            setup_demographics_ttk_theme(master)

    def _style(self, name: str, *, card: bool = False) -> str | None:
        if not self._shell_theme:
            return None
        prefix = f"{PREFIX}.Card" if card else PREFIX
        return f"{prefix}.{name}"

    def _mk_frame(self, parent, *, card: bool = False, **kw) -> ttk.Frame:
        st = self._style("TFrame", card=card)
        if st:
            kw["style"] = st
        return ttk.Frame(parent, **kw)

    def _mk_label(self, parent, *, card: bool = True, muted: bool = False,
                  title: bool = False, section: bool = False,
                  heading: bool = False, italic: bool = False, **kw) -> ttk.Label:
        if self._shell_theme:
            if muted:
                kw["style"] = self._style("Muted.TLabel", card=card)
            elif title:
                kw["style"] = self._style("Title.TLabel", card=card)
            elif section:
                kw["style"] = self._style("Section.TLabel", card=card)
            elif heading:
                kw["style"] = self._style("Heading.TLabel", card=card)
            elif italic:
                kw["style"] = self._style("Italic.TLabel", card=card)
            else:
                kw["style"] = self._style("TLabel", card=card)
            kw.pop("foreground", None)
            kw.pop("font", None)
        return ttk.Label(parent, **kw)

    def _mk_lf(self, parent, text: str, **kw) -> ttk.LabelFrame:
        st = self._style("TLabelframe", card=True)
        if st:
            kw["style"] = st
        return ttk.LabelFrame(parent, text=text, **kw)

    def _mk_tree(self, parent, **kw) -> ttk.Treeview:
        st = self._style("Treeview", card=False)
        if st:
            kw["style"] = st
        return ttk.Treeview(parent, **kw)

    def _mk_btn(
        self,
        parent,
        text: str,
        command,
        *,
        accent: bool = False,
        **pack_kw,
    ) -> tk.Button | ttk.Button:
        if self._shell_theme:
            if accent:
                btn = tk.Button(
                    parent,
                    text=text,
                    command=command,
                    bg=COLOR_ACCENT,
                    fg="white",
                    relief="flat",
                    bd=0,
                    font=FONT_BASE_BOLD,
                    padx=12,
                    pady=5,
                    cursor="hand2",
                    activebackground="#1D4ED8",
                    activeforeground="white",
                )
            else:
                btn = tk.Button(
                    parent,
                    text=text,
                    command=command,
                    bg=COLOR_CARD,
                    fg=COLOR_TEXT,
                    relief="flat",
                    bd=0,
                    font=FONT_BASE,
                    padx=10,
                    pady=5,
                    cursor="hand2",
                    highlightbackground=COLOR_BORDER,
                    highlightthickness=1,
                    activebackground=COLOR_SIDEBAR_ACTIVE_BG,
                )
            if pack_kw:
                btn.pack(**pack_kw)
            return btn
        btn = ttk.Button(parent, text=text, command=command)
        if pack_kw:
            btn.pack(**pack_kw)
        return btn

    def _set_widget_enabled(self, widget, enabled: bool) -> None:
        """Enable/disable ttk or tk buttons consistently."""
        if isinstance(widget, tk.Button):
            widget.configure(state="normal" if enabled else "disabled")
            return
        try:
            widget.state(["!disabled"] if enabled else ["disabled"])
        except Exception:
            pass

    def _mk_text_card(self, parent) -> tk.Text:
        """Read-only text area styled like a shell card."""
        if self._shell_theme:
            return tk.Text(
                parent,
                wrap="word",
                bg=COLOR_CARD,
                fg=COLOR_TEXT,
                font=FONT_BASE,
                relief="flat",
                highlightbackground=COLOR_BORDER,
                highlightthickness=1,
                bd=0,
            )
        return tk.Text(parent, wrap="word")
