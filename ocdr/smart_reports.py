"""
Smart reports that learn from past approval/rejection decisions.

Reads ``data/decisions/decisions.jsonl`` and generates insights:
  - Reconciliation summary (totals, rates, amounts)
  - Payer analysis (per-payer breakdown with warnings)
  - Learning insights (threshold recommendations, synonym suggestions)
  - Aging report (unpaid claims by age band)
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from ocdr.config import (
    get_expected_rate, get_payer, MATCH_AUTO_ACCEPT, MATCH_REVIEW,
    PAYER_CONFIG, UNDERPAYMENT_THRESHOLD,
)
from ocdr.decision_store import load_all_decisions, get_decision_stats


# ── Report 1: Reconciliation Summary ─────────────────────────────────────

def report_summary(as_excel: bool = False) -> dict:
    """Generate reconciliation summary from decision history.

    Returns stats dict AND prints to terminal.
    """
    stats = get_decision_stats()

    if stats["total"] == 0:
        print("\n  No decisions recorded yet. Run 'apply-835' first.\n")
        return stats

    print()
    print("=" * 54)
    print("  OCDR Reconciliation Summary")
    print("=" * 54)
    total = stats["total"]
    print(f"  Total claims reviewed:     {total:>6}")
    print(f"  Approved:                  {stats['approved']:>6} "
          f"({stats['approved']/total:.1%})")
    print(f"  Rejected:                  {stats['rejected']:>6} "
          f"({stats['rejected']/total:.1%})")
    print(f"  Skipped/Pending:           {stats['skipped']:>6} "
          f"({stats['skipped']/total:.1%})")
    print()
    print(f"  Auto-accepted (untouched): {stats['auto_accepted']:>6} "
          f"({stats['auto_accepted']/total:.1%})")
    print(f"  Manual review accepted:    {stats['review_accepted']:>6} "
          f"({stats['review_accepted']/total:.1%})")
    print(f"  Manual review rejected:    {stats['review_rejected']:>6} "
          f"({stats['review_rejected']/total:.1%})")
    print()
    print(f"  Total $ applied:       ${stats['total_approved_amount']:>12,.2f}")
    print(f"  Total $ rejected:      ${stats['total_rejected_amount']:>12,.2f}")
    print(f"  Total $ pending:       ${stats['total_skipped_amount']:>12,.2f}")
    print()
    print(f"  Avg match score (approved):  {stats['avg_score_approved']:.2f}")
    print(f"  Avg match score (rejected):  {stats['avg_score_rejected']:.2f}")
    print("=" * 54)
    print()

    return stats


# ── Report 2: Payer Analysis ─────────────────────────────────────────────

def report_payer() -> dict[str, dict]:
    """Per-payer breakdown with warnings."""
    decisions = load_all_decisions()
    if not decisions:
        print("\n  No decisions recorded yet.\n")
        return {}

    by_payer: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        payer = d.get("insurance_carrier") or d.get("payer", "UNKNOWN")
        by_payer[payer].append(d)

    results = {}
    print()
    print("=" * 72)
    print("  Payer Analysis")
    print("=" * 72)
    print(f"  {'Payer':<16} {'Claims':>6}  {'Approved':>8}  {'Avg Pay':>8}  "
          f"{'Denied':>6}  {'Underpaid':>9}")
    print("  " + "-" * 66)

    for payer in sorted(by_payer.keys()):
        ds = by_payer[payer]
        total = len(ds)
        approved = [d for d in ds if d.get("user_decision") == "APPROVE"]
        denied = [d for d in ds
                  if d.get("user_decision") == "APPROVE"
                  and float(d.get("claim_paid", 0) or 0) == 0]

        avg_pay = 0.0
        if approved:
            pays = [float(d.get("claim_paid", 0) or 0) for d in approved]
            avg_pay = sum(pays) / len(pays)

        # Count underpayments
        underpaid = 0
        for d in approved:
            paid = float(d.get("claim_paid", 0) or 0)
            mod = d.get("billing_modality", "")
            expected = float(get_expected_rate(mod, payer))
            if expected > 0 and paid > 0 and paid / expected < float(UNDERPAYMENT_THRESHOLD):
                underpaid += 1

        approval_rate = len(approved) / total if total else 0
        print(f"  {payer:<16} {total:>6}  {approval_rate:>7.1%}  "
              f"${avg_pay:>7,.0f}  {len(denied):>6}  "
              f"{underpaid:>5} ({underpaid/total:.0%})" if total else "")

        results[payer] = {
            "total": total,
            "approved": len(approved),
            "approval_rate": approval_rate,
            "avg_payment": avg_pay,
            "denied": len(denied),
            "underpaid": underpaid,
        }

        # Warnings
        payer_cfg = get_payer(payer)
        if total >= 5 and underpaid / total > 0.20:
            print(f"  !! {payer}: {underpaid/total:.0%} underpayment rate — "
                  f"significantly above threshold")
        if len(denied) >= 3:
            print(f"  !! {payer}: {len(denied)} denials — "
                  f"{payer_cfg['deadline']}-day filing deadline")

    print("=" * 72)
    print()
    return results


# ── Report 3: Learning Insights ──────────────────────────────────────────

def report_learning() -> dict:
    """Analyze decision history and suggest improvements."""
    decisions = load_all_decisions()
    if len(decisions) < 10:
        print(f"\n  Only {len(decisions)} decisions recorded. "
              f"Need at least 10 for learning insights.\n")
        return {}

    insights = {
        "threshold_recommendations": [],
        "synonym_suggestions": [],
        "payer_alias_suggestions": [],
        "scoring_insights": {},
    }

    # ── 1. Threshold analysis per payer ──
    by_payer: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        payer = d.get("insurance_carrier") or d.get("payer", "")
        if payer:
            by_payer[payer].append(d)

    print()
    print("=" * 60)
    print("  Learning Insights")
    print(f"  Based on {len(decisions)} decisions")
    print("=" * 60)

    print("\n  THRESHOLD RECOMMENDATIONS:")
    for payer, ds in sorted(by_payer.items()):
        if len(ds) < 5:
            continue
        # Find the lowest score that was always approved
        review_ds = [d for d in ds if d.get("system_status") == "REVIEW"]
        if not review_ds:
            continue
        approved_scores = sorted([
            d.get("match_score", 0) for d in review_ds
            if d.get("user_decision") == "APPROVE"
        ])
        rejected_scores = sorted([
            d.get("match_score", 0) for d in review_ds
            if d.get("user_decision") == "REJECT"
        ])
        if approved_scores:
            min_approved = approved_scores[0]
            # Check if any rejections above this score
            rejections_above = [s for s in rejected_scores if s >= min_approved]
            if not rejections_above and min_approved < MATCH_AUTO_ACCEPT:
                rec = (f"{payer}: Auto-accept at {min_approved:.2f} "
                       f"(100% user approval above this score, "
                       f"{len(approved_scores)} samples)")
                insights["threshold_recommendations"].append(rec)
                print(f"  * {rec}")

    if not insights["threshold_recommendations"]:
        print("  (No threshold changes recommended yet)")

    # ── 2. Body part mismatch patterns ──
    print("\n  BODY PART SYNONYMS TO ADD:")
    bp_mismatches: dict[tuple, int] = defaultdict(int)
    for d in decisions:
        if d.get("user_decision") == "APPROVE":
            for m in d.get("mismatches", []):
                if "Body part" in m:
                    # Extract the two body parts
                    parts = m.split("'")
                    if len(parts) >= 4:
                        bp1 = parts[1].upper()
                        bp2 = parts[3].upper()
                        key = tuple(sorted([bp1, bp2]))
                        bp_mismatches[key] += 1

    for (bp1, bp2), count in sorted(bp_mismatches.items(),
                                     key=lambda x: -x[1]):
        if count >= 2:
            syn = f'"{bp1}" <-> "{bp2}" — caused {count} unnecessary REVIEW flags'
            insights["synonym_suggestions"].append(syn)
            print(f"  * {syn}")

    if not insights["synonym_suggestions"]:
        print("  (No synonym suggestions yet)")

    # ── 3. Payer alias suggestions ──
    print("\n  PAYER ALIAS SUGGESTIONS:")
    payer_names_835: dict[str, int] = defaultdict(int)
    for d in decisions:
        p835 = d.get("payer", "")
        carrier = d.get("insurance_carrier", "")
        if p835 and carrier and p835 != carrier:
            payer_names_835[(p835, carrier)] += 1

    for (p835, carrier), count in sorted(payer_names_835.items(),
                                          key=lambda x: -x[1]):
        if count >= 2:
            alias = f'"{p835}" -> "{carrier}" — seen in {count} claims'
            insights["payer_alias_suggestions"].append(alias)
            print(f"  * {alias}")

    if not insights["payer_alias_suggestions"]:
        print("  (No alias suggestions yet)")

    # ── 4. Scoring insights ──
    print("\n  SCORING INSIGHTS:")
    score_buckets = defaultdict(lambda: {"approved": 0, "rejected": 0})
    for d in decisions:
        score = d.get("match_score", 0)
        bucket = round(score, 1)  # 0.8, 0.9, 1.0
        if d.get("user_decision") == "APPROVE":
            score_buckets[bucket]["approved"] += 1
        elif d.get("user_decision") == "REJECT":
            score_buckets[bucket]["rejected"] += 1

    for bucket in sorted(score_buckets.keys(), reverse=True):
        data = score_buckets[bucket]
        total = data["approved"] + data["rejected"]
        if total > 0:
            rate = data["approved"] / total
            print(f"  * Score {bucket:.1f}: {rate:.1%} approval rate "
                  f"({total} claims)")
            insights["scoring_insights"][str(bucket)] = {
                "approval_rate": rate,
                "total": total,
            }

    # Primary rejection reasons
    rejection_reasons: dict[str, int] = defaultdict(int)
    for d in decisions:
        if d.get("user_decision") == "REJECT":
            for m in d.get("mismatches", []):
                if "Name" in m:
                    rejection_reasons["name_mismatch"] += 1
                elif "Date" in m:
                    rejection_reasons["date_mismatch"] += 1
                elif "Modality" in m:
                    rejection_reasons["modality_mismatch"] += 1
                elif "Body" in m:
                    rejection_reasons["body_part_mismatch"] += 1

    if rejection_reasons:
        total_reasons = sum(rejection_reasons.values())
        print("\n  PRIMARY REJECTION REASONS:")
        for reason, count in sorted(rejection_reasons.items(),
                                     key=lambda x: -x[1]):
            print(f"  * {reason}: {count} ({count/total_reasons:.0%})")

    print("=" * 60)
    print()
    return insights


# ── Report 4: Aging Report ───────────────────────────────────────────────

def report_aging(billing_records: list[dict],
                 as_of: date | None = None) -> list[dict]:
    """Unpaid claims grouped by age bands.

    Args:
        billing_records: Records from read_ocmri().
        as_of: Reference date (default: today).
    """
    if as_of is None:
        as_of = date.today()

    unpaid = [r for r in billing_records
              if r.get("total_payment", Decimal("0")) == Decimal("0")
              and r.get("service_date")]

    bands = [
        ("0-30 days", 0, 30),
        ("31-60 days", 31, 60),
        ("61-90 days", 61, 90),
        ("91-180 days", 91, 180),
        ("181-365 days", 181, 365),
        ("365+ days", 366, 99999),
    ]

    results = []
    print()
    print("=" * 60)
    print(f"  Aging Report (as of {as_of.strftime('%m/%d/%Y')})")
    print("=" * 60)
    print(f"  {'Age Band':<16} {'Claims':>6}   {'Amount':>10}    {'Top Payer'}")
    print("  " + "-" * 52)

    for label, lo, hi in bands:
        band_records = []
        for r in unpaid:
            age = (as_of - r["service_date"]).days
            if lo <= age <= hi:
                band_records.append(r)

        if not band_records:
            continue

        total_amount = sum(
            float(get_expected_rate(
                r.get("modality", ""),
                r.get("insurance_carrier", "DEFAULT"),
                r.get("is_psma", False),
                r.get("gado_used", False),
            ))
            for r in band_records
        )

        # Top payer
        payer_counts: dict[str, int] = defaultdict(int)
        for r in band_records:
            payer_counts[r.get("insurance_carrier", "?")] += 1
        top_payer = max(payer_counts, key=payer_counts.get)
        top_count = payer_counts[top_payer]

        warn = ""
        if hi <= 90:
            # Check for approaching deadlines
            for r in band_records:
                deadline_days = get_payer(r.get("insurance_carrier", ""))["deadline"]
                if (as_of - r["service_date"]).days > deadline_days - 30:
                    warn = " !!"
                    break
        if hi > 365:
            warn = " !! PAST DEADLINE"

        print(f"  {label:<16} {len(band_records):>6}   "
              f"${total_amount:>9,.0f}    {top_payer} ({top_count}){warn}")

        results.append({
            "band": label,
            "claims": len(band_records),
            "amount": total_amount,
            "top_payer": top_payer,
            "records": band_records,
        })

    print("=" * 60)
    print()
    return results
