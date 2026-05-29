# schedule_storage.py — Clinic-wide appointment calendar storage.
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from paths import get_data_dir

FILE_APPOINTMENTS = "appointments.json"

APPT_STATUSES = (
    "scheduled",
    "checked_in",
    "in_progress",
    "completed",
    "no_show",
    "cancelled",
)

DEFAULT_DURATION_MIN = 15


def scheduling_dir() -> Path:
    p = get_data_dir() / "scheduling"
    p.mkdir(parents=True, exist_ok=True)
    return p


def appointments_path() -> Path:
    return scheduling_dir() / FILE_APPOINTMENTS


def _default_store() -> dict:
    return {"version": 1, "appointments": []}


def load_appointments() -> dict:
    p = appointments_path()
    if not p.is_file():
        return _default_store()
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return _default_store()
    if not isinstance(raw.get("appointments"), list):
        raw["appointments"] = []
    raw.setdefault("version", 1)
    return raw


def save_appointments(payload: dict) -> None:
    base = _default_store()
    base.update(payload or {})
    if not isinstance(base.get("appointments"), list):
        base["appointments"] = []
    p = appointments_path()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2)
    os.replace(tmp, p)


def new_appointment_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"appt_{stamp}_{uuid.uuid4().hex[:6]}"


def list_appointments(
    *,
    day: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    rows = list(load_appointments().get("appointments") or [])
    if day is not None:
        key = day.isoformat()
        rows = [r for r in rows if (r.get("date") or "") == key]
    elif start is not None or end is not None:
        lo = start or date.min
        hi = end or date.max
        filtered: list[dict] = []
        for r in rows:
            try:
                d = date.fromisoformat(r.get("date") or "")
            except Exception:
                continue
            if lo <= d <= hi:
                filtered.append(r)
        rows = filtered
    rows.sort(key=lambda r: (r.get("date") or "", r.get("start_time") or ""))
    return rows


def find_appointment(appt_id: str) -> dict | None:
    aid = (appt_id or "").strip()
    if not aid:
        return None
    for row in load_appointments().get("appointments") or []:
        if (row.get("appt_id") or "") == aid:
            return dict(row)
    return None


def upsert_appointment(record: dict) -> dict:
    store = load_appointments()
    rows = store.get("appointments") or []
    aid = (record.get("appt_id") or "").strip() or new_appointment_id()
    now = datetime.now().isoformat(timespec="seconds")
    payload = dict(record)
    payload["appt_id"] = aid
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    payload.setdefault("status", "scheduled")
    payload.setdefault("duration_min", DEFAULT_DURATION_MIN)
    payload.setdefault("appt_type", "Chiro Visit")
    payload.setdefault("provider", "")
    payload.setdefault("notes", "")
    payload.setdefault("exam_path", "")

    replaced = False
    for i, row in enumerate(rows):
        if (row.get("appt_id") or "") == aid:
            payload["created_at"] = row.get("created_at") or now
            rows[i] = payload
            replaced = True
            break
    if not replaced:
        rows.append(payload)
    store["appointments"] = rows
    save_appointments(store)
    return payload


def delete_appointment(appt_id: str) -> bool:
    aid = (appt_id or "").strip()
    if not aid:
        return False
    store = load_appointments()
    before = len(store.get("appointments") or [])
    store["appointments"] = [
        r for r in (store.get("appointments") or [])
        if (r.get("appt_id") or "") != aid
    ]
    if len(store["appointments"]) == before:
        return False
    save_appointments(store)
    return True


def upcoming_appointments(*, from_day: date | None = None, days: int = 7) -> list[dict]:
    start = from_day or date.today()
    end = start + timedelta(days=max(1, days) - 1)
    rows = list_appointments(start=start, end=end)
    active = [r for r in rows if (r.get("status") or "") not in ("cancelled",)]
    return active
