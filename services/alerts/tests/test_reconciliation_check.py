"""The 06:30 check of the nightly reconciliation (HU-36) against a schema
of its own. Needs PostgreSQL (DATABASE_URL); SNS is replaced."""

from datetime import UTC, date, datetime

import pytest

from services.alerts import notify, reconciliation_check
from shared.reconciliation import ReconciliationRun, RunStatus, create_schema
from shared.tests.isolated_db import isolated_sessions

# 11:30 UTC = 06:30 Bogota on 2026-10-06: the 02:00 run reconciled the 5th.
NOW = datetime(2026, 10, 6, 11, 30, tzinfo=UTC)
DAY = date(2026, 10, 5)


class FakeSNS:
    def __init__(self):
        self.published = []

    def create_topic(self, Name):
        return {"TopicArn": f"arn:aws:sns:us-east-2:000000000000:{Name}"}

    def publish(self, **kwargs):
        self.published.append(kwargs)


@pytest.fixture
def session():
    with isolated_sessions("reconciliation_check_test") as factory:
        with factory() as s:
            create_schema(s)
            yield s


@pytest.fixture
def sns(monkeypatch):
    fake = FakeSNS()
    monkeypatch.setattr(notify, "_client", lambda: fake)
    return fake


def _run(session, status, error=None):
    session.add(
        ReconciliationRun(
            run_day=DAY,
            status=status.value,
            error=error,
            started_at=datetime(2026, 10, 6, 7, 0, tzinfo=UTC),
        )
    )
    session.commit()


def test_the_checked_day_is_yesterday_in_bogota():
    assert reconciliation_check.reconciled_day(NOW) == DAY
    # 03:00 UTC of the 6th is still the 5th in Bogota: yesterday is the 4th.
    assert reconciliation_check.reconciled_day(
        datetime(2026, 10, 6, 3, 0, tzinfo=UTC)
    ) == date(2026, 10, 4)


def test_a_done_run_sends_nothing(session, sns):
    _run(session, RunStatus.DONE)
    assert reconciliation_check.check(session, NOW) is True
    assert sns.published == []


def test_a_run_that_never_started_warns_the_team(session, sns):
    assert reconciliation_check.check(session, NOW) is False
    [message] = sns.published
    assert message["TopicArn"].endswith(":ops-alarms")
    assert message["Subject"] == "Reconciliation of 2026-10-05 not done"
    assert "never started" in message["Message"]
    assert '{"day": "2026-10-05"}' in message["Message"]
    assert "MessageAttributes" not in message


def test_a_failed_run_says_why(session, sns):
    _run(session, RunStatus.FAILED, error="match: RuntimeError: boom")
    assert reconciliation_check.check(session, NOW) is False
    assert "FAILED: match: RuntimeError: boom" in sns.published[0]["Message"]


def test_a_run_still_going_is_not_done(session, sns):
    _run(session, RunStatus.RUNNING)
    assert reconciliation_check.check(session, NOW) is False
    assert "still RUNNING" in sns.published[0]["Message"]


def test_an_ops_topic_arn_is_used_as_is(session, sns, monkeypatch):
    arn = "arn:aws:sns:us-east-2:123456789012:securepay-dev-ops-alarms"
    monkeypatch.setattr(notify, "OPS_TOPIC", arn)
    reconciliation_check.check(session, NOW)
    assert sns.published[0]["TopicArn"] == arn
