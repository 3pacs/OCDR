"""Candelis sync engine — ingests study data into local SQLite.

Flow:
  1. Pull studies from Candelis via connector.fetch_studies()
  2. Upsert into candelis_studies (keyed on candelis_key)
  3. Map each study into a calendar_entries row (keyed on candelis_study_id)
  4. Attempt auto-match to billing_records using identifying markers
"""

import json
import logging
from datetime import date, datetime, timezone

from rapidfuzz import fuzz

from app import db
from app.models import BillingRecord, CalendarEntry, CandelisStudy

log = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────

def _parse_date(val):
    """Best-effort parse of a date value from Candelis."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y', '%Y%m%d'):
            try:
                return datetime.strptime(val.split('.')[0], fmt).date()
            except ValueError:
                continue
    return None


def _normalize_name(name):
    """Lowercase, strip, collapse whitespace for comparison."""
    if not name:
        return ''
    return ' '.join(name.lower().strip().split())


# ── upsert studies ──────────────────────────────────────────────

def upsert_studies(rows):
    """Insert or update CandelisStudy rows.  Returns (inserted, updated) counts."""
    inserted = updated = 0

    for row in rows:
        key = str(row.get('candelis_key') or row.get('accession_number') or '')
        if not key:
            continue

        existing = CandelisStudy.query.filter_by(candelis_key=key).first()

        fields = dict(
            accession_number=row.get('accession_number'),
            mrn=str(row['mrn']) if row.get('mrn') is not None else None,
            patient_name=row.get('patient_name'),
            patient_last_name=row.get('patient_last_name'),
            patient_first_name=row.get('patient_first_name'),
            birth_date=_parse_date(row.get('birth_date')),
            gender=row.get('gender'),
            phone=row.get('phone'),
            ssn_last4=row.get('ssn_last4'),
            jacket_number=row.get('jacket_number'),
            study_date=_parse_date(row.get('study_date')),
            study_time=row.get('study_time'),
            modality=row.get('modality'),
            study_description=row.get('study_description'),
            body_part=row.get('body_part'),
            referring_physician=row.get('referring_physician'),
            reading_physician=row.get('reading_physician'),
            insurance_carrier=row.get('insurance_carrier'),
            insurance_id=row.get('insurance_id'),
            authorization_number=row.get('authorization_number'),
            study_status=row.get('study_status'),
            location=row.get('location'),
            raw_data=row.get('_raw'),
        )

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            study = CandelisStudy(candelis_key=key, **fields)
            db.session.add(study)
            inserted += 1

    db.session.flush()
    return inserted, updated


# ── map to calendar entries ─────────────────────────────────────

def sync_to_calendar():
    """Create/update CalendarEntry rows for every CandelisStudy.

    Keyed on candelis_study_id so re-syncs are idempotent.
    """
    created = updated = 0
    studies = CandelisStudy.query.all()

    for study in studies:
        entry = CalendarEntry.query.filter_by(candelis_study_id=study.id).first()

        # Build the full patient name from components if not already set
        patient_name = study.patient_name
        if not patient_name and (study.patient_last_name or study.patient_first_name):
            parts = [study.patient_last_name or '', study.patient_first_name or '']
            patient_name = ', '.join(p for p in parts if p)

        fields = dict(
            source_system='CANDELIS',
            source_pdf='',
            schedule_date=study.study_date,
            time_slot=study.study_time,
            patient_name=patient_name,
            patient_id=int(study.mrn) if study.mrn and study.mrn.isdigit() else None,
            jacket_number=study.jacket_number,
            birth_date=study.birth_date,
            scan_type=study.study_description,
            modality=study.modality,
            referring_doctor=study.referring_physician,
            insurance_carrier=study.insurance_carrier,
            accession_number=study.accession_number,
            mrn=study.mrn,
            gender=study.gender,
            phone=study.phone,
            study_status=study.study_status,
            study_description=study.study_description,
            reading_physician=study.reading_physician,
            location=study.location,
            synced_at=datetime.now(timezone.utc),
        )

        if entry:
            for k, v in fields.items():
                setattr(entry, k, v)
            updated += 1
        else:
            entry = CalendarEntry(candelis_study_id=study.id, **fields)
            db.session.add(entry)
            created += 1

    db.session.flush()
    return created, updated


# ── auto-match to billing ──────────────────────────────────────

MATCH_METHODS = [
    # (method_name, confidence) — tried in priority order
    ('accession', 1.0),
    ('mrn+date', 0.95),
    ('dob+name+date', 0.85),
    ('fuzzy_name+date', 0.70),
]


def auto_match_entries():
    """Attempt to link unmatched CalendarEntry rows to BillingRecord rows.

    Uses a cascade of matching strategies from high to low confidence.
    Returns count of newly matched entries.
    """
    unmatched = CalendarEntry.query.filter(
        CalendarEntry.billing_record_id.is_(None),
        CalendarEntry.source_system == 'CANDELIS',
    ).all()

    matched = 0
    for entry in unmatched:
        record = _find_billing_match(entry)
        if record:
            matched += 1

    db.session.flush()
    return matched


def _find_billing_match(entry):
    """Try each match strategy in order.  First hit wins."""
    # 1. Accession number — strongest identifier
    if entry.accession_number:
        rec = BillingRecord.query.filter_by(
            era_claim_id=entry.accession_number
        ).first()
        if rec:
            _set_match(entry, rec, 'accession', 1.0)
            return rec

    # 2. MRN + service date
    if entry.mrn and entry.schedule_date:
        mrn_int = int(entry.mrn) if entry.mrn.isdigit() else None
        if mrn_int:
            rec = BillingRecord.query.filter_by(
                patient_id=mrn_int,
                service_date=entry.schedule_date,
            ).first()
            if rec:
                _set_match(entry, rec, 'mrn+date', 0.95)
                return rec

    # 3. DOB + patient name + date
    if entry.birth_date and entry.patient_name and entry.schedule_date:
        candidates = BillingRecord.query.filter_by(
            birth_date=entry.birth_date,
            service_date=entry.schedule_date,
        ).all()
        entry_name = _normalize_name(entry.patient_name)
        for rec in candidates:
            rec_name = _normalize_name(rec.patient_name)
            if rec_name and fuzz.ratio(entry_name, rec_name) >= 85:
                _set_match(entry, rec, 'dob+name+date', 0.85)
                return rec

    # 4. Fuzzy name + date (lower confidence)
    if entry.patient_name and entry.schedule_date:
        candidates = BillingRecord.query.filter_by(
            service_date=entry.schedule_date,
        ).all()
        entry_name = _normalize_name(entry.patient_name)
        best_score = 0
        best_rec = None
        for rec in candidates:
            rec_name = _normalize_name(rec.patient_name)
            score = fuzz.ratio(entry_name, rec_name)
            if score > best_score:
                best_score = score
                best_rec = rec
        if best_rec and best_score >= 90:
            conf = round(0.70 * (best_score / 100), 4)
            _set_match(entry, best_rec, 'fuzzy_name+date', conf)
            return best_rec

    return None


def _set_match(entry, record, method, confidence):
    entry.billing_record_id = record.id
    entry.match_method = method
    entry.match_confidence = confidence


# ── full sync orchestrator ──────────────────────────────────────

def run_sync(connector, from_date=None, to_date=None):
    """Full sync pipeline: fetch → upsert → map → match.

    Returns a summary dict.
    """
    log.info("Starting Candelis sync  from=%s  to=%s", from_date, to_date)

    rows, fields = connector.fetch_studies(from_date=from_date, to_date=to_date)
    log.info("Fetched %d studies (%d fields mapped)", len(rows), len(fields))

    ins, upd = upsert_studies(rows)
    log.info("Upserted studies: %d inserted, %d updated", ins, upd)

    cal_new, cal_upd = sync_to_calendar()
    log.info("Calendar entries: %d created, %d updated", cal_new, cal_upd)

    matched = auto_match_entries()
    log.info("Auto-matched %d entries to billing records", matched)

    db.session.commit()

    return {
        'studies_fetched': len(rows),
        'studies_inserted': ins,
        'studies_updated': upd,
        'calendar_created': cal_new,
        'calendar_updated': cal_upd,
        'billing_matched': matched,
        'fields_mapped': fields,
    }
