#!/usr/bin/env python3
"""
OCDR Billing Reconciliation System — CLI entry point.

Usage:
  python main.py import-candelis --input paste.txt --output staging.xlsx
  python main.py import-schedule --input schedule.csv --output staging.xlsx
  python main.py import-835 --input ./import/835/ --output era_parsed.xlsx
  python main.py merge-purview --input physicians.csv --staging staging.xlsx
  python main.py merge-schedule --schedule schedule.csv --candelis candelis.txt --output merged.xlsx
  python main.py reconcile --ocmri OCMRI.xlsx --era-folder ./import/835/ --output reconciliation.xlsx
"""

import argparse
import sys
from pathlib import Path

from ocdr.config import (
    OCMRI_PATH, RECONCILIATION_PATH, EDI_835_DIR,
    EXPORT_DIR, DATA_DIR,
)


def cmd_import_candelis(args):
    """Import Candelis PACS paste data."""
    from ocdr.candelis_importer import parse_candelis_file
    from ocdr.excel_writer import write_import_staging

    records = parse_candelis_file(args.input)
    output = args.output or str(EXPORT_DIR / "candelis_staging.xlsx")
    write_import_staging(output, records)
    print(f"Imported {len(records)} records from Candelis → {output}")


def cmd_import_schedule(args):
    """Import schedule entry CSV."""
    from ocdr.schedule_importer import parse_schedule_file
    from ocdr.excel_writer import write_import_staging

    records = parse_schedule_file(args.input)
    output = args.output or str(EXPORT_DIR / "schedule_staging.xlsx")
    write_import_staging(output, records, sheet_name="Schedule")
    print(f"Imported {len(records)} records from schedule → {output}")


def cmd_import_835(args):
    """Parse 835 EDI files."""
    from ocdr.era_835_parser import parse_835_folder, parse_835_file
    from ocdr.excel_writer import write_era_output

    input_path = Path(args.input)
    if input_path.is_dir():
        parsed = parse_835_folder(input_path)
    else:
        parsed = [parse_835_file(input_path)]

    output = args.output or str(EXPORT_DIR / "era_parsed.xlsx")
    write_era_output(output, parsed)

    total_claims = sum(len(p.get("claims", [])) for p in parsed)
    print(f"Parsed {len(parsed)} 835 files, {total_claims} claims → {output}")


def cmd_merge_purview(args):
    """Merge physician data from Purview reference."""
    from ocdr.purview_importer import (
        load_physician_reference, merge_physicians,
        save_physician_reference, discover_new_physicians,
    )
    from ocdr.excel_reader import read_ocmri
    from ocdr.excel_writer import write_import_staging

    physician_map = load_physician_reference(args.input)
    print(f"Loaded {len(physician_map)} physician references.")

    # Read staging workbook or OCMRI
    staging_path = args.staging or str(OCMRI_PATH)
    if staging_path.endswith(".xlsx"):
        records = read_ocmri(staging_path)
    else:
        from ocdr.candelis_importer import parse_candelis_file
        records = parse_candelis_file(staging_path)

    records = merge_physicians(records, physician_map)

    # Discover and save new physician references
    new_entries = discover_new_physicians(records, physician_map)
    if new_entries:
        physician_map.update(new_entries)
        save_physician_reference(args.input, physician_map)
        print(f"Discovered {len(new_entries)} new physician references.")

    output = args.output or str(EXPORT_DIR / "merged_staging.xlsx")
    write_import_staging(output, records)
    print(f"Merged physicians for {len(records)} records → {output}")


def cmd_merge_schedule(args):
    """Merge schedule CSV with Candelis data."""
    from ocdr.schedule_importer import parse_schedule_file, merge_schedule_with_candelis
    from ocdr.candelis_importer import parse_candelis_file
    from ocdr.excel_writer import write_import_staging

    schedule_records = parse_schedule_file(args.schedule)
    candelis_records = parse_candelis_file(args.candelis)
    merged = merge_schedule_with_candelis(schedule_records, candelis_records)

    output = args.output or str(EXPORT_DIR / "merged_staging.xlsx")
    write_import_staging(output, merged)
    print(f"Merged {len(schedule_records)} schedule + {len(candelis_records)} "
          f"Candelis → {len(merged)} records → {output}")


def cmd_reconcile(args):
    """Generate the reconciliation workbook."""
    from ocdr.excel_reader import read_ocmri
    from ocdr.era_835_parser import parse_835_folder, flatten_claims, match_835_to_billing
    from ocdr.reconciliation import generate_reconciliation

    # Read billing records
    ocmri_path = args.ocmri or str(OCMRI_PATH)
    billing_records = read_ocmri(ocmri_path)
    print(f"Read {len(billing_records)} billing records from {ocmri_path}")

    # Parse 835 files
    era_folder = args.era_folder or str(EDI_835_DIR)
    era_data = []
    match_results = None

    if Path(era_folder).exists():
        era_data = parse_835_folder(era_folder)
        total_claims = sum(len(p.get("claims", [])) for p in era_data)
        print(f"Parsed {len(era_data)} 835 files, {total_claims} claims")

        # Match claims to billing
        if billing_records and era_data:
            flat_claims = flatten_claims(era_data)
            match_results = match_835_to_billing(flat_claims, billing_records)
            auto = sum(1 for m in match_results if m["status"] == "AUTO_ACCEPT")
            review = sum(1 for m in match_results if m["status"] == "REVIEW")
            unmatched = sum(1 for m in match_results if m["status"] == "UNMATCHED")
            print(f"Matching: {auto} auto-accepted, {review} review, "
                  f"{unmatched} unmatched")
    else:
        print(f"No 835 folder found at {era_folder} — skipping ERA data.")

    # Generate reconciliation
    output = args.output or str(RECONCILIATION_PATH)
    generate_reconciliation(billing_records, era_data, match_results, output)
    print(f"Reconciliation workbook → {output}")


def main():
    parser = argparse.ArgumentParser(
        prog="ocdr",
        description="OCDR Billing Reconciliation System — Excel-first CLI tools",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── import-candelis ──
    p = subparsers.add_parser("import-candelis",
                               help="Import Candelis PACS paste data")
    p.add_argument("--input", "-i", required=True,
                   help="Path to saved Candelis paste .txt file")
    p.add_argument("--output", "-o",
                   help="Output staging .xlsx path")
    p.set_defaults(func=cmd_import_candelis)

    # ── import-schedule ──
    p = subparsers.add_parser("import-schedule",
                               help="Import schedule entry CSV")
    p.add_argument("--input", "-i", required=True,
                   help="Path to schedule entry CSV")
    p.add_argument("--output", "-o",
                   help="Output staging .xlsx path")
    p.set_defaults(func=cmd_import_schedule)

    # ── import-835 ──
    p = subparsers.add_parser("import-835",
                               help="Parse 835 EDI files")
    p.add_argument("--input", "-i", required=True,
                   help="Path to 835 file or folder")
    p.add_argument("--output", "-o",
                   help="Output .xlsx path for parsed ERA data")
    p.set_defaults(func=cmd_import_835)

    # ── merge-purview ──
    p = subparsers.add_parser("merge-purview",
                               help="Merge physician data from Purview reference CSV")
    p.add_argument("--input", "-i", required=True,
                   help="Path to physician reference CSV")
    p.add_argument("--staging", "-s",
                   help="Path to staging .xlsx or Candelis .txt to merge into")
    p.add_argument("--output", "-o",
                   help="Output merged staging .xlsx path")
    p.set_defaults(func=cmd_merge_purview)

    # ── merge-schedule ──
    p = subparsers.add_parser("merge-schedule",
                               help="Merge schedule CSV with Candelis data")
    p.add_argument("--schedule", required=True,
                   help="Path to schedule entry CSV")
    p.add_argument("--candelis", required=True,
                   help="Path to Candelis paste .txt file")
    p.add_argument("--output", "-o",
                   help="Output merged staging .xlsx path")
    p.set_defaults(func=cmd_merge_schedule)

    # ── reconcile ──
    p = subparsers.add_parser("reconcile",
                               help="Generate reconciliation workbook")
    p.add_argument("--ocmri",
                   help="Path to OCMRI.xlsx (read-only)")
    p.add_argument("--era-folder",
                   help="Path to folder containing 835 EDI files")
    p.add_argument("--output", "-o",
                   help="Output reconciliation .xlsx path")
    p.set_defaults(func=cmd_reconcile)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Ensure output directories exist
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    args.func(args)


if __name__ == "__main__":
    main()
