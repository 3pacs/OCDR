"""Office Ally / Payer Portal validator.

Logs into Office Ally (or generic payer portal) and validates:
- Claim status (paid, denied, pending)
- Payment amounts
- Denial reason codes
- Check/EFT numbers
"""

import logging
import os

from backend.app.browser.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)

# Default Office Ally URL — user can override via env
DEFAULT_PORTAL_URL = os.environ.get(
    "PAYER_PORTAL_URL",
    "https://pm.officeally.com/pm/login.aspx",
)


class PayerPortalValidator(BaseValidator):
    """Validate ERA/claim data against Office Ally or payer portal."""

    def __init__(self, portal_url: str | None = None, headless: bool = True):
        super().__init__(portal_url or DEFAULT_PORTAL_URL, headless)

    @property
    def name(self) -> str:
        return "payer_portal"

    def _get_credentials(self) -> tuple[str, str]:
        return (
            os.environ.get("OFFICE_ALLY_USER", ""),
            os.environ.get("OFFICE_ALLY_PASS", ""),
        )

    async def _login(self, page) -> bool:
        """Log into Office Ally."""
        try:
            username, password = self._get_credentials()

            # Office Ally login form
            await page.fill('input[name="txtUserName"], input[id="txtUserName"], input[type="text"]', username, timeout=10000)
            await page.fill('input[name="txtPassword"], input[id="txtPassword"], input[type="password"]', password, timeout=10000)
            await page.click('input[type="submit"], button[type="submit"], #btnLogin', timeout=10000)

            # Wait for navigation after login
            await page.wait_for_load_state("networkidle", timeout=30000)

            # Check for login errors
            content = await page.content()
            if "invalid" in content.lower() or "incorrect" in content.lower():
                logger.warning("Login appears to have failed — invalid credentials")
                return False

            logger.info("Office Ally login successful")
            return True

        except Exception as e:
            logger.error(f"Office Ally login error: {e}")
            return False

    async def _extract_portal_data(self, page, records: list[dict]) -> list[dict]:
        """Look up claims in Office Ally and extract status/payment data.

        For each record, navigate to claim search, look up by patient name
        and date of service, and capture the portal's data.
        """
        portal_data = []

        for rec in records:
            rec_id = str(rec.get("record_id", rec.get("id", "")))
            patient_name = rec.get("patient_name", "")
            service_date = rec.get("service_date", "")
            claim_id = rec.get("era_claim_id", "")

            try:
                # Navigate to claim search
                # Office Ally: ERA > Search Claims or Payments > Search
                await page.goto(
                    f"{self.portal_url.rsplit('/', 1)[0]}/ClaimSearch.aspx",
                    wait_until="networkidle",
                    timeout=15000,
                )

                # Try searching by claim ID first if available
                if claim_id:
                    try:
                        await page.fill(
                            'input[name*="ClaimID"], input[name*="claimid"], input[id*="ClaimID"]',
                            str(claim_id),
                            timeout=5000,
                        )
                    except Exception:
                        # Fall back to name + date search
                        pass

                # Search by patient name
                if patient_name:
                    # Split "LAST, FIRST" format
                    parts = patient_name.split(",", 1)
                    last_name = parts[0].strip() if parts else patient_name
                    first_name = parts[1].strip() if len(parts) > 1 else ""

                    try:
                        await page.fill(
                            'input[name*="LastName"], input[id*="LastName"]',
                            last_name,
                            timeout=5000,
                        )
                        if first_name:
                            await page.fill(
                                'input[name*="FirstName"], input[id*="FirstName"]',
                                first_name,
                                timeout=5000,
                            )
                    except Exception:
                        pass

                # Fill date of service if available
                if service_date:
                    date_str = str(service_date)
                    try:
                        await page.fill(
                            'input[name*="DateFrom"], input[id*="DateFrom"], input[name*="dos"]',
                            date_str,
                            timeout=5000,
                        )
                    except Exception:
                        pass

                # Click search
                try:
                    await page.click(
                        'input[value="Search"], button:has-text("Search"), #btnSearch',
                        timeout=5000,
                    )
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                # Extract results from the claims grid/table
                claim_data = await page.evaluate("""() => {
                    // Try to find a results table
                    const tables = document.querySelectorAll('table.grid, table.GridView, #gvClaims, table[id*="grid"]');
                    if (tables.length === 0) return null;

                    const table = tables[0];
                    const rows = table.querySelectorAll('tr');
                    if (rows.length < 2) return null;  // header + at least 1 data row

                    // Get first data row
                    const cells = rows[1].querySelectorAll('td');
                    const texts = Array.from(cells).map(c => c.innerText.trim());

                    return {
                        raw_cells: texts,
                        row_count: rows.length - 1,
                    };
                }""")

                if claim_data and claim_data.get("raw_cells"):
                    cells = claim_data["raw_cells"]
                    portal_data.append({
                        "record_id": rec_id,
                        "portal_status": _extract_status(cells),
                        "portal_paid_amount": _extract_amount(cells),
                        "portal_check_number": _extract_check(cells),
                        "portal_denial_code": _extract_denial(cells),
                        "raw_data": cells[:10],  # First 10 cells for debugging
                    })
                else:
                    portal_data.append({
                        "record_id": rec_id,
                        "portal_status": "NOT_FOUND",
                        "portal_paid_amount": None,
                        "portal_check_number": None,
                        "portal_denial_code": None,
                        "raw_data": [],
                    })

            except Exception as e:
                logger.warning(f"Error extracting claim {rec_id}: {e}")
                self.summary.add_error(f"Claim {rec_id}: {e}")

        return portal_data

    def _compare(self, db_record: dict, portal_record: dict) -> list[ValidationResult]:
        """Compare DB billing/ERA data against portal data."""
        results = []
        rec_id = str(db_record.get("record_id", db_record.get("id", "")))

        # Compare claim status
        db_status = db_record.get("denial_status", "")
        portal_status = portal_record.get("portal_status", "")
        if portal_status and portal_status != "NOT_FOUND":
            status_match = _status_equivalent(db_status, portal_status)
            results.append(ValidationResult(
                record_id=rec_id,
                field="claim_status",
                db_value=db_status,
                portal_value=portal_status,
                match=status_match,
                notes="" if status_match else "Status mismatch — check portal",
            ))

        # Compare payment amount
        db_amount = db_record.get("total_payment") or db_record.get("paid_amount")
        portal_amount = portal_record.get("portal_paid_amount")
        if portal_amount is not None and db_amount is not None:
            try:
                db_val = float(db_amount)
                portal_val = float(portal_amount)
                amount_match = abs(db_val - portal_val) < 0.01
                results.append(ValidationResult(
                    record_id=rec_id,
                    field="payment_amount",
                    db_value=db_val,
                    portal_value=portal_val,
                    match=amount_match,
                    notes="" if amount_match else f"Difference: ${abs(db_val - portal_val):.2f}",
                ))
            except (ValueError, TypeError):
                pass

        # Compare check/EFT number
        db_check = db_record.get("check_eft_number", "")
        portal_check = portal_record.get("portal_check_number", "")
        if portal_check and db_check:
            check_match = str(db_check).strip() == str(portal_check).strip()
            results.append(ValidationResult(
                record_id=rec_id,
                field="check_eft_number",
                db_value=db_check,
                portal_value=portal_check,
                match=check_match,
            ))

        return results


def _extract_status(cells: list[str]) -> str:
    """Try to find claim status in table cells."""
    status_keywords = {
        "paid": "PAID", "denied": "DENIED", "rejected": "DENIED",
        "pending": "PENDING", "processed": "PAID",
        "approved": "PAID", "finalized": "PAID",
    }
    for cell in cells:
        lower = cell.lower()
        for keyword, status in status_keywords.items():
            if keyword in lower:
                return status
    return ""


def _extract_amount(cells: list[str]) -> float | None:
    """Try to find a payment amount in table cells."""
    import re
    for cell in cells:
        # Look for dollar amounts like $1,234.56 or 1234.56
        match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2}))', cell)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_check(cells: list[str]) -> str | None:
    """Try to find a check/EFT number in table cells."""
    import re
    for cell in cells:
        # Check numbers are typically 6+ digit numbers or alphanumeric
        if re.match(r'^[A-Z0-9]{6,}$', cell.strip()):
            return cell.strip()
    return None


def _extract_denial(cells: list[str]) -> str | None:
    """Try to find a denial reason code."""
    import re
    for cell in cells:
        # CARC codes are 1-3 digit numbers
        if re.match(r'^\d{1,3}$', cell.strip()):
            code = cell.strip()
            if 1 <= int(code) <= 300:
                return code
    return None


def _status_equivalent(db_status: str | None, portal_status: str) -> bool:
    """Check if DB and portal statuses are semantically equivalent."""
    if not db_status:
        return portal_status in ("", "NOT_FOUND")

    db_upper = db_status.upper()
    portal_upper = portal_status.upper()

    equivalents = {
        "DENIED": {"DENIED", "REJECTED"},
        "PENDING": {"PENDING", "IN_PROCESS", "SUBMITTED"},
        "PAID": {"PAID", "PROCESSED", "APPROVED", "FINALIZED"},
        "WRITTEN_OFF": {"WRITTEN_OFF", "VOID", "VOIDED"},
    }

    for canonical, variants in equivalents.items():
        if db_upper in variants and portal_upper in variants:
            return True
        if db_upper == canonical and portal_upper in variants:
            return True

    return db_upper == portal_upper
