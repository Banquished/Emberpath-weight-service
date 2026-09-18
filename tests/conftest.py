import os
from collections.abc import Iterator

import pytest
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from src.core.database import get_session
from src.main import app

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://emberpath:emberpath_test@127.0.0.1:5433/emberpath_test"
)


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    database_url = (
        os.getenv("TEST_DATABASE_URL")
        or dotenv_values(".env").get("TEST_DATABASE_URL")
        or DEFAULT_TEST_DATABASE_URL
    )
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        pytest.fail(
            "TEST_DATABASE_URL must point to a PostgreSQL database ending _test"
        )

    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def client(database_engine: Engine) -> Iterator[TestClient]:
    with database_engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:

            def override_session() -> Iterator[Session]:
                yield session

            app.dependency_overrides[get_session] = override_session
            try:
                with TestClient(app) as test_client:
                    yield test_client
            finally:
                app.dependency_overrides.pop(get_session, None)
        transaction.rollback()
