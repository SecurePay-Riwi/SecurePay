"""Builder of fact_difference, fact_reconciliation_match and dim_partner
(Yulianis, HU-52).

Reads raw/reconciliation/fecha=<day>/differences.jsonl and matched.jsonl
(written by export.py) and writes fact_difference (partition run_day,
age_days and age_range counted to `day` with AGE_RANGES of
shared/reconciliation.py), fact_reconciliation_match (partition run_day)
and dim_partner (from Partner, partner_for() and PARTNER_UTC_OFFSET).
"""

from datetime import date

from services.analytics import spark as sp
from shared.analytics import RAW_RECONCILIATION
from shared.reconciliation import (
    AGE_RANGES,
    PARTNER_UTC_OFFSET,
    Partner,
    partner_for,
)

TABLES = ("fact_difference", "fact_reconciliation_match", "dim_partner")

DIFFERENCE_SCHEMA = (
    "id string, run_day string, partner string, type string, status string, "
    "reference string, currency string, pagoseguro_amount string, "
    "partner_amount string, amount_difference string, detected_at string, "
    "resolved_at string"
)
MATCH_SCHEMA = "run_day string, partner string, matched int"
# Every value partner_for() is asked about. A partner's lists are what it
# answers for them, so dim_partner cannot disagree with the reconciliation.
TX_TYPES = ("P2P", "QR", "RETIRO", "RECARGA")
CHANNELS = ("APP", "WEB", "CORRESPONSAL", "CAJERO")


def _age_range(age):
    """AGE_RANGES as a column: the name of the range `age` falls in."""
    from pyspark.sql import functions as F

    result = F.lit(None).cast("string")
    for name, low, high in reversed(AGE_RANGES):
        inside = age >= low if high is None else age.between(low, high)
        result = F.when(inside, name).otherwise(result)
    return result


def fact_difference(spark, day: date, raw: str):
    from pyspark.sql import functions as F

    paths = [
        path
        for path in sp.jsonl_files(raw, RAW_RECONCILIATION, [day])
        if path.rsplit("/", 1)[-1] == "differences.jsonl"
    ]
    rows = (
        sp.lines(spark, paths)
        .select(F.from_json("value", DIFFERENCE_SCHEMA).alias("row"))
        .select("row.*")
        .withColumn("run_day", F.col("run_day").cast("date"))
        .where(F.col("run_day") <= F.lit(day.isoformat()).cast("date"))
        .withColumn(
            "age_days", F.datediff(F.lit(day.isoformat()).cast("date"), "run_day")
        )
    )
    return rows.select(
        F.col("id").alias("difference_id"),
        "run_day",
        "partner",
        "type",
        "status",
        "reference",
        "currency",
        "pagoseguro_amount",
        "partner_amount",
        "amount_difference",
        "age_days",
        _age_range(F.col("age_days")).alias("age_range"),
        F.col("detected_at").cast("timestamp").alias("detected_at"),
        F.col("resolved_at").cast("timestamp").alias("resolved_at"),
    )


def fact_reconciliation_match(spark, day: date, raw: str):
    """What matched per run day and partner (contract v1.1), from the
    export's matched.jsonl."""
    from pyspark.sql import functions as F

    paths = [
        path
        for path in sp.jsonl_files(raw, RAW_RECONCILIATION, [day])
        if path.rsplit("/", 1)[-1] == "matched.jsonl"
    ]
    return (
        sp.lines(spark, paths)
        .select(F.from_json("value", MATCH_SCHEMA).alias("row"))
        .select("row.*")
        .withColumn("run_day", F.col("run_day").cast("date"))
        .where(F.col("run_day") <= F.lit(day.isoformat()).cast("date"))
        .select("run_day", "partner", "matched")
    )


def partner_rows() -> list[tuple]:
    """(partner, tx_types, channels, utc_offset) of every partner."""
    rows = []
    for partner in Partner:
        pairs = [
            (tx_type, channel)
            for tx_type in TX_TYPES
            for channel in CHANNELS
            if partner_for(tx_type, channel) == partner
        ]
        rows.append(
            (
                partner.value,
                sorted({tx_type for tx_type, _ in pairs}),
                sorted({channel for _, channel in pairs}),
                PARTNER_UTC_OFFSET[partner.value],
            )
        )
    return rows


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write fact_difference and fact_reconciliation_match (one partition
    per run_day) and dim_partner for the export of `day`. Returns the rows
    written per table."""
    written = {}
    for table, df in (
        ("fact_difference", fact_difference(spark, day, raw)),
        ("fact_reconciliation_match", fact_reconciliation_match(spark, day, raw)),
    ):
        df = df.cache()
        try:
            days = sorted(
                r["run_day"] for r in df.select("run_day").distinct().collect()
            )
            written[table] = sum(
                sp.write(spark, df.where(df["run_day"] == d), table, output, d)
                for d in days
            )
        finally:
            df.unpersist()
    partners = spark.createDataFrame(
        partner_rows(),
        "partner string, tx_types array<string>, channels array<string>, "
        "utc_offset int",
    )
    written["dim_partner"] = sp.write(spark, partners, "dim_partner", output)
    return written
