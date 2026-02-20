"""
Microsoft Purview integration.
Implements Step 6 — PHI asset registration and sensitivity labeling.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.config import settings


class PurviewClient:
    """
    Apache Atlas REST API client for Microsoft Purview.
    Uses MSAL for service principal authentication.
    """

    ATLAS_ENDPOINT = f"{settings.PURVIEW_ENDPOINT}/catalog/api/atlas/v2"

    def __init__(self):
        self._token: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        """Acquire OAuth2 token via MSAL service principal flow."""
        if not settings.PURVIEW_ENABLED:
            return None
        try:
            import msal
            app = msal.ConfidentialClientApplication(
                client_id=settings.PURVIEW_CLIENT_ID,
                client_credential=settings.PURVIEW_CLIENT_SECRET,
                authority=f"https://login.microsoftonline.com/{settings.PURVIEW_TENANT_ID}",
            )
            result = app.acquire_token_for_client(
                scopes=["https://purview.azure.net/.default"]
            )
            return result.get("access_token")
        except Exception:
            return None

    def register_patient_asset(self, patient_id: int, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        """Register or update a patient record as a Purview data asset."""
        if not settings.PURVIEW_ENABLED:
            return {"status": "disabled"}

        token = self._get_token()
        if not token:
            return {"status": "auth_failed"}

        entity = {
            "entity": {
                "typeName": "DataSet",
                "attributes": {
                    "name": f"patient_{patient_id}",
                    "qualifiedName": f"ocdr://patients/{patient_id}",
                    "description": "OCDR Patient Record — PHI",
                    "customAttributes": {
                        "patientId": str(patient_id),
                        "mrn": patient_data.get("mrn", ""),
                        "system": "OCDR Medical Imaging Management",
                    },
                },
                "classifications": [
                    {"typeName": "MICROSOFT.PERSONAL.HEALTH_INFORMATION"},
                    {"typeName": "MICROSOFT.PERSONAL.NAME"},
                ],
            }
        }

        try:
            import httpx
            response = httpx.post(
                f"{self.ATLAS_ENDPOINT}/entity",
                json=entity,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30,
            )
            return response.json()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def tag_phi_field(self, table_name: str, field_name: str) -> Dict[str, Any]:
        """Apply PHI sensitivity label to a specific field."""
        if not settings.PURVIEW_ENABLED:
            return {"status": "disabled"}
        # Implementation depends on Purview sensitivity label IDs
        return {"status": "not_implemented"}
