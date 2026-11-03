"""Analytics (sprint 6): the data lake's curated and analytics layers,
the six views of the business questions, and the replay of the engine
over the labeled history.

The pieces and their owners (contract in shared/analytics.py):

    etl.py                  raw -> curated -> analytics -> views   (Habith, step 0)
    build_decisions.py      curated/decisiones, fact_decision, fact_rule_hit,
                            fact_label, dim_date, dim_rule, dim_merchant (Habith)
    build_cases.py          fact_case                              (Yulianis, HU-51)
    build_reconciliation.py fact_difference, dim_partner           (Yulianis, HU-52)
    build_devices.py        dim_device                             (Yulianis, HU-47)
    export.py               PostgreSQL -> raw/cases, raw/reconciliation (Yulianis, C6)
    labels.py               generator labels and Kaggle rows (C4)  (Habith)
    replay.py, metrics.py   the engine over the history (C5)       (Habith, HU-44 to HU-46)
    build_metrics.py        rule_metrics, pattern_coverage (Spark) (Habith, HU-44 to HU-46)
    views.py, sql/          the views q1..q6 and their controls (C3)

Locally `uv run python -m services.analytics --day 2026-10-05` runs the
ETL and writes the views under ANALYTICS_DATA_DIR; in AWS the Glue job
securepay-<env>-analytics runs etl.main (infra/spark/analytics_job.py).
"""

import os

# Root of the lake in local runs (ignored by git); in AWS, s3://<datalake>.
ANALYTICS_DATA_DIR = os.getenv("ANALYTICS_DATA_DIR", "generated/analytics")
# Days of cases and differences the PostgreSQL export writes (C6).
ANALYTICS_EXPORT_DAYS = int(os.getenv("ANALYTICS_EXPORT_DAYS", "30"))
# The generator's labels.jsonl, copied by python -m services.analytics.labels.
LABELS_SOURCE = os.getenv(
    "LABELS_SOURCE", "../securepay-generator/generated/instance-0/labels.jsonl"
)
# Athena in AWS (HU-66): the workgroup and the Glue catalog database.
ATHENA_WORKGROUP = os.getenv("ATHENA_WORKGROUP", "securepay-dev-analytics")
GLUE_DATABASE = os.getenv("GLUE_DATABASE", "securepay_dev_analytics")

if ANALYTICS_EXPORT_DAYS <= 0:
    raise ValueError("ANALYTICS_EXPORT_DAYS must be positive.")
