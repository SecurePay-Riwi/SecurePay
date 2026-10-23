"""The live rule catalog used for each decision."""
import json
from functools import cache

from shared.cache import get_cache
from shared.rule_catalog import CATALOG_KEY, CatalogSnapshot, default_catalog


@cache
def _defaults() -> CatalogSnapshot:
    return default_catalog()


def current() -> CatalogSnapshot:
    """Read the latest catalog for each decision; cache failure must not break decisions."""
    try:
        raw = get_cache().get(CATALOG_KEY)
        if raw is None:
            return _defaults()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return CatalogSnapshot.model_validate(json.loads(raw))
    except Exception:
        return _defaults()
