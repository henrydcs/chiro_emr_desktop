"""
Local authentication for the EMR shell.

Stores a small users.json under the EMR data directory containing:
  - PBKDF2-SHA256 password hashes (200,000 iterations, 32-byte random salt)
  - per-user lockout state (5 failed attempts -> 5 minute lockout)

Designed for fully offline / local single-machine use. No network, no third-party deps.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from paths import get_data_dir

# -------- Tunables --------
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 32
HASH_BYTES = 32
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 5
MIN_PASSWORD_LEN = 8


def _users_file() -> Path:
    base = get_data_dir() / "auth"
    base.mkdir(parents=True, exist_ok=True)
    return base / "users.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _read_store() -> dict:
    p = _users_file()
    if not p.exists():
        return {"users": [], "lockouts": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        return {"users": [], "lockouts": {}}
    data.setdefault("users", [])
    data.setdefault("lockouts", {})
    return data


def _write_store(data: dict) -> None:
    p = _users_file()
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=HASH_BYTES,
    )


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


# -------- Public API --------

@dataclass
class AuthResult:
    ok: bool
    message: str
    username: str | None = None
    is_admin: bool = False


def has_any_user() -> bool:
    return bool(_read_store().get("users"))


def validate_password_strength(password: str) -> tuple[bool, str]:
    if not password or len(password) < MIN_PASSWORD_LEN:
        return False, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    classes = 0
    if any(c.islower() for c in password):
        classes += 1
    if any(c.isupper() for c in password):
        classes += 1
    if any(c.isdigit() for c in password):
        classes += 1
    if any(not c.isalnum() for c in password):
        classes += 1
    if classes < 2:
        return False, "Use at least 2 of: lowercase, uppercase, digits, symbols."
    return True, ""


def create_user(username: str, password: str, is_admin: bool = False) -> AuthResult:
    uname = _normalize_username(username)
    if not uname:
        return AuthResult(False, "Username is required.")
    ok, msg = validate_password_strength(password)
    if not ok:
        return AuthResult(False, msg)

    store = _read_store()
    if any(_normalize_username(u.get("username", "")) == uname for u in store["users"]):
        return AuthResult(False, "That username already exists.")

    salt = secrets.token_bytes(SALT_BYTES)
    h = _hash_password(password, salt)
    store["users"].append({
        "username": uname,
        "salt": salt.hex(),
        "hash": h.hex(),
        "iterations": PBKDF2_ITERATIONS,
        "is_admin": bool(is_admin),
        "created_at": _now_iso(),
        "last_login_at": None,
    })
    _write_store(store)
    return AuthResult(True, "User created.", username=uname, is_admin=is_admin)


def _is_locked(store: dict, uname: str) -> tuple[bool, str]:
    rec = store.get("lockouts", {}).get(uname)
    if not rec:
        return False, ""
    until = rec.get("locked_until")
    if not until:
        return False, ""
    try:
        until_dt = datetime.fromisoformat(until.rstrip("Z"))
    except Exception:
        return False, ""
    if datetime.utcnow() < until_dt:
        remaining = until_dt - datetime.utcnow()
        mins = int(remaining.total_seconds() // 60) + 1
        return True, f"Account is locked. Try again in ~{mins} min."
    return False, ""


def _record_failure(store: dict, uname: str) -> str:
    rec = store["lockouts"].get(uname) or {"failed": 0, "locked_until": None}
    rec["failed"] = int(rec.get("failed", 0)) + 1
    msg = ""
    if rec["failed"] >= MAX_FAILED_ATTEMPTS:
        until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
        rec["locked_until"] = until.isoformat(timespec="seconds") + "Z"
        rec["failed"] = 0
        msg = f"Too many failed attempts. Locked for {LOCKOUT_MINUTES} minutes."
    store["lockouts"][uname] = rec
    _write_store(store)
    return msg


def _record_success(store: dict, uname: str) -> None:
    if uname in store["lockouts"]:
        store["lockouts"][uname] = {"failed": 0, "locked_until": None}
    for u in store["users"]:
        if _normalize_username(u.get("username", "")) == uname:
            u["last_login_at"] = _now_iso()
            break
    _write_store(store)


def authenticate(username: str, password: str) -> AuthResult:
    uname = _normalize_username(username)
    if not uname or password is None:
        return AuthResult(False, "Username and password are required.")

    store = _read_store()
    locked, why = _is_locked(store, uname)
    if locked:
        return AuthResult(False, why)

    user = next(
        (u for u in store["users"] if _normalize_username(u.get("username", "")) == uname),
        None,
    )
    if user is None:
        # Hash anyway (timing) then report a generic message
        _ = _hash_password(password, secrets.token_bytes(SALT_BYTES))
        msg = _record_failure(store, uname) or "Invalid username or password."
        return AuthResult(False, msg)

    try:
        salt = bytes.fromhex(user.get("salt", ""))
        expected = bytes.fromhex(user.get("hash", ""))
    except Exception:
        return AuthResult(False, "Stored credential is corrupt. Contact admin.")

    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt,
        int(user.get("iterations") or PBKDF2_ITERATIONS),
        dklen=len(expected) or HASH_BYTES,
    )
    if not hmac.compare_digest(actual, expected):
        msg = _record_failure(store, uname) or "Invalid username or password."
        return AuthResult(False, msg)

    _record_success(store, uname)
    return AuthResult(True, "Welcome.", username=uname, is_admin=bool(user.get("is_admin")))


def change_password(username: str, old_password: str, new_password: str) -> AuthResult:
    res = authenticate(username, old_password)
    if not res.ok:
        return res
    ok, msg = validate_password_strength(new_password)
    if not ok:
        return AuthResult(False, msg)

    store = _read_store()
    uname = _normalize_username(username)
    for u in store["users"]:
        if _normalize_username(u.get("username", "")) == uname:
            salt = secrets.token_bytes(SALT_BYTES)
            u["salt"] = salt.hex()
            u["hash"] = _hash_password(new_password, salt).hex()
            u["iterations"] = PBKDF2_ITERATIONS
            _write_store(store)
            return AuthResult(True, "Password changed.", username=uname,
                              is_admin=bool(u.get("is_admin")))
    return AuthResult(False, "User not found.")
