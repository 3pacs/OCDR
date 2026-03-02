"""Central configuration for OCDR. All paths, payer config, and fee schedule."""

import sys
from pathlib import Path
from datetime import date
from decimal import Decimal

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Detect PyInstaller bundle
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running as a PyInstaller .exe
    #   BASE_DIR   = folder containing the .exe  (user data lives here)
    #   BUNDLE_DIR = temp extraction dir          (bundled resources live here)
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    # Running as normal Python
    BASE_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
IMPORT_DIR = DATA_DIR / "import"
EXPORT_DIR = DATA_DIR / "export"
TEMPLATE_DIR = BUNDLE_DIR / "templates"

OCMRI_PATH = DATA_DIR / "OCMRI.xlsx"
OCMRI_SHEET = "Current"

RECONCILIATION_PATH = EXPORT_DIR / "OCDR_Reconciliation.xlsx"

EDI_835_DIR = IMPORT_DIR / "835"
CANDELIS_DIR = IMPORT_DIR / "candelis"
SCHEDULE_DIR = IMPORT_DIR / "schedules"

# ---------------------------------------------------------------------------
# Excel serial date epoch  (accounts for Lotus 1-2-3 leap-year bug)
# ---------------------------------------------------------------------------
EXCEL_EPOCH = date(1899, 12, 30)

# ---------------------------------------------------------------------------
# Payer configuration  (from BUILD_SPEC seed data)
# ---------------------------------------------------------------------------
PAYER_CONFIG = {
    "M/M":       {"name": "Medicare/Medicaid",           "deadline": 365,  "has_secondary": True,  "alert_pct": 0.25},
    "CALOPTIMA": {"name": "CalOptima Managed Medicaid",  "deadline": 180,  "has_secondary": True,  "alert_pct": 0.25},
    "FAMILY":    {"name": "Family Health Plan",          "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "INS":       {"name": "Commercial Insurance",        "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "VU PHAN":   {"name": "Vu Phan Physician Group",    "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "W/C":       {"name": "Workers Compensation",        "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "BEACH":     {"name": "Beach Clinical Labs",         "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "JHANGIANI": {"name": "Jhangiani Physician Group",   "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "ONE CALL":  {"name": "One Call Care Management",    "deadline": 90,   "has_secondary": False, "alert_pct": 0.50},
    "OC ADV":    {"name": "One Call Advanced",           "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
    "SELF PAY":  {"name": "Self Pay / Uninsured",        "deadline": 9999, "has_secondary": False, "alert_pct": 0.25},
    "STATE":     {"name": "State Programs",              "deadline": 365,  "has_secondary": False, "alert_pct": 0.25},
    "COMP":      {"name": "Complimentary / Charity",     "deadline": 9999, "has_secondary": False, "alert_pct": 0.50},
    "X":         {"name": "Unknown / Unclassified",      "deadline": 180,  "has_secondary": False, "alert_pct": 0.50},
    "GH":        {"name": "Group Health",                "deadline": 180,  "has_secondary": False, "alert_pct": 0.25},
}

# ---------------------------------------------------------------------------
# Fee schedule  (from BUILD_SPEC seed data)
#   key = (modality, payer_code)   payer_code "DEFAULT" = global fallback
# ---------------------------------------------------------------------------
FEE_SCHEDULE = {
    ("CT",   "DEFAULT"):    Decimal("395.00"),
    ("HMRI", "DEFAULT"):    Decimal("750.00"),
    ("PET",  "DEFAULT"):    Decimal("2500.00"),
    ("BONE", "DEFAULT"):    Decimal("1800.00"),
    ("OPEN", "DEFAULT"):    Decimal("750.00"),
    ("DX",   "DEFAULT"):    Decimal("250.00"),
    # Payer-specific overrides
    ("HMRI", "JHANGIANI"):  Decimal("950.00"),
}

PSMA_PET_RATE = Decimal("8046.00")
GADO_PREMIUM = Decimal("200.00")
UNDERPAYMENT_THRESHOLD = Decimal("0.80")

# ---------------------------------------------------------------------------
# Payer aliases for normalisation  (BR-10)
# ---------------------------------------------------------------------------
PAYER_ALIASES = {
    "SELFPAY":  "SELF PAY",
    "SELF-PAY": "SELF PAY",
    "CASH":     "SELF PAY",
    "MEDICARE":           "M/M",
    "MEDICAID":           "M/M",
    "MEDICARE/MEDICAID":  "M/M",
}

# ---------------------------------------------------------------------------
# Matching thresholds  (BR-09)
# ---------------------------------------------------------------------------
MATCH_AUTO_ACCEPT = 0.95
MATCH_REVIEW = 0.80

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_expected_rate(modality: str, payer: str = "DEFAULT",
                      is_psma: bool = False, gado: bool = False) -> Decimal:
    """Look up expected rate, applying PSMA (BR-02) and gado premium (BR-03)."""
    if is_psma and modality == "PET":
        return PSMA_PET_RATE
    rate = FEE_SCHEDULE.get((modality, payer),
           FEE_SCHEDULE.get((modality, "DEFAULT"), Decimal("0.00")))
    if gado and modality in ("HMRI", "OPEN"):
        rate = rate + GADO_PREMIUM
    return rate


def get_payer(code: str) -> dict:
    """Return payer config dict; falls back to 180-day generic."""
    return PAYER_CONFIG.get(code, {"name": code, "deadline": 180,
                                    "has_secondary": False, "alert_pct": 0.25})
