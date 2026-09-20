import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.core.auth import Identity, resolve_user
from src.core.config import Settings
from src.core.database import Database
from src.models.user import ExternalIdentity, User

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_users_can_share_dates_but_never_access_each_others_logs(
    client: AsyncClient,
):
    first = await client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80}
    )
    assert first.status_code == 201
    log = first.json()
    url = f"/weight-logs/{log['id']}"
    client.headers["X-Test-Subject"] = "user_other"
    assert (await client.get("/weight-logs")).json() == []
    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"weight_kg": 70})).status_code == 404
    assert (await client.delete(url)).status_code == 404
    second = await client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 90}
    )
    assert second.status_code == 201
    assert (await client.get("/weight-logs")).json() == [second.json()]
    assert (
        await client.post("/weight-logs", json={"date": "2026-09-17", "weight_kg": 91})
    ).status_code == 409
    del client.headers["X-Test-Subject"]
    assert (await client.get("/weight-logs")).json() == [log]
    assert (await client.get(url)).json() == log


async def test_identity_mapping_is_stable_and_issuer_scoped(test_database_url):
    database = Database(Settings(database_url=test_database_url, _env_file=None))
    try:
        async with database.session_factory() as session:
            one = Identity("https://one.example", "same_subject")
            first = await resolve_user(session, one)
            assert await resolve_user(session, one) == first
            second = await resolve_user(
                session, Identity("https://two.example", "same_subject")
            )
            assert second != first
            assert (
                await session.scalar(select(User.id).where(User.id == first)) == first
            )
            assert (
                len(
                    list(
                        await session.scalars(
                            select(ExternalIdentity).where(
                                ExternalIdentity.subject == "same_subject"
                            )
                        )
                    )
                )
                == 2
            )
            await session.rollback()
    finally:
        await database.dispose()


async def test_claim_requires_existing_identity_and_is_idempotent(
    test_database_url, monkeypatch
):
    from datetime import date
    from decimal import Decimal
    from uuid import uuid4

    from sqlalchemy import delete

    from src import claim_legacy
    from src.models.weight_log import WeightLog

    settings = Settings(
        database_url=test_database_url,
        clerk_issuer="https://test.clerk.accounts.dev",
        _env_file=None,
    )
    monkeypatch.setattr(claim_legacy, "get_settings", lambda: settings)
    database = Database(settings)
    subject = f"user_{uuid4().hex}"
    user_id, identity_id, log_id = uuid4(), uuid4(), uuid4()
    try:
        async with database.session_factory() as session:
            session.add(User(id=user_id))
            await session.flush()
            session.add(
                ExternalIdentity(
                    id=identity_id,
                    user_id=user_id,
                    issuer=settings.clerk_issuer,
                    subject=subject,
                )
            )
            session.add(
                WeightLog(id=log_id, date=date(2098, 1, 1), weight_kg=Decimal("80.25"))
            )
            await session.commit()
        with pytest.raises(ValueError, match="Identity not found"):
            await claim_legacy.claim("user_unknown", True)
        assert await claim_legacy.claim(subject, False) == 1
        async with database.session_factory() as session:
            assert (await session.get(WeightLog, log_id)).user_id is None
        assert await claim_legacy.claim(subject, True) == 1
        assert await claim_legacy.claim(subject, True) == 0
        async with database.session_factory() as session:
            log = await session.get(WeightLog, log_id)
            assert log.user_id == user_id
            assert log.date == date(2098, 1, 1)
            assert log.weight_kg == Decimal("80.25")
    finally:
        async with database.session_factory() as session:
            await session.execute(delete(WeightLog).where(WeightLog.id == log_id))
            await session.execute(
                delete(ExternalIdentity).where(ExternalIdentity.id == identity_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await database.dispose()


async def test_signed_sessions_reach_database_and_enforce_ownership(test_database_url):
    from time import time
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from httpx import ASGITransport
    from sqlalchemy import delete

    from src.main import create_app
    from src.models.weight_log import WeightLog

    issuer = "https://signed.clerk.accounts.dev"
    settings = Settings(
        database_url=test_database_url,
        clerk_issuer=issuer,
        clerk_authorized_parties=["http://localhost:5173"],
        _env_file=None,
    )
    app = create_app(settings)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier._key = AsyncMock(
        return_value=jwt.PyJWK.from_json(
            jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())
        )
    )
    subjects = [f"user_{uuid4().hex}", f"user_{uuid4().hex}"]
    tokens = [
        jwt.encode(
            {
                "sub": subject,
                "sid": "sess_test",
                "iss": issuer,
                "azp": "http://localhost:5173",
                "iat": int(time()),
                "nbf": int(time()) - 1,
                "exp": int(time()) + 60,
            },
            key,
            algorithm="RS256",
            headers={"kid": "test"},
        )
        for subject in subjects
    ]
    async with app.router.lifespan_context(app):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as http:
                http.headers["Authorization"] = f"Bearer {tokens[0]}"
                created = await http.post(
                    "/weight-logs", json={"date": "2026-01-01", "weight_kg": 80}
                )
                assert created.status_code == 201
                log = created.json()
                http.headers["Authorization"] = f"Bearer {tokens[1]}"
                assert (await http.get("/weight-logs")).json() == []
                assert (await http.get(f"/weight-logs/{log['id']}")).status_code == 404
                assert (
                    await http.patch(
                        f"/weight-logs/{log['id']}", json={"weight_kg": 70}
                    )
                ).status_code == 404
                assert (
                    await http.delete(f"/weight-logs/{log['id']}")
                ).status_code == 404
                http.headers["Authorization"] = f"Bearer {tokens[0]}"
                assert (await http.get("/weight-logs")).json() == [log]
        finally:
            async with app.state.database.session_factory() as session:
                users = list(
                    await session.scalars(
                        select(ExternalIdentity.user_id).where(
                            ExternalIdentity.issuer == issuer,
                            ExternalIdentity.subject.in_(subjects),
                        )
                    )
                )
                await session.execute(
                    delete(WeightLog).where(WeightLog.user_id.in_(users))
                )
                await session.execute(
                    delete(ExternalIdentity).where(ExternalIdentity.user_id.in_(users))
                )
                await session.execute(delete(User).where(User.id.in_(users)))
                await session.commit()
