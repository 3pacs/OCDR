#!/usr/bin/env python
"""OCDR Management CLI — Easy data import and analysis.

Usage:
    python manage.py import-excel  /path/to/OCMRI.xlsx
    python manage.py import-835    /path/to/file.835
    python manage.py import-folder /path/to/folder/
    python manage.py seed
    python manage.py analyze
    python manage.py vendor-setup  officeally
    python manage.py vendor-download officeally
    python manage.py runserver
"""
import os
import sys
import glob
import argparse


def cmd_seed(args):
    """Seed payers, fee schedule, and denial codes into the database."""
    from seed_data import seed
    seed()


def cmd_import_excel(args):
    """Import an Excel file (OCMRI.xlsx format)."""
    from app import create_app
    from app.import_engine.excel_importer import import_excel_file

    filepath = args.file
    if not os.path.exists(filepath):
        print(f'Error: File not found: {filepath}')
        sys.exit(1)

    app = create_app()
    with app.app_context():
        print(f'Importing Excel file: {filepath}')
        result = import_excel_file(filepath)
        print(f'  Imported: {result["imported"]}')
        print(f'  Skipped:  {result["skipped"]}')
        print(f'  Errors:   {len(result["errors"])}')
        print(f'  Duration: {result["duration_ms"]}ms')
        if result['errors']:
            print(f'\n  First 10 errors:')
            for e in result['errors'][:10]:
                print(f'    - {e}')


def cmd_import_835(args):
    """Import a single 835/EDI file."""
    from app import create_app
    from app.parser.era_835_parser import parse_835_file

    filepath = args.file
    if not os.path.exists(filepath):
        print(f'Error: File not found: {filepath}')
        sys.exit(1)

    app = create_app()
    with app.app_context():
        print(f'Parsing 835 file: {filepath}')
        result = parse_835_file(filepath)
        print(f'  Filename:       {result["filename"]}')
        print(f'  Claims found:   {result["claims_found"]}')
        print(f'  Payment amount: ${result["payment_amount"]:,.2f}')
        print(f'  ERA Payment ID: {result["era_payment_id"]}')


def cmd_import_folder(args):
    """Import all supported files from a folder."""
    from app import create_app
    from app.import_engine.excel_importer import import_excel_file
    from app.parser.era_835_parser import parse_835_file

    folder = args.folder
    if not os.path.isdir(folder):
        print(f'Error: Folder not found: {folder}')
        sys.exit(1)

    app = create_app()
    with app.app_context():
        # Find all supported files
        patterns = {
            'excel': ['*.xlsx', '*.xls'],
            '835': ['*.835', '*.edi'],
        }

        total_imported = 0
        total_claims = 0
        total_errors = 0

        # Import Excel files
        for pattern in patterns['excel']:
            for filepath in glob.glob(os.path.join(folder, pattern)):
                print(f'  [EXCEL] {os.path.basename(filepath)}...')
                try:
                    result = import_excel_file(filepath)
                    total_imported += result['imported']
                    total_errors += len(result['errors'])
                    print(f'    -> Imported {result["imported"]}, skipped {result["skipped"]}')
                except Exception as e:
                    print(f'    -> ERROR: {e}')
                    total_errors += 1

        # Import 835 files
        for pattern in patterns['835']:
            for filepath in glob.glob(os.path.join(folder, pattern)):
                print(f'  [835]   {os.path.basename(filepath)}...')
                try:
                    result = parse_835_file(filepath)
                    total_claims += result['claims_found']
                    print(f'    -> {result["claims_found"]} claims, ${result["payment_amount"]:,.2f}')
                except Exception as e:
                    print(f'    -> ERROR: {e}')
                    total_errors += 1

        print(f'\nSummary:')
        print(f'  Records imported: {total_imported}')
        print(f'  ERA claims found: {total_claims}')
        print(f'  Errors:           {total_errors}')


def cmd_analyze(args):
    """Run post-import analysis and print recommendations."""
    from app import create_app
    from app.models import db, BillingRecord, EraPayment, EraClaimLine, Payer, FeeSchedule
    from app.revenue.underpayment_detector import get_expected_rate
    from app.revenue.filing_deadlines import categorize_deadline
    from datetime import date

    app = create_app()
    with app.app_context():
        total = BillingRecord.query.count()
        if total == 0:
            print('No data imported yet. Run one of:')
            print('  python manage.py import-excel /path/to/OCMRI.xlsx')
            print('  python manage.py import-835 /path/to/file.835')
            print('  python manage.py import-folder /path/to/folder/')
            return

        unpaid = BillingRecord.query.filter(BillingRecord.total_payment == 0).count()
        total_revenue = db.session.query(db.func.sum(BillingRecord.total_payment)).scalar() or 0
        era_count = EraPayment.query.count()
        era_claims = EraClaimLine.query.count()

        # Underpayment analysis
        underpaid = 0
        underpaid_variance = 0.0
        paid_records = BillingRecord.query.filter(BillingRecord.total_payment > 0).all()
        for r in paid_records:
            expected, threshold = get_expected_rate(
                r.modality, r.insurance_carrier, r.gado_used, r.is_psma
            )
            if expected and r.total_payment < (expected * threshold):
                underpaid += 1
                underpaid_variance += float(r.total_payment) - float(expected)

        # Filing deadline analysis
        today = date.today()
        alerts = BillingRecord.query.filter(
            BillingRecord.total_payment == 0,
            BillingRecord.appeal_deadline.isnot(None),
        ).all()
        past_deadline = sum(1 for a in alerts if categorize_deadline(a.appeal_deadline, today) == 'PAST_DEADLINE')
        warning = sum(1 for a in alerts if categorize_deadline(a.appeal_deadline, today) == 'WARNING_30DAY')

        # Carrier breakdown
        carrier_stats = db.session.query(
            BillingRecord.insurance_carrier,
            db.func.count(BillingRecord.id),
            db.func.sum(BillingRecord.total_payment),
        ).group_by(BillingRecord.insurance_carrier).order_by(
            db.func.sum(BillingRecord.total_payment).desc()
        ).all()

        # Print analysis
        print('=' * 60)
        print('  OCDR POST-IMPORT ANALYSIS')
        print('=' * 60)
        print(f'\n  Total billing records: {total:,}')
        print(f'  Total revenue:        ${total_revenue:,.2f}')
        print(f'  Unpaid claims ($0):   {unpaid:,}')
        print(f'  Underpaid claims:     {underpaid:,}  (${abs(underpaid_variance):,.2f} gap)')
        print(f'  ERA payments loaded:  {era_count:,}')
        print(f'  ERA claim lines:      {era_claims:,}')
        print(f'  Filing past deadline: {past_deadline}')
        print(f'  Filing 30-day warn:   {warning}')

        print(f'\n  REVENUE BY CARRIER (Top 10):')
        print(f'  {"Carrier":<15} {"Claims":>8} {"Revenue":>14} {"Avg":>10}')
        print(f'  {"-"*15} {"-"*8} {"-"*14} {"-"*10}')
        for carrier, count, revenue in carrier_stats[:10]:
            rev = float(revenue or 0)
            avg = rev / count if count > 0 else 0
            print(f'  {carrier:<15} {count:>8,} ${rev:>12,.2f} ${avg:>8,.2f}')

        # Recommendations
        print(f'\n  RECOMMENDED NEXT STEPS:')
        steps = []
        if unpaid > 0:
            steps.append(f'Review {unpaid:,} unpaid claims — visit /api/filing-deadlines/alerts')
        if past_deadline > 0:
            steps.append(f'URGENT: {past_deadline} claims past filing deadline — revenue unrecoverable if not acted on')
        if warning > 0:
            steps.append(f'{warning} claims approaching deadline within 30 days')
        if underpaid > 0:
            steps.append(f'{underpaid:,} underpaid claims (${abs(underpaid_variance):,.2f} gap) — visit /api/underpayments/summary')
        if era_count == 0:
            steps.append('Import 835 ERA files to enable payment matching and denial tracking')
        if era_count > 0 and era_claims > 0:
            steps.append(f'Run auto-matching to link {era_claims} ERA claims to billing records (Sprint 2)')

        for i, step in enumerate(steps, 1):
            print(f'  {i}. {step}')

        if not steps:
            print('  All clear! Data looks good.')

        print()


def cmd_vendor_setup(args):
    """Set up vendor credentials."""
    from app.vendor.credential_store import CredentialStore
    import getpass

    vendor = args.vendor
    print(f'Setting up credentials for: {vendor}')
    print('Credentials are encrypted and stored locally.')
    print()

    master = getpass.getpass('Master password (for encryption): ')
    username = input(f'{vendor} username: ')
    password = getpass.getpass(f'{vendor} password: ')

    store = CredentialStore()
    store.unlock(master)
    store.set(vendor, username, password)
    store.save()
    print(f'\nCredentials for {vendor} saved (encrypted).')


def cmd_vendor_download(args):
    """Download files from a vendor portal."""
    from app.vendor.credential_store import CredentialStore
    import getpass

    vendor = args.vendor
    master = getpass.getpass('Master password: ')

    store = CredentialStore()
    store.unlock(master)
    creds = store.get(vendor)
    if not creds:
        print(f'No credentials stored for {vendor}. Run: python manage.py vendor-setup {vendor}')
        sys.exit(1)

    connectors = {
        'officeally': 'app.vendor.office_ally.OfficeAllyConnector',
        'purview': 'app.vendor.purview.PurviewConnector',
    }

    if vendor not in connectors:
        print(f'Unknown vendor: {vendor}. Available: {", ".join(connectors.keys())}')
        sys.exit(1)

    module_path, class_name = connectors[vendor].rsplit('.', 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    download_dir = os.path.join(os.getcwd(), 'import', 'downloads')
    connector = cls(download_dir=download_dir, headless=not args.visible)

    print(f'Downloading from {vendor}...')
    result = connector.run(
        username=creds['username'],
        password=creds['password'],
    )

    if result['errors']:
        print(f'Errors: {result["errors"]}')
    print(f'Downloaded {len(result["files"])} files:')
    for f in result['files']:
        print(f'  - {f["filename"]} ({f["size"]} bytes)')


def cmd_runserver(args):
    """Start the Flask development server."""
    from app import create_app
    app = create_app()
    app.run(host=args.host, port=args.port, debug=True)


def main():
    parser = argparse.ArgumentParser(
        description='OCDR Management CLI — Import data and run analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python manage.py seed                              # Seed payers & fee schedule
  python manage.py import-excel OCMRI.xlsx           # Import Excel file
  python manage.py import-835 payment.835            # Import 835 ERA file
  python manage.py import-folder ./import/           # Import all files in folder
  python manage.py analyze                           # Run analysis on imported data
  python manage.py vendor-setup officeally           # Store vendor credentials
  python manage.py vendor-download officeally        # Download from vendor
  python manage.py runserver                         # Start web server
        """
    )
    sub = parser.add_subparsers(dest='command', help='Available commands')

    sub.add_parser('seed', help='Seed payers, fee schedule, and denial codes')

    p = sub.add_parser('import-excel', help='Import an Excel file')
    p.add_argument('file', help='Path to .xlsx file')

    p = sub.add_parser('import-835', help='Import an 835/EDI file')
    p.add_argument('file', help='Path to .835 or .edi file')

    p = sub.add_parser('import-folder', help='Import all files from a folder')
    p.add_argument('folder', help='Path to folder containing files')

    sub.add_parser('analyze', help='Run post-import analysis')

    p = sub.add_parser('vendor-setup', help='Store vendor portal credentials')
    p.add_argument('vendor', help='Vendor name (officeally, purview)')

    p = sub.add_parser('vendor-download', help='Download files from vendor portal')
    p.add_argument('vendor', help='Vendor name (officeally, purview)')
    p.add_argument('--visible', action='store_true', help='Show browser window')

    p = sub.add_parser('runserver', help='Start the development server')
    p.add_argument('--host', default='0.0.0.0', help='Host (default: 0.0.0.0)')
    p.add_argument('--port', type=int, default=5000, help='Port (default: 5000)')

    args = parser.parse_args()

    commands = {
        'seed': cmd_seed,
        'import-excel': cmd_import_excel,
        'import-835': cmd_import_835,
        'import-folder': cmd_import_folder,
        'analyze': cmd_analyze,
        'vendor-setup': cmd_vendor_setup,
        'vendor-download': cmd_vendor_download,
        'runserver': cmd_runserver,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
