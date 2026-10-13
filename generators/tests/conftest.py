"""Datos de prueba del generador, sin base de datos.

El catálogo falso imita lo que carga catalog.py desde PostgreSQL: cuentas
en las cuatro monedas, algunas en la lista restrictiva y otras con un
dispositivo compartido.
"""

import random
import uuid
from decimal import Decimal

import pytest

from generators.catalog import Catalogo, Cuenta
from generators.core import Core
from generators.defects import Defectos
from generators.money import cargar_tasas, redondear
from generators.patterns import CICLO
from shared.config import FECHA_REFERENCIA

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

# Cuántas cuentas de cada moneda y su saldo máximo.
MONEDAS = {"COP": (40, 20_000_000), "USD": (20, 5_000), "EUR": (12, 5_000), "JPY": (8, 750_000)}


def catalogo_falso(en_lista=4, compartidas=6):
    rng = random.Random(7)
    cuentas = {}
    for moneda, (n, saldo_max) in MONEDAS.items():
        for i in range(n):
            cid = uuid.uuid5(NAMESPACE, f"account:{moneda}:{i}")
            cuentas[cid] = Cuenta(
                id=cid,
                user_id=uuid.uuid5(NAMESPACE, f"user:{moneda}:{i}"),
                moneda=moneda,
                saldo=redondear(Decimal(str(rng.uniform(0, saldo_max))), moneda),
                dispositivos=[
                    uuid.uuid5(NAMESPACE, f"device:{moneda}:{i}:{j}")
                    for j in range(rng.randint(1, 2))
                ],
            )

    lista = list(cuentas.values())
    for c in lista[:en_lista]:
        c.en_lista = True
    for c in lista[en_lista : en_lista + compartidas]:
        c.compartida = True

    comercios = [uuid.uuid5(NAMESPACE, f"merchant:{i}") for i in range(10)]
    return Catalogo(cuentas=cuentas, comercios=comercios)


@pytest.fixture
def tasas():
    return cargar_tasas()


@pytest.fixture
def en_lista():
    """Ids de las cuentas del catálogo falso que están en la lista."""
    return {str(c.id) for c in catalogo_falso().en_lista}


@pytest.fixture
def generar(tasas):
    """Corre el generador completo sobre un catálogo falso nuevo.

    El catálogo se arma de nuevo en cada llamada porque el core mueve los
    saldos de las cuentas.
    """

    def _generar(cantidad=1_000, fraude=5, defectos=(0, 0, 0), semilla=42):
        core = Core(catalogo_falso(), tasas, cantidad, fraude, semilla, FECHA_REFERENCIA)
        core.patrones = CICLO
        d = Defectos(semilla, *defectos)
        return list(d.aplicar(core.eventos())), d

    return _generar
