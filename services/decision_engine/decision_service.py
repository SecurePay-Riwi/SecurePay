
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as DecisionTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from shared.events import evento_decision
from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario
from services.decision_engine import currency
from services.decision_engine import history
from services.decision_engine import idempotency as idem
from services.decision_engine import publisher
from services.decision_engine import velocity
from services.decision_engine.schemas import (
    Decision,
    TransactionRequest,
    TransactionType,
)

# What leaves the source account goes into its outgoing history.
# A top-up has no source account.
OUTGOING_TYPES = {TransactionType.P2P, TransactionType.QR, TransactionType.RETIRO}

# Version of the rules a decision was made with (the project brief asks
# to store it with every decision). While the rules live in the code,
# the version is the code's: raise it when a rule changes. Once rules
# administration exists, it comes from PostgreSQL.
RULES_VERSION = "2026.10.1"

# When several rules fire, the most severe wins.
SEVERITY = {Decision.APPROVE: 0, Decision.HOLD: 1, Decision.REJECT: 2}

NO_RULES_REASON = "The transaction did not trigger any configured rule."

log = logging.getLogger(__name__)

# RN-01: every transaction gets a decision in 200 ms. The engine stops
# waiting for the rules well before that, so the default decision and
# the network still fit in the budget.
TIMEOUT_MS = int(os.getenv("DECISION_TIMEOUT_MS", "120"))
# RN-01 default when the rules do not answer in time: approve below this
# amount, hold from it up.
DEFAULT_LIMIT_USD = Decimal(os.getenv("DEFAULT_DECISION_LIMIT_USD", "50"))
# Threads that evaluate the rules. A decision that times out keeps its
# thread until it ends, so this matches the requests FastAPI serves at
# once (40 by default).
WORKERS = int(os.getenv("DECISION_WORKERS", "40"))

if TIMEOUT_MS <= 0 or DEFAULT_LIMIT_USD <= 0 or WORKERS <= 0:
    raise ValueError("Timeout, default limit and workers must be positive.")

DEFAULT_RULE = "default_timeout"

# Set on the session when a decision outlives its request: the late
# thread closes the session, not the request (see main.get_db).
LATE_SESSION = "closed_by_late_decision"

_workers = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="decision")


@dataclass(frozen=True)
class TriggeredRule:
    """What a rule that fired says."""

    rule: str
    decision: Decision
    reason: str


def choose_decision(triggered: list[TriggeredRule]) -> tuple[Decision, str]:
    """Turn what each rule said into one decision and its reason.

    The most severe wins (reject, then hold). With no rule fired, the
    transaction is approved. Between two of the same severity, the first
    one evaluated wins.
    """
    if not triggered:
        return Decision.APPROVE, NO_RULES_REASON

    worst = max(triggered, key=lambda r: SEVERITY[r.decision])
    return worst.decision, worst.reason


class InvalidReference(Exception):
    """The transaction names an account or a merchant that cannot be used."""


def normalize_document(document: str) -> str:
    """Keep only the digits, which is how the restricted list is stored."""
    return re.sub(r"\D", "", document)


def _load_account(session: Session, account_id) -> Cuenta:
    account = session.get(Cuenta, account_id)

    if account is None:
        raise InvalidReference(f"Account {account_id} does not exist.")

    return account


def _decide(session: Session, payload: TransactionRequest) -> dict:
    """Apply the rules and return the decision, without storing it."""
    accounts = {
        account_id: _load_account(session, account_id)
        for account_id in (
            payload.source_account_id,
            payload.destination_account_id,
        )
        if account_id is not None
    }

    if payload.merchant_id is not None:
        if session.get(Comercio, payload.merchant_id) is None:
            raise InvalidReference(
                f"Merchant {payload.merchant_id} does not exist."
            )

    # The main account is the source; in a top-up, the destination.
    main_account = accounts[
        payload.source_account_id or payload.destination_account_id
    ]

    if main_account.moneda != payload.currency:
        raise InvalidReference(
            "The transaction currency is not the account currency."
        )

    owner = session.get(Usuario, main_account.user_id)

    # Rule: restricted list.
    on_list = (
        session.query(ListaRestrictiva.id)
        .filter(
            ListaRestrictiva.documento
            == normalize_document(owner.documento)
        )
        .first()
    )

    # Account history: written before deciding, whatever the decision,
    # because the attempt counts too (see history.py).
    outgoing = []
    if payload.type in OUTGOING_TYPES:
        outgoing = history.record_outgoing(
            payload.source_account_id,
            payload.id,
            payload.type.value,
            payload.amount,
            payload.transaction_date,
        )
    if payload.type == TransactionType.P2P:
        history.record_incoming(
            payload.destination_account_id,
            payload.id,
            payload.source_account_id,
            payload.amount,
            payload.transaction_date,
        )

    # Rule: velocity, only when the transaction is a transfer.
    transfers = 0
    if payload.type.value in velocity.TYPES:
        transfers = velocity.count(
            outgoing, history.to_ms(payload.transaction_date)
        )

    # Every rule is evaluated even if one already rejects: the decision
    # records all the rules that fired.
    triggered = []

    if on_list:
        triggered.append(TriggeredRule(
            "restricted_list",
            Decision.REJECT,
            "Account owner is on a restricted list.",
        ))

    if transfers > velocity.LIMIT:
        triggered.append(TriggeredRule(
            "velocity",
            Decision.HOLD,
            f"Velocity: {transfers} outgoing transfers in "
            f"{velocity.WINDOW_MIN} minutes from the same account.",
        ))

    decision, reason = choose_decision(triggered)

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": reason,
        "rules_version": RULES_VERSION,
        "rules_triggered": [r.rule for r in triggered],
        "by_default": False,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def default_decision(payload: TransactionRequest) -> dict:
    """RN-01: the decision when the rules do not answer in time.

    Approve below USD 50, hold from USD 50 up. Never reject: being slow
    is not a reason to turn a customer down.
    """
    amount_usd = currency.to_usd(payload.amount, payload.currency)

    if amount_usd < DEFAULT_LIMIT_USD:
        decision = Decision.APPROVE
    else:
        decision = Decision.HOLD

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": (
            f"Default decision: the rules did not answer in {TIMEOUT_MS} ms "
            f"(USD {amount_usd}, limit USD {DEFAULT_LIMIT_USD})."
        ),
        "rules_version": RULES_VERSION,
        "rules_triggered": [DEFAULT_RULE],
        "by_default": True,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def _decide_in_time(session: Session, payload: TransactionRequest) -> dict:
    """Run the rules, or answer with the default decision if they take
    longer than TIMEOUT_MS.

    A Python thread cannot be stopped, so the late evaluation finishes in
    the background and its result is dropped: the stored and published
    decision is the default one. It keeps the session, so it closes it.
    """
    future = _workers.submit(_decide, session, payload)

    try:
        return future.result(timeout=TIMEOUT_MS / 1000)
    except DecisionTimeout:
        session.info[LATE_SESSION] = True
        future.add_done_callback(lambda _: _close_late(session, payload.id))
        log.warning("Transaction %s: rules timed out, default decision", payload.id)
        return default_decision(payload)


def _close_late(session: Session, tx_id) -> None:
    try:
        session.close()
    except Exception:
        log.exception("Transaction %s: could not close the late session", tx_id)


def process_transaction(
    session: Session,
    payload: TransactionRequest,
) -> tuple[dict, bool]:
    """
    Evaluate a transaction only once per id.

    Returns (result, replay).
    replay=True means an existing decision was reused.

    Only the first decision is published to SNS: a resend returns the
    stored decision without publishing it again.
    """
    transaction = payload.model_dump(mode="json")
    fingerprint = idem.huella(transaction)

    previous = idem.reservar(payload.id, fingerprint)

    if previous:
        return previous, True

    try:
        result = _decide_in_time(session, payload)
    except Exception:
        # No decision means nothing to replay: the retry must decide.
        idem.liberar(payload.id)
        raise

    idem.guardar(payload.id, fingerprint, result)

    # Does not wait for SNS: hands the event to the background thread.
    publisher.publicar(evento_decision(transaction, result))

    return result, False
