"""Test muhiti: vaqtinchalik SQLite, in-memory Redis, bot o'chiq."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

_TMP = Path(tempfile.mkdtemp(prefix="adam-test-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "TELEGRAM_BOT_TOKEN": "123456:TEST-TOKEN",
        "GEMINI_API_KEY": "test-key",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
        "REDIS_URL": "",
        "ALLOW_DEV_AUTH": "false",
        "SESSION_TIMEOUT_SECONDS": "120",
        "WS_RATE_LIMIT_PER_MINUTE": "100",
        "FRONTEND_URL": "http://localhost:5173",
    }
)

import pytest  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app import models  # noqa: E402

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def make_init_data(
    user_id: int = 777,
    first_name: str = "Ali",
    *,
    auth_date: int | None = None,
    token: str = BOT_TOKEN,
    tamper: bool = False,
) -> str:
    """Telegram algoritmi bo'yicha imzolangan initData yaratadi."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": first_name, "username": "ali_test"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields["user"] = fields["user"].replace(first_name, first_name + "X")
    return urlencode(fields)


@pytest.fixture(scope="session", autouse=True)
async def _create_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables():
    yield
    async with SessionLocal() as db:
        for table in (
            models.Error, models.Vocabulary, models.Progress, models.Session,
            models.Payment, models.BotChat, models.User,
        ):
            await db.execute(delete(table))
        await db.commit()


@pytest.fixture
async def user_and_session():
    """DB da foydalanuvchi + ochiq sessiya yaratadi va SessionState qaytaradi."""
    from app.services.session_service import SessionState, create_session

    async with SessionLocal() as db:
        user = models.User(telegram_id=555, first_name="Vali", cefr_level="A1", level_progress=0)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        session = await create_session(db, user, "free")
    state = SessionState(
        session_id=session.id,
        user_id=user.id,
        user_name=user.first_name,
        level="A1",
        level_progress=0,
        mode="free",
        started_at=session.started_at,
    )
    return user, session, state
