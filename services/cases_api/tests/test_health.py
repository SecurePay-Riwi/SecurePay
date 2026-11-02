from sqlalchemy import inspect

from services.cases_api import deps
from shared.tests.isolated_db import down_sessions


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_creates_the_case_tables(client, sessions):
    with sessions() as session:
        tables = set(inspect(session.connection()).get_table_names())
    assert {"cases", "case_events", "compliance_reports", "account_transactions"} <= tables


def test_health_without_postgresql_is_503(client):
    deps.bind(down_sessions())

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "The cases database is not available."}
