"""Shared device rule (RN-04): the device of the transaction was used by
more than `max_accounts` accounts in the last `window_days` days.

It does not hold by itself: by default it only raises the risk score
(action APPROVE, score 30 in the catalog). RN-04 says the score rises
"for all" the accounts: every account that uses the device reads the
same set in dev:{device}, so each one of them gets the score on its
next transaction.

The engine records the main account (the source; in a top-up, the
destination) on every transaction, before deciding (history.py).
An account seen after this transaction (an event that arrived late)
still counts: it shares the device inside the window too.

Thresholds come from the catalog (SharedDeviceParams).
"""

from services.decision_engine import history
from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import RuleEntry, SharedDeviceParams

TYPE = "shared_device"

# The device history must hold the longest window the catalog accepts
# (SharedDeviceParams.window_days, le=30).
if history.DEVICE_DAYS < 30:
    raise ValueError("HISTORY_DEVICE_DAYS must cover the longest shared device window (30).")


def accounts(device_accounts, t: int, window_days: int) -> int:
    """Different accounts seen on the device in the `window_days` days
    up to t."""
    window = window_days * 24 * 3600 * 1000
    return len({d.account for d in device_accounts if d.t > t - window})


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    p: SharedDeviceParams = rule.typed_params()
    count = accounts(ctx.device_accounts, ctx.t_ms, p.window_days)

    if count > p.max_accounts:
        return hit(
            rule,
            f"Shared device: used by {count} accounts in the last "
            f"{p.window_days} days (limit {p.max_accounts}).",
        )
    return None
