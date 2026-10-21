"""Velocity rule: more than LIMIT outgoing transfers within WINDOW_MIN
minutes from the same account.

Counts over the account's outgoing history (history.py), which is
ordered by event time: an event that arrives late is counted in its
real place.
"""

import os
from bisect import bisect_left, bisect_right

WINDOW_MIN = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
LIMIT = int(os.getenv("VELOCITY_LIMIT", "5"))

if WINDOW_MIN <= 0 or LIMIT <= 0:
    raise ValueError("Velocity parameters must be positive.")

WINDOW_MS = WINDOW_MIN * 60 * 1000

# Only transfers between accounts count: a QR payment goes to a merchant
# and a withdrawal goes out as cash (logbook 3.7).
TYPES = {"P2P"}


def max_in_window(times: list[int], t: int, window: int = WINDOW_MS) -> int:
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


def count(outgoing, t: int) -> int:
    """Transfers in the busiest window among those that contain t.

    `outgoing` is the account's history, already sorted (it includes the
    transfer being evaluated). If it arrived late, the later ones already
    processed count too, because in real time they come after it.
    """
    times = [o.t for o in outgoing if o.type in TYPES]
    return max_in_window(times, t)
