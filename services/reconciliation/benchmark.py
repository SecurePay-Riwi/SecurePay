"""Performance of the Spark match (E-13): the fixture day, scaled up, run
with each Spark configuration of VARIANTS, timed and with its plan.

    uv run python -m services.reconciliation.benchmark --copies 20000 \
        --out benchmark/        # writes benchmark/report.json and plans

The scaled day keeps every case of the fixtures (MATCHED, AMOUNT_OFF,
DATE_OFF, ONLY_PAGOSEGURO, ONLY_PARTNER): each copy gives every
transaction id a new uuid5, in the decisions and in the records alike, so
the result of `copies` copies is `copies` times the fixture's. The
numbers go to doc-website/docs/operations/performance.mdx.
"""

import argparse
import json
import shutil
import subprocess
import time
import urllib.request
import uuid
from datetime import date
from pathlib import Path

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
DAY = date(2026, 10, 5)
NAMESPACE = uuid.UUID("6f1d7e22-1b4c-4a8e-9a55-0d6c3f6a9b10")

# name -> (what it shows, Spark settings). The session is new for each one.
VARIANTS = {
    "defaults": ("Spark 4.1 defaults, as match.session() was before E-13", {}),
    "tuned": ("match.session(): SESSION_SETTINGS", None),
}


def _new_id(copy: int, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{copy}:{value}"))


def scale(out: Path, copies: int) -> tuple[Path, Path]:
    """Writes decisions/fecha=<d>/part-0000.jsonl and records.jsonl with
    `copies` copies of the fixtures. Returns (records, decisions)."""
    decisions_out = out / "decisiones"
    for folder in sorted((FIXTURES / "decisiones").iterdir()):
        events = [json.loads(line) for line in (folder / "part-0000.jsonl").open()]
        target = decisions_out / folder.name
        target.mkdir(parents=True, exist_ok=True)
        with (target / "part-0000.jsonl").open("w") as f:
            for copy in range(copies):
                for event in events:
                    tx = event["transaction"]
                    tx = {**tx, "id": _new_id(copy, tx["id"])}
                    f.write(json.dumps({**event, "transaction": tx}) + "\n")

    source = FIXTURES / "curated" / "extractos" / f"fecha={DAY}" / "records.jsonl"
    records = [json.loads(line) for line in source.open()]
    records_out = out / "records.jsonl"
    with records_out.open("w") as f:
        for copy in range(copies):
            for record in records:
                f.write(
                    json.dumps(
                        {
                            **record,
                            "pagoseguro_reference": _new_id(
                                copy, record["pagoseguro_reference"]
                            ),
                            "partner_reference": f"{record['partner_reference']}-{copy}",
                        }
                    )
                    + "\n"
                )
    return records_out, decisions_out


def _stages(spark) -> list[dict]:
    """Completed stages of this application, from the Spark UI's REST API."""
    ui = spark.sparkContext.uiWebUrl
    app = spark.sparkContext.applicationId
    with urllib.request.urlopen(f"{ui}/api/v1/applications/{app}/stages") as r:
        return [s for s in json.load(r) if s["status"] == "COMPLETE"]


def run_variant(
    name: str, settings: dict | None, records: Path, decisions: Path, out: Path
) -> dict:
    from pyspark.sql import SparkSession

    from services.reconciliation import match

    builder = (
        SparkSession.builder.appName(f"benchmark-{name}")
        .master("local[*]")
        .config("spark.ui.showConsoleProgress", "false")
    )
    for key, value in (
        match.SESSION_SETTINGS
        if settings is None
        else {"spark.sql.session.timeZone": "UTC", **settings}
    ).items():
        builder = builder.config(key, value)
    spark = builder.getOrCreate()
    try:
        # Warm-up: the JVM and Python workers start once, outside the time.
        match.spark_match(spark, DAY, str(records), str(decisions)).limit(1).collect()
        before = {s["stageId"] for s in _stages(spark)}

        output = out / name / "conciliacion"
        start = time.perf_counter()
        result = match.reconcile(spark, DAY, str(records), str(decisions), str(output))
        seconds = time.perf_counter() - start

        stages = [s for s in _stages(spark) if s["stageId"] not in before]
        plan = match.spark_match(spark, DAY, str(records), str(decisions))
        (out / name).mkdir(parents=True, exist_ok=True)
        (out / name / "plan.txt").write_text(
            plan._jdf.queryExecution().explainString(
                spark._jvm.org.apache.spark.sql.execution.ExplainMode.fromString(
                    "formatted"
                )
            )
        )
        return {
            "variant": name,
            "seconds": round(seconds, 2),
            "rows": result["matched"] + result["unmatched"],
            "matched": result["matched"],
            "stages": len(stages),
            "tasks": sum(s["numTasks"] for s in stages),
            "shuffle_write_mb": round(
                sum(s["shuffleWriteBytes"] for s in stages) / 2**20, 1
            ),
            "shuffle_read_mb": round(
                sum(s["shuffleReadBytes"] for s in stages) / 2**20, 1
            ),
            "input_mb": round(sum(s["inputBytes"] for s in stages) / 2**20, 1),
        }
    finally:
        spark.stop()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--copies", type=int, default=20000)
    parser.add_argument("--out", type=Path, default=Path("benchmark"))
    parser.add_argument(
        "--runs", type=int, default=3, help="runs per variant; the median counts"
    )
    parser.add_argument("--variants", nargs="*", default=list(VARIANTS))
    args = parser.parse_args(argv)

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    records, decisions = scale(args.out / "data", args.copies)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    report = {"copies": args.copies, "commit": commit, "variants": {}}
    for name in args.variants:
        description, settings = VARIANTS[name]
        runs = [
            run_variant(name, settings, records, decisions, args.out)
            for _ in range(args.runs)
        ]
        runs.sort(key=lambda r: r["seconds"])
        report["variants"][name] = {
            "description": description,
            **runs[len(runs) // 2],
            "all_seconds": [r["seconds"] for r in runs],
        }
        print(json.dumps(report["variants"][name]))
    (args.out / "report.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
