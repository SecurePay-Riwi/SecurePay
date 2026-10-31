"""The alerts task: every 5 minutes in AWS (EventBridge -> Lambda), every
ALERTS_INTERVAL_SECONDS in local (python -m services.alerts).

Each job gets the same `now` and runs in its own try, so one failure does
not stop the others; a failed job rolls back and runs again next time.
Every job is safe to run twice.
"""

import logging
from datetime import UTC, datetime

from services.alerts import account_history, compliance_summary, escalation
from shared import db

log = logging.getLogger(__name__)

SessionLocal = db.SessionLocal

# In this order. HU-32 adds the archive() retry for RESOLVED cases with
# evidence_key null.
JOBS = {
    "escalated": lambda session, now: escalation.escalate_overdue(session, now),
    "notified": lambda session, now: compliance_summary.send_summary(session, now),
    "purged": lambda session, now: account_history.purge(session, now),
}


def handler(event=None, context=None) -> dict:
    """Run every job and return how many items each one handled (None for
    a job that failed)."""
    now = datetime.now(UTC)
    counts: dict[str, int | None] = {}
    with SessionLocal() as session:
        for name, job in JOBS.items():
            try:
                counts[name] = job(session, now)
            except Exception:
                log.exception("Alerts: %s failed", name)
                session.rollback()
                counts[name] = None
    log.info("Alerts: %s", counts)
    return counts
