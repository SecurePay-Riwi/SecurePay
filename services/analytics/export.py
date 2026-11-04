"""Export of PostgreSQL to the raw layer (Yulianis, HU-51 and HU-52,
contract C6).

    uv run python -m services.analytics.export --day 2026-10-05

In AWS, handler() is the Lambda securepay-<env>-analytics-export, a step
of the nightly state machine after the reconciliation's store.
"""

import argparse
import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from services.analytics import ANALYTICS_DATA_DIR, ANALYTICS_EXPORT_DAYS
from services.reconciliation import storage
from shared.analytics import RAW_CASES, RAW_RECONCILIATION, layer_path
from shared.cases import Case, CaseEvent
from shared.db import SessionLocal
from shared.reconciliation import ReconciliationDifference, ReconciliationRun

log = logging.getLogger(__name__)

BOGOTA = ZoneInfo("America/Bogota")


def _plain(value):
    """A column's value as the raw layer keeps it: decimal strings and
    UTC ISO times."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _row(item) -> dict:
    """Every column of an ORM row, under its column name."""
    return {
        column.name: _plain(getattr(item, column.key))
        for column in item.__table__.columns
    }


def export_day(session, day: date, root: str, now: datetime) -> dict:
    """Writes the CURRENT state of the cases created in the last
    ANALYTICS_EXPORT_DAYS days up to `day` to
    <root>/raw/cases/fecha=<day>/cases.jsonl and case_events.jsonl, and the
    reconciliation differences and runs of the same window to
    <root>/raw/reconciliation/fecha=<day>/differences.jsonl and runs.jsonl.
    One line per row, decimal strings, UTC ISO times. Replaces the day's
    files (idempotent). Returns {"day", "cases", "case_events",
    "differences", "runs"}."""
    first = day - timedelta(days=ANALYTICS_EXPORT_DAYS - 1)
    start = datetime.combine(first, time.min, UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, UTC)

    in_window = Case.created_at >= start, Case.created_at < end
    cases = session.scalars(select(Case).where(*in_window).order_by(Case.id)).all()
    events = session.scalars(
        select(CaseEvent)
        .join(Case, Case.id == CaseEvent.case_id)
        .where(*in_window)
        .order_by(CaseEvent.id)
    ).all()
    differences = session.scalars(
        select(ReconciliationDifference)
        .where(ReconciliationDifference.run_day.between(first, day))
        .order_by(ReconciliationDifference.id)
    ).all()
    runs = session.scalars(
        select(ReconciliationRun)
        .where(ReconciliationRun.run_day.between(first, day))
        .order_by(ReconciliationRun.run_day)
    ).all()

    cases_dir = layer_path(root, RAW_CASES, day)
    recon_dir = layer_path(root, RAW_RECONCILIATION, day)
    for folder, name, rows in (
        (cases_dir, "cases.jsonl", cases),
        (cases_dir, "case_events.jsonl", events),
        (recon_dir, "differences.jsonl", differences),
        (recon_dir, "runs.jsonl", runs),
    ):
        storage.write_jsonl(storage.join(folder, name), [_row(r) for r in rows])

    result = {
        "day": day.isoformat(),
        "cases": len(cases),
        "case_events": len(events),
        "differences": len(differences),
        "runs": len(runs),
    }
    log.info("Analytics export at %s: %s", now.isoformat(), result)
    return result


def handler(event, context=None) -> dict:  # Lambda securepay-<env>-analytics-export
    """event {"day": "YYYY-MM-DD"} (absent: yesterday in Bogota) -> export_day.
    Only reads PostgreSQL: the tables belong to the services that write them."""
    event = event or {}
    day = (
        date.fromisoformat(event["day"])
        if event.get("day")
        else datetime.now(BOGOTA).date() - timedelta(days=1)
    )
    with SessionLocal() as session:
        return export_day(session, day, ANALYTICS_DATA_DIR, datetime.now(UTC))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Export a day to the raw layer.")
    parser.add_argument("--day", type=date.fromisoformat)
    args = parser.parse_args(argv)
    print(json.dumps(handler({"day": args.day.isoformat()} if args.day else {})))


if __name__ == "__main__":
    main()
