"""Bank / Payment Portal validator.

Logs into bank portal and validates:
- EFT/check deposits match ERA payment records
- Payment dates
- Deposit amounts vs expected totals
"""

import logging
import os
import re

from backend.app.browser.base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)

DEFAULT_PORTAL_URL = os.environ.get(
    "BANK_PORTAL_URL",
    "https://online.bank.example.com/login",  # User sets real URL via env
)


class BankValidator(BaseValidator):
    """Validate ERA payments against bank deposit records."""

    def __init__(self, portal_url: str | None = None, headless: bool = True):
        super().__init__(portal_url or DEFAULT_PORTAL_URL, headless)

    @property
    def name(self) -> str:
        return "bank"

    def _get_credentials(self) -> tuple[str, str]:
        return (
            os.environ.get("BANK_PORTAL_USER", ""),
            os.environ.get("BANK_PORTAL_PASS", ""),
        )

    async def _login(self, page) -> bool:
        """Log into bank portal."""
        try:
            username, password = self._get_credentials()

            await page.fill(
                'input[name="username"], input[name="userId"], input[id*="user"], input[type="text"]',
                username,
                timeout=10000,
            )
            await page.fill(
                'input[name="password"], input[id*="pass"], input[type="password"]',
                password,
                timeout=10000,
            )
            await page.click(
                'button[type="submit"], input[type="submit"], button:has-text("Sign In"), button:has-text("Log In")',
                timeout=10000,
            )
            await page.wait_for_load_state("networkidle", timeout=30000)

            content = await page.content()
            if "invalid" in content.lower() or "incorrect" in content.lower():
                return False

            logger.info("Bank portal login successful")
            return True

        except Exception as e:
            logger.error(f"Bank login error: {e}")
            return False

    async def _extract_portal_data(self, page, records: list[dict]) -> list[dict]:
        """Search bank transactions for matching deposits.

        Records here are ERA payments with check/EFT numbers and amounts.
        We search the bank's transaction history for each.
        """
        portal_data = []

        # Navigate to transaction history / account activity
        try:
            # Try common bank portal navigation patterns
            for selector in [
                'a:has-text("Account Activity")',
                'a:has-text("Transaction History")',
                'a:has-text("Transactions")',
                'a:has-text("Account")',
                'a[href*="transaction"]',
                'a[href*="activity"]',
            ]:
                try:
                    await page.click(selector, timeout=5000)
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    break
                except Exception:
                    continue
        except Exception:
            pass

        for rec in records:
            rec_id = str(rec.get("record_id", rec.get("id", "")))
            check_number = rec.get("check_eft_number", "")
            payment_amount = rec.get("payment_amount")
            payment_date = rec.get("payment_date", "")

            try:
                # Search for the transaction
                # Try to use search/filter if available
                if check_number:
                    try:
                        search_input = await page.query_selector(
                            'input[name*="search"], input[name*="filter"], input[placeholder*="Search"], input[id*="search"]'
                        )
                        if search_input:
                            await search_input.fill(str(check_number))
                            await page.keyboard.press("Enter")
                            await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                # Extract visible transactions
                transactions = await page.evaluate("""(searchRef) => {
                    // Try to find transaction table/list
                    const tables = document.querySelectorAll(
                        'table.transactions, table[id*="transaction"], table[id*="activity"], .transaction-list table, table'
                    );

                    for (const table of tables) {
                        const rows = table.querySelectorAll('tr');
                        if (rows.length < 2) continue;

                        const results = [];
                        for (let i = 1; i < rows.length && i < 50; i++) {
                            const cells = rows[i].querySelectorAll('td');
                            const texts = Array.from(cells).map(c => c.innerText.trim());
                            const rowText = texts.join(' ');

                            // Check if this row matches our search
                            if (searchRef && rowText.includes(searchRef)) {
                                results.push({
                                    cells: texts,
                                    match_type: 'exact_ref',
                                });
                            }
                        }

                        if (results.length > 0) return results;

                        // If no exact match, return first few rows for manual review
                        const fallback = [];
                        for (let i = 1; i < Math.min(rows.length, 6); i++) {
                            const cells = rows[i].querySelectorAll('td');
                            fallback.push({
                                cells: Array.from(cells).map(c => c.innerText.trim()),
                                match_type: 'sample',
                            });
                        }
                        return fallback;
                    }
                    return [];
                }""", str(check_number))

                if transactions:
                    # Find best matching transaction
                    best = None
                    for txn in transactions:
                        if txn.get("match_type") == "exact_ref":
                            best = txn
                            break
                    if not best and transactions:
                        # Try amount matching
                        for txn in transactions:
                            cells = txn.get("cells", [])
                            for cell in cells:
                                amount = _parse_amount(cell)
                                if amount and payment_amount and abs(amount - float(payment_amount)) < 0.01:
                                    best = txn
                                    break

                    if best:
                        cells = best.get("cells", [])
                        portal_data.append({
                            "record_id": rec_id,
                            "portal_amount": _find_amount(cells),
                            "portal_date": _find_date(cells),
                            "portal_reference": _find_reference(cells, str(check_number)),
                            "found": True,
                            "raw_data": cells[:8],
                        })
                    else:
                        portal_data.append({
                            "record_id": rec_id,
                            "portal_amount": None,
                            "portal_date": None,
                            "portal_reference": None,
                            "found": False,
                            "raw_data": [],
                        })
                else:
                    portal_data.append({
                        "record_id": rec_id,
                        "portal_amount": None,
                        "portal_date": None,
                        "portal_reference": None,
                        "found": False,
                        "raw_data": [],
                    })

            except Exception as e:
                logger.warning(f"Error checking transaction {rec_id}: {e}")
                self.summary.add_error(f"Transaction {rec_id}: {e}")

        return portal_data

    def _compare(self, db_record: dict, portal_record: dict) -> list[ValidationResult]:
        """Compare ERA payment against bank transaction."""
        results = []
        rec_id = str(db_record.get("record_id", db_record.get("id", "")))

        # Check if transaction was found at all
        if not portal_record.get("found"):
            results.append(ValidationResult(
                record_id=rec_id,
                field="deposit",
                db_value=f"Check/EFT: {db_record.get('check_eft_number', 'N/A')}",
                portal_value="NOT_FOUND",
                match=False,
                notes="Deposit not found in bank — may not have posted yet",
            ))
            return results

        # Compare amount
        db_amount = db_record.get("payment_amount")
        portal_amount = portal_record.get("portal_amount")
        if db_amount is not None and portal_amount is not None:
            try:
                db_val = float(db_amount)
                portal_val = float(portal_amount)
                amount_match = abs(db_val - portal_val) < 0.01
                results.append(ValidationResult(
                    record_id=rec_id,
                    field="deposit_amount",
                    db_value=f"${db_val:,.2f}",
                    portal_value=f"${portal_val:,.2f}",
                    match=amount_match,
                    notes="" if amount_match else f"Difference: ${abs(db_val - portal_val):,.2f}",
                ))
            except (ValueError, TypeError):
                pass

        # Compare date
        db_date = str(db_record.get("payment_date", ""))
        portal_date = portal_record.get("portal_date", "")
        if db_date and portal_date:
            date_match = db_date in portal_date or portal_date in db_date
            results.append(ValidationResult(
                record_id=rec_id,
                field="deposit_date",
                db_value=db_date,
                portal_value=portal_date,
                match=date_match,
                notes="" if date_match else "Date mismatch — may be posting delay",
            ))

        # Compare reference number
        db_ref = str(db_record.get("check_eft_number", ""))
        portal_ref = portal_record.get("portal_reference", "")
        if db_ref and portal_ref:
            ref_match = db_ref.strip() == portal_ref.strip()
            results.append(ValidationResult(
                record_id=rec_id,
                field="reference_number",
                db_value=db_ref,
                portal_value=portal_ref,
                match=ref_match,
            ))

        return results


def _parse_amount(text: str) -> float | None:
    """Parse a dollar amount from text."""
    match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2}))', text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _find_amount(cells: list[str]) -> float | None:
    """Find the most likely amount in a row of cells."""
    for cell in cells:
        amount = _parse_amount(cell)
        if amount and amount > 0:
            return amount
    return None


def _find_date(cells: list[str]) -> str | None:
    """Find a date in a row of cells."""
    for cell in cells:
        if re.match(r'\d{1,2}/\d{1,2}/\d{2,4}', cell.strip()):
            return cell.strip()
        if re.match(r'\d{4}-\d{2}-\d{2}', cell.strip()):
            return cell.strip()
    return None


def _find_reference(cells: list[str], expected_ref: str) -> str | None:
    """Find a reference/check number in cells."""
    for cell in cells:
        if expected_ref and expected_ref in cell:
            return cell.strip()
        if re.match(r'^[A-Z0-9]{6,}$', cell.strip()):
            return cell.strip()
    return None
