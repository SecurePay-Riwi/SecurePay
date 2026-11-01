"""The Swagger page (/docs) documents what the cases API answers.

No database needed: it only reads /openapi.json. Each story adds its
endpoints to EXPECTED and checks its examples in test_examples_are_valid.
"""

from fastapi.testclient import TestClient

from services.cases_api.main import app
from services.cases_api.schemas import (
    AccountTransactionPage,
    Health,
    RelatedAccountList,
    RestrictedListReportPage,
    SuspiciousReport,
)

# Not `with`: the lifespan (database) does not run.
client = TestClient(app)

EXPECTED = {
    ("get", "/health"): ["200", "503"],
    ("get", "/compliance/restricted-list-reports"): ["200", "400", "503"],
    ("get", "/reports/suspicious"): ["200", "400", "503"],
    ("get", "/accounts/{account_id}/transactions"): ["200", "400", "503"],
    ("get", "/accounts/{account_id}/related-accounts"): ["200", "400", "503"],
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

    suspicious = "/reports/suspicious"
    SuspiciousReport.model_validate(_example("get", suspicious, "200"))
    csv_example = _paths()[suspicious]["get"]["responses"]["200"]["content"]["text/csv"]["example"]
    assert csv_example.startswith("case_id,transaction_id,account_id,pattern,")
    for status in ("400", "503"):
        assert set(_example("get", suspicious, status)) == {"detail"}

    history = "/accounts/{account_id}/transactions"
    AccountTransactionPage.model_validate(_example("get", history, "200"))
    for status in ("400", "503"):
        assert set(_example("get", history, status)) == {"detail"}

    related = "/accounts/{account_id}/related-accounts"
    RelatedAccountList.model_validate(_example("get", related, "200"))
    for status in ("400", "503"):
        assert set(_example("get", related, status)) == {"detail"}


def test_the_reports_period_is_from_and_to():
    params = _paths()["/compliance/restricted-list-reports"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["from", "to", "page", "size"]


def test_the_suspicious_report_takes_a_period_and_a_format():
    params = _paths()["/reports/suspicious"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["from", "to", "format"]


def test_the_account_history_is_paginated_by_days():
    params = _paths()["/accounts/{account_id}/transactions"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["account_id", "days", "page", "size"]


def test_the_related_accounts_take_days():
    params = _paths()["/accounts/{account_id}/related-accounts"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["account_id", "days"]


def test_title():
    assert client.get("/openapi.json").json()["info"]["title"] == "SecurePay cases API"
