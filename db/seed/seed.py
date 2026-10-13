
import os

from sqlalchemy import text

from db.seed.config import (
    MODE,
    VOLUMES,
    DEFECT_PERCENTAGE,
    TRANSACTION_FRAUD_PERCENTAGE,
    SEED,
)
from shared.db import get_session, engine
from shared.models import Base
from db.seed.tables.users import generar_usuarios
from db.seed.tables.accounts import generar_cuentas
from db.seed.tables.devices import generar_dispositivos
from db.seed.tables.merchants import generar_comercios
from db.seed.tables.restricted_lists import generar_listas
from generators.transactions import generar_transacciones


def reset_tablas():
    """Borra los datos existentes solo si SEED_RESET=true."""
    print("SEED_RESET=true -> borrando datos existentes...")

    with engine.connect() as conn:
        conn.execute(
            text(
                """
                TRUNCATE TABLE
                    transacciones,
                    usuarios,
                    cuentas,
                    dispositivos,
                    dispositivo_cuenta,
                    comercios,
                    listas_restrictivas
                CASCADE
                """
            )
        )
        conn.commit()

    print("  Tablas vaciadas.")
    print()


def main():
    print(f"Modo: {MODE}")
    print(f"Volúmenes: {VOLUMES[MODE]}")
    print(f"Porcentaje de defectos: {DEFECT_PERCENTAGE}%")
    print(
        f"Porcentaje de fraude: "
        f"{TRANSACTION_FRAUD_PERCENTAGE}%"
    )

    reset = os.getenv("SEED_RESET", "false").lower() == "true"

    # Crear únicamente las tablas que aún no existan. Va antes del reset
    # para que el TRUNCATE no falle con una tabla nueva (como cuentas).
    Base.metadata.create_all(engine)

    if reset:
        reset_tablas()

    session = get_session()

    try:
        vol = VOLUMES[MODE]

        print("Generando usuarios...")
        usuarios = generar_usuarios(
            session,
            vol["users"],
            DEFECT_PERCENTAGE,
        )

        print("Generando cuentas...")
        cuentas = generar_cuentas(session, usuarios)

        print("Generando dispositivos...")
        dispositivos = generar_dispositivos(
            session,
            usuarios,
            cuentas,
            vol["devices_per_user"],
            vol["shared_devices"],
        )

        print("Generando comercios...")
        comercios = generar_comercios(
            session,
            vol["merchants"],
        )

        print("Generando listas restrictivas...")
        generar_listas(
            session,
            vol["restricted_lists"],
        )

        print("Generando transacciones...")
        generar_transacciones(
            session=session,
            usuarios=usuarios,
            dispositivos=dispositivos,
            comercios=comercios,
            cantidad=vol["transactions"],
            fraud_percentage=TRANSACTION_FRAUD_PERCENTAGE,
            seed=SEED,
        )

        print()
        print("Seed completado.")

    finally:
        session.close()


if __name__ == "__main__":
    main()
