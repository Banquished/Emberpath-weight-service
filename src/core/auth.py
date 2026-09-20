import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Annotated
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.database import get_session
from src.models.user import ExternalIdentity, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str


def unauthorized() -> HTTPException:
    return HTTPException(
        401, "Invalid or missing session", headers={"WWW-Authenticate": "Bearer"}
    )


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.issuer = settings.clerk_issuer
        self.parties = settings.clerk_authorized_parties
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires = 0.0
        self._retry_after = 0.0
        self._lock = asyncio.Lock()

    async def _key(self, kid: str) -> jwt.PyJWK:
        async with self._lock:
            now = monotonic()
            if now >= self._expires or kid not in self._keys:
                if now >= self._retry_after:
                    self._retry_after = now + 30
                    try:
                        async with httpx.AsyncClient(
                            timeout=5, follow_redirects=False
                        ) as client:
                            response = await client.get(
                                f"{self.issuer}/.well-known/jwks.json"
                            )
                            response.raise_for_status()
                            key_set = jwt.PyJWKSet.from_dict(response.json())
                        self._keys = {
                            key.key_id: key
                            for key in key_set.keys
                            if key.key_id
                            and key.algorithm_name == "RS256"
                            and key.public_key_use in {None, "sig"}
                        }
                        self._expires = monotonic() + 300
                    except (
                        httpx.HTTPError,
                        ValueError,
                        TypeError,
                        KeyError,
                        jwt.PyJWTError,
                    ) as error:
                        raise HTTPException(
                            503, "Authentication temporarily unavailable"
                        ) from error
                if now >= self._expires:
                    raise HTTPException(503, "Authentication temporarily unavailable")
            key = self._keys.get(kid)
            if key is None:
                raise unauthorized()
            return key

    async def verify(self, token: str) -> Identity:
        if not self.issuer or not self.parties or "*" in self.parties:
            raise HTTPException(503, "Authentication is not configured")
        try:
            if len(token) > 16384:
                raise unauthorized()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise unauthorized()
            key = await self._key(kid)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"require": ["exp", "nbf", "iat", "iss", "sub", "azp", "sid"]},
            )
            subject = claims["sub"]
            if (
                not isinstance(subject, str)
                or not subject
                or len(subject) > 255
                or claims["azp"] not in self.parties
                or not isinstance(claims["sid"], str)
                or not claims["sid"]
                or claims.get("sts") == "pending"
            ):
                raise unauthorized()
            return Identity(self.issuer, subject)
        except (jwt.PyJWTError, ValueError, TypeError) as error:
            raise unauthorized() from error


async def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials is None:
        raise unauthorized()
    verifier: TokenVerifier = request.app.state.token_verifier
    return await verifier.verify(credentials.credentials)


async def resolve_user(session: AsyncSession, identity: Identity) -> UUID:
    query = select(ExternalIdentity.user_id).where(
        ExternalIdentity.issuer == identity.issuer,
        ExternalIdentity.subject == identity.subject,
    )
    user_id = await session.scalar(query)
    if user_id is not None:
        return user_id
    try:
        async with session.begin_nested():
            user = User()
            session.add(user)
            await session.flush()
            session.add(
                ExternalIdentity(
                    user_id=user.id, issuer=identity.issuer, subject=identity.subject
                )
            )
            await session.flush()
        return user.id
    except IntegrityError:
        user_id = await session.scalar(query)
        if user_id is None:
            raise
        return user_id


async def get_current_user(
    identity: Annotated[Identity, Depends(get_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UUID:
    user_id = await resolve_user(session, identity)
    await session.commit()
    return user_id


CurrentUser = Annotated[UUID, Depends(get_current_user)]
