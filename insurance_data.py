# insurance_data.py
"""
Centralized data layer for the Insurance Demographics + Stats subsystem.

Stores everything in two places:
  1) Clinic-wide insurance directory + cross-patient policy log:
        <DATA_DIR>/insurance.json
        {
          "version": 1,
          "carriers": [...],   # clinic-wide insurance carrier directory
          "policies": [...],   # one row per (patient × policy) — used by stats
        }
  2) Per-patient policy state (which carriers/policies the patient is currently
     enrolled in, including primary/secondary/etc.):
        <PATIENT_ROOT>/patient_info/insurance.json
        {"policies": [...]}

Insurance types
---------------
- "health":          Standard medical/health insurance
- "auto_pip":        Auto — Personal Injury Protection (no-fault)
- "auto_medpay":     Auto — Medical Payments coverage
- "auto_liability":  Auto — third-party liability (the at-fault driver's carrier)
- "workers_comp":    Workers' Compensation
- "medicare":        Medicare
- "medicaid":        Medicaid
- "cash":            Cash / self-pay
- "other":           Anything else

Each patient can hold many policies; each policy has a ``priority``
("primary" / "secondary" / "tertiary" / "other") that the user can use
to order them within a single insurance type (e.g. primary medical vs
secondary medical).

The clinic-wide ``policies`` log is denormalized so stats queries don't
have to walk every patient folder. Whenever a patient policy is added,
edited, or removed, both stores are kept in sync.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from paths import get_data_dir
from config import PATIENT_SUBDIR_INFO


# ---------------------------------------------------------------------------
# Type / priority vocabularies
# ---------------------------------------------------------------------------
INSURANCE_TYPES: tuple[str, ...] = (
    "health",
    "auto_pip",
    "auto_medpay",
    "auto_liability",
    "workers_comp",
    "medicare",
    "medicaid",
    "cash",
    "other",
)

INSURANCE_TYPE_LABELS: dict[str, str] = {
    "health":         "Health",
    "auto_pip":       "Auto — PIP",
    "auto_medpay":    "Auto — Med-Pay",
    "auto_liability": "Auto — Liability",
    "workers_comp":   "Workers' Comp",
    "medicare":       "Medicare",
    "medicaid":       "Medicaid",
    "cash":           "Cash / Self-Pay",
    "other":          "Other",
}

# Coarse buckets used by the Master Stats / Type Breakdown screens. Several
# insurance types can roll up to the same bucket (e.g. PIP, Med-Pay, Liability
# are all "Personal Injury / Auto").
INSURANCE_TYPE_BUCKETS: dict[str, str] = {
    "health":         "Health",
    "auto_pip":       "Personal Injury / Auto",
    "auto_medpay":    "Personal Injury / Auto",
    "auto_liability": "Personal Injury / Auto",
    "workers_comp":   "Workers' Comp",
    "medicare":       "Medicare",
    "medicaid":       "Medicaid",
    "cash":           "Cash / Self-Pay",
    "other":          "Other",
}

PRIORITIES: tuple[str, ...] = ("primary", "secondary", "tertiary", "other")

PRIORITY_LABELS: dict[str, str] = {
    "primary":   "Primary",
    "secondary": "Secondary",
    "tertiary":  "Tertiary",
    "other":     "Other",
}

POLICYHOLDER_RELATIONSHIPS: tuple[str, ...] = (
    "self", "spouse", "parent", "child", "other",
)


_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def insurance_db_path() -> Path:
    """Clinic-wide insurance database file path."""
    return get_data_dir() / "insurance.json"


def patient_insurance_path(patient_root: str | os.PathLike) -> Path:
    """Per-patient insurance state file path."""
    return Path(patient_root) / PATIENT_SUBDIR_INFO / "insurance.json"


# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------
def _default_db() -> dict:
    return {
        "version": 1,
        "carriers": [],
        "policies": [],
    }


def _default_patient_state() -> dict:
    return {"policies": []}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Load / save (clinic-wide DB)
# ---------------------------------------------------------------------------
def load_db() -> dict:
    p = insurance_db_path()
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
    if not isinstance(obj.get("carriers"), list):
        obj["carriers"] = []
    if not isinstance(obj.get("policies"), list):
        obj["policies"] = []
    return obj


def save_db(db: dict) -> None:
    p = insurance_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Carrier CRUD
# ---------------------------------------------------------------------------
CARRIER_FIELDS: tuple[str, ...] = (
    "name",
    "parent_company",
    "claims_address1",
    "claims_address2",
    "city",
    "state",
    "zip",
    "claims_phone",
    "fax",
    "payer_id",
    "portal_url",
    "default_type",
    "notes",
)


def _blank_carrier() -> dict:
    rec = {f: "" for f in CARRIER_FIELDS}
    rec["id"] = ""
    rec["created_at"] = ""
    rec["updated_at"] = ""
    return rec


def list_carriers() -> list[dict]:
    return list(load_db().get("carriers", []))


def list_carriers_alphabetical() -> list[dict]:
    items = list_carriers()
    items.sort(
        key=lambda c: (
            (c.get("name") or c.get("parent_company") or "").strip().lower()
        )
    )
    return items


def find_carrier(carrier_id: str) -> dict | None:
    if not carrier_id:
        return None
    for c in list_carriers():
        if c.get("id") == carrier_id:
            return c
    return None


def carrier_display_label(rec: dict | None) -> str:
    if not rec:
        return ""
    name = (rec.get("name") or "").strip()
    parent = (rec.get("parent_company") or "").strip()
    if name and parent and parent.lower() != name.lower():
        return f"{name} ({parent})"
    return name or parent or "(unnamed carrier)"


def add_carrier(data: dict) -> dict:
    with _LOCK:
        db = load_db()
        rec = _blank_carrier()
        for f in CARRIER_FIELDS:
            if f in data:
                rec[f] = (data.get(f) or "").strip()
        rec["id"] = _new_id()
        rec["created_at"] = _now_iso()
        rec["updated_at"] = rec["created_at"]
        db["carriers"].append(rec)
        save_db(db)
        return rec


def update_carrier(carrier_id: str, data: dict) -> dict | None:
    with _LOCK:
        db = load_db()
        updated: dict | None = None
        for rec in db.get("carriers", []):
            if rec.get("id") == carrier_id:
                for f in CARRIER_FIELDS:
                    if f in data:
                        rec[f] = (data.get(f) or "").strip()
                rec["updated_at"] = _now_iso()
                updated = rec
                break
        if updated is None:
            return None
        # Keep the denormalized carrier_name in sync everywhere it's stored
        # (clinic-wide log AND each affected patient's insurance.json) so the
        # rename is visible immediately without re-loading.
        new_label = carrier_display_label(updated)
        affected_patient_roots: set[str] = set()
        for pol in db.get("policies", []):
            if pol.get("carrier_id") == carrier_id:
                pol["carrier_name"] = new_label
                pr = (pol.get("patient_root") or "").strip()
                if pr:
                    affected_patient_roots.add(pr)
        save_db(db)
        for pr in affected_patient_roots:
            try:
                state = _load_patient_state(pr)
                changed = False
                for pol in state.get("policies", []):
                    if pol.get("carrier_id") == carrier_id:
                        pol["carrier_name"] = new_label
                        changed = True
                if changed:
                    _save_patient_state(pr, state)
            except Exception:
                pass
        return updated


def delete_carrier(carrier_id: str) -> bool:
    """Delete a carrier from the directory and from any patient policies that
    reference it. Returns True if anything was removed.

    Each affected patient's per-patient insurance.json is also updated so the
    UI stays consistent. The ``policies`` rows are removed from the clinic-wide
    log as well; the patient effectively loses that insurance entry."""
    with _LOCK:
        db = load_db()
        before_carriers = len(db.get("carriers", []))
        db["carriers"] = [
            c for c in db.get("carriers", []) if c.get("id") != carrier_id
        ]
        affected_patient_roots: set[str] = set()
        for pol in db.get("policies", []):
            if pol.get("carrier_id") == carrier_id:
                pr = (pol.get("patient_root") or "").strip()
                if pr:
                    affected_patient_roots.add(pr)
        db["policies"] = [
            p for p in db.get("policies", []) if p.get("carrier_id") != carrier_id
        ]
        changed = len(db["carriers"]) != before_carriers
        if changed or affected_patient_roots:
            save_db(db)
        # Mirror to per-patient state files.
        for pr in affected_patient_roots:
            try:
                state = _load_patient_state(pr)
                state["policies"] = [
                    p for p in state.get("policies", [])
                    if p.get("carrier_id") != carrier_id
                ]
                _save_patient_state(pr, state)
            except Exception:
                pass
        return changed


# ---------------------------------------------------------------------------
# Per-patient policies
# ---------------------------------------------------------------------------
POLICY_FIELDS: tuple[str, ...] = (
    "carrier_id",
    "insurance_type",
    "priority",
    "policy_number",
    "group_number",
    "claim_number",
    "policyholder_name",
    "policyholder_dob",
    "policyholder_relationship",
    "adjuster_name",
    "adjuster_phone",
    "adjuster_email",
    "effective_date",
    "termination_date",
    "notes",
)


def _blank_policy() -> dict:
    rec = {f: "" for f in POLICY_FIELDS}
    rec["id"] = ""
    rec["patient_id"] = ""
    rec["patient_name"] = ""
    rec["patient_root"] = ""
    rec["carrier_name"] = ""
    rec["created_at"] = ""
    rec["updated_at"] = ""
    return rec


def _normalize_type(t: str) -> str:
    t = (t or "").strip().lower()
    if t not in INSURANCE_TYPES:
        return "other"
    return t


def _normalize_priority(p: str) -> str:
    p = (p or "").strip().lower()
    if p not in PRIORITIES:
        return "primary"
    return p


def _load_patient_state(patient_root: str | os.PathLike) -> dict:
    if not patient_root:
        return _default_patient_state()
    p = patient_insurance_path(patient_root)
    if not p.exists():
        return _default_patient_state()
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f) or {}
    except Exception:
        return _default_patient_state()
    out = _default_patient_state()
    if isinstance(obj, dict) and isinstance(obj.get("policies"), list):
        out["policies"] = [p for p in obj["policies"] if isinstance(p, dict)]
    return out


def _save_patient_state(patient_root: str | os.PathLike, state: dict) -> None:
    p = patient_insurance_path(patient_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def load_patient_policies(patient_root: str | os.PathLike | None) -> list[dict]:
    """Read the policy list for a single patient (sorted: type, then priority)."""
    if not patient_root:
        return []
    state = _load_patient_state(patient_root)
    policies = list(state.get("policies", []))
    type_order = {t: i for i, t in enumerate(INSURANCE_TYPES)}
    pri_order = {p: i for i, p in enumerate(PRIORITIES)}
    policies.sort(key=lambda p: (
        type_order.get(_normalize_type(p.get("insurance_type")), 99),
        pri_order.get(_normalize_priority(p.get("priority")), 99),
        (p.get("created_at") or ""),
    ))
    return policies


def find_patient_policy(
    patient_root: str | os.PathLike, policy_id: str,
) -> dict | None:
    if not patient_root or not policy_id:
        return None
    for pol in load_patient_policies(patient_root):
        if pol.get("id") == policy_id:
            return pol
    return None


def add_patient_policy(
    *,
    patient_root: str | os.PathLike,
    patient_id: str,
    patient_name: str,
    data: dict,
) -> dict:
    """Add a new policy to the patient and to the clinic-wide log."""
    if not patient_root:
        raise ValueError("patient_root is required")

    pr = str(patient_root)
    rec = _blank_policy()
    for f in POLICY_FIELDS:
        if f in data:
            rec[f] = (data.get(f) or "").strip()
    rec["insurance_type"] = _normalize_type(rec.get("insurance_type"))
    rec["priority"] = _normalize_priority(rec.get("priority"))
    rec["id"] = _new_id()
    rec["patient_id"] = (patient_id or "").strip()
    rec["patient_name"] = (patient_name or "").strip()
    rec["patient_root"] = pr
    rec["carrier_name"] = carrier_display_label(find_carrier(rec.get("carrier_id") or ""))
    rec["created_at"] = _now_iso()
    rec["updated_at"] = rec["created_at"]

    with _LOCK:
        db = load_db()
        db["policies"].append(dict(rec))
        save_db(db)

        state = _load_patient_state(pr)
        state["policies"].append(dict(rec))
        _save_patient_state(pr, state)
    return rec


def update_patient_policy(
    *,
    patient_root: str | os.PathLike,
    policy_id: str,
    data: dict,
) -> dict | None:
    """Update an existing patient policy in both stores."""
    if not patient_root or not policy_id:
        return None

    pr = str(patient_root)
    with _LOCK:
        # Patient state ----------------------------------------------------
        state = _load_patient_state(pr)
        target: dict | None = None
        for pol in state.get("policies", []):
            if pol.get("id") == policy_id:
                target = pol
                break
        if target is None:
            return None
        for f in POLICY_FIELDS:
            if f in data:
                target[f] = (data.get(f) or "").strip()
        target["insurance_type"] = _normalize_type(target.get("insurance_type"))
        target["priority"] = _normalize_priority(target.get("priority"))
        target["carrier_name"] = carrier_display_label(
            find_carrier(target.get("carrier_id") or "")
        )
        target["updated_at"] = _now_iso()
        _save_patient_state(pr, state)

        # Clinic-wide log --------------------------------------------------
        db = load_db()
        for pol in db.get("policies", []):
            if pol.get("id") == policy_id:
                for f in POLICY_FIELDS:
                    if f in data:
                        pol[f] = (data.get(f) or "").strip()
                pol["insurance_type"] = target["insurance_type"]
                pol["priority"] = target["priority"]
                pol["carrier_name"] = target["carrier_name"]
                pol["updated_at"] = target["updated_at"]
                break
        save_db(db)
        return dict(target)


def delete_patient_policy(
    *,
    patient_root: str | os.PathLike,
    policy_id: str,
) -> bool:
    """Remove a single policy from both stores."""
    if not patient_root or not policy_id:
        return False

    pr = str(patient_root)
    with _LOCK:
        state = _load_patient_state(pr)
        before = len(state.get("policies", []))
        state["policies"] = [
            p for p in state.get("policies", []) if p.get("id") != policy_id
        ]
        changed = len(state["policies"]) != before
        if changed:
            _save_patient_state(pr, state)

        db = load_db()
        before_db = len(db.get("policies", []))
        db["policies"] = [
            p for p in db.get("policies", []) if p.get("id") != policy_id
        ]
        if len(db["policies"]) != before_db:
            save_db(db)
        return changed


def delete_all_policies_for_patient(
    *,
    patient_root: str | os.PathLike,
    patient_id: str = "",
) -> int:
    """Wipe every policy attached to this patient (used when a chart is deleted)."""
    pr = str(patient_root or "").strip()
    pid = (patient_id or "").strip()
    if not pr and not pid:
        return 0
    removed = 0
    with _LOCK:
        if pr:
            try:
                state = _load_patient_state(pr)
                removed = len(state.get("policies", []))
                state["policies"] = []
                _save_patient_state(pr, state)
            except Exception:
                pass

        db = load_db()
        before = len(db.get("policies", []))
        def _matches(p: dict) -> bool:
            if pr and (p.get("patient_root") or "").strip() == pr:
                return True
            if pid and (p.get("patient_id") or "").strip() == pid:
                return True
            return False
        db["policies"] = [p for p in db.get("policies", []) if not _matches(p)]
        if len(db["policies"]) != before:
            save_db(db)
            removed = max(removed, before - len(db["policies"]))
    return removed


# ---------------------------------------------------------------------------
# Aggregates / stats
# ---------------------------------------------------------------------------
def _ts_in_period(
    ts: str, year: int | None, month: int | None,
) -> bool:
    if year is None and month is None:
        return True
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return False
    if year is not None and dt.year != year:
        return False
    if month is not None and dt.month != month:
        return False
    return True


def list_policies(
    *,
    insurance_type: str | None = None,
    carrier_id: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> list[dict]:
    """Return clinic-wide policy rows filtered by any combination of fields.
    Period filters use the policy's ``created_at`` timestamp."""
    db = load_db()
    out: list[dict] = []
    norm_t = _normalize_type(insurance_type) if insurance_type else None
    for p in db.get("policies", []):
        if norm_t and _normalize_type(p.get("insurance_type")) != norm_t:
            continue
        if carrier_id and p.get("carrier_id") != carrier_id:
            continue
        if not _ts_in_period(p.get("created_at") or "", year, month):
            continue
        out.append(p)
    return out


def per_carrier_summary(
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """For each carrier in the directory, count how many distinct patients
    have a policy on it (within the optional period). Carriers with no
    activity are still returned so the user can see what's unused."""
    rows: list[dict[str, Any]] = []
    carriers = {c["id"]: c for c in list_carriers()}

    # Aggregate.
    by_carrier_pids: dict[str, set[str]] = {cid: set() for cid in carriers}
    by_carrier_count: dict[str, int] = {cid: 0 for cid in carriers}
    orphan_pids: set[str] = set()
    orphan_count = 0

    for p in list_policies(year=year, month=month):
        cid = p.get("carrier_id") or ""
        pid = (p.get("patient_id") or p.get("patient_root") or "").strip()
        if cid in carriers:
            by_carrier_count[cid] += 1
            if pid:
                by_carrier_pids[cid].add(pid)
        else:
            orphan_count += 1
            if pid:
                orphan_pids.add(pid)

    for cid, c in carriers.items():
        rows.append({
            "carrier_id": cid,
            "label": carrier_display_label(c),
            "policies": by_carrier_count[cid],
            "patients": len(by_carrier_pids[cid]),
        })

    if orphan_count:
        rows.append({
            "carrier_id": "",
            "label": "(deleted / unknown carrier)",
            "policies": orphan_count,
            "patients": len(orphan_pids),
        })

    rows.sort(key=lambda r: (-r["patients"], -r["policies"], r["label"].lower()))
    return rows


def per_type_summary(
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """Policies + distinct patients per insurance type."""
    by_type_pids: dict[str, set[str]] = {t: set() for t in INSURANCE_TYPES}
    by_type_count: dict[str, int] = {t: 0 for t in INSURANCE_TYPES}
    for p in list_policies(year=year, month=month):
        t = _normalize_type(p.get("insurance_type"))
        by_type_count[t] = by_type_count.get(t, 0) + 1
        pid = (p.get("patient_id") or p.get("patient_root") or "").strip()
        if pid:
            by_type_pids.setdefault(t, set()).add(pid)
    rows = [
        {
            "type": t,
            "label": INSURANCE_TYPE_LABELS[t],
            "bucket": INSURANCE_TYPE_BUCKETS[t],
            "policies": by_type_count.get(t, 0),
            "patients": len(by_type_pids.get(t, set())),
        }
        for t in INSURANCE_TYPES
    ]
    rows.sort(key=lambda r: (-r["patients"], -r["policies"], r["label"].lower()))
    return rows


def per_bucket_summary(
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict[str, Any]]:
    """Coarser breakdown that rolls Auto-PIP/Med-Pay/Liability into one bucket."""
    bucket_pids: dict[str, set[str]] = {}
    bucket_count: dict[str, int] = {}
    for p in list_policies(year=year, month=month):
        bucket = INSURANCE_TYPE_BUCKETS.get(
            _normalize_type(p.get("insurance_type")), "Other",
        )
        bucket_count[bucket] = bucket_count.get(bucket, 0) + 1
        pid = (p.get("patient_id") or p.get("patient_root") or "").strip()
        if pid:
            bucket_pids.setdefault(bucket, set()).add(pid)
    rows = [
        {
            "bucket": b,
            "policies": bucket_count.get(b, 0),
            "patients": len(bucket_pids.get(b, set())),
        }
        for b in sorted(bucket_count.keys() | bucket_pids.keys())
    ]
    rows.sort(key=lambda r: (-r["patients"], -r["policies"], r["bucket"].lower()))
    return rows


def overall_stats(
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Summary counters for the Master Stats header."""
    policies = list_policies(year=year, month=month)
    all_pids = {
        (p.get("patient_id") or p.get("patient_root") or "").strip()
        for p in policies
    }
    all_pids.discard("")
    carriers = list_carriers()
    active_carrier_ids = {p.get("carrier_id") for p in policies if p.get("carrier_id")}
    return {
        "total_policies": len(policies),
        "total_patients_with_insurance": len(all_pids),
        "total_carriers": len(carriers),
        "active_carriers": len(active_carrier_ids & {c["id"] for c in carriers}),
    }


def patient_counts_overall() -> dict[str, int]:
    """Counts that don't depend on a period filter."""
    db = load_db()
    return {
        "carriers": len(db.get("carriers", [])),
        "policies": len(db.get("policies", [])),
    }


# ---------------------------------------------------------------------------
# Bulk helpers (used by PDF export, etc.)
# ---------------------------------------------------------------------------
def carriers_for_pdf() -> Iterable[dict]:
    """Returns carriers in the order the PDF will print them (alphabetical
    by display name)."""
    return list_carriers_alphabetical()
