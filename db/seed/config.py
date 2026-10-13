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

# Porcentaje de los usuarios que también están en la lista restrictiva,
# con un mínimo para que en desarrollo haya con qué probar el rechazo.
# Con 0,1: 5 de 100 usuarios en desarrollo (por el mínimo) y 2.300 de
# 2,3 millones en el modo completo. Van dentro del total de la lista.
USUARIOS_EN_LISTA_PCT = float(os.getenv("SEED_USUARIOS_EN_LISTA_PCT", 0.1))
USUARIOS_EN_LISTA_MIN = int(os.getenv("SEED_USUARIOS_EN_LISTA_MIN", 5))

# Dispositivos compartidos. Cada patrón dice en cuántas cuentas se usa
# un mismo dispositivo y en cuántos días antes de la fecha de referencia
# se reparten esas asociaciones. La regla se dispara con más de 3 cuentas
# en 30 días.
PATRONES_COMPARTIDOS = [
    {"cuentas": 5, "dias": 30},  # Dispara la regla.
    {"cuentas": 4, "dias": 30},  # Dispara la regla.
    # Casos de control, solo para pruebas: NO deben disparar la regla.
    # Si el motor los marca, tiene un error.
    # 3 cuentas justas: atrapa a quien use ">= 3" en vez de "> 3".
    {"cuentas": 3, "dias": 30},
    # 5 cuentas repartidas en 90 días (unos 22 días entre una y otra,
    # nunca más de 2 en 30 días): atrapa a quien cuente todas las
    # cuentas del dispositivo en vez de solo las de la ventana.
    {"cuentas": 5, "dias": 90},
]

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
        "shared_devices": int(os.getenv("SEED_SHARED_DEVICES", 4)),
        "transactions": int(os.getenv("SEED_TRANSACTIONS", 100)),
    },
    "prod": {
        "users": int(os.getenv("SEED_USERS", 2_300_000)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 5_000)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 50_000)),
        "shared_devices": int(os.getenv("SEED_SHARED_DEVICES", 2_300)),
        "transactions": int(os.getenv("SEED_TRANSACTIONS", 100_000)),
    },
}
