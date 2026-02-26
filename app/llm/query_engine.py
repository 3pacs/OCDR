"""Structured query API that accepts JSON query specs and returns results.

This is the core safety layer: the LLM generates JSON query specifications,
NOT raw SQL.  All table names, column names, and operators are whitelisted.
All filter values are parameterized through SQLAlchemy ORM queries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func as sa_func

from app.models import (
    db,
    BillingRecord,
    EraPayment,
    EraClaimLine,
    Payer,
    FeeSchedule,
    ScheduleRecord,
    Physician,
)

# ── Whitelists ──────────────────────────────────────────────────────

ALLOWED_TABLES: dict[str, dict[str, Any]] = {
    "billing_records": {
        "model": BillingRecord,
        "columns": [
            "id", "patient_name", "referring_doctor", "scan_type", "gado_used",
            "insurance_carrier", "modality", "service_date", "primary_payment",
            "secondary_payment", "total_payment", "extra_charges",
            "reading_physician", "description", "is_psma", "denial_status",
            "denial_reason_code", "era_claim_id", "appeal_deadline",
            "import_source", "created_at",
        ],
    },
    "era_payments": {
        "model": EraPayment,
        "columns": [
            "id", "filename", "check_eft_number", "payment_amount",
            "payment_date", "payment_method", "payer_name", "parsed_at",
        ],
    },
    "era_claim_lines": {
        "model": EraClaimLine,
        "columns": [
            "id", "era_payment_id", "claim_id", "claim_status",
            "billed_amount", "paid_amount", "patient_name_835",
            "service_date_835", "cpt_code", "cas_group_code",
            "cas_reason_code", "cas_adjustment_amount",
            "match_confidence", "matched_billing_id",
        ],
    },
    "payers": {
        "model": Payer,
        "columns": [
            "code", "display_name", "filing_deadline_days",
            "expected_has_secondary",
        ],
    },
    "fee_schedule": {
        "model": FeeSchedule,
        "columns": [
            "id", "payer_code", "modality", "expected_rate",
            "underpayment_threshold",
        ],
    },
    "schedule_records": {
        "model": ScheduleRecord,
        "columns": [
            "id", "patient_name", "scan_type", "modality", "scheduled_date",
            "scheduled_time", "referring_doctor", "insurance_carrier",
            "location", "status", "import_source",
        ],
    },
    "physicians": {
        "model": Physician,
        "columns": [
            "name", "physician_type", "specialty", "clinic_affiliation",
        ],
    },
}

ALLOWED_ACTIONS = {"aggregate", "list", "count"}

ALLOWED_OPS = {"=", "!=", ">", "<", ">=", "<=", "in", "like", "between"}

ALLOWED_AGGREGATES = {"sum", "count", "avg", "min", "max"}

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100


# ── Public API ──────────────────────────────────────────────────────

def execute_query(query_spec: dict) -> dict:
    """Execute a structured query spec safely.

    query_spec format::

        {
            "action": "aggregate" | "list" | "count",
            "table": "billing_records" | "era_payments" | ...,
            "measures": ["sum:total_payment", "count:id", "avg:total_payment"],
            "dimensions": ["insurance_carrier", "modality"],
            "filters": [
                {"field": "service_date", "op": ">=", "value": "2025-01-01"},
                {"field": "total_payment", "op": ">", "value": 0}
            ],
            "order_by": [{"field": "sum:total_payment", "direction": "desc"}],
            "limit": 20
        }

    Returns a dict with ``"success"`` bool, ``"data"``, ``"count"``, and
    ``"error"`` keys.
    """
    try:
        _validate_spec(query_spec)
    except ValueError as exc:
        return {"success": False, "data": [], "count": 0, "error": str(exc)}

    action = query_spec["action"]
    try:
        if action == "aggregate":
            return _execute_aggregate(query_spec)
        elif action == "list":
            return _execute_list(query_spec)
        elif action == "count":
            return _execute_count(query_spec)
        else:
            return {"success": False, "data": [], "count": 0,
                    "error": f"Unknown action: {action}"}
    except Exception as exc:
        return {"success": False, "data": [], "count": 0,
                "error": f"Query execution error: {exc}"}


# ── Validation ──────────────────────────────────────────────────────

def _validate_spec(spec: dict) -> None:
    """Validate the entire query spec. Raises ValueError on problems."""
    if not isinstance(spec, dict):
        raise ValueError("query_spec must be a dict")

    action = spec.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Invalid action '{action}'. Allowed: {sorted(ALLOWED_ACTIONS)}"
        )

    table_name = spec.get("table")
    if table_name not in ALLOWED_TABLES:
        raise ValueError(
            f"Invalid table '{table_name}'. "
            f"Allowed: {sorted(ALLOWED_TABLES.keys())}"
        )

    allowed_cols = ALLOWED_TABLES[table_name]["columns"]

    # Validate measures (for aggregate)
    for measure in spec.get("measures", []):
        _validate_measure(measure, allowed_cols)

    # Validate dimensions (for aggregate)
    for dim in spec.get("dimensions", []):
        if dim not in allowed_cols:
            raise ValueError(
                f"Invalid dimension '{dim}' for table '{table_name}'. "
                f"Allowed: {allowed_cols}"
            )

    # Validate filters
    for filt in spec.get("filters", []):
        _validate_filter(filt, allowed_cols, table_name)

    # Validate order_by
    for ob in spec.get("order_by", []):
        _validate_order_by(ob, allowed_cols)

    # Validate limit
    limit = spec.get("limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if limit > MAX_LIMIT:
        raise ValueError(f"limit cannot exceed {MAX_LIMIT}")


def _validate_measure(measure: str, allowed_cols: list[str]) -> None:
    """Validate a measure string like 'sum:total_payment'."""
    if ":" not in measure:
        raise ValueError(
            f"Invalid measure format '{measure}'. Expected 'agg:column'."
        )
    agg, col = measure.split(":", 1)
    if agg not in ALLOWED_AGGREGATES:
        raise ValueError(
            f"Invalid aggregate '{agg}'. Allowed: {sorted(ALLOWED_AGGREGATES)}"
        )
    if col not in allowed_cols and col != "*":
        raise ValueError(
            f"Invalid column '{col}' in measure. Allowed: {allowed_cols}"
        )


def _validate_filter(filt: dict, allowed_cols: list[str],
                      table_name: str) -> None:
    """Validate a single filter dict."""
    if not isinstance(filt, dict):
        raise ValueError("Each filter must be a dict")
    field = filt.get("field")
    if field not in allowed_cols:
        raise ValueError(
            f"Invalid filter field '{field}' for table '{table_name}'. "
            f"Allowed: {allowed_cols}"
        )
    op = filt.get("op")
    if op not in ALLOWED_OPS:
        raise ValueError(
            f"Invalid operator '{op}'. Allowed: {sorted(ALLOWED_OPS)}"
        )
    if "value" not in filt:
        raise ValueError(f"Filter on '{field}' is missing 'value'")
    # 'between' requires a two-element list
    if op == "between":
        val = filt["value"]
        if not isinstance(val, (list, tuple)) or len(val) != 2:
            raise ValueError(
                f"'between' filter on '{field}' requires a two-element list"
            )
    # 'in' requires a list
    if op == "in":
        val = filt["value"]
        if not isinstance(val, (list, tuple)):
            raise ValueError(
                f"'in' filter on '{field}' requires a list of values"
            )


def _validate_order_by(ob: dict, allowed_cols: list[str]) -> None:
    """Validate an order_by dict."""
    if not isinstance(ob, dict):
        raise ValueError("Each order_by must be a dict")
    field = ob.get("field", "")
    direction = ob.get("direction", "asc")
    if direction not in ("asc", "desc"):
        raise ValueError(f"Invalid direction '{direction}'. Use 'asc'/'desc'.")
    # Field can be a plain column or an aggregate reference like 'sum:total_payment'
    if ":" in field:
        agg, col = field.split(":", 1)
        if agg not in ALLOWED_AGGREGATES:
            raise ValueError(f"Invalid aggregate '{agg}' in order_by")
        if col not in allowed_cols and col != "*":
            raise ValueError(f"Invalid column '{col}' in order_by")
    else:
        if field not in allowed_cols:
            raise ValueError(
                f"Invalid order_by field '{field}'. Allowed: {allowed_cols}"
            )


# ── Query Execution ─────────────────────────────────────────────────

def _get_model_and_cols(spec: dict):
    """Return the SQLAlchemy model class and allowed columns list."""
    table_name = spec["table"]
    table_info = ALLOWED_TABLES[table_name]
    model = table_info["model"]
    return model, table_info["columns"]


def _get_column(model, col_name: str):
    """Safely get a column attribute from a model."""
    return getattr(model, col_name)


def _build_aggregate_expr(model, measure: str):
    """Build a SQLAlchemy aggregate expression from 'agg:column'."""
    agg, col = measure.split(":", 1)
    agg_funcs = {
        "sum": sa_func.sum,
        "count": sa_func.count,
        "avg": sa_func.avg,
        "min": sa_func.min,
        "max": sa_func.max,
    }
    agg_func = agg_funcs[agg]
    if col == "*":
        return agg_func(getattr(model, "id", model)), measure
    return agg_func(_get_column(model, col)), measure


def _apply_filters(query, model, filters: list[dict]):
    """Apply validated filters to a SQLAlchemy query."""
    for filt in filters:
        col = _get_column(model, filt["field"])
        op = filt["op"]
        val = filt["value"]

        if op == "=":
            query = query.filter(col == val)
        elif op == "!=":
            query = query.filter(col != val)
        elif op == ">":
            query = query.filter(col > val)
        elif op == "<":
            query = query.filter(col < val)
        elif op == ">=":
            query = query.filter(col >= val)
        elif op == "<=":
            query = query.filter(col <= val)
        elif op == "in":
            query = query.filter(col.in_(val))
        elif op == "like":
            query = query.filter(col.like(val))
        elif op == "between":
            query = query.filter(col.between(val[0], val[1]))
    return query


def _execute_aggregate(spec: dict) -> dict:
    """Execute an aggregate query with GROUP BY."""
    model, _ = _get_model_and_cols(spec)
    measures = spec.get("measures", [])
    dimensions = spec.get("dimensions", [])
    filters = spec.get("filters", [])
    order_by_list = spec.get("order_by", [])
    limit = min(spec.get("limit", DEFAULT_LIMIT), MAX_LIMIT)

    # Build SELECT columns: dimensions + aggregate measures
    select_cols = []
    dim_cols = []
    for dim in dimensions:
        col = _get_column(model, dim)
        select_cols.append(col)
        dim_cols.append(col)

    measure_exprs = []
    for measure in measures:
        expr, label = _build_aggregate_expr(model, measure)
        labeled = expr.label(label)
        select_cols.append(labeled)
        measure_exprs.append((labeled, label))

    if not select_cols:
        return {"success": False, "data": [], "count": 0,
                "error": "Aggregate query requires at least one measure or dimension"}

    query = db.session.query(*select_cols)

    # Apply filters
    query = _apply_filters(query, model, filters)

    # GROUP BY dimensions
    if dim_cols:
        query = query.group_by(*dim_cols)

    # ORDER BY
    for ob in order_by_list:
        field = ob["field"]
        direction = ob.get("direction", "asc")
        if ":" in field:
            # Order by aggregate -- find the labeled column
            for labeled, label in measure_exprs:
                if label == field:
                    if direction == "desc":
                        query = query.order_by(labeled.desc())
                    else:
                        query = query.order_by(labeled.asc())
                    break
        else:
            col = _get_column(model, field)
            if direction == "desc":
                query = query.order_by(col.desc())
            else:
                query = query.order_by(col.asc())

    query = query.limit(limit)

    rows = query.all()

    # Format results
    data = []
    for row in rows:
        record = {}
        for i, dim in enumerate(dimensions):
            val = row[i]
            if isinstance(val, (date, datetime)):
                val = val.isoformat()
            record[dim] = val
        for j, measure in enumerate(measures):
            val = row[len(dimensions) + j]
            if val is not None and isinstance(val, float):
                val = round(val, 2)
            record[measure] = val
        data.append(record)

    return {"success": True, "data": data, "count": len(data), "error": None}


def _execute_list(spec: dict) -> dict:
    """Execute a list query returning individual records."""
    model, allowed_cols = _get_model_and_cols(spec)
    filters = spec.get("filters", [])
    order_by_list = spec.get("order_by", [])
    limit = min(spec.get("limit", DEFAULT_LIMIT), MAX_LIMIT)

    query = db.session.query(model)

    # Apply filters
    query = _apply_filters(query, model, filters)

    # ORDER BY
    for ob in order_by_list:
        field = ob["field"]
        direction = ob.get("direction", "asc")
        col = _get_column(model, field)
        if direction == "desc":
            query = query.order_by(col.desc())
        else:
            query = query.order_by(col.asc())

    query = query.limit(limit)

    rows = query.all()

    # Format results using to_dict if available, else manual
    data = []
    for row in rows:
        if hasattr(row, "to_dict"):
            record = row.to_dict()
        else:
            record = {}
            for col_name in allowed_cols:
                val = getattr(row, col_name, None)
                if isinstance(val, (date, datetime)):
                    val = val.isoformat()
                record[col_name] = val
        data.append(record)

    return {"success": True, "data": data, "count": len(data), "error": None}


def _execute_count(spec: dict) -> dict:
    """Execute a count query."""
    model, _ = _get_model_and_cols(spec)
    filters = spec.get("filters", [])

    query = db.session.query(sa_func.count(model.id
                             if hasattr(model, "id")
                             else getattr(model, "code")))

    # Apply filters
    query = _apply_filters(query, model, filters)

    count_val = query.scalar() or 0

    return {"success": True, "data": [{"count": count_val}],
            "count": count_val, "error": None}
