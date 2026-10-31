"""What every route of the cases API uses: a PostgreSQL session and the
X-User header. Routes import this module, never main.py.

    def assign(case_id: UUID, body: AssigneeChange,
               session: Annotated[Session, Depends(deps.get_session)],
               x_user: Annotated[str | None, Header()] = None):
        actor = deps.author(x_user)

The tests point the API at a schema of their own with bind().
"""

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from shared import db

SessionLocal = db.SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def author(value: str | None) -> str:
    """The X-User of a request that changes a case: 1 to 100 characters,
    or 400. Optional on reads."""
    name = (value or "").strip()
    if not 1 <= len(name) <= 100:
        raise HTTPException(status_code=400, detail="X-User must have 1 to 100 characters.")
    return name


def bind(maker: sessionmaker) -> None:
    """Use another session factory (the tests use their own schema)."""
    global SessionLocal
    SessionLocal = maker
