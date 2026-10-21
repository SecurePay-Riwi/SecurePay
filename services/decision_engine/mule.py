"""Mule account rule (RN-03): the account received transfers from at
least MIN_SENDERS different accounts and withdraws WITHDRAWN_PCT % or
more of its balance, all in less than WINDOW_MIN minutes.

Evaluated on the withdrawal, which is when the money leaves the wallet.
It reads the transfers the account received from its incoming history
(history.py). The share withdrawn is measured against the balance the
core reports before the withdrawal, which already includes what came in
(the engine does not keep balances; team decision of 2026-10-13).

A transfer that arrives after the withdrawal was decided cannot change
that decision: the rule only sees what was already recorded. One that
arrives late but before the withdrawal counts in its real place.
"""

import os
from decimal import Decimal

from services.decision_engine import history

WINDOW_MIN = int(os.getenv("MULE_WINDOW_MINUTES", "30"))
MIN_SENDERS = int(os.getenv("MULE_MIN_SENDERS", "3"))
WITHDRAWN_PCT = Decimal(os.getenv("MULE_WITHDRAWN_PCT", "80"))

if WINDOW_MIN <= 0 or MIN_SENDERS <= 0 or not 0 < WITHDRAWN_PCT <= 100:
    raise ValueError("Mule account parameters out of range.")

# The incoming history must still hold the whole window.
if history.IN_MINUTES < WINDOW_MIN:
    raise ValueError("HISTORY_IN_MINUTES must cover the mule window.")

WINDOW_MS = WINDOW_MIN * 60 * 1000

# Only a withdrawal: the rule says "withdraws" (RN-03), like the
# generator's mule pattern.
TYPES = {"RETIRO"}


def senders(incoming, t: int) -> int:
    """Different accounts that sent money in the WINDOW_MIN minutes up
    to t. Transfers recorded with a later time do not count."""
    return len({i.sender for i in incoming if t - WINDOW_MS < i.t <= t})


def withdraws_enough(amount: Decimal, balance_before: Decimal) -> bool:
    """The withdrawal takes WITHDRAWN_PCT % or more of the balance."""
    return amount * 100 >= WITHDRAWN_PCT * balance_before


def withdrawn_pct(amount: Decimal, balance_before: Decimal) -> Decimal:
    """For the decision reason only."""
    if balance_before <= 0:
        return Decimal("100")
    return (amount * 100 / balance_before).quantize(Decimal("0.1"))
