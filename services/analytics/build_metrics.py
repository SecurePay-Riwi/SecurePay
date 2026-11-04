"""Builder of rule_metrics and pattern_coverage (Habith, HU-44 to HU-46).

Both tables are rebuilt on every run, over every day in the lake:

- the engine's own decisions with a label (fact_decision joined with
  fact_label, today the generator's labels), measured in Spark with the
  definitions of metrics.py (analytics-model.mdx, views q2 and q3);
- the rows a replay left in raw/metrics/kaggle/ (python -m
  services.analytics.metrics --kaggle: PaySim and Sparkov replayed with
  the current catalog), added as they are.

A rule of the catalog that did not fire still has a row, with 0 hits,
when dim_rule knows that catalog version. Runs after build_decisions
(etl.BUILDERS): it reads fact_decision, fact_label, fact_rule_hit and
dim_rule.
"""

from datetime import date

from services.analytics import spark as sp
from services.analytics.metrics import DEFAULT_RULE, DETECTED, NO_PATTERN
from shared.analytics import RAW_METRICS

TABLES = ("rule_metrics", "pattern_coverage")

# What metrics.to_row() writes; ratios are decimal strings.
RAW_SCHEMAS = {
    "rule_metrics": (
        "rule string, label_source string, hits int, true_positives int, "
        "false_positives int, precision string, false_positive_rate string, "
        "rule_version int, rules_version string"
    ),
    "pattern_coverage": (
        "pattern string, label_source string, frauds int, detected int, "
        "missed int, detection_rate string, top_rule string, rules_version string, "
        "detected_amount_usd string, missed_amount_usd string"
    ),
}


def _ratio(numerator, denominator):
    """numerator / denominator with 4 decimals, rounded half up (Spark
    rounds decimals half up); null when the denominator is 0."""
    from pyspark.sql import functions as F

    exact = numerator.cast("decimal(18,6)") / denominator.cast("decimal(18,6)")
    return F.when(denominator == 0, F.lit(None)).otherwise(
        F.round(exact, 4).cast("decimal(9,4)")
    )


def labeled(spark, output: str):
    """One row per decision with a label: transaction_id, rules_version,
    label_source, is_fraud, pattern, decision, opens_case, amount_usd."""
    from pyspark.sql import functions as F

    decisions = sp.read(spark, "fact_decision", output).select(
        "transaction_id", "rules_version", "decision", "opens_case", "amount_usd"
    )
    labels = sp.read(spark, "fact_label", output).select(
        "transaction_id",
        F.col("source").alias("label_source"),
        "is_fraud",
        "pattern",
    )
    return decisions.join(labels.dropDuplicates(["transaction_id"]), "transaction_id")


def _hits(spark, output: str, rows):
    hits = sp.read(spark, "fact_rule_hit", output).select(
        "transaction_id", "rule", "rule_version"
    )
    return rows.join(hits, "transaction_id")


def rule_metrics(spark, output: str):
    from pyspark.sql import functions as F

    rows = labeled(spark, output)
    group = ["label_source", "rules_version"]
    legitimate = rows.groupBy(*group).agg(
        F.sum(F.when(F.col("is_fraud"), 0).otherwise(1)).alias("legitimate")
    )
    fired = (
        _hits(spark, output, rows)
        .where(F.col("rule") != DEFAULT_RULE)
        .groupBy(*group, "rule", "rule_version")
        .agg(
            F.countDistinct("transaction_id").alias("hits"),
            F.sum(F.when(F.col("is_fraud"), 1).otherwise(0)).alias("true_positives"),
        )
    )
    catalog = (
        sp.read(spark, "dim_rule", output)
        .where(F.col("rule") != DEFAULT_RULE)
        .select("rules_version", "rule", "rule_version")
    )
    every_rule = (
        legitimate.select(*group)
        .join(catalog, "rules_version")
        .unionByName(fired.select(*group, "rule", "rule_version"))
        .dropDuplicates()
    )
    hits = F.coalesce(F.col("hits"), F.lit(0))
    tp = F.coalesce(F.col("true_positives"), F.lit(0))
    return (
        every_rule.join(fired, [*group, "rule", "rule_version"], "left")
        .join(legitimate, group)
        .select(
            "rule",
            "rule_version",
            "rules_version",
            "label_source",
            hits.alias("hits"),
            tp.alias("true_positives"),
            (hits - tp).alias("false_positives"),
            _ratio(tp, hits).alias("precision"),
            _ratio(hits - tp, F.col("legitimate")).alias("false_positive_rate"),
        )
    )


def pattern_coverage(spark, output: str):
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    group = ["pattern", "label_source", "rules_version"]
    frauds = (
        labeled(spark, output)
        .where(F.col("is_fraud"))
        .withColumn("pattern", F.coalesce(F.col("pattern"), F.lit(NO_PATTERN)))
        .withColumn(
            "_detected",
            F.col("decision").isin(*DETECTED) | F.coalesce("opens_case", F.lit(False)),
        )
    )
    usd = F.coalesce(F.col("amount_usd"), F.lit(0).cast("decimal(18,2)"))
    counts = frauds.groupBy(*group).agg(
        F.count(F.lit(1)).alias("frauds"),
        F.sum(F.when(F.col("_detected"), 1).otherwise(0)).alias("detected"),
        F.sum(F.when(F.col("_detected"), usd).otherwise(0)).alias("_detected_usd"),
        F.sum(F.when(F.col("_detected"), 0).otherwise(usd)).alias("_missed_usd"),
    )
    best = Window.partitionBy(*group).orderBy(F.col("_n").desc(), F.col("rule"))
    top = (
        _hits(spark, output, frauds.where(F.col("_detected")))
        .groupBy(*group, "rule")
        .agg(F.countDistinct("transaction_id").alias("_n"))
        .withColumn("_rank", F.row_number().over(best))
        .where(F.col("_rank") == 1)
        .select(*group, F.col("rule").alias("top_rule"))
    )
    return counts.join(top, group, "left").select(
        "pattern",
        "label_source",
        "rules_version",
        "frauds",
        "detected",
        (F.col("frauds") - F.col("detected")).alias("missed"),
        _ratio(F.col("detected"), F.col("frauds")).alias("detection_rate"),
        F.col("_detected_usd").cast("decimal(18,2)").alias("detected_amount_usd"),
        F.col("_missed_usd").cast("decimal(18,2)").alias("missed_amount_usd"),
        "top_rule",
    )


def replayed(spark, raw: str, table: str):
    """The rows of raw/metrics/kaggle/<table>.jsonl (empty without a replay)."""
    from pyspark.sql import functions as F

    files = [
        f
        for f in sp.jsonl_files(raw, RAW_METRICS)
        if f.replace("\\", "/").endswith(f"/kaggle/{table}.jsonl")
    ]
    return (
        sp.lines(spark, files)
        .select(F.from_json("value", RAW_SCHEMAS[table]).alias("m"))
        .select("m.*")
    )


def build(spark, day: date, raw: str, output: str) -> dict:
    """Rebuild both tables (`day` is the day the ETL ran for; the tables
    cover every day). Returns the rows written per table."""
    return {
        "rule_metrics": sp.write(
            spark,
            rule_metrics(spark, output).unionByName(
                replayed(spark, raw, "rule_metrics"), allowMissingColumns=True
            ),
            "rule_metrics",
            output,
        ),
        "pattern_coverage": sp.write(
            spark,
            pattern_coverage(spark, output).unionByName(
                replayed(spark, raw, "pattern_coverage"), allowMissingColumns=True
            ),
            "pattern_coverage",
            output,
        ),
    }
