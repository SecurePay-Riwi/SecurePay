"""Transformación: convierte las filas de Kaggle en filas de transacciones.

De cada dataset se aprovecha solo lo que existe en la tabla transacciones:
el monto, la etiqueta de fraude y la fecha. Lo que la tabla exige y los
datasets no traen (usuario, dispositivo, comercio, canal) se asigna al azar
con la semilla del seed, entre los datos que el seed ya creó. Todo el azar
sale de generadores con semilla y se consume siempre en el mismo orden, así
que cada compañero obtiene exactamente las mismas filas.

Dos reglas mantienen los datos coherentes:
- Una transacción nunca es anterior a la existencia del dispositivo (que
  nace después del registro del usuario) ni a la creación del comercio.
- Solo se usan dispositivos de uso propio (asociados a una sola cuenta),
  para no alterar los casos de dispositivo compartido del seed.
"""

import hashlib
import uuid
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from db.datasets.config import (
    CATEGORIA_FRAUDTEST,
    FRAUDTEST_DESPLAZAMIENTO,
    PAYSIM_INICIO,
    PREFIJO_PATRON,
    TIPO_PAYSIM,
    nuevo_rng,
)
# Canales por tipo de operación: la misma tabla que usa el generador.
from generators.config import CANALES
from db.seed.tables.accounts import NAMESPACE


@dataclass(frozen=True)
class Dimensiones:
    """Lo que el seed ya creó y a lo que se pueden asignar las transacciones.

    usuarios: (disponible_desde, user_id), ordenados. disponible_desde es
        la fecha del primer dispositivo propio del usuario.
    dispositivos: user_id -> [(fecha_asociacion, device_id)], ordenados.
    comercios: (fecha_creacion, merchant_id, categoria) de los comercios
        activos, ordenados.
    """

    usuarios: tuple
    dispositivos: dict
    comercios: tuple


@dataclass
class Lote:
    """Filas listas para insertar y ejemplos de antes y después."""

    dataset: str
    filas: list = field(default_factory=list)
    ejemplos: list = field(default_factory=list)
    # Porcentaje de filas cuyo comercio es de la categoría equivalente
    # (solo fraudTest trae categoría; en PaySim queda en None).
    categoria_respetada_pct: float | None = None


class Asignador:
    """Reparte cada transacción entre los usuarios, dispositivos y comercios."""

    def __init__(self, dims, rng):
        self.rng = rng
        self.dims = dims
        self._fechas_usuarios = [f for f, _ in dims.usuarios]
        self._fechas_comercios = [c[0] for c in dims.comercios]
        self._por_categoria = {}
        for c in dims.comercios:
            self._por_categoria.setdefault(c[2], []).append(c)
        self._fechas_categoria = {
            cat: [c[0] for c in lista] for cat, lista in self._por_categoria.items()
        }
        # Cuántas veces se pidió una categoría y cuántas se pudo respetar.
        self.categoria_pedida = 0
        self.categoria_respetada = 0

    def elegir(self, cantidad):
        """Posición al azar entre 0 y cantidad - 1.

        Solo usa random(): sus resultados son los mismos en cualquier sistema
        y versión de Python (choice o randint no lo garantizan).
        """
        return int(self.rng.random() * cantidad)

    def usuario_y_dispositivo(self, fecha):
        """Usuario con dispositivo ya existente en `fecha`, y ese dispositivo.

        Devuelve también la fecha, que se adelanta solo si ningún usuario
        existía todavía.
        """
        k = bisect_right(self._fechas_usuarios, fecha)
        if k == 0:
            disponible, user_id = self.dims.usuarios[0]
            fecha = max(fecha, disponible)
            k = 1
        else:
            user_id = self.dims.usuarios[self.elegir(k)][1]

        dispositivos = self.dims.dispositivos[user_id]
        fechas = [d[0] for d in dispositivos]
        kd = max(bisect_right(fechas, fecha), 1)
        device_id = dispositivos[self.elegir(kd)][1]
        return user_id, device_id, fecha

    def comercio(self, fecha, categoria=None):
        """Comercio activo y ya creado en `fecha`, de la categoría pedida si se puede."""
        lista, fechas = self.dims.comercios, self._fechas_comercios
        if categoria is not None:
            self.categoria_pedida += 1
        if categoria in self._por_categoria:
            if bisect_right(self._fechas_categoria[categoria], fecha) > 0:
                lista = self._por_categoria[categoria]
                fechas = self._fechas_categoria[categoria]
                self.categoria_respetada += 1

        k = bisect_right(fechas, fecha)
        if k == 0:
            # Ningún comercio existía todavía: se usa el más antiguo.
            creacion, merchant_id, _ = lista[0]
            return merchant_id, max(fecha, creacion)
        return lista[self.elegir(k)][1], fecha


def _id_transaccion(dataset, indice):
    # Determinista y ligado a la fila de origen: volver a correr el ETL no
    # duplica nada, y cada transacción se puede rastrear hasta su CSV.
    return uuid.uuid5(NAMESPACE, f"hist:{dataset}:{indice}")


def _en_utc(fecha):
    return fecha.replace(tzinfo=timezone.utc)


def transformar_paysim(filas, dims):
    rng = nuevo_rng("paysim", "asignacion")
    asignador = Asignador(dims, rng)
    lote = Lote(dataset="paysim")

    for fila in filas:
        # step es la hora de la simulación; los minutos y segundos no existen
        # en el dataset, se sortean.
        fecha = (
            PAYSIM_INICIO
            + timedelta(hours=fila.step - 1)
            + timedelta(seconds=asignador.elegir(3600))
        )
        user_id, device_id, fecha = asignador.usuario_y_dispositivo(fecha)
        merchant_id, fecha = asignador.comercio(fecha)

        tipo = TIPO_PAYSIM[fila.tipo]
        canales = CANALES[tipo]
        canal = canales[asignador.elegir(len(canales))]
        patron = (
            f"{PREFIJO_PATRON}_paysim_{fila.tipo.lower()}" if fila.es_fraude else None
        )

        destino = {
            "id": _id_transaccion("paysim", fila.indice),
            "user_id": user_id,
            "device_id": device_id,
            "merchant_id": merchant_id,
            "amount": fila.monto,
            "transaction_date": _en_utc(fecha),
            "channel": canal,
            "is_fraud": fila.es_fraude,
            "fraud_pattern": patron,
        }
        lote.filas.append(destino)
        _guardar_ejemplo(
            lote,
            fila,
            destino,
            {"step": fila.step, "type": fila.tipo, "amount": fila.monto,
             "isFraud": int(fila.es_fraude)},
        )
    return lote


def transformar_fraudtest(filas, dims):
    rng = nuevo_rng("fraudtest", "asignacion")
    asignador = Asignador(dims, rng)
    lote = Lote(dataset="fraudtest")

    for fila in filas:
        fecha = fila.fecha + FRAUDTEST_DESPLAZAMIENTO
        user_id, device_id, fecha = asignador.usuario_y_dispositivo(fecha)
        merchant_id, fecha = asignador.comercio(
            fecha, CATEGORIA_FRAUDTEST[fila.categoria]
        )

        # Las categorías *_net son compras por internet; el resto, un pago
        # a un comercio, que en el generador es QR (solo APP).
        if fila.categoria.endswith("_net"):
            canal = "WEB"
        else:
            canales = CANALES["QR"]
            canal = canales[asignador.elegir(len(canales))]
        patron = (
            f"{PREFIJO_PATRON}_fraudtest_{fila.categoria}" if fila.es_fraude else None
        )

        destino = {
            "id": _id_transaccion("fraudtest", fila.indice),
            "user_id": user_id,
            "device_id": device_id,
            "merchant_id": merchant_id,
            "amount": fila.monto,
            "transaction_date": _en_utc(fecha),
            "channel": canal,
            "is_fraud": fila.es_fraude,
            "fraud_pattern": patron,
        }
        lote.filas.append(destino)
        _guardar_ejemplo(
            lote,
            fila,
            destino,
            {"trans_date_trans_time": fila.fecha.isoformat(sep=" "),
             "category": fila.categoria, "amt": fila.monto,
             "is_fraud": int(fila.es_fraude)},
        )
    if asignador.categoria_pedida:
        lote.categoria_respetada_pct = (
            100 * asignador.categoria_respetada / asignador.categoria_pedida
        )
    return lote


def _guardar_ejemplo(lote, fila, destino, origen):
    """Guarda los primeros 2 casos normales y los primeros 2 de fraude."""
    de_su_clase = [e for e in lote.ejemplos if e[0]["is_fraud"] == destino["is_fraud"]]
    if len(de_su_clase) < 2:
        origen = {"fila_csv": fila.indice, **origen}
        lote.ejemplos.append((destino, origen))


def huella(filas):
    """SHA-256 de todas las filas, en orden.

    Dos personas con los mismos CSV, el mismo seed y la misma semilla deben
    obtener la misma huella. Si no coincide, algo de lo anterior difiere.
    """
    h = hashlib.sha256()
    for f in filas:
        partes = (
            f["id"], f["user_id"], f["device_id"], f["merchant_id"],
            format(f["amount"], "f"), f["transaction_date"].isoformat(),
            f["channel"], int(f["is_fraud"]), f["fraud_pattern"] or "",
        )
        h.update("|".join(str(p) for p in partes).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()
