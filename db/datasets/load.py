"""Carga: lee del seed a qué se pueden asignar las transacciones e inserta."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from db.datasets.config import TAMANO_LOTE
from db.datasets.transform import Dimensiones
from shared.models import Comercio, Dispositivo, DispositivoCuenta, Transaccion


def cargar_dimensiones(session):
    """Lee (solo SELECT) los usuarios, dispositivos y comercios del seed."""
    # Dispositivos de uso propio: asociados a una sola cuenta. Los
    # compartidos se dejan quietos para no alterar sus casos de prueba.
    propios = (
        select(DispositivoCuenta.dispositivo_id)
        .group_by(DispositivoCuenta.dispositivo_id)
        .having(func.count() == 1)
    )
    filas = session.execute(
        select(Dispositivo.user_id, Dispositivo.id, Dispositivo.fecha_asociacion)
        .where(Dispositivo.id.in_(propios))
    ).all()

    # Se ordena aquí y no en SQL para no depender del orden de PostgreSQL.
    dispositivos = {}
    for user_id, device_id, fecha in filas:
        dispositivos.setdefault(user_id, []).append((fecha, str(device_id), device_id))
    dispositivos = {
        u: tuple((f, d) for f, _, d in sorted(lista))
        for u, lista in dispositivos.items()
    }
    usuarios = tuple(
        sorted(
            ((lista[0][0], u) for u, lista in dispositivos.items()),
            key=lambda x: (x[0], str(x[1])),
        )
    )

    comercios = session.execute(
        select(Comercio.fecha_creacion, Comercio.id, Comercio.categoria)
        .where(Comercio.estado == "activo")
    ).all()
    comercios = tuple(sorted(comercios, key=lambda x: (x[0], str(x[1]))))

    return Dimensiones(usuarios=usuarios, dispositivos=dispositivos, comercios=comercios)


def contar_transacciones(session):
    return session.execute(select(func.count()).select_from(Transaccion)).scalar_one()


def insertar(session, filas):
    """Inserta por lotes. Si el id ya existe, lo deja como está."""
    stmt = insert(Transaccion).on_conflict_do_nothing(index_elements=["id"])
    for i in range(0, len(filas), TAMANO_LOTE):
        session.execute(stmt, filas[i:i + TAMANO_LOTE])
    session.commit()
