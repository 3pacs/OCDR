import os
import glob
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import CalendarConfig, CalendarEntry, OcrJob, OcrPage

calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/api/calendar/config', methods=['GET'])
def get_config():
    cfg = CalendarConfig.query.order_by(CalendarConfig.set_at.desc()).first()
    if not cfg:
        return jsonify({'configured': False, 'pdf_folder_path': None, 'pdfs': []})

    pdfs = _scan_folder(cfg.pdf_folder_path)
    return jsonify({
        'configured': True,
        'pdf_folder_path': cfg.pdf_folder_path,
        'set_at': cfg.set_at.isoformat() if cfg.set_at else None,
        'pdfs': pdfs,
    })


@calendar_bp.route('/api/calendar/config', methods=['POST'])
def set_config():
    data = request.get_json()
    folder = data.get('pdf_folder_path', '').strip()

    if not folder:
        return jsonify({'error': 'pdf_folder_path is required'}), 400

    folder = os.path.abspath(os.path.expanduser(folder))

    if not os.path.isdir(folder):
        return jsonify({'error': f'Directory not found: {folder}'}), 400

    cfg = CalendarConfig(pdf_folder_path=folder)
    db.session.add(cfg)
    db.session.commit()

    pdfs = _scan_folder(folder)
    return jsonify({
        'configured': True,
        'pdf_folder_path': folder,
        'set_at': cfg.set_at.isoformat(),
        'pdfs': pdfs,
    })


@calendar_bp.route('/api/calendar/pdfs', methods=['GET'])
def list_pdfs():
    cfg = CalendarConfig.query.order_by(CalendarConfig.set_at.desc()).first()
    if not cfg:
        return jsonify({'error': 'No folder configured'}), 400

    pdfs = _scan_folder(cfg.pdf_folder_path)
    return jsonify({'pdf_folder_path': cfg.pdf_folder_path, 'pdfs': pdfs})


@calendar_bp.route('/api/calendar/entries', methods=['GET'])
def list_entries():
    date_from = request.args.get('from')
    date_to = request.args.get('to')

    query = CalendarEntry.query.order_by(CalendarEntry.schedule_date.desc())
    if date_from:
        query = query.filter(CalendarEntry.schedule_date >= date_from)
    if date_to:
        query = query.filter(CalendarEntry.schedule_date <= date_to)

    entries = query.limit(500).all()
    return jsonify([_serialize_entry(e) for e in entries])


@calendar_bp.route('/api/calendar/stats', methods=['GET'])
def stats():
    cfg = CalendarConfig.query.order_by(CalendarConfig.set_at.desc()).first()
    pdf_count = 0
    if cfg and os.path.isdir(cfg.pdf_folder_path):
        pdf_count = len(_scan_folder(cfg.pdf_folder_path))

    entry_count = CalendarEntry.query.count()
    matched_count = CalendarEntry.query.filter(
        CalendarEntry.billing_record_id.isnot(None)
    ).count()
    unmatched_count = entry_count - matched_count

    return jsonify({
        'configured': cfg is not None,
        'pdf_folder_path': cfg.pdf_folder_path if cfg else None,
        'pdf_count': pdf_count,
        'entry_count': entry_count,
        'matched_count': matched_count,
        'unmatched_count': unmatched_count,
    })


def _scan_folder(folder_path):
    """Scan folder recursively for PDF files and return sorted metadata."""
    if not os.path.isdir(folder_path):
        return []

    pattern = os.path.join(folder_path, '**', '*.pdf')
    files = glob.glob(pattern, recursive=True)

    pdfs = []
    for f in sorted(files):
        stat = os.stat(f)
        pdfs.append({
            'path': f,
            'name': os.path.basename(f),
            'relative_path': os.path.relpath(f, folder_path),
            'size_bytes': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })

    return pdfs


def _serialize_entry(entry):
    return {
        'id': entry.id,
        'source_pdf': entry.source_pdf,
        'source_system': entry.source_system,
        'page_number': entry.page_number,
        'schedule_date': entry.schedule_date.isoformat() if entry.schedule_date else None,
        'time_slot': entry.time_slot,
        'patient_name': entry.patient_name,
        'patient_id': entry.patient_id,
        'mrn': entry.mrn,
        'jacket_number': entry.jacket_number,
        'birth_date': entry.birth_date.isoformat() if entry.birth_date else None,
        'scan_type': entry.scan_type,
        'modality': entry.modality,
        'referring_doctor': entry.referring_doctor,
        'insurance_carrier': entry.insurance_carrier,
        'accession_number': entry.accession_number,
        'study_status': entry.study_status,
        'notes': entry.notes,
        'billing_record_id': entry.billing_record_id,
        'match_confidence': float(entry.match_confidence) if entry.match_confidence else None,
        'match_method': entry.match_method,
        'created_at': entry.created_at.isoformat() if entry.created_at else None,
    }


# ── OCR endpoints ───────────────────────────────────────────────

@calendar_bp.route('/api/calendar/ocr/start', methods=['POST'])
def ocr_start():
    """Start background OCR processing for all PDFs in configured folder."""
    cfg = CalendarConfig.query.order_by(CalendarConfig.set_at.desc()).first()
    if not cfg:
        return jsonify({'error': 'No PDF folder configured'}), 400

    from app.ocr.worker import start_ocr_run
    ok, msg = start_ocr_run(current_app._get_current_object(), cfg.pdf_folder_path)
    return jsonify({'ok': ok, 'message': msg})


@calendar_bp.route('/api/calendar/ocr/status', methods=['GET'])
def ocr_status():
    """Poll background OCR progress."""
    from app.ocr.worker import get_ocr_status
    status = get_ocr_status()

    # Also include DB-level stats
    total_jobs = OcrJob.query.count()
    completed_jobs = OcrJob.query.filter_by(status='completed').count()
    failed_jobs = OcrJob.query.filter_by(status='failed').count()
    total_pages_stored = db.session.query(OcrPage).count()
    ocr_entries = CalendarEntry.query.filter_by(source_system='PDF_OCR').count()

    return jsonify({
        **status,
        'db_total_jobs': total_jobs,
        'db_completed_jobs': completed_jobs,
        'db_failed_jobs': failed_jobs,
        'db_pages_stored': total_pages_stored,
        'db_ocr_entries': ocr_entries,
    })


@calendar_bp.route('/api/calendar/ocr/jobs', methods=['GET'])
def ocr_jobs():
    """List all OCR job records."""
    jobs = OcrJob.query.order_by(OcrJob.created_at.desc()).limit(200).all()
    return jsonify([{
        'id': j.id,
        'pdf_name': j.pdf_name,
        'status': j.status,
        'total_pages': j.total_pages,
        'processed_pages': j.processed_pages,
        'entries_found': j.entries_found,
        'error_message': j.error_message,
        'started_at': j.started_at.isoformat() if j.started_at else None,
        'completed_at': j.completed_at.isoformat() if j.completed_at else None,
    } for j in jobs])
