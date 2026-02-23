"""Integration tests for Flask API routes."""
import io
import json
import csv
import pytest


# ------------------------------------------------------------------ #
# Vendor routes                                                       #
# ------------------------------------------------------------------ #

class TestVendorRoutes:
    def test_list_vendors_returns_list(self, client):
        res = client.get("/api/vendors/")
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)

    def test_create_vendor(self, client):
        payload = {"name": "TestCo", "slug": "testco", "website": "https://test.co"}
        res = client.post("/api/vendors/", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["slug"] == "testco"

    def test_create_vendor_missing_slug(self, client):
        res = client.post("/api/vendors/", json={"name": "NoPK"})
        assert res.status_code == 400

    def test_create_vendor_duplicate_slug(self, client):
        client.post("/api/vendors/", json={"name": "DupA", "slug": "dupslug"})
        res = client.post("/api/vendors/", json={"name": "DupB", "slug": "dupslug"})
        assert res.status_code == 409

    def test_get_vendor(self, client):
        create_res = client.post("/api/vendors/", json={"name": "GetMe", "slug": "getme"})
        vid = create_res.get_json()["id"]
        res = client.get(f"/api/vendors/{vid}")
        assert res.status_code == 200
        assert res.get_json()["name"] == "GetMe"

    def test_get_nonexistent_vendor(self, client):
        res = client.get("/api/vendors/99999")
        assert res.status_code == 404

    def test_update_vendor(self, client):
        create_res = client.post("/api/vendors/", json={"name": "UpdateMe", "slug": "updateme"})
        vid = create_res.get_json()["id"]
        res = client.put(f"/api/vendors/{vid}", json={"notes": "Updated notes"})
        assert res.status_code == 200
        assert res.get_json()["notes"] == "Updated notes"

    def test_deactivate_vendor(self, client):
        create_res = client.post("/api/vendors/", json={"name": "DeactMe", "slug": "deactme"})
        vid = create_res.get_json()["id"]
        res = client.delete(f"/api/vendors/{vid}")
        assert res.status_code == 200
        # Verify vendor is now inactive
        get_res = client.get(f"/api/vendors/{vid}")
        assert get_res.get_json()["active"] is False


# ------------------------------------------------------------------ #
# Purchase routes                                                     #
# ------------------------------------------------------------------ #

class TestPurchaseRoutes:
    def _create_vendor(self, client, name="PurchVendor", slug="purchvendor"):
        res = client.post("/api/vendors/", json={"name": name, "slug": slug})
        return res.get_json()["id"]

    def test_create_and_list_purchases(self, client):
        vid = self._create_vendor(client)
        payload = {
            "order_number": "ORD-100",
            "status": "ordered",
            "total": 99.99,
            "items": [
                {"sku": "A1", "description": "Widget", "quantity": 2,
                 "unit_price": 40.0, "line_total": 80.0}
            ],
        }
        res = client.post(f"/api/vendors/{vid}/purchases", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["order_number"] == "ORD-100"
        assert len(data["items"]) == 1

        list_res = client.get(f"/api/vendors/{vid}/purchases")
        assert list_res.status_code == 200
        assert len(list_res.get_json()) >= 1

    def test_update_purchase_status(self, client):
        vid = self._create_vendor(client, "PurchVendor2", "purchvendor2")
        create_res = client.post(f"/api/vendors/{vid}/purchases",
                                 json={"order_number": "ORD-200", "status": "pending", "total": 0})
        pid = create_res.get_json()["id"]
        update_res = client.put(f"/api/vendors/{vid}/purchases/{pid}",
                                json={"status": "received"})
        assert update_res.status_code == 200
        assert update_res.get_json()["status"] == "received"


# ------------------------------------------------------------------ #
# Product routes                                                      #
# ------------------------------------------------------------------ #

class TestProductRoutes:
    def test_create_and_list_products(self, client):
        vendor_res = client.post("/api/vendors/", json={"name": "ProdVendor", "slug": "prodvendor"})
        vid = vendor_res.get_json()["id"]
        create_res = client.post(f"/api/vendors/{vid}/products",
                                 json={"name": "X-Ray Film", "sku": "XF-001", "unit_price": 25.0})
        assert create_res.status_code == 201
        list_res = client.get(f"/api/vendors/{vid}/products")
        assert list_res.status_code == 200
        assert len(list_res.get_json()) >= 1

    def test_create_product_missing_name(self, client):
        vendor_res = client.post("/api/vendors/", json={"name": "ProdVendor2", "slug": "prodvendor2"})
        vid = vendor_res.get_json()["id"]
        res = client.post(f"/api/vendors/{vid}/products", json={"sku": "X99"})
        assert res.status_code == 400


# ------------------------------------------------------------------ #
# Import routes                                                       #
# ------------------------------------------------------------------ #

class TestImportRoutes:
    def _make_csv_bytes(self):
        content = io.StringIO()
        writer = csv.DictWriter(content,
                                fieldnames=["Item #", "Description", "Qty", "Unit Price", "Total"])
        writer.writeheader()
        writer.writerow({"Item #": "T1", "Description": "Test Item",
                         "Qty": "2", "Unit Price": "10.00", "Total": "20.00"})
        return content.getvalue().encode("utf-8")

    def test_preview_csv(self, client):
        csv_bytes = self._make_csv_bytes()
        data = {"file": (io.BytesIO(csv_bytes), "test.csv", "text/csv")}
        res = client.post("/api/imports/preview", data=data, content_type="multipart/form-data")
        assert res.status_code == 200
        result = res.get_json()
        assert result["success"] is True
        assert len(result["headers"]) > 0

    def test_preview_no_file(self, client):
        res = client.post("/api/imports/preview")
        assert res.status_code == 400

    def test_upload_csv(self, client):
        csv_bytes = self._make_csv_bytes()
        data = {
            "file": (io.BytesIO(csv_bytes), "order.csv", "text/csv"),
            "category": "invoice",
            "auto_parse": "true",
        }
        res = client.post("/api/imports/upload", data=data, content_type="multipart/form-data")
        assert res.status_code == 201
        body = res.get_json()
        assert body["document"]["file_type"] == "csv"

    def test_upload_disallowed_extension(self, client):
        data = {"file": (io.BytesIO(b"exe content"), "evil.exe", "application/octet-stream")}
        res = client.post("/api/imports/upload", data=data, content_type="multipart/form-data")
        assert res.status_code == 400

    def test_list_documents(self, client):
        res = client.get("/api/imports/documents")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)

    def test_import_purchase_from_items(self, client):
        vendor_res = client.post("/api/vendors/", json={"name": "ImportVendor", "slug": "importvendor"})
        vid = vendor_res.get_json()["id"]
        payload = {
            "vendor_id": vid,
            "items": [
                {"sku": "I1", "description": "Item One", "quantity": 3,
                 "unit_price": 10.0, "line_total": 30.0}
            ],
            "status": "received",
        }
        res = client.post("/api/imports/import-purchase", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["subtotal"] == 30.0

    def test_import_purchase_missing_vendor(self, client):
        res = client.post("/api/imports/import-purchase",
                          json={"items": [], "status": "received"})
        assert res.status_code == 400
