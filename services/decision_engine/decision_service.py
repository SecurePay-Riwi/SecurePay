
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario
from services.decision_engine import idempotency as idem
from services.decision_engine.schemas import Decision, TransactionRequest


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
    """Aplica las reglas y devuelve la decisión, sin guardarla."""
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

    # Regla: lista restrictiva.
    en_lista = (
        session.query(ListaRestrictiva.id)
        .filter(
            ListaRestrictiva.documento
            == normalizar_documento(titular.documento)
        )
        .first()
    )

    # La regla de velocidad vuelve en Valkey, con la hora del evento,
    # en la historia 8.

    if en_lista:
        decision = Decision.REJECT
        reason = "Titular incluido en una lista restrictiva."
    else:
        decision = Decision.APPROVE
        reason = "La transacción no activó las reglas configuradas."

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": reason,
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
    """
    firma = idem.huella(payload.model_dump(mode="json"))

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

    return resultado, False
