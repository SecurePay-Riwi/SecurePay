"""Load test of the decision engine at 50, 150 and 300 tx/s (HU-60).

    uv run --group load locust -f infra/load/locustfile.py --headless \
        --host https://<ALB> --csv results/run

Each simulated core sends one transaction per second, so users = tx/s.
The shape holds each step of STEPS (50 sustained, 150, 300 peak) for
STEP_SECONDS and stops. The transactions come from transactions.py
(the seed's accounts, every type), dated now. Locust's numbers are seen from the client and include the
network; the 200 ms limit is judged on the load balancer's
TargetResponseTime and the engine's decision log (dashboard of HU-59).

Variables: LOAD_STEPS ("50,150,300"), LOAD_STEP_SECONDS (300),
LOAD_VERIFY_TLS ("false": dev's certificate is self-signed).
"""

import json
import os
import random
from collections import Counter
from datetime import UTC, datetime

from locust import FastHttpUser, LoadTestShape, constant_throughput, events, task
from transactions import transaction

STEPS = [int(n) for n in os.getenv("LOAD_STEPS", "50,150,300").split(",")]
STEP_SECONDS = int(os.getenv("LOAD_STEP_SECONDS", "300"))
VERIFY_TLS = os.getenv("LOAD_VERIFY_TLS", "false").lower() == "true"

DECISIONS = Counter()


class Core(FastHttpUser):
    """The wallet's core: one transaction per second."""

    wait_time = constant_throughput(1)
    insecure = not VERIFY_TLS

    def on_start(self):
        self.rng = random.Random()

    @task
    def decide(self):
        body = transaction(self.rng, datetime.now(UTC))
        with self.client.post(
            "/transactions", json=body, name=body["type"], catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return
            decision = response.json()
            DECISIONS[
                "default" if decision.get("by_default") else decision["decision"]
            ] += 1


@events.test_stop.add_listener
def print_decisions(**_):
    """How the engine answered: default decisions answered in time but
    without the rules (cache or rules timed out), so they count apart."""
    print(json.dumps({"decisions": dict(DECISIONS)}))


class Steps(LoadTestShape):
    """Each step of STEPS for STEP_SECONDS, reached in about 10 seconds."""

    def tick(self):
        step = int(self.get_run_time() // STEP_SECONDS)
        if step >= len(STEPS):
            return None
        users = STEPS[step]
        return users, max(1, users // 10)
