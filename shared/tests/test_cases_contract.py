"""The case tables of shared/cases.py, the contract of Sprint 4.

Needs PostgreSQL (DATABASE_URL); runs in a schema of its own.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

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
    in_currency,
    main_account,
    plain_rate,
    rate_values,
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
        event = CaseEvent(
            case_id=case.id,
            type=CaseEventType.CREATED.value,
            actor=SYSTEM_ACTOR,
            at=datetime.now(UTC),
        )
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
        session.execute(
            text("UPDATE case_events SET actor = 'x' WHERE id = :id"), {"id": event_id}
        )


def test_case_events_cannot_be_deleted(Session):
    event_id = _case_with_event(Session)
    with Session() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(
            text("DELETE FROM case_events WHERE id = :id"), {"id": event_id}
        )


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
    transaction = {
        "type": "P2P",
        "source_account_id": "a",
        "destination_account_id": "b",
    }
    assert main_account(transaction) == "a"


def test_main_account_of_a_top_up_is_the_destination():
    transaction = {
        "type": "RECARGA",
        "source_account_id": None,
        "destination_account_id": "b",
    }
    assert main_account(transaction) == "b"


def test_create_schema_adds_the_rate_columns_to_old_tables(Session):
    """HU-43: a database created before Sprint 5 gets usd_rate and
    rate_date (create_all() does not add columns)."""
    with Session() as session:
        for table in ("cases", "account_transactions"):
            session.execute(
                text(f"ALTER TABLE {table} DROP COLUMN usd_rate, DROP COLUMN rate_date")
            )
        session.commit()
        create_schema(session)
        for table in ("cases", "account_transactions"):
            columns = {
                c["name"] for c in inspect(session.connection()).get_columns(table)
            }
            assert {"usd_rate", "rate_date"} <= columns


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("950000.00", "COP", "950000.00"),
        ("25.5", "USD", "25.50"),
        ("25.50", "EUR", "25.50"),
        ("15000.00", "JPY", "15000"),
    ],
)
def test_in_currency_keeps_each_currency_decimals(amount, currency, expected):
    assert str(in_currency(Decimal(amount), currency)) == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("4129.53000000", "4129.53"),
        ("1.00000000", "1"),
        ("4000.00000000", "4000"),
        ("0.86937000", "0.86937"),
    ],
)
def test_plain_rate_has_no_trailing_zeros_nor_exponent(stored, expected):
    assert str(plain_rate(Decimal(stored))) == expected


def test_rate_values_reads_the_decision():
    assert rate_values({"usd_rate": "4129.53", "rate_date": "2026-10-13"}) == {
        "usd_rate": Decimal("4129.53"),
        "rate_date": date(2026, 10, 13),
    }
    assert rate_values({}) == {"usd_rate": None, "rate_date": None}
    with pytest.raises(ValueError):
        rate_values({"usd_rate": "0"})
