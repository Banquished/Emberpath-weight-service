from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.auth import get_current_user
from src.core.config import Settings
from src.core.database import get_session
from src.main import create_app


def test_weight_openapi_retains_validation_contract():
    schema = create_app(Settings(_env_file=None)).openapi()
    assert "/api/v1/weight-logs" not in schema["paths"]
    for path in ("/weight-logs", "/weight-logs/{log_id}"):
        for operation in schema["paths"][path].values():
            if "422" in operation["responses"]:
                assert operation["responses"]["422"]["content"]["application/json"][
                    "schema"
                ] == {"$ref": "#/components/schemas/HTTPValidationError"}


@pytest.mark.anyio
async def test_weight_validation_body_and_protocol_headers_are_preserved():
    application = create_app(Settings(_env_file=None))

    async def unused_session():
        yield AsyncMock()

    application.dependency_overrides[get_session] = unused_session
    application.dependency_overrides[get_current_user] = uuid4
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/weight-logs/not-a-uuid")
        assert response.status_code == 422
        assert set(response.json()) == {"detail"}
        assert response.json()["detail"][0]["loc"] == ["path", "log_id"]
        assert response.headers["X-Request-ID"]
        response = await client.put("/weight-logs")
        assert response.status_code == 405
        assert response.json() == {"detail": "Method Not Allowed"}
        assert response.headers["Allow"]
