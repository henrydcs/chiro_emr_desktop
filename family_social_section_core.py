# family_social_section_core.py — One Family/Social sub-section (Note builder + template Canvas).
from __future__ import annotations

import base64
import copy
import json
import os
import re
from datetime import datetime
from tkinter import ttk, messagebox, colorchooser

import tkinter as tk
import tkinter.font as tkfont

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

# Embedded in saved rich_text only — stripped before Tk formatting restore / Live Preview XML parse.
_PDF_FS_GRID_COMMENT_RE = re.compile(r"<!--pdf_fs_grid:(.*?)-->", re.DOTALL)

# wrap_px encodings for assoc per-primary plain aligned-column rows (edit box + live preview).
_PLAIN_COL_VALUE_WRAP_FLAG = 50_000_000


def _strip_pdf_fs_grid_comments(s: str | None) -> str:
    if not s:
        return ""
    return _PDF_FS_GRID_COMMENT_RE.sub("", str(s))

# Associated-dropdown slot colors (DD1, DD2, DD3, ...). DD1 starts orange by request.
ASSOC_SLOT_DEFAULT_COLORS: tuple[tuple[str, str], ...] = (
    ("Orange", "#f39c12"),  # DD1
    ("Green", "#2e7d32"),   # DD2
    ("Blue", "#1e88e5"),    # DD3
    ("Purple", "#8e24aa"),
    ("Teal", "#00897b"),
    ("Brown", "#6d4c41"),
    ("Red", "#c62828"),
    ("Pink", "#d81b60"),
    ("Indigo", "#3949ab"),
    ("Gray", "#616161"),
)

# Parts prefixed with this character attach to the previous run with no intervening space
# (used for intra-line header / detail segments in Associated Multiple bullet lines).
_ATTACH = "\x02"

# Per-dropdown bullet icon (Template editor). Used after tab for bullet lines / associated-multi rows.
# Keys are stored in each dropdown dict as `bullet_style`.
_BULLET_STYLE_TAB_SUFFIX: dict[str, str] = {
    # “none”: same tabbed line breaks as bulleted lines, with a space after the tab (no icon).
    "none": " ",
    "round_circle": "○ ",
    "filled_circle": "● ",
    "square": "□ ",
    "filled_square": "■ ",
    "dash_line": "– ",  # en dash
    "hyphen": "- ",
    "bullet": "• ",
}

VALID_DROPDOWN_BULLET_STYLES: frozenset[str] = frozenset(_BULLET_STYLE_TAB_SUFFIX.keys())

_BULLET_STYLE_CHOICES: tuple[tuple[str, str], ...] = (
    ("none", "None (no icon, indented lines)"),
    ("round_circle", "Round circle ○"),
    ("filled_circle", "Filled circle ●"),
    ("square", "Square □"),
    ("filled_square", "Filled square ■"),
    ("dash_line", "Dash line –"),
    ("hyphen", "Hyphen -"),
    ("bullet", "Classic bullet •"),
)


def _effective_bullet_style_key(dd: dict) -> str:
    st = dd.get("bullet_style")
    if isinstance(st, str) and st in _BULLET_STYLE_TAB_SUFFIX:
        return st
    if dd.get("associated_multi"):
        return "hyphen"
    if dd.get("associated_per_primary") and bool(dd.get("assoc_primary_use_bullets", True)):
        return "hyphen"
    return "bullet"


def _bullet_tab_suffix(dd: dict) -> str:
    return _BULLET_STYLE_TAB_SUFFIX[_effective_bullet_style_key(dd)]


def _bullet_line_prefix(dd: dict, first_line: bool) -> str:
    suf = _bullet_tab_suffix(dd)
    if first_line:
        return "\n\n\t" + suf
    return "\n\t" + suf


def _associated_detail_row_prefix(dd: dict, first_line: bool, *, use_tab_bullets: bool) -> str:
    """Associated dropdown rows: tab+bullet glyphs, or plain newlines only (Plan-of-care style)."""
    if use_tab_bullets:
        return _bullet_line_prefix(dd, first_line)
    return "\n\n" if first_line else "\n"


def _wrap_long_bullet_tokens(dd: dict, text: str, *, max_token_len: int = 42) -> str:
    """
    Hard-wrap very long unbroken tokens inside bullet content.

    Tk Text with wrap="word" does not wrap a single long token; this inserts
    continuation line breaks that keep wrapped chunks aligned with the bullet text.
    """
    s = str(text or "")
    if not s:
        return s
    if max_token_len < 8:
        max_token_len = 8
    cont = "\n\t" + (" " * len(_bullet_tab_suffix(dd)))
    token_re = re.compile(r"\S+")

    def _split_token(tok: str) -> str:
        if len(tok) <= max_token_len:
            return tok
        parts = [tok[i:i + max_token_len] for i in range(0, len(tok), max_token_len)]
        return parts[0] + "".join(cont + p for p in parts[1:])

    return token_re.sub(lambda m: _split_token(m.group(0)), s)

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


def _rstrip_trailing_newlines_only(s: str) -> str:
    """Trim only \\r/\\n at end so spaces after tab (bullet icon gap) stay on the line."""
    return str(s).rstrip("\r\n")


def _finalize_newline_gap_fragment(s: str) -> str:
    """Normalize \\n-leading fragments for finalize joins.

    `_rstrip_trailing_newlines_only` would erase fragments that are only newlines;
    those carry intentional paragraph gaps and must survive into runs/output.
    """
    body = str(s)
    if body.startswith("\n") and not body.strip("\r\n"):
        # Preserve blank-line gaps: "\\n" vs "\\n\\n" etc.
        return body.replace("\r\n", "\n").replace("\r", "\n")
    return _rstrip_trailing_newlines_only(body)


def _finalize_family_social_block(parts: list[str] | None) -> str:
    """Join prefix + dropdown fragments in a single pass.

    Joining rules per part (after filtering None / whitespace-only):
    • starts with "\\n"   → attach directly, rstrip trailing newlines only (keeps space after icon/tab)
    • starts with _ATTACH → strip the marker and attach directly (intra-line join)
    • otherwise           → strip and prepend a single space (except for the first part)

    No sentence-final period is added when the block contains any bullet ("\\n") part.
    """
    pl = list(parts or [])
    has_bullet = any(
        p is not None and str(p).startswith("\n") for p in pl
    )
    out = ""
    first = True
    for p in pl:
        if p is None:
            continue
        s = str(p)
        if not s.strip() and not s.startswith("\n"):
            continue
        if s.startswith("\n"):
            cleaned = _finalize_newline_gap_fragment(s)
            out = cleaned if first else (out + cleaned)
        elif s.startswith(_ATTACH):
            cleaned = s[len(_ATTACH):]
            out = cleaned if first else (out + cleaned)
        else:
            cleaned = s.strip()
            out = cleaned if first else (out + " " + cleaned)
        first = False
    out = out.strip()
    if not out:
        return ""
    if has_bullet:
        return out
    if out[-1] not in ".!?" and out[-1] != ",":
        out += "."
    return out


def _prefix_before_bullet_list(rp: str) -> str:
    """Trim trailing whitespace from prefix text; punctuation is left to the template author."""
    return (rp or "").rstrip()


def _fmt_tag_name(bold: bool, italic: bool, underline: bool) -> str | None:
    """Return a canonical tk.Text tag name for the given combination, or None if all off."""
    if not bold and not italic and not underline:
        return None
    return "_FMT_" + ("B" if bold else "") + ("I" if italic else "") + ("U" if underline else "")


def _dd_fmt_tag(dd: dict | None) -> str | None:
    """Derive the formatting tag name for a dropdown dict (or None = no formatting)."""
    if not dd:
        return None
    fmt = dd.get("text_format") or {}
    return _fmt_tag_name(bool(fmt.get("bold")), bool(fmt.get("italic")), bool(fmt.get("underline")))


def _finalize_family_social_block_annotated(
    parts: list[str] | None,
    dds: list["dict | None"],
    *,
    bullet_wrap_by_part_idx: dict[int, int] | None = None,
) -> list[tuple[str, "str | None", "int | None"]]:
    """
    Mirror of _finalize_family_social_block but return (text_chunk, tag, bullet_wrap_px).
    bullet_wrap_px (when set) requests Tk hanging continuation indent for wrapped lines.

    dds[i] is the dropdown dict for parts[i], or None for the prefix.
    Joining rules match _finalize_family_social_block exactly.
    """
    pl = list(parts or [])
    dl = list(dds or [])
    has_bullet = any(
        p is not None and str(p).startswith("\n") for p in pl
    )
    runs: list[tuple[str, "str | None", "int | None"]] = []
    first = True
    bullet_flow_px: int | None = None
    for pi, (p, d) in enumerate(zip(pl, dl)):
        if bullet_wrap_by_part_idx is not None and pi in bullet_wrap_by_part_idx:
            bullet_flow_px = int(bullet_wrap_by_part_idx[pi])
        else:
            bullet_flow_px = None
        if p is None:
            continue
        s = str(p)
        if not s.strip() and not s.startswith("\n"):
            continue
        tag = _dd_fmt_tag(d)
        wrap_px = bullet_flow_px
        if s.startswith("\n"):
            cleaned = _finalize_newline_gap_fragment(s)
            runs.append((cleaned if first else cleaned, tag, wrap_px))
        elif s.startswith(_ATTACH):
            cleaned = s[len(_ATTACH):]
            runs.append((cleaned, tag, wrap_px))
        else:
            cleaned = s.strip()
            if first:
                runs.append((cleaned, tag, wrap_px))
            else:
                runs.append((" " + cleaned, tag, wrap_px))
        first = False

    if not runs:
        return []

    # Strip any accidental leading space from the very first run.
    if runs[0][0].startswith(" "):
        runs[0] = (runs[0][0].lstrip(), runs[0][1], runs[0][2])

    if not has_bullet:
        full = "".join(r[0] for r in runs).strip()
        if full and full[-1] not in ".!?" and full[-1] != ",":
            last_t, last_tag, last_px = runs[-1]
            runs[-1] = (last_t + ".", last_tag, last_px)

    return [(t, tag, px) for t, tag, px in runs if t]


def _plain_grid_run_matches_export_row(
    run_a: tuple[str, str | None, int | None],
    run_b: tuple[str, str | None, int | None],
    er: dict,
) -> bool:
    ch, _, _ = run_a
    ch2, _, _ = run_b
    return (
        bool(er)
        and ch.rstrip() == str(er.get("h") or "").rstrip()
        and ch2.strip() == str(er.get("v") or "").strip()
    )


def _plain_grid_runs_match_export_row(
    runs_src: list[tuple[str, str | None, int | None]], i: int, er: dict
) -> tuple[bool, int]:
    """Match label + optional space-pad + value runs to one export row; return next index."""
    if i >= len(runs_src) or not er:
        return False, i
    if runs_src[i][0].rstrip() != str(er.get("h") or "").rstrip():
        return False, i
    j = i + 1
    while j < len(runs_src):
        mid = runs_src[j][0]
        if mid and not mid.strip():
            j += 1
            continue
        if mid and all(c == " " for c in mid):
            j += 1
            continue
        break
    if j >= len(runs_src):
        return False, i
    if runs_src[j][0].strip() != str(er.get("v") or "").strip():
        return False, i
    return True, j + 1


def _fmt_flags_dict(dd: dict, *, assoc: bool = False) -> dict[str, bool]:
    key = "assoc_text_format" if assoc else "text_format"
    fmt = dd.get(key) or {}
    return {
        "b": bool(fmt.get("bold")),
        "i": bool(fmt.get("italic")),
        "u": bool(fmt.get("underline")),
    }


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


def _format_output_radio_value(dd: dict) -> str:
    """Radiobutton group value for Narrative / Bullet lines / Comma / Period."""
    if bool(dd.get("multi_bullets")):
        return "bullets"
    t = dd.get("narrative_tail")
    if t == ",":
        return "comma"
    if t == ".":
        return "period"
    return "narrative"


def _apply_output_format_radio(dd: dict, value: str) -> None:
    if value == "bullets":
        dd["multi_bullets"] = True
        dd.pop("narrative_tail", None)
    else:
        dd["multi_bullets"] = False
        if value == "comma":
            dd["narrative_tail"] = ","
        elif value == "period":
            dd["narrative_tail"] = "."
        else:
            dd.pop("narrative_tail", None)


def _apply_narrative_tail_to_fragment(text: str, dd: dict) -> str:
    """For narrative-style output, optionally end with comma or period on the last phrase."""
    if bool(dd.get("multi_bullets")):
        return text
    t = dd.get("narrative_tail")
    if t not in (",", "."):
        return text
    s = (text or "").rstrip()
    if not s:
        return text
    if t == ",":
        return s.rstrip(",.") + ","
    return s.rstrip(".") + "."


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
        clear_assoc_on_primary_clear: bool = False,
    ):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self._app = app
        self.section = section
        self.templates = section.setdefault("templates", [])
        # Global color map for DD slot borders (DD1/DD2/...) across this whole section.
        self._assoc_slot_colors = section.setdefault("assoc_slot_colors", [])
        self._persist_all = persist_all_callback
        self.note_combo_vars: list[list[tk.StringVar]] = []
        self._note_builder_meta: list[list[dict]] = []
        self._visit_skip_by_tid: dict[int, bool] = {}
        # Note/Builder-only visual promotion target per template (does not affect print order).
        self._builder_dd_top_by_tid: dict[int, int] = {}
        self._builder_dd_repack_by_tid: dict[int, object] = {}
        self._skip_checkbox_vars: dict[int, tk.BooleanVar] = {}
        self._clear_assoc_on_primary_clear = bool(clear_assoc_on_primary_clear)
        if token_feedback_var is not None:
            self._token_copy_feedback_var = token_feedback_var
        else:
            self._token_copy_feedback_var = tk.StringVar(value="")
        self._clear_token_copy_msg_after_id = None
        # Tk Text tag cache: indent px → tag name for wrapped bullet continuation (lmargin2).
        self._bullet_wrap_tag_by_px: dict[int, str] = {}
        self._column_tab_tag_by_px: dict[int, str] = {}
        self._column_val_wrap_tag_by_px: dict[int, str] = {}

        self._build_note_tab(self)
        self._mw_bound = False

        # Demographic-var traces (DOB, exam date, names, sex) are owned by
        # `FamilySocialHistoryPage` instead of here.  See `tk_lifecycle.py`
        # and `FamilySocialHistoryPage._register_demographic_traces` for why:
        # the page outlives every section, so binding traces there makes the
        # subscription lifetime match the listener lifetime and prevents
        # stale callbacks firing on destroyed section text widgets after the
        # user deletes / renames / re-loads a sub-heading.

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
    def _ask_dropdown_creation_mode(
        self,
        *,
        title: str,
        prompt: str,
    ) -> str | None:
        """
        Prompt for a new template/dropdown selection mode.
        Returns "single", "single_full_prefix", "multiple", "multiple_full_prefix",
        "associated_multiple", "associated_per_primary", or None if cancelled.
        """
        result: list[str | None] = [None]
        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title(title)
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        dlg.grab_set()
        ttk.Label(dlg, text=prompt, wraplength=460).pack(padx=18, pady=(14, 10))

        def _pick(mode: str) -> None:
            result[0] = mode
            dlg.destroy()

        def _cancel() -> None:
            result[0] = None
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(pady=(0, 14))
        ttk.Button(bf, text="Single choice", width=22, command=lambda: _pick("single")).pack(
            side="top", pady=3
        )
        ttk.Button(
            bf,
            text="Single choice Full/Full",
            width=22,
            command=lambda: _pick("single_full_prefix"),
        ).pack(side="top", pady=3)
        ttk.Button(bf, text="Multiple choice", width=22, command=lambda: _pick("multiple")).pack(
            side="top", pady=3
        )
        ttk.Button(
            bf,
            text="Multiple choice Full/Full",
            width=22,
            command=lambda: _pick("multiple_full_prefix"),
        ).pack(side="top", pady=3)
        ttk.Button(
            bf,
            text="Associated Multiple",
            width=22,
            command=lambda: _pick("associated_multiple"),
        ).pack(side="top", pady=3)
        ttk.Button(
            bf,
            text="Associated per primary",
            width=22,
            command=lambda: _pick("associated_per_primary"),
        ).pack(side="top", pady=3)
        ttk.Button(bf, text="Cancel", width=14, command=_cancel).pack(side="top", pady=(8, 0))
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

    def _align_per_primary_associates(self, dd: dict) -> None:
        """Ensure per_primary_associates length matches primary items (template edits)."""
        if not dd.get("associated_per_primary"):
            return
        items = dd.get("items") or []
        if not isinstance(items, list):
            return
        ppa = dd.setdefault("per_primary_associates", [])
        while len(ppa) < len(items):
            ppa.append([])
        del ppa[len(items):]

    def _persist_templates(self) -> None:
        for t in self.templates:
            t.pop("_ghost_lbl", None)
            for dd in t.get("dropdowns") or []:
                if isinstance(dd, dict):
                    self._align_per_primary_associates(dd)
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
        note_inner = ttk.Frame(parent)
        note_inner.pack(fill="both", expand=True)

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
        ttk.Button(
            ctl,
            text="Textbox Edit Area",
            command=lambda: self._note_editor_text_layer.tkraise(),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            ctl,
            text="Sentence builder",
            command=lambda: self._note_editor_builder_layer.tkraise(),
        ).pack(side="left", padx=(8, 0))

        self._note_editor_stack = ttk.Frame(note_inner)
        self._note_editor_stack.pack(fill="x", expand=False, padx=10, pady=(0, 6))
        self._note_editor_builder_layer = ttk.Frame(self._note_editor_stack)
        self._note_editor_text_layer = ttk.Frame(self._note_editor_stack)
        self._note_editor_builder_layer.grid(row=0, column=0, sticky="nsew")
        self._note_editor_text_layer.grid(row=0, column=0, sticky="nsew")
        self._note_editor_stack.grid_columnconfigure(0, weight=1)

        builder_outer = ttk.LabelFrame(self._note_editor_builder_layer, text="Sentence builder")
        builder_outer.pack(fill="x", expand=False, pady=(0, 0))
        self._note_builder_outer = builder_outer

        canvas = tk.Canvas(builder_outer, highlightthickness=0, height=440)
        sb = ttk.Scrollbar(builder_outer, orient="vertical", command=canvas.yview)
        self.note_scroll_frame = ttk.Frame(canvas)
        self.note_scroll_frame.bind("<Configure>", lambda _e: self._sync_note_builder_scrollregion())
        self._note_builder_canvas_window_id = canvas.create_window(
            (0, 0), window=self.note_scroll_frame, anchor="nw"
        )
        canvas.bind("<Configure>", self._on_note_builder_canvas_configure)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.note_builder_canvas = canvas

        ttk.Label(
            self._note_editor_text_layer,
            text="Note text (editable — saved to chart, Live Preview, and PDF):",
        ).pack(anchor="w", padx=0, pady=(4, 2))

        # --- Formatting toolbar (Bold / Italic / Underline) ---
        fmt_bar = tk.Frame(self._note_editor_text_layer, bd=0)
        fmt_bar.pack(anchor="w", padx=0, pady=(0, 2))
        _tf_btn = ("Segoe UI", 9)
        tk.Label(fmt_bar, text="Format selection:", font=_tf_btn).pack(side="left", padx=(0, 6))
        self._fmt_bold_btn = tk.Button(
            fmt_bar, text="B", font=("Segoe UI", 9, "bold"),
            width=2, padx=3, pady=1, relief="raised", cursor="hand2",
            command=lambda: self._toggle_format("B"),
        )
        self._fmt_bold_btn.pack(side="left", padx=(0, 2))
        self._fmt_italic_btn = tk.Button(
            fmt_bar, text="I", font=("Segoe UI", 9, "italic"),
            width=2, padx=3, pady=1, relief="raised", cursor="hand2",
            command=lambda: self._toggle_format("I"),
        )
        self._fmt_italic_btn.pack(side="left", padx=(0, 2))
        self._fmt_underline_btn = tk.Button(
            fmt_bar, text="U", font=("Segoe UI", 9, "underline"),
            width=2, padx=3, pady=1, relief="raised", cursor="hand2",
            command=lambda: self._toggle_format("U"),
        )
        self._fmt_underline_btn.pack(side="left", padx=(0, 6))
        tk.Label(
            fmt_bar,
            text="(select text first, then click B / I / U to toggle formatting)",
            font=("Segoe UI", 8), foreground="#666666",
        ).pack(side="left")

        self.text = tk.Text(self._note_editor_text_layer, width=110, height=12, wrap="word")
        self.text.pack(fill="x", expand=False, padx=0, pady=(0, 8))
        self.text.bind("<KeyRelease>", lambda e: self._on_note_text_changed())
        # Save selection when focus leaves the text widget so the format buttons
        # can still access it (clicking a button shifts focus away from the widget).
        self.text.bind("<FocusOut>", self._on_text_focus_out)
        self._fmt_saved_sel: tuple[str | None, str | None] = (None, None)
        self._user_has_formatted: bool = False   # True when B/I/U applied without text edit
        # Formatting tags used by _apply_builder_to_note when dropdowns have text_format flags.
        _tf = ("Segoe UI", 10)
        self.text.tag_configure("_FMT_B",   font=(*_tf, "bold"))
        self.text.tag_configure("_FMT_I",   font=(*_tf, "italic"))
        self.text.tag_configure("_FMT_BI",  font=(*_tf, "bold italic"))
        self.text.tag_configure("_FMT_U",   underline=True)
        self.text.tag_configure("_FMT_BU",  font=(*_tf, "bold"),        underline=True)
        self.text.tag_configure("_FMT_IU",  font=(*_tf, "italic"),      underline=True)
        self.text.tag_configure("_FMT_BIU", font=(*_tf, "bold italic"), underline=True)

        self._note_editor_builder_layer.tkraise()

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

    def _bind_sentence_builder_readonly_combobox_wheel(self, cb: ttk.Combobox) -> None:
        """Wheel over sentence-builder single-choice combobox scrolls the builder canvas only.

        Tk applies `TCombobox` class bindings before the toplevel routed handler, so the
        value can change under the pointer unless we bind on the widget first and break.
        """
        nb = getattr(self, "note_builder_canvas", None)
        if nb is None:
            return

        def _wheel(_e: tk.Event, canvas=nb) -> str:
            try:
                if canvas.winfo_exists():
                    self._scroll_canvas_y(canvas, _e)
            except Exception:
                pass
            return "break"

        def _bind_on(w: tk.Misc | None, depth: int = 0) -> None:
            if w is None or depth > 6:
                return
            try:
                w.bind("<MouseWheel>", _wheel)
                w.bind("<Button-4>", _wheel)
                w.bind("<Button-5>", _wheel)
            except Exception:
                pass
            try:
                for ch in w.winfo_children():
                    _bind_on(ch, depth + 1)
            except Exception:
                pass

        _bind_on(cb)

    @staticmethod
    def _filter_items_by_prefix(items: list[str], query: str) -> list[int]:
        """Return source indexes of `items` whose text starts with `query` (case-insensitive).

        Empty / whitespace-only query returns every index (no filtering).
        """
        q = (query or "").lower().lstrip()
        if not q:
            return list(range(len(items)))
        return [i for i, it in enumerate(items) if str(it).lower().startswith(q)]

    @staticmethod
    def _multi_selected_source_indexes(meta: dict) -> list[int] | None:
        """Sorted source indexes selected for a multi-select dropdown, derived from meta['selected_set'].

        Returns None when the meta predates the search/filter refactor (no `selected_set`),
        signalling callers to fall back to `lb.curselection()`.
        """
        sel = meta.get("selected_set")
        if not isinstance(sel, set):
            return None
        return sorted(int(x) for x in sel)

    # Template cards: Note builder and Template editor canvas use two columns when multiple
    # templates exist; a single template spans the full width.
    _TEMPLATE_GRID_COLUMNS = 2
    _TEMPLATE_GRID_COLUMN_GAP_PX = 2
    _TEMPLATE_GRID_ROW_GAP_PX = 2

    # Extra pixels below the last builder row so the scrollbar range fully clears
    # the last dropdown (ttk layout + canvas embedding often clips the bottom otherwise).
    _NOTE_BUILDER_BOTTOM_SPACER_PX = 28

    def _on_note_builder_canvas_configure(self, event: tk.Event) -> None:
        """Keep the embedded frame width in sync with the canvas interior width."""
        canvas = getattr(self, "note_builder_canvas", None)
        wid = getattr(self, "_note_builder_canvas_window_id", None)
        if canvas is None or wid is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return
        # Scrollbar is packed beside the canvas, not inside it — full width is correct.
        try:
            canvas.itemconfigure(wid, width=event.width)
        except Exception:
            pass

    def _on_canvas_editor_canvas_configure(self, event: tk.Event) -> None:
        """Match sentence-builder canvas: stretch embedded Template editor frame to canvas width."""
        canvas = getattr(self, "canvas_editor_widget", None)
        wid = getattr(self, "_canvas_editor_canvas_window_id", None)
        if canvas is None or wid is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return
        try:
            canvas.itemconfigure(wid, width=event.width)
        except Exception:
            pass

    def _sync_canvas_editor_embed_width(self) -> None:
        """After rebuilding cards, re-apply embed width if the canvas did not emit <Configure>."""
        canvas = getattr(self, "canvas_editor_widget", None)
        wid = getattr(self, "_canvas_editor_canvas_window_id", None)
        if canvas is None or wid is None:
            return
        try:
            if not canvas.winfo_exists():
                return
            w = int(canvas.winfo_width())
            if w > 1:
                canvas.itemconfigure(wid, width=w)
        except (tk.TclError, ValueError, TypeError):
            pass

    def _sync_note_builder_scrollregion(self, _event: tk.Event | None = None) -> None:
        canvas = getattr(self, "note_builder_canvas", None)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return
        try:
            self.note_scroll_frame.update_idletasks()
        except Exception:
            pass
        bbox = canvas.bbox("all")
        if not bbox:
            return
        try:
            canvas.configure(scrollregion=bbox)
        except Exception:
            pass

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

        return None

    @staticmethod
    def _capture_canvas_top_pixel(canvas) -> float | None:
        """Return the absolute pixel offset of the top of the canvas viewport,
        or None if the canvas is not measurable. Using absolute pixels (not the
        yview fraction) is required because rebuilding assoc columns changes
        the canvas's scrollregion height — the same fraction would land on a
        different absolute pixel after the rebuild.
        """
        if canvas is None:
            return None
        try:
            if not canvas.winfo_exists():
                return None
            bbox = canvas.bbox("all")
            if not bbox:
                return None
            # canvasy(0) is the true document-space y coordinate at the top edge
            # of the viewport. This is more stable than deriving from yview()
            # fractions when nested canvases have non-zero scrollregion origins.
            return float(canvas.canvasy(0))
        except Exception:
            return None

    @staticmethod
    def _restore_canvas_top_pixel(canvas, top_pixel: float | None) -> None:
        if canvas is None or top_pixel is None:
            return
        try:
            if not canvas.winfo_exists():
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            y0 = float(bbox[1])
            total_h = float(bbox[3] - bbox[1])
            if total_h <= 0:
                return
            # yview fractions are relative to the scrollregion origin, not
            # absolute document coordinates; account for non-zero bbox top.
            new_frac = max(0.0, min(1.0, (top_pixel - y0) / total_h))
            canvas.yview_moveto(new_frac)
        except Exception:
            pass

    def _run_with_note_builder_scroll_preserved(self, fn) -> None:
        """Run `fn` while keeping the sentence-builder canvas viewport stable in *absolute pixels*.

        Restoration is deferred via after_idle so Tk can process the <Configure>
        event that updates the scrollregion *before* yview_moveto is called.

        Why pixels and not fractions: when assoc columns are destroyed and
        recreated, the canvas bbox("all") (and therefore its scrollregion
        height) changes. yview()[0] is a fraction of that height, so restoring
        the same fraction shifts the visible content. We capture the absolute
        top-pixel of the viewport, then re-derive the new fraction against the
        new scrollregion in the after_idle callback.
        """
        nb = getattr(self, "note_builder_canvas", None)

        nb_pix = self._capture_canvas_top_pixel(nb)

        fn()

        if nb_pix is not None:
            _nb = nb
            _nb_saved = nb_pix

            def _restore() -> None:
                self._restore_canvas_top_pixel(_nb, _nb_saved)

            self.after_idle(_restore)
            self.after_idle(lambda: self.after(0, _restore))

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

    def _on_text_focus_out(self, event=None) -> None:
        """Save the current text-widget selection so the B/I/U buttons can
        still access it after they steal keyboard focus."""
        try:
            self._fmt_saved_sel = (
                self.text.index("sel.first"),
                self.text.index("sel.last"),
            )
        except tk.TclError:
            self._fmt_saved_sel = (None, None)

    def _toggle_format(self, attr: str) -> None:
        """Toggle bold ('B'), italic ('I'), or underline ('U') on the current
        text-widget selection.

        Works as a smart toggle: if every character in the selection already
        carries the attribute, it is removed; otherwise it is added.  Other
        formatting attributes on the same characters are preserved.  After
        applying, the selection is restored and the Live-Preview / PDF are
        updated via on_change_callback().
        """
        import bisect

        # ── 1. Resolve the selection ──────────────────────────────────────
        try:
            sel_first = self.text.index("sel.first")
            sel_last  = self.text.index("sel.last")
        except tk.TclError:
            # Focus shifted to button — use the indices saved on FocusOut.
            sf, sl = getattr(self, "_fmt_saved_sel", (None, None))
            if not sf:
                return
            sel_first, sel_last = sf, sl

        if self.text.compare(sel_first, ">=", sel_last):
            return

        # ── 2. Build a linear-offset helper for this widget content ───────
        full_text = self.text.get("1.0", "end-1c")
        n = len(full_text)
        lines = full_text.split("\n")
        line_starts: list[int] = [0]
        for ln in lines[:-1]:
            line_starts.append(line_starts[-1] + len(ln) + 1)

        def _to_off(idx: str) -> int:
            try:
                ln_s, col_s = idx.split(".", 1)
                ln = int(ln_s) - 1
                col = int(col_s)
                if ln < 0:
                    return 0
                if ln >= len(line_starts):
                    return n
                return min(line_starts[ln] + col, n)
            except Exception:
                return 0

        def _to_idx(off: int) -> str:
            ln = bisect.bisect_right(line_starts, off) - 1
            if ln < 0:
                ln = 0
            return f"{ln + 1}.{off - line_starts[ln]}"

        s = _to_off(sel_first)
        e = _to_off(sel_last)
        if s >= e:
            return
        sel_len = e - s

        # ── 3. Read per-character (B, I, U) state from existing tags ──────
        b_at = [False] * sel_len
        i_at = [False] * sel_len
        u_at = [False] * sel_len

        _FMT_MAP: dict[str, tuple[bool, bool, bool]] = {
            "_FMT_B":   (True,  False, False),
            "_FMT_I":   (False, True,  False),
            "_FMT_BI":  (True,  True,  False),
            "_FMT_U":   (False, False, True),
            "_FMT_BU":  (True,  False, True),
            "_FMT_IU":  (False, True,  True),
            "_FMT_BIU": (True,  True,  True),
        }
        for tag, (tb, ti, tu) in _FMT_MAP.items():
            try:
                ranges = self.text.tag_ranges(tag)
            except tk.TclError:
                continue
            for r in range(0, len(ranges), 2):
                rs = max(_to_off(str(ranges[r])), s)
                re_ = min(_to_off(str(ranges[r + 1])), e)
                for k in range(rs - s, re_ - s):
                    if 0 <= k < sel_len:
                        b_at[k] = tb
                        i_at[k] = ti
                        u_at[k] = tu

        # ── 4. Determine toggle direction (off if all have it, else on) ───
        if attr == "B":
            new_val = not all(b_at)
            b_at = [new_val] * sel_len
        elif attr == "I":
            new_val = not all(i_at)
            i_at = [new_val] * sel_len
        else:  # "U"
            new_val = not all(u_at)
            u_at = [new_val] * sel_len

        # ── 5. Remove all _FMT_* tags from the selection, then re-apply ──
        for tag in _FMT_MAP:
            self.text.tag_remove(tag, sel_first, sel_last)

        pos = 0
        while pos < sel_len:
            cb, ci, cu = b_at[pos], i_at[pos], u_at[pos]
            j = pos + 1
            while j < sel_len and b_at[j] == cb and i_at[j] == ci and u_at[j] == cu:
                j += 1
            fmt_key = ("B" if cb else "") + ("I" if ci else "") + ("U" if cu else "")
            if fmt_key:
                self.text.tag_add(f"_FMT_{fmt_key}", _to_idx(s + pos), _to_idx(s + j))
            pos = j

        # ── 6. Restore selection highlight, return focus, notify app ──────
        self.text.tag_add("sel", sel_first, sel_last)
        self.text.focus_set()
        self._user_has_formatted = True   # signal: tags changed without text edit
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

    def set_all_template_visit_skip(self, skip: bool, *, notify: bool = True) -> None:
        """Set every template's 'Skip this block for this visit' flag and refresh this block's note."""
        for tmpl in self.templates:
            try:
                tid = int(tmpl["id"])
            except (TypeError, ValueError, KeyError):
                continue
            self._visit_skip_by_tid[tid] = bool(skip)
        for _, var in (getattr(self, "_skip_checkbox_vars", None) or {}).items():
            try:
                var.set(bool(skip))
            except tk.TclError:
                pass
        self._apply_builder_to_note()
        if notify:
            self.on_change_callback()

    def _tab_width_px_approx(self) -> int:
        try:
            fn = tkfont.Font(font=self.text.cget("font"))
            sw = int(fn.measure(" "))
            tw = int(fn.measure("\t"))
            fallback = max(sw * 8, 36)
            return max(tw, fallback) if tw > 0 else fallback
        except Exception:
            return 48

    def _measure_note_font_px(self, text: str, *, bold: bool = False, italic: bool = False) -> int:
        if not text:
            return 0
        try:
            fn = tkfont.Font(font=self.text.cget("font"))
            if bold:
                try:
                    fn.configure(weight="bold")
                except tk.TclError:
                    pass
            if italic:
                try:
                    fn.configure(slant="italic")
                except tk.TclError:
                    pass
            return int(fn.measure(text))
        except Exception:
            return int(len(text) * 6)

    def _assoc_bullet_wrap_indent_px(self, dd: dict, hdr: str, has_detail: bool) -> int:
        """Pixel offset where associated detail body starts (continuation lines align here)."""
        suf = _bullet_tab_suffix(dd)
        tab = self._tab_width_px_approx()
        fmt = dd.get("text_format") or {}
        hdr_m = self._measure_note_font_px(
            hdr, bold=bool(fmt.get("bold")), italic=bool(fmt.get("italic"))
        )
        sep_m = self._measure_note_font_px(": ", bold=False, italic=False) if has_detail else 0
        suf_m = self._measure_note_font_px(suf, bold=False, italic=False)
        bold_fudge = max(14, hdr_m // 6)
        return tab + suf_m + hdr_m + sep_m + bold_fudge

    def _assoc_plain_wrap_indent_px(self, dd: dict, hdr: str, has_detail: bool) -> int:
        """Hanging indent for associated-per-primary rows without tab/bullet prefix."""
        fmt = dd.get("text_format") or {}
        hdr_m = self._measure_note_font_px(
            hdr, bold=bool(fmt.get("bold")), italic=bool(fmt.get("italic"))
        )
        sep_m = self._measure_note_font_px(": ", bold=False, italic=False) if has_detail else 0
        bold_fudge = max(14, hdr_m // 6)
        return hdr_m + sep_m + bold_fudge

    def _assoc_plain_column_label_width_px(self, dd: dict, label: str) -> int:
        """Rendered width of one primary label (with colon), in edit-box font pixels."""
        fmt = dd.get("text_format") or {}
        lbl = str(label or "").strip()
        if not lbl.endswith(":"):
            lbl = f"{lbl}:"
        return self._measure_note_font_px(
            lbl, bold=bool(fmt.get("bold")), italic=bool(fmt.get("italic"))
        )

    def _assoc_plain_column_gap_px(self, dd: dict) -> int:
        """A few spaces after the longest primary label before detail text (preview/PDF edit box)."""
        sp = self._measure_note_font_px(" ", bold=False, italic=False)
        return max(4, sp * 2)

    def _assoc_plain_column_value_px(self, dd: dict, headers: list[str]) -> int:
        """Pixel offset where every row's detail text begins (widest label + small gap)."""
        max_hdr = 0
        for raw in headers:
            w = self._assoc_plain_column_label_width_px(dd, raw)
            max_hdr = max(max_hdr, w)
        return int(max_hdr + self._assoc_plain_column_gap_px(dd))

    def _assoc_plain_column_label_pad(self, dd: dict, hlbl: str, col_px: int) -> str:
        """Regular-width spaces after bold label so the detail column starts at col_px."""
        lbl_w = self._assoc_plain_column_label_width_px(dd, hlbl)
        gap = max(0, int(col_px) - lbl_w)
        sp_w = max(1, self._measure_note_font_px(" ", bold=False, italic=False))
        return " " * max(0, (gap + sp_w - 1) // sp_w)

    def _assoc_plain_column_tab_tag(self, px: int) -> str:
        """Tab stop at px from line start so every row's detail begins in one column."""
        if px <= 0:
            return ""
        tnm = self._column_tab_tag_by_px.get(px)
        if tnm is not None:
            return tnm
        tnm = f"fs_col_tab_{len(self._column_tab_tag_by_px)}_{int(px)}"
        try:
            self.text.tag_configure(tnm, tabs=(f"{int(px)}p",))
        except tk.TclError:
            try:
                fn = tkfont.Font(font=self.text.cget("font"))
                cw = max(1, int(fn.measure("0")))
                chars = max(1, (int(px) + cw - 1) // cw)
                self.text.tag_configure(tnm, tabs=(f"{chars}c",))
            except tk.TclError:
                return ""
        self._column_tab_tag_by_px[px] = tnm
        return tnm

    def _assoc_plain_column_value_wrap_tag(self, px: int) -> str:
        """Wrapped detail lines stay in the value column."""
        if px <= 0:
            return ""
        tnm = self._column_val_wrap_tag_by_px.get(px)
        if tnm is not None:
            return tnm
        tnm = f"fs_col_val_{len(self._column_val_wrap_tag_by_px)}_{int(px)}"
        try:
            self.text.tag_configure(tnm, lmargin1=0, lmargin2=int(px))
        except tk.TclError:
            return ""
        self._column_val_wrap_tag_by_px[px] = tnm
        return tnm

    def _simple_tab_bullet_wrap_indent_px(self, dd: dict) -> int:
        """Multi / single bullet lines: align wraps under text after tab + bullet glyph."""
        suf = _bullet_tab_suffix(dd)
        suf_m = self._measure_note_font_px(suf, bold=False, italic=False)
        return self._tab_width_px_approx() + suf_m + max(10, suf_m // 4)

    def _bullet_wrap_tag_name(self, px: int) -> str:
        if px <= 0:
            return ""
        tnm = self._bullet_wrap_tag_by_px.get(px)
        if tnm is not None:
            return tnm
        tnm = f"bull_wrap_{len(self._bullet_wrap_tag_by_px)}_{px}"
        try:
            self.text.tag_configure(tnm, lmargin1=0, lmargin2=int(px))
        except tk.TclError:
            pass
        self._bullet_wrap_tag_by_px[px] = tnm
        return tnm

    def _insert_builder_runs(self, runs: list[tuple[str, str | None, int | None]]) -> None:
        for chunk, tag, wrap_px in runs:
            tnames = []
            if wrap_px is not None:
                if wrap_px < 0:
                    ttag = self._assoc_plain_column_tab_tag(-int(wrap_px))
                    if ttag:
                        tnames.append(ttag)
                elif wrap_px >= _PLAIN_COL_VALUE_WRAP_FLAG:
                    col_px = int(wrap_px) - _PLAIN_COL_VALUE_WRAP_FLAG
                    wtag = self._assoc_plain_column_value_wrap_tag(col_px)
                    if wtag:
                        tnames.append(wtag)
                elif wrap_px > 0:
                    wtag = self._bullet_wrap_tag_name(int(wrap_px))
                    if wtag:
                        tnames.append(wtag)
            if tag:
                tnames.append(tag)
            if tnames:
                self.text.insert(tk.END, chunk, tuple(tnames))
            else:
                self.text.insert(tk.END, chunk)

    def _append_multi_full_prefix_fragment(
        self,
        dd: dict,
        dropdown_parts: list[str],
        dropdown_dds: list[dict | None],
    ) -> None:
        """Emit resolved dropdown prefix before Multiple choice Full/Full output.

        With Bullet Lines, a blank paragraph may precede the prefix when continuing prior content
        (same as Associated Multiple prefix spacing). With Narrative / Comma / Period, fragments
        stay in one paragraph—finalize joins with a single space like plain dropdown sentences.
        """
        if not bool(dd.get("multi_full_prefix")) or not bool(dd.get("multi")):
            return
        dd_prefix_raw = self._resolve_vars(str(dd.get("prefix") or "")).strip()
        if not dd_prefix_raw:
            return
        dd_prefix_text = _prefix_before_bullet_list(dd_prefix_raw)
        if dropdown_parts and bool(dd.get("multi_bullets")):
            dd_prefix_text = "\n\n" + dd_prefix_text
        dropdown_parts.append(dd_prefix_text)
        dropdown_dds.append(None)

    def _append_single_full_prefix_fragment(
        self,
        dd: dict,
        dropdown_parts: list[str],
        dropdown_dds: list[dict | None],
    ) -> None:
        """Emit resolved dropdown prefix before Single choice Full/Full output.

        Finalize joins this fragment with a single space like consecutive plain dropdown sentences
        (no blank paragraph before the prefix). Bullet Lines output still follows unchanged bullet logic.
        """
        if bool(dd.get("multi")) or not bool(dd.get("single_full_prefix")):
            return
        dd_prefix_raw = self._resolve_vars(str(dd.get("prefix") or "")).strip()
        if not dd_prefix_raw:
            return
        dd_prefix_text = _prefix_before_bullet_list(dd_prefix_raw)
        dropdown_parts.append(dd_prefix_text)
        dropdown_dds.append(None)

    def _compose_parts_for_template(
        self,
        i: int,
        tmpl: dict,
        _dd_out: "list[dict | None] | None" = None,
        _bullet_px_by_part_idx: dict[int, int] | None = None,
    ) -> list[str]:
        """
        Build prefix + non-Omit dropdown fragments. If this template has at least one
        dropdown and every dropdown is Omit/empty, return [] so the prefix is not left
        orphaned (e.g. no bare "Family history is." or "hello.").
        When _dd_out is provided it receives the dd dict (or None for prefix) parallel
        to each returned part, enabling per-fragment formatting annotation.
        """
        _dropdown_dds: list[dict | None] = []
        rp = (self._resolve_vars(tmpl.get("prefix") or "") or "").strip()
        dropdown_parts: list[str] = []
        # Before merging with rp, dropdown index -> continuation-indent px for that bullet paragraph.
        bullet_px_by_dropdown_idx: dict[int, int] = {}
        dds = tmpl.get("dropdowns") or []
        meta_row = self._note_builder_meta[i] if i < len(self._note_builder_meta) else []
        if i < len(self.note_combo_vars):
            for j, var in enumerate(self.note_combo_vars[i]):
                dd = dds[j] if j < len(dds) else {}
                meta = meta_row[j] if j < len(meta_row) else {}

                if isinstance(meta, dict) and (
                    meta.get("associated_multi") or meta.get("associated_per_primary")
                ):
                    abp_raw = meta.get("assoc_by_primary") or {}
                    abp: dict[int, set[int]] = {}
                    if isinstance(abp_raw, dict):
                        for kk, vv in abp_raw.items():
                            try:
                                ik = int(kk)
                            except (TypeError, ValueError):
                                continue
                            if isinstance(vv, set):
                                abp[ik] = set(int(x) for x in vv if isinstance(x, int))
                            elif isinstance(vv, (list, tuple)):
                                abp[ik] = set(int(x) for x in vv if isinstance(x, int))
                    pitems = meta.get("primary_items") or list(dd.get("items") or [])
                    selected_primary: set[int] = set()
                    pss_raw = meta.get("primary_selected_set")
                    if isinstance(pss_raw, set):
                        selected_primary = {int(x) for x in pss_raw if isinstance(x, int)}
                    else:
                        # Back-compat fallback for older meta: infer selected primaries
                        # from display-order list if the selected-set is unavailable.
                        selected_primary = {
                            int(x)
                            for x in (meta.get("primary_order") or [])
                            if isinstance(x, int)
                        }
                    if not selected_primary:
                        continue

                    use_tab_bullets = True
                    if meta.get("associated_per_primary"):
                        use_tab_bullets = bool(dd.get("assoc_primary_use_bullets", True))

                    plain_pp_grid_dd = bool(
                        meta.get("associated_per_primary") and not use_tab_bullets
                    )
                    plain_pp_columns_dd = bool(
                        plain_pp_grid_dd and dd.get("assoc_primary_plain_columns", False)
                    )
                    plain_col_px = 0
                    if plain_pp_columns_dd:
                        col_hdrs: list[str] = []
                        for pix, ptxt in enumerate(pitems):
                            if pix not in selected_primary:
                                continue
                            hr = self._resolve_vars(str(ptxt)).strip()
                            if hr:
                                col_hdrs.append(hr)
                        plain_col_px = self._assoc_plain_column_value_px(dd, col_hdrs)

                    shared_associates = list(dd.get("associate_items") or [])
                    # Proxy dicts so _dd_fmt_tag reads the correct key for each part.
                    _pri_proxy: dict = {"text_format": dd.get("text_format") or {}}
                    _asc_proxy: dict = {"text_format": dd.get("assoc_text_format") or {}}
                    first_bullet = True
                    any_bullet = False
                    emitted_plain_pp = False
                    dd_prefix_raw = self._resolve_vars(str(dd.get("prefix") or "")).strip()
                    if dd_prefix_raw:
                        dd_prefix_text = _prefix_before_bullet_list(dd_prefix_raw)
                        if dropdown_parts:
                            # When an associated dropdown prefix follows prior content,
                            # start it as a new paragraph (blank line gap).
                            dd_prefix_text = "\n\n" + dd_prefix_text
                        elif plain_pp_grid_dd:
                            # Plain grid: keep dropdown prefix out of the template-prefix paragraph.
                            dd_prefix_text = "\n\n" + dd_prefix_text
                        dropdown_parts.append(dd_prefix_text)
                        _dropdown_dds.append(None)
                    # Output order follows the Primary options layout (source of truth),
                    # not the associated-column visual order.
                    for pix, ptxt in enumerate(pitems):
                        if pix not in selected_primary:
                            continue
                        if meta.get("associated_per_primary"):
                            ppa = dd.get("per_primary_associates") or []
                            alist = list(ppa[pix]) if 0 <= pix < len(ppa) else []
                        else:
                            alist = shared_associates
                        hdr_raw = self._resolve_vars(str(ptxt)).strip()
                        if not hdr_raw:
                            continue
                        hdr = (
                            _wrap_long_bullet_tokens(dd, hdr_raw)
                            if use_tab_bullets
                            else hdr_raw
                        )
                        chosen_assoc = sorted(abp.get(pix, set()))
                        detail_parts = []
                        for ai in chosen_assoc:
                            if 0 <= ai < len(alist):
                                frag = self._resolve_vars(str(alist[ai])).strip()
                                if frag:
                                    detail_parts.append(
                                        _wrap_long_bullet_tokens(dd, frag)
                                        if use_tab_bullets
                                        else frag
                                    )
                        detail = _join_with_oxford_and(detail_parts)
                        plain_pp_grid = plain_pp_grid_dd
                        line_pfx = _associated_detail_row_prefix(
                            dd, first_bullet, use_tab_bullets=use_tab_bullets
                        )
                        if plain_pp_grid and dd_prefix_raw and first_bullet:
                            # Prefix already begins its own block; single newline before first row.
                            line_pfx = "\n"
                        if plain_pp_grid and not detail:
                            # Match Plan-of-care PDF summary: omit rows with no value text.
                            continue
                        if _bullet_px_by_part_idx is not None:
                            bi = len(dropdown_parts)
                            if use_tab_bullets:
                                bullet_px_by_dropdown_idx[bi] = self._assoc_bullet_wrap_indent_px(
                                    dd, hdr, bool(detail)
                                )
                            elif detail and not plain_pp_grid:
                                bullet_px_by_dropdown_idx[bi] = self._assoc_plain_wrap_indent_px(
                                    dd, hdr, True
                                )
                        dropdown_parts.append(line_pfx)
                        _dropdown_dds.append(None)
                        if plain_pp_grid:
                            hlbl = hdr.strip()
                            if not hlbl.endswith(":"):
                                hlbl = f"{hlbl}:"
                            self._fs_plain_grid_pdf_export_rows.append(
                                {
                                    "h": hlbl,
                                    "v": detail.strip(),
                                    "hf": _fmt_flags_dict(dd),
                                    "vf": _fmt_flags_dict(dd, assoc=True),
                                    "align": "columns" if plain_pp_columns_dd else "inline",
                                }
                            )
                            emitted_plain_pp = True
                            dropdown_parts.append(_ATTACH + hlbl)
                            _dropdown_dds.append(_pri_proxy)
                            # Single line break between rows comes from the next row's line_pfx;
                            # omit trailing newline here so Live Preview rows aren't double-spaced.
                            if plain_pp_columns_dd:
                                pad = self._assoc_plain_column_label_pad(
                                    dd, hlbl, plain_col_px
                                )
                                if pad:
                                    dropdown_parts.append(_ATTACH + pad)
                                    _dropdown_dds.append(None)
                                dropdown_parts.append(_ATTACH + detail)
                                _dropdown_dds.append(_asc_proxy)
                                if plain_col_px > 0:
                                    bullet_px_by_dropdown_idx[len(dropdown_parts) - 1] = (
                                        plain_col_px + _PLAIN_COL_VALUE_WRAP_FLAG
                                    )
                            else:
                                dropdown_parts.append(_ATTACH + " " + detail)
                                _dropdown_dds.append(_asc_proxy)
                        else:
                            # Header text (primary formatting)
                            dropdown_parts.append(_ATTACH + hdr)
                            _dropdown_dds.append(_pri_proxy)
                            # Detail text (associated formatting), if any
                            if detail:
                                dropdown_parts.append(_ATTACH + ": ")
                                _dropdown_dds.append(None)
                                dropdown_parts.append(_ATTACH + detail)
                                _dropdown_dds.append(_asc_proxy)
                        first_bullet = False
                        any_bullet = True
                    if emitted_plain_pp:
                        dropdown_parts.append("\n")
                        _dropdown_dds.append(None)
                    if not any_bullet:
                        continue
                    continue

                is_multi = bool(dd.get("multi"))
                if is_multi and bool(dd.get("multi_bullets")) and j < len(meta_row):
                    meta = meta_row[j]
                    lb = meta.get("lb")
                    its = list(meta.get("items") or [])
                    appended = False
                    chosen_idxs = self._multi_selected_source_indexes(meta)
                    if chosen_idxs is None and isinstance(lb, tk.Listbox):
                        try:
                            if lb.winfo_exists():
                                chosen_idxs = [int(x) for x in lb.curselection()]
                        except Exception:
                            chosen_idxs = None
                    if chosen_idxs:
                        chosen = [
                            _wrap_long_bullet_tokens(dd, self._resolve_vars(str(its[k])).strip())
                            for k in chosen_idxs
                            if 0 <= k < len(its)
                        ]
                        chosen = [x for x in chosen if x]
                        if chosen:
                            bp0 = _bullet_line_prefix(dd, True)
                            bpn = _bullet_line_prefix(dd, False)
                            block = bp0 + chosen[0] + "".join(bpn + c for c in chosen[1:])
                            if _bullet_px_by_part_idx is not None:
                                bi = len(dropdown_parts)
                                bullet_px_by_dropdown_idx[bi] = self._simple_tab_bullet_wrap_indent_px(dd)
                            self._append_multi_full_prefix_fragment(dd, dropdown_parts, _dropdown_dds)
                            dropdown_parts.append(block)
                            _dropdown_dds.append(dd)
                            appended = True
                    if appended:
                        continue
                    val_fb = self._resolve_vars(var.get() or "").strip()
                    if not val_fb or _is_omit_phrase(val_fb):
                        continue
                    self._append_multi_full_prefix_fragment(dd, dropdown_parts, _dropdown_dds)
                    dropdown_parts.append(val_fb)
                    _dropdown_dds.append(dd)
                    continue

                val = self._resolve_vars(var.get() or "").strip()
                if not val or _is_omit_phrase(val):
                    continue

                if not is_multi and bool(dd.get("multi_bullets")):
                    self._append_single_full_prefix_fragment(dd, dropdown_parts, _dropdown_dds)
                    block = _bullet_line_prefix(dd, True) + _wrap_long_bullet_tokens(dd, val.strip())
                    if _bullet_px_by_part_idx is not None:
                        bi = len(dropdown_parts)
                        bullet_px_by_dropdown_idx[bi] = self._simple_tab_bullet_wrap_indent_px(dd)
                    dropdown_parts.append(block)
                    _dropdown_dds.append(dd)
                    continue

                val = _apply_narrative_tail_to_fragment(val, dd)
                if is_multi:
                    self._append_multi_full_prefix_fragment(dd, dropdown_parts, _dropdown_dds)
                else:
                    self._append_single_full_prefix_fragment(dd, dropdown_parts, _dropdown_dds)
                dropdown_parts.append(val)
                _dropdown_dds.append(dd)

        if i < len(self.note_combo_vars) and len(self.note_combo_vars[i]) > 0 and not dropdown_parts:
            return []

        has_bullet_fragment = any(str(p).startswith("\n") for p in dropdown_parts if p)
        rp_for_parts = _prefix_before_bullet_list(rp) if (rp and has_bullet_fragment) else rp

        parts: list[str] = []
        parts_dds: list[dict | None] = []
        rp_offset = 0
        if rp_for_parts:
            parts.append(rp_for_parts)
            parts_dds.append(None)
            rp_offset = 1
        for bi, px in bullet_px_by_dropdown_idx.items():
            if _bullet_px_by_part_idx is not None:
                _bullet_px_by_part_idx[rp_offset + bi] = px
        parts.extend(dropdown_parts)
        parts_dds.extend(_dropdown_dds)

        if _dd_out is not None:
            _dd_out.extend(parts_dds)
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

    def _compose_builder_annotated_runs(self) -> list[tuple[str, "str | None", "int | None"]]:
        """
        Produce (text_chunk, tag_name_or_None, bullet_wrap_px_or_None) tuples for the full composed output.
        The plain text of all runs concatenated equals _compose_builder_text().
        Tags are derived from each dropdown's text_format flags.
        """
        # Cleared once per annotated compose; PDF plain-grid markers match runs order.
        self._fs_plain_grid_pdf_export_rows = []
        all_runs: list[tuple[str, str | None, int | None]] = []
        first_block = True
        for i, tmpl in enumerate(self.templates):
            if i >= len(self.note_combo_vars):
                break
            tid = int(tmpl["id"])
            if self._visit_skip_by_tid.get(tid, False):
                continue
            dd_out: list[dict | None] = []
            bullet_px: dict[int, int] = {}
            parts = self._compose_parts_for_template(
                i,
                tmpl,
                _dd_out=dd_out,
                _bullet_px_by_part_idx=bullet_px,
            )
            if not parts:
                continue
            while len(dd_out) < len(parts):
                dd_out.append(None)
            runs = _finalize_family_social_block_annotated(
                parts,
                dd_out[: len(parts)],
                bullet_wrap_by_part_idx=bullet_px or None,
            )
            if not runs:
                continue
            if not first_block:
                all_runs.append(("\n\n", None, None))
            all_runs.extend(runs)
            first_block = False
        return all_runs

    def _runs_from_text_widget(self) -> list[tuple[str, "str | None", "int | None"]]:
        """Read the bottom text widget content as (chunk, fmt_tag, wrap_px) runs.

        Used as a fallback when the note diverges from the builder output so
        that bold/italic/underline formatting and bullet continuation indents
        that are still present in the Tk Text widget survive into the Live
        Preview and the PDF.
        """
        try:
            full_text = self.text.get("1.0", "end-1c")
        except tk.TclError:
            return []
        n = len(full_text)
        if n == 0:
            return []

        # Convert Tk "line.col" index to a 0-based linear char offset.
        lines_split = full_text.split("\n")
        line_starts = [0]
        for ln in lines_split[:-1]:
            line_starts.append(line_starts[-1] + len(ln) + 1)

        def _tk_to_offset(tk_idx: str) -> int:
            try:
                ln_s, col_s = str(tk_idx).split(".", 1)
                ln = int(ln_s) - 1  # 1-based → 0-based
                col = int(col_s)
                if ln < 0:
                    return 0
                if ln >= len(line_starts):
                    return n
                return min(line_starts[ln] + col, n)
            except Exception:
                return 0

        # Per-character arrays: which format tag applies, and what wrap px.
        fmt_at: list[str | None] = [None] * n
        wrap_at: list[int] = [0] * n

        _fmt_tags = [
            "_FMT_B", "_FMT_I", "_FMT_BI",
            "_FMT_U", "_FMT_BU", "_FMT_IU", "_FMT_BIU",
        ]
        for tag in _fmt_tags:
            try:
                ranges = self.text.tag_ranges(tag)
            except tk.TclError:
                continue
            for i in range(0, len(ranges), 2):
                s = _tk_to_offset(str(ranges[i]))
                e = _tk_to_offset(str(ranges[i + 1]))
                for k in range(s, min(e, n)):
                    fmt_at[k] = tag

        for px, tag in list(self._bullet_wrap_tag_by_px.items()):
            try:
                ranges = self.text.tag_ranges(tag)
            except tk.TclError:
                continue
            for i in range(0, len(ranges), 2):
                s = _tk_to_offset(str(ranges[i]))
                e = _tk_to_offset(str(ranges[i + 1]))
                for k in range(s, min(e, n)):
                    wrap_at[k] = px

        for px, tag in list(self._column_tab_tag_by_px.items()):
            try:
                ranges = self.text.tag_ranges(tag)
            except tk.TclError:
                continue
            for i in range(0, len(ranges), 2):
                s = _tk_to_offset(str(ranges[i]))
                e = _tk_to_offset(str(ranges[i + 1]))
                for k in range(s, min(e, n)):
                    wrap_at[k] = -int(px)

        for px, tag in list(self._column_val_wrap_tag_by_px.items()):
            try:
                ranges = self.text.tag_ranges(tag)
            except tk.TclError:
                continue
            for i in range(0, len(ranges), 2):
                s = _tk_to_offset(str(ranges[i]))
                e = _tk_to_offset(str(ranges[i + 1]))
                for k in range(s, min(e, n)):
                    wrap_at[k] = int(px) + _PLAIN_COL_VALUE_WRAP_FLAG

        # Group consecutive characters with the same (fmt_tag, wrap_px) into runs.
        runs: list[tuple[str, str | None, int | None]] = []
        i = 0
        while i < n:
            cur_fmt = fmt_at[i]
            cur_wrap = wrap_at[i]
            j = i + 1
            while j < n and fmt_at[j] == cur_fmt and wrap_at[j] == cur_wrap:
                j += 1
            wrap_out = cur_wrap if cur_wrap != 0 else None
            runs.append((full_text[i:j], cur_fmt, wrap_out))
            i = j
        return runs

    def get_live_preview_annotated_runs(self) -> list[tuple[str, "str | None", "int | None"]]:
        """
        Return (text_chunk, tag, bullet_wrap_px) tuples suitable for the Live Preview text widget.
        Uses builder-annotated runs when the current note text matches the builder
        output; falls back to reading formatting directly from the text widget tags
        when the user has manually edited.
        """
        runs = self._compose_builder_annotated_runs()
        plain = "".join(t for t, _, _ in runs).strip()
        if plain != self.text.get("1.0", tk.END).strip() or self._user_has_formatted:
            widget_runs = self._runs_from_text_widget()
            return widget_runs if widget_runs else []
        return runs

    def get_rich_value(self) -> str:
        """
        Compose the note with inline ReportLab XML formatting tags (<b>, <i>, <u>).
        When the current note text has diverged from the builder output (user manually
        edited it), reads formatting directly from the text widget tags so bold/italic/
        underline annotations survive into the PDF.
        """
        from xml.sax.saxutils import escape as _xe

        def _wrap_run_safe(chunk: str, tag: "str | None") -> str:
            """Escape `chunk`, convert `\\n` to `<br/>`, and wrap each
            `<br/>`-separated segment in the run's bold/italic/underline
            tags.  Wrapping per-segment guarantees `<br/>` never appears
            INSIDE the formatting tags — splitting on `<br/>` downstream
            (e.g. in the PDF exporter) would otherwise produce unbalanced
            fragments that ReportLab silently degrades to plain text.
            """
            safe = _xe(chunk).replace("\n\n", "<br/><br/>").replace("\n", "<br/>")
            if not tag:
                return safe
            if tag == "LP_LABEL_BOLD":
                wrapped_segments: list[str] = []
                for seg in safe.split("<br/>"):
                    if seg:
                        seg = f"<b>{seg}</b>"
                    wrapped_segments.append(seg)
                return "<br/>".join(wrapped_segments)
            b = "B" in tag
            it = "I" in tag
            u = "U" in tag
            if not (b or it or u):
                return safe
            wrapped_segments = []
            for seg in safe.split("<br/>"):
                if seg:
                    if u:
                        seg = f"<u>{seg}</u>"
                    if it:
                        seg = f"<i>{seg}</i>"
                    if b:
                        seg = f"<b>{seg}</b>"
                wrapped_segments.append(seg)
            return "<br/>".join(wrapped_segments)

        def _rich_body_and_fs_grid_comments(
            runs_src: list[tuple[str, str | None, int | None]],
        ) -> str:
            export_rows = list(getattr(self, "_fs_plain_grid_pdf_export_rows", []) or [])
            parts: list[str] = []
            i = 0
            ri = 0
            n = len(runs_src)
            while i < n:
                if ri < len(export_rows):
                    matched, next_i = _plain_grid_runs_match_export_row(
                        runs_src, i, export_rows[ri]
                    )
                    if matched:
                        er = export_rows[ri]
                        # PDF consumes markers into a Plan-style table; omit duplicate inline XML here.
                        try:
                            grid_obj: dict = {
                                "h": er["h"],
                                "v": er["v"],
                                "hf": er["hf"],
                                "vf": er["vf"],
                            }
                            if str(er.get("align") or "") == "columns":
                                grid_obj["align"] = "columns"
                            payload = base64.urlsafe_b64encode(
                                json.dumps(grid_obj, separators=(",", ":")).encode("utf-8")
                            ).decode("ascii")
                            parts.append(f"<!--pdf_fs_grid:{payload}-->")
                        except Exception:
                            pass
                        ri += 1
                        i = next_i
                        continue
                ch, tag, _px = runs_src[i]
                parts.append(_wrap_run_safe(ch, tag))
                i += 1
            return "".join(parts)

        runs = self._compose_builder_annotated_runs()
        plain = "".join(t for t, _, _ in runs).strip()
        if plain != self.text.get("1.0", tk.END).strip() or self._user_has_formatted:
            # Builder output diverged, or user applied manual formatting — read
            # formatting directly from the text widget.
            widget_runs = self._runs_from_text_widget()
            if not widget_runs:
                return ""
            return "".join(_wrap_run_safe(chunk, tag) for chunk, tag, _px in widget_runs)
        return _rich_body_and_fs_grid_comments(runs)

    def get_builder_state(self) -> dict:
        """Serializable dropdown selections for exam JSON.
        Multi/single slots may use {"i": ..., "b": multi_bullets, "t": "," | "." optional}."""
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
                if meta.get("associated_multi") or meta.get("associated_per_primary"):
                    self._persist_assoc_column_widgets_into_meta(meta)
                    order = list(meta.get("primary_order") or [])
                    pss = meta.get("primary_selected_set")
                    if isinstance(pss, set):
                        order = [p for p in order if p in pss]
                    abp = meta.get("assoc_by_primary") or {}
                    sub_list: list[dict[str, list[int]]] = []
                    for pix in order:
                        cell = abp.get(pix)
                        if isinstance(cell, set):
                            sub_list.append({"i": sorted(int(x) for x in cell)})
                        elif isinstance(cell, dict):
                            ii = cell.get("i")
                            sub_list.append(
                                {
                                    "i": sorted(
                                        int(x)
                                        for x in (ii if isinstance(ii, (list, tuple)) else [])
                                    )
                                }
                            )
                        else:
                            sub_list.append({"i": []})
                    dd_states.append({"am": {"po": order, "sub": sub_list}})
                    continue

                if meta.get("multi"):
                    idxs: list[int] = self._multi_selected_source_indexes(meta) or []
                    if not idxs:
                        lb = meta.get("lb")
                        if isinstance(lb, tk.Listbox):
                            try:
                                if lb.winfo_exists():
                                    idxs = [int(x) for x in lb.curselection()]
                            except Exception:
                                pass
                    slot_m: dict = {"i": idxs, "b": bool(dd.get("multi_bullets"))}
                    tv_m = dd.get("narrative_tail")
                    if tv_m in (",", "."):
                        slot_m["t"] = tv_m
                    dd_states.append(slot_m)
                else:
                    val = (var.get() or "").strip()
                    if _is_omit_phrase(val):
                        dd_states.append(None)
                    else:
                        try:
                            ix = items.index(val)
                        except ValueError:
                            dd_states.append(None)
                        else:
                            st_s: dict = {"i": ix, "b": bool(dd.get("multi_bullets"))}
                            tv_s = dd.get("narrative_tail")
                            if tv_s in (",", "."):
                                st_s["t"] = tv_s
                            dd_states.append(st_s)
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

                if meta.get("associated_multi") or meta.get("associated_per_primary"):
                    self._persist_assoc_column_widgets_into_meta(meta)
                    pri_items = meta.get("primary_items") or list(dd.get("items") or [])
                    parsed_am: dict | None = None
                    if isinstance(raw_slot, dict) and isinstance(raw_slot.get("am"), dict):
                        parsed_am = raw_slot["am"]
                    po_list: list[int] = []
                    sub_entries: list[set[int]] = []
                    if isinstance(parsed_am, dict):
                        raw_po = parsed_am.get("po")
                        if isinstance(raw_po, list):
                            for x in raw_po:
                                try:
                                    xi = int(x)
                                except (TypeError, ValueError):
                                    continue
                                if 0 <= xi < len(pri_items):
                                    po_list.append(xi)
                        raw_sub = parsed_am.get("sub")
                        if isinstance(raw_sub, list):
                            for cell in raw_sub:
                                ixset: set[int] = set()
                                if isinstance(cell, dict):
                                    rr = cell.get("i")
                                    if isinstance(rr, list):
                                        for y in rr:
                                            try:
                                                iy = int(y)
                                            except (TypeError, ValueError):
                                                continue
                                            ixset.add(iy)
                                elif isinstance(cell, list):
                                    for y in cell:
                                        try:
                                            ixset.add(int(y))
                                        except (TypeError, ValueError):
                                            pass
                                sub_entries.append(ixset)
                    pss_raw = meta.get("primary_selected_set")
                    if isinstance(pss_raw, set):
                        pss_raw.clear()
                        pss_raw.update(po_list)

                    od = meta["primary_order"]
                    if isinstance(od, list):
                        od.clear()
                        od.extend(po_list)

                    abp_dst = meta.get("assoc_by_primary")
                    if isinstance(abp_dst, dict):
                        abp_dst.clear()
                        for qi, pix in enumerate(po_list):
                            chosen = set(sub_entries[qi]) if qi < len(sub_entries) else set()
                            if meta.get("associated_per_primary"):
                                ppa_r = dd.get("per_primary_associates") or []
                                cap = len(ppa_r[pix]) if 0 <= pix < len(ppa_r) else 0
                                chosen = {
                                    x for x in chosen if isinstance(x, int) and 0 <= x < cap
                                }
                            abp_dst[pix] = set(chosen)

                    meta["highlight_primary_idx"] = po_list[-1] if po_list else None

                    rep = meta.get("_repaint_primary")
                    if callable(rep):
                        try:
                            rep()
                        except Exception:
                            pass
                    reb = meta.get("_rebuilder")
                    if callable(reb):
                        try:
                            reb()
                        except Exception:
                            pass

                    dv = meta.get("dummy_var")
                    if isinstance(dv, tk.StringVar):
                        try:
                            dv.set("")
                        except Exception:
                            pass
                    continue

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
                    if raw_slot is not _BUILDER_SLOT_DEFAULT and isinstance(raw_slot, dict):
                        if dd.get("multi_bullets"):
                            dd.pop("narrative_tail", None)
                        elif "t" in raw_slot:
                            tv = raw_slot.get("t")
                            if tv in (",", "."):
                                dd["narrative_tail"] = tv
                            else:
                                dd.pop("narrative_tail", None)
                    fv = meta.get("fmt_var")
                    if isinstance(fv, tk.StringVar):
                        try:
                            fv.set(_format_output_radio_value(dd))
                        except Exception:
                            pass
                    sel_set = meta.get("selected_set")
                    if isinstance(sel_set, set):
                        sel_set.clear()
                        for ix in idxs:
                            if 0 <= ix < len(items):
                                sel_set.add(int(ix))
                    if isinstance(lb, tk.Listbox):
                        try:
                            lb.selection_clear(0, tk.END)
                            visible = meta.get("visible_to_source")
                            if isinstance(visible, list):
                                for vis_i, src_idx in enumerate(visible):
                                    if src_idx in (sel_set if isinstance(sel_set, set) else set(idxs)):
                                        lb.selection_set(vis_i)
                            else:
                                for ix in idxs:
                                    if 0 <= ix < lb.size():
                                        lb.selection_set(ix)
                            ordered = sorted(sel_set) if isinstance(sel_set, set) else idxs
                            chosen = [items[k] for k in ordered if 0 <= k < len(items)]
                            var.set(_join_with_oxford_and(chosen))
                        except Exception:
                            var.set("")
                    else:
                        var.set("")
                else:
                    fv_single = meta.get("fmt_var")
                    if raw_slot is _BUILDER_SLOT_DEFAULT:
                        var.set(items[0] if items else OPTION_OMIT)
                    elif raw_slot is None:
                        var.set(OPTION_OMIT)
                    elif isinstance(raw_slot, dict):
                        ri = raw_slot.get("i")
                        if isinstance(ri, int) and 0 <= ri < len(items):
                            var.set(items[ri])
                        else:
                            var.set(items[0] if items else OPTION_OMIT)
                        if "b" in raw_slot:
                            dd["multi_bullets"] = bool(raw_slot["b"])
                        if dd.get("multi_bullets"):
                            dd.pop("narrative_tail", None)
                        elif "t" in raw_slot:
                            tv = raw_slot.get("t")
                            if tv in (",", "."):
                                dd["narrative_tail"] = tv
                            else:
                                dd.pop("narrative_tail", None)
                        if isinstance(fv_single, tk.StringVar):
                            try:
                                fv_single.set(_format_output_radio_value(dd))
                            except Exception:
                                pass
                    elif isinstance(raw_slot, int) and 0 <= raw_slot < len(items):
                        var.set(items[raw_slot])
                        if isinstance(fv_single, tk.StringVar):
                            try:
                                fv_single.set(_format_output_radio_value(dd))
                            except Exception:
                                pass
                    else:
                        var.set(items[0] if items else OPTION_OMIT)

    def _apply_builder_to_note(self) -> None:
        # Belt-and-suspenders: if this section's text widget has already been
        # destroyed (e.g. a stray late-arriving demographic-var trace fired
        # after the page tore down this sub-heading), do nothing instead of
        # raising `TclError: invalid command name`.  With the page-owned
        # trace lifecycle this branch should be unreachable, but it keeps
        # the surface defensive against any future code path that calls in.
        try:
            if not self.text.winfo_exists():
                return
        except tk.TclError:
            return
        runs = self._compose_builder_annotated_runs()
        self.text.delete("1.0", tk.END)
        self._insert_builder_runs(runs)
        self._user_has_formatted = False   # builder rewrote the text; reset flag
        self._update_age_hint()
        self.on_change_callback()

    def _persist_assoc_column_widgets_into_meta(self, meta: dict) -> None:
        """Sync each associate listbox selection set into assoc_by_primary.

        Stores the SAME set object (not a copy) so that subsequent listbox
        clicks — which mutate the widget's `selected_set` in place — remain
        visible through `assoc_by_primary[pidx]`.

        Earlier this copied with `set(ss)`, which detached the widget's set
        from `assoc_by_primary` after every autosave (because autosave calls
        `get_builder_state()` → this method). After detachment, listbox
        clicks updated the orphaned widget set while composition kept reading
        the stale `assoc_by_primary` copy, so newly chosen detail items never
        appeared in the note / live preview / PDF.
        """
        wmap = meta.get("assoc_column_widgets") or {}
        dst = meta.setdefault("assoc_by_primary", {})
        if not isinstance(dst, dict):
            return
        for pidx, wdg in wmap.items():
            try:
                k = int(pidx)
            except (TypeError, ValueError):
                continue
            ss = wdg.get("selected_set")
            if isinstance(ss, set):
                dst[k] = ss

    # --- "Scroll to top" hint button (flashes on hover when scroll != 0) -------
    # Workaround for the layout-shift bug that nudges the canvas viewport when a
    # primary listbox is clicked while the canvas is scrolled below the top.
    # Hover behavior is FLASH-ONLY — never auto-scrolls — so it cannot trigger
    # the cascading <Enter> feedback loop that froze Tk in an earlier attempt.
    _SCROLL_BTN_FLASH_INTERVAL_MS = 380
    _SCROLL_BTN_COLOR_A = "#FFC107"  # amber
    _SCROLL_BTN_COLOR_B = "#FFE082"  # light amber
    _SCROLL_BTN_AT_TOP_EPSILON = 0.001

    def _find_enclosing_scroll_canvas(self, w: tk.Misc) -> tk.Canvas | None:
        """Walk up the master chain until we hit the sentence-builder scroll canvas."""
        nb = getattr(self, "note_builder_canvas", None)
        if nb is None:
            return None
        known: list[tk.Misc] = [nb]
        cur: tk.Misc | None = w
        # Bound the walk to avoid runaway loops on malformed widget trees.
        for _ in range(64):
            if cur is None:
                return None
            if cur in known:
                return cur  # type: ignore[return-value]
            cur = getattr(cur, "master", None)
        return None

    def _scroll_btn_canvas_at_top(self, canvas: tk.Canvas | None) -> bool:
        if canvas is None:
            return True
        try:
            if not canvas.winfo_exists():
                return True
            return float(canvas.yview()[0]) <= self._SCROLL_BTN_AT_TOP_EPSILON
        except Exception:
            return True

    def _scroll_btn_stop_flash(self, btn: tk.Button) -> None:
        try:
            aid = getattr(btn, "_flash_after_id", None)
        except Exception:
            aid = None
        if aid is not None:
            try:
                btn.after_cancel(aid)
            except Exception:
                pass
            try:
                btn._flash_after_id = None  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            if btn.winfo_exists():
                btn.configure(bg=getattr(btn, "_default_bg", "SystemButtonFace"))
        except Exception:
            pass

    def _scroll_btn_flash_step(
        self,
        btn: tk.Button,
        canvas: tk.Canvas | None,
        on: bool,
    ) -> None:
        try:
            if not btn.winfo_exists():
                return
        except Exception:
            return
        # Stop flashing the moment the canvas reaches the top.
        if self._scroll_btn_canvas_at_top(canvas):
            self._scroll_btn_stop_flash(btn)
            return
        try:
            btn.configure(
                bg=(self._SCROLL_BTN_COLOR_A if on else self._SCROLL_BTN_COLOR_B)
            )
        except Exception:
            return
        try:
            aid = btn.after(
                self._SCROLL_BTN_FLASH_INTERVAL_MS,
                lambda: self._scroll_btn_flash_step(btn, canvas, not on),
            )
            btn._flash_after_id = aid  # type: ignore[attr-defined]
        except Exception:
            pass

    def _scroll_btn_start_flash(self, btn: tk.Button, canvas: tk.Canvas | None) -> None:
        # Already flashing -> don't stack another schedule.
        if getattr(btn, "_flash_after_id", None) is not None:
            return
        # Only flash when there's actually somewhere to scroll up to.
        if self._scroll_btn_canvas_at_top(canvas):
            return
        self._scroll_btn_flash_step(btn, canvas, True)

    def _scroll_btn_clicked(self, btn: tk.Button, canvas: tk.Canvas | None) -> None:
        self._scroll_btn_stop_flash(btn)
        if canvas is None:
            return
        try:
            if canvas.winfo_exists():
                canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _render_associated_multi_row(self, card: ttk.Frame, dd: dict, dd_slot_index: int = 0) -> tuple[tk.StringVar, dict]:
        """
        Build primary multi-select plus one illuminated paired list box per ordered primary pick.

        Shared Associated Multiple (`associated_multi`) uses one secondary pool for every primary.
        Associated per primary (`associated_per_primary`) binds a distinct secondary item list to each primary row.
        """
        dd.setdefault("associate_label", "Associated detail")
        primary_items: list[str] = list(dd.get("items") or [])
        per_primary = bool(dd.get("associated_per_primary"))
        if per_primary:
            dd["associated_multi"] = False
            dd["multi"] = False
            dd.setdefault("assoc_primary_use_bullets", True)
            dd.setdefault("assoc_primary_plain_columns", False)
            dd.setdefault("associate_items", [])
            ppa_root = dd.setdefault("per_primary_associates", [])
            while len(ppa_root) < len(primary_items):
                ppa_root.append([])
            del ppa_root[len(primary_items):]
            assoc_items_tm: list[str] = []
        else:
            dd.setdefault("associate_items", ["Option A", "Option B"])
            assoc_items_tm = list(dd.get("associate_items") or [])
        var = tk.StringVar(value="")
        assoc_host = ttk.Frame(card)

        meta: dict = {
            "associated_multi": not per_primary,
            "associated_per_primary": per_primary,
            "multi": False,
            "dummy_var": var,
            "primary_items": primary_items,
            "associate_items": assoc_items_tm,
            "assoc_by_primary": {},
            "primary_order": [],
            "highlight_primary_idx": None,
            "assoc_host": assoc_host,
            "assoc_column_widgets": {},
        }

        dd_ref = dd
        dd_slot_i = max(0, int(dd_slot_index))

        top_fr = ttk.Frame(card)
        top_fr.pack(fill="x")

        if per_primary:
            pt = (dd_ref.get("label") or "Option") + (
                " — select one or more; each primary has its own secondary list:"
            )
            hint_txt = (
                "Click to select  •  Ctrl+click to deselect  •  "
                "each primary opens its own paired options column."
            )
        else:
            pt = (dd_ref.get("label") or "Option") + (
                " — select one or more (each choice adds its paired detail list below):"
            )
            hint_txt = "Click to select  •  Ctrl+click to deselect"
        ttk.Label(top_fr, text=pt).pack(anchor="w")
        ttk.Label(
            top_fr,
            text=hint_txt,
            font=("Segoe UI", 8),
            foreground="gray",
        ).pack(anchor="w")

        if per_primary:
            lay_fr = ttk.Frame(top_fr)
            lay_fr.pack(anchor="w", pady=(4, 2))
            ttk.Label(lay_fr, text="Printed rows:").pack(side="left", padx=(0, 8))
            lay_var = tk.StringVar(
                value="bullets" if dd_ref.get("assoc_primary_use_bullets", True) else "plain"
            )

            def _save_assoc_layout() -> None:
                dd_ref["assoc_primary_use_bullets"] = lay_var.get() == "bullets"
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            ttk.Radiobutton(
                lay_fr,
                text="Bullet lines",
                variable=lay_var,
                value="bullets",
                command=_save_assoc_layout,
            ).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                lay_fr,
                text="No bullet lines",
                variable=lay_var,
                value="plain",
                command=_save_assoc_layout,
            ).pack(side="left")

            col_fr = ttk.Frame(top_fr)
            col_var = tk.StringVar(
                value="columns"
                if dd_ref.get("assoc_primary_plain_columns", False)
                else "inline"
            )

            def _save_assoc_col_layout() -> None:
                dd_ref["assoc_primary_plain_columns"] = col_var.get() == "columns"
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            def _toggle_col_layout_opts(*_a: object) -> None:
                if lay_var.get() == "plain":
                    col_fr.pack(anchor="w", pady=(2, 0))
                else:
                    col_fr.pack_forget()

            ttk.Label(col_fr, text="Detail alignment:").pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                col_fr,
                text="After label",
                variable=col_var,
                value="inline",
                command=_save_assoc_col_layout,
            ).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                col_fr,
                text="Aligned column",
                variable=col_var,
                value="columns",
                command=_save_assoc_col_layout,
            ).pack(side="left")
            lay_var.trace_add("write", lambda *_: _toggle_col_layout_opts())
            _toggle_col_layout_opts()

        # Resolve the enclosing scroll canvas now so we don't walk the widget
        # tree on every hover tick. Used below by the "Scroll to top" hint
        # button (created next to "Clear primary selections" further down).
        target_canvas = self._find_enclosing_scroll_canvas(top_fr)

        search_var = tk.StringVar(value="")
        selected_set_primary: set[int] = set()
        meta["primary_selected_set"] = selected_set_primary
        visible_pri: list[int] = list(range(len(primary_items)))

        sf = ttk.Frame(top_fr)
        sf.pack(fill="x", pady=(4, 2))
        ttk.Label(sf, text="Search:").pack(side="left")
        ttk.Entry(sf, textvariable=search_var).pack(side="left", fill="x", expand=True, padx=(4, 4))

        lb_wrap = ttk.Frame(top_fr)
        lb_wrap.pack(fill="x")
        plb_h = min(max(len(primary_items), 3), 10)
        plb = tk.Listbox(lb_wrap, selectmode=tk.EXTENDED, height=plb_h, activestyle="dotbox", exportselection=False)
        for it in primary_items:
            plb.insert(tk.END, it)
        plb.pack(side="left", fill="x", expand=True)
        plsb = ttk.Scrollbar(lb_wrap, orient="vertical", command=plb.yview)
        plb.configure(yscrollcommand=plsb.set)
        plsb.pack(side="right", fill="y")
        meta["primary_lb"] = plb

        def _flush_assoc() -> None:
            self._persist_assoc_column_widgets_into_meta(meta)

        def _refresh_primary_filter() -> None:
            # Trace can outlive `plb` when the note-builder is re-rendered.
            try:
                if not plb.winfo_exists():
                    return
            except tk.TclError:
                return
            try:
                idxs = self._filter_items_by_prefix(primary_items, search_var.get())
                visible_pri[:] = idxs
                plb.delete(0, tk.END)
                for src_i in idxs:
                    plb.insert(tk.END, primary_items[src_i])
                for vis_i, src_i in enumerate(idxs):
                    if src_i in selected_set_primary:
                        plb.selection_set(vis_i)
            except tk.TclError:
                return

        meta["_repaint_primary"] = _refresh_primary_filter

        search_var.trace_add(
            "write",
            lambda *_a: _refresh_primary_filter(),
        )

        _primary_sync_token = [0]
        _primary_retry_after_id = [None]

        def _cancel_primary_retry() -> None:
            aid = _primary_retry_after_id[0]
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
                _primary_retry_after_id[0] = None

        def _schedule_primary_sync() -> None:
            """Defer sync until Tk finalizes listbox selection; coalesce bursts and cancel stale retries."""
            _cancel_primary_retry()
            _primary_sync_token[0] += 1
            tok = _primary_sync_token[0]

            def _run() -> None:
                if tok != _primary_sync_token[0]:
                    return
                _sync_primary_from_lb(0)

            self.after_idle(_run)

        def _sync_primary_from_lb(retry_phase: int = 0) -> None:
            before = frozenset(selected_set_primary)
            visible_as_set = set(visible_pri)
            had_visible_selected = bool(before & visible_as_set)

            sel_vis = set(plb.curselection())

            # Windows may report an empty selection for one event cycle during Ctrl-toggle; defer once.
            if (
                retry_phase == 0
                and not sel_vis
                and had_visible_selected
                and len(visible_pri) > 0
            ):
                sched_tok = _primary_sync_token[0]

                def _retry() -> None:
                    _primary_retry_after_id[0] = None
                    if sched_tok != _primary_sync_token[0]:
                        return
                    _sync_primary_from_lb(1)

                _cancel_primary_retry()
                _primary_retry_after_id[0] = self.after(45, _retry)
                return

            for vis_i, src_i in enumerate(visible_pri):
                if vis_i in sel_vis:
                    selected_set_primary.add(src_i)
                else:
                    selected_set_primary.discard(src_i)
            after = selected_set_primary
            order: list[int] = meta["primary_order"]
            before_f = frozenset(before)
            after_f = frozenset(after)
            added_list = sorted(int(x) for x in after_f - before_f)
            removed_list = sorted(int(x) for x in before_f - after_f)
            for rm in removed_list:
                while rm in order:
                    order.remove(rm)
                meta["assoc_by_primary"].pop(rm, None)
            for ad in added_list:
                # New selections should immediately surface at the top so users
                # can work in the newly-created associated column without a second click.
                while ad in order:
                    order.remove(ad)
                order.insert(0, ad)
            if added_list:
                meta["highlight_primary_idx"] = added_list[-1]
            order[:] = [p for p in order if p in selected_set_primary]
            meta["dummy_var"].set("")
            def _rebuild_and_notify() -> None:
                _rebuild_assoc_columns()
                self._on_builder_selection_changed()
            self._run_with_note_builder_scroll_preserved(_rebuild_and_notify)

        def _rebuild_assoc_columns() -> None:
            _flush_assoc()
            for ch in assoc_host.winfo_children():
                ch.destroy()
            meta["assoc_column_widgets"].clear()

            assoc_label_txt = dd_ref.get("associate_label") or "Associated detail"
            order_li: list[int] = list(meta["primary_order"])
            if not per_primary:
                aitems_live: list[str] = dd_ref.setdefault("associate_items", list(assoc_items_tm))

            for pidx in order_li:
                if pidx not in selected_set_primary or not (0 <= pidx < len(primary_items)):
                    continue
                ptitle = primary_items[pidx]
                # Keep border colors stable by DD slot order (DD1/DD2/DD3...) so
                # colors stay consistent across templates regardless of source item index.
                bd = self._assoc_slot_color_for_dd(dd_ref, dd_slot_i)

                outer_col = tk.Frame(assoc_host, highlightthickness=2, highlightbackground=bd)
                outer_col.pack(fill="x", pady=(8, 0))

                lf = ttk.LabelFrame(
                    outer_col,
                    text=f"Paired selections for «{ptitle}»: {assoc_label_txt} — select one or more:",
                )
                lf.pack(fill="x")

                work_set = meta["assoc_by_primary"].setdefault(pidx, set())

                if per_primary:
                    ppa_live = dd_ref.setdefault("per_primary_associates", [])
                    while len(ppa_live) <= pidx:
                        ppa_live.append([])
                    opts_live = ppa_live[pidx]
                else:
                    opts_live = aitems_live

                sub_search = tk.StringVar(value="")
                vis_ast: list[int] = list(range(len(opts_live)))

                row1 = ttk.Frame(lf)
                row1.pack(fill="x", padx=4, pady=(4, 2))
                ttk.Label(row1, text="Search:").pack(side="left")
                ttk.Entry(row1, textvariable=sub_search).pack(side="left", fill="x", expand=True, padx=(4, 4))

                awrap = ttk.Frame(lf)
                awrap.pack(fill="x", padx=4)
                alb_h = min(max(len(opts_live), 3), 8)
                alb = tk.Listbox(awrap, selectmode=tk.EXTENDED, height=alb_h, activestyle="dotbox", exportselection=False)

                def _ref_ast(
                    _alb: tk.Listbox = alb,
                    _opts: list[str] = opts_live,
                    _vt: list[int] = vis_ast,
                    _sv: tk.StringVar = sub_search,
                    _wk: set[int] = work_set,
                ) -> None:
                    # sub_search trace can outlive _alb when assoc columns are
                    # rebuilt (e.g. on a primary selection change).
                    try:
                        if not _alb.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    try:
                        q_idxs = self._filter_items_by_prefix(_opts, _sv.get())
                        _vt[:] = q_idxs
                        _alb.delete(0, tk.END)
                        for si in q_idxs:
                            _alb.insert(tk.END, _opts[si])
                        for vi2, sr in enumerate(q_idxs):
                            if sr in _wk:
                                _alb.selection_set(vi2)
                    except tk.TclError:
                        return

                sub_search.trace_add("write", lambda *_b, __r=_ref_ast: __r())

                alb.pack(side="left", fill="x", expand=True)
                alsb = ttk.Scrollbar(awrap, orient="vertical", command=alb.yview)
                alb.configure(yscrollcommand=alsb.set)
                alsb.pack(side="right", fill="y")

                def _sync_assoc(
                    _alb: tk.Listbox = alb,
                    _vt: list[int] = vis_ast,
                    _wk: set[int] = work_set,
                ) -> None:
                    curv = set(_alb.curselection())
                    for vi2, sr in enumerate(_vt):
                        if vi2 in curv:
                            _wk.add(sr)
                        else:
                            _wk.discard(sr)
                    self._on_builder_selection_changed()

                alb.bind("<<ListboxSelect>>", lambda _e, __s=_sync_assoc: __s())
                self._bind_listbox_mousewheel_local(alb)

                def _add_assoc_item(
                    _opts: list[str] = opts_live,
                    _sv: tk.StringVar = sub_search,
                    __r=_ref_ast,
                    __syn=_sync_assoc,
                    _wk: set[int] = work_set,
                ) -> None:
                    txt = (_sv.get() or "").strip()
                    if not txt:
                        return
                    low = {str(x).strip().lower() for x in _opts}
                    if txt.lower() in low:
                        _sv.set("")
                        __r()
                        return
                    if per_primary:
                        _opts.append(txt)
                    else:
                        dd_ref.setdefault("associate_items", _opts)
                        _opts.append(txt)
                        meta["associate_items"] = list(dd_ref["associate_items"])
                    self._persist_templates()
                    _wk.add(len(_opts) - 1)
                    _sv.set("")
                    __r()
                    __syn()

                def _clear_col(_alb: tk.Listbox = alb, _wk: set[int] = work_set) -> None:
                    _wk.clear()
                    _alb.selection_clear(0, tk.END)
                    self._on_builder_selection_changed()

                btnrow = ttk.Frame(lf)
                btnrow.pack(fill="x", padx=4, pady=(0, 4))
                ttk.Button(btnrow, text="+ Add to List", command=_add_assoc_item).pack(side="left")
                ttk.Button(btnrow, text="Clear column", command=_clear_col).pack(side="left", padx=(8, 0))

                meta["assoc_column_widgets"][pidx] = {"selected_set": work_set}

                _ref_ast()

        meta["_rebuild_associated_cols"] = _rebuild_assoc_columns

        _hint_tip: list[tk.Toplevel | None] = [None]

        def _dismiss_hint() -> None:
            tip = _hint_tip[0]
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass
                _hint_tip[0] = None

        def _show_deselect_hint(event) -> None:
            _dismiss_hint()
            tip = tk.Toplevel(self)
            tip.overrideredirect(True)
            tip.wm_geometry(f"+{event.x_root + 14}+{event.y_root + 14}")
            tk.Label(
                tip,
                text="Hold Ctrl and click the item to deselect it.",
                background="#fff9c4",
                foreground="#333333",
                relief="solid",
                borderwidth=1,
                padx=8,
                pady=5,
                font=("Segoe UI", 9),
            ).pack()
            _hint_tip[0] = tip
            tip.after(2500, _dismiss_hint)

        def _promote_primary_assoc_column(src_idx: int) -> None:
            """Move the clicked primary's paired column to the top of the associated list."""
            if src_idx not in selected_set_primary:
                return
            order = meta.get("primary_order")
            if not isinstance(order, list):
                return

            # Keep selected order stable, but force the clicked primary to the first column.
            current_selected = set(selected_set_primary)
            reordered = [src_idx]
            reordered.extend(p for p in order if p in current_selected and p != src_idx)
            # Defensive: include any selected primary not present in `order`.
            extras = sorted(p for p in current_selected if p != src_idx and p not in order)
            reordered.extend(extras)

            if order == reordered and meta.get("highlight_primary_idx") == src_idx:
                return
            order[:] = reordered
            meta["highlight_primary_idx"] = src_idx
            self._run_with_note_builder_scroll_preserved(_rebuild_assoc_columns)

        def _on_primary_press(event, _plb=plb, _vis=visible_pri, _ss=selected_set_primary) -> str:
            """Plain click — add to selection only; show hint if item is already selected."""
            # Returning "break" prevents Tk's default class binding, which normally
            # transfers keyboard focus to the listbox.  Restore it explicitly so
            # selected items remain visually highlighted.
            _plb.focus_set()
            idx = _plb.nearest(event.y)
            if 0 <= idx < _plb.size() and idx < len(_vis):
                src = _vis[idx]
                if src not in _ss:
                    _dismiss_hint()
                    _plb.selection_set(idx)
                    _schedule_primary_sync()
                else:
                    _promote_primary_assoc_column(src)
                    _show_deselect_hint(event)
            return "break"

        def _on_primary_ctrl_press(event, _plb=plb, _vis=visible_pri, _ss=selected_set_primary) -> str:
            """Ctrl+click — confirm then deselect; Ctrl+clicking an unselected item is a no-op."""
            _plb.focus_set()
            _dismiss_hint()
            idx = _plb.nearest(event.y)
            if 0 <= idx < _plb.size() and idx < len(_vis):
                src = _vis[idx]
                if src in _ss:
                    item_name = primary_items[src] if 0 <= src < len(primary_items) else "this item"
                    if messagebox.askyesno(
                        "Remove selection",
                        f"Remove \"{item_name}\"?\n\n"
                        "This will also delete its associated paired-detail dropdown.",
                        icon="warning",
                    ):
                        _plb.selection_clear(idx)
                        _schedule_primary_sync()
            return "break"

        # Intercept mouse events before Tk's class-level EXTENDED bindings fire.
        # "break" prevents the default clear-and-select (or toggle) behaviour.
        plb.bind("<ButtonPress-1>", _on_primary_press)
        plb.bind("<Control-ButtonPress-1>", _on_primary_ctrl_press)
        # Suppress default Shift-click range-extend and button-motion drag-extend.
        plb.bind("<Shift-ButtonPress-1>", lambda e: "break")
        plb.bind("<B1-Motion>", lambda e: "break")
        # Keep keyboard navigation for accessibility.
        plb.bind("<KeyRelease-Up>", lambda _e: _schedule_primary_sync())
        plb.bind("<KeyRelease-Down>", lambda _e: _schedule_primary_sync())
        plb.bind("<KeyRelease-space>", lambda _e: _schedule_primary_sync())
        plb.bind("<KeyRelease-Return>", lambda _e: _schedule_primary_sync())
        self._bind_listbox_mousewheel_local(plb)

        def _add_primary_item() -> None:
            _cancel_primary_retry()
            txt = (search_var.get() or "").strip()
            if not txt:
                return
            low = {str(x).strip().lower() for x in primary_items}
            if txt.lower() in low:
                search_var.set("")
                _refresh_primary_filter()
                return
            dd_ref.setdefault("items", primary_items).append(txt)
            self._persist_templates()
            primary_items.append(txt)
            li = len(primary_items) - 1
            if per_primary:
                ppa_new = dd_ref.setdefault("per_primary_associates", [])
                while len(ppa_new) <= li:
                    ppa_new.append([])
                del ppa_new[len(primary_items):]
            selected_set_primary.add(li)
            od = meta.get("primary_order")
            if isinstance(od, list):
                while li in od:
                    od.remove(li)
                od.insert(0, li)
            meta["highlight_primary_idx"] = li
            search_var.set("")
            _refresh_primary_filter()
            if visible_pri:
                plb.selection_set(len(visible_pri) - 1)
            _sync_primary_from_lb(0)

        ttk.Button(sf, text="+ Add to List", command=_add_primary_item).pack(side="left")

        def _clear_primary() -> None:
            _cancel_primary_retry()
            selected_set_primary.clear()
            plb.selection_clear(0, tk.END)
            meta["primary_order"].clear()
            meta["assoc_by_primary"].clear()
            meta["highlight_primary_idx"] = None
            if self._clear_assoc_on_primary_clear:
                # Subjectives-on-Canvas behavior: this action should fully reset paired
                # detail selections too (equivalent to pressing "Clear column" on each).
                for wdg in (meta.get("assoc_column_widgets") or {}).values():
                    ss = wdg.get("selected_set")
                    if isinstance(ss, set):
                        ss.clear()
                meta["assoc_column_widgets"].clear()
            else:
                _flush_assoc()
            var.set("")
            def _rebuild_and_notify() -> None:
                _rebuild_assoc_columns()
                self._on_builder_selection_changed()
            self._run_with_note_builder_scroll_preserved(_rebuild_and_notify)

        # Bottom button row: "Clear primary selections" + flashing "Scroll to top" hint.
        # The hint button is ALWAYS packed (no layout change on hover) and flashes
        # only while the cursor is over `top_fr` AND the enclosing scroll canvas
        # is below the top. Hover handlers never auto-scroll, so they cannot
        # trigger the cascading <Enter> feedback loop that froze Tk in an
        # earlier attempt — only an explicit click moves the canvas.
        btn_row = ttk.Frame(top_fr)
        btn_row.pack(anchor="w", pady=(2, 0))
        ttk.Button(btn_row, text="Clear primary selections", command=_clear_primary).pack(side="left")

        if target_canvas is not None:
            scroll_btn = tk.Button(
                btn_row,
                text="\u2934 Scroll to top",
                font=("Segoe UI", 8, "bold"),
                padx=6,
                pady=1,
                bd=1,
                relief="solid",
                cursor="hand2",
            )
            try:
                scroll_btn._default_bg = scroll_btn.cget("bg")  # type: ignore[attr-defined]
            except Exception:
                scroll_btn._default_bg = "SystemButtonFace"  # type: ignore[attr-defined]
            scroll_btn._flash_after_id = None  # type: ignore[attr-defined]
            scroll_btn.configure(
                command=lambda b=scroll_btn, c=target_canvas: self._scroll_btn_clicked(b, c)
            )
            scroll_btn.pack(side="left", padx=(8, 0))

            # Bind on `top_fr` (not the button) so hovering anywhere over the
            # primary section — title, search box, listbox, clear button, etc.
            # — triggers the hint, not just the button itself.
            #
            # Tk fires <Leave> on a parent with detail=NotifyInferior when the
            # cursor moves from the parent's own area INTO one of its children
            # (still inside the parent's bounds). We ignore those so the flash
            # doesn't stutter on/off as the cursor moves across sub-widgets.
            def _on_top_fr_enter(_e, b=scroll_btn, c=target_canvas) -> None:
                self._scroll_btn_start_flash(b, c)

            def _on_top_fr_leave(e, b=scroll_btn) -> None:
                detail = getattr(e, "detail", None)
                if isinstance(detail, str) and "Inferior" in detail:
                    return
                self._scroll_btn_stop_flash(b)

            top_fr.bind("<Enter>", _on_top_fr_enter, add="+")
            top_fr.bind("<Leave>", _on_top_fr_leave, add="+")
        _refresh_primary_filter()
        assoc_host.pack(fill="x")
        meta["_rebuilder"] = _rebuild_assoc_columns
        meta["dummy_var"] = var
        return var, meta

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
        self._builder_dd_repack_by_tid = {}

        self._prefix_resolved_labels: list[ttk.Label] = []

        base_cols = max(1, int(self._TEMPLATE_GRID_COLUMNS))
        cols = 1 if len(self.templates) <= 1 else base_cols
        for col in range(cols):
            self.note_scroll_frame.grid_columnconfigure(col, weight=1, uniform="note_template_cols")

        prefix_wrap_px = 880 if cols == 1 else 420

        for idx, tmpl in enumerate(self.templates):
            row_idx = idx // cols
            col_idx = idx % cols
            left_gap = 2
            right_gap = self._TEMPLATE_GRID_COLUMN_GAP_PX if col_idx == 0 else 2

            band = tk.Frame(self.note_scroll_frame, bg=self._template_band_bg(idx))
            band.grid(
                row=row_idx,
                column=col_idx,
                sticky="nsew",
                padx=(left_gap, right_gap),
                pady=(2, self._TEMPLATE_GRID_ROW_GAP_PX),
            )

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
            pl = ttk.Label(card, text=f"Prefix (resolved): {pv}", wraplength=prefix_wrap_px)
            pl.pack(anchor="w", padx=8, pady=(6, 2))
            self._prefix_resolved_labels.append(pl)

            row_vars: list[tk.StringVar] = []
            meta_row: list[dict] = []
            dds = list(tmpl.get("dropdowns") or [])
            dd_host = ttk.Frame(card)
            dd_host.pack(fill="x", padx=8, pady=(2, 4))
            dd_frames: dict[int, ttk.LabelFrame] = {}

            top_idx = self._builder_dd_top_by_tid.get(tid)
            if not isinstance(top_idx, int) or top_idx < 0 or top_idx >= len(dds):
                top_idx = None
                self._builder_dd_top_by_tid.pop(tid, None)

            def _display_order_for_template(_tid: int = tid, _dds: list[dict] = dds) -> list[int]:
                if not _dds:
                    return []
                pinned = self._builder_dd_top_by_tid.get(_tid)
                if not isinstance(pinned, int) or pinned < 0 or pinned >= len(_dds):
                    return list(range(len(_dds)))
                return [pinned] + [i2 for i2 in range(len(_dds)) if i2 != pinned]

            active_switch_row: list[ttk.Frame | None] = [None]

            def _refresh_embedded_switch_row(
                _tid: int = tid,
                _dds: list[dict] = dds,
                _active_switch_row: list[ttk.Frame | None] = active_switch_row,
                _dd_frames: dict[int, ttk.LabelFrame] = dd_frames,
                _display_order_fn=_display_order_for_template,
            ) -> None:
                old_row = _active_switch_row[0]
                if old_row is not None:
                    try:
                        old_row.destroy()
                    except Exception:
                        pass
                    _active_switch_row[0] = None
                if len(_dds) <= 1:
                    return
                order_idxs = _display_order_fn()
                if not order_idxs:
                    return
                top_di = order_idxs[0]
                top_fr = _dd_frames.get(top_di)
                if top_fr is None:
                    return
                switch_row = ttk.Frame(top_fr)
                kids = top_fr.winfo_children()
                if kids:
                    switch_row.pack(fill="x", padx=6, pady=(2, 2), before=kids[0])
                else:
                    switch_row.pack(fill="x", padx=6, pady=(2, 2))
                ttk.Label(switch_row, text="Quick dropdown buttons:").pack(side="left", padx=(0, 4))
                for di, dd in enumerate(_dds):
                    btn_name = self._builder_dd_button_name(dd, di)
                    if di == top_di:
                        btn_name = f"[{btn_name}]"
                    tk.Button(
                        switch_row,
                        text=btn_name,
                        font=("Segoe UI", 8),
                        padx=5,
                        pady=1,
                        command=lambda _di=di, _tid2=_tid: self._on_template_dd_quick_switch(_tid2, _di),
                    ).pack(side="left", padx=(0, 4))
                _active_switch_row[0] = switch_row

            def _repack_dropdown_blocks(
                _tid: int = tid,
                _dd_host: ttk.Frame = dd_host,
                _dd_frames: dict[int, ttk.LabelFrame] = dd_frames,
                _display_order_fn=_display_order_for_template,
                _refresh_fn=_refresh_embedded_switch_row,
            ) -> None:
                order_idxs = _display_order_fn()
                for wid in _dd_host.winfo_children():
                    wid.pack_forget()
                for di2 in order_idxs:
                    fr2 = _dd_frames.get(di2)
                    if fr2 is not None:
                        fr2.pack(fill="x", pady=3)
                _refresh_fn()
            self._builder_dd_repack_by_tid[tid] = _repack_dropdown_blocks

            for di, dd in enumerate(dds):
                items = list(dd.get("items") or [])
                dd_name = self._builder_dd_button_name(dd, di)
                fr = ttk.LabelFrame(dd_host, text=f"Template {tmpl['id']} ({dd_name})")
                dd_frames[di] = fr
                if bool(dd.get("associated_per_primary")):
                    var_am, meta_am = self._render_associated_multi_row(fr, dd, di)
                    row_vars.append(var_am)
                    meta_row.append(meta_am)
                    continue
                if bool(dd.get("associated_multi")):
                    var_am, meta_am = self._render_associated_multi_row(fr, dd, di)
                    row_vars.append(var_am)
                    meta_row.append(meta_am)
                    continue
                is_multi = bool(dd.get("multi"))
                dd.setdefault("multi_bullets", False)
                fmt_row = ttk.Frame(fr)
                fmt_row.pack(anchor="w", fill="x", pady=(0, 4))
                ttk.Label(fmt_row, text="Output format:").pack(side="left", padx=(0, 8))
                _fmt_var = tk.StringVar(value=_format_output_radio_value(dd))

                def _on_output_format(_d=dd, _fv=_fmt_var) -> None:
                    _apply_output_format_radio(_d, _fv.get())
                    self._persist_templates()
                    self._apply_builder_to_note()
                    self.on_change_callback()

                ttk.Radiobutton(
                    fmt_row,
                    text="Narrative",
                    variable=_fmt_var,
                    value="narrative",
                    command=_on_output_format,
                ).pack(side="left", padx=(0, 8))
                ttk.Radiobutton(
                    fmt_row,
                    text="Bullet lines",
                    variable=_fmt_var,
                    value="bullets",
                    command=_on_output_format,
                ).pack(side="left", padx=(0, 8))
                ttk.Radiobutton(
                    fmt_row,
                    text="Comma",
                    variable=_fmt_var,
                    value="comma",
                    command=_on_output_format,
                ).pack(side="left", padx=(0, 8))
                ttk.Radiobutton(
                    fmt_row,
                    text="Period",
                    variable=_fmt_var,
                    value="period",
                    command=_on_output_format,
                ).pack(side="left")

                title = dd.get("label") or "Option"
                ttk.Label(
                    fr,
                    text=(title + ("" if not is_multi else " — select one or more")) + ":",
                ).pack(anchor="w")
                if is_multi:
                    var = tk.StringVar(value="")

                    # Search row — type to filter visible items by case-insensitive starts-with.
                    # Hidden selections are preserved via `selected_set` (source-item indexes), so
                    # the filter only changes what's *shown*, never what's selected.
                    search_var = tk.StringVar(value="")
                    selected_set: set[int] = set()
                    visible_to_source: list[int] = list(range(len(items)))

                    sf = ttk.Frame(fr)
                    sf.pack(fill="x", pady=(0, 2))
                    ttk.Label(sf, text="Search:").pack(side="left")
                    search_entry = ttk.Entry(sf, textvariable=search_var)
                    search_entry.pack(side="left", fill="x", expand=True, padx=(4, 4))

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

                    def _refresh_filter(
                        _lb: tk.Listbox = lb,
                        _opts: list[str] = items,
                        _vts: list[int] = visible_to_source,
                        _ss: set[int] = selected_set,
                        _sv: tk.StringVar = search_var,
                    ) -> None:
                        new_idxs = self._filter_items_by_prefix(_opts, _sv.get())
                        _vts[:] = new_idxs
                        _lb.delete(0, tk.END)
                        for src_idx in new_idxs:
                            _lb.insert(tk.END, _opts[src_idx])
                        for vis_i, src_idx in enumerate(new_idxs):
                            if src_idx in _ss:
                                _lb.selection_set(vis_i)

                    def _sync_multi(
                        _lb: tk.Listbox = lb,
                        _opts: list[str] = items,
                        _v: tk.StringVar = var,
                        _vts: list[int] = visible_to_source,
                        _ss: set[int] = selected_set,
                    ) -> None:
                        # Update `selected_set` only for currently-visible rows, then derive the
                        # composed text from the full set (so hidden selections still appear).
                        visible_sel = set(_lb.curselection())
                        for vis_i, src_idx in enumerate(_vts):
                            if vis_i in visible_sel:
                                _ss.add(src_idx)
                            else:
                                _ss.discard(src_idx)
                        chosen_idxs = sorted(_ss)
                        chosen = [_opts[i] for i in chosen_idxs if 0 <= i < len(_opts)]
                        _v.set(_join_with_oxford_and(chosen))

                    def _on_search_var_changed(*_a, _r=_refresh_filter) -> None:
                        _r()

                    search_var.trace_add("write", _on_search_var_changed)

                    # Bind sync via default args: `_sync_multi` is reassigned each loop iteration;
                    # bare name lookup in a nested def would call the *last* dropdown's sync only.
                    def _multi_changed(_e=None, _s=_sync_multi) -> None:
                        _s()
                        self._on_builder_selection_changed()

                    def _clear_multi(_lb=lb, _s=_sync_multi, _ss=selected_set) -> None:
                        _ss.clear()
                        _lb.selection_clear(0, tk.END)
                        _s()
                        self._on_builder_selection_changed()

                    def _add_to_list_multi(
                        _opts: list[str] = items,
                        _ss: set[int] = selected_set,
                        _sv: tk.StringVar = search_var,
                        _r=_refresh_filter,
                        _s=_sync_multi,
                        _dd: dict = dd,
                    ) -> None:
                        txt = (_sv.get() or "").strip()
                        if not txt:
                            return
                        existing_lower = {str(x).strip().lower() for x in _opts}
                        if txt.lower() in existing_lower:
                            # Already present — clear the search so the existing item is visible.
                            _sv.set("")
                            return
                        _opts.append(txt)
                        # Keep the underlying template dict in sync (the items list is a copy).
                        _dd.setdefault("items", []).append(txt)
                        _ss.add(len(_opts) - 1)
                        self._persist_templates()
                        # Sync the canvas editor (if mounted) so its listbox shows the new item.
                        try:
                            if hasattr(self, "canvas_scroll_frame") and self.canvas_scroll_frame.winfo_exists():
                                self._render_canvas_editor()
                        except Exception:
                            pass
                        _sv.set("")  # Clear search so the new item shows in the full list.
                        _r()  # Defensive — trace fires on set, but call explicitly for clarity.
                        _s()
                        self._on_builder_selection_changed()

                    lb.bind("<<ListboxSelect>>", _multi_changed)
                    self._bind_listbox_mousewheel_local(lb)

                    ttk.Button(sf, text="+ Add to List", command=_add_to_list_multi).pack(side="left")

                    ttk.Button(fr, text="Clear selection", command=_clear_multi).pack(anchor="w", pady=(2, 0))
                    ttk.Label(
                        fr,
                        text="Tip: Ctrl- or Shift-click to select multiple rows.",
                        font=("Segoe UI", 8),
                        foreground="gray",
                    ).pack(anchor="w", pady=(0, 0))
                    row_vars.append(var)
                    meta_row.append(
                        {
                            "multi": True,
                            "lb": lb,
                            "items": items,
                            "fmt_var": _fmt_var,
                            "selected_set": selected_set,
                            "visible_to_source": visible_to_source,
                            "search_var": search_var,
                        }
                    )
                else:
                    display_items = [OPTION_OMIT] + items
                    initial = items[0] if items else OPTION_OMIT
                    var = tk.StringVar(value=initial)
                    cb = ttk.Combobox(fr, textvariable=var, values=display_items, state="readonly", width=46)
                    cb.pack(fill="x")
                    cb.bind("<<ComboboxSelected>>", lambda e: self._on_builder_selection_changed())
                    self._bind_sentence_builder_readonly_combobox_wheel(cb)
                    row_vars.append(var)
                    meta_row.append({"multi": False, "lb": None, "items": items, "fmt_var": _fmt_var})

            _repack_dropdown_blocks()
            self.note_combo_vars.append(row_vars)
            self._note_builder_meta.append(meta_row)

        pad_h = self._NOTE_BUILDER_BOTTOM_SPACER_PX
        tail = tk.Frame(self.note_scroll_frame, height=pad_h)
        tail.grid(
            row=(len(self.templates) + cols - 1) // cols,
            column=0,
            columnspan=cols,
            sticky="ew",
        )
        tail.grid_propagate(False)

        self._sync_note_builder_scrollregion()
        # ttk + Windows can finalize heights one idle tick late; second sync catches the true extent.
        self.after_idle(self._sync_note_builder_scrollregion)

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

    @staticmethod
    def _builder_dd_button_name(dd: dict, di: int) -> str:
        raw = str(dd.get("builder_button_name") or "").strip()
        return raw or f"DD{di + 1}"

    @staticmethod
    def _associated_column_border_color(slot_index: int) -> str:
        """Stable color by associated slot index (DD1, DD2, DD3, ...)."""
        palette = [hexv for _name, hexv in ASSOC_SLOT_DEFAULT_COLORS]
        if slot_index < 0:
            return "#c8c8c8"
        return palette[slot_index % len(palette)]

    @staticmethod
    def _normalize_hex_color(raw: str) -> str | None:
        s = (raw or "").strip()
        if not s:
            return None
        if not s.startswith("#"):
            s = "#" + s
        if re.fullmatch(r"#[0-9a-fA-F]{6}", s):
            return s.upper()
        return None

    @staticmethod
    def _normalize_rgb_to_hex(raw: str) -> str | None:
        s = (raw or "").strip()
        if not s:
            return None
        parts = [p for p in re.split(r"[,\s]+", s) if p]
        if len(parts) != 3:
            return None
        vals: list[int] = []
        for p in parts:
            try:
                v = int(p)
            except Exception:
                return None
            if v < 0 or v > 255:
                return None
            vals.append(v)
        return "#{:02X}{:02X}{:02X}".format(vals[0], vals[1], vals[2])

    def _assoc_slot_color_for_dd(self, dd: dict, slot_index: int) -> str:
        custom = self._assoc_slot_colors if isinstance(self._assoc_slot_colors, list) else []
        if 0 <= slot_index < len(custom):
            hx = self._normalize_hex_color(str(custom[slot_index]))
            if hx:
                return hx
        return self._associated_column_border_color(slot_index)

    def _set_assoc_slot_color_for_dd(self, dd: dict, slot_index: int, color_hex: str) -> None:
        hx = self._normalize_hex_color(color_hex)
        if not hx or slot_index < 0:
            return
        arr = self._assoc_slot_colors if isinstance(self._assoc_slot_colors, list) else []
        if not isinstance(self._assoc_slot_colors, list):
            self._assoc_slot_colors = arr
            self.section["assoc_slot_colors"] = arr
        while len(arr) <= slot_index:
            arr.append(self._associated_column_border_color(len(arr)))
        arr[slot_index] = hx

    def _max_dropdown_count(self) -> int:
        try:
            return max((len(t.get("dropdowns") or []) for t in self.templates), default=0)
        except Exception:
            return 0

    def _ask_assoc_slot_color(self, slot_index: int, current_hex: str) -> str | None:
        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title(f"Choose color for DD{slot_index + 1}")
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        dlg.grab_set()
        ttk.Label(
            dlg,
            text=f"Pick color for DD{slot_index + 1}:",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))

        result: list[str | None] = [None]
        current_norm = self._normalize_hex_color(current_hex or "") or ""

        popular_box = ttk.LabelFrame(dlg, text="Popular colors")
        popular_box.pack(fill="x", padx=12, pady=(0, 8))
        row = ttk.Frame(popular_box)
        row.pack(fill="x", padx=8, pady=8)

        for name, hx in ASSOC_SLOT_DEFAULT_COLORS:
            is_selected = hx.upper() == current_norm.upper()
            # Wrap each button so the selected color can show a clear colored border ring.
            ring = tk.Frame(
                row,
                highlightthickness=(2 if is_selected else 0),
                highlightbackground=hx,
                highlightcolor=hx,
                bd=0,
            )
            ring.pack(side="left", padx=(0, 6), pady=(0, 2))
            btn = tk.Button(
                ring,
                text=f"\u25CF {name}",
                fg=hx,
                font=("Segoe UI", 9, "bold" if is_selected else "normal"),
                padx=6,
                pady=2,
                command=lambda _hx=hx: (result.__setitem__(0, _hx), dlg.destroy()),
            )
            btn.pack()

        adv = ttk.LabelFrame(dlg, text="Advanced")
        adv.pack(fill="x", padx=12, pady=(0, 10))
        hex_row = ttk.Frame(adv)
        hex_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(hex_row, text="Hex (#RRGGBB):").pack(side="left")
        hex_var = tk.StringVar(value=current_hex)
        ttk.Entry(hex_row, textvariable=hex_var, width=14).pack(side="left", padx=6)

        rgb_row = ttk.Frame(adv)
        rgb_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(rgb_row, text="RGB (r,g,b):").pack(side="left")
        rgb_var = tk.StringVar(value="")
        ttk.Entry(rgb_row, textvariable=rgb_var, width=16).pack(side="left", padx=6)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))

        def _use_hex() -> None:
            hx = self._normalize_hex_color(hex_var.get() or "")
            if not hx:
                messagebox.showwarning("Invalid color", "Enter a valid hex color like #F39C12.")
                return
            result[0] = hx
            dlg.destroy()

        def _use_rgb() -> None:
            hx = self._normalize_rgb_to_hex(rgb_var.get() or "")
            if not hx:
                messagebox.showwarning("Invalid color", "Enter RGB as r,g,b with values 0-255.")
                return
            result[0] = hx
            dlg.destroy()

        def _use_picker() -> None:
            _rgb, hx = colorchooser.askcolor(color=current_hex, parent=dlg)
            if hx:
                result[0] = self._normalize_hex_color(hx) or hx
                dlg.destroy()

        ttk.Button(btn_row, text="Use hex", command=_use_hex).pack(side="left")
        ttk.Button(btn_row, text="Use RGB", command=_use_rgb).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="More colors…", command=_use_picker).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="right")

        dlg.wait_window(dlg)
        return result[0]

    def _build_assoc_slot_color_editor(self, parent: ttk.Frame, dd: dict) -> None:
        band = ttk.LabelFrame(parent, text="Associated dropdown border colors (DD slots)")
        band.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Label(
            band,
            text="DD1/DD2/DD3 colors stay consistent across templates. Pick a slot from the dropdown menu to edit.",
        ).pack(anchor="w", padx=6, pady=(6, 4))

        slot_count = max(10, self._max_dropdown_count())
        select_row = ttk.Frame(band)
        select_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(select_row, text="Color slot:").pack(side="left")

        selected_label = tk.StringVar(value="")

        def _slot_label(si: int) -> str:
            cur_hex = self._assoc_slot_color_for_dd(dd, si)
            return f"DD{si + 1}  \u25CF {cur_hex}"

        def _slot_hex(si: int) -> str:
            return self._assoc_slot_color_for_dd(dd, si)

        if slot_count > 0:
            selected_label.set(_slot_label(0))

        menu_btn = tk.Menubutton(
            select_row,
            textvariable=selected_label,
            relief="raised",
            indicatoron=True,
            direction="below",
            padx=8,
            pady=2,
            width=24,
            anchor="w",
        )
        menu_btn.pack(side="left", padx=(6, 0))
        slot_menu = tk.Menu(menu_btn, tearoff=False)
        menu_btn.configure(menu=slot_menu)
        if slot_count > 0:
            try:
                menu_btn.configure(fg=_slot_hex(0))
            except Exception:
                pass

        def _pick_slot(_si: int, _dd=dd) -> None:
            selected_label.set(_slot_label(_si))
            try:
                menu_btn.configure(fg=_slot_hex(_si))
            except Exception:
                pass
            self._choose_assoc_slot_color_and_save(_dd, _si)

        for si in range(slot_count):
            cur_hex = self._assoc_slot_color_for_dd(dd, si)
            slot_menu.add_command(
                label=_slot_label(si),
                foreground=cur_hex,
                activeforeground=cur_hex,
                command=lambda _si=si: _pick_slot(_si),
            )

    def _choose_assoc_slot_color_and_save(self, dd: dict, slot_index: int) -> None:
        cur = self._assoc_slot_color_for_dd(dd, slot_index)
        picked = self._ask_assoc_slot_color(slot_index, cur)
        if not picked:
            return
        self._set_assoc_slot_color_for_dd(dd, slot_index, picked)
        self._persist_templates()

        # IMPORTANT: when this is triggered from a tk.Menu / popup command, immediate
        # widget teardown+rebuild can race the active Tk callback stack on Windows and
        # terminate the app. Defer UI rebuild to the next idle tick.
        def _refresh_after_color_change() -> None:
            try:
                self._render_note_builder()
                self._render_canvas_editor()
                self._apply_builder_to_note()
                self.on_change_callback()
            except Exception:
                # Keep app alive if any stale widget path appears during deferred rebuild.
                pass

        self.after_idle(_refresh_after_color_change)

    def _on_template_dd_quick_switch(self, tid: int, di: int) -> None:
        """Promote a dropdown to top position in Note/Builder for one template only."""
        self._builder_dd_top_by_tid[int(tid)] = int(di)
        repack_cb = self._builder_dd_repack_by_tid.get(int(tid))
        if callable(repack_cb):
            try:
                repack_cb()
                return
            except Exception:
                pass
        # Fallback if callback is stale (e.g., after an unexpected widget teardown).
        self._render_note_builder()

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
        self.canvas_scroll_frame.bind("<Configure>", lambda _e: cv.configure(scrollregion=cv.bbox("all")))
        self._canvas_editor_canvas_window_id = cv.create_window(
            (0, 0), window=self.canvas_scroll_frame, anchor="nw"
        )
        cv.bind("<Configure>", self._on_canvas_editor_canvas_configure)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas_editor_widget = cv

    def _render_canvas_editor(self) -> None:
        for w in self.canvas_scroll_frame.winfo_children():
            w.destroy()

        base_cols = max(1, int(self._TEMPLATE_GRID_COLUMNS))
        cols = 1 if len(self.templates) <= 1 else base_cols
        for col in range(cols):
            self.canvas_scroll_frame.grid_columnconfigure(col, weight=1, uniform="canvas_template_cols")

        for idx, tmpl in enumerate(self.templates):
            self._build_template_editor_card(self.canvas_scroll_frame, tmpl, idx, cols)

        self.canvas_scroll_frame.update_idletasks()
        self.canvas_editor_widget.configure(scrollregion=self.canvas_editor_widget.bbox("all"))
        self.after_idle(self._sync_canvas_editor_embed_width)

    def _build_template_editor_card(self, parent: ttk.Frame, tmpl: dict, idx: int, cols: int | None = None) -> None:
        col_count = max(1, int(cols or self._TEMPLATE_GRID_COLUMNS))
        row_idx = idx // col_count
        col_idx = idx % col_count
        left_gap = 2
        right_gap = self._TEMPLATE_GRID_COLUMN_GAP_PX if col_idx == 0 else 2

        band = tk.Frame(parent, bg=self._template_band_bg(idx))
        band.grid(
            row=row_idx,
            column=col_idx,
            sticky="nsew",
            padx=(left_gap, right_gap),
            pady=(2, self._TEMPLATE_GRID_ROW_GAP_PX),
        )

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
        pe = ttk.Entry(outer, textvariable=prefix_var, width=48)
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

    def _canvas_item_list_editor_shell(self, parent: ttk.Widget, band_title: str, items: list[str]) -> None:
        """Compact list + search editor used twice for Associated Multiple on the template canvas."""
        band = ttk.LabelFrame(parent, text=band_title)
        band.pack(fill="x", padx=6, pady=(0, 10))

        search_var = tk.StringVar(value="")
        visible_to_source: list[int] = list(range(len(items)))

        def _persist_all() -> None:
            self._persist_templates()
            self._render_note_builder()
            self._render_canvas_editor()
            self._apply_builder_to_note()
            self.on_change_callback()

        sf = ttk.Frame(band)
        sf.pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(sf, text="Search:").pack(side="left")
        ttk.Entry(sf, textvariable=search_var).pack(side="left", fill="x", expand=True, padx=(4, 4))

        lf = ttk.Frame(band)
        lf.pack(fill="x", padx=6, pady=4)
        lb = tk.Listbox(lf, height=min(max(len(items), 3), 12), activestyle="dotbox")
        for it in items:
            lb.insert(tk.END, it)
        lb.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")

        new_var = tk.StringVar()

        def _refresh_filter() -> None:
            # The trace below outlives `lb` whenever this canvas-editor section is
            # re-rendered (e.g. _persist_all -> _render_canvas_editor). A late
            # write to `search_var` from the destroyed UI must not raise.
            try:
                if not lb.winfo_exists():
                    return
            except tk.TclError:
                return
            try:
                q = search_var.get()
                new_idxs = self._filter_items_by_prefix(items, q)
                visible_to_source[:] = new_idxs
                lb.delete(0, tk.END)
                for src_idx in new_idxs:
                    lb.insert(tk.END, items[src_idx])
            except tk.TclError:
                return

        search_var.trace_add("write", lambda *_a: _refresh_filter())

        def _src_idx_for_listbox_row(row: int) -> int | None:
            if 0 <= row < len(visible_to_source):
                return visible_to_source[row]
            return None

        def add_item() -> None:
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items.append(txt)
            new_var.set("")
            _persist_all()
            _refresh_filter()

        def update_item() -> None:
            sel = lb.curselection()
            if not sel:
                return
            src_idx = _src_idx_for_listbox_row(sel[0])
            if src_idx is None:
                return
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items[src_idx] = txt
            lb.delete(sel[0])
            lb.insert(sel[0], txt)
            _persist_all()

        def delete_item() -> None:
            sel = lb.curselection()
            if not sel:
                return
            src_idx = _src_idx_for_listbox_row(sel[0])
            if src_idx is None:
                return
            items.pop(src_idx)
            _persist_all()
            _refresh_filter()

        def add_to_list_from_search() -> None:
            txt = (search_var.get() or "").strip()
            if not txt:
                return
            existing_lower = {str(x).strip().lower() for x in items}
            if txt.lower() in existing_lower:
                search_var.set("")
                return
            items.append(txt)
            _persist_all()
            search_var.set("")

        def on_sel(_e=None) -> None:
            sel = lb.curselection()
            if sel:
                src_idx = _src_idx_for_listbox_row(sel[0])
                if src_idx is not None:
                    new_var.set(items[src_idx])

        lb.bind("<<ListboxSelect>>", on_sel)
        self._bind_listbox_mousewheel_local(lb)

        ttk.Button(sf, text="+ Add to List", command=add_to_list_from_search).pack(side="left")

        ent_row = ttk.Frame(band)
        ent_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Entry(ent_row, textvariable=new_var).pack(side="left", fill="x", expand=True)
        btn_row = ttk.Frame(band)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_row, text="Add item", command=add_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Update item", command=update_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Delete item", command=delete_item).pack(side="left", padx=2)

    def _build_dd_format_row(
        self,
        parent: ttk.Frame,
        dd: dict,
        fmt_key: str = "text_format",
        label_text: str = "Output text style:",
    ) -> None:
        """Render Bold / Italic / Underline checkboxes for a dropdown in the Canvas editor.
        fmt_key selects which dict key holds the format flags (e.g. 'assoc_text_format')."""
        fmt = dd.setdefault(fmt_key, {})
        fmt.setdefault("bold", False)
        fmt.setdefault("italic", False)
        fmt.setdefault("underline", False)

        fr = ttk.Frame(parent)
        fr.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(fr, text=label_text).pack(side="left", padx=(0, 8))

        bold_var = tk.BooleanVar(value=bool(fmt.get("bold")))
        ital_var = tk.BooleanVar(value=bool(fmt.get("italic")))
        unde_var = tk.BooleanVar(value=bool(fmt.get("underline")))

        def _save_fmt(_d=dd, _k=fmt_key, _b=bold_var, _i=ital_var, _u=unde_var) -> None:
            _d.setdefault(_k, {})
            _d[_k]["bold"] = _b.get()
            _d[_k]["italic"] = _i.get()
            _d[_k]["underline"] = _u.get()
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()

        ttk.Checkbutton(fr, text="Bold",      variable=bold_var, command=_save_fmt).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(fr, text="Italic",    variable=ital_var, command=_save_fmt).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(fr, text="Underline", variable=unde_var, command=_save_fmt).pack(side="left")

    def _build_dd_bullet_style_row(self, parent: ttk.Frame, dd: dict) -> None:
        """Combobox for bullet icon when output uses bullet lines or associated-multi rows."""
        key_to_label = {k: lab for k, lab in _BULLET_STYLE_CHOICES}
        label_to_key = {lab: k for k, lab in _BULLET_STYLE_CHOICES}
        labels = [lab for _, lab in _BULLET_STYLE_CHOICES]

        fr = ttk.Frame(parent)
        fr.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(fr, text="Bullet icon (for bullet-style lines):").pack(side="left", padx=(0, 8))
        var = tk.StringVar(value=key_to_label[_effective_bullet_style_key(dd)])
        cb = ttk.Combobox(fr, textvariable=var, values=labels, state="readonly", width=46)
        cb.pack(side="left", fill="x", expand=True)

        def _save(_e=None, _d=dd, _v=var):
            lab = (_v.get() or "").strip()
            k = label_to_key.get(lab)
            if k:
                _d["bullet_style"] = k
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

        cb.bind("<<ComboboxSelected>>", _save)

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

        dd.setdefault("builder_button_name", f"DD{di + 1}")
        btn_name_row = ttk.Frame(frame)
        btn_name_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(btn_name_row, text="Note/Builder button name:").pack(side="left")
        btn_name_var = tk.StringVar(value=self._builder_dd_button_name(dd, di))

        def _save_btn_name(_e=None, d=dd, v=btn_name_var) -> None:
            d["builder_button_name"] = (v.get() or "").strip()
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()

        btn_name_entry = ttk.Entry(btn_name_row, textvariable=btn_name_var, width=28)
        btn_name_entry.pack(side="left", padx=6, fill="x", expand=True)
        btn_name_entry.bind("<FocusOut>", _save_btn_name)
        btn_name_entry.bind("<Return>", _save_btn_name)

        if bool(dd.get("associated_per_primary")):
            frame.configure(text=f"Dropdown {di + 1} — Associated per primary")
            dd["associated_multi"] = False
            dd["multi"] = False
            dd.setdefault("assoc_primary_use_bullets", True)
            dd.setdefault("assoc_primary_plain_columns", False)
            dd.setdefault("associate_label", "Secondary options")
            dd.setdefault("associate_items", [])
            dd.setdefault("items", [])
            dd.setdefault("prefix", "")
            self._align_per_primary_associates(dd)

            type_app = ttk.Frame(frame)
            type_app.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(
                type_app,
                text=(
                    "Type: Associated per primary — each primary row has its own secondary item list."
                ),
                wraplength=620,
            ).pack(side="left")

            pref_row_app = ttk.Frame(frame)
            pref_row_app.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(pref_row_app, text="Prefix (optional, before rows):").pack(side="left")
            pref_var_app = tk.StringVar(value=str(dd.get("prefix") or ""))

            def _save_pref_app(_e=None, d=dd, v=pref_var_app) -> None:
                d["prefix"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            pref_entry_app = ttk.Entry(pref_row_app, textvariable=pref_var_app, width=48)
            pref_entry_app.pack(side="left", padx=6, fill="x", expand=True)
            pref_entry_app.bind("<FocusOut>", _save_pref_app)
            pref_entry_app.bind("<Return>", _save_pref_app)

            cap_app = ttk.Frame(frame)
            cap_app.pack(fill="x", padx=6, pady=(4, 2))
            ttk.Label(cap_app, text="Secondary lists caption (shown in builder):").pack(side="left")
            cap_var_app = tk.StringVar(value=str(dd.get("associate_label") or ""))

            def _save_cap_app(_e=None, d=dd, v=cap_var_app) -> None:
                d["associate_label"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            cap_entry_app = ttk.Entry(cap_app, textvariable=cap_var_app, width=48)
            cap_entry_app.pack(side="left", padx=6)
            cap_entry_app.bind("<FocusOut>", _save_cap_app)
            cap_entry_app.bind("<Return>", _save_cap_app)

            lay_app = ttk.Frame(frame)
            lay_app.pack(fill="x", padx=6, pady=(2, 4))
            ttk.Label(lay_app, text="Printed rows:").pack(side="left", padx=(0, 8))
            lay_sv_app = tk.StringVar(value="bullets" if dd.get("assoc_primary_use_bullets", True) else "plain")

            def _save_layout_app(*_a) -> None:
                dd["assoc_primary_use_bullets"] = lay_sv_app.get() == "bullets"
                self._save_and_reload()

            ttk.Radiobutton(
                lay_app,
                text="Bullet lines",
                variable=lay_sv_app,
                value="bullets",
                command=_save_layout_app,
            ).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                lay_app,
                text="No bullet lines",
                variable=lay_sv_app,
                value="plain",
                command=_save_layout_app,
            ).pack(side="left")

            col_app = ttk.Frame(frame)
            col_sv_app = tk.StringVar(
                value="columns" if dd.get("assoc_primary_plain_columns", False) else "inline"
            )

            def _save_col_layout_app(*_a: object) -> None:
                dd["assoc_primary_plain_columns"] = col_sv_app.get() == "columns"
                self._save_and_reload()

            def _toggle_col_layout_app(*_a: object) -> None:
                if lay_sv_app.get() == "plain":
                    col_app.pack(fill="x", padx=6, pady=(0, 4))
                else:
                    col_app.pack_forget()

            ttk.Label(col_app, text="Detail alignment:").pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                col_app,
                text="After label",
                variable=col_sv_app,
                value="inline",
                command=_save_col_layout_app,
            ).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                col_app,
                text="Aligned column",
                variable=col_sv_app,
                value="columns",
                command=_save_col_layout_app,
            ).pack(side="left")
            lay_sv_app.trace_add("write", lambda *_: _toggle_col_layout_app())
            _toggle_col_layout_app()

            self._build_assoc_slot_color_editor(frame, dd)
            self._canvas_item_list_editor_shell(frame, "Primary choices", dd["items"])
            self._build_dd_format_row(
                frame, dd,
                fmt_key="text_format",
                label_text="Primary items text style:",
            )
            prim_items_ref = dd["items"]
            ppa_edit = dd.setdefault("per_primary_associates", [])
            for ix_pp, lbl_pp in enumerate(list(prim_items_ref)):
                while len(ppa_edit) <= ix_pp:
                    ppa_edit.append([])
                self._canvas_item_list_editor_shell(
                    frame,
                    f"Secondary choices for «{lbl_pp}»",
                    ppa_edit[ix_pp],
                )
            self._build_dd_format_row(
                frame, dd,
                fmt_key="assoc_text_format",
                label_text="Secondary items text style:",
            )
            self._build_dd_bullet_style_row(frame, dd)
            ttk.Button(
                frame, text="Remove dropdown", command=lambda t=tmpl, d=di: self._remove_dropdown(t, d)
            ).pack(anchor="e", padx=6, pady=(0, 6))
            return

        if bool(dd.get("associated_multi")):
            frame.configure(text=f"Dropdown {di + 1} — Associated Multiple")
            dd["multi"] = False
            dd.setdefault("associate_label", "Associated detail")
            dd.setdefault("associate_items", [])
            dd.setdefault("items", [])
            dd.setdefault("prefix", "")

            type_row = ttk.Frame(frame)
            type_row.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(type_row, text="Type: Associated Multiple (indented dash lines below the prefix).").pack(side="left")

            def _convert_am_to_plain() -> None:
                if not messagebox.askyesno(
                    "Convert dropdown",
                    "Remove Associated Multiple and convert this dropdown to a plain multi-select?\n\n"
                    "Paired headline/detail structure cannot be preserved automatically.",
                ):
                    return
                dd["associated_multi"] = False
                dd["multi"] = True
                dd.pop("associate_label", None)
                dd.pop("associate_items", None)
                self._save_and_reload()

            ttk.Button(type_row, text="Convert to plain multiple…", command=_convert_am_to_plain).pack(side="right")

            pref_row = ttk.Frame(frame)
            pref_row.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(pref_row, text="Prefix (for this associated dropdown):").pack(side="left")
            pref_var = tk.StringVar(value=str(dd.get("prefix") or ""))

            def _save_pref(_e=None, d=dd, v=pref_var) -> None:
                d["prefix"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            pref_entry = ttk.Entry(pref_row, textvariable=pref_var, width=48)
            pref_entry.pack(side="left", padx=6, fill="x", expand=True)
            pref_entry.bind("<FocusOut>", _save_pref)
            pref_entry.bind("<Return>", _save_pref)

            al_pair = ttk.Frame(frame)
            al_pair.pack(fill="x", padx=6, pady=(4, 2))
            ttk.Label(al_pair, text='Paired list label (“body part …”):').pack(side="left")
            al_var = tk.StringVar(value=str(dd.get("associate_label") or ""))

            def _save_al(_e=None, d=dd, v=al_var) -> None:
                d["associate_label"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            ae = ttk.Entry(al_pair, textvariable=al_var, width=48)
            ae.pack(side="left", padx=6)
            ae.bind("<FocusOut>", _save_al)
            ae.bind("<Return>", _save_al)

            self._build_assoc_slot_color_editor(frame, dd)
            self._canvas_item_list_editor_shell(frame, "Primary (top) choices", dd["items"])
            self._build_dd_format_row(
                frame, dd,
                fmt_key="text_format",
                label_text="Primary items text style:",
            )
            assoc_title = dd.get("associate_label") or "Associated detail"
            self._canvas_item_list_editor_shell(frame, f"Paired choices ({assoc_title})", dd["associate_items"])
            self._build_dd_format_row(
                frame, dd,
                fmt_key="assoc_text_format",
                label_text="Paired items text style:",
            )
            self._build_dd_bullet_style_row(frame, dd)
            ttk.Button(
                frame, text="Remove dropdown", command=lambda t=tmpl, d=di: self._remove_dropdown(t, d)
            ).pack(anchor="e", padx=6, pady=(0, 6))
            return

        if bool(dd.get("multi_full_prefix")):
            dd["multi"] = True
            dd.setdefault("prefix", "")
            frame.configure(text=f"Dropdown {di + 1} — Multiple choice Full/Full")
            type_row_mff = ttk.Frame(frame)
            type_row_mff.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(
                type_row_mff,
                text="Type: Multiple choice Full/Full (optional prefix before selections).",
            ).pack(side="left")

            pref_row_mff = ttk.Frame(frame)
            pref_row_mff.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(pref_row_mff, text="Prefix (for this dropdown):").pack(side="left")
            pref_var_mff = tk.StringVar(value=str(dd.get("prefix") or ""))

            def _save_pref_mff(_e=None, d=dd, v=pref_var_mff) -> None:
                d["prefix"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            pref_entry_mff = ttk.Entry(pref_row_mff, textvariable=pref_var_mff, width=48)
            pref_entry_mff.pack(side="left", padx=6, fill="x", expand=True)
            pref_entry_mff.bind("<FocusOut>", _save_pref_mff)
            pref_entry_mff.bind("<Return>", _save_pref_mff)

        elif bool(dd.get("single_full_prefix")):
            dd["multi"] = False
            dd.setdefault("prefix", "")
            frame.configure(text=f"Dropdown {di + 1} — Single choice Full/Full")
            type_row_sff = ttk.Frame(frame)
            type_row_sff.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(
                type_row_sff,
                text="Type: Single choice Full/Full (optional prefix before selection).",
            ).pack(side="left")

            pref_row_sff = ttk.Frame(frame)
            pref_row_sff.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(pref_row_sff, text="Prefix (for this dropdown):").pack(side="left")
            pref_var_sff = tk.StringVar(value=str(dd.get("prefix") or ""))

            def _save_pref_sff(_e=None, d=dd, v=pref_var_sff) -> None:
                d["prefix"] = v.get()
                self._persist_templates()
                self._render_note_builder()
                self._apply_builder_to_note()
                self.on_change_callback()

            pref_entry_sff = ttk.Entry(pref_row_sff, textvariable=pref_var_sff, width=48)
            pref_entry_sff.pack(side="left", padx=6, fill="x", expand=True)
            pref_entry_sff.bind("<FocusOut>", _save_pref_sff)
            pref_entry_sff.bind("<Return>", _save_pref_sff)

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
            if not d["multi"]:
                d.pop("multi_full_prefix", None)
                d.pop("prefix", None)
            else:
                d.pop("single_full_prefix", None)
                d.pop("prefix", None)
            self._persist_templates()
            self._render_note_builder()
            self._render_canvas_editor()
            self._apply_builder_to_note()
            self.on_change_callback()

        ttk.Button(mode_row, text="Switch single / multiple", command=_flip_mode).pack(side="right")

        self._build_dd_format_row(frame, dd)
        self._build_dd_bullet_style_row(frame, dd)
        ttk.Button(
            frame, text="Remove dropdown", command=lambda t=tmpl, d=di: self._remove_dropdown(t, d)
        ).pack(anchor="e", padx=6)

        dd.setdefault("items", [])
        items = dd["items"]

        # Search row — type to filter the items listbox by case-insensitive starts-with;
        # `+ Add to List` is a quick-add convenience (mirrors the existing `Add item` button).
        search_var = tk.StringVar(value="")
        # Listbox row index -> index into source `items`. Refreshed whenever the filter changes
        # so update_item / delete_item / on_sel always operate on the correct source row.
        visible_to_source: list[int] = list(range(len(items)))

        sf = ttk.Frame(frame)
        sf.pack(fill="x", padx=6, pady=(0, 2))
        ttk.Label(sf, text="Search:").pack(side="left")
        search_entry = ttk.Entry(sf, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=(4, 4))

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

        def _refresh_filter() -> None:
            q = search_var.get()
            new_idxs = self._filter_items_by_prefix(items, q)
            visible_to_source[:] = new_idxs
            lb.delete(0, tk.END)
            for src_idx in new_idxs:
                lb.insert(tk.END, items[src_idx])

        def _on_search_var_changed(*_a) -> None:
            _refresh_filter()

        search_var.trace_add("write", _on_search_var_changed)

        def _src_idx_for_listbox_row(row: int) -> int | None:
            if 0 <= row < len(visible_to_source):
                return visible_to_source[row]
            return None

        def add_item():
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items.append(txt)
            new_var.set("")
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()
            _refresh_filter()

        def update_item():
            sel = lb.curselection()
            if not sel:
                return
            src_idx = _src_idx_for_listbox_row(sel[0])
            if src_idx is None:
                return
            txt = (new_var.get() or "").strip()
            if not txt:
                return
            items[src_idx] = txt
            # Refresh the visible row in place so the user sees the edit without losing the filter.
            lb.delete(sel[0])
            lb.insert(sel[0], txt)
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()

        def delete_item():
            sel = lb.curselection()
            if not sel:
                return
            src_idx = _src_idx_for_listbox_row(sel[0])
            if src_idx is None:
                return
            items.pop(src_idx)
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()
            _refresh_filter()

        def add_to_list_from_search():
            txt = (search_var.get() or "").strip()
            if not txt:
                return
            existing_lower = {str(x).strip().lower() for x in items}
            if txt.lower() in existing_lower:
                # Already in the list — clear filter so the user can see it instead of silently no-oping.
                search_var.set("")
                return
            items.append(txt)
            self._persist_templates()
            self._render_note_builder()
            self._apply_builder_to_note()
            self.on_change_callback()
            # Clear the search to reveal the full list (including the just-added item).
            search_var.set("")

        def on_sel(_e=None):
            sel = lb.curselection()
            if sel:
                src_idx = _src_idx_for_listbox_row(sel[0])
                if src_idx is not None:
                    new_var.set(items[src_idx])

        lb.bind("<<ListboxSelect>>", on_sel)
        self._bind_listbox_mousewheel_local(lb)

        ttk.Button(sf, text="+ Add to List", command=add_to_list_from_search).pack(side="left")

        ent_row = ttk.Frame(frame)
        ent_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Entry(ent_row, textvariable=new_var).pack(side="left", fill="x", expand=True)
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Button(btn_row, text="Add item", command=add_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Update item", command=update_item).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Delete item", command=delete_item).pack(side="left", padx=2)

    def _add_template(self) -> None:
        choice = self._ask_dropdown_creation_mode(
            title="New template — dropdown type",
            prompt=(
                "Choose how selections work for this template’s first dropdown.\n\n"
                "• Single / Multiple behave as usual.\n"
                "• Single choice Full/Full is single-select like Single choice with an optional "
                "prefix line before its selection.\n"
                "• Multiple choice Full/Full is multi-select like Multiple choice, but adds "
                "an optional prefix line before its selections (same prefix behavior as Associated Multiple).\n"
                "• Associated Multiple: the top dropdown is multi-select; each chosen item gains "
                "its own illuminated second list so you pair details (shown as indented dash "
                "lines below the prefix in the note, Live Preview, and PDF).\n"
                "• Associated per primary: each primary choice has its own separate secondary "
                "list (ideal when detail options differ by primary)."
            ),
        )
        if choice is None:
            return
        new_id = max((t["id"] for t in self.templates), default=0) + 1
        if choice == "associated_multiple":
            first_dd = {
                "label": "Primary options",
                "items": ["MRI", "X-Ray", "CT scan"],
                "builder_button_name": "DD1",
                "associated_multi": True,
                "associate_label": "Body region / detail",
                "associate_items": [
                    "Cervical spine",
                    "Thoracic spine",
                    "Lumbar spine",
                    "Head",
                    "Shoulder",
                ],
            }
        elif choice == "associated_per_primary":
            prim_seed = ["MRI", "X-Ray", "CT scan"]
            first_dd = {
                "label": "Primary options",
                "items": prim_seed,
                "builder_button_name": "DD1",
                "associated_per_primary": True,
                "associated_multi": False,
                "multi": False,
                "assoc_primary_use_bullets": True,
                "assoc_primary_plain_columns": False,
                "prefix": "",
                "associate_label": "Secondary options",
                "associate_items": [],
                "per_primary_associates": [
                    ["Cervical spine", "Thoracic spine", "Lumbar spine"],
                    ["Chest", "Abdomen"],
                    ["Head", "Neck"],
                ],
            }
        elif choice == "multiple_full_prefix":
            first_dd = {
                "label": "Option",
                "items": ["First phrase", "Second phrase"],
                "builder_button_name": "DD1",
                "multi": True,
                "multi_full_prefix": True,
                "prefix": "",
            }
        elif choice == "single_full_prefix":
            first_dd = {
                "label": "Option",
                "items": ["First phrase", "Second phrase"],
                "builder_button_name": "DD1",
                "multi": False,
                "single_full_prefix": True,
                "prefix": "",
            }
        else:
            first_dd = {
                "label": "Option",
                "items": ["First phrase", "Second phrase"],
                "builder_button_name": "DD1",
                "multi": choice == "multiple",
            }
        self.templates.append(
            {
                "id": new_id,
                "prefix": f"Template {new_id} prefix ",
                "dropdowns": [first_dd],
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

    def _renumber_templates_and_state(self) -> None:
        """Ensure template IDs are contiguous (1..N) and remap per-template UI state."""
        old_to_new: dict[int, int] = {}
        for new_i, t in enumerate(self.templates, start=1):
            try:
                old_i = int(t.get("id"))
            except Exception:
                old_i = new_i
            old_to_new[old_i] = new_i
            t["id"] = new_i

        old_skip = dict(self._visit_skip_by_tid)
        self._visit_skip_by_tid.clear()
        for old_i, is_skip in old_skip.items():
            new_i = old_to_new.get(int(old_i))
            if new_i is not None:
                self._visit_skip_by_tid[new_i] = bool(is_skip)

        old_top = dict(self._builder_dd_top_by_tid)
        self._builder_dd_top_by_tid.clear()
        for old_i, top_di in old_top.items():
            new_i = old_to_new.get(int(old_i))
            if new_i is not None and isinstance(top_di, int):
                self._builder_dd_top_by_tid[new_i] = top_di

    def _delete_template(self, tmpl: dict) -> None:
        if messagebox.askyesno("Delete template", f"Delete template {tmpl['id']}?"):
            self._visit_skip_by_tid.pop(int(tmpl["id"]), None)
            self._builder_dd_top_by_tid.pop(int(tmpl["id"]), None)
            # Mutate list in place — self.templates aliases section["templates"]; assigning
            # a new list would break persistence (orchestrator saves section dicts).
            self.templates[:] = [t for t in self.templates if t["id"] != tmpl["id"]]
            self._renumber_templates_and_state()
            self._save_and_reload()

    def _move_template(self, idx: int, direction: int) -> None:
        j = idx + direction
        if 0 <= j < len(self.templates):
            self.templates.insert(j, self.templates.pop(idx))
            self._save_and_reload()

    def _add_dropdown(self, tmpl: dict) -> None:
        choice = self._ask_dropdown_creation_mode(
            title="New dropdown — selection type",
            prompt=(
                "Choose selection behavior for this new dropdown.\n\n"
                "Single choice Full/Full is single-select like Single choice with an optional "
                "prefix before its output.\n\n"
                "Multiple choice Full/Full is multi-select like Multiple choice with an optional "
                "prefix before its output.\n\n"
                "Associated Multiple pairs each top-level choice with its own illuminated "
                "second list and prints indented dash lines in notes and PDFs.\n\n"
                "Associated per primary gives each primary its own secondary item list "
                "(detail choices can differ per primary) with optional bullet vs plain rows."
            ),
        )
        if choice is None:
            return
        if choice == "associated_multiple":
            new_dd = {
                "label": "Primary options",
                "items": ["MRI", "X-Ray", "CT scan"],
                "builder_button_name": f"DD{len(tmpl.get('dropdowns') or []) + 1}",
                "associated_multi": True,
                "prefix": str(tmpl.get("prefix") or ""),
                "associate_label": "Body region / detail",
                "associate_items": [
                    "Cervical spine",
                    "Thoracic spine",
                    "Lumbar spine",
                    "Head",
                    "Shoulder",
                ],
            }
        elif choice == "associated_per_primary":
            prim_seed = ["MRI", "X-Ray", "CT scan"]
            new_dd = {
                "label": "Primary options",
                "items": prim_seed,
                "builder_button_name": f"DD{len(tmpl.get('dropdowns') or []) + 1}",
                "associated_per_primary": True,
                "associated_multi": False,
                "multi": False,
                "assoc_primary_use_bullets": True,
                "assoc_primary_plain_columns": False,
                "prefix": "",
                "associate_label": "Secondary options",
                "associate_items": [],
                "per_primary_associates": [
                    ["Cervical spine", "Thoracic spine", "Lumbar spine"],
                    ["Chest", "Abdomen"],
                    ["Head", "Neck"],
                ],
            }
        elif choice == "multiple_full_prefix":
            new_dd = {
                "label": "New dropdown",
                "items": ["A", "B"],
                "builder_button_name": f"DD{len(tmpl.get('dropdowns') or []) + 1}",
                "multi": True,
                "multi_full_prefix": True,
                "prefix": "",
            }
        elif choice == "single_full_prefix":
            new_dd = {
                "label": "New dropdown",
                "items": ["A", "B"],
                "builder_button_name": f"DD{len(tmpl.get('dropdowns') or []) + 1}",
                "multi": False,
                "single_full_prefix": True,
                "prefix": "",
            }
        else:
            new_dd = {
                "label": "New dropdown",
                "items": ["A", "B"],
                "builder_button_name": f"DD{len(tmpl.get('dropdowns') or []) + 1}",
                "multi": choice == "multiple",
            }
        tmpl.setdefault("dropdowns", []).append(new_dd)
        self._save_and_reload()


    def _remove_dropdown(self, tmpl: dict, di: int) -> None:
        dds = tmpl.get("dropdowns") or []
        if len(dds) <= 1:
            messagebox.showwarning("Cannot remove", "Each template needs at least one dropdown.")
            return
        if messagebox.askyesno("Remove dropdown", "Remove this dropdown?"):
            dds.pop(di)
            tid = int(tmpl.get("id") or 0)
            top_di = self._builder_dd_top_by_tid.get(tid)
            if isinstance(top_di, int):
                if top_di == di:
                    self._builder_dd_top_by_tid.pop(tid, None)
                elif top_di > di:
                    self._builder_dd_top_by_tid[tid] = top_di - 1
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

    def set_value(self, value: str, *, builder_state: dict | None = None, rich_text: str | None = None) -> None:
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", value or "")
        if self.note_combo_vars and self._note_builder_meta:
            self._apply_builder_state(builder_state if isinstance(builder_state, dict) else None)
        # Store the saved rich_text so _reapply_builder_text_formatting can restore
        # bold/italic/underline tags when the note was manually edited (builder output diverges).
        self._loaded_rich_text: str = _strip_pdf_fs_grid_comments(rich_text or "")
        # Deferred re-syncs ensure UI matches saved state even after later widget rebuilds
        # (e.g. associated-multiple columns) settle.
        self.after_idle(self._sync_skip_checkbuttons)
        self.after_idle(self._reapply_builder_text_formatting)

    def _apply_rich_text_to_widget(self, rich_text: str) -> None:
        """Parse a saved rich_text XML string and re-apply its bold/italic/underline
        formatting tags to the Tk Text widget.

        Skips silently if the plain-text projection of rich_text does not match
        the widget's current content (prevents stale rich_text from corrupting text).
        """
        import re as _re
        from xml.sax.saxutils import unescape as _xu

        if not rich_text:
            return

        rich_text = _strip_pdf_fs_grid_comments(rich_text)

        # Tokenize into XML tag tokens and text-node tokens.
        _TOKEN = _re.compile(r'(<br\s*/?>|</?\s*[biu]\s*>)', _re.IGNORECASE)
        tokens = _TOKEN.split(rich_text)

        # Build runs: (text, bold, italic, underline)
        runs: list[tuple[str, bool, bool, bool]] = []
        bold = italic = underline = False
        for tok in tokens:
            if not tok:
                continue
            low = tok.strip().lower()
            if _re.match(r'<br\s*/?>', tok, _re.IGNORECASE):
                runs.append(("\n", bold, italic, underline))
            elif low == "<b>":
                bold = True
            elif low == "</b>":
                bold = False
            elif low == "<i>":
                italic = True
            elif low == "</i>":
                italic = False
            elif low == "<u>":
                underline = True
            elif low == "</u>":
                underline = False
            else:
                text = _xu(tok)
                if text:
                    runs.append((text, bold, italic, underline))

        if not runs:
            return

        # Verify the plain-text reconstruction matches the widget content.
        plain_from_rich = "".join(t for t, *_ in runs)
        try:
            current = self.text.get("1.0", "end-1c")
        except tk.TclError:
            return
        if plain_from_rich.strip() != current.strip():
            return  # Rich text is for different content — skip.

        # Re-insert text with formatting tags applied.
        try:
            self.text.delete("1.0", tk.END)
            for text, b, i, u in runs:
                fmt_key = ("B" if b else "") + ("I" if i else "") + ("U" if u else "")
                tag = f"_FMT_{fmt_key}" if fmt_key else None
                if tag:
                    self.text.insert(tk.END, text, tag)
                else:
                    self.text.insert(tk.END, text)
        except tk.TclError:
            pass

    def _reapply_builder_text_formatting(self) -> None:
        """Re-render the note textbox with format tags (bold/italic/underline + bullet styles)
        when the loaded plain text matches what the builder would produce. When the note was
        manually edited (builder output diverges), falls back to the saved rich_text so
        formatting survives app restarts."""
        try:
            runs = self._compose_builder_annotated_runs()
        except Exception:
            return
        if not runs:
            return
        plain = "".join(t for t, _, _ in runs)
        try:
            current = self.text.get("1.0", tk.END)
        except tk.TclError:
            return
        if plain.strip() != current.strip():
            # Builder output diverges (user manually edited).  Restore formatting
            # from the rich_text that was saved to JSON at last save time.
            saved_rich = getattr(self, "_loaded_rich_text", "")
            if saved_rich:
                self._apply_rich_text_to_widget(saved_rich)
            return
        try:
            self.text.delete("1.0", tk.END)
            self._insert_builder_runs(runs)
        except tk.TclError:
            pass

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
