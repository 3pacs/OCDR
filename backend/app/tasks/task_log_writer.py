"""Write TASKS.md — an LLM-readable log of all business tasks, their status, and action steps.

This file is regenerated whenever tasks change. Any LLM connected to the codebase
can read TASKS.md to understand what needs to be done, what was done, and how to do it.
"""

import os
from datetime import date, datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.business_task import BusinessTask, TaskInstance
from backend.app.models.insight_log import InsightLog

TASKS_MD_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "TASKS.md")


async def write_tasks_md(db: AsyncSession) -> str:
    """Regenerate TASKS.md with current task state. Returns the file path."""
    today = date.today()
    week_ago = today - timedelta(days=7)

    # Fetch all templates
    result = await db.execute(
        select(BusinessTask).order_by(BusinessTask.frequency, BusinessTask.priority)
    )
    templates = result.scalars().all()

    # Fetch today's instances
    result = await db.execute(
        select(TaskInstance, BusinessTask)
        .join(BusinessTask, TaskInstance.task_id == BusinessTask.id)
        .where(TaskInstance.due_date == today)
        .order_by(BusinessTask.priority)
    )
    today_rows = result.all()

    # Fetch recent history (7 days)
    result = await db.execute(
        select(TaskInstance, BusinessTask)
        .join(BusinessTask, TaskInstance.task_id == BusinessTask.id)
        .where(TaskInstance.due_date >= week_ago)
        .order_by(TaskInstance.due_date.desc(), BusinessTask.priority)
    )
    history_rows = result.all()

    lines = []
    lines.append("# TASKS.md — Business Task Log")
    lines.append("")
    lines.append(f"> Auto-generated: {datetime.utcnow().isoformat()}Z")
    lines.append(f"> This file is updated whenever tasks change. LLMs: read this to understand current operational state.")
    lines.append("")

    # --- Today's checklist ---
    lines.append(f"## Today's Checklist ({today.isoformat()})")
    lines.append("")
    if today_rows:
        completed = sum(1 for inst, _ in today_rows if inst.status == "COMPLETED")
        total = len(today_rows)
        lines.append(f"**Progress: {completed}/{total} completed**")
        lines.append("")
        for inst, tmpl in today_rows:
            if inst.status == "COMPLETED":
                check = "[x]"
                suffix = f" *(completed {inst.completed_at.strftime('%H:%M') if inst.completed_at else ''})*"
            elif inst.status == "SKIPPED":
                check = "[-]"
                suffix = " *(skipped)*"
            else:
                check = "[ ]"
                suffix = f" *({tmpl.estimated_minutes or '?'}min)*"
            notes_suffix = f" — {inst.notes}" if inst.notes else ""
            lines.append(f"- {check} **{tmpl.title}**{suffix}{notes_suffix}")
        lines.append("")
    else:
        lines.append("*No tasks scheduled for today.*")
        lines.append("")

    # --- Recent completion history ---
    lines.append("## Recent History (7 days)")
    lines.append("")
    by_date = {}
    for inst, tmpl in history_rows:
        d = inst.due_date.isoformat()
        if d not in by_date:
            by_date[d] = []
        by_date[d].append((inst, tmpl))

    for d in sorted(by_date.keys(), reverse=True):
        items = by_date[d]
        done = sum(1 for inst, _ in items if inst.status == "COMPLETED")
        lines.append(f"### {d} — {done}/{len(items)} completed")
        for inst, tmpl in items:
            status = "DONE" if inst.status == "COMPLETED" else inst.status
            notes_suffix = f" — {inst.notes}" if inst.notes else ""
            lines.append(f"- [{status}] {tmpl.title}{notes_suffix}")
        lines.append("")

    # --- All task templates with action steps ---
    lines.append("---")
    lines.append("")
    lines.append("## Task Runbooks (Action Steps)")
    lines.append("")
    lines.append("Detailed step-by-step instructions for each recurring task.")
    lines.append("LLMs: use these to guide the user through task completion.")
    lines.append("")

    freq_order = ["DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY", "ONE_TIME"]
    freq_labels = {"DAILY": "Daily", "WEEKLY": "Weekly", "BIWEEKLY": "Bi-Weekly", "MONTHLY": "Monthly", "ONE_TIME": "One-Time"}
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    by_freq = {}
    for t in templates:
        if t.frequency not in by_freq:
            by_freq[t.frequency] = []
        by_freq[t.frequency].append(t)

    for freq in freq_order:
        tasks = by_freq.get(freq, [])
        if not tasks:
            continue

        lines.append(f"### {freq_labels.get(freq, freq)} Tasks")
        lines.append("")

        for t in tasks:
            active = "ACTIVE" if t.is_active else "INACTIVE"
            schedule = ""
            if freq == "WEEKLY" and t.schedule_day is not None:
                schedule = f" (every {day_names[t.schedule_day]})"
            elif freq == "MONTHLY" and t.schedule_day:
                schedule = f" (day {t.schedule_day})"
            elif freq == "BIWEEKLY" and t.schedule_day is not None:
                schedule = f" (every other {day_names[t.schedule_day]})"

            lines.append(f"#### {t.title} [{active}]{schedule}")
            lines.append("")
            if t.description:
                lines.append(f"*{t.description}*")
                lines.append("")
            lines.append(f"- **Category:** {t.category}")
            lines.append(f"- **Priority:** {t.priority} ({'Urgent' if t.priority == 1 else 'High' if t.priority == 2 else 'Normal' if t.priority == 3 else 'Low'})")
            if t.estimated_minutes:
                lines.append(f"- **Estimated time:** {t.estimated_minutes} minutes")
            if t.notes:
                lines.append(f"- **Notes:** {t.notes}")
            lines.append("")

            if t.action_steps:
                lines.append(t.action_steps.strip())
                lines.append("")

            lines.append("---")
            lines.append("")

    # --- Pipeline improvement notes ---
    lines.append("## Pipeline Improvement Notes")
    lines.append("")
    lines.append("User notes and status updates on pipeline improvement suggestions.")
    lines.append("LLMs: use these to understand what improvements have been acknowledged, are in progress, or resolved.")
    lines.append("")

    pipeline_result = await db.execute(
        select(InsightLog)
        .where(InsightLog.category.like("PIPELINE_%"))
        .order_by(InsightLog.severity, InsightLog.title)
    )
    pipeline_logs = pipeline_result.scalars().all()

    if pipeline_logs:
        for log in pipeline_logs:
            status_icon = {
                "OPEN": "🔵",
                "ACKNOWLEDGED": "👀",
                "IN_PROGRESS": "🔧",
                "RESOLVED": "✅",
                "DISMISSED": "❌",
            }.get(log.status, "⚪")
            lines.append(f"#### {status_icon} {log.title} [{log.status}]")
            lines.append("")
            lines.append(f"- **Severity:** {log.severity}")
            if log.estimated_impact:
                lines.append(f"- **Impact:** ${float(log.estimated_impact):,.0f}")
            if log.resolution_notes:
                lines.append(f"- **User notes:** {log.resolution_notes}")
            if log.resolved_at:
                lines.append(f"- **Resolved:** {log.resolved_at.isoformat()}")
            lines.append("")
    else:
        lines.append("*No pipeline suggestions persisted yet. Visit /pipeline to generate them.*")
        lines.append("")

    content = "\n".join(lines)

    # Write the file
    filepath = os.path.abspath(TASKS_MD_PATH)
    with open(filepath, "w") as f:
        f.write(content)

    return filepath
