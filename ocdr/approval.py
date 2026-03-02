"""
Interactive 835 payment approval workflow.

Presents each matched claim line-by-line in the terminal for user
review.  Approved payments are written to a new Excel workbook.
Every decision is persisted to ``decision_store`` for smart reports.
"""

import json
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ocdr import logger
from ocdr.config import (
    OCMRI_PATH, EXPORT_DIR, PENDING_DIR,
    MATCH_AUTO_ACCEPT, MATCH_REVIEW, get_expected_rate,
)
from ocdr.cpt_map import enrich_claim_from_cpt
from ocdr.decision_store import (
    record_decision, check_duplicate_payment, save_session_state,
    load_session_state,
)


def run_approval_session(era_file: str,
                          ocmri_path: str | None = None,
                          output_path: str | None = None,
                          resume_path: str | None = None,
                          auto_accept: bool = False) -> Path:
    """Main entry point for interactive 835 approval.

    Returns the path to the output workbook.
    """
    from ocdr.era_835_parser import parse_835_file, flatten_claims
    from ocdr.excel_reader import read_ocmri
    from ocdr.business_rules import compute_match_score
    from ocdr.excel_writer import write_payment_applied

    # Parse 835
    parsed = parse_835_file(era_file)
    payer_name = parsed.get("payer_name", "UNKNOWN")
    check_num = parsed.get("check_eft_number", "")
    pay_amount = parsed.get("payment", {}).get("amount", Decimal("0"))
    pay_date = parsed.get("payment", {}).get("date")
    claims = flatten_claims([parsed])

    # Enrich claims with CPT data
    for c in claims:
        enrich_claim_from_cpt(c)

    # Read billing records
    ocmri = ocmri_path or str(OCMRI_PATH)
    billing_records = read_ocmri(ocmri)

    # Match claims to billing
    match_results = _match_all(claims, billing_records, compute_match_score)

    # Resume support
    start_idx = 0
    if resume_path:
        state = load_session_state(Path(resume_path))
        if state:
            start_idx = state.get("next_index", 0)
            print(f"Resuming from claim {start_idx + 1} of {len(match_results)}")

    # Print header
    _print_header(payer_name, check_num, pay_amount, pay_date, len(claims))

    # Process each claim
    approved: list[dict] = []
    rejected: list[dict] = []
    skipped: list[dict] = []
    batch_auto = auto_accept
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    for i in range(start_idx, len(match_results)):
        mr = match_results[i]
        claim = mr["claim"]
        billing = mr["billing_record"]
        score_detail = mr["match_score"]
        status = mr["status"]

        # Batch auto-approve mode
        if batch_auto and status == "AUTO_ACCEPT":
            # Check for duplicate payment
            if billing:
                dup = check_duplicate_payment(
                    billing.get("patient_name", ""),
                    billing.get("service_date"),
                    billing.get("modality", ""),
                )
                if dup:
                    _print_duplicate_warning(claim, dup, i + 1, len(match_results))
                    batch_auto = False  # Drop out of batch mode for this one
                else:
                    approved.append(_build_approved_record(claim, billing, score_detail))
                    _record_user_decision(
                        session_id, era_file, claim, billing,
                        score_detail, status, "APPROVE", payer_name,
                    )
                    continue
            else:
                pass  # Unmatched — can't auto-approve

        # Present claim
        _present_claim(claim, billing, score_detail, status, i + 1, len(match_results))

        # Duplicate check
        if billing:
            dup = check_duplicate_payment(
                billing.get("patient_name", ""),
                billing.get("service_date"),
                billing.get("modality", ""),
            )
            if dup:
                print(f"\n  ** DUPLICATE WARNING: Already paid ${dup.get('claim_paid', 0)} "
                      f"on {dup.get('timestamp', '?')[:10]}")

        # Get decision
        decision = _get_user_decision(status)

        if decision == "A":
            if billing:
                approved.append(_build_approved_record(claim, billing, score_detail))
                paid = claim.get("paid_amount", Decimal("0"))
                if paid > 0:
                    print(f"\n  >> APPROVED — ${paid} payment recorded")
                else:
                    print(f"\n  >> APPROVED — $0.00 (denial recorded for follow-up)")
            else:
                print("\n  !! Cannot approve — no matching billing record")
                skipped.append(mr)
                continue
            _record_user_decision(
                session_id, era_file, claim, billing,
                score_detail, status, "APPROVE", payer_name,
            )

        elif decision == "R":
            rejected.append(mr)
            print("\n  >> REJECTED")
            _record_user_decision(
                session_id, era_file, claim, billing,
                score_detail, status, "REJECT", payer_name,
            )

        elif decision == "S":
            skipped.append(mr)
            print("\n  >> SKIPPED")
            _record_user_decision(
                session_id, era_file, claim, billing,
                score_detail, status, "SKIP", payer_name,
            )

        elif decision == "M":
            # Manual match
            picked = _manual_match_picker(claim, billing_records, approved)
            if picked:
                new_score = compute_match_score(picked, claim)
                approved.append(_build_approved_record(claim, picked, new_score))
                paid = claim.get("paid_amount", Decimal("0"))
                print(f"\n  >> MANUALLY MATCHED & APPROVED — ${paid}")
                _record_user_decision(
                    session_id, era_file, claim, picked,
                    new_score, "MANUAL", "APPROVE", payer_name,
                )
            else:
                skipped.append(mr)
                print("\n  >> No selection made — skipped")

        elif decision == "B":
            # Enter batch mode
            batch_auto = True
            # Process current claim as auto-approve if eligible
            if status == "AUTO_ACCEPT" and billing:
                approved.append(_build_approved_record(claim, billing, score_detail))
                paid = claim.get("paid_amount", Decimal("0"))
                print(f"\n  >> BATCH AUTO — ${paid}")
                _record_user_decision(
                    session_id, era_file, claim, billing,
                    score_detail, status, "APPROVE", payer_name,
                )
            else:
                # Not auto-acceptable — still need manual decision
                print("\n  !! Not auto-acceptable. Enter decision for this claim:")
                batch_auto = False
                skipped.append(mr)

        elif decision == "Q":
            # Save state and quit
            state = {
                "era_file": era_file,
                "next_index": i,
                "session_id": session_id,
                "approved_count": len(approved),
            }
            pending_path = PENDING_DIR / f"pending_{session_id}.json"
            save_session_state(state, pending_path)
            print(f"\n  Session saved to {pending_path}")
            print(f"  Resume with: ocdr apply-835 --input {era_file} --resume {pending_path}")
            break

    # Write output
    if approved:
        out = output_path or str(
            EXPORT_DIR / f"applied_{datetime.now().strftime('%Y%m%d')}.xlsx"
        )
        write_payment_applied(out, approved)
    else:
        out = None

    # Print summary
    _print_summary(approved, rejected, skipped, out)

    return Path(out) if out else None


# ── Internal helpers ──────────────────────────────────────────────────────


def _match_all(claims, billing_records, compute_match_score):
    """Match each claim to the best billing record."""
    from ocdr.config import MATCH_AUTO_ACCEPT, MATCH_REVIEW

    results = []
    used: set[int] = set()

    for claim in claims:
        best_match = None
        best_score_val = 0.0
        best_score_detail = None
        best_idx = -1

        for idx, br in enumerate(billing_records):
            if idx in used:
                continue
            score_detail = compute_match_score(br, claim)
            if score_detail["score"] > best_score_val:
                best_score_val = score_detail["score"]
                best_score_detail = score_detail
                best_match = br
                best_idx = idx

        if best_match and best_score_val >= MATCH_REVIEW:
            used.add(best_idx)
            status = "AUTO_ACCEPT" if best_score_val >= MATCH_AUTO_ACCEPT else "REVIEW"
        else:
            status = "UNMATCHED"

        results.append({
            "claim": claim,
            "billing_record": best_match if status != "UNMATCHED" else None,
            "match_score": best_score_detail or {"score": 0, "mismatches": ["No match"]},
            "status": status,
        })

    return results


def _print_header(payer, check, amount, pay_date, claim_count):
    print()
    print("=" * 62)
    print(f"  835 Payment Review — {payer} (Check #{check})")
    date_str = pay_date.strftime("%m/%d/%Y") if pay_date else "N/A"
    print(f"  Payment: ${amount} | Date: {date_str} | Claims: {claim_count}")
    print("=" * 62)


def _present_claim(claim, billing, score_detail, status, num, total):
    score_val = score_detail.get("score", 0)
    print()
    print(f"-- Claim {num} of {total} -- [{status}  Score: {score_val:.2f}] "
          + "-" * 20)

    # ERA claim info
    patient = claim.get("patient_name", "?")
    svc_date = claim.get("service_date", "?")
    cpts = ", ".join(claim.get("cpt_codes", []) or [])
    billed = claim.get("billed_amount", Decimal("0"))
    paid = claim.get("paid_amount", Decimal("0"))
    print(f"\n  ERA Claim:     {patient} | {svc_date} | CPT {cpts}")
    print(f"                 Billed: ${billed} | Paid: ${paid}")

    # Adjustments
    for adj in claim.get("adjustments", []):
        for sub in adj.get("adjustments", []):
            print(f"                 Adj: {adj.get('group_code', '')}:"
                  f"{sub.get('reason_code', '')}=${sub.get('amount', 0)} "
                  f"({adj.get('group_name', '')})")

    # Matched billing record
    if billing:
        bp = billing.get("patient_name", "?")
        bd = billing.get("service_date", "?")
        bmod = billing.get("modality", "?")
        bscan = billing.get("scan_type", "?")
        brow = billing.get("source_row", "?")
        expected = get_expected_rate(
            billing.get("modality", ""),
            billing.get("insurance_carrier", "DEFAULT"),
            billing.get("is_psma", False),
            billing.get("gado_used", False),
        )
        print(f"\n  Matched to:    {bp} | {bd} | {bmod} | {bscan}")
        print(f"                 Row {brow} in OCMRI.xlsx")
        print(f"                 Expected rate: ${expected}")
    else:
        print("\n  Matched to:    ** NO MATCH FOUND **")

    # Score breakdown
    ns = score_detail.get("name_sim", 0)
    dm = score_detail.get("date_match", 0)
    mm = score_detail.get("modality_match", 0)
    bm = score_detail.get("body_part_match", 0)
    warn = lambda v: " !!" if v < 1.0 else ""
    print(f"\n  Score:  Name {ns:.0%}{warn(ns)}  Date {dm:.0%}{warn(dm)}  "
          f"Modality {mm:.0%}{warn(mm)}  Body {bm:.0%}{warn(bm)}")

    # Mismatches
    for m in score_detail.get("mismatches", []):
        print(f"  !! {m}")


def _print_duplicate_warning(claim, dup, num, total):
    print(f"\n-- Claim {num} of {total} -- [DUPLICATE WARNING] " + "-" * 15)
    print(f"  {claim.get('patient_name', '?')} | "
          f"Already paid ${dup.get('claim_paid', 0)} "
          f"on {dup.get('timestamp', '?')[:10]}")


def _get_user_decision(status: str) -> str:
    """Prompt the user for a decision. Returns A/R/S/M/Q/B."""
    valid = {"A", "R", "S", "M", "Q", "B"}
    while True:
        print("\n  [A]pprove  [R]eject  [S]kip  [M]anual match  "
              "[B]atch auto  [Q]uit")
        try:
            choice = input("  > ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            return "Q"
        if choice in valid:
            return choice
        if choice:
            print(f"  Invalid choice '{choice}'. Use A/R/S/M/B/Q.")


def _manual_match_picker(claim, billing_records, already_approved):
    """Show top candidates for manual matching."""
    from ocdr.business_rules import compute_match_score

    used_names = {r.get("patient_name", "") + str(r.get("service_date", ""))
                  for r in already_approved}

    candidates = []
    for idx, br in enumerate(billing_records):
        key = br.get("patient_name", "") + str(br.get("service_date", ""))
        if key in used_names:
            continue
        score = compute_match_score(br, claim)
        candidates.append((idx, br, score))

    candidates.sort(key=lambda x: x[2]["score"], reverse=True)
    candidates = candidates[:10]

    if not candidates:
        print("\n  No candidates available.")
        return None

    print("\n  Manual Match — Top candidates:")
    print("  " + "-" * 55)
    for rank, (idx, br, sc) in enumerate(candidates, 1):
        print(f"  {rank:2}. {br.get('patient_name', '?'):25s} | "
              f"{br.get('service_date', '?')} | "
              f"{br.get('modality', '?'):5s} | "
              f"Score: {sc['score']:.2f}")
    print(f"   0. Cancel")

    while True:
        try:
            choice = input("  Pick #> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice == "0":
            return None
        try:
            pick = int(choice) - 1
            if 0 <= pick < len(candidates):
                return candidates[pick][1]
        except ValueError:
            pass
        print("  Invalid selection.")


def _build_approved_record(claim: dict, billing: dict,
                            score_detail: dict) -> dict:
    """Merge claim payment data into billing record for output."""
    record = dict(billing)
    record["primary_payment"] = claim.get("paid_amount", Decimal("0"))
    record["claim_id"] = claim.get("claim_id", "")
    record["check_eft_number"] = claim.get("check_eft_number", "")
    record["payer_835"] = claim.get("payer_name", "")
    record["payment_date"] = claim.get("payment_date")
    record["payment_method"] = claim.get("payment_method", "")
    record["cpt_codes"] = ", ".join(claim.get("cpt_codes", []) or [])
    record["claim_billed"] = claim.get("billed_amount", Decimal("0"))
    record["claim_status"] = claim.get("claim_status", "")
    record["match_score"] = score_detail.get("score", 0)
    record["approval_timestamp"] = datetime.now().isoformat()

    # Compute total if not set
    primary = record.get("primary_payment", Decimal("0"))
    secondary = record.get("secondary_payment", Decimal("0"))
    if not isinstance(secondary, Decimal):
        secondary = Decimal(str(secondary or 0))
    if not isinstance(primary, Decimal):
        primary = Decimal(str(primary or 0))
    record["total_payment"] = primary + secondary

    return record


def _record_user_decision(session_id, era_file, claim, billing,
                           score_detail, system_status, user_decision,
                           payer_name):
    """Log the decision to the persistent decision store."""
    record_decision({
        "session_id": session_id,
        "source_835": str(era_file),
        "claim_id": claim.get("claim_id", ""),
        "claim_patient": claim.get("patient_name", ""),
        "claim_date": str(claim.get("service_date", "")),
        "claim_paid": str(claim.get("paid_amount", "0")),
        "claim_cpt": claim.get("cpt_codes", []),
        "billing_patient": billing.get("patient_name", "") if billing else "",
        "billing_date": str(billing.get("service_date", "")) if billing else "",
        "billing_modality": billing.get("modality", "") if billing else "",
        "billing_scan_type": billing.get("scan_type", "") if billing else "",
        "billing_row": billing.get("source_row") if billing else None,
        "match_score": score_detail.get("score", 0),
        "match_breakdown": {
            "name_sim": score_detail.get("name_sim", 0),
            "date_match": score_detail.get("date_match", 0),
            "modality_match": score_detail.get("modality_match", 0),
            "body_part_match": score_detail.get("body_part_match", 0),
        },
        "mismatches": score_detail.get("mismatches", []),
        "system_status": system_status,
        "user_decision": user_decision,
        "payer": payer_name,
        "insurance_carrier": (billing or {}).get("insurance_carrier", ""),
    })

    logger.log_decision(
        "user_approval",
        {"claim_id": claim.get("claim_id"), "patient": claim.get("patient_name")},
        {"decision": user_decision, "system_status": system_status,
         "score": score_detail.get("score", 0)},
        flags=score_detail.get("mismatches", []),
        confidence=score_detail.get("score", 0),
        reasoning=f"User {user_decision.lower()}d claim "
                  f"{claim.get('claim_id', '?')} ({system_status})",
    )


def _print_summary(approved, rejected, skipped, output_path):
    total_paid = sum(
        float(r.get("primary_payment", 0) or 0) for r in approved
    )
    print()
    print("=" * 62)
    print(f"  Summary: {len(approved)} approved, {len(rejected)} rejected, "
          f"{len(skipped)} skipped")
    print(f"  Total applied: ${total_paid:,.2f}")
    if output_path:
        print(f"  Output: {output_path}")
    print("=" * 62)
    print()
