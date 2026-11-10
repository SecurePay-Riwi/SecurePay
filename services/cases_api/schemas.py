"""Request and response bodies of the cases API.

Join point: each owner adds the models of their endpoints here. The
tables and states are shared/cases.py; never redefine them.
Money is Decimal (a decimal string in JSON), dates are UTC.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.cases import CaseOutcome, in_currency, plain_rate

USD_RATE = "Units of the currency per 1 USD the engine used for amount_usd (1 for USD), as a decimal string (RN-11, HU-43); null for decisions older than Sprint 5."
RATE_DATE = "Day of that rate: the transaction's day in UTC, or the last earlier day with a rate; null for decisions older than Sprint 5."


class CurrencyDecimals(BaseModel):
    """A model with amount, currency and usd_rate (HU-43): the amount
    keeps its currency's decimals (JPY has none) although the column
    keeps two, and the rate is answered as the engine gave it, without
    the column's trailing zeros."""

    @model_validator(mode="after")
    def _currency_decimals(self):
        self.amount = in_currency(self.amount, self.currency)
        self.usd_rate = plain_rate(self.usd_rate)
        return self


class Health(BaseModel):
    status: str


# --- Compliance (HU-34) ------------------------------------------------------


class RestrictedListReport(BaseModel):
    """RN-06: one listed document of a transaction (a compliance_reports row)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Report id.")
    case_id: UUID = Field(description="The case the transaction opened.")
    transaction_id: UUID = Field(
        description="The transaction where the owner took part."
    )
    account_id: UUID = Field(
        description="The account whose owner is listed (source or destination)."
    )
    document: str = Field(
        description="The owner's document, digits only, as the list stores it."
    )
    list_type: str = Field(
        description="The list it is on, as the provider names it (e.g. PEP, sanciones)."
    )
    matched_at: datetime = Field(
        description="When the consumer wrote the report, UTC (right after the decision)."
    )
    notified_at: datetime | None = Field(
        description="When the compliance summary e-mail included it, UTC; null until the next run of the alerts task.",
    )


class RestrictedListReportPage(BaseModel):
    items: list[RestrictedListReport] = Field(
        description="The reports of the page, newest first."
    )
    total: int = Field(description="Reports in the period, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Reports per page.")


# --- Reports (HU-35) --------------------------------------------------------


class SuspiciousCase(CurrencyDecimals):
    """One compliance case of the period (RN-03, RN-05, RN-06)."""

    case_id: UUID = Field(description="The case.")
    transaction_id: UUID = Field(description="The transaction that opened it.")
    account_id: UUID = Field(
        description="The main account: the source; in a top-up, the destination."
    )
    pattern: str = Field(
        description='The rules that fired, joined by "+" (e.g. mule, splitting+velocity).'
    )
    amount: Decimal = Field(
        description="Amount in the original currency, as a decimal string with its decimals (JPY: none)."
    )
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    usd_rate: Decimal | None = Field(default=None, description=USD_RATE)
    rate_date: date | None = Field(default=None, description=RATE_DATE)
    status: str = Field(description="OPEN, ESCALATED or RESOLVED.")
    outcome: str | None = Field(
        default=None, description="FRAUD or LEGITIMATE once resolved; null before."
    )
    created_at: datetime = Field(description="When the case was opened, UTC.")


class SuspiciousReport(BaseModel):
    from_: date = Field(
        alias="from", description="First day of the period (inclusive), UTC."
    )
    to: date = Field(description="Last day of the period (inclusive), UTC.")
    items: list[SuspiciousCase] = Field(
        description="The cases opened in the period, oldest first."
    )
    total: int = Field(description="Cases in the period.")
    message: str | None = Field(
        default=None,
        description='"No compliance cases in the period." when it is empty; null otherwise.',
    )

    model_config = ConfigDict(populate_by_name=True)


# --- Accounts (HU-28) --------------------------------------------------------


class AccountTransactionItem(CurrencyDecimals):
    """One transaction of the account (an account_transactions row).

    The nullable fields are always sent; their default only lets Swagger
    drop a null from an example."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID = Field(description="The transaction.")
    direction: str = Field(
        description="OUT: the account sent it (source). IN: the account received it (destination)."
    )
    counterparty_account_id: UUID | None = Field(
        default=None,
        description="The other account of the transaction; null in a QR payment, a withdrawal or a top-up.",
    )
    type: str = Field(description="P2P, QR, RECARGA or RETIRO.")
    channel: str = Field(description="Where the transaction was made (APP, WEB, ...).")
    merchant_id: UUID | None = Field(
        default=None, description="The merchant of a QR payment; null otherwise."
    )
    amount: Decimal = Field(
        description="Amount in the account's currency, as a decimal string with its decimals (JPY: none)."
    )
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    usd_rate: Decimal | None = Field(default=None, description=USD_RATE)
    rate_date: date | None = Field(default=None, description=RATE_DATE)
    device_id: UUID | None = Field(
        default=None,
        description="The device, only on the main account's row (the source; in a top-up, the destination).",
    )
    decision: str = Field(description="The engine's decision: APPROVE, HOLD or REJECT.")
    decision_reason: str = Field(description="Why the engine decided it.")
    rules_triggered: list[str] = Field(
        description="The rules that fired, as in the transaction.decided event."
    )
    risk_score: int = Field(description="Sum of the fired rules' scores, 0 to 100.")
    transaction_date: datetime = Field(
        description="When the transaction happened, UTC."
    )
    processed_at: datetime = Field(description="When the engine decided it, UTC.")


class AccountTransactionPage(BaseModel):
    account_id: UUID = Field(description="The account.")
    days: int = Field(description="The window: transactions of the last `days` days.")
    items: list[AccountTransactionItem] = Field(
        description="The transactions of the page, newest first."
    )
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
    open_cases: int = Field(
        description="Cases of the related account that are OPEN or ESCALATED."
    )


class RelatedAccountList(BaseModel):
    account_id: UUID = Field(description="The account.")
    days: int = Field(description="The window: devices used in the last `days` days.")
    items: list[RelatedAccount] = Field(
        description="One item per related account and shared device, the latest seen first.",
    )
    total: int = Field(description="Items in the list.")


class CaseSender(BaseModel):
    """One account that sent P2P transfers to the case's account before
    the transaction of the case."""

    account_id: UUID = Field(description="The sender.")
    transfers: int = Field(description="P2P transfers it sent in the window.")
    amount_usd: Decimal | None = Field(
        description="Their sum in USD, at the engine's rate of each one; null when none has it.",
    )
    first_at: datetime = Field(description="Its first transfer in the window, UTC.")
    last_at: datetime = Field(description="Its last transfer in the window, UTC.")
    open_cases: int = Field(
        description="Cases of the sender that are OPEN or ESCALATED."
    )


class CaseSenders(BaseModel):
    """CA-02: the network behind a mule case."""

    case_id: UUID = Field(description="The case.")
    account_id: UUID = Field(description="The case's main account, the receiver.")
    minutes: int = Field(description="The window before the case's transaction.")
    since: datetime = Field(description="Start of the window, UTC.")
    until: datetime = Field(
        description="The case's transaction date, UTC: end of the window."
    )
    senders: list[CaseSender] = Field(
        description="One item per sender, the most transfers first.",
    )
    total_senders: int = Field(description="Different senders in the window.")
    received_usd: Decimal = Field(
        description="Everything received in the window, in USD."
    )
    case_amount_usd: Decimal | None = Field(
        description="The case's transaction in USD (the withdrawal of a mule case).",
    )
    case_vs_received_pct: Decimal | None = Field(
        description=(
            "case_amount_usd as a percentage of received_usd, two decimals; "
            "null when nothing was received or the case has no USD amount."
        ),
    )


# --- Cases (HU-26) -----------------------------------------------------------


class CaseSummary(CurrencyDecimals):
    """One case of the inbox. The nullable fields are always sent."""

    id: UUID = Field(description="Case id.")
    transaction_id: UUID = Field(
        description="The transaction that opened it (one case per transaction)."
    )
    account_id: UUID = Field(
        description="The main account: the source; in a top-up, the destination."
    )
    status: str = Field(
        description="OPEN, ESCALATED (still open after due_at, RN-09) or RESOLVED."
    )
    decision: str = Field(description="The engine's decision: APPROVE, HOLD or REJECT.")
    rules_triggered: list[str] = Field(
        description="The rules that fired, as in the transaction.decided event."
    )
    risk_score: int = Field(description="Sum of the fired rules' scores, 0 to 100.")
    amount: Decimal = Field(
        description="Amount in the original currency, as a decimal string with its decimals (JPY: none)."
    )
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    amount_usd: Decimal | None = Field(
        default=None,
        description="The engine's amount in USD (RN-11), as a decimal string; null for decisions older than Sprint 4.",
    )
    usd_rate: Decimal | None = Field(default=None, description=USD_RATE)
    rate_date: date | None = Field(default=None, description=RATE_DATE)
    assignee: str | None = Field(
        default=None, description="The analyst who owns it; null until assigned."
    )
    created_at: datetime = Field(description="When the case was opened, UTC.")
    due_at: datetime = Field(
        description="The 4-hour limit (RN-09): created_at + CASE_DUE_MINUTES, UTC."
    )
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
    type: str = Field(
        description="CREATED, ASSIGNED, ESCALATED, RESOLVED or EVIDENCE_ARCHIVED."
    )
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
    rules_version: str = Field(
        description="The rule catalog version that decided (RN-08)."
    )
    rule_versions: dict[str, int] = Field(
        description="rule_version of each fired rule, by code (RN-08)."
    )
    transaction_date: datetime = Field(
        description="When the transaction happened, UTC."
    )
    transaction: dict = Field(
        description="The transaction as it came in the event (evidence)."
    )
    escalated_at: datetime | None = Field(
        default=None, description="When the alerts task escalated it, UTC."
    )
    resolved_at: datetime | None = Field(
        default=None, description="When it was resolved, UTC."
    )
    resolved_by: str | None = Field(
        default=None, description="The X-User who resolved it."
    )
    outcome: str | None = Field(
        default=None, description="FRAUD or LEGITIMATE, once resolved."
    )
    final_decision: str | None = Field(
        default=None,
        description="REJECT (FRAUD) or APPROVE (LEGITIMATE), set on resolution; what the core applies.",
    )
    resolution_note: str | None = Field(
        default=None, description="The analyst's note on resolution."
    )
    evidence_key: str | None = Field(
        default=None,
        description="S3 key of the archived evidence (RN-12); null until archived.",
    )
    events: list[CaseEventItem] = Field(
        description="What happened to the case, oldest first."
    )


# --- Cases (HU-27) -----------------------------------------------------------


class AssigneeChange(BaseModel):
    """Who owns the case from now on."""

    model_config = ConfigDict(str_strip_whitespace=True)

    assignee: str = Field(
        min_length=1, max_length=100, description="The analyst, 1 to 100 characters."
    )


# --- Cases (HU-30) -----------------------------------------------------------


class Resolution(BaseModel):
    """How the analyst closes the case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    outcome: CaseOutcome = Field(
        description="FRAUD (final_decision REJECT) or LEGITIMATE (final_decision APPROVE).",
    )
    note: str = Field(
        min_length=1, max_length=2000, description="Why, 1 to 2000 characters."
    )


# --- Reconciliation differences (HU-38 to HU-41) ---------------------------


class ReconciliationDifferenceItem(BaseModel):
    """What treasury has to look at: one reconciliation_differences row.

    The nullable fields are always sent; their default only lets Swagger
    drop a null from an example."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Difference id.")
    run_day: date = Field(description="The partners' day reconciled (YYYY-MM-DD).")
    partner: str = Field(
        description="banco_andino, red_corresponsales, cajeros_express or qr_pagos."
    )
    type: str = Field(
        description=(
            "MISSING_IN_PARTNER (approved by PagoSeguro, not in the partner's file), "
            "MISSING_IN_PAGOSEGURO (in the file, not approved by PagoSeguro) or "
            "AMOUNT_MISMATCH (same reference, more than 0.01 apart; RN-10)."
        ),
    )
    reference: str = Field(
        description="PagoSeguro's transaction id (as the partner wrote it, if only theirs)."
    )
    partner_reference: str | None = Field(
        default=None, description="The partner's own reference; null when only ours."
    )
    currency: str = Field(description="The original currency (COP, USD, EUR, JPY).")
    pagoseguro_amount: Decimal | None = Field(
        default=None,
        description="PagoSeguro's amount, with its currency's decimals (JPY: none); null in MISSING_IN_PAGOSEGURO.",
    )
    partner_amount: Decimal | None = Field(
        default=None,
        description="The partner's amount, with its currency's decimals; null in MISSING_IN_PARTNER.",
    )
    amount_difference: Decimal | None = Field(
        default=None,
        description="partner_amount - pagoseguro_amount, only in AMOUNT_MISMATCH.",
    )
    pagoseguro_at: datetime | None = Field(
        default=None, description="When PagoSeguro approved it, UTC."
    )
    partner_at: datetime | None = Field(
        default=None, description="When the partner dated it, UTC."
    )
    status: str = Field(description="PENDING or RESOLVED (final).")
    age_days: int | None = Field(
        default=None,
        description="Whole days from run_day to today (UTC) while PENDING (HU-41); null once RESOLVED.",
    )
    detected_at: datetime = Field(
        description="When the reconciliation first found it, UTC."
    )
    resolved_at: datetime | None = Field(
        default=None, description="When treasury resolved it, UTC."
    )
    resolved_by: str | None = Field(
        default=None, description="The X-User who resolved it."
    )
    resolution_note: str | None = Field(
        default=None, description="Treasury's note on resolution."
    )

    @model_validator(mode="after")
    def _currency_decimals_and_utc(self):
        """The columns keep two decimals; JPY is answered without them.
        PostgreSQL returns times in the session's zone; they go out in UTC."""
        for name in ("pagoseguro_amount", "partner_amount", "amount_difference"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, in_currency(value, self.currency))
        for name in ("pagoseguro_at", "partner_at", "detected_at", "resolved_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is not None:
                setattr(self, name, value.astimezone(UTC))
        return self


class ReconciliationDifferencePage(BaseModel):
    items: list[ReconciliationDifferenceItem] = Field(
        description="The differences of the page: oldest run_day first, then by partner.",
    )
    total: int = Field(description="Differences that match the filters, all pages.")
    page: int = Field(description="Page number, from 1.")
    size: int = Field(description="Differences per page.")


class AgeRange(BaseModel):
    range: str = Field(description="0-1, 2-7 or 8+ days old.")
    count: int = Field(description="Pending differences of that age.")
    by_type: dict[str, int] = Field(
        description="The same count by type: MISSING_IN_PARTNER, MISSING_IN_PAGOSEGURO, AMOUNT_MISMATCH.",
    )


class DifferenceAging(BaseModel):
    total: int = Field(description="Pending differences.")
    ranges: list[AgeRange] = Field(
        description="Always the three ranges, in order, even when empty."
    )


class DifferenceResolution(BaseModel):
    """How treasury closes a difference."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note: str = Field(
        min_length=1,
        max_length=2000,
        description="What was found or done, 1 to 2000 characters.",
    )


# --- Reconciliation runs (HU-37) --------------------------------------------


class ReconciliationRunItem(BaseModel):
    """One day reconciled (a reconciliation_runs row)."""

    model_config = ConfigDict(from_attributes=True)

    run_day: date = Field(description="The partners' day reconciled (YYYY-MM-DD).")
    status: str = Field(description="RUNNING, DONE or FAILED.")
    started_at: datetime = Field(
        description="When the last run of the day started, UTC."
    )
    finished_at: datetime | None = Field(
        default=None, description="When it finished, UTC; null while RUNNING."
    )
    files_read: int = Field(description="Partner files read.")
    records_read: int = Field(description="Detail lines read from them.")
    rows_rejected: int = Field(description="Lines or files that could not be read.")
    matched: int = Field(description="References that matched (RN-10).")
    differences: int = Field(description="Differences the run found.")
    error: str | None = Field(
        default=None,
        description="Why it FAILED: the step and its error; null otherwise.",
    )


class ReconciliationRunList(BaseModel):
    items: list[ReconciliationRunItem] = Field(
        description="The runs of the period, oldest day first."
    )
    total: int = Field(description="Runs in the period.")
