# family_social_section_core.py — One Family/Social sub-section (Note builder + template Canvas).
from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from tkinter import ttk, messagebox

import tkinter as tk

from paths import get_data_dir
from utils import today_mmddyyyy

TEMPLATES_FILENAME = "family_social_doc_templates.json"
# Stored in exam JSON under soap["family_social_builder"]; restores multi-select and
# per-exam Narrative vs Bullet lines (multi_bullets) after reload.
# Optional key "visit_skip": { "template_id": bool, ... } for per-template skip checkboxes.
SECTION_BUILDER_VERSION = 1
_BUILDER_SLOT_DEFAULT = object()

# Prepended to each builder dropdown (not stored in JSON). Selecting it drops that clause from output.
OPTION_OMIT = "(Omit — exclude from sentence)"
TEMPLATE_BAND_COLORS = ("#9D9D9D", "#C5C5C5")

# Template editor: button bank order — keep aligned with keys returned by `_format_context`.
PREFIX_PLACEHOLDER_TOKEN_KEYS: tuple[str, ...] = (
    "age",
    "sex",
    "he_she",
    "he_her",
    "him_her",
    "his_hers",
    "firstName",
    "lastName",
    "dob",
    "doi",
)


def _is_omit_phrase(text: str) -> bool:
    return (text or "").strip() == OPTION_OMIT


def _age_from_dob(dob_mmddyyyy: str, ref_mmddyyyy: str) -> str:
    dob_mmddyyyy = (dob_mmddyyyy or "").strip()
    ref_mmddyyyy = (ref_mmddyyyy or "").strip()
    if not dob_mmddyyyy or not ref_mmddyyyy:
        return ""
    try:
        birth = datetime.strptime(dob_mmddyyyy, "%m/%d/%Y")
        ref = datetime.strptime(ref_mmddyyyy, "%m/%d/%Y")
        age = ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))
        if age < 0:
            return ""
        return str(age)
    except Exception:
        return ""


def _finalize_sentence(parts: list[str]) -> str:
    chunks: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if s:
            chunks.append(s)
    if not chunks:
        return ""
    out = " ".join(chunks).strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out


def _finalize_family_social_block(parts: list[str]) -> str:
    """Join prefix + dropdown fragments; fragments starting with newline (bullet blocks) attach without a leading space."""
    chunks: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p)
        if not s.strip():
            continue
        if s.startswith("\n"):
            chunks.append(s.rstrip())
        else:
            chunks.append(s.strip())
    if not chunks:
        return ""
    out = chunks[0]
    for c in chunks[1:]:
        if c.startswith("\n"):
            out += c
        else:
            out += " " + c
    out = out.strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out


def _prefix_before_bullet_list(rp: str) -> str:
    """Suffix ':' on the prefix when a tabbed bullet list follows; skip if ':' already present."""
    s = (rp or "").rstrip()
    if not s:
        return s
    if s.endswith(":"):
        return s
    return s + ":"


def _join_with_oxford_and(items: list[str]) -> str:
    """Join phrases like “A, B, and C” (Oxford comma before “and”)."""
    parts = [str(x).strip() for x in items if str(x).strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


DEFAULT_TEMPLATES: list[dict] = [
    {
        "id": 1,
        "prefix": "The patient is a {age} year old {sex} who is ",
        "dropdowns": [
            {
                "label": "General appearance / status",
                "items": [
                    "healthy with no known health issues discussed today",
                    "well-appearing and in no acute distress",
                    "well-developed and well-nourished",
                    "alert, cooperative, and oriented appropriately to conversation",
                    "in mild distress but cooperative with examination",
                    "in moderate distress",
                    "chronically ill-appearing though alert",
                    "frail-appearing with deconditioning",
                    "presenting for routine follow-up of musculoskeletal complaints",
                    "presenting for evaluation of new symptoms as documented elsewhere in this record",
                ],
            },
            {
                "label": "Relevant medical context (optional phrasing)",
                "items": [
                    "with no significant past medical history reported",
                    "with a history of hypertension",
                    "with a history of Type 2 Diabetes Mellitus",
                    "with a history of cervical/lumbar spine surgery (details in record)",
                    "with multiple medical comorbidities as listed in the problem list",
                    "with medical history deferred; focus on today's musculoskeletal complaint",
                ],
            },
        ],
    },
    {
        "id": 2,
        "prefix": "Family history is ",
        "dropdowns": [
            {
                "label": "Family history",
                "items": [
                    "non-contributory to today's presentation",
                    "unknown or unable to obtain at this visit",
                    "contributory as documented below in the clinical note",
                    "significant for premature cardiovascular disease in first-degree relatives",
                    "significant for Type 2 Diabetes Mellitus in first-degree relatives",
                    "notable for autoimmune disease in family members",
                    "positive for malignancy in first-degree relatives (details deferred)",
                ],
            }
        ],
    },
]


class FamilySocialSectionCore(ttk.Frame):
    """
    One sub-section: sentence builder + note + template Canvas (mounted by orchestrator).
    Mutates `section` dict in place: keys id, heading, templates.
    """

    def __init__(
        self,
        parent,
        on_change_callback,
        app: tk.Misc | None,
        section: dict,
        persist_all_callback,
        token_feedback_var: tk.StringVar | None = None,
    ):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self._app = app
        self.section = section
        self.templates = section.setdefault("templates", [])
        self._persist_all = persist_all_callback
        self.note_combo_vars: list[list[tk.StringVar]] = []
        self._note_builder_meta: list[list[dict]] = []
        self._visit_skip_by_tid: dict[int, bool] = {}
        self._skip_checkbox_vars: dict[int, tk.BooleanVar] = {}
        if token_feedback_var is not None:
            self._token_copy_feedback_var = token_feedback_var
        else:
            self._token_copy_feedback_var = tk.StringVar(value="")
        self._clear_token_copy_msg_after_id = None

        self._build_note_tab(self)
        self._mw_bound = False

        if self._app is not None:
            try:
                self._app.dob_var.trace_add("write", lambda *_: self._on_demographics_changed())
                self._app.exam_date_var.trace_add("write", lambda *_: self._on_demographics_changed())
                for attr in ("first_name_var", "last_name_var", "doi_var"):
                    v = getattr(self._app, attr, None)
                    if v is not None and hasattr(v, "trace_add"):
                        v.trace_add("write", lambda *_: self._on_demographics_changed())
                hp = getattr(self._app, "hoi_page", None)
                if hp is not None and hasattr(hp, "sex_var"):
                    hp.sex_var.trace_add("write", lambda *_: self._on_demographics_changed())
            except Exception:
                pass

        self._render_note_builder()
        self._wire_mousewheel()

    def mount_canvas_editor(self, host: ttk.Frame) -> None:
        for w in host.winfo_children():
            w.destroy()
        self._build_canvas_tab(host)
        self._render_canvas_editor()

    def refresh_heading_label(self) -> None:
        """Reserved for future in-frame titles; block buttons show the heading."""
        return

    # --- persistence (orchestrator writes JSON; core only signals save) ---
    def _ask_dropdown_mode(self, *, title: str, prompt: str) -> bool | None:
        """
        Ask whether a new dropdown is single- or multi-select.
        Returns True for multiple, False for single, None if cancelled.
        """
        result: list[bool | None] = [None]
        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title(title)
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        dlg.grab_set()
        ttk.Label(dlg, text=prompt, wraplength=460).pack(padx=18, pady=(14, 10))

        def _single() -> None:
            result[0] = False
            dlg.destroy()

        def _multi() -> None:
            result[0] = True
            dlg.destroy()

        def _cancel() -> None:
            result[0] = None
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(pady=(0, 14))
        ttk.Button(bf, text="Single choice", width=16, command=_single).pack(side="left", padx=4)
        ttk.Button(bf, text="Multiple choice", width=16, command=_multi).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", width=10, command=_cancel).pack(side="left", padx=4)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        dlg.wait_window(dlg)
        return result[0]

    def _save_templates_file(self) -> None:
        self._persist_all()

    def _sanitize_templates_for_save(self) -> list[dict]:
        out: list[dict] = []
        for t in self.templates:
            out.append(
                {
                    "id": int(t["id"]),
                    "prefix": str(t.get("prefix") or ""),
                    "dropdowns": copy.deepcopy(t.get("dropdowns") or []),
                }
            )
        return out

    def _persist_templates(self) -> None:
        for t in self.templates:
            t.pop("_ghost_lbl", None)
        self._save_templates_file()

    # --- demographics & HOI sex (Type of Injury / MOI) ---
    def _hoi_sex_raw(self) -> str:
        if self._app is None:
            return ""
        try:
            hp = getattr(self._app, "hoi_page", None)
            if hp is not None and hasattr(hp, "sex_var"):
                return (hp.sex_var.get() or "").strip()
        except Exception:
            pass
        return ""

    def _sex_token_for_sentence(self) -> str:
        """
        Word inserted for {sex} in prefix templates.
        Uses HOI Sex: male / female; unknown → patient.
        """
        raw = self._hoi_sex_raw()
        if raw in ("", "(unknown)"):
            return "patient"
        return raw.lower()

    @staticmethod
    def _pronoun_placeholders(raw_sex: str) -> dict[str, str]:
        """Match HOI `_pronouns` semantics; keys are template token names."""
        s = (raw_sex or "").strip().lower()
        if s.startswith("m"):
            return {"he_she": "he", "him_her": "him", "his_hers": "his"}
        if s.startswith("f"):
            return {"he_she": "she", "him_her": "her", "his_hers": "her"}
        return {"he_she": "they", "him_her": "them", "his_hers": "their"}

    def _format_context(self) -> dict[str, str]:
        age = ""
        ref = today_mmddyyyy()
        firstName = ""
        lastName = ""
        dob = ""
        doi = ""
        if self._app is not None:
            try:
                ref = (self._app.exam_date_var.get() or "").strip() or ref
                age = _age_from_dob(self._app.dob_var.get(), ref)
            except Exception:
                age = ""
            try:
                fnv = getattr(self._app, "first_name_var", None)
                lnv = getattr(self._app, "last_name_var", None)
                dbv = getattr(self._app, "dob_var", None)
                doiv = getattr(self._app, "doi_var", None)
                if fnv is not None:
                    firstName = (fnv.get() or "").strip()
                if lnv is not None:
                    lastName = (lnv.get() or "").strip()
                if dbv is not None:
                    dob = (dbv.get() or "").strip()
                if doiv is not None:
                    doi = (doiv.get() or "").strip()
            except Exception:
                pass
        if not age:
            age = "____"
        sex = self._sex_token_for_sentence()
        pro = self._pronoun_placeholders(self._hoi_sex_raw())
        subj = pro["he_she"]
        return {
            "age": age,
            "sex": sex,
            "he_she": subj,
            "he_her": subj,
            "him_her": pro["him_her"],
            "his_hers": pro["his_hers"],
            "firstName": firstName,
            "lastName": lastName,
            "dob": dob,
            "doi": doi,
        }

    def _resolve_vars(self, text: str) -> str:
        ctx = self._format_context()
        try:
            return (text or "").format(**ctx)
        except (KeyError, ValueError, IndexError):
            return text or ""

    def _refresh_resolved_prefix_labels(self) -> None:
        labels = getattr(self, "_prefix_resolved_labels", None) or []
        for i, tmpl in enumerate(self.templates):
            if i >= len(labels):
                break
            pv = self._resolve_vars(tmpl.get("prefix") or "")
            try:
                labels[i].configure(text=f"Prefix (resolved): {pv}")
            except Exception:
                pass

    def _on_demographics_changed(self) -> None:
        self._update_age_hint()
        self._refresh_resolved_prefix_labels()
        self._apply_builder_to_note()

    def _update_age_hint(self) -> None:
        if not hasattr(self, "age_hint_var"):
            return
        ctx = self._format_context()
        self.age_hint_var.set(
            "Live sample: "
            f"age={ctx['age']}, sex={ctx['sex']}, "
            f"{ctx['he_she']}/{ctx['him_her']}/{ctx['his_hers']}, "
            f"name={ctx['firstName'] or '—'} {ctx['lastName'] or '—'}"
        )

    # --- note tab ---
    def _build_note_tab(self, parent: ttk.Frame) -> None:
        # Outer note-tab scroller (for smaller laptop heights). Existing inner builder
        # and canvas-editor wheel behavior remains independent.
        note_canvas = tk.Canvas(parent, highlightthickness=0)
        note_sb = ttk.Scrollbar(parent, orient="vertical", command=note_canvas.yview)
        note_canvas.configure(yscrollcommand=note_sb.set)
        note_canvas.pack(side="left", fill="both", expand=True)
        note_sb.pack(side="right", fill="y")

        note_inner = ttk.Frame(note_canvas)
        note_window = note_canvas.create_window((0, 0), window=note_inner, anchor="nw")

        def _sync_note_scrollregion(_e=None) -> None:
            note_canvas.configure(scrollregion=note_canvas.bbox("all"))

        def _sync_note_inner_width(event: tk.Event) -> None:
            note_canvas.itemconfigure(note_window, width=event.width)

        note_inner.bind("<Configure>", _sync_note_scrollregion)
        note_canvas.bind("<Configure>", _sync_note_inner_width)

        self.note_tab_canvas = note_canvas
        self._note_tab_outer = parent

        demo_row = ttk.Frame(note_inner)
        demo_row.pack(fill="x", padx=10, pady=(4, 2))
        ttk.Label(
            demo_row,
            text="Dropdown selections update the note, Live Preview, and PDF automatically. Edit the textbox for one-off wording.",
            foreground="gray",
        ).pack(side="left")

        self.age_hint_var = tk.StringVar(value="")
        ttk.Label(demo_row, textvariable=self.age_hint_var, foreground="gray").pack(side="left", padx=(12, 0))

        ctl = ttk.Frame(note_inner)
        ctl.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(
            ctl,
            text="Revert note to builder (discard manual edits in textbox)",
            command=self._apply_builder_to_note,
        ).pack(side="left")

        builder_outer = ttk.LabelFrame(note_inner, text="Sentence builder")
        builder_outer.pack(fill="x", expand=False, padx=10, pady=(0, 6))
        self._note_builder_outer = builder_outer

        canvas = tk.Canvas(builder_outer, highlightthickness=0, height=440)
        sb = ttk.Scrollbar(builder_outer, orient="vertical", command=canvas.yview)
        self.note_scroll_frame = ttk.Frame(canvas)
        self.note_scroll_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.note_scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.note_builder_canvas = canvas

        ttk.Label(note_inner, text="Note text (editable — saved to chart, Live Preview, and PDF):").pack(
            anchor="w", padx=10, pady=(4, 2)
        )
        self.text = tk.Text(note_inner, width=110, height=12, wrap="word")
        self.text.pack(fill="x", expand=False, padx=10, pady=(0, 8))
        self.text.bind("<KeyRelease>", lambda e: self._on_note_text_changed())

    @staticmethod
    def _widget_is_descendant_of(ancestor: tk.Widget | None, w: tk.Widget | None) -> bool:
        if ancestor is None or w is None:
            return False
        cur: tk.Widget | None = w
        while cur is not None:
            try:
                if cur == ancestor:
                    return True
                cur = cur.master  # type: ignore[assignment]
            except Exception:
                break
        return False

    @staticmethod
    def _is_wheel_local_widget(w: tk.Widget) -> bool:
        """Widgets whose mousewheel should not move the outer sentence-builder / canvas-editor canvas."""
        if isinstance(w, (tk.Listbox, tk.Text, tk.Entry, tk.Spinbox, tk.Scrollbar)):
            return True
        if isinstance(w, (ttk.Combobox, ttk.Entry, ttk.Spinbox, ttk.Scrollbar)):
            return True
        try:
            cls = w.winfo_class()
        except Exception:
            return False
        return cls in (
            "Listbox",
            "Text",
            "Entry",
            "TEntry",
            "TCombobox",
            "TSpinbox",
            "Scrollbar",
            "TScrollbar",
        )

    def _wheel_should_stay_local(self, w: tk.Widget | None) -> bool:
        if w is None:
            return False
        cur: tk.Widget | None = w
        while cur is not None:
            try:
                if self._is_wheel_local_widget(cur):
                    return True
                cur = cur.master  # type: ignore[assignment]
            except Exception:
                break
        return False

    def _bind_listbox_mousewheel_local(self, lb: tk.Listbox) -> None:
        """Keep wheel inside the listbox so the template editor canvas does not scroll."""

        def _on_wheel(e: tk.Event, box: tk.Listbox = lb) -> str:
            if getattr(e, "delta", 0):
                box.yview_scroll(int(-1 * (e.delta / 120)), "units")
            elif getattr(e, "num", None) == 4:
                box.yview_scroll(-1, "units")
            elif getattr(e, "num", None) == 5:
                box.yview_scroll(1, "units")
            return "break"

        lb.bind("<MouseWheel>", _on_wheel)
        lb.bind("<Button-4>", _on_wheel)
        lb.bind("<Button-5>", _on_wheel)

    def _scroll_canvas_y(self, canvas: tk.Canvas, event: tk.Event) -> bool:
        """Return True if wheel was handled (Windows delta or Linux b4/b5)."""
        if getattr(event, "delta", 0):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return True
        if getattr(event, "num", None) == 4:
            canvas.yview_scroll(-1, "units")
            return True
        if getattr(event, "num", None) == 5:
            canvas.yview_scroll(1, "units")
            return True
        return False

    def _on_builder_mousewheel(self, event: tk.Event) -> str | None:
        """Scroll sentence builder or template editor canvas when pointer is over that region."""
        try:
            top = self.winfo_toplevel()
            w = top.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return None

        if self._wheel_should_stay_local(w):
            return None

        co = getattr(self, "_canvas_editor_outer", None)
        ce = getattr(self, "canvas_editor_widget", None)
        if (
            co is not None
            and ce is not None
            and w is not None
            and self._widget_is_descendant_of(co, w)
        ):
            if self._scroll_canvas_y(ce, event):
                return "break"
            return None

        no = getattr(self, "_note_builder_outer", None)
        nb = getattr(self, "note_builder_canvas", None)
        if (
            no is not None
            and nb is not None
            and w is not None
            and self._widget_is_descendant_of(no, w)
        ):
            if self._scroll_canvas_y(nb, event):
                return "break"
            return None

        nt = getattr(self, "_note_tab_outer", None)
        nc = getattr(self, "note_tab_canvas", None)
        if nt is not None and nc is not None and w is not None and self._widget_is_descendant_of(nt, w):
            if self._scroll_canvas_y(nc, event):
                return "break"
            return None
        return None

    def _wire_mousewheel(self) -> None:
        if self._mw_bound:
            return
        top = self.winfo_toplevel()
        try:
            top.bind("<MouseWheel>", self._on_builder_mousewheel, add="+")
            top.bind("<Button-4>", self._on_builder_mousewheel, add="+")
            top.bind("<Button-5>", self._on_builder_mousewheel, add="+")
            self._mw_bound = True
        except Exception:
            pass

    def _on_note_text_changed(self) -> None:
        self.on_change_callback()

    def _on_builder_selection_changed(self) -> None:
        # Always push builder output to the note so Omit / dropdown changes reach Live Preview & PDF.
        self._apply_builder_to_note()

    def _visit_skip_toggled(self, tid: int, var: tk.BooleanVar) -> None:
        """Sync skip flag after Tk commits the checkbutton value, then refresh the note."""

        def _sync() -> None:
            self._visit_skip_by_tid[tid] = var.get()
            self._apply_builder_to_note()
            self.on_change_callback()

        # after_idle: on some platforms the bound BooleanVar is not updated before command runs.
        self.after_idle(_sync)

    def _restore_visit_skip_from_state(self, raw: dict | None) -> None:
        """Rebuild _visit_skip_by_tid from saved exam JSON; clear when state missing / legacy."""
        self._visit_skip_by_tid.clear()
        if raw is None:
            self._sync_skip_checkbuttons()
            return
        if raw.get("v") != SECTION_BUILDER_VERSION:
            self._sync_skip_checkbuttons()
            return
        vs_raw = raw.get("visit_skip")
        if isinstance(vs_raw, dict):
            for k, v in vs_raw.items():
                try:
                    self._visit_skip_by_tid[int(k)] = bool(v)
                except (TypeError, ValueError):
                    pass
        self._sync_skip_checkbuttons()

    def _sync_skip_checkbuttons(self) -> None:
        for tid, var in (getattr(self, "_skip_checkbox_vars", None) or {}).items():
            try:
                var.set(bool(self._visit_skip_by_tid.get(tid, False)))
            except tk.TclError:
                pass

    def _compose_parts_for_template(self, i: int, tmpl: dict) -> list[str]:
        """
        Build prefix + non-Omit dropdown fragments. If this template has at least one
        dropdown and every dropdown is Omit/empty, return [] so the prefix is not left
        orphaned (e.g. no bare "Family history is." or "hello.").
        """
        rp = (self._resolve_vars(tmpl.get("prefix") or "") or "").strip()
        dropdown_parts: list[str] = []
        dds = tmpl.get("dropdowns") or []
        meta_row = self._note_builder_meta[i] if i < len(self._note_builder_meta) else []
        if i < len(self.note_combo_vars):
            for j, var in enumerate(self.note_combo_vars[i]):
                dd = dds[j] if j < len(dds) else {}
                is_multi = bool(dd.get("multi"))
                if is_multi and bool(dd.get("multi_bullets")) and j < len(meta_row):
                    meta = meta_row[j]
                    lb = meta.get("lb")
                    its = list(meta.get("items") or [])
                    appended = False
                    if isinstance(lb, tk.Listbox):
                        try:
                            if lb.winfo_exists():
                                sel = lb.curselection()
                                chosen = [str(its[k]).strip() for k in sel if 0 <= k < len(its)]
                                chosen = [x for x in chosen if x]
                                if chosen:
                                    block = "\n\n\t• " + "\n\t• ".join(chosen)
                                    dropdown_parts.append(block)
                                    appended = True
                        except Exception:
                            pass
                    if appended:
                        continue
                    val_fb = (var.get() or "").strip()
                    if not val_fb or _is_omit_phrase(val_fb):
                        continue
                    dropdown_parts.append(val_fb)
                    continue

                val = (var.get() or "").strip()
                if not val or _is_omit_phrase(val):
                    continue
                dropdown_parts.append(val)

        if i < len(self.note_combo_vars) and len(self.note_combo_vars[i]) > 0 and not dropdown_parts:
            return []

        has_bullet_fragment = any(str(p).startswith("\n") for p in dropdown_parts if p)
        rp_for_parts = _prefix_before_bullet_list(rp) if (rp and has_bullet_fragment) else rp

        parts: list[str] = []
        if rp_for_parts:
            parts.append(rp_for_parts)
        parts.extend(dropdown_parts)
        return parts

    def _compose_builder_text(self) -> str:
        blocks: list[str] = []
        for i, tmpl in enumerate(self.templates):
            if i >= len(self.note_combo_vars):
                break
            tid = int(tmpl["id"])
            if self._visit_skip_by_tid.get(tid, False):
                continue
            parts = self._compose_parts_for_template(i, tmpl)
            if not parts:
                continue
            sent = _finalize_family_social_block(parts)
            if sent:
                blocks.append(sent)
        return "\n\n".join(blocks).strip()

    def get_builder_state(self) -> dict:
        """Serializable dropdown selections for exam JSON. Multi slots use {"i": indices, "b": multi_bullets}."""
        out: dict = {"v": SECTION_BUILDER_VERSION, "templates": {}}
        for i, tmpl in enumerate(self.templates):
            if i >= len(self.note_combo_vars) or i >= len(self._note_builder_meta):
                break
            tid = str(int(tmpl["id"]))
            dds = tmpl.get("dropdowns") or []
            row = self.note_combo_vars[i]
            meta_row = self._note_builder_meta[i]
            dd_states: list = []
            for j, dd in enumerate(dds):
                if j >= len(row) or j >= len(meta_row):
                    break
                meta = meta_row[j]
                var = row[j]
                items = list(meta.get("items") or [])
                if meta.get("multi"):
                    lb = meta.get("lb")
                    idxs: list[int] = []
                    if isinstance(lb, tk.Listbox):
                        try:
                            if lb.winfo_exists():
                                idxs = [int(x) for x in lb.curselection()]
                        except Exception:
                            pass
                    dd_states.append({"i": idxs, "b": bool(dd.get("multi_bullets"))})
                else:
                    val = (var.get() or "").strip()
                    if _is_omit_phrase(val):
                        dd_states.append(None)
                    else:
                        try:
                            dd_states.append(items.index(val))
                        except ValueError:
                            dd_states.append(None)
            out["templates"][tid] = {"dropdowns": dd_states}
        visit_skip_out: dict[str, bool] = {}
        for tmpl in self.templates:
            ti = int(tmpl["id"])
            visit_skip_out[str(ti)] = bool(self._visit_skip_by_tid.get(ti, False))
        out["visit_skip"] = visit_skip_out
        return out

    def _apply_builder_state(self, state: dict | None) -> None:
        """Rebuild StringVars + listbox highlights from saved indices (or defaults if state missing / invalid)."""
        if not self.note_combo_vars or not self._note_builder_meta:
            return
        raw = state if isinstance(state, dict) else None
        tmap: dict = {}
        if raw and raw.get("v") == SECTION_BUILDER_VERSION:
            tm = raw.get("templates")
            if isinstance(tm, dict):
                tmap = tm

        self._restore_visit_skip_from_state(raw)

        for i, tmpl in enumerate(self.templates):
            if i >= len(self.note_combo_vars) or i >= len(self._note_builder_meta):
                break
            tid = str(int(tmpl["id"]))
            tdat = tmap.get(tid)
            sels = tdat.get("dropdowns") if isinstance(tdat, dict) else None
            if not isinstance(sels, list):
                sels = []
            dds = tmpl.get("dropdowns") or []
            row = self.note_combo_vars[i]
            meta_row = self._note_builder_meta[i]
            for j, dd in enumerate(dds):
                if j >= len(row) or j >= len(meta_row):
                    break
                meta = meta_row[j]
                var = row[j]
                items = list(meta.get("items") or [])
                raw_slot = sels[j] if j < len(sels) else _BUILDER_SLOT_DEFAULT

                if meta.get("multi"):
                    lb = meta.get("lb")
                    idxs: list[int] = []
                    bullets_override: bool | None = None
                    if raw_slot is not _BUILDER_SLOT_DEFAULT and isinstance(raw_slot, dict):
                        raw_i = raw_slot.get("i")
                        if isinstance(raw_i, list):
                            for x in raw_i:
                                try:
                                    idxs.append(int(x))
                                except (TypeError, ValueError):
                                    pass
                        if "b" in raw_slot:
                            bullets_override = bool(raw_slot["b"])
                    elif raw_slot is not _BUILDER_SLOT_DEFAULT and isinstance(raw_slot, list):
                        for x in raw_slot:
                            try:
                                idxs.append(int(x))
                            except (TypeError, ValueError):
                                pass
                    if bullets_override is not None:
                        dd["multi_bullets"] = bullets_override
                        fv = meta.get("fmt_var")
                        if isinstance(fv, tk.StringVar):
                            try:
                                fv.set("bullets" if bullets_override else "narrative")
                            except Exception:
                                pass
                    if isinstance(lb, tk.Listbox):
                        try:
                            lb.selection_clear(0, tk.END)
                            for ix in idxs:
                                if 0 <= ix < lb.size():
                                    lb.selection_set(ix)
                            sel_idx = lb.curselection()
                            chosen = [items[k] for k in sel_idx if 0 <= k < len(items)]
                            var.set(_join_with_oxford_and(chosen))
                        except Exception:
                            var.set("")
                    else:
                        var.set("")
                else:
                    if raw_slot is _BUILDER_SLOT_DEFAULT:
                        var.set(items[0] if items else OPTION_OMIT)
                    elif raw_slot is None:
                        var.set(OPTION_OMIT)
                    elif isinstance(raw_slot, int) and 0 <= raw_slot < len(items):
                        var.set(items[raw_slot])
                    else:
                        var.set(items[0] if items else OPTION_OMIT)

    def _apply_builder_to_note(self) -> None:
        body = self._compose_builder_text()
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", body)
        self._update_age_hint()
        self.on_change_callback()

    # --- builder render ---
    def _render_note_builder(self) -> None:
        snapshot: dict | None = None
        try:
            if self.note_combo_vars and self._note_builder_meta:
                snapshot = self.get_builder_state()
        except Exception:
            snapshot = None

        for w in self.note_scroll_frame.winfo_children():
            w.destroy()
        self.note_combo_vars = []
        self._note_builder_meta = []
        self._skip_checkbox_vars = {}

        self._prefix_resolved_labels: list[ttk.Label] = []

        for idx, tmpl in enumerate(self.templates):
            band = tk.Frame(self.note_scroll_frame, bg=self._template_band_bg(idx))
            band.pack(fill="x", padx=4, pady=4)

            card = ttk.LabelFrame(band, text=f"Template {tmpl['id']}")
            card.pack(fill="x", padx=5, pady=5)

            tid = int(tmpl["id"])
            skip_v = tk.BooleanVar(value=self._visit_skip_by_tid.get(tid, False))
            self._skip_checkbox_vars[tid] = skip_v

            def _skip_cmd(t: int = tid, v: tk.BooleanVar = skip_v) -> None:
                self._visit_skip_toggled(t, v)

            ttk.Checkbutton(
                card,
                text="Skip this block for this visit (exclude from builder / note)",
                variable=skip_v,
                command=_skip_cmd,
            ).pack(anchor="w", padx=8, pady=(4, 0))

            pv = self._resolve_vars(tmpl.get("prefix") or "")
            pl = ttk.Label(card, text=f"Prefix (resolved): {pv}", wraplength=560)
            pl.pack(anchor="w", padx=8, pady=(6, 2))
            self._prefix_resolved_labels.append(pl)

            row_vars: list[tk.StringVar] = []
            meta_row: list[dict] = []
            for dd in tmpl.get("dropdowns") or []:
                items = list(dd.get("items") or [])
                is_multi = bool(dd.get("multi"))
                fr = ttk.Frame(card)
                fr.pack(fill="x", padx=8, pady=3)
                if is_multi:
                    dd.setdefault("multi_bullets", False)
                    fmt_row = ttk.Frame(fr)
                    fmt_row.pack(anchor="w", fill="x", pady=(0, 4))
                    ttk.Label(fmt_row, text="Output format:").pack(side="left", padx=(0, 8))
                    _fmt_var = tk.StringVar(value="bullets" if dd.get("multi_bullets") else "narrative")

                    def _on_multi_format(_d=dd, _fv=_fmt_var) -> None:
                        _d["multi_bullets"] = _fv.get() == "bullets"
                        self._persist_templates()
                        self._apply_builder_to_note()
                        self.on_change_callback()

                    ttk.Radiobutton(
                        fmt_row,
                        text="Narrative",
                        variable=_fmt_var,
                        value="narrative",
                        command=_on_multi_format,
                    ).pack(side="left", padx=(0, 8))
                    ttk.Radiobutton(
                        fmt_row,
                        text="Bullet lines",
                        variable=_fmt_var,
                        value="bullets",
                        command=_on_multi_format,
                    ).pack(side="left")

                title = dd.get("label") or "Option"
                ttk.Label(
                    fr,
                    text=(title + ("" if not is_multi else " — select one or more")) + ":",
                ).pack(anchor="w")
                if is_multi:
                    var = tk.StringVar(value="")
                    lb_wrap = ttk.Frame(fr)
                    lb_wrap.pack(fill="x")
                    lb_h = min(max(len(items), 3), 10)
                    lb = tk.Listbox(
                        lb_wrap,
                        selectmode=tk.EXTENDED,
                        height=lb_h,
                        activestyle="dotbox",
                        exportselection=False,
                    )
                    for it in items:
                        lb.insert(tk.END, it)
                    lb.pack(side="left", fill="x", expand=True)
                    lsb = ttk.Scrollbar(lb_wrap, orient="vertical", command=lb.yview)
                    lb.configure(yscrollcommand=lsb.set)
                    lsb.pack(side="right", fill="y")

                    def _sync_multi(
                        _lb: tk.Listbox = lb,
                        _opts: list[str] = items,
                        _v: tk.StringVar = var,
                    ) -> None:
                        sel_idx = _lb.curselection()
                        chosen = [_opts[i] for i in sel_idx if 0 <= i < len(_opts)]
                        _v.set(_join_with_oxford_and(chosen))

                    # Bind sync via default args: `_sync_multi` is reassigned each loop iteration;
                    # bare name lookup in a nested def would call the *last* dropdown's sync only.
                    def _multi_changed(_e=None, _s=_sync_multi) -> None:
                        _s()
                        self._on_builder_selection_changed()

                    def _clear_multi(_lb=lb, _s=_sync_multi) -> None:
                        _lb.selection_clear(0, tk.END)
                        _s()
                        self._on_builder_selection_changed()

                    lb.bind("<<ListboxSelect>>", _multi_changed)
                    self._bind_listbox_mousewheel_local(lb)

                    ttk.Button(fr, text="Clear selection", command=_clear_multi).pack(anchor="w", pady=(2, 0))
                    ttk.Label(
                        fr,
                        text="Tip: Ctrl- or Shift-click to select multiple rows.",
                        font=("Segoe UI", 8),
                        foreground="gray",
                    ).pack(anchor="w", pady=(0, 0))
                    row_vars.append(var)
                    meta_row.append({"multi": True, "lb": lb, "items": items, "fmt_var": _fmt_var})
                else:
                    display_items = [OPTION_OMIT] + items
                    initial = items[0] if items else OPTION_OMIT
                    var = tk.StringVar(value=initial)
                    cb = ttk.Combobox(fr, textvariable=var, values=display_items, state="readonly", width=80)
                    cb.pack(fill="x")
                    cb.bind("<<ComboboxSelected>>", lambda e: self._on_builder_selection_changed())
                    row_vars.append(var)
                    meta_row.append({"multi": False, "lb": None, "items": items})

            self.note_combo_vars.append(row_vars)
            self._note_builder_meta.append(meta_row)

        self.note_scroll_frame.update_idletasks()
        self.note_builder_canvas.configure(scrollregion=self.note_builder_canvas.bbox("all"))
        self._update_age_hint()
        if snapshot is not None:
            try:
                self._apply_builder_state(snapshot)
            except Exception:
                pass

    @staticmethod
    def _template_band_bg(idx: int) -> str:
        return TEMPLATE_BAND_COLORS[idx % len(TEMPLATE_BAND_COLORS)]

    def _copy_prefix_token_to_clipboard(self, token_key: str) -> None:
        token = (token_key or "").strip()
        if not token:
            return
        snippet = "{" + token + "}"
        top = self.winfo_toplevel()
        try:
            top.clipboard_clear()
            top.clipboard_append(snippet)
            top.update_idletasks()
        except Exception:
            self._token_copy_feedback_var.set("Could not copy to the clipboard. Type the token manually.")
            return

        aid = self._clear_token_copy_msg_after_id
        if aid is not None:
            try:
                self.after_cancel(aid)
            except Exception:
                pass

        self._token_copy_feedback_var.set(f"Copied “{snippet}” — click the prefix field, then Ctrl+V or right‑click → Paste.")

        def _clear_msg() -> None:
            self._token_copy_feedback_var.set("")
            self._clear_token_copy_msg_after_id = None

        self._clear_token_copy_msg_after_id = self.after(6000, _clear_msg)

    def _build_prefix_token_bank(self, parent: ttk.Widget) -> None:
        """
        Single-row token strip for the Template editor: each click copies `{token}` to the clipboard.
        """
        shell = ttk.LabelFrame(
            parent,
            text="Placeholder picker (Template editor)",
        )
        shell.pack(fill="x", padx=8, pady=(0, 4))

        panel = tk.Frame(shell, highlightthickness=1, highlightbackground="#c8c8c8", bg="#f4f4f5")
        panel.pack(fill="x", padx=4, pady=(2, 3))

        row = tk.Frame(panel, bg="#f4f4f5")
        row.pack(fill="x", padx=6, pady=3)

        tk.Label(
            row,
            text="Click to copy; paste in prefix (Ctrl+V or right‑click → Paste).",
            font=("Segoe UI", 8),
            bg="#f4f4f5",
            fg="#333333",
        ).pack(side="left", padx=(0, 6))

        _btn_padx = 4
        _btn_pady = 2
        for key in PREFIX_PLACEHOLDER_TOKEN_KEYS:
            label = "{" + key + "}"
            tk.Button(
                row,
                text=label,
                font=("Segoe UI", 7),
                cursor="hand2",
                relief=tk.FLAT,
                bg="#ffffff",
                activebackground="#e8eef7",
                bd=0,
                padx=_btn_padx,
                pady=_btn_pady,
                command=lambda k=key: self._copy_prefix_token_to_clipboard(k),
            ).pack(side="left", padx=(0, 2))

        tk.Label(
            row,
            textvariable=self._token_copy_feedback_var,
            font=("Segoe UI", 7),
            fg="#1b5e3b",
            bg="#f4f4f5",
            anchor="w",
            wraplength=340,
        ).pack(side="left", padx=(10, 0))

    # --- canvas tab ---
    def _build_canvas_tab(self, parent: ttk.Frame) -> None:
        hdr = ttk.Frame(parent)
        hdr.pack(fill="x", padx=8, pady=6)
        ttk.Button(hdr, text="Save templates", command=self._save_and_reload).pack(side="right")
        ttk.Button(hdr, text="＋ Add template", command=self._add_template).pack(side="right", padx=(0, 8))
        ttk.Label(hdr, text="Edit template prefixes and dropdown items.").pack(side="left")

        self._build_prefix_token_bank(parent)

        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._canvas_editor_outer = outer

        cv = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        self.canvas_scroll_frame = ttk.Frame(cv)
        self.canvas_scroll_frame.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=self.canvas_scroll_frame, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas_editor_widget = cv

    def _render_canvas_editor(self) -> None:
        for w in self.canvas_scroll_frame.winfo_children():
            w.destroy()

        for idx, tmpl in enumerate(self.templates):
            self._build_template_editor_card(self.canvas_scroll_frame, tmpl, idx)

        self.canvas_scroll_frame.update_idletasks()
        self.canvas_editor_widget.configure(scrollregion=self.canvas_editor_widget.bbox("all"))

    def _build_template_editor_card(self, parent: ttk.Frame, tmpl: dict, idx: int) -> None:
        band = tk.Frame(parent, bg=self._template_band_bg(idx))
        band.pack(fill="x", padx=2, pady=5)

        outer = ttk.LabelFrame(band, text=f"Template {tmpl['id']}")
        outer.pack(fill="x", padx=5, pady=5)

        bar = ttk.Frame(outer)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Clone", command=lambda t=tmpl: self._clone_template(t)).pack(side="right", padx=2)
        ttk.Button(bar, text="Delete", command=lambda t=tmpl: self._delete_template(t)).pack(side="right", padx=2)
        ttk.Button(bar, text="↓", width=2, command=lambda i=idx: self._move_template(i, 1)).pack(side="right")
        ttk.Button(bar, text="↑", width=2, command=lambda i=idx: self._move_template(i, -1)).pack(side="right")

        ttk.Label(outer, text="Prefix:").pack(anchor="w", padx=8)
        prefix_var = tk.StringVar(value=tmpl.get("prefix") or "")
        pe = ttk.Entry(outer, textvariable=prefix_var, width=90)
        pe.pack(fill="x", padx=8, pady=(0, 6))

        def _save_prefix(_e=None, t=tmpl, v=prefix_var):
            t["prefix"] = v.get()
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()

        pe.bind("<FocusOut>", _save_prefix)
        pe.bind("<Return>", _save_prefix)

        for di, dd in enumerate(tmpl.get("dropdowns") or []):
            self._build_dropdown_editor_block(outer, tmpl, di, dd)

        ttk.Button(
            outer, text="＋ Add dropdown to this template", command=lambda t=tmpl: self._add_dropdown(t)
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _build_dropdown_editor_block(self, parent: ttk.Frame, tmpl: dict, di: int, dd: dict) -> None:
        frame = ttk.LabelFrame(parent, text=f"Dropdown {di + 1}")
        frame.pack(fill="x", padx=8, pady=6)

        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Label:").pack(side="left")
        lbl_var = tk.StringVar(value=dd.get("label") or "")
        le = ttk.Entry(top, textvariable=lbl_var, width=40)
        le.pack(side="left", padx=6)

        def _save_lbl(_e=None, d=dd, v=lbl_var):
            d["label"] = v.get()
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()

        le.bind("<FocusOut>", _save_lbl)
        le.bind("<Return>", _save_lbl)

        is_multi = bool(dd.get("multi"))
        mode_row = ttk.Frame(frame)
        mode_row.pack(fill="x", padx=6, pady=(0, 2))
        mtxt = (
            "Selection: multiple (joined with commas and “and”)"
            if is_multi
            else "Selection: single (one choice)"
        )
        ttk.Label(mode_row, text=mtxt).pack(side="left")

        def _flip_mode(d=dd) -> None:
            d["multi"] = not bool(d.get("multi"))
            self._persist_templates()
            self._render_note_builder()
            self._render_canvas_editor()
            self._apply_builder_to_note()
            self.on_change_callback()

        ttk.Button(mode_row, text="Switch single / multiple", command=_flip_mode).pack(side="right")

        ttk.Button(
            frame, text="Remove dropdown", command=lambda t=tmpl, d=di: self._remove_dropdown(t, d)
        ).pack(anchor="e", padx=6)

        dd.setdefault("items", [])
        items = dd["items"]

        lf = ttk.Frame(frame)
        lf.pack(fill="x", padx=6, pady=4)
        lb = tk.Listbox(lf, height=min(max(len(items), 3), 10), activestyle="dotbox")
        for it in items:
            lb.insert(tk.END, it)
        lb.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")

        new_var = tk.StringVar()

        def add_item():
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items.append(txt)
            lb.insert(tk.END, txt)
            new_var.set("")
            self._save_and_reload()

        def update_item():
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items[idx] = txt
            lb.delete(idx)
            lb.insert(idx, txt)
            self._save_and_reload()

        def delete_item():
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            items.pop(idx)
            lb.delete(idx)
            self._save_and_reload()

        def on_sel(_e=None):
            sel = lb.curselection()
            if sel:
                new_var.set(items[sel[0]])

        lb.bind("<<ListboxSelect>>", on_sel)
        self._bind_listbox_mousewheel_local(lb)

        ent_row = ttk.Frame(frame)
        ent_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Entry(ent_row, textvariable=new_var).pack(side="left", fill="x", expand=True)
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Button(btn_row, text="Add item", command=add_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Update item", command=update_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Delete item", command=delete_item).pack(side="left", padx=2)

    def _add_template(self) -> None:
        mode = self._ask_dropdown_mode(
            title="New template — dropdown type",
            prompt=(
                "Should the first dropdown for this template allow only one choice (single), "
                "or several at once (multiple)?\n\n"
                "Multiple selections are combined with commas and “and” before the last item "
                "(for example: Ibuprofen, Tylenol, and Aspirin)."
            ),
        )
        if mode is None:
            return
        new_id = max((t["id"] for t in self.templates), default=0) + 1
        self.templates.append(
            {
                "id": new_id,
                "prefix": f"Template {new_id} prefix ",
                "dropdowns": [
                    {
                        "label": "Option",
                        "items": ["First phrase", "Second phrase"],
                        "multi": bool(mode),
                    }
                ],
            }
        )
        self._save_and_reload()

    def _clone_template(self, tmpl: dict) -> None:
        base = {
            "id": tmpl["id"],
            "prefix": tmpl.get("prefix") or "",
            "dropdowns": tmpl.get("dropdowns") or [],
        }
        cloned = copy.deepcopy(base)
        cloned["id"] = max((t["id"] for t in self.templates), default=0) + 1
        self.templates.append(cloned)
        self._save_and_reload()

    def _delete_template(self, tmpl: dict) -> None:
        if len(self.templates) <= 1:
            messagebox.showwarning("Cannot delete", "At least one template is required.")
            return
        if messagebox.askyesno("Delete template", f"Delete template {tmpl['id']}?"):
            self._visit_skip_by_tid.pop(int(tmpl["id"]), None)
            # Mutate list in place — self.templates aliases section["templates"]; assigning
            # a new list would break persistence (orchestrator saves section dicts).
            self.templates[:] = [t for t in self.templates if t["id"] != tmpl["id"]]
            self._save_and_reload()

    def _move_template(self, idx: int, direction: int) -> None:
        j = idx + direction
        if 0 <= j < len(self.templates):
            self.templates.insert(j, self.templates.pop(idx))
            self._save_and_reload()

    def _add_dropdown(self, tmpl: dict) -> None:
        mode = self._ask_dropdown_mode(
            title="New dropdown — selection type",
            prompt=(
                "Should this new dropdown allow only one choice (single), "
                "or several at once (multiple)?\n\n"
                "Multiple selections are combined with commas and “and” before the last item."
            ),
        )
        if mode is None:
            return
        tmpl.setdefault("dropdowns", []).append(
            {"label": "New dropdown", "items": ["A", "B"], "multi": bool(mode)}
        )
        self._save_and_reload()

    def _remove_dropdown(self, tmpl: dict, di: int) -> None:
        dds = tmpl.get("dropdowns") or []
        if len(dds) <= 1:
            messagebox.showwarning("Cannot remove", "Each template needs at least one dropdown.")
            return
        if messagebox.askyesno("Remove dropdown", "Remove this dropdown?"):
            dds.pop(di)
            self._save_and_reload()

    def _save_and_reload(self) -> None:
        self._persist_templates()
        self._render_note_builder()
        self._render_canvas_editor()
        self._apply_builder_to_note()
        self.on_change_callback()

    # --- TextPage-compatible API ---
    def get_value(self) -> str:
        return self.text.get("1.0", tk.END).strip()

    def set_value(self, value: str, *, builder_state: dict | None = None) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value or "")
        if self.note_combo_vars and self._note_builder_meta:
            self._apply_builder_state(builder_state if isinstance(builder_state, dict) else None)

    def has_content(self) -> bool:
        return bool(self.get_value().strip())

    def reset(self) -> None:
        self._visit_skip_by_tid.clear()
        self.note_combo_vars = []
        self._note_builder_meta = []
        self.text.delete("1.0", tk.END)
        self._render_note_builder()

    def tkraise(self, *args, **kwargs):
        super().tkraise(*args, **kwargs)
        self._wire_mousewheel()
