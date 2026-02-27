"""Bridge to Anthropic Claude API for chat queries.

Uses the ANTHROPIC_API_KEY from the environment (.env file).
Only sends schema metadata and aggregate stats — never patient data.
Uses urllib only (no external dependencies).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 2048
_TIMEOUT_SECONDS = 30


def get_api_key() -> str | None:
    """Retrieve the Anthropic API key from environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key

    # Check encrypted store as fallback
    key_file = os.path.join(os.getcwd(), ".ai_key.enc")
    if os.path.exists(key_file):
        try:
            from cryptography.fernet import Fernet
            import hashlib
            import base64

            secret = os.environ.get("SECRET_KEY", "dev-secret-key")
            fernet_key = base64.urlsafe_b64encode(
                hashlib.sha256(secret.encode()).digest()
            )
            f = Fernet(fernet_key)
            with open(key_file, "rb") as fh:
                encrypted = fh.read()
            return f.decrypt(encrypted).decode()
        except Exception:
            pass

    return None


def is_anthropic_available() -> bool:
    """Check if an Anthropic API key is configured."""
    return bool(get_api_key())


def query_anthropic(prompt: str, system_prompt: str | None = None) -> str:
    """Send a prompt to the Anthropic API and return the response text.

    Args:
        prompt: The user message to send.
        system_prompt: Optional system prompt for context.

    Returns:
        The generated text response, or an empty string on failure.
    """
    api_key = get_api_key()
    if not api_key:
        return ""

    request_body: dict = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        request_body["system"] = system_prompt

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    try:
        data = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            _API_URL, data=data, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            result_text = ""
            for block in resp_data.get("content", []):
                if block.get("type") == "text":
                    result_text += block["text"]
            return result_text

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        logger.error("Anthropic API error (%d): %s", e.code, error_body[:200])
        return ""
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        logger.error("Anthropic API connection error: %s", e)
        return ""
