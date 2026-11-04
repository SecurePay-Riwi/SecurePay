"""Data quality checks of the analytics model (HU-66, MAG-294): nulls,
formats and ranges of every table of shared/analytics.TABLES.

    uv run python -m services.analytics.quality --day 2026-10-05 --output generated/analytics

The checks come from the columns of TABLES, by name and type, so a new
table or column is checked without touching this file:

    not null    the partition column (day, run_day, as_of), the ids
                (transaction_id, case_id, difference_id), amount,
                amount_usd, rule, partner, and the key (first column) of
                every dim_* table
    not empty   every *_id column that has a value
    formats     currency in COP/USD/EUR/JPY; decision and final_decision
                in APPROVE/HOLD/REJECT
    ranges      amount and amount_usd > 0; risk_score and score 0 to 100;
                every ratio (decimal(9,4)) 0 to 1

check_table() runs them in one pass over a table (the partition of `day`
for a daily table, the whole table otherwise) and returns the failures.
CI runs them on the fixture day (test_quality.py); in AWS the analytics
Glue job runs check_day() after the builders and fails if any check does,
so the nightly state machine warns ops-alarms.
"""

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import date

from services.analytics import ANALYTICS_DATA_DIR
from services.analytics import spark as sp
from shared.analytics import TABLES, Table
from shared.config import MONEDA_DECIMALES

log = logging.getLogger(__name__)

CURRENCIES = tuple(sorted(MONEDA_DECIMALES))
DECISIONS = ("APPROVE", "HOLD", "REJECT")

REQUIRED = (
    "transaction_id",
    "case_id",
    "difference_id",
    "amount",
    "amount_usd",
    "rule",
    "partner",
)
POSITIVE = ("amount", "amount_usd")
SCORES = ("risk_score", "score")
DECISION_COLUMNS = ("decision", "final_decision")
RATIO = "decimal(9,4)"


@dataclass(frozen=True)
class Check:
    table: str
    column: str
    rule: str  # e.g. "not null", "in COP/EUR/JPY/USD", "between 0 and 100"

    @property
    def name(self) -> str:
        return f"{self.table}.{self.column} {self.rule}"


class QualityError(Exception):
    """Some check failed; the message lists every failure."""


def checks(table: Table) -> list[tuple[Check, object]]:
    """(check, condition of a BAD row) for every check of the table. The
    conditions are pyspark Columns, built here so nothing else imports
    pyspark."""
    from pyspark.sql import functions as F

    found = []

    def add(column, rule, bad):
        found.append((Check(table.name, column, rule), bad))

    required = set(REQUIRED) | ({table.partition} if table.partition else set())
    if table.name.startswith("dim_"):
        required.add(table.columns[0].name)
    for c in table.columns:
        col = F.col(c.name)
        if c.name in required:
            add(c.name, "not null", col.isNull())
        if c.name.endswith("_id") and c.type == "string":
            add(c.name, "not empty", col.isNotNull() & (F.trim(col) == ""))
        if c.name == "currency":
            add(c.name, f"in {'/'.join(CURRENCIES)}", ~col.isin(*CURRENCIES))
        if c.name in DECISION_COLUMNS:
            add(c.name, f"in {'/'.join(DECISIONS)}", ~col.isin(*DECISIONS))
        if c.name in POSITIVE:
            add(c.name, "> 0", col <= 0)
        if c.name in SCORES:
            add(c.name, "between 0 and 100", (col < 0) | (col > 100))
        if c.type == RATIO:
            add(c.name, "between 0 and 1", (col < 0) | (col > 1))
    return found


def failures_of(df, table: Table) -> dict[str, int]:
    """{check name: bad rows} of the checks that failed on `df`. A null
    value only fails "not null" (comparisons with null are not bad)."""
    from pyspark.sql import functions as F

    found = checks(table)
    if not found:
        return {}
    row = df.agg(
        *[
            F.sum(F.when(F.coalesce(bad, F.lit(False)), 1).otherwise(0)).alias(str(i))
            for i, (_, bad) in enumerate(found)
        ]
    ).first()
    return {
        check.name: row[str(i)]
        for i, (check, _) in enumerate(found)
        if row[str(i)]  # None when the table is empty
    }


def check_table(spark, table: str, root: str, day: date | None = None) -> dict:
    """The checks of one table: its partition of `day` when it is a daily
    table and `day` is given, all of it otherwise. {check: bad rows}."""
    t = TABLES[table]
    days = [day] if (day is not None and t.partition) else None
    return failures_of(sp.read(spark, table, root, days), t)


def check_day(spark, root: str, day: date) -> dict:
    """Every table of TABLES for `day`. Returns {"day", "tables": n,
    "failures": {check: bad rows}}; raises QualityError if any failed."""
    failures = {}
    for table in TABLES:
        failures.update(check_table(spark, table, root, day))
    result = {"day": day.isoformat(), "tables": len(TABLES), "failures": failures}
    if failures:
        raise QualityError(f"Data quality checks failed for {day}: {failures}")
    log.info("Data quality of %s: %s tables, every check passed", day, len(TABLES))
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Check a day of the analytics model.")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--output", default=ANALYTICS_DATA_DIR)
    args = parser.parse_args(argv)
    print(json.dumps(check_day(sp.session(), args.output, args.day)))


if __name__ == "__main__":
    main()
