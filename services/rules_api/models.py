"""PostgreSQL tables of the rules API.

`rules` is the current state, one row per rule. `rule_catalog_versions`
is the history: one row per change with the whole catalog it produced.
It is append-only; a trigger rejects any UPDATE, DELETE or TRUNCATE.

The tables have their own metadata (not shared/models.py): only this
service writes them, and the engine never reads them.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base(metadata=MetaData())


class Rule(Base):
    __tablename__ = "rules"

    code = Column(String(50), primary_key=True)
    type = Column(String(30), nullable=False)
    rn = Column(String(10), nullable=True)
    description = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    action = Column(String(10), nullable=False)
    opens_case = Column(Boolean, nullable=False, default=False)
    score = Column(Integer, nullable=False, default=0)
    params = Column(JSONB, nullable=False, default=dict)
    rule_version = Column(Integer, nullable=False, default=1)
    # Order of the rules created through the API (after the defaults).
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by = Column(String(100), nullable=False)


class CatalogVersion(Base):
    __tablename__ = "rule_catalog_versions"

    version = Column(Integer, primary_key=True, autoincrement=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    author = Column(String(100), nullable=False)
    # {"operation": ..., "code": ..., "before": {...} | null, "after": {...} | null}
    change = Column(JSONB, nullable=False)
    # The whole CatalogSnapshot of this version.
    snapshot = Column(JSONB, nullable=False)


IMMUTABLE_HISTORY = [
    text("""
        CREATE OR REPLACE FUNCTION rule_catalog_versions_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'rule_catalog_versions is append-only';
        END
        $$ LANGUAGE plpgsql
    """),
    text("DROP TRIGGER IF EXISTS rule_catalog_versions_no_change ON rule_catalog_versions"),
    text("""
        CREATE TRIGGER rule_catalog_versions_no_change
        BEFORE UPDATE OR DELETE ON rule_catalog_versions
        FOR EACH ROW EXECUTE FUNCTION rule_catalog_versions_append_only()
    """),
    text("DROP TRIGGER IF EXISTS rule_catalog_versions_no_truncate ON rule_catalog_versions"),
    text("""
        CREATE TRIGGER rule_catalog_versions_no_truncate
        BEFORE TRUNCATE ON rule_catalog_versions
        FOR EACH STATEMENT EXECUTE FUNCTION rule_catalog_versions_append_only()
    """),
]
