"""Builder of dim_device (Yulianis, HU-47).

Reads curated/decisiones of the 30 days up to `day` (accounts per device
like RN-04: the main account, the source or, in a top-up, the
destination) and the cases of raw/cases, and writes dim_device with its
risk_level (rules in doc-website/docs/reference/analytics-model.mdx).
"""

from datetime import date, timedelta

from services.analytics import build_cases
from services.analytics import spark as sp
from services.analytics.build_decisions import WINDOW_DAYS

TABLES = ("dim_device",)

SHARED_ACCOUNTS = 3  # RN-04: a device is shared with more than 3 accounts


def dim_device(decisions, case_rows, day: date):
    """One row per device with a transaction in the window."""
    from pyspark.sql import functions as F

    with_case = case_rows.select(
        F.col("transaction_id").alias("_case_transaction")
    ).distinct()
    counted = (
        decisions.where(F.col("device_id").isNotNull())
        .join(
            with_case,
            decisions["transaction_id"] == with_case["_case_transaction"],
            "left",
        )
        .groupBy("device_id")
        .agg(
            F.count_distinct(
                F.coalesce("source_account_id", "destination_account_id")
            ).alias("accounts_30d"),
            F.count(F.lit(1)).alias("transactions_30d"),
            F.sum(
                F.when(F.col("decision").isin("HOLD", "REJECT"), 1).otherwise(0)
            ).alias("held_or_rejected_30d"),
            F.count("_case_transaction").alias("cases_30d"),
        )
    )
    shared = F.col("accounts_30d") > SHARED_ACCOUNTS
    flagged = (F.col("held_or_rejected_30d") > 0) | (F.col("cases_30d") > 0)
    return counted.withColumn("shared", shared).select(
        "device_id",
        "accounts_30d",
        "transactions_30d",
        "held_or_rejected_30d",
        "cases_30d",
        "shared",
        F.when(shared & flagged, "HIGH")
        .when(shared | flagged, "MEDIUM")
        .otherwise("LOW")
        .alias("risk_level"),
        F.lit(day.isoformat()).cast("date").alias("as_of"),
    )


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write the partition as_of=<day> of dim_device. Returns the rows
    written per table."""
    days = [day - timedelta(days=n) for n in range(WINDOW_DAYS)]
    decisions = sp.read(spark, "curated_decision", output, days)
    df = dim_device(decisions, build_cases.cases(spark, day, raw), day)
    return {"dim_device": sp.write(spark, df, "dim_device", output, day)}
