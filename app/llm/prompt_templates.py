"""Pre-built prompt templates for common billing questions.

Each template contains a name, description, a query_spec template (with
optional placeholder fields), and a result_template string for formatting.
Templates can be used directly or matched via keyword patterns in chat.
"""

from __future__ import annotations

from datetime import date, timedelta


def _current_year() -> str:
    return str(date.today().year)


def _year_start() -> str:
    return f"{date.today().year}-01-01"


def _today() -> str:
    return date.today().isoformat()


def _thirty_days_ago() -> str:
    return (date.today() - timedelta(days=30)).isoformat()


def _ninety_days_from_now() -> str:
    return (date.today() + timedelta(days=90)).isoformat()


TEMPLATES: dict[str, dict] = {

    "revenue_by_carrier": {
        "name": "Revenue by Insurance Carrier",
        "description": "Total revenue broken down by insurance carrier for the current year.",
        "keywords": ["revenue", "carrier", "insurance", "payer", "income", "by carrier"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["sum:total_payment", "count:id", "avg:total_payment"],
            "dimensions": ["insurance_carrier"],
            "filters": [
                {"field": "service_date", "op": ">=", "value": _year_start},
            ],
            "order_by": [{"field": "sum:total_payment", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "Revenue by insurance carrier (year to date):\n"
            "{results}\n"
            "This shows the total payments received from each carrier."
        ),
    },

    "denial_analysis": {
        "name": "Denial Analysis",
        "description": "Breakdown of denied claims by carrier and reason code.",
        "keywords": ["denial", "denied", "denials", "reject", "rejected"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["count:id", "sum:total_payment"],
            "dimensions": ["insurance_carrier", "denial_reason_code"],
            "filters": [
                {"field": "denial_status", "op": "=", "value": "DENIED"},
            ],
            "order_by": [{"field": "count:id", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "Denial analysis:\n"
            "{results}\n"
            "These are currently denied claims grouped by carrier and reason."
        ),
    },

    "underpayment_check": {
        "name": "Underpayment Check",
        "description": "Compare actual payments against fee schedule expected rates.",
        "keywords": ["underpayment", "underpaid", "below rate", "fee schedule",
                      "expected rate", "short pay"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["sum:total_payment", "avg:total_payment", "count:id"],
            "dimensions": ["modality", "insurance_carrier"],
            "filters": [
                {"field": "total_payment", "op": ">", "value": 0},
                {"field": "service_date", "op": ">=", "value": _year_start},
            ],
            "order_by": [{"field": "avg:total_payment", "direction": "asc"}],
            "limit": 20,
        },
        "result_template": (
            "Payment rates by modality and carrier:\n"
            "{results}\n"
            "Compare these averages against the fee schedule to identify underpayments."
        ),
    },

    "monthly_trend": {
        "name": "Monthly Revenue Trend",
        "description": "Monthly revenue totals for the current year.",
        "keywords": ["monthly", "trend", "month", "over time", "by month"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["sum:total_payment", "count:id"],
            "dimensions": ["service_date"],
            "filters": [
                {"field": "service_date", "op": ">=", "value": _year_start},
            ],
            "order_by": [{"field": "service_date", "direction": "asc"}],
            "limit": 366,
        },
        "result_template": (
            "Revenue trend (current year):\n"
            "{results}\n"
            "This shows daily totals. Group by month for a high-level view."
        ),
    },

    "physician_ranking": {
        "name": "Physician Revenue Ranking",
        "description": "Reading physicians ranked by total revenue generated.",
        "keywords": ["physician", "doctor", "ranking", "top physician",
                      "reading physician", "dr"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["sum:total_payment", "count:id", "avg:total_payment"],
            "dimensions": ["reading_physician"],
            "filters": [
                {"field": "service_date", "op": ">=", "value": _year_start},
                {"field": "total_payment", "op": ">", "value": 0},
            ],
            "order_by": [{"field": "sum:total_payment", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "Physician revenue ranking (year to date):\n"
            "{results}\n"
            "Ranked by total payment amount."
        ),
    },

    "payer_comparison": {
        "name": "Payer Comparison",
        "description": "Compare payers by volume, revenue, and average payment.",
        "keywords": ["payer comparison", "compare payer", "compare carrier",
                      "carrier comparison", "which payer", "best payer"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["count:id", "sum:total_payment", "avg:total_payment"],
            "dimensions": ["insurance_carrier"],
            "filters": [
                {"field": "service_date", "op": ">=", "value": _year_start},
            ],
            "order_by": [{"field": "count:id", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "Payer comparison (year to date):\n"
            "{results}\n"
            "Sorted by volume. Check avg payment for rate quality."
        ),
    },

    "filing_deadline_check": {
        "name": "Filing Deadline Check",
        "description": "Claims approaching their filing deadlines.",
        "keywords": ["filing deadline", "deadline", "timely filing",
                      "about to expire", "expiring"],
        "query_spec": {
            "action": "list",
            "table": "billing_records",
            "filters": [
                {"field": "appeal_deadline", "op": "<=",
                 "value": _ninety_days_from_now},
                {"field": "appeal_deadline", "op": ">=", "value": _today},
                {"field": "denial_status", "op": "in",
                 "value": ["DENIED", "APPEALED"]},
            ],
            "order_by": [{"field": "appeal_deadline", "direction": "asc"}],
            "limit": 50,
        },
        "result_template": (
            "Claims approaching filing deadlines:\n"
            "{results}\n"
            "These claims need attention before their deadlines pass."
        ),
    },

    "schedule_utilization": {
        "name": "Schedule Utilization",
        "description": "Breakdown of scheduled appointments by modality and status.",
        "keywords": ["schedule", "utilization", "appointment", "scheduled",
                      "upcoming", "no show", "cancellation"],
        "query_spec": {
            "action": "aggregate",
            "table": "schedule_records",
            "measures": ["count:id"],
            "dimensions": ["modality", "status"],
            "filters": [
                {"field": "scheduled_date", "op": ">=",
                 "value": _thirty_days_ago},
            ],
            "order_by": [{"field": "count:id", "direction": "desc"}],
            "limit": 50,
        },
        "result_template": (
            "Schedule utilization (last 30 days):\n"
            "{results}\n"
            "Review cancellation and no-show rates by modality."
        ),
    },

    "era_reconciliation": {
        "name": "ERA Reconciliation",
        "description": "Summary of ERA payments and matching status.",
        "keywords": ["era", "reconciliation", "remittance", "835",
                      "unmatched", "matched", "eft"],
        "query_spec": {
            "action": "aggregate",
            "table": "era_claim_lines",
            "measures": ["count:id", "sum:billed_amount", "sum:paid_amount"],
            "dimensions": ["claim_status"],
            "filters": [],
            "order_by": [{"field": "count:id", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "ERA reconciliation summary:\n"
            "{results}\n"
            "Check for unmatched or partially paid claim lines."
        ),
    },

    "top_denial_codes": {
        "name": "Top Denial Reason Codes",
        "description": "Most frequent denial reason codes across all carriers.",
        "keywords": ["denial code", "reason code", "top denial", "denial reason",
                      "cas code", "adjustment code", "why denied"],
        "query_spec": {
            "action": "aggregate",
            "table": "billing_records",
            "measures": ["count:id", "sum:total_payment"],
            "dimensions": ["denial_reason_code"],
            "filters": [
                {"field": "denial_status", "op": "=", "value": "DENIED"},
            ],
            "order_by": [{"field": "count:id", "direction": "desc"}],
            "limit": 20,
        },
        "result_template": (
            "Top denial reason codes:\n"
            "{results}\n"
            "Address the most frequent codes to reduce future denials."
        ),
    },
}


def get_template(name: str) -> dict | None:
    """Get a template by its key name."""
    return TEMPLATES.get(name)


def resolve_query_spec(template: dict) -> dict:
    """Resolve a template's query_spec, calling any callable values.

    Some filter values are callables (like ``_year_start``) that return
    the current date.  This function evaluates them to produce a
    concrete query_spec ready for ``execute_query()``.
    """
    spec = template["query_spec"]
    resolved = {
        "action": spec["action"],
        "table": spec["table"],
        "measures": list(spec.get("measures", [])),
        "dimensions": list(spec.get("dimensions", [])),
        "order_by": list(spec.get("order_by", [])),
        "limit": spec.get("limit", 100),
    }

    resolved_filters = []
    for filt in spec.get("filters", []):
        resolved_filt = dict(filt)
        val = resolved_filt["value"]
        if callable(val):
            resolved_filt["value"] = val()
        elif isinstance(val, list):
            resolved_filt["value"] = [
                v() if callable(v) else v for v in val
            ]
        resolved_filters.append(resolved_filt)
    resolved["filters"] = resolved_filters

    return resolved


def match_template(message: str) -> str | None:
    """Try to match a user message to a template by keyword matching.

    Returns the template key if found, None otherwise.
    """
    message_lower = message.lower()

    best_match = None
    best_score = 0

    for key, tmpl in TEMPLATES.items():
        keywords = tmpl.get("keywords", [])
        score = 0
        for kw in keywords:
            if kw.lower() in message_lower:
                score += len(kw)  # Longer keyword matches score higher
        if score > best_score:
            best_score = score
            best_match = key

    return best_match if best_score > 0 else None
