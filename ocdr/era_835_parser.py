"""
X12 835 Electronic Remittance Advice (ERA) parser.

Parses 835 EDI files that contain payment/claim data from insurance payers.

Segment structure:
  - ``~`` is the segment terminator
  - ``*`` is the element separator
  - Segments: ISA, GS, ST, BPR, TRN, N1, CLP, SVC, CAS, DTM, NM1, SE, GE, IEA

Data flow:
  1. Read raw 835 text
  2. Split on ``~`` to get segments
  3. Parse envelope (ISA/GS/ST) for metadata
  4. Parse BPR for payment info (method, amount, date)
  5. Parse TRN for check/EFT number
  6. Parse N1*PR for payer name
  7. For each CLP: extract claim-level data
  8. Under each CLP: parse SVC (service lines), CAS (adjustments),
     DTM (dates), NM1 (patient name)
  9. Return structured dict ready for matching and reconciliation
"""

from pathlib import Path
from datetime import date
from decimal import Decimal
from typing import Optional

from ocdr import logger
from ocdr.normalizers import (
    normalize_patient_name, normalize_decimal, parse_date_flexible,
    normalize_payer_code,
)


def parse_835_file(filepath: str | Path) -> dict:
    """Parse a single 835 EDI file into a structured dict.

    Returns::

        {
            "file": str,
            "envelope": {...},
            "payment": {
                "method": str,    # BPR01: CHK, ACH, NON
                "amount": Decimal, # BPR02
                "date": date,     # BPR16
            },
            "check_eft_number": str,  # TRN02
            "payer_name": str,        # N1*PR
            "claims": [
                {
                    "claim_id": str,          # CLP01
                    "claim_status": str,      # CLP02
                    "billed_amount": Decimal,  # CLP03
                    "paid_amount": Decimal,    # CLP04
                    "patient_name": str,       # NM1*QC
                    "service_date": date,      # DTM*232
                    "service_lines": [{...}],  # SVC segments
                    "adjustments": [{...}],    # CAS segments
                },
                ...
            ],
        }
    """
    path = Path(filepath)
    raw = path.read_text(encoding="utf-8", errors="replace")
    result = parse_835_text(raw, source_file=path.name)
    logger.log_import_summary(
        source=f"835:{path.name}",
        records_in=len(result.get("claims", [])),
        records_out=len(result.get("claims", [])),
        errors=[],
        warnings=[],
    )
    return result


def parse_835_text(text: str, source_file: str = "") -> dict:
    """Parse raw 835 EDI text into a structured dict."""
    # Clean and split into segments
    text = text.replace("\n", "").replace("\r", "")
    segments = [s.strip() for s in text.split("~") if s.strip()]

    result = {
        "file": source_file,
        "envelope": {},
        "payment": {
            "method": "",
            "amount": Decimal("0.00"),
            "date": None,
        },
        "check_eft_number": "",
        "payer_name": "",
        "claims": [],
    }

    current_claim: Optional[dict] = None
    errors: list[dict] = []

    for seg_idx, segment in enumerate(segments):
        elements = segment.split("*")
        seg_id = elements[0] if elements else ""

        try:
            if seg_id == "ISA":
                result["envelope"]["isa"] = _parse_isa(elements)

            elif seg_id == "GS":
                result["envelope"]["gs"] = _parse_gs(elements)

            elif seg_id == "ST":
                result["envelope"]["st"] = _safe_get(elements, 1, "")

            elif seg_id == "BPR":
                result["payment"] = _parse_bpr(elements)

            elif seg_id == "TRN":
                result["check_eft_number"] = _safe_get(elements, 2, "")

            elif seg_id == "N1":
                # N1*PR = payer, N1*PE = payee
                qualifier = _safe_get(elements, 1, "")
                if qualifier == "PR":
                    result["payer_name"] = _safe_get(elements, 2, "")

            elif seg_id == "CLP":
                # Start a new claim
                if current_claim is not None:
                    result["claims"].append(current_claim)
                current_claim = _parse_clp(elements)

            elif seg_id == "SVC" and current_claim is not None:
                svc = _parse_svc(elements)
                current_claim["service_lines"].append(svc)

            elif seg_id == "CAS" and current_claim is not None:
                adj = _parse_cas(elements)
                current_claim["adjustments"].append(adj)

            elif seg_id == "DTM" and current_claim is not None:
                qualifier = _safe_get(elements, 1, "")
                date_val = _parse_edi_date(_safe_get(elements, 2, ""))
                if qualifier == "232":  # Service period start
                    current_claim["service_date"] = date_val
                elif qualifier == "233":  # Service period end
                    current_claim["service_date_end"] = date_val
                elif qualifier == "050":  # Received date
                    current_claim["received_date"] = date_val

            elif seg_id == "NM1" and current_claim is not None:
                qualifier = _safe_get(elements, 1, "")
                if qualifier == "QC":  # Patient
                    last = _safe_get(elements, 3, "")
                    first = _safe_get(elements, 4, "")
                    if last or first:
                        raw = f"{last}, {first}" if first else last
                        current_claim["patient_name"] = normalize_patient_name(raw)
                elif qualifier == "82":  # Rendering provider
                    last = _safe_get(elements, 3, "")
                    first = _safe_get(elements, 4, "")
                    current_claim["rendering_provider"] = (
                        f"{last}, {first}" if first else last
                    ).upper()

            elif seg_id == "SE":
                # End of transaction — finalize last claim
                if current_claim is not None:
                    result["claims"].append(current_claim)
                    current_claim = None

        except Exception as e:
            errors.append({
                "segment_idx": seg_idx,
                "segment": segment[:200],
                "error": str(e),
            })
            logger.log_error(
                "835_parse_segment",
                {"segment_idx": seg_idx, "segment": segment[:200]},
                e,
                suggested_fix=f"Check segment {seg_id} format. "
                              f"Expected X12 835 standard structure.",
            )

    # Catch any remaining open claim
    if current_claim is not None:
        result["claims"].append(current_claim)

    # Normalize payer name
    result["payer_name"] = normalize_payer_code(result["payer_name"])

    logger.log_import_summary(
        source=f"835_text:{source_file}",
        records_in=len(segments),
        records_out=len(result["claims"]),
        errors=errors,
        warnings=[],
    )
    return result


def parse_835_folder(folder_path: str | Path) -> list[dict]:
    """Parse all 835/EDI files in a folder.

    Returns a list of parsed 835 dicts (one per file).
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        logger.log_warning("835_folder", f"Not a directory: {folder}", {})
        return []

    results = []
    for ext in ("*.835", "*.edi", "*.EDI", "*.835"):
        for f in sorted(folder.glob(ext)):
            try:
                parsed = parse_835_file(f)
                results.append(parsed)
            except Exception as e:
                logger.log_error(
                    "835_file_parse",
                    {"file": str(f)},
                    e,
                    suggested_fix="Verify the file is a valid X12 835 EDI file.",
                )
    return results


def flatten_claims(parsed_files: list[dict]) -> list[dict]:
    """Flatten parsed 835 data into a flat list of claim dicts.

    Each claim gets enriched with payment-level info (payer, check number,
    payment date) for easier matching and reporting.
    """
    flat = []
    for pf in parsed_files:
        payer = pf.get("payer_name", "")
        check = pf.get("check_eft_number", "")
        payment_date = pf.get("payment", {}).get("date")
        payment_method = pf.get("payment", {}).get("method", "")

        for claim in pf.get("claims", []):
            enriched = dict(claim)
            enriched["payer_name"] = payer
            enriched["check_eft_number"] = check
            enriched["payment_date"] = payment_date
            enriched["payment_method"] = payment_method
            enriched["source_file"] = pf.get("file", "")
            # Extract CPT codes from service lines
            enriched["cpt_codes"] = [
                sl.get("cpt_code", "") for sl in claim.get("service_lines", [])
            ]
            flat.append(enriched)
    return flat


def match_835_to_billing(claims: list[dict],
                          billing_records: list[dict]) -> list[dict]:
    """Match 835 claims to billing records using BR-09 cross-reference.

    Uses ``compute_match_score`` from business_rules for per-field scoring.
    ALL fields must agree for 100% confidence — any single mismatch
    flags the record for human review.

    Returns a list of match result dicts::

        {
            "claim": dict,
            "billing_record": dict or None,
            "match_score": dict,   # from compute_match_score
            "status": "AUTO_ACCEPT" | "REVIEW" | "UNMATCHED",
        }
    """
    from ocdr.business_rules import compute_match_score
    from ocdr.config import MATCH_AUTO_ACCEPT, MATCH_REVIEW

    results = []
    used_billing: set[int] = set()  # indices of billing records already matched

    for claim in claims:
        best_match = None
        best_score_val = 0.0
        best_score_detail = None
        best_idx = -1

        for idx, br in enumerate(billing_records):
            if idx in used_billing:
                continue

            score_detail = compute_match_score(br, claim)
            score_val = score_detail["score"]

            if score_val > best_score_val:
                best_score_val = score_val
                best_score_detail = score_detail
                best_match = br
                best_idx = idx

        if best_match is not None and best_score_val >= MATCH_REVIEW:
            used_billing.add(best_idx)
            status = "AUTO_ACCEPT" if best_score_val >= MATCH_AUTO_ACCEPT else "REVIEW"
            result = {
                "claim": claim,
                "billing_record": best_match,
                "match_score": best_score_detail,
                "status": status,
            }
            logger.log_match_result(
                billing=best_match,
                era_claim=claim,
                score_breakdown=best_score_detail,
                decision=status,
            )
        else:
            result = {
                "claim": claim,
                "billing_record": None,
                "match_score": best_score_detail or {"score": 0.0, "mismatches": ["No suitable match found"]},
                "status": "UNMATCHED",
            }
            logger.log_match_result(
                billing=None,
                era_claim=claim,
                score_breakdown=result["match_score"],
                decision="UNMATCHED",
            )

        results.append(result)

    return results


# ── Internal segment parsers ──────────────────────────────────────────────


def _parse_isa(elements: list[str]) -> dict:
    """Parse ISA envelope segment."""
    return {
        "sender_id": _safe_get(elements, 6, "").strip(),
        "receiver_id": _safe_get(elements, 8, "").strip(),
        "date": _safe_get(elements, 9, ""),
        "time": _safe_get(elements, 10, ""),
        "control_number": _safe_get(elements, 13, "").strip(),
    }


def _parse_gs(elements: list[str]) -> dict:
    """Parse GS functional group segment."""
    return {
        "functional_id": _safe_get(elements, 1, ""),
        "sender_code": _safe_get(elements, 2, ""),
        "receiver_code": _safe_get(elements, 3, ""),
        "date": _safe_get(elements, 4, ""),
        "group_control": _safe_get(elements, 6, ""),
    }


def _parse_bpr(elements: list[str]) -> dict:
    """Parse BPR payment segment."""
    method = _safe_get(elements, 1, "")
    amount_str = _safe_get(elements, 2, "0")
    date_str = _safe_get(elements, 16, "")

    return {
        "method": method,
        "amount": normalize_decimal(amount_str),
        "date": _parse_edi_date(date_str),
    }


def _parse_clp(elements: list[str]) -> dict:
    """Parse CLP claim-level segment."""
    # CLP status codes: 1=Processed Primary, 2=Processed Secondary,
    # 3=Processed Tertiary, 4=Denied, 19=Processed Primary+Forwarded,
    # 20=Processed Secondary+Forwarded, 22=Reversal
    status_code = _safe_get(elements, 2, "")
    status_map = {
        "1": "PROCESSED_PRIMARY",
        "2": "PROCESSED_SECONDARY",
        "3": "PROCESSED_TERTIARY",
        "4": "DENIED",
        "19": "PROCESSED_PRIMARY_FORWARDED",
        "20": "PROCESSED_SECONDARY_FORWARDED",
        "22": "REVERSAL",
    }

    return {
        "claim_id": _safe_get(elements, 1, ""),
        "claim_status_code": status_code,
        "claim_status": status_map.get(status_code, f"UNKNOWN_{status_code}"),
        "billed_amount": normalize_decimal(_safe_get(elements, 3, "0")),
        "paid_amount": normalize_decimal(_safe_get(elements, 4, "0")),
        "patient_responsibility": normalize_decimal(_safe_get(elements, 5, "0")),
        "claim_filing_indicator": _safe_get(elements, 6, ""),
        "reference_id": _safe_get(elements, 7, ""),
        # Fields populated by subsequent segments
        "patient_name": "",
        "rendering_provider": "",
        "service_date": None,
        "service_date_end": None,
        "received_date": None,
        "service_lines": [],
        "adjustments": [],
    }


def _parse_svc(elements: list[str]) -> dict:
    """Parse SVC service line segment."""
    # SVC01 is a composite: procedure_id:cpt_code
    # e.g., "HC:70553" where HC = HCPCS, 70553 = CPT code
    procedure_composite = _safe_get(elements, 1, "")
    parts = procedure_composite.split(":")
    procedure_qualifier = parts[0] if parts else ""
    cpt_code = parts[1] if len(parts) > 1 else procedure_composite

    return {
        "procedure_qualifier": procedure_qualifier,
        "cpt_code": cpt_code,
        "billed_amount": normalize_decimal(_safe_get(elements, 2, "0")),
        "paid_amount": normalize_decimal(_safe_get(elements, 3, "0")),
        "revenue_code": _safe_get(elements, 4, ""),
        "units": _safe_get(elements, 5, "1"),
    }


def _parse_cas(elements: list[str]) -> dict:
    """Parse CAS claim adjustment segment.

    CAS segments can have up to 6 reason/amount groups:
      CAS*group*reason1*amount1*reason2*amount2*...
    """
    group_code = _safe_get(elements, 1, "")
    # Adjustment group codes: CO=Contractual, PR=Patient Responsibility,
    # OA=Other, PI=Payor Initiated
    group_map = {
        "CO": "CONTRACTUAL",
        "PR": "PATIENT_RESPONSIBILITY",
        "OA": "OTHER",
        "PI": "PAYOR_INITIATED",
    }

    adjustments = []
    # Reason/amount pairs start at index 2, in groups of 3
    # (reason_code, amount, quantity) but quantity is optional
    i = 2
    while i < len(elements):
        reason = _safe_get(elements, i, "")
        amount = normalize_decimal(_safe_get(elements, i + 1, "0"))
        if reason:
            adjustments.append({
                "reason_code": reason,
                "amount": amount,
            })
        i += 3  # skip optional quantity field

    return {
        "group_code": group_code,
        "group_name": group_map.get(group_code, group_code),
        "adjustments": adjustments,
        "total_adjustment": sum(
            (a["amount"] for a in adjustments), Decimal("0.00")
        ),
    }


def _parse_edi_date(date_str: str) -> Optional[date]:
    """Parse CCYYMMDD date format used in EDI."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except (ValueError, TypeError):
        return None


def _safe_get(elements: list[str], idx: int, default: str = "") -> str:
    """Safely get an element from a segment, returning default if missing."""
    if idx < len(elements):
        return elements[idx]
    return default
