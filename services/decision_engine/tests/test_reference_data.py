"""HU-67: the engine reads accounts, merchants and the restricted list
from the cache, and D2 decides what is missing there.

The reads go to a scratch Valkey database (15); the decisions use fake
reference data, so nothing here needs PostgreSQL.
"""

import subprocess
import sys
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import catalog, reference_data
from services.decision_engine import decision_service as ds
from services.decision_engine.reference_data import Account, CacheUnavailable
from services.decision_engine.schemas import TransactionRequest
from shared.cache import VALKEY_URL, build_client


@pytest.fixture
def cache(monkeypatch):
    url = urlunsplit(urlsplit(VALKEY_URL)._replace(path="/15"))
    client = build_client(url, cluster=False)
    try:
        client.flushdb()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")
    monkeypatch.setattr(reference_data, "get_cache", lambda: client)
    yield client
    client.flushdb()


# The reads.


def test_an_account_comes_back_with_its_owner_document(cache):
    account_id, user_id = uuid4(), uuid4()
    cache.hset(
        reference_data.account_key(account_id),
        mapping={
            "currency": "COP",
            "user_id": str(user_id),
            "document": "1000000027",
            "status": "activa",
        },
    )

    assert reference_data.get_account(account_id) == Account(
        str(account_id), "COP", str(user_id), "1000000027", "activa"
    )


def test_missing_data_is_none(cache):
    assert reference_data.get_account(uuid4()) is None
    assert reference_data.merchant_exists(uuid4()) is False


def test_a_merchant_exists_when_its_key_does(cache):
    merchant_id = uuid4()
    cache.hset(reference_data.merchant_key(merchant_id), mapping={"status": "activo"})

    assert reference_data.merchant_exists(merchant_id) is True


def test_the_restricted_list_is_none_until_it_is_loaded(cache):
    assert reference_data.on_restricted_list({"111"}) is None
    assert reference_data.on_restricted_list(set()) is None

    cache.set(reference_data.RESTRICTED_LOADED_AT, "2026-11-02T07:00:00+00:00")

    assert reference_data.on_restricted_list({"111"}) is False
    assert reference_data.on_restricted_list(set()) is False


def test_a_listed_document_is_found(cache):
    cache.sadd(reference_data.RESTRICTED_DOCS, "111")
    cache.set(reference_data.RESTRICTED_LOADED_AT, "2026-11-02T07:00:00+00:00")

    assert reference_data.on_restricted_list({"999", "111"}) is True


def test_valkey_down_is_cache_unavailable(monkeypatch):
    down = build_client("redis://localhost:1/0", cluster=False)
    monkeypatch.setattr(reference_data, "get_cache", lambda: down)

    with pytest.raises(CacheUnavailable):
        reference_data.get_account(uuid4())
    with pytest.raises(CacheUnavailable):
        reference_data.on_restricted_list({"111"})


# The decisions (D2).


def _payload(amount="10.00", merchant=False) -> TransactionRequest:
    """A USD withdrawal, or a QR payment to a merchant."""
    return TransactionRequest(
        id=uuid4(),
        type="QR" if merchant else "RETIRO",
        channel="APP" if merchant else "CAJERO",
        source_account_id=uuid4(),
        merchant_id=uuid4() if merchant else None,
        amount=amount,
        currency="USD",
        source_balance_before="1000.00",
        source_balance_after=f"{1000 - float(amount):.2f}",
        device_id=uuid4(),
        transaction_date=datetime.now(UTC),
    )


@pytest.fixture
def known_account(monkeypatch):
    """Every account exists in USD, every merchant exists, and the
    history is not written."""
    monkeypatch.setattr(
        reference_data,
        "get_account",
        lambda account_id: Account(str(account_id), "USD", "u", "123", "activa"),
    )
    monkeypatch.setattr(reference_data, "merchant_exists", lambda _id: True)
    monkeypatch.setattr(ds.history, "record_outgoing", lambda *a, **k: [])
    monkeypatch.setattr(ds.history, "record_device", lambda *a, **k: [])


@pytest.mark.parametrize("amount", ["10.00", "80.00"])
def test_list_not_loaded_holds_whatever_the_amount(known_account, monkeypatch, amount):
    monkeypatch.setattr(reference_data, "on_restricted_list", lambda _docs: None)

    result = ds._decide(_payload(amount), catalog.current())

    assert result["decision"] == "HOLD"
    assert result["by_default"] is True
    assert "restricted list is not loaded" in result["decision_reason"]


def test_list_not_loaded_does_not_matter_if_the_rule_is_disabled(
    known_account, monkeypatch
):
    monkeypatch.setattr(reference_data, "on_restricted_list", lambda _docs: None)
    base = catalog.current()
    snapshot = base.model_copy(
        update={
            "rules": [
                r.model_copy(update={"enabled": False})
                if r.code == ds.RESTRICTED_RULE
                else r
                for r in base.rules
            ]
        }
    )

    result = ds._decide(_payload("10.00"), snapshot)

    assert result["by_default"] is False


@pytest.mark.parametrize(
    ("amount", "expected"), [("10.00", "APPROVE"), ("80.00", "HOLD")]
)
def test_account_missing_in_the_cache_is_decided_by_rn01(monkeypatch, amount, expected):
    monkeypatch.setattr(reference_data, "get_account", lambda _id: None)

    result = ds._decide(_payload(amount), catalog.current())

    assert result["decision"] == expected
    assert result["by_default"] is True
    assert result["rules_triggered"] == [ds.DEFAULT_RULE]
    assert "is not in the cache" in result["decision_reason"]


def test_merchant_missing_in_the_cache_is_decided_by_rn01(known_account, monkeypatch):
    monkeypatch.setattr(reference_data, "merchant_exists", lambda _id: False)

    result = ds._decide(_payload("10.00", merchant=True), catalog.current())

    assert result["by_default"] is True
    assert "merchant" in result["decision_reason"]


def test_another_currency_is_still_refused(known_account):
    payload = _payload("10.00").model_copy(update={"currency": "EUR"})

    with pytest.raises(ds.InvalidReference):
        ds._decide(payload, catalog.current())


def test_cache_down_is_decided_by_rn01_in_time(monkeypatch):
    def down(_id):
        raise CacheUnavailable("simulated")

    monkeypatch.setattr(reference_data, "get_account", down)

    start = perf_counter()
    result, _ = ds.process_transaction(_payload("80.00"))
    elapsed_ms = (perf_counter() - start) * 1000

    assert result["decision"] == "HOLD"
    assert result["by_default"] is True
    assert "the cache did not answer" in result["decision_reason"]
    assert elapsed_ms < 200


# The engine never opens a connection to PostgreSQL.


def test_the_engine_does_not_import_the_database_module():
    code = (
        "import sys, services.decision_engine.main; "
        "sys.exit('shared.db' in sys.modules or 'shared.models' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
