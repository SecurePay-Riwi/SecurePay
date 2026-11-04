"""Builder of fact_case (Yulianis, HU-51).

Reads raw/cases/fecha=<day>/cases.jsonl and case_events.jsonl (the
current state of the cases, written by export.py) and writes fact_case
with the columns of shared/analytics.py TABLES["fact_case"]. Each file
holds the cases of several days, and each case goes to the partition of
the day of its created_at, so a case that changed state replaces its old
row when its day is written again.
"""

from datetime import date

from services.analytics import spark as sp
from shared.analytics import RAW_CASES
from shared.cases import CASE_DUE_MINUTES, CaseEventType

TABLES = ("fact_case",)

CASE_SCHEMA = (
    "id string, transaction_id string, rules_triggered array<string>, "
    "risk_score int, amount_usd string, status string, assignee string, "
    "created_at string, due_at string, escalated_at string, resolved_at string, "
    "resolved_by string, outcome string, final_decision string"
)
EVENT_SCHEMA = "case_id string, type string, at string"


def _read(spark, day: date, raw: str, file_name: str, schema: str):
    """The rows of one file of raw/cases/fecha=<day>/."""
    from pyspark.sql import functions as F

    paths = [
        path
        for path in sp.jsonl_files(raw, RAW_CASES, [day])
        if path.rsplit("/", 1)[-1] == file_name
    ]
    return (
        sp.lines(spark, paths)
        .select(F.from_json("value", schema).alias("row"))
        .select("row.*")
    )


def cases(spark, day: date, raw: str):
    """The exported cases of `day`, as they are in raw (cases_30d of
    dim_device reads them too)."""
    return _read(spark, day, raw, "cases.jsonl", CASE_SCHEMA)


def fact_case(case_rows, event_rows):
    """One row per case, with its last assignment from the events."""
    from pyspark.sql import functions as F

    assigned = (
        event_rows.where(F.col("type") == CaseEventType.ASSIGNED.value)
        .groupBy("case_id")
        .agg(F.max(F.col("at").cast("timestamp")).alias("assigned_at"))
    )
    created = F.col("created_at").cast("timestamp")
    resolved = F.col("resolved_at").cast("timestamp")
    escalations = (
        event_rows.where(F.col("type") == CaseEventType.ESCALATED.value)
        .select(F.col("case_id").alias("_escalated_case"))
        .distinct()
    )
    minutes = F.floor(
        (F.unix_micros(resolved) - F.unix_micros(created)) / 60_000_000
    ).cast("int")
    return (
        case_rows.join(assigned, case_rows["id"] == assigned["case_id"], "left")
        .join(escalations, F.col("id") == F.col("_escalated_case"), "left")
        .withColumn("case_id", F.col("id"))
        .withColumn("minutes_to_resolve", minutes)
        .select(
            "case_id",
            "transaction_id",
            F.to_date(created).alias("day"),
            created.alias("created_at"),
            F.col("due_at").cast("timestamp").alias("due_at"),
            F.col("assignee").alias("assigned_to"),
            "assigned_at",
            resolved.alias("resolved_at"),
            "resolved_by",
            "status",
            "outcome",
            "final_decision",
            F.col("_escalated_case").isNotNull().alias("escalated"),
            F.col("escalated_at").cast("timestamp").alias("escalated_at"),
            "minutes_to_resolve",
            (F.col("minutes_to_resolve") <= CASE_DUE_MINUTES).alias("within_sla"),
            "rules_triggered",
            "risk_score",
            "amount_usd",
        )
    )


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write fact_case for the cases exported on `day`: one partition per
    day of created_at. Returns the rows written per table."""
    events = _read(spark, day, raw, "case_events.jsonl", EVENT_SCHEMA)
    df = fact_case(cases(spark, day, raw), events).cache()
    try:
        days = sorted(r["day"] for r in df.select("day").distinct().collect())
        written = sum(
            sp.write(spark, df.where(df["day"] == d), "fact_case", output, d)
            for d in days
        )
    finally:
        df.unpersist()
    return {"fact_case": written}
