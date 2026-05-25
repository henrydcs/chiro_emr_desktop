# billing_case_export.py — PI case ledger summary export (TXT + CSV).
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from billing_pi_case import case_status_label, load_pi_case
from billing_pi_ledger import compute_pi_balance, list_pi_posted_encounters, load_pi_ledger
from billing_storage import patient_billing_root
from config import CLINIC_NAME
from shell_app import read_patient_profile


def build_case_summary_text(
    *,
    patient_root: str | Path,
    patient_name: str,
    date_from: str = "",
    date_to: str = "",
) -> str:
    case = load_pi_case(patient_root) or {}
    bal = compute_pi_balance(patient_root)
    profile = read_patient_profile(Path(patient_root))
    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()

    atty = case.get("attorney") or {}
    atty_line = (atty.get("name") or "").strip()
    if atty.get("firm"):
        atty_line = f"{atty_line} — {atty['firm']}".strip(" —")

    lines = [
        clinic,
        "PI CASE BILLING SUMMARY",
        "=" * 56,
        f"Patient: {patient_name}",
        f"DOB: {(profile.get('dob') or '').strip() or '—'}",
        f"Date of injury: {(case.get('date_of_injury') or '').strip() or '—'}",
        f"Claim #: {(case.get('claim_number') or '').strip() or '—'}",
        f"Case status: {case_status_label(case.get('case_status') or 'active')}",
        f"Attorney: {atty_line or '—'}",
        "",
        "Carriers:",
    ]
    carriers = case.get("carriers") or []
    if carriers:
        for c in carriers:
            if isinstance(c, dict):
                lines.append(
                    f"  • {c.get('type_label') or c.get('insurance_type')}: "
                    f"{c.get('carrier_name') or '—'}  "
                    f"Claim {c.get('claim_number') or '—'}"
                )
    else:
        lines.append("  (none on file)")

    if date_from or date_to:
        lines.extend(["", f"Date range: {date_from or 'start'} — {date_to or 'end'}"])

    lines.extend(
        [
            "",
            "FINANCIAL SUMMARY (PI / UCR)",
            "-" * 56,
            f"Total charges:    ${bal['total_charges']:>12,.2f}",
            f"Payments:         ${bal['total_payments']:>12,.2f}",
            f"Adjustments:      ${bal['total_adjustments']:>12,.2f}",
            f"Balance due:      ${bal['balance_due']:>12,.2f}",
            "",
        ]
    )
    settlement = case.get("settlement") or {}
    if settlement and isinstance(settlement, dict):
        lines.extend(
            [
                "SETTLEMENT (on file)",
                "-" * 56,
                f"Settlement payment: ${float(settlement.get('amount') or 0):>12,.2f}",
                f"Write-off:          ${float(settlement.get('write_off') or 0):>12,.2f}",
                f"Payment date:       {(settlement.get('payment_date') or '—')}",
                f"Memo:               {(settlement.get('memo') or '—')[:40]}",
                "",
            ]
        )

    lines.extend(
        [
            "VISITS / CHARGE DETAIL",
            "-" * 56,
        ]
    )

    visits = list_pi_posted_encounters(patient_root)
    for enc in visits:
        dos = enc.get("date_of_service") or "—"
        if date_from and _dos_before(dos, date_from):
            continue
        if date_to and _dos_after(dos, date_to):
            continue
        lines.append(
            f"\n{dos}  ·  {enc.get('exam_name') or 'Visit'}  "
            f"·  ${float(enc.get('amount_charged') or 0):,.2f}"
        )
        for ln in enc.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            cpt = ln.get("cpt_code") or ""
            mod = ln.get("modifier_1") or ""
            mod_s = f"-{mod}" if mod else ""
            units = ln.get("units") or 1
            amt = float(ln.get("amount") or 0)
            dx = ", ".join(ln.get("diagnosis_pointers") or [])
            lines.append(f"    {cpt}{mod_s}  x{units:g}  ${amt:,.2f}  DX {dx or '—'}")

    lines.extend(["", "PAYMENTS & ADJUSTMENTS", "-" * 56])
    for ent in load_pi_ledger(patient_root).get("entries") or []:
        if not isinstance(ent, dict):
            continue
        t = ent.get("type")
        if t == "charge":
            continue
        amt = float(ent.get("amount") or 0)
        d = ent.get("payment_date") or ent.get("recorded_at", "")[:10]
        if t == "payment":
            lines.append(
                f"  Payment {d}: ${amt:,.2f}  "
                f"from {(ent.get('payer') or 'other').title()}  "
                f"{(ent.get('memo') or '')[:40]}"
            )
        elif t == "adjustment":
            lines.append(f"  Adjustment {d}: ${amt:,.2f}  {(ent.get('memo') or '')[:50]}")

    lines.extend(
        [
            "",
            f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
        ]
    )
    return "\n".join(lines)


def build_case_lines_csv(
    patient_root: str | Path,
    *,
    date_from: str = "",
    date_to: str = "",
) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "date_of_service",
            "exam_name",
            "cpt",
            "modifier",
            "units",
            "amount",
            "diagnosis",
            "provider",
        ]
    )
    for enc in list_pi_posted_encounters(patient_root):
        dos = enc.get("date_of_service") or ""
        if date_from and _dos_before(dos, date_from):
            continue
        if date_to and _dos_after(dos, date_to):
            continue
        dos = enc.get("date_of_service") or ""
        exam = enc.get("exam_name") or ""
        prov = enc.get("provider") or ""
        for ln in enc.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            w.writerow(
                [
                    dos,
                    exam,
                    ln.get("cpt_code") or "",
                    ln.get("modifier_1") or "",
                    ln.get("units") or 1,
                    f"{float(ln.get('amount') or 0):.2f}",
                    ";".join(ln.get("diagnosis_pointers") or []),
                    prov,
                ]
            )
    return buf.getvalue()


def _parse_mmddyyyy(s: str):
    try:
        return datetime.strptime((s or "").strip(), "%m/%d/%Y")
    except Exception:
        return None


def _dos_before(dos: str, bound: str) -> bool:
    d, b = _parse_mmddyyyy(dos), _parse_mmddyyyy(bound)
    return bool(d and b and d < b)


def _dos_after(dos: str, bound: str) -> bool:
    d, b = _parse_mmddyyyy(dos), _parse_mmddyyyy(bound)
    return bool(d and b and d > b)


def save_case_exports(
    patient_root: str | Path,
    *,
    patient_name: str,
    date_from: str = "",
    date_to: str = "",
) -> tuple[Path, Path]:
    root = patient_billing_root(patient_root)
    exp = root / "exports"
    exp.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    txt_path = exp / f"pi_case_summary_{stamp}.txt"
    csv_path = exp / f"pi_case_lines_{stamp}.csv"

    txt_path.write_text(
        build_case_summary_text(
            patient_root=patient_root,
            patient_name=patient_name,
            date_from=date_from,
            date_to=date_to,
        ),
        encoding="utf-8",
    )
    csv_path.write_text(
        build_case_lines_csv(patient_root, date_from=date_from, date_to=date_to),
        encoding="utf-8",
    )
    from billing_receipt import archive_pi_summary_to_receipts

    archive_pi_summary_to_receipts(patient_root, txt_path.read_text(encoding="utf-8"))
    return txt_path, csv_path
