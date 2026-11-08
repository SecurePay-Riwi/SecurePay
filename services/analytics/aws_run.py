"""Records one run of the demo's stories on AWS for the /aws-run page.

    terraform -chdir=infra/terraform/envs/dev output -json > outputs.json
    uv run python -m services.analytics.aws_run --outputs outputs.json \\
        --user analyst@example.com --password '...' --allow-self-signed

Run it with dev up and an AWS profile that can read CloudWatch, ELB, ECS,
S3 and sign in to Cognito. It sends the demo's stories to the real engine
behind the load balancer with real seed accounts (infra/load/accounts.json),
waits for the Lambdas, follows each decision through the cases API and S3,
reads the run's metrics from CloudWatch and, with --load-test, the last
load test (Locust's CSV plus CloudWatch for each step). It writes
doc-website/static/aws-run/run.json, which the page only reads.

Every transaction gets a new id and the accounts are picked at random, so
two runs never share idempotency keys or history windows. It resolves one
case (the mule's) as LEGITIMATE to show the evidence being locked in S3.
"""

import argparse
import csv
import io
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "doc-website" / "static" / "aws-run" / "run.json"
ACCOUNTS = ROOT / "infra" / "load" / "accounts.json"
LIMIT_MS = 200
QUEUES = ("cases", "history", "analytics")
RESOLVED_STORY = "mule"

# What each story decides with the code catalog (services/analytics/demo.py).
EXPECTED = {
    "normal": "APPROVE",
    "over_limit": "HOLD",
    "restricted_list": "REJECT",
    "velocity": "HOLD",
    "mule": "HOLD",
    "shared_device": "APPROVE",
    "splitting": "HOLD",
    "account_takeover": "HOLD",
    "currency": "APPROVE",
}


# --- The stories, with real accounts --------------------------------------------


@dataclass
class Step:
    kind: str  # "transaction" or "security_event"
    label: str
    body: dict


@dataclass
class Story:
    id: str
    title: str
    rn: str
    main_account: str | None
    steps: list[Step] = field(default_factory=list)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _tx(
    kind: str,
    when: datetime,
    amount: str,
    currency: str,
    *,
    src: str | None = None,
    dst: str | None = None,
    merchant: str | None = None,
    channel: str = "APP",
    device: str,
    balance: str = "5000.00",
) -> dict:
    value = Decimal(amount)
    body = {
        "id": str(uuid.uuid4()),
        "type": kind,
        "channel": channel,
        "amount": amount,
        "currency": currency,
        "device_id": device,
        "transaction_date": _iso(when),
    }
    if src:
        before = Decimal(balance)
        body |= {
            "source_account_id": src,
            "source_balance_before": str(before),
            "source_balance_after": str(before - value),
        }
    if dst:
        body |= {
            "destination_account_id": dst,
            "destination_balance_before": balance,
            "destination_balance_after": str(Decimal(balance) + value),
        }
    if merchant:
        body["merchant_id"] = merchant
    return body


def stories(
    accounts: dict[str, list[str]],
    merchants: list[str],
    now: datetime,
    rng: random.Random,
    listed_account: str | None = None,
) -> tuple[list[Story], list[dict]]:
    """The demo's stories with fresh ids and random seed accounts, dated
    in the recent past so every history window applies. Returns the
    stories and the ones skipped, with why."""
    usd = rng.sample(accounts["USD"], 16)
    cop = rng.sample(accounts["COP"], 2)
    dev = lambda: str(uuid.uuid4())  # noqa: E731 - a new device each time
    ago = lambda minutes: now - timedelta(minutes=minutes)  # noqa: E731
    result: list[Story] = []
    skipped: list[dict] = []

    a, b = usd[0], usd[1]
    result.append(
        Story(
            "normal",
            "Everyday transfer",
            "RN-01",
            a,
            [
                Step(
                    "transaction",
                    "P2P of USD 28",
                    _tx("P2P", ago(1), "28.00", "USD", src=a, dst=b, device=dev()),
                )
            ],
        )
    )

    newcomer = str(uuid.uuid4())  # not in the cache: RN-01's default decision
    result.append(
        Story(
            "over_limit",
            "Default decision",
            "RN-01",
            None,
            [
                Step(
                    "transaction",
                    "P2P of USD 75 from an account not in the cache",
                    _tx(
                        "P2P", ago(1), "75.00", "USD", src=newcomer, dst=b, device=dev()
                    ),
                )
            ],
        )
    )

    if listed_account:
        result.append(
            Story(
                "restricted_list",
                "Restricted list",
                "RN-06",
                usd[2],
                [
                    Step(
                        "transaction",
                        "P2P of USD 120 to a listed owner",
                        _tx(
                            "P2P",
                            ago(1),
                            "120.00",
                            "USD",
                            src=usd[2],
                            dst=listed_account,
                            device=dev(),
                        ),
                    )
                ],
            )
        )
    else:
        skipped.append(
            {
                "id": "restricted_list",
                "reason": "needs an account whose owner is on the restricted list (--listed-account)",
            }
        )

    erin, frank, phone = usd[3], usd[4], dev()
    result.append(
        Story(
            "velocity",
            "Velocity",
            "RN-02",
            erin,
            [
                Step(
                    "transaction",
                    f"Transfer {i + 1} of 6, USD 15",
                    _tx(
                        "P2P",
                        ago(9 - m),
                        "15.00",
                        "USD",
                        src=erin,
                        dst=frank,
                        device=phone,
                    ),
                )
                for i, m in enumerate((0, 1, 3, 4, 6, 8))
            ],
        )
    )

    mule = usd[5]
    mule_steps = [
        Step(
            "transaction",
            f"Sender {i + 1} transfers USD 300",
            _tx(
                "P2P",
                ago(29 - 4 * i),
                "300.00",
                "USD",
                src=usd[6 + i],
                dst=mule,
                device=dev(),
            ),
        )
        for i in range(3)
    ]
    mule_steps.append(
        Step(
            "transaction",
            "Withdraws USD 765 of USD 900",
            _tx(
                "RETIRO",
                ago(1),
                "765.00",
                "USD",
                src=mule,
                channel="CAJERO",
                device=dev(),
                balance="900.00",
            ),
        )
    )
    result.append(Story("mule", "Mule account", "RN-03", mule, mule_steps))

    tablet, shop = dev(), rng.choice(merchants)
    result.append(
        Story(
            "shared_device",
            "Shared device",
            "RN-04",
            usd[12],
            [
                Step(
                    "transaction",
                    f"Account {i + 1} pays USD 12 from the same tablet",
                    _tx(
                        "QR",
                        ago(8 - 2 * i),
                        "12.00",
                        "USD",
                        src=acct,
                        merchant=shop,
                        device=tablet,
                    ),
                )
                for i, acct in enumerate(usd[9:13])
            ],
        )
    )

    henry, atm = usd[13], dev()
    result.append(
        Story(
            "splitting",
            "Splitting",
            "RN-05",
            henry,
            [
                Step(
                    "transaction",
                    f"Withdrawal {i + 1} of 3, USD 4,000",
                    _tx(
                        "RETIRO",
                        ago(minutes),
                        "4000.00",
                        "USD",
                        src=henry,
                        channel="CAJERO",
                        device=atm,
                        balance="15000.00",
                    ),
                )
                for i, minutes in enumerate((360, 180, 1))
            ],
        )
    )

    ivan, new_phone = usd[14], dev()
    events = [
        Step(
            "security_event",
            label,
            {
                "id": str(uuid.uuid4()),
                "type": kind,
                # The engine keys security events by account and never reads
                # user_id; accounts.json has no owners, so a new id goes here.
                "user_id": str(uuid.uuid4()),
                "account_id": ivan,
                "device_id": new_phone,
                "event_date": _iso(ago(minutes)),
            },
        )
        for kind, label, minutes in (
            ("DEVICE_CHANGE", "Device changed", 20),
            ("PASSWORD_CHANGE", "Password changed", 15),
        )
    ]
    result.append(
        Story(
            "account_takeover",
            "Account takeover",
            "RN-07",
            ivan,
            [
                *events,
                Step(
                    "transaction",
                    "P2P of USD 350 from the new phone",
                    _tx(
                        "P2P",
                        ago(1),
                        "350.00",
                        "USD",
                        src=ivan,
                        dst=usd[15],
                        device=new_phone,
                    ),
                ),
            ],
        )
    )

    result.append(
        Story(
            "currency",
            "Other currency",
            "RN-11",
            cop[0],
            [
                Step(
                    "transaction",
                    "P2P of COP 95,000",
                    _tx(
                        "P2P",
                        ago(1),
                        "95000.00",
                        "COP",
                        src=cop[0],
                        dst=cop[1],
                        device=dev(),
                        balance="20000000.00",
                    ),
                )
            ],
        )
    )
    return result, skipped


def load_accounts(path: Path = ACCOUNTS) -> tuple[dict[str, list[str]], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_currency: dict[str, list[str]] = {}
    for item in data["accounts"]:
        by_currency.setdefault(item["currency"], []).append(item["id"])
    return by_currency, data["merchants"]


# --- Talking to AWS -------------------------------------------------------------


class Http:
    """JSON over HTTPS. Dev's load balancer has a self-signed certificate
    unless domain_name is set, hence `verify`."""

    def __init__(self, verify: bool = True, timeout: float = 15.0):
        import httpx

        self._client = httpx.Client(verify=verify, timeout=timeout)

    def request(
        self, method: str, url: str, body: dict | None = None, token: str | None = None
    ) -> tuple[int, Any, float]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        started = time.perf_counter()
        response = self._client.request(method, url, json=body, headers=headers)
        elapsed = (time.perf_counter() - started) * 1000
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload, elapsed


class Aws:
    """The few AWS calls the run needs, behind one object the tests fake."""

    def __init__(self, region: str):
        import boto3

        session = boto3.session.Session(region_name=region)
        self._cw = session.client("cloudwatch")
        self._elb = session.client("elbv2")
        self._ecs = session.client("ecs")
        self._s3 = session.client("s3")
        self._cognito = session.client("cognito-idp")

    def token(self, client_id: str, user: str, password: str) -> str:
        reply = self._cognito.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": user, "PASSWORD": password},
        )
        return reply["AuthenticationResult"]["IdToken"]

    def balancer(self, dns_name: str) -> tuple[str, str]:
        """(load balancer, target group) dimension values for CloudWatch."""
        for lb in self._elb.describe_load_balancers()["LoadBalancers"]:
            if lb["DNSName"].lower() == dns_name.lower():
                arn = lb["LoadBalancerArn"]
                tg = self._elb.describe_target_groups(LoadBalancerArn=arn)
                tg_arn = tg["TargetGroups"][0]["TargetGroupArn"]
                return arn.split(":loadbalancer/")[1], tg_arn.split(":")[-1]
        raise SystemExit(f"No load balancer named {dns_name}")

    def running_tasks(self, cluster: str, service: str = "engine") -> int:
        reply = self._ecs.describe_services(cluster=cluster, services=[service])
        return reply["services"][0]["runningCount"]

    def metrics(self, queries: list[dict], start: datetime, end: datetime) -> dict:
        """id -> list of (timestamp, value), oldest first."""
        result: dict[str, list] = {}
        for i in range(0, len(queries), 500):
            kwargs = {
                "MetricDataQueries": queries[i : i + 500],
                "StartTime": start,
                "EndTime": end,
                "ScanBy": "TimestampAscending",
            }
            while True:
                reply = self._cw.get_metric_data(**kwargs)
                for item in reply["MetricDataResults"]:
                    result.setdefault(item["Id"], []).extend(
                        zip(item["Timestamps"], item["Values"], strict=True)
                    )
                if "NextToken" not in reply:
                    break
                kwargs["NextToken"] = reply["NextToken"]
        return result

    def lock(self, bucket: str, key: str) -> dict:
        head = self._s3.head_object(Bucket=bucket, Key=key)
        until = head.get("ObjectLockRetainUntilDate")
        return {
            "mode": head.get("ObjectLockMode"),
            "retain_until": _iso(until) if until else None,
        }

    def read_text(self, url: str) -> str:
        bucket, key = url.removeprefix("s3://").split("/", 1)
        return self._s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()


# --- CloudWatch queries -----------------------------------------------------------


def _metric(qid, namespace, name, dims, stat, period) -> dict:
    return {
        "Id": qid,
        "MetricStat": {
            "Metric": {
                "Namespace": namespace,
                "MetricName": name,
                "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()],
            },
            "Period": period,
            "Stat": stat,
        },
    }


def run_queries(ctx: dict, period: int) -> list[dict]:
    lb, tg = ctx["lb"], ctx["tg"]
    tgd = {"LoadBalancer": lb, "TargetGroup": tg}
    queries = [
        _metric(f"lat_{s}", "AWS/ApplicationELB", "TargetResponseTime", tgd, s, period)
        for s in ("p50", "p95", "p99")
    ]
    queries += [
        _metric("requests", "AWS/ApplicationELB", "RequestCount", tgd, "Sum", period),
        _metric("fallbacks", ctx["namespace"], "FallbackDecisions", {}, "Sum", period),
    ]
    for q in QUEUES:
        queries.append(
            _metric(
                f"queue_{q}",
                "AWS/SQS",
                "NumberOfMessagesReceived",
                {"QueueName": f"{ctx['prefix']}-{q}"},
                "Sum",
                period,
            )
        )
    for i, fn in enumerate(sorted(ctx["lambdas"])):
        for stat_name in ("Invocations", "Errors"):
            queries.append(
                _metric(
                    f"fn{i}_{stat_name.lower()}",
                    "AWS/Lambda",
                    stat_name,
                    {"FunctionName": fn},
                    "Sum",
                    period,
                )
            )
    return queries


def _total(series: list) -> float:
    return sum(v for _, v in series)


def _ms(series: list) -> float | None:
    values = [v for _, v in series]
    return round(max(values) * 1000, 1) if values else None


def run_metrics(aws, ctx: dict, start: datetime, end: datetime) -> dict:
    seconds = max(60, int((end - start).total_seconds()) // 60 * 60 + 60)
    data = aws.metrics(run_queries(ctx, seconds), start, end)
    lambdas = {}
    for i, fn in enumerate(sorted(ctx["lambdas"])):
        lambdas[fn] = {
            "invocations": int(_total(data.get(f"fn{i}_invocations", []))),
            "errors": int(_total(data.get(f"fn{i}_errors", []))),
        }
    return {
        "latency_ms": {s: _ms(data.get(f"lat_{s}", [])) for s in ("p50", "p95", "p99")},
        "requests": int(_total(data.get("requests", []))),
        "fallback_decisions": int(_total(data.get("fallbacks", []))),
        "queues": {q: int(_total(data.get(f"queue_{q}", []))) for q in QUEUES},
        "lambdas": lambdas,
    }


# --- The load test ----------------------------------------------------------------


def _parse_time(value: str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def load_steps(history_csv: str) -> list[dict]:
    """The steps of Locust's *_stats_history.csv: one per user count (users =
    tx/s in infra/load/locustfile.py), with its first and last second."""
    steps: list[dict] = []
    for row in csv.DictReader(io.StringIO(history_csv)):
        if row.get("Name") != "Aggregated" or not row.get("User Count"):
            continue
        rate, at = int(row["User Count"]), _parse_time(row["Timestamp"])
        if rate == 0:
            continue
        if steps and steps[-1]["rate"] == rate:
            steps[-1]["to"] = at
        else:
            steps.append({"rate": rate, "from": at, "to": at})
    return [s for s in steps if (s["to"] - s["from"]).total_seconds() >= 60]


def load_client(stats_csv: str) -> dict:
    """Locust's totals at the client, from *_stats.csv's Aggregated row."""
    for row in csv.DictReader(io.StringIO(stats_csv)):
        if row.get("Name") == "Aggregated":
            return {
                "requests": int(row["Request Count"]),
                "failures": int(row["Failure Count"]),
                "p50": float(row["50%"]),
                "p99": float(row["99%"]),
            }
    return {}


def load_test(aws, ctx: dict, history_csv: str, stats_csv: str) -> dict:
    steps = load_steps(history_csv)
    if not steps:
        raise SystemExit("The load test history has no step of a minute or more")
    lb, tg = ctx["lb"], ctx["tg"]
    tgd = {"LoadBalancer": lb, "TargetGroup": tg}
    ecs = {"ClusterName": ctx["cluster"], "ServiceName": "engine"}
    result = []
    for step in steps:
        start = step["from"].replace(second=0, microsecond=0) + timedelta(minutes=1)
        end = step["to"].replace(second=0, microsecond=0)
        if end <= start:
            start, end = step["from"], step["to"]
        period = max(60, int((end - start).total_seconds()) // 60 * 60)
        queries = [
            _metric(
                f"lat_{s}", "AWS/ApplicationELB", "TargetResponseTime", tgd, s, period
            )
            for s in ("p50", "p95", "p99")
        ] + [
            _metric(
                "requests", "AWS/ApplicationELB", "RequestCount", tgd, "Sum", period
            ),
            _metric(
                "e5xx",
                "AWS/ApplicationELB",
                "HTTPCode_Target_5XX_Count",
                tgd,
                "Sum",
                period,
            ),
            _metric(
                "l5xx",
                "AWS/ApplicationELB",
                "HTTPCode_ELB_5XX_Count",
                {"LoadBalancer": lb},
                "Sum",
                period,
            ),
            _metric(
                "fallbacks", ctx["namespace"], "FallbackDecisions", {}, "Sum", period
            ),
            _metric("cpu_avg", "AWS/ECS", "CPUUtilization", ecs, "Average", period),
            _metric("cpu_max", "AWS/ECS", "CPUUtilization", ecs, "Maximum", period),
        ]
        data = aws.metrics(queries, start, end)
        requests = int(_total(data.get("requests", [])))
        cpu_avg = [v for _, v in data.get("cpu_avg", [])]
        cpu_max = [v for _, v in data.get("cpu_max", [])]
        result.append(
            {
                "rate": step["rate"],
                "requests": requests,
                "p50": _ms(data.get("lat_p50", [])),
                "p95": _ms(data.get("lat_p95", [])),
                "p99": _ms(data.get("lat_p99", [])),
                "default_pct": round(
                    100 * _total(data.get("fallbacks", [])) / requests, 2
                )
                if requests
                else None,
                "http_5xx": int(
                    _total(data.get("e5xx", [])) + _total(data.get("l5xx", []))
                ),
                "cpu_avg": round(sum(cpu_avg) / len(cpu_avg), 1) if cpu_avg else None,
                "cpu_max": round(max(cpu_max), 1) if cpu_max else None,
            }
        )
    first, last = steps[0]["from"], steps[-1]["to"]
    series = aws.metrics(
        [_metric("p99", "AWS/ApplicationELB", "TargetResponseTime", tgd, "p99", 60)],
        first,
        last,
    ).get("p99", [])
    rate_at = lambda t: next(  # noqa: E731
        (s["rate"] for s in steps if s["from"] <= t <= s["to"] + timedelta(minutes=1)),
        None,
    )
    return {
        "source": "recorded",
        "label": f"Recorded {_iso(first)[:16].replace('T', ' ')} UTC",
        "limit_ms": LIMIT_MS,
        "steps": result,
        "client": load_client(stats_csv),
        "series": [
            {"minute": _iso(t), "p99": round(v * 1000, 1), "rate": rate_at(t)}
            for t, v in series
        ],
        "notes": None,
    }


# --- The run ------------------------------------------------------------------


def _main_decision(results: list[dict]) -> dict:
    return [r for r in results if r["kind"] == "transaction"][-1]


def send(http, base: str, story: Story) -> list[dict]:
    results = []
    for step in story.steps:
        path = "/transactions" if step.kind == "transaction" else "/security-events"
        status, reply, ms = http.request("POST", base + path, step.body)
        if status >= 400:
            raise SystemExit(f"{story.id}: {path} answered {status}: {reply}")
        results.append(
            {"kind": step.kind, "label": step.label, "reply": reply, "ms": round(ms, 1)}
        )
    return results


def _since(start: str, end: str | None) -> int | None:
    if not end:
        return None
    a = datetime.fromisoformat(start.replace("Z", "+00:00"))
    b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return round((b - a).total_seconds() * 1000)


def find_cases(http, api: str, token: str, ids: set[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for page in range(1, 21):
        status, reply, _ = http.request(
            "GET", f"{api}/cases?status=OPEN&size=100&page={page}", token=token
        )
        if status != 200:
            raise SystemExit(f"GET /cases answered {status}: {reply}")
        for item in reply.get("items", []):
            if item["transaction_id"] in ids:
                found[item["transaction_id"]] = item
        if len(found) == len(ids) or not reply.get("items"):
            break
    return found


def trace(http, aws, ctx: dict, token: str, story: Story, results: list) -> list[dict]:
    """What the system did with the story's decision, in order, with the
    milliseconds since the engine decided (both clocks are AWS's)."""
    main = _main_decision(results)
    decision = main["reply"]
    decided_at = decision["processed_at"]
    steps = [
        {
            "label": "Engine answered",
            "at_ms": 0,
            "detail": f"{decision['decision']} in {main['ms']} ms at the client",
        }
    ]
    if story.main_account:
        status, reply, _ = http.request(
            "GET",
            f"{ctx['api']}/accounts/{story.main_account}/transactions?days=1",
            token=token,
        )
        rows = reply.get("items", []) if status == 200 else []
        written = any(r["transaction_id"] == decision["transaction_id"] for r in rows)
        steps.append(
            {
                "label": "Account history written" if written else "History not found",
                "at_ms": None,
                "detail": "history consumer, RDS",
            }
        )
    case = ctx["cases"].get(decision["transaction_id"])
    if case:
        steps.append(
            {
                "label": "Case opened",
                "at_ms": _since(decided_at, case["created_at"]),
                "detail": f"cases consumer, RDS, due in 4 h ({case['id']})",
            }
        )
        if story.id == RESOLVED_STORY:
            steps += resolve(http, aws, ctx, token, case, decided_at)
    elif decision.get("opens_case"):
        steps.append(
            {"label": "Case not found", "at_ms": None, "detail": "cases consumer"}
        )
    return steps


def resolve(http, aws, ctx, token, case, decided_at) -> list[dict]:
    status, reply, _ = http.request(
        "POST",
        f"{ctx['api']}/cases/{case['id']}/resolution",
        {"outcome": "LEGITIMATE", "note": "Recorded run of the web demo"},
        token=token,
    )
    if status != 200:
        return [{"label": f"Resolution failed ({status})", "at_ms": None, "detail": ""}]
    steps = [
        {
            "label": "Analyst resolved it",
            "at_ms": _since(decided_at, reply.get("resolved_at")),
            "detail": f"LEGITIMATE, final decision {reply.get('final_decision')}",
        }
    ]
    key = reply.get("evidence_key")
    if key and ctx.get("evidence_bucket"):
        lock = aws.lock(ctx["evidence_bucket"], key)
        steps.append(
            {
                "label": "Evidence locked",
                "at_ms": None,
                "detail": f"s3://…/{key}, Object Lock {lock['mode']} until {lock['retain_until']}",
            }
        )
    return steps


def record(
    http,
    aws,
    outputs: dict,
    user: str,
    password: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    settle_seconds: int = 90,
    metrics_delay: int = 180,
    rng: random.Random | None = None,
    listed_account: str | None = None,
    accounts: tuple[dict, list] | None = None,
    region: str = "us-east-2",
) -> dict:
    value = lambda name: outputs[name]["value"]  # noqa: E731
    lb, tg = aws.balancer(value("alb_dns_name"))
    cluster = value("ecs_cluster_name")
    prefix = cluster  # the cluster is named like every resource: securepay-<env>
    ctx = {
        "lb": lb,
        "tg": tg,
        "cluster": cluster,
        "prefix": prefix,
        "namespace": f"SecurePay/{prefix}",
        "api": value("api_url").rstrip("/"),
        "lambdas": list((value("lambda_function_names") or {}).values()),
        "evidence_bucket": (value("bucket_names") or {}).get("evidence"),
    }
    by_currency, merchants = accounts or load_accounts()
    start = now()
    story_list, skipped = stories(
        by_currency, merchants, start, rng or random.Random(), listed_account
    )
    base = f"https://{value('alb_dns_name')}"
    sent = {s.id: send(http, base, s) for s in story_list}
    tasks = aws.running_tasks(cluster)

    sleep(settle_seconds)  # the Lambdas read the queues in batches
    token = aws.token(value("user_pool_client_id"), user, password)
    ids = {
        _main_decision(r)["reply"]["transaction_id"]
        for r in sent.values()
        if _main_decision(r)["reply"].get("opens_case")
    }
    ctx["cases"] = find_cases(http, ctx["api"], token, ids) if ids else {}

    scenario_rows = []
    for story in story_list:
        results = sent[story.id]
        decision = _main_decision(results)["reply"]
        scenario_rows.append(
            {
                "id": story.id,
                "title": story.title,
                "rn": story.rn,
                "expected": EXPECTED[story.id],
                "decision": decision["decision"],
                "matches": decision["decision"] == EXPECTED[story.id],
                "rules_triggered": decision["rules_triggered"],
                "risk_score": decision["risk_score"],
                "by_default": decision["by_default"],
                "amount_usd": decision.get("amount_usd"),
                "steps": [
                    {
                        "label": r["label"],
                        "ms": r["ms"],
                        "decision": r["reply"].get("decision")
                        if r["kind"] == "transaction"
                        else None,
                    }
                    for r in results
                ],
                "trace": trace(http, aws, ctx, token, story, results),
            }
        )
    end = now()
    sleep(metrics_delay)  # CloudWatch publishes a minute's numbers late
    return {
        "recorded_at": _iso(start),
        "environment": prefix,
        "region": region,
        "engine_tasks": tasks,
        "window": {"from": _iso(start), "to": _iso(end)},
        "scenarios": scenario_rows,
        "skipped": skipped,
        "metrics": run_metrics(
            aws, ctx, start - timedelta(minutes=1), end + timedelta(minutes=1)
        ),
    }


def render(content: dict) -> str:
    return json.dumps(content, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--outputs", required=True, help="terraform output -json")
    parser.add_argument("--user", required=True, help="a Cognito user (api_users)")
    parser.add_argument("--password", required=True)
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--listed-account", help="an account whose owner is listed")
    parser.add_argument(
        "--allow-self-signed",
        action="store_true",
        help="dev's load balancer has a self-signed certificate",
    )
    parser.add_argument("--load-test", help="folder or s3:// prefix with run_*.csv")
    parser.add_argument("--skip-run", action="store_true", help="only the load test")
    parser.add_argument("--settle-seconds", type=int, default=90)
    args = parser.parse_args(argv)

    outputs = json.loads(Path(args.outputs).read_text(encoding="utf-8"))
    aws = Aws(args.region)
    http = Http(verify=not args.allow_self_signed)
    current = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}

    run = current.get("run")
    if not args.skip_run:
        run = record(
            http,
            aws,
            outputs,
            args.user,
            args.password,
            settle_seconds=args.settle_seconds,
            listed_account=args.listed_account,
            region=args.region,
        )
    load = current.get("load_test")
    if args.load_test:
        read = (
            aws.read_text
            if args.load_test.startswith("s3://")
            else lambda p: Path(p).read_text(encoding="utf-8")
        )
        prefix = args.load_test.rstrip("/")
        lb, tg = aws.balancer(outputs["alb_dns_name"]["value"])
        cluster = outputs["ecs_cluster_name"]["value"]
        ctx = {
            "lb": lb,
            "tg": tg,
            "cluster": cluster,
            "namespace": f"SecurePay/{cluster}",
        }
        load = load_test(
            aws,
            ctx,
            read(f"{prefix}/run_stats_history.csv"),
            read(f"{prefix}/run_stats.csv"),
        )
    content = {
        "format_version": FORMAT_VERSION,
        "generated_from": "services/analytics/aws_run.py",
        "run": run,
        "load_test": load,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(content), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
