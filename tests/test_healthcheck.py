from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.core.config import Settings
from src.core.healthcheck import check_health, healthcheck_host


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("allowed_hosts", "expected_host"),
    [
        (["api.example.com"], "api.example.com"),
        (["*.example.com"], "healthcheck.example.com"),
        (["*"], "127.0.0.1"),
        (["localhost", "api.example.com"], "localhost"),
    ],
)
async def test_probe_host_matches_trusted_host_rules(allowed_hosts, expected_host):
    settings = Settings(_env_file=None, allowed_hosts=allowed_hosts)
    host = healthcheck_host(settings)
    assert host == expected_host

    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz", headers={"Host": host})

    assert response.status_code == 200


def test_probe_connects_to_loopback_with_production_host():
    settings = Settings(
        _env_file=None,
        environment="production",
        allowed_hosts=["api.example.com"],
    )
    with patch("src.core.healthcheck.HTTPConnection") as connection_class:
        connection = connection_class.return_value
        connection.getresponse.return_value.status = 200
        check_health(settings)

    connection_class.assert_called_once_with("127.0.0.1", 8000, timeout=3)
    connection.request.assert_called_once_with(
        "GET", "/healthz", headers={"Host": "api.example.com"}
    )
    connection.close.assert_called_once()


def test_probe_rejects_unhealthy_response():
    with patch("src.core.healthcheck.HTTPConnection") as connection_class:
        connection = connection_class.return_value
        connection.getresponse.return_value.status = 503
        with pytest.raises(RuntimeError, match="HTTP 503"):
            check_health(Settings(_env_file=None))
    connection.close.assert_called_once()


def test_probe_propagates_connection_failure_and_closes_connection():
    with patch("src.core.healthcheck.HTTPConnection") as connection_class:
        connection = connection_class.return_value
        connection.request.side_effect = ConnectionRefusedError
        with pytest.raises(ConnectionRefusedError):
            check_health(Settings(_env_file=None))
    connection.close.assert_called_once()


def test_probe_rejects_empty_allowed_hosts():
    with pytest.raises(ValueError, match="ALLOWED_HOSTS must not be empty"):
        healthcheck_host(Settings(_env_file=None, allowed_hosts=[]))
