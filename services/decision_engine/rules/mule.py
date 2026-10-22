"""Mule account rule (RN-03): the account received transfers from at
least `min_senders` different accounts and withdraws `withdrawn_pct` %
or more of its balance, all in less than `window_minutes` minutes.

Evaluated on the withdrawal, which is when the money leaves the wallet.
It reads the transfers the account received from its incoming history
(history.py). The share withdrawn is measured against the balance the
core reports before the withdrawal, which already includes what came in
(the engine does not keep balances; team decision of 2026-10-13).

A transfer that arrives after the withdrawal was decided cannot change
that decision: the rule only sees what was already recorded. One that
arrives late but before the withdrawal counts in its real place.

Thresholds come from the catalog (MuleParams).
"""

from decimal import Decimal

from services.decision_engine import history
from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import MuleParams, RuleEntry

TYPE = "mule"

# The incoming history must hold the longest window the catalog accepts
# (MuleParams.window_minutes, le=60).
if history.IN_MINUTES < 60:
    raise ValueError("HISTORY_IN_MINUTES must cover the longest mule window (60).")

# Only a withdrawal: the rule says "withdraws" (RN-03), like the
# generator's mule pattern.
TYPES = {"RETIRO"}


def senders(incoming, t: int, window_minutes: int) -> int:
    """Different accounts that sent money in the `window_minutes` minutes
    up to t. Transfers recorded with a later time do not count."""
    window = window_minutes * 60 * 1000
    return len({i.sender for i in incoming if t - window < i.t <= t})


def withdraws_enough(amount: Decimal, balance_before: Decimal, pct: Decimal) -> bool:
    """The withdrawal takes `pct` % or more of the balance."""
    return amount * 100 >= pct * balance_before


def withdrawn_pct(amount: Decimal, balance_before: Decimal) -> Decimal:
    """For the decision reason only."""
    if balance_before <= 0:
        return Decimal("100")
    return (amount * 100 / balance_before).quantize(Decimal("0.1"))


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    if ctx.payload.type.value not in TYPES:
        return None

    p: MuleParams = rule.typed_params()
    count = senders(ctx.incoming, ctx.t_ms, p.window_minutes)
    amount = ctx.payload.amount
    balance = ctx.payload.source_balance_before

    if count >= p.min_senders and withdraws_enough(amount, balance, p.withdrawn_pct):
        return hit(
            rule,
            f"Mule account: received transfers from {count} accounts "
            f"and withdrew {withdrawn_pct(amount, balance)}% of the balance "
            f"in less than {p.window_minutes} minutes.",
        )
    return None
