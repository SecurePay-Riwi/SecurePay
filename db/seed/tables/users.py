import random
import uuid

from faker import Faker
from sqlalchemy.dialects.postgresql import insert

from shared.models import Usuario
from db.seed.config import FECHA_REFERENCIA
from db.seed.defects.injector import (
    inyectar_defectos_usuarios,
    guardar_reporte_defectos,
)

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def generar_usuarios(session, cantidad, defect_percentage=0):
    fake = Faker("es_CO")
    Faker.seed(42)
    random.seed(42)

    # Rangos de fechas calculados desde la fecha fija, no desde hoy.
    hoy = FECHA_REFERENCIA.date()
    registro_desde = FECHA_REFERENCIA.replace(year=FECHA_REFERENCIA.year - 3)
    nacimiento_desde = hoy.replace(year=hoy.year - 80)
    nacimiento_hasta = hoy.replace(year=hoy.year - 18)

    usuarios = []

    for i in range(cantidad):
        user_id = uuid.uuid5(NAMESPACE, f"user:{i}")

        usuarios.append({
            "id": user_id,
            "nombre": fake.name(),
            "email": f"user{i}@pagoseguro.com",
            "documento": f"DOC{i:010d}",
            "telefono": fake.phone_number(),
            "fecha_nacimiento": fake.date_between(
                start_date=nacimiento_desde,
                end_date=nacimiento_hasta,
            ),
            "kyc_estado": random.choice(
                ["aprobado", "pendiente", "rechazado"]
            ),
            "fecha_registro": fake.date_time_between(
                start_date=registro_desde,
                end_date=FECHA_REFERENCIA,
            ),
        })

    defectos = inyectar_defectos_usuarios(
        usuarios,
        defect_percentage
    )

    for u in usuarios:
        stmt = insert(Usuario).values(**u).on_conflict_do_nothing(
            index_elements=["documento"]
        )
        session.execute(stmt)

    session.commit()

    print(f"  {len(usuarios)} usuarios generados")

    if defectos:
        print(f"  {len(defectos)} defectos inyectados")

        for defecto in defectos:
            print(
                f"    {defecto['tipo']} → "
                f"{defecto['campo']} → "
                f"{defecto['id']}"
            )

    guardar_reporte_defectos(defectos)

    return usuarios
