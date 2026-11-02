"""RN-09: the 4-hour escalation (HU-31) against a schema of its own.

Needs PostgreSQL (DATABASE_URL); SNS is replaced by a fake client, except
in the last test, which uses LocalStack when it is up.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from services.alerts import escalation, notify
from shared.cases import (
    CASE_DUE_MINUTES,
    Case,
    CaseEvent,
    CaseEventType,
    CaseStatus,
    create_schema,
)
from shared.tests.isolated_db import isolated_sessions

NOW = datetime(2026, 11, 1, 14, 5, tzinfo=UTC)
DUE = timedelta(minutes=CASE_DUE_MINUTES)


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
    with isolated_sessions("escalation_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


@pytest.fixture
def sns(monkeypatch):
    fake = FakeSNS()
    monkeypatch.setattr(notify, "_client", lambda: fake)
    monkeypatch.setattr(notify, "_topic_arn", None)
    return fake


def _case(factory, created_ago, status=CaseStatus.OPEN, assignee=None, rules=("mule",)):
    """A case created ``created_ago`` before NOW, due CASE_DUE_MINUTES later."""
    created_at = NOW - created_ago
    with factory() as session:
        case = Case(
            transaction_id=uuid4(), account_id=uuid4(), decision="HOLD",
            decision_reason="Mule account pattern.", rules_triggered=list(rules),
            rules_version="3", amount=Decimal("120.00"), currency="USD",
            transaction_date=created_at, transaction={}, status=status.value,
            assignee=assignee, created_at=created_at, due_at=created_at + DUE,
        )
        if status == CaseStatus.RESOLVED:
            case.resolved_at = created_at + timedelta(hours=1)
            case.outcome, case.final_decision = "LEGITIMATE", "APPROVE"
        session.add(case)
        session.commit()
        return case.id


def _state(factory, case_id):
    """What GET /cases/{id} shows: the case and its events in order."""
    with factory() as session:
        case = session.get(Case, case_id)
        events = session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
        ).all()
        return case.status, case.escalated_at, [(e.type, e.actor, e.at, e.data) for e in events]


def _escalations(factory):
    with factory() as session:
        return session.scalars(
            select(CaseEvent).where(CaseEvent.type == CaseEventType.ESCALATED.value)
        ).all()


def test_an_overdue_case_is_escalated_with_one_summary(sessions, sns):
    """Criterion 1: still open 4 hours after its creation -> escalated."""
    case_id = _case(sessions, DUE + timedelta(minutes=3))

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 1

    [message] = sns.published
    assert message["TopicArn"] == "arn:aws:sns:us-east-2:000000000000:business-alerts"
    assert message["Subject"] == "1 case escalated (open over 4 hours)"
    assert message["MessageAttributes"] == {
        "audience": {"DataType": "String", "StringValue": "supervisor"}
    }
    assert str(case_id) in message["Message"]
    assert "rules: mule" in message["Message"]


def test_the_escalation_shows_with_its_time(sessions, sns):
    """Criterion 3: status ESCALATED, escalated_at and an ESCALATED event
    by the system with the due_at it missed."""
    case_id = _case(sessions, DUE + timedelta(minutes=3))
    due_at = NOW - timedelta(minutes=3)

    with sessions() as session:
        escalation.escalate_overdue(session, NOW)

    status, escalated_at, events = _state(sessions, case_id)
    assert status == CaseStatus.ESCALATED.value
    assert escalated_at == NOW
    assert events == [("ESCALATED", "system", NOW, {"due_at": due_at.isoformat()})]


def test_a_case_not_due_yet_is_left_open(sessions, sns):
    case_id = _case(sessions, DUE - timedelta(minutes=1))

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 0

    assert sns.published == []
    assert _state(sessions, case_id) == (CaseStatus.OPEN.value, None, [])


def test_a_case_resolved_before_4_hours_is_not_escalated(sessions, sns):
    """Criterion 2: resolved in time -> no escalation, not even later."""
    case_id = _case(sessions, DUE + timedelta(hours=2), status=CaseStatus.RESOLVED)

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 0

    assert sns.published == []
    assert _state(sessions, case_id) == (CaseStatus.RESOLVED.value, None, [])


def test_twice_gives_one_event_and_one_summary(sessions, sns):
    _case(sessions, DUE + timedelta(minutes=3))

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 1
        assert escalation.escalate_overdue(session, NOW + timedelta(minutes=5)) == 0

    assert len(sns.published) == 1
    assert len(_escalations(sessions)) == 1


def test_an_escalated_case_is_not_escalated_again(sessions, sns):
    case_id = _case(sessions, DUE + timedelta(hours=1), status=CaseStatus.ESCALATED)

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 0

    assert sns.published == []
    assert _state(sessions, case_id) == (CaseStatus.ESCALATED.value, None, [])


def test_sns_down_escalates_nothing_until_the_next_run(sessions, monkeypatch):
    case_id = _case(sessions, DUE + timedelta(minutes=3))
    monkeypatch.setattr(notify, "_topic_arn", None)
    monkeypatch.setattr(notify, "_client", lambda: FakeSNS(fail=True))

    with sessions() as session:
        with pytest.raises(RuntimeError):
            escalation.escalate_overdue(session, NOW)
        session.rollback()  # what handler() does

    assert _state(sessions, case_id) == (CaseStatus.OPEN.value, None, [])

    working = FakeSNS()
    monkeypatch.setattr(notify, "_client", lambda: working)
    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW + timedelta(minutes=5)) == 1
    assert len(working.published) == 1
    assert _state(sessions, case_id)[0] == CaseStatus.ESCALATED.value


def test_at_most_100_per_run_the_most_overdue_first(sessions, sns):
    ids = [_case(sessions, DUE + timedelta(minutes=minutes)) for minutes in range(1, 106)]
    most_overdue = set(ids[5:])  # created 6 to 105 minutes past due

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 100
    with sessions() as session:
        escalated = {e.case_id for e in session.scalars(select(CaseEvent))}
    assert escalated == most_overdue
    assert sns.published[0]["Subject"] == "100 cases escalated (open over 4 hours)"

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW + timedelta(minutes=5)) == 5
    assert len(_escalations(sessions)) == 105
    assert len(sns.published) == 2


def test_every_pending_rule_escalates_and_the_summary_has_the_totals(sessions, sns):
    """D2: not only HOLD cases. The summary: totals first, then one line
    per case, the most overdue first."""
    oldest = _case(sessions, DUE + timedelta(hours=3, minutes=10),
                   rules=("restricted_list",), assignee="ana")
    newest = _case(sessions, DUE + timedelta(minutes=2), rules=("mule", "splitting"))

    with sessions() as session:
        assert escalation.escalate_overdue(session, NOW) == 2

    body = sns.published[0]["Message"]
    assert "Cases open for more than 4 hours: 2." in body
    assert "Unassigned: 1" in body
    assert "Most overdue: due at 2026-11-01 10:55 UTC (3 h 10 min ago)" in body
    assert body.index(str(oldest)) < body.index(str(newest))
    assert "rules: restricted_list  assignee: ana" in body
    assert "rules: mule, splitting  assignee: (none)" in body
    assert "GET /cases?status=ESCALATED" in body


def test_against_localstack_only_the_supervisor_gets_it(sessions, monkeypatch):
    """The real topic: a queue subscribed with the supervisor filter gets
    the summary, one subscribed for compliance does not. Skipped without
    LocalStack (docker compose up -d)."""
    from botocore.exceptions import BotoCoreError, ClientError

    from shared.aws import cliente

    try:
        sns, sqs = cliente("sns"), cliente("sqs")
        arn = sns.create_topic(Name=notify.TOPIC)["TopicArn"]
    except (BotoCoreError, ClientError):
        pytest.skip("LocalStack is not available (docker compose up -d)")
    monkeypatch.setattr(notify, "_topic_arn", None)

    def subscribe(audience):
        name = f"escalation-test-{audience}-{uuid4().hex[:8]}"
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

    supervisor, compliance = subscribe("supervisor"), subscribe("compliance")
    try:
        case_id = _case(sessions, DUE + timedelta(minutes=3))
        with sessions() as session:
            assert escalation.escalate_overdue(session, NOW) == 1

        received = sqs.receive_message(QueueUrl=supervisor[0], WaitTimeSeconds=5)
        [message] = received["Messages"]
        assert str(case_id) in message["Body"]
        assert sqs.receive_message(QueueUrl=compliance[0], WaitTimeSeconds=1).get("Messages") is None
    finally:
        for url, subscription in (supervisor, compliance):
            sns.unsubscribe(SubscriptionArn=subscription)
            sqs.delete_queue(QueueUrl=url)


@pytest.mark.parametrize(
    ("minutes", "text"),
    [(240, "4 hours"), (60, "1 hour"), (2, "2 minutes"), (1, "1 minute"), (90, "90 minutes")],
)
def test_the_e_mail_says_the_configured_limit(minutes, text):
    """CASE_DUE_MINUTES=2 in a demo says "2 minutes", not "4 hours"."""
    assert escalation.limit_text(minutes) == text
