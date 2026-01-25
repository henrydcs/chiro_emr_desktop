# chiro_app.py
import json
import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from diagnosis_page import DiagnosisPage
from doc_vault_page import DocVaultPage
import re
from HOI import HOIPage
from plan_page import PlanPage
from pathlib import Path

from paths import patients_dir

#Git Hub to Work Between Computers

#Start of Day
#git pull

#End of Day Push
# git status
# git add .
# git commit -m "End of day updates"
# git push

#And remember to make sure to be in the REPO FOLDER (OFFICE COMPUTER or HOME COMPUTER):
#...\EMRchiropractic\chiro_emr_desktop OR EMR_Code\chiro_emr_desktop
#If not in ROOT folder, make sure to "cd chiro_emr_desktop" without the quotes


# ----------- OPTIONAL: Pillow (Tkinter logo) -----------
PIL_OK = False
try:
    from PIL import Image, ImageTk  # type: ignore
    PIL_OK = True
except Exception:
    PIL_OK = False

from pdf_export import REPORTLAB_OK, build_combined_pdf
from config import (
    UI_PAGES,
    EXAMS,
    EXAM_COLORS,
    REGION_LABELS,
    SETTINGS_PATH,
    AUTOSAVE_DEBOUNCE_MS,
    LOGO_PATH, CLINIC_NAME, CLINIC_ADDR, CLINIC_PHONE_FAX,
    YEAR_CASES_ROOT, NEXT_YEAR_CASES_ROOT,
    PATIENT_SUBDIR_EXAMS, PATIENT_SUBDIR_PDFS,
)

from utils import (
    ensure_year_root,
    safe_slug,
    normalize_mmddyyyy, today_mmddyyyy,
    get_patient_root_dir, ensure_patient_dirs,
    to_last_first
)

# Pages
from subjectives import SubjectivesPage
from objectives import ObjectivesPage
from ui_pages import TextPage

EXAM_INDEX_FILENAME = "_exam_index.json"

# Keep config.EXAMS as your base list
BASE_EXAMS = list(EXAMS)


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
    # prefix example: "Re-Exam" or "Review of Findings"
    pat = re.compile(
        rf"^\s*{re.escape(prefix)}\s+(\d+)\s*$",
        re.IGNORECASE
    )
    nums: list[int] = []
    for name in existing:
        m = pat.match((name or "").strip())
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass
    return (max(nums) + 1) if nums else 1


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_year_root()       

        self._start_blank = "--new" in sys.argv

        self.title("PI Exams – SOAP Builder")
        self.geometry("1060x930")

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
        self.provider_var = tk.StringVar(value="")

        self.current_exam = tk.StringVar(value="Initial")
        self.current_page = tk.StringVar(value="HOI History")

        self.exams: list[str] = list(BASE_EXAMS)  # dynamic exam list (Initial, Re-Exam 1, ROF 1, etc.)

        self._autosave_after_id = None
        self.current_case_path: str | None = None
        self._loading = False

        self.last_exam_pdf_paths = {e: "" for e in EXAMS}
        self.last_all_exams_pdf_path = ""

        self._mousewheel_target = None
        self._tk_logo_image = None

        self._build_ui()
        self._wire_autosave_triggers()

        # Mousewheel scroll routing (Subjectives canvas)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel_linux_up)
        self.bind_all("<Button-5>", self._on_mousewheel_linux_down)

        # Start behavior
        if not self._start_blank:
            self.after(80, self.autoload_last_case_on_startup)
        else:
            self.status_var.set("Ready. (New blank form)")

    def _rebuild_exam_nav_buttons(self):
        # Remove old exam buttons only (leave label + add buttons alone)
        for name, btn in list(self.exam_buttons.items()):
            try:
                btn.destroy()
            except Exception:
                pass
        self.exam_buttons.clear()

        # Ensure current patient’s dynamic exams are loaded if we have a patient
        # (only do this once patient info exists; otherwise keep BASE_EXAMS)
        if self.get_current_patient_root():
            self.exams = self._load_dynamic_exams_for_patient()
        else:
            self.exams = list(BASE_EXAMS)

        # Recreate buttons (insert before the + buttons, which we pack on the right)
        for exam in self.exams:
            label = exam
            if exam.startswith("Review of Findings"):
                label = exam.replace("Review of Findings", "ROF", 1)

            btn = ttk.Button(
                self.exam_nav,
                text=label,
                command=lambda e=exam: self.switch_exam(e)
            )

            btn.pack(side="left", padx=4)
            self.exam_buttons[exam] = btn


        self._refresh_exam_button_styles()
        self._apply_exam_color_theme()

    def _ensure_patient_for_dynamic_exam(self) -> bool:
        if self.get_current_patient_root():
            return True
        messagebox.showinfo("Add Exam", "Enter Last, First, DOB, and DOI first (so the new exam can be saved under the patient).")
        return False

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
        self._refresh_exam_button_styles()
        self._apply_exam_color_theme()

        if copy_current:
            # Save the CURRENT on-screen content under the NEW exam name/path
            new_path = self.compute_exam_path(exam_name)
            if new_path:
                try:
                    self.save_case_to_path(new_path)
                    self.status_var.set(f"{exam_name} created (copied from previous exam).")
                except Exception as e:
                    self.status_var.set(f"{exam_name} created, but copy-save failed: {e}")
        else:
            self.clear_exam_content_only()
            self.current_case_path = None
            self.status_var.set(f"{exam_name} created (new blank exam).")



    
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

        self.last_exam_pdf_paths[exam] = path
        self.write_settings({
            "last_exam_pdfs": self.last_exam_pdf_paths,
            "last_all_exams_pdf": self.last_all_exams_pdf_path
        })
        if messagebox.askyesno("PDF Saved", f"PDF overwritten/saved:\n{path}\n\nOpen it now?"):
            open_with_default_app(path)



    # ---------- Providers for HOI ----------

    def _patient_info_from_demo(self) -> dict:
        return {
            "first": self.first_name_var.get().strip(),
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

        # =========================
        # Top-level 2-column layout
        # LEFT: your normal UI
        # RIGHT: live preview (starts at top of window)
        # =========================
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        #left_root = ttk.Frame(main)
        #left_root.pack(side="left", fill="both", expand=True)

        left_root = ttk.Frame(main, width=760)
        left_root.pack(side="left", fill="both", expand=True)
        left_root.pack_propagate(False)

        right_root = ttk.Frame(main)
        right_root.pack(side="right", fill="both", expand=True)


        #right_root = ttk.Frame(main, width=820)
        #right_root.pack(side="right", fill="y")
        #right_root.pack_propagate(False)
        #right_root.pack(side="right", fill="both", expand=True)


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
        # --- Add Exam buttons moved to Demographics header row (right side) ---
        self.add_final_btn = ttk.Button(demo_top, text="+ Final", command=self.add_final, style="AddExam.TButton")
        self.add_reexam_btn = ttk.Button(demo_top, text="+ Re-Exam", command=self.add_reexam, style="AddExam.TButton")
        self.add_rof_btn = ttk.Button(demo_top, text="+ ROF", command=self.add_rof, style="AddExam.TButton")
        self.add_rof_btn.pack(in_=demo_top, side="right", padx=(4, 0))
        self.add_reexam_btn.pack(in_=demo_top, side="right", padx=(4, 0))
        self.add_final_btn.pack(in_=demo_top, side="right", padx=(4, 0))


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

        ttk.Label(self.exam_nav, text="Exam:").pack(side="left", padx=(0, 8))
        self.exam_buttons: dict[str, ttk.Button] = {}

        # Add buttons row tools (right side)style="AddExam.TButton"
        # self.add_final_btn  = ttk.Button(self.exam_nav, text="+ Final", command=self.add_final, style="AddExam.TButton")

        # self.add_reexam_btn = ttk.Button(
        #     self.exam_nav,
        #     text="+ Re-Exam",
        #     command=self.add_reexam,
        #     style="AddExam.TButton"
        # )

        # self.add_rof_btn = ttk.Button(
        #     self.exam_nav,
        #     text="+ ROF",
        #     command=self.add_rof,
        #     style="AddExam.TButton"
        # )
        
        # build once
        self._rebuild_exam_nav_buttons()

        # pack add buttons at end
        #self.add_rof_btn.pack(side="right", padx=(4, 0))
        #self.add_reexam_btn.pack(side="right", padx=(4, 0))
        #self.add_final_btn.pack(side="right", padx=(4, 0))

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

        self.page_buttons: dict[str, ttk.Button] = {}
        for page in UI_PAGES:
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

        self.hoi_preview_scroll.pack(side="right", fill="y")
        self.hoi_preview_text.pack(side="left", fill="both", expand=True)


        # =========================
        # Create pages (unchanged logic, same widgets)
        # =========================
        # Keep HOIPage created so saving/PDF still works,
        # but it will no longer be shown as a "page" button.
        self.hoi_page = HOIPage(self.content, self.schedule_autosave)

        self.subjectives_page = SubjectivesPage(self.content, self.schedule_autosave)
        self.objectives_page = ObjectivesPage(self.content, self.schedule_autosave)
        self.diagnosis_page = DiagnosisPage(self.content, self.schedule_autosave)

        self.plan_page = PlanPage(self.content, on_change=self.schedule_autosave)

        self.doc_vault_page = DocVaultPage(
            self.content,
            self.schedule_autosave,
            get_patient_root_fn=self.get_current_patient_root
        )

        # Only pages you want in the LEFT nav go here:
        self.pages = {
            "HOI History": self.hoi_page,
            "Subjectives": self.subjectives_page,
            "Objectives": self.objectives_page,
            "Diagnosis": self.diagnosis_page,
            "Plan": self.plan_page,
            "Document Vault": self.doc_vault_page,
        }

        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        # Default page now (since HOI History is gone)
        self.show_page("Subjectives")

               


        # Wire HOI providers (this is the critical part for your first-name + regions)
        self.hoi_page.set_regions_provider(self._regions_from_subjectives)
        self.hoi_page.set_patient_provider(self._patient_info_from_demo)

        # self.pages = {
        #     "HOI History": self.hoi_page,
        #     "Subjectives": self.subjectives_page,
        #     "Objectives": self.objectives_page,
        #     "Diagnosis": self.diagnosis_page,
        #     "Plan": self.plan_page,
        #     "Document Vault": self.doc_vault_page,           
        # }

        # for page in self.pages.values():
        #     page.grid(row=0, column=0, sticky="nsew")
       
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

        self._apply_demographics_visibility()



    # ---------- Page switching ----------

    def show_page(self, page_name: str):
        if page_name not in self.pages:
            return
        self.current_page.set(page_name)
        self.pages[page_name].tkraise()
        self._refresh_page_button_styles()


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
                try:
                    self.objectives_page.set_value("")
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




    def switch_exam(self, exam_name: str):
        if exam_name == self.current_exam.get():
            return

        self._autosave(force=True)

        self.current_exam.set(exam_name)
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


    def _exam_index_path(self) -> str | None:
        patient_root = self.get_current_patient_root()
        if not patient_root:
            return None
        ensure_patient_dirs(patient_root)
        exams_dir = os.path.join(patient_root, PATIENT_SUBDIR_EXAMS)
        os.makedirs(exams_dir, exist_ok=True)
        return os.path.join(exams_dir, EXAM_INDEX_FILENAME)

    def _load_dynamic_exams_for_patient(self) -> list[str]:
        """
        Returns patient-specific exam list if index exists, else BASE_EXAMS.
        """
        p = self._exam_index_path()
        if not p or not os.path.exists(p):
            return list(BASE_EXAMS)

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            lst = data.get("exams") or []
            if not isinstance(lst, list):
                return list(BASE_EXAMS)

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

            # Always ensure BASE_EXAMS exist (so you never lose core tabs)
            for b in BASE_EXAMS:
                if b.lower() not in seen:
                    out.insert(len(out), b)

            return out
        except Exception:
            return list(BASE_EXAMS)

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

    def get_current_patient_root(self) -> str | None:
        return get_patient_root_dir(
            self.last_name_var.get(),
            self.first_name_var.get(),
            self.dob_var.get(),
            self.doi_var.get(),
        )

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

        # Load patient-specific dynamic exams (if patient data exists already)
        self._rebuild_exam_nav_buttons()

        last_exam = (settings.get("last_exam") or "").strip()
        if last_exam and last_exam.lower() in {e.lower() for e in self.exams}:
            self.current_exam.set(last_exam)
            self._refresh_exam_button_styles()


        last_path = settings.get("last_case_path")
        if last_path and os.path.exists(last_path):
            try:
                self.load_case_from_path(last_path)
                self.status_var.set(f"Loaded last file: {os.path.basename(last_path)}")
            except Exception as e:
                self.status_var.set(f"Could not load last file: {e}")
        else:
            self.status_var.set("Ready. (No last file found)")

        pdf_map = settings.get("last_exam_pdfs", {})
        if isinstance(pdf_map, dict):

            # Safety: ensure dynamic exams list exists
            if not hasattr(self, "exams") or not self.exams:
                self.exams = list(BASE_EXAMS)

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

    def _current_exam_has_content(self) -> bool:
        if hasattr(self, "hoi_page") and self.hoi_page.has_content():
            return True
        if self.subjectives_page.has_content():
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

    def make_payload(self) -> dict:
        exam_date = normalize_mmddyyyy(self.exam_date_var.get()) or today_mmddyyyy()
        last = self.last_name_var.get()
        first = self.first_name_var.get()
        display = to_last_first(last, first)

        subj_struct = self.subjectives_page.to_dict()

        try:
            hoi_struct = self.hoi_page.to_dict() or {}
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

        return {
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
                "objectives": obj_text,
                "objectives_struct": obj_struct,
                "diagnosis_struct": self.diagnosis_page.to_dict(),
                "diagnosis": self.diagnosis_page.get_value(),  # optional backward compat
                "plan": self.plan_page.get_struct(),
            }
        }
      
    

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



    def save_case_now(self):
        # 1) Try the normal computed path first (your usual "Save Exam Now")
        computed = self.compute_exam_path()
        if computed:
            try:
                self.save_case_to_path(computed)
            except Exception as e:
                messagebox.showerror("Save Failed", f"Could not save exam.\n\n{e}")
                return

            messagebox.showinfo(
                "Saved",
                f"Saved ({self.current_exam.get()}):\n{computed}"
            )
            return

        # 2) If we couldn't compute a path (missing name/date/etc), fall back to Save As...
        default_name = f"{safe_slug(self.current_exam.get())}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile=default_name,
            initialdir=str(YEAR_CASES_ROOT),
            title="Save Exam As..."
        )
        if not path:
            return

        try:
            self.save_case_to_path(path)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not save exam.\n\n{e}")
            return

        messagebox.showinfo("Saved", f"Saved:\n{path}")


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
            self.last_name_var.set(patient.get("last_name", ""))
            self.first_name_var.set(patient.get("first_name", ""))
            self.dob_var.set(patient.get("dob", ""))
            self.doi_var.set(patient.get("doi", ""))

            self.exam_date_var.set(normalize_mmddyyyy(patient.get("exam_date", "")) or today_mmddyyyy())
            self.claim_var.set(patient.get("claim", ""))
            self.provider_var.set(patient.get("provider", ""))

            soap = payload.get("soap", {}) or {}

            self.hoi_page.from_dict(soap.get("hoi_struct") or {})
            self.subjectives_page.from_dict(soap.get("subjectives") or {})

            obj_struct = soap.get("objectives_struct")
            if isinstance(obj_struct, dict):
                self.objectives_page.from_dict(obj_struct)
            else:
                self.objectives_page.set_value(soap.get("objectives", ""))

            dx_struct = soap.get("diagnosis_struct")
            if isinstance(dx_struct, dict):
                self.diagnosis_page.from_dict(dx_struct)
            else:
                # backward compat
                try:
                    self.diagnosis_page.set_value(soap.get("diagnosis", ""))
                except Exception:
                    pass

            # -------- Plan (structured) --------
            plan = (soap.get("plan", {}) or {})
            if isinstance(plan, dict):
                self.plan_page.load_struct(plan)
            else:
                # Backward compat: old cases stored plan as a string
                self.plan_page.load_struct({"plan_text": str(plan or ""), "auto_enabled": False})


            self.current_case_path = path
            self.write_settings({"last_case_path": path, "last_exam": self.current_exam.get()})

            self._rebuild_exam_nav_buttons()

            self._apply_exam_color_theme()
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
        if not messagebox.askyesno("RESET ENTIRE FORM", "Clear EVERYTHING (patient info + all sections) and return to Initial?"):
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

            self.current_exam.set("Initial")
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
                if orig_exam in EXAMS:
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


if __name__ == "__main__":
    ensure_year_root()
    App().mainloop()


