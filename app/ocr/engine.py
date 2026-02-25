"""PDF text extraction engine.

Strategy:
  1. Try pdfplumber first — works on digitally-created PDFs (most common)
  2. If a page yields no text, fall back to pytesseract for scanned images
  3. Also attempt table extraction via pdfplumber for structured schedules

All processing is 100% local.
"""

import logging
from io import BytesIO

import pdfplumber

log = logging.getLogger(__name__)

# Optional imports — graceful fallback if tesseract isn't installed
try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    log.info("pytesseract not available — OCR fallback disabled")


def extract_pdf(pdf_path):
    """Extract text and tables from every page of a PDF.

    Returns list of dicts, one per page:
      {
        'page': int,
        'text': str,             # full page text
        'tables': list[list],    # extracted tables (list of rows)
        'method': str,           # 'pdfplumber' or 'tesseract'
      }
    """
    pages = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            text = page.extract_text() or ''
            tables = page.extract_tables() or []
            method = 'pdfplumber'

            # If pdfplumber got no text, try tesseract on the page image
            if len(text.strip()) < 20 and HAS_TESSERACT:
                try:
                    img = page.to_image(resolution=300)
                    pil_img = img.original
                    text = pytesseract.image_to_string(pil_img)
                    method = 'tesseract'
                except Exception as exc:
                    log.warning("Tesseract failed on page %d of %s: %s", page_num, pdf_path, exc)

            pages.append({
                'page': page_num,
                'text': text.strip(),
                'tables': tables,
                'method': method,
            })

    return pages


def get_pdf_page_count(pdf_path):
    """Quick page count without full extraction."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)
