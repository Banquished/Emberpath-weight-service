import pytest
from fastapi import Path
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings
from src.main import create_app


@pytest.mark.anyio
async def test_openapi_documents_standard_validation_error_response() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/items/{item_id}")
    async def get_item(item_id: int = Path()) -> dict[str, int]:
        return {"item_id": item_id}

    responses = app.openapi()["paths"]["/items/{item_id}"]["get"]["responses"]

    assert responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/items/not-an-int")

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid request"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_openapi_uses_configured_application_version() -> None:
    application = create_app(Settings(app_version="1.2.3", _env_file=None))

    assert application.openapi()["info"]["version"] == "1.2.3"
