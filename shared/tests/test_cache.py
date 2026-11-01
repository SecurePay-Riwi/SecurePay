import valkey

from shared import cache


def test_single_node_client_by_default():
    client = cache.build_client("redis://localhost:6379/0", cluster=False)
    assert type(client) is valkey.Valkey


def test_cluster_client_when_asked(monkeypatch):
    # ValkeyCluster connects when it is built; only the choice is checked here.
    built = []
    monkeypatch.setattr(
        valkey.ValkeyCluster,
        "from_url",
        classmethod(lambda cls, url, **kw: built.append((url, kw)) or "cluster"),
    )

    assert cache.build_client("rediss://cache.example:6379", cluster=True) == "cluster"
    assert built == [("rediss://cache.example:6379", {"decode_responses": True})]


def test_get_cache_builds_one_client_on_first_use(monkeypatch):
    calls = []
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "build_client", lambda: calls.append(1) or object())

    first = cache.get_cache()
    assert cache.get_cache() is first
    assert calls == [1]


def test_get_cache_retries_after_a_failed_build(monkeypatch):
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise valkey.exceptions.ConnectionError("cache down")
        return "client"

    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "build_client", flaky)

    try:
        cache.get_cache()
    except valkey.exceptions.ConnectionError:
        pass
    assert cache.get_cache() == "client"
