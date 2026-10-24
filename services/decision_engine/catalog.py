"""The rule catalog the engine decides with (HU-20, contract C4).

The rules API publishes each catalog version in Valkey. The engine keeps
the last valid one in memory and, at most once every
RULES_REFRESH_SECONDS, reads `{rules}:version`; only when it changed
does it read and validate `{rules}:catalog`. One thread refreshes at a
time; the others keep deciding with the snapshot they have.

current() answers in a few milliseconds and never raises: if Valkey
fails or the catalog is invalid, it keeps the last valid snapshot, and
the code defaults (version 0) until one was ever loaded.
"""

import logging
import os
from threading import Lock
from time import monotonic

from shared.cache import get_cache
from shared.rule_catalog import (
    CATALOG_KEY,
    VERSION_KEY,
    CatalogSnapshot,
    default_catalog,
)

logger = logging.getLogger(__name__)

REFRESH_SECONDS = float(os.getenv("RULES_REFRESH_SECONDS", "1"))

if REFRESH_SECONDS < 0:
    raise ValueError("RULES_REFRESH_SECONDS cannot be negative.")

_lock = Lock()
_snapshot: CatalogSnapshot = default_catalog()
_checked_at: float | None = None


def current() -> CatalogSnapshot:
    """The active catalog. Read once per decision: every rule, the
    default decision and rules_version use the same snapshot."""
    global _checked_at

    if _checked_at is not None and monotonic() - _checked_at < REFRESH_SECONDS:
        return _snapshot
    if not _lock.acquire(blocking=False):
        return _snapshot
    try:
        _checked_at = monotonic()
        _refresh()
    finally:
        _lock.release()
    return _snapshot


def _refresh() -> None:
    global _snapshot

    try:
        cache = get_cache()
        version = cache.get(VERSION_KEY)
        # Nothing published (or Valkey lost it): keep what we have.
        if version is None or version == str(_snapshot.version):
            return
        raw = cache.get(CATALOG_KEY)
    except Exception:  # a decision never fails because of the catalog
        logger.warning("Rule catalog not refreshed: Valkey is not available", exc_info=True)
        return

    try:
        snapshot = CatalogSnapshot.model_validate_json(raw)
    except Exception:
        logger.exception("Rule catalog version %s is invalid; keeping version %s",
                         version, _snapshot.version)
        return

    _snapshot = snapshot
    logger.info("Rule catalog version %s loaded", snapshot.version)


def reset() -> None:
    """Back to the code defaults; the next call reads Valkey. For tests."""
    global _snapshot, _checked_at
    with _lock:
        _snapshot = default_catalog()
        _checked_at = None
