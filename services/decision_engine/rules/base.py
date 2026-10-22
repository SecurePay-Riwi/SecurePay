"""What every rule receives and returns.

A rule is a module with TYPE (a RuleType of shared/rule_catalog.py) and
evaluate(ctx, rule). It reads its thresholds from rule.typed_params(),
never from constants or environment variables, so the rules API can
change them without a redeploy. What it decides and whether it opens a
case also come from the catalog: the rule only says whether it fired.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property

from sqlalchemy.orm import Session

from services.decision_engine import history
from services.decision_engine.schemas import Decision, TransactionRequest
from shared.models import ListaRestrictiva
from shared.rule_catalog import RuleEntry


@dataclass(frozen=True)
class TriggeredRule:
    """What a rule that fired says."""

    rule: str  # RuleEntry.code
    decision: Decision
    reason: str
    score: int = 0
    opens_case: bool = False
    rule_version: int = 1


def hit(rule: RuleEntry, reason: str) -> TriggeredRule:
    """What a rule returns when it fires. Decision, case and score come
    from the catalog, not from the rule's code."""
    return TriggeredRule(
        rule.code,
        Decision(rule.action),
        reason,
        rule.score,
        rule.opens_case,
        rule.rule_version,
    )


@dataclass
class RuleContext:
    """Everything a rule may read about the transaction being decided.

    Built once per decision in _decide(), after writing the history.
    Expensive reads are lazy, so a disabled rule costs nothing.
    """

    payload: TransactionRequest
    session: Session
    t_ms: int
    amount_usd: Decimal
    # The source account's outgoing history after recording this
    # transaction; empty without a source account.
    outgoing: list[history.Outgoing] = field(default_factory=list)
    # Documents of every account owner involved, digits only.
    documents: set[str] = field(default_factory=set)
    # Every account that used the transaction's device, after recording
    # the main account (dev:{device}).
    device_accounts: list[history.DeviceUse] = field(default_factory=list)

    @cached_property
    def on_restricted_list(self) -> bool:
        if not self.documents:
            return False
        return (
            self.session.query(ListaRestrictiva.id)
            .filter(ListaRestrictiva.documento.in_(self.documents))
            .first()
        ) is not None

    @cached_property
    def incoming(self) -> list[history.Incoming]:
        if self.payload.source_account_id is None:
            return []
        return history.incoming(self.payload.source_account_id)
