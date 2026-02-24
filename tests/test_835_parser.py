"""Tests for the X12 835 EDI parser."""

import unittest
from datetime import date
from app.parser.era_835_parser import parse_835


# ── Sample 835 EDI data ─────────────────────────────────────────
# Minimal but valid 835 transaction with one payment and two claims
SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240115*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20240115*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*I*1500.00*C*ACH*CCP*01*999999999*DA*123456789**01*888888888*DA*987654321*20240115~"
    "TRN*1*EFT12345*1234567890~"
    "N1*PR*MEDICARE OF CALIFORNIA~"
    "N1*PE*OCEAN DIAGNOSTIC RADIOLOGY~"
    "CLP*CLM001*1*800.00*700.00*100.00*MA~"
    "NM1*QC*1*SMITH*JOHN****MI*123456789~"
    "DTM*232*20240101~"
    "SVC*HC:70553*400.00*350.00~"
    "CAS*CO*45*50.00~"
    "SVC*HC:70551*400.00*350.00~"
    "CAS*PR*1*50.00~"
    "CLP*CLM002*4*500.00*0.00*0.00*MA~"
    "NM1*QC*1*JONES*MARY****MI*987654321~"
    "DTM*232*20240105~"
    "SVC*HC:74177*500.00*0.00~"
    "CAS*CO*16*500.00~"
    "SE*18*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)

# 835 with check payment (CHK)
SAMPLE_835_CHECK = (
    "ISA*00*          *00*          *ZZ*PAYER          *ZZ*PROVIDER       *250301*0930*^*00501*000000002*0*P*:~"
    "GS*HP*PAYER*PROVIDER*20250301*0930*2*X*005010X221A1~"
    "ST*835*0002~"
    "BPR*C*2500.50*C*CHK************20250301~"
    "TRN*1*CHK98765*9999999999~"
    "N1*PR*BLUE CROSS BLUE SHIELD~"
    "N1*PE*OCEAN DIAGNOSTIC RADIOLOGY~"
    "CLP*CLM100*1*2500.50*2500.50*0.00*BL~"
    "NM1*QC*1*NGUYEN*DAVID****MI*111222333~"
    "DTM*232*20250201~"
    "SVC*HC:72148*2500.50*2500.50~"
    "SE*10*0002~"
    "GE*1*2~"
    "IEA*1*000000002~"
)

# 835 with multiple CAS adjustments on one claim
SAMPLE_835_MULTI_CAS = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240601*0800*^*00501*000000003*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20240601*0800*3*X*005010X221A1~"
    "ST*835*0003~"
    "BPR*I*300.00*C*ACH*CCP*01*999999999*DA*123456789**01*888888888*DA*987654321*20240601~"
    "TRN*1*EFT99999*1234567890~"
    "N1*PR*CALOPTIMA~"
    "CLP*CLM200*1*750.00*300.00*450.00*HM~"
    "NM1*QC*1*PATEL*RAJESH****MI*444555666~"
    "DTM*232*20240515~"
    "SVC*HC:70553*750.00*300.00~"
    "CAS*CO*45*250.00~"
    "CAS*PR*2*200.00~"
    "SE*10*0003~"
    "GE*1*3~"
    "IEA*1*000000003~"
)


class TestParse835(unittest.TestCase):
    """Test X12 835 parser with realistic EDI data."""

    def test_parse_basic_835(self):
        result = parse_835(SAMPLE_835, filename="test_basic.835")

        self.assertEqual(result["filename"], "test_basic.835")
        self.assertEqual(result["errors"], [])

        # Payment info
        payment = result["payment"]
        self.assertEqual(payment["payment_method"], "ACH")
        self.assertEqual(payment["payment_amount"], 1500.00)
        self.assertEqual(payment["payment_date"], date(2024, 1, 15))
        self.assertEqual(payment["check_eft_number"], "EFT12345")
        self.assertEqual(payment["payer_name"], "MEDICARE OF CALIFORNIA")
        self.assertEqual(payment["payee_name"], "OCEAN DIAGNOSTIC RADIOLOGY")

        # Claims
        self.assertEqual(len(result["claims"]), 2)

    def test_claim_details(self):
        result = parse_835(SAMPLE_835)
        claims = result["claims"]

        # First claim — paid
        c1 = claims[0]
        self.assertEqual(c1["claim_id"], "CLM001")
        self.assertEqual(c1["claim_status"], "PROCESSED_PRIMARY")
        self.assertEqual(c1["billed_amount"], 800.00)
        self.assertEqual(c1["paid_amount"], 700.00)
        self.assertEqual(c1["patient_name"], "SMITH, JOHN")
        self.assertEqual(c1["service_date"], date(2024, 1, 1))

        # Service lines
        self.assertEqual(len(c1["service_lines"]), 2)
        self.assertEqual(c1["service_lines"][0]["cpt_code"], "70553")
        self.assertEqual(c1["service_lines"][0]["paid_amount"], 350.00)
        self.assertEqual(c1["service_lines"][1]["cpt_code"], "70551")

    def test_denied_claim(self):
        result = parse_835(SAMPLE_835)
        c2 = result["claims"][1]

        self.assertEqual(c2["claim_id"], "CLM002")
        self.assertEqual(c2["claim_status"], "DENIED")
        self.assertEqual(c2["billed_amount"], 500.00)
        self.assertEqual(c2["paid_amount"], 0.00)
        self.assertEqual(c2["patient_name"], "JONES, MARY")

        # CAS adjustment
        svc = c2["service_lines"][0]
        self.assertEqual(len(svc["adjustments"]), 1)
        self.assertEqual(svc["adjustments"][0]["group_code"], "CO")
        self.assertEqual(svc["adjustments"][0]["reason_code"], "16")
        self.assertEqual(svc["adjustments"][0]["amount"], 500.00)

    def test_check_payment(self):
        result = parse_835(SAMPLE_835_CHECK, filename="check.835")

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["payment"]["payment_method"], "CHK")
        self.assertEqual(result["payment"]["payment_amount"], 2500.50)
        self.assertEqual(result["payment"]["check_eft_number"], "CHK98765")
        self.assertEqual(result["payment"]["payer_name"], "BLUE CROSS BLUE SHIELD")

        self.assertEqual(len(result["claims"]), 1)
        claim = result["claims"][0]
        self.assertEqual(claim["paid_amount"], 2500.50)
        self.assertEqual(claim["patient_name"], "NGUYEN, DAVID")

    def test_multi_cas_adjustments(self):
        result = parse_835(SAMPLE_835_MULTI_CAS)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["claims"]), 1)

        claim = result["claims"][0]
        self.assertEqual(claim["billed_amount"], 750.00)
        self.assertEqual(claim["paid_amount"], 300.00)
        self.assertEqual(claim["patient_name"], "PATEL, RAJESH")

        # Two CAS segments attached to the service line
        svc = claim["service_lines"][0]
        self.assertEqual(len(svc["adjustments"]), 2)
        self.assertEqual(svc["adjustments"][0]["group_code"], "CO")
        self.assertEqual(svc["adjustments"][0]["reason_code"], "45")
        self.assertEqual(svc["adjustments"][0]["amount"], 250.00)
        self.assertEqual(svc["adjustments"][1]["group_code"], "PR")
        self.assertEqual(svc["adjustments"][1]["reason_code"], "2")
        self.assertEqual(svc["adjustments"][1]["amount"], 200.00)

    def test_envelope_metadata(self):
        result = parse_835(SAMPLE_835)
        env = result["envelope"]

        self.assertEqual(env["isa_sender"], "SENDER")
        self.assertEqual(env["isa_receiver"], "RECEIVER")
        self.assertEqual(env["st_code"], "835")
        self.assertEqual(env["gs_code"], "HP")

    def test_empty_input(self):
        result = parse_835("", filename="empty.835")
        self.assertIn("Empty file", result["errors"])
        self.assertEqual(len(result["claims"]), 0)

    def test_invalid_input(self):
        result = parse_835("This is not an EDI file at all.", filename="bad.txt")
        self.assertTrue(len(result["errors"]) > 0)

    def test_whitespace_and_newlines(self):
        """Parser should handle 835 files with line breaks between segments."""
        text_with_newlines = SAMPLE_835_CHECK.replace("~", "~\n")
        result = parse_835(text_with_newlines)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(result["payment"]["payment_amount"], 2500.50)


if __name__ == "__main__":
    unittest.main()
