# config.py
import os
from pathlib import Path
from paths import get_data_dir, patients_dir



from env_config import get_env

PROVIDER_NAME = get_env("PROVIDER_NAME", "")
CLINIC_NAME = get_env("CLINIC_NAME", "Default Clinic Name")
CLINIC_ADDR = get_env("CLINIC_ADDR", "")
CLINIC_PHONE_FAX = get_env("CLINIC_PHONE_FAX", "")



# ----------------- PROJECT ROOT -----------------
BASE_DIR = os.path.dirname(__file__)

# ----------------- ASSETS -----------------
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "clinic_logo.png")  # PNG


# ----------------- CASE STORAGE (PHI-safe, external) -----------------
ACTIVE_YEAR = 2026

PATIENTS_ROOT: Path = patients_dir()

PATIENTS_ID_ROOT: Path = PATIENTS_ROOT / "id_cases"
PATIENTS_ID_ROOT.mkdir(parents=True, exist_ok=True)

YEAR_CASES_ROOT: Path = PATIENTS_ROOT / f"{ACTIVE_YEAR}cases"
NEXT_YEAR_CASES_ROOT: Path = PATIENTS_ROOT / f"{ACTIVE_YEAR + 1}cases"

YEAR_CASES_ROOT.mkdir(parents=True, exist_ok=True)
NEXT_YEAR_CASES_ROOT.mkdir(parents=True, exist_ok=True)

# App settings stored at year root (external data dir)
SETTINGS_PATH: Path = get_data_dir() / "_app_settings.json"


AUTOSAVE_DEBOUNCE_MS = 600


# ----------------- NAV / UI PAGES -----------------
# IMPORTANT: Define PAGES only ONCE (do NOT redefine later), or you will overwrite HOI History.
UI_PAGES = [
    "HOI History",
    "Subjectives",
    "Objectives",
    "Diagnosis",
    "Plan",
    "Doc Vault",    
]

# ----------------- EXAMS -----------------
EXAMS = ["Initial", "Re-Exam", "Review of Findings", "Final Exam"]

EXAM_COLORS = {
    "Initial": {"bg": "#E3F2FD", "accent": "#1E88E5"},
    "Re-Exam 1": {"bg": "#E8F5E9", "accent": "#43A047"},
    "Re-Exam 2": {"bg": "#FFFDE7", "accent": "#F9A825"},
    "Final Exam": {"bg": "#FCE4EC", "accent": "#C2185B"},
}

# ----------------- UI OPTIONS -----------------
PAIN_DESCRIPTORS = [
    "Achy", "Sharp", "Tension", "Dull", "Burning", "Throbbing",
    "Stabbing", "Shooting", "Tight", "Pressure", "Cramping"
]

RADIC_SYMPTOMS = ["None", "Numbness", "Tingling", "Weakness", "Sypmtoms", "Discomfort", "Pain"]

RADIC_LOCATIONS = [
    "(select)",
    "Left shoulder", "Right shoulder",    
    "Left arm", "Right arm",
    "Left forearm", "Right forearm",
    "Left hand", "Right hand", 
    "Left fingers", "Right fingers", "---------------",
    "Left buttocks", "Right buttocks",
    "Left hip", "Right hip",
    "Left thigh", "Right thigh",
    "Left knee", "Right knee",
    "Left leg", "Right leg", "-----------------",
    "Left ankle", "Right ankle",
    "Left foot", "Right foot", 
    "Left toes", "Right toes", 
]

REGION_OPTIONS = [
    "(none)",
    "CS", "TS", "LS",

    "R_SHOULDER", "L_SHOULDER", "BL_SHOULDER",
    "R_ELBOW", "L_ELBOW", "BL_ELBOW",
    "R_WRIST", "L_WRIST", "BL_WRIST",

    "R_HIP", "L_HIP", "BL_HIP",
    "R_KNEE", "L_KNEE", "BL_KNEE",
    "R_ANKLE", "L_ANKLE", "BL_ANKLE",
]



REGION_LABELS = {
    "CS": "Cervical Spine",
    "TS": "Thoracic Spine",
    "LS": "Lumbar Spine",

    "R_SHOULDER": "Right Shoulder",
    "L_SHOULDER": "Left Shoulder",
    "BL_SHOULDER": "Bilateral Shoulders",

    "R_ELBOW": "Right Elbow",
    "L_ELBOW": "Left Elbow",
    "BL_ELBOW": "Bilateral Elbows",

    "R_WRIST": "Right Wrist",
    "L_WRIST": "Left Wrist",
    "BL_WRIST": "Bilateral Wrists",

    "R_HIP": "Right Hip",
    "L_HIP": "Left Hip",
    "BL_HIP": "Bilateral Hips",

    "R_KNEE": "Right Knee",
    "L_KNEE": "Left Knee",
    "BL_KNEE": "Bilateral Knees",

    "R_ANKLE": "Right Ankle",
    "L_ANKLE": "Left Ankle",
    "BL_ANKLE": "Bilateral Ankles",
}


REGION_MUSCLES = {
    "CS": [
        "Upper trapezius",
        "Levator scapulae",
        "Cervical paraspinals",
        "SCM",
        "Scalenes",
        "Suboccipitals",
        "Rhomboids (upper)",
    ],
    "TS": [
        "Thoracic paraspinals",
        "Mid trapezius",
        "Lower trapezius",
        "Rhomboids",
        "Latissimus dorsi",
        "Serratus anterior",
        "Intercostals",
    ],
    "LS": [
        "Lumbar paraspinals",
        "Quadratus lumborum",
        "Gluteus medius",
        "Gluteus maximus",
        "Piriformis",
        "Hip flexors (iliopsoas)",
        "Hamstrings (proximal)",
    ],
    "RUE": [
        "Deltoid",
        "Biceps",
        "Triceps",
        "Forearm flexors",
        "Forearm extensors",
        "Rotator cuff",
        "Pectoralis",
    ],
    "LUE": [
        "Deltoid",
        "Biceps",
        "Triceps",
        "Forearm flexors",
        "Forearm extensors",
        "Rotator cuff",
        "Pectoralis",
    ],
    "RLE": [
        "Gluteals",
        "Quadriceps",
        "Hamstrings",
        "Calf (gastrocnemius/soleus)",
        "Tibialis anterior",
        "Peroneals",
    ],
    "LLE": [
        "Gluteals",
        "Quadriceps",
        "Hamstrings",
        "Calf (gastrocnemius/soleus)",
        "Tibialis anterior",
        "Peroneals",
    ],
}

# ----------------- PATIENT CHART SUBFOLDERS -----------------
PATIENT_SUBDIR_EXAMS = "exams"
PATIENT_SUBDIR_PDFS = "pdfs"
PATIENT_SUBDIR_ROFS = "rofs"
PATIENT_SUBDIR_INFO = "patient_info"
PATIENT_SUBDIR_IMAGING = "imaging"
PATIENT_SUBDIR_ATTORNEY = "attorney"
PATIENT_SUBDIR_BILLING = "billing"
PATIENT_SUBDIR_MESSAGES = "messages"

