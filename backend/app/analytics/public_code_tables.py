"""Public standard code tables for medical billing validation.

All data here comes from publicly available industry standards:
  - CARC (Claim Adjustment Reason Codes): X12/WPC maintained, updated ~3x/year
  - RARC (Remittance Advice Remark Codes): CMS/WPC maintained
  - X12 835 Claim Status Codes: ASC X12 standard
  - BPR Payment Method Codes: ASC X12 standard
  - CPT/HCPCS: CMS-published radiology code ranges
  - CAS Group Codes: ASC X12 standard

Sources:
  - https://www.wpc-edi.com/reference/ (CARC/RARC)
  - https://x12.org/codes (X12 code sets)
  - https://www.cms.gov/Medicare/Coding (CPT/HCPCS)
"""


# ============================================================
# CLAIM ADJUSTMENT REASON CODES (CARC)
# Full set from WPC/X12 — codes 1-300+
# Each maps to a short description for analytics/reporting
# ============================================================

CARC_CODES: dict[str, str] = {
    "1": "Deductible amount",
    "2": "Coinsurance amount",
    "3": "Co-payment amount",
    "4": "The procedure code is inconsistent with the modifier used",
    "5": "The procedure code/bill type is inconsistent with the place of service",
    "6": "The procedure/revenue code is inconsistent with the patient's age",
    "7": "The procedure/revenue code is inconsistent with the patient's gender",
    "8": "The procedure code is inconsistent with the provider type/specialty",
    "9": "The diagnosis is inconsistent with the patient's age",
    "10": "The diagnosis is inconsistent with the patient's gender",
    "11": "The diagnosis is inconsistent with the procedure",
    "12": "The diagnosis is inconsistent with the provider type",
    "13": "The date of death precedes the date of service",
    "14": "The date of birth follows the date of service",
    "15": "The authorization number is missing, invalid, or does not apply",
    "16": "Claim/service lacks information or has submission/billing error(s)",
    "17": "Requested information was not provided or was insufficient/incomplete",
    "18": "Exact duplicate claim/service",
    "19": "This is a work-related injury/illness and thus the liability of the Worker's Compensation carrier",
    "20": "This injury/illness is covered by the liability carrier",
    "21": "This injury/illness is the liability of the no-fault carrier",
    "22": "This care may be covered by another payer per coordination of benefits",
    "23": "The impact of prior payer(s) adjudication including payments and/or adjustments",
    "24": "Charges are covered under a capitation agreement/managed care plan",
    "25": "Payment for this claim/service adjusted because a Legislatively Mandated or Regulatory requirement was not met",
    "26": "Expenses incurred prior to coverage",
    "27": "Expenses incurred after coverage terminated",
    "28": "Coverage not in effect at the time the service was provided",
    "29": "The time limit for filing has expired",
    "30": "Payment adjusted because the patient has not met the required eligibility requirements",
    "31": "Patient cannot be identified as our insured",
    "32": "Our records indicate that this dependent is not an eligible dependent as defined",
    "33": "Insured has no dependent coverage",
    "34": "Insured has no coverage for newborns",
    "35": "Lifetime benefit maximum has been reached",
    "36": "Balance does not exceed co-payment amount",
    "37": "Balance does not exceed deductible",
    "38": "Services not provided or authorized by designated provider",
    "39": "Services denied at the time authorization/pre-certification was requested",
    "40": "Charges do not meet qualifications for emergent/urgent care",
    "42": "Charges exceed our fee schedule or maximum allowable amount",
    "43": "Gramm-Rudman-Hollings reduction",
    "44": "Prompt-payment discount",
    "45": "Charge exceeds fee schedule/maximum allowable or contracted/legislated fee arrangement",
    "49": "Non-Covered Service because it is a routine/preventive exam",
    "50": "Non-covered service because not deemed a medical necessity by the payer",
    "51": "Non-covered service because not deemed a medical necessity by the payer - predetermination",
    "52": "Non-covered service because not deemed a medical necessity by the payer - review organization",
    "53": "Services by an unauthorized provider",
    "54": "Multiple physicians/assistants are not covered in this case",
    "55": "Procedure/treatment/drug is deemed experimental/investigational by the payer",
    "56": "Procedure/treatment has not been deemed 'proven to be effective' by the payer",
    "57": "Payment denied/reduced because the payer deems the information submitted does not support this level of service",
    "58": "Treatment was deemed by the payer to have been rendered in an inappropriate or invalid place of service",
    "59": "Processed based on multiple or concurrent procedure rules",
    "60": "Charge not covered - Loss of eligibility during/after the authorized service period",
    "61": "Adjusted for failure to obtain proper pre-authorization/certification/notification",
    "62": "Payment denied/adjusted because expenses not incurred during authorized length of stay",
    "66": "Blood Deductible",
    "69": "Day outlier amount",
    "70": "Cost outlier - Loss in excess of loss threshold",
    "74": "Indirect Medical Education Adjustment",
    "75": "Direct Medical Education Adjustment",
    "76": "Disproportionate Share Adjustment",
    "78": "Non-covered days/room charge adjustment",
    "85": "Patient Interest Adjustment",
    "87": "Transfer amount",
    "89": "Professional fees removed from DRG",
    "90": "Ingredient cost adjustment",
    "91": "Dispensing fee adjustment",
    "94": "Processed in excess of charges",
    "95": "Plan procedures not followed",
    "96": "Non-covered charge(s)",
    "97": "The benefit for this service is included in the payment/allowance for another service/procedure",
    "100": "Payment made to patient/insured/responsible party/employer",
    "101": "Predetermination: anticipated payment upon completion of services",
    "102": "Major Medical Adjustment",
    "103": "Provider promotional discount",
    "104": "Managed care withholding",
    "105": "Tax withholding",
    "106": "Patient payment option/election not in effect",
    "107": "The related or qualifying claim/service was not identified on this claim",
    "108": "Rent/purchase guidelines were not met",
    "109": "Claim/service not covered by this payer/contractor",
    "110": "Billing date predates service date",
    "111": "Not covered unless the provider accepts assignment",
    "112": "Service not furnished directly to the patient and/or not documented",
    "114": "Procedure/product not approved by the Food and Drug Administration",
    "115": "Procedure postponed or canceled",
    "116": "The advance indemnification notice signed by the patient did not comply with requirements",
    "117": "Transportation is only covered to the closest facility",
    "118": "ESRD network  support adjustment",
    "119": "Benefit maximum for this time period or occurrence has been reached",
    "120": "Patient is covered by a managed care plan",
    "121": "Indemnification adjustment - Loss allocated to responsible party",
    "122": "Psychiatric reduction",
    "125": "Submission/billing error(s). At least one Remark Code must be provided",
    "128": "Newborn's services are covered in the mother's Allowance",
    "129": "Prior processing information appears incorrect",
    "130": "Claim submission fee",
    "131": "Claim specific negotiated discount",
    "132": "Prearranged demonstration project adjustment",
    "133": "The disposition of this claim/service is pending further review",
    "134": "Technical fees removed from DRG",
    "135": "Interim bill adjustment",
    "136": "Failure to follow prior payer's coverage rules",
    "137": "Regulatory Surcharges, Assessments, Allowances or Health Related Tax",
    "138": "Appeal procedures not followed or time limits not met",
    "139": "Contracted funding agreement - Loss of interest adjustment",
    "140": "Patient/Insured health identification number and name do not match",
    "141": "Claim spans eligible and ineligible periods of coverage, this is the reduction for the ineligible period",
    "142": "Monthly Medicaid patient liability amount",
    "143": "Portion of payment deferred",
    "144": "Incentive adjustment",
    "146": "Diagnosis was invalid for the date(s) of service reported",
    "147": "Provider contracted/negotiated rate expired or not on file",
    "148": "Information from another provider was not provided or was insufficient/incomplete",
    "149": "Lifetime benefit maximum has been reached for this service/benefit category",
    "150": "Payer deems the information submitted does not support this level of service",
    "151": "Payment adjusted because the payer deems the information submitted does not support this many/frequency of services",
    "152": "Payer deems the information submitted does not support this length of service",
    "153": "Payer deems the information submitted does not support this dosage",
    "154": "Payer deems the information submitted does not support this day's supply",
    "155": "Patient refused the service/procedure",
    "157": "Service/procedure was provided as a result of an act of war",
    "158": "Service/procedure was provided outside of the United States",
    "159": "Service/procedure was provided as a result of terrorism",
    "160": "Injury/illness was the result of an activity that is a benefit exclusion",
    "161": "Provider performance bonus",
    "162": "State-mandated Requirement for Property and Casualty",
    "163": "Attachment/other documentation referenced on the claim was not received",
    "164": "Attachment/other documentation referenced on the claim was not received in a timely fashion",
    "165": "Referral absent or exceeded",
    "166": "These services were submitted after this payer's responsibility for processing",
    "167": "This (these) diagnosis(es) is (are) not covered",
    "169": "Alternate benefit has been provided",
    "170": "Payment is denied when performed/billed by this type of provider",
    "171": "Payment is denied when performed/billed by this type of provider in this type of facility",
    "172": "Payment is adjusted when performed/billed by a provider of this specialty",
    "173": "Service/equipment was not prescribed by a physician",
    "174": "Service was not prescribed prior to delivery",
    "175": "Prescription is incomplete",
    "176": "Prescription is not current",
    "177": "Patient has not met the required eligibility requirements",
    "178": "Patient has not met the required spend down requirements",
    "179": "Patient has not met the required waiting requirements",
    "180": "Patient has not met the required residency requirements",
    "181": "Procedure code was invalid on the date of service",
    "182": "Procedure modifier was invalid on the date of service",
    "183": "The referring provider is not eligible to refer the service billed",
    "184": "The prescribing/ordering provider is not eligible to prescribe/order the service billed",
    "185": "The rendering provider is not eligible to perform the service billed",
    "186": "Level of care adjustment",
    "187": "Consumer Operated and Oriented Plan (CO-OP)  Adjustment",
    "188": "This product/procedure is only covered when used according to FDA recommendations",
    "189": "Not otherwise classified (NOC) or unlisted procedure",
    "190": "Payment is included in the allowance for a Skilled Nursing Facility",
    "191": "Not a member/subscriber",
    "192": "Non standard adjustment code from paper remittance",
    "193": "Original payment decision is being maintained",
    "194": "Anesthesia performed by the operating physician, the ## assistant surgeon or the attending physician",
    "195": "Refund amount - Loss",
    "196": "Claim/service denied based on prior payer's coverage determination",
    "197": "Precertification/authorization/notification/pre-treatment absent",
    "198": "Precertification/authorization exceeded",
    "199": "Revenue code and Procedure code do not match",
    "200": "Expenses incurred during lapse in coverage",
    "201": "Workers' Compensation case  settled. Patient is responsible",
    "202": "Non-covered personal comfort or convenience services",
    "203": "Discontinued or reduced service",
    "204": "This service/equipment/drug is not covered under the patient's current benefit plan",
    "205": "Pharmacy discount",
    "206": "National Provider Identifier - Entity Not Eligible",
    "207": "Claim/service not payable under the current contract",
    "208": "National Provider Identifier - Billing provider not eligible",
    "209": "National Provider Identifier - Referring provider not eligible",
    "210": "National Provider Identifier - Rendering provider not eligible",
    "211": "National Drug Code (NDC) not eligible or not on applicable formulary",
    "212": "Administrative/Regulatory cost recovery",
    "213": "Non-covered visit(s) because provider has failed to obtain the necessary pre-authorization",
    "214": "Workers' Compensation claim  -  Benefits are set per State fee schedule",
    "215": "Based on subrogation of a third party settlement",
    "216": "Based on entitlement to benefits",
    "217": "Based on payer-Loss reasonable and customary fees",
    "218": "Based on entitlement to benefits - Loss or Renewal date",
    "219": "Based on extent of injury",
    "220": "The applicable fee schedule/fee database does not contain the billed code",
    "221": "Missing Revalidation for Rendering/Referring/Prescribing/Ordering Provider",
    "222": "Exceeds the contracted maximum number of hours/days/units",
    "223": "Adjustment code for mandated federal, state or local law/regulation that is not already covered by another code",
    "224": "Patient identification compromised by a reported identity theft",
    "225": "Penalty or Interest Payment",
    "226": "Information requested from the Billing/Rendering Provider was not provided or not provided timely",
    "227": "Information requested from the patient/insured/responsible party was not provided or was insufficient/incomplete",
    "228": "Denied based on a  Clinical Edit - Loss. Remark Codes identify the edit.",
    "229": "Partial charge amount not considered by Medicare due to the initial claim Type of Bill being 12X",
    "230": "No available or  registered  payment/remittance address",
    "231": "Mutually exclusive procedures cannot be done in the same day/setting",
    "232": "Institutional Transfer Amount",
    "233": "Services/charges related to the  treating  of a Hospital-Acquired Condition (HAC)",
    "234": "This procedure is not paid separately",
    "235": "Sales Tax",
    "236": "This procedure or procedure/modifier combination is not compatible with another procedure or procedure/modifier combination provided on the same day",
    "237": "Legislated/Regulatory Penalty. At least one Remark Code must be provided.",
    "238": "Claim spans eligible and ineligible periods of coverage",
    "239": "Claim spans eligible and ineligible periods of coverage. Payments made are the patient's liability",
    "240": "The diagnosis is inconsistent with the provider type",
    "241": "Low Income Subsidy (LIS) co-payment amount",
    "242": "Services not provided by network/primary care providers",
    "243": "Services not authorized by network/primary care providers",
    "244": "Payment reduced to zero due to litigation against the provider",
    "245": "Provider performance/withheld amount",
    "246": "This non-payable code is for required reporting only",
    "247": "Deductible for this service has been waived",
    "248": "Payment denied/reduced because the prior  payer's (or payers') parsing,  claim  adjustment(s) did not reflect a  reasonable amount.",
    "249": "Payments from Outlier, Cost Report, etc., settle this claim.  Future settlement is expected.",
    "250": "The attachment is missing, incomplete, or deficient",
    "251": "The attachment received is incomplete or deficient",
    "252": "An attachment/other documentation is required to adjudicate this claim/service",
    "253": "Sequestration - Loss reduction of federal payment",
    "254": "Claim received by the dental plan, but benefits not available under this plan",
    "255": "The disposition of the claim/service is undetermined during the premium payment grace period",
    "256": "Service not payable per managed care contract",
    "257": "The disposition of the claim/service is undetermined during the appeal",
    "258": "Claim/service not covered when patient is in custody/incarcerated",
    "259": "Additional payment for Dental/Vision service",
    "260": "Participant has been reassigned to a new plan",
    "261": "The procedure or service is inconsistent with the patient's history",
    "262": "An attachment/other documentation is required to adjudicate this claim/service",
    "263": "Adjustment for prior overpayment",
    "264": "Claim/service adjusted based on plan benefit limits for non-network providers",
    "265": "Claim/service has been cancelled",
    "266": "Payment denied based on the disposition of a related Workers' Compensation claim",
    "267": "Payment denied as the referring, prescribing or rendering provider has been barred from participation",
    "268": "Claim/service submitted by an entity that is not eligible to participate",
    "269": "Mandated Federal, State or Local law/regulation- Loss",
    "270": "Claim received by the dental plan, but benefits not available under this plan. Submit these services to the patient's medical plan for further consideration.",
    "271": "Prior contractual reductions related to a current periodic payment as part of a multi-period payment plan",
    "272": "Coverage/program guidelines were not met",
    "273": "Coverage/program guidelines were exceeded",
    "274": "Fee/service not payable per patient Care  Coordination arrangement",
    "275": "Prior Payer's (or payers')  claim  adjustment(s)",
    "276": "Services denied by the prior payer(s) are not covered by this payer",
    "277": "The  disposition of the claim/service is undetermined during a  related, pending determination/adjudication",
    "278": "Performance program  adjustment",
    "279": "Services not provided by designated (network/primary care) providers",
    "280": "Claim/service denied or adjusted based on a  recovery audit",
    "281": "Prior year(s) claim(s) retroactive adjustments",
    "282": "Claim/service adjusted; clinical records do not support the diagnosis, procedure, or dates provided",
    "283": "Claim/service adjusted; documentation of prior therapies was not sufficient",
    "284": "Claim/service adjusted; peer review recommended a change",
    "285": "Claim/service not covered/payable because the associated hospital admission was deemed not medically necessary",
    "286": "Claim/service adjusted; appeal process has been exhausted",
    "287": "Claim/service denied/adjusted based on a submission from a Quality Improvement Organization (QIO) review",
    "288": "Claim/service adjusted; the submitted clinical records for the service(s) do not support that it/they were medically necessary",
    "289": "Claim/service denied; the provider type/specialty may not bill this service",
    "290": "Claim/service denied; the provider type/specialty may not bill this service in this facility/setting",
    "291": "Claim/service denied; the provider has not been approved to provide the service to the member",
    "292": "Claim/service denied; service is not consistent with the authorized services",
    "293": "Payment adjusted because the summary of care record was not received timely",
    "294": "Payment denied; Service not furnished by a physician or other qualified health care professional and/or not furnished under the direct supervision of a physician or other qualified health care professional",
}

# Quick-lookup set of valid CARC code numbers (string keys)
VALID_CARC_CODES: frozenset[str] = frozenset(CARC_CODES.keys())


# ============================================================
# X12 835 CLAIM STATUS CODES (CLP02)
# Complete set per ASC X12 standard
# ============================================================

CLAIM_STATUS_CODES: dict[str, str] = {
    "1": "Processed as Primary",
    "2": "Processed as Secondary",
    "3": "Processed as Tertiary",
    "4": "Denied",
    "5": "Pended",
    "10": "Received, but not in process",
    "13": "Suspended",
    "15": "Suspended - investigation with field",
    "16": "Suspended - Loss return with material",
    "17": "Suspended - Loss review organization",
    "19": "Processed as Primary, Forwarded to Additional Payer(s)",
    "20": "Processed as Secondary, Forwarded to Additional Payer(s)",
    "21": "Processed as Tertiary, Forwarded to Additional Payer(s)",
    "22": "Reversal of Previous Payment",
    "23": "Not Our Claim, Forwarded to Another Payer(s)",
    "25": "Predetermination Pricing Only - No Payment",
}

VALID_CLAIM_STATUS_CODES: frozenset[str] = frozenset(CLAIM_STATUS_CODES.keys())


# ============================================================
# BPR PAYMENT METHOD CODES (BPR01)
# ASC X12 835 standard
# ============================================================

PAYMENT_METHOD_CODES: dict[str, str] = {
    "C": "Payment accompanies RA",
    "D": "Make payment only",
    "H": "Notification only",
    "I": "Remittance information only",
    "P": "Prenotification of future transfers",
    "U": "Split payment and remittance",
    "X": "Handling party's option to split payment and remittance",
    "CHK": "Check",
    "ACH": "Automated Clearing House",
    "BOP": "Financial Institution Option",
    "FWT": "Federal Reserve Wire Transfer",
    "NON": "Non-Payment Data",
}

VALID_PAYMENT_METHODS: frozenset[str] = frozenset(PAYMENT_METHOD_CODES.keys())


# ============================================================
# CAS GROUP CODES (CAS01)
# ASC X12 standard — complete set with descriptions
# ============================================================

CAS_GROUP_CODE_DESCRIPTIONS: dict[str, str] = {
    "CO": "Contractual Obligation — provider write-off per contract",
    "CR": "Correction/Reversal — previous claim reversal",
    "OA": "Other Adjustment — adjustment not classifiable elsewhere",
    "PI": "Payer Initiated Reduction — payer-determined reduction",
    "PR": "Patient Responsibility — amount the patient owes",
}

VALID_CAS_GROUP_CODES: frozenset[str] = frozenset(CAS_GROUP_CODE_DESCRIPTIONS.keys())


# ============================================================
# RADIOLOGY CPT CODE RANGES (CMS)
# Diagnostic radiology: 70010-76499
# Radiation oncology: 77261-77799
# Nuclear medicine: 78012-79999
# Diagnostic ultrasound: 76506-76999
# ============================================================

# Comprehensive radiology CPT codes commonly seen in imaging centers
# Organized by modality for crosswalk validation
RADIOLOGY_CPT_CODES: dict[str, str] = {
    # CT (Computed Tomography) — 70000-74999 range
    "70450": "CT head/brain without contrast",
    "70460": "CT head/brain with contrast",
    "70470": "CT head/brain without contrast, then with contrast",
    "70480": "CT orbit/sella/ear without contrast",
    "70481": "CT orbit/sella/ear with contrast",
    "70482": "CT orbit/sella/ear without, then with contrast",
    "70486": "CT maxillofacial without contrast",
    "70487": "CT maxillofacial with contrast",
    "70488": "CT maxillofacial without, then with contrast",
    "70490": "CT soft tissue neck without contrast",
    "70491": "CT soft tissue neck with contrast",
    "70492": "CT soft tissue neck without, then with contrast",
    "70496": "CT angiography head",
    "70498": "CT angiography neck",
    "71250": "CT chest without contrast",
    "71260": "CT chest with contrast",
    "71270": "CT chest without, then with contrast",
    "71271": "CT chest low dose for lung cancer screening",
    "71275": "CT angiography chest",
    "72125": "CT cervical spine without contrast",
    "72126": "CT cervical spine with contrast",
    "72127": "CT cervical spine without, then with contrast",
    "72128": "CT thoracic spine without contrast",
    "72129": "CT thoracic spine with contrast",
    "72130": "CT thoracic spine without, then with contrast",
    "72131": "CT lumbar spine without contrast",
    "72132": "CT lumbar spine with contrast",
    "72133": "CT lumbar spine without, then with contrast",
    "72191": "CT angiography pelvis",
    "72192": "CT pelvis without contrast",
    "72193": "CT pelvis with contrast",
    "72194": "CT pelvis without, then with contrast",
    "73200": "CT upper extremity without contrast",
    "73201": "CT upper extremity with contrast",
    "73202": "CT upper extremity without, then with contrast",
    "73206": "CT angiography upper extremity",
    "73700": "CT lower extremity without contrast",
    "73701": "CT lower extremity with contrast",
    "73702": "CT lower extremity without, then with contrast",
    "73706": "CT angiography lower extremity",
    "74150": "CT abdomen without contrast",
    "74160": "CT abdomen with contrast",
    "74170": "CT abdomen without, then with contrast",
    "74174": "CT angiography abdomen and pelvis",
    "74175": "CT angiography abdomen",
    "74176": "CT abdomen and pelvis without contrast",
    "74177": "CT abdomen and pelvis with contrast",
    "74178": "CT abdomen and pelvis without, then with contrast",
    "75571": "CT heart calcium scoring",
    "75572": "CT heart without contrast, with quantitative evaluation",
    "75573": "CT heart with contrast, with quantitative evaluation",
    "75574": "CT angiography heart with contrast",
    "75635": "CT angiography abdominal aorta",
    # MRI (HMRI) — 70000-73999 range
    "70336": "MRI temporomandibular joint",
    "70540": "MRI orbit/face/neck without contrast",
    "70542": "MRI orbit/face/neck with contrast",
    "70543": "MRI orbit/face/neck without, then with contrast",
    "70551": "MRI brain without contrast",
    "70552": "MRI brain with contrast",
    "70553": "MRI brain without, then with contrast",
    "70554": "Functional MRI brain",
    "70555": "Functional MRI brain by technician",
    "71550": "MRI chest without contrast",
    "71551": "MRI chest with contrast",
    "71552": "MRI chest without, then with contrast",
    "71555": "MRA chest",
    "72141": "MRI cervical spine without contrast",
    "72142": "MRI cervical spine with contrast",
    "72146": "MRI thoracic spine without contrast",
    "72147": "MRI thoracic spine with contrast",
    "72148": "MRI lumbar spine without contrast",
    "72149": "MRI lumbar spine with contrast",
    "72156": "MRI cervical spine without, then with contrast",
    "72157": "MRI thoracic spine without, then with contrast",
    "72158": "MRI lumbar spine without, then with contrast",
    "72195": "MRI pelvis without contrast",
    "72196": "MRI pelvis with contrast",
    "72197": "MRI pelvis without, then with contrast",
    "73218": "MRI upper extremity without contrast",
    "73219": "MRI upper extremity with contrast",
    "73220": "MRI upper extremity without, then with contrast",
    "73221": "MRI any joint upper extremity without contrast",
    "73222": "MRI any joint upper extremity with contrast",
    "73223": "MRI any joint upper extremity without, then with contrast",
    "73718": "MRI lower extremity without contrast",
    "73719": "MRI lower extremity with contrast",
    "73720": "MRI lower extremity without, then with contrast",
    "73721": "MRI any joint lower extremity without contrast",
    "73722": "MRI any joint lower extremity with contrast",
    "73723": "MRI any joint lower extremity without, then with contrast",
    "74181": "MRI abdomen without contrast",
    "74182": "MRI abdomen with contrast",
    "74183": "MRI abdomen without, then with contrast",
    "77084": "MRI bone marrow blood supply",
    # PET (Positron Emission Tomography) — 78800 range
    "78429": "PET imaging for perfusion, single study",
    "78430": "PET imaging for perfusion, multiple studies",
    "78431": "PET imaging for perfusion with CT",
    "78432": "PET imaging for perfusion with CT, multiple",
    "78459": "PET for myocardial imaging, metabolic evaluation",
    "78491": "PET imaging for myocardial perfusion, single study",
    "78492": "PET imaging for myocardial perfusion, multiple studies",
    "78608": "PET brain imaging",
    "78609": "PET brain imaging with CT",
    "78811": "PET for limited area (other than brain or heart)",
    "78812": "PET skull base to mid-thigh",
    "78813": "PET whole body",
    "78814": "PET with CT, limited area",
    "78815": "PET with CT, skull base to mid-thigh",
    "78816": "PET with CT, whole body",
    "78830": "RP localization for radiopharmaceutical agent, limited",
    "78831": "RP localization with SPECT",
    "78832": "RP localization with SPECT/CT",
    # Bone Density / Nuclear Medicine — 78000-78999
    "77080": "DEXA bone density, axial skeleton",
    "77081": "DEXA bone density, appendicular",
    "77085": "DEXA bone density, axial with vertebral fracture assessment",
    "77086": "Vertebral fracture assessment",
    "78300": "Bone imaging, limited area",
    "78305": "Bone imaging, multiple areas",
    "78306": "Bone imaging, whole body",
    "78315": "Bone imaging, 3-phase study",
    "78350": "Bone density, single photon absorptiometry",
    "78399": "Nuclear medicine procedure, musculoskeletal, unlisted",
    # Diagnostic X-Ray (DX)
    "71045": "Chest X-ray, single view",
    "71046": "Chest X-ray, 2 views",
    "71047": "Chest X-ray, 3 views",
    "71048": "Chest X-ray, 4 or more views",
    "72020": "Spine X-ray, single view",
    "72040": "Cervical spine X-ray, 2-3 views",
    "72050": "Cervical spine X-ray, 4-5 views",
    "72052": "Cervical spine X-ray, 6 or more views",
    "72070": "Thoracic spine X-ray, 2 views",
    "72072": "Thoracic spine X-ray, 3 views",
    "72080": "Thoracolumbar spine X-ray, 2 views",
    "72100": "Lumbosacral spine X-ray, 2-3 views",
    "72110": "Lumbosacral spine X-ray, minimum 4 views",
    "73000": "Clavicle X-ray",
    "73010": "Scapula X-ray",
    "73020": "Shoulder X-ray, 1 view",
    "73030": "Shoulder X-ray, minimum 2 views",
    "73060": "Humerus X-ray, minimum 2 views",
    "73070": "Elbow X-ray, 2 views",
    "73080": "Elbow X-ray, minimum 3 views",
    "73090": "Forearm X-ray, 2 views",
    "73100": "Wrist X-ray, 2 views",
    "73110": "Wrist X-ray, minimum 3 views",
    "73120": "Hand X-ray, 2 views",
    "73130": "Hand X-ray, minimum 3 views",
    "73140": "Finger X-ray, minimum 2 views",
    "73501": "Hip X-ray, 1 view",
    "73502": "Hip X-ray, 2-3 views",
    "73503": "Hip X-ray, minimum 4 views",
    "73521": "Bilateral hips, 2 views",
    "73522": "Bilateral hips, 3-4 views",
    "73523": "Bilateral hips, 5 or more views",
    "73551": "Femur X-ray, 1 view",
    "73552": "Femur X-ray, minimum 2 views",
    "73560": "Knee X-ray, 1-2 views",
    "73562": "Knee X-ray, 3 views",
    "73564": "Knee X-ray, 4 or more views",
    "73565": "Bilateral knees, standing",
    "73590": "Tibia/fibula X-ray, 2 views",
    "73600": "Ankle X-ray, 2 views",
    "73610": "Ankle X-ray, minimum 3 views",
    "73620": "Foot X-ray, 2 views",
    "73630": "Foot X-ray, minimum 3 views",
    "73650": "Calcaneus X-ray, minimum 2 views",
    "73660": "Toe X-ray, minimum 2 views",
    # Fluoroscopy
    "76000": "Fluoroscopy, up to 1 hour",
    "77002": "Fluoroscopic guidance for needle placement",
    # Ultrasound (US)
    "76536": "Ultrasound soft tissues of head and neck",
    "76604": "Ultrasound chest/mediastinum",
    "76641": "Ultrasound breast, unilateral, complete",
    "76642": "Ultrasound breast, unilateral, limited",
    "76700": "Ultrasound abdomen, complete",
    "76705": "Ultrasound abdomen, limited",
    "76770": "Ultrasound retroperitoneal, complete",
    "76775": "Ultrasound retroperitoneal, limited",
    "76801": "Ultrasound pregnant uterus, first trimester",
    "76805": "Ultrasound pregnant uterus, after first trimester",
    "76830": "Ultrasound transvaginal",
    "76856": "Ultrasound pelvis, non-obstetric, complete",
    "76857": "Ultrasound pelvis, non-obstetric, limited",
    "76870": "Ultrasound scrotum",
    "76881": "Ultrasound extremity, non-vascular, complete",
    "76882": "Ultrasound extremity, non-vascular, limited",
    "93880": "Duplex scan extracranial arteries",
    "93925": "Duplex scan lower extremity arteries",
    "93926": "Duplex scan lower extremity arteries, unilateral",
    "93970": "Duplex scan extremity veins, complete bilateral",
    "93971": "Duplex scan extremity veins, unilateral",
    # Mammography (MAMMO)
    "77065": "Diagnostic mammography, unilateral",
    "77066": "Diagnostic mammography, bilateral",
    "77067": "Screening mammography, bilateral",
    "77061": "Digital breast tomosynthesis, unilateral",
    "77062": "Digital breast tomosynthesis, bilateral",
    "77063": "Screening digital breast tomosynthesis, bilateral",
}

VALID_RADIOLOGY_CPT_CODES: frozenset[str] = frozenset(RADIOLOGY_CPT_CODES.keys())


# Extended CPT-to-modality crosswalk (superset of the one in data_validation.py)
CPT_TO_MODALITY_EXTENDED: dict[str, str] = {}
_CT_PREFIXES = ("704", "705", "710", "711", "712", "721", "722", "723", "732", "737", "741", "742", "743", "744", "755", "756")
_MRI_PREFIXES = ("703", "705", "715", "721", "722", "723", "732", "737", "741", "770")
# Build from RADIOLOGY_CPT_CODES descriptions
for _code, _desc in RADIOLOGY_CPT_CODES.items():
    _desc_upper = _desc.upper()
    if "CT " in _desc_upper or _desc_upper.startswith("CT "):
        CPT_TO_MODALITY_EXTENDED[_code] = "CT"
    elif "MRI " in _desc_upper or "MRA " in _desc_upper or _desc_upper.startswith("MRI ") or _desc_upper.startswith("FUNCTIONAL MRI"):
        CPT_TO_MODALITY_EXTENDED[_code] = "HMRI"
    elif "PET " in _desc_upper or _desc_upper.startswith("PET ") or "RP LOCALIZATION" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "PET"
    elif "BONE " in _desc_upper and ("IMAGING" in _desc_upper or "DENSITY" in _desc_upper):
        CPT_TO_MODALITY_EXTENDED[_code] = "BONE"
    elif "DEXA" in _desc_upper or "VERTEBRAL FRACTURE" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "DEXA"
    elif "X-RAY" in _desc_upper or "CHEST X" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "DX"
    elif "FLUORO" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "FLUORO"
    elif "MAMMO" in _desc_upper or "TOMOSYNTHESIS" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "MAMMO"
    elif "ULTRASOUND" in _desc_upper or "DUPLEX" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "US"
    elif "NUCLEAR" in _desc_upper:
        CPT_TO_MODALITY_EXTENDED[_code] = "NM"

# Clean up module namespace
del _code, _desc, _desc_upper, _CT_PREFIXES, _MRI_PREFIXES


# ============================================================
# COMMON RARC (Remittance Advice Remark Codes)
# Supplementary codes that appear alongside CARC codes
# ============================================================

COMMON_RARC_CODES: dict[str, str] = {
    "M1": "X-ray not taken within the prescribed time frame",
    "M2": "Not paid separately when the patient is an inpatient",
    "M5": "Information provided is inconsistent",
    "M6": "Payment adjusted when a more specific diagnosis code is available",
    "M15": "Separately billed services/tests have been bundled",
    "M20": "Missing/incomplete/invalid HCPCS",
    "M27": "Missing/incomplete/invalid entitlement number or SSN",
    "M36": "This is a chronic condition for which a more acute phase of treatment was previously approved",
    "M49": "Missing/incomplete/invalid value code(s) or amount(s)",
    "M51": "Missing/incomplete/invalid procedure code(s)",
    "M76": "Missing/incomplete/invalid diagnosis or condition",
    "M77": "Missing/incomplete/invalid place of service",
    "M80": "Not covered when performed during the same session/date as a previously processed service",
    "M81": "You are required to code to the highest level of specificity",
    "MA01": "If you do not agree with the approved amounts, you may appeal",
    "MA04": "Secondary payment cannot be considered without the identity of/or payment information from the primary payer",
    "MA07": "The claim information has also been forwarded to Medicaid for review",
    "MA13": "You may be subject to penalties if you bill the patient for amounts not reported with the PR group code",
    "MA18": "The claim information is also being forwarded to the patient's supplemental insurer",
    "MA28": "Claim information was not forwarded because the supplemental coverage information was either invalid or not on file",
    "MA130": "Your claim contains incomplete and/or invalid information",
    "N1": "You may appeal this decision",
    "N2": "This allowance has been made in accordance with the most appropriate fee schedule",
    "N4": "Missing/incomplete/invalid prior Insurance Carrier(s) EOB",
    "N5": "EOB received from previous payer. Adjudication based on the information received",
    "N16": "Seeds request and target",
    "N19": "Procedure code incidental to primary procedure",
    "N20": "Service not separately priced or billed",
    "N30": "Patient ineligible for this service",
    "N56": "Procedure code billed is not correct; advise the most appropriate code",
    "N95": "This provider type/provider specialty may not bill this service",
    "N115": "This decision was based on a National Coverage Determination (NCD)",
    "N386": "This decision was based on a Local Coverage Determination (LCD)",
    "N425": "Statutorily excluded service(s)",
    "N432": "Adjustment based on a Recovery Audit",
    "N519": "Invalid/missing adjustment reason code",
    "N522": "Duplicate of a claim processed, or to be processed, as a crossover claim",
    "N527": "Payment adjusted: claim/service lacks indication of whether the patient owns the equipment",
    "N620": "Adjusted based on a previous payer(s) claim adjustment or allowed amount",
    "N657": "This should be billed with the appropriate code for this service/supply",
}

VALID_RARC_CODES: frozenset[str] = frozenset(COMMON_RARC_CODES.keys())


# ============================================================
# DTM QUALIFIER CODES (X12 835)
# Date/Time qualifier codes used in 835 remittance
# ============================================================

DTM_QUALIFIER_CODES: dict[str, str] = {
    "036": "Expiration",
    "050": "Received",
    "150": "Service Period Start",
    "151": "Service Period End",
    "232": "Claim Statement Period Start",
    "233": "Claim Statement Period End",
    "405": "Production",
    "472": "Service",
}

VALID_DTM_QUALIFIERS: frozenset[str] = frozenset(DTM_QUALIFIER_CODES.keys())


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def lookup_carc(code: str) -> str | None:
    """Return the description for a CARC code, or None if unknown."""
    return CARC_CODES.get(str(code).strip())


def lookup_claim_status(code: str) -> str | None:
    """Return the description for a claim status code, or None if unknown."""
    return CLAIM_STATUS_CODES.get(str(code).strip())


def lookup_cpt(code: str) -> str | None:
    """Return the description for a radiology CPT code, or None if unknown."""
    return RADIOLOGY_CPT_CODES.get(str(code).strip())


def cpt_to_modality(code: str) -> str | None:
    """Return the expected modality for a CPT code, or None if unknown."""
    return CPT_TO_MODALITY_EXTENDED.get(str(code).strip())


def is_valid_cpt_format(code: str) -> bool:
    """Check if a code matches CPT (5 digits) or HCPCS Level II (letter + 4 digits) format."""
    code = str(code).strip()
    if len(code) == 5 and code.isdigit():
        return True
    # HCPCS Level II: letter followed by 4 digits (e.g., A0428, J1234)
    if len(code) == 5 and code[0].isalpha() and code[1:].isdigit():
        return True
    return False


def is_radiology_cpt_range(code: str) -> bool:
    """Check if a 5-digit CPT code falls within known radiology ranges.

    Radiology CPT ranges (CMS):
      70010-76999: Diagnostic Radiology/Imaging
      77001-77799: Radiation Oncology (some imaging guidance)
      78000-79999: Nuclear Medicine
      93880-93998: Vascular studies (duplex/doppler)
    """
    code = str(code).strip()
    if not code.isdigit() or len(code) != 5:
        return False
    num = int(code)
    return (
        (70010 <= num <= 76999) or
        (77001 <= num <= 77799) or
        (78000 <= num <= 79999) or
        (93880 <= num <= 93998)
    )
