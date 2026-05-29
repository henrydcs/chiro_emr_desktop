# providers_storage.py — Clinic provider directory.
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from config import PROVIDER_NAME
from paths import get_data_dir

FILE_PROVIDERS = "providers.json"


def providers_path() -> Path:
    p = get_data_dir() / "clinic" / FILE_PROVIDERS
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _seed_providers() -> list[dict]:
    name = (PROVIDER_NAME or "").strip()
    if not name:
        return []
    return [{
        "provider_id": "provider_default",
        "display_name": name,
        "credentials": "",
        "npi": "",
        "email": "",
        "phone": "",
        "active": True,
        "is_default": True,
        "sort_order": 1,
    }]


def _default_store() -> dict:
    return {"version": 1, "providers": _seed_providers()}


def load_providers_store() -> dict:
    p = providers_path()
    if not p.is_file():
        store = _default_store()
        save_providers_store(store)
        return store
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = _default_store()
    if not isinstance(raw.get("providers"), list):
        raw["providers"] = _seed_providers()
    raw.setdefault("version", 1)
    return raw


def save_providers_store(payload: dict) -> None:
    base = _default_store()
    base.update(payload or {})
    providers = base.get("providers") or []
    if not isinstance(providers, list):
        providers = []
    base["providers"] = providers
    p = providers_path()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2)
    os.replace(tmp, p)


def list_providers(*, active_only: bool = False) -> list[dict]:
    rows = [dict(r) for r in load_providers_store().get("providers") or []]
    rows.sort(key=lambda r: (int(r.get("sort_order") or 999), (r.get("display_name") or "").lower()))
    if active_only:
        rows = [r for r in rows if r.get("active", True)]
    return rows


def provider_label(row: dict) -> str:
    name = (row.get("display_name") or "").strip()
    cred = (row.get("credentials") or "").strip()
    if cred:
        return f"{name}, {cred}"
    return name


def list_active_provider_labels() -> list[str]:
    out: list[str] = []
    for row in list_providers(active_only=True):
        label = provider_label(row)
        if label:
            out.append(label)
    return out


def find_provider(provider_id: str) -> dict | None:
    pid = (provider_id or "").strip()
    if not pid:
        return None
    for row in list_providers():
        if (row.get("provider_id") or "") == pid:
            return dict(row)
    return None


def default_provider_label() -> str:
    for row in list_providers(active_only=True):
        if row.get("is_default"):
            return provider_label(row)
    active = list_active_provider_labels()
    return active[0] if active else ""


def new_provider_id() -> str:
    return f"provider_{uuid.uuid4().hex[:8]}"


def upsert_provider(record: dict) -> dict:
    store = load_providers_store()
    rows = store.get("providers") or []
    pid = (record.get("provider_id") or "").strip() or new_provider_id()
    payload = dict(record)
    payload["provider_id"] = pid
    payload.setdefault("active", True)
    payload.setdefault("is_default", False)
    payload.setdefault("credentials", "")
    payload.setdefault("npi", "")
    payload.setdefault("email", "")
    payload.setdefault("phone", "")

    replaced = False
    for i, row in enumerate(rows):
        if (row.get("provider_id") or "") == pid:
            rows[i] = payload
            replaced = True
            break
    if not replaced:
        if not payload.get("sort_order"):
            payload["sort_order"] = max([int(r.get("sort_order") or 0) for r in rows] + [0]) + 1
        rows.append(payload)

    if payload.get("is_default"):
        for row in rows:
            row["is_default"] = (row.get("provider_id") or "") == pid
    elif rows and not any(r.get("is_default") for r in rows):
        rows[0]["is_default"] = True

    store["providers"] = rows
    save_providers_store(store)
    return payload


def delete_provider(provider_id: str) -> bool:
    pid = (provider_id or "").strip()
    if not pid:
        return False
    store = load_providers_store()
    before = len(store.get("providers") or [])
    rows = [r for r in (store.get("providers") or []) if (r.get("provider_id") or "") != pid]
    if len(rows) == before:
        return False
    if rows and not any(r.get("is_default") for r in rows):
        rows[0]["is_default"] = True
    store["providers"] = rows
    save_providers_store(store)
    return True
