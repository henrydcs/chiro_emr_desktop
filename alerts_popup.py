# alerts_popup.py
from __future__ import annotations
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox


#"alerts": {"red_flags": ["Progressive neuro deficits", "Night pain not relieved by rest"],"rapport": ["Likes fishing", "Has 2 kids", "Works night shift"], "conversation_prompts": ["Ask about the new puppy", "Follow up on hiking trip"]}



def _clean(s: str) -> str:
    return (s or "").strip()


DEFAULT_ALERTS = {
    "red_flags": [],
    "rapport": [],
    "conversation_prompts": [],
}


class AlertsPopup(tk.Toplevel):
    """
    Startup / patient alert popup that persists to JSON.

    - Left: Red flags
    - Right: Rapport / hobbies / conversation notes
    - Bottom: Conversation prompts / follow-ups
    """

    def __init__(self, master: tk.Tk, json_path: str, title: str = "Alerts / Conversation Notes"):
        super().__init__(master)
        self.master = master
        self.json_path = json_path

        self.title(title)
        self.geometry("900x520")
        self.minsize(760, 420)

        # Make it feel like a modal dialog
        self.transient(master)
        self.grab_set()

        # Data
        self.data = self._load_json()

        # Build UI
        self._build_ui()
        self._load_into_widgets()

        # Nice close behavior
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------- JSON -----------------
    def _load_json(self) -> dict:
        if not os.path.exists(self.json_path):
            return {"alerts": DEFAULT_ALERTS.copy()}

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                obj = json.load(f) or {}
        except Exception:
            # If JSON is corrupted, don't crash the EMR
            obj = {}

        if "alerts" not in obj or not isinstance(obj["alerts"], dict):
            obj["alerts"] = DEFAULT_ALERTS.copy()

        # Ensure keys exist
        for k, v in DEFAULT_ALERTS.items():
            if k not in obj["alerts"] or not isinstance(obj["alerts"][k], list):
                obj["alerts"][k] = []

        return obj

    def _save_json(self) -> None:
        self._flush_widgets_to_data()

        # Ensure folder exists
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)

        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save alerts JSON:\n{e}")

    # ----------------- UI -----------------
    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # LEFT: Red flags
        lf = ttk.LabelFrame(root, text="Red flags / watch-outs")
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)

        self.red_text = tk.Text(lf, wrap="word", height=10)
        self.red_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # RIGHT: Rapport / hobbies
        rf = ttk.LabelFrame(root, text="Rapport notes (hobbies, family, work, preferences)")
        rf.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        rf.rowconfigure(0, weight=1)
        rf.columnconfigure(0, weight=1)

        self.rapport_text = tk.Text(rf, wrap="word", height=10)
        self.rapport_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # BOTTOM: Conversation prompts
        bf = ttk.LabelFrame(root, text="Conversation prompts / follow-ups")
        bf.grid(row=1, column=0, columnspan=2, sticky="nsew")
        bf.rowconfigure(0, weight=1)
        bf.columnconfigure(0, weight=1)

        self.prompts_text = tk.Text(bf, wrap="word", height=6)
        self.prompts_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # Buttons
        btns = ttk.Frame(root)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))

        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Close", command=self.on_close).pack(side="right")

        # Optional: autosave when focus leaves the window
        self.bind("<FocusOut>", lambda e: self._save_json())

    def _load_into_widgets(self) -> None:
        alerts = self.data.get("alerts", DEFAULT_ALERTS)

        self.red_text.delete("1.0", "end")
        self.red_text.insert("1.0", "\n".join(alerts.get("red_flags", [])))

        self.rapport_text.delete("1.0", "end")
        self.rapport_text.insert("1.0", "\n".join(alerts.get("rapport", [])))

        self.prompts_text.delete("1.0", "end")
        self.prompts_text.insert("1.0", "\n".join(alerts.get("conversation_prompts", [])))

    def _flush_widgets_to_data(self) -> None:
        def lines_from_text(t: tk.Text) -> list[str]:
            raw = t.get("1.0", "end").splitlines()
            out = []
            for line in raw:
                s = _clean(line)
                if s:
                    out.append(s)
            return out

        self.data["alerts"]["red_flags"] = lines_from_text(self.red_text)
        self.data["alerts"]["rapport"] = lines_from_text(self.rapport_text)
        self.data["alerts"]["conversation_prompts"] = lines_from_text(self.prompts_text)

    # ----------------- actions -----------------
    def on_save(self) -> None:
        self._save_json()
        messagebox.showinfo("Saved", "Alerts saved.")

    def on_close(self) -> None:
        # Save on close (you can change this to “ask to save” if you want)
        self._save_json()
        self.grab_release()
        self.destroy()
