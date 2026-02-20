# OCDR — Medical Imaging Practice Management System

Full end-to-end practice management system for medical imaging centers (MRI, PET/CT, Bone Scans).

## Architecture

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11) |
| Database | PostgreSQL 16 via SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Task Queue | Celery + Redis |
| Document OCR | pdfplumber + pytesseract |
| Fuzzy Matching | rapidfuzz |
| Auth | JWT (python-jose) + bcrypt |
| Encryption | Fernet symmetric (cryptography) |
| External | Microsoft Purview, Office Ally |

## Quick Start

### Option 1 — Docker (recommended)

```bash
cp .env.example .env
# Edit .env: set ENCRYPTION_KEY, JWT_SECRET_KEY, APP_SECRET_KEY
docker compose up --build
```

Access:
- API docs: http://localhost:8000/docs
- Celery monitor: http://localhost:5555

### Option 2 — Local development

```bash
# Prerequisites: Python 3.11+, PostgreSQL, Redis, tesseract-ocr
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env   # edit values
alembic upgrade head
python scripts/seed_data.py  # load test data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Default Login Credentials (seed data)

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `Admin123!` |
| Biller | `biller1` | `Biller123!` |
| Front Desk | `frontdesk` | `Desk123!` |
| Read Only | `readonly` | `Read123!` |

## Project Structure

```
OCDR/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app factory
│   │   ├── config.py             # Pydantic settings
│   │   ├── database.py           # Async SQLAlchemy engine
│   │   ├── models/               # SQLAlchemy ORM models (15 tables)
│   │   ├── schemas/              # Pydantic request/response schemas
│   │   ├── api/v1/endpoints/     # CRUD endpoints (auth, patients, claims, etc.)
│   │   ├── core/                 # Security, encryption, audit logging
│   │   ├── matching/             # 4-pass payment matching engine
│   │   ├── ingestion/            # PDF schedule + EOB + payment parsers
│   │   ├── integrations/         # Office Ally + Purview clients
│   │   └── tasks/                # Celery tasks + beat schedule
│   ├── alembic/                  # Migrations (001_initial_schema.py)
│   ├── tests/                    # pytest unit + integration tests
│   └── scripts/seed_data.py      # Sample data loader
├── data/
│   ├── schedules/processed/      # Schedule PDFs (watched folder)
│   ├── eobs/processed/           # EOB PDFs (watched folder)
│   └── payments/processed/       # Check images (watched folder)
├── docker-compose.yml
├── .env.example
└── requirements.txt
```

## Database Schema (15 tables)

```
users ............. auth and RBAC (admin/biller/front_desk/read_only)
patients .......... core demographics (SSN encrypted at rest)
  insurance ........ primary/secondary payer info + eligibility
  appointments ..... schedule (MRI/PET/CT/Bone)
    scans .......... DICOM study + CPT codes + charges
      claims ....... billing claim + denial tracking
        payments ... insurance/patient payments
        reconciliation .. expected vs actual + variance
eobs .............. EOB documents (PDF/ERA/EFT)
  eob_line_items ... per-claim lines + adjustment codes
audit_logs ........ every INSERT/UPDATE/DELETE (HIPAA)
corrections ....... staff corrections → training data
payer_templates ... auto-learned extraction patterns
business_rules .... expected payment calculation rules
denial_patterns ... aggregated denial analytics
api_call_logs ..... every external API call logged
```

## API Endpoints (Steps 1 & 2)

| Resource | Methods | Notes |
|---|---|---|
| `POST /api/v1/auth/token` | Login | OAuth2 password flow |
| `GET /api/v1/auth/me` | Current user | |
| `/api/v1/patients/` | CRUD + fuzzy search | SSN encrypted |
| `/api/v1/insurance/` | CRUD | Primary/secondary |
| `/api/v1/appointments/` | CRUD + filters | Today's list |
| `/api/v1/scans/` | CRUD | Per-appointment |
| `/api/v1/claims/` | CRUD + AR aging | Denial tracking |
| `/api/v1/payments/` | CRUD + post | Manual posting |
| `/api/v1/eobs/` | CRUD + review queue | Line-item approve/reject |
| `/api/v1/reconciliation/` | CRUD | Auto-flags variances |
| `/api/v1/reports/*` | Dashboard, revenue, denial, AR | |

Full OpenAPI docs at `/docs`.

## Running Tests

```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

## Implementation Roadmap

- [x] Step 1: Database schema + Alembic migrations (15 tables)
- [x] Step 2: FastAPI CRUD API with full OpenAPI docs
- [ ] Step 3: Document watcher + ingestion pipeline (schedules, EOBs, payments)
- [ ] Step 4: Matching & reconciliation engine (full)
- [ ] Step 5: Office Ally integration (837P, 835 ERA, eligibility)
- [ ] Step 6: Microsoft Purview integration (PHI asset registration)
- [ ] Step 7: Web UI dashboard (React/Streamlit)
- [ ] Step 8: Learning/feedback layer (payer templates, denial patterns)
- [ ] Step 9: Reports with Excel/PDF export
- [ ] Step 10: Security hardening + field-level RBAC
- [ ] Step 11: Docker packaging + production deployment docs

## Security

- All PHI (SSN, etc.) encrypted at rest using Fernet symmetric encryption
- JWT authentication with access + refresh tokens
- Role-based access control: Admin, Biller, Front Desk, Read-Only
- Full audit log of every data change for HIPAA compliance
- Session timeout enforced via JWT expiry (configurable, default 30 min)
- Secrets in `.env` only — never hardcoded
