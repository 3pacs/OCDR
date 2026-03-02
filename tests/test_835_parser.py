"""Tests for ocdr.era_835_parser."""

import pytest
from datetime import date
from decimal import Decimal

from ocdr.era_835_parser import parse_835_text, flatten_claims


# Synthetic 835 EDI content for testing
SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*SENDER    *ZZ*RECEIVER  "
    "*250101*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20250101*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*C*1250.00*C*ACH*CCP*01*111222333*DA*9876543*1234567890**01*222333444*DA*1234567*20250115~"
    "TRN*1*CHECK12345*1234567890~"
    "N1*PR*BLUE CROSS INSURANCE~"
    "N1*PE*OC DIAGNOSTIC RADIOLOGY*FI*123456789~"
    "CLP*CLAIM001*1*750.00*600.00*50.00*12*REFID001~"
    "NM1*QC*1*SMITH*JOHN****MI*12345~"
    "DTM*232*20250110~"
    "SVC*HC:70553*750.00*600.00**1~"
    "CAS*CO*45*150.00~"
    "CLP*CLAIM002*4*395.00*0.00*0.00*12*REFID002~"
    "NM1*QC*1*TORRES*JULIA****MI*67890~"
    "DTM*232*20250112~"
    "SVC*HC:74178*395.00*0.00**1~"
    "CAS*PR*1*395.00~"
    "SE*16*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


class TestParse835:
    def test_basic_parse(self):
        result = parse_835_text(SAMPLE_835, source_file="test.835")
        assert result["file"] == "test.835"
        assert len(result["claims"]) == 2

    def test_payment_info(self):
        result = parse_835_text(SAMPLE_835)
        assert result["payment"]["method"] == "C"
        assert result["payment"]["amount"] == Decimal("1250.00")
        assert result["payment"]["date"] == date(2025, 1, 15)

    def test_check_number(self):
        result = parse_835_text(SAMPLE_835)
        assert result["check_eft_number"] == "CHECK12345"

    def test_payer_name(self):
        result = parse_835_text(SAMPLE_835)
        # normalize_payer_code will uppercase
        assert "BLUE CROSS" in result["payer_name"]

    def test_claim_1_details(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][0]
        assert claim["claim_id"] == "CLAIM001"
        assert claim["claim_status"] == "PROCESSED_PRIMARY"
        assert claim["billed_amount"] == Decimal("750.00")
        assert claim["paid_amount"] == Decimal("600.00")

    def test_claim_1_patient(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][0]
        assert claim["patient_name"] == "SMITH, JOHN"

    def test_claim_1_service_date(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][0]
        assert claim["service_date"] == date(2025, 1, 10)

    def test_claim_1_service_line(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][0]
        assert len(claim["service_lines"]) == 1
        svc = claim["service_lines"][0]
        assert svc["cpt_code"] == "70553"
        assert svc["billed_amount"] == Decimal("750.00")
        assert svc["paid_amount"] == Decimal("600.00")

    def test_claim_1_adjustment(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][0]
        assert len(claim["adjustments"]) == 1
        adj = claim["adjustments"][0]
        assert adj["group_code"] == "CO"
        assert adj["group_name"] == "CONTRACTUAL"

    def test_denied_claim(self):
        result = parse_835_text(SAMPLE_835)
        claim = result["claims"][1]
        assert claim["claim_status"] == "DENIED"
        assert claim["paid_amount"] == Decimal("0.00")
        assert claim["patient_name"] == "TORRES, JULIA"

    def test_empty_input(self):
        result = parse_835_text("")
        assert result["claims"] == []

    def test_envelope(self):
        result = parse_835_text(SAMPLE_835)
        assert "isa" in result["envelope"]
        assert "gs" in result["envelope"]


class TestFlattenClaims:
    def test_flatten(self):
        parsed = [parse_835_text(SAMPLE_835)]
        flat = flatten_claims(parsed)
        assert len(flat) == 2
        # Each claim should have payment-level fields
        for claim in flat:
            assert "payer_name" in claim
            assert "check_eft_number" in claim
            assert "payment_date" in claim
            assert "cpt_codes" in claim

    def test_cpt_codes_extracted(self):
        parsed = [parse_835_text(SAMPLE_835)]
        flat = flatten_claims(parsed)
        assert flat[0]["cpt_codes"] == ["70553"]
        assert flat[1]["cpt_codes"] == ["74178"]
