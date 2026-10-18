"""Telegram Mini App initData validatsiyasi (HMAC-SHA256) va auth dependency.

Algoritm (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in fields if k != "hash"))
  hash == hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, utcnow
from app.schemas import TelegramUser, UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["auth"])


class InitDataError(Exception):
    """initData yaroqsiz bo'lganda ko'tariladi."""


def validate_init_data(init_data: str, bot_token: str, max_age: int | None = None) -> TelegramUser:
    """initData satrini tekshiradi va Telegram foydalanuvchisini qaytaradi.

    Raises:
        InitDataError: hash mos kelmasa, eskirgan bo'lsa yoki `user` yo'q bo'lsa.
    """
    if not init_data:
        raise InitDataError("initData bo'sh")
    if not bot_token:
        raise InitDataError("Server bot tokeni sozlanmagan")

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError("initData formati noto'g'ri") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash yo'q")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("hash mos kelmadi")

    if max_age is not None:
        try:
            auth_date = int(pairs.get("auth_date", "0"))
        except ValueError as exc:
            raise InitDataError("auth_date noto'g'ri") from exc
        if auth_date <= 0 or time.time() - auth_date > max_age:
            raise InitDataError("initData eskirgan")

    raw_user = pairs.get("user")
    if not raw_user:
        raise InitDataError("user maydoni yo'q")
    try:
        return TelegramUser.model_validate(json.loads(raw_user))
    except (ValueError, TypeError) as exc:
        raise InitDataError("user maydoni noto'g'ri") from exc


def parse_auth(init_data: str) -> TelegramUser:
    """Prod: HMAC tekshiruvi. Dev (ALLOW_DEV_AUTH): `dev:<telegram_id>` ham qabul qilinadi."""
    if settings.dev_auth_enabled and init_data.startswith("dev:"):
        try:
            tg_id = int(init_data.split(":", 1)[1])
        except ValueError as exc:
            raise InitDataError("dev initData noto'g'ri") from exc
        return TelegramUser(id=tg_id, first_name="Dev", username="dev_user")
    return validate_init_data(init_data, settings.TELEGRAM_BOT_TOKEN, settings.INIT_DATA_MAX_AGE)


async def upsert_user(db: AsyncSession, tg: TelegramUser) -> User:
    """Foydalanuvchini telegram_id bo'yicha topadi yoki yaratadi, ma'lumotlarini yangilaydi."""
    user = (await db.execute(select(User).where(User.telegram_id == tg.id))).scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=tg.id,
            username=tg.username,
            first_name=tg.first_name or "",
            language="uz",
        )
        db.add(user)
    else:
        user.username = tg.username
        if tg.first_name:
            user.first_name = tg.first_name
        user.last_active_at = utcnow()
    await db.commit()
    await db.refresh(user)
    return user


def _extract_init_data(authorization: str | None, x_init_data: str | None) -> str:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "tma" and value:
            return value.strip()
    if x_init_data:
        return x_init_data.strip()
    return ""


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> User:
    """Har bir himoyalangan API uchun majburiy dependency.

    Header: `Authorization: tma <initData>` (yoki `X-Telegram-Init-Data`).
    """
    raw = _extract_init_data(authorization, x_telegram_init_data)
    try:
        tg_user = parse_auth(raw)
    except InitDataError as exc:
        logger.info("Auth rad etildi: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData") from exc
    return await upsert_user(db, tg_user)


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/auth", response_model=UserOut)
async def auth(user: CurrentUser) -> User:
    """initData ni tekshiradi va foydalanuvchi ma'lumotlarini qaytaradi."""
    return user
