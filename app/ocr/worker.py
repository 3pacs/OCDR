"""Background OCR worker — processes PDFs in a separate thread.

Usage:
    from app.ocr.worker import start_ocr_run
    start_ocr_run(app, folder_path)   # non-blocking, returns immediately
    get_ocr_status()                  # check progress
"""

import logging
import os
import glob
import threading
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Module-level state for the background worker
_worker_lock = threading.Lock()
_current_run = {
    'active': False,
    'total_pdfs': 0,
    'processed_pdfs': 0,
    'total_entries': 0,
    'errors': [],
    'started_at': None,
}


def get_ocr_status():
    """Return the current OCR run status (thread-safe snapshot)."""
    with _worker_lock:
        return dict(_current_run)


def start_ocr_run(app, folder_path):
    """Kick off background OCR processing for all PDFs in folder.

    Returns immediately.  Use get_ocr_status() to poll progress.
    """
    with _worker_lock:
        if _current_run['active']:
            return False, "OCR is already running"

        _current_run['active'] = True
        _current_run['processed_pdfs'] = 0
        _current_run['total_entries'] = 0
        _current_run['errors'] = []
        _current_run['started_at'] = datetime.now(timezone.utc).isoformat()

    # Collect PDFs
    pattern = os.path.join(folder_path, '**', '*.pdf')
    pdf_files = sorted(glob.glob(pattern, recursive=True))

    with _worker_lock:
        _current_run['total_pdfs'] = len(pdf_files)

    if not pdf_files:
        with _worker_lock:
            _current_run['active'] = False
        return False, "No PDF files found"

    # Start background thread
    t = threading.Thread(
        target=_run_ocr_pipeline,
        args=(app, pdf_files, folder_path),
        daemon=True,
    )
    t.start()
    return True, f"Started OCR for {len(pdf_files)} PDFs"


def _run_ocr_pipeline(app, pdf_files, folder_path):
    """Main OCR pipeline — runs in background thread."""
    with app.app_context():
        from app import db
        from app.models import OcrJob, OcrPage, CalendarEntry
        from app.ocr.engine import extract_pdf, get_pdf_page_count
        from app.ocr.parser import parse_schedule_text, parse_schedule_table

        for pdf_path in pdf_files:
            pdf_name = os.path.relpath(pdf_path, folder_path)

            # Skip if already processed
            existing = OcrJob.query.filter_by(
                pdf_path=pdf_path, status='completed'
            ).first()
            if existing:
                with _worker_lock:
                    _current_run['processed_pdfs'] += 1
                continue

            # Create or update job record
            job = OcrJob.query.filter_by(pdf_path=pdf_path).first()
            if not job:
                job = OcrJob(pdf_path=pdf_path, pdf_name=pdf_name, status='processing')
                db.session.add(job)
            else:
                job.status = 'processing'
                job.error_message = None

            job.started_at = datetime.now(timezone.utc)

            try:
                page_count = get_pdf_page_count(pdf_path)
                job.total_pages = page_count
                db.session.commit()

                # Extract text from all pages
                pages = extract_pdf(pdf_path)
                entries_total = 0

                for page_data in pages:
                    page_num = page_data['page']
                    text = page_data['text']
                    tables = page_data['tables']

                    # Store raw OCR page
                    ocr_page = OcrPage.query.filter_by(
                        ocr_job_id=job.id, page_number=page_num
                    ).first()
                    if not ocr_page:
                        ocr_page = OcrPage(
                            ocr_job_id=job.id,
                            page_number=page_num,
                        )
                        db.session.add(ocr_page)

                    ocr_page.raw_text = text
                    ocr_page.has_table = bool(tables)

                    # Parse entries from tables first (more structured)
                    entries = []
                    for table in tables:
                        entries.extend(parse_schedule_table(table))

                    # If no table entries, try line-by-line parsing
                    if not entries:
                        entries = parse_schedule_text(text)

                    ocr_page.entries_extracted = len(entries)

                    # Create CalendarEntry rows
                    for entry_data in entries:
                        _create_calendar_entry(db, entry_data, pdf_path, page_num)
                        entries_total += 1

                    job.processed_pages = page_num
                    db.session.commit()

                job.status = 'completed'
                job.entries_found = entries_total
                job.completed_at = datetime.now(timezone.utc)
                db.session.commit()

                with _worker_lock:
                    _current_run['processed_pdfs'] += 1
                    _current_run['total_entries'] += entries_total

            except Exception as exc:
                log.exception("OCR failed for %s", pdf_path)
                job.status = 'failed'
                job.error_message = str(exc)
                db.session.commit()

                with _worker_lock:
                    _current_run['processed_pdfs'] += 1
                    _current_run['errors'].append({
                        'pdf': pdf_name,
                        'error': str(exc),
                    })

        # Done
        with _worker_lock:
            _current_run['active'] = False


def _create_calendar_entry(db, entry_data, pdf_path, page_number):
    """Insert a CalendarEntry from parsed OCR data, avoiding duplicates."""
    from app.models import CalendarEntry

    patient_name = entry_data.get('patient_name')
    schedule_date = entry_data.get('schedule_date')
    time_slot = entry_data.get('time_slot')

    # Dedup: same patient + date + time from same PDF
    if patient_name and schedule_date:
        existing = CalendarEntry.query.filter_by(
            source_pdf=pdf_path,
            patient_name=patient_name,
            schedule_date=schedule_date,
            time_slot=time_slot,
        ).first()
        if existing:
            return

    patient_id_str = entry_data.get('patient_id')
    patient_id = int(patient_id_str) if patient_id_str and patient_id_str.isdigit() else None

    entry = CalendarEntry(
        source_system='PDF_OCR',
        source_pdf=pdf_path,
        page_number=page_number,
        schedule_date=schedule_date,
        time_slot=time_slot,
        patient_name=patient_name,
        patient_id=patient_id,
        mrn=patient_id_str,
        jacket_number=entry_data.get('jacket_number'),
        birth_date=entry_data.get('birth_date'),
        scan_type=entry_data.get('scan_type'),
        modality=entry_data.get('modality'),
        referring_doctor=entry_data.get('referring_doctor'),
        insurance_carrier=entry_data.get('insurance_carrier'),
        notes=entry_data.get('notes'),
        raw_ocr_text=entry_data.get('_raw_line'),
        ocr_processed_at=datetime.now(timezone.utc),
    )
    db.session.add(entry)
