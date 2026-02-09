# doc_vault_page.py
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from send2trash import send2trash


# Vault folder names (inside patient root)
VAULT_FOLDERS = [
    "attorney",
    "billing",
    "imaging",
    "messages",
    "patient_info",
    "pdfs",
]

def open_with_default_app(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception as e:
        raise RuntimeError(str(e))

def unique_dest_path(dest_dir: str, filename: str) -> str:
    """
    If dest exists, append _HHMMSS (and if still exists, add increment).
    """
    base = os.path.basename(filename)
    name, ext = os.path.splitext(base)
    candidate = os.path.join(dest_dir, base)
    if not os.path.exists(candidate):
        return candidate

    stamp = datetime.now().strftime("%H%M%S")
    candidate = os.path.join(dest_dir, f"{name}_{stamp}{ext}")
    if not os.path.exists(candidate):
        return candidate

    i = 2
    while True:
        candidate = os.path.join(dest_dir, f"{name}_{stamp}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1

class FolderPanel(ttk.Frame):
    def __init__(self, parent, *, get_folder_path_fn, set_status_fn):
        super().__init__(parent)
        self.get_folder_path_fn = get_folder_path_fn
        self.set_status_fn = set_status_fn
        self.folder_key: str | None = None
        self._build()

    def _build(self):
        hdr = ttk.Frame(self)
        hdr.pack(fill="x")

        self.title_lbl = ttk.Label(hdr, text="Folder: (select one)", font=("Segoe UI", 11, "bold"))
        self.title_lbl.pack(side="left")

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(8, 8))

        ttk.Button(btns, text="Import Files", command=self.import_files).pack(side="left")
        ttk.Button(btns, text="Open Selected", command=self.open_selected).pack(side="left", padx=8)
        ttk.Button(btns, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=8)
        ttk.Button(btns, text="Reveal Folder", command=self.reveal_folder).pack(side="left", padx=8)
        ttk.Button(btns, text="Refresh List", command=self.refresh).pack(side="left", padx=8)


        self.listbox = tk.Listbox(self, height=18)
        self.listbox.pack(fill="both", expand=True)

        ttk.Label(
            self,
            text="Tip: Enter Last/First/DOB/DOI in the main app to activate this vault.",
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self._show_placeholder()

    def _show_placeholder(self, msg: str | None = None):
        self.listbox.delete(0, tk.END)
        self.listbox.insert(tk.END, msg or "(Enter patient demographics to enable the vault.)")

    def _current_dir(self) -> str | None:
        if not self.folder_key:
            return None
        try:
            return self.get_folder_path_fn(self.folder_key)
        except Exception:
            return None

    def set_folder(self, folder_key: str):
        self.folder_key = folder_key
        self.title_lbl.config(text=f"Folder: {folder_key}")
        if not self._current_dir():
            self._show_placeholder("(Enter patient demographics to enable the vault.)")
            return
        self.refresh()

    def refresh(self):
        self.listbox.delete(0, tk.END)
        d = self._current_dir()
        if not d or not os.path.isdir(d):
            self._show_placeholder("(Enter patient demographics to enable the vault.)")
            return

        try:
            files = sorted(os.listdir(d), key=lambda x: x.lower())
        except Exception:
            files = []

        any_file = False
        for f in files:
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                self.listbox.insert(tk.END, f)
                any_file = True

        if not any_file:
            self.listbox.insert(tk.END, "(No files in this folder yet.)")

    def import_files(self):
        d = self._current_dir()
        if not d:
            messagebox.showinfo("Import", "Enter patient demographics first.")
            return

        os.makedirs(d, exist_ok=True)

        paths = filedialog.askopenfilenames(
            title=f"Import files into: {self.folder_key}",
            filetypes=[("All files", "*.*")],
        )
        if not paths:
            return

        added = 0
        for src in paths:
            if not os.path.exists(src):
                continue
            dest = unique_dest_path(d, os.path.basename(src))
            try:
                shutil.copy2(src, dest)
                added += 1
            except Exception as e:
                messagebox.showwarning("Import", f"Could not import:\n{src}\n\n{e}")

        self.refresh()
        self.set_status_fn(f"Imported {added} file(s) into {self.folder_key}.")

    def open_selected(self):
        d = self._current_dir()
        if not d:
            messagebox.showinfo("Open", "Enter patient demographics first.")
            return

        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Open", "Select a file from the list.")
            return

        fname = self.listbox.get(sel[0])
        if fname.startswith("("):
            return

        path = os.path.join(d, fname)
        if not os.path.exists(path):
            messagebox.showerror("Open", "File not found on disk.")
            return
        try:
            open_with_default_app(path)
        except Exception as e:
            messagebox.showerror("Open", f"Could not open file:\n\n{e}")

    def delete_selected(self):
        d = self._current_dir()
        if not d:
            messagebox.showinfo("Delete", "Enter patient demographics first.")
            return

        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("Delete", "Select a file from the list.")
            return

        fname = self.listbox.get(sel[0])
        if fname.startswith("("):
            return

        path = os.path.join(d, fname)
        if not os.path.exists(path):
            messagebox.showerror("Delete", "File not found on disk.")
            self.refresh()
            return

        if not messagebox.askyesno("Delete File", f"Delete this file?\n\n{fname}\n\nThis cannot be undone."):
            return

        try:
            send2trash(path)  #os.remove(path)  # permanent delete
            self.refresh()
            self.set_status_fn(f"Deleted: {fname}")
        except Exception as e:
            messagebox.showerror("Delete Failed", f"Could not delete:\n{fname}\n\n{e}")


    def reveal_folder(self):
        d = self._current_dir()
        if not d:
            messagebox.showinfo("Folder", "Enter patient demographics first.")
            return
        os.makedirs(d, exist_ok=True)
        try:
            open_with_default_app(d)
        except Exception as e:
            messagebox.showerror("Folder", f"Could not open folder:\n\n{e}")

class DocVaultPage(ttk.Frame):
    """
    Patient-linked doc vault page (no duplicate demographics).
    Uses chiro_app patient_root as the "case folder".
    """
    def __init__(self, parent, on_change_callback, get_patient_root_fn):
        super().__init__(parent)
        self.on_change_callback = on_change_callback
        self.get_patient_root_fn = get_patient_root_fn  # returns patient_root or None

        self._build_ui()

    def _vault_root(self) -> str | None:
        pr = self.get_patient_root_fn()
        if not pr:
            return None
        return os.path.join(pr, "vault")

    def _folder_path(self, key: str) -> str | None:
        vr = self._vault_root()
        if not vr:
            return None
        return os.path.join(vr, key)

    def ensure_vault_dirs(self):
        vr = self._vault_root()
        if not vr:
            return
        os.makedirs(vr, exist_ok=True)
        for k in VAULT_FOLDERS:
            os.makedirs(os.path.join(vr, k), exist_ok=True)

    def _build_ui(self):
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        top = ttk.Frame(outer)
        top.pack(fill="x")

        ttk.Label(top, text="Document Vault", font=("Segoe UI", 12, "bold")).pack(side="left")

        ttk.Button(top, text="Reveal Patient Vault Root", command=self.reveal_vault_root).pack(side="right")

        ttk.Separator(outer).pack(fill="x", pady=10)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Folders", font=("Segoe UI", 11, "bold")).pack(anchor="nw", pady=(0, 8))

        for k in VAULT_FOLDERS:
            ttk.Button(left, text=k, width=18, command=lambda kk=k: self.select_folder(kk)).pack(anchor="nw", pady=3)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(15, 0))

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(right, textvariable=self.status_var, foreground="gray").pack(anchor="w")

        self.folder_panel = FolderPanel(
            right,
            get_folder_path_fn=self._folder_path,
            set_status_fn=self.set_status,
        )
        self.folder_panel.pack(fill="both", expand=True, pady=(8, 0))

    def set_status(self, msg: str):
        self.status_var.set(msg)

    def select_folder(self, folder_key: str):
        pr = self.get_patient_root_fn()
        if not pr:
            messagebox.showinfo("Vault", "Enter Last, First, DOB, and DOI first.")
            return
        self.ensure_vault_dirs()
        self.folder_panel.set_folder(folder_key)
        self.set_status(f"Selected folder: {folder_key}")

    def reveal_vault_root(self):
        vr = self._vault_root()
        if not vr:
            messagebox.showinfo("Vault", "Enter Last, First, DOB, and DOI first.")
            return
        self.ensure_vault_dirs()
        try:
            open_with_default_app(vr)
        except Exception as e:
            messagebox.showerror("Vault", f"Could not open vault folder:\n\n{e}")
