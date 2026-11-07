import os
from threading import Lock

import valkey

import shared.config  # noqa: F401 (carga el .env con load_dotenv)

VALKEY_URL = os.getenv("VALKEY_URL", "redis://localhost:6379/0")

# ElastiCache Serverless only accepts clients that speak the cluster
# protocol, so AWS sets VALKEY_CLUSTER=true. Locally (one Valkey node) it
# stays false. Every key the services use works in both modes: each command
# touches one key, and the catalog keys share the {rules} hash tag.
VALKEY_CLUSTER = os.getenv("VALKEY_CLUSTER", "false").strip().lower() == "true"

_lock = Lock()
_client = None


# Explicit socket settings instead of the client's defaults (no timeouts,
# no keepalive): a connection that hangs fails in seconds instead of
# holding a worker, and keepalive keeps idle connections from being
# dropped silently between the engine and ElastiCache (HU-60, run 6).
SOCKET_SETTINGS = {
    "socket_connect_timeout": 2.0,
    "socket_timeout": 2.0,
    "socket_keepalive": True,
}

# How many connections and cluster topology refreshes the process has
# made, for the load test's late_decision line: a jump between two lines
# says the client reconnected (HU-60, run 6). Counted in cluster mode only.
stats = {"connections": 0, "topology_refreshes": 0}


def _count_connection(connection) -> None:
    stats["connections"] += 1


def _count_refreshes(client) -> None:
    initialize = client.nodes_manager.initialize

    def counted():
        stats["topology_refreshes"] += 1
        return initialize()

    client.nodes_manager.initialize = counted


def build_client(url: str = VALKEY_URL, cluster: bool = VALKEY_CLUSTER):
    """A new client for the URL. decode_responses=True returns str instead
    of bytes. Each client keeps its own connection pool."""
    if cluster:
        client = valkey.ValkeyCluster.from_url(
            url,
            decode_responses=True,
            valkey_connect_func=_count_connection,
            **SOCKET_SETTINGS,
        )
        _count_refreshes(client)
        return client
    return valkey.Valkey.from_url(url, decode_responses=True, **SOCKET_SETTINGS)


def get_cache():
    """The one client of the process, created on first use. A cluster
    client connects when it is built, so building it lazily keeps the
    service starting (and /health answering) while the cache is down; the
    request that needs it gets the connection error instead."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = build_client()
    return _client
