# A significant, separately identifiable E/M service was performed in addition to CMT, including a focused history, examination, and medical decision-making.

#Git Hub to Work Between Computers

#Start of Day
#git pull

#End of Day Push
# cd chiro_emr_desktop
# git status
# git add .
# git commit -m "End of day updates"
# git push

# git log --oneline --decorate -5  


# python chiro_app.py or

# cd chiro_emr_desktop

# git status
# git add -A
# git commit
# git push

#And remember to make sure to be in the REPO FOLDER (OFFICE COMPUTER or HOME COMPUTER):
#...\EMRchiropractic\chiro_emr_desktop OR EMR_Code\chiro_emr_desktop
#If not in ROOT folder, make sure to "cd chiro_emr_desktop" without the quotes
#testing git push / pull
# chiro_app.py
import json
import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
from diagnosis_page import DiagnosisPage
from doc_vault_page import DocVaultPage
import re
from HOI import HOIPage
from plan_page import PlanPage
from pathlib import Path
import tkinter.font as tkfont
from alerts_popup import AlertsPopup
from config import PATIENTS_ID_ROOT
from doc_vault_page import upsert_vault_file
from patient_storage import new_patient_id, get_patient_root, find_patient_root
from tk_docs_page import TkDocsPage
from pdf_export import REPORTLAB_OK, build_combined_pdf
from pdf_export import diagnosis_struct_to_live_preview_runs
from master_save import MasterSaveController
from config import (
    UI_PAGES,
    EXAM_COLORS,
    REGION_LABELS,
    SETTINGS_PATH,
    AUTOSAVE_DEBOUNCE_MS,
    LOGO_PATH, PROVIDER_NAME, CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX,
    YEAR_CASES_ROOT, NEXT_YEAR_CASES_ROOT, BASE_DIR,
    PATIENT_SUBDIR_EXAMS, PATIENT_SUBDIR_PDFS, EXAM_INDEX_SUBDIR,
)
from paths import get_data_dir

from utils import (
    ensure_year_root,
    safe_slug,
    normalize_mmddyyyy, today_mmddyyyy,
    ensure_patient_dirs,
    to_last_first,
)

# Pages
from subjectives import SubjectivesPage
from objectives import ObjectivesPage
from ui_pages import TextPage

# ----------- OPTIONAL: Pillow (Tkinter logo) -----------
PIL_OK = False
try:
    from PIL import Image, ImageTk  # type: ignore
    PIL_OK = True
except Exception:
    PIL_OK = False

EXAM_INDEX_FILENAME = "_exam_index.json"

# No base exams; only dynamic exams (Initial 1, Re-Exam 1, etc.)
EMPTY_EXAMS: list[str] = []

# Template category configuration: filesystem-safe slugs + human-readable labels
TEMPLATE_CATEGORIES = [
    ("initials", "Initials"),
    ("re_exams", "Re-Exams"),
    ("review_of_findings", "Review of Findings"),
    ("chiro_visits", "Chiro Visits"),
    ("therapy_only", "Therapy Only"),
    ("finals", "Finals"),
]


def get_templates_root() -> Path:
    """
    Return the external templates root directory under the EMR data directory,
    ensuring it and all category subfolders exist.

    Example: C:\\EMR_Data\\HOME\\templates\\initials, etc.
    """
    data_dir = get_data_dir()
    root = data_dir / "templates"
    root.mkdir(parents=True, exist_ok=True)

    for slug, _display in TEMPLATE_CATEGORIES:
        (root / slug).mkdir(parents=True, exist_ok=True)

    return root


def _find_sets(obj, path="root"):
    if isinstance(obj, set):
        print("FOUND set at:", path, "=>", obj)
        return True

    if isinstance(obj, dict):
        for k, v in obj.items():
            if _find_sets(v, f"{path}.{k}"):
                return True

    if isinstance(obj, list):
        for i, v in enumerate(obj):
            if _find_sets(v, f"{path}[{i}]"):
                return True

    return False

# Patient ID and folder paths: patient_storage.new_patient_id, get_patient_root, find_patient_root

def save_patient(content: dict):
    """Reserved for future use; app currently uses exam JSON as source of truth."""
    p = content.get("patient") or {}
    pid = (p.get("patient_id") or "").strip()
    if not pid:
        raise ValueError("Missing patient_id; cannot save.")
    folder = get_patient_root(pid, p.get("last_name", ""), p.get("first_name", ""))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "patient.json").write_text(json.dumps(content, indent=2), encoding="utf-8")


def load_patient(patient_id: str) -> dict:
    """Reserved for future use; folder resolved by id (pid or last_first__pid)."""
    folder = find_patient_root(patient_id)
    if not folder:
        raise FileNotFoundError(f"No patient folder found for id: {patient_id}")
    return json.loads((folder / "patient.json").read_text(encoding="utf-8"))


ALERTS_FILENAME = "alerts_dashboard.json"

def _ensure_json_file(path: str, default_obj=None):
    default_obj = {} if default_obj is None else default_obj
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_obj, f, indent=2)
    except Exception:
        pass

def open_with_default_app(path: str):
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Open PDF", f"Could not open the PDF:\n\n{e}")


def launch_new_form():
    """Launch a totally separate process running a fresh blank form."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--new"])


def _next_number(existing: list[str], prefix: str) -> int:
    """
    Return the smallest positive integer N such that
    '<prefix> N' is not already used in existing.
    Example: existing ['Re-Exam 1', 'Re-Exam 3'] -> returns 2.
    """
    pat = re.compile(
        rf"^\s*{re.escape(prefix)}\s+(\d+)\s*$",
        re.IGNORECASE
    )
    used = set()
    for name in existing:
        m = pat.match((name or "").strip())
        if m:
            try:
                used.add(int(m.group(1)))
            except Exception:
                pass

    # Find the smallest missing positive integer
    n = 1
    while n in used:
        n += 1
    return n


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_year_root()    

        style = ttk.Style()

        style.configure(
            "ActiveExam.TButton",
            font=("Segoe UI", 10, "bold")
        )

        self._alerts_popup_open = False

        self._alerts_popup_path = None
        self._alerts_popup_win = None

        self._live_preview_job = None  

        self._refreshing_preview = False


        self._start_blank = "--new" in sys.argv

        self.title("PI Exams – SOAP Builder")

        # Choose window size based on screen size so it works well
        # both on your large monitor and on a laptop.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        if screen_w >= 1600:
            # Large monitor (e.g., home)
            win_w, win_h = 1060, 930
            self._left_root_width = 960
        else:
            # Laptop / smaller screen
            # Leave a margin so the window doesn't hit screen edges
            margin = 80
            # Width: between 900 and 1060, but not wider than screen - margin
            win_w = max(900, min(1060, screen_w - margin))
            # Height: at most 930, but no more than 90% of screen height
            win_h = min(930, int(screen_h * 0.9))

            # Left column gets ~60% of total width
            self._left_root_width = int(win_w * 0.8)

        self.geometry(f"{win_w}x{win_h}")

        self.header_visible = tk.BooleanVar(value=True)
        self.demo_visible = tk.BooleanVar(value=True)
        self.demo_summary_var = tk.StringVar(value="")

        # Patient vars (shared across all exams)
        self.last_name_var = tk.StringVar(value="")
        self.first_name_var = tk.StringVar(value="")
        self.dob_var = tk.StringVar(value="")
        self.doi_var = tk.StringVar(value="")

        self.exam_date_var = tk.StringVar(value=today_mmddyyyy())
        self.claim_var = tk.StringVar(value="")       

        self.provider_var = tk.StringVar(value=PROVIDER_NAME)

        self.current_exam = tk.StringVar(value="")
        self.current_page = tk.StringVar(value="HOI History")

        self.exams: list[str] = list(EMPTY_EXAMS)  # dynamic exam list (Initial 1, Re-Exam 1, ROF 1, etc.)

        self._autosave_after_id = None
        self.current_case_path: str | None = None
        self._loading = False

        self.last_exam_pdf_paths: dict[str, str] = {}
        self.last_all_exams_pdf_path = ""

        self._mousewheel_target = None
        self._tk_logo_image = None     

        self.current_patient_id = None

        self.current_doc_label_var = tk.StringVar(value="")

        # Live Preview heading registry: maps logical section names
        # (e.g., "Subjectives") to Text indices like "12.0"
        self._preview_heading_indices: dict[str, str] = {}

        self.exam_date_var.trace_add("write", lambda *_: self._set_current_doc_label())
        
        self.master_save = MasterSaveController(self)
        self._build_ui()       
        self._wire_autosave_triggers()

        self._apply_demographics_visibility()

        
        
        # Mousewheel scroll routing (Subjectives canvas)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel_linux_up)
        self.bind_all("<Button-5>", self._on_mousewheel_linux_down)

        # Start behavior
        if not self._start_blank:
            self.after(80, self.autoload_last_case_on_startup)
        else:
            self.status_var.set("Ready. (New blank form)")
    
    def propagate_demographics_to_all_exams(self):
        patient_root = self.get_current_patient_root()
        if not patient_root:
            return

        exams_dir = os.path.join(patient_root, PATIENT_SUBDIR_EXAMS)
        if not os.path.isdir(exams_dir):
            return

        shared = {
            "patient_id": self.current_patient_id,
            "last_name": (self.last_name_var.get() or "").strip(),
            "first_name": (self.first_name_var.get() or "").strip(),
            "dob": (self.dob_var.get() or "").strip(),
            "doi": (self.doi_var.get() or "").strip(),
            "claim": (self.claim_var.get() or "").strip(),
            "provider": (self.provider_var.get() or "").strip(),
            "display_name": to_last_first(self.last_name_var.get(), self.first_name_var.get()),
        }

        for fn in os.listdir(exams_dir):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(exams_dir, fn)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f) or {}
            except Exception:
                continue

            payload.setdefault("patient", {})
            p = payload["patient"] if isinstance(payload["patient"], dict) else {}
            payload["patient"] = p

            # keep each exam's own visit date
            exam_date = (p.get("exam_date") or "").strip()

            p.update(shared)

            if exam_date:
                p["exam_date"] = exam_date

            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, path)
  

    def _date_for_exam_button(self, exam_name: str) -> str:
        """
        Return the exam's saved exam_date (from its JSON) if it exists,
        otherwise fall back to the current demographics exam_date.
        """
        # Fallback first
        fallback = (self.exam_date_var.get() or "").strip()

        path = self.compute_exam_path(exam_name)
        if not path or not os.path.exists(path):
            return fallback

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
            patient = payload.get("patient", {}) or {}
            d = (patient.get("exam_date") or "").strip()
            return normalize_mmddyyyy(d) or fallback
        except Exception:
            return fallback

            
    def _set_current_doc_label(self, date_str: str | None = None, exam_name: str | None = None):
        if not date_str:
            date_str = (self.exam_date_var.get() or "").strip()
        if not exam_name:
            exam_name = (self.current_exam.get() or "").strip()
        self.current_doc_label_var.set(f"{date_str}   {exam_name}")

    
    def _open_alerts_popup(self):
        self.show_current_patient_alerts_popup()

    
    def _alerts_path_for_current_patient(self) -> str:
        """
        Always patient-specific. If no patient yet, create a new patient_id and folder.
        """
        self._ensure_current_patient_id()
        patient_root = self.get_current_patient_root()
        if not patient_root:
            patient_root = str(get_patient_root(self.current_patient_id, "", ""))
        return os.path.join(patient_root, ALERTS_FILENAME)


    def show_current_patient_alerts_popup(self):
        """
        Open alerts popup using the current patient's alerts file.
        """
        path = self._alerts_path_for_current_patient()
        _ensure_json_file(path, default_obj={})
        self.show_alerts_popup(path)

    
    def _ensure_patient_id_in_payload(self, payload: dict) -> str:
        payload.setdefault("patient", {})
        payload["patient"]["patient_id"] = self._ensure_current_patient_id()
        return self.current_patient_id


    def show_alerts_popup(self, path: str):
        # If popup is already open but for a DIFFERENT patient/path, close it
        if getattr(self, "_alerts_popup_open", False):
            if getattr(self, "_alerts_popup_path", None) != path:
                try:
                    if self._alerts_popup_win and self._alerts_popup_win.winfo_exists():
                        self._alerts_popup_win.destroy()
                except Exception:
                    pass
                self._alerts_popup_open = False
            else:
                # Already open for this patient -> bring to front (no double-click feeling)
                try:
                    if self._alerts_popup_win and self._alerts_popup_win.winfo_exists():
                        self._alerts_popup_win.deiconify()
                        self._alerts_popup_win.lift()
                        self._alerts_popup_win.focus_force()
                except Exception:
                    pass
                return

        self._alerts_popup_open = True
        self._alerts_popup_path = path

        last = (self.last_name_var.get() or "").strip()
        first = (self.first_name_var.get() or "").strip()
        dob = (self.dob_var.get() or "").strip()

        name = ", ".join([x for x in [last, first] if x]) or "(No patient loaded)"
        patient_label = f"{name} | DOB: {dob or 'blank'}"

        pop = AlertsPopup(self, json_path=path, patient_label=patient_label)


        self._alerts_popup_win = pop

        def _on_close(_e=None):

            try:
                if self._alerts_popup_win and self._alerts_popup_win.winfo_exists():
                    self._alerts_popup_win.destroy()
            except Exception:
                pass
            self._alerts_popup_open = False
            self._alerts_popup_path = None
            self._alerts_popup_win = None

        pop.bind("<Destroy>", _on_close)             


    def _build_preview_heading_map(self) -> dict[str, str]:
        """
        Map the literal heading text in the Live Preview to the logical
        left-nav section name. Keys are the EXACT text used in the preview
        (upper-case), values are the page names used by show_page().
        """
        return {
            # HOI (beginning of Live Preview) — title depends on mode
            # Initial exam:
            "History of Present Illness": "HOI History",
            # Re-exam:
            "Status Update": "HOI History",
            # Final:
            "Final Visit Summary": "HOI History",
            # Subjectives / Family / Objectives / Assessment / Plan
            #"Mechanism of Injury (MOI)": "Type of Injury",
            "SUBJECTIVES": "Subjectives",
            "FAMILY / SOCIAL HISTORY": "Family/Social History",
            "OBJECTIVES": "Objectives",
            "ASSESSMENT": "Diagnosis",
            "PLAN OF CARE": "Plan",
        }
       
    def request_live_preview_refresh(self):
        # Debounce: cancel pending refresh and schedule a new one
        if getattr(self, "_live_preview_job", None) is not None:
            try:
                self.after_cancel(self._live_preview_job)
            except Exception:
                pass
            self._live_preview_job = None

        self._live_preview_job = self.after(80, self.refresh_live_preview)  # 60–120ms feels good

    
    def refresh_live_preview(self):
        if getattr(self, "_refreshing_preview", False):
            return
        self._refreshing_preview = True
        try:
            if not hasattr(self, "hoi_page"):
                return

            txt = getattr(self, "hoi_preview_text", None)
            if txt is None or not txt.winfo_exists():
                return
            
            # Build runs in PDF order: Beginning (Initial/Re-Exam/Final) → Subjectives → Objectives → ROF → Assessment
            runs = []
            try:
                # 1. Beginning: Initial / Re-Exam / Final (HPI, Status Update, Final Visit Summary)
                if hasattr(self.hoi_page, "get_live_preview_runs_beginning"):
                    beginning_runs = self.hoi_page.get_live_preview_runs_beginning() or []
                    if beginning_runs:
                        runs.extend(beginning_runs)
                elif hasattr(self.hoi_page, "get_live_preview_runs"):
                    # Fallback: if new methods don't exist, use old behavior for beginning only when not ROF
                    all_rof = self.hoi_page.get_live_preview_runs() or []
                    mode = (getattr(self.hoi_page, "rof_mode_var", None) or type("", (), {"get": lambda: "ROF"})()).get()
                    if all_rof and (mode or "").strip() not in ("ROF", ""):
                        runs.extend(all_rof)

                # 2. HOI History (MOI) — after History of Present Illness, before Subjectives
                if hasattr(self.hoi_page, "get_live_preview_runs_moi"):
                    moi_runs = self.hoi_page.get_live_preview_runs_moi() or []
                    if moi_runs:
                        if runs:
                            runs.append(("\n\n", None))
                        runs.extend(moi_runs)

                # 3. Subjectives
                if hasattr(self, "subjectives_page") and self.subjectives_page is not None:
                    subj_runs = self.subjectives_page.get_live_preview_runs()
                    if subj_runs:
                        if runs:
                            runs.append(("\n\n", None))
                        runs.extend(subj_runs)

                # 3a. Functional Status / ADLs (mirrors PDF: after Subjectives, before Objectives)
                if hasattr(self, "objectives_page") and self.objectives_page is not None:
                    try:
                        from pdf_export import adl_dict_to_plain_text
                        obj_struct = self.objectives_page.to_dict() or {}
                        gs = obj_struct.get("global") or {}
                        adl = gs.get("adl") or {}
                        adl_text = adl_dict_to_plain_text(adl)
                        if adl_text.strip():
                            if runs:
                                runs.append(("\n\n", None))
                            runs.append(("Functional Status\n", "H_BOLD"))
                            runs.append(("\n", None))
                            runs.append((adl_text.strip() + "\n\n", None))
                    except Exception:
                        pass

                # 3b. Family / Social History (mirrors PDF: after Functional Status, before Objectives)
                if hasattr(self, "family_social_page") and self.family_social_page is not None:
                    try:
                        fs_text = (self.family_social_page.get_value() or "").strip()
                        if fs_text:
                            if runs:
                                runs.append(("\n\n", None))
                            runs.append(("FAMILY / SOCIAL HISTORY\n", "H_BOLD"))
                            runs.append(("\n", None))
                            runs.append((fs_text + "\n\n", None))
                    except Exception:
                        pass                              

                # 4. Objectives (mirrors PDF: OBJECTIVES section — between Subjectives and ROF)
                if hasattr(self, "objectives_page") and self.objectives_page is not None:
                    try:
                        from pdf_export import objectives_struct_to_live_preview_runs
                        obj_struct = self.objectives_page.to_dict() or {}
                        obj_runs = objectives_struct_to_live_preview_runs(obj_struct)
                        if obj_runs:
                            if runs:
                                runs.append(("\n\n", None))
                            runs.append(("OBJECTIVES\n", "H_BOLD"))
                            runs.append(("\n", None))
                            runs.extend(obj_runs)
                    except Exception:
                        pass

                # 5. Review of Findings (ROF only — after Objectives, before Assessment)
                if hasattr(self.hoi_page, "get_live_preview_runs_rof"):
                    rof_runs = self.hoi_page.get_live_preview_runs_rof() or []
                    if rof_runs:
                        if runs:
                            runs.append(("\n\n", None))
                        runs.extend(rof_runs)

                # 6. Assessment (mirrors PDF: ASSESSMENT section)
                if hasattr(self, "diagnosis_page") and self.diagnosis_page is not None:
                    try:
                        dx_struct = self.diagnosis_page.to_dict()
                        assessment_runs = diagnosis_struct_to_live_preview_runs(dx_struct)
                        if assessment_runs:
                            if runs:
                                runs.append(("\n\n", None))
                            runs.append(("ASSESSMENT\n", "H_BOLD"))
                            runs.append(("\n", None))
                            runs.extend(assessment_runs)
                    except Exception:
                        pass

                # 7. Plan of Care (mirrors PDF: PLAN OF CARE section)
                if hasattr(self, "plan_page") and self.plan_page is not None:
                    try:
                        from plan_pdf import plan_struct_to_live_preview_runs
                        plan_struct = self.plan_page.get_struct()
                        work_recs = ""
                        if hasattr(self, "diagnosis_page") and self.diagnosis_page is not None:
                            dx_struct = self.diagnosis_page.to_dict() or {}
                            wp = (dx_struct.get("work_plan") or "").strip()
                            if wp and wp != "(select)":
                                work_mapping = {
                                    "Full Duty (No Restrictions)":
                                        "Return to work full duty with no restrictions.",
                                    "Modified Duty (Work Restrictions)":
                                        "Recommend modified duty with appropriate work restrictions.",
                                    "Off Work / TTD (Temporary Total Disability)":
                                        "Recommend the patient remain off work at this time (TTD) pending clinical improvement and re-evaluation.",
                                    "Off Work (Work Status Note Only)":
                                        "Work status note provided; patient advised to remain off work at this time as clinically indicated.",
                                    "Work Restrictions Pending Re-evaluation":
                                        "Work restrictions are pending re-evaluation at the next visit based on treatment response.",
                                    "Disability Note Requested":
                                        "Disability documentation requested; provide as clinically appropriate based on examination findings.",
                                    "Return to Work Note Requested":
                                        "Return-to-work documentation requested; provide based on current work status and clinical findings.",
                                    "FMLA / Leave Documentation Requested":
                                        "FMLA/leave documentation requested; provide as clinically appropriate.",
                                    "Referral for Work Capacity Evaluation":
                                        "Recommend referral for a work capacity evaluation to better define functional limitations and work restrictions.",
                                }
                                work_recs = work_mapping.get(wp, wp)
                        plan_runs = plan_struct_to_live_preview_runs(plan_struct, work_recs=work_recs)
                        if plan_runs:
                            if runs:
                                runs.append(("\n\n", None))
                            runs.append(("PLAN OF CARE\n", "H_BOLD"))
                            runs.append(("\n", None))
                            runs.extend(plan_runs)
                    except Exception:
                        pass

            except Exception as e:
                print("refresh_live_preview error:", e)
                runs = []

            # ✅ If content didn’t change, do NOTHING (prevents jitter)
            new_key = tuple((chunk or "", tag or "") for chunk, tag in runs)
            if getattr(self, "_last_preview_key", None) == new_key:
                return
            self._last_preview_key = new_key

            # Preserve current view
            try:
                y0 = txt.yview()[0]
            except Exception:
                y0 = 0.0

            try:
                txt.configure(state="normal")
                txt.delete("1.0", "end")

                for chunk, tag in runs:
                    if not chunk:
                        continue
                    if tag:
                        txt.insert("end", chunk, tag)
                    else:
                        txt.insert("end", chunk)

                # Add top/bottom spacer strips (light blue) to allow centering
                # of first/last headings with visible empty space.
                self._augment_preview_with_spacers(txt)

                # Tag heading lines and build the index registry for centering.
                self._retag_preview_headings(txt)

                # Restore the previous view position unless the caller
                # explicitly centers later (on click / section change).
                txt.yview_moveto(y0)

            finally:
                try:
                    txt.configure(state="disabled")
                except Exception:
                    pass

        finally:
            self._refreshing_preview = False


    def _augment_preview_with_spacers(self, txt: "tk.Text") -> None:
        """
        Ensure there is some light-blue "empty" space at the top and bottom
        of the Live Preview so that the first / last headings can be scrolled
        toward the vertical center.

        Implementation: we insert a few blank lines at top and bottom, tagged
        with a special SPACER_BG tag that uses a light-blue background.
        """
        # Configure the spacer tag once
        txt.tag_configure("SPACER_BG", background="#e0f0ff")

        # Insert top spacer only if not already present
        first_line = txt.get("1.0", "2.0")
        if "SPACER_MARKER_TOP" not in first_line:
            txt.insert("1.0", "SPACER_MARKER_TOP\n", ("SPACER_BG",))
            for _ in range(6):
                txt.insert("2.0", "\n", ("SPACER_BG",))

        # Insert bottom spacer only if not already present
        # (Look at the last couple of lines for the marker.)
        last_start = txt.index("end-2l")
        last_text = txt.get(last_start, "end-1c")
        if "SPACER_MARKER_BOTTOM" not in last_text:
            txt.insert("end-1c", "\nSPACER_MARKER_BOTTOM", ("SPACER_BG",))
            for _ in range(6):
                txt.insert("end-1c", "\n", ("SPACER_BG",))

    def _retag_preview_headings(self, txt: "tk.Text") -> None:
        """
        Find main SOAP headings in the Live Preview and:
        - Create a HEAD_* tag that covers the entire heading line.
        - Record the first index for each section into self._preview_heading_indices
          so we can center on them later.

        When multiple heading texts map to the same section (e.g. "History of
        Present Illness", "Status Update", "Final Visit Summary" -> HOI History),
        we must only delete that tag once, then add it to every matching line.
        """
        self._preview_heading_indices.clear()

        heading_map = self._build_preview_heading_map()
        seen_tag_names: set[str] = set()

        for heading_text, section_name in heading_map.items():
            tag_name = f"HEAD_{section_name.upper().replace(' ', '_').replace('/', '_')}"

            # Delete and configure each tag only once. Otherwise, when several
            # headings map to the same section (e.g. HOI), we'd remove the tag
            # from earlier lines when we process the next heading.
            if tag_name not in seen_tag_names:
                seen_tag_names.add(tag_name)
                txt.tag_delete(tag_name)
                txt.tag_configure(tag_name)

            search_start = "1.0"
            pattern = heading_text + "\n"

            while True:
                idx = txt.search(pattern, search_start, stopindex="end")
                if not idx:
                    break
                line_start = idx
                line_end = f"{idx} lineend"
                txt.tag_add(tag_name, line_start, line_end)

                # Record the FIRST occurrence for this section
                if section_name not in self._preview_heading_indices:
                    self._preview_heading_indices[section_name] = line_start

                search_start = line_end

    def _center_preview_on_heading_index(self, index: str) -> None:
        """
        Scroll the Live Preview so the line at `index` is placed at (or near)
        the top of the Text widget's visible area.
        """
        txt = getattr(self, "hoi_preview_text", None)
        if txt is None or not txt.winfo_exists():
            return

        txt.update_idletasks()

        try:
            target_line = int(str(txt.index(index)).split('.')[0])
            total_lines = int(str(txt.index("end-1c")).split('.')[0])
        except (ValueError, AttributeError):
            return

        if total_lines <= 1:
            return

        heading_frac = (target_line - 1) / total_lines
        top_frac = max(0.0, min(heading_frac, 1.0))
        txt.yview_moveto(top_frac)
    
    # If we did not converge, leave view as close as we got
    
    def _center_preview_on_section(self, section_name: str) -> None:
        """
        Center the Live Preview on the heading that corresponds to the
        given left-nav section name.  Searches the preview text directly
        each time (no cached-index dependency).
        """
        txt = getattr(self, "hoi_preview_text", None)
        if txt is None or not txt.winfo_exists():
            return

        heading_map = self._build_preview_heading_map()

        target_index = None
        for heading_text, mapped_section in heading_map.items():
            if mapped_section == section_name:
                idx = txt.search(heading_text, "1.0", stopindex="end")
                if idx:
                    target_index = f"{idx.split('.')[0]}.0"
                    break

        if not target_index:
            return

        self._center_preview_on_heading_index(target_index)

    def _on_preview_click(self, event) -> None:
        """
        When the user clicks inside the Live Preview, check whether the
        click landed on a main heading line or an important sub-heading.
        If so, center that heading and optionally switch/focus the left panel.
        """
        txt = getattr(self, "hoi_preview_text", None)
        if txt is None or not txt.winfo_exists():
            return

        # Convert click coordinates to a Text index
        index = txt.index(f"@{event.x},{event.y}")
        line_start = f"{index.split('.')[0]}.0"

        heading_map = self._build_preview_heading_map()

        # 1) Try tag-based match for top-level headings
        tags = txt.tag_names(line_start)
        for heading_text, section_name in heading_map.items():
            tag_name = f"HEAD_{section_name.upper().replace(' ', '_').replace('/', '_')}"
            if tag_name in tags:
                self._center_preview_on_heading_index(line_start)
                self.show_page(section_name)

                # Also let subheading logic run for more granular focus
                try:
                    line_end = txt.index(f"{line_start} lineend")
                    line_content = txt.get(line_start, line_end).strip()
                except Exception:
                    line_content = ""
                self._handle_preview_subheading_click(section_name, line_content)
                # Re-center after left-panel layout settles (same heading as nav click).
                self.after_idle(lambda sn=section_name: self._center_preview_on_section(sn))
                return

        # 2) Fallback: match by exact line text (in case tag wasn't applied)
        try:
            line_end = txt.index(f"{line_start} lineend")
            line_content = txt.get(line_start, line_end).strip()
        except Exception:
            return

        if line_content in heading_map:
            section_name = heading_map[line_content]
            self._center_preview_on_heading_index(line_start)
            self.show_page(section_name)
            self._handle_preview_subheading_click(section_name, line_content)
            self.after_idle(lambda sn=section_name: self._center_preview_on_section(sn))
            return

        
        # 3) If not a main heading, still see if this line is an important sub-heading
        #    ...

                # --- Assessment sub-headings (global) ---
        # Make these work regardless of which left-panel page is currently active.
        assess_line = (line_content or "").strip()
        if assess_line:
            # ASSESSMENT heading -> Assessment sub-section
            if assess_line.upper().startswith("ASSESSMENT"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_assessment_block"):
                    self.diagnosis_page.focus_assessment_block()
                return

            # Diagnosis -> Dx Block
            if assess_line.startswith("Diagnosis"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_diagnosis_block"):
                    self.diagnosis_page.focus_diagnosis_block()
                return

            # Causation
            if assess_line.startswith("Causation"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_causation_block"):
                    self.diagnosis_page.focus_causation_block()
                return

            # Prognosis
            if assess_line.startswith("Prognosis"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_prognosis_block"):
                    self.diagnosis_page.focus_prognosis_block()
                return

            # Imaging
            if assess_line.startswith("Imaging"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_imaging_block"):
                    self.diagnosis_page.focus_imaging_block()
                return

            # Referrals
            if assess_line.startswith("Referrals"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_referrals_block"):
                    self.diagnosis_page.focus_referrals_block()
                return

            # Current Work Status / Work Duties
            if "Current Work Status" in assess_line or "Work Duties" in assess_line:
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_work_status_block"):
                    self.diagnosis_page.focus_work_status_block()
                return

        # --- Plan of Care sub-headings (global) ---
        plan_line = (line_content or "").strip()
        if plan_line:
            # Care Type(s): -> Treatment block
            if plan_line.startswith("Care Type(s):"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_care_types_block"):
                    self.plan_page.focus_care_types_block()
                return

            # Regions: -> Regions Treated block
            if plan_line.startswith("Regions:"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_regions_treated_block"):
                    self.plan_page.focus_regions_treated_block()
                return

            # Frequency / Duration / Re-evaluation -> Schedule block
            if (
                plan_line.startswith("Frequency:")
                or plan_line.startswith("Duration:")
                or plan_line.startswith("Re-evaluation:")
            ):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_schedule_block"):
                    self.plan_page.focus_schedule_block()
                return

            # Goals: -> Goals block
            if plan_line.startswith("Goals:"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_goals_block"):
                    self.plan_page.focus_goals_block()
                return

            # Work Duties: -> Current Work Status block (Assessment page)
            if plan_line.startswith("Work Duties:"):
                self.show_page("Diagnosis")
                if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_work_status_block"):
                    self.diagnosis_page.focus_work_status_block()
                return

                        # Services Provided Today -> Services Provided Today block + popup
            if plan_line.startswith("Services Provided Today"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_services_block"):
                    self.plan_page.focus_services_block()
                return

            # Segment(s) Adjusted / Technique lines -> CMT details popup (segments & techniques)
            if (
                plan_line.strip().startswith("Segment(s) Adjusted")
                or "Technique(s):" in plan_line
            ):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_cmt_details_popup"):
                    self.plan_page.focus_cmt_details_popup()
                return

            # Chiropractic Manipulative Treatment / Adjustment Code -> main Services popup
            if (
                plan_line.startswith("Chiropractic Manipulative Treatment")
                or plan_line.strip().startswith("Adjustment Code:")
            ):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_cmt_popup"):
                    self.plan_page.focus_cmt_popup()
                return

            # Therapeutic Modalities heading -> main Services popup
            if plan_line.startswith("Therapeutic Modalities"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_services_block"):
                    self.plan_page.focus_services_block()
                    self.plan_page.open_services_main_popup()
                return

            # Modality Code lines -> open that specific therapy popup
            if plan_line.strip().startswith("Modality Code:"):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_therapy_popup"):
                    code = ""
                    try:
                        code = plan_line.split("Modality Code:")[1].split("—")[0].strip()
                    except Exception:
                        pass
                    self.plan_page.focus_therapy_popup(code)
                return

            # Therapy body-part / minutes lines (indented, contain " — " and "minutes")
            if "minutes" in plan_line.lower() and "—" in plan_line:
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_services_block"):
                    self.plan_page.focus_services_block()
                    self.plan_page.open_services_main_popup()
                return

            # Examination and Management / Exam Code / Exam Notes -> Exam popup
            if (
                plan_line.startswith("Examination and Management")
                or plan_line.strip().startswith("Exam Code:")
            ):
                self.show_page("Plan")
                if hasattr(self, "plan_page") and hasattr(self.plan_page, "focus_exam_popup"):
                    self.plan_page.focus_exam_popup()
                return

        # Fall back to the existing per-page subheading logic
        section_name = self.current_page.get() or ""

        # "Patient points to" sentence -> Subjectives, points view
        if "points to" in (line_content or "").lower():
            self.show_page("Subjectives")
            if hasattr(self, "subjectives_page") and hasattr(self.subjectives_page, "focus_points_to"):
                self.subjectives_page.focus_points_to(line_content)
            return
        
        # Subjectives body-region headings...
        try:
            from config import REGION_LABELS
        except Exception:
            REGION_LABELS = {}

        if line_content in REGION_LABELS.values():
            section_name = "Subjectives"
            self.show_page("Subjectives")
            self._handle_preview_subheading_click(section_name, line_content)
            return

        _obj_line = (line_content or "").strip()

        def _normalize_obj_tag(t: str) -> str:
            """Strip parentheses so '(C/S)' and 'C/S' both work."""
            if not t:
                return ""
            return (t.strip().strip("()") or "").strip()

        # Region-block headings: open Objectives and go straight to the block/section.
        # Match by containment so we still catch the line if formatting or parsing shifts.
        if "SOFT TISSUE PALPATION" in _obj_line:
            _parts = _obj_line.split()
            _tag = _normalize_obj_tag(_parts[-1]) if _parts else ""
            if _tag:
                self.show_page("Objectives")
                if hasattr(self, "objectives_page") and hasattr(self.objectives_page, "focus_palpation_region"):
                    self.objectives_page.focus_palpation_region(_tag)
            return
        if "ORTHOPEDIC EXAM" in _obj_line:
            _parts = _obj_line.split()
            _tag = _normalize_obj_tag(_parts[-1]) if _parts else ""
            if _tag:
                self.show_page("Objectives")
                if hasattr(self, "objectives_page") and hasattr(self.objectives_page, "focus_orthopedic_region"):
                    self.objectives_page.focus_orthopedic_region(_tag)
            return
        if "RANGE OF MOTION" in _obj_line:
            _parts = _obj_line.split()
            _tag = _normalize_obj_tag(_parts[-1]) if _parts else ""
            if _tag:
                self.show_page("Objectives")
                if hasattr(self, "objectives_page") and hasattr(self.objectives_page, "focus_rom_region"):
                    self.objectives_page.focus_rom_region(_tag)
            return

        # Other Objectives sub-headings (Functional Status, Vitals, Posture, Grip, Subluxations).
        # Only run when the line is clearly NOT a region-block line, so we never open Vitals
        # when the user clicked on Palpation/Ortho/ROM (e.g. after a refresh shifted the line).
        _is_region_block_line = (
            "SOFT TISSUE PALPATION" in _obj_line
            or "ORTHOPEDIC EXAM" in _obj_line
            or "RANGE OF MOTION" in _obj_line
        )
        if not _is_region_block_line and (
            _obj_line.startswith("Functional Status")
            or _obj_line.startswith("Vitals")
            or _obj_line.startswith("Posture")
            or _obj_line.startswith("Grip Strength")
            or "Spinal Palpatory Inspection" in _obj_line
        ):
            self.show_page("Objectives")
            self._handle_preview_subheading_click("Objectives", line_content)
            return

        # HOI subheading + keywords inside the MOI narrative...
        lower = (line_content or "").lower()
        ...

        if (
            "mechanism of injury" in lower
            or "medical care" in lower
            or "prescribed" in lower
            or "diagnostic imaging" in lower
        ):
            # Always use the HOI page for these keywords
            section_name = "HOI History"
            self.show_page("HOI History")

            # Column within the line where the user clicked (0-based)
            try:
                col = int(index.split(".")[1])
            except Exception:
                col = 0

            def _nearest_hoi_keyword(line_lower: str, col_idx: int) -> str | None:
                """
                Return one of:
                  'moi', 'prior_care', 'meds', 'diagnostics'
                based on which keyword center is closest to the click column.
                """
                candidates: list[tuple[float, str]] = []

                # Keywords and their logical targets, in rough priority order
                patterns = [
                    ("mechanism of injury (moi):", "moi"),
                    ("diagnostic imaging", "diagnostics"),
                    ("prescribed", "meds"),
                    ("medical care", "prior_care"),
                ]

                for key, label in patterns:
                    pos = line_lower.find(key)
                    if pos != -1:
                        center = pos + (len(key) / 2.0)
                        dist = abs(center - col_idx)
                        candidates.append((dist, label))

                if not candidates:
                    return None

                candidates.sort(key=lambda x: x[0])
                return candidates[0][1]

            target = _nearest_hoi_keyword(lower, col)

            if hasattr(self, "hoi_page") and target:
                if target == "moi" and hasattr(self.hoi_page, "focus_moi_section"):
                    self.hoi_page.focus_moi_section()
                elif target == "diagnostics" and hasattr(self.hoi_page, "focus_diagnostics_section"):
                    self.hoi_page.focus_diagnostics_section()
                elif target == "meds" and hasattr(self.hoi_page, "focus_medications_section"):
                    self.hoi_page.focus_medications_section()
                elif target == "prior_care" and hasattr(self.hoi_page, "focus_prior_care_section"):
                    self.hoi_page.focus_prior_care_section()

            # We’ve fully handled the HOI click here; no need to fall through.
            return

        # For everything else (Objectives, Plan, etc.) fall back to subheading handler.
        self._handle_preview_subheading_click(section_name, line_content)

    def _handle_preview_subheading_click(self, section_name: str, line: str) -> None:
        """
        Handle clicks on sub-headings or summary lines inside the Live Preview.

        - section_name: logical left-nav page (e.g. "HOI History", "Subjectives",
          "Objectives", "Plan").
        - line: the exact text content of the clicked line (trimmed).
        """
        line = (line or "").strip()
        if not line:
            return

        # ------------- HOI: Mechanism of Injury / Prior Care / Meds / Diagnostics -------------
        if section_name == "HOI History":
            lower = (line or "").strip().lower()

            # 1) Exact MOI heading line
            # Live Preview prints: "Mechanism of Injury (MOI):"
            if lower.startswith("mechanism of injury (moi):"):
                if hasattr(self, "hoi_page") and hasattr(self.hoi_page, "focus_moi_section"):
                    self.hoi_page.focus_moi_section()
                return

            # 2) More general keywords inside the HOI narrative.
            # Order here matters: we check DIAGNOSTIC IMAGING first,
            # then PRESCRIBED, then MEDICAL CARE, so a line containing
            # multiple phrases does not always fall into Prior Care.
            if "diagnostic imaging" in lower:
                if hasattr(self, "hoi_page") and hasattr(self.hoi_page, "focus_diagnostics_section"):
                    self.hoi_page.focus_diagnostics_section()
                return

            if "prescribed" in lower:
                if hasattr(self, "hoi_page") and hasattr(self.hoi_page, "focus_medications_section"):
                    self.hoi_page.focus_medications_section()
                return

            if "medical care" in lower:
                if hasattr(self, "hoi_page") and hasattr(self.hoi_page, "focus_prior_care_section"):
                    self.hoi_page.focus_prior_care_section()
                return

            return

        # ------------- Subjectives: region headings -> Block N {Region} -------------
        if section_name == "Subjectives":
            # Subjectives Live Preview prints REGION_LABELS as headings, e.g. "Cervical Spine"
            # We treat any known body-region label as a click on that block.
            if hasattr(self, "subjectives_page") and hasattr(self.subjectives_page, "focus_region_label"):
                try:
                    from config import REGION_LABELS  # local import to avoid cycles at top
                except Exception:
                    REGION_LABELS = {}
                # If this line matches any REGION_LABELS value, try to focus that block.
                if line in REGION_LABELS.values():
                    self.subjectives_page.focus_region_label(line)
            return

        # ------------- Objectives: Functional Status, Vitals, Posture, Palpation, Grip, Blocks -------------
        if section_name == "Objectives":
            if not hasattr(self, "objectives_page"):
                return

            # Functional Status -> ADLs block
            if line.startswith("Functional Status"):
                if hasattr(self.objectives_page, "focus_adl_section"):
                    self.objectives_page.focus_adl_section()

            # Vitals
            if line.startswith("Vitals"):
                if hasattr(self.objectives_page, "focus_vitals_section"):
                    self.objectives_page.focus_vitals_section()

            # Posture
            if line.lower().startswith("posture"):
                if hasattr(self.objectives_page, "focus_posture_section"):
                    self.objectives_page.focus_posture_section()

            # Spinal Palpatory Inspection -> Subluxations / palpation block (global)
            if "Spinal Palpatory Inspection" in line:
                if hasattr(self.objectives_page, "focus_spinal_palpation_section"):
                    self.objectives_page.focus_spinal_palpation_section()

            # Grip Strength (Jamar) -> Grip
            if "Grip Strength" in line or "Jamar" in line:
                if hasattr(self.objectives_page, "focus_grip_section"):
                    self.objectives_page.focus_grip_section()

            # Region block headings: SOFT TISSUE PALPATION {tag}, ORTHOPEDIC EXAM {tag}, RANGE OF MOTION {tag}
            stripped = (line or "").strip()
            parts = stripped.split()
            tag = parts[-1] if len(parts) >= 2 else ""

            if stripped.startswith("SOFT TISSUE PALPATION ") and tag:
                if hasattr(self.objectives_page, "focus_palpation_region"):
                    self.objectives_page.focus_palpation_region(tag)

            if stripped.startswith("ORTHOPEDIC EXAM ") and tag:
                if hasattr(self.objectives_page, "focus_orthopedic_region"):
                    self.objectives_page.focus_orthopedic_region(tag)

            if stripped.startswith("RANGE OF MOTION ") and tag:
                if hasattr(self.objectives_page, "focus_rom_region"):
                    self.objectives_page.focus_rom_region(tag)

            return

        # ------------- Assessment: Diagnosis / Causation / Prognosis / Imaging / Referrals / Work Status -------------
        # if section_name == "Diagnosis":
        #     if not hasattr(self, "diagnosis_page"):
        #         return

        #     stripped = (line or "").strip()

        #     # Main ASSESSMENT heading line should open the Assessment sub-section
        #     if stripped.upper().startswith("ASSESSMENT"):
        #         if hasattr(self.diagnosis_page, "focus_assessment_block"):
        #             self.diagnosis_page.focus_assessment_block()

        #     # Diagnosis -> Dx Block
        #     if stripped.startswith("Diagnosis"):
        #         if hasattr(self.diagnosis_page, "focus_diagnosis_block"):
        #             self.diagnosis_page.focus_diagnosis_block()

        #     # Causation
        #     if stripped.startswith("Causation"):
        #         if hasattr(self.diagnosis_page, "focus_causation_block"):
        #             self.diagnosis_page.focus_causation_block()

        #     # Prognosis
        #     if stripped.startswith("Prognosis"):
        #         if hasattr(self.diagnosis_page, "focus_prognosis_block"):
        #             self.diagnosis_page.focus_prognosis_block()

        #     # Imaging
        #     if stripped.startswith("Imaging"):
        #         if hasattr(self.diagnosis_page, "focus_imaging_block"):
        #             self.diagnosis_page.focus_imaging_block()

        #     # Referrals
        #     if stripped.startswith("Referrals"):
        #         if hasattr(self.diagnosis_page, "focus_referrals_block"):
        #             self.diagnosis_page.focus_referrals_block()

        #     # Current Work Status / Work Duties
        #     if "Current Work Status" in stripped or "Work Duties" in stripped:
        #         if hasattr(self.diagnosis_page, "focus_work_status_block"):
        #             self.diagnosis_page.focus_work_status_block()

        #     return
        # ------------- PLAN OF CARE: grid lines -> PlanPage blocks -------------
        # if section_name == "Plan":
        #     if not hasattr(self, "plan_page"):
        #         return
        #     lower = line.lower()

        #     if line.startswith("Care Type(s):"):
        #         if hasattr(self.plan_page, "focus_care_types_block"):
        #             self.plan_page.focus_care_types_block()
        #     elif line.startswith("Regions:"):
        #         if hasattr(self.plan_page, "focus_regions_treated_block"):
        #             self.plan_page.focus_regions_treated_block()
        #     elif line.startswith("Frequency:") or line.startswith("Duration:") or line.startswith("Re-evaluation:"):
        #         if hasattr(self.plan_page, "focus_schedule_block"):
        #             self.plan_page.focus_schedule_block()
        #     elif line.startswith("Goals:"):
        #         if hasattr(self.plan_page, "focus_goals_block"):
        #             self.plan_page.focus_goals_block()
        #     elif line.startswith("Work Duties:"):
        #         if hasattr(self, "diagnosis_page") and hasattr(self.diagnosis_page, "focus_work_status_block"):
        #             self.diagnosis_page.focus_work_status_block()
        #     elif line.startswith("Services Provided Today"):
        #         if hasattr(self.plan_page, "focus_services_block"):
        #             self.plan_page.focus_services_block()

        #     return

    def _rebuild_exam_nav_buttons(self):
        # Remove old exam buttons only (leave label + add buttons alone)
        for name, btn in list(self.exam_buttons.items()):
            try:
                btn.destroy()
            except Exception:
                pass
        self.exam_buttons.clear()

        # Ensure current patient’s dynamic exams are loaded if we have a patient
        # (only do this once patient info exists; otherwise keep EMPTY_EXAMS)
        if self.get_current_patient_root():
            self.exams = self._load_dynamic_exams_for_patient()
        else:
            self.exams = list(EMPTY_EXAMS)

        # Recreate buttons (insert before the + buttons, which we pack on the right)
        for exam in self.exams:
            label = exam
            if exam.startswith("Review of Findings"):
                label = exam.replace("Review of Findings", "ROF", 1)

            parent = getattr(self, "working_docs_list", None)
            if parent is None:
                return

            date_str = self._date_for_exam_button(exam)
            btn_text = f"{date_str}   {label}"
            btn = ttk.Button(parent, text=btn_text, command=lambda e=exam: self.switch_exam(e))
            btn.pack(fill="x", pady=4)
            self.exam_buttons[exam] = btn


        self._refresh_exam_button_styles()
        self._apply_exam_color_theme()        


    def _ensure_patient_for_dynamic_exam(self) -> bool:
        self._ensure_current_patient_id()
        return True


    def add_reexam(self):
        if not self._ensure_patient_for_dynamic_exam():
            return

        if not messagebox.askyesno(
            "Create Re-Exam",
            "Create a NEW Re-Exam?\n\n(This cannot be undone.)"
        ):
            return

        n = _next_number(self.exams, "Re-Exam")
        name = f"Re-Exam {n}"
        self._add_dynamic_exam(name, copy_current=True)   # copy forward
        self.after(0, lambda: self.switch_exam(name, force=True))


    def add_rof(self):
        if not self._ensure_patient_for_dynamic_exam():
            return

        if not messagebox.askyesno(
            "Create Review of Findings",
            "Create a NEW Review of Findings exam?\n\n(This cannot be undone.)"
        ):
            return

        n = _next_number(self.exams, "Review of Findings")
        name = f"Review of Findings {n}"
        self._add_dynamic_exam(name, copy_current=True)   # copy forward
        self.after(0, lambda: self.switch_exam(name, force=True))

    
    def add_final(self):
        if not self._ensure_patient_for_dynamic_exam():
            return

        if not messagebox.askyesno(
            "Create Final Exam",
            "Create a NEW Final exam?\n\n(This cannot be undone.)"
        ):
            return

        n = _next_number(self.exams, "Final")
        name = f"Final {n}"
        self._add_dynamic_exam(name, copy_current=True)
        self.after(0, lambda: self.switch_exam(name, force=True))


    def add_chiro_visit(self):
        if not self._ensure_patient_for_dynamic_exam():
            return

        if not messagebox.askyesno(
            "Create Chiropractic Treatment Note",
            "Create a NEW Chiropractic Treatment Note?\n\n(This cannot be undone.)"
        ):
            return

        n = _next_number(self.exams, "Chiro Visit")
        name = f"Chiro Visit {n}"
        self._add_dynamic_exam(name, copy_current=True)

        self.after(0, lambda: self.switch_exam(name, force=True))


    def add_initial(self):
        if not self._ensure_patient_for_dynamic_exam():
            return

        if not messagebox.askyesno(
            "Create Initial Exam",
            "Create a NEW Initial exam?\n\n(This cannot be undone.)"
        ):
            return

        n = _next_number(self.exams, "Initial")
        name = f"Initial {n}"
        self._add_dynamic_exam(name, copy_current=True)
        self.after(0, lambda: self.switch_exam(name, force=True))



    def _add_dynamic_exam(self, exam_name: str, copy_current: bool = False):

        exam_name = (exam_name or "").strip()
        if not exam_name:
            return

        # de-dupe by case-insensitive name
        existing_lower = {e.lower() for e in self.exams}
        if exam_name.lower() in existing_lower:
            self.switch_exam(exam_name)
            return

        # Save current exam first (best effort)
        try:
            self._autosave(force=True)
        except Exception:
            pass

        # Add to list + persist + rebuild UI
        self.exams.append(exam_name)
        self._save_dynamic_exams_for_patient()
        self._rebuild_exam_nav_buttons()

        # Initialize pdf map entry for new exam
        if not hasattr(self, "last_exam_pdf_paths") or not isinstance(self.last_exam_pdf_paths, dict):
            self.last_exam_pdf_paths = {}
        self.last_exam_pdf_paths[exam_name] = ""

        # Switch to it (no file exists yet -> clear exam content)
        self.current_exam.set(exam_name)
        self._set_current_doc_label()
        self._refresh_exam_button_styles()
        self._apply_exam_color_theme()
        # ✅ NEW: set today's visit date for a newly created exam (first time)
        self.exam_date_var.set(today_mmddyyyy())
        self._set_current_doc_label()        

        if copy_current:
            # Save the CURRENT on-screen content under the NEW exam name/path
            new_path = self.compute_exam_path(exam_name)
            if new_path:
                try:
                    self.save_case_to_path(new_path)
                    # ✅ NEW: rebuild so the new button pulls its date from JSON instead of fallback
                    #self._rebuild_exam_nav_buttons()
                    self.status_var.set(f"{exam_name} created (copied from previous exam).")
                except Exception as e:
                    self.status_var.set(f"{exam_name} created, but copy-save failed: {e}")
        else:
            self.clear_exam_content_only()
            self.current_case_path = None
            self.status_var.set(f"{exam_name} created (new blank exam).")
            # ✅ NEW: rebuild buttons so new button shows today's date immediately
            #self._rebuild_exam_nav_buttons()


    def delete_exam(self, exam_name: str):
        exam_name = (exam_name or "").strip()
        if not exam_name:
            return

        # Only allow deleting dynamic exams that exist in the list
        if exam_name not in self.exams:
            return

        # Confirm with the user
        if not messagebox.askyesno(
            "Delete Exam",
            f"Delete exam '{exam_name}' and ALL of its associated files?\n\n"
            "This will remove:\n"
            "- The exam JSON\n"
            "- Any PDFs for this exam\n"
            "- The exam entry in the index file\n\n"
            "This cannot be undone.\n\n"
            "Continue?"
        ):
            return

        patient_root = self.get_current_patient_root()

        # 1) Delete exam JSON file
        try:
            json_path = self.compute_exam_path(exam_name)
            if json_path and os.path.exists(json_path):
                os.remove(json_path)
        except Exception:
            pass

        # 2) Delete PDFs in patient_root/pdfs/ and in Doc Vault (vault/pdfs)
        try:
            if patient_root:
                exam_slug = safe_slug(exam_name).lower()

                # Main pdfs folder
                pdf_dir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)
                if os.path.isdir(pdf_dir):
                    for fn in os.listdir(pdf_dir):
                        low = fn.lower()
                        # export_current_exam_to_pdf_overwrite uses: "{exam_slug}_<display>_DOB_<dob>_DOI_<doi>.pdf"
                        if low.endswith(".pdf") and low.startswith(exam_slug + "_"):
                            try:
                                os.remove(os.path.join(pdf_dir, fn))
                            except Exception:
                                pass

                # Doc Vault pdfs folder (vault/pdfs)
                vault_dir = os.path.join(patient_root, "vault", "pdfs")
                if os.path.isdir(vault_dir):
                    for fn in os.listdir(vault_dir):
                        low = fn.lower()
                        # vault name pattern: "<date_slug>__<exam_slug>.pdf"
                        if low.endswith(f"__{exam_slug}.pdf"):
                            try:
                                os.remove(os.path.join(vault_dir, fn))
                            except Exception:
                                pass
        except Exception:
            pass

        # 3) Remove from in-memory lists/maps
        try:
            self.exams = [e for e in self.exams if e != exam_name]
            # Persist updated exam list into _exam_index.json in index_exam_number/
            self._save_dynamic_exams_for_patient()
        except Exception:
            pass

        try:
            if hasattr(self, "last_exam_pdf_paths") and isinstance(self.last_exam_pdf_paths, dict):
                self.last_exam_pdf_paths.pop(exam_name, None)
        except Exception:
            pass

        # 4) If we just deleted the current exam, move to another or clear
        if self.current_exam.get() == exam_name:
            if self.exams:
                new_exam = self.exams[-1]  # or self.exams[0]
                self.current_exam.set(new_exam)

                # Try to load its content if a JSON exists
                new_path = self.compute_exam_path(new_exam)
                if new_path and os.path.exists(new_path):
                    try:
                        self.load_case_from_path(new_path)
                    except Exception:
                        # If loading fails, at least clear the content
                        self.clear_exam_content_only()
                        self.current_case_path = None
            else:
                # No exams left for this patient
                self.current_exam.set("")
                self.clear_exam_content_only()
                self.current_case_path = None

        # 5) Refresh UI: exam nav + Docs timeline + theme + current doc label
        try:
            self._rebuild_exam_nav_buttons()
        except Exception:
            pass

        try:
            self._set_current_doc_label()
        except Exception:
            pass

        try:
            self._apply_exam_color_theme()
        except Exception:
            pass

        try:
            self.tk_docs_page.refresh()
        except Exception:
            pass

        self.status_var.set(f"Deleted exam: {exam_name}")
    

    def _toggle_header(self):
        self.header_visible.set(not self.header_visible.get())
        self._apply_header_visibility()

    def _apply_header_visibility(self):
        show = self.header_visible.get()

        if show:
            if not self.clinic_frame.winfo_ismapped():
                self.clinic_frame.pack(fill="x")
            if not self.header_separator.winfo_ismapped():
                self.header_separator.pack(fill="x", pady=(10, 0))
            if not self.exam_accent.winfo_ismapped():
                self.exam_accent.pack(fill="x", pady=(4, 6))

            self.header_toggle_btn.configure(text="Hide Header")
        else:
            if self.clinic_frame.winfo_ismapped():
                self.clinic_frame.pack_forget()
            if self.header_separator.winfo_ismapped():
                self.header_separator.pack_forget()
            if self.exam_accent.winfo_ismapped():
                self.exam_accent.pack_forget()

            self.header_toggle_btn.configure(text="Show Header")

    def _demo_summary_text(self) -> str:
        last = (self.last_name_var.get() or "").strip()
        first = (self.first_name_var.get() or "").strip()
        dob = (self.dob_var.get() or "").strip()
        doi = (self.doi_var.get() or "").strip()
        visit = (self.exam_date_var.get() or "").strip()
        claim = (self.claim_var.get() or "").strip()
        prov = (self.provider_var.get() or "").strip()

        name = ", ".join([x for x in [last, first] if x])
        parts = []
        parts.append(name if name else "Patient: (none)")
        if dob:   parts.append(f"DOB: {dob}")
        if doi:   parts.append(f"DOI: {doi}")
        if visit: parts.append(f"Visit: {visit}")
        if claim: parts.append(f"Claim: {claim}")
        if prov:  parts.append(f"DC: {prov}")

        return "   |   ".join(parts)

    def _refresh_demo_summary(self, *_):
        try:
            self.demo_summary_var.set(self._demo_summary_text())
        except Exception:
            pass

    def _toggle_demographics(self):
        self.demo_visible.set(not self.demo_visible.get())
        self._apply_demographics_visibility()

    def _apply_demographics_visibility(self):
        show = self.demo_visible.get()

        if show:
            # show full form
            if self.demo_summary_row.winfo_ismapped():
                self.demo_summary_row.pack_forget()
            if not self.info_frame.winfo_ismapped():
                self.info_frame.pack(fill="x", padx=10, pady=(10, 0))
            self.demo_toggle_btn.configure(text="Hide Demographics")
        else:
            # show thin summary line
            if self.info_frame.winfo_ismapped():
                self.info_frame.pack_forget()
            if not self.demo_summary_row.winfo_ismapped():
                self.demo_summary_row.pack(fill="x", padx=10, pady=(10, 0))
            self.demo_toggle_btn.configure(text="Show Demographics")

        self._refresh_demo_summary()
    
    
    
    def export_exam_pdf(self):
        # 1) Ask where to save
        save_path = filedialog.asksaveasfilename(
            title="Save Exam PDF As",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="final_exam.pdf",
        )
        if not save_path:
            return

        # 2) Build payloads the SAME way you already do when exporting now
        payloads = self._collect_payloads_for_pdf()  # <-- replace with YOUR real function
        if not payloads:
            messagebox.showinfo("Export PDF", "No data found to export.")
            return

        # 3) Build to temp, then overwrite atomically
        tmp_path = save_path + ".tmp"

        try:
            from pdf_export import build_combined_pdf  # import here avoids circular imports
            build_combined_pdf(tmp_path, payloads)     # <-- IMPORTANT: (path, payloads) order

            os.replace(tmp_path, save_path)

            # 4) Remember current PDF
            self.last_saved_pdf_path = save_path

            # 5) The “other popup”
            if messagebox.askyesno("PDF Saved", f"Saved:\n{save_path}\n\nOpen it now?"):
                open_with_default_app(save_path)

        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            messagebox.showerror("Export PDF Failed", f"Could not create the PDF:\n\n{e}")

    
    def export_current_exam_to_pdf_overwrite(self):
        if not self._ensure_reportlab():
            return

        patient_root = self.get_current_patient_root()
        if not patient_root:
            messagebox.showinfo("PDF", "Enter Last, First, DOB, and DOI first.")
            return

        ensure_patient_dirs(patient_root)
        pdf_dir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)
        os.makedirs(pdf_dir, exist_ok=True)

        display = to_last_first(self.last_name_var.get(), self.first_name_var.get()) or "Patient"
        dob = (self.dob_var.get() or "").strip()
        doi = (self.doi_var.get() or "").strip()
        exam = self.current_exam.get()

        # deterministic filename (same exam overwrites every time)
        filename = f"{safe_slug(exam)}_{safe_slug(display)}_DOB_{safe_slug(dob)}_DOI_{safe_slug(doi)}.pdf"
        path = os.path.join(pdf_dir, filename)

        payload = self.make_payload() or {}
        build_combined_pdf(path, [payload])

        # ✅ Auto-save/replace into Doc Vault -> pdfs/
        try:
            patient_root = self.get_current_patient_root()
            if patient_root:
                exam = self.current_exam.get()
                # stable vault filename per exam:
                #vault_name = f"{safe_slug(exam)}.pdf"
                exam = self.current_exam.get()

                # use demographics visit date (normalized), fallback to today
                date_str = normalize_mmddyyyy(self.exam_date_var.get()) or today_mmddyyyy()

                # deterministic name: "02_12_2026__re_exam_1.pdf"
                exam_slug = safe_slug(exam)
                date_slug = safe_slug(date_str)
                vault_name = f"{date_slug}__{exam_slug}.pdf"

                # (optional but recommended) delete any older variants for this exam in the vault
                vault_dir = os.path.join(patient_root, "vault", "pdfs")
                try:
                    if os.path.isdir(vault_dir):
                        for fn in os.listdir(vault_dir):
                            if fn.lower().endswith(f"__{exam_slug}.pdf"):
                                try:
                                    os.remove(os.path.join(vault_dir, fn))
                                except Exception:
                                    pass
                except Exception:
                    pass

                vault_path = upsert_vault_file(patient_root, "pdfs", path, vault_name)

                # If user is on Doc Vault page and viewing pdfs, refresh list
                if getattr(self.current_page, "get", lambda: "")() == "Doc Vault":
                    try:
                        if getattr(self.doc_vault_page.folder_panel, "folder_key", None) == "pdfs":
                            self.doc_vault_page.refresh_current_folder()
                    except Exception:
                        pass

                self.status_var.set(f"PDF saved + updated in Vault: {os.path.basename(vault_path)}")
        except Exception as e:
            print("Vault upsert failed:", e)


        self.last_exam_pdf_paths[exam] = path
        self.write_settings({
            "last_exam_pdfs": self.last_exam_pdf_paths,
            "last_all_exams_pdf": self.last_all_exams_pdf_path
        })        

    # ---------- Providers for HOI ----------
    def _patient_info_from_demo(self) -> dict:
        return {
            "first": self.first_name_var.get().strip(),
            "last": self.last_name_var.get().strip(),
            "doi": self.doi_var.get().strip(),
            # if later you add sex to demographics, include it here:
            # "sex": self.sex_var.get().strip(),
        }

    def _regions_from_subjectives(self) -> list[str]:
        """
        Return pretty region LABELS from subjectives blocks, e.g.:
        ["Cervical Spine", "Lumbar Spine"]
        """
        try:
            data = self.subjectives_page.to_dict() or {}
            blocks = data.get("blocks") or []
        except Exception:
            return []

        labels = []
        for b in blocks:
            region_code = (b.get("region") or "").strip()
            label = REGION_LABELS.get(region_code, "")
            if label:
                labels.append(label)

        seen = set()
        out = []
        for x in labels:
            k = x.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    # ---------- Color Theme ----------
    def _apply_exam_color_theme(self):
        exam = self.current_exam.get()
        theme = EXAM_COLORS.get(exam)
        if not theme:
            return

        bg = theme["bg"]
        accent = theme["accent"]

        self.exam_nav.configure(bg=bg)
        if hasattr(self, "exam_accent"):
            self.exam_accent.configure(bg=accent)

        for name, btn in self.exam_buttons.items():
            if name == exam:
                btn.configure(style="ActiveExam.TButton")
            else:
                btn.configure(style="TButton")

    # ---------- Mousewheel ----------
    def _set_mousewheel_target(self, widget: tk.Widget | None):
        self._mousewheel_target = widget

    def _on_mousewheel(self, event):
        if not self._mousewheel_target:
            return
        if event.delta == 0:
            return
        steps = int(-1 * (event.delta / 120))
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self._mousewheel_target.yview_scroll(steps, "units")

    def _on_mousewheel_linux_up(self, event):
        if self._mousewheel_target:
            self._mousewheel_target.yview_scroll(-1, "units")

    def _on_mousewheel_linux_down(self, event):
        if self._mousewheel_target:
            self._mousewheel_target.yview_scroll(1, "units")

    # ---------- PDF open ----------
    def open_pdf_file(self, pdf_path: str):
        if not pdf_path or not os.path.exists(pdf_path):
            messagebox.showwarning("Not found", "No PDF file found to open.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(pdf_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", pdf_path], check=False)
            else:
                subprocess.run(["xdg-open", pdf_path], check=False)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open PDF:\n{e}")

    def open_current_exam_pdf(self):
        self.open_pdf_file(self.last_exam_pdf_paths.get(self.current_exam.get(), ""))

    def open_all_exams_pdf(self):
        self.open_pdf_file(self.last_all_exams_pdf_path)

    # ---------- UI ----------
    def _build_ui(self):
        padx = 10
       
        # Top-level 2-column layout
        # LEFT: your normal UI
        # RIGHT: live preview (starts at top of window)        
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        # Use the width chosen in __init__ based on screen size.
        # Fallback to 960 if for some reason it wasn't set.
        left_root_width = getattr(self, "_left_root_width", 960)

        left_root = ttk.Frame(main, width=left_root_width)
        left_root.pack(side="left", fill="both", expand=True)
        left_root.pack_propagate(False)

        right_root = ttk.Frame(main)
        right_root.pack(side="right", fill="both", expand=True)      
               
        # --- Header container (collapsible) ---
        self.header_container = ttk.Frame(left_root)
        self.header_container.pack(fill="x", padx=padx, pady=(padx, 0))

        # Toggle row
        toggle_row = ttk.Frame(self.header_container)
        toggle_row.pack(fill="x")

        self.header_toggle_btn = ttk.Button(
            toggle_row,
            text="Hide Header",
            command=self._toggle_header
        )
        self.header_toggle_btn.pack(side="left")
        self.alerts_btn = ttk.Button(
            toggle_row,
            text="Alerts",
            command=self._open_alerts_popup
        )
        self.alerts_btn.pack(side="left", padx=5)

        self.master_save_btn = ttk.Button(toggle_row, text="Master Save", command=self.master_save.run)
        self.master_save_btn.pack(side="left", padx=5)

        self.templates_btn = ttk.Button(toggle_row, text="Templates", command=self._open_templates_popup)
        self.templates_btn.pack(side="left", padx=5)        

        # The actual clinic header frame (this will be hidden/shown)
        self.clinic_frame = ttk.Frame(self.header_container)
        self.clinic_frame.pack(fill="x", pady=(0, 0))

        logo_label = ttk.Label(self.clinic_frame)
        logo_label.pack(side="left", padx=(0, 12))

        if os.path.exists(LOGO_PATH) and PIL_OK:
            try:
                img = Image.open(LOGO_PATH).convert("RGBA")
                img = img.resize((110, 110))
                self._tk_logo_image = ImageTk.PhotoImage(img)
                logo_label.configure(image=self._tk_logo_image)
            except Exception:
                logo_label.configure(text="(logo)")
        elif os.path.exists(LOGO_PATH) and not PIL_OK:
            logo_label.configure(text="Install pillow for JPG:\npython -m pip install pillow")
        else:
            logo_label.configure(text="(logo missing)")

        clinic_text = ttk.Frame(self.clinic_frame)
        clinic_text.pack(side="left", fill="x", expand=True)
        ttk.Label(clinic_text, text=CLINIC_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(clinic_text, text=CLINIC_ADDR, font=("Segoe UI", 12)).pack(anchor="w", pady=(2, 0))
        ttk.Label(clinic_text, text=CLINIC_PHONE_FAX, font=("Segoe UI", 12)).pack(anchor="w", pady=(2, 0))

        # separator + accent should hide/show with the header too
        self.header_separator = ttk.Separator(self.header_container)
        self.header_separator.pack(fill="x", pady=(10, 0))

        self.exam_accent = tk.Frame(self.header_container, height=4)
        self.exam_accent.pack(fill="x", pady=(4, 6))       

        # --- Patient info (collapsible + 1-line summary) ---
        demo_wrap = ttk.Frame(left_root)
        demo_wrap.pack(fill="x", padx=padx, pady=(padx, 0))

        demo_top = ttk.Frame(demo_wrap)
        demo_top.pack(fill="x")

        ttk.Label(demo_top, text="Demographics:", font=("Segoe UI", 10, "bold")).pack(side="left")

        self.demo_toggle_btn = ttk.Button(
            demo_top,
            text="Hide Demographics",
            command=self._toggle_demographics
        )
        self.demo_toggle_btn.pack(side="left")          
        
        # One-line summary row (shown only when collapsed)
        self.demo_summary_row = ttk.Frame(demo_wrap)
        # (do NOT pack here; visibility controlled by _apply_demographics_visibility)
        ttk.Label(
            self.demo_summary_row,
            textvariable=self.demo_summary_var,
            foreground="gray"
        ).pack(side="left", fill="x", expand=True)

        # The full demographics form (your existing label frame)
        self.info_frame = ttk.LabelFrame(demo_wrap, text="Patient / Case Info (shared across all exams)")
        self.info_frame.pack(fill="x")  # visibility controlled later

        # --- Exam nav ---
        self.exam_nav = tk.Frame(left_root)
        self.exam_nav.pack(fill="x", padx=padx, pady=(6, 0))

        ttk.Label(self.exam_nav, text="Exam:")#.pack(expand=True, anchor="center", padx=(0, 8))
        self.exam_buttons: dict[str, ttk.Button] = {}

        self.current_doc_label = ttk.Label(
            self.exam_nav,
            textvariable=self.current_doc_label_var,
            font=("Segoe UI", 10, "bold")
        )
        self.current_doc_label.pack(expand=True, anchor="center")        
        
        # build once
        self._rebuild_exam_nav_buttons()
        
        # ✅ Alias so your existing grid code can stay exactly the same:
        info = self.info_frame

        # --- your existing grid code stays the same below ---
        ttk.Label(info, text="Last name:").grid(row=0, column=0, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.last_name_var, width=22).grid(row=0, column=1, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="First name:").grid(row=0, column=2, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.first_name_var, width=22).grid(row=0, column=3, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="DOB (MM/DD/YYYY):").grid(row=1, column=0, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.dob_var, width=18).grid(row=1, column=1, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="Date of injury (DOI):").grid(row=1, column=2, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.doi_var, width=18).grid(row=1, column=3, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="Visit Date:").grid(row=2, column=0, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.exam_date_var, width=18).grid(row=2, column=1, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="Claim #:").grid(row=2, column=2, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.claim_var, width=18).grid(row=2, column=3, sticky="w", padx=padx, pady=6)

        ttk.Label(info, text="Provider (DC):").grid(row=3, column=0, sticky="w", padx=padx, pady=6)
        ttk.Entry(info, textvariable=self.provider_var, width=32).grid(row=3, column=1, sticky="w", padx=padx, pady=6)

        # --- Section nav (now inside left pane) ---
        soap_nav = ttk.Frame(left_root)
        soap_nav.pack(fill="x")
        ttk.Label(soap_nav, text="Section:").pack(side="left", padx=(0, 8))

        # Build nav list but inject Family/Social History between Subjectives and Objectives
        nav_pages = []
        for p in UI_PAGES:
            nav_pages.append(p)
            if p == "Subjectives" and "Family/Social History" not in nav_pages:
                nav_pages.append("Family/Social History")

        if "Docs" not in nav_pages:
            if "Doc Vault" in nav_pages:
                idx = nav_pages.index("Doc Vault")
                nav_pages.insert(idx, "Docs")
            else:
                nav_pages.append("Docs")

        self.page_buttons: dict[str, ttk.Button] = {}
        for page in nav_pages:
            b = ttk.Button(soap_nav, text=page, command=lambda p=page: self.show_page(p))
            b.pack(side="left", padx=4)
            self.page_buttons[page] = b

        # --- Content container (now inside left pane) ---
        self.content = ttk.Frame(left_root)        

        self.content.pack(fill="both", expand=True, pady=(10, 0))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # --- Right pane: permanent HOI / preview panel ---
        preview = ttk.LabelFrame(right_root, text="HOI / Live Preview (placeholder)")
        preview.pack(fill="both", expand=True, padx=(0, padx), pady=0)

        self.hoi_preview_text = tk.Text(preview, wrap="word")
        self.hoi_preview_scroll = ttk.Scrollbar(preview, orient="vertical", command=self.hoi_preview_text.yview)
        self.hoi_preview_text.configure(yscrollcommand=self.hoi_preview_scroll.set)
        self.hoi_preview_text.configure(state="disabled")

        self.hoi_preview_scroll.pack(side="right", fill="y")
        self.hoi_preview_text.pack(side="left", fill="both", expand=True)
        # Clickable headings in Live Preview
        self.hoi_preview_text.bind("<Button-1>", self._on_preview_click)

        def apply_preview_styles(txt: "tk.Text"):
            base = tkfont.nametofont("TkDefaultFont")
            bold = base.copy()
            bold.configure(weight="bold")
            txt.tag_configure("H_BOLD", font=bold)

        # call once after widget is created:
        apply_preview_styles(self.hoi_preview_text)        
        
        self.hoi_page = HOIPage(self.content, self.schedule_autosave)
        self.after(50, self.request_live_preview_refresh)

        def _subjectives_on_change():
            self.schedule_autosave()
            try:
                if hasattr(self, "hoi_page") and self.hoi_page is not None:
                    self.hoi_page._regen_moi_now()
            except Exception:
                pass
        self.subjectives_page = SubjectivesPage(self.content, _subjectives_on_change, app=self)
        self.family_social_page = TextPage(self.content, "Family/Social History", self.schedule_autosave)
        self.objectives_page = ObjectivesPage(self.content, self.schedule_autosave)
        self.diagnosis_page = DiagnosisPage(self.content, self.schedule_autosave)

        self.plan_page = PlanPage(self.content, on_change=self.schedule_autosave)

        # ✅ Correct place — wire callback AFTER both exist
        self.plan_page.set_subjectives_clear_regions_fn(
            self.subjectives_page.clear_all_body_regions
        )

        self.doc_vault_page = DocVaultPage(
            self.content,
            self.schedule_autosave,
            get_patient_root_fn=self.get_current_patient_root
        )        

        # --- Tk Docs timeline page ---
        self.tk_docs_page = TkDocsPage(
            self.content,
            get_exam_names_fn=lambda: self.exams,
            get_exam_path_fn=lambda exam: self.compute_exam_path(exam),
            get_fallback_date_fn=lambda: self.exam_date_var.get(),
            on_open_exam=lambda exam: self.switch_exam(exam),
            on_delete_exam=lambda exam: self.delete_exam(exam),
            #on_hover_exam=lambda exam, date_str: self._set_current_doc_label(date_str, exam),
            on_add_initial=self.add_initial,
            on_add_reexam=self.add_reexam,
            on_add_rof=self.add_rof,
            on_add_final=self.add_final,
            on_add_chiro=self.add_chiro_visit,
            set_scroll_target_fn=self._set_mousewheel_target,
            get_current_exam_fn=lambda: self.current_exam.get(),
        )

        # Only pages you want in the LEFT nav go here:
        self.pages = {
            "HOI History": self.hoi_page,
            "Subjectives": self.subjectives_page,
            "Family/Social History": self.family_social_page,
            "Objectives": self.objectives_page,
            "Diagnosis": self.diagnosis_page,
            "Plan": self.plan_page,
            "Docs": self.tk_docs_page,
            "Doc Vault": self.doc_vault_page,
        }

        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.tk_docs_page.refresh()

        # Now that Working Docs widgets exist, build the exam buttons into it
        self._rebuild_exam_nav_buttons()
        self._set_current_doc_label()        

        # Default page now (since HOI History is gone)
        self.show_page("Subjectives")               

        # Wire HOI providers (this is the critical part for your first-name + regions)
        self.hoi_page.set_regions_provider(self._regions_from_subjectives)
        self.hoi_page.set_patient_provider(self._patient_info_from_demo)       
       
        # Mousewheel routing for Subjectives scroll canvas
        if hasattr(self.subjectives_page, "canvas"):
            self.subjectives_page.canvas.bind("<Enter>", lambda e: self._set_mousewheel_target(self.subjectives_page.canvas))
            self.subjectives_page.canvas.bind("<Leave>", lambda e: self._set_mousewheel_target(None))
        if hasattr(self.subjectives_page, "scroll_frame") and hasattr(self.subjectives_page, "canvas"):
            self.subjectives_page.scroll_frame.bind("<Enter>", lambda e: self._set_mousewheel_target(self.subjectives_page.canvas))
            self.subjectives_page.scroll_frame.bind("<Leave>", lambda e: self._set_mousewheel_target(None))

        style = ttk.Style(self)
        style.configure("ActiveExam.TButton", font=("Segoe UI", 10, "bold"))

        style.configure(
            "AddExam.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(10, 4)
        )

        style.map(
            "AddExam.TButton",
            foreground=[("!disabled", "#7a1f1f")],   # dark red text
            background=[("active", "#f5c6c6")]
        )

        # --- Bottom buttons ---
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=padx, pady=padx)

        ttk.Button(bottom, text="Load Exam File (.json)", command=self.load_case_manual).pack(side="left")
        ttk.Button(bottom, text="Save Exam Now", command=self.save_case_now).pack(side="left", padx=(8, 0))

        ttk.Button(bottom, text="Export CURRENT Exam to PDF", command=self.export_current_exam_to_pdf).pack(side="left", padx=(8, 0))
        ttk.Button(bottom, text="Open Current Exam PDF", command=self.open_current_exam_pdf).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Export ALL Exams to ONE PDF", command=self.export_all_exams_to_one_pdf).pack(side="left", padx=(14, 0))
        ttk.Button(bottom, text="Open ALL Exams PDF", command=self.open_all_exams_pdf).pack(side="left", padx=(6, 0))

        ttk.Button(bottom, text="Print Exam Counts", command=self.print_exam_counts_for_current_patient).pack(side="left", padx=(8, 0))

        ttk.Button(bottom, text="Open New Form", command=launch_new_form).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Reset Exam (current only)", command=self.reset_current_exam).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="CLEAR FORM (does not delete files)", command=self.reset_entire_form).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Start New Case (keeps files)", command=self.start_new_case).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="Export CURRENT Exam to PDF (overwrite)", command=self.export_current_exam_to_pdf_overwrite)\
            .pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, foreground="gray").pack(anchor="w", padx=padx, pady=(0, padx))

        self._refresh_exam_button_styles()
        self._refresh_page_button_styles()
        self._apply_exam_color_theme()
        self._apply_header_visibility()

        for v in (
            self.last_name_var, self.first_name_var,
            self.dob_var, self.doi_var,
            self.exam_date_var, self.claim_var, self.provider_var
        ):
            v.trace_add("write", self._refresh_demo_summary)        

    # ---------- Page switching ----------

    def show_page(self, page_name: str):
        if page_name not in self.pages:
            return
        self.current_page.set(page_name)
        self.pages[page_name].tkraise()
        self._refresh_page_button_styles()

        # Also center the Live Preview on the corresponding heading, if any.
        self._center_preview_on_section(page_name)


    def _refresh_page_button_styles(self):
        current = self.current_page.get()
        for page, btn in self.page_buttons.items():
            btn.state(["!disabled"])
            if page == current:
                btn.state(["disabled"])

    
    def _prompt_new_exam_clear_dialog(self, target_exam: str) -> dict | None:
        """
        Returns:
        - dict of selections: {"hoi": bool, "subjectives": bool, "objectives": bool, "diagnosis": bool, "plan": bool}
        - {} means keep everything (clear nothing)
        - None means user cancelled (do not switch exams)
        """
        dlg = tk.Toplevel(self)
        dlg.title("Start New Exam")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        # Default: keep everything (unchecked)
        vars_map = {
            "hoi": tk.BooleanVar(value=False),
            "subjectives": tk.BooleanVar(value=False),
            "objectives": tk.BooleanVar(value=False),
            "diagnosis": tk.BooleanVar(value=False),
            "plan": tk.BooleanVar(value=False),
        }

        wrap = ttk.Frame(dlg, padding=14)
        wrap.pack(fill="both", expand=True)

        ttk.Label(
            wrap,
            text=f"You're switching to a NEW exam: {target_exam}\n\n"
                "Choose what to clear from the current on-screen exam.\n"
                "Leave everything unchecked to KEEP everything and just tweak it.",
            justify="left"
        ).pack(anchor="w")

        ttk.Separator(wrap).pack(fill="x", pady=10)

        # Only show checkboxes for sections that actually have content (nice UX)
        def add_cb(key: str, label: str, has_it: bool):
            if not has_it:
                return
            ttk.Checkbutton(wrap, text=label, variable=vars_map[key]).pack(anchor="w", pady=2)

        add_cb("hoi", "HOI", hasattr(self, "hoi_page") and self.hoi_page.has_content())
        add_cb("subjectives", "Subjectives", hasattr(self, "subjectives_page") and self.subjectives_page.has_content())
        add_cb("objectives", "Objectives", hasattr(self, "objectives_page") and self.objectives_page.has_content())
        add_cb("diagnosis", "Diagnosis", hasattr(self, "diagnosis_page") and self.diagnosis_page.has_content())
        add_cb("plan", "Plan", hasattr(self, "plan_page") and self.plan_page.has_content())

        # If nothing has content, no need to ask — but we still allow OK/cancel
        ttk.Separator(wrap).pack(fill="x", pady=10)

        result: dict | None = {}

        def keep_all():
            nonlocal result
            result = {}  # keep everything
            dlg.destroy()

        def clear_selected():
            nonlocal result
            result = {k: v.get() for k, v in vars_map.items()}
            dlg.destroy()

        def cancel():
            nonlocal result
            result = None
            dlg.destroy()

        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(4, 0))

        ttk.Button(btns, text="Cancel", command=cancel).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Clear Selected", command=clear_selected).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Keep Everything", command=keep_all).pack(side="right")

        # Center-ish
        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_rootx()+120}+{self.winfo_rooty()+120}")

        self.wait_window(dlg)
        return result

    def _clear_sections_silent(self, sel: dict):
        # HOI
        if sel.get("hoi"):            
            try:
                self.hoi_page.from_dict({})
            except Exception:
                try:
                    self.hoi_page.reset()
                except Exception:
                    pass

        # Subjectives
        if sel.get("subjectives"):
            try:
                self.subjectives_page.reset()
            except Exception:
                try:
                # fallback
                    self.subjectives_page.from_dict({"blocks": []})
                except Exception:
                    pass

        # Objectives
        if sel.get("objectives"):
            try:
                self.objectives_page.from_dict({"global": {}, "blocks": []})
            except Exception:
                pass

        # Diagnosis
        if sel.get("diagnosis"):
            try:
                self.diagnosis_page.from_dict({})
            except Exception:
                try:
                    self.diagnosis_page.set_value("")
                except Exception:
                    pass

        # Plan
        if sel.get("plan"):
            try:
                self.plan_page.reset()
            except Exception:
                try:
                    self.plan_page.load_struct({"auto_enabled": True, "plan_text": ""})
                except Exception:
                    pass


    def switch_exam(self, exam_name: str, force: bool = False):

        if (not force) and (exam_name == self.current_exam.get()):
            return        

        self._autosave(force=True)

        self.current_exam.set(exam_name)

        self._set_current_doc_label()
        self._apply_exam_color_theme()
        self._refresh_exam_button_styles()
        


        path = self.compute_exam_path(exam_name)
        if path and os.path.exists(path):
            try:
                self.load_case_from_path(path)
                self.status_var.set(f"Loaded {exam_name}: {os.path.basename(path)}")
            except Exception as e:
                self.status_var.set(f"Could not load {exam_name}: {e}")
        else:
            # Target exam has no saved file yet -> treat as "new exam"
            # Ask once what to clear (default is KEEP everything)
            sel = self._prompt_new_exam_clear_dialog(exam_name)

            if sel is None:
                # user cancelled: do not switch
                return

            # Keep current content unless user chose sections to clear
            if sel:
                self._clear_sections_silent(sel)

            self.current_case_path = None
            self.status_var.set(f"{exam_name} ready (new exam; carry-over kept unless cleared).")

        self.write_settings({"last_exam": exam_name})


    def _refresh_exam_button_styles(self):
        current = self.current_exam.get()
        for exam, btn in self.exam_buttons.items():
            btn.state(["!disabled"])
            if exam == current:
                btn.configure(style="ActiveExam.TButton")
            else:
                btn.configure(style="TButton")
    
    # Then update _exam_index_path() (lines 1809-1816) to:
    def _exam_index_path(self) -> str | None:
        patient_root = self.get_current_patient_root()
        if not patient_root:
            return None
        ensure_patient_dirs(patient_root)
        index_dir = os.path.join(patient_root, EXAM_INDEX_SUBDIR)  
        os.makedirs(index_dir, exist_ok=True)
        return os.path.join(index_dir, EXAM_INDEX_FILENAME)

    def _load_dynamic_exams_for_patient(self) -> list[str]:
        """
        Returns patient-specific exam list from _exam_index.json.
        Checks index_exam_number/ first, then exams/ (legacy). Migrates if found in legacy.
        Returns empty list if no index or invalid; no base exams are injected.
        """
        patient_root = self.get_current_patient_root()
        if not patient_root:
            return list(EMPTY_EXAMS)

        ensure_patient_dirs(patient_root)
        exams_dir = os.path.join(patient_root, PATIENT_SUBDIR_EXAMS)
        index_dir = os.path.join(patient_root, EXAM_INDEX_SUBDIR)
        os.makedirs(index_dir, exist_ok=True)

        # Try new location first, then legacy (exams/)
        primary_path = os.path.join(index_dir, EXAM_INDEX_FILENAME)
        legacy_path = os.path.join(exams_dir, EXAM_INDEX_FILENAME)

        p = primary_path if os.path.isfile(primary_path) else legacy_path
        if not p or not os.path.isfile(p):
            return list(EMPTY_EXAMS)

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            lst = data.get("exams") or []
            if not isinstance(lst, list):
                return list(EMPTY_EXAMS)

            # normalize + de-dupe but preserve order
            out = []
            seen = set()
            for x in lst:
                s = (x or "").strip()
                if not s:
                    continue
                k = s.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(s)

            # Migrate from legacy to new location
            if p == legacy_path and out:
                try:
                    with open(primary_path, "w", encoding="utf-8") as f:
                        json.dump({"exams": out}, f, indent=2)
                except Exception:
                    pass

            return out
        except Exception:
            return list(EMPTY_EXAMS)

    def _classify_exam_type(self, exam_name: str) -> str | None:
        """
        Map a dynamic exam name to a logical type.

        Returns one of: "initial", "re_exam", "rof", "chiro", "final", or None.
        """
        s = (exam_name or "").strip().lower()
        if not s:
            return None

        if s.startswith("initial"):
            return "initial"
        if s.startswith("re-exam"):
            return "re_exam"
        if s.startswith("review of findings"):
            return "rof"
        if s.startswith("chiro visit"):
            return "chiro"
        if s.startswith("final"):
            return "final"

        return None
    
    def print_exam_counts_for_current_patient(self) -> None:
        """
        Count saved exams for the CURRENT patient by type and print the results to the terminal.

        Types:
          - Initial
          - Re-Exam
          - Review of Findings
          - Chiro Visit
          - Final

        Only exams that have a saved JSON file on disk are counted.
        """
        patient_root = self.get_current_patient_root()
        if not patient_root:
            print("No current patient; cannot count exams.")
            return

        # Ensure dynamic exam list is up to date for this patient
        try:
            if self.get_current_patient_root():
                self.exams = self._load_dynamic_exams_for_patient()
        except Exception as e:
            print(f"Could not load dynamic exams for patient: {e}")
            return

        counts = {
            "initial": 0,
            "re_exam": 0,
            "rof": 0,
            "chiro": 0,
            "final": 0,
        }

        for exam in (self.exams or []):
            exam_type = self._classify_exam_type(exam)
            if not exam_type:
                continue  # skip unknown types

            # Only count exams that actually have a saved JSON file
            path = self.compute_exam_path(exam)
            if not path or not os.path.exists(path):
                continue

            counts[exam_type] = counts.get(exam_type, 0) + 1

        total = sum(counts.values())

        print("Exam counts for current patient:")
        print(f"  Initial:        {counts['initial']}")
        print(f"  Re-Exam:        {counts['re_exam']}")
        print(f"  Review of Findings: {counts['rof']}")
        print(f"  Chiro Visit:    {counts['chiro']}")
        print(f"  Final:          {counts['final']}")
        print(f"  TOTAL visits:   {total}")        
    

    def _save_dynamic_exams_for_patient(self):
        p = self._exam_index_path()
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"exams": list(self.exams)}, f, indent=2)
        except Exception:
            pass

    # ---------- Settings ----------

    def write_settings(self, settings: dict):
        ensure_year_root()
        base: dict = {}
        if SETTINGS_PATH.exists():
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    base = json.load(f) or {}
            except Exception:
                base = {}
        base.update(settings)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(base, f, indent=2)

    def read_settings(self) -> dict:
        if not SETTINGS_PATH.exists():
            return {}

        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    # ---------- Patient folders / paths ----------    
    def _ensure_current_patient_id(self) -> str:
        """Ensure we have a patient ID; create one if missing. Returns current_patient_id."""
        pid = getattr(self, "current_patient_id", None)
        if not pid:
            self.current_patient_id = new_patient_id()
            return self.current_patient_id
        return pid

    def get_current_patient_root(self):
        pid = getattr(self, "current_patient_id", None)
        if not pid:
            return None
        folder = get_patient_root(
            pid,
            self.last_name_var.get() or "",
            self.first_name_var.get() or "",
        )
        return str(folder)


    def compute_exam_path(self, exam_name: str | None = None) -> str | None:
        exam_name = exam_name or self.current_exam.get()

        patient_root = self.get_current_patient_root()
        if not patient_root:
            return None

        ensure_patient_dirs(patient_root)
        filename = f"{safe_slug(exam_name)}.json"
        return os.path.join(patient_root, PATIENT_SUBDIR_EXAMS, filename)

    def autoload_last_case_on_startup(self):
        if getattr(self, "_start_blank", False):
            self.status_var.set("Ready. (New blank form)")
            self._apply_exam_color_theme()
            return

        settings = self.read_settings()

        last_path = settings.get("last_case_path")
        if last_path and os.path.exists(last_path):
            try:
                self.load_case_from_path(last_path)
                self.status_var.set(f"Loaded last file: {os.path.basename(last_path)}")

                # ✅ NOW that patient_id exists, rebuild dynamic exams + refresh Docs timeline
                self._rebuild_exam_nav_buttons()
                try:
                    self.tk_docs_page.refresh()
                except Exception:
                    pass

            except Exception as e:
                self.status_var.set(f"Could not load last file: {e}")
        else:
            self.status_var.set("Ready. (No last file found)")

        # keep this AFTER load/rebuild
        last_exam = (settings.get("last_exam") or "").strip()
        if last_exam and last_exam.lower() in {e.lower() for e in self.exams}:
            self.current_exam.set(last_exam)
            self._refresh_exam_button_styles()

        pdf_map = settings.get("last_exam_pdfs", {})
        if isinstance(pdf_map, dict):
            if not hasattr(self, "exams") or not self.exams:
                self.exams = list(EMPTY_EXAMS)

            for exam in self.exams:
                self.last_exam_pdf_paths[exam] = pdf_map.get(exam, "") or ""

        self.last_all_exams_pdf_path = settings.get("last_all_exams_pdf", "") or ""
        self._apply_exam_color_theme()


    def _wire_autosave_triggers(self):
        for v in (
            self.last_name_var, self.first_name_var,
            self.dob_var, self.doi_var, self.exam_date_var,
            self.claim_var, self.provider_var
        ):
            v.trace_add("write", lambda *_: self.schedule_autosave())

    def schedule_autosave(self):
        if self._loading:
            return

        if self._autosave_after_id is not None:
            try:
                self.after_cancel(self._autosave_after_id)
            except Exception:
                pass

        self._autosave_after_id = self.after(AUTOSAVE_DEBOUNCE_MS, self._autosave)

        # ✅ ONE place to refresh preview (debounced)
        self.request_live_preview_refresh()
        

    def _current_exam_has_content(self) -> bool:
        if hasattr(self, "hoi_page") and self.hoi_page.has_content():
            return True
        if self.subjectives_page.has_content():
            return True
        if hasattr(self, "family_social_page") and self.family_social_page.has_content():
            return True
        if self.objectives_page.has_content():
            return True
        if self.diagnosis_page.has_content():
            return True
        if self.plan_page.has_content():
            return True
        return False


    def _autosave(self, force: bool = False):
        if self._loading:
            return
        if not force:
            self._autosave_after_id = None

        path = self.compute_exam_path()
        if not path:
            self.status_var.set("Auto-save waiting: enter Last, First, DOB, and DOI.")
            return

        if not self._current_exam_has_content():
            self.status_var.set(f"Not auto-saving ({self.current_exam.get()}): no content yet.")
            return

        try:
            self.save_case_to_path(path)
            self.status_var.set(f"Auto-saved ({self.current_exam.get()}): {os.path.basename(path)}")
        except Exception as e:
            self.status_var.set(f"Auto-save failed: {e}")

    # ---------- Save / Load ----------
    def _apply_soap_to_ui(self, soap: dict):
        """Apply a soap dict to all SOAP pages (HOI, Subjectives, Objectives, Diagnosis, Plan, Family/Social). Does not change patient demographics."""
        soap = soap or {}
        self.hoi_page.from_dict(soap.get("hoi_struct") or {})
        self.subjectives_page.from_dict(soap.get("subjectives") or {})
        try:
            self.family_social_page.set_value(soap.get("family_social") or "")
        except Exception:
            pass
        obj_struct = soap.get("objectives_struct")
        if isinstance(obj_struct, dict):
            self.objectives_page.from_dict(obj_struct)
        else:
            self.objectives_page.from_dict({"global": {}, "blocks": []})
        dx_struct = soap.get("diagnosis_struct")
        if isinstance(dx_struct, dict):
            self.diagnosis_page.from_dict(dx_struct)
        else:
            try:
                self.diagnosis_page.set_value(soap.get("diagnosis", ""))
            except Exception:
                pass
        plan = soap.get("plan") or {}
        if isinstance(plan, dict):
            self.plan_page.load_struct(plan)
        else:
            self.plan_page.load_struct({"plan_text": str(plan or ""), "auto_enabled": False})
                # Regen MOI so regions sentence includes subjectives (HOI loads before subjectives)
        try:
            if hasattr(self, "hoi_page") and self.hoi_page is not None:
                self.hoi_page._regen_moi_now()
        except Exception:
            pass

    def apply_template_to_current_exam(self, template_dict: dict):
        """
        Merge template (partial soap) into current exam payload and refresh UI.
        Does not save to file or change exam type. Template can be { "soap": {...} } or direct soap keys.
        """
        if not template_dict:
            return
        template_soap = template_dict.get("soap")
        if template_soap is None:
            template_soap = {k: v for k, v in template_dict.items() if k != "template_name"}
        current = self.make_payload() or {}
        current_soap = current.get("soap") or {}
        merged_soap = dict(current_soap)
        for k, v in template_soap.items():
            merged_soap[k] = v
        self._apply_soap_to_ui(merged_soap)

    def _open_templates_popup(self):
        """Open a Toplevel: Save Template button + 6-column categorized template list."""
        templates_root = get_templates_root()

        popup = tk.Toplevel(self)
        popup.title("Templates")
        popup.geometry("900x420")
        popup.transient(self)
        popup.attributes("-topmost", True)

        frame = ttk.Frame(popup, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Templates", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(0, 8))

        inner = ttk.Frame(frame)
        inner.pack(fill="both", expand=True)

        column_frames: dict[str, ttk.Frame] = {}

        for col_index, (slug, display) in enumerate(TEMPLATE_CATEGORIES):
            ttk.Label(inner, text=display, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=col_index, sticky="n", padx=4, pady=(0, 4)
            )
            col_frame = ttk.Frame(inner)
            col_frame.grid(row=1, column=col_index, sticky="nsew", padx=4)
            column_frames[slug] = col_frame
            inner.columnconfigure(col_index, weight=1)

        inner.rowconfigure(1, weight=1)

        def _load_category(slug: str):
            col_frame = column_frames[slug]
            for w in col_frame.winfo_children():
                w.destroy()

            dir_path = templates_root / slug
            try:
                files = sorted(
                    f for f in os.listdir(dir_path)
                    if f.lower().endswith(".json")
                )
            except Exception:
                files = []

            if not files:
                ttk.Label(col_frame, text="(None)").pack(anchor="w", pady=(0, 2))
                return

            for fn in files:
                path = dir_path / fn
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}

                label = (data.get("template_name") or "").strip() or (
                    fn.replace(".json", "").replace("_", " ").title()
                )

                row = ttk.Frame(col_frame)
                row.pack(fill="x", pady=2)

                apply_btn = ttk.Button(
                    row,
                    text=label,
                    command=lambda d=data.copy(), p=popup: self._apply_template_and_close(d, p),
                )
                apply_btn.pack(side="left", fill="x", expand=True)

                def _make_delete_cmd(template_path: Path = path, category_slug: str = slug):
                    def _delete():
                        if not messagebox.askyesno(
                            "Delete Template",
                            f"Are you sure you want to delete this template?\n\n{template_path.name}",
                            parent=popup,
                        ):
                            return
                        try:
                            os.remove(template_path)
                        except Exception as e:
                            messagebox.showerror(
                                "Delete Template",
                                f"Could not delete template:\n{e}",
                                parent=popup,
                            )
                            return
                        _load_category(category_slug)

                    return _delete

                del_btn = ttk.Button(row, text="X", width=3, command=_make_delete_cmd())
                del_btn.pack(side="right", padx=(4, 0))

        def refresh_all_categories():
            for slug, _display in TEMPLATE_CATEGORIES:
                _load_category(slug)

        ttk.Button(
            btn_row,
            text="Save Template",
            command=lambda: self._save_current_as_template(templates_root, refresh_all_categories),
        ).pack(side="left", padx=(0, 8))

        refresh_all_categories()

        ttk.Button(frame, text="Close", command=popup.destroy).pack(pady=(12, 0))

    def _ask_template_category(self, parent) -> str | None:
        """
        Show a small dialog with a Combobox to select one of the six template categories.
        Returns the folder slug (e.g. 're_exams') or None if cancelled.
        """
        dialog = tk.Toplevel(parent)
        dialog.title("Select Template Category")
        dialog.transient(parent)
        dialog.attributes("-topmost", True)
        dialog.geometry("320x120")

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Category:").pack(anchor="w")
        display_names = [display for _slug, display in TEMPLATE_CATEGORIES]
        var = tk.StringVar(value=display_names[0])
        combo = ttk.Combobox(frame, textvariable=var, values=display_names, state="readonly", width=28)
        combo.pack(fill="x", pady=(0, 8))
        combo.current(0)

        result: list[str | None] = [None]

        def on_ok():
            try:
                idx = display_names.index(var.get())
            except ValueError:
                idx = 0
            result[0] = TEMPLATE_CATEGORIES[idx][0]
            dialog.grab_release()
            dialog.destroy()

        def on_cancel():
            result[0] = None
            dialog.grab_release()
            dialog.destroy()

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Save", command=on_ok).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Cancel", command=on_cancel).pack(side="left")

        dialog.grab_set()
        dialog.focus_set()
        combo.focus_set()
        dialog.wait_window()
        return result[0]

    def _save_current_as_template(self, templates_root: Path, refresh_all_categories):
        """
        Save current exam's SOAP content as a new template in the external templates directory.
        Prompts for template name, then shows category dropdown; writes to the selected category folder.
        """
        name = simpledialog.askstring(
            "Save Template",
            "Template name (e.g. Re-Exam F/S Mild):",
            parent=self,
        )
        if not (name or "").strip():
            return
        name = name.strip()

        slug = self._ask_template_category(self)
        if slug is None:
            return

        category_dir = templates_root / slug

        filename_slug = safe_slug(name) or "template"
        filename = f"{filename_slug}.json"
        path = category_dir / filename

        if path.exists():
            if not messagebox.askyesno(
                "Overwrite Template",
                f"A template file already exists:\n\n{path}\n\nOverwrite it?",
                parent=self,
            ):
                return

        try:
            payload = self.make_payload() or {}
            soap = payload.get("soap") or {}
            out = {"template_name": name, "soap": soap}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            refresh_all_categories()
            messagebox.showinfo("Templates", f"Saved as:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Save Template", f"Could not save template:\n{e}", parent=self)

    def _apply_template_and_close(self, template_dict: dict, popup: tk.Toplevel):
        self.apply_template_to_current_exam(template_dict)
        try:
            popup.destroy()
        except Exception:
            pass

    def make_payload(self) -> dict:
        exam_date = normalize_mmddyyyy(self.exam_date_var.get()) or today_mmddyyyy()
        last = self.last_name_var.get()
        first = self.first_name_var.get()
        display = to_last_first(last, first)

        subj_struct = self.subjectives_page.to_dict()

        try:
            #print("SAVE uses HOIPage id:", id(self.hoi_page))
            hoi_struct = self.hoi_page.to_dict() or {}
             # ✅ Add per-mode manual text into hoi_struct for PDF saving/printing
            hoi_struct["manual_initial"] = self.hoi_page.manual_initial_var.get()
            hoi_struct["manual_reexam"]  = self.hoi_page.manual_reexam_var.get()
            hoi_struct["manual_rof"]     = self.hoi_page.manual_rof_var.get()
            hoi_struct["manual_final"]   = self.hoi_page.manual_final_var.get()
            #print("DEBUG HOI ROF:", hoi_struct.get("rof"))
        except Exception:
            hoi_struct = {}

        obj_text = ""
        obj_struct = {"global": {}, "blocks": []}

        try:
            obj_text = self.objectives_page.get_value() or ""
        except Exception:
            obj_text = ""

        try:
            raw = self.objectives_page.to_dict() or {}
        except Exception:
            raw = {}

        if isinstance(raw, dict):
            g = raw.get("global")
            if g is None:
                g = raw.get("globals")
            obj_struct["global"] = g if isinstance(g, dict) else {}
            b = raw.get("blocks")
            obj_struct["blocks"] = b if isinstance(b, list) else []
        else:
            obj_struct = {"global": {}, "blocks": []}

        payload =  {
            "schema_version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "exam": self.current_exam.get(),
            "patient": {
                "last_name": last,
                "first_name": first,
                "display_name": display,
                "dob": self.dob_var.get(),
                "doi": self.doi_var.get(),
                "exam_date": exam_date,
                "claim": self.claim_var.get(),
                "provider": self.provider_var.get(),
            },
            "soap": {
                "hoi_struct": hoi_struct,
                "subjectives": subj_struct,
                "family_social": self.family_social_page.get_value() if hasattr(self, "family_social_page") else "",
                "objectives": obj_text,
                "objectives_struct": obj_struct,
                "diagnosis_struct": self.diagnosis_page.to_dict(),
                "diagnosis": self.diagnosis_page.get_value(),  # optional backward compat
                "plan": self.plan_page.get_struct(),
            }
        }
    
        # ✅ Ensure stable patient_id
        payload.setdefault("patient", {})
        payload["patient"]["patient_id"] = self._ensure_current_patient_id()

        return payload      
    

    def save_case_to_path(self, path: str | Path):
        path = Path(path)
        payload = self.make_payload()

        _find_sets(payload)

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        os.replace(tmp_path, path)

        self.current_case_path = str(path)
        self.write_settings({
            "last_case_path": str(path),
            "last_exam": self.current_exam.get()       
        })

        try:
            self.propagate_demographics_to_all_exams()
        except Exception:
            pass


    def save_case_now(self):
        """
        Save the current exam to the patient_id-based auto path.
        No Save-As dialog. If we can't compute the path, show an error and stop.
        """

        # Ensure patient id exists so we can compute a path (no Save As dialog)
        self._ensure_current_patient_id()
        computed = self.compute_exam_path()
        if not computed:
            messagebox.showerror("Save Failed", "Could not compute save path.")
            return

        try:
            self.save_case_to_path(computed)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not save exam.\n\n{e}")
            return

        messagebox.showinfo("Saved", f"Saved ({self.current_exam.get()}):\n{computed}")



    def load_case_manual(self):
        initialdir = str(YEAR_CASES_ROOT)

        patient_root = self.get_current_patient_root()
        if patient_root:
            exams_dir = os.path.join(patient_root, PATIENT_SUBDIR_EXAMS)
            if os.path.isdir(exams_dir):
                initialdir = exams_dir

        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=initialdir,
            title="Open Saved Exam..."
        )
        if not path:
            return

        try:
            self.load_case_from_path(path)
            messagebox.showinfo("Loaded", f"Loaded:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load:\n{e}")



    def load_case_from_path(self, path: str):
        self._loading = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            file_exam = (payload.get("exam") or "").strip()
            if file_exam:
                # If this exam isn't in the dynamic list yet, add it and rebuild tabs
                if file_exam.lower() not in {e.lower() for e in self.exams}:
                    self.exams.append(file_exam)
                    self._save_dynamic_exams_for_patient()
                    self._rebuild_exam_nav_buttons()

                self.current_exam.set(file_exam)
                self._refresh_exam_button_styles()


            patient = payload.get("patient", {}) or {}
            # ✅ Restore stable patient_id from file
            pid = (patient.get("patient_id") or "").strip()
            if pid:
                self.current_patient_id = pid

            self.last_name_var.set(patient.get("last_name", ""))
            self.first_name_var.set(patient.get("first_name", ""))
            self.dob_var.set(patient.get("dob", ""))
            self.doi_var.set(patient.get("doi", ""))

            self.exam_date_var.set(normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy())
            self.claim_var.set(patient.get("claim", ""))
            
            prov = (patient.get("provider") or "").strip()
            self.provider_var.set(prov if prov else "")
            
            soap = payload.get("soap", {}) or {}
            self._apply_soap_to_ui(soap)

            self.current_case_path = path
            self.write_settings({"last_case_path": path, "last_exam": self.current_exam.get()})

            self._rebuild_exam_nav_buttons()

            self._apply_exam_color_theme()

            self._set_current_doc_label()

            # ✅ refresh Docs timeline so it shows ALL saved exams immediately
            try:
                self.tk_docs_page.refresh()
            except Exception:
                pass

            # After loading patient_id + names, show that patient's alerts file
            self.after_idle(self.show_current_patient_alerts_popup)

        finally:
            self._loading = False
                   
    # ---------- Reset ----------
    def clear_exam_content_only(self):
        """
        Clears all exam-related UI fields without touching
        patient demographics or app-level state.
        Safe for Start New Case.
        """

        # HOI
        try:
            self.hoi_page.reset()
        except Exception:
            try:
                self.hoi_page.from_dict({})
            except Exception:
                pass

        # Subjectives
        try:
            self.subjectives_page.reset()
        except Exception:
            try:
                self.subjectives_page.from_dict({})
            except Exception:
                pass

        # ✅ NEW: Family/Social History
        try:
            self.family_social_page.reset()
        except Exception:
            try:
                self.family_social_page.set_value("")
            except Exception:
                pass

        
        # Objectives
        try:
            self.objectives_page.reset()
        except Exception:
            try:
                self.objectives_page.from_dict({})
            except Exception:
                pass

        # Diagnosis
        try:
            self.diagnosis_page.reset()
        except Exception:
            try:
                self.diagnosis_page.from_dict({})
            except Exception:
                pass

        # Plan
        try:
            self.plan_page.reset()
        except Exception:
            try:
                self.plan_page.load_struct({
                    "auto_enabled": True,
                    "plan_text": ""
                })
            except Exception:
                pass
        

    def reset_current_exam(self):
        if not messagebox.askyesno("Reset Exam", f"Clear ONLY the current exam ({self.current_exam.get()})?"):
            return
        self.clear_exam_content_only()
        self.current_case_path = None
        self.status_var.set(f"{self.current_exam.get()} cleared (not deleted on disk).")

    def reset_entire_form(self):
        if not messagebox.askyesno("RESET ENTIRE FORM", "Clear EVERYTHING (patient info + all sections) and start blank?\n\nYou can add exams with + Initial, + Re-Exam, etc."):
            return
        self.reset_entire_form_ui_only()

    def reset_entire_form_ui_only(self):
        self._loading = True
        try:
            self.last_name_var.set("")
            self.first_name_var.set("")
            self.dob_var.set("")
            self.doi_var.set("")
            self.exam_date_var.set(today_mmddyyyy())
            self.claim_var.set("")
            self.provider_var.set("")

            first_exam = self.exams[0] if self.exams else ""
            self.current_exam.set(first_exam)
            self._refresh_exam_button_styles()

            self.clear_exam_content_only()
            self.current_case_path = None

            self.show_page("HOI History")
            self.status_var.set("Ready. (New blank form)")
        finally:
            self._loading = False

    # ---------- PDF export ----------
    # (Your existing export methods can remain as-is; unchanged for brevity.)
    # Keep your pdf_export wiring exactly the same.

    def _ensure_reportlab(self) -> bool:
        if REPORTLAB_OK:
            return True
        messagebox.showerror(
            "Missing dependency: reportlab",
            "PDF export requires the 'reportlab' package.\n\nInstall it with:\n"
            "python -m pip install reportlab\n\n"
            "If you have multiple Pythons installed, run:\n"
            r'& "C:\Program Files\Python313\python.exe" -m pip install reportlab'
        )
        return False

    def export_current_exam_to_pdf(self):
        if not self._ensure_reportlab():
            return

        patient_root = self.get_current_patient_root()
        initialdir = str(YEAR_CASES_ROOT)
        if patient_root:
            ensure_patient_dirs(patient_root)
            initialdir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)

        display = to_last_first(self.last_name_var.get(), self.first_name_var.get()) or "Patient"
        dob = self.dob_var.get().strip()
        doi = self.doi_var.get().strip()

        default_name = (
            f"{safe_slug(self.current_exam.get())}_"
            f"{safe_slug(display)}_DOB_{safe_slug(dob)}_DOI_{safe_slug(doi)}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=default_name,
            initialdir=initialdir,
            title="Save CURRENT Exam PDF As..."
        )
        if not path:
            return

        payload = self.make_payload() or {}
        build_combined_pdf(path, [payload])

        # ✅ Auto-save/replace into Doc Vault -> pdfs/
        try:
            patient_root = self.get_current_patient_root()
            if patient_root:
                exam = self.current_exam.get()
                # stable vault filename per exam:
                #vault_name = f"{safe_slug(exam)}.pdf"
                exam = self.current_exam.get()

                # use demographics visit date (normalized), fallback to today
                date_str = normalize_mmddyyyy(self.exam_date_var.get()) or today_mmddyyyy()

                # deterministic name: "02_12_2026__re_exam_1.pdf"
                exam_slug = safe_slug(exam)
                date_slug = safe_slug(date_str)
                vault_name = f"{date_slug}__{exam_slug}.pdf"

                # (optional but recommended) delete any older variants for this exam in the vault
                vault_dir = os.path.join(patient_root, "vault", "pdfs")
                try:
                    if os.path.isdir(vault_dir):
                        for fn in os.listdir(vault_dir):
                            if fn.lower().endswith(f"__{exam_slug}.pdf"):
                                try:
                                    os.remove(os.path.join(vault_dir, fn))
                                except Exception:
                                    pass
                except Exception:
                    pass

                vault_path = upsert_vault_file(patient_root, "pdfs", path, vault_name)

                # If user is on Doc Vault page and viewing pdfs, refresh list
                if getattr(self.current_page, "get", lambda: "")() == "Doc Vault":
                    try:
                        if getattr(self.doc_vault_page.folder_panel, "folder_key", None) == "pdfs":
                            self.doc_vault_page.refresh_current_folder()
                    except Exception:
                        pass

                self.status_var.set(f"PDF saved + updated in Vault: {os.path.basename(vault_path)}")
        except Exception as e:
            print("Vault upsert failed:", e)


        self.last_exam_pdf_paths[self.current_exam.get()] = path
        self.write_settings({
            "last_exam_pdfs": self.last_exam_pdf_paths,
            "last_all_exams_pdf": self.last_all_exams_pdf_path
        })
        messagebox.showinfo("Success", f"PDF saved:\n{path}")

    def export_all_exams_to_one_pdf(self):
        if not self._ensure_reportlab():
            return

        patient_root = self.get_current_patient_root()
        if not patient_root:
            messagebox.showinfo("PDF", "Enter Last, First, DOB, and DOI first.")
            return

        ensure_patient_dirs(patient_root)
        pdf_dir = os.path.join(patient_root, PATIENT_SUBDIR_PDFS)
        os.makedirs(pdf_dir, exist_ok=True)

        display = to_last_first(self.last_name_var.get(), self.first_name_var.get()) or "Patient"
        dob = (self.dob_var.get() or "").strip()
        doi = (self.doi_var.get() or "").strip()

        default_name = (
            f"ALL_EXAMS_{safe_slug(display)}_DOB_{safe_slug(dob)}_DOI_{safe_slug(doi)}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=default_name,
            initialdir=pdf_dir,
            title="Save ALL Exams to ONE PDF As..."
        )
        if not path:
            return

        # Preserve current UI state
        orig_exam = self.current_exam.get()
        orig_page = self.current_page.get()
        orig_case_path = self.current_case_path

        payloads: list[dict] = []
        skipped: list[str] = []

        # Ensure current exam gets saved first (so disk-based exams are up to date)
        try:
            self._autosave(force=True)
        except Exception:
            pass

        try:
            # Build each exam payload using the same normalization as Export Current Exam
            for exam in self.exams:
                exam_path = self.compute_exam_path(exam)
                if not exam_path or not os.path.exists(exam_path):
                    skipped.append(exam)
                    continue

                try:
                    # Load that exam into the UI (same mechanism used elsewhere)
                    self.load_case_from_path(exam_path)

                    # Now make the payload the SAME way Export Current does
                    payload = self.make_payload() or {}
                    if payload:
                        payloads.append(payload)
                    else:
                        skipped.append(f"{exam} (empty payload)")
                except Exception as e:
                    skipped.append(f"{exam} (error: {e})")

            if not payloads:
                messagebox.showinfo(
                    "Export All Exams",
                    "No saved exams found to export.\n\n"
                    "Tip: Save at least one exam first (Save Exam Now)."
                )
                return

            # Build combined PDF
            build_combined_pdf(path, payloads)

            self.last_all_exams_pdf_path = path
            self.write_settings({
                "last_exam_pdfs": self.last_exam_pdf_paths,
                "last_all_exams_pdf": self.last_all_exams_pdf_path
            })

            msg = f"All-exams PDF saved:\n{path}"
            if skipped:
                msg += "\n\nSkipped:\n- " + "\n- ".join(skipped)

            if messagebox.askyesno("Success", msg + "\n\nOpen it now?"):
                open_with_default_app(path)

        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not create the combined PDF:\n\n{e}")

        finally:
            # Restore prior UI state as best as possible
            try:
                # Go back to the original exam if we can
                if orig_exam in self.exams:
                    self.current_exam.set(orig_exam)
                    self._refresh_exam_button_styles()

                    # If we had a file for it, load it back
                    orig_path = self.compute_exam_path(orig_exam)
                    if orig_path and os.path.exists(orig_path):
                        try:
                            self.load_case_from_path(orig_path)
                        except Exception:
                            pass

                # Restore page view
                if orig_page in self.pages:
                    self.show_page(orig_page)

                self.current_case_path = orig_case_path
                self._apply_exam_color_theme()
            except Exception:
                pass


    # ---------- Start New Case ----------
    def start_new_case(self):
        try:
            self._autosave(force=True)
        except Exception:
            pass

        if not messagebox.askyesno(
            "Start New Case",
            "This will clear the on-screen form so you can start a NEW case.\n\n"
            "It will NOT delete any saved JSON files or PDFs.\n\n"
            "Continue?"
        ):
            return

        self.reset_entire_form_ui_only()
        self.current_case_path = None
        self.last_exam_pdf_paths = {e: "" for e in self.exams}
        self.last_all_exams_pdf_path = ""
        self.status_var.set("New case started. Previous cases/files are unchanged.")
        self.current_patient_id = None
        self._ensure_current_patient_id()
        self.after_idle(self.show_current_patient_alerts_popup)


if __name__ == "__main__":
    ensure_year_root()
    App().mainloop()


