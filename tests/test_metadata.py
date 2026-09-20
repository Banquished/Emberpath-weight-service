from unittest.mock import PropertyMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings
from src.core.database import Database
from src.main import create_app


@pytest.mark.anyio
async def test_root_returns_default_metadata_without_database_or_auth():
    app = create_app(Settings(_env_file=None))
    with patch.object(
        Database, "session_factory", new_callable=PropertyMock
    ) as sessions:
        sessions.side_effect = AssertionError("Metadata must not access the database")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")
        sessions.assert_not_called()
    assert response.status_code == 200
    assert response.json() == {
        "service": "Emberpath Weight Service",
        "version": "0.1.0",
        "documentation": "/docs",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("environment", "docs_enabled", "has_docs"),
    [
        ("production", None, False),
        ("production", True, True),
        ("development", False, False),
    ],
)
async def test_metadata_uses_settings_and_advertises_only_enabled_docs(
    environment, docs_enabled, has_docs
):
    app = create_app(
        Settings(
            _env_file=None,
            app_name="Example Service",
            app_version="2.3.4",
            environment=environment,
            allowed_hosts=["test"],
            docs_enabled=docs_enabled,
            database_required=True,
            database_url="postgresql+psycopg://service:unused@127.0.0.1:1/service",
        )
    )
    with patch.object(
        Database, "session_factory", new_callable=PropertyMock
    ) as sessions:
        sessions.side_effect = AssertionError("Metadata must not access the database")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")
            documentation = await client.get("/docs")
        sessions.assert_not_called()
    assert response.status_code == 200
    expected = {"service": "Example Service", "version": "2.3.4"}
    if has_docs:
        expected["documentation"] = "/docs"
    assert response.json() == expected
    assert documentation.status_code == (200 if has_docs else 404)
