"""Scenarios of the interactive demo on the documentation site.

    uv run python -m services.analytics.demo

Writes doc-website/static/demo/scenarios.json (format_version 1): a few
fixed stories, each decided by the engine's own rules through the replay
in memory (replay.decide_all, the code default catalog, the fixed
2026-10-01 rates), plus the same stories decided with one threshold
changed. The page only reads this file; it never decides anything.

Fixed dates and uuid5 ids: two runs write the same bytes on any system.
services/analytics/tests/test_demo.py fails when the committed file is
not what the engine gives today.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from services.analytics.replay import ReferenceData, decide_all
from services.decision_engine import currency
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from shared.rule_catalog import DEFAULT_RULES, CatalogSnapshot, RuleEntry

FORMAT_VERSION = 1
OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "doc-website"
    / "static"
    / "demo"
    / "scenarios.json"
)
DAY = date(2026, 10, 5)
CATALOG_CREATED_AT = datetime(2026, 10, 1, tzinfo=UTC)
CASE_DUE_MINUTES = 240
EVIDENCE = "cases/<yyyy>/<mm>/<case_id>.json (S3 Object Lock, 10 years)"
QUEUES = ["cases", "history", "analytics"]
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://securepay-riwi.github.io/SecurePay/demo")

# Display names for the page; the catalog has codes, not titles.
RULE_TITLES = {
    "restricted_list": "Restricted list",
    "velocity": "Velocity",
    "mule": "Mule account",
    "shared_device": "Shared device",
    "splitting": "Splitting",
    "account_takeover": "Account takeover",
    "default_timeout": "Default decision",
}

# The threshold control: one parameter changed at a time (contract C3).
THRESHOLDS = (
    ("velocity", "limit", (3, 5, 8)),
    ("default_timeout", "limit_usd", (20, 50, 100)),
)


def uid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, second, tzinfo=UTC)


# --- Reference data: what the cache has -------------------------------------------

# name: (currency, document). Invented people; never data of the seed.
ACCOUNTS = {
    "alice": ("USD", "2000000001"),
    "bob": ("USD", "2000000002"),
    "carol": ("USD", "2000000003"),
    "dave": ("USD", "2000000004"),
    "erin": ("USD", "2000000005"),
    "frank": ("USD", "2000000006"),
    "mule": ("USD", "2000000007"),
    "sender1": ("USD", "2000000008"),
    "sender2": ("USD", "2000000009"),
    "sender3": ("USD", "2000000010"),
    "shared1": ("USD", "2000000011"),
    "shared2": ("USD", "2000000012"),
    "shared3": ("USD", "2000000013"),
    "shared4": ("USD", "2000000014"),
    "henry": ("USD", "2000000015"),
    "ivan": ("USD", "2000000016"),
    "julia": ("COP", "2000000017"),
    "kevin": ("COP", "2000000018"),
}
LISTED = ("dave",)
MERCHANTS = ("corner_shop",)
# Not in ACCOUNTS: opened after the nightly cache load, so the engine
# cannot find it and answers with RN-01's default decision.
NOT_IN_CACHE = "newcomer"

BALANCE = {"USD": Decimal("5000.00"), "COP": Decimal("20000000.00")}


def acct(name: str) -> str:
    return uid(f"account:{name}")


def reference() -> ReferenceData:
    return ReferenceData(
        accounts={
            acct(name): {
                "currency": cur,
                "user_id": uid(f"user:{name}"),
                "document": doc,
                "status": "activa",
            }
            for name, (cur, doc) in ACCOUNTS.items()
        },
        merchants={uid(f"merchant:{m}") for m in MERCHANTS},
        restricted_documents={ACCOUNTS[n][1] for n in LISTED},
    )


# --- Scenarios --------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    label: str
    request: TransactionRequest | SecurityEventRequest

    @property
    def when(self) -> datetime:
        if isinstance(self.request, TransactionRequest):
            return self.request.transaction_date
        return self.request.event_date


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    rn: str
    story: str
    steps: tuple[Step, ...]  # the last transaction is the protagonist

    @property
    def transactions(self) -> list[TransactionRequest]:
        return [
            s.request for s in self.steps if isinstance(s.request, TransactionRequest)
        ]

    @property
    def security_events(self) -> list[SecurityEventRequest]:
        return [
            s.request for s in self.steps if isinstance(s.request, SecurityEventRequest)
        ]

    @property
    def protagonist(self) -> TransactionRequest:
        return max(self.transactions, key=lambda t: (t.transaction_date, str(t.id)))


def tx(
    name: str,
    kind: str,
    when: datetime,
    amount: str,
    *,
    src: str | None = None,
    dst: str | None = None,
    merchant: str | None = None,
    channel: str = "APP",
    device: str | None = None,
    balance: str | None = None,
) -> TransactionRequest:
    """One TransactionRequest in the main account's currency."""
    main = src or dst
    cur = ACCOUNTS.get(main, ("USD",))[0]
    value = Decimal(amount)
    body = {
        "id": uid(f"tx:{name}"),
        "type": kind,
        "channel": channel,
        "amount": amount,
        "currency": cur,
        "device_id": uid(f"device:{device or main}"),
        "transaction_date": when.isoformat(),
    }
    if src:
        before = Decimal(balance) if balance else BALANCE[cur]
        body |= {
            "source_account_id": acct(src),
            "source_balance_before": str(before),
            "source_balance_after": str(before - value),
        }
    if dst:
        before = BALANCE[ACCOUNTS[dst][0]]
        body |= {
            "destination_account_id": acct(dst),
            "destination_balance_before": str(before),
            "destination_balance_after": str(before + value),
        }
    if merchant:
        body["merchant_id"] = uid(f"merchant:{merchant}")
    return TransactionRequest(**body)


def security_event(
    name: str, kind: str, when: datetime, account: str, device: str
) -> SecurityEventRequest:
    return SecurityEventRequest(
        id=uid(f"sec:{name}"),
        type=kind,
        user_id=uid(f"user:{account}"),
        account_id=acct(account),
        device_id=uid(f"device:{device}"),
        event_date=when,
    )


def scenarios() -> list[Scenario]:
    velocity_minutes = (0, 1, 3, 4, 6, 8)
    return [
        Scenario(
            id="normal",
            title="Everyday transfer",
            rn="RN-01",
            story="Alice sends Bob USD 28. Nothing unusual: no rule fires.",
            steps=(
                Step(
                    "Alice sends Bob USD 28",
                    tx("normal", "P2P", at(9), "28.00", src="alice", dst="bob"),
                ),
            ),
        ),
        Scenario(
            id="over_limit",
            title="Default decision",
            rn="RN-01",
            story=(
                "A brand-new account sends USD 75 before the nightly cache load "
                "includes it. The rules cannot run, so the default decision "
                "applies: approve below USD 50, hold from USD 50 up."
            ),
            steps=(
                Step(
                    "A new account sends Bob USD 75",
                    tx(
                        "over_limit",
                        "P2P",
                        at(9, 30),
                        "75.00",
                        src=NOT_IN_CACHE,
                        dst="bob",
                    ),
                ),
            ),
        ),
        Scenario(
            id="restricted_list",
            title="Restricted list",
            rn="RN-06",
            story=(
                "Carol sends USD 120 to Dave, whose document is on a sanctions "
                "list. The engine rejects it and compliance gets a report."
            ),
            steps=(
                Step(
                    "Carol sends Dave USD 120",
                    tx("restricted", "P2P", at(10), "120.00", src="carol", dst="dave"),
                ),
            ),
        ),
        Scenario(
            id="velocity",
            title="Velocity",
            rn="RN-02",
            story=(
                "Erin sends six small transfers to Frank in 8 minutes. More "
                "than 5 in 10 minutes holds the sixth."
            ),
            steps=tuple(
                Step(
                    f"Transfer {i + 1} of 6: USD 15 to Frank",
                    tx(
                        f"velocity_{i}",
                        "P2P",
                        at(11, minute),
                        "15.00",
                        src="erin",
                        dst="frank",
                    ),
                )
                for i, minute in enumerate(velocity_minutes)
            ),
        ),
        Scenario(
            id="mule",
            title="Mule account",
            rn="RN-03",
            story=(
                "Three different people send money to one account, and 20 minutes "
                "after the last one it withdraws 85 % of its balance."
            ),
            steps=(
                *(
                    Step(
                        f"Sender {i + 1} transfers USD 300",
                        tx(
                            f"mule_in_{i}",
                            "P2P",
                            at(12, 4 * i),
                            "300.00",
                            src=f"sender{i + 1}",
                            dst="mule",
                        ),
                    )
                    for i in range(3)
                ),
                Step(
                    "The account withdraws USD 765 of USD 900",
                    tx(
                        "mule_out",
                        "RETIRO",
                        at(12, 28),
                        "765.00",
                        src="mule",
                        channel="CAJERO",
                        balance="900.00",
                    ),
                ),
            ),
        ),
        Scenario(
            id="shared_device",
            title="Shared device",
            rn="RN-04",
            story=(
                "Four different accounts pay at the same shop from the same "
                "tablet. The fourth raises the risk score, but it is approved."
            ),
            steps=tuple(
                Step(
                    f"Account {i} pays USD 12 from the shared tablet",
                    tx(
                        f"shared_{i}",
                        "QR",
                        at(13, 10 * (i - 1)),
                        "12.00",
                        src=f"shared{i}",
                        merchant="corner_shop",
                        device="shared_tablet",
                    ),
                )
                for i in range(1, 5)
            ),
        ),
        Scenario(
            id="splitting",
            title="Splitting",
            rn="RN-05",
            story=(
                "Henry withdraws USD 4,000 three times in one day. Each is below "
                "the USD 10,000 reporting limit, together they are above it."
            ),
            steps=tuple(
                Step(
                    f"Withdrawal {i + 1} of 3: USD 4,000",
                    tx(
                        f"split_{i}",
                        "RETIRO",
                        at(hour),
                        "4000.00",
                        src="henry",
                        channel="CAJERO",
                        balance="15000.00",
                    ),
                )
                for i, hour in enumerate((8, 14, 20))
            ),
        ),
        Scenario(
            id="account_takeover",
            title="Account takeover",
            rn="RN-07",
            story=(
                "Ivan's account logs in from a new phone and changes its "
                "password. 15 minutes later it sends USD 350."
            ),
            steps=(
                Step(
                    "Device changed to a new phone",
                    security_event(
                        "ato_device", "DEVICE_CHANGE", at(15), "ivan", "ivan_new"
                    ),
                ),
                Step(
                    "Password changed",
                    security_event(
                        "ato_password", "PASSWORD_CHANGE", at(15, 5), "ivan", "ivan_new"
                    ),
                ),
                Step(
                    "Ivan's account sends Bob USD 350",
                    tx(
                        "takeover",
                        "P2P",
                        at(15, 20),
                        "350.00",
                        src="ivan",
                        dst="bob",
                        device="ivan_new",
                    ),
                ),
            ),
        ),
        Scenario(
            id="currency",
            title="Other currency",
            rn="RN-11",
            story=(
                "Julia sends Kevin COP 95,000. The engine reports it in USD with "
                "the day's rate and keeps the original amount."
            ),
            steps=(
                Step(
                    "Julia sends Kevin COP 95,000",
                    tx("currency", "P2P", at(16), "95000.00", src="julia", dst="kevin"),
                ),
            ),
        ),
    ]


# --- Deciding ---------------------------------------------------------------------


def catalog(changes: dict[str, dict] | None = None) -> CatalogSnapshot:
    """The code default catalog, with `changes` (code -> params) applied."""
    changes = changes or {}
    rules = [
        RuleEntry(**{**r.model_dump(), "params": {**r.params, **changes[r.code]}})
        if r.code in changes
        else r
        for r in DEFAULT_RULES
    ]
    return CatalogSnapshot(
        version=0, created_at=CATALOG_CREATED_AT, author="code", rules=rules
    )


def decide(scenario: Scenario, snapshot: CatalogSnapshot) -> dict[str, dict]:
    """transaction id -> the engine's decision, without processed_at. Each
    scenario starts with an empty history."""
    decided = decide_all(
        snapshot, scenario.transactions, reference(), scenario.security_events
    )
    result = {}
    for t, decision in decided:
        decision = dict(decision)
        decision.pop("processed_at", None)
        result[str(t.id)] = decision
    return result


def after(decision: dict) -> dict:
    """What happens after the protagonist's decision (the real system)."""
    opens_case = decision["opens_case"]
    return {
        "queues": QUEUES,
        "opens_case": opens_case,
        "case_due_minutes": CASE_DUE_MINUTES if opens_case else None,
        "compliance_report": "restricted_list" in decision["rules_triggered"],
        "evidence": EVIDENCE if opens_case else None,
    }


def scenario_json(scenario: Scenario, decisions: dict[str, dict]) -> dict:
    steps = []
    for step in sorted(scenario.steps, key=lambda s: (s.when, str(s.request.id))):
        item = {
            "kind": "transaction"
            if isinstance(step.request, TransactionRequest)
            else "security_event",
            "label": step.label,
            "request": step.request.model_dump(mode="json", exclude_none=True),
        }
        if item["kind"] == "transaction":
            item["decision"] = decisions[str(step.request.id)]
        steps.append(item)
    return {
        "id": scenario.id,
        "title": scenario.title,
        "rn": scenario.rn,
        "story": scenario.story,
        "steps": steps,
        "after": after(decisions[str(scenario.protagonist.id)]),
    }


def catalog_json(snapshot: CatalogSnapshot) -> dict:
    return {
        "version": str(snapshot.version),
        "rules": [
            {
                "code": r.code,
                "title": RULE_TITLES.get(r.code, r.code),
                "rn": r.rn,
                "action": r.action,
                "opens_case": r.opens_case,
                "score": r.score,
                "enabled": r.enabled,
                "description": r.description,
                "params": r.typed_params().model_dump(mode="json"),
            }
            for r in snapshot.rules
        ],
    }


def protagonist_decisions(all_scenarios, snapshot) -> dict[str, str]:
    return {
        s.id: decide(s, snapshot)[str(s.protagonist.id)]["decision"]
        for s in all_scenarios
    }


def threshold_variants(all_scenarios, default_decisions) -> list[dict]:
    variants = []
    for code, param, values in THRESHOLDS:
        default = Decimal(str(catalog().get(code).params[param]))
        options = []
        for value in values:
            decisions = protagonist_decisions(
                all_scenarios, catalog({code: {param: str(value)}})
            )
            options.append(
                {
                    "value": value,
                    "decisions": decisions,
                    "changed": sum(
                        decisions[k] != default_decisions[k] for k in decisions
                    ),
                }
            )
        variants.append(
            {"rule": code, "param": param, "default": int(default), "values": options}
        )
    return variants


def build() -> dict:
    """The content of scenarios.json."""
    currency.load({})  # the fixed 2026-10-01 rates, whatever was loaded before
    snapshot = catalog()
    all_scenarios = scenarios()
    decided = {s.id: decide(s, snapshot) for s in all_scenarios}
    default_decisions = {
        s.id: decided[s.id][str(s.protagonist.id)]["decision"] for s in all_scenarios
    }
    return {
        "format_version": FORMAT_VERSION,
        "generated_from": "services/analytics/demo.py",
        "catalog": catalog_json(snapshot),
        "scenarios": [scenario_json(s, decided[s.id]) for s in all_scenarios],
        "threshold_variants": threshold_variants(all_scenarios, default_decisions),
    }


def render(content: dict) -> str:
    return json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(build()), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
