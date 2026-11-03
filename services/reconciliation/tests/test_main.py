"""Local orchestration (python -m services.reconciliation).

Needs PostgreSQL (DATABASE_URL); runs in a schema of its own.
"""

import pytest

from services.reconciliation import __main__ as orchestration
from services.reconciliation import match
from services.reconciliation.tests.conftest import DAY, DECISIONS, STATEMENTS
from shared.reconciliation import ReconciliationRun, RunStatus, create_schema
from shared.tests.isolated_db import isolated_sessions


@pytest.fixture
def session():
    with isolated_sessions("reconciliation_main_test") as factory, factory() as s:
        create_schema(s)
        yield s


def _run(session) -> ReconciliationRun:
    return session.query(ReconciliationRun).filter_by(run_day=DAY).one()


def test_runs_the_three_steps(session, tmp_path):
    result = orchestration.run_day(session, DAY, STATEMENTS, DECISIONS, str(tmp_path))
    assert result["day"] == "2026-10-05"
    assert (
        tmp_path / "curated" / "extractos" / "fecha=2026-10-05" / "records.jsonl"
    ).exists()
    assert list(
        (tmp_path / "curated" / "conciliacion" / "fecha=2026-10-05").glob("part-*.json")
    )
    assert _run(session).error is None


def test_a_failed_step_marks_the_run_failed(session, tmp_path, monkeypatch):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(match, "reconcile", broken)
    with pytest.raises(RuntimeError):
        orchestration.run_day(session, DAY, STATEMENTS, DECISIONS, str(tmp_path))
    run = _run(session)
    assert run.status == RunStatus.FAILED.value
    assert run.error == "match: RuntimeError: boom"
    assert run.finished_at is not None


def test_running_a_day_again_reuses_its_run(session, tmp_path):
    orchestration.start_run(session, DAY, orchestration.datetime.now(orchestration.UTC))
    orchestration.fail_run(
        session,
        DAY,
        "ingest",
        ValueError("x"),
        orchestration.datetime.now(orchestration.UTC),
    )
    orchestration.run_day(session, DAY, STATEMENTS, DECISIONS, str(tmp_path))
    assert session.query(ReconciliationRun).count() == 1
    assert _run(session).error is None


def test_days_from_to():
    args = orchestration.argparse.Namespace(day=None, from_=DAY, to=DAY.replace(day=7))
    assert [d.day for d in orchestration.days(args)] == [5, 6, 7]
