"""Rule metrics (HU-44 to HU-46, contract C5): the definitions with
decisions and labels built by hand, the plain-Python metrics against the
answer key of the fixture day, the replay of the command, and the Spark
builder with the rows of a Kaggle replay. Only the last test needs Java."""

import json
import shutil
from decimal import Decimal

import pytest

from services.analytics import build_metrics, metrics, views
from services.analytics.labels import generator_labels
from services.analytics.metrics import Label
from services.analytics.replay import ReferenceData, ReplayDecision
from services.analytics.tests.conftest import DAY, FIXTURES
from services.decision_engine import currency
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from shared.rule_catalog import default_catalog

LABELS = FIXTURES / "raw" / "labels" / "fecha=2026-10-05" / "labels.jsonl"


@pytest.fixture(autouse=True)
def fixed_rates():
    currency.load({})
    yield
    currency.load({})


def decision(tx, decision="APPROVE", rules=(), opens_case=False, version="0"):
    return ReplayDecision(tx, decision, tuple(rules), 0, opens_case, version)


def label(tx, is_fraud, pattern=None, source="generator"):
    return Label(tx, source, pattern, is_fraud, None)


def _plain(rows):
    out = []
    for r in rows:
        row = metrics.to_row(r)
        row.pop("rules_version")
        out.append(row)
    return out


# --- Definitions ----------------------------------------------------------------


def test_precision_and_false_positive_rate_are_exact():
    decisions = [
        decision("a", "HOLD", ["velocity"]),
        decision("b", "HOLD", ["velocity"]),
        decision("c", "HOLD", ["velocity"]),
        decision("d"),
        decision("e"),
        decision("f"),
    ]
    labels = [
        label("a", True, "VELOCITY"),
        label("b", True, "VELOCITY"),
        label("c", False),
        label("d", False),
        label("e", False),
        label("f", False),
    ]

    [row] = metrics.rule_metrics(decisions, labels)

    assert row == metrics.RuleMetrics(
        rule="velocity",
        label_source="generator",
        hits=3,
        true_positives=2,
        false_positives=1,
        precision=Decimal("0.6667"),  # 2/3, half up
        false_positive_rate=Decimal("0.2500"),  # 1 of 4 legitimate
        rule_version=None,
        rules_version="0",
    )


def test_a_rule_with_no_hits_has_no_precision():
    snapshot = default_catalog()

    rows = metrics.rule_metrics([decision("a")], [label("a", False)], snapshot)

    codes = [r.code for r in snapshot.rules if r.code != "default_timeout"]
    assert [r.rule for r in rows] == sorted(codes)
    assert all(r.hits == 0 and r.precision is None for r in rows)
    assert all(r.false_positive_rate == Decimal("0.0000") for r in rows)
    assert {r.rule_version for r in rows} == {1}


def test_a_transaction_without_a_label_does_not_count():
    decisions = [decision("a", "HOLD", ["mule"]), decision("b", "HOLD", ["mule"])]

    [row] = metrics.rule_metrics(decisions, [label("a", True, "MULE")])

    assert (row.hits, row.true_positives, row.false_positives) == (1, 1, 0)
    assert row.false_positive_rate is None  # no labeled legitimate transaction


def test_the_default_decision_is_not_a_rule():
    rows = metrics.rule_metrics(
        [decision("a", "HOLD", ["default_timeout"])], [label("a", False)]
    )

    assert rows == []


def test_label_sources_and_catalog_versions_are_measured_apart():
    decisions = [
        decision("a", "HOLD", ["velocity"]),
        decision("b", "HOLD", ["velocity"], version="3"),
        decision("c", "HOLD", ["velocity"]),
    ]
    labels = [
        label("a", True),
        label("b", True),
        label("c", False, source="paysim"),
    ]

    rows = metrics.rule_metrics(decisions, labels)

    assert [(r.label_source, r.rules_version, r.true_positives) for r in rows] == [
        ("generator", "0", 1),
        ("generator", "3", 1),
        ("paysim", "0", 0),
    ]


def test_a_repeated_label_or_decision_counts_once():
    decisions = [decision("a", "HOLD", ["mule"])] * 2

    [row] = metrics.rule_metrics(decisions, [label("a", True), label("a", False)])

    assert (row.hits, row.true_positives) == (1, 1)  # the first label wins


def test_detected_is_hold_reject_or_a_case():
    decisions = [
        decision("a", "HOLD", ["velocity"]),
        decision("b", "REJECT", ["restricted_list"]),
        decision("c", "APPROVE", ["splitting"], opens_case=True),
        decision("d", "APPROVE", ["shared_device"]),
        decision("e"),
    ]
    labels = [label(t, True, "MIXED") for t in "abcde"]

    [row] = metrics.pattern_coverage(decisions, labels)

    assert (row.frauds, row.detected, row.missed) == (5, 3, 2)
    assert row.detection_rate == Decimal("0.6000")


def test_top_rule_is_the_one_that_detects_most_ties_alphabetical():
    decisions = [
        decision("a", "HOLD", ["velocity", "shared_device"]),
        decision("b", "HOLD", ["velocity"]),
        decision("c", "HOLD", ["mule"]),
        decision("d", "HOLD", ["mule"]),
        decision("e", "APPROVE", ["shared_device"]),  # missed: does not count
        decision("f", "APPROVE", ["shared_device"]),
    ]
    labels = [label(t, True, "P") for t in "abcdef"]

    [row] = metrics.pattern_coverage(decisions, labels)

    assert row.top_rule == "mule"  # mule 2, velocity 2: alphabetical


def test_a_pattern_never_detected_has_no_top_rule():
    [row] = metrics.pattern_coverage([decision("a")], [label("a", True, "MULE")])

    assert (row.detected, row.detection_rate, row.top_rule) == (
        0,
        Decimal("0.0000"),
        None,
    )


def test_legitimate_labels_have_no_pattern_row():
    rows = metrics.pattern_coverage(
        [decision("a"), decision("b", "HOLD", ["velocity"])],
        [label("a", False), label("b", True)],
    )

    assert [(r.pattern, r.frauds) for r in rows] == [("UNKNOWN", 1)]


def test_false_positive_examples_are_the_largest_legitimate_amounts():
    decisions = [decision(t, "HOLD", ["velocity"]) for t in "abcdefg"]
    labels = [label("a", True)] + [label(t, False) for t in "bcdefg"]
    amounts = {t: Decimal(i * 10) for i, t in enumerate("abcdefg")}

    examples = metrics.false_positive_examples(decisions, labels, amounts)

    assert [e["transaction_id"] for e in examples["velocity"]] == list("gfedc")


def test_expected_rule_hits_count_where_the_label_expects_the_rule():
    decisions = [
        decision("a", "HOLD", ["velocity"]),
        decision("b"),
        decision("c"),
    ]
    labels = [
        Label("a", "generator", "VELOCITY", True, "velocity"),
        Label("b", "generator", "VELOCITY", True, "velocity"),
        Label("c", "generator", "VELOCITY", True, None),  # part of the burst
    ]

    assert metrics.expected_rule_hits(decisions, labels) == {
        "velocity": {"expected": 2, "fired": 1}
    }


# --- Against the fixture day ------------------------------------------------------


def _fixture_history():
    events = {}
    for path in sorted((FIXTURES / "raw" / "decisiones").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            events.setdefault(e["transaction"]["id"], e)
    day = {
        t: e
        for t, e in events.items()
        if e["transaction"]["transaction_date"].startswith(DAY.isoformat())
    }
    return events, day


def _engine_decisions(events):
    return [
        ReplayDecision(
            transaction_id=t,
            decision=e["decision"]["decision"],
            rules_triggered=tuple(e["decision"]["rules_triggered"]),
            risk_score=e["decision"]["risk_score"],
            opens_case=e["decision"]["opens_case"],
            rules_version=e["decision"]["rules_version"],
        )
        for t, e in events.items()
    ]


def test_the_metrics_give_the_answer_key(expected):
    _, day = _fixture_history()
    decisions, labels = _engine_decisions(day), generator_labels(str(LABELS))

    rules = metrics.rule_metrics(decisions, labels, default_catalog())
    patterns = metrics.pattern_coverage(decisions, labels)

    assert _plain(rules) == _sorted_q2(expected["q2"])
    assert _plain(patterns) == expected["q3"]


def _sorted_q2(rows):
    keys = (
        "rule label_source hits true_positives false_positives precision "
        "false_positive_rate rule_version"
    ).split()
    return [{k: r[k] for k in keys} for r in sorted(rows, key=lambda r: r["rule"])]


def test_the_command_replays_and_measures_the_history():
    events, day = _fixture_history()
    transactions = [TransactionRequest(**e["transaction"]) for e in events.values()]
    security = [
        SecurityEventRequest(**json.loads(x))
        for x in (FIXTURES / "security_events.jsonl").read_text().splitlines()
    ]
    day_labels = [
        lb for lb in generator_labels(str(LABELS)) if lb.transaction_id in day
    ]

    result = metrics.measure(
        default_catalog(),
        transactions,
        day_labels,
        ReferenceData.from_fixtures(FIXTURES),
        security,
    )

    assert result["rules_version"] == "0"
    assert result["transactions"] == len(events)
    assert result["labeled"] == len(day_labels)
    assert result["rule_metrics"] == metrics.rule_metrics(
        _engine_decisions(day), day_labels, default_catalog()
    )
    examples = result["false_positive_examples"]["shared_device"]
    assert len(examples) == 2  # the two false positives of q2
    assert examples[0]["amount_usd"] >= examples[1]["amount_usd"]


def test_current_catalog_without_the_rules_api_is_the_code_defaults():
    from sqlalchemy.exc import OperationalError

    from shared.db import SessionLocal

    try:
        with SessionLocal() as session:
            snapshot = metrics.current_catalog(session)
    except OperationalError:
        pytest.skip("PostgreSQL is not available")

    assert snapshot.rules  # the latest version, or the code defaults


def test_write_raw_leaves_the_rows_for_the_etl(tmp_path):
    rows = metrics.rule_metrics(
        [decision("a", "HOLD", ["velocity"])], [label("a", True, source="paysim")]
    )

    written = metrics.write_raw(
        {"rule_metrics": rows, "pattern_coverage": []}, str(tmp_path), "kaggle"
    )

    path = tmp_path / "raw" / "metrics" / "kaggle" / "rule_metrics.jsonl"
    assert written["rule_metrics"] == str(path)
    assert json.loads(path.read_text()) == {
        "rule": "velocity",
        "label_source": "paysim",
        "hits": 1,
        "true_positives": 1,
        "false_positives": 0,
        "precision": "1.0000",
        "false_positive_rate": None,
        "rule_version": None,
        "rules_version": "0",
    }


# --- The Spark builder with a Kaggle replay ----------------------------------------


def test_the_etl_adds_the_kaggle_replay_to_the_views(spark, lake, tmp_path, expected):
    raw = tmp_path / "raw-root"
    shutil.copytree(FIXTURES / "raw", raw / "raw")
    output = tmp_path / "lake"
    shutil.copytree(lake, output)
    kaggle = [
        decision("k1", "HOLD", ["velocity"], version="2"),
        decision("k2", "APPROVE", version="2"),
        decision("k3", "HOLD", ["velocity"], version="1"),  # an older catalog
    ]
    kaggle_labels = [
        label("k1", True, "kaggle_paysim_TRANSFER", "paysim"),
        label("k2", False, source="paysim"),
        label("k3", True, "kaggle_paysim_TRANSFER", "paysim"),
    ]
    metrics.write_raw(
        {
            "rule_metrics": metrics.rule_metrics(kaggle, kaggle_labels),
            "pattern_coverage": metrics.pattern_coverage(kaggle, kaggle_labels),
        },
        str(raw),
        "kaggle",
    )

    written = build_metrics.build(spark, DAY, str(raw), str(output))
    views.register_tables(spark, str(output))

    assert written == {
        "rule_metrics": len(expected["q2"]) + 2,
        "pattern_coverage": len(expected["q3"]) + 2,
    }
    for view in ("q2", "q3"):
        rows = [r.asDict() for r in views.run_view(spark, view).collect()]
        control = [r.asDict() for r in views.run_control(spark, view).collect()]
        assert sorted(map(str, rows)) == sorted(map(str, control)), view
        paysim = [r for r in rows if r["label_source"] == "paysim"]
        assert len(paysim) == 1, view  # only the latest catalog (2)
    [q2] = [
        r.asDict()
        for r in views.run_view(spark, "q2").collect()
        if r["label_source"] == "paysim"
    ]
    assert (q2["rule"], q2["hits"], q2["precision"]) == (
        "velocity",
        1,
        Decimal("1.0000"),
    )
