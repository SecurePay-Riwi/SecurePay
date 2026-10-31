"""The alerts handler runs its three jobs in order, each in its own try.

No database needed: the jobs and the session are replaced.
"""

from datetime import datetime

import pytest

from services.alerts import account_history, compliance_summary, escalation, handler


class FakeSession:
    def __init__(self):
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def session(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(handler, "SessionLocal", lambda: fake)
    return fake


@pytest.fixture
def calls(monkeypatch):
    calls = []

    def job(name, result):
        def run(session, now):
            assert isinstance(now, datetime) and now.tzinfo is not None
            calls.append((name, now))
            if isinstance(result, Exception):
                raise result
            return result
        return run

    def install(escalated=0, notified=0, purged=0):
        monkeypatch.setattr(escalation, "escalate_overdue", job("escalate", escalated))
        monkeypatch.setattr(compliance_summary, "send_summary", job("summary", notified))
        monkeypatch.setattr(account_history, "purge", job("purge", purged))
        return calls

    return install


def test_runs_the_three_jobs_in_order(session, calls):
    made = calls(escalated=2, notified=1, purged=7)

    result = handler.handler({}, None)

    assert [name for name, _ in made] == ["escalate", "summary", "purge"]
    # One clock for the three.
    assert len({now for _, now in made}) == 1
    assert result == {"escalated": 2, "notified": 1, "purged": 7}


def test_a_failing_job_does_not_stop_the_others(session, calls):
    made = calls(escalated=RuntimeError("SNS down"), notified=3, purged=4)

    result = handler.handler()

    assert [name for name, _ in made] == ["escalate", "summary", "purge"]
    assert result == {"escalated": None, "notified": 3, "purged": 4}
    assert session.rollbacks == 1


def test_the_skeleton_jobs_do_nothing(session):
    assert handler.handler() == {"escalated": 0, "notified": 0, "purged": 0}
