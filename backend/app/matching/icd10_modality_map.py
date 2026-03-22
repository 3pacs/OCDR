"""ICD-10 diagnosis code → expected imaging modality mapping.

Maps ICD-10 diagnosis categories to the imaging modalities typically ordered
for those conditions. Used by the auto-matcher as a confidence modifier:
when a claim has both a CPT code (→ procedure modality) and a diagnosis code,
we can verify they're clinically consistent.

IMPORTANT: This is a SOFT validation layer. It boosts confidence when
diagnosis and modality align, and lowers confidence when they conflict.
It does NOT hard-reject matches — clinical practice varies.

The mapping is organized by ICD-10 chapter (letter prefix) and then by
specific code ranges within each chapter.

Sources: CMS ICD-10-CM guidelines, ACR Appropriateness Criteria, standard
radiology ordering patterns for outpatient imaging centers.
"""

from __future__ import annotations


# Maps ICD-10 code prefix → list of expected modalities.
# More specific prefixes take priority over broader ones.
# Each entry is (prefix, expected_modalities, description).
ICD10_MODALITY_RULES: list[tuple[str, list[str], str]] = [
    # === ONCOLOGY (C00-C96) ===
    # Cancer staging/restaging → PET/CT is standard of care
    ("C61",    ["PET", "HMRI", "CT", "BONE"],  "Prostate cancer"),
    ("C34",    ["PET", "CT"],                   "Lung cancer"),
    ("C50",    ["PET", "CT", "HMRI", "MAMMO"],  "Breast cancer"),
    ("C18",    ["PET", "CT"],                   "Colon cancer"),
    ("C19",    ["PET", "CT"],                   "Rectosigmoid cancer"),
    ("C20",    ["PET", "CT"],                   "Rectal cancer"),
    ("C22",    ["PET", "CT", "HMRI"],           "Liver cancer"),
    ("C25",    ["PET", "CT"],                   "Pancreatic cancer"),
    ("C43",    ["PET", "CT"],                   "Melanoma"),
    ("C56",    ["PET", "CT"],                   "Ovarian cancer"),
    ("C64",    ["PET", "CT"],                   "Kidney cancer"),
    ("C67",    ["PET", "CT"],                   "Bladder cancer"),
    ("C71",    ["HMRI", "CT", "PET"],           "Brain cancer"),
    ("C73",    ["PET", "CT", "US"],             "Thyroid cancer"),
    ("C81",    ["PET", "CT"],                   "Hodgkin lymphoma"),
    ("C82",    ["PET", "CT"],                   "Follicular lymphoma"),
    ("C83",    ["PET", "CT"],                   "Non-follicular lymphoma"),
    ("C84",    ["PET", "CT"],                   "T-cell lymphoma"),
    ("C85",    ["PET", "CT"],                   "Other lymphoma"),
    ("C90",    ["PET", "CT", "HMRI", "BONE"],   "Multiple myeloma"),
    ("C91",    ["PET", "CT"],                   "Lymphoid leukemia"),
    ("C92",    ["PET", "CT"],                   "Myeloid leukemia"),
    # Broad cancer category — any C-code not matched above
    ("C",      ["PET", "CT", "HMRI"],           "Cancer (general)"),

    # Cancer history / surveillance
    ("Z85",    ["PET", "CT", "HMRI"],           "Personal history of cancer"),
    ("Z80",    ["CT", "HMRI", "MAMMO"],         "Family history of cancer"),

    # === MUSCULOSKELETAL (M00-M99) ===
    ("M54",    ["HMRI", "CT", "DX"],            "Back pain / dorsalgia"),
    ("M51",    ["HMRI", "CT"],                  "Disc disorders"),
    ("M50",    ["HMRI", "CT"],                  "Cervical disc disorders"),
    ("M47",    ["HMRI", "CT", "DX"],            "Spondylosis"),
    ("M48",    ["HMRI", "CT", "DX"],            "Spinal stenosis"),
    ("M79",    ["HMRI", "DX", "US"],            "Soft tissue disorders"),
    ("M75",    ["HMRI", "DX", "US"],            "Shoulder lesions"),
    ("M23",    ["HMRI"],                        "Internal knee derangement"),
    ("M25",    ["HMRI", "DX"],                  "Joint disorders"),
    ("M17",    ["DX", "HMRI"],                  "Knee osteoarthritis"),
    ("M16",    ["DX", "HMRI"],                  "Hip osteoarthritis"),
    ("M",      ["HMRI", "CT", "DX"],            "Musculoskeletal (general)"),

    # === INJURY / FRACTURE (S00-T88) ===
    ("S72",    ["DX", "CT"],                    "Femur fracture"),
    ("S82",    ["DX", "CT"],                    "Lower leg fracture"),
    ("S42",    ["DX", "CT"],                    "Shoulder/upper arm fracture"),
    ("S52",    ["DX", "CT"],                    "Forearm fracture"),
    ("S62",    ["DX"],                          "Hand/wrist fracture"),
    ("S92",    ["DX"],                          "Foot fracture"),
    ("S06",    ["CT", "HMRI"],                  "Intracranial injury"),
    ("S",      ["DX", "CT", "HMRI"],            "Injury (general)"),

    # === NEUROLOGICAL (G00-G99) ===
    ("G43",    ["HMRI", "CT"],                  "Migraine"),
    ("G44",    ["HMRI", "CT"],                  "Headache syndromes"),
    ("G40",    ["HMRI", "CT"],                  "Epilepsy"),
    ("G35",    ["HMRI"],                        "Multiple sclerosis"),
    ("G20",    ["HMRI", "CT"],                  "Parkinson's disease"),
    ("G",      ["HMRI", "CT"],                  "Neurological (general)"),

    # === CARDIOVASCULAR (I00-I99) ===
    ("I63",    ["CT", "HMRI"],                  "Cerebral infarction / stroke"),
    ("I61",    ["CT", "HMRI"],                  "Intracerebral hemorrhage"),
    ("I60",    ["CT", "HMRI"],                  "Subarachnoid hemorrhage"),
    ("I25",    ["CT", "PET"],                   "Chronic ischemic heart disease"),
    ("I",      ["CT", "HMRI", "US"],            "Cardiovascular (general)"),

    # === RESPIRATORY (J00-J99) ===
    ("J18",    ["DX", "CT"],                    "Pneumonia"),
    ("J84",    ["CT", "DX"],                    "Interstitial pulmonary disease"),
    ("J43",    ["CT", "DX"],                    "Emphysema"),
    ("J44",    ["CT", "DX"],                    "COPD"),
    ("J",      ["DX", "CT"],                    "Respiratory (general)"),

    # === DIGESTIVE (K00-K93) ===
    ("K80",    ["US", "CT"],                    "Cholelithiasis / gallstones"),
    ("K57",    ["CT"],                          "Diverticular disease"),
    ("K",      ["CT", "US"],                    "Digestive (general)"),

    # === GENITOURINARY (N00-N99) ===
    ("N20",    ["CT", "DX", "US"],              "Kidney/ureter calculus"),
    ("N40",    ["HMRI", "US"],                  "Prostate conditions"),
    ("N63",    ["MAMMO", "US"],                 "Breast lump"),
    ("N",      ["CT", "US", "HMRI"],            "Genitourinary (general)"),

    # === PREGNANCY (O00-O99) ===
    ("O",      ["US"],                          "Pregnancy-related"),

    # === SYMPTOMS (R00-R99) ===
    ("R91",    ["CT", "DX"],                    "Abnormal lung findings"),
    ("R92",    ["MAMMO", "US"],                 "Abnormal breast findings"),
    ("R93",    ["CT", "HMRI", "US"],            "Abnormal organ findings"),
    ("R10",    ["CT", "US"],                    "Abdominal pain"),
    ("R51",    ["HMRI", "CT"],                  "Headache"),
    ("R22",    ["CT", "US", "HMRI"],            "Localized swelling/mass"),
    ("R",      ["CT", "HMRI", "DX", "US"],      "Symptoms (general)"),

    # === PSMA-specific codes ===
    # PSMA PET/CT is specifically for prostate cancer staging
    ("C61",    ["PET"],                         "Prostate cancer — PSMA PET indication"),
    ("Z85.46", ["PET"],                         "Prostate cancer history — PSMA PET follow-up"),
]

# Precomputed: sorted by prefix length descending for longest-match-first lookup
_SORTED_RULES = sorted(ICD10_MODALITY_RULES, key=lambda r: -len(r[0]))


def get_expected_modalities(diagnosis_codes: str | None) -> set[str]:
    """Given comma-separated ICD-10 codes, return set of expected modalities.

    Returns empty set if no diagnosis codes provided (= no opinion).
    """
    if not diagnosis_codes:
        return set()

    expected = set()
    for raw_code in diagnosis_codes.split(","):
        code = raw_code.strip().upper()
        if not code:
            continue
        # Find the most specific matching rule
        for prefix, modalities, _desc in _SORTED_RULES:
            if code.startswith(prefix.upper()):
                expected.update(modalities)
                break
    return expected


def diagnosis_modality_score(
    diagnosis_codes: str | None,
    modality: str | None,
) -> float:
    """Score how well a billing record's modality fits the claim's diagnosis.

    Returns:
        1.0  — diagnosis confirms this modality (strong match)
        0.0  — no diagnosis data (neutral — no opinion)
       -0.5  — diagnosis suggests a different modality (mild penalty)

    The penalty is mild because:
    - ICD-10 coding varies by physician preference
    - Some diagnoses legitimately span multiple modality types
    - The mapping is approximate, not exhaustive
    """
    if not diagnosis_codes or not modality:
        return 0.0  # No data → neutral

    expected = get_expected_modalities(diagnosis_codes)
    if not expected:
        return 0.0

    mod_upper = modality.upper()
    if mod_upper in expected:
        return 1.0  # Diagnosis confirms this modality
    else:
        return -0.5  # Mild penalty — diagnosis suggests different modality


def explain_diagnosis_modality(
    diagnosis_codes: str | None,
    modality: str | None,
) -> str:
    """Human-readable explanation of diagnosis↔modality compatibility.

    Used in the diagnose endpoint to explain match reasoning.
    """
    if not diagnosis_codes:
        return "No diagnosis codes available"
    if not modality:
        return "No modality on billing record"

    expected = get_expected_modalities(diagnosis_codes)
    if not expected:
        return f"No modality rules for diagnosis code(s): {diagnosis_codes}"

    mod_upper = modality.upper()
    if mod_upper in expected:
        return f"COMPATIBLE: {modality} is expected for diagnosis {diagnosis_codes} (expected: {', '.join(sorted(expected))})"
    else:
        return f"MISMATCH: {modality} not expected for diagnosis {diagnosis_codes} (expected: {', '.join(sorted(expected))})"
