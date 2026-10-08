import os

from sqlalchemy import text

from seeds.config import MODE, VOLUMES, DEFECT_PERCENTAGE
from seeds.db import get_session, engine
from seeds.models import Base
from seeds.generators.users import generar_usuarios
from seeds.generators.devices import generar_dispositivos
from seeds.generators.merchants import generar_comercios
from seeds.generators.restricted_lists import generar_listas

def reset_tablas():
    """Borra todas las tablas antes de insertar. Solo si SEED_RESET=true."""
    print("SEED_RESET=true -> borrando datos existentes...")
    with engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE usuarios, dispositivos, comercios, listas_restrictivas CASCADE"
        ))
        conn.commit()
    print("  Tablas vaciadas.")
    print()


def main():
    print(f"Modo: {MODE}")
    print(f"Volúmenes: {VOLUMES[MODE]}")
    print(f"Porcentaje de defectos: {DEFECT_PERCENTAGE}%")

    # Reset opcional
    reset = os.getenv("SEED_RESET", "false").lower() == "true"
    if reset:
        reset_tablas()

    print()

    # Crear tablas si no existen
    Base.metadata.create_all(engine)

    session = get_session()
    try:
        vol = VOLUMES[MODE]

        print("Generando usuarios...")
        usuarios = generar_usuarios(
            session,
            vol["users"],
            DEFECT_PERCENTAGE
        )
        print("Generando dispositivos...")
        generar_dispositivos(session, usuarios, vol["devices_per_user"])

        print("Generando comercios...")
        generar_comercios(session, vol["merchants"])

        print("Generando listas restrictivas...")
        generar_listas(session, vol["restricted_lists"])

        print()
        print("Seed completado.")
    finally:
        session.close()


if __name__ == "__main__":
    main()