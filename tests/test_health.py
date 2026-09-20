import logging
from logging.handlers import BufferingHandler

import pytest
from httpx import ASGITransport, AsyncClient

from src import main
from src.core.config import Settings


def get_client(
    app, *, base_url: str = "http://test", raise_app_exceptions: bool = True
) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url=base_url,
    )


@pytest.mark.anyio
async def test_healthz() -> None:
    app = main.create_app(Settings(_env_file=None))
    async with get_client(app) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readyz_without_required_database() -> None:
    app = main.create_app(Settings(_env_file=None))
    async with get_client(app) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readyz_uses_the_factory_database_configuration() -> None:
    app = main.create_app(
        Settings(
            database_required=True,
            database_url="postgresql+psycopg://service:password@127.0.0.1:1/service",
            _env_file=None,
        )
    )
    async with get_client(app, raise_app_exceptions=False) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is unavailable"


@pytest.mark.anyio
async def test_healthz_returns_request_id_and_security_headers() -> None:
    app = main.create_app(Settings(_env_file=None))
    async with get_client(app) as client:
        response = await client.get(
            "/healthz", headers={"X-Request-ID": "test-request"}
        )

    assert response.headers["X-Request-ID"] == "test-request"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.anyio
async def test_invalid_request_id_is_replaced() -> None:
    app = main.create_app(Settings(_env_file=None))
    async with get_client(app) as client:
        response = await client.get(
            "/healthz", headers={"X-Request-ID": "invalid value"}
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid value"


@pytest.mark.anyio
async def test_unhandled_errors_return_the_standard_error_shape() -> None:
    app = main.create_app(Settings(_env_file=None))

    @app.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("test failure")

    async with get_client(app, raise_app_exceptions=False) as client:
        response = await client.get("/test-error")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_unhandled_errors_emit_completed_request_telemetry() -> None:
    app = main.create_app(Settings(_env_file=None))

    @app.get("/test-error-telemetry")
    async def test_error() -> None:
        raise RuntimeError("test failure")

    middleware_logger = logging.getLogger("src.core.middleware")
    capture_handler = BufferingHandler(capacity=100)
    middleware_logger.addHandler(capture_handler)
    try:
        async with get_client(app, raise_app_exceptions=False) as client:
            response = await client.get(
                "/test-error-telemetry",
                headers={"X-Request-ID": "telemetry-request"},
            )
    finally:
        middleware_logger.removeHandler(capture_handler)

    completed_logs = [
        record
        for record in capture_handler.buffer
        if record.message == "request_completed"
    ]

    assert response.status_code == 500
    assert len(completed_logs) == 1
    assert completed_logs[0].request_id == "telemetry-request"
    assert completed_logs[0].method == "GET"
    assert completed_logs[0].path == "/test-error-telemetry"
    assert completed_logs[0].status_code == 500
    assert completed_logs[0].duration_ms >= 0


@pytest.mark.anyio
async def test_framework_errors_return_the_standard_error_shape() -> None:
    app = main.create_app(
        Settings(
            allowed_hosts=["api.example.com"],
            cors_origins=["https://app.example.com"],
            _env_file=None,
        )
    )
    async with get_client(app, base_url="http://api.example.com") as client:
        not_found = await client.get("/missing")
        invalid_host = await client.get(
            "/healthz", headers={"Host": "invalid.example.com"}
        )
        invalid_origin = await client.options(
            "/healthz",
            headers={
                "Origin": "https://invalid.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    for response in (not_found, invalid_host, invalid_origin):
        assert response.headers["content-type"] == "application/json"
        assert response.json()["request_id"] == response.headers["X-Request-ID"]

    assert not_found.status_code == 404
    assert not_found.json()["detail"] == "Not Found"
    assert invalid_host.status_code == 400
    assert invalid_host.json()["detail"] == "Invalid host header"
    assert invalid_origin.status_code == 400
    assert invalid_origin.json()["detail"] == "Disallowed CORS origin"


@pytest.mark.anyio
async def test_cors_credentials_are_disabled_by_default() -> None:
    app = main.create_app(
        Settings(cors_origins=["https://app.example.com"], _env_file=None)
    )
    async with get_client(app) as client:
        response = await client.options(
            "/healthz",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert "access-control-allow-credentials" not in response.headers
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.anyio
async def test_cors_defaults_to_get_only() -> None:
    app = main.create_app(
        Settings(cors_origins=["https://app.example.com"], _env_file=None)
    )
    async with get_client(app) as client:
        response = await client.options(
            "/healthz",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Disallowed CORS method"


def test_openapi_documents_operational_response_models() -> None:
    app = main.create_app(Settings(_env_file=None))
    responses = app.openapi()["paths"]["/readyz"]["get"]["responses"]

    assert "200" in responses
    assert "503" in responses


@pytest.mark.anyio
async def test_lifespan_disposes_shared_resources(monkeypatch) -> None:
    disposed = False

    async def dispose() -> None:
        nonlocal disposed
        disposed = True

    app = main.create_app(Settings(_env_file=None))
    monkeypatch.setattr(app.state.database, "dispose", dispose)

    async with app.router.lifespan_context(app):
        assert disposed is False

    assert disposed is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code,headers",
    [
        (401, {"WWW-Authenticate": "Bearer"}),
        (429, {"Retry-After": "60"}),
    ],
)
async def test_http_exception_headers_are_preserved(code, headers):
    from fastapi import HTTPException

    app = main.create_app(Settings(_env_file=None))

    @app.get("/header-error")
    async def header_error():
        raise HTTPException(
            status_code=code, detail="Request rejected", headers=headers
        )

    async with get_client(app) as client:
        response = await client.get("/header-error")
        wrong_method = await client.post("/healthz")

    assert response.status_code == code
    for name, value in headers.items():
        assert response.headers[name] == value
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert wrong_method.status_code == 405
    assert "GET" in wrong_method.headers["Allow"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("https://app.example.com", True),
        ("https://other.example.com", False),
    ],
)
async def test_unhandled_errors_obey_cors_and_do_not_escape_to_server(origin, allowed):
    import io

    from sqlalchemy.exc import StatementError

    from src.core.logging import JsonFormatter

    app = main.create_app(
        Settings(
            cors_origins=["https://app.example.com"],
            cors_allow_credentials=True,
            _env_file=None,
        )
    )

    @app.get("/private-error")
    async def private_error():
        raise StatementError(
            "Failing row contains private-weight-101.25",
            "INSERT INTO logs VALUES (:weight)",
            {"weight": "private-weight-101.25"},
            ValueError("private-weight-101.25"),
        )

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("src")
    app_logger.addHandler(handler)
    try:
        # Raising transport proves no original exception escapes to server logging.
        async with get_client(app, raise_app_exceptions=True) as client:
            response = await client.get(
                "/private-error",
                headers={"Origin": origin, "X-Request-ID": "private-error-id"},
            )
    finally:
        app_logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": "private-error-id",
    }
    assert "private-weight" not in output.getvalue()
    assert "unhandled_exception" in output.getvalue()
    assert "StatementError" in output.getvalue()
    if allowed:
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    else:
        assert "Access-Control-Allow-Origin" not in response.headers
