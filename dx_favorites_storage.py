# dx_favorites_storage.py — clinic-wide ICD-10 favorites added via Search ICD-10.
from __future__ import annotations

import json
from pathlib import Path

from paths import get_data_dir

_VERSION = 1
_FILENAME = "dx_favorites.json"


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _default_store() -> dict:
    return {"version": _VERSION, "favorites": []}


def _clean(s: str) -> str:
    return (s or "").strip()


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
    favs = raw.get("favorites")
    if not isinstance(favs, list):
        favs = []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in favs:
        if not isinstance(item, dict):
            continue
        label = _clean(item.get("label", ""))
        icd10 = _clean(item.get("icd10", ""))
        if not label and not icd10:
            continue
        if icd10.startswith("-") or label.startswith("-"):
            continue
        key = (icd10 or label).lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"label": label, "icd10": icd10})
    return {"version": _VERSION, "favorites": cleaned}


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def list_favorites() -> list[tuple[str, str]]:
    """Return [(label, icd10), ...] in saved order."""
    out: list[tuple[str, str]] = []
    for item in load_store().get("favorites") or []:
        if isinstance(item, dict):
            out.append((_clean(item.get("label", "")), _clean(item.get("icd10", ""))))
    return out


def add_favorite(label: str, icd10: str) -> bool:
    """
    Append a clinic favorite if not already present (by ICD-10 code when set).
    Returns True when the store changed.
    """
    label = _clean(label)
    icd10 = _clean(icd10)
    if not label and not icd10:
        return False
    if icd10.startswith("-") or label.startswith("-"):
        return False

    store = load_store()
    favs: list[dict[str, str]] = list(store.get("favorites") or [])
    key = (icd10 or label).lower()
    for item in favs:
        existing_code = _clean(item.get("icd10", "")).lower()
        existing_label = _clean(item.get("label", "")).lower()
        if key and key in (existing_code, existing_label):
            return False
        if icd10 and existing_code == icd10.lower():
            return False

    favs.append({"label": label, "icd10": icd10})
    store["favorites"] = favs
    save_store(store)
    return True
