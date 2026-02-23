"""Abstract base class for vendor integrations."""
from abc import ABC, abstractmethod
from typing import Any


class BaseVendor(ABC):
    """
    All vendor integrations must subclass BaseVendor and implement
    the abstract methods below. This keeps vendor-specific logic
    isolated while allowing the rest of the app to work generically.
    """

    # Override in each subclass
    SLUG: str = ""
    DISPLAY_NAME: str = ""

    # ------------------------------------------------------------------ #
    # Required interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def parse_order_csv(self, filepath: str) -> list[dict[str, Any]]:
        """
        Parse a vendor-specific CSV export and return a list of
        normalised purchase-item dicts ready to be inserted as
        PurchaseItem rows.

        Expected keys per item:
            sku, description, quantity, unit_price, line_total
        """

    @abstractmethod
    def parse_invoice(self, filepath: str) -> dict[str, Any]:
        """
        Parse a vendor-specific invoice (PDF or structured file) and
        return a dict with purchase-level fields:
            order_number, invoice_number, order_date, subtotal,
            tax, shipping, total, items (list of item dicts)
        """

    # ------------------------------------------------------------------ #
    # Optional helpers with sensible defaults                              #
    # ------------------------------------------------------------------ #

    def normalize_currency(self, value: Any) -> float:
        """Strip currency symbols and convert to float."""
        if value is None:
            return 0.0
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def normalize_date(self, value: Any) -> str | None:
        """Return ISO-8601 date string or None."""
        if not value:
            return None
        import re
        from datetime import datetime

        value = str(value).strip()
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def __repr__(self) -> str:
        return f"<Vendor:{self.SLUG}>"
