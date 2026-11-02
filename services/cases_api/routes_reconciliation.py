"""Reconciliation differences for treasury (HU-38 to HU-41, RN-10).

The reconciliation (services/reconciliation/) writes the differences;
these routes list them, show their age and resolve them. Tables and
states: shared/reconciliation.py.

    GET  /reconciliation/differences                 HU-38, HU-39, HU-40
    GET  /reconciliation/differences/aging           HU-41
    POST /reconciliation/differences/{id}/resolution HU-41
    GET  /reconciliation/runs                        HU-37 (Habith)
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import (
    AgeRange,
    DifferenceAging,
    DifferenceResolution,
    ReconciliationDifferenceItem,
    ReconciliationDifferencePage,
    ReconciliationRunItem,
    ReconciliationRunList,
)
from shared.reconciliation import (
    AGE_RANGES,
    DifferenceStatus,
    DifferenceType,
    Partner,
    ReconciliationDifference,
    ReconciliationRun,
)

router = APIRouter(tags=["Reconciliation"])


# --- Differences (HU-38 to HU-41) ---------------------------------------------

MAX_PAGE_SIZE = 200
NOT_FOUND = "Difference not found."
RESOLVED = "The difference is resolved; it can no longer change."


def today() -> date:
    """Today in UTC: the age of a difference counts from its run_day (C3)."""
    return datetime.now(UTC).date()


def age_days(difference: ReconciliationDifference, on: date) -> int | None:
    """Whole days from run_day to `on` while PENDING; None once RESOLVED."""
    if difference.status != DifferenceStatus.PENDING.value:
        return None
    return (on - difference.run_day).days


def age_range(days: int) -> str:
    """The AGE_RANGES label of an age (0-1, 2-7, 8+). A day ahead of
    today (a clock skew) counts as 0."""
    days = max(days, 0)
    for label, low, high in AGE_RANGES:
        if days >= low and (high is None or days <= high):
            return label
    raise ValueError(f"no age range for {days} days")


def item(difference: ReconciliationDifference, on: date) -> ReconciliationDifferenceItem:
    answer = ReconciliationDifferenceItem.model_validate(difference)
    answer.age_days = age_days(difference, on)
    return answer


@router.get(
    "/reconciliation/differences",
    response_model=ReconciliationDifferencePage,
    **docs.RECONCILIATION_DIFFERENCES,
)
def list_differences(
    session: Annotated[Session, Depends(deps.get_session)],
    type_: Annotated[
        DifferenceType | None,
        Query(alias="type", description="Only this type. Without it: every type."),
    ] = None,
    partner: Annotated[Partner | None, Query(description="Only this partner.")] = None,
    status: Annotated[
        DifferenceStatus, Query(description="PENDING (default) or RESOLVED."),
    ] = DifferenceStatus.PENDING,
    from_: Annotated[date | None, Query(alias="from", description="From this run_day (inclusive).")] = None,
    to: Annotated[date | None, Query(description="Up to this run_day (inclusive).")] = None,
    page: Annotated[int, Query(ge=1, description="Page number, from 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Differences per page.")
    ] = 50,
):
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(status_code=400, detail="`from` must not be after `to`.")
    conditions = [ReconciliationDifference.status == status.value]
    if type_ is not None:
        conditions.append(ReconciliationDifference.type == type_.value)
    if partner is not None:
        conditions.append(ReconciliationDifference.partner == partner.value)
    if from_ is not None:
        conditions.append(ReconciliationDifference.run_day >= from_)
    if to is not None:
        conditions.append(ReconciliationDifference.run_day <= to)

    total = session.scalar(
        select(func.count()).select_from(ReconciliationDifference).where(*conditions)
    )
    differences = session.scalars(
        select(ReconciliationDifference)
        .where(*conditions)
        # Oldest day first (HU-41), then by partner; the rest keeps pages stable.
        .order_by(ReconciliationDifference.run_day, ReconciliationDifference.partner,
                  ReconciliationDifference.type, ReconciliationDifference.reference)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    on = today()
    return ReconciliationDifferencePage(
        items=[item(d, on) for d in differences], total=total, page=page, size=size,
    )


@router.get(
    "/reconciliation/differences/aging",
    response_model=DifferenceAging,
    **docs.RECONCILIATION_AGING,
)
def differences_aging(
    session: Annotated[Session, Depends(deps.get_session)],
    partner: Annotated[Partner | None, Query(description="Only this partner.")] = None,
):
    conditions = [ReconciliationDifference.status == DifferenceStatus.PENDING.value]
    if partner is not None:
        conditions.append(ReconciliationDifference.partner == partner.value)
    rows = session.execute(
        select(ReconciliationDifference.run_day, ReconciliationDifference.type, func.count())
        .where(*conditions)
        .group_by(ReconciliationDifference.run_day, ReconciliationDifference.type)
    ).all()

    on = today()
    ranges = {label: {t.value: 0 for t in DifferenceType} for label, _, _ in AGE_RANGES}
    for run_day, kind, count in rows:
        ranges[age_range((on - run_day).days)][kind] += count
    return DifferenceAging(
        total=sum(count for _, _, count in rows),
        ranges=[AgeRange(range=label, count=sum(by_type.values()), by_type=by_type)
                for label, by_type in ranges.items()],
    )


@router.post(
    "/reconciliation/differences/{difference_id}/resolution",
    response_model=ReconciliationDifferenceItem,
    **docs.RECONCILIATION_RESOLVE,
)
def resolve_difference(
    difference_id: UUID,
    body: DifferenceResolution,
    session: Annotated[Session, Depends(deps.get_session)],
    x_user: Annotated[str | None, Header(description="Who resolves it (1 to 100 characters).")] = None,
):
    actor = deps.author(x_user)
    # Locked until the commit: two people never resolve the same one.
    difference = session.scalars(
        select(ReconciliationDifference)
        .where(ReconciliationDifference.id == difference_id)
        .with_for_update()
    ).first()
    if difference is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if difference.status == DifferenceStatus.RESOLVED.value:
        raise HTTPException(status_code=409, detail=RESOLVED)
    difference.status = DifferenceStatus.RESOLVED.value
    difference.resolved_at = datetime.now(UTC)
    difference.resolved_by = actor
    difference.resolution_note = body.note
    session.commit()
    return item(difference, today())


# --- Runs (HU-37) ------------------------------------------------------------
# Habith's: the runs of a period with their counts. Yulianis's routes go above.


@router.get("/reconciliation/runs", response_model=ReconciliationRunList, **docs.RECONCILIATION_RUNS)
def reconciliation_runs(
    session: Annotated[Session, Depends(deps.get_session)],
    from_: Annotated[date | None, Query(alias="from", description="From this day (inclusive), by run_day.")] = None,
    to: Annotated[date | None, Query(description="Up to this day (inclusive), by run_day.")] = None,
):
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(status_code=400, detail="`from` must not be after `to`.")
    conditions = []
    if from_ is not None:
        conditions.append(ReconciliationRun.run_day >= from_)
    if to is not None:
        conditions.append(ReconciliationRun.run_day <= to)
    runs = session.scalars(
        select(ReconciliationRun).where(*conditions).order_by(ReconciliationRun.run_day)
    ).all()
    return ReconciliationRunList(items=[ReconciliationRunItem.model_validate(r) for r in runs],
                                 total=len(runs))
