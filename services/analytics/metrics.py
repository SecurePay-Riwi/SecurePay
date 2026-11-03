"""Rule metrics over labeled decisions (contract C5; Habith, HU-44 to HU-46).

A label says whether a transaction is fraud (C4). A transaction without
a label counts neither as a hit nor as a false positive. The definitions
(analytics-model.mdx, views q2 and q3):

- rule_metrics, per rule, label source and catalog version: hits =
  labeled transactions where the rule fired, true_positives = those that
  are fraud, false_positives = the rest, precision = tp / hits (None with
  0 hits), false_positive_rate = fp / labeled legitimate transactions.
  default_timeout is not a rule of the catalog and has no row.
- pattern_coverage, per fraud pattern, label source and catalog version:
  detected = decision HOLD or REJECT, or opens_case; missed = the rest;
  detection_rate = detected / frauds; top_rule = the rule that fires
  most among the detected ones (ties: alphabetical; None when none was
  detected).

Ratios have 4 decimals, rounded half up. These functions measure a
replay (the Kaggle history, the simulation of HU-24); the ETL measures
the engine's own decisions of the lake with the same definitions in
Spark (build_metrics.py), and the tests run both against the answer key.

The command replays a labeled history with the current catalog and
prints the metrics and, per rule, the false positives with the largest
amounts (HU-45):

    uv run python -m services.analytics.metrics --kaggle [--limit N] [--root generated/analytics]
    uv run python -m services.analytics.metrics --events <events.jsonl> --labels <labels.jsonl>

With --kaggle it also writes raw/metrics/kaggle/rule_metrics.jsonl and
pattern_coverage.jsonl under --root, which the next ETL run adds to the
rule_metrics and pattern_coverage tables. The generator's history is
only printed: the lake already has the engine's decisions of it.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from shared.rule_catalog import CatalogSnapshot

if TYPE_CHECKING:  # the replay imports the engine; the ETL does not need it
    from services.analytics.replay import ReplayDecision

log = logging.getLogger(__name__)

DEFAULT_RULE = "default_timeout"  # the default decision, not a catalog rule
DETECTED = ("HOLD", "REJECT")
NO_PATTERN = "UNKNOWN"  # a fraud label without a pattern
EXAMPLES = 5  # false positives shown per rule (HU-45)

_RATIO = Decimal("0.0001")


@dataclass(frozen=True)
class Label:
    transaction_id: str
    source: str  # LabelSource value
    pattern: str | None
    is_fraud: bool
    expected_rule: str | None


@dataclass(frozen=True)
class RuleMetrics:
    rule: str
    label_source: str
    hits: int  # labeled transactions where the rule fired
    true_positives: int  # fired and is_fraud
    false_positives: int  # fired and not is_fraud
    precision: Decimal | None  # tp / hits (None when hits == 0)
    false_positive_rate: Decimal | None  # fp / labeled legitimate transactions
    rule_version: int | None = None  # in the catalog replayed (None without it)
    rules_version: str | None = None  # the catalog version of the decisions


@dataclass(frozen=True)
class PatternCoverage:  # HU-46
    pattern: str
    label_source: str
    frauds: int
    detected: int  # decision HOLD or REJECT, or opens_case
    missed: int
    detection_rate: Decimal | None
    top_rule: str | None
    rules_version: str | None = None


def ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(_RATIO, ROUND_HALF_UP)


def detected(decision: ReplayDecision) -> bool:
    return decision.decision in DETECTED or decision.opens_case


def _labeled(
    decisions: Iterable[ReplayDecision], labels: Iterable[Label]
) -> list[tuple[ReplayDecision, Label]]:
    """Each decision with its label (the first label of an id), once per
    transaction; decisions without a label are left out."""
    by_id: dict[str, Label] = {}
    for label in labels:
        by_id.setdefault(str(label.transaction_id), label)
    seen, pairs = set(), []
    for d in decisions:
        label = by_id.get(str(d.transaction_id))
        if label is None or d.transaction_id in seen:
            continue
        seen.add(d.transaction_id)
        pairs.append((d, label))
    return pairs


def rule_metrics(
    decisions: Iterable[ReplayDecision],
    labels: Iterable[Label],
    snapshot: CatalogSnapshot | None = None,
) -> list[RuleMetrics]:
    """Per rule, label source and catalog version (HU-44, HU-45). With
    the `snapshot` replayed, every rule of it has a row (0 hits included)
    with its rule_version; without it, only the rules that fired.
    Ordered by label source, catalog version and rule."""
    groups: dict[tuple[str, str], list[tuple[ReplayDecision, Label]]] = defaultdict(
        list
    )
    for d, label in _labeled(decisions, labels):
        groups[(label.source, d.rules_version)].append((d, label))

    versions = {}
    if snapshot is not None:
        versions = {r.code: r.rule_version for r in snapshot.rules}
    rows = []
    for (source, rules_version), pairs in sorted(groups.items()):
        legitimate = sum(1 for _, label in pairs if not label.is_fraud)
        fired = Counter(r for d, _ in pairs for r in set(d.rules_triggered))
        frauds = Counter(
            r for d, label in pairs if label.is_fraud for r in set(d.rules_triggered)
        )
        codes = set(versions) | set(fired)
        for rule in sorted(codes - {DEFAULT_RULE}):
            hits, tp = fired[rule], frauds[rule]
            rows.append(
                RuleMetrics(
                    rule=rule,
                    label_source=source,
                    hits=hits,
                    true_positives=tp,
                    false_positives=hits - tp,
                    precision=ratio(tp, hits),
                    false_positive_rate=ratio(hits - tp, legitimate),
                    rule_version=versions.get(rule),
                    rules_version=rules_version,
                )
            )
    return rows


def pattern_coverage(
    decisions: Iterable[ReplayDecision], labels: Iterable[Label]
) -> list[PatternCoverage]:
    """Per fraud pattern, label source and catalog version (HU-46),
    ordered by those three."""
    groups: dict[tuple[str, str, str], list[ReplayDecision]] = defaultdict(list)
    for d, label in _labeled(decisions, labels):
        if label.is_fraud:
            key = (label.pattern or NO_PATTERN, label.source, d.rules_version)
            groups[key].append(d)
    rows = []
    for (pattern, source, rules_version), frauds in sorted(groups.items()):
        caught = [d for d in frauds if detected(d)]
        rules = Counter(r for d in caught for r in set(d.rules_triggered))
        rows.append(
            PatternCoverage(
                pattern=pattern,
                label_source=source,
                frauds=len(frauds),
                detected=len(caught),
                missed=len(frauds) - len(caught),
                detection_rate=ratio(len(caught), len(frauds)),
                top_rule=min(rules, key=lambda r: (-rules[r], r)) if rules else None,
                rules_version=rules_version,
            )
        )
    return rows


def false_positive_examples(
    decisions: Iterable[ReplayDecision],
    labels: Iterable[Label],
    amounts_usd: dict[str, Decimal],
    limit: int = EXAMPLES,
) -> dict[str, list[dict]]:
    """Per rule, the `limit` legitimate transactions with the largest
    amount in USD where it fired (HU-45), largest first (then id)."""
    found: dict[str, list[dict]] = defaultdict(list)
    for d, label in _labeled(decisions, labels):
        if label.is_fraud:
            continue
        for rule in set(d.rules_triggered) - {DEFAULT_RULE}:
            found[rule].append(
                {
                    "transaction_id": d.transaction_id,
                    "label_source": label.source,
                    "decision": d.decision,
                    "amount_usd": amounts_usd.get(d.transaction_id),
                    "rules_triggered": list(d.rules_triggered),
                }
            )
    return {
        rule: sorted(
            rows,
            key=lambda r: (-(r["amount_usd"] or Decimal(0)), r["transaction_id"]),
        )[:limit]
        for rule, rows in sorted(found.items())
    }


def expected_rule_hits(
    decisions: Iterable[ReplayDecision], labels: Iterable[Label]
) -> dict[str, dict]:
    """Per expected_rule of the labels: how many labeled transactions
    expect it and on how many it fired. The generator marks every
    transaction of a fraud scheme as fraud, but expects the rule only on
    the one that completes it (the 6th transfer, the withdrawal)."""
    found: dict[str, dict] = {}
    for d, lbl in _labeled(decisions, labels):
        if not lbl.expected_rule:
            continue
        row = found.setdefault(lbl.expected_rule, {"expected": 0, "fired": 0})
        row["expected"] += 1
        row["fired"] += lbl.expected_rule in d.rules_triggered
    return dict(sorted(found.items()))


def to_row(metric: RuleMetrics | PatternCoverage) -> dict:
    """A metric as a JSON row: ratios as decimal strings."""
    return {
        k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(metric).items()
    }


# --- The command --------------------------------------------------------------

RAW_METRICS_FILES = ("rule_metrics", "pattern_coverage")


def current_catalog(session) -> CatalogSnapshot:
    """The latest version of the rules API's catalog (rule_catalog_versions),
    or the code defaults when the API never wrote one. Read with plain SQL:
    this module does not import the rules API."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    from shared.rule_catalog import default_catalog

    try:
        row = session.execute(
            text(
                "SELECT snapshot FROM rule_catalog_versions "
                "ORDER BY version DESC LIMIT 1"
            )
        ).first()
    except ProgrammingError:  # the rules API never created its tables
        session.rollback()
        row = None
    return default_catalog() if row is None else CatalogSnapshot.model_validate(row[0])


def measure(snapshot, transactions, labels, reference, security_events=()) -> dict:
    """Replay `transactions` with `snapshot` and measure them."""
    from services.analytics import replay as rp

    decided = rp.decide_all(snapshot, transactions, reference, security_events)
    decisions = [
        rp.ReplayDecision(
            transaction_id=str(tx.id),
            decision=result["decision"],
            rules_triggered=tuple(result["rules_triggered"]),
            risk_score=result["risk_score"],
            opens_case=result["opens_case"],
            rules_version=result["rules_version"],
        )
        for tx, result in decided
    ]
    amounts = {str(tx.id): Decimal(result["amount_usd"]) for tx, result in decided}
    labels = list(labels)
    return {
        "rules_version": str(snapshot.version),
        "transactions": len(decisions),
        "labeled": len(_labeled(decisions, labels)),
        "rule_metrics": rule_metrics(decisions, labels, snapshot),
        "pattern_coverage": pattern_coverage(decisions, labels),
        "false_positive_examples": false_positive_examples(decisions, labels, amounts),
        "expected_rule_hits": expected_rule_hits(decisions, labels),
    }


def write_raw(result: dict, root: str, name: str) -> dict[str, str]:
    """raw/metrics/<name>/<table>.jsonl under root (local or s3://)."""
    from services.reconciliation import storage
    from shared.analytics import RAW_METRICS, layer_path

    written = {}
    for table in RAW_METRICS_FILES:
        path = f"{layer_path(root, RAW_METRICS)}/{name}/{table}.jsonl"
        rows = [json.dumps(to_row(m)) for m in result[table]]
        storage.write_text(path, "".join(f"{r}\n" for r in rows))
        written[table] = path
    return written


def _printable(result: dict) -> dict:
    out = dict(result)
    for table in RAW_METRICS_FILES:
        out[table] = [to_row(m) for m in result[table]]
    return out


def main(argv=None) -> None:
    from services.analytics import ANALYTICS_DATA_DIR
    from services.analytics import labels as lb
    from services.analytics.replay import ReferenceData
    from shared.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="python -m services.analytics.metrics")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--kaggle", action="store_true", help="PaySim and Sparkov")
    source.add_argument("--events", help="the generator's events.jsonl")
    parser.add_argument("--labels", help="the generator's labels.jsonl")
    parser.add_argument("--limit", type=int, help="Kaggle rows at most")
    parser.add_argument(
        "--catalog", help="a CatalogSnapshot JSON instead of the current one"
    )
    parser.add_argument("--root", default=ANALYTICS_DATA_DIR)
    args = parser.parse_args(argv)
    if args.events and not args.labels:
        parser.error("--events needs --labels")

    with SessionLocal() as session:
        if args.catalog:
            with open(args.catalog, encoding="utf-8") as f:
                snapshot = CatalogSnapshot.model_validate_json(f.read())
        else:
            snapshot = current_catalog(session)
        reference = ReferenceData.from_database(session)
        if args.kaggle:
            transactions, labels = lb.kaggle_transactions(session, args.limit)
            security = ()
        else:
            transactions, security = lb.generator_events(args.events)
            labels = lb.generator_labels(args.labels)

    result = measure(snapshot, transactions, labels, reference, security)
    out = _printable(result)
    if args.kaggle:
        out["written"] = write_raw(result, args.root, "kaggle")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
