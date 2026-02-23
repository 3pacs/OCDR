"""
CSV import service.

Handles both generic CSV imports (auto-detect columns) and
vendor-specific CSV imports (uses vendor integration classes).
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd


# ------------------------------------------------------------------ #
# Generic CSV helpers                                                 #
# ------------------------------------------------------------------ #

def preview_csv(filepath: str, rows: int = 20) -> dict[str, Any]:
    """
    Return headers and first N rows of a CSV file for preview.
    """
    try:
        df = pd.read_csv(filepath, nrows=rows, encoding="utf-8-sig")
        return {
            "success": True,
            "headers": list(df.columns),
            "rows": df.fillna("").astype(str).values.tolist(),
            "total_columns": len(df.columns),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "headers": [], "rows": []}


def import_generic_csv(filepath: str, column_map: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Import a generic CSV, optionally remapping columns.

    column_map: {"csv_column_name": "target_field"}
    Target fields: sku, description, quantity, unit_price, line_total,
                   order_number, order_date
    """
    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        if column_map:
            df = df.rename(columns={v: k for k, v in column_map.items()})

        items = []
        for _, row in df.iterrows():
            item: dict[str, Any] = {
                "sku": str(row.get("sku", "") or "").strip(),
                "description": str(row.get("description", "") or "").strip(),
                "quantity": _safe_float(row.get("quantity", 1)),
                "unit_price": _safe_float(row.get("unit_price", 0)),
                "line_total": _safe_float(row.get("line_total", 0)),
            }
            if item["line_total"] == 0 and item["quantity"] and item["unit_price"]:
                item["line_total"] = round(item["quantity"] * item["unit_price"], 2)
            items.append(item)

        return {
            "success": True,
            "items": items,
            "count": len(items),
            "columns_found": list(df.columns),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "items": []}


def import_vendor_csv(filepath: str, vendor_slug: str) -> dict[str, Any]:
    """
    Use a vendor-specific parser to import a CSV.
    Falls back to generic import if no vendor handler is registered.
    """
    from app.vendors.registry import VendorRegistry

    handler = VendorRegistry.get(vendor_slug)
    if handler is None:
        return import_generic_csv(filepath)

    try:
        items = handler.parse_order_csv(filepath)
        return {"success": True, "items": items, "count": len(items), "vendor": vendor_slug}
    except Exception as exc:
        return {"success": False, "error": str(exc), "items": [], "vendor": vendor_slug}


# ------------------------------------------------------------------ #
# XLSX support                                                        #
# ------------------------------------------------------------------ #

def import_xlsx(filepath: str, sheet_name: int | str = 0) -> dict[str, Any]:
    """Import an Excel file, treating the first sheet as a table."""
    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        items = df.fillna("").astype(str).to_dict(orient="records")
        return {
            "success": True,
            "items": items,
            "count": len(items),
            "headers": list(df.columns),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "items": []}


# ------------------------------------------------------------------ #
# Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _safe_float(value: Any) -> float:
    if value is None or str(value).strip() in ("", "nan", "NaN"):
        return 0.0
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0
