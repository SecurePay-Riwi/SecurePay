"""The Swagger page (/docs) documents what the cases API answers.

No database needed: it only reads /openapi.json. Each story adds its
endpoints to EXPECTED and checks its examples in test_examples_are_valid.
"""

from fastapi.testclient import TestClient

from services.cases_api.main import app
from services.cases_api.schemas import Health

# Not `with`: the lifespan (database) does not run.
client = TestClient(app)

EXPECTED = {
    ("get", "/health"): ["200", "503"],
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


def test_title():
    assert client.get("/openapi.json").json()["info"]["title"] == "SecurePay cases API"
