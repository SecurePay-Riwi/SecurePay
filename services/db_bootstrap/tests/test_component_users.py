"""Each component works with its own database user and nothing more
(MAG-361), against a PostgreSQL schema of its own.

Needs PostgreSQL (DATABASE_URL) with a user that may create roles (the
Compose and CI user is a superuser; in RDS the master user has
CREATEROLE). db-bootstrap creates the tables, the users and their grants;
then every component runs its real code with its own user, as in AWS
(CREATE_SCHEMA=false), and the users are dropped at the end.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, make_url, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from services.alerts import handler as alerts
from services.alerts import notify
from services.cache_loader import loader
from services.cache_loader.tests.test_loader import cache  # noqa: F401 (fixture)
from services.consumers import batch, cases, history
from services.consumers.tests import test_cases_consumer as cases_test
from services.consumers.tests import test_history_consumer as history_test
from services.db_bootstrap import bootstrap, grants
from services.reconciliation import store
from services.reconciliation.tests.test_store import _row as match_row
from shared import config, evidence
from shared.cases import (
    CASE_DUE_MINUTES,
    AccountTransaction,
    Case,
    CaseEvent,
    CaseStatus,
    ComplianceReport,
)
from shared.db import engine as dev_engine
from shared.models import Comercio
from shared.reconciliation import ReconciliationDifference, ReconciliationRun
from shared.tests.isolated_db import isolated_sessions
from shared.tests.test_evidence import FakeS3

SCHEMA = "db_bootstrap_test"

# Every character the Terraform passwords may have (override_special),
# so the URL of each user is proven to survive them.
PASSWORDS = {user: f"{user}-pw!#$%^&*()-_=+[]{{}}<>:?" for user in grants.USERS}


def _existing_users() -> set[str]:
    with dev_engine.connect() as conn:
        return set(
            conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:users)"),
                {"users": grants.USERS},
            ).scalars()
        )


def _drop_users(keep: set[str]) -> None:
    """Drop the users this test created. After the schema is dropped they
    own nothing and have no grant left, so DROP ROLE is enough (DROP OWNED
    would need membership of the role, which the RDS master user does not
    have either). Users that existed before (roles belong to the whole
    server, another local database may use them) are kept."""
    with dev_engine.begin() as conn:
        for user in set(grants.USERS) - keep:
            conn.execute(text(f'DROP ROLE IF EXISTS "{user}"'))


@pytest.fixture
def admin():
    """The master user's sessions, after db-bootstrap ran once."""
    before = _existing_users()
    try:
        with isolated_sessions(SCHEMA) as factory:
            with factory() as session:
                bootstrap.bootstrap(session, PASSWORDS.__getitem__)
            yield factory
    finally:
        _drop_users(keep=before)


def _environ(user: str) -> dict:
    """The environment of the component's Lambda, as Terraform sets it."""
    url = make_url(dev_engine.url)
    return {
        "DATABASE_USER": user,
        "DATABASE_PASSWORD_PARAMETER": f"/securepay/dev/rds/{user}",
        "DATABASE_HOST": url.host,
        "DATABASE_PORT": str(url.port or 5432),
        "DATABASE_NAME": url.database,
        "DATABASE_SSLMODE": "disable",  # local PostgreSQL has no TLS
    }


@pytest.fixture
def as_user(monkeypatch):
    """as_user(name) -> session factory of that user, built the way the
    component builds it (config.database_url with its parameter)."""
    monkeypatch.setattr(config, "CREATE_SCHEMA", False)
    engines = []

    def factory(user):
        parameter = f"/securepay/dev/rds/{user}"
        url = config.database_url(
            _environ(user), read=lambda name: {parameter: PASSWORDS[user]}[name]
        )
        engine = create_engine(
            url.replace("postgresql://", "postgresql+psycopg://", 1),
            connect_args={"options": f"-csearch_path={SCHEMA}"},
        )
        engines.append(engine)
        return sessionmaker(bind=engine)

    yield factory
    for engine in engines:
        engine.dispose()


def _denied(factory, statement: str) -> bool:
    with factory() as session:
        try:
            session.execute(text(statement))
            session.commit()
        except ProgrammingError as exc:
            return "permission denied" in str(exc) or "must be owner" in str(exc)
    return False


# --- db-bootstrap -----------------------------------------------------------


def test_every_table_exists_and_belongs_to_the_master_user(admin):
    with admin() as session:
        owners = dict(
            session.execute(
                text(
                    "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = :s"
                ),
                {"s": SCHEMA},
            ).all()
        )
        me = session.execute(text("SELECT current_user")).scalar_one()
    for table in ("usuarios", "cuentas", "cases", "case_events", "reconciliation_runs"):
        assert owners[table] == me


def test_running_it_again_changes_nothing_and_keeps_working(admin, as_user):
    with admin() as session:
        result = bootstrap.bootstrap(session, PASSWORDS.__getitem__)
    assert result["users"] == grants.USERS
    with as_user("history_consumer")() as session:
        assert session.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_a_new_password_is_applied_on_the_next_run(admin, as_user, monkeypatch):
    new = {**PASSWORDS, "alerts": "another-password-#?%"}
    with admin() as session:
        bootstrap.bootstrap(session, new.__getitem__)
    monkeypatch.setattr(
        "services.db_bootstrap.tests.test_component_users.PASSWORDS", new
    )
    with as_user("alerts")() as session:
        assert session.scalar(select(func.count()).select_from(Case)) == 0


def test_a_grant_removed_from_the_list_is_removed_in_the_database(
    admin, as_user, monkeypatch
):
    reduced = {**grants.TABLES, "list_loader": {"cuentas": grants.READ}}
    monkeypatch.setattr(bootstrap, "TABLES", reduced)
    with admin() as session:
        bootstrap.bootstrap(session, PASSWORDS.__getitem__)
    assert _denied(as_user("list_loader"), "SELECT count(*) FROM comercios")


def test_postgresql_gets_a_verifier_not_the_password():
    """The SCRAM-SHA-256 verifier of RFC 5802, as PostgreSQL stores it;
    the logins of every test above prove PostgreSQL accepts it."""
    verifier = bootstrap.scram_sha256("secret#?", salt=b"0123456789abcdef")
    assert verifier == bootstrap.scram_sha256("secret#?", salt=b"0123456789abcdef")
    assert verifier.startswith("SCRAM-SHA-256$4096:MDEyMzQ1Njc4OWFiY2RlZg==$")
    assert "secret" not in verifier


# --- each component with its own user ---------------------------------------


def test_cases_consumer_opens_a_case_and_its_compliance_report(
    admin, as_user, monkeypatch
):
    listed = cases_test._owner(admin, "1000000070", listed_as="PEP")
    clean = cases_test._owner(admin, "1000000001")
    monkeypatch.setattr(cases, "SessionLocal", as_user("cases_consumer"))

    result = cases.handler(cases_test._batch(cases_test._listed_event(listed, clean)))

    assert result == {"batchItemFailures": []}
    with admin() as session:
        assert session.scalar(select(func.count()).select_from(Case)) == 1
        assert session.scalar(select(func.count()).select_from(CaseEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ComplianceReport)) == 1


def test_history_consumer_writes_the_account_rows(admin, as_user, monkeypatch):
    monkeypatch.setattr(history, "SessionLocal", as_user("history_consumer"))
    batch._schema_ready.clear()

    result = history.handler(history_test._batch(history_test._event()))

    assert result == {"batchItemFailures": []}
    with admin() as session:
        assert session.scalar(select(func.count()).select_from(AccountTransaction)) == 2


class FakeSNS:
    def __init__(self):
        self.published = []

    def create_topic(self, Name):
        return {"TopicArn": f"arn:aws:sns:us-east-2:000000000000:{Name}"}

    def publish(self, **kwargs):
        self.published.append(kwargs)


def _alerts_work(admin, now):
    """One overdue case, one resolved case without evidence, one compliance
    report not sent yet and one history row older than 30 days."""
    created = now - timedelta(minutes=CASE_DUE_MINUTES + 10)
    common = {
        "account_id": uuid4(),
        "decision": "HOLD",
        "decision_reason": "Mule account pattern.",
        "rules_triggered": ["mule"],
        "rules_version": "3",
        "amount": Decimal("120.00"),
        "currency": "USD",
        "transaction_date": created,
        "transaction": {},
        "created_at": created,
        "due_at": created + timedelta(minutes=CASE_DUE_MINUTES),
    }
    with admin() as session:
        overdue = Case(transaction_id=uuid4(), status=CaseStatus.OPEN.value, **common)
        resolved = Case(
            transaction_id=uuid4(),
            status=CaseStatus.RESOLVED.value,
            resolved_at=created + timedelta(minutes=5),
            **common,
        )
        session.add_all([overdue, resolved])
        session.flush()
        session.add(
            ComplianceReport(
                case_id=overdue.id,
                transaction_id=overdue.transaction_id,
                account_id=overdue.account_id,
                document="1000000070",
                list_type="PEP",
                matched_at=created,
            )
        )
        session.commit()
    rows = history_test.history.history_rows(
        json.loads(json.dumps(history_test._event()))
    )
    with admin() as session:
        for row in rows:
            row["transaction_date"] = now - timedelta(days=40)
        history.write(session, rows)
        session.commit()


def test_alerts_runs_every_job(admin, as_user, monkeypatch):
    now = datetime.now(UTC)
    _alerts_work(admin, now)
    sns, s3 = FakeSNS(), FakeS3()
    monkeypatch.setattr(notify, "_client", lambda: sns)
    monkeypatch.setattr(notify, "_topic_arn", None)
    monkeypatch.setattr(evidence, "_client", lambda: s3)
    monkeypatch.setattr(alerts, "SessionLocal", as_user("alerts"))
    monkeypatch.setattr(alerts, "_schema_ready", False)

    counts = alerts.handler({}, None)

    assert counts == {"escalated": 1, "notified": 1, "purged": 2, "archived": 1}
    assert alerts.handler({"job": "reconciliation_check"}) == {
        "reconciliation_done": False
    }


def test_difference_writer_saves_the_run_and_its_differences(
    admin, as_user, monkeypatch
):
    rows = [match_row("ONLY_PAGOSEGURO"), match_row("MATCHED", reference="ref-2")]
    day = rows[0].run_day
    with as_user("reconciliation")() as session:
        result = store.save(session, day, rows, {"files_read": 1}, datetime.now(UTC))
    with as_user("reconciliation")() as session:  # again: the upsert path
        store.save(session, day, rows, {"files_read": 1}, datetime.now(UTC))

    assert result["new_differences"] == 1
    with admin() as session:
        assert session.scalar(select(func.count()).select_from(ReconciliationRun)) == 1
        assert (
            session.scalar(select(func.count()).select_from(ReconciliationDifference))
            == 1
        )


def test_list_loader_copies_the_reference_data(admin, as_user, cache):  # noqa: F811
    cases_test._owner(admin, "1000000070", listed_as="PEP")
    with admin() as session:
        session.add(
            Comercio(
                nombre="Shop",
                categoria="retail",
                estado="activo",
                fecha_creacion=datetime(2026, 1, 1),
            )
        )
        session.commit()

    with as_user("list_loader")() as session:
        counts = loader.load(
            session, cache=cache, now=datetime(2026, 11, 3, tzinfo=UTC)
        )

    assert (counts["accounts"], counts["merchants"], counts["restricted"]) == (1, 1, 1)


def test_analytics_export_writes_the_raw_layer(admin, as_user, monkeypatch, tmp_path):
    from services.analytics import export

    monkeypatch.setattr(export, "SessionLocal", as_user("analytics_export"))
    monkeypatch.setattr(export, "ANALYTICS_DATA_DIR", str(tmp_path))

    result = export.handler({"day": "2026-10-05"})

    assert result["day"] == "2026-10-05"
    assert (tmp_path / "raw" / "cases" / "fecha=2026-10-05" / "cases.jsonl").exists()


def test_analytics_export_reads_what_the_kaggle_replay_needs(admin, as_user, tmp_path):
    """MAG-312: the Kaggle rows, the reference data and the catalog."""
    from services.analytics import metrics

    with as_user("analytics_export")() as session:
        done = metrics.kaggle_metrics(session, str(tmp_path))

    # db-bootstrap stored version 1; the seed of this schema has no Kaggle rows.
    assert done["rules_version"] == "1"
    assert done["transactions"] == 0


def test_rules_api_changes_the_catalog_with_its_user(admin, as_user, monkeypatch):
    from services.rules_api import store as rules_store

    monkeypatch.setattr(rules_store, "SessionLocal", as_user("rules_api"))

    def disable(session, rules):
        rule = rules["velocity"].model_copy(update={"enabled": False})
        rules_store.save(session, rule, "ana")
        return {"operation": "disable", "code": "velocity"}, [rule]

    snapshot, _ = rules_store.write("ana", disable)

    # db-bootstrap stored version 1 with the code defaults.
    assert snapshot.version == 2
    assert rules_store.latest().version == 2
    assert not next(r for r in snapshot.rules if r.code == "velocity").enabled


def test_cases_api_assigns_and_resolves_with_its_user(admin, as_user, monkeypatch):
    from fastapi.testclient import TestClient

    from services.cases_api import deps
    from services.cases_api.main import app

    now = datetime.now(UTC)
    _alerts_work(admin, now)
    with admin() as session:
        case_id = session.scalar(
            select(Case.id).where(Case.status == CaseStatus.OPEN.value)
        )
    monkeypatch.setattr(evidence, "archive", lambda session, case: None)
    monkeypatch.setattr(deps, "SessionLocal", as_user("cases_api"))
    ana = {"X-User": "ana"}

    with TestClient(app) as client:
        assigned = client.put(
            f"/cases/{case_id}/assignee", json={"assignee": "ana"}, headers=ana
        )
        resolved = client.post(
            f"/cases/{case_id}/resolution",
            json={"outcome": "LEGITIMATE", "note": "Confirmed by phone."},
            headers=ana,
        )
        reads = [
            client.get("/cases"),
            client.get(f"/cases/{case_id}"),
            client.get("/compliance/restricted-list-reports"),
            client.get("/reconciliation/differences"),
            client.get("/reconciliation/differences/aging"),
            client.get(f"/reports/suspicious?from={now.date()}&to={now.date()}"),
        ]

    assert (assigned.status_code, resolved.status_code) == (200, 200), (
        assigned.text,
        resolved.text,
    )
    assert [r.status_code for r in reads] == [200] * len(reads)


# --- and nothing more ---------------------------------------------------------


@pytest.mark.parametrize("user", grants.USERS)
def test_no_user_can_drop_change_or_create_tables(admin, as_user, user):
    factory = as_user(user)
    assert _denied(factory, "DROP TABLE cases")
    assert _denied(factory, "TRUNCATE usuarios")
    assert _denied(factory, "ALTER TABLE cuentas ADD COLUMN x int")
    assert _denied(factory, f"CREATE TABLE {SCHEMA}.intruder (id int)")


@pytest.mark.parametrize(
    "user, statement",
    [
        ("cases_consumer", "DELETE FROM cases"),
        ("cases_consumer", "UPDATE cases SET status = 'RESOLVED'"),
        ("cases_consumer", "SELECT count(*) FROM account_transactions"),
        ("history_consumer", "SELECT count(*) FROM cases"),
        ("history_consumer", "SELECT count(*) FROM usuarios"),
        ("history_consumer", "DELETE FROM account_transactions"),
        ("alerts", "DELETE FROM cases"),
        ("alerts", "DELETE FROM case_events"),
        ("alerts", "SELECT count(*) FROM usuarios"),
        ("reconciliation", "SELECT count(*) FROM cases"),
        ("reconciliation", "DELETE FROM reconciliation_differences"),
        ("list_loader", "INSERT INTO listas_restrictivas (documento) VALUES ('1')"),
        ("list_loader", "SELECT count(*) FROM cases"),
        ("analytics_export", "SELECT count(*) FROM compliance_reports"),
        ("analytics_export", "SELECT count(*) FROM account_transactions"),
        ("analytics_export", "UPDATE transacciones SET is_fraud = true"),
        ("analytics_export", "UPDATE cases SET status = 'RESOLVED'"),
        ("rules_api", "DELETE FROM rules"),
        ("rules_api", "SELECT count(*) FROM cases"),
        ("rules_api", "INSERT INTO listas_restrictivas (documento) VALUES ('1')"),
        ("cases_api", "DELETE FROM cases"),
        ("cases_api", "INSERT INTO cases (transaction_id) VALUES (gen_random_uuid())"),
        ("cases_api", "SELECT count(*) FROM usuarios"),
        ("cases_api", "UPDATE compliance_reports SET notified_at = now()"),
        ("cases_api", "DELETE FROM account_transactions"),
        ("analytics_export", "DELETE FROM reconciliation_differences"),
        (
            "analytics_export",
            "INSERT INTO reconciliation_runs (run_day) VALUES ('2026-10-05')",
        ),
    ],
)
def test_each_user_is_denied_what_it_does_not_need(admin, as_user, user, statement):
    assert _denied(as_user(user), statement)


def test_the_append_only_events_stay_append_only(admin, as_user):
    for user in ("cases_consumer", "alerts", "cases_api"):
        assert _denied(as_user(user), "UPDATE case_events SET actor = 'x'")


# --- configuration --------------------------------------------------------------


def test_without_database_user_the_url_is_database_url():
    url = "postgresql://a:b@localhost:5433/x"
    assert config.database_url({"DATABASE_URL": url}) == url


def test_the_password_is_read_from_its_parameter_and_survives_any_character():
    password = "p!#$%^&*()-_=+[]{}<>:?/@ "
    read = []
    url = config.database_url(
        {
            "DATABASE_USER": "alerts",
            "DATABASE_PASSWORD_PARAMETER": "/securepay/dev/rds/alerts",
            "DATABASE_HOST": "db.example",
        },
        read=lambda name: read.append(name) or password,
    )
    parsed = make_url(url)
    assert read == ["/securepay/dev/rds/alerts"]
    assert (parsed.username, parsed.password) == ("alerts", password)
    assert (parsed.host, parsed.port, parsed.database) == (
        "db.example",
        5432,
        "securepay",
    )
    assert parsed.query["sslmode"] == "require"


def test_create_schema_does_nothing_in_aws(monkeypatch):
    """With CREATE_SCHEMA=false it does not even touch the session."""
    from shared import cases as case_tables
    from shared import reconciliation

    monkeypatch.setattr(config, "CREATE_SCHEMA", False)
    from services.rules_api import store as rules_store

    case_tables.create_schema(None)
    reconciliation.create_schema(None)
    rules_store.create_schema(None)


def test_every_table_in_the_grants_exists(admin):
    with admin() as session:
        tables = set(
            session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
                {"s": SCHEMA},
            ).scalars()
        )
    for user, granted in grants.TABLES.items():
        assert set(granted) <= tables, user


def test_terraform_knows_every_user():
    """grants.py, the IAM role of db-bootstrap, the Lambdas' environment and
    the passwords in Parameter Store name the same users."""
    import re
    from pathlib import Path

    terraform = Path(__file__).parents[3] / "infra" / "terraform" / "modules"

    def users(path, start):
        source = (terraform / path).read_text()
        block = source[source.index(start) :]
        listed = re.search(r"(?:default\s*=|for user in)\s*\[([^\]]*)\]", block)
        return set(re.findall(r'"([a-z_]+)"', listed.group(1)))

    expected = set(grants.USERS)
    assert users("iam/variables.tf", 'variable "database_users"') == expected
    assert users("lambdas/main.tf", "database_user = { for user in [") == expected
    assert expected <= users("database/variables.tf", 'variable "component_users"')
