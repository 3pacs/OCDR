"""Candelis RIS database connector.

Connects to the Candelis SQL Server instance on the local network via pyodbc.
All data stays local — never leaves the LAN.
"""

import json
import logging
from datetime import datetime, timezone

import pyodbc

log = logging.getLogger(__name__)


class CandelisConnector:
    """Manages the pyodbc connection to a Candelis SQL Server database."""

    def __init__(self, config):
        """
        Parameters
        ----------
        config : CandelisConfig  (or dict with same keys)
            Connection settings read from the local database.
        """
        if hasattr(config, 'server'):
            self.server = config.server
            self.database = config.database
            self.username = config.username
            self.password = config.password
            self.port = config.port or 1433
            self.driver = config.driver or 'ODBC Driver 17 for SQL Server'
            self.study_table = config.study_table or 'Study'
            self.patient_table = config.patient_table or 'Patient'
        else:
            self.server = config['server']
            self.database = config['database']
            self.username = config['username']
            self.password = config['password']
            self.port = config.get('port', 1433)
            self.driver = config.get('driver', 'ODBC Driver 17 for SQL Server')
            self.study_table = config.get('study_table', 'Study')
            self.patient_table = config.get('patient_table', 'Patient')

    # ── connection ──────────────────────────────────────────────

    def _connection_string(self):
        return (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            "TrustServerCertificate=yes;"
        )

    def connect(self):
        """Return a pyodbc Connection.  Caller must close it."""
        return pyodbc.connect(self._connection_string(), timeout=10)

    def test_connection(self):
        """Quick connectivity check.  Returns (ok: bool, message: str)."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return True, "Connection successful"
        except pyodbc.Error as exc:
            return False, str(exc)

    # ── discovery ───────────────────────────────────────────────

    def list_tables(self):
        """Return list of user-table names in the Candelis database."""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            tables = [
                row.table_name
                for row in cursor.tables(tableType='TABLE')
                if row.table_schem in ('dbo', None)
            ]
            return sorted(tables)
        finally:
            conn.close()

    def list_columns(self, table_name):
        """Return list of column names for a given table."""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            cols = [
                row.column_name
                for row in cursor.columns(table=table_name)
            ]
            return cols
        finally:
            conn.close()

    # ── data fetching ───────────────────────────────────────────

    def _row_to_dict(self, cursor, row):
        """Convert a pyodbc Row to a plain dict using cursor.description."""
        return {
            desc[0]: val
            for desc, val in zip(cursor.description, row)
        }

    def fetch_studies(self, from_date=None, to_date=None, limit=5000):
        """Pull study records from Candelis.

        Uses a broad SELECT that captures the most common Candelis column names.
        Columns that don't exist in the target schema are silently skipped.

        Returns a list of dicts, one per study row.
        """
        conn = self.connect()
        try:
            cursor = conn.cursor()

            # Discover which columns actually exist in the study table
            available = set(self.list_columns(self.study_table))

            # Map our desired fields to common Candelis column names (priority order)
            field_map = {
                'candelis_key':       ['StudyKey', 'StudyID', 'ID', 'study_key'],
                'accession_number':   ['AccessionNumber', 'Accession', 'accession_number'],
                'mrn':                ['PatientID', 'MRN', 'PatientMRN', 'patient_id'],
                'patient_name':       ['PatientName', 'Patient_Name', 'patient_name'],
                'patient_last_name':  ['PatientLastName', 'PatLastName', 'LastName', 'patient_last_name'],
                'patient_first_name': ['PatientFirstName', 'PatFirstName', 'FirstName', 'patient_first_name'],
                'birth_date':         ['DateOfBirth', 'PatientDOB', 'DOB', 'BirthDate', 'birth_date'],
                'gender':             ['Sex', 'Gender', 'PatientSex', 'gender'],
                'phone':              ['Phone', 'PhoneNumber', 'PatientPhone', 'phone'],
                'ssn_last4':          ['SSN', 'SSNLast4', 'ssn_last4'],
                'jacket_number':      ['JacketNumber', 'Jacket', 'jacket_number'],
                'study_date':         ['StudyDate', 'ExamDate', 'ScheduledDate', 'study_date'],
                'study_time':         ['StudyTime', 'ExamTime', 'ScheduledTime', 'study_time'],
                'modality':           ['Modality', 'ModalityType', 'modality'],
                'study_description':  ['StudyDescription', 'ExamDescription', 'Description',
                                       'ProcedureDescription', 'study_description'],
                'body_part':          ['BodyPart', 'BodyPartExamined', 'body_part'],
                'referring_physician': ['ReferringPhysicianName', 'ReferringPhysician',
                                        'RefPhysician', 'referring_physician'],
                'reading_physician':  ['ReadingPhysicianName', 'ReadingPhysician',
                                        'InterpretingPhysician', 'reading_physician'],
                'insurance_carrier':  ['InsuranceCarrier', 'Insurance', 'PrimaryInsurance',
                                       'PayerName', 'insurance_carrier'],
                'insurance_id':       ['InsuranceID', 'PolicyNumber', 'InsurancePolicyID',
                                       'insurance_id'],
                'authorization_number': ['AuthorizationNumber', 'AuthNumber', 'PriorAuth',
                                          'authorization_number'],
                'study_status':       ['Status', 'StudyStatus', 'ExamStatus', 'study_status'],
                'location':           ['Location', 'InstitutionName', 'Facility', 'location'],
            }

            # Resolve which actual column to use for each field
            select_cols = {}  # our_field -> actual_column
            for our_field, candidates in field_map.items():
                for col in candidates:
                    if col in available:
                        select_cols[our_field] = col
                        break

            if not select_cols:
                raise RuntimeError(
                    f"Could not map any columns from table '{self.study_table}'. "
                    f"Available columns: {sorted(available)}"
                )

            # Build SELECT
            col_list = ', '.join(
                f"[{actual}]" for actual in select_cols.values()
            )
            our_fields = list(select_cols.keys())

            sql = f"SELECT TOP {limit} {col_list} FROM [{self.study_table}]"
            params = []

            # Date filters on whichever date column we resolved
            date_col = select_cols.get('study_date')
            if date_col and (from_date or to_date):
                clauses = []
                if from_date:
                    clauses.append(f"[{date_col}] >= ?")
                    params.append(from_date)
                if to_date:
                    clauses.append(f"[{date_col}] <= ?")
                    params.append(to_date)
                sql += " WHERE " + " AND ".join(clauses)

            if date_col:
                sql += f" ORDER BY [{date_col}] DESC"

            log.info("Candelis query: %s  params=%s", sql, params)
            cursor.execute(sql, params)

            results = []
            for row in cursor.fetchall():
                record = {}
                for i, field in enumerate(our_fields):
                    val = row[i]
                    # Normalize date/datetime to string for JSON serialisation
                    if isinstance(val, datetime):
                        val = val.isoformat()
                    elif hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    record[field] = val
                # Also stash the raw row for full provenance
                record['_raw'] = json.dumps(
                    {our_fields[i]: str(row[i]) if row[i] is not None else None
                     for i in range(len(our_fields))},
                    default=str,
                )
                results.append(record)

            return results, our_fields
        finally:
            conn.close()

    def fetch_study_count(self, from_date=None, to_date=None):
        """Return the total study count (optionally filtered by date range)."""
        conn = self.connect()
        try:
            cursor = conn.cursor()
            available = set(self.list_columns(self.study_table))

            sql = f"SELECT COUNT(*) FROM [{self.study_table}]"
            params = []

            # Find the date column
            date_candidates = ['StudyDate', 'ExamDate', 'ScheduledDate', 'study_date']
            date_col = next((c for c in date_candidates if c in available), None)

            if date_col and (from_date or to_date):
                clauses = []
                if from_date:
                    clauses.append(f"[{date_col}] >= ?")
                    params.append(from_date)
                if to_date:
                    clauses.append(f"[{date_col}] <= ?")
                    params.append(to_date)
                sql += " WHERE " + " AND ".join(clauses)

            cursor.execute(sql, params)
            return cursor.fetchone()[0]
        finally:
            conn.close()
