"""Tests for the Topaz export parser and crosswalk logic."""

from backend.app.parsing.topaz_export_parser import (
    parse_topaz_export,
    looks_like_topaz_export,
    _detect_format,
    _match_column_name,
    FIELD_PATTERNS,
)


# ─── Format detection ────────────────────────────────────────────────────

class TestFormatDetection:
    def test_pipe_delimited(self):
        content = "Chart Number|Topaz ID|Patient Name\n100|5001|SMITH, JOHN\n101|5002|DOE, JANE\n102|5003|JONES, BOB\n"
        assert _detect_format(content) == "pipe"

    def test_tab_delimited(self):
        content = "Chart Number\tTopaz ID\tPatient Name\n100\t5001\tSMITH, JOHN\n101\t5002\tDOE, JANE\n102\t5003\tJONES, BOB\n"
        assert _detect_format(content) == "tab"

    def test_csv(self):
        content = "Chart Number,Topaz ID,Patient Name,Date\n100,5001,SMITH JOHN,2024-01-01\n101,5002,DOE JANE,2024-01-02\n102,5003,JONES BOB,2024-01-03\n"
        assert _detect_format(content) == "csv"

    def test_xml(self):
        content = '<?xml version="1.0"?><Patients><Row><ChartNumber>100</ChartNumber><BillingId>5001</BillingId></Row></Patients>'
        assert _detect_format(content) == "xml"

    def test_xml_without_declaration(self):
        content = "<Patients><Row><ChartNumber>100</ChartNumber><BillingId>5001</BillingId></Row></Patients>"
        assert _detect_format(content) == "xml"


# ─── Column name matching ────────────────────────────────────────────────

class TestColumnMatching:
    def test_chart_number_aliases(self):
        assert _match_column_name("Chart Number", FIELD_PATTERNS) == "chart_number"
        assert _match_column_name("Patient ID", FIELD_PATTERNS) == "chart_number"
        assert _match_column_name("MRN", FIELD_PATTERNS) == "chart_number"
        assert _match_column_name("Account", FIELD_PATTERNS) == "chart_number"
        assert _match_column_name("Chart#", FIELD_PATTERNS) == "chart_number"

    def test_topaz_id_aliases(self):
        assert _match_column_name("Topaz ID", FIELD_PATTERNS) == "topaz_id"
        assert _match_column_name("Billing ID", FIELD_PATTERNS) == "topaz_id"
        assert _match_column_name("Claim ID", FIELD_PATTERNS) == "topaz_id"
        assert _match_column_name("Encounter ID", FIELD_PATTERNS) == "topaz_id"
        assert _match_column_name("Invoice", FIELD_PATTERNS) == "topaz_id"
        assert _match_column_name("Reference ID", FIELD_PATTERNS) == "topaz_id"

    def test_patient_name(self):
        assert _match_column_name("Patient Name", FIELD_PATTERNS) == "patient_name"
        assert _match_column_name("Patient", FIELD_PATTERNS) == "patient_name"

    def test_service_date(self):
        assert _match_column_name("Service Date", FIELD_PATTERNS) == "service_date"
        assert _match_column_name("DOS", FIELD_PATTERNS) == "service_date"


# ─── Pipe-delimited parsing ─────────────────────────────────────────────

SAMPLE_PIPE = """Chart Number|Billing ID|Patient Name|Service Date|Notes
100|5001|SMITH, JOHN|2024-01-15|MRI lumbar
101|5002|DOE, JANE|2024-01-16|CT abdomen
102|5003|JONES, BOB|2024-01-17|PET scan
103|5004|WILLIAMS, ALICE|2024-01-18|Bone density
"""


class TestPipeDelimited:
    def test_basic_parse(self):
        result = parse_topaz_export(SAMPLE_PIPE, "test_export")
        assert result.format_detected == "pipe"
        assert result.total_rows == 4

    def test_crosswalk_pairs(self):
        result = parse_topaz_export(SAMPLE_PIPE, "test_export")
        assert len(result.crosswalk_pairs) == 4
        pair = result.crosswalk_pairs[0]
        assert pair["chart_number"] == "100"
        assert pair["topaz_id"] == "5001"
        assert pair["patient_name"] == "SMITH, JOHN"

    def test_column_mapping(self):
        result = parse_topaz_export(SAMPLE_PIPE, "test_export")
        assert "chart_number" in result.column_mapping
        assert "topaz_id" in result.column_mapping
        assert "patient_name" in result.column_mapping

    def test_extra_fields(self):
        result = parse_topaz_export(SAMPLE_PIPE, "test_export")
        assert "Notes" in result.extra_fields

    def test_no_warnings(self):
        result = parse_topaz_export(SAMPLE_PIPE, "test_export")
        assert len(result.warnings) == 0


# ─── Tab-delimited parsing ──────────────────────────────────────────────

SAMPLE_TAB = "Account\tClaim Number\tPatient\tDate\n200\t6001\tSMITH JOHN\t01/15/2024\n201\t6002\tDOE JANE\t01/16/2024\n202\t6003\tJONES BOB\t01/17/2024\n"


class TestTabDelimited:
    def test_basic_parse(self):
        result = parse_topaz_export(SAMPLE_TAB, "tab_export")
        assert result.format_detected == "tab"
        assert result.total_rows == 3

    def test_crosswalk_extraction(self):
        result = parse_topaz_export(SAMPLE_TAB, "tab_export")
        pair = result.crosswalk_pairs[0]
        assert pair["chart_number"] == "200"
        assert pair["topaz_id"] == "6001"


# ─── CSV parsing ─────────────────────────────────────────────────────────

SAMPLE_CSV = """PatientID,InvoiceID,Name,DOS,Amount
300,7001,SMITH JOHN,2024-01-15,500.00
301,7002,DOE JANE,2024-01-16,750.00
302,7003,JONES BOB,2024-01-17,1200.00
"""


class TestCSV:
    def test_basic_parse(self):
        result = parse_topaz_export(SAMPLE_CSV, "csv_export")
        assert result.format_detected == "csv"
        assert result.total_rows == 3

    def test_id_field_detection(self):
        result = parse_topaz_export(SAMPLE_CSV, "csv_export")
        assert result.crosswalk_pairs[0]["chart_number"] == "300"
        assert result.crosswalk_pairs[0]["topaz_id"] == "7001"


# ─── XML parsing ─────────────────────────────────────────────────────────

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<PatientData>
  <Patient>
    <ChartNumber>400</ChartNumber>
    <BillingId>8001</BillingId>
    <PatientName>SMITH, JOHN</PatientName>
    <ServiceDate>2024-01-15</ServiceDate>
  </Patient>
  <Patient>
    <ChartNumber>401</ChartNumber>
    <BillingId>8002</BillingId>
    <PatientName>DOE, JANE</PatientName>
    <ServiceDate>2024-01-16</ServiceDate>
  </Patient>
</PatientData>
"""


class TestXML:
    def test_basic_parse(self):
        result = parse_topaz_export(SAMPLE_XML, "xml_export")
        assert result.format_detected == "xml"
        assert result.total_rows == 2

    def test_crosswalk_pairs(self):
        result = parse_topaz_export(SAMPLE_XML, "xml_export")
        pair = result.crosswalk_pairs[0]
        assert pair["chart_number"] == "400"
        assert pair["topaz_id"] == "8001"
        assert pair["patient_name"] == "SMITH, JOHN"


# ─── Content sniffing ────────────────────────────────────────────────────

class TestContentSniffing:
    def test_looks_like_topaz_billing_data(self):
        assert looks_like_topaz_export("Chart Number|Billing ID|Patient\n100|5001|SMITH")
        assert looks_like_topaz_export("Account,Claim ID,Name\n200,6001,DOE")

    def test_does_not_match_x12(self):
        x12 = "ISA*00*          *00*          *ZZ*SENDER~BPR*C*1500*~"
        # X12 files don't have "chart" or "billing id" headers
        assert not looks_like_topaz_export(x12)

    def test_does_not_match_random_text(self):
        assert not looks_like_topaz_export("Hello world, this is just random text.")
        assert not looks_like_topaz_export("")

    def test_matches_with_id_columns(self):
        assert looks_like_topaz_export("Patient Name|Account Number|Status\n12345|SMITH|Active\n")


# ─── Edge cases ──────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_content(self):
        result = parse_topaz_export("", "empty")
        assert result.total_rows == 0

    def test_header_only(self):
        result = parse_topaz_export("Chart|Billing ID|Name\n", "header_only")
        assert result.total_rows == 0

    def test_partial_crosswalk_topaz_only(self):
        """File with topaz_id but no chart_number column."""
        content = "Claim ID|Patient Name|Date\n9001|SMITH JOHN|2024-01-15\n9002|DOE JANE|2024-01-16\n"
        result = parse_topaz_export(content, "topaz_only")
        assert result.total_rows == 2
        assert result.crosswalk_pairs[0]["topaz_id"] == "9001"

    def test_partial_crosswalk_chart_only(self):
        """File with chart_number but no topaz_id column."""
        content = "Chart Number|Patient Name|Date\n500|SMITH JOHN|2024-01-15\n501|DOE JANE|2024-01-16\n"
        result = parse_topaz_export(content, "chart_only")
        assert result.total_rows == 2
        assert result.crosswalk_pairs[0]["chart_number"] == "500"

    def test_mixed_empty_values(self):
        """Rows with some empty crosswalk fields should still be captured if at least one ID exists."""
        content = "Chart|Billing ID|Name\n100|5001|SMITH\n||DOE\n102||JONES\n"
        result = parse_topaz_export(content, "mixed")
        # Row 2 has no IDs, should be skipped. Row 3 has chart only.
        assert result.total_rows == 2

    def test_quoted_csv(self):
        content = '"Chart Number","Billing ID","Patient Name"\n"100","5001","SMITH, JOHN"\n"101","5002","DOE, JANE"\n'
        result = parse_topaz_export(content, "quoted.csv")
        assert result.total_rows == 2
        pair = result.crosswalk_pairs[0]
        assert pair["chart_number"] == "100"
        assert pair["topaz_id"] == "5001"
