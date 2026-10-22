"""The rule catalog the engine decides with.

For now it is always the code defaults (version 0). HU-20 replaces the
body of current() with the reader of the catalog the rules API publishes
in Valkey; the signature stays, and so do its promises: it answers in a
few milliseconds and never raises.
"""

from functools import cache

from shared.rule_catalog import CatalogSnapshot, default_catalog


@cache
def _defaults() -> CatalogSnapshot:
    return default_catalog()


def current() -> CatalogSnapshot:
    """The active catalog. Read once per decision: every rule, the
    default decision and rules_version use the same snapshot."""
    return _defaults()
