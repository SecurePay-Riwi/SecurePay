"""The 30-day history of an account and its related accounts (HU-28, HU-29).

The history consumer writes ``account_transactions`` (one row per account
of each transaction) and the alerts task deletes what is older than
``ACCOUNT_HISTORY_DAYS``; these routes only read.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.cases_api import deps, docs
from services.cases_api.schemas import AccountTransactionItem, AccountTransactionPage
from shared.cases import ACCOUNT_HISTORY_DAYS, AccountTransaction

router = APIRouter(tags=["Accounts"])

MAX_PAGE_SIZE = 100


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=AccountTransactionPage,
    **docs.ACCOUNT_TRANSACTIONS,
)
def account_transactions(
    account_id: UUID,
    session: Annotated[Session, Depends(deps.get_session)],
    days: Annotated[
        int,
        Query(ge=1, le=ACCOUNT_HISTORY_DAYS,
              description=f"Transactions of the last `days` days (1 to {ACCOUNT_HISTORY_DAYS})."),
    ] = ACCOUNT_HISTORY_DAYS,
    page: Annotated[int, Query(ge=1, description="Page number, from 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Transactions per page.")
    ] = 50,
):
    since = datetime.now(UTC) - timedelta(days=days)
    conditions = [
        AccountTransaction.account_id == account_id,
        AccountTransaction.transaction_date >= since,
    ]

    total = session.scalar(
        select(func.count()).select_from(AccountTransaction).where(*conditions)
    )
    rows = session.scalars(
        select(AccountTransaction)
        .where(*conditions)
        .order_by(AccountTransaction.transaction_date.desc(),
                  AccountTransaction.transaction_id)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return AccountTransactionPage(
        account_id=account_id,
        days=days,
        items=[AccountTransactionItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )
