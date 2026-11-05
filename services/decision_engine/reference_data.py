"""Reference data in the cache: accounts, merchants and the restricted
list (contract C5, HU-67).

The cache loader (services/cache_loader/) writes these keys from
PostgreSQL and the engine reads them, so it never opens a connection to
the database. The key names are in shared/refdata.py.

    acct:<account_id>    hash {currency, user_id, document (digits only), status}
    merch:<merchant_id>  hash {status, category}
    {restricted}:docs    set of listed documents (digits only)
    {restricted}:loaded_at, refdata:loaded_at   ISO time of the last load

The loader writes {restricted}:docs:next and RENAMEs it over
{restricted}:docs (same hash tag, valid in cluster mode), so a document
taken off the list is gone after the next load. Account and merchant
keys expire after REFDATA_TTL_HOURS, which every load renews: what was
deleted at the source disappears on its own. One key per command
(ElastiCache Serverless).

Every read returns None (or False) when the data is not there and raises
CacheUnavailable when Valkey does not answer; the engine then answers
with RN-01's default decision (decision D2 of sprint 5).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import valkey

from shared.cache import get_cache
from shared.refdata import (  # noqa: F401 (the key names live in shared/refdata.py)
    REFDATA_LOADED_AT,
    REFDATA_TTL_HOURS,
    RESTRICTED_DOCS,
    RESTRICTED_DOCS_NEXT,
    RESTRICTED_LOADED_AT,
    account_key,
    merchant_key,
)


class CacheUnavailable(Exception):
    """Valkey did not answer a reference data read."""


@dataclass(frozen=True)
class Account:
    """What the engine needs of an account (acct:<id>)."""

    id: str
    currency: str
    user_id: str
    document: str
    status: str


# Another source of the same three reads, for replaying the engine
# without Valkey (services/analytics/replay.py, contract C5). None: the
# cache, as always in the engine.
_source: ContextVar = ContextVar("reference_source", default=None)


@contextmanager
def use_source(source) -> Iterator[None]:
    """Read accounts, merchants and the restricted list from `source`
    inside the block: an object with get_account(account_id),
    merchant_exists(merchant_id) and on_restricted_list(documents), with
    the same answers as the functions below."""
    token = _source.set(source)
    try:
        yield
    finally:
        _source.reset(token)


def _read(command, *args):
    try:
        return command(*args)
    except valkey.exceptions.ValkeyError as exc:
        raise CacheUnavailable(str(exc)) from exc


def uses_cache() -> bool:
    """True unless use_source() put another source in this context."""
    return _source.get() is None


def _account(account_id, data: dict) -> Account | None:
    if not data:
        return None
    return Account(
        id=str(account_id),
        currency=data["currency"],
        user_id=data["user_id"],
        document=data["document"],
        status=data["status"],
    )


def get_account(account_id) -> Account | None:
    """The account, or None if the cache does not have it."""
    if (source := _source.get()) is not None:
        return source.get_account(account_id)
    return _account(account_id, _read(get_cache().hgetall, account_key(account_id)))


def lookup(account_ids, merchant_id=None) -> tuple[dict, bool | None]:
    """Every account (None for one the cache does not have) and whether
    the merchant exists (None without a merchant), in one round trip to
    Valkey: the same answers as get_account() and merchant_exists(), which
    cost one round trip each (load test of 2026-11-05)."""
    ids = [account_id for account_id in account_ids if account_id is not None]
    if (source := _source.get()) is not None:
        accounts = {account_id: source.get_account(account_id) for account_id in ids}
        if merchant_id is None:
            return accounts, None
        return accounts, source.merchant_exists(merchant_id)

    pipe = get_cache().pipeline(transaction=False)
    for account_id in ids:
        pipe.hgetall(account_key(account_id))
    if merchant_id is not None:
        pipe.exists(merchant_key(merchant_id))
    replies = _read(pipe.execute)

    accounts = {
        account_id: _account(account_id, data)
        for account_id, data in zip(ids, replies, strict=False)
    }
    if merchant_id is None:
        return accounts, None
    return accounts, bool(replies[len(ids)])


def merchant_exists(merchant_id) -> bool:
    if (source := _source.get()) is not None:
        return source.merchant_exists(merchant_id)
    return bool(_read(get_cache().exists, merchant_key(merchant_id)))


def on_restricted_list(documents: set[str]) -> bool | None:
    """Whether any of the documents (digits only) is listed.

    None when the list was never loaded ({restricted}:loaded_at is
    missing): an empty set is not a key, so only the mark tells "nobody
    is listed" from "the list is not there".
    """
    if (source := _source.get()) is not None:
        return source.on_restricted_list(documents)
    pipe = get_cache().pipeline(transaction=False)
    queue_restricted(pipe, documents)
    return restricted_answer(_read(pipe.execute))


def queue_restricted(pipe, documents: set[str]) -> int:
    """Queue on a pipeline the commands on_restricted_list() needs, so
    they can share a round trip with other commands. Returns how many
    replies they take; restricted_answer() reads them."""
    if documents:
        pipe.smismember(RESTRICTED_DOCS, sorted(documents))
        pipe.exists(RESTRICTED_LOADED_AT)
        return 2
    pipe.exists(RESTRICTED_LOADED_AT)
    return 1


def restricted_answer(replies: list) -> bool | None:
    """on_restricted_list() from the replies of queue_restricted(). A
    pipeline run with raise_on_error=False returns an error in place of
    its reply: that is CacheUnavailable too."""
    for reply in replies:
        if isinstance(reply, Exception):
            raise CacheUnavailable(str(reply)) from reply
    *hits, loaded = replies
    if hits and any(hits[0]):
        return True
    if not loaded:
        return None
    return False
