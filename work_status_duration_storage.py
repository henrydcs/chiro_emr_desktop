# work_status_duration_storage.py — clinic-wide duration choices for work status letters.
from __future__ import annotations

import json
from pathlib import Path

from paths import get_data_dir

_VERSION = 1
_FILENAME = "work_status_duration_choices.json"

DEFAULT_DURATIONS: list[str] = [
    "1 day",
    "2 days",
    "3 days",
    "5 days",
    "7 days",
    "1 week",
    "2 weeks",
    "3 weeks",
    "4 weeks",
    "1 month",
    "2 months",
    "3 months",
]


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _default_store() -> dict:
    return {"version": _VERSION, "custom": []}


def load_store() -> dict:
    path = _store_path()
    if not path.exists():
        return _default_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return _default_store()
    if not isinstance(raw, dict):
        return _default_store()
    custom = raw.get("custom")
    if not isinstance(custom, list):
        custom = []
    cleaned = []
    seen: set[str] = set()
    for item in custom:
        if not isinstance(item, str):
            continue
        s = item.strip()
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return {"version": _VERSION, "custom": cleaned}


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def list_custom_durations() -> list[str]:
    return list(load_store().get("custom") or [])


def add_custom_duration(label: str) -> bool:
    s = (label or "").strip()
    if not s:
        return False
    store = load_store()
    custom: list[str] = list(store.get("custom") or [])
    existing = {x.strip().lower() for x in DEFAULT_DURATIONS} | {x.strip().lower() for x in custom}
    if s.lower() in existing:
        return False
    custom.append(s)
    store["custom"] = custom
    save_store(store)
    return True


def all_duration_choices() -> list[str]:
    """Dropdown values: (select) + built-ins + saved custom (sorted)."""
    custom = list_custom_durations()
    merged: list[str] = []
    seen: set[str] = set()
    for item in ["(select)", *DEFAULT_DURATIONS, *sorted(custom, key=str.lower)]:
        key = item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
