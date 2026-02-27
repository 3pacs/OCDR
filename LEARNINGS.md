# OCDR — Learnings

> Persistent lessons from past sessions. Review at session start.
> Pattern: what happened → what we learned → rule to prevent recurrence.
> Last updated: 2026-02-27

---

## Import Engine

1. **Column detection order matters.** The excel/csv importers try multiple column name patterns. If a new pattern is added, it must go AFTER more specific patterns to avoid false matches.
   - Rule: Most-specific pattern first, most-generic last.

2. **Date parsing is fragile.** Excel serial dates, 2-digit years, MM/DD/YY vs DD/MM/YY ambiguity. Always use `validation.py:parse_date()` — never `datetime.strptime()` directly.
   - Rule: All date parsing goes through `parse_date()`. No exceptions.

3. **Batch inserts in groups of 500.** SQLite locks up on huge single transactions. Flush every 500 rows.
   - Rule: `db.session.flush()` every 500 inserts during bulk import.

## Database

4. **Never drop columns on existing DBs.** SQLite doesn't support DROP COLUMN cleanly. Add new columns alongside old ones.
   - Rule: Additive schema changes only. Old columns stay.

5. **Money is DECIMAL(10,2) in existing columns.** New money columns should use INTEGER cents to avoid float drift.
   - Rule: New money = INTEGER cents. Existing money = leave as DECIMAL.

## Matching

6. **Name normalization is critical.** ERA files use different name formats than billing (WILLIAM vs BILL, suffixes, middle initials). The name_aliases table tracks confirmed pairs.
   - Rule: Always check name_aliases before declaring a name mismatch.

## Environment

7. **X:\ drive is not accessible from Claude Code sandbox.** Must have user copy files locally.
   - Rule: Don't assume network drives are mounted. Check access before planning imports.

8. **Topaz uses flat text files, not a database.** Bespoke 1980s software. No documentation.
   - Rule: Reverse-engineer format from sample data. Never assume standard formats.

## Testing

9. **Run `pytest tests/ -x -q` after every change.** Tests catch regressions that visual inspection misses.
   - Rule: No commit without passing tests.

## Anti-Patterns (Don't Do This)

- Don't load all records into memory — use pagination/yield_per
- Don't use f-strings for HTML — XSS risk
- Don't refactor code you weren't asked to change
- Don't create new files when editing existing ones works
- Don't guess file contents — read first
