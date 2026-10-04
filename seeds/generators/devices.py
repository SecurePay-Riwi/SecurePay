import random
import uuid
from faker import Faker
from sqlalchemy.dialects.postgresql import insert
from seeds.models import Dispositivo

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

def generar_dispositivos(session, usuarios, dispositivos_por_usuario):
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
                "user_agent": fake.user_agent(),
                "ip": fake.ipv4(),
                "fecha_asociacion": fake.date_time_between(
                    start_date=u["fecha_registro"], end_date="now"
                ),
            })

    for d in dispositivos:
        stmt = insert(Dispositivo).values(**d).on_conflict_do_nothing(
            index_elements=["device_fingerprint"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(dispositivos)} dispositivos generados")
    return dispositivos