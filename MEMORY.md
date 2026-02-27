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
- Sprint 11: PLANNED (schema hardening)
- Sprint 12: PLANNED (performance/security)
- Sprint 13: PLANNED (LLM integration)
- Sprint 14: PLANNED (advanced workflows)
- Sprint 15: PLANNED (production polish)

## Key Decisions

- 2026-02-27: Decided to add MEMORY.md, LEARNINGS.md, autonomy rules to project
- 2026-02-27: Topaz data extraction identified as major upcoming project
- 2026-02-27: Created topaz_importer.py scaffold in import_engine/

## Active Blockers

- X:\ drive not accessible from Claude Code sandbox — need sample files copied locally
- No Topaz documentation exists — format must be reverse-engineered from raw data
