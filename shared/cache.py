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


def build_client(url: str = VALKEY_URL, cluster: bool = VALKEY_CLUSTER):
    """A new client for the URL. decode_responses=True returns str instead
    of bytes. Each client keeps its own connection pool."""
    if cluster:
        return valkey.ValkeyCluster.from_url(url, decode_responses=True)
    return valkey.Valkey.from_url(url, decode_responses=True)


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
