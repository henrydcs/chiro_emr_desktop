# dx_favorites_storage.py — clinic-wide ICD-10 favorite blocks for Search Dx Favorites.
from __future__ import annotations

import json
import uuid
from pathlib import Path

from paths import get_data_dir

_VERSION = 2
_FILENAME = "dx_favorites.json"
_DEFAULT_BLOCK_NAME = "General Favorites"


def _store_path() -> Path:
    return get_data_dir() / _FILENAME


def _clean(s: str) -> str:
    return (s or "").strip()


def _new_block_id() -> str:
    return uuid.uuid4().hex[:10]


def _default_store() -> dict:
    return {"version": _VERSION, "blocks": []}


def _normalize_favorite_item(label: str, icd10: str) -> dict[str, str] | None:
    label = _clean(label)
    icd10 = _clean(icd10)
    if not label and not icd10:
        return None
    if icd10.startswith("-") or label.startswith("-"):
        return None
    return {"label": label, "icd10": icd10}


def _clean_favorites_list(favs: list) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in favs or []:
        if not isinstance(item, dict):
            continue
        norm = _normalize_favorite_item(item.get("label", ""), item.get("icd10", ""))
        if norm is None:
            continue
        key = (norm["icd10"] or norm["label"]).lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(norm)
    return cleaned


def _clean_block(block: dict) -> dict | None:
    if not isinstance(block, dict):
        return None
    block_id = _clean(block.get("id", "")) or _new_block_id()
    name = _clean(block.get("name", "")) or "Favorites"
    favs = _clean_favorites_list(block.get("favorites") or [])
    return {"id": block_id, "name": name, "favorites": favs}


def _migrate_store(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return _default_store()

    if raw.get("version") == _VERSION and isinstance(raw.get("blocks"), list):
        blocks = []
        for b in raw.get("blocks") or []:
            cleaned = _clean_block(b)
            if cleaned is not None:
                blocks.append(cleaned)
        return {"version": _VERSION, "blocks": blocks}

    # v1: flat favorites list
    favs = raw.get("favorites") if isinstance(raw.get("favorites"), list) else []
    cleaned = _clean_favorites_list(favs)
    if not cleaned:
        return _default_store()
    return {
        "version": _VERSION,
        "blocks": [
            {
                "id": _new_block_id(),
                "name": "Clinic Favorites",
                "favorites": cleaned,
            }
        ],
    }


def load_store() -> dict:
    path = _store_path()
    if not path.exists():
        return _default_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return _default_store()
    return _migrate_store(raw)


def save_store(store: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for b in store.get("blocks") or []:
        cleaned = _clean_block(b)
        if cleaned is not None:
            blocks.append(cleaned)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": _VERSION, "blocks": blocks}, f, indent=2)


def list_blocks() -> list[dict]:
    """Return [{"id", "name", "favorites": [(label, icd10), ...]}, ...]."""
    out: list[dict] = []
    for block in load_store().get("blocks") or []:
        if not isinstance(block, dict):
            continue
        cleaned = _clean_block(block)
        if cleaned is None:
            continue
        favs = [
            (_clean(f.get("label", "")), _clean(f.get("icd10", "")))
            for f in cleaned.get("favorites") or []
            if isinstance(f, dict)
        ]
        out.append(
            {
                "id": cleaned["id"],
                "name": cleaned["name"],
                "favorites": favs,
            }
        )
    return out


def save_blocks(blocks: list[dict]) -> None:
    payload = {"version": _VERSION, "blocks": []}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        cleaned = _clean_block(
            {
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "favorites": [
                    {"label": lbl, "icd10": code}
                    for lbl, code in (block.get("favorites") or [])
                ],
            }
        )
        if cleaned is not None:
            payload["blocks"].append(cleaned)
    save_store(payload)


def list_favorites() -> list[tuple[str, str]]:
    """All favorites from every block (deduped by ICD, block order preserved)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for block in list_blocks():
        for label, code in block.get("favorites") or []:
            key = (code or label).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append((label, code))
    return out


def favorite_exists(icd10: str, *, label: str = "") -> bool:
    code_key = _clean(icd10).lower()
    label_key = _clean(label).lower()
    for lbl, code in list_favorites():
        if code_key and code.lower() == code_key:
            return True
        if not code_key and label_key and lbl.lower() == label_key:
            return True
    return False


def _ensure_default_block(store: dict) -> dict:
    blocks = list(store.get("blocks") or [])
    if blocks:
        return store
    blocks.append(
        {
            "id": _new_block_id(),
            "name": _DEFAULT_BLOCK_NAME,
            "favorites": [],
        }
    )
    store["blocks"] = blocks
    return store


def add_favorite(label: str, icd10: str, *, block_id: str | None = None) -> bool:
    """
    Add a favorite to a block (default: first block, creating General Favorites if needed).
    Also makes it available in all Dx dropdowns via list_favorites().
    """
    label = _clean(label)
    icd10 = _clean(icd10)
    item = _normalize_favorite_item(label, icd10)
    if item is None:
        return False
    if favorite_exists(icd10, label=label):
        return False

    store = _ensure_default_block(load_store())
    blocks = list(store.get("blocks") or [])
    target_id = block_id
    if not target_id and blocks:
        target_id = blocks[0].get("id")
    if not target_id:
        return False

    changed = False
    for block in blocks:
        if _clean(block.get("id", "")) != _clean(target_id):
            continue
        favs = list(block.get("favorites") or [])
        favs.append(item)
        block["favorites"] = favs
        changed = True
        break

    if not changed:
        return False
    store["blocks"] = blocks
    save_store(store)
    return True


def create_block(name: str) -> dict:
    store = load_store()
    blocks = list(store.get("blocks") or [])
    block = {"id": _new_block_id(), "name": _clean(name) or "Favorites", "favorites": []}
    blocks.append(block)
    store["blocks"] = blocks
    save_store(store)
    return block


def rename_block(block_id: str, new_name: str) -> bool:
    name = _clean(new_name)
    if not name:
        return False
    store = load_store()
    changed = False
    for block in store.get("blocks") or []:
        if _clean(block.get("id", "")) == _clean(block_id):
            block["name"] = name
            changed = True
            break
    if not changed:
        return False
    save_store(store)
    return True


def delete_block(block_id: str) -> bool:
    store = load_store()
    blocks = list(store.get("blocks") or [])
    new_blocks = [b for b in blocks if _clean(b.get("id", "")) != _clean(block_id)]
    if len(new_blocks) == len(blocks):
        return False
    store["blocks"] = new_blocks
    save_store(store)
    return True
