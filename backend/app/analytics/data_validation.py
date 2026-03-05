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

from backend.app.analytics.public_code_tables import (
    VALID_CARC_CODES,
    VALID_CLAIM_STATUS_CODES,
    VALID_PAYMENT_METHODS,
    VALID_CAS_GROUP_CODES,
    VALID_RADIOLOGY_CPT_CODES,
    CPT_TO_MODALITY_EXTENDED,
    CARC_CODES,
    CLAIM_STATUS_CODES,
    is_valid_cpt_format,
    is_radiology_cpt_range,
    lookup_carc,
    lookup_claim_status,
    lookup_cpt,
    cpt_to_modality,
)


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

# X12 835 claim status codes — full standard set from public_code_tables
VALID_CLAIM_STATUSES = VALID_CLAIM_STATUS_CODES

CLAIM_STATUS_LABELS = {
    "1": "PAID_PRIMARY",
    "2": "PAID_SECONDARY",
    "3": "PAID_TERTIARY",
    "4": "DENIED",
    "5": "PENDED",
    "10": "RECEIVED_NOT_IN_PROCESS",
    "13": "SUSPENDED",
    "15": "SUSPENDED_INVESTIGATION",
    "16": "SUSPENDED_RETURN_MATERIAL",
    "17": "SUSPENDED_REVIEW_ORG",
    "19": "PRIMARY_FORWARDED",
    "20": "SECONDARY_FORWARDED",
    "21": "TERTIARY_FORWARDED",
    "22": "REVERSAL",
    "23": "NOT_OUR_CLAIM_FORWARDED",
    "25": "PREDETERMINATION",
}

# ANSI X12 Claim Adjustment Group Codes — from public standard
CAS_GROUP_CODES = VALID_CAS_GROUP_CODES

# Full CARC codes from public_code_tables (294 codes)
COMMON_CAS_REASON_CODES = VALID_CARC_CODES

PAYMENT_METHODS = VALID_PAYMENT_METHODS

IMPORT_SOURCES = frozenset({"excel_structured", "excel_flexible", "era_835", "manual"})

# CPT to modality crosswalk — extended version from public_code_tables
CPT_TO_MODALITY = CPT_TO_MODALITY_EXTENDED


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
    """Validate an ERA claim line against public X12/CMS standards."""
    results = []

    # --- Claim status (X12 835 CLP02 standard) ---
    status = record.get("claim_status")
    if status and status not in VALID_CLAIM_STATUSES:
        results.append(ValidationResult(
            False, "claim_status", status,
            f"Unknown X12 claim status '{status}'. Valid codes: {', '.join(sorted(VALID_CLAIM_STATUSES))}",
        ))
    elif status:
        label = lookup_claim_status(status)
        if label and "Denied" in label:
            results.append(ValidationResult(
                True, "claim_status", status,
                f"Claim denied: {label}",
                severity="INFO",
            ))

    # --- CAS group code (X12 standard) ---
    group = record.get("cas_group_code")
    if group and group.upper() not in CAS_GROUP_CODES:
        results.append(ValidationResult(
            False, "cas_group_code", group,
            f"Unknown CAS group code '{group}'. Valid: {', '.join(sorted(CAS_GROUP_CODES))}",
            severity="WARNING",
        ))

    # --- CAS reason code (CARC — full public standard) ---
    reason = record.get("cas_reason_code")
    if reason:
        reason_clean = str(reason).strip()
        if reason_clean not in VALID_CARC_CODES:
            results.append(ValidationResult(
                False, "cas_reason_code", reason,
                f"Unknown CARC code '{reason}'. Not in X12 CARC standard (294 codes)",
                severity="WARNING",
            ))
        else:
            desc = lookup_carc(reason_clean)
            # Flag high-impact denial reasons
            if reason_clean in ("29", "27", "26"):  # Timely filing, coverage terminated, prior to coverage
                results.append(ValidationResult(
                    True, "cas_reason_code", reason,
                    f"Filing/eligibility denial: CARC-{reason_clean} ({desc})",
                    severity="INFO",
                ))

    # --- CPT/HCPCS code format and range validation ---
    cpt = record.get("cpt_code")
    if cpt:
        clean = cpt.strip()
        if not is_valid_cpt_format(clean):
            results.append(ValidationResult(
                False, "cpt_code", cpt,
                f"'{cpt}' is not valid CPT (5 digits) or HCPCS Level II (letter + 4 digits) format",
                severity="WARNING",
            ))
        elif clean.isdigit() and not is_radiology_cpt_range(clean):
            results.append(ValidationResult(
                False, "cpt_code", cpt,
                f"CPT '{cpt}' is outside radiology ranges (70010-76999, 77001-77799, 78000-79999)",
                severity="WARNING",
            ))
        elif clean in VALID_RADIOLOGY_CPT_CODES:
            # Known code — check modality crosswalk consistency
            expected_modality = cpt_to_modality(clean)
            claim_modality = record.get("modality")
            if expected_modality and claim_modality and expected_modality.upper() != claim_modality.upper():
                results.append(ValidationResult(
                    False, "cpt_code", cpt,
                    f"CPT {cpt} ({lookup_cpt(clean)}) maps to {expected_modality}, "
                    f"but claim modality is {claim_modality}",
                    severity="WARNING",
                ))

    # --- Payment method (X12 BPR01 standard) ---
    payment_method = record.get("payment_method")
    if payment_method and payment_method not in VALID_PAYMENT_METHODS:
        results.append(ValidationResult(
            False, "payment_method", payment_method,
            f"Unknown payment method '{payment_method}'. Valid X12 BPR codes: "
            f"{', '.join(sorted(VALID_PAYMENT_METHODS))}",
            severity="WARNING",
        ))

    # --- Paid vs billed sanity ---
    billed = float(record.get("billed_amount", 0) or 0)
    paid = float(record.get("paid_amount", 0) or 0)
    if paid > billed > 0:
        results.append(ValidationResult(
            False, "paid_amount", paid,
            f"Paid (${paid:,.2f}) exceeds billed (${billed:,.2f})",
            severity="WARNING",
        ))

    # --- CAS adjustment amount vs billed-paid delta ---
    cas_adj = float(record.get("cas_adjustment_amount", 0) or 0)
    if cas_adj > 0 and billed > 0 and paid >= 0:
        expected_adj = billed - paid
        if expected_adj > 0 and abs(cas_adj - expected_adj) > 1.0:
            results.append(ValidationResult(
                False, "cas_adjustment_amount", cas_adj,
                f"CAS adjustment (${cas_adj:,.2f}) differs from billed-paid delta "
                f"(${expected_adj:,.2f}) by more than $1.00",
                severity="INFO",
            ))

    return results


def validate_era_payment(record: dict) -> list[ValidationResult]:
    """Validate an ERA payment record against X12 835 standards."""
    results = []

    # Payment method (BPR01)
    method = record.get("payment_method")
    if method and method not in VALID_PAYMENT_METHODS:
        results.append(ValidationResult(
            False, "payment_method", method,
            f"Unknown X12 payment method '{method}'. Valid: {', '.join(sorted(VALID_PAYMENT_METHODS))}",
            severity="WARNING",
        ))

    # Payment amount sanity
    amount = record.get("payment_amount")
    if amount is not None:
        try:
            fval = float(amount)
            if fval < 0:
                results.append(ValidationResult(
                    False, "payment_amount", amount,
                    f"Negative ERA payment amount: ${fval:,.2f}",
                    severity="WARNING",
                ))
            if fval > 1_000_000:
                results.append(ValidationResult(
                    False, "payment_amount", amount,
                    f"Unusually large ERA payment: ${fval:,.2f} — verify",
                    severity="WARNING",
                ))
        except (ValueError, TypeError):
            results.append(ValidationResult(
                False, "payment_amount", amount,
                f"Payment amount is not a valid number: {amount}",
            ))

    # Payment date sanity
    pdate = record.get("payment_date")
    if pdate and isinstance(pdate, date):
        if pdate > date.today():
            results.append(ValidationResult(
                False, "payment_date", pdate,
                "ERA payment date is in the future",
                severity="WARNING",
            ))
        if pdate < date(2010, 1, 1):
            results.append(ValidationResult(
                False, "payment_date", pdate,
                "ERA payment date before 2010 — likely a parsing error",
                severity="WARNING",
            ))

    # Check/EFT number format
    check = record.get("check_eft_number")
    if check:
        check = str(check).strip()
        if len(check) < 2:
            results.append(ValidationResult(
                False, "check_eft_number", check,
                "Check/EFT number too short — likely incomplete",
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


def validate_era_batch(claims: list[dict], payment_info: dict | None = None) -> dict:
    """Validate a batch of ERA claim lines and optional payment header.

    Returns:
        {
            "total": int,
            "valid": int,
            "warnings": int,
            "errors": int,
            "payment_errors": [...],
            "claim_errors": [...],
            "claim_warnings": [...],
            "unknown_carc_codes": set,
            "unknown_cpt_codes": set,
            "non_radiology_cpt_codes": set,
        }
    """
    total = len(claims)
    valid = 0
    warnings = 0
    errors = 0
    payment_errors = []
    claim_errors = []
    claim_warnings = []
    unknown_carc_codes = set()
    unknown_cpt_codes = set()
    non_radiology_cpt_codes = set()

    # Validate payment header
    if payment_info:
        p_results = validate_era_payment(payment_info)
        for r in p_results:
            payment_errors.append(r.to_dict())

    for i, claim in enumerate(claims):
        results = validate_era_claim_line(claim)

        rec_errors = [r for r in results if r.severity == "ERROR"]
        rec_warnings = [r for r in results if r.severity in ("WARNING", "INFO")]

        if rec_errors:
            errors += 1
            for e in rec_errors[:3]:
                claim_errors.append({"claim_index": i, **e.to_dict()})
        elif rec_warnings:
            warnings += 1
            for w in rec_warnings[:3]:
                claim_warnings.append({"claim_index": i, **w.to_dict()})
        else:
            valid += 1

        # Track unknown codes
        reason = claim.get("cas_reason_code")
        if reason and str(reason).strip() not in VALID_CARC_CODES:
            unknown_carc_codes.add(str(reason).strip())

        cpt = claim.get("cpt_code")
        if cpt:
            cpt_clean = str(cpt).strip()
            if cpt_clean.isdigit() and len(cpt_clean) == 5:
                if cpt_clean not in VALID_RADIOLOGY_CPT_CODES:
                    unknown_cpt_codes.add(cpt_clean)
                if not is_radiology_cpt_range(cpt_clean):
                    non_radiology_cpt_codes.add(cpt_clean)

    return {
        "total": total,
        "valid": valid,
        "warnings": warnings,
        "errors": errors,
        "payment_errors": payment_errors[:20],
        "claim_errors": claim_errors[:50],
        "claim_warnings": claim_warnings[:50],
        "unknown_carc_codes": sorted(unknown_carc_codes),
        "unknown_cpt_codes": sorted(unknown_cpt_codes),
        "non_radiology_cpt_codes": sorted(non_radiology_cpt_codes),
    }


# ============================================================
# ENRICHMENT — attach public code descriptions to records
# ============================================================

def enrich_carc_description(reason_code: str | None) -> str | None:
    """Return human-readable description for a CARC reason code."""
    if not reason_code:
        return None
    return lookup_carc(str(reason_code).strip())


def enrich_claim_status_description(status_code: str | None) -> str | None:
    """Return human-readable description for an X12 claim status code."""
    if not status_code:
        return None
    return lookup_claim_status(str(status_code).strip())


def enrich_cpt_description(cpt_code: str | None) -> str | None:
    """Return human-readable description for a radiology CPT code."""
    if not cpt_code:
        return None
    return lookup_cpt(str(cpt_code).strip())
