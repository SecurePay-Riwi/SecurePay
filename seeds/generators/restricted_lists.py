import uuid
from faker import Faker
from sqlalchemy.dialects.postgresql import insert
from seeds.models import ListaRestrictiva

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def generar_listas(session, cantidad):
    fake = Faker("es_CO")
    Faker.seed(45)

    listas = []
    for i in range(cantidad):
        listas.append({
            "id": uuid.uuid5(NAMESPACE, f"list:{i}"),
            "documento": f"LIST{i:010d}",
            "tipo": fake.random_element(elements=("sanciones", "PEP")),
            "fecha_inclusion": fake.date_between(start_date="-5y", end_date="today"),
        })

    for l in listas:
        stmt = insert(ListaRestrictiva).values(**l).on_conflict_do_nothing(
            index_elements=["documento"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(listas)} listas generadas")
    return listas