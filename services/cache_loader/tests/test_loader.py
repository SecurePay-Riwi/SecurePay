"""The cache loader (HU-67, contract C5).

The loader writes into a scratch Valkey database (15), so the keys the
engine tests read in database 0 stay as they are. The last test needs the
seed loaded in PostgreSQL.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import pytest
import valkey
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from services.cache_loader import loader
from shared.cache import VALKEY_URL, build_client
from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario
from shared.refdata import (
    REFDATA_LOADED_AT,
    REFDATA_TTL_HOURS,
    RESTRICTED_DOCS,
    RESTRICTED_DOCS_NEXT,
    RESTRICTED_LOADED_AT,
    account_key,
    digits,
    merchant_key,
)

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


@pytest.fixture
def cache():
    url = urlunsplit(urlsplit(VALKEY_URL)._replace(path="/15"))
    client = build_client(url, cluster=False)
    try:
        client.flushdb()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")
    yield client
    client.flushdb()


def test_restricted_list_is_replaced_in_one_step(cache):
    assert loader.write_restricted(cache, ["111", "222", "111"], NOW) == 2

    assert set(cache.smembers(RESTRICTED_DOCS)) == {"111", "222"}
    assert not cache.exists(RESTRICTED_DOCS_NEXT)
    assert cache.get(RESTRICTED_LOADED_AT) == NOW.isoformat()


def test_a_document_taken_off_the_list_is_gone_after_the_next_load(cache):
    loader.write_restricted(cache, ["111", "222"], NOW)
    later = NOW + timedelta(days=1)

    loader.write_restricted(cache, ["111"], later)

    assert set(cache.smembers(RESTRICTED_DOCS)) == {"111"}
    assert cache.get(RESTRICTED_LOADED_AT) == later.isoformat()


def test_an_empty_list_is_loaded_with_nobody_on_it(cache):
    loader.write_restricted(cache, ["111"], NOW)

    assert loader.write_restricted(cache, [], NOW) == 0

    # No set (Valkey has no empty sets), but the mark says it was loaded.
    assert not cache.exists(RESTRICTED_DOCS)
    assert cache.exists(RESTRICTED_LOADED_AT)


def test_a_leftover_next_key_does_not_leak_into_the_list(cache):
    # A load that died halfway left {restricted}:docs:next behind.
    cache.sadd(RESTRICTED_DOCS_NEXT, "999")

    loader.write_restricted(cache, ["111"], NOW)

    assert set(cache.smembers(RESTRICTED_DOCS)) == {"111"}


def test_hashes_are_written_in_batches_with_their_ttl(cache, monkeypatch):
    monkeypatch.setattr(loader, "BATCH", 2)
    entries = [
        (account_key(i), {"currency": "COP", "status": "activa"}) for i in range(5)
    ]

    assert loader.write_hashes(cache, entries, ttl_seconds=3600) == 5

    for i in range(5):
        assert cache.hgetall(account_key(i)) == {"currency": "COP", "status": "activa"}
        assert 3590 < cache.ttl(account_key(i)) <= 3600


def test_a_new_load_renews_the_ttl(cache):
    cache.hset(merchant_key("m1"), mapping={"status": "activo"})
    cache.expire(merchant_key("m1"), 10)

    loader.write_hashes(cache, [(merchant_key("m1"), {"status": "activo"})], 3600)

    assert cache.ttl(merchant_key("m1")) > 10


def test_load_copies_the_seed_into_the_cache(cache):
    try:
        with loader.SessionLocal() as session:
            counts = loader.load(session, cache, NOW)
            account, document = session.execute(
                select(Cuenta, Usuario.documento)
                .join(Usuario, Usuario.id == Cuenta.user_id)
                .limit(1)
            ).one()
            merchant = session.scalars(select(Comercio).limit(1)).one()
            listed = {
                digits(d) for d in session.scalars(select(ListaRestrictiva.documento))
            }
            totals = (
                session.query(Cuenta).count(),
                session.query(Comercio).count(),
            )
    except OperationalError:
        pytest.skip("PostgreSQL with the seed is not available")

    assert (counts["accounts"], counts["merchants"]) == totals
    assert counts["restricted"] == len(listed)
    assert cache.hgetall(account_key(account.id)) == {
        "currency": account.moneda,
        "user_id": str(account.user_id),
        "document": digits(document),
        "status": account.estado,
    }
    assert cache.hgetall(merchant_key(merchant.id)) == {
        "status": merchant.estado,
        "category": merchant.categoria,
    }
    assert cache.ttl(account_key(account.id)) > (REFDATA_TTL_HOURS - 1) * 3600
    assert set(cache.smembers(RESTRICTED_DOCS)) == listed
    assert cache.get(REFDATA_LOADED_AT) == NOW.isoformat()
