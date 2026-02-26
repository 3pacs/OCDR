"""HTTP bridge to a local LLM server (Ollama / llama.cpp).

Uses only ``urllib.request`` from the standard library -- no extra
dependencies required.  Connects to ``localhost:11434`` by default
(standard Ollama port).
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

# Default endpoint and model -- can be overridden via Flask config
_DEFAULT_ENDPOINT = "http://localhost:11434"
_DEFAULT_MODEL = "llama3"
_TIMEOUT_SECONDS = 30


def query_local_llm(prompt: str, system_prompt: str | None = None,
                     endpoint: str | None = None,
                     model: str | None = None) -> str:
    """Send a prompt to the local LLM and return the response text.

    Uses the Ollama ``/api/generate`` endpoint with streaming disabled.

    Args:
        prompt: The user prompt to send.
        system_prompt: Optional system prompt for context.
        endpoint: LLM server base URL (default: ``http://localhost:11434``).
        model: Model name to use (default: ``llama3``).

    Returns:
        The generated text response, or an empty string if the LLM is
        not available or any error occurs.
    """
    endpoint = endpoint or _DEFAULT_ENDPOINT
    model = model or _DEFAULT_MODEL
    url = f"{endpoint}/api/generate"

    body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system_prompt:
        body["system"] = system_prompt

    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return resp_data.get("response", "")
    except (urllib.error.URLError, urllib.error.HTTPError,
            OSError, json.JSONDecodeError, KeyError, TypeError):
        return ""


def is_llm_available(endpoint: str | None = None) -> bool:
    """Check if the local LLM server is reachable.

    Makes a lightweight GET request to the server root endpoint.

    Returns:
        True if the server responds, False otherwise.
    """
    endpoint = endpoint or _DEFAULT_ENDPOINT

    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError,
            OSError, TypeError):
        return False
