"""ERA payer name → billing carrier code normalization.

Single source of truth for mapping ERA 835 payer names to the
normalized carrier codes used in billing_records.insurance_carrier.

RULES (per OCMRI practice):
  - Blue Shield, Anthem, Blue Cross, AARP, United*, CIGNA, CalPERS,
    FEP, Colonial Penn, Golden Rule, Oxford, Transamerica, Keenan,
    Amvicare, Navigere, UMR = INS
  - Noridian, Medicare Service Center = M/M
  - CalOptima, Blue Shield Promise, CA Medi-Cal, LA Care, Molina = CALOPTIMA
  - Prospect, United Care Medical Group = FAMILY (separate from INS)
  - One Call = ONE CALL
  - State of California DHCS = STATE
  - Government Employees Health = INS

*Note: "UNITED CARE MEDICAL GROUP" → FAMILY (physician group, not UHC)
       "UNITEDHEALTHCARE*" → INS (actual UHC plans)
"""

# Complete mapping of all known ERA payer names to billing carrier codes.
# When a payer name is not found here, the normalize function will attempt
# substring matching before falling back to the raw name.
ERA_PAYER_TO_CARRIER: dict[str, str] = {
    # === Medicare / M/M ===
    "MEDICARE SERVICE CENTER": "M/M",
    "MEDICARE": "M/M",
    "NORIDIAN HEALTHCARE SOLUTIONS, LLC": "M/M",

    # === CalOptima / Managed Medicaid ===
    "CALOPTIMA": "CALOPTIMA",
    "CA MEDI-CAL": "CALOPTIMA",
    "BLUE SHIELD OF CALIFORNIA PROMISE HEALTH PLAN": "CALOPTIMA",
    "LA CARE": "CALOPTIMA",
    "MOLINA HEALTHCARE OF CALIFORNIA": "CALOPTIMA",

    # === FAMILY (physician groups — NOT commercial insurance) ===
    "PROSPECT MEDICAL SYSTEMS": "FAMILY",
    "PROSPECT STARCARE MEDICAL GROUP": "FAMILY",
    "PROSPECT/REGION B": "FAMILY",
    "UNITED CARE MEDICAL GROUP": "FAMILY",

    # === INS (commercial insurance) ===
    # Blue Shield / Blue Cross / Anthem
    "CALIFORNIA PHYSICIANS SERVICE DBA BLUE SHIELD CA": "INS",
    "BLUE CROSS OF CALIFORNIA (CA)": "INS",
    "ANTHEM BC LIFE   HEALTH INS CO": "INS",
    "ANTHEM BC LIFE & HEALTH INS CO": "INS",
    "ANTHEM INSURANCE COMPANIES, INC.": "INS",

    # UnitedHealthcare (all variations — NOT "United Care Medical Group")
    "UNITEDHEALTHCARE SERVICES INC AND ITS AFFILIATES": "INS",
    "UNITEDHEALTHCARE INSURANCE COMPANY AND ITS AFFILIATES": "INS",
    "UNITEDHEALTHCARE BENEFITS PLAN OF CALIFORNIA": "INS",
    "UNITEDHEALTHCARE": "INS",
    "UNITED HEALTHCARE SERVICES INC": "INS",
    "UNITED AMERICAN INSURANCE CO": "INS",
    "UHC GOVERNMENT EMPLOYEES HEALTH ASSOC": "INS",

    # AARP (UHC subsidiary)
    "AARP SUPPLEMENTAL HEALTH PLANS FROM UNITEDHEALTHCARE": "INS",

    # CalPERS
    "CALPERS": "INS",

    # CIGNA
    "CIGNA HEALTH AND LIFE INSURANCE COMPANY": "INS",

    # Federal Employee Programs
    "FEP BASIC CLAIMS ACCOUNT-FACETS": "INS",
    "FEP PPO BLUE FOCUS CLAIMS ACCOUNT": "INS",
    "FEP STANDARD CLAIMS ACCOUNT-FACETS": "INS",
    "POSTAL SERVICE HBP-BASIC": "INS",
    "POSTAL SERVICE HBP-STD": "INS",
    "GOVERNMENT EMPLOYEES HEALTH ASSOCIATION": "INS",

    # Other commercial
    "COLONIAL PENN LIFE INS. CO.": "INS",
    "GOLDEN RULE INSURANCE COMPANY": "INS",
    "OXFORD HEALTH INSURANCE INC": "INS",
    "TRANSAMERICA LIFE INSURANCE COMPANY": "INS",
    "KEENAN": "INS",
    "AMVICARE": "INS",
    "NAVIGERE": "INS",
    "UMR": "INS",
    "UMR USNAS": "INS",
    "AUTO CLUB ENTERPRISES RETIREE": "INS",

    # === ONE CALL ===
    "ONE CALL - DIAGNOSTICS": "ONE CALL",

    # === STATE ===
    "STATE OF CALIFORNIA - DEPARTMENT OF HEALTH CARE SERVICES": "STATE",

    # === Internal / Misc ===
    "ACCOUNTING DEPT.": "SELF PAY",
}

# Substring rules for payer names not in the exact map.
# Checked in order — first match wins. Case-insensitive.
_SUBSTRING_RULES: list[tuple[str, str]] = [
    ("MEDICARE", "M/M"),
    ("NORIDIAN", "M/M"),
    ("CALOPTIMA", "CALOPTIMA"),
    ("MEDI-CAL", "CALOPTIMA"),
    ("LA CARE", "CALOPTIMA"),
    ("MOLINA", "CALOPTIMA"),
    ("PROSPECT", "FAMILY"),
    ("UNITED CARE", "FAMILY"),
    ("ANTHEM", "INS"),
    ("BLUE SHIELD", "INS"),
    ("BLUE CROSS", "INS"),
    ("UNITEDHEALTHCARE", "INS"),
    ("UNITED HEALTH", "INS"),
    ("AARP", "INS"),
    ("CIGNA", "INS"),
    ("UMR", "INS"),
    ("FEP ", "INS"),
    ("POSTAL SERVICE", "INS"),
    ("OXFORD", "INS"),
    ("ONE CALL", "ONE CALL"),
    ("WORKERS COMP", "W/C"),
]


def normalize_era_payer(payer_name: str | None) -> str:
    """Normalize an ERA 835 payer name to a billing carrier code.

    Returns the normalized carrier code, or "UNKNOWN" if the name
    cannot be mapped.
    """
    if not payer_name:
        return "UNKNOWN"

    name = payer_name.strip()
    upper = name.upper()

    # 1. Exact match (case-insensitive)
    carrier = ERA_PAYER_TO_CARRIER.get(upper) or ERA_PAYER_TO_CARRIER.get(name)
    if carrier:
        return carrier

    # 2. Substring rules
    for substring, code in _SUBSTRING_RULES:
        if substring in upper:
            return code

    # 3. No match — return UNKNOWN (don't store raw payer names as carrier)
    return "UNKNOWN"
