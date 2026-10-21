
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.events import evento_decision
from shared.models import Comercio, Cuenta, ListaRestrictiva, Usuario
from services.decision_engine import idempotency as idem
from services.decision_engine import publisher
from services.decision_engine import velocity
from services.decision_engine.schemas import (
    Decision,
    TransactionRequest,
    TransactionType,
)

# Solo las transferencias entre cuentas cuentan para la velocidad: un pago
# QR va a un comercio y un retiro sale a efectivo.
TIPOS_VELOCIDAD = {TransactionType.P2P}

# Versión de las reglas con que se decidió (el enunciado pide guardarla
# en cada decisión). Mientras las reglas vivan en el código, la versión
# es la del código: se sube al cambiar una regla. Cuando exista la
# administración de reglas, sale de PostgreSQL.
REGLAS_VERSION = "2026.10.1"

# Si varias reglas se activan, gana la más severa.
SEVERIDAD = {Decision.APPROVE: 0, Decision.HOLD: 1, Decision.REJECT: 2}

MOTIVO_SIN_REGLAS = "La transacción no activó las reglas configuradas."


@dataclass(frozen=True)
class ReglaActivada:
    """Lo que dice una regla que se activó."""

    regla: str
    decision: Decision
    motivo: str


def elegir_decision(activadas: list[ReglaActivada]) -> tuple[Decision, str]:
    """Junta lo que dijo cada regla en una sola decisión y su motivo.

    Gana la más severa (rechazar, luego retener). Sin reglas activadas,
    se aprueba. Con dos de la misma severidad, gana la primera evaluada.
    """
    if not activadas:
        return Decision.APPROVE, MOTIVO_SIN_REGLAS

    peor = max(activadas, key=lambda r: SEVERIDAD[r.decision])
    return peor.decision, peor.motivo


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

    # Regla: velocidad. Se registra aunque otra regla decida, porque el
    # intento de transferir cuenta igual.
    transferencias = 0
    if payload.type in TIPOS_VELOCIDAD:
        transferencias = velocity.registrar_y_contar(
            payload.source_account_id, payload.id, payload.transaction_date
        )

    # Se evalúan todas las reglas aunque una ya rechace: la decisión
    # guarda todas las que se activaron.
    activadas = []

    if en_lista:
        activadas.append(ReglaActivada(
            "lista_restrictiva",
            Decision.REJECT,
            "Titular incluido en una lista restrictiva.",
        ))

    if transferencias > velocity.LIMITE:
        activadas.append(ReglaActivada(
            "velocidad",
            Decision.HOLD,
            f"Velocidad: {transferencias} transferencias salientes en "
            f"{velocity.VENTANA_MIN} minutos desde la misma cuenta.",
        ))

    decision, reason = elegir_decision(activadas)

    return {
        "transaction_id": str(payload.id),
        "decision": decision.value,
        "decision_reason": reason,
        "rules_version": REGLAS_VERSION,
        "rules_triggered": [r.regla for r in activadas],
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
