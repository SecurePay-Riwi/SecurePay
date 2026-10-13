import uuid
from collections import namedtuple
from decimal import Decimal

from generators.catalog import elegir_cuentas, es_de_instancia

Fila = namedtuple("Fila", "id user_id moneda saldo en_lista compartida")


def filas(n):
    return [
        Fila(uuid.UUID(int=i), uuid.UUID(int=10_000 + i), "JPY", Decimal("500.00"), False, False)
        for i in range(n)
    ]


def test_cada_cuenta_queda_en_una_sola_instancia():
    todas = filas(30)
    repartidas = [elegir_cuentas(todas, 0, i, 3) for i in range(3)]
    ids = [cid for parte in repartidas for cid in parte]
    assert len(ids) == len(set(ids)) == 30
    assert all(es_de_instancia(cid, 1, 3) for cid in repartidas[1])


def test_max_cuentas_corta_en_el_orden_recibido():
    todas = filas(30)
    elegidas = elegir_cuentas(todas, 5)
    assert list(elegidas) == [f.id for f in todas[:5]]


def test_el_saldo_del_yen_queda_sin_decimales():
    cuenta = next(iter(elegir_cuentas(filas(1), 0).values()))
    assert str(cuenta.saldo) == "500"
