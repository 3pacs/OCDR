"""
X12 835 ERA Parser (F-02).

Parses .835 and .txt files containing X12 835 Electronic Remittance Advice.
Extracts: ISA/GS/ST envelope, BPR payment, TRN trace, CLP claims,
SVC service lines, CAS adjustments, NM1 names, DTP dates.
"""

import logging
import os
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.era import ERAPayment, ERAClaimLine
from backend.app.analytics.data_validation import (
    validate_era_payment,
    validate_era_claim_line,
)

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> date | None:
    """Parse X12 date format CCYYMMDD to Python date."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _parse_amount(amount_str: str) -> float | None:
    """Parse amount string to float."""
    if not amount_str:
        return None
    try:
        return round(float(amount_str), 2)
    except (ValueError, TypeError):
        return None


def _split_segments(raw: str) -> list[str]:
    """Split raw X12 content into segments using ~ delimiter."""
    raw = raw.strip()
    raw = raw.replace("\r\n", "").replace("\n", "").replace("\r", "")
    segments = [s.strip() for s in raw.split("~") if s.strip()]
    return segments


def _parse_segment(segment: str, delimiter: str = "*") -> list[str]:
    """Split a segment into elements."""
    return segment.split(delimiter)


def parse_835_content(raw_content: str, filename: str) -> dict:
    """
    Parse a single 835 file content.

    Returns dict with:
      - payment: dict of payment-level data (BPR, TRN)
      - claims: list of claim dicts (CLP, SVC, CAS, NM1)
    """
    segments = _split_segments(raw_content)

    # Detect element separator from ISA segment
    element_sep = "*"
    for seg in segments:
        if seg.startswith("ISA"):
            if len(seg) > 3:
                element_sep = seg[3]
            break

    payment_info = {
        "filename": filename,
        "payment_amount": None,
        "payment_date": None,
        "payment_method": None,
        "check_eft_number": None,
        "payer_name": None,
    }

    claims: list[dict] = []
    current_claim: dict | None = None

    for seg_raw in segments:
        elements = _parse_segment(seg_raw, element_sep)
        seg_id = elements[0] if elements else ""

        if seg_id == "BPR":
            payment_info["payment_method"] = elements[1] if len(elements) > 1 else None
            payment_info["payment_amount"] = _parse_amount(elements[2]) if len(elements) > 2 else None
            if len(elements) > 16:
                payment_info["payment_date"] = _parse_date(elements[16])

        elif seg_id == "TRN":
            payment_info["check_eft_number"] = elements[2] if len(elements) > 2 else None

        elif seg_id == "N1":
            if len(elements) > 2 and elements[1] == "PR":
                payment_info["payer_name"] = elements[2]

        elif seg_id == "CLP":
            if current_claim is not None:
                claims.append(current_claim)

            current_claim = {
                "claim_id": elements[1] if len(elements) > 1 else None,
                "claim_status": elements[2] if len(elements) > 2 else None,
                "billed_amount": _parse_amount(elements[3]) if len(elements) > 3 else None,
                "paid_amount": _parse_amount(elements[4]) if len(elements) > 4 else None,
                "patient_name_835": None,
                "service_date_835": None,
                "cpt_code": None,
                "cas_group_code": None,
                "cas_reason_code": None,
                "cas_adjustment_amount": None,
            }

        elif seg_id == "NM1" and current_claim is not None:
            if len(elements) > 1 and elements[1] == "QC":
                last = elements[3] if len(elements) > 3 else ""
                first = elements[4] if len(elements) > 4 else ""
                name = f"{last}, {first}".strip(", ").upper()
                current_claim["patient_name_835"] = name

        elif seg_id == "SVC" and current_claim is not None:
            if len(elements) > 1:
                svc_id = elements[1]
                if ":" in svc_id:
                    parts = svc_id.split(":")
                    current_claim["cpt_code"] = parts[1] if len(parts) > 1 else svc_id
                else:
                    current_claim["cpt_code"] = svc_id

        elif seg_id == "CAS" and current_claim is not None:
            if len(elements) > 1:
                current_claim["cas_group_code"] = elements[1]
            if len(elements) > 2:
                current_claim["cas_reason_code"] = elements[2]
            if len(elements) > 3:
                current_claim["cas_adjustment_amount"] = _parse_amount(elements[3])

        elif seg_id == "DTM" and current_claim is not None:
            if len(elements) > 2 and elements[1] in ("232", "233", "472"):
                current_claim["service_date_835"] = _parse_date(elements[2])

    if current_claim is not None:
        claims.append(current_claim)

    return {"payment": payment_info, "claims": claims}


async def import_835_file(
    file_content: str,
    filename: str,
    session: AsyncSession,
) -> dict:
    """Parse an 835 file and store in era_payments and era_claim_lines."""
    parsed = parse_835_content(file_content, filename)
    payment_data = parsed["payment"]

    # Validate payment header against X12 standards
    payment_warnings = []
    p_results = validate_era_payment(payment_data)
    for r in p_results:
        if not r.valid:
            payment_warnings.append(r.to_dict())
            logger.warning(f"835 payment validation ({filename}): {r.message}")

    era_payment = ERAPayment(
        filename=payment_data["filename"],
        check_eft_number=payment_data["check_eft_number"],
        payment_amount=payment_data["payment_amount"],
        payment_date=payment_data["payment_date"],
        payment_method=payment_data["payment_method"],
        payer_name=payment_data["payer_name"],
    )
    session.add(era_payment)
    await session.flush()

    claim_warnings = []
    for claim_data in parsed["claims"]:
        # Validate each claim against CARC/CPT/X12 standards
        c_results = validate_era_claim_line(claim_data)
        for r in c_results:
            if not r.valid:
                claim_warnings.append({
                    "claim_id": claim_data.get("claim_id"),
                    **r.to_dict(),
                })
                logger.warning(
                    f"835 claim validation ({filename}, claim {claim_data.get('claim_id')}): "
                    f"{r.message}"
                )

        claim_line = ERAClaimLine(
            era_payment_id=era_payment.id,
            claim_id=claim_data["claim_id"],
            claim_status=claim_data["claim_status"],
            billed_amount=claim_data["billed_amount"],
            paid_amount=claim_data["paid_amount"],
            patient_name_835=claim_data["patient_name_835"],
            service_date_835=claim_data["service_date_835"],
            cpt_code=claim_data["cpt_code"],
            cas_group_code=claim_data["cas_group_code"],
            cas_reason_code=claim_data["cas_reason_code"],
            cas_adjustment_amount=claim_data["cas_adjustment_amount"],
        )
        session.add(claim_line)

    await session.commit()

    logger.info(
        f"835 import: {filename} — payment=${payment_data['payment_amount']}, "
        f"{len(parsed['claims'])} claims, "
        f"{len(payment_warnings)} payment warnings, {len(claim_warnings)} claim warnings"
    )

    return {
        "filename": filename,
        "payment_amount": payment_data["payment_amount"],
        "check_eft_number": payment_data["check_eft_number"],
        "payer_name": payment_data["payer_name"],
        "claims_found": len(parsed["claims"]),
        "validation_warnings": {
            "payment": payment_warnings[:10],
            "claims": claim_warnings[:50],
        },
    }


async def import_835_folder(
    folder_path: str,
    session: AsyncSession,
) -> dict:
    """Scan a folder for .835 and .edi files and parse them all."""
    results = []
    total_claims = 0

    if not os.path.isdir(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    for fname in sorted(os.listdir(folder_path)):
        if fname.lower().endswith((".835", ".edi", ".txt")):
            fpath = os.path.join(folder_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                result = await import_835_file(content, fname, session)
                results.append(result)
                total_claims += result["claims_found"]
            except Exception as e:
                logger.error(f"Error parsing {fname}: {e}")
                results.append({"filename": fname, "error": str(e)})

    return {
        "files_parsed": len(results),
        "claims_found": total_claims,
        "details": results,
    }
