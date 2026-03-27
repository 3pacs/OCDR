"""OCR engine for scanned documents and images.

Uses OpenCV for image preprocessing and Tesseract for text extraction.
Handles:
  - Scanned PDF pages (rendered via pdfplumber → image)
  - Image files (PNG, JPG, TIFF, BMP)
  - Multi-page documents

After OCR, the extracted text is routed through format detection
to determine if it's an EOB, schedule, or other document type.
"""
import os
import tempfile

from app.models import db


def _preprocess_image(image):
    """Apply preprocessing to improve OCR accuracy.

    Steps: grayscale → denoise → adaptive threshold → deskew.
    """
    import cv2
    import numpy as np

    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Denoise
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

    # Adaptive threshold for better text contrast
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # Deskew: detect angle and rotate
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 0.5:  # Only deskew if significantly skewed
            (h, w) = thresh.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(
                thresh, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )

    return thresh


def _extract_text_from_image(image):
    """Run Tesseract OCR on a preprocessed image."""
    import pytesseract
    # Use page segmentation mode 6 (uniform block of text)
    config = '--psm 6 --oem 3'
    text = pytesseract.image_to_string(image, config=config)
    return text


def ocr_image(filepath):
    """OCR a single image file and extract data.

    Returns import results after routing the OCR text through
    format detection and the appropriate parser.
    """
    import cv2

    image = cv2.imread(filepath)
    if image is None:
        return {
            'status': 'error',
            'reason': f'Cannot read image file: {filepath}',
        }

    preprocessed = _preprocess_image(image)
    text = _extract_text_from_image(preprocessed)

    if not text.strip():
        return {
            'claims_found': 0,
            'ocr_text_length': 0,
            'message': 'OCR produced no readable text from image',
        }

    # Route through text analysis
    return _route_ocr_text(text, os.path.basename(filepath))


def ocr_pdf(filepath):
    """OCR a scanned PDF (pages rendered as images).

    Extracts each page, runs OCR, concatenates text, then parses.
    """
    all_text = ''
    page_count = 0

    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_count += 1
                # First try direct text extraction
                page_text = page.extract_text()
                if page_text and len(page_text.strip()) > 50:
                    all_text += page_text + '\n'
                    continue

                # Fall back to OCR via page image
                page_image = page.to_image(resolution=300)
                img_path = tempfile.mktemp(suffix='.png')
                try:
                    page_image.save(img_path)
                    import cv2
                    image = cv2.imread(img_path)
                    if image is not None:
                        preprocessed = _preprocess_image(image)
                        ocr_text = _extract_text_from_image(preprocessed)
                        all_text += ocr_text + '\n'
                finally:
                    if os.path.exists(img_path):
                        os.unlink(img_path)

    except ImportError:
        return {
            'status': 'error',
            'reason': 'pdfplumber or cv2/pytesseract not installed for OCR',
        }
    except Exception as e:
        return {
            'status': 'error',
            'reason': f'OCR processing failed: {str(e)}',
        }

    if not all_text.strip():
        return {
            'claims_found': 0,
            'pages_processed': page_count,
            'message': 'OCR could not extract readable text from scanned PDF',
        }

    result = _route_ocr_text(all_text, os.path.basename(filepath))
    result['pages_processed'] = page_count
    return result


def _route_ocr_text(text, filename):
    """Route OCR-extracted text to the appropriate parser.

    Checks if the text looks like 835 EDI, an EOB, or a schedule.
    """
    upper = text.upper()
    result = {
        'ocr_text_length': len(text),
        'filename': filename,
    }

    # Check for X12 835 content
    edi_indicators = ('ISA*', 'BPR*', 'CLP*', 'ST*835')
    edi_hits = sum(1 for ind in edi_indicators if ind in upper)
    if edi_hits >= 2:
        # Write to temp file and parse as 835
        from app.parser.era_835_parser import parse_835_content, store_parsed_835
        parsed = parse_835_content(text, filename)
        era_payment, claims_new, claims_dup = store_parsed_835(parsed)
        result.update({
            'detected_type': '835_edi',
            'claims_found': len(parsed['claims']),
            'claims_new': claims_new,
            'claims_duplicate': claims_dup,
        })
        if era_payment:
            result['era_payment_id'] = era_payment.id
        return result

    # Check for schedule content
    schedule_keywords = ('SCHEDULE', 'APPOINTMENT', 'APPT', 'ARRIVAL', 'EXAM TIME')
    schedule_hits = sum(1 for kw in schedule_keywords if kw in upper)
    if schedule_hits >= 2:
        from app.import_engine.schedule_parser import parse_schedule_text
        sched_result = parse_schedule_text(text, filename)
        result.update(sched_result)
        result['detected_type'] = 'schedule'
        return result

    # Default: try as EOB text
    from app.import_engine.pdf_parser import _store_extracted_claims
    eob_result = _store_extracted_claims(text, filename, source='OCR_EOB')
    result.update(eob_result)
    result['detected_type'] = 'eob'
    return result
