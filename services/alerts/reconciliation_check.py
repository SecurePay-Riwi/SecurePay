"""Was last night's reconciliation done in time? (HU-36, deadline 07:00)

In AWS a schedule invokes the alerts Lambda at 06:30 Bogota with
{"job": "reconciliation_check"}. If yesterday's run (the day Step Functions
reconciled at 02:00) is not DONE, it publishes one message to the ops
alarms topic: the run failed, is still running, or never started. The last
case is the one the Step Functions alarm cannot see.
"""

import logging
from datetime import date, datetime, timedelta

from services.alerts import notify
from shared.reconciliation import ReconciliationRun, RunStatus, create_schema

log = logging.getLogger(__name__)

# Bogota is UTC-5 all year (no daylight saving since 1993).
BOGOTA = timedelta(hours=-5)


def reconciled_day(now: datetime) -> date:
    """The day the 02:00 run of today reconciles: yesterday in Bogota."""
    return (now + BOGOTA).date() - timedelta(days=1)


def check(session, now: datetime) -> bool:
    """True when the run of reconciled_day(now) is DONE; otherwise warn the
    team and return False. Raises if SNS fails (the handler logs it)."""
    create_schema(session)  # idempotent: the tables may not exist yet in AWS
    day = reconciled_day(now)
    run = session.query(ReconciliationRun).filter_by(run_day=day).one_or_none()
    if run is not None and run.status == RunStatus.DONE.value:
        log.info("Reconciliation of %s is DONE", day)
        return True

    if run is None:
        state = "it never started (no run in reconciliation_runs)"
    elif run.status == RunStatus.FAILED.value:
        state = f"it FAILED: {run.error}"
    else:
        state = f"it is still {run.status} (started {run.started_at:%Y-%m-%d %H:%M} UTC)"
    body = (
        f"The reconciliation of {day} is not done and the deadline is 07:00 Bogota: {state}.\n"
        "Check the execution in Step Functions (securepay-<env>-reconciliation), fix the cause "
        f'and start it again with {{"day": "{day}"}}.'
    )
    notify.publish_ops(f"Reconciliation of {day} not done", body)
    log.warning("Reconciliation of %s not done: %s", day, state)
    return False
