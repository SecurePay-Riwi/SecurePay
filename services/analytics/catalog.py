"""The Glue catalog tables of the analytics model, from shared/analytics.py
(HU-66, MAG-363).

    uv run python -m services.analytics.catalog

writes infra/terraform/modules/analytics/tables.json, which Terraform
reads to create one Glue table per entry of TABLES (no crawler), so the
schema lives in one place. test_catalog.py fails when the file is older
than TABLES: run the command again and commit the file.

A daily table is partitioned by the folder fecha=<day>/ (a `fecha`
string key, filled by Athena's partition projection, so no partition is
ever registered); its own `day`, `run_day` or `as_of` column stays in
the Parquet files and is what the views use.
"""

import argparse
import json
from pathlib import Path

from shared.analytics import ANALYTICS, PARTITION, TABLES

OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "terraform"
    / "modules"
    / "analytics"
    / "tables.json"
)

# Glue limits a column comment to 255 characters.
COMMENT_LIMIT = 255


def glue_tables() -> dict:
    """{table: {"description", "location", "partition", "columns": [...]}}:
    location is relative to the bucket, partition the key's name or null."""
    return {
        t.name: {
            "description": f"{t.grain[:1].upper()}{t.grain[1:]}. Source: {t.source}"[
                :COMMENT_LIMIT
            ],
            "location": f"{ANALYTICS}/{t.name}/",
            "partition": PARTITION if t.partition else None,
            "columns": [
                {
                    "name": c.name,
                    "type": c.type,
                    "comment": c.description[:COMMENT_LIMIT],
                }
                for c in t.columns
            ],
        }
        for t in TABLES.values()
    }


def render() -> str:
    return json.dumps(glue_tables(), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Write the Glue catalog tables.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    args.output.write_text(render(), encoding="utf-8")
    print(f"{len(TABLES)} tables written to {args.output}")


if __name__ == "__main__":
    main()
