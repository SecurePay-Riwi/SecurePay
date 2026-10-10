
import random
import uuid

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from seeds.models import Transaccion


NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def generar_transacciones(
    session,
    usuarios,
    dispositivos,
    comercios,
    cantidad,
    fraud_percentage=0,
    seed=42,
):
    """
    Genera transacciones normales y fraudulentas.

    Los patrones sintéticos son:
    - MULE_ACTIVITY
    - TRANSACTION_SPLITTING
    - VELOCITY

    Las transacciones se identifican de forma determinista para
    evitar insertar nuevamente los mismos registros al repetir el seed.
    """

    if cantidad < 0:
        raise ValueError("La cantidad no puede ser negativa")

    if not 0 <= fraud_percentage <= 100:
        raise ValueError("El porcentaje de fraude debe estar entre 0 y 100")

    if cantidad == 0:
        print("  No hay transacciones para generar")
        return []

    if not usuarios or not dispositivos or not comercios:
        raise ValueError(
            "Se necesitan usuarios, dispositivos y comercios para generar "
            "transacciones"
        )

    rng = random.Random(seed)

    # Agrupar dispositivos por usuario para respetar las relaciones.
    dispositivos_por_usuario = {}

    for dispositivo in dispositivos:
        user_id = dispositivo["user_id"]
        dispositivos_por_usuario.setdefault(user_id, []).append(dispositivo)

    usuarios_validos = [
        usuario
        for usuario in usuarios
        if usuario["id"] in dispositivos_por_usuario
    ]

    if not usuarios_validos:
        raise ValueError("No hay usuarios con dispositivos disponibles")

    fraude_total = round(cantidad * fraud_percentage / 100)
    normales_total = cantidad - fraude_total

    transacciones = []
    ahora = datetime.now(timezone.utc)

    def crear_transaccion(
        indice,
        usuario,
        fecha,
        fraudulenta=False,
        patron=None,
        importe=None,
    ):
        dispositivos_usuario = dispositivos_por_usuario[usuario["id"]]

        dispositivo = rng.choice(dispositivos_usuario)
        comercio = rng.choice(comercios)

        return {
            "id": uuid.uuid5(NAMESPACE, f"transaction:{indice}"),
            "user_id": usuario["id"],
            "device_id": dispositivo["id"],
            "merchant_id": comercio["id"],
            "amount": importe if importe is not None else Decimal(
                str(round(rng.uniform(5_000, 500_000), 2))
            ),
            "transaction_date": fecha,
            "channel": rng.choice(
                ["WEB", "MOBILE", "ATM", "POS"]
            ),
            "is_fraud": fraudulenta,
            "fraud_pattern": patron,
            "decision": None,
            "decision_reason": None,
            "processed_at": None,
        }

    # 1. Generar transacciones normales.
    for indice in range(normales_total):
        usuario = rng.choice(usuarios_validos)
        fecha = ahora - timedelta(
            days=rng.randint(0, 30),
            minutes=rng.randint(0, 1440),
        )

        transacciones.append(
            crear_transaccion(indice, usuario, fecha)
        )

    # 2. Distribuir las transacciones fraudulentas entre patrones.
    patrones = [
        "MULE_ACTIVITY",
        "TRANSACTION_SPLITTING",
        "VELOCITY",
    ]

    if fraude_total:
        base, resto = divmod(fraude_total, len(patrones))
        indice_fraude = normales_total

        for posicion, patron in enumerate(patrones):
            cantidad_patron = base + (1 if posicion < resto else 0)

            if cantidad_patron == 0:
                continue

            # Todas las operaciones de este grupo comparten usuario.
            usuario = rng.choice(usuarios_validos)
            fecha_base = ahora - timedelta(days=rng.randint(0, 7))

            for j in range(cantidad_patron):
                if patron == "MULE_ACTIVITY":
                    # Varias operaciones próximas en el tiempo.
                    fecha = fecha_base + timedelta(minutes=j)
                    importe = Decimal(
                        str(round(rng.uniform(100_000, 600_000), 2))
                    )

                elif patron == "TRANSACTION_SPLITTING":
                    # Operaciones de importes relativamente pequeños.
                    fecha = fecha_base + timedelta(minutes=j * 2)
                    importe = Decimal(
                        str(round(rng.uniform(10_000, 50_000), 2))
                    )

                else:  # VELOCITY
                    # Muchas operaciones concentradas en pocos segundos.
                    fecha = fecha_base + timedelta(seconds=j * 10)
                    importe = Decimal(
                        str(round(rng.uniform(20_000, 250_000), 2))
                    )

                transacciones.append(
                    crear_transaccion(
                        indice_fraude,
                        usuario,
                        fecha,
                        fraudulenta=True,
                        patron=patron,
                        importe=importe,
                    )
                )

                indice_fraude += 1

    # 3. Insertar sin duplicar IDs deterministas existentes.
    try:
        for transaccion in transacciones:
            stmt = (
                insert(Transaccion)
                .values(**transaccion)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            session.execute(stmt)

        session.commit()

    except Exception:
        session.rollback()
        raise

    print(f"  Transacciones generadas: {len(transacciones)}")
    print(f"  Fraudulentas: {fraude_total}")
    print(f"  Normales: {normales_total}")

    for patron in patrones:
        total_patron = sum(
            1
            for transaccion in transacciones
            if transaccion["fraud_pattern"] == patron
        )
        print(f"  {patron}: {total_patron}")

    return transacciones
