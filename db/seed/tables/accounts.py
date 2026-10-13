import random
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.dialects.postgresql import insert

from shared.models import Cuenta
from db.seed.config import MONEDAS, CUENTAS_BLOQUEADAS_PCT

NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")


def generar_cuentas(session, usuarios):
    """Crea una cuenta por usuario, con su moneda y su saldo inicial."""
    rng = random.Random(46)

    monedas = list(MONEDAS)
    pesos = [MONEDAS[m]["peso"] for m in monedas]

    cuentas = []
    for u in usuarios:
        moneda = rng.choices(monedas, weights=pesos)[0]
        config = MONEDAS[moneda]

        # 0.01 para dos decimales, 1 para el yen.
        paso = Decimal(1).scaleb(-config["decimales"])
        saldo = Decimal(str(rng.uniform(0, config["saldo_max"]))).quantize(
            paso, rounding=ROUND_HALF_UP
        )

        bloqueada = rng.random() * 100 < CUENTAS_BLOQUEADAS_PCT

        cuentas.append({
            "id": uuid.uuid5(NAMESPACE, f"account:{u['id']}"),
            "user_id": u["id"],
            "moneda": moneda,
            "saldo": saldo,
            "fecha_apertura": u["fecha_registro"],
            "estado": "bloqueada" if bloqueada else "activa",
        })

    for c in cuentas:
        stmt = insert(Cuenta).values(**c).on_conflict_do_nothing(
            index_elements=["user_id"]
        )
        session.execute(stmt)

    session.commit()
    print(f"  {len(cuentas)} cuentas generadas")
    return cuentas
