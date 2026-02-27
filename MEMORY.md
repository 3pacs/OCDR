# OCDR — Project Memory

> Curated long-term context. Under 100 lines. Updated each session.
> Last updated: 2026-02-27

---

## Environment

- **OS:** Windows (primary), Linux container (Claude Code sandbox)
- **Local path:** C:\OCDR (repo root on Windows)
- **X:\ drive:** Mapped network share — holds Topaz legacy data
- **Topaz path:** X:\tpzservr\ (main data files)
- **Database:** ocdr.db (~7MB, ~10K+ records, SQLite)
- **Server:** Flask dev server on localhost:5000
- **LLM:** Ollama at localhost:11434 (planned, not active yet)

## Topaz Legacy System

- **What:** Bespoke DOS-era software from the 1980s, name "Topaz"
- **Storage:** Flat text files, NOT a real database
- **Location:** X:\tpzservr\ (giant files, mostly raw data)
- **File extensions:** NONE — files have no .txt/.dat/.csv extension, just bare names
- **Format:** Unknown — needs reverse-engineering. Likely fixed-width or custom delimiters
- **Encoding:** Probably CP437 or ASCII (DOS era)
- **Goal:** Extract ALL data to phase out Topaz entirely
- **Status:** BLOCKED — X:\ not accessible from sandbox. Need user to copy sample files to topaz_samples/
- **Next step:** User provides dir listing or sample files from X:\tpzservr\

## Facility Profile

- **Type:** Imaging center
- **Modalities:** CT, HMRI, PET, BONE, OPEN, DX, GH
- **Key carriers:** M/M, CALOPTIMA, FAMILY, INS, W/C, SELF PAY
- **Billing volume:** ~10K+ records in current system

## Current Sprint Status

- Sprints 1-10: COMPLETE (core billing, ERA, matching, smart matching)
- Sprint 11: 15% (lookup tables exist, migrations not initialized)
- Sprint 12: 40% (8 issues fixed this session, see below)
- Sprint 13: 70% (query engine + chat working, Ollama untested)
- Sprint 14: 20% (scaffolded, not wired to UI)
- Sprint 15: 5% (Flask-Login wired, User model exists, but auth not enforced)

## Issues Fixed (2026-02-27 session 2)

- Registered analysis_bp blueprint (fixed 404 on /api/analysis/post-import)
- Fixed LIKE wildcard escape in physician_statements.py and api.py search endpoints
- Fixed EraPayment.to_dict() N+1 query (COUNT query instead of loading all claim_lines)
- Fixed ERA parser rsplit path handling → os.path.basename()
- Capped per_page to 500 on all pagination endpoints
- Added file extension validation on ERA, Excel, and CSV upload endpoints
- Improved denial queue: DB-level pagination for age/amount sorts
- Replaced all deprecated Query.get() with db.session.get()
- All tests: 318 passed, 0 failed, 0 warnings

## Key Decisions

- 2026-02-27: Decided to add MEMORY.md, LEARNINGS.md, autonomy rules to project
- 2026-02-27: Topaz data extraction identified as major upcoming project
- 2026-02-27: Created topaz_importer.py scaffold in import_engine/
- 2026-02-27: Fixed 8 ISSUES.md items (Sprint 12 work)

## Active Blockers

- X:\ drive not accessible from Claude Code sandbox — need sample files copied locally
- No Topaz documentation exists — format must be reverse-engineered from raw data
- Authentication not enforced (Flask-Login wired but no @login_required on routes)
