# package_engine.py — Pure derivation for package state, balance, and refund math.
#
# This module is the analog of billing_engine.py for packages:
#   * No I/O of its own (caller passes loaded events / encounter dicts in).
#   * No side effects.
#   * All state for a package (status, visits remaining, deferred revenue, etc.)
#     is COMPUTED from the immutable event log — never read off a stored field.
#
# The package "state machine":
#
#       (no events) --purchase-->  active
#                                    |
#                                    +-- redemption (still has visits) --> active
#                                    +-- redemption (last visit)         --> exhausted
#                                    +-- (today > expiration_date)       --> expired
#                                    +-- refund                          --> refunded
#                                    +-- cancellation                    --> cancelled
#
# Precedence when multiple terminal conditions exist:
#   cancelled > refunded > exhausted > expired > active
# (Once a package is cancelled it stays cancelled; refund > expiration etc.)

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from package_storage import (
    EVENT_CANCELLATION,
    EVENT_PAYMENT,
    EVENT_PURCHASE,
    EVENT_REDEMPTION,
    EVENT_REFUND,
    REFUND_STRATEGIES,
    REFUND_STRATEGY_RETAIL_AUDIT,
    REFUND_STRATEGY_TRUE_PRORATA,
)


# ---------------------------------------------------------------------------
# Status constants (derived only)
# ---------------------------------------------------------------------------

STATUS_ACTIVE = "active"
STATUS_EXHAUSTED = "exhausted"
STATUS_EXPIRED = "expired"
STATUS_REFUNDED = "refunded"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = (STATUS_ACTIVE, STATUS_EXHAUSTED, STATUS_EXPIRED, STATUS_REFUNDED, STATUS_CANCELLED)


def status_label(status: str) -> str:
    return {
        STATUS_ACTIVE: "Active",
        STATUS_EXHAUSTED: "Exhausted",
        STATUS_EXPIRED: "Expired",
        STATUS_REFUNDED: "Refunded",
        STATUS_CANCELLED: "Cancelled",
    }.get(status, status or "—")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_md_y(s: str) -> date | None:
    """Parse MM/DD/YYYY (and a few common variants). Returns None on failure."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def add_months_iso(start_mdy: str, months: int) -> str:
    """Add N months to an MM/DD/YYYY date; return MM/DD/YYYY ('' on failure or months<=0)."""
    d = _parse_md_y(start_mdy)
    if not d or months <= 0:
        return ""
    # Naive month math: roll year if needed; clamp day to month length.
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    # Clamp the day to last valid day of target month.
    for trial_day in (d.day, 28, 27, 26):
        try:
            return date(year, month, trial_day).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return ""


def today_str() -> str:
    return date.today().strftime("%m/%d/%Y")


# ---------------------------------------------------------------------------
# Per-package derived state
# ---------------------------------------------------------------------------

def compute_package_state(
    events_for_package: Iterable[dict],
    *,
    as_of: date | None = None,
) -> dict:
    """
    Given all events for ONE package_id, return a derived state dict:

        {
          "package_id": str,
          "purchase": dict,                # the purchase event (canonical metadata)
          "redemptions": [dict, ...],      # in event order
          "refunds": [dict, ...],
          "cancellations": [dict, ...],
          "status": "active|exhausted|expired|refunded|cancelled",
          "visits_used": int,
          "visits_remaining": int,
          "value_recognized": float,       # earned revenue total
          "deferred_revenue_remaining": float,
          "refund_paid": float,            # signed positive (money out to patient)
          "expires_on": "MM/DD/YYYY" | "",
          "expires_in_days": int | None,   # None when no expiration
          "is_expired_by_date": bool,
        }

    Pass `as_of` to test expiration on a specific date (defaults to today).
    """
    events = list(events_for_package or [])
    if not events:
        return _empty_state()

    purchase = next((e for e in events if e.get("type") == EVENT_PURCHASE), None)
    if not purchase:
        return _empty_state()

    redemptions = [e for e in events if e.get("type") == EVENT_REDEMPTION]
    refunds = [e for e in events if e.get("type") == EVENT_REFUND]
    cancellations = [e for e in events if e.get("type") == EVENT_CANCELLATION]
    payments = [e for e in events if e.get("type") == EVENT_PAYMENT]

    total_visits = int(purchase.get("total_visits") or 0)
    prorated = float(purchase.get("prorated_value_per_visit") or 0.0)
    purchase_price = float(purchase.get("purchase_price") or 0.0)
    expires_on = (purchase.get("expiration_date") or "").strip()

    visits_used = len(redemptions)
    visits_remaining = max(0, total_visits - visits_used)

    value_recognized = round(
        sum(float(r.get("value_recognized") or prorated or 0.0) for r in redemptions),
        2,
    )
    refund_paid = round(sum(float(r.get("amount") or 0.0) for r in refunds), 2)

    # NEW: collected so far = sum of EVENT_PAYMENT events. Patient AR = purchase_price - collected.
    amount_paid = round(sum(float(p.get("amount") or 0.0) for p in payments), 2)
    purchase_balance_due = round(max(0.0, purchase_price - amount_paid), 2)
    is_paid_in_full = purchase_balance_due <= 0.01

    # Deferred revenue (GAAP): money on hand that hasn't been earned via service yet.
    # Bounded by amount_paid (the clinic can't have "deferred" more than it collected).
    deferred_revenue = round(max(0.0, amount_paid - value_recognized - refund_paid), 2)

    today = as_of or date.today()
    exp_date = _parse_md_y(expires_on)
    is_expired_by_date = bool(exp_date and exp_date < today)
    expires_in_days = (exp_date - today).days if exp_date else None

    status = _derive_status(
        visits_remaining=visits_remaining,
        has_refund=bool(refunds),
        has_cancellation=bool(cancellations),
        is_expired_by_date=is_expired_by_date,
    )

    return {
        "package_id": purchase.get("package_id") or "",
        "purchase": purchase,
        "redemptions": redemptions,
        "refunds": refunds,
        "cancellations": cancellations,
        "payments": payments,
        "status": status,
        "visits_used": visits_used,
        "visits_remaining": visits_remaining,
        "value_recognized": value_recognized,
        "deferred_revenue_remaining": deferred_revenue,
        "refund_paid": refund_paid,
        "amount_paid": amount_paid,
        "purchase_price": round(purchase_price, 2),
        "purchase_balance_due": purchase_balance_due,
        "is_paid_in_full": is_paid_in_full,
        "expires_on": expires_on,
        "expires_in_days": expires_in_days,
        "is_expired_by_date": is_expired_by_date,
    }


def _empty_state() -> dict:
    return {
        "package_id": "",
        "purchase": None,
        "redemptions": [],
        "refunds": [],
        "cancellations": [],
        "payments": [],
        "status": "",
        "visits_used": 0,
        "visits_remaining": 0,
        "value_recognized": 0.0,
        "deferred_revenue_remaining": 0.0,
        "refund_paid": 0.0,
        "amount_paid": 0.0,
        "purchase_price": 0.0,
        "purchase_balance_due": 0.0,
        "is_paid_in_full": False,
        "expires_on": "",
        "expires_in_days": None,
        "is_expired_by_date": False,
    }


def _derive_status(
    *,
    visits_remaining: int,
    has_refund: bool,
    has_cancellation: bool,
    is_expired_by_date: bool,
) -> str:
    if has_cancellation:
        return STATUS_CANCELLED
    if has_refund:
        return STATUS_REFUNDED
    if visits_remaining <= 0:
        return STATUS_EXHAUSTED
    if is_expired_by_date:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


def is_redeemable(state: dict) -> bool:
    """A package is redeemable iff status==active and visits_remaining>0."""
    return state.get("status") == STATUS_ACTIVE and int(state.get("visits_remaining") or 0) > 0


# ---------------------------------------------------------------------------
# Group helpers (multiple packages)
# ---------------------------------------------------------------------------

def states_for_patient(events: Iterable[dict]) -> list[dict]:
    """Group events by package_id and compute state for each, ordered by purchase date desc."""
    events = list(events or [])
    by_pkg: dict[str, list[dict]] = {}
    for e in events:
        pid = e.get("package_id") or ""
        if not pid:
            continue
        by_pkg.setdefault(pid, []).append(e)
    states = [compute_package_state(evs) for evs in by_pkg.values()]
    states.sort(
        key=lambda s: (s.get("purchase") or {}).get("timestamp") or "",
        reverse=True,
    )
    return states


def active_redeemable_packages(events: Iterable[dict]) -> list[dict]:
    return [s for s in states_for_patient(events) if is_redeemable(s)]


# ---------------------------------------------------------------------------
# CPT classification + primary-code selection
# ---------------------------------------------------------------------------
# Spinal CMT codes — value = number of regions (used to pick "most regions wins"
# when several spinal codes appear on the same encounter).
SPINAL_CMT_REGIONS: dict[str, int] = {
    "98940": 1,  # 1-2 regions
    "98941": 2,  # 3-4 regions
    "98942": 3,  # 5 regions
}
EXTREMITY_CMT_CODES: frozenset[str] = frozenset({"98943"})


def _is_spinal_cmt(cpt: str) -> int | None:
    """Returns region rank (1..3) if `cpt` is a spinal CMT code, else None."""
    return SPINAL_CMT_REGIONS.get(cpt)


def _is_extremity_cmt(cpt: str) -> bool:
    return cpt in EXTREMITY_CMT_CODES


def _is_therapy_modality(cpt: str) -> bool:
    """
    97xxx CPT range = physiotherapy / therapeutic modality. Includes hot/cold
    pack (97010), traction (97012), e-stim (97014), ultrasound (97035),
    massage (97124), therapeutic exercise (97110), etc.
    """
    return len(cpt) == 5 and cpt.startswith("97") and cpt[2:].isdigit()


def pick_primary_cpt(cpts: Iterable[str]) -> str:
    """
    Choose the "primary" CPT to use as the headline code for a package
    redemption when multiple CPTs were performed on the same visit.

    Priority order (per clinic policy):
      1. Spinal CMT, more regions wins:        98942 > 98941 > 98940
      2. Extremity CMT:                        98943
      3. First therapy modality (97xxx) in encounter order
      4. First other code in encounter order  (E/M, X-ray, supplies, etc.)

    Returns "" if the iterable is empty (zero-CPT visits still count as a
    package redemption — the patient just used a visit slot).
    """
    cpts_list = [str(c).strip() for c in cpts if str(c).strip()]
    if not cpts_list:
        return ""

    spinals = [c for c in cpts_list if _is_spinal_cmt(c) is not None]
    if spinals:
        return max(spinals, key=lambda c: _is_spinal_cmt(c) or 0)

    for c in cpts_list:
        if _is_extremity_cmt(c):
            return c

    for c in cpts_list:
        if _is_therapy_modality(c):
            return c

    return cpts_list[0]


def packages_covering_cpt(
    events: Iterable[dict],
    cpt: str,
) -> list[dict]:
    """Active+redeemable packages whose whitelist contains the given CPT."""
    cpt = (cpt or "").strip()
    if not cpt:
        return []
    out: list[dict] = []
    for s in active_redeemable_packages(events):
        purchase = s.get("purchase") or {}
        whitelist = set(str(c).strip() for c in (purchase.get("cpt_whitelist") or []))
        if cpt in whitelist:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Refund math — present BOTH strategies side by side (Gap B)
# ---------------------------------------------------------------------------

def compute_refund_quote(
    state: dict,
    *,
    retail_value_per_visit: float | None = None,
) -> dict:
    """
    Returns:
        {
          "purchase_price": float,
          "visits_used": int,
          "visits_remaining": int,
          "prorated_value_per_visit": float,
          "retail_value_per_visit": float,        # for Strategy 2
          "strategy_true_pro_rata": {
              "refund_amount": float,
              "calc": "purchase_price * visits_remaining / total_visits"
          },
          "strategy_retail_audit": {
              "refund_amount": float,
              "calc": "purchase_price - (visits_used * retail_value_per_visit)"
          },
        }

    Both quotes are floored at zero (you cannot owe the patient more than they paid).
    """
    purchase = state.get("purchase") or {}
    total_visits = int(purchase.get("total_visits") or 0)
    purchase_price = float(purchase.get("purchase_price") or 0.0)
    visits_used = int(state.get("visits_used") or 0)
    visits_remaining = max(0, total_visits - visits_used)
    prorated = float(purchase.get("prorated_value_per_visit") or 0.0)
    retail = float(
        retail_value_per_visit
        if retail_value_per_visit is not None
        else purchase.get("retail_value_per_visit") or 0.0
    )

    # Already paid in refunds, subtract from any new quote.
    already_refunded = float(state.get("refund_paid") or 0.0)

    if total_visits > 0:
        prorata = purchase_price * (visits_remaining / total_visits)
    else:
        prorata = 0.0
    prorata = max(0.0, round(prorata - already_refunded, 2))

    audit = purchase_price - (visits_used * retail)
    audit = max(0.0, round(audit - already_refunded, 2))

    return {
        "purchase_price": round(purchase_price, 2),
        "total_visits": total_visits,
        "visits_used": visits_used,
        "visits_remaining": visits_remaining,
        "already_refunded": round(already_refunded, 2),
        "prorated_value_per_visit": round(prorated, 2),
        "retail_value_per_visit": round(retail, 2),
        "strategy_true_pro_rata": {
            "key": REFUND_STRATEGY_TRUE_PRORATA,
            "refund_amount": prorata,
            "calc": f"${purchase_price:,.2f} × {visits_remaining}/{total_visits}"
                    + (f" − already refunded ${already_refunded:,.2f}" if already_refunded else ""),
        },
        "strategy_retail_audit": {
            "key": REFUND_STRATEGY_RETAIL_AUDIT,
            "refund_amount": audit,
            "calc": f"${purchase_price:,.2f} − ({visits_used} × ${retail:,.2f})"
                    + (f" − already refunded ${already_refunded:,.2f}" if already_refunded else ""),
        },
    }


# ---------------------------------------------------------------------------
# Practice-wide totals (deferred revenue, earned revenue) — for reports
# ---------------------------------------------------------------------------

def aggregate_revenue(events: Iterable[dict]) -> dict:
    """
    Sum-up across one patient (caller can sum across patients):
        {
          "package_contracted":  float,   # sum of contract prices ever sold (AR + collected)
          "package_collections": float,   # money actually collected (sum of EVENT_PAYMENT)
          "package_outstanding": float,   # AR — contracted - collected (what patients still owe)
          "package_earned":      float,   # revenue recognized via redemptions
          "package_refunded":    float,   # money returned via refunds
          "package_deferred":    float,   # collected - earned - refunded (liability)
        }
    """
    states = states_for_patient(events)
    contracted = sum(float(s.get("purchase_price") or 0.0) for s in states)
    collections = sum(float(s.get("amount_paid") or 0.0) for s in states)
    outstanding = sum(float(s.get("purchase_balance_due") or 0.0) for s in states)
    earned = sum(float(s.get("value_recognized") or 0.0) for s in states)
    refunded = sum(float(s.get("refund_paid") or 0.0) for s in states)
    deferred = max(0.0, collections - earned - refunded)
    return {
        "package_contracted": round(contracted, 2),
        "package_collections": round(collections, 2),
        "package_outstanding": round(outstanding, 2),
        "package_earned": round(earned, 2),
        "package_refunded": round(refunded, 2),
        "package_deferred": round(deferred, 2),
    }


def earned_revenue_in_range(
    events: Iterable[dict],
    *,
    date_from: str = "",
    date_to: str = "",
) -> float:
    """
    Sum value_recognized of redemption events whose date_of_service (MM/DD/YYYY)
    falls within [date_from, date_to] inclusive. Empty bounds mean unbounded on that side.
    """
    d_from = _parse_md_y(date_from)
    d_to = _parse_md_y(date_to)
    total = 0.0
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != EVENT_REDEMPTION:
            continue
        dos = _parse_md_y(e.get("date_of_service") or "")
        if d_from and (not dos or dos < d_from):
            continue
        if d_to and (not dos or dos > d_to):
            continue
        total += float(e.get("value_recognized") or 0.0)
    return round(total, 2)
