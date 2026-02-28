# OCDR Database Redesign — Opus-Level Architecture Review

**Version:** 1.0 | **Created:** 2026-02-26 | **Reviewer:** Claude Opus 4.6
**Current State:** 14 tables, SQLite, no FK constraints, no migrations
**Target State:** Properly normalized, FK-enforced, migration-ready, LLM-queryable

---

## 1. EXECUTIVE SUMMARY

The current database works but has accumulated structural debt. It was built feature-by-feature (billing → ERA → matching → smart learning) and each layer added tables without rethinking the whole. The result is a schema where:

- **Nothing references anything** — zero foreign key constraints enforced
- **Strings do the work of foreign keys** — carrier names, doctor names, modality codes are free-text everywhere
- **Comma-separated values live in columns** — CPT codes, CAS codes packed into single TEXT fields
- **Money is stored as floats** — precision loss on every calculation
- **No audit trail** — most tables lack updated_at; no soft deletes
- **No migration system** — schema changes require `db.create_all()` which can't alter existing columns

This document proposes a phased redesign that can be done incrementally without breaking the running system.

---

## 2. CURRENT SCHEMA PROBLEMS (Ranked by Impact)

### CRITICAL: Data Integrity

| # | Problem | Where | Impact |
|---|---------|-------|--------|
| D-01 | **No FK on matched_billing_id** | era_claim_lines → billing_records | Orphaned matches — claim points to deleted billing record, downstream code crashes |
| D-02 | **No FK on insurance_carrier** | billing_records.insurance_carrier is free-text | "M/M", "MEDICARE", "MEDI-CAL" all stored differently; payer analytics fragment |
| D-03 | **No FK on referring_doctor** | billing_records.referring_doctor is free-text | "SMITH, JOHN" vs "SMITH,JOHN" vs "Dr. Smith" — physician stats are wrong |
| D-04 | **CPT codes as comma-separated string** | era_claim_lines.cpt_code | Can't query "find all claims with CPT 74177"; can't index; can't join |
| D-05 | **CAS codes as comma-separated string** | era_claim_lines.cas_group_code, cas_reason_code | Same problem — denial analytics require string parsing in Python |
| D-06 | **No unique constraints** | fee_schedule(payer,modality), learned_weights(carrier,modality) | Duplicate rows accumulate silently |

### HIGH: Financial Precision

| # | Problem | Where | Impact |
|---|---------|-------|--------|
| D-07 | **Money stored as FLOAT/DECIMAL** | All payment columns | IEEE 754 rounding: $100.10 + $200.20 might = $300.29999... |
| D-08 | **Gado premium hardcoded** | api.py line ~160, not in fee_schedule | $200 premium applied in Python, not queryable, not auditable |
| D-09 | **total_payment invariant not enforced** | billing_records | total != primary + secondary after denial resolution |

### MEDIUM: Query Performance

| # | Problem | Where | Impact |
|---|---------|-------|--------|
| D-10 | **Full table scans for analytics** | denial_queue, filing_deadlines, underpayments | Every dashboard load scans entire billing_records |
| D-11 | **No composite indexes** | (carrier, service_date), (modality, service_date), etc. | GROUP BY queries scan full table |
| D-12 | **Denormalized carrier/modality in match_outcomes** | Duplicates from billing_records | Data can diverge if billing record updated |

### LOW: Operational

| # | Problem | Where | Impact |
|---|---------|-------|--------|
| D-13 | **No soft deletes** | All tables | Can't undo; no history |
| D-14 | **datetime.utcnow() deprecated** | All default timestamps | Python 3.12+ warnings |
| D-15 | **No migration system** | No Alembic/Flask-Migrate | Schema changes require manual intervention |

---

## 3. PROPOSED SCHEMA V2

### Design Principles

1. **Foreign keys everywhere** — if column references another table, enforce it
2. **Lookup tables for controlled vocabularies** — modality, carrier, denial codes
3. **Junction tables for many-to-many** — CPT codes, CAS adjustments
4. **Integer cents for money** — $100.50 stored as 10050
5. **Audit columns on everything** — created_at, updated_at, deleted_at
6. **Composite indexes for common queries** — match the actual WHERE/GROUP BY patterns

### 3.1 New Lookup Tables

```sql
-- Controlled vocabulary for imaging modalities
CREATE TABLE modalities (
    code        TEXT PRIMARY KEY,    -- CT, HMRI, PET, BONE, OPEN, DX, GH
    display_name TEXT NOT NULL,       -- "High-Field MRI", "CT Scan"
    category    TEXT,                 -- MRI_GROUP, CT_PET_GROUP
    sort_order  INTEGER DEFAULT 0
);

-- Controlled vocabulary for scan types (body parts)
CREATE TABLE scan_types (
    code        TEXT PRIMARY KEY,    -- ABDOMEN, CHEST, HEAD, CERVICAL, LUMBAR
    display_name TEXT NOT NULL,
    sort_order  INTEGER DEFAULT 0
);

-- CPT code reference (expandable)
CREATE TABLE cpt_codes (
    code        TEXT PRIMARY KEY,    -- "74177", "70553"
    description TEXT,                -- "CT Abdomen with contrast"
    modality_code TEXT REFERENCES modalities(code),
    source      TEXT DEFAULT 'MANUAL' -- MANUAL, LEARNED, CMS
);

-- CAS reason code reference
CREATE TABLE cas_reason_codes (
    code        TEXT PRIMARY KEY,    -- "4", "45", "96", "197"
    group_code  TEXT NOT NULL,       -- CO, PR, OA, PI, CR
    description TEXT,                -- "The procedure code is inconsistent..."
    category    TEXT                  -- CODING, AUTHORIZATION, MEDICAL_NECESSITY, etc.
);
```

### 3.2 Modified Core Tables

```sql
-- billing_records v2: FKs enforced, money in cents, audit columns
ALTER TABLE billing_records ADD COLUMN modality_code TEXT REFERENCES modalities(code);
ALTER TABLE billing_records ADD COLUMN carrier_code TEXT REFERENCES payers(code);
ALTER TABLE billing_records ADD COLUMN scan_type_code TEXT REFERENCES scan_types(code);
ALTER TABLE billing_records ADD COLUMN physician_id INTEGER REFERENCES physicians(id);
ALTER TABLE billing_records ADD COLUMN updated_at DATETIME;
ALTER TABLE billing_records ADD COLUMN deleted_at DATETIME;

-- primary_payment_cents, secondary_payment_cents, total_payment_cents (INTEGER)
-- Keep old columns during migration, compute cents = round(dollars * 100)

-- era_claim_lines v2: proper FK, remove comma-separated fields
ALTER TABLE era_claim_lines ADD CONSTRAINT fk_matched_billing
    FOREIGN KEY (matched_billing_id) REFERENCES billing_records(id);
-- Remove: cpt_code, cas_group_code, cas_reason_code (move to junction tables)
```

### 3.3 New Junction Tables

```sql
-- Many-to-many: ERA claim line ↔ CPT codes
CREATE TABLE era_claim_cpt_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    era_claim_id    INTEGER NOT NULL REFERENCES era_claim_lines(id),
    cpt_code        TEXT NOT NULL REFERENCES cpt_codes(code),
    billed_amount   INTEGER,         -- cents
    paid_amount     INTEGER,         -- cents
    units           INTEGER DEFAULT 1
);
CREATE INDEX idx_claim_cpt ON era_claim_cpt_codes(era_claim_id);
CREATE INDEX idx_cpt_claim ON era_claim_cpt_codes(cpt_code);

-- Many-to-many: ERA claim line ↔ CAS adjustments
CREATE TABLE era_claim_adjustments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    era_claim_id    INTEGER NOT NULL REFERENCES era_claim_lines(id),
    group_code      TEXT NOT NULL,    -- CO, PR, OA, PI
    reason_code     TEXT NOT NULL REFERENCES cas_reason_codes(code),
    amount          INTEGER NOT NULL, -- cents (positive = reduction)
    quantity        INTEGER DEFAULT 0
);
CREATE INDEX idx_adj_claim ON era_claim_adjustments(era_claim_id);
CREATE INDEX idx_adj_reason ON era_claim_adjustments(reason_code);
```

### 3.4 Fee Schedule v2

```sql
-- Add gado premium as a proper column, add unique constraint
CREATE TABLE fee_schedule_v2 (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    payer_code              TEXT REFERENCES payers(code),  -- NULL = default
    modality_code           TEXT NOT NULL REFERENCES modalities(code),
    scan_type_code          TEXT REFERENCES scan_types(code), -- NULL = any
    base_rate_cents         INTEGER NOT NULL,    -- expected payment in cents
    gado_premium_cents      INTEGER DEFAULT 0,   -- contrast premium in cents
    underpayment_threshold  REAL DEFAULT 0.80,
    effective_date          DATE,                 -- when this rate starts
    end_date                DATE,                 -- NULL = current
    source                  TEXT DEFAULT 'MANUAL',-- MANUAL, LEARNED, CONTRACT
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME,
    UNIQUE(payer_code, modality_code, scan_type_code, effective_date)
);
```

### 3.5 Composite Indexes for Common Queries

```sql
-- Dashboard: revenue by carrier by month
CREATE INDEX idx_billing_carrier_date ON billing_records(insurance_carrier, service_date);

-- Dashboard: revenue by modality
CREATE INDEX idx_billing_modality_date ON billing_records(modality, service_date);

-- Denial queue: unpaid claims by carrier
CREATE INDEX idx_billing_denial ON billing_records(denial_status, insurance_carrier, service_date);

-- Filing deadlines: unpaid claims by date
CREATE INDEX idx_billing_unpaid_date ON billing_records(total_payment, service_date)
    WHERE total_payment = 0;

-- Match engine: candidates by date range
CREATE INDEX idx_billing_match ON billing_records(service_date, patient_name, modality);

-- ERA: claims by payment
CREATE INDEX idx_era_claims_payment ON era_claim_lines(era_payment_id, paid_amount);

-- Schedule: upcoming appointments
CREATE INDEX idx_schedule_upcoming ON schedule_records(scheduled_date, status);
```

---

## 4. MIGRATION STRATEGY

### Phase 1: Non-Breaking Additions (Sprint 11)
Add new columns, lookup tables, and junction tables alongside existing ones.
No existing code breaks. Dual-write during transition.

```
billing_records.insurance_carrier  → keep (old)
billing_records.carrier_code       → add (new FK)
```

### Phase 2: Backfill & Dual-Write (Sprint 11-12)
Migration script populates new columns from old ones.
All write paths updated to set both old and new columns.

### Phase 3: Read Migration (Sprint 12-13)
Queries migrated one endpoint at a time to use new columns.
Each migration is a separate commit; easy to revert.

### Phase 4: Drop Old Columns (Sprint 14+)
Once all reads use new columns, drop the old free-text columns.
Only after full test coverage confirms nothing references them.

### Migration Tooling
```bash
# Install Flask-Migrate (wraps Alembic)
pip install Flask-Migrate

# Initialize
flask db init

# Generate migration from model changes
flask db migrate -m "Add lookup tables and FKs"

# Apply
flask db upgrade

# Rollback
flask db downgrade
```

---

## 5. LLM QUERYABILITY

The redesigned schema is specifically optimized for LLM interaction:

### Why This Matters
When a local LLM is connected, it will need to:
1. **Understand the schema** — clear table/column names, no encoded knowledge
2. **Write correct SQL** — FKs make JOINs obvious; lookup tables make filters clear
3. **Avoid data quality traps** — normalized data means no "MEDICARE vs M/M" confusion

### Schema Description for LLM Context
```
Tables: billing_records, era_payments, era_claim_lines, payers,
        fee_schedule, physicians, schedule_records, modalities,
        scan_types, cpt_codes, cas_reason_codes,
        era_claim_cpt_codes, era_claim_adjustments

Key relationships:
  billing_records.carrier_code → payers.code
  billing_records.modality_code → modalities.code
  billing_records.scan_type_code → scan_types.code
  era_claim_lines.era_payment_id → era_payments.id
  era_claim_lines.matched_billing_id → billing_records.id
  era_claim_cpt_codes.era_claim_id → era_claim_lines.id
  era_claim_cpt_codes.cpt_code → cpt_codes.code
  era_claim_adjustments.era_claim_id → era_claim_lines.id

Money columns end in _cents (INTEGER, divide by 100 for display).
Dates are ISO 8601 (YYYY-MM-DD).
All tables have created_at. Most have updated_at.
```

This schema description fits in ~500 tokens — small enough to include in every LLM prompt.

---

## 6. WHAT NOT TO CHANGE

Some things look like problems but aren't worth fixing:

1. **SQLite as the database** — This is a local-first app. SQLite handles 50K records easily. No need for PostgreSQL unless multi-user.
2. **Single models.py file** — 14 models in one file is fine. Splitting into a models/ package adds complexity for no gain at this scale.
3. **Flask blueprints structure** — Two blueprints (ui + api) is appropriate. No need to split further.
4. **Test structure** — 6 test files with 221 tests is well-organized. Don't restructure.
5. **The learning tables (SM-01 through SM-12)** — These are well-designed. They layer on top correctly and don't need restructuring.
