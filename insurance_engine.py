from __future__ import annotations

import copy
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from insurance_billing_storage import (
    append_claim_event_atomic,
    append_posting_event_atomic,
    ensure_insurance_files,
    load_insurance_authorizations,
    load_insurance_catalog,
    load_insurance_claims,
    load_insurance_policies,
    load_insurance_postings,
    save_insurance_authorizations,
    sync_insurance_policies_snapshot,
)


CLAIM_STATUSES = (
    "draft",
    "ready_to_submit",
    "submitted",
    "payer_acknowledged",
    "rejected",
    "pending",
    "adjudicated",
    "paid_partial",
    "paid_full",
    "denied",
    "appealed",
    "closed",
    "voided",
)

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"ready_to_submit", "voided"},
    "ready_to_submit": {"submitted", "draft", "voided"},
    "submitted": {"payer_acknowledged", "rejected", "pending", "adjudicated", "paid_partial", "paid_full", "denied", "voided"},
    "payer_acknowledged": {"pending", "rejected"},
    "rejected": {"ready_to_submit", "voided", "appealed", "denied"},
    "pending": {"adjudicated", "denied"},
    "adjudicated": {"paid_partial", "paid_full", "denied", "closed", "voided"},
    "paid_partial": {"paid_full", "appealed", "closed", "voided"},
    "paid_full": {"closed"},
    "denied": {"appealed", "closed", "voided"},
    "appealed": {"pending", "denied", "paid_partial", "paid_full", "closed"},
    "closed": set(),
    "voided": set(),
}


_ICD_RE = re.compile(r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _claim_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"clm_{ts}_{uuid.uuid4().hex[:4]}"


def _event_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _line_charge(line: dict) -> float:
    fees = line.get("fees") or {}
    try:
        if fees.get("pi_ucr") not in (None, ""):
            return float(fees.get("pi_ucr") or 0.0)
        if fees.get("cash") not in (None, ""):
            return float(fees.get("cash") or 0.0)
        return float(line.get("amount") or 0.0)
    except Exception:
        return 0.0


def _active_policies_snapshot(patient_root: str, patient_id: str = "") -> dict:
    # Always re-sync from insurance_data to keep billing snapshot current.
    return sync_insurance_policies_snapshot(patient_root, patient_id=patient_id)


def _primary_policy(policies: list[dict]) -> dict | None:
    for p in policies:
        if (p.get("status") or "active") == "active" and (p.get("order") or "").lower() == "primary":
            return p
    for p in policies:
        if (p.get("status") or "active") == "active":
            return p
    return None


def _secondary_policy(policies: list[dict], primary_policy_id: str) -> dict | None:
    for p in policies:
        if p.get("policy_id") == primary_policy_id:
            continue
        if (p.get("status") or "active") == "active" and (p.get("order") or "").lower() == "secondary":
            return p
    return None


def _validate_dx_codes(diagnoses: list[str]) -> list[str]:
    warnings: list[str] = []
    for code in diagnoses:
        c = (code or "").strip().upper()
        if not c:
            warnings.append("Blank diagnosis code.")
            continue
        if not _ICD_RE.match(c):
            warnings.append(f"Diagnosis '{c}' may not match ICD-10 format.")
    return warnings


def _dx_index_by_code(diagnoses: list[str]) -> dict[str, int]:
    return {
        (code or "").strip().upper(): idx
        for idx, code in enumerate(diagnoses, start=1)
        if (code or "").strip()
    }


def _expand_dx_tokens(raw_ptrs: list) -> list[str]:
    """Accept list entries and comma/semicolon-separated ICD or index tokens."""
    out: list[str] = []
    for item in raw_ptrs or []:
        text = str(item or "").strip()
        if not text:
            continue
        for part in text.replace(";", ",").split(","):
            tok = part.strip().upper()
            if tok:
                out.append(tok)
    return out


def _dx_ptr_indices_for_line(diagnoses: list[str], ln: dict) -> list[str]:
    """
    CMS-1500 diagnosis pointers are 1..N indices into the claim diagnosis list.
    Shadow encounters store full ICD-10 codes on each line — convert those to
  indices here (e.g. ['S06.0X0A','M50.20'] -> ['1','2']).
    """
    idx_map = _dx_index_by_code(diagnoses)
    tokens = _expand_dx_tokens(ln.get("diagnosis_pointers") or ln.get("dx_ptr") or [])
    indices: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if tok.isdigit():
            n = int(tok)
            if 1 <= n <= len(diagnoses):
                key = str(n)
                if key not in seen:
                    indices.append(key)
                    seen.add(key)
            continue
        n = idx_map.get(tok)
        if n is not None:
            key = str(n)
            if key not in seen:
                indices.append(key)
                seen.add(key)
    if not indices and diagnoses:
        indices = ["1"]
    return indices


def _validate_dx_ptrs(lines: list[dict], diagnoses: list[str]) -> list[str]:
    warnings: list[str] = []
    max_idx = len(diagnoses)
    idx_map = _dx_index_by_code(diagnoses)
    for ln in lines:
        ptrs = ln.get("dx_ptr") or []
        if not ptrs:
            warnings.append(f"Line {ln.get('line_id')}: missing DX pointer.")
            continue
        for ptr in ptrs:
            s = str(ptr or "").strip().upper()
            if s.isdigit():
                n = int(s)
                if n < 1 or n > max_idx:
                    warnings.append(f"Line {ln.get('line_id')}: DX pointer {n} out of range.")
                continue
            # Legacy snapshots may still store ICD-10 codes instead of indices.
            if s in idx_map:
                continue
            warnings.append(f"Line {ln.get('line_id')}: invalid DX pointer '{s}'.")
    return warnings


def _plan_auth_requirements(policy: dict) -> set[str]:
    """CPT codes that require authorization from catalog plan + policy overrides."""
    policy = policy or {}
    requires: set[str] = set()
    for cpt in policy.get("requires_auth_for") or []:
        c = str(cpt or "").strip()
        if c:
            requires.add(c)
    plan_id = (policy.get("plan_id") or "").strip()
    carrier_id = (policy.get("carrier_id") or "").strip()
    catalog = load_insurance_catalog()
    for plan in catalog.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        match = False
        if plan_id and (plan.get("plan_id") or "").strip() == plan_id:
            match = True
        elif carrier_id and (plan.get("carrier_id") or "").strip() == carrier_id and not plan_id:
            match = True
        if match:
            for cpt in plan.get("requires_auth_for") or []:
                c = str(cpt or "").strip()
                if c:
                    requires.add(c)
    return requires


def _policy_for_claim(patient_root: str, st: dict) -> dict:
    snap = st.get("snapshot") or {}
    ps = snap.get("policy_snapshot") or {}
    policy_id = (ps.get("policy_id") or st.get("policy_id") or "").strip()
    merged = dict(ps)
    for p in load_insurance_policies(patient_root).get("policies") or []:
        if (p.get("policy_id") or "").strip() == policy_id:
            merged = {**p, **ps}
            break
    return merged


def _validate_authorizations(
    patient_root: str,
    policy: dict,
    dos: str,
    lines: list[dict],
) -> list[str]:
    warnings: list[str] = []
    auth_db = load_insurance_authorizations(patient_root)
    auths = auth_db.get("authorizations") or []
    requires = _plan_auth_requirements(policy)
    if not requires:
        return warnings
    for ln in lines:
        cpt = (ln.get("cpt") or "").strip()
        if cpt not in requires:
            continue
        auth_no = (ln.get("auth_number") or "").strip()
        if not auth_no:
            warnings.append(f"CPT {cpt} requires authorization but auth_number is blank.")
            continue
        hit = next((a for a in auths if (a.get("auth_number") or "").strip() == auth_no), None)
        if not hit:
            warnings.append(f"CPT {cpt} auth '{auth_no}' not found in insurance_authorizations.")
            continue
        if (hit.get("status") or "").lower() != "active":
            warnings.append(f"Authorization {auth_no} is not active.")
        eff = (hit.get("effective_date") or "").strip()
        exp = (hit.get("expiration_date") or "").strip()
        if eff and dos and dos < eff:
            warnings.append(f"Authorization {auth_no} not effective on DOS {dos}.")
        if exp and dos and dos > exp:
            warnings.append(f"Authorization {auth_no} expired before DOS {dos}.")
        total_units = int(hit.get("total_units_approved") or 0)
        units_used = int(hit.get("units_used") or 0)
        req_units = int(ln.get("units") or 1)
        if total_units and units_used + req_units > total_units:
            warnings.append(
                f"Authorization {auth_no} exceeds approved units "
                f"({units_used + req_units}/{total_units})."
            )
    return warnings


def _snapshot_from_encounter(encounter: dict, *, policy: dict, cob_level: str, claim_frequency_code: str, original_ref_claim_id: str | None) -> dict:
    # billing_engine shadow encounters store diagnosis codes under
    # `diagnosis_pointers` (not `diagnoses`) and provider under `provider`
    # (not `provider_id`). Keep both aliases so claims can be created from
    # shadow/posted snapshots without losing required scrub fields.
    raw_diagnoses = encounter.get("diagnoses") or encounter.get("diagnosis_pointers") or []
    diagnoses = [str(x).strip().upper() for x in raw_diagnoses if str(x).strip()]
    lines: list[dict] = []
    for idx, ln in enumerate(encounter.get("lines") or [], start=1):
        cpt = str(ln.get("cpt_code") or ln.get("cpt") or "").strip()
        mod = str(ln.get("modifier_1") or "").strip()
        units = int(ln.get("units") or 1)
        charge = round(float(_line_charge(ln)), 2)
        dx_ptr = _dx_ptr_indices_for_line(diagnoses, ln)
        lines.append(
            {
                "line_id": f"ln{idx}",
                "cpt": cpt,
                "modifiers": [mod] if mod else [],
                "units": units,
                "charge": charge,
                "dx_ptr": dx_ptr,
                "auth_number": "",
            }
        )
    return {
        "claim_frequency_code": claim_frequency_code or "1",
        "original_ref_claim_id": original_ref_claim_id,
        "cob_level": cob_level or "primary",
        "date_of_service": encounter.get("date_of_service") or "",
        "provider_id": encounter.get("provider_id") or encounter.get("provider") or "",
        "place_of_service": encounter.get("place_of_service") or "11",
        "diagnoses": diagnoses,
        "lines": lines,
        "encounter_snapshot": {
            "exam_name": encounter.get("exam_name") or "",
            "exam_path": encounter.get("exam_path") or "",
        },
        "policy_snapshot": {
            "policy_id": policy.get("policy_id") or "",
            "order": policy.get("order") or "",
            "carrier_id": policy.get("carrier_id") or "",
            "carrier_name": policy.get("carrier_name") or "",
            "member_id": policy.get("member_id") or "",
            "group_number": policy.get("group_number") or "",
        },
    }


def create_claim_from_encounter(
    *,
    patient_root: str,
    patient_id: str,
    patient_name: str,
    encounter: dict,
    recorded_by: str = "",
    policy_id: str = "",
    cob_level: str = "primary",
    claim_frequency_code: str = "1",
    original_ref_claim_id: str | None = None,
) -> dict:
    ensure_insurance_files(patient_root, patient_id=patient_id)
    pol_db = _active_policies_snapshot(patient_root, patient_id=patient_id)
    policies = pol_db.get("policies") or []
    if not policies:
        # Fallback: billing-side policy snapshot may already exist even when
        # insurance_data has not been populated yet (new installs / imports).
        policies = (load_insurance_policies(patient_root, patient_id=patient_id).get("policies") or [])
    policy = None
    if policy_id:
        policy = next((p for p in policies if p.get("policy_id") == policy_id), None)
    if policy is None:
        policy = _primary_policy(policies)
    if policy is None:
        raise ValueError("No active insurance policy found. Add policy first.")

    claim_id = _claim_id()
    snapshot = _snapshot_from_encounter(
        encounter,
        policy=policy,
        cob_level=cob_level,
        claim_frequency_code=claim_frequency_code,
        original_ref_claim_id=original_ref_claim_id,
    )
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_created",
        "claim_id": claim_id,
        "encounter_id": encounter.get("encounter_id") or "",
        "policy_id": policy.get("policy_id") or "",
        "payer_id": policy.get("carrier_id") or "",
        "patient_id": patient_id or "",
        "patient_name": patient_name or "",
        "status_after": "draft",
        "snapshot": snapshot,
        "recorded_by": recorded_by or "",
    }
    append_claim_event_atomic(patient_root, event)
    return event


def refresh_claim_snapshot_from_encounter(
    *,
    patient_root: str,
    claim_id: str,
    encounter: dict,
    recorded_by: str = "",
) -> dict:
    """Rebuild claim snapshot from the current visit (fixes stale drafts)."""
    st = get_claim_state(patient_root, claim_id)
    if not st:
        raise ValueError("Claim not found.")
    if (st.get("status") or "") not in ("draft", "ready_to_submit"):
        raise ValueError("Only draft or ready-to-submit claims can be refreshed from the visit.")
    snap = st.get("snapshot") or {}
    policy_snap = snap.get("policy_snapshot") or {}
    policy = {
        "policy_id": policy_snap.get("policy_id") or st.get("policy_id") or "",
        "order": policy_snap.get("order") or "",
        "carrier_id": policy_snap.get("carrier_id") or st.get("payer_id") or "",
        "carrier_name": policy_snap.get("carrier_name") or "",
        "member_id": policy_snap.get("member_id") or "",
        "group_number": policy_snap.get("group_number") or "",
    }
    new_snapshot = _snapshot_from_encounter(
        encounter,
        policy=policy,
        cob_level=snap.get("cob_level") or "primary",
        claim_frequency_code=snap.get("claim_frequency_code") or "1",
        original_ref_claim_id=snap.get("original_ref_claim_id"),
    )
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_snapshot_refreshed",
        "claim_id": claim_id,
        "snapshot": new_snapshot,
        "recorded_by": recorded_by or "",
    }
    append_claim_event_atomic(patient_root, event)
    return event


def derive_claim_states(patient_root: str) -> list[dict]:
    ensure_insurance_files(patient_root)
    claims = load_insurance_claims(patient_root).get("events") or []
    postings = load_insurance_postings(patient_root).get("events") or []
    # Preserve append order from the ledger files. Timestamps are second-level,
    # so sorting by timestamp/event_id can reorder same-second transitions and
    # incorrectly regress status (e.g., submitted -> draft).
    claims_sorted = list(claims)
    postings_sorted = list(postings)

    by_claim: dict[str, dict[str, Any]] = {}
    for e in claims_sorted:
        cid = e.get("claim_id") or ""
        if not cid:
            continue
        state = by_claim.setdefault(
            cid,
            {
                "claim_id": cid,
                "encounter_id": "",
                "policy_id": "",
                "payer_id": "",
                "patient_id": "",
                "patient_name": "",
                "status": "draft",
                "snapshot": {},
                "created_at": "",
                "updated_at": "",
                "warnings": [],
                "totals": {
                    "charged": 0.0,
                    "allowed": 0.0,
                    "payer_paid": 0.0,
                    "patient_resp": 0.0,
                    "adjustments": 0.0,
                    "outstanding_payer_balance": 0.0,
                },
            },
        )
        state["encounter_id"] = e.get("encounter_id") or state["encounter_id"]
        state["policy_id"] = e.get("policy_id") or state["policy_id"]
        state["payer_id"] = e.get("payer_id") or state["payer_id"]
        state["patient_id"] = e.get("patient_id") or state["patient_id"]
        state["patient_name"] = e.get("patient_name") or state["patient_name"]
        if e.get("type") == "claim_created":
            state["snapshot"] = e.get("snapshot") or {}
            state["created_at"] = e.get("timestamp") or state["created_at"]
            state["status"] = "draft"
        elif e.get("type") == "claim_snapshot_refreshed":
            state["snapshot"] = e.get("snapshot") or state.get("snapshot") or {}
        if e.get("type") in ("claim_status_changed", "claim_submitted", "claim_created"):
            state["status"] = e.get("status_after") or state["status"]
        state["updated_at"] = e.get("timestamp") or state["updated_at"]

    for p in postings_sorted:
        cid = p.get("claim_id") or ""
        if cid not in by_claim:
            continue
        st = by_claim[cid]
        tot = st["totals"]
        ptot = p.get("totals") or {}
        tot["charged"] += float(ptot.get("charged") or 0.0)
        tot["allowed"] += float(ptot.get("allowed") or 0.0)
        tot["payer_paid"] += float(ptot.get("payer_paid") or 0.0)
        tot["patient_resp"] += float(ptot.get("patient_resp") or 0.0)
        tot["adjustments"] += float(ptot.get("adjustments") or 0.0)
        st["updated_at"] = p.get("timestamp") or st["updated_at"]

    for st in by_claim.values():
        snapshot = st.get("snapshot") or {}
        lines = snapshot.get("lines") or []
        original_charged = round(sum(float(ln.get("charge") or 0.0) for ln in lines), 2)
        # If no posting yet, charged comes from claim lines.
        if st["totals"]["charged"] <= 0.0:
            st["totals"]["charged"] = original_charged
        # Reconciliation equation:
        # charged = payer_paid + patient_resp + adjustments + outstanding_payer_balance
        outstanding = (
            st["totals"]["charged"]
            - st["totals"]["payer_paid"]
            - st["totals"]["patient_resp"]
            - st["totals"]["adjustments"]
        )
        st["totals"]["outstanding_payer_balance"] = round(max(0.0, outstanding), 2)
        st["totals"] = {k: round(float(v or 0.0), 2) for k, v in st["totals"].items()}
    return sorted(by_claim.values(), key=lambda r: (r.get("updated_at") or "", r.get("claim_id") or ""), reverse=True)


def get_claim_state(patient_root: str, claim_id: str) -> dict | None:
    for st in derive_claim_states(patient_root):
        if st.get("claim_id") == claim_id:
            return st
    return None


def validate_claim_for_ready(patient_root: str, claim_id: str) -> list[str]:
    st = get_claim_state(patient_root, claim_id)
    if not st:
        return ["Claim not found."]
    snap = st.get("snapshot") or {}
    lines = snap.get("lines") or []
    diagnoses = [str(x or "").strip().upper() for x in (snap.get("diagnoses") or []) if str(x or "").strip()]
    warnings: list[str] = []

    if not lines:
        warnings.append("Claim has no service lines.")
    if not snap.get("provider_id"):
        warnings.append("Provider is missing.")
    if not snap.get("place_of_service"):
        warnings.append("Place of service is missing.")
    if not diagnoses:
        warnings.append("No diagnosis codes.")
    warnings.extend(_validate_dx_codes(diagnoses))
    warnings.extend(_validate_dx_ptrs(lines, diagnoses))

    policy = _policy_for_claim(patient_root, st)
    warnings.extend(
        _validate_authorizations(
            patient_root,
            policy=policy,
            dos=snap.get("date_of_service") or "",
            lines=lines,
        )
    )
    freq = str(snap.get("claim_frequency_code") or "1").strip()
    if freq == "7" and not (snap.get("original_ref_claim_id") or "").strip():
        warnings.append("Correction claim (freq 7) missing original reference claim ID.")
    if freq == "8" and not (snap.get("original_ref_claim_id") or "").strip():
        warnings.append("Void claim (freq 8) missing original reference claim ID.")
    return warnings


def change_claim_status(
    *,
    patient_root: str,
    claim_id: str,
    to_status: str,
    recorded_by: str = "",
    reason: str = "",
) -> dict:
    st = get_claim_state(patient_root, claim_id)
    if not st:
        raise ValueError("Claim not found.")
    from_status = st.get("status") or "draft"
    to_status = (to_status or "").strip().lower()
    if to_status not in CLAIM_STATUSES:
        raise ValueError(f"Unknown status: {to_status}")
    allowed = STATUS_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(f"Cannot move claim from {from_status} to {to_status}.")
    if to_status == "ready_to_submit":
        warnings = validate_claim_for_ready(patient_root, claim_id)
        blocking = [w for w in warnings if w]
        if blocking:
            raise ValueError("Claim scrub failed:\n- " + "\n- ".join(blocking))

    ev_type = "claim_submitted" if to_status == "submitted" else "claim_status_changed"
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": ev_type,
        "claim_id": claim_id,
        "from_status": from_status,
        "to_status": to_status,
        "status_after": to_status,
        "reason": reason or "",
        "recorded_by": recorded_by or "",
    }
    append_claim_event_atomic(patient_root, event)
    return event


def _normalize_line_postings_for_claim(claim_state: dict, payer_paid: float, patient_resp: float) -> list[dict]:
    snap = claim_state.get("snapshot") or {}
    lines = snap.get("lines") or []
    total_charged = sum(float(ln.get("charge") or 0.0) for ln in lines) or 0.0
    out: list[dict] = []
    if not lines:
        return out
    for idx, ln in enumerate(lines):
        charged = round(float(ln.get("charge") or 0.0), 2)
        if idx == len(lines) - 1:
            # absorb rounding residue
            paid_so_far = round(sum(float(x.get("payer_paid") or 0.0) for x in out), 2)
            pat_so_far = round(sum(float(x.get("patient_resp") or 0.0) for x in out), 2)
            ln_paid = round(payer_paid - paid_so_far, 2)
            ln_pat = round(patient_resp - pat_so_far, 2)
        else:
            ratio = (charged / total_charged) if total_charged > 0 else (1.0 / len(lines))
            ln_paid = round(payer_paid * ratio, 2)
            ln_pat = round(patient_resp * ratio, 2)
        allowed = round(ln_paid + ln_pat, 2)
        adjustment_amt = round(allowed - charged, 2)
        adjustments = []
        if abs(adjustment_amt) > 0.0001:
            adjustments.append({"type": "contractual", "carc": "45", "amount": adjustment_amt})
        out.append(
            {
                "line_id": ln.get("line_id") or "",
                "charged": charged,
                "allowed": allowed,
                "payer_paid": ln_paid,
                "patient_resp": ln_pat,
                "adjustments": adjustments,
                "denial_carc": None,
                "remark_rarc": None,
            }
        )
    return out


def _post_status_after(posting_event: dict) -> str:
    t = posting_event.get("totals") or {}
    charged = float(t.get("charged") or 0.0)
    payer = float(t.get("payer_paid") or 0.0)
    pat = float(t.get("patient_resp") or 0.0)
    adj = float(t.get("adjustments") or 0.0)
    outstanding = round(charged - payer - pat - adj, 2)
    if payer <= 0.0 and pat <= 0.0:
        return "denied"
    if outstanding <= 0.01:
        if pat <= 0.01:
            return "paid_full"
        return "paid_partial"
    return "adjudicated"


def _consume_auth_units(
    patient_root: str,
    *,
    claim_id: str,
    line_postings: list[dict],
    claim_state: dict,
) -> None:
    snap = claim_state.get("snapshot") or {}
    lines_by_id = {str(ln.get("line_id") or ""): ln for ln in (snap.get("lines") or [])}
    auth_db = load_insurance_authorizations(patient_root)
    auths = auth_db.get("authorizations") or []
    changed = False
    for lp in line_postings:
        line_id = str(lp.get("line_id") or "")
        ln = lines_by_id.get(line_id) or {}
        auth_number = (ln.get("auth_number") or "").strip()
        if not auth_number:
            continue
        units = int(ln.get("units") or 1)
        for a in auths:
            if (a.get("auth_number") or "").strip() != auth_number:
                continue
            a["units_used"] = int(a.get("units_used") or 0) + units
            linked = a.get("linked_claims") or []
            if claim_id not in linked:
                linked.append(claim_id)
                a["linked_claims"] = linked
            changed = True
            break
    if changed:
        save_insurance_authorizations(patient_root, auth_db, patient_id=auth_db.get("patient_id") or "")


def _trigger_secondary_claim_if_needed(
    patient_root: str,
    *,
    claim_state: dict,
    posting_event: dict,
    recorded_by: str,
) -> dict | None:
    snap = claim_state.get("snapshot") or {}
    if (snap.get("cob_level") or "primary") != "primary":
        return None
    patient_resp = float((posting_event.get("totals") or {}).get("patient_resp") or 0.0)
    if patient_resp <= 0.01:
        return None

    pols = load_insurance_policies(patient_root).get("policies") or []
    sec = _secondary_policy(pols, claim_state.get("policy_id") or "")
    if not sec:
        return None

    new_claim_id = _claim_id()
    sec_snapshot = dict(snap)
    sec_snapshot["cob_level"] = "secondary"
    sec_snapshot["claim_frequency_code"] = "1"
    sec_snapshot["original_ref_claim_id"] = claim_state.get("claim_id") or ""
    sec_snapshot["primary_adjudication_ref"] = {
        "claim_id": claim_state.get("claim_id") or "",
        "payer_id": claim_state.get("payer_id") or "",
        "totals": posting_event.get("totals") or {},
    }
    evt_created = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_created",
        "claim_id": new_claim_id,
        "encounter_id": claim_state.get("encounter_id") or "",
        "policy_id": sec.get("policy_id") or "",
        "payer_id": sec.get("carrier_id") or "",
        "patient_id": claim_state.get("patient_id") or "",
        "patient_name": claim_state.get("patient_name") or "",
        "status_after": "draft",
        "snapshot": sec_snapshot,
        "recorded_by": recorded_by or "",
        "auto_generated": True,
    }
    append_claim_event_atomic(patient_root, evt_created)
    evt_ready = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_status_changed",
        "claim_id": new_claim_id,
        "from_status": "draft",
        "to_status": "ready_to_submit",
        "status_after": "ready_to_submit",
        "reason": "Auto-routed from primary adjudication (COB).",
        "recorded_by": recorded_by or "",
        "auto_generated": True,
    }
    append_claim_event_atomic(patient_root, evt_ready)
    return {"created_event": evt_created, "ready_event": evt_ready}


def post_payer_payment(
    *,
    patient_root: str,
    claim_id: str,
    payer_id: str,
    posting_date: str,
    deposit_ref: str,
    payer_paid: float,
    patient_resp: float = 0.0,
    recorded_by: str = "",
    line_postings: list[dict] | None = None,
    denial_carc: str = "",
) -> dict:
    st = get_claim_state(patient_root, claim_id)
    if not st:
        raise ValueError("Claim not found.")
    if st.get("status") in ("draft", "ready_to_submit"):
        raise ValueError("Claim must be submitted before posting payer adjudication.")

    if denial_carc:
        snap = st.get("snapshot") or {}
        lp = []
        for ln in snap.get("lines") or []:
            charged = round(float(ln.get("charge") or 0.0), 2)
            lp.append(
                {
                    "line_id": ln.get("line_id") or "",
                    "charged": charged,
                    "allowed": 0.0,
                    "payer_paid": 0.0,
                    "patient_resp": 0.0,
                    "adjustments": [{"type": "denial", "carc": denial_carc, "amount": -charged}],
                    "denial_carc": denial_carc,
                    "remark_rarc": None,
                }
            )
        payer_paid = 0.0
        patient_resp = 0.0
    else:
        lp = line_postings or _normalize_line_postings_for_claim(
            st, payer_paid=float(payer_paid or 0.0), patient_resp=float(patient_resp or 0.0)
        )
    totals = {
        "charged": round(sum(float(x.get("charged") or 0.0) for x in lp), 2),
        "allowed": round(sum(float(x.get("allowed") or 0.0) for x in lp), 2),
        "payer_paid": round(sum(float(x.get("payer_paid") or 0.0) for x in lp), 2),
        "patient_resp": round(sum(float(x.get("patient_resp") or 0.0) for x in lp), 2),
        "adjustments": round(
            sum(float(adj.get("amount") or 0.0) for x in lp for adj in (x.get("adjustments") or [])),
            2,
        ),
    }
    posting = {
        "event_id": _event_id("post"),
        "timestamp": _now_iso(),
        "type": "payer_posting",
        "claim_id": claim_id,
        "posting_date": posting_date or "",
        "deposit_ref": deposit_ref or "",
        "payer_id": payer_id or st.get("payer_id") or "",
        "line_postings": lp,
        "totals": totals,
        "recorded_by": recorded_by or "",
    }
    append_posting_event_atomic(patient_root, posting)
    _consume_auth_units(patient_root, claim_id=claim_id, line_postings=lp, claim_state=st)

    current = get_claim_state(patient_root, claim_id) or st
    from_status = current.get("status") or "pending"
    to_status = _post_status_after(posting)
    if to_status in STATUS_TRANSITIONS.get(from_status, set()):
        ev_status = {
            "event_id": _event_id("evt"),
            "timestamp": _now_iso(),
            "type": "claim_status_changed",
            "claim_id": claim_id,
            "from_status": from_status,
            "to_status": to_status,
            "status_after": to_status,
            "reason": "Auto-updated from payer posting.",
            "recorded_by": recorded_by or "",
            "auto_generated": True,
        }
        append_claim_event_atomic(patient_root, ev_status)

    sec = _trigger_secondary_claim_if_needed(
        patient_root,
        claim_state=current,
        posting_event=posting,
        recorded_by=recorded_by,
    )
    out = {"posting_event": posting}
    if sec:
        out["secondary_claim"] = sec
    return out


def claim_events(patient_root: str, claim_id: str) -> list[dict]:
    rows = [e for e in (load_insurance_claims(patient_root).get("events") or []) if (e.get("claim_id") or "") == claim_id]
    return sorted(rows, key=lambda e: (e.get("timestamp") or "", e.get("event_id") or ""))


def claim_postings(patient_root: str, claim_id: str) -> list[dict]:
    rows = [
        p
        for p in (load_insurance_postings(patient_root).get("events") or [])
        if (p.get("claim_id") or "") == claim_id
    ]
    return sorted(rows, key=lambda p: (p.get("timestamp") or "", p.get("event_id") or ""))


def create_correction_or_void_claim(
    *,
    patient_root: str,
    original_claim_id: str,
    claim_frequency_code: str,
    recorded_by: str = "",
    void_original: bool = True,
) -> dict:
    """
    Create a replacement (7) or void (8) claim from an adjudicated/submitted original.
    When freq is 8 and void_original is True, the original claim moves to voided.
    """
    freq = (claim_frequency_code or "").strip()
    if freq not in ("7", "8"):
        raise ValueError("Correction/void claims must use frequency code 7 or 8.")
    orig = get_claim_state(patient_root, original_claim_id)
    if not orig:
        raise ValueError("Original claim not found.")
    orig_status = (orig.get("status") or "").lower()
    if orig_status in ("draft", "ready_to_submit", "voided"):
        raise ValueError(f"Cannot derive claim from status '{orig_status}'.")
    snap = copy.deepcopy(orig.get("snapshot") or {})
    snap["claim_frequency_code"] = freq
    snap["original_ref_claim_id"] = original_claim_id
    policy = snap.get("policy_snapshot") or {}
    claim_id = _claim_id()
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_created",
        "claim_id": claim_id,
        "encounter_id": orig.get("encounter_id") or "",
        "policy_id": policy.get("policy_id") or orig.get("policy_id") or "",
        "payer_id": policy.get("carrier_id") or orig.get("payer_id") or "",
        "patient_id": orig.get("patient_id") or "",
        "patient_name": orig.get("patient_name") or "",
        "status_after": "draft",
        "snapshot": snap,
        "recorded_by": recorded_by or "",
        "derived_from_claim_id": original_claim_id,
        "claim_frequency_code": freq,
    }
    append_claim_event_atomic(patient_root, event)
    if freq == "8" and void_original and orig_status != "voided":
        change_claim_status(
            patient_root=patient_root,
            claim_id=original_claim_id,
            to_status="voided",
            recorded_by=recorded_by,
            reason=f"Voided by replacement claim {claim_id} (freq 8).",
        )
    return event


def mark_claim_denied(
    *,
    patient_root: str,
    claim_id: str,
    recorded_by: str = "",
    reason: str = "",
) -> dict:
    return change_claim_status(
        patient_root=patient_root,
        claim_id=claim_id,
        to_status="denied",
        recorded_by=recorded_by,
        reason=reason or "Marked denied for follow-up.",
    )


def appeal_claim(
    *,
    patient_root: str,
    claim_id: str,
    recorded_by: str = "",
    reason: str = "",
) -> dict:
    return change_claim_status(
        patient_root=patient_root,
        claim_id=claim_id,
        to_status="appealed",
        recorded_by=recorded_by,
        reason=reason or "Appeal filed.",
    )


DENIAL_QUEUE_STATUSES = frozenset({"denied", "rejected", "appealed"})


def denial_appeal_queue(patient_root: str) -> list[dict]:
    states = derive_claim_states(patient_root)
    rows: list[dict] = []
    for st in states:
        status = (st.get("status") or "").lower()
        if status not in DENIAL_QUEUE_STATUSES:
            continue
        snap = st.get("snapshot") or {}
        pol = snap.get("policy_snapshot") or {}
        rows.append(
            {
                **st,
                "payer_name": pol.get("carrier_name") or st.get("payer_id") or "",
                "dos": snap.get("date_of_service") or "",
                "patient_resp": float((st.get("totals") or {}).get("patient_resp") or 0.0),
            }
        )
    return sorted(rows, key=lambda r: (r.get("dos") or "", r.get("claim_id") or ""), reverse=True)


def _parse_iso_date(s: str) -> date | None:
    text = (s or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _ar_bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    return "90+"


AR_OPEN_STATUSES = frozenset(
    {
        "submitted",
        "payer_acknowledged",
        "pending",
        "adjudicated",
        "paid_partial",
        "denied",
        "appealed",
    }
)


def compute_insurance_ar_aging(patient_root: str) -> dict:
    """
    A/R buckets by days since DOS for open insurance claims.
    Returns summary buckets plus per-claim rows.
    """
    today = date.today()
    states = derive_claim_states(patient_root)
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    rows: list[dict] = []
    for st in states:
        status = (st.get("status") or "").lower()
        if status not in AR_OPEN_STATUSES:
            continue
        snap = st.get("snapshot") or {}
        dos_s = snap.get("date_of_service") or ""
        dos = _parse_iso_date(dos_s)
        age = (today - dos).days if dos else 0
        bucket = _ar_bucket(max(0, age))
        tots = st.get("totals") or {}
        outstanding = float(tots.get("outstanding_payer_balance") or 0.0)
        patient_resp = float(tots.get("patient_resp") or 0.0)
        amount = round(outstanding + patient_resp, 2)
        if amount <= 0.01 and status not in ("denied", "appealed"):
            continue
        buckets[bucket] = round(buckets.get(bucket, 0.0) + amount, 2)
        pol = snap.get("policy_snapshot") or {}
        rows.append(
            {
                "claim_id": st.get("claim_id") or "",
                "status": status,
                "dos": dos_s,
                "age_days": age,
                "bucket": bucket,
                "payer": pol.get("carrier_name") or st.get("payer_id") or "",
                "payer_balance": outstanding,
                "patient_resp": patient_resp,
                "total_ar": amount,
            }
        )
    rows.sort(key=lambda r: (-int(r.get("age_days") or 0), r.get("claim_id") or ""))
    return {
        "as_of": today.isoformat(),
        "buckets": buckets,
        "total_ar": round(sum(buckets.values()), 2),
        "claims": rows,
    }


def build_ar_aging_report_text(patient_root: str, *, patient_name: str = "") -> str:
    data = compute_insurance_ar_aging(patient_root)
    w = 56
    sep = "-" * w
    lines = [
        "INSURANCE A/R AGING REPORT",
        "=" * w,
        f"As of            : {data.get('as_of') or '—'}",
    ]
    if patient_name:
        lines.append(f"Patient           : {patient_name}")
    lines.extend(["", "SUMMARY BY AGE", sep])
    buckets = data.get("buckets") or {}
    for key in ("0-30", "31-60", "61-90", "90+"):
        lines.append(f"  {key:>6} days : ${float(buckets.get(key) or 0):>10,.2f}")
    lines.append(f"  {'TOTAL':>6}      : ${float(data.get('total_ar') or 0):>10,.2f}")
    lines.extend(["", "OPEN CLAIMS", sep])
    for row in data.get("claims") or []:
        lines.append(
            f"  {row.get('dos') or '—':10}  {row.get('bucket'):>6}  "
            f"{(row.get('status') or ''):12}  "
            f"${float(row.get('total_ar') or 0):>8,.2f}  "
            f"{row.get('payer') or ''}  {row.get('claim_id') or ''}"
        )
    if not data.get("claims"):
        lines.append("  (no open A/R)")
    return "\n".join(lines)


def collect_insurance_copay(
    *,
    patient_root: str,
    claim_id: str,
    amount: float,
    method: str,
    payment_date: str = "",
    recorded_by: str = "",
) -> dict:
    """
    Collect insurance patient responsibility at the desk.

    * Visit not on cash ledger → posts copay-only charge, then payment.
    * Visit already posted → records payment for copay amount only (partial OK).
    """
    from billing_ledger import (
        is_encounter_posted,
        load_posted_encounter,
        post_insurance_copay_checkout,
        record_payment,
    )

    st = get_claim_state(patient_root, claim_id)
    if not st:
        raise ValueError("Claim not found.")
    outstanding = insurance_copay_outstanding_for_claim(patient_root, claim_id)
    if outstanding <= 0.01:
        raise ValueError("No insurance patient responsibility is outstanding on this claim.")
    pay_amt = round(float(amount or 0), 2)
    if pay_amt <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    if pay_amt > outstanding + 0.01:
        raise ValueError(
            f"Amount ${pay_amt:,.2f} exceeds outstanding copay ${outstanding:,.2f}."
        )

    snap = st.get("snapshot") or {}
    pol = snap.get("policy_snapshot") or {}
    exam_path = (snap.get("encounter_snapshot") or {}).get("exam_path") or ""
    if not exam_path:
        raise ValueError("Claim has no linked visit path. Select the visit and refresh the claim.")
    payer_name = pol.get("carrier_name") or st.get("payer_id") or "Insurance"

    mode = "payment_only"
    posted = None
    if not is_encounter_posted(patient_root, exam_path):
        posted = post_insurance_copay_checkout(
            patient_root=patient_root,
            exam_path=exam_path,
            copay_amount=pay_amt,
            claim_id=claim_id,
            payer_name=payer_name,
            posted_by=recorded_by,
        )
        mode = "copay_checkout"

    enc_id = (posted or load_posted_encounter(patient_root, exam_path) or {}).get("encounter_id") or ""
    pay = record_payment(
        patient_root=patient_root,
        amount=pay_amt,
        method=method,
        payment_date=payment_date,
        encounter_id=enc_id,
        exam_path=exam_path,
        memo=f"Insurance copay · {claim_id}",
        recorded_by=recorded_by,
    )
    link_patient_resp_to_cash(
        patient_root=patient_root,
        claim_id=claim_id,
        exam_path=exam_path,
        amount=pay_amt,
        recorded_by=recorded_by,
    )
    return {
        "mode": mode,
        "posted": posted,
        "payment": pay,
        "amount": pay_amt,
        "outstanding_before": outstanding,
        "outstanding_after": round(max(0.0, outstanding - pay_amt), 2),
    }


def link_patient_resp_to_cash(
    *,
    patient_root: str,
    claim_id: str,
    exam_path: str,
    amount: float,
    recorded_by: str = "",
) -> dict:
    """Record that patient responsibility was routed to cash ledger collection."""
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_patient_resp_linked",
        "claim_id": claim_id,
        "exam_path": exam_path or "",
        "amount": round(float(amount or 0.0), 2),
        "recorded_by": recorded_by or "",
    }
    append_claim_event_atomic(patient_root, event)
    return event


def postable_claims_queue(patient_root: str) -> list[dict]:
    states = derive_claim_states(patient_root)
    return [s for s in states if (s.get("status") or "") in {"pending", "adjudicated", "submitted", "payer_acknowledged", "paid_partial"}]


def _claim_matches_visit(st: dict, *, exam_path: str, encounter_id: str) -> bool:
    snap = st.get("snapshot") or {}
    enc_snap = snap.get("encounter_snapshot") or {}
    if exam_path and (enc_snap.get("exam_path") or "") == exam_path:
        return True
    if encounter_id and (st.get("encounter_id") or "") == encounter_id:
        return True
    return False


def patient_resp_collected_for_claim(patient_root: str, claim_id: str, *, exam_path: str = "") -> float:
    """Amount of patient responsibility already routed/collected for a claim."""
    linked = 0.0
    for e in claim_events(patient_root, claim_id):
        if e.get("type") == "claim_patient_resp_linked":
            linked += float(e.get("amount") or 0.0)
    if exam_path:
        try:
            from billing_ledger import load_cash_ledger, load_posted_encounter

            posted = load_posted_encounter(patient_root, exam_path)
            if posted and posted.get("insurance_copay_checkout"):
                enc_id = posted.get("encounter_id") or ""
                exam_resolved = str(Path(exam_path).resolve())
                paid = 0.0
                for ent in load_cash_ledger(patient_root).get("entries") or []:
                    if not isinstance(ent, dict) or ent.get("type") != "payment":
                        continue
                    if ent.get("encounter_id") == enc_id or str(ent.get("exam_path") or "") == exam_resolved:
                        paid += float(ent.get("amount") or 0.0)
                if paid > 0:
                    return round(paid, 2)
        except Exception:
            pass
    return round(linked, 2)


def insurance_copay_outstanding_for_claim(patient_root: str, claim_id: str) -> float:
    st = get_claim_state(patient_root, claim_id)
    if not st:
        return 0.0
    assigned = float((st.get("totals") or {}).get("patient_resp") or 0.0)
    if assigned <= 0.0:
        return 0.0
    snap = st.get("snapshot") or {}
    exam_path = (snap.get("encounter_snapshot") or {}).get("exam_path") or ""
    collected = patient_resp_collected_for_claim(patient_root, claim_id, exam_path=exam_path)
    return round(max(0.0, assigned - collected), 2)


def insurance_balance_for_visit(
    patient_root: str,
    *,
    exam_path: str = "",
    encounter_id: str = "",
) -> dict:
    """
    Patient-responsibility balance for one visit from insurance postings.
    Returns assigned, collected, outstanding, and related claim_ids.
    """
    assigned = 0.0
    collected = 0.0
    claim_ids: list[str] = []
    for st in derive_claim_states(patient_root):
        if not _claim_matches_visit(st, exam_path=exam_path, encounter_id=encounter_id):
            continue
        pr = float((st.get("totals") or {}).get("patient_resp") or 0.0)
        if pr <= 0.0:
            continue
        cid = st.get("claim_id") or ""
        claim_ids.append(cid)
        assigned += pr
        collected += patient_resp_collected_for_claim(
            patient_root, cid, exam_path=exam_path or ""
        )
    assigned = round(assigned, 2)
    collected = round(min(collected, assigned), 2)
    return {
        "patient_resp_assigned": assigned,
        "patient_resp_collected": collected,
        "patient_resp_outstanding": round(max(0.0, assigned - collected), 2),
        "claim_ids": claim_ids,
    }


def insurance_patient_balance_total(patient_root: str) -> float:
    """Outstanding insurance patient responsibility across all open claims."""
    total = 0.0
    skip_status = frozenset({"voided", "closed", "draft", "ready_to_submit"})
    for st in derive_claim_states(patient_root):
        status = (st.get("status") or "").lower()
        if status in skip_status:
            continue
        pr = float((st.get("totals") or {}).get("patient_resp") or 0.0)
        if pr <= 0.0:
            continue
        cid = st.get("claim_id") or ""
        snap = st.get("snapshot") or {}
        exam_path = (snap.get("encounter_snapshot") or {}).get("exam_path") or ""
        collected = patient_resp_collected_for_claim(patient_root, cid, exam_path=exam_path)
        total += max(0.0, pr - collected)
    return round(total, 2)


def suggest_auth_number_for_cpt(patient_root: str, cpt: str, payer_id: str = "") -> str:
    """Best-effort auth # for a CPT from active authorizations."""
    cpt = (cpt or "").strip()
    payer_id = (payer_id or "").strip()
    auths = load_insurance_authorizations(patient_root).get("authorizations") or []
    for a in auths:
        if (a.get("status") or "").lower() != "active":
            continue
        if payer_id and (a.get("payer_id") or "").strip() not in ("", payer_id):
            continue
        allowed = a.get("allowed_cpts") or []
        if allowed and cpt not in allowed:
            continue
        return (a.get("auth_number") or "").strip()
    return ""


def update_claim_line_auth_numbers(
    *,
    patient_root: str,
    claim_id: str,
    auth_by_line_id: dict[str, str],
    recorded_by: str = "",
) -> dict:
    st = get_claim_state(patient_root, claim_id)
    if not st:
        raise ValueError("Claim not found.")
    if (st.get("status") or "") not in ("draft", "ready_to_submit"):
        raise ValueError("Auth numbers can only be edited on draft or ready-to-submit claims.")
    snap = copy.deepcopy(st.get("snapshot") or {})
    for ln in snap.get("lines") or []:
        lid = str(ln.get("line_id") or "")
        if lid in auth_by_line_id:
            ln["auth_number"] = (auth_by_line_id[lid] or "").strip()
    event = {
        "event_id": _event_id("evt"),
        "timestamp": _now_iso(),
        "type": "claim_snapshot_refreshed",
        "claim_id": claim_id,
        "snapshot": snap,
        "recorded_by": recorded_by or "",
        "reason": "Updated line authorization numbers.",
    }
    append_claim_event_atomic(patient_root, event)
    return event


__all__ = [
    "AR_OPEN_STATUSES",
    "CLAIM_STATUSES",
    "DENIAL_QUEUE_STATUSES",
    "STATUS_TRANSITIONS",
    "appeal_claim",
    "build_ar_aging_report_text",
    "change_claim_status",
    "claim_events",
    "claim_postings",
    "collect_insurance_copay",
    "compute_insurance_ar_aging",
    "create_claim_from_encounter",
    "create_correction_or_void_claim",
    "denial_appeal_queue",
    "derive_claim_states",
    "get_claim_state",
    "insurance_balance_for_visit",
    "insurance_copay_outstanding_for_claim",
    "insurance_patient_balance_total",
    "link_patient_resp_to_cash",
    "mark_claim_denied",
    "post_payer_payment",
    "postable_claims_queue",
    "refresh_claim_snapshot_from_encounter",
    "suggest_auth_number_for_cpt",
    "update_claim_line_auth_numbers",
    "validate_claim_for_ready",
]

