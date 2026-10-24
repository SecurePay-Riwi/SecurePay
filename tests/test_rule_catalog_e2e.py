"""HU-23 and CA-06 end to end: the rules API and the engine together.

A rule changed through the rules API reaches the next decision without
restarting the engine, and every decision records the catalog version
and the version of each rule that fired (RN-08). With those two numbers
GET /rules/versions/{n} shows the exact thresholds that decided.

Both services run in this process against the same PostgreSQL and
Valkey, the way Compose wires them. They only meet through Valkey:
this test is the one place that uses both. The rules API gets an empty
schema of its own; the engine reads the seeded tables.

Needs PostgreSQL with the seed (securepay-seed) and Valkey.
"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.decision_engine import catalog, publisher, rules
from services.decision_engine.tests.test_api import (
    _cuenta_del_seed,
    _minutos,
    _payload_qr,
    _payloads_p2p,
)
from services.decision_engine.tests.test_api import client as engine
from services.rules_api import store
from services.rules_api.main import app as rules_app
from shared.cache import get_cache
from shared.db import engine as dev_engine
from shared.rule_catalog import CATALOG_KEY, VERSION_KEY

SCHEMA = "rules_e2e_test"


@pytest.fixture
def events(monkeypatch):
    """What the engine would publish to SNS."""
    published = []
    monkeypatch.setattr(publisher, "publicar", published.append)
    return published


@pytest.fixture
def rules_api():
    """The rules API on an empty schema: at startup it stores version 1
    and publishes it in Valkey. The engine starts from the code defaults
    and has to pick it up on its own."""
    with dev_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    db = create_engine(dev_engine.url, connect_args={"options": f"-csearch_path={SCHEMA}"})
    previous = store.SessionLocal
    store.bind(sessionmaker(bind=db))
    get_cache().delete(CATALOG_KEY, VERSION_KEY)
    catalog.reset()
    try:
        with TestClient(rules_app) as client:
            yield client
    finally:
        store.bind(previous)
        db.dispose()
        get_cache().delete(CATALOG_KEY, VERSION_KEY)
        catalog.reset()
        with dev_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


def _wait_for_refresh():
    """The engine checks {rules}:version at most every RULES_REFRESH_SECONDS."""
    time.sleep(catalog.REFRESH_SECONDS + 0.1)


def _decide(payload: dict) -> dict:
    response = engine.post("/transactions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_rule_changed_through_the_api_decides_the_next_transaction(rules_api, events):
    payloads = _payloads_p2p(_minutos(0, 1, 2, 3))

    first = _decide(payloads[0])
    assert first["rules_version"] == "1"
    assert first["decision"] == "APPROVE"

    # CA-06: velocity holds from the third transfer instead of the sixth.
    change = rules_api.put(
        "/rules/velocity",
        json={"action": "HOLD", "params": {"window_minutes": 10, "limit": 2}},
        headers={"X-User": "habith"},
    )
    assert change.status_code == 200, change.text
    assert change.json()["catalog_version"] == 2
    assert change.json()["rule"]["rule_version"] == 2

    _wait_for_refresh()

    assert _decide(payloads[1])["decision"] == "APPROVE"
    third = _decide(payloads[2])
    assert third["decision"] == "HOLD"
    assert third["rules_triggered"] == ["velocity"]
    assert third["rules_version"] == "2"
    assert third["rule_versions"] == {"velocity": 2}

    # The event the cases and analytics consumers keep says the same.
    event = next(e for e in events if e["decision"]["transaction_id"] == payloads[2]["id"])
    assert event["decision"]["rules_version"] == "2"
    assert event["decision"]["rule_versions"] == {"velocity": 2}

    # Audit: the stored version shows the thresholds that decided.
    audited = rules_api.get(f"/rules/versions/{third['rules_version']}").json()
    velocity = next(r for r in audited["rules"] if r["code"] == "velocity")
    assert velocity["rule_version"] == third["rule_versions"]["velocity"]
    assert velocity["params"]["limit"] == 2
    before = rules_api.get("/rules/versions/1").json()
    assert next(r for r in before["rules"] if r["code"] == "velocity")["params"]["limit"] == 5


def test_a_past_decision_keeps_its_version_after_the_catalog_changes(rules_api, events):
    payloads = _payloads_p2p(_minutos(0, 1, 2, 3))
    rules_api.put(
        "/rules/velocity",
        json={"action": "HOLD", "params": {"window_minutes": 10, "limit": 2}},
    )
    _wait_for_refresh()
    held = [_decide(p) for p in payloads[:3]][-1]
    assert (held["rules_version"], held["rule_versions"]) == ("2", {"velocity": 2})

    disabled = rules_api.post("/rules/velocity/disable")
    assert disabled.json()["catalog_version"] == 3
    _wait_for_refresh()

    # A resend returns the stored decision with the version it used...
    replay = _decide(payloads[2])
    assert replay["idempotent_replay"] is True
    assert replay["decision"] == "HOLD"
    assert (replay["rules_version"], replay["rule_versions"]) == ("2", {"velocity": 2})

    # ...while a new one already decides with version 3.
    fourth = _decide(payloads[3])
    assert fourth["decision"] == "APPROVE"
    assert fourth["rules_triggered"] == []
    assert (fourth["rules_version"], fourth["rule_versions"]) == ("3", {})


def test_every_catalog_rule_has_code_and_can_be_disabled(rules_api, events):
    published = rules_api.get("/rules").json()
    assert published["version"] == 1
    types = {r["type"] for r in published["rules"]} - {"default_timeout"}
    assert types == set(rules.REGISTRY)

    # Every rule off: an owner on the restricted list is not rejected.
    for code in sorted(r["code"] for r in published["rules"] if r["type"] in types):
        response = rules_api.post(f"/rules/{code}/disable")
        assert response.status_code == 200, response.text
    _wait_for_refresh()

    decision = _decide(_payload_qr(_cuenta_del_seed(en_lista=True)))
    assert decision["rules_version"] == str(1 + len(types))
    assert decision["rules_triggered"] == []
    assert decision["decision"] == "APPROVE"
