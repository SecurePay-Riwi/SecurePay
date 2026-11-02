"""RN-09: escalate the cases still open after 4 hours (HU-31).

A case is due ``CASE_DUE_MINUTES`` (240) after it was created. Every run
of the alerts task (5 minutes in AWS) moves the OPEN cases whose
``due_at`` has passed to ESCALATED, writes their ESCALATED event and
sends the supervisor ONE summary to the SNS topic ``BUSINESS_ALERTS_TOPIC``
with ``audience = "supervisor"`` (contract v2, 2026-11-01). So a case is
escalated at most 5 minutes late. Every pending case escalates, not only
the HOLD ones: the restricted list and splitting cases also wait for an
analyst (team decision D2).

Safe to run twice, like the compliance summary: the cases are locked
(``FOR UPDATE SKIP LOCKED``), at most ``BATCH_SIZE`` per run and the most
overdue first, and the summary is published BEFORE the commit. If SNS
fails, the caller rolls back and the same cases stay OPEN for the next
run; if the commit fails after the publish, the supervisor gets the
summary twice, never zero times. A RESOLVED or ESCALATED case never
moves again.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.alerts import notify
from shared.cases import (
    CASE_DUE_MINUTES,
    SYSTEM_ACTOR,
    Case,
    CaseEvent,
    CaseEventType,
    CaseStatus,
)

log = logging.getLogger(__name__)

AUDIENCE = "supervisor"
# Most cases per run. A normal run has a few; after an outage, the rest go
# in the next runs, the most overdue first.
BATCH_SIZE = 100


def limit_text(minutes: int = CASE_DUE_MINUTES) -> str:
    """The time limit as the e-mail says it: 240 -> "4 hours", and a demo
    with CASE_DUE_MINUTES=2 -> "2 minutes"."""
    if minutes % 60:
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    hours = minutes // 60
    return f"{hours} hour" + ("" if hours == 1 else "s")


def subject(count: int) -> str:
    noun = "case" if count == 1 else "cases"
    return f"{count} {noun} escalated (open over {limit_text()})"


def _utc(moment: datetime) -> datetime:
    """PostgreSQL returns timestamptz in the session's time zone (a local
    database may use America/Bogota); the e-mail and the event say UTC."""
    return moment.astimezone(UTC)


def _ago(due_at: datetime, now: datetime) -> str:
    minutes = max(int((now - due_at).total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min ago" if hours else f"{minutes} min ago"


def body(cases: list[Case], now: datetime) -> str:
    """Plain text: the totals first, then one line per case, the most
    overdue first (``cases`` comes in that order)."""
    unassigned = sum(1 for case in cases if not case.assignee)
    oldest = _utc(cases[0].due_at)
    lines = [
        f"Cases open for more than {limit_text()}: {len(cases)}. Escalated to the supervisor.",
        f"Unassigned: {unassigned}",
        f"Most overdue: due at {oldest:%Y-%m-%d %H:%M} UTC ({_ago(oldest, now)})",
        "",
        "Cases, most overdue first:",
    ]
    for case in cases:
        rules = ", ".join(case.rules_triggered) or "-"
        lines.append(
            f"- {case.id}  due {_utc(case.due_at):%Y-%m-%d %H:%M} UTC  "
            f"rules: {rules}  assignee: {case.assignee or '(none)'}"
        )
    lines += ["", "Details: GET /cases?status=ESCALATED on the cases API."]
    return "\n".join(lines)


def escalate_overdue(session: Session, now: datetime) -> int:
    """Up to 100 OPEN cases with due_at <= now (most overdue first, FOR UPDATE
    SKIP LOCKED) -> ESCALATED + event; ONE SNS summary (audience=supervisor)
    published BEFORE the commit (contract v2, 2026-11-01).
    Returns how many. Safe to run twice (only OPEN cases move)."""
    cases = session.scalars(
        select(Case)
        .where(Case.status == CaseStatus.OPEN.value, Case.due_at <= now)
        .order_by(Case.due_at, Case.id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()
    if not cases:
        session.rollback()  # release the (empty) transaction
        return 0

    for case in cases:
        case.status = CaseStatus.ESCALATED.value
        case.escalated_at = now
        session.add(CaseEvent(
            case_id=case.id,
            type=CaseEventType.ESCALATED.value,
            actor=SYSTEM_ACTOR,
            at=now,
            data={"due_at": _utc(case.due_at).isoformat()},
        ))
    session.flush()

    notify.publish(subject(len(cases)), body(cases, now), AUDIENCE)
    session.commit()
    log.info("Alerts: %d overdue case(s) escalated to the supervisor", len(cases))
    return len(cases)
