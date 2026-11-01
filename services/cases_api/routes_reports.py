"""Report of suspicious operations for compliance (HU-35).

Every case is a compliance case (D1: only the decisions with opens_case
open one: mule account RN-03, splitting RN-05, restricted list RN-06), so
the report lists the cases opened in a period, as JSON or as a CSV file.
"""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import SuspiciousCase, SuspiciousReport
from shared.cases import Case

router = APIRouter(tags=["Reports"])

MAX_DAYS = 31
EMPTY = "No compliance cases in the period."
CSV_COLUMNS = [
    "case_id", "transaction_id", "account_id", "pattern", "amount",
    "currency", "amount_usd", "status", "outcome", "created_at",
]


class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"


def period(start: date, end: date) -> tuple[datetime, datetime]:
    """Both days inclusive, in UTC: [start 00:00, the day after end 00:00)."""
    if start > end:
        raise HTTPException(status_code=400, detail="`from` must not be after `to`.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"The period can have at most {MAX_DAYS} days.")
    return (datetime.combine(start, time.min, UTC),
            datetime.combine(end + timedelta(days=1), time.min, UTC))


def row(case: Case) -> SuspiciousCase:
    return SuspiciousCase(
        case_id=case.id,
        transaction_id=case.transaction_id,
        account_id=case.account_id,
        pattern="+".join(case.rules_triggered),
        amount=case.amount,
        currency=case.currency,
        amount_usd=case.amount_usd,
        status=case.status,
        outcome=case.outcome,
        created_at=case.created_at,
    )


def to_csv(items: list[SuspiciousCase]) -> str:
    """One line per case under a header. Amounts as decimal text (never
    scientific notation); an empty value for null."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for item in items:
        values = item.model_dump()
        writer.writerow([
            "" if values[c] is None
            else format(values[c], "f") if c in ("amount", "amount_usd")
            else values[c].astimezone(UTC).isoformat() if c == "created_at"
            else str(values[c])
            for c in CSV_COLUMNS
        ])
    return out.getvalue()


@router.get("/reports/suspicious", response_model=SuspiciousReport, **docs.SUSPICIOUS_REPORT)
def suspicious_report(
    session: Annotated[Session, Depends(deps.get_session)],
    from_: Annotated[date, Query(alias="from", description="First day (inclusive), YYYY-MM-DD, UTC.")],
    to: Annotated[date, Query(description="Last day (inclusive), YYYY-MM-DD, UTC.")],
    report_format: Annotated[
        ReportFormat,
        Query(alias="format", description="json (default) or csv, a file to download."),
    ] = ReportFormat.JSON,
):
    start, end = period(from_, to)
    cases = session.scalars(
        select(Case)
        .where(Case.created_at >= start, Case.created_at < end)
        .order_by(Case.created_at, Case.id)
    ).all()
    items = [row(case) for case in cases]

    if report_format is ReportFormat.CSV:
        filename = f"suspicious-report-{from_.isoformat()}-{to.isoformat()}.csv"
        return Response(
            content=to_csv(items),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return SuspiciousReport(
        from_=from_,
        to=to,
        items=items,
        total=len(items),
        message=None if items else EMPTY,
    )
