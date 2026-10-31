"""Cases consumer (HU-25) against an empty PostgreSQL schema of its own.

Needs PostgreSQL (DATABASE_URL); the seed's tables are not used.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from services.consumers import cases
from shared.cases import (
    CASE_DUE_MINUTES,
    SYSTEM_ACTOR,
    Case,
    CaseEvent,
    CaseEventType,
    CaseStatus,
    create_schema,
)
from shared.events import evento_decision
from shared.tests.isolated_db import isolated_sessions


@pytest.fixture
def sessions(monkeypatch):
    with isolated_sessions("cases_consumer_test") as factory:
        with factory() as session:
            create_schema(session)
        monkeypatch.setattr(cases, "SessionLocal", factory)
        yield factory


def _event(
    rules=("mule",),
    decision="HOLD",
    opens_case=True,
    tx_type="RETIRO",
    source=True,
    **decision_fields,
):
    tx_id = str(uuid4())
    transaction = {
        "id": tx_id,
        "type": tx_type,
        "channel": "APP",
        "source_account_id": str(uuid4()) if source else None,
        "destination_account_id": str(uuid4()),
        "merchant_id": None,
        "amount": "950000.00",
        "currency": "COP",
        "device_id": str(uuid4()),
        "transaction_date": "2026-10-13T20:00:00Z",
    }
    result = {
        "transaction_id": tx_id,
        "decision": decision,
        "decision_reason": "Test decision.",
        "rules_version": "3",
        "rules_triggered": list(rules),
        "rule_versions": {rule: 1 for rule in rules},
        "opens_case": opens_case,
        "amount_usd": "230.05",
        "risk_score": 50,
        "by_default": False,
        "processed_at": "2026-10-13T20:00:00.010000+00:00",
    }
    result.update(decision_fields)
    return evento_decision(transaction, result)


def _batch(*bodies):
    return {
        "Records": [
            {
                "messageId": f"m{i}",
                "receiptHandle": f"r{i}",
                "body": body if isinstance(body, str) else json.dumps(body),
            }
            for i, body in enumerate(bodies)
        ]
    }


def _cases(factory):
    with factory() as session:
        return session.scalars(select(Case)).all()


def _events(factory, case_id):
    with factory() as session:
        return session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
        ).all()


def test_a_mule_decision_opens_a_case_with_its_created_event(sessions):
    event = _event(rules=("mule",))
    before = datetime.now(UTC)

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    [case] = _cases(sessions)
    tx = event["transaction"]
    assert case.transaction_id == UUID(tx["id"])
    assert case.account_id == UUID(tx["source_account_id"])
    assert case.status == CaseStatus.OPEN.value
    assert case.decision == "HOLD"
    assert case.decision_reason == "Test decision."
    assert case.rules_triggered == ["mule"]
    assert case.rules_version == "3"
    assert case.rule_versions == {"mule": 1}
    assert case.risk_score == 50
    assert case.amount == Decimal("950000.00")
    assert case.currency == "COP"
    assert case.amount_usd == Decimal("230.05")
    assert case.transaction_date == datetime(2026, 10, 13, 20, tzinfo=UTC)
    assert case.transaction == tx
    assert case.assignee is None
    # due_at counts from the consumer's clock, not from transaction_date.
    assert case.created_at >= before
    assert case.due_at - case.created_at == timedelta(minutes=CASE_DUE_MINUTES)

    [created] = _events(sessions, case.id)
    assert created.type == CaseEventType.CREATED.value
    assert created.actor == SYSTEM_ACTOR
    assert created.at == case.created_at
    assert created.data == {}


def test_the_same_event_twice_opens_one_case(sessions):
    body = json.dumps(_event())

    # In two batches (a redelivery) and twice in the same batch.
    assert cases.handler(_batch(body)) == {"batchItemFailures": []}
    assert cases.handler(_batch(body, body)) == {"batchItemFailures": []}

    [case] = _cases(sessions)
    assert len(_events(sessions, case.id)) == 1


def test_a_velocity_hold_without_opens_case_opens_nothing(sessions):
    event = _event(rules=("velocity",), decision="HOLD", opens_case=False)

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    assert _cases(sessions) == []


def test_an_approve_without_opens_case_opens_nothing(sessions):
    event = _event(rules=(), decision="APPROVE", opens_case=False)

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    assert _cases(sessions) == []


def test_a_splitting_approve_opens_a_compliance_case(sessions):
    """Carried over from Sprint 3 (HU-15, MAG-131 / MAG-146): splitting
    approves the transaction but opens a compliance case (RN-05)."""
    event = _event(rules=("splitting",), decision="APPROVE", tx_type="P2P")

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    [case] = _cases(sessions)
    assert case.status == CaseStatus.OPEN.value
    assert case.decision == "APPROVE"
    assert case.rules_triggered == ["splitting"]
    assert [e.type for e in _events(sessions, case.id)] == [CaseEventType.CREATED.value]


def test_a_restricted_list_reject_opens_a_case(sessions):
    event = _event(rules=("restricted_list",), decision="REJECT", tx_type="P2P")

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    [case] = _cases(sessions)
    assert case.decision == "REJECT"


def test_a_top_up_case_belongs_to_the_destination_account(sessions):
    event = _event(
        rules=("restricted_list",), decision="REJECT", tx_type="RECARGA", source=False
    )

    cases.handler(_batch(event))

    [case] = _cases(sessions)
    assert case.account_id == UUID(event["transaction"]["destination_account_id"])


def test_an_event_without_amount_usd_still_opens_a_case(sessions):
    event = _event()
    del event["decision"]["amount_usd"]

    assert cases.handler(_batch(event)) == {"batchItemFailures": []}

    [case] = _cases(sessions)
    assert case.amount_usd is None


def test_a_broken_event_fails_alone(sessions):
    good = _event()
    no_amount = _event()
    del no_amount["transaction"]["amount"]
    bad_id = _event()
    bad_id["decision"]["transaction_id"] = "not-a-uuid"

    result = cases.handler(_batch(good, "not json", no_amount, bad_id))

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "m1"},
            {"itemIdentifier": "m2"},
            {"itemIdentifier": "m3"},
        ]
    }
    [case] = _cases(sessions)
    assert case.transaction_id == UUID(good["transaction"]["id"])


def test_postgresql_down_returns_the_whole_batch(monkeypatch):
    down = sessionmaker(bind=create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x"))
    monkeypatch.setattr(cases, "SessionLocal", down)
    velocity = _event(rules=("velocity",), opens_case=False)

    result = cases.handler(_batch(_event(), _event(), velocity))

    # The two that open a case go back to the queue; the velocity HOLD
    # needed nothing from PostgreSQL and is acknowledged.
    assert result == {
        "batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m1"}]
    }


def test_a_failed_batch_writes_nothing(sessions, monkeypatch):
    calls = []
    real_open_case = cases.open_case

    def fail_on_second(session, values):
        calls.append(1)
        if len(calls) == 2:
            raise cases.SQLAlchemyError("connection lost")
        return real_open_case(session, values)

    monkeypatch.setattr(cases, "open_case", fail_on_second)

    result = cases.handler(_batch(_event(), _event()))

    assert result == {
        "batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m1"}]
    }
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Case)) == 0
        assert session.scalar(select(func.count()).select_from(CaseEvent)) == 0
