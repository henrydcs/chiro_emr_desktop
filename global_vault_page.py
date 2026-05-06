# global_vault_page.py
"""
Clinic-wide ("global") document vault.

Mirrors DocVaultPage but is rooted at <DATA_DIR>/global_vault/ instead of a
per-patient folder, so the same set of reference documents (Attorney Lists,
Doctors-on-Liens Referral Logs, Insurance directories, Company Stats, etc.)
is visible from every patient chart.

The actual list/import/open/delete UI is reused from `doc_vault_page.FolderPanel`
to avoid duplicating that logic; this file only owns the folder layout and
the global root path.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox

from doc_vault_page import FolderPanel, open_with_default_app
from paths import global_vault_dir


# Folder names (subdirectories under <DATA_DIR>/global_vault/).
# Insurance is included up-front so the button is wired even though the
# Insurance directory feature itself comes later.
GLOBAL_VAULT_FOLDERS = [
    "attorneys",
    "doctors_on_liens",
    "insurance",
    "company_stats",
]

GLOBAL_FOLDER_LABELS = {
    "attorneys": "attorneys",
    "doctors_on_liens": "doctors on liens",
    "insurance": "insurance",
    "company_stats": "company stats",
}


def ensure_global_vault_dirs() -> str:
    """Create the global vault root and all known subfolders if missing.
    Returns the absolute path to the global vault root.
    """
    root = str(global_vault_dir())
    os.makedirs(root, exist_ok=True)
    for k in GLOBAL_VAULT_FOLDERS:
        os.makedirs(os.path.join(root, k), exist_ok=True)
    return root


def global_vault_folder_path(folder_key: str) -> str:
    """Absolute path to a global-vault subfolder (created if missing)."""
    root = ensure_global_vault_dirs()
    path = os.path.join(root, folder_key)
    os.makedirs(path, exist_ok=True)
    return path


class GlobalVaultPage(ttk.Frame):
    """
    Clinic-wide doc vault page. Always available — does NOT require patient
    demographics, since these documents are shared across every chart.
    """

    def __init__(self, parent, on_change_callback=None):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self._build_ui()
        # Auto-select the first folder so the right-hand panel never shows the
        # per-patient placeholder text inherited from FolderPanel.
        if GLOBAL_VAULT_FOLDERS:
            self.after_idle(lambda: self.select_folder(GLOBAL_VAULT_FOLDERS[0]))

    # ---------- Path helpers ----------
    def _vault_root(self) -> str:
        return ensure_global_vault_dirs()

    def _folder_path(self, key: str) -> str:
        return global_vault_folder_path(key)

    def ensure_vault_dirs(self):
        ensure_global_vault_dirs()

    def refresh_current_folder(self):
        try:
            self.ensure_vault_dirs()
            if hasattr(self, "folder_panel") and self.folder_panel:
                self.folder_panel.refresh()
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        top = ttk.Frame(outer)
        top.pack(fill="x")

        ttk.Label(
            top,
            text="Global Vault (shared across all charts)",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        ttk.Button(
            top, text="Reveal Global Vault Root", command=self.reveal_vault_root,
        ).pack(side="right")

        ttk.Separator(outer).pack(fill="x", pady=10)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Folders", font=("Segoe UI", 11, "bold")).pack(
            anchor="nw", pady=(0, 8)
        )

        for k in GLOBAL_VAULT_FOLDERS:
            ttk.Button(
                left,
                text=GLOBAL_FOLDER_LABELS.get(k, k),
                width=18,
                command=lambda kk=k: self.select_folder(kk),
            ).pack(anchor="nw", pady=3)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(15, 0))

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(right, textvariable=self.status_var, foreground="gray").pack(
            anchor="w"
        )

        self.folder_panel = FolderPanel(
            right,
            get_folder_path_fn=self._folder_path,
            set_status_fn=self.set_status,
        )
        self.folder_panel.pack(fill="both", expand=True, pady=(8, 0))

        # Override the Doc-Vault tip (which mentions per-patient demographics).
        try:
            for child in self.folder_panel.winfo_children():
                if isinstance(child, ttk.Label):
                    txt = (child.cget("text") or "")
                    if "Enter Last/First/DOB/DOI" in txt:
                        child.configure(
                            text=(
                                "Tip: documents in the Global Vault are visible from every "
                                "patient chart. Use this for clinic-wide directories such as "
                                "Attorney Lists, Doctors-on-Liens Referral Logs, Insurance, etc."
                            )
                        )
        except Exception:
            pass

    def set_status(self, msg: str):
        self.status_var.set(msg)
        if self.on_change_callback:
            try:
                self.on_change_callback()
            except Exception:
                pass

    def select_folder(self, folder_key: str):
        self.ensure_vault_dirs()
        # Patch the placeholder copy on first selection so it doesn't say "enter
        # patient demographics" (the FolderPanel was authored for the per-patient
        # vault). The folder always exists for the global vault, so this only
        # matters before any folder is selected.
        self.folder_panel.set_folder(folder_key)
        self.set_status(f"Selected folder: {folder_key}")

    def reveal_vault_root(self):
        vr = self._vault_root()
        try:
            open_with_default_app(vr)
        except Exception as e:
            messagebox.showerror(
                "Global Vault", f"Could not open vault folder:\n\n{e}"
            )
