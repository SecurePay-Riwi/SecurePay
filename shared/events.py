"""Evento de decisión: lo que el motor publica en SNS y leen los consumidores.

El motor y los consumidores se despliegan por separado (Fargate y Lambda),
así que el formato vive aquí, en un solo lugar. Si cambia de forma
incompatible, se sube EVENT_VERSION para que un consumidor viejo lo
rechace en vez de leerlo mal.
"""

import json

EVENT_TYPE = "transaction.decided"
EVENT_VERSION = 1

CAMPOS_DECISION = ("transaction_id", "decision", "decision_reason", "processed_at")


class EventoInvalido(ValueError):
    """El mensaje no es un evento de decisión que este código sepa leer."""


def evento_decision(transaccion: dict, resultado: dict) -> dict:
    """Arma el evento con la transacción tal como llegó y la decisión."""
    return {
        "event_type": EVENT_TYPE,
        "event_version": EVENT_VERSION,
        "transaction": transaccion,
        "decision": resultado,
    }


def leer_evento(cuerpo: str) -> dict:
    """Convierte el cuerpo de un mensaje de SQS en evento, o falla."""
    try:
        evento = json.loads(cuerpo)
    except (TypeError, ValueError) as exc:
        raise EventoInvalido("El mensaje no es JSON.") from exc

    if not isinstance(evento, dict):
        raise EventoInvalido("El mensaje no es un objeto JSON.")

    if (
        evento.get("event_type") != EVENT_TYPE
        or evento.get("event_version") != EVENT_VERSION
    ):
        raise EventoInvalido(
            f"Tipo o versión desconocidos: {evento.get('event_type')} "
            f"v{evento.get('event_version')}."
        )

    if not isinstance(evento.get("transaction"), dict) or not isinstance(
        evento.get("decision"), dict
    ):
        raise EventoInvalido("Al evento le falta la transacción o la decisión.")

    faltan = [c for c in CAMPOS_DECISION if c not in evento["decision"]]
    if faltan:
        raise EventoInvalido(f"A la decisión le faltan campos: {faltan}.")

    return evento
