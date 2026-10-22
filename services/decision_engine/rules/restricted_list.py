"""Restricted list rule (RN-06): an owner of any account in the
transaction is on the restricted list.

The list is checked for every owner involved (source and destination),
in PostgreSQL. Loading it into Valkey comes in a later story.
"""

from services.decision_engine.rules.base import RuleContext, TriggeredRule, hit
from shared.rule_catalog import RuleEntry

TYPE = "restricted_list"


def evaluate(ctx: RuleContext, rule: RuleEntry) -> TriggeredRule | None:
    if ctx.on_restricted_list:
        return hit(rule, "Account owner is on a restricted list.")
    return None
