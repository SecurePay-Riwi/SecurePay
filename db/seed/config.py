import os

from dotenv import load_dotenv

# FECHA_REFERENCIA no se usa aquí: se importa para que las tablas del seed
# la sigan tomando de este archivo.
from shared.config import FECHA_REFERENCIA, MONEDA_DECIMALES  # noqa: F401

load_dotenv()

SEED = int(os.getenv("SEED", 42))
MODE = os.getenv("SEED_MODE", "dev")
DEFECT_PERCENTAGE = float(os.getenv("SEED_DEFECT_PERCENTAGE", 0))

# Monedas de las cuentas: peso relativo en el reparto, saldo inicial
# máximo y decimales. El yen no lleva decimales (defecto de precisión
# decimal según moneda que pide el enunciado).
MONEDAS = {
    "COP": {"peso": 50, "saldo_max": 20_000_000, "decimales": MONEDA_DECIMALES["COP"]},
    "USD": {"peso": 25, "saldo_max": 5_000, "decimales": MONEDA_DECIMALES["USD"]},
    "EUR": {"peso": 15, "saldo_max": 5_000, "decimales": MONEDA_DECIMALES["EUR"]},
    "JPY": {"peso": 10, "saldo_max": 750_000, "decimales": MONEDA_DECIMALES["JPY"]},
}

# Porcentaje de cuentas que nacen bloqueadas.
CUENTAS_BLOQUEADAS_PCT = float(os.getenv("SEED_CUENTAS_BLOQUEADAS_PCT", 2))

# Porcentaje de los usuarios que también están en la lista restrictiva,
# con un mínimo para que en desarrollo haya con qué probar el rechazo.
# Con 0,1: 5 de 100 usuarios en desarrollo (por el mínimo) y 2.300 de
# 2,3 millones en el modo completo. Van dentro del total de la lista.
USUARIOS_EN_LISTA_PCT = float(os.getenv("SEED_USUARIOS_EN_LISTA_PCT", 0.1))
USUARIOS_EN_LISTA_MIN = int(os.getenv("SEED_USUARIOS_EN_LISTA_MIN", 5))

# Comercios recién creados (posibles comercios ficticios): este porcentaje
# de comercios se crea en los últimos N días antes de la fecha de
# referencia; el resto, antes de esa ventana.
COMERCIOS_NUEVOS_PCT = float(os.getenv("SEED_COMERCIOS_NUEVOS_PCT", 10))
COMERCIOS_NUEVOS_DIAS = int(os.getenv("SEED_COMERCIOS_NUEVOS_DIAS", 30))

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

VOLUMES = {
    "dev": {
        "users": int(os.getenv("SEED_USERS", 100)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 50)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 20)),
        "shared_devices": int(os.getenv("SEED_SHARED_DEVICES", 4)),
    },
    "prod": {
        "users": int(os.getenv("SEED_USERS", 2_300_000)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 5_000)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 50_000)),
        "shared_devices": int(os.getenv("SEED_SHARED_DEVICES", 2_300)),
    },
}
