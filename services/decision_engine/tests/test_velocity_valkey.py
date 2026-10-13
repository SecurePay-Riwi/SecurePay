from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import velocity
from services.decision_engine.velocity import (
    a_ms,
    historial,
    max_en_ventana,
    registrar_y_contar,
)
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

    get_cache().delete(f"vel:{cuenta_id}")


def enviar(cuenta_id, minutos):
    """Registra una transferencia por cada minuto, en el orden dado, y
    devuelve los ids y el conteo que obtuvo cada una."""
    ids, conteos = [], []
    for m in minutos:
        tx_id = str(uuid4())
        ids.append(tx_id)
        conteos.append(registrar_y_contar(cuenta_id, tx_id, minuto(m)))
    return ids, conteos


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


# Con Valkey.


def test_six_transfers_in_eight_minutes_pass_the_limit(cuenta):
    _, conteos = enviar(cuenta, [0, 1.6, 3.2, 4.8, 6.4, 8])

    assert conteos == [1, 2, 3, 4, 5, 6]
    assert conteos[-1] > velocity.LIMITE


def test_five_transfers_stay_within_the_limit(cuenta):
    _, conteos = enviar(cuenta, [0, 2, 4, 6, 8])

    assert max(conteos) == velocity.LIMITE


def test_transfers_more_than_ten_minutes_apart_do_not_add_up(cuenta):
    _, conteos = enviar(cuenta, [0, 1, 2, 3, 4, 15])

    assert conteos[-1] == 1


def test_late_event_is_accepted_and_kept(cuenta):
    ids, _ = enviar(cuenta, [5, 6])
    tarde, _ = enviar(cuenta, [1])

    assert tarde[0] in historial(cuenta)


def test_history_follows_event_time_not_arrival(cuenta):
    # Llegan 5, 7, 2, 9, 1: el historial queda 1, 2, 5, 7, 9.
    ids, _ = enviar(cuenta, [5, 7, 2, 9, 1])
    por_hora = [ids[4], ids[2], ids[0], ids[1], ids[3]]

    assert historial(cuenta) == por_hora


def test_late_event_completes_the_window(cuenta):
    # Cinco transferencias en orden y la sexta, del minuto 2, llega al final.
    _, conteos = enviar(cuenta, [0, 1, 3, 4, 5, 2])

    assert conteos[:5] == [1, 2, 3, 4, 5]
    assert conteos[-1] == 6


def test_late_event_outside_the_window_does_not_count(cuenta):
    # Llega tarde pero es de 20 minutos antes: no se junta con las demás.
    _, conteos = enviar(cuenta, [30, 31, 32, 33, 34, 10])

    assert conteos[-1] == 1


def test_resent_id_is_not_counted_twice(cuenta):
    tx_id = str(uuid4())
    registrar_y_contar(cuenta, tx_id, minuto(0))

    assert registrar_y_contar(cuenta, tx_id, minuto(0)) == 1


def test_history_older_than_retention_is_pruned(cuenta):
    viejo, _ = enviar(cuenta, [0])
    reciente = minuto(velocity.HISTORIAL_HORAS * 60 + 1)
    registrar_y_contar(cuenta, str(uuid4()), reciente)

    assert viejo[0] not in historial(cuenta)
    assert 0 < get_cache().ttl(f"vel:{cuenta}") <= velocity.HISTORIAL_MS // 1000
