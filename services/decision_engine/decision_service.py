
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.events import evento_decision
from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario
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

NO_RULES_REASON = "La transacción no activó las reglas configuradas."


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


class ReferenciaInvalida(Exception):
    """La transacción nombra una cuenta o un comercio que no sirve."""


def normalizar_documento(documento: str) -> str:
    """Deja solo los dígitos, que es como se guarda la lista restrictiva."""
    return re.sub(r"\D", "", documento)


def _cargar_cuenta(session: Session, cuenta_id) -> Cuenta:
    cuenta = session.get(Cuenta, cuenta_id)

    if cuenta is None:
        raise ReferenciaInvalida(f"La cuenta {cuenta_id} no existe.")

    return cuenta


def _decidir(session: Session, payload: TransactionRequest) -> dict:
    """Apply the rules and return the decision, without storing it."""
    cuentas = {
        cuenta_id: _cargar_cuenta(session, cuenta_id)
        for cuenta_id in (
            payload.source_account_id,
            payload.destination_account_id,
        )
        if cuenta_id is not None
    }

    if payload.merchant_id is not None:
        if session.get(Comercio, payload.merchant_id) is None:
            raise ReferenciaInvalida(
                f"El comercio {payload.merchant_id} no existe."
            )

    # La cuenta principal es la de origen; en una recarga, la de destino.
    principal = cuentas[
        payload.source_account_id or payload.destination_account_id
    ]

    if principal.moneda != payload.currency:
        raise ReferenciaInvalida(
            "La moneda de la transacción no es la de la cuenta."
        )

    titular = session.get(Usuario, principal.user_id)

    # Rule: restricted list.
    en_lista = (
        session.query(ListaRestrictiva.id)
        .filter(
            ListaRestrictiva.documento
            == normalizar_documento(titular.documento)
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

    if en_lista:
        triggered.append(TriggeredRule(
            "restricted_list",
            Decision.REJECT,
            "Titular incluido en una lista restrictiva.",
        ))

    if transfers > velocity.LIMIT:
        triggered.append(TriggeredRule(
            "velocity",
            Decision.HOLD,
            f"Velocidad: {transfers} transferencias salientes en "
            f"{velocity.WINDOW_MIN} minutos desde la misma cuenta.",
        ))

    decision, reason = choose_decision(triggered)

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": reason,
        "rules_version": RULES_VERSION,
        "rules_triggered": [r.rule for r in triggered],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def process_transaction(
    session: Session,
    payload: TransactionRequest,
) -> tuple[dict, bool]:
    """
    Evalúa una transacción una sola vez por id.

    Devuelve (resultado, replay).
    replay=True indica que se reutilizó una decisión existente.

    Solo la primera decisión se publica en SNS: un reenvío devuelve la
    decisión guardada sin volver a publicarla.
    """
    transaccion = payload.model_dump(mode="json")
    firma = idem.huella(transaccion)

    previo = idem.reservar(payload.id, firma)

    if previo:
        return previo, True

    try:
        resultado = _decidir(session, payload)
    except Exception:
        # Sin decisión no hay nada que repetir: el reintento debe decidir.
        idem.liberar(payload.id)
        raise

    idem.guardar(payload.id, firma, resultado)

    # No espera a SNS: deja el evento para el hilo de fondo y sigue.
    publisher.publicar(evento_decision(transaccion, resultado))

    return resultado, False
