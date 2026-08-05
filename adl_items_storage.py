# adl_items_storage.py — clinic-wide ADL item list (order, labels).
from __future__ import annotations

import json
from pathlib import Path

from paths import get_data_dir

_VERSION = 1
_FILENAME = "adl_items.json"

DEFAULT_ADL_ITEMS = [
    "Sitting tolerance decreased",
    "Standing tolerance decreased",
    "Walking tolerance decreased",
    "Lifting/carrying limited",
    "Bending/twisting limited",
    "Driving tolerance decreased",
    "Sleep disrupted",
    "Work duties limited",
    "Household chores limited",
]


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _clean(label: str) -> str:
    return (label or "").strip()


def _default_store() -> dict:
    return {"version": _VERSION, "items": list(DEFAULT_ADL_ITEMS), "prefix": ""}


def _clean_items(items: list) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        label = _clean(str(raw))
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return cleaned


def load_store() -> dict:
    path = _store_path()
    if not path.exists():
        return _default_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return _default_store()
    if not isinstance(raw, dict):
        return _default_store()
    items = _clean_items(raw.get("items"))
    if not items:
        return _default_store()
    prefix = raw.get("prefix", "")
    if prefix is None:
        prefix = ""
    return {"version": _VERSION, "items": items, "prefix": str(prefix)}


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    items = _clean_items((store or {}).get("items"))
    if not items:
        items = list(DEFAULT_ADL_ITEMS)
    prefix = (store or {}).get("prefix", "")
    if prefix is None:
        prefix = ""
    payload = {"version": _VERSION, "items": items, "prefix": str(prefix)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def list_items() -> list[str]:
    return list(load_store().get("items") or [])


def save_items(items: list[str]) -> None:
    store = load_store()
    store["items"] = _clean_items(items)
    save_store(store)


def get_prefix() -> str:
    return str(load_store().get("prefix") or "")


def set_prefix(prefix: str) -> None:
    store = load_store()
    store["prefix"] = str(prefix) if prefix is not None else ""
    save_store(store)


def add_item(label: str) -> bool:
    label = _clean(label)
    if not label:
        return False
    items = list_items()
    if any(existing.lower() == label.lower() for existing in items):
        return False
    items.append(label)
    save_items(items)
    return True


def rename_item(old_label: str, new_label: str) -> bool:
    old_label = _clean(old_label)
    new_label = _clean(new_label)
    if not old_label or not new_label:
        return False
    if old_label.lower() == new_label.lower():
        return True
    items = list_items()
    if not any(x.lower() == old_label.lower() for x in items):
        return False
    if any(x.lower() == new_label.lower() for x in items):
        return False
    out = [new_label if x.lower() == old_label.lower() else x for x in items]
    save_items(out)
    return True


def delete_item(label: str) -> bool:
    label = _clean(label)
    if not label:
        return False
    items = list_items()
    out = [x for x in items if x.lower() != label.lower()]
    if len(out) == len(items):
        return False
    save_items(out)
    return True


def move_item(label: str, delta: int) -> bool:
    label = _clean(label)
    if not label or delta not in (-1, 1):
        return False
    items = list_items()
    idx = next((i for i, x in enumerate(items) if x.lower() == label.lower()), -1)
    if idx < 0:
        return False
    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(items):
        return False
    items[idx], items[new_idx] = items[new_idx], items[idx]
    save_items(items)
    return True
