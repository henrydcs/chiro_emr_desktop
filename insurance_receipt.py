# insurance_receipt.py — Insurance EOB/remittance text + save helpers.
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from config import CLINIC_ADDR, CLINIC_NAME, CLINIC_PHONE_FAX
from insurance_billing_storage import load_carc_rarc_codes, load_insurance_postings
from insurance_engine import claim_postings, get_claim_state
from billing_receipt import save_receipt_file


_FREQ_LABELS = {
    "1": "Original",
    "7": "Replacement / correction",
    "8": "Void of prior claim",
}


def _carc_label(code: str | None) -> str:
    if not code:
        return ""
    codes = load_carc_rarc_codes().get("carc") or {}
    desc = codes.get(str(code).strip()) or ""
    return f"{code} — {desc}" if desc else str(code)


def _dx_labels(diagnoses: list[str], ptrs: list) -> str:
    out: list[str] = []
    for ptr in ptrs or []:
        s = str(ptr or "").strip()
        if s.isdigit():
            idx = int(s) - 1
            if 0 <= idx < len(diagnoses):
                out.append(diagnoses[idx])
                continue
        out.append(s)
    return ", ".join(out) if out else "—"


def build_insurance_claim_summary_text(
    *,
    patient_name: str,
    claim_state: dict,
    postings: list[dict] | None = None,
) -> str:
    """Plain-text claim summary for Document preview (draft through adjudicated)."""
    snap = claim_state.get("snapshot") or {}
    pol = snap.get("policy_snapshot") or {}
    tots = claim_state.get("totals") or {}
    lines = snap.get("lines") or []
    diagnoses = snap.get("diagnoses") or []
    postings = postings if postings is not None else []

    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()
    w = 56
    sep = "-" * w
    out: list[str] = [
        clinic,
        (CLINIC_ADDR or "").strip(),
        (CLINIC_PHONE_FAX or "").strip(),
        "",
        "INSURANCE CLAIM SUMMARY",
        "=" * w,
        f"Patient          : {patient_name}",
        f"Claim ID         : {claim_state.get('claim_id') or '—'}",
        f"Status           : {(claim_state.get('status') or '—').replace('_', ' ').title()}",
        f"COB level        : {(snap.get('cob_level') or 'primary').title()}",
        f"Frequency        : {_FREQ_LABELS.get(str(snap.get('claim_frequency_code') or '1'), 'Original')}",
    ]
    ref = snap.get("original_ref_claim_id") or ""
    if ref:
        out.append(f"Replaces claim   : {ref}")
    out.extend(
        [
            f"Payer            : {pol.get('carrier_name') or claim_state.get('payer_id') or '—'}",
            f"Member ID        : {pol.get('member_id') or '—'}",
            f"Date of service  : {snap.get('date_of_service') or '—'}",
            f"Provider         : {snap.get('provider_id') or '—'}",
            f"Place of service : {snap.get('place_of_service') or '—'}",
            "",
            "DIAGNOSES",
            sep,
        ]
    )
    if diagnoses:
        for i, dx in enumerate(diagnoses, start=1):
            out.append(f"  {i}. {dx}")
    else:
        out.append("  (none)")
    out.extend(["", "SERVICE LINES", sep])
    for ln in lines:
        mods = ",".join(ln.get("modifiers") or []) or ""
        mod_s = f" ({mods})" if mods else ""
        dxs = _dx_labels(diagnoses, ln.get("dx_ptr") or [])
        auth = (ln.get("auth_number") or "").strip()
        auth_s = f"  Auth: {auth}" if auth else ""
        out.append(
            f"  {ln.get('cpt') or '—'}{mod_s}  "
            f"x{int(ln.get('units') or 1)}  "
            f"${float(ln.get('charge') or 0):,.2f}  DX: {dxs}{auth_s}"
        )
    out.extend(
        [
            "",
            "TOTALS",
            sep,
            f"  Charged              : ${float(tots.get('charged') or 0):>10,.2f}",
            f"  Allowed              : ${float(tots.get('allowed') or 0):>10,.2f}",
            f"  Payer paid           : ${float(tots.get('payer_paid') or 0):>10,.2f}",
            f"  Patient responsibility: ${float(tots.get('patient_resp') or 0):>10,.2f}",
            f"  Adjustments          : ${float(tots.get('adjustments') or 0):>10,.2f}",
            f"  Payer balance        : ${float(tots.get('outstanding_payer_balance') or 0):>10,.2f}",
        ]
    )
    if postings:
        out.extend(["", "PAYER POSTINGS", sep])
        for p in postings:
            pt = p.get("totals") or {}
            out.append(
                f"  {p.get('posting_date') or p.get('timestamp', '')[:10]}  "
                f"paid ${float(pt.get('payer_paid') or 0):,.2f}  "
                f"pat resp ${float(pt.get('patient_resp') or 0):,.2f}  "
                f"ref {p.get('deposit_ref') or '—'}"
            )
    out.append("")
    out.append("Use Post payer after Submit to record remittance (EOB).")
    return "\n".join(out)


def build_insurance_eob_text(
    *,
    patient_name: str,
    claim_state: dict,
    posting: dict,
) -> str:
    """Remittance / EOB-style text after payer posting."""
    snap = claim_state.get("snapshot") or {}
    pol = snap.get("policy_snapshot") or {}
    tots = posting.get("totals") or {}
    line_posts = posting.get("line_postings") or []
    lines_by_id = {str(ln.get("line_id") or ""): ln for ln in (snap.get("lines") or [])}
    diagnoses = snap.get("diagnoses") or []

    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()
    w = 56
    sep = "-" * w
    out: list[str] = [
        clinic,
        (CLINIC_ADDR or "").strip(),
        (CLINIC_PHONE_FAX or "").strip(),
        "",
        "INSURANCE REMITTANCE / EOB",
        "=" * w,
        f"Patient          : {patient_name}",
        f"Claim ID         : {claim_state.get('claim_id') or '—'}",
        f"Payer            : {pol.get('carrier_name') or posting.get('payer_id') or '—'}",
        f"Posting date     : {posting.get('posting_date') or '—'}",
        f"Deposit / check  : {posting.get('deposit_ref') or '—'}",
        f"Date of service  : {snap.get('date_of_service') or '—'}",
        "",
        "LINE ADJUDICATION",
        sep,
    ]
    for lp in line_posts:
        lid = str(lp.get("line_id") or "")
        ln = lines_by_id.get(lid) or {}
        cpt = ln.get("cpt") or "—"
        carc = lp.get("denial_carc")
        denial = f"  DENIED ({_carc_label(carc)})" if carc else ""
        out.append(
            f"  {cpt}  charged ${float(lp.get('charged') or 0):,.2f}  "
            f"allowed ${float(lp.get('allowed') or 0):,.2f}  "
            f"payer ${float(lp.get('payer_paid') or 0):,.2f}  "
            f"patient ${float(lp.get('patient_resp') or 0):,.2f}{denial}"
        )
        for adj in lp.get("adjustments") or []:
            out.append(
                f"      adj ${float(adj.get('amount') or 0):,.2f}  "
                f"CARC {_carc_label(adj.get('carc'))}"
            )
    out.extend(
        [
            "",
            "REMITTANCE TOTALS",
            sep,
            f"  Payer paid           : ${float(tots.get('payer_paid') or 0):>10,.2f}",
            f"  Patient responsibility: ${float(tots.get('patient_resp') or 0):>10,.2f}",
            f"  Contractual adj.     : ${float(tots.get('adjustments') or 0):>10,.2f}",
            "",
            "Collect patient responsibility on Cash checkout when applicable.",
        ]
    )
    return "\n".join(out)


def save_insurance_eob_receipt(
    patient_root: str | Path,
    *,
    patient_name: str,
    claim_state: dict,
    posting: dict,
) -> Path:
    text = build_insurance_eob_text(
        patient_name=patient_name,
        claim_state=claim_state,
        posting=posting,
    )
    claim_id = (claim_state.get("claim_id") or "claim").strip()
    return save_receipt_file(
        patient_root,
        text,
        prefix="insurance_eob",
        subfolder="insurance",
        unique_key=_safe_claim_key(claim_id),
    )


def save_insurance_claim_summary_receipt(
    patient_root: str | Path,
    *,
    patient_name: str,
    claim_state: dict,
) -> Path:
    cid = claim_state.get("claim_id") or ""
    postings = claim_postings(patient_root, cid) if cid else []
    text = build_insurance_claim_summary_text(
        patient_name=patient_name,
        claim_state=claim_state,
        postings=postings,
    )
    return save_receipt_file(
        patient_root,
        text,
        prefix="insurance_claim",
        subfolder="insurance",
        unique_key=_safe_claim_key(cid),
    )


def _safe_claim_key(claim_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (claim_id or "").strip())


def build_insurance_copay_receipt_text(
    *,
    patient_name: str,
    claim_state: dict,
    amount: float,
    method: str,
    payment_date: str = "",
) -> str:
    snap = claim_state.get("snapshot") or {}
    pol = snap.get("policy_snapshot") or {}
    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()
    lines = [
        clinic,
        (CLINIC_ADDR or "").strip(),
        (CLINIC_PHONE_FAX or "").strip(),
        "",
        "INSURANCE PATIENT COPAY RECEIPT",
        "=" * 42,
        f"Patient: {patient_name}",
        f"Claim ID: {claim_state.get('claim_id') or '—'}",
        f"Payer: {pol.get('carrier_name') or claim_state.get('payer_id') or '—'}",
        f"Date of service: {snap.get('date_of_service') or '—'}",
        "",
        f"Copay collected: ${float(amount):,.2f}",
        f"Method: {(method or 'cash').title()}",
    ]
    if payment_date:
        lines.append(f"Payment date: {payment_date}")
    lines.append("")
    lines.append("This receipt is for the insurance EOB patient responsibility only.")
    lines.append("It is not the full visit cash fee schedule charge.")
    return "\n".join(lines)


def save_insurance_copay_receipt(
    patient_root: str | Path,
    *,
    patient_name: str,
    claim_state: dict,
    amount: float,
    method: str,
    payment_date: str = "",
) -> Path:
    text = build_insurance_copay_receipt_text(
        patient_name=patient_name,
        claim_state=claim_state,
        amount=amount,
        method=method,
        payment_date=payment_date,
    )
    cid = claim_state.get("claim_id") or "claim"
    return save_receipt_file(
        patient_root,
        text,
        prefix="insurance_copay",
        subfolder="insurance",
        unique_key=_safe_claim_key(cid),
    )


def insurance_receipt_stem(claim_id: str, *, kind: str = "eob") -> str:
    key = _safe_claim_key(claim_id)
    if kind == "claim":
        return f"insurance_claim_{key}"
    if kind == "statement":
        return f"insurance_statement_{key}"
    return f"insurance_eob_{key}"
