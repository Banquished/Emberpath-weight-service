import asyncio
import os
import sys
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from src.core.config import Settings
from src.core.database import Database, get_session

# Import the module-level ASGI app without loading a developer's local dotenv file.
with patch.dict(Settings.model_config, env_file=None):
    from src.main import create_app


@pytest.fixture
def anyio_backend() -> str | tuple[str, dict[str, object]]:
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("Set TEST_DATABASE_URL to run weight CRUD integration tests")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        pytest.fail("TEST_DATABASE_URL must use PostgreSQL and a database ending _test")
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
async def client(test_database_url: str) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url=test_database_url, database_required=True, _env_file=None
    )
    application = create_app(settings)
    database: Database = application.state.database
    async with (
        application.router.lifespan_context(application),
        database.engine.connect() as connection,
    ):
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:

                async def override_session() -> AsyncIterator[AsyncSession]:
                    yield session

                application.dependency_overrides[get_session] = override_session
                async with AsyncClient(
                    transport=ASGITransport(app=application), base_url="http://test"
                ) as http_client:
                    yield http_client
        finally:
            application.dependency_overrides.clear()
            await transaction.rollback()
