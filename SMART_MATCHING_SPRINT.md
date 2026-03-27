# OCDR Smart Matching Features – Feature List & Sprint Plan

**Version:** 1.0 | **Created:** 2026-02-25 | **Builds on:** BUILD_SPEC.md v5.0
**Constraint:** 100% LOCAL – all learning stored in SQLite, no cloud/ML APIs

---

## 1. FEATURE PRIORITY LIST (Ranked by Revenue Impact)

### TIER 1 — HIGH IMPACT (Estimated $200K+ annual recovery)

| # | Feature | Current Problem | Smart Solution | Revenue Impact |
|---|---------|----------------|---------------|----------------|
| SM-01 | **Adaptive Match Weights** | Fixed 0.50/0.30/0.20 weights for name/date/modality — suboptimal for different payer types | Learn optimal weights per carrier and modality from confirm/reject outcomes | HIGH — reduces manual review queue by 40-60%, catches missed auto-accepts |
| SM-02 | **Adaptive Match Thresholds** | Fixed 0.95 auto-accept, 0.80 review — too conservative for known-good carriers, too loose for problem carriers | Per-carrier/modality thresholds that tighten or loosen based on historical accuracy | HIGH — fewer false accepts (saves rework), fewer false rejects (catches revenue) |
| SM-03 | **Denial Recoverability Learning** | Fixed formula `expected * (1 - days/365)` with $500 fallback — ignores actual recovery rates by carrier/reason | Track actual appeal outcomes, learn real recovery rates per carrier + denial reason code | HIGH — prioritizes queue by actual likelihood of recovery, not just age |
| SM-04 | **Patient Name Alias Memory** | Fuzzy match fails on nicknames (WILLIAM/BILL), maiden names, spelling variants | Store confirmed name pairs as aliases; auto-match on future encounters | HIGH — directly fixes the #1 match failure mode |

### TIER 2 — MEDIUM IMPACT (Estimated $50-200K annual recovery)

| # | Feature | Current Problem | Smart Solution | Revenue Impact |
|---|---------|----------------|---------------|----------------|
| SM-05 | **CPT-to-Modality Learning** | Hardcoded ~20 CPT prefix mappings — new CPT codes get 0.0 modality score | Learn CPT→modality from confirmed matches; expand map automatically | MEDIUM — fixes modality mismatch for new procedure codes |
| SM-06 | **Date Proximity Scoring Curves** | Step function: exact=1.0, ±1=0.8, ±2=0.5, else=0.0 — doesn't reflect real patterns | Learn actual date offset distribution from confirmed matches; smooth scoring curve | MEDIUM — catches matches at ±3-5 days that currently score 0.0 |
| SM-07 | **Carrier Payment Pattern Learning** | Fee schedule is static DEFAULT rates — doesn't reflect actual payer behavior | Track actual payment amounts per carrier/modality, detect underpayment trends | MEDIUM — auto-updates expected rates, catches systematic underpayment |
| SM-08 | **Import Column Alias Learning** | Fixed alias maps in importers — new column names fail silently | Remember manually mapped columns for future imports from same source | MEDIUM — reduces import errors and manual intervention |

### TIER 3 — OPERATIONAL EFFICIENCY

| # | Feature | Current Problem | Smart Solution | Revenue Impact |
|---|---------|----------------|---------------|----------------|
| SM-09 | **Normalization Map Expansion** | Fixed MODALITY_MAP and CARRIER_NORMALIZE — new variations need code changes | Auto-detect unmapped values, suggest mappings based on context, remember approvals | LOW-MEDIUM — prevents data quality degradation over time |
| SM-10 | **Match Confidence Calibration** | Confidence scores aren't calibrated — 0.90 doesn't mean 90% correct | Calibrate scores against actual accuracy using Platt scaling on historical data | LOW — improves trust in auto-accept decisions |
| SM-11 | **PSMA Keyword Expansion** | Fixed 4 keywords: PSMA, GA-68, GA68, GALLIUM | Learn new PSMA indicators from confirmed PSMA records | LOW — ensures no PSMA revenue tracking is missed |
| SM-12 | **Denial Reason Pattern Detection** | Denial codes displayed but no pattern analysis | Detect recurring denial patterns (same carrier + reason + modality) and auto-flag | LOW — proactive denial prevention vs reactive appeals |

---

## 2. DATABASE SCHEMA — New Tables for Smart Matching

### Table: match_outcomes
Stores every confirm/reject decision for learning.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| era_claim_id | INTEGER | FK NOT NULL | The ERA claim line |
| billing_record_id | INTEGER | FK | The billing record it was matched to |
| action | TEXT | NOT NULL | CONFIRMED, REJECTED, REASSIGNED |
| original_score | FLOAT | | Score at time of match |
| name_score | FLOAT | | Component: name similarity |
| date_score | FLOAT | | Component: date proximity |
| modality_score | FLOAT | | Component: modality match |
| carrier | TEXT | | Insurance carrier at time of match |
| modality | TEXT | | Billing modality at time of match |
| created_at | DATETIME | DEFAULT NOW | When decision was made |

### Table: name_aliases
Stores confirmed patient name pairs.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| name_a | TEXT | NOT NULL | First name variant (normalized) |
| name_b | TEXT | NOT NULL | Second name variant (normalized) |
| match_count | INTEGER | DEFAULT 1 | Times this pair was confirmed |
| created_at | DATETIME | DEFAULT NOW | First seen |

### Table: learned_weights
Stores optimized weights per carrier/modality combination.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| carrier | TEXT | | Carrier code (NULL = global default) |
| modality | TEXT | | Modality (NULL = all modalities) |
| name_weight | FLOAT | NOT NULL | Learned name weight (default 0.50) |
| date_weight | FLOAT | NOT NULL | Learned date weight (default 0.30) |
| modality_weight | FLOAT | NOT NULL | Learned modality weight (default 0.20) |
| auto_accept_threshold | FLOAT | NOT NULL | Learned auto-accept (default 0.95) |
| review_threshold | FLOAT | NOT NULL | Learned review threshold (default 0.80) |
| sample_size | INTEGER | DEFAULT 0 | Outcomes used to compute these weights |
| updated_at | DATETIME | DEFAULT NOW | Last recalculation |

### Table: learned_cpt_modality
Stores CPT→modality mappings learned from confirmed matches.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| cpt_prefix | TEXT | PK | CPT code or prefix |
| modality | TEXT | NOT NULL | Mapped modality code |
| confidence | FLOAT | DEFAULT 1.0 | Mapping confidence (0-1) |
| source | TEXT | NOT NULL | HARDCODED or LEARNED |
| match_count | INTEGER | DEFAULT 1 | Confirmed matches supporting this |
| updated_at | DATETIME | DEFAULT NOW | Last update |

### Table: denial_outcomes
Stores appeal results for learning recovery rates.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| billing_record_id | INTEGER | FK NOT NULL | The denied record |
| carrier | TEXT | NOT NULL | Insurance carrier |
| denial_reason | TEXT | | CAS reason code |
| modality | TEXT | | Modality |
| days_old_at_appeal | INTEGER | | Days old when appealed |
| outcome | TEXT | NOT NULL | RECOVERED, PARTIAL, WRITTEN_OFF |
| recovered_amount | FLOAT | DEFAULT 0 | Actual recovered dollars |
| expected_amount | FLOAT | | Expected from fee schedule |
| created_at | DATETIME | DEFAULT NOW | Resolution date |

### Table: column_aliases_learned
Stores import column mappings learned from user corrections.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| source_name | TEXT | NOT NULL | Original column header text |
| target_field | TEXT | NOT NULL | Mapped DB field name |
| source_format | TEXT | | CSV, EXCEL, PDF |
| confidence | FLOAT | DEFAULT 1.0 | Mapping confidence |
| use_count | INTEGER | DEFAULT 1 | Times this mapping was used |

### Table: normalization_learned
Stores new modality/carrier normalizations from user approvals.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK AUTOINCREMENT | Row ID |
| category | TEXT | NOT NULL | MODALITY or CARRIER |
| raw_value | TEXT | NOT NULL | Unmapped input value |
| normalized_value | TEXT | NOT NULL | Approved normalized form |
| approved_by | TEXT | DEFAULT 'SYSTEM' | USER or SYSTEM |
| use_count | INTEGER | DEFAULT 1 | Times applied |

---

## 3. SPRINT PLAN

### Sprint 7: Core Learning Infrastructure + Adaptive Matching
**Duration:** 2 weeks | **Goal:** Foundation for all smart features + highest-impact matching improvements

| Ticket | Feature | Title | Priority | Est Hours | Depends On | Files to Create/Modify |
|--------|---------|-------|----------|-----------|------------|----------------------|
| SM-01a | SM-01 | Match Outcome Tracking — record every confirm/reject with component scores | P0 | 8 | F-03 | `app/matching/match_memory.py`, `app/models.py` (add MatchOutcome model) |
| SM-01b | SM-01 | Weight Optimizer — compute optimal weights from outcomes per carrier/modality | P0 | 12 | SM-01a | `app/matching/weight_optimizer.py`, `app/models.py` (add LearnedWeights model) |
| SM-01c | SM-01 | Integrate learned weights into match engine — use per-carrier weights when available | P0 | 6 | SM-01b | `app/matching/match_engine.py` (modify `compute_match_score`, `run_matching`) |
| SM-02a | SM-02 | Threshold Optimizer — compute per-carrier auto-accept/review thresholds from accuracy metrics | P1 | 8 | SM-01a | `app/matching/weight_optimizer.py` (extend) |
| SM-02b | SM-02 | Apply adaptive thresholds in match runner | P1 | 4 | SM-02a | `app/matching/match_engine.py` (modify `run_matching`) |
| SM-04a | SM-04 | Name Alias Store — capture confirmed name pairs from match outcomes | P1 | 6 | SM-01a | `app/matching/match_memory.py` (extend), `app/models.py` (add NameAlias model) |
| SM-04b | SM-04 | Name Alias Lookup — boost name_similarity when alias pair is known | P1 | 6 | SM-04a | `app/matching/match_engine.py` (modify `name_similarity`) |
| SM-T01 | — | Tests for Sprint 7: outcome tracking, weight optimization, alias matching | P0 | 8 | all above | `tests/test_smart_matching.py` |

**Sprint 7 Total: 58 hours**

**Acceptance Criteria:**
- Every match confirm/reject stores component scores in match_outcomes table
- After 50+ outcomes for a carrier, learned weights are used instead of defaults
- Confirmed name pairs are stored and boost future match scores to 1.0
- Adaptive thresholds computed per carrier from precision/recall metrics
- All existing 156 tests still pass + 20+ new smart matching tests

---

### Sprint 8: Denial Intelligence + Payment Learning
**Duration:** 2 weeks | **Goal:** Smart denial prioritization + payment pattern detection

| Ticket | Feature | Title | Priority | Est Hours | Depends On | Files to Create/Modify |
|--------|---------|-------|----------|-----------|------------|----------------------|
| SM-03a | SM-03 | Denial Outcome Tracking — record appeal results (recovered, partial, written-off) | P0 | 6 | F-04 | `app/revenue/denial_memory.py`, `app/models.py` (add DenialOutcome model) |
| SM-03b | SM-03 | Recovery Rate Calculator — compute actual recovery rates per carrier + denial reason | P0 | 8 | SM-03a | `app/revenue/denial_memory.py` (extend) |
| SM-03c | SM-03 | Smart Recoverability Scoring — replace fixed formula with learned rates | P1 | 6 | SM-03b | `app/revenue/denial_tracker.py` (modify `_recoverability_score`) |
| SM-07a | SM-07 | Payment Pattern Tracker — aggregate actual payments per carrier/modality | P1 | 8 | F-05 | `app/revenue/payment_patterns.py`, `app/models.py` |
| SM-07b | SM-07 | Auto-Update Fee Schedule — suggest or auto-apply learned expected rates | P2 | 6 | SM-07a | `app/revenue/payment_patterns.py` (extend), `app/ui/api.py` |
| SM-12a | SM-12 | Denial Pattern Detection — identify recurring carrier+reason+modality combos | P2 | 6 | SM-03a | `app/revenue/denial_memory.py` (extend) |
| SM-T02 | — | Tests for Sprint 8: denial outcomes, recovery rates, payment patterns | P0 | 8 | all above | `tests/test_denial_learning.py` |

**Sprint 8 Total: 48 hours**

**Acceptance Criteria:**
- Every denial resolution stores actual recovered amount in denial_outcomes table
- After 10+ outcomes for a carrier+reason combo, learned recovery rate replaces formula
- Payment patterns tracked with rolling 90-day averages per carrier/modality
- Recurring denial patterns (3+ occurrences) flagged with suggested preventive action
- API endpoint to view learned recovery rates and payment patterns

---

### Sprint 9: Matching Refinements + Import Intelligence
**Duration:** 2 weeks | **Goal:** Better CPT mapping, date scoring, import column learning

| Ticket | Feature | Title | Priority | Est Hours | Depends On | Files to Create/Modify |
|--------|---------|-------|----------|-----------|------------|----------------------|
| SM-05a | SM-05 | CPT Learning Store — capture CPT→modality from confirmed matches | P1 | 6 | SM-01a | `app/matching/match_memory.py` (extend), `app/models.py` (add LearnedCptModality) |
| SM-05b | SM-05 | Integrate learned CPT map into modality scoring | P1 | 4 | SM-05a | `app/matching/match_engine.py` (modify `_cpt_to_modality`) |
| SM-06a | SM-06 | Date Distribution Tracker — record actual date offsets from confirmed matches | P2 | 4 | SM-01a | `app/matching/match_memory.py` (extend) |
| SM-06b | SM-06 | Smooth Date Scoring — replace step function with learned distribution curve | P2 | 6 | SM-06a | `app/matching/match_engine.py` (modify `date_match_score`) |
| SM-08a | SM-08 | Import Column Learning — prompt on unmapped columns, store user mappings | P2 | 8 | F-12 | `app/import_engine/column_learner.py`, `app/models.py` (add ColumnAliasLearned) |
| SM-08b | SM-08 | Apply learned columns in future imports | P2 | 4 | SM-08a | `app/import_engine/csv_importer.py`, `app/import_engine/excel_importer.py` |
| SM-09a | SM-09 | Normalization Expansion — detect unmapped modality/carrier values, suggest mappings | P2 | 6 | — | `app/import_engine/normalization_learner.py`, `app/models.py` (add NormalizationLearned) |
| SM-09b | SM-09 | API for approving/rejecting normalization suggestions | P2 | 4 | SM-09a | `app/ui/api.py` (add endpoints) |
| SM-T03 | — | Tests for Sprint 9: CPT learning, date curves, column learning, normalization | P0 | 8 | all above | `tests/test_import_learning.py` |

**Sprint 9 Total: 50 hours**

**Acceptance Criteria:**
- New CPT codes learned from confirmed matches appear in CPT map within same session
- Date scoring uses Gaussian-like curve learned from actual date offset distribution
- Unmapped import columns trigger a prompt; user response stored for future imports
- Unknown modality/carrier values surfaced in admin dashboard with suggested mappings
- All normalization suggestions require user approval before being applied

---

### Sprint 10: Calibration, Analytics Dashboard, and Polish
**Duration:** 1 week | **Goal:** Confidence calibration, learning analytics UI, system polish

| Ticket | Feature | Title | Priority | Est Hours | Depends On | Files to Create/Modify |
|--------|---------|-------|----------|-----------|------------|----------------------|
| SM-10a | SM-10 | Confidence Calibration — Platt scaling on historical match outcomes | P2 | 8 | SM-01a | `app/matching/calibration.py` |
| SM-10b | SM-10 | Apply calibrated scores in match results display | P2 | 3 | SM-10a | `app/matching/match_engine.py`, `app/ui/api.py` |
| SM-11a | SM-11 | PSMA Keyword Learning — expand detection from confirmed PSMA records | P3 | 4 | — | `app/import_engine/validation.py` (modify `detect_psma`) |
| SM-UI1 | — | Smart Matching Analytics Dashboard — show learning progress, accuracy trends | P1 | 12 | SM-01a, SM-03a | `templates/smart_matching.html`, `app/ui/dashboard.py`, `app/ui/api.py` |
| SM-UI2 | — | Admin: Learning Configuration — reset weights, view aliases, manage thresholds | P2 | 8 | SM-UI1 | `templates/admin.html` (extend), `app/ui/api.py` |
| SM-T04 | — | Tests for Sprint 10: calibration, PSMA learning, dashboard API | P0 | 6 | all above | `tests/test_calibration.py` |

**Sprint 10 Total: 41 hours**

**Acceptance Criteria:**
- Calibrated confidence scores: if system says 0.90, actual accuracy is ~90%
- PSMA keywords auto-expand when new patterns detected in confirmed PSMA records
- Analytics dashboard shows: accuracy over time, learning curve, outcomes by carrier
- Admin panel allows: reset learned weights, view/edit name aliases, adjust min sample sizes
- Full regression: all existing tests pass + all new Sprint 7-10 tests pass

---

## 4. API ROUTES — New Endpoints for Smart Matching

| Method | Route | Sprint | Description |
|--------|-------|--------|-------------|
| POST | /api/match/confirm/\<id\> | S7 | Confirm match — stores outcome with component scores |
| POST | /api/match/reject/\<id\> | S7 | Reject match — stores outcome, removes match |
| POST | /api/match/reassign/\<id\> | S7 | Reassign to different billing record — stores outcome |
| GET | /api/smart/weights | S7 | View current learned weights (per carrier/modality) |
| POST | /api/smart/weights/reset | S7 | Reset learned weights to defaults |
| GET | /api/smart/aliases | S7 | View all name alias pairs |
| DELETE | /api/smart/aliases/\<id\> | S7 | Remove an incorrect name alias |
| GET | /api/smart/outcomes | S7 | View match outcome history (paginated) |
| POST | /api/denials/\<id\>/resolve | S8 | Resolve denial — stores recovery outcome |
| GET | /api/smart/recovery-rates | S8 | View learned recovery rates per carrier+reason |
| GET | /api/smart/payment-patterns | S8 | View learned payment patterns per carrier+modality |
| GET | /api/smart/denial-patterns | S8 | View detected recurring denial patterns |
| GET | /api/smart/cpt-map | S9 | View CPT→modality mappings (hardcoded + learned) |
| GET | /api/smart/normalization/pending | S9 | View unmapped values needing approval |
| POST | /api/smart/normalization/approve | S9 | Approve a normalization suggestion |
| GET | /api/smart/analytics | S10 | Learning analytics: accuracy trends, sample sizes |
| GET | /api/smart/dashboard | S10 | Smart matching dashboard data |

---

## 5. BUSINESS RULES — Smart Matching

| Rule | Description | Min Sample |
|------|-------------|------------|
| BR-SM-01 | Learned weights only activate after N confirmed outcomes for that carrier/modality | 50 |
| BR-SM-02 | Learned thresholds must maintain ≥95% precision (false accept rate <5%) | 50 |
| BR-SM-03 | Name aliases require 2+ independent confirmations before auto-applying | 2 |
| BR-SM-04 | Learned CPT→modality mappings require 3+ confirming matches | 3 |
| BR-SM-05 | Denial recovery rates require 10+ outcomes before replacing formula | 10 |
| BR-SM-06 | Normalization suggestions require explicit user approval | 1 |
| BR-SM-07 | Weight optimization runs after every 25 new outcomes (incremental) | 25 |
| BR-SM-08 | All learning is reversible — admin can reset any learned parameter to defaults | — |
| BR-SM-09 | Learned parameters stored locally in SQLite — never leaves the machine | — |
| BR-SM-10 | Date scoring curve extends to ±7 days (was ±2) with learned weights | 30 |

---

## 6. TECHNICAL APPROACH — How Learning Works

### Weight Optimization Algorithm (SM-01)
```
For each carrier/modality combination with 50+ outcomes:
  1. Collect all (name_score, date_score, modality_score, correct) tuples
  2. Use logistic regression to find weights that maximize:
     P(correct | w1*name + w2*date + w3*modality)
  3. Constrain: w1 + w2 + w3 = 1.0, all weights > 0.05
  4. Store if accuracy improves vs default weights on same data
  5. Fallback: carrier-level → modality-level → global → hardcoded defaults
```

### Threshold Optimization Algorithm (SM-02)
```
For each carrier with 50+ outcomes:
  1. Compute precision/recall at each threshold from 0.70 to 1.00
  2. Auto-accept threshold = lowest threshold with precision >= 0.95
  3. Review threshold = lowest threshold with precision >= 0.80
  4. Constrain: review_threshold >= 0.70, auto_accept >= review + 0.05
```

### Denial Recovery Learning (SM-03)
```
For each carrier + denial_reason pair with 10+ outcomes:
  1. Compute actual recovery_rate = sum(recovered) / sum(expected)
  2. Compute recovery_probability = count(recovered > 0) / count(all)
  3. New recoverability = expected * recovery_probability * recovery_rate * age_decay
  4. Age decay learned from actual data instead of fixed 1/365
```

### Name Alias Learning (SM-04)
```
On match confirm:
  1. If name_similarity < 0.95 AND match was confirmed:
     Store (normalize(name_a), normalize(name_b)) as candidate alias
  2. After 2+ independent confirmations of same pair:
     Add to active alias set
  3. On future matches: if alias pair found, name_similarity = 1.0
```

---

## 7. MIGRATION PATH — Backward Compatibility

All smart matching features are **additive** — the system works identically to current behavior until enough outcomes are collected:

1. **Default weights** (0.50/0.30/0.20) used until 50+ outcomes exist for a carrier
2. **Default thresholds** (0.95/0.80) used until 50+ outcomes exist
3. **Default CPT map** used; learned mappings supplement it, never replace
4. **Default recoverability formula** used until 10+ denial outcomes per carrier+reason
5. **Default normalization maps** always apply; learned maps add new entries only

No existing functionality is removed or changed. Smart features layer on top progressively.

---

## 8. SUCCESS METRICS

| Metric | Current Baseline | Sprint 7 Target | Sprint 10 Target |
|--------|-----------------|-----------------|-----------------|
| Auto-accept rate | ~60% of matches | 70% | 80% |
| False accept rate | Unknown | <5% | <3% |
| Manual review queue size | All 0.80-0.95 | Reduced 30% | Reduced 60% |
| Match accuracy (human-confirmed) | Unknown | Tracked | >95% |
| Denial recovery rate | Unknown | Tracked | Improved 20% |
| Average denial queue priority accuracy | Random | Tracked | Top-20 = highest-recovery items |
| Import column mapping failures | Manual | Reduced 50% | Reduced 80% |
| Unknown modality/carrier values | Silently passed through | Flagged | Auto-suggested |
