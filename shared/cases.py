"""Cases, their events, compliance reports and the per-account history.

Written by the consumers (create a case, a restricted list report and the
account history), the cases API (assign, resolve) and the alerts task
(escalate, notify, purge). Each of them imports the tables from here;
nobody else defines columns or states. Not part of the published
securepay-shared package (like rule_catalog.py).

A case moves OPEN -> ESCALATED -> RESOLVED or OPEN -> RESOLVED. Only the
alerts task escalates; RESOLVED is final. Every transition writes one
CaseEvent in the same database transaction as the change, and
case_events is append-only (a trigger rejects UPDATE, DELETE and
TRUNCATE).

The tables have their own metadata (not shared/models.py, which the
seed creates), as services/rules_api/models.py does.
"""

import enum
import os
import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session, declarative_base

# RN-09: 4 hours. In minutes so a demo can shorten it.
CASE_DUE_MINUTES = int(os.getenv("CASE_DUE_MINUTES", "240"))
# HU-28: how long account_transactions keeps a row.
ACCOUNT_HISTORY_DAYS = int(os.getenv("ACCOUNT_HISTORY_DAYS", "30"))
# Actor of the events nobody asked for (create, escalate, archive).
SYSTEM_ACTOR = "system"

# Any constant works; it only has to be the same for every service.
SCHEMA_LOCK = 4181

Base = declarative_base(metadata=MetaData())


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"  # created, waiting for an analyst
    ESCALATED = "ESCALATED"  # still open after due_at (RN-09)
    RESOLVED = "RESOLVED"  # closed with an outcome; final


# The states an analyst still has to work on (the inbox).
PENDING = (CaseStatus.OPEN, CaseStatus.ESCALATED)


class CaseOutcome(str, enum.Enum):
    FRAUD = "FRAUD"  # final_decision REJECT
    LEGITIMATE = "LEGITIMATE"  # final_decision APPROVE


class CaseEventType(str, enum.Enum):
    CREATED = "CREATED"  # consumer (HU-25), data {}
    ASSIGNED = "ASSIGNED"  # cases API (HU-27), data {"from": str | None, "to": str}
    ESCALATED = "ESCALATED"  # alerts task (HU-31), data {"due_at": iso}
    RESOLVED = "RESOLVED"  # cases API (HU-30), data {"outcome", "final_decision", "note"}
    EVIDENCE_ARCHIVED = "EVIDENCE_ARCHIVED"  # evidence.archive (HU-32), data {"bucket", "key", "retain_until"}


class Case(Base):
    """One case per transaction whose decision has opens_case (D1)."""

    __tablename__ = "cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # One case per transaction: a repeated event never opens a second one.
    transaction_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    # Main account: the source; in RECARGA, the destination (main_account()).
    account_id = Column(UUID(as_uuid=True), nullable=False)
    # The engine's decision: APPROVE / HOLD / REJECT.
    decision = Column(String(10), nullable=False)
    decision_reason = Column(Text, nullable=False)
    # ["mule", ...], as in the transaction.decided event.
    rules_triggered = Column(JSONB, nullable=False)
    rules_version = Column(String(20), nullable=False)
    rule_versions = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    risk_score = Column(Integer, nullable=False, default=0, server_default=text("0"))
    # Original currency; amount_usd is the engine's (null only for events
    # without it).
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    amount_usd = Column(Numeric(18, 2), nullable=True)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    # The event's transaction, as it came (evidence).
    transaction = Column(JSONB, nullable=False)
    status = Column(String(10), nullable=False, default=CaseStatus.OPEN.value,
                    server_default=CaseStatus.OPEN.value)
    assignee = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    # created_at + CASE_DUE_MINUTES, with the consumer's clock.
    due_at = Column(DateTime(timezone=True), nullable=False)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(100), nullable=True)
    outcome = Column(String(10), nullable=True)  # CaseOutcome
    # D4: APPROVE (LEGITIMATE) or REJECT (FRAUD), set on resolution.
    final_decision = Column(String(10), nullable=True)
    resolution_note = Column(Text, nullable=True)
    # S3 key of the evidence once archived (HU-32).
    evidence_key = Column(String(300), nullable=True)


class CaseEvent(Base):
    """What happened to a case, in order. Append-only."""

    __tablename__ = "case_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)
    type = Column(String(20), nullable=False)  # CaseEventType
    actor = Column(String(100), nullable=False)  # X-User, or SYSTEM_ACTOR
    at = Column(DateTime(timezone=True), nullable=False)
    data = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))


class ComplianceReport(Base):
    """RN-06: one row per listed document of a transaction (HU-34)."""

    __tablename__ = "compliance_reports"
    __table_args__ = (UniqueConstraint("transaction_id", "document"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    transaction_id = Column(UUID(as_uuid=True), nullable=False)
    # The account whose owner is listed.
    account_id = Column(UUID(as_uuid=True), nullable=False)
    document = Column(String, nullable=False)  # usuarios.documento
    list_type = Column(String, nullable=False)  # listas_restrictivas.tipo
    # When the consumer wrote it ("immediately").
    matched_at = Column(DateTime(timezone=True), nullable=False)
    # Set by the 5-minute compliance summary.
    notified_at = Column(DateTime(timezone=True), nullable=True)


class AccountTransaction(Base):
    """D3: 30 days of transactions per account (HU-28, HU-29). One row per
    account present: OUT for the source, IN for the destination."""

    __tablename__ = "account_transactions"
    __table_args__ = (PrimaryKeyConstraint("transaction_id", "account_id"),)

    transaction_id = Column(UUID(as_uuid=True), nullable=False)
    account_id = Column(UUID(as_uuid=True), nullable=False)
    direction = Column(String(3), nullable=False)  # OUT / IN
    counterparty_account_id = Column(UUID(as_uuid=True), nullable=True)
    type = Column(String(10), nullable=False)  # P2P / QR / RECARGA / RETIRO
    channel = Column(String(30), nullable=False)
    merchant_id = Column(UUID(as_uuid=True), nullable=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    amount_usd = Column(Numeric(18, 2), nullable=True)
    # Only on the main account's row (the same rule as dev:{device}).
    device_id = Column(UUID(as_uuid=True), nullable=True)
    decision = Column(String(10), nullable=False)
    decision_reason = Column(Text, nullable=False)
    rules_triggered = Column(JSONB, nullable=False)
    risk_score = Column(Integer, nullable=False, default=0, server_default=text("0"))
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False)


# The inbox: pending first by risk, then by the time left.
Index("ix_cases_inbox", Case.status, Case.risk_score.desc(), Case.due_at)
Index("ix_cases_account_id", Case.account_id)
Index(
    "ix_account_transactions_account_date",
    AccountTransaction.account_id,
    AccountTransaction.transaction_date.desc(),
)
Index(
    "ix_account_transactions_device_date",
    AccountTransaction.device_id,
    AccountTransaction.transaction_date,
    postgresql_where=AccountTransaction.device_id.isnot(None),
)


APPEND_ONLY_EVENTS = [
    text("""
        CREATE OR REPLACE FUNCTION case_events_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'case_events is append-only';
        END
        $$ LANGUAGE plpgsql
    """),
    text("DROP TRIGGER IF EXISTS case_events_no_change ON case_events"),
    text("""
        CREATE TRIGGER case_events_no_change
        BEFORE UPDATE OR DELETE ON case_events
        FOR EACH ROW EXECUTE FUNCTION case_events_append_only()
    """),
    text("DROP TRIGGER IF EXISTS case_events_no_truncate ON case_events"),
    text("""
        CREATE TRIGGER case_events_no_truncate
        BEFORE TRUNCATE ON case_events
        FOR EACH STATEMENT EXECUTE FUNCTION case_events_append_only()
    """),
]


def main_account(transaction: dict) -> str:
    """The source account; in RECARGA (no source), the destination. The
    same rule as the engine."""
    return str(transaction.get("source_account_id") or transaction["destination_account_id"])


def create_schema(session: Session) -> None:
    """Create the four tables and the append-only trigger if they are
    missing, and commit.

    Idempotent and under an advisory lock, so the cases API, the consumers
    and the alerts task can all call it at startup at the same time.
    """
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK})
    Base.metadata.create_all(session.connection())
    for statement in APPEND_ONLY_EVENTS:
        session.execute(statement)
    session.commit()
