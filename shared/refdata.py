"""Cache keys of the reference data (contract C5, HU-67).

The cache loader (services/cache_loader/) writes them from PostgreSQL
and the engine (services/decision_engine/reference_data.py) reads them.
Both import the names from here, so neither service imports the other.
Not part of the published securepay-shared package.

    acct:<account_id>    hash {currency, user_id, document (digits only), status}
    merch:<merchant_id>  hash {status, category}
    {restricted}:docs    set of listed documents (digits only)
    {restricted}:loaded_at, refdata:loaded_at   ISO time of the last load
"""

import os
import re

REFDATA_TTL_HOURS = int(os.getenv("REFDATA_TTL_HOURS", "48"))

RESTRICTED_DOCS = "{restricted}:docs"
RESTRICTED_DOCS_NEXT = "{restricted}:docs:next"
RESTRICTED_LOADED_AT = "{restricted}:loaded_at"
REFDATA_LOADED_AT = "refdata:loaded_at"


def account_key(account_id) -> str:
    return f"acct:{account_id}"


def merchant_key(merchant_id) -> str:
    return f"merch:{merchant_id}"


def digits(document: str) -> str:
    """Keep only the digits: how documents are compared with the list."""
    return re.sub(r"\D", "", document)
