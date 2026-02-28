"""
Template-based appeal letter generation from denial data.

Generates professional HTML appeal letters using billing record data,
with all user-supplied values escaped via markupsafe.escape() to prevent
XSS and injection issues.
"""

from datetime import date
from markupsafe import escape


APPEAL_TEMPLATES = {
    "CO-4": {
        "description": "inconsistent procedure code",
        "argument": (
            "The procedure code submitted accurately reflects the service rendered. "
            "The imaging study performed is consistent with the documented clinical "
            "indication and the CPT code assigned. We respectfully request that the "
            "claim be re-evaluated with consideration of the attached clinical "
            "documentation demonstrating medical necessity and procedural accuracy."
        ),
    },
    "CO-45": {
        "description": "charge exceeds fee schedule",
        "argument": (
            "The charge submitted is consistent with the contracted rate and the "
            "prevailing fee schedule for this service in our geographic area. We "
            "believe the adjudication applied an incorrect fee schedule or failed to "
            "account for applicable modifiers. Please review the enclosed fee "
            "schedule documentation and reprocess accordingly."
        ),
    },
    "CO-96": {
        "description": "non-covered charge",
        "argument": (
            "This service is a covered benefit under the patient's plan. The imaging "
            "study was ordered by the referring physician based on clinical findings "
            "that meet the plan's coverage criteria. Enclosed please find the "
            "relevant plan benefit documentation and clinical notes supporting "
            "medical necessity and coverage eligibility."
        ),
    },
    "CO-197": {
        "description": "missing precertification",
        "argument": (
            "Precertification was obtained prior to the date of service. The "
            "authorization reference number is included in the original claim "
            "submission. If the authorization was not located during adjudication, "
            "we have enclosed a copy of the authorization confirmation. We request "
            "that the claim be reprocessed with the attached documentation."
        ),
    },
    "CO-16": {
        "description": "missing information",
        "argument": (
            "All required information was included in the original claim submission. "
            "We have reviewed the claim and confirmed that all necessary fields, "
            "including patient demographics, provider identifiers, and clinical "
            "data, are present and accurate. Enclosed please find a corrected claim "
            "form with all fields clearly populated for your review."
        ),
    },
    "CO-29": {
        "description": "timely filing",
        "argument": (
            "The original claim was submitted within the contractually required "
            "filing period. Enclosed is proof of timely submission including the "
            "original submission confirmation, electronic acknowledgment receipt, "
            "and/or certified mail documentation. We respectfully request that "
            "the timely filing denial be overturned and the claim reprocessed."
        ),
    },
    "CO-50": {
        "description": "not medically necessary",
        "argument": (
            "The imaging study was medically necessary based on the patient's "
            "clinical presentation, symptoms, and the referring physician's "
            "clinical judgment. The enclosed medical records, physician notes, "
            "and relevant clinical guidelines demonstrate that the study met "
            "accepted standards of medical necessity. We request peer-to-peer "
            "review if further clinical discussion is required."
        ),
    },
}

# Default argument for denial codes not in the template map
_DEFAULT_ARGUMENT = (
    "We believe this claim was denied in error. The services rendered were "
    "medically necessary, properly coded, and submitted in accordance with "
    "all payer requirements. We respectfully request a full review of the "
    "enclosed documentation and reconsideration of this denial."
)


def generate_appeal_letter(billing_record_dict: dict, payer_info: dict = None) -> str:
    """Generate an HTML appeal letter from billing record data.

    Uses string templating with markupsafe.escape() on ALL user data
    to prevent injection attacks.

    Args:
        billing_record_dict: Dictionary from BillingRecord.to_dict() containing
            patient_name, service_date, scan_type, modality, denial_status,
            denial_reason_code, insurance_carrier, era_claim_id, total_payment,
            and other billing fields.
        payer_info: Optional dict with payer details:
            {"name": str, "address": str, "city_state_zip": str,
             "filing_deadline_days": int}

    Returns:
        HTML string containing the formatted appeal letter.
    """
    # Extract and escape all user-supplied data
    patient_name = escape(billing_record_dict.get("patient_name", ""))
    service_date_raw = billing_record_dict.get("service_date", "")
    service_date = escape(str(service_date_raw)) if service_date_raw else escape("N/A")
    scan_type = escape(billing_record_dict.get("scan_type", ""))
    modality = escape(billing_record_dict.get("modality", ""))
    denial_status = escape(billing_record_dict.get("denial_status", "") or "")
    denial_reason_code = billing_record_dict.get("denial_reason_code", "") or ""
    carrier = escape(billing_record_dict.get("insurance_carrier", ""))
    claim_id = escape(billing_record_dict.get("era_claim_id", "") or "N/A")
    total_payment = billing_record_dict.get("total_payment", 0.0) or 0.0
    patient_id = escape(str(billing_record_dict.get("patient_id", "") or ""))
    referring_doctor = escape(billing_record_dict.get("referring_doctor", "") or "")
    description = escape(billing_record_dict.get("description", "") or "")
    appeal_deadline_raw = billing_record_dict.get("appeal_deadline", "")
    appeal_deadline = escape(str(appeal_deadline_raw)) if appeal_deadline_raw else ""

    # Determine denial template
    template = APPEAL_TEMPLATES.get(denial_reason_code)
    if template:
        denial_description = escape(template["description"])
        appeal_argument = template["argument"]
    else:
        denial_description = escape(denial_reason_code or "unspecified reason")
        appeal_argument = _DEFAULT_ARGUMENT

    escaped_denial_code = escape(denial_reason_code or "N/A")

    # Payer info (escaped)
    if payer_info:
        payer_name = escape(payer_info.get("name", carrier))
        payer_address = escape(payer_info.get("address", ""))
        payer_city_state_zip = escape(payer_info.get("city_state_zip", ""))
    else:
        payer_name = carrier
        payer_address = ""
        payer_city_state_zip = ""

    today = date.today().strftime("%B %d, %Y")

    # Format payment as currency
    try:
        expected_payment = f"${float(total_payment):,.2f}"
    except (ValueError, TypeError):
        expected_payment = "$0.00"

    # Build the appeal deadline notice
    deadline_notice = ""
    if appeal_deadline:
        deadline_notice = (
            f'<p style="color: #c0392b; font-weight: bold;">'
            f"Appeal Deadline: {appeal_deadline}</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Appeal Letter - {patient_name} - {claim_id}</title>
    <style>
        body {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 12pt;
            line-height: 1.6;
            color: #222;
            max-width: 8.5in;
            margin: 0.75in auto;
            padding: 0 0.5in;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 16pt;
            margin: 0;
            color: #1a1a2e;
        }}
        .header p {{
            font-size: 10pt;
            margin: 2px 0;
            color: #555;
        }}
        .date-section {{
            text-align: right;
            margin-bottom: 20px;
        }}
        .payer-address {{
            margin-bottom: 20px;
        }}
        .re-line {{
            background-color: #f5f5f5;
            border-left: 4px solid #1a1a2e;
            padding: 10px 15px;
            margin-bottom: 20px;
            font-size: 11pt;
        }}
        .re-line strong {{
            display: inline-block;
            width: 140px;
        }}
        .body-text {{
            margin-bottom: 15px;
            text-align: justify;
        }}
        .signature-block {{
            margin-top: 40px;
        }}
        .signature-line {{
            border-top: 1px solid #333;
            width: 250px;
            margin-top: 50px;
            padding-top: 5px;
        }}
        .enclosures {{
            margin-top: 30px;
            font-size: 10pt;
            color: #555;
        }}
        .deadline-notice {{
            margin-bottom: 15px;
        }}
        @media print {{
            body {{ margin: 0; padding: 0.5in; }}
        }}
    </style>
</head>
<body>

    <!-- Practice Header -->
    <div class="header">
        <h1>[Practice Name]</h1>
        <p>[Practice Address Line 1]</p>
        <p>[City, State ZIP] | Phone: [Phone] | Fax: [Fax]</p>
        <p>Tax ID: [Tax ID] | NPI: [NPI Number]</p>
    </div>

    <!-- Date -->
    <div class="date-section">
        <p>{today}</p>
    </div>

    <!-- Payer Address -->
    <div class="payer-address">
        <p><strong>{payer_name}</strong></p>
        <p>Appeals and Grievances Department</p>
        {"<p>" + str(payer_address) + "</p>" if payer_address else ""}
        {"<p>" + str(payer_city_state_zip) + "</p>" if payer_city_state_zip else ""}
    </div>

    <!-- RE Line -->
    <div class="re-line">
        <p><strong>RE: Appeal of Claim Denial</strong></p>
        <p><strong>Patient Name:</strong> {patient_name}</p>
        {"<p><strong>Patient ID:</strong> " + str(patient_id) + "</p>" if patient_id else ""}
        <p><strong>Claim ID:</strong> {claim_id}</p>
        <p><strong>Date of Service:</strong> {service_date}</p>
        <p><strong>Service:</strong> {scan_type} ({modality})</p>
        {"<p><strong>Description:</strong> " + str(description) + "</p>" if description else ""}
        <p><strong>Denial Code:</strong> {escaped_denial_code} &mdash; {denial_description}</p>
        <p><strong>Expected Payment:</strong> {expected_payment}</p>
    </div>

    {deadline_notice}

    <!-- Body -->
    <div class="body-text">
        <p>Dear Appeals Review Committee,</p>
    </div>

    <div class="body-text">
        <p>
            I am writing to formally appeal the denial of the above-referenced claim
            for <strong>{patient_name}</strong>, date of service
            <strong>{service_date}</strong>. The claim was denied under reason code
            <strong>{escaped_denial_code}</strong> ({denial_description}).
        </p>
    </div>

    <div class="body-text">
        <p>
            The patient underwent a <strong>{scan_type}</strong> imaging study
            (modality: <strong>{modality}</strong>) as ordered by the referring
            physician{", <strong>" + str(referring_doctor) + "</strong>," if referring_doctor else ""}
            based on documented clinical necessity.
        </p>
    </div>

    <div class="body-text">
        <p>{appeal_argument}</p>
    </div>

    <div class="body-text">
        <p>
            Based on the foregoing, we respectfully request that {payer_name}
            reverse the denial of claim <strong>{claim_id}</strong> and reprocess
            the claim for payment in the amount of <strong>{expected_payment}</strong>.
        </p>
    </div>

    <div class="body-text">
        <p>
            Should you require any additional information or documentation to
            complete your review, please do not hesitate to contact our office.
            We appreciate your prompt attention to this matter.
        </p>
    </div>

    <!-- Signature Block -->
    <div class="signature-block">
        <p>Respectfully submitted,</p>
        <div class="signature-line">
            <p>[Authorized Representative Name]</p>
            <p>[Title]</p>
            <p>[Practice Name]</p>
            <p>Date: {today}</p>
        </div>
    </div>

    <!-- Enclosures -->
    <div class="enclosures">
        <p><strong>Enclosures:</strong></p>
        <ul>
            <li>Copy of original claim</li>
            <li>Explanation of Benefits (EOB) / Remittance Advice</li>
            <li>Relevant medical records and clinical documentation</li>
            <li>Referring physician order / prescription</li>
            <li>Applicable clinical guidelines or coverage criteria</li>
        </ul>
    </div>

</body>
</html>"""

    return html
