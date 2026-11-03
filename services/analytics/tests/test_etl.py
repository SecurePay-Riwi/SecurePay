"""The decisions' builder over the fixture day (step 0): curated
deduplicates and keeps the day's window, the facts and dimensions have
the contract's schema, and running the day again gives the same result.
Spark tests: they skip without Java."""

import json
from datetime import date
from decimal import Decimal

from services.analytics import etl
from services.analytics import spark as sp
from services.analytics.tests.conftest import DAY, FIXTURES
from shared.analytics import TABLES, spark_schema

# What the fixture day has (README.md): 35 transactions in raw, one of
# the day before; 34 of the day, 32 of them labeled.
DAY_TRANSACTIONS = 34
LABELED = 32


def _raw_events() -> list[dict]:
    return [
        json.loads(line)
        for path in sorted((FIXTURES / "raw" / "decisiones").rglob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _rows(spark, table, lake, days=None):
    return [r.asDict() for r in sp.read(spark, table, lake, days).collect()]


def test_curated_has_one_row_per_transaction_of_the_day(spark, lake):
    rows = _rows(spark, "curated_decision", lake, [DAY])
    events = _raw_events()

    assert len(events) > len({e["transaction"]["id"] for e in events})  # repeated lines
    assert len(rows) == DAY_TRANSACTIONS
    assert len({r["transaction_id"] for r in rows}) == DAY_TRANSACTIONS
    assert {r["day"] for r in rows} == {DAY}


def test_curated_reads_the_events_that_arrive_the_next_day(spark, lake):
    late = [
        e
        for e in _raw_events()
        if e["transaction"]["transaction_date"].startswith("2026-10-05T23:58")
    ]
    ids = {r["transaction_id"] for r in _rows(spark, "curated_decision", lake, [DAY])}

    assert late and late[0]["transaction"]["id"] in ids


def test_curated_leaves_out_the_day_before(spark, lake):
    before = [
        e
        for e in _raw_events()
        if e["transaction"]["transaction_date"].startswith("2026-10-04")
    ]
    ids = {r["transaction_id"] for r in _rows(spark, "curated_decision", lake, [DAY])}

    assert before and before[0]["transaction"]["id"] not in ids


def test_curated_keeps_the_event_as_the_engine_decided(spark, lake):
    event = next(
        e for e in _raw_events() if e["decision"]["rules_triggered"] == ["splitting"]
    )
    tx, d = event["transaction"], event["decision"]
    [row] = [
        r
        for r in _rows(spark, "curated_decision", lake, [DAY])
        if r["transaction_id"] == tx["id"]
    ]

    assert row["amount"] == Decimal(tx["amount"])
    assert row["source_balance_before"] == Decimal(tx["source_balance_before"])
    assert row["decision"] == d["decision"] == "HOLD"
    assert row["rules_triggered"] == ["splitting"]
    assert json.loads(row["rule_versions"]) == d["rule_versions"]
    assert row["opens_case"] is True
    assert row["amount_usd"] == Decimal(d["amount_usd"])
    assert row["usd_rate"] == Decimal(d["usd_rate"])
    assert row["rate_date"] == date.fromisoformat(d["rate_date"])


def test_fact_decision_has_the_labels_source(spark, lake):
    rows = _rows(spark, "fact_decision", lake, [DAY])

    assert len(rows) == DAY_TRANSACTIONS
    assert sum(1 for r in rows if r["label_source"] == "generator") == LABELED
    assert {r["label_source"] for r in rows} == {"generator", None}


def test_fact_label_is_one_row_per_labeled_transaction(spark, lake):
    rows = _rows(spark, "fact_label", lake, [DAY])

    # The security event and the repeated line of labels.jsonl are left out.
    assert len(rows) == LABELED
    assert len({r["transaction_id"] for r in rows}) == LABELED
    assert {r["source"] for r in rows} == {"generator"}
    assert sum(r["is_fraud"] for r in rows) == 19


def test_fact_rule_hit_takes_decision_and_score_from_the_catalog(spark, lake):
    hits = _rows(spark, "fact_rule_hit", lake, [DAY])
    by_rule = {}
    for h in hits:
        by_rule.setdefault(h["rule"], set()).add(
            (h["rule_version"], h["decision"], h["score"])
        )

    assert by_rule == {
        "restricted_list": {(1, "REJECT", 0)},
        "velocity": {(1, "HOLD", 0)},
        "mule": {(1, "HOLD", 0)},
        "shared_device": {(1, "APPROVE", 30)},
        "splitting": {(1, "HOLD", 40)},
        "account_takeover": {(1, "HOLD", 0)},
        # The default decision: the transaction's own decision.
        "default_timeout": {(1, "APPROVE", 0), (1, "HOLD", 0)},
    }


def test_dim_date_and_dim_rule(spark, lake):
    [day] = _rows(spark, "dim_date", lake)
    rules = _rows(spark, "dim_rule", lake)

    assert day == {
        "day": DAY,
        "year": 2026,
        "month": 10,
        "day_of_month": 5,
        "weekday": 1,  # a Monday
        "is_weekend": False,
    }
    splitting = next(r for r in rules if r["rule"] == "splitting")
    assert (splitting["action"], splitting["opens_case"], splitting["score"]) == (
        "HOLD",
        True,
        40,
    )
    assert {r["rules_version"] for r in rules} == {"0"}


def test_dim_merchant_counts_the_30_days(spark, lake, expected):
    rows = {r["merchant_id"]: r for r in _rows(spark, "dim_merchant", lake, [DAY])}
    risky = {r["id"]: r for r in expected["q6"] if r["kind"] == "MERCHANT"}

    assert len(rows) == 3
    for merchant_id, r in risky.items():
        assert rows[merchant_id]["transactions_30d"] == r["transactions_30d"]
        assert rows[merchant_id]["held_or_rejected_30d"] == r["held_or_rejected_30d"]
    assert {r["as_of"] for r in rows.values()} == {DAY}
    assert sum(r["fraud_labeled_30d"] for r in rows.values()) == 1


def test_every_table_is_written_with_its_schema(spark, lake):
    for name in (
        "curated_decision",
        *[
            t
            for t in TABLES
            if t.startswith(
                (
                    "fact_decision",
                    "fact_rule",
                    "fact_label",
                    "dim_date",
                    "dim_rule",
                    "dim_merchant",
                )
            )
        ],
    ):
        assert sp.read(spark, name, lake).schema == spark_schema(name), name


def test_running_the_day_again_gives_the_same_tables(spark, lake, tmp_path):
    again = str(tmp_path / "again")
    first = etl.run_day(spark, DAY, str(FIXTURES), again)
    second = etl.run_day(spark, DAY, str(FIXTURES), again)

    assert first == second
    assert first["tables"]["curated_decision"] == DAY_TRANSACTIONS
    assert len(_rows(spark, "fact_decision", again)) == DAY_TRANSACTIONS


def test_the_builders_of_step_0_write_nothing_yet(spark, tmp_path):
    from services.analytics import build_cases, build_devices, build_reconciliation

    for builder in (build_cases, build_reconciliation, build_devices):
        assert builder.build(spark, DAY, str(FIXTURES), str(tmp_path)) == {}
    assert etl.BUILDERS[0].__module__ == "services.analytics.build_decisions"


def test_a_local_session_refuses_to_write_to_s3(spark):
    import pytest

    with pytest.raises(ValueError, match="local folders"):
        sp.write(
            spark,
            spark.createDataFrame([], spark_schema("dim_date")),
            "dim_date",
            "s3://lake",
        )
