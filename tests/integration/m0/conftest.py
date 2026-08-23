import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from benchmark_adapters.postgres import create_product_engine


@pytest.fixture()
def product_engine():
    database_url = os.environ.get("M0_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("M0_TEST_DATABASE_URL is not configured")
    if os.environ.get("M0_TEST_DATABASE_ALLOW_DESTRUCTIVE") != "1":
        pytest.skip("destructive M0 test database guard is not enabled")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("M0 integration tests require a database ending in _test")

    engine = create_product_engine(database_url, pool_size=9)
    lock_connection = engine.connect()
    lock_connection.execute(text("SELECT pg_advisory_lock(7430021999)"))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE studies CASCADE"))
        yield engine
    finally:
        lock_connection.execute(text("SELECT pg_advisory_unlock(7430021999)"))
        lock_connection.close()
        engine.dispose()
