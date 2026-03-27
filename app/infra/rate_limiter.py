"""Lightweight in-process rate limiter for Flask.

No external dependencies — uses a simple sliding-window counter
stored in-memory. Suitable for single-process deployments (our
local-first SQLite app).

Usage in blueprints:
    from app.infra.rate_limiter import rate_limit

    @api_bp.route("/upload", methods=["POST"])
    @rate_limit("10/minute")
    def upload():
        ...

Or apply globally via init_rate_limiting(app) which protects
all POST/PUT/DELETE routes at a default rate.
"""

import functools
import time
import threading
from collections import defaultdict

from flask import request, jsonify


# ── Sliding window storage ──────────────────────────────────────

_lock = threading.Lock()
# {key: [timestamp, timestamp, ...]}
_windows = defaultdict(list)


def _clean_window(key, window_seconds):
    """Remove expired timestamps from window."""
    cutoff = time.monotonic() - window_seconds
    _windows[key] = [t for t in _windows[key] if t > cutoff]


def _check_rate(key, max_requests, window_seconds):
    """Check if request is within rate limit.

    Returns (allowed: bool, remaining: int, retry_after: float or None).
    """
    now = time.monotonic()
    with _lock:
        _clean_window(key, window_seconds)
        current = len(_windows[key])

        if current >= max_requests:
            oldest = _windows[key][0] if _windows[key] else now
            retry_after = window_seconds - (now - oldest)
            return False, 0, max(retry_after, 0.1)

        _windows[key].append(now)
        return True, max_requests - current - 1, None


# ── Parse rate string ───────────────────────────────────────────

def _parse_rate(rate_string):
    """Parse rate limit string like '10/minute', '100/hour', '5/second'."""
    parts = rate_string.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid rate format: {rate_string}")

    max_requests = int(parts[0])
    period = parts[1].strip().lower()

    period_seconds = {
        "second": 1, "sec": 1, "s": 1,
        "minute": 60, "min": 60, "m": 60,
        "hour": 3600, "hr": 3600, "h": 3600,
    }

    if period not in period_seconds:
        raise ValueError(f"Unknown period: {period}")

    return max_requests, period_seconds[period]


# ── Decorator ───────────────────────────────────────────────────

def rate_limit(rate_string, key_func=None):
    """Decorator to rate-limit a Flask endpoint.

    Args:
        rate_string: "N/period" (e.g. "10/minute", "100/hour")
        key_func: Callable(request) -> str for grouping. Default: remote IP.
    """
    max_requests, window_seconds = _parse_rate(rate_string)

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # Skip rate limiting in test mode
            from flask import current_app
            if current_app.config.get("TESTING"):
                return f(*args, **kwargs)

            if key_func:
                key = key_func(request)
            else:
                key = f"rl:{f.__name__}:{request.remote_addr}"

            allowed, remaining, retry_after = _check_rate(
                key, max_requests, window_seconds
            )

            if not allowed:
                resp = jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after": round(retry_after, 1),
                })
                resp.status_code = 429
                resp.headers["Retry-After"] = str(int(retry_after + 1))
                resp.headers["X-RateLimit-Limit"] = str(max_requests)
                resp.headers["X-RateLimit-Remaining"] = "0"
                return resp

            response = f(*args, **kwargs)
            # Add rate limit headers to successful responses
            if hasattr(response, "headers"):
                response.headers["X-RateLimit-Limit"] = str(max_requests)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

        return wrapper
    return decorator


# ── Global rate limiting via app.before_request ─────────────────

def init_rate_limiting(app, default_write_rate="30/minute",
                       default_read_rate="120/minute"):
    """Install global rate limiting on the Flask app.

    Applies:
      - Write endpoints (POST/PUT/DELETE): default_write_rate
      - Read endpoints (GET): default_read_rate

    Exempts health check, static files, and TESTING mode.
    """
    # Skip rate limiting entirely in test mode
    if app.config.get("TESTING"):
        return

    write_max, write_window = _parse_rate(default_write_rate)
    read_max, read_window = _parse_rate(default_read_rate)

    @app.before_request
    def _global_rate_limit():
        # Skip static files and health check
        if request.path.startswith("/static") or request.path == "/api/health":
            return None

        ip = request.remote_addr or "unknown"

        if request.method in ("POST", "PUT", "DELETE"):
            key = f"global:write:{ip}"
            allowed, remaining, retry_after = _check_rate(
                key, write_max, write_window
            )
        else:
            key = f"global:read:{ip}"
            allowed, remaining, retry_after = _check_rate(
                key, read_max, read_window
            )

        if not allowed:
            resp = jsonify({
                "error": "Rate limit exceeded. Please slow down.",
                "retry_after": round(retry_after, 1),
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(int(retry_after + 1))
            return resp

        return None
