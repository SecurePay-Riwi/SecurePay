"""The nightly reconciliation end to end (HU-36 to HU-40, RN-10).

The three steps chained the way `python -m services.reconciliation` and
Step Functions run them: ingest reads the four partners' files of the
fixture day, match crosses them with the decisions in Spark (local mode)
and store saves the differences and closes the run. Each step has its own
tests; this one checks that their outputs fit together and that the day
gives the answer key (fixtures/extracts_report.json).

Needs PostgreSQL (an empty schema of its own) and Java 17 or later for
Spark; it skips without Java, like the match tests.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from services.reconciliation import __main__ as orchestration
from services.reconciliation import match
from shared.reconciliation import (
    DifferenceStatus,
    ReconciliationDifference,
    ReconciliationRun,
    RunStatus,
    create_schema,
)
from shared.tests.isolated_db import isolated_sessions

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "reconciliation"
    / "tests"
    / "fixtures"
)
DAY = date(2026, 10, 5)
REPORT = json.loads((FIXTURES / "extracts_report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spark():
    if shutil.which("java") is None:
        pytest.skip(
            "Spark needs Java 17 or later: install it to run the reconciliation end to end"
        )
    return match.session()


@pytest.fixture
def session():
    with isolated_sessions("reconciliation_e2e_test") as factory:
        with factory() as s:
            create_schema(s)
            yield s


def _run(session, spark, target: Path) -> dict:
    return orchestration.run_day(
        session,
        DAY,
        str(FIXTURES / "extractos"),
        str(FIXTURES / "decisiones"),
        str(target),
        spark,
    )


def _differences(session) -> set[tuple]:
    return {
        (d.type, d.partner, d.reference)
        for d in session.query(ReconciliationDifference).filter_by(run_day=DAY)
    }


def _expected() -> set[tuple]:
    return {
        (d["type"], d["partner"], d["reference"])
        for d in REPORT["expected_differences"]
    }


def test_the_fixture_day_gives_the_answer_key(session, spark, tmp_path):
    expected = REPORT["expected_run"]

    result = _run(session, spark, tmp_path)

    assert result["matched"] == expected["matched"]
    assert result["differences"] == expected["differences"]

    run = session.query(ReconciliationRun).filter_by(run_day=DAY).one()
    assert run.status == RunStatus.DONE.value
    assert run.error is None
    assert run.finished_at is not None
    assert (run.files_read, run.records_read, run.rows_rejected) == (
        expected["files_read"],
        expected["records"],
        expected["rejected"],
    )
    assert (run.matched, run.differences) == (
        expected["matched"],
        expected["differences"],
    )

    assert _differences(session) == _expected()
    statuses = {d.status for d in session.query(ReconciliationDifference)}
    assert statuses == {DifferenceStatus.PENDING.value}


def test_each_step_leaves_its_files_for_the_next(session, spark, tmp_path):
    _run(session, spark, tmp_path)

    curated = tmp_path / "curated"
    records = (curated / "extractos" / "fecha=2026-10-05" / "records.jsonl").read_text(
        encoding="utf-8"
    )
    rejects = (curated / "extractos" / "fecha=2026-10-05" / "rejects.jsonl").read_text(
        encoding="utf-8"
    )
    parts = sorted((curated / "conciliacion" / "fecha=2026-10-05").glob("part-*.json"))

    assert len(records.splitlines()) == REPORT["expected_run"]["records"]
    assert len(rejects.splitlines()) == REPORT["expected_run"]["rejected"]
    assert len(parts) == 1
    assert (
        len(parts[0].read_text(encoding="utf-8").splitlines())
        == REPORT["expected_run"]["match_rows"]
    )


def test_running_the_day_again_neither_duplicates_nor_reopens(session, spark, tmp_path):
    _run(session, spark, tmp_path)
    first = session.query(ReconciliationDifference).filter_by(run_day=DAY).first()
    first.status = DifferenceStatus.RESOLVED.value
    session.commit()

    result = _run(session, spark, tmp_path)

    # The day still has its 6 differences, but no row is added (D4).
    assert result["differences"] == REPORT["expected_run"]["differences"]
    assert session.query(ReconciliationDifference).count() == len(
        REPORT["expected_differences"]
    )
    assert _differences(session) == _expected()
    session.refresh(first)
    assert first.status == DifferenceStatus.RESOLVED.value
    run = session.query(ReconciliationRun).filter_by(run_day=DAY).one()
    assert run.status == RunStatus.DONE.value


def test_a_failing_step_marks_the_run_failed(session, spark, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("cluster down")

    monkeypatch.setattr(match, "reconcile", broken)

    with pytest.raises(RuntimeError):
        _run(session, spark, tmp_path)

    run = session.query(ReconciliationRun).filter_by(run_day=DAY).one()
    assert run.status == RunStatus.FAILED.value
    assert run.error == "match: RuntimeError: cluster down"
    assert session.query(ReconciliationDifference).count() == 0
