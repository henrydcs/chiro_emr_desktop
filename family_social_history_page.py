# family_social_history_page.py — Family/Social: multi-block UI (HOI-style) + per-block note builder.
from __future__ import annotations

import copy
import json
import os
from tkinter import ttk

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
        ttk.Label(outer, text=title).pack(anchor="w", padx=10, pady=(8, 4))

        top = ttk.Frame(outer)
        top.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(top, text="Family/Social Blocks:").pack(side="left", padx=(0, 8))

        self.block_buttons = ttk.Frame(top)
        self.block_buttons.pack(side="left", fill="x", expand=True)

        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        self.tab_note = ttk.Frame(self.nb)
        self.tab_canvas = ttk.Frame(self.nb)
        self.nb.add(self.tab_note, text="Note & builder")
        self.nb.add(self.tab_canvas, text="Template editor (Canvas)")

        self.container = ttk.Frame(self.tab_note)
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self._section_buttons: dict[str, tk.Button] = {}
        self._cores_by_id: dict[str, FamilySocialSectionCore] = {}
        self._id_order: list[str] = []
        self.frames: dict[str, ttk.Frame] = {}

        for sec in self.sections:
            sid = sec["id"]
            self._id_order.append(sid)
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

        self.active_block_id = tk.StringVar(value=self._id_order[0] if self._id_order else "")
        if self._id_order:
            self.after_idle(lambda: self._show_block(self._id_order[0]))

        self.nb.bind("<<NotebookTabChanged>>", self._on_nb_tab_changed)

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

    # --- TextPage-style API ---

    def get_value(self) -> str:
        parts: list[str] = []
        for sid in self._id_order:
            c = self._cores_by_id.get(sid)
            if c is None:
                continue
            t = c.get_value().strip()
            if t:
                parts.append(t)
        return "\n\n".join(parts).strip()

    def get_live_preview_runs(self) -> list[tuple[str, str | None]]:
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
                runs.append((h + "\n", "LP_LABEL_BOLD"))
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
        if self._id_order:
            first_id = self._id_order[0]
            first = self._cores_by_id.get(first_id)
            if first is not None:
                first.set_value(value or "", builder_state=raw)
            for sid in self._id_order[1:]:
                c = self._cores_by_id.get(sid)
                if c is not None:
                    c.set_value("", builder_state=None)

    def has_content(self) -> bool:
        return any(c.has_content() for c in self._cores_by_id.values())

    def reset(self) -> None:
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
