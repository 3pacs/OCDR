"""
Payment image ingestion (check images, credit card receipts).
Extracts check number, date, payer, and amount via OCR.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.tasks.celery_app import celery_app


def _ocr_image(file_path: str) -> str:
    """Run Tesseract OCR on a check image (PDF, JPG, or PNG)."""
    ext = Path(file_path).suffix.lower()
    try:
        import pytesseract
        from PIL import Image

        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                images = [page.to_image(resolution=200).original for page in pdf.pages]
            texts = [pytesseract.image_to_string(img) for img in images]
            return "\n".join(texts)
        else:
            img = Image.open(file_path)
            return pytesseract.image_to_string(img)
    except Exception as exc:
        return ""


def _extract_check_fields(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}

    # Check number
    m = re.search(r"(?:check\s*#?|no\.?)\s*:?\s*(\d{4,10})", text, re.IGNORECASE)
    if m:
        fields["check_number"] = m.group(1)

    # Date
    m = re.search(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b", text)
    if m:
        from dateutil import parser as dparser
        try:
            fields["check_date"] = dparser.parse(m.group(1)).date()
        except Exception:
            pass

    # Payer (pay to the order of)
    m = re.search(r"(?:pay to the order of|payable to|from)\s*:?\s*([A-Z][A-Za-z\s,\.]+)", text, re.IGNORECASE)
    if m:
        fields["payer_name"] = m.group(1).strip()[:255]

    # Amount (look for dollar amounts)
    m = re.search(r"\*+\s*\$?([\d,]+\.\d{2})\s*\*+|\$\s*([\d,]+\.\d{2})", text)
    if m:
        amount_str = (m.group(1) or m.group(2) or "").replace(",", "")
        try:
            fields["amount"] = float(amount_str)
        except ValueError:
            pass

    # Memo line
    m = re.search(r"(?:memo|for)\s*:?\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        fields["memo"] = m.group(1).strip()[:255]

    return fields


@celery_app.task(name="app.ingestion.payment_parser.process_payment_image", bind=True)
def process_payment_image(self, file_path: str):
    return asyncio.get_event_loop().run_until_complete(_async_process_payment_image(file_path))


async def _async_process_payment_image(file_path: str) -> Dict[str, Any]:
    from app.database import AsyncSessionLocal
    from app.models.eob import EOB
    from sqlalchemy import select

    text = _ocr_image(file_path)
    fields = _extract_check_fields(text)

    if not fields:
        return {"status": "failed", "file": file_path, "reason": "No fields extracted"}

    async with AsyncSessionLocal() as db:
        # Try to link to existing EOB by check number
        eob_id = None
        if fields.get("check_number"):
            eob_result = await db.execute(
                select(EOB).where(EOB.check_number == fields["check_number"])
            )
            eob = eob_result.scalar_one_or_none()
            if eob:
                eob_id = eob.id

        # Store the image path in the EOB or create a minimal EOB record
        if not eob_id:
            eob = EOB(
                raw_file_path=file_path,
                file_type="image",
                payer_name=fields.get("payer_name"),
                check_number=fields.get("check_number"),
                check_date=fields.get("check_date"),
                total_paid=fields.get("amount"),
                processed_status="needs_review",
                raw_extracted_text=text[:2000],
                extraction_method="tesseract",
                confidence_score=65.0,
            )
            db.add(eob)
            await db.flush()
            eob_id = eob.id

        await db.commit()

    # Move to processed
    src = Path(file_path)
    dest = src.parent / "processed" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    return {
        "status": "success",
        "file": src.name,
        "eob_id": eob_id,
        "extracted_fields": {k: str(v) for k, v in fields.items()},
    }
