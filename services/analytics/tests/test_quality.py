"""Data quality checks (HU-66, MAG-294): the fixture day passes every
check, and each kind of bad row is caught."""

from decimal import Decimal

import pytest

from services.analytics import quality
from services.analytics.tests.conftest import DAY
from shared.analytics import TABLES


def test_the_fixture_day_passes_every_check(spark, lake):
    result = quality.check_day(spark, lake, DAY)

    assert result == {"day": DAY.isoformat(), "tables": len(TABLES), "failures": {}}


def test_every_table_has_checks():
    for table in TABLES.values():
        assert quality.checks(table), table.name


def _decisions(spark, **changes):
    """One valid fact_decision row with `changes` applied."""
    from shared.analytics import spark_schema

    row = {
        "transaction_id": "t-1",
        "day": DAY,
        "type": "P2P",
        "currency": "USD",
        "channel": "APP",
        "amount": Decimal("10.00"),
        "amount_usd": Decimal("10.00"),
        "decision": "APPROVE",
        "risk_score": 0,
    }
    row.update(changes)
    schema = spark_schema("fact_decision")
    return spark.createDataFrame(
        [tuple(row.get(f.name) for f in schema.fields)], schema
    )


@pytest.mark.parametrize(
    "changes, failed",
    [
        ({"transaction_id": None}, "fact_decision.transaction_id not null"),
        ({"transaction_id": " "}, "fact_decision.transaction_id not empty"),
        ({"day": None}, "fact_decision.day not null"),
        ({"amount_usd": None}, "fact_decision.amount_usd not null"),
        ({"currency": "GBP"}, "fact_decision.currency in COP/EUR/JPY/USD"),
        ({"decision": "MAYBE"}, "fact_decision.decision in APPROVE/HOLD/REJECT"),
        ({"amount": Decimal("0")}, "fact_decision.amount > 0"),
        ({"amount_usd": Decimal("-1")}, "fact_decision.amount_usd > 0"),
        ({"risk_score": 101}, "fact_decision.risk_score between 0 and 100"),
        ({"merchant_id": ""}, "fact_decision.merchant_id not empty"),
    ],
)
def test_a_bad_row_fails_its_check(spark, changes, failed):
    df = _decisions(spark, **changes)

    assert quality.failures_of(df, TABLES["fact_decision"]) == {failed: 1}


def test_optional_columns_may_be_null(spark):
    df = _decisions(spark, merchant_id=None, device_id=None, channel=None)

    assert quality.failures_of(df, TABLES["fact_decision"]) == {}


def test_a_ratio_out_of_range_fails(spark):
    from shared.analytics import spark_schema

    schema = spark_schema("rule_metrics")
    values = {"rule": "velocity", "precision": Decimal("1.5")}
    df = spark.createDataFrame(
        [tuple(values.get(f.name) for f in schema.fields)], schema
    )

    assert quality.failures_of(df, TABLES["rule_metrics"]) == {
        "rule_metrics.precision between 0 and 1": 1
    }


def test_the_key_of_a_dimension_is_required(spark):
    from shared.analytics import spark_schema

    schema = spark_schema("dim_device")
    df = spark.createDataFrame([(None,) + (None,) * 6 + (DAY,)], schema)

    assert quality.failures_of(df, TABLES["dim_device"]) == {
        "dim_device.device_id not null": 1
    }


def test_check_day_raises_with_every_failure(spark, tmp_path):
    from services.analytics import spark as sp

    sp.write(
        spark, _decisions(spark, currency="GBP"), "fact_decision", str(tmp_path), DAY
    )

    with pytest.raises(quality.QualityError, match="currency in COP/EUR/JPY/USD"):
        quality.check_day(spark, str(tmp_path), DAY)


def test_an_empty_table_passes(spark, tmp_path):
    assert quality.check_table(spark, "fact_case", str(tmp_path), DAY) == {}
