"""GET /reconciliation/runs (HU-37) against a schema of its own."""

from datetime import UTC, date, datetime, timedelta

from services.cases_api import deps
from shared.reconciliation import ReconciliationRun, RunStatus
from shared.tests.isolated_db import down_sessions

URL = "/reconciliation/runs"
T0 = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


def _run(factory, day: date, status=RunStatus.DONE, error=None):
    with factory() as session:
        session.add(ReconciliationRun(
            run_day=day, status=status.value, started_at=T0,
            finished_at=None if status is RunStatus.RUNNING else T0 + timedelta(minutes=5),
            files_read=4, records_read=11, rows_rejected=2, matched=8, differences=6, error=error,
        ))
        session.commit()


def test_oldest_day_first_with_its_counts(client, sessions):
    _run(sessions, date(2026, 10, 6), RunStatus.FAILED, "match: RuntimeError: boom")
    _run(sessions, date(2026, 10, 5))

    body = client.get(URL).json()

    assert body["total"] == 2
    assert [r["run_day"] for r in body["items"]] == ["2026-10-05", "2026-10-06"]
    first, failed = body["items"]
    assert first == {
        "run_day": "2026-10-05", "status": "DONE",
        "started_at": "2026-10-06T07:00:00Z", "finished_at": "2026-10-06T07:05:00Z",
        "files_read": 4, "records_read": 11, "rows_rejected": 2, "matched": 8,
        "differences": 6, "error": None,
    }
    assert failed["status"] == "FAILED" and failed["error"] == "match: RuntimeError: boom"


def test_from_and_to_are_inclusive_days(client, sessions):
    for day in (4, 5, 6, 7):
        _run(sessions, date(2026, 10, day))

    body = client.get(URL, params={"from": "2026-10-05", "to": "2026-10-06"}).json()

    assert [r["run_day"] for r in body["items"]] == ["2026-10-05", "2026-10-06"]


def test_a_period_without_runs_is_empty(client):
    assert client.get(URL, params={"from": "2026-01-01", "to": "2026-01-31"}).json() == {
        "items": [], "total": 0}


def test_from_after_to_is_400(client):
    response = client.get(URL, params={"from": "2026-10-06", "to": "2026-10-05"})
    assert response.status_code == 400


def test_an_invalid_day_is_400(client):
    assert client.get(URL, params={"from": "yesterday"}).status_code == 400


def test_database_down_is_503(client):
    deps.bind(down_sessions())
    assert client.get(URL).status_code == 503
