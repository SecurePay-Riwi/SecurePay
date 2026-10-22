"""The rule catalog (shared/rule_catalog.py) and how the engine evaluates
it. Unit tests: no PostgreSQL, Valkey or LocalStack.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.decision_engine import catalog, rules
from services.decision_engine.decision_service import evaluate_rules
from services.decision_engine.history import Outgoing, to_ms
from services.decision_engine.rules.base import RuleContext
from services.decision_engine.schemas import Decision, TransactionRequest
from shared.rule_catalog import (
    DEFAULT_RULES,
    PARAMS_BY_TYPE,
    CatalogSnapshot,
    RuleEntry,
    default_catalog,
)

BASE = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _snapshot(*entries: RuleEntry, version: int = 7) -> CatalogSnapshot:
    return CatalogSnapshot(
        version=version, created_at=BASE, author="test", rules=list(entries)
    )


def _velocity(**changes) -> RuleEntry:
    fields = dict(code="velocity", type="velocity", action="HOLD",
                  params={"window_minutes": 10, "limit": 5})
    fields.update(changes)
    return RuleEntry(**fields)


def _restricted(**changes) -> RuleEntry:
    fields = dict(code="restricted_list", type="restricted_list", action="REJECT",
                  opens_case=True)
    fields.update(changes)
    return RuleEntry(**fields)


def _context(transfers: int, on_list: bool = False) -> RuleContext:
    """A P2P that is the last of `transfers` transfers, one per minute."""
    times = [BASE + timedelta(minutes=m) for m in range(transfers)]
    payload = TransactionRequest(
        id=uuid4(), type="P2P", channel="APP",
        source_account_id=uuid4(), destination_account_id=uuid4(),
        amount="10.00", currency="USD",
        source_balance_before="100.00", source_balance_after="90.00",
        destination_balance_before="0.00", destination_balance_after="10.00",
        device_id=uuid4(), transaction_date=times[-1],
    )
    ctx = RuleContext(
        payload=payload,
        session=None,
        t_ms=to_ms(times[-1]),
        amount_usd=Decimal("10.00"),
        outgoing=[
            Outgoing(str(i), "P2P", "10.00", to_ms(t)) for i, t in enumerate(times)
        ],
    )
    ctx.on_restricted_list = on_list  # skips the PostgreSQL query
    return ctx


# The contract.


def test_default_catalog_is_valid_and_version_zero():
    snapshot = default_catalog()

    assert snapshot.version == 0
    assert [r.code for r in snapshot.rules] == [r.code for r in DEFAULT_RULES]
    assert catalog.current() == snapshot


def test_every_rule_type_with_code_has_parameters():
    assert set(rules.REGISTRY) <= set(PARAMS_BY_TYPE)


def test_snapshot_survives_a_json_round_trip():
    snapshot = default_catalog()
    assert CatalogSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize(
    "fields",
    [
        dict(code="velocity", type="velocity", action="HOLD",
             params={"window_minutes": 2000, "limit": 5}),  # longer than the history
        dict(code="velocity", type="velocity", action="HOLD",
             params={"limit": 5, "minutes": 10}),           # unknown parameter
        dict(code="velocity", type="velocity", action="WAIT"),
        dict(code="velocity", type="teleport", action="HOLD"),
        dict(code="Velocity!", type="velocity", action="HOLD"),
    ],
    ids=["window-too-long", "unknown-param", "bad-action", "unknown-type", "bad-code"],
)
def test_invalid_rules_are_refused(fields):
    with pytest.raises(ValidationError):
        RuleEntry(**fields)


def test_rule_codes_must_be_unique():
    with pytest.raises(ValidationError):
        _snapshot(_velocity(), _velocity())


# How the engine evaluates it.


def test_parameters_come_from_the_catalog():
    ctx = _context(transfers=3)

    assert evaluate_rules(ctx, _snapshot(_velocity())) == []
    stricter = _velocity(params={"window_minutes": 10, "limit": 2})
    held = evaluate_rules(ctx, _snapshot(stricter))
    assert [r.rule for r in held] == ["velocity"]


def test_decision_case_and_score_come_from_the_catalog():
    [result] = evaluate_rules(
        _context(transfers=6),
        _snapshot(
            _velocity(action="REJECT", opens_case=True, score=40, rule_version=3)
        ),
    )

    assert result.decision == Decision.REJECT
    assert result.opens_case is True
    assert result.score == 40
    assert result.rule_version == 3


def test_disabled_rule_is_not_evaluated():
    ctx = _context(transfers=6)
    assert evaluate_rules(ctx, _snapshot(_velocity(enabled=False))) == []


def test_new_rule_of_an_existing_type_takes_part():
    # HU-19: a second velocity rule with its own code and thresholds.
    hourly = _velocity(code="velocity_1h", params={"window_minutes": 60, "limit": 2})

    triggered = evaluate_rules(_context(transfers=3), _snapshot(_velocity(), hourly))

    assert [r.rule for r in triggered] == ["velocity_1h"]


def test_catalog_order_is_the_evaluation_order():
    ctx = _context(transfers=6, on_list=True)

    first = evaluate_rules(ctx, _snapshot(_restricted(), _velocity()))
    second = evaluate_rules(ctx, _snapshot(_velocity(), _restricted()))

    assert [r.rule for r in first] == ["restricted_list", "velocity"]
    assert [r.rule for r in second] == ["velocity", "restricted_list"]


def test_types_without_code_and_the_default_decision_are_skipped():
    without_code = [
        RuleEntry(code=t, type=t, action="HOLD")
        for t in PARAMS_BY_TYPE
        if t not in rules.REGISTRY and t != "default_timeout"
    ]
    snapshot = _snapshot(
        *without_code,
        RuleEntry(code="default_timeout", type="default_timeout", action="HOLD"),
    )
    assert evaluate_rules(_context(transfers=6), snapshot) == []
