"""The recorder of the /aws-run page (services/analytics/aws_run.py), with a
fake engine, cases API and AWS: no network, no credentials."""

import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from services.analytics import aws_run
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
ACCOUNTS = (
    {
        "USD": [f"00000000-0000-4000-8000-{i:012d}" for i in range(40)],
        "COP": [f"00000000-0000-4000-9000-{i:012d}" for i in range(5)],
    },
    ["11111111-1111-4111-8111-111111111111"],
)
OUTPUTS = {
    "alb_dns_name": {"value": "securepay-dev-alb-1.us-east-2.elb.amazonaws.com"},
    "ecs_cluster_name": {"value": "securepay-dev"},
    "api_url": {"value": "https://api.example.test/"},
    "user_pool_client_id": {"value": "client"},
    "lambda_function_names": {
        "value": {
            "cases": "securepay-dev-cases-consumer",
            "alerts": "securepay-dev-alerts",
        }
    },
    "bucket_names": {"value": {"evidence": "securepay-dev-evidence-123"}},
}
# What the fake engine answers for the last transaction of each story.
ANSWERS = {
    "normal": ("APPROVE", [], False),
    "over_limit": ("HOLD", ["default_timeout"], False),
    "velocity": ("HOLD", ["velocity"], False),
    "mule": ("HOLD", ["mule"], True),
    "shared_device": ("APPROVE", ["shared_device"], False),
    "splitting": ("HOLD", ["splitting"], True),
    "account_takeover": ("HOLD", ["account_takeover"], False),
    "currency": ("APPROVE", [], False),
}


class FakeSystem:
    """The engine, the cases API and AWS, answering from ANSWERS."""

    def __init__(self, stories):
        self.last = {s.id: s.steps[-1].body["id"] for s in stories}
        self.story_of = {v: k for k, v in self.last.items()}
        self.calls = []

    # Http
    def request(self, method, url, body=None, token=None):
        self.calls.append((method, url))
        if url.endswith("/transactions"):
            story = self.story_of.get(body["id"])
            decision, rules, opens = ANSWERS[story] if story else ("APPROVE", [], False)
            return (
                200,
                {
                    "transaction_id": body["id"],
                    "decision": decision,
                    "rules_triggered": rules,
                    "opens_case": opens,
                    "risk_score": 30 if rules == ["shared_device"] else 0,
                    "by_default": story == "over_limit",
                    "amount_usd": body["amount"],
                    "processed_at": "2026-11-08T15:00:00.100Z",
                },
                12.5,
            )
        if url.endswith("/security-events"):
            return 200, {"recorded": True}, 4.0
        if "/cases?" in url:
            items = [
                {
                    "id": f"case-{story}",
                    "transaction_id": tx,
                    "created_at": "2026-11-08T15:00:01.600Z",
                }
                for story, tx in self.last.items()
                if ANSWERS.get(story, ("", [], False))[2]
            ]
            return 200, {"items": items}, 30.0
        if url.endswith("/resolution"):
            return (
                200,
                {
                    "resolved_at": "2026-11-08T15:02:00.100Z",
                    "final_decision": "APPROVE",
                    "evidence_key": "cases/2026/11/case-mule.json",
                },
                40.0,
            )
        if "/transactions?days=1" in url:
            items = [{"transaction_id": tx} for tx in self.last.values()]
            return 200, {"items": items}, 20.0
        raise AssertionError(url)

    # Aws
    def balancer(self, dns):
        return "app/securepay-dev-alb/abc", "targetgroup/securepay-dev-engine/def"

    def running_tasks(self, cluster):
        return 4

    def token(self, client_id, user, password):
        return "token"

    def lock(self, bucket, key):
        return {"mode": "COMPLIANCE", "retain_until": "2036-11-08T15:02:00Z"}

    def metrics(self, queries, start, end):
        t = start
        values = {
            "lat_p50": 0.012,
            "lat_p95": 0.02,
            "lat_p99": 0.05,
            "p99": 0.05,
            "requests": 21,
            "fallbacks": 1,
            "cpu_avg": 4.5,
            "cpu_max": 6.6,
        }
        return {
            q["Id"]: [(t, values.get(q["Id"], 3))]
            for q in queries
            if q["Id"] in values or q["Id"].startswith(("queue_", "fn", "e5", "l5"))
        }


def build():
    return aws_run.stories(
        *ACCOUNTS, NOW, random.Random(7), listed_account=ACCOUNTS[0]["USD"][-1]
    )


def test_every_request_is_valid_for_the_engine():
    stories, skipped = build()
    assert skipped == []
    assert [s.id for s in stories] == list(aws_run.EXPECTED)
    for story in stories:
        for step in story.steps:
            model = (
                TransactionRequest
                if step.kind == "transaction"
                else SecurityEventRequest
            )
            model(**step.body)


def test_the_stories_fit_their_rule_windows():
    stories, _ = build()
    by_id = {s.id: s for s in stories}
    dates = lambda s: [  # noqa: E731
        datetime.fromisoformat(
            (st.body.get("transaction_date") or st.body["event_date"]).replace(
                "Z", "+00:00"
            )
        )
        for st in s.steps
    ]
    for story in stories:
        assert all(d < NOW for d in dates(story)), story.id
        assert dates(story) == sorted(dates(story)), story.id
    velocity = dates(by_id["velocity"])
    assert len(velocity) == 6 and velocity[-1] - velocity[0] < timedelta(minutes=10)
    mule = dates(by_id["mule"])
    assert mule[-1] - mule[0] < timedelta(minutes=30)
    senders = {st.body["source_account_id"] for st in by_id["mule"].steps[:3]}
    assert len(senders) == 3
    devices = {st.body["device_id"] for st in by_id["shared_device"].steps}
    accounts = {st.body["source_account_id"] for st in by_id["shared_device"].steps}
    assert len(devices) == 1 and len(accounts) == 4


def test_every_run_uses_new_ids_and_skips_the_list_without_an_account():
    one, _ = aws_run.stories(*ACCOUNTS, NOW, random.Random(1))
    two, skipped = aws_run.stories(*ACCOUNTS, NOW, random.Random(1))
    ids = lambda ss: {st.body["id"] for s in ss for st in s.steps}  # noqa: E731
    assert not ids(one) & ids(two)
    assert [s["id"] for s in skipped] == ["restricted_list"]


def test_a_recorded_run_follows_each_decision():
    stories, _ = aws_run.stories(*ACCOUNTS, NOW, random.Random(3))
    fake = FakeSystem(stories)
    original = aws_run.stories
    aws_run.stories = lambda *a, **k: (
        stories,
        [{"id": "restricted_list", "reason": "x"}],
    )
    try:
        run = aws_run.record(
            fake,
            fake,
            OUTPUTS,
            "analyst@example.test",
            "secret",
            now=lambda: NOW,
            sleep=lambda s: None,
            accounts=ACCOUNTS,
        )
    finally:
        aws_run.stories = original
    by_id = {s["id"]: s for s in run["scenarios"]}
    assert all(s["matches"] for s in run["scenarios"])
    mule = [t["label"] for t in by_id["mule"]["trace"]]
    assert mule == [
        "Engine answered",
        "Account history written",
        "Case opened",
        "Analyst resolved it",
        "Evidence locked",
    ]
    assert by_id["mule"]["trace"][2]["at_ms"] == 1500
    assert "COMPLIANCE" in by_id["mule"]["trace"][-1]["detail"]
    assert "Case opened" not in [t["label"] for t in by_id["normal"]["trace"]]
    assert by_id["over_limit"]["trace"] == by_id["over_limit"]["trace"][:1]
    assert run["engine_tasks"] == 4
    assert run["metrics"]["latency_ms"] == {"p50": 12.0, "p95": 20.0, "p99": 50.0}
    assert set(run["metrics"]["queues"]) == {"cases", "history", "analytics"}
    assert run["skipped"][0]["id"] == "restricted_list"
    assert (
        "GET",
        "https://api.example.test/cases?status=OPEN&size=100&page=1",
    ) in fake.calls


HISTORY = """Timestamp,User Count,Type,Name,Requests/s,Failures/s,50%,95%,99%
1762531200,0,,Aggregated,0,0,0,0,0
1762531260,50,,Aggregated,50,0,20,30,60
1762531500,50,,Aggregated,50,0,20,30,60
1762531510,150,,Aggregated,150,0,25,40,90
1762531800,150,,Aggregated,150,0,25,40,90
1762531805,300,,Aggregated,300,0,30,100,170
1762531830,300,,Aggregated,300,0,30,100,170
"""
STATS = """Type,Name,Request Count,Failure Count,50%,99%
POST,/transactions,149486,4,29,170
,Aggregated,149486,4,29,170
"""


def test_load_steps_are_the_user_counts_held_a_minute():
    steps = aws_run.load_steps(HISTORY)
    assert [s["rate"] for s in steps] == [50, 150]
    assert aws_run.load_client(STATS) == {
        "requests": 149486,
        "failures": 4,
        "p50": 29.0,
        "p99": 170.0,
    }


def test_a_recorded_load_test_has_one_row_per_step():
    fake = FakeSystem([])
    ctx = {"lb": "app/x/1", "tg": "targetgroup/y/2", "cluster": "c", "namespace": "n"}
    load = aws_run.load_test(fake, ctx, HISTORY, STATS)
    assert load["source"] == "recorded" and load["limit_ms"] == 200
    assert [s["rate"] for s in load["steps"]] == [50, 150]
    assert load["steps"][0]["p99"] == 50.0
    assert load["steps"][0]["default_pct"] == round(100 / 21, 2)
    assert load["series"][0]["p99"] == 50.0


def test_the_committed_file_has_the_page_s_shape():
    content = json.loads(aws_run.OUTPUT.read_text(encoding="utf-8"))
    assert content["format_version"] == aws_run.FORMAT_VERSION
    load = content["load_test"]
    assert load["limit_ms"] == aws_run.LIMIT_MS
    assert [s["rate"] for s in load["steps"]] == [50, 150, 300]
    for step in load["steps"]:
        assert {"rate", "requests", "p50", "p95", "p99"} <= set(step)
    run = content["run"]
    if run is not None:
        assert {s["id"] for s in run["scenarios"]} <= set(aws_run.EXPECTED)


@pytest.mark.parametrize("value", ["2026-11-08T15:00:00Z", "2026-11-08T15:00:00+00:00"])
def test_since_reads_both_utc_forms(value):
    assert aws_run._since(value, "2026-11-08T15:00:01.5Z") == 1500
