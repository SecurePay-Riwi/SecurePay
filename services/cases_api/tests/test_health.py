from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from services.cases_api import deps


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_creates_the_case_tables(client, sessions):
    with sessions() as session:
        tables = set(inspect(session.connection()).get_table_names())
    assert {"cases", "case_events", "compliance_reports", "account_transactions"} <= tables


def test_health_without_postgresql_is_503(client):
    down = create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x")
    deps.bind(sessionmaker(bind=down))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "The cases database is not available."}
