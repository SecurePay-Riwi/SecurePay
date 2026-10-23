"""Security events per account (device and password changes) in Valkey.
Read by the account takeover rule: a device change, a password change
and a transaction above USD 200 within an hour.

One sorted set per account, `sec:{account}`, scored by event_date in
milliseconds, member `id|type|device_id`. Keeping the id in the member
makes a resend of the same event a no-op. Events older than
HISTORY_SECURITY_MINUTES (60 by default) before the newest one are
trimmed, the same way as the transaction history.
"""

import os
from dataclasses import dataclass

from services.decision_engine import history
from shared.cache import get_cache

SECURITY_MINUTES = int(os.getenv("HISTORY_SECURITY_MINUTES", "60"))

if SECURITY_MINUTES <= 0:
    raise ValueError("HISTORY_SECURITY_MINUTES must be positive.")

SECURITY_MS = SECURITY_MINUTES * 60 * 1000


@dataclass(frozen=True)
class SecurityEvent:
    id: str
    type: str  # DEVICE_CHANGE or PASSWORD_CHANGE
    device_id: str
    t: int  # event time in ms


def security_key(account_id) -> str:
    return f"sec:{account_id}"


def record(event) -> None:
    """Store one SecurityEventRequest in its account's set."""
    history.record(
        security_key(event.account_id),
        f"{event.id}|{event.type.value}|{event.device_id}",
        event.event_date,
        SECURITY_MS,
        return_history=False,
    )


def recent(account_id) -> list[SecurityEvent]:
    """Retained security events of the account, oldest first."""
    raw = get_cache().zrange(security_key(account_id), 0, -1, withscores=True)
    result = []
    for m, t in raw:
        id_, type_, device_id = m.split("|")
        result.append(SecurityEvent(id_, type_, device_id, int(t)))
    return result
