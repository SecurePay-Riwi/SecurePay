"""Cases consumer (HU-25, HU-34): opens a case for each decision that asks
for one and reports the listed documents to compliance.

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

RN-06 (HU-34): when ``restricted_list`` fired, the same database
transaction writes one ``compliance_reports`` row per listed document of
the owners of the source and destination accounts, looked up in
PostgreSQL the way the engine does it (only the digits of
``usuarios.documento`` against ``listas_restrictivas.documento``). The
insert is ``ON CONFLICT (transaction_id, document) DO NOTHING``, so a
repeated event writes no second report. A report belongs to a case: if
the catalog turns off ``opens_case`` for ``restricted_list``, there is
no case and no report. The alerts task e-mails the new reports to
compliance every 5 minutes (``services/alerts/compliance_summary.py``).
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select
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
    ComplianceReport,
    main_account,
)
from shared.models import Cuenta, ListaRestrictiva, Usuario

log = logging.getLogger(__name__)

RESTRICTED_LIST = "restricted_list"

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


def listed_parties(event: dict) -> list[UUID]:
    """The accounts whose owners must be checked against the restricted
    list: source and destination, when ``restricted_list`` fired.
    Checked before touching the database, like case_values()."""
    if RESTRICTED_LIST not in event["decision"]["rules_triggered"]:
        return []
    transaction = event["transaction"]
    try:
        return [
            UUID(str(transaction[key]))
            for key in ("source_account_id", "destination_account_id")
            if transaction.get(key)
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise NotACase(f"{type(exc).__name__}: {exc}") from exc


def listed_documents(session, accounts: list[UUID]) -> list[tuple[UUID, str, str]]:
    """(account, document, list type) of each owner of these accounts who
    is on the restricted list. Only the digits of the owner's document
    are compared, as the engine does (normalize_document())."""
    digits = func.regexp_replace(Usuario.documento, r"\D", "", "g")
    rows = session.execute(
        select(Cuenta.id, ListaRestrictiva.documento, ListaRestrictiva.tipo)
        .join(Usuario, Usuario.id == Cuenta.user_id)
        .join(ListaRestrictiva, ListaRestrictiva.documento == digits)
        .where(Cuenta.id.in_(accounts))
        .order_by(ListaRestrictiva.documento)
    )
    return [tuple(row) for row in rows]


def report_listed(
    session, case_id: UUID | None, values: dict, accounts: list[UUID]
) -> int:
    """RN-06: one compliance_reports row per listed document. Returns how
    many were written (0 for a repeated event).

    When the case already existed (a repeated event) its id is looked up,
    so a report the first delivery missed is still written."""
    transaction_id = values["transaction_id"]
    if case_id is None:
        case_id = session.scalar(
            select(Case.id).where(Case.transaction_id == transaction_id)
        )
    listed = listed_documents(session, accounts)
    if not listed:
        log.warning(
            "Cases: restricted_list fired for transaction %s but no owner is "
            "listed now; no compliance report",
            transaction_id,
        )
        return 0
    written = session.execute(
        insert(ComplianceReport)
        .values(
            [
                {
                    "case_id": case_id,
                    "transaction_id": transaction_id,
                    "account_id": account_id,
                    "document": document,
                    "list_type": list_type,
                    "matched_at": values["created_at"],
                }
                for account_id, document, list_type in listed
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[ComplianceReport.transaction_id, ComplianceReport.document]
        )
        .returning(ComplianceReport.id)
    ).all()
    return len(written)


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
            cases.append(
                (message_id, case_values(decided, now), listed_parties(decided))
            )
        except NotACase as exc:
            log.error("Message %s cannot open a case: %s", message_id, exc)
            failed.append(message_id)

    if not cases:
        return respuesta(failed)

    try:
        with SessionLocal() as session:
            opened, reported = [], []
            for _, values, accounts in cases:
                case_id = open_case(session, values)
                opened.append(case_id)
                reported.append(
                    report_listed(session, case_id, values, accounts) if accounts else 0
                )
            session.commit()
    except SQLAlchemyError:
        # Nothing was committed: the whole batch goes back to the queue.
        log.exception(
            "Cases: PostgreSQL failed; %d messages return to the queue", len(cases)
        )
        return respuesta(failed + [message_id for message_id, _, _ in cases])

    for (_, values, _), case_id, reports in zip(cases, opened, reported):
        if reports:
            log.info(
                "Cases: %d restricted list report(s) for transaction %s",
                reports,
                values["transaction_id"],
            )
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
