"""The compliance summary e-mail (HU-34, RN-06) against a schema of its own.

Needs PostgreSQL (DATABASE_URL); SNS is replaced by a fake client.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from services.alerts import compliance_summary
from shared.cases import Case, ComplianceReport, create_schema
from shared.tests.isolated_db import isolated_sessions

NOW = datetime(2026, 10, 31, 14, 5, tzinfo=UTC)


class FakeSNS:
    def __init__(self, fail=False):
        self.published = []
        self.fail = fail

    def create_topic(self, Name):
        return {"TopicArn": f"arn:aws:sns:us-east-2:000000000000:{Name}"}

    def publish(self, **kwargs):
        if self.fail:
            raise RuntimeError("SNS down")
        self.published.append(kwargs)


@pytest.fixture
def sessions():
    with isolated_sessions("compliance_summary_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


@pytest.fixture
def sns(monkeypatch):
    fake = FakeSNS()
    monkeypatch.setattr(compliance_summary, "_client", lambda: fake)
    monkeypatch.setattr(compliance_summary, "_topic_arn", None)
    return fake


def _report(factory, document="1000000070", list_type="PEP", notified_at=None):
    matched_at = NOW - timedelta(minutes=3)
    with factory() as session:
        case = Case(
            transaction_id=uuid4(), account_id=uuid4(), decision="REJECT",
            decision_reason="Account owner is on a restricted list.",
            rules_triggered=["restricted_list"], rules_version="3",
            amount=Decimal("10.00"), currency="USD", transaction_date=matched_at,
            transaction={}, created_at=matched_at, due_at=matched_at + timedelta(hours=4),
        )
        session.add(case)
        session.flush()
        report = ComplianceReport(
            case_id=case.id, transaction_id=case.transaction_id, account_id=case.account_id,
            document=document, list_type=list_type, matched_at=matched_at,
            notified_at=notified_at,
        )
        session.add(report)
        session.commit()
        return report.id


def _notified(factory):
    with factory() as session:
        return {
            r.document: r.notified_at
            for r in session.scalars(select(ComplianceReport))
        }


def test_one_message_for_the_new_reports(sessions, sns):
    _report(sessions, "1000000070", "PEP")
    _report(sessions, "1000000016", "sanciones")
    _report(sessions, "1000000040", notified_at=NOW - timedelta(minutes=10))

    with sessions() as session:
        assert compliance_summary.send_summary(session, NOW) == 2

    [message] = sns.published
    assert message["TopicArn"] == "arn:aws:sns:us-east-2:000000000000:business-alerts"
    assert message["Subject"] == "RN-06: 2 restricted list reports"
    assert message["MessageAttributes"] == {
        "audience": {"DataType": "String", "StringValue": "compliance"}
    }
    assert "1000000070 (PEP)" in message["Message"]
    assert "1000000016 (sanciones)" in message["Message"]
    assert "1000000040" not in message["Message"]
    notified = _notified(sessions)
    assert notified["1000000070"] == NOW and notified["1000000016"] == NOW
    assert notified["1000000040"] == NOW - timedelta(minutes=10)


def test_twice_sends_one_message(sessions, sns):
    _report(sessions)

    with sessions() as session:
        assert compliance_summary.send_summary(session, NOW) == 1
        assert compliance_summary.send_summary(session, NOW + timedelta(minutes=5)) == 0

    assert len(sns.published) == 1
    assert sns.published[0]["Subject"] == "RN-06: 1 restricted list report"


def test_without_reports_nothing_is_published(sessions, sns):
    with sessions() as session:
        assert compliance_summary.send_summary(session, NOW) == 0

    assert sns.published == []


def test_sns_down_leaves_the_reports_for_the_next_run(sessions, monkeypatch):
    _report(sessions)
    monkeypatch.setattr(compliance_summary, "_client", lambda: FakeSNS(fail=True))

    with sessions() as session:
        with pytest.raises(RuntimeError):
            compliance_summary.send_summary(session, NOW)
        session.rollback()  # what handler() does

    assert _notified(sessions) == {"1000000070": None}


def test_a_topic_arn_is_used_as_is(sessions, sns, monkeypatch):
    arn = "arn:aws:sns:us-east-2:123456789012:securepay-dev-business-alerts"
    monkeypatch.setattr(compliance_summary, "TOPIC", arn)
    _report(sessions)

    with sessions() as session:
        compliance_summary.send_summary(session, NOW)

    assert sns.published[0]["TopicArn"] == arn


def test_against_localstack_only_compliance_gets_it(sessions, monkeypatch):
    """The real topic: a queue subscribed with the compliance filter gets
    the summary, one subscribed with another audience does not. Skipped
    without LocalStack (docker compose up -d)."""
    from botocore.exceptions import BotoCoreError, ClientError

    from shared.aws import cliente

    try:
        sns, sqs = cliente("sns"), cliente("sqs")
        arn = sns.create_topic(Name=compliance_summary.TOPIC)["TopicArn"]
    except (BotoCoreError, ClientError):
        pytest.skip("LocalStack is not available (docker compose up -d)")
    monkeypatch.setattr(compliance_summary, "_topic_arn", None)

    def subscribe(audience):
        name = f"compliance-summary-test-{audience}-{uuid4().hex[:8]}"
        url = sqs.create_queue(QueueName=name)["QueueUrl"]
        queue_arn = sqs.get_queue_attributes(
            QueueUrl=url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        subscription = sns.subscribe(
            TopicArn=arn, Protocol="sqs", Endpoint=queue_arn,
            Attributes={"FilterPolicy": f'{{"audience": ["{audience}"]}}',
                        "RawMessageDelivery": "true"},
        )["SubscriptionArn"]
        return url, subscription

    compliance, treasury = subscribe("compliance"), subscribe("treasury")
    try:
        _report(sessions)
        with sessions() as session:
            assert compliance_summary.send_summary(session, NOW) == 1

        received = sqs.receive_message(QueueUrl=compliance[0], WaitTimeSeconds=5)
        [message] = received["Messages"]
        assert "1000000070 (PEP)" in message["Body"]
        assert sqs.receive_message(QueueUrl=treasury[0], WaitTimeSeconds=1).get("Messages") is None
    finally:
        for url, subscription in (compliance, treasury):
            sns.unsubscribe(SubscriptionArn=subscription)
            sqs.delete_queue(QueueUrl=url)
