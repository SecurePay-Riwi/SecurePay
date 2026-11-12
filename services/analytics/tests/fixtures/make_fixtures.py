"""Builds the analytics fixtures: one small day (2026-10-05) of the raw
layer and its answer key, expected_views.json.

    PYTHONPATH=. uv run python services/analytics/tests/fixtures/make_fixtures.py

The decisions are not written by hand: the transactions below go through
the engine's own rules (services/analytics/replay.py, the code default
catalog, the fixed 2026-10-01 rates), so every rule fires as it would in
the engine. The answer key is computed here in plain Python, from the
definitions of the views (doc-website/docs/reference/analytics-model.mdx),
never from the SQL it checks.

The files are committed; run this again only to change the day, and
with Habith (three people's tests depend on them). README.md lists what
the day has.
"""

import json
import math
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from services.analytics.replay import ReferenceData, decide_all
from services.decision_engine import currency
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from shared.events import evento_decision
from shared.reconciliation import AGE_RANGES, partner_for
from shared.rule_catalog import default_catalog

HERE = Path(__file__).parent
DAY = date(2026, 10, 5)
# When the nightly export ran (C6): the cases' state is the one of this moment.
EXPORTED_AT = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)
CASE_DUE_MINUTES = 240
NS = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://securepay-riwi.github.io/analytics-fixtures"
)


def uid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def at(hour: int, minute: int = 0, second: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


# --- Reference data -------------------------------------------------------------

ACCOUNTS = {
    # name: (currency, document)
    "n1": ("COP", "1000000001"),
    "n2": ("USD", "1000000002"),
    "n3": ("EUR", "1000000003"),
    "n4": ("JPY", "1000000004"),
    "v": ("COP", "1000000005"),
    "mu": ("USD", "1000000006"),
    "s1": ("USD", "1000000007"),
    "s2": ("USD", "1000000008"),
    "s3": ("USD", "1000000009"),
    "sp": ("USD", "1000000010"),
    "sp2": ("EUR", "1000000011"),
    "at": ("EUR", "1000000012"),
    "r": ("COP", "1000000013"),
    "r2": ("USD", "1000000014"),
    "d1": ("COP", "1000000015"),
    "d2": ("USD", "1000000016"),
    "d3": ("EUR", "1000000017"),
    "d4": ("JPY", "1000000018"),
}
LISTED = ("r", "r2")
MERCHANTS = ("m1", "m2")  # m3 is not in the cache: default decision
SHARED_DEVICE = "dv"


def acct(name: str) -> str:
    return uid(f"account:{name}")


def device(name: str) -> str:
    return uid(f"device:{name}")


def reference() -> dict:
    return {
        "accounts": {
            acct(n): {
                "currency": c,
                "user_id": uid(f"user:{n}"),
                "document": doc,
                "status": "activa",
            }
            for n, (c, doc) in ACCOUNTS.items()
        },
        "merchants": sorted(uid(f"merchant:{m}") for m in MERCHANTS),
        "restricted_documents": sorted(ACCOUNTS[n][1] for n in LISTED),
    }


# --- The day's transactions ------------------------------------------------------

BALANCE = {"COP": "90000000.00", "USD": "50000.00", "EUR": "40000.00", "JPY": "9000000"}


def _minus(balance: str, amount: str, cur: str) -> str:
    places = Decimal(1).scaleb(-2 if cur != "JPY" else 0)
    return str((Decimal(balance) - Decimal(amount)).quantize(places))


def _plus(balance: str, amount: str, cur: str) -> str:
    places = Decimal(1).scaleb(-2 if cur != "JPY" else 0)
    return str((Decimal(balance) + Decimal(amount)).quantize(places))


def tx(
    name,
    kind,
    when,
    amount,
    *,
    src=None,
    dst=None,
    merchant=None,
    channel="APP",
    dev=None,
    cur=None,
    src_before=None,
):
    """One TransactionRequest; currency is the main account's."""
    main = src or dst
    cur = cur or ACCOUNTS.get(main, ("USD",))[0]
    body = {
        "id": uid(f"tx:{name}"),
        "type": kind,
        "channel": channel,
        "amount": amount,
        "currency": cur,
        "device_id": device(dev or main),
        "transaction_date": when.isoformat(),
    }
    if src:
        before = src_before or BALANCE[cur]
        body |= {
            "source_account_id": acct(src),
            "source_balance_before": before,
            "source_balance_after": _minus(before, amount, cur),
        }
    if dst:
        dcur = ACCOUNTS.get(dst, (cur,))[0]
        body |= {
            "destination_account_id": acct(dst),
            "destination_balance_before": BALANCE[dcur],
            "destination_balance_after": _plus(BALANCE[dcur], amount, dcur)
            if dcur == cur
            else BALANCE[dcur],
        }
    if merchant:
        body["merchant_id"] = uid(f"merchant:{merchant}")
    return name, TransactionRequest(**body)


def transactions() -> list[tuple[str, TransactionRequest]]:
    t = [
        # Window edges: the day before (excluded) and a late one (included).
        tx(
            "edge_before",
            "RECARGA",
            at(23, 50, day=DAY - timedelta(days=1)),
            "30.00",
            dst="n2",
        ),
        # Normal operations of every type, currency and channel.
        tx("n_topup_app", "RECARGA", at(1), "150000.00", dst="n1"),
        tx(
            "n_topup_corr",
            "RECARGA",
            at(1, 30),
            "80.00",
            dst="n2",
            channel="CORRESPONSAL",
        ),
        tx("n_qr_eur", "QR", at(2), "35.50", src="n3", merchant="m1"),
        tx("n_atm_jpy", "RETIRO", at(2, 30), "12000", src="n4", channel="CAJERO"),
        tx("n_p2p_web", "P2P", at(3), "20.00", src="n2", dst="n1", channel="WEB"),
        tx("n_qr_cop", "QR", at(3, 30), "45000.00", src="n1", merchant="m2"),
        tx(
            "n_corr_cop", "RETIRO", at(4), "200000.00", src="n1", channel="CORRESPONSAL"
        ),
        tx("n_topup_web", "RECARGA", at(4, 30), "100.00", dst="n3", channel="WEB"),
        # RN-06: a listed source (on the shared device) and a listed destination.
        tx(
            "restricted_src",
            "P2P",
            at(9),
            "50000.00",
            src="r",
            dst="n1",
            dev=SHARED_DEVICE,
        ),
        tx("restricted_dst", "P2P", at(12), "60.00", src="n2", dst="r2", channel="WEB"),
    ]
    # RN-02: six transfers in five minutes, the sixth is held.
    t += [
        tx(f"velocity_{i}", "P2P", at(10, i), "20000.00", src="v", dst="n1")
        for i in range(6)
    ]
    # RN-03: three senders, then 95 % of the balance withdrawn.
    t += [
        tx(f"mule_in_{i}", "P2P", at(11, 5 * i), "300.00", src=f"s{i + 1}", dst="mu")
        for i in range(3)
    ]
    t.append(
        tx(
            "mule_out",
            "RETIRO",
            at(11, 20),
            "950.00",
            src="mu",
            channel="CAJERO",
            src_before="1000.00",
        )
    )
    # RN-04: the shared device reaches more than 3 accounts (r, d1, d2, d3, d4).
    t += [
        tx(
            f"shared_{i}",
            "QR",
            at(12, 10 * i),
            amount,
            src=f"d{i}",
            merchant="m1",
            dev=SHARED_DEVICE,
        )
        for i, amount in ((1, "30000.00"), (2, "8.00"), (3, "7.50"), (4, "900"))
    ]
    # RN-05: two splits of three withdrawals each (USD and EUR).
    t += [
        tx(f"split_{i}", "RETIRO", when, amount, src="sp", channel="CAJERO")
        for i, (when, amount) in enumerate(
            ((at(13), "3500.00"), (at(16), "3600.00"), (at(20), "3700.00"))
        )
    ]
    t += [
        tx(f"split2_{i}", "RETIRO", when, amount, src="sp2", channel="CORRESPONSAL")
        for i, (when, amount) in enumerate(
            ((at(14), "3000.00"), (at(17), "3100.00"), (at(23, 30), "3200.00"))
        )
    ]
    # RN-07: device and password change, then a QR payment above USD 200.
    t.append(tx("takeover", "QR", at(15, 30), "400.00", src="at", merchant="m2"))
    # RN-01: an account and a merchant missing in the cache (not labeled).
    t.append(
        tx("default_ghost", "P2P", at(18), "10.00", src="ghost", dst="n1", cur="USD")
    )
    t.append(tx("default_merchant", "QR", at(18, 30), "75.00", src="n2", merchant="m3"))
    # Late: decided on the day, arrives after midnight (raw fecha=2026-10-06).
    t.append(tx("late_atm", "RETIRO", at(23, 58), "5000", src="n4", channel="CAJERO"))
    return t


def security_events() -> list[SecurityEventRequest]:
    return [
        SecurityEventRequest(
            id=uid(f"sec:{kind}"),
            type=kind,
            user_id=uid("user:at"),
            account_id=acct("at"),
            device_id=device("at-new"),
            event_date=when,
        )
        for kind, when in (("DEVICE_CHANGE", at(15)), ("PASSWORD_CHANGE", at(15, 10)))
    ]


# name prefix -> (pattern, is_fraud); names not here are labeled legitimate,
# except UNLABELED.
PATTERNS = {
    "velocity_": ("VELOCITY", True),
    "mule_": ("MULE", True),
    "shared_": ("SHARED_DEVICE", False),
    "split": ("SPLITTING", True),
    "takeover": ("ACCOUNT_TAKEOVER", True),
    "restricted_": ("RESTRICTED_LIST", True),
}
EXPECTED_RULE = {
    "velocity_5": "velocity",
    "mule_out": "mule",
    "shared_1": "shared_device",
    "shared_2": "shared_device",
    "shared_3": "shared_device",
    "shared_4": "shared_device",
    "split_2": "splitting",
    "split2_2": "splitting",
    "takeover": "account_takeover",
    "restricted_src": "restricted_list",
    "restricted_dst": "restricted_list",
}
UNLABELED = ("default_ghost", "default_merchant", "edge_before")


def label_of(name: str) -> dict | None:
    if name in UNLABELED:
        return None
    pattern, fraud = next(
        (v for prefix, v in PATTERNS.items() if name.startswith(prefix)), (None, False)
    )
    return {
        "pattern": pattern,
        "pattern_id": f"{pattern}-0-1" if pattern else None,
        "is_fraud": fraud,
        "expected_rule": EXPECTED_RULE.get(name),
    }


# --- Writing ---------------------------------------------------------------------


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
        encoding="utf-8",
    )


def money(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def ratio(num: int, den: int) -> str | None:
    if den == 0:
        return None
    return str((Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"), ROUND_HALF_UP))


def build():
    currency.load({})  # the fixed 2026-10-01 rates
    named = transactions()
    names = {str(t.id): n for n, t in named}
    ref = reference()
    decided = decide_all(
        default_catalog(),
        [t for _, t in named],
        ReferenceData(
            ref["accounts"], set(ref["merchants"]), set(ref["restricted_documents"])
        ),
        security_events(),
    )
    events = {}
    for t, result in decided:
        # Deterministic processing time: 50 ms after the transaction.
        result["processed_at"] = (
            t.transaction_date + timedelta(milliseconds=50)
        ).isoformat()
        events[names[str(t.id)]] = evento_decision(t.model_dump(mode="json"), result)

    (HERE / "reference.json").write_text(
        json.dumps(ref, indent=2) + "\n", encoding="utf-8"
    )
    write_jsonl(
        HERE / "security_events.jsonl",
        [e.model_dump(mode="json") for e in security_events()],
    )

    # raw/decisiones: by arrival day, in two files, with repeated lines.
    order = list(events)
    late = ["late_atm"]
    on_day = [n for n in order if n not in late]
    half = len(on_day) // 2
    raw = HERE / "raw" / "decisiones"
    write_jsonl(
        raw / "fecha=2026-10-05" / "part-0001.jsonl", [events[n] for n in on_day[:half]]
    )
    write_jsonl(
        raw / "fecha=2026-10-05" / "part-0002.jsonl",
        [events[n] for n in on_day[half:]]
        + [events["n_topup_app"], events["mule_out"]],
    )
    write_jsonl(raw / "fecha=2026-10-06" / "part-0001.jsonl", [events[n] for n in late])

    # raw/labels: as the generator writes them (a security line, a duplicate).
    label_lines = []
    for n in order:
        label = label_of(n)
        if label is not None:
            label_lines.append(
                {
                    "id": str(events[n]["transaction"]["id"]),
                    "kind": "transaction",
                    **label,
                }
            )
        if n == "takeover":
            label_lines.insert(
                -1,
                {
                    "id": str(security_events()[0].id),
                    "kind": "security",
                    **label_of("takeover"),
                },
            )
    label_lines.append({**label_lines[1], "duplicate": True, "defects": ["DUPLICATE"]})
    write_jsonl(
        HERE / "raw" / "labels" / "fecha=2026-10-05" / "labels.jsonl", label_lines
    )

    cases, case_events = make_cases(events)
    write_jsonl(HERE / "raw" / "cases" / "fecha=2026-10-05" / "cases.jsonl", cases)
    write_jsonl(
        HERE / "raw" / "cases" / "fecha=2026-10-05" / "case_events.jsonl", case_events
    )
    differences, runs, matched = make_reconciliation(events)
    write_jsonl(
        HERE / "raw" / "reconciliation" / "fecha=2026-10-05" / "differences.jsonl",
        differences,
    )
    write_jsonl(
        HERE / "raw" / "reconciliation" / "fecha=2026-10-05" / "runs.jsonl", runs
    )
    write_jsonl(
        HERE / "raw" / "reconciliation" / "fecha=2026-10-05" / "matched.jsonl",
        matched,
    )

    day_events = {
        n: e
        for n, e in events.items()
        if datetime.fromisoformat(e["transaction"]["transaction_date"]).date() == DAY
    }
    labels = {
        str(e["transaction"]["id"]): label_of(n)
        for n, e in day_events.items()
        if label_of(n)
    }
    expected = {
        "day": DAY.isoformat(),
        "q1": expected_q1(day_events),
        "q2": expected_q2(day_events, labels),
        "q3": expected_q3(day_events, labels),
        "q4": expected_q4(cases, case_events),
        "q5": expected_q5(differences, matched),
        "q6": expected_q6(day_events, labels, cases),
    }
    (HERE / "expected_views.json").write_text(
        json.dumps(expected, indent=2) + "\n", encoding="utf-8"
    )
    return events, expected


# --- Cases and reconciliation (the state of the nightly export) -------------------

# name of the transaction -> what happened to its case by EXPORTED_AT.
CASE_STORY = {
    "restricted_src": {"assign": (20, "ana"), "resolve": (90, "ana", "FRAUD")},
    "restricted_dst": {
        "escalate": 243,
        "assign": (245, "luis"),
        "resolve": (250, "luis", "LEGITIMATE"),
    },
    "mule_out": {"escalate": 243},
    "split_2": {"assign": (10, "ana"), "resolve": (30, "ana", "FRAUD")},
    "split2_2": {},
}


def make_cases(events):
    cases, case_events = [], []
    event_id = 0

    def add(case_id, kind, actor, when, data):
        nonlocal event_id
        event_id += 1
        case_events.append(
            {
                "id": event_id,
                "case_id": case_id,
                "type": kind,
                "actor": actor,
                "at": when.isoformat(),
                "data": data,
            }
        )

    for name, story in CASE_STORY.items():
        event = events[name]
        tx_, d = event["transaction"], event["decision"]
        assert d["opens_case"], name
        created = datetime.fromisoformat(d["processed_at"]) + timedelta(seconds=1)
        due = created + timedelta(minutes=CASE_DUE_MINUTES)
        case_id = uid(f"case:{name}")
        row = {
            "id": case_id,
            "transaction_id": tx_["id"],
            "account_id": tx_.get("source_account_id") or tx_["destination_account_id"],
            "decision": d["decision"],
            "decision_reason": d["decision_reason"],
            "rules_triggered": d["rules_triggered"],
            "rules_version": d["rules_version"],
            "rule_versions": d["rule_versions"],
            "risk_score": d["risk_score"],
            "amount": tx_["amount"],
            "currency": tx_["currency"],
            "amount_usd": d["amount_usd"],
            "usd_rate": d["usd_rate"],
            "rate_date": d["rate_date"],
            "transaction_date": tx_["transaction_date"],
            "transaction": tx_,
            "status": "OPEN",
            "assignee": None,
            "created_at": created.isoformat(),
            "due_at": due.isoformat(),
            "escalated_at": None,
            "resolved_at": None,
            "resolved_by": None,
            "outcome": None,
            "final_decision": None,
            "resolution_note": None,
            "evidence_key": None,
        }
        add(case_id, "CREATED", "system", created, {})
        steps = []
        if "escalate" in story:
            steps.append((story["escalate"], "escalate"))
        if "assign" in story:
            steps.append((story["assign"][0], "assign"))
        if "resolve" in story:
            steps.append((story["resolve"][0], "resolve"))
        for minutes, step in sorted(steps):
            when = created + timedelta(minutes=minutes)
            if step == "escalate":
                row |= {"status": "ESCALATED", "escalated_at": when.isoformat()}
                add(case_id, "ESCALATED", "system", when, {"due_at": due.isoformat()})
            elif step == "assign":
                _, who = story["assign"]
                add(
                    case_id, "ASSIGNED", who, when, {"from": row["assignee"], "to": who}
                )
                row["assignee"] = who
            else:
                _, who, outcome = story["resolve"]
                final = "REJECT" if outcome == "FRAUD" else "APPROVE"
                key = f"cases/{created:%Y}/{created:%m}/{case_id}.json"
                row |= {
                    "status": "RESOLVED",
                    "resolved_at": when.isoformat(),
                    "resolved_by": who,
                    "outcome": outcome,
                    "final_decision": final,
                    "resolution_note": f"Reviewed by {who}.",
                    "evidence_key": key,
                }
                add(
                    case_id,
                    "RESOLVED",
                    who,
                    when,
                    {
                        "outcome": outcome,
                        "final_decision": final,
                        "note": row["resolution_note"],
                    },
                )
                add(
                    case_id,
                    "EVIDENCE_ARCHIVED",
                    "system",
                    when + timedelta(seconds=2),
                    {
                        "bucket": "securepay-dev-evidence",
                        "key": key,
                        "retain_until": "2036-10-05T00:00:00+00:00",
                    },
                )
        assert datetime.fromisoformat(case_events[-1]["at"]) <= EXPORTED_AT, name
        cases.append(row)
    return cases, case_events


def make_reconciliation(events):
    def ours(name):
        t = events[name]["transaction"]
        return t["id"], t["currency"], t["amount"], t["transaction_date"]

    runs = {d: uid(f"run:{d}") for d in ("2026-09-25", "2026-10-01", "2026-10-05")}
    rows = []

    def diff(
        name,
        run_day,
        partner,
        kind,
        reference,
        cur,
        pago,
        part,
        at_ours,
        at_partner,
        status="PENDING",
        resolved=None,
    ):
        detected = datetime.fromisoformat(f"{run_day}T07:05:00+00:00") + timedelta(
            days=1
        )
        rows.append(
            {
                "id": uid(f"difference:{name}"),
                "run_id": runs[run_day],
                "run_day": run_day,
                "partner": partner,
                "type": kind,
                "reference": reference,
                "partner_reference": None
                if kind == "MISSING_IN_PARTNER"
                else f"P-{name}",
                "currency": cur,
                "pagoseguro_amount": pago,
                "partner_amount": part,
                "amount_difference": money(Decimal(part) - Decimal(pago))
                if kind == "AMOUNT_MISMATCH"
                else None,
                "pagoseguro_at": at_ours,
                "partner_at": at_partner,
                "status": status,
                "detected_at": detected.isoformat(),
                "resolved_at": resolved,
                "resolved_by": "tesoreria" if resolved else None,
                "resolution_note": "Partner resent the file." if resolved else None,
            }
        )

    ref, cur, amount, when = ours("n_topup_app")
    assert partner_for("RECARGA", "APP").value == "banco_andino"
    diff(
        "topup_missing",
        "2026-10-05",
        "banco_andino",
        "MISSING_IN_PARTNER",
        ref,
        cur,
        amount,
        None,
        when,
        None,
    )
    ref, cur, amount, when = ours("n_qr_eur")
    diff(
        "qr_amount",
        "2026-10-05",
        "qr_pagos",
        "AMOUNT_MISMATCH",
        ref,
        cur,
        amount,
        "35.72",
        when,
        when,
    )
    diff(
        "atm_unknown",
        "2026-10-01",
        "cajeros_express",
        "MISSING_IN_PAGOSEGURO",
        uid("ref:atm"),
        "JPY",
        None,
        "8000",
        None,
        "2026-10-01T15:00:00+00:00",
    )
    diff(
        "corr_resolved",
        "2026-10-01",
        "red_corresponsales",
        "MISSING_IN_PARTNER",
        uid("ref:corr"),
        "USD",
        "80.00",
        None,
        "2026-10-01T16:00:00+00:00",
        None,
        status="RESOLVED",
        resolved="2026-10-03T14:00:00+00:00",
    )
    diff(
        "old_amount",
        "2026-09-25",
        "banco_andino",
        "AMOUNT_MISMATCH",
        uid("ref:old"),
        "COP",
        "100000.00",
        "99000.00",
        "2026-09-25T10:00:00+00:00",
        "2026-09-25T10:00:00+00:00",
    )
    diff(
        "old_qr",
        "2026-09-25",
        "qr_pagos",
        "MISSING_IN_PAGOSEGURO",
        uid("ref:oldqr"),
        "USD",
        None,
        "15.00",
        None,
        "2026-09-25T11:00:00+00:00",
    )

    per_run = Counter(r["run_day"] for r in rows)
    run_rows = [
        {
            "id": run_id,
            "run_day": d,
            "status": "DONE",
            "started_at": f"{date.fromisoformat(d) + timedelta(days=1)}T07:00:00+00:00",
            "finished_at": f"{date.fromisoformat(d) + timedelta(days=1)}T07:06:00+00:00",
            "files_read": 4,
            "records_read": 10 + per_run[d],
            "rows_rejected": 0,
            "matched": 10,
            "differences": per_run[d],
            "error": None,
        }
        for d, run_id in runs.items()
    ]
    # What matched per partner (the MATCHED rows of each run's match
    # output): adds up to the run's matched.
    split = (("banco_andino", 4), ("cajeros_express", 3), ("qr_pagos", 2))
    split += (("red_corresponsales", 1),)
    matched = [
        {"run_day": d, "partner": partner, "matched": n}
        for d in runs
        for partner, n in split
    ]
    return rows, run_rows, matched


# --- The answer key ----------------------------------------------------------------


def expected_q1(day_events):
    groups = defaultdict(lambda: [0, Decimal(0)])
    for e in day_events.values():
        t, d = e["transaction"], e["decision"]
        key = (DAY.isoformat(), t["type"], t["currency"], t["channel"], d["decision"])
        groups[key][0] += 1
        groups[key][1] += Decimal(d["amount_usd"])
    return [
        {
            "day": k[0],
            "type": k[1],
            "currency": k[2],
            "channel": k[3],
            "decision": k[4],
            "transactions": n,
            "amount_usd": money(total),
        }
        for k, (n, total) in sorted(groups.items())
    ]


RULES = [r for r in default_catalog().rules if r.type != "default_timeout"]


def expected_q2(day_events, labels):
    """rule_metrics of the generator's labels (definitions of C5)."""
    labeled = [e for e in day_events.values() if str(e["transaction"]["id"]) in labels]
    legit = sum(
        1 for e in labeled if not labels[str(e["transaction"]["id"])]["is_fraud"]
    )
    rows = []
    for rule in RULES:
        fired = [e for e in labeled if rule.code in e["decision"]["rules_triggered"]]
        tp = sum(1 for e in fired if labels[str(e["transaction"]["id"])]["is_fraud"])
        fp = len(fired) - tp
        rows.append(
            {
                "rule": rule.code,
                "rule_version": rule.rule_version,
                "hits": len(fired),
                "true_positives": tp,
                "false_positives": fp,
                "precision": ratio(tp, len(fired)),
                "false_positive_rate": ratio(fp, legit),
                "label_source": "generator",
            }
        )
    return sorted(rows, key=lambda r: r["rule"])


def _detected(decision: dict) -> bool:
    return decision["decision"] in ("HOLD", "REJECT") or decision["opens_case"]


def expected_q3(day_events, labels):
    by_pattern = defaultdict(list)
    for e in day_events.values():
        label = labels.get(str(e["transaction"]["id"]))
        if label and label["is_fraud"]:
            by_pattern[label["pattern"]].append(
                (e["decision"], label["expected_rule"] is not None)
            )
    rows = []
    for pattern, pairs in sorted(by_pattern.items()):
        decisions = [d for d, _ in pairs]
        detected = [d for d in decisions if _detected(d)]
        missed = [d for d in decisions if not _detected(d)]
        expected = [d for d, wants_rule in pairs if wants_rule]
        expected_detected = [d for d in expected if _detected(d)]
        rules = Counter(r for d in detected for r in d["rules_triggered"])
        top = min(rules, key=lambda r: (-rules[r], r)) if rules else None
        rows.append(
            {
                "pattern": pattern,
                "label_source": "generator",
                "frauds": len(decisions),
                "detected": len(detected),
                "missed": len(decisions) - len(detected),
                "detection_rate": ratio(len(detected), len(decisions)),
                "detected_amount_usd": money(
                    sum((Decimal(d["amount_usd"]) for d in detected), Decimal(0))
                ),
                "missed_amount_usd": money(
                    sum((Decimal(d["amount_usd"]) for d in missed), Decimal(0))
                ),
                "top_rule": top,
                "expected": len(expected),
                "expected_detected": len(expected_detected),
                "expected_detection_rate": ratio(len(expected_detected), len(expected)),
            }
        )
    return rows


def expected_q4(cases, case_events):
    groups = defaultdict(list)
    for c in cases:
        created = datetime.fromisoformat(c["created_at"])
        analyst = c["resolved_by"] or c["assignee"]
        groups[(created.date().isoformat(), analyst, c["status"], c["outcome"])].append(
            c
        )
    rows = []
    for (day, analyst, status, outcome), items in sorted(
        groups.items(),
        key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2], kv[0][3] or ""),
    ):
        minutes = sorted(
            math.floor(
                (
                    datetime.fromisoformat(c["resolved_at"])
                    - datetime.fromisoformat(c["created_at"])
                ).total_seconds()
                / 60
            )
            for c in items
            if c["resolved_at"]
        )
        p90 = minutes[math.ceil(0.9 * len(minutes)) - 1] if minutes else None
        rows.append(
            {
                "day": day,
                "analyst": analyst,
                "status": status,
                "outcome": outcome,
                "cases": len(items),
                "escalated": sum(1 for c in items if c["escalated_at"]),
                "avg_minutes_to_resolve": money(Decimal(sum(minutes)) / len(minutes))
                if minutes
                else None,
                "p90_minutes_to_resolve": p90,
                "within_sla_pct": money(
                    Decimal(100 * sum(1 for m in minutes if m <= CASE_DUE_MINUTES))
                    / len(minutes)
                )
                if minutes
                else None,
            }
        )
    return rows


def _age_range(age: int) -> str:
    for name, low, high in AGE_RANGES:
        if age >= low and (high is None or age <= high):
            return name
    raise ValueError(age)


def expected_q5(differences, matched):
    matched_rows = [
        {
            "run_day": m["run_day"],
            "partner": m["partner"],
            "type": "MATCHED",
            "status": None,
            "age_range": None,
            "currency": None,
            "records": m["matched"],
            "amount_difference_total": None,
        }
        for m in matched
    ]
    groups = defaultdict(list)
    for d in differences:
        age = (DAY - date.fromisoformat(d["run_day"])).days
        groups[
            (
                d["run_day"],
                d["partner"],
                d["type"],
                d["status"],
                _age_range(age),
                d["currency"],
            )
        ].append(d)
    return [
        {
            "run_day": k[0],
            "partner": k[1],
            "type": k[2],
            "status": k[3],
            "age_range": k[4],
            "currency": k[5],
            "records": len(items),
            "amount_difference_total": money(
                sum(
                    Decimal(d["amount_difference"])
                    for d in items
                    if d["amount_difference"]
                )
            )
            if any(d["amount_difference"] for d in items)
            else None,
        }
        for k, items in sorted(groups.items())
    ] + matched_rows


LEVEL = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def expected_q6(day_events, labels, cases):
    case_tx = {c["transaction_id"] for c in cases}
    devices = defaultdict(lambda: {"accounts": set(), "tx": 0, "held": 0, "cases": 0})
    merchants = defaultdict(lambda: {"tx": 0, "held": 0, "fraud": 0})
    for e in day_events.values():
        t, d = e["transaction"], e["decision"]
        held = d["decision"] in ("HOLD", "REJECT")
        dev = devices[t["device_id"]]
        dev["accounts"].add(t.get("source_account_id") or t["destination_account_id"])
        dev["tx"] += 1
        dev["held"] += held
        dev["cases"] += t["id"] in case_tx
        if t.get("merchant_id"):
            m = merchants[t["merchant_id"]]
            m["tx"] += 1
            m["held"] += held
            m["fraud"] += bool(labels.get(t["id"], {}).get("is_fraud"))
    rows = []
    device_rows = []
    for dev_id, v in devices.items():
        shared = len(v["accounts"]) > 3
        flagged = v["held"] > 0 or v["cases"] > 0
        level = (
            "HIGH" if shared and flagged else "MEDIUM" if shared or flagged else "LOW"
        )
        device_rows.append(
            {
                "kind": "DEVICE",
                "id": dev_id,
                "risk_level": level,
                "accounts_30d": len(v["accounts"]),
                "transactions_30d": v["tx"],
                "held_or_rejected_30d": v["held"],
                "cases_30d": v["cases"],
            }
        )
    merchant_rows = []
    for m_id, v in merchants.items():
        level = (
            "HIGH"
            if v["fraud"] > 0 and v["held"] > 0
            else "MEDIUM"
            if v["fraud"] > 0 or v["held"] > 0
            else "LOW"
        )
        merchant_rows.append(
            {
                "kind": "MERCHANT",
                "id": m_id,
                "risk_level": level,
                "accounts_30d": None,
                "transactions_30d": v["tx"],
                "held_or_rejected_30d": v["held"],
                "cases_30d": None,
            }
        )
    for group in (device_rows, merchant_rows):
        ranked = sorted(
            group,
            key=lambda r: (
                -LEVEL[r["risk_level"]],
                -r["held_or_rejected_30d"],
                -r["transactions_30d"],
                r["id"],
            ),
        )
        for i, r in enumerate(ranked, start=1):
            if r["risk_level"] != "LOW":
                rows.append({**r, "rank": i})
    return rows


if __name__ == "__main__":
    _, answer = build()
    print(
        json.dumps(
            {k: (len(v) if isinstance(v, list) else v) for k, v in answer.items()}
        )
    )
