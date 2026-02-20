"""Initial full schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

Creates all tables for the OCDR Medical Imaging Practice Management System:
  users, patients, insurance, appointments, scans, claims, payments,
  eobs, eob_line_items, reconciliation, audit_logs,
  corrections, payer_templates, business_rules, denial_patterns, api_call_logs
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ENUM types (PostgreSQL) ───────────────────────────────────────────────
    # SQLite ignores these; PostgreSQL needs them defined before use.
    connection = op.get_bind()
    is_pg = connection.dialect.name == "postgresql"

    if is_pg:
        op.execute("CREATE TYPE user_role_enum AS ENUM ('admin','biller','front_desk','read_only')")
        op.execute("CREATE TYPE gender_enum AS ENUM ('M','F','O','U')")
        op.execute("CREATE TYPE patient_verification_enum AS ENUM ('verified','needs_verification','flagged')")
        op.execute("CREATE TYPE modality_enum AS ENUM ('MRI','PET','CT','PET_CT','BONE_SCAN','XRAY','ULTRASOUND','OTHER')")
        op.execute("CREATE TYPE appointment_status_enum AS ENUM ('scheduled','completed','cancelled','no_show','rescheduled')")
        op.execute("CREATE TYPE report_status_enum AS ENUM ('pending','preliminary','final','amended','corrected')")
        op.execute("CREATE TYPE claim_status_enum AS ENUM ('draft','submitted','accepted','pending','paid','denied','partial','appealed','void','corrected')")
        op.execute("CREATE TYPE payment_type_enum AS ENUM ('insurance_check','insurance_eft','insurance_era','patient_check','patient_credit_card','patient_cash','patient_ach','adjustment')")
        op.execute("CREATE TYPE posting_status_enum AS ENUM ('pending','posted','rejected','needs_review')")
        op.execute("CREATE TYPE eob_file_type_enum AS ENUM ('pdf','image','era_835','manual')")
        op.execute("CREATE TYPE eob_processed_status_enum AS ENUM ('pending','processing','processed','failed','needs_review')")
        op.execute("CREATE TYPE extraction_method_enum AS ENUM ('pdfplumber','tesseract','era_835','manual')")
        op.execute("CREATE TYPE line_match_status_enum AS ENUM ('unmatched','matched','manual_review','rejected')")
        op.execute("CREATE TYPE recon_status_enum AS ENUM ('matched','partial','unmatched','disputed','written_off')")
        op.execute("CREATE TYPE audit_action_enum AS ENUM ('INSERT','UPDATE','DELETE')")
        op.execute("CREATE TYPE doc_type_enum AS ENUM ('schedule','eob','payment')")
        op.execute("CREATE TYPE rule_type_enum AS ENUM ('pct_of_billed','pct_of_medicare','fixed_amount','formula')")
        op.execute("CREATE TYPE api_service_enum AS ENUM ('office_ally','purview','other')")

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="read_only"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── patients ──────────────────────────────────────────────────────────────
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mrn", sa.String(50), nullable=False, unique=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("gender", sa.String(1), nullable=True),
        sa.Column("address_line1", sa.String(200), nullable=True),
        sa.Column("address_line2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("zip_code", sa.String(10), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("ssn_encrypted", sa.String(512), nullable=True, comment="Fernet-encrypted SSN"),
        sa.Column("verification_status", sa.String(50), nullable=False, server_default="needs_verification"),
        sa.Column("source_file", sa.String(500), nullable=True),
        sa.Column("extraction_confidence", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_patients_mrn", "patients", ["mrn"])
    op.create_index("ix_patients_dob", "patients", ["dob"])
    op.create_index("ix_patients_last_name", "patients", ["last_name"])

    # ── insurance ─────────────────────────────────────────────────────────────
    op.create_table(
        "insurance",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payer_name", sa.String(255), nullable=False),
        sa.Column("payer_id", sa.String(50), nullable=True),
        sa.Column("plan_name", sa.String(255), nullable=True),
        sa.Column("member_id", sa.String(100), nullable=True),
        sa.Column("group_number", sa.String(100), nullable=True),
        sa.Column("subscriber_name", sa.String(255), nullable=True),
        sa.Column("relationship_to_patient", sa.String(50), nullable=True),
        sa.Column("copay", sa.Numeric(10, 2), nullable=True),
        sa.Column("deductible", sa.Numeric(10, 2), nullable=True),
        sa.Column("out_of_pocket_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("authorization_number", sa.String(100), nullable=True),
        sa.Column("authorization_start_date", sa.Date, nullable=True),
        sa.Column("authorization_end_date", sa.Date, nullable=True),
        sa.Column("authorized_visits", sa.Integer, nullable=True),
        sa.Column("visits_used", sa.Integer, nullable=True, server_default="0"),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_secondary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("eligibility_verified", sa.Boolean, nullable=True),
        sa.Column("eligibility_verified_at", sa.Date, nullable=True),
        sa.Column("eligibility_response_raw", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_insurance_patient_id", "insurance", ["patient_id"])
    op.create_index("ix_insurance_payer_id", "insurance", ["payer_id"])
    op.create_index("ix_insurance_member_id", "insurance", ["member_id"])

    # ── appointments ──────────────────────────────────────────────────────────
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scan_date", sa.Date, nullable=False),
        sa.Column("scan_time", sa.Time, nullable=True),
        sa.Column("modality", sa.String(50), nullable=False),
        sa.Column("body_part", sa.String(200), nullable=True),
        sa.Column("referring_physician", sa.String(255), nullable=True),
        sa.Column("ordering_physician", sa.String(255), nullable=True),
        sa.Column("ordering_npi", sa.String(20), nullable=True),
        sa.Column("facility_location", sa.String(255), nullable=True),
        sa.Column("technologist", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source_file", sa.String(500), nullable=True),
        sa.Column("extraction_confidence", sa.Float, nullable=True),
        sa.Column("raw_extracted_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.create_index("ix_appointments_scan_date", "appointments", ["scan_date"])
    op.create_index("ix_appointments_modality", "appointments", ["modality"])
    op.create_index("ix_appointments_status", "appointments", ["status"])

    # ── scans ─────────────────────────────────────────────────────────────────
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("accession_number", sa.String(100), nullable=True, unique=True),
        sa.Column("dicom_study_uid", sa.String(255), nullable=True, unique=True),
        sa.Column("study_description", sa.String(500), nullable=True),
        sa.Column("radiologist", sa.String(255), nullable=True),
        sa.Column("report_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("cpt_codes", sa.JSON, nullable=True),
        sa.Column("units", sa.Integer, nullable=True, server_default="1"),
        sa.Column("charges", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scans_appointment_id", "scans", ["appointment_id"])
    op.create_index("ix_scans_accession_number", "scans", ["accession_number"])

    # ── claims ────────────────────────────────────────────────────────────────
    op.create_table(
        "claims",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scan_id", sa.Integer, sa.ForeignKey("scans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("insurance_id", sa.Integer, sa.ForeignKey("insurance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("claim_number", sa.String(100), nullable=True, unique=True),
        sa.Column("office_ally_claim_id", sa.String(100), nullable=True),
        sa.Column("date_of_service", sa.Date, nullable=True),
        sa.Column("date_submitted", sa.Date, nullable=True),
        sa.Column("follow_up_date", sa.Date, nullable=True),
        sa.Column("billed_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("allowed_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("adjustment_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("patient_responsibility", sa.Numeric(10, 2), nullable=True),
        sa.Column("claim_status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("denial_reason", sa.Text, nullable=True),
        sa.Column("denial_code", sa.String(50), nullable=True),
        sa.Column("last_synced_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_claims_scan_id", "claims", ["scan_id"])
    op.create_index("ix_claims_insurance_id", "claims", ["insurance_id"])
    op.create_index("ix_claims_claim_number", "claims", ["claim_number"])
    op.create_index("ix_claims_claim_status", "claims", ["claim_status"])
    op.create_index("ix_claims_date_of_service", "claims", ["date_of_service"])
    op.create_index("ix_claims_denial_code", "claims", ["denial_code"])

    # ── eobs ──────────────────────────────────────────────────────────────────
    op.create_table(
        "eobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("raw_file_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False, server_default="pdf"),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("payer_id", sa.String(50), nullable=True),
        sa.Column("check_number", sa.String(100), nullable=True),
        sa.Column("check_date", sa.Date, nullable=True),
        sa.Column("npi", sa.String(20), nullable=True),
        sa.Column("total_paid", sa.Numeric(10, 2), nullable=True),
        sa.Column("processed_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_claim_ids", sa.JSON, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("raw_extracted_text", sa.Text, nullable=True),
        sa.Column("extraction_method", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_eobs_payer_name", "eobs", ["payer_name"])
    op.create_index("ix_eobs_check_number", "eobs", ["check_number"])
    op.create_index("ix_eobs_processed_status", "eobs", ["processed_status"])

    # ── eob_line_items ────────────────────────────────────────────────────────
    op.create_table(
        "eob_line_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("eob_id", sa.Integer, sa.ForeignKey("eobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_id", sa.Integer, sa.ForeignKey("claims.id", ondelete="SET NULL"), nullable=True),
        sa.Column("patient_name_raw", sa.String(255), nullable=True),
        sa.Column("date_of_service", sa.Date, nullable=True),
        sa.Column("cpt_code", sa.String(20), nullable=True),
        sa.Column("modifier", sa.String(10), nullable=True),
        sa.Column("units", sa.Integer, nullable=True),
        sa.Column("billed_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("allowed_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("patient_responsibility", sa.Numeric(10, 2), nullable=True),
        sa.Column("adjustment_codes", sa.JSON, nullable=True),
        sa.Column("match_confidence", sa.Float, nullable=True),
        sa.Column("match_pass", sa.String(50), nullable=True),
        sa.Column("match_status", sa.String(50), nullable=False, server_default="unmatched"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_eob_line_items_eob_id", "eob_line_items", ["eob_id"])
    op.create_index("ix_eob_line_items_claim_id", "eob_line_items", ["claim_id"])
    op.create_index("ix_eob_line_items_dos", "eob_line_items", ["date_of_service"])

    # ── payments ──────────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("claim_id", sa.Integer, sa.ForeignKey("claims.id", ondelete="SET NULL"), nullable=True),
        sa.Column("eob_id", sa.Integer, sa.ForeignKey("eobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("payment_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("check_number", sa.String(100), nullable=True),
        sa.Column("check_image_path", sa.String(500), nullable=True),
        sa.Column("eob_source_file", sa.String(500), nullable=True),
        sa.Column("posting_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("posted_by", sa.String(100), nullable=True),
        sa.Column("posted_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_confidence", sa.Float, nullable=True),
        sa.Column("match_pass", sa.String(50), nullable=True),
        sa.Column("adjustment_codes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payments_patient_id", "payments", ["patient_id"])
    op.create_index("ix_payments_claim_id", "payments", ["claim_id"])
    op.create_index("ix_payments_payment_date", "payments", ["payment_date"])
    op.create_index("ix_payments_posting_status", "payments", ["posting_status"])
    op.create_index("ix_payments_check_number", "payments", ["check_number"])

    # ── reconciliation ────────────────────────────────────────────────────────
    op.create_table(
        "reconciliation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("claim_id", sa.Integer, sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("expected_payment", sa.Numeric(10, 2), nullable=True),
        sa.Column("actual_payment", sa.Numeric(10, 2), nullable=True),
        sa.Column("variance", sa.Numeric(10, 2), nullable=True),
        sa.Column("variance_pct", sa.Float, nullable=True),
        sa.Column("reconciliation_status", sa.String(50), nullable=False, server_default="unmatched"),
        sa.Column("flagged_for_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reconciliation_claim_id", "reconciliation", ["claim_id"])
    op.create_index("ix_reconciliation_status", "reconciliation", ["reconciliation_status"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("record_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("old_values", sa.Text, nullable=True),
        sa.Column("new_values", sa.Text, nullable=True),
        sa.Column("changed_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_table_name", "audit_logs", ["table_name"])
    op.create_index("ix_audit_logs_record_id", "audit_logs", ["record_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_changed_at", "audit_logs", ["changed_at"])

    # ── corrections ───────────────────────────────────────────────────────────
    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_document_type", sa.String(50), nullable=False),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("original_extracted_value", sa.Text, nullable=True),
        sa.Column("corrected_value", sa.Text, nullable=True),
        sa.Column("document_path", sa.String(500), nullable=True),
        sa.Column("corrected_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_corrections_payer_name", "corrections", ["payer_name"])
    op.create_index("ix_corrections_field_name", "corrections", ["field_name"])

    # ── payer_templates ───────────────────────────────────────────────────────
    op.create_table(
        "payer_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payer_name", sa.String(255), nullable=False, unique=True),
        sa.Column("field_patterns", sa.JSON, nullable=True),
        sa.Column("extraction_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payer_templates_payer_name", "payer_templates", ["payer_name"])

    # ── business_rules ────────────────────────────────────────────────────────
    op.create_table(
        "business_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule_name", sa.String(255), nullable=False),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("payer_id", sa.String(50), nullable=True),
        sa.Column("cpt_code", sa.String(20), nullable=True),
        sa.Column("modality", sa.String(50), nullable=True),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("rule_params", sa.JSON, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_business_rules_payer_id", "business_rules", ["payer_id"])
    op.create_index("ix_business_rules_cpt_code", "business_rules", ["cpt_code"])

    # ── denial_patterns ───────────────────────────────────────────────────────
    op.create_table(
        "denial_patterns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("payer_id", sa.String(50), nullable=True),
        sa.Column("cpt_code", sa.String(20), nullable=True),
        sa.Column("denial_code", sa.String(50), nullable=False),
        sa.Column("denial_reason", sa.Text, nullable=True),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("total_denied_amount", sa.Float, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_denial_patterns_denial_code", "denial_patterns", ["denial_code"])
    op.create_index("ix_denial_patterns_payer_name", "denial_patterns", ["payer_name"])
    op.create_index("ix_denial_patterns_cpt_code", "denial_patterns", ["cpt_code"])

    # ── api_call_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "api_call_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("request_payload", sa.Text, nullable=True),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_call_logs_service", "api_call_logs", ["service"])


def downgrade() -> None:
    op.drop_table("api_call_logs")
    op.drop_table("denial_patterns")
    op.drop_table("business_rules")
    op.drop_table("payer_templates")
    op.drop_table("corrections")
    op.drop_table("audit_logs")
    op.drop_table("reconciliation")
    op.drop_table("payments")
    op.drop_table("eob_line_items")
    op.drop_table("eobs")
    op.drop_table("claims")
    op.drop_table("scans")
    op.drop_table("appointments")
    op.drop_table("insurance")
    op.drop_table("patients")
    op.drop_table("users")

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        for enum_name in [
            "user_role_enum", "gender_enum", "patient_verification_enum",
            "modality_enum", "appointment_status_enum", "report_status_enum",
            "claim_status_enum", "payment_type_enum", "posting_status_enum",
            "eob_file_type_enum", "eob_processed_status_enum", "extraction_method_enum",
            "line_match_status_enum", "recon_status_enum", "audit_action_enum",
            "doc_type_enum", "rule_type_enum", "api_service_enum",
        ]:
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")
