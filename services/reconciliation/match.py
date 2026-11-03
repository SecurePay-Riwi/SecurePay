"""Step 2: match the partners' records with the engine's decisions (HU-37).

Contract C2: reconcile() reads the records of a day and the decisions of
the window day-1..day+1, and writes one MatchRow per reference.

reconcile() runs in PySpark (HU-37): local[*] in the tests and Compose,
the job's session on AWS Glue 6.0 (infra/spark/match_job.py runs main()).
match_day() is the same match in plain Python: the reference the Spark
tests compare against. pyspark is imported inside the Spark functions,
so importing this module does not need it (the Docker image has none).

The rules (RN-10, D3, D4):
- PagoSeguro side: APPROVE decisions that are not P2P, once per
  transaction id (raw/decisiones may repeat a line), whose partner_day()
  is the day. Partners do not see transfers inside the wallet nor what
  was rejected or held.
- Same reference on both sides: DATE_OFF when the times are more than
  DATE_TOLERANCE_DAYS apart, else AMOUNT_OFF when the amounts differ by
  more than AMOUNT_TOLERANCE, else MATCHED. Both limits are included.
- A partner record whose reference is an APPROVE of the window but of
  another partner day still counts: its date decides.
- ONLY_PAGOSEGURO: ours, not in the file. ONLY_PARTNER: in the file, and
  not an APPROVE of the window.
"""

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from services.reconciliation import storage
from shared.reconciliation import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    PARTNER_UTC_OFFSET,
    MatchRow,
    MatchStatus,
    StatementRecord,
    partner_day,
    partner_for,
    record_from_json,
)

log = logging.getLogger(__name__)

# What a partner never sees.
INTERNAL_TYPES = ("P2P",)


@dataclass(frozen=True)
class Ours:
    """One of our transactions that goes through a partner."""

    reference: str
    partner: str
    partner_day: date
    currency: str
    amount: Decimal
    at: datetime


def window(day: date) -> list[date]:
    """The days of raw/decisiones read for `day`."""
    return [day + timedelta(days=d) for d in (-1, 0, 1)]


def pagoseguro_side(events: list[dict]) -> dict[str, Ours]:
    """Our approved transactions that a partner sees, by id (once each)."""
    ours: dict[str, Ours] = {}
    for event in events:
        tx, decision = event["transaction"], event["decision"]
        if decision.get("decision") != "APPROVE" or tx["type"] in INTERNAL_TYPES:
            continue
        partner = partner_for(tx["type"], tx["channel"])
        if partner is None or str(tx["id"]) in ours:
            continue
        at = datetime.fromisoformat(tx["transaction_date"])
        ours[str(tx["id"])] = Ours(
            reference=str(tx["id"]),
            partner=partner.value,
            partner_day=partner_day(partner, at),
            currency=tx["currency"],
            amount=Decimal(str(tx["amount"])),
            at=at,
        )
    return ours


def _status(ours: Ours, record: StatementRecord) -> MatchStatus:
    if abs(record.transaction_at - ours.at) > timedelta(days=DATE_TOLERANCE_DAYS):
        return MatchStatus.DATE_OFF
    if abs(record.amount - ours.amount) > AMOUNT_TOLERANCE:
        return MatchStatus.AMOUNT_OFF
    return MatchStatus.MATCHED


def match_day(
    day: date, records: list[StatementRecord], events: list[dict]
) -> list[MatchRow]:
    """The reference match: one MatchRow per reference, sorted by partner
    and reference. `events` are the transaction.decided events of the
    window (window(day)); `records` the partners' records of `day`."""
    in_window = pagoseguro_side(events)
    by_reference: dict[str, StatementRecord] = {}
    for record in records:
        # A reference twice in the files is one operation: the first counts.
        by_reference.setdefault(record.pagoseguro_reference, record)

    rows = []
    for reference, record in by_reference.items():
        ours = in_window.get(reference)
        rows.append(
            MatchRow(
                run_day=day,
                partner=record.partner,
                status=(
                    _status(ours, record) if ours else MatchStatus.ONLY_PARTNER
                ).value,
                reference=reference,
                partner_reference=record.partner_reference,
                currency=record.currency,
                pagoseguro_amount=ours.amount if ours else None,
                partner_amount=record.amount,
                pagoseguro_at=ours.at if ours else None,
                partner_at=record.transaction_at,
            )
        )
    for reference, ours in in_window.items():
        if ours.partner_day != day or reference in by_reference:
            continue
        rows.append(
            MatchRow(
                run_day=day,
                partner=ours.partner,
                status=MatchStatus.ONLY_PAGOSEGURO.value,
                reference=reference,
                partner_reference=None,
                currency=ours.currency,
                pagoseguro_amount=ours.amount,
                partner_amount=None,
                pagoseguro_at=ours.at,
                partner_at=None,
            )
        )
    return sorted(rows, key=lambda r: (r.partner, r.reference))


def read_records(records_path: str) -> list[StatementRecord]:
    return [record_from_json(d) for d in storage.read_jsonl(records_path)]


def read_decisions(decisions_path: str, day: date) -> list[dict]:
    """Every event of raw/decisiones/fecha=<d>/ for the days of the window."""
    events = []
    for d in window(day):
        for path in storage.list_files(
            storage.join(decisions_path, f"fecha={d.isoformat()}"), "*.jsonl"
        ):
            events += storage.read_jsonl(path)
    return events


# --- Spark (HU-37) -----------------------------------------------------------

APP_NAME = "securepay-reconciliation-match"
_ONE_DAY_SECONDS = DATE_TOLERANCE_DAYS * 24 * 3600

# The keys of a MatchRow, in to_json() order (the keys Spark writes).
MATCH_COLUMNS = (
    "run_day",
    "partner",
    "status",
    "reference",
    "partner_reference",
    "currency",
    "pagoseguro_amount",
    "partner_amount",
    "pagoseguro_at",
    "partner_at",
)


def session():
    """The Spark session of the match: the cluster's under spark-submit
    (AWS Glue), local[*] otherwise. Times are compared in UTC."""
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName(APP_NAME)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def _spark_reads(spark, path: str) -> bool:
    """Whether Spark reads and writes `path` itself: always a local folder,
    s3:// only on a cluster (Glue reads S3; local mode has no S3 driver,
    so with LocalStack the files go through storage.py)."""
    return not storage.is_s3(path) or not spark.sparkContext.master.startswith("local")


def _lines(spark, paths: list[str]):
    """A DataFrame with one `value` per JSON line of the files, in order."""
    from pyspark.sql import Row

    if not paths:
        return spark.createDataFrame([], "value string")
    if all(_spark_reads(spark, p) for p in paths):
        return spark.read.text(paths)
    rows = [
        Row(value=line) for p in paths for line in storage.read_text(p).splitlines()
    ]
    return spark.createDataFrame(rows, "value string")


def _utc_text(ts):
    """A timestamp as to_json() writes it: ISO 8601 in UTC, microseconds
    only when they are not zero (datetime.isoformat())."""
    from pyspark.sql import functions as F

    micros = F.date_format(ts, "SSSSSS")
    return F.when(ts.isNull(), F.lit(None)).otherwise(
        F.concat(
            F.date_format(ts, "yyyy-MM-dd'T'HH:mm:ss"),
            F.when(micros == "000000", F.lit("")).otherwise(
                F.concat(F.lit("."), micros)
            ),
            F.lit("+00:00"),
        )
    )


def partner_column(tx_type, channel):
    """partner_for() as a Spark column (null when no partner sees it);
    test_match checks that both agree."""
    from pyspark.sql import functions as F

    return (
        F.when((tx_type == "RECARGA") & channel.isin("APP", "WEB"), "banco_andino")
        .when(
            tx_type.isin("RECARGA", "RETIRO") & (channel == "CORRESPONSAL"),
            "red_corresponsales",
        )
        .when((tx_type == "RETIRO") & (channel == "CAJERO"), "cajeros_express")
        .when(tx_type == "QR", "qr_pagos")
    )


def _offset_hours(partner):
    from pyspark.sql import functions as F

    pairs = [
        item
        for name, hours in PARTNER_UTC_OFFSET.items()
        for item in (F.lit(name), F.lit(hours))
    ]
    return F.create_map(*pairs)[partner]


EVENT_SCHEMA = (
    "transaction struct<id string, type string, channel string, amount string, "
    "currency string, transaction_date string>, decision struct<decision string>"
)
RECORD_SCHEMA = (
    "partner string, pagoseguro_reference string, partner_reference string, "
    "currency string, amount string, transaction_at string"
)


def spark_pagoseguro_side(spark, decisions_path: str, day: date):
    """pagoseguro_side() in Spark: one row per approved transaction a
    partner sees, with its partner_day."""
    from pyspark.sql import functions as F

    paths = [
        f
        for d in window(day)
        for f in storage.list_files(
            storage.join(decisions_path, f"fecha={d.isoformat()}"), "*.jsonl"
        )
    ]
    events = (
        _lines(spark, paths)
        .select(F.from_json("value", EVENT_SCHEMA).alias("e"))
        .select("e.*")
    )
    tx = F.col("transaction")
    at = F.to_timestamp(tx["transaction_date"])
    ours = (
        events.where(
            (F.col("decision.decision") == "APPROVE")
            & ~tx["type"].isin(*INTERNAL_TYPES)
        )
        .select(
            tx["id"].alias("reference"),
            partner_column(tx["type"], tx["channel"]).alias("our_partner"),
            tx["currency"].alias("our_currency"),
            tx["amount"].alias("pagoseguro_amount"),
            at.alias("our_at"),
        )
        .where(F.col("our_partner").isNotNull())
        .dropDuplicates(["reference"])
    )
    local_time = F.col("our_at") + F.make_interval(
        hours=_offset_hours(F.col("our_partner"))
    )
    return ours.withColumn("our_day", F.to_date(local_time))


def spark_records(spark, records_path: str):
    """The partners' records of the day, the first line of a repeated
    reference only (like match_day)."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    records = (
        _lines(spark, [records_path])
        .withColumn("_order", F.monotonically_increasing_id())
        .select("_order", F.from_json("value", RECORD_SCHEMA).alias("r"))
        .select("_order", "r.*")
    )
    first = Window.partitionBy("pagoseguro_reference").orderBy("_order")
    return (
        records.withColumn("_n", F.row_number().over(first))
        .where(F.col("_n") == 1)
        .select(
            F.col("pagoseguro_reference").alias("reference"),
            "partner",
            "partner_reference",
            "currency",
            F.col("amount").alias("partner_amount"),
            F.to_timestamp("transaction_at").alias("partner_ts"),
        )
    )


def spark_match(spark, day: date, records_path: str, decisions_path: str):
    """match_day() in Spark: a DataFrame with the MATCH_COLUMNS (strings,
    as to_json() writes them), sorted by partner and reference."""
    from pyspark.sql import functions as F

    ours = spark_pagoseguro_side(spark, decisions_path, day)
    records = spark_records(spark, records_path)
    decimal = "decimal(38,10)"
    seconds_apart = F.abs(
        F.col("partner_ts").cast("double") - F.col("our_at").cast("double")
    )
    amount_apart = F.abs(
        F.col("partner_amount").cast(decimal) - F.col("pagoseguro_amount").cast(decimal)
    )
    status = (
        F.when(F.col("our_at").isNull(), MatchStatus.ONLY_PARTNER.value)
        .when(seconds_apart > _ONE_DAY_SECONDS, MatchStatus.DATE_OFF.value)
        .when(
            amount_apart > F.lit(str(AMOUNT_TOLERANCE)).cast(decimal),
            MatchStatus.AMOUNT_OFF.value,
        )
        .otherwise(MatchStatus.MATCHED.value)
    )
    in_file = records.join(ours, "reference", "left").select(
        "reference",
        "partner",
        status.alias("status"),
        "partner_reference",
        "currency",
        "pagoseguro_amount",
        "partner_amount",
        F.col("our_at"),
        F.col("partner_ts"),
    )
    only_ours = (
        ours.where(F.col("our_day") == F.lit(day.isoformat()).cast("date"))
        .join(records.select("reference"), "reference", "left_anti")
        .select(
            "reference",
            F.col("our_partner").alias("partner"),
            F.lit(MatchStatus.ONLY_PAGOSEGURO.value).alias("status"),
            F.lit(None).cast("string").alias("partner_reference"),
            F.col("our_currency").alias("currency"),
            "pagoseguro_amount",
            F.lit(None).cast("string").alias("partner_amount"),
            F.col("our_at"),
            F.lit(None).cast("timestamp").alias("partner_ts"),
        )
    )
    return (
        in_file.unionByName(only_ours)
        .select(
            F.lit(day.isoformat()).alias("run_day"),
            "partner",
            "status",
            "reference",
            "partner_reference",
            "currency",
            "pagoseguro_amount",
            "partner_amount",
            _utc_text(F.col("our_at")).alias("pagoseguro_at"),
            _utc_text(F.col("partner_ts")).alias("partner_at"),
        )
        .orderBy("partner", "reference")
    )


def write_rows(spark, rows, output_path: str) -> None:
    """The MatchRows as JSON lines, part-*.json under output_path (replaced
    if the day runs again). Nulls are written, as to_json() does."""
    if _spark_reads(spark, output_path):
        (
            rows.coalesce(1)
            .write.mode("overwrite")
            .option("ignoreNullFields", "false")
            .json(output_path)
        )
        return
    storage.write_jsonl(
        storage.join(output_path, "part-00000.json"),
        [r.asDict() for r in rows.collect()],
    )


def reconcile(
    spark, day: date, records_path: str, decisions_path: str, output_path: str
) -> dict:
    """PagoSeguro side: events of raw/decisiones fecha=day-1..day+1, decision
    APPROVE, type != P2P, deduplicated by transaction id, partner_for() and
    partner_day() == day. Full outer join with the records on reference.
    MATCHED when |amount diff| <= 0.01 and |date diff| <= 1 day; AMOUNT_OFF,
    DATE_OFF, ONLY_PAGOSEGURO, ONLY_PARTNER otherwise. A partner record whose
    reference is an APPROVE of the window but of another partner_day still
    counts (date check). Writes one MatchRow per reference as JSON lines under
    output_path (curated/conciliacion/fecha=<day>/). Returns {"day",
    "match_path", "matched", "unmatched"}.

    `spark` None: session() (local[*], or the cluster's under spark-submit)."""
    from pyspark.sql import functions as F

    spark = spark or session()
    rows = spark_match(spark, day, records_path, decisions_path).cache()
    try:
        write_rows(spark, rows, output_path)
        counts = (
            rows.groupBy()
            .agg(
                F.count(F.lit(1)).alias("total"),
                F.sum(
                    F.when(F.col("status") == MatchStatus.MATCHED.value, 1).otherwise(0)
                ).alias("matched"),
            )
            .first()
        )
    finally:
        rows.unpersist()
    matched = int(counts["matched"] or 0)
    return {
        "day": day.isoformat(),
        "match_path": output_path,
        "matched": matched,
        "unmatched": int(counts["total"]) - matched,
    }


def main(argv=None) -> None:  # spark-submit / AWS Glue entry point
    """--day --records --decisions --output"""
    parser = argparse.ArgumentParser(
        description="Match a day of partner records with the decisions."
    )
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--records", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(reconcile(None, args.day, args.records, args.decisions, args.output))
    )


if __name__ == "__main__":
    main()
