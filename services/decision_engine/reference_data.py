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


def _read(command, *args):
    try:
        return command(*args)
    except valkey.exceptions.ValkeyError as exc:
        raise CacheUnavailable(str(exc)) from exc


def get_account(account_id) -> Account | None:
    """The account, or None if the cache does not have it."""
    data = _read(get_cache().hgetall, account_key(account_id))
    if not data:
        return None
    return Account(
        id=str(account_id),
        currency=data["currency"],
        user_id=data["user_id"],
        document=data["document"],
        status=data["status"],
    )


def merchant_exists(merchant_id) -> bool:
    return bool(_read(get_cache().exists, merchant_key(merchant_id)))


def on_restricted_list(documents: set[str]) -> bool | None:
    """Whether any of the documents (digits only) is listed.

    None when the list was never loaded ({restricted}:loaded_at is
    missing): an empty set is not a key, so only the mark tells "nobody
    is listed" from "the list is not there".
    """
    if documents:
        hits = _read(get_cache().smismember, RESTRICTED_DOCS, sorted(documents))
        if any(hits):
            return True
    if not _read(get_cache().exists, RESTRICTED_LOADED_AT):
        return None
    return False
