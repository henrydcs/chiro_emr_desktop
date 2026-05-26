# billing_engine.py — Phase 1 shadow billing: clinical services → draft charge lines.
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from insurance_data import INSURANCE_TYPE_BUCKETS, load_patient_policies

# ---------------------------------------------------------------------------
# Exam type classification (aligned with chiro_app, + therapy_only)
# ---------------------------------------------------------------------------

EXAM_TYPES = (
    "initial",
    "re_exam",
    "rof",
    "chiro",
    "therapy_only",
    "final",
)


def classify_exam_type(exam_name: str) -> str | None:
    s = (exam_name or "").strip().lower()
    if not s:
        return None
    if s.startswith("initial"):
        return "initial"
    if s.startswith("re-exam") or s.startswith("reexam"):
        return "re_exam"
    if s.startswith("review of findings"):
        return "rof"
    if "therapy only" in s or s.startswith("therapy only"):
        return "therapy_only"
    if s.startswith("chiro visit"):
        return "chiro"
    if s.startswith("final"):
        return "final"
    return None


# ---------------------------------------------------------------------------
# Payer mode from patient insurance
# ---------------------------------------------------------------------------

_PI_TYPES = frozenset({"auto_pip", "auto_medpay", "auto_liability"})


def determine_payer_mode(patient_root: str | Path | None) -> str:
    """Return 'pi' if primary policy is PI/auto bucket, else 'cash'."""
    if not patient_root:
        return "cash"
    policies = load_patient_policies(patient_root)
    primary = None
    for pol in policies:
        if (pol.get("priority") or "").strip().lower() == "primary":
            primary = pol
            break
    if primary is None and policies:
        primary = policies[0]
    if not primary:
        return "cash"
    itype = (primary.get("insurance_type") or "").strip().lower()
    if itype in _PI_TYPES:
        return "pi"
    bucket = INSURANCE_TYPE_BUCKETS.get(itype, "")
    if bucket == "Personal Injury / Auto":
        return "pi"
    if itype == "cash":
        return "cash"
    return "cash"


# ---------------------------------------------------------------------------
# CPT parsing (mirrors plan_pdf conventions)
# ---------------------------------------------------------------------------

_CPT_RE = re.compile(r"^(\d{5})(?:-([A-Z0-9]{2}))?$", re.I)


def _clean(s: str) -> str:
    return (s or "").strip()


def parse_code_modifier(raw: str) -> tuple[str, str, str]:
    """
    Parse '99213-25: Office visit...' or '98941: Spinal...' or '99213-25'.
    Returns (cpt, modifier, description).
    """
    s = _clean(raw)
    if not s:
        return ("", "", "")
    desc = ""
    if ":" in s:
        left, right = s.split(":", 1)
        s = _clean(left)
        desc = _clean(right)
    m = _CPT_RE.match(s.replace(" ", ""))
    if m:
        return (m.group(1), (m.group(2) or "").upper(), desc)
    # fallback: digits at start
    parts = s.split("-", 1)
    code = _clean(parts[0])
    mod = _clean(parts[1]).upper() if len(parts) > 1 else ""
    if code.isdigit() and len(code) == 5:
        return (code, mod, desc)
    return ("", "", desc)


def split_service_key(key: str) -> tuple[str, str]:
    """'97110: Therapeutic exercise' -> ('97110', 'Therapeutic exercise')."""
    s = _clean(key)
    if not s:
        return ("", "")
    if ": " in s:
        a, b = s.split(": ", 1)
        return (_clean(a), _clean(b))
    if ":" in s:
        a, b = s.split(":", 1)
        return (_clean(a), _clean(b))
    return (_clean(s), "")


def is_no_cmt(cmt_code: str) -> bool:
    s = _clean(cmt_code).lower()
    return not s or s.startswith("0000") or "no cmt" in s


# ---------------------------------------------------------------------------
# Diagnosis extraction
# ---------------------------------------------------------------------------


def extract_diagnosis_codes(diagnosis_struct: dict | None, *, limit: int = 4) -> list[str]:
    codes: list[str] = []
    if not isinstance(diagnosis_struct, dict):
        return codes
    for blk in diagnosis_struct.get("blocks") or []:
        if not isinstance(blk, dict):
            continue
        code = _clean(blk.get("icd10", ""))
        if code and code not in codes:
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


# ---------------------------------------------------------------------------
# Units (clinic-configurable rule; default 15-minute units for timed therapy)
# ---------------------------------------------------------------------------


def therapy_units_from_minutes(minutes: int, *, minutes_per_unit: int = 15) -> int:
    if minutes <= 0:
        return 0
    if minutes < 8:
        return 0
    # CMS-style simplified: bill in 15-min increments, minimum 1 unit when >= 8 min
    units = max(1, (minutes + minutes_per_unit - 1) // minutes_per_unit)
    return units


def aggregate_therapy_units(parts: dict) -> int:
    """Sum minutes across checked regions for one modality; convert to units."""
    total_min = 0
    if not isinstance(parts, dict):
        return 0
    for _region, val in parts.items():
        if not isinstance(val, (list, tuple)) or len(val) < 2:
            continue
        try:
            checked = bool(val[0])
        except Exception:
            checked = False
        if not checked:
            continue
        try:
            mins = int(_clean(str(val[1])) or "0")
        except ValueError:
            mins = 0
        total_min += max(0, mins)
    return therapy_units_from_minutes(total_min)


# ---------------------------------------------------------------------------
# Charge line builder
# ---------------------------------------------------------------------------

_LINE_ID = 0


def _new_line_id() -> str:
    global _LINE_ID
    _LINE_ID += 1
    return f"cl_{uuid.uuid4().hex[:12]}"


def _make_line(
    *,
    cpt: str,
    modifier: str = "",
    description: str = "",
    units: float = 1,
    service_path: str,
    diagnosis_pointers: list[str],
    place_of_service: str = "11",
) -> dict[str, Any]:
    return {
        "charge_line_id": _new_line_id(),
        "cpt_code": cpt,
        "modifier_1": modifier or None,
        "modifier_2": None,
        "description": description,
        "units": float(units) if units else 1.0,
        "diagnosis_pointers": list(diagnosis_pointers),
        "place_of_service": place_of_service,
        "source": {"service_path": service_path},
        "status": "draft",
    }


def build_charge_lines_from_services(
    services: dict,
    diagnosis_pointers: list[str],
) -> list[dict[str, Any]]:
    """Transform plan.services into draft charge lines."""
    services = services if isinstance(services, dict) else {}
    lines: list[dict[str, Any]] = []

    cmt_code = _clean(services.get("cmt_code", ""))
    if cmt_code and not is_no_cmt(cmt_code):
        cpt, mod, desc = parse_code_modifier(cmt_code)
        if cpt:
            lines.append(
                _make_line(
                    cpt=cpt,
                    modifier=mod,
                    description=desc or "Chiropractic manipulative treatment",
                    units=1,
                    service_path="plan.services.cmt_code",
                    diagnosis_pointers=diagnosis_pointers,
                )
            )

    em_raw = _clean(services.get("em_code", "")) or _clean(services.get("exam_code", ""))
    if em_raw:
        cpt, mod, desc = parse_code_modifier(em_raw)
        if cpt:
            lines.append(
                _make_line(
                    cpt=cpt,
                    modifier=mod,
                    description=desc or "Evaluation and management",
                    units=1,
                    service_path="plan.services.em_code",
                    diagnosis_pointers=diagnosis_pointers,
                )
            )

    therapy_data = services.get("therapy_data") or {}
    if isinstance(therapy_data, dict):
        for therapy_key, parts in therapy_data.items():
            if not isinstance(parts, dict) or not parts:
                continue
            code, desc = split_service_key(therapy_key)
            if not code:
                continue
            units = aggregate_therapy_units(parts)
            if units <= 0:
                continue
            lines.append(
                _make_line(
                    cpt=code,
                    description=desc or "Therapy modality",
                    units=units,
                    service_path=f"plan.services.therapy_data.{therapy_key}",
                    diagnosis_pointers=diagnosis_pointers,
                )
            )

    return lines


# ---------------------------------------------------------------------------
# Validation warnings (appointment-type expectations)
# ---------------------------------------------------------------------------

_VALIDATION_RULES: dict[str, dict[str, Any]] = {
    "initial": {
        "expect_em": True,
        "warn_cmt_without_em": True,
        "unexpected": [],
    },
    "re_exam": {
        "expect_em": True,
        "expect_em_modifier_25": True,
        "expect_cmt": True,
    },
    "rof": {
        "warn_cmt": True,
        "warn_em": False,
    },
    "chiro": {
        "expect_cmt": True,
    },
    "therapy_only": {
        "forbid_cmt": True,
        "forbid_em": True,
        "expect_therapy": True,
    },
    "final": {
        "note": "Final visits may include discharge E/M; confirm billable intent.",
    },
}


def validate_shadow_encounter(
    *,
    exam_type: str | None,
    services: dict,
    lines: list[dict],
    diagnosis_pointers: list[str],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    services = services if isinstance(services, dict) else {}

    has_cmt = bool(_clean(services.get("cmt_code", ""))) and not is_no_cmt(
        services.get("cmt_code", "")
    )
    has_em = bool(
        _clean(services.get("em_code", "")) or _clean(services.get("exam_code", ""))
    )
    has_therapy = bool(lines) and any(
        "therapy_data" in (ln.get("source") or {}).get("service_path", "")
        for ln in lines
    )
    if not has_therapy:
        td = services.get("therapy_data") or {}
        has_therapy = isinstance(td, dict) and any(
            isinstance(v, dict) and v for v in td.values()
        )

    if not diagnosis_pointers:
        warnings.append(
            {
                "level": "warning",
                "code": "missing_dx",
                "message": "No ICD-10 codes on the Diagnosis page — charge lines need diagnosis pointers.",
            }
        )

    if not lines:
        warnings.append(
            {
                "level": "info",
                "code": "no_services",
                "message": "No billable services in Services Provided Today for this visit.",
            }
        )

    rules = _VALIDATION_RULES.get(exam_type or "", {})
    if not exam_type:
        return warnings

    if rules.get("expect_em") and not has_em:
        warnings.append(
            {
                "level": "warning",
                "code": "missing_em",
                "message": f"{exam_type.replace('_', ' ').title()} visits usually include an E/M code.",
            }
        )

    if rules.get("expect_em_modifier_25") and has_em:
        em_raw = _clean(services.get("em_code", "")) or _clean(services.get("exam_code", ""))
        cpt, mod, _ = parse_code_modifier(em_raw)
        if cpt and mod != "25":
            warnings.append(
                {
                    "level": "warning",
                    "code": "em_missing_25",
                    "message": "Re-exam E/M is often billed with modifier -25 when CMT is performed same day.",
                }
            )

    if rules.get("expect_cmt") and not has_cmt:
        warnings.append(
            {
                "level": "warning",
                "code": "missing_cmt",
                "message": "Chiro visit types usually include a CMT code (not No CMT).",
            }
        )

    if rules.get("warn_cmt") and has_cmt:
        warnings.append(
            {
                "level": "info",
                "code": "unexpected_cmt",
                "message": "Review of Findings visits often do not include CMT — confirm billable intent.",
            }
        )

    if rules.get("forbid_cmt") and has_cmt:
        warnings.append(
            {
                "level": "warning",
                "code": "therapy_only_cmt",
                "message": "Therapy Only visits should not include CMT.",
            }
        )

    if rules.get("forbid_em") and has_em:
        warnings.append(
            {
                "level": "warning",
                "code": "therapy_only_em",
                "message": "Therapy Only visits should not include E/M.",
            }
        )

    if rules.get("expect_therapy") and not has_therapy:
        warnings.append(
            {
                "level": "warning",
                "code": "therapy_only_empty",
                "message": "Therapy Only visits should include at least one modality.",
            }
        )

    if rules.get("warn_cmt_without_em") and has_cmt and not has_em:
        warnings.append(
            {
                "level": "warning",
                "code": "cmt_without_em",
                "message": "Initial visit with CMT but no E/M — confirm documentation supports billing.",
            }
        )

    note = rules.get("note")
    if note:
        warnings.append({"level": "info", "code": "type_note", "message": note})

    return warnings


# ---------------------------------------------------------------------------
# Full encounter build from exam JSON
# ---------------------------------------------------------------------------


def load_exam_payload(exam_path: str | Path) -> dict:
    p = Path(exam_path)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    return data if isinstance(data, dict) else {}


def build_shadow_encounter(
    *,
    exam_path: str | Path,
    patient_root: str | Path | None = None,
    fee_lookup: Any = None,
) -> dict[str, Any]:
    """
    Build a shadow billing encounter dict from a saved exam JSON file.
    fee_lookup: callable(cpt, modifier, schedule) -> float | None
    """
    payload = load_exam_payload(exam_path)
    exam_name = _clean(payload.get("exam", "")) or Path(exam_path).stem
    patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else {}
    exam_date = _clean(patient.get("exam_date", ""))
    provider = _clean(patient.get("provider", ""))
    soap = payload.get("soap") if isinstance(payload.get("soap"), dict) else {}
    plan = soap.get("plan") if isinstance(soap.get("plan"), dict) else {}
    services = plan.get("services") if isinstance(plan.get("services"), dict) else {}
    dx_struct = soap.get("diagnosis_struct") if isinstance(soap.get("diagnosis_struct"), dict) else {}
    dx_codes = extract_diagnosis_codes(dx_struct)

    exam_type = classify_exam_type(exam_name)
    lines = build_charge_lines_from_services(services, dx_codes)
    warnings = validate_shadow_encounter(
        exam_type=exam_type,
        services=services,
        lines=lines,
        diagnosis_pointers=dx_codes,
    )

    payer_mode = determine_payer_mode(patient_root)
    schedules = ("cash", "pi_ucr")
    totals: dict[str, float] = {}
    line_fees: dict[str, dict[str, float]] = {}

    for ln in lines:
        cpt = ln.get("cpt_code") or ""
        mod = ln.get("modifier_1") or ""
        fees: dict[str, float] = {}
        for sch in schedules:
            amt = 0.0
            if fee_lookup:
                try:
                    v = fee_lookup(cpt, mod, sch)
                    if v is not None:
                        amt = float(v)
                except Exception:
                    amt = 0.0
            fees[sch] = round(amt * float(ln.get("units") or 1), 2)
        line_fees[ln["charge_line_id"]] = fees
        ln["fees"] = fees

    for sch in schedules:
        totals[sch] = round(
            sum(line_fees[lid].get(sch, 0) for lid in line_fees),
            2,
        )

    enc_id = f"enc_{uuid.uuid4().hex[:12]}"

    # Phase 5 — Package deals: attach per-line redemption suggestions when the
    # patient is on cash payer mode and has an active package whose whitelist
    # contains the CPT. Caller (BillingPage cash-checkout flow) uses this hint
    # to prompt the user before posting.
    package_meta: dict = {"suggested_redemptions": [], "active_package_count": 0}
    if patient_root and payer_mode == "cash":
        try:
            from package_engine import (
                active_redeemable_packages,
                packages_covering_cpt,
            )
            from package_storage import load_package_log

            events = load_package_log(patient_root).get("events") or []
            active = active_redeemable_packages(events)
            package_meta["active_package_count"] = len(active)
            if active:
                for ln in lines:
                    cpt = (ln.get("cpt_code") or "").strip()
                    if not cpt:
                        continue
                    covering = packages_covering_cpt(events, cpt)
                    if not covering:
                        continue
                    fees = ln.get("fees") or {}
                    pkg_options = []
                    for s in covering:
                        purchase = s.get("purchase") or {}
                        pkg_options.append({
                            "package_id": s.get("package_id") or "",
                            "catalog_id": purchase.get("catalog_id") or "",
                            "name": purchase.get("name") or "",
                            "visits_remaining": int(s.get("visits_remaining") or 0),
                            "prorated_value_per_visit": float(
                                purchase.get("prorated_value_per_visit") or 0.0
                            ),
                            "expires_on": purchase.get("expiration_date") or "",
                        })
                    package_meta["suggested_redemptions"].append({
                        "charge_line_id": ln.get("charge_line_id") or "",
                        "cpt": cpt,
                        "description": ln.get("description") or "",
                        "full_fee_cash": float(fees.get("cash") or 0.0),
                        "package_options": pkg_options,
                    })
        except Exception:
            # Never let package lookup break shadow encounter generation.
            package_meta = {"suggested_redemptions": [], "active_package_count": 0}

    return {
        "encounter_id": enc_id,
        "exam_path": str(Path(exam_path).resolve()),
        "exam_name": exam_name,
        "exam_type": exam_type,
        "date_of_service": exam_date,
        "provider": provider,
        "payer_mode_suggested": payer_mode,
        "status": "shadow",
        "phase": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "diagnosis_pointers": dx_codes,
        "lines": lines,
        "warnings": warnings,
        "totals": totals,
        "primary_schedule": "cash" if payer_mode == "cash" else "pi_ucr",
        "package_meta": package_meta,
    }
