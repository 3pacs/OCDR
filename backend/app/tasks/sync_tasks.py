"""
Celery tasks for external system synchronization (Office Ally, Purview).
Stubs — full implementation in Steps 5 and 6.
"""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.sync_tasks.sync_office_ally_claim_status", bind=True, max_retries=3)
def sync_office_ally_claim_status(self):
    """Pull claim status updates from Office Ally on a schedule."""
    try:
        from app.integrations.office_ally import OfficeAllyClient
        client = OfficeAllyClient()
        return client.sync_claim_statuses()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@celery_app.task(name="app.tasks.sync_tasks.push_claim_to_office_ally", bind=True, max_retries=3)
def push_claim_to_office_ally(self, claim_id: int):
    """Push a single claim to Office Ally in 837P format."""
    try:
        from app.integrations.office_ally import OfficeAllyClient
        client = OfficeAllyClient()
        return client.submit_claim(claim_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
