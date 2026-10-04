import random
import uuid
from faker import Faker
from sqlalchemy.dialects.postgresql import insert
from seeds.models import Comercio

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def generar_comercios(session, cantidad):
    fake = Faker("es_CO")
    Faker.seed(44)
    random.seed(44)

    categorias = ["retail", "servicios", "alimentos", "tecnologia", "salud"]

    comercios = []
    for i in range(cantidad):
        comercios.append({
            "id": uuid.uuid5(NAMESPACE, f"merchant:{i}"),
            "nombre": fake.company(),
            "categoria": random.choice(categorias),
            "direccion": fake.address(),
            "fecha_creacion": fake.date_time_between(start_date="-2y", end_date="now"),
            "estado": random.choice(["activo", "inactivo", "suspendido"]),
        })

    for c in comercios:
        stmt = insert(Comercio).values(**c).on_conflict_do_nothing(
            index_elements=["id"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(comercios)} comercios generados")
    return comercios