# clinic_profile.py — one clinic identity per computer, stored in the data folder.
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from paths import get_data_dir

PROFILE_NAME = "clinic_profile.json"
LOGO_NAME = "clinic_logo.png"
SKIP_NAME = "clinic_setup_skipped"

_DEFAULTS: dict[str, str] = {}
_DEFAULT_LOGO = ""

_FIELDS = (
    "clinic_name",
    "clinic_addr",
    "clinic_phone_fax",
    "clinic_email",
    "provider_name",
    "provider_license",
    "provider_npi",
)

# Printed report header. Missing values keep the current letterhead.
_LAYOUT_DEFAULTS = {
    "logo_width": 72.0,
    "logo_height": 72.0,
    "clinic_name_size": 14.0,
    "clinic_detail_size": 11.0,
    "logo_y_offset": -51.4,
}
_LAYOUT_FIELDS = tuple(_LAYOUT_DEFAULTS)


def install_defaults(values: dict[str, str], logo_path: str) -> None:
    _DEFAULTS.clear()
    _DEFAULTS.update({k: str(v or "") for k, v in values.items()})
    global _DEFAULT_LOGO
    _DEFAULT_LOGO = str(logo_path or "")


def profile_path() -> Path:
    return get_data_dir() / PROFILE_NAME


def _skip_path() -> Path:
    return get_data_dir() / SKIP_NAME


def _logo_file() -> Path:
    return get_data_dir() / LOGO_NAME


def load_profile() -> dict | None:
    try:
        path = profile_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def needs_first_run_prompt() -> bool:
    if load_profile() is not None:
        return False
    try:
        return not _skip_path().is_file()
    except Exception:
        return False


def mark_setup_skipped() -> None:
    path = _skip_path()
    path.write_text("", encoding="utf-8")


def text_value(key: str) -> str:
    profile = load_profile()
    if profile is not None and key in profile:
        return str(profile.get(key) or "")
    return _DEFAULTS.get(key, "")


def logo_path() -> str:
    profile = load_profile()
    if profile and profile.get("logo_set"):
        try:
            path = _logo_file()
            if path.is_file():
                return str(path)
        except Exception:
            pass
    return _DEFAULT_LOGO


def current_fields() -> dict[str, str]:
    return {key: text_value(key) for key in _FIELDS}


def _format_layout_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def layout_value(key: str) -> float:
    profile = load_profile()
    raw = None
    if profile is not None and key in profile:
        raw = profile.get(key)
    if raw is None or str(raw).strip() == "":
        raw = _LAYOUT_DEFAULTS[key]
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(_LAYOUT_DEFAULTS[key])


def layout_fields() -> dict[str, str]:
    return {key: _format_layout_number(layout_value(key)) for key in _LAYOUT_FIELDS}


def _layout_payload(fields: dict[str, str], existing: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in _LAYOUT_FIELDS:
        raw = fields.get(key, existing.get(key, ""))
        if raw is None or str(raw).strip() == "":
            continue
        try:
            number = float(str(raw).strip())
        except ValueError as exc:
            raise ValueError(f"{key.replace('_', ' ')} must be a number.") from exc
        if key != "logo_y_offset" and number <= 0:
            raise ValueError(f"{key.replace('_', ' ')} must be greater than zero.")
        out[key] = number
    return out


def using_custom_logo() -> bool:
    profile = load_profile()
    return bool(profile and profile.get("logo_set") and _logo_file().is_file())


def save_profile(fields: dict[str, str], logo_source: str | None = None) -> None:
    name = (fields.get("clinic_name") or "").strip()
    if not name:
        raise ValueError("Clinic name is required.")
    root = get_data_dir()
    existing = load_profile() or {}
    logo_set = bool(existing.get("logo_set"))
    if logo_source:
        src = Path(logo_source)
        if not src.is_file():
            raise ValueError("Logo file was not found.")
        if src.suffix.lower() != ".png":
            raise ValueError("Choose a PNG logo.")
        dest = root / LOGO_NAME
        if src.resolve() != dest.resolve():
            tmp_logo = dest.with_suffix(".png.tmp")
            shutil.copyfile(src, tmp_logo)
            os.replace(tmp_logo, dest)
        logo_set = True
    payload = {key: (fields.get(key) or "").strip() for key in _FIELDS}
    payload["clinic_name"] = name
    payload["logo_set"] = logo_set
    payload.update(_layout_payload(fields, existing))
    path = root / PROFILE_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class ClinicText:
    """String stand-in that re-reads the clinic profile on each use."""

    def __init__(self, key: str):
        self._key = key

    def _v(self) -> str:
        return text_value(self._key)

    def __str__(self) -> str:
        return self._v()

    def __repr__(self) -> str:
        return repr(self._v())

    def __bool__(self) -> bool:
        return bool(self._v().strip())

    def __format__(self, spec: str) -> str:
        return format(self._v(), spec)

    def __iter__(self):
        return iter(self._v())

    def __add__(self, other):
        return self._v() + other

    def __radd__(self, other):
        return other + self._v()

    def decode(self, encoding: str = "utf8", errors: str = "strict") -> str:
        return self._v()

    def strip(self, chars: str | None = None) -> str:
        if chars is None:
            return self._v().strip()
        return self._v().strip(chars)

    def __getattr__(self, name: str):
        return getattr(self._v(), name)


class ClinicPath:
    """Logo path that follows this computer's saved logo, if one was chosen."""

    def _v(self) -> str:
        return logo_path()

    def __str__(self) -> str:
        return self._v()

    def __repr__(self) -> str:
        return repr(self._v())

    def __fspath__(self) -> str:
        return self._v()

    def __bool__(self) -> bool:
        return bool(self._v())

    def __format__(self, spec: str) -> str:
        return format(self._v(), spec)

    def __add__(self, other):
        return self._v() + other

    def __radd__(self, other):
        return other + self._v()

    def decode(self, encoding: str = "utf8", errors: str = "strict") -> str:
        return self._v()

    def __getattr__(self, name: str):
        return getattr(self._v(), name)
