"""X12 835 Electronic Remittance Advice (ERA) parser.

Parses ANSI X12 835 EDI files into structured payment and claim data.
Handles ISA/GS/ST envelopes, BPR payment info, TRN trace numbers,
CLP claim-level data, SVC service lines, and CAS adjustment segments.

Segment delimiter: ~ (tilde)
Element delimiter: * (asterisk)
Sub-element delimiter: : (colon)
"""

import os

from datetime import datetime, date


# ── Claim status code mapping ──────────────────────────────────
CLAIM_STATUS_CODES = {
    "1": "PROCESSED_PRIMARY",
    "2": "PROCESSED_SECONDARY",
    "3": "PROCESSED_TERTIARY",
    "4": "DENIED",
    "19": "PROCESSED_PRIMARY_FORWARDED",
    "20": "PROCESSED_SECONDARY_FORWARDED",
    "21": "PROCESSED_TERTIARY_FORWARDED",
    "22": "REVERSAL",
    "23": "NOT_OUR_CLAIM",
    "25": "PREDETERMINATION",
}

# ── CAS group codes ────────────────────────────────────────────
CAS_GROUP_CODES = {
    "CO": "Contractual Obligation",
    "CR": "Correction/Reversal",
    "OA": "Other Adjustment",
    "PI": "Payer Initiated Reduction",
    "PR": "Patient Responsibility",
}


def _parse_date_8(val):
    """Parse CCYYMMDD date string."""
    if not val or len(val) < 8:
        return None
    try:
        return datetime.strptime(val[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _safe_float(val):
    """Convert string to float, return 0.0 on failure."""
    if not val:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _get_element(elements, index, default=""):
    """Safely get element at index."""
    if index < len(elements):
        return elements[index].strip()
    return default


def parse_835(raw_text, filename="unknown"):
    """Parse a raw X12 835 EDI text into structured data.

    Returns dict:
        {
            "filename": str,
            "envelope": { isa/gs/st metadata },
            "payment": {
                "payment_method": str,   # CHK, ACH, FWT, NON
                "payment_amount": float,
                "payment_date": date,
                "check_eft_number": str,
                "payer_name": str,
                "payer_id": str,
                "payee_name": str,
            },
            "claims": [
                {
                    "claim_id": str,
                    "claim_status": str,
                    "billed_amount": float,
                    "paid_amount": float,
                    "patient_name": str,
                    "service_date": date,
                    "adjustments": [
                        {
                            "group_code": str,
                            "reason_code": str,
                            "amount": float,
                        }
                    ],
                    "service_lines": [
                        {
                            "cpt_code": str,
                            "billed_amount": float,
                            "paid_amount": float,
                            "adjustments": [...]
                        }
                    ]
                }
            ],
            "errors": [str],
        }
    """
    result = {
        "filename": filename,
        "envelope": {},
        "payment": {},
        "claims": [],
        "errors": [],
    }

    if not raw_text or not raw_text.strip():
        result["errors"].append("Empty file")
        return result

    # Normalize line endings and whitespace
    raw_text = raw_text.replace("\r\n", "").replace("\r", "").replace("\n", "")

    # Detect delimiters from ISA segment
    # ISA is always 106 characters with fixed positions
    # Element separator is at position 3, segment terminator at position 105
    element_sep = "*"
    segment_sep = "~"

    if raw_text.startswith("ISA") and len(raw_text) >= 106:
        element_sep = raw_text[3]
        segment_sep = raw_text[105]
    elif element_sep not in raw_text:
        result["errors"].append("Cannot detect EDI delimiters — not a valid X12 835 file")
        return result

    # Split into segments
    segments = [s.strip() for s in raw_text.split(segment_sep) if s.strip()]

    current_claim = None
    current_service_line = None
    payer_name = ""
    payee_name = ""

    for seg_text in segments:
        elements = seg_text.split(element_sep)
        seg_id = elements[0].upper() if elements else ""

        # ── ISA: Interchange Control Header ──────────
        if seg_id == "ISA":
            result["envelope"]["isa_sender"] = _get_element(elements, 6)
            result["envelope"]["isa_receiver"] = _get_element(elements, 8)
            result["envelope"]["isa_date"] = _get_element(elements, 9)
            result["envelope"]["isa_control"] = _get_element(elements, 13)

        # ── GS: Functional Group Header ──────────────
        elif seg_id == "GS":
            result["envelope"]["gs_code"] = _get_element(elements, 1)
            result["envelope"]["gs_sender"] = _get_element(elements, 2)
            result["envelope"]["gs_receiver"] = _get_element(elements, 3)

        # ── ST: Transaction Set Header ───────────────
        elif seg_id == "ST":
            result["envelope"]["st_code"] = _get_element(elements, 1)
            result["envelope"]["st_control"] = _get_element(elements, 2)

        # ── BPR: Financial Information ───────────────
        elif seg_id == "BPR":
            method_code = _get_element(elements, 4)
            payment_method = {
                "CHK": "CHK", "ACH": "ACH", "FWT": "FWT", "NON": "NON",
            }.get(method_code, method_code or "CHK")

            result["payment"]["payment_method"] = payment_method
            result["payment"]["payment_amount"] = _safe_float(_get_element(elements, 2))
            # BPR16 (1-indexed) = index 16, but many files vary.
            # Try index 16 first, then search backwards for last 8-digit date.
            pay_date = _parse_date_8(_get_element(elements, 16))
            if not pay_date:
                for idx in range(len(elements) - 1, 2, -1):
                    val = _get_element(elements, idx)
                    if len(val) == 8 and val.isdigit():
                        pay_date = _parse_date_8(val)
                        if pay_date:
                            break
            result["payment"]["payment_date"] = pay_date

        # ── TRN: Reassociation Trace Number ──────────
        elif seg_id == "TRN":
            result["payment"]["check_eft_number"] = _get_element(elements, 2)

        # ── N1: Party Identification ─────────────────
        elif seg_id == "N1":
            qualifier = _get_element(elements, 1)
            name = _get_element(elements, 2)
            if qualifier == "PR":  # Payer
                payer_name = name
                result["payment"]["payer_name"] = name
                result["payment"]["payer_id"] = _get_element(elements, 4)
            elif qualifier == "PE":  # Payee
                payee_name = name
                result["payment"]["payee_name"] = name

        # ── CLP: Claim Payment Information ───────────
        elif seg_id == "CLP":
            # Save previous claim
            if current_claim:
                result["claims"].append(current_claim)

            claim_status_code = _get_element(elements, 2)
            current_claim = {
                "claim_id": _get_element(elements, 1),
                "claim_status_code": claim_status_code,
                "claim_status": CLAIM_STATUS_CODES.get(claim_status_code, claim_status_code),
                "billed_amount": _safe_float(_get_element(elements, 3)),
                "paid_amount": _safe_float(_get_element(elements, 4)),
                "patient_name": "",
                "service_date": None,
                "adjustments": [],
                "service_lines": [],
            }
            current_service_line = None

        # ── NM1: Patient/Subscriber Name (within CLP) ─
        elif seg_id == "NM1" and current_claim:
            qualifier = _get_element(elements, 1)
            if qualifier == "QC":  # Patient
                last = _get_element(elements, 3)
                first = _get_element(elements, 4)
                if last and first:
                    current_claim["patient_name"] = f"{last}, {first}"
                elif last:
                    current_claim["patient_name"] = last

        # ── DTM: Date/Time Reference ────────────────
        elif seg_id == "DTM" and current_claim:
            qualifier = _get_element(elements, 1)
            if qualifier in ("232", "233", "472"):  # Service dates
                current_claim["service_date"] = _parse_date_8(_get_element(elements, 2))

        # ── SVC: Service Payment Information ────────
        elif seg_id == "SVC" and current_claim:
            composite = _get_element(elements, 1)
            # CPT code is in composite: HC:CPT_CODE or format like HC:99213
            cpt_code = ""
            if ":" in composite:
                parts = composite.split(":")
                cpt_code = parts[1] if len(parts) > 1 else parts[0]
            else:
                cpt_code = composite

            current_service_line = {
                "cpt_code": cpt_code,
                "billed_amount": _safe_float(_get_element(elements, 2)),
                "paid_amount": _safe_float(_get_element(elements, 3)),
                "adjustments": [],
            }
            current_claim["service_lines"].append(current_service_line)

        # ── CAS: Claim Adjustment Segment ──────────
        elif seg_id == "CAS":
            group_code = _get_element(elements, 1)

            # CAS can have multiple reason/amount triplets:
            # CAS*CO*45*10.00*PR*1*5.00~
            # Pattern: group, then repeating (reason, amount, [quantity]) triplets
            adjustments = []
            i = 2
            while i < len(elements):
                reason = _get_element(elements, i)
                amount = _safe_float(_get_element(elements, i + 1)) if i + 1 < len(elements) else 0.0
                if reason:
                    adj = {
                        "group_code": group_code,
                        "reason_code": reason,
                        "amount": amount,
                    }
                    adjustments.append(adj)
                i += 3  # Skip reason, amount, quantity

            # Attach to service line if we're inside one, otherwise to claim
            if current_service_line:
                current_service_line["adjustments"].extend(adjustments)
            elif current_claim:
                current_claim["adjustments"].extend(adjustments)

        # ── PLB: Provider Level Balance ──────────────
        elif seg_id == "PLB":
            pass  # Provider-level adjustments (withholding, etc.)

        # ── SE: Transaction Set Trailer ──────────────
        elif seg_id == "SE":
            pass

        # ── GE/IEA: Functional/Interchange trailers ─
        elif seg_id in ("GE", "IEA"):
            pass

    # Save last claim
    if current_claim:
        result["claims"].append(current_claim)

    # Validation
    if not result["payment"].get("payment_amount") and result["payment"].get("payment_amount") != 0:
        result["errors"].append("No BPR (payment) segment found")
    if not result["claims"]:
        result["errors"].append("No CLP (claim) segments found")

    return result


def parse_835_file(filepath, filename=None):
    """Parse an 835 file from disk. Returns parsed result dict."""
    if filename is None:
        filename = os.path.basename(filepath)

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw_text = f.read()

    return parse_835(raw_text, filename=filename)
