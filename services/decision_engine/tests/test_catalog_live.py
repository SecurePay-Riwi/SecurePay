"""HU-20 and HU-21: the engine decides with the catalog the rules API
publishes in Valkey, without a restart.

The unit tests fake Valkey. The last two need PostgreSQL with the seed
and Valkey, like test_api.py.
"""

import pytest

from services.decision_engine import catalog
from services.decision_engine.tests.test_api import (
    _decisiones,
    _minutos,
    _payloads_p2p,
    client,
)
from shared.cache import get_cache
from shared.rule_catalog import (
    CATALOG_KEY,
    VERSION_KEY,
    CatalogSnapshot,
    default_catalog,
)


def _with(version: int, **velocity) -> CatalogSnapshot:
    """The defaults at another version, with velocity changed."""
    base = default_catalog()
    rules = [
        r.model_copy(update=velocity) if r.code == "velocity" else r
        for r in base.rules
    ]
    return base.model_copy(update={"version": version, "author": "test", "rules": rules})


class FakeCache:
    def __init__(self, snapshot: CatalogSnapshot | None = None, raw: str | None = None):
        self.values = {}
        self.reads = 0
        if snapshot is not None:
            self.publish(snapshot)
        if raw is not None:
            self.values = {VERSION_KEY: "9", CATALOG_KEY: raw}

    def publish(self, snapshot):
        self.values = {VERSION_KEY: str(snapshot.version), CATALOG_KEY: snapshot.model_dump_json()}

    def get(self, key):
        self.reads += 1
        return self.values.get(key)


@pytest.fixture(autouse=True)
def fresh_catalog(monkeypatch):
    catalog.reset()
    monkeypatch.setattr(catalog, "REFRESH_SECONDS", 0)
    yield
    catalog.reset()


def test_defaults_until_something_is_published(monkeypatch):
    monkeypatch.setattr(catalog, "get_cache", lambda: FakeCache())

    assert catalog.current().version == 0


def test_reads_the_published_catalog(monkeypatch):
    cache = FakeCache(_with(12, params={"window_minutes": 10, "limit": 2}))
    monkeypatch.setattr(catalog, "get_cache", lambda: cache)

    snapshot = catalog.current()

    assert snapshot.version == 12
    assert snapshot.get("velocity").params["limit"] == 2


def test_reads_the_catalog_only_when_the_version_changes(monkeypatch):
    cache = FakeCache(_with(3))
    monkeypatch.setattr(catalog, "get_cache", lambda: cache)

    catalog.current()
    reads = cache.reads
    catalog.current()

    # Only {rules}:version again, not the whole catalog.
    assert cache.reads == reads + 1


def test_checks_at_most_once_per_refresh_period(monkeypatch):
    cache = FakeCache(_with(3))
    monkeypatch.setattr(catalog, "get_cache", lambda: cache)
    monkeypatch.setattr(catalog, "REFRESH_SECONDS", 60)

    catalog.current()
    reads = cache.reads
    for _ in range(100):
        catalog.current()

    assert cache.reads == reads


def test_keeps_the_last_catalog_when_valkey_fails(monkeypatch):
    cache = FakeCache(_with(5, enabled=False))
    monkeypatch.setattr(catalog, "get_cache", lambda: cache)
    assert catalog.current().version == 5

    def down():
        raise ConnectionError("Valkey is down")

    monkeypatch.setattr(catalog, "get_cache", down)

    # Not the defaults: velocity stays disabled.
    assert catalog.current().version == 5
    assert catalog.current().get("velocity").enabled is False


def test_keeps_the_last_catalog_when_the_new_one_is_invalid(monkeypatch):
    cache = FakeCache(_with(5))
    monkeypatch.setattr(catalog, "get_cache", lambda: cache)
    catalog.current()

    cache.values = {VERSION_KEY: "6", CATALOG_KEY: "{invalid"}

    assert catalog.current().version == 5


def test_invalid_catalog_before_any_falls_back_to_the_defaults(monkeypatch):
    monkeypatch.setattr(catalog, "get_cache", lambda: FakeCache(raw="{invalid"))

    assert catalog.current().version == 0


@pytest.fixture
def published():
    """Publish in the real Valkey the way the rules API does; remove it
    afterwards so other tests decide with the defaults."""
    cache = get_cache()

    def publish(snapshot):
        cache.set(CATALOG_KEY, snapshot.model_dump_json())
        cache.set(VERSION_KEY, str(snapshot.version))

    yield publish
    cache.delete(CATALOG_KEY, VERSION_KEY)


def test_a_new_limit_applies_to_the_next_decision(published):
    # HU-20: limit 2 instead of 5, no restart.
    published(_with(41, params={"window_minutes": 10, "limit": 2}))

    payloads = _payloads_p2p(_minutos(0, 1, 2))

    assert _decisiones(payloads[:2]) == ["APPROVE", "APPROVE"]
    third = client.post("/transactions", json=payloads[2]).json()
    assert third["decision"] == "HOLD"
    assert third["rules_triggered"] == ["velocity"]
    # RN-08: the decision records the version it used.
    assert third["rules_version"] == "41"


def test_a_disabled_rule_stops_and_comes_back_when_enabled(published):
    # HU-21: with velocity off the sixth transfer is approved; on again,
    # the seventh is held because the history kept being written.
    published(_with(42, enabled=False))
    payloads = _payloads_p2p(_minutos(0, 1, 2, 3, 4, 5, 6))

    assert _decisiones(payloads[:6]) == ["APPROVE"] * 6

    published(_with(43, enabled=True))

    assert _decisiones(payloads[6:]) == ["HOLD"]
