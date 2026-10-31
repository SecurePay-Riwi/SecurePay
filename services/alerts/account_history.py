"""D3: the account history keeps ACCOUNT_HISTORY_DAYS (HU-28)."""

from datetime import datetime

from sqlalchemy.orm import Session


def purge(session: Session, now: datetime) -> int:
    """Delete account_transactions older than ACCOUNT_HISTORY_DAYS.
    Returns how many rows.

    HU-28 fills it in; the signature stays.
    """
    return 0
