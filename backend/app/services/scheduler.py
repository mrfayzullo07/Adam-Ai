"""Fon vazifalari (har daqiqada):
  1. Free limiti yangilangan foydalanuvchilarga xabar (faqat limitga yetganlarga, Pro/Max'ga emas).
  2. Pullik tarif tugashidan 3 kun oldin eslatma; tugaganda Free'ga o'tkazish va xabar.
  3. Max egalarining kanallariga kunlik dars.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from app.bot.common import webapp_button
from app.config import settings
from app.database import SessionLocal
from app.gemini.text import GeminiTextError
from app.models import BotChat, User
from app.services import billing
from app.services.group_tutor import generate_daily_lesson

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
REMIND_BEFORE = timedelta(days=3)
SEND_PAUSE = 0.05

_task: asyncio.Task[None] | None = None
_lesson_cache: dict[date, str] = {}


def _kb(*, plans: bool) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    btn = webapp_button()
    if btn is not None:
        rows.append([btn])
    if plans:
        rows.append([InlineKeyboardButton(text="💎 Tariflar", callback_data="plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _send(bot: Bot, chat_id: int, text: str, kb: InlineKeyboardMarkup | None = None) -> bool:
    """Yuborildimi? Bloklangan foydalanuvchi uchun False (qayta urinilmaydi)."""
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        await asyncio.sleep(SEND_PAUSE)
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        return await _send(bot, chat_id, text, kb)
    except TelegramForbiddenError:
        return False
    except TelegramAPIError as exc:
        logger.warning("Xabar yuborilmadi (%s): %s", chat_id, exc)
        return False


async def notify_limit_renewed(bot: Bot, now: datetime) -> None:
    async with SessionLocal() as db:
        users = (await db.execute(select(User).where(User.limit_notify.is_(True)))).scalars().all()
        for u in users:
            plan = billing.effective_plan(u, now)
            if plan.code != "free":
                u.limit_notify = False  # Pro/Max'ga bunday xabar shart emas
                continue
            if billing.get_quota(u, now).exhausted:
                continue
            u.limit_notify = False
            await _send(
                bot,
                u.telegram_id,
                "⏰ <b>Limitingiz yangilandi!</b>\n"
                f"Adam bilan yana {billing.format_duration_uz(plan.limit_seconds or 0)} gaplasha olasiz 🎤\n\n"
                f"💎 Pro tarifida har {billing.PLANS['pro'].window_hours} soatda "
                f"{billing.format_duration_uz(billing.PLANS['pro'].limit_seconds or 0)} — "
                f"{billing.format_price(billing.PLANS['pro'].price)}.",
                _kb(plans=True),
            )
        await db.commit()


async def handle_plan_expiry(bot: Bot, now: datetime) -> None:
    async with SessionLocal() as db:
        users = (
            await db.execute(select(User).where(User.plan != "free", User.plan_expires_at.is_not(None)))
        ).scalars().all()
        for u in users:
            exp = billing._utc(u.plan_expires_at)
            assert exp is not None
            title = billing.PLANS.get(u.plan, billing.PLANS["free"]).title
            if exp <= now:
                u.plan = "free"
                u.plan_expires_at = None
                u.plan_reminded = False
                u.usage_window_start = None
                u.usage_seconds = 0
                await _send(
                    bot,
                    u.telegram_id,
                    f"⌛️ <b>{title}</b> tarifingiz muddati tugadi va siz Free tarifiga o'tdingiz.\n"
                    "Davom ettirish uchun tarifni yangilang 👇",
                    _kb(plans=True),
                )
            elif not u.plan_reminded and exp - now <= REMIND_BEFORE:
                u.plan_reminded = True
                await _send(
                    bot,
                    u.telegram_id,
                    f"🔔 <b>{title}</b> tarifingiz {exp.astimezone(settings.local_tz):%d.%m.%Y %H:%M} da tugaydi.\n"
                    "Uzilishsiz davom etish uchun oldindan yangilab qo'ying — muddat ustiga qo'shiladi.",
                    _kb(plans=True),
                )
        await db.commit()


async def post_daily_lessons(bot: Bot, now: datetime) -> None:
    local = now.astimezone(settings.local_tz)
    if local.hour < settings.DAILY_LESSON_HOUR:
        return
    today = local.date()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(BotChat).where(
                    BotChat.chat_type == "channel",
                    BotChat.active.is_(True),
                    BotChat.daily_lessons.is_(True),
                )
            )
        ).scalars().all()
        due = [r for r in rows if r.last_lesson_date != today]
        if not due:
            return
        text = _lesson_cache.get(today)
        if text is None:
            try:
                me = await bot.me()
                text = await generate_daily_lesson(today, me.username)
            except (GeminiTextError, ValueError) as exc:
                logger.error("Kunlik dars yaratilmadi: %s", exc)
                return
            _lesson_cache.clear()
            _lesson_cache[today] = text
        for row in due:
            owner = await db.get(User, row.owner_user_id)
            if owner is None or not billing.effective_plan(owner, now).groups:
                continue
            try:
                await bot.send_message(row.chat_id, text)
                row.last_lesson_date = today
            except TelegramForbiddenError:
                row.active = False
            except TelegramAPIError as exc:
                logger.warning("Kanalga dars joylanmadi (%s): %s", row.chat_id, exc)
                row.last_lesson_date = today  # bir kunda qayta-qayta urinmaslik
            await asyncio.sleep(SEND_PAUSE)
        await db.commit()


async def run_once(bot: Bot) -> None:
    now = billing.utcnow()
    for job in (notify_limit_renewed, handle_plan_expiry, post_daily_lessons):
        try:
            await job(bot, now)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduler vazifasi xato: %s", job.__name__)


async def _loop(bot: Bot) -> None:
    while True:
        await run_once(bot)
        await asyncio.sleep(TICK_SECONDS)


def start_scheduler(bot: Bot) -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_loop(bot), name="adam-scheduler")
        logger.info("Scheduler ishga tushdi")


async def stop_scheduler() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _task = None
