"""Unit tests for vendor integration classes and CSV import service."""
import csv
import pytest

from app.vendors.base import BaseVendor
from app.vendors.spectrumxray import SpectrumXrayVendor
from app.vendors.petnet import PetNetVendor
from app.vendors.registry import VendorRegistry
from app.services.csv_importer import (
    preview_csv,
    import_generic_csv,
    import_vendor_csv,
    _safe_float,
)


# ------------------------------------------------------------------ #
# BaseVendor helpers                                                  #
# ------------------------------------------------------------------ #

class TestBaseVendorHelpers:
    """Test normalize_* helpers via a concrete subclass."""

    def setup_method(self):
        self.vendor = SpectrumXrayVendor()

    def test_normalize_currency_plain(self):
        assert self.vendor.normalize_currency("25.00") == 25.0

    def test_normalize_currency_dollar_sign(self):
        assert self.vendor.normalize_currency("$1,234.56") == 1234.56

    def test_normalize_currency_none(self):
        assert self.vendor.normalize_currency(None) == 0.0

    def test_normalize_currency_invalid(self):
        assert self.vendor.normalize_currency("n/a") == 0.0

    def test_normalize_date_slash(self):
        assert self.vendor.normalize_date("01/15/2025") == "2025-01-15"

    def test_normalize_date_iso(self):
        assert self.vendor.normalize_date("2025-06-30") == "2025-06-30"

    def test_normalize_date_none(self):
        assert self.vendor.normalize_date(None) is None

    def test_normalize_date_unrecognised(self):
        assert self.vendor.normalize_date("not-a-date") is None


# ------------------------------------------------------------------ #
# SpectrumXray vendor                                                 #
# ------------------------------------------------------------------ #

class TestSpectrumXrayVendor:
    def test_slug(self):
        assert SpectrumXrayVendor.SLUG == "spectrumxray"

    def test_parse_order_csv(self, sample_csv_path):
        vendor = SpectrumXrayVendor()
        items = vendor.parse_order_csv(sample_csv_path)
        assert len(items) == 2
        first = items[0]
        assert first["sku"] == "XR-100"
        assert first["quantity"] == 2.0
        assert first["unit_price"] == 25.0
        assert first["line_total"] == 50.0

    def test_parse_order_csv_computes_line_total(self, tmp_path):
        """If Total column missing, compute from qty * unit_price."""
        f = tmp_path / "no_total.csv"
        with open(f, "w", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["Item #", "Description", "Qty", "Unit Price"])
            writer.writeheader()
            writer.writerow({"Item #": "A1", "Description": "Widget", "Qty": "3", "Unit Price": "10.00"})
        vendor = SpectrumXrayVendor()
        items = vendor.parse_order_csv(str(f))
        assert items[0]["line_total"] == 30.0

    def test_parse_order_csv_skips_empty_rows(self, tmp_path):
        f = tmp_path / "empty_rows.csv"
        with open(f, "w", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["Item #", "Description", "Qty", "Unit Price", "Total"])
            writer.writeheader()
            writer.writerow({"Item #": "", "Description": "", "Qty": "", "Unit Price": "", "Total": ""})
            writer.writerow({"Item #": "X1", "Description": "Film", "Qty": "1", "Unit Price": "10", "Total": "10"})
        vendor = SpectrumXrayVendor()
        items = vendor.parse_order_csv(str(f))
        assert len(items) == 1


# ------------------------------------------------------------------ #
# PetNet vendor                                                       #
# ------------------------------------------------------------------ #

class TestPetNetVendor:
    def test_slug(self):
        assert PetNetVendor.SLUG == "petnet"

    def test_parse_order_csv(self, sample_petnet_csv_path):
        vendor = PetNetVendor()
        items = vendor.parse_order_csv(sample_petnet_csv_path)
        assert len(items) == 1
        assert items[0]["sku"] == "PN-500"
        assert items[0]["quantity"] == 10.0
        assert items[0]["line_total"] == 50.0


# ------------------------------------------------------------------ #
# Vendor registry                                                     #
# ------------------------------------------------------------------ #

class TestVendorRegistry:
    def test_get_spectrumxray(self):
        v = VendorRegistry.get("spectrumxray")
        assert isinstance(v, SpectrumXrayVendor)

    def test_get_petnet(self):
        v = VendorRegistry.get("petnet")
        assert isinstance(v, PetNetVendor)

    def test_get_unknown_returns_none(self):
        assert VendorRegistry.get("nonexistent") is None

    def test_all_slugs(self):
        slugs = VendorRegistry.all_slugs()
        assert "spectrumxray" in slugs
        assert "petnet" in slugs

    def test_register_new_vendor(self):
        class NewVendor(BaseVendor):
            SLUG = "newvendor"
            DISPLAY_NAME = "New Vendor"
            def parse_order_csv(self, filepath): return []
            def parse_invoice(self, filepath): return {}

        VendorRegistry.register(NewVendor)
        assert VendorRegistry.get("newvendor") is not None


# ------------------------------------------------------------------ #
# CSV importer service                                                #
# ------------------------------------------------------------------ #

class TestCsvImporterService:
    def test_safe_float_number(self):
        assert _safe_float("3.14") == 3.14

    def test_safe_float_currency(self):
        assert _safe_float("$10.00") == 10.0

    def test_safe_float_empty(self):
        assert _safe_float("") == 0.0

    def test_safe_float_nan(self):
        assert _safe_float("nan") == 0.0

    def test_preview_csv(self, sample_csv_path):
        result = preview_csv(sample_csv_path)
        assert result["success"] is True
        assert "Item #" in result["headers"]
        assert len(result["rows"]) == 2

    def test_import_generic_csv(self, tmp_path):
        f = tmp_path / "generic.csv"
        with open(f, "w", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["sku", "description", "quantity", "unit_price"])
            writer.writeheader()
            writer.writerow({"sku": "G1", "description": "Gadget", "quantity": "5", "unit_price": "2.00"})
        result = import_generic_csv(str(f))
        assert result["success"] is True
        assert result["count"] == 1
        assert result["items"][0]["line_total"] == 10.0

    def test_import_vendor_csv_spectrumxray(self, sample_csv_path):
        result = import_vendor_csv(sample_csv_path, "spectrumxray")
        assert result["success"] is True
        assert result["count"] == 2

    def test_import_vendor_csv_unknown_falls_back_to_generic(self, sample_csv_path):
        # Falls back to generic import for unknown vendors
        result = import_vendor_csv(sample_csv_path, "unknown_vendor")
        assert result["success"] is True
