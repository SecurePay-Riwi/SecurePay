"""The accounts and merchants the load test sends money between (HU-60).

    uv run python -m infra.load.accounts

reads the seed's PostgreSQL (DATABASE_URL) and writes accounts.json next
to this file: the active accounts with their currency and the active
merchants. The seed is deterministic and AWS dev is seeded in the same
mode (SEED_MODE=dev, 100 users), so the file works against dev's engine
too; run it again only if the seed changes.
"""

import json
from pathlib import Path

from sqlalchemy import text

from shared.db import SessionLocal

OUTPUT = Path(__file__).resolve().parent / "accounts.json"


def read(session) -> dict:
    accounts = session.execute(
        text("SELECT id, moneda FROM cuentas WHERE estado = 'activa' ORDER BY id")
    ).all()
    merchants = session.execute(
        text("SELECT id FROM comercios WHERE estado = 'activo' ORDER BY id")
    ).all()
    return {
        "accounts": [{"id": str(a.id), "currency": a.moneda} for a in accounts],
        "merchants": [str(m.id) for m in merchants],
    }


def main() -> None:
    with SessionLocal() as session:
        data = read(session)
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{len(data['accounts'])} accounts, {len(data['merchants'])} merchants")


if __name__ == "__main__":
    main()
