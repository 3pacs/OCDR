#!/usr/bin/env python3
"""
Generate realistic sample data for the OCMRI Billing Reconciliation System.

Creates:
  1. OCMRI.xlsx — 200 billing records across 6 modalities, 16 payers, 12 months
  2. sample_era_*.835 — 5 ERA 835 files with ~150 claim lines (some matched, some not)
  3. Covers edge cases: PSMA PET, gado contrast, denials, secondary insurance,
     written-off claims, research patients, name mismatches

Usage:
  python scripts/generate_sample_data.py
  # Files land in data/excel/ and data/eobs/
"""

import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from openpyxl import Workbook
except ImportError:
    print("ERROR: openpyxl required. Run: pip install openpyxl")
    sys.exit(1)


# ============================================================
# REALISTIC REFERENCE DATA
# ============================================================

DOCTORS = [
    "JHANGIANI", "BEACH", "PHAN", "NGUYEN", "SMITH",
    "RODRIGUEZ", "KIM", "PARK", "CHEN", "WILLIAMS",
    "JOHNSON", "MARTINEZ", "LEE", "TAYLOR", "BROWN",
]

READING_PHYSICIANS = [
    "JHANGIANI", "BEACH", "PHAN", "NGUYEN", "SMITH",
    "KIM", "CHEN", "LEE",
]

PAYER_CODES = [
    "M/M", "CALOPTIMA", "FAMILY", "INS", "VU PHAN",
    "W/C", "BEACH", "ONE CALL", "OC ADV", "SELF PAY",
    "STATE", "COMP", "GH", "JHANGIANI", "X",
]

# Weighted distribution: Medicare/Medicaid most common
PAYER_WEIGHTS = [
    25, 12, 8, 15, 3, 5, 4, 3, 2, 5,
    3, 2, 5, 3, 5,
]

MODALITIES = ["CT", "HMRI", "PET", "BONE", "OPEN", "DX"]
MODALITY_WEIGHTS = [30, 25, 10, 10, 15, 10]

# Scan descriptions by modality
SCAN_TYPES = {
    "CT": [
        "CT ABDOMEN W CONTRAST", "CT CHEST WO CONTRAST", "CT HEAD WO CONTRAST",
        "CT PELVIS W CONTRAST", "CT SPINE LUMBAR WO CONTRAST", "CT ABDOMEN PELVIS W CONTRAST",
        "CT BRAIN W/WO CONTRAST", "CT NECK W CONTRAST",
    ],
    "HMRI": [
        "MRI BRAIN WO CONTRAST", "MRI BRAIN W/WO CONTRAST", "MRI LUMBAR SPINE WO",
        "MRI KNEE LEFT WO CONTRAST", "MRI SHOULDER RIGHT W/WO", "MRI CERVICAL SPINE WO",
        "MRI ABDOMEN W/WO CONTRAST", "MRI PELVIS WO CONTRAST",
    ],
    "PET": [
        "PET/CT WHOLE BODY", "PET/CT SKULL BASE TO THIGH",
        "PET/CT BRAIN", "PET/CT PSMA GA-68 WHOLE BODY",
        "PET/CT PSMA PROSTATE STAGING",
    ],
    "BONE": [
        "BONE SCAN WHOLE BODY", "BONE SCAN LIMITED", "BONE SCAN 3-PHASE",
        "BONE DENSITY DEXA SCAN",
    ],
    "OPEN": [
        "MRI BRAIN WO CONTRAST (OPEN)", "MRI LUMBAR SPINE WO (OPEN)",
        "MRI KNEE WO CONTRAST (OPEN)", "MRI CERVICAL SPINE WO (OPEN)",
    ],
    "DX": [
        "XRAY CHEST 2 VIEW", "XRAY ABDOMEN", "XRAY HAND 3 VIEW",
        "XRAY KNEE 3 VIEW", "XRAY SPINE LUMBAR 3 VIEW", "XRAY SHOULDER 2 VIEW",
    ],
}

# CPT codes by modality
CPT_CODES = {
    "CT": ["70460", "71260", "70450", "72131", "74177", "74178"],
    "HMRI": ["70551", "70553", "72148", "73721", "73222", "72141"],
    "PET": ["78815", "78816", "78814"],
    "BONE": ["78300", "78305", "78315", "77080"],
    "OPEN": ["70551", "72148", "73721", "72141"],
    "DX": ["71046", "74018", "73130", "73562", "72100", "73030"],
}

# Fee schedule: expected rates by modality
FEE_RATES = {
    "CT": 395.00, "HMRI": 750.00, "PET": 2500.00,
    "BONE": 1800.00, "OPEN": 750.00, "DX": 250.00,
    "PET_PSMA": 8046.00,
}

# Realistic patient names — mix of demographics
PATIENT_NAMES = [
    # Standard names
    ("SMITH", "JOHN"), ("JOHNSON", "MARY"), ("WILLIAMS", "ROBERT"),
    ("BROWN", "PATRICIA"), ("JONES", "JAMES"), ("GARCIA", "MARIA"),
    ("MILLER", "DAVID"), ("DAVIS", "JENNIFER"), ("RODRIGUEZ", "CARLOS"),
    ("MARTINEZ", "LINDA"), ("HERNANDEZ", "JOSE"), ("LOPEZ", "ELIZABETH"),
    ("GONZALEZ", "DANIEL"), ("WILSON", "BARBARA"), ("ANDERSON", "RICHARD"),
    ("THOMAS", "SUSAN"), ("TAYLOR", "JOSEPH"), ("MOORE", "MARGARET"),
    ("JACKSON", "CHARLES"), ("MARTIN", "JESSICA"),
    # Hispanic compound names (edge case: name matching)
    ("FAVELA DE CENICEROS", "CAMERINA"), ("GARCIA LOPEZ", "MARIA ELENA"),
    ("RODRIGUEZ SANCHEZ", "ANA PATRICIA"), ("DE LA CRUZ", "PEDRO"),
    ("VAN NGUYEN", "THANH"), ("TRAN", "HOANG"),
    # Asian names (edge case: short names)
    ("KIM", "SOOMIN"), ("PARK", "JINSOO"), ("CHEN", "WEI"),
    ("NGUYEN", "LINH"), ("LE", "TUYET"), ("PHAM", "HUNG"),
    # Research patients
    ("DOE", "JANE"), ("DOE", "JOHN"), ("TEST", "PATIENT"),
    # More standard
    ("CLARK", "NANCY"), ("LEWIS", "KEVIN"), ("ROBINSON", "DONNA"),
    ("WALKER", "STEVEN"), ("HALL", "CAROL"), ("ALLEN", "GEORGE"),
    ("YOUNG", "RUTH"), ("KING", "EDWARD"), ("WRIGHT", "HELEN"),
    ("SCOTT", "BRIAN"), ("GREEN", "SHARON"), ("BAKER", "RONALD"),
    ("ADAMS", "DOROTHY"), ("NELSON", "TIMOTHY"), ("HILL", "DEBORAH"),
    ("RAMIREZ", "ANTHONY"), ("CAMPBELL", "LAURA"), ("MITCHELL", "FRANK"),
    ("ROBERTS", "STEPHANIE"), ("CARTER", "RAYMOND"), ("PHILLIPS", "ANDREA"),
    ("EVANS", "DENNIS"), ("TURNER", "KIMBERLY"), ("TORRES", "JERRY"),
    ("PARKER", "PAMELA"), ("COLLINS", "ALEXANDER"), ("EDWARDS", "EMILY"),
    ("STEWART", "JOSHUA"), ("SANCHEZ", "CHRISTINE"), ("MORRIS", "GARY"),
    ("ROGERS", "MICHELLE"), ("REED", "LARRY"), ("COOK", "AMANDA"),
    ("MORGAN", "SCOTT"), ("BELL", "SANDRA"), ("MURPHY", "JESSE"),
    ("BAILEY", "CATHERINE"), ("RIVERA", "TERRY"), ("COOPER", "JANICE"),
    ("RICHARDSON", "SEAN"), ("COX", "DIANA"), ("HOWARD", "PETER"),
    ("WARD", "CHERYL"), ("TORRES", "RALPH"), ("PETERSON", "JEAN"),
    ("GRAY", "CARL"), ("RAMIREZ", "ANGELA"), ("JAMES", "WAYNE"),
    ("WATSON", "ALICE"), ("BROOKS", "KEITH"), ("SANDERS", "THERESA"),
]

# Date range: Jan 2024 to Dec 2025
DATE_START = date(2024, 1, 1)
DATE_END = date(2025, 12, 31)
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def random_date(start=DATE_START, end=DATE_END):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def random_birth_date():
    """Generate a random birth date (18-95 years old)."""
    today = date.today()
    age = random.randint(18, 95)
    return today - timedelta(days=age * 365 + random.randint(0, 364))


# ============================================================
# GENERATE OCMRI EXCEL (23-column layout)
# ============================================================

def generate_billing_records(n=200):
    """Generate n realistic billing records."""
    records = []
    # Assign stable patient IDs
    patient_pool = list(PATIENT_NAMES[:min(n, len(PATIENT_NAMES))])
    patient_data = {}
    for i, (last, first) in enumerate(patient_pool):
        chart_id = 4000 + i
        topaz_id = 60000 + i
        dob = random_birth_date()
        patient_data[(last, first)] = {
            "chart_id": chart_id, "topaz_id": topaz_id, "dob": dob
        }

    for i in range(n):
        last, first = random.choice(patient_pool)
        pd_ = patient_data[(last, first)]
        patient_name = f"{last}, {first}"
        doctor = random.choice(DOCTORS)
        modality = random.choices(MODALITIES, weights=MODALITY_WEIGHTS, k=1)[0]
        scan = random.choice(SCAN_TYPES[modality])
        gado = "YES" if (modality in ("HMRI", "OPEN") and random.random() < 0.4) else ""
        insurance = random.choices(PAYER_CODES, weights=PAYER_WEIGHTS, k=1)[0]
        svc_date = random_date()

        # Determine PSMA
        is_psma = "PSMA" in scan
        effective_modality = "PET_PSMA" if is_psma else modality
        base_rate = FEE_RATES.get(effective_modality, 500.0)

        # Payment logic based on insurance
        if insurance == "X":
            # Written-off
            primary = 0.0
            secondary = 0.0
            total = 0.0
        elif insurance in ("SELF PAY", "COMP"):
            primary = round(base_rate * random.uniform(0.2, 0.5), 2)
            secondary = 0.0
            total = primary
        elif insurance == "M/M":
            # Medicare — often has secondary
            primary = round(base_rate * random.uniform(0.6, 0.9), 2)
            if random.random() < 0.4:
                secondary = round(base_rate * random.uniform(0.05, 0.15), 2)
            else:
                secondary = 0.0
            total = round(primary + secondary, 2)
        else:
            primary = round(base_rate * random.uniform(0.5, 1.0), 2)
            secondary = 0.0
            if random.random() < 0.1:
                secondary = round(base_rate * random.uniform(0.05, 0.2), 2)
            total = round(primary + secondary, 2)

        extra_charges = round(random.uniform(0, 50), 2) if random.random() < 0.15 else 0.0
        reader = random.choice(READING_PHYSICIANS)

        # Sometimes names differ slightly between column A and O (edge case G-04)
        if random.random() < 0.05:
            display_name = f"{last}, {first[0]}."  # Abbreviated
        else:
            display_name = patient_name

        schedule_date = svc_date - timedelta(days=random.randint(0, 14))
        month = MONTHS[svc_date.month - 1]
        year = str(svc_date.year)
        is_new = "YES" if random.random() < 0.08 else ""

        records.append({
            "patient_name": patient_name,
            "doctor": doctor,
            "scan": scan,
            "gado": gado,
            "insurance": insurance,
            "type": modality,
            "date": svc_date,
            "primary": primary,
            "secondary": secondary,
            "total": total,
            "extra": extra_charges,
            "read_by": reader,
            "chart_id": pd_["chart_id"],
            "birth_date": pd_["dob"],
            "patient_name_display": display_name,
            "s_date": schedule_date,
            "modalities": modality,
            "description": scan,
            "month": month,
            "year": year,
            "new": is_new,
            "topaz_patient_id": pd_["topaz_id"],
            "payer_group": insurance if insurance not in ("X", "COMP") else "",
        })

    return records


def write_ocmri_excel(records, output_path):
    """Write records to OCMRI.xlsx in 23-column format."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Current"

    # 23-column header (new layout)
    headers = [
        "Patient", "Doctor", "Scan", "Gado", "Insurance", "Type", "Date",
        "Primary", "Secondary", "Total", "Extra", "Read By", "Chart ID",
        "Birth Date", "Patient Name", "S Date", "Modalities", "Description",
        "Month", "Year", "New", "Patient ID", "Payer Group"
    ]
    ws.append(headers)

    for r in records:
        ws.append([
            r["patient_name"], r["doctor"], r["scan"], r["gado"],
            r["insurance"], r["type"], r["date"],
            r["primary"], r["secondary"], r["total"], r["extra"],
            r["read_by"], r["chart_id"], r["birth_date"],
            r["patient_name_display"], r["s_date"], r["modalities"],
            r["description"], r["month"], r["year"], r["new"],
            r["topaz_patient_id"], r["payer_group"],
        ])

    wb.save(output_path)
    print(f"  Wrote {len(records)} records to {output_path}")
    return output_path


# ============================================================
# GENERATE ERA 835 FILES
# ============================================================

def _format_date_835(d):
    """Format date as CCYYMMDD."""
    return d.strftime("%Y%m%d")


def generate_835_file(records_subset, payer_name, check_number, payment_date, filename):
    """Generate a single 835 file from a subset of billing records."""
    total_payment = sum(r["total"] for r in records_subset)

    segments = []

    # ISA header
    segments.append(
        f"ISA*00*          *00*          *ZZ*PAYER          "
        f"*ZZ*OCMRI          *{_format_date_835(payment_date)[:6]}*{_format_date_835(payment_date)[6:]}"
        f"*^*00501*000000001*0*P*:"
    )
    segments.append("GS*HP*PAYER*OCMRI*20250101*1200*1*X*005010X221A1")
    segments.append("ST*835*0001")

    # BPR — payment info
    segments.append(
        f"BPR*C*{total_payment:.2f}*C*ACH*CCP*01*999999999*DA*123456789*"
        f"1234567890**01*999999999*DA*987654321*{_format_date_835(payment_date)}"
    )

    # TRN — trace number
    segments.append(f"TRN*1*{check_number}*1234567890")

    # N1 — payer
    segments.append(f"N1*PR*{payer_name}")
    segments.append("N1*PE*ORANGE COUNTY DIAGNOSTIC RADIOLOGY*XX*1234567890")

    for rec in records_subset:
        # Use Topaz prefix-encoded ID (edge case G-05)
        prefix = random.choice(["10", "20"]) if random.random() < 0.3 else "10"
        claim_id = f"{prefix}0{rec['topaz_patient_id']}"

        # Sometimes zero-pad (edge case G-06)
        if random.random() < 0.2:
            claim_id = claim_id.zfill(12)

        last, first = rec["patient_name"].split(", ", 1)

        # Determine claim status
        if rec["insurance"] == "X":
            claim_status = "4"  # Denied
        elif rec["total"] == 0:
            claim_status = "4"
        else:
            claim_status = random.choice(["1", "1", "1", "1", "2", "22"])

        billed_amount = FEE_RATES.get(
            "PET_PSMA" if "PSMA" in rec["scan"] else rec["type"], 500.0
        )

        # CLP — claim
        segments.append(
            f"CLP*{claim_id}*{claim_status}*{billed_amount:.2f}*{rec['total']:.2f}"
        )

        # NM1 — patient name (sometimes different from billing — edge case G-01)
        era_last = last
        era_first = first
        if random.random() < 0.05:
            # Simulate name mismatch: truncate or use maiden name
            if " " in era_last:
                era_last = era_last.split()[0]  # Truncate compound name
        segments.append(f"NM1*QC*1*{era_last}*{era_first}")

        # SVC — service line
        modality = rec["type"]
        cpt = random.choice(CPT_CODES.get(modality, ["99999"]))
        segments.append(f"SVC*HC:{cpt}*{billed_amount:.2f}*{rec['total']:.2f}")

        # DTP — service date (sometimes offset by a few days — edge case G-08)
        svc_date = rec["date"]
        if random.random() < 0.15:
            svc_date = svc_date + timedelta(days=random.randint(-3, 3))
        segments.append(f"DTP*472*D8*{_format_date_835(svc_date)}")

        # CAS — adjustments (if underpaid or denied)
        adj_amount = round(billed_amount - rec["total"], 2)
        if adj_amount > 0.01:
            if claim_status == "4":
                # Denial — use common CARC codes
                reason = random.choice(["29", "27", "26", "96", "197", "CO16"])
                group = "CO"
            else:
                # Contractual adjustment
                reason = random.choice(["45", "42", "253"])
                group = "CO"
            segments.append(f"CAS*{group}*{reason}*{adj_amount:.2f}")

    segments.append("SE*999*0001")
    segments.append("GE*1*1")
    segments.append("IEA*1*000000001")

    return "~\n".join(segments) + "~"


def generate_all_835s(records, output_dir):
    """Generate 5 ERA 835 files from billing records."""
    # Split records into 5 groups by payer
    payer_groups = {}
    for r in records:
        carrier = r["insurance"]
        if carrier not in ("X", "COMP", "SELF PAY"):
            payer_groups.setdefault(carrier, []).append(r)

    files_written = []
    file_idx = 0

    # Create ~5 files from the largest payer groups
    sorted_payers = sorted(payer_groups.items(), key=lambda x: -len(x[1]))

    for payer, recs in sorted_payers[:5]:
        file_idx += 1
        payment_date = date(2025, random.randint(6, 12), random.randint(1, 28))
        check_number = f"EFT{random.randint(100000, 999999)}"
        filename = f"sample_era_{file_idx:02d}_{payer.replace('/', '_').replace(' ', '_')}.835"
        filepath = os.path.join(output_dir, filename)

        content = generate_835_file(recs, payer, check_number, payment_date, filename)

        with open(filepath, "w") as f:
            f.write(content)

        files_written.append(filepath)
        print(f"  Wrote {len(recs)} claims to {filepath}")

    # Add one file with unmatched claims (patients not in billing)
    file_idx += 1
    unmatched_records = []
    for i in range(10):
        last = random.choice(["UNKNOWN", "ORPHAN", "GHOST", "PHANTOM", "MYSTERY"])
        first = random.choice(["PATIENT", "CLAIM", "RECORD"])
        unmatched_records.append({
            "patient_name": f"{last}, {first}",
            "doctor": "UNKNOWN",
            "scan": "CT ABDOMEN W CONTRAST",
            "gado": "",
            "insurance": "INS",
            "type": "CT",
            "date": random_date(date(2025, 6, 1), date(2025, 12, 31)),
            "primary": round(random.uniform(200, 800), 2),
            "secondary": 0.0,
            "total": round(random.uniform(200, 800), 2),
            "extra": 0.0,
            "topaz_patient_id": 99000 + i,
        })

    filename = f"sample_era_{file_idx:02d}_unmatched.835"
    filepath = os.path.join(output_dir, filename)
    content = generate_835_file(
        unmatched_records, "UNKNOWN PAYER", "EFT000000",
        date(2025, 11, 15), filename
    )
    with open(filepath, "w") as f:
        f.write(content)
    files_written.append(filepath)
    print(f"  Wrote {len(unmatched_records)} unmatched claims to {filepath}")

    return files_written


# ============================================================
# MAIN
# ============================================================

def main():
    random.seed(42)  # Reproducible

    excel_dir = PROJECT_ROOT / "data" / "excel"
    eobs_dir = PROJECT_ROOT / "data" / "eobs"
    excel_dir.mkdir(parents=True, exist_ok=True)
    eobs_dir.mkdir(parents=True, exist_ok=True)

    print("Generating sample OCMRI billing data...")
    records = generate_billing_records(200)
    excel_path = write_ocmri_excel(records, excel_dir / "OCMRI_sample.xlsx")

    print("\nGenerating sample ERA 835 files...")
    era_files = generate_all_835s(records, str(eobs_dir))

    print(f"\n{'='*60}")
    print(f"Sample data generated:")
    print(f"  OCMRI Excel: {excel_path}")
    print(f"  ERA 835 files: {len(era_files)} files in {eobs_dir}")
    print(f"  Total billing records: {len(records)}")
    print(f"\nTo load into the system:")
    print(f"  1. Upload OCMRI_sample.xlsx via /import page")
    print(f"  2. Upload ERA files via /import 835 tab")
    print(f"  3. Or use the API:")
    print(f"     curl -X POST http://localhost:8000/api/import/excel \\")
    print(f"       -F 'file=@data/excel/OCMRI_sample.xlsx'")
    print(f"     curl -X POST http://localhost:8000/api/import/scan-eobs")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
