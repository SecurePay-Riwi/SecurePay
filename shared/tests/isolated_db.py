"""An empty PostgreSQL schema of its own for a test, so the tables of the
dev database are never touched. Used by the tests of the case tables
(shared, consumers, cases API, alerts task).

    with isolated_sessions("cases_api_test") as Session:
        with Session() as session:
            create_schema(session)
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from shared.db import engine as dev_engine


@contextmanager
def isolated_sessions(schema: str) -> Iterator[sessionmaker]:
    """A session factory whose search_path is a new, empty schema; the
    schema is dropped afterwards. The seed's tables are not in it."""
    with dev_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(dev_engine.url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()
        with dev_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def down_sessions() -> sessionmaker:
    """A session factory for a PostgreSQL that is down. ``connect_timeout``
    matters: on Linux port 1 refuses at once, but on Windows the connection
    waits forever without it."""
    return sessionmaker(
        bind=create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x", connect_args={"connect_timeout": 1})
    )
