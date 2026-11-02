"""Reconciliation differences for treasury (HU-38 to HU-41, RN-10).

The reconciliation (services/reconciliation/) writes the differences;
these routes list them, show their age and resolve them. Tables and
states: shared/reconciliation.py.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import ReconciliationRunItem, ReconciliationRunList
from shared.reconciliation import ReconciliationRun

router = APIRouter(tags=["Reconciliation"])


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
