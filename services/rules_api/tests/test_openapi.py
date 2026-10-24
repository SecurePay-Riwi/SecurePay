"""The Swagger page (/docs) documents what the rules API answers.

No database or Valkey needed: it only reads /openapi.json.
"""

from fastapi.testclient import TestClient

from services.rules_api.main import app
from services.rules_api.schemas import RuleChange
from shared.rule_catalog import CatalogSnapshot, RuleEntry

# Not `with`: the lifespan (database) does not run.
client = TestClient(app)

EXPECTED = {
    ("get", "/health"): ["200", "503"],
    ("get", "/rules"): ["200", "503"],
    ("post", "/rules"): ["201", "400", "409", "503"],
    ("get", "/rules/{code}"): ["200", "404", "503"],
    ("put", "/rules/{code}"): ["200", "400", "404", "503"],
    ("post", "/rules/{code}/enable"): ["200", "400", "404", "503"],
    ("post", "/rules/{code}/disable"): ["200", "400", "404", "409", "503"],
    ("get", "/rules/versions"): ["200", "400", "503"],
    ("get", "/rules/versions/{version}"): ["200", "400", "404", "503"],
    ("post", "/rules/versions/{version}/activate"): ["200", "400", "404", "503"],
    ("post", "/rules/publish"): ["200", "503"],
}


def _paths() -> dict:
    return client.get("/openapi.json").json()["paths"]


def test_every_status_code_is_documented():
    paths = _paths()
    documented = {
        (method, path): sorted(op["responses"])
        for path, ops in paths.items()
        for method, op in ops.items()
    }

    # FastAPI's automatic 422 is never answered: invalid input is 400.
    assert documented == EXPECTED


def _example(method, path, status):
    return _paths()[path][method]["responses"][status]["content"]["application/json"]["example"]


def test_examples_are_valid():
    CatalogSnapshot.model_validate(_example("get", "/rules", "200"))
    RuleEntry.model_validate(_example("get", "/rules/{code}", "200"))
    for method, path, status in [
        ("post", "/rules", "201"),
        ("put", "/rules/{code}", "200"),
        ("post", "/rules/{code}/enable", "200"),
        ("post", "/rules/{code}/disable", "200"),
    ]:
        RuleChange.model_validate(_example(method, path, status))
