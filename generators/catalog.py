"""Catálogo del core: lo que el generador necesita saber de la base.

Lee PostgreSQL una sola vez, al arrancar, y deja todo en memoria. Desde ahí
el generador no vuelve a consultar la base: los saldos los lleva él, como
lo haría el core de la billetera.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text

from generators.money import redondear


@dataclass
class Cuenta:
    id: uuid.UUID
    user_id: uuid.UUID
    moneda: str
    saldo: Decimal
    dispositivos: list[uuid.UUID] = field(default_factory=list)
    # El documento del dueño está en la lista restrictiva.
    en_lista: bool = False
    # Usa un dispositivo que también usan otras cuentas.
    compartida: bool = False


@dataclass
class Catalogo:
    cuentas: dict[uuid.UUID, Cuenta]
    comercios: list[uuid.UUID]

    @property
    def en_lista(self):
        return [c for c in self.cuentas.values() if c.en_lista]

    @property
    def compartidas(self):
        return [c for c in self.cuentas.values() if c.compartida]


# Cuentas activas con dos marcas: si el dueño está en la lista restrictiva
# (comparando solo los dígitos del documento, porque el seed lo escribe en
# varios formatos) y si usa un dispositivo compartido.
#
# El orden pone primero las cuentas especiales y después el resto en un
# orden al azar pero fijo para la misma semilla. Así, al cortar en
# max_accounts, las especiales siempre entran y la muestra es reproducible.
SQL_CUENTAS = text(r"""
    WITH compartidos AS (
        SELECT dispositivo_id
        FROM dispositivo_cuenta
        GROUP BY dispositivo_id
        HAVING count(*) > 1
    ),
    cuentas_compartidas AS (
        SELECT DISTINCT cuenta_id
        FROM dispositivo_cuenta
        WHERE dispositivo_id IN (SELECT dispositivo_id FROM compartidos)
    ),
    marcadas AS (
        SELECT
            c.id,
            c.user_id,
            c.moneda,
            c.saldo,
            regexp_replace(u.documento, '\D', '', 'g') IN (
                SELECT documento FROM listas_restrictivas
            ) AS en_lista,
            c.id IN (SELECT cuenta_id FROM cuentas_compartidas) AS compartida
        FROM cuentas c
        JOIN usuarios u ON u.id = c.user_id
        WHERE c.estado = 'activa'
    )
    SELECT *
    FROM marcadas
    ORDER BY (en_lista OR compartida) DESC, md5(id::text || :semilla)
""")

SQL_DISPOSITIVOS = text("""
    SELECT cuenta_id, dispositivo_id
    FROM dispositivo_cuenta
    WHERE cuenta_id = ANY(:ids)
    ORDER BY cuenta_id, fecha_asociacion
""")

SQL_COMERCIOS = text("""
    SELECT id FROM comercios WHERE estado = 'activo' ORDER BY id
""")


def es_de_instancia(cuenta_id, indice, total):
    """Reparte las cuentas entre instancias sin que dos tomen la misma."""
    return cuenta_id.int % total == indice


def elegir_cuentas(filas, max_cuentas, indice=0, total=1):
    """Toma las cuentas de esta instancia, hasta max_cuentas (0 = todas).

    Recibe las filas ya ordenadas por SQL_CUENTAS y deja de leer en cuanto
    junta las que necesita, así no recorre millones de filas de más.
    """
    cuentas = {}
    for fila in filas:
        if not es_de_instancia(fila.id, indice, total):
            continue

        cuentas[fila.id] = Cuenta(
            id=fila.id,
            user_id=fila.user_id,
            moneda=fila.moneda,
            # La columna guarda 2 decimales para todas las monedas; el yen
            # llega como 636114.00 y aquí se deja en 636114.
            saldo=redondear(fila.saldo, fila.moneda),
            en_lista=fila.en_lista,
            compartida=fila.compartida,
        )

        if max_cuentas and len(cuentas) >= max_cuentas:
            break

    return cuentas


def cargar(engine, semilla, max_cuentas, indice=0, total=1):
    """Lee la base una vez y devuelve el catálogo en memoria."""
    with engine.connect() as conn:
        # yield_per trae las filas por bloques de 1.000 en vez de todas
        # juntas: con 2,3 millones de cuentas la memoria no se dispara.
        filas = conn.execution_options(yield_per=1_000).execute(
            SQL_CUENTAS, {"semilla": str(semilla)}
        )
        cuentas = elegir_cuentas(filas, max_cuentas, indice, total)
        filas.close()

        if cuentas:
            for fila in conn.execute(SQL_DISPOSITIVOS, {"ids": list(cuentas)}):
                cuentas[fila.cuenta_id].dispositivos.append(fila.dispositivo_id)

        comercios = [fila.id for fila in conn.execute(SQL_COMERCIOS)]

    # Una cuenta sin dispositivo no puede transaccionar.
    cuentas = {k: c for k, c in cuentas.items() if c.dispositivos}

    if not cuentas:
        raise ValueError("No hay cuentas activas con dispositivo. ¿Corriste el seed?")
    if not comercios:
        raise ValueError("No hay comercios activos. ¿Corriste el seed?")

    catalogo = Catalogo(cuentas=cuentas, comercios=comercios)
    print(
        f"  Catálogo: {len(cuentas)} cuentas "
        f"({len(catalogo.en_lista)} en lista restrictiva, "
        f"{len(catalogo.compartidas)} con dispositivo compartido), "
        f"{len(comercios)} comercios"
    )
    return catalogo
