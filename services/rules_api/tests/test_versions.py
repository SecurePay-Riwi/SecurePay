"""HU-22: every catalog version is kept, can be read back and never
changes; an old version can be activated again as a new one."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

LIMIT_2 = {"action": "HOLD", "params": {"window_minutes": 10, "limit": 2}}


def test_versions_are_listed_newest_first_with_author_and_change(client):
    client.put("/rules/velocity", json=LIMIT_2, headers={"X-User": "Habith"})

    page = client.get("/rules/versions").json()

    assert page["total"] == 2
    latest, seed = page["versions"]
    assert latest["version"] == 2
    assert latest["author"] == "Habith"
    assert latest["change"]["operation"] == "update"
    assert latest["change"]["code"] == "velocity"
    assert latest["change"]["before"]["params"]["limit"] == 5
    assert latest["change"]["after"]["params"]["limit"] == 2
    assert seed["change"]["operation"] == "seed"


def test_versions_are_paginated(client):
    for limit in (2, 3, 4):
        client.put("/rules/velocity", json={**LIMIT_2, "params": {"window_minutes": 10, "limit": limit}})

    page = client.get("/rules/versions", params={"limit": 2, "offset": 1}).json()

    assert page["total"] == 4
    assert [v["version"] for v in page["versions"]] == [3, 2]
    assert client.get("/rules/versions", params={"limit": 0}).status_code == 400


def test_each_version_keeps_its_whole_catalog(client):
    client.put("/rules/velocity", json=LIMIT_2)

    v1 = client.get("/rules/versions/1").json()
    v2 = client.get("/rules/versions/2").json()

    assert next(r for r in v1["rules"] if r["code"] == "velocity")["params"]["limit"] == 5
    assert next(r for r in v2["rules"] if r["code"] == "velocity")["params"]["limit"] == 2
    assert client.get("/rules/versions/999").status_code == 404


@pytest.mark.parametrize("statement", [
    "UPDATE rule_catalog_versions SET author = 'someone else'",
    "DELETE FROM rule_catalog_versions",
    "TRUNCATE rule_catalog_versions",
])
def test_history_cannot_be_changed_in_the_database(client, isolated, statement):
    with pytest.raises(DBAPIError, match="append-only"), isolated.begin() as conn:
        conn.execute(text(statement))

    with isolated.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM rule_catalog_versions")).scalar() == 1


def test_activate_an_old_version_creates_a_new_one(client):
    client.put("/rules/velocity", json=LIMIT_2)
    client.post("/rules", json={"code": "velocity_1h", "type": "velocity", "action": "HOLD",
                                "params": {"window_minutes": 60, "limit": 20}})

    response = client.post("/rules/versions/1/activate", headers={"X-User": "Habith"})

    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["version"] == 4
    velocity = next(r for r in catalog["rules"] if r["code"] == "velocity")
    assert velocity["params"]["limit"] == 5
    assert velocity["rule_version"] == 3
    # Created after version 1: kept, but disabled.
    assert next(r for r in catalog["rules"] if r["code"] == "velocity_1h")["enabled"] is False
    # History is not rewritten.
    assert client.get("/rules/versions").json()["total"] == 4
    assert client.get("/rules/versions/4").json()["version"] == 4


def test_activate_the_current_catalog_creates_no_version(client):
    assert client.post("/rules/versions/1/activate").json()["version"] == 1
    assert client.post("/rules/versions/9/activate").status_code == 404
