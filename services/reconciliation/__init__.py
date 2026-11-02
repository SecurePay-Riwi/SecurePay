"""Nightly reconciliation with the payment partners (Sprint 5, RN-10).

The steps and their owners (contract in shared/reconciliation.py):

    ingest.py   read the partners' files of a day       (HU-36)
    match.py    match them with the engine's decisions  (HU-37, Spark)
    store.py    turn the match into differences         (HU-38 to HU-40)
    storage.py  read and write a local folder or s3://, for the three

Locally `uv run python -m services.reconciliation --day 2026-10-05` runs
the three in order; in AWS, Step Functions does it at 02:00 in Bogota.
"""

import os

# Root of curated/ in local runs (ignored by git); in AWS, s3://<datalake>.
RECON_DATA_DIR = os.getenv("RECON_DATA_DIR", "generated/reconciliation")
# Where ingest reads the partners' files.
STATEMENTS_SOURCE = os.getenv("STATEMENTS_SOURCE", "../securepay-csv/generated/extractos")
# What the analytics consumer writes: one folder fecha=YYYY-MM-DD per day.
DECISIONS_SOURCE = os.getenv("DECISIONS_SOURCE", "s3://pagoseguro-datalake/raw/decisiones")


def records_dir(target: str, day) -> str:
    """Where ingest writes records.jsonl and rejects.jsonl for `day`."""
    return f"{target.rstrip('/')}/curated/extractos/fecha={day.isoformat()}"


def match_dir(target: str, day) -> str:
    """Where match writes the part-*.json files of `day`."""
    return f"{target.rstrip('/')}/curated/conciliacion/fecha={day.isoformat()}"
