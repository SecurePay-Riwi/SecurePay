"""POST /rules/simulations (HU-24): one day of the fixture lake replayed
with a candidate and with the current catalog. It compares them and
never writes: no rule, no catalog version, nothing in Valkey.

Needs PostgreSQL and Valkey, like the other tests of the rules API; the
lake and the reference data are the analytics fixtures."""

import pytest
from sqlalchemy import text

from services.analytics.replay import ReferenceData
from services.analytics.tests.conftest import FIXTURES
from services.decision_engine import currency
from services.rules_api import simulation
from shared.cache import get_cache
from shared.rule_catalog import CATALOG_KEY, DEFAULT_RULES, VERSION_KEY

DAY = "2026-10-05"


def _rules(**changes) -> list[dict]:
    rules = []
    for r in DEFAULT_RULES:
        rule = r.model_dump(mode="json")
        rules.append({**rule, **changes.get(r.code, {})})
    return rules


@pytest.fixture(autouse=True)
def lake(monkeypatch):
    currency.load({})
    monkeypatch.setattr(simulation, "raw_root", lambda: str(FIXTURES))
    monkeypatch.setattr(
        simulation, "reference", lambda: ReferenceData.from_fixtures(FIXTURES)
    )
    yield
    currency.load({})


def _state(engine) -> tuple:
    with engine.connect() as conn:
        versions = conn.scalar(text("SELECT count(*) FROM rule_catalog_versions"))
        rules = conn.execute(
            text("SELECT code, action, rule_version FROM rules ORDER BY code")
        ).all()
    cache = get_cache()
    return versions, rules, cache.get(VERSION_KEY), cache.get(CATALOG_KEY)


def test_splitting_back_to_approve_lets_the_splits_go(client):
    body = {"day": DAY, "candidate": _rules(splitting={"action": "APPROVE"})}

    response = client.post("/rules/simulations", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["day"] == DAY
    assert result["transactions"] == 34
    assert result["current"]["rules_version"] == "1"  # the API's seed version
    assert result["candidate"]["rules_version"] == "candidate"
    assert result["changed"] == 2
    assert result["changes"] == {"HOLD->APPROVE": 2}
    assert result["released_usd"] == "7324.67"
    assert result["stopped_usd"] == "0.00"
    assert result["current"]["cases"] == result["candidate"]["cases"]
    assert [e["candidate"]["decision"] for e in result["examples"]] == [
        "APPROVE",
        "APPROVE",
    ]
    assert {m["rule"] for m in result["current"]["metrics"]} >= {"splitting"}


def test_a_simulation_never_writes(client, isolated):
    before = _state(isolated)

    client.post(
        "/rules/simulations",
        json={"day": DAY, "candidate": _rules(velocity={"action": "REJECT"})},
    )

    assert _state(isolated) == before


def test_the_same_catalog_changes_nothing(client):
    current = client.get("/rules").json()

    result = client.post(
        "/rules/simulations", json={"day": DAY, "candidate": current}
    ).json()

    assert result["changed"] == 0
    assert result["current"]["decisions"] == result["candidate"]["decisions"]


def test_against_an_old_version(client):
    response = client.post(
        "/rules/simulations",
        json={"day": DAY, "candidate": _rules(), "against_version": 1},
    )

    assert response.status_code == 200
    assert response.json()["current"]["rules_version"] == "1"


def test_a_version_that_does_not_exist_is_404(client):
    response = client.post(
        "/rules/simulations",
        json={"day": DAY, "candidate": _rules(), "against_version": 999},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Catalog version 999 does not exist."}


@pytest.mark.parametrize(
    "dates",
    [
        {"from": "2026-10-04", "to": "2026-10-05"},
        {"day": DAY, "to": "2026-10-06"},
        {},
    ],
)
def test_one_day_at_a_time(client, dates):
    response = client.post("/rules/simulations", json={**dates, "candidate": _rules()})

    assert response.status_code == 422
    assert "one day" in response.json()["detail"]


def test_an_invalid_candidate_is_400(client):
    rules = _rules(velocity={"params": {"window_minutes": 0, "limit": 5}})

    response = client.post("/rules/simulations", json={"day": DAY, "candidate": rules})

    assert response.status_code == 400
