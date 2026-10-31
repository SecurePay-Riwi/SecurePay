"""D3: the account history keeps ACCOUNT_HISTORY_DAYS (HU-28).

The history consumer writes ``account_transactions``; every run of the
alerts task (5 minutes in AWS) deletes the rows whose
``transaction_date`` is older than ``now - ACCOUNT_HISTORY_DAYS``, the
same window the cases API reads.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from shared.cases import ACCOUNT_HISTORY_DAYS, AccountTransaction

log = logging.getLogger(__name__)


def cutoff(now: datetime) -> datetime:
    """The oldest transaction_date the history keeps."""
    return now - timedelta(days=ACCOUNT_HISTORY_DAYS)


def purge(session: Session, now: datetime) -> int:
    """Delete account_transactions older than ACCOUNT_HISTORY_DAYS.
    Returns how many rows."""
    deleted = session.execute(
        delete(AccountTransaction).where(AccountTransaction.transaction_date < cutoff(now))
    ).rowcount
    session.commit()
    if deleted:
        log.info("Alerts: %d account history row(s) older than %d days deleted",
                 deleted, ACCOUNT_HISTORY_DAYS)
    return deleted
