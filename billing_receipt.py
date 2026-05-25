# billing_receipt.py — Cash receipts and PI case billing documents.
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX
from billing_ledger import compute_cash_balance, encounter_amount_due, load_posted_encounter
from billing_storage import patient_billing_root

_DOC_PREFIX_LABELS: tuple[tuple[str, str], ...] = (
    ("settlement_", "PI settlement"),
    ("pi_case_summary_", "PI case summary"),
    ("pi_cover_sheet_", "PI cover sheet"),
    ("receipt_", "Cash receipt"),
)


@dataclass(frozen=True)
class BillingDocument:
    path: Path
    label: str
    kind: str
    mtime: float


def _line_items_text(lines: list) -> list[str]:
    out: list[str] = []
    for ln in lines or []:
        if not isinstance(ln, dict):
            continue
        cpt = ln.get("cpt_code") or ""
        mod = ln.get("modifier_1") or ""
        mod_s = f"-{mod}" if mod else ""
        desc = (ln.get("description") or "")[:40]
        units = ln.get("units") or 1
        amt = float(ln.get("amount") or (ln.get("fees") or {}).get("cash") or 0)
        out.append(f"  {cpt}{mod_s}  x{units:g}  ${amt:,.2f}  {desc}")
    return out


def build_receipt_text(
    *,
    patient_name: str,
    posted: dict,
    payment: dict | None = None,
    account_balance: float | None = None,
    patient_root: str | Path | None = None,
) -> str:
    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()
    addr = (CLINIC_ADDR or "").strip()
    phone = (CLINIC_PHONE_FAX or "").strip()

    total = float(posted.get("amount_charged") or 0)
    dos = posted.get("date_of_service") or "—"
    exam = posted.get("exam_name") or "Visit"
    provider = posted.get("provider") or ""

    lines_out = [
        clinic,
        addr,
        phone,
        "",
        "PAYMENT RECEIPT" if payment else "SERVICE RECEIPT",
        "=" * 42,
        f"Patient: {patient_name}",
        f"Date of service: {dos}",
        f"Visit: {exam}",
    ]
    if provider:
        lines_out.append(f"Provider: {provider}")
    lines_out.extend(["", "Charges:"])
    lines_out.extend(_line_items_text(posted.get("lines") or []))
    lines_out.append("")
    lines_out.append(f"Visit total: ${total:,.2f}")

    exam_path = posted.get("exam_path") or ""
    visit_due: float | None = None
    if patient_root and exam_path:
        visit_due = encounter_amount_due(patient_root, exam_path)

    if payment:
        pamt = float(payment.get("amount") or 0)
        method = (payment.get("method") or "cash").title()
        pdate = payment.get("payment_date") or ""
        lines_out.append(f"Paid today ({method}): ${pamt:,.2f}")
        if pdate:
            lines_out.append(f"Payment date: {pdate}")
        if visit_due is None:
            visit_due = round(max(0.0, total - pamt), 2)

    if visit_due is not None:
        if visit_due <= 0.01:
            lines_out.append("Visit balance: PAID IN FULL")
        else:
            lines_out.append(f"Visit balance: ${visit_due:,.2f}")
    elif not payment:
        lines_out.append(f"Visit balance: ${total:,.2f}")

    if account_balance is not None:
        lines_out.append(f"Account balance (all visits): ${account_balance:,.2f}")

    lines_out.extend(
        [
            "",
            f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
            "",
            "Thank you for your visit.",
        ]
    )
    return "\n".join(lines_out)


def build_settlement_receipt_text(
    *,
    patient_name: str,
    patient_root: str | Path,
    settlement_amount: float,
    write_off: float,
    balance_before: float,
    payment_date: str,
    payer: str,
    memo: str,
) -> str:
    from billing_pi_case import case_status_label, load_pi_case
    from billing_pi_ledger import compute_pi_balance

    clinic = (CLINIC_NAME or "Chiropractic Clinic").strip()
    addr = (CLINIC_ADDR or "").strip()
    phone = (CLINIC_PHONE_FAX or "").strip()
    case = load_pi_case(patient_root) or {}
    bal = compute_pi_balance(patient_root)

    lines_out = [
        clinic,
        addr,
        phone,
        "",
        "PI CASE SETTLEMENT RECEIPT",
        "=" * 48,
        f"Patient: {patient_name}",
        f"Case status: {case_status_label(case.get('case_status') or 'active')}",
        f"Date of injury: {(case.get('date_of_injury') or '').strip() or '—'}",
        "",
        "SETTLEMENT",
        "-" * 48,
        f"Received from: {(payer or 'attorney').strip().title()}",
        f"Payment date: {payment_date or '—'}",
        f"Settlement amount: ${float(settlement_amount):,.2f}",
    ]
    if write_off > 0.01:
        lines_out.append(f"Write-off (auto): ${float(write_off):,.2f}")
    lines_out.extend(
        [
            f"Balance before settlement: ${float(balance_before):,.2f}",
            f"Case balance now: ${bal['balance_due']:,.2f}",
            "",
            "CASE TOTALS (PI / UCR)",
            "-" * 48,
            f"Total charges: ${bal['total_charges']:,.2f}",
            f"Total payments: ${bal['total_payments']:,.2f}",
            f"Total adjustments: ${bal['total_adjustments']:,.2f}",
        ]
    )
    if memo:
        lines_out.extend(["", f"Memo: {memo}"])
    lines_out.extend(
        [
            "",
            f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
            "",
            "Confidential — for billing records.",
        ]
    )
    return "\n".join(lines_out)


def document_display_label(path: Path, *, source: str = "") -> str:
    """Human label for a billing document path."""
    stem = path.stem
    for prefix, title in _DOC_PREFIX_LABELS:
        if stem.startswith(prefix):
            stamp = stem[len(prefix) :]
            try:
                when = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
                return f"{title} · {when.strftime('%m/%d/%Y %I:%M %p')}"
            except ValueError:
                return f"{title} · {path.name}"
    if source:
        return f"{source} · {path.name}"
    try:
        when = datetime.fromtimestamp(path.stat().st_mtime)
        return f"{path.name} · {when.strftime('%m/%d/%Y %I:%M %p')}"
    except OSError:
        return path.name


def list_billing_documents(patient_root: str | Path) -> list[BillingDocument]:
    """All viewable billing text documents (receipts folder, exports, packet summaries)."""
    root = patient_billing_root(patient_root)
    seen: set[str] = set()
    docs: list[BillingDocument] = []

    def _add(path: Path, label: str, kind: str) -> None:
        key = str(path.resolve())
        if key in seen or not path.is_file():
            return
        seen.add(key)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        docs.append(BillingDocument(path=path, label=label, kind=kind, mtime=mtime))

    rec_dir = root / "receipts"
    if rec_dir.is_dir():
        for p in rec_dir.glob("*.txt"):
            _add(p, document_display_label(p), "receipt")

    exp_dir = root / "exports"
    if exp_dir.is_dir():
        for p in exp_dir.glob("pi_case_summary_*.txt"):
            _add(p, document_display_label(p, source="Export"), "export")

    packets_dir = root / "packets"
    if packets_dir.is_dir():
        for packet in sorted(
            (d for d in packets_dir.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        ):
            for fname, title in (
                ("01_case_billing_summary.txt", "Packet summary"),
                ("00_cover_sheet.txt", "Packet cover"),
            ):
                p = packet / fname
                if p.is_file():
                    _add(
                        p,
                        f"{title} · {packet.name}",
                        "packet",
                    )

    docs.sort(key=lambda d: d.mtime, reverse=True)
    return docs


def list_receipt_files(patient_root: str | Path) -> list[Path]:
    """Backward-compatible: paths in receipts/ only."""
    return [d.path for d in list_billing_documents(patient_root) if d.kind == "receipt"]


def receipt_display_label(path: Path) -> str:
    return document_display_label(path)


def archive_pi_summary_to_receipts(
    patient_root: str | Path,
    summary_text: str,
    *,
    cover_text: str | None = None,
) -> list[Path]:
    """Copy PI case summary (and optional cover) into billing/receipts for Receipt folder."""
    saved: list[Path] = []
    saved.append(save_receipt_file(patient_root, summary_text, prefix="pi_case_summary"))
    if cover_text:
        saved.append(save_receipt_file(patient_root, cover_text, prefix="pi_cover_sheet"))
    return saved


def patient_receipts_dir(patient_root: str | Path) -> Path:
    d = patient_billing_root(patient_root) / "receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_receipts_folder(patient_root: str | Path) -> None:
    p = str(patient_receipts_dir(patient_root).resolve())
    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')


def save_receipt_file(
    patient_root: str | Path,
    text: str,
    *,
    prefix: str = "receipt",
) -> Path:
    rec_dir = patient_receipts_dir(patient_root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = rec_dir / f"{prefix}_{stamp}.txt"
    path.write_text(text, encoding="utf-8")
    return path
