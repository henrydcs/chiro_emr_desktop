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
EXAMS = []  # No base exams; all exams are dynamic (Initial 1, Re-Exam 1, etc.)

EXAM_COLORS = {
    "Initial": {"bg": "#E3F2FD", "accent": "#1E88E5"},
    "Re-Exam 1": {"bg": "#E8F5E9", "accent": "#43A047"},
    "Re-Exam 2": {"bg": "#FFFDE7", "accent": "#F9A825"},
    "Final Exam": {"bg": "#FCE4EC", "accent": "#C2185B"},
}

# ----------------- UI OPTIONS -----------------
PAIN_DESCRIPTORS = [
    "Achy", "Sharp", "Soreness", "Tension", "Dull", "Burning", "Throbbing",
    "Stabbing", "Shooting", "Tightness", "Pressure", "Cramping", "Pulsating",
]

RADIC_SYMPTOMS = ["None", "Numbness", "Tingling", "Weakness", "Sypmtoms", "Discomfort", "Pain"]

RADIC_LOCATIONS = [
    "(select)",
    "Bilateral upper trapezius muscles",
    "Left upper trapezius muscle", 
    "Right upper trapezius muscle",
    "Bilateral shoulders", "Left shoulder", "Right shoulder",    
    "Bilateral arms", "Left arm", "Right arm",
    "Bilateral elbows", "Left elbow", "Right elbow",
    "Bilateral forearms", "Left forearm", "Right forearm",
    "Bilateral wrists", "Left wrist", "Right wrist",
    "Bilateral hands", "Left hand", "Right hand",
    "Left and Right fingers", "Left finger", "Right finger",
    "Bilateral hips", "Left hip", "Right hip",
    "Bilateral thighs", "Left thigh", "Right thigh",
    "Bilateral knees", "Left knee", "Right knee", 
    "Bilateral legs", "Left leg", "Right leg", 
    "Bilateral ankles", "Left ankle", "Right ankle",
    "Bilateral feet", "Left foot", "Right foot",
    "Left and Right toes", "Left toe", "Right toe",             
    
]

REGION_OPTIONS = [
    "(none)",
    "Head", "CS", "TS", "LS", "Sacrum",

    "R_SHOULDER", "L_SHOULDER", "BL_SHOULDER",
    "R_ARM", "L_ARM", "BL_ARMS",
    "R_ELBOW", "L_ELBOW", "BL_ELBOW",
    "R_FOREARM", "L_FOREARM", "BL_FOREARMS",
    "R_WRIST", "L_WRIST", "BL_WRIST",
    "R_HAND", "L_HAND", "BL_HANDS",

    "R_HIP", "L_HIP", "BL_HIP",
    'R_THIGH', 'L_THIGH', "BL_THIGH",
    "R_KNEE", "L_KNEE", "BL_KNEE",
    "R_LEG", "L_LEG", "BL_LEGS",
    "R_ANKLE", "L_ANKLE", "BL_ANKLE",
    "R_FOOT", "L_FOOT", "BL_FEET",
]



REGION_LABELS = {
    "Head": "Head",
    "CS": "Cervical Spine",
    "TS": "Thoracic Spine",
    "LS": "Lumbar Spine",
    "Sacrum": "Sacrum",

    "R_SHOULDER": "Right Shoulder",
    "L_SHOULDER": "Left Shoulder",
    "BL_SHOULDER": "Bilateral Shoulders",

    "R_ARM": "Right Arm",
    "L_ARM": "Left Arm",
    "BL_ARMS": "Bilateral Arms",

    "R_ELBOW": "Right Elbow",
    "L_ELBOW": "Left Elbow",
    "BL_ELBOW": "Bilateral Elbows",

    "R_FOREARM": "Right Forearm",
    "L_FOREARM": "Left Forearm",
    "BL_FOREARMS": "Bilateral Forearms",

    "R_WRIST": "Right Wrist",
    "L_WRIST": "Left Wrist",
    "BL_WRIST": "Bilateral Wrists",

    "R_HAND": "Right Hand",
    "L_HAND": "Left Hand",
    "BL_HANDS": "Bilateral Hands",

    "R_HIP": "Right Hip",
    "L_HIP": "Left Hip",
    "BL_HIP": "Bilateral Hips",

    "R_THIGH": "Right Thigh",
    "L_THIGH": "Left Thigh",
    "BL_THIGH": "Bilateral Thighs",

    "R_KNEE": "Right Knee",
    "L_KNEE": "Left Knee",
    "BL_KNEE": "Bilateral Knees",

    "R_LEG": "Right Leg",
    "L_LEG": "Left Leg",
    "BL_LEGS": "Bilateral Legs",

    "R_ANKLE": "Right Ankle",
    "L_ANKLE": "Left Ankle",
    "BL_ANKLE": "Bilateral Ankles",

    "R_FOOT": "Right Foot",
    "L_FOOT": "Left Foot",
    "BL_FEET": "Bilateral Feet",
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
EXAM_INDEX_SUBDIR = "index_exam_number" #where _index_exam.json now lives

