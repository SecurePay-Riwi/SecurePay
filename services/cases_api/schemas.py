"""Request and response bodies of the cases API.

Join point: each owner adds the models of their endpoints here. The
tables and states are shared/cases.py; never redefine them.
Money is Decimal (a decimal string in JSON), dates are UTC.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    status: str


# --- Compliance (HU-34) ------------------------------------------------------

class RestrictedListReport(BaseModel):
    """RN-06: one listed document of a transaction (a compliance_reports row)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Report id.")
    case_id: UUID = Field(description="The case the transaction opened.")
    transaction_id: UUID = Field(description="The transaction where the owner took part.")
    account_id: UUID = Field(description="The account whose owner is listed (source or destination).")
    document: str = Field(description="The owner's document, digits only, as the list stores it.")
    list_type: str = Field(description="The list it is on, as the provider names it (e.g. PEP, sanciones).")
    matched_at: datetime = Field(description="When the consumer wrote the report, UTC (right after the decision).")
    notified_at: datetime | None = Field(
        description="When the compliance summary e-mail included it, UTC; null until the next run of the alerts task.",
    )


class RestrictedListReportPage(BaseModel):
    items: list[RestrictedListReport] = Field(description="The reports of the page, newest first.")
    total: int = Field(description="Reports in the period, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Reports per page.")


# --- Reports (HU-35) --------------------------------------------------------

class SuspiciousCase(BaseModel):
    """One compliance case of the period (RN-03, RN-05, RN-06)."""

    case_id: UUID = Field(description="The case.")
    transaction_id: UUID = Field(description="The transaction that opened it.")
    account_id: UUID = Field(description="The main account: the source; in a top-up, the destination.")
    pattern: str = Field(description='The rules that fired, joined by "+" (e.g. mule, splitting+velocity).')
    amount: Decimal = Field(description="Amount in the original currency, as a decimal string.")
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    status: str = Field(description="OPEN, ESCALATED or RESOLVED.")
    outcome: str | None = Field(default=None, description="FRAUD or LEGITIMATE once resolved; null before.")
    created_at: datetime = Field(description="When the case was opened, UTC.")


class SuspiciousReport(BaseModel):
    from_: date = Field(alias="from", description="First day of the period (inclusive), UTC.")
    to: date = Field(description="Last day of the period (inclusive), UTC.")
    items: list[SuspiciousCase] = Field(description="The cases opened in the period, oldest first.")
    total: int = Field(description="Cases in the period.")
    message: str | None = Field(
        default=None,
        description='"No compliance cases in the period." when it is empty; null otherwise.',
    )

    model_config = ConfigDict(populate_by_name=True)


# --- Accounts (HU-28) --------------------------------------------------------

class AccountTransactionItem(BaseModel):
    """One transaction of the account (an account_transactions row).

    The nullable fields are always sent; their default only lets Swagger
    drop a null from an example."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID = Field(description="The transaction.")
    direction: str = Field(description="OUT: the account sent it (source). IN: the account received it (destination).")
    counterparty_account_id: UUID | None = Field(
        default=None,
        description="The other account of the transaction; null in a QR payment, a withdrawal or a top-up.",
    )
    type: str = Field(description="P2P, QR, RECARGA or RETIRO.")
    channel: str = Field(description="Where the transaction was made (APP, WEB, ...).")
    merchant_id: UUID | None = Field(default=None, description="The merchant of a QR payment; null otherwise.")
    amount: Decimal = Field(description="Amount in the account's currency, as a decimal string.")
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    device_id: UUID | None = Field(
        default=None,
        description="The device, only on the main account's row (the source; in a top-up, the destination).",
    )
    decision: str = Field(description="The engine's decision: APPROVE, HOLD or REJECT.")
    decision_reason: str = Field(description="Why the engine decided it.")
    rules_triggered: list[str] = Field(description="The rules that fired, as in the transaction.decided event.")
    risk_score: int = Field(description="Sum of the fired rules' scores, 0 to 100.")
    transaction_date: datetime = Field(description="When the transaction happened, UTC.")
    processed_at: datetime = Field(description="When the engine decided it, UTC.")


class AccountTransactionPage(BaseModel):
    account_id: UUID = Field(description="The account.")
    days: int = Field(description="The window: transactions of the last `days` days.")
    items: list[AccountTransactionItem] = Field(description="The transactions of the page, newest first.")
    total: int = Field(description="Transactions in the window, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Transactions per page.")


# --- Accounts (HU-29) --------------------------------------------------------

class RelatedAccount(BaseModel):
    """Another account that used one of the account's devices."""

    account_id: UUID = Field(description="The related account.")
    device_id: UUID = Field(description="The device both accounts used in the window.")
    last_seen: datetime = Field(
        description="The related account's last transaction on that device in the window, UTC.",
    )
    open_cases: int = Field(description="Cases of the related account that are OPEN or ESCALATED.")


class RelatedAccountList(BaseModel):
    account_id: UUID = Field(description="The account.")
    days: int = Field(description="The window: devices used in the last `days` days.")
    items: list[RelatedAccount] = Field(
        description="One item per related account and shared device, the latest seen first.",
    )
    total: int = Field(description="Items in the list.")
