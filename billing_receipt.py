# billing_receipt.py — Cash receipts and PI case billing documents.
from __future__ import annotations

import os
import re
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
    ("insurance_eob_", "Insurance EOB"),
    ("insurance_claim_", "Insurance claim"),
    ("insurance_statement_", "Insurance statement"),
)


@dataclass(frozen=True)
class BillingDocument:
    path: Path
    label: str
    kind: str
    mtime: float
    stream: str = "other"  # one of: cash, package, pi, insurance, membership, export, packet, other
    # Optional sidecar .txt path for inline previewing. Used when `path` is a
    # PDF (or doesn't exist yet — lazy generation) but a text version of the
    # same receipt is available on disk. The dialog reads this for the preview
    # pane so the user can see the receipt without opening the PDF viewer.
    text_sidecar: Path | None = None


# All money streams that get their own receipts subfolder. The dialog and the
# per-tab "Receipt folder" buttons use this list as the canonical source so
# adding a new stream in one place propagates everywhere.
RECEIPT_STREAMS: tuple[str, ...] = ("cash", "package", "pi", "insurance", "membership")

# Display labels for each stream (used in dialog titles / row prefixes).
STREAM_DISPLAY_LABELS: dict[str, str] = {
    "cash": "Cash",
    "package": "Package",
    "pi": "PI",
    "insurance": "Insurance",
    "membership": "Membership",
}


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


_CASH_DATE_RE = re.compile(
    r"Date of service:\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", re.IGNORECASE
)
_LEGACY_STAMP_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})_\d{6}$")


def _parse_cash_receipt_date(text_path: Path) -> str:
    """Parse 'Date of service: MM/DD/YYYY' from a cash receipt text file. '' if not found."""
    try:
        text = text_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _CASH_DATE_RE.search(text)
    if not m:
        return ""
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    if len(yy) == 2:
        yy = "20" + yy
    try:
        return f"{int(mm):02d}/{int(dd):02d}/{int(yy):04d}"
    except ValueError:
        return ""


def _date_from_legacy_stamp(stem: str) -> str:
    """Try to parse YYYYMMDD from a legacy timestamped stem like 'receipt_20260525_181234'."""
    m = _LEGACY_STAMP_RE.search(stem)
    if not m:
        return ""
    yy, mm, dd = m.group(1), m.group(2), m.group(3)
    try:
        return f"{int(mm):02d}/{int(dd):02d}/{int(yy):04d}"
    except ValueError:
        return ""


def _collect_cash_receipts(cash_dir: Path) -> list[BillingDocument]:
    """
    Group cash receipt files by stem and return one BillingDocument per visit.

    Cash receipts come in pairs (.txt + .pdf) keyed by encounter_id, but either
    file may be missing. Per the user's request the dialog shows ONE row per
    visit (no .txt duplicate), labeled "Cash Rcpt, MM/DD/YYYY, PDF".

    The canonical `path` is the .pdf (real or planned — lazy-generated on
    double-click). The `.txt` sibling, when present, is attached as
    `text_sidecar` so the dialog can preview the receipt text inline without
    opening the PDF viewer.
    """
    if not cash_dir.is_dir():
        return []

    by_stem: dict[str, dict] = {}
    for p in cash_dir.iterdir():
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in {".pdf", ".txt"}:
            continue
        info = by_stem.setdefault(p.stem, {"pdf": None, "txt": None, "mtime": 0.0})
        if suf == ".pdf":
            info["pdf"] = p
        else:
            info["txt"] = p
        try:
            info["mtime"] = max(info["mtime"], p.stat().st_mtime)
        except OSError:
            pass

    out: list[BillingDocument] = []
    for stem, info in by_stem.items():
        pdf_path = info["pdf"]
        txt_path = info["txt"]
        canonical = pdf_path if pdf_path is not None else (cash_dir / f"{stem}.pdf")
        date_str = ""
        if txt_path is not None:
            date_str = _parse_cash_receipt_date(txt_path)
        if not date_str:
            date_str = _date_from_legacy_stamp(stem)
        if not date_str and info["mtime"]:
            try:
                date_str = datetime.fromtimestamp(info["mtime"]).strftime("%m/%d/%Y")
            except (OSError, ValueError):
                date_str = ""
        label = f"Cash Rcpt, {date_str or '—'}, PDF"
        out.append(
            BillingDocument(
                path=canonical,
                label=label,
                kind="receipt",
                mtime=info["mtime"],
                stream="cash",
                text_sidecar=txt_path,
            )
        )
    return out


_PKG_STMT_DATE_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})$")


def _collect_package_receipts(
    pkg_dir: Path, patient_root: str | Path
) -> list[BillingDocument]:
    """
    Group package receipt files by stem (one row per .pdf/.txt pair) and label
    them per the user's request:

      * `<Plan Name>, MM/DD/YYYY, PDF`   — statements (one per day per package)
      * `<Plan Name> Contract, PDF`      — contracts (one per package)

    The .txt sidecar (if present) is attached as `text_sidecar` so the dialog
    can preview the receipt content inline; double-click then lazy-generates
    the .pdf when missing.
    """
    if not pkg_dir.is_dir():
        return []

    # Lazy-import to avoid a circular dependency at module load time.
    try:
        from package_storage import find_purchase_event
    except Exception:
        find_purchase_event = None  # type: ignore[assignment]

    by_stem: dict[str, dict] = {}
    for p in pkg_dir.iterdir():
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in {".pdf", ".txt"}:
            continue
        info = by_stem.setdefault(p.stem, {"pdf": None, "txt": None, "mtime": 0.0})
        if suf == ".pdf":
            info["pdf"] = p
        else:
            info["txt"] = p
        try:
            info["mtime"] = max(info["mtime"], p.stat().st_mtime)
        except OSError:
            pass

    out: list[BillingDocument] = []
    for stem, info in by_stem.items():
        pdf_path = info["pdf"]
        txt_path = info["txt"]
        canonical = pdf_path if pdf_path is not None else (pkg_dir / f"{stem}.pdf")

        kind = ""
        package_id = ""
        date_str = ""
        if stem.startswith("package_contract_"):
            kind = "contract"
            package_id = stem[len("package_contract_"):]
        elif stem.startswith("package_statement_"):
            kind = "statement"
            rest = stem[len("package_statement_"):]
            m = _PKG_STMT_DATE_RE.search(rest)
            if m:
                package_id = rest[: m.start()]
                date_str = f"{int(m.group(2)):02d}/{int(m.group(3)):02d}/{int(m.group(1)):04d}"
            else:
                package_id = rest

        # Plan name lookup — best-effort. Falls back gracefully for legacy
        # files where the package may no longer exist in storage.
        plan_name = ""
        if package_id and find_purchase_event is not None:
            try:
                purchase = find_purchase_event(patient_root, package_id)
                if purchase:
                    plan_name = purchase.get("name") or ""
            except Exception:
                plan_name = ""
        if not plan_name:
            plan_name = "Package"  # safe default

        # Fallback date for statements when filename has no _YYYYMMDD suffix
        if kind == "statement" and not date_str:
            mt = info["mtime"]
            if mt:
                try:
                    date_str = datetime.fromtimestamp(mt).strftime("%m/%d/%Y")
                except (OSError, ValueError):
                    date_str = ""

        if kind == "contract":
            label = f"{plan_name} Contract, PDF"
        elif kind == "statement":
            label = f"{plan_name}, {date_str or '—'}, PDF"
        else:
            # Unknown package filename pattern — surface it but generically.
            label = f"Package · {stem}"

        out.append(
            BillingDocument(
                path=canonical,
                label=label,
                kind="receipt",
                mtime=info["mtime"],
                stream="package",
                text_sidecar=txt_path,
            )
        )
    return out


def _collect_insurance_receipts(ins_dir: Path) -> list[BillingDocument]:
    """One row per insurance .pdf/.txt pair (EOB, claim summary, statement)."""
    if not ins_dir.is_dir():
        return []
    by_stem: dict[str, dict] = {}
    for p in ins_dir.iterdir():
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf not in {".pdf", ".txt"}:
            continue
        info = by_stem.setdefault(p.stem, {"pdf": None, "txt": None, "mtime": 0.0})
        if suf == ".pdf":
            info["pdf"] = p
        else:
            info["txt"] = p
        try:
            info["mtime"] = max(info["mtime"], p.stat().st_mtime)
        except OSError:
            pass

    out: list[BillingDocument] = []
    for stem, info in by_stem.items():
        pdf_path = info["pdf"]
        txt_path = info["txt"]
        canonical = pdf_path if pdf_path is not None else (ins_dir / f"{stem}.pdf")
        if stem.startswith("insurance_eob_"):
            kind = "EOB"
        elif stem.startswith("insurance_copay_"):
            kind = "Copay"
        elif stem.startswith("insurance_statement_"):
            kind = "Statement"
        elif stem.startswith("insurance_claim_"):
            kind = "Claim"
        else:
            kind = "Insurance"
        claim_part = stem.split("_", 2)[-1] if "_" in stem else stem
        label = f"Insurance {kind}, {claim_part}, PDF"
        out.append(
            BillingDocument(
                path=canonical,
                label=label,
                kind="receipt",
                mtime=info["mtime"],
                stream="insurance",
                text_sidecar=txt_path,
            )
        )
    return out


def _classify_legacy_flat_receipt(stem: str) -> str:
    """Guess stream for a doc in the legacy flat receipts/ folder by filename prefix."""
    if stem.startswith(("settlement_", "pi_case_summary_", "pi_cover_sheet_", "pi_case_statement_")):
        return "pi"
    if stem.startswith(("package_contract_", "package_statement_")):
        return "package"
    if stem.startswith(("receipt_",)):
        return "cash"
    return "cash"  # default — pre-streams receipts were all cash


def list_billing_documents(
    patient_root: str | Path,
    *,
    streams: tuple[str, ...] | list[str] | None = None,
) -> list[BillingDocument]:
    """
    All viewable billing documents (receipts subfolders, exports, packet summaries).

    Pass `streams=("cash",)` (or any subset) to filter to just one money stream.
    The umbrella "exports" + "packets" docs are included only when:
      * no stream filter is provided, OR
      * the filter explicitly includes "pi" (those are PI-case artifacts).
    """
    root = patient_billing_root(patient_root)
    seen: set[str] = set()
    docs: list[BillingDocument] = []
    want: set[str] | None = set(streams) if streams else None

    def _add(path: Path, label: str, kind: str, stream: str) -> None:
        if want is not None and stream not in want:
            return
        key = str(path.resolve())
        if key in seen or not path.is_file():
            return
        seen.add(key)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        docs.append(
            BillingDocument(path=path, label=label, kind=kind, mtime=mtime, stream=stream)
        )

    rec_dir = root / "receipts"
    if rec_dir.is_dir():
        # Legacy flat folder — files written before per-stream subfolders existed.
        # Classify each by filename prefix so the stream filter still works.
        for p in rec_dir.glob("*.txt"):
            stream = _classify_legacy_flat_receipt(p.stem)
            _add(p, document_display_label(p), "receipt", stream)
        for p in rec_dir.glob("*.pdf"):
            stream = _classify_legacy_flat_receipt(p.stem)
            _add(p, document_display_label(p), "receipt", stream)
        # Modern per-stream subfolders. Each stream gets its own receipts dir.
        for stream in RECEIPT_STREAMS:
            sub = rec_dir / stream
            if not sub.is_dir():
                continue
            if stream == "cash":
                # Cash uses a special collector that groups .pdf+.txt pairs by
                # stem so the dialog shows ONE row per visit (no .txt dup).
                if want is not None and "cash" not in want:
                    continue
                for doc in _collect_cash_receipts(sub):
                    key = str(doc.path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    docs.append(doc)
                continue
            if stream == "package":
                # Same idea for packages — one row per .pdf/.txt pair, labeled
                # "<Plan Name>, MM/DD/YYYY, PDF" or "<Plan Name> Contract, PDF".
                if want is not None and "package" not in want:
                    continue
                for doc in _collect_package_receipts(sub, patient_root):
                    key = str(doc.path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    docs.append(doc)
                continue
            if stream == "insurance":
                if want is not None and "insurance" not in want:
                    continue
                for doc in _collect_insurance_receipts(sub):
                    key = str(doc.path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    docs.append(doc)
                continue
            for p in sub.glob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in {".txt", ".pdf"}:
                    continue
                label_prefix = STREAM_DISPLAY_LABELS[stream]
                _add(p, f"{label_prefix} · {document_display_label(p)}", "receipt", stream)

    # Exports + packets are PI-case artifacts. Surface them when the user is
    # browsing PI receipts (or browsing the unfiltered global view).
    exp_dir = root / "exports"
    if exp_dir.is_dir():
        for p in exp_dir.glob("pi_case_summary_*.txt"):
            _add(p, document_display_label(p, source="Export"), "export", "pi")

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
                    _add(p, f"{title} · {packet.name}", "packet", "pi")

    docs.sort(key=lambda d: d.mtime, reverse=True)
    return docs


def ensure_receipt_subfolders(patient_root: str | Path) -> None:
    """
    Pre-create the five per-stream receipt subfolders so the user sees the
    full structure when browsing in Explorer (even if a stream is empty).
    Safe to call repeatedly — idempotent.
    """
    for stream in RECEIPT_STREAMS:
        patient_receipts_dir(patient_root, subfolder=stream)


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
    """Copy PI case summary (and optional cover) into billing/receipts/pi/."""
    saved: list[Path] = []
    saved.append(save_receipt_file(patient_root, summary_text, prefix="pi_case_summary", subfolder="pi"))
    if cover_text:
        saved.append(save_receipt_file(patient_root, cover_text, prefix="pi_cover_sheet", subfolder="pi"))
    return saved


def patient_receipts_dir(patient_root: str | Path, subfolder: str = "") -> Path:
    base = patient_billing_root(patient_root) / "receipts"
    if subfolder:
        d = base / subfolder.strip().strip("/").strip("\\")
    else:
        d = base
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_receipts_folder(patient_root: str | Path, subfolder: str = "") -> None:
    """
    Open the receipts folder in the OS file browser. When `subfolder` is given
    (e.g. "cash", "package"), opens that stream-specific subfolder so the user
    lands in the right place from a tab-specific button.
    """
    p = str(patient_receipts_dir(patient_root, subfolder=subfolder).resolve())
    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')


def _safe_key(s: str) -> str:
    """Sanitize a string for use in a filename (alnum + - _)."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (s or "").strip())


def save_receipt_file(
    patient_root: str | Path,
    text: str,
    *,
    prefix: str = "receipt",
    subfolder: str = "cash",
    unique_key: str = "",
) -> Path:
    """
    Save a text receipt to the patient's receipts folder.

    Default subfolder is 'cash' so plain receipts land in receipts/cash/ alongside
    cash PDFs. Pass subfolder="" to use the legacy flat folder, or
    subfolder="pi" / "package" / etc. to keep money streams separate.

    When `unique_key` is provided (e.g. an encounter_id or exam stem), the
    filename uses that key INSTEAD of a timestamp, so re-saving for the same
    visit OVERWRITES the previous file (one receipt per visit). When omitted,
    a timestamp suffix is used (legacy behavior).
    """
    rec_dir = patient_receipts_dir(patient_root, subfolder=subfolder)
    if unique_key:
        suffix = _safe_key(unique_key)
    else:
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = rec_dir / f"{prefix}_{suffix}.txt"
    path.write_text(text, encoding="utf-8")
    return path
