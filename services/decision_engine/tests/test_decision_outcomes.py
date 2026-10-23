"""One test for each possible engine outcome.

Unit tests: they only check how the triggered rules become one decision,
without PostgreSQL, Valkey or LocalStack.
"""

import pytest

from services.decision_engine.decision_service import (
    NO_RULES_REASON,
    TriggeredRule,
    choose_decision,
)
from services.decision_engine.schemas import Decision

RESTRICTED = TriggeredRule("restricted_list", Decision.REJECT, "restricted list reason")
VELOCITY = TriggeredRule("velocity", Decision.HOLD, "velocity reason")
MULE = TriggeredRule("mule", Decision.HOLD, "mule reason")
SHARED_DEVICE = TriggeredRule("shared_device", Decision.APPROVE, "shared device reason", score=30)
SPLITTING = TriggeredRule("splitting", Decision.APPROVE, "splitting reason",
                          score=40, opens_case=True)
OTHER_HOLD = TriggeredRule("other", Decision.HOLD, "other reason")


def test_no_rule_triggered_is_approved():
    assert choose_decision([]) == (Decision.APPROVE, NO_RULES_REASON)


def test_hold_rule_is_held():
    assert choose_decision([VELOCITY]) == (Decision.HOLD, "velocity reason")


def test_reject_rule_is_rejected():
    assert choose_decision([RESTRICTED]) == (Decision.REJECT, "restricted list reason")


@pytest.mark.parametrize(
    "triggered",
    [[VELOCITY, RESTRICTED], [RESTRICTED, VELOCITY]],
    ids=["hold-first", "reject-first"],
)
def test_most_severe_rule_wins_whatever_the_order(triggered):
    assert choose_decision(triggered) == (Decision.REJECT, "restricted list reason")


def test_same_severity_keeps_the_first_reason():
    assert choose_decision([VELOCITY, OTHER_HOLD]) == (
        Decision.HOLD,
        "velocity reason",
    )


def test_mule_is_held():
    assert choose_decision([MULE]) == (Decision.HOLD, "mule reason")


def test_mule_and_restricted_list_is_rejected():
    assert choose_decision([MULE, RESTRICTED]) == (
        Decision.REJECT,
        "restricted list reason",
    )


TAKEOVER = TriggeredRule("account_takeover", Decision.HOLD, "takeover reason")


def test_account_takeover_is_held():
    assert choose_decision([TAKEOVER]) == (Decision.HOLD, "takeover reason")


def test_account_takeover_and_restricted_list_is_rejected():
    assert choose_decision([TAKEOVER, RESTRICTED]) == (
        Decision.REJECT,
        "restricted list reason",
    )


def test_shared_device_alone_is_approved_with_its_reason():
    assert choose_decision([SHARED_DEVICE]) == (Decision.APPROVE, "shared device reason")


def test_shared_device_and_velocity_is_held():
    assert choose_decision([SHARED_DEVICE, VELOCITY]) == (Decision.HOLD, "velocity reason")


def test_splitting_alone_is_approved_with_its_reason():
    assert choose_decision([SPLITTING]) == (Decision.APPROVE, "splitting reason")


def test_splitting_and_velocity_is_held():
    assert choose_decision([SPLITTING, VELOCITY]) == (Decision.HOLD, "velocity reason")
