"""
EMR Shell Application

Top-level wrapper around the existing SOAP builder (chiro_app.py).
- Login screen (local PBKDF2 auth, no internet)
- First-run Create-Admin wizard
- Sidebar navigation (Dashboard, Schedule, Documents, Patients, Providers,
  Appt Types, Team, Clinics, Admin)
- Documents workspace (patient search, sticky notes, encounters, documents, tasks)
- Clicking an Encounter launches the existing chiro_app.py SOAP builder as a
  subprocess (logic-preserving) and re-syncs the active patient on return.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import shutil

import auth
from config import PATIENT_SUBDIR_EXAMS, PATIENTS_ID_ROOT
from paths import get_data_dir
from patient_storage import get_patient_root, new_patient_id
from utils import find_patient_folder_by_id, normalize_mmddyyyy, to_last_first

# ---------------- App constants ----------------

NAV_ITEMS: list[tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("schedule", "Schedule"),
    ("documents", "Documents"),
    ("patients", "Patients"),
    ("providers", "Providers"),
    ("appt_types", "Appt Types"),
    ("team", "Team"),
    ("clinics", "Clinics"),
    ("admin", "Admin"),
]

# Color palette (light, modern, similar to the provided screenshots)
COLOR_BG_APP = "#F4F6FA"
COLOR_BG_SIDEBAR = "#FFFFFF"
COLOR_SIDEBAR_TEXT = "#1F2937"
COLOR_SIDEBAR_HOVER = "#EEF2FF"
COLOR_SIDEBAR_ACTIVE_BG = "#E8EEFF"
COLOR_SIDEBAR_ACTIVE_FG = "#2563EB"
COLOR_TOPBAR_BG = "#FFFFFF"
COLOR_BORDER = "#E5E7EB"
COLOR_CARD = "#FFFFFF"
COLOR_TEXT = "#0F172A"
COLOR_MUTED = "#6B7280"
COLOR_ACCENT = "#2563EB"
COLOR_GREEN = "#16A34A"
COLOR_RED = "#DC2626"
COLOR_GREEN_SOFT = "#DCFCE7"
COLOR_RED_SOFT = "#FEE2E2"

FONT_BASE = ("Segoe UI", 10)
FONT_BASE_BOLD = ("Segoe UI", 10, "bold")
FONT_SECTION = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_BIG = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 9)
FONT_SMALL_MUTED = ("Segoe UI", 9)


# ---------------- Shared state file ----------------

def shell_state_path() -> Path:
    """JSON file used to communicate the active patient between shell and SOAP."""
    base = get_data_dir() / "shell"
    base.mkdir(parents=True, exist_ok=True)
    return base / "shell_state.json"


def read_shell_state() -> dict:
    p = shell_state_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_shell_state(data: dict) -> None:
    p = shell_state_path()
    tmp = p.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        pass


# ---------------- Patient scan helpers (shared with chiro_app idea) ----------------

def _read_patient_json(folder: Path) -> dict:
    p = folder / "patient.json"
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("patient")
    return inner if isinstance(inner, dict) else raw


def _read_demographics_from_any_exam(folder: Path) -> dict:
    exams_dir = folder / PATIENT_SUBDIR_EXAMS
    if not exams_dir.is_dir():
        return {}
    try:
        files = [p for p in exams_dir.iterdir()
                 if p.is_file() and p.suffix.lower() == ".json"
                 and p.name.lower() != "_exam_index.json"]
    except Exception:
        return {}
    if not files:
        return {}
    try:
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        pass
    for p in files:
        try:
            payload = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        patient = payload.get("patient") if isinstance(payload, dict) else None
        if isinstance(patient, dict):
            last = (patient.get("last_name") or "").strip()
            first = (patient.get("first_name") or "").strip()
            dob = (patient.get("dob") or "").strip()
            pid = (patient.get("patient_id") or "").strip()
            if last or first or dob or pid:
                return {"last_name": last, "first_name": first, "dob": dob, "patient_id": pid}
    return {}


def _names_from_folder_name(folder_name: str) -> tuple[str, str]:
    name = (folder_name or "").strip()
    if "__" not in name:
        return ("", "")
    prefix = name.rsplit("__", 1)[0]
    if "_" not in prefix:
        return ("", "")
    last_tok, first_tok = prefix.split("_", 1)
    clean = lambda s: re.sub(r"_+", " ", s).strip()
    last = clean(last_tok)
    first = clean(first_tok)
    if last.lower() == "unknown":
        last = ""
    if first.lower() == "unknown":
        first = ""
    return (last, first)


def _patient_id_from_folder_name(name: str) -> str:
    name = (name or "").strip()
    if "__" in name:
        return name.rsplit("__", 1)[-1].strip()
    return name


def patient_record_from_folder(folder: Path) -> dict | None:
    if not folder.is_dir():
        return None
    patient = _read_patient_json(folder)
    if not patient:
        patient = _read_demographics_from_any_exam(folder)

    pid = (patient.get("patient_id") or "").strip() or _patient_id_from_folder_name(folder.name)
    last = (patient.get("last_name") or "").strip()
    first = (patient.get("first_name") or "").strip()
    dob = (patient.get("dob") or "").strip()

    if not last and not first:
        fl, ff = _names_from_folder_name(folder.name)
        last = last or fl
        first = first or ff

    label = to_last_first(last, first) or folder.name
    return {
        "folder": str(folder.resolve()),
        "patient_id": pid,
        "last": last,
        "first": first,
        "dob": dob,
        "label": label,
    }


def scan_patients(last_q: str, first_q: str, dob_q: str, limit: int = 80) -> list[dict]:
    last_q = (last_q or "").strip().lower()
    first_q = (first_q or "").strip().lower()
    dob_q = (dob_q or "").strip()
    if not (last_q or first_q or dob_q):
        return []

    root = Path(PATIENTS_ID_ROOT)
    matches: list[dict] = []
    try:
        children = sorted([p for p in root.iterdir() if p.is_dir()],
                          key=lambda p: p.name.lower())
    except Exception:
        return []

    for folder in children:
        rec = patient_record_from_folder(folder)
        if not rec:
            continue
        last_n = (rec.get("last") or "").lower()
        first_n = (rec.get("first") or "").lower()
        dob_s = rec.get("dob") or ""
        if last_q and not last_n.startswith(last_q):
            continue
        if first_q and not first_n.startswith(first_q):
            continue
        if dob_q and not dob_s.startswith(dob_q):
            continue
        matches.append(rec)

    matches.sort(key=lambda r: ((r.get("last") or "").lower(),
                                (r.get("first") or "").lower(),
                                r.get("patient_id") or ""))
    return matches[:limit]


def list_all_patients(limit: int = 5000) -> list[dict]:
    """Return all patient records from id_cases (no query needed)."""
    root = Path(PATIENTS_ID_ROOT)
    out: list[dict] = []
    try:
        children = sorted([p for p in root.iterdir() if p.is_dir()],
                          key=lambda p: p.name.lower())
    except Exception:
        return []
    for folder in children:
        rec = patient_record_from_folder(folder)
        if rec:
            out.append(rec)
    out.sort(key=lambda r: ((r.get("last") or "").lower(),
                            (r.get("first") or "").lower(),
                            r.get("patient_id") or ""))
    return out[:limit]


def read_patient_profile(folder: Path) -> dict:
    """
    Read a patient profile from <folder>/patient.json.

    Returns the inner ``patient`` dict if the envelope form is used,
    otherwise the raw top-level dict, or {} if missing/unreadable.
    """
    p = folder / "patient.json"
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("patient")
    return dict(inner) if isinstance(inner, dict) else dict(raw)


def write_patient_profile(folder: Path, profile: dict) -> None:
    """Atomically write <folder>/patient.json with the {patient: profile} envelope."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "patient.json"
    payload = {"patient": dict(profile)}
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, p)


def get_last_visit_date(folder: Path) -> str:
    """Latest exam_date (MM/DD/YYYY) for this patient, or '' if no visits."""
    visits = collect_visits_for_patient(folder)
    return visits[0]["exam_date"] if visits else ""


def collect_visits_for_patient(folder: Path) -> list[dict]:
    """Return list of {exam_name, exam_date, provider, path} sorted newest first."""
    out: list[dict] = []
    exams_dir = folder / PATIENT_SUBDIR_EXAMS
    if not exams_dir.is_dir():
        return out

    try:
        files = [p for p in exams_dir.iterdir()
                 if p.is_file() and p.suffix.lower() == ".json"
                 and p.name.lower() != "_exam_index.json"]
    except Exception:
        return out

    for p in files:
        try:
            payload = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue

        ex_name = (payload.get("exam") or "").strip() or p.stem
        patient = payload.get("patient") or {}
        if isinstance(patient, dict):
            exam_date = normalize_mmddyyyy(patient.get("exam_date") or "") or ""
            provider = (patient.get("provider") or "").strip()
        else:
            exam_date = ""
            provider = ""

        out.append({
            "exam_name": ex_name,
            "exam_date": exam_date,
            "provider": provider,
            "path": str(p.resolve()),
        })

    def sort_key(item: dict):
        d = item.get("exam_date") or ""
        try:
            return datetime.strptime(d, "%m/%d/%Y")
        except Exception:
            return datetime.min

    out.sort(key=sort_key, reverse=True)
    return out


# ---------------- Common UI helpers ----------------

def make_card(parent: tk.Misc, title: str, hint: str = "") -> tuple[tk.Frame, tk.Frame]:
    """A card-styled frame. Returns (outer_card, body_frame)."""
    outer = tk.Frame(parent, bg=COLOR_CARD,
                     highlightbackground=COLOR_BORDER,
                     highlightcolor=COLOR_BORDER,
                     highlightthickness=1, bd=0)

    header = tk.Frame(outer, bg=COLOR_CARD)
    header.pack(fill="x", padx=14, pady=(12, 6))
    tk.Label(header, text=title, bg=COLOR_CARD, fg=COLOR_TEXT,
             font=FONT_SECTION).pack(side="left")
    if hint:
        tk.Label(header, text="  · " + hint, bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(side="left")

    body = tk.Frame(outer, bg=COLOR_CARD)
    body.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    return outer, body


# ============================================================
# LOGIN SCREEN
# ============================================================

class LoginScreen(tk.Frame):
    """The login (or first-run create-admin) screen, packed into the root window."""

    def __init__(self, master: "EmrShellApp"):
        super().__init__(master, bg=COLOR_BG_APP)
        self.app = master
        self.pack(fill="both", expand=True)

        self._mode = "login" if auth.has_any_user() else "create_admin"
        self._build()

    def _build(self) -> None:
        for w in self.winfo_children():
            w.destroy()

        wrapper = tk.Frame(self, bg=COLOR_BG_APP)
        wrapper.place(relx=0.5, rely=0.5, anchor="center")

        card = tk.Frame(wrapper, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER,
                        highlightcolor=COLOR_BORDER,
                        highlightthickness=1, bd=0)
        card.pack(padx=20, pady=20)

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(padx=36, pady=30)

        tk.Label(inner, text="Chiro EMR", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Segoe UI", 22, "bold")).pack(anchor="center")
        tk.Label(inner,
                 text=("Create your administrator account" if self._mode == "create_admin"
                       else "Sign in to continue"),
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE).pack(anchor="center", pady=(4, 22))

        form = tk.Frame(inner, bg=COLOR_CARD)
        form.pack()

        tk.Label(form, text="Username", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.username_var = tk.StringVar()
        u_entry = ttk.Entry(form, textvariable=self.username_var, width=32)
        u_entry.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        tk.Label(form, text="Password", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.password_var = tk.StringVar()
        p_entry = ttk.Entry(form, textvariable=self.password_var, width=32, show="•")
        p_entry.grid(row=3, column=0, sticky="ew", pady=(0, 14))

        if self._mode == "create_admin":
            tk.Label(form, text="Confirm password", bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=FONT_BASE).grid(row=4, column=0, sticky="w", pady=(0, 4))
            self.confirm_var = tk.StringVar()
            c_entry = ttk.Entry(form, textvariable=self.confirm_var, width=32, show="•")
            c_entry.grid(row=5, column=0, sticky="ew", pady=(0, 14))
            self._confirm_entry = c_entry
        else:
            self.confirm_var = None

        self.status_var = tk.StringVar(value="")
        status_lbl = tk.Label(form, textvariable=self.status_var,
                              bg=COLOR_CARD, fg=COLOR_RED, font=FONT_SMALL,
                              wraplength=300, justify="left")
        status_lbl.grid(row=6, column=0, sticky="w", pady=(0, 6))

        if self._mode == "create_admin":
            hint = (
                "Password must be at least "
                f"{auth.MIN_PASSWORD_LEN} characters and use at least 2 of: "
                "lowercase, uppercase, digits, symbols."
            )
            tk.Label(form, text=hint, bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_SMALL, wraplength=300, justify="left").grid(
                row=7, column=0, sticky="w", pady=(0, 10))

        btn_text = "Create Account" if self._mode == "create_admin" else "Sign In"
        sign_btn = tk.Button(form, text=btn_text,
                             command=self._submit,
                             bg=COLOR_ACCENT, fg="white",
                             activebackground="#1D4ED8", activeforeground="white",
                             font=FONT_BASE_BOLD, relief="flat", bd=0,
                             padx=16, pady=8, cursor="hand2")
        sign_btn.grid(row=8, column=0, sticky="ew", pady=(8, 0))

        # A small text link to switch between modes (create new / back to sign in).
        link_row = tk.Frame(form, bg=COLOR_CARD)
        link_row.grid(row=9, column=0, sticky="ew", pady=(12, 0))

        if self._mode == "login":
            tk.Label(link_row, text="No account yet?",
                     bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_SMALL).pack(side="left")
            switch_text = "Create one"
        else:
            tk.Label(link_row, text="Already have an account?",
                     bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_SMALL).pack(side="left")
            switch_text = "Sign in"

        link = tk.Label(link_row, text="  " + switch_text,
                        bg=COLOR_CARD, fg=COLOR_ACCENT,
                        font=("Segoe UI", 9, "underline"),
                        cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: self._toggle_mode())

        u_entry.focus_set()
        self.bind_all("<Return>", lambda e: self._submit())

    def _toggle_mode(self) -> None:
        self._mode = "create_admin" if self._mode == "login" else "login"
        self.status_var.set("")
        self._build()

    def _submit(self) -> None:
        uname = (self.username_var.get() or "").strip()
        pw = self.password_var.get() or ""

        if self._mode == "create_admin":
            confirm = (self.confirm_var.get() if self.confirm_var else "") or ""
            if pw != confirm:
                self.status_var.set("Passwords do not match.")
                return
            res = auth.create_user(uname, pw, is_admin=True)
            if not res.ok:
                self.status_var.set(res.message)
                return
            self.status_var.set("")
            self._mode = "login"
            self._build()
            self.status_var.set("Account created. Please sign in.")
            return

        res = auth.authenticate(uname, pw)
        if not res.ok:
            self.status_var.set(res.message)
            return

        self.unbind_all("<Return>")
        self.app.on_login_success(res.username or uname, res.is_admin)


# ============================================================
# SHELL (sidebar + page area)
# ============================================================

class ShellLayout(tk.Frame):
    """The main shell shown after login: top bar, sidebar nav, page area."""

    def __init__(self, master: "EmrShellApp", current_user: str):
        super().__init__(master, bg=COLOR_BG_APP)
        self.app = master
        self.current_user = current_user
        self.pack(fill="both", expand=True)

        self._nav_buttons: dict[str, tk.Label] = {}
        self._pages: dict[str, tk.Frame] = {}
        self._active_page_id = "dashboard"

        # Documents page is the only "rich" page in this iteration.
        self.documents_page: DocumentsPage | None = None

        self._build()
        self.show_page("dashboard")

    # ---- layout ----
    def _build(self) -> None:
        topbar = tk.Frame(self, bg=COLOR_TOPBAR_BG, height=48,
                          highlightbackground=COLOR_BORDER,
                          highlightthickness=1)
        topbar.pack(side="top", fill="x")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="  Chiro EMR", bg=COLOR_TOPBAR_BG,
                 fg=COLOR_TEXT, font=("Segoe UI", 13, "bold")).pack(side="left", padx=10)

        # Right side of topbar: user info + logout
        right = tk.Frame(topbar, bg=COLOR_TOPBAR_BG)
        right.pack(side="right", padx=10)

        tk.Label(right, text=f"Signed in as  {self.current_user}",
                 bg=COLOR_TOPBAR_BG, fg=COLOR_MUTED, font=FONT_SMALL
                 ).pack(side="left", padx=(0, 12))
        logout_btn = tk.Button(right, text="Sign Out",
                               command=self.app.logout,
                               bg=COLOR_TOPBAR_BG, fg=COLOR_ACCENT,
                               relief="flat", bd=0, font=FONT_BASE,
                               cursor="hand2",
                               activebackground=COLOR_TOPBAR_BG,
                               activeforeground="#1D4ED8")
        logout_btn.pack(side="left")

        body = tk.Frame(self, bg=COLOR_BG_APP)
        body.pack(side="top", fill="both", expand=True)

        sidebar = tk.Frame(body, bg=COLOR_BG_SIDEBAR, width=180,
                           highlightbackground=COLOR_BORDER, highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        for nav_id, label in NAV_ITEMS:
            self._make_nav_button(sidebar, nav_id, label)

        # Main page area
        self.page_area = tk.Frame(body, bg=COLOR_BG_APP)
        self.page_area.pack(side="left", fill="both", expand=True)

        # Build pages
        for nav_id, label in NAV_ITEMS:
            if nav_id == "dashboard":
                page = DashboardPage(self.page_area, self.current_user)
            elif nav_id == "documents":
                page = DocumentsPage(self.page_area, self)
                self.documents_page = page
            elif nav_id == "patients":
                page = PatientsPage(self.page_area, self)
            else:
                page = PlaceholderPage(self.page_area, label)
            self._pages[nav_id] = page

    def _make_nav_button(self, parent: tk.Frame, nav_id: str, label: str) -> None:
        btn = tk.Label(parent, text="   " + label, anchor="w",
                       bg=COLOR_BG_SIDEBAR, fg=COLOR_SIDEBAR_TEXT,
                       font=FONT_BASE, padx=10, pady=10, cursor="hand2")
        btn.pack(fill="x", padx=8, pady=2)

        def on_enter(_e=None, _id=nav_id):
            if self._active_page_id != _id:
                btn.configure(bg=COLOR_SIDEBAR_HOVER)

        def on_leave(_e=None, _id=nav_id):
            if self._active_page_id != _id:
                btn.configure(bg=COLOR_BG_SIDEBAR)

        def on_click(_e=None, _id=nav_id):
            self.show_page(_id)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", on_click)
        self._nav_buttons[nav_id] = btn

    def show_page(self, nav_id: str) -> None:
        if nav_id not in self._pages:
            return
        # Hide all
        for p in self._pages.values():
            p.pack_forget()
        # Show selected
        self._pages[nav_id].pack(fill="both", expand=True)
        # Refresh nav highlighting
        for nid, lbl in self._nav_buttons.items():
            if nid == nav_id:
                lbl.configure(bg=COLOR_SIDEBAR_ACTIVE_BG, fg=COLOR_SIDEBAR_ACTIVE_FG,
                              font=FONT_BASE_BOLD)
            else:
                lbl.configure(bg=COLOR_BG_SIDEBAR, fg=COLOR_SIDEBAR_TEXT,
                              font=FONT_BASE)
        self._active_page_id = nav_id


# ============================================================
# PAGES
# ============================================================

class PlaceholderPage(tk.Frame):
    def __init__(self, parent: tk.Misc, title: str):
        super().__init__(parent, bg=COLOR_BG_APP)
        wrap = tk.Frame(self, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(wrap, text=title, bg=COLOR_BG_APP,
                 fg=COLOR_TEXT, font=FONT_TITLE).pack(anchor="w")
        tk.Label(wrap, text="Coming soon.", bg=COLOR_BG_APP,
                 fg=COLOR_MUTED, font=FONT_BASE).pack(anchor="w", pady=(4, 12))

        card, body = make_card(wrap, "Placeholder")
        card.pack(fill="both", expand=True)
        tk.Label(body, text=f"The {title} workspace will be built later.",
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE).pack(anchor="w", pady=20)


class DashboardPage(tk.Frame):
    def __init__(self, parent: tk.Misc, current_user: str):
        super().__init__(parent, bg=COLOR_BG_APP)
        wrap = tk.Frame(self, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(wrap, text="Dashboard", bg=COLOR_BG_APP,
                 fg=COLOR_TEXT, font=FONT_TITLE).pack(anchor="w")
        tk.Label(wrap,
                 text=f"Welcome back, {current_user}. Company stats and overview will appear here.",
                 bg=COLOR_BG_APP, fg=COLOR_MUTED, font=FONT_BASE).pack(anchor="w", pady=(4, 16))

        # Stat cards row (placeholders)
        row = tk.Frame(wrap, bg=COLOR_BG_APP)
        row.pack(fill="x")
        for i, (label, value) in enumerate([
            ("Active Patients", "—"),
            ("Visits This Week", "—"),
            ("Open Tasks", "—"),
            ("Pending Documents", "—"),
        ]):
            card, body = make_card(row, label)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0), pady=(0, 12))
            tk.Label(body, text=value, bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(2, 6))
            tk.Label(body, text="Coming soon", bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_SMALL).pack(anchor="w")
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="stat")

        # Lower row
        lower = tk.Frame(wrap, bg=COLOR_BG_APP)
        lower.pack(fill="both", expand=True, pady=(8, 0))
        for i, title in enumerate(["Recent Activity", "Upcoming Appointments"]):
            card, body = make_card(lower, title)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            tk.Label(body, text="No data yet.", bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=FONT_BASE).pack(anchor="w", pady=20)
            lower.grid_columnconfigure(i, weight=1, uniform="lower")
        lower.grid_rowconfigure(0, weight=1)


# ============================================================
# DOCUMENTS PAGE — full implementation
# ============================================================

class DocumentsPage(tk.Frame):
    """
    Documents workspace.
    Layout:
      ┌──────────┬───────────────────────────────────────────────┐
      │  Filter  │   Sticky Notes |   Encounters   |  Documents  │
      │  sidebar │                |                |             │
      │          │----------------+----------------+-------------│
      │          │              Tasks                            │
      └──────────┴───────────────────────────────────────────────┘
    """

    def __init__(self, parent: tk.Misc, shell: ShellLayout):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell

        # Active patient state (folder Path or None)
        self.active_patient: dict | None = None

        # Patient search state (for the Documents-page search box)
        self._search_popup: tk.Toplevel | None = None
        self._search_listbox: tk.Listbox | None = None
        self._search_after_id: str | None = None
        self._search_results: list[dict] = []

        # Subprocess tracking (so we can detect when SOAP closes)
        self._soap_proc: subprocess.Popen | None = None
        self._soap_poll_after_id: str | None = None

        self._build()

        # Whenever this page becomes visible again, re-pull the active
        # patient from disk so edits made elsewhere (Patients page, SOAP)
        # are reflected immediately.
        self.bind("<Map>", lambda _e: self.refresh_active_patient_from_disk())

    # ---- layout ----
    def _build(self) -> None:
        outer = tk.Frame(self, bg=COLOR_BG_APP)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        # Selected patient header
        header = tk.Frame(outer, bg=COLOR_BG_APP)
        header.pack(fill="x", pady=(0, 10))

        tk.Label(header, text="SELECTED PATIENT", bg=COLOR_BG_APP,
                 fg=COLOR_MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.patient_name_var = tk.StringVar(value="No patient selected")
        tk.Label(header, textvariable=self.patient_name_var,
                 bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")

        body = tk.Frame(outer, bg=COLOR_BG_APP)
        body.pack(fill="both", expand=True)

        # Filter sidebar (left)
        self._build_filter_sidebar(body)

        # Right side (panels)
        right = tk.Frame(body, bg=COLOR_BG_APP)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # Top row: Sticky Notes | Encounters | Documents
        top_row = tk.Frame(right, bg=COLOR_BG_APP)
        top_row.pack(fill="both", expand=True)

        sticky_card, sticky_body = make_card(top_row, "Sticky Notes", "Coming soon")
        sticky_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_sticky_skeleton(sticky_body)

        enc_card, enc_body = make_card(top_row, "Encounters", "click a row to open SOAP")
        enc_card.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self._build_encounters_panel(enc_body)

        docs_card, docs_body = make_card(top_row, "Documents", "Coming soon")
        docs_card.grid(row=0, column=2, sticky="nsew")
        self._build_documents_skeleton(docs_body)

        top_row.grid_columnconfigure(0, weight=1, uniform="dp")
        top_row.grid_columnconfigure(1, weight=1, uniform="dp")
        top_row.grid_columnconfigure(2, weight=1, uniform="dp")
        top_row.grid_rowconfigure(0, weight=1)

        # Bottom row: Tasks
        tasks_card, tasks_body = make_card(right, "Tasks", "built-in coming")
        tasks_card.pack(fill="both", expand=True, pady=(12, 0))
        self._build_tasks_skeleton(tasks_body)

    def _build_filter_sidebar(self, parent: tk.Frame) -> None:
        side = tk.Frame(parent, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER, highlightthickness=1,
                        width=240)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        pad = {"padx": 14}
        tk.Label(side, text="Documents", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BIG).pack(anchor="w", pady=(14, 0), **pad)
        tk.Label(side, text="Date: Today", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(anchor="w", pady=(2, 8), **pad)

        # Date inputs (placeholders)
        date_row = tk.Frame(side, bg=COLOR_CARD)
        date_row.pack(fill="x", **pad)
        self.date_from_var = tk.StringVar(value="Today")
        self.date_to_var = tk.StringVar(value=datetime.now().strftime("%-m/%-d/%y") if os.name != "nt" else datetime.now().strftime("%#m/%#d/%y"))
        ttk.Entry(date_row, textvariable=self.date_from_var, width=10).pack(side="left")
        tk.Label(date_row, text="–", bg=COLOR_CARD, fg=COLOR_MUTED).pack(side="left", padx=4)
        ttk.Entry(date_row, textvariable=self.date_to_var, width=10).pack(side="left")

        chip_row = tk.Frame(side, bg=COLOR_CARD)
        chip_row.pack(fill="x", pady=(6, 12), **pad)
        for txt, accent in [("Today", True), ("3 Day", False), ("7 Day", False)]:
            b = tk.Label(chip_row, text=" " + txt + " ",
                         bg=(COLOR_ACCENT if accent else "#F1F5F9"),
                         fg=("white" if accent else COLOR_TEXT),
                         font=FONT_SMALL, padx=8, pady=3, cursor="hand2")
            b.pack(side="left", padx=(0, 6))

        tk.Label(side, text="Status", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE_BOLD).pack(anchor="w", pady=(4, 2), **pad)
        ttk.Combobox(side, values=["All visits", "Signed", "Unsigned"],
                     state="readonly").pack(fill="x", **pad)

        tk.Label(side, text="Practitioner", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE_BOLD).pack(anchor="w", pady=(12, 2), **pad)
        ttk.Combobox(side, values=["Tin, Dale"], state="readonly").pack(fill="x", **pad)

        # Patient search (matches the SOAP demographics search box,
        # except this one does NOT show the visit-picker popup — clicking
        # an Encounter handles that instead.)
        tk.Label(side, text="Patient", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE_BOLD).pack(anchor="w", pady=(16, 2), **pad)
        tk.Label(side,
                 text=("Search across all patient folders (Last / First / DOB). "
                       "Click a result to load it here."),
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
                 wraplength=210, justify="left").pack(anchor="w", **pad)

        search_frame = tk.Frame(side, bg=COLOR_CARD)
        search_frame.pack(fill="x", pady=(8, 0), **pad)

        # 3 small entries; same UX as the SOAP demographics search.
        self.search_last_var = tk.StringVar()
        self.search_first_var = tk.StringVar()
        self.search_dob_var = tk.StringVar()

        tk.Label(search_frame, text="Last", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        self.search_last_entry = ttk.Entry(search_frame, textvariable=self.search_last_var)
        self.search_last_entry.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        tk.Label(search_frame, text="First", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).grid(row=2, column=0, sticky="w")
        self.search_first_entry = ttk.Entry(search_frame, textvariable=self.search_first_var)
        self.search_first_entry.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        tk.Label(search_frame, text="DOB", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).grid(row=4, column=0, sticky="w")
        self.search_dob_entry = ttk.Entry(search_frame, textvariable=self.search_dob_var)
        self.search_dob_entry.grid(row=5, column=0, sticky="ew")

        search_frame.grid_columnconfigure(0, weight=1)

        for ent in (self.search_last_entry, self.search_first_entry, self.search_dob_entry):
            ent.bind("<KeyRelease>", self._on_search_keyrelease)
            ent.bind("<FocusOut>", lambda e: self.after(150, self._search_focus_out_check))
            ent.bind("<Escape>", lambda e: self._hide_search_popup())
            ent.bind("<Return>", self._on_search_return)
            ent.bind("<Down>", self._on_search_down)

        # Clear / Hint
        clear_btn = tk.Button(side, text="Clear patient",
                              command=self.clear_active_patient,
                              bg=COLOR_CARD, fg=COLOR_ACCENT, relief="flat", bd=0,
                              cursor="hand2", font=FONT_SMALL,
                              activebackground=COLOR_CARD, activeforeground="#1D4ED8")
        clear_btn.pack(anchor="w", padx=10, pady=(14, 0))

    # ---- panels ----
    def _build_sticky_skeleton(self, body: tk.Frame) -> None:
        self.sticky_empty_lbl = tk.Label(
            body, text="No sticky notes yet.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE)
        self.sticky_empty_lbl.pack(anchor="center", pady=40)

    def _build_documents_skeleton(self, body: tk.Frame) -> None:
        self.docs_empty_lbl = tk.Label(
            body, text="No documents uploaded yet.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE)
        self.docs_empty_lbl.pack(anchor="center", pady=40)

    def _build_tasks_skeleton(self, body: tk.Frame) -> None:
        self.tasks_empty_lbl = tk.Label(
            body, text="No tasks yet.",
            bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE)
        self.tasks_empty_lbl.pack(anchor="center", pady=40)

    def _build_encounters_panel(self, body: tk.Frame) -> None:
        # Hint line
        self.enc_hint_var = tk.StringVar(
            value="Search for a patient on the left to see encounters."
        )
        self.enc_hint_lbl = tk.Label(body, textvariable=self.enc_hint_var,
                                     bg=COLOR_CARD, fg=COLOR_MUTED,
                                     font=FONT_SMALL,
                                     wraplength=380, justify="left")
        self.enc_hint_lbl.pack(anchor="w", pady=(0, 8))

        # Scrollable list
        list_wrap = tk.Frame(body, bg=COLOR_CARD,
                             highlightbackground=COLOR_BORDER, highlightthickness=1)
        list_wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_wrap, bg=COLOR_CARD, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.enc_inner = tk.Frame(canvas, bg=COLOR_CARD)
        self._enc_window = canvas.create_window((0, 0), window=self.enc_inner, anchor="nw")
        self._enc_canvas = canvas

        def _on_inner_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfigure(self._enc_window, width=e.width)

        self.enc_inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel
        def _on_mw(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mw))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._render_encounters_empty_state()

    # ---- encounters rendering ----
    def _clear_encounters(self) -> None:
        for w in self.enc_inner.winfo_children():
            w.destroy()

    def _render_encounters_empty_state(self) -> None:
        self._clear_encounters()
        tk.Label(self.enc_inner,
                 text="No patient selected.",
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_BASE
                 ).pack(anchor="center", pady=40)

    def _render_encounters_for_patient(self, patient: dict) -> None:
        self._clear_encounters()
        folder = Path(patient["folder"])
        visits = collect_visits_for_patient(folder)

        if not visits:
            self.enc_hint_var.set(
                f"{patient['label']} — no encounters yet. "
                "Click below to start the first visit."
            )
            self._make_start_first_visit_row(patient)
            return

        self.enc_hint_var.set(
            f"{patient['label']} — {len(visits)} encounter(s). Click a row to open SOAP."
        )

        for visit in visits:
            self._make_encounter_row(visit)

    def _make_start_first_visit_row(self, patient: dict) -> None:
        """Empty-state placeholder: a clickable row that launches SOAP with a
        fresh Initial 1 exam ready for the just-created patient."""
        row = tk.Frame(self.enc_inner, bg=COLOR_CARD,
                       highlightbackground=COLOR_BORDER,
                       highlightthickness=1, cursor="hand2")
        row.pack(fill="x", padx=8, pady=(20, 4))

        marker = tk.Label(row, text="  +  ",
                          bg="#EEF2FF", fg=COLOR_ACCENT,
                          font=("Segoe UI", 12, "bold"), padx=4)
        marker.pack(side="left", fill="y")

        text_box = tk.Frame(row, bg=COLOR_CARD)
        text_box.pack(side="left", fill="both", expand=True, padx=8, pady=10)

        tk.Label(text_box, text="Start Initial Visit",
                 bg=COLOR_CARD, fg=COLOR_ACCENT,
                 font=FONT_BASE_BOLD).pack(anchor="w")
        tk.Label(text_box,
                 text="Opens the SOAP builder with a blank Initial 1 exam ready to fill in.",
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL,
                 wraplength=320, justify="left").pack(anchor="w", pady=(2, 0))

        def open_new(_e=None, _pid=patient.get("patient_id") or ""):
            if not _pid:
                messagebox.showerror("Cannot start visit",
                                     "This patient is missing a patient_id.")
                return
            self.launch_soap_for_patient_id(_pid)

        for w in (row, marker, text_box, *text_box.winfo_children()):
            w.bind("<Button-1>", open_new)

        def hover_in(_e=None):
            row.configure(bg="#F8FAFC")

        def hover_out(_e=None):
            row.configure(bg=COLOR_CARD)

        row.bind("<Enter>", hover_in)
        row.bind("<Leave>", hover_out)

        # Helpful hint below
        tk.Label(self.enc_inner,
                 text="The visit will appear here automatically once you save it.",
                 bg=COLOR_CARD, fg=COLOR_MUTED, font=FONT_SMALL
                 ).pack(anchor="center", pady=(6, 4))

    def _make_encounter_row(self, visit: dict) -> None:
        row = tk.Frame(self.enc_inner, bg=COLOR_CARD,
                       highlightbackground=COLOR_BORDER,
                       highlightthickness=1, cursor="hand2")
        row.pack(fill="x", padx=8, pady=4)

        is_signed = self._infer_signed_state(visit["path"])
        marker_bg = COLOR_GREEN_SOFT if is_signed else COLOR_RED_SOFT
        marker_fg = COLOR_GREEN if is_signed else COLOR_RED
        marker = tk.Label(row, text=" ✓ " if is_signed else " ✎ ",
                          bg=marker_bg, fg=marker_fg, font=FONT_BASE_BOLD,
                          padx=4)
        marker.pack(side="left", fill="y")

        text_box = tk.Frame(row, bg=COLOR_CARD)
        text_box.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        date_str = visit.get("exam_date") or "—"
        prov = visit.get("provider") or "—"
        exam_name = visit.get("exam_name") or ""

        line1 = tk.Frame(text_box, bg=COLOR_CARD)
        line1.pack(fill="x")
        tk.Label(line1, text=date_str, bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE_BOLD).pack(side="left")
        tk.Label(line1, text="  ·  ", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(side="left")
        tk.Label(line1, text=prov, bg=COLOR_CARD, fg=COLOR_ACCENT,
                 font=FONT_BASE_BOLD).pack(side="left")

        line2 = tk.Frame(text_box, bg=COLOR_CARD)
        line2.pack(fill="x")
        tk.Label(line2, text=exam_name, bg=COLOR_CARD,
                 fg=self._exam_type_color(exam_name),
                 font=FONT_BASE).pack(side="left")

        def open_visit(_e=None, _path=visit["path"]):
            self.launch_soap_for_path(_path)

        for w in (row, marker, text_box, line1, line2,
                  *line1.winfo_children(), *line2.winfo_children()):
            w.bind("<Button-1>", open_visit)

        def hover_in(_e=None):
            row.configure(bg="#F8FAFC")

        def hover_out(_e=None):
            row.configure(bg=COLOR_CARD)

        row.bind("<Enter>", hover_in)
        row.bind("<Leave>", hover_out)

    @staticmethod
    def _infer_signed_state(path: str) -> bool:
        """Heuristic: treat any exam JSON with a non-empty 'signed' key as signed; else unsigned."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
        except Exception:
            return False
        if isinstance(payload, dict):
            sig = payload.get("signed") or payload.get("signed_at") or payload.get("locked")
            if sig:
                return True
        return False

    @staticmethod
    def _exam_type_color(exam_name: str) -> str:
        s = (exam_name or "").lower()
        if "initial" in s:
            return "#2563EB"
        if "re-exam" in s or "reexam" in s:
            return "#7C3AED"
        if "review" in s:
            return "#0EA5E9"
        if "final" in s:
            return "#DB2777"
        return COLOR_GREEN

    # ---- patient search ----
    def _on_search_keyrelease(self, event=None):
        keysym = getattr(event, "keysym", "") or ""
        if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                      "Alt_L", "Alt_R", "Escape"):
            return
        if keysym in ("Up", "Down", "Return") and self._search_popup \
                and self._search_popup.winfo_exists():
            return
        if self._search_after_id is not None:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.after(220, self._search_refresh)

    def _search_refresh(self):
        self._search_after_id = None
        rows = scan_patients(
            self.search_last_var.get(),
            self.search_first_var.get(),
            self.search_dob_var.get(),
        )
        self._search_results = rows
        if not rows:
            self._hide_search_popup()
            return
        self._show_search_popup(rows)

    def _show_search_popup(self, rows: list[dict]):
        self._hide_search_popup()
        pop = tk.Toplevel(self)
        pop.wm_overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except Exception:
            pass

        lb_h = min(14, max(5, len(rows)))
        lb = tk.Listbox(pop, height=lb_h, width=46, activestyle="dotbox",
                        font=("Segoe UI", 10), selectmode=tk.SINGLE)
        lb.pack(fill="both", expand=True)

        for rec in rows:
            dob_s = (rec.get("dob") or "").strip()
            tail = f"   ·   DOB {dob_s}" if dob_s else ""
            lb.insert(tk.END, f"{rec.get('label', '')}{tail}")

        self.update_idletasks()
        ent = self.search_last_entry
        x = ent.winfo_rootx()
        y = ent.winfo_rooty() + ent.winfo_height()
        pop.geometry(f"+{x}+{y}")

        def pick(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            self._activate_search_index(int(sel[0]))

        lb.bind("<Double-Button-1>", pick)
        lb.bind("<Return>", pick)
        lb.bind("<Escape>", lambda _e: self._hide_search_popup())
        pop.bind("<Escape>", lambda _e: self._hide_search_popup())

        self._search_popup = pop
        self._search_listbox = lb

    def _hide_search_popup(self):
        if self._search_popup is not None:
            try:
                if self._search_popup.winfo_exists():
                    self._search_popup.destroy()
            except Exception:
                pass
        self._search_popup = None
        self._search_listbox = None

    def _search_focus_out_check(self):
        pop = self._search_popup
        if pop is None:
            return
        try:
            if not pop.winfo_exists():
                self._search_popup = None
                self._search_listbox = None
                return
        except Exception:
            return
        fg = self.focus_get()
        if fg is None:
            self._hide_search_popup()
            return
        for ent in (self.search_last_entry, self.search_first_entry, self.search_dob_entry):
            if fg == ent:
                return
        # If focus is inside the popup, leave it
        w = fg
        while w is not None:
            if w == pop:
                return
            w = getattr(w, "master", None)
        self._hide_search_popup()

    def _on_search_return(self, _event=None):
        if self._search_popup and self._search_popup.winfo_exists() and self._search_results:
            idx = 0
            lb = self._search_listbox
            if lb:
                sel = lb.curselection()
                if sel:
                    idx = int(sel[0])
            self._activate_search_index(idx)
            return "break"
        return None

    def _on_search_down(self, _event=None):
        lb = self._search_listbox
        pop = self._search_popup
        if lb is None or pop is None or not pop.winfo_exists() or lb.size() < 1:
            return None
        lb.focus_set()
        lb.selection_clear(0, tk.END)
        lb.selection_set(0)
        lb.activate(0)
        return "break"

    def _activate_search_index(self, idx: int):
        if idx < 0 or idx >= len(self._search_results):
            return
        rec = self._search_results[idx]
        self.set_active_patient(rec)
        self.search_last_var.set("")
        self.search_first_var.set("")
        self.search_dob_var.set("")
        self._hide_search_popup()

    # ---- public: active patient ----
    def set_active_patient(self, patient: dict) -> None:
        self.active_patient = patient
        label = patient.get("label") or "(unnamed)"
        dob = (patient.get("dob") or "").strip()
        if dob:
            label = f"{label}    DOB {dob}"
        self.patient_name_var.set(label)
        write_shell_state({
            "active_patient_id": patient.get("patient_id"),
            "active_patient_folder": patient.get("folder"),
            "active_patient_label": patient.get("label"),
        })
        self._render_encounters_for_patient(patient)

    def clear_active_patient(self) -> None:
        self.active_patient = None
        self.patient_name_var.set("No patient selected")
        self._render_encounters_empty_state()
        self.enc_hint_var.set("Search for a patient on the left to see encounters.")
        write_shell_state({"active_patient_id": None,
                           "active_patient_folder": None,
                           "active_patient_label": None})

    def reload_active_patient_from_shell_state(self) -> None:
        """After SOAP exits, re-read shell state in case the patient was switched."""
        st = read_shell_state()
        folder = st.get("active_patient_folder")
        if not folder:
            return
        try:
            rec = patient_record_from_folder(Path(folder))
        except Exception:
            rec = None
        if rec:
            # Only repaint if it's actually different OR if we want a refresh
            self.set_active_patient(rec)
        else:
            # Fallback to the snapshot from shell_state
            self.set_active_patient({
                "folder": folder,
                "patient_id": st.get("active_patient_id") or "",
                "last": "",
                "first": "",
                "dob": "",
                "label": st.get("active_patient_label") or "",
            })

    def refresh_active_patient_from_disk(self) -> None:
        """
        Re-resolve the active patient from disk by patient_id.

        Called when the page is shown again or when the Patients page edits a
        patient. The folder may have been renamed (last/first changed) so we
        look up by patient_id rather than the cached folder path. The header
        label and Encounters list are repainted with fresh data.
        """
        if not self.active_patient:
            return
        pid = (self.active_patient.get("patient_id") or "").strip()
        if not pid:
            return

        folder: Path | None = None
        try:
            f = find_patient_folder_by_id(Path(PATIENTS_ID_ROOT), pid)
            if f and f.is_dir():
                folder = f
        except Exception:
            folder = None

        if folder is None:
            # Cached folder path — try as last resort
            cached = self.active_patient.get("folder") or ""
            if cached and Path(cached).is_dir():
                folder = Path(cached)

        if folder is None:
            # The patient was deleted under us — clear the page.
            self.clear_active_patient()
            return

        rec = patient_record_from_folder(folder)
        if rec:
            self.set_active_patient(rec)

    # ---- launch SOAP ----
    def _launch_soap(self, extra_args: list[str]) -> None:
        """Common launcher: start chiro_app.py as a subprocess, hide the shell,
        poll for exit, then restore the shell + refresh active patient."""
        if self._soap_proc is not None and self._soap_proc.poll() is None:
            messagebox.showinfo("SOAP open",
                                "The SOAP builder is already open. Exit it first.")
            return

        # Persist current active patient so SOAP can pick it up if needed
        if self.active_patient:
            write_shell_state({
                "active_patient_id": self.active_patient.get("patient_id"),
                "active_patient_folder": self.active_patient.get("folder"),
                "active_patient_label": self.active_patient.get("label"),
            })

        chiro = Path(__file__).resolve().parent / "chiro_app.py"
        if not chiro.exists():
            messagebox.showerror("Missing file", f"Could not find: {chiro}")
            return

        args = [
            sys.executable,
            str(chiro),
            "--from-shell",
            "--shell-state-file", str(shell_state_path()),
            *extra_args,
        ]

        try:
            self._soap_proc = subprocess.Popen(args)
        except Exception as e:
            messagebox.showerror("Could not launch SOAP", str(e))
            return

        # Hide shell window while SOAP is open
        self.shell.app.withdraw()

        # Poll for subprocess exit
        self._poll_soap_proc()

    def launch_soap_for_path(self, exam_path: str) -> None:
        """Open SOAP focused on a specific saved exam JSON."""
        self._launch_soap(["--open-exam", exam_path] if exam_path else [])

    def launch_soap_for_patient_id(self, patient_id: str) -> None:
        """Open SOAP focused on this patient with a fresh Initial 1 exam
        ready to fill in (if they have no exams yet) or their newest exam."""
        if not (patient_id or "").strip():
            return
        self._launch_soap(["--patient-id", patient_id])

    def _poll_soap_proc(self):
        proc = self._soap_proc
        if proc is None:
            return
        rc = proc.poll()
        if rc is None:
            self._soap_poll_after_id = self.after(400, self._poll_soap_proc)
            return

        # SOAP closed — show shell again, refresh active patient
        self._soap_proc = None
        self._soap_poll_after_id = None
        try:
            self.shell.app.deiconify()
            self.shell.app.lift()
            self.shell.app.focus_force()
        except Exception:
            pass
        self.reload_active_patient_from_shell_state()


# ============================================================
# PATIENTS PAGE — list / detail / form (new + edit)
# ============================================================

GENDER_CHOICES = ["MALE", "FEMALE", "OTHER"]


def _format_address(addr) -> str:
    """Render the address dict (or legacy string) as a single display line."""
    if isinstance(addr, str):
        return addr.strip()
    if not isinstance(addr, dict):
        return ""
    street = (addr.get("street") or "").strip()
    city = (addr.get("city") or "").strip()
    state = (addr.get("state") or "").strip()
    zipc = (addr.get("zip") or "").strip()
    parts = []
    if street:
        parts.append(street)
    tail = ", ".join(p for p in [city] if p)
    last = " ".join(p for p in [state, zipc] if p)
    line2 = ", ".join(p for p in [tail, last] if p)
    if line2:
        parts.append(line2)
    return ", ".join(parts)


class PatientsPage(tk.Frame):
    """List / detail / new+edit form for patient records."""

    def __init__(self, parent: tk.Misc, shell: ShellLayout):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.shell = shell

        # Three subviews stacked in self; only one packed at a time.
        self._views: dict[str, tk.Frame] = {}
        for name in ("list", "detail", "form"):
            self._views[name] = tk.Frame(self, bg=COLOR_BG_APP)

        # Selected record (used by detail and edit-mode form)
        self._selected_rec: dict | None = None
        self._form_mode: str = "new"  # "new" | "edit"

        # Sort state for the patient list
        self._sort_col: str = "name"
        self._sort_desc: bool = False

        # Treeview row id -> patient record (so click handler can resolve)
        self._row_to_rec: dict[str, dict] = {}

        # Build list view once; detail/form rebuilt on demand
        self._build_list_view(self._views["list"])

        # Track which subview is currently active (so we can refresh the right
        # one when the page becomes visible again)
        self._active_subview: str = "list"

        self._show("list")

        # When this page becomes visible, refresh whichever subview is active
        # so changes made elsewhere (e.g. SOAP rename) are picked up.
        self.bind("<Map>", lambda _e: self._on_page_shown())

    # ---- subview switching ----
    def _show(self, name: str) -> None:
        for n, v in self._views.items():
            v.pack_forget()
        self._views[name].pack(fill="both", expand=True)
        self._active_subview = name

    def _on_page_shown(self) -> None:
        """Refresh the currently-visible subview from disk."""
        if self._active_subview == "list":
            self._refresh_list()
        elif self._active_subview == "detail" and self._selected_rec:
            # Patient may have been renamed elsewhere — re-resolve folder by
            # patient_id and rebuild the detail view from fresh disk data.
            pid = (self._selected_rec.get("patient_id") or "").strip()
            if pid:
                folder = find_patient_folder_by_id(Path(PATIENTS_ID_ROOT), pid)
                if folder and folder.is_dir():
                    fresh = patient_record_from_folder(folder)
                    if fresh:
                        self._selected_rec = fresh
            self._rebuild("detail", self._build_detail_view)
        # form: don't trample user's input

    def _rebuild(self, name: str, builder) -> None:
        frame = self._views[name]
        for w in frame.winfo_children():
            w.destroy()
        builder(frame)

    # ============================================================
    # LIST VIEW
    # ============================================================
    def _build_list_view(self, parent: tk.Frame) -> None:
        wrap = tk.Frame(parent, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        header = tk.Frame(wrap, bg=COLOR_BG_APP)
        header.pack(fill="x")
        tk.Label(header, text="Patients", bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=FONT_TITLE).pack(side="left")

        new_btn = tk.Button(header, text="+ New Patient",
                            command=self._on_new,
                            bg=COLOR_ACCENT, fg="white",
                            relief="flat", bd=0, padx=14, pady=6,
                            font=FONT_BASE_BOLD, cursor="hand2",
                            activebackground="#1D4ED8",
                            activeforeground="white")
        new_btn.pack(side="right")

        # Filter row
        filter_row = tk.Frame(wrap, bg=COLOR_BG_APP)
        filter_row.pack(fill="x", pady=(10, 8))
        tk.Label(filter_row, text="Filter:", bg=COLOR_BG_APP,
                 fg=COLOR_MUTED, font=FONT_BASE).pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())
        ttk.Entry(filter_row, textvariable=self.filter_var, width=36).pack(side="left")

        self.count_var = tk.StringVar(value="")
        tk.Label(filter_row, textvariable=self.count_var,
                 bg=COLOR_BG_APP, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(side="right")

        # Card containing the table
        card = tk.Frame(wrap, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)

        cols = ("name", "dob", "gender", "phone", "email", "last_visit")
        col_titles = {
            "name": "NAME",
            "dob": "DATE OF BIRTH",
            "gender": "GENDER",
            "phone": "PHONE",
            "email": "EMAIL",
            "last_visit": "LAST VISIT",
        }
        col_widths = {
            "name": 220, "dob": 120, "gender": 90,
            "phone": 130, "email": 220, "last_visit": 120,
        }

        # Style headings + rows
        try:
            style = ttk.Style()
            style.configure("Patients.Treeview",
                            background=COLOR_CARD, fieldbackground=COLOR_CARD,
                            foreground=COLOR_TEXT, rowheight=28,
                            borderwidth=0, font=FONT_BASE)
            style.configure("Patients.Treeview.Heading",
                            background="#F8FAFC", foreground=COLOR_MUTED,
                            font=("Segoe UI", 9, "bold"))
            style.layout("Patients.Treeview",
                         [("Patients.Treeview.treearea", {"sticky": "nswe"})])
        except Exception:
            pass

        tree = ttk.Treeview(card, columns=cols, show="headings",
                            style="Patients.Treeview", selectmode="browse")
        for c in cols:
            tree.heading(c, text=col_titles[c],
                         command=lambda cc=c: self._sort_by(cc))
            tree.column(c, width=col_widths[c], anchor="w")

        vsb = ttk.Scrollbar(card, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tree.tag_configure("name_link", foreground=COLOR_ACCENT)
        tree.bind("<Double-Button-1>", self._on_row_open)
        tree.bind("<Return>", self._on_row_open)
        tree.bind("<<TreeviewSelect>>", lambda _e: None)

        self._tree = tree

    def _refresh_list(self) -> None:
        if not hasattr(self, "_tree"):
            return
        try:
            self._tree.delete(*self._tree.get_children())
        except Exception:
            return

        self._row_to_rec.clear()
        q = (getattr(self, "filter_var", tk.StringVar()).get() or "").strip().lower()

        all_patients = list_all_patients()
        rows: list[tuple[dict, str, str, str, str, str, str]] = []
        for rec in all_patients:
            folder = Path(rec["folder"])
            profile = read_patient_profile(folder)

            last = (profile.get("last_name") or rec.get("last") or "").strip()
            first = (profile.get("first_name") or rec.get("first") or "").strip()
            dob = (profile.get("dob") or rec.get("dob") or "").strip()
            gender = (profile.get("gender") or "").strip().upper()
            phone = (profile.get("phone") or "").strip()
            email = (profile.get("email") or "").strip()
            last_visit = get_last_visit_date(folder)

            name = to_last_first(last, first) or folder.name
            if q:
                hay = " ".join([name, dob, gender, phone, email]).lower()
                if q not in hay:
                    continue
            rows.append((rec, name, dob, gender, phone, email, last_visit))

        # Sort
        def sort_key(item):
            _rec, name, dob, gender, phone, email, lv = item
            if self._sort_col == "name":
                return name.lower()
            if self._sort_col == "dob":
                return dob
            if self._sort_col == "gender":
                return gender
            if self._sort_col == "phone":
                return phone
            if self._sort_col == "email":
                return email.lower()
            if self._sort_col == "last_visit":
                return lv
            return name.lower()

        rows.sort(key=sort_key, reverse=self._sort_desc)

        for rec, name, dob, gender, phone, email, lv in rows:
            row_id = self._tree.insert(
                "", "end",
                values=(name, dob, gender, phone, email, lv),
                tags=("name_link",),
            )
            self._row_to_rec[row_id] = rec

        try:
            self.count_var.set(f"{len(rows)} patient(s)")
        except Exception:
            pass

    def _sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._refresh_list()

    def _on_row_open(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        rec = self._row_to_rec.get(sel[0])
        if not rec:
            return
        self._open_detail(rec)

    # ============================================================
    # DETAIL VIEW
    # ============================================================
    def _open_detail(self, rec: dict) -> None:
        self._selected_rec = rec
        self._rebuild("detail", self._build_detail_view)
        self._show("detail")

    def _build_detail_view(self, parent: tk.Frame) -> None:
        rec = self._selected_rec or {}
        folder = Path(rec.get("folder") or "")
        profile = read_patient_profile(folder) if folder.exists() else {}

        wrap = tk.Frame(parent, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        # Back link
        back = tk.Label(wrap, text="← Back to Patients",
                        bg=COLOR_BG_APP, fg=COLOR_ACCENT,
                        font=("Segoe UI", 9), cursor="hand2")
        back.pack(anchor="w")
        back.bind("<Button-1>", lambda _e: self._show("list"))

        # Header row
        header = tk.Frame(wrap, bg=COLOR_BG_APP)
        header.pack(fill="x", pady=(8, 14))
        last = (profile.get("last_name") or rec.get("last") or "").strip()
        first = (profile.get("first_name") or rec.get("first") or "").strip()
        title = (f"{first} {last}".strip()) or rec.get("label") or "Patient"
        tk.Label(header, text=title, bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=FONT_TITLE).pack(side="left")

        edit_btn = tk.Button(header, text="Edit", command=self._on_edit,
                             bg=COLOR_ACCENT, fg="white",
                             activebackground="#1D4ED8", activeforeground="white",
                             relief="flat", bd=0, padx=14, pady=6,
                             font=FONT_BASE_BOLD, cursor="hand2")
        edit_btn.pack(side="right", padx=(8, 0))

        del_btn = tk.Button(header, text="Delete", command=self._on_delete,
                            bg=COLOR_CARD, fg=COLOR_RED,
                            activebackground="#FEF2F2", activeforeground=COLOR_RED,
                            relief="solid", bd=1,
                            highlightbackground=COLOR_RED,
                            padx=14, pady=5,
                            font=FONT_BASE_BOLD, cursor="hand2")
        del_btn.pack(side="right")

        # Card with fields
        card = tk.Frame(wrap, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))

        body = tk.Frame(card, bg=COLOR_CARD)
        body.pack(fill="x", padx=20, pady=20)

        def field_pair(row, col, label, value):
            cell = tk.Frame(body, bg=COLOR_CARD)
            cell.grid(row=row, column=col, sticky="nw", padx=(0, 30), pady=(0, 14))
            tk.Label(cell, text=label.upper(), bg=COLOR_CARD, fg=COLOR_MUTED,
                     font=("Segoe UI", 9, "bold")).pack(anchor="w")
            tk.Label(cell, text=(value or "—"), bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=FONT_BASE).pack(anchor="w", pady=(2, 0))

        gender = (profile.get("gender") or "").strip().upper()
        email = (profile.get("email") or "").strip()
        phone = (profile.get("phone") or "").strip()
        dob = (profile.get("dob") or rec.get("dob") or "").strip()
        addr = profile.get("address")

        field_pair(0, 0, "First name", first)
        field_pair(0, 1, "Last name", last)
        field_pair(1, 0, "Date of birth", dob)
        field_pair(1, 1, "Gender", gender)
        field_pair(2, 0, "Email", email)
        field_pair(2, 1, "Phone", phone)
        field_pair(3, 0, "Address", _format_address(addr))

        body.grid_columnconfigure(0, weight=1, uniform="d")
        body.grid_columnconfigure(1, weight=1, uniform="d")

        # Patient ID hint
        tk.Label(wrap, text=f"Patient ID: {rec.get('patient_id', '')}",
                 bg=COLOR_BG_APP, fg=COLOR_MUTED, font=FONT_SMALL
                 ).pack(anchor="w")

    # ============================================================
    # FORM VIEW (new + edit)
    # ============================================================
    def _on_new(self) -> None:
        self._selected_rec = None
        self._form_mode = "new"
        self._rebuild("form", self._build_form_view)
        self._show("form")

    def _on_edit(self) -> None:
        if not self._selected_rec:
            return
        self._form_mode = "edit"
        self._rebuild("form", self._build_form_view)
        self._show("form")

    def _build_form_view(self, parent: tk.Frame) -> None:
        is_edit = (self._form_mode == "edit")
        rec = self._selected_rec or {}
        folder = Path(rec.get("folder") or "")
        profile = read_patient_profile(folder) if (is_edit and folder.exists()) else {}

        # Pre-fill vars
        self.f_first = tk.StringVar(value=profile.get("first_name") or "")
        self.f_last = tk.StringVar(value=profile.get("last_name") or "")
        self.f_dob = tk.StringVar(value=profile.get("dob") or "")
        self.f_gender = tk.StringVar(value=(profile.get("gender") or "").upper())
        self.f_email = tk.StringVar(value=profile.get("email") or "")
        self.f_phone = tk.StringVar(value=profile.get("phone") or "")
        addr = profile.get("address") or {}
        if isinstance(addr, str):
            addr = {"street": addr, "city": "", "state": "", "zip": ""}
        self.f_street = tk.StringVar(value=addr.get("street") or "")
        self.f_city = tk.StringVar(value=addr.get("city") or "")
        self.f_state = tk.StringVar(value=addr.get("state") or "")
        self.f_zip = tk.StringVar(value=addr.get("zip") or "")

        wrap = tk.Frame(parent, bg=COLOR_BG_APP)
        wrap.pack(fill="both", expand=True, padx=20, pady=20)

        back = tk.Label(wrap, text="← Back to Patients",
                        bg=COLOR_BG_APP, fg=COLOR_ACCENT,
                        font=("Segoe UI", 9), cursor="hand2")
        back.pack(anchor="w")
        back.bind("<Button-1>", lambda _e: self._cancel_form())

        # Title
        if is_edit:
            first = self.f_first.get().strip() or rec.get("first") or ""
            last = self.f_last.get().strip() or rec.get("last") or ""
            title = (f"{first} {last}".strip()) or rec.get("label") or "Edit patient"
        else:
            title = "New Patient"
        tk.Label(wrap, text=title, bg=COLOR_BG_APP, fg=COLOR_TEXT,
                 font=FONT_TITLE).pack(anchor="w", pady=(8, 14))

        # Card
        card = tk.Frame(wrap, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(fill="x")

        body = tk.Frame(card, bg=COLOR_CARD)
        body.pack(fill="x", padx=20, pady=20)

        def label(row, col, text, required=False):
            t = text + (" *" if required else "")
            cell = tk.Frame(body, bg=COLOR_CARD)
            cell.grid(row=row, column=col, sticky="ew", padx=(0, 14), pady=(0, 4))
            tk.Label(cell, text=t, bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=FONT_BASE).pack(anchor="w")
            return cell

        def entry(row, col, var, **kwargs):
            ent = ttk.Entry(body, textvariable=var, **kwargs)
            ent.grid(row=row, column=col, sticky="ew", padx=(0, 14), pady=(0, 12))
            return ent

        # Row 0: First/Last labels
        label(0, 0, "First Name", required=True)
        label(0, 1, "Last Name", required=True)
        # Row 1: First/Last entries
        entry(1, 0, self.f_first)
        entry(1, 1, self.f_last)

        # Row 2: DOB / Gender labels
        label(2, 0, "Date of Birth", required=True)
        label(2, 1, "Gender", required=True)
        # Row 3: DOB / Gender entries
        dob_frame = tk.Frame(body, bg=COLOR_CARD)
        dob_frame.grid(row=3, column=0, sticky="ew", padx=(0, 14), pady=(0, 12))
        ttk.Entry(dob_frame, textvariable=self.f_dob, width=24).pack(side="left", fill="x", expand=True)
        tk.Label(dob_frame, text="MM/DD/YYYY", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=FONT_SMALL).pack(side="left", padx=(8, 0))

        gender_combo = ttk.Combobox(body, textvariable=self.f_gender,
                                    values=GENDER_CHOICES, state="readonly")
        gender_combo.grid(row=3, column=1, sticky="ew", padx=(0, 14), pady=(0, 12))

        # Row 4–5: Email
        label(4, 0, "Email")
        entry(5, 0, self.f_email)
        body.grid_rowconfigure(5, weight=0)
        # span email across both columns visually
        body.grid_slaves(row=5, column=0)[0].grid_configure(columnspan=2)
        body.grid_slaves(row=4, column=0)[0].grid_configure(columnspan=2)

        # Row 6–7: Phone
        label(6, 0, "Phone")
        entry(7, 0, self.f_phone)
        body.grid_slaves(row=7, column=0)[0].grid_configure(columnspan=2)
        body.grid_slaves(row=6, column=0)[0].grid_configure(columnspan=2)

        # Row 8–9: Street (full width)
        label(8, 0, "Address — Street")
        entry(9, 0, self.f_street)
        body.grid_slaves(row=9, column=0)[0].grid_configure(columnspan=2)
        body.grid_slaves(row=8, column=0)[0].grid_configure(columnspan=2)

        # Row 10: City | State | ZIP labels (3-up)
        addr_lbl = tk.Frame(body, bg=COLOR_CARD)
        addr_lbl.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, 0))
        addr_lbl.grid_columnconfigure(0, weight=3, uniform="addr")
        addr_lbl.grid_columnconfigure(1, weight=1, uniform="addr")
        addr_lbl.grid_columnconfigure(2, weight=1, uniform="addr")
        tk.Label(addr_lbl, text="City", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Label(addr_lbl, text="State", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE).grid(row=0, column=1, sticky="w", padx=(0, 8))
        tk.Label(addr_lbl, text="ZIP", bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_BASE).grid(row=0, column=2, sticky="w")

        # Row 11: City / State / ZIP entries
        addr_row = tk.Frame(body, bg=COLOR_CARD)
        addr_row.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(2, 12))
        addr_row.grid_columnconfigure(0, weight=3, uniform="addr")
        addr_row.grid_columnconfigure(1, weight=1, uniform="addr")
        addr_row.grid_columnconfigure(2, weight=1, uniform="addr")
        ttk.Entry(addr_row, textvariable=self.f_city).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Entry(addr_row, textvariable=self.f_state).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Entry(addr_row, textvariable=self.f_zip).grid(row=0, column=2, sticky="ew")

        body.grid_columnconfigure(0, weight=1, uniform="form")
        body.grid_columnconfigure(1, weight=1, uniform="form")

        # Status / error line
        self.form_status_var = tk.StringVar(value="")
        tk.Label(card, textvariable=self.form_status_var,
                 bg=COLOR_CARD, fg=COLOR_RED, font=FONT_SMALL,
                 wraplength=600, justify="left"
                 ).pack(anchor="w", padx=20)

        # Buttons
        btns = tk.Frame(card, bg=COLOR_CARD)
        btns.pack(fill="x", padx=20, pady=(8, 16))
        save_btn = tk.Button(btns, text="Save Changes" if is_edit else "Save",
                             command=self._save_form,
                             bg=COLOR_ACCENT, fg="white",
                             activebackground="#1D4ED8", activeforeground="white",
                             relief="flat", bd=0, padx=18, pady=8,
                             font=FONT_BASE_BOLD, cursor="hand2")
        save_btn.pack(side="left")

        cancel_btn = tk.Button(btns, text="Cancel",
                               command=self._cancel_form,
                               bg=COLOR_CARD, fg=COLOR_TEXT,
                               relief="solid", bd=1,
                               padx=18, pady=7,
                               font=FONT_BASE, cursor="hand2",
                               activebackground="#F1F5F9",
                               activeforeground=COLOR_TEXT)
        cancel_btn.pack(side="left", padx=(8, 0))

    def _cancel_form(self) -> None:
        if self._form_mode == "edit" and self._selected_rec:
            self._open_detail(self._selected_rec)
        else:
            self._show("list")

    def _save_form(self) -> None:
        first = (self.f_first.get() or "").strip()
        last = (self.f_last.get() or "").strip()
        dob_raw = (self.f_dob.get() or "").strip()
        gender = (self.f_gender.get() or "").strip().upper()
        email = (self.f_email.get() or "").strip()
        phone = (self.f_phone.get() or "").strip()
        street = (self.f_street.get() or "").strip()
        city = (self.f_city.get() or "").strip()
        state = (self.f_state.get() or "").strip()
        zipc = (self.f_zip.get() or "").strip()

        # Required
        missing = [name for name, val in [
            ("First Name", first), ("Last Name", last),
            ("Date of Birth", dob_raw), ("Gender", gender),
        ] if not val]
        if missing:
            self.form_status_var.set("Please fill in: " + ", ".join(missing))
            return

        if gender not in GENDER_CHOICES:
            self.form_status_var.set("Gender must be one of: " + ", ".join(GENDER_CHOICES))
            return

        dob = normalize_mmddyyyy(dob_raw)
        if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", dob):
            self.form_status_var.set("Date of Birth must be MM/DD/YYYY (e.g. 02/02/1972).")
            return

        # Build profile
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        if self._form_mode == "edit" and self._selected_rec:
            pid = (self._selected_rec.get("patient_id") or "").strip()
            if not pid:
                self.form_status_var.set("Cannot edit: missing patient_id.")
                return
        else:
            pid = new_patient_id()

        # Make / locate folder. get_patient_root will rename it on edit if name changed.
        try:
            folder = get_patient_root(pid, last, first)
        except Exception as e:
            self.form_status_var.set(f"Could not create patient folder: {e}")
            return

        # Preserve any existing profile fields we don't manage (forward-compat)
        existing = read_patient_profile(folder) if self._form_mode == "edit" else {}
        profile = dict(existing)
        profile.update({
            "patient_id": pid,
            "first_name": first,
            "last_name": last,
            "dob": dob,
            "gender": gender,
            "email": email,
            "phone": phone,
            "address": {
                "street": street, "city": city, "state": state, "zip": zipc,
            },
            "updated_at": now_iso,
        })
        if "created_at" not in profile:
            profile["created_at"] = now_iso

        try:
            write_patient_profile(folder, profile)
        except Exception as e:
            self.form_status_var.set(f"Could not save patient.json: {e}")
            return

        # Build a fresh record + open detail
        new_rec = patient_record_from_folder(folder) or {
            "folder": str(folder.resolve()),
            "patient_id": pid, "last": last, "first": first, "dob": dob,
            "label": to_last_first(last, first) or pid,
        }
        self._selected_rec = new_rec

        # If the edited patient is the active patient on the Documents page,
        # push the refreshed record over so its header and Encounters list
        # repaint immediately (folder may have been renamed).
        try:
            doc = self.shell.documents_page
            if doc and doc.active_patient and \
               (doc.active_patient.get("patient_id") or "").strip() == pid:
                doc.set_active_patient(new_rec)
        except Exception:
            pass

        self._open_detail(new_rec)

    # ============================================================
    # DELETE
    # ============================================================
    def _on_delete(self) -> None:
        rec = self._selected_rec
        if not rec:
            return
        folder = Path(rec.get("folder") or "")
        if not folder.exists():
            messagebox.showerror("Delete", "Patient folder not found.")
            return

        visit_count = len(collect_visits_for_patient(folder))
        warn = (
            f"Permanently delete this patient and ALL their data?\n\n"
            f"  Name:   {rec.get('label') or folder.name}\n"
            f"  Folder: {folder}\n"
            f"  Visits: {visit_count}\n\n"
            f"This will remove every exam, PDF, document, and image stored "
            f"under this patient. This cannot be undone."
        )
        if not messagebox.askyesno("Delete patient — confirm", warn, icon="warning"):
            return

        try:
            shutil.rmtree(folder)
        except Exception as e:
            messagebox.showerror("Delete failed", f"Could not delete folder:\n{e}")
            return

        # If this patient was the active patient on Documents, clear it
        try:
            doc = self.shell.documents_page
            if doc and doc.active_patient and \
               Path(doc.active_patient.get("folder") or "").resolve() == folder.resolve():
                doc.clear_active_patient()
        except Exception:
            pass

        self._selected_rec = None
        self._show("list")
        self._refresh_list()


# ============================================================
# TOP-LEVEL APP CONTROLLER
# ============================================================

class EmrShellApp(tk.Tk):
    """
    Single tk.Tk root that swaps content between Login and Shell.
    """

    def __init__(self):
        super().__init__()
        self.title("Chiro EMR")
        self._set_initial_geometry(login=True)
        self.configure(bg=COLOR_BG_APP)

        # Better-looking ttk theme if available
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        self._screen: tk.Frame | None = None
        self.current_user: str | None = None

        self._show_login()

    def _set_initial_geometry(self, login: bool):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if login:
            w, h = 480, 540
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(420, 480)
        else:
            w = min(1280, sw - 80)
            h = min(820, sh - 80)
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(1000, 640)

    def _clear_screen(self):
        if self._screen is not None:
            try:
                self._screen.destroy()
            except Exception:
                pass
            self._screen = None

    def _show_login(self):
        self._clear_screen()
        self._set_initial_geometry(login=True)
        self._screen = LoginScreen(self)

    def _show_shell(self):
        self._clear_screen()
        self._set_initial_geometry(login=False)
        self._screen = ShellLayout(self, self.current_user or "user")

    # ---- callbacks ----
    def on_login_success(self, username: str, _is_admin: bool):
        self.current_user = username
        self._show_shell()

    def logout(self):
        if not messagebox.askyesno("Sign out", "Sign out of the EMR?"):
            return
        self.current_user = None
        self._show_login()


def main():
    app = EmrShellApp()
    app.mainloop()


if __name__ == "__main__":
    main()
