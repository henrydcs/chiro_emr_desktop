from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from billing_storage import clinic_billing_dir, patient_billing_root
from insurance_data import load_patient_policies


FILE_INSURANCE_POLICIES = "insurance_policies.json"
FILE_INSURANCE_AUTHS = "insurance_authorizations.json"
FILE_INSURANCE_CLAIMS = "insurance_claims.json"
FILE_INSURANCE_POSTINGS = "insurance_postings.json"
FILE_INSURANCE_PENDING = "insurance_pending.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return json.loads(json.dumps(default))
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return json.loads(json.dumps(default))
    if not isinstance(raw, dict):
        return json.loads(json.dumps(default))
    out = json.loads(json.dumps(default))
    out.update(raw)
    return out


def insurance_catalog_path() -> Path:
    return clinic_billing_dir() / "insurance_catalog.json"


def carc_rarc_codes_path() -> Path:
    return clinic_billing_dir() / "carc_rarc_codes.json"


def patient_insurance_billing_path(patient_root: str | os.PathLike, filename: str) -> Path:
    return patient_billing_root(patient_root) / filename


def default_insurance_catalog() -> dict:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "payers": [],
        "plans": [
            {
                "plan_id": "default_chiro",
                "carrier_id": "",
                "name": "Default chiropractic",
                "requires_auth_for": ["97110", "97112", "97124", "97012", "97014"],
            }
        ],
        "fee_schedules": [],
    }


def default_carc_rarc_codes() -> dict:
    return {
        "version": 1,
        "carc": {
            "1": "Deductible Amount",
            "2": "Coinsurance Amount",
            "3": "Co-payment Amount",
            "45": "Charge exceeds fee schedule/maximum allowable or contractual agreement.",
            "197": "Precertification/authorization/notification absent.",
        },
        "rarc": {
            "N1": "Missing/incomplete/invalid supporting documentation.",
            "N130": "Consultant report missing.",
        },
    }


def default_patient_policies(patient_id: str = "") -> dict:
    return {"version": 1, "patient_id": patient_id or "", "policies": []}


def default_patient_authorizations(patient_id: str = "") -> dict:
    return {"version": 1, "patient_id": patient_id or "", "authorizations": []}


def default_patient_claims() -> dict:
    return {"version": 1, "events": []}


def default_patient_postings() -> dict:
    return {"version": 1, "events": []}


def default_patient_pending() -> dict:
    return {"version": 1, "journal": []}


def load_insurance_catalog() -> dict:
    return _load_json(insurance_catalog_path(), default_insurance_catalog())


def save_insurance_catalog(catalog: dict) -> None:
    payload = default_insurance_catalog()
    payload.update(catalog or {})
    payload["updated_at"] = _now_iso()
    _atomic_write_json(insurance_catalog_path(), payload)


def load_carc_rarc_codes() -> dict:
    return _load_json(carc_rarc_codes_path(), default_carc_rarc_codes())


def save_carc_rarc_codes(codes: dict) -> None:
    payload = default_carc_rarc_codes()
    payload.update(codes or {})
    _atomic_write_json(carc_rarc_codes_path(), payload)


def load_insurance_policies(patient_root: str | os.PathLike, patient_id: str = "") -> dict:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_POLICIES)
    return _load_json(p, default_patient_policies(patient_id))


def save_insurance_policies(patient_root: str | os.PathLike, payload: dict, patient_id: str = "") -> None:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_POLICIES)
    base = default_patient_policies(patient_id)
    base.update(payload or {})
    _atomic_write_json(p, base)


def sync_insurance_policies_snapshot(
    patient_root: str | os.PathLike,
    *,
    patient_id: str = "",
) -> dict:
    """
    Mirror patient policies from insurance_data.py into billing/insurance_policies.json.
    """
    rows = load_patient_policies(patient_root)
    mapped: list[dict[str, Any]] = []
    for row in rows:
        mapped.append(
            {
                "policy_id": row.get("id") or "",
                "order": row.get("priority") or "primary",
                "insurance_type": row.get("insurance_type") or "health",
                "carrier_id": row.get("carrier_id") or "",
                "carrier_name": row.get("carrier_name") or "",
                "plan_id": row.get("plan_id") or "",
                "member_id": row.get("policy_number") or "",
                "group_number": row.get("group_number") or "",
                "subscriber_name": row.get("policyholder_name") or "",
                "relationship_to_subscriber": row.get("policyholder_relationship") or "",
                "subscriber_dob": row.get("policyholder_dob") or "",
                "effective_date": row.get("effective_date") or "",
                "termination_date": row.get("termination_date") or "",
                "status": "active" if not (row.get("termination_date") or "").strip() else "inactive",
                "notes": row.get("notes") or "",
            }
        )
    if not mapped:
        # Do not clobber an existing billing-side insurance snapshot with an
        # empty mirror if insurance_data has not been populated yet.
        existing = load_insurance_policies(patient_root, patient_id=patient_id)
        if existing.get("policies"):
            return existing
    payload = default_patient_policies(patient_id=patient_id)
    payload["policies"] = mapped
    save_insurance_policies(patient_root, payload, patient_id=patient_id)
    return payload


def load_insurance_authorizations(patient_root: str | os.PathLike, patient_id: str = "") -> dict:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_AUTHS)
    return _load_json(p, default_patient_authorizations(patient_id))


def save_insurance_authorizations(
    patient_root: str | os.PathLike,
    payload: dict,
    patient_id: str = "",
) -> None:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_AUTHS)
    base = default_patient_authorizations(patient_id)
    base.update(payload or {})
    _atomic_write_json(p, base)


def load_insurance_claims(patient_root: str | os.PathLike) -> dict:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_CLAIMS)
    return _load_json(p, default_patient_claims())


def save_insurance_claims(patient_root: str | os.PathLike, payload: dict) -> None:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_CLAIMS)
    base = default_patient_claims()
    base.update(payload or {})
    _atomic_write_json(p, base)


def load_insurance_postings(patient_root: str | os.PathLike) -> dict:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_POSTINGS)
    return _load_json(p, default_patient_postings())


def save_insurance_postings(patient_root: str | os.PathLike, payload: dict) -> None:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_POSTINGS)
    base = default_patient_postings()
    base.update(payload or {})
    _atomic_write_json(p, base)


def load_insurance_pending(patient_root: str | os.PathLike) -> dict:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_PENDING)
    pending = _load_json(p, default_patient_pending())
    if not isinstance(pending.get("journal"), list):
        pending["journal"] = []
    return pending


def save_insurance_pending(patient_root: str | os.PathLike, payload: dict) -> None:
    p = patient_insurance_billing_path(patient_root, FILE_INSURANCE_PENDING)
    base = default_patient_pending()
    base.update(payload or {})
    if not isinstance(base.get("journal"), list):
        base["journal"] = []
    _atomic_write_json(p, base)


def ensure_insurance_files(
    patient_root: str | os.PathLike,
    *,
    patient_id: str = "",
) -> None:
    if not insurance_catalog_path().is_file():
        save_insurance_catalog(default_insurance_catalog())
    if not carc_rarc_codes_path().is_file():
        save_carc_rarc_codes(default_carc_rarc_codes())
    if not patient_insurance_billing_path(patient_root, FILE_INSURANCE_POLICIES).is_file():
        sync_insurance_policies_snapshot(patient_root, patient_id=patient_id)
    if not patient_insurance_billing_path(patient_root, FILE_INSURANCE_AUTHS).is_file():
        save_insurance_authorizations(patient_root, default_patient_authorizations(patient_id), patient_id=patient_id)
    if not patient_insurance_billing_path(patient_root, FILE_INSURANCE_CLAIMS).is_file():
        save_insurance_claims(patient_root, default_patient_claims())
    if not patient_insurance_billing_path(patient_root, FILE_INSURANCE_POSTINGS).is_file():
        save_insurance_postings(patient_root, default_patient_postings())
    if not patient_insurance_billing_path(patient_root, FILE_INSURANCE_PENDING).is_file():
        save_insurance_pending(patient_root, default_patient_pending())


def _append_pending_intent(
    patient_root: str | os.PathLike,
    *,
    op_name: str,
    target_file: str,
    payload: dict,
) -> str:
    pending = load_insurance_pending(patient_root)
    journal = pending.get("journal") or []
    jid = f"jrn_{uuid.uuid4().hex[:12]}"
    journal.append(
        {
            "journal_id": jid,
            "status": "pending",
            "created_at": _now_iso(),
            "completed_at": "",
            "op_name": op_name,
            "target_file": target_file,
            "payload": payload,
        }
    )
    pending["journal"] = journal
    save_insurance_pending(patient_root, pending)
    return jid


def _mark_pending_completed(patient_root: str | os.PathLike, journal_id: str) -> None:
    pending = load_insurance_pending(patient_root)
    for item in pending.get("journal") or []:
        if item.get("journal_id") == journal_id:
            item["status"] = "completed"
            item["completed_at"] = _now_iso()
            break
    save_insurance_pending(patient_root, pending)


def append_claim_event_atomic(patient_root: str | os.PathLike, event: dict) -> None:
    jid = _append_pending_intent(
        patient_root,
        op_name="append_claim_event",
        target_file=FILE_INSURANCE_CLAIMS,
        payload=event,
    )
    claims = load_insurance_claims(patient_root)
    events = claims.get("events") or []
    events.append(event)
    claims["events"] = events
    save_insurance_claims(patient_root, claims)
    _mark_pending_completed(patient_root, jid)


def append_posting_event_atomic(patient_root: str | os.PathLike, event: dict) -> None:
    jid = _append_pending_intent(
        patient_root,
        op_name="append_posting_event",
        target_file=FILE_INSURANCE_POSTINGS,
        payload=event,
    )
    postings = load_insurance_postings(patient_root)
    events = postings.get("events") or []
    events.append(event)
    postings["events"] = events
    save_insurance_postings(patient_root, postings)
    _mark_pending_completed(patient_root, jid)


def add_authorization(
    patient_root: str | os.PathLike,
    *,
    patient_id: str,
    auth_number: str,
    payer_id: str,
    effective_date: str,
    expiration_date: str,
    allowed_cpts: list[str],
    total_units_approved: int,
    recorded_by: str = "",
) -> dict:
    auths = load_insurance_authorizations(patient_root, patient_id=patient_id)
    item = {
        "auth_id": f"auth_{uuid.uuid4().hex[:10]}",
        "auth_number": (auth_number or "").strip(),
        "payer_id": (payer_id or "").strip(),
        "effective_date": (effective_date or "").strip(),
        "expiration_date": (expiration_date or "").strip(),
        "allowed_cpts": [str(c).strip() for c in (allowed_cpts or []) if str(c).strip()],
        "total_units_approved": int(total_units_approved or 0),
        "units_used": 0,
        "status": "active",
        "linked_claims": [],
        "created_at": _now_iso(),
        "recorded_by": recorded_by or "",
    }
    rows = auths.get("authorizations") or []
    rows.append(item)
    auths["authorizations"] = rows
    save_insurance_authorizations(patient_root, auths, patient_id=patient_id)
    return item


def update_authorization(
    patient_root: str | os.PathLike,
    *,
    auth_id: str,
    patient_id: str = "",
    **fields: Any,
) -> dict | None:
    auths = load_insurance_authorizations(patient_root, patient_id=patient_id)
    rows = auths.get("authorizations") or []
    for a in rows:
        if (a.get("auth_id") or "") != auth_id:
            continue
        for key, val in fields.items():
            if key == "allowed_cpts" and val is not None:
                a["allowed_cpts"] = [str(c).strip() for c in val if str(c).strip()]
            elif key in a or key in (
                "auth_number",
                "payer_id",
                "effective_date",
                "expiration_date",
                "total_units_approved",
                "units_used",
                "status",
            ):
                a[key] = val
        save_insurance_authorizations(patient_root, auths, patient_id=patient_id)
        return a
    return None

