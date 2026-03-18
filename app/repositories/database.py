from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """
    Returns the engine, creating it on the first call (lazy initialization).

    Decision: lazy initialization prevents the module import from attempting to connect
    to the database immediately. This is especially important in unit tests
    that do not need a database, the engine is only created when
    get_session() or async_session_factory() are actually called.
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_size=20,
            max_overflow=10,
            echo=False,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the session factory, creating it on the first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency injection for database session.

    Uses a context manager to ensure the session is closed
    even in case of an exception.

    Yields:
        Async SQLAlchemy session.
    """
    async with _get_session_factory()() as session:
        yield session


@asynccontextmanager
async def async_session_factory() -> AsyncGenerator[AsyncSession, None]:
    """
    Session context manager for use outside of FastAPI (e.g. worker).

    Exemplo de uso:
        async with async_session_factory() as session:
            ...
    """
    async with _get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    """Closes all connections in the pool. Called on application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
