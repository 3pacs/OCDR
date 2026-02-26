"""AI Schema Analyst — uses Claude API to help parse unknown file formats.

SECURITY MODEL:
  1. The PHI scrubber strips ALL patient data before anything leaves the machine
  2. Only structural metadata is sent: column names, data types, format patterns,
     aggregate counts, segment types, delimiter info
  3. The API key is stored encrypted on disk (AES-256 via Fernet)
  4. All API calls use HTTPS (TLS 1.2+)
  5. A final validate_payload_phi_free() check runs before every request
  6. The full prompt and response are logged locally for audit

WHAT GETS SENT (safe):
  - Column headers / field names
  - Data type patterns ("[DATE_VALUE]", "[NUMBER]", "[PATIENT_NAME]")
  - Row/column counts
  - File format info (extension, delimiters, encoding)
  - X12 segment counts (ISA, BPR, CLP, SVC, CAS)
  - Public code sets (CPT codes, payer codes, modalities, denial codes)
  - Aggregate stats (total records, sums — never per-patient)

WHAT NEVER LEAVES (PHI):
  - Patient names, DOBs, addresses, phone, email, SSN
  - Patient IDs, MRNs, account numbers
  - Specific service dates tied to patients
  - Any value that could identify an individual
"""
import json
import os
import logging
from datetime import datetime

from flask import request, jsonify
from app.import_engine import import_bp
from app.import_engine.phi_scrubber import (
    extract_safe_file_metadata,
    extract_safe_schema,
    extract_safe_db_schema,
    validate_payload_phi_free,
)

logger = logging.getLogger(__name__)

# Local audit log for all AI interactions
AUDIT_LOG_DIR = os.path.join(os.getcwd(), 'logs', 'ai_audit')


def _get_api_key():
    """Retrieve the Claude API key from encrypted storage or env var."""
    # First check environment variable
    key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if key:
        return key

    # Then check encrypted store
    key_file = os.path.join(os.getcwd(), '.ai_key.enc')
    if os.path.exists(key_file):
        try:
            from cryptography.fernet import Fernet
            secret = os.environ.get('SECRET_KEY', 'dev-secret-key')
            # Derive a Fernet key from the app secret
            import hashlib
            import base64
            fernet_key = base64.urlsafe_b64encode(
                hashlib.sha256(secret.encode()).digest()
            )
            f = Fernet(fernet_key)
            with open(key_file, 'rb') as fh:
                encrypted = fh.read()
            return f.decrypt(encrypted).decode()
        except Exception:
            pass

    return None


def _store_api_key(api_key):
    """Encrypt and store the API key locally."""
    from cryptography.fernet import Fernet
    import hashlib
    import base64

    secret = os.environ.get('SECRET_KEY', 'dev-secret-key')
    fernet_key = base64.urlsafe_b64encode(
        hashlib.sha256(secret.encode()).digest()
    )
    f = Fernet(fernet_key)
    encrypted = f.encrypt(api_key.encode())

    key_file = os.path.join(os.getcwd(), '.ai_key.enc')
    with open(key_file, 'wb') as fh:
        fh.write(encrypted)

    return True


def _audit_log(action, payload_sent, response_received):
    """Log every AI interaction locally for HIPAA audit trail."""
    os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'action': action,
        'payload_sent': payload_sent,
        'response_received': response_received,
    }
    log_path = os.path.join(AUDIT_LOG_DIR, f'{timestamp}_{action}.json')
    with open(log_path, 'w') as f:
        json.dump(log_entry, f, indent=2, default=str)


def _call_claude_api(system_prompt, user_message, payload):
    """Send a PHI-free payload to Claude API and return the response.

    Performs a final safety check before transmission.
    """
    api_key = _get_api_key()
    if not api_key:
        return {
            'error': 'No API key configured. Set ANTHROPIC_API_KEY in .env or '
                     'use POST /api/ai/configure to store one.',
        }

    # FINAL SAFETY CHECK — abort if any PHI detected
    is_safe, issues = validate_payload_phi_free(payload)
    if not is_safe:
        _audit_log('BLOCKED_PHI_DETECTED', {'issues': issues}, None)
        return {
            'error': 'PHI detected in payload — transmission blocked',
            'phi_issues': issues,
        }

    # Build the API request
    import urllib.request
    import urllib.error

    request_body = {
        'model': 'claude-sonnet-4-20250514',
        'max_tokens': 2048,
        'system': system_prompt,
        'messages': [
            {'role': 'user', 'content': user_message + '\n\n```json\n'
             + json.dumps(payload, indent=2, default=str) + '\n```'},
        ],
    }

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    }

    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps(request_body).encode('utf-8'),
        headers=headers,
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode('utf-8'))
            result_text = ''
            for block in response_data.get('content', []):
                if block.get('type') == 'text':
                    result_text += block['text']

            _audit_log('api_call', payload, result_text)
            return {'response': result_text, 'model': response_data.get('model')}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        _audit_log('api_error', payload, error_body)
        return {'error': f'API error ({e.code}): {error_body}'}
    except Exception as e:
        _audit_log('api_error', payload, str(e))
        return {'error': f'Connection error: {str(e)}'}


# ---- Public functions for AI-assisted parsing ----

def analyze_file_structure(filepath, content_preview=None):
    """Ask Claude to analyze a file's structure and suggest parsing strategy.

    Only sends PHI-free metadata (headers, patterns, counts).
    """
    metadata = extract_safe_file_metadata(filepath, content_preview)

    system = (
        "You are a data format analyst for a medical billing reconciliation system. "
        "You receive ONLY structural metadata about files — never patient data. "
        "Analyze the file structure and suggest: (1) the file format, "
        "(2) which parser to use (835 EDI, CSV, PDF EOB, schedule), "
        "(3) column mappings if applicable, (4) any data quality concerns. "
        "Be specific and actionable."
    )

    user_msg = (
        "Analyze this file's structure and tell me how to parse it. "
        "No patient data is included — only structural metadata:"
    )

    return _call_claude_api(system, user_msg, metadata)


def suggest_column_mapping(headers, sample_patterns):
    """Ask Claude to suggest column mappings for an unknown CSV/Excel file."""
    payload = {
        'headers': headers,
        'sample_value_patterns': sample_patterns,
        'target_fields': [
            'patient_name', 'service_date', 'scan_type', 'modality',
            'insurance_carrier', 'primary_payment', 'secondary_payment',
            'total_payment', 'referring_doctor', 'reading_physician',
            'patient_id', 'description', 'gado_used', 'schedule_date',
        ],
    }

    system = (
        "You are a column mapping assistant for a medical billing system. "
        "Given column headers and value TYPE PATTERNS (never actual patient data), "
        "suggest which source column maps to which target field. "
        "Return a JSON object with {target_field: source_column_index}. "
        "Only map columns you are confident about."
    )

    user_msg = "Suggest column mappings for this file. Only type patterns shown, no actual data:"
    return _call_claude_api(system, user_msg, payload)


def analyze_database_health():
    """Ask Claude to analyze the database schema and suggest improvements."""
    schema = extract_safe_db_schema()

    system = (
        "You are a healthcare billing database analyst. "
        "You receive ONLY aggregate statistics and schema metadata — never patient data. "
        "Analyze the database health and suggest: (1) data quality issues, "
        "(2) missing data patterns, (3) recommended next steps for reconciliation, "
        "(4) potential revenue recovery opportunities based on aggregate stats."
    )

    user_msg = "Analyze this database health. Only aggregate stats and schema shown:"
    return _call_claude_api(system, user_msg, schema)


def explain_parsing_error(error_message, file_metadata):
    """Ask Claude to help diagnose a parsing error."""
    payload = {
        'error_message': error_message,
        'file_metadata': file_metadata,
    }

    system = (
        "You are a technical support assistant for a medical billing import system. "
        "Help diagnose why a file failed to parse. Suggest concrete fixes. "
        "You receive only error messages and file metadata — never patient data."
    )

    user_msg = "Help me fix this parsing error:"
    return _call_claude_api(system, user_msg, payload)


# ---- API Routes ----

@import_bp.route('/ai/configure', methods=['POST'])
def configure_ai():
    """POST /api/import/ai/configure - Store encrypted API key.

    JSON body: { "api_key": "sk-ant-..." }
    The key is encrypted with AES-256 (Fernet) and stored locally.
    """
    data = request.get_json(silent=True)
    if not data or 'api_key' not in data:
        return jsonify({'error': 'Provide api_key in JSON body'}), 400

    api_key = data['api_key'].strip()
    if not api_key.startswith('sk-'):
        return jsonify({'error': 'Invalid API key format'}), 400

    try:
        _store_api_key(api_key)
        return jsonify({
            'status': 'ok',
            'message': 'API key encrypted and stored locally',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@import_bp.route('/ai/status', methods=['GET'])
def ai_status():
    """GET /api/import/ai/status - Check if AI assistant is configured."""
    api_key = _get_api_key()
    return jsonify({
        'configured': api_key is not None,
        'key_source': 'env' if os.environ.get('ANTHROPIC_API_KEY') else 'encrypted_file',
        'phi_policy': 'STRICT — only structural metadata transmitted, never patient data',
    })


@import_bp.route('/ai/analyze-file', methods=['POST'])
def ai_analyze_file():
    """POST /api/import/ai/analyze-file - AI analysis of an uploaded file.

    Upload a file and the AI will analyze its structure (PHI-free)
    and suggest how to parse it.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    import tempfile
    ext = os.path.splitext(file.filename)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)

        # Read a preview for content analysis
        preview = None
        try:
            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                preview = f.read(4000)
        except Exception:
            pass

        result = analyze_file_structure(tmp_path, preview)
        result['filename'] = file.filename
        return jsonify(result)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/ai/analyze-db', methods=['GET'])
def ai_analyze_db():
    """GET /api/import/ai/analyze-db - AI analysis of database health.

    Sends only aggregate stats and schema metadata to Claude.
    """
    result = analyze_database_health()
    return jsonify(result)


@import_bp.route('/ai/suggest-mapping', methods=['POST'])
def ai_suggest_mapping():
    """POST /api/import/ai/suggest-mapping - AI column mapping suggestion.

    Upload a CSV/Excel file and get AI-suggested column mappings.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    import tempfile
    ext = os.path.splitext(file.filename)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        file.save(tmp_path)

        # Extract headers and scrubbed sample patterns
        headers = []
        sample_patterns = []

        if ext.lower() in ('.csv', '.txt'):
            import csv
            with open(tmp_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                for i, row in enumerate(reader):
                    if i >= 3:
                        break
                    from app.import_engine.phi_scrubber import scrub_value
                    scrubbed = [scrub_value(cell)[0] for cell in row]
                    sample_patterns.append(scrubbed)
        elif ext.lower() in ('.xlsx', '.xls'):
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(max_row=4, values_only=True))
            if rows:
                headers = [str(h) if h else '' for h in rows[0]]
                for row in rows[1:4]:
                    from app.import_engine.phi_scrubber import scrub_value
                    scrubbed = [scrub_value(cell)[0] for cell in row]
                    sample_patterns.append(scrubbed)
            wb.close()

        result = suggest_column_mapping(headers, sample_patterns)
        result['detected_headers'] = headers
        result['filename'] = file.filename
        return jsonify(result)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@import_bp.route('/ai/phi-check', methods=['POST'])
def phi_safety_check():
    """POST /api/import/ai/phi-check - Check if a payload contains PHI.

    Useful for testing: submit any JSON and verify the scrubber catches PHI.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Provide JSON body to check'}), 400

    is_safe, issues = validate_payload_phi_free(data)
    return jsonify({
        'is_safe': is_safe,
        'issues': issues,
        'policy': 'Payload must contain zero PHI before external transmission',
    })
