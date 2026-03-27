# HEARTBEAT — Claude Code Session Maintenance

> Instructions for maintaining project memory and session continuity.
> This file is loaded when heartbeat/cron tasks run.

---

## On Every Session Start

1. **Read MEMORY.md** for current project state and context
2. **Read today's daily log** at `memory/YYYY-MM-DD.md` (create if missing)
3. **Check CLAUDE.md** for any rule changes
4. **Check LEARNINGS.md** for anti-patterns to avoid

## On Every Session End

1. **Update today's daily log** (`memory/YYYY-MM-DD.md`) with:
   - What was worked on (files changed, features added/fixed)
   - Key decisions made and why
   - Any user feedback or corrections received
   - Blockers encountered or resolved
   - Tests status (pass/fail count)

2. **Promote important items to MEMORY.md** if they affect future sessions:
   - New environment details
   - Architecture decisions
   - Sprint status changes
   - New blockers or resolved blockers

3. **Update LEARNINGS.md** if any mistakes were made

## Daily Log Format

Each day gets a file at `memory/YYYY-MM-DD.md`:

```markdown
# YYYY-MM-DD — Session Log

## Work Done
- [bullet points of changes]

## Decisions
- [key decisions and rationale]

## User Feedback
- [corrections, preferences, guidance received]

## Files Changed
- [list of modified files]

## Tests
- X passed, Y failed

## Blockers
- [any open blockers]
```

## Memory Hygiene Rules

- **Daily logs are append-only** — never edit past days
- **MEMORY.md stays under 100 lines** — archive old info to daily logs
- **Don't duplicate** — if it's in a daily log, don't also put it in MEMORY.md unless it's load-bearing context
- **Date everything** — use absolute dates, not "yesterday" or "last week"
- **Memory files in `.claude/projects/` are for cross-session Claude memories** (user prefs, feedback, project context)
- **Memory files in `memory/` are project logs** (daily work, decisions, state changes)

## What Goes Where

| Information | Location |
|-------------|----------|
| User preferences, role, feedback | `.claude/projects/.../memory/*.md` |
| Daily work log | `memory/YYYY-MM-DD.md` |
| Curated project state | `MEMORY.md` |
| Mistakes and anti-patterns | `LEARNINGS.md` |
| Agent instructions and rules | `CLAUDE.md` |
