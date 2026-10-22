"""Splitting rule (RN-05): `min_transactions` or more transactions from
the same account in `window_hours` hours, each below the daily limit,
that together go over it.

It counts everything that leaves the account (P2P, QR and withdrawal):
RN-05 says "transactions", and splitting a large amount works the same
whichever way the money goes out. It reads the outgoing history
(history.py), which already includes the transaction being decided.

A transaction at or above the limit is not part of a split: it is left
out of the count and the sum, and when it is the one being decided the
rule does not fire. Every later transaction of the split inside the
window fires too; the cases consumer (HU-25) groups them by account.

Amounts in the history are in the account's currency; each one is
converted to USD (fixed 2026-10-01 rates until HU-42). By default the
rule approves and opens a compliance case (score 40): RN-05 asks for a
case, not for holding the money.

Thresholds come from the catalog (SplittingParams).
"""

from decimal import Decimal

from services.decision_engine import currency, history
from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import RuleEntry, SplittingParams

TYPE = "splitting"

# The outgoing history must hold the longest window the catalog accepts
# (SplittingParams.window_hours, le=24).
if history.OUT_HOURS < 24:
    raise ValueError("HISTORY_OUT_HOURS must cover the longest splitting window (24 h).")


def below_limit(outgoing, tx_currency: str, t: int, window_hours: int,
                limit_usd: Decimal) -> dict[str, Decimal]:
    """Amount in USD of each outgoing transaction below the limit in the
    `window_hours` hours up to t, by id. Those recorded with a later
    time do not count."""
    window = window_hours * 3600 * 1000
    amounts = {}
    for o in outgoing:
        if t - window < o.t <= t:
            amount = currency.to_usd(Decimal(o.amount), tx_currency)
            if amount < limit_usd:
                amounts[o.id] = amount
    return amounts


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    p: SplittingParams = rule.typed_params()
    amounts = below_limit(ctx.outgoing, ctx.payload.currency, ctx.t_ms,
                          p.window_hours, p.daily_limit_usd)

    if str(ctx.payload.id) not in amounts:
        return None

    total = sum(amounts.values(), Decimal("0"))
    if len(amounts) >= p.min_transactions and total > p.daily_limit_usd:
        return hit(
            rule,
            f"Splitting: {len(amounts)} transactions in {p.window_hours} hours, "
            f"each below USD {p.daily_limit_usd}, adding up to USD {total}.",
        )
    return None
