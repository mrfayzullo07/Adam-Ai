"""FastAPI ilovasi: CORS, routerlar, hayot sikli (DB + Redis + bot)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, progress, ws
from app.bot.bot import get_bot, start_bot, stop_bot, webhook_router
from app.config import settings
from app.database import close_db, init_db
from app.redis_client import close_redis, init_redis
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# Juda shovqinli kutubxonalar
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger("adam")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: DB, Redis, bot. Shutdown: teskari tartibda yopish."""
    logger.info("Adam ishga tushmoqda (env=%s, bot=%s)", settings.ENVIRONMENT, settings.effective_bot_mode)
    await init_db()
    await init_redis()
    try:
        await start_bot()
    except Exception:  # noqa: BLE001
        logger.exception("Botni ishga tushirib bo'lmadi — API ishlashda davom etadi")
    bot = get_bot()
    if bot is not None:
        start_scheduler(bot)
    try:
        yield
    finally:
        await stop_scheduler()
        await stop_bot()
        await close_redis()
        await close_db()
        logger.info("Adam to'xtatildi")


app = FastAPI(title="Adam API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Telegram-Init-Data"],
    max_age=600,
)

app.include_router(auth.router)
app.include_router(progress.router)
app.include_router(ws.router)
app.include_router(webhook_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
