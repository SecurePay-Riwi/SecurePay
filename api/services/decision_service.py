
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from seeds.models import (
    Comercio,
    Dispositivo,
    ListaRestrictiva,
    Transaccion,
    Usuario,
)
from api.schemas import Decision, TransactionRequest


IDEMPOTENCY_WINDOW_SECONDS = int(
    os.getenv("IDEMPOTENCY_WINDOW_SECONDS", "86400")
)
VELOCITY_WINDOW_MINUTES = int(
    os.getenv("VELOCITY_WINDOW_MINUTES", "10")
)
VELOCITY_LIMIT = int(os.getenv("VELOCITY_LIMIT", "5"))
HIGH_AMOUNT_THRESHOLD = int(
    os.getenv("HIGH_AMOUNT_THRESHOLD", "1000000")
)


def _get_processed_at_utc(transaction: Transaccion) -> datetime | None:
    """Normaliza processed_at a una fecha con zona horaria UTC."""
    processed_at = transaction.processed_at

    if processed_at is None:
        return None

    if processed_at.tzinfo is None:
        return processed_at.replace(tzinfo=timezone.utc)

    return processed_at.astimezone(timezone.utc)


def _is_within_idempotency_window(
    transaction: Transaccion,
    now: datetime,
) -> bool:
    """Comprueba si la decisión guardada sigue dentro de la ventana."""
    processed_at = _get_processed_at_utc(transaction)

    if processed_at is None or not transaction.decision:
        return False

    elapsed = (now - processed_at).total_seconds()

    return 0 <= elapsed <= IDEMPOTENCY_WINDOW_SECONDS


def _get_existing_result(
    session: Session,
    transaction_id,
) -> tuple[Transaccion, bool] | None:
    """Recupera una decisión existente si todavía es reutilizable."""
    existing = session.get(Transaccion, transaction_id)

    if existing is None:
        return None

    now = datetime.now(timezone.utc)

    if _is_within_idempotency_window(existing, now):
        return existing, True

    if existing.decision and existing.processed_at:
        raise ValueError(
            "El ID ya existe, pero su ventana de idempotencia expiró."
        )

    raise ValueError(
        "El ID ya existe sin una decisión procesada. "
        "Utiliza un identificador de transacción nuevo."
    )


def process_transaction(
    session: Session,
    payload: TransactionRequest,
) -> tuple[Transaccion, bool]:
    """
    Evalúa y persiste una transacción.

    Devuelve (transacción, replay).
    replay=True indica que se reutilizó una decisión existente.
    """

    if IDEMPOTENCY_WINDOW_SECONDS <= 0:
        raise ValueError("La ventana de idempotencia debe ser positiva.")

    if VELOCITY_WINDOW_MINUTES <= 0 or VELOCITY_LIMIT <= 0:
        raise ValueError("Los parámetros de velocidad deben ser positivos.")

    now = datetime.now(timezone.utc)

    # HU-07: reutilizar primero una decisión ya procesada.
    existing_result = _get_existing_result(session, payload.id)

    if existing_result is not None:
        return existing_result

    # Validar que existan las referencias de la transacción.
    usuario = session.get(Usuario, payload.user_id)
    dispositivo = session.get(Dispositivo, payload.device_id)
    comercio = session.get(Comercio, payload.merchant_id)

    if usuario is None or dispositivo is None or comercio is None:
        raise ValueError("El usuario, dispositivo o comercio no existe.")

    if dispositivo.user_id != payload.user_id:
        raise ValueError("El dispositivo no pertenece al usuario indicado.")

    # Regla 1: lista restrictiva.
    documento_restringido = (
        session.query(ListaRestrictiva.id)
        .filter(ListaRestrictiva.documento == usuario.documento)
        .first()
    )

    # Regla 2: velocidad de transacciones recientes del usuario.
    cutoff = now - timedelta(minutes=VELOCITY_WINDOW_MINUTES)

    transacciones_recientes = (
        session.query(func.count(Transaccion.id))
        .filter(
            Transaccion.user_id == payload.user_id,
            Transaccion.transaction_date >= cutoff,
            Transaccion.transaction_date <= now,
        )
        .scalar()
        or 0
    )

    # Determinar la decisión.
    if documento_restringido:
        decision = Decision.REJECT
        reason = "Usuario incluido en una lista restrictiva."

    elif transacciones_recientes >= VELOCITY_LIMIT:
        decision = Decision.HOLD
        reason = (
            f"Velocidad elevada: ya existen "
            f"{transacciones_recientes} transacciones recientes."
        )

    elif payload.amount >= HIGH_AMOUNT_THRESHOLD:
        decision = Decision.HOLD
        reason = "Importe igual o superior al umbral configurado."

    else:
        decision = Decision.APPROVE
        reason = "La transacción no activó las reglas configuradas."

    transaction = Transaccion(
        id=payload.id,
        user_id=payload.user_id,
        device_id=payload.device_id,
        merchant_id=payload.merchant_id,
        amount=payload.amount,
        transaction_date=payload.transaction_date,
        channel=payload.channel,
        is_fraud=False,
        fraud_pattern=None,
        decision=decision.value,
        decision_reason=reason,
        processed_at=now,
    )

    try:
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return transaction, False

    except IntegrityError:
        # Otra solicitud pudo insertar el mismo ID simultáneamente.
        session.rollback()

        # Tras el rollback, comprobar si esa solicitud guardó la decisión.
        existing_result = _get_existing_result(session, payload.id)

        if existing_result is not None:
            return existing_result

        # Si no existe una decisión reutilizable, propagar el error.
        raise

    except Exception:
        session.rollback()
        raise
