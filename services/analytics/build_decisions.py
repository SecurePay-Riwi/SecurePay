"""Builder of the decisions' tables (Habith, sprint 6 step 0).

    curated/decisiones/fecha=<day>/   the transaction.decided events of the
                                      day, one row per transaction_id
    fact_decision, fact_rule_hit, fact_label (daily), dim_merchant (30 days
    up to the day), dim_date and dim_rule (whole tables)

The day of a transaction is its transaction_date in UTC. The analytics
consumer partitions raw/decisiones by the day the event arrived, so the
events of a day are read from fecha=<day-1..day+1> (a late or early
event still lands in its own day). raw does not deduplicate: the first
event of each transaction_id wins (earliest processed_at, then file and
line order).
"""

from datetime import date, timedelta

from services.analytics import spark as sp
from shared.analytics import RAW_DECISIONS, RAW_LABELS, LabelSource
from shared.rule_catalog import CatalogSnapshot, default_catalog

TABLES = (
    "curated_decision",
    "fact_decision",
    "fact_rule_hit",
    "fact_label",
    "dim_merchant",
    "dim_date",
    "dim_rule",
)

# The window of dim_merchant (and dim_device), like RN-04.
WINDOW_DAYS = 30

# What the analytics consumer writes: the event of shared/events.py.
# Money comes as decimal strings; rule_versions as an object.
EVENT_SCHEMA = (
    "event_type string, event_version int, "
    "transaction struct<id string, type string, channel string, "
    "source_account_id string, destination_account_id string, merchant_id string, "
    "amount string, currency string, source_balance_before string, "
    "source_balance_after string, destination_balance_before string, "
    "destination_balance_after string, device_id string, transaction_date string>, "
    "decision struct<transaction_id string, decision string, decision_reason string, "
    "rules_version string, rules_triggered array<string>, "
    "rule_versions map<string,int>, opens_case boolean, amount_usd string, "
    "usd_rate string, rate_date string, risk_score int, by_default boolean, "
    "processed_at string>"
)

LABEL_SCHEMA = (
    "id string, kind string, pattern string, is_fraud boolean, "
    "expected_rule string, duplicate boolean"
)

DEFAULT_RULE = "default_timeout"


def window(day: date) -> list[date]:
    """The days of raw/decisiones read for `day`."""
    return [day + timedelta(days=d) for d in (-1, 0, 1)]


def curated(spark, day: date, raw: str):
    """curated/decisiones of `day`: one row per transaction_id."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    events = (
        sp.lines(spark, sp.jsonl_files(raw, RAW_DECISIONS, window(day)))
        .select("_order", F.from_json("value", EVENT_SCHEMA).alias("e"))
        .where(F.col("e.transaction.id").isNotNull())
    )
    tx, d = F.col("e.transaction"), F.col("e.decision")
    at = F.to_timestamp(tx["transaction_date"])
    processed = F.to_timestamp(d["processed_at"])
    first = Window.partitionBy("transaction_id").orderBy(
        F.col("processed_at").asc_nulls_last(), F.col("_order")
    )
    money = "decimal(18,2)"
    return (
        events.select(
            "_order",
            tx["id"].alias("transaction_id"),
            F.to_date(at).alias("day"),
            at.alias("transaction_at"),
            tx["type"].alias("type"),
            tx["channel"].alias("channel"),
            tx["source_account_id"].alias("source_account_id"),
            tx["destination_account_id"].alias("destination_account_id"),
            tx["merchant_id"].alias("merchant_id"),
            tx["amount"].cast(money).alias("amount"),
            tx["currency"].alias("currency"),
            tx["source_balance_before"].cast(money).alias("source_balance_before"),
            tx["source_balance_after"].cast(money).alias("source_balance_after"),
            tx["destination_balance_before"]
            .cast(money)
            .alias("destination_balance_before"),
            tx["destination_balance_after"]
            .cast(money)
            .alias("destination_balance_after"),
            tx["device_id"].alias("device_id"),
            d["decision"].alias("decision"),
            d["decision_reason"].alias("decision_reason"),
            d["rules_version"].alias("rules_version"),
            F.coalesce(d["rules_triggered"], F.array().cast("array<string>")).alias(
                "rules_triggered"
            ),
            F.to_json(
                F.coalesce(d["rule_versions"], F.create_map().cast("map<string,int>"))
            ).alias("rule_versions"),
            F.coalesce(d["opens_case"], F.lit(False)).alias("opens_case"),
            F.coalesce(d["risk_score"], F.lit(0)).alias("risk_score"),
            F.coalesce(d["by_default"], F.lit(False)).alias("by_default"),
            d["amount_usd"].cast(money).alias("amount_usd"),
            d["usd_rate"].cast("decimal(18,8)").alias("usd_rate"),
            F.to_date(d["rate_date"]).alias("rate_date"),
            processed.alias("processed_at"),
        )
        .where(F.col("day") == F.lit(day.isoformat()).cast("date"))
        .withColumn("_n", F.row_number().over(first))
        .where(F.col("_n") == 1)
        .drop("_n", "_order")
    )


def labels(spark, raw: str):
    """The generator's labels of every raw/labels/fecha=*/ file, once per
    transaction (a label file covers a whole run, not one day; security
    events and repeated lines are left out)."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    rows = (
        sp.lines(spark, sp.jsonl_files(raw, RAW_LABELS))
        .select("_order", F.from_json("value", LABEL_SCHEMA).alias("l"))
        .select("_order", "l.*")
        .where(
            F.col("id").isNotNull()
            & (F.coalesce(F.col("kind"), F.lit("transaction")) == "transaction")
        )
    )
    first = Window.partitionBy("id").orderBy(
        F.coalesce(F.col("duplicate"), F.lit(False)), F.col("_order")
    )
    return (
        rows.withColumn("_n", F.row_number().over(first))
        .where(F.col("_n") == 1)
        .select(
            F.col("id").alias("transaction_id"),
            F.lit(LabelSource.GENERATOR.value).alias("source"),
            "pattern",
            F.coalesce(F.col("is_fraud"), F.lit(False)).alias("is_fraud"),
            "expected_rule",
        )
    )


def fact_label(cur, label_rows):
    """The labels of the day's transactions."""
    return label_rows.join(cur.select("transaction_id", "day"), "transaction_id")


def fact_decision(cur, day_labels):
    from pyspark.sql import functions as F

    return cur.join(
        day_labels.select("transaction_id", F.col("source").alias("label_source")),
        "transaction_id",
        "left",
    )


def dim_rule(spark, catalogs: list[CatalogSnapshot]):
    """One row per (rule, rule_version) of each catalog given."""
    rows = [
        (
            r.code,
            r.rule_version,
            r.type,
            r.action,
            r.opens_case,
            r.score,
            r.enabled,
            str(c.version),
        )
        for c in catalogs
        for r in c.rules
    ]
    return spark.createDataFrame(
        rows,
        "rule string, rule_version int, type string, action string, "
        "opens_case boolean, score int, enabled boolean, rules_version string",
    ).dropDuplicates(["rule", "rule_version", "rules_version"])


def fact_rule_hit(cur, rules):
    """One row per rule in rules_triggered. decision and score come from
    the catalog entry (rule, rule_version); for default_timeout, the
    transaction's decision. Unknown entries keep null."""
    from pyspark.sql import functions as F

    entries = rules.select(
        "rule", "rule_version", F.col("action").alias("_action"), "score"
    ).dropDuplicates(["rule", "rule_version"])
    hits = cur.select(
        "transaction_id",
        "day",
        F.col("decision").alias("_tx_decision"),
        F.explode("rules_triggered").alias("rule"),
        F.from_json("rule_versions", "map<string,int>").alias("_versions"),
    ).withColumn("rule_version", F.col("_versions")[F.col("rule")])
    return hits.join(entries, ["rule", "rule_version"], "left").select(
        "transaction_id",
        "day",
        "rule",
        "rule_version",
        F.when(F.col("rule") == DEFAULT_RULE, F.col("_tx_decision"))
        .otherwise(F.col("_action"))
        .alias("decision"),
        F.when(F.col("rule") == DEFAULT_RULE, F.lit(0))
        .otherwise(F.col("score"))
        .alias("score"),
    )


def dim_merchant(spark, output: str, day: date, label_rows):
    """Every merchant with a QR payment in the 30 days up to `day`."""
    from pyspark.sql import functions as F

    days = [day - timedelta(days=i) for i in range(WINDOW_DAYS)]
    recent = sp.read(spark, "curated_decision", output, days).where(
        F.col("merchant_id").isNotNull()
    )
    fraud = label_rows.where(F.col("is_fraud")).select(
        "transaction_id", F.lit(1).alias("_fraud")
    )
    return (
        recent.join(fraud, "transaction_id", "left")
        .groupBy("merchant_id")
        .agg(
            F.count(F.lit(1)).alias("transactions_30d"),
            F.sum(
                F.when(F.col("decision").isin("HOLD", "REJECT"), 1).otherwise(0)
            ).alias("held_or_rejected_30d"),
            F.sum(F.coalesce(F.col("_fraud"), F.lit(0))).alias("fraud_labeled_30d"),
        )
        .withColumn("as_of", F.lit(day.isoformat()).cast("date"))
    )


def dim_date(spark, output: str):
    """One row per day with curated decisions."""
    from pyspark.sql import functions as F

    days = sp.stored_days(output, "curated_decision")
    df = spark.createDataFrame([(d,) for d in days], "day date")
    return df.select(
        "day",
        F.year("day").alias("year"),
        F.month("day").alias("month"),
        F.dayofmonth("day").alias("day_of_month"),
        # Spark's dayofweek is 1 = Sunday; ISO is 1 = Monday.
        (((F.dayofweek("day") + 5) % 7) + 1).alias("weekday"),
        F.dayofweek("day").isin(1, 7).alias("is_weekend"),
    )


def build(
    spark,
    day: date,
    raw: str,
    output: str,
    catalogs: list[CatalogSnapshot] | None = None,
) -> dict:
    """Write curated/decisiones and the decisions' tables of `day`.
    `catalogs`: the catalog versions for dim_rule (the code defaults,
    version 0, when not given). Returns the rows written per table."""
    catalogs = catalogs or [default_catalog()]
    written = {}
    written["curated_decision"] = sp.write(
        spark, curated(spark, day, raw), "curated_decision", output, day
    )
    cur = sp.read(spark, "curated_decision", output, [day]).cache()
    label_rows = labels(spark, raw).cache()
    try:
        day_labels = fact_label(cur, label_rows)
        rules = dim_rule(spark, catalogs)
        written["fact_label"] = sp.write(spark, day_labels, "fact_label", output, day)
        written["fact_decision"] = sp.write(
            spark, fact_decision(cur, day_labels), "fact_decision", output, day
        )
        written["dim_rule"] = sp.write(spark, rules, "dim_rule", output)
        written["fact_rule_hit"] = sp.write(
            spark, fact_rule_hit(cur, rules), "fact_rule_hit", output, day
        )
        written["dim_merchant"] = sp.write(
            spark,
            dim_merchant(spark, output, day, label_rows),
            "dim_merchant",
            output,
            day,
        )
        written["dim_date"] = sp.write(
            spark, dim_date(spark, output), "dim_date", output
        )
    finally:
        cur.unpersist()
        label_rows.unpersist()
    return written
