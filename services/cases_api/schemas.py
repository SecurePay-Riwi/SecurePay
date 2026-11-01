"""Request and response bodies of the cases API.

Join point: each owner adds the models of their endpoints here. The
tables and states are shared/cases.py; never redefine them.
Money is Decimal (a decimal string in JSON), dates are UTC.
"""

from datetime import datetime
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


# --- Cases (HU-26) -----------------------------------------------------------

class CaseSummary(BaseModel):
    """One case of the inbox. The nullable fields are always sent."""

    id: UUID = Field(description="Case id.")
    transaction_id: UUID = Field(description="The transaction that opened it (one case per transaction).")
    account_id: UUID = Field(description="The main account: the source; in a top-up, the destination.")
    status: str = Field(description="OPEN, ESCALATED (still open after due_at, RN-09) or RESOLVED.")
    decision: str = Field(description="The engine's decision: APPROVE, HOLD or REJECT.")
    rules_triggered: list[str] = Field(description="The rules that fired, as in the transaction.decided event.")
    risk_score: int = Field(description="Sum of the fired rules' scores, 0 to 100.")
    amount: Decimal = Field(description="Amount in the original currency, as a decimal string.")
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    assignee: str | None = Field(default=None, description="The analyst who owns it; null until assigned.")
    created_at: datetime = Field(description="When the case was opened, UTC.")
    due_at: datetime = Field(description="The 4-hour limit (RN-09): created_at + CASE_DUE_MINUTES, UTC.")
    minutes_left: int | None = Field(
        default=None,
        description="Whole minutes until due_at, rounded down: negative once it is overdue. Null when RESOLVED.",
    )


class CasePage(BaseModel):
    items: list[CaseSummary] = Field(
        description="The cases of the page: highest risk first, then the closest to due_at.",
    )
    total: int = Field(description="Cases that match the filters, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Cases per page.")


class CaseEventItem(BaseModel):
    """One thing that happened to a case (a case_events row)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Event id; increases with every event.")
    type: str = Field(description="CREATED, ASSIGNED, ESCALATED, RESOLVED or EVIDENCE_ARCHIVED.")
    actor: str = Field(description="The X-User who did it, or `system`.")
    at: datetime = Field(description="When it happened, UTC.")
    data: dict = Field(
        description=(
            'Details by type: ASSIGNED {"from", "to"}; ESCALATED {"due_at"}; '
            'RESOLVED {"outcome", "final_decision", "note"}; '
            'EVIDENCE_ARCHIVED {"bucket", "key", "retain_until"}; CREATED {}.'
        ),
    )


class CaseDetail(CaseSummary):
    """A case with everything it stores and its events."""

    decision_reason: str = Field(description="Why the engine decided it.")
    rules_version: str = Field(description="The rule catalog version that decided (RN-08).")
    rule_versions: dict[str, int] = Field(description="rule_version of each fired rule, by code (RN-08).")
    transaction_date: datetime = Field(description="When the transaction happened, UTC.")
    transaction: dict = Field(description="The transaction as it came in the event (evidence).")
    escalated_at: datetime | None = Field(default=None, description="When the alerts task escalated it, UTC.")
    resolved_at: datetime | None = Field(default=None, description="When it was resolved, UTC.")
    resolved_by: str | None = Field(default=None, description="The X-User who resolved it.")
    outcome: str | None = Field(default=None, description="FRAUD or LEGITIMATE, once resolved.")
    final_decision: str | None = Field(
        default=None,
        description="REJECT (FRAUD) or APPROVE (LEGITIMATE), set on resolution; what the core applies.",
    )
    resolution_note: str | None = Field(default=None, description="The analyst's note on resolution.")
    evidence_key: str | None = Field(
        default=None,
        description="S3 key of the archived evidence (RN-12); null until archived.",
    )
    events: list[CaseEventItem] = Field(description="What happened to the case, oldest first.")


# --- Cases (HU-27) -----------------------------------------------------------

class AssigneeChange(BaseModel):
    """Who owns the case from now on."""

    model_config = ConfigDict(str_strip_whitespace=True)

    assignee: str = Field(min_length=1, max_length=100, description="The analyst, 1 to 100 characters.")
