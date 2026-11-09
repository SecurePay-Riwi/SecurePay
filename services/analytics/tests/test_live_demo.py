import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from infra.load import accounts as account_export
from services.analytics import live_demo
from services.decision_engine.main import app


def test_committed_live_accounts_match_the_seed_fixture():
    assert live_demo.OUTPUT.read_text(encoding="utf-8") == live_demo.render(
        live_demo.build()
    )


def test_live_accounts_are_active_and_restricted_account_is_excluded():
    seed = json.loads(live_demo.SOURCE.read_text(encoding="utf-8"))
    data = live_demo.build()
    active_ids = {account["id"] for account in seed["accounts"]}
    restricted_ids = set(seed["restricted_accounts"])
    demo_ids = {
        account_id for accounts in data["accounts"].values() for account_id in accounts
    }

    assert data["restricted_account_id"] in restricted_ids
    assert data["restricted_account_id"] in active_ids
    assert demo_ids.isdisjoint(restricted_ids)
    assert demo_ids.issubset(active_ids)
    assert set(data["merchants"]) == set(seed["merchants"])


def test_account_export_matches_documents_with_the_restricted_list():
    listed_account = SimpleNamespace(id=uuid4(), moneda="USD", documento="1.234-567")
    unlisted_account = SimpleNamespace(id=uuid4(), moneda="COP", documento="987-654")

    class FakeResult:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, query):
            statement = str(query)
            if "listas_restrictivas" in statement:
                return FakeResult([("1234567",)])
            if "comercios" in statement:
                return FakeResult([SimpleNamespace(id=uuid4())])
            return FakeResult([listed_account, unlisted_account])

    result = account_export.read(FakeSession())

    assert result["restricted_accounts"] == [str(listed_account.id)]
    assert [account["currency"] for account in result["accounts"]] == ["USD", "COP"]
    assert len(result["merchants"]) == 1


def test_engine_cors_is_limited_to_the_live_demo_origins():
    client = TestClient(app)
    for origin in (
        "https://securepay-riwi.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ):
        response = client.options(
            "/transactions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

    rejected = client.options(
        "/transactions",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
