from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import Settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings: Settings) -> None:
        self._database_url = (
            str(settings.database_url) if settings.database_url else None
        )
        self._connect_timeout_seconds = settings.database_connect_timeout_seconds
        self._pool_size = settings.database_pool_size
        self._max_overflow = settings.database_max_overflow
        self._pool_timeout_seconds = settings.database_pool_timeout_seconds
        self._pool_recycle_seconds = settings.database_pool_recycle_seconds
        self._pool_pre_ping = settings.database_pool_pre_ping
        self._statement_timeout_milliseconds = (
            settings.database_statement_timeout_seconds * 1000
        )
        self._lock_timeout_milliseconds = settings.database_lock_timeout_seconds * 1000
        self._idle_transaction_timeout_milliseconds = (
            settings.database_idle_transaction_timeout_seconds * 1000
        )
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def database_url(self) -> str:
        if self._database_url is None:
            raise RuntimeError(
                "Set DATABASE_URL before using the database or migrations"
            )
        return self._database_url

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self.database_url,
                hide_parameters=True,
                connect_args={
                    "connect_timeout": self._connect_timeout_seconds,
                    "options": (
                        f"-c statement_timeout={self._statement_timeout_milliseconds} "
                        f"-c lock_timeout={self._lock_timeout_milliseconds} "
                        "-c idle_in_transaction_session_timeout="
                        f"{self._idle_transaction_timeout_milliseconds}"
                    ),
                },
                max_overflow=self._max_overflow,
                pool_pre_ping=self._pool_pre_ping,
                pool_recycle=self._pool_recycle_seconds,
                pool_size=self._pool_size,
                pool_timeout=self._pool_timeout_seconds,
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine, expire_on_commit=False
            )
        return self._session_factory

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._session_factory = None
        self._engine = None


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session_factory() as session:
        yield session
