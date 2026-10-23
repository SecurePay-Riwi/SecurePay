"""Account takeover rule (RN-07): a device change, a password change and
a transaction above `min_amount_usd` from the same account, all in less
than `window_minutes` minutes.

The changes come from POST /security-events, stored per account in
`sec:{account}` (security_events.py). The rule looks back from the
transaction: both changes must have happened in the `window_minutes`
before it. A change dated after the transaction does not count, even if
it arrived first.

Thresholds come from the catalog (AccountTakeoverParams).
"""

from services.decision_engine import security_events
from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import AccountTakeoverParams, RuleEntry

TYPE = "account_takeover"

# The security history must hold the longest window the catalog accepts
# (AccountTakeoverParams.window_minutes, le=60).
if security_events.SECURITY_MINUTES < 60:
    raise ValueError(
        "HISTORY_SECURITY_MINUTES must cover the longest takeover window (60)."
    )

# Money leaves the account: a recharge has no source account.
TYPES = {"P2P", "QR", "RETIRO"}

SIGNALS = {"DEVICE_CHANGE", "PASSWORD_CHANGE"}


def changes_in_window(events, t: int, window_minutes: int) -> set[str]:
    """Types of the security events in the `window_minutes` minutes up
    to t."""
    window = window_minutes * 60 * 1000
    return {e.type for e in events if t - window < e.t <= t}


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    if ctx.payload.type.value not in TYPES:
        return None

    p: AccountTakeoverParams = rule.typed_params()
    if ctx.amount_usd <= p.min_amount_usd:
        return None

    if SIGNALS <= changes_in_window(ctx.security_events, ctx.t_ms, p.window_minutes):
        return hit(
            rule,
            f"Account takeover: device and password changed in the last "
            f"{p.window_minutes} minutes and the transaction is "
            f"USD {ctx.amount_usd:.2f} (limit USD {p.min_amount_usd}).",
        )
    return None
