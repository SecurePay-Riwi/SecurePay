"""HU-67 end to end: the cache loader fills Valkey from the seeded
PostgreSQL and the engine decides from it.

Needs the seed loaded in PostgreSQL and Valkey. Every test loads the
whole cache again when it ends.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from services.cache_loader import loader
from services.decision_engine.main import app
from services.decision_engine.tests.test_api import _cuenta_del_seed, _payload_qr
from shared.cache import get_cache
from shared.models import Usuario
from shared.refdata import RESTRICTED_DOCS, RESTRICTED_LOADED_AT, digits

client = TestClient(app)


@pytest.fixture
def full_load():
    """Load everything from PostgreSQL before and after the test."""
    try:
        with loader.SessionLocal() as session:
            loader.load(session)
    except OperationalError:
        pytest.skip("PostgreSQL with the seed is not available")
    yield
    with loader.SessionLocal() as session:
        loader.load(session)


def _owner_document(account) -> str:
    with loader.SessionLocal() as session:
        return digits(session.get(Usuario, account.user_id).documento)


def test_a_document_taken_off_the_list_stops_rejecting_after_the_reload(full_load):
    listed = _cuenta_del_seed(en_lista=True)
    first = client.post("/transactions", json=_payload_qr(listed))
    assert first.json()["decision"] == "REJECT", first.text

    # The next load no longer has the owner's document.
    cache = get_cache()
    others = set(cache.smembers(RESTRICTED_DOCS)) - {_owner_document(listed)}
    loader.write_restricted(cache, others, datetime.now(UTC))

    second = client.post("/transactions", json=_payload_qr(listed))

    assert second.status_code == 200, second.text
    assert second.json()["decision"] != "REJECT"
    assert "restricted_list" not in second.json()["rules_triggered"]


def test_list_not_loaded_holds_even_a_small_payment(full_load):
    get_cache().delete(RESTRICTED_DOCS)
    get_cache().delete(RESTRICTED_LOADED_AT)

    response = client.post("/transactions", json=_payload_qr(_cuenta_del_seed(en_lista=False)))

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "HOLD"
    assert response.json()["by_default"] is True
