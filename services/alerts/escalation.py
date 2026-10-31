"""RN-09: escalate the cases still open after 4 hours (HU-31)."""

from datetime import datetime

from sqlalchemy.orm import Session


def escalate_overdue(session: Session, now: datetime) -> int:
    """OPEN cases with due_at <= now -> ESCALATED + event + SNS to the
    supervisor. Returns how many. Safe to run twice (only OPEN cases move).

    HU-31 fills it in; the signature stays.
    """
    return 0
