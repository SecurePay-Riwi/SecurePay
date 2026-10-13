"""Configuración del generador de transacciones.

El generador hace de core de la billetera: manda transacciones al motor
de decisión. Todo lo que cambia entre desarrollo, la demo y la prueba de
carga se ajusta aquí o con variables de entorno, sin tocar código.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from shared.config import FECHA_REFERENCIA  # noqa: F401 (la usan los patrones)

load_dotenv()

SEED = int(os.getenv("SEED", 42))
MODE = os.getenv("GEN_MODE", "dev")

# --- Volumen ---------------------------------------------------------------

# "max_accounts" limita cuántas cuentas se cargan en memoria. Con 2,3
# millones no hace falta tenerlas todas: unas 50.000 alcanzan para 50 tx/s.
# Las cuentas especiales (lista restrictiva y dispositivos compartidos)
# se cargan siempre, aunque no caigan en la muestra.
VOLUMES = {
    "dev": {
        "transactions": int(os.getenv("GEN_TRANSACTIONS", 1_000)),
        "max_accounts": int(os.getenv("GEN_MAX_ACCOUNTS", 0)),  # 0 = todas
    },
    "prod": {
        "transactions": int(os.getenv("GEN_TRANSACTIONS", 1_000_000)),
        "max_accounts": int(os.getenv("GEN_MAX_ACCOUNTS", 50_000)),
    },
}

# Transacciones por segundo al mandar al motor. 0 = lo más rápido posible.
# Es el ritmo real de envío, no el de las fechas de las transacciones.
RATE_PER_SECOND = float(os.getenv("GEN_RATE", 50))

# Cuántas transacciones hace en promedio cada cuenta al día. Fija cuánto
# avanza la fecha simulada entre una transacción y otra: con 100 cuentas,
# unos 15 minutos; con 50.000, menos de 2 segundos. Así una cuenta normal
# nunca dispara una regla por casualidad.
TX_PER_ACCOUNT_DAY = float(os.getenv("GEN_TX_PER_ACCOUNT_DAY", 1))

# --- Salida ----------------------------------------------------------------

# "http": manda cada transacción al motor, como el core.
# "file": la escribe en un archivo .jsonl, para probar sin el motor.
OUTPUT = os.getenv("GEN_OUTPUT", "file")
ENGINE_URL = os.getenv("GEN_ENGINE_URL", "http://localhost:8000")
OUTPUT_DIR = Path(os.getenv("GEN_OUTPUT_DIR", "generated"))

# --- Varias instancias a la vez (prueba de carga) ---------------------------

# Cada instancia toma solo las cuentas que le tocan (instancia i de n), así
# dos generadores nunca mueven el saldo de la misma cuenta.
INSTANCE_INDEX = int(os.getenv("GEN_INSTANCE_INDEX", 0))
INSTANCE_COUNT = int(os.getenv("GEN_INSTANCE_COUNT", 1))

# --- Fraude y defectos -----------------------------------------------------

# Porcentaje de las transacciones que pertenecen a un patrón de fraude.
FRAUD_PERCENTAGE = float(os.getenv("GEN_FRAUD_PERCENTAGE", 5))

# Defectos de calidad que pide el enunciado, en porcentaje.
DUPLICATE_PERCENTAGE = float(os.getenv("GEN_DUPLICATE_PERCENTAGE", 2))
OUT_OF_ORDER_PERCENTAGE = float(os.getenv("GEN_OUT_OF_ORDER_PERCENTAGE", 2))
DECIMAL_DEFECT_PERCENTAGE = float(os.getenv("GEN_DECIMAL_DEFECT_PERCENTAGE", 1))

# --- Transacciones normales ------------------------------------------------

# Peso relativo de cada tipo. Una recarga no tiene cuenta origen, un retiro
# no tiene cuenta destino y solo el pago QR lleva comercio.
TIPOS = {"P2P": 40, "QR": 30, "RECARGA": 15, "RETIRO": 15}

CANALES = {
    "P2P": ["APP", "WEB"],
    "QR": ["APP"],
    "RECARGA": ["APP", "WEB", "CORRESPONSAL"],
    "RETIRO": ["CORRESPONSAL", "CAJERO"],
}

# Monto normal de cada transacción, en USD. Se convierte a la moneda de la
# cuenta con las tasas guardadas de Frankfurter.
MONTO_NORMAL_USD = {"min": 1, "max": 150}
MONTO_RECARGA_USD = {"min": 10, "max": 300}

# --- Reglas que deben imitar los patrones ----------------------------------

# Son los umbrales del enunciado. Los patrones de fraude se fabrican para
# pasarlos y sus casos de control para quedarse justo por debajo.
REGLAS = {
    # Más de 5 transferencias salientes en 10 minutos desde la misma cuenta.
    "velocidad": {"transferencias": 5, "minutos": 10},
    # Recibe de 3 o más remitentes distintos y retira el 80 % o más del
    # saldo en menos de 30 minutos.
    "mula": {"remitentes": 3, "retiro_pct": 80, "minutos": 30},
    # 3 o más transacciones en 24 h, cada una bajo el límite diario de
    # reporte y que juntas lo pasan. USD 10.000 es el parámetro inicial.
    "fraccionamiento": {"transacciones": 3, "horas": 24, "limite_usd": 10_000},
    # Cambio de dispositivo + cambio de contraseña + transacción de más de
    # USD 200, todo en menos de 1 hora.
    "toma_cuenta": {"monto_usd": 200, "minutos": 60},
}

# --- Tasas de cambio -------------------------------------------------------

# Tasas de Frankfurter de la fecha de referencia, consultadas una vez y
# guardadas en el repo para que todas las corridas den lo mismo.
TASAS_FILE = Path(__file__).parent / "data" / "tasas_2026-10-01.json"


def validar():
    """Falla al arrancar si algún valor no tiene sentido."""
    if MODE not in VOLUMES:
        raise ValueError(f"GEN_MODE debe ser uno de {list(VOLUMES)}")

    if OUTPUT not in ("http", "file"):
        raise ValueError("GEN_OUTPUT debe ser 'http' o 'file'")

    if RATE_PER_SECOND < 0:
        raise ValueError("GEN_RATE no puede ser negativo")

    if TX_PER_ACCOUNT_DAY <= 0:
        raise ValueError("GEN_TX_PER_ACCOUNT_DAY debe ser mayor que 0")

    if not 0 <= INSTANCE_INDEX < INSTANCE_COUNT:
        raise ValueError(
            "GEN_INSTANCE_INDEX debe estar entre 0 y GEN_INSTANCE_COUNT - 1"
        )

    porcentajes = {
        "GEN_FRAUD_PERCENTAGE": FRAUD_PERCENTAGE,
        "GEN_DUPLICATE_PERCENTAGE": DUPLICATE_PERCENTAGE,
        "GEN_OUT_OF_ORDER_PERCENTAGE": OUT_OF_ORDER_PERCENTAGE,
        "GEN_DECIMAL_DEFECT_PERCENTAGE": DECIMAL_DEFECT_PERCENTAGE,
    }
    for nombre, valor in porcentajes.items():
        if not 0 <= valor <= 100:
            raise ValueError(f"{nombre} debe estar entre 0 y 100")
