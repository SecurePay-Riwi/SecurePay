"""The six views of the business questions (contract C3).

sql/q<N>_<name>.sql is an Athena CREATE OR REPLACE VIEW over the tables
of shared/analytics.py; sql/control/q<N>.sql reaches the same numbers
another way, without the view. Both are written in the SQL that Athena
(Trino) and Spark SQL share, so locally they run in Spark over the
Parquet tables (test_views.py, and the last step of the ETL).
"""

import re
from pathlib import Path

from services.analytics import spark as sp
from shared.analytics import TABLES

SQL_DIR = Path(__file__).parent / "sql"
CONTROL_DIR = SQL_DIR / "control"

_VIEW = re.compile(
    r"^\s*CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)\s+AS\s+", re.IGNORECASE | re.DOTALL
)


def view_files() -> dict[str, Path]:
    """q1 -> sql/q1_transactions.sql, ... for every view in sql/."""
    return {p.name.split("_", 1)[0]: p for p in sorted(SQL_DIR.glob("q*_*.sql"))}


def _strip_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


def view_sql(view: str) -> tuple[str, str]:
    """(name of the view, its SELECT) of sql/q<N>_*.sql."""
    sql = _strip_comments(view_files()[view].read_text(encoding="utf-8"))
    found = _VIEW.match(sql)
    if not found:
        raise ValueError(f"{view}: expected CREATE OR REPLACE VIEW <name> AS SELECT")
    return found.group(1), sql[found.end() :].strip().rstrip(";")


def control_sql(view: str) -> str:
    sql = (CONTROL_DIR / f"{view}.sql").read_text(encoding="utf-8")
    return _strip_comments(sql).strip().rstrip(";")


def register_tables(spark, output: str) -> None:
    """Every table of TABLES as a temporary view with its own name."""
    for name in TABLES:
        sp.read(spark, name, output).createOrReplaceTempView(name)


def run_view(spark, view: str):
    """The view as a DataFrame (register_tables first). It is also
    registered under its name, as in Athena."""
    name, select = view_sql(view)
    df = spark.sql(select)
    df.createOrReplaceTempView(name)
    return df


def run_control(spark, view: str):
    return spark.sql(control_sql(view))


def write_views(spark, output: str) -> dict:
    """Run every view over the local tables and write each one to
    <output>/views/<view>/ as Parquet (what Power BI imports in
    development, D6). Returns the rows of each view."""
    register_tables(spark, output)
    written = {}
    for view in view_files():
        df = run_view(spark, view)
        path = f"{output.rstrip('/')}/views/{view}"
        if not sp.spark_reads(spark, path):
            raise ValueError(f"A local Spark session writes local folders, not {path}")
        df.coalesce(1).write.mode("overwrite").parquet(path)
        written[view] = df.count()
    return written
