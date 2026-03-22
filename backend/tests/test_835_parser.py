"""Tests for the X12 835 ERA parser (F-02)."""

from backend.app.parsing.x12_835_parser import parse_835_content


SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *230101*1200*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20230101*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*C*1500.00*C*ACH*CTX*01*999999999*DA*123456789*1234567890**01*999999999*DA*987654321*20230115~"
    "TRN*1*12345678*1234567890~"
    "N1*PR*MEDICARE OF CALIFORNIA~"
    "CLP*CLM001*1*2000.00*800.00*0*MC*11111111~"
    "NM1*QC*1*SMITH*JOHN****MI*123456789A~"
    "SVC*HC:74177*1000.00*400.00~"
    "CAS*CO*45*200.00~"
    "DTM*232*20230101~"
    "CLP*CLM002*4*1500.00*0.00*0*MC*22222222~"
    "NM1*QC*1*DOE*JANE****MI*987654321B~"
    "SVC*HC:78816*1500.00*0.00~"
    "CAS*CO*4*1500.00~"
    "DTM*232*20230105~"
    "SE*15*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


def test_parse_payment_info():
    result = parse_835_content(SAMPLE_835, "test.835")
    payment = result["payment"]

    assert payment["filename"] == "test.835"
    assert payment["payment_amount"] == 1500.00
    assert payment["payment_method"] == "C"
    assert payment["check_eft_number"] == "12345678"
    assert payment["payer_name"] == "MEDICARE OF CALIFORNIA"
    assert payment["payment_date"] is not None
    assert payment["payment_date"].year == 2023
    assert payment["payment_date"].month == 1
    assert payment["payment_date"].day == 15


def test_parse_claims():
    result = parse_835_content(SAMPLE_835, "test.835")
    claims = result["claims"]

    assert len(claims) == 2

    # First claim - paid
    c1 = claims[0]
    assert c1["claim_id"] == "CLM001"
    assert c1["claim_status"] == "1"  # processed primary
    assert c1["billed_amount"] == 2000.00
    assert c1["paid_amount"] == 800.00
    assert c1["patient_name_835"] == "SMITH, JOHN"
    assert c1["cpt_code"] == "74177"
    assert c1["cas_group_code"] == "CO"
    assert c1["cas_reason_code"] == "45"
    assert c1["cas_adjustment_amount"] == 200.00
    assert c1["service_date_835"] is not None

    # Second claim - denied
    c2 = claims[1]
    assert c2["claim_id"] == "CLM002"
    assert c2["claim_status"] == "4"  # denied
    assert c2["paid_amount"] == 0.00
    assert c2["patient_name_835"] == "DOE, JANE"
    assert c2["cas_reason_code"] == "4"  # not covered


def test_empty_content():
    result = parse_835_content("", "empty.835")
    assert result["claims"] == []
    assert result["payment"]["payment_amount"] is None


def test_minimal_content():
    minimal = "BPR*C*100.00~TRN*1*CHK999~CLP*C1*1*500*100~"
    result = parse_835_content(minimal, "minimal.835")
    assert result["payment"]["payment_amount"] == 100.00
    assert result["payment"]["check_eft_number"] == "CHK999"
    assert len(result["claims"]) == 1
    assert result["claims"][0]["claim_id"] == "C1"
