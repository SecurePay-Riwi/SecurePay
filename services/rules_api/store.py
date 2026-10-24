"""Versioned rule catalog in PostgreSQL.

Every write runs in one transaction: take the catalog lock, change
`rules`, build the whole CatalogSnapshot from it, insert it in
`rule_catalog_versions` with version max + 1, commit. The lock
(a transaction advisory lock) makes concurrent writes wait for each
other, so versions never repeat and no change is lost.

Publishing to Valkey happens after the commit, in main.py.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from services.rules_api.models import IMMUTABLE_HISTORY, Base, CatalogVersion, Rule
from shared import db
from shared.rule_catalog import DEFAULT_RULES, CatalogSnapshot, RuleEntry

# Any constant works; it only has to be the same for every writer.
CATALOG_LOCK = 4133

SessionLocal = db.SessionLocal

_DEFAULT_ORDER = {rule.code: i for i, rule in enumerate(DEFAULT_RULES)}


class NoChange(Exception):
    """The write would leave the catalog as it is: no new version."""


def create_schema() -> None:
    """Create the tables and the append-only trigger if they are missing,
    and store version 1 with the code defaults when there is none."""
    with SessionLocal() as session, session.begin():
        # Under the lock, so two replicas starting together do not race.
        _lock(session)
        Base.metadata.create_all(session.connection())
        for statement in IMMUTABLE_HISTORY:
            session.execute(statement)

        if session.scalar(select(func.count()).select_from(CatalogVersion)) == 0:
            now = datetime.now(UTC)
            for rule in DEFAULT_RULES:
                session.add(_to_row(rule, "code", now))
            session.flush()
            _insert_version(
                session, "code", now,
                {"operation": "seed", "code": None, "before": None, "after": None},
            )


def latest() -> CatalogSnapshot:
    with SessionLocal() as session:
        row = session.scalars(
            select(CatalogVersion).order_by(CatalogVersion.version.desc()).limit(1)
        ).first()
        return CatalogSnapshot.model_validate(row.snapshot)


def version(number: int) -> CatalogSnapshot | None:
    with SessionLocal() as session:
        row = session.get(CatalogVersion, number)
        return None if row is None else CatalogSnapshot.model_validate(row.snapshot)


def versions(limit: int, offset: int) -> tuple[int, list[CatalogVersion]]:
    """Total number of versions and one page of them, newest first."""
    with SessionLocal() as session:
        total = session.scalar(select(func.count()).select_from(CatalogVersion))
        rows = session.scalars(
            select(CatalogVersion)
            .order_by(CatalogVersion.version.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        session.expunge_all()
        return total, rows


def write(
    author: str,
    change: Callable[[Session, dict[str, RuleEntry]], tuple[dict, list[RuleEntry]]],
) -> tuple[CatalogSnapshot, list[RuleEntry]]:
    """Apply one change and store the version it produces.

    `change(session, rules)` gets the current rules by code, writes the
    rows it changes (with `save()`) and returns the change record and
    the rules it changed. It raises NoChange (or an HTTP error) to stop
    without a new version.
    """
    with SessionLocal() as session, session.begin():
        _lock(session)
        rules = {row.code: _to_entry(row) for row in session.scalars(select(Rule))}
        record, changed = change(session, rules)
        session.flush()
        snapshot = _insert_version(session, author, datetime.now(UTC), record)
        return snapshot, changed


def save(session: Session, rule: RuleEntry, author: str) -> None:
    """Insert or replace the row of one rule."""
    row = session.get(Rule, rule.code)
    now = datetime.now(UTC)
    if row is None:
        session.add(_to_row(rule, author, now))
        return

    for field, value in rule.model_dump(mode="json").items():
        setattr(row, field, value)
    row.updated_at = now
    row.updated_by = author


def _lock(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_LOCK})


def _insert_version(session: Session, author: str, now: datetime, record: dict) -> CatalogSnapshot:
    number = (session.scalar(select(func.max(CatalogVersion.version))) or 0) + 1
    snapshot = CatalogSnapshot(version=number, created_at=now, author=author, rules=_ordered(session))
    session.add(CatalogVersion(
        version=number,
        created_at=now,
        author=author,
        change=record,
        snapshot=snapshot.model_dump(mode="json"),
    ))
    return snapshot


def _ordered(session: Session) -> list[RuleEntry]:
    """The default rules in their code order, then the created ones by
    creation date. The catalog order is the evaluation order."""
    rows = session.scalars(select(Rule)).all()
    rows.sort(key=lambda r: (
        _DEFAULT_ORDER.get(r.code, len(_DEFAULT_ORDER)), r.created_at, r.code,
    ))
    return [_to_entry(row) for row in rows]


def _to_row(rule: RuleEntry, author: str, now: datetime) -> Rule:
    return Rule(**rule.model_dump(mode="json"), created_at=now, updated_at=now, updated_by=author)


def _to_entry(row: Rule) -> RuleEntry:
    return RuleEntry(
        code=row.code, type=row.type, rn=row.rn, description=row.description,
        enabled=row.enabled, action=row.action, opens_case=row.opens_case,
        score=row.score, params=row.params, rule_version=row.rule_version,
    )


def bind(maker: sessionmaker) -> None:
    """Use another session factory (the tests use their own schema)."""
    global SessionLocal
    SessionLocal = maker
