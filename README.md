# OCDR — Billing Reconciliation System

Healthcare billing analytics and reconciliation platform for medical imaging operations. Imports claims from Excel/CSV/835 EDI files, reconciles payments, detects denials and underpayments, tracks filing deadlines, and provides revenue analytics dashboards.

**100% local** — zero cloud, zero internet, zero external APIs. HIPAA-compliant.

## Stack

- **Backend:** Python 3.11+ / Flask 3.x / SQLAlchemy / SQLite 3
- **Frontend:** Bootstrap 5.3 / Chart.js 4.x / Jinja2
- **Data:** X12 835 EDI parser, Excel (openpyxl), CSV (pandas), PDF (pdfplumber), OCR (Tesseract 5.x)
- **Matching:** rapidfuzz for fuzzy patient name matching

## Quick Start

```bash
# 1. Clone and set up environment
git clone <repo-url> && cd OCDR
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env as needed

# 4. Initialize database and seed data
flask db upgrade
python seed_data.py

# 5. Run
flask run
# Open http://localhost:5000
```

## Key Features

| Feature | Description |
|---------|-------------|
| Excel Import | Parse OCMRI.xlsx (19,936+ billing records) |
| 835 ERA Parser | Parse X12-835 Electronic Remittance Advice files |
| Auto-Match | Fuzzy match ERA claims to billing records (85%+ confidence) |
| Denial Tracking | Queue and prioritize 722+ denied claims for appeal |
| Underpayment Detection | Flag claims paid below expected rates ($913K gap) |
| Filing Deadlines | Track timely filing limits per payer (90–365 days) |
| Secondary Follow-Up | Identify missing secondary insurance payments ($643K) |
| Payer Analytics | Monitor carrier revenue trends and contract issues |
| Physician Analytics | Revenue by referring physician, volume alerts |
| PSMA PET Tracking | Dedicated dashboard for PSMA PET scans ($8,046 avg) |
| Backup & Recovery | Automated backups with SHA256 integrity and retention policy |

## Project Structure

```
app/                    Flask application (Blueprint-based)
├── import_engine/      Excel, CSV, PDF, OCR importers
├── parser/             X12 835 ERA parser
├── matching/           Fuzzy matching engine
├── revenue/            Denials, underpayments, deadlines, duplicates
├── analytics/          Payer, physician, PSMA, Gado analytics
├── core/               Payment matching/reconciliation
├── monitor/            Folder watcher (auto-ingest)
├── export/             CSV export bridge for Excel
├── infra/              Backup manager
└── ui/                 Dashboard routes
templates/              Jinja2 HTML templates
static/                 CSS + JS assets
tests/                  pytest test suite
migrations/             Alembic database migrations
```

## Testing

```bash
pytest tests/                    # Run all tests
pytest tests/ -v                 # Verbose output
pytest tests/test_835_parser.py  # Single test file
```

## Documentation

- **[BUILD_SPEC.md](BUILD_SPEC.md)** — Complete technical specification (features, DB schema, API routes, business rules)
- **[CLAUDE.md](CLAUDE.md)** — AI agent guide (conventions, architecture, pitfalls)

## Security

- All data stays local — no cloud, no external APIs, no telemetry
- Never commit PHI (patient data, OCMRI.xlsx) to version control
- Optional SQLCipher encryption for the database
- Credentials stored in `.env` (gitignored)

## License

Private — not for distribution.
