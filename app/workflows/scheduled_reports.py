"""
Periodic summary report generation.

Generates daily and weekly HTML summary reports using SQL aggregate queries.
All user-supplied data is escaped with markupsafe.escape() for safe HTML output.
"""

from datetime import date, timedelta
from markupsafe import escape
from sqlalchemy import func, and_
from app.models import db, BillingRecord, ClaimStatusHistory


def _query_period_stats(start_date, end_date):
    """Query aggregate statistics for a date range.

    Uses SQL aggregates -- does NOT load all records into memory.

    Args:
        start_date: Start date (inclusive).
        end_date: End date (inclusive).

    Returns:
        dict with new_claims, revenue, denials, avg_payment.
    """
    row = db.session.query(
        func.count(BillingRecord.id).label("new_claims"),
        func.coalesce(func.sum(BillingRecord.total_payment), 0.0).label("revenue"),
        func.sum(
            func.iif(
                BillingRecord.denial_status.in_(["DENIED", "APPEALED"]),
                1, 0
            )
        ).label("denials"),
        func.coalesce(func.avg(BillingRecord.total_payment), 0.0).label("avg_payment"),
    ).filter(
        BillingRecord.service_date >= start_date,
        BillingRecord.service_date <= end_date,
    ).one()

    return {
        "new_claims": int(row.new_claims or 0),
        "revenue": round(float(row.revenue or 0), 2),
        "denials": int(row.denials or 0),
        "avg_payment": round(float(row.avg_payment or 0), 2),
    }


def _query_appeals_resolved(start_date, end_date):
    """Count appeals resolved (transitioned from APPEALED to PAID/PARTIAL/WRITTEN_OFF).

    Uses ClaimStatusHistory to find resolution transitions within the period.
    """
    count = db.session.query(
        func.count(ClaimStatusHistory.id)
    ).filter(
        ClaimStatusHistory.old_status == "APPEALED",
        ClaimStatusHistory.new_status.in_(["PAID", "PARTIAL", "WRITTEN_OFF"]),
        ClaimStatusHistory.created_at >= start_date.isoformat(),
        ClaimStatusHistory.created_at < (end_date + timedelta(days=1)).isoformat(),
    ).scalar()

    return int(count or 0)


def _query_upcoming_deadlines(as_of_date, days_ahead=14):
    """Count claims with appeal deadlines in the next N days."""
    deadline_end = as_of_date + timedelta(days=days_ahead)
    count = db.session.query(
        func.count(BillingRecord.id)
    ).filter(
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline >= as_of_date,
        BillingRecord.appeal_deadline <= deadline_end,
        BillingRecord.denial_status.in_(["DENIED", "APPEALED"]),
    ).scalar()

    return int(count or 0)


def _query_carrier_breakdown(start_date, end_date):
    """Get per-carrier claim count and revenue for a date range."""
    rows = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("claim_count"),
        func.coalesce(func.sum(BillingRecord.total_payment), 0.0).label("revenue"),
        func.sum(
            func.iif(
                BillingRecord.denial_status.in_(["DENIED", "APPEALED"]),
                1, 0
            )
        ).label("denials"),
    ).filter(
        BillingRecord.service_date >= start_date,
        BillingRecord.service_date <= end_date,
    ).group_by(
        BillingRecord.insurance_carrier,
    ).order_by(
        func.sum(BillingRecord.total_payment).desc(),
    ).all()

    return [
        {
            "carrier": row[0] or "UNKNOWN",
            "claim_count": int(row[1]),
            "revenue": round(float(row[2]), 2),
            "denials": int(row[3] or 0),
        }
        for row in rows
    ]


def generate_daily_summary() -> dict:
    """Generate a daily summary report.

    Returns:
        {
            "date": str (ISO format),
            "new_claims": int,
            "revenue_today": float,
            "denials_today": int,
            "appeals_resolved": int,
            "upcoming_deadlines": int,
            "html": str  (full HTML report),
        }
    """
    today = date.today()
    stats = _query_period_stats(today, today)
    appeals_resolved = _query_appeals_resolved(today, today)
    upcoming_deadlines = _query_upcoming_deadlines(today)

    report_data = {
        "date": today.isoformat(),
        "new_claims": stats["new_claims"],
        "revenue_today": stats["revenue"],
        "denials_today": stats["denials"],
        "appeals_resolved": appeals_resolved,
        "upcoming_deadlines": upcoming_deadlines,
    }

    # Generate HTML
    report_data["html"] = _render_daily_html(report_data)
    return report_data


def _render_daily_html(data: dict) -> str:
    """Render the daily summary as HTML with escaped user data."""
    report_date = escape(data["date"])
    new_claims = int(data["new_claims"])
    revenue = float(data["revenue_today"])
    denials = int(data["denials_today"])
    appeals_resolved = int(data["appeals_resolved"])
    upcoming_deadlines = int(data["upcoming_deadlines"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Daily Summary - {report_date}</title>
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            max-width: 800px;
            margin: 20px auto;
            color: #333;
            background: #fafafa;
        }}
        .report-header {{
            background: #1a1a2e;
            color: #fff;
            padding: 20px 30px;
            border-radius: 8px 8px 0 0;
        }}
        .report-header h1 {{
            margin: 0;
            font-size: 22px;
        }}
        .report-header p {{
            margin: 5px 0 0;
            opacity: 0.8;
            font-size: 14px;
        }}
        .metrics {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            padding: 20px 30px;
            background: #fff;
            border: 1px solid #e0e0e0;
        }}
        .metric-card {{
            flex: 1;
            min-width: 140px;
            background: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            border: 1px solid #e9ecef;
        }}
        .metric-card .value {{
            font-size: 28px;
            font-weight: bold;
            color: #1a1a2e;
        }}
        .metric-card .label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-top: 5px;
        }}
        .metric-card.warning .value {{
            color: #e67e22;
        }}
        .metric-card.danger .value {{
            color: #c0392b;
        }}
        .metric-card.success .value {{
            color: #27ae60;
        }}
        .footer {{
            padding: 15px 30px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-top: none;
            border-radius: 0 0 8px 8px;
            font-size: 12px;
            color: #888;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="report-header">
        <h1>Daily Summary Report</h1>
        <p>{report_date}</p>
    </div>
    <div class="metrics">
        <div class="metric-card">
            <div class="value">{new_claims}</div>
            <div class="label">New Claims</div>
        </div>
        <div class="metric-card success">
            <div class="value">${revenue:,.2f}</div>
            <div class="label">Revenue Today</div>
        </div>
        <div class="metric-card{"" if denials == 0 else " danger"}">
            <div class="value">{denials}</div>
            <div class="label">Denials Today</div>
        </div>
        <div class="metric-card success">
            <div class="value">{appeals_resolved}</div>
            <div class="label">Appeals Resolved</div>
        </div>
        <div class="metric-card{"" if upcoming_deadlines == 0 else " warning"}">
            <div class="value">{upcoming_deadlines}</div>
            <div class="label">Upcoming Deadlines</div>
        </div>
    </div>
    <div class="footer">
        Generated automatically. Data reflects claims with service date of {report_date}.
    </div>
</body>
</html>"""


def generate_weekly_summary() -> dict:
    """Generate a weekly summary with trends.

    Compares the current week (Mon-Sun) with the previous week
    to calculate revenue change percentage.

    Returns:
        {
            "week_start": str, "week_end": str,
            "total_revenue": float, "revenue_change_pct": float,
            "total_claims": int,
            "denials": int, "resolved": int,
            "by_carrier": [
                {"carrier": str, "claim_count": int, "revenue": float, "denials": int},
                ...
            ],
            "html": str,
        }
    """
    today = date.today()
    # Current week: Monday through today (or Sunday if complete)
    week_start = today - timedelta(days=today.weekday())
    week_end = today

    # Previous week for trend comparison
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)

    # Current week stats
    current_stats = _query_period_stats(week_start, week_end)
    prev_stats = _query_period_stats(prev_week_start, prev_week_end)

    # Revenue change percentage
    if prev_stats["revenue"] > 0:
        revenue_change_pct = round(
            ((current_stats["revenue"] - prev_stats["revenue"]) / prev_stats["revenue"]) * 100,
            1,
        )
    else:
        revenue_change_pct = 0.0 if current_stats["revenue"] == 0 else 100.0

    # Appeals resolved this week
    resolved = _query_appeals_resolved(week_start, week_end)

    # Per-carrier breakdown
    by_carrier = _query_carrier_breakdown(week_start, week_end)

    report_data = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_revenue": current_stats["revenue"],
        "revenue_change_pct": revenue_change_pct,
        "total_claims": current_stats["new_claims"],
        "denials": current_stats["denials"],
        "resolved": resolved,
        "by_carrier": by_carrier,
    }

    report_data["html"] = _render_weekly_html(report_data)
    return report_data


def _render_weekly_html(data: dict) -> str:
    """Render the weekly summary as HTML with escaped user data."""
    week_start = escape(data["week_start"])
    week_end = escape(data["week_end"])
    total_revenue = float(data["total_revenue"])
    revenue_change_pct = float(data["revenue_change_pct"])
    total_claims = int(data["total_claims"])
    denials = int(data["denials"])
    resolved = int(data["resolved"])
    by_carrier = data.get("by_carrier", [])

    # Revenue trend indicator
    if revenue_change_pct > 0:
        trend_class = "success"
        trend_arrow = "&#9650;"  # up triangle
        trend_sign = "+"
    elif revenue_change_pct < 0:
        trend_class = "danger"
        trend_arrow = "&#9660;"  # down triangle
        trend_sign = ""
    else:
        trend_class = ""
        trend_arrow = "&#9644;"  # dash
        trend_sign = ""

    # Build carrier rows
    carrier_rows = ""
    for c in by_carrier:
        carrier_name = escape(c.get("carrier", "UNKNOWN"))
        c_count = int(c.get("claim_count", 0))
        c_revenue = float(c.get("revenue", 0))
        c_denials = int(c.get("denials", 0))
        carrier_rows += f"""
        <tr>
            <td>{carrier_name}</td>
            <td style="text-align:right;">{c_count}</td>
            <td style="text-align:right;">${c_revenue:,.2f}</td>
            <td style="text-align:right;">{c_denials}</td>
        </tr>"""

    if not carrier_rows:
        carrier_rows = """
        <tr>
            <td colspan="4" style="text-align:center; color:#888;">No data for this period.</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Weekly Summary - {week_start} to {week_end}</title>
    <style>
        body {{
            font-family: Arial, Helvetica, sans-serif;
            max-width: 900px;
            margin: 20px auto;
            color: #333;
            background: #fafafa;
        }}
        .report-header {{
            background: #1a1a2e;
            color: #fff;
            padding: 20px 30px;
            border-radius: 8px 8px 0 0;
        }}
        .report-header h1 {{
            margin: 0;
            font-size: 22px;
        }}
        .report-header p {{
            margin: 5px 0 0;
            opacity: 0.8;
            font-size: 14px;
        }}
        .content {{
            background: #fff;
            border: 1px solid #e0e0e0;
            padding: 20px 30px;
        }}
        .metrics {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-bottom: 25px;
        }}
        .metric-card {{
            flex: 1;
            min-width: 130px;
            background: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            border: 1px solid #e9ecef;
        }}
        .metric-card .value {{
            font-size: 26px;
            font-weight: bold;
            color: #1a1a2e;
        }}
        .metric-card .label {{
            font-size: 11px;
            color: #666;
            text-transform: uppercase;
            margin-top: 5px;
        }}
        .metric-card .trend {{
            font-size: 13px;
            margin-top: 4px;
        }}
        .success {{ color: #27ae60; }}
        .danger {{ color: #c0392b; }}
        .warning {{ color: #e67e22; }}
        h2 {{
            font-size: 16px;
            color: #1a1a2e;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-size: 12px;
            text-transform: uppercase;
            color: #555;
        }}
        tr:hover td {{
            background: #f5f7fa;
        }}
        .footer {{
            padding: 15px 30px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-top: none;
            border-radius: 0 0 8px 8px;
            font-size: 12px;
            color: #888;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="report-header">
        <h1>Weekly Summary Report</h1>
        <p>{week_start} &mdash; {week_end}</p>
    </div>
    <div class="content">
        <div class="metrics">
            <div class="metric-card">
                <div class="value">{total_claims}</div>
                <div class="label">Total Claims</div>
            </div>
            <div class="metric-card">
                <div class="value">${total_revenue:,.2f}</div>
                <div class="label">Total Revenue</div>
                <div class="trend {trend_class}">
                    {trend_arrow} {trend_sign}{revenue_change_pct:.1f}% vs prev week
                </div>
            </div>
            <div class="metric-card{"" if denials == 0 else " danger"}">
                <div class="value">{denials}</div>
                <div class="label">Denials</div>
            </div>
            <div class="metric-card">
                <div class="value">{resolved}</div>
                <div class="label">Appeals Resolved</div>
            </div>
        </div>

        <h2>Breakdown by Carrier</h2>
        <table>
            <thead>
                <tr>
                    <th>Carrier</th>
                    <th style="text-align:right;">Claims</th>
                    <th style="text-align:right;">Revenue</th>
                    <th style="text-align:right;">Denials</th>
                </tr>
            </thead>
            <tbody>
                {carrier_rows}
            </tbody>
        </table>
    </div>
    <div class="footer">
        Generated automatically. Data reflects service dates {week_start} through {week_end}.
    </div>
</body>
</html>"""
