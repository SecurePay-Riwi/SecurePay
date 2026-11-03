"""Builder of fact_case (Yulianis, HU-51).

Reads raw/cases/fecha=<day>/cases.jsonl and case_events.jsonl (the
current state of the cases, written by export.py) and writes fact_case
with the columns of shared/analytics.py TABLES["fact_case"], partitioned
by the day of created_at. Step 0 leaves the signature only: it writes
nothing yet.
"""

from datetime import date

TABLES = ("fact_case",)


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write fact_case for the cases exported on `day`. Returns the rows
    written per table ({} until HU-51)."""
    return {}
