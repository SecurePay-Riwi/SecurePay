"""The Swagger page (/docs) documents what the engine really answers.

No database or Valkey needed: it only reads /openapi.json.
"""

from fastapi.testclient import TestClient

from services.decision_engine.main import app
from services.decision_engine.schemas import TransactionRequest, TransactionResponse

client = TestClient(app)


def _post_transactions() -> dict:
    return client.get("/openapi.json").json()["paths"]["/transactions"]["post"]


def test_every_status_code_the_engine_returns_is_documented():
    # 400 instead of FastAPI's default 422 for an invalid body.
    assert sorted(_post_transactions()["responses"]) == [
        "200", "400", "409", "422", "500", "503",
    ]


def test_request_examples_are_valid_transactions():
    examples = _post_transactions()["requestBody"]["content"][
        "application/json"
    ]["examples"]

    for example in examples.values():
        TransactionRequest.model_validate(example["value"])


def test_response_examples_are_valid_responses():
    examples = _post_transactions()["responses"]["200"]["content"][
        "application/json"
    ]["examples"]

    for example in examples.values():
        TransactionResponse.model_validate(example["value"])
