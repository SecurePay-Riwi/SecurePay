"""The cases API against an empty PostgreSQL schema of its own, so the
tables of the dev database are never touched.

Needs PostgreSQL (DATABASE_URL).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.cases_api import deps
from services.cases_api.main import app
from shared.cases import SYSTEM_ACTOR, Case, CaseEvent, CaseEventType, CaseStatus
from shared.tests.isolated_db import isolated_sessions


@pytest.fixture
def sessions():
    """The session factory the API uses during the test."""
    with isolated_sessions("cases_api_test") as factory:
        previous = deps.SessionLocal
        deps.bind(factory)
        try:
            yield factory
        finally:
            deps.bind(previous)


@pytest.fixture
def client(sessions):
    # The context runs the lifespan: create_schema().
    with TestClient(app) as c:
        yield c


@pytest.fixture
def add_case(sessions, client):
    """Insert a case and its CREATED event; returns the case id.

    due_in is the time left until due_at (negative: overdue). Depends on
    client so the tables exist (create_schema runs in its lifespan).
    """

    def add(
        *,
        risk_score: int = 50,
        due_in: timedelta = timedelta(hours=4),
        status: CaseStatus = CaseStatus.OPEN,
        assignee: str | None = None,
        rules_triggered: tuple[str, ...] = ("mule",),
        amount: str = "100.00",
        currency: str = "USD",
        amount_usd: str | None = "100.00",
    ):
        now = datetime.now(UTC)
        tx_id = uuid4()
        account = uuid4()
        case = Case(
            transaction_id=tx_id,
            account_id=account,
            decision="HOLD",
            decision_reason="Test case.",
            rules_triggered=list(rules_triggered),
            rules_version="1",
            rule_versions={rule: 1 for rule in rules_triggered},
            risk_score=risk_score,
            amount=Decimal(amount),
            currency=currency,
            amount_usd=None if amount_usd is None else Decimal(amount_usd),
            transaction_date=now,
            transaction={"id": str(tx_id), "type": "RETIRO",
                         "source_account_id": str(account), "amount": amount,
                         "currency": currency},
            status=status.value,
            assignee=assignee,
            created_at=now,
            due_at=now + due_in,
        )
        if status is CaseStatus.ESCALATED:
            case.escalated_at = now
        if status is CaseStatus.RESOLVED:
            case.resolved_at = now
            case.resolved_by = "ana"
            case.outcome = "LEGITIMATE"
            case.final_decision = "APPROVE"
            case.resolution_note = "Known customer."
        with sessions() as session:
            session.add(case)
            session.flush()
            session.add(CaseEvent(case_id=case.id, type=CaseEventType.CREATED.value,
                                  actor=SYSTEM_ACTOR, at=now, data={}))
            session.commit()
            return case.id

    return add
