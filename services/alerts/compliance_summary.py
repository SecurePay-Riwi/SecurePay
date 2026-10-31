"""RN-06: the summary e-mail of restricted list reports for compliance (HU-34).

The cases consumer writes a ``compliance_reports`` row the moment a
restricted list decision arrives. Every run of the alerts task (5
minutes in AWS) sends the ones not notified yet in ONE message to the
SNS topic ``BUSINESS_ALERTS_TOPIC``, with the message attribute
``audience = "compliance"`` so the compliance e-mail subscription can
filter it (team decision of 2026-10-14, SNS filters per recipient).
With no new reports, nothing is published.

Safe to run twice: the reports are locked (``FOR UPDATE SKIP LOCKED``),
marked with ``notified_at`` and committed after the publish. If SNS
fails, the caller rolls back and the same reports go in the next run; if
the commit fails after the publish, compliance gets them twice, never
zero times.
"""

import logging
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.aws import cliente
from shared.cases import ComplianceReport

log = logging.getLogger(__name__)

# A topic name (LocalStack: created by infra/localstack/init/01_messaging.py)
# or its ARN (AWS: securepay-<env>-business-alerts).
TOPIC = os.getenv("BUSINESS_ALERTS_TOPIC", "business-alerts")
AUDIENCE = "compliance"

_topic_arn: str | None = None


def _client():
    return cliente("sns")


def topic_arn(sns) -> str:
    """The ARN as given, or the ARN of the topic with that name
    (create_topic is idempotent: it returns the existing topic)."""
    global _topic_arn
    if TOPIC.startswith("arn:"):
        return TOPIC
    if _topic_arn is None:
        _topic_arn = sns.create_topic(Name=TOPIC)["TopicArn"]
    return _topic_arn


def subject(count: int) -> str:
    noun = "report" if count == 1 else "reports"
    return f"RN-06: {count} restricted list {noun}"


def body(reports: list[ComplianceReport]) -> str:
    """Plain text: one block per listed document, oldest first."""
    lines = [
        (
            f"Account owners on a restricted list (RN-06): {len(reports)}. "
            "Each transaction has a case for an analyst."
        ),
        "",
    ]
    for report in reports:
        lines += [
            f"- Document {report.document} ({report.list_type})",
            f"  Matched at:  {report.matched_at.isoformat()}",
            f"  Transaction: {report.transaction_id}",
            f"  Account:     {report.account_id}",
            f"  Case:        {report.case_id}",
        ]
    lines += ["", "Details: GET /compliance/restricted-list-reports on the cases API."]
    return "\n".join(lines)


def send_summary(session: Session, now: datetime) -> int:
    """One e-mail (SNS business-alerts) with the compliance_reports where
    notified_at is null; sets notified_at. Returns how many reports."""
    reports = session.scalars(
        select(ComplianceReport)
        .where(ComplianceReport.notified_at.is_(None))
        .order_by(ComplianceReport.matched_at, ComplianceReport.document)
        .with_for_update(skip_locked=True)
    ).all()
    if not reports:
        session.rollback()  # release the (empty) transaction
        return 0

    for report in reports:
        report.notified_at = now
    session.flush()

    sns = _client()
    sns.publish(
        TopicArn=topic_arn(sns),
        Subject=subject(len(reports)),
        Message=body(reports),
        MessageAttributes={
            "audience": {"DataType": "String", "StringValue": AUDIENCE},
        },
    )
    session.commit()
    log.info("Alerts: %d restricted list report(s) sent to compliance", len(reports))
    return len(reports)
