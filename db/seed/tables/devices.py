import random
import uuid
from datetime import timedelta

from faker import Faker
from sqlalchemy.dialects.postgresql import insert

from shared.models import Dispositivo, DispositivoCuenta
from db.seed.config import FECHA_REFERENCIA, PATRONES_COMPARTIDOS
from db.seed.fechas import fecha_hora_entre

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def user_agent(fake):
    """User agent de Chrome, Safari u Opera.

    user_agent() de Faker a veces arma uno de Firefox con una fecha
    adentro, y esas fechas salen distintas en Windows y en Linux (ver
    db/seed/fechas.py). Estos tres navegadores no la usan.
    """
    return fake.random_element((fake.chrome, fake.safari, fake.opera))()


def generar_dispositivos(
    session, usuarios, cuentas, dispositivos_por_usuario, cantidad_compartidos
):
    fake = Faker("es_CO")
    Faker.seed(43)
    random.seed(43)

    dispositivos = []
    for u in usuarios:
        n = random.randint(1, dispositivos_por_usuario)
        for j in range(n):
            dev_id = uuid.uuid5(NAMESPACE, f"device:{u['id']}:{j}")
            dispositivos.append({
                "id": dev_id,
                "user_id": u["id"],
                "device_fingerprint": str(uuid.uuid5(NAMESPACE, f"fp:{u['id']}:{j}")),
                "user_agent": user_agent(fake),
                "ip": fake.ipv4(),
                "fecha_asociacion": fecha_hora_entre(
                    fake.random, u["fecha_registro"], FECHA_REFERENCIA
                ),
            })

    # Cada dispositivo normal queda asociado a la cuenta de su dueño.
    cuenta_por_usuario = {c["user_id"]: c for c in cuentas}
    asociaciones = [
        {
            "dispositivo_id": d["id"],
            "cuenta_id": cuenta_por_usuario[d["user_id"]]["id"],
            "fecha_asociacion": d["fecha_asociacion"],
        }
        for d in dispositivos
    ]

    compartidos, asociaciones_compartidas = generar_compartidos(
        fake, cuentas, cantidad_compartidos
    )
    dispositivos += compartidos
    asociaciones += asociaciones_compartidas

    for d in dispositivos:
        stmt = insert(Dispositivo).values(**d).on_conflict_do_nothing(
            index_elements=["device_fingerprint"]
        )
        session.execute(stmt)

    for a in asociaciones:
        stmt = insert(DispositivoCuenta).values(**a).on_conflict_do_nothing(
            index_elements=["dispositivo_id", "cuenta_id"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(dispositivos)} dispositivos generados ({len(compartidos)} compartidos)")
    print(f"  {len(asociaciones)} asociaciones dispositivo-cuenta generadas")
    return dispositivos


def generar_compartidos(fake, cuentas, cantidad):
    """Dispositivos usados en varias cuentas, según PATRONES_COMPARTIDOS."""
    rng = random.Random(47)

    # Las columnas de fecha no guardan zona horaria.
    referencia = FECHA_REFERENCIA.replace(tzinfo=None)

    # Solo cuentas activas abiertas antes del patrón más largo, para que
    # ninguna asociación quede antes de que exista la cuenta.
    dias_max = max(p["dias"] for p in PATRONES_COMPARTIDOS)
    candidatas = [
        c for c in cuentas
        if c["estado"] == "activa"
        and c["fecha_apertura"] < referencia - timedelta(days=dias_max)
    ]
    cuentas_max = max(p["cuentas"] for p in PATRONES_COMPARTIDOS)
    if cantidad and len(candidatas) < cuentas_max:
        raise ValueError(
            f"Se necesitan al menos {cuentas_max} cuentas activas abiertas "
            f"hace más de {dias_max} días para los dispositivos compartidos"
        )

    dispositivos = []
    asociaciones = []
    for k in range(cantidad):
        patron = PATRONES_COMPARTIDOS[k % len(PATRONES_COMPARTIDOS)]
        elegidas = rng.sample(candidatas, patron["cuentas"])

        # Fechas repartidas parejo entre 1 y (dias - 1) días antes de la
        # referencia, para no caer justo en el borde de la ventana.
        tramo = (patron["dias"] - 2) / (patron["cuentas"] - 1)
        fechas = [
            referencia - timedelta(days=1 + i * tramo)
            for i in range(patron["cuentas"])
        ]

        # El dueño (opción A: dispositivos.user_id se mantiene) es la
        # cuenta que lo usó primero, la de la fecha más antigua.
        dev_id = uuid.uuid5(NAMESPACE, f"shared_device:{k}")
        dispositivos.append({
            "id": dev_id,
            "user_id": elegidas[-1]["user_id"],
            "device_fingerprint": str(uuid.uuid5(NAMESPACE, f"fp:shared:{k}")),
            "user_agent": user_agent(fake),
            "ip": fake.ipv4(),
            "fecha_asociacion": fechas[-1],
        })

        for cuenta, fecha in zip(elegidas, fechas):
            asociaciones.append({
                "dispositivo_id": dev_id,
                "cuenta_id": cuenta["id"],
                "fecha_asociacion": fecha,
            })

    return dispositivos, asociaciones
