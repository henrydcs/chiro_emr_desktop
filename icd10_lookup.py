# icd10_lookup.py
"""Local CMS ICD-10-CM code lookup (no SQLite / no network).

Reads icd10cm_codes_YYYY.txt from the EMR data directory and provides
in-memory search for the Diagnosis page picker.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paths import icd10_codes_file, icd10_source_dir


@dataclass(frozen=True)
class Icd10Entry:
    code_raw: str       # CMS form without decimal, e.g. "M542"
    code: str           # Dotted form, e.g. "M54.2"
    description: str


_CACHE: list[Icd10Entry] | None = None
_CACHE_PATH: str | None = None


def format_icd10_with_dot(code_raw: str) -> str:
    """Insert the ICD-10-CM decimal after the 3-character category when needed."""
    s = (code_raw or "").strip().upper().replace(".", "").replace(" ", "")
    if not s:
        return ""
    if len(s) <= 3:
        return s
    return f"{s[:3]}.{s[3:]}"


def normalize_icd10_query(query: str) -> str:
    """Uppercase alphanumeric form for code matching (dots/spaces stripped)."""
    return "".join(ch for ch in (query or "").upper() if ch.isalnum())


def _parse_codes_line(line: str) -> Icd10Entry | None:
    s = (line or "").rstrip("\r\n")
    if not s.strip():
        return None
    # CMS codes file: code (no decimal) then one or more spaces, then description.
    parts = s.split(None, 1)
    if len(parts) < 2:
        return None
    code_raw = parts[0].strip().upper()
    desc = parts[1].strip()
    if not code_raw or not desc:
        return None
    if not code_raw[0].isalpha():
        return None
    return Icd10Entry(
        code_raw=code_raw,
        code=format_icd10_with_dot(code_raw),
        description=desc,
    )


def resolve_icd10_codes_path() -> Path | None:
    return icd10_codes_file()


def load_icd10_entries(force_reload: bool = False) -> list[Icd10Entry]:
    """Load (and cache) all CMS ICD-10-CM entries from the Source folder."""
    global _CACHE, _CACHE_PATH
    path = resolve_icd10_codes_path()
    if path is None:
        _CACHE = []
        _CACHE_PATH = None
        return []

    path_s = str(path.resolve())
    if not force_reload and _CACHE is not None and _CACHE_PATH == path_s:
        return _CACHE

    entries: list[Icd10Entry] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            ent = _parse_codes_line(line)
            if ent is not None:
                entries.append(ent)

    _CACHE = entries
    _CACHE_PATH = path_s
    return entries


def icd10_file_status() -> tuple[bool, str]:
    """Return (ok, message) describing whether the CMS file is available."""
    path = resolve_icd10_codes_path()
    if path is None:
        return False, f"ICD-10 file not found in:\n{icd10_source_dir()}"
    if not path.is_file():
        return False, f"ICD-10 file not found:\n{path}"
    return True, str(path)


def search_icd10(query: str, limit: int = 60) -> list[Icd10Entry]:
    """Search by code prefix and/or description keywords (case-insensitive)."""
    q = (query or "").strip()
    if not q:
        return []

    entries = load_icd10_entries()
    if not entries:
        return []

    q_norm = normalize_icd10_query(q)
    q_lower = q.lower()
    words = [w for w in q_lower.split() if w]

    scored: list[tuple[int, Icd10Entry]] = []
    for ent in entries:
        code_norm = ent.code_raw
        desc_l = ent.description.lower()
        score = 0

        if q_norm and code_norm.startswith(q_norm):
            score = 300 - min(len(code_norm), 50)
            if code_norm == q_norm:
                score = 400
        elif q_norm and q_norm in code_norm:
            score = 200
        elif words and all(w in desc_l for w in words):
            # Prefer matches that start earlier in the description.
            pos = desc_l.find(words[0])
            score = 100 - min(pos if pos >= 0 else 99, 99)
        elif q_lower in desc_l:
            pos = desc_l.find(q_lower)
            score = 80 - min(pos if pos >= 0 else 79, 79)
        else:
            continue

        scored.append((score, ent))
        if len(scored) >= max(limit * 8, 200) and score < 200:
            # Soft early exit once we have plenty of weaker matches
            # (code-prefix hits are still collected fully via continues above).
            pass

    scored.sort(key=lambda t: (-t[0], t[1].code, t[1].description.lower()))
    return [ent for _, ent in scored[: max(1, int(limit))]]


def display_for_entry(ent: Icd10Entry) -> str:
    """UI display matching Diagnosis favorites: 'Description — CODE'."""
    return f"{ent.description} — {ent.code}"
