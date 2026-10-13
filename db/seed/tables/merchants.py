import random
import uuid
from datetime import timedelta
from faker import Faker
from sqlalchemy.dialects.postgresql import insert
from shared.models import Comercio
from db.seed.config import (
    FECHA_REFERENCIA,
    COMERCIOS_NUEVOS_PCT,
    COMERCIOS_NUEVOS_DIAS,
)

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def generar_comercios(session, cantidad):
    fake = Faker("es_CO")
    Faker.seed(44)
    random.seed(44)

    categorias = ["retail", "servicios", "alimentos", "tecnologia", "salud"]
    # Tipo de negocio que va antes del nombre, para que se lea como comercio.
    prefijos = {
        "retail": "Tienda",
        "servicios": "Servicios",
        "alimentos": "Restaurante",
        "tecnologia": "Tecnología",
        "salud": "Farmacia",
    }

    creacion_desde = FECHA_REFERENCIA.replace(year=FECHA_REFERENCIA.year - 2)
    # Límite entre comercios antiguos y recién creados.
    nuevos_desde = FECHA_REFERENCIA - timedelta(days=COMERCIOS_NUEVOS_DIAS)

    # Qué comercios son recién creados, elegidos con una semilla fija.
    n_nuevos = round(cantidad * COMERCIOS_NUEVOS_PCT / 100)
    nuevos = set(random.Random(49).sample(range(cantidad), n_nuevos))

    comercios = []
    for i in range(cantidad):
        if i in nuevos:
            desde, hasta = nuevos_desde, FECHA_REFERENCIA
        else:
            desde, hasta = creacion_desde, nuevos_desde

        # Faker deja "and" y "Ltd" en inglés; se pasan a español.
        empresa = (
            fake.company()
            .replace(" and ", " y ")
            .replace(" Ltd", " Ltda.")
        )
        categoria = random.choice(categorias)

        comercio = {
            "id": uuid.uuid5(NAMESPACE, f"merchant:{i}"),
            "nombre": f"{prefijos[categoria]} {empresa}",
            "categoria": categoria,
            "direccion": fake.address(),
            "fecha_creacion": fake.date_time_between(
                start_date=desde, end_date=hasta
            ),
            "estado": random.choice(["activo", "inactivo", "suspendido"]),
        }
        # Un comercio recién creado está activo: si no, no recibe pagos.
        if i in nuevos:
            comercio["estado"] = "activo"
        comercios.append(comercio)

    for c in comercios:
        stmt = insert(Comercio).values(**c).on_conflict_do_nothing(
            index_elements=["id"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(comercios)} comercios generados ({n_nuevos} recién creados)")
    return comercios