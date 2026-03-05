"""Data validation and external-validatable checks.

DATA CLASSIFICATION
==================

STATIC DATA (rarely changes, can be hardcoded/seeded):
  - VALID_MODALITIES: imaging modality codes (CT, HMRI, PET, BONE, OPEN, DX, PET_PSMA)
  - VALID_DENIAL_STATUSES: denial workflow states
  - VALID_CLAIM_STATUSES: X12 835 claim status codes (1, 2, 4, 22)
  - CAS_GROUP_CODES: ANSI adjustment reason group codes (CO, OA, PI, PR, CR)
  - CPT_TO_MODALITY: CPT code to modality crosswalk
  - PAYMENT_METHODS: ERA payment method codes (CHK, ACH, NON)

SEMI-STATIC DATA (changes quarterly/annually, managed via admin):
  - Payer codes + filing deadlines (new payers appear ~1-2x/year)
  - Fee schedule rates (renegotiated annually)
  - Physician roster (new doctors, retirements)
  - CAS reason codes (ANSI standard, updated yearly)

DYNAMIC DATA (changes per-transaction, from imports):
  - BillingRecord fields (patient, service, payment data)
  - ERA payment/claim data (from 835 files)
  - Match linkages (computed by auto-matcher)
  - Denial tracking fields (workflow state)

EXTERNALLY VALIDATABLE:
  - CPT codes: validate against CMS CPT code database
  - CAS reason codes: validate against X12 CARC/RARC tables
  - Payer IDs: validate against CMS NPPES / payer ID registry
  - Modality codes: fixed set, validate on import
  - Payment amounts: non-negative, reasonable range checks
  - Dates: service_date not in future, not before 2015
  - Patient names: not empty, reasonable length, no numeric-only
"""

from datetime import date
from decimal import Decimal
from typing import Any


# ============================================================
# STATIC ENUMS — these are the source of truth
# ============================================================

VALID_MODALITIES = frozenset({
    "CT", "HMRI", "PET", "BONE", "OPEN", "DX", "PET_PSMA",
    "FLUORO", "MAMMO", "US", "NM", "DEXA",  # Less common but valid
})

VALID_DENIAL_STATUSES = frozenset({
    "DENIED", "PENDING", "APPEALED", "OVERTURNED", "WRITTEN_OFF",
    "RESUBMITTED", "PAID_ON_APPEAL",
})

VALID_CLAIM_STATUSES = frozenset({
    "1",   # Processed as primary
    "2",   # Processed as secondary
    "4",   # Denied
    "22",  # Reversal of previous payment
    "23",  # Predetermination pricing
})

CLAIM_STATUS_LABELS = {
    "1": "PAID_PRIMARY",
    "2": "PAID_SECONDARY",
    "4": "DENIED",
    "22": "REVERSAL",
    "23": "PREDETERMINATION",
}

# ANSI X12 Claim Adjustment Group Codes
CAS_GROUP_CODES = frozenset({
    "CO",  # Contractual Obligation
    "CR",  # Correction/Reversal
    "OA",  # Other Adjustment
    "PI",  # Payer Initiated Reduction
    "PR",  # Patient Responsibility
})

# Common CAS Reason Codes (CARC) — top 30 most seen
COMMON_CAS_REASON_CODES = frozenset({
    "1", "2", "3", "4", "5", "16", "18", "22", "23", "24",
    "26", "27", "29", "31", "45", "50", "55", "59", "96", "97",
    "100", "107", "109", "119", "125", "130", "131", "133", "136", "140",
    "146", "167", "170", "171", "181", "186", "187", "188", "189", "190",
    "197", "198", "199", "204", "213", "216", "219", "222", "223", "224",
    "226", "227", "234", "235", "236", "237", "238", "239", "240", "242",
    "243", "246", "247", "253", "261", "262",
})

PAYMENT_METHODS = frozenset({"CHK", "ACH", "NON", "FWT", "BOP"})

IMPORT_SOURCES = frozenset({"excel_structured", "excel_flexible", "era_835", "manual"})

# CPT to modality crosswalk (externally validatable against CMS)
CPT_TO_MODALITY = {
    "74177": "CT", "74178": "CT", "74176": "CT", "72193": "CT",
    "72192": "CT", "74174": "CT", "71260": "CT", "71250": "CT",
    "70553": "HMRI", "70551": "HMRI", "70552": "HMRI",
    "73721": "HMRI", "73718": "HMRI", "73220": "HMRI",
    "78816": "PET", "78815": "PET", "78814": "PET",
    "78300": "BONE", "78305": "BONE",
    "71046": "DX", "71045": "DX", "73030": "DX",
}


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

class ValidationResult:
    """Result of a validation check."""
    __slots__ = ("valid", "field", "value", "message", "severity")

    def __init__(self, valid: bool, field: str, value: Any, message: str = "", severity: str = "ERROR"):
        self.valid = valid
        self.field = field
        self.value = value
        self.message = message
        self.severity = severity  # ERROR, WARNING, INFO

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "field": self.field,
            "value": str(self.value)[:100] if self.value else None,
            "message": self.message,
            "severity": self.severity,
        }


def validate_billing_record(record: dict) -> list[ValidationResult]:
    """Validate a billing record before insert/update.

    Returns list of validation results (empty = all good).
    Only returns failures and warnings.
    """
    results = []

    # --- Required fields ---
    for field in ("patient_name", "referring_doctor", "insurance_carrier", "modality", "service_date"):
        val = record.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            results.append(ValidationResult(
                False, field, val,
                f"Required field '{field}' is missing or empty",
            ))

    # --- Patient name checks ---
    name = record.get("patient_name", "")
    if name:
        if len(name) < 3:
            results.append(ValidationResult(
                False, "patient_name", name,
                "Patient name too short (< 3 chars)",
            ))
        if name.replace(" ", "").isdigit():
            results.append(ValidationResult(
                False, "patient_name", name,
                "Patient name is numeric-only — likely a data error",
            ))

    # --- Modality validation ---
    modality = record.get("modality")
    if modality and modality.upper() not in VALID_MODALITIES:
        results.append(ValidationResult(
            False, "modality", modality,
            f"Unknown modality '{modality}'. Valid: {', '.join(sorted(VALID_MODALITIES))}",
            severity="WARNING",
        ))

    # --- Service date checks ---
    svc_date = record.get("service_date")
    if svc_date:
        if isinstance(svc_date, date):
            if svc_date > date.today():
                results.append(ValidationResult(
                    False, "service_date", svc_date,
                    "Service date is in the future",
                ))
            if svc_date < date(2010, 1, 1):
                results.append(ValidationResult(
                    False, "service_date", svc_date,
                    "Service date before 2010 — likely a parsing error",
                    severity="WARNING",
                ))

    # --- Payment amount checks ---
    for field in ("primary_payment", "secondary_payment", "total_payment"):
        val = record.get(field, 0)
        if val is None:
            continue
        try:
            fval = float(val)
        except (ValueError, TypeError):
            results.append(ValidationResult(
                False, field, val,
                f"Payment field '{field}' is not a valid number",
            ))
            continue

        if fval < 0:
            results.append(ValidationResult(
                False, field, val,
                f"Payment '{field}' is negative: {fval}",
                severity="WARNING",
            ))
        if fval > 100_000:
            results.append(ValidationResult(
                False, field, val,
                f"Payment '{field}' is unusually high: ${fval:,.2f} — verify",
                severity="WARNING",
            ))

    # --- Total payment consistency ---
    primary = float(record.get("primary_payment", 0) or 0)
    secondary = float(record.get("secondary_payment", 0) or 0)
    total = float(record.get("total_payment", 0) or 0)
    if primary + secondary > 0 and total > 0:
        expected = primary + secondary
        if abs(expected - total) > 1.0:  # Allow $1 rounding
            results.append(ValidationResult(
                False, "total_payment", total,
                f"Total (${total:,.2f}) != Primary (${primary:,.2f}) + Secondary (${secondary:,.2f}) = ${expected:,.2f}",
                severity="WARNING",
            ))

    # --- Denial status validation ---
    denial = record.get("denial_status")
    if denial and denial.upper() not in VALID_DENIAL_STATUSES:
        results.append(ValidationResult(
            False, "denial_status", denial,
            f"Unknown denial status '{denial}'. Valid: {', '.join(sorted(VALID_DENIAL_STATUSES))}",
            severity="WARNING",
        ))

    # --- Insurance carrier checks ---
    carrier = record.get("insurance_carrier")
    if carrier:
        if len(carrier) < 2:
            results.append(ValidationResult(
                False, "insurance_carrier", carrier,
                "Insurance carrier code too short",
                severity="WARNING",
            ))
        if carrier.upper() in ("X", "UNKNOWN", "N/A", "NA", "NONE", ""):
            results.append(ValidationResult(
                False, "insurance_carrier", carrier,
                f"Insurance carrier is placeholder '{carrier}' — needs verification",
                severity="WARNING",
            ))

    return results


def validate_era_claim_line(record: dict) -> list[ValidationResult]:
    """Validate an ERA claim line."""
    results = []

    # Claim status
    status = record.get("claim_status")
    if status and status not in VALID_CLAIM_STATUSES:
        results.append(ValidationResult(
            False, "claim_status", status,
            f"Unknown claim status '{status}'. Valid: {', '.join(sorted(VALID_CLAIM_STATUSES))}",
        ))

    # CAS group code
    group = record.get("cas_group_code")
    if group and group.upper() not in CAS_GROUP_CODES:
        results.append(ValidationResult(
            False, "cas_group_code", group,
            f"Unknown CAS group code '{group}'. Valid: {', '.join(sorted(CAS_GROUP_CODES))}",
            severity="WARNING",
        ))

    # CPT code format
    cpt = record.get("cpt_code")
    if cpt:
        clean = cpt.strip()
        if not (clean.isdigit() and len(clean) == 5):
            results.append(ValidationResult(
                False, "cpt_code", cpt,
                f"CPT code '{cpt}' is not a valid 5-digit code",
                severity="WARNING",
            ))

    # Paid vs billed sanity
    billed = float(record.get("billed_amount", 0) or 0)
    paid = float(record.get("paid_amount", 0) or 0)
    if paid > billed > 0:
        results.append(ValidationResult(
            False, "paid_amount", paid,
            f"Paid (${paid:,.2f}) exceeds billed (${billed:,.2f})",
            severity="WARNING",
        ))

    return results


def validate_payer_code(code: str, known_payers: set[str]) -> ValidationResult:
    """Check if a payer code is in the known payer registry."""
    if code.upper() in {p.upper() for p in known_payers}:
        return ValidationResult(True, "insurance_carrier", code, "Known payer")
    return ValidationResult(
        False, "insurance_carrier", code,
        f"Payer '{code}' not in registry — add to payers table or verify spelling",
        severity="WARNING",
    )


# ============================================================
# BATCH VALIDATION (for import pipelines)
# ============================================================

def validate_batch(records: list[dict], known_payers: set[str] | None = None) -> dict:
    """Validate a batch of records and return summary.

    Returns:
        {
            "total": int,
            "valid": int,
            "warnings": int,
            "errors": int,
            "error_details": [...],
            "warning_details": [...],
            "unknown_payers": set,
            "unknown_modalities": set,
        }
    """
    total = len(records)
    valid = 0
    warnings = 0
    errors = 0
    error_details = []
    warning_details = []
    unknown_payers = set()
    unknown_modalities = set()

    for i, rec in enumerate(records):
        results = validate_billing_record(rec)

        # Payer check
        if known_payers:
            carrier = rec.get("insurance_carrier")
            if carrier:
                payer_check = validate_payer_code(carrier, known_payers)
                if not payer_check.valid:
                    results.append(payer_check)
                    unknown_payers.add(carrier)

        rec_errors = [r for r in results if r.severity == "ERROR"]
        rec_warnings = [r for r in results if r.severity == "WARNING"]

        if rec_errors:
            errors += 1
            for e in rec_errors[:3]:  # Cap detail output
                error_details.append({"row": i, **e.to_dict()})
        elif rec_warnings:
            warnings += 1
            for w in rec_warnings[:3]:
                warning_details.append({"row": i, **w.to_dict()})
        else:
            valid += 1

        # Track unknowns
        mod = rec.get("modality")
        if mod and mod.upper() not in VALID_MODALITIES:
            unknown_modalities.add(mod)

    return {
        "total": total,
        "valid": valid,
        "warnings": warnings,
        "errors": errors,
        "error_details": error_details[:50],
        "warning_details": warning_details[:50],
        "unknown_payers": sorted(unknown_payers),
        "unknown_modalities": sorted(unknown_modalities),
    }
