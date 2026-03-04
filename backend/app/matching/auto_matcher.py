"""
5-Pass Auto-Matching Engine (Phase 1).

Matches manual_billing records (chart_number) against era_claims + billing_software (topaz_id):
- Pass 1: Exact composite (name + DOB + DOS + amount) → confidence 99
- Pass 2: Strong fuzzy (name ≥95% + DOB + DOS + CPT) → confidence 95
- Pass 3: Medium fuzzy (name ≥90% + DOS + modality) → confidence 85
- Pass 4: Weak fuzzy (name ≥85% + DOS ±3 days) → confidence 70
- Pass 5: Amount-anchored (carrier + DOS + amount match) → confidence 75

TODO: Step 5 - Full implementation
"""
