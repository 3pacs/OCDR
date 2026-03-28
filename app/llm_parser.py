"""
Local LLM integration via Ollama for document parsing.

Supports Hermes, Llama, Qwen models running locally.
Extracts patient info (name, DOB, address) from scanned documents.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OCR extraction (Tesseract + OpenCV preprocessing)
# ---------------------------------------------------------------------------


def extract_text_from_image(image_path: str) -> str:
    """Extract text from an image using Tesseract OCR with preprocessing."""
    try:
        import cv2
        import pytesseract

        img = cv2.imread(image_path)
        if img is None:
            return ""

        # Preprocessing: grayscale, threshold, denoise
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 3)
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        text = pytesseract.image_to_string(thresh, config="--psm 6")
        return text.strip()
    except ImportError:
        logger.warning("pytesseract or cv2 not installed, falling back to basic OCR")
        return _fallback_ocr(image_path)
    except Exception as e:
        logger.error("OCR failed for %s: %s", image_path, e)
        return ""


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file."""
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)
    except ImportError:
        logger.warning("pdfplumber not installed")
        return ""
    except Exception as e:
        logger.error("PDF extraction failed for %s: %s", pdf_path, e)
        return ""


def _fallback_ocr(image_path: str) -> str:
    """Fallback OCR using tesseract CLI directly."""
    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# LLM parsing via Ollama
# ---------------------------------------------------------------------------

PARSE_PROMPT = """You are a medical document parser. Analyze the following text extracted from a scanned document.

Extract the following information and return ONLY valid JSON with these fields:
{
  "document_type": "one of: drivers_license, state_id, insurance_card, lab_result, medical_record, prescription, referral, consent_form, imaging_report, other",
  "patient_name": "full name as found on document or null",
  "first_name": "first name or null",
  "last_name": "last name or null",
  "date_of_birth": "MM/DD/YYYY format or null",
  "address": "full address as found on document or null",
  "phone": "phone number or null",
  "insurance_carrier": "insurance company name or null",
  "policy_number": "insurance policy/member ID or null",
  "document_date": "date on the document or null",
  "summary": "brief 1-2 sentence summary of what this document is"
}

If a field cannot be determined from the text, set it to null.
For IDs (driver's license, state ID), extract the name, DOB, and address carefully.

DOCUMENT TEXT:
---
{text}
---

Return ONLY the JSON object, no other text."""


MATCH_PROMPT = """Given these patient records in the system and the extracted document info, which patient is the best match?

PATIENTS IN SYSTEM:
{patients}

EXTRACTED FROM DOCUMENT:
Name: {name}
DOB: {dob}
Address: {address}

Return ONLY valid JSON:
{{
  "matched_patient_id": <integer ID of best match or null if no match>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "brief explanation"
}}

Return ONLY the JSON object."""


def query_ollama(prompt: str, model: str = "hermes3",
                 base_url: str = "http://localhost:11434") -> str:
    """Send a prompt to Ollama and return the response text."""
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024,
                }
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.ConnectionError:
        logger.error("Cannot connect to Ollama at %s. Is it running?", base_url)
        raise RuntimeError(
            f"Cannot connect to Ollama at {base_url}. "
            "Make sure Ollama is running: 'ollama serve'"
        )
    except Exception as e:
        logger.error("Ollama query failed: %s", e)
        raise


def query_ollama_vision(image_path: str, prompt: str, model: str = "llama3.2-vision",
                        base_url: str = "http://localhost:11434") -> str:
    """Send an image directly to a vision-capable model via Ollama."""
    import base64

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1024,
                }
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.error("Ollama vision query failed: %s", e)
        raise


def parse_document(file_path: str, model: str = "hermes3",
                   base_url: str = "http://localhost:11434") -> dict:
    """
    Full pipeline: OCR the document, then LLM-parse the extracted text.
    Returns parsed JSON dict with patient info.
    """
    ext = Path(file_path).suffix.lower()

    # Step 1: Extract text via OCR or PDF parser
    if ext == ".pdf":
        raw_text = extract_text_from_pdf(file_path)
        # If PDF has no text (scanned), try OCR on rendered pages
        if not raw_text.strip():
            raw_text = _ocr_pdf_pages(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"):
        raw_text = extract_text_from_image(file_path)
    else:
        raw_text = ""

    if not raw_text.strip():
        return {
            "error": "No text could be extracted from document",
            "raw_text": "",
            "parsed": {},
        }

    # Step 2: Send to LLM for structured extraction
    prompt = PARSE_PROMPT.format(text=raw_text[:4000])  # limit context
    llm_response = query_ollama(prompt, model=model, base_url=base_url)

    # Step 3: Parse JSON from LLM response
    parsed = _extract_json(llm_response)

    return {
        "raw_text": raw_text,
        "llm_response": llm_response,
        "parsed": parsed,
    }


def match_patient(extracted_info: dict, patients: list,
                  model: str = "hermes3",
                  base_url: str = "http://localhost:11434") -> dict:
    """
    Use LLM to match extracted document info to an existing patient.
    Returns dict with matched_patient_id, confidence, reasoning.
    """
    patient_list = "\n".join(
        f"ID: {p['id']}, Name: {p['full_name']}, DOB: {p.get('date_of_birth', 'N/A')}"
        for p in patients
    )

    prompt = MATCH_PROMPT.format(
        patients=patient_list,
        name=extracted_info.get("patient_name", "unknown"),
        dob=extracted_info.get("date_of_birth", "unknown"),
        address=extracted_info.get("address", "unknown"),
    )

    llm_response = query_ollama(prompt, model=model, base_url=base_url)
    return _extract_json(llm_response)


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response text."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in the response
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return {"error": "Could not parse LLM response", "raw_response": text}


def _ocr_pdf_pages(pdf_path: str) -> str:
    """Render PDF pages to images and OCR them."""
    try:
        import pdfplumber
        from PIL import Image

        texts = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:10]):  # limit to 10 pages
                img = page.to_image(resolution=300)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    img.save(tmp.name)
                    text = extract_text_from_image(tmp.name)
                    if text:
                        texts.append(text)
                    Path(tmp.name).unlink(missing_ok=True)
        return "\n".join(texts)
    except Exception as e:
        logger.error("PDF OCR fallback failed: %s", e)
        return ""
