# package_storage.py — Package deals: clinic catalog + per-patient event log.
#
# Architecture (matches billing_storage / billing_ledger conventions):
#   <data_dir>/billing/package_catalog.json    — clinic-wide package templates
#   <patient>/billing/packages.json            — per-patient append-only event log
#   <patient>/billing/_pending.json            — best-effort write journal (atomicity)
#
# Design rules (do not violate):
#   1. The event log is APPEND-ONLY. Never delete or mutate prior events.
#   2. Status, visits_remaining, deferred_revenue are DERIVED from events.
#      They are never stored. See package_engine.compute_package_state.
#   3. Write order for any multi-file operation MUST be:
#         _pending.json (intent) -> packages.json (event) -> cash_ledger.json -> clear _pending.json
#      This way packages.json is the single source of truth and reconciliation
#      can replay or warn about a partial cash_ledger write.
#   4. PI patients are out of scope by convention — UI gates the sell action,
#      but storage does not refuse (so historical data is portable).

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from billing_storage import patient_billing_root, clinic_billing_dir

_CATALOG_VERSION = 1
_EVENT_LOG_VERSION = 1
_JOURNAL_VERSION = 1


# ---------------------------------------------------------------------------
# Event types (closed enum — extending requires bumping _EVENT_LOG_VERSION)
# ---------------------------------------------------------------------------

EVENT_PURCHASE = "purchase"
EVENT_REDEMPTION = "redemption"
EVENT_REFUND = "refund"
EVENT_CANCELLATION = "cancellation"
EVENT_CONTRACT_FILED = "contract_filed"
EVENT_PAYMENT = "payment"  # money in toward purchase_price (allows partial pay-as-you-go)

EVENT_TYPES = frozenset(
    {
        EVENT_PURCHASE,
        EVENT_REDEMPTION,
        EVENT_REFUND,
        EVENT_CANCELLATION,
        EVENT_CONTRACT_FILED,
        EVENT_PAYMENT,
    }
)

REFUND_STRATEGY_TRUE_PRORATA = "true_pro_rata"
REFUND_STRATEGY_RETAIL_AUDIT = "retail_audit"
REFUND_STRATEGIES = frozenset({REFUND_STRATEGY_TRUE_PRORATA, REFUND_STRATEGY_RETAIL_AUDIT})


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def new_catalog_id() -> str:
    return f"pkgc_{uuid.uuid4().hex[:12]}"


def new_package_instance_id() -> str:
    return f"pkg_{uuid.uuid4().hex[:12]}"


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Clinic-wide package catalog
# ---------------------------------------------------------------------------

def package_catalog_path() -> Path:
    return clinic_billing_dir() / "package_catalog.json"


def _empty_catalog() -> dict:
    return {"version": _CATALOG_VERSION, "templates": []}


def load_package_catalog() -> dict:
    p = package_catalog_path()
    if not p.is_file():
        return _empty_catalog()
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return _empty_catalog()
    if not isinstance(raw, dict):
        return _empty_catalog()
    raw.setdefault("version", _CATALOG_VERSION)
    raw.setdefault("templates", [])
    if not isinstance(raw["templates"], list):
        raw["templates"] = []
    return raw


def save_package_catalog(catalog: dict) -> None:
    _atomic_write_json(package_catalog_path(), catalog)


def _validate_template_payload(data: dict) -> None:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Template name is required.")
    try:
        total_visits = int(data.get("total_visits") or 0)
    except (TypeError, ValueError):
        raise ValueError("Total visits must be a whole number.")
    if total_visits <= 0:
        raise ValueError("Total visits must be greater than zero.")
    try:
        price = float(data.get("package_price") or 0)
    except (TypeError, ValueError):
        raise ValueError("Package price must be a number.")
    if price < 0:
        raise ValueError("Package price cannot be negative.")
    whitelist = data.get("cpt_whitelist") or []
    if not isinstance(whitelist, (list, tuple)) or not whitelist:
        raise ValueError("Pick at least one CPT code for the whitelist.")
    for cpt in whitelist:
        s = str(cpt or "").strip()
        if not s or not s.isdigit() or len(s) != 5:
            raise ValueError(f"CPT '{cpt}' is not a valid 5-digit code.")
    try:
        months = int(data.get("expiration_months") or 0)
    except (TypeError, ValueError):
        raise ValueError("Expiration months must be a whole number.")
    if months < 0:
        raise ValueError("Expiration months cannot be negative (0 = no expiration).")


def _merge_template(existing: dict | None, data: dict) -> dict:
    rec = dict(existing or {})
    rec.setdefault("catalog_id", new_catalog_id())
    rec.setdefault("created_at", _now_iso())
    rec["name"] = (data.get("name") or rec.get("name") or "").strip()
    rec["total_visits"] = int(data.get("total_visits") or rec.get("total_visits") or 0)
    rec["package_price"] = round(float(data.get("package_price") or rec.get("package_price") or 0), 2)
    rec["cpt_whitelist"] = sorted({str(c).strip() for c in (data.get("cpt_whitelist") or []) if str(c).strip()})
    rec["expiration_months"] = int(data.get("expiration_months") or rec.get("expiration_months") or 0)
    rec["disclaimer_text"] = (data.get("disclaimer_text") or rec.get("disclaimer_text") or "").strip()
    rec["cancellation_policy"] = (data.get("cancellation_policy") or rec.get("cancellation_policy") or "").strip()
    rec["no_show_policy"] = (data.get("no_show_policy") or rec.get("no_show_policy") or "").strip()
    rec["notes"] = (data.get("notes") or rec.get("notes") or "").strip()
    rec["active"] = bool(data.get("active", rec.get("active", True)))
    rec["updated_at"] = _now_iso()
    return rec


def list_catalog_templates(*, active_only: bool = False) -> list[dict]:
    catalog = load_package_catalog()
    items = list(catalog.get("templates") or [])
    if active_only:
        items = [t for t in items if t.get("active", True)]
    items.sort(key=lambda t: ((t.get("name") or "").lower(), t.get("catalog_id") or ""))
    return items


def find_catalog_template(catalog_id: str) -> dict | None:
    if not catalog_id:
        return None
    for t in load_package_catalog().get("templates") or []:
        if t.get("catalog_id") == catalog_id:
            return t
    return None


def upsert_catalog_template(data: dict) -> dict:
    """Insert or update a clinic-wide package template."""
    _validate_template_payload(data)
    catalog = load_package_catalog()
    templates = list(catalog.get("templates") or [])
    target_id = (data.get("catalog_id") or "").strip()
    if target_id:
        found = False
        for i, t in enumerate(templates):
            if t.get("catalog_id") == target_id:
                templates[i] = _merge_template(t, data)
                found = True
                break
        if not found:
            templates.append(_merge_template({"catalog_id": target_id}, data))
            rec = templates[-1]
        else:
            rec = templates[i]
    else:
        rec = _merge_template(None, data)
        templates.append(rec)
    catalog["templates"] = templates
    save_package_catalog(catalog)
    return rec


def set_catalog_template_active(catalog_id: str, active: bool) -> None:
    catalog = load_package_catalog()
    changed = False
    for t in catalog.get("templates") or []:
        if t.get("catalog_id") == catalog_id:
            t["active"] = bool(active)
            t["updated_at"] = _now_iso()
            changed = True
            break
    if changed:
        save_package_catalog(catalog)


# ---------------------------------------------------------------------------
# Per-patient event log
# ---------------------------------------------------------------------------

def package_log_path(patient_root: str | os.PathLike) -> Path:
    return patient_billing_root(patient_root) / "packages.json"


def _empty_event_log() -> dict:
    return {"version": _EVENT_LOG_VERSION, "events": []}


def load_package_log(patient_root: str | os.PathLike) -> dict:
    p = package_log_path(patient_root)
    if not p.is_file():
        return _empty_event_log()
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return _empty_event_log()
    if not isinstance(raw, dict):
        return _empty_event_log()
    raw.setdefault("version", _EVENT_LOG_VERSION)
    raw.setdefault("events", [])
    if not isinstance(raw["events"], list):
        raw["events"] = []
    return raw


def save_package_log(patient_root: str | os.PathLike, log: dict) -> None:
    _atomic_write_json(package_log_path(patient_root), log)


def append_event(patient_root: str | os.PathLike, event: dict) -> dict:
    """Append a single event to the patient log. Returns the stored event (with id/timestamp)."""
    if not isinstance(event, dict):
        raise TypeError("event must be a dict")
    etype = (event.get("type") or "").strip().lower()
    if etype not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {etype!r}")
    rec = dict(event)
    rec["type"] = etype
    rec.setdefault("event_id", new_event_id())
    rec.setdefault("timestamp", _now_iso())
    log = load_package_log(patient_root)
    log["events"].append(rec)
    save_package_log(patient_root, log)
    return rec


def all_events_for_package(patient_root: str | os.PathLike, package_id: str) -> list[dict]:
    if not package_id:
        return []
    return [
        e for e in load_package_log(patient_root).get("events") or []
        if isinstance(e, dict) and e.get("package_id") == package_id
    ]


def find_purchase_event(patient_root: str | os.PathLike, package_id: str) -> dict | None:
    for e in all_events_for_package(patient_root, package_id):
        if e.get("type") == EVENT_PURCHASE:
            return e
    return None


def list_packages(patient_root: str | os.PathLike) -> list[str]:
    """Return all package_ids that have ever existed for this patient (ordered by first event)."""
    seen: list[str] = []
    for e in load_package_log(patient_root).get("events") or []:
        if not isinstance(e, dict):
            continue
        pid = e.get("package_id") or ""
        if pid and pid not in seen:
            seen.append(pid)
    return seen


# ---------------------------------------------------------------------------
# Write-ahead journal (best-effort atomicity for multi-file operations)
# ---------------------------------------------------------------------------
#
# Workflow for a redemption (which touches packages.json AND cash_ledger.json):
#
#   1. write_journal(patient_root, op_dict)   -> records intent
#   2. append_event(patient_root, redemption) -> packages.json updated (source of truth)
#   3. ledger writes (charge + adjustment)    -> cash_ledger.json updated
#   4. clear_journal(patient_root)            -> intent cleared on success
#
# If process dies between (2) and (3): on next BillingPage load,
# reconcile_pending_operations() finds the orphan journal entry and either:
#   - sees the cash_ledger already has the adjustment (op completed, just stale journal) -> clear it
#   - sees no adjustment -> warn the user that packages.json says a redemption happened
#     but cash_ledger.json is missing the offsetting adjustment.
# We DO NOT auto-rewrite the ledger; the user must confirm via a repair dialog.

def journal_path(patient_root: str | os.PathLike) -> Path:
    return patient_billing_root(patient_root) / "_pending.json"


def write_journal(patient_root: str | os.PathLike, op: dict) -> dict:
    """Record a single pending operation (overwrites any prior pending op)."""
    rec = {
        "version": _JOURNAL_VERSION,
        "op_id": f"jop_{uuid.uuid4().hex[:12]}",
        "started_at": _now_iso(),
        "op": dict(op or {}),
    }
    _atomic_write_json(journal_path(patient_root), rec)
    return rec


def load_journal(patient_root: str | os.PathLike) -> dict | None:
    p = journal_path(patient_root)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def clear_journal(patient_root: str | os.PathLike) -> None:
    p = journal_path(patient_root)
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Reconciliation — read-only health check across packages.json and cash_ledger.json
# ---------------------------------------------------------------------------

def reconcile_pending_operations(patient_root: str | os.PathLike) -> dict:
    """
    Inspect packages.json vs cash_ledger.json and any stale journal entry.

    Returns:
        {
          "orphan_redemptions": [list of redemption event_ids with no matching ledger adjustment],
          "orphan_adjustments": [list of ledger entry ids that reference a missing redemption],
          "stale_journal": dict | None,
          "ok": bool  (True iff no orphans and no stale journal),
        }
    """
    from billing_ledger import load_cash_ledger

    log = load_package_log(patient_root)
    ledger = load_cash_ledger(patient_root)

    # Modern redemption events are self-contained in packages.json and intentionally
    # do NOT write a paired adjustment to cash_ledger.json (package money is fully
    # separated from cash money). Only legacy events with writes_to_cash_ledger
    # truthy are expected to have a matching cash-ledger adjustment.
    redemption_events = [
        e for e in log.get("events") or []
        if isinstance(e, dict) and e.get("type") == EVENT_REDEMPTION
    ]
    legacy_redemptions = [
        e for e in redemption_events if e.get("writes_to_cash_ledger")
    ]
    ledger_entries = [
        e for e in ledger.get("entries") or []
        if isinstance(e, dict)
    ]

    adjustment_keys = {
        (e.get("package_id") or "", e.get("redemption_event_id") or "")
        for e in ledger_entries
        if (e.get("type") == "adjustment") and (e.get("subtype") == "package")
    }
    legacy_redemption_keys = {
        (e.get("package_id") or "", e.get("event_id") or "")
        for e in legacy_redemptions
    }

    orphan_redemptions = sorted(
        e.get("event_id") or ""
        for e in legacy_redemptions
        if (e.get("package_id") or "", e.get("event_id") or "") not in adjustment_keys
    )
    orphan_adjustments = sorted(
        e.get("id") or ""
        for e in ledger_entries
        if e.get("type") == "adjustment"
        and e.get("subtype") == "package"
        and (e.get("package_id") or "", e.get("redemption_event_id") or "") not in legacy_redemption_keys
    )

    stale = load_journal(patient_root)
    return {
        "orphan_redemptions": orphan_redemptions,
        "orphan_adjustments": orphan_adjustments,
        "stale_journal": stale,
        "ok": not orphan_redemptions and not orphan_adjustments and stale is None,
    }


# ---------------------------------------------------------------------------
# Package-posted encounter file (mirrors cash <exam>.posted.json and PI's
# <exam>.posted.pi.json — kept fully separate so the three flows never share
# state or math).
# ---------------------------------------------------------------------------

def _package_posted_filename(exam_path: str | os.PathLike) -> str:
    stem = Path(exam_path).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return f"{safe}.posted.package.json"


def package_posted_path(
    patient_root: str | os.PathLike,
    exam_path: str | os.PathLike,
) -> Path:
    from billing_storage import encounters_dir

    return encounters_dir(patient_root) / _package_posted_filename(exam_path)


def load_package_posted_encounter(
    patient_root: str | os.PathLike,
    exam_path: str | os.PathLike,
) -> dict | None:
    p = package_posted_path(patient_root, exam_path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def save_package_posted_encounter(
    patient_root: str | os.PathLike,
    encounter: dict,
) -> Path:
    exam_path = encounter.get("exam_path") or ""
    out = package_posted_path(patient_root, exam_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(encounter, f, indent=2)
    os.replace(tmp, out)
    return out


def is_encounter_package_posted(
    patient_root: str | os.PathLike,
    exam_path: str | os.PathLike,
) -> bool:
    return load_package_posted_encounter(patient_root, exam_path) is not None


def post_encounter_to_package(
    *,
    patient_root: str | os.PathLike,
    exam_path: str | os.PathLike,
    package_id: str,
    cpt: str = "",          # legacy: when set, takes priority as the "primary" CPT label
    charge_line_id: str = "",
    date_of_service: str = "",
    posted_by: str = "",
) -> tuple[dict, dict]:
    """
    Apply the entire encounter to a package: append ONE redemption event to
    packages.json (decrementing visits_remaining by 1) AND write a sidecar
    posted-package file so the encounter row UI can show the Pckg$ badge.

    The whole VISIT is the unit of redemption — not a single CPT. Every CPT
    line on the encounter is recorded on the redemption (no whitelist filter)
    so the package receipt reflects the full services rendered that day.

    A "primary" CPT is chosen for the legacy single-code label using clinic
    priority rules (spinal CMT > extremity CMT > therapy 97xxx > other);
    `cpt=...` arg overrides the auto-pick when set.

    The package's `cpt_whitelist` (set at sale time) is now INFORMATIONAL only
    — it describes the services the plan was originally designed around, but
    posting a visit no longer requires any CPT to match. This lets a patient
    redeem a visit with a therapy-only encounter, an E/M-only visit, etc.

    Does NOT touch cash_ledger.json or pi_ledger.json — package money is fully
    isolated from cash and PI money by design.

    Returns (posted_encounter, redemption_event).

    Raises ValueError if the visit is already posted to ANY flow (cash / PI /
    package), or if the requested package is not active/redeemable.
    """
    from billing_engine import determine_payer_mode
    from billing_ledger import is_encounter_posted as _is_cash_posted
    from billing_pi_ledger import is_encounter_pi_posted
    from billing_storage import (
        build_and_save_shadow,
        load_shadow_encounter,
        save_shadow_encounter,
    )
    from package_engine import compute_package_state, is_redeemable, pick_primary_cpt

    exam_path = str(Path(exam_path).resolve())

    if is_encounter_package_posted(patient_root, exam_path):
        raise ValueError("This visit is already posted to a package deal.")
    if _is_cash_posted(patient_root, exam_path):
        raise ValueError(
            "This visit is already posted to the cash ledger. Each visit posts "
            "to exactly one flow — void it on Cash checkout first to switch."
        )
    if is_encounter_pi_posted(patient_root, exam_path):
        raise ValueError(
            "This visit is already posted to the PI case. Each visit posts to "
            "exactly one flow — void it on the PI ledger first to switch."
        )

    if determine_payer_mode(patient_root) == "pi":
        raise ValueError(
            "Package deals are for cash patients. This patient is typed PI/Auto."
        )

    pkg_state = compute_package_state(all_events_for_package(patient_root, package_id))
    if not pkg_state.get("purchase") or not is_redeemable(pkg_state):
        raise ValueError(
            "Selected package is not active and redeemable (it may be expired, "
            "exhausted, refunded, or cancelled)."
        )
    purchase = pkg_state.get("purchase") or {}

    shadow = load_shadow_encounter(patient_root, exam_path)
    if not shadow:
        shadow = build_and_save_shadow(patient_root=patient_root, exam_path=exam_path)

    # Pull EVERY CPT line off the encounter, in chart order (used by the
    # primary-CPT picker as the tiebreak for therapy / other codes).
    cpts_covered: list[str] = []
    for ln in shadow.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        line_cpt = (ln.get("cpt_code") or "").strip()
        if not line_cpt or line_cpt in cpts_covered:
            continue
        cpts_covered.append(line_cpt)
    # Whitelist no longer gates redemption — every encounter CPT counts.
    cpts_not_covered: list[str] = []

    # Primary CPT label — caller-supplied `cpt` wins (legacy override); else
    # use the priority picker. Falls back to "" for zero-CPT encounters
    # (patient redeemed a visit slot without any billable CPT line).
    requested = (cpt or "").strip()
    if requested and requested in cpts_covered:
        cpt_primary = requested
    else:
        cpt_primary = pick_primary_cpt(cpts_covered)

    enc_id = shadow.get("encounter_id") or f"enc_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    posted = dict(shadow)
    posted["encounter_id"] = enc_id
    posted["status"] = "posted"
    posted["phase"] = 5
    posted["posted_at"] = now
    posted["posted_by"] = posted_by
    posted["posted_flow"] = "package"
    posted["package_id"] = package_id
    posted["package_name"] = purchase.get("name") or ""
    posted["package_cpts_redeemed"] = list(cpts_covered)
    posted["package_cpt_redeemed"] = cpt_primary  # legacy field
    posted["package_cpts_not_covered"] = list(cpts_not_covered)
    posted["fee_schedule_used"] = "package"
    for ln in posted.get("lines") or []:
        if isinstance(ln, dict):
            ln["status"] = "posted_to_package"

    write_journal(
        patient_root,
        {
            "kind": "post_encounter_to_package",
            "exam_path": exam_path,
            "encounter_id": enc_id,
            "package_id": package_id,
        },
    )
    try:
        event = append_event(
            patient_root,
            {
                "type": EVENT_REDEMPTION,
                "package_id": package_id,
                "catalog_id": purchase.get("catalog_id") or "",
                "encounter_id": enc_id,
                "exam_path": exam_path,
                "charge_line_id": charge_line_id or "",
                # NEW: store the full list of covered CPTs from this visit.
                "cpts_redeemed": list(cpts_covered),
                # Legacy primary CPT label kept for back-compat with old readers.
                "cpt_redeemed": cpt_primary,
                # Encounter CPTs NOT covered by the package — recorded for audit
                # transparency. Still only ONE visit is consumed from the package.
                "cpts_not_covered": list(cpts_not_covered),
                "value_recognized": round(
                    float(purchase.get("prorated_value_per_visit") or 0.0), 2
                ),
                "date_of_service": (date_of_service or posted.get("date_of_service") or "").strip(),
                "recorded_by": posted_by,
                # Modern redemptions are self-contained in packages.json — the
                # reconciliation pass skips them when looking for orphan
                # cash-ledger adjustments (none are expected).
                "writes_to_cash_ledger": False,
            },
        )
        save_package_posted_encounter(patient_root, posted)
        shadow["status"] = "posted_to_package"
        shadow["posted_at"] = now
        shadow["posted_flow"] = "package"
        save_shadow_encounter(patient_root, shadow)
    finally:
        clear_journal(patient_root)

    return posted, event


# ---------------------------------------------------------------------------
# Package payment events (toward purchase price — supports partial pay-as-you-go)
# ---------------------------------------------------------------------------

def record_package_payment(
    *,
    patient_root: str | os.PathLike,
    package_id: str,
    amount: float,
    method: str = "cash",
    payment_date: str = "",
    memo: str = "",
    recorded_by: str = "",
) -> dict:
    """
    Append a EVENT_PAYMENT event to packages.json. Does NOT touch cash_ledger.json.

    Package money is fully isolated from cash money — collections, balances, and
    receipts for package deals stand alone from the cash account.
    """
    from package_engine import compute_package_state

    if amount <= 0:
        raise ValueError("Package payment amount must be greater than zero.")
    if not package_id:
        raise ValueError("package_id is required.")

    state = compute_package_state(all_events_for_package(patient_root, package_id))
    if not state.get("purchase"):
        raise ValueError("Package not found.")

    pay_date = (payment_date or "").strip() or datetime.now().strftime("%m/%d/%Y")
    return append_event(
        patient_root,
        {
            "type": EVENT_PAYMENT,
            "package_id": package_id,
            "amount": round(float(amount), 2),
            "method": (method or "cash").strip().lower(),
            "payment_date": pay_date,
            "memo": (memo or "").strip(),
            "recorded_by": recorded_by,
        },
    )
