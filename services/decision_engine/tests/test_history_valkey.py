"""Historial por cuenta (history.py) y la regla de velocidad que cuenta
sobre él (velocity.py)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import history, velocity
from services.decision_engine.history import (
    a_ms,
    clave_entradas,
    clave_salidas,
    entradas,
    registrar_entrada,
    registrar_salida,
)
from services.decision_engine.velocity import max_en_ventana
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

    get_cache().delete(clave_salidas(cuenta_id), clave_entradas(cuenta_id))


def transferir(cuenta_id, minutos, tipo="P2P"):
    """Registra una salida por cada minuto, en el orden dado, y devuelve
    los ids y el conteo de velocidad que obtuvo cada una."""
    ids, conteos = [], []
    for m in minutos:
        tx_id = str(uuid4())
        ids.append(tx_id)
        salidas = registrar_salida(cuenta_id, tx_id, tipo, "1.00", minuto(m))
        conteos.append(velocity.contar(salidas, a_ms(minuto(m))))
    return ids, conteos


def ids_salidas(cuenta_id):
    return [m.split("|")[0] for m in get_cache().zrange(clave_salidas(cuenta_id), 0, -1)]


# Sin infraestructura: la ventana más cargada que contiene a t.


def test_window_counts_only_events_within_ten_minutes():
    horas = [a_ms(minuto(m)) for m in (0, 5, 10, 11)]
    # Para el minuto 10, la ventana [0, 10] tiene 3 y [5, 15] también 3.
    assert max_en_ventana(horas, a_ms(minuto(10))) == 3


def test_window_includes_later_events_for_a_late_one():
    horas = [a_ms(minuto(m)) for m in (0, 1, 2, 3, 4, 5)]
    # El del minuto 2 está en la ventana [0, 10] con los otros cinco.
    assert max_en_ventana(horas, a_ms(minuto(2))) == 6


def test_window_edge_is_inclusive():
    horas = [a_ms(minuto(0)), a_ms(minuto(10))]
    assert max_en_ventana(horas, a_ms(minuto(10))) == 2


def test_velocity_counts_only_p2p_outgoing():
    t = a_ms(minuto(5))
    salidas = [
        history.Salida(str(i), tipo, "1.00", a_ms(minuto(i)))
        for i, tipo in enumerate(["P2P", "QR", "RETIRO", "QR", "P2P", "P2P"])
    ]
    assert velocity.contar(salidas, t) == 3


# Velocidad con Valkey.


def test_six_transfers_in_eight_minutes_pass_the_limit(cuenta):
    _, conteos = transferir(cuenta, [0, 1.6, 3.2, 4.8, 6.4, 8])

    assert conteos == [1, 2, 3, 4, 5, 6]
    assert conteos[-1] > velocity.LIMITE


def test_five_transfers_stay_within_the_limit(cuenta):
    _, conteos = transferir(cuenta, [0, 2, 4, 6, 8])

    assert max(conteos) == velocity.LIMITE


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

    salidas = registrar_salida(cuenta, tx_id, "RETIRO", "250000.00", minuto(0))

    assert salidas == [history.Salida(tx_id, "RETIRO", "250000.00", a_ms(minuto(0)))]


def test_outgoing_history_keeps_type_and_amount(cuenta):
    registrar_salida(cuenta, "a", "P2P", "10.50", minuto(0))
    salidas = registrar_salida(cuenta, "b", "QR", "3", minuto(1))

    assert [(s.id, s.tipo, s.monto) for s in salidas] == [
        ("a", "P2P", "10.50"),
        ("b", "QR", "3"),
    ]


def test_history_follows_event_time_not_arrival(cuenta):
    # Llegan 5, 7, 2, 9, 1: el historial queda 1, 2, 5, 7, 9.
    ids, _ = transferir(cuenta, [5, 7, 2, 9, 1])

    assert ids_salidas(cuenta) == [ids[4], ids[2], ids[0], ids[1], ids[3]]


def test_resent_id_is_not_counted_twice(cuenta):
    tx_id = str(uuid4())
    registrar_salida(cuenta, tx_id, "P2P", "1.00", minuto(0))
    salidas = registrar_salida(cuenta, tx_id, "P2P", "1.00", minuto(0))

    assert len(salidas) == 1


def test_outgoing_history_older_than_retention_is_pruned(cuenta):
    viejo, _ = transferir(cuenta, [0])
    transferir(cuenta, [history.SALIDAS_HORAS * 60 + 1])

    assert viejo[0] not in ids_salidas(cuenta)
    assert 0 < get_cache().ttl(clave_salidas(cuenta)) <= history.SALIDAS_MS // 1000


# Historial de entradas.


def test_incoming_transfers_keep_the_sender_in_event_order(cuenta):
    registrar_entrada(cuenta, "b", "remitente-2", minuto(5))
    registrar_entrada(cuenta, "a", "remitente-1", minuto(1))

    assert entradas(cuenta) == [
        history.Entrada("a", "remitente-1", a_ms(minuto(1))),
        history.Entrada("b", "remitente-2", a_ms(minuto(5))),
    ]


def test_account_without_incoming_transfers_has_empty_history(cuenta):
    assert entradas(cuenta) == []


def test_incoming_history_older_than_retention_is_pruned(cuenta):
    registrar_entrada(cuenta, "viejo", "r", minuto(0))
    registrar_entrada(cuenta, "nuevo", "r", minuto(history.ENTRADAS_MIN + 1))

    assert [e.id for e in entradas(cuenta)] == ["nuevo"]
    assert 0 < get_cache().ttl(clave_entradas(cuenta)) <= history.ENTRADAS_MS // 1000
