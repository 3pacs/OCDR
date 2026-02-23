"""SpectrumXray vendor integration."""
from typing import Any
import csv
from app.vendors.base import BaseVendor


class SpectrumXrayVendor(BaseVendor):
    SLUG = "spectrumxray"
    DISPLAY_NAME = "SpectrumXray"

    # Column name mappings — adjust if actual export headers differ
    CSV_COLUMNS = {
        "sku": ["item #", "item number", "sku", "part #", "part number"],
        "description": ["description", "item description", "product name"],
        "quantity": ["qty", "quantity", "ordered"],
        "unit_price": ["unit price", "price", "each"],
        "line_total": ["total", "ext price", "extended price", "line total"],
    }

    def _find_col(self, headers: list[str], aliases: list[str]) -> str | None:
        lower = [h.lower().strip() for h in headers]
        for alias in aliases:
            if alias.lower() in lower:
                return headers[lower.index(alias.lower())]
        return None

    def parse_order_csv(self, filepath: str) -> list[dict[str, Any]]:
        items = []
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            col_map = {
                field: self._find_col(list(headers), aliases)
                for field, aliases in self.CSV_COLUMNS.items()
            }

            for row in reader:
                sku_col = col_map.get("sku")
                desc_col = col_map.get("description")
                qty_col = col_map.get("quantity")
                price_col = col_map.get("unit_price")
                total_col = col_map.get("line_total")

                qty = self.normalize_currency(row.get(qty_col) if qty_col else None)
                unit_price = self.normalize_currency(row.get(price_col) if price_col else None)
                line_total = self.normalize_currency(row.get(total_col) if total_col else None)

                if line_total == 0 and qty and unit_price:
                    line_total = round(qty * unit_price, 2)

                item = {
                    "sku": row.get(sku_col, "").strip() if sku_col else "",
                    "description": row.get(desc_col, "").strip() if desc_col else "",
                    "quantity": qty,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
                if item["description"] or item["sku"]:
                    items.append(item)

        return items

    def parse_invoice(self, filepath: str) -> dict[str, Any]:
        """
        Basic PDF invoice parser using PyPDF2 text extraction.
        SpectrumXray invoices contain text that can be scraped
        for order number, totals, and line items.
        """
        try:
            import PyPDF2

            text_pages: list[str] = []
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text_pages.append(page.extract_text() or "")

            full_text = "\n".join(text_pages)
            return self._parse_invoice_text(full_text)
        except Exception as exc:
            return {"error": str(exc), "items": []}

    def _parse_invoice_text(self, text: str) -> dict[str, Any]:
        import re

        result: dict[str, Any] = {
            "order_number": None,
            "invoice_number": None,
            "order_date": None,
            "subtotal": 0.0,
            "tax": 0.0,
            "shipping": 0.0,
            "total": 0.0,
            "items": [],
        }

        # Extract order / invoice numbers
        m = re.search(r"Order\s*#?\s*[:\-]?\s*(\w+)", text, re.IGNORECASE)
        if m:
            result["order_number"] = m.group(1)

        m = re.search(r"Invoice\s*#?\s*[:\-]?\s*(\w+)", text, re.IGNORECASE)
        if m:
            result["invoice_number"] = m.group(1)

        # Extract date
        m = re.search(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", text)
        if m:
            result["order_date"] = self.normalize_date(m.group(1))

        # Extract totals
        for label, key in [("Subtotal", "subtotal"), ("Tax", "tax"),
                           ("Shipping", "shipping"), ("Total", "total")]:
            m = re.search(rf"{label}[:\s]+\$?([\d,\.]+)", text, re.IGNORECASE)
            if m:
                result[key] = self.normalize_currency(m.group(1))

        return result
