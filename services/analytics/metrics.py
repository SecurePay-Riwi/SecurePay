"""Rule metrics over a replay (contract C5; Habith, HU-44 to HU-46).

A label says whether a transaction is fraud (C4). A transaction without
a label counts neither as a hit nor as a false positive. Step 0 leaves
the shapes and the signatures: the functions return empty lists until
HU-44 (rule_metrics) and HU-46 (pattern_coverage).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from services.analytics.replay import ReplayDecision


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


@dataclass(frozen=True)
class PatternCoverage:  # HU-46
    pattern: str
    label_source: str
    frauds: int
    detected: int  # decision HOLD or REJECT, or opens_case
    missed: int
    detection_rate: Decimal | None
    top_rule: str | None


def rule_metrics(
    decisions: Iterable[ReplayDecision], labels: Iterable[Label]
) -> list[RuleMetrics]:
    """Per rule and label source (HU-44, HU-45). Empty until HU-44."""
    return []


def pattern_coverage(
    decisions: Iterable[ReplayDecision], labels: Iterable[Label]
) -> list[PatternCoverage]:
    """Per fraud pattern and label source (HU-46). Empty until HU-46."""
    return []
