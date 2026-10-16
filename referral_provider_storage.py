# referral_provider_storage.py — clinic-wide referral provider dropdown choices.
from __future__ import annotations

import json
from pathlib import Path

from paths import get_data_dir

_VERSION = 1
_FILENAME = "referral_provider_choices.json"

DEFAULT_PROVIDERS: list[str] = [
    "Orthopedist",
    "Neurologist",
    "Pain Management",
    "Primary Care",
    "Physical Therapy",
    "Radiology",
    "Chiropractic Specialty",
    "Psychology",
    "None at this time",
]


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _default_store() -> dict:
    return {"version": _VERSION, "custom": []}


def _clean_labels(items: list) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


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
    return {"version": _VERSION, "custom": _clean_labels(raw.get("custom"))}


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"version": _VERSION, "custom": _clean_labels(store.get("custom"))},
            f,
            indent=2,
        )


def all_referral_provider_choices() -> list[str]:
    custom = load_store().get("custom") or []
    merged: list[str] = []
    seen: set[str] = set()
    for item in ["(select)", *DEFAULT_PROVIDERS, *sorted(custom, key=str.lower)]:
        key = item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def add_custom_referral_provider(label: str) -> bool:
    s = (label or "").strip()
    if not s or s.lower() == "(select)":
        return False
    store = load_store()
    existing = {x.strip().lower() for x in DEFAULT_PROVIDERS} | {
        x.strip().lower() for x in (store.get("custom") or [])
    }
    if s.lower() in existing:
        return False
    custom = list(store.get("custom") or [])
    custom.append(s)
    store["custom"] = custom
    save_store(store)
    return True
