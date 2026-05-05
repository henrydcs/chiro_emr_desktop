# attorney_data.py
"""
Centralized data layer for the Attorney Demographics + Referrals subsystem.

Stores everything in two places:
  1) Clinic-wide attorney directory + referral event log:
        <DATA_DIR>/attorneys.json
  2) Per-patient referral state (which attorney(s) the patient is currently linked
     to, and in which direction):
        <PATIENT_ROOT>/patient_info/referral.json

Referral directions
-------------------
- "from_dol":       Patient was referred to our clinic by Doctors on Liens (and we
                    record which attorney is handling the case under DoL).
- "from_attorney":  Patient was referred to our clinic directly by an attorney
                    (NOT through DoL).
- "to_attorney":    Patient came to us first; we referred the patient out to an
                    attorney.

Each (patient_id, direction) is single-valued: a patient's "from_dol" attorney,
"from_attorney" attorney, and "to_attorney" attorney are each one attorney record
at a time. Toggling a button off removes the link AND the corresponding referral
event from the log.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import get_data_dir
from config import PATIENT_SUBDIR_INFO


REFERRAL_DIRECTIONS = ("from_dol", "from_attorney", "to_attorney")

DIRECTION_LABELS = {
    "from_dol": "Doctors on Liens",
    "from_attorney": "Attorney Referred Patient",
    "to_attorney": "We Referred to Attorney",
}

_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def attorneys_db_path() -> Path:
    """Clinic-wide attorney database file path."""
    return get_data_dir() / "attorneys.json"


def patient_referral_path(patient_root: str | os.PathLike) -> Path:
    """Per-patient referral state file path."""
    return Path(patient_root) / PATIENT_SUBDIR_INFO / "referral.json"


# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------
def _default_db() -> dict:
    return {
        "version": 1,
        "attorneys": [],
        "referrals": [],
    }


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Load / save (clinic-wide DB)
# ---------------------------------------------------------------------------
def load_db() -> dict:
    p = attorneys_db_path()
    if not p.exists():
        return _default_db()
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f) or {}
    except Exception:
        return _default_db()

    if not isinstance(obj, dict):
        return _default_db()

    obj.setdefault("version", 1)
    if not isinstance(obj.get("attorneys"), list):
        obj["attorneys"] = []
    if not isinstance(obj.get("referrals"), list):
        obj["referrals"] = []
    return obj


def save_db(db: dict) -> None:
    p = attorneys_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Attorney CRUD
# ---------------------------------------------------------------------------
ATTORNEY_FIELDS = (
    "firm_name",
    "attorney_name",
    "contact_name",
    "paralegal_name",
    "case_manager",
    "address1",
    "address2",
    "city",
    "state",
    "zip",
    "phone",
    "fax",
    "email",
    "website",
    "notes",
)


def _blank_attorney() -> dict:
    rec = {f: "" for f in ATTORNEY_FIELDS}
    rec["id"] = ""
    rec["created_at"] = ""
    rec["updated_at"] = ""
    return rec


def list_attorneys() -> list[dict]:
    return list(load_db().get("attorneys", []))


def list_attorneys_alphabetical(*, by: str = "firm_name") -> list[dict]:
    items = list_attorneys()
    items.sort(
        key=lambda a: (
            (a.get(by) or a.get("attorney_name") or a.get("firm_name") or "")
            .strip()
            .lower()
        )
    )
    return items


def find_attorney(attorney_id: str) -> dict | None:
    if not attorney_id:
        return None
    for a in list_attorneys():
        if a.get("id") == attorney_id:
            return a
    return None


def attorney_display_label(rec: dict | None) -> str:
    if not rec:
        return ""
    firm = (rec.get("firm_name") or "").strip()
    name = (rec.get("attorney_name") or "").strip()
    if firm and name:
        return f"{firm} — {name}"
    return firm or name or "(unnamed attorney)"


def add_attorney(data: dict) -> dict:
    with _LOCK:
        db = load_db()
        rec = _blank_attorney()
        for f in ATTORNEY_FIELDS:
            if f in data:
                rec[f] = (data.get(f) or "").strip()
        rec["id"] = _new_id()
        rec["created_at"] = _now_iso()
        rec["updated_at"] = rec["created_at"]
        db["attorneys"].append(rec)
        save_db(db)
        return rec


def update_attorney(attorney_id: str, data: dict) -> dict | None:
    with _LOCK:
        db = load_db()
        for rec in db.get("attorneys", []):
            if rec.get("id") == attorney_id:
                for f in ATTORNEY_FIELDS:
                    if f in data:
                        rec[f] = (data.get(f) or "").strip()
                rec["updated_at"] = _now_iso()
                save_db(db)
                return rec
    return None


def delete_attorney(attorney_id: str) -> bool:
    """Delete an attorney and all referrals that point to it."""
    with _LOCK:
        db = load_db()
        before = len(db.get("attorneys", []))
        db["attorneys"] = [a for a in db.get("attorneys", []) if a.get("id") != attorney_id]
        db["referrals"] = [r for r in db.get("referrals", []) if r.get("attorney_id") != attorney_id]
        changed = len(db["attorneys"]) != before
        if changed:
            save_db(db)
        return changed


# ---------------------------------------------------------------------------
# Referral event log
# ---------------------------------------------------------------------------
def _normalize_direction(direction: str) -> str:
    d = (direction or "").strip().lower()
    if d not in REFERRAL_DIRECTIONS:
        raise ValueError(f"invalid referral direction: {direction!r}")
    return d


def add_referral(
    *,
    patient_id: str,
    patient_name: str,
    attorney_id: str,
    direction: str,
    exam_label: str = "",
    notes: str = "",
    timestamp: str | None = None,
) -> dict:
    """Append a new referral event. Does not de-duplicate."""
    direction = _normalize_direction(direction)
    with _LOCK:
        db = load_db()
        rec = {
            "id": _new_id(),
            "patient_id": (patient_id or "").strip(),
            "patient_name": (patient_name or "").strip(),
            "attorney_id": (attorney_id or "").strip(),
            "direction": direction,
            "exam_label": (exam_label or "").strip(),
            "notes": (notes or "").strip(),
            "timestamp": timestamp or _now_iso(),
        }
        db["referrals"].append(rec)
        save_db(db)
        return rec


def remove_referrals_for_patient(patient_id: str, direction: str) -> int:
    """Remove all referral events matching (patient_id, direction). Returns count removed."""
    direction = _normalize_direction(direction)
    pid = (patient_id or "").strip()
    if not pid:
        return 0
    with _LOCK:
        db = load_db()
        kept = [
            r for r in db.get("referrals", [])
            if not (r.get("patient_id") == pid and r.get("direction") == direction)
        ]
        removed = len(db.get("referrals", [])) - len(kept)
        if removed:
            db["referrals"] = kept
            save_db(db)
        return removed


def list_referrals(
    *,
    direction: str | None = None,
    attorney_id: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> list[dict]:
    """Return referrals filtered by any combination of criteria."""
    db = load_db()
    out: list[dict] = []
    for r in db.get("referrals", []):
        if direction and r.get("direction") != direction:
            continue
        if attorney_id and r.get("attorney_id") != attorney_id:
            continue
        if year is not None or month is not None:
            ts = (r.get("timestamp") or "").strip()
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                continue
            if year is not None and dt.year != year:
                continue
            if month is not None and dt.month != month:
                continue
        out.append(r)
    return out


def count_referrals_by_attorney(
    *,
    direction: str,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, int]:
    """Map attorney_id -> count for the given direction (and optional period)."""
    counts: dict[str, int] = {}
    for r in list_referrals(direction=_normalize_direction(direction), year=year, month=month):
        aid = r.get("attorney_id") or ""
        counts[aid] = counts.get(aid, 0) + 1
    return counts


def total_count(
    *,
    direction: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> int:
    if direction is None:
        return sum(
            len(list_referrals(direction=d, year=year, month=month))
            for d in REFERRAL_DIRECTIONS
        )
    return len(list_referrals(direction=_normalize_direction(direction), year=year, month=month))


# ---------------------------------------------------------------------------
# Per-patient referral state
# ---------------------------------------------------------------------------
def _default_patient_state() -> dict:
    return {d: {"attorney_id": "", "set_at": ""} for d in REFERRAL_DIRECTIONS}


def load_patient_referral_state(patient_root: str | os.PathLike | None) -> dict:
    if not patient_root:
        return _default_patient_state()
    p = patient_referral_path(patient_root)
    if not p.exists():
        return _default_patient_state()
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f) or {}
    except Exception:
        return _default_patient_state()
    out = _default_patient_state()
    if isinstance(obj, dict):
        for d in REFERRAL_DIRECTIONS:
            v = obj.get(d)
            if isinstance(v, dict):
                out[d] = {
                    "attorney_id": (v.get("attorney_id") or "").strip(),
                    "set_at": (v.get("set_at") or "").strip(),
                }
    return out


def save_patient_referral_state(patient_root: str | os.PathLike, state: dict) -> None:
    p = patient_referral_path(patient_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def set_patient_referral(
    *,
    patient_root: str | os.PathLike,
    patient_id: str,
    patient_name: str,
    direction: str,
    attorney_id: str,
    exam_label: str = "",
) -> dict:
    """Set the patient's attorney for the given direction.

    - Removes any prior referral event for (patient_id, direction).
    - Adds a fresh referral event with current timestamp.
    - Updates the per-patient referral state file.

    Returns the updated patient state dict.
    """
    direction = _normalize_direction(direction)
    state = load_patient_referral_state(patient_root)

    remove_referrals_for_patient(patient_id, direction)
    rec = add_referral(
        patient_id=patient_id,
        patient_name=patient_name,
        attorney_id=attorney_id,
        direction=direction,
        exam_label=exam_label,
    )

    state[direction] = {
        "attorney_id": attorney_id,
        "set_at": rec["timestamp"],
    }
    save_patient_referral_state(patient_root, state)
    return state


def clear_patient_referral(
    *,
    patient_root: str | os.PathLike,
    patient_id: str,
    direction: str,
) -> dict:
    """Toggle off: remove the patient's attorney for the given direction
    and delete matching referral events from the log."""
    direction = _normalize_direction(direction)
    state = load_patient_referral_state(patient_root)
    remove_referrals_for_patient(patient_id, direction)
    state[direction] = {"attorney_id": "", "set_at": ""}
    save_patient_referral_state(patient_root, state)
    return state


# ---------------------------------------------------------------------------
# Aggregates for the Stats tabs
# ---------------------------------------------------------------------------
def _ymd(ts: str) -> tuple[int, int, int] | None:
    try:
        dt = datetime.fromisoformat(ts)
        return (dt.year, dt.month, dt.day)
    except Exception:
        return None


def referrals_table_for_period(
    *,
    direction: str,
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    """Rows for a Doctors-on-Liens-style table for the given month/year.

    Each row contains: index, patient_name, attorney_label, address_phone, timestamp.
    """
    direction = _normalize_direction(direction)
    rows: list[dict[str, Any]] = []
    for r in list_referrals(direction=direction, year=year, month=month):
        att = find_attorney(r.get("attorney_id") or "") or {}
        rows.append({
            "patient_name": r.get("patient_name") or "",
            "attorney_label": attorney_display_label(att) if att else "(unknown attorney)",
            "address": " ".join(filter(None, [
                (att.get("address1") or "").strip(),
                (att.get("address2") or "").strip(),
                ", ".join(filter(None, [
                    (att.get("city") or "").strip(),
                    (att.get("state") or "").strip(),
                ])).strip(),
                (att.get("zip") or "").strip(),
            ])).strip(),
            "phone": (att.get("phone") or "").strip(),
            "fax": (att.get("fax") or "").strip(),
            "email": (att.get("email") or "").strip(),
            "timestamp": r.get("timestamp") or "",
        })

    rows.sort(key=lambda x: x.get("timestamp") or "")
    return rows


def per_attorney_summary(
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """Master per-attorney summary across all 3 directions."""
    out: list[dict[str, Any]] = []
    for att in list_attorneys_alphabetical():
        aid = att.get("id") or ""
        row = {
            "attorney_id": aid,
            "label": attorney_display_label(att),
            "from_dol": len(list_referrals(direction="from_dol", attorney_id=aid, year=year, month=month)),
            "from_attorney": len(list_referrals(direction="from_attorney", attorney_id=aid, year=year, month=month)),
            "to_attorney": len(list_referrals(direction="to_attorney", attorney_id=aid, year=year, month=month)),
        }
        row["total"] = row["from_dol"] + row["from_attorney"] + row["to_attorney"]
        out.append(row)
    return out
