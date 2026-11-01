"""The Swagger page (/docs) documents what the cases API answers.

No database needed: it only reads /openapi.json. Each story adds its
endpoints to EXPECTED and checks its examples in test_examples_are_valid.
"""

from fastapi.testclient import TestClient

from services.cases_api.main import app
from services.cases_api.schemas import (
    AccountTransactionPage,
    CaseDetail,
    CasePage,
    Health,
    RelatedAccountList,
    RestrictedListReportPage,
)

# Not `with`: the lifespan (database) does not run.
client = TestClient(app)

EXPECTED = {
    ("get", "/health"): ["200", "503"],
    ("get", "/compliance/restricted-list-reports"): ["200", "400", "503"],
    ("get", "/accounts/{account_id}/transactions"): ["200", "400", "503"],
    ("get", "/accounts/{account_id}/related-accounts"): ["200", "400", "503"],
    ("get", "/cases"): ["200", "400", "503"],
    ("get", "/cases/{case_id}"): ["200", "400", "404", "503"],
    ("put", "/cases/{case_id}/assignee"): ["200", "400", "404", "409", "503"],
    ("post", "/cases/{case_id}/resolution"): ["200", "400", "404", "409", "503"],
}


def _paths() -> dict:
    return client.get("/openapi.json").json()["paths"]


def test_every_status_code_is_documented():
    documented = {
        (method, path): sorted(op["responses"])
        for path, ops in _paths().items()
        for method, op in ops.items()
    }

    # FastAPI's automatic 422 is never answered: invalid input is 400.
    assert documented == EXPECTED


def _example(method, path, status):
    return _paths()[path][method]["responses"][status]["content"]["application/json"]["example"]


def test_examples_are_valid():
    Health.model_validate(_example("get", "/health", "200"))
    assert set(_example("get", "/health", "503")) == {"detail"}

    reports = "/compliance/restricted-list-reports"
    RestrictedListReportPage.model_validate(_example("get", reports, "200"))
    for status in ("400", "503"):
        assert set(_example("get", reports, status)) == {"detail"}

    history = "/accounts/{account_id}/transactions"
    AccountTransactionPage.model_validate(_example("get", history, "200"))
    for status in ("400", "503"):
        assert set(_example("get", history, status)) == {"detail"}

    related = "/accounts/{account_id}/related-accounts"
    RelatedAccountList.model_validate(_example("get", related, "200"))
    for status in ("400", "503"):
        assert set(_example("get", related, status)) == {"detail"}

    CasePage.model_validate(_example("get", "/cases", "200"))
    for status in ("400", "503"):
        assert set(_example("get", "/cases", status)) == {"detail"}

    case = "/cases/{case_id}"
    CaseDetail.model_validate(_example("get", case, "200"))
    for status in ("400", "404", "503"):
        assert set(_example("get", case, status)) == {"detail"}

    assignee = "/cases/{case_id}/assignee"
    assigned = CaseDetail.model_validate(_example("put", assignee, "200"))
    assert assigned.events[-1].type == "ASSIGNED"
    for status in ("400", "404", "409", "503"):
        assert set(_example("put", assignee, status)) == {"detail"}

    resolution = "/cases/{case_id}/resolution"
    resolved = CaseDetail.model_validate(_example("post", resolution, "200"))
    assert (resolved.outcome, resolved.final_decision) == ("FRAUD", "REJECT")
    for status in ("400", "404", "409", "503"):
        assert set(_example("post", resolution, status)) == {"detail"}


def test_the_reports_period_is_from_and_to():
    params = _paths()["/compliance/restricted-list-reports"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["from", "to", "page", "size"]


def test_the_account_history_is_paginated_by_days():
    params = _paths()["/accounts/{account_id}/transactions"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["account_id", "days", "page", "size"]


def test_the_related_accounts_take_days():
    params = _paths()["/accounts/{account_id}/related-accounts"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["account_id", "days"]


def test_the_inbox_filters_and_paginates():
    params = _paths()["/cases"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["status", "assignee", "page", "size"]


def test_assigning_needs_x_user():
    params = _paths()["/cases/{case_id}/assignee"]["put"]["parameters"]
    assert [p["name"] for p in params] == ["case_id", "x-user"]


def test_resolving_needs_x_user():
    params = _paths()["/cases/{case_id}/resolution"]["post"]["parameters"]
    assert [p["name"] for p in params] == ["case_id", "x-user"]


def test_title():
    assert client.get("/openapi.json").json()["info"]["title"] == "SecurePay cases API"
