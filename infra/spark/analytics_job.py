"""Entry point of the analytics Spark job on AWS Glue 6.0 (HU-66).

Step Functions starts the Glue job with --day --raw --output after the
reconciliation's store and the PostgreSQL export (modules/reconciliation).
Glue adds arguments of its own (--JOB_NAME, --JOB_RUN_ID, ...), so only
ours go on. It builds the day with every builder of etl.BUILDERS, then
runs the data quality checks (services/analytics/quality.py): a failed
check fails the job, and the state machine warns ops-alarms. Our code
comes in --extra-py-files (the zip modules/reconciliation builds) and its
libraries in --additional-python-modules (modules/analytics).
"""

import argparse
import sys

OURS = ("--day", "--raw", "--output")


def job_args(argv: list[str]) -> list[str]:
    """Our three arguments out of everything Glue passes, in etl.main's form."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in OURS:
        parser.add_argument(name, required=True)
    known, _ = parser.parse_known_args(argv)
    return [part for name in OURS for part in (name, getattr(known, name[2:]))]


def run(argv: list[str]) -> dict:
    """The ETL of the day, then its quality checks (raises QualityError)."""
    import json
    from datetime import date

    from services.analytics import etl, quality
    from services.analytics import spark as sp

    args = dict(zip(OURS, job_args(argv)[1::2], strict=True))
    day = date.fromisoformat(args["--day"])
    spark = sp.session()
    built = etl.run_day(spark, day, args["--raw"], args["--output"])
    checked = quality.check_day(spark, args["--output"], day)
    result = {**built, "quality": checked}
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    print(f"Python {sys.version}", flush=True)
    run(sys.argv[1:])
