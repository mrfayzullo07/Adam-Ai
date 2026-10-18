"""Max tarifi: Adam'ni guruh va kanallarga qo'shish.

- Faqat Max tarifidagi foydalanuvchi qo'sha oladi, aks holda bot o'zi chiqib ketadi.
- Guruhda: @mention, Adam'ga reply yoki /adam buyrug'i bilan yozilgan matn/ovozli xabarga javob beradi.
- Kanalda: har kuni avtomatik dars (scheduler joylaydi).
- Egasining Max tarifi tugasa, guruhda javob bermaydi (kuniga bir marta ogohlantiradi).
"""
from __future__ import annotations

import io
import logging
import time
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import select

from app.bot.common import ensure_user
from app.config import settings
from app.database import SessionLocal
from app.gemini.text import GeminiTextError
from app.models import BotChat, User
from app.services import billing
from app.services.group_tutor import answer_group_message

logger = logging.getLogger(__name__)
router = Router(name="groups")

GROUP_TYPES = {"group", "supergroup"}
ACTIVE_STATUSES = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}
CHAT_COOLDOWN_SECONDS = 2.0
MAX_VOICE_SECONDS = 120
NOTICE_INTERVAL = timedelta(hours=24)

_last_reply: dict[int, float] = {}


async def _dm(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramAPIError:
        pass  # foydalanuvchi botga /start bosmagan bo'lishi mumkin


@router.my_chat_member(F.chat.type.in_(GROUP_TYPES | {"channel"}))
async def on_my_chat_member(event: ChatMemberUpdated, bot: Bot) -> None:
    chat = event.chat
    status = event.new_chat_member.status
    async with SessionLocal() as db:
        row = (await db.execute(select(BotChat).where(BotChat.chat_id == chat.id))).scalar_one_or_none()
        if status not in ACTIVE_STATUSES:
            if row is not None:
                row.active = False
                await db.commit()
            return

        adder = await ensure_user(db, event.from_user)
        plan = billing.effective_plan(adder)
        if not plan.groups:
            text = (
                "👑 Adam'ni guruh yoki kanalga qo'shish faqat <b>Max</b> tarifida mumkin.\n"
                "Tariflar: botga /tarif deb yozing."
            )
            if chat.type in GROUP_TYPES:
                try:
                    await bot.send_message(chat.id, text)
                except TelegramAPIError:
                    pass
            await _dm(bot, event.from_user.id, text)
            try:
                await bot.leave_chat(chat.id)
            except TelegramAPIError:
                pass
            return

        if row is None:
            row = BotChat(chat_id=chat.id, chat_type=chat.type, owner_user_id=adder.id)
            db.add(row)
        row.chat_type = chat.type
        row.title = (chat.title or "")[:256]
        row.owner_user_id = adder.id
        row.active = True
        await db.commit()

    me = await bot.me()
    if chat.type in GROUP_TYPES:
        try:
            await bot.send_message(
                chat.id,
                "👋 Salom! Men <b>Adam</b> — ingliz tili repetitoriman.\n\n"
                f"Savol berish uchun xabarda @{me.username} deb yozing yoki mening xabarimga reply qiling.\n"
                "Men tarjima qilaman, xatolarni tuzataman va tushuntiraman. Ovozli xabar ham yuborishingiz mumkin 🎤",
            )
        except TelegramAPIError:
            pass
        await _dm(bot, event.from_user.id, f"✅ Adam «{escape(chat.title or 'guruh')}» guruhiga ulandi.")
    else:
        hint = (
            ""
            if status == ChatMemberStatus.ADMINISTRATOR
            else "\n⚠️ Postlar joylashi uchun Adam'ni kanalga <b>admin</b> qiling (xabar joylash huquqi bilan)."
        )
        await _dm(
            bot,
            event.from_user.id,
            f"✅ Adam «{escape(chat.title or 'kanal')}» kanaliga ulandi.\n"
            f"Har kuni soat {settings.DAILY_LESSON_HOUR:02d}:00 da kunlik dars joylanadi.{hint}",
        )


@router.message(F.chat.type.in_(GROUP_TYPES), F.migrate_to_chat_id)
async def on_migrate(message: Message) -> None:
    """Guruh supergroup'ga aylanganda chat_id o'zgaradi."""
    async with SessionLocal() as db:
        row = (await db.execute(select(BotChat).where(BotChat.chat_id == message.chat.id))).scalar_one_or_none()
        if row is not None and message.migrate_to_chat_id:
            row.chat_id = message.migrate_to_chat_id
            row.chat_type = "supergroup"
            await db.commit()


def _strip_mention(text: str, username: str) -> str:
    out = text
    for variant in (f"@{username}", f"@{username.lower()}"):
        out = out.replace(variant, " ")
    if out.lstrip().lower().startswith("/adam"):
        out = out.lstrip()[5:]
        if out.startswith("@"):
            out = out.split(" ", 1)[1] if " " in out else ""
    return " ".join(out.split())


@router.message(F.chat.type.in_(GROUP_TYPES))
async def on_group_message(message: Message, bot: Bot) -> None:
    me = await bot.me()
    username = me.username or ""
    text = message.text or message.caption or ""
    replied = message.reply_to_message
    reply_to_bot = bool(replied and replied.from_user and replied.from_user.id == me.id)
    mentioned = bool(username) and f"@{username.lower()}" in text.lower()
    command = text.lstrip().lower().startswith("/adam")
    if not (reply_to_bot or mentioned or command):
        return

    async with SessionLocal() as db:
        row = (await db.execute(select(BotChat).where(BotChat.chat_id == message.chat.id))).scalar_one_or_none()
        owner = await db.get(User, row.owner_user_id) if row is not None else None
        allowed = bool(row and row.active and owner and billing.effective_plan(owner).groups)
        if not allowed:
            now = billing.utcnow()
            last = billing._utc(row.notice_sent_at) if row is not None else None
            if row is not None and (last is None or now - last > NOTICE_INTERVAL):
                row.notice_sent_at = now
                await db.commit()
                await message.reply(
                    "⏸ Adam bu guruhda vaqtincha ishlamayapti: guruh egasining 👑 Max tarifi faol emas."
                )
            return

    now_m = time.monotonic()
    if now_m - _last_reply.get(message.chat.id, 0) < CHAT_COOLDOWN_SECONDS:
        return
    _last_reply[message.chat.id] = now_m

    question = _strip_mention(text, username)
    voice_bytes: bytes | None = None
    voice_src = message.voice or (replied.voice if (replied and (mentioned or command)) else None)
    if voice_src is not None:
        if (voice_src.duration or 0) > MAX_VOICE_SECONDS:
            await message.reply(f"Ovozli xabar {MAX_VOICE_SECONDS // 60} daqiqadan oshmasin 🙏")
            return
        buf = io.BytesIO()
        try:
            await bot.download(voice_src.file_id, destination=buf)
            voice_bytes = buf.getvalue()
        except TelegramAPIError:
            voice_bytes = None

    context = None
    if replied is not None and not reply_to_bot:
        context = replied.text or replied.caption
    elif reply_to_bot and replied is not None:
        context = replied.text

    if not question and voice_bytes is None and not context:
        await message.reply("Savolingizni yozing yoki ovozli xabar yuboring 🙂", parse_mode=None)
        return
    if not question and context and voice_bytes is None:
        question = "Shu xabarni tushuntirib bering / tarjima qiling va xatolarini tuzating."

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except TelegramAPIError:
        pass
    asker = message.from_user.first_name if message.from_user else ""
    try:
        answer = await answer_group_message(question, context=context, voice=voice_bytes, asker=asker)
    except GeminiTextError as exc:
        logger.error("Guruh javobi xato: %s", exc)
        answer = "Hozir javob bera olmadim, birozdan so'ng qayta urinib ko'ring 🙏"
    await message.reply(answer[:4000], parse_mode=None)
