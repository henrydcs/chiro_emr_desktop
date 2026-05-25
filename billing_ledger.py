# billing_ledger.py — Phase 2 cash account: post charges, payments, balance.
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from billing_engine import determine_payer_mode
from billing_storage import (
    build_and_save_shadow,
    encounters_dir,
    load_shadow_encounter,
    make_fee_lookup,
    save_shadow_encounter,
)

_LEDGER_VERSION = 1


def _ledger_path(patient_root: str | os.PathLike) -> Path:
    from billing_storage import patient_billing_root

    p = patient_billing_root(patient_root) / "cash_ledger.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _posted_filename(exam_path: str | Path) -> str:
    stem = Path(exam_path).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return f"{safe}.posted.json"


def load_cash_ledger(patient_root: str | os.PathLike) -> dict:
    p = _ledger_path(patient_root)
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


def save_cash_ledger(patient_root: str | os.PathLike, ledger: dict) -> None:
    p = _ledger_path(patient_root)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
    os.replace(tmp, p)


def load_posted_encounter(patient_root: str | os.PathLike, exam_path: str | Path) -> dict | None:
    p = encounters_dir(patient_root) / _posted_filename(exam_path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def save_posted_encounter(patient_root: str | os.PathLike, encounter: dict) -> Path:
    exam_path = encounter.get("exam_path") or ""
    out = encounters_dir(patient_root) / _posted_filename(exam_path)
    tmp = out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(encounter, f, indent=2)
    os.replace(tmp, out)
    return out


def is_encounter_posted(patient_root: str | os.PathLike, exam_path: str | Path) -> bool:
    return load_posted_encounter(patient_root, exam_path) is not None


def compute_cash_balance(patient_root: str | os.PathLike) -> dict[str, float]:
    ledger = load_cash_ledger(patient_root)
    charges = 0.0
    payments = 0.0
    for ent in ledger.get("entries") or []:
        if not isinstance(ent, dict):
            continue
        amt = float(ent.get("amount") or 0)
        if ent.get("type") == "charge":
            charges += amt
        elif ent.get("type") == "payment":
            payments += amt
    balance = round(charges - payments, 2)
    return {
        "total_charges": round(charges, 2),
        "total_payments": round(payments, 2),
        "balance_due": balance,
    }


def post_encounter_to_cash_ledger(
    *,
    patient_root: str | os.PathLike,
    exam_path: str | Path,
    posted_by: str = "",
    force_cash: bool = False,
) -> dict:
    """
    Post shadow charges to the patient's cash ledger (Phase 2).
    Returns the posted encounter dict.
    """
    exam_path = str(Path(exam_path).resolve())
    if is_encounter_posted(patient_root, exam_path):
        raise ValueError("This visit is already posted.")

    payer = determine_payer_mode(patient_root)
    if payer == "pi" and not force_cash:
        raise ValueError(
            "Primary insurance is PI/Auto. Use Post to PI case on the PI ledger panel, "
            "or confirm Post cash for same-day desk payment."
        )

    shadow = load_shadow_encounter(patient_root, exam_path)
    if not shadow:
        shadow = build_and_save_shadow(patient_root=patient_root, exam_path=exam_path)

    schedule = "cash"
    total = float((shadow.get("totals") or {}).get(schedule) or 0)
    if total <= 0 and not (shadow.get("lines") or []):
        raise ValueError("No charge lines to post.")

    enc_id = shadow.get("encounter_id") or f"enc_{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat(timespec="seconds")

    posted = dict(shadow)
    posted["encounter_id"] = enc_id
    posted["status"] = "posted"
    posted["phase"] = 2
    posted["posted_at"] = now
    posted["posted_by"] = posted_by
    posted["fee_schedule_used"] = schedule
    posted["amount_charged"] = round(total, 2)
    for ln in posted.get("lines") or []:
        if isinstance(ln, dict):
            ln["status"] = "posted"
            fees = ln.get("fees") or {}
            ln["amount"] = float(fees.get(schedule) or 0)

    save_posted_encounter(patient_root, posted)

    ledger = load_cash_ledger(patient_root)
    ledger.setdefault("entries", []).append(
        {
            "id": f"le_{uuid.uuid4().hex[:12]}",
            "type": "charge",
            "encounter_id": enc_id,
            "exam_path": exam_path,
            "date_of_service": posted.get("date_of_service") or "",
            "amount": round(total, 2),
            "posted_at": now,
            "memo": posted.get("exam_name") or "",
        }
    )
    save_cash_ledger(patient_root, ledger)

    shadow["status"] = "posted"
    shadow["posted_at"] = now
    save_shadow_encounter(patient_root, shadow)

    return posted


def record_payment(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    method: str,
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

    entry = {
        "id": f"le_{uuid.uuid4().hex[:12]}",
        "type": "payment",
        "amount": round(float(amount), 2),
        "method": (method or "cash").strip().lower(),
        "payment_date": pay_date,
        "recorded_at": now,
        "recorded_by": recorded_by,
        "encounter_id": encounter_id or "",
        "exam_path": exam_path or "",
        "memo": memo or "",
    }

    ledger = load_cash_ledger(patient_root)
    ledger.setdefault("entries", []).append(entry)
    save_cash_ledger(patient_root, ledger)
    return entry


def encounter_amount_due(
    patient_root: str | os.PathLike,
    exam_path: str | Path,
) -> float:
    """Amount still owed on a posted visit (charge minus payments linked to it)."""
    posted = load_posted_encounter(patient_root, exam_path)
    if not posted:
        return 0.0
    enc_id = posted.get("encounter_id") or ""
    charged = float(posted.get("amount_charged") or 0)
    paid = 0.0
    for ent in load_cash_ledger(patient_root).get("entries") or []:
        if ent.get("type") != "payment":
            continue
        if enc_id and ent.get("encounter_id") == enc_id:
            paid += float(ent.get("amount") or 0)
        elif str(ent.get("exam_path") or "") == str(Path(exam_path).resolve()):
            paid += float(ent.get("amount") or 0)
    return round(max(0.0, charged - paid), 2)
