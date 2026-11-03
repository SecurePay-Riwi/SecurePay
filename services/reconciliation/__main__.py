"""Runs the nightly reconciliation locally, as Step Functions does in AWS.

    uv run python -m services.reconciliation --day 2026-10-05
    uv run python -m services.reconciliation --from 2026-10-01 --to 2026-10-07

For each day: ingest.run -> match.reconcile -> store.save. The run of the
day is RUNNING when it starts and FAILED, with the step and its error, if
a step fails; store.save closes it as DONE.
"""

import argparse
import json
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert

from services.reconciliation import (
    DECISIONS_SOURCE,
    RECON_DATA_DIR,
    STATEMENTS_SOURCE,
    ingest,
    match,
    match_dir,
    store,
)
from shared.db import SessionLocal
from shared.reconciliation import ReconciliationRun, RunStatus, create_schema

log = logging.getLogger("services.reconciliation")


def start_run(session, day: date, now: datetime) -> None:
    """The run of `day` is RUNNING again (a repeated day reuses its row)."""
    values = {
        "run_day": day,
        "status": RunStatus.RUNNING.value,
        "started_at": now,
        "finished_at": None,
        "error": None,
    }
    session.execute(
        insert(ReconciliationRun)
        .values(**values)
        .on_conflict_do_update(index_elements=[ReconciliationRun.run_day], set_=values)
    )
    session.commit()


def fail_run(session, day: date, step: str, error: Exception, now: datetime) -> None:
    session.rollback()
    session.query(ReconciliationRun).filter(ReconciliationRun.run_day == day).update(
        {
            "status": RunStatus.FAILED.value,
            "finished_at": now,
            "error": f"{step}: {type(error).__name__}: {error}",
        }
    )
    session.commit()


def run_day(
    session, day: date, source: str, decisions: str, target: str, spark=None
) -> dict:
    """The three steps for one day. Raises the step's error after marking
    the run FAILED. `spark` None: match starts a local session."""
    start_run(session, day, datetime.now(UTC))
    step = "ingest"
    try:
        read = ingest.run(day, source, target)
        step = "match"
        matched = match.reconcile(
            spark, day, read["records_path"], decisions, match_dir(target, day)
        )
        step = "store"
        rows = store.load_rows(matched["match_path"])
        return store.save(session, day, rows, {**read, **matched}, datetime.now(UTC))
    except Exception as exc:
        fail_run(session, day, step, exc, datetime.now(UTC))
        raise


def days(args) -> list[date]:
    if args.day:
        return [args.day]
    if not (args.from_ and args.to):
        raise SystemExit("Give --day, or --from and --to.")
    return [
        args.from_ + timedelta(days=i) for i in range((args.to - args.from_).days + 1)
    ]


def main(argv=None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="python -m services.reconciliation")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--from", dest="from_", type=date.fromisoformat)
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--source", default=STATEMENTS_SOURCE)
    parser.add_argument("--decisions", default=DECISIONS_SOURCE)
    parser.add_argument("--target", default=RECON_DATA_DIR)
    args = parser.parse_args(argv)

    spark = match.session()  # one local Spark session for every day
    with SessionLocal() as session:
        create_schema(session)
        for day in days(args):
            result = run_day(
                session, day, args.source, args.decisions, args.target, spark
            )
            log.info("Reconciled %s: %s", day, json.dumps(result))


if __name__ == "__main__":
    main()
