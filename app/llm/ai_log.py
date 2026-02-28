"""AI Communication Log — structured log files for AI assistant analysis.

Creates JSONL (JSON Lines) log files that external AI tools (like Claude Code)
can read to understand the system's state, chat history, insights, and
recommended actions.

All patient data (PHI) is encrypted before writing to logs.

Log Structure:
  ai_logs/
    chat_log.jsonl        — every chat interaction (question + response)
    insights_log.jsonl    — AI-generated insights and anomaly detections
    actions_log.jsonl     — recommended actions for human review
    system_log.jsonl      — system events (imports, matches, errors)
    context.json          — current system snapshot (refreshed periodically)

Each JSONL line is a JSON object with:
  {
    "ts": "2026-02-27T14:30:00Z",   — UTC timestamp
    "type": "chat|insight|action|system",
    "data": { ... },                 — encrypted PHI where applicable
    "meta": { ... }                  — non-PHI metadata
  }
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.llm.phi_encrypt import (
    encrypt_record,
    redact_phi_from_text,
    PHI_FIELDS,
)

_LOG_DIR = None


def _get_log_dir() -> str:
    """Get or create the AI log directory."""
    global _LOG_DIR
    if _LOG_DIR:
        return _LOG_DIR

    try:
        from flask import current_app
        _LOG_DIR = current_app.config.get("AI_LOG_FOLDER", "ai_logs")
    except RuntimeError:
        _LOG_DIR = os.environ.get("AI_LOG_FOLDER", "ai_logs")

    os.makedirs(_LOG_DIR, exist_ok=True)
    return _LOG_DIR


def _write_log(filename: str, entry: dict):
    """Append a log entry to a JSONL file."""
    log_dir = _get_log_dir()
    filepath = os.path.join(log_dir, filename)

    entry["ts"] = datetime.now(timezone.utc).isoformat()

    line = json.dumps(entry, default=str, ensure_ascii=False)
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read_log(filename: str, tail: int = 50) -> list[dict]:
    """Read the last N entries from a JSONL log file."""
    log_dir = _get_log_dir()
    filepath = os.path.join(log_dir, filename)

    if not os.path.exists(filepath):
        return []

    lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    # Take last N lines
    recent = lines[-tail:] if len(lines) > tail else lines

    entries = []
    for line in recent:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return entries


# ══════════════════════════════════════════════════════════════════
#  Chat Logging
# ══════════════════════════════════════════════════════════════════

def log_chat(question: str, response: str, source: str,
             query_used: dict | None = None):
    """Log a chat interaction with PHI redacted from the question/response."""
    _write_log("chat_log.jsonl", {
        "type": "chat",
        "data": {
            "question": redact_phi_from_text(question),
            "response": redact_phi_from_text(response),
            "source": source,
            "query_spec": query_used,
        },
    })


def get_chat_history(tail: int = 50) -> list[dict]:
    """Read recent chat history from the log."""
    return _read_log("chat_log.jsonl", tail=tail)


# ══════════════════════════════════════════════════════════════════
#  Insight Logging (AI-generated observations)
# ══════════════════════════════════════════════════════════════════

def log_insight(title: str, message: str, severity: str = "info",
                category: str = "general", data: dict | None = None):
    """Log an AI-generated insight.

    severity: info, warning, critical
    category: revenue, denials, scheduling, payer, physician, system
    """
    entry_data = {
        "title": title,
        "message": redact_phi_from_text(message),
        "severity": severity,
        "category": category,
    }
    if data:
        entry_data["details"] = encrypt_record(data) if data else {}

    _write_log("insights_log.jsonl", {
        "type": "insight",
        "data": entry_data,
    })


def get_insights(tail: int = 50) -> list[dict]:
    """Read recent insights from the log."""
    return _read_log("insights_log.jsonl", tail=tail)


# ══════════════════════════════════════════════════════════════════
#  Action Logging (recommended actions for human review)
# ══════════════════════════════════════════════════════════════════

def log_action(action: str, reason: str, priority: str = "normal",
               target: dict | None = None):
    """Log a recommended action.

    priority: low, normal, high, urgent
    target: related record data (PHI will be encrypted)
    """
    entry_data = {
        "action": action,
        "reason": redact_phi_from_text(reason),
        "priority": priority,
        "status": "pending",
    }
    if target:
        entry_data["target"] = encrypt_record(target)

    _write_log("actions_log.jsonl", {
        "type": "action",
        "data": entry_data,
    })


def get_actions(tail: int = 50, status: str | None = None) -> list[dict]:
    """Read recent action recommendations."""
    entries = _read_log("actions_log.jsonl", tail=tail)
    if status:
        entries = [e for e in entries if e.get("data", {}).get("status") == status]
    return entries


# ══════════════════════════════════════════════════════════════════
#  System Event Logging
# ══════════════════════════════════════════════════════════════════

def log_system_event(event: str, details: dict | None = None):
    """Log a system event (imports, matches, errors, etc.)."""
    entry_data = {"event": event}
    if details:
        # Encrypt any PHI in details
        entry_data["details"] = encrypt_record(details)

    _write_log("system_log.jsonl", {
        "type": "system",
        "data": entry_data,
    })


def get_system_events(tail: int = 50) -> list[dict]:
    """Read recent system events."""
    return _read_log("system_log.jsonl", tail=tail)


# ══════════════════════════════════════════════════════════════════
#  Context Snapshot (for external AI consumption)
# ══════════════════════════════════════════════════════════════════

def write_context_snapshot():
    """Write a JSON snapshot of current system state for external AI tools.

    This file is designed to be read by Claude Code or similar tools
    to understand the system without accessing the database directly.
    No PHI is included — only aggregate statistics.
    """
    try:
        from app.llm.context_builder import build_context
        context = build_context()
    except Exception:
        context = {}

    # Add log summaries
    chat_entries = get_chat_history(tail=10)
    insight_entries = get_insights(tail=10)
    action_entries = get_actions(tail=10, status="pending")

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system_state": context,
        "recent_chats": len(chat_entries),
        "recent_chat_topics": [
            e.get("data", {}).get("question", "")[:100]
            for e in chat_entries
        ],
        "pending_actions": len(action_entries),
        "action_summaries": [
            {
                "action": e.get("data", {}).get("action", ""),
                "priority": e.get("data", {}).get("priority", ""),
                "reason": e.get("data", {}).get("reason", "")[:200],
            }
            for e in action_entries
        ],
        "recent_insights": [
            {
                "title": e.get("data", {}).get("title", ""),
                "severity": e.get("data", {}).get("severity", ""),
                "category": e.get("data", {}).get("category", ""),
            }
            for e in insight_entries
        ],
    }

    log_dir = _get_log_dir()
    filepath = os.path.join(log_dir, "context.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)

    return snapshot


def read_context_snapshot() -> dict:
    """Read the current context snapshot."""
    log_dir = _get_log_dir()
    filepath = os.path.join(log_dir, "context.json")

    if not os.path.exists(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════
#  Instructions file — tells external AI what to do
# ══════════════════════════════════════════════════════════════════

def write_ai_instructions():
    """Write an instructions file for external AI tools.

    This tells Claude Code (or similar) how to read and respond to
    the log files, and what actions it should take.
    """
    log_dir = _get_log_dir()
    filepath = os.path.join(log_dir, "INSTRUCTIONS.md")

    instructions = """\
# AI Log Communication Protocol

This directory contains structured log files from the OCDR medical billing
system's AI assistant. These files are designed for consumption by external
AI tools (e.g., Claude Code) to maintain continuity and provide assistance.

## Files

| File | Format | Purpose |
|------|--------|---------|
| `context.json` | JSON | Current system snapshot (aggregate stats, no PHI) |
| `chat_log.jsonl` | JSONL | Chat interactions (PHI redacted) |
| `insights_log.jsonl` | JSONL | AI-generated observations and anomalies |
| `actions_log.jsonl` | JSONL | Recommended actions pending human review |
| `system_log.jsonl` | JSONL | Import events, match results, errors |

## PHI Protection

- All patient names, IDs, and identifying fields are encrypted (prefix `ENC:`)
  or hashed (prefix `HASH:`) before writing to logs
- Free text is redacted of name patterns (replaced with `[REDACTED]`)
- Aggregate statistics (totals, averages) are safe and unencrypted
- NEVER attempt to decrypt or reverse PHI from these logs

## How to Use These Logs

1. Read `context.json` for current system state
2. Check `actions_log.jsonl` for pending recommendations
3. Review `insights_log.jsonl` for anomalies that need investigation
4. Use `chat_log.jsonl` to understand what the user has been asking about
5. Write responses by creating new entries via the API

## Communication Protocol

To send a message back to the OCDR AI assistant:
- POST to `/api/ai-log/action` with `{"action": "...", "reason": "...", "priority": "..."}`
- POST to `/api/ai-log/insight` with `{"title": "...", "message": "...", "severity": "...", "category": "..."}`

The AI assistant will surface your insights and actions to the user
in the dashboard and chat interface.
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(instructions)

    return filepath
