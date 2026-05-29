# appt_types_storage.py — Clinic appointment types (aligned with SOAP exam types).
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from paths import get_data_dir

FILE_APPT_TYPES = "appt_types.json"

# Matches billing_engine.EXAM_TYPES + chiro_app TEMPLATE_CATEGORIES labels.
DEFAULT_APPT_TYPES: list[dict] = [
    {
        "type_id": "initial",
        "label": "Initial",
        "exam_type": "initial",
        "duration_min": 60,
        "color_bg": "#DBEAFE",
        "color_fg": "#1E40AF",
        "active": True,
        "sort_order": 1,
        "builtin": True,
    },
    {
        "type_id": "re_exam",
        "label": "Re-Exam",
        "exam_type": "re_exam",
        "duration_min": 45,
        "color_bg": "#EDE9FE",
        "color_fg": "#6D28D9",
        "active": True,
        "sort_order": 2,
        "builtin": True,
    },
    {
        "type_id": "rof",
        "label": "Review of Findings",
        "exam_type": "rof",
        "duration_min": 30,
        "color_bg": "#E0F2FE",
        "color_fg": "#0369A1",
        "active": True,
        "sort_order": 3,
        "builtin": True,
    },
    {
        "type_id": "chiro",
        "label": "Chiro Visit",
        "exam_type": "chiro",
        "duration_min": 15,
        "color_bg": "#DCFCE7",
        "color_fg": "#15803D",
        "active": True,
        "sort_order": 4,
        "builtin": True,
    },
    {
        "type_id": "therapy_only",
        "label": "Therapy Only",
        "exam_type": "therapy_only",
        "duration_min": 30,
        "color_bg": "#FEF3C7",
        "color_fg": "#92400E",
        "active": True,
        "sort_order": 5,
        "builtin": True,
    },
    {
        "type_id": "final",
        "label": "Final",
        "exam_type": "final",
        "duration_min": 45,
        "color_bg": "#FCE7F3",
        "color_fg": "#BE185D",
        "active": True,
        "sort_order": 6,
        "builtin": True,
    },
]

EXAM_TYPE_LABELS: dict[str, str] = {
    "initial": "Initial",
    "re_exam": "Re-Exam",
    "rof": "Review of Findings",
    "chiro": "Chiro Visit",
    "therapy_only": "Therapy Only",
    "final": "Final",
}


def appt_types_path() -> Path:
    p = get_data_dir() / "scheduling" / FILE_APPT_TYPES
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _default_store() -> dict:
    return {"version": 1, "types": [dict(t) for t in DEFAULT_APPT_TYPES]}


def load_appt_types_store() -> dict:
    p = appt_types_path()
    if not p.is_file():
        store = _default_store()
        save_appt_types_store(store)
        return store
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = _default_store()
    if not isinstance(raw.get("types"), list) or not raw["types"]:
        raw = _default_store()
        save_appt_types_store(raw)
    raw.setdefault("version", 1)
    return raw


def save_appt_types_store(payload: dict) -> None:
    base = _default_store()
    base.update(payload or {})
    types = base.get("types") or []
    if not isinstance(types, list):
        types = [dict(t) for t in DEFAULT_APPT_TYPES]
    base["types"] = types
    p = appt_types_path()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2)
    os.replace(tmp, p)


def list_appt_types(*, active_only: bool = False) -> list[dict]:
    rows = [dict(r) for r in load_appt_types_store().get("types") or []]
    rows.sort(key=lambda r: (int(r.get("sort_order") or 999), (r.get("label") or "").lower()))
    if active_only:
        rows = [r for r in rows if r.get("active", True)]
    return rows


def list_active_appt_type_labels() -> list[str]:
    return [(r.get("label") or "").strip() for r in list_appt_types(active_only=True) if (r.get("label") or "").strip()]


def find_appt_type_by_label(label: str) -> dict | None:
    key = (label or "").strip().lower()
    if not key:
        return None
    for row in list_appt_types():
        if (row.get("label") or "").strip().lower() == key:
            return dict(row)
    return None


def default_duration_for_label(label: str) -> int:
    row = find_appt_type_by_label(label)
    if row:
        try:
            return max(15, int(row.get("duration_min") or 15))
        except Exception:
            pass
    return 15


def style_for_appt_type_label(label: str) -> dict[str, str]:
    row = find_appt_type_by_label(label)
    if row:
        return {
            "bg": row.get("color_bg") or "#DBEAFE",
            "fg": row.get("color_fg") or "#1E40AF",
        }
    return {"bg": "#DBEAFE", "fg": "#1E40AF"}


def upsert_appt_type(record: dict) -> dict:
    store = load_appt_types_store()
    rows = store.get("types") or []
    tid = (record.get("type_id") or "").strip() or f"type_{uuid.uuid4().hex[:8]}"
    payload = dict(record)
    payload["type_id"] = tid
    payload.setdefault("active", True)
    payload.setdefault("builtin", False)
    replaced = False
    for i, row in enumerate(rows):
        if (row.get("type_id") or "") == tid:
            if row.get("builtin"):
                payload["builtin"] = True
                payload.setdefault("exam_type", row.get("exam_type"))
            rows[i] = payload
            replaced = True
            break
    if not replaced:
        if not payload.get("sort_order"):
            payload["sort_order"] = max([int(r.get("sort_order") or 0) for r in rows] + [0]) + 1
        rows.append(payload)
    store["types"] = rows
    save_appt_types_store(store)
    return payload


def reset_appt_types_to_defaults() -> None:
    save_appt_types_store(_default_store())
