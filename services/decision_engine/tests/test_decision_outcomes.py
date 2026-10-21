"""Una prueba por cada resultado posible del motor.

Son unitarias: prueban solo cómo se juntan las reglas activadas en una
decisión, sin PostgreSQL, Valkey ni LocalStack.
"""

import pytest

from services.decision_engine.decision_service import (
    NO_RULES_REASON,
    TriggeredRule,
    choose_decision,
)
from services.decision_engine.schemas import Decision

LISTA = TriggeredRule("restricted_list", Decision.REJECT, "motivo lista")
VELOCIDAD = TriggeredRule("velocity", Decision.HOLD, "motivo velocidad")
OTRA_RETENCION = TriggeredRule("otra", Decision.HOLD, "motivo otra")


def test_no_rule_triggered_is_approved():
    assert choose_decision([]) == (Decision.APPROVE, NO_RULES_REASON)


def test_hold_rule_is_held():
    assert choose_decision([VELOCIDAD]) == (Decision.HOLD, "motivo velocidad")


def test_reject_rule_is_rejected():
    assert choose_decision([LISTA]) == (Decision.REJECT, "motivo lista")


@pytest.mark.parametrize(
    "activadas",
    [[VELOCIDAD, LISTA], [LISTA, VELOCIDAD]],
    ids=["hold-first", "reject-first"],
)
def test_most_severe_rule_wins_whatever_the_order(activadas):
    assert choose_decision(activadas) == (Decision.REJECT, "motivo lista")


def test_same_severity_keeps_the_first_reason():
    assert choose_decision([VELOCIDAD, OTRA_RETENCION]) == (
        Decision.HOLD,
        "motivo velocidad",
    )
