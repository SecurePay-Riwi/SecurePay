"""The analytics contract (shared/analytics.py, sprint 6 C1 and C2): the
paths of the layers, the tables of the dimensional model with the
contract's columns, and the data dictionary page that documents them."""

import re
from datetime import date
from pathlib import Path

import pytest

from shared import analytics
from shared.analytics import TABLES, TYPES, LabelSource, layer_path, table_path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "doc-website" / "docs" / "reference" / "analytics-model.mdx"

# The columns of contract C2, in order (rule_metrics and pattern_coverage
# from C3 and C5).
CONTRACT = {
    "fact_decision": "transaction_id day transaction_at type currency channel amount amount_usd usd_rate rate_date decision risk_score rules_version by_default opens_case device_id merchant_id source_account_id destination_account_id label_source",
    "fact_rule_hit": "transaction_id day rule rule_version decision score",
    "fact_label": "transaction_id day source pattern is_fraud expected_rule",
    "fact_case": "case_id transaction_id day created_at due_at assigned_to assigned_at resolved_at resolved_by status outcome final_decision escalated escalated_at minutes_to_resolve within_sla rules_triggered risk_score amount_usd",
    "fact_difference": "difference_id run_day partner type status reference currency pagoseguro_amount partner_amount amount_difference age_days age_range detected_at resolved_at",
    "fact_reconciliation_match": "run_day partner matched",
    "dim_date": "day year month day_of_month weekday is_weekend",
    "dim_rule": "rule rule_version type action opens_case score enabled rules_version",
    "dim_partner": "partner tx_types channels utc_offset",
    "dim_device": "device_id accounts_30d transactions_30d held_or_rejected_30d cases_30d shared risk_level as_of",
    "dim_merchant": "merchant_id transactions_30d held_or_rejected_30d fraud_labeled_30d as_of",
    "rule_metrics": "rule rule_version rules_version label_source hits true_positives false_positives precision false_positive_rate",
    "pattern_coverage": "pattern label_source rules_version frauds detected missed detection_rate detected_amount_usd missed_amount_usd top_rule",
}


def test_layer_paths():
    day = date(2026, 10, 5)

    assert layer_path("s3://lake/", analytics.RAW_DECISIONS, day) == (
        "s3://lake/raw/decisiones/fecha=2026-10-05"
    )
    assert layer_path("generated/analytics", analytics.CURATED_DECISIONS) == (
        "generated/analytics/curated/decisiones"
    )
    assert table_path("s3://lake", "fact_case", day) == (
        "s3://lake/analytics/fact_case/fecha=2026-10-05"
    )
    assert table_path("s3://lake", "dim_rule") == "s3://lake/analytics/dim_rule"


def test_label_sources():
    assert [s.value for s in LabelSource] == ["generator", "paysim", "sparkov"]


def test_the_tables_are_the_contracts():
    assert {name: " ".join(t.column_names) for name, t in TABLES.items()} == CONTRACT


def test_every_column_has_a_known_type_and_a_description():
    for table in (*TABLES.values(), analytics.CURATED_DECISION):
        assert table.grain and table.source and table.owner, table.name
        for column in table.columns:
            assert column.type in TYPES, (table.name, column.name)
            assert column.description.endswith("."), (table.name, column.name)


def test_a_partition_is_a_date_column_of_its_table():
    for table in TABLES.values():
        if table.partition is None:
            continue
        [column] = [c for c in table.columns if c.name == table.partition]
        assert column.type == "date", table.name


def test_money_is_decimal_and_moments_are_timestamps():
    for table in (*TABLES.values(), analytics.CURATED_DECISION):
        for c in table.columns:
            if c.name.startswith("amount") or c.name.endswith("_amount"):
                assert c.type == "decimal(18,2)", (table.name, c.name)
            if c.name.endswith("_at") and c.name != "as_of":
                assert c.type == "timestamp", (table.name, c.name)


def test_an_unknown_type_is_refused():
    with pytest.raises(ValueError, match="unknown type"):
        analytics.Column("x", "float", "A float.")


def test_the_data_dictionary_documents_every_table_and_column():
    page = PAGE.read_text(encoding="utf-8")

    for table in TABLES.values():
        assert re.search(rf"^### `{table.name}`", page, re.MULTILINE), table.name
        for column in table.columns:
            assert f"| `{column.name}` | `{column.type}` |" in page, (
                table.name,
                column.name,
            )


def test_spark_schema_follows_the_table():
    T = pytest.importorskip("pyspark.sql.types")

    schema = analytics.spark_schema("fact_decision")

    assert [f.name for f in schema.fields] == list(TABLES["fact_decision"].column_names)
    types = {f.name: f.dataType for f in schema.fields}
    assert types["amount"] == T.DecimalType(18, 2)
    assert types["usd_rate"] == T.DecimalType(18, 8)
    assert types["day"] == T.DateType()
    assert types["transaction_at"] == T.TimestampType()
    assert analytics.spark_schema("fact_case")["rules_triggered"].dataType == (
        T.ArrayType(T.StringType())
    )


def test_only_analytics_imports_the_replay():
    """C5: nobody outside services/analytics/ imports the analytics code,
    the replay included, except the rules API's simulation route (HU-24,
    services/rules_api/simulation.py) and tests."""
    allowed = ROOT / "services" / "rules_api" / "simulation.py"
    for path in (ROOT / "services").rglob("*.py"):
        if "analytics" in path.parts or "tests" in path.parts or path == allowed:
            continue
        assert "services.analytics" not in path.read_text(encoding="utf-8"), path
