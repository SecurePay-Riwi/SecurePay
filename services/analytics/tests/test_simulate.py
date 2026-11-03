"""The simulation of a rule version (HU-24) over the fixture day: the
candidate catalog, the day's history read from raw/decisiones, and the
demo case of decision D2 (splitting back to APPROVE). No Java or Valkey;
one test needs PostgreSQL."""

import json
from datetime import date

import pytest

from services.analytics import simulate
from services.analytics.replay import ReferenceData
from services.analytics.tests.conftest import DAY, FIXTURES
from services.decision_engine import currency
from services.decision_engine.schemas import SecurityEventRequest
from shared.rule_catalog import CatalogSnapshot, default_catalog


@pytest.fixture(autouse=True)
def fixed_rates():
    currency.load({})
    yield
    currency.load({})


def _rules(**changes) -> list[dict]:
    return [
        {**r.model_dump(mode="json"), **changes.get(r.code, {})}
        for r in default_catalog().rules
    ]


def _security():
    path = FIXTURES / "security_events.jsonl"
    return [
        SecurityEventRequest(**json.loads(x)) for x in path.read_text().splitlines()
    ]


def _run(candidate, security=()):
    transactions, day_ids = simulate.day_history(str(FIXTURES), DAY)
    current = default_catalog()
    return simulate.simulate(
        DAY,
        current,
        simulate.candidate_snapshot(candidate, current),
        transactions,
        day_ids,
        ReferenceData.from_fixtures(FIXTURES),
        simulate.day_labels(str(FIXTURES)),
        security,
    )


def test_the_history_of_the_day_is_read_once_per_transaction(expected):
    transactions, day_ids = simulate.day_history(str(FIXTURES), DAY)

    assert len(day_ids) == sum(r["transactions"] for r in expected["q1"])
    assert len({str(t.id) for t in transactions}) == len(transactions)
    # The day before is replayed too (warm-up), but not compared.
    assert len(transactions) > len(day_ids)
    assert {t.transaction_date.date() for t in transactions} == {
        date(2026, 10, 4),
        DAY,
    }


def test_a_day_without_decisions_is_empty(tmp_path):
    assert simulate.day_history(str(tmp_path), DAY) == ([], set())


def test_the_candidate_can_be_a_list_of_rules_or_a_catalog():
    current = default_catalog()

    from_list = simulate.candidate_snapshot(_rules(), current)
    from_dict = simulate.candidate_snapshot(current.model_dump(mode="json"), current)

    assert isinstance(from_list, CatalogSnapshot)
    assert from_list.rules == current.rules
    assert from_list.author == "candidate"
    assert from_dict == current
    with pytest.raises(ValueError):
        simulate.candidate_snapshot(
            _rules(velocity={"params": {"window_minutes": 0}}), current
        )


def test_splitting_back_to_approve_releases_the_splits():
    """The demo of D2: the old version (APPROVE) against the current one
    (HOLD). Both splits of the day pass and their money keeps leaving."""
    result = _run(_rules(splitting={"action": "APPROVE"}), _security())

    assert result["day"] == DAY.isoformat()
    assert result["transactions"] == 34
    assert result["changed"] == 2
    assert result["changes"] == {"HOLD->APPROVE": 2}
    assert result["released_usd"] == "7324.67"
    assert result["stopped_usd"] == "0.00"
    assert (
        result["current"]["decisions"]["HOLD"] - 2
        == (result["candidate"]["decisions"]["HOLD"])
    )
    # Still a case each: the candidate keeps opens_case.
    assert result["current"]["cases"] == result["candidate"]["cases"]
    [first, second] = result["examples"]
    assert first["current"]["decision"] == "HOLD"
    assert first["candidate"]["decision"] == "APPROVE"
    assert first["current"]["rules_triggered"] == ["splitting"]
    assert float(first["amount_usd"]) >= float(second["amount_usd"])


def test_the_current_catalog_against_itself_changes_nothing():
    result = _run(_rules(), _security())

    assert result["changed"] == 0
    assert result["examples"] == []
    assert result["current"]["decisions"] == result["candidate"]["decisions"]
    assert result["current"]["metrics"] == [
        {**m, "rules_version": "0"} for m in result["candidate"]["metrics"]
    ]


def test_the_metrics_of_each_side_use_the_labels():
    result = _run(_rules(velocity={"enabled": False}), _security())

    current = {m["rule"]: m for m in result["current"]["metrics"]}
    candidate = {m["rule"]: m for m in result["candidate"]["metrics"]}
    assert current["velocity"]["true_positives"] == 1
    assert candidate["velocity"]["hits"] == 0
    assert result["changes"] == {"HOLD->APPROVE": 1}


def test_a_stricter_candidate_stops_money():
    result = _run(_rules(shared_device={"action": "HOLD"}), _security())

    assert result["changes"] == {"APPROVE->HOLD": 2}
    assert result["released_usd"] == "0.00"
    assert result["stopped_usd"] != "0.00"


def test_a_version_that_does_not_exist():
    from sqlalchemy.exc import OperationalError

    from shared.db import SessionLocal

    try:
        with SessionLocal() as session:
            latest = simulate.catalog_version(session, None)
            with pytest.raises(simulate.VersionNotFound):
                simulate.catalog_version(session, 999_999)
    except OperationalError:
        pytest.skip("PostgreSQL is not available")

    assert latest.rules


def test_the_command_prints_the_comparison(tmp_path, capsys):
    from sqlalchemy.exc import OperationalError

    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_rules(splitting={"action": "APPROVE"})))
    try:
        simulate.main(
            [
                "--day",
                DAY.isoformat(),
                "--candidate",
                str(candidate),
                "--raw",
                str(FIXTURES),
                "--reference",
                str(FIXTURES),
                "--security",
                str(FIXTURES / "security_events.jsonl"),
            ]
        )
    except OperationalError:
        pytest.skip("PostgreSQL is not available")

    result = json.loads(capsys.readouterr().out)
    assert (result["changed"], result["released_usd"]) == (2, "7324.67")
