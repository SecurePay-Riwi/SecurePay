"""Publishes the catalog to Valkey for the decision engine (contract C4).

Both keys share the {rules} hash tag, so one script writes them in the
same slot. A write only replaces an older version: two writers that
commit in one order and publish in the other cannot leave the engine on
the older catalog. `force` skips that check; the API uses it at startup
and in POST /rules/publish, where PostgreSQL is the truth.
"""

from shared.cache import get_cache
from shared.rule_catalog import CATALOG_KEY, VERSION_KEY, CatalogSnapshot

_PUBLISH = """
local current = redis.call('GET', KEYS[2])
if ARGV[3] == '0' and current and tonumber(current) >= tonumber(ARGV[2]) then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""

_script = None


def publish(snapshot: CatalogSnapshot, force: bool = False) -> bool:
    """Write the snapshot. False when Valkey already had a newer one."""
    global _script
    if _script is None:
        _script = get_cache().register_script(_PUBLISH)

    written = _script(
        keys=[CATALOG_KEY, VERSION_KEY],
        args=[snapshot.model_dump_json(), str(snapshot.version), 1 if force else 0],
    )
    return bool(written)
