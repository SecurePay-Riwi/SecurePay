import random
import uuid
from faker import Faker
from sqlalchemy.dialects.postgresql import insert
from shared.models import ListaRestrictiva
from db.seed.config import (
    FECHA_REFERENCIA,
    USUARIOS_EN_LISTA_PCT,
    USUARIOS_EN_LISTA_MIN,
)

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def generar_listas(session, usuarios, cantidad):
    fake = Faker("es_CO")
    Faker.seed(45)

    hoy = FECHA_REFERENCIA.date()
    inclusion_desde = hoy.replace(year=hoy.year - 5)

    # Clientes que también están en la lista: un porcentaje de los usuarios,
    # con un mínimo, sin pasar del total de la lista ni de los usuarios.
    n_clientes = max(
        USUARIOS_EN_LISTA_MIN,
        round(len(usuarios) * USUARIOS_EN_LISTA_PCT / 100),
    )
    n_clientes = min(n_clientes, cantidad, len(usuarios))
    clientes = random.Random(48).sample(usuarios, n_clientes)

    listas = []
    for i in range(cantidad):
        if i < n_clientes:
            # Mismo documento del cliente, en formato canónico.
            documento = clientes[i]["documento"]
        else:
            # Personas que no son clientes: cédulas de 8 dígitos, que nunca
            # coinciden con las de 10 dígitos de los usuarios.
            documento = str(10_000_000 + i)

        listas.append({
            "id": uuid.uuid5(NAMESPACE, f"list:{i}"),
            "documento": documento,
            "tipo": fake.random_element(elements=("sanciones", "PEP")),
            "fecha_inclusion": fake.date_between(
                start_date=inclusion_desde, end_date=hoy
            ),
        })

    for l in listas:
        stmt = insert(ListaRestrictiva).values(**l).on_conflict_do_nothing(
            index_elements=["documento"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(listas)} personas en la lista restrictiva ({n_clientes} son clientes)")
    return listas