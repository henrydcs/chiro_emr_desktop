# billing_pi_ledger.py — Phase 3 PI case ledger: post visits, payments, adjustments.
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from billing_engine import determine_payer_mode
from billing_storage import (
    build_and_save_shadow,
    encounters_dir,
    load_shadow_encounter,
    save_shadow_encounter,
)

from billing_pi_case import load_or_create_pi_case, load_pi_case, save_pi_case

_LEDGER_VERSION = 1
_PI_SCHEDULE = "pi_ucr"


def _pi_ledger_path(patient_root: str | os.PathLike) -> Path:
    from billing_storage import patient_billing_root

    p = patient_billing_root(patient_root) / "pi_ledger.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _pi_posted_filename(exam_path: str | Path) -> str:
    stem = Path(exam_path).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return f"{safe}.pi_posted.json"


def load_pi_ledger(patient_root: str | os.PathLike) -> dict:
    p = _pi_ledger_path(patient_root)
    if not p.is_file():
        return {"version": _LEDGER_VERSION, "entries": []}
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"version": _LEDGER_VERSION, "entries": []}
    if not isinstance(raw, dict):
        return {"version": _LEDGER_VERSION, "entries": []}
    raw.setdefault("version", _LEDGER_VERSION)
    raw.setdefault("entries", [])
    return raw


def save_pi_ledger(patient_root: str | os.PathLike, ledger: dict) -> None:
    p = _pi_ledger_path(patient_root)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, p)


def load_pi_posted_encounter(patient_root: str | os.PathLike, exam_path: str | Path) -> dict | None:
    p = encounters_dir(patient_root) / _pi_posted_filename(exam_path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def save_pi_posted_encounter(patient_root: str | os.PathLike, encounter: dict) -> Path:
    exam_path = encounter.get("exam_path") or ""
    out = encounters_dir(patient_root) / _pi_posted_filename(exam_path)
    tmp = out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(encounter, f, indent=2)
    os.replace(tmp, out)
    return out


def is_encounter_pi_posted(patient_root: str | os.PathLike, exam_path: str | Path) -> bool:
    return load_pi_posted_encounter(patient_root, exam_path) is not None


def list_pi_posted_encounters(patient_root: str | os.PathLike) -> list[dict]:
    d = encounters_dir(patient_root)
    out: list[dict] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.pi_posted.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out.append(raw)
        except Exception:
            continue

    def _sort_key(enc: dict):
        dos = enc.get("date_of_service") or ""
        try:
            return datetime.strptime(dos, "%m/%d/%Y")
        except Exception:
            return datetime.min

    out.sort(key=_sort_key)
    return out


def compute_pi_balance(patient_root: str | os.PathLike) -> dict[str, float]:
    ledger = load_pi_ledger(patient_root)
    charges = 0.0
    payments = 0.0
    adjustments = 0.0
    for ent in ledger.get("entries") or []:
        if not isinstance(ent, dict):
            continue
        amt = float(ent.get("amount") or 0)
        t = ent.get("type")
        if t == "charge":
            charges += amt
        elif t == "payment":
            payments += amt
        elif t == "adjustment":
            adjustments += amt
    balance = round(charges - payments + adjustments, 2)
    return {
        "total_charges": round(charges, 2),
        "total_payments": round(payments, 2),
        "total_adjustments": round(adjustments, 2),
        "balance_due": balance,
    }


def post_encounter_to_pi_case(
    *,
    patient_root: str | os.PathLike,
    exam_path: str | Path,
    posted_by: str = "",
    patient_id: str = "",
) -> dict:
    """Post visit charges to PI/UCR case ledger (accumulates; not desk cash)."""
    from billing_ledger import is_encounter_posted

    exam_path = str(Path(exam_path).resolve())
    if is_encounter_pi_posted(patient_root, exam_path):
        raise ValueError("This visit is already posted to the PI case.")
    if is_encounter_posted(patient_root, exam_path):
        raise ValueError(
            "This visit was posted to the cash ledger. "
            "Cannot also post to PI case (void not available in Phase 3)."
        )

    if determine_payer_mode(patient_root) != "pi":
        raise ValueError(
            "Patient primary insurance is not PI/Auto. "
            "Use cash checkout, or update insurance typing."
        )

    if is_pi_case_settled(patient_root):
        raise ValueError(
            "This PI case is settled. Reopen the case in Edit case before posting new visits."
        )

    case = load_or_create_pi_case(patient_root, patient_id=patient_id)
    shadow = load_shadow_encounter(patient_root, exam_path)
    if not shadow:
        shadow = build_and_save_shadow(patient_root=patient_root, exam_path=exam_path)

    schedule = _PI_SCHEDULE
    total = float((shadow.get("totals") or {}).get(schedule) or 0)
    if total <= 0 and not (shadow.get("lines") or []):
        raise ValueError("No charge lines to post.")

    enc_id = shadow.get("encounter_id") or f"enc_{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat(timespec="seconds")

    posted = dict(shadow)
    posted["encounter_id"] = enc_id
    posted["status"] = "posted"
    posted["ledger"] = "pi"
    posted["phase"] = 3
    posted["case_id"] = case.get("case_id") or ""
    posted["posted_at"] = now
    posted["posted_by"] = posted_by
    posted["fee_schedule_used"] = schedule
    posted["amount_charged"] = round(total, 2)
    for ln in posted.get("lines") or []:
        if isinstance(ln, dict):
            ln["status"] = "posted"
            fees = ln.get("fees") or {}
            ln["amount"] = float(fees.get(schedule) or 0)

    save_pi_posted_encounter(patient_root, posted)

    ledger = load_pi_ledger(patient_root)
    ledger.setdefault("entries", []).append(
        {
            "id": f"ple_{uuid.uuid4().hex[:12]}",
            "type": "charge",
            "encounter_id": enc_id,
            "case_id": case.get("case_id") or "",
            "exam_path": exam_path,
            "date_of_service": posted.get("date_of_service") or "",
            "amount": round(total, 2),
            "posted_at": now,
            "memo": posted.get("exam_name") or "",
        }
    )
    save_pi_ledger(patient_root, ledger)

    shadow["pi_posted_at"] = now
    shadow["ledger"] = "pi"
    save_shadow_encounter(patient_root, shadow)

    return posted


def record_pi_payment(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    payer: str,
    payment_date: str = "",
    encounter_id: str = "",
    exam_path: str = "",
    memo: str = "",
    recorded_by: str = "",
) -> dict:
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    now = datetime.now().isoformat(timespec="seconds")
    pay_date = (payment_date or "").strip() or datetime.now().strftime("%m/%d/%Y")
    case = load_or_create_pi_case(patient_root)

    entry = {
        "id": f"ple_{uuid.uuid4().hex[:12]}",
        "type": "payment",
        "amount": round(float(amount), 2),
        "payer": (payer or "other").strip().lower(),
        "payment_date": pay_date,
        "recorded_at": now,
        "recorded_by": recorded_by,
        "case_id": case.get("case_id") or "",
        "encounter_id": encounter_id or "",
        "exam_path": exam_path or "",
        "memo": memo or "",
    }
    ledger = load_pi_ledger(patient_root)
    ledger.setdefault("entries", []).append(entry)
    save_pi_ledger(patient_root, ledger)
    return entry


def record_pi_adjustment(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    memo: str = "",
    recorded_by: str = "",
) -> dict:
    """Negative amount = reduction/write-off (e.g. settlement)."""
    if amount == 0:
        raise ValueError("Adjustment amount cannot be zero.")
    now = datetime.now().isoformat(timespec="seconds")
    case = load_or_create_pi_case(patient_root)
    entry = {
        "id": f"ple_{uuid.uuid4().hex[:12]}",
        "type": "adjustment",
        "amount": round(float(amount), 2),
        "recorded_at": now,
        "recorded_by": recorded_by,
        "case_id": case.get("case_id") or "",
        "memo": (memo or "").strip(),
    }
    ledger = load_pi_ledger(patient_root)
    ledger.setdefault("entries", []).append(entry)
    save_pi_ledger(patient_root, ledger)
    return entry


def preview_pi_settlement(
    patient_root: str | os.PathLike,
    settlement_amount: float,
) -> dict[str, float]:
    """Preview write-off and remaining balance for a settlement amount."""
    bal = compute_pi_balance(patient_root)
    balance_due = bal["balance_due"]
    amount = round(float(settlement_amount), 2)
    if amount <= 0:
        write_off = 0.0
        balance_after = balance_due
    elif amount > balance_due + 0.01:
        write_off = 0.0
        balance_after = balance_due
    else:
        write_off = round(balance_due - amount, 2)
        balance_after = round(max(0.0, balance_due - amount - write_off), 2)
    return {
        "balance_before": balance_due,
        "total_charges": bal["total_charges"],
        "total_payments": bal["total_payments"],
        "total_adjustments": bal["total_adjustments"],
        "settlement_amount": amount,
        "write_off": write_off,
        "balance_after": balance_after,
    }


def is_pi_case_settled(patient_root: str | os.PathLike) -> bool:
    case = load_pi_case(patient_root)
    return bool(case and (case.get("case_status") or "").strip().lower() == "settled")


def record_pi_settlement(
    *,
    patient_root: str | os.PathLike,
    settlement_amount: float,
    payer: str = "attorney",
    payment_date: str = "",
    memo: str = "",
    recorded_by: str = "",
    close_case: bool = True,
) -> dict:
    """
    Record a lump-sum PI settlement: case-level payment plus automatic write-off
    for any remaining balance, optionally marking the case as settled.
    """
    if is_pi_case_settled(patient_root):
        raise ValueError("This PI case is already marked settled.")

    amount = round(float(settlement_amount), 2)
    if amount <= 0:
        raise ValueError("Settlement amount must be greater than zero.")

    preview = preview_pi_settlement(patient_root, amount)
    balance_due = preview["balance_before"]
    if balance_due <= 0.01:
        raise ValueError("PI case has no balance due to settle.")
    if amount > balance_due + 0.01:
        raise ValueError(
            f"Settlement (${amount:,.2f}) exceeds balance due (${balance_due:,.2f})."
        )

    write_off = preview["write_off"]
    pay_date = (payment_date or "").strip() or datetime.now().strftime("%m/%d/%Y")
    base_memo = (memo or "").strip() or "Case settlement"

    payment = record_pi_payment(
        patient_root=patient_root,
        amount=amount,
        payer=payer,
        payment_date=pay_date,
        encounter_id="",
        exam_path="",
        memo=base_memo,
        recorded_by=recorded_by,
    )

    adjustment = None
    if write_off > 0.01:
        adj_memo = f"Settlement write-off (${write_off:,.2f})"
        if base_memo and base_memo != "Case settlement":
            adj_memo = f"{adj_memo} — {base_memo}"
        adjustment = record_pi_adjustment(
            patient_root=patient_root,
            amount=-write_off,
            memo=adj_memo,
            recorded_by=recorded_by,
        )

    case = load_or_create_pi_case(patient_root)
    if close_case:
        case["case_status"] = "settled"
        case["settled_at"] = datetime.now().isoformat(timespec="seconds")
        case["settlement"] = {
            "amount": amount,
            "write_off": write_off,
            "payment_date": pay_date,
            "payer": (payer or "attorney").strip().lower(),
            "memo": base_memo,
            "recorded_by": recorded_by,
            "payment_id": payment.get("id") or "",
            "adjustment_id": (adjustment or {}).get("id") or "",
        }
        save_pi_case(patient_root, case)

    balance_after = compute_pi_balance(patient_root)["balance_due"]
    return {
        "payment": payment,
        "adjustment": adjustment,
        "write_off": write_off,
        "balance_before": balance_due,
        "balance_after": balance_after,
        "case_status": case.get("case_status") or "active",
    }


def pi_encounter_amount_due(
    patient_root: str | os.PathLike,
    exam_path: str | Path,
) -> float:
    if is_pi_case_settled(patient_root):
        return 0.0
    posted = load_pi_posted_encounter(patient_root, exam_path)
    if not posted:
        return 0.0
    enc_id = posted.get("encounter_id") or ""
    charged = float(posted.get("amount_charged") or 0)
    paid = 0.0
    for ent in load_pi_ledger(patient_root).get("entries") or []:
        if ent.get("type") != "payment":
            continue
        if enc_id and ent.get("encounter_id") == enc_id:
            paid += float(ent.get("amount") or 0)
        elif str(ent.get("exam_path") or "") == str(Path(exam_path).resolve()):
            paid += float(ent.get("amount") or 0)
    return round(max(0.0, charged - paid), 2)
