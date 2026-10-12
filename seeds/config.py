import os
from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("SEED", 42))
MODE = os.getenv("SEED_MODE", "dev")
DEFECT_PERCENTAGE = float(os.getenv("SEED_DEFECT_PERCENTAGE", 0))

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
        "users": int(os.getenv("SEED_USERS", 100_000)),
        "devices_per_user": int(os.getenv("SEED_DEVICES_PER_USER", 2)),
        "merchants": int(os.getenv("SEED_MERCHANTS", 5_000)),
        "restricted_lists": int(os.getenv("SEED_RESTRICTED_LISTS", 50_000)),
        "transactions": int(os.getenv("SEED_TRANSACTIONS", 100_000)),
    },
}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro"
)