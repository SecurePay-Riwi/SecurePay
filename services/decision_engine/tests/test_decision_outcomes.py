"""Una prueba por cada resultado posible del motor.

Son unitarias: prueban solo cómo se juntan las reglas activadas en una
decisión, sin PostgreSQL, Valkey ni LocalStack.
"""

import pytest

from services.decision_engine.decision_service import (
    MOTIVO_SIN_REGLAS,
    ReglaActivada,
    elegir_decision,
)
from services.decision_engine.schemas import Decision

LISTA = ReglaActivada("lista_restrictiva", Decision.REJECT, "motivo lista")
VELOCIDAD = ReglaActivada("velocidad", Decision.HOLD, "motivo velocidad")
OTRA_RETENCION = ReglaActivada("otra", Decision.HOLD, "motivo otra")


def test_no_rule_triggered_is_approved():
    assert elegir_decision([]) == (Decision.APPROVE, MOTIVO_SIN_REGLAS)


def test_hold_rule_is_held():
    assert elegir_decision([VELOCIDAD]) == (Decision.HOLD, "motivo velocidad")


def test_reject_rule_is_rejected():
    assert elegir_decision([LISTA]) == (Decision.REJECT, "motivo lista")


@pytest.mark.parametrize(
    "activadas",
    [[VELOCIDAD, LISTA], [LISTA, VELOCIDAD]],
    ids=["hold-first", "reject-first"],
)
def test_most_severe_rule_wins_whatever_the_order(activadas):
    assert elegir_decision(activadas) == (Decision.REJECT, "motivo lista")


def test_same_severity_keeps_the_first_reason():
    assert elegir_decision([VELOCIDAD, OTRA_RETENCION]) == (
        Decision.HOLD,
        "motivo velocidad",
    )
