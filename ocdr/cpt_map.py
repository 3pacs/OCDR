"""
CPT code → modality / body part mapping.

Used during 835 matching to verify that the CPT code on the ERA claim
corresponds to the modality and body part on the billing record.  This
dramatically improves matching accuracy since CPT codes are precise
while description-based fields can vary.

Also provides body-part synonym sets so that "ABDOMEN" matches "A/P",
"HEAD" matches "BRAIN", etc.
"""


# ── CPT → (modality, body_part) ──────────────────────────────────────────

CPT_MAP: dict[str, dict[str, str]] = {
    # MRI — Head / Brain
    "70551": {"modality": "HMRI", "body_part": "HEAD"},
    "70552": {"modality": "HMRI", "body_part": "HEAD"},
    "70553": {"modality": "HMRI", "body_part": "HEAD"},
    # MRI — Spine
    "72141": {"modality": "HMRI", "body_part": "CERVICAL"},
    "72142": {"modality": "HMRI", "body_part": "CERVICAL"},
    "72146": {"modality": "HMRI", "body_part": "THORACIC"},
    "72147": {"modality": "HMRI", "body_part": "THORACIC"},
    "72148": {"modality": "HMRI", "body_part": "LUMBAR"},
    "72149": {"modality": "HMRI", "body_part": "LUMBAR"},
    "72156": {"modality": "HMRI", "body_part": "CERVICAL"},
    "72157": {"modality": "HMRI", "body_part": "THORACIC"},
    "72158": {"modality": "HMRI", "body_part": "LUMBAR"},
    # MRI — Extremities
    "73221": {"modality": "HMRI", "body_part": "SHOULDER"},
    "73222": {"modality": "HMRI", "body_part": "SHOULDER"},
    "73223": {"modality": "HMRI", "body_part": "SHOULDER"},
    "73721": {"modality": "HMRI", "body_part": "KNEE"},
    "73722": {"modality": "HMRI", "body_part": "KNEE"},
    "73723": {"modality": "HMRI", "body_part": "KNEE"},
    "73718": {"modality": "HMRI", "body_part": "ANKLE"},
    "73719": {"modality": "HMRI", "body_part": "ANKLE"},
    "73720": {"modality": "HMRI", "body_part": "FOOT"},
    # MRI — Pelvis / Abdomen
    "72195": {"modality": "HMRI", "body_part": "PELVIS"},
    "72196": {"modality": "HMRI", "body_part": "PELVIS"},
    "72197": {"modality": "HMRI", "body_part": "PELVIS"},
    "74181": {"modality": "HMRI", "body_part": "ABDOMEN"},
    "74182": {"modality": "HMRI", "body_part": "ABDOMEN"},
    "74183": {"modality": "HMRI", "body_part": "ABDOMEN"},
    # MRI — Chest
    "71550": {"modality": "HMRI", "body_part": "CHEST"},
    "71551": {"modality": "HMRI", "body_part": "CHEST"},
    "71552": {"modality": "HMRI", "body_part": "CHEST"},
    # CT — Head
    "70450": {"modality": "CT", "body_part": "HEAD"},
    "70460": {"modality": "CT", "body_part": "HEAD"},
    "70470": {"modality": "CT", "body_part": "HEAD"},
    # CT — Chest
    "71250": {"modality": "CT", "body_part": "CHEST"},
    "71260": {"modality": "CT", "body_part": "CHEST"},
    "71270": {"modality": "CT", "body_part": "CHEST"},
    # CT — Abdomen
    "74150": {"modality": "CT", "body_part": "ABDOMEN"},
    "74160": {"modality": "CT", "body_part": "ABDOMEN"},
    "74170": {"modality": "CT", "body_part": "ABDOMEN"},
    # CT — Abdomen/Pelvis (C.A.P)
    "74176": {"modality": "CT", "body_part": "ABDOMEN"},
    "74177": {"modality": "CT", "body_part": "ABDOMEN"},
    "74178": {"modality": "CT", "body_part": "ABDOMEN"},
    # CT — Pelvis
    "72192": {"modality": "CT", "body_part": "PELVIS"},
    "72193": {"modality": "CT", "body_part": "PELVIS"},
    "72194": {"modality": "CT", "body_part": "PELVIS"},
    # CT — Spine
    "72125": {"modality": "CT", "body_part": "CERVICAL"},
    "72126": {"modality": "CT", "body_part": "CERVICAL"},
    "72128": {"modality": "CT", "body_part": "THORACIC"},
    "72129": {"modality": "CT", "body_part": "THORACIC"},
    "72131": {"modality": "CT", "body_part": "LUMBAR"},
    "72132": {"modality": "CT", "body_part": "LUMBAR"},
    # CT — Sinus
    "70486": {"modality": "CT", "body_part": "SINUS"},
    "70487": {"modality": "CT", "body_part": "SINUS"},
    "70488": {"modality": "CT", "body_part": "SINUS"},
    # PET/CT
    "78811": {"modality": "PET", "body_part": "WHOLE BODY"},
    "78812": {"modality": "PET", "body_part": "WHOLE BODY"},
    "78813": {"modality": "PET", "body_part": "WHOLE BODY"},
    "78814": {"modality": "PET", "body_part": "WHOLE BODY"},
    "78815": {"modality": "PET", "body_part": "WHOLE BODY"},
    "78816": {"modality": "PET", "body_part": "WHOLE BODY"},
    # PSMA PET
    "78832": {"modality": "PET", "body_part": "WHOLE BODY"},
    # Bone scan
    "78300": {"modality": "BONE", "body_part": "WHOLE BODY"},
    "78305": {"modality": "BONE", "body_part": "WHOLE BODY"},
    "78306": {"modality": "BONE", "body_part": "WHOLE BODY"},
    # X-ray (DX)
    "73562": {"modality": "DX", "body_part": "KNEE"},
    "73564": {"modality": "DX", "body_part": "KNEE"},
    "73600": {"modality": "DX", "body_part": "ANKLE"},
    "73610": {"modality": "DX", "body_part": "ANKLE"},
    "73620": {"modality": "DX", "body_part": "FOOT"},
    "73630": {"modality": "DX", "body_part": "FOOT"},
    "71045": {"modality": "DX", "body_part": "CHEST"},
    "71046": {"modality": "DX", "body_part": "CHEST"},
}


# ── Body-part synonyms ───────────────────────────────────────────────────
# Groups of terms that should be treated as equivalent for matching.
# If any two terms appear in the same group, body_part_match = 1.0.

BODY_PART_SYNONYMS: list[set[str]] = [
    {"HEAD", "BRAIN"},
    {"ABDOMEN", "A/P", "ABD/PEL", "ABDOMEN/PELVIS"},
    {"LUMBAR", "LSP", "L-SPINE", "LSPINE"},
    {"CERVICAL", "CSP", "C-SPINE", "CSPINE"},
    {"THORACIC", "TSP", "T-SPINE", "TSPINE"},
    {"WHOLE BODY", "WB", "TOTAL BODY"},
    {"SHOULDER", "SHLDR"},
    {"FOOT", "FT"},
    {"ANKLE", "ANK"},
]

# Pre-compute a lookup: term → canonical (first element of the set)
_SYNONYM_MAP: dict[str, str] = {}
for _group in BODY_PART_SYNONYMS:
    canonical = sorted(_group)[0]  # deterministic canonical form
    for _term in _group:
        _SYNONYM_MAP[_term] = canonical


def normalize_body_part(body_part: str) -> str:
    """Normalize a body part string via synonym mapping."""
    bp = body_part.strip().upper()
    return _SYNONYM_MAP.get(bp, bp)


def are_body_parts_equivalent(bp1: str, bp2: str) -> bool:
    """Return True if two body parts are synonyms."""
    return normalize_body_part(bp1) == normalize_body_part(bp2)


def lookup_cpt(cpt_code: str) -> dict[str, str] | None:
    """Look up a CPT code and return modality + body_part, or None."""
    return CPT_MAP.get(cpt_code)


def enrich_claim_from_cpt(claim: dict) -> dict:
    """Add modality and scan_type to a claim dict from its CPT codes.

    If the claim has ``cpt_codes`` or ``service_lines``, look up the first
    recognized CPT and set ``modality`` and ``scan_type`` on the claim.
    """
    # Try cpt_codes list first (from flatten_claims)
    cpt_codes = claim.get("cpt_codes", [])
    if not cpt_codes:
        cpt_codes = [
            sl.get("cpt_code", "")
            for sl in claim.get("service_lines", [])
        ]

    for code in cpt_codes:
        info = lookup_cpt(code)
        if info:
            if not claim.get("modality"):
                claim["modality"] = info["modality"]
            if not claim.get("scan_type"):
                claim["scan_type"] = info["body_part"]
            claim["cpt_modality"] = info["modality"]
            claim["cpt_body_part"] = info["body_part"]
            break

    return claim
