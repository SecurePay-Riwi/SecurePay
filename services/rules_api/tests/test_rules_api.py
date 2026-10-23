from fastapi.testclient import TestClient

from shared.rule_catalog import CATALOG_KEY, VERSION_KEY
from services.rules_api import main, store


class Pipeline:
    def __init__(self, cache): self.cache, self.commands = cache, []
    def set(self, key, value): self.commands.append(("set", key, value)); return self
    def rpush(self, key, value): self.commands.append(("rpush", key, value)); return self
    def publish(self, key, value): self.commands.append(("publish", key, value)); return self
    def execute(self): return [getattr(self.cache, method)(*args) for method, *args in self.commands]


class FakeValkey:
    def __init__(self): self.values, self.lists = {}, {}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value; return True
    def rpush(self, key, value): self.lists.setdefault(key, []).append(value); return len(self.lists[key])
    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]
    def llen(self, key): return len(self.lists.get(key, []))
    def publish(self, channel, value): return 0
    def pipeline(self, transaction=True): return Pipeline(self)


cache = FakeValkey()
client = TestClient(main.app)


def setup_function(monkeypatch):
    cache.values.clear()
    cache.lists.clear()
    monkeypatch.setattr(store, "get_cache", lambda: cache)


def test_create_rule_versions_catalog_and_records_author():
    response = client.post("/rules", headers={"X-Rule-Author": "Anndelgado"}, json={
        "code": "amount_limit", "type": "velocity", "action": "HOLD",
        "params": {"window_minutes": 10, "limit": 4},
    })
    assert response.status_code == 201, response.text
    assert response.json()["version"] == 1
    assert response.json()["author"] == "Anndelgado"
    assert cache.values[VERSION_KEY] == "1"
    assert len(cache.lists[store.HISTORY_KEY]) == 2
    assert cache.values[CATALOG_KEY]


def test_invalid_rule_returns_400_with_reason():
    response = client.post("/rules", json={
        "code": "bad_rule", "type": "velocity", "action": "HOLD",
        "params": {"window_minutes": 0, "limit": 5},
    })
    assert response.status_code == 400 and "errors" in response.json()


def test_disable_rule_creates_immutable_version():
    response = client.patch("/rules/velocity/enabled", json={"enabled": False})
    assert response.status_code == 200 and response.json()["version"] == 1
    assert client.get("/rules/versions").json()["versions"][-1]["version"] == 1
    assert client.get("/rules/versions/0").json()["version"] == 0


def test_mandatory_rule_cannot_be_disabled():
    response = client.patch("/rules/default_timeout/enabled", json={"enabled": False})
    assert response.status_code == 400


def test_duplicate_rule_is_rejected():
    response = client.post("/rules", json={
        "code": "velocity", "type": "velocity", "action": "HOLD",
        "params": {"window_minutes": 10, "limit": 5},
    })
    assert response.status_code == 409


def test_update_increments_catalog_and_rule_versions():
    response = client.patch("/rules/velocity", json={"params": {"window_minutes": 5, "limit": 4}})
    assert response.status_code == 200 and response.json()["version"] == 1
    rule = next(item for item in response.json()["rules"] if item["code"] == "velocity")
    assert rule["rule_version"] == 2


def test_missing_version_returns_404():
    assert client.get("/rules/versions/999").status_code == 404


def test_version_history_describes_changed_fields():
    response = client.patch("/rules/velocity/enabled", json={"enabled": False})
    assert response.status_code == 200
    versions = client.get("/rules/versions").json()["versions"]
    assert versions[-1]["author"] == "api"
    assert {"operation": "updated", "rule": "velocity", "fields": ["enabled", "rule_version"]} in versions[-1]["changes"]


def test_invalid_rule_update_returns_400():
    response = client.patch("/rules/velocity", json={"params": {"window_minutes": 0, "limit": 5}})
    assert response.status_code == 400
    assert "Invalid rule update" in response.json()["detail"]
