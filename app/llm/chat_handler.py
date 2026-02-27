"""Handles chat interactions for the LLM integration layer.

Processes user messages through a four-tier approach:
1. If a local LLM (Ollama) is available, sends a structured prompt and
   parses the JSON query spec from the response.
2. If Anthropic API key is configured, uses Claude to generate query specs.
3. If no LLM, tries to pattern-match the message to a pre-built template.
4. Falls back to a helpful error message with suggestions.
"""

from __future__ import annotations

import json
import logging

from app.llm.schema_context import get_schema_context
from app.llm.query_engine import execute_query
from app.llm.result_formatter import format_results
from app.llm.context_builder import build_context
from app.llm.prompt_templates import (
    TEMPLATES,
    get_template,
    resolve_query_spec,
    match_template,
)
from app.llm.local_bridge import query_local_llm, is_llm_available
from app.llm.anthropic_bridge import query_anthropic, is_anthropic_available

logger = logging.getLogger(__name__)


def handle_chat_message(message: str) -> dict:
    """Process a chat message and return a response.

    Tries three strategies in order:
    1. **LLM** -- If a local LLM is reachable, send a structured prompt
       and parse the response as a JSON query spec.
    2. **Template** -- Pattern-match the message to a pre-built template.
    3. **Fallback** -- Return a helpful message listing available topics.

    Args:
        message: The user's natural language question.

    Returns::

        {
            "response": str,       # Natural language answer
            "query_used": dict | None,  # The query spec used (if any)
            "source": "template" | "llm" | "fallback"
        }
    """
    if not message or not message.strip():
        return {
            "response": "Please enter a question about your billing data.",
            "query_used": None,
            "source": "fallback",
        }

    message = message.strip()

    # Strategy 1: Try local LLM (Ollama)
    result = _try_llm(message)
    if result is not None:
        return result

    # Strategy 2: Try Anthropic API (Claude)
    result = _try_anthropic(message)
    if result is not None:
        return result

    # Strategy 3: Try template matching
    result = _try_template(message)
    if result is not None:
        return result

    # Strategy 4: Fallback
    return _fallback_response(message)


# ── Strategy 1: Local LLM ──────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a medical billing data analyst assistant for an outpatient imaging center.
You answer questions by generating JSON query specifications.

{schema}

INSTRUCTIONS:
- Respond ONLY with a valid JSON query spec object.
- Do NOT include any explanation, markdown, or extra text.
- The JSON must have these keys: action, table, measures (for aggregate),
  dimensions (for aggregate), filters, order_by, limit.
- action must be one of: aggregate, list, count.
- measures use format "agg:column" where agg is sum/count/avg/min/max.
- filters use format {{"field": "col", "op": "op", "value": val}}.
- Allowed ops: =, !=, >, <, >=, <=, in, like, between.
- Use the current year for date filters unless the user specifies otherwise.

DATA CONTEXT:
{context}
"""


def _try_llm(message: str) -> dict | None:
    """Attempt to use the local LLM to generate a query spec."""
    if not is_llm_available():
        return None

    try:
        # Build the system prompt with schema and context
        context_data = build_context()
        context_summary = _format_context_for_prompt(context_data)

        system_prompt = _SYSTEM_PROMPT.format(
            schema=get_schema_context(),
            context=context_summary,
        )

        # Query the LLM
        llm_response = query_local_llm(
            prompt=message,
            system_prompt=system_prompt,
        )

        if not llm_response:
            return None

        # Parse JSON from the LLM response
        query_spec = _extract_json(llm_response)
        if query_spec is None:
            logger.warning("LLM response was not valid JSON: %s",
                           llm_response[:200])
            return None

        # Execute the query
        results = execute_query(query_spec)

        if not results.get("success"):
            logger.warning("LLM-generated query failed: %s",
                           results.get("error"))
            # Fall through to template matching
            return None

        # Format the results
        formatted = format_results(query_spec, results)

        return {
            "response": formatted,
            "query_used": query_spec,
            "source": "llm",
        }

    except Exception as exc:
        logger.error("LLM strategy failed: %s", exc)
        return None


# ── Strategy 2: Anthropic API ─────────────────────────────────────


def _try_anthropic(message: str) -> dict | None:
    """Attempt to use the Anthropic Claude API to generate a query spec."""
    if not is_anthropic_available():
        return None

    try:
        context_data = build_context()
        context_summary = _format_context_for_prompt(context_data)

        system_prompt = _SYSTEM_PROMPT.format(
            schema=get_schema_context(),
            context=context_summary,
        )

        api_response = query_anthropic(
            prompt=message,
            system_prompt=system_prompt,
        )

        if not api_response:
            return None

        # Parse JSON from the response
        query_spec = _extract_json(api_response)
        if query_spec is None:
            logger.warning("Anthropic response was not valid JSON: %s",
                           api_response[:200])
            return None

        # Execute the query
        results = execute_query(query_spec)

        if not results.get("success"):
            logger.warning("Anthropic-generated query failed: %s",
                           results.get("error"))
            return None

        formatted = format_results(query_spec, results)

        return {
            "response": formatted,
            "query_used": query_spec,
            "source": "anthropic",
        }

    except Exception as exc:
        logger.error("Anthropic strategy failed: %s", exc)
        return None


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM output text.

    Handles cases where the LLM wraps JSON in markdown code blocks
    or includes extra text before/after.
    """
    text = text.strip()

    # Try direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try to extract from markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            cleaned = part.strip()
            # Remove optional language identifier (e.g., "json\n")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

    # Try to find JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _format_context_for_prompt(ctx: dict) -> str:
    """Format the context dict into a concise string for the prompt."""
    lines = [
        f"Total billing records: {ctx.get('total_billing_records', 0):,}",
        f"Total revenue: ${ctx.get('total_revenue', 0):,.2f}",
    ]
    dr = ctx.get("date_range", {})
    if dr.get("earliest") and dr.get("latest"):
        lines.append(f"Date range: {dr['earliest']} to {dr['latest']}")

    carriers = ctx.get("top_carriers", [])
    if carriers:
        top = ", ".join(
            f"{c['carrier']} ({c['count']})" for c in carriers[:5]
        )
        lines.append(f"Top carriers: {top}")

    modalities = ctx.get("top_modalities", [])
    if modalities:
        top = ", ".join(
            f"{m['modality']} ({m['count']})" for m in modalities[:5]
        )
        lines.append(f"Top modalities: {top}")

    pending = ctx.get("pending_denials", 0)
    if pending:
        lines.append(f"Pending denials: {pending}")

    return "\n".join(lines)


# ── Strategy 2: Template Matching ──────────────────────────────────

def _try_template(message: str) -> dict | None:
    """Try to match the message to a pre-built template."""
    template_key = match_template(message)
    if template_key is None:
        return None

    template = get_template(template_key)
    if template is None:
        return None

    try:
        query_spec = resolve_query_spec(template)
        results = execute_query(query_spec)

        if not results.get("success"):
            logger.warning("Template query '%s' failed: %s",
                           template_key, results.get("error"))
            return None

        formatted = format_results(query_spec, results)

        # Wrap with the template's result_template if available
        result_tmpl = template.get("result_template", "{results}")
        response_text = result_tmpl.format(results=formatted)

        return {
            "response": response_text,
            "query_used": query_spec,
            "source": "template",
        }
    except Exception as exc:
        logger.error("Template '%s' execution failed: %s",
                     template_key, exc)
        return None


# ── Strategy 3: Fallback ───────────────────────────────────────────

_AVAILABLE_TOPICS = [
    "Revenue by insurance carrier",
    "Denial analysis",
    "Underpayment detection",
    "Monthly revenue trends",
    "Physician revenue ranking",
    "Payer comparison",
    "Filing deadline alerts",
    "Schedule utilization",
    "ERA reconciliation",
    "Top denial reason codes",
]


def _fallback_response(message: str) -> dict:
    """Return a helpful fallback when no strategy succeeds."""
    topics = "\n".join(f"  - {t}" for t in _AVAILABLE_TOPICS)
    response = (
        "I wasn't able to answer that specific question. "
        "Here are topics I can help with:\n\n"
        f"{topics}\n\n"
        "Try asking about one of these topics, or rephrase your question."
    )
    return {
        "response": response,
        "query_used": None,
        "source": "fallback",
    }
