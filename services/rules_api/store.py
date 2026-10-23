"""Valkey persistence for versioned rule catalogs."""
import json
from datetime import datetime, timezone
from typing import Any

from shared.cache import get_cache
from shared.rule_catalog import CATALOG_KEY, VERSION_KEY, CatalogSnapshot, default_catalog

HISTORY_KEY = "{rules}:history"
CHANGE_CHANNEL = "{rules}:changed"


def _parse(raw: str | bytes) -> CatalogSnapshot:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return CatalogSnapshot.model_validate(json.loads(raw))


def current_catalog(client: Any | None = None) -> CatalogSnapshot:
    cache = client or get_cache()
    raw = cache.get(CATALOG_KEY)
    if raw is None:
        snapshot = default_catalog()
        encoded = snapshot.model_dump_json()
        pipe = cache.pipeline(transaction=True)
        pipe.set(CATALOG_KEY, encoded)
        pipe.set(VERSION_KEY, str(snapshot.version))
        pipe.rpush(HISTORY_KEY, encoded)
        pipe.execute()
        return snapshot
    snapshot = _parse(raw)
    if cache.llen(HISTORY_KEY) == 0:
        cache.rpush(HISTORY_KEY, snapshot.model_dump_json())
    return snapshot


def publish_snapshot(snapshot: CatalogSnapshot, client: Any | None = None) -> None:
    cache = client or get_cache()
    encoded = snapshot.model_dump_json()
    pipe = cache.pipeline(transaction=True)
    pipe.set(CATALOG_KEY, encoded)
    pipe.set(VERSION_KEY, str(snapshot.version))
    pipe.rpush(HISTORY_KEY, encoded)
    pipe.publish(CHANGE_CHANNEL, str(snapshot.version))
    pipe.execute()


def catalog_versions(client: Any | None = None) -> list[CatalogSnapshot]:
    cache = client or get_cache()
    current = current_catalog(cache)
    snapshots = [_parse(raw) for raw in cache.lrange(HISTORY_KEY, 0, -1)]
    if not snapshots:
        return [current]
    if snapshots[-1].version != current.version:
        snapshots.append(current)
    return snapshots


def next_snapshot(current: CatalogSnapshot, rules: list, author: str) -> CatalogSnapshot:
    return CatalogSnapshot(version=current.version + 1, created_at=datetime.now(timezone.utc), author=author, rules=rules)
