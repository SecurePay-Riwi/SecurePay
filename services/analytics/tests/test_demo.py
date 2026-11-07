"""The demo's scenarios.json (contract C4): it is what the engine gives
today, every scenario decides what its story says, every request is
valid for the engine, and two builds are the same. No Java, PostgreSQL
or Valkey needed."""

import json

import pytest

from services.analytics import demo
from services.decision_engine import currency
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest

# scenario id -> (decision, rules_triggered, opens_case) of its last transaction
EXPECTED = {
    "normal": ("APPROVE", [], False),
    "over_limit": ("HOLD", ["default_timeout"], False),
    "restricted_list": ("REJECT", ["restricted_list"], True),
    "velocity": ("HOLD", ["velocity"], False),
    "mule": ("HOLD", ["mule"], True),
    "shared_device": ("APPROVE", ["shared_device"], False),
    "splitting": ("HOLD", ["splitting"], True),
    "account_takeover": ("HOLD", ["account_takeover"], False),
    "currency": ("APPROVE", [], False),
}


@pytest.fixture(autouse=True)
def fixed_rates():
    currency.load({})
    yield
    currency.load({})


@pytest.fixture(scope="module")
def built() -> dict:
    return demo.build()


def protagonist(scenario: dict) -> dict:
    return [s for s in scenario["steps"] if s["kind"] == "transaction"][-1]


def test_the_committed_file_is_what_the_engine_gives(built):
    committed = demo.OUTPUT.read_text(encoding="utf-8")
    assert committed == demo.render(built), (
        "run uv run python -m services.analytics.demo "
        "and commit doc-website/static/demo/scenarios.json"
    )


def test_every_scenario_decides_what_its_story_says(built):
    assert [s["id"] for s in built["scenarios"]] == list(EXPECTED)
    for scenario in built["scenarios"]:
        decision = protagonist(scenario)["decision"]
        expected, rules, opens_case = EXPECTED[scenario["id"]]
        got = (
            decision["decision"],
            decision["rules_triggered"],
            decision["opens_case"],
        )
        assert got == (expected, rules, opens_case), scenario["id"]
        assert scenario["after"]["opens_case"] is opens_case
        assert scenario["after"]["compliance_report"] is ("restricted_list" in rules)


def test_the_default_decision_and_the_risk_scores(built):
    by_id = {s["id"]: protagonist(s)["decision"] for s in built["scenarios"]}
    assert by_id["over_limit"]["by_default"] is True
    assert by_id["shared_device"]["risk_score"] == 30
    assert by_id["splitting"]["risk_score"] == 40
    assert by_id["currency"]["usd_rate"] == "3317.65"


def test_every_request_is_valid_for_the_engine(built):
    for scenario in built["scenarios"]:
        for step in scenario["steps"]:
            model = (
                TransactionRequest
                if step["kind"] == "transaction"
                else SecurityEventRequest
            )
            model(**step["request"])
            assert ("decision" in step) is (step["kind"] == "transaction")


def test_steps_are_in_time_order_and_no_decision_has_processed_at(built):
    for scenario in built["scenarios"]:
        times = [
            s["request"].get("transaction_date") or s["request"]["event_date"]
            for s in scenario["steps"]
        ]
        assert times == sorted(times), scenario["id"]
        for step in scenario["steps"]:
            assert "processed_at" not in step.get("decision", {})


def test_threshold_variants_change_only_what_the_rule_decides(built):
    variants = {v["rule"]: v for v in built["threshold_variants"]}
    assert set(variants) == {"velocity", "default_timeout"}
    for variant in variants.values():
        default = next(v for v in variant["values"] if v["value"] == variant["default"])
        assert default["changed"] == 0
    velocity = {v["value"]: v for v in variants["velocity"]["values"]}
    assert velocity[8]["decisions"]["velocity"] == "APPROVE"
    timeout = {v["value"]: v for v in variants["default_timeout"]["values"]}
    assert timeout[100]["decisions"]["over_limit"] == "APPROVE"
    assert timeout[100]["changed"] == 1


def test_two_builds_are_the_same(built):
    assert json.dumps(demo.build(), sort_keys=True) == json.dumps(built, sort_keys=True)
