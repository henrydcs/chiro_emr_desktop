# billing_closeout.py — Phase 4: superbill, cover sheet, attorney packet assembly.
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from billing_case_export import (
    _dos_after,
    _dos_before,
    build_case_summary_text,
)
from billing_pi_case import case_status_label, load_pi_case
from billing_pi_ledger import compute_pi_balance, list_pi_posted_encounters, load_pi_ledger
from billing_storage import patient_billing_root
from config import (
    CLINIC_ADDR,
    CLINIC_NAME,
    CLINIC_PHONE_FAX,
    PATIENT_SUBDIR_EXAMS,
    PATIENT_SUBDIR_PDFS,
)
from shell_app import collect_visits_for_patient, read_patient_profile

try:
    from utils import safe_slug, to_last_first
except ImportError:
    def safe_slug(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", (s or "").strip()) or "unknown"

    def to_last_first(last: str, first: str) -> str:
        return f"{(last or '').strip()}, {(first or '').strip()}".strip(", ")


VAULT_PACKET_FOLDERS = ("attorney", "billing", "doctors_on_liens", "pdfs", "referrals", "imaging")


def _packet_root(patient_root: str | Path) -> Path:
    return patient_billing_root(patient_root) / "packets"


def _filtered_encounters(
    patient_root: str | Path,
    *,
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    out: list[dict] = []
    for enc in list_pi_posted_encounters(patient_root):
        dos = enc.get("date_of_service") or ""
        if date_from and _dos_before(dos, date_from):
            continue
        if date_to and _dos_after(dos, date_to):
            continue
        out.append(enc)
    return out


def compute_pi_balance_for_range(
    patient_root: str | Path,
    *,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, float]:
    """Charges filtered by DOS; payments/adjustments apply to whole case."""
    charges = 0.0
    for enc in _filtered_encounters(patient_root, date_from=date_from, date_to=date_to):
        charges += float(enc.get("amount_charged") or 0)
    full = compute_pi_balance(patient_root)
    payments = full["total_payments"]
    adjustments = full["total_adjustments"]
    balance = round(charges - payments + adjustments, 2)
    return {
        "total_charges": round(charges, 2),
        "total_payments": payments,
        "total_adjustments": adjustments,
        "balance_due": balance,
    }


def build_superbill_rows(
    patient_root: str | Path,
    *,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for enc in _filtered_encounters(patient_root, date_from=date_from, date_to=date_to):
        dos = enc.get("date_of_service") or ""
        prov = enc.get("provider") or ""
        dx_list = enc.get("diagnosis_pointers") or []
        for ln in enc.get("lines") or []:
            if not isinstance(ln, dict):
                continue
            dx = list(ln.get("diagnosis_pointers") or dx_list)
            while len(dx) < 4:
                dx.append("")
            rows.append(
                {
                    "date_of_service": dos,
                    "place_of_service": ln.get("place_of_service") or "11",
                    "cpt": ln.get("cpt_code") or "",
                    "modifier": ln.get("modifier_1") or "",
                    "units": ln.get("units") or 1,
                    "charge": float(ln.get("amount") or 0),
                    "dx1": dx[0] if len(dx) > 0 else "",
                    "dx2": dx[1] if len(dx) > 1 else "",
                    "dx3": dx[2] if len(dx) > 2 else "",
                    "dx4": dx[3] if len(dx) > 3 else "",
                    "description": (ln.get("description") or "")[:60],
                    "rendering_provider": prov,
                    "exam_name": enc.get("exam_name") or "",
                }
            )
    return rows


def build_superbill_csv(
    patient_root: str | Path,
    *,
    date_from: str = "",
    date_to: str = "",
) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "DOS",
            "POS",
            "CPT",
            "Modifier",
            "Units",
            "Charge",
            "DX1",
            "DX2",
            "DX3",
            "DX4",
            "Provider",
            "Description",
            "Visit",
        ]
    )
    for r in build_superbill_rows(patient_root, date_from=date_from, date_to=date_to):
        w.writerow(
            [
                r["date_of_service"],
                r["place_of_service"],
                r["cpt"],
                r["modifier"],
                r["units"],
                f"{r['charge']:.2f}",
                r["dx1"],
                r["dx2"],
                r["dx3"],
                r["dx4"],
                r["rendering_provider"],
                r["description"],
                r["exam_name"],
            ]
        )
    return buf.getvalue()


def build_superbill_text(
    patient_root: str | Path,
    *,
    patient_name: str,
    date_from: str = "",
    date_to: str = "",
) -> str:
    rows = build_superbill_rows(patient_root, date_from=date_from, date_to=date_to)
    bal = compute_pi_balance_for_range(patient_root, date_from=date_from, date_to=date_to)
    lines = [
        (CLINIC_NAME or "Clinic").strip(),
        "SUPERBILL / ITEMIZED CHARGE GRID",
        "=" * 72,
        f"Patient: {patient_name}",
        f"Date range: {date_from or 'all'} — {date_to or 'all'}",
        f"Line items: {len(rows)}",
        f"Charges in range: ${bal['total_charges']:,.2f}",
        "",
        f"{'DOS':<12}{'POS':<4}{'CPT':<6}{'Mod':<4}{'U':<4}{'Charge':>10}",
        "-" * 72,
    ]
    for i, r in enumerate(rows):
        dxs = ", ".join(x for x in (r["dx1"], r["dx2"], r["dx3"], r["dx4"]) if x)
        lines.append(
            f"{r['date_of_service']:<12}{r['place_of_service']:<4}{r['cpt']:<6}"
            f"{r['modifier'] or '':<4}{r['units']!s:<4}${r['charge']:>9,.2f}"
        )
        if dxs:
            lines.append(f"  DX: {dxs}")
        desc = (r["description"] or "").strip()
        if desc:
            lines.append(f"  {desc}")
        if i < len(rows) - 1:
            lines.append("")
    lines.extend(["", f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}"])
    return "\n".join(lines)


def build_cover_sheet_text(
    *,
    patient_root: str | Path,
    patient_name: str,
    date_from: str = "",
    date_to: str = "",
) -> str:
    case = load_pi_case(patient_root) or {}
    profile = read_patient_profile(Path(patient_root))
    bal = compute_pi_balance_for_range(patient_root, date_from=date_from, date_to=date_to)
    full_bal = compute_pi_balance(patient_root)
    atty = case.get("attorney") or {}
    atty_line = (atty.get("name") or "").strip()
    if atty.get("firm"):
        atty_line = f"{atty_line} — {atty['firm']}".strip(" —")

    enc_count = len(_filtered_encounters(patient_root, date_from=date_from, date_to=date_to))
    line_count = len(
        build_superbill_rows(patient_root, date_from=date_from, date_to=date_to)
    )

    return "\n".join(
        [
            (CLINIC_NAME or "Chiropractic Clinic").strip(),
            (CLINIC_ADDR or "").strip(),
            (CLINIC_PHONE_FAX or "").strip(),
            "",
            "ATTORNEY / CARRIER BILLING PACKET — COVER SHEET",
            "=" * 60,
            "",
            f"Prepared for: {atty_line or '(Attorney not on file)'}",
            f"Patient: {patient_name}",
            f"DOB: {(profile.get('dob') or '').strip() or '—'}",
            f"Date of injury: {(case.get('date_of_injury') or '').strip() or '—'}",
            f"Claim #: {(case.get('claim_number') or '').strip() or '—'}",
            f"Case status: {case_status_label(case.get('case_status') or 'active')}",
            "",
            f"Service date range: {date_from or 'First visit'} — {date_to or 'Last visit'}",
            f"Visits in packet: {enc_count}",
            f"Charge line items: {line_count}",
            "",
            "FINANCIAL SUMMARY",
            "-" * 60,
            f"Charges (date range):     ${bal['total_charges']:>12,.2f}",
            f"Payments (case total):    ${bal['total_payments']:>12,.2f}",
            f"Adjustments (case total): ${bal['total_adjustments']:>12,.2f}",
            f"Balance due (case total): ${full_bal['balance_due']:>12,.2f}",
            "",
            "ENCLOSED DOCUMENTS (see manifest.json in this folder)",
            "  • Cover sheet (this file)",
            "  • Case billing summary",
            "  • Superbill grid (CSV + TXT)",
            "  • Clinical exam PDFs (when available)",
            "  • Attorney / lien / billing vault documents (when selected)",
            "",
            "NOTES",
            (case.get("notes") or "").strip() or "  (none)",
            "",
            f"Generated: {datetime.now().strftime('%m/%d/%Y %I:%M %p')}",
            "",
            "Confidential — for billing and legal review.",
        ]
    )


def _expected_exam_pdf_names(enc: dict, profile: dict) -> list[str]:
    exam = enc.get("exam_name") or ""
    patient = enc.get("patient") if isinstance(enc.get("patient"), dict) else profile
    last = (patient.get("last_name") or profile.get("last_name") or "").strip()
    first = (patient.get("first_name") or profile.get("first_name") or "").strip()
    display = to_last_first(last, first) or "Patient"
    dob = (patient.get("dob") or profile.get("dob") or "").strip()
    doi = (patient.get("doi") or profile.get("doi") or "").strip()
    names = [
        f"{safe_slug(exam)}_{safe_slug(display)}_DOB_{safe_slug(dob)}_DOI_{safe_slug(doi)}.pdf",
    ]
    dos = enc.get("date_of_service") or ""
    if dos:
        names.append(f"{safe_slug(dos)}__{safe_slug(exam)}.pdf")
    names.append(f"{safe_slug(exam)}.pdf")
    return names


def _load_exam_json(exam_path: str | Path) -> dict:
    try:
        raw = json.loads(Path(exam_path).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def find_clinical_pdf_for_visit(
    patient_root: str | Path,
    *,
    exam_path: str,
    exam_name: str = "",
    date_of_service: str = "",
) -> Path | None:
    root = Path(patient_root)
    payload = _load_exam_json(exam_path)
    profile = read_patient_profile(root)
    patient = payload.get("patient") if isinstance(payload.get("patient"), dict) else profile
    exam = exam_name or payload.get("exam") or ""

    candidates: list[Path] = []
    expected = _expected_exam_pdf_names(
        {"exam_name": exam, "patient": patient, "date_of_service": date_of_service},
        profile,
    )

    pdf_dir = root / PATIENT_SUBDIR_PDFS
    if pdf_dir.is_dir():
        for name in expected:
            p = pdf_dir / name
            if p.is_file():
                candidates.append(p)
        exam_slug = safe_slug(exam).lower()
        for p in pdf_dir.glob("*.pdf"):
            if exam_slug and exam_slug in p.stem.lower():
                candidates.append(p)

    vault_pdf = root / "vault" / "pdfs"
    if vault_pdf.is_dir():
        dos_slug = safe_slug(date_of_service) if date_of_service else ""
        exam_slug = safe_slug(exam)
        if dos_slug and exam_slug:
            vp = vault_pdf / f"{dos_slug}__{exam_slug}.pdf"
            if vp.is_file():
                candidates.append(vp)
        for p in vault_pdf.glob("*.pdf"):
            if exam_slug and exam_slug in p.stem.lower():
                candidates.append(p)

    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def list_vault_files(patient_root: str | Path, folder_keys: tuple[str, ...]) -> list[Path]:
    root = Path(patient_root)
    out: list[Path] = []
    for key in folder_keys:
        d = root / "vault" / key
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                out.append(p)
    return out


def build_attorney_packet(
    *,
    patient_root: str | Path,
    patient_name: str,
    date_from: str = "",
    date_to: str = "",
    include_clinical_pdfs: bool = True,
    include_vault_attorney: bool = True,
    include_vault_billing: bool = True,
    include_vault_liens: bool = True,
) -> Path:
    """
    Assemble a folder under billing/packets/ with billing docs, manifest, and copies.
    Returns the packet directory path.
    """
    root = Path(patient_root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    packet_dir = _packet_root(root) / f"attorney_packet_{stamp}"
    clinical_dir = packet_dir / "clinical_records"
    vault_dir = packet_dir / "vault_documents"
    packet_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "patient_name": patient_name,
        "date_from": date_from,
        "date_to": date_to,
        "files": [],
    }

    def _add(rel: str, src: Path | None = None, *, kind: str = "generated") -> None:
        manifest["files"].append(
            {"path": rel.replace("\\", "/"), "kind": kind, "source": str(src) if src else ""}
        )

    # Generated billing documents
    cover = build_cover_sheet_text(
        patient_root=root,
        patient_name=patient_name,
        date_from=date_from,
        date_to=date_to,
    )
    (packet_dir / "00_cover_sheet.txt").write_text(cover, encoding="utf-8")
    _add("00_cover_sheet.txt")

    summary = build_case_summary_text(
        patient_root=root,
        patient_name=patient_name,
        date_from=date_from,
        date_to=date_to,
    )
    (packet_dir / "01_case_billing_summary.txt").write_text(summary, encoding="utf-8")
    _add("01_case_billing_summary.txt")

    sb_csv = build_superbill_csv(root, date_from=date_from, date_to=date_to)
    (packet_dir / "02_superbill.csv").write_text(sb_csv, encoding="utf-8")
    _add("02_superbill.csv")

    sb_txt = build_superbill_text(
        root, patient_name=patient_name, date_from=date_from, date_to=date_to
    )
    (packet_dir / "02_superbill.txt").write_text(sb_txt, encoding="utf-8")
    _add("02_superbill.txt")

    # Clinical PDFs
    if include_clinical_pdfs:
        clinical_dir.mkdir(exist_ok=True)
        visits = collect_visits_for_patient(root)
        for v in visits:
            dos = v.get("exam_date") or ""
            if date_from and _dos_before(dos, date_from):
                continue
            if date_to and _dos_after(dos, date_to):
                continue
            exam_path = v.get("path") or ""
            pdf = find_clinical_pdf_for_visit(
                root,
                exam_path=exam_path,
                exam_name=v.get("exam_name") or "",
                date_of_service=dos,
            )
            if pdf and pdf.is_file():
                dest_name = f"{safe_slug(dos)}__{safe_slug(v.get('exam_name') or 'visit')}.pdf"
                dest = clinical_dir / dest_name
                shutil.copy2(pdf, dest)
                _add(f"clinical_records/{dest_name}", pdf, kind="clinical_pdf")

    # Vault documents
    vault_keys: list[str] = []
    if include_vault_attorney:
        vault_keys.append("attorney")
    if include_vault_billing:
        vault_keys.append("billing")
    if include_vault_liens:
        vault_keys.append("doctors_on_liens")

    if vault_keys:
        vault_dir.mkdir(exist_ok=True)
        for src in list_vault_files(root, tuple(vault_keys)):
            sub = src.parent.name
            dest = vault_dir / sub / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _add(f"vault_documents/{sub}/{src.name}", src, kind="vault")

    # Checklist for admin
    checklist = [
        "ADMIN CLOSE-OUT CHECKLIST",
        "=" * 40,
        "[ ] Cover sheet reviewed",
        "[ ] Superbill matches posted PI charges",
        "[ ] All visits in date range included",
        "[ ] Clinical PDFs attached for each visit",
        "[ ] Attorney / lien documents attached",
        "[ ] Case status updated (Active → Settled)",
        "[ ] Record settlement used OR final adjustment recorded if reduction",
        "",
        f"Packet folder: {packet_dir.name}",
    ]
    (packet_dir / "CHECKLIST.txt").write_text("\n".join(checklist), encoding="utf-8")
    _add("CHECKLIST.txt")

    (packet_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    from billing_receipt import archive_pi_summary_to_receipts

    archive_pi_summary_to_receipts(root, summary, cover_text=cover)

    return packet_dir


def open_packet_folder(packet_dir: str | Path) -> None:
    p = str(Path(packet_dir).resolve())
    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')
