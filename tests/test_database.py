import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.config import Config
from fastapi import Request
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from src.core.config import Settings
from src.core.database import Database, get_session
from src.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_database_applies_connection_and_query_timeouts() -> None:
    database = Database(
        Settings(
            database_url="postgresql+psycopg://service:password@localhost:5432/service",
            database_connect_timeout_seconds=2,
            database_statement_timeout_seconds=5,
            database_lock_timeout_seconds=3,
            database_idle_transaction_timeout_seconds=9,
            _env_file=None,
        )
    )

    with patch("src.core.database.create_async_engine") as create_engine:
        _ = database.engine

    assert create_engine.call_args.kwargs["hide_parameters"] is True
    assert create_engine.call_args.kwargs["connect_args"] == {
        "connect_timeout": 2,
        "options": (
            "-c statement_timeout=5000 -c lock_timeout=3000 "
            "-c idle_in_transaction_session_timeout=9000"
        ),
    }


@pytest.mark.anyio
async def test_get_session_uses_factory_app_database() -> None:
    app = create_app(
        Settings(
            database_url="postgresql+psycopg://service:password@localhost:5432/service",
            _env_file=None,
        )
    )
    session = AsyncMock()
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session_context)
    app.state.database._session_factory = session_factory
    request = Request({"type": "http", "app": app})

    sessions = get_session(request)

    assert await anext(sessions) is session
    session_factory.assert_called_once_with()
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)


@pytest.mark.integration
@pytest.mark.anyio
async def test_migrations_and_database_session() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL and a database ending _test")

    database = Database(Settings(database_url=database_url, _env_file=None))
    try:
        config = Config(ROOT / "alembic.ini")
        config.attributes["database_url"] = database_url
        command.upgrade(config, "head")
        command.check(config)
        async with database.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        assert {"alembic_version", "weight_logs"} <= set(table_names)
        async with database.session_factory() as session:
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await database.dispose()
