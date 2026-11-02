"""Loads the reference data the engine reads into the cache (HU-67,
contract C5): every account with its owner's document, every merchant
and the restricted list, from PostgreSQL.

    uv run python -m services.cache_loader      (Compose: after the seed)
    handler(event, context)                     (AWS: daily Lambda)

Accounts and merchants are written with a pipeline without transaction,
in batches, each with REFDATA_TTL_HOURS of life that the next load
renews: what was deleted at the source expires on its own. The list is
written to {restricted}:docs:next and RENAMEd over {restricted}:docs, so
the engine never sees half a list and a document taken off it is gone
after the load. Every command touches one key (ElastiCache Serverless).
"""

import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared import db
from shared.cache import get_cache
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

log = logging.getLogger(__name__)

SessionLocal = db.SessionLocal

# Rows read from PostgreSQL and commands sent to Valkey at a time.
BATCH = 5000


def account_entries(session: Session) -> Iterator[tuple[str, dict]]:
    """acct:<id> and its hash, for every account."""
    query = (
        select(Cuenta.id, Cuenta.moneda, Cuenta.user_id, Usuario.documento, Cuenta.estado)
        .join(Usuario, Usuario.id == Cuenta.user_id)
        .execution_options(yield_per=BATCH)
    )
    for account_id, currency, user_id, document, status in session.execute(query):
        yield account_key(account_id), {
            "currency": currency,
            "user_id": str(user_id),
            "document": digits(document),
            "status": status,
        }


def merchant_entries(session: Session) -> Iterator[tuple[str, dict]]:
    """merch:<id> and its hash, for every merchant."""
    query = select(Comercio.id, Comercio.estado, Comercio.categoria).execution_options(
        yield_per=BATCH
    )
    for merchant_id, status, category in session.execute(query):
        yield merchant_key(merchant_id), {"status": status, "category": category}


def restricted_documents(session: Session) -> Iterator[str]:
    """Every listed document, digits only."""
    query = select(ListaRestrictiva.documento).execution_options(yield_per=BATCH)
    for (document,) in session.execute(query):
        if digits(document):
            yield digits(document)


def write_hashes(cache, entries: Iterable[tuple[str, dict]], ttl_seconds: int) -> int:
    """HSET and EXPIRE each key, BATCH keys per round trip. Returns how
    many keys were written."""
    count = 0
    pipe = cache.pipeline(transaction=False)
    for key, mapping in entries:
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, ttl_seconds)
        count += 1
        if count % BATCH == 0:
            pipe.execute()
            pipe = cache.pipeline(transaction=False)
    pipe.execute()
    return count


def write_restricted(cache, documents: Iterable[str], now: datetime) -> int:
    """Replace the restricted list in one step and mark it as loaded.
    Returns how many different documents it has."""
    cache.delete(RESTRICTED_DOCS_NEXT)
    count = 0
    batch: list[str] = []
    for document in documents:
        batch.append(document)
        if len(batch) == BATCH:
            count += cache.sadd(RESTRICTED_DOCS_NEXT, *batch)
            batch = []
    if batch:
        count += cache.sadd(RESTRICTED_DOCS_NEXT, *batch)

    if count:
        cache.rename(RESTRICTED_DOCS_NEXT, RESTRICTED_DOCS)
    else:
        # An empty set is not a key: nobody is listed, and the mark below
        # tells the engine the list was loaded anyway.
        cache.delete(RESTRICTED_DOCS)
    cache.set(RESTRICTED_LOADED_AT, now.isoformat())
    return count


def load(session: Session, cache=None, now: datetime | None = None) -> dict:
    """Load everything and return how much of each went to the cache."""
    cache = cache or get_cache()
    now = now or datetime.now(UTC)
    ttl_seconds = REFDATA_TTL_HOURS * 3600

    counts = {
        "accounts": write_hashes(cache, account_entries(session), ttl_seconds),
        "merchants": write_hashes(cache, merchant_entries(session), ttl_seconds),
        "restricted": write_restricted(cache, restricted_documents(session), now),
    }
    cache.set(REFDATA_LOADED_AT, now.isoformat())
    counts["loaded_at"] = now.isoformat()
    log.info("Cache loader: %s", counts)
    return counts


def handler(event=None, context=None) -> dict:
    """Lambda entry point (AWS, once a day)."""
    with SessionLocal() as session:
        return load(session)
