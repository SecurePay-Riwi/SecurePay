"""Runs the analytics ETL locally, as the Glue job does in AWS, and
writes the views for Power BI.

    uv run python -m services.analytics --day 2026-10-05
    uv run python -m services.analytics --from 2026-10-01 --to 2026-10-07
    uv run python -m services.analytics --day 2026-10-05 \
        --raw services/analytics/tests/fixtures --output generated/analytics

raw/ is read from --raw (default ANALYTICS_DATA_DIR; it may be the
LocalStack bucket, s3://pagoseguro-datalake); curated/, analytics/ and
views/ go to --output (default ANALYTICS_DATA_DIR, a local folder).
"""

import argparse
import json
import logging
from datetime import date, timedelta

from services.analytics import ANALYTICS_DATA_DIR, etl, views
from services.analytics import spark as sp

log = logging.getLogger("services.analytics")


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
    parser = argparse.ArgumentParser(prog="python -m services.analytics")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--from", dest="from_", type=date.fromisoformat)
    parser.add_argument("--to", type=date.fromisoformat)
    parser.add_argument("--raw", default=ANALYTICS_DATA_DIR)
    parser.add_argument("--output", default=ANALYTICS_DATA_DIR)
    args = parser.parse_args(argv)

    spark = sp.session()
    for day in days(args):
        log.info("Built %s", json.dumps(etl.run_day(spark, day, args.raw, args.output)))
    log.info("Views: %s", json.dumps(views.write_views(spark, args.output)))


if __name__ == "__main__":
    main()
