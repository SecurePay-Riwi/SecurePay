"""Per-account movement history in Valkey, ordered by event time. Read
by the rules that look at the account's past.

Sorted sets scored by transaction_date in milliseconds (an event that
arrives late lands in its real place, not at the end):

- `out:{account}`: what leaves the account (P2P, QR and withdrawal).
  Member `id|type|amount`. Used by velocity (10 min) and splitting
  (24 h).
- `in:{account}`: incoming P2P transfers. Member `id|sender|amount`.
  Used by the mule account rule (30 min): it needs the senders and the
  amount received to compare it with what is withdrawn.
- `dev:{device}`: the accounts that used a device. Member the account
  id, scored by the last time it was seen (ZADD moves it). Used by the
  shared device rule (30 days).

A top-up is not stored: it does not come from another account and no
money leaves.

Attempts are stored whatever the decision: the history is written
before deciding, in a single call (decided by Jorge on 2026-10-21).
Several people trying to send money to one account, or one account
trying many transfers, is already the signal.

Amounts are in the account's currency: every transaction of an account
uses its currency, so sums add up. Converting to USD comes when the
engine reads the exchange-rates table.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from shared.cache import get_cache

OUT_HOURS = int(os.getenv("HISTORY_OUT_HOURS", "24"))
IN_MINUTES = int(os.getenv("HISTORY_IN_MINUTES", "60"))
DEVICE_DAYS = int(os.getenv("HISTORY_DEVICE_DAYS", "30"))

if OUT_HOURS <= 0 or IN_MINUTES <= 0 or DEVICE_DAYS <= 0:
    raise ValueError("History retention must be positive.")

OUT_MS = OUT_HOURS * 3600 * 1000
IN_MS = IN_MINUTES * 60 * 1000
DEVICE_MS = DEVICE_DAYS * 24 * 3600 * 1000

# Everything in one script so two requests for the same account do not
# overlap: Valkey runs a whole script before serving another command.
# One key per script: in ElastiCache Serverless two keys may live on
# different nodes.
# KEYS[1] = out:{account} or in:{account}
# ARGV = member, event time (ms), retention (ms), retention (s),
#        return the history (1) or not (0)
_RECORD = """
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
local last = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
local cutoff = tonumber(last[2]) - tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('(%.0f', cutoff))
redis.call('EXPIRE', KEYS[1], ARGV[4])
if ARGV[5] == '1' then
  return redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
end
return {}
"""


class ValkeyHistory:
    """The engine's backend: every history key in Valkey."""

    def __init__(self):
        self._script = None

    def record(self, key, member, t_ms, retention_ms, return_history) -> list:
        """_RECORD in one call. Valkey's reply: member, score, member..."""
        if self._script is None:
            self._script = get_cache().register_script(_RECORD)
        return self._script(
            keys=[key],
            args=[
                member,
                t_ms,
                retention_ms,
                retention_ms // 1000,
                1 if return_history else 0,
            ],
        )

    def read(self, key) -> list[tuple[str, float]]:
        return get_cache().zrange(key, 0, -1, withscores=True)


class InMemoryHistory:
    """The same sorted sets in a dict, for replaying the engine over the
    history without Valkey (services/analytics/replay.py, contract C5).
    Same order (score, then member) and same trim as _RECORD: what is
    older than the retention, counted from the newest event, goes away.
    Not thread safe: one replay per instance."""

    def __init__(self):
        self._sets: dict[str, dict[str, int]] = {}

    def record(self, key, member, t_ms, retention_ms, return_history) -> list:
        members = self._sets.setdefault(key, {})
        members[member] = t_ms
        cutoff = max(members.values()) - retention_ms
        for m in [m for m, t in members.items() if t < cutoff]:
            del members[m]
        if not return_history:
            return []
        return [item for m, t in self._sorted(key) for item in (m, t)]

    def read(self, key) -> list[tuple[str, float]]:
        return self._sorted(key)

    def _sorted(self, key) -> list[tuple[str, int]]:
        members = self._sets.get(key, {})
        return sorted(members.items(), key=lambda item: (item[1], item[0]))


_valkey = ValkeyHistory()
_backend: ContextVar[ValkeyHistory | InMemoryHistory | None] = ContextVar(
    "history_backend", default=None
)


def backend() -> ValkeyHistory | InMemoryHistory:
    """Valkey, unless use_backend() put another one in this context."""
    return _backend.get() or _valkey


@contextmanager
def use_backend(new_backend) -> Iterator[None]:
    """Write and read the history in `new_backend` inside the block (the
    replay of services/analytics/ uses InMemoryHistory). Outside it, and
    in the engine, the backend is Valkey: nothing changes there."""
    token = _backend.set(new_backend)
    try:
        yield
    finally:
        _backend.reset(token)


@dataclass(frozen=True)
class Outgoing:
    id: str
    type: str
    amount: str
    t: int  # event time in ms


@dataclass(frozen=True)
class Incoming:
    id: str
    sender: str
    amount: str
    t: int


@dataclass(frozen=True)
class DeviceUse:
    account: str
    t: int  # last time the account used the device, in ms


def outgoing_key(account_id) -> str:
    return f"out:{account_id}"


def incoming_key(account_id) -> str:
    return f"in:{account_id}"


def device_key(device_id) -> str:
    return f"dev:{device_id}"


def to_ms(date) -> int:
    return int(date.timestamp() * 1000)


def record(key, member, date, retention_ms, return_history):
    """Add one member to a sorted set of the history and trim what is
    older than the retention, counted from the newest event. Returns the
    retained history when asked. Every history key is written through
    here, in backend()."""
    return backend().record(key, member, to_ms(date), retention_ms, return_history)


def read(key) -> list[tuple[str, float]]:
    """Every member of a history key with its score, oldest first. Every
    history key is read through here, in backend()."""
    return backend().read(key)


def _pairs(raw):
    """Valkey's reply alternates member and score."""
    return zip(raw[0::2], raw[1::2], strict=True)


def record_outgoing(account_id, tx_id, tx_type, amount, date) -> list[Outgoing]:
    """Store what leaves the account and return all its retained outgoing
    movements, in real chronological order."""
    member = f"{tx_id}|{tx_type}|{amount}"
    raw = record(outgoing_key(account_id), member, date, OUT_MS, return_history=True)

    result = []
    for m, t in _pairs(raw):
        id_, type_, amount_ = m.split("|")
        result.append(Outgoing(id_, type_, amount_, int(float(t))))
    return result


def record_incoming(account_id, tx_id, sender_id, amount, date) -> None:
    """Store a transfer coming into the account. Returns nothing: rules
    are evaluated on the account that moves the money."""
    record(
        incoming_key(account_id),
        f"{tx_id}|{sender_id}|{amount}",
        date,
        IN_MS,
        return_history=False,
    )


def incoming(account_id) -> list[Incoming]:
    """Transfers that came into the account, in chronological order."""
    raw = read(incoming_key(account_id))
    result = []
    for m, t in raw:
        id_, sender, amount = m.split("|")
        result.append(Incoming(id_, sender, amount, int(t)))
    return result


def record_device(device_id, account_id, date) -> list[DeviceUse]:
    """Store that the account used the device and return every account
    retained for it, with the last time each one was seen.

    An event older than the one already stored for that account moves
    its last time back; that only shortens how long it is kept.
    """
    raw = record(
        device_key(device_id), str(account_id), date, DEVICE_MS, return_history=True
    )
    return [DeviceUse(m, int(float(t))) for m, t in _pairs(raw)]
