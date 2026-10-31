"""History consumer (HU-28): the 30-day history of every account (D3).

For each ``transaction.decided`` event, one ``account_transactions`` row
per account present in the transaction: ``OUT`` for the source and
``IN`` for the destination, with the other one as counterparty. A QR
payment or a withdrawal has only the source; a top-up (RECARGA) only the
destination. Every decision is written, APPROVE, HOLD or REJECT: the
analyst sees the attempts too.

``device_id`` goes only on the main account's row (``main_account()``:
the source; in a top-up, the destination), the same rule as the engine's
``dev:{device}``. The related accounts (HU-29) are read from there.

Amounts stay in the account's currency, with the engine's ``amount_usd``
(null for events older than Sprint 4). The cases API reads the table
(``GET /accounts/{account_id}/transactions``) and the alerts task deletes
the rows older than ``ACCOUNT_HISTORY_DAYS`` (``account_history.purge``).

The insert is ``ON CONFLICT (transaction_id, account_id) DO NOTHING``, so
a repeated event (SNS and SQS deliver at least once) writes nothing
twice. One session and one database transaction per batch. A message
that cannot be read as history is checked before writing and fails
alone in batchItemFailures; if PostgreSQL fails, nothing is committed
and the whole batch goes back to the queue (after 5 attempts, the DLQ).

D3 replaced the device–account pairs in DynamoDB of the original design:
they stay a design idea, they are not built in Sprint 4.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from services.consumers.batch import leer_lote, respuesta
from shared import db
from shared.cases import AccountTransaction, main_account

log = logging.getLogger(__name__)

OUT = "OUT"
IN = "IN"

# The tests point it at a schema of their own.
SessionLocal = db.SessionLocal


class NotHistory(ValueError):
    """The event lacks what a history row needs."""


def _datetime(value) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"date without time zone: {value}")
    return parsed


def _uuid(value) -> UUID | None:
    return None if value in (None, "") else UUID(str(value))


def history_rows(event: dict) -> list[dict]:
    """The account_transactions rows of one event: OUT for the source and
    IN for the destination, when present.

    Everything is checked here, before touching the database, so a broken
    event fails alone instead of breaking the batch's transaction.
    """
    transaction = event["transaction"]
    decision = event["decision"]
    try:
        source = _uuid(transaction.get("source_account_id"))
        destination = _uuid(transaction.get("destination_account_id"))
        if source is None and destination is None:
            raise ValueError("the transaction has no account")
        main = UUID(main_account(transaction))
        rules_triggered = decision["rules_triggered"]
        if not isinstance(rules_triggered, list):
            raise TypeError("rules_triggered must be a list")
        amount_usd = decision.get("amount_usd")
        common = {
            "transaction_id": UUID(str(decision["transaction_id"])),
            "type": str(transaction["type"]),
            "channel": str(transaction["channel"]),
            "merchant_id": _uuid(transaction.get("merchant_id")),
            "amount": Decimal(str(transaction["amount"])),
            "currency": str(transaction["currency"]),
            "amount_usd": None if amount_usd is None else Decimal(str(amount_usd)),
            "decision": str(decision["decision"]),
            "decision_reason": str(decision["decision_reason"]),
            "rules_triggered": rules_triggered,
            "risk_score": int(decision.get("risk_score") or 0),
            "transaction_date": _datetime(transaction["transaction_date"]),
            "processed_at": _datetime(decision["processed_at"]),
        }
        device = _uuid(transaction.get("device_id"))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise NotHistory(f"{type(exc).__name__}: {exc}") from exc

    rows = []
    for account, direction, counterparty in (
        (source, OUT, destination),
        (destination, IN, source),
    ):
        # A transfer to the same account has one row (the primary key).
        if account is None or any(r["account_id"] == account for r in rows):
            continue
        rows.append(
            {
                **common,
                "account_id": account,
                "direction": direction,
                "counterparty_account_id": counterparty,
                "device_id": device if account == main else None,
            }
        )
    return rows


def write(session, rows: list[dict]) -> int:
    """Insert the rows, skipping the ones already there. Returns how many
    were new."""
    written = session.execute(
        insert(AccountTransaction)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[AccountTransaction.transaction_id, AccountTransaction.account_id]
        )
        .returning(AccountTransaction.transaction_id)
    ).all()
    return len(written)


def handler(event, context=None):
    valid, failed = leer_lote(event)

    rows, pending = [], []
    for message_id, decided in valid:
        try:
            rows += history_rows(decided)
            pending.append(message_id)
        except NotHistory as exc:
            log.error("Message %s cannot be written to the history: %s", message_id, exc)
            failed.append(message_id)

    if not rows:
        return respuesta(failed)

    try:
        with SessionLocal() as session:
            written = write(session, rows)
            session.commit()
    except SQLAlchemyError:
        # Nothing was committed: the whole batch goes back to the queue.
        log.exception(
            "History: PostgreSQL failed; %d messages return to the queue", len(pending)
        )
        return respuesta(failed + pending)

    log.info(
        "History: %d row(s) written for %d event(s) (%d already there)",
        written,
        len(pending),
        len(rows) - written,
    )
    return respuesta(failed)
