import random
import uuid

from faker import Faker
from sqlalchemy.dialects.postgresql import insert

from seeds.models import Usuario
from seeds.defects.injector import (
    inyectar_defectos_usuarios,
    guardar_reporte_defectos,
)

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def generar_usuarios(session, cantidad, defect_percentage=0):
    fake = Faker("es_CO")
    Faker.seed(42)
    random.seed(42)

    usuarios = []

    for i in range(cantidad):
        user_id = uuid.uuid5(NAMESPACE, f"user:{i}")

        usuarios.append({
            "id": user_id,
            "nombre": fake.name(),
            "email": f"user{i}@pagoseguro.com",
            "documento": f"DOC{i:010d}",
            "telefono": fake.phone_number(),
            "fecha_nacimiento": fake.date_of_birth(
                minimum_age=18,
                maximum_age=80
            ),
            "kyc_estado": random.choice(
                ["aprobado", "pendiente", "rechazado"]
            ),
            "fecha_registro": fake.date_time_between(
                start_date="-3y",
                end_date="now"
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
