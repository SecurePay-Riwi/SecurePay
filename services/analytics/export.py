"""Export of PostgreSQL to the raw layer (Yulianis, HU-51 and HU-52,
contract C6).

    uv run python -m services.analytics.export --day 2026-10-05

In AWS, handler() is the Lambda securepay-<env>-analytics-export, a step
of the nightly state machine after the reconciliation's store, and with
{"job": "kaggle_metrics"} the step after it (metrics.kaggle_metrics()).
"""

import argparse
import json
import logging
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from services.analytics import ANALYTICS_DATA_DIR, ANALYTICS_EXPORT_DAYS
from services.reconciliation import RECON_DATA_DIR, match_dir, storage, store
from shared.analytics import RAW_CASES, RAW_RECONCILIATION, layer_path
from shared.cases import Case, CaseEvent
from shared.db import SessionLocal
from shared.reconciliation import (
    MatchStatus,
    Partner,
    ReconciliationDifference,
    ReconciliationRun,
)

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


def matched_rows(run_days, source: str | None = None) -> list[dict]:
    """{"run_day", "partner", "matched"} for every partner of each run day
    whose match output still exists: the MATCHED rows of
    match_dir(RECON_DATA_DIR, run_day) (contract v1.1). A day without
    output gives no rows."""
    source = source or RECON_DATA_DIR
    rows = []
    for run_day in sorted(set(run_days)):
        output = store.load_rows(match_dir(source, run_day))
        if not output:
            continue
        counts = Counter(r.partner for r in output if r.status == MatchStatus.MATCHED)
        rows.extend(
            {
                "run_day": run_day.isoformat(),
                "partner": p.value,
                "matched": counts[p.value],
            }
            for p in Partner
        )
    return rows


def export_day(
    session, day: date, root: str, now: datetime, matches: str | None = None
) -> dict:
    """Writes the CURRENT state of the cases created in the last
    ANALYTICS_EXPORT_DAYS days up to `day` to
    <root>/raw/cases/fecha=<day>/cases.jsonl and case_events.jsonl, and the
    reconciliation differences and runs of the same window to
    <root>/raw/reconciliation/fecha=<day>/differences.jsonl and runs.jsonl,
    and matched.jsonl: {"run_day", "partner", "matched"} per run of the
    window and partner, the MATCHED rows of the run's match output
    (store.load_rows(match_dir(matches or RECON_DATA_DIR, run_day)); 0 rows
    when the output is gone).
    One line per row, decimal strings, UTC ISO times. Replaces the day's
    files (idempotent). Returns {"day", "cases", "case_events",
    "differences", "runs", "matched"}."""
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
    matched = matched_rows((run.run_day for run in runs), matches)
    storage.write_jsonl(storage.join(recon_dir, "matched.jsonl"), matched)

    result = {
        "day": day.isoformat(),
        "cases": len(cases),
        "case_events": len(events),
        "differences": len(differences),
        "runs": len(runs),
        "matched": len(matched),
    }
    log.info("Analytics export at %s: %s", now.isoformat(), result)
    return result


def handler(event, context=None) -> dict:  # Lambda securepay-<env>-analytics-export
    """event {"day": "YYYY-MM-DD"} (absent: yesterday in Bogota) -> export_day.
    event {"job": "kaggle_metrics"} -> the Kaggle replay's metrics to
    raw/metrics/kaggle/ (MAG-312), the state machine's next step.
    Only reads PostgreSQL: the tables belong to the services that write them."""
    event = event or {}
    if event.get("job") == "kaggle_metrics":
        # Imported here: the export does not need the engine's rules.
        from services.analytics.metrics import kaggle_metrics

        with SessionLocal() as session:
            done = kaggle_metrics(session, ANALYTICS_DATA_DIR)
        done.pop("result", None)
        return done
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
