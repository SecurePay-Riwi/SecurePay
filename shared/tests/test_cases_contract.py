"""The case tables of shared/cases.py, the contract of Sprint 4.

Needs PostgreSQL (DATABASE_URL); runs in a schema of its own.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from shared.cases import (
    CASE_DUE_MINUTES,
    PENDING,
    SYSTEM_ACTOR,
    Case,
    CaseEvent,
    CaseEventType,
    CaseStatus,
    create_schema,
    main_account,
)
from shared.tests.isolated_db import isolated_sessions

TABLES = {"cases", "case_events", "compliance_reports", "account_transactions"}


@pytest.fixture
def Session():
    with isolated_sessions("cases_contract_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


def _case(transaction_id=None) -> Case:
    now = datetime.now(UTC)
    return Case(
        transaction_id=transaction_id or uuid.uuid4(),
        account_id=uuid.uuid4(),
        decision="HOLD",
        decision_reason="Mule account.",
        rules_triggered=["mule"],
        rules_version="0",
        amount="1500.00",
        currency="USD",
        amount_usd="1500.00",
        transaction_date=now,
        transaction={"id": "x"},
        created_at=now,
        due_at=now + timedelta(minutes=CASE_DUE_MINUTES),
    )


def _case_with_event(Session) -> int:
    with Session() as session:
        case = _case()
        session.add(case)
        session.flush()
        event = CaseEvent(case_id=case.id, type=CaseEventType.CREATED.value,
                          actor=SYSTEM_ACTOR, at=datetime.now(UTC))
        session.add(event)
        session.commit()
        return event.id


def test_create_schema_creates_the_tables(Session):
    with Session() as session:
        assert TABLES <= set(inspect(session.connection()).get_table_names())


def test_create_schema_twice_does_not_fail(Session):
    event_id = _case_with_event(Session)
    with Session() as session:
        create_schema(session)
        assert session.get(CaseEvent, event_id) is not None


def test_new_case_defaults(Session):
    with Session() as session:
        case = _case()
        session.add(case)
        session.commit()
        session.refresh(case)
        assert case.status == CaseStatus.OPEN.value
        assert case.risk_score == 0
        assert case.rule_versions == {}


def test_case_events_cannot_be_updated(Session):
    event_id = _case_with_event(Session)
    with Session() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("UPDATE case_events SET actor = 'x' WHERE id = :id"), {"id": event_id})


def test_case_events_cannot_be_deleted(Session):
    event_id = _case_with_event(Session)
    with Session() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM case_events WHERE id = :id"), {"id": event_id})


def test_case_events_cannot_be_truncated(Session):
    _case_with_event(Session)
    with Session() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("TRUNCATE case_events"))


def test_one_case_per_transaction(Session):
    transaction_id = uuid.uuid4()
    with Session() as session:
        session.add(_case(transaction_id))
        session.commit()
    with Session() as session, pytest.raises(IntegrityError):
        session.add(_case(transaction_id))
        session.commit()


def test_pending_states():
    assert set(PENDING) == {CaseStatus.OPEN, CaseStatus.ESCALATED}


def test_main_account_is_the_source():
    transaction = {"type": "P2P", "source_account_id": "a", "destination_account_id": "b"}
    assert main_account(transaction) == "a"


def test_main_account_of_a_top_up_is_the_destination():
    transaction = {"type": "RECARGA", "source_account_id": None, "destination_account_id": "b"}
    assert main_account(transaction) == "b"
