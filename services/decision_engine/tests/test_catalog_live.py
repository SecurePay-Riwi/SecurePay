from shared.rule_catalog import CATALOG_KEY, default_catalog
from services.decision_engine import catalog


class FakeCache:
    def __init__(self, value=None): self.value = value
    def get(self, key):
        assert key == CATALOG_KEY
        return self.value


def test_current_reads_live_catalog(monkeypatch):
    live = default_catalog().model_copy(update={"version": 12, "author": "test"})
    monkeypatch.setattr(catalog, "get_cache", lambda: FakeCache(live.model_dump_json()))
    assert catalog.current().version == 12
    assert catalog.current().author == "test"


def test_current_falls_back_when_valkey_fails(monkeypatch):
    def fail(): raise ConnectionError("unavailable")
    monkeypatch.setattr(catalog, "get_cache", fail)
    assert catalog.current().version == 0


def test_current_falls_back_for_invalid_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "get_cache", lambda: FakeCache("{invalid"))
    assert catalog.current().version == 0
