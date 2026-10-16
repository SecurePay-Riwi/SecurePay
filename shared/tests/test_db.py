from shared.db import engine, url_con_psycopg3


def test_plain_postgresql_url_uses_psycopg3():
    url = "postgresql://usuario:clave@localhost:5432/pagoseguro"
    assert url_con_psycopg3(url) == "postgresql+psycopg://usuario:clave@localhost:5432/pagoseguro"


def test_postgres_alias_uses_psycopg3():
    assert url_con_psycopg3("postgres://u:p@h/db").startswith("postgresql+psycopg://")


def test_explicit_driver_is_respected():
    url = "postgresql+psycopg://u:p@h/db"
    assert url_con_psycopg3(url) == url


def test_engine_uses_the_installed_driver():
    assert engine.dialect.driver == "psycopg"
