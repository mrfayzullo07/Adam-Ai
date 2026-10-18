"""Async SQLAlchemy engine, sessiya fabrikasi va DB hayot sikli."""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Barcha ORM modellari uchun asos."""


def _engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False, "timeout": 30}, "poolclass": NullPool}
    connect_args: dict[str, Any] = {
        # Supabase/Neon pgbouncer (transaction mode) bilan prepared statement muammosini oldini oladi
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
    }
    if settings.database_requires_ssl:
        connect_args["ssl"] = "require"
    return {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "connect_args": connect_args,
    }


engine: AsyncEngine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Jadvallarni yaratadi (create_all) va ulanishni tekshiradi."""
    from app import models  # noqa: F401  (modellar Base.metadata ga ro'yxatdan o'tishi uchun)

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
    logger.info("Database tayyor: %s", engine.url.render_as_string(hide_password=True))


def _add_missing_columns(conn: Connection) -> None:
    """Yengil migratsiya: modelga qo'shilgan, lekin mavjud jadvalda yo'q ustunlarni ALTER TABLE bilan qo'shadi."""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            default = ""
            if col.server_default is not None and isinstance(col.server_default.arg, str):
                default = " DEFAULT '" + col.server_default.arg.replace("'", "''") + "'"
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col_type}{default}'))
            logger.info("Migratsiya: %s.%s ustuni qo'shildi", table.name, col.name)


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database ulanishi yopildi")


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: har so'rov uchun alohida sessiya."""
    async with SessionLocal() as session:
        yield session
