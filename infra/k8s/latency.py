"""The same requests against two engines, to compare them (HU-58).

    uv run python infra/k8s/latency.py http://127.0.0.1:8000 http://127.0.0.1:8080

Sends `--requests` transactions (smoke-transaction.json with a new id
each, `--workers` at a time) to each URL in turn and prints the p50, p95
and p99 latency seen by the client, the errors and the decisions. Only the
standard library, so it runs from any computer with Python. The two
engines share Valkey, so every run writes the same account's history:
after five transfers in ten minutes the velocity rule answers HOLD, which
is still a full decision and is measured the same.
"""

import argparse
import json
import math
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TRANSACTION = (
    Path(__file__).resolve().parents[1]
    / "terraform"
    / "envs"
    / "dev"
    / "smoke-transaction.json"
)


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile (the one of analytics-model.mdx)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def one(url: str, body: dict, timeout: float) -> tuple[float, str]:
    """(milliseconds, decision or error) of one POST /transactions."""
    data = json.dumps({**body, "id": str(uuid.uuid4())}).encode()
    request = urllib.request.Request(
        f"{url.rstrip('/')}/transactions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            outcome = json.loads(response.read())["decision"]
    except urllib.error.HTTPError as error:
        outcome = f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError) as error:
        outcome = type(error).__name__
    return (time.perf_counter() - started) * 1000, outcome


def measure(url: str, requests: int, workers: int, timeout: float = 5) -> dict:
    body = json.loads(TRANSACTION.read_text(encoding="utf-8"))
    one(url, body, timeout)  # warm-up: connections, the catalog, the rates
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: one(url, body, timeout), range(requests)))
    seconds = time.perf_counter() - started
    times = [ms for ms, outcome in results if outcome in ("APPROVE", "HOLD", "REJECT")]
    return {
        "url": url,
        "requests": requests,
        "per_second": round(requests / seconds, 1),
        "p50_ms": round(percentile(times, 0.50), 1),
        "p95_ms": round(percentile(times, 0.95), 1),
        "p99_ms": round(percentile(times, 0.99), 1),
        "outcomes": dict(Counter(outcome for _, outcome in results)),
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Compare the engine's latency.")
    parser.add_argument("urls", nargs="+", help="engine base URLs")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args(argv)
    for url in args.urls:
        print(json.dumps(measure(url, args.requests, args.workers)))


if __name__ == "__main__":
    main()
