# family_social_history_page.py — Family/Social narrative builder + Canvas template editor.
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

# Prepended to each builder dropdown (not stored in JSON). Selecting it drops that clause from output.
OPTION_OMIT = "(Omit — exclude from sentence)"
TEMPLATE_BAND_COLORS = ("#9D9D9D", "#C5C5C5")


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


class FamilySocialHistoryPage(ttk.Frame):
    """
    Same persistence contract as TextPage: get_value / set_value / has_content / reset.
    Adds sentence-builder dropdowns and a Canvas tab to edit templates (JSON in data dir).
    """

    def __init__(self, parent, title: str, on_change_callback, app: tk.Misc | None = None):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self._app = app
        self.templates = self._load_templates()
        self.note_combo_vars: list[list[tk.StringVar]] = []
        # Per-template "skip for this visit" (by template id); survives Canvas re-save re-renders.
        self._visit_skip_by_tid: dict[int, bool] = {}

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=title).pack(anchor="w", padx=10, pady=(8, 4))

        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        self.tab_note = ttk.Frame(self.nb)
        self.tab_canvas = ttk.Frame(self.nb)
        self.nb.add(self.tab_note, text="Note & builder")
        self.nb.add(self.tab_canvas, text="Template editor (Canvas)")

        self._build_note_tab(self.tab_note)
        self._build_canvas_tab(self.tab_canvas)
        self._mw_bound = False

        if self._app is not None:
            try:
                self._app.dob_var.trace_add("write", lambda *_: self._on_demographics_changed())
                self._app.exam_date_var.trace_add("write", lambda *_: self._on_demographics_changed())
                hp = getattr(self._app, "hoi_page", None)
                if hp is not None and hasattr(hp, "sex_var"):
                    hp.sex_var.trace_add("write", lambda *_: self._on_demographics_changed())
            except Exception:
                pass

        self._render_note_builder()
        self._render_canvas_editor()
        self._wire_mousewheel()

    # --- persistence ---
    def _templates_path(self) -> str:
        return str(get_data_dir() / TEMPLATES_FILENAME)

    def _load_templates(self) -> list[dict]:
        path = self._templates_path()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                pass
        return copy.deepcopy(DEFAULT_TEMPLATES)

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

    def _save_templates_file(self) -> None:
        path = self._templates_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._sanitize_templates_for_save(), f, indent=2)

    def _persist_templates(self) -> None:
        for t in self.templates:
            t.pop("_ghost_lbl", None)
        self._save_templates_file()

    # --- demographics & HOI sex (Type of Injury / MOI) ---
    def _sex_token_for_sentence(self) -> str:
        """
        Word inserted for {sex} in prefix templates.
        Uses HOI → Type of Injury (or MOI block) sex/pronouns: Male / Female / Unknown.
        """
        raw = ""
        if self._app is not None:
            try:
                hp = getattr(self._app, "hoi_page", None)
                if hp is not None and hasattr(hp, "sex_var"):
                    raw = (hp.sex_var.get() or "").strip()
            except Exception:
                pass
        if raw in ("", "(unknown)"):
            return "patient"
        return raw.lower()

    def _format_context(self) -> dict[str, str]:
        age = ""
        ref = today_mmddyyyy()
        if self._app is not None:
            try:
                ref = (self._app.exam_date_var.get() or "").strip() or ref
                age = _age_from_dob(self._app.dob_var.get(), ref)
            except Exception:
                age = ""
        if not age:
            age = "____"
        sex = self._sex_token_for_sentence()
        return {
            "age": age,
            "sex": sex,
            "pod": "0",
            "stage": "___",
            "comorbidities": "multiple conditions",
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
        self._refresh_ghost_labels_only()
        if self.auto_apply_builder.get():
            self._apply_builder_to_note()

    def _update_age_hint(self) -> None:
        if not hasattr(self, "age_hint_var"):
            return
        ctx = self._format_context()
        self.age_hint_var.set(f"Tokens: age={ctx['age']}, sex token={ctx['sex']}")

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
            text='{sex} from HOI Type of Injury. Dropdown/Omit/Skip always refresh the note below. "(Omit...)" removes that clause.',
            foreground="gray",
        ).pack(side="left")

        self.age_hint_var = tk.StringVar(value="")
        ttk.Label(demo_row, textvariable=self.age_hint_var, foreground="gray").pack(side="left", padx=(12, 0))

        ctl = ttk.Frame(note_inner)
        ctl.pack(fill="x", padx=10, pady=(0, 4))
        self.auto_apply_builder = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctl,
            text="Also refresh note when DOB or visit date changes (token {age})",
            variable=self.auto_apply_builder,
            command=lambda: self._on_auto_toggle(),
        ).pack(side="left")
        ttk.Button(ctl, text="Apply builder → note now", command=self._apply_builder_to_note).pack(
            side="left", padx=(12, 0)
        )

        builder_outer = ttk.LabelFrame(note_inner, text="Sentence builder")
        builder_outer.pack(fill="x", expand=False, padx=10, pady=(0, 6))
        self._note_builder_outer = builder_outer

        canvas = tk.Canvas(builder_outer, highlightthickness=0, height=220)
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

    def _on_auto_toggle(self) -> None:
        if self.auto_apply_builder.get():
            self._apply_builder_to_note()

    def _on_note_text_changed(self) -> None:
        self.on_change_callback()

    def _on_builder_selection_changed(self) -> None:
        self._refresh_ghost_labels_only()
        # Always push builder output to the note so Omit / dropdown changes reach Live Preview & PDF.
        self._apply_builder_to_note()

    def _visit_skip_toggled(self, tid: int, var: tk.BooleanVar) -> None:
        """Sync skip flag after Tk commits the checkbutton value, then refresh the note."""

        def _sync() -> None:
            self._visit_skip_by_tid[tid] = var.get()
            self._refresh_ghost_labels_only()
            self._apply_builder_to_note()
            self.on_change_callback()

        # after_idle: on some platforms the bound BooleanVar is not updated before command runs.
        self.after_idle(_sync)

    def _compose_parts_for_template(self, i: int, tmpl: dict) -> list[str]:
        """
        Build prefix + non-Omit dropdown fragments. If this template has at least one
        dropdown and every dropdown is Omit/empty, return [] so the prefix is not left
        orphaned (e.g. no bare "Family history is." or "hello.").
        """
        rp = (self._resolve_vars(tmpl.get("prefix") or "") or "").strip()
        dropdown_parts: list[str] = []
        if i < len(self.note_combo_vars):
            for var in self.note_combo_vars[i]:
                val = (var.get() or "").strip()
                if not val or _is_omit_phrase(val):
                    continue
                dropdown_parts.append(val)

        if i < len(self.note_combo_vars) and len(self.note_combo_vars[i]) > 0 and not dropdown_parts:
            return []

        parts: list[str] = []
        if rp:
            parts.append(rp)
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
            sent = _finalize_sentence(parts)
            if sent:
                blocks.append(sent)
        return "\n\n".join(blocks).strip()

    def _apply_builder_to_note(self) -> None:
        body = self._compose_builder_text()
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", body)
        self._update_age_hint()
        self.on_change_callback()

    def _refresh_ghost_labels_only(self) -> None:
        for i, tmpl in enumerate(self.templates):
            if i >= len(self.note_combo_vars):
                continue
            ghost = getattr(tmpl, "_ghost_lbl", None)
            if ghost is None or not isinstance(ghost, tk.Widget):
                continue
            try:
                if not ghost.winfo_exists():
                    continue
            except Exception:
                continue
            tid = int(tmpl["id"])
            if self._visit_skip_by_tid.get(tid, False):
                ghost.configure(text="▸ (Skipped for this visit — not included in note text from builder)")
                continue
            parts = self._compose_parts_for_template(i, tmpl)
            if not parts:
                ghost.configure(
                    text="▸ (Omit on all options — prefix and options excluded from note)"
                )
                continue
            ghost.configure(text="▸ " + _finalize_sentence(parts))

    # --- builder render ---
    def _render_note_builder(self) -> None:
        for w in self.note_scroll_frame.winfo_children():
            w.destroy()
        self.note_combo_vars = []

        self._prefix_resolved_labels: list[ttk.Label] = []

        for idx, tmpl in enumerate(self.templates):
            band = tk.Frame(self.note_scroll_frame, bg=self._template_band_bg(idx))
            band.pack(fill="x", padx=4, pady=4)

            card = ttk.LabelFrame(band, text=f"Template {tmpl['id']}")
            card.pack(fill="x", padx=5, pady=5)

            tid = int(tmpl["id"])
            skip_v = tk.BooleanVar(value=self._visit_skip_by_tid.get(tid, False))

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
            for dd in tmpl.get("dropdowns") or []:
                items = list(dd.get("items") or [])
                display_items = [OPTION_OMIT] + items
                fr = ttk.Frame(card)
                fr.pack(fill="x", padx=8, pady=3)
                ttk.Label(fr, text=(dd.get("label") or "Option") + ":").pack(anchor="w")
                initial = items[0] if items else OPTION_OMIT
                var = tk.StringVar(value=initial)
                cb = ttk.Combobox(fr, textvariable=var, values=display_items, state="readonly", width=80)
                cb.pack(fill="x")
                cb.bind("<<ComboboxSelected>>", lambda e: self._on_builder_selection_changed())
                row_vars.append(var)

            self.note_combo_vars.append(row_vars)

            ghost = ttk.Label(card, text="", wraplength=560, foreground="#0B6E4F")
            ghost.pack(anchor="w", padx=8, pady=(2, 8))
            tmpl["_ghost_lbl"] = ghost  # not serialized

        self.note_scroll_frame.update_idletasks()
        self.note_builder_canvas.configure(scrollregion=self.note_builder_canvas.bbox("all"))
        self._update_age_hint()
        self._refresh_ghost_labels_only()

    @staticmethod
    def _template_band_bg(idx: int) -> str:
        return TEMPLATE_BAND_COLORS[idx % len(TEMPLATE_BAND_COLORS)]

    # --- canvas tab ---
    def _build_canvas_tab(self, parent: ttk.Frame) -> None:
        hdr = ttk.Frame(parent)
        hdr.pack(fill="x", padx=8, pady=6)
        ttk.Button(hdr, text="Save templates", command=self._save_and_reload).pack(side="right")
        ttk.Button(hdr, text="＋ Add template", command=self._add_template).pack(side="right", padx=(0, 8))
        ttk.Label(
            hdr,
            text="Edit prefixes and dropdown items. Prefix placeholders: {age} (DOB vs visit date), {sex} (HOI Type of Injury pronouns), {pod}, {stage}, {comorbidities}.",
        ).pack(side="left")

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
            if self.auto_apply_builder.get():
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
            self.on_change_callback()

        le.bind("<FocusOut>", _save_lbl)
        le.bind("<Return>", _save_lbl)

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
        new_id = max((t["id"] for t in self.templates), default=0) + 1
        self.templates.append(
            {
                "id": new_id,
                "prefix": f"Template {new_id} prefix ",
                "dropdowns": [{"label": "Option", "items": ["First phrase", "Second phrase"]}],
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
        cloned["prefix"] = "(Copy) " + str(cloned.get("prefix") or "")
        self.templates.append(cloned)
        self._save_and_reload()

    def _delete_template(self, tmpl: dict) -> None:
        if len(self.templates) <= 1:
            messagebox.showwarning("Cannot delete", "At least one template is required.")
            return
        if messagebox.askyesno("Delete template", f"Delete template {tmpl['id']}?"):
            self._visit_skip_by_tid.pop(int(tmpl["id"]), None)
            self.templates = [t for t in self.templates if t["id"] != tmpl["id"]]
            self._save_and_reload()

    def _move_template(self, idx: int, direction: int) -> None:
        j = idx + direction
        if 0 <= j < len(self.templates):
            self.templates.insert(j, self.templates.pop(idx))
            self._save_and_reload()

    def _add_dropdown(self, tmpl: dict) -> None:
        tmpl.setdefault("dropdowns", []).append({"label": "New dropdown", "items": ["A", "B"]})
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

    def set_value(self, value: str) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value or "")

    def has_content(self) -> bool:
        return bool(self.get_value().strip())

    def reset(self) -> None:
        self._visit_skip_by_tid.clear()
        self.set_value("")
        self._render_note_builder()

    def tkraise(self, *args, **kwargs):
        super().tkraise(*args, **kwargs)
        self._wire_mousewheel()
