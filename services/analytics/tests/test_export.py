"""The PostgreSQL export (contract C6): what export_day() writes is what
the builders read. The database tests run in their own schema."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from services.analytics import export
from services.analytics.tests.conftest import DAY, FIXTURES
from services.reconciliation import storage
from shared import cases as case_tables
from shared import reconciliation as recon_tables
from shared.cases import Case, CaseEvent
from shared.reconciliation import ReconciliationDifference, ReconciliationRun

NOW = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)


@pytest.fixture
def session():
    from shared.tests.isolated_db import isolated_sessions

    try:
        with isolated_sessions("analytics_export_test") as Session:
            with Session() as db:
                case_tables.create_schema(db)
                recon_tables.create_schema(db)
                yield db
    except OperationalError:
        pytest.skip("The export tests need PostgreSQL")


def _case(created_at: datetime) -> Case:
    transaction_id = uuid4()
    return Case(
        id=uuid4(),
        transaction_id=transaction_id,
        account_id=uuid4(),
        decision="HOLD",
        decision_reason="Mule account.",
        rules_triggered=["mule"],
        rules_version="0",
        rule_versions={"mule": 1},
        risk_score=50,
        amount=Decimal("100.50"),
        currency="USD",
        amount_usd=Decimal("100.50"),
        usd_rate=Decimal("1"),
        rate_date=created_at.date(),
        transaction_date=created_at,
        transaction={"id": str(transaction_id)},
        status="OPEN",
        created_at=created_at,
        due_at=created_at + timedelta(hours=4),
    )


def _run(run_day: date) -> ReconciliationRun:
    return ReconciliationRun(
        id=uuid4(), run_day=run_day, status="DONE", started_at=NOW, finished_at=NOW
    )


def _difference(run: ReconciliationRun) -> ReconciliationDifference:
    return ReconciliationDifference(
        id=uuid4(),
        run_id=run.id,
        run_day=run.run_day,
        partner="qr_pagos",
        type="AMOUNT_MISMATCH",
        reference=str(uuid4()),
        currency="EUR",
        pagoseguro_amount=Decimal("35.50"),
        partner_amount=Decimal("35.72"),
        amount_difference=Decimal("0.22"),
        status="PENDING",
        detected_at=NOW,
    )


def _load(session):
    """A case and a run inside the window, one case and one run outside
    each end of it."""
    inside = _case(datetime(2026, 10, 5, 12, 0, tzinfo=UTC))
    too_old = _case(datetime(2026, 9, 5, 23, 59, tzinfo=UTC))
    too_new = _case(datetime(2026, 10, 6, 0, 0, tzinfo=UTC))
    session.add_all([inside, too_old, too_new])
    session.flush()
    session.add(CaseEvent(case_id=inside.id, type="CREATED", actor="system", at=NOW))
    session.add(CaseEvent(case_id=too_old.id, type="CREATED", actor="system", at=NOW))
    runs = [_run(DAY), _run(date(2026, 9, 5)), _run(date(2026, 10, 6))]
    session.add_all(runs)
    session.flush()
    session.add_all(_difference(run) for run in runs)
    session.commit()
    return inside


def _raw(root: Path, layer: str, name: str) -> list[dict]:
    return storage.read_jsonl(str(root / "raw" / layer / f"fecha={DAY}" / name))


def test_it_writes_the_window_and_nothing_else(session, tmp_path):
    inside = _load(session)

    result = export.export_day(session, DAY, str(tmp_path), NOW)

    assert result == {
        "day": "2026-10-05",
        "cases": 1,
        "case_events": 1,
        "differences": 1,
        "runs": 1,
    }
    assert _raw(tmp_path, "cases", "cases.jsonl")[0]["id"] == str(inside.id)


def test_the_lines_have_the_shape_of_the_fixtures(session, tmp_path):
    _load(session)

    export.export_day(session, DAY, str(tmp_path), NOW)

    for layer, name in (
        ("cases", "cases.jsonl"),
        ("cases", "case_events.jsonl"),
        ("reconciliation", "differences.jsonl"),
        ("reconciliation", "runs.jsonl"),
    ):
        assert set(_raw(tmp_path, layer, name)[0]) == set(
            _raw(FIXTURES, layer, name)[0]
        )

    case = _raw(tmp_path, "cases", "cases.jsonl")[0]
    assert case["amount_usd"] == "100.50"
    assert case["created_at"] == "2026-10-05T12:00:00+00:00"
    assert case["rate_date"] == "2026-10-05"
    difference = _raw(tmp_path, "reconciliation", "differences.jsonl")[0]
    assert difference["amount_difference"] == "0.22"


def test_running_it_again_replaces_the_files(session, tmp_path):
    _load(session)

    first = export.export_day(session, DAY, str(tmp_path), NOW)
    second = export.export_day(session, DAY, str(tmp_path), NOW)

    assert first == second
    assert len(_raw(tmp_path, "cases", "cases.jsonl")) == 1


def test_an_empty_window_writes_empty_files(session, tmp_path):
    result = export.export_day(session, DAY, str(tmp_path), NOW)

    assert result["cases"] == result["differences"] == 0
    assert _raw(tmp_path, "cases", "cases.jsonl") == []


def test_the_handler_defaults_to_yesterday_in_bogota(monkeypatch):
    seen = {}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake(session, day, root, now):
        seen["day"] = day
        return {"day": day.isoformat()}

    monkeypatch.setattr(export, "SessionLocal", Session)
    monkeypatch.setattr(export, "export_day", fake)

    export.handler({"day": "2026-10-05"})
    assert seen["day"] == DAY

    export.handler(None)
    assert seen["day"] == datetime.now(export.BOGOTA).date() - timedelta(days=1)
