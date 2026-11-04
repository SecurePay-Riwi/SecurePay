"""Prepares the database for the components' own users (MAG-361).

Terraform invokes this Lambda on every apply that creates the database or
changes a password (aws_lambda_invocation). With the master user it:

1. creates every table: the seed's (shared/models.py), the case tables
   with their append-only trigger and the reconciliation tables. The seed
   finds them already there and only inserts; its reset uses TRUNCATE, so
   the grants below survive every reseed;
2. creates or updates the user of each component with its password from
   Parameter Store;
3. gives each user only the grants of grants.py, after revoking what it
   had, so a grant removed from grants.py is removed in the database too.

Idempotent. The passwords are read here, never received in the event, and
never returned or logged: the invocation result is kept in the Terraform
state. PostgreSQL gets a SCRAM-SHA-256 verifier, not the password, so the
password is not in the statement either.
"""

import base64
import hashlib
import hmac
import logging
import os
from collections.abc import Callable

from psycopg import sql
from sqlalchemy.orm import Session

from services.db_bootstrap.grants import SEQUENCES, TABLES, USERS
from shared import cases, reconciliation
from shared.config import read_parameter
from shared.models import Base as SeedBase

log = logging.getLogger(__name__)

# Parent path of the passwords: /securepay/<env>/rds (one per user).
PARAMETER_PATH = os.getenv("DATABASE_PARAMETER_PATH", "/securepay/dev/rds")

SCRAM_ITERATIONS = 4096  # PostgreSQL's default


def scram_sha256(password: str, salt: bytes | None = None) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores for this password
    (RFC 5802, as pg_authid keeps it). The generated passwords are ASCII,
    which SASLprep leaves as they are."""
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, SCRAM_ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    stored_key = hashlib.sha256(client_key).digest()

    def b64(value: bytes) -> str:
        return base64.b64encode(value).decode()

    return (
        f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt)}"
        f"${b64(stored_key)}:{b64(server_key)}"
    )


def create_tables(session: Session) -> None:
    """Every table, as the master user (the owner)."""
    SeedBase.metadata.create_all(session.connection())
    session.commit()
    cases.create_schema(session, force=True)
    reconciliation.create_schema(session, force=True)


def set_user(cursor, user: str, password: str, schema: str) -> None:
    """Create or update the user and leave it with exactly its grants."""
    role = sql.Identifier(user)
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,))
    # A new role has none of SUPERUSER, CREATEDB or CREATEROLE. ALTER only
    # touches LOGIN and the password: the RDS master user is not a
    # superuser and may not even name the SUPERUSER attribute.
    verb = sql.SQL("ALTER") if cursor.fetchone() else sql.SQL("CREATE")
    cursor.execute(
        sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
            verb, role, sql.Literal(scram_sha256(password))
        )
    )

    namespace = sql.Identifier(schema)
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(namespace, role)
    )
    cursor.execute(
        sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {}").format(
            namespace, role
        )
    )
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, role))

    for table, privileges in TABLES[user].items():
        cursor.execute(
            sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                sql.SQL(", ").join(sql.SQL(p) for p in privileges),
                sql.Identifier(schema, table),
                role,
            )
        )
    for table, column in SEQUENCES.get(user, []):
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, %s)",
            (f"{schema}.{table}", column),
        )
        (sequence,) = cursor.fetchone()
        cursor.execute(
            sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(sql.SQL(sequence), role)
        )


def bootstrap(session: Session, password: Callable[[str], str]) -> dict:
    """Tables, users and grants in the schema of the session's search_path
    (public in AWS; a schema of its own in the tests). password(user)
    returns that user's password."""
    create_tables(session)

    connection = session.connection()
    schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    cursor = connection.connection.driver_connection.cursor()
    # PostgreSQL 15+ already denies it; kept explicit for an older engine.
    cursor.execute(
        sql.SQL("REVOKE CREATE ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema))
    )
    for user in USERS:
        set_user(cursor, user, password(user), schema)
    session.commit()

    tables = sum(len(t) for t in TABLES.values())
    log.info(
        "db-bootstrap: %d users, %d table grants in %s", len(USERS), tables, schema
    )
    return {"users": USERS, "schema": schema, "table_grants": tables}


def handler(event=None, context=None) -> dict:
    """Lambda entry point. The event is ignored: Terraform only changes it
    to make the invocation run again."""
    from shared.db import SessionLocal

    with SessionLocal() as session:
        return bootstrap(
            session, lambda user: read_parameter(f"{PARAMETER_PATH}/{user}")
        )
