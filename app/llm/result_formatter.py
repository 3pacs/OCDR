"""Converts query results into natural language summaries.

Takes the structured dict returned by query_engine.execute_query() and
produces human-readable text suitable for display in a chat interface.
"""

from __future__ import annotations


def format_results(query_spec: dict, results: dict) -> str:
    """Convert structured query results into a readable text summary.

    Args:
        query_spec: The original query specification dict.
        results: The dict returned by ``execute_query()``.

    Returns:
        A human-readable string summarizing the results.
    """
    if not results.get("success"):
        return f"Query failed: {results.get('error', 'Unknown error')}"

    action = query_spec.get("action", "")
    data = results.get("data", [])
    count = results.get("count", 0)

    if not data:
        return _format_empty(query_spec)

    if action == "aggregate":
        return _format_aggregate(query_spec, data, count)
    elif action == "list":
        return _format_list(query_spec, data, count)
    elif action == "count":
        return _format_count(query_spec, data)
    else:
        return f"Results: {count} record(s) returned."


# ── Private formatters ──────────────────────────────────────────────

def _format_empty(query_spec: dict) -> str:
    """Format a message for empty result sets."""
    table = query_spec.get("table", "unknown")
    filters = query_spec.get("filters", [])

    msg = f"No results found in {_humanize_table(table)}"
    if filters:
        conditions = []
        for f in filters:
            conditions.append(
                f"{_humanize_column(f['field'])} {f['op']} {f['value']}"
            )
        msg += f" matching: {', '.join(conditions)}"
    msg += "."
    return msg


def _format_aggregate(query_spec: dict, data: list[dict],
                       count: int) -> str:
    """Format aggregate query results with totals and averages."""
    table = query_spec.get("table", "unknown")
    dimensions = query_spec.get("dimensions", [])
    measures = query_spec.get("measures", [])
    filters = query_spec.get("filters", [])

    lines = []

    # Title line
    dim_label = " by " + " and ".join(
        _humanize_column(d) for d in dimensions
    ) if dimensions else ""
    measure_label = ", ".join(
        _humanize_measure(m) for m in measures
    ) if measures else "Summary"
    lines.append(f"{measure_label} from {_humanize_table(table)}{dim_label}:")

    # Filter summary
    if filters:
        filter_parts = []
        for f in filters:
            filter_parts.append(
                f"{_humanize_column(f['field'])} {f['op']} {f['value']}"
            )
        lines.append(f"  Filters: {', '.join(filter_parts)}")

    lines.append("")

    # Data rows
    for i, row in enumerate(data, 1):
        parts = []
        # Dimensions first
        for dim in dimensions:
            parts.append(f"{_humanize_column(dim)}: {row.get(dim, 'N/A')}")
        # Then measures
        for measure in measures:
            val = row.get(measure)
            parts.append(f"{_humanize_measure(measure)}: {_format_value(measure, val)}")
        lines.append(f"  {i}. {' | '.join(parts)}")

    lines.append("")
    lines.append(f"Total groups: {count}")

    # If there's a single group, add a grand summary
    if count == 1 and not dimensions:
        row = data[0]
        summary_parts = []
        for measure in measures:
            val = row.get(measure)
            summary_parts.append(
                f"{_humanize_measure(measure)}: {_format_value(measure, val)}"
            )
        return f"Summary for {_humanize_table(table)}: {', '.join(summary_parts)}."

    return "\n".join(lines)


def _format_list(query_spec: dict, data: list[dict], count: int) -> str:
    """Format list query results with item details."""
    table = query_spec.get("table", "unknown")
    filters = query_spec.get("filters", [])
    limit = query_spec.get("limit", 100)

    lines = []
    lines.append(f"{_humanize_table(table)} ({count} record(s)):")

    if filters:
        filter_parts = []
        for f in filters:
            filter_parts.append(
                f"{_humanize_column(f['field'])} {f['op']} {f['value']}"
            )
        lines.append(f"  Filters: {', '.join(filter_parts)}")

    lines.append("")

    # Determine display columns -- use a sensible subset
    display_cols = _pick_display_columns(table, data)

    for i, row in enumerate(data, 1):
        parts = []
        for col in display_cols:
            val = row.get(col)
            if val is not None:
                parts.append(f"{_humanize_column(col)}: {val}")
        lines.append(f"  {i}. {' | '.join(parts)}")

    if count >= limit:
        lines.append(f"\n  (Showing first {limit} results)")

    return "\n".join(lines)


def _format_count(query_spec: dict, data: list[dict]) -> str:
    """Format count query results."""
    table = query_spec.get("table", "unknown")
    filters = query_spec.get("filters", [])
    count_val = data[0].get("count", 0) if data else 0

    msg = f"Count of {_humanize_table(table)}: {count_val:,}"
    if filters:
        conditions = []
        for f in filters:
            conditions.append(
                f"{_humanize_column(f['field'])} {f['op']} {f['value']}"
            )
        msg += f" (where {', '.join(conditions)})"
    msg += "."
    return msg


# ── Helpers ─────────────────────────────────────────────────────────

_TABLE_NAMES = {
    "billing_records": "Billing Records",
    "era_payments": "ERA Payments",
    "era_claim_lines": "ERA Claim Lines",
    "payers": "Payers",
    "fee_schedule": "Fee Schedule",
    "schedule_records": "Schedule Records",
    "physicians": "Physicians",
}


def _humanize_table(table: str) -> str:
    """Convert table name to human-readable form."""
    return _TABLE_NAMES.get(table, table.replace("_", " ").title())


def _humanize_column(col: str) -> str:
    """Convert column name to human-readable form."""
    return col.replace("_", " ").title()


def _humanize_measure(measure: str) -> str:
    """Convert a measure like 'sum:total_payment' to 'Total Payment (Sum)'."""
    if ":" not in measure:
        return measure.replace("_", " ").title()
    agg, col = measure.split(":", 1)
    col_label = col.replace("_", " ").title()
    agg_label = agg.upper()
    return f"{col_label} ({agg_label})"


def _format_value(measure: str, val) -> str:
    """Format a value based on its measure context."""
    if val is None:
        return "N/A"
    # Detect monetary columns by name
    money_keywords = {"payment", "amount", "charges", "rate", "revenue",
                      "owed", "paid", "premium", "threshold"}
    measure_lower = measure.lower()
    is_money = any(kw in measure_lower for kw in money_keywords)
    if is_money and isinstance(val, (int, float)):
        return f"${val:,.2f}"
    if isinstance(val, float):
        return f"{val:,.2f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def _pick_display_columns(table: str, data: list[dict]) -> list[str]:
    """Pick the most useful columns to display for a table."""
    # Preferred display columns by table
    preferred = {
        "billing_records": [
            "patient_name", "service_date", "modality",
            "insurance_carrier", "total_payment", "denial_status",
        ],
        "era_payments": [
            "payer_name", "payment_date", "payment_amount",
            "check_eft_number", "payment_method",
        ],
        "era_claim_lines": [
            "patient_name_835", "service_date_835", "cpt_code",
            "billed_amount", "paid_amount", "claim_status",
        ],
        "payers": [
            "code", "display_name", "filing_deadline_days",
        ],
        "fee_schedule": [
            "payer_code", "modality", "expected_rate",
            "underpayment_threshold",
        ],
        "schedule_records": [
            "patient_name", "scheduled_date", "modality",
            "scan_type", "status",
        ],
        "physicians": [
            "name", "physician_type", "specialty",
        ],
    }

    cols = preferred.get(table)
    if cols:
        # Only include columns that actually appear in the data
        if data:
            available = set(data[0].keys())
            return [c for c in cols if c in available]
    # Fallback: first 5 keys from first row
    if data:
        return list(data[0].keys())[:5]
    return []
