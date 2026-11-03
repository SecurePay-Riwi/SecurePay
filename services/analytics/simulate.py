"""Simulate a rule version over the history (HU-24; Habith).

Replays one day with two catalogs, the current one (or version
--against) and a candidate, and compares them: decisions, cases, the
rule metrics against the labels (metrics.py) and the transactions whose
decision changes. Nothing is written: no rules, no catalog versions, no
Valkey.

    uv run python -m services.analytics.simulate --day 2026-10-05 \\
        --candidate candidate.json [--against N] [--kaggle] [--raw ROOT] \\
        [--security security_events.jsonl] [--reference FOLDER]

The day's transactions come from raw/decisiones (what the engine
decided, read with plain Python, no Spark) or, with --kaggle, from the
Kaggle rows of PostgreSQL. The replay also runs the WARMUP_DAYS before
the day, so the 24-hour history of velocity, mule and splitting starts
full; only the day is compared. raw/decisiones does not hold the device
and password changes: pass the generator's security events with
--security, or account_takeover cannot fire. The rules API runs the
same simulation in POST /rules/simulations (D5: one day at a time).

candidate.json is a CatalogSnapshot or a list of RuleEntry.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError

from shared.rule_catalog import CatalogSnapshot, RuleEntry

log = logging.getLogger(__name__)

WARMUP_DAYS = 1  # days replayed before the day, for the 24-hour history
MAX_EXAMPLES = 10
DECISIONS = ("APPROVE", "HOLD", "REJECT")
CANDIDATE_AUTHOR = "candidate"


class VersionNotFound(LookupError):
    """No catalog version with that number."""


# --- Inputs -------------------------------------------------------------------


def candidate_snapshot(data, against: CatalogSnapshot) -> CatalogSnapshot:
    """A CatalogSnapshot, or a list of RuleEntry that becomes one (with
    the version number of `against`, author "candidate")."""
    if isinstance(data, CatalogSnapshot):
        return data
    if isinstance(data, list):
        rules = TypeAdapter(list[RuleEntry]).validate_python(data)
        return CatalogSnapshot(
            version=against.version,
            created_at=datetime.now(UTC),
            author=CANDIDATE_AUTHOR,
            rules=rules,
        )
    return CatalogSnapshot.model_validate(data)


def catalog_version(session, version: int | None) -> CatalogSnapshot:
    """Version `version` of the rules API's catalog (rule_catalog_versions),
    or the latest one when None (the code defaults without the API)."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    from services.analytics.metrics import current_catalog

    if version is None:
        return current_catalog(session)
    try:
        row = session.execute(
            text("SELECT snapshot FROM rule_catalog_versions WHERE version = :v"),
            {"v": version},
        ).first()
    except ProgrammingError:  # the rules API never created its tables
        session.rollback()
        row = None
    if row is None:
        raise VersionNotFound(f"Catalog version {version} does not exist.")
    return CatalogSnapshot.model_validate(row[0])


def _utc_day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).date()


def day_history(root: str, day: date):
    """The transactions of raw/decisiones for `day` and its WARMUP_DAYS,
    once per id (the first event of an id, earliest processed_at), in a
    list, and the ids of `day`. A line the engine would refuse is left
    out."""
    from services.decision_engine.schemas import TransactionRequest
    from services.reconciliation import storage
    from shared.analytics import RAW_DECISIONS, layer_path

    first = day - timedelta(days=WARMUP_DAYS)
    folders = [
        layer_path(root, RAW_DECISIONS, first + timedelta(days=d))
        for d in range(-1, WARMUP_DAYS + 2)
    ]
    events: dict[str, tuple[str, dict]] = {}
    for folder in folders:
        for path in storage.list_files(folder, "*.jsonl"):
            for event in storage.read_jsonl(path):
                tx = event.get("transaction") or {}
                tx_id = tx.get("id")
                if not tx_id or not tx.get("transaction_date"):
                    continue
                processed = (event.get("decision") or {}).get("processed_at") or "~"
                if tx_id not in events or processed < events[tx_id][0]:
                    events[tx_id] = (processed, tx)

    transactions, day_ids = [], set()
    for tx_id, (_, tx) in events.items():
        when = _utc_day(tx["transaction_date"])
        if not first <= when <= day:
            continue
        try:
            transactions.append(TransactionRequest(**tx))
        except ValidationError:
            continue
        if when == day:
            day_ids.add(str(tx_id))
    return transactions, day_ids


def day_labels(root: str) -> list:
    """The generator's labels of every raw/labels/fecha=*/ file."""
    from services.analytics.labels import generator_labels
    from services.reconciliation import storage
    from shared.analytics import RAW_LABELS, layer_path

    labels = []
    for path in storage.list_files(layer_path(root, RAW_LABELS), "*.jsonl"):
        labels.extend(generator_labels(path))
    return labels


def kaggle_day(session, day: date):
    """The Kaggle rows of `day` and its WARMUP_DAYS, their ids of `day` and
    their labels."""
    from services.analytics.labels import kaggle_transactions

    first = day - timedelta(days=WARMUP_DAYS)
    rows, labels = kaggle_transactions(session)
    transactions = [
        t for t in rows if first <= t.transaction_date.astimezone(UTC).date() <= day
    ]
    day_ids = {
        str(t.id)
        for t in transactions
        if t.transaction_date.astimezone(UTC).date() == day
    }
    return transactions, day_ids, [lb for lb in labels if lb.transaction_id in day_ids]


# --- The simulation -------------------------------------------------------------


def _decide(snapshot, transactions, reference, security, day_ids) -> dict:
    from services.analytics import replay

    decided = replay.decide_all(snapshot, transactions, reference, security)
    return {str(tx.id): (tx, r) for tx, r in decided if str(tx.id) in day_ids}


def _summary(snapshot, decided: dict, labels, label: str) -> dict:
    from services.analytics import metrics
    from services.analytics.replay import ReplayDecision

    decisions = [
        ReplayDecision(
            transaction_id=tx_id,
            decision=r["decision"],
            rules_triggered=tuple(r["rules_triggered"]),
            risk_score=r["risk_score"],
            opens_case=r["opens_case"],
            rules_version=r["rules_version"],
        )
        for tx_id, (_, r) in decided.items()
    ]
    counts = Counter(d.decision for d in decisions)
    return {
        "rules_version": label,
        "decisions": {d: counts.get(d, 0) for d in DECISIONS},
        "cases": sum(1 for d in decisions if d.opens_case),
        "amount_usd": {
            d: str(
                sum(
                    (
                        Decimal(r["amount_usd"])
                        for _, r in decided.values()
                        if r["decision"] == d
                    ),
                    Decimal("0.00"),
                )
            )
            for d in DECISIONS
        },
        "metrics": [
            metrics.to_row(m) for m in metrics.rule_metrics(decisions, labels, snapshot)
        ],
    }


def _side(result: dict) -> dict:
    return {
        "decision": result["decision"],
        "rules_triggered": result["rules_triggered"],
        "opens_case": result["opens_case"],
        "risk_score": result["risk_score"],
    }


def simulate(
    day: date,
    current: CatalogSnapshot,
    candidate: CatalogSnapshot,
    transactions: list,
    day_ids: set[str],
    reference,
    labels: Iterable = (),
    security_events: Iterable = (),
) -> dict:
    """Replay the day with both catalogs and compare them. `changed` counts
    the transactions whose decision changes; `changes` says from what to
    what; `released_usd` is the money the candidate lets through that the
    current catalog held or rejected (and `stopped_usd` the reverse);
    `examples` are up to MAX_EXAMPLES changed transactions, largest first."""
    labels, security = list(labels), list(security_events)
    now = _decide(current, transactions, reference, security, day_ids)
    then = _decide(candidate, transactions, reference, security, day_ids)

    changed = sorted(
        (
            t
            for t in now
            if t in then and now[t][1]["decision"] != then[t][1]["decision"]
        ),
        key=lambda t: (-Decimal(now[t][1]["amount_usd"]), t),
    )
    released = stopped = Decimal("0.00")
    changes: Counter = Counter()
    for t in changed:
        before, after = now[t][1]["decision"], then[t][1]["decision"]
        changes[f"{before}->{after}"] += 1
        amount = Decimal(now[t][1]["amount_usd"])
        if after == "APPROVE":
            released += amount
        elif before == "APPROVE":
            stopped += amount

    examples = []
    for t in changed[:MAX_EXAMPLES]:
        tx, result = now[t]
        examples.append(
            {
                "transaction_id": t,
                "type": tx.type,
                "amount": str(tx.amount),
                "currency": tx.currency,
                "amount_usd": result["amount_usd"],
                "current": _side(result),
                "candidate": _side(then[t][1]),
            }
        )
    return {
        "day": day.isoformat(),
        "transactions": len(now),
        "current": _summary(current, now, labels, str(current.version)),
        "candidate": _summary(candidate, then, labels, CANDIDATE_AUTHOR),
        "changed": len(changed),
        "changes": dict(sorted(changes.items())),
        "released_usd": str(released),
        "stopped_usd": str(stopped),
        "examples": examples,
    }


def main(argv=None) -> None:
    from services.analytics import ANALYTICS_DATA_DIR
    from services.analytics.replay import ReferenceData
    from services.decision_engine.schemas import SecurityEventRequest
    from services.reconciliation import storage
    from shared.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="python -m services.analytics.simulate")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--candidate", required=True, help="CatalogSnapshot or rules JSON"
    )
    parser.add_argument(
        "--against", type=int, help="catalog version (default: current)"
    )
    parser.add_argument("--kaggle", action="store_true", help="the Kaggle history")
    parser.add_argument("--raw", default=ANALYTICS_DATA_DIR, help="root of raw/")
    parser.add_argument("--security", help="security events (JSON lines)")
    parser.add_argument(
        "--reference",
        help="a folder with reference.json instead of the seed tables (the fixtures)",
    )
    args = parser.parse_args(argv)

    with open(args.candidate, encoding="utf-8") as f:
        data = json.load(f)
    security = []
    if args.security:
        security = [
            SecurityEventRequest(**row) for row in storage.read_jsonl(args.security)
        ]

    with SessionLocal() as session:
        try:
            current = catalog_version(session, args.against)
        except VersionNotFound as exc:
            raise SystemExit(str(exc)) from exc
        if args.reference:
            reference = ReferenceData.from_fixtures(args.reference)
        else:
            reference = ReferenceData.from_database(session)
        if args.kaggle:
            transactions, day_ids, labels = kaggle_day(session, args.day)
        else:
            transactions, day_ids = day_history(args.raw, args.day)
            labels = day_labels(args.raw)

    result = simulate(
        args.day,
        current,
        candidate_snapshot(data, current),
        transactions,
        day_ids,
        reference,
        labels,
        security,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
