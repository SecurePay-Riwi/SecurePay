"""Export of PostgreSQL to the raw layer (Yulianis, HU-51 and HU-52,
contract C6). Step 0 leaves the signatures only.

In AWS, handler() is the Lambda securepay-<env>-analytics-export, a step
of the nightly state machine after the reconciliation's store.
"""

from datetime import date, datetime


def export_day(session, day: date, root: str, now: datetime) -> dict:
    """Writes the CURRENT state of the cases created in the last
    ANALYTICS_EXPORT_DAYS days up to `day` to
    <root>/raw/cases/fecha=<day>/cases.jsonl and case_events.jsonl, and the
    reconciliation differences and runs of the same window to
    <root>/raw/reconciliation/fecha=<day>/differences.jsonl and runs.jsonl.
    One line per row, decimal strings, UTC ISO times. Replaces the day's
    files (idempotent). Returns {"day", "cases", "case_events",
    "differences", "runs"}."""
    raise NotImplementedError("HU-51 and HU-52 (Yulianis)")


def handler(event, context=None) -> dict:  # Lambda securepay-<env>-analytics-export
    """event {"day": "YYYY-MM-DD"} (absent: yesterday in Bogota) -> export_day."""
    raise NotImplementedError("HU-51 and HU-52 (Yulianis)")
