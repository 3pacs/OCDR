"""Import data routes — file upload, preview, and import execution.

Endpoints:
  GET  /import                     - Import page
  POST /api/import/upload          - Upload a file, get preview + auto-mapping
  POST /api/import/run             - Execute import with confirmed mapping
  GET  /api/import/jobs            - List import history
  GET  /api/import/jobs/<id>       - Single job details
"""

import json
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request
from werkzeug.utils import secure_filename

from app import db
from app.models import ImportJob, BillingRecord

import_bp = Blueprint('import', __name__)

ALLOWED_EXTENSIONS = {'.xlsx', '.xls', '.csv'}


def _upload_folder(app):
    folder = app.config.get('UPLOAD_FOLDER', os.path.join(app.instance_path, '..', 'uploads'))
    os.makedirs(folder, exist_ok=True)
    return folder


@import_bp.route('/import')
def index():
    """Render the import page."""
    recent_jobs = ImportJob.query.order_by(ImportJob.created_at.desc()).limit(20).all()
    total_records = db.session.query(BillingRecord).count()
    return render_template('import.html', jobs=recent_jobs, total_records=total_records)


@import_bp.route('/api/import/upload', methods=['POST'])
def upload():
    """Upload a file and return a preview with auto-detected column mapping."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'Unsupported file type: {ext}. Use .xlsx, .xls, or .csv'}), 400

    filename = secure_filename(file.filename)
    folder = _upload_folder(request.app if hasattr(request, 'app') else import_bp)
    # Actually get the app properly
    from flask import current_app
    folder = _upload_folder(current_app)
    filepath = os.path.join(folder, filename)
    file.save(filepath)

    from app.import_engine.importer import preview_file
    try:
        preview = preview_file(filepath)
    except Exception as exc:
        return jsonify({'error': f'Failed to read file: {exc}'}), 400

    # Create a pending ImportJob
    job = ImportJob(
        filename=filename,
        file_type='excel' if ext in ('.xlsx', '.xls') else 'csv',
        status='pending',
        total_rows=preview['total_rows'],
        column_mapping=json.dumps(preview['auto_mapping']),
    )
    db.session.add(job)
    db.session.commit()

    return jsonify({
        'job_id': job.id,
        'filename': filename,
        'filepath': filepath,
        **preview,
    })


@import_bp.route('/api/import/run', methods=['POST'])
def run():
    """Execute import for a previously uploaded file."""
    data = request.get_json(force=True)
    job_id = data.get('job_id')
    column_mapping = data.get('column_mapping')

    if not job_id:
        return jsonify({'error': 'job_id required'}), 400

    job = ImportJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    from flask import current_app
    filepath = os.path.join(_upload_folder(current_app), job.filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'Uploaded file not found'}), 404

    from app.import_engine.importer import run_import
    try:
        result = run_import(filepath, job.id, column_mapping)
        return jsonify({'ok': True, **result})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@import_bp.route('/api/import/jobs', methods=['GET'])
def list_jobs():
    jobs = ImportJob.query.order_by(ImportJob.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': j.id,
        'filename': j.filename,
        'file_type': j.file_type,
        'status': j.status,
        'total_rows': j.total_rows,
        'imported_rows': j.imported_rows,
        'skipped_rows': j.skipped_rows,
        'error_rows': j.error_rows,
        'error_message': j.error_message,
        'completed_at': j.completed_at.isoformat() if j.completed_at else None,
        'created_at': j.created_at.isoformat() if j.created_at else None,
    } for j in jobs])


@import_bp.route('/api/import/jobs/<int:job_id>', methods=['GET'])
def get_job(job_id):
    j = ImportJob.query.get_or_404(job_id)
    return jsonify({
        'id': j.id,
        'filename': j.filename,
        'file_type': j.file_type,
        'status': j.status,
        'total_rows': j.total_rows,
        'imported_rows': j.imported_rows,
        'skipped_rows': j.skipped_rows,
        'error_rows': j.error_rows,
        'errors': json.loads(j.errors) if j.errors else [],
        'column_mapping': json.loads(j.column_mapping) if j.column_mapping else {},
        'error_message': j.error_message,
        'completed_at': j.completed_at.isoformat() if j.completed_at else None,
        'created_at': j.created_at.isoformat() if j.created_at else None,
    })
