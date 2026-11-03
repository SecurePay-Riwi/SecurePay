"""Builder of fact_difference and dim_partner (Yulianis, HU-52).

Reads raw/reconciliation/fecha=<day>/differences.jsonl and runs.jsonl
(written by export.py) and writes fact_difference (partition run_day,
age_days and age_range counted to `day` with AGE_RANGES of
shared/reconciliation.py) and dim_partner (from Partner and
PARTNER_UTC_OFFSET). Step 0 leaves the signature only: it writes nothing
yet.
"""

from datetime import date

TABLES = ("fact_difference", "dim_partner")


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write fact_difference and dim_partner for the export of `day`.
    Returns the rows written per table ({} until HU-52)."""
    return {}
