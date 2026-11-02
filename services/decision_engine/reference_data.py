"""Reference data in the cache: accounts, merchants and the restricted
list (contract C5, HU-67).

The cache loader (services/cache_loader/, HU-67) writes these keys from
PostgreSQL and the engine reads them, so it never opens a connection to
the database. Step 0 only fixes the key names; HU-67 adds the reads
(get_account, merchant_exists, on_restricted_list).

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
"""

import os

REFDATA_TTL_HOURS = int(os.getenv("REFDATA_TTL_HOURS", "48"))

RESTRICTED_DOCS = "{restricted}:docs"
RESTRICTED_DOCS_NEXT = "{restricted}:docs:next"
RESTRICTED_LOADED_AT = "{restricted}:loaded_at"
REFDATA_LOADED_AT = "refdata:loaded_at"


def account_key(account_id) -> str:
    return f"acct:{account_id}"


def merchant_key(merchant_id) -> str:
    return f"merch:{merchant_id}"
