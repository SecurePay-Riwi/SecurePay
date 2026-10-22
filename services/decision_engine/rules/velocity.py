"""Velocity rule (RN-02): more than `limit` outgoing transfers within
`window_minutes` minutes from the same account.

Counts over the account's outgoing history (history.py), which is
ordered by event time: an event that arrives late is counted in its
real place. Thresholds come from the catalog (VelocityParams).
"""

from bisect import bisect_left, bisect_right

from services.decision_engine import history
from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import RuleEntry, VelocityParams

TYPE = "velocity"

# The outgoing history must hold the longest window the catalog accepts
# (VelocityParams.window_minutes, le=1440).
if history.OUT_HOURS < 24:
    raise ValueError("HISTORY_OUT_HOURS must cover the longest velocity window (24 h).")

# Only transfers between accounts count: a QR payment goes to a merchant
# and a withdrawal goes out as cash (logbook 3.7).
TYPES = {"P2P"}


def max_in_window(times: list[int], t: int, window: int) -> int:
    """Largest number of transfers inside a `window` ms window that
    contains t. `times` is sorted and includes t.

    Trying the windows that start at each event between t - window and t
    is enough: any other window can slide to an event without losing one.
    """
    best = 0
    start = bisect_left(times, t - window)
    end = bisect_right(times, t)

    for begin in times[start:end]:
        inside = bisect_right(times, begin + window) - bisect_left(times, begin)
        best = max(best, inside)

    return best


def count(outgoing, t: int, window_minutes: int) -> int:
    """Transfers in the busiest window among those that contain t.

    `outgoing` is the account's history, already sorted (it includes the
    transfer being evaluated). If it arrived late, the later ones already
    processed count too, because in real time they come after it.
    """
    times = [o.t for o in outgoing if o.type in TYPES]
    return max_in_window(times, t, window_minutes * 60 * 1000)


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    if ctx.payload.type.value not in TYPES:
        return None

    p: VelocityParams = rule.typed_params()
    transfers = count(ctx.outgoing, ctx.t_ms, p.window_minutes)

    if transfers > p.limit:
        return hit(
            rule,
            f"Velocity: {transfers} outgoing transfers in "
            f"{p.window_minutes} minutes from the same account.",
        )
    return None
