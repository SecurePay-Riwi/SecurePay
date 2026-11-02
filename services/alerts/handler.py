"""The alerts task: every 5 minutes in AWS (EventBridge -> Lambda), every
ALERTS_INTERVAL_SECONDS in local (python -m services.alerts).

Each job gets the same `now` and runs in its own try, so one failure does
not stop the others; a failed job rolls back and runs again next time.
Every job is safe to run twice.

In AWS the first run of each Lambda container also creates the case
tables (``ensure_schema``): a Lambda has no startup step like
``python -m services.alerts``.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from services.alerts import account_history, compliance_summary, escalation, reconciliation_check
from shared import db, evidence
from shared.cases import create_schema

log = logging.getLogger(__name__)

SessionLocal = db.SessionLocal

# True once the case tables exist (one check per Lambda container).
_schema_ready = False

# In this order. "archived" retries the evidence of RESOLVED cases whose
# evidence_key is still null (HU-32).
JOBS = {
    "escalated": lambda session, now: escalation.escalate_overdue(session, now),
    "notified": lambda session, now: compliance_summary.send_summary(session, now),
    "purged": lambda session, now: account_history.purge(session, now),
    "archived": lambda session, now: evidence.archive_pending(session),
}


def ensure_schema() -> None:
    """Create the case tables the first time this process runs the task.
    create_schema() is idempotent and takes an advisory lock. If PostgreSQL
    is down it only logs: the jobs fail too and run again in 5 minutes."""
    global _schema_ready
    if _schema_ready:
        return
    try:
        with SessionLocal() as session:
            create_schema(session)
    except SQLAlchemyError:
        log.exception("Alerts: could not create the case tables")
        return
    _schema_ready = True


def handler(event=None, context=None) -> dict:
    """Run every job and return how many items each one handled (None for
    a job that failed). {"job": "reconciliation_check"} (the 06:30 schedule,
    HU-36) runs only that check."""
    if (event or {}).get("job") == "reconciliation_check":
        return run_reconciliation_check()
    ensure_schema()
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


def run_reconciliation_check() -> dict:
    """{"reconciliation_done": True/False}, or None if the check failed
    (logged as ERROR, which the alerts alarm counts)."""
    with SessionLocal() as session:
        try:
            done = reconciliation_check.check(session, datetime.now(UTC))
        except Exception:
            log.exception("Alerts: reconciliation_check failed")
            session.rollback()
            done = None
    return {"reconciliation_done": done}
