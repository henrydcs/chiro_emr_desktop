# family_social_history_page.py — Family/Social: multi-block UI (HOI-style) + per-block note builder.
from __future__ import annotations

import copy
import json
import os
import uuid
from tkinter import messagebox, simpledialog, ttk

import tkinter as tk

from paths import get_data_dir

from family_social_section_core import (
    DEFAULT_TEMPLATES,
    FamilySocialSectionCore,
    TEMPLATES_FILENAME,
)

# Exam JSON key `family_social_builder` top-level version (wraps per-block builder states).
BUILDER_STATE_VERSION = 2

_FILE_VERSION = 2

_DEFAULT_BLOCK_SPECS: tuple[tuple[str, str], ...] = (
    ("fam", "Family history"),
    ("soc", "Social history"),
    ("edu", "Education & occupation"),
    ("sub", "Tobacco, alcohol, & substance use"),
    ("oth", "Other social history"),
)


def _deepcopy_templates() -> list[dict]:
    return copy.deepcopy(DEFAULT_TEMPLATES)


def _normalize_template_dd(dd: dict) -> None:
    if not isinstance(dd, dict):
        return
    dd.setdefault("multi", False)
    dd.setdefault("multi_bullets", False)


def _normalize_template_list(templates: list) -> list[dict]:
    out: list[dict] = []
    for t in templates or []:
        if not isinstance(t, dict):
            continue
        for dd in t.get("dropdowns") or []:
            _normalize_template_dd(dd if isinstance(dd, dict) else None)
        out.append(t)
    return out


def _default_sections() -> list[dict]:
    return [
        {"id": sid, "heading": label, "templates": _deepcopy_templates()}
        for sid, label in _DEFAULT_BLOCK_SPECS
    ]


def _coerce_sections_loaded(raw_sections: list) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for i, s in enumerate(raw_sections or []):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or f"sec{i}").strip() or f"sec{i}"
        if sid in seen:
            sid = f"{sid}_{i}"
        seen.add(sid)
        heading = str(s.get("heading") or f"Block {i + 1}").strip() or f"Block {i + 1}"
        tmpl = _normalize_template_list(list(s.get("templates") or []))
        if not tmpl:
            tmpl = _deepcopy_templates()
        out.append({"id": sid, "heading": heading, "templates": tmpl})
    return out if out else _default_sections()


def _load_sections_from_disk() -> list[dict]:
    path = str(get_data_dir() / TEMPLATES_FILENAME)
    if not os.path.exists(path):
        return _default_sections()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _default_sections()

    if isinstance(data, list) and data:
        for t in data:
            if isinstance(t, dict):
                for dd in t.get("dropdowns") or []:
                    _normalize_template_dd(dd if isinstance(dd, dict) else None)
        sections = _default_sections()
        if sections:
            sections[0]["templates"] = data
        return sections

    if isinstance(data, dict):
        if int(data.get("file_version") or 0) == _FILE_VERSION:
            secs = data.get("sections")
            if isinstance(secs, list) and secs:
                return _coerce_sections_loaded(secs)

    return _default_sections()


# Notebook-only style: theme-default tab colors; bold only on the selected tab.
_FAMILY_SOCIAL_NB_STYLE = "FamilySocial.TNotebook"
_FAMILY_SOCIAL_TAB_STYLE = f"{_FAMILY_SOCIAL_NB_STYLE}.Tab"


def _setup_family_social_notebook_style(master: tk.Misc) -> None:
    style = ttk.Style(master)
    style.configure(_FAMILY_SOCIAL_NB_STYLE, borderwidth=0, padding=0)
    style.configure(_FAMILY_SOCIAL_TAB_STYLE, font=("Segoe UI", 10))
    style.map(
        _FAMILY_SOCIAL_TAB_STYLE,
        font=[
            ("selected", ("Segoe UI", 10, "bold")),
            ("!selected", ("Segoe UI", 10, "normal")),
        ],
    )


class FamilySocialHistoryPage(ttk.Frame):
    """
    HOI-style block row + one FamilySocialSectionCore per block (own textbox & builder).
    Template JSON: { "file_version": 2, "sections": [ { id, heading, templates }, ... ] }
    """

    def __init__(self, parent, title: str, on_change_callback, app: tk.Misc | None = None):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self._app = app
        self.sections: list[dict] = _load_sections_from_disk()
        self._token_copy_feedback_var = tk.StringVar(value="")

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(header, text=title).pack(side="left", anchor="w")
        self._skip_section_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            header,
            text="Skip entire section for this visit (omit from Live Preview & PDF)",
            variable=self._skip_section_var,
            command=self._on_skip_section_toggled,
        ).pack(side="left", padx=(16, 0))

        top = ttk.Frame(outer)
        top.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(top, text="Family/Social Blocks:").pack(anchor="w")

        scroll_wrap = ttk.Frame(top)
        scroll_wrap.pack(fill="x", expand=True)

        self._blocks_hsb = ttk.Scrollbar(scroll_wrap, orient="horizontal")
        self._blocks_canvas = tk.Canvas(
            scroll_wrap,
            height=44,
            highlightthickness=0,
            borderwidth=0,
        )
        self._blocks_canvas.configure(xscrollcommand=self._blocks_hsb.set)
        self._blocks_hsb.configure(command=self._blocks_canvas.xview)

        self._blocks_canvas.grid(row=0, column=0, sticky="ew")
        self._blocks_hsb.grid(row=1, column=0, sticky="ew")
        scroll_wrap.columnconfigure(0, weight=1)

        self.block_buttons = ttk.Frame(self._blocks_canvas)
        self._blocks_canvas_win = self._blocks_canvas.create_window(
            (0, 0),
            window=self.block_buttons,
            anchor="nw",
        )

        self.block_buttons.bind("<Configure>", self._on_family_social_blocks_inner_configure)
        self._blocks_canvas.bind("<Configure>", self._on_family_social_blocks_canvas_configure)

        _setup_family_social_notebook_style(self)
        self.nb = ttk.Notebook(outer, style=_FAMILY_SOCIAL_NB_STYLE)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        self.tab_note = ttk.Frame(self.nb)
        self.tab_canvas = ttk.Frame(self.nb)
        self.tab_manage = ttk.Frame(self.nb)
        self.nb.add(self.tab_note, text="Note & builder")
        self.nb.add(self.tab_canvas, text="Template editor (Canvas)")
        self.nb.add(self.tab_manage, text="Sub-sections")

        self.container = ttk.Frame(self.tab_note)
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self._section_buttons: dict[str, tk.Button] = {}
        self._cores_by_id: dict[str, FamilySocialSectionCore] = {}
        self.frames: dict[str, ttk.Frame] = {}
        self._subsection_listbox: tk.Listbox | None = None

        for sec in self.sections:
            self._mount_section_core(sec)

        self._rebuild_block_buttons()
        first_sid = self.sections[0]["id"] if self.sections else ""
        self.active_block_id = tk.StringVar(value=first_sid)
        if self.sections:
            self.after_idle(lambda: self._show_block(self.sections[0]["id"]))

        self._build_subsection_manager_tab()
        self.nb.bind("<<NotebookTabChanged>>", self._on_nb_tab_changed)

    def _on_skip_section_toggled(self) -> None:
        app = self._app
        if app is not None and hasattr(app, "request_live_preview_refresh"):
            try:
                app.request_live_preview_refresh()
            except Exception:
                pass
        self.on_change_callback()

    def get_section_skipped(self) -> bool:
        return bool(self._skip_section_var.get())

    def set_section_skipped(self, skipped: bool) -> None:
        self._skip_section_var.set(bool(skipped))

    def _on_family_social_blocks_inner_configure(self, _event=None) -> None:
        self._sync_family_social_blocks_scroll()

    def _on_family_social_blocks_canvas_configure(self, event: tk.Event) -> None:
        try:
            h = int(event.height)
            if h > 1:
                self._blocks_canvas.itemconfigure(self._blocks_canvas_win, height=h)
        except (tk.TclError, ValueError, TypeError):
            pass
        self._sync_family_social_blocks_scroll()

    def _sync_family_social_blocks_scroll(self) -> None:
        cv = getattr(self, "_blocks_canvas", None)
        if cv is None:
            return
        try:
            cv.update_idletasks()
            bbox = cv.bbox("all")
            if bbox:
                cv.configure(scrollregion=bbox)
        except tk.TclError:
            pass

    @staticmethod
    def _alloc_section_id() -> str:
        return f"s_{uuid.uuid4().hex[:12]}"

    def _mount_section_core(self, sec: dict) -> str:
        sid = sec["id"]
        if sid in self.frames:
            return sid
        shell = ttk.Frame(self.container)
        shell.grid(row=0, column=0, sticky="nsew")
        self.frames[sid] = shell
        core = FamilySocialSectionCore(
            shell,
            on_change_callback=self.on_change_callback,
            app=self._app,
            section=sec,
            persist_all_callback=self._persist_templates_to_disk,
            token_feedback_var=self._token_copy_feedback_var,
        )
        core.pack(fill="both", expand=True)
        self._cores_by_id[sid] = core
        return sid

    def _rebuild_block_buttons(self) -> None:
        for w in self.block_buttons.winfo_children():
            w.destroy()
        self._section_buttons.clear()
        active = self.active_block_id.get() if hasattr(self, "active_block_id") else ""
        for sec in self.sections:
            sid = sec["id"]
            btn = tk.Button(
                self.block_buttons,
                text=sec["heading"],
                font=("Segoe UI", 10),
                relief="raised",
                bd=1,
                command=lambda i=sid: self._show_block(i),
            )
            btn.pack(side="left", padx=4)
            self._section_buttons[sid] = btn
        if active and active in self._section_buttons:
            self._section_buttons[active].configure(font=("Segoe UI", 10, "bold"))
        elif self.sections:
            self._section_buttons[self.sections[0]["id"]].configure(font=("Segoe UI", 10, "bold"))
        self.after_idle(self._sync_family_social_blocks_scroll)

    def _build_subsection_manager_tab(self) -> None:
        intro = ttk.Frame(self.tab_manage)
        intro.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(
            intro,
            text=(
                "Sub-sections appear as block buttons above (left → right = print order in Live Preview / PDF). "
                "Add, rename, reorder, or delete here — changes are saved for this workstation."
            ),
            wraplength=720,
        ).pack(anchor="w")

        mid = ttk.Frame(self.tab_manage)
        mid.pack(fill="both", expand=True, padx=10, pady=8)

        lb_frame = ttk.Frame(mid)
        lb_frame.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lb_frame, orient="vertical")
        self._subsection_listbox = tk.Listbox(lb_frame, height=14, activestyle="dotbox", exportselection=False)
        self._subsection_listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._subsection_listbox.configure(yscrollcommand=sb.set)
        sb.configure(command=self._subsection_listbox.yview)

        self._subsection_listbox.bind("<Double-Button-1>", self._on_subsection_listbox_double)

        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=(14, 6))

        ttk.Label(side, text="New sub-heading").pack(anchor="w")
        self._new_subheading_var = tk.StringVar(value="")
        ttk.Entry(side, textvariable=self._new_subheading_var, width=34).pack(fill="x", pady=(0, 8))

        ttk.Button(side, text="Add sub-section", command=self._subsection_add).pack(fill="x", pady=2)
        ttk.Button(side, text="Rename selected…", command=self._subsection_rename).pack(fill="x", pady=2)
        ttk.Button(side, text="Move up", command=lambda: self._subsection_move(-1)).pack(fill="x", pady=2)
        ttk.Button(side, text="Move down", command=lambda: self._subsection_move(1)).pack(fill="x", pady=2)
        ttk.Button(side, text="Delete selected…", command=self._subsection_delete).pack(fill="x", pady=2)

        self._refresh_subsection_listbox()

    def _refresh_subsection_listbox(self) -> None:
        lb = self._subsection_listbox
        if lb is None:
            return
        lb.delete(0, tk.END)
        for sec in self.sections:
            lb.insert(tk.END, sec.get("heading") or sec.get("id") or "")

    def _on_subsection_listbox_double(self, _e=None) -> None:
        lb = self._subsection_listbox
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            return
        sid = self.sections[int(sel[0])]["id"]
        try:
            self.nb.select(self.tab_note)
        except Exception:
            pass
        self._show_block(sid)

    def _subsection_add(self) -> None:
        heading = (self._new_subheading_var.get() or "").strip()
        if not heading:
            messagebox.showwarning(
                "Sub-heading required",
                "Enter a sub-heading label (e.g. “Occupational history”), then click Add sub-section.",
            )
            return
        sid = self._alloc_section_id()
        self.sections.append(
            {"id": sid, "heading": heading, "templates": _deepcopy_templates()}
        )
        self._mount_section_core(self.sections[-1])
        self._rebuild_block_buttons()
        self._show_block(sid)
        self._new_subheading_var.set("")
        self._refresh_subsection_listbox()
        try:
            if self._subsection_listbox is not None:
                self._subsection_listbox.selection_clear(0, tk.END)
                self._subsection_listbox.selection_set(len(self.sections) - 1)
        except Exception:
            pass
        self._persist_templates_to_disk()
        self.on_change_callback()

    def _subsection_rename(self) -> None:
        lb = self._subsection_listbox
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Select a row", "Select a sub-section in the list first.")
            return
        i = int(sel[0])
        sec = self.sections[i]
        sid = sec["id"]
        new_h = simpledialog.askstring(
            "Rename sub-section",
            "Sub-heading (sentence case recommended):",
            initialvalue=sec.get("heading") or "",
            parent=self.winfo_toplevel(),
        )
        if new_h is None:
            return
        new_h = new_h.strip()
        if not new_h:
            messagebox.showwarning("Invalid name", "Sub-heading cannot be empty.")
            return
        sec["heading"] = new_h
        btn = self._section_buttons.get(sid)
        if btn is not None:
            btn.configure(text=new_h)
        self._refresh_subsection_listbox()
        lb.selection_set(i)
        self._persist_templates_to_disk()
        self.on_change_callback()

    def _subsection_move(self, delta: int) -> None:
        lb = self._subsection_listbox
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Select a row", "Select a sub-section in the list first.")
            return
        i = int(sel[0])
        j = i + delta
        if j < 0 or j >= len(self.sections):
            return
        self.sections[i], self.sections[j] = self.sections[j], self.sections[i]
        self._rebuild_block_buttons()
        self._refresh_subsection_listbox()
        lb.selection_set(j)
        self._persist_templates_to_disk()
        self.on_change_callback()

    def _subsection_delete(self) -> None:
        lb = self._subsection_listbox
        if lb is None:
            return
        if len(self.sections) <= 1:
            messagebox.showinfo(
                "Cannot delete",
                "At least one sub-section must remain.",
            )
            return
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Select a row", "Select a sub-section in the list first.")
            return
        i = int(sel[0])
        sec = self.sections[i]
        sid = sec["id"]
        heading = sec.get("heading") or sid
        if not messagebox.askyesno(
            "Delete sub-section",
            f"Delete “{heading}” and its sentence-builder templates on this machine?\n\n"
            "Text already saved inside past exam files is not removed from those files.",
        ):
            return
        self.sections.pop(i)
        self._destroy_block_ui(sid)
        self._rebuild_block_buttons()
        next_sid = self.sections[min(i, len(self.sections) - 1)]["id"]
        self._show_block(next_sid)
        self._refresh_subsection_listbox()
        try:
            lb.selection_set(min(i, len(self.sections) - 1))
        except Exception:
            pass
        if self.nb.index(self.nb.select()) == 1:
            self._mount_canvas_for_active()
        self._persist_templates_to_disk()
        self.on_change_callback()

    def _destroy_block_ui(self, sid: str) -> None:
        self._cores_by_id.pop(sid, None)
        fr = self.frames.pop(sid, None)
        if fr is not None:
            try:
                fr.destroy()
            except Exception:
                pass

    def _on_nb_tab_changed(self, _e=None) -> None:
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            return
        if idx == 1:
            self._mount_canvas_for_active()

    def _mount_canvas_for_active(self) -> None:
        sid = self.active_block_id.get()
        core = self._cores_by_id.get(sid)
        if core is None:
            return
        core.mount_canvas_editor(self.tab_canvas)

    def _persist_templates_to_disk(self) -> None:
        path = str(get_data_dir() / TEMPLATES_FILENAME)
        payload = {
            "file_version": _FILE_VERSION,
            "sections": [
                {
                    "id": str(s["id"]),
                    "heading": str(s.get("heading") or ""),
                    "templates": copy.deepcopy(s.get("templates") or []),
                }
                for s in self.sections
            ],
        }
        for sec in payload["sections"]:
            for t in sec.get("templates") or []:
                if isinstance(t, dict):
                    for dd in t.get("dropdowns") or []:
                        if isinstance(dd, dict):
                            dd.pop("_ghost_lbl", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _show_block(self, sid: str) -> None:
        if sid not in self.frames:
            return
        self.active_block_id.set(sid)
        self.frames[sid].tkraise()
        for bid, btn in self._section_buttons.items():
            btn.configure(
                font=("Segoe UI", 10, "bold") if bid == sid else ("Segoe UI", 10)
            )
        self.on_change_callback()
        try:
            if self.nb.index(self.nb.select()) == 1:
                self._mount_canvas_for_active()
        except Exception:
            pass

    def focus_subsection_for_preview_line(self, line: str) -> bool:
        """
        Live Preview click on a subsection heading: open Family/Social, Note & builder tab,
        and select the block whose heading matches `line` (exact, trimmed).
        """
        line = (line or "").strip()
        if not line:
            return False
        for sec in self.sections:
            h = (sec.get("heading") or "").strip()
            if h == line:
                app = self._app
                if app is not None and hasattr(app, "show_page"):
                    app.show_page("Family/Social History", scroll_live_preview=False)
                try:
                    self.nb.select(self.tab_note)
                except Exception:
                    pass
                self._show_block(sec["id"])
                return True
        return False

    # --- TextPage-style API ---

    def get_value(self) -> str:
        parts: list[str] = []
        for sec in self.sections:
            c = self._cores_by_id.get(sec["id"])
            if c is None:
                continue
            t = c.get_value().strip()
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()

    def get_live_preview_runs(self) -> list[tuple[str, str | None]]:
        if self._skip_section_var.get():
            return []
        runs: list[tuple[str, str | None]] = []
        wrote_header = False
        for sec in self.sections:
            sid = sec["id"]
            core = self._cores_by_id.get(sid)
            if core is None:
                continue
            t = core.get_value().strip()
            if not t:
                continue
            if not wrote_header:
                runs.append(("FAMILY / SOCIAL HISTORY\n", "H_BOLD"))
                runs.append(("\n", None))
                wrote_header = True
            else:
                runs.append(("\n\n", None))
            h = (sec.get("heading") or "").strip()
            if h:
                runs.append((h + "\n", "LP_FS_SUBHEAD"))
                runs.append(("\n", None))
            runs.append((t + "\n", None))
        return runs

    def get_builder_state(self) -> dict:
        blocks: list[dict] = []
        for sec in self.sections:
            sid = sec["id"]
            core = self._cores_by_id.get(sid)
            if core is None:
                continue
            inner = core.get_builder_state()
            blocks.append(
                {
                    "id": sid,
                    "heading": sec.get("heading") or "",
                    "text": core.get_value(),
                    "builder": inner,
                }
            )
        return {"v": BUILDER_STATE_VERSION, "blocks": blocks}

    def set_value(self, value: str, *, builder_state: dict | None = None) -> None:
        raw = builder_state if isinstance(builder_state, dict) else None
        if raw and int(raw.get("v") or 0) == BUILDER_STATE_VERSION:
            by_id: dict[str, dict] = {}
            for b in raw.get("blocks") or []:
                if isinstance(b, dict) and b.get("id") is not None:
                    by_id[str(b["id"])] = b
            for sec in self.sections:
                sid = sec["id"]
                blk = by_id.get(sid, {})
                c = self._cores_by_id.get(sid)
                if c is None:
                    continue
                inner = blk.get("builder") if isinstance(blk.get("builder"), dict) else None
                txt = blk.get("text") if "text" in blk else ""
                if txt is None:
                    txt = ""
                c.set_value(str(txt), builder_state=inner)
            return

        # Legacy v1: one shared builder blob + combined note text
        if self.sections:
            first_id = self.sections[0]["id"]
            first = self._cores_by_id.get(first_id)
            if first is not None:
                first.set_value(value or "", builder_state=raw)
            for sec in self.sections[1:]:
                c = self._cores_by_id.get(sec["id"])
                if c is not None:
                    c.set_value("", builder_state=None)

    def has_content(self) -> bool:
        return any(c.has_content() for c in self._cores_by_id.values())

    def reset(self) -> None:
        self._skip_section_var.set(False)
        for c in self._cores_by_id.values():
            c.reset()

    def tkraise(self, *args, **kwargs):
        super().tkraise(*args, **kwargs)
        sid = self.active_block_id.get()
        c = self._cores_by_id.get(sid)
        if c is not None and hasattr(c, "_wire_mousewheel"):
            c._wire_mousewheel()


__all__ = [
    "BUILDER_STATE_VERSION",
    "DEFAULT_TEMPLATES",
    "FamilySocialHistoryPage",
    "TEMPLATES_FILENAME",
]
