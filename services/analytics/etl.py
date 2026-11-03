"""The analytics ETL: raw -> curated -> analytics (Habith, step 0).

    run_day(spark, day, raw, output)   every builder of BUILDERS for `day`
    main(argv)                         --day --raw --output (AWS Glue entry,
                                       infra/spark/analytics_job.py)

BUILDERS is the meeting point of the builders: one line each, in order
(the decisions first: the others read curated/decisiones). Each builder
is build(spark, day, raw, output) -> {table: rows written} and replaces
the partitions it writes, so a day can run again.
"""

import argparse
import json
import logging
from datetime import date

from services.analytics import (
    build_cases,
    build_decisions,
    build_devices,
    build_metrics,
    build_reconciliation,
)
from services.analytics import spark as sp

log = logging.getLogger(__name__)

BUILDERS = (
    build_decisions.build,  # Habith: curated, fact_decision, fact_rule_hit, ...
    build_cases.build,  # Yulianis (HU-51): fact_case
    build_reconciliation.build,  # Yulianis (HU-52): fact_difference, dim_partner
    build_devices.build,  # Yulianis (HU-47): dim_device
    build_metrics.build,  # Habith (HU-44 to HU-46): rule_metrics, pattern_coverage
)


def run_day(spark, day: date, raw: str, output: str) -> dict:
    """Every builder for `day`. Returns {"day", "tables": {table: rows}}."""
    tables = {}
    for builder in BUILDERS:
        tables.update(builder(spark, day, raw, output))
    log.info("Analytics %s: %s", day, tables)
    return {"day": day.isoformat(), "tables": tables}


def main(argv=None) -> None:  # spark-submit / AWS Glue entry point
    """--day --raw --output: raw is the root of raw/ (s3://<datalake> in
    AWS), output the root of curated/ and analytics/ (the same bucket)."""
    parser = argparse.ArgumentParser(description="Build a day of the analytics model.")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_day(sp.session(), args.day, args.raw, args.output)))


if __name__ == "__main__":
    main()
