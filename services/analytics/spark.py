"""Spark helpers of the analytics builders: the session, reading JSON
lines and writing or reading the Parquet tables of shared/analytics.py.

Like the reconciliation's match: Spark reads and writes local folders,
and s3:// only on a cluster (AWS Glue). In local mode s3:// (LocalStack)
raw files are read through services/reconciliation/storage.py; the
output of a local run must be a local folder. pyspark is imported inside
the functions, so importing this module does not need it.
"""

from datetime import date

from services.reconciliation import storage
from shared.analytics import (
    CURATED_DECISION,
    CURATED_DECISIONS,
    PARTITION,
    TABLES,
    layer_path,
    spark_schema,
    table_path,
)

APP_NAME = "securepay-analytics"


def session():
    """The cluster's session under spark-submit (AWS Glue), local[*]
    otherwise. Times in UTC."""
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName(APP_NAME)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )


def is_local(spark) -> bool:
    return spark.sparkContext.master.startswith("local")


def spark_reads(spark, path: str) -> bool:
    """Whether Spark reads `path` itself: a local folder always, s3://
    only on a cluster."""
    return not storage.is_s3(path) or not is_local(spark)


def lines(spark, paths: list[str]):
    """A DataFrame with one `value` per line of the files, and `_order`
    (the file and line order, for "the first one wins")."""
    from pyspark.sql import Row
    from pyspark.sql import functions as F

    if not paths:
        return spark.createDataFrame([], "value string, _order bigint")
    if all(spark_reads(spark, p) for p in paths):
        return spark.read.text(sorted(paths)).withColumn(
            "_order", F.monotonically_increasing_id()
        )
    rows = [
        Row(value=line, _order=i)
        for i, line in enumerate(
            line
            for p in sorted(paths)
            for line in storage.read_text(p).splitlines()
            if line.strip()
        )
    ]
    return spark.createDataFrame(rows, "value string, _order bigint")


def jsonl_files(root: str, layer: str, days: list[date] | None = None) -> list[str]:
    """The *.jsonl files of a raw layer: of the given days, or of every day."""
    if days is None:
        return storage.list_files(layer_path(root, layer), "*.jsonl")
    return [
        f
        for d in days
        for f in storage.list_files(layer_path(root, layer, d), "*.jsonl")
    ]


def _check_output(spark, path: str) -> None:
    if storage.is_s3(path) and is_local(spark):
        raise ValueError(
            f"A local Spark session writes local folders, not {path}: "
            "use a local ANALYTICS_DATA_DIR (AWS Glue writes s3://)."
        )


def write(spark, df, table: str, root: str, day: date | None = None) -> int:
    """Write a table with its schema (shared/analytics.py) as Parquet:
    the partition fecha=<day>/ of a daily table, or the whole table.
    Replaces what was there, so running a day again gives the same
    result. Returns how many rows it wrote."""
    schema = spark_schema(table)
    df = df.select([df[f.name].cast(f.dataType).alias(f.name) for f in schema.fields])
    if table == CURATED_DECISION.name:
        path = layer_path(root, CURATED_DECISIONS, day)
    else:
        path = table_path(root, table, day)
    _check_output(spark, path)
    df = df.cache()
    try:
        count = df.count()
        df.coalesce(1).write.mode("overwrite").parquet(path)
    finally:
        df.unpersist()
    return count


def _days_in(folder: str) -> list[date]:
    """The days of the fecha=<day>/ folders that have Parquet files."""
    found = set()
    for f in storage.list_files(folder, "*.parquet"):
        for part in f.split("/"):
            if part.startswith(f"{PARTITION}="):
                found.add(date.fromisoformat(part.split("=", 1)[1]))
    return sorted(found)


def stored_days(root: str, table: str) -> list[date]:
    """Days with a partition written, of curated_decision or a daily table."""
    if table == CURATED_DECISION.name:
        return _days_in(layer_path(root, CURATED_DECISIONS))
    return _days_in(table_path(root, table))


def read(spark, table: str, root: str, days: list[date] | None = None):
    """A table (or curated_decision) with its schema: the given days of a
    daily table (those that exist), or all of it. Empty, with the schema,
    when nothing was written."""
    schema = spark_schema(table)
    daily = table == CURATED_DECISION.name or TABLES[table].partition is not None
    if daily:
        existing = stored_days(root, table)
        wanted = existing if days is None else [d for d in days if d in existing]
        base = (
            (lambda d: layer_path(root, CURATED_DECISIONS, d))
            if table == CURATED_DECISION.name
            else (lambda d: table_path(root, table, d))
        )
        paths = [base(d) for d in wanted]
    else:
        whole = table_path(root, table)
        paths = [whole] if storage.list_files(whole, "*.parquet") else []
    if not paths:
        return spark.createDataFrame([], schema)
    return spark.read.schema(schema).parquet(*paths)
