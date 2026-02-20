"""
EOB PDF ingestion pipeline.
Parses EOB documents, extracts line items, and runs the matching engine.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.matching.engine import EOBLineData, match_eob_line, run_reconciliation
from app.tasks.celery_app import celery_app


def _extract_check_info(text: str) -> Dict[str, Any]:
    """Extract check number, date, payer name, and total from EOB header."""
    result: Dict[str, Any] = {}

    # Check number
    m = re.search(r"(?:check|eft|payment)\s*#?\s*:?\s*(\w{4,20})", text, re.IGNORECASE)
    if m:
        result["check_number"] = m.group(1)

    # Check date
    m = re.search(r"(?:check|payment|issue)\s*date\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", text, re.IGNORECASE)
    if m:
        from dateutil import parser as dparser
        try:
            result["check_date"] = dparser.parse(m.group(1)).date()
        except Exception:
            pass

    # Payer name — first non-blank line or after "From:"
    m = re.search(r"(?:from|payer|insurance company)\s*:?\s*([A-Z][A-Za-z\s,\.]+)", text, re.IGNORECASE)
    if m:
        result["payer_name"] = m.group(1).strip()[:255]

    # NPI
    m = re.search(r"\bNPI[\s:]*(\d{10})\b", text, re.IGNORECASE)
    if m:
        result["npi"] = m.group(1)

    # Total paid
    m = re.search(r"(?:total\s*(?:payment|paid|amount))\s*:?\s*\$?([\d,]+\.\d{2})", text, re.IGNORECASE)
    if m:
        result["total_paid"] = float(m.group(1).replace(",", ""))

    return result


def _extract_line_items(text: str) -> List[Dict[str, Any]]:
    """
    Extract individual claim lines from EOB text.
    Looks for rows with: patient name, DOS, CPT, billed, allowed, paid amounts.
    This is a heuristic parser — payer templates improve accuracy over time.
    """
    lines = []
    # Pattern: date | cpt | billed | allowed | paid (flexible whitespace)
    # Also tries to grab patient name from preceding text
    line_pattern = re.compile(
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+"  # DOS
        r"(\d{5}(?:-\d+)?)\s+"                      # CPT code
        r"\$?([\d,]+\.\d{2})\s+"                    # billed
        r"\$?([\d,]+\.\d{2})\s+"                    # allowed
        r"\$?([\d,]+\.\d{2})"                        # paid
    )

    for m in line_pattern.finditer(text):
        from dateutil import parser as dparser
        try:
            dos = dparser.parse(m.group(1)).date()
        except Exception:
            continue

        # Look backward for patient name
        start = max(0, m.start() - 200)
        context = text[start:m.start()]
        name_m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})", context)
        patient_name = name_m.group(1) if name_m else "Unknown"

        # Adjustment codes (CO-45, PR-2, etc.)
        adj_context = text[m.end():m.end() + 100]
        adj_codes = re.findall(r"(CO|PR|OA|PI|CR)-(\d+)\s+\$?([\d,]+\.\d{2})?", adj_context)

        lines.append({
            "patient_name": patient_name,
            "date_of_service": dos,
            "cpt_code": m.group(2),
            "billed_amount": float(m.group(3).replace(",", "")),
            "allowed_amount": float(m.group(4).replace(",", "")),
            "paid_amount": float(m.group(5).replace(",", "")),
            "adjustment_codes": [
                {"code": f"{g[0]}-{g[1]}", "amount": float(g[2].replace(",", "") if g[2] else "0")}
                for g in adj_codes
            ],
        })

    return lines


def _parse_pdf_text(file_path: str) -> tuple[str, str, float]:
    """Try pdfplumber, fall back to tesseract."""
    import pdfplumber
    try:
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages).strip()
            if len(text) > 50:
                return text, "pdfplumber", 85.0
    except Exception:
        pass
    try:
        import pytesseract
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            pages = [pytesseract.image_to_string(p.to_image(resolution=200).original) for p in pdf.pages]
        return "\n".join(pages).strip(), "tesseract", 60.0
    except Exception:
        return "", "failed", 0.0


@celery_app.task(name="app.ingestion.eob_parser.process_eob_pdf", bind=True)
def process_eob_pdf(self, file_path: str):
    return asyncio.get_event_loop().run_until_complete(_async_process_eob_pdf(file_path))


async def _async_process_eob_pdf(file_path: str) -> Dict[str, Any]:
    from app.database import AsyncSessionLocal
    from app.models.eob import EOB, EOBLineItem
    from app.models.payment import Payment
    from datetime import datetime, timezone

    raw_text, method, confidence = _parse_pdf_text(file_path)
    if not raw_text:
        return {"status": "failed", "file": file_path}

    header = _extract_check_info(raw_text)
    line_items_data = _extract_line_items(raw_text)

    async with AsyncSessionLocal() as db:
        # Create EOB record
        eob = EOB(
            raw_file_path=file_path,
            file_type="pdf",
            payer_name=header.get("payer_name"),
            check_number=header.get("check_number"),
            check_date=header.get("check_date"),
            npi=header.get("npi"),
            total_paid=header.get("total_paid"),
            processed_status="processing",
            raw_extracted_text=raw_text[:5000],
            extraction_method=method,
            confidence_score=confidence,
        )
        db.add(eob)
        await db.flush()

        matched_claim_ids = []
        needs_review = False

        for item_data in line_items_data:
            line_data = EOBLineData(
                patient_name=item_data["patient_name"],
                date_of_service=item_data["date_of_service"],
                cpt_codes=[item_data["cpt_code"]],
                check_number=header.get("check_number"),
                paid_amount=item_data.get("paid_amount"),
                billed_amount=item_data.get("billed_amount"),
            )
            match_result = await match_eob_line(line_data, db)

            line_item = EOBLineItem(
                eob_id=eob.id,
                claim_id=match_result.claim_id,
                patient_name_raw=item_data["patient_name"],
                date_of_service=item_data["date_of_service"],
                cpt_code=item_data["cpt_code"],
                billed_amount=item_data.get("billed_amount"),
                allowed_amount=item_data.get("allowed_amount"),
                paid_amount=item_data.get("paid_amount"),
                adjustment_codes=item_data.get("adjustment_codes"),
                match_confidence=match_result.confidence,
                match_pass=match_result.pass_name,
                match_status="matched" if match_result.claim_id and not match_result.needs_review else
                             ("manual_review" if match_result.needs_review else "unmatched"),
            )
            db.add(line_item)

            if match_result.claim_id:
                matched_claim_ids.append(match_result.claim_id)

                # Auto-post if above threshold
                if match_result.confidence >= settings.EOB_AUTO_POST_THRESHOLD and not match_result.needs_review:
                    from app.models.appointment import Appointment
                    from app.models.scan import Scan
                    from app.models.claim import Claim
                    from sqlalchemy import select
                    claim_result = await db.execute(
                        select(Claim).where(Claim.id == match_result.claim_id)
                    )
                    claim = claim_result.scalar_one_or_none()
                    if claim:
                        # Get patient_id through scan → appointment
                        scan_result = await db.execute(select(Scan).where(Scan.id == claim.scan_id))
                        scan = scan_result.scalar_one_or_none()
                        if scan:
                            appt_result = await db.execute(
                                select(Appointment).where(Appointment.id == scan.appointment_id)
                            )
                            appt = appt_result.scalar_one_or_none()
                            if appt:
                                payment = Payment(
                                    patient_id=appt.patient_id,
                                    claim_id=match_result.claim_id,
                                    eob_id=eob.id,
                                    payment_date=header.get("check_date") or date.today(),
                                    payment_type="insurance_check",
                                    amount=item_data.get("paid_amount", 0),
                                    check_number=header.get("check_number"),
                                    eob_source_file=os.path.basename(file_path),
                                    posting_status="posted",
                                    posted_by="auto_matching_engine",
                                    posted_date=datetime.now(timezone.utc),
                                    match_confidence=match_result.confidence,
                                    match_pass=match_result.pass_name,
                                )
                                db.add(payment)
                                await run_reconciliation(
                                    match_result.claim_id, item_data.get("paid_amount", 0), db
                                )
                else:
                    needs_review = True

        eob.matched_claim_ids = matched_claim_ids
        eob.processed_status = "needs_review" if needs_review else "processed"
        eob.processed_at = datetime.now(timezone.utc)

        await db.commit()

    # Move to processed folder
    src = Path(file_path)
    dest = src.parent / "processed" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    return {
        "status": "success",
        "eob_id": eob.id,
        "payer": header.get("payer_name"),
        "line_items": len(line_items_data),
        "matched_claims": len(matched_claim_ids),
        "needs_review": needs_review,
    }
