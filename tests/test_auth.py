from time import time
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.core.auth import Identity, TokenVerifier
from src.core.config import Settings
from src.main import create_app

ISSUER = "https://test.clerk.accounts.dev"
PARTY = "http://localhost:5173"
pytestmark = pytest.mark.anyio


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def claims():
    return {
        "iss": ISSUER,
        "sub": "user_one",
        "sid": "sess_one",
        "azp": PARTY,
        "iat": int(time()),
        "nbf": int(time()) - 1,
        "exp": int(time()) + 60,
    }


@pytest.fixture
def verifier(signing_key):
    verifier = TokenVerifier(
        Settings(clerk_issuer=ISSUER, clerk_authorized_parties=[PARTY], _env_file=None)
    )
    verifier._key = AsyncMock(
        return_value=jwt.PyJWK.from_json(
            jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key())
        )
    )
    return verifier


def token(key, claims):
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


async def test_valid_session(verifier, signing_key, claims):
    assert await verifier.verify(token(signing_key, claims)) == Identity(
        ISSUER, "user_one"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "https://attacker.test"),
        ("azp", "https://attacker.test"),
        ("exp", 1),
        ("nbf", 9999999999),
        ("iat", 9999999999),
        ("sub", ""),
        ("sid", ""),
    ],
)
async def test_rejects_invalid_claims(verifier, signing_key, claims, field, value):
    claims[field] = value
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token(signing_key, claims))
    assert error.value.status_code == 401


@pytest.mark.parametrize("field", ["iss", "sub", "sid", "azp", "exp", "nbf", "iat"])
async def test_rejects_missing_claims(verifier, signing_key, claims, field):
    del claims[field]
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token(signing_key, claims))
    assert error.value.status_code == 401


async def test_rejects_wrong_signature(verifier, claims):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token(other_key, claims))
    assert error.value.status_code == 401


async def test_rejects_hmac_without_fetching_keys(verifier, claims):
    with pytest.raises(HTTPException) as error:
        await verifier.verify(
            jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": "test"})
        )
    assert error.value.status_code == 401
    verifier._key.assert_not_called()


async def test_routes_require_auth_but_health_is_public():
    application = create_app(Settings(_env_file=None))
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for method, path in [
            ("get", "/weight-logs"),
            ("get", "/weight-logs/export"),
            ("post", "/weight-logs/import/preview"),
            ("post", "/weight-logs/import"),
            ("get", "/weight-goals/active"),
            ("put", "/weight-goals/active"),
            ("patch", "/weight-goals/not-an-id"),
            ("post", "/weight-logs"),
            ("get", "/weight-logs/not-an-id"),
            ("patch", "/weight-logs/not-an-id"),
            ("delete", "/weight-logs/not-an-id"),
        ]:
            response = await client.request(method, path)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/")).status_code == 200
        assert (
            await client.get("/weight-logs", headers={"Authorization": "Bearer token"})
        ).status_code == 503


async def test_malformed_numeric_date_is_unauthorized(verifier, signing_key, claims):
    claims["exp"] = []
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token(signing_key, claims))
    assert error.value.status_code == 401


async def test_pending_session_is_unauthorized(verifier, signing_key, claims):
    claims["sts"] = "pending"
    with pytest.raises(HTTPException) as error:
        await verifier.verify(token(signing_key, claims))
    assert error.value.status_code == 401


async def test_jwks_cache_rotation_and_unknown_key_rate_limit(
    signing_key, claims, monkeypatch
):
    import json

    import httpx

    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update(kid="test", alg="RS256", use="sig")
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"keys": [jwk]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    verifier = TokenVerifier(
        Settings(clerk_issuer=ISSUER, clerk_authorized_parties=[PARTY], _env_file=None)
    )
    for _ in range(2):
        assert await verifier.verify(token(signing_key, claims)) == Identity(
            ISSUER, "user_one"
        )
    assert calls == [f"{ISSUER}/.well-known/jwks.json"]
    unknown = jwt.encode(
        claims, signing_key, algorithm="RS256", headers={"kid": "unknown"}
    )
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await verifier.verify(unknown)
        assert error.value.status_code == 401
    assert len(calls) == 1
    jwk["kid"] = "unknown"
    verifier._retry_after = 0
    assert await verifier.verify(unknown) == Identity(ISSUER, "user_one")
    assert len(calls) == 2


async def test_jwks_outage_fails_closed_and_backs_off(signing_key, claims, monkeypatch):
    import httpx

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    verifier = TokenVerifier(
        Settings(clerk_issuer=ISSUER, clerk_authorized_parties=[PARTY], _env_file=None)
    )
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await verifier.verify(token(signing_key, claims))
        assert error.value.status_code == 503
    assert len(calls) == 1


def test_auth_config_empty_issuer_and_explicit_origins():
    from pydantic import ValidationError

    assert Settings(clerk_issuer="", _env_file=None).clerk_issuer is None
    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(clerk_authorized_parties=["*"], _env_file=None)
