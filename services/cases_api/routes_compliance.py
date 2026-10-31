"""Restricted list reports (HU-34, RN-06).

The cases consumer writes them (one per listed document of a transaction)
and the alerts task e-mails them to compliance; this route only reads.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import RestrictedListReport, RestrictedListReportPage
from shared.cases import ComplianceReport

router = APIRouter(tags=["Compliance"])

MAX_PAGE_SIZE = 100


def _utc(value: datetime | None) -> datetime | None:
    """A date or time without a time zone is UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@router.get(
    "/compliance/restricted-list-reports",
    response_model=RestrictedListReportPage,
    **docs.RESTRICTED_LIST_REPORTS,
)
def restricted_list_reports(
    session: Annotated[Session, Depends(deps.get_session)],
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="From this time (inclusive), by matched_at."),
    ] = None,
    to: Annotated[
        datetime | None,
        Query(description="Up to this time (exclusive), by matched_at."),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number, from 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Reports per page.")
    ] = 50,
):
    start, end = _utc(from_), _utc(to)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="`from` must not be after `to`.")

    conditions = []
    if start is not None:
        conditions.append(ComplianceReport.matched_at >= start)
    if end is not None:
        conditions.append(ComplianceReport.matched_at < end)

    total = session.scalar(
        select(func.count()).select_from(ComplianceReport).where(*conditions)
    )
    reports = session.scalars(
        select(ComplianceReport)
        .where(*conditions)
        .order_by(ComplianceReport.matched_at.desc(), ComplianceReport.document)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return RestrictedListReportPage(
        items=[RestrictedListReport.model_validate(r) for r in reports],
        total=total,
        page=page,
        size=size,
    )
