"""The cases API as API Gateway invokes it in AWS: main.handler with an
HTTP API event, through Mangum, against the same app."""

import json

from services.cases_api import main
from shared.tests.http_api_event import http_api_event


def test_the_inbox_through_the_lambda(add_case):
    case_id = add_case()

    answer = main.handler(http_api_event("GET", "/cases"), None)

    assert answer["statusCode"] == 200
    assert [c["id"] for c in json.loads(answer["body"])["items"]] == [str(case_id)]


def test_assigning_through_the_lambda_takes_the_user_from_x_user(add_case):
    case_id = add_case()
    event = http_api_event(
        "PUT",
        f"/cases/{case_id}/assignee",
        body={"assignee": "ana@example.com"},
        headers={"x-user": "ana@example.com"},
    )

    answer = main.handler(event, None)

    assert answer["statusCode"] == 200, answer["body"]
    assert json.loads(answer["body"])["assignee"] == "ana@example.com"


def test_a_query_string_reaches_the_route(add_case):
    add_case()

    answer = main.handler(
        http_api_event("GET", "/cases", query="status=RESOLVED"), None
    )

    assert answer["statusCode"] == 200
    assert json.loads(answer["body"])["items"] == []


def test_a_preflight_of_any_path_is_answered():
    # modules/api sends OPTIONS /rules, /cases, ... here without a token.
    for path in ("/rules", "/rules/versions", "/cases", "/reports/suspicious"):
        answer = main.handler(http_api_event("OPTIONS", path), None)

        assert answer["statusCode"] == 204, (path, answer)
