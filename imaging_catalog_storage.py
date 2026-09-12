# imaging_catalog_storage.py — clinic-wide imaging modality & body-part dropdown choices.
from __future__ import annotations

import json
from pathlib import Path

from paths import get_data_dir

_VERSION = 1
_FILENAME = "imaging_catalog_choices.json"

DEFAULT_MODALITIES: list[str] = ["X-ray", "MRI", "CT", "Ultrasound"]

DEFAULT_BODY_PARTS: list[str] = [
    "Cervical Spine",
    "Thoracic Spine",
    "Lumbar Spine",
    "Right Shoulder",
    "Left Shoulder",
    "B/L Shoulders",
    "Right Elbow",
    "Left Elbow",
    "B/L Elbows",
    "Right Wrist",
    "Left Wrist",
    "B/L Wrists",
    "Right Hip",
    "Left Hip",
    "B/L Hips",
    "Right Knee",
    "Left Knee",
    "B/L Knees",
    "Right Ankle",
    "Left Ankle",
    "B/L Ankles",
]


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _default_store() -> dict:
    return {"version": _VERSION, "custom_modalities": [], "custom_body_parts": []}


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
    return {
        "version": _VERSION,
        "custom_modalities": _clean_labels(raw.get("custom_modalities")),
        "custom_body_parts": _clean_labels(raw.get("custom_body_parts")),
    }


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _VERSION,
        "custom_modalities": _clean_labels(store.get("custom_modalities")),
        "custom_body_parts": _clean_labels(store.get("custom_body_parts")),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _merge_choices(defaults: list[str], custom: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in ["(select)", *defaults, *sorted(custom, key=str.lower)]:
        key = item.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def all_modality_choices() -> list[str]:
    store = load_store()
    return _merge_choices(DEFAULT_MODALITIES, store.get("custom_modalities") or [])


def all_body_part_choices() -> list[str]:
    store = load_store()
    return _merge_choices(DEFAULT_BODY_PARTS, store.get("custom_body_parts") or [])


def add_custom_modality(label: str) -> bool:
    s = (label or "").strip()
    if not s or s.lower() == "(select)":
        return False
    store = load_store()
    existing = {x.strip().lower() for x in DEFAULT_MODALITIES} | {
        x.strip().lower() for x in (store.get("custom_modalities") or [])
    }
    if s.lower() in existing:
        return False
    custom = list(store.get("custom_modalities") or [])
    custom.append(s)
    store["custom_modalities"] = custom
    save_store(store)
    return True


def add_custom_body_part(label: str) -> bool:
    s = (label or "").strip()
    if not s or s.lower() == "(select)":
        return False
    store = load_store()
    existing = {x.strip().lower() for x in DEFAULT_BODY_PARTS} | {
        x.strip().lower() for x in (store.get("custom_body_parts") or [])
    }
    if s.lower() in existing:
        return False
    custom = list(store.get("custom_body_parts") or [])
    custom.append(s)
    store["custom_body_parts"] = custom
    save_store(store)
    return True
