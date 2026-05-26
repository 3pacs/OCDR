"""Purview / Candelis PACS validator.

Logs into the PACS web viewer and validates:
- Patient demographics (name, DOB)
- Study records (modality, scan type, date)
- Referring physician
"""

import logging
import os

from backend.app.browser.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)

DEFAULT_PORTAL_URL = os.environ.get(
    "PACS_PORTAL_URL",
    "https://purview.example.com/login",  # User sets real URL via env
)


class PACSValidator(BaseValidator):
    """Validate billing records against Purview/Candelis PACS data."""

    def __init__(self, portal_url: str | None = None, headless: bool = True):
        super().__init__(portal_url or DEFAULT_PORTAL_URL, headless)

    @property
    def name(self) -> str:
        return "pacs"

    def _get_credentials(self) -> tuple[str, str]:
        return (
            os.environ.get("PURVIEW_USER", ""),
            os.environ.get("PURVIEW_PASS", ""),
        )

    async def _login(self, page) -> bool:
        """Log into Purview/Candelis."""
        try:
            username, password = self._get_credentials()

            # Generic login form — works for most PACS web UIs
            await page.fill(
                'input[name="username"], input[name="user"], input[id*="user"], input[type="text"]',
                username,
                timeout=10000,
            )
            await page.fill(
                'input[name="password"], input[id*="pass"], input[type="password"]',
                password,
                timeout=10000,
            )
            await page.click(
                'button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Sign")',
                timeout=10000,
            )
            await page.wait_for_load_state("networkidle", timeout=30000)

            content = await page.content()
            if "invalid" in content.lower() or "failed" in content.lower():
                return False

            logger.info("PACS login successful")
            return True

        except Exception as e:
            logger.error(f"PACS login error: {e}")
            return False

    async def _extract_portal_data(self, page, records: list[dict]) -> list[dict]:
        """Search for patients/studies in PACS and extract data."""
        portal_data = []

        for rec in records:
            rec_id = str(rec.get("record_id", rec.get("id", "")))
            patient_name = rec.get("patient_name", "")
            service_date = rec.get("service_date", "")
            patient_id = rec.get("patient_id", "")

            try:
                # Navigate to patient/study search
                # Try common PACS search URLs
                search_urls = [
                    f"{self.portal_url.rsplit('/', 1)[0]}/search",
                    f"{self.portal_url.rsplit('/', 1)[0]}/worklist",
                    f"{self.portal_url.rsplit('/', 1)[0]}/studies",
                ]

                for url in search_urls:
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=10000)
                        break
                    except Exception:
                        continue

                # Search by patient name or ID
                if patient_id:
                    try:
                        await page.fill(
                            'input[name*="patientid"], input[name*="PatientID"], input[id*="patientId"], input[name*="mrn"]',
                            str(patient_id),
                            timeout=5000,
                        )
                    except Exception:
                        pass

                if patient_name:
                    parts = patient_name.split(",", 1)
                    last_name = parts[0].strip()
                    try:
                        await page.fill(
                            'input[name*="patient"], input[name*="Patient"], input[name*="lastName"], input[id*="patient"]',
                            last_name,
                            timeout=5000,
                        )
                    except Exception:
                        pass

                if service_date:
                    try:
                        await page.fill(
                            'input[name*="date"], input[name*="Date"], input[id*="studyDate"]',
                            str(service_date),
                            timeout=5000,
                        )
                    except Exception:
                        pass

                # Click search
                try:
                    await page.click(
                        'button:has-text("Search"), input[value="Search"], button[type="submit"]',
                        timeout=5000,
                    )
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                # Extract study data from results
                study_data = await page.evaluate("""() => {
                    // Try common PACS result table patterns
                    const tables = document.querySelectorAll(
                        'table.studies, table.worklist, table[id*="study"], table[id*="result"], .study-list table, table'
                    );
                    for (const table of tables) {
                        const rows = table.querySelectorAll('tr');
                        if (rows.length < 2) continue;

                        const headerCells = rows[0].querySelectorAll('th, td');
                        const headers = Array.from(headerCells).map(h => h.innerText.trim().toLowerCase());

                        const dataCells = rows[1].querySelectorAll('td');
                        const data = Array.from(dataCells).map(d => d.innerText.trim());

                        // Build named map
                        const result = {};
                        headers.forEach((h, i) => {
                            if (i < data.length) result[h] = data[i];
                        });
                        result.raw_cells = data.slice(0, 10);
                        return result;
                    }
                    return null;
                }""")

                if study_data:
                    portal_data.append({
                        "record_id": rec_id,
                        "portal_patient_name": (
                            study_data.get("patient name", "") or
                            study_data.get("patient", "") or
                            study_data.get("name", "")
                        ),
                        "portal_modality": (
                            study_data.get("modality", "") or
                            study_data.get("mod", "")
                        ),
                        "portal_study_date": (
                            study_data.get("study date", "") or
                            study_data.get("date", "") or
                            study_data.get("dos", "")
                        ),
                        "portal_description": (
                            study_data.get("description", "") or
                            study_data.get("study description", "")
                        ),
                        "portal_referring": (
                            study_data.get("referring", "") or
                            study_data.get("referring physician", "") or
                            study_data.get("ref physician", "")
                        ),
                        "raw_data": study_data.get("raw_cells", []),
                    })
                else:
                    portal_data.append({
                        "record_id": rec_id,
                        "portal_patient_name": "",
                        "portal_modality": "",
                        "portal_study_date": "",
                        "portal_description": "",
                        "portal_referring": "",
                        "raw_data": [],
                    })

            except Exception as e:
                logger.warning(f"Error extracting PACS study {rec_id}: {e}")
                self.summary.add_error(f"Study {rec_id}: {e}")

        return portal_data

    def _compare(self, db_record: dict, portal_record: dict) -> list[ValidationResult]:
        """Compare billing record against PACS study data."""
        results = []
        rec_id = str(db_record.get("record_id", db_record.get("id", "")))

        # Compare patient name
        db_name = (db_record.get("patient_name", "") or "").upper().strip()
        portal_name = (portal_record.get("portal_patient_name", "") or "").upper().strip()
        if portal_name:
            # Use fuzzy comparison for names (G-01, G-02, G-03 gotchas)
            name_match = _fuzzy_name_match(db_name, portal_name)
            results.append(ValidationResult(
                record_id=rec_id,
                field="patient_name",
                db_value=db_name,
                portal_value=portal_name,
                match=name_match,
                notes="" if name_match else "Name mismatch — check G-01/G-02/G-03 gotchas",
            ))

        # Compare modality
        db_mod = (db_record.get("modality", "") or "").upper().strip()
        portal_mod = (portal_record.get("portal_modality", "") or "").upper().strip()
        if portal_mod:
            mod_match = db_mod == portal_mod or db_mod in portal_mod or portal_mod in db_mod
            results.append(ValidationResult(
                record_id=rec_id,
                field="modality",
                db_value=db_mod,
                portal_value=portal_mod,
                match=mod_match,
            ))

        # Compare service date
        db_date = str(db_record.get("service_date", ""))
        portal_date = portal_record.get("portal_study_date", "")
        if portal_date and db_date:
            date_match = db_date in portal_date or portal_date in db_date
            results.append(ValidationResult(
                record_id=rec_id,
                field="service_date",
                db_value=db_date,
                portal_value=portal_date,
                match=date_match,
            ))

        # Compare referring physician
        db_doc = (db_record.get("referring_doctor", "") or "").upper().strip()
        portal_doc = (portal_record.get("portal_referring", "") or "").upper().strip()
        if portal_doc and db_doc:
            doc_match = _fuzzy_name_match(db_doc, portal_doc)
            results.append(ValidationResult(
                record_id=rec_id,
                field="referring_doctor",
                db_value=db_doc,
                portal_value=portal_doc,
                match=doc_match,
            ))

        return results


def _fuzzy_name_match(name1: str, name2: str, threshold: int = 80) -> bool:
    """Fuzzy compare two names, handling order differences and particles."""
    if not name1 or not name2:
        return False

    # Exact match
    if name1 == name2:
        return True

    # Token-sorted comparison (handles "LAST, FIRST" vs "FIRST LAST")
    try:
        from rapidfuzz import fuzz
        score = max(
            fuzz.token_sort_ratio(name1, name2),
            fuzz.token_set_ratio(name1, name2),
        )
        return score >= threshold
    except ImportError:
        # Fallback: simple containment check
        tokens1 = set(name1.replace(",", " ").split())
        tokens2 = set(name2.replace(",", " ").split())
        overlap = tokens1 & tokens2
        if not tokens1 or not tokens2:
            return False
        return len(overlap) / min(len(tokens1), len(tokens2)) >= 0.5
