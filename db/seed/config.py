import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("SEED", 42))
MODE = os.getenv("SEED_MODE", "dev")
DEFECT_PERCENTAGE = float(os.getenv("SEED_DEFECT_PERCENTAGE", 0))

# Fecha fija desde la que se calculan todas las fechas del seed.
# Así dos corridas dan los mismos datos sin importar el día.
FECHA_REFERENCIA = datetime(2026, 10, 1, tzinfo=timezone.utc)

# Monedas de las cuentas: peso relativo en el reparto, saldo inicial
# máximo y decimales. El yen no lleva decimales (defecto de precisión
# decimal según moneda que pide el enunciado).
MONEDAS = {
    "COP": {"peso": 50, "saldo_max": 20_000_000, "decimales": 2},
    "USD": {"peso": 25, "saldo_max": 5_000, "decimales": 2},
    "EUR": {"peso": 15, "saldo_max": 5_000, "decimales": 2},
    "JPY": {"peso": 10, "saldo_max": 750_000, "decimales": 0},
}

# Porcentaje de cuentas que nacen bloqueadas.
CUENTAS_BLOQUEADAS_PCT = float(os.getenv("SEED_CUENTAS_BLOQUEADAS_PCT", 2))

TRANSACTION_FRAUD_PERCENTAGE = float(
    os.getenv("SEED_FRAUD_PERCENTAGE", 0)
)

if not 0 <= TRANSACTION_FRAUD_PERCENTAGE <= 100:
    raise ValueError(
        "SEED_FRAUD_PERCENTAGE debe estar entre 0 y 100"
    )

VOLUMES = {
    "dev": {
        "users": int(os.getenv("SEED_USERS", 100)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 50)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 20)),
        "transactions": int(os.getenv("SEED_TRANSACTIONS", 100)),
    },
    "prod": {
        "users": int(os.getenv("SEED_USERS", 2_300_000)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 5_000)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 50_000)),
        "transactions": int(os.getenv("SEED_TRANSACTIONS", 100_000)),
    },
}
