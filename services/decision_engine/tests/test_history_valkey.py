"""Per-account history (history.py) and the velocity rule that counts
over it (velocity.py)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import history, velocity
from services.decision_engine.history import (
    to_ms,
    incoming_key,
    outgoing_key,
    incoming,
    record_incoming,
    record_outgoing,
)
from services.decision_engine.velocity import max_in_window
from shared.cache import get_cache


BASE = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def minuto(m):
    return BASE + timedelta(minutes=m)


@pytest.fixture
def cuenta():
    """Cuenta única por prueba; se omite la prueba si Valkey no está levantado."""
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey no está disponible en VALKEY_URL")

    cuenta_id = str(uuid4())
    yield cuenta_id

    get_cache().delete(outgoing_key(cuenta_id), incoming_key(cuenta_id))


def transferir(cuenta_id, minutos, tipo="P2P"):
    """Registra una salida por cada minuto, en el orden dado, y devuelve
    los ids y el conteo de velocidad que obtuvo cada una."""
    ids, conteos = [], []
    for m in minutos:
        tx_id = str(uuid4())
        ids.append(tx_id)
        salidas = record_outgoing(cuenta_id, tx_id, tipo, "1.00", minuto(m))
        conteos.append(velocity.count(salidas, to_ms(minuto(m))))
    return ids, conteos


def ids_salidas(cuenta_id):
    return [m.split("|")[0] for m in get_cache().zrange(outgoing_key(cuenta_id), 0, -1)]


# Sin infraestructura: la ventana más cargada que contiene a t.


def test_window_counts_only_events_within_ten_minutes():
    horas = [to_ms(minuto(m)) for m in (0, 5, 10, 11)]
    # Para el minuto 10, la ventana [0, 10] tiene 3 y [5, 15] también 3.
    assert max_in_window(horas, to_ms(minuto(10))) == 3


def test_window_includes_later_events_for_a_late_one():
    horas = [to_ms(minuto(m)) for m in (0, 1, 2, 3, 4, 5)]
    # El del minuto 2 está en la ventana [0, 10] con los otros cinco.
    assert max_in_window(horas, to_ms(minuto(2))) == 6


def test_window_edge_is_inclusive():
    horas = [to_ms(minuto(0)), to_ms(minuto(10))]
    assert max_in_window(horas, to_ms(minuto(10))) == 2


def test_velocity_counts_only_p2p_outgoing():
    t = to_ms(minuto(5))
    salidas = [
        history.Outgoing(str(i), tipo, "1.00", to_ms(minuto(i)))
        for i, tipo in enumerate(["P2P", "QR", "RETIRO", "QR", "P2P", "P2P"])
    ]
    assert velocity.count(salidas, t) == 3


# Velocity with Valkey.


def test_six_transfers_in_eight_minutes_pass_the_limit(cuenta):
    _, conteos = transferir(cuenta, [0, 1.6, 3.2, 4.8, 6.4, 8])

    assert conteos == [1, 2, 3, 4, 5, 6]
    assert conteos[-1] > velocity.LIMIT


def test_five_transfers_stay_within_the_limit(cuenta):
    _, conteos = transferir(cuenta, [0, 2, 4, 6, 8])

    assert max(conteos) == velocity.LIMIT


def test_transfers_more_than_ten_minutes_apart_do_not_add_up(cuenta):
    _, conteos = transferir(cuenta, [0, 1, 2, 3, 4, 15])

    assert conteos[-1] == 1


def test_qr_and_withdrawals_in_history_do_not_add_to_velocity(cuenta):
    transferir(cuenta, [0, 1, 2], tipo="QR")
    transferir(cuenta, [3, 4], tipo="RETIRO")
    _, conteos = transferir(cuenta, [5])

    assert len(ids_salidas(cuenta)) == 6
    assert conteos == [1]


def test_late_event_completes_the_window(cuenta):
    # Cinco transferencias en orden y la sexta, del minuto 2, llega al final.
    _, conteos = transferir(cuenta, [0, 1, 3, 4, 5, 2])

    assert conteos[:5] == [1, 2, 3, 4, 5]
    assert conteos[-1] == 6


def test_late_event_outside_the_window_does_not_count(cuenta):
    # Llega tarde pero es de 20 minutos antes: no se junta con las demás.
    _, conteos = transferir(cuenta, [30, 31, 32, 33, 34, 10])

    assert conteos[-1] == 1


# Historial de salidas.


def test_first_movement_of_an_account_has_only_itself(cuenta):
    tx_id = str(uuid4())

    salidas = record_outgoing(cuenta, tx_id, "RETIRO", "250000.00", minuto(0))

    assert salidas == [history.Outgoing(tx_id, "RETIRO", "250000.00", to_ms(minuto(0)))]


def test_outgoing_history_keeps_type_and_amount(cuenta):
    record_outgoing(cuenta, "a", "P2P", "10.50", minuto(0))
    salidas = record_outgoing(cuenta, "b", "QR", "3", minuto(1))

    assert [(s.id, s.type, s.amount) for s in salidas] == [
        ("a", "P2P", "10.50"),
        ("b", "QR", "3"),
    ]


def test_history_follows_event_time_not_arrival(cuenta):
    # Llegan 5, 7, 2, 9, 1: el historial queda 1, 2, 5, 7, 9.
    ids, _ = transferir(cuenta, [5, 7, 2, 9, 1])

    assert ids_salidas(cuenta) == [ids[4], ids[2], ids[0], ids[1], ids[3]]


def test_resent_id_is_not_counted_twice(cuenta):
    tx_id = str(uuid4())
    record_outgoing(cuenta, tx_id, "P2P", "1.00", minuto(0))
    salidas = record_outgoing(cuenta, tx_id, "P2P", "1.00", minuto(0))

    assert len(salidas) == 1


def test_outgoing_history_older_than_retention_is_pruned(cuenta):
    viejo, _ = transferir(cuenta, [0])
    transferir(cuenta, [history.OUT_HOURS * 60 + 1])

    assert viejo[0] not in ids_salidas(cuenta)
    assert 0 < get_cache().ttl(outgoing_key(cuenta)) <= history.OUT_MS // 1000


# Historial de entradas.


def test_incoming_transfers_keep_the_sender_in_event_order(cuenta):
    record_incoming(cuenta, "b", "sender-2", "40000.00", minuto(5))
    record_incoming(cuenta, "a", "sender-1", "25000.00", minuto(1))

    assert incoming(cuenta) == [
        history.Incoming("a", "sender-1", "25000.00", to_ms(minuto(1))),
        history.Incoming("b", "sender-2", "40000.00", to_ms(minuto(5))),
    ]


def test_account_without_incoming_transfers_has_empty_history(cuenta):
    assert incoming(cuenta) == []


def test_incoming_history_older_than_retention_is_pruned(cuenta):
    record_incoming(cuenta, "viejo", "r", "1.00", minuto(0))
    record_incoming(cuenta, "nuevo", "r", "1.00", minuto(history.IN_MINUTES + 1))

    assert [e.id for e in incoming(cuenta)] == ["nuevo"]
    assert 0 < get_cache().ttl(incoming_key(cuenta)) <= history.IN_MS // 1000
