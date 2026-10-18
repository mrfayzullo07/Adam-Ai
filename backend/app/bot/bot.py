"""Bot hayot sikli: development'da polling, production'da webhook."""
from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, MenuButtonWebApp, Update, WebAppInfo
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.bot.admin import router as admin_router
from app.bot.groups import router as groups_router
from app.bot.handlers import router as handlers_router
from app.bot.payments import router as payments_router
from app.config import settings

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"
webhook_router = APIRouter(tags=["telegram"])

_bot: Bot | None = None
_dp: Dispatcher | None = None
_polling_task: asyncio.Task[None] | None = None
_webhook_secret: str = settings.WEBHOOK_SECRET or secrets.token_urlsafe(32)


def _build() -> tuple[Bot, Dispatcher]:
    bot = Bot(settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Tartib muhim: handlers'dagi umumiy fallback eng oxirida turadi
    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(groups_router)
    dp.include_router(handlers_router)
    return bot, dp


def get_bot() -> Bot | None:
    return _bot


async def get_bot_username() -> str | None:
    if _bot is None:
        return None
    try:
        return (await _bot.me()).username
    except Exception:  # noqa: BLE001
        return None


async def _configure_bot(bot: Bot) -> None:
    """Buyruqlar ro'yxati va menyu tugmasini sozlaydi (xato bo'lsa ham ishlashda davom etadi)."""
    user_commands = [
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="tarif", description="Tariflar va to'lov"),
        BotCommand(command="mening", description="Tarifim va qolgan vaqt"),
        BotCommand(command="help", description="Yordam"),
    ]
    admin_commands = [
        BotCommand(command="admin", description="🛠 Admin panel"),
        BotCommand(command="stats", description="📊 Statistika"),
        BotCommand(command="users", description="👥 Foydalanuvchilar"),
        BotCommand(command="subs", description="💎 Obunachilar"),
        BotCommand(command="pending", description="🧾 Tekshiruvdagi to'lovlar"),
        BotCommand(command="user", description="🔎 Foydalanuvchini topish"),
        BotCommand(command="grant", description="🎁 Tarif berish"),
    ]
    try:
        await bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
        for admin_id in settings.admin_ids:
            try:
                await bot.set_my_commands(admin_commands + user_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:  # noqa: BLE001
                logger.warning("Admin %s uchun buyruqlar menyusi o'rnatilmadi", admin_id)
        await bot.set_my_commands([BotCommand(command="adam", description="Adam'ga savol berish")])
        if settings.WEBAPP_URL.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🎤 Adam", web_app=WebAppInfo(url=settings.WEBAPP_URL))
            )
    except Exception:  # noqa: BLE001
        logger.exception("Bot buyruqlari/menyu tugmasini sozlashda xato")


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Polling to'xtadi")


async def start_bot() -> None:
    """Rejimga qarab botni ishga tushiradi."""
    global _bot, _dp, _polling_task
    mode = settings.effective_bot_mode
    if mode == "disabled":
        logger.info("Bot o'chirilgan (token yo'q yoki BOT_MODE=disabled)")
        return

    _bot, _dp = _build()
    await _configure_bot(_bot)

    if mode == "webhook":
        if not settings.BACKEND_URL.startswith("https://"):
            logger.error("Webhook uchun BACKEND_URL https:// bo'lishi kerak — bot ishga tushmadi")
            return
        url = settings.BACKEND_URL + WEBHOOK_PATH
        await _bot.set_webhook(
            url,
            secret_token=_webhook_secret,
            allowed_updates=_dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        logger.info("Webhook o'rnatildi: %s", url)
    else:
        _polling_task = asyncio.create_task(_run_polling(_bot, _dp), name="bot-polling")
        logger.info("Bot polling rejimida ishga tushdi")


async def stop_bot() -> None:
    """Polling'ni to'xtatadi va bot sessiyasini yopadi."""
    global _bot, _dp, _polling_task
    if _polling_task is not None and _dp is not None:
        try:
            await _dp.stop_polling()
        except Exception:  # noqa: BLE001
            pass
        _polling_task.cancel()
        try:
            await _polling_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _polling_task = None
    if _bot is not None:
        await _bot.session.close()
    _bot = None
    _dp = None
    logger.info("Bot to'xtatildi")


@webhook_router.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    """Telegram update'larini qabul qiladi (faqat to'g'ri secret token bilan)."""
    if _bot is None or _dp is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not x_telegram_bot_api_secret_token or not secrets.compare_digest(x_telegram_bot_api_secret_token, _webhook_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    try:
        update = Update.model_validate(await request.json(), context={"bot": _bot})
        await _dp.feed_update(_bot, update)
    except Exception:  # noqa: BLE001
        logger.exception("Webhook update'ni qayta ishlashda xato")
    return {"ok": True}
