# OCDR — Project Memory

> Curated long-term context. Under 100 lines. Updated each session.
> Last updated: 2026-03-19

---

## Environment

- **OS:** Windows 11 Home
- **Local path:** C:\OCDR (Flask app, repo root)
- **Docker path:** C:\Users\anikd\ocdr (React + FastAPI + Postgres)
- **X:\ drive:** Mapped network share — holds Topaz legacy data
- **Database:** ocdr.db (~7MB, ~10K+ records, SQLite, WAL mode)
- **Flask server:** localhost:5000 (`python run.py`)
- **Docker stack:** localhost:8000 (backend), localhost:3000 (frontend), localhost:5432 (postgres)
- **LLM:** Ollama at localhost:11434 (planned, not active yet)

## Two Apps, Same Data

- Flask (C:\OCDR) and Docker (C:\Users\anikd\ocdr) share the same data
- Docker is source of truth — more work has been put into it
- Changes must be applied to both apps simultaneously
- Match engine, pipeline analysis, carrier normalization are synced

## Facility Profile

- **Type:** Imaging center
- **Modalities:** CT, HMRI, PET, BONE, OPEN, DX, US, MAMMO, DEXA, FLUORO
- **Key carriers:** M/M, CALOPTIMA, FAMILY, INS, W/C, SELF PAY, ONE CALL, C2C
- **Billing volume:** ~10K+ records

## Match Engine (Updated 2026-03-19)

- 14-pass progressive matching (ported from Docker)
- Passes: Topaz ID -> Patient ID -> Exact -> Strong fuzzy -> Medium -> Weak -> Date windows -> Amount -> Name+modality -> Name+amount -> Name only -> Broad fuzzy -> Supply linking -> Auto-create
- Order-independent name normalization (sorted tokens)
- ICD-10 diagnosis -> modality scoring
- 400+ CPT codes + HCPCS supply code mappings
- Many-to-one: multiple ERA claims can link to same billing record

## Current Sprint Status

- Sprints 1-10: COMPLETE
- Sprint 11: 15% (lookup tables exist, migrations not initialized)
- Sprint 12: 90% (perf/security fixes done)
- Sprint 13: 95% (query engine + chat UI + AI logs + PHI encryption)
- Sprint 14: 90% (appeal letters, aging report, claim lifecycle)
- Sprint 15: 90% (auth, rate limiting, auto-backup, health check)

## Key Decisions

- 2026-03-19: Match engine fully ported from Docker (14-pass progressive)
- 2026-03-19: Payer compliance uses modality-aware comparison (not flat average)
- 2026-03-19: W/C, ONE CALL, C2C excluded from underpayment analysis
- 2026-03-19: Daily session logs in memory/YYYY-MM-DD.md
- 2026-02-28: Auth gated by AUTH_ENFORCEMENT env var
- 2026-02-28: Rate limiting disabled in TESTING mode

## Active Blockers

- Topaz sample files staged but NOT committed/pushed
- Sprint 11 (Flask-Migrate) not initialized
