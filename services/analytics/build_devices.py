"""Builder of dim_device (Yulianis, HU-47).

Reads curated/decisiones of the 30 days up to `day` (accounts per device
like RN-04: the main account, the source or, in a top-up, the
destination) and the cases of raw/cases, and writes dim_device with its
risk_level (rules in doc-website/docs/reference/analytics-model.mdx).
Step 0 leaves the signature only: it writes nothing yet.
"""

from datetime import date

TABLES = ("dim_device",)


def build(spark, day: date, raw: str, output: str, **_) -> dict:
    """Write the partition as_of=<day> of dim_device. Returns the rows
    written per table ({} until HU-47)."""
    return {}
