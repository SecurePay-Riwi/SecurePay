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
