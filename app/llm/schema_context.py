"""Auto-generates a schema description (~500 tokens) for LLM prompts.

Provides a concise, structured summary of the database schema so an LLM
can understand available tables, columns, relationships, and data conventions
without needing direct database access.
"""


def get_schema_context() -> str:
    """Return a string describing all tables, columns, relationships,
    and data conventions for use in LLM prompts.

    The description is kept to approximately 500 tokens to fit within
    typical context windows alongside user queries.
    """
    return _SCHEMA_DESCRIPTION


_SCHEMA_DESCRIPTION = """\
DATABASE SCHEMA FOR OCDR (Outpatient Center Data Reconciliation)

TABLES:

1. billing_records - Core billing/claims table.
   Columns: id (int PK), patient_name (text), referring_doctor (text),
   scan_type (text), gado_used (bool), insurance_carrier (text),
   modality (text), service_date (date), primary_payment (float $),
   secondary_payment (float $), total_payment (float $),
   extra_charges (float $), reading_physician (text), description (text),
   is_psma (bool), denial_status (text), denial_reason_code (text),
   era_claim_id (text), appeal_deadline (date), import_source (text),
   created_at (datetime).

2. era_payments - ERA (Electronic Remittance Advice) payment batches.
   Columns: id (int PK), filename (text), check_eft_number (text),
   payment_amount (float $), payment_date (date),
   payment_method (text), payer_name (text), parsed_at (datetime).
   Relationship: has many era_claim_lines.

3. era_claim_lines - Individual claim lines within an ERA payment.
   Columns: id (int PK), era_payment_id (int FK->era_payments),
   claim_id (text), claim_status (text), billed_amount (float $),
   paid_amount (float $), patient_name_835 (text),
   service_date_835 (date), cpt_code (text), cas_group_code (text),
   cas_reason_code (text), cas_adjustment_amount (float $),
   match_confidence (float 0-1), matched_billing_id (int FK->billing_records).

4. payers - Insurance payer configuration.
   Columns: code (text PK), display_name (text),
   filing_deadline_days (int), expected_has_secondary (bool).

5. fee_schedule - Expected payment rates by payer and modality.
   Columns: id (int PK), payer_code (text), modality (text),
   expected_rate (float $), underpayment_threshold (float 0-1).

6. schedule_records - Patient appointment schedule.
   Columns: id (int PK), patient_name (text), scan_type (text),
   modality (text), scheduled_date (date), scheduled_time (text),
   referring_doctor (text), insurance_carrier (text), location (text),
   status (text), import_source (text).

7. physicians - Reading/referring physician reference.
   Columns: name (text PK), physician_type (text), specialty (text),
   clinic_affiliation (text).

RELATIONSHIPS:
- era_claim_lines.era_payment_id -> era_payments.id
- era_claim_lines.matched_billing_id -> billing_records.id
- fee_schedule.payer_code references payers.code
- fee_schedule.modality references modalities.code

DATA CONVENTIONS:
- Modality codes: CT, HMRI (High-Field MRI), PET, BONE, OPEN (Open MRI), DX (Digital X-Ray), GH (General Health).
- Carrier codes: M/M (Medicare/Medicaid), CALOPTIMA, FAMILY (Family Health), INS (Generic Insurance), W/C (Workers Comp), SELF PAY.
- All monetary values are in US dollars as float (e.g. 250.00).
- Dates are formatted YYYY-MM-DD.
- denial_status values: DENIED, APPEALED, RESOLVED, or NULL (no denial).
- schedule_records.status values: SCHEDULED, COMPLETED, CANCELLED, NO_SHOW.
- match_confidence ranges from 0.0 (no match) to 1.0 (perfect match).\
"""
