"""
Schedule PDF ingestion pipeline.
Implements Step 3 (document ingestion) for appointment schedules.

Strategy:
  1. Try pdfplumber for text-based PDFs
  2. Fall back to pytesseract for scanned/image PDFs
  3. Fuzzy-match extracted patient names against existing patients
  4. Create or link patient records
  5. Create Appointment records with source metadata
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.tasks.celery_app import celery_app


# ── Field extraction helpers ──────────────────────────────────────────────────

DATE_PATTERNS = [
    r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b",
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b",
]

TIME_PATTERN = r"\b(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\b"

MODALITY_KEYWORDS = {
    "MRI": ["mri", "magnetic resonance"],
    "PET_CT": ["pet/ct", "pet ct", "petct"],
    "PET": ["pet scan", "positron"],
    "CT": ["ct scan", "computed tomography", "cat scan"],
    "BONE_SCAN": ["bone scan", "nuclear medicine", "nm bone"],
    "XRAY": ["x-ray", "xray", "radiograph"],
    "ULTRASOUND": ["ultrasound", "sonogram", "echo"],
}


def _extract_date(text: str) -> Optional[date]:
    for pattern in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                from dateutil import parser as dparser
                return dparser.parse(m.group(0)).date()
            except Exception:
                pass
    return None


def _extract_time(text: str) -> Optional[time]:
    m = re.search(TIME_PATTERN, text, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        meridiem = (m.group(3) or "").upper()
        if meridiem == "PM" and hour != 12:
            hour += 12
        elif meridiem == "AM" and hour == 12:
            hour = 0
        return time(hour % 24, minute)
    return None


def _extract_modality(text: str) -> str:
    text_lower = text.lower()
    for modality, keywords in MODALITY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return modality
    return "OTHER"


def _extract_patient_name(text: str) -> Optional[str]:
    """Simple heuristic: look for 'Patient:', 'Name:', or capitalized name patterns."""
    patterns = [
        r"(?:patient|name|pt)[\s:]+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"([A-Z][a-z]+,\s*[A-Z][a-z]+)",  # Last, First format
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_npi(text: str) -> Optional[str]:
    m = re.search(r"\bNPI[\s:]*(\d{10})\b", text, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_auth_number(text: str) -> Optional[str]:
    m = re.search(r"(?:auth(?:orization)?|prior auth)[\s#:]*([A-Z0-9\-]{6,20})", text, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_physician(text: str, label: str = "referring") -> Optional[str]:
    pattern = rf"(?:{label}[\s\w]*physician|{label}[\s\w]*doctor|{label} dr\.?)[\s:]+([A-Z][a-z]+ [A-Z][a-z]+)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def _parse_pdf_text(file_path: str) -> tuple[str, str, float]:
    """
    Try pdfplumber first, fall back to tesseract.
    Returns: (extracted_text, method_used, confidence)
    """
    import pdfplumber

    try:
        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
            text = "\n".join(pages_text).strip()
            if len(text) > 50:
                confidence = min(95.0, 70.0 + len(text) / 100)
                return text, "pdfplumber", round(confidence, 1)
    except Exception:
        pass

    # Fallback: OCR with tesseract
    try:
        import pytesseract
        from PIL import Image
        import pdfplumber

        ocr_pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                img = page.to_image(resolution=200).original
                ocr_pages.append(pytesseract.image_to_string(img))
        text = "\n".join(ocr_pages).strip()
        return text, "tesseract", 60.0
    except Exception:
        return "", "failed", 0.0


@celery_app.task(name="app.ingestion.schedule_parser.process_schedule_pdf", bind=True)
def process_schedule_pdf(self, file_path: str):
    """
    Celery task: parse a schedule PDF and create appointment records.
    """
    return asyncio.get_event_loop().run_until_complete(
        _async_process_schedule_pdf(file_path)
    )


async def _async_process_schedule_pdf(file_path: str) -> Dict[str, Any]:
    """Async implementation of schedule PDF processing."""
    from app.database import AsyncSessionLocal
    from app.models.patient import Patient
    from app.models.appointment import Appointment
    from rapidfuzz import fuzz, process
    from sqlalchemy import select

    raw_text, method, confidence = _parse_pdf_text(file_path)
    if not raw_text:
        return {"status": "failed", "file": file_path, "reason": "Could not extract text"}

    # Parse key fields
    extracted_date = _extract_date(raw_text)
    extracted_time = _extract_time(raw_text)
    patient_name = _extract_patient_name(raw_text)
    modality = _extract_modality(raw_text)
    auth_number = _extract_auth_number(raw_text)
    ordering_npi = _extract_npi(raw_text)
    referring_physician = _extract_physician(raw_text, "referring")
    ordering_physician = _extract_physician(raw_text, "ordering")

    results = []

    async with AsyncSessionLocal() as db:
        # Fuzzy-match patient name
        patient_id = None
        match_confidence = 0.0

        if patient_name:
            all_patients_result = await db.execute(select(Patient))
            all_patients = all_patients_result.scalars().all()
            names = {p.id: p.full_name for p in all_patients}

            if names:
                matches = process.extract(
                    patient_name, names, scorer=fuzz.token_sort_ratio, limit=1,
                    score_cutoff=settings.PATIENT_FUZZY_MATCH_THRESHOLD
                )
                if matches:
                    best_match = matches[0]
                    match_confidence = best_match[1]
                    matched_patient_id = best_match[2]

                    if match_confidence >= settings.PATIENT_FUZZY_MATCH_THRESHOLD:
                        patient_id = matched_patient_id
                        # Flag for review if below high-confidence threshold
                        if match_confidence < settings.PATIENT_REVIEW_THRESHOLD:
                            matched_patient = next(p for p in all_patients if p.id == matched_patient_id)
                            matched_patient.verification_status = "flagged"

        # If no patient matched, create a placeholder
        if not patient_id and patient_name:
            import uuid
            parts = patient_name.split()
            new_patient = Patient(
                mrn=f"MRN-{uuid.uuid4().hex[:8].upper()}",
                first_name=parts[0] if parts else "Unknown",
                last_name=" ".join(parts[1:]) if len(parts) > 1 else "Unknown",
                dob=date(1900, 1, 1),  # placeholder DOB
                verification_status="needs_verification",
                source_file=os.path.basename(file_path),
                extraction_confidence=confidence,
            )
            db.add(new_patient)
            await db.flush()
            patient_id = new_patient.id

        # Create appointment
        if patient_id and extracted_date:
            appt = Appointment(
                patient_id=patient_id,
                scan_date=extracted_date,
                scan_time=extracted_time,
                modality=modality,
                referring_physician=referring_physician,
                ordering_physician=ordering_physician,
                ordering_npi=ordering_npi,
                status="scheduled",
                source_file=os.path.basename(file_path),
                extraction_confidence=confidence,
                raw_extracted_text=raw_text[:2000],
            )
            db.add(appt)
            await db.flush()
            results.append({"appointment_id": appt.id, "patient_id": patient_id})

        await db.commit()

    # Move file to processed folder
    src = Path(file_path)
    dest = src.parent / "processed" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    return {
        "status": "success",
        "file": src.name,
        "method": method,
        "confidence": confidence,
        "patient_name_extracted": patient_name,
        "patient_match_confidence": match_confidence,
        "appointments_created": results,
    }
