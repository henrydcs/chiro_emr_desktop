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

_LEDGER_VERSION = 3  # v3: cash ledger is now PURE cash. Package money lives in
                     #     packages.json; PI money lives in pi_ledger.json. Legacy
                     #     v2 entries tagged as package activity (memo_kind=
                     #     "package_purchase" or subtype="package") are still on
                     #     disk for audit, but EXCLUDED from cash balance math by
                     #     _is_package_entry() so cash math is pure cash.

# Closed enum of cash-ledger entry types.
#   charge      — billable service posted from an encounter (positive)
#   payment     — money in from patient/cardholder (positive)
#   adjustment  — contractual reduction (signed; negative reduces balance).
#                 Modern flow never writes subtype='package' here (package money
#                 is fully separated). Legacy v2 'package' adjustments stay on
#                 disk for forensic audit but are filtered out of balance math.
#   refund      — money OUT to the patient (positive amount, but treated as
#                 a payment reversal in the balance formula).
LEDGER_ENTRY_TYPES = frozenset({"charge", "payment", "adjustment", "refund"})


def _is_package_entry(entry: dict) -> bool:
    """
    True iff the entry was written by a (legacy) package-deal code path.

    Cash-balance math, encounter_amount_due, and cash-receipt totals MUST
    exclude these so cash visits stand alone from package collections /
    redemptions. The entries remain on disk for forensic audit; they're just
    invisible to cash math.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("memo_kind") == "package_purchase":
        return True
    if entry.get("type") == "adjustment" and entry.get("subtype") == "package":
        return True
    return False


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


def find_posted_encounter_by_id(
    patient_root: str | os.PathLike, encounter_id: str
) -> dict | None:
    """
    Look up a posted encounter by its `encounter_id` (e.g. 'enc_724238ccbf73').

    Used when the cash-receipt dialog needs to lazy-generate a PDF from a
    receipt that's named `receipt_<encounter_id>.txt` but has no .pdf sibling
    yet. Scans `<patient>/billing/encounters/*.posted.json` for a match.
    Returns None if no posted file references that id.
    """
    enc_id = (encounter_id or "").strip()
    if not enc_id:
        return None
    enc_dir = encounters_dir(patient_root)
    if not enc_dir.is_dir():
        return None
    for p in enc_dir.glob("*.posted.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and raw.get("encounter_id") == enc_id:
            return raw
    return None


def compute_cash_balance(patient_root: str | os.PathLike) -> dict[str, float]:
    """
    balance_due = charges + adjustments - payments + refunds

    Adjustments are signed (package coverage uses negative values to offset
    the corresponding full-fee charge line and zero-out patient responsibility).
    Refunds are stored as positive amounts but RESTORE the balance — when the
    clinic refunds $100 to the patient, $100 of prior payments is "undone".
    """
    ledger = load_cash_ledger(patient_root)
    charges = 0.0
    payments = 0.0
    adjustments = 0.0
    refunds = 0.0
    for ent in ledger.get("entries") or []:
        if not isinstance(ent, dict):
            continue
        if _is_package_entry(ent):
            continue  # package money is fully separate — never touches cash math
        amt = float(ent.get("amount") or 0)
        etype = ent.get("type")
        if etype == "charge":
            charges += amt
        elif etype == "payment":
            payments += amt
        elif etype == "adjustment":
            adjustments += amt
        elif etype == "refund":
            refunds += amt
    balance = round(charges + adjustments - payments + refunds, 2)
    return {
        "total_charges": round(charges, 2),
        "total_payments": round(payments, 2),
        "total_adjustments": round(adjustments, 2),
        "total_refunds": round(refunds, 2),
        "balance_due": balance,
    }


def post_encounter_to_cash_ledger(
    *,
    patient_root: str | os.PathLike,
    exam_path: str | Path,
    posted_by: str = "",
    force_cash: bool = False,
    package_redemptions: list[dict] | None = None,
) -> dict:
    """
    Post shadow charges to the patient's cash ledger (Phase 2).

    `package_redemptions` (optional, Phase 5): list of dicts describing per-line
    package coverage to apply atomically:
        [{
          "charge_line_id": "cl_xxx",   # which encounter line is covered
          "cpt": "98941",               # for audit
          "package_id": "pkg_xxx",      # which package instance
          "catalog_id": "pkgc_xxx",     # template (may be "")
          "amount_offset": 75.00,       # the FULL fee to write off (positive)
          "value_recognized": 60.00,    # deferred → earned for this redemption
        }, ...]

    The encounter posts at FULL fee schedule prices (audit integrity), and a
    matching negative adjustment is written per redemption — net patient
    responsibility for covered lines is $0.

    Write order (CRITICAL — see package_storage.write_journal docstring):
      1. journal     -> _pending.json (intent)
      2. packages.json events appended (source of truth)
      3. posted encounter JSON written
      4. cash ledger entries appended (charge + N adjustments)
      5. journal cleared
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

    # Phase 5: optional package redemption flow.
    # We sequence multi-file writes via a small journal so a crash mid-flight
    # leaves packages.json (the source of truth) intact and the user gets a
    # clear reconciliation warning instead of silent ledger corruption.
    redemption_records: list[dict] = []
    if package_redemptions:
        from package_storage import (
            EVENT_REDEMPTION,
            append_event,
            clear_journal,
            write_journal,
        )

        write_journal(
            patient_root,
            {
                "kind": "post_encounter_with_redemptions",
                "exam_path": exam_path,
                "encounter_id": enc_id,
                "redemption_count": len(package_redemptions),
            },
        )
        for rd in package_redemptions:
            event = append_event(
                patient_root,
                {
                    "type": EVENT_REDEMPTION,
                    "package_id": rd.get("package_id") or "",
                    "catalog_id": rd.get("catalog_id") or "",
                    "encounter_id": enc_id,
                    "exam_path": exam_path,
                    "charge_line_id": rd.get("charge_line_id") or "",
                    "cpt_redeemed": rd.get("cpt") or "",
                    "value_recognized": round(float(rd.get("value_recognized") or 0.0), 2),
                    "amount_offset": round(float(rd.get("amount_offset") or 0.0), 2),
                    "date_of_service": posted.get("date_of_service") or "",
                    "recorded_by": posted_by,
                },
            )
            redemption_records.append({"event": event, "input": rd})

    save_posted_encounter(patient_root, posted)

    ledger = load_cash_ledger(patient_root)
    entries = ledger.setdefault("entries", [])
    entries.append(
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
    for rec in redemption_records:
        rd = rec["input"]
        evt = rec["event"]
        entries.append(
            {
                "id": f"le_{uuid.uuid4().hex[:12]}",
                "type": "adjustment",
                "subtype": "package",
                "encounter_id": enc_id,
                "exam_path": exam_path,
                "date_of_service": posted.get("date_of_service") or "",
                "amount": -abs(round(float(rd.get("amount_offset") or 0.0), 2)),
                "package_id": rd.get("package_id") or "",
                "redemption_event_id": evt.get("event_id") or "",
                "charge_line_id": rd.get("charge_line_id") or "",
                "memo": f"Package coverage · {rd.get('cpt') or ''}",
                "recorded_at": now,
                "recorded_by": posted_by,
            }
        )
    save_cash_ledger(patient_root, ledger)

    if package_redemptions:
        from package_storage import clear_journal

        clear_journal(patient_root)

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
    """Amount still owed on a posted visit (charge minus payments and adjustments linked to it)."""
    posted = load_posted_encounter(patient_root, exam_path)
    if not posted:
        return 0.0
    enc_id = posted.get("encounter_id") or ""
    exam_resolved = str(Path(exam_path).resolve())
    charged = float(posted.get("amount_charged") or 0)
    paid = 0.0
    adjusted = 0.0
    refunded = 0.0
    for ent in load_cash_ledger(patient_root).get("entries") or []:
        if not isinstance(ent, dict):
            continue
        if _is_package_entry(ent):
            continue  # legacy package adjustments don't reduce cash AR anymore
        match_enc = bool(enc_id and ent.get("encounter_id") == enc_id)
        match_path = str(ent.get("exam_path") or "") == exam_resolved
        if not (match_enc or match_path):
            continue
        etype = ent.get("type")
        amt = float(ent.get("amount") or 0)
        if etype == "payment":
            paid += amt
        elif etype == "adjustment":
            adjusted += amt
        elif etype == "refund":
            refunded += amt
    due = charged + adjusted - paid + refunded
    return round(max(0.0, due), 2)


def is_encounter_cash_paid_in_full(
    patient_root: str | os.PathLike,
    exam_path: str | Path,
) -> bool:
    """
    True when the visit is cash-posted and nothing remains due on that visit
    (full payment collected, or balance zeroed by payments + adjustments).

    Used by the encounter list to show a paid-in-full checkmark on yellow
    cash cards. Partial payments and posted-but-unpaid visits return False.
    """
    if not is_encounter_posted(patient_root, exam_path):
        return False
    return encounter_amount_due(patient_root, exam_path) <= 0.01


# ---------------------------------------------------------------------------
# Phase 5 — generic adjustment / refund / package purchase entry points
# ---------------------------------------------------------------------------

def record_adjustment(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    subtype: str = "manual",
    memo: str = "",
    encounter_id: str = "",
    exam_path: str = "",
    package_id: str = "",
    redemption_event_id: str = "",
    recorded_by: str = "",
) -> dict:
    """
    Generic cash-ledger adjustment.
      * amount is SIGNED: negative reduces balance (e.g. package coverage, courtesy)
      * subtype is freeform tag: "package" (used by post_encounter_to_cash_ledger),
        "courtesy", "writeoff", "manual", etc.
    Does NOT auto-create a packages.json event; the caller is responsible for that
    in flows that touch both files. Standalone adjustments (e.g. courtesy discount)
    only touch the cash ledger and are safe to record here directly.
    """
    if amount == 0:
        raise ValueError("Adjustment amount must be non-zero.")
    now = datetime.now().isoformat(timespec="seconds")
    entry = {
        "id": f"le_{uuid.uuid4().hex[:12]}",
        "type": "adjustment",
        "subtype": (subtype or "manual").strip().lower(),
        "amount": round(float(amount), 2),
        "memo": (memo or "").strip(),
        "encounter_id": encounter_id or "",
        "exam_path": exam_path or "",
        "package_id": package_id or "",
        "redemption_event_id": redemption_event_id or "",
        "recorded_at": now,
        "recorded_by": recorded_by,
    }
    ledger = load_cash_ledger(patient_root)
    ledger.setdefault("entries", []).append(entry)
    save_cash_ledger(patient_root, ledger)
    return entry


def record_refund(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    method: str,
    refund_date: str = "",
    memo: str = "",
    package_id: str = "",
    encounter_id: str = "",
    exam_path: str = "",
    recorded_by: str = "",
) -> dict:
    """
    Refund a patient (money OUT). Amount must be > 0 — sign is implicit
    (refund INCREASES balance_due, reversing a prior payment).
    """
    if amount <= 0:
        raise ValueError("Refund amount must be greater than zero.")
    now = datetime.now().isoformat(timespec="seconds")
    refund_dt = (refund_date or "").strip() or datetime.now().strftime("%m/%d/%Y")
    entry = {
        "id": f"le_{uuid.uuid4().hex[:12]}",
        "type": "refund",
        "amount": round(float(amount), 2),
        "method": (method or "cash").strip().lower(),
        "refund_date": refund_dt,
        "memo": (memo or "").strip(),
        "package_id": package_id or "",
        "encounter_id": encounter_id or "",
        "exam_path": exam_path or "",
        "recorded_at": now,
        "recorded_by": recorded_by,
    }
    ledger = load_cash_ledger(patient_root)
    ledger.setdefault("entries", []).append(entry)
    save_cash_ledger(patient_root, ledger)
    return entry


def package_purchase_payments(patient_root: str | os.PathLike) -> list[dict]:
    """
    All package payment events for the patient (modern: from packages.json
    EVENT_PAYMENT entries). Legacy cash-ledger entries tagged memo_kind=
    "package_purchase" are also surfaced so historical reports stay correct.
    """
    out: list[dict] = []
    try:
        from package_storage import EVENT_PAYMENT, load_package_log

        for e in load_package_log(patient_root).get("events") or []:
            if isinstance(e, dict) and e.get("type") == EVENT_PAYMENT:
                out.append(e)
    except Exception:
        pass
    # Legacy entries (kept on disk for forensic audit; pre-v3 sales recorded
    # the initial payment to cash_ledger.json with memo_kind="package_purchase")
    for ent in load_cash_ledger(patient_root).get("entries") or []:
        if not isinstance(ent, dict):
            continue
        if ent.get("type") == "payment" and ent.get("memo_kind") == "package_purchase":
            out.append(ent)
    return out


def record_package_purchase_payment(
    *,
    patient_root: str | os.PathLike,
    amount: float,
    method: str,
    payment_date: str = "",
    memo: str = "",
    package_id: str = "",
    catalog_id: str = "",
    recorded_by: str = "",
) -> dict:
    """
    DEPRECATED — package money is no longer commingled with cash money.
    This shim now forwards to package_storage.record_package_payment so any
    legacy callers keep working while writing to the correct ledger.
    """
    from package_storage import record_package_payment

    return record_package_payment(
        patient_root=patient_root,
        package_id=package_id,
        amount=amount,
        method=method,
        payment_date=payment_date,
        memo=memo,
        recorded_by=recorded_by,
    )
