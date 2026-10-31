"""RN-06: the summary e-mail of restricted list reports for compliance (HU-34)."""

from datetime import datetime

from sqlalchemy.orm import Session


def send_summary(session: Session, now: datetime) -> int:
    """One e-mail (SNS business-alerts) with the compliance_reports where
    notified_at is null; sets notified_at. Returns how many reports.

    HU-34 fills it in; the signature stays.
    """
    return 0
