"""Denial action suggestions and fix recommendations.

Given a CARC code and claim context, recommends specific actions:
  - RESUBMIT: claim can be corrected and resubmitted
  - APPEAL: denial is contestable with supporting documentation
  - WRITE_OFF: contractual obligation, likely non-recoverable
  - PATIENT_BILL: patient responsibility (deductible, copay, coinsurance)
  - CORRECT_AND_RESUBMIT: specific data fix needed before resubmission
  - FOLLOW_UP: contact payer for more information
"""

from backend.app.analytics.public_code_tables import CARC_CODES


# Maps CARC code ranges to action categories with specific guidance
CARC_ACTION_MAP: dict[str, dict] = {
    # --- Patient responsibility (generally not appealable) ---
    "1": {
        "action": "PATIENT_BILL",
        "fix": "Bill patient for deductible amount.",
        "severity": "low",
        "recoverable": True,
    },
    "2": {
        "action": "PATIENT_BILL",
        "fix": "Bill patient for coinsurance amount.",
        "severity": "low",
        "recoverable": True,
    },
    "3": {
        "action": "PATIENT_BILL",
        "fix": "Bill patient for co-payment amount.",
        "severity": "low",
        "recoverable": True,
    },
    # --- Coding/modifier issues (fixable, resubmit) ---
    "4": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Review procedure code and modifier combination. Correct the modifier to match the procedure and resubmit.",
        "severity": "medium",
        "recoverable": True,
    },
    "5": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Procedure code or bill type doesn't match place of service. Verify POS code and resubmit.",
        "severity": "medium",
        "recoverable": True,
    },
    "6": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Patient age doesn't match procedure. Verify DOB on file and resubmit with correct demographics.",
        "severity": "medium",
        "recoverable": True,
    },
    "7": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Patient gender doesn't match procedure. Verify gender on file and resubmit.",
        "severity": "medium",
        "recoverable": True,
    },
    "8": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Procedure doesn't match provider type/specialty. Verify rendering provider NPI and taxonomy code.",
        "severity": "medium",
        "recoverable": True,
    },
    "9": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Diagnosis inconsistent with patient age. Verify ICD-10 code and patient DOB.",
        "severity": "medium",
        "recoverable": True,
    },
    "10": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Diagnosis inconsistent with patient gender. Verify ICD-10 code and patient demographics.",
        "severity": "medium",
        "recoverable": True,
    },
    "11": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Diagnosis doesn't support the procedure. Review medical necessity and update ICD-10 to support the imaging study.",
        "severity": "high",
        "recoverable": True,
    },
    # --- Authorization issues ---
    "15": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Prior authorization number missing or invalid. Obtain auth number from referring provider and resubmit.",
        "severity": "high",
        "recoverable": True,
    },
    # --- Information/submission errors ---
    "16": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Claim has submission/billing errors. Review claim form for missing fields (NPI, taxonomy, POS, modifiers) and resubmit corrected claim.",
        "severity": "high",
        "recoverable": True,
    },
    "17": {
        "action": "FOLLOW_UP",
        "fix": "Payer requesting additional information. Contact payer to determine what's needed, then submit requested documentation.",
        "severity": "medium",
        "recoverable": True,
    },
    # --- Duplicate ---
    "18": {
        "action": "WRITE_OFF",
        "fix": "Exact duplicate claim. Verify the original claim was paid. If different service, appeal with documentation showing distinct encounters.",
        "severity": "low",
        "recoverable": False,
    },
    # --- Coordination of benefits ---
    "22": {
        "action": "FOLLOW_UP",
        "fix": "May be covered by another payer (COB). Verify primary/secondary insurance order and submit to correct payer first.",
        "severity": "medium",
        "recoverable": True,
    },
    "23": {
        "action": "FOLLOW_UP",
        "fix": "Adjustment due to prior payer adjudication. Verify EOB from primary payer and submit with primary payment info.",
        "severity": "medium",
        "recoverable": True,
    },
    # --- Eligibility issues ---
    "26": {
        "action": "FOLLOW_UP",
        "fix": "Service date before coverage start. Verify patient eligibility dates. If incorrect, appeal with proof of coverage.",
        "severity": "high",
        "recoverable": True,
    },
    "27": {
        "action": "PATIENT_BILL",
        "fix": "Service date after coverage ended. Verify termination date. Bill patient or check for other active coverage.",
        "severity": "high",
        "recoverable": False,
    },
    "29": {
        "action": "APPEAL",
        "fix": "Filing deadline expired. If within appeal window, submit appeal with proof of timely filing (original submission date).",
        "severity": "critical",
        "recoverable": True,
    },
    "31": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Patient not identified as insured. Verify subscriber ID and patient relationship to subscriber. Resubmit with correct info.",
        "severity": "high",
        "recoverable": True,
    },
    # --- Contractual (generally write-off) ---
    "42": {
        "action": "WRITE_OFF",
        "fix": "Charges exceed fee schedule. This is a contractual adjustment — typically write off the difference.",
        "severity": "low",
        "recoverable": False,
    },
    "45": {
        "action": "WRITE_OFF",
        "fix": "Contractual fee schedule adjustment. Write off per contract terms.",
        "severity": "low",
        "recoverable": False,
    },
    # --- Medical necessity ---
    "50": {
        "action": "APPEAL",
        "fix": "Denied as not medically necessary. Appeal with clinical notes, referring physician's order, and medical necessity documentation.",
        "severity": "critical",
        "recoverable": True,
    },
    "51": {
        "action": "APPEAL",
        "fix": "Predetermination: not medically necessary. Submit appeal with clinical documentation supporting the imaging study.",
        "severity": "critical",
        "recoverable": True,
    },
    "52": {
        "action": "APPEAL",
        "fix": "Review organization denied medical necessity. Escalate appeal with peer-to-peer review request and clinical evidence.",
        "severity": "critical",
        "recoverable": True,
    },
    # --- Level of service ---
    "57": {
        "action": "APPEAL",
        "fix": "Level of service not supported. Appeal with documentation justifying the level of imaging performed.",
        "severity": "high",
        "recoverable": True,
    },
    "58": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Invalid place of service. Verify POS code matches where imaging was performed and resubmit.",
        "severity": "medium",
        "recoverable": True,
    },
    "59": {
        "action": "WRITE_OFF",
        "fix": "Multiple/concurrent procedure reduction. Review if bundling rules apply. If incorrect bundling, appeal with modifier 59.",
        "severity": "medium",
        "recoverable": True,
    },
    # --- Common high-frequency codes ---
    "96": {
        "action": "FOLLOW_UP",
        "fix": "Non-covered charge(s). Verify procedure is a covered benefit. If covered, appeal with plan documentation.",
        "severity": "high",
        "recoverable": True,
    },
    "97": {
        "action": "APPEAL",
        "fix": "Payment adjusted based on benefit not provided in this plan. Verify patient's specific plan benefits and appeal if imaging is covered.",
        "severity": "high",
        "recoverable": True,
    },
    "109": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Claim not covered by this payer. Verify insurance is active and correct payer ID. Resubmit to correct payer.",
        "severity": "high",
        "recoverable": True,
    },
    "197": {
        "action": "APPEAL",
        "fix": "Precertification/authorization/notification absent. Obtain retroactive auth if possible, or appeal with proof of emergency/medical necessity.",
        "severity": "critical",
        "recoverable": True,
    },
    "204": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Service/equipment/drug not covered by this payer. Verify payer and plan, resubmit to correct insurance.",
        "severity": "high",
        "recoverable": True,
    },
    "242": {
        "action": "CORRECT_AND_RESUBMIT",
        "fix": "Services not provided by network/primary care provider. Verify provider participation status and resubmit.",
        "severity": "high",
        "recoverable": True,
    },
}

# Default action for unmapped CARC codes
_DEFAULT_ACTION = {
    "action": "FOLLOW_UP",
    "fix": "Contact payer for specific denial details and determine appropriate corrective action.",
    "severity": "medium",
    "recoverable": True,
}

# CAS group code context
CAS_GROUP_CONTEXT = {
    "CO": {
        "label": "Contractual Obligation",
        "meaning": "Provider contractual write-off. Generally non-recoverable from patient.",
        "patient_billable": False,
    },
    "PR": {
        "label": "Patient Responsibility",
        "meaning": "Patient owes this amount (deductible, copay, coinsurance).",
        "patient_billable": True,
    },
    "OA": {
        "label": "Other Adjustment",
        "meaning": "Adjustment that is not contractual or patient responsibility. Investigate further.",
        "patient_billable": False,
    },
    "PI": {
        "label": "Payer Initiated Reduction",
        "meaning": "Payer reduced payment. May be appealable if applied incorrectly.",
        "patient_billable": False,
    },
    "CR": {
        "label": "Correction/Reversal",
        "meaning": "Correction to a previous claim. Verify original claim status.",
        "patient_billable": False,
    },
}


def get_denial_detail(
    carc_code: str | None,
    cas_group: str | None = None,
    billed_amount: float = 0,
    paid_amount: float = 0,
    adjustment_amount: float = 0,
    days_old: int = 0,
    carrier: str | None = None,
) -> dict:
    """
    Generate actionable denial detail with fix suggestions.

    Returns a structured response with:
    - CARC code description
    - CAS group context
    - Recommended action (RESUBMIT, APPEAL, WRITE_OFF, etc.)
    - Specific fix instructions
    - Severity and recoverability assessment
    - Priority score
    """
    # CARC info
    carc_desc = CARC_CODES.get(str(carc_code), "Unknown adjustment reason") if carc_code else None
    action_info = CARC_ACTION_MAP.get(str(carc_code), _DEFAULT_ACTION) if carc_code else _DEFAULT_ACTION

    # CAS group info
    group_info = CAS_GROUP_CONTEXT.get(cas_group) if cas_group else None

    # Override action if CAS group indicates patient responsibility
    if cas_group == "PR" and action_info["action"] not in ("PATIENT_BILL",):
        action_info = {
            **action_info,
            "action": "PATIENT_BILL",
            "fix": f"Patient responsibility ({carc_desc or 'adjustment'}). Bill patient for the adjustment amount.",
        }
    elif cas_group == "CO" and action_info["action"] in ("APPEAL", "FOLLOW_UP"):
        # Contractual obligations are generally write-offs
        action_info = {
            **action_info,
            "action": "WRITE_OFF",
            "fix": f"Contractual adjustment: {carc_desc or 'per contract'}. Write off per provider agreement.",
            "recoverable": False,
        }

    # Priority score (higher = more urgent)
    priority = 0
    if action_info.get("recoverable"):
        priority += 50
    if action_info.get("severity") == "critical":
        priority += 40
    elif action_info.get("severity") == "high":
        priority += 30
    elif action_info.get("severity") == "medium":
        priority += 20
    else:
        priority += 10
    # Urgency from amount
    if billed_amount > 1000:
        priority += 20
    elif billed_amount > 500:
        priority += 10
    # Urgency from age
    if days_old > 300:
        priority -= 20  # Very old, lower priority
    elif days_old > 150:
        priority -= 10

    return {
        "carc_code": carc_code,
        "carc_description": carc_desc,
        "cas_group_code": cas_group,
        "cas_group_info": group_info,
        "recommended_action": action_info["action"],
        "fix_instructions": action_info["fix"],
        "severity": action_info.get("severity", "medium"),
        "recoverable": action_info.get("recoverable", True),
        "priority_score": priority,
        "financial_context": {
            "billed_amount": billed_amount,
            "paid_amount": paid_amount,
            "adjustment_amount": adjustment_amount,
            "potential_recovery": billed_amount - paid_amount if action_info.get("recoverable") else 0,
        },
    }
