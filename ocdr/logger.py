"""
Structured JSON logging for autonomous agent debugging.

Every decision, transformation, error, and flag is logged with enough
context that a future Claude agent can diagnose issues without asking
questions.

Logs are written to ``data/logs/session_YYYYMMDD_HHMMSS.jsonl`` — one
JSON object per line (JSONL format), human-readable when pretty-printed.
"""

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ocdr.config import BASE_DIR

_LOG_DIR = BASE_DIR / "data" / "logs"
_session_path: Optional[Path] = None


def _ensure_log_dir():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_session_log_path() -> Path:
    """Return (and lazily create) the current session's log file."""
    global _session_path
    if _session_path is None:
        _ensure_log_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _session_path = _LOG_DIR / f"session_{ts}.jsonl"
    return _session_path


def _write(entry: dict):
    """Append a single JSON line to the session log."""
    path = get_session_log_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")


# ── Public API ─────────────────────────────────────────────────────────────

def log_decision(operation: str,
                 input_data: Any,
                 output_data: Any,
                 flags: Optional[list[str]] = None,
                 confidence: Optional[float] = None,
                 reasoning: str = ""):
    """Log a processing decision with full context."""
    _write({
        "level": "INFO",
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "input": _safe_serialize(input_data),
        "output": _safe_serialize(output_data),
        "flags": flags or [],
        "confidence": confidence,
        "reasoning": reasoning,
    })


def log_error(operation: str,
              input_data: Any,
              error: Exception,
              suggested_fix: str = ""):
    """Log an error with the exact input that caused it and a fix suggestion.

    The ``suggested_fix`` should be a plain-English description that a
    future agent can act on (e.g. "Check that the date value is a valid
    Excel serial number or MM/DD/YYYY string").
    """
    _write({
        "level": "ERROR",
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "input": _safe_serialize(input_data),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": traceback.format_exc(),
        "suggested_fix": suggested_fix,
    })


def log_warning(operation: str,
                message: str,
                context: Any = None):
    """Log a non-fatal anomaly worth investigating."""
    _write({
        "level": "WARNING",
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "message": message,
        "context": _safe_serialize(context),
    })


def log_import_summary(source: str,
                       records_in: int,
                       records_out: int,
                       errors: list,
                       warnings: list):
    """Summary entry written at the end of each import operation."""
    _write({
        "level": "SUMMARY",
        "timestamp": datetime.now().isoformat(),
        "operation": "import_summary",
        "source": source,
        "records_in": records_in,
        "records_out": records_out,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [_safe_serialize(e) for e in errors[:50]],
        "warnings": [_safe_serialize(w) for w in warnings[:50]],
    })


def log_match_result(billing: Any,
                     era_claim: Any,
                     score_breakdown: dict,
                     decision: str):
    """Log every matching attempt with per-field scores."""
    _write({
        "level": "INFO",
        "timestamp": datetime.now().isoformat(),
        "operation": "match_attempt",
        "billing": _safe_serialize(billing),
        "era_claim": _safe_serialize(era_claim),
        "score_breakdown": score_breakdown,
        "decision": decision,
    })


def get_recent_errors(n: int = 10) -> list[dict]:
    """Read the last *n* ERROR entries from the current session log."""
    path = get_session_log_path()
    if not path.exists():
        return []
    errors = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("level") == "ERROR":
                    errors.append(entry)
            except json.JSONDecodeError:
                continue
    return errors[-n:]


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_serialize(obj: Any) -> Any:
    """Convert objects to JSON-safe types without crashing."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    # Fallback: convert to string
    return str(obj)
