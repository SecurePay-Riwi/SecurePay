"""The inbox, a case with its events, assigning and resolving (HU-26, HU-27, HU-30).

The cases consumer opens the cases and the alerts task escalates them;
these routes read them and, on the analyst's request, change them. Every
change writes its CaseEvent in the same transaction (shared/cases.py).
"""

import math
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import CaseDetail, CaseEventItem, CasePage, CaseSummary
from shared.cases import PENDING, Case, CaseEvent, CaseStatus

router = APIRouter(tags=["Cases"])

MAX_PAGE_SIZE = 100
NOT_FOUND = "Case not found."


def minutes_left(case: Case, now: datetime) -> int | None:
    """Whole minutes until due_at, rounded down (negative once overdue);
    None for a resolved case, which has no limit any more (RN-09)."""
    if case.status == CaseStatus.RESOLVED.value:
        return None
    return math.floor((case.due_at - now).total_seconds() / 60)


def summary(case: Case, now: datetime) -> CaseSummary:
    return CaseSummary(
        id=case.id,
        transaction_id=case.transaction_id,
        account_id=case.account_id,
        status=case.status,
        decision=case.decision,
        rules_triggered=case.rules_triggered,
        risk_score=case.risk_score,
        amount=case.amount,
        currency=case.currency,
        amount_usd=case.amount_usd,
        assignee=case.assignee,
        created_at=case.created_at,
        due_at=case.due_at,
        minutes_left=minutes_left(case, now),
    )


def detail(session: Session, case: Case, now: datetime) -> CaseDetail:
    """The case with its events, oldest first."""
    events = session.scalars(
        select(CaseEvent).where(CaseEvent.case_id == case.id).order_by(CaseEvent.id)
    ).all()
    return CaseDetail(
        **summary(case, now).model_dump(),
        decision_reason=case.decision_reason,
        rules_version=case.rules_version,
        rule_versions=case.rule_versions,
        transaction_date=case.transaction_date,
        transaction=case.transaction,
        escalated_at=case.escalated_at,
        resolved_at=case.resolved_at,
        resolved_by=case.resolved_by,
        outcome=case.outcome,
        final_decision=case.final_decision,
        resolution_note=case.resolution_note,
        evidence_key=case.evidence_key,
        events=[CaseEventItem.model_validate(e) for e in events],
    )


def get_case(session: Session, case_id: UUID, *, for_update: bool = False) -> Case:
    """The case, or 404. for_update locks its row until the commit, so two
    changes (or a change and the escalation) never cross."""
    query = select(Case).where(Case.id == case_id)
    if for_update:
        query = query.with_for_update()
    case = session.scalars(query).first()
    if case is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return case


@router.get("/cases", response_model=CasePage, **docs.CASES)
def list_cases(
    session: Annotated[Session, Depends(deps.get_session)],
    status: Annotated[
        CaseStatus | None,
        Query(description="Only this state. Without it: the pending cases (OPEN and ESCALATED)."),
    ] = None,
    assignee: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Only the cases of this analyst."),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number, from 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Cases per page.")
    ] = 20,
):
    if status is None:
        conditions = [Case.status.in_([s.value for s in PENDING])]
    else:
        conditions = [Case.status == status.value]
    if assignee is not None:
        conditions.append(Case.assignee == assignee)

    total = session.scalar(select(func.count()).select_from(Case).where(*conditions))
    cases = session.scalars(
        select(Case)
        .where(*conditions)
        # Highest risk first; with the same risk, the closest to the
        # 4-hour limit (RN-09). The id keeps pages stable.
        .order_by(Case.risk_score.desc(), Case.due_at, Case.id)
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    now = datetime.now(UTC)
    return CasePage(
        items=[summary(case, now) for case in cases],
        total=total,
        page=page,
        size=size,
    )


@router.get("/cases/{case_id}", response_model=CaseDetail, **docs.CASE)
def read_case(
    case_id: UUID,
    session: Annotated[Session, Depends(deps.get_session)],
):
    return detail(session, get_case(session, case_id), datetime.now(UTC))
