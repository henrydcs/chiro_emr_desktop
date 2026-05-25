# billing_storage.py — fee schedules and shadow encounter persistence.
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from config import PATIENT_SUBDIR_BILLING, PATIENT_SUBDIR_EXAMS
from paths import get_data_dir

from billing_engine import build_shadow_encounter

# Default clinic fees (Phase 1 — editable via fee_schedules.json)
_DEFAULT_FEES: dict[str, dict[str, float]] = {
    "cash": {
        "98940": 65.0,
        "98941": 75.0,
        "98942": 85.0,
        "98943": 55.0,
        "99202": 125.0,
        "99203": 165.0,
        "99204": 225.0,
        "99212": 95.0,
        "99213": 120.0,
        "99214": 155.0,
        "97010": 35.0,
        "97012": 45.0,
        "97014": 40.0,
        "97110": 55.0,
        "97112": 55.0,
        "97140": 60.0,
        "97530": 55.0,
    },
    "pi_ucr": {
        "98940": 95.0,
        "98941": 110.0,
        "98942": 125.0,
        "98943": 80.0,
        "99202": 185.0,
        "99203": 245.0,
        "99204": 335.0,
        "99212": 140.0,
        "99213": 175.0,
        "99214": 225.0,
        "97010": 55.0,
        "97012": 65.0,
        "97014": 60.0,
        "97110": 80.0,
        "97112": 80.0,
        "97140": 85.0,
        "97530": 80.0,
    },
}


def clinic_billing_dir() -> Path:
    d = get_data_dir() / "billing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fee_schedules_path() -> Path:
    return clinic_billing_dir() / "fee_schedules.json"


def load_fee_schedules() -> dict[str, dict[str, float]]:
    p = fee_schedules_path()
    if not p.is_file():
        return {k: dict(v) for k, v in _DEFAULT_FEES.items()}
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {k: dict(v) for k, v in _DEFAULT_FEES.items()}
    out: dict[str, dict[str, float]] = {}
    for sch, fees in raw.items():
        if isinstance(fees, dict):
            out[sch] = {str(cpt): float(amt) for cpt, amt in fees.items() if cpt}
    for sch, defaults in _DEFAULT_FEES.items():
        out.setdefault(sch, {})
        for cpt, amt in defaults.items():
            out[sch].setdefault(cpt, amt)
    return out


def save_fee_schedules(schedules: dict[str, dict[str, float]]) -> None:
    p = fee_schedules_path()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2)
    os.replace(tmp, p)


def get_fee(
    cpt: str,
    schedule: str,
    *,
    schedules: dict[str, dict[str, float]] | None = None,
) -> float | None:
    cpt = (cpt or "").strip()
    if not cpt:
        return None
    sched = schedules if schedules is not None else load_fee_schedules()
    fees = sched.get(schedule) or {}
    if cpt in fees:
        return float(fees[cpt])
    return None


def make_fee_lookup(
    schedules: dict[str, dict[str, float]] | None = None,
) -> Callable[[str, str, str], float | None]:
    sched = schedules if schedules is not None else load_fee_schedules()

    def lookup(cpt: str, _modifier: str, schedule: str) -> float | None:
        return get_fee(cpt, schedule, schedules=sched)

    return lookup


def patient_billing_root(patient_root: str | os.PathLike) -> Path:
    return Path(patient_root) / PATIENT_SUBDIR_BILLING


def encounters_dir(patient_root: str | os.PathLike) -> Path:
    d = patient_billing_root(patient_root) / "encounters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _encounter_filename(exam_path: str | Path) -> str:
    stem = Path(exam_path).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return f"{safe}.shadow.json"


def save_shadow_encounter(patient_root: str | os.PathLike, encounter: dict) -> Path:
    exam_path = encounter.get("exam_path") or ""
    out = encounters_dir(patient_root) / _encounter_filename(exam_path)
    tmp = out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(encounter, f, indent=2)
    os.replace(tmp, out)
    return out


def load_shadow_encounter(patient_root: str | os.PathLike, exam_path: str | Path) -> dict | None:
    p = encounters_dir(patient_root) / _encounter_filename(exam_path)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def list_shadow_encounters(patient_root: str | os.PathLike) -> list[dict]:
    d = encounters_dir(patient_root)
    out: list[dict] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.shadow.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out.append(raw)
        except Exception:
            continue
    return out


def resolve_exam_file(patient_root: str | os.PathLike, exam_path: str | Path) -> Path:
    """Resolve exam JSON path (absolute path or under patient exams/)."""
    p = Path(exam_path)
    if p.is_file():
        return p.resolve()
    root = Path(patient_root)
    for candidate in (
        root / PATIENT_SUBDIR_EXAMS / p.name,
        root / p,
    ):
        if candidate.is_file():
            return candidate.resolve()
    return p.resolve()


def shadow_file_path(patient_root: str | os.PathLike, exam_path: str | Path) -> Path:
    return encounters_dir(patient_root) / _encounter_filename(exam_path)


def is_shadow_stale(patient_root: str | os.PathLike, exam_path: str | Path) -> bool:
    """True when saved exam JSON is newer than the cached billing shadow preview."""
    exam_p = resolve_exam_file(patient_root, exam_path)
    sh_p = shadow_file_path(patient_root, exam_path)
    if not exam_p.is_file():
        return False
    if not sh_p.is_file():
        return True
    try:
        return exam_p.stat().st_mtime > sh_p.stat().st_mtime
    except OSError:
        return True


def load_or_refresh_shadow_encounter(
    patient_root: str | os.PathLike,
    exam_path: str | Path,
    *,
    force: bool = False,
) -> dict | None:
    """
    Load billing shadow preview from disk, rebuilding from exam JSON when stale or missing.
    Keeps encounter_id stable across rebuilds when possible.
    """
    root = Path(patient_root)
    exam_p = resolve_exam_file(root, exam_path)
    if not exam_p.is_file():
        return None
    exam_key = str(exam_p)

    if not force and not is_shadow_stale(root, exam_key):
        cached = load_shadow_encounter(root, exam_key)
        if cached:
            return cached

    old = load_shadow_encounter(root, exam_key)
    enc = build_shadow_encounter(
        exam_path=exam_key,
        patient_root=root,
        fee_lookup=make_fee_lookup(),
    )
    if old and old.get("encounter_id"):
        enc["encounter_id"] = old["encounter_id"]
    save_shadow_encounter(root, enc)
    return enc


def sync_billing_shadow_for_exam_save(exam_path: str | Path) -> None:
    """Rebuild billing shadow after chart save (Master Save / Save) so Billing stays in sync."""
    try:
        exam_p = Path(exam_path).resolve()
        patient_root = exam_p.parent.parent
        if not patient_root.is_dir():
            return
        load_or_refresh_shadow_encounter(patient_root, exam_p, force=True)
    except Exception:
        pass


def build_and_save_shadow(
    *,
    patient_root: str | os.PathLike,
    exam_path: str | Path,
) -> dict:
    enc = load_or_refresh_shadow_encounter(patient_root, exam_path, force=True)
    if enc:
        return enc
    raise FileNotFoundError(f"Exam file not found: {exam_path}")


def charge_master_path() -> Path:
    return clinic_billing_dir() / "charge_master.json"


_DEFAULT_CHARGE_MASTER: list[dict] = [
    {"cpt": "98940", "description": "Spinal, 1-2 regions", "category": "cmt"},
    {"cpt": "98941", "description": "Spinal, 3-4 regions", "category": "cmt"},
    {"cpt": "98942", "description": "Spinal, 5 regions", "category": "cmt"},
    {"cpt": "98943", "description": "Extraspinal / extremity", "category": "cmt"},
    {"cpt": "99202", "description": "E/M new patient — straightforward MDM", "category": "em"},
    {"cpt": "99203", "description": "E/M new patient — low MDM", "category": "em"},
    {"cpt": "99212", "description": "E/M established — straightforward MDM", "category": "em"},
    {"cpt": "99213", "description": "E/M established — low MDM", "category": "em"},
    {"cpt": "99214", "description": "E/M established — moderate MDM", "category": "em"},
    {"cpt": "97010", "description": "Hot/cold packs", "category": "therapy"},
    {"cpt": "97012", "description": "Mechanical traction", "category": "therapy"},
    {"cpt": "97014", "description": "Electrical stimulation", "category": "therapy"},
    {"cpt": "97110", "description": "Therapeutic exercise", "category": "therapy"},
    {"cpt": "97112", "description": "Neuromuscular reeducation", "category": "therapy"},
    {"cpt": "97140", "description": "Manual therapy", "category": "therapy"},
    {"cpt": "97530", "description": "Therapeutic activities", "category": "therapy"},
]


def load_charge_master() -> list[dict]:
    from service_catalog import ensure_charge_catalog

    return ensure_charge_catalog()


def save_charge_master(items: list[dict]) -> None:
    p = charge_master_path()
    tmp = p.with_suffix(".json.tmp")
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["version"] = 2
    raw["items"] = items
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    os.replace(tmp, p)
    schedules = load_fee_schedules()
    for item in items:
        cpt = str(item.get("cpt") or "").strip()
        if not cpt:
            continue
        for sch in ("cash", "pi_ucr"):
            schedules.setdefault(sch, {})
            schedules[sch].setdefault(cpt, _DEFAULT_FEES.get(sch, {}).get(cpt, 0.0))
    save_fee_schedules(schedules)


def upsert_charge_master_item(cpt: str, description: str, category: str = "other") -> None:
    """Backward-compatible wrapper — use service_catalog.upsert_catalog_item."""
    from service_catalog import upsert_catalog_item

    upsert_catalog_item(
        cpt=cpt,
        short_description=description,
        category=category,
    )


def set_fee_for_cpt(cpt: str, *, cash: float | None = None, pi_ucr: float | None = None) -> None:
    cpt = (cpt or "").strip()
    schedules = load_fee_schedules()
    if cash is not None:
        schedules.setdefault("cash", {})[cpt] = float(cash)
    if pi_ucr is not None:
        schedules.setdefault("pi_ucr", {})[cpt] = float(pi_ucr)
    save_fee_schedules(schedules)


def rebuild_all_shadows_for_patient(
    patient_root: str | os.PathLike,
    exam_paths: list[str],
) -> list[dict]:
    built: list[dict] = []
    for path in exam_paths:
        try:
            built.append(build_and_save_shadow(patient_root=patient_root, exam_path=path))
        except Exception:
            continue
    return built
