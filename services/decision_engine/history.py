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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import valkey

from shared.cache import get_cache

OUT_HOURS = int(os.getenv("HISTORY_OUT_HOURS", "24"))
# The rules read at most the newest OUT_LIMIT outgoing movements. An
# account with more in 24 h is already held by velocity; without a limit
# one busy account makes every decision on it read and parse its whole
# day (load test of 2026-11-05: p50 120 ms and 27 % default decisions).
OUT_LIMIT = int(os.getenv("HISTORY_OUT_LIMIT", "100"))
IN_MINUTES = int(os.getenv("HISTORY_IN_MINUTES", "60"))
DEVICE_DAYS = int(os.getenv("HISTORY_DEVICE_DAYS", "30"))

if OUT_HOURS <= 0 or IN_MINUTES <= 0 or DEVICE_DAYS <= 0 or OUT_LIMIT <= 0:
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
#        return the history (1) or not (0), first index to return
#        (0 = all of them, -N = the newest N)
_RECORD = """
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
local last = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
local cutoff = tonumber(last[2]) - tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('(%.0f', cutoff))
redis.call('EXPIRE', KEYS[1], ARGV[4])
if ARGV[5] == '1' then
  return redis.call('ZRANGE', KEYS[1], ARGV[6], -1, 'WITHSCORES')
end
return {}
"""


def _args(member, t_ms, retention_ms, return_history, limit) -> list:
    return [
        member,
        t_ms,
        retention_ms,
        retention_ms // 1000,
        1 if return_history else 0,
        -limit,
    ]


class ValkeyHistory:
    """The engine's backend: every history key in Valkey."""

    def __init__(self):
        self._script = None

    def _registered(self):
        if self._script is None:
            self._script = get_cache().register_script(_RECORD)
        return self._script

    def record(self, key, member, t_ms, retention_ms, return_history, limit=0) -> list:
        """_RECORD in one call. Valkey's reply: member, score, member..."""
        return self._registered()(
            keys=[key], args=_args(member, t_ms, retention_ms, return_history, limit)
        )

    def queue(self, pipe, record: "Record") -> None:
        """Queue _RECORD on a pipeline by its SHA (EVALSHA), so several
        records share one round trip. valkey-py's cluster pipeline blocks
        its evalsha() method and cannot load scripts, but sends the
        command itself to the key's node; when Valkey does not know the
        script yet the reply is NoScriptError and finish() records that
        one again with record(), which loads it."""
        pipe.execute_command(
            "EVALSHA",
            self._registered().sha,
            1,
            record.key,
            *_args(
                record.member,
                record.t_ms,
                record.retention_ms,
                record.return_history,
                record.limit,
            ),
        )

    def finish(self, record: "Record", reply) -> list:
        """The reply of a queued record: the history, or the error Valkey
        returned in its place, raised (NoScriptError is recorded again)."""
        if isinstance(reply, valkey.exceptions.NoScriptError):
            return self.record(
                record.key,
                record.member,
                record.t_ms,
                record.retention_ms,
                record.return_history,
                record.limit,
            )
        if isinstance(reply, Exception):
            raise reply
        return reply

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

    def record(self, key, member, t_ms, retention_ms, return_history, limit=0) -> list:
        members = self._sets.setdefault(key, {})
        members[member] = t_ms
        cutoff = max(members.values()) - retention_ms
        for m in [m for m, t in members.items() if t < cutoff]:
            del members[m]
        if not return_history:
            return []
        kept = self._sorted(key)[-limit:] if limit else self._sorted(key)
        return [item for m, t in kept for item in (m, t)]

    def read(self, key) -> list[tuple[str, float]]:
        return self._sorted(key)

    def _sorted(self, key) -> list[tuple[str, int]]:
        members = self._sets.get(key, {})
        return sorted(members.items(), key=lambda item: (item[1], item[0]))


_valkey = ValkeyHistory()
_backend: ContextVar[ValkeyHistory | InMemoryHistory | None] = ContextVar(
    "history_backend", default=None
)


def uses_valkey() -> bool:
    """True unless use_backend() put another backend in this context."""
    return backend() is _valkey


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
class Record:
    """One member to add to a history key, and how to read the reply:
    `parse` turns Valkey's reply (member, score, ...) into what the
    record_*() function of that key returns."""

    key: str
    member: str
    t_ms: int
    retention_ms: int
    return_history: bool
    limit: int = 0
    parse: Callable[[list], object] = lambda _raw: None


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


def record(key, member, date, retention_ms, return_history, limit=0):
    """Add one member to a sorted set of the history and trim what is
    older than the retention, counted from the newest event. Returns the
    retained history when asked, only its newest `limit` members when
    `limit` is set. Every history key is written through here, in
    backend()."""
    return backend().record(
        key, member, to_ms(date), retention_ms, return_history, limit
    )


def read(key) -> list[tuple[str, float]]:
    """Every member of a history key with its score, oldest first. Every
    history key is read through here, in backend()."""
    return backend().read(key)


def _pairs(raw):
    """Valkey's reply alternates member and score."""
    return zip(raw[0::2], raw[1::2], strict=True)


def run(records: list[Record]) -> list:
    """Write every record, in order, and return what each one's parse
    makes of its reply. In Valkey they share one round trip (a pipeline,
    not a transaction: each script is still atomic on its own key)."""
    if not uses_valkey():
        return [
            r.parse(
                backend().record(
                    r.key, r.member, r.t_ms, r.retention_ms, r.return_history, r.limit
                )
            )
            for r in records
        ]
    pipe = get_cache().pipeline(transaction=False)
    queue(pipe, records)
    return finish(records, pipe.execute(raise_on_error=False))


def queue(pipe, records: list[Record]) -> None:
    """Queue the records on a Valkey pipeline that may carry other
    commands too (the engine adds the restricted list's); finish() reads
    their replies, the first len(records) of the pipeline."""
    for r in records:
        _valkey.queue(pipe, r)


def finish(records: list[Record], replies: list) -> list:
    """What run() returns, from the replies of queue()'s commands. Run
    the pipeline with raise_on_error=False: a record Valkey did not have
    the script for yet is recorded again here."""
    return [
        r.parse(_valkey.finish(r, reply))
        for r, reply in zip(records, replies, strict=True)
    ]


def _outgoing(raw) -> list[Outgoing]:
    result = []
    for m, t in _pairs(raw):
        id_, type_, amount_ = m.split("|")
        result.append(Outgoing(id_, type_, amount_, int(float(t))))
    return result


def _device_uses(raw) -> list[DeviceUse]:
    return [DeviceUse(m, int(float(t))) for m, t in _pairs(raw)]


def outgoing_record(account_id, tx_id, tx_type, amount, date) -> Record:
    """record_outgoing() as a Record, for run()."""
    return Record(
        outgoing_key(account_id),
        f"{tx_id}|{tx_type}|{amount}",
        to_ms(date),
        OUT_MS,
        return_history=True,
        limit=OUT_LIMIT,
        parse=_outgoing,
    )


def incoming_record(account_id, tx_id, sender_id, amount, date) -> Record:
    """record_incoming() as a Record, for run()."""
    return Record(
        incoming_key(account_id),
        f"{tx_id}|{sender_id}|{amount}",
        to_ms(date),
        IN_MS,
        return_history=False,
    )


def device_record(device_id, account_id, date) -> Record:
    """record_device() as a Record, for run()."""
    return Record(
        device_key(device_id),
        str(account_id),
        to_ms(date),
        DEVICE_MS,
        return_history=True,
        parse=_device_uses,
    )


def record_outgoing(account_id, tx_id, tx_type, amount, date) -> list[Outgoing]:
    """Store what leaves the account and return its newest OUT_LIMIT
    retained outgoing movements, in real chronological order."""
    r = outgoing_record(account_id, tx_id, tx_type, amount, date)
    return r.parse(record(r.key, r.member, date, r.retention_ms, True, r.limit))


def record_incoming(account_id, tx_id, sender_id, amount, date) -> None:
    """Store a transfer coming into the account. Returns nothing: rules
    are evaluated on the account that moves the money."""
    r = incoming_record(account_id, tx_id, sender_id, amount, date)
    record(r.key, r.member, date, r.retention_ms, return_history=False)


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
    r = device_record(device_id, account_id, date)
    return r.parse(record(r.key, r.member, date, r.retention_ms, True))
