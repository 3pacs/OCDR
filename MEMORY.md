# OCDR — Project Memory

> Curated long-term context. Under 100 lines. Updated each session.
> Last updated: 2026-02-28

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

- **What:** Bespoke .NET application (originally DOS-era, now .NET), name "Topaz"
- **Platform:** .NET (Windows), data storage local on X:\ drive
- **Storage:** Flat text files, NOT a real database
- **Location:** X:\tpzservr\ (giant files, mostly raw data)
- **File extensions:** NONE — files have no .txt/.dat/.csv extension, just bare names
- **File naming:** Monthly=MON[12]YYYY (e.g. JAN12025), Lookups=patnt/doclst/inslst/cptlst/dxtlst/reflst
- **Format:** Unknown — needs reverse-engineering. Likely fixed-width or custom delimiters
- **Encoding:** Probably CP437 or ASCII (DOS era)
- **Goal:** Extract ALL data to phase out Topaz entirely
- **Status:** File classifier built, parser scaffold ready — WAITING for files to be git committed/pushed from Windows
- **Next step:** User must `git commit -m "Add Topaz files" && git push` from C:\OCDR on Windows

## Facility Profile

- **Type:** Imaging center
- **Modalities:** CT, HMRI, PET, BONE, OPEN, DX, GH
- **Key carriers:** M/M, CALOPTIMA, FAMILY, INS, W/C, SELF PAY
- **Billing volume:** ~10K+ records in current system

## Current Sprint Status

- Sprints 1-10: COMPLETE (core billing, ERA, matching, smart matching)
- Sprint 11: 15% (lookup tables exist, migrations not initialized)
- Sprint 12: 90% (all perf/security fixes done, only benchmark tests remain)
- Sprint 13: 95% (query engine + chat UI + AI logs + PHI encryption all working)
- Sprint 14: 90% (appeal letters, aging report, claim lifecycle all implemented)
- Sprint 15: 90% (auth enforcement, rate limiting, auto-backup, health check DONE; deployment script pending)

## Work Done (2026-02-28)

- Enhanced topaz_importer.py with file classification system (20 categories)
- Added 3 Topaz API endpoints: /api/topaz/{summary,analyze,file/<name>}
- Built in-process rate limiter (app/infra/rate_limiter.py) — no external deps
- Added @auth_required on all page routes, @admin_required on admin page
- Added AUTH_ENFORCEMENT config flag (off by default, set env var to enable)
- Added auto-backup on startup (runs if last backup >24h old)
- Enhanced /api/health with journal_mode, auth_enforced, disk info, table/ERA/schedule counts
- Added backup verify endpoint: /api/backup/verify/<filename>
- All tests: 399 passed, 0 failed

## Key Decisions

- 2026-02-27: Decided to add MEMORY.md, LEARNINGS.md, autonomy rules to project
- 2026-02-27: Topaz data extraction identified as major upcoming project
- 2026-02-27: Created topaz_importer.py scaffold in import_engine/
- 2026-02-27: Fixed 8 ISSUES.md items (Sprint 12 work)
- 2026-02-28: Auth enforcement gated by AUTH_ENFORCEMENT env var (safe rollout)
- 2026-02-28: Rate limiting disabled in TESTING mode to avoid test interference
- 2026-02-28: No external dependency for rate limiting — pure Python sliding window

## Active Blockers

- Topaz sample files staged but NOT committed/pushed from Windows. Need: git commit && git push
- No Topaz documentation exists — format must be reverse-engineered from raw data
- Sprint 11 (Flask-Migrate) not initialized yet
