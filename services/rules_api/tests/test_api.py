"""HU-19, HU-20 and HU-21: create, change, enable and disable rules.
Each change is one catalog version, stored and published to Valkey."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from services.rules_api import publisher
from shared.cache import get_cache
from shared.rule_catalog import CATALOG_KEY, DEFAULT_RULES, VERSION_KEY, CatalogSnapshot

VELOCITY_1H = {
    "code": "velocity_1h", "type": "velocity", "rn": "RN-02", "action": "HOLD",
    "params": {"window_minutes": 60, "limit": 20},
}


def _published() -> CatalogSnapshot:
    return CatalogSnapshot.model_validate_json(get_cache().get(CATALOG_KEY))


def test_startup_stores_and_publishes_the_defaults_as_version_1(client):
    catalog = client.get("/rules").json()

    assert catalog["version"] == 1
    assert catalog["author"] == "code"
    assert [r["code"] for r in catalog["rules"]] == [r.code for r in DEFAULT_RULES]
    assert get_cache().get(VERSION_KEY) == "1"
    assert _published().version == 1


def test_startup_publishes_again_after_valkey_lost_the_catalog(isolated):
    from fastapi.testclient import TestClient

    from services.rules_api.main import app

    with TestClient(app) as c:
        c.put("/rules/velocity", json={"action": "HOLD", "params": {"window_minutes": 10, "limit": 4}})
    get_cache().delete(CATALOG_KEY, VERSION_KEY)

    with TestClient(app):
        assert get_cache().get(VERSION_KEY) == "2"
        assert _published().get("velocity").params["limit"] == 4


def test_get_one_rule(client):
    response = client.get("/rules/velocity")

    assert response.status_code == 200
    assert response.json()["params"] == {"window_minutes": 10, "limit": 5}
    assert client.get("/rules/nope_rule").status_code == 404


def test_create_rule_with_an_existing_type(client):
    response = client.post("/rules", json=VELOCITY_1H, headers={"X-User": "Yulianis"})

    assert response.status_code == 201, response.text
    assert response.json()["catalog_version"] == 2
    assert response.json()["rule"]["rule_version"] == 1
    catalog = _published()
    assert catalog.version == 2
    assert catalog.author == "Yulianis"
    # Created rules go after the defaults.
    assert catalog.rules[-1].code == "velocity_1h"


def test_existing_code_is_409(client):
    assert client.post("/rules", json={**VELOCITY_1H, "code": "velocity"}).status_code == 409
    assert client.get("/rules").json()["version"] == 1


@pytest.mark.parametrize("body", [
    {**VELOCITY_1H, "params": {"window_minutes": 0, "limit": 5}},     # params out of range
    {**VELOCITY_1H, "params": {"window": 10, "limit": 5}},            # unknown param
    {**VELOCITY_1H, "type": "teleport"},                              # unknown type
    {**VELOCITY_1H, "code": "Velocity 1h"},                           # bad code
    {**VELOCITY_1H, "code": "versions"},                              # reserved path
    {**VELOCITY_1H, "type": "default_timeout", "params": {}},         # only one default
    {**VELOCITY_1H, "rule_version": 7},                               # always starts at 1
])
def test_invalid_rule_is_400(client, body):
    response = client.post("/rules", json=body)

    assert response.status_code == 400, response.text
    assert "detail" in response.json()
    assert client.get("/rules").json()["version"] == 1


def test_update_changes_params_and_raises_both_versions(client):
    response = client.put(
        "/rules/velocity",
        json={"action": "HOLD", "params": {"window_minutes": 10, "limit": 2}},
        headers={"X-User": "Habith"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["catalog_version"] == 2
    assert response.json()["rule"]["rule_version"] == 2
    assert _published().get("velocity").params == {"window_minutes": 10, "limit": 2}


def test_invalid_update_keeps_the_rule(client):
    response = client.put("/rules/velocity", json={"action": "HOLD", "params": {"window_minutes": 0, "limit": 2}})

    assert response.status_code == 400
    assert response.json()["detail"] == "The request contains invalid rule data."
    assert response.json()["errors"]
    assert client.get("/rules/velocity").json()["params"]["window_minutes"] == 10
    assert client.get("/rules").json()["version"] == 1


def test_update_cannot_change_code_or_type(client):
    response = client.put("/rules/velocity", json={"action": "HOLD", "type": "mule", "params": {}})

    assert response.status_code == 400


def test_update_unknown_rule_is_404(client):
    assert client.put("/rules/nope_rule", json={"action": "HOLD"}).status_code == 404


def test_same_update_creates_no_version(client):
    body = {"action": "HOLD", "params": {"window_minutes": 10, "limit": 5}}

    response = client.put("/rules/velocity", json=body)

    assert response.status_code == 200
    assert response.json()["catalog_version"] == 1
    assert response.json()["rule"]["rule_version"] == 1


def test_disable_and_enable(client):
    disabled = client.post("/rules/velocity/disable", headers={"X-User": "Jorge"})

    assert disabled.status_code == 200
    assert disabled.json()["rule"]["enabled"] is False
    assert disabled.json()["catalog_version"] == 2
    assert _published().get("velocity").enabled is False

    # Already disabled: no new version.
    assert client.post("/rules/velocity/disable").json()["catalog_version"] == 2

    enabled = client.post("/rules/velocity/enable")
    assert enabled.json()["rule"]["enabled"] is True
    assert enabled.json()["rule"]["rule_version"] == 3
    assert enabled.json()["catalog_version"] == 3


def test_default_decision_cannot_be_disabled(client):
    assert client.post("/rules/default_timeout/disable").status_code == 409
    assert client.get("/rules").json()["version"] == 1


def test_author_header_must_not_be_empty(client):
    assert client.post("/rules/velocity/disable", headers={"X-User": "  "}).status_code == 400


def test_concurrent_writes_get_distinct_versions(client):
    def change(limit):
        return client.put(
            "/rules/velocity",
            json={"action": "HOLD", "params": {"window_minutes": 10, "limit": limit}},
        ).json()["catalog_version"]

    with ThreadPoolExecutor(10) as pool:
        versions = list(pool.map(change, range(10, 20)))

    assert sorted(versions) == list(range(2, 12))
    rule = client.get("/rules/velocity").json()
    # No change was lost: each one raised the rule version.
    assert rule["rule_version"] == 11
    assert _published().version == 11


def test_an_older_version_never_replaces_a_newer_one_in_valkey(client):
    newer = client.put("/rules/velocity", json={"action": "HOLD", "params": {"window_minutes": 10, "limit": 3}})
    assert newer.json()["catalog_version"] == 2

    old = CatalogSnapshot.model_validate(client.get("/rules/versions/1").json())
    assert publisher.publish(old) is False
    assert _published().version == 2


def test_change_is_kept_when_valkey_is_down(client, monkeypatch):
    import valkey

    def down(*args, **kwargs):
        raise valkey.exceptions.ConnectionError("down")

    monkeypatch.setattr(publisher, "publish", down)
    response = client.post("/rules/velocity/disable")

    assert response.status_code == 200
    assert response.json()["catalog_version"] == 2
    assert get_cache().get(VERSION_KEY) == "1"

    monkeypatch.undo()
    assert client.post("/rules/publish").json() == {"version": 2, "published": True}
    assert _published().get("velocity").enabled is False


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_database_is_the_truth(client, isolated):
    client.post("/rules", json=VELOCITY_1H)

    with isolated.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM rules")).scalar() == len(DEFAULT_RULES) + 1
        assert conn.execute(text("SELECT max(version) FROM rule_catalog_versions")).scalar() == 2
