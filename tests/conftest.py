import pytest
from sqlalchemy.exc import OperationalError


@pytest.fixture(scope="session", autouse=True)
def reference_data_cache():
    """Accounts, merchants and the restricted list in the cache, from the
    seeded PostgreSQL, as the cache-loader service does in Compose."""
    from services.cache_loader import loader

    try:
        with loader.SessionLocal() as session:
            loader.load(session)
    except OperationalError:
        pass
