"""Cases consumer (HU-25): opens a case for each decision that asks for one.

Only the decisions with ``opens_case`` open a case (D1, team decision of
2026-10-13): by default mule account, splitting and restricted list. The
rest are acknowledged and do nothing; a velocity HOLD opens no case.

One case per transaction: the insert is ``ON CONFLICT (transaction_id) DO
NOTHING`` and the CREATED event is written only when the case was
inserted, so a repeated event (SNS and SQS deliver at least once) never
opens a second case nor writes a second CREATED.

One session and one database transaction per batch. A message that cannot
be read as a case is reported in batchItemFailures and the rest of the
batch goes on; if PostgreSQL fails, the whole batch returns to the queue
(after 5 attempts it goes to the DLQ). No event is lost in silence.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from services.consumers.batch import leer_lote, respuesta
from shared import db
from shared.cases import (
    CASE_DUE_MINUTES,
    SYSTEM_ACTOR,
    Case,
    CaseEvent,
    CaseEventType,
    CaseStatus,
    main_account,
)

log = logging.getLogger(__name__)

# The tests point it at a schema of their own.
SessionLocal = db.SessionLocal


class NotACase(ValueError):
    """The event asks for a case but lacks what a case needs."""


def _datetime(value) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"date without time zone: {value}")
    return parsed


def case_values(event: dict, now: datetime) -> dict:
    """The columns of the case for an event with opens_case.

    Everything is checked here, before touching the database, so a broken
    event fails alone instead of breaking the batch's transaction.
    """
    transaction = event["transaction"]
    decision = event["decision"]
    try:
        amount_usd = decision.get("amount_usd")
        rules_triggered = decision["rules_triggered"]
        rule_versions = decision.get("rule_versions") or {}
        if not isinstance(rules_triggered, list) or not isinstance(rule_versions, dict):
            raise TypeError(
                "rules_triggered must be a list and rule_versions an object"
            )
        return {
            "transaction_id": UUID(str(decision["transaction_id"])),
            "account_id": UUID(main_account(transaction)),
            "decision": str(decision["decision"]),
            "decision_reason": str(decision["decision_reason"]),
            "rules_triggered": rules_triggered,
            "rules_version": str(decision["rules_version"]),
            "rule_versions": rule_versions,
            "risk_score": int(decision.get("risk_score") or 0),
            "amount": Decimal(str(transaction["amount"])),
            "currency": str(transaction["currency"]),
            "amount_usd": None if amount_usd is None else Decimal(str(amount_usd)),
            "transaction_date": _datetime(transaction["transaction_date"]),
            "transaction": transaction,
            "status": CaseStatus.OPEN.value,
            "created_at": now,
            "due_at": now + timedelta(minutes=CASE_DUE_MINUTES),
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise NotACase(f"{type(exc).__name__}: {exc}") from exc


def open_case(session, values: dict) -> UUID | None:
    """Insert the case and its CREATED event. Returns the new case's id, or
    None if the transaction already had a case (nothing is written)."""
    case_id = session.execute(
        insert(Case)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[Case.transaction_id])
        .returning(Case.id)
    ).scalar_one_or_none()

    if case_id is not None:
        session.add(
            CaseEvent(
                case_id=case_id,
                type=CaseEventType.CREATED.value,
                actor=SYSTEM_ACTOR,
                at=values["created_at"],
                data={},
            )
        )
    return case_id


def handler(event, context=None):
    valid, failed = leer_lote(event)
    now = datetime.now(UTC)

    cases = []
    for message_id, decided in valid:
        decision = decided["decision"]
        if not decision.get("opens_case"):
            continue
        try:
            cases.append((message_id, case_values(decided, now)))
        except NotACase as exc:
            log.error("Message %s cannot open a case: %s", message_id, exc)
            failed.append(message_id)

    if not cases:
        return respuesta(failed)

    try:
        with SessionLocal() as session:
            opened = [open_case(session, values) for _, values in cases]
            session.commit()
    except SQLAlchemyError:
        # Nothing was committed: the whole batch goes back to the queue.
        log.exception(
            "Cases: PostgreSQL failed; %d messages return to the queue", len(cases)
        )
        return respuesta(failed + [message_id for message_id, _ in cases])

    for (_, values), case_id in zip(cases, opened):
        if case_id is None:
            log.info(
                "Cases: transaction %s already has a case", values["transaction_id"]
            )
        else:
            log.info(
                "Cases: case %s opened for transaction %s (%s)",
                case_id,
                values["transaction_id"],
                ", ".join(values["rules_triggered"]),
            )
    return respuesta(failed)
