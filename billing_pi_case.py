# billing_pi_case.py — PI case metadata (DOI, attorney, carriers, status).
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import attorney_data as adata
from insurance_data import INSURANCE_TYPE_LABELS, load_patient_policies
from shell_app import read_patient_profile

from billing_storage import patient_billing_root

_CASE_VERSION = 1
_PI_TYPES = frozenset({"auto_pip", "auto_medpay", "auto_liability"})


def pi_case_path(patient_root: str | os.PathLike) -> Path:
    p = patient_billing_root(patient_root) / "pi_case.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _attorney_display(attorney_id: str) -> dict:
    rec = adata.find_attorney(attorney_id) if attorney_id else None
    if not rec:
        return {"id": attorney_id or "", "name": "", "firm": ""}
    name = (rec.get("name") or "").strip()
    firm = (rec.get("firm") or "").strip()
    return {"id": attorney_id, "name": name, "firm": firm}


def _carriers_from_policies(patient_root: str | os.PathLike) -> list[dict]:
    out: list[dict] = []
    for pol in load_patient_policies(patient_root):
        itype = (pol.get("insurance_type") or "").strip().lower()
        if itype not in _PI_TYPES:
            continue
        out.append(
            {
                "insurance_type": itype,
                "type_label": INSURANCE_TYPE_LABELS.get(itype, itype),
                "carrier_name": (pol.get("carrier_name") or "").strip(),
                "claim_number": (pol.get("claim_number") or pol.get("policy_number") or "").strip(),
                "policy_number": (pol.get("policy_number") or "").strip(),
                "priority": (pol.get("priority") or "").strip(),
            }
        )
    return out


def _attorney_from_referrals(patient_root: str | os.PathLike) -> dict:
    state = adata.load_patient_referral_state(patient_root)
    for direction in ("from_attorney", "from_dol", "to_attorney"):
        aid = (state.get(direction) or {}).get("attorney_id") or ""
        if aid:
            info = _attorney_display(aid)
            info["referral_direction"] = direction
            return info
    return {"id": "", "name": "", "firm": "", "referral_direction": ""}


def build_pi_case_from_chart(patient_root: str | os.PathLike, patient_id: str = "") -> dict:
    """Assemble case fields from patient.json, insurance, and attorney referral."""
    profile = read_patient_profile(Path(patient_root))
    return {
        "case_id": f"case_{uuid.uuid4().hex[:12]}",
        "version": _CASE_VERSION,
        "patient_id": patient_id or (profile.get("patient_id") or ""),
        "case_status": "active",
        "date_of_injury": (profile.get("doi") or "").strip(),
        "claim_number": (profile.get("claim") or "").strip(),
        "attorney": _attorney_from_referrals(patient_root),
        "carriers": _carriers_from_policies(patient_root),
        "notes": "",
        "opened_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def load_pi_case(patient_root: str | os.PathLike) -> dict | None:
    p = pi_case_path(patient_root)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def save_pi_case(patient_root: str | os.PathLike, case: dict) -> None:
    case = dict(case)
    case["updated_at"] = datetime.now().isoformat(timespec="seconds")
    p = pi_case_path(patient_root)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2)
    os.replace(tmp, p)


def load_or_create_pi_case(
    patient_root: str | os.PathLike,
    *,
    patient_id: str = "",
    refresh_from_chart: bool = False,
) -> dict:
    existing = load_pi_case(patient_root)
    if existing and not refresh_from_chart:
        return existing
    fresh = build_pi_case_from_chart(patient_root, patient_id=patient_id)
    if existing:
        fresh["case_id"] = existing.get("case_id") or fresh["case_id"]
        fresh["case_status"] = existing.get("case_status") or fresh["case_status"]
        fresh["notes"] = existing.get("notes") or ""
        fresh["opened_at"] = existing.get("opened_at") or fresh["opened_at"]
        if not fresh.get("date_of_injury"):
            fresh["date_of_injury"] = existing.get("date_of_injury") or ""
        if not fresh.get("claim_number"):
            fresh["claim_number"] = existing.get("claim_number") or ""
    save_pi_case(patient_root, fresh)
    return fresh


def sync_pi_case_from_chart(patient_root: str | os.PathLike, patient_id: str = "") -> dict:
    return load_or_create_pi_case(
        patient_root, patient_id=patient_id, refresh_from_chart=True
    )


def case_status_label(status: str) -> str:
    return {
        "active": "Active",
        "settled": "Settled",
        "closed": "Closed",
    }.get((status or "").strip().lower(), status or "Active")
