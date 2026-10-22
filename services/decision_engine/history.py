"""Per-account movement history in Valkey, ordered by event time. Read
by the rules that look at the account's past.

Two sorted sets per account, scored by transaction_date in milliseconds
(an event that arrives late lands in its real place, not at the end):

- `out:{account}`: what leaves the account (P2P, QR and withdrawal).
  Member `id|type|amount`. Used by velocity (10 min) and, later,
  splitting (24 h).
- `in:{account}`: incoming P2P transfers. Member `id|sender|amount`.
  Used by the mule account rule (30 min): it needs the senders and the
  amount received to compare it with what is withdrawn.

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
from dataclasses import dataclass

from shared.cache import get_cache

OUT_HOURS = int(os.getenv("HISTORY_OUT_HOURS", "24"))
IN_MINUTES = int(os.getenv("HISTORY_IN_MINUTES", "60"))

if OUT_HOURS <= 0 or IN_MINUTES <= 0:
    raise ValueError("History retention must be positive.")

OUT_MS = OUT_HOURS * 3600 * 1000
IN_MS = IN_MINUTES * 60 * 1000

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

_script = None


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


def outgoing_key(account_id) -> str:
    return f"out:{account_id}"


def incoming_key(account_id) -> str:
    return f"in:{account_id}"


def to_ms(date) -> int:
    return int(date.timestamp() * 1000)


def record(key, member, date, retention_ms, return_history):
    """Add one member to a sorted set of the history and trim what is
    older than the retention, counted from the newest event. Returns the
    retained history when asked. Every history key is written through
    here."""
    global _script
    if _script is None:
        _script = get_cache().register_script(_RECORD)

    return _script(
        keys=[key],
        args=[member, to_ms(date), retention_ms, retention_ms // 1000,
              1 if return_history else 0],
    )


def _pairs(raw):
    """Valkey's reply alternates member and score."""
    return zip(raw[0::2], raw[1::2])


def record_outgoing(account_id, tx_id, tx_type, amount, date) -> list[Outgoing]:
    """Store what leaves the account and return all its retained outgoing
    movements, in real chronological order."""
    member = f"{tx_id}|{tx_type}|{amount}"
    raw = record(outgoing_key(account_id), member, date, OUT_MS,
                  return_history=True)

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
    raw = get_cache().zrange(incoming_key(account_id), 0, -1, withscores=True)
    result = []
    for m, t in raw:
        id_, sender, amount = m.split("|")
        result.append(Incoming(id_, sender, amount, int(t)))
    return result
