"""The nightly reconciliation with the payment partners (Sprint 5, RN-10).

Four steps, one owner each, that only meet through the shapes below:

    1. read     services/reconciliation/ingest.py  partner files -> StatementRecord
    2. match    services/reconciliation/match.py   records + decisions -> MatchRow
    3. store    services/reconciliation/store.py   MatchRow -> reconciliation_differences
    4. query    services/cases_api/routes_reconciliation.py

Every step imports its enums, records and tables from here; nobody else
defines columns, types or states. to_json() and the *_from_json()
functions are the only code that serializes them (Spark writes the same
keys): amounts are decimal strings ("27.07"), times ISO 8601 in UTC
("2026-10-05T07:45:29+00:00") and days "YYYY-MM-DD".

A partner's file covers one day in the partner's own time zone, so a
top-up at 23:30 in Bogota lands in that day's file although in UTC it is
already the next day. That is why RN-10 accepts dates one day apart.

The tables have their own metadata, like shared/cases.py. Not part of the
published securepay-shared package.
"""

import enum
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session, declarative_base

# RN-10: a record matches when the amount differs by at most 0.01 and the
# dates by at most one day (both limits included).
AMOUNT_TOLERANCE = Decimal("0.01")
DATE_TOLERANCE_DAYS = 1

# Any constant works; it only has to be the same for every service.
SCHEMA_LOCK = 5237


class Partner(str, enum.Enum):
    BANCO_ANDINO = "banco_andino"  # RECARGA via APP or WEB, UTC
    RED_CORRESPONSALES = "red_corresponsales"  # RECARGA and RETIRO at CORRESPONSAL, UTC-5
    CAJEROS_EXPRESS = "cajeros_express"  # RETIRO at CAJERO, UTC-5
    QR_PAGOS = "qr_pagos"  # QR, UTC


# Hours from UTC of the day a partner writes in its file (Bogota has no
# daylight saving time since 1993, so a fixed offset is exact).
PARTNER_UTC_OFFSET = {
    "banco_andino": 0,
    "red_corresponsales": -5,
    "cajeros_express": -5,
    "qr_pagos": 0,
}


def partner_for(tx_type: str, channel: str) -> Partner | None:
    """Which partner sees a PagoSeguro transaction; None for P2P and the
    rest (no partner sees a transfer inside the wallet)."""
    if tx_type == "RECARGA" and channel in ("APP", "WEB"):
        return Partner.BANCO_ANDINO
    if tx_type in ("RECARGA", "RETIRO") and channel == "CORRESPONSAL":
        return Partner.RED_CORRESPONSALES
    if tx_type == "RETIRO" and channel == "CAJERO":
        return Partner.CAJEROS_EXPRESS
    if tx_type == "QR":
        return Partner.QR_PAGOS
    return None


def partner_zone(partner: Partner | str) -> timezone:
    """The fixed time zone a partner writes its dates in."""
    return timezone(timedelta(hours=PARTNER_UTC_OFFSET[Partner(partner).value]))


def partner_day(partner: Partner | str, at: datetime) -> date:
    """The day of `at` in the partner's own time zone: the file it goes in."""
    if at.tzinfo is None:
        raise ValueError("partner_day needs a time with a time zone")
    return at.astimezone(partner_zone(partner)).date()


class MatchStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    ONLY_PAGOSEGURO = "ONLY_PAGOSEGURO"  # ours, not in the partner's file
    ONLY_PARTNER = "ONLY_PARTNER"  # in the file, not ours
    AMOUNT_OFF = "AMOUNT_OFF"  # same reference, |diff| > 0.01
    DATE_OFF = "DATE_OFF"  # same reference, dates > 1 day apart


class DifferenceType(str, enum.Enum):
    MISSING_IN_PARTNER = "MISSING_IN_PARTNER"
    MISSING_IN_PAGOSEGURO = "MISSING_IN_PAGOSEGURO"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"


class DifferenceStatus(str, enum.Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"  # final


class RunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


# Age ranges of pending differences (HU-41): (label, min days, max days or None).
AGE_RANGES = (("0-1", 0, 1), ("2-7", 2, 7), ("8+", 8, None))


# --- The records the steps hand each other ---------------------------------


@dataclass(frozen=True)
class StatementRecord:
    """One detail line of a partner file, normalized (output of ingest)."""

    partner: str  # Partner value
    statement_day: date  # the file's day (partner time zone)
    file_name: str  # e.g. banco_andino_20261005_v2.csv
    line_number: int  # 1-based, in that file
    pagoseguro_reference: str  # our transaction id as the partner wrote it
    partner_reference: str
    tx_type: str  # RECARGA, RETIRO or QR
    currency: str
    amount: Decimal  # real precision (88.910 -> 88.91)
    transaction_at: datetime  # converted to UTC


@dataclass(frozen=True)
class RejectedRow:
    """A line of a partner file that could not be read, or a whole file
    that is missing or whose control record does not add up."""

    partner: str
    file_name: str
    line_number: int  # 0 when it is about the whole file
    raw: str
    reason: str  # English, e.g. "amount is not a number"


@dataclass(frozen=True)
class MatchRow:
    """One per reference and day (output of match)."""

    run_day: date
    partner: str
    status: str  # MatchStatus value
    reference: str  # PagoSeguro reference (ours or as the partner wrote it)
    partner_reference: str | None
    currency: str
    pagoseguro_amount: Decimal | None
    partner_amount: Decimal | None
    pagoseguro_at: datetime | None
    partner_at: datetime | None


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("times must have a time zone")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def to_json(row) -> dict:
    """StatementRecord, RejectedRow or MatchRow -> a JSON-safe dict."""
    return {key: _json_value(value) for key, value in asdict(row).items()}


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _time(value) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"time without a time zone: {value}")
    return parsed.astimezone(UTC)


def _check_keys(cls, d: dict) -> None:
    missing = {f.name for f in fields(cls)} - d.keys()
    if missing:
        raise ValueError(f"{cls.__name__} is missing {sorted(missing)}")


def record_from_json(d: dict) -> StatementRecord:
    _check_keys(StatementRecord, d)
    return StatementRecord(
        partner=d["partner"],
        statement_day=date.fromisoformat(d["statement_day"]),
        file_name=d["file_name"],
        line_number=int(d["line_number"]),
        pagoseguro_reference=d["pagoseguro_reference"],
        partner_reference=d["partner_reference"],
        tx_type=d["tx_type"],
        currency=d["currency"],
        amount=_decimal(d["amount"]),
        transaction_at=_time(d["transaction_at"]),
    )


def match_row_from_json(d: dict) -> MatchRow:
    _check_keys(MatchRow, d)
    return MatchRow(
        run_day=date.fromisoformat(d["run_day"]),
        partner=d["partner"],
        status=MatchStatus(d["status"]).value,
        reference=d["reference"],
        partner_reference=d["partner_reference"],
        currency=d["currency"],
        pagoseguro_amount=_decimal(d["pagoseguro_amount"]),
        partner_amount=_decimal(d["partner_amount"]),
        pagoseguro_at=_time(d["pagoseguro_at"]),
        partner_at=_time(d["partner_at"]),
    )


# --- Tables ----------------------------------------------------------------

Base = declarative_base(metadata=MetaData())


class ReconciliationRun(Base):
    """One per day reconciled. A repeated run of the same day updates it."""

    __tablename__ = "reconciliation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_day = Column(Date, nullable=False, unique=True)
    status = Column(String(10), nullable=False, default=RunStatus.RUNNING.value,
                    server_default=RunStatus.RUNNING.value)  # RunStatus
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    files_read = Column(Integer, nullable=False, default=0, server_default=text("0"))
    records_read = Column(Integer, nullable=False, default=0, server_default=text("0"))
    rows_rejected = Column(Integer, nullable=False, default=0, server_default=text("0"))
    matched = Column(Integer, nullable=False, default=0, server_default=text("0"))
    differences = Column(Integer, nullable=False, default=0, server_default=text("0"))
    # Why the run is FAILED (the step and its error).
    error = Column(Text, nullable=True)


class ReconciliationDifference(Base):
    """What treasury has to look at (HU-38 to HU-41). A RESOLVED one is
    final: running the day again neither duplicates nor reopens it."""

    __tablename__ = "reconciliation_differences"
    __table_args__ = (UniqueConstraint("run_day", "partner", "type", "reference"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("reconciliation_runs.id"), nullable=False)
    run_day = Column(Date, nullable=False)
    partner = Column(String(30), nullable=False)  # Partner
    type = Column(String(30), nullable=False)  # DifferenceType
    reference = Column(String(100), nullable=False)
    partner_reference = Column(String(100), nullable=True)
    currency = Column(String(3), nullable=False)
    pagoseguro_amount = Column(Numeric(18, 2), nullable=True)
    partner_amount = Column(Numeric(18, 2), nullable=True)
    # partner - pagoseguro, only in AMOUNT_MISMATCH.
    amount_difference = Column(Numeric(18, 2), nullable=True)
    pagoseguro_at = Column(DateTime(timezone=True), nullable=True)
    partner_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(10), nullable=False, default=DifferenceStatus.PENDING.value,
                    server_default=DifferenceStatus.PENDING.value)  # DifferenceStatus
    detected_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(100), nullable=True)
    resolution_note = Column(Text, nullable=True)


# Treasury's list: pending first, oldest day first.
Index(
    "ix_reconciliation_differences_status_day",
    ReconciliationDifference.status,
    ReconciliationDifference.run_day,
)


def create_schema(session: Session) -> None:
    """Create the two tables if they are missing, and commit.

    Idempotent and under an advisory lock, so the cases API and the
    reconciliation can both call it at startup at the same time.
    """
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK})
    Base.metadata.create_all(session.connection())
    session.commit()
