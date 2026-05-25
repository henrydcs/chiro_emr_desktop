# service_catalog.py — Shared charge catalog for Plan (Services Provided Today) and Billing.
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from billing_storage import (
    _DEFAULT_FEES,
    charge_master_path,
    load_charge_master,
    load_fee_schedules,
    save_charge_master,
    set_fee_for_cpt,
)

CATEGORIES = ("cmt", "em", "therapy")
NO_CMT_CODE = "0000"
_CATALOG_VERSION = 2

# Display lines matching legacy plan_page.py (short labels after colon).
_PLAN_CMT_SEED: list[tuple[str, str, str, str]] = [
    ("98940", "", "Spinal, 1-2 regions", "cmt"),
    ("98941", "", "Spinal, 3-4 regions", "cmt"),
    ("98942", "", "Spinal, 5 regions", "cmt"),
    ("98943", "", "Extraspinal", "cmt"),
    (NO_CMT_CODE, "", "No CMT Today", "cmt"),
]

_PLAN_EM_SEED: list[tuple[str, str, str, str, str]] = [
    (
        "99202",
        "",
        "Office visit new — straightforward MDM",
        "Office or other outpatient visit for the evaluation and management of a new patient, "
        "which requires a medically appropriate history and/or examination and straightforward medical decision making.",
        "em",
    ),
    (
        "99202",
        "25",
        "E/M re-eval with CMT (99202-25)",
        "A significant, separately identifiable evaluation and management service was performed alongside today's CMT "
        "to conduct a formal re-evaluation of the patient's progress, encompassing a medically appropriate history, "
        "physical examination, and low-level medical decision-making to update the treatment plan.",
        "em",
    ),
    (
        "99203",
        "",
        "Office visit new — low MDM",
        "Office or other outpatient visit for the evaluation and management (E/M) of a new patient, which requires "
        "a medically appropriate history and/or examination and low level of medical decision making (MDM).",
        "em",
    ),
    (
        "99203",
        "25",
        "E/M new patient with CMT (99203-25)",
        "In addition to the CMT and/or physiotherapy performed today, a significant and separately identifiable E/M "
        "service was provided for this new patient, requiring a medically appropriate history, physical examination, "
        "and a moderate level of medical decision-making to establish the clinical baseline and treatment plan.",
        "em",
    ),
    (
        "99212",
        "",
        "Office visit established — straightforward",
        "Office or other outpatient visit for the evaluation and management of an established patient, which requires "
        "a medically appropriate history and/or examination and straightforward medical decision making.",
        "em",
    ),
    (
        "99212",
        "25",
        "E/M re-eval with CMT (99212-25)",
        "A significant, separately identifiable evaluation and management service was performed alongside today's CMT "
        "to conduct a formal re-evaluation of the patient's progress, encompassing a medically appropriate history, "
        "physical examination, and low-level medical decision-making to update the treatment plan.",
        "em",
    ),
    (
        "99213",
        "",
        "Office visit established — low MDM",
        "Office or other outpatient visit for the evaluation and management (E/M) of an established patient, which "
        "requires a medically appropriate history and/or examination and low level of medical decision making (MDM).",
        "em",
    ),
    (
        "99213",
        "25",
        "E/M re-eval with CMT (99213-25)",
        "A significant, separately identifiable evaluation and management service was performed alongside the CMT "
        "and/or physiotherapy to facilitate a re-evaluation of the patient's condition, including a medically "
        "appropriate history and examination with low to moderate medical decision-making to assess clinical improvement.",
        "em",
    ),
    (
        "99214",
        "",
        "Office visit established — moderate MDM",
        "Office or other outpatient visit for the evaluation and management of an established patient with moderate "
        "complexity medical decision making.",
        "em",
    ),
    (
        "99214",
        "25",
        "Office visit moderate with CMT (99214-25)",
        "Office or other outpatient visit for the evaluation and management of an established patient with moderate "
        "complexity, performed as a significant, separately identifiable service with today's CMT.",
        "em",
    ),
]

_EM_LONG_DEFAULTS: dict[tuple[str, str], str] = {
    (cpt, (mod or "").upper()): long
    for cpt, mod, _short, long, _cat in _PLAN_EM_SEED
}

_PLAN_THERAPY_SEED: list[tuple[str, str, str, str]] = [
    ("97012", "", "Mechanical Traction", "therapy"),
    ("97014", "", "Electric Stimulation", "therapy"),
    ("97124", "", "MRT / Vibratory Massage", "therapy"),
    ("97110", "", "Therapeutic Exercise", "therapy"),
    ("97140", "", "Manual Therapy", "therapy"),
    ("97035", "", "Ultrasound", "therapy"),
    ("97010", "", "Hot/Cold Pack", "therapy"),
    ("97112", "", "Neuromuscular Re-ed", "therapy"),
]


def _new_id() -> str:
    return f"cm_{uuid.uuid4().hex[:12]}"


def normalize_category(cat: str) -> str:
    c = (cat or "").strip().lower()
    if c in CATEGORIES:
        return c
    return "therapy"


def format_code(cpt: str, modifier: str = "") -> str:
    cpt = (cpt or "").strip()
    mod = (modifier or "").strip().upper()
    if mod:
        return f"{cpt}-{mod}"
    return cpt


def format_display_line(item: dict) -> str:
    """Same shape saved in plan.services: '98941: Spinal, 3-4 regions' or '99213-25: Label'."""
    code = format_code(str(item.get("cpt") or ""), str(item.get("modifier") or ""))
    label = (item.get("short_description") or item.get("description") or "").strip()
    if not code:
        return label
    return f"{code}: {label}" if label else code


def _fee_key(item: dict) -> str:
    """Billing fee_schedules.json keys by base CPT only."""
    return str(item.get("cpt") or "").strip()


def _validate_cpt(cpt: str) -> None:
    cpt = (cpt or "").strip()
    if cpt == NO_CMT_CODE:
        return
    if len(cpt) != 5 or not cpt.isdigit():
        raise ValueError("CPT must be 5 digits (0000 allowed for No CMT).")


def _merge_item(existing: dict | None, data: dict) -> dict:
    rec = dict(existing or {})
    rec.setdefault("id", _new_id())
    rec["cpt"] = (data.get("cpt") or rec.get("cpt") or "").strip()
    rec["modifier"] = (data.get("modifier") or rec.get("modifier") or "").strip().upper()
    rec["short_description"] = (
        (data.get("short_description") or data.get("description") or rec.get("short_description") or "")
        .strip()
    )
    rec["description"] = rec["short_description"]
    if "long_description" in data:
        rec["long_description"] = (data.get("long_description") or "").strip()
    elif normalize_category(rec.get("category")) == "em":
        rec.setdefault("long_description", "")
    rec["category"] = normalize_category(data.get("category") or rec.get("category"))
    rec["active"] = bool(data.get("active", rec.get("active", True)))
    try:
        rec["sort_order"] = int(data.get("sort_order", rec.get("sort_order", 0)))
    except (TypeError, ValueError):
        rec["sort_order"] = 0
    rec["protected"] = rec["cpt"] == NO_CMT_CODE or bool(rec.get("protected"))
    return rec


def _seed_items() -> list[dict]:
    items: list[dict] = []
    order = 0
    for cpt, mod, label, cat in _PLAN_CMT_SEED:
        order += 1
        items.append(
            {
                "id": _new_id(),
                "cpt": cpt,
                "modifier": mod,
                "short_description": label,
                "description": label,
                "category": cat,
                "active": True,
                "sort_order": order,
                "protected": cpt == NO_CMT_CODE,
            }
        )
    for cpt, mod, label, long_desc, cat in _PLAN_EM_SEED:
        order += 1
        items.append(
            {
                "id": _new_id(),
                "cpt": cpt,
                "modifier": mod,
                "short_description": label,
                "description": label,
                "long_description": long_desc,
                "category": cat,
                "active": True,
                "sort_order": order,
                "protected": False,
            }
        )
    for cpt, mod, label, cat in _PLAN_THERAPY_SEED:
        order += 1
        items.append(
            {
                "id": _new_id(),
                "cpt": cpt,
                "modifier": mod,
                "short_description": label,
                "description": label,
                "category": cat,
                "active": True,
                "sort_order": order,
                "protected": False,
            }
        )
    return items


def ensure_charge_catalog(*, force_reseed: bool = False) -> list[dict]:
    """
    Load catalog; seed from plan defaults if missing or version upgrade.
    Ensures No CMT (0000) row exists.
    """
    p = charge_master_path()
    items: list[dict] = []
    if p.is_file() and not force_reseed:
        try:
            raw = json.loads(p.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                ver = raw.get("version", 1)
                raw_items = raw.get("items")
                if isinstance(raw_items, list) and raw_items:
                    items = [_merge_item(x, x) for x in raw_items if isinstance(x, dict) and x.get("cpt")]
        except Exception:
            items = []

    if not items:
        items = _seed_items()
        _apply_default_fees(items)
        save_charge_master(items)
        _write_catalog_version(items)
        _backfill_em_long_descriptions(items)
        return items

    if not any(str(x.get("cpt")) == NO_CMT_CODE for x in items):
        items.insert(
            0,
            _merge_item(
                None,
                {
                    "cpt": NO_CMT_CODE,
                    "modifier": "",
                    "short_description": "No CMT Today",
                    "category": "cmt",
                    "active": True,
                    "sort_order": 0,
                    "protected": True,
                },
            ),
        )
        save_charge_master(items)

    _backfill_em_long_descriptions(items)
    return items


def _backfill_em_long_descriptions(items: list[dict]) -> None:
    """Fill missing E/M long_description from clinic defaults (one-time merge)."""
    changed = False
    for it in items:
        if normalize_category(it.get("category")) != "em":
            continue
        if (it.get("long_description") or "").strip():
            continue
        key = (str(it.get("cpt") or ""), str(it.get("modifier") or "").upper())
        default = _EM_LONG_DEFAULTS.get(key, "")
        if default:
            it["long_description"] = default
            changed = True
    if changed:
        save_charge_master(items)


def _write_catalog_version(items: list[dict]) -> None:
    p = charge_master_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["version"] = _CATALOG_VERSION
    raw["items"] = items
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    import os

    os.replace(tmp, p)


def _apply_default_fees(items: list[dict]) -> None:
    schedules = load_fee_schedules()
    for item in items:
        cpt = _fee_key(item)
        if not cpt or cpt == NO_CMT_CODE:
            for sch in ("cash", "pi_ucr"):
                schedules.setdefault(sch, {})[cpt] = 0.0
            continue
        for sch in ("cash", "pi_ucr"):
            schedules.setdefault(sch, {})
            if cpt not in schedules[sch]:
                schedules[sch][cpt] = float(_DEFAULT_FEES.get(sch, {}).get(cpt, 0.0))
    from billing_storage import save_fee_schedules

    save_fee_schedules(schedules)


def get_active_items(category: str | None = None) -> list[dict]:
    items = [x for x in ensure_charge_catalog() if x.get("active", True)]
    if category:
        cat = normalize_category(category)
        items = [x for x in items if normalize_category(x.get("category")) == cat]
    items.sort(key=lambda x: (int(x.get("sort_order") or 0), _fee_key(x), x.get("modifier") or ""))
    return items


def get_display_lines(category: str) -> list[str]:
    return [format_display_line(x) for x in get_active_items(category)]


def find_item_by_id(item_id: str) -> dict | None:
    for it in ensure_charge_catalog():
        if it.get("id") == item_id:
            return it
    return None


def catalog_long_description(item: dict | None) -> str:
    if not item:
        return ""
    return (item.get("long_description") or "").strip()


def default_em_long_for_line(display_line: str) -> str:
    it = find_item_by_display_line(display_line)
    return catalog_long_description(it)


def save_em_long_description(
    text: str,
    *,
    display_line: str = "",
    cpt: str = "",
    modifier: str = "",
    short_description: str = "",
    item_id: str | None = None,
) -> str:
    """
    Persist E/M long description to the clinic catalog (shared by Fee Schedule and Services).
    Returns the saved text.
    """
    text = (text or "").strip()
    it: dict | None = None
    if item_id:
        it = find_item_by_id(item_id)
    if not it and (display_line or "").strip():
        it = find_item_by_display_line(display_line)
    if not it and (cpt or "").strip():
        cpt_s = cpt.strip()
        mod_s = (modifier or "").strip().upper()
        for cand in ensure_charge_catalog():
            if (
                str(cand.get("cpt")) == cpt_s
                and str(cand.get("modifier") or "").upper() == mod_s
                and normalize_category(cand.get("category")) == "em"
            ):
                it = cand
                break

    if it:
        rec = upsert_catalog_item(
            cpt=str(it.get("cpt")),
            modifier=str(it.get("modifier") or ""),
            short_description=str(it.get("short_description") or ""),
            category="em",
            long_description=text,
            item_id=str(it.get("id")),
        )
        return catalog_long_description(rec) or text

    cpt_s = (cpt or "").strip()
    if not cpt_s:
        raise ValueError("Enter an E/M CPT code before saving the long description.")
    short = (short_description or "").strip() or cpt_s
    rec = upsert_catalog_item(
        cpt=cpt_s,
        modifier=(modifier or "").strip(),
        short_description=short,
        category="em",
        long_description=text,
    )
    return catalog_long_description(rec) or text


def synced_em_long_for_line(display_line: str, visit_fallback: str = "") -> str:
    """Long text for an E/M line: catalog value, else optional visit fallback."""
    catalog = default_em_long_for_line(display_line)
    if catalog:
        return catalog
    return (visit_fallback or "").strip()


def find_item_by_display_line(line: str) -> dict | None:
    s = (line or "").strip()
    if not s:
        return None
    for it in ensure_charge_catalog():
        if format_display_line(it) == s:
            return it
    return None


def upsert_catalog_item(
    *,
    cpt: str,
    short_description: str,
    category: str,
    modifier: str = "",
    cash: float | None = None,
    pi_ucr: float | None = None,
    long_description: str | None = None,
    item_id: str | None = None,
    active: bool = True,
    sort_order: int | None = None,
) -> dict:
    _validate_cpt(cpt)
    cat = normalize_category(category)
    items = ensure_charge_catalog()
    cpt = cpt.strip()
    mod = (modifier or "").strip().upper()

    target: dict | None = None
    if item_id:
        target = find_item_by_id(item_id)
    if target is None:
        for it in items:
            if (
                str(it.get("cpt")) == cpt
                and str(it.get("modifier") or "").upper() == mod
                and normalize_category(it.get("category")) == cat
            ):
                target = it
                break

    data = {
        "cpt": cpt,
        "modifier": mod,
        "short_description": (short_description or "").strip() or cpt,
        "category": cat,
        "active": active,
    }
    if sort_order is not None:
        data["sort_order"] = sort_order
    if long_description is not None and cat == "em":
        data["long_description"] = long_description

    if target is None:
        data["id"] = _new_id()
        if sort_order is None:
            same_cat = [x for x in items if normalize_category(x.get("category")) == cat]
            data["sort_order"] = (max((int(x.get("sort_order") or 0) for x in same_cat), default=0) + 1)
        rec = _merge_item(None, data)
        items.append(rec)
    else:
        if target.get("protected") and cpt != NO_CMT_CODE:
            raise ValueError("This system entry cannot be modified.")
        rec = _merge_item(target, data)
        for i, it in enumerate(items):
            if it.get("id") == rec["id"]:
                items[i] = rec
                break

    save_charge_master(items)

    fk = _fee_key(rec)
    if fk and fk != NO_CMT_CODE:
        if cash is not None:
            set_fee_for_cpt(fk, cash=cash)
        if pi_ucr is not None:
            set_fee_for_cpt(fk, pi_ucr=pi_ucr)
    elif fk == NO_CMT_CODE:
        set_fee_for_cpt(NO_CMT_CODE, cash=0.0, pi_ucr=0.0)

    return rec


def set_item_active(item_id: str, active: bool) -> None:
    it = find_item_by_id(item_id)
    if not it:
        raise ValueError("Item not found.")
    if it.get("protected"):
        raise ValueError("No CMT (0000) cannot be deactivated.")
    upsert_catalog_item(
        cpt=str(it.get("cpt")),
        short_description=str(it.get("short_description") or ""),
        category=str(it.get("category")),
        modifier=str(it.get("modifier") or ""),
        item_id=item_id,
        active=active,
    )


def category_label(cat: str) -> str:
    return {"cmt": "CMT", "em": "E/M", "therapy": "Therapy"}.get(normalize_category(cat), cat)
