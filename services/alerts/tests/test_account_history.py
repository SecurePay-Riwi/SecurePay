"""The purge of the account history (HU-28, D3) against a schema of its own.

Needs PostgreSQL (DATABASE_URL).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from services.alerts import account_history
from shared.cases import ACCOUNT_HISTORY_DAYS, AccountTransaction, create_schema
from shared.tests.isolated_db import isolated_sessions

NOW = datetime(2026, 10, 31, 14, 5, tzinfo=UTC)


@pytest.fixture
def sessions():
    with isolated_sessions("account_history_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


def _row(factory, transaction_date):
    with factory() as session:
        row = AccountTransaction(
            transaction_id=uuid4(), account_id=uuid4(), direction="OUT", type="P2P",
            channel="APP", amount=Decimal("10.00"), currency="USD", decision="APPROVE",
            decision_reason="Below USD 50.", rules_triggered=[],
            transaction_date=transaction_date, processed_at=transaction_date,
        )
        session.add(row)
        session.commit()
        return row.transaction_id


def _left(factory):
    with factory() as session:
        return set(session.scalars(select(AccountTransaction.transaction_id)))


def test_purge_deletes_what_is_older_than_30_days(sessions):
    old = _row(sessions, NOW - timedelta(days=31))
    _row(sessions, NOW - timedelta(days=ACCOUNT_HISTORY_DAYS, seconds=1))
    edge = _row(sessions, NOW - timedelta(days=ACCOUNT_HISTORY_DAYS))
    recent = _row(sessions, NOW - timedelta(days=1))

    with sessions() as session:
        assert account_history.purge(session, NOW) == 2

    assert _left(sessions) == {edge, recent}
    assert old not in _left(sessions)


def test_purge_twice_deletes_nothing_the_second_time(sessions):
    _row(sessions, NOW - timedelta(days=31))

    with sessions() as session:
        assert account_history.purge(session, NOW) == 1
        assert account_history.purge(session, NOW) == 0
