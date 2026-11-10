"""The rules API as API Gateway invokes it in AWS: main.handler with an
HTTP API event, through Mangum, against the same app."""

import json

from services.rules_api import main
from shared.cache import get_cache
from shared.rule_catalog import VERSION_KEY
from shared.tests.http_api_event import http_api_event


def test_the_first_invocation_publishes_the_catalog_and_answers(isolated, monkeypatch):
    monkeypatch.setattr(main, "_lambda_ready", False)

    answer = main.handler(http_api_event("GET", "/rules"), None)

    assert answer["statusCode"] == 200
    codes = [rule["code"] for rule in json.loads(answer["body"])["rules"]]
    assert "velocity" in codes
    assert get_cache().get(VERSION_KEY) == "1"


def test_a_change_through_the_lambda_takes_the_user_from_x_user(isolated, monkeypatch):
    monkeypatch.setattr(main, "_lambda_ready", False)
    event = http_api_event(
        "POST", "/rules/velocity/disable", headers={"x-user": "ana@example.com"}
    )

    answer = main.handler(event, None)

    assert answer["statusCode"] == 200, answer["body"]
    versions = main.handler(http_api_event("GET", "/rules/versions"), None)
    page = json.loads(versions["body"])
    assert page["versions"][0]["author"] == "ana@example.com"


def _as(group: str) -> dict:
    # HTTP API passes an array claim as one string.
    return {"email": f"{group}@example.com", "cognito:groups": f"[{group}]"}


def test_an_analyst_cannot_change_the_catalog(isolated, monkeypatch):
    monkeypatch.setattr(main, "_lambda_ready", False)
    before = json.loads(main.handler(http_api_event("GET", "/rules"), None)["body"])

    for method, path in [
        ("POST", "/rules/velocity/disable"),
        ("POST", "/rules/velocity/enable"),
        ("POST", "/rules/publish"),
        ("POST", "/rules/versions/1/activate"),
    ]:
        answer = main.handler(
            http_api_event(method, path, claims=_as("analista")), None
        )
        assert answer["statusCode"] == 403, (path, answer["body"])

    after = json.loads(main.handler(http_api_event("GET", "/rules"), None)["body"])
    assert after["version"] == before["version"]


def test_an_analyst_can_read_and_the_manager_can_change(isolated, monkeypatch):
    monkeypatch.setattr(main, "_lambda_ready", False)

    read = main.handler(http_api_event("GET", "/rules", claims=_as("analista")), None)
    change = main.handler(
        http_api_event("POST", "/rules/velocity/disable", claims=_as("gerente")), None
    )

    assert read["statusCode"] == 200
    assert change["statusCode"] == 200, change["body"]
    assert json.loads(change["body"])["rule"]["enabled"] is False
