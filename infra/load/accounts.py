"""The accounts and merchants the load test sends money between (HU-60).

    uv run python -m infra.load.accounts

reads the seed's PostgreSQL (DATABASE_URL) and writes accounts.json next
to this file: active accounts with their currency, active accounts whose
owners are on the restricted list, and active merchants. The seed is
deterministic and AWS dev is seeded with the same volume (SEED_MODE=dev,
SEED_USERS=10000 in envs/dev), so the file works against dev's engine too;
seed with SEED_USERS=10000 before running it, and run it again only if the
seed changes. One account per line.
"""

import json
from pathlib import Path

from sqlalchemy import text

from shared.db import SessionLocal
from shared.refdata import digits

OUTPUT = Path(__file__).resolve().parent / "accounts.json"


def read(session) -> dict:
    accounts = session.execute(
        text(
            "SELECT c.id, c.moneda, u.documento "
            "FROM cuentas c JOIN usuarios u ON u.id = c.user_id "
            "WHERE c.estado = 'activa' ORDER BY c.id"
        )
    ).all()
    restricted_documents = {
        digits(documento)
        for (documento,) in session.execute(
            text("SELECT documento FROM listas_restrictivas")
        ).all()
    }
    merchants = session.execute(
        text("SELECT id FROM comercios WHERE estado = 'activo' ORDER BY id")
    ).all()
    return {
        "accounts": [{"id": str(a.id), "currency": a.moneda} for a in accounts],
        "restricted_accounts": [
            str(a.id) for a in accounts if digits(a.documento) in restricted_documents
        ],
        "merchants": [str(m.id) for m in merchants],
    }


def main() -> None:
    with SessionLocal() as session:
        data = read(session)
    lines = [json.dumps(a) for a in data["accounts"]]
    OUTPUT.write_text(
        '{"accounts": [\n'
        + ",\n".join(lines)
        + '\n],\n"restricted_accounts": '
        + json.dumps(data["restricted_accounts"])
        + ',\n"merchants": '
        + json.dumps(data["merchants"])
        + "}\n",
        encoding="utf-8",
    )
    print(
        f"{len(data['accounts'])} accounts, "
        f"{len(data['restricted_accounts'])} restricted accounts, "
        f"{len(data['merchants'])} merchants"
    )


if __name__ == "__main__":
    main()
