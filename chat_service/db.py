"""Chat bazasiga ulanish.

Engine LAZY yaratiladi (support'dan farqi): testlar `init_engine()` bilan SQLite
(`aiosqlite`) beradi, prod esa `CHAT_DB_URL` dagi Postgres'ni. Import paytida
engine yaratilsa, testda ham asyncpg drayveri va real baza talab qilinardi.
"""

from __future__ import annotations

from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from chat_service.config import CHAT_DB_URL

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def init_engine(url: str = CHAT_DB_URL) -> AsyncEngine:
    global _engine, _sessionmaker
    kwargs: dict = {"echo": False}
    if url.startswith("postgresql"):
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
