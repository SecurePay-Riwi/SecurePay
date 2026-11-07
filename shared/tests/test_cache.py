import valkey

from shared import cache


def test_single_node_client_by_default():
    client = cache.build_client("redis://localhost:6379/0", cluster=False)
    assert type(client) is valkey.Valkey
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 2.0
    assert kwargs["socket_connect_timeout"] == 2.0
    assert kwargs["socket_keepalive"] is True


class FakeNodes:
    def initialize(self):
        return "initialized"


class FakeCluster:
    def __init__(self):
        self.nodes_manager = FakeNodes()


def test_cluster_client_when_asked(monkeypatch):
    # ValkeyCluster connects when it is built; only the choice is checked here.
    built = []
    monkeypatch.setattr(
        valkey.ValkeyCluster,
        "from_url",
        classmethod(lambda cls, url, **kw: built.append((url, kw)) or FakeCluster()),
    )

    assert isinstance(
        cache.build_client("rediss://cache.example:6379", cluster=True), FakeCluster
    )
    url, kwargs = built[0]
    assert url == "rediss://cache.example:6379"
    assert kwargs["decode_responses"] is True
    assert kwargs["valkey_connect_func"] is cache._count_connection
    assert {k: kwargs[k] for k in cache.SOCKET_SETTINGS} == cache.SOCKET_SETTINGS


def test_cluster_client_counts_connections_and_refreshes(monkeypatch):
    monkeypatch.setattr(cache, "stats", {"connections": 0, "topology_refreshes": 0})
    client = FakeCluster()
    cache._count_refreshes(client)

    cache._count_connection(object())
    assert client.nodes_manager.initialize() == "initialized"

    assert cache.stats == {"connections": 1, "topology_refreshes": 1}


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
